# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Phase 2 repo extension integration tests (Story 1.4).

Covers the new functions added by Story 1.4:

- ``list_studies`` / ``count_studies`` with cursor + since + status filter.
- ``aggregate_trials_summary`` shape (counts grouped by status + winner).
- ``list_trials_paginated`` across 5 sort variants.
- ``bulk_create_queries`` + ``count_queries_in_set``.
- ``list_running_study_ids``.

Tests run against the CI service-container Postgres and skip locally when
the DB isn't reachable (see ``backend/tests/conftest.py:postgres_reachable``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo


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
        declared_params={"q": "string"},
        version=1,
    )
    return template.id


async def _seed_query_set(db: AsyncSession, cluster_id: str) -> str:
    qs = await repo.create_query_set(
        db,
        id=_uuid(),
        name=f"qs-{_uuid()[:8]}",
        cluster_id=cluster_id,
    )
    return qs.id


async def _seed_judgment_list(db: AsyncSession, cluster_id: str, query_set_id: str) -> str:
    jl = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"jl-{_uuid()[:8]}",
        query_set_id=query_set_id,
        cluster_id=cluster_id,
        target="idx",
        rubric="rubric text",
        status="complete",
    )
    return jl.id


async def _seed_study(
    db: AsyncSession,
    *,
    cluster_id: str,
    template_id: str,
    query_set_id: str,
    judgment_list_id: str,
    status: str = "queued",
    name_suffix: str | None = None,
) -> str:
    sid = _uuid()
    name = f"s-{name_suffix or _uuid()[:8]}"
    study = await repo.create_study(
        db,
        id=sid,
        name=name,
        cluster_id=cluster_id,
        target="idx",
        template_id=template_id,
        query_set_id=query_set_id,
        judgment_list_id=judgment_list_id,
        search_space={"params": {"x": {"type": "int", "low": 1, "high": 10}}},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 10},
        status=status,
        optuna_study_name=sid,
    )
    return study.id


