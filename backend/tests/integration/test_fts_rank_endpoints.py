# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""FTS relevance-rank ordering integration tests (feat_fts_rank_ordering).

When ``?q=`` is present and no explicit ``?sort=`` is supplied, the 6
searchable list endpoints order by ``ts_rank`` descending (relevance). Each
seed helper creates two matching rows of *different prominence* — the term
appears 3× in the high-relevance row's name/title and 1× in the low-relevance
row — so ``ts_rank(high) > ts_rank(low)`` deterministically (more term
occurrences ⇒ higher rank regardless of the default no-length-normalization).

Marked ``@pytest.mark.integration``; skipped when Postgres is not reachable.
"""

from __future__ import annotations

import uuid

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


def _term() -> str:
    # Unique alnum token per seed call → test isolation (no cross-test matches).
    return "rk" + uuid.uuid4().hex[:8]


async def _seed_clusters_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        high = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"{term} {term} {term} hi",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        low = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"{term} lo",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        await db.commit()
        return high.id, low.id, term


async def _seed_query_sets_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qsrank-{uuid.uuid4().hex[:6]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        high = await repo.create_query_set(
            db, id=str(uuid.uuid4()), name=f"{term} {term} {term} hi", cluster_id=cluster.id
        )
        low = await repo.create_query_set(
            db, id=str(uuid.uuid4()), name=f"{term} lo", cluster_id=cluster.id
        )
        await db.commit()
        return high.id, low.id, term


async def _seed_query_templates_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        high = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"{term} {term} {term} hi",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        low = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"{term} lo",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()
        return high.id, low.id, term


async def _seed_judgment_lists_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jlrank-{uuid.uuid4().hex[:6]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jlrank-qs-{uuid.uuid4().hex[:6]}",
            cluster_id=cluster.id,
        )

        async def _mk(name: str) -> str:
            jl = await repo.create_judgment_list(
                db,
                id=str(uuid.uuid4()),
                name=name,
                description=None,
                query_set_id=qs.id,
                cluster_id=cluster.id,
                target="stub-index",
                current_template_id=None,
                rubric="hand-built",
                status="complete",
                failed_reason=None,
                calibration=None,
            )
            return jl.id

        high_id = await _mk(f"{term} {term} {term} hi")
        low_id = await _mk(f"{term} lo")
        await db.commit()
        return high_id, low_id, term


async def _seed_studies_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"strank-{uuid.uuid4().hex[:6]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"strank-tmpl-{uuid.uuid4().hex[:6]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"strank-qs-{uuid.uuid4().hex[:6]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"strank-jl-{uuid.uuid4().hex[:6]}",
            description=None,
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )

        async def _mk(name: str) -> str:
            study = await repo.create_study(
                db,
                id=str(uuid.uuid4()),
                name=name,
                cluster_id=cluster.id,
                target="stub-index",
                template_id=template.id,
                query_set_id=qs.id,
                judgment_list_id=jl.id,
                search_space={"params": {}},
                objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
                config={"max_trials": 5},
                status="queued",
                optuna_study_name=str(uuid.uuid4()),
            )
            return study.id

        high_id = await _mk(f"{term} {term} {term} hi")
        low_id = await _mk(f"{term} lo")
        await db.commit()
        return high_id, low_id, term


async def _seed_conversations_rank() -> tuple[str, str, str]:
    term = _term()
    factory = get_session_factory()
    async with factory() as db:
        high = await repo.create_conversation(
            db, conversation_id=str(uuid.uuid4()), title=f"{term} {term} {term} hi"
        )
        low = await repo.create_conversation(
            db, conversation_id=str(uuid.uuid4()), title=f"{term} lo"
        )
        await db.commit()
        return high.id, low.id, term


RANK_RESOURCES = [
    pytest.param("/api/v1/clusters", _seed_clusters_rank, id="clusters"),
    pytest.param("/api/v1/studies", _seed_studies_rank, id="studies"),
    pytest.param("/api/v1/query-sets", _seed_query_sets_rank, id="query-sets"),
    pytest.param("/api/v1/query-templates", _seed_query_templates_rank, id="query-templates"),
    pytest.param("/api/v1/judgment-lists", _seed_judgment_lists_rank, id="judgment-lists"),
    pytest.param("/api/v1/conversations", _seed_conversations_rank, id="conversations"),
]


@pytest.mark.parametrize("path,seed_fn", RANK_RESOURCES)
async def test_relevance_orders_more_relevant_first(
    path: str, seed_fn, async_client: httpx.AsyncClient
) -> None:
    """AC-1/AC-9: with ``?q=`` and no ``?sort=``, the higher-ts_rank row sorts
    before the lower-ts_rank row across every searchable resource."""
    high_id, low_id, term = await seed_fn()
    resp = await async_client.get(f"{path}?q={term}")
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()["data"]]
    assert high_id in ids and low_id in ids, ids
    assert ids.index(high_id) < ids.index(low_id), ids


async def test_pagination_no_skip_no_dupe(async_client: httpx.AsyncClient) -> None:
    """AC-2: walking the rank-ordered result one row at a time via the cursor
    yields every matching row exactly once (no skip, no duplicate)."""
    high_id, low_id, term = await _seed_clusters_rank()
    # Page size 1 forces a cursor round-trip between the two matching rows.
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):  # safety bound; expect 2 rows
        url = f"/api/v1/clusters?q={term}&limit=1" + (f"&cursor={cursor}" if cursor else "")
        resp = await async_client.get(url)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend(row["id"] for row in body["data"])
        cursor = body.get("next_cursor")
        if not body.get("has_more"):
            break
    assert seen == [high_id, low_id], seen
    assert len(seen) == len(set(seen))


async def test_explicit_sort_overrides_rank(async_client: httpx.AsyncClient) -> None:
    """AC-3: ``?q=`` + explicit ``?sort=name:asc`` orders by name, not rank.

    The low-relevance name (``"{term} lo"``) sorts before the high-relevance
    name (``"{term} {term} {term} hi"``) under ``name:asc`` (the repeated-term
    prefix is lexically greater is irrelevant — 'l' in 'lo' vs the term prefix;
    we assert the order matches a plain name sort, the opposite of rank)."""
    high_id, low_id, term = await _seed_clusters_rank()
    resp = await async_client.get(f"/api/v1/clusters?q={term}&sort=name:asc")
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()["data"] if row["id"] in {high_id, low_id}]
    # name:asc → the two names sort lexically; high name starts with "{term} {term}…",
    # low name with "{term} lo". Both share the "{term} " prefix; next char is the
    # term's first char (high) vs 'l' (low) — so high < low iff term[0] < 'l'.
    expected = sorted(
        [(f"{term} {term} {term} hi", high_id), (f"{term} lo", low_id)], key=lambda t: t[0]
    )
    assert ids == [rid for _, rid in expected], ids


async def test_tampered_rank_cursor_returns_422(async_client: httpx.AsyncClient) -> None:
    """AC-5: a malformed cursor on the rank path surfaces 422 VALIDATION_ERROR,
    not 500 (the rank path decodes with value_is_datetime=False but the same
    shape/type guards apply)."""
    resp = await async_client.get("/api/v1/clusters?q=anything&cursor=not-a-valid-cursor")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_no_q_does_not_rank(async_client: httpx.AsyncClient) -> None:
    """AC-4: without ``?q=``, ordering is the legacy created_at DESC — the
    later-created 'low' row (inserted second) precedes the 'high' row."""
    high_id, low_id, _term = await _seed_clusters_rank()
    resp = await async_client.get("/api/v1/clusters?limit=200")
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()["data"] if row["id"] in {high_id, low_id}]
    # low was created after high → newest-first puts low before high.
    assert ids == [low_id, high_id], ids
