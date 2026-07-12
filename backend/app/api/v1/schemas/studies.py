# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-template, query-set, per-query, study, and trial models (feat_study_lifecycle)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.api.v1._wire_types import (
    EngineTypeWire,
    ObjectiveDirection,
    ObjectiveK,
    ObjectiveMetric,
    PrunerKind,
    SamplerKind,
    StudyStatusWire,
    TrialStatusWire,
)
from backend.app.domain.study.chain_summary import ChainStopReason
from backend.app.domain.study.confidence import ConfidenceShape
from backend.app.domain.study.convergence import ConvergenceVerdict, StudyConvergenceShape

# ---------------------------------------------------------------------------
# feat_study_lifecycle Phase 2 — query-template / query-set / study / trial
# schemas. Per CLAUDE.md "Enumerated Value Contract Discipline" every wire
# Literal carries a source-of-truth comment.
# ---------------------------------------------------------------------------


# --- Query template -------------------------------------------------------


class CreateQueryTemplateRequest(BaseModel):
    """Request body for ``POST /api/v1/query-templates``."""

    # Path-safe pattern (security audit 2026-07-12): the name is interpolated
    # into the params-file path (`{name}.params.json`) by the open_pr worker.
    # Must start alphanumeric and exclude path separators so a name like
    # `../.github/workflows/x` can't relocate the written file within the repo
    # branch (the clone-root containment check bounds the host FS but not the
    # intended config_path subtree). Allows the usual kebab/snake/dotted names.
    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    engine_type: EngineTypeWire
    body: str = Field(min_length=1)
    declared_params: dict[str, str] = Field(default_factory=dict)
    parent_id: str | None = None


class QueryTemplateDetail(BaseModel):
    """``GET /api/v1/query-templates/{id}`` response."""

    id: str
    name: str
    engine_type: EngineTypeWire
    body: str
    declared_params: dict[str, str]
    version: int
    parent_id: str | None
    created_at: datetime


class QueryTemplateSummary(BaseModel):
    """List-view shape; drops ``body`` + the full ``declared_params`` dict.

    Surfaces ``param_count`` (= ``len(declared_params)``) so the
    templates list can show each template's tuning surface at a glance.
    ``param_count`` is free to compute — ``declared_params`` is a JSONB
    column already loaded on the row (not a child relationship), so the
    count is ``len(row.declared_params)`` with no extra query and no
    N+1 risk. The full dict remains on ``QueryTemplateDetail``.
    """

    id: str
    name: str
    engine_type: EngineTypeWire
    version: int
    param_count: int
    created_at: datetime


class QueryTemplateListResponse(BaseModel):
    """``GET /api/v1/query-templates`` response."""

    data: list[QueryTemplateSummary]
    next_cursor: str | None
    has_more: bool


# --- Query set + queries --------------------------------------------------


class CreateQuerySetRequest(BaseModel):
    """``POST /api/v1/query-sets`` body.

    ``cluster_id`` is required because Phase 1's shipped schema has
    ``query_sets.cluster_id NOT NULL``. Spec FR-3 wording (``cluster_id?``)
    is documented drift tracked at
    ``docs/00_overview/planned_features/chore_spec_query_set_cluster_id_drift/idea.md``.
    """

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    cluster_id: str = Field(min_length=1, max_length=36)


class QuerySetDetail(BaseModel):
    """``GET /api/v1/query-sets/{id}`` response."""

    id: str
    name: str
    description: str | None
    cluster_id: str
    query_count: int
    created_at: datetime


class QuerySetSummary(BaseModel):
    """List-view shape.

    ``query_count`` is the number of queries in the set. It is resolved
    via a single batched ``GROUP BY query_set_id`` aggregate per page
    (``repo.count_queries_for_sets``), NOT a per-row count — so the
    list endpoint stays at a fixed 2 queries (the page + the count
    aggregate) regardless of page size. This is the same no-N+1 pattern
    ``feat_studies_convergence_visibility`` (PR #421) used for the
    studies-list ``trial_count`` field.
    """

    id: str
    name: str
    cluster_id: str
    query_count: int
    created_at: datetime


class QuerySetListResponse(BaseModel):
    """``GET /api/v1/query-sets`` response."""

    data: list[QuerySetSummary]
    next_cursor: str | None
    has_more: bool


