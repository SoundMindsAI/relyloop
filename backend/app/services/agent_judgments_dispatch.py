# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Service-layer dispatch for judgment generation — LLM + UBI.

(feat_chat_agent Story 2.2 + feat_ubi_judgments Story 2.2 / FR-4)

The preflight (OpenAI configured / capability cache / model pricing / budget
peek / FK resolution / consistency / oversize) + INSERT + Arq enqueue lift out
of ``backend/app/api/v1/judgments.py`` so:

* The LLM router AND the chat-agent ``generate_judgments_llm`` tool reuse the
  same checks (`start_judgment_generation`).
* The UBI router AND the chat-agent ``generate_judgments_from_ubi`` tool reuse
  the same checks (`start_ubi_judgment_generation`).

Per spec FR-4: shared helpers factor the duplicated logic out so the two
dispatchers (LLM and UBI) don't drift. Five helpers — ``_resolve_fk``,
``_check_consistency``, ``_check_llm_preflight``, ``_check_oversized_query_set``,
``_insert_generating_list_and_enqueue`` — each owns one slice of the preflight
chain. ``start_judgment_generation`` and ``start_ubi_judgment_generation`` are
thin orchestrators over these helpers.

Raises ``HTTPException`` with the spec §7.5 error envelope so the router's
existing handler passes the structured detail through unchanged and the agent
dispatcher can map ``HTTPException.detail['error_code']`` into a
``tool_result.error`` payload.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from arq.connections import ArqRedis
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.core.logging import get_logger
from backend.app.core.settings import Settings
from backend.app.db import repo
from backend.app.db.models import Cluster, QuerySet
from backend.app.db.models.query_template import QueryTemplate
from backend.app.llm.budget_gate import peek_daily_total
from backend.app.llm.capability_check import read_or_recompute_capability_result
from backend.app.llm.cost_model import known_models
from backend.app.services.cluster import build_adapter
from backend.app.services.ubi_errors import UbiNotEnabledError
from backend.app.services.ubi_reader import UbiReader
from backend.app.services.ubi_readiness import count_ubi_events_in_window

logger = get_logger(__name__)


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


# ---------------------------------------------------------------------------
# Request / Result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgmentGenerationRequest:
    """Inputs to ``start_judgment_generation`` (LLM path).

    Mirrors the shape of ``CreateJudgmentListGenerateRequest`` (the router's
    request body) so callers can pass either the request model fields directly
    or build this dataclass from tool args.
    """

    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    current_template_id: str
    rubric: str


@dataclass(frozen=True, slots=True)
class UbiJudgmentGenerationRequest:
    """Inputs to ``start_ubi_judgment_generation`` (UBI path, FR-4).

    Mirrors ``CreateJudgmentListFromUbiRequest`` (Story 3.2's router shape).
    ``current_template_id`` + ``rubric`` are REQUIRED when
    ``converter == 'hybrid_ubi_llm'`` and REJECTED otherwise — the Pydantic
    layer enforces this via ``model_validator``; the dispatcher trusts the
    request to have been validated.
    """

    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    since: datetime
    until: datetime | None
    converter: Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]
    converter_config: dict[str, Any] | None
    llm_fill_threshold: int | None
    min_impressions_threshold: int | None
    mapping_strategy: Literal["reject", "first_match", "most_recent"]
    current_template_id: str | None
    rubric: str | None


@dataclass(frozen=True, slots=True)
class JudgmentGenerationResult:
    """Return value from the LLM + UBI dispatch entry points.

    Both ``start_judgment_generation`` and
    ``start_ubi_judgment_generation`` return this shape so the router
    handlers and agent-tool dispatchers can compose uniformly.
    """

    judgment_list_id: str
    status: Literal["generating"]


# ---------------------------------------------------------------------------
# Shared preflight helpers (FR-4 — extracted so LLM + UBI dispatchers share)
# ---------------------------------------------------------------------------


