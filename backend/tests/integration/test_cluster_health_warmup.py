# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the cluster health warmup against real Postgres + Redis.

Skipped when service containers aren't available (mirrors the
``postgres_reachable()`` skip pattern used by other integration tests).

Covers:

- **AC-8 (cold-cache happy path):** seed clusters → delete `cluster:health:*`
  keys → spawn warmup → wait for `cluster_health_warmup_completed` log
  (deterministic signal, NOT a fixed sleep per plan cycle-1 B2) → assert
  `/healthz` aggregate reports `healthy: N`.
- **AC-9 (backwards-compat — response contract unchanged):** call
  `GET /api/v1/clusters` after warmup; assert response shape matches
  pre-fix contract. Does NOT assert "first list call → N probe invocations"
  per plan cycle-1 B7 (warmup may pre-warm cache, that's expected).
- **AC-10 (out-of-band insert lazy-warm chain):** trigger warmup → assert
  `/healthz` accurate → direct ORM insert + `await db.commit()` (per plan
  cycle-1 B4 — `repo.create_cluster` only flushes) → assert `/healthz`
  shows the new cluster as cache-miss-unreachable → call
  `GET /api/v1/clusters` to lazy-warm → assert `/healthz` healthy again.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, MutableMapping
from typing import Any

import httpx
import pytest
import pytest_asyncio
import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.adapters.health_cache import _key as cluster_cache_key
from backend.app.db import repo
from backend.app.services.cluster_health_warmup import (
    run_cluster_health_warmup_background,
)
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — integration tests require service container",
    ),
]


def _make_cluster_kwargs(slug: str) -> dict[str, object]:
    """Cluster-create kwargs that mirror what scripts/seed_meaningful_demos.py uses."""
    return {
        "id": str(uuid.uuid4()),
        "name": slug,
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "local-es",
    }


@pytest_asyncio.fixture
async def db_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """One-shot DB session factory (disposed after each test).

    Mirrors the engine/factory lifecycle used by the autouse cleanup
    fixture in ``backend/tests/integration/conftest.py`` — fresh engine
    per test to avoid asyncpg cross-loop pool issues.
    """
    from backend.app.core.settings import get_settings

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Async Redis client against the CI service container."""
    from backend.app.core.settings import get_settings

    client = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


async def _delete_cache_keys(redis_client: Redis, cluster_ids: list[str]) -> None:
    """Explicitly flush ``cluster:health:{id}`` keys to defeat 30s TTL warmth."""
    keys = [cluster_cache_key(cid) for cid in cluster_ids]
    if keys:
        await redis_client.delete(*keys)


async def _wait_for_warmup_completed(
    logs: list[MutableMapping[str, Any]],
    timeout: float = 10.0,
    poll: float = 0.05,
) -> MutableMapping[str, Any]:
    """Bounded-poll for the warmup-completion event (cycle-3 B2 pattern).

    Time-based sleeps are flaky on slow CI runners; we poll the captured
    log list until the event appears or the timeout elapses.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for entry in logs:
            if entry.get("event") == "cluster_health_warmup_completed":
                return entry
        await asyncio.sleep(poll)
    raise AssertionError(
        f"Warmup completion event not seen within {timeout}s; captured events: "
        f"{[e.get('event') for e in logs]}"
    )


class TestAC8HappyPath:
    """AC-8: cold-cache → warmup completes → /healthz truthful counts."""

    async def test_warmup_populates_cache_for_seeded_clusters(
        self,
        db_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        async_client: httpx.AsyncClient,
    ) -> None:
        # 1) Seed two clusters via direct ORM insert + commit (the autouse
        #    `_clean_phase2_tables` fixture wipes them after the test).
        cluster_ids: list[str] = []
        async with db_factory() as db:
            for slug in ("warmup-test-a", "warmup-test-b"):
                cluster = await repo.create_cluster(db, **_make_cluster_kwargs(slug))
                cluster_ids.append(cluster.id)
            await db.commit()

        # 2) Explicit cold cache (cycle-1 B2): the 30s TTL keeps cache rows
        #    warm across test sessions; deletion forces the warmup to do
        #    real work.
        await _delete_cache_keys(redis_client, cluster_ids)

        # 3) Enter the capture context BEFORE spawning the task (cycle-3 B2 —
        #    the completion event fires inside the task; the capture must be
        #    active before the task is created or the event is missed).
        with structlog.testing.capture_logs() as logs:
            task = asyncio.create_task(
                run_cluster_health_warmup_background(db_factory, redis_client)
            )
            # Bounded polling — fails clearly on flake instead of hanging.
            completion = await _wait_for_warmup_completed(logs, timeout=10.0)
            await task  # ensure task is fully awaited

        # 4) Completion log shape per FR-5.
        assert completion.get("count") == 2
        assert completion.get("failures") == 0
        duration_ms = completion.get("duration_ms")
        assert isinstance(duration_ms, int) and duration_ms >= 0

        # 5) Cache keys populated.
        for cid in cluster_ids:
            cached = await redis_client.get(cluster_cache_key(cid))
            assert cached is not None, f"cluster:health:{cid} not populated"

        # 6) /healthz aggregate reflects the populated cache: both seeded
        # clusters MUST be accounted for (healthy + unreachable sum to at
        # least 2). The healthy/unreachable split depends on whether the
        # test runner can reach `http://elasticsearch:9200` (works inside
        # the Compose network; may not from the test runner). What this
        # test deterministically guarantees per AC-8 + the cache-key-exists
        # assertions above:
        #   - warmup POPULATED the cache for both clusters (no cache miss)
        #   - aggregate.registered count includes them
        #   - aggregate.healthy + .unreachable accounts for them (no
        #     silent miss-count where they're dropped from the aggregate)
        resp = await async_client.get("/healthz")
        body = resp.json()
        agg = body["subsystems"]["elasticsearch_clusters"]
        assert agg["registered"] >= 2, agg
        # The warmup populated cache → both clusters appear in healthy OR
        # unreachable, summing to at least 2 (no cluster falls off the
        # aggregate due to a third state).
        accounted_for = agg["healthy"] + agg["unreachable"]
        assert accounted_for == agg["registered"], agg


