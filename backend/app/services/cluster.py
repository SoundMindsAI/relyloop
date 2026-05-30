# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cluster service — registration, lookup, dispatch (Story 3.1).

Composes the repo + adapter + Redis cache into business operations:

* ``register_cluster`` — validates enums, builds an adapter, probes
  ``health_check``, and either inserts a new row or revives a previously
  soft-deleted same-named row (per spec §10 Data retention).
* ``get_or_probe_health`` — read-through cache on top of ``read_cached_health``;
  on miss probes the cluster and writes the result with the canonical 30s TTL.
* ``build_adapter`` — public factory used by routers (Stories 3.3/3.4) AND
  by ``backend/workers/trials.py`` (the Optuna trial runner from
  ``infra_optuna_eval``). Renamed from the private ``_build_adapter`` in
  ``infra_optuna_eval`` Story 2.3 so the worker doesn't have to import
  across module boundaries via a leading-underscore symbol.
* ``dispatch_run_query`` — wraps the adapter's ``search_batch`` with
  ``asyncio.wait_for`` as an outer wall-clock guard for the run_query API.

Per cycle 1 F8: ``CredentialsMissing`` raised by adapter construction is
caught here and translated to ``ClusterUnreachable`` so the router emits
``CLUSTER_UNREACHABLE`` rather than a generic 500.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import uuid_utils
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.credentials import CredentialsMissing
from backend.app.adapters.elastic import (
    ALLOWED_AUTH_PER_ENGINE,
    RESERVED_AUTH_KINDS,
    SUPPORTED_AUTH_KINDS,
    SUPPORTED_ENGINE_TYPES,
    ElasticAdapter,
)
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.health_cache import read_cached_health, write_cached_health
from backend.app.adapters.protocol import HealthStatus, NativeQuery, ScoredHit
from backend.app.db import repo
from backend.app.db.models import Cluster

# ---------------------------------------------------------------------------
# Service exceptions — translated by routers to spec §7.5 error codes.
# ---------------------------------------------------------------------------


class ClusterUnreachable(Exception):
    """Surfaces 503 ``CLUSTER_UNREACHABLE`` at the router."""


class ClusterNameTaken(Exception):
    """Surfaces 409 ``CLUSTER_NAME_TAKEN`` at the router."""


class EngineTypeNotSupported(Exception):
    """Surfaces 400 ``ENGINE_NOT_SUPPORTED`` at the router."""


class AuthKindNotSupported(Exception):
    """Surfaces 400 ``AUTH_KIND_NOT_SUPPORTED`` at the router.

    Used both for unknown values AND reserved-but-unimplemented values
    (e.g. ``opensearch_sigv4``).
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def register_cluster(
    db: AsyncSession,
    redis: Redis,
    *,
    name: str,
    engine_type: str,
    environment: str,
    base_url: str,
    auth_kind: str,
    credentials_ref: str,
    engine_config: dict[str, Any] | None,
    notes: str | None,
    target_filter: str | None = None,
) -> tuple[Cluster, HealthStatus]:
    """Probe → insert (or revive) → cache. Reject if the cluster is unreachable.

    Resurrection path (per spec §10 Data retention): if a row with the same
    name exists but is soft-deleted, it is revived (``deleted_at = NULL``)
    with the new field values rather than INSERTed (which would otherwise
    violate the unique constraint).
    """
    if engine_type not in SUPPORTED_ENGINE_TYPES:
        raise EngineTypeNotSupported(
            f"engine_type must be one of: {sorted(SUPPORTED_ENGINE_TYPES)} (got: {engine_type!r})"
        )
    if auth_kind in RESERVED_AUTH_KINDS:
        raise AuthKindNotSupported(f"{auth_kind!r} is reserved but not implemented in MVP1")
    if auth_kind not in SUPPORTED_AUTH_KINDS:
        raise AuthKindNotSupported(
            f"auth_kind must be one of: "
            f"{sorted(SUPPORTED_AUTH_KINDS | RESERVED_AUTH_KINDS)} "
            f"(got: {auth_kind!r})"
        )
    # Cross-product allowlist — engine_type × auth_kind. Independently-valid
    # values can still form a nonsense pairing (e.g. opensearch + es_apikey).
    # Reject those at the request boundary rather than discovering them later
    # when the operator tries to debug why their cluster keeps probing
    # unreachable.
    allowed_for_engine = ALLOWED_AUTH_PER_ENGINE.get(engine_type, frozenset())
    if auth_kind not in allowed_for_engine:
        raise AuthKindNotSupported(
            f"auth_kind={auth_kind!r} is not valid for engine_type={engine_type!r}; "
            f"allowed for {engine_type!r}: {sorted(allowed_for_engine)}"
        )

    existing = await repo.get_any_cluster_by_name(db, name)
    if existing is not None and existing.deleted_at is None:
        raise ClusterNameTaken(name)

    cluster_id_for_probe = existing.id if existing is not None else str(uuid_utils.uuid7())

    try:
        adapter = ElasticAdapter(
            cluster_id=cluster_id_for_probe,
            engine_type=engine_type,  # type: ignore[arg-type]
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=engine_config,
        )
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc

    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()

    if health.status == "unreachable":
        raise ClusterUnreachable(health.error or "cluster did not respond within timeout")

    # Auto-fill engine_config.api_version from health.version (Decision Log
    # 2026-05-09: api_version is the major-version slot of the engine).
    cfg = dict(engine_config or {})
    if "api_version" not in cfg and health.version:
        cfg["api_version"] = health.version.split(".")[0]

    if existing is not None:
        cluster = await repo.revive_cluster(
            db,
            existing,
            engine_type=engine_type,
            environment=environment,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=cfg or None,
            notes=notes,
            target_filter=target_filter,
        )
    else:
        cluster = await repo.create_cluster(
            db,
            id=cluster_id_for_probe,
            name=name,
            engine_type=engine_type,
            environment=environment,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=cfg or None,
            notes=notes,
            target_filter=target_filter,
        )
    await db.commit()
    await write_cached_health(redis, cluster.id, health)
    return cluster, health


async def get_or_probe_health(redis: Redis, cluster: Cluster) -> HealthStatus:
    """Return cached HealthStatus, or probe + cache (30s TTL).

    Catches ``CredentialsMissing`` from adapter construction so a missing
    YAML entry surfaces as an ``unreachable`` health rather than escaping
    to the router as a 500.
    """
    cached = await read_cached_health(redis, cluster.id)
    if cached is not None:
        return cached
    try:
        adapter = build_adapter(cluster)
    except CredentialsMissing as exc:
        # Cache the synthetic unreachable result so probe_registered_clusters
        # (cache-only aggregate per CLAUDE.md Absolute Rule #11) sees a
        # cached "fail" instead of cache-miss for credentials-missing
        # clusters. Per bug_demo_clusters_unreachable_in_healthz spec FR-7.
        health = HealthStatus(
            status="unreachable",
            checked_at=datetime.now(UTC).isoformat(),
            error=f"credentials resolution failed: {exc}",
        )
        await write_cached_health(redis, cluster.id, health)
        return health
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    await write_cached_health(redis, cluster.id, health)
    return health


async def soft_delete_cluster(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Soft-delete a cluster row and commit. Returns the row, or None if absent."""
    cluster = await repo.soft_delete_cluster(db, cluster_id)
    if cluster is not None:
        await db.commit()
    return cluster


