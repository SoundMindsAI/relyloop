# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Method-agnostic GitHub REST client (feat_github_webhook Story 1.5).

Generalises ``backend.workers.git_pr._github_post`` (POST-only, shipped
with feat_github_pr_worker) into ``github_request(client, method, url,
*, json_body=None, token=...)`` so the polling reconciler (``GET
/repos/.../pulls/{n}``) and the register-webhook worker (``GET /hooks``
+ ``POST /hooks``) share the same retry policy.

Retry policy (verbatim from the prior `_github_post` implementation):

* ``httpx.RequestError`` — exponential-backoff retry up to
  ``HTTP_RETRY_MAX`` attempts; propagate on budget exhaustion.
* ``5xx`` — exponential-backoff retry.
* ``429`` — honour ``Retry-After`` (clamped at ``RATE_LIMIT_CLAMP_S``).
* ``403`` — secondary rate-limit detection:
  - ``Retry-After`` header present → wait that duration.
  - ``X-RateLimit-Remaining: 0`` + ``X-RateLimit-Reset`` → wait until reset.
  - Body mentions ``"rate limit"`` or ``"abuse"`` → exponential backoff.
  - None of the above → terminal (e.g. PAT lacks scope).
* Other 4xx — terminal.

Tokens are caller-supplied and never logged — the global
``RedactTokensProcessor`` (feat_github_pr_worker Story 1.4) provides the
defense-in-depth backstop, and this module emits no log lines of its
own.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

HTTP_TIMEOUT_S: float = 30.0
"""Default per-request timeout for GitHub REST calls."""

HTTP_RETRY_MAX: int = 3
"""Total attempt budget (initial + retries)."""

HTTP_RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0)
"""Exponential-backoff schedule (must align with ``HTTP_RETRY_MAX``)."""

RATE_LIMIT_CLAMP_S: float = 60.0
"""Hard cap on honoured ``Retry-After`` / ``X-RateLimit-Reset`` waits."""


def parse_retry_after(response: httpx.Response) -> float:
    """Return the ``Retry-After`` header as seconds (default 1.0)."""
    raw = response.headers.get("retry-after", "1")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0


def is_secondary_rate_limit(response: httpx.Response) -> bool:
    """True iff a 403 carries the secondary-rate-limit header pair."""
    return (
        response.headers.get("x-ratelimit-remaining") == "0"
        and "x-ratelimit-reset" in response.headers
    )


def body_mentions_rate_limit(response: httpx.Response) -> bool:
    """Conservative body-substring match for GitHub's abuse-detection 403s.

    Some secondary-rate-limit responses carry no headers — only a JSON
    body like ``{"message": "You have exceeded a secondary rate limit"}``.
    Substring match on the lowercased body; defensive try/except so a
    bytes/encoding edge case doesn't crash the retry loop.
    """
    try:
        text = response.text.lower()
    except Exception:  # noqa: BLE001 — defensive against bytes/encoding edge
        return False
    return "rate limit" in text or "abuse" in text


def parse_rate_limit_reset(response: httpx.Response) -> float:
    """Return ``X-RateLimit-Reset`` as seconds-from-now (default 1.0)."""
    raw = response.headers.get("x-ratelimit-reset", "0")
    try:
        return max(0.0, float(raw) - time.time())
    except ValueError:
        return 1.0


async def github_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    token: str,
) -> httpx.Response:
    """Method-agnostic GitHub REST call with the established retry policy.

    Args:
        client: Caller-owned ``httpx.AsyncClient`` (so connection
            pooling / timeout configuration / mock transports stay in
            the caller's hands).
        method: HTTP verb (``GET``, ``POST``, ``PATCH``, ...). The case
            is normalised to upper.
        url: Absolute GitHub API URL.
        json_body: Optional JSON body. ``None`` for GETs.
        token: GitHub PAT — sent in the ``Authorization`` header.
            Caller is responsible for sourcing it from the mounted
            secrets bundle.

    Returns:
        The final ``httpx.Response``. Caller inspects ``status_code``.

    Raises:
        httpx.RequestError: A network error persisted across all retry
            attempts. The leading line from the most recent attempt is
            re-raised so the caller can include the error class in its
            ``pr_open_error`` write.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    verb = method.upper()
    last_response: httpx.Response | None = None
    last_exc: Exception | None = None
    for attempt in range(HTTP_RETRY_MAX):
        try:
            response = await client.request(verb, url, json=json_body, headers=headers)
        except httpx.RequestError as exc:
            last_exc = exc
            await asyncio.sleep(HTTP_RETRY_BACKOFF_S[attempt])
            continue
        last_response = response
        if response.status_code < 400:
            return response
        if response.status_code >= 500:
            await asyncio.sleep(HTTP_RETRY_BACKOFF_S[attempt])
            continue
        if response.status_code == 429:
            wait = parse_retry_after(response)
            await asyncio.sleep(min(wait, RATE_LIMIT_CLAMP_S))
            continue
        if response.status_code == 403:
            # GitHub's secondary rate limit emits inconsistent signals;
            # cover the three observed shapes (header, header-pair, body).
            if "retry-after" in response.headers:
                wait = parse_retry_after(response)
                await asyncio.sleep(min(wait, RATE_LIMIT_CLAMP_S))
                continue
            if is_secondary_rate_limit(response):
                wait = parse_rate_limit_reset(response)
                await asyncio.sleep(min(wait, RATE_LIMIT_CLAMP_S))
                continue
            if body_mentions_rate_limit(response):
                await asyncio.sleep(HTTP_RETRY_BACKOFF_S[attempt])
                continue
        # Other 4xx — terminal.
        return response
    if last_response is not None:
        return last_response
    assert last_exc is not None  # noqa: S101 — invariant: at least one attempt
    raise last_exc
