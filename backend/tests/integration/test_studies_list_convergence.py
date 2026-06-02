# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for studies-list ``trial_count`` + ``convergence_verdict``.

Covers ``feat_studies_convergence_visibility`` Story 1.1 — AC-1, AC-2,
AC-3, AC-3b, AC-4, AC-5 end-to-end against the live FastAPI app + the
integration-test Postgres. Mirrors the seed/insert helpers in
``test_studies_api_convergence.py`` (the detail-page sibling) so a
single fixture set proves list/detail parity (AC-2).

The bounded-query assertion (AC-5) attaches a SQLAlchemy
``before_cursor_execute`` event hook to count the queries the
batched helpers add over the previously-shipped baseline:
- M=0 page (no study with ``complete >= 50``) → 1 added query (just the
  count aggregate; no trial-load).
- M>0 page (≥1 study with ``complete >= 50``) → 2 added queries (count
  aggregate + one batched trial-load).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_engine, get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_study(
    *,
    status: str = "completed",
    direction: str | None = "maximize",
) -> tuple[str, str]:
    """Seed a minimal study chain; return ``(study_id, cluster_id)``.

    Returning the cluster_id alongside the study lets each test scope its
    list call via ``?cluster_id=`` so prior tests' fixtures cannot
    pollute its query budget (each ``_seed_study`` builds a fresh
    cluster — see the ``cv-list-cluster-`` prefix).

    ``direction=None`` writes the objective WITHOUT a direction key (the
    default-maximize backward-compat path); pass an explicit non-Literal
    string (e.g. ``"sideways"``) for the invalid-direction parity case.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-list-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-list-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-list-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cv-list-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        objective: dict[str, Any] = {"metric": "ndcg", "k": 10}
        if direction is not None:
            objective["direction"] = direction
        study_id = str(uuid.uuid4())
        await repo.create_study(
            db,
            id=study_id,
            name=f"cv-list-study-{uuid.uuid4().hex[:8]}",
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
    return study_id, cluster.id


async def _insert_complete_trials(
    *,
    study_id: str,
    count: int,
    primary_metric: float = 0.5,
) -> None:
    """Insert ``count`` complete non-baseline Optuna trials, ascending numbers."""
    factory = get_session_factory()
    async with factory() as db:
        for i in range(count):
            await repo.create_trial(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                optuna_trial_number=i,
                status="complete",
                params={},
                metrics={},
                primary_metric=primary_metric,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                duration_ms=100,
            )
        await db.commit()


async def _find_study(async_client: httpx.AsyncClient, study_id: str) -> dict[str, Any]:
    """Find one study by id in the list response (paginating if needed)."""
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = await async_client.get("/api/v1/studies", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for item in body["data"]:
            if item["id"] == study_id:
                return item
        if not body.get("has_more"):
            raise AssertionError(f"study {study_id} not found in list response")
        cursor = body["next_cursor"]


# ---------------------------------------------------------------------------
# AC-1: trial_count
# ---------------------------------------------------------------------------


async def test_ac1_trial_count_matches_non_baseline_total(
    async_client: httpx.AsyncClient,
) -> None:
    """A completed study with N non-baseline trials shows ``trial_count == N``."""
    study_id, _cluster_id = await _seed_study(status="completed")
    await _insert_complete_trials(study_id=study_id, count=12)
    item = await _find_study(async_client, study_id)
    assert item["trial_count"] == 12


# ---------------------------------------------------------------------------
# AC-3: count-gated verdict for 5–49 trials
# ---------------------------------------------------------------------------


async def test_ac3_5_to_49_complete_returns_too_few_trials(
    async_client: httpx.AsyncClient,
) -> None:
    study_id, _cluster_id = await _seed_study(status="completed")
    await _insert_complete_trials(study_id=study_id, count=12)
    item = await _find_study(async_client, study_id)
    assert item["convergence_verdict"] == "too_few_trials"


async def test_below_5_complete_returns_null_verdict(
    async_client: httpx.AsyncClient,
) -> None:
    study_id, _cluster_id = await _seed_study(status="completed")
    await _insert_complete_trials(study_id=study_id, count=3)
    item = await _find_study(async_client, study_id)
    assert item["convergence_verdict"] is None


# ---------------------------------------------------------------------------
# AC-4: in-flight short-circuit
# ---------------------------------------------------------------------------


async def test_ac4_running_with_many_trials_returns_null(
    async_client: httpx.AsyncClient,
) -> None:
    study_id, _cluster_id = await _seed_study(status="running")
    # 60 complete trials — would classify if not for the in-flight gate.
    await _insert_complete_trials(study_id=study_id, count=60)
    item = await _find_study(async_client, study_id)
    assert item["convergence_verdict"] is None


# ---------------------------------------------------------------------------
# AC-3b: invalid-direction parity (gate before count)
# ---------------------------------------------------------------------------


async def test_ac3b_invalid_direction_at_30_trials_yields_null(
    async_client: httpx.AsyncClient,
) -> None:
    """Invalid direction with 30 trials → list and detail both null."""
    study_id, _cluster_id = await _seed_study(status="completed", direction="sideways")
    await _insert_complete_trials(study_id=study_id, count=30)

    list_item = await _find_study(async_client, study_id)
    assert list_item["convergence_verdict"] is None

    detail = await async_client.get(f"/api/v1/studies/{study_id}")
    assert detail.status_code == 200
    assert detail.json()["convergence"] is None


# ---------------------------------------------------------------------------
# AC-2: list verdict matches detail verdict
# ---------------------------------------------------------------------------


async def test_ac2_list_verdict_equals_detail_verdict_for_classifier_path(
    async_client: httpx.AsyncClient,
) -> None:
    """A 60-trial completed study reaches gate-4; list & detail must agree."""
    study_id, _cluster_id = await _seed_study(status="completed")
    # 60 monotonically rising trials -> still_improving (well above epsilon).
    factory = get_session_factory()
    async with factory() as db:
        for i in range(60):
            await repo.create_trial(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                optuna_trial_number=i,
                status="complete",
                params={},
                metrics={},
                primary_metric=0.5 + 0.005 * i,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                duration_ms=100,
            )
        await db.commit()

    list_item = await _find_study(async_client, study_id)
    detail = await async_client.get(f"/api/v1/studies/{study_id}")
    assert detail.status_code == 200
    assert list_item["convergence_verdict"] == detail.json()["convergence"]["verdict"]


# ---------------------------------------------------------------------------
# AC-5: bounded-query budget — M=0 → 1 added query; M>0 → 2 added queries.
# ---------------------------------------------------------------------------


def _capture_query_count(target_substrings: tuple[str, ...]) -> tuple[list[str], Any]:
    """Build a SQLAlchemy event hook that captures queries matching any substring.

    Returns ``(captured, hook)`` — ``captured`` is mutated as queries fire,
    ``hook`` is the function the caller attaches/removes from the engine's
    ``before_cursor_execute`` event.
    """
    captured: list[str] = []

    def _hook(_conn: Any, _cursor: Any, statement: str, *_args: Any, **_kw: Any) -> None:
        for needle in target_substrings:
            if needle in statement:
                captured.append(statement)
                break

    return captured, _hook


async def test_ac5_bounded_queries_m_zero_and_m_positive(
    async_client: httpx.AsyncClient,
) -> None:
    """The bounded-query budget: M=0 → 1 added query (count only); M>0 → 2 added queries.

    Wires a SQLAlchemy ``before_cursor_execute`` hook on the engine's
    sync_engine to count exactly the two added queries our resolver
    issues. Distinguishes them by inspecting the statement text:
    - count aggregate → contains the ``GROUP BY trials.study_id`` clause
    - batched trial load → ``SELECT trials.* ... WHERE trials.study_id IN``
      with ``status = 'complete'`` and ``is_baseline IS NOT TRUE``.
    """
    from sqlalchemy import event

    # M=0 setup: one completed study with only 12 trials (count-gate path).
    # Each _seed_study creates a fresh cluster; we scope the list call to
    # that cluster_id so prior tests' 60-trial fixtures (e.g. AC-2) cannot
    # pollute this test's query budget. Without scoping, the M=0 page
    # would also include any >=50-trial study seeded earlier in the run,
    # turning the M=0 case into an unintended M>0 case.
    m0_study_id, m0_cluster_id = await _seed_study(status="completed")
    await _insert_complete_trials(study_id=m0_study_id, count=12)

    engine = get_engine()
    # Discriminators (mutually exclusive):
    # - count aggregate: has ``GROUP BY trials.study_id`` (no ORDER BY).
    # - batched trial-load: has ``ORDER BY trials.study_id, trials.optuna_trial_number``
    #   (the only emitter of that exact two-column ORDER BY).
    # A bare ``trials.study_id IN`` substring would match BOTH queries —
    # the count's WHERE clause also has the IN-list. Discriminate on the
    # ORDER BY instead.
    count_q, count_hook = _capture_query_count(("GROUP BY trials.study_id",))
    load_q, load_hook = _capture_query_count(
        ("ORDER BY trials.study_id, trials.optuna_trial_number",)
    )

    event.listen(engine.sync_engine, "before_cursor_execute", count_hook)
    event.listen(engine.sync_engine, "before_cursor_execute", load_hook)
    try:
        # M=0 page (scoped to m0_cluster_id): count_q should rise by 1,
        # load_q should stay at 0 (the 12-trial study is below the 50-floor).
        baseline_count = len(count_q)
        baseline_load = len(load_q)
        resp = await async_client.get(
            "/api/v1/studies",
            params={"limit": 200, "cluster_id": m0_cluster_id},
        )
        assert resp.status_code == 200, resp.text
        m0_count_added = len(count_q) - baseline_count
        m0_load_added = len(load_q) - baseline_load
        assert m0_count_added == 1, f"M=0 expected exactly 1 count aggregate; got {m0_count_added}"
        assert m0_load_added == 0, (
            f"M=0 must NOT trigger the batched trial-load; got {m0_load_added}"
        )

        # M>0 setup: a fresh cluster with a single 60-trial study; scoped
        # list call sees exactly that study, so the resolver hits the
        # ``complete >= 50`` subset → 1 count aggregate + 1 batched
        # trial-load (still bounded regardless of how many such studies
        # would be on the page).
        m1_study_id, m1_cluster_id = await _seed_study(status="completed")
        await _insert_complete_trials(study_id=m1_study_id, count=60)

        baseline_count = len(count_q)
        baseline_load = len(load_q)
        resp = await async_client.get(
            "/api/v1/studies",
            params={"limit": 200, "cluster_id": m1_cluster_id},
        )
        assert resp.status_code == 200, resp.text
        m1_count_added = len(count_q) - baseline_count
        m1_load_added = len(load_q) - baseline_load
        assert m1_count_added == 1, f"M>0 expected exactly 1 count aggregate; got {m1_count_added}"
        assert m1_load_added == 1, f"M>0 expected exactly 1 batched trial-load; got {m1_load_added}"
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_hook)
        event.remove(engine.sync_engine, "before_cursor_execute", load_hook)
