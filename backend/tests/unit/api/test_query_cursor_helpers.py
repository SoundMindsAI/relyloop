"""Unit tests for the per-query cursor helpers (feat_query_inline_crud Story 1.1).

Pure-function tests for ``_encode_query_cursor`` / ``_decode_query_cursor``.
No DB. Covers the cycle-1 GPT-5.5 F2 validator: invalid shape, non-string
``id``, non-UUIDv7 hex all raise 422 ``VALIDATION_ERROR`` deterministically.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import pytest
from fastapi import HTTPException

from backend.app.api.v1.query_sets import _decode_query_cursor, _encode_query_cursor


def _detail(exc: HTTPException) -> dict[str, Any]:
    """Narrow ``HTTPException.detail`` (typed ``Any``) to the envelope dict."""
    return cast(dict[str, Any], exc.detail)


class TestEncodeQueryCursor:
    def test_round_trip(self) -> None:
        original = "01935b9a-0000-7000-8000-000000000001"
        encoded = _encode_query_cursor(original)
        assert _decode_query_cursor(encoded) == original

    def test_encoded_is_url_safe_base64(self) -> None:
        encoded = _encode_query_cursor("01935b9a-0000-7000-8000-000000000001")
        # URL-safe base64 uses `-` and `_` instead of `+` and `/`; padding may use `=`.
        assert all(c.isalnum() or c in "-_=" for c in encoded)

    def test_encoded_decodes_to_id_only_object(self) -> None:
        encoded = _encode_query_cursor("01935b9a-0000-7000-8000-000000000001")
        decoded = json.loads(base64.urlsafe_b64decode(encoded.encode()).decode())
        assert decoded == {"id": "01935b9a-0000-7000-8000-000000000001"}


class TestDecodeQueryCursor:
    def test_invalid_base64_raises_422(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor("not-valid-base64!@#")
        assert exc.value.status_code == 422
        assert _detail(exc.value)["error_code"] == "VALIDATION_ERROR"

    def test_decoded_non_object_raises_422(self) -> None:
        # base64 of `"just a string"` JSON
        raw = base64.urlsafe_b64encode(json.dumps("just a string").encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422
        assert "JSON object" in _detail(exc.value)["message"]

    def test_decoded_list_raises_422(self) -> None:
        raw = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422

    def test_missing_id_key_raises_422(self) -> None:
        raw = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422
        assert "UUIDv7" in _detail(exc.value)["message"]

    def test_id_value_none_raises_422(self) -> None:
        raw = base64.urlsafe_b64encode(json.dumps({"id": None}).encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422

    def test_id_value_int_raises_422(self) -> None:
        raw = base64.urlsafe_b64encode(json.dumps({"id": 42}).encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422

    def test_id_value_non_uuid_string_raises_422(self) -> None:
        raw = base64.urlsafe_b64encode(json.dumps({"id": "not-a-uuid"}).encode()).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422

    def test_id_value_uppercase_hex_raises_422(self) -> None:
        # Regex is lowercase-only per RFC 9562 canonical form.
        raw = base64.urlsafe_b64encode(
            json.dumps({"id": "01935B9A-0000-7000-8000-000000000001"}).encode()
        ).decode()
        with pytest.raises(HTTPException) as exc:
            _decode_query_cursor(raw)
        assert exc.value.status_code == 422

    def test_valid_uuidv7_accepted(self) -> None:
        valid = "01935b9a-abcd-7000-8000-000000000001"
        raw = _encode_query_cursor(valid)
        assert _decode_query_cursor(raw) == valid
