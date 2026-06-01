# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``fetch_study_convergence`` (Story 2.2).

Exercises the async service against the live test Postgres. Covers the 6
scenarios in plan Story 2.2 DoD:

* completed study + ≥50 converged trials → shape with ``verdict="converged"``
* running study + 80 complete trials → ``None`` (classifier NOT invoked)
* completed study + 4 complete trials → ``None`` (sub-MIN)
* baseline-filter invariant — baseline row never appears in the curve
* minimize direction → ``verdict="converged"`` with non-increasing curve
* invalid ``direction`` → ``None`` + ``convergence_invalid_direction`` WARN

The classifier-exception path (return None, GET still 200) is asserted
end-to-end in the contract test added by Story 3.1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.db.session import get_session_factory
from backend.app.services.study_convergence import (
    _resolve_direction,
    fetch_study_convergence,
)
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


# ---------------------------------------------------------------------------
# Seeding helpers — shaped like test_studies_api_confidence.py
# ---------------------------------------------------------------------------


async def _seed_study(
    *,
    status: str = "completed",
    objective: dict[str, Any] | None = None,
) -> str:
    """Seed a minimal study chain and return its id.

    The orchestrator's foreign keys (cluster, template, query_set, jl) are
    fully populated so the study row passes its CHECK constraints. Trials
    are inserted separately via :func:`_insert_trial` so each test
    controls its own trial shape.
    """
    if objective is None:
        objective = {"metric": "ndcg", "k": 10, "direction": "maximize"}
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        study_id = str(uuid.uuid4())
        await repo.create_study(
            db,
            id=study_id,
            name=f"cv-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective=objective,
            config={"max_trials": 1000},
            status=status,
            optuna_study_name=study_id,
        )
        await db.commit()
    return study_id


async def _insert_trial(
    *,
    study_id: str,
    optuna_trial_number: int,
    primary_metric: float | None,
    status: str = "complete",
    is_baseline: bool = False,
) -> None:
    """Insert one trial row directly."""
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_trial(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
            status=status,
            params={},
            metrics={},
            primary_metric=primary_metric,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
            is_baseline=is_baseline,
        )
        await db.commit()


async def _get_study_row(db: AsyncSession, study_id: str) -> Study:
    """Return the freshly-loaded ``Study`` ORM row."""
    row = await db.get(Study, study_id)
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# _resolve_direction — pure unit-shaped tests (no DB)
# ---------------------------------------------------------------------------


class TestResolveDirection:
    def test_explicit_maximize(self) -> None:
        assert _resolve_direction({"direction": "maximize"}) == "maximize"

    def test_explicit_minimize(self) -> None:
        assert _resolve_direction({"direction": "minimize"}) == "minimize"

    def test_missing_key_defaults_to_maximize(self) -> None:
        assert _resolve_direction({"metric": "ndcg"}) == "maximize"

    def test_none_objective_defaults_to_maximize(self) -> None:
        assert _resolve_direction(None) == "maximize"

    def test_invalid_string_returns_none(self) -> None:
        assert _resolve_direction({"direction": "max"}) is None
        assert _resolve_direction({"direction": "MAXIMIZE"}) is None
        assert _resolve_direction({"direction": ""}) is None


# ---------------------------------------------------------------------------
# DB-backed integration scenarios
# ---------------------------------------------------------------------------


async def test_completed_converged_study_returns_shape() -> None:
    study_id = await _seed_study(status="completed")
    # 275 trials: climb 0..0.5 in the first 30%, then plateau → converged.
    for i in range(275):
        metric = 0.5 if i >= 82 else 0.5 * (i / 82)
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=metric)
    factory = get_session_factory()
    async with factory() as db:
        row = await _get_study_row(db, study_id)
        shape = await fetch_study_convergence(db, row)
    assert shape is not None
    assert shape.verdict == "converged"
    assert shape.direction == "maximize"
    assert shape.total_complete_trials == 275


async def test_running_study_short_circuits_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    study_id = await _seed_study(status="running")
    # 80 complete trials — plenty for a verdict, but the in-flight gate
    # must fire FIRST.
    for i in range(80):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)

    classifier_invocations: list[int] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        classifier_invocations.append(1)
        raise AssertionError("classifier must NOT be invoked on running studies")

    monkeypatch.setattr("backend.app.services.study_convergence.classify_convergence", spy)

    factory = get_session_factory()
    async with factory() as db:
        row = await _get_study_row(db, study_id)
        shape = await fetch_study_convergence(db, row)
    assert shape is None
    assert classifier_invocations == []


