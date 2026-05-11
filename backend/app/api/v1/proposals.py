"""Digest fetch + proposal CRUD endpoints (feat_digest_proposal Epic 3).

Six endpoints under ``/api/v1``:

* ``GET /studies/{id}/digest`` — Story 3.1; fetch the digest for a
  completed study; 404 ``DIGEST_NOT_READY`` if the worker hasn't run yet.
* ``POST /proposals`` — Story 3.2; manual proposal creation (chat-agent
  hand-crafted tweaks; ``study_id`` and ``study_trial_id`` left NULL).
* ``GET /proposals`` — Story 3.3; cursor-paginated list with status +
  cluster_id filters + ``X-Total-Count`` header.
* ``GET /proposals/{id}`` — Story 3.3; detail with inline study_summary
  + digest (saves the UI a fan-out query).
* ``POST /proposals/{id}/reject`` — Story 3.4; ``pending → rejected``
  transition.
* ``POST /proposals/{id}/open_pr`` — feat_github_pr_worker Story 3.1;
  preflight validates the cluster has a config_repo + the per-repo PAT
  is readable, then enqueues the ``open_pr`` worker job (deterministic
  ``_job_id`` for dedup per AC-12). 503 ``QUEUE_UNAVAILABLE`` (cycle-2
  F5) when the Arq pool is missing or enqueue raises — NOT best-effort,
  because this feature has no boot-scan recovery path.

The handlers share three private helpers (``_err``, ``_encode_cursor``,
``_decode_cursor``) copied from :mod:`backend.app.api.v1.judgments` /
:mod:`backend.app.api.v1.studies`. The hoist to a shared helper module
is deferred to the existing follow-up ``chore_router_helpers_hoist`` per
the feat_llm_judgments deferral note.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Annotated

import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    CreateProposalRequest,
    DigestResponse,
    OpenPrResponse,
    ProposalDetail,
    ProposalsListResponse,
    ProposalStatusWire,
    ProposalSummary,
    RejectProposalRequest,
    _ClusterEmbed,
    _DigestEmbed,
    _StudySummary,
    _TemplateEmbed,
)
from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.db.models import Proposal
from backend.app.db.repo.proposal import InvalidStateTransition
from backend.app.db.session import get_db

router = APIRouter()
logger = get_logger(__name__)

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def _encode_cursor(created_at: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at.isoformat(), row_id]).encode()).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        created_at = datetime.fromisoformat(decoded[0])
        row_id = str(decoded[1])
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    return created_at, row_id


# ---------------------------------------------------------------------------
# Detail-assembly helpers
# ---------------------------------------------------------------------------


async def _assemble_proposal_detail(db: AsyncSession, proposal: Proposal) -> ProposalDetail:
    """Build the full ProposalDetail wire shape with inline study_summary + digest."""
    cluster = await repo.get_cluster(db, proposal.cluster_id)
    template = await repo.get_query_template(db, proposal.template_id)
    if cluster is None or template is None:
        # Defensive: the FKs are NOT NULL at the DB level, so this
        # branch is unreachable in practice.
        raise _err(
            500,
            "INTERNAL_ERROR",
            f"proposal {proposal.id} references missing cluster/template",
            False,
        )

    study_summary: _StudySummary | None = None
    digest_embed: _DigestEmbed | None = None
    if proposal.study_id is not None:
        study = await repo.get_study(db, proposal.study_id)
        if study is not None:
            query_set = await repo.get_query_set(db, study.query_set_id)
            jl = await repo.get_judgment_list(db, study.judgment_list_id)
            qs_count = (
                await repo.count_queries_in_set(db, study.query_set_id)
                if query_set is not None
                else 0
            )
            study_summary = _StudySummary(
                id=study.id,
                name=study.name,
                status=study.status,
                best_metric=study.best_metric,
                best_trial_id=study.best_trial_id,
                query_set={
                    "id": query_set.id if query_set else study.query_set_id,
                    "name": query_set.name if query_set else "",
                    "query_count": qs_count,
                },
                judgment_list={
                    "id": jl.id if jl else study.judgment_list_id,
                    "name": jl.name if jl else "",
                    "status": jl.status if jl else "",
                },
            )
        digest = await repo.get_digest_for_study(db, proposal.study_id)
        if digest is not None:
            digest_embed = _DigestEmbed(
                id=digest.id,
                narrative=digest.narrative,
                parameter_importance=digest.parameter_importance,
                recommended_config=digest.recommended_config,
                suggested_followups=digest.suggested_followups,
                generated_at=digest.generated_at,
            )

    return ProposalDetail(
        id=proposal.id,
        study_id=proposal.study_id,
        study_summary=study_summary,
        study_trial_id=proposal.study_trial_id,
        cluster=_ClusterEmbed(
            id=cluster.id,
            name=cluster.name,
            engine_type=cluster.engine_type,
            environment=cluster.environment,
        ),
        template=_TemplateEmbed(
            id=template.id,
            name=template.name,
            version=template.version,
            engine_type=template.engine_type,
        ),
        config_diff=proposal.config_diff,
        metric_delta=proposal.metric_delta,
        status=proposal.status,  # narrowed by CHECK constraint
        pr_url=proposal.pr_url,
        pr_state=proposal.pr_state,  # narrowed by CHECK
        pr_merged_at=proposal.pr_merged_at,
        pr_open_error=proposal.pr_open_error,
        rejected_reason=proposal.rejected_reason,
        digest=digest_embed,
        created_at=proposal.created_at,
    )


async def _assemble_proposal_summary_batch(
    db: AsyncSession, proposals: list[Proposal]
) -> list[ProposalSummary]:
    """Batch-fetch clusters + templates to avoid N+1; assemble row summaries."""
    cluster_ids = {p.cluster_id for p in proposals}
    template_ids = {p.template_id for p in proposals}
    clusters_by_id = {}
    templates_by_id = {}
    for cid in cluster_ids:
        c = await repo.get_cluster(db, cid)
        if c is not None:
            clusters_by_id[cid] = c
    for tid in template_ids:
        t = await repo.get_query_template(db, tid)
        if t is not None:
            templates_by_id[tid] = t
    out: list[ProposalSummary] = []
    for p in proposals:
        c = clusters_by_id.get(p.cluster_id)
        t = templates_by_id.get(p.template_id)
        out.append(
            ProposalSummary(
                id=p.id,
                study_id=p.study_id,
                cluster=_ClusterEmbed(
                    id=c.id if c else p.cluster_id,
                    name=c.name if c else "",
                    engine_type=c.engine_type if c else "",
                    environment=c.environment if c else None,
                ),
                template=_TemplateEmbed(
                    id=t.id if t else p.template_id,
                    name=t.name if t else "",
                    version=t.version if t else 0,
                    engine_type=t.engine_type if t else None,
                ),
                status=p.status,
                pr_state=p.pr_state,
                pr_url=p.pr_url,
                metric_delta=p.metric_delta,
                created_at=p.created_at,
            )
        )
    return out


# ---------------------------------------------------------------------------
# GET /api/v1/studies/{id}/digest  (Story 3.1, FR-3 / AC-3 / AC-4)
# ---------------------------------------------------------------------------


@router.get(
    "/studies/{study_id}/digest",
    response_model=DigestResponse,
    tags=["digests"],
)
async def get_study_digest(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DigestResponse:
    """Fetch the digest for a completed study.

    Returns 404 ``DIGEST_NOT_READY`` (``retryable=true``) when:
    - the study is not in ``status='completed'``, OR
    - the study is completed but the worker hasn't written the digest yet
      (worker lag, or a worker-side terminal failure like
      ``OPENAI_NOT_CONFIGURED`` deferred the run).
    """
    study = await repo.get_study(db, study_id)
    if study is None:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)
    if study.status != "completed":
        raise _err(
            404,
            "DIGEST_NOT_READY",
            f"study is in status {study.status!r}; digest is only available on completed studies",
            True,
        )
    digest = await repo.get_digest_for_study(db, study_id)
    if digest is None:
        raise _err(
            404,
            "DIGEST_NOT_READY",
            f"digest for study {study_id} has not been written yet",
            True,
        )
    return DigestResponse(
        id=digest.id,
        study_id=digest.study_id,
        narrative=digest.narrative,
        parameter_importance=digest.parameter_importance,
        recommended_config=digest.recommended_config,
        suggested_followups=digest.suggested_followups,
        generated_by=digest.generated_by,
        generated_at=digest.generated_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/proposals  (Story 3.2, FR-4 / AC-6 — manual creation)
# ---------------------------------------------------------------------------


@router.post(
    "/proposals",
    response_model=ProposalDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["proposals"],
)
async def create_manual_proposal(
    body: CreateProposalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProposalDetail:
    """Manually create a proposal (chat-agent hand-crafted tweaks).

    ``study_id`` and ``study_trial_id`` are NULL for manual proposals.
    Validates FK targets (cluster + template exist) before insert.
    """
    cluster = await repo.get_cluster(db, body.cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {body.cluster_id} not found", False)
    template = await repo.get_query_template(db, body.template_id)
    if template is None:
        raise _err(404, "TEMPLATE_NOT_FOUND", f"template {body.template_id} not found", False)

    proposal = await repo.create_proposal(
        db,
        id=str(uuid_utils.uuid7()),
        study_id=None,
        study_trial_id=None,
        cluster_id=body.cluster_id,
        template_id=body.template_id,
        config_diff=body.config_diff,
        metric_delta=body.metric_delta,
        status="pending",
    )
    await db.commit()
    return await _assemble_proposal_detail(db, proposal)


# ---------------------------------------------------------------------------
# GET /api/v1/proposals  (Story 3.3, FR-4 list)
# ---------------------------------------------------------------------------


@router.get(
    "/proposals",
    response_model=ProposalsListResponse,
    tags=["proposals"],
)
async def list_proposals_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[ProposalStatusWire | None, Query(alias="status")] = None,
    cluster_id: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> ProposalsListResponse:
    """List proposals with cursor pagination + status + cluster_id filters."""
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    rows = list(
        await repo.list_proposals_paginated(
            db,
            cursor=decoded_cursor,
            limit=limit + 1,
            status=status_filter,
            cluster_id=cluster_id,
        )
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    total = await repo.count_proposals(db, status=status_filter, cluster_id=cluster_id)
    response.headers["X-Total-Count"] = str(total)
    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    summaries = await _assemble_proposal_summary_batch(db, rows)
    return ProposalsListResponse(data=summaries, next_cursor=next_cursor, has_more=has_more)


# ---------------------------------------------------------------------------
# GET /api/v1/proposals/{id}  (Story 3.3, FR-4 detail)
# ---------------------------------------------------------------------------


@router.get(
    "/proposals/{proposal_id}",
    response_model=ProposalDetail,
    tags=["proposals"],
)
async def get_proposal_endpoint(
    proposal_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProposalDetail:
    proposal = await repo.get_proposal(db, proposal_id)
    if proposal is None:
        raise _err(404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} not found", False)
    return await _assemble_proposal_detail(db, proposal)


# ---------------------------------------------------------------------------
# POST /api/v1/proposals/{id}/reject  (Story 3.4, FR-4 / AC-5)
# ---------------------------------------------------------------------------


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalDetail,
    tags=["proposals"],
)
async def reject_proposal_endpoint(
    proposal_id: str,
    body: RejectProposalRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProposalDetail:
    """AC-5: ``pending → rejected`` transition; 409 INVALID_STATE_TRANSITION otherwise."""
    proposal = await repo.get_proposal(db, proposal_id)
    if proposal is None:
        raise _err(404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} not found", False)
    try:
        await repo.reject_proposal(db, proposal_id, reason=body.reason)
    except InvalidStateTransition as exc:
        raise _err(
            409,
            "INVALID_STATE_TRANSITION",
            f"proposal {proposal_id} is in status {exc.current_status!r}; "
            "only 'pending' proposals can be rejected",
            False,
        ) from exc
    await db.commit()
    refreshed = await repo.get_proposal(db, proposal_id)
    if refreshed is None:
        # Defensive: race with concurrent delete (out of MVP1 scope but
        # cheaper to handle than to debug a 500 in the wild).
        raise _err(
            404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} disappeared mid-update", False
        )
    return await _assemble_proposal_detail(db, refreshed)


# ---------------------------------------------------------------------------
# POST /api/v1/proposals/{id}/open_pr  (feat_github_pr_worker Story 3.1, FR-1)
# ---------------------------------------------------------------------------


def _read_auth_secret(auth_ref: str) -> str | None:
    """Read the per-repo PAT from the mounted-secrets bundle.

    Mirrors the worker's :func:`backend.workers.git_pr._read_pat`
    containment check. Returns ``None`` when the file is missing or
    empty (handler maps to ``GITHUB_NOT_CONFIGURED`` 503 per AC-2).
    """
    import os
    from pathlib import Path

    if not auth_ref:
        return None
    override = os.environ.get("RELYLOOP_SECRETS_DIR")
    secrets_root = Path(override).resolve() if override else Path("./secrets").resolve()
    candidate = (secrets_root / auth_ref).resolve()
    try:
        candidate.relative_to(secrets_root)
    except ValueError:
        return None
    # GPT-5.5 final-review F4 — require an actual file (not a directory or
    # symlink-to-directory) AND tolerate OSError on read so a malformed
    # secret path returns clean GITHUB_NOT_CONFIGURED instead of crashing.
    if not candidate.is_file():
        return None
    try:
        content = candidate.read_text().strip()
    except OSError:
        return None
    return content or None


@router.post(
    "/proposals/{proposal_id}/open_pr",
    response_model=OpenPrResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["proposals"],
)
async def open_pr_endpoint(
    proposal_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OpenPrResponse:
    """Enqueue the ``open_pr`` worker for an operator-approved proposal.

    Preflight order matches spec FR-1:

    1. Proposal exists → else 404 ``PROPOSAL_NOT_FOUND``.
    2. Proposal status is ``pending`` → else 409 ``INVALID_STATE_TRANSITION``
       (AC-6).
    3. Cluster has a ``config_repo_id`` → else 422 ``CLUSTER_HAS_NO_CONFIG_REPO``.
    4. Per-repo PAT readable from ``./secrets/{auth_ref}`` → else 503
       ``GITHUB_NOT_CONFIGURED`` (AC-2).
    5. Enqueue with deterministic ``_job_id=f"open_pr:{proposal_id}"``
       for dedup (AC-12). On enqueue failure (Arq pool absent or raise)
       return 503 ``QUEUE_UNAVAILABLE`` per cycle-2 F5 — there is NO
       boot-scan recovery for this worker, so a silent enqueue drop
       would leave the proposal pending forever with no ``pr_open_error``.
    """
    proposal = await repo.get_proposal(db, proposal_id)
    if proposal is None:
        raise _err(404, "PROPOSAL_NOT_FOUND", f"proposal {proposal_id} not found", False)
    if proposal.status != "pending":
        raise _err(
            409,
            "INVALID_STATE_TRANSITION",
            f"proposal {proposal_id} is in status {proposal.status!r}; "
            "only 'pending' proposals can have a PR opened",
            False,
        )
    cluster = await repo.get_cluster(db, proposal.cluster_id)
    if cluster is None or cluster.config_repo_id is None:
        raise _err(
            422,
            "CLUSTER_HAS_NO_CONFIG_REPO",
            f"cluster {proposal.cluster_id} has no config_repo wired in; "
            "register one via POST /api/v1/config-repos and update the cluster",
            False,
        )
    config_repo = await repo.get_config_repo(db, cluster.config_repo_id)
    if config_repo is None:
        raise _err(
            422,
            "CLUSTER_HAS_NO_CONFIG_REPO",
            f"config_repo {cluster.config_repo_id} not found",
            False,
        )
    if _read_auth_secret(config_repo.auth_ref) is None:
        raise _err(
            503,
            "GITHUB_NOT_CONFIGURED",
            f"GitHub PAT for auth_ref={config_repo.auth_ref!r} is missing or empty; "
            "populate ./secrets/<auth_ref> and retry",
            True,
        )
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise _err(
            503,
            "QUEUE_UNAVAILABLE",
            "Arq pool is not initialized; ensure the worker is running and retry",
            True,
        )
    # GPT-5.5 final-review C3-F1 — Arq's enqueue_job is idempotent on
    # _job_id, AND keeps job results in Redis for ~1h after completion by
    # default. With a static `_job_id="open_pr:{proposal_id}"`, an operator
    # retry after a worker-side failure (pr_open_error populated, status
    # still 'pending') would silently no-op for the entire retention
    # window. Salt the _job_id with a hash of the prior error so each
    # retry-after-failure gets a fresh dedup key. In-flight dedup is
    # preserved (no pr_open_error yet → static key), and post-success
    # retries are caught by the INVALID_STATE_TRANSITION preflight above.
    job_id = f"open_pr:{proposal_id}"
    if proposal.pr_open_error:
        suffix = hashlib.blake2b(proposal.pr_open_error.encode("utf-8"), digest_size=4).hexdigest()
        job_id = f"open_pr:{proposal_id}:retry-{suffix}"
    try:
        job = await arq_pool.enqueue_job("open_pr", proposal_id, _job_id=job_id)
    except Exception as exc:  # noqa: BLE001 — single-purpose: surface as 503
        logger.warning(
            "POST /proposals/{id}/open_pr: arq enqueue raised; returning 503",
            proposal_id=proposal_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise _err(
            503,
            "QUEUE_UNAVAILABLE",
            f"Arq enqueue failed: {type(exc).__name__}; retry after the worker recovers",
            True,
        ) from exc
    if job is None:
        # Defense-in-depth — Arq dedup'd against an in-flight job with the
        # same key. Surface this so an operator who hits "Open PR" twice
        # in 100ms knows the second click was deduped, not lost.
        logger.info(
            "POST /proposals/{id}/open_pr: arq dedup'd against in-flight job",
            proposal_id=proposal_id,
            job_id=job_id,
        )
    return OpenPrResponse(
        proposal_id=proposal_id,
        status="pending",
        message="PR creation queued",
    )


__all__ = ["router"]
