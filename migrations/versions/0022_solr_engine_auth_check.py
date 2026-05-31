# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""solr_engine_auth_check.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-30 00:00:00.000000

infra_adapter_solr Story A6 / FR-3 — extends two ``clusters`` CHECK
constraints to admit Apache Solr:

- ``clusters_engine_type_check``: ``elasticsearch | opensearch`` →
  ``+ solr``
- ``clusters_auth_kind_check``: ``es_apikey | es_basic | opensearch_basic |
  opensearch_sigv4`` → ``+ solr_basic | solr_apikey``

Both are pure relaxations (new values admitted; existing rows unaffected), so
upgrade needs no backfill. Per CLAUDE.md Absolute Rule #5 this ships a
reversible ``downgrade()`` that round-trips cleanly. The downgrade hard-guards
against existing Solr-typed rows: restoring the narrower CHECK while a
``engine_type='solr'`` (or solr auth_kind) row exists would either fail with a
confusing constraint-violation or silently orphan the row, so we abort with a
clear operator message instead.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("clusters_engine_type_check", "clusters", type_="check")
    op.create_check_constraint(
        "clusters_engine_type_check",
        "clusters",
        "engine_type IN ('elasticsearch', 'opensearch', 'solr')",
    )
    op.drop_constraint("clusters_auth_kind_check", "clusters", type_="check")
    op.create_check_constraint(
        "clusters_auth_kind_check",
        "clusters",
        "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', "
        "'opensearch_sigv4', 'solr_basic', 'solr_apikey')",
    )


def downgrade() -> None:
    # Hard-guard: abort if any Solr-typed rows exist so the operator gets a
    # clear message instead of a constraint-violation or an orphaned row.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, name FROM clusters "
            "WHERE engine_type = 'solr' "
            "   OR auth_kind IN ('solr_basic', 'solr_apikey') "
            "LIMIT 5"
        )
    ).fetchall()
    if rows:
        listed = ", ".join(f"{r.id} ({r.name})" for r in rows)
        raise RuntimeError(
            f"Cannot downgrade {revision}: {len(rows)} Solr cluster row(s) still exist: "
            f"{listed}. Delete or migrate these rows before downgrading."
        )

    op.drop_constraint("clusters_auth_kind_check", "clusters", type_="check")
    op.create_check_constraint(
        "clusters_auth_kind_check",
        "clusters",
        "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')",
    )
    op.drop_constraint("clusters_engine_type_check", "clusters", type_="check")
    op.create_check_constraint(
        "clusters_engine_type_check",
        "clusters",
        "engine_type IN ('elasticsearch', 'opensearch')",
    )
