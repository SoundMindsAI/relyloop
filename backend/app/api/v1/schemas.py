# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
from backend.app.domain.study.chain_summary import ChainStopReason as ChainStopReason
from backend.app.domain.study.confidence import ConfidenceShape as ConfidenceShape
from backend.app.domain.study.convergence import (
    ConvergenceVerdict as ConvergenceVerdict,
)
from backend.app.domain.study.convergence import (
    StudyConvergenceShape as StudyConvergenceShape,
)
from backend.app.domain.study.followups import FollowupItem as FollowupItem

# ``ConfidenceShape`` is defined in :mod:`backend.app.domain.study.confidence`
# (the canonical assembler module per Story 1.3). The explicit ``as`` re-export
# above keeps it importable via ``from backend.app.api.v1.schemas import
# ConfidenceShape`` under mypy strict's ``no_implicit_reexport``.

EngineType = Literal["elasticsearch", "opensearch", "solr"]
"""Response-only: values are guaranteed by service-layer validation before the
DB write, so the response model is safe to lock down with ``Literal``.
``solr`` added by ``infra_adapter_solr`` (Story A6/A11)."""

Environment = Literal["prod", "staging", "dev"]
"""Both request- and response-side: spec §8.5 has no ENVIRONMENT_NOT_SUPPORTED
domain code, so invalid values surface as 422 VALIDATION_ERROR via Pydantic."""

AuthKind = Literal[
    "es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4", "solr_basic", "solr_apikey"
]
"""Response-only — see EngineType note. ``solr_basic`` / ``solr_apikey`` added
by ``infra_adapter_solr``."""

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


