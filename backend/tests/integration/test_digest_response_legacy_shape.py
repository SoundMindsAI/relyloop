# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Defensive read-path: legacy list[str] JSONB unwraps to text items (AC-5).

After Story 3.3 migrated digests.suggested_followups from ARRAY(Text) to
JSONB, the migration's PL/pgSQL helper wraps legacy text rows as
``[{kind: 'text', rationale: <text>, search_space: null}]``. But should
any consumer (a test fixture, a hand-edited row, a future regression)
ever write a raw ``["str", ...]`` payload into the JSONB column, the
defensive wrapper in the API layer (Story 4.1) must still produce a
valid response. This test seeds exactly that shape and asserts the
``GET /api/v1/studies/{id}/digest`` endpoint wraps it cleanly.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_list_of_strings_jsonb_wraps_at_response_layer(
    async_client: httpx.AsyncClient,
) -> None:
    """A row whose JSONB is ``["a", "b"]`` returns 2 text-kind items."""
    seeded = await seed_completed_study()
    study_id = seeded["study_id"]

    # Seed a digest with the defensive-but-illegal raw list[str] JSONB
    # payload directly via raw SQL — bypasses the worker contract that
    # would normally serialize structured dicts.
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO digests (id, study_id, narrative, parameter_importance, "
                "recommended_config, suggested_followups, generated_by, generated_at) "
                "VALUES (:id, :sid, 'n', '{}'::jsonb, '{}'::jsonb, "
                "CAST(:sf AS jsonb), 'local:test', NOW())"
            ),
            {
                "id": str(uuid.uuid4()),
                "sid": study_id,
                "sf": '["a", "b"]',
            },
        )
        await db.commit()

    response = await async_client.get(f"/api/v1/studies/{study_id}/digest")
    assert response.status_code == 200
    body = response.json()
    sf = body["suggested_followups"]
    assert len(sf) == 2
    assert sf[0]["kind"] == "text"
    assert sf[0]["rationale"] == "a"
    assert sf[0]["search_space"] is None
    assert sf[1]["kind"] == "text"
    assert sf[1]["rationale"] == "b"
