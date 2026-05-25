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

import structlog
from sqlalchemy import event, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from backend.app.db import repo
from backend.app.db.models import Study

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Public exceptions — router translates these to spec §7.5 error codes.
# ---------------------------------------------------------------------------


class StudyNotFound(Exception):
    """Router → 404 ``STUDY_NOT_FOUND``."""


class BaselineTrialNotFound(Exception):
    """Raised by :func:`stamp_baseline_trial` when ``trial_id`` doesn't exist.

    feat_study_baseline_trial FR-12 — the orchestrator / worker MUST pass a
    pre-generated UUIDv7 that corresponds to an inserted row by the time
    the helper is called. Missing rows indicate either a cascade race or a
    caller bug.
    """


class InvalidBaselineTrialState(Exception):
    """Raised when the loaded baseline trial row has unexpected attributes.

    feat_study_baseline_trial FR-12 — preconditions: ``trial.study_id ==
    study_id``, ``trial.is_baseline == True``, ``trial.status == 'complete'``.
    Anything else is a caller bug (the helper refuses to stamp
    ``baseline_trial_id`` against a non-baseline / non-complete row).
    """


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
    from_status = study.status
    _ensure_legal(from_status, "running")
    async with _authorize_status_mutation(db):
        study.status = "running"
        study.started_at = datetime.now(UTC)
        await db.flush()
    logger.info(
        "study state transition",
        event_type="study_state_transition",
        study_id=study_id,
        from_status=from_status,
        to_status="running",
    )
    return study


async def cancel_study(db: AsyncSession, study_id: str) -> Study:
    """Transition ``queued → cancelled`` or ``running → cancelled``.

    Stamps ``completed_at = now()`` so list-endpoint counts reflect the
    end time.
    """
    study = await _load_for_update(db, study_id)
    from_status = study.status
    _ensure_legal(from_status, "cancelled")
    async with _authorize_status_mutation(db):
        study.status = "cancelled"
        study.completed_at = datetime.now(UTC)
        await db.flush()
    logger.info(
        "study state transition",
        event_type="study_state_transition",
        study_id=study_id,
        from_status=from_status,
        to_status="cancelled",
    )
    return study


