"""Pydantic request / response models for ``/api/v1/clusters`` (Story 3.2).

Per cycle 1 F2 + cycle 2 F1: ``engine_type`` and ``auth_kind`` are typed as
``str`` (NOT ``Literal[...]``) so unknown values reach the service layer and
surface as the spec's domain-specific 400 codes (``ENGINE_NOT_SUPPORTED`` /
``AUTH_KIND_NOT_SUPPORTED``). A Pydantic ``Literal`` would short-circuit at
validation and produce a generic 422 ``VALIDATION_ERROR``, contradicting
spec FR-5.

``environment`` IS ``Literal[...]`` because spec §8.5 defines no
``ENVIRONMENT_NOT_SUPPORTED`` code — invalid values legitimately surface as
422 ``VALIDATION_ERROR`` (cycle 2 F1 / cycle 3 F3 fix). **Do NOT change this
back to ``str``.**
"""

from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.adapters.protocol import TargetInfo
from backend.app.core.settings import get_settings
from backend.app.domain.study.confidence import ConfidenceShape as ConfidenceShape

# ``ConfidenceShape`` is defined in :mod:`backend.app.domain.study.confidence`
# (the canonical assembler module per Story 1.3). The explicit ``as`` re-export
# above keeps it importable via ``from backend.app.api.v1.schemas import
# ConfidenceShape`` under mypy strict's ``no_implicit_reexport``.

EngineType = Literal["elasticsearch", "opensearch"]
"""Response-only: values are guaranteed by service-layer validation before the
DB write, so the response model is safe to lock down with ``Literal``."""

Environment = Literal["prod", "staging", "dev"]
"""Both request- and response-side: spec §8.5 has no ENVIRONMENT_NOT_SUPPORTED
domain code, so invalid values surface as 422 VALIDATION_ERROR via Pydantic."""

AuthKind = Literal["es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4"]
"""Response-only — see EngineType note."""

HealthStatusValue = Literal["green", "yellow", "red", "unreachable"]


class HealthCheckResult(BaseModel):
    """Wire shape of the per-cluster health probe (mirrors ``HealthStatus``)."""

    status: HealthStatusValue
    version: str | None = None
    checked_at: str
    error: str | None = None


