"""search_vector_conversations.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-16 00:00:05.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``conversations`` derived from ``title`` (which is
nullable, so ``coalesce(title, '')`` is used), plus a GIN index
``conversations_search_vector_idx`` on it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``conversations``."""
    op.execute(
        """
        ALTER TABLE conversations
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, ''))) STORED
        """
    )
    op.execute(
        "CREATE INDEX conversations_search_vector_idx ON conversations USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column."""
    op.execute("DROP INDEX IF EXISTS conversations_search_vector_idx")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS search_vector")
