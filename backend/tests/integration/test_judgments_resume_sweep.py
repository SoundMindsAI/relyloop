"""Integration tests for ``backend.workers.judgments_resume.resume_stuck_judgment_lists``.

Spec: docs/00_overview/planned_features/feat_judgments_periodic_resume_sweep/feature_spec.md

Covers AC-3 (no-op tick), AC-4 (one row, counter < cap + full FR-6 log
contract), AC-5 (cap breach), AC-6 (per-id failure isolation), AC-7
(boot-sweep dedup coexistence), plus TTL refresh on every INCR.

Real Postgres via ``get_session_factory()`` + real Redis via
``Redis.from_url(real_settings.redis_url, ...)`` — same shape as
:mod:`backend.tests.integration.test_polling_reconciler` and
:mod:`backend.tests.integration.test_budget_guardrail`. The only fake is
the Arq pool, mocked via :class:`unittest.mock.AsyncMock` so the test
can introspect ``enqueue_job`` calls without booting an Arq worker.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import structlog
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests._log_helpers import assert_log_level
from backend.tests.conftest import postgres_reachable
from backend.workers.judgments_resume import (
    _TTL_SECONDS,
    resume_counter_key,
    resume_stuck_judgment_lists,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_stuck_judgment_list(name_suffix: str | None = None) -> str:
    """Insert a (cluster, query_set, judgment_list status='generating') chain.

    Returns the judgment_list id. Mirrors
    :func:`backend.tests.integration.test_judgment_repo._seed_chain` but
    minimal — this test only needs the parent row, not queries/judgments.
    """
    suffix = name_suffix or uuid.uuid4().hex[:8]
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"rs-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"rs-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"rs-qs-{suffix}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"rs-jl-{suffix}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="generating",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
        return jl.id


_TRACKED_KEYS_BY_CLIENT: dict[int, set[str]] = {}


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Yield a per-test Redis client + clean up any keys this test wrote.

    Tracks keys for cleanup via a module-level dict keyed by ``id(client)``;
    tests register keys via :func:`_track` and the fixture's teardown
    deletes them. Using a sidecar dict (rather than stashing the set on
    the Redis client itself) keeps mypy/ruff happy without ``setattr``
    or dynamic attribute access on a third-party class.
    """
    settings = get_settings()
    client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    _TRACKED_KEYS_BY_CLIENT[id(client)] = set()
    try:
        yield client
    finally:
        # Best-effort cleanup of any keys the test created.
        tracked = _TRACKED_KEYS_BY_CLIENT.pop(id(client), set())
        for key in tracked:
            try:
                await client.delete(key)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        await client.aclose()


def _track(redis_client: Redis, *keys: str) -> None:
    """Register Redis keys for cleanup at end-of-test."""
    tracked = _TRACKED_KEYS_BY_CLIENT.setdefault(id(redis_client), set())
    tracked.update(keys)


async def test_no_stuck_rows_returns_clean_summary(redis_client: Redis) -> None:
    """AC-3: empty judgment_lists table → ``{candidates: 0, ...}``.

    No ``judgment_stuck_detected`` log line emitted because count=0.
    """
    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock()
    ctx = {"arq_pool": fake_pool}

    with structlog.testing.capture_logs() as captured:
        summary = await resume_stuck_judgment_lists(ctx)

    assert summary == {"candidates": 0, "enqueued": 0, "capped": 0, "errored": 0}
    fake_pool.enqueue_job.assert_not_awaited()
    events = [e["event"] for e in captured]
    assert "judgment_stuck_detected" not in events
    # FR-6: always emit judgments_resume_tick_complete, even on no-op.
    assert "judgments_resume_tick_complete" in events


