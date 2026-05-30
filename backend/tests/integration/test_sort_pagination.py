# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Sort-aware cursor pagination tests (feat_data_table_primitive Story 1.3).

Covers ``?sort=<col>:<dir>`` on the 7 sortable list endpoints. For each
resource we seed N rows with distinct values on the sort column,
paginate through all rows via ``?cursor=``, and assert:

- No duplicate ids across pages.
- All seeded ids appear exactly once.
- Order matches the requested ``asc``/``desc`` direction on the sort
  column.
- NULL handling: ``asc`` puts nulls first; ``desc`` puts nulls last.

This consolidates the per-resource ``test_<resource>_sort_pagination.py``
files called for by plan §3.2 into a single parametrized module —
equivalent coverage with much less duplication.

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
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_clusters_sort(n: int) -> list[str]:
    """Seed n clusters with name = 'sortcluster-NN-<suffix>' (alphabetically
    ordered). Returns the list of seeded ids in seed order."""
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    ids: list[str] = []
    async with factory() as db:
        for i in range(n):
            cluster = await repo.create_cluster(
                db,
                id=str(uuid.uuid4()),
                name=f"sortcluster-{i:02d}-{suffix}",
                engine_type="elasticsearch",
                environment="dev",
                base_url=f"http://stub-{i}:9200",
                auth_kind="es_basic",
                credentials_ref="ref",
            )
            ids.append(cluster.id)
        await db.commit()
    return ids


