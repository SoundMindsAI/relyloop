"""Study state machine + ``studies.status`` protection guard (Story 1.3, FR-7).

All ``studies.status`` mutations route through four async service functions
(``start_study``, ``cancel_study``, ``complete_study``, ``fail_study``).
A module-level ``before_flush`` event listener attached to
``sqlalchemy.orm.Session`` detects any mutation that did NOT go through
this module (i.e. didn't set the ``_GUARD_KEY`` sentinel on ``Session.info``)
and raises :exc:`StudyStateProtectionError`. AC-6 verified.

**Legal transitions** (per spec §9 state diagram):

.. code-block::

    queued    → running | cancelled
    running   → completed | cancelled | failed
    completed → (terminal)
    cancelled → (terminal)
    failed    → (terminal)

Idempotency note: ``start_study(study_id)`` on an already-``running`` study
is a no-op (returns the row unchanged). This is the FR-5 resume path —
``backend/workers/orchestrator.py:start_study`` (the Arq job) calls this
service function unconditionally on entry; on a resume invocation the
study is already ``running`` and we return immediately rather than raising
``InvalidStateTransition``.

**Cancel-race tolerance** (spec §11): all transitions ``SELECT … FOR UPDATE``
the study row, so concurrent transitions serialize at the row-lock; the
loser raises :exc:`InvalidStateTransition`. The orchestrator's `_stop`
helper catches this and exits silently.

**Listener wiring**: :func:`_install_state_guard_listener` is idempotent
via ``event.contains(...)``; safe to call from multiple test sessions or
from process re-entry. ``_study_state_guard`` is module-level (NOT defined
inside the installer) so its callable identity is stable — without this,
each installer call would register a fresh closure and accumulate
duplicate listeners (C2-F2 cycle-2 finding).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from backend.app.db.models import Study

# ---------------------------------------------------------------------------
# Public exceptions — router translates these to spec §7.5 error codes.
# ---------------------------------------------------------------------------


class StudyNotFound(Exception):
    """Router → 404 ``STUDY_NOT_FOUND``."""


class InvalidStateTransition(Exception):
    """Router → 409 ``INVALID_STATE_TRANSITION``."""


class StudyStateProtectionError(RuntimeError):
    """Raised when an unauthorized ``Study.status`` change is attempted.

    The ``before_flush`` listener detects status mutations on Study rows
    that don't carry the ``_GUARD_KEY`` sentinel in ``Session.info``.
    Service callers MUST go through one of the public functions in this
    module (``start_study``, ``cancel_study``, ``complete_study``,
    ``fail_study``), which set the sentinel for the duration of their
    mutation.

    AC-6 verified by ``test_study_state.py`` (unit) and
    ``test_study_lifecycle.py`` (integration — real session + flush).
    """


# ---------------------------------------------------------------------------
# Authorization sentinel — set on Session.info via the context manager.
# ---------------------------------------------------------------------------


_GUARD_KEY = "_relyloop_study_state_authorized"


@asynccontextmanager
async def _authorize_status_mutation(db: AsyncSession) -> AsyncIterator[None]:
    """Mark the underlying sync Session as authorized to mutate ``studies.status``.

    The ``before_flush`` listener checks ``session.info[_GUARD_KEY]`` and
    permits the change. Cleared on exit so subsequent unrelated flushes
    on the same session don't inherit the authorization.
    """
    sync_session = db.sync_session
    sync_session.info[_GUARD_KEY] = True
    try:
        yield
    finally:
        sync_session.info.pop(_GUARD_KEY, None)


# ---------------------------------------------------------------------------
# Legal-transition matrix — single source of truth.
# ---------------------------------------------------------------------------


_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}


def _ensure_legal(current: str, target: str) -> None:
    if target not in _LEGAL_TRANSITIONS.get(current, frozenset()):
        raise InvalidStateTransition(f"illegal transition: {current!r} → {target!r}")


# ---------------------------------------------------------------------------
# Public transitions
# ---------------------------------------------------------------------------


async def _load_for_update(db: AsyncSession, study_id: str) -> Study:
    """``SELECT … FOR UPDATE`` to serialize concurrent transitions.

    Spec §11 "Cancel race": a user cancel and an orchestrator-driven
    `max_trials` stop can fire simultaneously. The row lock ensures one
    transaction wins; the loser sees the post-commit state on its own
    re-read and raises ``InvalidStateTransition`` from ``_ensure_legal``.
    """
    stmt = select(Study).where(Study.id == study_id).with_for_update()
    study = (await db.execute(stmt)).scalar_one_or_none()
    if study is None:
        raise StudyNotFound(study_id)
    return study


async def start_study(db: AsyncSession, study_id: str) -> Study:
    """Atomic ``queued → running``; stamps ``started_at = now()``.

    Idempotent on ``running`` — returns the row unchanged so the
    FR-5 resume path (orchestrator restart) can call this
    unconditionally without raising.
    """
    study = await _load_for_update(db, study_id)
    if study.status == "running":
        return study  # idempotent — resume path
    _ensure_legal(study.status, "running")
    async with _authorize_status_mutation(db):
        study.status = "running"
        study.started_at = datetime.now(UTC)
        await db.flush()
    return study


async def cancel_study(db: AsyncSession, study_id: str) -> Study:
    """Transition ``queued → cancelled`` or ``running → cancelled``.

    Stamps ``completed_at = now()`` so list-endpoint counts reflect the
    end time.
    """
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "cancelled")
    async with _authorize_status_mutation(db):
        study.status = "cancelled"
        study.completed_at = datetime.now(UTC)
        await db.flush()
    return study


async def complete_study(
    db: AsyncSession,
    study_id: str,
    *,
    best_metric: float | None,
    best_trial_id: str | None,
    stop_reason: str,
) -> Study:
    """``running → completed`` + denormalize best_metric / best_trial_id.

    ``stop_reason`` is captured by the caller's structlog log entry
    (``event_type='stop_condition_fired'``) — not persisted on the row
    (no column for it in MVP1; spec §13 Operability defines the log
    contract). Accepted values: ``max_trials_reached`` |
    ``time_budget_exceeded``.
    """
    del stop_reason  # for log context only; not persisted in MVP1
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "completed")
    async with _authorize_status_mutation(db):
        study.status = "completed"
        study.completed_at = datetime.now(UTC)
        study.best_metric = best_metric
        study.best_trial_id = best_trial_id
        await db.flush()
    return study


async def fail_study(
    db: AsyncSession,
    study_id: str,
    *,
    failed_reason: str,
) -> Study:
    """``running → failed`` + populate ``failed_reason`` per AC-5."""
    study = await _load_for_update(db, study_id)
    _ensure_legal(study.status, "failed")
    async with _authorize_status_mutation(db):
        study.status = "failed"
        study.completed_at = datetime.now(UTC)
        study.failed_reason = failed_reason
        await db.flush()
    return study


# ---------------------------------------------------------------------------
# Event listener — module-level callable + idempotent installer.
# ---------------------------------------------------------------------------


def _study_state_guard(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    """Block any unauthorized ``Study.status`` change on ``before_flush``.

    Module-scoped so its identity is stable across multiple
    :func:`_install_state_guard_listener` calls. SQLAlchemy's
    duplicate-listener short-circuit relies on callable identity, not
    equality — a nested closure would silently register N times.
    """
    del flush_context, instances  # not needed; listener signature requires them
    if session.info.get(_GUARD_KEY):
        return
    for obj in session.dirty:
        if not isinstance(obj, Study):
            continue
        history = inspect(obj).attrs["status"].history
        if history.has_changes():
            raise StudyStateProtectionError(
                "direct UPDATE of studies.status outside the service layer "
                "is forbidden; route through "
                "backend.app.services.study_state"
            )


def _install_state_guard_listener(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Idempotently attach the state guard to ``Session.before_flush``.

    Safe to call multiple times — ``event.contains`` short-circuits when
    the listener is already attached. The ``session_factory`` parameter
    is retained for signature compatibility with the wiring in
    ``backend.app.db.session`` but unused (the listener targets
    ``sqlalchemy.orm.Session`` directly).
    """
    del session_factory  # listener target is `Session`, not the factory
    if not event.contains(Session, "before_flush", _study_state_guard):
        event.listen(Session, "before_flush", _study_state_guard)
