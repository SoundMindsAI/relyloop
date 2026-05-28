"""Unit tests for the FastAPI lifespan hook in :mod:`backend.app.main`.

Maps to plan Story 1.3 DoD (bug_demo_clusters_unreachable_in_healthz):

- AC-1: lifespan spawns BOTH the capability-check task AND the warmup task.
- AC-7 (lifespan side): shutdown cancels the warmup task; the warmup's
  `async with db_factory()` releases the session via __aexit__ on
  CancelledError propagation. The DB-session-release proof itself is in
  ``test_cluster_health_warmup.py::TestShutdownCancellation`` (per spec
  §19 D-10); this file owns the cancel/await/swallow ordering proof.
- FR-4 regression: capability-check task continues to be cancelled.

Per plan cycle-1 B1, lifespan tests are NOT hermetic by default — entering
the real lifespan constructs a Redis client, calls get_session_factory,
and awaits arq.create_pool. All four need to be patched to fakes BEFORE
entering the lifespan context, otherwise the tests perform real
infrastructure I/O / hang / become environment-dependent.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Set DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE BEFORE importing
# backend.app.main because main.py evaluates `get_settings()` at module
# load (line 178: `_cors_origins = [...]`). Without this, the import
# raises pydantic_core.ValidationError. The conftest fixture
# `_clear_settings_caches` resets the cache between tests, so the stubs
# here only apply during this module's collection / first call.
_stub_dir = tempfile.mkdtemp(prefix="relyloop-lifespan-test-")
_db_url_file = os.path.join(_stub_dir, "db_url")
_pw_file = os.path.join(_stub_dir, "pg_password")
with open(_db_url_file, "w") as _fh:
    _fh.write("postgresql+asyncpg://x:y@localhost/test")
with open(_pw_file, "w") as _fh:
    _fh.write("test")
os.environ.setdefault("DATABASE_URL_FILE", _db_url_file)
os.environ.setdefault("POSTGRES_PASSWORD_FILE", _pw_file)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from backend.app import main as app_main  # noqa: E402


@pytest.fixture
def _patched_externals(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch all four external dependencies the lifespan touches.

    Returns the patched fakes so tests can introspect their state.
    """
    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock(return_value=None)

    # backend.app.main imports Redis from redis.asyncio at module load —
    # patch the attribute on the main module so .from_url returns our fake.
    fake_redis_class = MagicMock()
    fake_redis_class.from_url = MagicMock(return_value=fake_redis)
    monkeypatch.setattr(app_main, "Redis", fake_redis_class)

    fake_factory = MagicMock(name="async_sessionmaker")
    monkeypatch.setattr(app_main, "get_session_factory", lambda: fake_factory)

    # Settings.openai_* attributes are read inside the lifespan; provide a
    # minimal fake that satisfies the access patterns.
    fake_settings = MagicMock()
    fake_settings.redis_url = "redis://localhost:6379/0"
    fake_settings.openai_base_url = "https://api.openai.com/v1"
    fake_settings.openai_api_key = None
    fake_settings.openai_model = "gpt-4o-mini-2024-07-18"
    monkeypatch.setattr(app_main, "get_settings", lambda: fake_settings)

    # Arq pool: arq.connections.create_pool is imported inside the lifespan
    # body; patch the create_pool function directly on the arq module.
    import arq.connections

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock(return_value=None)
    monkeypatch.setattr(
        arq.connections,
        "create_pool",
        AsyncMock(return_value=fake_pool),
    )
    monkeypatch.setattr(arq.connections.RedisSettings, "from_dsn", lambda *_a, **_kw: None)

    return {
        "redis": fake_redis,
        "factory": fake_factory,
        "settings": fake_settings,
        "pool": fake_pool,
    }


