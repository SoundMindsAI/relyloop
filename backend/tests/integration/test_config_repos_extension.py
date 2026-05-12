"""Integration tests for ``POST /api/v1/config-repos`` Story 4.2 extension.

The existing endpoint behavior (response shape, 201 status, preflight
error codes) is unchanged. This file covers the NEW post-commit
best-effort enqueue of ``register_webhook``:

* Existing happy-path response shape preserved.
* ``webhook_secret_ref`` populated → ``enqueue_job`` called once.
* ``webhook_secret_ref`` NULL → enqueue NOT called.
* ``app.state.arq_pool`` absent → 201 still returned, WARN logged with
  ``register_webhook_enqueue_skipped_no_pool``.
* ``enqueue_job`` raises → 201 still returned, WARN logged with
  ``register_webhook_enqueue_failed``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


@pytest_asyncio.fixture
async def secrets_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[Path]:
    """Provide a writable secrets dir + pre-create auth_ref and webhook_secret_ref."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))
    yield secrets_dir


def _create_body(*, name: str, with_webhook_secret: bool, secrets_dir: Path) -> dict[str, str]:
    """Return a config-repo create payload, optionally with webhook_secret_ref.

    Side effect: writes the referenced secret files into ``secrets_dir`` so
    the AUTH_REF_NOT_FOUND preflight passes.
    """
    auth_ref = f"pat-{uuid.uuid4().hex[:8]}"
    (secrets_dir / auth_ref).write_text("placeholder")
    body: dict[str, str] = {
        "name": name,
        "repo_url": "https://github.com/example/repo",
        "auth_ref": auth_ref,
        "default_branch": "main",
        "pr_base_branch": "main",
    }
    if with_webhook_secret:
        webhook_ref = f"hook-{uuid.uuid4().hex[:8]}"
        (secrets_dir / webhook_ref).write_text("hookcontent")
        body["webhook_secret_ref"] = webhook_ref
    return body


async def test_post_config_repo_response_shape_unchanged(
    async_client: httpx.AsyncClient,
    secrets_dir: Path,
) -> None:
    """Happy path: 201 + the documented ConfigRepoDetail fields."""
    body = _create_body(
        name=f"cr-shape-{uuid.uuid4().hex[:6]}",
        with_webhook_secret=False,
        secrets_dir=secrets_dir,
    )
    response = await async_client.post("/api/v1/config-repos", json=body)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["name"] == body["name"]
    assert payload["provider"] == "github"
    assert payload["repo_url"] == body["repo_url"]
    assert payload["webhook_secret_ref"] is None
    assert payload["webhook_registration_error"] is None


async def test_post_config_repo_with_secret_enqueues_register_webhook(
    async_client: httpx.AsyncClient,
    secrets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """webhook_secret_ref populated → enqueue_job called with register_webhook."""
    from backend.app.main import app

    enqueue = AsyncMock()
    pool_stub = type("PoolStub", (), {"enqueue_job": enqueue})()
    monkeypatch.setattr(app.state, "arq_pool", pool_stub, raising=False)

    body = _create_body(
        name=f"cr-enqueued-{uuid.uuid4().hex[:6]}",
        with_webhook_secret=True,
        secrets_dir=secrets_dir,
    )
    response = await async_client.post("/api/v1/config-repos", json=body)
    assert response.status_code == 201

    enqueue.assert_awaited_once()
    args, kwargs = enqueue.call_args
    assert args[0] == "register_webhook"
    assert isinstance(args[1], str)
    assert kwargs.get("_job_id", "").startswith("register_webhook:")


async def test_post_config_repo_without_secret_does_not_enqueue(
    async_client: httpx.AsyncClient,
    secrets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """webhook_secret_ref NULL → enqueue NOT called."""
    from backend.app.main import app

    enqueue = AsyncMock()
    pool_stub = type("PoolStub", (), {"enqueue_job": enqueue})()
    monkeypatch.setattr(app.state, "arq_pool", pool_stub, raising=False)

    body = _create_body(
        name=f"cr-no-hook-{uuid.uuid4().hex[:6]}",
        with_webhook_secret=False,
        secrets_dir=secrets_dir,
    )
    response = await async_client.post("/api/v1/config-repos", json=body)
    assert response.status_code == 201
    enqueue.assert_not_awaited()


async def test_post_config_repo_pool_absent_still_returns_201(
    async_client: httpx.AsyncClient,
    secrets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pool absent → 201 + WARN with register_webhook_enqueue_skipped_no_pool."""
    from backend.app.main import app

    # Force pool absent.
    monkeypatch.delattr(app.state, "arq_pool", raising=False)

    caplog.set_level(logging.WARNING, logger="backend.app.api.v1.config_repos")
    body = _create_body(
        name=f"cr-no-pool-{uuid.uuid4().hex[:6]}",
        with_webhook_secret=True,
        secrets_dir=secrets_dir,
    )
    response = await async_client.post("/api/v1/config-repos", json=body)
    assert response.status_code == 201
    # structlog → stdlib logging; caplog captures the event name in the message body.
    log_messages = [record.getMessage() for record in caplog.records]
    assert any("register_webhook_enqueue_skipped_no_pool" in msg for msg in log_messages), (
        f"missing skipped-no-pool log; saw: {log_messages}"
    )


async def test_post_config_repo_enqueue_raises_still_returns_201(
    async_client: httpx.AsyncClient,
    secrets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """enqueue_job raises → 201 still returned + WARN logged."""
    from backend.app.main import app

    async def _raises(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("redis unreachable")

    pool_stub = type("PoolStub", (), {"enqueue_job": _raises})()
    monkeypatch.setattr(app.state, "arq_pool", pool_stub, raising=False)

    caplog.set_level(logging.WARNING, logger="backend.app.api.v1.config_repos")
    body = _create_body(
        name=f"cr-enqueue-raises-{uuid.uuid4().hex[:6]}",
        with_webhook_secret=True,
        secrets_dir=secrets_dir,
    )
    response = await async_client.post("/api/v1/config-repos", json=body)
    assert response.status_code == 201
    log_messages = [record.getMessage() for record in caplog.records]
    assert any("register_webhook_enqueue_failed" in msg for msg in log_messages), (
        f"missing enqueue-failed log; saw: {log_messages}"
    )


def test_endpoint_source_does_not_use_get_arq_pool_factory() -> None:
    """Static grep: no Depends(get_arq_pool) — that factory doesn't exist.

    The established pattern is ``getattr(request.app.state, "arq_pool", None)``.
    This guard catches future drift if anyone tries to wire a Depends-based
    factory that doesn't exist anywhere in the codebase.
    """
    source = Path("backend/app/api/v1/config_repos.py").read_text()
    assert "get_arq_pool" not in source
