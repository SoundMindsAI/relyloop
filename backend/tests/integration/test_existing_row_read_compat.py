"""Existing-row read compatibility regression for infra_ir_measures_migration.

Per spec AC-12 + plan cycle-1 F9: inserts a synthetic ``Trial`` row whose
``metrics`` and ``per_query_metrics`` JSONB columns are keyed exactly the
way production rows are keyed today (user-facing tokens: ``ndcg@10``,
``map@10``, ``map``, ``mrr``, etc.). Then exercises every downstream
consumer (``fetch_study_confidence``, the trial-list API serialization,
the digest worker's top-trials read pattern) and asserts each one
hydrates the pre-migration shape without raising.

This is the load-bearing test for the "no-migration / no-backfill" claim
in the feature spec — proves the migration preserves byte-identical
read compatibility for every persisted trial that already exists in
production.

Skips automatically when Postgres isn't reachable from the host shell.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from backend.app.db import repo
from backend.app.db.models import Study, Trial
from backend.app.db.session import get_session_factory
from backend.app.services.study_confidence import fetch_study_confidence
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_study_for_compat() -> tuple[str, list[str]]:
    """Seed a minimal study chain pinned to objective metric=ndcg, k=10.

    Returns ``(study_id, query_ids)``. Best-trial linkage is set by the
    test once the trial row is inserted.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"compat-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"compat-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"compat-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        # Seed enough queries for the per_query dict to point at real query
        # rows (the confidence orchestrator's Q4 join needs query_text for
        # named regressors).
        query_ids: list[str] = []
        for i in range(6):
            qid = str(uuid.uuid4())
            await repo.create_query(
                db,
                id=qid,
                query_set_id=query_set.id,
                query_text=f"compat-q-{i}",
            )
            query_ids.append(qid)
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"compat-jl-{uuid.uuid4().hex[:8]}",
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
            name=f"compat-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 100},
            status="completed",
            failed_reason=None,
            optuna_study_name=study_id,
            baseline_metric=None,
            best_metric=0.82,
            best_trial_id=None,
        )
        await db.commit()
        return study_id, query_ids


async def _insert_trial_with_pre_migration_shape(
    *,
    study_id: str,
    query_ids: list[str],
    primary_metric: float,
    optuna_trial_number: int,
) -> str:
    """Insert one trial whose JSONB is shaped exactly like a production row.

    The metrics/per_query_metrics keys are user-facing tokens (``ndcg@10``,
    ``map@10``, ``map``, ``mrr``) — the same shape ``score()`` has been
    emitting since infra_optuna_eval shipped. The test asserts every
    consumer hydrates this shape without raising post-migration.
    """
    factory = get_session_factory()
    async with factory() as db:
        trial_id = str(uuid.uuid4())
        await repo.create_trial(
            db,
            id=trial_id,
            study_id=study_id,
            optuna_trial_number=optuna_trial_number,
            params={"title.boost": 2.5},
            primary_metric=primary_metric,
            metrics={
                # Pre-migration JSONB shape: user-facing tokens only.
                "ndcg@10": primary_metric,
                "map@10": 0.71,
                "map": 0.65,
                "mrr": 0.91,
                "precision@10": 0.55,
                "recall@10": 0.62,
            },
            per_query_metrics={
                # 6 queries; needs ≥ BOOTSTRAP_MIN_N_QUERIES=5 for ci_95.
                query_ids[0]: {
                    "ndcg@10": 0.83,
                    "map@10": 0.70,
                    "map": 0.66,
                    "mrr": 1.00,
                },
                query_ids[1]: {
                    "ndcg@10": 0.81,
                    "map@10": 0.72,
                    "map": 0.65,
                    "mrr": 0.83,
                },
                query_ids[2]: {
                    "ndcg@10": 0.85,
                    "map@10": 0.74,
                    "map": 0.67,
                    "mrr": 1.00,
                },
                query_ids[3]: {
                    "ndcg@10": 0.79,
                    "map@10": 0.68,
                    "map": 0.62,
                    "mrr": 0.50,
                },
                query_ids[4]: {
                    "ndcg@10": 0.84,
                    "map@10": 0.73,
                    "map": 0.66,
                    "mrr": 1.00,
                },
                query_ids[5]: {
                    "ndcg@10": 0.80,
                    "map@10": 0.69,
                    "map": 0.63,
                    "mrr": 0.50,
                },
            },
            duration_ms=1200,
            status="complete",
            error=None,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )
        await db.commit()
    return trial_id


async def _set_best_trial(study_id: str, trial_id: str) -> None:
    """Patch ``studies.best_trial_id`` post-hoc."""
    factory = get_session_factory()
    async with factory() as db:
        row = await db.get(Study, study_id)
        assert row is not None
        row.best_trial_id = trial_id
        await db.flush()
        await db.commit()


