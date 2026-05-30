# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`backend.app.services.cluster_health_warmup`.

Maps to plan Story 1.2 DoD: AC-2, AC-4, AC-5, AC-6, FR-5, FR-6, and the
DB-session-release portion of AC-7 (FR-4 / D-10).

Per plan cycle-1 B1, AC-3 (cache-hit short-circuit) lives in
``test_cluster_service.py`` instead because the cache-first behavior is
INSIDE ``get_or_probe_health``, not inside the warmup loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from redis.asyncio import Redis

from backend.app.adapters.protocol import HealthStatus
from backend.app.db import repo
from backend.app.db.models.cluster import Cluster
from backend.app.services import cluster as cluster_svc
from backend.app.services.cluster_health_warmup import (
    run_cluster_health_warmup_background,
)
from backend.tests._log_helpers import assert_log_level


def _make_cluster(name: str, idx: int = 0) -> Cluster:
    """Build an in-memory Cluster row (no DB)."""
    return Cluster(
        id=f"019e5d00-0000-7000-8000-{idx:012d}",
        name=name,
        engine_type="elasticsearch",
        environment="dev",
        base_url=f"http://{name}:9200",
        auth_kind="es_basic",
        credentials_ref="local-es",
        config_repo_id=None,
        config_path=None,
        engine_config=None,
        notes=None,
        target_filter=None,
        created_at=datetime.now(UTC),
        deleted_at=None,
    )


def _make_redis_ok() -> MagicMock:
    """Redis mock with successful ping."""
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(return_value=True)
    return client


def _make_redis_ping_fails() -> MagicMock:
    """Redis mock whose ping raises (simulates Redis-down at warmup start)."""
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(side_effect=RuntimeError("redis unreachable"))
    return client


class _FakeAsyncSession:
    """Records ``__aenter__`` / ``__aexit__`` invocation for FR-4/D-10 testing."""

    def __init__(self) -> None:
        self.enter_calls = 0
        self.exit_calls = 0
        self.last_exit_exc_type: type[BaseException] | None = None

    async def __aenter__(self) -> _FakeAsyncSession:
        self.enter_calls += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.exit_calls += 1
        self.last_exit_exc_type = exc_type


def _make_fake_factory(session: _FakeAsyncSession) -> Any:
    """Return a callable that mimics ``async_sessionmaker[AsyncSession]``."""

    def _factory() -> _FakeAsyncSession:
        return session

    return _factory


# ---------------------------------------------------------------------------
# AC-4 — Empty registry skip path
# ---------------------------------------------------------------------------


