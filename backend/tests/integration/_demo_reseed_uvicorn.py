# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""In-process uvicorn helpers for ``POST /api/v1/_test/demo/reseed`` tests.

The reseed worker's ``api_client`` self-calls the API base URL (FR-1c). The
default integration-test fixture uses ``ASGITransport(app=app)`` which has no
listening socket — the self-call would fail with ``ConnectError``. This helper
boots uvicorn on a real loopback port so both the test client AND the worker's
self-call hit the same in-process ``app`` object via the network stack.

Critical event-loop invariant
------------------------------

uvicorn runs as an :class:`asyncio.Task` **in the test's own event loop** — NOT
in a background thread. The reseed integration tests drive the worker *inline*
(``await run_demo_reseed(ctx)``), and both the worker and the uvicorn request
handlers touch the process-wide ``get_engine()`` async engine. asyncpg
connections are bound to the loop that created them: sharing one engine across
two loops (a thread's loop + the test's loop) corrupts the connection pool with
``cannot perform operation: another operation is in progress`` /
``Future ... attached to a different loop``, surfacing as a 500 on the worker's
``POST /api/v1/clusters`` self-call. Co-locating the server and the worker in a
single loop is what keeps the shared engine sound. See
:func:`backend.tests.integration._demo_reseed_uvicorn.fresh_db_engine_cache`
for the companion guard that stops the cached engine leaking across the
per-function loops pytest-asyncio creates.

Why same-process matters (per spec §5 + plan §3.2 topology decision):

* ``app.dependency_overrides[...]`` and ``monkeypatch.setattr(...)`` apply
  to BOTH the test-side request AND the handler's loopback self-call —
  because both hit the same Python process via uvicorn.
* ``caplog`` captures route-handler logs (AC-13 commit-ordering proof).
* A sibling ``engine.connect()`` from the same process can query
  ``pg_locks`` against the shared Postgres container (AC-16 pin observer).

