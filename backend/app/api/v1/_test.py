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

import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import Settings, get_settings
from backend.app.db import repo
from backend.app.db.models import Digest, JudgmentList, Proposal, Study
from backend.app.db.session import get_db, get_engine
from backend.app.services.demo_seeding import (
    _ES_DELETE_AUTH,
    _OS_DELETE_AUTH,
    _TRUNCATE_DEMO_TABLES_SQL,
    DEMO_RESEED_LOCK_KEY,
    ReseedSummary,
    _resolve_engine_base_url,
    reseed_demo_state,
)
from backend.app.services.test_seeding import seed_study_completed_with_digest
from scripts.seed_meaningful_demos import (
    DEMO_ES_INDICES,
    DEMO_OS_INDICES,
)
from scripts.seed_meaningful_demos import (
    ES as _CLI_ES,
)
from scripts.seed_meaningful_demos import (
    OS as _CLI_OS,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# feat_home_demo_reseed_endpoint Story 1.2 — test hook for AC-12 (cleanup-
# while-locked race). Production callers MUST leave this ``None``; the
# integration test monkeypatches it to a ``threading.Event`` so the test
# can fire a concurrent reseed during the cleanup pass and observe the
# 409 SEED_IN_PROGRESS response. Documented module-private; no production
# code path reads or writes it. Per the plan §3.2 Task 8.
_demo_reseed_cleanup_test_gate: Any = None

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
    )
    await db.commit()
    return SeedCompletedStudyResponse(
        study_id=triple.study_id,
        digest_id=triple.digest_id,
        proposal_id=triple.proposal_id,
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
# feat_home_demo_reseed_endpoint Story 1.2 — POST /api/v1/_test/demo/reseed.
#
# Orchestrates a full wipe + reseed of the 4 demo scenarios from
# ``scripts/seed_meaningful_demos.py``. Gated by ``_require_development_env``
# so it returns 404 outside dev (same envelope as "not registered" — see
# spec §11/§FR-2).
#
# Architecture per spec §5/§10:
#   - Acquires a Postgres session-level advisory lock on a DEDICATED
#     pinned ``AsyncConnection`` (NOT the request-scoped ``AsyncSession``
#     from ``get_db``). Per FR-3 / AC-16, holding the lock on a
#     dedicated connection guarantees the same backend pid holds the
#     lock for the entire orchestration window, including the cleanup
#     pass on failure.
#   - Constructs TWO ``httpx.AsyncClient`` instances per FR-1c:
#       * ``api_client`` — self-calls ``http://localhost:8000`` (uses
#         FastAPI's loopback to hit the same process).
#       * ``engine_client`` — absolute URLs against ES/OS.
#     Each carries the per-call timeout from
#     ``settings.demo_reseed_per_call_http_timeout_s``. Per FR-4 there
#     is NO outer wall-clock timeout — only the per-call ceiling.
#   - On any exception, rolls back the caller's session, runs
#     :func:`_run_demo_reseed_cleanup` under the held lock (using a
#     fresh DB connection — cycle-1 finding B1), then raises 503
#     SEED_FAILED.
#   - Releases the advisory lock in ``finally`` (only if it was
#     successfully acquired — cycle-14 finding B1).
# ---------------------------------------------------------------------------


async def _run_demo_reseed_cleanup(engine_client: httpx.AsyncClient) -> None:
    """Best-effort cleanup pass. Per spec FR-2.

    Opens a FRESH DB connection via the module's engine (NOT the
    caller's ``AsyncSession``, which may be in a broken/rolled-back
    state after the mid-flight exception). Each cleanup step
    (TRUNCATE, index DELETEs) tolerates every error so cleanup always
    completes. Runs while the route handler still holds the advisory
    lock — so concurrent reseeds 409 until the handler unlocks.

    Cycle-1 GPT-5.5 plan review B1 — cleanup MUST use a fresh DB unit,
    not the caller's session.
    """
    # AC-12 test hook: a ``threading.Event`` injected by the integration
    # test gates the cleanup pass on a signal from the test, letting the
    # test fire a concurrent reseed during the window when the cleanup
    # is mid-flight but the advisory lock is still held.
    if _demo_reseed_cleanup_test_gate is not None:
        import asyncio

        await asyncio.to_thread(_demo_reseed_cleanup_test_gate.wait)

    engine = get_engine()
    try:
        async with engine.begin() as cleanup_conn:
            await cleanup_conn.execute(text(_TRUNCATE_DEMO_TABLES_SQL))
        logger.info("demo_reseed_cleanup_truncated")
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        logger.warning("demo_reseed_cleanup_truncate_failed", extra={"exc": str(exc)})

    es_base = _resolve_engine_base_url(_CLI_ES)
    for idx in DEMO_ES_INDICES:
        try:
            resp = await engine_client.delete(
                f"{es_base}/{idx}", auth=httpx.BasicAuth(*_ES_DELETE_AUTH)
            )
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_es_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.info(
                "demo_reseed_cleanup_es_delete_skipped",
                extra={"idx": idx, "exc": str(exc)},
            )

    os_base = _resolve_engine_base_url(_CLI_OS)
    for idx in DEMO_OS_INDICES:
        try:
            resp = await engine_client.delete(
                f"{os_base}/{idx}", auth=httpx.BasicAuth(*_OS_DELETE_AUTH)
            )
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_os_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.info(
                "demo_reseed_cleanup_os_delete_skipped",
                extra={"idx": idx, "exc": str(exc)},
            )


@router.post(
    f"{_TEST_PREFIX}/demo/reseed",
    response_model=ReseedSummary,
    status_code=status.HTTP_200_OK,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
    summary="Wipe + reseed all 4 demo scenarios (dev-only)",
    description=(
        "Wipes the demo Postgres tables and ES/OS indices, then re-seeds "
        "the 4 demo scenarios from ``scripts/seed_meaningful_demos.py``. "
        "Gated by ``ENVIRONMENT=development`` — 404 RESOURCE_NOT_FOUND "
        "outside dev. Per feat_home_demo_reseed_endpoint spec."
    ),
)
async def reseed_demo(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReseedSummary:
    """See module-level block comment above."""
    engine = get_engine()
    async with engine.connect() as lock_conn:
        acquired = False  # Sentinel; set True only after successful acquisition.
        try:
            acquired = bool(
                (
                    await lock_conn.execute(
                        text("SELECT pg_try_advisory_lock(:k)"),
                        {"k": DEMO_RESEED_LOCK_KEY},
                    )
                ).scalar_one()
            )
            # Close the implicit txn SQLAlchemy autobegan for the SELECT.
            # Per cycle-14 plan review B1 — if this commit raises, the
            # ``finally`` block still runs the unlock under the
            # ``acquired`` guard.
            await lock_conn.commit()

            if not acquired:
                raise _err(
                    409,
                    "SEED_IN_PROGRESS",
                    "A demo reseed is already running; wait for it to complete.",
                    True,
                )

            timeout = httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)
            async with (
                httpx.AsyncClient(base_url="http://localhost:8000", timeout=timeout) as api_client,
                httpx.AsyncClient(timeout=timeout) as engine_client,
            ):
                try:
                    logger.info("demo_reseed_started")
                    summary = await reseed_demo_state(db, api_client, engine_client)
                    logger.info(
                        "demo_reseed_completed",
                        extra={"duration_ms": summary.duration_ms},
                    )
                    return summary
                except HTTPException:
                    # Propagate our own envelope responses verbatim.
                    raise
                except Exception as exc:  # noqa: BLE001 - route handler boundary
                    logger.warning(
                        "demo_reseed_failed",
                        extra={
                            "exc_class": type(exc).__name__,
                            "exc": str(exc),
                        },
                    )
                    # Roll back the caller's session before cleanup so
                    # the request's transaction-scope teardown is clean
                    # (cycle-2 plan-review finding A2).
                    try:
                        await db.rollback()
                    except Exception as rb_exc:  # noqa: BLE001
                        logger.warning(
                            "demo_reseed_caller_session_rollback_failed",
                            extra={"exc": str(rb_exc)},
                        )
                    await _run_demo_reseed_cleanup(engine_client)
                    raise _err(
                        503,
                        "SEED_FAILED",
                        (
                            "Demo reseed failed mid-flight. Cleanup applied. "
                            "On a timeout edge, run `docker compose restart api` "
                            "before retry — see the demo-reseed runbook."
                        ),
                        True,
                    ) from exc
        finally:
            if acquired:
                released = bool(
                    (
                        await lock_conn.execute(
                            text("SELECT pg_advisory_unlock(:k)"),
                            {"k": DEMO_RESEED_LOCK_KEY},
                        )
                    ).scalar_one()
                )
                await lock_conn.commit()
                if released:
                    logger.info(
                        "demo_reseed_advisory_unlock",
                        extra={"released": True, "key": DEMO_RESEED_LOCK_KEY},
                    )
                else:
                    logger.warning(
                        "demo_reseed_advisory_unlock_returned_false",
                        extra={"released": False, "key": DEMO_RESEED_LOCK_KEY},
                    )
