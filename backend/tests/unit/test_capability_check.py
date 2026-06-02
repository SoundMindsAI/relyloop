# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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

import asyncio
import json
from datetime import UTC, datetime
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
    read_or_recompute_capability_result,
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
# models_endpoint_status_code — surfaces the HTTP status on probe failure
# (bug_openai_capability_check_incapable_on_valid_key, Story 1.2 / AC-3..AC-5/AC-8)
# ---------------------------------------------------------------------------


class TestModelsEndpointStatusCode:
    async def test_http_401_captures_status_code(self) -> None:
        """AC-3: bad-key returns models_endpoint='fail' + status_code=401."""
        redis = _make_redis()
        transport = _build_handler(models_status=401)
        with structlog.testing.capture_logs() as captured:
            async with httpx.AsyncClient(transport=transport) as http:
                result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.models_endpoint_status_code == 401
        assert result.chat_completion == "untested"
        # WARN log MUST carry the structured `status_code` field per cycle-1 B3.
        step_events = [e for e in captured if e.get("step") == "models_endpoint"]
        assert step_events, captured
        for entry in step_events:
            assert_log_level(entry, "warning")
        assert any(e.get("status_code") == 401 for e in step_events), step_events

    async def test_http_429_captures_status_code(self) -> None:
        """Rate-limited case — operator can distinguish from auth failure."""
        redis = _make_redis()
        transport = _build_handler(models_status=429)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.models_endpoint_status_code == 429

    async def test_http_500_captures_status_code(self) -> None:
        """Upstream-outage case — operator can distinguish from local config issues."""
        redis = _make_redis()
        transport = _build_handler(models_status=500)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.models_endpoint_status_code == 500

    async def test_network_error_reports_none_status_code(self) -> None:
        """AC-4: network-class failure (httpx.HTTPError) yields models_endpoint='fail' + None."""
        redis = _make_redis()

        def _raise(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated DNS failure")

        transport = httpx.MockTransport(_raise)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "fail"
        assert result.models_endpoint_status_code is None

    async def test_success_path_reports_none_status_code(self) -> None:
        """AC-5: status_code stays None on the happy path (no 200 noise)."""
        redis = _make_redis()
        async with httpx.AsyncClient(transport=_build_handler()) as http:
            result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)
        assert result.models_endpoint == "ok"
        assert result.models_endpoint_status_code is None

    def test_pre_fix_cached_row_deserializes_with_status_code_none(self) -> None:
        """AC-8: a CapabilityResult JSON serialized before this fix (no
        ``models_endpoint_status_code`` key) deserializes cleanly with the
        new field defaulting to None.
        """
        legacy_json = json.dumps(
            {
                "base_url": BASE_URL,
                "model": MODEL,
                "models_endpoint": "ok",
                "chat_completion": "ok",
                "function_calling": "ok",
                "structured_output": "ok",
                "tested_at": "2026-05-09T12:00:00Z",
            }
        )
        result = CapabilityResult.model_validate_json(legacy_json)
        assert result.models_endpoint == "ok"
        assert result.models_endpoint_status_code is None


# ---------------------------------------------------------------------------
# AC-10 — security redaction (cache layer)
# (bug_openai_capability_check_incapable_on_valid_key, Story 1.2)
# ---------------------------------------------------------------------------


