"""Repo unit-of-work tests for feat_llm_judgments Story 1.2.

Exercises every function in :mod:`backend.app.db.repo.judgment` and the
extensions added to :mod:`backend.app.db.repo.judgment_list` against a real
Postgres test database. Mirrors the
``backend/tests/integration/test_study_repos.py`` pattern.

Covers:

* :func:`create_judgment` + :func:`get_judgment`
* :func:`bulk_create_judgments` happy path + ``ON CONFLICT DO NOTHING``
* :func:`upsert_judgment_human_override` REPLACE semantics (FR-4 / AC-2)
* :func:`list_judgments_paginated` + cursor + source filter
* :func:`count_judgments_for_list` total + per-source
* :func:`count_judgments_for_list_and_query` (resume-skip helper)
* :func:`source_breakdown_for_list` (three-term shape; ``feat_ubi_judgments`` FR-10)
* :func:`list_judgment_lists` + :func:`count_judgment_lists`
* :func:`update_judgment_list_status` + :func:`update_judgment_list_calibration`
* :func:`list_generating_judgment_list_ids`
"""

from __future__ import annotations

import uuid

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


async def _seed_chain() -> dict[str, str]:
    """Insert a complete (cluster, template, query_set, queries, judgment_list)
    chain and return their IDs."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jr-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"jr-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jr-qs-{uuid.uuid4().hex[:8]}",
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
            name=f"jr-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="generating",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "query_id_1": q1.id,
        "query_id_2": q2.id,
        "judgment_list_id": jl.id,
    }


async def test_create_and_get_judgment() -> None:
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        judgment = await repo.create_judgment(
            db,
            id=str(uuid.uuid4()),
            judgment_list_id=ids["judgment_list_id"],
            query_id=ids["query_id_1"],
            doc_id="d1",
            rating=2,
            source="llm",
            rater_ref="openai:gpt-4o-2024-08-06",
            notes="rationale",
        )
        await db.commit()
        fetched = await repo.get_judgment(db, judgment.id)
        assert fetched is not None
        assert fetched.rating == 2
        assert fetched.source == "llm"


async def test_bulk_create_judgments_idempotent() -> None:
    ids = await _seed_chain()
    factory = get_session_factory()
    rows = [
        {
            "id": str(uuid.uuid4()),
            "judgment_list_id": ids["judgment_list_id"],
            "query_id": ids["query_id_1"],
            "doc_id": f"d{i}",
            "rating": i % 4,
            "source": "llm",
            "rater_ref": "openai:gpt-4o-2024-08-06",
            "notes": None,
        }
        for i in range(5)
    ]
    async with factory() as db:
        inserted_1 = await repo.bulk_create_judgments(db, rows)
        await db.commit()
        assert inserted_1 == 5
    async with factory() as db:
        # Same rows again → ON CONFLICT DO NOTHING → 0 inserted.
        # Use fresh IDs but the same (judgment_list_id, query_id, doc_id) keys.
        retry_rows = [{**r, "id": str(uuid.uuid4())} for r in rows]
        inserted_2 = await repo.bulk_create_judgments(db, retry_rows)
        await db.commit()
        assert inserted_2 == 0
        total = await repo.count_judgments_for_list(db, ids["judgment_list_id"])
        assert total == 5


async def test_upsert_judgment_human_override_replaces() -> None:
    """AC-2: PATCH replaces LLM row in place; source flips llm → human."""
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        original = await repo.create_judgment(
            db,
            id=str(uuid.uuid4()),
            judgment_list_id=ids["judgment_list_id"],
            query_id=ids["query_id_1"],
            doc_id="d1",
            rating=2,
            source="llm",
            rater_ref="openai:gpt-4o-2024-08-06",
            notes="llm rationale",
        )
        await db.commit()
        overridden = await repo.upsert_judgment_human_override(
            db,
            judgment_list_id=ids["judgment_list_id"],
            query_id=ids["query_id_1"],
            doc_id="d1",
            rating=0,
            notes="obviously irrelevant",
        )
        await db.commit()
        assert overridden.rating == 0
        assert overridden.source == "human"
        assert overridden.rater_ref == "operator"
        assert overridden.notes == "obviously irrelevant"
        # Verify count stays at 1 — UPSERT replaced, not appended.
        total = await repo.count_judgments_for_list(db, ids["judgment_list_id"])
        assert total == 1
        # The originally-inserted row's id is now associated with the human override
        # OR the upsert minted a new id (DO UPDATE keeps the existing id, DO INSERT
        # uses the supplied id). Either way: source breakdown reflects 0 LLM rows.
        breakdown = await repo.source_breakdown_for_list(db, ids["judgment_list_id"])
        assert breakdown == {"llm": 0, "human": 1, "click": 0}
        # original is no longer reachable as 'llm' source.
        refetched = await repo.get_judgment(db, original.id)
        assert refetched is not None
        assert refetched.source == "human"


async def test_upsert_judgment_human_override_creates_new_row() -> None:
    """First-time override on a (query, doc) with no existing row → INSERT path."""
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.upsert_judgment_human_override(
            db,
            judgment_list_id=ids["judgment_list_id"],
            query_id=ids["query_id_1"],
            doc_id="d-fresh",
            rating=3,
            notes="from scratch",
        )
        await db.commit()
        assert row.source == "human"
        assert row.rating == 3


async def test_list_judgments_paginated_with_source_filter() -> None:
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        # Seed 3 LLM + 2 human rows.
        rows = [
            {
                "id": str(uuid.uuid4()),
                "judgment_list_id": ids["judgment_list_id"],
                "query_id": ids["query_id_1"],
                "doc_id": f"d{i}",
                "rating": 2,
                "source": "llm",
                "rater_ref": "openai:gpt-4o-2024-08-06",
                "notes": None,
            }
            for i in range(3)
        ]
        await repo.bulk_create_judgments(db, rows)
        for i in range(2):
            await repo.upsert_judgment_human_override(
                db,
                judgment_list_id=ids["judgment_list_id"],
                query_id=ids["query_id_1"],
                doc_id=f"h{i}",
                rating=1,
                notes=None,
            )
        await db.commit()

        llm_rows = await repo.list_judgments_paginated(
            db, ids["judgment_list_id"], source="llm", limit=50
        )
        human_rows = await repo.list_judgments_paginated(
            db, ids["judgment_list_id"], source="human", limit=50
        )
        all_rows = await repo.list_judgments_paginated(db, ids["judgment_list_id"], limit=50)
        assert len(llm_rows) == 3
        assert len(human_rows) == 2
        assert len(all_rows) == 5
        assert all(r.source == "llm" for r in llm_rows)
        assert all(r.source == "human" for r in human_rows)


async def test_count_judgments_for_list_and_query() -> None:
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        rows = [
            {
                "id": str(uuid.uuid4()),
                "judgment_list_id": ids["judgment_list_id"],
                "query_id": ids["query_id_1"],
                "doc_id": f"d{i}",
                "rating": 2,
                "source": "llm",
                "rater_ref": "openai:gpt-4o-2024-08-06",
                "notes": None,
            }
            for i in range(4)
        ]
        await repo.bulk_create_judgments(db, rows)
        await db.commit()
        n = await repo.count_judgments_for_list_and_query(
            db, ids["judgment_list_id"], ids["query_id_1"]
        )
        assert n == 4
        # Other query → 0.
        n2 = await repo.count_judgments_for_list_and_query(
            db, ids["judgment_list_id"], ids["query_id_2"]
        )
        assert n2 == 0


async def test_list_judgment_lists_pagination_and_count() -> None:
    factory = get_session_factory()
    # Seed 3 chains; each creates one judgment_list.
    seeded_ids: list[str] = []
    for _ in range(3):
        ids = await _seed_chain()
        seeded_ids.append(ids["judgment_list_id"])

    async with factory() as db:
        listed = await repo.list_judgment_lists(db, limit=2)
        assert len(listed) == 2
        total = await repo.count_judgment_lists(db)
        assert total >= 3
        # Cursor pagination: next page.
        cursor = (listed[-1].created_at, listed[-1].id)
        next_page = await repo.list_judgment_lists(db, cursor=cursor, limit=2)
        assert len(next_page) >= 1
        # IDs returned across both pages should be unique.
        seen_ids = {r.id for r in listed} | {r.id for r in next_page}
        assert len(seen_ids) == len(listed) + len(next_page)


async def test_update_judgment_list_status_and_calibration() -> None:
    ids = await _seed_chain()
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.update_judgment_list_status(
            db, ids["judgment_list_id"], status="complete"
        )
        await db.commit()
        assert updated.status == "complete"
        assert updated.failed_reason is None

        # Now mark failed with reason.
        updated_2 = await repo.update_judgment_list_status(
            db,
            ids["judgment_list_id"],
            status="failed",
            failed_reason="OPENAI_BUDGET_EXCEEDED",
        )
        await db.commit()
        assert updated_2.status == "failed"
        assert updated_2.failed_reason == "OPENAI_BUDGET_EXCEEDED"

        # Calibration.
        cal = {"cohens_kappa": 0.72, "weighted_kappa": 0.78, "n_samples": 30}
        updated_3 = await repo.update_judgment_list_calibration(db, ids["judgment_list_id"], cal)
        await db.commit()
        assert updated_3.calibration == cal


async def test_list_generating_judgment_list_ids() -> None:
    """Resume sweep helper — surfaces every 'generating' row at worker boot."""
    factory = get_session_factory()
    # Seed two chains; flip one to 'complete' so only the other shows up.
    ids_a = await _seed_chain()
    ids_b = await _seed_chain()
    async with factory() as db:
        await repo.update_judgment_list_status(db, ids_b["judgment_list_id"], status="complete")
        await db.commit()
        generating = await repo.list_generating_judgment_list_ids(db)
        assert ids_a["judgment_list_id"] in generating
        assert ids_b["judgment_list_id"] not in generating
