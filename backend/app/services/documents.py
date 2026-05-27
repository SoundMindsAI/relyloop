"""Helpers for the documents browse endpoint.

Per ``feat_index_document_browser`` spec D-27 / FR-3: the list endpoint
serves a *truncated* preview of ``_source`` so a single index with large
documents (multi-MB) cannot exhaust the wire / browser. The detail endpoint
returns the full document.

Two-layer truncation:

1. Per-field cap (default 8 KiB UTF-8): any top-level field whose JSON
   serialization exceeds the cap is replaced with the sentinel string
   :data:`DOCUMENT_FIELD_TRUNCATED`. The frontend renders the sentinel
   verbatim with a tooltip linking to the detail view.
2. Whole-document cap (default 64 KiB UTF-8): if the post-field-cap
   document still exceeds the cap, the full ``_source`` is replaced with
   ``{DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: True, "field_count": N}`` so the
   frontend can render a "Document too large for list view" placeholder.
"""

from __future__ import annotations

import json
from typing import Any

DOCUMENT_FIELD_TRUNCATED: str = "<…truncated; full value on detail view…>"
"""Sentinel string written in place of any per-field value that exceeds the
list-view per-field cap. Includes a non-ASCII ellipsis (``…``) so collisions
with real document content are vanishingly rare in practice (per spec
failure-mode catalog)."""

DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: str = "__list_view_too_large__"
"""Top-level key written when the whole document still exceeds the list-view
cap *after* per-field truncation. The frontend treats this as a placeholder
and links the operator to the detail view."""


def _utf8_len(value: Any) -> int:
    """Return the UTF-8 byte length of ``json.dumps(value, ensure_ascii=False)``."""
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def truncate_source_for_list(
    source: dict[str, Any] | None,
    *,
    per_field_cap_bytes: int = 8192,
    total_cap_bytes: int = 65536,
) -> dict[str, Any] | None:
    """Apply two-layer truncation to a single document's ``_source``.

    Returns ``None`` when ``source`` is ``None`` (``_source: false`` indices).
    """
    if source is None:
        return None

    result: dict[str, Any] = {}
    for field, value in source.items():
        if _utf8_len(value) > per_field_cap_bytes:
            result[field] = DOCUMENT_FIELD_TRUNCATED
        else:
            result[field] = value

    if _utf8_len(result) > total_cap_bytes:
        return {
            DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: True,
            "field_count": len(source),
        }
    return result
