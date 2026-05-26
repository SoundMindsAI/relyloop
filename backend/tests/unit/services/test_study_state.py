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


# ---------------------------------------------------------------------------
# feat_auto_followup_studies Story 1.3 — cancel_study_with_chain_cascade
# ---------------------------------------------------------------------------


def _build_study_with_id(study_id: str, *, status: str, parent_id: str | None = None) -> Study:
    """Like _build_study but with custom id + optional parent_study_id."""
    return Study(
        id=study_id,
        name=f"study-{study_id}",
        cluster_id="c1",
        target="idx",
        template_id="tpl",
        query_set_id="qs",
        judgment_list_id="jl",
        search_space={"params": {}},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 10},
        status=status,
        optuna_study_name=study_id,
        parent_study_id=parent_id,
    )


class _MultiStudyFakeSession:
    """Fake AsyncSession that returns studies from an in-memory map.

    Supports the cascade flow: ``_load_for_update(study_id)`` → returns
    the study with that id. ``flush()`` is a no-op (mutations happen on
    the in-memory rows). Tracks every status mutation so tests can
    assert the cascade hit the right rows.
    """

    def __init__(self, studies: dict[str, Study]) -> None:
        self._studies = studies
        self._sync = _FakeSyncSession()
        self.flush_count = 0

    async def execute(self, stmt: Any) -> _FakeResult:  # noqa: ANN401
        # _load_for_update builds `SELECT Study WHERE Study.id == study_id .with_for_update()`
        # The id is embedded as a positional bind param; pull from the compiled stmt.
        compiled = stmt.compile()
        # Pydantic-validated id strings; SQLAlchemy's compiled params dict carries the
        # id under the first positional key, which is "id_1" in the default style.
        bound = compiled.params
        # Look for a parameter whose value matches a known study id; safer than
        # trying to parse SQLAlchemy's internal naming.
        for _key, value in bound.items():
            if isinstance(value, str) and value in self._studies:
                return _FakeResult(self._studies[value])
        return _FakeResult(None)

    async def flush(self) -> None:
        self.flush_count += 1

    @property
    def sync_session(self) -> _FakeSyncSession:
        return self._sync


@pytest.mark.asyncio
async def test_cascade_cancel_in_flight_parent_with_no_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Realistic single-study case: in-flight parent + no children → just
    cancels the parent. No cascade activity (matches existing
    single-cancel behavior)."""
    parent = _build_study_with_id("p1", status="running")
    db = _MultiStudyFakeSession({"p1": parent})

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    result = await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_cascade_cancel_completed_parent_with_running_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Realistic chain case (AC-8): completed parent + running direct
    child. Parent stays completed (no transition); child gets cancelled."""
    parent = _build_study_with_id("p1", status="completed")
    child = _build_study_with_id("c1", status="running", parent_id="p1")
    db = _MultiStudyFakeSession({"p1": parent, "c1": child})

    async def fake_list_children(_db: Any, parent_id: str) -> list[Study]:
        return [child] if parent_id == "p1" else []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    result = await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]
    assert result.status == "completed"  # parent unchanged (terminal)
    assert child.status == "cancelled"  # child transitioned


