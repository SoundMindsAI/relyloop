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

from pydantic import BaseModel, Field, field_validator

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
