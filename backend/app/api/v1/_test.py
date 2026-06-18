# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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

import asyncio
import logging
from typing import Annotated, Any

from arq.connections import ArqRedis
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import EngineTypeWire
from backend.app.core.settings import Settings, get_settings
from backend.app.db import repo
from backend.app.db.models import Digest, JudgmentList, Proposal, Study
from backend.app.db.session import get_db
from backend.app.services.demo_seeding import (
    ReseedStatusResponse,
    _now_iso,
    _resolve_engine_base_url,
    is_engine_reachable_with_version,
    status_get,
    status_set,
)
from backend.app.services.demo_seeding import (
    _demo_reseed_cleanup_test_gate as _demo_reseed_cleanup_test_gate,
)
from backend.app.services.demo_seeding import (
    reseed_status_is_stale as _reseed_status_is_stale,
)
from backend.app.services.demo_seeding import (
    run_demo_reseed_cleanup as _run_demo_reseed_cleanup,  # noqa: F401 — back-compat alias
)
from backend.app.services.test_seeding import (
    seed_auto_followup_chain,
    seed_study_completed_with_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# feat_home_demo_reseed_endpoint Story 1.2 (legacy) — AC-12 test hook.
# After bug_demo_reseed_fake_metric_regression converted the reseed to an
# Arq job, the cleanup pass runs in the worker (not the route handler).
# The canonical hook + cleanup function now live at
# :mod:`backend.app.services.demo_seeding`. The aliases above keep the
# AC-12 integration test importable until it's updated for the new flow.
__all__ = [
    "_demo_reseed_cleanup_test_gate",
    "_run_demo_reseed_cleanup",
]

# Subpath chosen to make the test surface visually distinct from the
# production API. Anything under ``/api/v1/_test/...`` is gated and
# should never appear in operator scripts.
_TEST_PREFIX = "/_test"


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    """Canonical error-envelope shape — mirrors ``studies.py:74-78``.

    All test-only DELETE handlers raise via this helper so the
    ``{detail: {error_code, message, retryable}}`` shape is consistent
    with the rest of the v1 API (env-guard 404 inline below uses the
    same shape via the original `HTTPException(detail=...)` pattern,
    kept inline for backwards compatibility with the
    `seed-completed` precedent).
    """
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


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
    winner_per_query: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional per-query metrics dict to populate on the winner "
            "trial. Shape: `{query_id: {metric_token: float}}` where "
            "metric_token matches what `scoring.score()` emits (e.g. "
            "`ndcg@10`). Set alongside `runner_up_per_query` to drive the "
            "ConfidencePanel happy path on `/studies/[id]`. When omitted, "
            "the seeded trials have `per_query_metrics IS NULL` (the "
            "pre-feat_pr_metric_confidence shape)."
        ),
    )
    runner_up_per_query: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional per-query metrics for the runner-up trial; pairs with `winner_per_query`."
        ),
    )
    suggested_followups: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "feat_digest_executable_followups Story 6.1 — optional structured "
            "FollowupItem list (`[{kind, rationale, search_space}]`) to seed "
            "on the digest. When omitted, the seeder writes two default text-kind "
            "items. The E2E Run-followup spec passes a `narrow` item so it can "
            "drive the per-card Run button + modal prefill flow."
        ),
    )
    extra_trial_metrics: list[float] | None = Field(
        default=None,
        description=(
            "Optional list of additional complete-trial `primary_metric` values "
            "(numbered from 2 upward) seeded on top of the default winner (0.487) "
            "+ runner-up (0.412). Used to push the study past the convergence "
            "classifier's usable-trial floor (5) so the `<ConvergencePanel>` "
            "renders a real verdict + curve instead of the too_few_trials null "
            "state (feat_study_convergence_indicator). Every value MUST be < 0.487 "
            "so the winner / best_metric / proposal / digest stay anchored to the "
            "unchanged 0.412 -> 0.487 story. Omit for the default 2-trial shape."
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
        winner_per_query=body.winner_per_query,
        runner_up_per_query=body.runner_up_per_query,
        suggested_followups=body.suggested_followups,
        extra_trial_metrics=body.extra_trial_metrics,
    )
    await db.commit()
    return SeedCompletedStudyResponse(
        study_id=triple.study_id,
        digest_id=triple.digest_id,
        proposal_id=triple.proposal_id,
    )


class SeedAutoFollowupChainRequest(BaseModel):
    """Payload for ``POST /api/v1/_test/auto-followup/seed-chain``.

    Seeds ``depth + 1`` linked studies (root → … → leaf) so E2E tests can
    cover the chain-panel parent-link / children-table / cascade-radio paths
    that the public ``POST /api/v1/studies`` endpoint can't drive
    (``parent_study_id`` is set only by the auto-followup worker).

    Closes ``chore_auto_followup_e2e_chain_seed_helper`` (idea #2).
    """

    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(min_length=1)
    query_set_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    judgment_list_id: str = Field(min_length=1)
    depth: int = Field(
        ge=1,
        le=5,
        description=(
            "Number of chain hops to seed. depth=1 → root + leaf (2 nodes). "
            "depth=2 → root + 1 middle + leaf (3 nodes)."
        ),
    )
    in_flight_leaf: bool = Field(
        default=True,
        description=(
            "When True (default), the deepest node is left at status='queued'. "
            "When False, it's driven to 'completed' too. Default True matches the "
            "primary E2E use case: cascade-radio coverage where the middle node "
            "needs an in-flight child."
        ),
    )
    in_flight_middle: bool = Field(
        default=True,
        description=(
            "When True (default), the immediate parent of the leaf is left at "
            "status='queued' so the Cancel button is enabled (canCancel = "
            "running || queued per study-action-bar.tsx:46). Required for the "
            "cancel-modal cascade-radio test. When False, all intermediates "
            "are completed (more realistic chain state but cancel modal "
            "won't open on the middle)."
        ),
    )


class SeedAutoFollowupChainResponse(BaseModel):
    """IDs of every node in the seeded chain, in parent→child order."""

    root_id: str
    middle_ids: list[str]
    leaf_id: str


@router.post(
    f"{_TEST_PREFIX}/auto-followup/seed-chain",
    response_model=SeedAutoFollowupChainResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Seed an auto-followup chain of N+1 linked studies",
    description=(
        "Test-only endpoint. Returns 404 unless `ENVIRONMENT=development`. "
        "Inserts a chain of `depth + 1` studies where each child carries the "
        "prior node's id as `parent_study_id`. The public POST /studies "
        "endpoint does NOT accept `parent_study_id` (it's set only by the "
        "auto-followup worker via `repo.create_study(parent_study_id=...)`), "
        "so this endpoint is the only way to drive deterministic E2E "
        "coverage of chain-panel parent-link / children-table / cascade-"
        "radio paths. Closes chore_auto_followup_e2e_chain_seed_helper."
    ),
)
async def seed_auto_followup_chain_endpoint(  # pragma: no cover  - integration only
    body: SeedAutoFollowupChainRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeedAutoFollowupChainResponse:
    """Thin wire-glue. See module docstring + service-layer docstring."""
    triple = await seed_auto_followup_chain(
        db,
        cluster_id=body.cluster_id,
        query_set_id=body.query_set_id,
        template_id=body.template_id,
        judgment_list_id=body.judgment_list_id,
        depth=body.depth,
        in_flight_leaf=body.in_flight_leaf,
        in_flight_middle=body.in_flight_middle,
    )
    await db.commit()
    return SeedAutoFollowupChainResponse(
        root_id=triple.root_id,
        middle_ids=triple.middle_ids,
        leaf_id=triple.leaf_id,
    )


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — six test-only DELETE endpoints.
#
# All gated by ``_require_development_env`` so they 404 outside dev. Each
# handler does preflight ``SELECT EXISTS`` checks for non-cascade dependent
# tables before calling the repo's ``hard_delete_*`` function, emitting a
# resource-specific 409 envelope if any dependents remain. The cleanup
# script (``ui/tests/e2e/global-teardown.ts``) is responsible for ordering
# DELETE calls so 409s don't fire in normal flow — the 409 is a safety
# net against ordering bugs.
#
# Handler signature pattern (per implementation_plan.md §1.1 key interfaces):
# ``response_class=Response`` + ``return Response(status_code=204)`` guards
# the 204-no-body contract from FastAPI accidentally serializing a body.
# ---------------------------------------------------------------------------


@router.delete(
    f"{_TEST_PREFIX}/proposals/{{proposal_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a proposal (test-only)",
)
async def delete_test_proposal(
    proposal_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-1: Hard-delete the proposal row. No FK children — no preflight needed."""
    deleted = await repo.hard_delete_proposal(db, proposal_id)
    if not deleted:
        raise _err(404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} not found", False)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    f"{_TEST_PREFIX}/digests/{{digest_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a digest (test-only)",
)
async def delete_test_digest(
    digest_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-2: Hard-delete the digest row. No FK children — no preflight needed."""
    deleted = await repo.hard_delete_digest(db, digest_id)
    if not deleted:
        raise _err(404, "DIGEST_NOT_FOUND", f"digest {digest_id} not found", False)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    f"{_TEST_PREFIX}/studies/{{study_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a study (test-only)",
)
async def delete_test_study(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-3 — hard-delete the study row.

    Trials cascade-delete via existing FK. Preflight-checks ``proposals``
    + ``digests`` (both non-cascade); 409 if any dependent rows reference
    the study.
    """
    # Preflight: STUDY_HAS_DEPENDENT_PROPOSAL fires first (by code order).
    has_proposal = (
        await db.execute(select(exists().where(Proposal.study_id == study_id)))
    ).scalar()
    if has_proposal:
        raise _err(
            409,
            "STUDY_HAS_DEPENDENT_PROPOSAL",
            f"study {study_id} has dependent proposal; delete proposal(s) first",
            False,
        )
    has_digest = (await db.execute(select(exists().where(Digest.study_id == study_id)))).scalar()
    if has_digest:
        raise _err(
            409,
            "STUDY_HAS_DEPENDENT_DIGEST",
            f"study {study_id} has dependent digest; delete digest first",
            False,
        )
    deleted = await repo.hard_delete_study(db, study_id)
    if not deleted:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    f"{_TEST_PREFIX}/judgment-lists/{{judgment_list_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a judgment_list (test-only)",
)
async def delete_test_judgment_list(
    judgment_list_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-4 — hard-delete the judgment_list row.

    Judgments cascade-delete via existing FK. Preflight-checks ``studies``
    (non-cascade); 409 if any study references the judgment_list.
    """
    has_study = (
        await db.execute(select(exists().where(Study.judgment_list_id == judgment_list_id)))
    ).scalar()
    if has_study:
        raise _err(
            409,
            "JUDGMENT_LIST_HAS_DEPENDENT_STUDY",
            f"judgment_list {judgment_list_id} has dependent study; delete study(ies) first",
            False,
        )
    deleted = await repo.hard_delete_judgment_list(db, judgment_list_id)
    if not deleted:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment_list {judgment_list_id} not found",
            False,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    f"{_TEST_PREFIX}/query-sets/{{query_set_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a query_set (test-only)",
)
async def delete_test_query_set(
    query_set_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-5 — hard-delete the query_set row.

    Queries cascade-delete via existing FK. Preflight-checks ``studies``
    + ``judgment_lists`` (both non-cascade); 409 with resource-specific
    code if either references.
    """
    has_study = (
        await db.execute(select(exists().where(Study.query_set_id == query_set_id)))
    ).scalar()
    if has_study:
        raise _err(
            409,
            "QUERY_SET_HAS_DEPENDENT_STUDY",
            f"query_set {query_set_id} has dependent study; delete study(ies) first",
            False,
        )
    has_judgment_list = (
        await db.execute(select(exists().where(JudgmentList.query_set_id == query_set_id)))
    ).scalar()
    if has_judgment_list:
        raise _err(
            409,
            "QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST",
            f"query_set {query_set_id} has dependent judgment_list; delete judgment_list(s) first",
            False,
        )
    deleted = await repo.hard_delete_query_set(db, query_set_id)
    if not deleted:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query_set {query_set_id} not found",
            False,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    f"{_TEST_PREFIX}/query-templates/{{template_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Hard-delete a query_template (test-only)",
)
async def delete_test_query_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """FR-6 — hard-delete the query_template row.

    No FK children cascade with template. Preflight-checks ``studies``,
    ``proposals``, and ``judgment_lists.current_template_id`` in
    **fixed priority order: STUDY > PROPOSAL > JUDGMENT_LIST** (per
    spec §FR-6) — first match wins.
    """
    has_study = (
        await db.execute(select(exists().where(Study.template_id == template_id)))
    ).scalar()
    if has_study:
        raise _err(
            409,
            "QUERY_TEMPLATE_HAS_DEPENDENT_STUDY",
            f"query_template {template_id} has dependent study; delete study(ies) first",
            False,
        )
    has_proposal = (
        await db.execute(select(exists().where(Proposal.template_id == template_id)))
    ).scalar()
    if has_proposal:
        raise _err(
            409,
            "QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL",
            f"query_template {template_id} has dependent proposal; delete proposal(s) first",
            False,
        )
    has_judgment_list = (
        await db.execute(select(exists().where(JudgmentList.current_template_id == template_id)))
    ).scalar()
    if has_judgment_list:
        raise _err(
            409,
            "QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST",
            f"query_template {template_id} has dependent judgment_list; "
            f"delete judgment_list(s) first or clear current_template_id",
            False,
        )
    deleted = await repo.hard_delete_query_template(db, template_id)
    if not deleted:
        raise _err(
            404,
            "TEMPLATE_NOT_FOUND",
            f"template {template_id} not found",
            False,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Demo reseed (bug_demo_reseed_fake_metric_regression).
#
# Async pattern: POST enqueues an Arq job and returns 202; the worker
# (:func:`backend.workers.demo_reseed.run_demo_reseed`) does the actual
# wipe + real-study reseed and writes progress to a Redis key. The
# frontend polls ``GET /api/v1/_test/demo/reseed/status`` for updates.
#
# The cleanup pass (formerly inline at this site) lives at
# :func:`backend.app.services.demo_seeding.run_demo_reseed_cleanup` and
# is invoked by the worker on failure under the held advisory lock.
# ---------------------------------------------------------------------------


class ReseedRequest(BaseModel):
    """Optional body for ``POST /api/v1/_test/demo/reseed``.

    feat_selective_engine_startup_and_demo Story 2.2 / FR-4.

    When ``engines`` is null, missing, or the body itself is empty,
    behaviour is identical to today: reseed every reachable engine. When
    provided, only scenarios whose ``engine_type`` is in the list are
    attempted; the others are recorded in ``scenarios_skipped`` with
    reason ``user_excluded`` (FR-5, FR-6).

    The inner ``min_length=1`` rejects ``engines: []`` at validation
    (decision D-7): an empty list is a no-op request with no legitimate
    workflow, so it returns 422 ``VALIDATION_ERROR`` rather than
    silently doing nothing. ``engines: null`` and a missing key stay
    valid — those are the well-known "use the default" sentinels.
    """

    model_config = ConfigDict(extra="forbid")

    engines: list[EngineTypeWire] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional subset of {elasticsearch, opensearch, solr}. When "
            "non-null, reseed only scenarios whose engine_type is in "
            "this list — others are skipped with reason 'user_excluded'. "
            "Null or omitted = reseed every reachable engine (current "
            "behavior). Empty list is rejected at validation."
        ),
    )


@router.post(
    f"{_TEST_PREFIX}/demo/reseed",
    response_model=ReseedStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Enqueue a demo-state reseed (dev-only, async)",
    description=(
        "Enqueues an Arq job that wipes the demo Postgres tables + ES/OS "
        "indices, then re-seeds the 4 demo scenarios from "
        "``scripts/seed_meaningful_demos.py`` using REAL studies (real "
        "Optuna trials, real metrics per scenario). Returns 202 + an "
        "initial ``ReseedStatusResponse`` immediately; the frontend polls "
        "``GET /api/v1/_test/demo/reseed/status`` for progress.\n\n"
        "Per ``bug_demo_reseed_fake_metric_regression``. Replaces the "
        "previous synchronous path that called "
        "``/_test/studies/seed-completed`` and produced identical "
        "``best_metric=0.487`` rows for every scenario.\n\n"
        "Optional ``engines`` body filter (feat_selective_engine_startup_"
        "and_demo FR-4): when present, only scenarios whose engine_type "
        "is in the list are attempted; the others are reported in "
        "``scenarios_skipped`` with reason ``user_excluded``. Null or "
        "missing = reseed every reachable engine (today's behavior)."
    ),
)
async def reseed_demo(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    body: Annotated[ReseedRequest | None, Body()] = None,
) -> ReseedStatusResponse:
    """Enqueue the demo-reseed Arq job + return immediately.

    Operational notes:

    - Status persistence: the worker writes to Redis under the key
      :data:`backend.app.services.demo_seeding.DEMO_RESEED_STATUS_KEY`.
      This handler seeds the key with a ``running`` payload before
      enqueueing so the frontend's first poll never sees ``idle``.
    - Concurrency: a deterministic Arq job id keyed on the literal
      ``"demo_reseed:singleton"`` prevents a double-clicked button from
      enqueuing two simultaneous jobs. The worker's advisory-lock
      acquisition is a belt-and-suspenders safeguard.
    - On 409 ``SEED_IN_PROGRESS``: returned when the current Redis
      status is ``running`` and was last updated <1 hour ago. The
      operator should wait + poll the status endpoint.
    """
    arq_pool: ArqRedis | None = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise _err(
            503,
            "ARQ_POOL_UNAVAILABLE",
            "Worker pool not initialized; cannot enqueue reseed job.",
            True,
        )

    # Reuse the shared ArqRedis pool (subclasses Redis) instead of opening
    # a fresh connection pool per request — per Gemini PR #286 finding #2.
    current = await status_get(arq_pool)
    if current.status == "running" and not _reseed_status_is_stale(current):
        raise _err(
            409,
            "SEED_IN_PROGRESS",
            (
                "A demo reseed is already running. Poll "
                "GET /api/v1/_test/demo/reseed/status for progress."
            ),
            True,
        )
    # Per ``bug_demo_reseed_button_silent_enqueue_failure``: if the prior
    # ``running`` payload is older than ``DEMO_RESEED_JOB_TIMEOUT_S``, the
    # worker either crashed silently (container restart, OOM, hard kill
    # before any exception handler ran) or hit a path the worker's
    # ``except BaseException`` barrier somehow missed. Treat as failed and
    # let this POST proceed instead of leaving the operator 409-blocked
    # forever. The new ``initial`` payload below overwrites the stale one.

    # 4 small SCENARIOS + 1 rich ESCI scenario — matches ``make seed-demo``.
    # Worker will overwrite this status once it picks up the job, but
    # use the same total here so the operator never sees a misleading
    # "Scenario 0 of 4" while the worker is still queued.
    from backend.app.services.demo_seeding import SCENARIOS as _DEMO_SCENARIOS

    initial = ReseedStatusResponse(
        status="running",
        started_at=_now_iso(),
        scenarios_total=len(_DEMO_SCENARIOS) + 1,
        scenarios_completed=0,
        current_step="enqueued — waiting for worker",
    )
    await status_set(arq_pool, initial)

    # Deterministic job id — Arq drops duplicate enqueues with the same
    # _job_id within its dedup window (default 60s). A faster double-click
    # gets one job; a slower retry after the previous run completed
    # creates a fresh job (because Redis state has moved on).
    #
    # ``engines`` is None when the body is absent OR ``{"engines": null}``
    # OR ``{}`` (FastAPI parses an empty body to None when the body param
    # has ``default=None``). All three are the "reseed every reachable
    # engine" sentinel. A non-None list reached this line only after
    # Pydantic's ``min_length=1`` allowed it through, so empty-list
    # already returned 422 above.
    engines_filter = body.engines if body is not None else None
    job = await arq_pool.enqueue_job(
        "run_demo_reseed",
        _job_id="demo_reseed:singleton",
        engines=engines_filter,
    )
    logger.info(
        "demo_reseed_enqueued",
        extra={
            "job_id": job.job_id if job is not None else None,
            "engines": engines_filter,
        },
    )
    return initial


@router.get(
    f"{_TEST_PREFIX}/demo/reseed/status",
    response_model=ReseedStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Poll the current demo-reseed progress (dev-only)",
    description=(
        "Returns the current reseed status from Redis. When no reseed "
        "has ever run (or the result TTL'd out), returns "
        "``{status: 'idle'}`` rather than 404 so the frontend's polling "
        "loop is trivially safe."
    ),
)
async def reseed_demo_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReseedStatusResponse:
    """Return the current :class:`ReseedStatusResponse` payload.

    Reuses the shared ArqRedis pool from ``request.app.state`` when
    available (per Gemini PR #286 finding #3) to avoid opening a fresh
    connection pool on every poll. Falls back to a request-scoped
    ``Redis.from_url`` if the worker pool isn't initialized yet
    (e.g., on first boot before lifespan startup completes).
    """
    arq_pool: ArqRedis | None = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        return await status_get(arq_pool)

    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        return await status_get(redis)
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Demo engine capability probe (feat_selective_engine_startup_and_demo Story 2.1).
#
# Powers the "Reset to demo state" modal's engine-selection checkbox group:
# the frontend fetches this endpoint when the dialog opens to know which
# engines are running, then defaults the checkbox group to all reachable
# engines. The reseed POST body's optional ``engines`` filter (Story 2.2)
# is grounded in the same ``EngineTypeWire`` allowlist, so the two
# surfaces never disagree on what's a valid engine name.
#
# This endpoint is a pure network probe — no Arq dependency, no Redis
# dependency. Probes the three engines concurrently via ``asyncio.gather``
# so the worst case stays ~2s (each ``is_engine_reachable`` is bounded by
# its own 2s timeout). Returns 200 even when all three are unreachable
# (the reachability data IS the response, not the error).
# ---------------------------------------------------------------------------


class DemoEngineStatus(BaseModel):
    """Per-engine reachability + version snapshot for the reset-modal.

    ``version`` is the engine's self-reported version number
    (``body['version']['number']`` for ES/OS,
    ``lucene.solr-spec-version`` for Solr). ``None`` when the engine is
    unreachable or the version field is missing / malformed
    (the reachability gate still passes — RelyLoop just can't tell
    what version answered). feat_engine_version_selection FR-7.
    """

    model_config = ConfigDict(extra="forbid")

    engine_type: EngineTypeWire
    reachable: bool
    version: str | None = None


class DemoEnginesResponse(BaseModel):
    """Response shape of ``GET /api/v1/_test/demo/engines``."""

    model_config = ConfigDict(extra="forbid")

    engines: list[DemoEngineStatus]


# Canonical host URLs the demo reseed uses for each engine. Probed verbatim
# from CLI contexts; the API container translates them to Compose service
# DNS names via ``_resolve_engine_base_url`` (which is what the demo reseed
# orchestrator also uses). Centralized here so a Compose port change only
# touches one place. Matches the URLs referenced by SCENARIOS and the rich
# scenario at ``backend.app.services.demo_seeding``.
_DEMO_ENGINE_PROBE_URLS: tuple[tuple[EngineTypeWire, str], ...] = (
    ("elasticsearch", "http://localhost:9200"),
    ("opensearch", "http://localhost:9201"),
    ("solr", "http://localhost:8983"),
)


@router.get(
    f"{_TEST_PREFIX}/demo/engines",
    response_model=DemoEnginesResponse,
    status_code=status.HTTP_200_OK,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Report which engines are reachable (dev-only)",
    description=(
        "Probes Elasticsearch, OpenSearch, and Apache Solr concurrently "
        "and returns per-engine reachability. Always returns 200 — when "
        "no engine is reachable, the response carries "
        "``reachable=false`` on all three rather than erroring. Powers "
        "the reset-to-demo modal's engine-selection checkbox group "
        "(feat_selective_engine_startup_and_demo FR-7)."
    ),
)
async def demo_engines() -> DemoEnginesResponse:
    """Probe the three engines in parallel; return per-engine reachability.

    Each ``is_engine_reachable_with_version`` call is bounded by its own 2s
    timeout (defined at
    :func:`backend.app.services.demo_seeding.is_engine_reachable_with_version`),
    so the worst-case wall-clock for this handler is ~2s even when all
    three engines are unreachable. The engine_type ordering of the
    response is deterministic and matches ``_DEMO_ENGINE_PROBE_URLS``.
    """
    resolved = [
        (engine_type, _resolve_engine_base_url(url)) for engine_type, url in _DEMO_ENGINE_PROBE_URLS
    ]
    # feat_engine_version_selection FR-8: call the version-aware sibling probe
    # so each row carries the engine's self-reported version when reachable.
    # The original is_engine_reachable stays in this module (imported above)
    # because snapshot_engine_reachability — used by the reseed orchestrator —
    # still consumes the bool-only path; only this capability endpoint needs
    # the richer return shape.
    results = await asyncio.gather(
        *(is_engine_reachable_with_version(url, engine_type) for engine_type, url in resolved)
    )
    return DemoEnginesResponse(
        engines=[
            DemoEngineStatus(engine_type=engine_type, reachable=ok, version=version)
            for (engine_type, _), (ok, version) in zip(resolved, results, strict=True)
        ]
    )
