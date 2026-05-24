"""studies_parent_proposal.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-23 00:00:00.000000

feat_digest_executable_followups Story 3.1 — adds proposal-lineage columns
to ``studies`` so a study born from "Run this followup" remembers the
proposal + followup index it came from.

Columns added:

- ``parent_proposal_id VARCHAR(36) NULL`` — FK to ``proposals.id`` (no
  ``ondelete`` clause; lineage is detached atomically by the BEFORE DELETE
  trigger below rather than cascaded).
- ``parent_proposal_followup_index INT NULL`` — 0-based index into the
  parent digest's ``suggested_followups`` array, recorded for audit only.

Schema invariants:

- Partial B-tree index on ``parent_proposal_id WHERE parent_proposal_id IS
  NOT NULL`` — the column is sparse (only set for followup-spawned studies);
  a partial index keeps the index small while still serving lineage
  lookups.
- CHECK ``studies_parent_proposal_pair_check`` — both lineage columns
  must be set together (and the index must be ≥ 0), or both must be NULL.
  Half-set rows are nonsense and are rejected at the DB layer so no
  service-layer bug can persist them.
- BEFORE DELETE trigger on ``proposals`` —
  ``fn_clear_studies_parent_proposal_on_proposal_delete()`` NULLs both
  lineage columns on every dependent ``studies`` row in the same
  transaction as the parent ``proposals`` delete. This preserves the
  invariant atomically: it is impossible to observe a half-set row even
  during concurrent deletes.

Per CLAUDE.md Absolute Rule #5, this migration ships ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TRIGGER_FN_SQL = """
CREATE OR REPLACE FUNCTION fn_clear_studies_parent_proposal_on_proposal_delete()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE studies
    SET parent_proposal_id = NULL,
        parent_proposal_followup_index = NULL
    WHERE parent_proposal_id = OLD.id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER_SQL = """
CREATE TRIGGER trg_clear_studies_parent_proposal_on_proposal_delete
BEFORE DELETE ON proposals
FOR EACH ROW
EXECUTE FUNCTION fn_clear_studies_parent_proposal_on_proposal_delete();
"""


def upgrade() -> None:
    """Add the lineage columns, partial index, CHECK constraint, and trigger."""
    op.add_column(
        "studies",
        sa.Column(
            "parent_proposal_id",
            sa.String(36),
            sa.ForeignKey("proposals.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "studies",
        sa.Column("parent_proposal_followup_index", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_studies_parent_proposal_id",
        "studies",
        ["parent_proposal_id"],
        postgresql_where=sa.text("parent_proposal_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "studies_parent_proposal_pair_check",
        "studies",
        (
            "(parent_proposal_id IS NULL AND parent_proposal_followup_index IS NULL) "
            "OR (parent_proposal_id IS NOT NULL "
            "AND parent_proposal_followup_index IS NOT NULL "
            "AND parent_proposal_followup_index >= 0)"
        ),
    )
    op.execute(sa.text(_TRIGGER_FN_SQL))
    op.execute(sa.text(_TRIGGER_SQL))


def downgrade() -> None:
    """Drop the trigger, function, CHECK, index, and columns in inverse order."""
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS "
            "trg_clear_studies_parent_proposal_on_proposal_delete ON proposals;"
        )
    )
    op.execute(
        sa.text(
            "DROP FUNCTION IF EXISTS "
            "fn_clear_studies_parent_proposal_on_proposal_delete();"
        )
    )
    op.drop_constraint("studies_parent_proposal_pair_check", "studies", type_="check")
    op.drop_index("ix_studies_parent_proposal_id", table_name="studies")
    op.drop_column("studies", "parent_proposal_followup_index")
    op.drop_column("studies", "parent_proposal_id")
