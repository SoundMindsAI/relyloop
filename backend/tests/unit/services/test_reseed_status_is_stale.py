"""Unit tests for ``reseed_status_is_stale`` (defense-in-depth stale check).

Per ``bug_demo_reseed_button_silent_enqueue_failure`` §"Proposed
capabilities" #2. The POST handler uses this helper to convert a
stuck-``running`` status (where the worker crashed before any exception
handler could write ``failed``) into a "treat as failed and proceed"
outcome, instead of leaving the operator 409-blocked forever.

Pure function, deterministic, accepts ``now`` for testability.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.services.demo_seeding import (
    DEMO_RESEED_JOB_TIMEOUT_S,
    ReseedStatusResponse,
    reseed_status_is_stale,
)

_NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)


def _running(started_offset_s: int) -> ReseedStatusResponse:
    """Build a ``running`` payload with ``started_at`` = ``_NOW - offset``."""
    started = (_NOW - timedelta(seconds=started_offset_s)).isoformat().replace("+00:00", "Z")
    return ReseedStatusResponse(status="running", started_at=started)


def test_idle_status_is_never_stale() -> None:
    """Stale check only applies to ``running``."""
    assert reseed_status_is_stale(ReseedStatusResponse(status="idle"), now=_NOW) is False


@pytest.mark.parametrize("status", ["complete", "failed"])
def test_terminal_statuses_are_never_stale(status: str) -> None:
    """``complete`` and ``failed`` are terminal — the POST handler doesn't gate on them."""
    s = ReseedStatusResponse(
        status=status,
        started_at="2020-01-01T00:00:00Z",  # ancient
    )
    assert reseed_status_is_stale(s, now=_NOW) is False


def test_running_without_started_at_is_not_stale() -> None:
    """Missing ``started_at`` → conservative: not stale (keep the 409 behavior)."""
    s = ReseedStatusResponse(status="running")
    assert reseed_status_is_stale(s, now=_NOW) is False


def test_running_with_malformed_started_at_is_not_stale() -> None:
    """Unparseable timestamp → conservative: not stale."""
    s = ReseedStatusResponse(status="running", started_at="not-an-iso-string")
    assert reseed_status_is_stale(s, now=_NOW) is False


def test_running_just_started_is_not_stale() -> None:
    """Fresh running job → 409 behavior preserved."""
    assert reseed_status_is_stale(_running(0), now=_NOW) is False


def test_running_at_exactly_the_timeout_is_not_stale() -> None:
    """Boundary: == timeout → not yet stale (strict `>` comparison)."""
    assert reseed_status_is_stale(_running(DEMO_RESEED_JOB_TIMEOUT_S), now=_NOW) is False


def test_running_one_second_past_timeout_is_stale() -> None:
    """Boundary: > timeout → stale."""
    assert reseed_status_is_stale(_running(DEMO_RESEED_JOB_TIMEOUT_S + 1), now=_NOW) is True


def test_running_far_past_timeout_is_stale() -> None:
    """Hour-old running status (4x the timeout) is unambiguously stale."""
    assert reseed_status_is_stale(_running(3600 * 4), now=_NOW) is True


def test_custom_timeout_threshold_respected() -> None:
    """Caller can override the timeout (used by tests; production uses the default)."""
    s = _running(60)  # 1 min old
    assert reseed_status_is_stale(s, now=_NOW, timeout_s=30) is True
    assert reseed_status_is_stale(s, now=_NOW, timeout_s=120) is False


def test_naive_timestamp_treated_as_utc() -> None:
    """Tolerate a ``started_at`` without timezone — assume UTC.

    Defensive: the worker writes ``_now_iso`` which always emits a ``Z``
    suffix, but a future code path or manual Redis edit could write a
    naive timestamp. Don't crash; treat as UTC.
    """
    naive = (_NOW - timedelta(seconds=DEMO_RESEED_JOB_TIMEOUT_S + 60)).isoformat()
    s = ReseedStatusResponse(status="running", started_at=naive)
    assert reseed_status_is_stale(s, now=_NOW) is True
