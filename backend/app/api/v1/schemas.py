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

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.core.settings import get_settings

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
    created_at: datetime
    health_check: HealthCheckResult


class ClusterListResponse(BaseModel):
    """Paginated list response."""

    data: list[ClusterSummary]
    next_cursor: str | None
    has_more: bool


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
ObjectiveMetric = Literal["ndcg", "map", "precision", "recall", "mrr", "err"]

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
    "created_at_desc",
    "created_at_asc",
    "optuna_trial_number_asc",
]

# Values must match backend/app/db/models/trial.py CHECK constraint.
TrialStatusWire = Literal["complete", "failed", "pruned"]


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


# --- Study ---------------------------------------------------------------


class ObjectiveSpec(BaseModel):
    """Wire shape of ``studies.objective`` (write-side validated at create)."""

    metric: ObjectiveMetric
    k: ObjectiveK | None = None  # required for ndcg/precision/recall; ignored for mrr/err
    direction: ObjectiveDirection = "maximize"


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
