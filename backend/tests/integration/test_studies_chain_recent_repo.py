# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``list_recent_completed_chains``
(feat_overnight_studies_summary_card Story 1.1).

Exercises the recent-completed-chains discovery repo helper against the
real test Postgres. Covers the spec ACs the repo layer owns:

* AC-12 — multi-link chain returned exactly once (anchor dedup)
* AC-2  — single-study (length 1) excluded
* AC-3  — ``since`` boundary filter
* AC-4  — chain with an in-flight interior link excluded
* AC-11 — terminal-failed chain returned with its derived shape intact
* Plus the concurrent-delete safety net: a candidate whose chain is
  hard-deleted between the candidate query and the traversal is skipped,
  never raised.
"""

from __future__ import annotations

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


class _Fixtures:
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
    completed_at: datetime | None = None,
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
        completed_at=completed_at,
    )
    return sid


@pytest.mark.integration
class TestListRecentCompletedChains:
    async def test_no_chains_returns_empty(self, db_session: AsyncSession) -> None:
        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)
        assert result == []

    async def test_three_link_chain_returned_once_with_correct_anchor(
        self, db_session: AsyncSession
    ) -> None:
        """AC-12: dedup — a 3-link chain shows up as exactly ONE row keyed
        on the anchor, even though candidates B and C both qualify.
        """
        fx = await _seed_fixtures(db_session)
        anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.65,
            baseline_metric=0.60,
            created_at=_BASE,
            completed_at=_BASE + timedelta(minutes=5),
        )
        mid = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=anchor,
            best_metric=0.72,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        tail = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=mid,
            best_metric=0.74,
            created_at=_BASE + timedelta(hours=2),
            completed_at=_BASE + timedelta(hours=2, minutes=5),
        )
        await db_session.commit()

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)

        assert len(result) == 1
        traversal = result[0]
        assert traversal.anchor_id == anchor
        assert [s.id for s in traversal.links] == [anchor, mid, tail]

    async def test_single_study_excluded(self, db_session: AsyncSession) -> None:
        """AC-2: a study with no parent (chain length 1) must NOT appear."""
        fx = await _seed_fixtures(db_session)
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=0.6,
            completed_at=_BASE + timedelta(minutes=5),
        )
        await db_session.commit()

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)
        assert result == []

    async def test_since_boundary_excludes_older_chain(self, db_session: AsyncSession) -> None:
        """AC-3: ``since`` filters chains whose terminal members completed
        before the cutoff. Inclusive at the cutoff (``completed_at >= since``).
        """
        fx = await _seed_fixtures(db_session)
        old_anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.6,
            baseline_metric=0.5,
            created_at=_BASE,
            completed_at=_BASE + timedelta(minutes=5),
        )
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=old_anchor,
            best_metric=0.65,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1),  # before `since` cutoff
        )
        new_anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=0.6,
            created_at=_BASE + timedelta(hours=10),
            completed_at=_BASE + timedelta(hours=10, minutes=5),
        )
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=new_anchor,
            best_metric=0.74,
            created_at=_BASE + timedelta(hours=11),
            completed_at=_BASE + timedelta(hours=11, minutes=5),
        )
        await db_session.commit()

        cutoff = _BASE + timedelta(hours=5)
        result = await repo.list_recent_completed_chains(db_session, since=cutoff, limit=20)

        assert len(result) == 1
        assert result[0].anchor_id == new_anchor

    async def test_in_flight_chain_excluded(self, db_session: AsyncSession) -> None:
        """AC-4: a chain whose interior link is still running must NOT
        appear. The candidate query already excludes non-terminal tails;
        this test exercises the defensive in-flight skip on the resolved
        traversal.
        """
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
            completed_at=_BASE + timedelta(minutes=5),
        )
        # Mid link terminated and qualifies as a candidate via its
        # completed_at + parent_study_id IS NOT NULL. Tail is still running
        # → derive_chain_stop_reason returns "in_flight" → excluded.
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=anchor,
            best_metric=0.7,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        mid = (
            await db_session.execute(
                text("SELECT id FROM studies WHERE parent_study_id = :a"), {"a": anchor}
            )
        ).scalar_one()
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=mid,
            status="running",
            best_metric=None,
            created_at=_BASE + timedelta(hours=2),
            completed_at=None,
        )
        await db_session.commit()

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)
        assert result == []

    async def test_terminal_failed_chain_returned(self, db_session: AsyncSession) -> None:
        """AC-11 data path: a chain whose tail is terminal-failed (parent
        followup failed → chain terminated) is included in the result
        with its derived shape intact (failed tail, no best_metric).
        """
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
            completed_at=_BASE + timedelta(minutes=5),
        )
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=anchor,
            status="failed",
            best_metric=None,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        await db_session.commit()

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)

        assert len(result) == 1
        traversal = result[0]
        assert traversal.anchor_id == anchor
        assert len(traversal.links) == 2
        # Tail status drives the downstream stop_reason → "parent_failed".
        assert traversal.links[-1].status == "failed"
        assert traversal.links[-1].best_metric is None

    async def test_concurrent_anchor_delete_skipped(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Concurrent-delete safety net — a candidate whose chain becomes
        unresolvable between the candidate query and the traversal call
        (``get_chain_for_study`` returns ``None``) must be skipped
        silently, never raised. Mirrors the chain-panel defensive skip
        at ``study.py:327-333``.

        We can't reproduce the orphan-anchor scenario directly in
        Postgres because the ``studies.parent_study_id`` self-FK blocks
        deleting an anchor that still has children. So we patch
        ``get_chain_for_study`` to return ``None`` for one specific id
        and assert the helper skips that candidate and still returns the
        surviving chain.
        """
        from backend.app.db.repo import study as study_repo

        fx = await _seed_fixtures(db_session)
        # Surviving chain we expect to see in the result.
        survive_anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.7,
            baseline_metric=0.6,
            created_at=_BASE,
            completed_at=_BASE + timedelta(minutes=5),
        )
        await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=survive_anchor,
            best_metric=0.75,
            created_at=_BASE + timedelta(hours=1),
            completed_at=_BASE + timedelta(hours=1, minutes=5),
        )
        # Disposable chain whose tail we'll force the traversal to fail
        # for (race-window stand-in). Tail completed AFTER the surviving
        # chain so it sorts first in the candidate query, exercising the
        # skip BEFORE the surviving candidate is processed.
        doomed_anchor = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            best_metric=0.5,
            baseline_metric=0.4,
            created_at=_BASE + timedelta(hours=2),
            completed_at=_BASE + timedelta(hours=2, minutes=5),
        )
        doomed_child_id = await _seed_study(
            db_session,
            cluster_id=fx.cluster_id,
            template_id=fx.template_id,
            query_set_id=fx.query_set_id,
            judgment_list_id=fx.judgment_list_id,
            parent_study_id=doomed_anchor,
            best_metric=0.55,
            created_at=_BASE + timedelta(hours=3),
            completed_at=_BASE + timedelta(hours=3, minutes=5),
        )
        await db_session.commit()

        # Patch get_chain_for_study to simulate the concurrent-delete race
        # for the doomed child specifically.
        real_get_chain = study_repo.get_chain_for_study

        async def patched_get_chain(
            db: AsyncSession, study_id: str
        ) -> study_repo.ChainTraversalResult | None:
            if study_id == doomed_child_id:
                return None
            return await real_get_chain(db, study_id)

        monkeypatch.setattr(study_repo, "get_chain_for_study", patched_get_chain)

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=20)

        # The doomed candidate is silently skipped; the surviving chain
        # remains.
        assert len(result) == 1
        assert result[0].anchor_id == survive_anchor

    async def test_limit_caps_distinct_chains(self, db_session: AsyncSession) -> None:
        """Sanity: ``limit`` actually caps the number of distinct chains
        returned, AND the candidate scan-cap (``limit * 5``) is generous
        enough to fill a small limit even when every chain is minimum-length.
        """
        fx = await _seed_fixtures(db_session)
        anchors: list[str] = []
        for i in range(5):
            anchor = await _seed_study(
                db_session,
                cluster_id=fx.cluster_id,
                template_id=fx.template_id,
                query_set_id=fx.query_set_id,
                judgment_list_id=fx.judgment_list_id,
                best_metric=0.6,
                baseline_metric=0.5,
                created_at=_BASE + timedelta(hours=10 * i),
                completed_at=_BASE + timedelta(hours=10 * i, minutes=5),
            )
            await _seed_study(
                db_session,
                cluster_id=fx.cluster_id,
                template_id=fx.template_id,
                query_set_id=fx.query_set_id,
                judgment_list_id=fx.judgment_list_id,
                parent_study_id=anchor,
                best_metric=0.7,
                created_at=_BASE + timedelta(hours=10 * i + 1),
                completed_at=_BASE + timedelta(hours=10 * i + 1, minutes=5),
            )
            anchors.append(anchor)
        await db_session.commit()

        result = await repo.list_recent_completed_chains(db_session, since=None, limit=3)
        assert len(result) == 3
        # Newest-first by tail completion → anchors[4], [3], [2].
        assert [t.anchor_id for t in result] == [anchors[4], anchors[3], anchors[2]]
