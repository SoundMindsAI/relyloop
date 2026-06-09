# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the async demo-reseed flow.

``POST /api/v1/_test/demo/reseed`` enqueues an Arq job and returns **202**
with an initial ``ReseedStatusResponse{status:"running"}``; the worker
(:func:`backend.workers.demo_reseed.run_demo_reseed`) does the real
wipe + reseed and writes per-phase status to Redis; the frontend polls
``GET /api/v1/_test/demo/reseed/status`` for terminal ``complete`` / ``failed``.

These tests exercise that contract end-to-end against real Postgres + ES/OS
+ Redis (heavy CI lane). The worker is invoked **inline** in the test process
(``await run_demo_reseed(ctx)``) so the advisory lock is held on a connection
this process can observe via ``pg_locks`` (AC-16) and so the cleanup gate
(AC-12) can be driven from the same event loop. The queued Arq job is never
consumed, so the singleton dedup keys are cleared before each test AND between
consecutive POSTs in one test.

Skips cleanly when Postgres / ES / OS / Redis are unbound. Unit coverage of
the Redis status helpers lives at
``backend/tests/unit/services/test_demo_seeding_status.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.services.demo_seeding import (
    DEMO_RESEED_LOCK_KEY,
    DEMO_RESEED_STATUS_KEY,
    ReseedStatusResponse,
    _now_iso,
)
from backend.app.services.demo_seeding import status_set as _status_set
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._demo_reseed_uvicorn import running_uvicorn

# Arq 0.28.0 singleton dedup keys for _job_id="demo_reseed:singleton". The
# inline harness never consumes the queued job, so these persist (~24h TTL)
# and would silently drop the next POST's enqueue — clear them before each
# test and between consecutive POSTs.
_SINGLETON_DEDUP_KEYS: tuple[str, ...] = (
    "arq:job:demo_reseed:singleton",
    "arq:result:demo_reseed:singleton",
    "arq:in-progress:demo_reseed:singleton",
)

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Reachability helpers — skip the test gracefully if ES/OS/Redis aren't bound.
# ---------------------------------------------------------------------------


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def _engine_reachable() -> bool:
    """Check ES (9200) + OS (9201) are bound on localhost (or compose dns)."""
    for host in ("127.0.0.1", "localhost", "elasticsearch", "opensearch"):
        if _tcp_open(host, 9200, 0.3) and _tcp_open("127.0.0.1", 9201, 0.3):
            return True
        if _tcp_open(host, 9200, 0.3):
            for os_host in ("127.0.0.1", "localhost", "opensearch"):
                if _tcp_open(os_host, 9201, 0.3):
                    return True
    return False


def _redis_reachable() -> bool:
    """Best-effort TCP probe of the configured Redis (host:port from redis_url)."""
    from urllib.parse import urlparse

    from backend.app.core.settings import get_settings

    try:
        parsed = urlparse(get_settings().redis_url)
    except Exception:  # noqa: BLE001
        return False
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    if _tcp_open(host, port, 0.3):
        return True
    # The configured host may be a Compose DNS name (`redis`) unresolvable
    # from the test host — fall back to loopback.
    return _tcp_open("127.0.0.1", port, 0.3)


