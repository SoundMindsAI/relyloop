"""Unit tests for ``backend.app.db.repo._sort``.

Covers the four pure helpers that drive sort-aware cursor pagination
across every list endpoint that accepts ``?sort=<col>:<dir>``:

- ``parse_sort`` — defense-in-depth allowlist + direction parse.
- ``order_by_clauses`` — ORDER BY shape with explicit NULLS handling.
- ``encode_cursor`` / ``decode_cursor`` — opaque base64-JSON round-trip
  with datetime ↔ ISO 8601 string awareness.
- ``cursor_value_is_datetime`` — convention check used by routers.

No DB, no FastAPI app — these are pure functions with mocked
SQLAlchemy column refs (the helpers don't introspect the columns
beyond passing them through to SQLAlchemy builders).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.app.db.repo._sort import (
    ParsedSort,
    cursor_value_is_datetime,
    decode_cursor,
    encode_cursor,
    order_by_clauses,
    parse_sort,
)

# ---------------------------------------------------------------------------
# parse_sort
# ---------------------------------------------------------------------------


def test_parse_sort_returns_none_for_none_input() -> None:
    assert parse_sort(None, {"name": object()}) is None


def test_parse_sort_returns_none_for_empty_string() -> None:
    assert parse_sort("", {"name": object()}) is None


def test_parse_sort_returns_none_for_unknown_column() -> None:
    """Defense-in-depth: Pydantic at the router boundary already rejects
    unknown col names with VALIDATION_ERROR, but the helper still
    treats an unknown name as 'no sort active' rather than blowing up."""
    sentinel = object()
    assert parse_sort("unknown_col:asc", {"name": sentinel}) is None


def test_parse_sort_with_explicit_asc_direction() -> None:
    col = object()
    parsed = parse_sort("name:asc", {"name": col})
    assert parsed is not None
    assert parsed.column is col
    assert parsed.desc is False
    assert parsed.col_name == "name"


def test_parse_sort_with_explicit_desc_direction() -> None:
    col = object()
    parsed = parse_sort("created_at:desc", {"created_at": col})
    assert parsed is not None
    assert parsed.desc is True
    assert parsed.col_name == "created_at"


def test_parse_sort_defaults_to_ascending_when_direction_missing() -> None:
    """``sort=name`` (no `:`) parses as ASC by convention — `dir_str` is
    empty, which is not equal to ``"desc"``, so ``desc=False``."""
    col = object()
    parsed = parse_sort("name", {"name": col})
    assert parsed is not None
    assert parsed.desc is False


def test_parse_sort_treats_non_desc_direction_as_ascending() -> None:
    """Any direction string other than the literal ``"desc"`` parses as
    ASC. Pydantic ``Literal["asc", "desc"]`` upstream rejects garbage
    before this helper runs — defense-in-depth means we never raise
    here, we just default."""
    col = object()
    parsed = parse_sort("name:upward", {"name": col})
    assert parsed is not None
    assert parsed.desc is False


# ---------------------------------------------------------------------------
# order_by_clauses
# ---------------------------------------------------------------------------


def _mock_col() -> MagicMock:
    """Build a mock that mirrors the SQLAlchemy InstrumentedAttribute surface
    we touch — ``.desc()``, ``.asc()``, ``.nulls_first()``, ``.nulls_last()``,
    all returning fresh mocks so the chain is observable."""
    col = MagicMock(name="col")
    col.desc.return_value = MagicMock(name="col.desc()")
    col.asc.return_value = MagicMock(name="col.asc()")
    col.desc.return_value.nulls_last.return_value = MagicMock(name="col.desc().nulls_last()")
    col.asc.return_value.nulls_first.return_value = MagicMock(name="col.asc().nulls_first()")
    return col


def test_order_by_clauses_returns_default_descending_when_unsorted() -> None:
    default_col = _mock_col()
    id_col = _mock_col()
    clauses = order_by_clauses(None, default_col, id_col)
    assert clauses == [default_col.desc.return_value, id_col.desc.return_value]


def test_order_by_clauses_with_desc_sort_uses_nulls_last() -> None:
    sort_col = _mock_col()
    id_col = _mock_col()
    parsed = ParsedSort(column=sort_col, desc=True, col_name="name")
    clauses = order_by_clauses(parsed, default_col=_mock_col(), id_col=id_col)
    # Primary clause is sort_col.desc().nulls_last(); tiebreaker is id DESC.
    assert clauses[0] is sort_col.desc.return_value.nulls_last.return_value
    assert clauses[1] is id_col.desc.return_value
    sort_col.desc.assert_called_once_with()
    sort_col.desc.return_value.nulls_last.assert_called_once_with()


def test_order_by_clauses_with_asc_sort_uses_nulls_first() -> None:
    sort_col = _mock_col()
    id_col = _mock_col()
    parsed = ParsedSort(column=sort_col, desc=False, col_name="name")
    clauses = order_by_clauses(parsed, default_col=_mock_col(), id_col=id_col)
    assert clauses[0] is sort_col.asc.return_value.nulls_first.return_value
    sort_col.asc.assert_called_once_with()
    sort_col.asc.return_value.nulls_first.assert_called_once_with()


# ---------------------------------------------------------------------------
# encode_cursor / decode_cursor
# ---------------------------------------------------------------------------


def test_cursor_round_trip_with_datetime_value() -> None:
    dt = datetime(2026, 5, 16, 12, 30, 0, tzinfo=UTC)
    row_id = "01935b9a-0000-7000-8000-000000000001"
    encoded = encode_cursor(dt, row_id)
    decoded_dt, decoded_id = decode_cursor(encoded, value_is_datetime=True)
    assert decoded_dt == dt
    assert decoded_id == row_id


def test_cursor_round_trip_with_str_value() -> None:
    name = "products-prod-es"
    row_id = "01935b9a-0000-7000-8000-000000000002"
    encoded = encode_cursor(name, row_id)
    decoded_name, decoded_id = decode_cursor(encoded, value_is_datetime=False)
    assert decoded_name == name
    assert decoded_id == row_id


def test_cursor_round_trip_with_null_value() -> None:
    row_id = "01935b9a-0000-7000-8000-000000000003"
    encoded = encode_cursor(None, row_id)
    decoded_value, decoded_id = decode_cursor(encoded, value_is_datetime=True)
    assert decoded_value is None
    assert decoded_id == row_id


def test_cursor_round_trip_with_int_value() -> None:
    encoded = encode_cursor(42, "row-id")
    decoded_value, decoded_id = decode_cursor(encoded, value_is_datetime=False)
    assert decoded_value == 42
    assert decoded_id == "row-id"


def test_decode_cursor_raises_value_error_on_malformed_input() -> None:
    with pytest.raises((ValueError, Exception)):
        decode_cursor("not-base64-or-json!", value_is_datetime=False)


# ---------------------------------------------------------------------------
# cursor_value_is_datetime
# ---------------------------------------------------------------------------


def test_cursor_value_is_datetime_returns_true_for_default_sort() -> None:
    """When parsed is None the default is ``(created_at, id)`` — datetime."""
    assert cursor_value_is_datetime(None) is True


@pytest.mark.parametrize("col_name", ["created_at", "completed_at", "ended_at"])
def test_cursor_value_is_datetime_returns_true_for_known_datetime_cols(col_name: str) -> None:
    parsed = ParsedSort(column=object(), desc=True, col_name=col_name)
    assert cursor_value_is_datetime(parsed) is True


@pytest.mark.parametrize("col_name", ["name", "status", "version", "rating", "primary_metric"])
def test_cursor_value_is_datetime_returns_false_for_non_datetime_cols(col_name: str) -> None:
    parsed = ParsedSort(column=object(), desc=False, col_name=col_name)
    assert cursor_value_is_datetime(parsed) is False


# NOTE: ``keyset_predicate`` cannot be exercised in pure unit-test form —
# its branches call ``<`` / ``==`` on SQLAlchemy column refs, which return
# SQL expression objects rather than booleans. A bare ``MagicMock`` doesn't
# overload those operators. The function is covered end-to-end by the
# per-resource sort-pagination integration tests
# (``backend/tests/integration/test_<resource>_sort_pagination.py``) which
# hit the live Postgres + SQLAlchemy stack with real column refs and
# multi-page cursor walks.
