# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration test for the three-term ``source_breakdown`` on
``GET /api/v1/judgment-lists/{id}`` (feat_ubi_judgments Story 2.3 / FR-10).

Seeds a judgment list with mixed ``source`` rows (llm + human + click)
and asserts the detail response surfaces ``{llm, human, click}`` with the
``llm + human + click == judgment_count`` invariant + exposes
``generation_params``.
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


async def _seed_list_with_mixed_sources() -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"bd-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="opensearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db, id=str(uuid.uuid4()), name=f"bd-qs-{uuid.uuid4().hex[:8]}", cluster_id=cluster.id
        )
        q = await repo.create_query(db, id=str(uuid.uuid4()), query_set_id=qs.id, query_text="q")
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"bd-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="products",
            current_template_id=None,
            rubric="UBI converter: ctr_threshold",
            status="complete",
            failed_reason=None,
            calibration={"coverage_pct": 0.8},
            generation_params={"generation_kind": "ubi", "converter": "ctr_threshold"},
        )
        rows = [
            {"source": "llm", "rater_ref": "openai:x"},
            {"source": "human", "rater_ref": "operator"},
            {"source": "click", "rater_ref": "ubi:ctr_threshold"},
            {"source": "click", "rater_ref": "ubi:ctr_threshold"},
        ]
        for i, r in enumerate(rows):
            await repo.create_judgment(
                db,
                id=str(uuid.uuid4()),
                judgment_list_id=jl.id,
                query_id=q.id,
                doc_id=f"doc-{i}",
                rating=2,
                source=r["source"],
                rater_ref=r["rater_ref"],
            )
        await db.commit()
    return jl.id


async def test_detail_returns_three_term_breakdown(async_client: httpx.AsyncClient) -> None:
    jl_id = await _seed_list_with_mixed_sources()
    resp = await async_client.get(f"/api/v1/judgment-lists/{jl_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    bd = body["source_breakdown"]
    assert bd == {"llm": 1, "human": 1, "click": 2}
    assert bd["llm"] + bd["human"] + bd["click"] == body["judgment_count"]
    # generation_params surfaced for the value-delta card (Story 4.3).
    assert body["generation_params"]["generation_kind"] == "ubi"


async def test_click_source_filter_returns_only_click_rows(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_list_with_mixed_sources()
    resp = await async_client.get(
        f"/api/v1/judgment-lists/{jl_id}/judgments", params={"source": "click"}
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 2
    assert all(r["source"] == "click" for r in rows)
