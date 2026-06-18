# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``GET /api/v1/_test/demo/engines``.

feat_selective_engine_startup_and_demo Story 2.1 / FR-7 — base capability
endpoint.

feat_engine_version_selection Story 2.2 / FR-7+FR-8 — extends each row
with the engine's self-reported version. The handler now calls
``is_engine_reachable_with_version`` (returns ``(reachable, version)``)
instead of the bool-only ``is_engine_reachable``. These tests patch the
new sibling — see test_is_engine_reachable_with_version.py for hermetic
unit tests of the probe itself.

The backend CI service-container topology runs ES and OpenSearch but NOT
Solr (Solr only runs in the optional smoke job per
infra_smoke_reseed_runtime_budget). So in this test environment we expect:
  - elasticsearch.reachable = True
  - opensearch.reachable    = True
  - solr.reachable          = False

The tests patch the probe to make the assertions deterministic regardless
of the local-vs-CI engine availability — the real probe is exercised
inside its own unit tests; here we're guarding the endpoint's wiring
(ordering, shape, parallel dispatch, 200-on-all-down, version field
propagation).
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

    async def fake_probe(_url: str, _engine_type: str) -> tuple[bool, str | None]:
        return True, "x.y.z"

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
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
        assert set(row.keys()) == {"engine_type", "reachable", "version"}


async def test_engines_endpoint_reports_mixed_reachability(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES + OS reachable, Solr unreachable → faithful per-engine booleans."""
    from backend.app.api.v1 import _test as test_router

    async def fake_probe(_url: str, engine_type: str) -> tuple[bool, str | None]:
        if engine_type == "solr":
            return False, None
        return True, "x.y.z"

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
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

    async def fake_probe(_url: str, _engine_type: str) -> tuple[bool, str | None]:
        return False, None

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    assert all(not row["reachable"] for row in response.json()["engines"])


async def test_engines_endpoint_probes_engines_in_parallel(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent dispatch — three 0.5s probes finish in ~0.5s, not ~1.5s.

    Guards against accidental sequential refactoring of the
    asyncio.gather call.
    """
    import asyncio
    import time

    from backend.app.api.v1 import _test as test_router

    async def slow_probe(_url: str, _engine_type: str) -> tuple[bool, str | None]:
        await asyncio.sleep(0.5)
        return True, "x.y.z"

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", slow_probe)
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
    """The Pydantic models reject extra fields — ConfigDict(extra='forbid').

    feat_engine_version_selection Story 2.2: the `version` field was added
    to DemoEngineStatus; ensure it's the only addition and no other field
    snuck in.
    """
    from backend.app.api.v1 import _test as test_router

    async def fake_probe(_url: str, _engine_type: str) -> tuple[bool, str | None]:
        return True, "x.y.z"

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert set(body.keys()) == {"engines"}, (
        f"DemoEnginesResponse top-level keys drifted: {sorted(body.keys())}"
    )
    for row in body["engines"]:
        assert set(row.keys()) == {"engine_type", "reachable", "version"}, (
            f"DemoEngineStatus row keys drifted: {sorted(row.keys())}"
        )


# ---------------------------------------------------------------------------
# feat_engine_version_selection Story 2.2 — version field assertions
# ---------------------------------------------------------------------------


async def test_engines_endpoint_returns_version_when_reachable(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: when an engine is reachable, its row carries the parsed version.

    Mock returns engine-specific version strings so the test verifies the
    handler propagates them faithfully (i.e. the version isn't hardcoded
    or constant-folded).
    """
    from backend.app.api.v1 import _test as test_router

    async def fake_probe(_url: str, engine_type: str) -> tuple[bool, str | None]:
        versions = {"elasticsearch": "9.4.1", "opensearch": "3.6.0", "solr": "10.0.0"}
        return True, versions[engine_type]

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    rows = {row["engine_type"]: row for row in response.json()["engines"]}
    assert rows["elasticsearch"] == {
        "engine_type": "elasticsearch",
        "reachable": True,
        "version": "9.4.1",
    }
    assert rows["opensearch"] == {
        "engine_type": "opensearch",
        "reachable": True,
        "version": "3.6.0",
    }
    assert rows["solr"] == {
        "engine_type": "solr",
        "reachable": True,
        "version": "10.0.0",
    }


async def test_engines_endpoint_returns_null_version_when_unreachable(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6: unreachable engine row carries version=null; reachable peers unchanged.

    Also covers AC-7's contract on the endpoint side: a probe that returns
    (True, None) (reachable but version malformed) is faithfully propagated
    as reachable=true + version=null — the operator still sees the engine
    answered.
    """
    from backend.app.api.v1 import _test as test_router

    async def fake_probe(_url: str, engine_type: str) -> tuple[bool, str | None]:
        if engine_type == "opensearch":
            return False, None  # unreachable
        if engine_type == "solr":
            return True, None  # reachable, version probe failed (AC-7)
        return True, "9.4.1"  # ES happy path

    monkeypatch.setattr(test_router, "is_engine_reachable_with_version", fake_probe)
    response = await async_client.get("/api/v1/_test/demo/engines")
    assert response.status_code == 200
    rows = {row["engine_type"]: row for row in response.json()["engines"]}
    assert rows["elasticsearch"]["version"] == "9.4.1"
    assert rows["elasticsearch"]["reachable"] is True
    assert rows["opensearch"]["reachable"] is False
    assert rows["opensearch"]["version"] is None
    assert rows["solr"]["reachable"] is True
    assert rows["solr"]["version"] is None
