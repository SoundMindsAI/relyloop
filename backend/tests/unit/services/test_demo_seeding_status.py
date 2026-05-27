"""Unit tests for the demo-reseed status helpers and Redis serialization.

Per ``bug_demo_reseed_fake_metric_regression``. Covers the pure parts of
the new flow: the ReseedStatusResponse Pydantic shape, the search_space
builder, and the Redis status_get/status_set round-trip via a stub Redis.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.services.demo_seeding import (
    DEMO_RESEED_STATUS_KEY,
    DEMO_RESEED_STATUS_TTL_S,
    ReseedStatusResponse,
    ReseedSummary,
    _build_search_space,
    status_get,
    status_set,
)


class _StubRedis:
    """Minimal async Redis stub — only the get/set operations we care about."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.store[key] = value
        self.ttls[key] = ex

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)


def test_reseed_status_shape_required_fields() -> None:
    """``status`` is the only required field; everything else defaults."""
    s = ReseedStatusResponse(status="idle")
    assert s.status == "idle"
    assert s.scenarios_total == 0
    assert s.scenarios_completed == 0
    assert s.current_step is None
    assert s.failed_reason is None
    assert s.summary is None


def test_reseed_status_rejects_extra_fields() -> None:
    """``extra="forbid"`` so the wire shape stays in lockstep with the schema."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReseedStatusResponse.model_validate({"status": "idle", "unknown": "field"})


@pytest.mark.parametrize(
    "status",
    ["idle", "running", "complete", "failed"],
)
def test_reseed_status_accepts_each_literal(status: str) -> None:
    s = ReseedStatusResponse.model_validate({"status": status})
    assert s.status == status


def test_reseed_status_rejects_unknown_literal() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReseedStatusResponse.model_validate({"status": "invalid"})


def test_reseed_status_summary_field_roundtrips() -> None:
    """The summary slot accepts a full ReseedSummary on completion."""
    summary = ReseedSummary(
        clusters_created=4,
        query_sets_created=4,
        studies_completed=4,
        proposals_created=4,
        duration_ms=12345,
    )
    s = ReseedStatusResponse(status="complete", summary=summary)
    assert s.summary is not None
    assert s.summary.duration_ms == 12345


async def test_status_set_writes_json_with_ttl() -> None:
    """``status_set`` JSON-encodes the payload + sets the 1h TTL."""
    redis = _StubRedis()
    status = ReseedStatusResponse(
        status="running",
        started_at="2026-05-27T16:50:00Z",
        scenarios_total=4,
        scenarios_completed=2,
        current_step="seeding acme",
    )
    await status_set(redis, status)  # type: ignore[arg-type]
    raw = redis.store[DEMO_RESEED_STATUS_KEY]
    payload = json.loads(raw)
    assert payload["status"] == "running"
    assert payload["scenarios_completed"] == 2
    assert payload["current_step"] == "seeding acme"
    assert redis.ttls[DEMO_RESEED_STATUS_KEY] == DEMO_RESEED_STATUS_TTL_S


async def test_status_get_returns_idle_when_key_absent() -> None:
    """Absent key → status="idle" rather than 404 / exception (D-5)."""
    redis = _StubRedis()
    s = await status_get(redis)  # type: ignore[arg-type]
    assert s.status == "idle"
    assert s.scenarios_total == 0


async def test_status_get_roundtrips_full_payload() -> None:
    redis = _StubRedis()
    original = ReseedStatusResponse(
        status="complete",
        started_at="2026-05-27T16:50:00Z",
        finished_at="2026-05-27T16:53:42Z",
        scenarios_total=4,
        scenarios_completed=4,
        summary=ReseedSummary(
            clusters_created=4,
            query_sets_created=4,
            studies_completed=4,
            proposals_created=4,
            duration_ms=12345,
        ),
    )
    await status_set(redis, original)  # type: ignore[arg-type]
    fetched = await status_get(redis)  # type: ignore[arg-type]
    assert fetched.status == "complete"
    assert fetched.scenarios_completed == 4
    assert fetched.summary is not None
    assert fetched.summary.duration_ms == 12345


async def test_status_get_handles_malformed_json_as_idle() -> None:
    """Defensive: a corrupted key shouldn't crash the polling endpoint."""
    redis = _StubRedis()
    redis.store[DEMO_RESEED_STATUS_KEY] = b"not-json-{"
    s = await status_get(redis)  # type: ignore[arg-type]
    assert s.status == "idle"


def test_build_search_space_emits_log_uniform_floats_for_each_param() -> None:
    """The CLI's exact shape — every declared param gets [0.5, 5.0] log-uniform."""
    space = _build_search_space({"title_boost": "float", "description_boost": "float"})
    assert set(space["params"].keys()) == {"title_boost", "description_boost"}
    title: dict[str, Any] = space["params"]["title_boost"]
    assert title == {"type": "float", "low": 0.5, "high": 5.0, "log": True}


def test_build_search_space_empty_params_returns_empty_space() -> None:
    space = _build_search_space({})
    assert space == {"params": {}}
