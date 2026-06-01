# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``StudyDetail.convergence`` (Story 3.1).

Covers AC-8 / AC-9 / AC-10 end-to-end against the live FastAPI app +
integration-test Postgres. The classifier itself is unit-tested in
``backend/tests/unit/domain/study/test_convergence.py`` and the async
service in ``backend/tests/integration/test_study_convergence_integration.py``;
this suite proves ``_detail()`` threads the field correctly through the
GET response AND the cancel response.

AC-8 — completed study with ≥50 converged trials → GET returns
``convergence.verdict == "converged"`` with a full best-so-far curve.
AC-9 — running study → GET returns ``convergence: null`` (the in-flight
short-circuit fires before the classifier).
AC-10 — running → cancelled transition → POST cancel response carries
a populated ``convergence`` (since after cancellation the study is
terminal).
AC-classifier-exception — when the classifier raises mid-request, the
GET still returns 200 with ``convergence: null`` (never 500).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_study(*, status: str = "completed") -> str:
    """Seed a minimal study chain; return its id."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-api-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-api-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-api-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-api-jl-{uuid.uuid4().hex[:8]}",
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
            name=f"cv-api-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 1000},
            status=status,
            optuna_study_name=study_id,
        )
        await db.commit()
    return study_id


async def _insert_trial(
    *, study_id: str, optuna_trial_number: int, primary_metric: float | None
) -> None:
    """Insert one complete Optuna trial."""
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_trial(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
            status="complete",
            params={},
            metrics={},
            primary_metric=primary_metric,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
        )
        await db.commit()


async def test_ac8_completed_converged_study_returns_full_shape(
    async_client: httpx.AsyncClient,
) -> None:
    """A 275-trial converged study returns verdict='converged' + 275-point curve."""

    study_id = await _seed_study(status="completed")
    for i in range(275):
        metric = 0.5 if i >= 82 else 0.5 * (i / 82)
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=metric)
    resp = await async_client.get(f"/api/v1/studies/{study_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    convergence = body.get("convergence")
    assert convergence is not None, "convergence must be populated"
    assert convergence["verdict"] == "converged"
    assert convergence["direction"] == "maximize"
    assert convergence["total_complete_trials"] == 275
    assert convergence["window_size"] == 20
    assert convergence["warmup_floor"] == 50
    assert convergence["epsilon"] == pytest.approx(0.005)
    curve = convergence["best_so_far_curve"]
    assert isinstance(curve, list) and len(curve) == 275
    assert all("trial_number" in p and "best_so_far" in p for p in curve)


async def test_ac9_running_study_returns_null_convergence(
    async_client: httpx.AsyncClient,
) -> None:
    """Running studies short-circuit; the API surfaces convergence: null."""

    study_id = await _seed_study(status="running")
    # 80 complete trials — plenty for a verdict, but in-flight gate wins.
    for i in range(80):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)
    resp = await async_client.get(f"/api/v1/studies/{study_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["convergence"] is None


async def test_ac10_cancel_transition_populates_convergence(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /studies/{id}/cancel on a running study returns the populated
    detail body; the now-terminal study carries a non-null convergence."""

    study_id = await _seed_study(status="running")
    # 80 complete trials — enough to clear the warmup floor (50). The cancel
    # response should reflect the freshly-terminal study's verdict.
    for i in range(80):
        # 80 trials with monotonic gain → still_improving (well above eps).
        await _insert_trial(
            study_id=study_id,
            optuna_trial_number=i,
            primary_metric=0.5 + 0.005 * i,
        )
    resp = await async_client.post(f"/api/v1/studies/{study_id}/cancel")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    # Convergence should be populated (study is now terminal — in-flight gate
    # passes; classifier runs against the seeded trials).
    convergence = body.get("convergence")
    assert convergence is not None, "cancel response should carry convergence"
    assert convergence["verdict"] in ("converged", "still_improving", "too_few_trials")


async def test_classifier_exception_keeps_get_status_200(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising classifier must not crash GET; response is 200 with null."""

    study_id = await _seed_study(status="completed")
    for i in range(60):
        await _insert_trial(study_id=study_id, optuna_trial_number=i, primary_metric=0.5)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic classifier crash")

    monkeypatch.setattr("backend.app.services.study_convergence.classify_convergence", boom)

    resp = await async_client.get(f"/api/v1/studies/{study_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["convergence"] is None
