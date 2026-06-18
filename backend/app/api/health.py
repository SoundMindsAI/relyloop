# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Health check endpoint (infra_foundation Story 3.2 / FR-2 / spec §7.1).

``GET /healthz`` returns the documented JSON shape per spec §7.3:

.. code-block:: json

    {
      "status": "ok" | "degraded",
      "subsystems": {
        "db": "ok" | "down",
        "redis": "ok" | "down",
        "openai": "configured" | "missing_key" | "incapable",
        "elasticsearch": "reachable" | "unreachable",
        "opensearch": "reachable" | "unreachable"
      },
      "openai_endpoint": "<base_url>",
      "openai_capabilities": {"chat": ..., "function_calling": ..., "structured_output": ...},
      "version": "0.1.0",
      "uptime_seconds": <int>
    }

HTTP 200 when all required subsystems are healthy.
HTTP 503 when any of (db, redis, elasticsearch, opensearch) is down/unreachable.

OpenAI degraded states (``missing_key`` / ``incapable``) do **not** trigger 503 —
OpenAI is optional pre-judgments-feature per spec FR-2.

The endpoint is **unauthenticated** by design (operator probe, unprefixed —
not under /api/v1/) per CLAUDE.md Absolute Rule #6.

**Spec inconsistency note:** §7.4 enum table lists ``subsystems.openai`` values
as ``configured | missing_key`` (2 values), but FR-2 lists them as
``configured | missing_key | incapable`` (3 values). Plan §13 Review log
finding #1: implementing FR-2 (more specific) and recommending spec patch.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import probes
from backend.app.core.settings import Settings, get_settings
from backend.app.db.session import get_db, get_engine
from backend.app.llm.capability_models import CapabilityResult

router = APIRouter()

# Process-start timestamp for uptime_seconds calculation. Captured at module
# import (i.e. at API process start), reset only on process restart.
_PROCESS_STARTED_AT = time.monotonic()

# Per-subsystem probe timeout (spec FR-2: each probe runs in parallel with
# a 200ms timeout so the endpoint stays under 500ms p99 even if one probe hangs).
PROBE_TIMEOUT_SECONDS = 0.2


# ----------------------------------------------------------------------------
# Pydantic response models
# ----------------------------------------------------------------------------


class OpenAICapabilities(BaseModel):
    """Cached results of the OpenAI capability check (Story 3.3 populates Redis).

    Step 1 (``models_endpoint``) is reported first because it gates the rest:
    when it fails, the other three are reported as ``"untested"``. The
    ``models_endpoint_status_code`` field is required-but-nullable
    (per ``bug_openai_capability_check_incapable_on_valid_key`` spec §19 D-3/D-8)
    — always present in the JSON, ``null`` when not applicable. This lets
    operators distinguish ``401 -> bad key``, ``429 -> quota``,
    ``5xx -> upstream outage``, ``null -> network unreachable / cache miss``.
    """

    models_endpoint: Literal["ok", "fail", "untested"] = Field(
        description=(
            "GET /models probe outcome. 'ok' / 'fail' are projected from "
            "CapabilityResult.models_endpoint; 'untested' is the cache-miss "
            "default, matching the existing chat / function_calling / "
            "structured_output cache-miss handling."
        )
    )
    models_endpoint_status_code: int | None = Field(
        description=(
            "HTTP status code from the GET /models probe when it HTTP-failed "
            "(>= 400). null for the success path, network-class failure "
            "(timeout / DNS / connection-refused), or cache miss. Required-"
            "but-nullable: the JSON key is always present with explicit null "
            "when no value, never omitted."
        )
    )
    chat: Literal["ok", "fail", "untested"] = Field(description="Chat completion probe result")
    function_calling: Literal["ok", "fail", "untested"] = Field(
        description="Function-calling probe result (tool_choice=required)"
    )
    structured_output: Literal["ok", "fail", "untested"] = Field(
        description="JSON-schema response_format probe result"
    )


class Subsystems(BaseModel):
    """Per-subsystem reachability/configuration state. Wire values per spec §7.4."""

    db: Literal["ok", "down"] = Field(description="Postgres reachability")
    redis: Literal["ok", "down"] = Field(description="Redis reachability")
    openai: Literal["configured", "missing_key", "incapable"] = Field(
        description=(
            "OpenAI key + capability state. 'incapable' added per FR-2 vs. spec §7.4 "
            "enum table — see implementation_plan.md §13 Review log."
        )
    )
    elasticsearch: Literal["reachable", "unreachable", "not_selected"] = Field(
        description=(
            "Local Elasticsearch container reachability. 'not_selected' when "
            "'es' is excluded from the operator's RELYLOOP_ENGINES / "
            "COMPOSE_PROFILES selection — the probe is skipped and the state is "
            "NON-blocking (does not trigger overall 'degraded'). "
            "bug_healthz_degraded_blocks_ui_engine_subset."
        )
    )
    opensearch: Literal["reachable", "unreachable", "not_selected"] = Field(
        description=(
            "Local OpenSearch container reachability. 'not_selected' when 'os' "
            "is excluded from the operator's selection (NON-blocking; skipped). "
            "bug_healthz_degraded_blocks_ui_engine_subset."
        )
    )
    solr: Literal["reachable", "unreachable", "not_configured"] = Field(
        default="not_configured",
        description=(
            "Local Apache Solr container reachability. 'not_configured' when "
            "SOLR_HOST is unset (operator opted out of running the Solr "
            "service). Added by infra_adapter_solr Story A10 / spec FR-12a."
        ),
    )
    elasticsearch_clusters: probes.ClusterAggregateHealth = Field(
        description=(
            "Aggregate health of user-registered clusters (infra_adapter_elastic "
            "Story 3.5 / spec §2). registered=0 → all-zero counts; informational "
            "only — does NOT trigger overall `degraded`."
        )
    )