@asynccontextmanager
async def acquire_adapter(cluster: Cluster) -> AsyncIterator[ElasticAdapter]:
    """Build an adapter from a stored cluster row, ensure ``aclose()`` on exit.

    Translates ``CredentialsMissing`` (raised by adapter construction when the
    operator removes a YAML entry between registration and now) into the
    service-layer ``ClusterUnreachable`` so router callers can adjudicate it
    under the same 503 ``CLUSTER_UNREACHABLE`` translation they already use
    for adapter-internal failures (per cycle 1 F8 + final-review F3).

    Usage in a router::

        try:
            async with acquire_adapter(cluster) as adapter:
                return await adapter.get_schema(target)
        except (ClusterUnreachable, ClusterUnreachableError) as exc:
            raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
        except TargetNotFoundError as exc:
            raise _err(404, "TARGET_NOT_FOUND", ...) from exc
    """
    try:
        adapter = build_adapter(cluster)
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc
    try:
        yield adapter
    finally:
        await adapter.aclose()


async def dispatch_run_query(
    adapter: ElasticAdapter,
    *,
    target: str,
    query_dsl: dict[str, Any],
    top_k: int,
    timeout_s: float,
) -> list[ScoredHit]:
    """Execute one query DSL fragment as a 1-element search_batch.

    ``timeout_s`` is threaded into the adapter via ``timeout=`` so the
    operator's 5–30s budget actually fires (the adapter's default 10s
    httpx client timeout would otherwise pre-empt). ``asyncio.wait_for``
    is the outer wall-clock guard in case httpx itself doesn't honor the
    deadline; +1.0s slack lets cleanup run.
    """
    query = NativeQuery(
        query_id="run_query",
        body={"query": query_dsl, "size": top_k},
    )
    try:
        result = await asyncio.wait_for(
            adapter.search_batch(
                target=target,
                queries=[query],
                top_k=top_k,
                strict_errors=True,
                timeout=timeout_s,
            ),
            timeout=timeout_s + 1.0,
        )
    except TimeoutError as exc:
        raise QueryTimeoutError(f"query exceeded {timeout_s}s budget") from exc
    return result.get("run_query", [])


# Re-export the InvalidQueryDSLError + QueryTimeoutError + ClusterUnreachableError
# domain types for the router's exception-translation table convenience.
__all__ = [
    "AuthKindNotSupported",
    "ClusterNameTaken",
    "ClusterUnreachable",
    "ClusterUnreachableError",
    "EngineTypeNotSupported",
    "InvalidQueryDSLError",
    "QueryTimeoutError",
    "dispatch_run_query",
    "get_or_probe_health",
    "register_cluster",
    "soft_delete_cluster",
    "build_adapter",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def build_adapter(cluster: Cluster) -> ElasticAdapter:
    """Construct a fresh ``ElasticAdapter`` from a stored cluster row."""
    return ElasticAdapter(
        cluster_id=cluster.id,
        engine_type=cluster.engine_type,  # type: ignore[arg-type]
        base_url=cluster.base_url,
        auth_kind=cluster.auth_kind,
        credentials_ref=cluster.credentials_ref,
        engine_config=cluster.engine_config,
    )