async def test_existing_row_read_compat_ac12(async_client: httpx.AsyncClient) -> None:
    """AC-12: pre-migration JSONB shape hydrates every consumer post-migration.

    Exercises three independent read paths against the same pre-migration row:
      1. ``fetch_study_confidence`` (via ``GET /api/v1/studies/{id}.confidence``)
      2. The trial-list endpoint's JSONB serialization
      3. The digest worker's top-trials selection (read pattern simulated
         directly via SQLAlchemy — exercises the same shape without booting
         the worker process)

    None of the three may raise; all three must return non-None data
    sourced from the synthetic pre-migration trial.
    """
    study_id, query_ids = await _seed_study_for_compat()
    trial_id = await _insert_trial_with_pre_migration_shape(
        study_id=study_id,
        query_ids=query_ids,
        primary_metric=0.82,
        optuna_trial_number=5,
    )
    # Add 4 more trials so convergence + runner-up + late-stddev signals
    # populate (BOOTSTRAP / CONVERGENCE / LATE_TRIAL minimums need ≥ 5
    # complete trials). Pre-migration shape used throughout.
    for i, m in enumerate([0.78, 0.75, 0.72, 0.70], start=6):
        await _insert_trial_with_pre_migration_shape(
            study_id=study_id,
            query_ids=query_ids,
            primary_metric=m,
            optuna_trial_number=i,
        )
    await _set_best_trial(study_id, trial_id)

    # --- (1a) Confidence orchestrator via the StudyDetail endpoint ----------
    resp = await async_client.get(f"/api/v1/studies/{study_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    confidence = body.get("confidence")
    assert confidence is not None, (
        "AC-12 (1a): pre-migration JSONB row failed to hydrate ConfidenceShape — confidence is None"
    )
    # The headline mirrors study.best_metric (0.82).
    assert confidence["headline"]["value"] == pytest.approx(0.82, abs=1e-6)
    # n_queries comes from the winner's per_query_metrics dict → 6.
    assert confidence["headline"]["n_queries"] == 6
    # CI populates from the per_query values for ndcg@10.
    assert confidence["ci_95"] is not None, (
        "AC-12 (1a): CI should populate from per_query when ≥ 5 datapoints exist"
    )
    assert confidence["ci_95"]["n_samples"] == 6

    # --- (1b) Confidence orchestrator called DIRECTLY (per phase-gate F5) ---
    # Exercises the service-layer function on its own — not just via the API
    # endpoint — so the function-level contract is independently asserted.
    factory = get_session_factory()
    async with factory() as db:
        study_row = await db.get(Study, study_id)
        assert study_row is not None
        direct_shape = await fetch_study_confidence(db, study_row)
    assert direct_shape is not None, (
        "AC-12 (1b): fetch_study_confidence returned None for a pre-migration JSONB row"
    )
    assert direct_shape.headline.value == pytest.approx(0.82, abs=1e-6)
    assert direct_shape.headline.n_queries == 6
    assert direct_shape.ci_95 is not None
    assert direct_shape.ci_95.n_samples == 6

    # --- (2) Trial-list endpoint serializes the JSONB through unchanged ----
    # TrialListResponse uses `data` for the list field (verified against
    # backend/app/api/v1/schemas.py::TrialListResponse).
    list_resp = await async_client.get(f"/api/v1/studies/{study_id}/trials")
    assert list_resp.status_code == 200, list_resp.text
    trials_payload = list_resp.json()["data"]
    assert any(t["id"] == trial_id for t in trials_payload), (
        f"AC-12 (2): inserted trial {trial_id!r} missing from trial-list response"
    )
    # Find the inserted trial in the response; its metrics dict must be the
    # exact pre-migration shape (user-facing tokens) we wrote.
    winner_row = next(t for t in trials_payload if t["id"] == trial_id)
    expected_keys = {"ndcg@10", "map@10", "map", "mrr", "precision@10", "recall@10"}
    assert set(winner_row["metrics"].keys()) == expected_keys, (
        f"AC-12 (2): trial-list response key drift; "
        f"got={sorted(winner_row['metrics'].keys())!r}, expected={sorted(expected_keys)!r}"
    )

    # --- (3) Digest worker top-trials read pattern -------------------------
    # The digest worker (backend/workers/digest.py:632) reads complete trials
    # ordered by primary_metric DESC. Simulate the same SELECT directly to
    # prove the JSONB column can be read back without raising.
    async with factory() as db:
        stmt = (
            select(Trial)
            .where(Trial.study_id == study_id, Trial.status == "complete")
            .order_by(Trial.primary_metric.desc())
        )
        top_trials = list((await db.execute(stmt)).scalars().all())
    assert top_trials, "AC-12 (3): top-trials SELECT returned zero rows"
    assert top_trials[0].id == trial_id, (
        f"AC-12 (3): top-trial ordering broken; expected {trial_id!r}, got {top_trials[0].id!r}"
    )
    # The .metrics JSONB read back through SQLAlchemy must be the same dict
    # we wrote — round-trip clean.
    assert top_trials[0].metrics["ndcg@10"] == pytest.approx(0.82, abs=1e-6)
    assert top_trials[0].per_query_metrics is not None
    assert set(top_trials[0].per_query_metrics.keys()) == set(query_ids)