async def test_sub_min_complete_returns_none() -> None:
    study_id = await _seed_study(status="completed")
    # 4 complete trials — below CONVERGENCE_FLAT_MIN_COMPLETE (5).
    for i in range(4):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)
    factory = get_session_factory()
    async with factory() as db:
        row = await _get_study_row(db, study_id)
        shape = await fetch_study_convergence(db, row)
    assert shape is None


async def test_baseline_row_excluded_from_curve() -> None:
    study_id = await _seed_study(status="completed")
    # 50 usable Optuna trials.
    for i in range(50):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)
    # 1 baseline at optuna_trial_number=-1 — must be excluded.
    await _insert_trial(
        study_id=study_id,
        optuna_trial_number=-1,
        primary_metric=99.0,
        is_baseline=True,
    )
    factory = get_session_factory()
    async with factory() as db:
        row = await _get_study_row(db, study_id)
        shape = await fetch_study_convergence(db, row)
    assert shape is not None
    assert shape.total_complete_trials == 50
    # No CurvePoint should reference the baseline sentinel.
    assert all(p.trial_number != -1 for p in shape.best_so_far_curve)


async def test_minimize_direction_converged() -> None:
    study_id = await _seed_study(
        status="completed",
        objective={"metric": "ndcg", "k": 10, "direction": "minimize"},
    )
    # 200 trials: drop 1.0 → 0.5 in first 30%, then plateau → minimize-converged.
    for i in range(200):
        metric = 0.5 if i >= 60 else 1.0 - 0.5 * (i / 60)
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=metric)
    factory = get_session_factory()
    async with factory() as db:
        row = await _get_study_row(db, study_id)
        shape = await fetch_study_convergence(db, row)
    assert shape is not None
    assert shape.direction == "minimize"
    assert shape.verdict == "converged"
    # Best-so-far curve must be non-increasing for minimize.
    import itertools

    values = [p.best_so_far for p in shape.best_so_far_curve]
    assert all(prev >= curr for prev, curr in itertools.pairwise(values))


async def test_invalid_direction_warns_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_id = await _seed_study(
        status="completed",
        objective={"metric": "ndcg", "k": 10, "direction": "max"},
    )
    # 60 complete trials — plenty for a verdict, BUT the invalid direction
    # must short-circuit before the classifier runs.
    for i in range(60):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)

    classifier_invocations: list[int] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        classifier_invocations.append(1)
        raise AssertionError("classifier must NOT be invoked on invalid direction")

    monkeypatch.setattr("backend.app.services.study_convergence.classify_convergence", spy)

    # RelyLoop's structlog config writes through its own ConsoleRenderer
    # (not stdlib logging), so caplog can't observe these. Use the
    # canonical ``structlog.testing.capture_logs`` context manager which
    # intercepts at the structlog layer regardless of the wrapped logger.
    with structlog.testing.capture_logs() as cap:
        factory = get_session_factory()
        async with factory() as db:
            row = await _get_study_row(db, study_id)
            shape = await fetch_study_convergence(db, row)
    assert shape is None
    assert classifier_invocations == []
    warn_events = [r for r in cap if r.get("event") == "convergence_invalid_direction"]
    assert warn_events, (
        f"expected convergence_invalid_direction WARN; saw events={[r.get('event') for r in cap]}"
    )
    # WARN payload carries the raw direction value verbatim.
    assert warn_events[0].get("raw_direction") == "max"
    assert warn_events[0].get("log_level") == "warning"


async def test_classifier_exception_warns_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the pure classifier raises, the aggregator must catch + WARN."""

    study_id = await _seed_study(status="completed")
    for i in range(60):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("synthetic classifier failure")

    monkeypatch.setattr("backend.app.services.study_convergence.classify_convergence", boom)

    with structlog.testing.capture_logs() as cap:
        factory = get_session_factory()
        async with factory() as db:
            row = await _get_study_row(db, study_id)
            shape = await fetch_study_convergence(db, row)
    assert shape is None
    warn_events = [r for r in cap if r.get("event") == "convergence_classifier_exception"]
    seen_events = [r.get("event") for r in cap]
    assert warn_events, f"expected convergence_classifier_exception WARN; saw events={seen_events}"
    assert warn_events[0].get("exception_type") == "ValueError"
    assert warn_events[0].get("exception_str") == "synthetic classifier failure"
