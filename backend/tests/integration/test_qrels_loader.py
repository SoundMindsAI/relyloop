"""Integration tests for the real ``load_qrels`` (feat_llm_judgments Story 1.6).

Replaces the MVP1 stub-era contract with end-to-end SELECTs against a real
Postgres test database. Mirrors the seeding pattern in
``test_judgment_repo.py``.
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.qrels_loader import load_qrels
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_with_judgments(judgment_rows: list[dict[str, object]]) -> str:
    """Seed cluster/template/query_set/queries/judgment_list + judgments.

    ``judgment_rows`` contains partial rows; this helper fills in
    ``judgment_list_id``, generates ids, and commits.

    Returns the ``judgment_list_id`` so the caller can pass it to
    :func:`load_qrels`.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"ql-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"ql-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"ql-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        q1 = await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            query_text="qtext-1",
        )
        q2 = await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            query_text="qtext-2",
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"ql-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()

    # Map "q1" / "q2" placeholders in the test inputs to real ids.
    q_id_by_label = {"q1": q1.id, "q2": q2.id}
    seeded_rows: list[dict[str, object]] = []
    for row in judgment_rows:
        label = row["query_id"]
        assert isinstance(label, str)
        seeded_rows.append(
            {
                "id": str(uuid.uuid4()),
                "judgment_list_id": jl.id,
                "query_id": q_id_by_label[label],
                "doc_id": row["doc_id"],
                "rating": row["rating"],
                "source": row.get("source", "llm"),
                "rater_ref": row.get("rater_ref", "openai:test"),
                "notes": row.get("notes"),
            }
        )

    async with factory() as db:
        await repo.bulk_create_judgments(db, seeded_rows)
        await db.commit()

    return jl.id


async def test_load_qrels_returns_grouped_by_query_id() -> None:
    jl_id = await _seed_with_judgments(
        [
            {"query_id": "q1", "doc_id": "docA", "rating": 3},
            {"query_id": "q1", "doc_id": "docB", "rating": 1},
            {"query_id": "q2", "doc_id": "docA", "rating": 2},
        ]
    )
    factory = get_session_factory()
    async with factory() as db:
        qrels = await load_qrels(db, jl_id)

    assert set(qrels.keys()) == {*qrels.keys()}  # two distinct query ids
    assert len(qrels) == 2
    # All ratings preserved + cast to int.
    sample_query = next(iter(qrels.keys()))
    assert all(isinstance(rating, int) for rating in qrels[sample_query].values())


async def test_load_qrels_unknown_id_returns_empty_dict() -> None:
    """No rows → ``{}``. Callers handle empty case (no JudgmentsTableMissing
    raise in the real implementation)."""
    factory = get_session_factory()
    async with factory() as db:
        qrels = await load_qrels(db, str(uuid.uuid4()))
    assert qrels == {}


async def test_load_qrels_includes_human_overrides() -> None:
    """Human-override rows (after PATCH) are loaded just like LLM rows.

    The UPSERT replaces the LLM row in place — there's at most one row per
    (query_id, doc_id) — so the loader doesn't dedupe by source.
    """
    jl_id = await _seed_with_judgments(
        [
            {"query_id": "q1", "doc_id": "docA", "rating": 3, "source": "llm"},
            {
                "query_id": "q1",
                "doc_id": "docB",
                "rating": 2,
                "source": "human",
                "rater_ref": "operator",
            },
        ]
    )
    factory = get_session_factory()
    async with factory() as db:
        qrels = await load_qrels(db, jl_id)

    # Both ratings reach the qrels map regardless of source.
    sample_query = next(iter(qrels.keys()))
    assert qrels[sample_query] == {"docA": 3, "docB": 2}