class TestEmptyRegistry:
    async def test_count_clusters_zero_skips_paginate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4: ``count → 0`` emits skip log; ``list_clusters`` NOT called."""
        list_calls: list[Any] = []

        async def _count(_db: Any) -> int:
            return 0

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            list_calls.append(kwargs)
            return []

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ok()
            )

        assert list_calls == [], "list_clusters MUST NOT be called when count == 0"
        skipped = [e for e in logs if e.get("event") == "cluster_health_warmup_skipped"]
        assert len(skipped) == 1, logs
        assert skipped[0].get("count") == 0


# ---------------------------------------------------------------------------
# AC-2 + FR-5 — Happy path: walk every cluster, emit single summary log
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_warmup_walks_all_clusters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-2: 3 clusters → get_or_probe_health called 3 times; completion
        log has count=3, failures=0, duration_ms >= 0.
        """
        clusters = [_make_cluster(f"c{i}", idx=i) for i in range(3)]

        async def _count(_db: Any) -> int:
            return len(clusters)

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            # Mirror the cursor-based pagination loop in the warmup. With
            # limit=200 and 3 clusters, this returns the whole list on the
            # first call. The warmup exits the while-loop when len(page)
            # < limit, so a single call is sufficient.
            return list(clusters)

        probe_calls: list[str] = []

        async def _probe(_redis: Any, cluster: Cluster) -> HealthStatus:
            probe_calls.append(cluster.id)
            return HealthStatus(
                status="green",
                checked_at=datetime.now(UTC).isoformat(),
                error=None,
            )

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)
        monkeypatch.setattr(cluster_svc, "get_or_probe_health", _probe)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ok()
            )

        assert probe_calls == [c.id for c in clusters]
        completed = [e for e in logs if e.get("event") == "cluster_health_warmup_completed"]
        assert len(completed) == 1, logs
        assert completed[0].get("count") == 3
        assert completed[0].get("failures") == 0
        duration_ms = completed[0].get("duration_ms")
        assert isinstance(duration_ms, int) and duration_ms >= 0

    async def test_warmup_unaffected_by_get_or_probe_health_cache_hits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The warmup just calls get_or_probe_health once per cluster. The
        function's cache-first behavior is tested at the service layer in
        test_cluster_service.py (AC-3 per plan cycle-1 B1). Here we just
        assert the warmup completes cleanly when get_or_probe_health
        returns cached values.
        """
        clusters = [_make_cluster("c0", 0), _make_cluster("c1", 1)]

        async def _count(_db: Any) -> int:
            return len(clusters)

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            return list(clusters)

        async def _probe_returns_cached(_redis: Any, _cluster: Cluster) -> HealthStatus:
            # Simulating a cache hit — get_or_probe_health returns without
            # building any adapter. The warmup doesn't observe this; it
            # just sees the return value.
            return HealthStatus(
                status="green",
                checked_at=datetime.now(UTC).isoformat(),
                error=None,
            )

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)
        monkeypatch.setattr(cluster_svc, "get_or_probe_health", _probe_returns_cached)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ok()
            )

        completed = [e for e in logs if e.get("event") == "cluster_health_warmup_completed"]
        assert len(completed) == 1
        assert completed[0].get("count") == 2
        assert completed[0].get("failures") == 0


# ---------------------------------------------------------------------------
# AC-5 — Per-cluster exceptions don't abort the loop
# ---------------------------------------------------------------------------


class TestPerClusterFailures:
    async def test_one_cluster_raises_loop_continues(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-5: middle cluster raises; first + third still probed; completion
        log has count=3, failures=1; WARN log emitted with cluster ID.
        """
        clusters = [_make_cluster("good-a", 0), _make_cluster("bad", 1), _make_cluster("good-c", 2)]

        async def _count(_db: Any) -> int:
            return len(clusters)

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            return list(clusters)

        probed: list[str] = []

        async def _probe(_redis: Any, cluster: Cluster) -> HealthStatus:
            probed.append(cluster.id)
            if cluster.name == "bad":
                raise RuntimeError("simulated probe failure")
            return HealthStatus(
                status="green",
                checked_at=datetime.now(UTC).isoformat(),
                error=None,
            )

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)
        monkeypatch.setattr(cluster_svc, "get_or_probe_health", _probe)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ok()
            )

        # All 3 were attempted (loop didn't abort).
        assert probed == [c.id for c in clusters]

        # WARN log includes cluster ID + name + error string.
        warn = [e for e in logs if e.get("event") == "cluster_health_warmup_cluster_failed"]
        assert len(warn) == 1, logs
        assert_log_level(warn[0], "warning")
        assert warn[0].get("cluster_id") == clusters[1].id
        assert warn[0].get("cluster_name") == "bad"
        assert "simulated probe failure" in warn[0].get("error", "")

        # Completion log: count=3, failures=1.
        completed = [e for e in logs if e.get("event") == "cluster_health_warmup_completed"]
        assert len(completed) == 1
        assert completed[0].get("count") == 3
        assert completed[0].get("failures") == 1

    async def test_task_level_exception_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-6: ``repo.list_clusters`` raises → warmup catches at the task
        boundary, logs WARN, returns without propagating.
        """

        async def _count(_db: Any) -> int:
            return 5  # registry is non-empty so we enter the paginate loop

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            raise RuntimeError("simulated DB error mid-paginate")

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            # No exception escapes:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ok()
            )

        raised = [e for e in logs if e.get("event") == "cluster_health_warmup_raised"]
        assert len(raised) == 1, logs
        assert_log_level(raised[0], "warning")
        assert "simulated DB error mid-paginate" in raised[0].get("error", "")

        # Completion log NOT fired (task exited early via the except).
        completed = [e for e in logs if e.get("event") == "cluster_health_warmup_completed"]
        assert completed == []


# ---------------------------------------------------------------------------
# FR-6 / D-9 — Redis ping at warmup start
# ---------------------------------------------------------------------------


class TestRedisDownAtStart:
    async def test_redis_ping_failure_logs_warn_and_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-6: Redis ping raises → WARN ``cluster_health_warmup_redis_unavailable``;
        warmup proceeds with per-cluster probes.
        """
        clusters = [_make_cluster("c0", 0)]

        async def _count(_db: Any) -> int:
            return 1

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            return list(clusters)

        probe_called = asyncio.Event()

        async def _probe(_redis: Any, _cluster: Cluster) -> HealthStatus:
            probe_called.set()
            return HealthStatus(
                status="green",
                checked_at=datetime.now(UTC).isoformat(),
                error=None,
            )

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)
        monkeypatch.setattr(cluster_svc, "get_or_probe_health", _probe)

        session = _FakeAsyncSession()
        with structlog.testing.capture_logs() as logs:
            await run_cluster_health_warmup_background(
                _make_fake_factory(session), _make_redis_ping_fails()
            )

        # WARN fired BEFORE any per-cluster probing.
        warn = [e for e in logs if e.get("event") == "cluster_health_warmup_redis_unavailable"]
        assert len(warn) == 1, logs
        assert_log_level(warn[0], "warning")
        assert "redis unreachable" in warn[0].get("error", "")

        # And the warmup STILL probed the cluster (didn't bail on ping failure).
        assert probe_called.is_set()

        # And the completion log fired normally.
        completed = [e for e in logs if e.get("event") == "cluster_health_warmup_completed"]
        assert len(completed) == 1


