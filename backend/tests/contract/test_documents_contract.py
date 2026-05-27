"""Contract tests for ``feat_index_document_browser`` Stories 2.2 + 2.3.

Asserts:

* Response shapes (``DocumentSummary``, ``DocumentListResponse``,
  adapter ``Document``) are importable + carry the expected fields.
* OpenAPI registers both endpoints with the documented paths.
* Router source contains the spec §7.5 error codes
  (``CLUSTER_NOT_FOUND``, ``TARGET_NOT_FOUND``, ``DOCUMENT_NOT_FOUND``,
  ``TARGETS_FORBIDDEN``, ``CLUSTER_UNREACHABLE``, ``VALIDATION_ERROR``).
* ``DOCUMENT_NOT_FOUND`` is **NEW** to this surface — confirms it isn't
  silently mis-typed.
* ``X-Total-Count`` header presence on the list endpoint (asserted by
  router-source grep — the integration test exercises the actual header
  value).
* ``?since=`` rejected by the strict-query-param dep (integration).

The integration tests at
``backend/tests/integration/test_documents_endpoints.py`` cover the live
ES-backed round trips. Contract layer is hermetic — no DB / no ES.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

SPEC_ERROR_CODES = {
    "CLUSTER_NOT_FOUND",
    "TARGET_NOT_FOUND",
    "DOCUMENT_NOT_FOUND",  # NEW — detail endpoint only
    "TARGETS_FORBIDDEN",
    "CLUSTER_UNREACHABLE",
    "VALIDATION_ERROR",
}

EXPECTED_ENDPOINTS = {
    ("get", "/api/v1/clusters/{cluster_id}/targets/{target}/documents"),
    ("get", "/api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}"),
}

_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — error-code paths flow through get_db dependency",
)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


def test_response_models_importable() -> None:
    """All documented response models are importable from their canonical modules."""
    from backend.app.adapters.protocol import (
        AdapterDocumentHit,
        Document,
        DocumentPage,
    )
    from backend.app.api.v1.schemas import (
        DocumentListResponse,
        DocumentSummary,
    )

    # Required fields per spec §8 / D-17.
    assert "doc_id" in DocumentSummary.model_fields
    assert "source" in DocumentSummary.model_fields
    assert "data" in DocumentListResponse.model_fields
    assert "next_cursor" in DocumentListResponse.model_fields
    assert "has_more" in DocumentListResponse.model_fields
    assert "doc_id" in Document.model_fields
    assert "source" in Document.model_fields
    assert "doc_id" in AdapterDocumentHit.model_fields
    assert "sort" in AdapterDocumentHit.model_fields
    assert "hits" in DocumentPage.model_fields
    assert "total" in DocumentPage.model_fields


def test_router_source_contains_spec_error_codes() -> None:
    """The 6 spec §7.5 error codes appear as literals in the router source."""
    src = Path("backend/app/api/v1/clusters.py").read_text(encoding="utf-8")
    missing = [c for c in SPEC_ERROR_CODES if c not in src]
    assert not missing, f"router does not raise: {missing}"


def test_router_source_emits_x_total_count_header() -> None:
    """The list endpoint sets the X-Total-Count header per FR-3."""
    src = Path("backend/app/api/v1/clusters.py").read_text(encoding="utf-8")
    assert "X-Total-Count" in src


def test_router_source_uses_strict_query_params() -> None:
    """The list endpoint gates unknown query params via the strict dep."""
    src = Path("backend/app/api/v1/clusters.py").read_text(encoding="utf-8")
    assert "strict_unknown_query_params" in src
    assert '"cursor"' in src
    assert '"limit"' in src
    assert '"fields"' in src


def test_truncation_sentinel_constant_exported() -> None:
    """The frontend imports the sentinel by name — must stay exported."""
    from backend.app.services.documents import (
        DOCUMENT_FIELD_TRUNCATED,
        DOCUMENT_LIST_VIEW_TOO_LARGE_KEY,
    )

    assert isinstance(DOCUMENT_FIELD_TRUNCATED, str)
    assert DOCUMENT_FIELD_TRUNCATED.startswith("<")
    assert "truncated" in DOCUMENT_FIELD_TRUNCATED
    assert DOCUMENT_LIST_VIEW_TOO_LARGE_KEY.startswith("__")


@_skip_if_no_pg
async def test_openapi_registers_both_endpoints(
    async_client: httpx.AsyncClient,
) -> None:
    """Both new endpoints appear in the OpenAPI schema with expected paths."""
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    found = {
        (method.lower(), path)
        for path, ops in paths.items()
        for method in ops
        if (method.lower(), path) in EXPECTED_ENDPOINTS
    }
    assert found == EXPECTED_ENDPOINTS, EXPECTED_ENDPOINTS - found


@_skip_if_no_pg
async def test_list_endpoint_rejects_unknown_query_param(
    async_client: httpx.AsyncClient,
) -> None:
    """``?since=`` is not in the allowlist — must return 422 VALIDATION_ERROR."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents?since=2024-01-01",
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["error_code"] == "VALIDATION_ERROR"
    assert body["detail"]["retryable"] is False


@_skip_if_no_pg
async def test_list_endpoint_rejects_wildcard_fields(
    async_client: httpx.AsyncClient,
) -> None:
    """``?fields=*`` is wildcard-rejected per FR-3."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents?fields=*",
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


@_skip_if_no_pg
async def test_list_endpoint_caps_limit_at_100(
    async_client: httpx.AsyncClient,
) -> None:
    """``?limit=101`` exceeds the documented cap → 422 VALIDATION_ERROR."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents?limit=101",
    )
    assert resp.status_code == 422


@_skip_if_no_pg
async def test_list_endpoint_404_for_missing_cluster(
    async_client: httpx.AsyncClient,
) -> None:
    """Hitting a non-existent cluster_id returns CLUSTER_NOT_FOUND."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents",
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["error_code"] == "CLUSTER_NOT_FOUND"
    assert body["detail"]["retryable"] is False


@_skip_if_no_pg
async def test_detail_endpoint_404_for_missing_cluster(
    async_client: httpx.AsyncClient,
) -> None:
    """Detail endpoint shares the CLUSTER_NOT_FOUND path."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents/some-id",
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


@_skip_if_no_pg
async def test_detail_endpoint_path_converter_accepts_slashes(
    async_client: httpx.AsyncClient,
) -> None:
    """``{doc_id:path}`` round-trips slashes (D-17 / AC-16). Without the
    converter, FastAPI would 404 before reaching the handler. We confirm
    the request reaches the cluster-lookup branch (CLUSTER_NOT_FOUND)
    rather than failing at routing (404 with FastAPI's default body)."""
    resp = await async_client.get(
        "/api/v1/clusters/00000000-0000-0000-0000-000000000000"
        "/targets/foo/documents/has/multiple/slashes",
    )
    assert resp.status_code == 404
    body = resp.json()
    # Reached our handler — got the structured envelope, not FastAPI's default.
    assert "detail" in body
    assert body["detail"]["error_code"] == "CLUSTER_NOT_FOUND"
