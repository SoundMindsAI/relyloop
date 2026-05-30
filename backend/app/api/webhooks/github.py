# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""GitHub webhook receiver (feat_github_webhook Story 2.1 / FR-1).

Single endpoint ``POST /webhooks/github``. Unprefixed mount per
CLAUDE.md Rule #6 + ``docs/01_architecture/api-conventions.md``.

Order of operations (per spec FR-1):

1. Read raw body bytes (HMAC must hash the exact bytes GitHub sent).
2. Extract ``repository.full_name`` and parse to ``(owner, repo)``.
3. Look up the matching ``config_repos`` row. Unknown repo → 403
   ``INVALID_SIGNATURE`` (don't reveal repo enumeration).
4. Read the per-repo HMAC secret from the mounted-secrets bundle
   (``webhook_secret_ref``). Missing secret → 403.
5. Verify ``X-Hub-Signature-256`` via constant-time HMAC compare.
   Mismatch → 403.
6. Dispatch via the pure-domain ``dispatch_event``; the dispatcher
   returns a :class:`WebhookDecision` with ``action ∈ {applied, noop,
   ping}`` — it NEVER emits ``unknown_pr`` (router-only).
7. If the decision asks for a mutation, look up the proposal by
   ``decision.pr_url``. Missing proposal → override ``wire_action`` to
   ``unknown_pr`` and skip the mutation (spec §11 downstream-invariant
   audit). Otherwise call the matching ``mark_proposal_pr_*`` repo
   function and commit.
8. Emit one structured ``webhook_received`` log line carrying spec
   §13 NFR-Operability fields: ``delivery_id``, ``event``, ``action``,
   ``proposal_id``, ``result`` (= wire action).

The webhook secret itself is never logged. The static-grep assertion in
``backend/tests/contract/test_webhook_api_contract.py`` enforces this.

Re-exports ``WEBHOOK_ACTION_VALUES`` from
``backend.app.domain.git.webhook_dispatch`` so spec §8.4's grep cite at
this path also passes (the wire-action source of truth lives in one
module — the dispatch one — and is consumed from there).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.session import get_db
from backend.app.domain.git import (
    WEBHOOK_ACTION_VALUES,
    dispatch_event,
    parse_repository_full_name,
    verify_webhook_signature,
)
from backend.app.git import read_mounted_secret

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Re-exported so spec §8.4's grep cite at `backend/app/api/webhooks/github.py`
# also passes (the canonical wire-action source of truth lives in
# `backend.app.domain.git.webhook_dispatch`).
__all__ = ["WEBHOOK_ACTION_VALUES", "router"]


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    """Build the project-wide error envelope (mirror of every v1 router)."""
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def _invalid_signature() -> HTTPException:
    return _err(
        status.HTTP_403_FORBIDDEN,
        "INVALID_SIGNATURE",
        "Signature mismatch or unknown repository.",
        retryable=False,
    )


@router.post("/github", status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Receive a single GitHub webhook delivery.

    Returns ``{"status": "ok", "action": <wire_action>}`` where
    ``wire_action`` is one of the four values in
    :data:`WEBHOOK_ACTION_VALUES`.

    Raises:
        HTTPException(403, INVALID_SIGNATURE): bad signature or unknown
            repository. Both share one error code so the receiver does
            not reveal repo enumeration.
    """
    delivery_id = request.headers.get("x-github-delivery", "")
    event_type = request.headers.get("x-github-event", "")
    signature_header = request.headers.get("x-hub-signature-256")
    body = await request.body()

    try:
        parsed_body: Any = json.loads(body) if body else {}
    except json.JSONDecodeError:
        # Malformed JSON from a verified-signature payload is unexpected —
        # treat as a signature failure (we can't validate intent without
        # parseable fields). The HMAC compare would fail anyway because
        # the signature was computed against this same body.
        logger.warning(
            "webhook_invalid_signature",
            delivery_id=delivery_id,
            gh_event=event_type,
            reason="malformed_payload",
        )
        raise _invalid_signature() from None
    if not isinstance(parsed_body, dict):
        # GPT-5.5 final-review F2 — a valid JSON non-object (e.g. ``[]``,
        # ``"foo"``, ``null``) would crash payload.get(...) with
        # AttributeError → 500. Treat as signature failure.
        logger.warning(
            "webhook_invalid_signature",
            delivery_id=delivery_id,
            gh_event=event_type,
            reason="non_object_payload",
        )
        raise _invalid_signature()
    payload: dict[str, Any] = parsed_body

    full_name = ""
    repository = payload.get("repository")
    if isinstance(repository, dict):
        candidate = repository.get("full_name")
        if isinstance(candidate, str):
            full_name = candidate
    owner_repo = parse_repository_full_name(full_name) if full_name else None
    if owner_repo is None:
        logger.warning(
            "webhook_invalid_signature",
            delivery_id=delivery_id,
            gh_event=event_type,
            reason="unparseable_repository",
        )
        raise _invalid_signature()

    config_repo_row = await repo.lookup_config_repo_by_owner_repo(db, *owner_repo)
    if config_repo_row is None or not config_repo_row.webhook_secret_ref:
        logger.warning(
            "webhook_invalid_signature",
            delivery_id=delivery_id,
            gh_event=event_type,
            reason="unknown_repo",
        )
        raise _invalid_signature()

    secret = read_mounted_secret(config_repo_row.webhook_secret_ref)
    if not secret or not verify_webhook_signature(body, signature_header, secret):
        logger.warning(
            "webhook_invalid_signature",
            delivery_id=delivery_id,
            gh_event=event_type,
            reason="bad_signature",
        )
        raise _invalid_signature()

    decision = dispatch_event(event_type, payload)
    wire_action: str = decision.action
    proposal_id: str | None = None

    if decision.mutation != "none":
        # The dispatcher never emits unknown_pr — only the router does,
        # after the lookup miss. See spec §11 + the dispatcher's
        # `_NOOP`/`_PING` carve-out.
        assert decision.pr_url is not None  # noqa: S101 — invariant of dispatcher
        proposal_row = await repo.lookup_proposal_by_pr_url(db, decision.pr_url)
        if proposal_row is None:
            wire_action = "unknown_pr"
        else:
            proposal_id = proposal_row.id
            if decision.mutation == "merged":
                # GPT-5.5 final-review F3 — GitHub eventual-consistency
                # can yield merged=true with merged_at missing/null.
                # Fall back to closed-state mutation (PR is no longer open)
                # rather than crash the receiver; the polling reconciler
                # will catch up on the merged_at value on the next tick.
                if decision.pr_merged_at is None:
                    await repo.mark_proposal_pr_closed(db, proposal_id)
                else:
                    updated_proposal = await repo.mark_proposal_pr_merged(
                        db, proposal_id, pr_merged_at=decision.pr_merged_at
                    )
                    # feat_config_repo_baseline_tracking FR-3 — maintain
                    # config_repos.last_merged_proposal_id pointer. Only
                    # fires when this delivery actually performed the
                    # pending → pr_merged transition (mark_proposal_pr_merged
                    # returned non-None). Duplicate / out-of-order deliveries
                    # return None and skip naturally. Cluster.config_repo_id
                    # IS NULL is a silent skip (cluster has no Git repo
                    # wired).
                    if updated_proposal is not None:
                        cluster_row = await repo.get_cluster(db, updated_proposal.cluster_id)
                        if cluster_row is not None and cluster_row.config_repo_id is not None:
                            await repo.update_config_repo_last_merged_pointer(
                                db,
                                config_repo_id=cluster_row.config_repo_id,
                                proposal_id=proposal_id,
                                pr_merged_at=decision.pr_merged_at,
                            )
                        else:
                            logger.debug(
                                "config_repo_last_merged_pointer_skipped_no_repo",
                                proposal_id=proposal_id,
                                cluster_id=updated_proposal.cluster_id,
                            )
            elif decision.mutation == "closed":
                await repo.mark_proposal_pr_closed(db, proposal_id)
            elif decision.mutation == "reopened":
                await repo.mark_proposal_pr_reopened(db, proposal_id)
            await db.commit()

    logger.info(
        "webhook_received",
        delivery_id=delivery_id,
        gh_event=event_type,
        action=wire_action,
        proposal_id=proposal_id,
        result=wire_action,
    )

    return {"status": "ok", "action": wire_action}
