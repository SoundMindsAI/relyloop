"""studies_baseline_trial.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-25 00:00:00.000000

feat_study_baseline_trial Story 1.1 / FR-1 — adds the two columns + one
partial unique index that activate the deferred-Phase-2 baseline-trial
work from feat_pr_metric_confidence:

- ``studies.baseline_trial_id String(36) NULL`` — denormalized FK to the
  baseline ``trials`` row (not a formal FK; same pattern as
  ``best_trial_id``).
- ``trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE`` — marker for the
  off-band non-Optuna baseline trial.
- ``uq_trials_study_baseline_complete`` — partial unique index on
  ``trials (study_id) WHERE is_baseline = TRUE AND status = 'complete'``
  enforcing at-most-one-complete-baseline-per-study at the DB level
  (defense against orchestrator double-enqueue on resume; one of the
  three layers in feat_study_baseline_trial decision-log D-16).

Per CLAUDE.md Absolute Rule #5, ships ``downgrade()`` and round-trips
cleanly. Both upgrade and downgrade are idempotent via ``IF [NOT] EXISTS``
guards so re-running the migration is a no-op (no manual cleanup
required).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. studies.baseline_trial_id String(36) NULL — idempotent.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'studies' AND column_name = 'baseline_trial_id'
            ) THEN
                ALTER TABLE studies ADD COLUMN baseline_trial_id VARCHAR(36);
            END IF;
        END $$;
        """
    )

    # 2. trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE — idempotent.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'trials' AND column_name = 'is_baseline'
            ) THEN
                ALTER TABLE trials ADD COLUMN is_baseline BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END $$;
        """
    )

    # 3. Partial unique index — at most one COMPLETE baseline per study.
    # CREATE INDEX IF NOT EXISTS makes this naturally idempotent.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_trials_study_baseline_complete
        ON trials (study_id)
        WHERE is_baseline = TRUE AND status = 'complete';
        """
    )


def downgrade() -> None:
    # Reverse order: index first, then trials column, then studies column.
    op.execute("DROP INDEX IF EXISTS uq_trials_study_baseline_complete;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'trials' AND column_name = 'is_baseline'
            ) THEN
                ALTER TABLE trials DROP COLUMN is_baseline;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'studies' AND column_name = 'baseline_trial_id'
            ) THEN
                ALTER TABLE studies DROP COLUMN baseline_trial_id;
            END IF;
        END $$;
        """
    )