class HealthResponse(BaseModel):
    """The /healthz response body. Same shape for HTTP 200 and 503."""

    status: Literal["ok", "degraded"]
    subsystems: Subsystems
    openai_endpoint: str = Field(description="Configured OPENAI_BASE_URL")
    openai_capabilities: OpenAICapabilities
    version: str = Field(description="Application version (relyloop_git_sha)")
    uptime_seconds: int = Field(description="Seconds since the API process started")


# ----------------------------------------------------------------------------
# Status mapping (per spec FR-2 §7.3)
# ----------------------------------------------------------------------------


def overall_status(s: Subsystems) -> Literal["ok", "degraded"]:
    """Compute overall status from per-subsystem state.

    Per spec §7.3: only db/redis/elasticsearch/opensearch trigger degraded.
    OpenAI 'missing_key' and 'incapable' are NON-blocking.

    Engine-selection-aware (bug_healthz_degraded_blocks_ui_engine_subset): an
    engine that the operator excluded via RELYLOOP_ENGINES reports
    'not_selected' (ES/OS) or 'not_configured' (Solr), neither of which is
    'unreachable', so an intentionally-absent engine never trips 'degraded'.
    The check below is unchanged — it keys on 'unreachable', which only a
    SELECTED-but-down engine can be.
    """
    blocking_down = (
        s.db == "down"
        or s.redis == "down"
        # Only a SELECTED-but-down engine reports "unreachable"; an
        # intentionally-excluded engine reports "not_selected" (ES/OS) /
        # "not_configured" (Solr) and is non-blocking.
        or s.elasticsearch == "unreachable"
        or s.opensearch == "unreachable"
        or s.solr == "unreachable"
    )
    return "degraded" if blocking_down else "ok"


# ----------------------------------------------------------------------------
# Dependency injection helpers (overridden in tests)
# ----------------------------------------------------------------------------


async def get_redis_client() -> AsyncIterator[Redis]:
    """Yield a Redis async client; close after the request completes.

    Yield-style FastAPI dependency so the connection is closed when the
    handler returns (otherwise frequent /healthz polls accumulate
    connections — surfaced by GPT-5.5 final review of PR #4).
    """
    client: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


