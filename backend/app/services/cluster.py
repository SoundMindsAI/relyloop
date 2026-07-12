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
from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.health_cache import read_cached_health, write_cached_health
from backend.app.adapters.protocol import HealthStatus, NativeQuery, ScoredHit
from backend.app.adapters.registry import (
    ALLOWED_AUTH_PER_ENGINE,
    RESERVED_AUTH_KINDS,
    SUPPORTED_AUTH_KINDS,
    SUPPORTED_ENGINE_TYPES,
)
from backend.app.adapters.solr import SolrAdapter
from backend.app.db import repo
from backend.app.db.models import Cluster
from backend.app.services.cluster_url_policy import (
    ClusterUrlBlocked as ClusterUrlBlocked,  # re-export (defined there to avoid a cycle)
)
from backend.app.services.cluster_url_policy import (
    assert_base_url_allowed,
)

# Adapter union type — the concrete adapters this MVP supports. Public APIs
# (build_adapter, acquire_adapter, dispatch_run_query) annotate against this
# union so the caller can rely on the Protocol surface without a runtime
# isinstance check. Callers that need a Protocol-only constraint can import
# ``SearchAdapter`` from ``backend.app.adapters.protocol`` directly — the
# union is structurally a subset.
ClusterAdapter = ElasticAdapter | SolrAdapter

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

    # SSRF guard (bug_cluster_url_ssrf_hostname_bypass FR-2) — reject internal /
    # cloud-metadata targets before any adapter build or network probe. No-op
    # unless RELYLOOP_ALLOW_PRIVATE_CLUSTERS is False.
    await assert_base_url_allowed(base_url)

    existing = await repo.get_any_cluster_by_name(db, name)
    if existing is not None and existing.deleted_at is None:
        raise ClusterNameTaken(name)

    cluster_id_for_probe = existing.id if existing is not None else str(uuid_utils.uuid7())

    try:
        adapter = _build_adapter_from_args(
            cluster_id=cluster_id_for_probe,
            engine_type=engine_type,
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


async def reprobe_cluster(db: AsyncSession, redis: Redis, cluster_id: str) -> Cluster:
    """Re-run capability probe for a registered cluster + persist to engine_config.

    Story A9 / spec FR-2. Selects the row FOR UPDATE so concurrent /reprobe
    calls serialize safely (each call runs its own probe sequentially after
    acquiring the row lock — not strictly "coalesce", per cycle-2 C2-B3
    terminology clarification). On probe failure, raises ``ClusterUnreachable``
    without committing — the row is left at its prior engine_config.

    Currently Solr is the only adapter with a `probe_capabilities` method;
    for ES/OpenSearch this falls through to a health_check-only refresh.
    """
    cluster = await repo.get_cluster_by_id_for_update(db, cluster_id)
    if cluster is None:
        raise ClusterNotFound(cluster_id)

    # SSRF re-validation on the reuse path (see acquire_adapter). No-op unless
    # RELYLOOP_ALLOW_PRIVATE_CLUSTERS is False.
    await assert_base_url_allowed(cluster.base_url)
    try:
        adapter = build_adapter(cluster)
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc

    new_engine_config: dict[str, Any] = dict(cluster.engine_config or {})
    try:
        # Always run a health_check so we know the cluster is reachable + has
        # the correct version. Solr additionally runs probe_capabilities to
        # refresh UBI/LTR/uniqueKey state.
        health = await adapter.health_check()
        if health.status == "unreachable":
            raise ClusterUnreachable(health.error or "cluster did not respond within timeout")
        if cluster.engine_type == "solr":
            from backend.app.adapters.solr import SolrAdapter

            assert isinstance(adapter, SolrAdapter)  # noqa: S101 — narrow type for mypy
            probe = await adapter.probe_capabilities()
            new_engine_config.update(probe.model_dump())
        elif health.version:
            new_engine_config["api_version"] = health.version.split(".")[0]
    finally:
        await adapter.aclose()

    updated = await repo.update_cluster_engine_config(
        db, cluster_id, engine_config=new_engine_config or None
    )
    await db.commit()
    await write_cached_health(redis, cluster_id, health)
    return updated or cluster


async def test_cluster_connection(
    *,
    engine_type: str,
    base_url: str,
    auth_kind: str,
    credentials_ref: str,
    engine_config: dict[str, Any] | None,
) -> ConnectionTestSummary:
    """Build a transient adapter from unsaved form fields and probe.

    Returns a `ConnectionTestSummary` without writing to the database. Validates
    the engine×auth pairing BEFORE the network call so an invalid combo 400s
    rather than wasting a probe round-trip. The endpoint is a diagnostic — it
    always returns a structured result, never raises for transport-level
    failures (those surface as ``reachable=False`` with ``error`` set).

    Validation that DOES raise (translated to 400 at the router):
    * ``EngineTypeNotSupported`` — unknown engine_type
    * ``AuthKindNotSupported`` — engine_type×auth_kind mismatch / reserved
    * ``ClusterUnreachable`` — credentials resolution failed before any probe
    """
    if engine_type not in SUPPORTED_ENGINE_TYPES:
        raise EngineTypeNotSupported(
            f"engine_type must be one of: {sorted(SUPPORTED_ENGINE_TYPES)} (got: {engine_type!r})"
        )
    if auth_kind in RESERVED_AUTH_KINDS:
        raise AuthKindNotSupported(f"{auth_kind!r} is reserved but not implemented in MVP2")
    if auth_kind not in SUPPORTED_AUTH_KINDS:
        raise AuthKindNotSupported(
            f"auth_kind must be one of: "
            f"{sorted(SUPPORTED_AUTH_KINDS | RESERVED_AUTH_KINDS)} "
            f"(got: {auth_kind!r})"
        )
    allowed_for_engine = ALLOWED_AUTH_PER_ENGINE.get(engine_type, frozenset())
    if auth_kind not in allowed_for_engine:
        raise AuthKindNotSupported(
            f"auth_kind={auth_kind!r} is not valid for engine_type={engine_type!r}; "
            f"allowed for {engine_type!r}: {sorted(allowed_for_engine)}"
        )

    # SSRF guard (bug_cluster_url_ssrf_hostname_bypass FR-2) — same pre-probe
    # rejection as register_cluster. No-op unless RELYLOOP_ALLOW_PRIVATE_CLUSTERS
    # is False.
    await assert_base_url_allowed(base_url)

    try:
        adapter = _build_adapter_from_args(
            cluster_id="transient",
            engine_type=engine_type,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=engine_config,
        )
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc

    try:
        health = await adapter.health_check()
        reachable = health.status in ("green", "yellow")
        capabilities: dict[str, Any] | None = None
        # For reachable Solr clusters, also run probe_capabilities (best-effort)
        # so the operator sees UBI/LTR/uniqueKey availability before submitting.
        if reachable and engine_type == "solr":
            from backend.app.adapters.solr import SolrAdapter

            assert isinstance(adapter, SolrAdapter)  # noqa: S101 — narrow type for mypy
            try:
                probe = await adapter.probe_capabilities()
                capabilities = probe.model_dump()
            except ClusterUnreachableError:
                # Probe failed but health passed — surface capabilities=None
                # rather than rejecting the test result; operator can still
                # register and run reprobe later.
                capabilities = None
        return ConnectionTestSummary(
            reachable=reachable,
            status=health.status,
            version=health.version,
            engine_capabilities=capabilities,
            error=health.error,
        )
    finally:
        await adapter.aclose()


class ClusterNotFound(LookupError):
    """Cluster row not found. Maps to 404 CLUSTER_NOT_FOUND at the router."""


class ConnectionTestSummary:
    """Internal service-layer wrapper around the connection-test result.

    The router maps this to the ``ConnectionTestResult`` Pydantic schema.
    Defined as a plain class (not a Pydantic model) so the service layer
    stays Pydantic-free at the boundary.
    """

    def __init__(
        self,
        *,
        reachable: bool,
        status: str,
        version: str | None,
        engine_capabilities: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        """Capture the probe result fields."""
        self.reachable = reachable
        self.status = status
        self.version = version
        self.engine_capabilities = engine_capabilities
        self.error = error


async def get_or_probe_health(redis: Redis, cluster: Cluster) -> HealthStatus:
    """Return cached HealthStatus, or probe + cache (30s TTL).

    Catches ``CredentialsMissing`` from adapter construction so a missing
    YAML entry surfaces as an ``unreachable`` health rather than escaping
    to the router as a 500.
    """
    cached = await read_cached_health(redis, cluster.id)
    if cached is not None:
        return cached
    # SSRF re-validation on the reuse path (see acquire_adapter). A rebound host
    # is surfaced as a cached ``unreachable`` health rather than a 500 so the
    # /healthz aggregate (cache-only per Absolute Rule #11) degrades cleanly.
    # No-op unless RELYLOOP_ALLOW_PRIVATE_CLUSTERS is False.
    try:
        await assert_base_url_allowed(cluster.base_url)
    except ClusterUrlBlocked as exc:
        health = HealthStatus(
            status="unreachable",
            checked_at=datetime.now(UTC).isoformat(),
            error=f"cluster base_url blocked by SSRF policy: {exc}",
        )
        await write_cached_health(redis, cluster.id, health)
        return health
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
async def acquire_adapter(cluster: Cluster) -> AsyncIterator[ClusterAdapter]:
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
    # SSRF re-validation on the reuse path (bug_cluster_url_ssrf_hostname_bypass
    # Phase 2 — DNS-rebinding TOCTOU mitigation). The registration-time guard
    # classified the *then*-current DNS resolution and stored an immutable
    # base_url; re-running it here re-resolves + re-classifies on every adapter
    # build, so a host that pointed at a public IP at registration but was later
    # rebound to an internal/metadata address is caught before we connect.
    # No-op unless RELYLOOP_ALLOW_PRIVATE_CLUSTERS is False. Does not defeat a
    # within-single-connection rebind — full connect-time IP pinning remains the
    # residual Phase-2 item.
    await assert_base_url_allowed(cluster.base_url)
    try:
        adapter = build_adapter(cluster)
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc
    try:
        yield adapter
    finally:
        await adapter.aclose()


async def dispatch_run_query(
    adapter: ClusterAdapter,
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
    # Per-engine body shape (infra_adapter_solr review F1): NativeQuery.body
    # is the *engine-native* request body. For ES/OpenSearch that's the
    # search-request body (`{query, size}` → an `_msearch` line). For Solr
    # it's the `/select` request-parameter dict — wrapping it in
    # `{"query": ..., "size": ...}` would hand Solr the meaningless params
    # `query` + `size` instead of `q`/`rows`, silently returning wrong
    # results. So for Solr we pass `query_dsl` through as Solr params and let
    # `SolrAdapter._build_select_request` add `rows`/`fl`.
    if adapter.engine_type == "solr":
        query = NativeQuery(query_id="run_query", body=dict(query_dsl))
    else:
        query = NativeQuery(query_id="run_query", body={"query": query_dsl, "size": top_k})
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


def build_adapter(cluster: Cluster) -> ClusterAdapter:
    """Construct a fresh adapter from a stored cluster row.

    Dispatches on ``cluster.engine_type``: ``elasticsearch``/``opensearch`` →
    ``ElasticAdapter``; ``solr`` → ``SolrAdapter`` (added by
    ``infra_adapter_solr`` Story A1). The unified ``SearchAdapter`` Protocol
    contract means callers don't care which concrete class is returned —
    they call Protocol methods.
    """
    return _build_adapter_from_args(
        cluster_id=cluster.id,
        engine_type=cluster.engine_type,
        base_url=cluster.base_url,
        auth_kind=cluster.auth_kind,
        credentials_ref=cluster.credentials_ref,
        engine_config=cluster.engine_config,
    )


def _build_adapter_from_args(
    *,
    cluster_id: str,
    engine_type: str,
    base_url: str,
    auth_kind: str,
    credentials_ref: str,
    engine_config: dict[str, Any] | None,
) -> ClusterAdapter:
    """Internal factory shared by ``build_adapter`` and ``register_cluster``.

    ``build_adapter`` is row-driven (a persisted ``Cluster`` already exists);
    ``register_cluster`` is request-driven (no row yet — the probe runs
    before the INSERT). Both share this factory so the dispatch logic stays
    in one place.

    Dispatches strictly on ``engine_type``. Unknown engines raise
    ``EngineTypeNotSupported`` (translated to 400 by the router).
    """
    if engine_type == "solr":
        return SolrAdapter(
            cluster_id=cluster_id,
            engine_type="solr",
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=engine_config,
        )
    if engine_type in ("elasticsearch", "opensearch"):
        return ElasticAdapter(
            cluster_id=cluster_id,
            engine_type=engine_type,  # type: ignore[arg-type]
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=engine_config,
        )
    raise EngineTypeNotSupported(
        f"engine_type={engine_type!r} has no adapter; supported: {sorted(SUPPORTED_ENGINE_TYPES)}"
    )
