# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``StudyDetail.confidence`` (feat_pr_metric_confidence Story 1.4).

Covers AC-3, AC-3a, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-15, AC-16
end-to-end against the live FastAPI app + integration-test Postgres. The
shape itself is unit-tested in
``backend/tests/unit/domain/study/test_confidence.py`` (Story 1.3); this
suite proves the 4-query read pattern + ``_detail()`` wiring assemble the
shape correctly off a real DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
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


async def _seed_study(
    *,
    objective: dict[str, Any] | None = None,
    best_metric: float | None = 0.84,
    seed_queries: int = 0,
) -> dict[str, Any]:
    """Seed a minimal study chain. Returns ids + the chain handles.

    No trials inserted — the caller adds trials via :func:`_insert_trial`
    and then patches ``study.best_trial_id`` via :func:`_set_best_trial`.
    """
    if objective is None:
        objective = {"metric": "ndcg", "k": 10, "direction": "maximize"}
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cf-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"cf-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"cf-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(seed_queries):
            qid = str(uuid.uuid4())
            await repo.create_query(
                db,
                id=qid,
                query_set_id=query_set.id,
                query_text=f"q-text-{i}",
            )
            query_ids.append(qid)
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"cf-jl-{uuid.uuid4().hex[:8]}",
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
            name=f"cf-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective=objective,
            config={"max_trials": 100},
            status="completed",
            failed_reason=None,
            optuna_study_name=study_id,
            baseline_metric=None,
            best_metric=best_metric,
            best_trial_id=None,
        )
        await db.commit()
    return {
        "study_id": study_id,
        "cluster_id": cluster.id,
        "query_set_id": query_set.id,
        "query_ids": query_ids,
    }


async def _insert_trial(
    *,
    study_id: str,
    optuna_trial_number: int,
    primary_metric: float | None,
    per_query_metrics: dict[str, Any] | None = None,
    status: str = "complete",
) -> str:
    """Insert one trial row directly; returns its UUID."""
    factory = get_session_factory()
    async with factory() as db:
        trial_id = str(uuid.uuid4())
        kwargs: dict[str, Any] = {
            "id": trial_id,
            "study_id": study_id,
            "optuna_trial_number": optuna_trial_number,
            "status": status,
            "params": {},
            "metrics": {},
            "primary_metric": primary_metric,
            "started_at": datetime.now(UTC),
            "ended_at": datetime.now(UTC),
            "duration_ms": 100,
        }
        if per_query_metrics is not None:
            kwargs["per_query_metrics"] = per_query_metrics
        await repo.create_trial(db, **kwargs)
        await db.commit()
    return trial_id


async def _set_best_trial(study_id: str, trial_id: str | None) -> None:
    """Patch ``studies.best_trial_id`` post-hoc."""
    from backend.app.db.models import Study as _Study

    factory = get_session_factory()
    async with factory() as db:
        row = await db.get(_Study, study_id)
        assert row is not None
        row.best_trial_id = trial_id
        await db.flush()
        await db.commit()


# ---------------------------------------------------------------------------
# AC-3 — old study (per_query_metrics IS NULL) → partial confidence
# ---------------------------------------------------------------------------


async def test_ac3_old_study_returns_partial_confidence_with_aggregate_signals(
    async_client: httpx.AsyncClient,
) -> None:
    """Per-query sub-fields null; aggregate signals populated."""
    ctx = await _seed_study(best_metric=0.84)
    # 12 complete trials, NO per_query_metrics — covers the 10-trial floor for
    # late_trial_stddev and the 3-trial floor for convergence.
    trial_ids: list[str] = []
    metrics = [0.84, 0.82, 0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68, 0.66, 0.64, 0.62]
    for i, m in enumerate(metrics):
        tid = await _insert_trial(
            study_id=ctx["study_id"],
            optuna_trial_number=i,
            primary_metric=m,
        )
        trial_ids.append(tid)
    # Winner is trial 0 (highest primary_metric).
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    assert resp.status_code == 200, resp.text
    confidence = resp.json()["confidence"]
    assert confidence is not None
    assert confidence["ci_95"] is None  # AC-3: no per-query → no CI
    assert confidence["per_query_outcomes"] is None  # AC-3: no per-query data
    assert confidence["headline"]["n_queries"] is None  # AC-3
    assert confidence["headline"]["value"] == pytest.approx(0.84)
    # Aggregate signals populated.
    assert confidence["runner_up_gap"] is not None
    assert confidence["late_trial_stddev"] is not None
    assert confidence["convergence"] is not None
    assert confidence["convergence"]["best_at_trial"] == 0
    # 12 trials at optuna_trial_number 0..11 → max+1 = 12 (matches count when
    # trial numbers are sequential, which is the seed shape here).
    assert confidence["convergence"]["total_trials"] == 12


