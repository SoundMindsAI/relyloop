"""proposals_last_polled_at.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-23 00:00:00.000000

chore_reconciler_terminal_closed_no_poll Story 1.1 — adds a nullable
``last_polled_at TIMESTAMPTZ`` column to ``proposals``. No default, no
backfill, no index. The reconciler's ``stamp_proposal_last_polled_at``
helper writes the column when it observes ``(merged=false, state=closed)``
against a ``(pr_opened, closed)`` candidate (FR-2); the candidate query
``list_pr_opened_proposals_for_reconcile`` excludes rows stamped within
the last 24 hours (FR-3).

Per CLAUDE.md Absolute Rule #5, this migration ships ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable last_polled_at column."""
    op.add_column(
        "proposals",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the last_polled_at column."""
    op.drop_column("proposals", "last_polled_at")
