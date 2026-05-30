# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""clusters_config_repos.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09 16:00:00.000000

infra_adapter_elastic Story 1.3. Creates the first business tables (per
``docs/01_architecture/data-model.md``):

* ``config_repos`` — Git repo registry (created first; ``clusters`` FKs to it).
* ``clusters`` — Elasticsearch / OpenSearch cluster registry.

CHECK constraints enforce the four enumerated string columns: ``provider``,
``engine_type``, ``environment``, ``auth_kind``. ``downgrade()`` reverses by
dropping ``clusters`` first (FK direction) then ``config_repos``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create config_repos, then clusters with FK + CHECKs."""
    op.create_table(
        "config_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("repo_url", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=False, server_default="main"),
        sa.Column("pr_base_branch", sa.String(), nullable=False, server_default="main"),
        sa.Column("auth_ref", sa.String(), nullable=False),
        sa.Column("webhook_secret_ref", sa.String(), nullable=True),
        sa.Column("webhook_registration_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("provider IN ('github')", name="config_repos_provider_check"),
    )
    op.create_table(
        "clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("engine_type", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("auth_kind", sa.String(), nullable=False),
        sa.Column("credentials_ref", sa.String(), nullable=False),
        sa.Column(
            "config_repo_id",
            sa.String(36),
            sa.ForeignKey("config_repos.id"),
            nullable=True,
        ),
        sa.Column("config_path", sa.String(), nullable=True),
        sa.Column("engine_config", JSONB(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "engine_type IN ('elasticsearch', 'opensearch')",
            name="clusters_engine_type_check",
        ),
        sa.CheckConstraint(
            "environment IN ('prod', 'staging', 'dev')",
            name="clusters_environment_check",
        ),
        sa.CheckConstraint(
            "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')",
            name="clusters_auth_kind_check",
        ),
    )


def downgrade() -> None:
    """Drop clusters first (it FKs to config_repos), then config_repos."""
    op.drop_table("clusters")
    op.drop_table("config_repos")
