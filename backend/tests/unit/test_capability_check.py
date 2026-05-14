"""Capability-check unit tests (infra_foundation Story 3.3 / FR-7).

Mocks ``httpx.AsyncClient`` to exercise every probe outcome:

- All four probes succeed → ``CapabilityResult`` all-ok
- Models endpoint fails → downstream probes reported as ``"untested"``
- Chat / FC / structured-output failures (HTTP 4xx) → corresponding field
  ``"fail"``
- Network timeout → field ``"fail"``; logged at WARN
- ``api_key`` empty → background runner skips entirely (no Redis writes)

Verifies:

- Redis ``set`` is called with the 24h TTL key and ``model_dump_json()`` body.
- WARN-level structured log emitted on any probe failure.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import structlog
from redis.asyncio import Redis

from backend.app.llm.capability_check import (
    CACHE_TTL_SECONDS,
    cache_key,
    check_capabilities,
    run_capability_check_background,
)
from backend.app.llm.capability_models import CapabilityResult
from backend.tests._log_helpers import assert_log_level

BASE_URL = "https://api.openai.com/v1"
MODEL = "gpt-4o-2024-08-06"
API_KEY = "sk-test-key"


# ---------------------------------------------------------------------------
# httpx mock helpers
# ---------------------------------------------------------------------------


def _ok_models_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"id": "gpt-4o"}]},
        request=request,
    )


def _ok_chat_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        request=request,
    )


def _ok_function_calling_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "echo",
                                    "arguments": json.dumps({"text": "hello"}),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        request=request,
    )


def _ok_structured_output_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": json.dumps({"value": 42})}}]
        },
        request=request,
    )


def _build_handler(
    *,
    models_status: int = 200,
    chat_status: int = 200,
    fc_status: int = 200,
    structured_status: int = 200,
    chat_body: dict[str, Any] | None = None,
    fc_body: dict[str, Any] | None = None,
    structured_body: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    """Return a MockTransport that routes by URL path + payload shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            if models_status != 200:
                return httpx.Response(models_status, json={"error": "x"}, request=request)
            return _ok_models_response(request)

        # All chat/completions calls — distinguish by payload.
        body = json.loads(request.content) if request.content else {}
        if "tools" in body:
            if fc_status != 200:
                return httpx.Response(fc_status, json={"error": "x"}, request=request)
            if fc_body is not None:
                return httpx.Response(200, json=fc_body, request=request)
            return _ok_function_calling_response(request)
        if "response_format" in body:
            if structured_status != 200:
                return httpx.Response(structured_status, json={"error": "x"}, request=request)
            if structured_body is not None:
                return httpx.Response(200, json=structured_body, request=request)
            return _ok_structured_output_response(request)
        # Plain chat completion.
        if chat_status != 200:
            return httpx.Response(chat_status, json={"error": "x"}, request=request)
        if chat_body is not None:
            return httpx.Response(200, json=chat_body, request=request)
        return _ok_chat_response(request)

    return httpx.MockTransport(handler)


def _make_redis() -> MagicMock:
    """Mock ``redis.asyncio.Redis`` with awaitable ``set``."""
    client = MagicMock(spec=Redis)
    client.set = AsyncMock(return_value=True)
    return client


# ---------------------------------------------------------------------------
# Happy path — all probes succeed
# ---------------------------------------------------------------------------


class TestAllProbesOk:
    async def test_all_four_probes_succeed_returns_ok_result(self) -> None:
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler()) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "ok"
        assert result.chat_completion == "ok"
        assert result.function_calling == "ok"
        assert result.structured_output == "ok"
        assert result.base_url == BASE_URL
        assert result.model == MODEL

    async def test_redis_set_called_with_24h_ttl(self) -> None:
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler()) as http:
            await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        redis.set.assert_awaited_once()
        call = redis.set.call_args
        assert call.args[0] == cache_key(BASE_URL)
        # Body is JSON-serialized CapabilityResult
        body = json.loads(call.args[1])
        assert body["base_url"] == BASE_URL
        assert body["models_endpoint"] == "ok"
        assert call.kwargs.get("ex") == CACHE_TTL_SECONDS == 86_400


# ---------------------------------------------------------------------------
# Models endpoint failure short-circuits downstream probes
# ---------------------------------------------------------------------------


class TestModelsEndpointFailure:
    async def test_models_failure_marks_downstream_untested(self) -> None:
        redis = _make_redis()
        transport = _build_handler(models_status=503)
        # `structlog.testing.capture_logs()` swaps the active processor chain
        # for one that appends every event to a list — invariant under
        # `cache_logger_on_first_use=True` and stdout/stderr re-binding.
        # capsys couldn't capture these because the cached PrintLogger holds
        # a stale stdout reference from before pytest's capture started.
        # (bug_capability_check_test_isolation idea.)
        with structlog.testing.capture_logs() as captured:
            async with httpx.AsyncClient(transport=transport) as http:
                result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.chat_completion == "untested"
        assert result.function_calling == "untested"
        assert result.structured_output == "untested"
        # Verify the WARN was emitted with the structured `step` field.
        # Filter by the structured `step` field first (key-name stable across
        # structlog versions), then assert level via the tolerant helper.
        step_events = [e for e in captured if e.get("step") == "models_endpoint"]
        assert step_events, captured
        for entry in step_events:
            assert_log_level(entry, "warning")


