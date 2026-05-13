"""Integration tests for ``count_and_sample_judgment_refs`` (feat_query_inline_crud Story 3.2).

Verifies the 4-field ``JudgmentRefCounts`` return shape across the
boundary cases used by the 409 ``QUERY_HAS_JUDGMENTS`` envelope:

* 0 lists → all-zero
* 1 list, 1 judgment
* 10 lists (right at the sample cap)
* 11+ lists (overflow_count > 0)
* alphabetical ordering of ``sample_lists`` by ``name``
"""

from __future__ import annotations

import uuid

import pytest
import uuid_utils

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


async def _seed_query_with_n_lists(num_lists: int, judgments_per_list: int = 1) -> str:
    """Seed one query + ``num_lists`` judgment-lists each referencing it."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jrq-c-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"jrq-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        q = await repo.create_query(
            db,
            id=str(uuid_utils.uuid7()),
            query_set_id=qs.id,
            query_text="target",
        )
        # Seed N lists with names that sort alphabetically: list-00, list-01, …
        for i in range(num_lists):
            jl = await repo.create_judgment_list(
                db,
                id=str(uuid_utils.uuid7()),
                name=f"jrq-list-{i:03d}-{uuid.uuid4().hex[:4]}",
                query_set_id=qs.id,
                cluster_id=cluster.id,
                target="t",
                rubric="r",
                status="complete",
            )
            for j in range(judgments_per_list):
                await repo.create_judgment(
                    db,
                    id=str(uuid_utils.uuid7()),
                    judgment_list_id=jl.id,
                    query_id=q.id,
                    doc_id=f"doc-{i}-{j}",
                    rating=2,
                    source="llm",
                    rater_ref="openai:test",
                )
        await db.commit()
        return q.id


async def test_zero_lists_all_fields_zero() -> None:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jrq-empty-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"jrq-empty-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        q = await repo.create_query(
            db,
            id=str(uuid_utils.uuid7()),
            query_set_id=qs.id,
            query_text="lonely",
        )
        await db.commit()
        refs = await repo.count_and_sample_judgment_refs(db, q.id)
        assert refs.judgment_count == 0
        assert refs.list_count == 0
        assert refs.sample_lists == []
        assert refs.overflow_count == 0


async def test_one_list_one_judgment() -> None:
    qid = await _seed_query_with_n_lists(num_lists=1, judgments_per_list=1)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid)
        assert refs.judgment_count == 1
        assert refs.list_count == 1
        assert len(refs.sample_lists) == 1
        assert refs.overflow_count == 0


async def test_ten_lists_at_sample_cap() -> None:
    qid = await _seed_query_with_n_lists(num_lists=10, judgments_per_list=2)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid)
        assert refs.judgment_count == 20  # 10 lists × 2 judgments
        assert refs.list_count == 10
        assert len(refs.sample_lists) == 10
        assert refs.overflow_count == 0  # exactly at the cap


async def test_eleven_lists_overflow_one() -> None:
    qid = await _seed_query_with_n_lists(num_lists=11, judgments_per_list=1)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid)
        assert refs.judgment_count == 11
        assert refs.list_count == 11
        assert len(refs.sample_lists) == 10
        assert refs.overflow_count == 1


async def test_fifteen_lists_overflow_five() -> None:
    qid = await _seed_query_with_n_lists(num_lists=15, judgments_per_list=3)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid)
        assert refs.judgment_count == 45
        assert refs.list_count == 15
        assert len(refs.sample_lists) == 10
        assert refs.overflow_count == 5


async def test_sample_lists_alphabetical_by_name() -> None:
    qid = await _seed_query_with_n_lists(num_lists=5)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid)
        names = [r.name for r in refs.sample_lists]
        assert names == sorted(names), f"sample_lists must be alphabetical; got {names!r}"


async def test_custom_sample_limit() -> None:
    """The helper accepts a non-default ``sample_limit`` keyword."""
    qid = await _seed_query_with_n_lists(num_lists=5)
    factory = get_session_factory()
    async with factory() as db:
        refs = await repo.count_and_sample_judgment_refs(db, qid, sample_limit=2)
        assert refs.list_count == 5
        assert len(refs.sample_lists) == 2
        assert refs.overflow_count == 3
