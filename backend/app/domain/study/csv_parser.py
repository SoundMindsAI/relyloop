"""CSV → row-dicts parser for bulk query upload (Story 3.2, FR-3 + AC-8).

Pure-domain helper used by ``POST /api/v1/query-sets/{id}/queries`` when
the request carries ``Content-Type: text/csv``. The matching JSON path
(``Content-Type: application/json``) is handled by Pydantic on the
router side.

Schema:

* Required column: ``query_text``.
* Optional column: ``reference_answer``.
* Any other columns become per-row ``query_metadata`` dict entries
  (preserves spec §7 FR-3 "metadata as additional columns").
* Row-count cap: 10,000 (defense-in-depth against operator typos +
  resource starvation).

Errors raise :exc:`InvalidCsvError`; the router translates to spec §7.5
400 ``INVALID_CSV``.
"""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any


class InvalidCsvError(ValueError):
    """CSV header mismatch, row count exceeded, or per-row validation failure.

    Router translates to 400 ``INVALID_CSV`` per spec §7.5.
    """


_REQUIRED_COLUMNS: frozenset[str] = frozenset({"query_text"})
_OPTIONAL_COLUMNS: frozenset[str] = frozenset({"reference_answer"})
_MAX_ROWS: int = 10_000


def parse_queries_csv(body: bytes) -> list[dict[str, Any]]:
    """Parse a UTF-8 CSV body into row dicts suitable for ``bulk_create_queries``.

    Returns a list of ``{"query_text", "reference_answer", "query_metadata"}``
    dicts. ``query_metadata`` is ``None`` when no extra columns appear.

    Raises :exc:`InvalidCsvError` on UTF-8 decode failure, missing
    header, missing required columns, blank ``query_text``, or row count
    over :data:`_MAX_ROWS`.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCsvError(f"csv body is not valid UTF-8: {exc}") from exc

    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise InvalidCsvError("csv body has no header row")

    headers = set(reader.fieldnames)
    missing = _REQUIRED_COLUMNS - headers
    if missing:
        raise InvalidCsvError(f"csv missing required column(s): {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):  # row 1 was the header
        if i > _MAX_ROWS + 1:
            raise InvalidCsvError(f"csv exceeds max row count ({_MAX_ROWS})")
        query_text = row.get("query_text") or ""
        if not query_text.strip():
            raise InvalidCsvError(f"row {i}: empty `query_text`")
        metadata = {
            k: v
            for k, v in row.items()
            if k not in _REQUIRED_COLUMNS and k not in _OPTIONAL_COLUMNS and v
        }
        rows.append(
            {
                "query_text": query_text,
                "reference_answer": row.get("reference_answer") or None,
                "query_metadata": metadata or None,
            }
        )
    return rows


__all__ = ["InvalidCsvError", "parse_queries_csv"]
