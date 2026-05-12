"""Contract assertions for the feat_github_pr_worker API surface.

Mirrors :mod:`backend.tests.contract.test_digest_proposal_api_contract`.
Asserts:

* All four endpoints (1 ``open_pr`` on the proposals router + 3 on the
  config-repos router) are registered in the OpenAPI schema.
* Response model wiring on the success status of each new endpoint.
* The split static-grep audit (cycle-2 F4 / cycle-3 F1):
  - **router source** for ``proposals.py`` (the ``open_pr`` handler) +
    ``config_repos.py`` (the 3 CRUD handlers) MUST contain the 9
    endpoint-visible spec §8.5 codes.
  - **worker source** for ``backend/workers/git_pr.py`` MUST contain
    the 5 worker-only terminal codes (``PARAM_NOT_IN_TEMPLATE``,
    ``PARAMS_FILE_NOT_FOUND``, ``BRANCH_EXISTS``, ``GITHUB_API_FAILED``,
    ``CLONE_FAILED``).
  - Negative: router source MUST NOT raise any of the 5 worker-only
    codes (guards against accidental routerization that would change
    the spec contract).
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
    ("post", "/api/v1/proposals/{proposal_id}/open_pr"),
    ("post", "/api/v1/config-repos"),
    ("get", "/api/v1/config-repos"),
    ("get", "/api/v1/config-repos/{config_repo_id}"),
}


# Spec §8.5 endpoint-visible codes raised by the routers for this feature.
ROUTER_VISIBLE_CODES = frozenset(
    {
        "PROPOSAL_NOT_FOUND",
        "INVALID_STATE_TRANSITION",
        "CLUSTER_HAS_NO_CONFIG_REPO",
        "GITHUB_NOT_CONFIGURED",
        "QUEUE_UNAVAILABLE",
        "UNSUPPORTED_PROVIDER",
        "AUTH_REF_NOT_FOUND",
        "CONFIG_REPO_NAME_TAKEN",
        "CONFIG_REPO_NOT_FOUND",
    }
)

# Spec §8.5 internal/worker-only terminal codes.
WORKER_ONLY_CODES = frozenset(
    {
        "PARAM_NOT_IN_TEMPLATE",
        "PARAMS_FILE_NOT_FOUND",
        "BRANCH_EXISTS",
        "GITHUB_API_FAILED",
        "CLONE_FAILED",
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
async def test_openapi_registers_all_four_endpoints(
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
async def test_open_pr_endpoint_response_model_is_open_pr_response(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/proposals/{proposal_id}/open_pr"]["post"]
    success = op["responses"]["202"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("OpenPrResponse"), ref


@_skip_if_no_pg
async def test_create_config_repo_response_model_is_config_repo_detail(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/config-repos"]["post"]
    success = op["responses"]["201"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ConfigRepoDetail"), ref


@_skip_if_no_pg
async def test_list_config_repos_response_model_is_list_response(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/config-repos"]["get"]
    success = op["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ConfigReposListResponse"), ref


@_skip_if_no_pg
async def test_config_repo_detail_response_model_is_config_repo_detail(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    schema = response.json()
    op = schema["paths"]["/api/v1/config-repos/{config_repo_id}"]["get"]
    success = op["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("ConfigRepoDetail"), ref


def test_router_source_contains_every_endpoint_visible_code() -> None:
    """Cycle-2 F4 / cycle-3 F1: router sources contain the 9 endpoint-visible codes.

    Codes may live in ``proposals.py`` (open_pr router shim), ``config_repos.py``
    (CRUD), or ``backend/app/services/agent_proposals_dispatch.py`` (the open_pr
    preflight lifted out by feat_chat_agent Story 2.4 so the chat-agent tool
    reuses the same checks). Concatenating these source files lets us audit
    the full feature surface in one grep.
    """
    proposals_src = Path("backend/app/api/v1/proposals.py").read_text(encoding="utf-8")
    config_repos_src = Path("backend/app/api/v1/config_repos.py").read_text(encoding="utf-8")
    dispatch_src = Path("backend/app/services/agent_proposals_dispatch.py").read_text(
        encoding="utf-8"
    )
    combined = proposals_src + "\n" + config_repos_src + "\n" + dispatch_src
    missing = [code for code in ROUTER_VISIBLE_CODES if code not in combined]
    assert not missing, f"router sources do not raise endpoint-visible codes: {missing}"


def test_router_source_does_not_raise_worker_only_codes() -> None:
    """Cycle-2 F4 / cycle-3 F1 negative: routers must not raise worker-only codes.

    Looks for the actual call shape ``_err(... "<CODE>" ...)`` — the
    router files may *reference* a worker code in a docstring (rare here)
    but must NOT raise it as an HTTP error envelope (would change the
    spec contract; worker codes are NOT endpoint-visible per spec §8.5).
    """
    proposals_src = Path("backend/app/api/v1/proposals.py").read_text(encoding="utf-8")
    config_repos_src = Path("backend/app/api/v1/config_repos.py").read_text(encoding="utf-8")
    combined = proposals_src + "\n" + config_repos_src
    leaked = [code for code in WORKER_ONLY_CODES if f'"{code}"' in combined]
    assert not leaked, (
        f"router sources RAISE worker-only codes (should stay in worker source): {leaked}"
    )


def test_worker_source_contains_every_worker_only_code() -> None:
    """Cycle-2 F4 / cycle-3 F1: worker source contains the 5 worker-only codes.

    Each MUST appear as a literal in the worker source (used in error
    strings written via ``_safe_set_pr_open_error`` or surfaced in
    structured ``event_type`` log lines). Allows missing codes to fail
    loudly at CI time rather than silently when an operator hits an
    edge case in production.
    """
    worker_path = Path("backend/workers/git_pr.py")
    source = worker_path.read_text(encoding="utf-8")
    missing = [code for code in WORKER_ONLY_CODES if code not in source]
    assert not missing, f"worker source missing internal/worker-only codes: {missing}"
