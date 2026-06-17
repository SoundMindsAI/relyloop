# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``GET /api/v1/_test/demo/engines``.

feat_selective_engine_startup_and_demo Story 2.1 / FR-7.

The endpoint probes Elasticsearch, OpenSearch, and Apache Solr concurrently
via ``is_engine_reachable`` and returns per-engine reachability. The
backend CI service-container topology runs ES and OpenSearch but NOT Solr
(Solr only runs in the optional smoke job per
[`infra_smoke_reseed_runtime_budget`](
docs/00_overview/implemented_features/2026_06_02_infra_smoke_reseed_runtime_budget/
)). So in this test environment we expect:
  - elasticsearch.reachable = True
  - opensearch.reachable    = True
  - solr.reachable          = False

The test patches ``is_engine_reachable`` to make the assertions
deterministic regardless of the local-vs-CI engine availability — the
real probe is exercised inside the engine reachability snapshot's own
existing tests; here we're guarding the endpoint's wiring (ordering,
shape, parallel dispatch, 200-on-all-down).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.integration

# Mirror the skip pattern from ``test_demo_seeding.py``: this test uses
# the ``async_client`` fixture which applies Alembic migrations against
# the test database. When Postgres isn't reachable (running from the host
# without a port-mapped service container) the test skips cleanly. CI's
# GHA service containers (and ``make test-worktree`` from inside a
# sibling container) provide the Postgres needed for the test to run.
if not postgres_reachable():
    pytest.skip(
        "demo engines capability tests require Postgres (for the async_client "
        "fixture's Alembic migration step). Run via CI service containers or "
        "from inside the Compose stack — `make test-worktree`.",
        allow_module_level=True,
    )


async def test_engines_endpoint_returns_three_rows_in_deterministic_order(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns 200 + three engines in (es, os, solr) order — every time."""
    from backend.app.api.v1 import _test as test_router

    async def fake_reachable(_url: str, _engine_type: str) -> bool:
        return True

    monkeypatch.setattr(test_router, "is_engine_reachable", fake_reachable)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body.keys()) == ["engines"]
    assert [row["engine_type"] for row in body["engines"]] == [
        "elasticsearch",
        "opensearch",
        "solr",
    ]
    for row in body["engines"]:
        assert isinstance(row["reachable"], bool)
        assert set(row.keys()) == {"engine_type", "reachable"}


async def test_engines_endpoint_reports_mixed_reachability(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES + OS reachable, Solr unreachable → faithful per-engine booleans."""
    from backend.app.api.v1 import _test as test_router

    async def fake_reachable(_url: str, engine_type: str) -> bool:
        return engine_type != "solr"

    monkeypatch.setattr(test_router, "is_engine_reachable", fake_reachable)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    rows = {row["engine_type"]: row["reachable"] for row in response.json()["engines"]}
    assert rows == {"elasticsearch": True, "opensearch": True, "solr": False}


async def test_engines_endpoint_returns_200_when_all_unreachable(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Endpoint must NOT error when no engine answers — reachability IS the payload."""
    from backend.app.api.v1 import _test as test_router

    async def fake_reachable(_url: str, _engine_type: str) -> bool:
        return False

    monkeypatch.setattr(test_router, "is_engine_reachable", fake_reachable)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    assert all(not row["reachable"] for row in response.json()["engines"])


async def test_engines_endpoint_probes_engines_in_parallel(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent dispatch — three 1s probes finish in ~1s, not ~3s.

    Guards against accidental sequential refactoring of the
    asyncio.gather call.
    """
    import asyncio
    import time

    from backend.app.api.v1 import _test as test_router

    async def slow_reachable(_url: str, _engine_type: str) -> bool:
        await asyncio.sleep(0.5)
        return True

    monkeypatch.setattr(test_router, "is_engine_reachable", slow_reachable)
    start = time.monotonic()
    response = await async_client.get("/api/v1/_test/demo/engines")
    elapsed = time.monotonic() - start
    assert response.status_code == 200
    # Sequential would be ~1.5s; parallel ~0.5s. Leave generous headroom
    # for CI-runner slowdowns; the assertion only fails on a meaningful
    # serialization regression.
    assert elapsed < 1.2, f"three 0.5s probes took {elapsed:.2f}s — concurrency regressed"


async def test_engines_endpoint_gated_by_development_env(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside ``environment=='development'`` the endpoint returns 404."""
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "staging")
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 404


async def test_engines_endpoint_response_keys_are_exhaustive(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new Pydantic models reject extra fields — ConfigDict(extra='forbid')."""
    from backend.app.api.v1 import _test as test_router

    async def fake_reachable(_url: str, _engine_type: str) -> bool:
        return True

    monkeypatch.setattr(test_router, "is_engine_reachable", fake_reachable)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert set(body.keys()) == {"engines"}, (
        f"DemoEnginesResponse top-level keys drifted: {sorted(body.keys())}"
    )
    for row in body["engines"]:
        assert set(row.keys()) == {"engine_type", "reachable"}, (
            f"DemoEngineStatus row keys drifted: {sorted(row.keys())}"
        )