# ---------------------------------------------------------------------------
# AC-7 / FR-4 / D-10 — Shutdown cancellation releases the DB session
# ---------------------------------------------------------------------------


class TestShutdownCancellation:
    async def test_cancellation_during_probe_does_not_leak_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-4 / D-10 (refactored — see CI feedback on PR #236 round 1):

        The warmup loads all cluster rows under a SHORT-LIVED DB session,
        then releases the session BEFORE the per-cluster probe loop. This
        prevents asyncpg-pool contention when per-cluster HTTP probes
        stall on fake URLs (which made
        test_ac7_concurrent_merges_serialize_via_row_lock fail under
        the lifespan-spawned warmup).

        Test invariants:
         - DB session enters + exits CLEANLY before any probe runs (no
           CancelledError seen by __aexit__).
         - Per-cluster probe receives CancelledError when task.cancel()
           is called mid-loop.
         - The session was already released by the time cancellation
           arrives, so there's no possibility of a "session never
           released" leak under cancellation.
        """
        clusters = [_make_cluster(f"c{i}", idx=i) for i in range(3)]
        probe_started = asyncio.Event()
        blocker = asyncio.Event()
        cancel_seen_in_probe = asyncio.Event()

        async def _count(_db: Any) -> int:
            return len(clusters)

        async def _list(_db: Any, **kwargs: Any) -> list[Cluster]:
            return list(clusters)

        async def _probe(_redis: Any, _cluster: Cluster) -> HealthStatus:
            probe_started.set()
            # Block forever until cancellation arrives.
            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancel_seen_in_probe.set()
                raise
            return HealthStatus(
                status="green",
                checked_at=datetime.now(UTC).isoformat(),
                error=None,
            )

        monkeypatch.setattr(repo, "count_clusters", _count)
        monkeypatch.setattr(repo, "list_clusters", _list)
        monkeypatch.setattr(cluster_svc, "get_or_probe_health", _probe)

        session = _FakeAsyncSession()
        task = asyncio.create_task(
            run_cluster_health_warmup_background(_make_fake_factory(session), _make_redis_ok())
        )

        # Synchronization point: wait for the probe to have entered the loop.
        await probe_started.wait()
        # The per-page refactor opens TWO sessions before reaching the probe
        # loop: (1) count_clusters, (2) first page's list_clusters. Each
        # opens AND exits cleanly before its respective work — no session
        # is held during the per-cluster HTTP probes.
        assert session.enter_calls == 2
        assert session.exit_calls == 2
        assert session.last_exit_exc_type is None  # clean exit, no exception

        # Now cancel and confirm CancelledError propagates through the probe.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The probe coroutine saw the cancellation.
        assert cancel_seen_in_probe.is_set()
        # Session counters unchanged from before cancellation — both sessions
        # were already released; no double-close, no leak.
        assert session.exit_calls == 2
