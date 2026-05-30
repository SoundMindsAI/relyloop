# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Opaque cursor encoding for the documents browse endpoint.

Encodes/decodes the ES ``hits.hits[i].sort`` array (used as ``search_after``
on the next request) as a base64-urlsafe JSON blob. Per
``feat_index_document_browser`` spec FR-11 / D-25.

The cursor is opaque to clients — they pass back the string verbatim. The
encoding is reversible and stateless (no server-side cursor registry).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from backend.app.api.v1._errors import _err


def encode_documents_cursor(sort: list[Any]) -> str:
    """Encode an ES sort array into an opaque cursor string.

    Uses ``separators=(",", ":")`` so the base64-encoded blob in the query
    string stays as short as possible — relevant when an operator's sort
    contains long string IDs and the cursor would otherwise be bloated by
    JSON's default whitespace (Gemini cycle-1 finding #5).
    """
    compact = json.dumps(sort, separators=(",", ":"))
    return base64.urlsafe_b64encode(compact.encode("utf-8")).decode("ascii")


def decode_documents_cursor(raw: str) -> list[Any]:
    """Reverse of :func:`encode_documents_cursor`.

    Raises ``HTTPException(422, VALIDATION_ERROR)`` on malformed input — both
    base64 / JSON parse errors AND structural errors (e.g., a cursor that
    decodes to ``{}`` or a bare string). Per cycle-2 F9: a syntactically
    valid encoding of ``{}`` or ``"foo"`` would otherwise pass through to
    ES as ``search_after`` and trigger an engine-side error with no useful
    error_code on the wire.
    """
    try:
        payload = base64.urlsafe_b64decode(raw.encode("ascii"))
        value = json.loads(payload.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    if not isinstance(value, list):
        raise _err(
            422,
            "VALIDATION_ERROR",
            "invalid cursor: decoded value is not a list",
            False,
        )
    return value
