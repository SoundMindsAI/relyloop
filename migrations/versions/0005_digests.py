"""digests.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-11 18:00:00.000000

feat_digest_proposal Story 1.1 — creates the ``digests`` table per
``docs/01_architecture/data-model.md`` §"digests, proposals".

The ``proposals`` table is owned by ``feat_study_lifecycle`` Phase 1 and
already exists at full MVP1 shape; this migration adds only the ``digests``
child of ``studies`` (one digest per study, enforced by ``study_id UNIQUE``).

The ``suggested_followups`` column is NOT NULL with an empty-array default
per cycle-1 F1 of the GPT-5.5 review — avoids ``Optional[list[str]]`` leaking
into every API consumer when the worker writes an empty list (FR-5 + AC-2
zero-trials path explicitly write ``[]``).

Per CLAUDE.md Absolute Rule #5, this migration ships a ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``digests`` table."""
    op.create_table(
        "digests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "study_id",
            sa.String(36),
            sa.ForeignKey("studies.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("parameter_importance", postgresql.JSONB(), nullable=False),
        sa.Column("recommended_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "suggested_followups",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::TEXT[]"),
        ),
        sa.Column("generated_by", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Drop the ``digests`` table."""
    op.drop_table("digests")