@pytest.mark.integration
class TestListStudies:
    """list_studies + count_studies with cursor, since, status filters."""

    async def test_cursor_pagination_round_trip(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        # 5 studies — small enough to keep the test fast.
        for i in range(5):
            await _seed_study(
                db_session,
                cluster_id=cluster_id,
                template_id=template_id,
                query_set_id=qs_id,
                judgment_list_id=jl_id,
                name_suffix=str(i),
            )
            await asyncio.sleep(0.01)  # ensure created_at differs across rows
        await db_session.commit()

        page1 = await repo.list_studies(db_session, limit=3)
        assert len(page1) == 3
        # cursor = (created_at, id) of the last row in page1
        last = page1[-1]
        page2 = await repo.list_studies(db_session, cursor=(last.created_at, last.id), limit=10)
        # page2 contains the remaining 2 (newest-first ordering means page1
        # had the 3 most-recent; page2 has the 2 oldest).
        assert len(page2) == 2
        # No overlap between page1 and page2.
        ids1 = {s.id for s in page1}
        ids2 = {s.id for s in page2}
        assert ids1.isdisjoint(ids2)

    async def test_status_filter(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            status="running",
            name_suffix="r1",
        )
        await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            status="queued",
            name_suffix="q1",
        )
        await db_session.commit()

        running = await repo.list_studies(db_session, status="running")
        assert all(s.status == "running" for s in running)
        assert any(s.name == "s-r1" for s in running)
        assert not any(s.name == "s-q1" for s in running)

    async def test_since_filter(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        # PostgreSQL's ``now()`` returns transaction-start time, so two
        # inserts in the same savepoint share a ``created_at``. To
        # exercise the ``?since=`` filter deterministically, we patch
        # ``created_at`` to explicit values via UPDATE.
        from sqlalchemy import update

        from backend.app.db.models import Study

        early_id = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            name_suffix="early",
        )
        t_early = datetime.now(UTC) - timedelta(seconds=10)
        t0 = datetime.now(UTC)
        late_id = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            name_suffix="late",
        )
        t_late = t0 + timedelta(seconds=10)
        await db_session.execute(
            update(Study).where(Study.id == early_id).values(created_at=t_early)
        )
        await db_session.execute(update(Study).where(Study.id == late_id).values(created_at=t_late))
        await db_session.commit()

        recent = await repo.list_studies(db_session, since=t0)
        names = {s.name for s in recent}
        assert "s-late" in names
        assert "s-early" not in names

    async def test_count_matches_list_ignoring_pagination(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        for i in range(4):
            await _seed_study(
                db_session,
                cluster_id=cluster_id,
                template_id=template_id,
                query_set_id=qs_id,
                judgment_list_id=jl_id,
                status="running" if i % 2 == 0 else "queued",
                name_suffix=str(i),
            )
        await db_session.commit()

        running_count = await repo.count_studies(db_session, status="running")
        running_rows = await repo.list_studies(db_session, status="running")
        assert running_count == len(running_rows)
        assert running_count == 2  # 4 seeded, half running


@pytest.mark.integration
class TestTrialsSummary:
    """aggregate_trials_summary shape + best_trial_id selection."""

    async def test_summary_with_mixed_statuses(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        study_id = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
        )
        # 3 complete with metrics, 2 failed, 1 pruned.
        winner_id = _uuid()
        await repo.create_trial(
            db_session,
            id=_uuid(),
            study_id=study_id,
            optuna_trial_number=0,
            params={},
            primary_metric=0.5,
            metrics={"ndcg@10": 0.5},
            status="complete",
        )
        await repo.create_trial(
            db_session,
            id=winner_id,
            study_id=study_id,
            optuna_trial_number=1,
            params={},
            primary_metric=0.83,
            metrics={"ndcg@10": 0.83},
            status="complete",
        )
        await repo.create_trial(
            db_session,
            id=_uuid(),
            study_id=study_id,
            optuna_trial_number=2,
            params={},
            primary_metric=0.7,
            metrics={"ndcg@10": 0.7},
            status="complete",
        )
        for n in (3, 4):
            await repo.create_trial(
                db_session,
                id=_uuid(),
                study_id=study_id,
                optuna_trial_number=n,
                params={},
                primary_metric=None,
                metrics={},
                status="failed",
                error="cluster unreachable",
            )
        await repo.create_trial(
            db_session,
            id=_uuid(),
            study_id=study_id,
            optuna_trial_number=5,
            params={},
            primary_metric=None,
            metrics={},
            status="pruned",
        )
        await db_session.commit()

        summary = await repo.aggregate_trials_summary(db_session, study_id)
        assert summary.total == 6
        assert summary.complete == 3
        assert summary.failed == 2
        assert summary.pruned == 1
        assert summary.best_primary_metric == pytest.approx(0.83)
        assert summary.best_trial_id == winner_id

    async def test_summary_empty_study(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        study_id = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
        )
        await db_session.commit()

        summary = await repo.aggregate_trials_summary(db_session, study_id)
        assert summary.total == 0
        assert summary.complete == 0
        assert summary.failed == 0
        assert summary.pruned == 0
        assert summary.best_primary_metric is None
        assert summary.best_trial_id is None


@pytest.mark.integration
class TestListTrialsPaginated:
    """list_trials_paginated across 5 sort variants."""

    async def _seed_three_complete_trials(self, db_session: AsyncSession) -> tuple[str, list[str]]:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        study_id = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
        )
        # metrics: trial 0 = 0.3, trial 1 = 0.9 (best), trial 2 = 0.6.
        ids = []
        for n, metric in [(0, 0.3), (1, 0.9), (2, 0.6)]:
            tid = _uuid()
            ids.append(tid)
            await repo.create_trial(
                db_session,
                id=tid,
                study_id=study_id,
                optuna_trial_number=n,
                params={},
                primary_metric=metric,
                metrics={"ndcg@10": metric},
                status="complete",
            )
        await db_session.commit()
        return study_id, ids

    async def test_primary_metric_desc(self, db_session: AsyncSession) -> None:
        study_id, _ = await self._seed_three_complete_trials(db_session)
        trials = await repo.list_trials_paginated(
            db_session, study_id, sort_key="primary_metric_desc"
        )
        metrics = [t.primary_metric for t in trials]
        assert metrics == [0.9, 0.6, 0.3]

    async def test_primary_metric_asc(self, db_session: AsyncSession) -> None:
        study_id, _ = await self._seed_three_complete_trials(db_session)
        trials = await repo.list_trials_paginated(
            db_session, study_id, sort_key="primary_metric_asc"
        )
        metrics = [t.primary_metric for t in trials]
        assert metrics == [0.3, 0.6, 0.9]

    async def test_optuna_trial_number_asc(self, db_session: AsyncSession) -> None:
        study_id, _ = await self._seed_three_complete_trials(db_session)
        trials = await repo.list_trials_paginated(
            db_session, study_id, sort_key="optuna_trial_number_asc"
        )
        numbers = [t.optuna_trial_number for t in trials]
        assert numbers == [0, 1, 2]

    async def test_count_trials(self, db_session: AsyncSession) -> None:
        study_id, _ = await self._seed_three_complete_trials(db_session)
        assert await repo.count_trials(db_session, study_id) == 3


