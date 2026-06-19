# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for Arq worker functions."""

from __future__ import annotations

from typing import Any

import structlog


async def close_quietly(client: Any, *, logger: structlog.stdlib.BoundLogger, label: str) -> None:
    """Close an async client/adapter in a ``finally``, swallowing any error.

    Cleanup must never mask the real job outcome: a raise from a client's
    close in a ``finally`` would replace a re-raised original exception (or
    fail an otherwise-successful job). No-ops on ``None``. Prefers the
    async-resource ``aclose()`` convention (httpx, redis, the SearchAdapter)
    and falls back to ``close()`` (the openai ``AsyncOpenAI`` spelling), so a
    single call site covers every client a worker holds.
    """
    if client is None:
        return
    closer = getattr(client, "aclose", None) or getattr(client, "close", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception:  # noqa: BLE001 — cleanup must not mask the job outcome
        logger.debug(f"{label} close raised", exc_info=True)