@pytest.mark.asyncio
async def test_cascade_cancel_completed_root_completed_middle_running_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-3 C3-1 the-leaf-is-2-hops-deep case. Depth-3 chain where
    the only in-flight study is the leaf. Cascade must recurse through
    the completed intermediate to reach it."""
    root = _build_study_with_id("R", status="completed")
    middle = _build_study_with_id("M", status="completed", parent_id="R")
    leaf = _build_study_with_id("L", status="running", parent_id="M")
    db = _MultiStudyFakeSession({"R": root, "M": middle, "L": leaf})

    async def fake_list_children(_db: Any, parent_id: str) -> list[Study]:
        if parent_id == "R":
            return [middle]
        if parent_id == "M":
            return [leaf]
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    result = await study_state.cancel_study_with_chain_cascade(db, "R")  # type: ignore[arg-type]
    assert result.status == "completed"
    assert middle.status == "completed"
    assert leaf.status == "cancelled"  # the only in-flight node → only one transition


@pytest.mark.asyncio
async def test_cascade_no_cascade_on_terminal_parent_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cascade=False on a terminal parent raises InvalidStateTransition
    per AC-9 wire contract (phase-gate review F3 — service now delegates
    to cancel_study so the single-cancel error contract is preserved).

    Without the delegation, the service would silently return unchanged
    and the API would have to compensate. With the delegation, the
    service's behavior matches its docstring and the API just routes."""
    parent = _build_study_with_id("p1", status="completed")
    db = _MultiStudyFakeSession({"p1": parent})

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        return []  # Shouldn't be called when cascade=False

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    with pytest.raises(InvalidStateTransition):
        await study_state.cancel_study_with_chain_cascade(
            db,  # type: ignore[arg-type]
            "p1",
            cascade=False,
        )
    # Parent untouched (delegation to cancel_study raised before any mutation).
    assert parent.status == "completed"


@pytest.mark.asyncio
async def test_cascade_with_cascade_false_only_cancels_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cascade=False on an in-flight parent: cancels only the parent,
    leaves children untouched."""
    parent = _build_study_with_id("p1", status="running")
    child = _build_study_with_id("c1", status="running", parent_id="p1")
    db = _MultiStudyFakeSession({"p1": parent, "c1": child})

    call_count = 0

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        nonlocal call_count
        call_count += 1
        return [child]

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    result = await study_state.cancel_study_with_chain_cascade(
        db,  # type: ignore[arg-type]
        "p1",
        cascade=False,
    )
    assert result.status == "cancelled"
    assert child.status == "running"  # child untouched
    assert call_count == 0  # list_children never called


@pytest.mark.asyncio
async def test_cascade_handles_already_cancelled_child_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a child is already cancelled (race with another cancel path),
    the cascade catches InvalidStateTransition and continues."""
    parent = _build_study_with_id("p1", status="running")
    cancelled_child = _build_study_with_id("c1", status="cancelled", parent_id="p1")
    running_grandchild = _build_study_with_id("g1", status="running", parent_id="c1")
    db = _MultiStudyFakeSession(
        {
            "p1": parent,
            "c1": cancelled_child,
            "g1": running_grandchild,
        }
    )

    async def fake_list_children(_db: Any, parent_id: str) -> list[Study]:
        if parent_id == "p1":
            return [cancelled_child]
        if parent_id == "c1":
            return [running_grandchild]
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]
    assert parent.status == "cancelled"
    assert cancelled_child.status == "cancelled"  # was already; recursed THROUGH it
    assert running_grandchild.status == "cancelled"  # reached via recursion


