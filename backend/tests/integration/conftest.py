# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration-test conftest (Phase 2).

Three autouse fixtures:

* :func:`_clean_phase2_tables` — wipes Phase 2 tables after every test so
  TestClient-driven commits (which bypass the savepoint-scoped
  ``db_session`` fixture) don't leak rows into the next test.

* :func:`_restore_settings_mutations` — feat_digest_proposal Story 2.1
  helpers mutate ``settings.__dict__["openai_api_key"]`` /
  ``["openai_model"]`` to exercise the OPENAI_NOT_CONFIGURED /
  UNKNOWN_MODEL_PRICING preflight paths. The lru_cache'd Settings
  instance survives across tests, so without explicit restoration the
  mutation pollutes subsequent tests (the digest_openai_deferral test
  setting key=None caused the judgments-worker happy-path test to bail
  on the OPENAI_NOT_CONFIGURED preflight). This fixture snapshots the
  mutated keys before each test and restores them after.

* :func:`async_client` — an ``httpx.AsyncClient`` mounted on the
  FastAPI app via ``LifespanManager``. The lifespan-driven Arq pool
  wiring is suppressed via ``app.state`` injection so the studies
  POST handler degrades gracefully to a no-op enqueue (operators must
  boot the worker separately to drive the lifecycle).

  Mixing ``async def`` tests with the sync ``TestClient`` triggers
  "Future attached to a different loop" errors because TestClient
  spawns its own loop nested inside pytest-asyncio's loop. Using
  ``httpx.AsyncClient`` keeps every coroutine on the test's single
  loop.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import text

from backend.tests.conftest import postgres_reachable

# Disable the lifespan-spawned cluster-health warmup task during
# integration tests. The warmup interleaves on the event loop with the
# test body and perturbs the timing of the latent webhook merge-handler
# row-lock race captured at
# docs/00_overview/planned_features/02_mvp2/
# bug_webhook_concurrent_merge_race_timing_sensitive/idea.md.
# Production deployments leave this UNSET so the warmup runs. Tests that
# need to exercise the warmup explicitly (e.g.
# backend/tests/integration/test_cluster_health_warmup.py) call
# `run_cluster_health_warmup_background` directly and don't depend on
# the lifespan-spawn path.
os.environ.setdefault("RELYLOOP_DISABLE_STARTUP_WARMUP", "1")


@pytest_asyncio.fixture(autouse=True)
async def _clean_phase2_tables() -> AsyncIterator[None]:
    """Wipe Phase 2 tables after each test (FK-safe order).

    Uses a **one-shot engine** that we dispose at the end of the fixture
    so the asyncpg connections don't get pooled and re-issued to the next
    test (which runs on a fresh event loop and would hit
    ``MissingGreenlet`` when asyncpg tries to close the prior-loop
    connection).
    """
    yield
    if not postgres_reachable():
        return

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as db:
            for table in (
                # feat_digest_proposal: digests has FK to studies — delete BEFORE
                # proposals so we don't have to think about the proposals → studies
                # → digests dependency direction (digests is a sibling of proposals
                # under studies, not a parent).
                "digests",
                "proposals",
                "trials",
                "studies",
                # feat_llm_judgments: judgments cascades on judgment_lists DELETE,
                # but explicit DELETE keeps cleanup deterministic + matches the
                # existing FK-safe order convention.
                "judgments",
                "judgment_lists",
                "queries",
                "query_sets",
                "query_templates",
                "clusters",
            ):
                await db.execute(text(f"DELETE FROM {table}"))
            await db.commit()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _restore_settings_mutations() -> AsyncIterator[None]:
    """Snapshot + restore Settings mutations made by digest tests.

    The digest helpers in :mod:`backend.tests.integration._digest_helpers`
    mutate ``settings.__dict__["openai_api_key"]`` and
    ``["openai_model"]`` directly to exercise the OPENAI_NOT_CONFIGURED /
    UNKNOWN_MODEL_PRICING preflight branches. The lru_cache'd Settings
    instance is shared across tests, so without restoration these
    mutations leak — the judgments worker happy-path test (which expects
    a configured key) bails on the polluted None.
    """
    from backend.app.core.settings import get_settings

    settings = get_settings()
    snapshot = {
        key: settings.__dict__.get(key, _MISSING) for key in ("openai_api_key", "openai_model")
    }
    yield
    for key, value in snapshot.items():
        if value is _MISSING:
            settings.__dict__.pop(key, None)
        else:
            settings.__dict__[key] = value


_MISSING: object = object()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an ``httpx.AsyncClient`` mounted on the FastAPI app.

    Applies Alembic migrations on first call (CI doesn't run migrations
    as a separate workflow step). Uses ``LifespanManager`` so
    startup/shutdown hooks run (including the Arq pool builder). In
    tests Redis IS reachable (CI service container) so the pool
    builds; the enqueued ``start_study`` jobs sit in the queue with no
    worker to pick them up — that's fine, the tests don't assert
    worker behavior.
    """
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# arq_pool_spy — opt-in recording double for the Arq/Redis enqueue sink
# (chore_studies_post_arq_spy_fixture). Lets studies-POST integration tests
# positively assert enqueue behavior: rejection paths assert NO enqueue,
# success paths assert exactly one `("start_study", <id>)` enqueue.
# ---------------------------------------------------------------------------


class SpyArqPool:
    """In-memory recording double for ``arq.connections.ArqRedis``.

    Records each ``enqueue_job`` call as a flattened ``(name, *args)`` tuple
    so the studies-POST handler's ``enqueue_job("start_study", study_id)``
    records ``("start_study", study_id)``. Returns a truthy sentinel to
    mirror ``ArqRedis.enqueue_job``'s "returns a Job on accept" contract
    (FR-1 / D-3, D-4).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> object:
        self.calls.append((name, *args))  # flattened: (name,) + args
        return object()  # truthy sentinel (not None)


_UNSET: object = object()
"""Sentinel distinguishing "attr unset" from "attr is None"."""


@contextlib.contextmanager
def install_arq_pool_spy(app: FastAPI) -> Iterator[SpyArqPool]:
    """Install a :class:`SpyArqPool` on ``app.state.arq_pool``; restore on exit.

    Captures the prior value (or ``_UNSET`` if the attribute was never set,
    which happens on Redis-down boots per ``backend/app/main.py``). On exit,
    deletes the attribute if it was originally unset, else reassigns the
    captured value (FR-2 / D-5).
    """
    prior = getattr(app.state, "arq_pool", _UNSET)
    spy = SpyArqPool()
    app.state.arq_pool = spy
    try:
        yield spy
    finally:
        if prior is _UNSET:
            # delattr is safe: we set it above, so it exists now.
            delattr(app.state, "arq_pool")
        else:
            app.state.arq_pool = prior


@pytest_asyncio.fixture
async def arq_pool_spy(async_client: httpx.AsyncClient) -> AsyncIterator[SpyArqPool]:
    """Yield a :class:`SpyArqPool` installed on the live app AFTER the lifespan
    built (or skipped) the real pool. Depends on ``async_client`` so the
    install ordering is correct (FR-2 / D-2). NOT autouse (D-1)."""
    from backend.app.main import app

    with install_arq_pool_spy(app) as spy:
        yield spy