class TestSecurityRedaction:
    """The integer HTTP status code MAY be cached/logged; the response body MUST NOT.

    OpenAI 401 bodies quote the bad bearer token back (e.g.
    ``{"error":{"message":"Invalid Bearer token: sk-..."}}``). Surfacing the
    body in CapabilityResult/Redis/logs would leak the secret to anyone
    polling /healthz or tailing api logs. CLAUDE.md Absolute Rule #10 +
    feature_spec.md AC-10.
    """

    FORBIDDEN_TOKEN_TEXT = "Invalid Bearer token: sk-redacted-token-abc"
    FORBIDDEN_TOKEN_FRAGMENT = "sk-redacted-token-abc"

    async def test_401_body_does_not_leak_into_cache_or_logs(self) -> None:
        redis = _make_redis()

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/models")
            # Body literally contains the secret-like token that we MUST redact.
            return httpx.Response(
                401,
                json={"error": {"message": self.FORBIDDEN_TOKEN_TEXT}},
                request=request,
            )

        transport = httpx.MockTransport(handler)
        with structlog.testing.capture_logs() as captured:
            async with httpx.AsyncClient(transport=transport) as http:
                result = await check_capabilities(BASE_URL, API_KEY, MODEL, redis, http_client=http)

        # Positive case: integer status code IS captured for the operator's diagnostic.
        assert result.models_endpoint_status_code == 401

        # Negative case: neither the cached JSON nor structlog contains the body.
        cached_json = result.model_dump_json()
        assert "Invalid Bearer token" not in cached_json, cached_json
        assert self.FORBIDDEN_TOKEN_FRAGMENT not in cached_json, cached_json

        # Capture every structlog event's stringified form (covers all fields,
        # not just `message`).
        log_blob = "".join(repr(e) for e in captured)
        assert "Invalid Bearer token" not in log_blob, log_blob
        assert self.FORBIDDEN_TOKEN_FRAGMENT not in log_blob, log_blob

        # WARN-level event for step=models_endpoint MUST exist with status_code=401.
        step_events = [e for e in captured if e.get("step") == "models_endpoint"]
        assert step_events, captured
        for entry in step_events:
            assert_log_level(entry, "warning")
        assert any(e.get("status_code") == 401 for e in step_events), step_events

        # Sanity check: the value the Redis mock received is also clean.
        cached_arg = redis.set.call_args.args[1]
        assert "Invalid Bearer token" not in cached_arg, cached_arg
        assert self.FORBIDDEN_TOKEN_FRAGMENT not in cached_arg, cached_arg


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


# ---------------------------------------------------------------------------
# bug_llm_capability_cache_no_refresh regression guard
# ---------------------------------------------------------------------------


def _make_redis_with_get(cached_raw: bytes | str | None) -> MagicMock:
    """Mock ``redis.asyncio.Redis`` with awaitable ``get`` + ``set``.

    ``cached_raw`` is what ``redis.get(cache_key)`` returns:
    - ``None`` → cache miss (the bug's failure mode).
    - ``bytes`` / ``str`` → cache hit, decoded as a ``CapabilityResult`` JSON.
    """
    client = MagicMock(spec=Redis)
    client.get = AsyncMock(return_value=cached_raw)
    client.set = AsyncMock(return_value=True)
    return client