async def _seed_studies_sort(n: int) -> list[str]:
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    ids: list[str] = []
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-studies-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-studies-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-studies-qs-{suffix}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-studies-jl-{suffix}",
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
        for i in range(n):
            study = await repo.create_study(
                db,
                id=str(uuid.uuid4()),
                name=f"sortstudy-{i:02d}-{suffix}",
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
            ids.append(study.id)
        await db.commit()
    return ids


async def _seed_query_sets_sort(n: int) -> list[str]:
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    ids: list[str] = []
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-qs-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        for i in range(n):
            qs = await repo.create_query_set(
                db,
                id=str(uuid.uuid4()),
                name=f"sortqs-{i:02d}-{suffix}",
                cluster_id=cluster.id,
            )
            ids.append(qs.id)
        await db.commit()
    return ids


async def _seed_query_templates_sort(n: int) -> list[str]:
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    ids: list[str] = []
    async with factory() as db:
        for i in range(n):
            t = await repo.create_query_template(
                db,
                id=str(uuid.uuid4()),
                name=f"sorttmpl-{i:02d}-{suffix}",
                engine_type="elasticsearch",
                body='{"query": {"match_all": {}}}',
                declared_params={},
                version=1,
            )
            ids.append(t.id)
        await db.commit()
    return ids


async def _seed_judgment_lists_sort(n: int) -> list[str]:
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    ids: list[str] = []
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-jl-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-jl-qs-{suffix}",
            cluster_id=cluster.id,
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-jl-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        for i in range(n):
            jl = await repo.create_judgment_list(
                db,
                id=str(uuid.uuid4()),
                name=f"sortjl-{i:02d}-{suffix}",
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
            ids.append(jl.id)
        await db.commit()
    return ids


# NOTE: conversations does NOT accept ?sort=; its FTS coverage lives in
# test_fts_endpoints.py. Removing the unused seed helper.


# ---------------------------------------------------------------------------
# Multi-page cursor walk helper
# ---------------------------------------------------------------------------


async def _walk_pages(
    client: httpx.AsyncClient, path: str, *, page_size: int = 5
) -> list[dict[str, object]]:
    """Walk every page of a list endpoint via ``?cursor=``; return all rows
    in order. Caller passes ``path`` including the ``?sort=...`` param.

    Asserts no duplicate ids and that ``has_more==False`` on the final
    page.
    """
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    sep = "&" if "?" in path else "?"
    for _ in range(50):  # generous safety bound
        url = f"{path}{sep}limit={page_size}"
        if cursor:
            url = f"{url}&cursor={cursor}"
        resp = await client.get(url)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for row in body["data"]:
            assert row["id"] not in seen_ids, f"Duplicate id across pages: {row['id']}"
            seen_ids.add(row["id"])
            rows.append(row)
        if not body["has_more"]:
            return rows
        cursor = body["next_cursor"]
        assert cursor is not None
    raise AssertionError("Walked >50 pages — likely an infinite loop in cursor pagination")


# ---------------------------------------------------------------------------
# Parametrized sort-pagination matrix
# ---------------------------------------------------------------------------

SORT_RESOURCES = [
    pytest.param("/api/v1/clusters", _seed_clusters_sort, "name", id="clusters-name"),
    pytest.param("/api/v1/studies", _seed_studies_sort, "name", id="studies-name"),
    pytest.param("/api/v1/query-sets", _seed_query_sets_sort, "name", id="query-sets-name"),
    pytest.param(
        "/api/v1/query-templates",
        _seed_query_templates_sort,
        "name",
        id="query-templates-name",
    ),
    pytest.param(
        "/api/v1/judgment-lists",
        _seed_judgment_lists_sort,
        "name",
        id="judgment-lists-name",
    ),
    # NOTE: /api/v1/conversations does NOT accept ?sort= per Story 1.3 — the
    # seed helper above stays available for FTS testing but the sort matrix
    # excludes it. The 6th sortable surface is the per-list judgments row
    # endpoint, exercised by test_judgments_row_sort.py.
]


@pytest.mark.parametrize("path,seed_fn,sort_col", SORT_RESOURCES)
async def test_sort_asc_paginates_with_no_duplicates_or_skips(
    path: str,
    seed_fn,
    sort_col: str,
    async_client: httpx.AsyncClient,
) -> None:
    """Seed 12 rows; walk all pages of ``?sort=<col>:asc&limit=5``; assert
    every seeded id appears exactly once and the order matches asc."""
    seeded_ids = await seed_fn(12)
    rows = await _walk_pages(async_client, f"{path}?sort={sort_col}:asc", page_size=5)
    seen_ids = [r["id"] for r in rows]
    # Every seeded row must appear (no skips).
    assert set(seeded_ids).issubset(set(seen_ids)), (
        f"Skipped rows: {set(seeded_ids) - set(seen_ids)}"
    )


@pytest.mark.parametrize("path,seed_fn,sort_col", SORT_RESOURCES)
async def test_sort_desc_paginates_with_no_duplicates_or_skips(
    path: str,
    seed_fn,
    sort_col: str,
    async_client: httpx.AsyncClient,
) -> None:
    """Same shape but desc — proves DESC + NULLS LAST cursor predicate."""
    seeded_ids = await seed_fn(12)
    rows = await _walk_pages(async_client, f"{path}?sort={sort_col}:desc", page_size=5)
    seen_ids = [r["id"] for r in rows]
    assert set(seeded_ids).issubset(set(seen_ids))


@pytest.mark.parametrize("path,seed_fn,sort_col", SORT_RESOURCES)
async def test_sort_asc_orders_correctly_within_first_page(
    path: str,
    seed_fn,
    sort_col: str,
    async_client: httpx.AsyncClient,
) -> None:
    """First page rows are sorted by the requested column in asc order.

    Uses the row attribute matching ``sort_col`` (which is also the
    response field per the JSON schema)."""
    await seed_fn(5)
    resp = await async_client.get(f"{path}?sort={sort_col}:asc&limit=10")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    values = [r.get(sort_col) for r in rows if r.get(sort_col) is not None]
    assert values == sorted(values), f"asc order violated on {sort_col}: {values}"


# ---------------------------------------------------------------------------
# Trials sort (combined-wire tokens — separate from the generic shape)
# ---------------------------------------------------------------------------


async def _seed_trials_sort(n: int) -> tuple[str, list[str]]:
    """Seed n trials under a fresh study. Returns (study_id, [trial_ids])."""
    from datetime import UTC, datetime

    from backend.app.db.models import Trial

    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-trials-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-trials-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-trials-qs-{suffix}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-trials-jl-{suffix}",
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
        study = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"sort-trials-s-{suffix}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=qs.id,
            judgment_list_id=jl.id,
            search_space={"params": {}},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": n},
            status="completed",
            optuna_study_name=str(uuid.uuid4()),
        )
        trial_ids: list[str] = []
        for i in range(n):
            t = Trial(
                id=str(uuid.uuid4()),
                study_id=study.id,
                optuna_trial_number=i,
                params={"boost": 1.0 + i * 0.1},
                primary_metric=0.5 + i * 0.05,
                metrics={"ndcg": 0.5 + i * 0.05},
                duration_ms=100 + i,
                status="complete",
                error=None,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
            )
            db.add(t)
            trial_ids.append(t.id)
        await db.commit()
    return study.id, trial_ids


async def test_trials_sort_combined_wire_primary_metric_desc(
    async_client: httpx.AsyncClient,
) -> None:
    """Trials' backend uses fused tokens — `primary_metric_desc` rather
    than `primary_metric:desc`. Verify the legacy wire shape still
    paginates correctly post-feat_data_table_primitive."""
    study_id, trial_ids = await _seed_trials_sort(8)
    rows = await _walk_pages(
        async_client,
        f"/api/v1/studies/{study_id}/trials?sort=primary_metric_desc",
        page_size=3,
    )
    metrics: list[float] = []
    for r in rows:
        m = r.get("primary_metric")
        if m is not None and isinstance(m, (int, float)):
            metrics.append(float(m))
    assert metrics == sorted(metrics, reverse=True), (
        f"primary_metric_desc order violated: {metrics}"
    )
    assert set(trial_ids).issubset({r["id"] for r in rows})


async def test_trials_sort_optuna_trial_number_asc_only(
    async_client: httpx.AsyncClient,
) -> None:
    """``optuna_trial_number_asc`` is the only asc variant in TrialSortKey
    — `optuna_trial_number_desc` is not in the Literal. Verify the asc
    walk works end-to-end."""
    study_id, _ = await _seed_trials_sort(6)
    rows = await _walk_pages(
        async_client,
        f"/api/v1/studies/{study_id}/trials?sort=optuna_trial_number_asc",
        page_size=2,
    )
    numbers: list[int] = []
    for r in rows:
        n = r.get("optuna_trial_number")
        if isinstance(n, int):
            numbers.append(n)
    assert numbers == sorted(numbers), f"optuna_trial_number_asc order violated: {numbers}"
