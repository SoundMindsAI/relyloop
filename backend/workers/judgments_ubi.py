# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``generate_judgments_from_ubi`` Arq job (feat_ubi_judgments Story 3.3 / FR-5).

UBI-derived judgment generation pipeline:

1. Load the ``judgment_lists`` row + ``generation_params`` JSONB. Bail
   early if missing / already-terminal / missing the resume payload
   (the dispatcher always populates ``generation_params`` for UBI
   rows; a NULL here signals a partial-deploy race and the row flips
   to ``failed_reason='MISSING_GENERATION_PARAMS'``).
2. Build the engine adapter + :class:`UbiReader` + position-bias prior.
3. ``await reader.read_features(...)`` — empty result is the race
   fallback (preflight U-D2 catches the sync case; this terminal
   flip is the "in-flight window disappeared" safety net).
4. Construct the chosen converter:

   * ``ctr_threshold`` → :class:`CtrThresholdConverter`
   * ``dwell_time`` → :class:`DwellTimeThresholdConverter`
   * ``hybrid_ubi_llm`` → :class:`HybridUbiLlmConverter` with an
     injected LLM callback wired through
     :func:`backend.app.llm.openai_judge.rate_query_batch` +
     :mod:`backend.app.llm.budget_gate`.

5. Read the ``{ubi_query_id: user_query}`` map for the window;
   apply the chosen ``mapping_strategy`` per query when joining UBI
   ``user_query`` strings → ``queries.query_text`` →
   ``queries.id``. Per-query ambiguous mappings under
   ``mapping_strategy='reject'`` are **skipped, not terminal**
   (cycle-3 finding ``ambiguous-mapping-behavior-contradictory``);
   the per-list ``ambiguous_query_skip_count`` is surfaced via
   calibration JSONB.
6. Bulk-insert ``judgments`` rows with ``source='click'`` (pure
   UBI pairs) or ``source='llm'`` (hybrid LLM-fill pairs).
7. Write calibration JSONB::

       {coverage_pct, head_pairs, tail_pairs,
        position_bias_prior_id, llm_fill_calls?,
        ambiguous_query_skip_count, sparse_query_skip_count}

8. Terminal status: ``complete`` on a clean loop; ``failed`` +
   structured ``failed_reason`` on
   :class:`UbiInsufficientDataError` (race fallback),
   :class:`BudgetExceededError` (hybrid LLM-fill exhausted the
   daily budget), :class:`UnknownModelPricingError`, or unexpected
   exception.

**Hybrid LLM-fill implementation note.** Spec FR-2 describes hybrid as
"applies an inner pure converter where ``impression_count >=
llm_fill_threshold``; below the threshold, defers the pair to LLM-fill
via an injected callback." The callback signature is
``Callable[[list[tuple[str, str, str]]], Awaitable[dict[tuple[str, str], int]]]``
taking ``(query_id, doc_id, query_text)`` tuples. The worker-local
:func:`_make_llm_rate_callback` constructs the callback bound to:

* :func:`adapter.get_document` for a doc-body fetch BY ID. The FR-2
  callback contract is explicitly per-``(query_id, doc_id)`` pair (it
  takes ``(query_id, doc_id, query_text)`` tuples), so the LLM-fill
  rates the EXACT sparse pairs UBI surfaced — fetching each doc by its
  known id is the correct way to do that. (A template render +
  ``search_batch`` would retrieve whatever the query ranks, NOT the
  specific sparse pairs — so it would rate the wrong docs. The spec
  §FR-3 prose "template … to retrieve docs per query" predates the
  per-pair callback design in FR-2 and is the stale half; the
  ``current_template_id`` field is retained for lineage/provenance
  parity with the LLM path, not for retrieval. Whether to drop that
  now-vestigial requirement is tracked as a contract decision in
  ``chore_ubi_hybrid_template_render``.)
* :func:`rate_query_batch` for the LLM call + the existing budget
  gate + capability cache.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

import openai
import structlog
import uuid_utils
from openai import AsyncOpenAI
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.domain.ubi import (
    CtrThresholdConverter,
    DwellTimeThresholdConverter,
    FeatureVec,
    HybridUbiLlmConverter,
    LlmRateCallback,
    SignalsConverter,
)
from backend.app.domain.ubi.converter import ConverterConfig
from backend.app.llm.budget_gate import (
    BudgetExceededError,
    peek_daily_total,
    record_cost,
)
from backend.app.llm.cost_model import UnknownModelPricingError, estimated_max_call_cost
from backend.app.llm.openai_judge import rate_query_batch
from backend.app.llm.prompt_loader import load_judgment_prompts, render_user_prompt
from backend.app.services.cluster import build_adapter
from backend.app.services.ubi_errors import UbiNotEnabledError
from backend.app.services.ubi_reader import UbiReader

