# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Judgment-generation service layer.

Composition logic for turning a ``judgment_lists`` row into persisted
``judgments`` — shared by the LLM judge worker (``workers.judgments``) and
the UBI worker (``workers.judgments_ubi``). The workers own orchestration
(load the row, build clients, loop queries, flip terminal status, clean up);
this module owns the per-list/per-query composition of repos + adapter + LLM
+ budget so that logic lives in the service layer rather than the worker.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import openai
import structlog
import uuid_utils
from openai import AsyncOpenAI
from redis.asyncio import Redis

from backend.app.adapters.protocol import NativeQuery, QueryTemplate
from backend.app.db import repo
from backend.app.domain.study.template_defaults import compute_default_params
from backend.app.llm.budget_gate import BudgetExceededError, peek_daily_total, safe_record_cost
from backend.app.llm.cost_model import estimated_max_call_cost
from backend.app.llm.openai_judge import rate_query_batch
from backend.app.llm.prompt_loader import render_user_prompt

logger = structlog.get_logger(__name__)


TOP_K = 50
"""Retrieval depth per query (per spec §13 cost guardrail).

50 is the design target: enough docs to give the LLM useful relevance
contrast across the rubric scale, low enough that one call per query keeps
the tutorial cost under $1."""

_DOC_BODY_CHAR_LIMIT = 500
"""Per-doc body truncation length (per spec §13).

Bounds the input token count; only the first 500 chars of each doc body are
passed to the LLM. The doc body is just for the rubric judgment, not for
retrieval — full-text retention isn't needed."""


def _build_doc_inputs(hits: Sequence[Any]) -> list[dict[str, str]]:
    """Translate ``ScoredHit`` rows into ``[{doc_id, body}, ...]`` for the prompt.

    Body extraction prefers ``hit.source.body`` (the canonical text field);
    falls back to a JSON-dumped ``hit.source`` when absent. The result is
    trimmed to :data:`_DOC_BODY_CHAR_LIMIT` characters per doc.
    """
    out: list[dict[str, str]] = []
    for hit in hits:
        source = getattr(hit, "source", None) or {}
        body_raw = source.get("body") if isinstance(source, dict) else None
        if not body_raw:
            # Fall back to a stable string form of the source. ``source`` is
            # engine ``_source`` (always JSON-origin in practice), but guard the
            # dump anyway now that this helper is service-layer: a future caller
            # could pass a hit whose source holds a non-serializable value, and
            # a TypeError here would abort the whole judgment run.
            import json as _json

            try:
                body_raw = _json.dumps(source, ensure_ascii=False)
            except TypeError:
                body_raw = str(source)
        body = str(body_raw)
        if len(body) > _DOC_BODY_CHAR_LIMIT:
            body = body[:_DOC_BODY_CHAR_LIMIT]
        out.append({"doc_id": str(hit.doc_id), "body": body})
    return out


async def fail_judgment_list(db: Any, judgment_list_id: str, failed_reason: str) -> None:
    """Flip a judgment list to ``status='failed'`` with a structured reason.

    Commits in the caller's session. Shared by both judgment workers — the
    terminal-failure transition is identical regardless of which generation
    path (LLM or UBI) hit the failure.
    """
    await repo.update_judgment_list_status(
        db, judgment_list_id, status="failed", failed_reason=failed_reason
    )
    await db.commit()


