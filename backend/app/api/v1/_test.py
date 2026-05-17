"""Test-only endpoints exposed when ``Settings.environment == "development"``.

These endpoints exist solely to support deterministic E2E coverage of
surfaces that are normally driven by long-running workers (e.g. the
orchestrator + digest worker producing a completed study with a digest).

**Security model.** Each endpoint guards on ``Settings.environment`` and
returns 404 ``RESOURCE_NOT_FOUND`` outside development. There is no auth
in MVP1 — the environment guard is the sole gate. Staging (MVP3+) and
production (MVP4+) MUST set ``ENVIRONMENT=staging``/``production`` so the
test surface disappears.

Origin: ``infra_e2e_seed_completed_study/idea.md`` (option 1 — API-direct
insertion path).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import Settings, get_settings
from backend.app.db.session import get_db
from backend.app.services.test_seeding import seed_study_completed_with_digest

router = APIRouter()

# Subpath chosen to make the test surface visually distinct from the
# production API. Anything under ``/api/v1/_test/...`` is gated and
# should never appear in operator scripts.
_TEST_PREFIX = "/_test"


def _require_development_env(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Dependency: return 404 unless ``Settings.environment == "development"``.

    Returns 404 rather than 403 so the endpoint shape is indistinguishable
    from "not registered" — an operator probing a production install
    cannot discover this surface exists.
    """
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "RESOURCE_NOT_FOUND",
                "message": "Not found",
                "retryable": False,
            },
        )


class SeedCompletedStudyRequest(BaseModel):
    """Payload for ``POST /api/v1/_test/studies/seed-completed``.

    All four FK fields are required; the caller is responsible for
    seeding the parent rows first (typically via the public
    ``seedFullChain`` E2E helper).
    """

    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(min_length=1)
    query_set_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    judgment_list_id: str = Field(min_length=1)
    with_pending_proposal: bool = Field(
        default=True,
        description=(
            "When true (default), also insert a `status='pending'` proposal "
            "linked to the study so the digest panel's Open PR button "
            "renders enabled. Set false to test the AC-11 "
            "aria-disabled-button + tooltip path."
        ),
    )


class SeedCompletedStudyResponse(BaseModel):
    """IDs of the inserted rows; mirrors :class:`SeededStudyTriple`."""

    study_id: str
    digest_id: str
    proposal_id: str | None


@router.post(
    f"{_TEST_PREFIX}/studies/seed-completed",
    response_model=SeedCompletedStudyResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Seed a completed study + digest + (optional) pending proposal",
    description=(
        "Test-only endpoint. Returns 404 unless `ENVIRONMENT=development`. "
        "Inserts a study (driven through queued → running → completed via "
        "the legal state-machine transitions), 2 trials (one winner, one "
        "comparison), a digest, and optionally a pending proposal in a "
        "single transaction. Used by the Playwright E2E suite to cover "
        "the digest-panel surfaces (7 tooltip placements + AC-7 body "
        "content + AC-11 Open PR enabled/disabled branches) without "
        "waiting on the orchestrator + Optuna workers."
    ),
)
async def seed_completed_study(  # pragma: no cover  - integration only
    body: SeedCompletedStudyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeedCompletedStudyResponse:
    """See module docstring.

    Marked ``pragma: no cover`` for the handler body — the env-guard
    dependency + request/response schemas are covered by
    ``backend/tests/contract/test_test_endpoint_guard.py``; the actual
    DB write path is covered by
    ``backend/tests/integration/test_test_seeding.py``. The handler is
    one-line wire glue between those two layers.
    """
    triple = await seed_study_completed_with_digest(
        db,
        cluster_id=body.cluster_id,
        query_set_id=body.query_set_id,
        template_id=body.template_id,
        judgment_list_id=body.judgment_list_id,
        with_pending_proposal=body.with_pending_proposal,
    )
    await db.commit()
    return SeedCompletedStudyResponse(
        study_id=triple.study_id,
        digest_id=triple.digest_id,
        proposal_id=triple.proposal_id,
    )
