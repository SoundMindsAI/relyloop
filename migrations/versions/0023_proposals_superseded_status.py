# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""proposals_superseded_status.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-05 00:00:00.000000

feat_overnight_final_solution_phase3 Story 1.1 / FR-1 — extends the
``proposals_status_check`` CHECK constraint to admit ``'superseded'``
as the system-initiated non-winning-chain-link status.

This is a pure relaxation (new value admitted; existing rows unaffected),
so upgrade needs no backfill. Per CLAUDE.md Absolute Rule #5 this ships a
reversible ``downgrade()`` that round-trips cleanly. The downgrade
hard-guards against existing ``'superseded'`` rows: restoring the narrower
CHECK while such a row exists would fail with a confusing constraint
violation, so we abort with a clear operator message instead (spec D-3 /
Q4 locked option (a) — refuse, not destructive DELETE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("proposals_status_check", "proposals", type_="check")
    op.create_check_constraint(
        "proposals_status_check",
        "proposals",
        "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')",
    )


def downgrade() -> None:
    # Hard-guard (spec D-3 / Q4 locked): refuse if any ``superseded`` rows
    # exist so the operator gets a clear message instead of a constraint
    # violation. Operator must manually decide each row (typically:
    # ``UPDATE proposals SET status='rejected' WHERE status='superseded';``)
    # before re-running the downgrade.
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT COUNT(*) FROM proposals WHERE status = 'superseded'")
    ).scalar_one()
    if count:
        # S608: the f-string is a HUMAN-READABLE error message naming the
        # recommended manual recovery UPDATE; it's not executed as SQL.
        manual_fix = (
            "UPDATE proposals SET status='rejected' "  # noqa: S608
            "WHERE status='superseded';"
        )
        raise RuntimeError(
            f"Cannot downgrade {revision}: {count} proposal row(s) with "
            f"status='superseded' exist. Update them to 'rejected' first: "
            f"{manual_fix}"
        )

    op.drop_constraint("proposals_status_check", "proposals", type_="check")
    op.create_check_constraint(
        "proposals_status_check",
        "proposals",
        "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')",
    )
