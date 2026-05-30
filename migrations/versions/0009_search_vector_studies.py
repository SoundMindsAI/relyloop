# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""search_vector_studies.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-16 00:00:01.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``studies`` derived from ``name + target``,
plus a GIN index ``studies_search_vector_idx`` on it.

See ``0008_search_vector_clusters.py`` for the rationale on generated columns
+ GIN indexes + why the ORM model does NOT declare this column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``studies``."""
    op.execute(
        """
        ALTER TABLE studies
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(target, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX studies_search_vector_idx ON studies USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column."""
    op.execute("DROP INDEX IF EXISTS studies_search_vector_idx")
    op.execute("ALTER TABLE studies DROP COLUMN IF EXISTS search_vector")