class BulkQueryItem(BaseModel):
    """One query in a JSON bulk-upload."""

    query_text: str = Field(min_length=1, max_length=4000)
    reference_answer: str | None = None
    query_metadata: dict[str, Any] | None = None


class BulkQueriesJsonRequest(BaseModel):
    """``POST /api/v1/query-sets/{id}/queries`` JSON body."""

    queries: list[BulkQueryItem] = Field(min_length=1, max_length=10_000)


class BulkQueriesResponse(BaseModel):
    """``POST /api/v1/query-sets/{id}/queries`` response."""

    added: int


# --- feat_query_inline_crud: per-query CRUD --------------------------------


class QueryRow(BaseModel):
    """Wire row returned by the per-query GET + PATCH endpoints.

    Used by both ``GET /api/v1/query-sets/{set_id}/queries`` and
    ``PATCH /api/v1/query-sets/{set_id}/queries/{query_id}``.
    ``judgment_count`` is a derived field — single batched GROUP BY in the
    router via :func:`backend.app.db.repo.judgment.count_judgments_per_query`.
    """

    id: str
    query_text: str
    reference_answer: str | None
    query_metadata: dict[str, Any] | None
    judgment_count: int


class QueryListResponse(BaseModel):
    """``GET /api/v1/query-sets/{set_id}/queries`` response."""

    data: list[QueryRow]
    next_cursor: str | None
    has_more: bool


class UpdateQueryRequest(BaseModel):
    """``PATCH /api/v1/query-sets/{set_id}/queries/{query_id}`` body.

    Whole-object replace on ``query_metadata`` (NOT deep-merge); explicit
    ``null`` removes a nullable field; omitted key = no change. Empty
    body ``{}`` validates as a no-op (AC-28).

    ``query_text`` is NOT NULL on the underlying table, so explicit-null
    is rejected by the ``@model_validator`` below (a 422 surfaces sooner
    than the SQL ``NotNullViolation``).
    """

    model_config = ConfigDict(extra="forbid")
    query_text: str | None = Field(default=None, min_length=1, max_length=4000)
    reference_answer: str | None = None  # explicit None → NULL the column
    query_metadata: dict[str, Any] | None = None  # whole-object replace

    @model_validator(mode="after")
    def _reject_explicit_null_query_text(self) -> UpdateQueryRequest:
        if "query_text" in self.model_fields_set and self.query_text is None:
            raise ValueError("query_text cannot be null (column is NOT NULL)")
        return self


class JudgmentListRef(BaseModel):
    """One entry in the ``QUERY_HAS_JUDGMENTS`` 409 envelope.

    Lives in ``detail.judgment_lists``. Maps from the repo-layer
    :class:`backend.app.db.repo.judgment.JudgmentListRefRow` at the
    router boundary.
    """

    id: str
    name: str


class QueryHasJudgmentsDetail(BaseModel):
    """The ``detail`` object of a 409 ``QUERY_HAS_JUDGMENTS`` response.

    Extends the canonical ``{error_code, message, retryable}`` envelope
    with two structured fields the frontend consumes directly
    (``judgment_lists`` + ``overflow_count``). Wired into the FastAPI
    route's ``responses={409: {"model": QueryHasJudgmentsEnvelope}}`` so
    the OpenAPI schema documents the contract.
    """

    error_code: Literal["QUERY_HAS_JUDGMENTS"]
    message: str
    retryable: Literal[False]
    judgment_lists: list[JudgmentListRef]  # up to 10 entries, alphabetical
    overflow_count: int  # max(0, total_list_count - 10)


class QueryHasJudgmentsEnvelope(BaseModel):
    """Top-level 409 wrapper (FastAPI nests under ``detail`` for HTTPException)."""

    detail: QueryHasJudgmentsDetail


# --- Study ---------------------------------------------------------------


_K_REQUIRED_METRICS: frozenset[str] = frozenset({"ndcg", "precision", "recall"})


