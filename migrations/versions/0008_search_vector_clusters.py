# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""search_vector_clusters.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-16 00:00:00.000000

feat_data_table_primitive Story 1.1 — adds a Postgres ``tsvector`` generated
column ``search_vector`` to ``clusters`` derived from ``name + base_url``,
plus a GIN index ``clusters_search_vector_idx`` on it.

The column is ``GENERATED ALWAYS AS (...) STORED`` so Postgres recomputes
it on every INSERT/UPDATE — no backfill required, no application writes.
The ORM model (``backend/app/db/models/cluster.py``) intentionally does
NOT declare this column (per spec FR-2 invariant); the FTS predicate is
constructed at the repo layer via ``sa.text("search_vector @@ ...")``.

Per CLAUDE.md Absolute Rule #5, this migration ships ``downgrade()`` and
round-trips cleanly.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated ``search_vector`` column and GIN index on ``clusters``."""
    op.execute(
        """
        ALTER TABLE clusters
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(base_url, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX clusters_search_vector_idx ON clusters USING GIN (search_vector)"
    )


def downgrade() -> None:
    """Drop the GIN index then the generated column (reverse FK-respecting order)."""
    op.execute("DROP INDEX IF EXISTS clusters_search_vector_idx")
    op.execute("ALTER TABLE clusters DROP COLUMN IF EXISTS search_vector")
