# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cluster registry, health, connection-test, run-query, and document-browse models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from backend.app.adapters.protocol import TargetInfo
from backend.app.api.v1._wire_types import (
    AuthKind,
    EngineType,
    Environment,
    HealthStatusValue,
)


def _validate_base_url_structure(v: str) -> str:
    """Shared structural validation for ``base_url`` (scheme + host present).

    Single source of truth for ``CreateClusterRequest`` and
    ``ConnectionTestRequest`` (they were byte-for-byte duplicates — the drift
    source fixed by bug_cluster_url_ssrf_hostname_bypass FR-4). Pure structure
    only: scheme ∈ {http, https} and a host is present, both raising
    ``ValueError`` → 422 ``VALIDATION_ERROR``. The SSRF *policy* (private /
    loopback / link-local / metadata rejection, incl. DNS resolution) lives in
    the async service helper ``backend/app/services/cluster_url_policy.py``
    (it requires DNS I/O, which a synchronous Pydantic validator must not do).
    """
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https scheme")
    if not parsed.hostname:
        raise ValueError("base_url must include a host")
    # Accessing .port raises ValueError on a malformed port (e.g.
    # "host:9200abc") — catch it here so it surfaces as 422 VALIDATION_ERROR
    # rather than propagating to the service layer (Gemini review #2).
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base_url has an invalid port") from exc
    return v


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
        """Structural validation only — SSRF policy is in the service layer."""
        return _validate_base_url_structure(v)


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
        """Structural validation only — SSRF policy is in the service layer."""
        return _validate_base_url_structure(v)


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
