"""OpenAI-compatible endpoint capability check (infra_foundation Story 3.3 / FR-7).

Runs a 4-step self-test against ``OPENAI_BASE_URL`` and caches the result in
Redis under ``openai:capabilities:{sha256(base_url)}`` with a 24h TTL.

Per the "Capability check at startup" section of
``docs/01_architecture/llm-orchestration.md``:

1. ``GET {base_url}/models`` — verify reachable.
2. ``POST {base_url}/chat/completions`` (1-token) — verify chat works.
3. ``POST .../chat/completions`` with a trivial ``echo(text)`` tool +
   ``tool_choice="required"`` — verify tool-calling works.
4. ``POST .../chat/completions`` with ``response_format=json_schema`` for a
   1-field schema — verify structured output works.

The function logs at WARN on any probe failure (with the failing step name +
the response error) and never raises — partial degradation is reported via
the cached ``CapabilityResult``, never as a startup crash. CLAUDE.md Absolute
Rule #11: ``/healthz`` reads the cached result; the check itself runs once at
startup as a fire-and-forget task.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from redis.asyncio import Redis

from backend.app.core.logging import get_logger
from backend.app.llm.capability_models import CapabilityResult

logger = get_logger(__name__)

# Per-call HTTP timeout (5s — tolerant of slow local-LLM cold-starts; the check
# is non-blocking via asyncio.create_task() so a slow endpoint doesn't hold
# startup).
PROBE_HTTP_TIMEOUT_SECONDS = 5.0

# Cache TTL: 24h per llm-orchestration.md.
CACHE_TTL_SECONDS = 86_400

# Status literal type alias for the per-probe result.
ProbeStatus = Literal["ok", "fail", "untested"]


def cache_key(base_url: str) -> str:
    """Return the Redis key for the cached capability result.

    Hashing the base URL avoids pinning the key to a length-bounded label and
    makes the key stable across restarts even when the URL contains ports,
    paths, or query strings.
    """
    digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()
    return f"openai:capabilities:{digest}"


async def _probe_models_endpoint(client: httpx.AsyncClient, base_url: str, api_key: str) -> bool:
    """Step 1 — ``GET {base_url}/models``."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        logger.warning(
            "OpenAI capability check: models_endpoint failed",
            step="models_endpoint",
            url=url,
            error=str(exc),
        )
        return False
    if resp.status_code >= 400:
        logger.warning(
            "OpenAI capability check: models_endpoint returned error status",
            step="models_endpoint",
            url=url,
            status_code=resp.status_code,
        )
        return False
    return True


async def _probe_chat_completion(
    client: httpx.AsyncClient, base_url: str, api_key: str, model: str
) -> bool:
    """Step 2 — minimal 1-token completion."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "OpenAI capability check: chat_completion failed",
            step="chat_completion",
            url=url,
            error=str(exc),
        )
        return False
    if resp.status_code >= 400:
        logger.warning(
            "OpenAI capability check: chat_completion returned error status",
            step="chat_completion",
            url=url,
            status_code=resp.status_code,
        )
        return False
    try:
        body = resp.json()
        # Minimal shape check — `choices[0].message` must exist.
        _ = body["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning(
            "OpenAI capability check: chat_completion response unparseable",
            step="chat_completion",
            url=url,
            error=str(exc),
        )
        return False
    return True


async def _probe_function_calling(
    client: httpx.AsyncClient, base_url: str, api_key: str, model: str
) -> bool:
    """Step 3 — single trivial ``echo(text)`` tool, ``tool_choice="required"``."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Echo the word 'hello'."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo back the input text verbatim.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }
        ],
        "tool_choice": "required",
        "max_tokens": 64,
    }
    try:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "OpenAI capability check: function_calling failed",
            step="function_calling",
            url=url,
            error=str(exc),
        )
        return False
    if resp.status_code >= 400:
        logger.warning(
            "OpenAI capability check: function_calling returned error status",
            step="function_calling",
            url=url,
            status_code=resp.status_code,
        )
        return False
    try:
        body = resp.json()
        tool_calls = body["choices"][0]["message"].get("tool_calls")
        if not tool_calls:
            raise ValueError("no tool_calls in response")
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning(
            "OpenAI capability check: function_calling response missing tool_calls",
            step="function_calling",
            url=url,
            error=str(exc),
        )
        return False
    return True


