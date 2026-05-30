# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""judgment_lists_generation_params.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-29 00:00:00.000000

feat_ubi_judgments Story 1.1 / FR-4 + FR-5 backing — adds one additive,
nullable JSONB column to the existing ``judgment_lists`` table so the
boot-time resume sweep can reconstruct UBI worker calls without depending
on the Arq job payload (which can be lost on broker restart or pool
restart between API and worker).

- ``judgment_lists.generation_params JSONB NULL`` — UBI lists populate
  this at INSERT with the request shape ``{generation_kind: 'ubi',
  target, since, until, converter, converter_config, llm_fill_threshold,
  min_impressions_threshold, mapping_strategy, current_template_id?,
  rubric?}``. LLM lists leave the column NULL — the existing
  ``current_template_id`` + ``rubric`` columns already carry LLM
  resume state. The ``generation_kind`` discriminator is what
  ``feat_ubi_judgments`` Story 3.3 (worker) and Story 4.3 (value-delta
  card) use to distinguish UBI/hybrid from LLM lists.

Per CLAUDE.md Absolute Rule #5, ships ``downgrade()`` and round-trips
cleanly. Both upgrade and downgrade are idempotent via ``IF [NOT] EXISTS``
guards so re-running the migration is a no-op (no manual cleanup
required). Pre-existing LLM judgment-list rows survive both directions
cleanly because the column is nullable and never read on the LLM path.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # judgment_lists.generation_params JSONB NULL — idempotent.
    # No CHECK constraint: the JSONB shape is enforced by the dispatcher
    # at INSERT time via the Pydantic CreateJudgmentListFromUbiRequest
    # schema; a CHECK on JSONB shape would duplicate that validation in
    # SQL and complicate future schema evolution (e.g., adding a new
    # converter type in v1.5+).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'judgment_lists' AND column_name = 'generation_params'
            ) THEN
                ALTER TABLE judgment_lists ADD COLUMN generation_params JSONB;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'judgment_lists' AND column_name = 'generation_params'
            ) THEN
                ALTER TABLE judgment_lists DROP COLUMN generation_params;
            END IF;
        END $$;
        """
    )