class ConnectionTestRequest(BaseModel):
    """Body for ``POST /api/v1/clusters/test-connection`` (infra_adapter_solr Story A9).

    Same shape as ``CreateClusterRequest`` minus the persisted-only fields
    (``name``, ``environment``, ``notes``, ``target_filter``). ``engine_type``
    + ``auth_kind`` are typed as ``str`` (not Literal) so a bad value yields
    the project-standard 400 envelope rather than a raw 422 — same convention
    as ``CreateClusterRequest``.
    """

    engine_type: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=512)
    auth_kind: str = Field(min_length=1, max_length=64)
    credentials_ref: str = Field(min_length=1, max_length=128)
    engine_config: dict[str, Any] | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Same base_url validation as CreateClusterRequest — see that class for rationale."""
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("base_url must include a host")
        try:
            ip = ip_address(parsed.hostname)
        except ValueError:
            return v
        if (ip.is_private or ip.is_loopback) and not get_settings().relyloop_allow_private_clusters:
            raise ValueError(
                f"base_url host {parsed.hostname} is a private-range IP "
                f"and RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
            )
        return v


class ConnectionTestResult(BaseModel):
    """Response for ``POST /api/v1/clusters/test-connection``.

    Always 200 — reachable vs unreachable surfaces via ``reachable`` +
    ``status`` fields. The endpoint is a diagnostic, never a mutation,
    so it never returns 503; invalid engine×auth pairings 400 BEFORE the
    network call. (Cycle-delta F1.)
    """

    reachable: bool
    """True when the cluster responded green/yellow within timeout."""

    status: Literal["green", "yellow", "red", "unreachable"]
    """Mirrors HealthStatus.status — green/yellow when reachable, unreachable otherwise."""

    version: str | None = None
    """Engine version when reachable; None when unreachable."""

    engine_capabilities: dict[str, Any] | None = None
    """For Solr clusters: probe summary (mode + ubi_component_present +
    ltr_module_present + ltr_models + unique_key_per_target). None for ES/OS
    or for unreachable clusters."""

    error: str | None = None
    """Human-readable diagnostic when not reachable."""


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
# feat_index_document_browser — documents-browse list endpoint.
# Per spec §7.1 / FR-3. Detail endpoint reuses the adapter ``Document`` model
# directly (F3 resolution — single source of truth, no router-side schema
# drift).
# ---------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    """One row in the documents list (per FR-3 / FR-8).

    ``source`` is the *truncated* preview emitted by
    ``backend.app.services.documents.truncate_source_for_list``. The detail
    endpoint returns the untruncated ``Document.source``.
    """

    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None


class DocumentListResponse(BaseModel):
    """``GET /api/v1/clusters/{cluster_id}/targets/{target}/documents`` response.

    ``next_cursor`` opaque-encodes the ES ``hits[-1].sort`` array of the
    last visible row when ``has_more`` is True (see
    ``backend.app.api.v1._documents_cursor``). The ``X-Total-Count`` header
    on the response carries the engine's ``hits.total.value``.
    """

    data: list[DocumentSummary]
    next_cursor: str | None
    has_more: bool


# ---------------------------------------------------------------------------
# feat_study_lifecycle Phase 2 — query-template / query-set / study / trial
# schemas. Per CLAUDE.md "Enumerated Value Contract Discipline" every wire
# Literal carries a source-of-truth comment.
# ---------------------------------------------------------------------------


# Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES.
EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]

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


# --------------------------------------------------------------------------
# feat_llm_judgments — Epic 3 schemas (Stories 3.1 – 3.5)
# --------------------------------------------------------------------------

# Values must match backend/app/db/models/judgment_list.py CHECK constraint
# judgment_lists_status_check.
JudgmentListStatusWire = Literal["generating", "complete", "failed"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_source_check. `click` is live in MVP2 (feat_ubi_judgments FR-10) —
# UBI worker writes `source='click'` rows + the source filter accepts the value
# (see JudgmentSourceFilterWire below).
JudgmentSourceWire = Literal["llm", "human", "click"]

# Used as the ?source= filter on GET /judgment-lists/{id}/judgments.
# Widened in feat_ubi_judgments FR-10 to accept `click` so the UI's
# Source filter on judgment-list detail can surface UBI rows. Cycle 2 F6's
# rejection-at-API-boundary contract was superseded the moment UBI shipped
# click rows.
JudgmentSourceFilterWire = Literal["llm", "human", "click"]

# Values must match backend/app/db/models/judgment.py CHECK constraint
# judgments_rating_check.
RatingWire = Literal[0, 1, 2, 3]

# ---------------------------------------------------------------------------
# UBI wire-value contracts (feat_ubi_judgments FR-9)
# ---------------------------------------------------------------------------
# UBI converter kind — body of POST /api/v1/judgments/generate-from-ubi.
# Source-of-truth: this Literal + the UbiJudgmentGenerationRequest dataclass
# in backend/app/services/agent_judgments_dispatch.py.
UbiConverterKind = Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]

# Superset surfaced by the frontend method picker (Story 4.2). The `llm`
# branch routes to POST /judgments/generate (existing); the three UBI
# branches route to POST /judgments/generate-from-ubi (Story 3.2). The
# UBI endpoint itself never accepts `llm` for `converter` — that mapping
# happens client-side.
JudgmentGenerationMethodWire = Literal["llm", "ctr_threshold", "dwell_time", "hybrid_ubi_llm"]

# UBI readiness rung label returned by GET /api/v1/clusters/{id}/ubi-readiness.
# Source-of-truth: the UbiReadinessRung Literal in
# backend/app/services/ubi_readiness.py.
UbiReadinessRungWire = Literal["rung_0", "rung_1", "rung_2", "rung_3"]

# UBI mapping strategy (FR-5 step 5 — how the worker joins UBI user_query
# strings to query_set.queries.query_text when they're ambiguous).
# `reject` is the default; under it ambiguous pairs are skipped per-query
# (NOT terminal — cycle-3 finding `ambiguous-mapping-behavior-contradictory`).
UbiMappingStrategyWire = Literal["reject", "first_match", "most_recent"]


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

    Evolved 2026-05-29 by ``feat_ubi_judgments`` FR-10 — now three terms
    (``llm + human + click == judgment_count``). The cycle-2 F6
    "click folds into human" contract is superseded the moment UBI ships
    click rows; the UI's source-breakdown card now renders all three
    buckets separately so operators see the mix at a glance.
    """

    llm: int
    human: int
    click: int


class JudgmentListSummary(BaseModel):
    """List-view row on ``GET /api/v1/judgment-lists``."""

    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    status: JudgmentListStatusWire
    created_at: datetime


class JudgmentListDetail(BaseModel):
    """``GET /api/v1/judgment-lists/{id}`` response.

    Note: ``generation_params`` is populated for UBI lists (feat_ubi_judgments
    Story 1.1's JSONB column) and NULL for LLM lists. The Story 4.3 UI
    (``<ValueDeltaCard>`` + ``<AmbiguousSkipRecoveryCard>``) reads the
    payload to discriminate UBI/hybrid lists and to reconstruct the
    original request for the ambiguous-skip "Re-run with most_recent"
    affordance.
    """

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
    generation_params: dict[str, Any] | None
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

ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected", "superseded"]
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
    """Body of ``GET /api/v1/studies/{id}/digest`` (FR-3 / AC-3).

    feat_digest_executable_followups Story 4.1 — ``suggested_followups`` is
    now a discriminated-union list (NarrowFollowup | WidenFollowup |
    TextFollowup), populated by the digest handler via
    ``parse_followup_list(digest.suggested_followups, ...)`` so legacy or
    malformed JSONB payloads never crash the response.
    """

    id: str
    study_id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]
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
    """Inline digest summary on the proposal-detail response.

    feat_digest_executable_followups Story 4.1 — ``suggested_followups`` is
    now a discriminated-union list (see ``DigestResponse``).
    """

    id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]
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
    is_currently_live: bool = False
    """True when this proposal is some ``config_repos.last_merged_proposal_id``
    (feat_config_repo_baseline_tracking FR-5). Pointer-only derivation —
    symmetric with ``?is_last_merged=true``. Defaults to False so list
    responses that don't populate the field (e.g., legacy callers) deserialize
    cleanly."""
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
    is_currently_live: bool = False
    """True when this proposal is some ``config_repos.last_merged_proposal_id``
    (feat_config_repo_baseline_tracking FR-5). See :class:`ProposalSummary`."""
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
    last_merged_proposal: ProposalSummary | None = None
    """The proposal currently tracked as the live config for this repo
    (feat_config_repo_baseline_tracking FR-4). NULL when no merge has occurred
    yet. Always present in detail responses (populated when the pointer is
    set). On list responses every row defaults to ``None`` — the list path
    does NOT JOIN the proposal embed to keep paginated list responses
    lightweight."""
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