async def _resolve_fk(
    db: AsyncSession,
    *,
    cluster_id: str,
    query_set_id: str,
    template_id: str | None,
) -> tuple[Cluster, QuerySet, QueryTemplate | None]:
    """FK resolution — cluster, query_set, optional template.

    Raises the spec-aligned 404 ``HTTPException`` per missing entity:

    * ``CLUSTER_NOT_FOUND`` — cluster row missing.
    * ``TEMPLATE_NOT_FOUND`` — template row missing (only when
      ``template_id`` is supplied — UBI's pure converters pass ``None``
      and skip this branch).
    * ``QUERY_SET_NOT_FOUND`` — query set row missing.
    """
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)

    template: QueryTemplate | None = None
    if template_id is not None:
        template = await repo.get_query_template(db, template_id)
        if template is None:
            raise _err(
                404,
                "TEMPLATE_NOT_FOUND",
                f"template {template_id} not found",
                False,
            )

    query_set = await repo.get_query_set(db, query_set_id)
    if query_set is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {query_set_id} not found", False)

    return cluster, query_set, template


def _check_consistency(
    *,
    cluster: Cluster,
    query_set: QuerySet,
    cluster_id: str,
    query_set_id: str,
    template: QueryTemplate | None,
) -> None:
    """Consistency checks — raise 422 ``VALIDATION_ERROR`` on mismatch.

    * ``query_set.cluster_id`` must equal ``cluster_id`` (you can't
      generate judgments for a query set that lives on a different
      cluster).
    * When ``template`` is provided, ``template.engine_type`` must equal
      ``cluster.engine_type`` (Jinja templates render against a specific
      engine's DSL).
    """
    if query_set.cluster_id != cluster_id:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query_set {query_set_id} belongs to cluster "
            f"{query_set.cluster_id!r}, not {cluster_id!r}",
            False,
        )
    if template is not None and template.engine_type != cluster.engine_type:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"template engine_type {template.engine_type!r} does not match "
            f"cluster engine_type {cluster.engine_type!r}",
            False,
        )


async def _check_llm_preflight(*, settings: Settings, redis: Redis) -> None:
    """LLM-side preflight (A → B → B.1 → C from the original dispatcher).

    Raises the matching 503 envelope:

    * ``OPENAI_NOT_CONFIGURED`` — key missing.
    * ``LLM_PROVIDER_INCAPABLE`` — capability cache miss /
      ``structured_output != ok`` / cached model != configured model.
    * ``UNKNOWN_MODEL_PRICING`` — ``Settings.openai_model`` has no
      ``cost_model`` entry.
    * ``OPENAI_BUDGET_EXCEEDED`` — pre-call peek already >= budget.

    UBI's pure converters skip this helper entirely; hybrid mode calls
    it inside the dispatcher because LLM-fill calls go through the
    same budget gate.
    """
    # A — key.
    if not settings.openai_api_key:
        raise _err(
            503,
            "OPENAI_NOT_CONFIGURED",
            "OPENAI_API_KEY_FILE is empty; cannot dispatch judgment generation",
            False,
        )

    # B — capability cache.
    # bug_llm_capability_cache_no_refresh (D-5): swap read_capability_result →
    # read_or_recompute_capability_result so a cache miss after the 24h TTL
    # passes triggers an inline recompute instead of returning 503. By this
    # line, settings.openai_api_key is guaranteed non-empty (step A above).
    cap = await read_or_recompute_capability_result(
        redis,
        settings.openai_base_url,
        settings.openai_api_key,
        settings.openai_model,
    )
    if cap is None or cap.structured_output != "ok" or cap.model != settings.openai_model:
        if cap is None:
            # Unreachable in practice: api_key was validated non-empty at
            # step A, and the helper only returns None on empty key. Kept
            # as a defensive guard against future helper-contract drift.
            cause = "cache miss"
        elif cap.model != settings.openai_model:
            cause = (
                f"cached probe model {cap.model!r} != configured "
                f"OPENAI_MODEL {settings.openai_model!r}"
            )
        else:
            cause = f"structured_output={cap.structured_output!r}"
        raise _err(
            503,
            "LLM_PROVIDER_INCAPABLE",
            f"OpenAI capability check ({cause}); structured-output required",
            False,
        )

    # B.1 — pricing.
    if settings.openai_model not in known_models():
        raise _err(
            503,
            "UNKNOWN_MODEL_PRICING",
            f"OPENAI_MODEL={settings.openai_model!r} has no entry in cost_model; "
            "cannot enforce daily budget gate",
            False,
        )

    # C — budget peek.
    if settings.openai_daily_budget_usd > 0:
        current = await peek_daily_total(redis)
        if current >= settings.openai_daily_budget_usd:
            raise _err(
                503,
                "OPENAI_BUDGET_EXCEEDED",
                f"daily total ${current:.2f} >= budget ${settings.openai_daily_budget_usd:.2f}",
                True,
            )


