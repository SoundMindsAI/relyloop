"""Contract assertions for the Epic 3 judgments API (feat_llm_judgments).

Asserts:

* Every endpoint is registered in the OpenAPI schema at the expected method
  + path.
* Each Pydantic response_model is wired so OpenAPI exposes the right shape.
* All 13 error codes (the 11 from spec §8.5 + ``QUERY_NOT_IN_SET`` and
  ``LIST_NOT_READY`` drift codes + ``UNKNOWN_MODEL_PRICING``) are reachable
  in the source — best-effort grep + functional smoke for the codes whose
  preflight does not require DB rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

# The OpenAPI-introspection tests need the FastAPI app to boot which in turn
# needs a reachable Postgres (the lifespan opens an engine). The static
# error-code grep test below does not — it's plain file-IO. Apply the skipif
# to specific tests instead of the module so the grep test runs in any env.
_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — error-code paths flow through get_db dependency",
)


EXPECTED_ENDPOINTS = {
    ("post", "/api/v1/judgments/generate"),
    ("post", "/api/v1/judgment-lists/import"),
    ("get", "/api/v1/judgment-lists"),
    ("get", "/api/v1/judgment-lists/{judgment_list_id}"),
    ("get", "/api/v1/judgment-lists/{judgment_list_id}/judgments"),
    (
        "patch",
        "/api/v1/judgment-lists/{judgment_list_id}/judgments/{judgment_id}",
    ),
    ("post", "/api/v1/judgment-lists/{judgment_list_id}/calibration"),
}


# Spec §8.5 + cycle-1 drift (QUERY_NOT_IN_SET, LIST_NOT_READY) + cycle-2 drift
# (UNKNOWN_MODEL_PRICING).
SPEC_ERROR_CODES = frozenset(
    {
        "OPENAI_NOT_CONFIGURED",
        "OPENAI_BUDGET_EXCEEDED",
        "LLM_PROVIDER_INCAPABLE",
        "JUDGMENT_LIST_NOT_FOUND",
        "JUDGMENT_LIST_NAME_TAKEN",
        "JUDGMENT_NOT_FOUND",
        "INVALID_RATING",
        "INSUFFICIENT_SAMPLES",
        "QUERY_SET_NOT_FOUND",
        "CLUSTER_NOT_FOUND",
        "TEMPLATE_NOT_FOUND",
        "QUERY_NOT_IN_SET",
        "LIST_NOT_READY",
        "UNKNOWN_MODEL_PRICING",
    }
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


@_skip_if_no_pg
async def test_openapi_registers_all_seven_endpoints(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    for method, path in EXPECTED_ENDPOINTS:
        assert path in paths, f"missing path {path}"
        assert method in paths[path], f"missing {method.upper()} on {path}"


@_skip_if_no_pg
async def test_post_generate_response_model_is_registered(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/judgments/generate"]["post"]
    # 202 success response must reference the GenerateJudgmentsResponse model.
    success = op["responses"]["202"]
    content = success["content"]["application/json"]
    ref = content["schema"]["$ref"]
    assert ref.endswith("GenerateJudgmentsResponse"), ref


@_skip_if_no_pg
async def test_patch_override_response_model_is_judgment_row(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/judgment-lists/{judgment_list_id}/judgments/{judgment_id}"][
        "patch"
    ]
    success = op["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("JudgmentRow"), ref


@_skip_if_no_pg
async def test_list_judgment_lists_endpoint_declares_filter_query_params(
    async_client: httpx.AsyncClient,
) -> None:
    """``bug_judgment_lists_listing_ignores_query_set_filter`` contract gate.

    Asserts that the OpenAPI schema for ``GET /api/v1/judgment-lists``
    declares ``query_set_id`` and ``cluster_id`` as query parameters. Both
    are constrained to 1–36 chars (UUIDv7). Without these declarations,
    FastAPI silently dropped the params from the frontend ``useJudgmentLists``
    hook, leaving the create-study modal's Step-2 dropdown unfiltered and
    forcing the user to a confusing 422 at ``POST /api/v1/studies``.
    """
    response = await async_client.get("/openapi.json")
    schema = response.json()
    params = schema["paths"]["/api/v1/judgment-lists"]["get"].get("parameters", [])
    by_name = {p["name"]: p for p in params if p.get("in") == "query"}

    assert "query_set_id" in by_name, (
        f"GET /judgment-lists missing `query_set_id` query param; got {sorted(by_name)}"
    )
    assert "cluster_id" in by_name, (
        f"GET /judgment-lists missing `cluster_id` query param; got {sorted(by_name)}"
    )
    # Both should be optional strings (UUIDv7 → max 36 chars).
    for name in ("query_set_id", "cluster_id"):
        spec = by_name[name]["schema"]
        # Optional → anyOf [string, null] or `nullable: true` depending on
        # FastAPI's emitted shape.
        if "anyOf" in spec:
            string_branch = next((s for s in spec["anyOf"] if s.get("type") == "string"), None)
            assert string_branch is not None, f"{name}: no string branch in anyOf"
            assert string_branch.get("maxLength") == 36, (
                f"{name}: maxLength != 36 (got {string_branch.get('maxLength')})"
            )
        else:
            assert spec.get("type") == "string", f"{name}: not a string"
            assert spec.get("maxLength") == 36, f"{name}: maxLength != 36"


def test_all_spec_error_codes_referenced_in_router_source() -> None:
    """Every spec/drift error code appears as a literal in the router OR its dispatch helper.

    Cheap static check that no error code was renamed without updating the
    spec/contract. Catches drift between the catalog and the handler — not a
    full contract test but a useful safety net. The preflight error codes
    (OPENAI_*, LLM_PROVIDER_INCAPABLE, UNKNOWN_MODEL_PRICING, TEMPLATE_NOT_FOUND)
    live in :mod:`backend.app.services.agent_judgments_dispatch` since
    feat_chat_agent Story 2.2 lifted them out of the router so the chat-agent
    ``generate_judgments_llm`` tool reuses the same checks.
    """
    sources = "\n".join(
        Path(p).read_text(encoding="utf-8")
        for p in (
            "backend/app/api/v1/judgments.py",
            "backend/app/services/agent_judgments_dispatch.py",
        )
    )
    missing = [code for code in SPEC_ERROR_CODES if code not in sources]
    assert not missing, f"neither router nor dispatch helper raises spec codes: {missing}"
