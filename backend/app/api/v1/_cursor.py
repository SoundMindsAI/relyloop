# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared opaque cursor helpers for /api/v1 routers.

The repository layer owns keyset predicates. This module owns the HTTP-router
concern: encoding cursor payloads for clients and translating malformed cursor
tokens into the standard API error envelope.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from backend.app.api.v1._errors import _err


def encode_created_at_cursor(created_at: datetime, row_id: str) -> str:
    """Encode the common ``(created_at, id)`` cursor shape."""
    return encode_value_cursor(created_at, row_id)


def decode_created_at_cursor(raw: str) -> tuple[datetime, str]:
    """Decode the common ``(created_at, id)`` cursor shape."""
    value, row_id = decode_value_cursor(raw)
    if not isinstance(value, datetime):
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"invalid cursor: expected datetime value, got {type(value).__name__}",
            False,
        )
    return value, row_id


def encode_value_cursor(value: Any, row_id: str) -> str:
    """Encode a cursor whose value half may be datetime / numeric / str / None."""
    encoded_value: Any = value.isoformat() if isinstance(value, datetime) else value
    return base64.urlsafe_b64encode(json.dumps([encoded_value, row_id]).encode()).decode()


def decode_value_cursor(raw: str, *, datetime_value: bool = True) -> tuple[Any, str]:
    """Decode an opaque cursor token.

    ``datetime_value=False`` keeps the value half in its JSON-decoded shape,
    which is useful for sort-specific cursors such as trial metric or trial
    number. Shape failures surface as ``422 VALIDATION_ERROR``.
    """
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("cursor payload must be a 2-element list")
        raw_value = decoded[0]
        row_id = str(decoded[1])
        value: Any
        if datetime_value:
            value = datetime.fromisoformat(raw_value) if raw_value is not None else None
        else:
            value = raw_value
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    return value, row_id