class TestLifespanSpawnsBothTasks:
    async def test_lifespan_spawns_capability_and_warmup_tasks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _patched_externals: dict[str, Any],
    ) -> None:
        """AC-1: both background coroutines are invoked when lifespan enters."""
        # Ensure the env-var gate is NOT set (default-spawn behavior).
        monkeypatch.delenv("RELYLOOP_DISABLE_STARTUP_WARMUP", raising=False)

        cap_invocations: list[dict[str, Any]] = []
        warmup_invocations: list[tuple[Any, Any]] = []

        async def _fake_cap(**kwargs: Any) -> None:
            cap_invocations.append(kwargs)

        async def _fake_warmup(db_factory: Any, redis_client: Any) -> None:
            warmup_invocations.append((db_factory, redis_client))

        monkeypatch.setattr(app_main, "run_capability_check_background", _fake_cap)
        monkeypatch.setattr(app_main, "run_cluster_health_warmup_background", _fake_warmup)

        app = FastAPI()
        async with app_main.lifespan(app):
            # Give the spawned create_task coroutines a chance to run.
            await asyncio.sleep(0)

        assert len(cap_invocations) == 1, cap_invocations
        assert len(warmup_invocations) == 1, warmup_invocations
        # warmup receives the patched factory + redis client.
        assert warmup_invocations[0][0] is _patched_externals["factory"]
        assert warmup_invocations[0][1] is _patched_externals["redis"]

    async def test_lifespan_skips_warmup_when_env_var_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _patched_externals: dict[str, Any],
    ) -> None:
        """RELYLOOP_DISABLE_STARTUP_WARMUP=1 skips the warmup task entirely.

        Used by integration-test conftest to avoid event-loop interleaving
        with the latent webhook merge-handler row-lock race captured at
        docs/00_overview/planned_features/02_mvp2/bug_webhook_concurrent_merge_race_timing_sensitive/idea.md.
        Capability-check task is unaffected.
        """
        monkeypatch.setenv("RELYLOOP_DISABLE_STARTUP_WARMUP", "1")

        cap_invocations: list[dict[str, Any]] = []
        warmup_invocations: list[tuple[Any, Any]] = []

        async def _fake_cap(**kwargs: Any) -> None:
            cap_invocations.append(kwargs)

        async def _fake_warmup(db_factory: Any, redis_client: Any) -> None:
            warmup_invocations.append((db_factory, redis_client))

        monkeypatch.setattr(app_main, "run_capability_check_background", _fake_cap)
        monkeypatch.setattr(app_main, "run_cluster_health_warmup_background", _fake_warmup)

        app = FastAPI()
        async with app_main.lifespan(app):
            await asyncio.sleep(0)

        # Capability check still spawns (orthogonal feature).
        assert len(cap_invocations) == 1
        # Warmup is gated off — coroutine NEVER called.
        assert len(warmup_invocations) == 0, warmup_invocations


class TestLifespanShutdownCancels:
    async def test_shutdown_cancels_warmup_task_if_running(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _patched_externals: dict[str, Any],
    ) -> None:
        """AC-7 (lifespan side): per plan cycle-1 B2, use explicit cancel-seen
        signaling instead of the weak "no warning" check. The fake warmup
        blocks forever; the lifespan teardown MUST cancel it, AND the
        CancelledError MUST be observed inside the warmup coroutine
        (proving main.py's cancel/await/swallow ran).
        """
        # Ensure the integration-conftest-set RELYLOOP_DISABLE_STARTUP_WARMUP
        # doesn't leak into this unit test. Pytest collects integration test
        # modules before running unit tests, so the integration conftest's
        # module-level `os.environ.setdefault` may have already set this
        # env var. Without the delenv, the warmup task would not spawn and
        # `await started.wait()` would time out.
        monkeypatch.delenv("RELYLOOP_DISABLE_STARTUP_WARMUP", raising=False)

        started = asyncio.Event()
        cancel_seen = asyncio.Event()

        async def _fake_warmup_blocks(_db_factory: Any, _redis_client: Any) -> None:
            started.set()
            try:
                await asyncio.Event().wait()  # block forever
            except asyncio.CancelledError:
                cancel_seen.set()
                raise

        async def _fake_cap_noop(**_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(app_main, "run_capability_check_background", _fake_cap_noop)
        monkeypatch.setattr(app_main, "run_cluster_health_warmup_background", _fake_warmup_blocks)

        app = FastAPI()
        async with app_main.lifespan(app):
            # Wait for the warmup to enter its blocking section.
            await asyncio.wait_for(started.wait(), timeout=2.0)
            assert not cancel_seen.is_set()

        # Lifespan exited → cancel/await/swallow ran. The warmup observed
        # CancelledError.
        assert cancel_seen.is_set()

    async def test_shutdown_cancels_capability_task_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _patched_externals: dict[str, Any],
    ) -> None:
        """FR-4 regression: Story 1.3's edit didn't break the existing
        capability-check shutdown ordering. Same pattern as above but for
        the cap_task.
        """
        cap_started = asyncio.Event()
        cap_cancel_seen = asyncio.Event()

        async def _fake_cap_blocks(**_kwargs: Any) -> None:
            cap_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cap_cancel_seen.set()
                raise

        async def _fake_warmup_noop(_db_factory: Any, _redis_client: Any) -> None:
            return None

        monkeypatch.setattr(app_main, "run_capability_check_background", _fake_cap_blocks)
        monkeypatch.setattr(app_main, "run_cluster_health_warmup_background", _fake_warmup_noop)

        app = FastAPI()
        async with app_main.lifespan(app):
            await asyncio.wait_for(cap_started.wait(), timeout=2.0)

        assert cap_cancel_seen.is_set()