# ---------------------------------------------------------------------------
# bug_auto_followup_completed_parent_stop_chain_race — Option A fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_zeroes_completed_parent_depth_to_break_pending_enqueue_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop-chain race fix: when the cascade traverses a `completed` parent
    with `auto_followup_depth > 0`, it MUST zero the depth so a pending
    `enqueue_followup_study(parent_id)` Arq job — fired by the digest worker
    before the cascade ran but still sitting in the queue — observes
    SKIP_DEPTH_EXHAUSTED on its load and refuses to create a child.

    Reproduces the race deterministically without timer/thread coordination:
    we don't actually enqueue the Arq job; we assert (a) the cascade mutated
    the depth, AND (b) the chain gate, when invoked directly against the
    post-cascade parent, returns SKIP_DEPTH_EXHAUSTED — which is what the
    worker would observe."""
    # Lazy import — domain.study.auto_followup is the gate's home; the
    # production code at backend/workers/auto_followup.py:104 calls
    # evaluate_chain_gate the same way.
    from backend.app.domain.study.auto_followup import (
        ChainGateDecision,
        evaluate_chain_gate,
    )

    parent = _build_study_with_id("p1", status="completed")
    parent.config = {"max_trials": 10, "auto_followup_depth": 2}
    parent.best_metric = 0.85
    parent.baseline_metric = 0.65  # so the gate's lift branch passes pre-mutation
    db = _MultiStudyFakeSession({"p1": parent})

    # Sanity: pre-cascade, the gate would ENQUEUE if the worker fired now.
    pre_outcome = evaluate_chain_gate(parent, [])
    assert pre_outcome.decision is ChainGateDecision.ENQUEUE

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]

    assert parent.status == "completed"  # cascade leaves terminal parents alone
    assert parent.config["auto_followup_depth"] == 0  # the fix

    # Post-cascade, a pending worker's gate would short-circuit.
    post_outcome = evaluate_chain_gate(parent, [])
    assert post_outcome.decision is ChainGateDecision.SKIP_DEPTH_EXHAUSTED


@pytest.mark.asyncio
async def test_cascade_does_not_mutate_depth_when_already_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minimal-mutation guard: if `auto_followup_depth` is already 0 (the
    parent was a depth-0 leaf), the cascade doesn't touch config. Asserted
    by config-dict identity preservation so future readers can see the
    cascade left the parent's JSONB alone."""
    parent = _build_study_with_id("p1", status="completed")
    parent.config = {"max_trials": 10, "auto_followup_depth": 0}
    config_before = parent.config  # capture identity, not just value
    db = _MultiStudyFakeSession({"p1": parent})

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]

    # No reassignment → same dict instance.
    assert parent.config is config_before


@pytest.mark.asyncio
async def test_cascade_does_not_mutate_depth_on_in_flight_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-flight parents never had a pending followup-enqueue (digest only
    fires on `completed`), so the depth-zeroing fix must NOT widen its
    surface to running/queued parents. Their config stays intact; the
    cascade's existing cancel_study path handles the chain-stop."""
    parent = _build_study_with_id("p1", status="running")
    parent.config = {"max_trials": 10, "auto_followup_depth": 2}
    db = _MultiStudyFakeSession({"p1": parent})

    async def fake_list_children(_db: Any, _parent_id: str) -> list[Study]:
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    await study_state.cancel_study_with_chain_cascade(db, "p1")  # type: ignore[arg-type]

    assert parent.status == "cancelled"
    assert parent.config["auto_followup_depth"] == 2  # untouched


@pytest.mark.asyncio
async def test_cascade_zeroes_depth_recursively_on_completed_chain_intermediates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depth-3 chain where root + middle are both `completed` with
    `auto_followup_depth > 0`. Both must have their depth zeroed (each
    intermediate could have its own pending enqueue-followup job). The
    recursion at cancel_study_with_chain_cascade re-enters with each
    child as the new parent, so the mutation naturally propagates."""
    root = _build_study_with_id("R", status="completed")
    root.config = {"max_trials": 10, "auto_followup_depth": 2}
    middle = _build_study_with_id("M", status="completed", parent_id="R")
    middle.config = {"max_trials": 10, "auto_followup_depth": 1}
    leaf = _build_study_with_id("L", status="running", parent_id="M")
    leaf.config = {"max_trials": 10, "auto_followup_depth": 0}
    db = _MultiStudyFakeSession({"R": root, "M": middle, "L": leaf})

    async def fake_list_children(_db: Any, parent_id: str) -> list[Study]:
        if parent_id == "R":
            return [middle]
        if parent_id == "M":
            return [leaf]
        return []

    monkeypatch.setattr("backend.app.db.repo.list_children_of_study", fake_list_children)

    await study_state.cancel_study_with_chain_cascade(db, "R")  # type: ignore[arg-type]

    assert root.config["auto_followup_depth"] == 0
    assert middle.config["auto_followup_depth"] == 0
    assert leaf.status == "cancelled"  # in-flight leaf gets the normal cancel


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
