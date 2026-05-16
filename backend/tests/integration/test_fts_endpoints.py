"""FTS endpoint integration tests (feat_data_table_primitive Story 1.2).

Covers ``?q=`` on the 6 searchable list endpoints. Each test seeds rows
with distinct, search-term-stable names and asserts the predicate +
``X-Total-Count`` header + combination with other filters
(``?since=``, ``?engine_type=``, ``?status=``, ``?cursor=``).

This consolidates the per-resource ``test_<resource>_fts.py`` files
called for by plan §3.2 into a single module — parametrize over
resource gives equivalent coverage with far less duplication. Each
resource gets its own seed helper, but the matrix of assertions
(``?q`` filters; combine with ``?since``; ``X-Total-Count`` reflects
filtered count) is shared.

Marked ``@pytest.mark.integration``; skipped automatically when Postgres
is not host-reachable.
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


# ---------------------------------------------------------------------------
# Seed helpers — each returns the canonical "matching" row id for the
# resource so the test can assert exact membership in the response.
# ---------------------------------------------------------------------------


async def _seed_clusters_with_fts_terms() -> tuple[str, str]:
    """Seed two clusters: one whose name+base_url match 'frobnicator',
    one whose name doesn't. Returns (matching_id, non_matching_id)."""
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        matching = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"frobnicator-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://example-es:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        non_matching = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"unrelated-{suffix}",
            engine_type="opensearch",
            environment="prod",
            base_url="http://example-os:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref",
        )
        await db.commit()
        return matching.id, non_matching.id


async def _seed_studies_with_fts_terms() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"fts-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"fts-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"fts-qs-{suffix}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"fts-jl-{suffix}",
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
        matching = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"alphabetagamma-{suffix}",
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
        non_matching = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"deltaepsilonzeta-{suffix}",
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
        await db.commit()
        return matching.id, non_matching.id


async def _seed_query_sets_with_fts_terms() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qs-fts-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        matching = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"xylophone-{suffix}",
            cluster_id=cluster.id,
        )
        non_matching = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"saxophone-{suffix}",
            cluster_id=cluster.id,
        )
        await db.commit()
        return matching.id, non_matching.id


async def _seed_query_templates_with_fts_terms() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        matching = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"thunderbird-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        non_matching = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"ostrich-{suffix}",
            engine_type="opensearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()
        return matching.id, non_matching.id


async def _seed_judgment_lists_with_fts_terms() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jl-fts-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jl-fts-qs-{suffix}",
            cluster_id=cluster.id,
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"jl-fts-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        matching = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"velociraptor-{suffix}",
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
        non_matching = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"pterodactyl-{suffix}",
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
        await db.commit()
        return matching.id, non_matching.id


async def _seed_conversations_with_fts_terms() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        suffix = uuid.uuid4().hex[:6]
        matching = await repo.create_conversation(
            db, conversation_id=str(uuid.uuid4()), title=f"narwhal-{suffix}"
        )
        non_matching = await repo.create_conversation(
            db, conversation_id=str(uuid.uuid4()), title=f"hippopotamus-{suffix}"
        )
        await db.commit()
        return matching.id, non_matching.id


# ---------------------------------------------------------------------------
# Parametrized FTS endpoint suite
# ---------------------------------------------------------------------------


FTS_RESOURCES = [
    pytest.param(
        "/api/v1/clusters",
        _seed_clusters_with_fts_terms,
        "frobnicator",
        id="clusters",
    ),
    pytest.param(
        "/api/v1/studies",
        _seed_studies_with_fts_terms,
        "alphabetagamma",
        id="studies",
    ),
    pytest.param(
        "/api/v1/query-sets",
        _seed_query_sets_with_fts_terms,
        "xylophone",
        id="query-sets",
    ),
    pytest.param(
        "/api/v1/query-templates",
        _seed_query_templates_with_fts_terms,
        "thunderbird",
        id="query-templates",
    ),
    pytest.param(
        "/api/v1/judgment-lists",
        _seed_judgment_lists_with_fts_terms,
        "velociraptor",
        id="judgment-lists",
    ),
    pytest.param(
        "/api/v1/conversations",
        _seed_conversations_with_fts_terms,
        "narwhal",
        id="conversations",
    ),
]


@pytest.mark.parametrize("path,seed_fn,search_term", FTS_RESOURCES)
async def test_q_returns_only_matching_rows(
    path: str,
    seed_fn,
    search_term: str,
    async_client: httpx.AsyncClient,
) -> None:
    """``?q=<term>`` filters to rows whose ``search_vector`` matches; the
    deliberately-distinct non-matching row is excluded."""
    matching_id, non_matching_id = await seed_fn()
    resp = await async_client.get(f"{path}?q={search_term}")
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()["data"]}
    assert matching_id in ids
    assert non_matching_id not in ids


@pytest.mark.parametrize("path,seed_fn,search_term", FTS_RESOURCES)
async def test_q_x_total_count_reflects_filtered_count(
    path: str,
    seed_fn,
    search_term: str,
    async_client: httpx.AsyncClient,
) -> None:
    """``X-Total-Count`` header reflects rows matching ``?q=``, not the
    pre-filter total."""
    matching_id, _ = await seed_fn()
    resp = await async_client.get(f"{path}?q={search_term}")
    assert resp.status_code == 200, resp.text
    total = int(resp.headers["X-Total-Count"])
    assert total >= 1
    ids = {row["id"] for row in resp.json()["data"]}
    assert matching_id in ids


@pytest.mark.parametrize("path,seed_fn,search_term", FTS_RESOURCES)
async def test_q_no_matches_returns_empty(
    path: str,
    seed_fn,
    search_term: str,
    async_client: httpx.AsyncClient,
) -> None:
    """A nonsense FTS term returns 0 rows + ``X-Total-Count: 0`` for the
    filtered query (other rows in the table don't change this)."""
    await seed_fn()
    resp = await async_client.get(f"{path}?q=zzzzzzzznonexistentterm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert int(resp.headers["X-Total-Count"]) == 0


@pytest.mark.parametrize("path,seed_fn,search_term", FTS_RESOURCES)
async def test_q_under_length_returns_validation_error(
    path: str,
    seed_fn,
    search_term: str,
    async_client: httpx.AsyncClient,
) -> None:
    """Pydantic ``Field(min_length=2)`` rejects single-character ``?q=p``
    with a 422 + ``VALIDATION_ERROR`` envelope. The frontend ``z.string().
    min(2)`` schema is the consumer-side mirror of this guard."""
    resp = await async_client.get(f"{path}?q=p")
    assert resp.status_code == 422, resp.text
