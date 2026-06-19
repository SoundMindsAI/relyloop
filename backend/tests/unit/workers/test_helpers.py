# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the shared worker cleanup helper ``close_quietly``."""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from backend.workers.helpers import close_quietly

logger = structlog.get_logger("test")


class _AcloseClient:
    """httpx / redis / SearchAdapter convention."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _CloseClient:
    """openai AsyncOpenAI convention (no ``aclose``)."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RaisingClient:
    async def aclose(self) -> None:
        raise RuntimeError("boom during close")


@pytest.mark.asyncio
async def test_prefers_aclose() -> None:
    client = _AcloseClient()
    await close_quietly(client, logger=logger, label="redis")
    assert client.closed is True


@pytest.mark.asyncio
async def test_falls_back_to_close() -> None:
    client = _CloseClient()
    await close_quietly(client, logger=logger, label="openai client")
    assert client.closed is True


@pytest.mark.asyncio
async def test_none_is_noop() -> None:
    # Must not raise when the worker never constructed the client.
    await close_quietly(None, logger=logger, label="adapter")


@pytest.mark.asyncio
async def test_swallows_close_error() -> None:
    # A raise from close in a finally must never propagate / mask the job outcome.
    await close_quietly(_RaisingClient(), logger=logger, label="adapter")


@pytest.mark.asyncio
async def test_object_without_close_is_noop() -> None:
    sentinel: Any = object()
    await close_quietly(sentinel, logger=logger, label="mystery")