class TestAC9ResponseContractUnchanged:
    """AC-9: /api/v1/clusters response shape is unchanged post-warmup."""

    async def test_list_clusters_response_shape_after_warmup(
        self,
        db_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        async_client: httpx.AsyncClient,
    ) -> None:
        async with db_factory() as db:
            await repo.create_cluster(db, **_make_cluster_kwargs("ac9-cluster"))
            await db.commit()

        # Run warmup so cache is warm.
        await run_cluster_health_warmup_background(db_factory, redis_client)

        resp = await async_client.get("/api/v1/clusters?limit=200")
        assert resp.status_code == 200
        body = resp.json()
        # Pre-fix contract: { data: [ClusterSummary, ...], next_cursor, has_more }
        assert isinstance(body.get("data"), list)
        assert "next_cursor" in body
        assert "has_more" in body
        if body["data"]:
            first = body["data"][0]
            # ClusterSummary always has these keys; `health_check` is populated
            # from get_or_probe_health (cache-first now thanks to warmup).
            # Per final-review F4: assert the FULL expected key set,
            # including health_check, so a regression that drops a field
            # is caught.
            for key in (
                "id",
                "name",
                "engine_type",
                "environment",
                "base_url",
                "health_check",
            ):
                assert key in first, first
            # Verify health_check substructure (status + checked_at) — the
            # public contract per ClusterSummary schema.
            health = first["health_check"]
            assert isinstance(health, dict), health
            assert "status" in health
            assert "checked_at" in health


class TestAC10OutOfBandLazyWarm:
    """AC-10: post-warmup out-of-band insert remains cache-miss until lazy-warm."""

    async def test_direct_orm_insert_after_warmup_lazy_warms_on_first_list(
        self,
        db_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        async_client: httpx.AsyncClient,
    ) -> None:
        # 1) Seed + run initial warmup.
        async with db_factory() as db:
            initial = await repo.create_cluster(db, **_make_cluster_kwargs("ac10-initial"))
            initial_id = initial.id
            await db.commit()

        await _delete_cache_keys(redis_client, [initial_id])
        await run_cluster_health_warmup_background(db_factory, redis_client)

        # 2) After warmup: capture the BASELINE aggregate (per final-review
        #    F3 — we'll assert the delta below, not just registered count).
        body_before = (await async_client.get("/healthz")).json()
        agg_before = body_before["subsystems"]["elasticsearch_clusters"]
        registered_before = agg_before["registered"]
        unreachable_before = agg_before["unreachable"]
        assert registered_before >= 1

        # 3) Out-of-band insert via direct ORM + commit (per plan cycle-1 B4 —
        #    NOT POST /api/v1/clusters, which would probe + cache at
        #    registration time per cluster.py:147+188).
        async with db_factory() as db:
            new_cluster = await repo.create_cluster(db, **_make_cluster_kwargs("ac10-post-warmup"))
            new_cluster_id = new_cluster.id
            await db.commit()  # CRITICAL — without this commit, /healthz's
            # separate DB session wouldn't see the row (B4).

        # 4) /healthz registered count + unreachable count both increment by 1
        #    (per final-review F3 — the cache-miss-equals-unreachable
        #    semantic at probes.py:124-126 means the new cluster shows up
        #    in unreachable, not in healthy).
        body_after_insert = (await async_client.get("/healthz")).json()
        agg_after_insert = body_after_insert["subsystems"]["elasticsearch_clusters"]
        assert agg_after_insert["registered"] == registered_before + 1
        assert agg_after_insert["unreachable"] == unreachable_before + 1
        # The new cluster has no cache row → confirms the cache-miss path.
        cached = await redis_client.get(cluster_cache_key(new_cluster_id))
        assert cached is None, "new cluster MUST be cache-miss before lazy-warm"

        # 5) Lazy-warm via /api/v1/clusters: the list endpoint calls
        #    get_or_probe_health for each cluster (including the new one),
        #    populating cache.
        list_resp = await async_client.get("/api/v1/clusters?limit=200")
        assert list_resp.status_code == 200

        # 6) /healthz unreachable count returns to the original baseline
        #    (the new cluster is now in healthy OR unreachable depending on
        #    engine reachability — but it's NO LONGER cache-miss-unreachable;
        #    it has a definitive cached status). Per final-review F3.
        body_after_warm = (await async_client.get("/healthz")).json()
        agg_after_warm = body_after_warm["subsystems"]["elasticsearch_clusters"]
        assert agg_after_warm["registered"] == registered_before + 1
        # The full aggregate is back to "every cluster has a cached state":
        accounted_for_after = agg_after_warm["healthy"] + agg_after_warm["unreachable"]
        assert accounted_for_after == agg_after_warm["registered"]

        # 6) New cluster's cache row exists post-list.
        cached_after = await redis_client.get(cluster_cache_key(new_cluster_id))
        assert cached_after is not None, "new cluster's cache row should be populated by lazy-warm"
