"""Unit tests for the prefix-parser path in
:func:`backend.app.api.errors.validation_exception_handler`
(feat_auto_followup_studies Story 1.1).

The handler unwraps a ``<ALLOWLISTED_CODE>: human msg`` prefix from a
single-error Pydantic ValidationError and emits the canonical envelope
with ``error_code=<ALLOWLISTED_CODE>``. Falls back to ``VALIDATION_ERROR``
when:

  - the message has no prefix that matches the regex, OR
  - the prefix is not in the allowlist, OR
  - multiple field errors are present (multi-error fallback).

This file exercises the handler directly via a synthetic
RequestValidationError — no live FastAPI app needed.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from backend.app.api.errors import validation_exception_handler
from backend.app.api.v1.schemas import StudyConfigSpec


def _run_handler(exc: RequestValidationError) -> dict[str, object]:
    """Drive the async handler synchronously and decode its JSON body."""
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    response = asyncio.run(validation_exception_handler(request, exc))
    body = json.loads(bytes(response.body))
    body["__status__"] = response.status_code
    return body


def test_auto_followup_depth_emits_canonical_error_code() -> None:
    """Out-of-range depth → envelope ``error_code=AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE``.

    Verifies the end-to-end Pydantic-validator → handler path:
    ``StudyConfigSpec(auto_followup_depth=6)`` raises ValidationError,
    handler unwraps the prefix.
    """
    try:
        StudyConfigSpec(max_trials=20, auto_followup_depth=6)
    except ValidationError as e:
        # FastAPI's RequestValidationError wraps a Pydantic ValidationError;
        # for the prefix-parser path we only need exc.errors() to match.
        body = _run_handler(RequestValidationError(e.errors()))
    else:
        raise AssertionError("StudyConfigSpec did not raise on out-of-range depth")

    assert body["__status__"] == 422
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE"
    assert "between 0 and 5" in detail["message"]
    assert detail["retryable"] is False


def test_non_prefixed_validation_error_falls_back_to_generic_envelope() -> None:
    """Regression guard (cycle-2 finding C2-1): a Pydantic validator that
    raises ValueError WITHOUT a recognized prefix (e.g., the existing
    _require_one_stop_condition validator at schemas.py:578) must still
    return the generic VALIDATION_ERROR envelope. This locks down that the
    prefix parser doesn't accidentally consume non-prefixed messages.
    """
    try:
        StudyConfigSpec()  # neither max_trials nor time_budget_min set
    except ValidationError as e:
        body = _run_handler(RequestValidationError(e.errors()))
    else:
        raise AssertionError("StudyConfigSpec() with no stop condition should raise")

    assert body["__status__"] == 422
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "VALIDATION_ERROR"
    assert "stop condition" in detail["message"]


def test_unallowlisted_prefix_falls_back_to_generic() -> None:
    """A ValueError with a syntactically-valid prefix that's NOT in the
    allowlist falls back to VALIDATION_ERROR. Locks down the allowlist
    as the authoritative whitelist (constraint from cycle-2 C2-1)."""
    # Build a synthetic Pydantic error with a prefix that matches the
    # regex but isn't in the allowlist.
    synthetic_errors = [
        {
            "type": "value_error",
            "loc": ("body", "foo"),
            "msg": "Value error, SOME_UNRELATED_CODE: this should fall back",
            "input": None,
        }
    ]
    body = _run_handler(RequestValidationError(synthetic_errors))

    assert body["__status__"] == 422
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "VALIDATION_ERROR"
    # Generic envelope re-formats the message with the field path
    assert "foo" in detail["message"]


def test_multi_error_response_falls_back_to_generic() -> None:
    """When the request triggers multiple validation errors (e.g., two
    invalid fields), the prefix parser is bypassed — even if one error
    matches an allowlisted prefix. The single-error contract avoids
    ambiguity over which prefix wins."""
    synthetic_errors = [
        {
            "type": "value_error",
            "loc": ("body", "config", "auto_followup_depth"),
            "msg": (
                "Value error, AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE: "
                "config.auto_followup_depth must be between 0 and 5; got 7"
            ),
            "input": 7,
        },
        {
            "type": "missing",
            "loc": ("body", "name"),
            "msg": "Field required",
            "input": None,
        },
    ]
    body = _run_handler(RequestValidationError(synthetic_errors))

    assert body["__status__"] == 422
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "VALIDATION_ERROR"  # NOT the depth code
    # Both field paths appear in the summarized message
    assert "auto_followup_depth" in detail["message"]
    assert "name" in detail["message"]


@pytest.mark.parametrize(
    "raw_msg",
    [
        "Value error, no_prefix at all just plain text",
        "Value error, lowercase_prefix: bad",  # lowercase fails regex
        "Value error, XX: too short for the {3,63} length",  # 2 chars fails regex
        "Value error, MISSING_COLON_at_end and then text",  # no colon
    ],
)
def test_malformed_prefixes_fall_back_to_generic(raw_msg: str) -> None:
    """Prefix regex is intentionally strict — these should all fall through."""
    synthetic_errors = [
        {
            "type": "value_error",
            "loc": ("body", "field"),
            "msg": raw_msg,
            "input": None,
        }
    ]
    body = _run_handler(RequestValidationError(synthetic_errors))
    assert body["__status__"] == 422
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "VALIDATION_ERROR"
