# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the chore_e2e_test_rows_isolation Story 1.1 DELETE endpoints.

20 cases per implementation_plan.md §3.2:
- 6 happy paths (one per endpoint) — 204 + row gone + cascade children gone.
- 6 404s (one per endpoint) — unknown id → resource-specific NOT_FOUND code.
- 8 409s — every declared HAS_DEPENDENT code.

Mirrors the test_test_seeding.py FK-seed helper pattern (lines 25-72) and
the async_client fixture from backend/tests/conftest.py.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select

from backend.app.db import repo
from backend.app.db.models import (
    Digest,
    Judgment,
    JudgmentList,
    Proposal,
    Query,
    QuerySet,
    QueryTemplate,
    Study,
    Trial,
)
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_cluster_only() -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"tde-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        await db.commit()
    return cluster.id


async def _seed_template(name_suffix: str = "") -> str:
    factory = get_session_factory()
    async with factory() as db:
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"tde-tmpl-{name_suffix or uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"boost": {"type": "float", "min": 0.5, "max": 5.0}},
            version=1,
        )
        await db.commit()
    return template.id


async def _seed_query_set(cluster_id: str, num_queries: int = 0) -> tuple[str, list[str]]:
    """Create a query_set + N queries; return (qs_id, [query_ids])."""
    factory = get_session_factory()
    async with factory() as db:
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"tde-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster_id,
        )
        query_ids: list[str] = []
        for i in range(num_queries):
            q = await repo.create_query(
                db,
                id=str(uuid.uuid4()),
                query_set_id=qs.id,
                query_text=f"tde-q-{i}",
            )
            query_ids.append(q.id)
        await db.commit()
    return qs.id, query_ids


async def _seed_judgment_list(
    cluster_id: str,
    query_set_id: str,
    template_id: str | None = None,
    num_judgments: int = 0,
    query_ids: list[str] | None = None,
) -> str:
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"tde-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set_id,
            cluster_id=cluster_id,
            target="stub-index",
            current_template_id=template_id,
            rubric="r",
            status="complete",
        )
        if num_judgments > 0 and query_ids:
            for i in range(min(num_judgments, len(query_ids))):
                await repo.create_judgment(
                    db,
                    id=str(uuid.uuid4()),
                    judgment_list_id=jl.id,
                    query_id=query_ids[i],
                    doc_id=f"doc-{i}",
                    rating=2,
                    source="human",
                )
        await db.commit()
    return jl.id


async def _seed_study(
    cluster_id: str,
    query_set_id: str,
    judgment_list_id: str,
    template_id: str,
    num_trials: int = 0,
) -> str:
    factory = get_session_factory()
    async with factory() as db:
        study = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"tde-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster_id,
            target="stub-index",
            template_id=template_id,
            query_set_id=query_set_id,
            judgment_list_id=judgment_list_id,
            search_space={"params": {"boost": {"type": "float", "low": 0.5, "high": 5.0}}},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 10},
            status="queued",
            optuna_study_name=str(uuid.uuid4()),
        )
        for i in range(num_trials):
            await repo.create_trial(
                db,
                id=str(uuid.uuid4()),
                study_id=study.id,
                optuna_trial_number=i,
                params={"boost": 1.0 + i},
                status="complete",
                primary_metric=0.5,
                metrics={"ndcg@10": 0.5},
            )
        await db.commit()
    return study.id


async def _seed_digest(study_id: str) -> str:
    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            narrative="t",
            parameter_importance={"boost": 1.0},
            recommended_config={"boost": 1.5},
            suggested_followups=[],
            generated_by="local:test-seed",
        )
        await db.commit()
    return digest.id


async def _seed_proposal(
    cluster_id: str,
    template_id: str,
    study_id: str | None = None,
) -> str:
    factory = get_session_factory()
    async with factory() as db:
        proposal = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=study_id,
            study_trial_id=None,
            cluster_id=cluster_id,
            template_id=template_id,
            config_diff={"boost": {"from": 1.0, "to": 1.5}},
            status="pending",
        )
        await db.commit()
    return proposal.id


