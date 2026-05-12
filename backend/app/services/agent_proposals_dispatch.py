"""Service-layer dispatch for ``open_pr`` (feat_chat_agent Story 2.4).

Lifts the ``open_pr`` preflight + Arq enqueue from
:mod:`backend.app.api.v1.proposals` so both the
``POST /api/v1/proposals/{id}/open_pr`` router AND the chat-agent ``open_pr``
tool reuse the exact same checks. Wire behavior is unchanged: same error codes
(PROPOSAL_NOT_FOUND / INVALID_STATE_TRANSITION / CLUSTER_HAS_NO_CONFIG_REPO /
GITHUB_NOT_CONFIGURED / QUEUE_UNAVAILABLE), same status codes (404 / 409 / 422
/ 503), same OpenPrResponse return shape.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from arq.connections import ArqRedis
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.db import repo

logger = get_logger(__name__)


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def read_auth_secret(auth_ref: str) -> str | None:
    """Read the per-repo PAT from the mounted-secrets bundle.

    Mirrors the original :func:`_read_auth_secret` from the proposals router
    (and the worker's :func:`backend.workers.git_pr._read_pat` containment
    check). Returns ``None`` when the file is missing or empty (caller maps
    to ``GITHUB_NOT_CONFIGURED`` 503 per AC-2).
    """
    if not auth_ref:
        return None
    override = os.environ.get("RELYLOOP_SECRETS_DIR")
    secrets_root = Path(override).resolve() if override else Path("./secrets").resolve()
    candidate = (secrets_root / auth_ref).resolve()
    try:
        candidate.relative_to(secrets_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        content = candidate.read_text().strip()
    except OSError:
        return None
    return content or None


@dataclass(frozen=True, slots=True)
class OpenPrResult:
    """Return value from ``open_pr``."""

    proposal_id: str
    status: Literal["pending"]
    message: str


async def open_pr(
    *,
    db: AsyncSession,
    arq_pool: ArqRedis | None,
    proposal_id: str,
) -> OpenPrResult:
    """Run the open_pr preflight + enqueue the worker. Returns the wire response shape.

    Preflight order (matches spec FR-1 from feat_github_pr_worker):

    1. Proposal exists → else 404 ``PROPOSAL_NOT_FOUND``.
    2. Proposal status is ``pending`` → else 409 ``INVALID_STATE_TRANSITION``.
    3. Cluster has a ``config_repo_id`` + the row resolves → else 422
       ``CLUSTER_HAS_NO_CONFIG_REPO``.
    4. Per-repo PAT readable from ``./secrets/{auth_ref}`` → else 503
       ``GITHUB_NOT_CONFIGURED``.
    5. Arq pool present → else 503 ``QUEUE_UNAVAILABLE``.
    6. Enqueue with deterministic ``_job_id="open_pr:{proposal_id}"`` (salted
       with a 4-byte hash of any prior ``pr_open_error`` so a retry-after-
       failure isn't silently de-duped against the prior key for ~1h).
    7. ``enqueue_job`` raise → 503 ``QUEUE_UNAVAILABLE`` (no boot-scan
       recovery for this worker — must surface).
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
    if read_auth_secret(config_repo.auth_ref) is None:
        raise _err(
            503,
            "GITHUB_NOT_CONFIGURED",
            f"GitHub PAT for auth_ref={config_repo.auth_ref!r} is missing or empty; "
            "populate ./secrets/<auth_ref> and retry",
            True,
        )
    if arq_pool is None:
        raise _err(
            503,
            "QUEUE_UNAVAILABLE",
            "Arq pool is not initialized; ensure the worker is running and retry",
            True,
        )
    # Salt the _job_id with a hash of any prior error so each retry-after-
    # failure gets a fresh dedup key (per GPT-5.5 final-review C3-F1 in the
    # original router implementation).
    job_id = f"open_pr:{proposal_id}"
    if proposal.pr_open_error:
        suffix = hashlib.blake2b(proposal.pr_open_error.encode("utf-8"), digest_size=4).hexdigest()
        job_id = f"open_pr:{proposal_id}:retry-{suffix}"
    try:
        job = await arq_pool.enqueue_job("open_pr", proposal_id, _job_id=job_id)
    except Exception as exc:  # noqa: BLE001 — single-purpose: surface as 503
        logger.warning(
            "open_pr: arq enqueue raised; returning 503",
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
        logger.info(
            "open_pr: arq dedup'd against in-flight job",
            proposal_id=proposal_id,
            job_id=job_id,
        )
    return OpenPrResult(
        proposal_id=proposal_id,
        status="pending",
        message="PR creation queued",
    )
