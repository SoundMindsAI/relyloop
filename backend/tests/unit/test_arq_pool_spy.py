# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``SpyArqPool`` (chore_studies_post_arq_spy_fixture Story 1.1).

Pure in-memory double — no DB / Redis / app. Verifies the recording shape
(flattened ``(name, *args)`` tuple) + the truthy-sentinel return contract
that mirrors ``ArqRedis.enqueue_job`` (FR-1 / D-3, D-4). The integration
wiring (install-after-lifespan ordering, restore branches) is covered in
``backend/tests/integration/test_studies_api.py``.
"""

from __future__ import annotations

from backend.tests.integration.conftest import SpyArqPool

# NB: no per-test @pytest.mark.asyncio and no module-level
# `pytestmark = pytest.mark.asyncio` — the project sets
# `asyncio_mode = "auto"` (pyproject.toml), so async tests are collected
# automatically. This matches the dominant codebase convention (e.g.
# backend/tests/unit/services/test_ubi_reader.py: 17 async tests, zero
# asyncio markers). (Gemini review: the line-18 suggestion assumed
# asyncio_mode=strict — it's auto, so no marker is needed.)


async def test_records_flattened_name_and_args() -> None:
    """``enqueue_job(name, *args)`` records ``(name, *args)`` flattened."""
    pool = SpyArqPool()
    ret = await pool.enqueue_job("start_study", "study-123")
    assert pool.calls == [("start_study", "study-123")]
    # Truthy sentinel (not None) — mirrors ArqRedis.enqueue_job returning a Job.
    assert ret is not None
    assert bool(ret) is True


async def test_records_multiple_calls_in_order() -> None:
    pool = SpyArqPool()
    await pool.enqueue_job("start_study", "a")
    await pool.enqueue_job("start_study", "b")
    assert pool.calls == [("start_study", "a"), ("start_study", "b")]


async def test_extra_args_are_flattened_kwargs_ignored() -> None:
    """Positional varargs flatten into the tuple; kwargs are NOT recorded
    (the studies-POST handler only passes positional args)."""
    pool = SpyArqPool()
    await pool.enqueue_job("job", "x", "y", _defer_by=5)
    assert pool.calls == [("job", "x", "y")]


async def test_empty_args_records_name_only() -> None:
    pool = SpyArqPool()
    await pool.enqueue_job("noargs")
    assert pool.calls == [("noargs",)]


async def test_enqueue_job_is_a_coroutine() -> None:
    """``enqueue_job`` must be awaitable to match the production await site."""
    import inspect

    assert inspect.iscoroutinefunction(SpyArqPool.enqueue_job)
