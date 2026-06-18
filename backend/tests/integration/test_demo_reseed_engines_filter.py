# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the ``POST /api/v1/_test/demo/reseed`` body shapes.

feat_selective_engine_startup_and_demo Story 2.2 / FR-4.

Exercises the FastAPI route + Pydantic validation + Arq enqueue plumbing.
Uses the ``arq_pool_spy`` fixture so we positively assert what the route
enqueues without actually running the destructive reseed.

The orchestrator's engine-filter LOGIC (small SCENARIOS loop + rich
scenario, user_excluded vs unreachable reasons) has fast unit coverage in
``backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py``
— this file guards the wire surface, not the orchestrator internals.
"""

from __future__ import annotations

import httpx
import pytest

from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.integration

if not postgres_reachable():
    pytest.skip(
        "demo reseed engines-filter integration tests require Postgres "
        "for the async_client fixture's Alembic migration step. Run via "
        "CI service containers or `make test-worktree`.",
        allow_module_level=True,
    )


async def test_post_with_engines_filter_accepted(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,  # SpyArqPool — installed on app.state
) -> None:
    """Body ``{engines: ["elasticsearch"]}`` → 202 + initial running shape."""
    # Clear any prior status from earlier tests.
    response = await async_client.post(
        "/api/v1/_test/demo/reseed",
        json={"engines": ["elasticsearch"]},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    # New field defaults to {} on the initial payload.
    assert body["scenarios_skipped_reasons"] == {}
    # AC-7 / FR-5: the engines selection rides on the enqueued job kwargs.
    spy = arq_pool_spy
    enqueued = [c for c in spy.calls if c[0] == "run_demo_reseed"]  # type: ignore[attr-defined]
    assert len(enqueued) == 1, (
        f"expected exactly one run_demo_reseed enqueue, got {spy.calls!r}"  # type: ignore[attr-defined]
    )


async def test_post_with_empty_body_treats_as_all_engines(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """Body ``{}`` → 202; engines treated as None (back-compat sentinel)."""
    response = await async_client.post("/api/v1/_test/demo/reseed", json={})
    assert response.status_code == 202, response.text


async def test_post_with_null_engines_treats_as_all_engines(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """Body ``{engines: null}`` → 202; null is the back-compat sentinel."""
    response = await async_client.post(
        "/api/v1/_test/demo/reseed",
        json={"engines": None},
    )
    assert response.status_code == 202, response.text


async def test_post_clears_stale_result_key_before_enqueue(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """A prior run's cached Arq result must not dedup-block a retry.

    bug_reseed_failure_blocks_retry_arq_singleton_dedup — Arq keeps a finished
    job's result under ``arq:result:<job_id>`` for keep_result (default 1h) and
    silently aborts a re-enqueue of the same ``_job_id`` while that key exists,
    leaving the operator stuck on "enqueued — waiting for worker". The reseed
    POST handler deletes that key before enqueuing so a deliberate retry after
    a completed/failed run actually runs.
    """
    from arq.constants import result_key_prefix

    from backend.app.api.v1._test import _RESEED_JOB_ID

    spy = arq_pool_spy
    result_key = f"{result_key_prefix}{_RESEED_JOB_ID}"
    # Simulate a completed prior run whose result is still cached in Redis.
    spy._store[result_key] = b"stale-result"  # type: ignore[attr-defined]

    response = await async_client.post("/api/v1/_test/demo/reseed", json={})
    assert response.status_code == 202, response.text

    # The stale result key was deleted (so Arq won't dedup the enqueue) ...
    assert result_key in spy.deleted, (  # type: ignore[attr-defined]
        f"expected the stale result key to be cleared, deleted={spy.deleted!r}"  # type: ignore[attr-defined]
    )
    assert result_key not in spy._store  # type: ignore[attr-defined]
    # ... and the job was actually enqueued (not deduped to None).
    enqueued = [c for c in spy.calls if c[0] == "run_demo_reseed"]  # type: ignore[attr-defined]
    assert len(enqueued) == 1, (
        f"expected exactly one run_demo_reseed enqueue, got {spy.calls!r}"  # type: ignore[attr-defined]
    )


async def test_post_with_no_body_accepted(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """POST with Content-Length: 0 / no body → 202 (today's clients).

    The body parameter is ``Annotated[ReseedRequest | None, Body()] = None``
    so an absent body resolves to None inside the handler and the engines
    filter never fires.
    """
    response = await async_client.post("/api/v1/_test/demo/reseed")
    assert response.status_code == 202, response.text


async def test_post_with_unknown_engine_rejected_422(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """Body ``{engines: ["fusion"]}`` → 422 VALIDATION_ERROR per FR-4 / AC-5."""
    response = await async_client.post(
        "/api/v1/_test/demo/reseed",
        json={"engines": ["fusion"]},
    )
    assert response.status_code == 422, response.text
    # FastAPI's default 422 envelope shape is loc-based; we just guard the
    # status code + that no enqueue happened.
    spy = arq_pool_spy
    enqueued = [c for c in spy.calls if c[0] == "run_demo_reseed"]  # type: ignore[attr-defined]
    assert len(enqueued) == 0, "rejected body should not enqueue a job"


async def test_post_with_mixed_valid_and_invalid_engines_rejected_422(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """A single invalid value anywhere in the list rejects the whole request."""
    response = await async_client.post(
        "/api/v1/_test/demo/reseed",
        json={"engines": ["elasticsearch", "fusion"]},
    )
    assert response.status_code == 422


async def test_post_with_empty_engines_list_rejected_422(
    async_client: httpx.AsyncClient,
    arq_pool_spy: object,
) -> None:
    """Body ``{engines: []}`` → 422 per D-7 (empty-list-rejected-at-validation)."""
    response = await async_client.post(
        "/api/v1/_test/demo/reseed",
        json={"engines": []},
    )
    assert response.status_code == 422