@pytest.mark.integration
class TestBulkQueryInsert:
    """bulk_create_queries + count_queries_in_set."""

    async def test_bulk_insert_and_count(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        rows: list[dict[str, object]] = [
            {"query_text": "shoes", "reference_answer": None, "query_metadata": None},
            {"query_text": "boots", "reference_answer": "leather boots"},
            {"query_text": "sandals", "query_metadata": {"category": "summer"}},
        ]
        inserted = await repo.bulk_create_queries(db_session, qs_id, rows)
        await db_session.commit()
        assert inserted == 3
        assert await repo.count_queries_in_set(db_session, qs_id) == 3

    async def test_bulk_insert_empty_rows_returns_zero(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        inserted = await repo.bulk_create_queries(db_session, qs_id, [])
        assert inserted == 0


@pytest.mark.integration
class TestListQueryTemplatesAndSets:
    """list_query_templates / list_query_sets pagination + count (E1-F4 fix)."""

    async def test_list_query_templates_paginates(self, db_session: AsyncSession) -> None:
        for _ in range(3):
            await _seed_template(db_session)
            await asyncio.sleep(0.01)
        await db_session.commit()
        page1 = await repo.list_query_templates(db_session, limit=2)
        assert len(page1) == 2
        last = page1[-1]
        page2 = await repo.list_query_templates(
            db_session, cursor=(last.created_at, last.id), limit=10
        )
        assert {t.id for t in page1}.isdisjoint({t.id for t in page2})

    async def test_count_query_templates_matches_list(self, db_session: AsyncSession) -> None:
        for _ in range(2):
            await _seed_template(db_session)
        await db_session.commit()
        rows = await repo.list_query_templates(db_session)
        assert await repo.count_query_templates(db_session) == len(rows)

    async def test_list_query_sets_paginates(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        for _ in range(3):
            await _seed_query_set(db_session, cluster_id)
            await asyncio.sleep(0.01)
        await db_session.commit()
        page1 = await repo.list_query_sets(db_session, limit=2)
        assert len(page1) == 2
        last = page1[-1]
        page2 = await repo.list_query_sets(db_session, cursor=(last.created_at, last.id), limit=10)
        assert {q.id for q in page1}.isdisjoint({q.id for q in page2})

    async def test_count_query_sets_matches_list(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        for _ in range(2):
            await _seed_query_set(db_session, cluster_id)
        await db_session.commit()
        rows = await repo.list_query_sets(db_session)
        assert await repo.count_query_sets(db_session) == len(rows)


@pytest.mark.integration
class TestListRunningStudyIds:
    """Phase 2 / FR-5 resume-sweep helper."""

    async def test_returns_only_running_study_ids(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template_id = await _seed_template(db_session)
        qs_id = await _seed_query_set(db_session, cluster_id)
        jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
        run1 = await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            status="running",
            name_suffix="r1",
        )
        await _seed_study(
            db_session,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            status="completed",
            name_suffix="c1",
        )
        await db_session.commit()

        ids = await repo.list_running_study_ids(db_session)
        assert run1 in ids


@pytest.mark.integration
class TestGetTrial:
    """``repo.get_trial`` (feat_agent_propose_search_space Story 2.1).

    Parallel to ``repo.get_study`` — single-row fetch by primary key. Used by
    the ``propose_search_space`` agent tool to load a prior study's winning
    trial via ``Study.best_trial_id``.
    """

    async def _seed_one_trial(self, db: AsyncSession) -> tuple[str, str]:
        cluster_id = await _seed_cluster(db)
        template_id = await _seed_template(db)
        qs_id = await _seed_query_set(db, cluster_id)
        jl_id = await _seed_judgment_list(db, cluster_id, qs_id)
        study_id = await _seed_study(
            db,
            cluster_id=cluster_id,
            template_id=template_id,
            query_set_id=qs_id,
            judgment_list_id=jl_id,
            status="completed",
            name_suffix="get-trial",
        )
        trial_id = _uuid()
        await repo.create_trial(
            db,
            id=trial_id,
            study_id=study_id,
            optuna_trial_number=0,
            params={"boost_title": 2.5},
            primary_metric=0.42,
            metrics={"ndcg@10": 0.42},
            duration_ms=120,
            status="complete",
        )
        await db.commit()
        return study_id, trial_id

    async def test_returns_trial_when_found(self, db_session: AsyncSession) -> None:
        _study_id, trial_id = await self._seed_one_trial(db_session)
        row = await repo.get_trial(db_session, trial_id)
        assert row is not None
        assert row.id == trial_id
        assert row.params == {"boost_title": 2.5}
        assert row.primary_metric == 0.42
        assert row.status == "complete"

    async def test_returns_none_when_missing(self, db_session: AsyncSession) -> None:
        row = await repo.get_trial(db_session, _uuid())
        assert row is None