logger = structlog.get_logger(__name__)

_DOC_BODY_CHAR_LIMIT = 500
"""Per-doc body truncation length (mirrors generate_judgments_llm)."""


# ----------------------------------------------------------------------------
# mapping_strategy join helper
# ----------------------------------------------------------------------------


def _apply_mapping_strategy(
    *,
    ubi_query_to_user_query: dict[str, str],
    query_set_rows: Sequence[Any],
    mapping_strategy: str,
) -> tuple[dict[str, str], int]:
    """Resolve ``ubi_query_id → queries.id`` via ``user_query`` string match.

    Returns ``(ubi_query_id_to_internal_query_id, ambiguous_skip_count)``.
    Per-spec FR-5: ambiguous mappings under ``mapping_strategy='reject'``
    are SKIPPED with a counter increment (NOT terminal — cycle-3 finding
    `ambiguous-mapping-behavior-contradictory`).

    * ``'reject'`` — UBI query whose ``user_query`` matches multiple
      ``queries.query_text`` rows is skipped + counted.
    * ``'first_match'`` — pick the first matching row (sorted by id
      for determinism).
    * ``'most_recent'`` — pick the row with the highest ``created_at``.
    """
    # Build the user_query → list[query_row] index.
    by_text: dict[str, list[Any]] = {}
    for row in query_set_rows:
        by_text.setdefault(row.query_text, []).append(row)

    mapping: dict[str, str] = {}
    ambiguous_count = 0
    for ubi_qid, user_query in ubi_query_to_user_query.items():
        candidates = by_text.get(user_query, [])
        if not candidates:
            # No match at all — this UBI query has no corresponding row in
            # the operator's query_set. Silently drop (not a per-query skip;
            # the query simply isn't in the operator's evaluation set).
            continue
        if len(candidates) == 1:
            mapping[ubi_qid] = candidates[0].id
            continue
        # Ambiguous: multiple query_set rows share this user_query text.
        if mapping_strategy == "reject":
            ambiguous_count += 1
            continue
        if mapping_strategy == "first_match":
            picked = sorted(candidates, key=lambda r: r.id)[0]
        elif mapping_strategy == "most_recent":
            picked = max(candidates, key=lambda r: r.created_at)
        else:
            # Unknown strategy — treat like reject (defensive; the request
            # validator enforces the wire allowlist).
            ambiguous_count += 1
            continue
        mapping[ubi_qid] = picked.id
    return mapping, ambiguous_count


# ----------------------------------------------------------------------------
# Hybrid LLM-fill callback factory
# ----------------------------------------------------------------------------