# ---------------------------------------------------------------------------
# AC-3a — best_trial_id IS NULL → confidence whole-object null
# ---------------------------------------------------------------------------


async def test_ac3a_missing_best_trial_id_returns_null_confidence(
    async_client: httpx.AsyncClient,
) -> None:
    """best_trial_id unset → whole-object null."""
    ctx = await _seed_study(best_metric=None)
    # No trials, no winner.
    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["confidence"] is None


async def test_ac3a_dangling_best_trial_id_returns_null_confidence(
    async_client: httpx.AsyncClient,
) -> None:
    """best_trial_id set but trial row missing → whole-object null."""
    ctx = await _seed_study(best_metric=0.5)
    # Point at a non-existent trial id.
    await _set_best_trial(ctx["study_id"], str(uuid.uuid4()))
    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["confidence"] is None


# ---------------------------------------------------------------------------
# AC-4 — bootstrap CI reproducibility (same response twice → byte-equal CI)
# ---------------------------------------------------------------------------


async def test_ac4_bootstrap_ci_is_reproducible_across_calls(
    async_client: httpx.AsyncClient,
) -> None:
    """Two successive GETs → identical CI low/high (seed=42 lock)."""
    ctx = await _seed_study(best_metric=0.84, seed_queries=20)
    qids = ctx["query_ids"]
    # Winner: per_query_metrics carries an ndcg value for each of 20 queries.
    # Use deterministic floats spread across [0.6, 0.95] for a non-degenerate CI.
    winner_per_query = {
        qid: {"ndcg@10": 0.6 + (i * 0.018), "map": 0.5, "precision": 0.5, "recall": 0.5, "mrr": 0.5}
        for i, qid in enumerate(qids)
    }
    # Need ≥10 trials so all aggregate signals populate.
    trial_ids: list[str] = []
    for i in range(15):
        per_q = winner_per_query if i == 0 else None
        tid = await _insert_trial(
            study_id=ctx["study_id"],
            optuna_trial_number=i,
            primary_metric=0.84 - (i * 0.01),
            per_query_metrics=per_q,
        )
        trial_ids.append(tid)
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    r1 = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    r2 = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    ci1 = r1.json()["confidence"]["ci_95"]
    ci2 = r2.json()["confidence"]["ci_95"]
    assert ci1 is not None and ci2 is not None
    assert ci1["low"] == ci2["low"]
    assert ci1["high"] == ci2["high"]
    assert ci1["method"] == "bootstrap_n1000"
    assert ci1["n_samples"] == 20


# ---------------------------------------------------------------------------
# AC-5 — runner-up gap classification (robust_plateau vs sharp_peak)
# ---------------------------------------------------------------------------


async def test_ac5_runner_up_gap_robust_plateau(async_client: httpx.AsyncClient) -> None:
    """Top 10 within 0.005 of the winner → robust_plateau."""
    ctx = await _seed_study(best_metric=0.840)
    # 10 trials all within < 0.005 of the winner — picked just inside the band
    # to avoid float-equality boundary noise on 0.840 - 0.835.
    metrics = [0.840, 0.839, 0.838, 0.837, 0.837, 0.838, 0.837, 0.838, 0.839, 0.837]
    trial_ids: list[str] = []
    for i, m in enumerate(metrics):
        tid = await _insert_trial(study_id=ctx["study_id"], optuna_trial_number=i, primary_metric=m)
        trial_ids.append(tid)
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    gap = resp.json()["confidence"]["runner_up_gap"]
    assert gap is not None
    assert gap["classification"] == "robust_plateau"


async def test_ac5_runner_up_gap_sharp_peak(async_client: httpx.AsyncClient) -> None:
    """Winner > 0.005 above runner-up → sharp_peak."""
    ctx = await _seed_study(best_metric=0.840)
    metrics = [0.840, 0.760, 0.755, 0.750]
    trial_ids: list[str] = []
    for i, m in enumerate(metrics):
        tid = await _insert_trial(study_id=ctx["study_id"], optuna_trial_number=i, primary_metric=m)
        trial_ids.append(tid)
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    gap = resp.json()["confidence"]["runner_up_gap"]
    assert gap is not None
    assert gap["classification"] == "sharp_peak"