class ObjectiveSpec(BaseModel):
    """Wire shape of ``studies.objective`` (write-side validated at create).

    ``k`` is required for ``ndcg`` / ``precision`` / ``recall`` (per
    standard IR-evaluation conventions: those metrics are computed at a
    cutoff rank). ``map`` accepts ``k`` optionally; ``mrr`` / ``err`` ignore
    it. The model_validator enforces this so a malformed objective
    surfaces as 400 ``INVALID_SEARCH_SPACE`` / 422 ``VALIDATION_ERROR``
    at study-create time rather than failing later inside ``run_trial``
    when the worker computes the metric.
    """

    metric: ObjectiveMetric
    k: ObjectiveK | None = None
    direction: ObjectiveDirection = "maximize"

    @model_validator(mode="after")
    def _require_k_for_cutoff_metrics(self) -> ObjectiveSpec:
        if self.metric in _K_REQUIRED_METRICS and self.k is None:
            raise ValueError(
                f"objective.k is required when metric is one of "
                f"{sorted(_K_REQUIRED_METRICS)}; got metric={self.metric!r} k=None"
            )
        return self


class StudyConfigSpec(BaseModel):
    """Wire shape of ``studies.config`` (write-side).

    The model_validator below enforces that at least one stop condition is
    set — otherwise the study has no terminating condition (FR-4).
    ``parallelism`` / ``trial_timeout_s`` are optional; when absent the
    worker reads ``Settings.studies_default_parallelism`` /
    ``studies_default_timeout_s`` at job time. The API layer does NOT
    materialize these fields into the stored row — see Story 1.5 +
    Story 3.3's ``config.model_dump(exclude_none=True, exclude_unset=True)``
    contract.
    """

    max_trials: int | None = Field(default=None, ge=1, le=100_000)
    time_budget_min: float | None = Field(default=None, gt=0)
    parallelism: int | None = Field(default=None, ge=1, le=64)
    trial_timeout_s: int | None = Field(default=None, ge=5, le=3600)
    sampler: SamplerKind | None = None
    pruner: PrunerKind | None = None
    seed: int | None = None
    secondary_metrics: list[str] | None = None
    baseline_params: dict[str, str | int | float | bool | None] | None = None
    """feat_study_baseline_trial FR-6: explicit baseline-trial params (tier
    b of the resolver fallback). Stored as-is inside ``studies.config``
    JSONB. Discriminated-value dict forbids nested objects/arrays —
    Pydantic emits ``VALIDATION_ERROR`` (422) on violation. Stays in
    ``config`` (not a top-level column) per spec D-7."""
    auto_followup_depth: int | None = Field(default=None)
    """feat_auto_followup_studies FR-1 + D-12: 0..5 valid; 0 is the
    worker-internal terminal-state value (operators set None to opt out).
    Bound check is done via ``_validate_auto_followup_depth`` below — NOT
    via Field(ge, le) — so the project's canonical error envelope can
    carry ``AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`` per spec §8.5 (the prefix
    parser in :mod:`backend.app.api.errors` picks up the ``<CODE>:``
    prefix from the raised ValueError message)."""
    auto_followup_strategy: str | None = Field(default=None)
    """feat_overnight_final_solution FR-1 + D-13: ``"narrow"`` | ``"follow_suggestions"``
    | ``None`` (treated as ``"narrow"`` by the worker).

    **Field type is ``str | None`` (NOT ``Literal[...]``)** — per spec D-13,
    a field-level ``Literal`` would surface bad values as Pydantic's generic
    ``VALIDATION_ERROR`` envelope BEFORE the ``mode="after"`` validator
    could emit the canonical ``AUTO_FOLLOWUP_STRATEGY_INVALID`` code. Same
    pattern as ``auto_followup_depth`` above: enum check + pair rule done
    in :meth:`_validate_auto_followup_strategy` via the ``<CODE>:`` prefix
    convention so :func:`backend.app.api.errors.validation_exception_handler`
    unwraps the canonical envelope. The two accepted values are exposed as
    the module-level :data:`AUTO_FOLLOWUP_STRATEGY_VALUES` tuple (consumed
    by the CI source-of-truth grep gate and mirrored as
    ``OVERNIGHT_STRATEGY_VALUES`` in ``ui/src/lib/enums.ts``)."""

    @model_validator(mode="before")
    @classmethod
    def _reject_worker_managed_keys(cls, data: object) -> object:
        """Reject operator-submitted worker-managed JSONB keys (D-14).

        ``auto_followup_visited_template_ids`` + ``auto_followup_selected_kind``
        are written ONLY by the autopilot worker on chain children. Allowing
        the wizard to seed them would break the single-writer rule for the
        cycle-guard list and risk spoofed badges on the chain panel.

        ``StudyConfigSpec`` defaults to ``extra="ignore"`` (Pydantic default
        — no ``model_config`` declared above), so an unknown key is silently
        dropped before any ``mode="after"`` validator runs. This
        ``mode="before"`` validator inspects the raw dict so the keys
        actually get rejected with the canonical envelope.

        We deliberately do NOT set ``extra="forbid"`` model-wide: that would
        broaden the blast radius and reject any future config key during
        rollout (a stored config re-validated through this model in a
        worker would fail).
        """
        if not isinstance(data, dict):
            return data
        forbidden_keys = (
            "auto_followup_visited_template_ids",
            "auto_followup_selected_kind",
        )
        for key in forbidden_keys:
            if key in data:
                raise ValueError(
                    f"AUTO_FOLLOWUP_STRATEGY_INVALID: config.{key} is worker-managed "
                    "and may not be set at study creation"
                )
        return data

    @model_validator(mode="after")
    def _require_one_stop_condition(self) -> StudyConfigSpec:
        if self.max_trials is None and self.time_budget_min is None:
            raise ValueError(
                "studies.config must specify at least one of `max_trials` or "
                "`time_budget_min` — otherwise the study has no terminating "
                "stop condition"
            )
        return self

    @model_validator(mode="after")
    def _validate_auto_followup_depth(self) -> StudyConfigSpec:
        """feat_auto_followup_studies FR-1: range check with error-code prefix.

        The ``AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE:`` prefix is recognized by
        :func:`backend.app.api.errors.validation_exception_handler`, which
        unwraps it into the response envelope's ``error_code`` field.
        """
        if self.auto_followup_depth is not None and not (0 <= self.auto_followup_depth <= 5):
            raise ValueError(
                "AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE: config.auto_followup_depth "
                f"must be between 0 and 5 inclusive when set; "
                f"got {self.auto_followup_depth}"
            )
        return self

    @model_validator(mode="after")
    def _validate_auto_followup_strategy(self) -> StudyConfigSpec:
        """feat_overnight_final_solution FR-1 + D-13: enum + pair check.

        Two rules: (a) value MUST be in :data:`AUTO_FOLLOWUP_STRATEGY_VALUES`
        when set, (b) value MUST only be set when ``auto_followup_depth >= 1``
        (a strategy choice on a depth-0 study is meaningless).

        Both surface as ``AUTO_FOLLOWUP_STRATEGY_INVALID`` via the
        ``<CODE>:`` prefix convention (allowlisted in
        :data:`backend.app.api.errors._CUSTOM_ERROR_CODE_ALLOWLIST`).
        """
        if self.auto_followup_strategy is None:
            return self
        if self.auto_followup_strategy not in AUTO_FOLLOWUP_STRATEGY_VALUES:
            raise ValueError(
                "AUTO_FOLLOWUP_STRATEGY_INVALID: config.auto_followup_strategy "
                f"must be 'narrow' or 'follow_suggestions'; "
                f"got {self.auto_followup_strategy!r}"
            )
        if self.auto_followup_depth is None or self.auto_followup_depth < 1:
            raise ValueError(
                "AUTO_FOLLOWUP_STRATEGY_INVALID: config.auto_followup_strategy "
                "only applies when config.auto_followup_depth >= 1"
            )
        return self