async def test_one_stuck_row_enqueues_with_deterministic_job_id_and_logs(
    redis_client: Redis,
) -> None:
    """AC-4 + FR-6: enqueue with ``_job_id``, INCR counter, refresh TTL, log every required event.

    Asserts:
    * Exactly one ``enqueue_job`` call with the deterministic ``_job_id``.
    * Redis counter = 1 after the tick.
    * TTL is approximately ``_TTL_SECONDS`` (between -60 and the full value).
    * FR-6 log contract: ``judgment_stuck_detected`` + ``judgment_resume_enqueued``
      + ``judgments_resume_tick_complete`` each emitted exactly once with full
      payloads.
    """
    jid = await _seed_stuck_judgment_list()
    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=object())  # successful enqueue
    ctx = {"arq_pool": fake_pool}

    key = resume_counter_key(datetime.now(UTC), jid)
    _track(redis_client, key)

    with structlog.testing.capture_logs() as captured:
        summary = await resume_stuck_judgment_lists(ctx)

    # 1. Summary
    assert summary == {"candidates": 1, "enqueued": 1, "capped": 0, "errored": 0}

    # 2. Enqueue call: deterministic _job_id matching the boot-time sweep.
    fake_pool.enqueue_job.assert_awaited_once_with(
        "generate_judgments_llm",
        jid,
        _job_id=f"generate_judgments_llm:{jid}",
    )

    # 3. Redis counter state.
    raw = await redis_client.get(key)
    assert raw is not None
    assert int(raw) == 1

    # 4. TTL is approximately 26h. ``redis.ttl`` returns remaining seconds
    #    (or -1 if no TTL, -2 if no key). Tolerate up to 60s slip for the
    #    real-time clock between INCR and TTL fetch.
    ttl = await redis_client.ttl(key)
    assert _TTL_SECONDS - 60 <= ttl <= _TTL_SECONDS

    # 5. FR-6 log contract.
    events_by_name: dict[str, list[Any]] = {}
    for entry in captured:
        events_by_name.setdefault(entry["event"], []).append(entry)

    stuck_events = events_by_name.get("judgment_stuck_detected", [])
    assert len(stuck_events) == 1
    assert stuck_events[0]["count"] == 1
    assert stuck_events[0]["cadence_min"] == 15
    assert stuck_events[0]["ids"] == [jid]

    enqueued_events = events_by_name.get("judgment_resume_enqueued", [])
    assert len(enqueued_events) == 1
    assert enqueued_events[0]["event_type"] == "judgment_resume_enqueued"
    assert enqueued_events[0]["judgment_list_id"] == jid

    tick_events = events_by_name.get("judgments_resume_tick_complete", [])
    assert len(tick_events) == 1
    assert tick_events[0]["candidates"] == 1
    assert tick_events[0]["enqueued"] == 1
    assert tick_events[0]["capped"] == 0
    assert tick_events[0]["errored"] == 0
    assert tick_events[0]["cadence_min"] == 15


async def test_cap_breach_skips_enqueue_and_warns(redis_client: Redis) -> None:
    """AC-5: pre-seeded counter at cap → no enqueue, counter advances, WARN log.

    The cap check reads the POST-INCR value; pre-seeding to ``cap`` means
    the next INCR yields ``cap + 1`` which is > cap → capped=True.
    """
    jid = await _seed_stuck_judgment_list()
    cap = get_settings().relyloop_judgments_resume_max_per_day
    key = resume_counter_key(datetime.now(UTC), jid)
    _track(redis_client, key)
    await redis_client.set(key, cap)

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock()
    ctx = {"arq_pool": fake_pool}

    with structlog.testing.capture_logs() as captured:
        summary = await resume_stuck_judgment_lists(ctx)

    assert summary == {"candidates": 1, "enqueued": 0, "capped": 1, "errored": 0}
    fake_pool.enqueue_job.assert_not_awaited()

    raw = await redis_client.get(key)
    assert int(raw or 0) == cap + 1

    capped_events = [e for e in captured if e["event"] == "judgment_resume_capped"]
    assert len(capped_events) == 1
    entry = capped_events[0]
    assert_log_level(entry, "warning")
    assert entry["judgment_list_id"] == jid
    assert entry["count"] == cap + 1
    assert entry["cap"] == cap