The fixtures themselves live in each test file (both function-scoped, so the
server shares each test's event loop) — this module exposes the lifecycle
primitive :func:`running_uvicorn` plus the two harness guards
:func:`fresh_db_engine_cache` and :func:`patched_engine_hosts`.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import socket
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import patch

import uvicorn

# ``/.dockerenv`` exists iff this process runs inside a container. Mirrors
# ``scripts/seed_meaningful_demos.py``'s ``_INSIDE_CONTAINER`` so the engine
# host topology the tests assume matches the one the SCENARIOS constants were
# built against.
_INSIDE_CONTAINER = os.path.exists("/.dockerenv")

# Port 8000 is the canonical value the worker self-calls (the default
# ``Settings.relyloop_worker_api_base_url`` = ``http://api:8000``; the harness
# overrides it to ``http://127.0.0.1:8000``).
DEMO_RESEED_PORT = 8000


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def engines_reachable() -> bool:
    """ES + OS reachable in either topology.

    In a container on the Compose network they answer on the service-DNS
    ports (``elasticsearch:9200`` / ``opensearch:9200``); on the host / CI
    runner they answer on the host-published loopback ports
    (``127.0.0.1:9200`` / ``127.0.0.1:9201`` — OS uses :9201 on the host only
    to dodge the ES collision). Probe both so the guard matches wherever the
    suite runs.
    """
    es_ok = (
        _port_open("elasticsearch", 9200, 0.3)
        or _port_open("127.0.0.1", 9200, 0.3)
        or _port_open("localhost", 9200, 0.3)
    )
    os_ok = (
        _port_open("opensearch", 9200, 0.3)
        or _port_open("127.0.0.1", 9201, 0.3)
        or _port_open("localhost", 9201, 0.3)
    )
    return es_ok and os_ok


def _assert_port_free() -> None:
    """Fail loudly when 127.0.0.1:8000 is already bound.

    The worker self-calls ``127.0.0.1:8000``, so the harness MUST own that
    port. When running on the host, stop the API container with
    ``docker compose stop api`` first. Inside a container on the Compose
    network the container's own loopback is independent of the host's, so the
    running ``api`` service does not collide.
    """
    if _port_open("127.0.0.1", DEMO_RESEED_PORT):
        raise RuntimeError(
            f"127.0.0.1:{DEMO_RESEED_PORT} is occupied — stop the API "
            "container with `docker compose stop api` before running "
            "demo-reseed integration tests on the host."
        )


def _assert_localhost_resolves_to_ipv4() -> None:
    """Verify ``localhost:8000`` is reachable via IPv4 from the test process.

    Uvicorn binds ``127.0.0.1:8000`` for portability + a deterministic
    teardown (binding ``::`` introduces dual-stack address-family
    complications on macOS/BSD runners). On platforms where ``localhost``
    resolves to ``::1`` first, a ``http://localhost:8000`` self-call would fail
    with ``ConnectError``. Validate with a short-lived TCP probe via
    ``localhost`` — if it succeeds, a localhost self-call would work too.

    Per GPT-5.5 final-review Medium #3.
    """
    if not _port_open("localhost", DEMO_RESEED_PORT, timeout=2.0):
        raise RuntimeError(
            f"localhost:{DEMO_RESEED_PORT} did NOT accept a probe even "
            f"though uvicorn is bound at 127.0.0.1:{DEMO_RESEED_PORT}. "
            f"This indicates 'localhost' on this host resolves to ::1 "
            f"first and a `http://localhost:8000` self-call would fail with "
            f"ConnectError. Either bind dual-stack (host='::') OR force "
            f"'localhost' to resolve to 127.0.0.1 in /etc/hosts."
        )


async def _await_started(
    server: uvicorn.Server,
    serve_task: asyncio.Task[None],
    *,
    deadline: float = 10.0,
    step: float = 0.05,
) -> None:
    """Poll ``server.started`` until uvicorn finishes startup (or fail fast)."""
    waited = 0.0
    while not server.started:
        if serve_task.done():
            # Re-raise the startup exception if the serve task already died.
            serve_task.result()
            raise RuntimeError("uvicorn serve task exited before startup completed")
        await asyncio.sleep(step)
        waited += step
        if waited >= deadline:
            server.should_exit = True
            raise RuntimeError(
                f"uvicorn never started on 127.0.0.1:{server.config.port} within {deadline}s"
            )


@contextlib.asynccontextmanager
async def running_uvicorn() -> AsyncIterator[str]:
    """Start uvicorn in the CURRENT event loop, apply migrations, yield base URL.

    The server runs as an ``asyncio.Task`` in the caller's loop so the inline
    worker and the request handlers share one loop (and therefore one sound
    asyncpg pool). The task is stopped via uvicorn's graceful
    ``should_exit`` flow on teardown rather than thread-killing, which would
    leak sockets.
    """
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    _assert_port_free()

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=DEMO_RESEED_PORT,
        log_level="warning",
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    # We run inside the test's main-thread event loop; uvicorn's default signal
    # handlers would clobber pytest's. Disable them — teardown uses
    # ``should_exit`` instead.
    server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]

    serve_task: asyncio.Task[None] = asyncio.create_task(server.serve(), name="uvicorn-demo-reseed")
    try:
        await _await_started(server, serve_task)
        _assert_localhost_resolves_to_ipv4()
        yield f"http://127.0.0.1:{DEMO_RESEED_PORT}"
    finally:
        server.should_exit = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(serve_task), timeout=10.0)
        if not serve_task.done():
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await serve_task


@contextlib.asynccontextmanager
async def fresh_db_engine_cache() -> AsyncIterator[None]:
    """Clear (and on teardown dispose) the process-wide engine caches per test.

    pytest-asyncio runs each test in its own function-scoped event loop, but
    ``get_engine()`` / ``get_session_factory()`` are ``@lru_cache``d
    process-wide. Without resetting them, an async engine created in test A's
    loop is reused from test B's loop → asyncpg cross-loop corruption. Clearing
    BEFORE the test forces a fresh engine in the current loop; disposing AFTER
    (while this loop is still open) releases its pool cleanly.
    """
    from backend.app.db import session as session_mod

    # Drop any stale reference left by a prior loop without awaiting its
    # (dead-loop) connections — the previous test's teardown already disposed.
    session_mod.get_session_factory.cache_clear()
    session_mod.get_engine.cache_clear()
    try:
        yield
    finally:
        if session_mod.get_engine.cache_info().currsize:
            with contextlib.suppress(Exception):
                await session_mod.get_engine().dispose()
        session_mod.get_session_factory.cache_clear()
        session_mod.get_engine.cache_clear()


def _func_name(f: Any) -> str:
    """Name of an Arq worker entry (raw coroutine OR ``arq.func(...)`` wrapper)."""
    name = getattr(f, "name", None) or getattr(f, "__name__", "")
    return str(name)