async def cancel_study_with_chain_cascade(
    db: AsyncSession,
    study_id: str,
    *,
    cascade: bool = True,
) -> Study:
    """Cancel a chain rooted at ``study_id`` (Story 1.3, FR-8 + cycle-3 C3-1).

    The cascade is **tolerant of terminal parents**: a normal
    auto-followup chain has ``parent.status == 'completed'`` by the time
    a child exists (the digest worker only fires on the ``completed``
    transition — verified at backend/workers/orchestrator.py:452). The
    cascade traverses the chain regardless of intermediate states; only
    in-flight (``queued``/``running``) studies get the cancel transition.

    Behavior:

    * If ``cascade=False`` — only the parent is touched. If the parent
      is terminal, ``cancel_study`` raises ``InvalidStateTransition``
      (preserves the existing single-cancel error contract per spec AC-9).
    * If ``cascade=True``:

      - If ``parent.status in {'queued', 'running'}``: call ``cancel_study(parent)``.
      - Else (parent already terminal): log ``auto_followup_cancel_terminal_parent``
        and DO NOT attempt the transition (avoids ``InvalidStateTransition``
        on completed ancestors per cycle-3 C3-1 fix).
      - In BOTH cases, iterate ``list_children_of_study(parent)`` and recurse
        into each child. Per cycle-3 C3-1: recurse into every direct child
        regardless of status so completed intermediates act as relay nodes
        on the way to in-flight descendants. The transition (and FR-9
        event #8 ``auto_followup_cancelled_with_parent``) fires only when
        a child is actually in-flight; terminal children emit
        ``auto_followup_cancel_terminal_parent`` and the recursion
        continues into THEIR children.

    Idempotency: ``cancel_study`` raises ``InvalidStateTransition`` on
    already-cancelled studies. The cascade catches it and continues so
    a re-delivery of a cascade request doesn't fail loudly.

    Returns the parent ``Study`` row (status may be ``'cancelled'`` if it
    was in-flight, or unchanged if it was already terminal).
    """
    # Lazy import to avoid a circular dependency
    # (repo.__init__ → services.study_state via cancel_study guard registration
    # in some test bootstrap paths). Inline import is the standard escape.
    from backend.app.db import repo

    # Per phase-gate review F3: cascade=False delegates to cancel_study so
    # the existing single-cancel error contract is preserved — terminal
    # parents raise InvalidStateTransition per AC-9 wire contract. Without
    # this, the service silently returns unchanged terminal parents and
    # diverges from its docstring.
    if not cascade:
        return await cancel_study(db, study_id)

    parent = await _load_for_update(db, study_id)

    # Parent transition (or terminal-skip).
    if parent.status in {"queued", "running"}:
        try:
            parent = await cancel_study(db, study_id)
        except InvalidStateTransition:
            # Race: another transition won between our _load_for_update and
            # the cancel_study re-read. Log and continue to the cascade so
            # children still get cleaned up.
            logger.info(
                "cancel_study_with_chain_cascade: parent transition race; continuing cascade",
                event_type="study_state_transition_race",
                study_id=study_id,
            )
    else:
        logger.info(
            "auto_followup cascade traversing terminal parent",
            event_type="auto_followup_cancel_terminal_parent",
            study_id=study_id,
            parent_status=parent.status,
        )

    # Cascade into direct children (C3-1: traverse all, not just in-flight).
    children = await repo.list_children_of_study(db, study_id)
    for child in children:
        if child.status in {"queued", "running"}:
            try:
                await cancel_study(db, child.id)
            except InvalidStateTransition:
                # Child already terminal between list + cancel — fine.
                logger.info(
                    "cascade cancel race on child; already terminal",
                    event_type="study_state_transition_race",
                    study_id=child.id,
                    parent_study_id=study_id,
                )
            else:
                logger.info(
                    "auto-followup child cancelled with parent",
                    event_type="auto_followup_cancelled_with_parent",
                    parent_study_id=study_id,
                    child_study_id=child.id,
                )
        else:
            logger.info(
                "auto_followup cascade traversing terminal child",
                event_type="auto_followup_cancel_terminal_parent",
                study_id=child.id,
                parent_study_id=study_id,
                parent_status=child.status,
            )
        # Always recurse — a completed child may own a running grandchild.
        await cancel_study_with_chain_cascade(db, child.id, cascade=True)

    return parent


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
    study = await _load_for_update(db, study_id)
    from_status = study.status
    _ensure_legal(from_status, "completed")
    async with _authorize_status_mutation(db):
        study.status = "completed"
        study.completed_at = datetime.now(UTC)
        study.best_metric = best_metric
        study.best_trial_id = best_trial_id
        await db.flush()
    logger.info(
        "study state transition",
        event_type="study_state_transition",
        study_id=study_id,
        from_status=from_status,
        to_status="completed",
        stop_reason=stop_reason,
        best_metric=best_metric,
        best_trial_id=best_trial_id,
    )
    return study


async def fail_study(
    db: AsyncSession,
    study_id: str,
    *,
    failed_reason: str,
) -> Study:
    """``running → failed`` + populate ``failed_reason`` per AC-5."""
    study = await _load_for_update(db, study_id)
    from_status = study.status
    _ensure_legal(from_status, "failed")
    async with _authorize_status_mutation(db):
        study.status = "failed"
        study.completed_at = datetime.now(UTC)
        study.failed_reason = failed_reason
        await db.flush()
    logger.warning(
        "study state transition",
        event_type="study_state_transition",
        study_id=study_id,
        from_status=from_status,
        to_status="failed",
        failed_reason=failed_reason,
    )
    return study


# ---------------------------------------------------------------------------
# Baseline-trial stamping helper (feat_study_baseline_trial FR-12)
# ---------------------------------------------------------------------------


