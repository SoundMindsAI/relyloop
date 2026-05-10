"""Study-lifecycle repo integration tests (feat_study_lifecycle Phase 1, Story 1.3).

Exercises every function in the 7 new repo modules against the real test
Postgres provisioned by CI. Skips automatically when Postgres isn't host-
reachable (the local laptop case — see ``docs/03_runbooks/local-dev.md``
§"Local-vs-CI test layers").

The fixture ``db_session`` (in ``backend/tests/conftest.py``) wraps each
test in a SAVEPOINT-style transaction that's rolled back at teardown, so
tests don't leak rows between runs and we don't need cleanup boilerplate
inside each test body.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo


def _uuid() -> str:
    return str(uuid.uuid4())


async def _seed_cluster(db: AsyncSession) -> str:
    """Create a cluster row + return its id (FK target for query_sets, etc.)."""
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


@pytest.mark.integration
class TestQueryTemplateRepo:
    """3 functions: create, get, get_by_name_version."""

    async def test_create_then_get(self, db_session: AsyncSession) -> None:
        template = await repo.create_query_template(
            db_session,
            id=_uuid(),
            name="qt-test-1",
            engine_type="elasticsearch",
            body="{}",
            declared_params={"q": "string"},
            version=1,
        )
        await db_session.commit()

        fetched = await repo.get_query_template(db_session, template.id)
        assert fetched is not None
        assert fetched.name == "qt-test-1"
        assert fetched.declared_params == {"q": "string"}

    async def test_get_returns_none_for_missing(self, db_session: AsyncSession) -> None:
        assert await repo.get_query_template(db_session, "missing-id") is None

    async def test_get_by_name_version_round_trip(self, db_session: AsyncSession) -> None:
        await repo.create_query_template(
            db_session,
            id=_uuid(),
            name="qt-versioned",
            engine_type="elasticsearch",
            body="{}",
            declared_params={},
            version=1,
        )
        await repo.create_query_template(
            db_session,
            id=_uuid(),
            name="qt-versioned",
            engine_type="elasticsearch",
            body="{}",
            declared_params={},
            version=2,
        )
        await db_session.commit()

        v1 = await repo.get_query_template_by_name_version(db_session, "qt-versioned", 1)
        v2 = await repo.get_query_template_by_name_version(db_session, "qt-versioned", 2)
        v3 = await repo.get_query_template_by_name_version(db_session, "qt-versioned", 3)
        assert v1 is not None and v1.version == 1
        assert v2 is not None and v2.version == 2
        assert v3 is None


@pytest.mark.integration
class TestQuerySetRepo:
    """2 functions: create, get."""

    async def test_create_then_get(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            description="desc",
            cluster_id=cluster_id,
        )
        await db_session.commit()

        fetched = await repo.get_query_set(db_session, query_set.id)
        assert fetched is not None
        assert fetched.cluster_id == cluster_id

    async def test_get_returns_none_for_missing(self, db_session: AsyncSession) -> None:
        assert await repo.get_query_set(db_session, "missing-id") is None


@pytest.mark.integration
class TestQueryRepo:
    """2 functions: create, list_queries_for_set."""

    async def test_create_and_list_round_trip(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster_id,
        )
        for text in ["red shoes", "blue hat", "green shirt"]:
            await repo.create_query(
                db_session,
                id=_uuid(),
                query_set_id=query_set.id,
                query_text=text,
            )
        await db_session.commit()

        queries = await repo.list_queries_for_set(db_session, query_set.id)
        assert len(queries) == 3
        assert sorted(q.query_text for q in queries) == ["blue hat", "green shirt", "red shoes"]

    async def test_metadata_via_query_metadata_attr(self, db_session: AsyncSession) -> None:
        """The `metadata` DB column is exposed as `query_metadata` on the ORM model
        (cycle-1 GPT-5.5 F5 fix)."""
        cluster_id = await _seed_cluster(db_session)
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster_id,
        )
        query = await repo.create_query(
            db_session,
            id=_uuid(),
            query_set_id=query_set.id,
            query_text="x",
            query_metadata={"vertical": "shoes", "language": "en"},
        )
        await db_session.commit()
        assert query.query_metadata == {"vertical": "shoes", "language": "en"}


@pytest.mark.integration
class TestJudgmentListRepo:
    """2 functions: create, get."""

    async def test_create_then_get(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster_id,
        )
        judgment_list = await repo.create_judgment_list(
            db_session,
            id=_uuid(),
            name=f"jl-{_uuid()[:8]}",
            query_set_id=query_set.id,
            cluster_id=cluster_id,
            target="products",
            rubric="rate 0-3",
            status="complete",
        )
        await db_session.commit()

        fetched = await repo.get_judgment_list(db_session, judgment_list.id)
        assert fetched is not None
        assert fetched.target == "products"


@pytest.mark.integration
class TestStudyRepo:
    """2 functions: create, get."""

    async def test_create_then_get(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template = await repo.create_query_template(
            db_session,
            id=_uuid(),
            name=f"qt-{_uuid()[:8]}",
            engine_type="elasticsearch",
            body="{}",
            declared_params={},
        )
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster_id,
        )
        judgment_list = await repo.create_judgment_list(
            db_session,
            id=_uuid(),
            name=f"jl-{_uuid()[:8]}",
            query_set_id=query_set.id,
            cluster_id=cluster_id,
            target="products",
            rubric="rate",
            status="complete",
        )
        sid = _uuid()
        study = await repo.create_study(
            db_session,
            id=sid,
            name="study-test",
            cluster_id=cluster_id,
            target="products",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 50, "parallelism": 4},
            status="queued",
            optuna_study_name=sid,
        )
        await db_session.commit()

        fetched = await repo.get_study(db_session, study.id)
        assert fetched is not None
        assert fetched.status == "queued"
        assert fetched.optuna_study_name == sid


@pytest.mark.integration
class TestTrialRepo:
    """2 functions: create, list_trials_for_study."""

    async def test_create_and_list_ordered_by_trial_number(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template = await repo.create_query_template(
            db_session,
            id=_uuid(),
            name=f"qt-{_uuid()[:8]}",
            engine_type="elasticsearch",
            body="{}",
            declared_params={},
        )
        query_set = await repo.create_query_set(
            db_session,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster_id,
        )
        judgment_list = await repo.create_judgment_list(
            db_session,
            id=_uuid(),
            name=f"jl-{_uuid()[:8]}",
            query_set_id=query_set.id,
            cluster_id=cluster_id,
            target="products",
            rubric="rate",
            status="complete",
        )
        sid = _uuid()
        await repo.create_study(
            db_session,
            id=sid,
            name="study-trial-test",
            cluster_id=cluster_id,
            target="products",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={},
            status="running",
            optuna_study_name=sid,
        )
        # Insert in reverse-trial-number order; the listing should re-sort.
        for trial_num in [3, 1, 2]:
            await repo.create_trial(
                db_session,
                id=_uuid(),
                study_id=sid,
                optuna_trial_number=trial_num,
                params={"boost": 1.0},
                metrics={"ndcg@10": 0.5 + 0.1 * trial_num},
                primary_metric=0.5 + 0.1 * trial_num,
                status="complete",
            )
        await db_session.commit()

        trials = await repo.list_trials_for_study(db_session, sid)
        assert [t.optuna_trial_number for t in trials] == [1, 2, 3]


@pytest.mark.integration
class TestProposalRepo:
    """2 functions: create, get."""

    async def test_create_then_get_with_study_link(self, db_session: AsyncSession) -> None:
        cluster_id = await _seed_cluster(db_session)
        template = await repo.create_query_template(
            db_session,
            id=_uuid(),
            name=f"qt-{_uuid()[:8]}",
            engine_type="elasticsearch",
            body="{}",
            declared_params={},
        )
        proposal = await repo.create_proposal(
            db_session,
            id=_uuid(),
            cluster_id=cluster_id,
            template_id=template.id,
            config_diff={"title_boost": {"from": 1.0, "to": 2.0}},
            status="pending",
        )
        await db_session.commit()

        fetched = await repo.get_proposal(db_session, proposal.id)
        assert fetched is not None
        assert fetched.config_diff == {"title_boost": {"from": 1.0, "to": 2.0}}
        assert fetched.study_id is None  # hand-crafted-style proposal
        assert fetched.pr_state is None  # not yet opened
