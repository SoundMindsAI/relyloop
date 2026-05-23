"""Polling reconciler for stale ``pr_opened`` proposals (feat_github_webhook FR-2).

Runs on the cron cadence derived from ``Settings.relyloop_pr_poll_minutes``
(see :func:`_poll_cron_kwargs` in ``backend.workers.all`` for the
divisor-of-60 / multiple-of-60 routing). Each tick:

1. Selects candidate proposals via
   :func:`backend.app.db.repo.list_pr_opened_proposals_for_reconcile`
   (status=pr_opened, pr_state=open, pr_url set, created_at < 90 days).
2. For each candidate, parses ``(owner, repo, number)`` from the stored
   ``pr_url``, reads the matching ``config_repos.auth_ref`` PAT, and
   issues ``GET /repos/{owner}/{repo}/pulls/{number}``.
3. Branches on the response body — ``merged=true`` →
   :func:`mark_proposal_pr_merged`; ``state="closed"`` (unmerged) →
   :func:`mark_proposal_pr_closed`; ``state="open"`` → no-op (PR is
   genuinely still open).
4. Logs every other terminal response (404 / 401 / 403 / 5xx /
   ``httpx.RequestError`` after retry budget) at WARN and continues.
5. On HTTP 429, logs WARN with ``x-ratelimit-reset`` and **breaks the
   proposal loop** for this tick — the next tick retries (spec §10).

No in-job retry envelope — the cron tick IS the retry. Idempotent: a
no-op on a stable proposal is cheap.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx
import structlog

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.git import HTTP_TIMEOUT_S, github_request, read_mounted_secret

logger = structlog.get_logger(__name__)

_PR_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[a-zA-Z0-9._-]+)/(?P<repo>[a-zA-Z0-9._-]+)/pull/"
    r"(?P<number>\d+)$"
)


def _parse_pr_url(pr_url: str) -> tuple[str, str, int] | None:
    """Return ``(owner, repo, number)`` from a GitHub PR HTML URL, or None."""
    match = _PR_URL_PATTERN.match(pr_url)
    if match is None:
        return None
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _coerce_merged_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _list_candidates() -> Sequence[Any]:
    factory = get_session_factory()
    async with factory() as db:
        return await repo.list_pr_opened_proposals_for_reconcile(db)


async def _resolve_config_repo(owner: str, repo_name: str) -> Any | None:
    factory = get_session_factory()
    async with factory() as db:
        return await repo.lookup_config_repo_by_owner_repo(db, owner, repo_name)


async def reconcile_pr_state(ctx: dict[str, Any]) -> dict[str, int]:
    """Poll GitHub for the current state of every stale ``pr_opened`` proposal.

    Returns a summary dict ``{candidates, reconciled, unchanged, errored,
    rate_limited}`` logged at INFO for observability.
    """
    summary = {"candidates": 0, "reconciled": 0, "unchanged": 0, "errored": 0, "rate_limited": 0}

    candidates = await _list_candidates()
    summary["candidates"] = len(candidates)
    if not candidates:
        logger.info("pr_reconcile_tick_noop", **summary)
        return summary

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        for proposal in candidates:
            parsed_url = _parse_pr_url(proposal.pr_url) if proposal.pr_url else None
            if parsed_url is None:
                logger.warning(
                    "pr_reconcile_unparseable_url",
                    proposal_id=proposal.id,
                    pr_url=proposal.pr_url,
                )
                summary["errored"] += 1
                continue
            owner, repo_name, number = parsed_url

            config_repo_row = await _resolve_config_repo(owner, repo_name)
            if config_repo_row is None:
                logger.warning(
                    "pr_reconcile_no_config_repo",
                    proposal_id=proposal.id,
                    owner=owner,
                    repo=repo_name,
                )
                summary["errored"] += 1
                continue

            token = read_mounted_secret(config_repo_row.auth_ref)
            if token is None:
                logger.warning(
                    "pr_reconcile_pat_missing",
                    proposal_id=proposal.id,
                    config_repo_id=config_repo_row.id,
                )
                summary["errored"] += 1
                continue

            url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{number}"
            try:
                response = await github_request(client, "GET", url, token=token)
            except httpx.RequestError as exc:
                logger.warning(
                    "pr_reconcile_request_error",
                    proposal_id=proposal.id,
                    error_type=type(exc).__name__,
                )
                summary["errored"] += 1
                continue

            if response.status_code == 429:
                logger.warning(
                    "pr_reconcile_rate_limited",
                    proposal_id=proposal.id,
                    x_ratelimit_reset=response.headers.get("x-ratelimit-reset"),
                )
                summary["rate_limited"] += 1
                # Spec §10: skip remaining proposals; next tick retries.
                break

            if response.status_code in (401, 403, 404) or response.status_code >= 500:
                logger.warning(
                    "pr_reconcile_terminal_error",
                    proposal_id=proposal.id,
                    status_code=response.status_code,
                )
                summary["errored"] += 1
                continue

            if response.status_code != 200:
                logger.warning(
                    "pr_reconcile_unexpected_status",
                    proposal_id=proposal.id,
                    status_code=response.status_code,
                )
                summary["errored"] += 1
                continue

            payload = response.json()
            merged = bool(payload.get("merged"))
            state = payload.get("state")
            merged_at = _coerce_merged_at(payload.get("merged_at"))

            factory = get_session_factory()
            if merged and merged_at is not None:
                # bug_pr_reconciler_blocked_by_closed_fallback — branch on
                # the candidate's current pr_state. Normal candidates are
                # (pr_opened, open); fallback-closed candidates arrive in
                # (pr_opened, closed) because the webhook's merged_at=null
                # branch closed them prematurely. Both transition to
                # (pr_merged, merged) but the WHERE clauses differ.
                async with factory() as db:
                    recovery_path = proposal.pr_state == "closed"
                    if recovery_path:
                        updated = await repo.mark_proposal_pr_merged_from_closed(
                            db, proposal.id, pr_merged_at=merged_at
                        )
                        if updated is not None:
                            logger.info(
                                "pr_reconcile_recovered_eventual_consistency",
                                proposal_id=proposal.id,
                                pr_merged_at=merged_at.isoformat(),
                            )
                    else:
                        updated = await repo.mark_proposal_pr_merged(
                            db, proposal.id, pr_merged_at=merged_at
                        )
                    if updated is not None:
                        # feat_config_repo_baseline_tracking FR-3a — maintain
                        # config_repos.last_merged_proposal_id pointer when
                        # the reconciler is the first observer of the merge
                        # (e.g., the webhook was never delivered, OR the
                        # webhook's merged_at=null fallback transitioned the
                        # row before GitHub reported a timestamp). Same
                        # transaction as the proposal UPDATE.
                        cluster_row = await repo.get_cluster(db, proposal.cluster_id)
                        if cluster_row is not None and cluster_row.config_repo_id is not None:
                            await repo.update_config_repo_last_merged_pointer(
                                db,
                                config_repo_id=cluster_row.config_repo_id,
                                proposal_id=proposal.id,
                                pr_merged_at=merged_at,
                            )
                        else:
                            logger.debug(
                                "config_repo_last_merged_pointer_skipped_no_repo",
                                proposal_id=proposal.id,
                                cluster_id=proposal.cluster_id,
                            )
                    await db.commit()
                if updated is not None:
                    summary["reconciled"] += 1
                else:
                    summary["unchanged"] += 1
            elif state == "closed":
                async with factory() as db:
                    updated = await repo.mark_proposal_pr_closed(db, proposal.id)
                    await db.commit()
                if updated is not None:
                    summary["reconciled"] += 1
                else:
                    summary["unchanged"] += 1
            else:
                # state == "open" — proposal is genuinely still pending review.
                summary["unchanged"] += 1

    logger.info("pr_reconcile_tick_complete", **summary)
    return summary


# Re-exported so the validators module can dedup the supported set against
# `_poll_cron_kwargs` (both reference the same source-of-truth).
SUPPORTED_POLL_MINUTES: frozenset[int] = frozenset(
    {1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}
)
"""Whitelist of values ``RELYLOOP_PR_POLL_MINUTES`` may take.