# ---------------------------------------------------------------------------
# AC-6 — late-trial stddev matches numpy at N=50
# ---------------------------------------------------------------------------


async def test_ac6_late_trial_stddev_window_math_matches_numpy(
    async_client: httpx.AsyncClient,
) -> None:
    """50 complete trials → window_size=10, value = np.std(last10, ddof=1)."""
    ctx = await _seed_study(best_metric=0.99)
    metrics = [0.99 - (i * 0.005) for i in range(50)]
    trial_ids: list[str] = []
    for i, m in enumerate(metrics):
        tid = await _insert_trial(study_id=ctx["study_id"], optuna_trial_number=i, primary_metric=m)
        trial_ids.append(tid)
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    noise = resp.json()["confidence"]["late_trial_stddev"]
    assert noise is not None
    assert noise["window_size"] == 10
    expected = float(np.std(np.asarray(metrics[-10:], dtype=np.float64), ddof=1))
    assert noise["value"] == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# AC-7 — late-trial stddev suppressed at N<10
# ---------------------------------------------------------------------------


async def test_ac7_late_trial_stddev_null_when_fewer_than_ten_trials(
    async_client: httpx.AsyncClient,
) -> None:
    ctx = await _seed_study(best_metric=0.8)
    trial_ids: list[str] = []
    for i in range(9):
        tid = await _insert_trial(
            study_id=ctx["study_id"],
            optuna_trial_number=i,
            primary_metric=0.8 - (i * 0.01),
        )
        trial_ids.append(tid)
    await _set_best_trial(ctx["study_id"], trial_ids[0])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    assert resp.json()["confidence"]["late_trial_stddev"] is None


# ---------------------------------------------------------------------------
# AC-8 — early_held convergence regime
# ---------------------------------------------------------------------------


async def test_ac8_convergence_regime_early_held(async_client: httpx.AsyncClient) -> None:
    """Winner at trial 200/1000 + late plateau within 0.005 → early_held."""
    ctx = await _seed_study(best_metric=0.84)
    # Sparse trial-number distribution to avoid inserting 1000 rows.
    # Winner at trial_number=200; max_trial_number=1000; a late trial at
    # trial_number=800 has primary_metric within 0.005 of the winner.
    trial_specs = [
        (0, 0.70),
        (100, 0.78),
        (200, 0.84),  # winner
        (400, 0.80),
        (600, 0.79),
        (800, 0.838),  # late plateau within 0.005 of 0.84
        (1000, 0.74),
    ]
    trial_ids: dict[int, str] = {}
    for tn, m in trial_specs:
        tid = await _insert_trial(
            study_id=ctx["study_id"], optuna_trial_number=tn, primary_metric=m
        )
        trial_ids[tn] = tid
    await _set_best_trial(ctx["study_id"], trial_ids[200])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    conv = resp.json()["confidence"]["convergence"]
    assert conv is not None
    assert conv["regime"] == "early_held"
    assert conv["best_at_trial"] == 200
    # Sparse trial numbers (0, 100, …, 1000) — 7 complete trials but the
    # Optuna budget is 1001 (max trial number 1000 + 1 for 0-indexed
    # numbering). GPT-5.5 review finding #6: total_trials must reflect
    # the budget, not the count, so the PR body reads "best at trial
    # 200 of 1001" rather than "200 of 7".
    assert conv["total_trials"] == 1001


# ---------------------------------------------------------------------------
# AC-9 — late_rising convergence regime
# ---------------------------------------------------------------------------


async def test_ac9_convergence_regime_late_rising(async_client: httpx.AsyncClient) -> None:
    """Winner at trial 950/1000 → late_rising."""
    ctx = await _seed_study(best_metric=0.84)
    trial_specs = [
        (0, 0.50),
        (100, 0.55),
        (500, 0.70),
        (800, 0.78),
        (950, 0.84),  # winner — past 90% of max trial number
        (1000, 0.82),
    ]
    trial_ids: dict[int, str] = {}
    for tn, m in trial_specs:
        tid = await _insert_trial(
            study_id=ctx["study_id"], optuna_trial_number=tn, primary_metric=m
        )
        trial_ids[tn] = tid
    await _set_best_trial(ctx["study_id"], trial_ids[950])

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    conv = resp.json()["confidence"]["convergence"]
    assert conv is not None
    assert conv["regime"] == "late_rising"