async def get_es_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx async client for ES probes; close after the request."""
    client = httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        yield client
    finally:
        await client.aclose()


def _safe_status(value: object, fallback: str) -> str:
    """Coerce probe results, treating exceptions as the safe fallback."""
    if isinstance(value, BaseException):
        return fallback
    return str(value)


async def _read_capability_cache(redis_client: Redis, base_url: str) -> CapabilityResult | None:
    """Best-effort read of the cached capability check from Redis.

    Returns None on cache miss or Redis error. Story 3.3 wires the cache writer.
    """
    import hashlib

    cache_key = f"openai:capabilities:{hashlib.sha256(base_url.encode()).hexdigest()}"
    try:
        raw = await redis_client.get(cache_key)
    except Exception:  # noqa: BLE001 — cache miss is non-fatal
        return None
    if raw is None:
        return None
    try:
        return CapabilityResult.model_validate_json(raw)
    except Exception:  # noqa: BLE001 — corrupted cache entry treated as miss
        return None


# ----------------------------------------------------------------------------
# /healthz handler
# ----------------------------------------------------------------------------


@router.get(
    "/healthz",
    response_model=HealthResponse,
    responses={
        503: {"model": HealthResponse, "description": "One or more required subsystems is down"}
    },
    tags=["operator"],
)
async def healthz(
    settings: Annotated[Settings, Depends(get_settings)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
    es_client: Annotated[httpx.AsyncClient, Depends(get_es_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Probe each subsystem in parallel and return the documented JSON shape.

    Args:
        settings: Application settings (DB URL, ES/OS URLs, OpenAI base URL, etc.)
        redis_client: Redis client for ping probe + capability-cache read
        es_client: shared httpx client for ES + OpenSearch HTTP probes
        db: Async DB session for the registered-clusters aggregate (Story 3.5)

    Returns:
        JSONResponse with the HealthResponse body and HTTP 200 (healthy) or 503 (degraded).
    """
    engine = get_engine()
    es_base_url = "http://elasticsearch:9200"
    os_base_url = "http://opensearch:9200"
    # Solr is optional — opt-in via SOLR_HOST. When unset the probe is
    # skipped entirely and subsystems.solr reports "not_configured".
    solr_base_url = (
        f"http://{settings.solr_host}:{settings.solr_port}" if settings.solr_host else None
    )

    # bug_healthz_degraded_blocks_ui_engine_subset — engine-selection-aware
    # probing. When the operator excluded an engine via RELYLOOP_ENGINES
    # (→ COMPOSE_PROFILES → settings.selected_engines), skip its probe entirely
    # and report "not_selected" (a non-blocking state, mirroring Solr's
    # "not_configured"). Without this an intentionally-absent ES/OS reports
    # "unreachable" → degraded → 503 → the api healthcheck fails → ui/worker
    # never start.
    selected = settings.selected_engines
    es_selected = "es" in selected
    os_selected = "os" in selected

    # Run all async probes concurrently with per-probe 200ms timeouts.
    # asyncio.wait_for raises TimeoutError on timeout; gather(return_exceptions=True)
    # collects the exception so a single hung probe doesn't fail the others.
    # Result indices are fixed (db=0, redis=1, es=2, os=3, clusters=4, solr=5)
    # so the not-selected substitution must keep the es/os slots in place.
    # `asyncio.sleep(0, result="not_selected")` is an immediately-resolving
    # coroutine — no nested-function-per-request overhead (Gemini review).
    probe_coros = [
        asyncio.wait_for(probes.probe_db(engine), timeout=PROBE_TIMEOUT_SECONDS),
        asyncio.wait_for(probes.probe_redis(redis_client), timeout=PROBE_TIMEOUT_SECONDS),
        (
            asyncio.wait_for(
                probes.probe_elasticsearch(es_client, es_base_url),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
            if es_selected
            else asyncio.sleep(0, result="not_selected")
        ),
        (
            asyncio.wait_for(
                probes.probe_opensearch(es_client, os_base_url),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
            if os_selected
            else asyncio.sleep(0, result="not_selected")
        ),
        asyncio.wait_for(
            probes.probe_registered_clusters(db, redis_client),
            timeout=PROBE_TIMEOUT_SECONDS,
        ),
    ]
    if solr_base_url is not None:
        probe_coros.append(
            asyncio.wait_for(
                probes.probe_solr(es_client, solr_base_url),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        )
    results = await asyncio.gather(*probe_coros, return_exceptions=True)
    db_status = _safe_status(results[0], fallback="down")
    redis_status = _safe_status(results[1], fallback="down")
    es_status = _safe_status(results[2], fallback="unreachable")
    os_status = _safe_status(results[3], fallback="unreachable")
    clusters_aggregate: probes.ClusterAggregateHealth
    raw_clusters = results[4]
    if isinstance(raw_clusters, BaseException) or not isinstance(
        raw_clusters, probes.ClusterAggregateHealth
    ):
        # Probe timeout / DB/Redis hiccup: surface zeros (informational field).
        clusters_aggregate = probes.ClusterAggregateHealth(registered=0, healthy=0, unreachable=0)
    else:
        clusters_aggregate = raw_clusters
    if solr_base_url is None:
        solr_status: str = "not_configured"
    else:
        solr_status = _safe_status(results[5], fallback="unreachable")

    # OpenAI state is computed from cached capability data + key presence.
    cap = await _read_capability_cache(redis_client, settings.openai_base_url)
    openai_state = probes.probe_openai_state(settings.openai_api_key, cap)

    subsystems = Subsystems.model_validate(
        {
            "db": db_status,
            "redis": redis_status,
            "openai": openai_state,
            "elasticsearch": es_status,
            "opensearch": os_status,
            "solr": solr_status,
            "elasticsearch_clusters": clusters_aggregate.model_dump(),
        }
    )

    capabilities = (
        OpenAICapabilities(
            models_endpoint=cap.models_endpoint,
            models_endpoint_status_code=cap.models_endpoint_status_code,
            chat=cap.chat_completion,
            function_calling=cap.function_calling,
            structured_output=cap.structured_output,
        )
        if cap is not None
        else OpenAICapabilities(
            models_endpoint="untested",
            models_endpoint_status_code=None,
            chat="untested",
            function_calling="untested",
            structured_output="untested",
        )
    )

    body = HealthResponse(
        status=overall_status(subsystems),
        subsystems=subsystems,
        openai_endpoint=settings.openai_base_url,
        openai_capabilities=capabilities,
        version=settings.relyloop_git_sha,
        uptime_seconds=int(time.monotonic() - _PROCESS_STARTED_AT),
    )

    http_status = status.HTTP_200_OK if body.status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=body.model_dump())
