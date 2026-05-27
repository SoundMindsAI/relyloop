"""Unit tests for ``backend/app/api/v1/_strict_query_params.py``.

Per ``feat_index_document_browser`` Story 2.1. Covers the FastAPI-dependency
shape: allowed params pass; disallowed ones raise 422 with the spec error
envelope.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from backend.app.api.v1._strict_query_params import strict_unknown_query_params


def test_allowed_params_pass() -> None:
    """Calling the dependency callable directly with an in-memory Request."""
    dep = strict_unknown_query_params({"cursor", "limit"})
    scope = {
        "type": "http",
        "query_string": b"cursor=abc&limit=25",
        "headers": [],
    }
    req = Request(scope=scope)
    dep(req)  # no exception


def test_unknown_param_raises_422() -> None:
    dep = strict_unknown_query_params({"cursor", "limit"})
    scope = {
        "type": "http",
        "query_string": b"cursor=abc&since=2024-01-01",
        "headers": [],
    }
    req = Request(scope=scope)
    with pytest.raises(HTTPException) as exc_info:
        dep(req)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "VALIDATION_ERROR"  # type: ignore[index]
    assert "since" in exc_info.value.detail["message"]  # type: ignore[index]


def test_empty_allowlist_rejects_everything() -> None:
    dep = strict_unknown_query_params(set())
    scope = {
        "type": "http",
        "query_string": b"anything=1",
        "headers": [],
    }
    req = Request(scope=scope)
    with pytest.raises(HTTPException):
        dep(req)


def test_disallowed_multiple_params() -> None:
    """When multiple unknown params are present, the first one is reported."""
    dep = strict_unknown_query_params({"cursor"})
    scope = {
        "type": "http",
        "query_string": b"cursor=abc&extra=1&another=2",
        "headers": [],
    }
    req = Request(scope=scope)
    with pytest.raises(HTTPException) as exc_info:
        dep(req)
    assert exc_info.value.status_code == 422
    # Either "extra" or "another" must be cited (depending on dict iter order
    # over the query-param OrderedDict — Starlette preserves insertion order,
    # so we'll see "extra").
    msg = exc_info.value.detail["message"]  # type: ignore[index]
    assert "extra" in msg or "another" in msg