# feat_overnight_final_solution Story 1.1 / D-13 — wire-value source of truth
# for ``StudyConfigSpec.auto_followup_strategy``. Mirrored by the frontend
# ``OVERNIGHT_STRATEGY_VALUES`` in ``ui/src/lib/enums.ts`` and consumed by
# the CI grep gate at ``scripts/ci/verify_enum_source_of_truth.sh``. Keep
# this declaration module-level (NOT inside the class) so the grep gate's
# AST resolver finds the bare tuple assignment.
AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")


class ParentFollowupRef(BaseModel):
    """Optional lineage payload on ``POST /api/v1/studies``.

    feat_digest_executable_followups FR-11 — when the operator clicks
    "Run this followup" on a proposal's digest card, the create-study
    payload carries the parent proposal's id + the 0-based index into
    the digest's ``suggested_followups`` array so the spawned study
    remembers where it came from.

    ``proposal_id`` is a UUIDv7 (36-char hex). The exact-length bound
    forces malformed strings to surface as 422 ``VALIDATION_ERROR``
    rather than reach the DB FK check and emerge as a 404
    ``PROPOSAL_NOT_FOUND``.
    """

    proposal_id: str = Field(min_length=36, max_length=36)
    followup_index: int = Field(ge=0)


class CreateStudyRequest(BaseModel):
    """``POST /api/v1/studies`` body.

    ``search_space`` is validated post-Pydantic-parse via
    :class:`backend.app.domain.study.search_space.SearchSpace` so
    :exc:`pydantic.ValidationError` produces the spec's 400
    ``INVALID_SEARCH_SPACE`` (per Story 3.3 task 2).

    feat_digest_executable_followups Story 4.2 — optional ``parent`` field
    records the parent proposal + followup-index lineage when the study
    was spawned from a digest "Run this followup" action (FR-11).
    """

    name: str = Field(min_length=1, max_length=256)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    template_id: str = Field(min_length=1, max_length=36)
    query_set_id: str = Field(min_length=1, max_length=36)
    judgment_list_id: str = Field(min_length=1, max_length=36)
    search_space: dict[str, Any]
    objective: ObjectiveSpec
    config: StudyConfigSpec
    parent: ParentFollowupRef | None = None
    parent_study_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
        description=(
            "feat_study_clone_from_previous FR-7 — when the operator clones an "
            "existing study via the study-detail Clone button, this carries the "
            "source study's id. Server validates existence (404 "
            "PARENT_STUDY_NOT_FOUND) and same-cluster (422 "
            "PARENT_STUDY_WRONG_CLUSTER) before persisting to studies.parent_study_id. "
            "Independent of the proposal-lineage 'parent' field (D-5); both may be set."
        ),
    )


