# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for shared /api/v1 cursor helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import HTTPException

from backend.app.api.v1._cursor import (
    decode_created_at_cursor,
    decode_value_cursor,
    encode_created_at_cursor,
    encode_value_cursor,
)


def test_created_at_cursor_round_trips_datetime_and_id() -> None:
    created_at = datetime(2026, 6, 18, 19, 30, tzinfo=UTC)
    token = encode_created_at_cursor(created_at, "row-1")

    assert decode_created_at_cursor(token) == (created_at, "row-1")


def test_value_cursor_keeps_non_datetime_value_shape_when_requested() -> None:
    token = encode_value_cursor(42, "trial-1")

    assert decode_value_cursor(token, datetime_value=False) == (42, "trial-1")


def test_value_cursor_decodes_datetime_value_by_default() -> None:
    ended_at = datetime(2026, 6, 18, 20, 15, tzinfo=UTC)
    token = encode_value_cursor(ended_at, "trial-2")

    assert decode_value_cursor(token) == (ended_at, "trial-2")


def test_malformed_cursor_raises_standard_validation_error() -> None:
    with pytest.raises(HTTPException) as raised:
        decode_created_at_cursor("not-a-cursor")

    assert raised.value.status_code == 422
    detail = cast("dict[str, object]", raised.value.detail)
    assert detail["error_code"] == "VALIDATION_ERROR"
    message = detail["message"]
    assert isinstance(message, str)
    assert message.startswith("invalid cursor:")
    assert detail["retryable"] is False
