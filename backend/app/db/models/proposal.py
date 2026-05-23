"""``proposals`` ORM model (feat_study_lifecycle Phase 1, Story 1.1).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"proposals".

This feature creates the **full** MVP1 shape (not a stub) so downstream
features (`feat_digest_proposal` populates the row from a study's winning
trial; `feat_github_pr_worker` opens the PR and stamps `pr_url`/`pr_state`/
`pr_merged_at`/`pr_open_error`; `feat_github_webhook` updates `pr_state`
from GitHub events) can read/write without further migration.

Two CHECK constraints:
- ``status ∈ {pending, pr_opened, pr_merged, rejected}``.
- ``pr_state`` accepts NULL (pre-PR-open) or one of ``{open, closed, merged}``
  (mirrors GitHub's PR states).

Hand-crafted proposals (via `feat_chat_agent`'s tool call) leave ``study_id``
+ ``study_trial_id`` + ``metric_delta`` NULL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Proposal(Base):
    """A configuration change to be opened as a PR against the search-config repo."""

    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')",
            name="proposals_status_check",
        ),
        CheckConstraint(
            "pr_state IS NULL OR pr_state IN ('open', 'closed', 'merged')",
            name="proposals_pr_state_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("studies.id"), nullable=True
    )
    """NULL when the proposal is hand-crafted via `feat_chat_agent`."""
    study_trial_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("trials.id"), nullable=True
    )
    """The winning trial; NULL for hand-crafted proposals."""
    cluster_id: Mapped[str] = mapped_column(String(36), ForeignKey("clusters.id"), nullable=False)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_templates.id"), nullable=False
    )
    config_diff: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """``{param: {from, to}}`` — the parameter change being proposed."""
    metric_delta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """``{ndcg@10: {baseline, achieved, delta_pct}}`` — NULL for hand-crafted."""
    status: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``pending | pr_opened | pr_merged | rejected`` (CHECK enforced)."""
    pr_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    """GitHub PR URL; populated by `feat_github_pr_worker`."""
    pr_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Mirrors GitHub: ``open | closed | merged`` or NULL pre-open. Updated by
    `feat_github_webhook`."""
    pr_merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pr_open_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Populated when `feat_github_pr_worker` fails to open the PR;
    cleared on successful retry."""
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Reconciler stamp recording the last time ``reconcile_pr_state`` observed
    ``(merged=false, state=closed)`` against a ``(pr_opened, closed)`` row. Used
    by the ``list_pr_opened_proposals_for_reconcile`` 24-hour exclusion. Written
    ONLY by ``stamp_proposal_last_polled_at`` (see
    ``chore_reconciler_terminal_closed_no_poll`` FR-2)."""
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Operator-supplied reason when ``status == 'rejected'``."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
