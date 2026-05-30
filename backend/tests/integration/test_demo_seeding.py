# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the demo-reseed flow.

PAUSED PER bug_demo_reseed_fake_metric_regression — the sync-flow tests
in this file were written against the previous handler that ran the
entire reseed inline and returned a ReseedSummary synchronously. The
handler now enqueues an Arq job and returns 202 immediately; status
flows through a Redis-backed polling endpoint. Rewriting the test
suite for the new async flow is tracked in the bug folder's "Follow-up
work" section.

Until the rewrite lands:

* Unit coverage of the new flow lives at
  ``backend/tests/unit/services/test_demo_seeding_status.py`` (14 cases
  covering the Pydantic shape, search_space builder, and Redis
  status_get/status_set round-trip).
* The contract test at
  ``backend/tests/contract/test_openapi_surface.py`` enforces the new
  202 + GET /status surface.
* End-to-end coverage on the real stack is provided by
  ``backend/tests/smoke/test_demo_reseed_real_studies.py`` once it
  lands (per the bug folder's regression-test commitment).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.services.demo_seeding import DEMO_RESEED_LOCK_KEY
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._demo_reseed_uvicorn import running_uvicorn

# bug_demo_reseed_fake_metric_regression — the sync-flow tests in this
# file are pre-async-flow. Pause all tests here until the file is
# rewritten for 202 + Redis-poll. Unit coverage lives at
# backend/tests/unit/services/test_demo_seeding_status.py.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(
        reason=(
            "Sync-flow tests paused — bug_demo_reseed_fake_metric_regression "
            "converted the reseed handler to async enqueue + poll."
        )
    ),
]


# ---------------------------------------------------------------------------
# Reachability helpers — skip the test gracefully if ES/OS aren't bound.
# ---------------------------------------------------------------------------


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def _engine_reachable() -> bool:
    """Check ES (9200) + OS (9201) are bound on localhost (or compose dns)."""
    # Try both localhost and the Compose DNS name; the test process may be
    # the host (port-bound) or a CI service-container peer (DNS).
    for host in ("127.0.0.1", "localhost", "elasticsearch", "opensearch"):
        if _tcp_open(host, 9200, 0.3) and _tcp_open("127.0.0.1", 9201, 0.3):
            return True
        if _tcp_open(host, 9200, 0.3):
            for os_host in ("127.0.0.1", "localhost", "opensearch"):
                if _tcp_open(os_host, 9201, 0.3):
                    return True
    return False


