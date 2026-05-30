# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""digests_suggested_followups_jsonb.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-23 00:00:00.000000

feat_digest_executable_followups Story 3.3 — changes
``digests.suggested_followups`` from ``ARRAY(Text)`` to ``JSONB`` so the
column can carry the discriminated-union ``FollowupItem`` shape
(``{kind, rationale, search_space}`` per
``backend.app.domain.study.followups``).

PL/pgSQL helper-function pattern (locked design):

Postgres rejects subqueries inside ``ALTER COLUMN TYPE ... USING`` — so
the migration creates a transient PL/pgSQL helper function, runs ALTER
TABLE referencing the helper, then drops the helper. The upgrade helper
wraps every text-array element ``r`` as
``{"kind": "text", "rationale": r, "search_space": null}``; the downgrade
helper unwraps every JSONB element back to the rationale string (lossy
— ``narrow`` / ``widen`` lineage collapses to its rationale text).

Round-trip with both populated and empty rows:

- An ``ARRAY['try widen title_boost', 'add tie_breaker']`` row becomes
  ``[{"kind": "text", "rationale": "try widen title_boost",
       "search_space": null},
      {"kind": "text", "rationale": "add tie_breaker",
       "search_space": null}]``.
- An ``ARRAY[]::TEXT[]`` row becomes ``[]::jsonb``.
- Downgrade restores the rationale-only text arrays.

Per CLAUDE.md Absolute Rule #5, ships ``downgrade()`` and round-trips
cleanly. The downgrade is lossy by spec — structured ``narrow`` / ``widen``
items collapse to their ``rationale`` strings. This is acceptable because
the column type change is itself the one-way doorway: production has no
``narrow`` / ``widen`` data yet at the moment 0019 ships.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# PL/pgSQL helper: wrap a text[] into a JSONB array of {kind, rationale,
# search_space} text-followup objects. Used by upgrade()'s
# ``ALTER COLUMN TYPE ... USING helper(...)`` clause.
_UPGRADE_HELPER_FN = """
CREATE OR REPLACE FUNCTION _fn_wrap_text_array_as_jsonb_followups(arr text[])
RETURNS jsonb AS $$
DECLARE
    result jsonb := '[]'::jsonb;
    elem text;
BEGIN
    IF arr IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;
    FOREACH elem IN ARRAY arr LOOP
        result := result || jsonb_build_array(
            jsonb_build_object(
                'kind', 'text',
                'rationale', elem,
                'search_space', NULL
            )
        );
    END LOOP;
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""

_DROP_UPGRADE_HELPER_FN = (
    "DROP FUNCTION IF EXISTS _fn_wrap_text_array_as_jsonb_followups(text[]);"
)

# PL/pgSQL helper: unwrap a JSONB array of followup objects back to a
# text[] of rationale strings (LOSSY — drops kind + search_space).
_DOWNGRADE_HELPER_FN = """
CREATE OR REPLACE FUNCTION _fn_unwrap_jsonb_followups_as_text_array(j jsonb)
RETURNS text[] AS $$
DECLARE
    result text[] := ARRAY[]::text[];
    elem jsonb;
BEGIN
    IF j IS NULL OR jsonb_typeof(j) <> 'array' THEN
        RETURN ARRAY[]::text[];
    END IF;
    FOR elem IN SELECT * FROM jsonb_array_elements(j) LOOP
        result := array_append(
            result,
            COALESCE(elem->>'rationale', '')
        );
    END LOOP;
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""

_DROP_DOWNGRADE_HELPER_FN = (
    "DROP FUNCTION IF EXISTS _fn_unwrap_jsonb_followups_as_text_array(jsonb);"
)


def upgrade() -> None:
    """Change suggested_followups from text[] to jsonb via PL/pgSQL helper."""
    op.execute(sa.text(_UPGRADE_HELPER_FN))
    op.execute(sa.text("ALTER TABLE digests ALTER COLUMN suggested_followups DROP DEFAULT;"))
    op.execute(
        sa.text(
            "ALTER TABLE digests "
            "ALTER COLUMN suggested_followups TYPE jsonb "
            "USING _fn_wrap_text_array_as_jsonb_followups(suggested_followups);"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE digests "
            "ALTER COLUMN suggested_followups SET DEFAULT '[]'::jsonb;"
        )
    )
    op.execute(sa.text(_DROP_UPGRADE_HELPER_FN))


def downgrade() -> None:
    """Revert suggested_followups from jsonb to text[] (LOSSY — collapses to rationale)."""
    op.execute(sa.text(_DOWNGRADE_HELPER_FN))
    op.execute(sa.text("ALTER TABLE digests ALTER COLUMN suggested_followups DROP DEFAULT;"))
    op.execute(
        sa.text(
            "ALTER TABLE digests "
            "ALTER COLUMN suggested_followups TYPE text[] "
            "USING _fn_unwrap_jsonb_followups_as_text_array(suggested_followups);"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE digests "
            "ALTER COLUMN suggested_followups SET DEFAULT ARRAY[]::text[];"
        )
    )
    op.execute(sa.text(_DROP_DOWNGRADE_HELPER_FN))
