# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""proposals_pr_url_idx.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-12 12:00:00.000000

feat_github_webhook Story 1.1 — adds a partial B-tree index
``proposals_pr_url_idx`` on ``proposals(pr_url) WHERE pr_url IS NOT NULL`` to
support ``lookup_proposal_by_pr_url`` (the webhook receiver's single-row
proposal lookup keyed on the GitHub PR HTML URL).

The index is partial so only the rows with a non-null ``pr_url`` are indexed
— pre-PR-open proposals don't carry a URL yet and would just bloat the
B-tree if included.

Per CLAUDE.md Absolute Rule #5, this migration ships a ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the partial B-tree index on ``proposals.pr_url``."""
    op.create_index(
        "proposals_pr_url_idx",
        "proposals",
        ["pr_url"],
        postgresql_where=sa.text("pr_url IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the partial B-tree index."""
    op.drop_index("proposals_pr_url_idx", table_name="proposals")
