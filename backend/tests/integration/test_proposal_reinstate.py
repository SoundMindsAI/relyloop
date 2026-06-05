# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""POST /api/v1/proposals/{id}/reinstate tests (Phase 3 Story 3.1, FR-6).

Mirrors the ``test_proposal_reject.py`` pattern (read-check-mutate, 404
+ 409 discrimination). Covers AC-11, AC-12, AC-13 + ``?include_superseded``
URL filter behavior (D-15 revised).
"""

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


async def _supersede_proposal_directly(proposal_id: str) -> None:
    """Flip a pending proposal to superseded via the repo helper.

    Used by the reinstate tests instead of seeding a full chain — keeps
    these tests focused on the endpoint contract (chain-rollup coverage
    lives in the orchestrator integration tests).
    """
    factory = get_session_factory()
    async with factory() as db:
        proposal = await repo.get_proposal(db, proposal_id)
        assert proposal is not None
        await repo.bulk_mark_superseded(db, study_ids=[proposal.study_id])  # type: ignore[list-item]
        await db.commit()


async def test_reinstate_superseded_returns_200_with_pending(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-11: superseded → pending flip surfaces in the response body."""
    seeded = await seed_completed_study()
    await _supersede_proposal_directly(seeded["proposal_id"])
    response = await async_client.post(f"/api/v1/proposals/{seeded['proposal_id']}/reinstate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["id"] == seeded["proposal_id"]


async def test_reinstate_unknown_id_returns_404_proposal_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-12: 404 PROPOSAL_NOT_FOUND on unknown id (D-17 discrimination)."""
    response = await async_client.post(f"/api/v1/proposals/{uuid.uuid4()}/reinstate")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error_code"] == "PROPOSAL_NOT_FOUND"
    assert body["detail"]["retryable"] is False


async def test_reinstate_pending_returns_409_invalid_state(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-13: 409 INVALID_STATE_TRANSITION on already-pending row (D-16 reuse)."""
    seeded = await seed_completed_study()
    response = await async_client.post(f"/api/v1/proposals/{seeded['proposal_id']}/reinstate")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["error_code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"]["retryable"] is False
    assert "'pending'" in body["detail"]["message"]


async def test_reinstate_pr_opened_returns_409_invalid_state(
    async_client: httpx.AsyncClient,
) -> None:
    """Defense: pr_opened rows can't be reinstated either."""
    seeded = await seed_completed_study()
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_opened(
            db, seeded["proposal_id"], pr_url="https://example.com/pr/1"
        )
        await db.commit()
    response = await async_client.post(f"/api/v1/proposals/{seeded['proposal_id']}/reinstate")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["error_code"] == "INVALID_STATE_TRANSITION"


async def test_reinstate_idempotent_double_post_returns_409(
    async_client: httpx.AsyncClient,
) -> None:
    """A duplicate POST after a successful reinstate returns 409."""
    seeded = await seed_completed_study()
    await _supersede_proposal_directly(seeded["proposal_id"])
    first = await async_client.post(f"/api/v1/proposals/{seeded['proposal_id']}/reinstate")
    assert first.status_code == 200
    second = await async_client.post(f"/api/v1/proposals/{seeded['proposal_id']}/reinstate")
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "INVALID_STATE_TRANSITION"


# ---------------------------------------------------------------------------
# ?include_superseded filter (D-15 revised)
# ---------------------------------------------------------------------------


async def test_list_default_omits_superseded(
    async_client: httpx.AsyncClient,
) -> None:
    """D-15 revised: default URL (no ?include_superseded) hides superseded rows."""
    seeded = await seed_completed_study()
    await _supersede_proposal_directly(seeded["proposal_id"])
    response = await async_client.get("/api/v1/proposals")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["data"]}
    assert seeded["proposal_id"] not in ids


async def test_list_include_superseded_true_includes_superseded(
    async_client: httpx.AsyncClient,
) -> None:
    """D-15 revised: ?include_superseded=true surfaces superseded rows."""
    seeded = await seed_completed_study()
    await _supersede_proposal_directly(seeded["proposal_id"])
    response = await async_client.get("/api/v1/proposals?include_superseded=true")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["data"]}
    assert seeded["proposal_id"] in ids


async def test_list_explicit_status_overrides_include_superseded(
    async_client: httpx.AsyncClient,
) -> None:
    """D-15 revised: explicit ?status= beats implicit include_superseded.

    ``?status=pending&include_superseded=true`` returns ONLY pending rows
    (the superseded proposal is filtered by the explicit status, not
    re-admitted by the boolean).
    """
    seeded_a = await seed_completed_study()  # stays pending
    seeded_b = await seed_completed_study()
    await _supersede_proposal_directly(seeded_b["proposal_id"])
    response = await async_client.get("/api/v1/proposals?status=pending&include_superseded=true")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["data"]}
    assert seeded_a["proposal_id"] in ids
    assert seeded_b["proposal_id"] not in ids


async def test_list_explicit_status_superseded_returns_only_superseded(
    async_client: httpx.AsyncClient,
) -> None:
    """FR-1 + D-15: ?status=superseded returns only the superseded rows."""
    seeded_pending = await seed_completed_study()
    seeded_superseded = await seed_completed_study()
    await _supersede_proposal_directly(seeded_superseded["proposal_id"])
    response = await async_client.get("/api/v1/proposals?status=superseded")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["data"]}
    assert seeded_superseded["proposal_id"] in ids
    assert seeded_pending["proposal_id"] not in ids


async def test_list_single_value_status_backward_compatible(
    async_client: httpx.AsyncClient,
) -> None:
    """D-15 revised: existing ?status=pending URLs unchanged (single-value contract)."""
    seeded = await seed_completed_study()
    response = await async_client.get("/api/v1/proposals?status=pending")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["data"]}
    assert seeded["proposal_id"] in ids