class TrialsSummaryShape(BaseModel):
    """The ``trials_summary`` field embedded in :class:`StudyDetail`."""

    total: int
    complete: int
    failed: int
    pruned: int
    best_primary_metric: float | None


class StudyDetail(BaseModel):
    """``GET /api/v1/studies/{id}`` response + ``POST/cancel`` response."""

    id: str
    name: str
    cluster_id: str
    target: str
    template_id: str
    query_set_id: str
    judgment_list_id: str
    search_space: dict[str, Any]
    objective: dict[str, Any]
    config: dict[str, Any]
    status: StudyStatusWire
    failed_reason: str | None
    optuna_study_name: str
    parent_study_id: str | None
    baseline_metric: float | None
    baseline_trial_id: str | None
    best_metric: float | None
    best_trial_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    trials_summary: TrialsSummaryShape
    confidence: ConfidenceShape | None = None
    """Per-study metric-confidence analytics (feat_pr_metric_confidence FR-5a).

    ``None`` when the study has no winner trial (still running or
    ``best_trial_id`` points at a deleted row — AC-3a). Otherwise a partial
    or full :class:`ConfidenceShape` per FR-7's graceful-degradation
    contract."""
    convergence: StudyConvergenceShape | None = None
    """Per-study convergence verdict (feat_study_convergence_indicator FR-4).

    ``None`` for in-flight studies (``queued`` / ``running``), studies whose
    usable Optuna-trial count is below ``CONVERGENCE_FLAT_MIN_COMPLETE`` (5),
    or the graceful-degrade null paths emitted by ``fetch_study_convergence``
    (invalid persisted ``direction``; classifier exception). Otherwise a
    populated :class:`StudyConvergenceShape` carrying the verdict
    (``converged`` / ``still_improving`` / ``too_few_trials``), the
    best-so-far curve, the trailing-window numerics, and the comparison
    constants (epsilon, warmup floor) for the UI panel and the digest
    narrative. Distinct from ``confidence.convergence.regime`` — that field
    classifies *winner-trial timing* (early_held / late_rising / noisy),
    while this field classifies *metric plateau*."""


