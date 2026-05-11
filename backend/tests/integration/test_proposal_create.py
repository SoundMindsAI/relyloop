"""POST /api/v1/proposals tests (Story 3.2, FR-4 / AC-6 — manual creation)."""

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


async def test_manual_proposal_creates_pending_row(async_client: httpx.AsyncClient) -> None:
    """AC-6: POST /proposals creates a status='pending' row with study_id NULL."""
    seeded = await seed_completed_study()
    body = {
        "cluster_id": seeded["cluster_id"],
        "template_id": seeded["template_id"],
        "config_diff": {"field_boosts.title": {"from": 2.0, "to": 4.0}},
    }
    response = await async_client.post("/api/v1/proposals", json=body)
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["study_id"] is None
    assert payload["study_trial_id"] is None
    assert payload["config_diff"] == {"field_boosts.title": {"from": 2.0, "to": 4.0}}

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, payload["id"])
        assert row is not None
        assert row.status == "pending"
        assert row.study_id is None


async def test_create_with_unknown_cluster_returns_404(async_client: httpx.AsyncClient) -> None:
    seeded = await seed_completed_study()
    body = {
        "cluster_id": str(uuid.uuid4()),
        "template_id": seeded["template_id"],
        "config_diff": {},
    }
    response = await async_client.post("/api/v1/proposals", json=body)
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


async def test_create_with_unknown_template_returns_404(async_client: httpx.AsyncClient) -> None:
    seeded = await seed_completed_study()
    body = {
        "cluster_id": seeded["cluster_id"],
        "template_id": str(uuid.uuid4()),
        "config_diff": {},
    }
    response = await async_client.post("/api/v1/proposals", json=body)
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


async def test_create_with_missing_required_fields_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Pydantic validation surfaces as 422 VALIDATION_ERROR per the existing envelope."""
    response = await async_client.post("/api/v1/proposals", json={"config_diff": {}})
    assert response.status_code == 422
