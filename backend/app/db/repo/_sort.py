"""Sort-aware cursor pagination helpers.

Shared by every list/count repo function that accepts ``?sort=<col>:<dir>``.

Cursor leading key MUST match ORDER BY leading key for keyset pagination to
work correctly (no duplicates, no skips). When ``?sort=`` is absent or
``created_at:desc``, the cursor is ``(created_at, id)`` — the legacy shape.
For any other ``?sort=``, the cursor is ``(<sort_col_value>, id)``: the
leading key is the sort column's value at the last row of the previous
page.

Null handling follows the explicit ``NULLS FIRST`` / ``NULLS LAST`` clauses
in the ORDER BY:
- ``asc`` direction → ``NULLS FIRST`` (nulls iterated first)
- ``desc`` direction → ``NULLS LAST`` (nulls iterated last)

See spec FR-3a "Cursor-pagination correctness under ``?sort=``" + Story 1.3
notes in feat_data_table_primitive/implementation_plan.md.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_


@dataclass(frozen=True)
class ParsedSort:
    """Resolved sort specification for a single list query."""

    column: Any  # SQLAlchemy column ref (InstrumentedAttribute or ColumnElement)
    desc: bool
    col_name: str  # e.g., "name", "created_at" — the key from the allowed map


def parse_sort(s: str | None, allowed: dict[str, Any]) -> ParsedSort | None:
    """Parse ``?sort=<col>:<asc|desc>`` against an allowlist.

    ``allowed`` maps the col name to the SQLAlchemy column reference for
    that table. Returns ``None`` when ``s`` is ``None`` or empty, or when
    the col name is not in the allowlist (Pydantic ``Literal[...]``
    already rejects unknown values at the router boundary; this helper
    is a defense-in-depth check).
    """
    if not s:
        return None
    col_name, _, dir_str = s.partition(":")
    col = allowed.get(col_name)
    if col is None:
        return None
    return ParsedSort(column=col, desc=(dir_str == "desc"), col_name=col_name)


def order_by_clauses(
    parsed: ParsedSort | None,
    default_col: Any,
    id_col: Any,
) -> list[Any]:
    """Build the ORDER BY clauses for a list query.

    When ``parsed is None``, returns ``[default_col DESC, id DESC]`` —
    the legacy shape used by every list endpoint pre-Story-1.3.

    Otherwise, returns the sort column with explicit NULLS handling
    (``NULLS LAST`` on ``desc``, ``NULLS FIRST`` on ``asc``) plus the
    ``id DESC`` tie-breaker.
    """
    if parsed is None:
        return [default_col.desc(), id_col.desc()]
    primary = (
        parsed.column.desc().nulls_last() if parsed.desc else parsed.column.asc().nulls_first()
    )
    return [primary, id_col.desc()]


def keyset_predicate(
    parsed: ParsedSort | None,
    cursor_value: Any,
    cursor_id: str,
    default_col: Any,
    id_col: Any,
) -> Any:
    """Build the keyset cursor predicate matching ``order_by_clauses``.

    When ``parsed is None``, returns the legacy ``(created_at, id)``
    predicate. Otherwise, builds a null-aware predicate matching the
    active ORDER BY direction + NULLS position.
    """
    if parsed is None:
        return or_(
            default_col < cursor_value,
            and_(default_col == cursor_value, id_col < cursor_id),
        )

    col = parsed.column
    if parsed.desc:
        # DESC + NULLS LAST: non-null rows in descending value, then nulls.
        if cursor_value is None:
            # Cursor row is null → already past all non-null rows;
            # remaining rows are nulls with smaller id.
            return and_(col.is_(None), id_col < cursor_id)
        # Cursor row has a non-null value → either smaller value, or same
        # value with smaller id, or any null row (nulls come after).
        return or_(
            col < cursor_value,
            and_(col == cursor_value, id_col < cursor_id),
            col.is_(None),
        )
    # ASC + NULLS FIRST: nulls first, then non-null rows in ascending value.
    if cursor_value is None:
        # Cursor row is null → either any non-null row, or another null
        # with smaller id.
        return or_(
            col.is_not(None),
            and_(col.is_(None), id_col < cursor_id),
        )
    # Cursor row has a non-null value → already past all nulls; remaining
    # rows are non-null with larger value, or same value with smaller id.
    return or_(
        col > cursor_value,
        and_(col == cursor_value, id_col < cursor_id),
    )


def encode_cursor(value: Any, row_id: str) -> str:
    """Sort-key-agnostic cursor encoder.

    ``value`` may be a datetime, str, int, float, or None — JSON-serializable
    via ``isoformat()`` for datetimes, raw for primitives, ``null`` for None.
    """
    if isinstance(value, datetime):
        encoded_value: Any = value.isoformat()
    else:
        encoded_value = value
    return base64.urlsafe_b64encode(json.dumps([encoded_value, row_id]).encode()).decode()


def decode_cursor(raw: str, *, value_is_datetime: bool) -> tuple[Any, str]:
    """Reverse of :func:`encode_cursor`; raises ``ValueError`` on parse failure.

    ``value_is_datetime`` controls whether the value-half is parsed as
    ISO 8601 datetime. The router caller decides this based on the active
    ``?sort=`` parameter: e.g., ``sort=created_at:desc`` → ``True``;
    ``sort=name:asc`` → ``False`` (str).
    """
    decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    raw_value = decoded[0]
    row_id = str(decoded[1])
    if value_is_datetime and raw_value is not None:
        value: Any = datetime.fromisoformat(raw_value)
    else:
        value = raw_value
    return value, row_id


# Default column-name fragments that imply datetime cursor values. The
# router caller passes the active sort col name into this helper instead
# of hardcoding the check; centralized here so the convention stays in
# one place.
_DATETIME_SORT_COLS: frozenset[str] = frozenset({"created_at", "completed_at", "ended_at"})


def cursor_value_is_datetime(parsed: ParsedSort | None) -> bool:
    """Return True when the active sort's cursor value-half is a datetime.

    When ``parsed is None`` (default ordering by ``created_at``), returns
    True. Otherwise checks the col name against the standard datetime set.
    """
    if parsed is None:
        return True
    return parsed.col_name in _DATETIME_SORT_COLS