class StudyChainLink(BaseModel):
    """One link in the rolled-up overnight-chain summary (feat_overnight_autopilot §8.3)."""

    id: str
    name: str
    status: StudyStatusWire
    best_metric: float | None
    baseline_metric: float | None
    direction: ObjectiveDirection
    delta_from_prev: float | None
    """null for the anchor OR when either side's best_metric is null; else
    direction-normalized ``this.best_metric - prev.best_metric``."""
    proposal_id: str | None
    auto_followup_depth_remaining: int | None
    """``studies.config.get('auto_followup_depth')`` — null when key absent,
    0 when the post-decrement leaf."""
    failed_reason: str | None
    created_at: datetime
    completed_at: datetime | None
    template_id: str
    """``studies.template_id`` — needed by the chain panel's swap_template
    badge so the frontend can resolve the target template's display name
    via ``GET /api/v1/query-templates/{id}``. Added by Story 3.1 per
    P1-B5 (the badge is otherwise not buildable from the chain payload
    alone). Non-optional — every study has a template."""
    selected_followup_kind: Literal["narrow_default", "narrow", "widen", "swap_template"] | None = (
        None
    )
    """feat_overnight_final_solution Story 3.1 / FR-6 — the path
    :func:`backend.app.workers.auto_followup.enqueue_followup_study` took
    when creating this link. ``null`` for the anchor (no parent
    follow-up to consume) and for every link created under the legacy
    ``"narrow"`` strategy (per D-12 the legacy path persists no
    ``auto_followup_selected_kind`` key). The chain endpoint applies a
    defensive coercion before populating this field: an unknown JSONB
    value in ``studies.config.auto_followup_selected_kind`` (manual DB
    INSERT, schema drift) coerces to ``null`` + a
    ``chain_selected_kind_unknown`` WARN — never raises a Pydantic
    ``ValidationError`` that would 500 the endpoint. Mirrored
    character-for-character by ``ui/src/lib/enums.ts SELECTED_FOLLOWUP_KIND_VALUES``
    (Story 3.2)."""


class StudyChainResponse(BaseModel):
    """``GET /api/v1/studies/{id}/chain`` response (feat_overnight_autopilot §8.3)."""

    anchor_study_id: str
    best_link_id: str | None
    best_metric: float | None
    cumulative_lift: float | None
    direction: ObjectiveDirection
    stop_reason: ChainStopReason
    """Derived per spec §9. Values must match
    backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS."""
    proposal_id_for_best_link: str | None
    links: list[StudyChainLink]


class RecentChainSummary(BaseModel):
    """One row in the ``GET /api/v1/studies/chains/recent`` response.

    Per spec §8.1 (feat_overnight_studies_summary_card). Per-chain
    rollup feeding the "Ran while you were away" card on ``/studies``
    — anchor identity + chain length + the best link's metric + the
    chain's cumulative lift + the derived stop reason + the
    surfaceable proposal id for the best link. Read-only; no state
    transitions, no audit events.
    """

    anchor_study_id: str
    anchor_name: str
    chain_length: int
    """``len(traversal.links)`` — guaranteed ``>= 2`` by the discovery
    repo (FR-1)."""
    best_metric: float | None
    """``None`` when every link's ``best_metric IS NULL`` (e.g. a
    terminal-failed chain). The card renders the stop-reason phrase in
    place of the numeric line on this path (AC-11)."""
    objective_metric: str
    """``traversal.links[0].objective.get('metric')`` — surfaced so the
    card can render "Best <metric>: <value>" without an extra request."""
    cumulative_lift: float | None
    """Direction-normalized lift via
    :func:`backend.app.domain.study.chain_summary.compute_cumulative_lift`.
    ``None`` when the completed-link subset is empty OR no baseline is
    derivable (mirrors the chain panel's null-lift contract)."""
    direction: ObjectiveDirection
    stop_reason: ChainStopReason
    """Derived per spec §9. Values must match
    backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS."""
    best_link_proposal_id: str | None
    """The selected (newest non-rejected) proposal for the best link,
    surfaced so the card's "Review chain" link can deep-link directly
    to the proposal when one exists."""
    tail_completed_at: datetime
    """``traversal.links[-1].completed_at`` — the chain tail's terminal
    timestamp. Drives the card's localStorage dismissal cutoff
    (``max(tail_completed_at) + 1ms`` per FR-5)."""


