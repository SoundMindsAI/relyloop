# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``GET /api/v1/studies/chains/recent``
(feat_overnight_studies_summary_card Story 1.2).

Exercises the endpoint end-to-end through the real FastAPI app + DB:

* AC-1 — multi-link chain appears in the response with the right shape
* AC-5 — empty data array → 200 with ``data:[]``
* AC-11 — terminal-failed chain returns with null metric fields
* Route-order collision regression — ``/studies/chains/recent`` hits the
  new handler, not ``get_study_detail`` with ``study_id="chains"``
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


async def _seed_fixtures(db: Any) -> dict[str, str]:
    cluster = await repo.create_cluster(
        db,
        id=_uuid(),
        name=f"rc-c-{uuid.uuid4().hex[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://stub:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
    )
    template = await repo.create_query_template(
        db,
        id=_uuid(),
        name=f"rc-qt-{uuid.uuid4().hex[:8]}",
        engine_type="elasticsearch",
        body="{}",
        declared_params={},
    )
    query_set = await repo.create_query_set(
        db, id=_uuid(), name=f"rc-qs-{uuid.uuid4().hex[:8]}", cluster_id=cluster.id
    )
    jl = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"rc-jl-{uuid.uuid4().hex[:8]}",
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
    completed_at: datetime | None = None,
    name: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    sid = _uuid()
    await repo.create_study(
        db,
        id=sid,
        name=name if name is not None else f"rc-study-{sid[:8]}",
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
        completed_at=completed_at,
    )
    return sid


async def test_recent_chains_returns_chain_ac1(async_client: httpx.AsyncClient) -> None:
    """AC-1: a 3-link chain shows up exactly once with anchor identity,
    chain length, best-link metric, derived stop reason, and a non-null
    ``tail_completed_at``.
    """
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_fixtures(db)
        anchor = await _seed_study(
            db,
            fx,
            name="Anchor study",
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            completed_at=_BASE + timedelta(minutes=5),
        )
        mid = await _seed_study(
            db,
            fx,
            parent_study_id=anchor,
            best_metric=0.72,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        await _seed_study(
            db,
            fx,
            parent_study_id=mid,
            best_metric=0.74,
            created_at=_BASE + timedelta(hours=2),
            completed_at=_BASE + timedelta(hours=2, minutes=5),
            config={"auto_followup_depth": 0},
        )
        await db.commit()

    resp = await async_client.get("/api/v1/studies/chains/recent")
    assert resp.status_code == 200
    assert resp.headers.get("X-Total-Count") == "1"
    body = resp.json()
    assert body["next_cursor"] is None
    assert body["has_more"] is False
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["anchor_study_id"] == anchor
    assert row["anchor_name"] == "Anchor study"
    assert row["chain_length"] == 3
    assert row["best_metric"] == pytest.approx(0.74)
    assert row["objective_metric"] == "ndcg"
    assert row["cumulative_lift"] == pytest.approx(0.14)
    assert row["direction"] == "maximize"
    assert row["stop_reason"] == "depth_exhausted"
    assert row["best_link_proposal_id"] is None
    # tail completed_at is the LAST link's completed_at, surfaced as ISO.
    assert row["tail_completed_at"].startswith("2026-05-31T02:05")


async def test_recent_chains_empty_returns_200_ac5(async_client: httpx.AsyncClient) -> None:
    """AC-5: with no chains in the DB the endpoint returns 200 with an
    empty data array and ``X-Total-Count: 0``.
    """
    resp = await async_client.get("/api/v1/studies/chains/recent")
    assert resp.status_code == 200
    assert resp.headers.get("X-Total-Count") == "0"
    body = resp.json()
    assert body == {"data": [], "next_cursor": None, "has_more": False}


async def test_recent_chains_failed_tail_null_metric_ac11(async_client: httpx.AsyncClient) -> None:
    """AC-11: a chain whose terminal tail is ``failed`` (no best_metric)
    is returned with ``best_metric: null`` and ``cumulative_lift: null``.
    The stop reason resolves to ``parent_failed`` so the card can render
    the failure phrase in place of the numeric row.
    """
    factory = get_session_factory()
    async with factory() as db:
        fx = await _seed_fixtures(db)
        anchor = await _seed_study(
            db,
            fx,
            best_metric=0.6,
            baseline_metric=0.5,
            created_at=_BASE,
            completed_at=_BASE + timedelta(minutes=5),
        )
        await _seed_study(
            db,
            fx,
            parent_study_id=anchor,
            status="failed",
            best_metric=None,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        await db.commit()

    resp = await async_client.get("/api/v1/studies/chains/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["anchor_study_id"] == anchor
    assert row["chain_length"] == 2
    # The anchor's best_metric is non-null so the "best of completed
    # subset" picks the anchor — `best_metric` is the anchor's value,
    # `cumulative_lift` is anchor − baseline.
    assert row["best_metric"] == pytest.approx(0.6)
    assert row["cumulative_lift"] == pytest.approx(0.1)
    assert row["stop_reason"] == "parent_failed"


async def test_recent_chains_route_order_collision(async_client: httpx.AsyncClient) -> None:
    """Route-order regression: ``/studies/chains/recent`` MUST hit
    ``get_recent_chains``, not ``get_study_detail`` with
    ``study_id="chains"``. The former returns 200 + the documented body
    shape; the latter would 404 with ``STUDY_NOT_FOUND``.
    """
    resp = await async_client.get("/api/v1/studies/chains/recent")
    assert resp.status_code == 200
    body = resp.json()
    # The recent-chains shape has a `data` key; STUDY_NOT_FOUND would
    # carry a top-level `detail.error_code` envelope.
    assert "data" in body
    assert "detail" not in body
