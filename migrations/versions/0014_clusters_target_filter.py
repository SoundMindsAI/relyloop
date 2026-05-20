"""clusters_target_filter.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-20 00:00:00.000000

feat_cluster_target_filter Story B1 — adds a nullable ``target_filter VARCHAR(256)``
column to ``clusters``. Operator-supplied glob pattern (``fnmatch.fnmatchcase`` syntax)
that scopes ``list_targets()`` to matching index/collection names. ``NULL`` = no filter
(default, backward-compatible).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``target_filter`` column to ``clusters``."""
    op.add_column(
        "clusters",
        sa.Column("target_filter", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    """Drop the ``target_filter`` column."""
    op.drop_column("clusters", "target_filter")