class TestReadOrRecomputeCapabilityResult:
    """Regression guard for ``bug_llm_capability_cache_no_refresh``.

    The 24h ``CACHE_TTL_SECONDS`` TTL passes; nothing repopulates the
    cache; LLM-gated endpoints return 503 ``LLM_PROVIDER_INCAPABLE``
    until the api process restarts. ``read_or_recompute_capability_result``
    closes the gap by recomputing on miss inline.
    """

    async def test_cache_miss_with_api_key_recomputes_and_writes_back(
        self,
    ) -> None:
        """The bug's exact failure mode: cache empty, key configured.

        With the old ``read_capability_result``, this returned ``None``
        and the preflight raised ``LLM_PROVIDER_INCAPABLE``. The helper
        must instead probe inline, return a real ``CapabilityResult``,
        and write the result back to Redis (re-arming the cache).
        """
        redis = _make_redis_with_get(cached_raw=None)
        async with httpx.AsyncClient(transport=_build_handler()) as http:
            result = await read_or_recompute_capability_result(
                redis, BASE_URL, API_KEY, MODEL, http_client=http
            )
        assert result is not None, (
            "cache miss with a configured api_key MUST recompute, not return None"
        )
        assert result.base_url == BASE_URL
        assert result.model == MODEL
        # check_capabilities writes back as a side effect:
        redis.set.assert_awaited_once()
        write_call = redis.set.call_args
        assert write_call.args[0] == cache_key(BASE_URL)
        # And the TTL is the same 24h we started with — no silent change.
        assert write_call.kwargs.get("ex") == CACHE_TTL_SECONDS

    async def test_cache_hit_returns_cached_value_without_reprobing(
        self,
    ) -> None:
        """Cache-hit path: helper short-circuits before any HTTP work.

        Critical: we MUST NOT add latency to steady-state dispatches.
        The bug is about cold-expiry recovery, not about re-probing on
        every read.
        """
        # Pre-populate the cache with a known-good result.
        cached_result = CapabilityResult(
            base_url=BASE_URL,
            model=MODEL,
            models_endpoint="ok",
            chat_completion="ok",
            function_calling="ok",
            structured_output="ok",
            tested_at=datetime.now(UTC),
        )
        redis = _make_redis_with_get(cached_raw=cached_result.model_dump_json())
        # Use a transport that raises on ANY HTTP call — proves no probe fires.

        def _explode(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                f"cache-hit path made an HTTP request to {request.url} — "
                "helper should have short-circuited",
            )

        transport = httpx.MockTransport(_explode)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await read_or_recompute_capability_result(
                redis, BASE_URL, API_KEY, MODEL, http_client=http
            )
        assert result is not None
        assert result.structured_output == "ok"
        # And critically, no write either — we returned the cached row as-is.
        redis.set.assert_not_awaited()

    async def test_cache_miss_with_empty_api_key_returns_none(self) -> None:
        """Empty-key contract preserved.

        Consumers like ``/healthz`` rely on ``None`` to surface
        ``OPENAI_API_KEY_FILE`` being unset as a distinct degraded
        state from an unreachable endpoint. The helper MUST NOT
        attempt a probe with an empty key (which would fail
        spuriously and write a confusing ``models_endpoint="fail"``
        row to Redis).
        """
        redis = _make_redis_with_get(cached_raw=None)

        def _explode(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                f"empty-key path made an HTTP request to {request.url} — "
                "helper should have returned None without probing",
            )

        transport = httpx.MockTransport(_explode)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await read_or_recompute_capability_result(
                redis, BASE_URL, "", MODEL, http_client=http
            )
        assert result is None, (
            "empty api_key MUST return None to preserve "
            "read_capability_result's 'no key, no capability' semantic"
        )
        redis.set.assert_not_awaited()

    async def test_cache_miss_with_check_capabilities_raising_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Defensive failure mode: unexpected exception inside the
        recompute path returns ``None`` instead of bubbling as a 500.

        ``check_capabilities`` is documented as "never raises" but
        ``run_capability_check_background`` defensively wraps it
        anyway. The helper matches that posture so the caller's
        existing cap-miss path (→ 503 LLM_PROVIDER_INCAPABLE for the
        judgments dispatcher) still fires, rather than producing a
        bare 500 from an unhandled exception.

        Regression guard for GPT-5.5 final review finding #2 on PR #426.
        """
        from backend.app.llm import capability_check as cc

        redis = _make_redis_with_get(cached_raw=None)

        async def _raising_check_capabilities(*args: Any, **kwargs: Any) -> CapabilityResult:
            raise RuntimeError("simulated upstream failure during recompute")

        monkeypatch.setattr(cc, "check_capabilities", _raising_check_capabilities)

        result = await read_or_recompute_capability_result(redis, BASE_URL, API_KEY, MODEL)
        assert result is None, (
            "an unexpected exception during recompute MUST surface as None "
            "(cap-miss path) — never bubble up as 500"
        )

    async def test_concurrent_requests_on_one_worker_collapse_to_single_probe(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Single-flight: 10 concurrent recompute callers fire 1 probe.

        Without the per-worker ``_RECOMPUTE_LOCK``, every coroutine that
        observes the cache miss between read and write would fire its
        own ``check_capabilities`` call (the GPT-5.5 final review on
        PR #426 caught this — the original D-4 bound of
        ``WEB_CONCURRENCY × probes`` undercounted concurrent in-worker
        requests).

        With the lock + the in-lock double-checked read, only one
        coroutine actually probes; the others see the populated cache
        on their second read and short-circuit.
        """
        from backend.app.llm import capability_check as cc

        probe_calls = 0
        # The "cache" is a single mutable container — the first probe
        # populates it, subsequent reads return the populated value.
        cache_state: list[CapabilityResult | None] = [None]

        async def _counting_check_capabilities(
            base_url: str,
            api_key: str,
            model: str,
            redis_client: Redis,
            *,
            http_client: httpx.AsyncClient | None = None,
        ) -> CapabilityResult:
            nonlocal probe_calls
            probe_calls += 1
            result = CapabilityResult(
                base_url=base_url,
                model=model,
                models_endpoint="ok",
                chat_completion="ok",
                function_calling="ok",
                structured_output="ok",
                tested_at=datetime.now(UTC),
            )
            # Yield to give concurrent waiters a chance to interleave.
            await asyncio.sleep(0)
            cache_state[0] = result
            return result

        async def _stateful_read_capability_result(
            redis_client: Redis, base_url: str
        ) -> CapabilityResult | None:
            return cache_state[0]

        monkeypatch.setattr(cc, "check_capabilities", _counting_check_capabilities)
        monkeypatch.setattr(cc, "read_capability_result", _stateful_read_capability_result)

        redis = _make_redis_with_get(cached_raw=None)
        results = await asyncio.gather(
            *[
                read_or_recompute_capability_result(redis, BASE_URL, API_KEY, MODEL)
                for _ in range(10)
            ]
        )

        assert probe_calls == 1, (
            f"single-flight lock MUST collapse 10 concurrent recompute "
            f"callers to 1 probe; got {probe_calls}"
        )
        assert all(r is not None for r in results), (
            "all 10 callers MUST receive the recomputed CapabilityResult"
        )
        assert all(r.structured_output == "ok" for r in results if r is not None)

    async def test_cache_miss_with_none_api_key_returns_none(self) -> None:
        """Type-level: api_key is annotated as `str | None`. The internal
        check `if not api_key` handles both ``None`` and ``""`` —
        regression guard so a caller can pass `settings.openai_api_key`
        directly (which is `str | None` in the Settings model) without
        the ``or ""`` boilerplate.

        Regression guard for Gemini Code Assist finding #1 on PR #426.
        """
        redis = _make_redis_with_get(cached_raw=None)

        def _explode(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                f"None-api_key path made an HTTP request to {request.url} — "
                "helper should have returned None without probing",
            )

        transport = httpx.MockTransport(_explode)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await read_or_recompute_capability_result(
                redis, BASE_URL, None, MODEL, http_client=http
            )
        assert result is None
        redis.set.assert_not_called()

    async def test_cache_hit_with_degraded_result_is_returned_as_is(
        self,
    ) -> None:
        """Cache-hit short-circuit applies even when the cached row is
        degraded (e.g., ``structured_output="fail"``). The preflight's
        per-field policy continues to decide whether to refuse; the
        helper does NOT re-probe a known-degraded row hoping it
        recovered.
        """
        cached_result = CapabilityResult(
            base_url=BASE_URL,
            model=MODEL,
            models_endpoint="ok",
            chat_completion="ok",
            function_calling="ok",
            structured_output="fail",  # degraded — but still a cache hit
            tested_at=datetime.now(UTC),
        )
        redis = _make_redis_with_get(cached_raw=cached_result.model_dump_json())

        def _explode(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                "degraded-cache-hit path should not re-probe; "
                f"unexpected HTTP request to {request.url}",
            )

        transport = httpx.MockTransport(_explode)
        async with httpx.AsyncClient(transport=transport) as http:
            result = await read_or_recompute_capability_result(
                redis, BASE_URL, API_KEY, MODEL, http_client=http
            )
        assert result is not None
        assert result.structured_output == "fail"
        redis.set.assert_not_awaited()