# ---------------------------------------------------------------------------
# AC-10 — per-query regressor naming with query_text join
# ---------------------------------------------------------------------------


async def test_ac10_per_query_regressor_includes_query_text(
    async_client: httpx.AsyncClient,
) -> None:
    """Regressor row carries query_text from the queries table."""
    ctx = await _seed_study(best_metric=0.84, seed_queries=2)
    qids = ctx["query_ids"]
    qA, qB = qids[0], qids[1]
    # Winner: qA scored 0.41 (will regress vs runner-up's 0.92);
    # qB scored 0.85 (unchanged vs runner-up's 0.85).
    winner_per_query = {
        qA: {"ndcg@10": 0.41},
        qB: {"ndcg@10": 0.85},
    }
    runner_up_per_query = {
        qA: {"ndcg@10": 0.92},
        qB: {"ndcg@10": 0.85},
    }
    winner_id = await _insert_trial(
        study_id=ctx["study_id"],
        optuna_trial_number=0,
        primary_metric=0.84,
        per_query_metrics=winner_per_query,
    )
    await _insert_trial(
        study_id=ctx["study_id"],
        optuna_trial_number=1,
        primary_metric=0.83,
        per_query_metrics=runner_up_per_query,
    )
    await _set_best_trial(ctx["study_id"], winner_id)

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    outcomes = resp.json()["confidence"]["per_query_outcomes"]
    assert outcomes is not None
    assert outcomes["comparison_against"] == "runner_up"
    assert outcomes["regressed"] == 1
    assert outcomes["unchanged"] == 1
    assert outcomes["improved"] == 0
    regressors = outcomes["top_regressors"]
    assert len(regressors) == 1
    row = regressors[0]
    assert row["query_id"] == qA
    assert row["query_text"] == "q-text-0"
    assert row["winner_score"] == pytest.approx(0.41)
    assert row["comparison_score"] == pytest.approx(0.92)
    assert row["delta"] == pytest.approx(-0.51)


# ---------------------------------------------------------------------------
# AC-15 — bootstrap CI suppressed at N(queries) < 5
# ---------------------------------------------------------------------------


async def test_ac15_bootstrap_ci_null_when_fewer_than_five_queries(
    async_client: httpx.AsyncClient,
) -> None:
    ctx = await _seed_study(best_metric=0.8, seed_queries=4)
    qids = ctx["query_ids"]
    winner_per_query = {qid: {"ndcg@10": 0.7 + i * 0.02} for i, qid in enumerate(qids)}
    winner_id = await _insert_trial(
        study_id=ctx["study_id"],
        optuna_trial_number=0,
        primary_metric=0.8,
        per_query_metrics=winner_per_query,
    )
    await _set_best_trial(ctx["study_id"], winner_id)

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    confidence = resp.json()["confidence"]
    assert confidence is not None
    assert confidence["ci_95"] is None
    # headline still populates from study.best_metric.
    assert confidence["headline"]["value"] == pytest.approx(0.8)
    assert confidence["headline"]["n_queries"] == 4


# ---------------------------------------------------------------------------
# AC-16 — per_query_outcomes + runner_up_gap suppressed when only 1 complete trial
# ---------------------------------------------------------------------------


async def test_ac16_single_complete_trial_suppresses_runner_up_signals(
    async_client: httpx.AsyncClient,
) -> None:
    """Only 1 complete trial → per_query_outcomes + runner_up_gap null; CI still populates."""
    ctx = await _seed_study(best_metric=0.8, seed_queries=6)
    qids = ctx["query_ids"]
    winner_per_query = {qid: {"ndcg@10": 0.7 + i * 0.02} for i, qid in enumerate(qids)}
    winner_id = await _insert_trial(
        study_id=ctx["study_id"],
        optuna_trial_number=0,
        primary_metric=0.8,
        per_query_metrics=winner_per_query,
    )
    # Other trials all failed (no primary_metric).
    for i in range(1, 5):
        await _insert_trial(
            study_id=ctx["study_id"],
            optuna_trial_number=i,
            primary_metric=None,
            status="failed",
        )
    await _set_best_trial(ctx["study_id"], winner_id)

    resp = await async_client.get(f"/api/v1/studies/{ctx['study_id']}")
    confidence = resp.json()["confidence"]
    assert confidence is not None
    assert confidence["per_query_outcomes"] is None
    assert confidence["runner_up_gap"] is None
    # Winner-only signals still populate.
    assert confidence["ci_95"] is not None
    assert confidence["headline"]["n_queries"] == 6