Divisors of 60 (sub-hourly minute set) plus multiples of 60 that divide
1440 (hourly + multi-hour set). Anything else cannot be expressed as a
single ``arq.cron(minute=..., hour=...)`` invocation, so we reject at
Settings-validation time rather than silently snapping (cross-model
review F3 / A4).
"""

FALLBACK_POLL_MINUTES: int = 15
"""Default cadence operators get if validation slipped (shouldn't happen)."""


def _poll_cron_kwargs() -> dict[str, Any]:
    """Translate ``Settings.relyloop_pr_poll_minutes`` into arq.cron kwargs.

    * n ≤ 60 (divisor of 60): ``minute=set(range(0, 60, n))``.
    * n > 60 (multiple of 60 dividing 1440):
      ``hour=set(range(0, 24, n // 60)), minute={0}``.

    Unsupported values fall back to the documented default with a WARN
    log so the operator gets observable behaviour instead of silent
    breakage.
    """
    from backend.app.core.settings import get_settings

    n = get_settings().relyloop_pr_poll_minutes
    if n not in SUPPORTED_POLL_MINUTES:
        logger.warning(
            "pr_poll_minutes_unsupported",
            configured=n,
            falling_back_to=FALLBACK_POLL_MINUTES,
            supported=sorted(SUPPORTED_POLL_MINUTES),
        )
        n = FALLBACK_POLL_MINUTES
    if n <= 60:
        return {"minute": set(range(0, 60, n))}
    return {"hour": set(range(0, 24, n // 60)), "minute": {0}}
