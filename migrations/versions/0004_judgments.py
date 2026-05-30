# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""judgments.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-11 12:00:00.000000

feat_llm_judgments Story 1.1 — creates the ``judgments`` child table per
``docs/01_architecture/data-model.md`` §"judgment_lists and judgments".

The parent ``judgment_lists`` table was created by
``0003_study_lifecycle_schema`` (full MVP1 shape including ``cluster_id``,
``target``, ``current_template_id``, ``status``, ``failed_reason``,
``calibration``); this migration adds ONLY the child rating rows. The
``judgments`` UNIQUE ``(judgment_list_id, query_id, doc_id)`` constraint is
the contract for human-override UPSERT semantics (FR-4 / AC-2).

Per CLAUDE.md Absolute Rule #5, this migration ships a ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401  -- not used directly; keeps import parity with 0003

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``judgments`` child table."""
    op.create_table(
        "judgments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "judgment_list_id",
            sa.String(36),
            sa.ForeignKey("judgment_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            sa.String(36),
            sa.ForeignKey("queries.id"),
            nullable=False,
        ),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("rater_ref", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "rating BETWEEN 0 AND 3",
            name="judgments_rating_check",
        ),
        sa.CheckConstraint(
            "source IN ('llm', 'human', 'click')",
            name="judgments_source_check",
        ),
        sa.UniqueConstraint(
            "judgment_list_id",
            "query_id",
            "doc_id",
            name="judgments_unique_key",
        ),
    )
    # Index for the qrels_loader `SELECT ... WHERE judgment_list_id = :id`
    # workload + the per-query resume-skip count in Story 2.1.
    op.create_index(
        "judgments_list_query_idx",
        "judgments",
        ["judgment_list_id", "query_id"],
    )


def downgrade() -> None:
    """Drop the ``judgments`` table (index drops automatically with it)."""
    op.drop_index("judgments_list_query_idx", table_name="judgments")
    op.drop_table("judgments")