async def test_per_id_failure_isolated_loop_continues(redis_client: Redis) -> None:
    """AC-6: first row's enqueue raises → second row still enqueues.

    Handler returns ``{candidates: 2, enqueued: 1, capped: 0, errored: 1}``;
    one ``judgment_resume_errored`` WARN log line for the failing id.
    """
    jid1 = await _seed_stuck_judgment_list(name_suffix="a")
    jid2 = await _seed_stuck_judgment_list(name_suffix="b")
    _track(
        redis_client,
        resume_counter_key(datetime.now(UTC), jid1),
        resume_counter_key(datetime.now(UTC), jid2),
    )

    enqueue_calls: list[str] = []

    async def _selective_enqueue(*args: object, **_kwargs: object) -> object:
        # args = ("generate_judgments_llm", jid)
        jid = args[1] if len(args) >= 2 else None
        assert isinstance(jid, str)
        enqueue_calls.append(jid)
        # Repo returns ids in created_at-ish order; we don't know which is
        # "first" so raise on jid1 specifically.
        if jid == jid1:
            raise RuntimeError("simulated transient Arq failure")
        return object()

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(side_effect=_selective_enqueue)
    ctx = {"arq_pool": fake_pool}

    with structlog.testing.capture_logs() as captured:
        summary = await resume_stuck_judgment_lists(ctx)

    assert summary == {"candidates": 2, "enqueued": 1, "capped": 0, "errored": 1}
    assert set(enqueue_calls) == {jid1, jid2}

    errored = [e for e in captured if e["event"] == "judgment_resume_errored"]
    assert len(errored) == 1
    assert_log_level(errored[0], "warning")
    assert errored[0]["judgment_list_id"] == jid1
    assert errored[0]["error_type"] == "RuntimeError"


async def test_arq_dedup_coexistence_with_boot_sweep(redis_client: Redis) -> None:
    """AC-7: cron's enqueue runs even when boot-sweep already enqueued the same id.

    The handler doesn't introspect Arq's silent dedup result (``enqueue_job``
    may return None when ``_job_id`` is already pending). It counts the
    *attempt* in ``summary["enqueued"]``. The Redis counter still advances —
    by design, the cap counts attempts, not successes (spec AC-7 note).
    """
    jid = await _seed_stuck_judgment_list()
    key = resume_counter_key(datetime.now(UTC), jid)
    _track(redis_client, key)

    fake_pool = AsyncMock()
    # Simulate Arq dedup: enqueue_job returns None for an already-pending _job_id.
    fake_pool.enqueue_job = AsyncMock(return_value=None)
    ctx = {"arq_pool": fake_pool}

    summary = await resume_stuck_judgment_lists(ctx)

    assert summary == {"candidates": 1, "enqueued": 1, "capped": 0, "errored": 0}
    fake_pool.enqueue_job.assert_awaited_once_with(
        "generate_judgments_llm",
        jid,
        _job_id=f"generate_judgments_llm:{jid}",
    )
    assert int(await redis_client.get(key) or 0) == 1


async def test_ttl_refreshed_on_every_tick(redis_client: Redis) -> None:
    """Two consecutive ticks against the same stuck row → TTL refreshed twice.

    Mirrors backend/app/llm/budget_gate.py:86-87 — EXPIRE on every INCR
    prevents the key from expiring mid-day during late-hour activity.
    """
    jid = await _seed_stuck_judgment_list()
    key = resume_counter_key(datetime.now(UTC), jid)
    _track(redis_client, key)

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=object())
    ctx = {"arq_pool": fake_pool}

    # First tick.
    await resume_stuck_judgment_lists(ctx)
    ttl_after_first = await redis_client.ttl(key)
    assert _TTL_SECONDS - 60 <= ttl_after_first <= _TTL_SECONDS

    # Second tick (same row still status='generating' since we didn't run the
    # actual generate_judgments_llm handler).
    await resume_stuck_judgment_lists(ctx)
    ttl_after_second = await redis_client.ttl(key)
    assert _TTL_SECONDS - 60 <= ttl_after_second <= _TTL_SECONDS

    # Counter advanced.
    assert int(await redis_client.get(key) or 0) == 2
