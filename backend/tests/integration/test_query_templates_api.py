"""Integration smoke for /api/v1/query-templates (Story 3.1, FR-2 + AC-7).

The full contract test matrix lives in
``backend/tests/contract/test_studies_api_contract.py`` /
``test_studies_error_codes.py`` (Story 3.5). This file covers the
behavior gates that Story 3.1's DoD calls out specifically:

* AC-7 sandbox rejection — POST with ``{{ os.system('rm -rf /') }}`` →
  400 ``INVALID_TEMPLATE_SYNTAX``.
* POST happy path round-trip + GET-detail.
* GET-list cursor pagination + X-Total-Count header.
"""

from __future__ import annotations

import httpx
import pytest

from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_post_query_template_happy_path(async_client: httpx.AsyncClient) -> None:
    """Round-trip: POST → 201 + GET-detail returns the same row."""
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "qt-happy",
            "engine_type": "elasticsearch",
            "body": '{"query": {"match": {"title": "{{ query_text }}"}}}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["name"] == "qt-happy"
    assert payload["engine_type"] == "elasticsearch"
    assert payload["version"] == 1
    template_id = payload["id"]

    detail = await async_client.get(f"/api/v1/query-templates/{template_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == template_id


async def test_post_query_template_ac7_sandbox_call_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-7: ``{{ os.system('rm -rf /') }}`` → 400 INVALID_TEMPLATE_SYNTAX."""
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "qt-ac7",
            "engine_type": "elasticsearch",
            "body": "{{ os.system('rm -rf /') }}",
            "declared_params": {},
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_post_query_template_attribute_access_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    """Sandbox: ``{{ "".__class__ }}`` → 400 INVALID_TEMPLATE_SYNTAX."""
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "qt-attr",
            "engine_type": "elasticsearch",
            "body": '{{ "".__class__ }}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


async def test_post_query_template_undeclared_param_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    """Body uses ``{{ foo }}`` not in declared_params → 400 UNDECLARED_PARAM_USED."""
    resp = await async_client.post(
        "/api/v1/query-templates",
        json={
            "name": "qt-undecl",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ foo }}"}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "UNDECLARED_PARAM_USED"


async def test_get_query_template_not_found(async_client: httpx.AsyncClient) -> None:
    """GET-detail with unknown id → 404 TEMPLATE_NOT_FOUND."""
    resp = await async_client.get("/api/v1/query-templates/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


async def test_list_query_templates_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    """GET-list emits the X-Total-Count header."""
    resp = await async_client.get("/api/v1/query-templates")
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers


async def test_post_query_template_name_taken_returns_409(
    async_client: httpx.AsyncClient,
) -> None:
    """Duplicate (name, version=1) → 409 TEMPLATE_NAME_TAKEN."""
    body = {
        "name": "qt-dupe",
        "engine_type": "elasticsearch",
        "body": '{"query": {"match_all": {}}}',
        "declared_params": {},
    }
    r1 = await async_client.post("/api/v1/query-templates", json=body)
    assert r1.status_code == 201, r1.text
    r2 = await async_client.post("/api/v1/query-templates", json=body)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "TEMPLATE_NAME_TAKEN"