async def _probe_structured_output(
    client: httpx.AsyncClient, base_url: str, api_key: str, model: str
) -> bool:
    """Step 4 — ``response_format=json_schema`` for a 1-field schema."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Return value=42 as JSON."}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "trivial",
                "schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        "max_tokens": 64,
    }
    try:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "OpenAI capability check: structured_output failed",
            step="structured_output",
            url=url,
            error=str(exc),
        )
        return False
    if resp.status_code >= 400:
        logger.warning(
            "OpenAI capability check: structured_output returned error status",
            step="structured_output",
            url=url,
            status_code=resp.status_code,
        )
        return False
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        # Content should be a JSON string parseable into the trivial schema.
        import json

        parsed = json.loads(content)
        if "value" not in parsed:
            raise ValueError("response JSON missing required 'value' key")
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        logger.warning(
            "OpenAI capability check: structured_output response unparseable",
            step="structured_output",
            url=url,
            error=str(exc),
        )
        return False
    return True


async def check_capabilities(
    base_url: str,
    api_key: str,
    model: str,
    redis_client: Redis,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> CapabilityResult:
    """Run the 4-step capability self-test and cache the result in Redis.

    Args:
        base_url: ``OPENAI_BASE_URL`` (e.g., ``https://api.openai.com/v1``).
        api_key: Resolved API key (caller MUST pre-check it is non-empty —
            see ``backend/app/main.py`` startup hook).
        model: Default model name to use for the chat / FC / structured-output
            probes (typically ``Settings.openai_model``).
        redis_client: Async Redis client for storing the result.
        http_client: Optional ``httpx.AsyncClient``; tests inject mocks.
            When ``None``, the function constructs one with a
            ``PROBE_HTTP_TIMEOUT_SECONDS`` per-call timeout.

    Returns:
        ``CapabilityResult`` populated with each probe's outcome. Never
        raises — failure paths are logged at WARN and reported as
        ``"fail"``/``"untested"`` fields. Steps 2-4 are reported as
        ``"untested"`` if step 1 (models endpoint) fails, since downstream
        probes cannot meaningfully run against an unreachable endpoint.

    Side effects:
        Writes the JSON-serialized result to Redis under ``cache_key(base_url)``
        with a ``CACHE_TTL_SECONDS`` (24h) TTL. A Redis write failure is
        logged at WARN and swallowed.
    """
    owns_client = http_client is None
    client: httpx.AsyncClient = http_client or httpx.AsyncClient(timeout=PROBE_HTTP_TIMEOUT_SECONDS)

    try:
        models_ok = await _probe_models_endpoint(client, base_url, api_key)
        chat_status: ProbeStatus
        fc_status: ProbeStatus
        struct_status: ProbeStatus
        if not models_ok:
            # Skip downstream probes — they can't succeed if /models is unreachable.
            chat_status = "untested"
            fc_status = "untested"
            struct_status = "untested"
        else:
            chat_ok = await _probe_chat_completion(client, base_url, api_key, model)
            chat_status = "ok" if chat_ok else "fail"
            fc_ok = await _probe_function_calling(client, base_url, api_key, model)
            fc_status = "ok" if fc_ok else "fail"
            struct_ok = await _probe_structured_output(client, base_url, api_key, model)
            struct_status = "ok" if struct_ok else "fail"

        result = CapabilityResult(
            base_url=base_url,
            model=model,
            models_endpoint="ok" if models_ok else "fail",
            chat_completion=chat_status,
            function_calling=fc_status,
            structured_output=struct_status,
            tested_at=datetime.now(UTC),
        )

        try:
            await redis_client.set(
                cache_key(base_url),
                result.model_dump_json(),
                ex=CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — cache-write failure is non-fatal
            logger.warning(
                "OpenAI capability check: failed to cache result in Redis",
                error=str(exc),
            )

        # Single summary log on success — easier to grep than per-step logs.
        if all(s == "ok" for s in (chat_status, fc_status, struct_status)) and models_ok:
            logger.info(
                "OpenAI capability check passed",
                base_url=base_url,
                model=model,
                chat=chat_status,
                function_calling=fc_status,
                structured_output=struct_status,
            )
        else:
            logger.warning(
                "OpenAI capability check completed with degraded capabilities",
                base_url=base_url,
                model=model,
                models_endpoint="ok" if models_ok else "fail",
                chat=chat_status,
                function_calling=fc_status,
                structured_output=struct_status,
            )

        return result
    finally:
        if owns_client:
            await client.aclose()


async def run_capability_check_background(
    base_url: str,
    api_key: str | None,
    model: str,
    redis_client: Redis,
) -> None:
    """Fire-and-forget startup wrapper.

    Skips entirely when ``api_key`` is ``None``/empty (matches the
    ``OPENAI_API_KEY_FILE`` empty-file convention). Catches every exception so
    a slow / broken endpoint cannot crash the API process.
    """
    if not api_key:
        logger.info(
            "OpenAI capability check skipped: OPENAI_API_KEY not configured",
            base_url=base_url,
        )
        return
    try:
        await check_capabilities(base_url, api_key, model, redis_client)
    except asyncio.CancelledError:  # pragma: no cover — propagate shutdown
        raise
    except Exception as exc:  # noqa: BLE001 — never crash the API on capability check
        logger.warning(
            "OpenAI capability check raised unexpectedly; treating as untested",
            base_url=base_url,
            error=str(exc),
        )
