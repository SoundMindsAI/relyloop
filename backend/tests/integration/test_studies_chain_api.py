# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``GET /api/v1/studies/{id}/chain`` (feat_overnight_autopilot Story 1.3).

DB-backed happy-path coverage: AC-3 (3-link chain), AC-4 (404 unknown),
AC-5 (non-chained single study), AC-8 (in_flight), AC-9 (cancelled),
AC-10 (parent_failed), and the D-11 rejected-proposal exclusion. Rows are
seeded directly via the repo (the chaining engine is not invoked), then the
endpoint is exercised through the real FastAPI app + DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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

_BASE = datetime(2026, 5, 31, tzinfo=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


async def _seed_chain_fixtures(db: Any) -> dict[str, str]:
    cluster = await repo.create_cluster(
        db,
        id=_uuid(),
        name=f"chain-c-{uuid.uuid4().hex[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://stub:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
    )
    template = await repo.create_query_template(
        db,
        id=_uuid(),
        name=f"chain-qt-{uuid.uuid4().hex[:8]}",
        engine_type="elasticsearch",
        body="{}",
        declared_params={},
        version=1,
    )
    query_set = await repo.create_query_set(
        db, id=_uuid(), name=f"chain-qs-{uuid.uuid4().hex[:8]}", cluster_id=cluster.id
    )
    jl = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"chain-jl-{uuid.uuid4().hex[:8]}",
        query_set_id=query_set.id,
        cluster_id=cluster.id,
        target="products",
        rubric="rate",
        status="complete",
    )
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
    }


async def _seed_study(
    db: Any,
    fx: dict[str, str],
    *,
    parent_study_id: str | None = None,
    status: str = "completed",
    best_metric: float | None = None,
    baseline_metric: float | None = None,
    created_at: datetime | None = None,
    config: dict[str, Any] | None = None,
    failed_reason: str | None = None,
    completed_at: datetime | None = None,
) -> str:
    sid = _uuid()
    await repo.create_study(
        db,
        id=sid,
        name=f"chain-study-{sid[:8]}",
        cluster_id=fx["cluster_id"],
        target="products",
        template_id=fx["template_id"],
        query_set_id=fx["query_set_id"],
        judgment_list_id=fx["judgment_list_id"],
        search_space={},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config=config if config is not None else {},
        status=status,
        optuna_study_name=sid,
        parent_study_id=parent_study_id,
        best_metric=best_metric,
        baseline_metric=baseline_metric,
        created_at=created_at if created_at is not None else _BASE,
        failed_reason=failed_reason,
        completed_at=completed_at,
    )
    return sid


