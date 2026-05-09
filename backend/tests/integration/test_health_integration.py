"""End-to-end /healthz integration test (infra_foundation Story 4.4).

Boots the full Compose stack, hits ``GET /healthz``, asserts the documented
JSON shape (spec §7.3). Marked ``@pytest.mark.integration`` so it skips in
unit-only runs.

The test does NOT itself run ``docker compose up -d`` — it expects the stack
to be up. CI runs `make up` first; locally, run `make up && make test-integration`.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = os.environ.get("RELYLOOP_API_URL", "http://localhost:8000")


async def _api_reachable() -> bool:
    """Probe the API root with a 1s timeout. Skip the test if it's down."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            await client.get(f"{API_URL}/healthz")
        return True
    except (httpx.HTTPError, OSError):
        return False


@pytest.mark.integration
async def test_healthz_returns_documented_shape() -> None:
    """`GET /healthz` must return spec §7.3's JSON shape.

    Asserts the top-level keys + the per-subsystem enum values without
    asserting specific reachability — both 200 (all healthy) and 503
    (some down) are valid HTTP statuses for this contract.
    """
    if not await _api_reachable():
        pytest.skip(f"API not reachable at {API_URL} — run `make up` first")
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{API_URL}/healthz")
    # 200 or 503 — both are valid responses depending on subsystem state.
    assert resp.status_code in (200, 503), f"unexpected status {resp.status_code}"
    body = resp.json()
    assert set(body.keys()) >= {
        "status",
        "subsystems",
        "openai_endpoint",
        "openai_capabilities",
        "version",
        "uptime_seconds",
    }
    assert body["status"] in {"ok", "degraded"}
    assert set(body["subsystems"].keys()) == {
        "db",
        "redis",
        "openai",
        "elasticsearch",
        "opensearch",
    }
    # Per-subsystem enum sanity
    assert body["subsystems"]["db"] in {"ok", "down"}
    assert body["subsystems"]["redis"] in {"ok", "down"}
    assert body["subsystems"]["openai"] in {"configured", "missing_key", "incapable"}
    assert body["subsystems"]["elasticsearch"] in {"reachable", "unreachable"}
    assert body["subsystems"]["opensearch"] in {"reachable", "unreachable"}
    assert isinstance(body["uptime_seconds"], int) and body["uptime_seconds"] >= 0


@pytest.mark.integration
async def test_healthz_status_consistent_with_subsystems() -> None:
    """`status: degraded` ⇔ at least one of db/redis/es/opensearch is unhealthy."""
    if not await _api_reachable():
        pytest.skip(f"API not reachable at {API_URL} — run `make up` first")
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{API_URL}/healthz")
    body = resp.json()
    s = body["subsystems"]
    blocking_down = (
        s["db"] == "down"
        or s["redis"] == "down"
        or s["elasticsearch"] == "unreachable"
        or s["opensearch"] == "unreachable"
    )
    expected = "degraded" if blocking_down else "ok"
    assert (
        body["status"] == expected
    ), f"status={body['status']!r} but subsystems={s!r} imply {expected!r}"
    expected_http = 503 if expected == "degraded" else 200
    assert resp.status_code == expected_http
