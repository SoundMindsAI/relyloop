"""``backend.app.services.study_state`` unit tests (Story 1.3, FR-7).

State-machine + guard-listener tests. Service-layer functions are async
and take an ``AsyncSession`` — we mock the row-fetch + flush via a tiny
fake session helper instead of standing up a real DB connection (those
paths are covered by integration tests in Story 2.1).

AC-6 lives here in spirit (the unit test asserts the listener raises
``StudyStateProtectionError`` when ``Session.info`` doesn't carry the
sentinel) and is reasserted in
``backend/tests/integration/test_study_lifecycle.py`` with a real flush.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.db.models import Study
from backend.app.services import study_state
from backend.app.services.study_state import (
    _GUARD_KEY,
    InvalidStateTransition,
    StudyNotFound,
    StudyStateProtectionError,
    _study_state_guard,
)

# ---------------------------------------------------------------------------
# Fake session — enough surface for the service functions under test.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value: Any) -> None:  # noqa: ANN401 — test helper
        self._value = value

    def scalar_one_or_none(self) -> Any:  # noqa: ANN401 — test helper
        return self._value


class _FakeSyncSession:
    """Minimal sync-session surface — only `.info` is needed for the
    sentinel context manager and the listener identity check."""

    def __init__(self) -> None:
        self.info: dict[str, Any] = {}


class _FakeAsyncSession:
    """Tiny AsyncSession surface for the state-machine tests.

    Records calls so the test can assert mutation order without spinning
    up a real engine.
    """

    def __init__(self, study: Study | None) -> None:
        self._study = study
        self._sync = _FakeSyncSession()
        self.flushed = False

    async def execute(self, _stmt: Any) -> _FakeResult:  # noqa: ANN401
        return _FakeResult(self._study)

    async def flush(self) -> None:
        self.flushed = True

    @property
    def sync_session(self) -> _FakeSyncSession:
        return self._sync


def _build_study(status: str) -> Study:
    """Construct a Study row without touching the DB."""
    return Study(
        id="study-1",
        name="t",
        cluster_id="c1",
        target="idx",
        template_id="tpl",
        query_set_id="qs",
        judgment_list_id="jl",
        search_space={"params": {}},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 10},
        status=status,
        optuna_study_name="study-1",
    )


# ---------------------------------------------------------------------------
# Happy-path transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_study_queued_to_running() -> None:
    study = _build_study("queued")
    db = _FakeAsyncSession(study)
    result = await study_state.start_study(db, "study-1")  # type: ignore[arg-type]
    assert result.status == "running"
    assert isinstance(result.started_at, datetime)
    assert db.flushed


@pytest.mark.asyncio
async def test_start_study_is_idempotent_on_running() -> None:
    """Resume path — FR-5. Returns unchanged; no flush, no mutation."""
    study = _build_study("running")
    original_started_at = study.started_at
    db = _FakeAsyncSession(study)
    result = await study_state.start_study(db, "study-1")  # type: ignore[arg-type]
    assert result.status == "running"
    assert result.started_at is original_started_at
    assert not db.flushed


@pytest.mark.asyncio
async def test_cancel_study_from_queued() -> None:
    study = _build_study("queued")
    db = _FakeAsyncSession(study)
    result = await study_state.cancel_study(db, "study-1")  # type: ignore[arg-type]
    assert result.status == "cancelled"
    assert isinstance(result.completed_at, datetime)


@pytest.mark.asyncio
async def test_cancel_study_from_running() -> None:
    study = _build_study("running")
    db = _FakeAsyncSession(study)
    result = await study_state.cancel_study(db, "study-1")  # type: ignore[arg-type]
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_complete_study_denormalizes_winners() -> None:
    study = _build_study("running")
    db = _FakeAsyncSession(study)
    result = await study_state.complete_study(
        db,  # type: ignore[arg-type]
        "study-1",
        best_metric=0.83,
        best_trial_id="trial-best",
        stop_reason="max_trials_reached",
    )
    assert result.status == "completed"
    assert result.best_metric == 0.83
    assert result.best_trial_id == "trial-best"


@pytest.mark.asyncio
async def test_fail_study_populates_reason() -> None:
    study = _build_study("running")
    db = _FakeAsyncSession(study)
    result = await study_state.fail_study(
        db,  # type: ignore[arg-type]
        "study-1",
        failed_reason="5 consecutive trial failures",
    )
    assert result.status == "failed"
    assert result.failed_reason == "5 consecutive trial failures"


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "transition"),
    [
        # Terminal states are sinks — no transition out.
        ("completed", "running"),
        ("completed", "cancelled"),
        ("cancelled", "running"),
        ("failed", "running"),
        # queued can only go to running/cancelled — not completed/failed.
        ("queued", "completed"),
        ("queued", "failed"),
    ],
)
@pytest.mark.asyncio
async def test_illegal_transitions_raise(from_status: str, transition: str) -> None:
    """Terminal states are sinks; queued can only go to running/cancelled."""
    study = _build_study(from_status)
    db = _FakeAsyncSession(study)
    if transition == "running":
        with pytest.raises(InvalidStateTransition):
            await study_state.start_study(db, "study-1")  # type: ignore[arg-type]
    elif transition == "completed":
        with pytest.raises(InvalidStateTransition):
            await study_state.complete_study(
                db,  # type: ignore[arg-type]
                "study-1",
                best_metric=None,
                best_trial_id=None,
                stop_reason="x",
            )
    elif transition == "cancelled":
        with pytest.raises(InvalidStateTransition):
            await study_state.cancel_study(db, "study-1")  # type: ignore[arg-type]
    elif transition == "failed":
        with pytest.raises(InvalidStateTransition):
            await study_state.fail_study(db, "study-1", failed_reason="x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_study_not_found_raises() -> None:
    db = _FakeAsyncSession(None)
    with pytest.raises(StudyNotFound):
        await study_state.start_study(db, "absent")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Guard listener — AC-6 (duck-typed; integration coverage in
# test_study_lifecycle.py wires the listener to a real session + flush)
# ---------------------------------------------------------------------------


class _FakeListenerSession:
    """Duck-typed stand-in for ``sqlalchemy.orm.Session`` — surface used
    by :func:`_study_state_guard` is just ``.info`` (dict) + ``.dirty``
    (iterable). We can't subclass Session because its constructor wants
    a real engine; we can't bypass __init__ because ``Session.dirty`` is
    a read-only property. Listener signature accepts ``Session`` but the
    implementation never narrows beyond duck typing."""

    def __init__(self, info: dict[str, Any], dirty: set[object]) -> None:
        self.info = info
        self.dirty = dirty


def test_guard_raises_when_status_changed_without_sentinel() -> None:
    """A Study with a changed `.status` and no sentinel in `session.info`
    raises StudyStateProtectionError."""
    study = _build_study("queued")
    study.status = "running"
    fake = _FakeListenerSession(info={}, dirty={study})

    with pytest.raises(StudyStateProtectionError, match="forbidden"):
        _study_state_guard(fake, None, None)  # type: ignore[arg-type]


def test_guard_allows_when_sentinel_set() -> None:
    """With the sentinel set, the listener returns silently."""
    study = _build_study("queued")
    study.status = "running"
    fake = _FakeListenerSession(info={_GUARD_KEY: True}, dirty={study})

    _study_state_guard(fake, None, None)  # type: ignore[arg-type]


def test_guard_ignores_non_study_objects() -> None:
    """Other ORM models in the dirty set are ignored — only Study is protected."""

    class Other:
        pass

    fake = _FakeListenerSession(info={}, dirty={Other()})
    _study_state_guard(fake, None, None)  # type: ignore[arg-type]


# "Only ``status`` is inspected" / "non-status mutations don't trigger" is
# covered by the AC-6 integration test in test_study_lifecycle.py — the
# transient-vs-loaded attribute-history semantics require a real Session
# to exercise meaningfully.

# Silence "Session imported but unused" — kept for type-hint clarity in
# the docstring above.
del Session
