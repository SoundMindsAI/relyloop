"""Contract assertions for the GitHub webhook receiver (Story 2.1).

* The endpoint is registered in the OpenAPI schema under
  ``POST /webhooks/github``.
* The router source re-exports ``WEBHOOK_ACTION_VALUES`` so spec §8.4's
  grep cite at ``backend/app/api/webhooks/github.py`` passes.
* The only error code raised by the router is ``INVALID_SIGNATURE``
  (negative grep against the spec §8.5 catalog — no PROPOSAL_NOT_FOUND,
  CONFIG_REPO_NOT_FOUND, INVALID_STATE_TRANSITION, etc., leak through).
* No log call site in the router accepts the webhook secret value
  (negative grep — defense-in-depth against future log-line drift).
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
    reason="Postgres not reachable — webhook router resolves get_db dependency at boot",
)


_ROUTER_SOURCE = Path(__file__).resolve().parents[2] / "app" / "api" / "webhooks" / "github.py"


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=10.0,
        ) as client:
            yield client


@_skip_if_no_pg
async def test_webhook_endpoint_registered(async_client: httpx.AsyncClient) -> None:
    """``POST /webhooks/github`` appears in the OpenAPI schema."""
    response = await async_client.get("/openapi.json")
    schema = response.json()
    assert "/webhooks/github" in schema["paths"], (
        f"webhook endpoint missing from OpenAPI; got paths={list(schema['paths'])[:10]}"
    )
    assert "post" in schema["paths"]["/webhooks/github"]


def test_router_source_re_exports_action_values() -> None:
    """Spec §8.4 grep cite at the router path must find WEBHOOK_ACTION_VALUES."""
    text = _ROUTER_SOURCE.read_text()
    assert "WEBHOOK_ACTION_VALUES" in text, (
        "Router source must re-export WEBHOOK_ACTION_VALUES so spec §8.4's grep "
        "cite at backend/app/api/webhooks/github.py succeeds."
    )


def test_router_source_raises_only_invalid_signature() -> None:
    """Negative-grep: the router must NOT raise any non-INVALID_SIGNATURE error_code.

    Asserts only ``INVALID_SIGNATURE`` appears as an ``error_code=`` literal
    inside the router source. If a future change adds a different code
    (e.g. PROPOSAL_NOT_FOUND), the contract test catches it before merge.
    """
    text = _ROUTER_SOURCE.read_text()
    other_codes = (
        "PROPOSAL_NOT_FOUND",
        "INVALID_STATE_TRANSITION",
        "CLUSTER_HAS_NO_CONFIG_REPO",
        "GITHUB_NOT_CONFIGURED",
        "VALIDATION_ERROR",
        "RESOURCE_NOT_FOUND",
        "CONFIG_REPO_NOT_FOUND",
        "UNSUPPORTED_PROVIDER",
        "AUTH_REF_NOT_FOUND",
        "QUEUE_UNAVAILABLE",
    )
    for code in other_codes:
        assert code not in text, (
            f"Router source must not raise {code!r}; only INVALID_SIGNATURE is "
            "the spec §8.5 contract for the webhook receiver."
        )
    assert "INVALID_SIGNATURE" in text


def test_router_source_does_not_log_webhook_secret() -> None:
    """Static grep: no log call site references the secret content.

    The router reads the secret via ``read_mounted_secret(...)`` into a
    local ``secret`` variable. That variable must never appear inside a
    log call. Conservative regex match: any call ``logger.<level>(...)``
    whose argument list contains the bareword ``secret``.
    """
    text = _ROUTER_SOURCE.read_text()
    log_calls = re.findall(r"logger\.\w+\([^)]*\)", text, flags=re.DOTALL)
    for call in log_calls:
        # The webhook_secret_ref column NAME is fine to log if it ever became
        # useful for debugging — only the secret content is forbidden. The
        # check rejects bareword ``secret`` (the local variable), allowing
        # ``webhook_secret_ref`` as a substring.
        assert not re.search(r"\bsecret\b(?!_ref)", call), (
            f"Log call leaks webhook secret: {call!r}"
        )