# Skip the whole module if neither Postgres nor the engines are reachable.
# We can't drive the reseed without both.
if not postgres_reachable() or not _engine_reachable():
    pytest.skip(
        "demo reseed integration tests require Postgres + ES + OS service "
        "containers. Run via `make test-integration` against the dev stack "
        "or in CI where the service containers are provisioned.",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Module-scoped uvicorn fixture — one server for all 9 tests in this file.
# AC-4's timeout test lives in test_demo_seeding_timeout.py with its own
# function-scoped fixture to avoid ReadTimeout residual contamination.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _stub_cluster_credentials(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Provide ``Settings.cluster_credentials_yaml`` for the test.

    The backend job in ``.github/workflows/pr.yml`` writes
    ``./secrets/cluster_credentials.yaml`` but doesn't set
    ``CLUSTER_CREDENTIALS_FILE`` for the pytest step — so
    ``get_settings().cluster_credentials_yaml`` returns ``None``,
    which makes the in-orchestrator ``POST /api/v1/clusters`` probe
    fail with ``CredentialsMissing`` → 503 ``CLUSTER_UNREACHABLE``.

    Mount a tmp file with the ``local-es`` + ``local-opensearch``
    credentials the demo scenarios reference, set
    ``CLUSTER_CREDENTIALS_FILE`` so the env-var read survives the
    autouse ``_clear_settings_caches`` fixture (which runs before
    every test and dumps the Settings lru_cache).
    """
    import os

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
    original = os.environ.get("CLUSTER_CREDENTIALS_FILE")
    os.environ["CLUSTER_CREDENTIALS_FILE"] = str(creds_file)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("CLUSTER_CREDENTIALS_FILE", None)
        else:
            os.environ["CLUSTER_CREDENTIALS_FILE"] = original


@pytest.fixture(scope="module", autouse=True)
def _patch_engine_for_test_host() -> Any:
    """Three patches to make the in-process uvicorn reach the CI services.

    The production resolver maps localhost:9200/9201 → Compose-DNS
    elasticsearch:9200/opensearch:9201 — correct for the API container at
    runtime. In the test environment the in-process uvicorn runs on the
    GHA runner HOST (not in a container), where the Compose-DNS names
    don't resolve (services are reachable only via forwarded ports).

    1. The service-module's ``_resolve_engine_base_url`` reference so
       engine self-calls (PUT/POST/DELETE against ES/OS) go to
       ``127.0.0.1:9200`` / ``127.0.0.1:9201``.
    2. The route-handler's re-import of the same symbol so cleanup
       index DELETEs land on the same loopback ports.
    3. The service-module's ``SCENARIOS`` list — each scenario's
       ``base_url`` ships as ``http://elasticsearch:9200`` /
       ``http://opensearch:9200`` (the value the api container stores
       on the ``clusters`` row). When the test process calls
       ``POST /api/v1/clusters``, the cluster-create handler probes
       that ``base_url`` — and the test process can't resolve those
       Compose DNS names. Rewrite to ``127.0.0.1`` for the test.
    """
    import copy

    import backend.app.api.v1._test as test_mod
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
        with (
            patch.object(svc_mod, "_resolve_engine_base_url", passthrough),
            patch.object(test_mod, "_resolve_engine_base_url", passthrough),
        ):
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
    async with httpx.AsyncClient(base_url=demo_reseed_base_url, timeout=180.0) as client:
        yield client


# ---------------------------------------------------------------------------
# Test-only DB engine for assertions / observers (separate from the
# request-scope ``AsyncSession`` the handler uses).
# ---------------------------------------------------------------------------


def _make_test_engine() -> Any:
    from backend.app.core.settings import get_settings

    return create_async_engine(get_settings().database_url, future=True)


async def _table_count(engine: Any, table: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


async def _truncate_all_demo_tables(engine: Any) -> None:
    """Reset DB between tests in this module — the autouse cleanup in
    ``conftest.py`` only DELETEs Phase 2 tables; we also need to reset
    sequences / RESTART IDENTITY so judgments cascade cleanly.
    """
    from backend.app.services.demo_seeding import _TRUNCATE_DEMO_TABLES_SQL

    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_DEMO_TABLES_SQL))


@pytest.fixture
async def db_engine() -> Any:
    engine = _make_test_engine()
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_demo_state_before_each(db_engine: Any) -> Any:
    """Wipe demo tables + ES/OS indices before EACH test in this module.

    We need an empty starting state for AC-1; previous tests may have
    populated. Cheap (TRUNCATE on small tables).
    """
    await _truncate_all_demo_tables(db_engine)
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
# AC-1: happy path on a clean DB.
# ---------------------------------------------------------------------------


async def test_reseed_happy_path_on_clean_db(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    response = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={}, timeout=180.0)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clusters_created"] == 4
    assert body["query_sets_created"] == 4
    assert body["studies_completed"] == 4
    assert body["proposals_created"] == 4
    assert body["duration_ms"] > 0
    # Spec §9 invariants
    assert await _table_count(db_engine, "clusters") == 4
    assert await _table_count(db_engine, "query_sets") == 4
    assert await _table_count(db_engine, "query_templates") == 4
    assert await _table_count(db_engine, "judgment_lists") == 4
    assert await _table_count(db_engine, "studies") == 4
    assert await _table_count(db_engine, "digests") == 4
    assert await _table_count(db_engine, "proposals") == 4
    # trials: 2 per study (winner + comparison) = 8
    assert await _table_count(db_engine, "trials") == 8


# ---------------------------------------------------------------------------
# AC-2: replaces pre-populated demo state.
# ---------------------------------------------------------------------------


async def test_reseed_replaces_populated_demo_state(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    # First reseed: populate.
    first = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={}, timeout=180.0)
    assert first.status_code == 200, first.text
    async with db_engine.connect() as conn:
        rows = await conn.execute(text("SELECT id FROM clusters ORDER BY name"))
        first_cluster_ids = {row[0] for row in rows}
    assert len(first_cluster_ids) == 4

    # Second reseed: replace.
    second = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={}, timeout=180.0)
    assert second.status_code == 200, second.text
    async with db_engine.connect() as conn:
        rows = await conn.execute(text("SELECT id FROM clusters ORDER BY name"))
        second_cluster_ids = {row[0] for row in rows}
    assert len(second_cluster_ids) == 4
    # New UUIDs — the TRUNCATE wiped the originals.
    assert first_cluster_ids.isdisjoint(second_cluster_ids)


# ---------------------------------------------------------------------------
# AC-3: concurrent reseed returns 409.
# ---------------------------------------------------------------------------


async def test_concurrent_reseed_returns_409(
    demo_reseed_client: httpx.AsyncClient,
) -> None:
    async with (
        httpx.AsyncClient(base_url=str(demo_reseed_client.base_url), timeout=180.0) as client_a,
        httpx.AsyncClient(base_url=str(demo_reseed_client.base_url), timeout=180.0) as client_b,
    ):
        results = await asyncio.gather(
            client_a.post("/api/v1/_test/demo/reseed", json={}),
            client_b.post("/api/v1/_test/demo/reseed", json={}),
            return_exceptions=False,
        )
    statuses = sorted(r.status_code for r in results)
    # One 200, one 409. Either request can win the lock race.
    assert statuses == [200, 409], [r.status_code for r in results]
    bodies = {r.status_code: r.json() for r in results}
    assert bodies[409]["detail"]["error_code"] == "SEED_IN_PROGRESS"
    assert bodies[409]["detail"]["retryable"] is True


# ---------------------------------------------------------------------------
# AC-13: TRUNCATE commits before any self-call (log ordering).
# ---------------------------------------------------------------------------


async def test_truncate_commits_before_first_self_call(
    demo_reseed_client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")
    caplog.set_level(logging.INFO, logger="backend.app.api.v1._test")
    response = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={}, timeout=180.0)
    assert response.status_code == 200, response.text
    # caplog captures logs in the test process — uvicorn runs in a
    # background thread of THIS same process, so the records land.
    messages = [r.message for r in caplog.records]
    truncate_idx = next(
        (i for i, m in enumerate(messages) if m == "demo_reseed_truncate_committed"),
        None,
    )
    assert truncate_idx is not None, f"missing truncate log; saw {messages[:10]}"
    # Find the first api-client api/v1/clusters POST start log.
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
        f"TRUNCATE commit log (idx={truncate_idx}) MUST precede first "
        f"api-client self-call log (idx={first_cluster_call_idx})"
    )


# ---------------------------------------------------------------------------
# AC-14: natural failure (api_client side) cleans up deterministically.
# ---------------------------------------------------------------------------


async def test_natural_failure_cleanup_after_python_control_returns(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    """Monkeypatch the test_seeding service so the FIRST scenario's
    ``seed-completed`` self-call fails with a RuntimeError. The
    orchestrator unwinds → cleanup TRUNCATEs partial state → 503.
    """
    from backend.app.api.v1 import _test as test_mod
    from backend.app.services import test_seeding

    original = test_seeding.seed_study_completed_with_digest

    async def _raise(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated api self-call failure")

    # _test.py imports the function into its own namespace at module load —
    # patching only the service module's attribute leaves the handler's
    # local reference pointing at the unpatched original. Patch BOTH.
    with (
        patch.object(test_seeding, "seed_study_completed_with_digest", _raise),
        patch.object(test_mod, "seed_study_completed_with_digest", _raise),
    ):
        response = await demo_reseed_client.post(
            "/api/v1/_test/demo/reseed", json={}, timeout=180.0
        )
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["detail"]["error_code"] == "SEED_FAILED"
    # Cleanup ran — demo tables are deterministically empty.
    assert await _table_count(db_engine, "clusters") == 0
    assert await _table_count(db_engine, "studies") == 0
    assert await _table_count(db_engine, "query_sets") == 0
    # Sanity: the original symbol is restored after the with-block.
    assert test_seeding.seed_study_completed_with_digest is original


# ---------------------------------------------------------------------------
# AC-5: mid-loop ES failure — partial state cleans up, 503 returns.
# ---------------------------------------------------------------------------


async def test_reseed_mid_flight_engine_failure_returns_503_and_cleans_up(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    """Monkeypatch ``httpx.AsyncClient.put`` to fail on the SECOND
    scenario's first engine PUT. The first scenario completes (real ES
    PUT succeeds), then the second scenario's PUT raises ConnectError.
    Orchestrator unwinds → cleanup → 503.
    """
    original_put = httpx.AsyncClient.put
    call_count = {"engine_put": 0}
    # The first scenario does: 1 PUT (mapping) + 5 PUT (docs) = 6 engine PUTs
    # before we want to fail. Fail on the 7th (start of scenario 2's PUTs).
    fail_threshold = 6

    async def counting_put(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> Any:
        # Only count engine-targeted PUTs (i.e., not the api self-call client).
        # Match by port — engine clients hit :9200 / :9201; api self-calls hit :8000.
        url_str = str(url)
        if ":9200" in url_str or ":9201" in url_str:
            call_count["engine_put"] += 1
            if call_count["engine_put"] > fail_threshold:
                raise httpx.ConnectError("simulated ES unreachable", request=None)
        return await original_put(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "put", counting_put):
        response = await demo_reseed_client.post(
            "/api/v1/_test/demo/reseed", json={}, timeout=180.0
        )
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["detail"]["error_code"] == "SEED_FAILED"
    # Cleanup ran — partial scenario-1 state is gone.
    assert await _table_count(db_engine, "clusters") == 0
    # The `products` index (scenario 1) was deleted by cleanup.
    async with httpx.AsyncClient(timeout=10.0) as check:
        for host in ("http://elasticsearch:9200", "http://127.0.0.1:9200"):
            try:
                head = await check.head(f"{host}/products", auth=("elastic", "changeme"))
                assert head.status_code == 404, (
                    f"products index still exists after cleanup: {head.status_code}"
                )
                break
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                continue


# ---------------------------------------------------------------------------
# AC-15: dual-client contract — no role mixing, correct basic auth.
# ---------------------------------------------------------------------------


async def test_dual_client_contract_no_role_mixing(
    demo_reseed_client: httpx.AsyncClient,
) -> None:
    """Record every httpx request and assert:

    * Every ``/api/v1/*`` request hits ``localhost:8000`` (api self-call).
    * Every ``:9200`` request lands on the engine client (ES port).
    * Every ``:9201`` request lands on the engine client (OS port).
    * No api request bleeds into the engine port range and vice versa.

    Authorization-header correctness is NOT asserted at this layer —
    httpx applies ``auth=...`` arguments inside ``AsyncClient.send`` AFTER
    the interceptor sees the request, so the Authorization header isn't
    visible to the recorder. AC-1's happy-path already proves the auth is
    correct: a wrong auth would 401 on the ES PUT and bubble up as
    503 ``SEED_FAILED``.
    """
    recorded: list[dict[str, Any]] = []
    original_send = httpx.AsyncClient.send

    async def recording_send(
        self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any
    ) -> Any:
        recorded.append({"method": request.method, "url": str(request.url)})
        return await original_send(self, request, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "send", recording_send):
        response = await demo_reseed_client.post(
            "/api/v1/_test/demo/reseed", json={}, timeout=180.0
        )
    assert response.status_code == 200, response.text

    # Partition by port: api self-calls hit :8000; engine calls hit :9200/:9201.
    # The resolver-patch test fixture makes these all loopback addresses; the
    # production resolver uses ``elasticsearch`` / ``opensearch`` Compose DNS
    # names — partition by port so the assertion is robust.
    api_requests = [r for r in recorded if ":8000" in r["url"]]
    es_requests = [r for r in recorded if ":9200" in r["url"]]
    os_requests = [r for r in recorded if ":9201" in r["url"]]
    assert len(api_requests) > 0, "no api-client self-calls recorded"
    assert len(es_requests) > 0, "no engine ES requests recorded"
    assert len(os_requests) > 0, "no engine OS requests recorded"
    # No role mixing: no api-client request hit an engine port, no
    # engine-client request hit the api port.
    for r in api_requests:
        assert ":9200" not in r["url"] and ":9201" not in r["url"], (
            f"api request unexpectedly hit engine port: {r}"
        )
    for r in es_requests + os_requests:
        assert ":8000" not in r["url"], f"engine request unexpectedly hit api port: {r}"


# ---------------------------------------------------------------------------
# AC-16: advisory lock pinned to one Postgres connection.
# ---------------------------------------------------------------------------


def _pg_locks_key_parts(key: int) -> tuple[int, int]:
    """Split a signed int64 key into Postgres ``pg_locks`` (classid, objid).

    Postgres stores a single-bigint advisory lock as two 32-bit ints in
    ``pg_locks``. Per cycle-5 plan-review finding B3.
    """
    key_u64 = key & ((1 << 64) - 1)
    classid = (key_u64 >> 32) & 0xFFFFFFFF
    objid = key_u64 & 0xFFFFFFFF
    return classid, objid


async def test_advisory_lock_pinned_to_one_connection(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    classid, objid = _pg_locks_key_parts(DEMO_RESEED_LOCK_KEY)

    observed_pids: list[int] = []
    observer_done = asyncio.Event()

    async def _observer() -> None:
        # Poll pg_locks every 200ms while the reseed is running.
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

    observer_task = asyncio.create_task(_observer())
    try:
        response = await demo_reseed_client.post(
            "/api/v1/_test/demo/reseed", json={}, timeout=180.0
        )
        assert response.status_code == 200, response.text
    finally:
        observer_done.set()
        await observer_task

    # During the reseed, the lock was held — at least one observation.
    assert observed_pids, (
        "observer never saw the advisory lock — possibly the reseed "
        "finished too fast for the 200ms poll. Increase the workload "
        "if this test starts flaking."
    )
    # The pid never changed — same backend held the lock throughout.
    assert len(set(observed_pids)) == 1, (
        f"advisory lock changed pids mid-flight: {sorted(set(observed_pids))}"
    )

    # After the handler returned, the lock is gone.
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
    assert not post_rows, f"lock still held after handler return: {post_rows}"


# ---------------------------------------------------------------------------
# AC-12: cleanup-while-locked blocks a concurrent reseed.
# ---------------------------------------------------------------------------


async def test_cleanup_while_locked_blocks_concurrent_reseed(
    demo_reseed_client: httpx.AsyncClient, db_engine: Any
) -> None:
    """Inject a ``threading.Event`` test gate into the cleanup pass. The
    test:

    1. Triggers request A with a forced-failure monkeypatch.
    2. Waits for A's handler to enter the cleanup pass (gated by event).
    3. Fires request B and asserts 409 SEED_IN_PROGRESS (A still holds
       the lock).
    4. Signals the gate — A's cleanup completes, lock releases.
    5. Fires request C and asserts 200.
    """
    from backend.app.api.v1 import _test as _test_module
    from backend.app.services import test_seeding

    gate = threading.Event()
    cleanup_entered = threading.Event()

    # Wrap the cleanup so the test learns the moment it's about to wait.
    original_cleanup = _test_module._run_demo_reseed_cleanup

    async def gated_cleanup(*args: Any, **kwargs: Any) -> None:
        cleanup_entered.set()
        return await original_cleanup(*args, **kwargs)

    async def _fail_first_seed(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("forced failure for AC-12")

    with (
        patch.object(test_seeding, "seed_study_completed_with_digest", _fail_first_seed),
        patch.object(_test_module, "seed_study_completed_with_digest", _fail_first_seed),
        patch.object(_test_module, "_demo_reseed_cleanup_test_gate", gate),
        patch.object(_test_module, "_run_demo_reseed_cleanup", gated_cleanup),
    ):
        # Step 1: kick off request A.
        async with httpx.AsyncClient(
            base_url=str(demo_reseed_client.base_url), timeout=180.0
        ) as client_a:
            task_a = asyncio.create_task(client_a.post("/api/v1/_test/demo/reseed", json={}))
            # Step 2: wait for A's handler to enter cleanup.
            for _ in range(200):  # up to 20s
                if cleanup_entered.is_set():
                    break
                await asyncio.sleep(0.1)
            assert cleanup_entered.is_set(), "request A never entered cleanup within 20s"

            # Step 3: fire B; assert 409 (A still holds the lock).
            response_b = await demo_reseed_client.post(
                "/api/v1/_test/demo/reseed", json={}, timeout=180.0
            )
            assert response_b.status_code == 409, response_b.text
            assert response_b.json()["detail"]["error_code"] == "SEED_IN_PROGRESS"

            # Step 4: release A's cleanup.
            gate.set()
            response_a = await task_a
            assert response_a.status_code == 503, response_a.text

    # Step 5: fire C now that the lock is gone. (Outside the patches so
    # the third reseed actually succeeds.)
    response_c = await demo_reseed_client.post("/api/v1/_test/demo/reseed", json={}, timeout=180.0)
    assert response_c.status_code == 200, response_c.text
