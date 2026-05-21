"""End-to-end integration test for the ``open_pr`` worker's confidence plumbing.

Story 1.5 / FR-5d: prove that the worker's call site fetches confidence
via :func:`fetch_study_confidence` and threads it into
:func:`_render_pr_body_study_backed` so the ``## Confidence`` section
lands in the rendered PR body. The full 15-step worker contract (lock,
clone, push, GitHub POST) is exercised by the existing
``feat_github_pr_worker`` integration suite — this test focuses on the
new confidence data plumbing without re-running those steps.

We drive the real DB (live session via the integration-test Postgres)
plus the live :func:`fetch_study_confidence` service helper, then feed
the resulting shape into the real :func:`_render_pr_body_study_backed`
renderer. Both functions are imported from production code; only the
git / GitHub side effects are bypassed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.services.study_confidence import fetch_study_confidence
from backend.tests.conftest import postgres_reachable
from backend.workers.git_pr import _render_pr_body_study_backed

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_completed_study_with_per_query_metrics(
    *,
    n_queries: int = 8,
    n_total_trials: int = 12,
) -> dict[str, Any]:
    """Seed a completed study with per_query_metrics populated on the
    winner trial + runner-up trial. Returns ids + the study row.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(n_queries):
            qid = str(uuid.uuid4())
            await repo.create_query(
                db,
                id=qid,
                query_set_id=query_set.id,
                query_text=f"sample query {i}",
            )
            query_ids.append(qid)
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-jl-{uuid.uuid4().hex[:8]}",
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
            name="pr-confidence-study",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": n_total_trials},
            status="completed",
            failed_reason=None,
            optuna_study_name=study_id,
            baseline_metric=None,
            best_metric=0.840,
            best_trial_id=None,
        )
        # Winner trial — high per-query metrics + 1 designed regressor.
        winner_per_query = {
            qid: {"ndcg": 0.85 - (0.01 * i) if i != 0 else 0.40} for i, qid in enumerate(query_ids)
        }
        # Runner-up trial — qid 0 scored higher (so winner regresses on it).
        runner_up_per_query = {
            qid: {"ndcg": 0.95 if i == 0 else 0.84 - (0.01 * i)} for i, qid in enumerate(query_ids)
        }
        # Trial 0 = winner.
        winner_trial = await repo.create_trial(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            optuna_trial_number=0,
            status="complete",
            params={},
            metrics={},
            primary_metric=0.840,
            per_query_metrics=winner_per_query,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
        )
        # Trial 1 = runner-up.
        await repo.create_trial(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            optuna_trial_number=1,
            status="complete",
            params={},
            metrics={},
            primary_metric=0.830,
            per_query_metrics=runner_up_per_query,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
        )
        # Remaining filler trials with monotonically decreasing primary_metric
        # so noise-floor + convergence + runner-up gap signals all populate.
        for i in range(2, n_total_trials):
            await repo.create_trial(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                optuna_trial_number=i,
                status="complete",
                params={},
                metrics={},
                primary_metric=0.83 - (0.01 * i),
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                duration_ms=100,
            )
        # Patch best_trial_id post-trial-create.
        from backend.app.db.models import Study as _Study

        study_row = await db.get(_Study, study_id)
        assert study_row is not None
        study_row.best_trial_id = winner_trial.id
        await db.flush()
        await db.commit()
    return {
        "study_id": study_id,
        "cluster_id": cluster.id,
        "winner_trial_id": winner_trial.id,
        "regressing_qid": query_ids[0],
    }


async def test_open_pr_worker_plumbing_renders_confidence_section() -> None:
    """End-to-end: seed → fetch_study_confidence → renderer outputs ## Confidence.

    Mirrors the production call-site logic in
    :func:`backend.workers.git_pr.open_pr` (lines ~898-915) for the
    study-backed branch: fetch the study, fetch confidence, render the
    body. Bypasses the lock + clone + push + GitHub POST steps because
    those are covered by the existing ``feat_github_pr_worker`` suite —
    Story 1.5's FR-5d is specifically about the data-plumbing slice.
    """
    ctx = await _seed_completed_study_with_per_query_metrics()
    factory = get_session_factory()
    async with factory() as db:
        study = await repo.get_study(db, ctx["study_id"])
        assert study is not None
        confidence = await fetch_study_confidence(db, study)

    assert confidence is not None
    # Confidence assembled from the seed: 8 queries → bootstrap CI populates;
    # ≥10 complete trials → late-trial 1σ populates; ≥3 → convergence; ≥2
    # → runner-up gap; both winner + runner-up have per_query → outcomes.
    assert confidence.ci_95 is not None
    assert confidence.runner_up_gap is not None
    assert confidence.late_trial_stddev is not None
    assert confidence.convergence is not None
    assert confidence.per_query_outcomes is not None
    assert confidence.per_query_outcomes.regressed >= 1
    # The designed regressor (qid 0) must appear among top_regressors.
    regressor_qids = {row.query_id for row in confidence.per_query_outcomes.top_regressors}
    assert ctx["regressing_qid"] in regressor_qids

    # Now run the real renderer with the real study object + the real
    # confidence shape. Mirrors what the production worker does at
    # git_pr.py:904.
    proposal = SimpleNamespace(
        metric_delta={
            "ndcg@10": {"baseline": 0.612, "achieved": 0.840, "delta_pct": 37.3},
        },
        config_diff={"k1": {"from": 1.2, "to": 1.4}},
    )
    digest = SimpleNamespace(suggested_followups=["Try BM25 k1=1.4"])
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=proposal.config_diff,
        chart_md="",
        base_url="https://relyloop.acme.internal",
        confidence=confidence,
    )

    # The ## Confidence section landed between ## Metric delta and ## Config diff.
    metric_idx = body.index("## Metric delta")
    conf_idx = body.index("## Confidence")
    config_idx = body.index("## Config diff")
    assert metric_idx < conf_idx < config_idx
    # CI line + N(queries) reflect the seeded data.
    assert "95% CI" in body
    assert "N=8 queries" in body
    # Per-query line + regressor block populate.
    assert "vs runner_up" in body
    assert "Queries that regressed:" in body
    # The named regressor's text appears verbatim.
    assert "sample query 0" in body
