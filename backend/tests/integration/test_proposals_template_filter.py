# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``?template_id=`` filter on ``/api/v1/proposals``
(feat_data_table_primitive FR-3 / Story 1.5).

Asserts the proposals list endpoint accepts ``?template_id=<uuid>`` and
returns only proposals whose ``template_id`` matches. Combines with the
existing ``?status=`` filter to confirm both constraints AND-stack as
expected.
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


async def _seed_two_proposals_with_distinct_templates() -> tuple[str, str, str, str]:
    """Seed two manual proposals — one per template. Returns
    (template_a_id, template_b_id, proposal_a_id, proposal_b_id)."""
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"tmpl-filter-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template_a = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"tmpl-a-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        template_b = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"tmpl-b-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        # Manual proposals (study_id is nullable).
        proposal_a = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=None,
            cluster_id=cluster.id,
            template_id=template_a.id,
            status="pending",
            config_diff={},
            metric_delta={},
        )
        proposal_b = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=None,
            cluster_id=cluster.id,
            template_id=template_b.id,
            status="pending",
            config_diff={},
            metric_delta={},
        )
        await db.commit()
        return template_a.id, template_b.id, proposal_a.id, proposal_b.id


async def test_template_id_filters_to_matching_proposals(
    async_client: httpx.AsyncClient,
) -> None:
    (
        template_a_id,
        template_b_id,
        proposal_a_id,
        proposal_b_id,
    ) = await _seed_two_proposals_with_distinct_templates()
    resp = await async_client.get(f"/api/v1/proposals?template_id={template_a_id}")
    assert resp.status_code == 200, resp.text
    ids = {row["id"] for row in resp.json()["data"]}
    assert proposal_a_id in ids
    assert proposal_b_id not in ids


async def test_template_id_x_total_count_reflects_filtered_count(
    async_client: httpx.AsyncClient,
) -> None:
    template_a_id, _, proposal_a_id, _ = await _seed_two_proposals_with_distinct_templates()
    resp = await async_client.get(f"/api/v1/proposals?template_id={template_a_id}")
    assert resp.status_code == 200, resp.text
    total = int(resp.headers["X-Total-Count"])
    assert total >= 1
    assert proposal_a_id in {row["id"] for row in resp.json()["data"]}


async def test_template_id_stacks_with_status_filter(
    async_client: httpx.AsyncClient,
) -> None:
    """``?template_id=A&status=pending`` returns proposal_a;
    ``?template_id=A&status=pr_merged`` returns nothing for the same
    cluster (no proposals have that status combo)."""
    template_a_id, _, proposal_a_id, _ = await _seed_two_proposals_with_distinct_templates()
    pending = await async_client.get(
        f"/api/v1/proposals?template_id={template_a_id}&status=pending"
    )
    assert pending.status_code == 200, pending.text
    assert proposal_a_id in {row["id"] for row in pending.json()["data"]}

    merged = await async_client.get(
        f"/api/v1/proposals?template_id={template_a_id}&status=pr_merged"
    )
    assert merged.status_code == 200, merged.text
    assert proposal_a_id not in {row["id"] for row in merged.json()["data"]}


async def test_template_id_invalid_uuid_returns_validation_error(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/api/v1/proposals?template_id=not-a-uuid")
    assert resp.status_code == 422, resp.text