class RecentChainsResponse(BaseModel):
    """``GET /api/v1/studies/chains/recent`` response shape.

    Inert pagination: this endpoint emits ``next_cursor=null`` and
    ``has_more=false`` always (OQ-2 resolved — limit-cap only). The
    fields stay on the wire for consistency with the rest of the
    studies surface, so a future MVP3 keyset-pagination story can
    populate them without breaking clients (idea filed in this PR).
    """

    data: list[RecentChainSummary]
    next_cursor: str | None = None
    has_more: bool = False


class StudySummary(BaseModel):
    """List-view shape."""

    id: str
    name: str
    cluster_id: str
    status: StudyStatusWire
    baseline_metric: float | None = None
    """Starting metric: the off-band non-Optuna baseline-trial score (the
    default/initial config's performance before optimization), surfaced so
    the studies-list UI can render a ``starting → best`` delta beside the
    winner — the same ``baseline_metric → best_metric`` framing the study
    detail page's digest panel already shows. ``None`` until the baseline
    trial completes, when baseline is skipped/failed, or for studies that
    predate ``feat_study_baseline_trial``. Defaults to ``None`` for
    backward compatibility on hand-constructed instances in tests; the live
    API always populates it from ``studies.baseline_metric``."""
    best_metric: float | None
    direction: ObjectiveDirection = "maximize"
    """Objective direction, surfaced so the studies-list UI can label a
    ``best_metric`` correctly. The CEILING badge (``best_metric >= 0.99``)
    is only meaningful for ``maximize`` objectives — for ``minimize`` a
    0.99 is a *bad* score, not a ceiling. Defaults to ``maximize`` so
    pre-``feat_study_baseline_trial`` studies whose ``objective`` JSON
    predates the ``direction`` key still render correctly. Per
    ``bug_ceiling_badge_assumes_maximize_direction``."""
    created_at: datetime
    completed_at: datetime | None
    trial_count: int = 0
    """Non-baseline trial-row count for this study, matching the detail
    page's ``trials_summary.total`` exactly (both use
    ``is_baseline.is_(False)``). A ``max_trials=50`` study with a
    completed baseline shows ``trial_count=50``. Computed per request via
    one batched ``GROUP BY study_id`` aggregate
    (``count_trials_for_studies``); see
    ``feat_studies_convergence_visibility`` Story 1.1 / FR-1. Default
    ``0`` for backward compatibility on hand-constructed instances in
    tests; the live API always populates it."""
    convergence_verdict: ConvergenceVerdict | None = None
    """Per-study convergence verdict literal (NOT the full
    :class:`StudyConvergenceShape` — list payload only). Equal to
    ``StudyDetail.convergence.verdict`` for every case (in-flight /
    invalid-direction / ``<5`` / ``5–49`` / ``≥50``) — see AC-2 + AC-3b
    in ``feat_studies_convergence_visibility/feature_spec.md``. Computed
    via :func:`backend.app.services.study_convergence.resolve_list_convergence_verdicts`
    using the same gate order as ``fetch_study_convergence``
    (in-flight → direction → count → classifier). ``None`` for in-flight
    studies, invalid-direction completed studies, ``< 5`` complete
    non-baseline trials, and the graceful-degrade exception path; never
    raises."""


class StudyListResponse(BaseModel):
    """``GET /api/v1/studies`` response."""

    data: list[StudySummary]
    next_cursor: str | None
    has_more: bool


# --- Trial ---------------------------------------------------------------


class TrialDetail(BaseModel):
    """``GET /api/v1/studies/{id}/trials`` response row."""

    id: str
    study_id: str
    optuna_trial_number: int
    params: dict[str, Any]
    primary_metric: float | None
    metrics: dict[str, Any]
    duration_ms: int | None
    status: TrialStatusWire
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None
    is_baseline: bool = False
    """feat_study_baseline_trial FR-8 — TRUE only for the off-band
    non-Optuna baseline trial. The frontend uses this to filter the
    trials-table by default and to render the "Baseline" badge under the
    "Show baseline trial" toggle (FR-9)."""


class TrialListResponse(BaseModel):
    """``GET /api/v1/studies/{id}/trials`` response."""

    data: list[TrialDetail]
    next_cursor: str | None
    has_more: bool
