# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``backend.workers.register_webhook.register_webhook``.

Mocks GitHub via :class:`httpx.MockTransport`. Asserts spec FR-3 ACs:

* AC-6 — happy path: no existing hook → 201 on POST →
  ``webhook_registration_error`` is NULL.
* AC-6 dedup — existing hook with matching ``config.url`` → no POST →
  error column NULL.
* AC-7 (404) — PAT scope failure → error column populated.
* AC-7 (422) — bad payload from GitHub → error column populated.
* AC-7 (5xx) — transient outage after retry budget → error column populated.
* AC-7 (network) — RequestError after retry budget → error column populated.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.git.github_client.asyncio.sleep", _instant)
    yield


@pytest.fixture(autouse=True)
def _relyloop_base_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The worker needs RELYLOOP_BASE_URL to build the GitHub-facing hook URL."""
    monkeypatch.setenv("RELYLOOP_BASE_URL", "https://relyloop.test")
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def register_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[str]:
    """Seed config_repo + mounted PAT + webhook secret. Yield config_repo id."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    pat_ref = f"pat-{uuid.uuid4().hex[:8]}"
    secret_ref = f"hook-{uuid.uuid4().hex[:8]}"
    (secrets_dir / pat_ref).write_text("ghp_" + "B" * 40 + "\n")
    (secrets_dir / secret_ref).write_text("secret-content\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-{uuid.uuid4().hex[:8]}",
            provider="github",
            repo_url="https://github.com/example/configs",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=pat_ref,
            webhook_secret_ref=secret_ref,
        )
        await db.commit()
        cr_id = cr.id
    yield cr_id


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    import httpx as httpx_module

    original = httpx_module.AsyncClient

    def _factory(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        kwargs["transport"] = handler
        return original(*args, **kwargs)

    monkeypatch.setattr("backend.workers.register_webhook.httpx.AsyncClient", _factory)


async def _read_error_column(config_repo_id: str) -> str | None:
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_config_repo(db, config_repo_id)
    assert row is not None
    return row.webhook_registration_error


async def test_register_webhook_happy_path_creates_hook(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6 — no existing hook → 201 → error column NULL."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": 42})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "created"}
    assert await _read_error_column(register_env) is None


async def test_register_webhook_dedup_existing(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6 dedup — existing hook with matching config.url → no POST → NULL error."""
    captured: dict[str, int] = {"posts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "config": {"url": "https://relyloop.test/webhooks/github"},
                    }
                ],
            )
        captured["posts"] += 1
        return httpx.Response(201)

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "exists"}
    assert captured["posts"] == 0
    assert await _read_error_column(register_env) is None


async def test_register_webhook_404_populates_error(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7 — POST returns 404 → error column populated with PAT-scope message."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(404, text="Not Found")

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "failed"}
    error = await _read_error_column(register_env)
    assert error is not None and "admin:repo_hook" in error


async def test_register_webhook_422_populates_error(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7 — POST returns 422 → error column populated with validation message."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(422, json={"message": "Validation failed"})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "failed"}
    error = await _read_error_column(register_env)
    assert error is not None and "422" in error


async def test_register_webhook_5xx_populates_error(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7 — POST returns 503 after retries → error column populated."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(503, text="server overloaded")

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "failed"}
    error = await _read_error_column(register_env)
    assert error is not None and "transient" in error.lower()


async def test_register_webhook_network_error_populates_error(
    register_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7 — RequestError after retries → error column populated."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.register_webhook import register_webhook

    result = await register_webhook({}, register_env)
    assert result == {"status": "failed"}
    error = await _read_error_column(register_env)
    assert error is not None and "network" in error.lower()