async def stamp_baseline_trial(
    db: AsyncSession,
    study_id: str,
    trial_id: str,
    primary_metric: float,
) -> bool:
    """Stamp ``studies.baseline_trial_id`` + ``baseline_metric`` idempotently.

    Single chokepoint for all three paths that durably write the baseline
    FK (feat_study_baseline_trial D-12):

    1. The orchestrator's fast-path stamp (FR-2 step 7).
    2. The worker's self-stamp on successful baseline completion
       (FR-10 step 7).
    3. The ``resume_study`` re-stamp for unstamped complete baselines
       (spec §9 idempotency).

    Returns ``True`` if this caller stamped (1 row affected by the UPDATE);
    ``False`` if a sibling already stamped (race-tolerant — the
    ``WHERE baseline_trial_id IS NULL`` predicate makes this idempotent).

    Raises :class:`BaselineTrialNotFound` if the trial row is missing
    (caller bug — the orchestrator pre-generates the UUIDv7 and the worker
    INSERTed before calling). Raises :class:`InvalidBaselineTrialState`
    if the row's ``study_id`` / ``is_baseline`` / ``status`` don't match
    expectations.

    **Commit is left to the caller.** Both the orchestrator and the worker
    MUST call ``await db.commit()`` after this returns to durably land the
    stamp. The async-session pattern in :func:`complete_study` /
    :func:`fail_study` above sets the precedent.
    """
    trial = await repo.get_trial(db, trial_id)
    if trial is None:
        raise BaselineTrialNotFound(f"baseline trial {trial_id!r} not found in trials table")
    if trial.study_id != study_id:
        raise InvalidBaselineTrialState(
            f"baseline trial {trial_id!r} has study_id={trial.study_id!r}, expected {study_id!r}"
        )
    if not trial.is_baseline:
        raise InvalidBaselineTrialState(
            f"trial {trial_id!r} is not a baseline row (is_baseline=False)"
        )
    if trial.status != "complete":
        raise InvalidBaselineTrialState(
            f"baseline trial {trial_id!r} status={trial.status!r}, expected 'complete'"
        )

    # Idempotent UPDATE — only stamps if not already stamped.
    result = await db.execute(
        text(
            "UPDATE studies "
            "SET baseline_trial_id = :trial_id, baseline_metric = :primary_metric "
            "WHERE id = :study_id AND baseline_trial_id IS NULL "
            "RETURNING id"
        ),
        {
            "trial_id": trial_id,
            "primary_metric": primary_metric,
            "study_id": study_id,
        },
    )
    stamped = result.fetchone() is not None
    if stamped:
        logger.info(
            "baseline_stamped",
            event_type="baseline_stamped",
            study_id=study_id,
            trial_id=trial_id,
            primary_metric=primary_metric,
        )
    else:
        logger.info(
            "baseline_stamp_no_op",
            event_type="baseline_stamp_no_op",
            study_id=study_id,
            trial_id=trial_id,
            reason="baseline_trial_id_already_set",
        )
    return stamped


# ---------------------------------------------------------------------------
# Event listener — module-level callable + idempotent installer.
# ---------------------------------------------------------------------------


def _study_state_guard(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    """Block any unauthorized ORM-attribute ``Study.status`` change on ``before_flush``.

    Module-scoped so its identity is stable across multiple
    :func:`_install_state_guard_listener` calls. SQLAlchemy's
    duplicate-listener short-circuit relies on callable identity, not
    equality — a nested closure would silently register N times.

    Bulk ``session.execute(update(Study).values(status=...))`` statements
    bypass ``session.dirty`` and would slip past this listener; those are
    caught by :func:`_study_state_orm_execute_guard` below
    (``do_orm_execute`` event).
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


def _study_state_orm_execute_guard(orm_execute_state: object) -> None:
    """Block bulk ORM UPDATE/DELETE on ``Study.status`` via ``do_orm_execute``.

    Catches ``session.execute(update(Study).values(status=...))`` and
    similar bulk statements that bypass ``session.dirty`` (and therefore
    the ``before_flush`` listener). Cycle-2 GPT-5.5 review C2-F2 fix.

    Whitelisted by the same ``_GUARD_KEY`` sentinel as the dirty-row
    path, so service-layer mutators can still issue bulk updates if
    they ever need to (none do in MVP1).
    """
    from sqlalchemy.sql.dml import Update

    state = orm_execute_state  # untyped — SQLAlchemy passes ORMExecuteState
    session = getattr(state, "session", None)
    if session is None or session.info.get(_GUARD_KEY):
        return
    statement = getattr(state, "statement", None)
    if statement is None or not isinstance(statement, Update):
        return
    # Inspect the entity being updated.
    target = statement.entity_description or {}
    if target.get("entity") is not Study:
        return
    # Bulk update of Study; reject if `status` is in the SET clause.
    values = getattr(statement, "_values", None) or {}
    if any(getattr(col, "name", None) == "status" for col in values):
        raise StudyStateProtectionError(
            "direct bulk UPDATE of studies.status outside the service layer "
            "is forbidden; route through "
            "backend.app.services.study_state"
        )


def _install_state_guard_listener(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Idempotently attach the state guard to ``Session.before_flush`` + ``do_orm_execute``.

    Safe to call multiple times — ``event.contains`` short-circuits when
    the listener is already attached. The ``session_factory`` parameter
    is retained for signature compatibility with the wiring in
    ``backend.app.db.session`` but unused (the listener targets
    ``sqlalchemy.orm.Session`` directly).
    """
    del session_factory  # listener target is `Session`, not the factory
    if not event.contains(Session, "before_flush", _study_state_guard):
        event.listen(Session, "before_flush", _study_state_guard)
    if not event.contains(Session, "do_orm_execute", _study_state_orm_execute_guard):
        event.listen(Session, "do_orm_execute", _study_state_orm_execute_guard)
