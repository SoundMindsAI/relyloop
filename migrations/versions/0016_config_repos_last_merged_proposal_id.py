# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""config_repos_last_merged_proposal_id.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-22 00:00:00.000000

feat_config_repo_baseline_tracking Story 1.1 — adds a nullable
``last_merged_proposal_id VARCHAR(36)`` column to ``config_repos``, an
``ON DELETE SET NULL`` FK to ``proposals(id)``, and a partial B-tree
index on the new column (only NON-NULL rows are indexed).

Upgrade also backfills the column for existing rows: for each
``config_repo``, picks the most recently merged proposal (by
``pr_merged_at DESC, id DESC``) via the FK chain
``proposals → clusters → config_repos``. Proposals whose cluster has
``config_repo_id IS NULL`` are excluded. Repos with no merged
proposal stay NULL.

Per CLAUDE.md Absolute Rule #5, this migration ships ``downgrade()``
and round-trips cleanly: ``alembic upgrade head && alembic downgrade -1
&& alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column, FK, partial index, and backfill from existing data."""
    op.add_column(
        "config_repos",
        sa.Column(
            "last_merged_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "config_repos_last_merged_proposal_id_idx",
        "config_repos",
        ["last_merged_proposal_id"],
        postgresql_where=sa.text("last_merged_proposal_id IS NOT NULL"),
    )
    # Backfill — single SQL UPDATE seeds the column from existing merged
    # proposals via the proposals → clusters → config_repos FK chain.
    # `pr_merged_at IS NOT NULL` is defense-in-depth (GPT-5.5 cycle-1 F3):
    # in normal flow mark_proposal_pr_merged sets both fields atomically,
    # but the filter ensures no pre-feat_github_webhook historical row
    # with NULL timestamp slips in. The `DISTINCT ON` + `ORDER BY` picks
    # the newest-by-timestamp; the `id DESC` tie-break is a deterministic
    # one-time seed for the cosmically-unlikely simultaneous-microsecond
    # case. Runtime guard (FR-2) intentionally never overwrites on equal
    # timestamps — see spec §19 "Tie-break asymmetry" decision-log entry.
    op.execute("""
        UPDATE config_repos cr
        SET last_merged_proposal_id = sub.proposal_id
        FROM (
            SELECT DISTINCT ON (c.config_repo_id)
                c.config_repo_id, p.id AS proposal_id
            FROM proposals p
            JOIN clusters c ON c.id = p.cluster_id
            WHERE p.pr_state = 'merged'
              AND p.pr_merged_at IS NOT NULL
              AND c.config_repo_id IS NOT NULL
            ORDER BY c.config_repo_id, p.pr_merged_at DESC, p.id DESC
        ) AS sub
        WHERE cr.id = sub.config_repo_id;
    """)


def downgrade() -> None:
    """Drop the partial index and the column (in that order — index references the column)."""
    op.drop_index(
        "config_repos_last_merged_proposal_id_idx",
        table_name="config_repos",
    )
    op.drop_column("config_repos", "last_merged_proposal_id")
