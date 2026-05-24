"""AC-4 isolated test: per-call timeout returns 503 SEED_FAILED.

Per plan §3.2 Task 4, AC-4 lives in its own file with a function-scoped
uvicorn fixture because the ``httpx.ReadTimeout`` residual may leave a
server-side handler completing AFTER the test's 503 has returned, and
shared uvicorn instances across other tests would risk contamination.

This file:

1. Boots a fresh uvicorn for THIS test only.
2. Forces ``seed_study_completed_with_digest`` to sleep 5s.
3. Bypasses the Pydantic validator's ``ge=30`` lower bound via
   ``model_construct`` to set the per-call timeout to 1s (per the plan's
   "DO NOT weaken the production validator" rule).
4. Asserts the response is 503 SEED_FAILED.
5. Asserts via caplog that the ``demo_reseed_cleanup_truncated`` log
   line is emitted — proving cleanup was attempted even though
   post-cleanup emptiness is NOT guaranteed (per the spec's
   ReadTimeout residual).
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from backend.tests.conftest import postgres_reachable
from backend.tests.integration._demo_reseed_uvicorn import running_uvicorn

pytestmark = pytest.mark.integration


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def _engine_reachable() -> bool:
    for host in ("127.0.0.1", "localhost", "elasticsearch"):
        if _tcp_open(host, 9200, 0.3):
            for os_host in ("127.0.0.1", "localhost", "opensearch"):
                if _tcp_open(os_host, 9201, 0.3):
                    return True
    return False


if not postgres_reachable() or not _engine_reachable():
    pytest.skip(
        "demo reseed timeout test requires Postgres + ES + OS service containers.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def _stub_cluster_credentials(tmp_path: Any) -> Any:
    """Mount cluster_credentials.yaml so the cluster-create probe inside
    the orchestrator can resolve ``local-es`` / ``local-opensearch``.
    See the sibling fixture in ``test_demo_seeding.py`` for the
    detailed rationale (uses CLUSTER_CREDENTIALS_FILE env var to
    survive the autouse ``_clear_settings_caches`` reset).
    """
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
    original = os.environ.get("CLUSTER_CREDENTIALS_FILE")
    os.environ["CLUSTER_CREDENTIALS_FILE"] = str(creds_file)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("CLUSTER_CREDENTIALS_FILE", None)
        else:
            os.environ["CLUSTER_CREDENTIALS_FILE"] = original


@pytest.fixture(autouse=True)
def _patch_engine_for_test_host() -> Any:
    """Same patches as the sibling fixture in ``test_demo_seeding.py`` —
    resolver + SCENARIOS base_url so the test process can reach ES/OS
    + the cluster-create probe via 127.0.0.1 ports."""
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


# Function-scoped uvicorn — one fresh server per test in this file so the
# ReadTimeout residual cannot pollute later tests in the module.
@pytest_asyncio.fixture
async def demo_reseed_client_function_scoped() -> AsyncIterator[httpx.AsyncClient]:
    with running_uvicorn() as base_url:
        async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
            yield client


async def test_reseed_per_call_timeout_returns_503(
    demo_reseed_client_function_scoped: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-4 — single self-call exceeds the per-call timeout → 503 SEED_FAILED.

    Implementation:

    * Monkeypatch ``test_seeding.seed_study_completed_with_digest`` to
      ``asyncio.sleep(5)`` — guarantees the api-client self-call
      exceeds our 1s ceiling.
    * Patch the lru_cache'd ``Settings`` instance's
      ``demo_reseed_per_call_http_timeout_s`` to 1 — bypasses the
      ``ge=30`` validator without weakening the production rule.
    """
    from backend.app.core.settings import get_settings
    from backend.app.services import test_seeding

    caplog.set_level(logging.INFO, logger="backend.app.api.v1._test")

    async def _slow_seed(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(5)

    settings = get_settings()
    original_timeout = settings.__dict__.get("demo_reseed_per_call_http_timeout_s")
    settings.__dict__["demo_reseed_per_call_http_timeout_s"] = 1
    try:
        with patch.object(test_seeding, "seed_study_completed_with_digest", _slow_seed):
            response = await demo_reseed_client_function_scoped.post(
                "/api/v1/_test/demo/reseed", json={}, timeout=60.0
            )
    finally:
        if original_timeout is None:
            settings.__dict__.pop("demo_reseed_per_call_http_timeout_s", None)
        else:
            settings.__dict__["demo_reseed_per_call_http_timeout_s"] = original_timeout

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["detail"]["error_code"] == "SEED_FAILED"
    assert body["detail"]["retryable"] is True
    # Cycle-10 finding A1 — cleanup MUST have been attempted.
    cleanup_messages = [
        r.message for r in caplog.records if r.message == "demo_reseed_cleanup_truncated"
    ]
    assert cleanup_messages, (
        "expected demo_reseed_cleanup_truncated in caplog — cleanup pass "
        "was not entered after the timeout path"
    )