if not postgres_reachable() or not _engine_reachable() or not _redis_reachable():
    pytest.skip(
        "demo reseed integration tests require Postgres + ES + OS + Redis "
        "service containers. Run via `make test-integration` against the dev "
        "stack or in CI where the service containers are provisioned.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Carried-forward autouse fixtures (credentials + engine-host patching).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _stub_cluster_credentials(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Provide ``Settings.cluster_credentials_yaml`` + redirect the worker's
    API self-call base URL to the in-process uvicorn.

    The credentials file backs the in-orchestrator ``POST /api/v1/clusters``
    probe (without it the probe 503s ``CLUSTER_UNREACHABLE``). The
    ``RELYLOOP_WORKER_API_BASE_URL`` override (Story 0.1 / D-3) points the
    worker's inline self-calls at ``127.0.0.1:8000`` — the harness uvicorn —
    instead of the ``api:8000`` Compose alias the worker container would use
    in production. Both env vars survive the autouse ``_clear_settings_caches``
    fixture (which dumps the Settings lru_cache before every test).
    """
    tmp = tmp_path_factory.mktemp("demo_reseed_credentials")
    creds_file = tmp / "cluster_credentials.yaml"
    creds_file.write_text(
        "local-es:\n"
        "  username: elastic\n"
        "  password: changeme\n"
        "local-opensearch:\n"
        "  username: admin\n"
        "  password: admin\n"
    )
    prev_creds = os.environ.get("CLUSTER_CREDENTIALS_FILE")
    prev_base = os.environ.get("RELYLOOP_WORKER_API_BASE_URL")
    os.environ["CLUSTER_CREDENTIALS_FILE"] = str(creds_file)
    os.environ["RELYLOOP_WORKER_API_BASE_URL"] = "http://127.0.0.1:8000"
    try:
        yield
    finally:
        for key, prev in (
            ("CLUSTER_CREDENTIALS_FILE", prev_creds),
            ("RELYLOOP_WORKER_API_BASE_URL", prev_base),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


@pytest.fixture(scope="module", autouse=True)
def _patch_engine_for_test_host() -> Any:
    """Map localhost:9200/9201 → 127.0.0.1 loopback for the in-process uvicorn,
    and rewrite each scenario's ``base_url`` to loopback so the cluster-create
    probe resolves from the test host (which can't resolve Compose DNS names).
    """
    import copy

    import backend.app.services.demo_seeding as svc_mod

    def passthrough(host_base_url: str) -> str:
        if host_base_url == "http://localhost:9200":
            return "http://127.0.0.1:9200"
        if host_base_url == "http://localhost:9201":
            return "http://127.0.0.1:9201"
        raise ValueError(f"unexpected URL in test resolver: {host_base_url}")

    original_scenarios = svc_mod.SCENARIOS
    patched_scenarios = copy.deepcopy(original_scenarios)
    for scenario in patched_scenarios:
        base = scenario["base_url"]
        if base == "http://elasticsearch:9200":
            scenario["base_url"] = "http://127.0.0.1:9200"
        elif base == "http://opensearch:9200":
            scenario["base_url"] = "http://127.0.0.1:9201"
    svc_mod.SCENARIOS = patched_scenarios
    try:
        # Only demo_seeding owns _resolve_engine_base_url now (the async
        # refactor moved cleanup out of the _test route handler), so patch it
        # there only — _test.py no longer has the symbol.
        with patch.object(svc_mod, "_resolve_engine_base_url", passthrough):
            yield
    finally:
        svc_mod.SCENARIOS = original_scenarios


@pytest_asyncio.fixture(scope="module")
async def demo_reseed_base_url() -> AsyncIterator[str]:
    with running_uvicorn() as base_url:
        yield base_url


@pytest_asyncio.fixture
async def demo_reseed_client(
    demo_reseed_base_url: str,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=demo_reseed_base_url, timeout=300.0) as client:
        yield client


@pytest_asyncio.fixture
async def arq_ctx() -> AsyncIterator[dict[str, Any]]:
    """Yield ``{"redis": <real handle>}`` suitable for ``run_demo_reseed(ctx)``.

    The worker reads ``ctx["redis"]`` for status writes; everything else
    (``get_engine``/``get_session_factory``/``get_settings``) resolves to the
    process-wide instances the test queries.
    """
    from backend.app.core.settings import get_settings

    redis: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await redis.ping()
    except Exception as exc:  # noqa: BLE001
        await redis.aclose()
        pytest.skip(f"Redis not reachable for arq_ctx: {exc}")
    try:
        yield {"redis": redis}
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Test-only DB engine for assertions / observers.
# ---------------------------------------------------------------------------


def _make_test_engine() -> Any:
    from backend.app.core.settings import get_settings

    return create_async_engine(get_settings().database_url, future=True)


async def _table_count(engine: Any, table: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


async def _truncate_all_demo_tables(engine: Any) -> None:
    from backend.app.services.demo_seeding import _TRUNCATE_DEMO_TABLES_SQL

    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_DEMO_TABLES_SQL))


async def _clear_singleton_dedup_keys(redis: Redis) -> None:
    """DELETE the three Arq singleton dedup keys. Idempotent."""
    await redis.delete(*_SINGLETON_DEDUP_KEYS)


async def _clear_status_key(redis: Redis) -> None:
    """DELETE the Redis status key so a stale running/complete never leaks a 409."""
    await redis.delete(DEMO_RESEED_STATUS_KEY)


@pytest.fixture
async def db_engine() -> Any:
    engine = _make_test_engine()
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_demo_state_before_each(db_engine: Any) -> Any:
    """Wipe demo tables + ES/OS indices + the Redis status/dedup keys before
    EACH test so every case starts from a clean, 409-free state.
    """
    await _truncate_all_demo_tables(db_engine)

    from backend.app.core.settings import get_settings

    redis: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await _clear_status_key(redis)
        await _clear_singleton_dedup_keys(redis)
    finally:
        await redis.aclose()

    # Best-effort wipe ES + OS indices in case a prior test left them.
    async with httpx.AsyncClient(timeout=10.0) as wipe_client:
        for idx in ("products", "docs-articles", "job-listings"):
            for host in ("http://elasticsearch:9200", "http://127.0.0.1:9200"):
                try:
                    await wipe_client.delete(f"{host}/{idx}", auth=("elastic", "changeme"))
                    break
                except Exception:  # noqa: BLE001 - best-effort wipe
                    continue
        for idx in ("news-articles",):
            for host in ("http://opensearch:9201", "http://127.0.0.1:9201"):
                try:
                    await wipe_client.delete(f"{host}/{idx}", auth=("admin", "admin"))
                    break
                except Exception:  # noqa: BLE001
                    continue
    yield


# ---------------------------------------------------------------------------
# POST-then-poll helpers (Story 1.2).
# ---------------------------------------------------------------------------


async def _get_status(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/v1/_test/demo/reseed/status")
    assert r.status_code == 200, r.text
    return r.json()


def _scenarios_total() -> int:
    """len(SCENARIOS) + 1 — the rich ESCI scenario the POST handler adds."""
    from backend.app.services.demo_seeding import SCENARIOS

    return len(SCENARIOS) + 1


async def post_and_run_to_terminal(
    client: httpx.AsyncClient, ctx: dict[str, Any]
) -> dict[str, Any]:
    """POST → assert 202 + initial running → drive the worker inline → return
    the terminal ``GET /status`` payload. Clears the singleton dedup keys after
    the inline run so a subsequent POST in the same test enqueues cleanly.
    """
    from backend.workers.demo_reseed import run_demo_reseed

    resp = await client.post("/api/v1/_test/demo/reseed", json={})
    assert resp.status_code == 202, resp.text
    initial = resp.json()
    assert initial["status"] == "running", initial
    assert initial["scenarios_completed"] == 0, initial
    assert initial["scenarios_total"] == _scenarios_total(), initial
    assert initial["current_step"], initial
    assert initial["summary"] is None, initial

    await run_demo_reseed(ctx)
    await _clear_singleton_dedup_keys(ctx["redis"])
    return await _get_status(client)


# ---------------------------------------------------------------------------
# AC-1: happy path on a clean DB.
# ---------------------------------------------------------------------------


async def test_reseed_happy_path_on_clean_db(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any, arq_ctx: dict[str, Any]
) -> None:
    terminal = await post_and_run_to_terminal(demo_reseed_client, arq_ctx)
    assert terminal["status"] == "complete", terminal
    assert terminal["summary"] is not None, terminal
    assert terminal["scenarios_completed"] == terminal["scenarios_total"]

    # Counts read runtime summary, never a hardcoded 4/5 (rich scenario may
    # run when an OpenAI key is present → N==5, else N==4).
    summary = terminal["summary"]
    n = summary["clusters_created"]
    # Summary symmetry (demo_seeding.py:1618-1626): clusters + query_sets track
    # len(SCENARIOS)+rich_count exactly; studies == proposals == len(results)+rich.
    assert summary["query_sets_created"] == n
    assert summary["studies_completed"] == summary["proposals_created"]

    # DB counts vs runtime N. `==` for clusters/proposals/query_sets (the rich
    # path registers its own query set → still == N); `>=` for tables the
    # rich/UBI re-entry may augment.
    assert await _table_count(db_engine, "clusters") == n
    assert await _table_count(db_engine, "proposals") == n
    assert await _table_count(db_engine, "query_sets") == n
    assert await _table_count(db_engine, "query_templates") >= n
    assert await _table_count(db_engine, "judgment_lists") >= n
    assert await _table_count(db_engine, "studies") >= n
    assert await _table_count(db_engine, "digests") >= n


# ---------------------------------------------------------------------------
# AC-2: replaces pre-populated demo state (disjoint cluster ids).
# ---------------------------------------------------------------------------


async def test_reseed_replaces_populated_demo_state(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any, arq_ctx: dict[str, Any]
) -> None:
    first = await post_and_run_to_terminal(demo_reseed_client, arq_ctx)
    assert first["status"] == "complete", first
    async with db_engine.connect() as conn:
        first_ids = {row[0] for row in await conn.execute(text("SELECT id FROM clusters"))}
    assert first_ids

    # The helper already cleared the dedup keys after the first run, so the
    # second POST enqueues cleanly.
    second = await post_and_run_to_terminal(demo_reseed_client, arq_ctx)
    assert second["status"] == "complete", second
    async with db_engine.connect() as conn:
        second_ids = {row[0] for row in await conn.execute(text("SELECT id FROM clusters"))}
    assert second_ids
    # UUIDv7 PKs (backend/app/db/models/cluster.py) are fresh after
    # TRUNCATE ... RESTART IDENTITY CASCADE.
    assert first_ids.isdisjoint(second_ids)


# ---------------------------------------------------------------------------
# AC-3: concurrent reseed returns 409; + ARQ_POOL_UNAVAILABLE 503 micro-case.
# ---------------------------------------------------------------------------


async def test_concurrent_reseed_returns_409(
    demo_reseed_client: httpx.AsyncClient, arq_ctx: dict[str, Any]
) -> None:
    # Seed a fresh `running` status directly so the POST's stale-check passes
    # (not stale) and it 409s. Do NOT drive the worker.
    await _status_set(
        arq_ctx["redis"],
        ReseedStatusResponse(
            status="running",
            started_at=_now_iso(),
            scenarios_total=_scenarios_total(),
            scenarios_completed=0,
        ),
    )
    resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "SEED_IN_PROGRESS"
    assert isinstance(detail["message"], str) and detail["message"]
    assert detail["retryable"] is True
    # Clear so the next test doesn't 409 unexpectedly.
    await _clear_status_key(arq_ctx["redis"])


async def test_reseed_arq_pool_unavailable_returns_503(
    demo_reseed_client: httpx.AsyncClient,
) -> None:
    from backend.app.main import app

    prev = getattr(app.state, "arq_pool", None)
    app.state.arq_pool = None
    try:
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
    finally:
        app.state.arq_pool = prev
    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "ARQ_POOL_UNAVAILABLE"
    assert detail["retryable"] is True


# ---------------------------------------------------------------------------
# AC-5: mid-loop engine failure → terminal `failed` + cleanup log.
# ---------------------------------------------------------------------------


async def test_reseed_mid_flight_engine_failure_drives_failed_and_cleanup(
    demo_reseed_client: httpx.AsyncClient,
    arq_ctx: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from backend.workers.demo_reseed import run_demo_reseed

    caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")

    original_put = httpx.AsyncClient.put
    call_count = {"engine_put": 0}
    fail_threshold = 6  # scenario-1's mapping + docs PUTs succeed; fail on scenario-2.

    async def counting_put(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> Any:
        url_str = str(url)
        if ":9200" in url_str or ":9201" in url_str:
            call_count["engine_put"] += 1
            if call_count["engine_put"] > fail_threshold:
                raise httpx.ConnectError(
                    "simulated ES unreachable", request=httpx.Request("PUT", url)
                )
        return await original_put(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "put", counting_put):
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
        await run_demo_reseed(arq_ctx)  # inner handler catches → cleanup → failed → returns
    await _clear_singleton_dedup_keys(arq_ctx["redis"])

    terminal = await _get_status(demo_reseed_client)
    assert terminal["status"] == "failed", terminal
    assert terminal["failed_reason"], terminal
    assert any(r.message == "demo_reseed_cleanup_truncated" for r in caplog.records), (
        f"no cleanup log; saw {[r.message for r in caplog.records][-15:]}"
    )


# ---------------------------------------------------------------------------
# AC-13: TRUNCATE commits before any api self-call (log ordering).
# ---------------------------------------------------------------------------


async def test_truncate_commits_before_first_self_call(
    demo_reseed_client: httpx.AsyncClient,
    arq_ctx: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")
    terminal = await post_and_run_to_terminal(demo_reseed_client, arq_ctx)
    assert terminal["status"] == "complete", terminal

    messages = [r.message for r in caplog.records]
    truncate_idx = next(
        (i for i, m in enumerate(messages) if m == "demo_reseed_truncate_committed"),
        None,
    )
    assert truncate_idx is not None, f"missing truncate log; saw {messages[:10]}"
    first_cluster_call_idx = next(
        (
            i
            for i, r in enumerate(caplog.records)
            if r.message == "demo_reseed_api_call_started"
            and r.__dict__.get("client") == "api"
            and "/api/v1/clusters" in str(r.__dict__.get("url", ""))
        ),
        None,
    )
    assert first_cluster_call_idx is not None, (
        "no demo_reseed_api_call_started log for POST /api/v1/clusters"
    )
    assert truncate_idx < first_cluster_call_idx, (
        f"TRUNCATE commit (idx={truncate_idx}) MUST precede first api self-call "
        f"(idx={first_cluster_call_idx})"
    )


# ---------------------------------------------------------------------------
# AC-14: natural failure cleanup is deterministic (wiped tables are 0).
# ---------------------------------------------------------------------------


async def test_natural_failure_cleanup_is_deterministic(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any, arq_ctx: dict[str, Any]
) -> None:
    from backend.workers.demo_reseed import run_demo_reseed

    original_put = httpx.AsyncClient.put
    call_count = {"engine_put": 0}
    fail_threshold = 6

    async def counting_put(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> Any:
        url_str = str(url)
        if ":9200" in url_str or ":9201" in url_str:
            call_count["engine_put"] += 1
            if call_count["engine_put"] > fail_threshold:
                raise httpx.ConnectError(
                    "simulated ES unreachable", request=httpx.Request("PUT", url)
                )
        return await original_put(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "put", counting_put):
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
        await run_demo_reseed(arq_ctx)
    await _clear_singleton_dedup_keys(arq_ctx["redis"])

    terminal = await _get_status(demo_reseed_client)
    assert terminal["status"] == "failed", terminal
    # run_demo_reseed_cleanup TRUNCATEs the demo tables under the held lock.
    assert await _table_count(db_engine, "clusters") == 0
    assert await _table_count(db_engine, "studies") == 0
    assert await _table_count(db_engine, "query_sets") == 0


# ---------------------------------------------------------------------------
# AC-15: dual-client contract — no role mixing.
# ---------------------------------------------------------------------------


async def test_dual_client_contract_no_role_mixing(
    demo_reseed_client: httpx.AsyncClient, arq_ctx: dict[str, Any]
) -> None:
    from backend.workers.demo_reseed import run_demo_reseed

    recorded: list[dict[str, Any]] = []
    original_send = httpx.AsyncClient.send

    async def recording_send(
        self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any
    ) -> Any:
        recorded.append({"method": request.method, "url": str(request.url)})
        return await original_send(self, request, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "send", recording_send):
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
        await run_demo_reseed(arq_ctx)
    await _clear_singleton_dedup_keys(arq_ctx["redis"])
    terminal = await _get_status(demo_reseed_client)
    assert terminal["status"] == "complete", terminal

    # Partition by port: api self-calls hit :8000; engine calls hit :9200/:9201.
    api_requests = [r for r in recorded if ":8000" in r["url"]]
    es_requests = [r for r in recorded if ":9200" in r["url"]]
    os_requests = [r for r in recorded if ":9201" in r["url"]]
    assert api_requests, "no api-client self-calls recorded"
    assert es_requests, "no engine ES requests recorded"
    assert os_requests, "no engine OS requests recorded"
    for r in api_requests:
        assert ":9200" not in r["url"] and ":9201" not in r["url"], (
            f"api request hit an engine port: {r}"
        )
    for r in es_requests + os_requests:
        assert ":8000" not in r["url"], f"engine request hit the api port: {r}"


# ---------------------------------------------------------------------------
# AC-16: advisory lock pinned to one Postgres connection (inline worker).
# ---------------------------------------------------------------------------


def _pg_locks_key_parts(key: int) -> tuple[int, int]:
    key_u64 = key & ((1 << 64) - 1)
    classid = (key_u64 >> 32) & 0xFFFFFFFF
    objid = key_u64 & 0xFFFFFFFF
    return classid, objid


async def test_advisory_lock_pinned_to_one_connection(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any, arq_ctx: dict[str, Any]
) -> None:
    from backend.workers.demo_reseed import run_demo_reseed

    classid, objid = _pg_locks_key_parts(DEMO_RESEED_LOCK_KEY)
    observed_pids: list[int] = []
    observer_done = asyncio.Event()

    async def _observer() -> None:
        while not observer_done.is_set():
            async with db_engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT pid FROM pg_locks "
                            "WHERE locktype = 'advisory' AND classid = :c AND objid = :o"
                        ),
                        {"c": classid, "o": objid},
                    )
                ).all()
            if rows:
                observed_pids.append(int(rows[0][0]))
            try:
                await asyncio.wait_for(observer_done.wait(), timeout=0.2)
            except TimeoutError:
                continue

    resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
    assert resp.status_code == 202, resp.text
    observer_task = asyncio.create_task(_observer())
    try:
        await run_demo_reseed(arq_ctx)  # holds the lock on get_engine().connect() in-process
    finally:
        observer_done.set()
        await observer_task
    await _clear_singleton_dedup_keys(arq_ctx["redis"])

    assert observed_pids, (
        "observer never saw the advisory lock — possibly the reseed finished "
        "too fast for the 200ms poll. Increase the workload if this flakes."
    )
    assert len(set(observed_pids)) == 1, (
        f"advisory lock changed pids mid-flight: {sorted(set(observed_pids))}"
    )
    async with db_engine.connect() as conn:
        post_rows = (
            await conn.execute(
                text(
                    "SELECT pid FROM pg_locks "
                    "WHERE locktype = 'advisory' AND classid = :c AND objid = :o"
                ),
                {"c": classid, "o": objid},
            )
        ).all()
    assert not post_rows, f"lock still held after the inline worker returned: {post_rows}"


# ---------------------------------------------------------------------------
# AC-12: cleanup-while-locked blocks a concurrent reseed (inline-task).
# ---------------------------------------------------------------------------


async def test_cleanup_while_locked_blocks_concurrent_reseed(
    demo_reseed_client: httpx.AsyncClient, arq_ctx: dict[str, Any]
) -> None:
    import backend.app.services.demo_seeding as svc_mod
    from backend.app.services import test_seeding
    from backend.workers.demo_reseed import run_demo_reseed

    gate = threading.Event()
    cleanup_entered = threading.Event()

    # The worker calls demo_seeding.run_demo_reseed_cleanup, which itself reads
    # the demo_seeding module gate at :492 — patch the gate on demo_seeding,
    # NOT _test. Wrap cleanup to learn when it's entered (before it blocks on
    # the gate's to_thread offload).
    original_cleanup = svc_mod.run_demo_reseed_cleanup

    async def gated_cleanup(*args: Any, **kwargs: Any) -> None:
        cleanup_entered.set()
        return await original_cleanup(*args, **kwargs)

    async def _fail_first_seed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("forced failure for AC-12")

    with (
        patch.object(test_seeding, "seed_study_completed_with_digest", _fail_first_seed),
        patch.object(svc_mod, "_demo_reseed_cleanup_test_gate", gate),
        patch.object(svc_mod, "run_demo_reseed_cleanup", gated_cleanup),
    ):
        # Also patch the worker's binding of run_demo_reseed_cleanup (imported
        # into the worker module namespace at load).
        with patch("backend.workers.demo_reseed.run_demo_reseed_cleanup", gated_cleanup):
            # POST A seeds `running`; launch the worker as a background task so
            # it holds the lock + blocks in cleanup on the gate.
            resp_a = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
            assert resp_a.status_code == 202, resp_a.text
            task_a = asyncio.create_task(run_demo_reseed(arq_ctx))

            for _ in range(200):  # up to 20s; gate's to_thread offload frees the loop
                if cleanup_entered.is_set():
                    break
                await asyncio.sleep(0.1)
            assert cleanup_entered.is_set(), "worker A never entered cleanup within 20s"

            # POST B while A holds the lock + a `running` status → 409.
            resp_b = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
            assert resp_b.status_code == 409, resp_b.text
            assert resp_b.json()["detail"]["error_code"] == "SEED_IN_PROGRESS"

            gate.set()
            await task_a

    terminal_a = await _get_status(demo_reseed_client)
    assert terminal_a["status"] == "failed", terminal_a

    # Third reseed (outside the patches) reaches complete.
    await _clear_singleton_dedup_keys(arq_ctx["redis"])
    await _clear_status_key(arq_ctx["redis"])
    terminal_c = await post_and_run_to_terminal(demo_reseed_client, arq_ctx)
    assert terminal_c["status"] == "complete", terminal_c


# ---------------------------------------------------------------------------
# AC-Async: polling transition running → complete, monotonic scenarios_completed.
# ---------------------------------------------------------------------------


async def test_polling_transition_running_to_complete_monotonic(
    demo_reseed_client: httpx.AsyncClient, arq_ctx: dict[str, Any]
) -> None:
    import backend.workers.demo_reseed as worker_mod
    from backend.app.services.demo_seeding import status_set as real_status_set

    recorded: list[dict[str, Any]] = []

    async def spy_status_set(redis: Any, status: ReseedStatusResponse) -> None:
        recorded.append(
            {"status": status.status, "scenarios_completed": status.scenarios_completed}
        )
        await real_status_set(redis, status)

    # The worker's _redis_status_cb calls the demo_reseed module binding of
    # status_set — patch THAT to capture every per-phase write (the single
    # Redis key is overwritten, so start/end reads cannot prove monotonicity).
    with patch.object(worker_mod, "status_set", spy_status_set):
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
        await worker_mod.run_demo_reseed(arq_ctx)
    await _clear_singleton_dedup_keys(arq_ctx["redis"])

    assert recorded, "no status writes captured"
    assert recorded[0]["status"] == "running"
    assert recorded[0]["scenarios_completed"] == 0
    completes = [r["scenarios_completed"] for r in recorded]
    assert all(b >= a for a, b in zip(completes, completes[1:], strict=False)), (
        f"scenarios_completed not monotonic: {completes}"
    )
    assert recorded[-1]["status"] == "complete", recorded[-1]
    terminal = await _get_status(demo_reseed_client)
    assert terminal["status"] == "complete"
    assert terminal["summary"] is not None
    assert terminal["scenarios_completed"] == terminal["scenarios_total"]


# ---------------------------------------------------------------------------
# AC-Reg: worker registration + enqueue guard.
# ---------------------------------------------------------------------------


async def test_worker_registration_and_enqueue_guard(
    demo_reseed_client: httpx.AsyncClient,
) -> None:
    from backend.app.main import app
    from backend.workers.all import WorkerSettings

    names = {getattr(f, "coroutine", f).__name__ for f in WorkerSettings.functions}
    assert "run_demo_reseed" in names, f"run_demo_reseed not registered; saw {sorted(names)}"

    calls: list[dict[str, Any]] = []
    pool = app.state.arq_pool
    real_enqueue = pool.enqueue_job

    async def spy_enqueue(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, "kwargs": kwargs})
        return await real_enqueue(*args, **kwargs)

    with patch.object(pool, "enqueue_job", spy_enqueue):
        resp = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
    assert len(calls) == 1, calls
    assert calls[0]["args"][0] == "run_demo_reseed", calls[0]
    assert calls[0]["kwargs"].get("_job_id") == "demo_reseed:singleton", calls[0]

    # This test enqueued a real (unconsumed) job — clear the dedup + status keys.
    from backend.app.core.settings import get_settings

    redis: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await _clear_singleton_dedup_keys(redis)
        await _clear_status_key(redis)
    finally:
        await redis.aclose()