async def _check_oversized_query_set(db: AsyncSession, *, query_set_id: str) -> None:
    """Reject if the set has > 10K queries (Original FR-3 E)."""
    count = await repo.count_queries_in_set(db, query_set_id)
    if count > 10_000:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query set has {count} queries; max 10000 allowed for LLM generation",
            False,
        )


async def _insert_generating_list_and_enqueue(
    *,
    db: AsyncSession,
    arq_pool: ArqRedis | None,
    kind: Literal["llm", "ubi"],
    fields: dict[str, Any],
    enqueue_job_name: str,
    judgment_list_name: str,
) -> str:
    """INSERT the row + commit + best-effort Arq enqueue.

    Returns the new ``judgment_list_id``. UNIQUE-name collision → 409
    ``JUDGMENT_LIST_NAME_TAKEN``. Pool absent / enqueue raise → WARN
    log; the boot-time resume sweep recovers (covered by
    ``feat_judgments_periodic_resume_sweep``).
    """
    judgment_list_id = str(uuid.uuid4())
    try:
        await repo.create_judgment_list(
            db,
            id=judgment_list_id,
            status="generating",
            failed_reason=None,
            calibration=None,
            **fields,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _err(
            409,
            "JUDGMENT_LIST_NAME_TAKEN",
            f"judgment list name {judgment_list_name!r} already exists",
            False,
        ) from exc

    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job(
                enqueue_job_name,
                judgment_list_id,
                _job_id=f"{enqueue_job_name}:{judgment_list_id}",
            )
        except Exception as exc:  # noqa: BLE001 — durable row + sweep covers this
            logger.warning(
                "start_judgment_generation: arq enqueue raised — relying on worker boot sweep",
                judgment_list_id=judgment_list_id,
                kind=kind,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    return judgment_list_id


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


async def start_judgment_generation(
    *,
    db: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis | None,
    settings: Settings,
    req: JudgmentGenerationRequest,
) -> JudgmentGenerationResult:
    """Run the full preflight + create the judgment_list row + enqueue the worker.

    Preflight order (parity with the pre-refactor body):

    A/B/B.1/C. LLM preflight (key / capability / pricing / budget).
    D. FK resolution (cluster / template / query_set).
    D.1. Consistency (query_set ↔ cluster, template engine ↔ cluster engine).
    E. Oversized query set (>10K) → 422 VALIDATION_ERROR.
    F. INSERT (UNIQUE collision → 409 JUDGMENT_LIST_NAME_TAKEN); commit;
       best-effort enqueue.
    """
    await _check_llm_preflight(settings=settings, redis=redis)
    cluster, query_set, template = await _resolve_fk(
        db,
        cluster_id=req.cluster_id,
        query_set_id=req.query_set_id,
        template_id=req.current_template_id,
    )
    _check_consistency(
        cluster=cluster,
        query_set=query_set,
        cluster_id=req.cluster_id,
        query_set_id=req.query_set_id,
        template=template,
    )
    await _check_oversized_query_set(db, query_set_id=req.query_set_id)

    judgment_list_id = await _insert_generating_list_and_enqueue(
        db=db,
        arq_pool=arq_pool,
        kind="llm",
        fields={
            "name": req.name,
            "description": req.description,
            "query_set_id": req.query_set_id,
            "cluster_id": req.cluster_id,
            "target": req.target,
            "current_template_id": req.current_template_id,
            "rubric": req.rubric,
        },
        enqueue_job_name="generate_judgments_llm",
        judgment_list_name=req.name,
    )
    return JudgmentGenerationResult(judgment_list_id=judgment_list_id, status="generating")


# ---------------------------------------------------------------------------
# UBI path
# ---------------------------------------------------------------------------


MAX_UBI_WINDOW_DAYS = 90
"""Spec FR-4 U-D cap on the (since, until) window."""


def _build_ubi_generation_params(req: UbiJudgmentGenerationRequest) -> dict[str, Any]:
    """Build the ``generation_params`` JSONB persisted at INSERT time (FR-4 U-G).

    Always injects ``generation_kind: 'ubi'`` server-side so the worker
    resume sweep can discriminate UBI/hybrid rows from LLM rows and
    Story 4.3's ``<ValueDeltaCard>`` can branch its rendering.
    """
    return {
        "generation_kind": "ubi",
        "target": req.target,
        "since": req.since.isoformat(),
        "until": req.until.isoformat() if req.until is not None else None,
        "converter": req.converter,
        "converter_config": req.converter_config,
        "llm_fill_threshold": req.llm_fill_threshold,
        "min_impressions_threshold": req.min_impressions_threshold,
        "mapping_strategy": req.mapping_strategy,
        "current_template_id": req.current_template_id,
        "rubric": req.rubric,
    }


async def start_ubi_judgment_generation(
    *,
    db: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis | None,
    settings: Settings,
    req: UbiJudgmentGenerationRequest,
) -> JudgmentGenerationResult:
    """Run the full UBI preflight + INSERT + enqueue (FR-4 U-A..U-H).

    Preflight order:

    * **U-A.** FK resolution. ``current_template_id`` required for hybrid,
      forbidden for pure (Pydantic layer enforces; helper trusts).
    * **U-B.** Consistency (query_set ↔ cluster, template engine ↔
      cluster engine when hybrid).
    * **U-C.** UBI readiness probe (``get_schema('ubi_queries')``) →
      412 ``UBI_NOT_ENABLED``.
    * **U-D.** Window validity + 90-day cap → 422 ``UBI_WINDOW_TOO_LARGE``.
    * **U-D2.** Sync count gate → 422 ``UBI_INSUFFICIENT_DATA`` when
      below ``min_impressions_threshold`` (FR-4 + cycle-3 D-10d).
    * **U-E.** Hybrid-mode LLM preflight (A+B+B.1+C from the LLM path).
    * **U-F.** Oversized query set (>10K) → 422.
    * **U-G.** INSERT row with ``generation_params`` JSONB carrying the
      worker-resume payload (incl. ``generation_kind: 'ubi'``
      discriminator).
    * **U-H.** Best-effort Arq enqueue (``generate_judgments_from_ubi``).
    """
    # Normalize naive datetimes to UTC-aware up front. Pydantic accepts a
    # naive ISO-8601 `since`/`until` (no offset) and leaves it naive; comparing
    # a naive datetime with the aware `datetime.now(UTC)` below raises
    # TypeError and crashes the dispatcher (Gemini PR #317 finding #1). Treat
    # naive inputs as UTC — the wire contract is UTC per the request schema.
    since_utc = req.since if req.since.tzinfo is not None else req.since.replace(tzinfo=UTC)
    until_utc = (
        req.until
        if (req.until is None or req.until.tzinfo is not None)
        else req.until.replace(tzinfo=UTC)
    )
    req = dataclasses.replace(req, since=since_utc, until=until_utc)

    is_hybrid = req.converter == "hybrid_ubi_llm"
    template_id_for_resolve = req.current_template_id if is_hybrid else None

    # U-A.
    cluster, query_set, template = await _resolve_fk(
        db,
        cluster_id=req.cluster_id,
        query_set_id=req.query_set_id,
        template_id=template_id_for_resolve,
    )
    # U-B.
    _check_consistency(
        cluster=cluster,
        query_set=query_set,
        cluster_id=req.cluster_id,
        query_set_id=req.query_set_id,
        template=template,
    )

    # U-C + U-D + U-D2 — adapter-bound checks. Build adapter once.
    # Adapter connectivity failures (probe / count) translate to the spec
    # §8.5 503 CLUSTER_UNREACHABLE envelope rather than bubbling as an
    # unstructured 500 (GPT-5.5 PR #317 final-review finding #2). The
    # UbiNotEnabledError → 412 catch is narrower and runs first.
    adapter = build_adapter(cluster)
    try:
        # Inject Settings-backed scan ceilings (FR-5/FR-7) so the dispatcher's
        # probe + sync count gate (U-C / U-D2) use the same defaults as the
        # worker. The probe + count helpers don't iterate the full stream
        # themselves — the ceilings only kick in if `count_ubi_events`
        # eventually delegates to the paginated path; passing them here keeps
        # the construction-site contract consistent across all 3 call sites.
        reader = UbiReader(
            adapter,
            max_events=settings.ubi_max_events_scan,
            max_queries=settings.ubi_max_queries_scan,
            query_id_batch_size=settings.ubi_query_id_batch_size,
            query_id_batch_max_bytes=settings.ubi_query_id_batch_max_bytes,
        )
        try:
            await reader._probe_enabled()
        except UbiNotEnabledError as exc:
            raise _err(412, "UBI_NOT_ENABLED", str(exc), False) from exc
        except ClusterUnreachableError as exc:
            raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc

        # U-D.
        effective_until = req.until or datetime.now(UTC)
        if req.since >= effective_until:
            raise _err(
                422,
                "VALIDATION_ERROR",
                f"since {req.since.isoformat()} must be < until {effective_until.isoformat()}",
                False,
            )
        window = effective_until - req.since
        if window > timedelta(days=MAX_UBI_WINDOW_DAYS):
            raise _err(
                422,
                "UBI_WINDOW_TOO_LARGE",
                f"window {window.days} days exceeds {MAX_UBI_WINDOW_DAYS}-day cap "
                "(narrow `since`/`until` and retry)",
                False,
            )

        # U-D2. NOTE: the count is scoped to (target, window) — NOT to the
        # query set. Scoping to the query set requires the UBI
        # user_query → queries.query_text join (the worker does this per
        # FR-5 step 5), which is too expensive for a sync preflight. This
        # is a deliberate MVP approximation: a target carrying unrelated
        # traffic can pass U-D2 even when the selected query set has thin
        # coverage; the worker's empty-features race-fallback
        # (UBI_INSUFFICIENT_DATA terminal) catches the truly-empty scoped
        # case. (GPT-5.5 PR #317 finding #4 — accepted as documented.)
        min_threshold = req.min_impressions_threshold or 100
        try:
            observed = await count_ubi_events_in_window(
                adapter,
                target=req.target,
                since=req.since,
                until=effective_until,
                cap=min_threshold,
            )
        except ClusterUnreachableError as exc:
            raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
        if observed < min_threshold:
            base_msg = (
                f"only {observed} UBI events match the window "
                f"{req.since.isoformat()}..{effective_until.isoformat()} "
                f"against target {req.target!r} (required: {min_threshold})"
            )
            if is_hybrid:
                hint = " — widen `since`/`until` to include more traffic and retry"
            else:
                hint = (
                    " — widen the window OR switch to the `hybrid_ubi_llm` "
                    "converter for LLM-fill on sparse pairs"
                )
            raise _err(422, "UBI_INSUFFICIENT_DATA", base_msg + hint, False)
    finally:
        await adapter.aclose()

    # U-E (hybrid only).
    if is_hybrid:
        await _check_llm_preflight(settings=settings, redis=redis)

    # U-F.
    await _check_oversized_query_set(db, query_set_id=req.query_set_id)

    # U-G + U-H.
    converter_description = (
        req.rubric if is_hybrid and req.rubric is not None else f"UBI converter: {req.converter}"
    )
    judgment_list_id = await _insert_generating_list_and_enqueue(
        db=db,
        arq_pool=arq_pool,
        kind="ubi",
        fields={
            "name": req.name,
            "description": req.description,
            "query_set_id": req.query_set_id,
            "cluster_id": req.cluster_id,
            "target": req.target,
            "current_template_id": req.current_template_id,
            "rubric": converter_description,
            "generation_params": _build_ubi_generation_params(req),
        },
        enqueue_job_name="generate_judgments_from_ubi",
        judgment_list_name=req.name,
    )
    return JudgmentGenerationResult(judgment_list_id=judgment_list_id, status="generating")
