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
            declared_params={"boost": {"type": "float", "min": 0.5, "max": 5.0}},
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


# ---------------------------------------------------------------------------
# chore_auto_followup_e2e_chain_seed_helper — POST /api/v1/_test/auto-followup/
# seed-chain
# ---------------------------------------------------------------------------


async def test_seed_chain_returns_root_middles_leaf(async_client: httpx.AsyncClient) -> None:
    """Happy path — depth=2 returns root_id + 1 middle_id + leaf_id, parent links wired."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/auto-followup/seed-chain",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "depth": 2,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert isinstance(body.get("root_id"), str) and body["root_id"]
    assert isinstance(body.get("middle_ids"), list)
    # depth=2 → 3 nodes → exactly 1 middle.
    assert len(body["middle_ids"]) == 1
    middle_id = body["middle_ids"][0]
    assert isinstance(middle_id, str) and middle_id
    assert isinstance(body.get("leaf_id"), str) and body["leaf_id"]

    # Verify the parent_study_id wiring + status defaults via direct repo reads.
    factory = get_session_factory()
    async with factory() as db:
        root = await repo.get_study(db, body["root_id"])
        middle = await repo.get_study(db, middle_id)
        leaf = await repo.get_study(db, body["leaf_id"])

    assert root is not None and middle is not None and leaf is not None
    assert root.parent_study_id is None
    assert middle.parent_study_id == root.id
    assert leaf.parent_study_id == middle.id

    # Status defaults: root completed (terminal), middle queued (cancellable
    # for the E2E cascade-radio test), leaf queued (in-flight child).
    assert root.status == "completed"
    assert middle.status == "queued"
    assert leaf.status == "queued"

    # Depth counter decrements per hop: root=depth, middle=1, leaf=0.
    assert root.config.get("auto_followup_depth") == 2
    assert middle.config.get("auto_followup_depth") == 1
    assert leaf.config.get("auto_followup_depth") == 0


async def test_seed_chain_depth_1_has_no_middles(async_client: httpx.AsyncClient) -> None:
    """depth=1 collapses to root → leaf with empty middle_ids."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/auto-followup/seed-chain",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "depth": 1,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert body["middle_ids"] == []
    assert isinstance(body["root_id"], str) and isinstance(body["leaf_id"], str)


async def test_seed_chain_in_flight_flags_drive_status(async_client: httpx.AsyncClient) -> None:
    """``in_flight_leaf=False`` + ``in_flight_middle=False`` makes the whole chain completed."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/auto-followup/seed-chain",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "depth": 2,
            "in_flight_leaf": False,
            "in_flight_middle": False,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    factory = get_session_factory()
    async with factory() as db:
        root = await repo.get_study(db, body["root_id"])
        middle = await repo.get_study(db, body["middle_ids"][0])
        leaf = await repo.get_study(db, body["leaf_id"])
    assert root.status == "completed"  # type: ignore[union-attr]
    assert middle.status == "completed"  # type: ignore[union-attr]
    assert leaf.status == "completed"  # type: ignore[union-attr]


async def test_seed_chain_rejects_depth_zero(async_client: httpx.AsyncClient) -> None:
    """``depth=0`` is rejected at the Pydantic-validation layer (ge=1)."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/auto-followup/seed-chain",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "depth": 0,
        },
    )

    assert response.status_code == httpx.codes.UNPROCESSABLE_ENTITY, response.text
