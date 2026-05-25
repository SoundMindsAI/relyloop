"""Unit tests for :mod:`backend.app.services.cluster`.

Focused on the cache-write invariants of :func:`get_or_probe_health`. The
function was extended by ``bug_demo_clusters_unreachable_in_healthz`` Story
1.1 (FR-7) to cache the synthetic ``HealthStatus(unreachable)`` returned
when ``CredentialsMissing`` is raised — see the spec §19 D-7.

Cache-hit short-circuit (AC-3) and the FR-7 regression guard (AC-11) live
here per the spec's §14 test-strategy table (and per cycle-1 B1 of the
plan review — the cache-first behavior is INSIDE ``get_or_probe_health``,
not inside the warmup function).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis

from backend.app.adapters.credentials import CredentialsMissing
from backend.app.adapters.protocol import HealthStatus
from backend.app.db.models.cluster import Cluster
from backend.app.services import cluster as cluster_svc


def _make_cluster(name: str = "test-cluster", credentials_ref: str = "missing-ref-xyz") -> Cluster:
    """Construct an in-memory Cluster instance for unit tests (no DB)."""
    return Cluster(
        id="019e5d00-0000-7000-8000-000000000000",
        name=name,
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://test-cluster:9200",
        auth_kind="es_basic",
        credentials_ref=credentials_ref,
        config_repo_id=None,
        config_path=None,
        engine_config=None,
        notes=None,
        target_filter=None,
        created_at=datetime.now(UTC),
        deleted_at=None,
    )


def _make_redis_with_no_cache() -> MagicMock:
    """Mocked Redis whose ``get`` returns None (cache miss) and ``set`` succeeds.

    Returns ``MagicMock`` (not ``Redis``) so mypy sees the mock's
    ``call_count`` / ``call_args`` attributes — matches the
    ``_make_redis()`` pattern at ``backend/tests/unit/test_capability_check.py:142``.
    """
    client = MagicMock(spec=Redis)
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    return client


def _make_redis_with_cached(cached_json: bytes) -> MagicMock:
    """Mocked Redis whose ``get`` returns a pre-cached JSON-serialized HealthStatus."""
    client = MagicMock(spec=Redis)
    client.get = AsyncMock(return_value=cached_json)
    client.set = AsyncMock(return_value=True)
    return client


# ---------------------------------------------------------------------------
# AC-11 — FR-7 CredentialsMissing cache-write regression guard
# ---------------------------------------------------------------------------


class TestCredentialsMissingCachesUnreachable:
    """Guard for ``bug_demo_clusters_unreachable_in_healthz`` Story 1.1.

    Pre-fix: ``get_or_probe_health`` returned the synthetic unreachable
    HealthStatus without calling ``write_cached_health``, so cache stayed
    empty and ``probe_registered_clusters`` re-reported the cluster as
    cache-miss-unreachable on every poll. Post-fix: the cache always
    lands with a value in EVERY branch.
    """

    async def test_credentials_missing_writes_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-11 positive: first call synthesizes + caches + returns."""
        cluster = _make_cluster(credentials_ref="missing-ref-xyz")
        redis = _make_redis_with_no_cache()

        def _raise_missing(_cluster: Cluster) -> object:
            raise CredentialsMissing("entry not found: missing-ref-xyz")

        monkeypatch.setattr(cluster_svc, "build_adapter", _raise_missing)

        result = await cluster_svc.get_or_probe_health(redis, cluster)

        assert result.status == "unreachable"
        assert result.error is not None
        assert "missing-ref-xyz" in result.error
        # FR-7: cache MUST have been written exactly once with the cluster's key.
        assert redis.set.call_count == 1
        # First positional arg to redis.set is the cache key.
        from backend.app.adapters.health_cache import _key as cache_key

        assert redis.set.call_args.args[0] == cache_key(cluster.id)

    async def test_second_call_returns_cached_without_rebuilding_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-11 negative: a second call within the 30s TTL is a cache-hit
        and does NOT re-invoke ``build_adapter``.

        Simulates the warmup running twice within the TTL (e.g. operator
        restarts the API container while the cache from a prior boot is
        still warm). The cache-first branch at lines 199-201 must return
        the cached value without re-attempting credential resolution.
        """
        cluster = _make_cluster(credentials_ref="missing-ref-xyz")
        # Pre-cache a synthesized unreachable result.
        cached_health = HealthStatus(
            status="unreachable",
            checked_at=datetime.now(UTC).isoformat(),
            error="credentials resolution failed: entry not found: missing-ref-xyz",
        )
        redis = _make_redis_with_cached(cached_health.model_dump_json().encode("utf-8"))

        def _must_not_be_called(_cluster: Cluster) -> object:
            pytest.fail("build_adapter MUST NOT be invoked on cache hit (cluster.py:199-201)")

        monkeypatch.setattr(cluster_svc, "build_adapter", _must_not_be_called)

        result = await cluster_svc.get_or_probe_health(redis, cluster)

        assert result.status == "unreachable"
        assert result.error == cached_health.error
        # build_adapter was NOT called (asserted via pytest.fail above);
        # additionally, redis.set was NOT called (no re-cache on hit).
        assert redis.set.call_count == 0


# ---------------------------------------------------------------------------
# AC-3 — Cache-hit short-circuit on successful prior probe
# ---------------------------------------------------------------------------


class TestCacheHitShortCircuit:
    """AC-3: when ``cluster:health:{id}`` is populated with a SUCCESS
    result, ``get_or_probe_health`` returns the cached value without
    calling ``build_adapter`` or ``adapter.health_check()``.

    Moved here from the warmup test file per plan cycle-1 B1: the
    cache-first behavior is a property of ``get_or_probe_health``, not
    of the warmup loop that calls it.
    """

    async def test_cache_hit_does_not_invoke_build_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cluster = _make_cluster(credentials_ref="local-es")
        cached_health = HealthStatus(
            status="green",
            checked_at=datetime.now(UTC).isoformat(),
            error=None,
        )
        redis = _make_redis_with_cached(cached_health.model_dump_json().encode("utf-8"))

        def _must_not_be_called(_cluster: Cluster) -> object:
            pytest.fail("build_adapter MUST NOT be invoked when cache hit at cluster.py:199-201")

        monkeypatch.setattr(cluster_svc, "build_adapter", _must_not_be_called)

        result = await cluster_svc.get_or_probe_health(redis, cluster)

        assert result.status == "green"
        # No new write on cache hit (the cached row already has the 30s TTL).
        assert redis.set.call_count == 0
