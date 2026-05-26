"""Static guard for `scripts/seed_meaningful_demos._COUNT_LIVE_CLUSTERS_SQL`.

Pins the SQL contract so a future edit can't silently re-introduce the
`bug_seed_demo_if_empty_counts_soft_deleted` regression: the
`--if-empty` auto-seed gate must count only LIVE clusters
(`WHERE deleted_at IS NULL`), otherwise a single E2E test that
soft-deletes its cluster fixtures permanently false-skips the
auto-seed on every subsequent `make up`.

Companion integration test at
`backend/tests/integration/test_seed_meaningful_demos_if_empty.py`
exercises the same SQL end-to-end against a real Postgres with a
known soft-deleted row.
"""

from __future__ import annotations

from scripts.seed_meaningful_demos import _COUNT_LIVE_CLUSTERS_SQL


def test_count_live_clusters_sql_filters_soft_deleted() -> None:
    """The SQL must include `WHERE deleted_at IS NULL`.

    Whitespace-normalized substring check so trivial reformatting
    (extra spaces, line breaks) doesn't false-trigger.
    """
    normalized = _COUNT_LIVE_CLUSTERS_SQL.upper().replace(" ", "").replace("\n", "")
    assert "WHEREDELETED_ATISNULL" in normalized, (
        f"_COUNT_LIVE_CLUSTERS_SQL must include `WHERE deleted_at IS NULL` "
        f"so soft-deleted clusters don't false-trigger the --if-empty skip. "
        f"See bug_seed_demo_if_empty_counts_soft_deleted/bug_fix.md. "
        f"Current value: {_COUNT_LIVE_CLUSTERS_SQL!r}"
    )


def test_count_live_clusters_sql_targets_clusters_table() -> None:
    """The SQL must select from `clusters` (not a typo or wrong table)."""
    normalized = _COUNT_LIVE_CLUSTERS_SQL.upper().replace(" ", "")
    assert "FROMCLUSTERS" in normalized, (
        f"_COUNT_LIVE_CLUSTERS_SQL must read FROM the `clusters` table. "
        f"Current value: {_COUNT_LIVE_CLUSTERS_SQL!r}"
    )
