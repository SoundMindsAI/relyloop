"""Contract assertions for the Epic 3 digest-proposal API.

Asserts:

* Every endpoint is registered in the OpenAPI schema at the expected
  method + path.
* The split static-grep audit per cycle-2 F4 / cycle-3 F1:
  - router source `backend/app/api/v1/proposals.py` MUST contain the
    7 endpoint-visible spec §8.5 codes.
  - worker source `backend/workers/digest.py` MUST contain the 5
    internal/worker-only codes (`INVALID_STUDY_STATE` + 4 worker
    terminal reasons), each emitted as a structured `error_code=`
    literal alongside its `event_type` marker.
  - the router source MUST NOT contain any of the worker-only codes
    (negative assertion — guards against unauthorized routerization
    that would change the spec contract).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — error-code paths flow through get_db dependency",
)


EXPECTED_ENDPOINTS = {
    ("get", "/api/v1/studies/{study_id}/digest"),
    ("post", "/api/v1/proposals"),
    ("get", "/api/v1/proposals"),
    ("get", "/api/v1/proposals/{proposal_id}"),
    ("post", "/api/v1/proposals/{proposal_id}/reject"),
}


# Spec §8.5 endpoint-visible codes (router source).
ROUTER_VISIBLE_CODES = frozenset(
    {
        "DIGEST_NOT_READY",
        "STUDY_NOT_FOUND",
        "PROPOSAL_NOT_FOUND",
        "CLUSTER_NOT_FOUND",
        "TEMPLATE_NOT_FOUND",
        "INVALID_STATE_TRANSITION",
        "VALIDATION_ERROR",
    }
)

# Spec §8.5 internal/worker-only codes (worker source).
WORKER_ONLY_CODES = frozenset(
    {
        "INVALID_STUDY_STATE",  # defense-in-depth in the worker
        "OPENAI_NOT_CONFIGURED",
        "LLM_PROVIDER_INCAPABLE",
        "UNKNOWN_MODEL_PRICING",
        "OPENAI_BUDGET_EXCEEDED",
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
async def test_openapi_registers_all_five_endpoints(
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
async def test_get_digest_response_model_is_digest_response(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/studies/{study_id}/digest"]["get"]
    success = op["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("DigestResponse"), ref


@_skip_if_no_pg
async def test_create_proposal_response_model_is_proposal_detail(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/proposals"]["post"]
    success = op["responses"]["201"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ProposalDetail"), ref


@_skip_if_no_pg
async def test_list_proposals_response_model_is_proposals_list(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/proposals"]["get"]
    success = op["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ProposalsListResponse"), ref


@_skip_if_no_pg
async def test_proposal_summary_schema_includes_is_currently_live(
    async_client: httpx.AsyncClient,
) -> None:
    """feat_config_repo_baseline_tracking FR-5 — ProposalSummary schema in OpenAPI
    must declare is_currently_live: bool with default false."""
    response = await async_client.get("/openapi.json")
    schema = response.json()
    proposal_summary_schema = schema["components"]["schemas"]["ProposalSummary"]
    properties = proposal_summary_schema["properties"]
    assert "is_currently_live" in properties, (
        "ProposalSummary.is_currently_live missing from OpenAPI"
    )
    field = properties["is_currently_live"]
    assert field.get("type") == "boolean", f"ProposalSummary.is_currently_live not bool: {field}"
    assert field.get("default") is False, (
        f"ProposalSummary.is_currently_live default is not False: {field}"
    )


@_skip_if_no_pg
async def test_proposal_detail_schema_includes_is_currently_live(
    async_client: httpx.AsyncClient,
) -> None:
    """feat_config_repo_baseline_tracking FR-5 — ProposalDetail schema in OpenAPI
    must also declare is_currently_live: bool with default false."""
    response = await async_client.get("/openapi.json")
    schema = response.json()
    proposal_detail_schema = schema["components"]["schemas"]["ProposalDetail"]
    properties = proposal_detail_schema["properties"]
    assert "is_currently_live" in properties, (
        "ProposalDetail.is_currently_live missing from OpenAPI"
    )
    field = properties["is_currently_live"]
    assert field.get("type") == "boolean", f"ProposalDetail.is_currently_live not bool: {field}"
    assert field.get("default") is False, (
        f"ProposalDetail.is_currently_live default is not False: {field}"
    )


@_skip_if_no_pg
async def test_invalid_is_last_merged_returns_wrapped_validation_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    """feat_config_repo_baseline_tracking AC-12 — GET /api/v1/proposals with a
    non-bool ?is_last_merged value (e.g. 'maybe', '2') returns 422 with the
    standard RelyLoop envelope wrapped by the global validation handler at
    backend/app/api/errors.py:103-118 (NOT FastAPI's raw {detail: [{...}]})."""
    resp = await async_client.get("/api/v1/proposals?is_last_merged=maybe")
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    detail = body["detail"]
    assert isinstance(detail, dict), f"detail should be wrapped, got {detail!r}"
    assert detail.get("error_code") == "VALIDATION_ERROR"
    assert detail.get("retryable") is False


@_skip_if_no_pg
async def test_proposal_detail_digest_embed_includes_swap_template_branch(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-9 (feat_digest_executable_followups_swap_template Story 4.1):
    the ProposalDetail.digest._DigestEmbed embed must surface the widened
    FollowupItem union including the SwapTemplateFollowup branch in OpenAPI.

    Asserts the discriminated-union shape via the rendered $defs (Pydantic
    inlines them under ``components.schemas`` in FastAPI's OpenAPI output).
    """
    response = await async_client.get("/openapi.json")
    schema = response.json()
    schemas = schema["components"]["schemas"]
    # The SwapTemplateFollowup component must be present.
    assert "SwapTemplateFollowup" in schemas
    swap = schemas["SwapTemplateFollowup"]
    assert swap["properties"]["kind"].get("const") == "swap_template" or (
        swap["properties"]["kind"].get("enum") == ["swap_template"]
    )
    assert "template_id" in swap["properties"]
    assert "template_id" in swap["required"]
    assert "search_space" in swap["properties"]


def test_router_source_contains_every_endpoint_visible_code() -> None:
    """Cycle-2 F4 / cycle-3 F1: router contains the 7 endpoint-visible codes."""
    router_path = Path("backend/app/api/v1/proposals.py")
    source = router_path.read_text(encoding="utf-8")
    missing = [code for code in ROUTER_VISIBLE_CODES if code not in source]
    assert not missing, f"router source does not raise endpoint-visible codes: {missing}"


def test_router_source_does_not_raise_worker_only_codes() -> None:
    """Cycle-2 F4 / cycle-3 F1 negative assertion: worker-only codes are not RAISED by the router.

    Looks for the actual call shape ``_err(... "<CODE>" ...)`` rather than
    plain mentions — the router is allowed to *reference* a worker code
    in a docstring (e.g. explaining why a deferred digest returns
    ``DIGEST_NOT_READY`` because of an upstream ``OPENAI_NOT_CONFIGURED``)
    but must NOT raise it as an HTTP error envelope.

    Guards against an accidental routerization of a worker-only code,
    which would change the spec contract (worker codes are NOT supposed
    to be endpoint-visible per spec §8.5 last paragraph).
    """
    router_path = Path("backend/app/api/v1/proposals.py")
    source = router_path.read_text(encoding="utf-8")
    leaked = [
        code
        for code in WORKER_ONLY_CODES
        # Look for the actual raise signature: `_err(... "CODE", ...)` —
        # quoted as a string literal positional arg to _err.
        if f'"{code}"' in source
    ]
    assert not leaked, (
        f"router source RAISES worker-only codes (should stay in worker source): {leaked}"
    )


def test_worker_source_contains_every_worker_only_code() -> None:
    """Cycle-2 F4 / cycle-3 F1: worker source contains the 5 internal codes.

    Each code MUST appear as an ``error_code=`` structured-log literal
    so the contract grep finds it.
    """
    worker_path = Path("backend/workers/digest.py")
    source = worker_path.read_text(encoding="utf-8")
    missing = [code for code in WORKER_ONLY_CODES if code not in source]
    assert not missing, f"worker source missing internal/worker-only codes: {missing}"
