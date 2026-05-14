"""Integration tests for query repo extensions (feat_query_inline_crud).

Covers:

* :func:`get_query` — single fetch / missing returns ``None``.
* :func:`count_queries_for_set` — total count, with and without ``?since``.
* :func:`list_queries_for_set_cursor` — pagination by ``after_id``, ``?since``
  by UUIDv7 lower bound, ordering by ``id ASC``.
* :func:`update_query` — single-field, multi-field, explicit-null,
  empty-fields_set short-circuit.
* :func:`delete_query` — raises ``IntegrityError`` when judgments exist.
* :func:`count_judgments_per_query` — batch helper, post-fills zeros.

DB-backed via the existing service-container Postgres + ``get_session_factory``.
"""

from __future__ import annotations

import uuid

import pytest
import uuid_utils
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


async def _seed_set_with_queries(num_queries: int = 3) -> tuple[str, list[str]]:
    """Seed cluster → query_set → N queries; return (set_id, [query_ids])."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qre-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qre-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(num_queries):
            q = await repo.create_query(
                db,
                id=str(uuid_utils.uuid7()),
                query_set_id=qs.id,
                query_text=f"q-{i}",
                reference_answer=None if i % 2 == 0 else f"ref-{i}",
                query_metadata={"i": i} if i % 2 == 0 else None,
            )
            query_ids.append(q.id)
        await db.commit()
    return qs.id, query_ids


# ---------------------------------------------------------------------------
# get_query
# ---------------------------------------------------------------------------


async def test_get_query_returns_row() -> None:
    set_id, [q1, *_] = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_query(db, q1)
        assert row is not None
        assert row.id == q1
        assert row.query_set_id == set_id


async def test_get_query_returns_none_for_missing() -> None:
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_query(db, "00000000-0000-7000-8000-000000000000")
        assert row is None


# ---------------------------------------------------------------------------
# count_queries_for_set
# ---------------------------------------------------------------------------


async def test_count_queries_for_set_no_filter() -> None:
    set_id, _ = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        assert await repo.count_queries_for_set(db, set_id) == 5


async def test_count_queries_for_set_with_since_filter() -> None:
    """``since_lower_bound_id`` filters out queries minted before the boundary."""
    set_id, query_ids = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        # query_ids are UUIDv7 → lexically sorted. Filter on q[2] (inclusive) = 3 rows.
        result = await repo.count_queries_for_set(db, set_id, since_lower_bound_id=query_ids[2])
        assert result == 3


async def test_count_queries_for_set_empty_set() -> None:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qre-empty-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qre-empty-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        await db.commit()
        assert await repo.count_queries_for_set(db, qs.id) == 0


# ---------------------------------------------------------------------------
# list_queries_for_set_cursor
# ---------------------------------------------------------------------------


async def test_list_cursor_first_page() -> None:
    set_id, query_ids = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_queries_for_set_cursor(db, set_id, limit=3)
        assert len(rows) == 3
        # UUIDv7 lexical ordering = creation order
        assert [r.id for r in rows] == query_ids[:3]


async def test_list_cursor_with_after_id_excludes_cursor_row() -> None:
    set_id, query_ids = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        # cursor on q[2] → exclusive → returns q[3], q[4]
        rows = await repo.list_queries_for_set_cursor(db, set_id, after_id=query_ids[2], limit=10)
        assert [r.id for r in rows] == query_ids[3:]


async def test_list_cursor_with_since_inclusive_boundary() -> None:
    """``?since`` is inclusive — a row minted exactly at the boundary appears."""
    set_id, query_ids = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_queries_for_set_cursor(
            db, set_id, since_lower_bound_id=query_ids[2], limit=10
        )
        # Inclusive — includes q[2]
        assert [r.id for r in rows] == query_ids[2:]


async def test_list_cursor_with_cursor_plus_since() -> None:
    """``after_id`` AND ``since_lower_bound_id`` compose."""
    set_id, query_ids = await _seed_set_with_queries(5)
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_queries_for_set_cursor(
            db,
            set_id,
            after_id=query_ids[2],
            since_lower_bound_id=query_ids[1],
            limit=10,
        )
        # after_id is stricter than since here (after excludes q[2], since includes q[1])
        # Intersection: q[3], q[4]
        assert [r.id for r in rows] == query_ids[3:]


async def test_list_cursor_empty_set() -> None:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qre-lst-empty-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qre-lst-empty-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        await db.commit()
        rows = await repo.list_queries_for_set_cursor(db, qs.id)
        assert rows == []


async def test_list_cursor_limit_equals_total() -> None:
    set_id, query_ids = await _seed_set_with_queries(3)
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_queries_for_set_cursor(db, set_id, limit=3)
        assert [r.id for r in rows] == query_ids


# ---------------------------------------------------------------------------
# update_query
# ---------------------------------------------------------------------------


async def test_update_query_single_field() -> None:
    _, query_ids = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.update_query(db, query_ids[0], fields_set={"query_text": "new text"})
        await db.commit()
        assert updated is not None
        assert updated.query_text == "new text"

    # Verify other fields unchanged.
    async with factory() as db:
        check = await repo.get_query(db, query_ids[0])
        assert check is not None
        assert check.query_text == "new text"
        # q_0 had query_metadata={"i":0}, reference_answer=None per seed
        assert check.query_metadata == {"i": 0}
        assert check.reference_answer is None


async def test_update_query_multi_field() -> None:
    _, query_ids = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.update_query(
            db,
            query_ids[0],
            fields_set={"query_text": "x", "reference_answer": "y", "query_metadata": {"new": 1}},
        )
        await db.commit()
        assert updated is not None
        assert updated.query_text == "x"
        assert updated.reference_answer == "y"
        assert updated.query_metadata == {"new": 1}


async def test_update_query_explicit_null_metadata() -> None:
    """Explicit ``query_metadata=None`` overwrites the JSONB column to NULL."""
    _, query_ids = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.update_query(db, query_ids[0], fields_set={"query_metadata": None})
        await db.commit()
        assert updated is not None
        assert updated.query_metadata is None


async def test_update_query_empty_fields_set_short_circuits() -> None:
    """Empty ``fields_set`` returns the current row (AC-28 no-op)."""
    _, query_ids = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.update_query(db, query_ids[0], fields_set={})
        assert result is not None
        assert result.id == query_ids[0]
        # query_text from seed: "q-0"
        assert result.query_text == "q-0"


async def test_update_query_missing_returns_none() -> None:
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.update_query(
            db, "00000000-0000-7000-8000-000000000000", fields_set={"query_text": "x"}
        )
        assert result is None


# ---------------------------------------------------------------------------
# delete_query — FK guard via IntegrityError
# ---------------------------------------------------------------------------


async def test_delete_query_no_judgments_succeeds() -> None:
    _, query_ids = await _seed_set_with_queries(2)
    factory = get_session_factory()
    async with factory() as db:
        await repo.delete_query(db, query_ids[0])
        await db.commit()
        row = await repo.get_query(db, query_ids[0])
        assert row is None


async def test_delete_query_with_judgments_raises_integrity_error() -> None:
    """Postgres FK check fires synchronously on flush."""
    set_id, query_ids = await _seed_set_with_queries(2)

    # Seed a judgment list + a judgment referencing q[0].
    factory = get_session_factory()
    async with factory() as db:
        qs = await repo.get_query_set(db, set_id)
        assert qs is not None
        cluster_id = qs.cluster_id
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qre-jl-{uuid.uuid4().hex[:8]}",
            query_set_id=set_id,
            cluster_id=cluster_id,
            target="test-index",
            rubric="rubric-v1",
            status="complete",
        )
        await repo.create_judgment(
            db,
            id=str(uuid_utils.uuid7()),
            judgment_list_id=jl.id,
            query_id=query_ids[0],
            doc_id="doc-1",
            rating=2,
            source="llm",
            rater_ref="openai:test",
        )
        await db.commit()

    # Now attempt the delete — should raise IntegrityError on flush.
    async with factory() as db:
        with pytest.raises(IntegrityError):
            await repo.delete_query(db, query_ids[0])

    # Verify the row still exists post-rollback.
    async with factory() as db:
        row = await repo.get_query(db, query_ids[0])
        assert row is not None


# ---------------------------------------------------------------------------
# count_judgments_per_query — Story 1.3 batch helper
# ---------------------------------------------------------------------------


async def test_count_judgments_per_query_empty_input() -> None:
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.count_judgments_per_query(db, [])
        assert result == {}


async def test_count_judgments_per_query_mixed_counts() -> None:
    set_id, query_ids = await _seed_set_with_queries(3)
    factory = get_session_factory()
    async with factory() as db:
        qs = await repo.get_query_set(db, set_id)
        assert qs is not None
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qre-cnt-{uuid.uuid4().hex[:8]}",
            query_set_id=set_id,
            cluster_id=qs.cluster_id,
            target="test-index",
            rubric="rubric-v1",
            status="complete",
        )
        # 5 judgments on q[0], 2 on q[1], 0 on q[2]
        for i in range(5):
            await repo.create_judgment(
                db,
                id=str(uuid_utils.uuid7()),
                judgment_list_id=jl.id,
                query_id=query_ids[0],
                doc_id=f"doc-{i}",
                rating=2,
                source="llm",
                rater_ref="openai:test",
            )
        for i in range(2):
            await repo.create_judgment(
                db,
                id=str(uuid_utils.uuid7()),
                judgment_list_id=jl.id,
                query_id=query_ids[1],
                doc_id=f"doc-{i}",
                rating=2,
                source="llm",
                rater_ref="openai:test",
            )
        await db.commit()

        counts = await repo.count_judgments_per_query(db, query_ids)
        assert counts == {query_ids[0]: 5, query_ids[1]: 2, query_ids[2]: 0}


async def test_count_judgments_per_query_post_fills_zeros() -> None:
    """A query with zero judgments is in the result dict with value 0."""
    _, query_ids = await _seed_set_with_queries(3)
    factory = get_session_factory()
    async with factory() as db:
        counts = await repo.count_judgments_per_query(db, query_ids)
        assert counts == {qid: 0 for qid in query_ids}
