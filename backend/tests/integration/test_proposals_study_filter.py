"""``?study_id=`` filter on ``/api/v1/proposals``.

Regression coverage for the bug where the proposals list endpoint silently
ignored the ``?study_id=`` query parameter: ``useProposalForStudy`` in the
frontend was issuing ``GET /api/v1/proposals?study_id=X&status=pending``
expecting study-scoped results, but the endpoint had no ``study_id``
parameter declared and returned the most-recent global pending proposal
across all studies. This surfaced as the digest panel rendering the
"Open PR (enabled)" branch when there was no proposal for the current
study — and as the smoke-lane failure that originally caused
``infra_e2e_seed_completed_study`` PR #130 to drop its two E2E tests.

Mirrors the structure of ``test_proposals_template_filter.py``.
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


async def _seed_two_proposals_under_distinct_studies() -> tuple[str, str, str, str]:
    """Seed two pending proposals — one per study — sharing the same cluster
    and template. Returns (study_a_id, study_b_id, proposal_a_id, proposal_b_id)."""
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"study-filter-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"study-filter-tpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            name=f"study-filter-qs-{suffix}",
            description=None,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            name=f"study-filter-jl-{suffix}",
            generated_by="local:test",
        )
        study_a = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"study-a-{suffix}",
            cluster_id=cluster.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            template_id=template.id,
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            search_space={},
            optimizer_config={"max_trials": 1},
        )
        study_b = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name=f"study-b-{suffix}",
            cluster_id=cluster.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            template_id=template.id,
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            search_space={},
            optimizer_config={"max_trials": 1},
        )
        proposal_a = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=study_a.id,
            cluster_id=cluster.id,
            template_id=template.id,
            status="pending",
            config_diff={},
            metric_delta={},
        )
        proposal_b = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=study_b.id,
            cluster_id=cluster.id,
            template_id=template.id,
            status="pending",
            config_diff={},
            metric_delta={},
        )
        await db.commit()
        return study_a.id, study_b.id, proposal_a.id, proposal_b.id


async def test_study_id_filters_to_matching_proposals(
    async_client: httpx.AsyncClient,
) -> None:
    (
        study_a_id,
        study_b_id,
        proposal_a_id,
        proposal_b_id,
    ) = await _seed_two_proposals_under_distinct_studies()
    resp = await async_client.get(f"/api/v1/proposals?study_id={study_a_id}")
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()["data"]}
    assert proposal_a_id in ids
    assert proposal_b_id not in ids


async def test_study_id_x_total_count_reflects_filtered_count(
    async_client: httpx.AsyncClient,
) -> None:
    study_a_id, _, proposal_a_id, _ = await _seed_two_proposals_under_distinct_studies()
    resp = await async_client.get(f"/api/v1/proposals?study_id={study_a_id}")
    assert resp.status_code == 200, resp.text
    total = int(resp.headers["X-Total-Count"])
    # Exactly one proposal exists for this study; assert the total reflects the
    # filter rather than the global pending count.
    assert total == 1
    assert proposal_a_id in {row["id"] for row in resp.json()["data"]}


async def test_study_id_stacks_with_status_filter(
    async_client: httpx.AsyncClient,
) -> None:
    """``?study_id=A&status=pending`` returns proposal_a;
    ``?study_id=A&status=pr_merged`` returns nothing."""
    study_a_id, _, proposal_a_id, _ = await _seed_two_proposals_under_distinct_studies()
    pending = await async_client.get(f"/api/v1/proposals?study_id={study_a_id}&status=pending")
    assert pending.status_code == 200, pending.text
    assert proposal_a_id in {row["id"] for row in pending.json()["data"]}

    merged = await async_client.get(f"/api/v1/proposals?study_id={study_a_id}&status=pr_merged")
    assert merged.status_code == 200, merged.text
    assert proposal_a_id not in {row["id"] for row in merged.json()["data"]}


async def test_study_id_invalid_uuid_returns_validation_error(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/api/v1/proposals?study_id=not-a-uuid")
    assert resp.status_code == 422, resp.text


async def test_study_id_nonexistent_returns_empty(
    async_client: httpx.AsyncClient,
) -> None:
    """Regression: pre-fix, a nonexistent study_id returned the most-recent
    global pending proposal (filter was silently ignored)."""
    nonexistent = str(uuid.uuid4())
    resp = await async_client.get(f"/api/v1/proposals?study_id={nonexistent}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert int(resp.headers["X-Total-Count"]) == 0
