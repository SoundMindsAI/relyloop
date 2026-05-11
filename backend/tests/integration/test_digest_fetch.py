"""GET /api/v1/studies/{id}/digest tests (Story 3.1, FR-3 / AC-3 / AC-4)."""

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


async def test_fetch_existing_digest_returns_200(async_client: httpx.AsyncClient) -> None:
    """AC-3: digest fetch returns the body when the digest exists."""
    seeded = await seed_completed_study()
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=seeded["study_id"],
            narrative="canonical narrative",
            parameter_importance={"field_boosts.title": 0.5, "tie_breaker": 0.5},
            recommended_config={"field_boosts.title": 4.7},
            suggested_followups=["try fuzziness=AUTO"],
            generated_by="openai:gpt-4o-2024-08-06",
        )
        await db.commit()

    response = await async_client.get(f"/api/v1/studies/{seeded['study_id']}/digest")
    assert response.status_code == 200
    body = response.json()
    assert body["narrative"] == "canonical narrative"
    assert body["recommended_config"] == {"field_boosts.title": 4.7}
    assert body["suggested_followups"] == ["try fuzziness=AUTO"]
    assert body["generated_by"] == "openai:gpt-4o-2024-08-06"


async def test_fetch_on_running_study_returns_404_digest_not_ready(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-4: study not yet completed → 404 DIGEST_NOT_READY (retryable).

    Phase 2 wires a SQLAlchemy event listener that raises
    ``StudyStateProtectionError`` on direct status UPDATEs outside the
    service layer (FR-7), so we seed the study in ``running`` state via
    the helper's ``study_status`` parameter rather than mutating after
    create.
    """
    seeded = await seed_completed_study(study_status="running", best_metric=None)
    factory = get_session_factory()
    async with factory() as db:
        study = await repo.get_study(db, seeded["study_id"])
        assert study is not None
        assert study.status == "running"
    del factory  # only here to satisfy the cleanup audit

    response = await async_client.get(f"/api/v1/studies/{seeded['study_id']}/digest")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error_code"] == "DIGEST_NOT_READY"
    assert body["detail"]["retryable"] is True


async def test_fetch_on_completed_study_without_digest_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Completed study but no digest yet (worker lag) → 404 DIGEST_NOT_READY."""
    seeded = await seed_completed_study()
    response = await async_client.get(f"/api/v1/studies/{seeded['study_id']}/digest")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error_code"] == "DIGEST_NOT_READY"


async def test_fetch_unknown_study_returns_404_study_not_found(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown study_id → 404 STUDY_NOT_FOUND (NOT DIGEST_NOT_READY)."""
    response = await async_client.get(f"/api/v1/studies/{uuid.uuid4()}/digest")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"
