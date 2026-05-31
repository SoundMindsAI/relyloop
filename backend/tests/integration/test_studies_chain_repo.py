# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``get_chain_for_study`` (feat_overnight_autopilot Story 1.2).

Exercises the chain-traversal repo helper against the real test Postgres:
linear happy path, anchor-only single-link, descendant cap, upward cycle
cap, fan-out ``LIMIT 1`` truncation, and the proposal-lookup ordering /
rejected-exclusion. Skips automatically when Postgres isn't host-reachable.

Rows are committed (not savepoint-scoped) so the cyclic ``parent_study_id``
seeding via direct ``UPDATE`` is visible to the helper's own queries; the
``_clean_phase2_tables`` autouse fixture wipes them after each test.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo

_BASE = datetime(2026, 5, 31, tzinfo=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


async def _seed_cluster(db: AsyncSession) -> str:
    cluster = await repo.create_cluster(
        db,
        id=_uuid(),
        name=f"c-{_uuid()[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://x:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
    )
    return cluster.id


async def _seed_template(db: AsyncSession) -> str:
    template = await repo.create_query_template(
        db,
        id=_uuid(),
        name=f"qt-{_uuid()[:8]}",
        engine_type="elasticsearch",
        body="{}",
        declared_params={},
    )
    return template.id


async def _seed_study(
    db: AsyncSession,
    *,
    cluster_id: str,
    template_id: str,
    query_set_id: str,
    judgment_list_id: str,
    parent_study_id: str | None = None,
    status: str = "completed",
    best_metric: float | None = None,
    baseline_metric: float | None = None,
    created_at: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    sid = _uuid()
    await repo.create_study(
        db,
        id=sid,
        name=f"study-{sid[:8]}",
        cluster_id=cluster_id,
        target="products",
        template_id=template_id,
        query_set_id=query_set_id,
        judgment_list_id=judgment_list_id,
        search_space={},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config=config if config is not None else {},
        status=status,
        optuna_study_name=sid,
        parent_study_id=parent_study_id,
        best_metric=best_metric,
        baseline_metric=baseline_metric,
        created_at=created_at if created_at is not None else _BASE,
    )
    return sid


class _Fixtures:
    """Container for the shared FK targets a chain needs."""

    def __init__(self, cluster_id: str, template_id: str, query_set_id: str, jl_id: str) -> None:
        self.cluster_id = cluster_id
        self.template_id = template_id
        self.query_set_id = query_set_id
        self.judgment_list_id = jl_id


async def _seed_fixtures(db: AsyncSession) -> _Fixtures:
    cluster_id = await _seed_cluster(db)
    template_id = await _seed_template(db)
    query_set = await repo.create_query_set(
        db, id=_uuid(), name=f"qs-{_uuid()[:8]}", cluster_id=cluster_id
    )
    jl = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"jl-{_uuid()[:8]}",
        query_set_id=query_set.id,
        cluster_id=cluster_id,
        target="products",
        rubric="rate",
        status="complete",
    )
    return _Fixtures(cluster_id, template_id, query_set.id, jl.id)


@pytest.mark.integration
class TestGetChainForStudy:
    async def test_missing_study_returns_none(self, db_session: AsyncSession) -> None:
        assert (
            await repo.get_chain_for_study(db_session, "01890000-dead-beef-0000-000000000000")
            is None
        )

    async def test_linear_three_link_chain_ordered(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        s1 = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
        )
        s2 = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=s1,
            best_metric=0.72,
            created_at=_BASE + timedelta(hours=1),
        )
        s3 = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=s2,
            best_metric=0.74,
            created_at=_BASE + timedelta(hours=2),
        )
        await db_session.commit()

        # Anchored from the MIDDLE link to prove the upward walk reaches S1.
        result = await repo.get_chain_for_study(db_session, s2)
        assert result is not None
        assert result.anchor_id == s1
        assert [s.id for s in result.links] == [s1, s2, s3]
        # Anchor has an explicit baseline → no anchor_trials lookup fired.
        assert result.anchor_trials is None

    async def test_anchor_only_single_link(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        sid = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.70,
            baseline_metric=0.65,
        )
        await db_session.commit()

        result = await repo.get_chain_for_study(db_session, sid)
        assert result is not None
        assert result.anchor_id == sid
        assert [s.id for s in result.links] == [sid]
        assert result.proposal_id_by_link_id == {}

    async def test_descendant_walk_visits_five_children(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        ids: list[str] = []
        parent: str | None = None
        for i in range(7):  # 1 anchor + 6 descendants; cap should clip at 6 rows
            sid = await _seed_study(
                db_session,
                cluster_id=fx.cluster_id,
                template_id=fx.template_id,
                query_set_id=fx.query_set_id,
                judgment_list_id=fx.judgment_list_id,
                parent_study_id=parent,
                best_metric=0.5 + 0.01 * i,
                baseline_metric=0.5 if parent is None else None,
                created_at=_BASE + timedelta(hours=i),
            )
            ids.append(sid)
            parent = sid
        await db_session.commit()

        result = await repo.get_chain_for_study(db_session, ids[0])
        assert result is not None
        # anchor + 5 descendants = 6 rows max (D-7).
        assert len(result.links) == 6
        assert [s.id for s in result.links] == ids[:6]

    async def test_upward_cycle_caps_at_ten_hops(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ) -> None:
        fx = await _seed_fixtures(db_session)
        # Seed a 2-node cycle by direct UPDATE bypassing the model invariant.
        a = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.6,
            baseline_metric=0.5,
            created_at=_BASE,
        )
        b = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=a,
            best_metric=0.7,
            created_at=_BASE + timedelta(hours=1),
        )
        # Make A point at B → cycle A → B → A.
        await db_session.execute(
            text("UPDATE studies SET parent_study_id = :b WHERE id = :a"), {"a": a, "b": b}
        )
        await db_session.commit()

        with caplog.at_level(logging.WARNING):
            result = await repo.get_chain_for_study(db_session, b)
        assert result is not None  # terminates, no infinite loop
        assert any("cap or cycle" in rec.message for rec in caplog.records)

    async def test_upward_linear_chain_hits_ten_hop_cap(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An ACYCLIC linear ancestry deeper than the 10-hop cap must stop at
        the cap (not climb to the true root) and WARN with ``hop_count == 10``.

        The sibling ``test_upward_cycle_caps_at_ten_hops`` seeds a 2-node cycle,
        which exits via the visited-set guard after one hop — so it proves the
        cycle guard, NOT the defensive hop cap. This test seeds a strictly
        acyclic 12-deep chain so the WARN can ONLY originate from the
        ``hops >= _CHAIN_UPWARD_HOP_CAP`` branch, exercising the cap bound,
        its ``hop_count`` telemetry, and the cap-stop-as-anchor semantics.
        """
        fx = await _seed_fixtures(db_session)
        # Seed S0 (root) → S1 → … → S11 (12 nodes, 11 parent links).
        prev: str | None = None
        ids: list[str] = []
        for i in range(12):
            sid = await _seed_study(
                db_session,
                cluster_id=fx.cluster_id,
                template_id=fx.template_id,
                query_set_id=fx.query_set_id,
                judgment_list_id=fx.judgment_list_id,
                parent_study_id=prev,
                best_metric=0.5 + i * 0.01,
                baseline_metric=0.5 if i == 0 else None,
                created_at=_BASE + timedelta(hours=i),
            )
            ids.append(sid)
            prev = sid
        deepest = ids[-1]  # S11

        with caplog.at_level(logging.WARNING):
            result = await repo.get_chain_for_study(db_session, deepest)

        assert result is not None  # terminates, no infinite loop
        # WARN fired specifically via the hop cap (acyclic → cycle guard cannot
        # fire), and the telemetry records exactly the cap value.
        assert any(getattr(rec, "hop_count", None) == 10 for rec in caplog.records)
        # Cap-stop anchor is S1 (10 hops above S11), NOT the true root S0.
        assert result.anchor_id == ids[1]
        assert result.anchor_id != ids[0]

    async def test_fanout_takes_first_and_warns(
        self, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
    ) -> None:
        fx = await _seed_fixtures(db_session)
        anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.6,
            baseline_metric=0.5,
            created_at=_BASE,
        )
        first_child = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=anchor,
            best_metric=0.7,
            created_at=_BASE + timedelta(hours=1),
        )
        # Second sibling (later created_at) — should be dropped.
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=anchor,
            best_metric=0.9,
            created_at=_BASE + timedelta(hours=2),
        )
        await db_session.commit()

        with caplog.at_level(logging.WARNING):
            result = await repo.get_chain_for_study(db_session, anchor)
        assert result is not None
        assert [s.id for s in result.links] == [anchor, first_child]
        assert any("fan-out" in rec.message for rec in caplog.records)

    async def test_proposal_lookup_newest_non_rejected_wins(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        sid = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=0.65,
        )
        # Older proposal, then a newer one — newer wins.
        old = await repo.create_proposal(
            db_session,
            id=_uuid(),
            study_id=sid,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            config_diff={"x": {"from": 1, "to": 2}},
            status="pending",
            created_at=_BASE,
        )
        new = await repo.create_proposal(
            db_session,
            id=_uuid(),
            study_id=sid,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            config_diff={"x": {"from": 1, "to": 3}},
            status="pr_opened",
            created_at=_BASE + timedelta(hours=1),
        )
        await db_session.commit()

        result = await repo.get_chain_for_study(db_session, sid)
        assert result is not None
        assert result.proposal_id_by_link_id[sid] == new.id
        assert result.proposal_id_by_link_id[sid] != old.id

    async def test_proposal_lookup_excludes_rejected(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        sid = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=0.65,
        )
        await repo.create_proposal(
            db_session,
            id=_uuid(),
            study_id=sid,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            config_diff={"x": {"from": 1, "to": 2}},
            status="rejected",
            created_at=_BASE,
        )
        await db_session.commit()

        result = await repo.get_chain_for_study(db_session, sid)
        assert result is not None
        # All proposals rejected → no key in the dict.
        assert sid not in result.proposal_id_by_link_id

    async def test_anchor_trials_only_when_baseline_null(self, db_session: AsyncSession) -> None:
        fx = await _seed_fixtures(db_session)
        sid = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=None,  # triggers the anchor-trials lookup
        )
        for tn in range(3):
            await repo.create_trial(
                db_session,
                id=_uuid(),
                study_id=sid,
                optuna_trial_number=tn,
                params={"boost": 1.0},
                metrics={"ndcg@10": 0.5},
                primary_metric=0.5,
                status="complete",
            )
        await db_session.commit()

        result = await repo.get_chain_for_study(db_session, sid)
        assert result is not None
        assert result.anchor_trials is not None
        assert len(result.anchor_trials) == 3