def _make_llm_rate_callback(
    *,
    openai_client: AsyncOpenAI,
    model: str,
    rubric: str,
    bundle_system: str,
    target: str,
    adapter: Any,
    redis: Redis,
    budget_usd: float,
    llm_fill_calls_counter: list[int],
) -> LlmRateCallback:
    """Construct the :class:`LlmRateCallback` bound for hybrid mode.

    The callback receives ``[(query_id, doc_id, query_text), ...]`` for
    pairs the inner converter couldn't rate (``impression_count <
    llm_fill_threshold``). It groups by ``query_text``, fetches doc
    bodies via :func:`adapter.get_document`, calls
    :func:`rate_query_batch`, records cost through the daily budget
    gate, and returns ``{(query_id, doc_id): rating}``.

    ``llm_fill_calls_counter`` is a mutable list (length-1 int counter)
    so the worker can read the per-list LLM-call total for the
    calibration JSONB without threading another mutable through.
    """

    async def _callback(
        pairs: list[tuple[str, str, str]],
    ) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = {}
        if not pairs:
            return out

        # Group by query_text → run one rate_query_batch per query.
        by_query: dict[str, list[tuple[str, str]]] = {}
        query_id_for_text: dict[str, str] = {}
        for qid, did, qtext in pairs:
            by_query.setdefault(qtext, []).append((qid, did))
            query_id_for_text.setdefault(qtext, qid)

        for query_text, qd_pairs in by_query.items():
            qid = query_id_for_text[query_text]

            # Pre-call budget peek (spec FR-2 + FR-5).
            if budget_usd > 0:
                current = await peek_daily_total(redis)
                est_max = estimated_max_call_cost(model)
                if current + est_max > budget_usd:
                    raise BudgetExceededError(
                        f"current ${current:.4f} + estimated ${est_max:.4f} "
                        f"> budget ${budget_usd:.4f}"
                    )

            # Fetch doc bodies for this query's pairs. Map each prompt ordinal
            # back to the FULL (query_id, doc_id) tuple — not just doc_id.
            # Multiple distinct internal query_ids can share the same
            # query_text (duplicate rows in the operator's query set), and
            # they're grouped together here; mapping prompt_id → doc_id alone
            # would attribute every rating to the single representative `qid`
            # and silently drop ratings for the others (Gemini PR #317
            # findings #2 + #3).
            doc_inputs: list[dict[str, str]] = []
            prompt_id_to_real: dict[str, tuple[str, str]] = {}
            for i, (pair_query_id, doc_id) in enumerate(qd_pairs):
                doc = await adapter.get_document(target, doc_id)
                source = getattr(doc, "source", None) if doc is not None else None
                body_raw: str
                if isinstance(source, dict) and source.get("body"):
                    body_raw = str(source["body"])
                elif source is not None:
                    import json as _json

                    body_raw = _json.dumps(source, ensure_ascii=False)
                else:
                    body_raw = ""
                body = body_raw[:_DOC_BODY_CHAR_LIMIT]
                prompt_id = f"item-{i}"
                doc_inputs.append({"doc_id": prompt_id, "body": body})
                prompt_id_to_real[prompt_id] = (pair_query_id, doc_id)

            expected = set(prompt_id_to_real.keys())
            user_prompt = render_user_prompt(
                rubric_text=rubric,
                query_text=query_text,
                docs=doc_inputs,
            )
            system_prompt = f"{bundle_system}\n\n<rubric>\n{rubric}\n</rubric>"

            try:
                result = await rate_query_batch(
                    client=openai_client,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    expected_doc_ids=expected,
                )
            except (
                openai.AuthenticationError,
                openai.PermissionDeniedError,
                openai.BadRequestError,
                openai.NotFoundError,
            ):
                # Persistent provider misconfig — propagate so the worker
                # marks the list failed.
                raise
            except Exception as exc:
                # Per-query operational failure — skip this query's pairs
                # (matches the LLM worker's isolation pattern).
                logger.warning(
                    "ubi worker: hybrid LLM call failed for query, skipping",
                    event_type="ubi_hybrid_llm_failed",
                    query_id=qid,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                continue

            try:
                await record_cost(redis, result.cost_usd)
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "ubi worker: record_cost failed (budget telemetry only)",
                    event_type="ubi_record_cost_failed",
                    cost_usd=result.cost_usd,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

            llm_fill_calls_counter[0] += 1

            # Map prompt-only ordinals back to the real (query_id, doc_id) so
            # ratings stay attributed to the requesting query.
            for r in result.ratings:
                real_pair = prompt_id_to_real.get(r.doc_id)
                if real_pair is None:
                    continue  # hallucinated id; skip
                out[real_pair] = r.rating

        return out

    return _callback


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------


async def generate_judgments_from_ubi(ctx: dict[str, Any], judgment_list_id: str) -> None:
    """Arq entry point — run the UBI judge pipeline for one judgment list (FR-5)."""
    del ctx  # unused
    settings = get_settings()
    started_at = time.monotonic()
    factory = get_session_factory()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    openai_client: AsyncOpenAI | None = None
    adapter: Any = None

    try:
        async with factory() as db:
            judgment_list = await repo.get_judgment_list(db, judgment_list_id)
            if judgment_list is None:
                logger.info(
                    "ubi worker: list vanished, returning",
                    event_type="ubi_list_missing",
                    judgment_list_id=judgment_list_id,
                )
                return
            if judgment_list.status != "generating":
                logger.info(
                    "ubi worker: list already terminal, returning",
                    event_type="ubi_list_already_terminal",
                    judgment_list_id=judgment_list_id,
                    status=judgment_list.status,
                )
                return
            params: dict[str, Any] | None = judgment_list.generation_params
            if params is None or params.get("generation_kind") != "ubi":
                logger.warning(
                    "ubi worker: missing or non-ubi generation_params",
                    event_type="ubi_missing_generation_params",
                    judgment_list_id=judgment_list_id,
                )
                await _fail_list(db, judgment_list_id, "MISSING_GENERATION_PARAMS")
                return

            cluster = await repo.get_cluster(db, judgment_list.cluster_id)
            if cluster is None:
                await _fail_list(db, judgment_list_id, "CLUSTER_NOT_FOUND")
                return
            query_set_rows = await repo.list_queries_for_set(db, judgment_list.query_set_id)

        # Build adapter + reader (UbiReader respects the no-writes invariant).
        adapter = build_adapter(cluster)
        reader = UbiReader(adapter, position_bias_prior=settings.ubi_position_bias_prior)

        target = params["target"]
        since = datetime.fromisoformat(params["since"])
        until = datetime.fromisoformat(params["until"]) if params.get("until") else None
        converter_kind = params["converter"]
        converter_config_dict = params.get("converter_config") or {}
        mapping_strategy = params.get("mapping_strategy") or "reject"

        # Read features.
        try:
            features = await reader.read_features(
                target=target,
                since=since,
                until=until,
            )
        except UbiNotEnabledError as exc:
            async with factory() as db:
                await _fail_list(db, judgment_list_id, "UBI_NOT_ENABLED")
            logger.warning(
                "ubi worker: ubi not enabled mid-run",
                event_type="ubi_not_enabled_mid_run",
                judgment_list_id=judgment_list_id,
                error=str(exc),
            )
            return

        if not features:
            # Race fallback: preflight U-D2 catches the obvious case; this
            # fires only when the in-flight window's data vanished.
            async with factory() as db:
                await _fail_list(db, judgment_list_id, "UBI_INSUFFICIENT_DATA")
            logger.info(
                "ubi worker: empty features after probe — race fallback fired",
                event_type="ubi_empty_features_race",
                judgment_list_id=judgment_list_id,
            )
            return

        # Read the ubi_query_id → user_query map for the same window.
        ubi_query_to_user_query = await reader.read_user_query_map(
            target=target,
            since=since,
            until=until,
        )
        query_id_map, ambiguous_skip_count = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_query_to_user_query,
            query_set_rows=query_set_rows,
            mapping_strategy=mapping_strategy,
        )

        # Construct converter. The hybrid converter needs an internal-id →
        # query_text lookup for its LLM-fill callback payload; build a
        # closure over the loaded query_set_rows.
        query_text_by_internal_id: dict[str, str] = {
            row.id: row.query_text for row in query_set_rows
        }

        def _lookup_query_text(query_id: str) -> str:
            return query_text_by_internal_id.get(query_id, "")

        converter, llm_fill_counter = _build_converter(
            kind=converter_kind,
            converter_config=converter_config_dict,
            params=params,
            settings=settings,
            redis=redis_client,
            adapter=adapter,
            target=target,
            query_text_lookup=_lookup_query_text,
        )
        if isinstance(converter, _HybridConverterPack):
            openai_client = converter.openai_client
            actual_converter = converter.converter
        else:
            actual_converter = converter

        # Map features' ubi_query_id keys to internal queries.id keys; pairs
        # whose ubi_query_id has no resolution (no match OR ambiguous-reject)
        # are skipped. Track tail/head counts for calibration.
        scoped_features: dict[tuple[str, str], FeatureVec] = {}
        sparse_skip_count = 0
        for (ubi_qid, doc_id), feat in features.items():
            internal_qid = query_id_map.get(ubi_qid)
            if internal_qid is None:
                # Either no match in the query set OR skipped via ambiguous.
                # The ambiguous tally was already incremented above; the
                # no-match case isn't a skip (the query just isn't in the
                # operator's set).
                continue
            scoped_features[(internal_qid, doc_id)] = feat

        if not scoped_features:
            # All pairs filtered out by mapping_strategy — degenerate but
            # valid; complete with judgment_count=0 and the skip counts.
            async with factory() as db:
                await _write_calibration_and_complete(
                    db,
                    judgment_list_id=judgment_list_id,
                    head_pairs=0,
                    tail_pairs=0,
                    coverage_pct=0.0,
                    llm_fill_calls=0,
                    ambiguous_skip_count=ambiguous_skip_count,
                    sparse_skip_count=sparse_skip_count,
                )
            logger.info(
                "ubi worker: no scoped features after mapping; completed empty",
                event_type="ubi_no_scoped_features",
                judgment_list_id=judgment_list_id,
                ambiguous_skip_count=ambiguous_skip_count,
            )
            return

        # The request-level llm_fill_threshold (top-level generation_params
        # field) must reach BOTH the converter's head/tail partition AND the
        # source-attribution below, or they disagree (GPT-5.5 PR #317
        # finding #5). The HybridUbiLlmConverter reads
        # `config.extra['llm_fill_threshold']`, so merge the top-level value
        # into the converter config extra (a value already inside
        # converter_config wins — explicit operator override).
        llm_fill_threshold = params.get("llm_fill_threshold") or 20
        converter_extra: dict[str, Any] = {
            "llm_fill_threshold": llm_fill_threshold,
            **converter_config_dict,
        }

        # Apply converter to scoped features.
        try:
            ratings = await actual_converter.convert(
                scoped_features,
                ConverterConfig(extra=converter_extra),
            )
            # sparse_query_skip_count = scoped queries that received NO rating.
            # Pure converters rate every pair (so this is 0), but in hybrid
            # mode the LLM-fill callback skips a query's tail pairs when its
            # LLM call fails (per-query isolation) — those pairs never appear
            # in `ratings`, and this surfaces them in calibration telemetry
            # (Gemini PR #317 finding #5).
            rated_queries = {qid for qid, _doc in ratings}
            all_scoped_queries = {qid for qid, _doc in scoped_features}
            sparse_skip_count = len(all_scoped_queries - rated_queries)
        except BudgetExceededError as exc:
            async with factory() as db:
                await _fail_list(db, judgment_list_id, "OPENAI_BUDGET_EXCEEDED")
            logger.warning(
                "ubi worker: hybrid budget exceeded mid-loop",
                event_type="ubi_budget_exceeded",
                judgment_list_id=judgment_list_id,
                error=str(exc),
            )
            return
        except UnknownModelPricingError:
            async with factory() as db:
                await _fail_list(db, judgment_list_id, "UNKNOWN_MODEL_PRICING")
            return

        # Build rows. Pair source = 'click' (pure UBI rating) if the inner
        # converter rated it; 'llm' if the hybrid LLM-fill callback filled it.
        # The HybridUbiLlmConverter merges the two dicts; we re-derive the
        # split by the SAME threshold the converter used (merged above).
        is_hybrid = converter_kind == "hybrid_ubi_llm"
        model = settings.openai_model if is_hybrid else None
        rows: list[dict[str, Any]] = []
        for pair, rating in ratings.items():
            if pair not in scoped_features:
                continue
            feat = scoped_features[pair]
            internal_qid, doc_id = pair
            if is_hybrid and feat.impression_count < llm_fill_threshold:
                source = "llm"
                rater_ref = f"openai:{model}" if model is not None else "openai:unknown"
            else:
                source = "click"
                rater_ref = f"ubi:{converter_kind}"
            rows.append(
                {
                    "id": str(uuid_utils.uuid7()),
                    "judgment_list_id": judgment_list_id,
                    "query_id": internal_qid,
                    "doc_id": doc_id,
                    "rating": rating,
                    "source": source,
                    "rater_ref": rater_ref,
                }
            )

        async with factory() as db:
            if rows:
                await repo.bulk_create_judgments(db, rows)
                await db.commit()

            # Calibration tally.
            head_pairs = sum(
                1 for f in scoped_features.values() if f.impression_count >= llm_fill_threshold
            )
            tail_pairs = len(scoped_features) - head_pairs
            coverage_pct = len(rows) / max(len(scoped_features), 1)
            await _write_calibration_and_complete(
                db,
                judgment_list_id=judgment_list_id,
                head_pairs=head_pairs,
                tail_pairs=tail_pairs,
                coverage_pct=coverage_pct,
                llm_fill_calls=llm_fill_counter[0],
                ambiguous_skip_count=ambiguous_skip_count,
                sparse_skip_count=sparse_skip_count,
            )

        logger.info(
            "ubi worker: list complete",
            event_type="ubi_list_complete",
            judgment_list_id=judgment_list_id,
            judgment_count=len(rows),
            head_pairs=head_pairs,
            tail_pairs=tail_pairs,
            ambiguous_skip_count=ambiguous_skip_count,
            llm_fill_calls=llm_fill_counter[0],
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    except Exception as exc:  # noqa: BLE001 — any unexpected failure → mark failed
        logger.warning(
            "ubi worker: unhandled exception — marking list failed",
            event_type="ubi_unhandled_failure",
            judgment_list_id=judgment_list_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        try:
            async with factory() as db:
                await _fail_list(db, judgment_list_id, f"UNEXPECTED:{type(exc).__name__}")
        except Exception:  # noqa: BLE001
            logger.exception(
                "ubi worker: failed to record terminal status",
                judgment_list_id=judgment_list_id,
            )
    finally:
        if openai_client is not None:
            try:
                await openai_client.close()
            except Exception:  # noqa: BLE001
                logger.debug("openai client close raised", exc_info=True)
        if adapter is not None:
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("adapter close raised", exc_info=True)
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001
            logger.debug("redis close raised", exc_info=True)


# ----------------------------------------------------------------------------
# Converter construction helpers
# ----------------------------------------------------------------------------


class _HybridConverterPack:
    """Bundle the converter + the openai client it owns (so the worker can close it)."""

    def __init__(self, converter: SignalsConverter, openai_client: AsyncOpenAI) -> None:
        self.converter = converter
        self.openai_client = openai_client


def _build_converter(
    *,
    kind: str,
    converter_config: dict[str, Any],
    params: dict[str, Any],
    settings: Any,
    redis: Redis,
    adapter: Any,
    target: str,
    query_text_lookup: Callable[[str], str],
) -> tuple[SignalsConverter | _HybridConverterPack, list[int]]:
    """Construct the chosen converter.

    Returns ``(converter | _HybridConverterPack, llm_fill_calls_counter)``.
    The counter is a mutable ``[int]`` cell so the hybrid callback can
    increment it without needing a thread-safe primitive (the worker is
    single-coroutine per list).
    """
    counter: list[int] = [0]
    if kind == "ctr_threshold":
        return CtrThresholdConverter(), counter
    if kind == "dwell_time":
        return DwellTimeThresholdConverter(), counter
    if kind == "hybrid_ubi_llm":
        inner_kind = converter_config.get("inner", "ctr_threshold")
        inner: SignalsConverter
        if inner_kind == "dwell_time":
            inner = DwellTimeThresholdConverter()
        else:
            inner = CtrThresholdConverter()
        openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key, base_url=settings.openai_base_url
        )
        bundle = load_judgment_prompts()
        callback: LlmRateCallback = _make_llm_rate_callback(
            openai_client=openai_client,
            model=settings.openai_model,
            rubric=params.get("rubric") or "Rate the document's relevance to the query (0-3).",
            bundle_system=bundle.system_prompt,
            target=target,
            adapter=adapter,
            redis=redis,
            budget_usd=settings.openai_daily_budget_usd,
            llm_fill_calls_counter=counter,
        )
        converter: SignalsConverter = HybridUbiLlmConverter(
            inner=inner,
            llm_rate=callback,
            query_text_lookup=query_text_lookup,
        )
        return _HybridConverterPack(converter, openai_client), counter
    raise ValueError(f"unknown converter kind: {kind!r}")


# ----------------------------------------------------------------------------
# Terminal-status helpers
# ----------------------------------------------------------------------------


async def _fail_list(db: Any, judgment_list_id: str, failed_reason: str) -> None:
    """Helper: flip a list to ``status='failed'`` with a structured reason."""
    await repo.update_judgment_list_status(
        db, judgment_list_id, status="failed", failed_reason=failed_reason
    )
    await db.commit()


async def _write_calibration_and_complete(
    db: Any,
    *,
    judgment_list_id: str,
    head_pairs: int,
    tail_pairs: int,
    coverage_pct: float,
    llm_fill_calls: int,
    ambiguous_skip_count: int,
    sparse_skip_count: int,
) -> None:
    """Write the UBI calibration JSONB + flip status to ``complete``."""
    calibration: dict[str, Any] = {
        "coverage_pct": coverage_pct,
        "head_pairs": head_pairs,
        "tail_pairs": tail_pairs,
        "position_bias_prior_id": None,  # Settings.ubi_position_bias_prior_file path future
        "ambiguous_query_skip_count": ambiguous_skip_count,
        "sparse_query_skip_count": sparse_skip_count,
    }
    if llm_fill_calls > 0:
        calibration["llm_fill_calls"] = llm_fill_calls
    await repo.update_judgment_list_calibration(db, judgment_list_id, calibration)
    await repo.update_judgment_list_status(db, judgment_list_id, status="complete")
    await db.commit()


__all__ = [
    "generate_judgments_from_ubi",
    "_make_llm_rate_callback",
    "_apply_mapping_strategy",
]


# Keep mypy happy about the Awaitable / Callable imports being used.
_LlmRateCallbackT: type = type(Callable[[list[tuple[str, str, str]]], Awaitable[Any]])
del _LlmRateCallbackT
