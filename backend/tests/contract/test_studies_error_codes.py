"""Spec §7.5 error-code matrix for the Phase 2 API surface (Story 3.5).

The DB-dependent codes are exercised at the integration layer
(``backend/tests/integration/test_*_api.py``). This module asserts the
pure-contract codes reachable via the FastAPI app without writing rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
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


async def test_invalid_template_syntax_via_call(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "bad-call",
            "engine_type": "elasticsearch",
            "body": "{{ foo() }}",
            "declared_params": {"foo": "callable"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_invalid_template_syntax_via_attribute(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "bad-attr",
            "engine_type": "elasticsearch",
            "body": "{{ x.y }}",
            "declared_params": {"x": "string"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_undeclared_param_used(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "undecl",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ undeclared }}"}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "UNDECLARED_PARAM_USED"


async def test_declared_param_unused(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "unused",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ query_text }}"}',
            "declared_params": {"orphan": "string"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "DECLARED_PARAM_UNUSED"


async def test_trials_list_invalid_sort_key_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Bad ``?sort=`` value → 422 VALIDATION_ERROR before the study lookup."""
    fake = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.get(f"/api/v1/studies/{fake}/trials?sort=unknown")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_query_set_bulk_missing_query_set_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /queries on unknown query_set → 404 QUERY_SET_NOT_FOUND.

    The INVALID_CSV content-type path requires a real query_set; that
    surface is covered in integration's ``test_csv_upload.py``."""
    fake = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.post(
        f"/api/v1/query-sets/{fake}/queries",
        content=b"not really a csv",
        headers={"Content-Type": "text/xml"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"
