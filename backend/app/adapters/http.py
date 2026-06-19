# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared HTTP transport helpers for search-engine adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from backend.app.adapters.errors import ClusterUnreachableError

ErrorFactory = Callable[[str], Exception]


async def request_with_retry(
    client: httpx.AsyncClient,
    *,
    method: str,
    base_url: str,
    path: str,
    auth_headers: dict[str, str],
    correlation_header: str,
    json: Any = None,
    content: bytes | str | None = None,
    params: dict[str, Any] | None = None,
    request_id: str | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    translate_errors: bool = True,
    read_timeout_error: ErrorFactory = ClusterUnreachableError,
) -> httpx.Response:
    """Issue one adapter request with the spec §13 single retry.

    Connection-class failures are retried exactly once. With
    ``translate_errors=True``, the final connection failure and 401/403/5xx
    responses map to adapter-domain exceptions. Callers may choose the
    read-timeout exception class because Solr strict query paths surface read
    timeouts as ``QueryTimeoutError`` while Elastic keeps the older
    ``ClusterUnreachableError`` behavior.
    """
    headers = dict(auth_headers)
    if extra_headers:
        headers.update(extra_headers)
    if request_id:
        headers[correlation_header] = request_id

    kwargs: dict[str, Any] = {
        "method": method,
        "url": f"{base_url}{path}",
        "headers": headers,
        "params": params,
    }
    if json is not None:
        kwargs["json"] = json
    if content is not None:
        kwargs["content"] = content
    if timeout is not None:
        kwargs["timeout"] = timeout

    connection_excs = (
        httpx.ConnectError,
        httpx.RemoteProtocolError,
        httpx.ConnectTimeout,
    )

    resp: httpx.Response | None = None
    for attempt in (1, 2):
        try:
            resp = await client.request(**kwargs)
            break
        except httpx.ReadTimeout as exc:
            if attempt == 2:
                if translate_errors:
                    raise read_timeout_error(str(exc)) from exc
                raise
        except connection_excs as exc:
            if attempt == 2:
                if translate_errors:
                    raise ClusterUnreachableError(str(exc)) from exc
                raise
    if resp is None:  # pragma: no cover - the loop either assigns or raises.
        raise RuntimeError("request retry loop exited without response")

    if translate_errors and resp.status_code in (401, 403):
        raise ClusterUnreachableError(
            f"Authentication failed (HTTP {resp.status_code}) for {method} {path}"
        )
    if translate_errors and resp.status_code >= 500:
        raise ClusterUnreachableError(f"HTTP {resp.status_code} from {method} {path}")
    return resp