async def test_chain_three_link_ac3(async_client: httpx.AsyncClient) -> None:
    """AC-3: S1(0.65/base 0.60) → S2(0.72) → S3(0.74), best=S3, lift=0.14."""
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        s1 = await _seed_study(
            db,
            fx,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            config={"auto_followup_depth": 3},
        )
        s2 = await _seed_study(
            db,
            fx,
            parent_study_id=s1,
            best_metric=0.72,
            created_at=_BASE + timedelta(hours=1),
            config={"auto_followup_depth": 2},
        )
        s3 = await _seed_study(
            db,
            fx,
            parent_study_id=s2,
            best_metric=0.74,
            created_at=_BASE + timedelta(hours=2),
            config={"auto_followup_depth": 0},
        )
        # Proposal only on S2 to prove proposal_id_for_best_link (S3) is null.
        await repo.create_proposal(
            db,
            id=_uuid(),
            study_id=s2,
            cluster_id=fx["cluster_id"],
            template_id=fx["template_id"],
            config_diff={"x": {"from": 1, "to": 2}},
            status="pending",
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{s2}/chain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_study_id"] == s1
    assert body["best_link_id"] == s3
    assert body["best_metric"] == pytest.approx(0.74)
    assert body["cumulative_lift"] == pytest.approx(0.14)
    assert body["direction"] == "maximize"
    assert body["proposal_id_for_best_link"] is None  # S3 has no proposal
    assert body["stop_reason"] == "depth_exhausted"  # tail depth 0
    ids = [lk["id"] for lk in body["links"]]
    assert ids == [s1, s2, s3]
    deltas = [lk["delta_from_prev"] for lk in body["links"]]
    assert deltas[0] is None
    assert deltas[1] == pytest.approx(0.07)
    assert deltas[2] == pytest.approx(0.02)


async def test_chain_404_unknown_ac4(async_client: httpx.AsyncClient) -> None:
    missing = "01890000-0000-7000-8000-deadbeef0000"
    resp = await async_client.get(f"/api/v1/studies/{missing}/chain")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "STUDY_NOT_FOUND"
    assert detail["message"] == f"study {missing} not found"
    assert detail["retryable"] is False


async def test_chain_single_link_ac5(async_client: httpx.AsyncClient) -> None:
    """AC-5: non-chained completed study, best 0.74 / baseline 0.65 → lift 0.09."""
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        x = await _seed_study(
            db,
            fx,
            best_metric=0.74,
            baseline_metric=0.65,
            config={"auto_followup_depth": 0},
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{x}/chain")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["links"]) == 1
    assert body["best_link_id"] == x
    assert body["cumulative_lift"] == pytest.approx(0.09)
    assert body["stop_reason"] == "depth_exhausted"


async def test_chain_in_flight_ac8(async_client: httpx.AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        s1 = await _seed_study(
            db,
            fx,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            config={"auto_followup_depth": 2},
        )
        await _seed_study(
            db,
            fx,
            parent_study_id=s1,
            status="running",
            created_at=_BASE + timedelta(hours=1),
            config={"auto_followup_depth": 1},
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{s1}/chain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stop_reason"] == "in_flight"
    # completed subset = {S1} → best_link_id is S1, cumulative_lift derivable.
    assert body["best_link_id"] == s1


async def test_chain_cancelled_ac9(async_client: httpx.AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        s1 = await _seed_study(
            db,
            fx,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            config={"auto_followup_depth": 2},
        )
        s2 = await _seed_study(
            db,
            fx,
            parent_study_id=s1,
            best_metric=0.70,
            created_at=_BASE + timedelta(hours=1),
            config={"auto_followup_depth": 1},
        )
        await _seed_study(
            db,
            fx,
            parent_study_id=s2,
            status="cancelled",
            created_at=_BASE + timedelta(hours=2),
            config={"auto_followup_depth": 0},
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{s1}/chain")
    assert resp.status_code == 200
    assert resp.json()["stop_reason"] == "cancelled"


async def test_chain_parent_failed_ac10(async_client: httpx.AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        s1 = await _seed_study(
            db,
            fx,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            config={"auto_followup_depth": 2},
        )
        s2 = await _seed_study(
            db,
            fx,
            parent_study_id=s1,
            best_metric=0.70,
            created_at=_BASE + timedelta(hours=1),
            config={"auto_followup_depth": 1},
        )
        await _seed_study(
            db,
            fx,
            parent_study_id=s2,
            status="failed",
            failed_reason="engine timeout",
            created_at=_BASE + timedelta(hours=2),
            config={"auto_followup_depth": 0},
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{s1}/chain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stop_reason"] == "parent_failed"
    assert body["links"][-1]["failed_reason"] == "engine timeout"


async def test_chain_rejected_proposal_excluded_d11(async_client: httpx.AsyncClient) -> None:
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_chain_fixtures(db)
        x = await _seed_study(
            db,
            fx,
            best_metric=0.74,
            baseline_metric=0.65,
            config={"auto_followup_depth": 0},
        )
        await repo.create_proposal(
            db,
            id=_uuid(),
            study_id=x,
            cluster_id=fx["cluster_id"],
            template_id=fx["template_id"],
            config_diff={"x": {"from": 1, "to": 2}},
            status="rejected",
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{x}/chain")
    assert resp.status_code == 200
    body = resp.json()
    # All proposals rejected → best link's proposal surfaces as null.
    assert body["proposal_id_for_best_link"] is None
    assert body["links"][0]["proposal_id"] is None