# ---------------------------------------------------------------------------
# UBI readiness + generate-from-ubi request shapes (feat_ubi_judgments
# Stories 3.1 + 3.2)
# ---------------------------------------------------------------------------


class UbiReadinessResponse(BaseModel):
    """``GET /api/v1/clusters/{cluster_id}/ubi-readiness`` response (FR-7).

    ``covered_pairs_pct`` and ``head_covered`` are nullable — MVP2's
    rung classifier uses event-count thresholds (the SearchAdapter
    Protocol doesn't expose an exact ``_count`` endpoint). The fields
    are reserved on the wire so a future ``infra_adapter_count_method``
    can fill them without breaking the contract. See
    :mod:`backend.app.services.ubi_readiness` for the rationale.
    """

    rung: UbiReadinessRungWire
    covered_pairs_pct: float | None
    head_covered: bool | None
    checked_at: datetime


class CreateJudgmentListFromUbiRequest(BaseModel):
    """Body for ``POST /api/v1/judgments/generate-from-ubi`` (Story 3.2 / FR-3).

    Mirrors :class:`backend.app.services.agent_judgments_dispatch.UbiJudgmentGenerationRequest`.
    The ``@model_validator(mode="after")`` enforces the conditional
    requiredness of ``current_template_id`` + ``rubric`` per the hybrid
    converter: REQUIRED when ``converter == 'hybrid_ubi_llm'`` (the LLM-
    fill path needs both); FORBIDDEN otherwise (pure UBI never calls
    the LLM so accepting them silently would mask operator error).
    """

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    since: datetime
    until: datetime | None = None
    converter: UbiConverterKind
    converter_config: dict[str, Any] | None = None
    llm_fill_threshold: int | None = Field(default=20, ge=1)
    min_impressions_threshold: int | None = Field(default=100, ge=1)
    mapping_strategy: UbiMappingStrategyWire = "reject"
    current_template_id: str | None = Field(default=None, min_length=36, max_length=36)
    rubric: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_hybrid_conditional(self) -> CreateJudgmentListFromUbiRequest:
        is_hybrid = self.converter == "hybrid_ubi_llm"
        has_template = self.current_template_id is not None
        has_rubric = self.rubric is not None
        if is_hybrid and not (has_template and has_rubric):
            raise ValueError(
                "current_template_id and rubric are REQUIRED when converter == 'hybrid_ubi_llm'"
            )
        if not is_hybrid and (has_template or has_rubric):
            raise ValueError(
                "current_template_id and rubric MUST be null for non-hybrid converters"
            )
        return self


# ---------------------------------------------------------------------------
# Study comparison (feat_ubi_llm_study_comparison) — read-only.
# CompareKind / CompareWarningCode are the canonical Literals; the
# study_comparison service imports them so there is one source of truth.
# ---------------------------------------------------------------------------

CompareKind = Literal["llm", "ubi"]
CompareWarningCode = Literal["CROSS_CLUSTER", "TARGET_MISMATCH", "OBJECTIVE_MISMATCH"]


class CompareWarning(BaseModel):
    """A non-fatal mismatch between the two compared studies."""

    code: CompareWarningCode
    message: str


class StudyComparePairing(BaseModel):
    """Validated LLM↔UBI study pair returned by ``GET /studies/compare``."""

    a_study_id: str
    b_study_id: str
    a_kind: CompareKind
    b_kind: CompareKind
    query_set_id: str
    warnings: list[CompareWarning]


class StudyPairResponse(BaseModel):
    """``GET /studies/{id}/pair`` — the counterpart, or nulls when none."""

    study_id: str | None
    kind: CompareKind | None


class JudgmentListStudyResponse(BaseModel):
    """``GET /judgment-lists/{id}/study`` — the single completed study, or null."""

    study_id: str | None
