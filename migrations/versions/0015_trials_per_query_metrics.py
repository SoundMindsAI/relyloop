"""trials_per_query_metrics.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-21 00:00:00.000000

feat_pr_metric_confidence Story 1.1 — adds a nullable ``per_query_metrics JSONB``
column to ``trials`` plus a CHECK constraint enforcing the column is NULL or a
JSON object (not an array, scalar, or boolean). The run_trial worker writes
``scored["per_query"]`` (from ``backend/app/eval/scoring.py:194``) on the
success branch; failed/pruned trials leave the column NULL. Old trials predating
this migration stay NULL (no backfill — confidence analytics degrade gracefully
per spec FR-7).

Shape: ``{query_id: {metric_name: float}}`` matching ``ScoreResult.per_query``
keys (``ndcg``, ``map``, ``precision``, ``recall``, ``mrr`` — user-facing names,
NOT the pytrec_eval wire forms).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable ``per_query_metrics`` JSONB column + CHECK constraint."""
    op.add_column(
        "trials",
        sa.Column("per_query_metrics", JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "trials_per_query_metrics_object_check",
        "trials",
        "per_query_metrics IS NULL OR jsonb_typeof(per_query_metrics) = 'object'",
    )


def downgrade() -> None:
    """Drop the CHECK constraint and the column (in that order — constraint
    references the column)."""
    op.drop_constraint(
        "trials_per_query_metrics_object_check",
        "trials",
        type_="check",
    )
    op.drop_column("trials", "per_query_metrics")
