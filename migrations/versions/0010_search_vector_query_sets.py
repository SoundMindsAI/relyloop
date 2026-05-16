"""search_vector_query_sets.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-16 00:00:02.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``query_sets`` derived from ``name``, plus a GIN
index ``query_sets_search_vector_idx`` on it.

See ``0008_search_vector_clusters.py`` for the rationale.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``query_sets``."""
    op.execute(
        """
        ALTER TABLE query_sets
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, ''))) STORED
        """
    )
    op.execute(
        "CREATE INDEX query_sets_search_vector_idx ON query_sets USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column."""
    op.execute("DROP INDEX IF EXISTS query_sets_search_vector_idx")
    op.execute("ALTER TABLE query_sets DROP COLUMN IF EXISTS search_vector")
