"""Contract assertions for the per-query CRUD endpoints (feat_query_inline_crud).

* The 3 new endpoints (GET / PATCH / DELETE) appear in the OpenAPI schema.
* ``QueryListResponse`` is the GET 200 response model.
* ``QueryRow`` is the PATCH 200 response model.
* ``QueryHasJudgmentsEnvelope`` is the DELETE 409 response model with the
  ``judgment_lists`` array + ``overflow_count`` int fields documented.
* All 4 error codes (``QUERY_SET_NOT_FOUND`` — reused, ``QUERY_NOT_FOUND``,
  ``QUERY_HAS_JUDGMENTS``, ``VALIDATION_ERROR`` — standard) appear in the
  router source via grep-based static check.
* No log line in the router emits ``query_text`` / ``reference_answer`` /
  ``query_metadata`` values (defense-in-depth for §10 Threat 3 audit-log
  policy when MVP2 lands).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — router resolves get_db at boot",
)

_ROUTER_SOURCE = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "query_sets.py"


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


@_skip_if_no_pg
async def test_three_endpoints_present_in_openapi(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]

    list_path = "/api/v1/query-sets/{query_set_id}/queries"
    per_query_path = "/api/v1/query-sets/{query_set_id}/queries/{query_id}"

    assert list_path in paths
    assert "get" in paths[list_path]  # NEW
    assert "post" in paths[list_path]  # existing bulk-add — unchanged

    assert per_query_path in paths
    assert "patch" in paths[per_query_path]  # NEW
    assert "delete" in paths[per_query_path]  # NEW


@_skip_if_no_pg
async def test_get_response_model_is_query_list_response(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/openapi.json")
    schema = resp.json()
    list_op = schema["paths"]["/api/v1/query-sets/{query_set_id}/queries"]["get"]
    ref = list_op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/QueryListResponse"
    assert "QueryListResponse" in schema["components"]["schemas"]
    assert "QueryRow" in schema["components"]["schemas"]


@_skip_if_no_pg
async def test_patch_response_model_is_query_row(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.get("/openapi.json")
    schema = resp.json()
    patch_op = schema["paths"]["/api/v1/query-sets/{query_set_id}/queries/{query_id}"]["patch"]
    ref = patch_op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/QueryRow"


@_skip_if_no_pg
async def test_delete_409_response_model_is_query_has_judgments_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/openapi.json")
    schema = resp.json()
    delete_op = schema["paths"]["/api/v1/query-sets/{query_set_id}/queries/{query_id}"]["delete"]
    ref = delete_op["responses"]["409"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/QueryHasJudgmentsEnvelope"

    components = schema["components"]["schemas"]
    assert "QueryHasJudgmentsEnvelope" in components
    assert "QueryHasJudgmentsDetail" in components
    assert "JudgmentListRef" in components

    detail_schema = components["QueryHasJudgmentsDetail"]
    detail_props = detail_schema["properties"]
    # The structured fields the frontend consumes:
    assert "judgment_lists" in detail_props
    assert "overflow_count" in detail_props


@_skip_if_no_pg
async def test_update_query_request_in_components(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.get("/openapi.json")
    components = resp.json()["components"]["schemas"]
    assert "UpdateQueryRequest" in components
    props = components["UpdateQueryRequest"]["properties"]
    # All three optional fields present.
    assert "query_text" in props
    assert "reference_answer" in props
    assert "query_metadata" in props
    # `extra="forbid"` should manifest as `additionalProperties: false`.
    assert components["UpdateQueryRequest"].get("additionalProperties") is False


# ---------------------------------------------------------------------------
# Error code coverage (grep against router source)
# ---------------------------------------------------------------------------


def test_router_emits_all_four_error_codes() -> None:
    """All 4 codes from spec §8.5 appear in the router source."""
    source = _ROUTER_SOURCE.read_text()
    for code in ("QUERY_SET_NOT_FOUND", "QUERY_NOT_FOUND", "QUERY_HAS_JUDGMENTS"):
        assert code in source, f"{code} missing from {_ROUTER_SOURCE}"
    # VALIDATION_ERROR also referenced via _decode_query_cursor.
    assert "VALIDATION_ERROR" in source


def test_router_never_logs_query_text_value() -> None:
    """Defense-in-depth: no logger.info/warning/error call passes a query_text VALUE.

    We allow the bareword ``query_text`` as a key-name argument (the
    PATCH log records `fields_changed=sorted(fields_set.keys())` which
    includes the literal string "query_text" if the operator PATCHed that
    field — that's a key NAME, not its value). What's forbidden is
    passing the actual column VALUE to a log call.
    """
    source = _ROUTER_SOURCE.read_text()

    # Grep every logger.X(...) call body for the column-value access patterns.
    forbidden_patterns = [
        r"row\.query_text",
        r"row\.reference_answer",
        r"row\.query_metadata",
        r"updated\.query_text",
        r"updated\.reference_answer",
        r"updated\.query_metadata",
        r"body\.query_text",
        r"body\.reference_answer",
        r"body\.query_metadata",
    ]

    # Look at logger.* call bodies only — extract everything between
    # `logger.<level>(` and the matching `)`. Simple non-greedy match;
    # works because logger calls in this file are single-statement.
    logger_call_re = re.compile(r"logger\.\w+\((.*?)\)", re.DOTALL)
    for match in logger_call_re.finditer(source):
        call_body = match.group(1)
        for pat in forbidden_patterns:
            assert not re.search(pat, call_body), (
                f"Logger call contains forbidden VALUE access {pat!r}: {call_body[:200]!r}"
            )
