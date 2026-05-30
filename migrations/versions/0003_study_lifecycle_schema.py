# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""study_lifecycle_schema.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-10 12:00:00.000000

feat_study_lifecycle Phase 1 Story 1.2. Creates the 7-table schema
substrate that every downstream feature consumes (per
``docs/01_architecture/data-model.md``):

* ``query_templates`` — Jinja query templates with versioning + fork lineage.
* ``query_sets`` — named query collections (cluster-scoped).
* ``queries`` — the queries within a set (CASCADE on set delete).
* ``judgment_lists`` — full MVP1 shape so ``feat_llm_judgments`` can
  author rows without further migration.
* ``studies`` — full MVP1 shape (5-state status + denormalized best fields).
* ``trials`` — append-only; CASCADE on study delete; index on
  ``(study_id, primary_metric DESC NULLS LAST)`` for fast top-trial sort.
* ``proposals`` — full MVP1 shape so ``feat_digest_proposal`` /
  ``feat_github_pr_worker`` / ``feat_github_webhook`` can read/write
  without further migration.

Tables created in FK-respecting order (parents before children).
``downgrade()`` drops in reverse so FKs unwind cleanly.

Per CLAUDE.md Absolute Rule #5, this migration includes a `downgrade()`
implementation and round-trips cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the 7 study-lifecycle tables in FK-respecting order."""
    # 1) query_templates — only outgoing FK is the self-FK on parent_id.
    op.create_table(
        "query_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("engine_type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("declared_params", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("query_templates.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "version", name="query_templates_name_version_key"),
    )

    # 2) query_sets — FK to clusters (created in 0002).
    op.create_table(
        "query_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "cluster_id",
            sa.String(36),
            sa.ForeignKey("clusters.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 3) queries — CASCADE on parent query_set delete.
    op.create_table(
        "queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "query_set_id",
            sa.String(36),
            sa.ForeignKey("query_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
    )

    # 4) judgment_lists — FK to query_sets, clusters, query_templates.
    op.create_table(
        "judgment_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "query_set_id",
            sa.String(36),
            sa.ForeignKey("query_sets.id"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.String(36),
            sa.ForeignKey("clusters.id"),
            nullable=False,
        ),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column(
            "current_template_id",
            sa.String(36),
            sa.ForeignKey("query_templates.id"),
            nullable=True,
        ),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("calibration", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'complete', 'failed')",
            name="judgment_lists_status_check",
        ),
    )

    # 5) studies — FKs to clusters, query_templates, query_sets, judgment_lists,
    #    self-FK on parent_study_id.
    op.create_table(
        "studies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "cluster_id",
            sa.String(36),
            sa.ForeignKey("clusters.id"),
            nullable=False,
        ),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("query_templates.id"),
            nullable=False,
        ),
        sa.Column(
            "query_set_id",
            sa.String(36),
            sa.ForeignKey("query_sets.id"),
            nullable=False,
        ),
        sa.Column(
            "judgment_list_id",
            sa.String(36),
            sa.ForeignKey("judgment_lists.id"),
            nullable=False,
        ),
        sa.Column("search_space", JSONB(), nullable=False),
        sa.Column("objective", JSONB(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("optuna_study_name", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "parent_study_id",
            sa.String(36),
            sa.ForeignKey("studies.id"),
            nullable=True,
        ),
        sa.Column("baseline_metric", sa.Float(), nullable=True),
        sa.Column("best_metric", sa.Float(), nullable=True),
        sa.Column("best_trial_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'failed')",
            name="studies_status_check",
        ),
    )

    # 6) trials — CASCADE on parent study delete; specialized index on
    #    (study_id, primary_metric DESC NULLS LAST) for fast top-trial sort.
    op.create_table(
        "trials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "study_id",
            sa.String(36),
            sa.ForeignKey("studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("optuna_trial_number", sa.Integer(), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("primary_metric", sa.Float(), nullable=True),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('complete', 'failed', 'pruned')",
            name="trials_status_check",
        ),
    )
    # Specialized index — DESC NULLS LAST won't autogenerate from ORM-only
    # declarations, so it's created explicitly here.
    op.execute(
        "CREATE INDEX trials_study_metric ON trials (study_id, primary_metric DESC NULLS LAST)"
    )

    # 7) proposals — FKs to studies (nullable for hand-crafted), trials
    #    (nullable for hand-crafted), clusters, query_templates.
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "study_id",
            sa.String(36),
            sa.ForeignKey("studies.id"),
            nullable=True,
        ),
        sa.Column(
            "study_trial_id",
            sa.String(36),
            sa.ForeignKey("trials.id"),
            nullable=True,
        ),
        sa.Column(
            "cluster_id",
            sa.String(36),
            sa.ForeignKey("clusters.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("query_templates.id"),
            nullable=False,
        ),
        sa.Column("config_diff", JSONB(), nullable=False),
        sa.Column("metric_delta", JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("pr_state", sa.Text(), nullable=True),
        sa.Column("pr_merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pr_open_error", sa.Text(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')",
            name="proposals_status_check",
        ),
        sa.CheckConstraint(
            "pr_state IS NULL OR pr_state IN ('open', 'closed', 'merged')",
            name="proposals_pr_state_check",
        ),
    )


def downgrade() -> None:
    """Drop the 7 tables in reverse FK order so FKs unwind cleanly."""
    op.drop_table("proposals")
    op.execute("DROP INDEX IF EXISTS trials_study_metric")
    op.drop_table("trials")
    op.drop_table("studies")
    op.drop_table("judgment_lists")
    op.drop_table("queries")
    op.drop_table("query_sets")
    op.drop_table("query_templates")
