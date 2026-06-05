# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the FTS relevance-rank ordering helpers (feat_fts_rank_ordering).

The load-bearing test here is the **keyset oracle** (``TestRankKeysetExactness``):
it verifies — without a database — that the ``(rank_bucket DESC, id DESC)``
keyset predicate the rank path builds selects *exactly* the rows after a given
cursor, with no skip and no duplicate, across rank ties and bucket boundaries.
The DB-backed integration matrix (``test_fts_rank_endpoints.py``) confirms the
SQL translation; this oracle confirms the math.
"""

from __future__ import annotations

from backend.app.db.repo._fts import (
    RANK_BUCKET_SCALE,
    rank_active,
    rank_bucket_expr,
)
from backend.app.db.repo._sort import (
    ParsedSort,
    decode_cursor,
    encode_cursor,
)


class TestRankActive:
    def test_active_when_q_present_and_no_sort(self) -> None:
        assert rank_active("hello", None) is True

    def test_inactive_when_q_empty(self) -> None:
        assert rank_active(None, None) is False
        assert rank_active("", None) is False

    def test_inactive_when_explicit_sort_present(self) -> None:
        parsed = ParsedSort(column=object(), desc=True, col_name="name")
        assert rank_active("hello", parsed) is False


class TestRankBucketExprSql:
    def test_sql_contains_ts_rank_floor_and_plainto_tsquery(self) -> None:
        # Compile the expression to a SQL string and assert it carries the
        # load-bearing pieces (ts_rank over search_vector, the floor()*scale
        # bucketing, and the injection-safe plainto_tsquery).
        sql = str(rank_bucket_expr("phones")).lower()
        assert "ts_rank" in sql
        assert "floor" in sql
        assert "plainto_tsquery" in sql

    def test_scale_is_one_million(self) -> None:
        assert RANK_BUCKET_SCALE == 1_000_000


class TestRankCursorRoundTrip:
    def test_int_value_round_trips(self) -> None:
        # On the rank path the cursor value-half is an int rank_bucket; decode
        # with value_is_datetime=False (the router's rank-path setting).
        token = encode_cursor(123456, "row-abc")
        value, row_id = decode_cursor(token, value_is_datetime=False)
        assert value == 123456
        assert row_id == "row-abc"

    def test_zero_bucket_round_trips(self) -> None:
        token = encode_cursor(0, "row-zero")
        value, row_id = decode_cursor(token, value_is_datetime=False)
        assert value == 0
        assert row_id == "row-zero"


def _keyset_after(rows: list[tuple[int, str]], cursor: tuple[int, str]) -> list[tuple[int, str]]:
    """Python mirror of ``keyset_predicate(parsed=None, ...)`` for the rank path.

    The rank ORDER BY is ``(rank_bucket DESC, id DESC)`` and the predicate built
    by ``order_by_clauses(None, default_col=rank_col, id_col)`` /
    ``keyset_predicate(None, value, id, default_col=rank_col, id_col)`` is the
    legacy 2-column DESC keyset:

        (rank < cursor_rank) OR (rank == cursor_rank AND id < cursor_id)

    This function applies that boolean to ``rows`` so we can assert it selects
    exactly the suffix the SQL would.
    """
    c_rank, c_id = cursor
    return [(r, i) for (r, i) in rows if (r < c_rank or (r == c_rank and i < c_id))]


class TestRankKeysetExactness:
    """The keyset predicate must select EXACTLY the rows after the cursor."""

    def _sorted(self, rows: list[tuple[int, str]]) -> list[tuple[int, str]]:
        # (rank_bucket DESC, id DESC) — matches order_by_clauses(None, ...).
        return sorted(rows, key=lambda t: (t[0], t[1]), reverse=True)

    def test_no_skip_no_dupe_across_pages_with_ties_and_boundaries(self) -> None:
        # Sample rows incl. rank ties (same bucket, different id) and adjacent
        # buckets, deliberately unsorted on input.
        rows = [
            (500, "id-a"),
            (500, "id-b"),  # tie with id-a
            (500, "id-c"),  # 3-way tie
            (499, "id-d"),  # adjacent bucket
            (0, "id-e"),  # zero bucket (no match)
            (12345, "id-f"),  # top
            (12345, "id-g"),  # tie at top
        ]
        ordered = self._sorted(rows)

        # Walk the full list one page (size 2) at a time using the keyset
        # predicate; the concatenation of pages must equal the single sorted
        # list exactly — no row skipped, none duplicated.
        page_size = 2
        seen: list[tuple[int, str]] = []
        cursor: tuple[int, str] | None = None
        while True:
            if cursor is None:
                remaining = ordered
            else:
                # keyset selects the suffix; re-sort to page order.
                remaining = self._sorted(_keyset_after(rows, cursor))
            page = remaining[:page_size]
            if not page:
                break
            seen.extend(page)
            cursor = page[-1]
        assert seen == ordered
        # Every row appears exactly once.
        assert len(seen) == len(set(seen)) == len(rows)

    def test_cursor_at_a_tie_boundary_excludes_already_seen_tie_members(self) -> None:
        rows = [(500, "id-c"), (500, "id-b"), (500, "id-a")]  # all same bucket
        ordered = self._sorted(rows)  # id-c, id-b, id-a (id DESC)
        # Cursor at the first row → predicate must return id-b then id-a only.
        after = self._sorted(_keyset_after(rows, ordered[0]))
        assert after == ordered[1:]

    def test_cursor_at_bucket_edge_includes_lower_bucket(self) -> None:
        rows = [(500, "id-a"), (499, "id-z"), (499, "id-y")]
        after = self._sorted(_keyset_after(rows, (500, "id-a")))
        assert after == [(499, "id-z"), (499, "id-y")]
