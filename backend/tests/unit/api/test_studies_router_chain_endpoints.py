"""Router-level tests for the Story 2.3 chain endpoints.

Verifies that ``backend.app.api.v1.studies`` registers:

* ``GET /studies/{study_id}/children`` (FR-10 backend)
* ``POST /studies/{study_id}/cancel?cascade=<bool>`` (FR-8 wire surface)

Plus the ``_parse_cascade`` dependency that emits ``INVALID_CASCADE_PARAM``
(400) for invalid query values instead of FastAPI's default 422.

These are router-introspection tests, not end-to-end. The end-to-end
contract is exercised by the integration tests in
``backend/tests/integration/test_studies_api.py`` (CI-gated; not on
host without service containers). Router introspection gives a fast
regression guard against the endpoint shape drifting.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api.v1.studies import _parse_cascade, router


def _api_route_paths_methods() -> set[tuple[str, tuple[str, ...]]]:
    """Collect (path, methods) tuples from APIRoutes only (skip non-route entries)."""
    from fastapi.routing import APIRoute

    return {
        (route.path, tuple(sorted(route.methods)))
        for route in router.routes
        if isinstance(route, APIRoute)
    }


def test_children_endpoint_registered() -> None:
    """GET /studies/{study_id}/children is on the router."""
    assert ("/studies/{study_id}/children", ("GET",)) in _api_route_paths_methods()


def test_cancel_endpoint_registered() -> None:
    """POST /studies/{study_id}/cancel is on the router (extended, not new)."""
    assert ("/studies/{study_id}/cancel", ("POST",)) in _api_route_paths_methods()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("  true  ", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
    ],
)
def test_parse_cascade_accepts_case_insensitive_bool(raw: str, expected: bool) -> None:
    """Per spec §8.2: ``?cascade=`` parses case-insensitively."""
    assert _parse_cascade(raw) is expected


@pytest.mark.parametrize("raw", ["yes", "no", "1", "0", "True!", "", "maybe"])
def test_parse_cascade_rejects_non_bool_values_with_invalid_cascade_param(raw: str) -> None:
    """Per spec §8.5: invalid ``?cascade=`` raises 400 ``INVALID_CASCADE_PARAM``
    (NOT FastAPI's default 422). The custom dependency is the canonical
    mechanism per Story 2.3."""
    from typing import Any, cast

    with pytest.raises(HTTPException) as exc_info:
        _parse_cascade(raw)
    assert exc_info.value.status_code == 400
    # exc.detail is typed `Any` by FastAPI; cast to dict for the assertion.
    detail = cast(dict[str, Any], exc_info.value.detail)
    assert detail["error_code"] == "INVALID_CASCADE_PARAM"
    assert detail["retryable"] is False
    assert "true" in detail["message"].lower()
    assert "false" in detail["message"].lower()


def test_parse_cascade_default_is_true() -> None:
    """The ``Query(default='true')`` default makes ``?cascade=`` optional;
    omitting it on the URL produces ``cascade=True`` (spec §8.1 default
    + D-9 cascade-by-default rationale)."""
    # When called with no args, the FastAPI Query default fires — but in
    # our unit-test invocation we have to pass the default explicitly.
    # Verify the function works correctly when invoked with the default.
    assert _parse_cascade("true") is True


def test_cancel_route_accepts_cascade_dependency() -> None:
    """The cancel handler signature declares ``cascade`` as an
    ``Annotated[bool, Depends(_parse_cascade)]`` parameter. Regression
    guard: a change that drops the cascade parameter from the route
    signature would silently revert FR-8 to the pre-Story-2.3
    single-cancel behavior."""
    from fastapi.routing import APIRoute

    for route in router.routes:
        if isinstance(route, APIRoute) and route.path == "/studies/{study_id}/cancel":
            sig_params = list(route.endpoint.__annotations__.keys())
            assert "cascade" in sig_params, (
                "POST /studies/{id}/cancel handler is missing the `cascade` "
                "parameter — Story 2.3 cascade query-param wiring is gone."
            )
            return
    raise AssertionError("POST /studies/{id}/cancel route not found")
