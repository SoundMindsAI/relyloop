"""GET /api/v1/proposals/{id} tests (Story 3.3, FR-4 detail)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_detail_with_study_id_inlines_study_summary_and_digest(
    async_client: httpx.AsyncClient,
) -> None:
    """Detail with study-backed proposal: study_summary + digest both populated."""
    seeded = await seed_completed_study()
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=seeded["study_id"],
            narrative="canonical narrative",
            parameter_importance={"field_boosts.title": 1.0},
            recommended_config={"field_boosts.title": 4.7},
            suggested_followups=["x"],
            generated_by="openai:gpt-4o-2024-08-06",
        )
        await db.commit()

    response = await async_client.get(f"/api/v1/proposals/{seeded['proposal_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["study_id"] == seeded["study_id"]
    assert body["study_summary"] is not None
    assert body["study_summary"]["query_set"]["query_count"] == 0  # no queries seeded
    assert body["digest"] is not None
    assert body["digest"]["narrative"] == "canonical narrative"


async def test_detail_for_manual_proposal_omits_study_summary_and_digest(
    async_client: httpx.AsyncClient,
) -> None:
    """Manual proposal (study_id NULL): study_summary AND digest both null."""
    seeded = await seed_completed_study()
    create = await async_client.post(
        "/api/v1/proposals",
        json={
            "cluster_id": seeded["cluster_id"],
            "template_id": seeded["template_id"],
            "config_diff": {},
        },
    )
    assert create.status_code == 201
    proposal_id = create.json()["id"]

    response = await async_client.get(f"/api/v1/proposals/{proposal_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["study_id"] is None
    assert body["study_summary"] is None
    assert body["digest"] is None


async def test_detail_unknown_id_returns_404_proposal_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get(f"/api/v1/proposals/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "PROPOSAL_NOT_FOUND"
