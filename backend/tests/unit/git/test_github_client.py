"""Unit tests for ``backend.app.git.github_client.github_request``.

Method-agnostic retry policy covered via ``httpx.MockTransport`` (the
established mocking pattern in this codebase — see
``backend/tests/unit/adapters/test_request_retry.py`` and
``backend/tests/unit/test_capability_check.py``). Tests are
parametrised over GET + POST so the method-agnostic generalisation
introduced by feat_github_webhook Story 1.5 is exercised on both verbs.

Asyncio sleeps are patched to ``0`` via the autouse ``_fast_sleep``
fixture so the retry loop is fast under pytest.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from backend.app.git.github_client import (
    HTTP_RETRY_MAX,
    github_request,
)

_TOKEN = "ghp_" + "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_METHODS = ("GET", "POST")


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch asyncio.sleep so retry-backoff waits don't slow the tests."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.git.github_client.asyncio.sleep", _instant)
    yield


def _make_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_returns_2xx_immediately(method: str) -> None:
    """Success path: a single 2xx response returns without retrying."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(
            client,
            method,
            "https://api.github.com/foo",
            json_body=None if method == "GET" else {"a": 1},
            token=_TOKEN,
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls["n"] == 1


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_5xx(method: str) -> None:
    """5xx triggers exponential backoff; eventual 2xx is returned."""
    statuses = iter([503, 502, 200])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), text="ok")

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(
            client,
            method,
            "https://api.github.com/foo",
            json_body=None,
            token=_TOKEN,
        )
    assert response.status_code == 200


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_429_then_returns(method: str) -> None:
    """429 with Retry-After is honoured (sleep is patched to 0)."""
    sequence = iter([429, 200])

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(sequence)
        if status == 429:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, text="recovered")

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(
            client,
            method,
            "https://api.github.com/foo",
            json_body=None,
            token=_TOKEN,
        )
    assert response.status_code == 200


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_403_with_retry_after(method: str) -> None:
    """403 carrying ``Retry-After`` is treated as a transient signal."""
    sequence = iter([403, 200])

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(sequence)
        if status == 403:
            return httpx.Response(403, headers={"retry-after": "0"}, text="slow down")
        return httpx.Response(200)

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 200


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_403_with_secondary_rate_limit(method: str) -> None:
    """403 with ``X-RateLimit-Remaining: 0`` retries until success."""
    sequence = iter([403, 200])

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(sequence)
        if status == 403:
            return httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"},
                text="",
            )
        return httpx.Response(200)

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 200


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_403_with_abuse_body(method: str) -> None:
    """403 whose body mentions ``rate limit`` retries via exponential backoff."""
    sequence = iter([403, 200])

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(sequence)
        if status == 403:
            return httpx.Response(
                403,
                text='{"message": "You have exceeded a secondary rate limit"}',
            )
        return httpx.Response(200)

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 200


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_returns_terminal_403_immediately(method: str) -> None:
    """403 with NO retry signal is terminal (PAT scope failure)."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, text="Resource not accessible by personal access token")

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 403
    assert calls["n"] == 1


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_returns_4xx_terminal_immediately(method: str) -> None:
    """4xx (other than 429/403-with-signal) is terminal."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="Not Found")

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 404
    assert calls["n"] == 1


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_retries_request_error_then_returns(method: str) -> None:
    """RequestError on first attempt + 2xx on the second succeeds."""
    state: dict[str, Any] = {"calls": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            raise httpx.ConnectError("transient network blip")
        return httpx.Response(200)

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 200
    assert state["calls"] == 2


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_propagates_request_error_after_budget(method: str) -> None:
    """RequestError on every attempt → final exception propagates."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with _make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.RequestError):
            await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_returns_last_5xx_after_budget_exhausted(method: str) -> None:
    """All attempts return 5xx → the last response is returned (not raised)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="server overloaded")

    async with _make_client(httpx.MockTransport(handler)) as client:
        response = await github_request(client, method, "https://api.github.com/foo", token=_TOKEN)
    assert response.status_code == 503


@pytest.mark.parametrize("method", _METHODS)
async def test_github_request_sends_token_and_version_headers(method: str) -> None:
    """Authorization Bearer + X-GitHub-Api-Version are set on every call."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        captured["api_version"] = request.headers.get("x-github-api-version", "")
        captured["accept"] = request.headers.get("accept", "")
        captured["method"] = request.method
        return httpx.Response(200)

    async with _make_client(httpx.MockTransport(handler)) as client:
        await github_request(
            client,
            method,
            "https://api.github.com/foo",
            json_body=None if method == "GET" else {"a": 1},
            token=_TOKEN,
        )
    assert captured["auth"] == f"Bearer {_TOKEN}"
    assert captured["api_version"] == "2022-11-28"
    assert captured["accept"] == "application/vnd.github+json"
    assert captured["method"] == method


def test_http_retry_max_is_three() -> None:
    """Sanity check: the retry budget aligns with the documented backoff schedule."""
    from backend.app.git.github_client import HTTP_RETRY_BACKOFF_S

    assert HTTP_RETRY_MAX == 3
    assert len(HTTP_RETRY_BACKOFF_S) == HTTP_RETRY_MAX
