# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""GitHub webhook event dispatcher (feat_github_webhook Story 1.3).

Pure-domain decision function: takes ``X-GitHub-Event`` + parsed payload,
returns a :class:`WebhookDecision` describing the mutation the router
should perform. No DB access, no I/O, no async.

Ownership note (cross-model review F2): the dispatcher NEVER returns
``action="unknown_pr"``. That string is router-owned and only emitted
when the router's ``lookup_proposal_by_pr_url`` returns ``None`` after a
``mutation``-requesting decision. The dispatcher's ``action`` Literal is
narrowed to ``{"applied", "noop", "ping"}`` so static typing enforces
the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

WEBHOOK_ACTION_VALUES: frozenset[str] = frozenset({"applied", "noop", "unknown_pr", "ping"})
"""Source-of-truth for the spec §8.4 ``action`` wire values.

Re-exported by ``backend.app.api.webhooks.github`` so spec §8.4's grep
cite at that path also passes (the router's source contains the symbol).
The full set (including the router-only ``"unknown_pr"``) lives here.
"""

HANDLED_EVENT_TYPES: frozenset[str] = frozenset({"ping", "pull_request"})
"""``X-GitHub-Event`` values the dispatcher inspects. Anything else → noop."""


@dataclass(frozen=True)
class WebhookDecision:
    """The dispatcher's verdict for a single webhook delivery.

    Attributes:
        action: Wire-level ``action`` value the router emits in the
            response body. NEVER ``"unknown_pr"`` — that's router-owned
            (set after a proposal-lookup miss).
        pr_url: The ``pull_request.html_url`` the router should look up,
            or ``None`` when no mutation is requested.
        pr_merged_at: The merge timestamp from ``pull_request.merged_at``,
            populated only when ``mutation == "merged"``.
        mutation: Which ``mark_proposal_pr_*`` call the router should
            perform. ``"none"`` means no DB work.
    """

    action: Literal["applied", "noop", "ping"]
    pr_url: str | None
    pr_merged_at: datetime | None
    mutation: Literal["merged", "closed", "reopened", "none"]


_NOOP = WebhookDecision(action="noop", pr_url=None, pr_merged_at=None, mutation="none")
_PING = WebhookDecision(action="ping", pr_url=None, pr_merged_at=None, mutation="none")


def _parse_merged_at(raw: Any) -> datetime | None:
    """Best-effort parse of GitHub's ISO-8601 ``merged_at`` timestamp."""
    if not isinstance(raw, str) or not raw:
        return None
    # GitHub emits ``2026-05-12T11:00:00Z``; Python's fromisoformat handles
    # the explicit-offset form natively, and ``Z`` needs the ``+00:00`` swap.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def dispatch_event(event_type: str, payload: dict[str, Any]) -> WebhookDecision:
    """Decide the next mutation given a verified webhook payload.

    Args:
        event_type: ``X-GitHub-Event`` header value.
        payload: Parsed JSON body.

    Returns:
        A :class:`WebhookDecision`. The router translates
        ``mutation != "none"`` + missing proposal into the wire
        ``"unknown_pr"`` action.
    """
    if event_type == "ping":
        return _PING

    if event_type != "pull_request":
        # Unknown/unhandled event types: log + noop (forward-compatible).
        return _NOOP

    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    pr_url = pull_request.get("html_url") if isinstance(pull_request, dict) else None
    if not isinstance(pr_url, str) or not pr_url:
        # PR-shaped event without a usable URL → cannot mutate.
        return _NOOP

    if action == "closed":
        if pull_request.get("merged") is True:
            merged_at = _parse_merged_at(pull_request.get("merged_at"))
            return WebhookDecision(
                action="applied",
                pr_url=pr_url,
                pr_merged_at=merged_at,
                mutation="merged",
            )
        # closed-without-merge: keep proposals.status='pr_opened' so the
        # operator can re-open_pr (spec §11 downstream-invariant audit).
        return WebhookDecision(
            action="applied",
            pr_url=pr_url,
            pr_merged_at=None,
            mutation="closed",
        )

    if action == "reopened":
        return WebhookDecision(
            action="applied",
            pr_url=pr_url,
            pr_merged_at=None,
            mutation="reopened",
        )

    # opened / edited / synchronize / review_requested / assigned / ...:
    # log + 200 with action=noop. We never want GitHub retrying these.
    return _NOOP
