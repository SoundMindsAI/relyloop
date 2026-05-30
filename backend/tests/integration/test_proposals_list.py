# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""GET /api/v1/proposals tests (Story 3.3, FR-4 list)."""

from __future__ import annotations

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


async def test_list_default_returns_paginated_summaries(async_client: httpx.AsyncClient) -> None:
    """List endpoint returns pending proposals + X-Total-Count header."""
    seeded = await seed_completed_study()
    response = await async_client.get("/api/v1/proposals")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "next_cursor" in body
    assert "has_more" in body
    assert "X-Total-Count" in response.headers
    ids = [p["id"] for p in body["data"]]
    assert seeded["proposal_id"] in ids


async def test_status_filter_rejects_unknown_value_with_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Wire-value Literal enforcement: ?status=unknown surfaces as 422."""
    response = await async_client.get("/api/v1/proposals?status=garbage")
    assert response.status_code == 422


async def test_cluster_id_filter_returns_only_matching_rows(
    async_client: httpx.AsyncClient,
) -> None:
    """?cluster_id= filters to a single cluster's proposals."""
    seeded_a = await seed_completed_study()
    seeded_b = await seed_completed_study()
    response = await async_client.get(f"/api/v1/proposals?cluster_id={seeded_a['cluster_id']}")
    assert response.status_code == 200
    cluster_ids = {p["cluster"]["id"] for p in response.json()["data"]}
    assert cluster_ids == {seeded_a["cluster_id"]}
    # And the other cluster's proposal is excluded:
    assert seeded_b["cluster_id"] not in cluster_ids


async def test_status_pending_filter_includes_pending_proposals(
    async_client: httpx.AsyncClient,
) -> None:
    """?status=pending includes the orchestrator-inserted pending row."""
    seeded = await seed_completed_study()
    response = await async_client.get("/api/v1/proposals?status=pending")
    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["data"]]
    assert seeded["proposal_id"] in ids
    # All returned rows are pending.
    assert all(p["status"] == "pending" for p in response.json()["data"])
