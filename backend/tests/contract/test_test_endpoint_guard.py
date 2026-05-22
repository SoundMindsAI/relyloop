"""Contract: ``/api/v1/_test/*`` endpoints exist ONLY when ``ENVIRONMENT=development``.

Builds a minimal FastAPI app wired with the same ``_test`` router that
``backend.app.main`` mounts, then overrides ``get_settings`` to assert the
environment-guard behavior across all four canonical values.

This is the security-relevant assertion for ``infra_e2e_seed_completed_study``:
test-only insertion endpoints MUST NOT exist in staging or production. The
guard returns 404 (``RESOURCE_NOT_FOUND``) rather than 403 so an operator
probing the surface can't distinguish "endpoint exists but forbidden" from
"endpoint never registered" — the staging/production behavior is
indistinguishable from "this server doesn't have that feature."
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from backend.app.api.v1 import _test as test_router
from backend.app.core.settings import Settings, get_settings


def _stub_settings(environment: str) -> Settings:
    """Build a ``Settings`` instance with the required-secret paths pointed at
    ``/dev/null`` (we never resolve them) and the ``environment`` field set.

    Used directly by the guard unit tests AND by ``_build_test_app`` for the
    HTTP-layer parametrized tests.
    """
    return Settings(
        database_url_file=Path("/dev/null"),
        postgres_password_file=Path("/dev/null"),
        environment=environment,
    )


def _build_test_app(environment: str) -> FastAPI:
    """Mount the test router with a Settings override fixing ``environment``."""
    app = FastAPI()
    app.include_router(test_router.router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: _stub_settings(environment)
    return app


_NON_DEV_ENVIRONMENTS = ["staging", "production", "ci", "qa", ""]


@pytest.mark.parametrize("environment", _NON_DEV_ENVIRONMENTS)
async def test_seed_completed_returns_404_outside_development(environment: str) -> None:
    """The endpoint MUST NOT be reachable in any non-development environment.

    Covers the canonical MVP1→GA values (staging is MVP3+, production is
    MVP4+) plus typo-shaped values an operator might set by mistake — all
    return 404 rather than silently allow.
    """
    app = _build_test_app(environment)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/_test/studies/seed-completed",
            json={
                "cluster_id": "x",
                "query_set_id": "x",
                "template_id": "x",
                "judgment_list_id": "x",
            },
        )
    assert response.status_code == httpx.codes.NOT_FOUND
    body = response.json()
    assert body["detail"]["error_code"] == "RESOURCE_NOT_FOUND"
    assert body["detail"]["retryable"] is False


def test_guard_passes_in_development() -> None:
    """The guard dependency must NOT raise when ``environment == "development"``.

    Asserted at the dependency-function layer (no HTTP) because the
    happy-path also needs DB connectivity, which the integration suite
    covers — the contract test's job here is to prove the gate fires
    correctly in both directions.
    """
    settings = _stub_settings("development")
    # Must not raise.
    test_router._require_development_env(settings)


@pytest.mark.parametrize("environment", _NON_DEV_ENVIRONMENTS)
def test_guard_raises_404_outside_development(environment: str) -> None:
    """Symmetric dependency-layer test: the guard raises with the expected
    error code + retryable flag for every non-development value."""
    settings = _stub_settings(environment)
    with pytest.raises(HTTPException) as exc_info:
        test_router._require_development_env(settings)
    assert exc_info.value.status_code == httpx.codes.NOT_FOUND
    # FastAPI types ``HTTPException.detail`` as ``str``, but our routers raise
    # with a structured envelope per api-conventions §"Standard error codes".
    # Cast through ``Any`` to assert on the actual dict shape without tripping
    # mypy's narrowed-to-str unreachable check.
    detail: Any = exc_info.value.detail
    assert detail == {
        "error_code": "RESOURCE_NOT_FOUND",
        "message": "Not found",
        "retryable": False,
    }


def test_seed_completed_request_schema_rejects_unknown_fields() -> None:
    """``extra='forbid'`` is enforced so a tampered payload doesn't silently
    smuggle additional columns into the insert path."""
    with pytest.raises(ValidationError):
        test_router.SeedCompletedStudyRequest(
            cluster_id="c",
            query_set_id="q",
            template_id="t",
            judgment_list_id="j",
            unknown_field="x",  # type: ignore[call-arg]
        )


def test_seed_completed_request_schema_defaults_with_pending_proposal_true() -> None:
    body = test_router.SeedCompletedStudyRequest(
        cluster_id="c",
        query_set_id="q",
        template_id="t",
        judgment_list_id="j",
    )
    assert body.with_pending_proposal is True


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — env-guard contract for the 6 new
# DELETE endpoints. Each MUST 404 with RESOURCE_NOT_FOUND (the env-guard
# envelope, NOT the resource-specific <RESOURCE>_NOT_FOUND) when env != "development".
# ---------------------------------------------------------------------------


_TEST_DELETE_PATHS = [
    "/api/v1/_test/proposals/some-id",
    "/api/v1/_test/digests/some-id",
    "/api/v1/_test/studies/some-id",
    "/api/v1/_test/judgment-lists/some-id",
    "/api/v1/_test/query-sets/some-id",
    "/api/v1/_test/query-templates/some-id",
]


@pytest.mark.parametrize("environment", _NON_DEV_ENVIRONMENTS)
@pytest.mark.parametrize("path", _TEST_DELETE_PATHS)
async def test_test_delete_endpoints_return_404_outside_development(
    path: str, environment: str
) -> None:
    """Each of the 6 new ``DELETE /api/v1/_test/<resource>/{id}`` endpoints
    MUST return 404 ``RESOURCE_NOT_FOUND`` (the env-guard envelope) when
    ``Settings.environment`` is not ``"development"`` — the same shape as
    "endpoint not registered" so operators can't probe for the surface.
    """
    app = _build_test_app(environment)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(path)
    assert response.status_code == httpx.codes.NOT_FOUND
    body = response.json()
    assert body["detail"]["error_code"] == "RESOURCE_NOT_FOUND"
    assert body["detail"]["retryable"] is False