# ---------------------------------------------------------------------------
# Per-probe failure cases (chat / FC / structured)
# ---------------------------------------------------------------------------


class TestPerProbeFailures:
    async def test_chat_completion_4xx_marks_chat_fail(self) -> None:
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler(chat_status=429)) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "ok"
        assert result.chat_completion == "fail"
        # Subsequent probes still run — they're independent capability surfaces
        assert result.function_calling == "ok"
        assert result.structured_output == "ok"

    async def test_function_calling_failure_marks_fc_fail(self) -> None:
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler(fc_status=400)) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.function_calling == "fail"
        assert result.chat_completion == "ok"
        assert result.structured_output == "ok"

    async def test_function_calling_response_missing_tool_calls(self) -> None:
        redis = _make_redis()
        # Successful HTTP 200 but no tool_calls in the message
        bad_fc_body = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        transport = _build_handler(fc_body=bad_fc_body)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.function_calling == "fail"

    async def test_structured_output_failure_marks_struct_fail(self) -> None:
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler(structured_status=500)) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.structured_output == "fail"

    async def test_structured_output_returning_non_json_marks_fail(self) -> None:
        redis = _make_redis()
        bad_struct = {"choices": [{"message": {"role": "assistant", "content": "not-json"}}]}
        transport = _build_handler(structured_body=bad_struct)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.structured_output == "fail"

    async def test_chat_response_missing_message_marks_fail(self) -> None:
        redis = _make_redis()
        bad_chat: dict[str, Any] = {"choices": []}
        transport = _build_handler(chat_body=bad_chat)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.chat_completion == "fail"


# ---------------------------------------------------------------------------
# Network errors (timeout, connection refused) — all reported as fail
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    async def test_models_timeout_reported_as_fail(self) -> None:
        redis = _make_redis()

        def _raise(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("simulated timeout")

        transport = httpx.MockTransport(_raise)
        with structlog.testing.capture_logs() as captured:
            async with httpx.AsyncClient(transport=transport) as http:
                result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.chat_completion == "untested"
        # Pin the WARN: same step + the simulated-timeout error text from the
        # `error` kwarg passed to logger.warning(...). Filter by the
        # structured `step` field, then assert level via the tolerant helper.
        step_events = [e for e in captured if e.get("step") == "models_endpoint"]
        assert step_events, captured
        for entry in step_events:
            assert_log_level(entry, "warning")
        assert any("simulated timeout" in str(e.get("error", "")) for e in step_events), step_events

    async def test_redis_set_failure_does_not_raise(self) -> None:
        redis = _make_redis()
        redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
        # check_capabilities must still return a valid result
        async with httpx.AsyncClient(transport=_build_handler()) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert isinstance(result, CapabilityResult)
        assert result.models_endpoint == "ok"


# ---------------------------------------------------------------------------
# Background runner skip-on-no-key
# ---------------------------------------------------------------------------


class TestBackgroundRunner:
    async def test_no_api_key_skips_entirely(self) -> None:
        redis = _make_redis()
        await run_capability_check_background(BASE_URL, None, MODEL, redis)
        # No Redis writes when there's no key
        redis.set.assert_not_called()

    async def test_empty_api_key_skips_entirely(self) -> None:
        redis = _make_redis()
        await run_capability_check_background(BASE_URL, "", MODEL, redis)
        redis.set.assert_not_called()

    async def test_runner_swallows_unexpected_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Runner must NEVER crash the API process on capability-check failure."""
        from backend.app.llm import capability_check as cc

        async def _boom(*_args: Any, **_kwargs: Any) -> CapabilityResult:
            raise RuntimeError("synthetic")

        monkeypatch.setattr(cc, "check_capabilities", _boom)
        redis = _make_redis()
        # No assertion on result — we're verifying no exception escapes
        await run_capability_check_background(BASE_URL, API_KEY, MODEL, redis)


# ---------------------------------------------------------------------------
# cache_key is stable + sha256-based
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_cache_key_format_and_stability(self) -> None:
        key1 = cache_key(BASE_URL)
        key2 = cache_key(BASE_URL)
        assert key1 == key2
        assert key1.startswith("openai:capabilities:")
        # sha256 hex digest is 64 chars
        assert len(key1.split(":", 2)[-1]) == 64

    def test_different_base_urls_produce_different_keys(self) -> None:
        assert cache_key("http://a/v1") != cache_key("http://b/v1")
