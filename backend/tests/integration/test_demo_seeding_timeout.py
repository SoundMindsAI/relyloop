# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-4 isolated test: a worker-side per-call HTTP timeout drives terminal
``failed`` + cleanup.

After ``bug_demo_reseed_fake_metric_regression`` made the reseed async, the
per-call timeout no longer surfaces on the POST (which returns 202 before any
self-call runs) — it lives in the worker. When a single self-call inside
``run_demo_reseed`` exceeds ``demo_reseed_per_call_http_timeout_s``, the
``httpx.ReadTimeout`` propagates, the worker's inner handler runs
``run_demo_reseed_cleanup`` under the held advisory lock, writes terminal
``failed`` to Redis, and returns. ``GET /status`` then reports ``failed`` with
a timeout-flavored ``failed_reason``.

Function-scoped uvicorn so the ReadTimeout residual can't pollute siblings.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from redis.asyncio import Redis

from backend.app.services.demo_seeding import DEMO_RESEED_STATUS_KEY
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._demo_reseed_uvicorn import (
    engines_reachable,
    fresh_db_engine_cache,
    patched_engine_hosts,
    running_study_worker,
    running_uvicorn,
)

# See test_demo_seeding.py — excluded from the per-PR heavy lane, run by the
# demo-reseed-nightly workflow.
pytestmark = [pytest.mark.integration, pytest.mark.demo_reseed_full]

_SINGLETON_DEDUP_KEYS: tuple[str, ...] = (
    "arq:job:demo_reseed:singleton",
    "arq:result:demo_reseed:singleton",
    "arq:in-progress:demo_reseed:singleton",
)


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def _redis_reachable() -> bool:
    from urllib.parse import urlparse

    from backend.app.core.settings import get_settings

    try:
        parsed = urlparse(get_settings().redis_url)
    except Exception:  # noqa: BLE001
        return False
    port = parsed.port or 6379
    return _tcp_open(parsed.hostname or "127.0.0.1", port, 0.3) or _tcp_open("127.0.0.1", port, 0.3)


if not postgres_reachable() or not engines_reachable() or not _redis_reachable():
    pytest.skip(
        "demo reseed timeout test requires Postgres + ES + OS + Redis service containers.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def _stub_cluster_credentials(tmp_path: Any) -> Any:
    """Mount cluster_credentials.yaml + redirect the worker's API base URL to
    the in-process uvicorn (mirrors test_demo_seeding.py)."""
    import os

    creds_file = tmp_path / "cluster_credentials.yaml"
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


@pytest.fixture(autouse=True)
def _patch_engine_for_test_host() -> Any:
    """No-op in-container; loopback rewrite on the host / CI (see
    :func:`patched_engine_hosts`)."""
    with patched_engine_hosts():
        yield


@pytest.fixture(autouse=True)
def _fast_study_trials() -> Any:
    """Shrink the per-study trial budget for speed — the timeout test forces a
    failure before studies complete, but keep parity with test_demo_seeding."""
    import backend.app.services.demo_seeding as svc_mod

    with patch.object(svc_mod, "_REAL_STUDY_MAX_TRIALS", 3):
        yield


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test() -> AsyncIterator[None]:
    """Reset the async-engine caches around each test (see
    :func:`fresh_db_engine_cache`)."""
    async with fresh_db_engine_cache():
        yield


@pytest_asyncio.fixture(autouse=True)
async def _study_worker(_fresh_engine_per_test: None) -> AsyncIterator[None]:
    """In-loop Arq worker draining the study/judgment job graph (see
    :func:`running_study_worker`)."""
    async with running_study_worker():
        yield


@pytest_asyncio.fixture
async def demo_reseed_client_function_scoped(
    _fresh_engine_per_test: None,
) -> AsyncIterator[httpx.AsyncClient]:
    # In-loop uvicorn shares this test's event loop with the inline worker so
    # the shared asyncpg pool stays sound.
    async with running_uvicorn() as base_url:
        async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
            yield client


@pytest_asyncio.fixture
async def arq_ctx() -> AsyncIterator[dict[str, Any]]:
    from backend.app.core.settings import get_settings

    redis: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    try:
        await redis.ping()
    except Exception as exc:  # noqa: BLE001
        await redis.aclose()
        pytest.skip(f"Redis not reachable for arq_ctx: {exc}")
    # Clear any leaked status/dedup keys so the POST doesn't 409 and the
    # enqueue isn't deduped.
    await redis.delete(DEMO_RESEED_STATUS_KEY, *_SINGLETON_DEDUP_KEYS)
    try:
        yield {"redis": redis}
    finally:
        await redis.delete(DEMO_RESEED_STATUS_KEY, *_SINGLETON_DEDUP_KEYS)
        await redis.aclose()


async def test_worker_per_call_timeout_drives_failed_and_cleanup(
    demo_reseed_client_function_scoped: httpx.AsyncClient,
    arq_ctx: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A worker self-call exceeding the per-call timeout → terminal ``failed`` +
    cleanup, WITHOUT weakening the production ``ge=30`` validator.

    The async refactor retired the ``seed_study_completed_with_digest`` shortcut
    the legacy test slowed down, and the reseed's per-scenario studies now run
    through the real worker (which would need cluster credentials we don't want
    to thread in here). Instead, drive the timeout structurally: pin the
    per-call HTTP timeout to a value so small that the worker's VERY FIRST
    self-call (``POST /api/v1/clusters``) exceeds it. That hits the same inner
    handler — httpx ``*Timeout`` → cleanup-under-lock → terminal ``failed`` —
    before any study/UBI work runs, so the contract is exercised without a real
    study. The timeout is set via ``settings.__dict__`` on the lru_cached
    instance (bypasses ``ge=30`` without changing the field), restored in
    ``finally``.
    """
    from backend.app.core.settings import get_settings
    from backend.workers.demo_reseed import run_demo_reseed

    caplog.set_level(logging.INFO, logger="backend.app.services.demo_seeding")

    settings = get_settings()
    original_timeout = settings.__dict__.get("demo_reseed_per_call_http_timeout_s")
    settings.__dict__["demo_reseed_per_call_http_timeout_s"] = 0.001
    try:
        resp = await demo_reseed_client_function_scoped.post("/api/v1/_test/demo/reseed", json={})
        assert resp.status_code == 202, resp.text
        # Inner handler catches the httpx timeout → cleanup → failed → returns.
        await run_demo_reseed(arq_ctx)
    finally:
        if original_timeout is None:
            settings.__dict__.pop("demo_reseed_per_call_http_timeout_s", None)
        else:
            settings.__dict__["demo_reseed_per_call_http_timeout_s"] = original_timeout

    status_resp = await demo_reseed_client_function_scoped.get("/api/v1/_test/demo/reseed/status")
    assert status_resp.status_code == 200, status_resp.text
    terminal = status_resp.json()
    assert terminal["status"] == "failed", terminal
    # failed_reason is f"{type(exc).__name__}: ..." — httpx timeout classes all
    # contain "Timeout" (ReadTimeout / ConnectTimeout / PoolTimeout).
    assert "Timeout" in (terminal["failed_reason"] or ""), terminal
    assert any(r.message == "demo_reseed_cleanup_truncated" for r in caplog.records), (
        f"no cleanup log; saw {[r.message for r in caplog.records][-15:]}"
    )