async def process_judgment_query(
    *,
    db: Any,
    redis: Redis,
    openai_client: AsyncOpenAI,
    judgment_list_id: str,
    judgment_list: Any,
    template: QueryTemplate,
    template_row: Any,
    query: Any,
    adapter: Any,
    bundle_system: str,
    rubric_text: str,
    model: str,
    budget_usd: float,
) -> bool:
    """Compose one query's judgment generation: budget → search → LLM → persist.

    Returns:
        ``True`` when judgments were persisted (success or already-judged
        resume-skip) and ``False`` when the query was skipped for any
        operational reason (search failed, LLM partial, empty hits).
        The worker loop uses this to decide whether to mark the list
        ``complete`` (all True) or ``failed`` with
        ``failed_reason='PARTIAL_LLM_FAILURE'`` (any False). Per GPT-5.5
        cycle-8 C8-F1 — without the tracking, a partial-LLM-response
        skip would leave the list ``complete`` with missing qrels and
        the resume sweep would never pick it back up.

    Raises on budget / pricing failures so the worker loop can mark the
    list ``failed`` with the specific reason.
    """
    # Resume-skip: if this query already has ANY judgments, the prior worker
    # pass either completed it OR was atomically rolled back. Because
    # bulk_create_judgments + commit happens in one transaction after the
    # LLM call, the only post-crash states are "0 rows" or "the full batch
    # returned by the LLM". A hardcoded ``existing >= TOP_K`` would fail for
    # queries that legitimately returned fewer than TOP_K hits (sparse
    # indices, tutorial-scale datasets) and would re-spend OpenAI dollars.
    # Per GPT-5.5 final review F2.
    existing = await repo.count_judgments_for_list_and_query(db, judgment_list_id, query.id)
    if existing > 0:
        logger.info(
            "query already judged, skipping",
            event_type="judgment_skip_resume",
            judgment_list_id=judgment_list_id,
            query_id=query.id,
            existing_count=existing,
        )
        return True

    # Pre-call budget peek (spec FR-2 + GPT-5.5 cycle 1 F8).
    if budget_usd > 0:
        current = await peek_daily_total(redis)
        est_max = estimated_max_call_cost(model)
        if current + est_max > budget_usd:
            raise BudgetExceededError(
                f"current ${current:.4f} + estimated ${est_max:.4f} > budget ${budget_usd:.4f}"
            )

    # Render template + execute search.
    default_params = compute_default_params(template_row)
    try:
        native = adapter.render(template, default_params, query.query_text)
        # Override the adapter-generated query_id with our own so the
        # search_batch response key matches what we expect.
        native = NativeQuery(query_id=str(query.id), body=native.body)
        hits_by_qid = await adapter.search_batch(
            target=judgment_list.target,
            queries=[native],
            top_k=TOP_K,
            strict_errors=False,
        )
    except Exception as exc:
        logger.warning(
            "judgment worker: search failed for query, skipping",
            event_type="judgment_search_failed",
            judgment_list_id=judgment_list_id,
            query_id=query.id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False

    hits = hits_by_qid.get(str(query.id), [])
    if not hits:
        # Zero hits: not a worker failure — there's genuinely nothing to
        # judge. Count this as success so the outer loop can still mark
        # the list complete. The downstream qrels_loader returns ``{}``
        # for queries with no judgments, which run_trial handles
        # gracefully.
        logger.info(
            "judgment worker: no hits for query, skipping LLM call",
            event_type="judgment_no_hits",
            judgment_list_id=judgment_list_id,
            query_id=query.id,
        )
        return True

    # Ordinal prompt-ids decouple engine-supplied doc_ids (which may contain
    # XML-sensitive chars like ``<``, ``&``, ``"``) from the LLM's
    # round-trippable identifier. Autoescape on the Jinja sandbox would
    # otherwise render ``<doc id="a&b">`` as ``<doc id="a&amp;b">`` — the
    # LLM would echo back ``a&amp;b`` and the worker's allowlist
    # (which has ``a&b``) would drop it as spurious, producing a permanent
    # zero-judgments outcome. Per GPT-5.5 cycle-6 C6-F1.
    raw_docs = _build_doc_inputs(hits)
    prompt_docs = [{"doc_id": f"item-{i}", "body": d["body"]} for i, d in enumerate(raw_docs)]
    prompt_id_to_real = {f"item-{i}": d["doc_id"] for i, d in enumerate(raw_docs)}
    expected_doc_ids = set(prompt_id_to_real.keys())

    user_prompt = render_user_prompt(
        rubric_text=rubric_text,
        query_text=query.query_text,
        docs=prompt_docs,
    )

    # Spec FR-3c: "The actual prompt sent to OpenAI MUST include this rubric
    # in full as part of the system prompt." We append the per-list rubric
    # to the operator-fixed system message so the rubric appears at the
    # top of the instruction hierarchy AND inside the user message's
    # <rubric> delimiter block (defense in depth).
    system_prompt = f"{bundle_system}\n\n<rubric>\n{rubric_text}\n</rubric>"

    try:
        result = await rate_query_batch(
            client=openai_client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_doc_ids=expected_doc_ids,
        )
    except (
        openai.AuthenticationError,
        openai.PermissionDeniedError,
        openai.BadRequestError,
        openai.NotFoundError,
    ):
        # Persistent provider misconfiguration (bad key, model id, endpoint,
        # ZDR enrollment denied, etc.). No subsequent query will succeed —
        # propagate so the outer handler marks the list failed with
        # ``failed_reason='UNEXPECTED:<ErrorType>'`` rather than silently
        # producing a `complete` list with zero judgments. Per GPT-5.5
        # cycle-2 C2-F1.
        raise
    except Exception as exc:
        # Per-query operational failure (rate-limit exhaustion after retries,
        # 5xx after retries, malformed JSON after retries). Subsequent queries
        # may still succeed; isolate this one.
        logger.warning(
            "judgment worker: LLM call failed for query, skipping",
            event_type="judgment_llm_failed",
            judgment_list_id=judgment_list_id,
            query_id=query.id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False

    # All-or-nothing persistence: confirm the response is a *set-equal*
    # match for the expected doc_ids. A simple ``len(ratings) <
    # len(expected_doc_ids)`` check would still admit duplicates like
    # ``[d1, d1]`` when expected was ``{d1, d2}`` — the UNIQUE constraint
    # would then admit only the first row and resume-skip would strand d2
    # forever (per GPT-5.5 cycle-3 C3-F1). Require exact set equality
    # AND that the LLM did not repeat any doc_id (no duplicates).
    returned_ids = [r.doc_id for r in result.ratings]
    returned_set = set(returned_ids)
    if returned_set != expected_doc_ids or len(returned_ids) != len(returned_set):
        logger.warning(
            "judgment worker: LLM response not set-equal to expected docs; "
            "skipping partial persist for retry",
            event_type="judgment_partial_response",
            judgment_list_id=judgment_list_id,
            query_id=query.id,
            expected=len(expected_doc_ids),
            returned_unique=len(returned_set),
            returned_total=len(returned_ids),
        )
        # Still record the cost — we paid for the call. The retry pays again,
        # but the alternative (permanent partial state) is worse.
        await safe_record_cost(
            redis,
            result.cost_usd,
            logger=logger,
            log_message="judgment service: record_cost failed (budget telemetry only)",
            event_type="judgment_record_cost_failed",
        )
        return False

    rater_ref = f"openai:{result.model}"
    rows = [
        {
            "id": str(uuid_utils.uuid7()),
            "judgment_list_id": judgment_list_id,
            "query_id": str(query.id),
            # Map prompt-only ordinal id (``item-N``) back to the real
            # engine-supplied doc_id for DB persistence (C6-F1).
            "doc_id": prompt_id_to_real[r.doc_id],
            "rating": r.rating,
            "source": "llm",
            "rater_ref": rater_ref,
            "notes": r.rationale,
        }
        for r in result.ratings
    ]
    # Persist FIRST, then record cost. If Redis is transiently unavailable
    # at the record_cost step we'd otherwise drop the already-paid-for
    # ratings (per GPT-5.5 cycle-2 C2-F3). Order swap means we may
    # under-count daily spend if Redis flaps, which is recoverable on
    # rollover; losing paid-for judgments is not.
    if rows:
        await repo.bulk_create_judgments(db, rows)
        await db.commit()

    new_total = await safe_record_cost(
        redis,
        result.cost_usd,
        logger=logger,
        log_message="judgment service: record_cost failed (budget telemetry only)",
        event_type="judgment_record_cost_failed",
    )

    logger.info(
        "judgment query processed",
        event_type="judgment_query_complete",
        judgment_list_id=judgment_list_id,
        query_id=query.id,
        ratings_count=len(result.ratings),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        running_total_usd=new_total,
        duration_ms=result.duration_ms,
    )
    return True