class CreateClusterRequest(BaseModel):
    """Request body for ``POST /api/v1/clusters``.

    See module docstring for the deliberate ``str`` vs ``Literal`` split.
    """

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    engine_type: str = Field(min_length=1, max_length=64)
    environment: Environment
    base_url: str = Field(min_length=1, max_length=512)
    auth_kind: str = Field(min_length=1, max_length=64)
    credentials_ref: str = Field(min_length=1, max_length=128)
    engine_config: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    target_filter: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description=(
            "Optional glob pattern (fnmatch.fnmatchcase: *, ?, [seq], [!seq]; "
            "no brace expansion). Scopes GET /clusters/{id}/targets to "
            "matching index names. Null = no filter."
        ),
    )

    @field_validator("target_filter", mode="before")
    @classmethod
    def strip_target_filter(cls, v: Any) -> Any:
        """Strip whitespace BEFORE min_length/max_length run (feat_cluster_target_filter FR-2).

        Pydantic v2 default validator mode is ``after`` — that would let a
        padded valid filter like ``"  " + "x"*256`` fail max_length=256 even
        though the stripped value is exactly 256 chars. ``mode="before"`` runs
        the strip first; ``min_length=1`` then catches the empty/whitespace-only
        case and ``max_length=256`` runs on the stripped value.

        Glob syntax is NOT validated — Python ``fnmatch`` is permissive (every
        non-empty string is a valid glob). A pattern that matches nothing at
        runtime surfaces via the create-study modal's empty-state, not a 422.
        """
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Validate scheme + host per spec §10 Threat 3.

        * Scheme must be http or https (other schemes → 422).
        * Host must not be a private-range / loopback IP unless
          ``RELYLOOP_ALLOW_PRIVATE_CLUSTERS`` is True (default for MVP1).
        * Hostnames (non-IP) always pass — DNS resolution is intentionally
          NOT performed at validation time (it would require DNS I/O on
          every POST and isn't load-bearing for the MVP1 threat model).
        """
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("base_url must include a host")
        try:
            ip = ip_address(parsed.hostname)
        except ValueError:
            return v  # hostname; skip private-IP check
        if (ip.is_private or ip.is_loopback) and not get_settings().relyloop_allow_private_clusters:
            raise ValueError(
                f"base_url host {parsed.hostname} is a private-range IP "
                f"and RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
            )
        return v


class ClusterDetail(BaseModel):
    """``GET /api/v1/clusters/{id}`` response."""

    id: str
    name: str
    engine_type: EngineType
    environment: Environment
    base_url: str
    auth_kind: AuthKind
    engine_config: dict[str, Any] | None = None
    notes: str | None = None
    target_filter: str | None = None
    created_at: datetime
    health_check: HealthCheckResult


class ClusterSummary(BaseModel):
    """List-view; drops engine_config + notes for brevity."""

    id: str
    name: str
    engine_type: EngineType
    environment: Environment
    base_url: str
    auth_kind: AuthKind
    target_filter: str | None = None
    created_at: datetime
    health_check: HealthCheckResult


class ClusterListResponse(BaseModel):
    """Paginated list response."""

    data: list[ClusterSummary]
    next_cursor: str | None
    has_more: bool


class TargetListResponse(BaseModel):
    """Response for ``GET /api/v1/clusters/{cluster_id}/targets`` (FR-1).

    Unpaginated by design — see feature_spec.md §7.1 "pagination shape
    rationale". The single-resource lookup pattern matches
    ``/clusters/{id}/schema`` rather than the queryable ``/clusters`` list.
    ``EntitySelectListPage<T>``'s ``next_cursor`` and ``has_more`` fields
    are optional, so this bare ``data``-only shape consumes correctly on
    the frontend without pretending to be a cursor endpoint.
    """

    data: list[TargetInfo]


class RunQueryRequest(BaseModel):
    """``POST /api/v1/clusters/{id}/run_query`` body."""

    target: str = Field(min_length=1, max_length=256)
    query_dsl: dict[str, Any]
    top_k: int = Field(default=10, ge=1, le=1000)


class RunQueryHit(BaseModel):
    """One hit in the ``run_query`` response."""

    doc_id: str
    score: float
    source: dict[str, Any] | None = None


class RunQueryResponse(BaseModel):
    """``POST /api/v1/clusters/{id}/run_query`` response."""

    hits: list[RunQueryHit]


# ---------------------------------------------------------------------------
# feat_study_lifecycle Phase 2 — query-template / query-set / study / trial
# schemas. Per CLAUDE.md "Enumerated Value Contract Discipline" every wire
# Literal carries a source-of-truth comment.
# ---------------------------------------------------------------------------


# Values must match backend/app/adapters/elastic.py SUPPORTED_ENGINE_TYPES.
EngineTypeWire = Literal["elasticsearch", "opensearch"]

# Values must match backend/app/db/models/study.py CHECK constraint AND
# backend/app/db/repo/study.py StudyStatusFilter Literal.
StudyStatusWire = Literal["queued", "running", "completed", "cancelled", "failed"]

# Values must match backend/app/eval/scoring.py SUPPORTED_METRICS frozenset.
# ERR@k is deferred to MVP2 per infra_optuna_eval feature_spec.md §3 / §FR-3 / §13.
ObjectiveMetric = Literal["ndcg", "map", "precision", "recall", "mrr"]

# Values must match backend/app/eval/scoring.py SUPPORTED_K_VALUES frozenset.
ObjectiveK = Literal[1, 3, 5, 10, 20, 50, 100]

ObjectiveDirection = Literal["maximize", "minimize"]

# Values must match backend/app/eval/types.py SamplerKind Literal.
SamplerKind = Literal["tpe", "random"]

# Values must match backend/app/eval/types.py PrunerKind Literal.
PrunerKind = Literal["median", "none"]

# Values must match backend/app/db/repo/trial.py TrialSortKey Literal.
TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "ended_at_desc",
    "ended_at_asc",
    "optuna_trial_number_asc",
]

# Values must match backend/app/db/models/trial.py CHECK constraint.
TrialStatusWire = Literal["complete", "failed", "pruned"]


# ---------------------------------------------------------------------------
# DataTable sort-key Literals (feat_data_table_primitive Story 1.3)
#
# Each ``<Resource>SortKey`` is the cross-product of sortable columns × {asc, desc}
# accepted by ``GET /api/v1/<resource>?sort=<value>``. Frontend mirrors these
# arrays in ``ui/src/lib/enums.ts`` (CI grep gate enforces parity).
# ---------------------------------------------------------------------------

# Values must match ui/src/lib/enums.ts CLUSTER_SORT_VALUES.
ClusterSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "environment:asc",
    "environment:desc",
]

# Values must match ui/src/lib/enums.ts STUDY_SORT_VALUES.
StudySortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "completed_at:asc",
    "completed_at:desc",
    "best_metric:asc",
    "best_metric:desc",
    "status:asc",
    "status:desc",
]

# Values must match ui/src/lib/enums.ts QUERY_SET_SORT_VALUES.
QuerySetSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
]

# Values must match ui/src/lib/enums.ts QUERY_TEMPLATE_SORT_VALUES.
QueryTemplateSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "engine_type:asc",
    "engine_type:desc",
    "version:asc",
    "version:desc",
]

# Values must match ui/src/lib/enums.ts JUDGMENT_LIST_SORT_VALUES.
JudgmentListSortKey = Literal[
    "name:asc",
    "name:desc",
    "created_at:asc",
    "created_at:desc",
    "status:asc",
    "status:desc",
]

# Values must match ui/src/lib/enums.ts JUDGMENT_ROW_SORT_VALUES.
JudgmentRowSortKey = Literal[
    "created_at:asc",
    "created_at:desc",
    "rating:asc",
    "rating:desc",
    "source:asc",
    "source:desc",
]

# Values must match ui/src/lib/enums.ts PROPOSAL_SORT_VALUES.
ProposalSortKey = Literal[
    "created_at:asc",
    "created_at:desc",
    "status:asc",
    "status:desc",
    "pr_state:asc",
    "pr_state:desc",
]


# --- Query template -------------------------------------------------------


class CreateQueryTemplateRequest(BaseModel):
    """Request body for ``POST /api/v1/query-templates``."""

    name: str = Field(min_length=1, max_length=256)
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
    """List-view shape; drops ``body`` + ``declared_params`` for brevity."""

    id: str
    name: str
    engine_type: EngineTypeWire
    version: int
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
    ``docs/02_product/planned_features/chore_spec_query_set_cluster_id_drift/idea.md``.
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
    """List-view shape; omits ``query_count`` to avoid N+1 counts at list time."""

    id: str
    name: str
    cluster_id: str
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
    pytrec_eval semantics: those metrics are computed at a cutoff
    rank). ``map`` accepts ``k`` optionally; ``mrr`` / ``err`` ignore
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

    @model_validator(mode="after")
    def _require_one_stop_condition(self) -> StudyConfigSpec:
        if self.max_trials is None and self.time_budget_min is None:
            raise ValueError(
                "studies.config must specify at least one of `max_trials` or "
                "`time_budget_min` — otherwise the study has no terminating "
                "stop condition"
            )
        return self


class CreateStudyRequest(BaseModel):
    """``POST /api/v1/studies`` body.

    ``search_space`` is validated post-Pydantic-parse via
    :class:`backend.app.domain.study.search_space.SearchSpace` so
    :exc:`pydantic.ValidationError` produces the spec's 400
    ``INVALID_SEARCH_SPACE`` (per Story 3.3 task 2).
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


class StudySummary(BaseModel):
    """List-view shape."""

    id: str
    name: str
    cluster_id: str
    status: StudyStatusWire
    best_metric: float | None
    created_at: datetime
    completed_at: datetime | None


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


class TrialListResponse(BaseModel):
    """``GET /api/v1/studies/{id}/trials`` response."""

    data: list[TrialDetail]
    next_cursor: str | None
    has_more: bool


# --------------------------------------------------------------------------
# feat_llm_judgments — Epic 3 schemas (Stories 3.1 – 3.5)
# --------------------------------------------------------------------------

# Values must match backend/app/db/models/judgment_list.py CHECK constraint
# judgment_lists_status_check.
JudgmentListStatusWire = Literal["generating", "complete", "failed"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_source_check. `click` is reserved for v1.5+ click-derived
# judgments — emitted on read paths but never accepted on the source filter
# (see JudgmentSourceFilterWire below).
JudgmentSourceWire = Literal["llm", "human", "click"]

# Subset of JudgmentSourceWire used as the ?source= filter on
# GET /judgment-lists/{id}/judgments. Spec §8.4 enumerates only `llm` and
# `human` for this filter — `click` is rejected at the API boundary
# (GPT-5.5 cycle 1 F1).
JudgmentSourceFilterWire = Literal["llm", "human"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_rating_check.
RatingWire = Literal[0, 1, 2, 3]


class CreateJudgmentListGenerateRequest(BaseModel):
    """Body for ``POST /api/v1/judgments/generate`` (Story 3.1)."""

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    current_template_id: str = Field(min_length=1, max_length=36)
    rubric: str = Field(min_length=1)


class GenerateJudgmentsResponse(BaseModel):
    """Response of ``POST /api/v1/judgments/generate``.

    Per GPT-5.5 cycle 1 F5 — the endpoint registers a typed
    ``response_model`` so OpenAPI introspection + contract tests can verify
    the wire shape.
    """

    judgment_list_id: str
    status: Literal["generating"]


class _SourceBreakdown(BaseModel):
    """Source-breakdown sub-shape on :class:`JudgmentListDetail`.

    Per spec FR-6 the response names only ``llm`` and ``human`` (GPT-5.5
    cycle 1 F6). Reserved ``click`` rows fold into ``human`` per the cycle 2
    F6 invariant ``llm + human == judgment_count``.
    """

    llm: int
    human: int


class JudgmentListSummary(BaseModel):
    """List-view row on ``GET /api/v1/judgment-lists``."""

    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    status: JudgmentListStatusWire
    created_at: datetime


class JudgmentListDetail(BaseModel):
    """``GET /api/v1/judgment-lists/{id}`` response."""

    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    current_template_id: str | None
    rubric: str
    status: JudgmentListStatusWire
    failed_reason: str | None
    judgment_count: int
    source_breakdown: _SourceBreakdown
    calibration: dict[str, Any] | None
    created_at: datetime


class JudgmentListListResponse(BaseModel):
    """``GET /api/v1/judgment-lists`` response."""

    data: list[JudgmentListSummary]
    next_cursor: str | None
    has_more: bool


class JudgmentRow(BaseModel):
    """``GET /api/v1/judgment-lists/{id}/judgments`` row + PATCH response."""

    id: str
    judgment_list_id: str
    query_id: str
    doc_id: str
    rating: RatingWire
    source: JudgmentSourceWire
    rater_ref: str | None
    confidence: float | None
    notes: str | None
    created_at: datetime


class JudgmentListJudgmentsResponse(BaseModel):
    """``GET /api/v1/judgment-lists/{id}/judgments`` response."""

    data: list[JudgmentRow]
    next_cursor: str | None
    has_more: bool


class ImportJudgmentItem(BaseModel):
    """One row in :class:`ImportJudgmentListRequest`."""

    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire
    notes: str | None = Field(default=None, max_length=2000)


class ImportJudgmentListRequest(BaseModel):
    """Body for ``POST /api/v1/judgment-lists/import`` (Story 3.2)."""

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    rubric: str = Field(min_length=1)
    judgments: list[ImportJudgmentItem] = Field(min_length=1, max_length=100_000)


class OverrideJudgmentRequest(BaseModel):
    """Body for ``PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}``.

    ``rating`` is INTENTIONALLY unbounded at the Pydantic layer — spec §8.5
    requires out-of-range failures to surface as 400 ``INVALID_RATING`` (not
    Pydantic's default 422 ``VALIDATION_ERROR``). The handler validates the
    value manually and raises the domain code (per GPT-5.5 cycle 1 F4).
    """

    rating: int
    notes: str | None = Field(default=None, max_length=2000)


class CalibrationSample(BaseModel):
    """One row in :class:`CalibrationSamplesRequest`."""

    query_id: str = Field(min_length=1, max_length=36)
    doc_id: str = Field(min_length=1, max_length=512)
    rating: RatingWire


class CalibrationSamplesRequest(BaseModel):
    """Body for ``POST /api/v1/judgment-lists/{id}/calibration`` (Story 3.5)."""

    human_samples: list[CalibrationSample] = Field(min_length=1)


class CalibrationResponse(BaseModel):
    """Calibration endpoint response.

    Mirrors :class:`backend.app.eval.calibration.CalibrationResult` —
    persisted as ``judgment_lists.calibration`` JSONB.
    """

    cohens_kappa: float | None
    weighted_kappa: float | None
    per_class: dict[str, float]
    n_samples: int
    warning: str | None


# ---------------------------------------------------------------------------
# feat_digest_proposal Epic 3 schemas (Stories 3.1-3.4)
# ---------------------------------------------------------------------------

ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected"]
"""Wire values for ``proposals.status`` filter on ``GET /api/v1/proposals``.

Values must match backend/app/db/models/proposal.py CHECK
proposals_status_check (cycle-2 F4 / cycle-3 F1).
"""

ProposalSourceWire = Literal["study", "manual"]
"""Wire values for ``?source=`` filter on ``GET /api/v1/proposals``.

``study`` → ``study_id IS NOT NULL`` (proposal derived from a completed
study). ``manual`` → ``study_id IS NULL`` (operator-authored hand-crafted
proposal). Omit for both. Per chore_proposals_source_filter_server_side.

Values must match backend/app/db/repo/proposal.py ProposalSourceFilter +
ui/src/components/proposals/proposal-source-filter-chips.tsx (frontend
chip values exclude the meta `all` selection — that's a UI-only "no
filter" sentinel).
"""

ProposalPrStateWire = Literal["open", "closed", "merged"]
"""Wire values for ``proposals.pr_state``.

Values must match backend/app/db/models/proposal.py CHECK
proposals_pr_state_check.
"""


class DigestResponse(BaseModel):
    """Body of ``GET /api/v1/studies/{id}/digest`` (FR-3 / AC-3)."""

    id: str
    study_id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[str]
    generated_by: str
    generated_at: datetime


class CreateProposalRequest(BaseModel):
    """Body of ``POST /api/v1/proposals`` (manual proposal creation, FR-4 / AC-6)."""

    cluster_id: str = Field(min_length=1, max_length=36)
    template_id: str = Field(min_length=1, max_length=36)
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None = None


class RejectProposalRequest(BaseModel):
    """Body of ``POST /api/v1/proposals/{id}/reject`` (FR-4 / AC-5)."""

    reason: str | None = Field(default=None, max_length=500)


class _ClusterEmbed(BaseModel):
    """Inline cluster summary on proposal responses."""

    id: str
    name: str
    engine_type: str
    environment: str | None = None


class _TemplateEmbed(BaseModel):
    """Inline template summary on proposal responses."""

    id: str
    name: str
    version: int
    engine_type: str | None = None


class _StudySummary(BaseModel):
    """Inline study summary on the proposal-detail response."""

    id: str
    name: str
    status: str
    best_metric: float | None
    best_trial_id: str | None
    query_set: dict[str, Any]
    judgment_list: dict[str, Any]


class _DigestEmbed(BaseModel):
    """Inline digest summary on the proposal-detail response."""

    id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[str]
    generated_at: datetime


class ProposalSummary(BaseModel):
    """Row in the ``GET /api/v1/proposals`` list response."""

    id: str
    study_id: str | None
    cluster: _ClusterEmbed
    template: _TemplateEmbed
    status: ProposalStatusWire
    pr_state: ProposalPrStateWire | None
    pr_url: str | None
    metric_delta: dict[str, Any] | None
    created_at: datetime


class ProposalDetail(BaseModel):
    """Body of the proposal detail endpoints.

    Used by ``GET /api/v1/proposals/{id}``, ``POST /api/v1/proposals``,
    and ``POST /api/v1/proposals/{id}/reject``.
    """

    id: str
    study_id: str | None
    study_summary: _StudySummary | None
    study_trial_id: str | None
    cluster: _ClusterEmbed
    template: _TemplateEmbed
    config_diff: dict[str, Any]
    metric_delta: dict[str, Any] | None
    status: ProposalStatusWire
    pr_url: str | None
    pr_state: ProposalPrStateWire | None
    pr_merged_at: datetime | None
    pr_open_error: str | None
    rejected_reason: str | None
    digest: _DigestEmbed | None
    created_at: datetime


class ProposalsListResponse(BaseModel):
    """Body of ``GET /api/v1/proposals``."""

    data: list[ProposalSummary]
    next_cursor: str | None
    has_more: bool


# ---------------------------------------------------------------------------
# feat_github_pr_worker schemas (Story 1.2)
# ---------------------------------------------------------------------------


ConfigRepoProviderWire = Literal["github"]
"""Wire values for ``config_repos.provider``.

Values must match backend/app/db/models/config_repo.py CHECK
config_repos_provider_check (MVP1: 'github' only; MVP3 extends to
'gitlab' / 'bitbucket').
"""


class OpenPrResponse(BaseModel):
    """Body of ``POST /api/v1/proposals/{id}/open_pr`` (FR-1).

    Returned with HTTP 202 on successful enqueue. Status is always
    ``'pending'`` at enqueue time; the worker flips it to ``'pr_opened'``
    after the PR is open.
    """

    proposal_id: str
    status: Literal["pending"]
    message: str


class CreateConfigRepoRequest(BaseModel):
    """Body of ``POST /api/v1/config-repos`` (FR-3).

    ``provider`` is server-derived from ``repo_url`` (cycle-2 F4 from
    spec review) — NOT in the payload. The validator enforces a strict
    GitHub URL pattern; non-GitHub URLs surface as 400
    ``UNSUPPORTED_PROVIDER`` at the router layer.
    """

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    repo_url: str = Field(min_length=1, max_length=512)
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    pr_base_branch: str = Field(default="main", min_length=1, max_length=128)
    auth_ref: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    webhook_secret_ref: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


class ConfigRepoDetail(BaseModel):
    """``GET /api/v1/config-repos/{id}`` response + ``POST`` 201 body."""

    id: str
    name: str
    provider: ConfigRepoProviderWire
    repo_url: str
    default_branch: str
    pr_base_branch: str
    auth_ref: str
    webhook_secret_ref: str | None
    webhook_registration_error: str | None
    created_at: datetime


class ConfigReposListResponse(BaseModel):
    """``GET /api/v1/config-repos`` response."""

    data: list[ConfigRepoDetail]
    next_cursor: str | None
    has_more: bool


# ---------------------------------------------------------------------------
# feat_chat_agent (Stories 3.1 + 3.2)
# ---------------------------------------------------------------------------


# Wire-value Literals also exported through the source-of-truth gate to
# ui/src/lib/enums.ts (Story 4.4). Values must match
# backend/app/db/models/message.py messages_role_check (CHECK constraint).
MessageRoleWire = Literal["user", "assistant", "tool"]
MESSAGE_ROLE_VALUES: tuple[str, ...] = ("user", "assistant", "tool")

SSEEventTypeWire = Literal["token", "tool_call", "tool_result", "done"]
SSE_EVENT_TYPE_VALUES: tuple[str, ...] = ("token", "tool_call", "tool_result", "done")


class CreateConversationRequest(BaseModel):
    """``POST /api/v1/conversations`` body."""

    title: str | None = Field(default=None, max_length=200)


class MessageWire(BaseModel):
    """One row of ``GET /api/v1/conversations/{id}.messages``."""

    id: str
    role: MessageRoleWire
    content: dict[str, Any]
    tool_calls: list[dict[str, Any]] | None = None
    created_at: datetime


class ConversationSummary(BaseModel):
    """``GET /api/v1/conversations`` row + ``POST`` 201 body.

    ``last_message_preview`` is the most recent user / assistant message's
    ``content.text``, truncated at the repo layer to 120 chars (with ``…``
    suffix when cut). Tool-role rows and assistant rows whose ``content.kind``
    is ``system_notice`` are skipped. ``None`` for brand-new conversations
    with no qualifying messages — see ``chore_chat_last_message_preview``.

    ``last_message_at`` is the ``created_at`` of that same row, or ``None``
    for empty conversations. The list page uses it to render "when did
    anyone last touch this thread" instead of the conversation's
    ``created_at``.
    """

    id: str
    title: str | None
    created_at: datetime
    message_count: int
    last_message_preview: str | None = None
    last_message_at: datetime | None = None


class ConversationDetail(BaseModel):
    """``GET /api/v1/conversations/{id}`` response."""

    id: str
    title: str | None
    created_at: datetime
    messages: list[MessageWire]


class ConversationsListResponse(BaseModel):
    """``GET /api/v1/conversations`` response."""

    data: list[ConversationSummary]
    next_cursor: str | None
    has_more: bool


class SendMessageRequestContent(BaseModel):
    """Sub-shape inside :class:`SendMessageRequest`."""

    text: str = Field(min_length=1, max_length=20_000)


class SendMessageRequest(BaseModel):
    """``POST /api/v1/conversations/{id}/messages`` body (Story 3.2)."""

    role: Literal["user"] = "user"
    content: SendMessageRequestContent