@contextlib.asynccontextmanager
async def running_study_worker() -> AsyncIterator[None]:
    """Run an in-loop Arq worker that executes the study/judgment job graph.

    The reseed orchestrator creates real studies via ``POST /api/v1/studies``
    (which enqueues ``start_study`` → which enqueues ``run_trial`` /
    ``run_baseline_trial`` → ``generate_digest``) and ``ctr_threshold`` UBI
    scenarios via ``POST /api/v1/judgments/generate-from-ubi`` (enqueues
    ``generate_judgments_from_ubi``), then polls each to a terminal state. None
    of that completes without a worker draining the queue — neither the inline
    harness nor the pr.yml backend lane runs one, so without this the reseed
    hangs/fails on ``poll_study: status='queued'``.

    The worker runs as a task **in the test's event loop** (same loop as the
    inline ``run_demo_reseed`` + uvicorn) so the shared ``get_engine()`` async
    pool stays single-loop. It registers every production worker function EXCEPT
    ``run_demo_reseed``, which is replaced by an instant no-op stub: the POST
    enqueues ``demo_reseed:singleton`` and the test runs the REAL reseed inline,
    so the worker must consume-and-discard that queued job (cleanly, as a
    registered no-op — not an "unknown function" error) to avoid a second,
    racing reseed. The custom ``on_startup`` seeds ``optuna_storage`` +
    ``arq_pool`` but SKIPS the production resume-sweep (which would re-enqueue
    studies and interfere).
    """
    import asyncio as _asyncio

    from arq import func
    from arq.connections import ArqRedis, RedisSettings, create_pool
    from arq.worker import Worker

    from backend.app.core.settings import get_settings
    from backend.app.eval.optuna_runtime import build_storage
    from backend.workers.all import WorkerSettings

    settings = get_settings()

    async def _noop_demo_reseed(ctx: Any, *args: Any, **kwargs: Any) -> None:
        # The test drives the REAL reseed inline; this stub just drains the
        # enqueued demo_reseed:singleton job so no second reseed runs.
        return None

    async def _on_startup(ctx: dict[str, Any]) -> None:
        ctx["optuna_storage"] = await _asyncio.to_thread(build_storage, settings.database_url)
        ctx["arq_pool"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    async def _on_shutdown(ctx: dict[str, Any]) -> None:
        storage = ctx.get("optuna_storage")
        if storage is not None:
            engine = getattr(storage, "_engine", None) or getattr(storage, "engine", None)
            if engine is not None:
                with contextlib.suppress(Exception):
                    await _asyncio.to_thread(engine.dispose)
        pool: ArqRedis | None = ctx.get("arq_pool")
        if pool is not None:
            with contextlib.suppress(Exception):
                await pool.aclose()

    functions = [f for f in WorkerSettings.functions if _func_name(f) != "run_demo_reseed"]
    functions.append(func(_noop_demo_reseed, name="run_demo_reseed", max_tries=1))

    worker = Worker(
        functions=functions,
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
        handle_signals=False,
        poll_delay=0.1,
        retry_jobs=False,
        keep_result=5,
    )
    task: asyncio.Task[None] = asyncio.create_task(worker.async_run(), name="arq-study-worker")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        with contextlib.suppress(Exception):
            await worker.close()


@contextlib.contextmanager
def patched_engine_hosts() -> Iterator[None]:
    """Point the reseed at engines reachable from the current topology.

    * **Inside a container** (Compose network): the SCENARIOS constants are
      already Compose-DNS URLs (``elasticsearch:9200`` / ``opensearch:9200``)
      and directly reachable, so this is a no-op and the production
      ``_resolve_engine_base_url`` runs for real.
    * **On the host / CI runner** (engines published on loopback): rewrite each
      scenario's ``base_url`` and the engine-base resolver to ``127.0.0.1``
      (ES :9200, OS :9201 — the host-published ports).
    """
    import backend.app.services.demo_seeding as svc_mod

    if _INSIDE_CONTAINER:
        yield
        return

    def passthrough(host_base_url: str) -> str:
        loopback = {
            "http://localhost:9200": "http://127.0.0.1:9200",
            "http://localhost:9201": "http://127.0.0.1:9201",
        }
        try:
            return loopback[host_base_url]
        except KeyError as exc:
            raise ValueError(f"unexpected URL in test resolver: {host_base_url}") from exc

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
        # _resolve_engine_base_url lives only in demo_seeding now (the async
        # refactor moved cleanup out of the _test route handler).
        with patch.object(svc_mod, "_resolve_engine_base_url", passthrough):
            yield
    finally:
        svc_mod.SCENARIOS = original_scenarios


__all__ = [
    "DEMO_RESEED_PORT",
    "engines_reachable",
    "fresh_db_engine_cache",
    "patched_engine_hosts",
    "running_study_worker",
    "running_uvicorn",
]
