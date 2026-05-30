# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""search_vector_query_templates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-16 00:00:03.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``query_templates`` derived from ``name``, plus a
GIN index ``query_templates_search_vector_idx`` on it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``query_templates``."""
    op.execute(
        """
        ALTER TABLE query_templates
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, ''))) STORED
        """
    )
    op.execute(
        "CREATE INDEX query_templates_search_vector_idx ON query_templates USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column."""
    op.execute("DROP INDEX IF EXISTS query_templates_search_vector_idx")
    op.execute("ALTER TABLE query_templates DROP COLUMN IF EXISTS search_vector")
