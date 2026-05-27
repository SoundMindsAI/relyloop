"""Unit tests for ``backend/app/services/documents.py::truncate_source_for_list``.

Per ``feat_index_document_browser`` Story 2.1 / spec D-27 / FR-3.
"""

from __future__ import annotations

from backend.app.services.documents import (
    DOCUMENT_FIELD_TRUNCATED,
    DOCUMENT_LIST_VIEW_TOO_LARGE_KEY,
    truncate_source_for_list,
)


def test_none_source_returns_none() -> None:
    assert truncate_source_for_list(None) is None


def test_small_source_passes_through() -> None:
    source = {"title": "Acme widget", "brand": "Acme", "price": 19.99}
    assert truncate_source_for_list(source) == source


def test_per_field_cap_replaces_large_field() -> None:
    big_value = "x" * 9000  # 9 KB > 8 KiB default cap
    source = {"title": "ok", "description": big_value}
    out = truncate_source_for_list(source)
    assert out is not None
    assert out["title"] == "ok"
    assert out["description"] == DOCUMENT_FIELD_TRUNCATED


def test_per_field_cap_handles_nested_value_over_cap() -> None:
    """A nested-object top-level value over the cap is replaced wholesale."""
    big_nested = {"deeply": {"nested": {"value": "x" * 9000}}}
    source = {"title": "ok", "metadata": big_nested}
    out = truncate_source_for_list(source)
    assert out is not None
    assert out["metadata"] == DOCUMENT_FIELD_TRUNCATED


def test_per_field_cap_respects_custom_value() -> None:
    source = {"a": "x" * 100, "b": "ok"}
    out = truncate_source_for_list(source, per_field_cap_bytes=50)
    assert out is not None
    assert out["a"] == DOCUMENT_FIELD_TRUNCATED
    assert out["b"] == "ok"


def test_whole_doc_cap_replaces_with_placeholder() -> None:
    """When per-field truncation isn't enough, the whole doc is replaced."""
    # 100 small-ish fields each just under per-field cap but cumulatively
    # well over the total cap.
    source = {f"f{i}": "x" * 1000 for i in range(100)}
    out = truncate_source_for_list(source, per_field_cap_bytes=8192, total_cap_bytes=10000)
    assert out == {DOCUMENT_LIST_VIEW_TOO_LARGE_KEY: True, "field_count": 100}


def test_multibyte_chars_counted_in_utf8_bytes() -> None:
    """A 4-char emoji takes 4 UTF-8 bytes per code point — caps must respect this."""
    # Use a 4-byte emoji and a tight per-field cap to confirm UTF-8 byte counting.
    value = "🎉" * 5  # 5 × 4 = 20 bytes
    source = {"emoji": value}
    out = truncate_source_for_list(source, per_field_cap_bytes=10)
    assert out is not None
    assert out["emoji"] == DOCUMENT_FIELD_TRUNCATED


def test_empty_dict_passes_through() -> None:
    assert truncate_source_for_list({}) == {}
