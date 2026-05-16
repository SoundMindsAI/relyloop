"""search_vector_judgment_lists.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-16 00:00:04.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``judgment_lists`` derived from ``name + target``,
plus a GIN index ``judgment_lists_search_vector_idx`` on it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``judgment_lists``."""
    op.execute(
        """
        ALTER TABLE judgment_lists
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(target, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX judgment_lists_search_vector_idx ON judgment_lists USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column."""
    op.execute("DROP INDEX IF EXISTS judgment_lists_search_vector_idx")
    op.execute("ALTER TABLE judgment_lists DROP COLUMN IF EXISTS search_vector")
