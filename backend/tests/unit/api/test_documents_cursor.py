"""Unit tests for ``backend/app/api/v1/_documents_cursor.py``.

Per ``feat_index_document_browser`` Story 2.1 / FR-11. Covers:

- Round-trip encode → decode preserves the sort array verbatim
- Malformed base64 / JSON → 422 VALIDATION_ERROR
- Empty list round-trips
- Mixed-type list (str, int, None) round-trips
- Cycle-2 F9: non-list decoded value (``{}`` or bare string) → 422
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi import HTTPException

from backend.app.api.v1._documents_cursor import (
    decode_documents_cursor,
    encode_documents_cursor,
)


def _roundtrip(sort: list[Any]) -> list[Any]:
    return decode_documents_cursor(encode_documents_cursor(sort))


def test_encode_decode_roundtrip_string_sort() -> None:
    sort = ["doc-042"]
    assert _roundtrip(sort) == sort


def test_encode_decode_roundtrip_empty_list() -> None:
    assert _roundtrip([]) == []


def test_encode_decode_roundtrip_mixed_types() -> None:
    sort = ["doc-007", 42, None, True]
    assert _roundtrip(sort) == sort


def test_decode_rejects_malformed_base64() -> None:
    with pytest.raises(HTTPException) as exc_info:
        decode_documents_cursor("!!!not-valid-base64$$$")
    assert exc_info.value.status_code == 422
    detail: Any = exc_info.value.detail
    assert detail["error_code"] == "VALIDATION_ERROR"
    assert detail["retryable"] is False


def test_decode_rejects_non_json_payload() -> None:
    raw = base64.urlsafe_b64encode(b"not json at all").decode("ascii")
    with pytest.raises(HTTPException) as exc_info:
        decode_documents_cursor(raw)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "VALIDATION_ERROR"  # type: ignore[index]


def test_decode_rejects_object_payload() -> None:
    """Cycle-2 F9: a syntactically valid encoding of ``{}`` would otherwise
    pass through to ES as ``search_after`` and produce engine errors."""
    raw = base64.urlsafe_b64encode(json.dumps({"not": "a list"}).encode()).decode("ascii")
    with pytest.raises(HTTPException) as exc_info:
        decode_documents_cursor(raw)
    assert exc_info.value.status_code == 422
    assert "not a list" in exc_info.value.detail["message"]  # type: ignore[index]


def test_decode_rejects_string_payload() -> None:
    raw = base64.urlsafe_b64encode(json.dumps("doc-001").encode()).decode("ascii")
    with pytest.raises(HTTPException) as exc_info:
        decode_documents_cursor(raw)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "VALIDATION_ERROR"  # type: ignore[index]


def test_encoded_cursor_is_urlsafe() -> None:
    """The encoded blob must only contain URL-safe characters so it round-trips
    cleanly through query strings."""
    encoded = encode_documents_cursor(["doc with spaces / slash"])
    # base64-urlsafe alphabet: A-Z a-z 0-9 - _ =
    assert all(c.isalnum() or c in "-_=" for c in encoded)
