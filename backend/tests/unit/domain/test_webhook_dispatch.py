# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``dispatch_event`` (feat_github_webhook Story 1.3).

Covers every branch of the FR-1 matrix plus a parametrised negative
assertion that the dispatcher NEVER emits ``action="unknown_pr"`` — that
string is router-owned (set after a proposal-lookup miss).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.domain.git import (
    HANDLED_EVENT_TYPES,
    WEBHOOK_ACTION_VALUES,
    WebhookDecision,
    dispatch_event,
)

_PR_URL = "https://github.com/octocat/hello/pull/42"


def _pr_payload(action: str, **pull_request: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"html_url": _PR_URL}
    base.update(pull_request)
    return {"action": action, "pull_request": base}


def test_ping_returns_ping_action() -> None:
    decision = dispatch_event("ping", {"zen": "Anything added dilutes everything else."})
    assert decision == WebhookDecision(
        action="ping", pr_url=None, pr_merged_at=None, mutation="none"
    )


def test_closed_and_merged_returns_merged_mutation() -> None:
    payload = _pr_payload("closed", merged=True, merged_at="2026-05-12T11:00:00Z")
    decision = dispatch_event("pull_request", payload)
    assert decision.action == "applied"
    assert decision.mutation == "merged"
    assert decision.pr_url == _PR_URL
    assert decision.pr_merged_at == datetime(2026, 5, 12, 11, 0, 0, tzinfo=UTC)


def test_closed_without_merge_returns_closed_mutation() -> None:
    """closed + merged=false: pr_state → closed but status STAYS pr_opened (§11)."""
    payload = _pr_payload("closed", merged=False)
    decision = dispatch_event("pull_request", payload)
    assert decision == WebhookDecision(
        action="applied", pr_url=_PR_URL, pr_merged_at=None, mutation="closed"
    )


def test_reopened_returns_reopened_mutation() -> None:
    payload = _pr_payload("reopened")
    decision = dispatch_event("pull_request", payload)
    assert decision == WebhookDecision(
        action="applied", pr_url=_PR_URL, pr_merged_at=None, mutation="reopened"
    )


@pytest.mark.parametrize(
    "action",
    ["opened", "edited", "synchronize", "review_requested", "assigned", "ready_for_review"],
)
def test_other_pull_request_actions_noop(action: str) -> None:
    payload = _pr_payload(action)
    decision = dispatch_event("pull_request", payload)
    assert decision.action == "noop"
    assert decision.mutation == "none"


@pytest.mark.parametrize(
    "event_type",
    ["push", "issues", "deployment_status", "workflow_run", "completely_unknown"],
)
def test_unknown_event_types_noop(event_type: str) -> None:
    decision = dispatch_event(event_type, {"action": "anything"})
    assert decision.action == "noop"
    assert decision.mutation == "none"


def test_pull_request_without_html_url_noop() -> None:
    """Malformed payload (no pull_request.html_url) is a defensive noop."""
    decision = dispatch_event(
        "pull_request", {"action": "closed", "pull_request": {"merged": True}}
    )
    assert decision == WebhookDecision(
        action="noop", pr_url=None, pr_merged_at=None, mutation="none"
    )


def test_pull_request_without_pull_request_field_noop() -> None:
    decision = dispatch_event("pull_request", {"action": "closed"})
    assert decision == WebhookDecision(
        action="noop", pr_url=None, pr_merged_at=None, mutation="none"
    )


def test_unparseable_merged_at_returns_none_timestamp() -> None:
    """Non-ISO-8601 ``merged_at`` returns the merged mutation with None timestamp."""
    payload = _pr_payload("closed", merged=True, merged_at="not-a-timestamp")
    decision = dispatch_event("pull_request", payload)
    assert decision.mutation == "merged"
    assert decision.pr_merged_at is None


def test_handled_event_types_frozenset() -> None:
    """Spec §8.4 source-of-truth tie-back."""
    assert HANDLED_EVENT_TYPES == frozenset({"ping", "pull_request"})


def test_webhook_action_values_frozenset() -> None:
    """Spec §8.4 source-of-truth tie-back."""
    assert WEBHOOK_ACTION_VALUES == frozenset({"applied", "noop", "unknown_pr", "ping"})


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("ping", {}),
        ("pull_request", _pr_payload("closed", merged=True, merged_at="2026-05-12T11:00:00Z")),
        ("pull_request", _pr_payload("closed", merged=False)),
        ("pull_request", _pr_payload("reopened")),
        ("pull_request", _pr_payload("opened")),
        ("pull_request", _pr_payload("synchronize")),
        ("push", {}),
        ("issues", {}),
    ],
)
def test_dispatcher_never_emits_unknown_pr(event_type: str, payload: dict[str, Any]) -> None:
    """Cross-model review F2: ``"unknown_pr"`` is router-owned, not dispatcher-owned.

    The static type narrows ``action`` to ``Literal["applied", "noop", "ping"]``,
    but assert at runtime too so regressions surface clearly.
    """
    decision = dispatch_event(event_type, payload)
    # Positive form — mypy narrows decision.action to the 3-element Literal,
    # which already PROVES it's never "unknown_pr". The runtime check guards
    # against future widening of the Literal.
    assert decision.action in {"applied", "noop", "ping"}
