"""Repo unit-of-work tests for feat_digest_proposal Story 1.2.

Exercises every function in :mod:`backend.app.db.repo.digest` against a real
Postgres test database. Mirrors the
``backend/tests/integration/test_judgment_repo.py`` pattern.

Covers:

* :func:`create_digest` + :func:`get_digest_for_study`
* UNIQUE on ``study_id`` enforcement (one digest per study)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

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


async def _seed_study() -> str:
    """Insert the minimal parent chain a digest needs; return the study_id."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"dr-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"dr-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"dr-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"dr-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        study = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"dr-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective={},
            config={},
            status="completed",
            optuna_study_name=str(uuid.uuid4()),
        )
        await db.commit()
        return study.id


async def test_create_digest_and_fetch_by_study() -> None:
    """Round-trip create_digest + get_digest_for_study."""
    study_id = await _seed_study()
    digest_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as db:
        d = await repo.create_digest(
            db,
            id=digest_id,
            study_id=study_id,
            narrative="rich narrative",
            parameter_importance={"field_boosts.title": 0.5, "tie_breaker": 0.5},
            recommended_config={"field_boosts.title": 4.5},
            # JSONB column carries the discriminated-union FollowupItem
            # shape; one ``text`` item is the simplest non-empty case.
            suggested_followups=[
                {"kind": "text", "rationale": "try fuzziness=AUTO", "search_space": None}
            ],
            generated_by="openai:gpt-4o-2024-08-06",
        )
        await db.commit()
        assert d.id == digest_id
        assert d.study_id == study_id
        assert d.suggested_followups == [
            {"kind": "text", "rationale": "try fuzziness=AUTO", "search_space": None}
        ]

    async with factory() as db:
        fetched = await repo.get_digest_for_study(db, study_id)
        assert fetched is not None
        assert fetched.id == digest_id
        assert fetched.narrative == "rich narrative"
        assert fetched.recommended_config == {"field_boosts.title": 4.5}


async def test_get_digest_for_study_returns_none_when_absent() -> None:
    """get_digest_for_study yields None for studies without a digest."""
    study_id = await _seed_study()
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.get_digest_for_study(db, study_id)
        assert result is None


async def test_unique_constraint_rejects_second_digest_for_same_study() -> None:
    """digests.study_id UNIQUE — one digest per study."""
    study_id = await _seed_study()
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            narrative="first",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[],
            generated_by="local:test",
        )
        await db.commit()

    with pytest.raises(IntegrityError):
        async with factory() as db:
            await repo.create_digest(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                narrative="second (forbidden)",
                parameter_importance={},
                recommended_config={},
                suggested_followups=[],
                generated_by="local:test",
            )
            await db.commit()
