"""baseline.

Revision ID: 0001
Revises:
Create Date: 2026-05-09 15:25:00.000000

The first migration in RelyLoop's history. Creates the ``alembic_version`` table
implicitly (Alembic auto-manages this on first ``upgrade head``); no business
tables yet — those land with their owning features per
[`docs/01_architecture/data-model.md`](../../docs/01_architecture/data-model.md):

  * ``infra_adapter_elastic`` — clusters, config_repos
  * ``feat_study_lifecycle`` (schema epic) — query_sets, query_templates,
    judgment_lists, studies, trials, proposals
  * ``feat_llm_judgments`` — judgments (child of judgment_lists)
  * ``feat_digest_proposal`` — digests (1:1 with studies)
  * ``feat_chat_agent`` — conversations, messages

This baseline migration is intentionally a no-op: ``upgrade()`` and
``downgrade()`` both pass. Subsequent feature migrations chain off this
revision (``down_revision = "0001"`` for the next migration to land).
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op baseline. alembic_version table auto-created by Alembic."""


def downgrade() -> None:
    """No-op baseline. Nothing to reverse."""