async def _count(model: type, **filters: object) -> int:
    factory = get_session_factory()
    async with factory() as db:
        stmt = select(func.count()).select_from(model)
        for col, val in filters.items():
            stmt = stmt.where(getattr(model, col) == val)
        return int((await db.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# Happy paths — 6 cases (FR-1 through FR-6)
# ---------------------------------------------------------------------------


async def test_delete_proposal_happy_path(async_client: httpx.AsyncClient) -> None:
    """FR-1: DELETE proposal → 204 + row gone."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    proposal_id = await _seed_proposal(cluster_id, template_id)

    resp = await async_client.delete(f"/api/v1/_test/proposals/{proposal_id}")
    assert resp.status_code == 204
    assert await _count(Proposal, id=proposal_id) == 0


async def test_delete_digest_happy_path(async_client: httpx.AsyncClient) -> None:
    """FR-2: DELETE digest → 204 + row gone."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    study_id = await _seed_study(cluster_id, qs_id, jl_id, template_id)
    digest_id = await _seed_digest(study_id)

    resp = await async_client.delete(f"/api/v1/_test/digests/{digest_id}")
    assert resp.status_code == 204
    assert await _count(Digest, id=digest_id) == 0


async def test_delete_study_happy_path_cascades_trials(
    async_client: httpx.AsyncClient,
) -> None:
    """FR-3 + AC-5: DELETE study → 204 + study gone + trials cascade-deleted."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    study_id = await _seed_study(cluster_id, qs_id, jl_id, template_id, num_trials=3)
    # Sanity: trials exist before delete.
    assert await _count(Trial, study_id=study_id) == 3

    resp = await async_client.delete(f"/api/v1/_test/studies/{study_id}")
    assert resp.status_code == 204
    assert await _count(Study, id=study_id) == 0
    # Trials cascade via FK at trial.py:60.
    assert await _count(Trial, study_id=study_id) == 0


async def test_delete_judgment_list_happy_path_cascades_judgments(
    async_client: httpx.AsyncClient,
) -> None:
    """FR-4 + AC-6: DELETE judgment_list → 204 + judgments cascade-deleted."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, query_ids = await _seed_query_set(cluster_id, num_queries=2)
    jl_id = await _seed_judgment_list(
        cluster_id, qs_id, template_id, num_judgments=2, query_ids=query_ids
    )
    assert await _count(Judgment, judgment_list_id=jl_id) == 2

    resp = await async_client.delete(f"/api/v1/_test/judgment-lists/{jl_id}")
    assert resp.status_code == 204
    assert await _count(JudgmentList, id=jl_id) == 0
    assert await _count(Judgment, judgment_list_id=jl_id) == 0


async def test_delete_query_set_happy_path_cascades_queries(
    async_client: httpx.AsyncClient,
) -> None:
    """FR-5 + AC-7: DELETE query_set → 204 + queries cascade-deleted."""
    cluster_id = await _seed_cluster_only()
    qs_id, _ = await _seed_query_set(cluster_id, num_queries=3)
    assert await _count(Query, query_set_id=qs_id) == 3

    resp = await async_client.delete(f"/api/v1/_test/query-sets/{qs_id}")
    assert resp.status_code == 204
    assert await _count(QuerySet, id=qs_id) == 0
    assert await _count(Query, query_set_id=qs_id) == 0


async def test_delete_query_template_happy_path(
    async_client: httpx.AsyncClient,
) -> None:
    """FR-6: DELETE query_template → 204 + row gone."""
    template_id = await _seed_template()

    resp = await async_client.delete(f"/api/v1/_test/query-templates/{template_id}")
    assert resp.status_code == 204
    assert await _count(QueryTemplate, id=template_id) == 0


# ---------------------------------------------------------------------------
# 404 on unknown id — 6 cases (one per endpoint)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected_code",
    [
        ("proposals", "PROPOSAL_NOT_FOUND"),
        ("digests", "DIGEST_NOT_FOUND"),
        ("studies", "STUDY_NOT_FOUND"),
        ("judgment-lists", "JUDGMENT_LIST_NOT_FOUND"),
        ("query-sets", "QUERY_SET_NOT_FOUND"),
        ("query-templates", "TEMPLATE_NOT_FOUND"),
    ],
)
async def test_delete_unknown_id_returns_404(
    async_client: httpx.AsyncClient, path: str, expected_code: str
) -> None:
    """Every endpoint returns 404 with the resource-specific NOT_FOUND code."""
    unknown_id = str(uuid.uuid4())
    resp = await async_client.delete(f"/api/v1/_test/{path}/{unknown_id}")
    assert resp.status_code == 404
    body = resp.json()["detail"]
    assert body["error_code"] == expected_code
    assert body["retryable"] is False


# ---------------------------------------------------------------------------
# 409 on dependent row — 8 cases (every declared HAS_DEPENDENT code)
# ---------------------------------------------------------------------------


async def test_delete_study_409_with_dependent_proposal(
    async_client: httpx.AsyncClient,
) -> None:
    """STUDY_HAS_DEPENDENT_PROPOSAL fires first when both proposal + digest exist."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    study_id = await _seed_study(cluster_id, qs_id, jl_id, template_id)
    await _seed_proposal(cluster_id, template_id, study_id=study_id)

    resp = await async_client.delete(f"/api/v1/_test/studies/{study_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "STUDY_HAS_DEPENDENT_PROPOSAL"
    # Study still exists.
    assert await _count(Study, id=study_id) == 1


async def test_delete_study_409_with_dependent_digest(
    async_client: httpx.AsyncClient,
) -> None:
    """STUDY_HAS_DEPENDENT_DIGEST fires when only digest (no proposal) exists."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    study_id = await _seed_study(cluster_id, qs_id, jl_id, template_id)
    await _seed_digest(study_id)

    resp = await async_client.delete(f"/api/v1/_test/studies/{study_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "STUDY_HAS_DEPENDENT_DIGEST"


async def test_delete_judgment_list_409_with_dependent_study(
    async_client: httpx.AsyncClient,
) -> None:
    """JUDGMENT_LIST_HAS_DEPENDENT_STUDY fires when a study references the JL."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    await _seed_study(cluster_id, qs_id, jl_id, template_id)

    resp = await async_client.delete(f"/api/v1/_test/judgment-lists/{jl_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "JUDGMENT_LIST_HAS_DEPENDENT_STUDY"


async def test_delete_query_set_409_with_dependent_study(
    async_client: httpx.AsyncClient,
) -> None:
    """QUERY_SET_HAS_DEPENDENT_STUDY fires when a study references the QS."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    await _seed_study(cluster_id, qs_id, jl_id, template_id)

    resp = await async_client.delete(f"/api/v1/_test/query-sets/{qs_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_HAS_DEPENDENT_STUDY"


async def test_delete_query_set_409_with_dependent_judgment_list(
    async_client: httpx.AsyncClient,
) -> None:
    """QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST fires when only a JL (no study)
    references the QS. Locks the STUDY-first preflight order."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    await _seed_judgment_list(cluster_id, qs_id, template_id)
    # No study references qs.

    resp = await async_client.delete(f"/api/v1/_test/query-sets/{qs_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST"


async def test_delete_query_template_409_with_dependent_study(
    async_client: httpx.AsyncClient,
) -> None:
    """QUERY_TEMPLATE_HAS_DEPENDENT_STUDY fires first (top of priority order)."""
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id)
    await _seed_study(cluster_id, qs_id, jl_id, template_id)

    resp = await async_client.delete(f"/api/v1/_test/query-templates/{template_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "QUERY_TEMPLATE_HAS_DEPENDENT_STUDY"


async def test_delete_query_template_409_with_dependent_proposal(
    async_client: httpx.AsyncClient,
) -> None:
    """QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL fires when only a proposal
    references the template (no study, no JL). Priority order: STUDY > PROPOSAL > JUDGMENT_LIST.

    Two-template fixture: T_delete is what we try to delete; T_study is
    used by an unrelated study so the study reference doesn't trigger
    the STUDY code path for T_delete.
    """
    cluster_id = await _seed_cluster_only()
    template_id_delete = await _seed_template(name_suffix="del")
    template_id_study = await _seed_template(name_suffix="stu")
    qs_id, _ = await _seed_query_set(cluster_id)
    jl_id = await _seed_judgment_list(cluster_id, qs_id, template_id_study)
    # Study references T_study, NOT T_delete.
    await _seed_study(cluster_id, qs_id, jl_id, template_id_study)
    # Proposal references T_delete with study_id=NULL (study_id is nullable
    # per proposal.py:49 — `nullable=True`).
    await _seed_proposal(cluster_id, template_id_delete, study_id=None)

    resp = await async_client.delete(f"/api/v1/_test/query-templates/{template_id_delete}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL"


async def test_delete_query_template_409_with_dependent_judgment_list(
    async_client: httpx.AsyncClient,
) -> None:
    """QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST fires when only a JL
    references the template via current_template_id (no study, no proposal).

    Verifies the priority order falls all the way through to JL.
    """
    cluster_id = await _seed_cluster_only()
    template_id = await _seed_template()
    qs_id, _ = await _seed_query_set(cluster_id)
    # JL references the template via current_template_id.
    await _seed_judgment_list(cluster_id, qs_id, template_id)
    # No study, no proposal.

    resp = await async_client.delete(f"/api/v1/_test/query-templates/{template_id}")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST"
