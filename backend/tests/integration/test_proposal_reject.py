"""POST /api/v1/proposals/{id}/reject tests (Story 3.4, FR-4 / AC-5)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_reject_pending_transitions_to_rejected_with_reason(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-5: reject sets status='rejected' + populates rejected_reason."""
    seeded = await seed_completed_study()
    response = await async_client.post(
        f"/api/v1/proposals/{seeded['proposal_id']}/reject",
        json={"reason": "metric delta too small to justify churn"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["rejected_reason"] == "metric delta too small to justify churn"


async def test_reject_already_terminal_returns_409_invalid_state(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-5: a second reject on a rejected proposal → 409 INVALID_STATE_TRANSITION."""
    seeded = await seed_completed_study()
    first = await async_client.post(
        f"/api/v1/proposals/{seeded['proposal_id']}/reject",
        json={"reason": "first"},
    )
    assert first.status_code == 200
    second = await async_client.post(
        f"/api/v1/proposals/{seeded['proposal_id']}/reject",
        json={"reason": "second"},
    )
    assert second.status_code == 409
    body = second.json()
    assert body["detail"]["error_code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"]["retryable"] is False


async def test_reject_unknown_id_returns_404_proposal_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.post(
        f"/api/v1/proposals/{uuid.uuid4()}/reject",
        json={"reason": "x"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "PROPOSAL_NOT_FOUND"


async def test_reject_with_no_reason_succeeds(async_client: httpx.AsyncClient) -> None:
    """reason is optional — empty body should be accepted."""
    seeded = await seed_completed_study()
    response = await async_client.post(
        f"/api/v1/proposals/{seeded['proposal_id']}/reject",
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["rejected_reason"] is None
