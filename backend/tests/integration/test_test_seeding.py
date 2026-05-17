"""Integration smoke for the development-only seed endpoint.

End-to-end smoke for ``POST /api/v1/_test/studies/seed-completed`` against a
live Postgres. Asserts only the smoke surface: response status + response
shape. The dev-only env guard + request/response schema are covered by
``backend/tests/contract/test_test_endpoint_guard.py``; the actual repo
write path is exercised here so a bug in :mod:`backend.app.services.test_seeding`
surfaces before the Playwright E2E lane finds it (which runs against a
``make up`` stack and is much slower / harder to debug).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory

pytestmark = pytest.mark.integration


async def _seed_fk_chain() -> dict[str, str]:
    """Create the four FK rows the seed endpoint requires."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"title.boost": {"type": "float", "min": 0.5, "max": 5.0}},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
    }


async def test_seed_completed_returns_triple(async_client: httpx.AsyncClient) -> None:
    """Happy path — endpoint returns 201 with study_id + digest_id + proposal_id."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/studies/seed-completed",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert isinstance(body.get("study_id"), str) and body["study_id"]
    assert isinstance(body.get("digest_id"), str) and body["digest_id"]
    assert isinstance(body.get("proposal_id"), str) and body["proposal_id"]


async def test_seed_completed_without_proposal_returns_null(
    async_client: httpx.AsyncClient,
) -> None:
    """``with_pending_proposal=False`` returns ``proposal_id: null``."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/studies/seed-completed",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "with_pending_proposal": False,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert isinstance(body.get("study_id"), str) and body["study_id"]
    assert isinstance(body.get("digest_id"), str) and body["digest_id"]
    assert body.get("proposal_id") is None
