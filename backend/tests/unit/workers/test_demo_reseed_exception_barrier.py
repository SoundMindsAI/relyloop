"""Unit tests for the ``run_demo_reseed`` top-level exception barrier.

Per ``bug_demo_reseed_button_silent_enqueue_failure``. The worker
function previously had two gap regions where an exception escaped
without writing ``status="failed"`` to Redis:

- Lines 76-88 (settings load, factory init, Redis acquisition) — sat
  *outside* the outer ``try``.
- Lines 91-133 (``get_engine()``, ``engine.connect()``, advisory-lock
  query, ``factory()`` session, ``httpx.AsyncClient(...)``) — sat
  *inside* the outer ``try`` but the block had no ``except``, only a
  ``finally`` to close Redis.

The fix wraps the entire function body in an ``except BaseException``
barrier that writes a ``failed`` status payload to Redis and then
re-raises (preserves Arq's ``JobExecutionFailed`` record + the
worker-log traceback).

These tests use a ``_FakeAsyncRedis`` that records ``set`` calls so we
can assert what the barrier wrote to the status key without standing up
a real Redis server. They stub ``get_settings`` / ``get_session_factory``
/ ``get_engine`` at the worker-module level so the test never tries to
resolve a real DB URL or open a real engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from backend.app.core.settings import get_settings
from backend.app.services.demo_seeding import DEMO_RESEED_STATUS_KEY


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide required-secret env vars so ``get_settings()`` constructs cleanly.

    Per CLAUDE.md Rule #2 these are the only two boot-blocking required
    secrets. Pointing both at ``/dev/null`` is the standard test-side
    pattern (matches ``test_poll_cron_kwargs.py``). The barrier under
    test never resolves the file contents — only ``settings.redis_url``,
    which is non-secret.
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeAsyncRedis:
    """Minimal async Redis stand-in for the barrier test.

    The barrier only needs ``set`` (via ``status_set``) on the failure
    path. The cleanup ``redis.aclose()`` is also called — we capture it
    so the test can assert the close path was taken when appropriate.
    """

    def __init__(self) -> None:
        self.set_calls: list[tuple[str, Any, dict[str, Any]]] = []
        self.aclose_called = False

    async def set(self, key: str, value: Any, **kwargs: Any) -> None:
        self.set_calls.append((key, value, kwargs))

    async def get(self, key: str) -> Any:  # pragma: no cover — barrier never reads
        return None

    async def aclose(self) -> None:
        self.aclose_called = True


def _install_noop_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``get_session_factory`` and ``get_engine`` to no-op sentinels.

    Each test overrides the specific dependency it wants to raise; the
    rest are stubbed here so the worker never touches a real DB. The
    barrier writes status BEFORE any of these are called when Redis is
    pre-supplied via ``ctx``, so the only thing being tested is that the
    barrier catches whatever the test arranges to raise.
    """
    from backend.workers import demo_reseed as worker_mod

    monkeypatch.setattr(worker_mod, "get_session_factory", lambda: object())
    monkeypatch.setattr(worker_mod, "get_engine", lambda: object())


@pytest.mark.asyncio
async def test_exception_barrier_writes_failed_status_when_get_engine_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_engine()`` raising should flip Redis to ``failed`` and re-raise.

    This is the canonical regression for the gap at lines 91-133 (inside
    the outer try, no except). On ``main`` this test fails because the
    bare ``try/finally`` swallows nothing — the exception escapes
    without ``status_set`` ever being called. On this branch the outer
    ``except BaseException`` barrier writes ``failed`` first.
    """
    from backend.workers import demo_reseed as worker_mod

    _install_noop_deps(monkeypatch)

    def _raise_get_engine() -> None:
        raise RuntimeError("boom from get_engine")

    monkeypatch.setattr(worker_mod, "get_engine", _raise_get_engine)

    fake_redis = _FakeAsyncRedis()

    with pytest.raises(RuntimeError, match="boom from get_engine"):
        await worker_mod.run_demo_reseed({"redis": fake_redis})

    # Barrier MUST have written exactly one failed-status payload.
    assert len(fake_redis.set_calls) == 1, (
        f"Expected one status_set after barrier; got {len(fake_redis.set_calls)}"
    )
    key, raw_payload, _kwargs = fake_redis.set_calls[0]
    assert key == DEMO_RESEED_STATUS_KEY
    payload = json.loads(raw_payload)
    assert payload["status"] == "failed", payload
    assert "RuntimeError" in payload["failed_reason"], payload["failed_reason"]
    assert "boom from get_engine" in payload["failed_reason"], payload["failed_reason"]
    assert payload["started_at"] is not None
    assert payload["finished_at"] is not None


@pytest.mark.asyncio
async def test_exception_barrier_writes_failed_status_when_get_session_factory_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_session_factory()`` raising should also be caught.

    This is the canonical regression for the gap at lines 76-88
    (outside the outer try). On ``main`` this test fails because the
    factory init was uncovered. On this branch the barrier covers it.
    """
    from backend.workers import demo_reseed as worker_mod

    _install_noop_deps(monkeypatch)

    def _raise_factory() -> None:
        raise ValueError("session-factory misconfigured")

    monkeypatch.setattr(worker_mod, "get_session_factory", _raise_factory)

    fake_redis = _FakeAsyncRedis()

    with pytest.raises(ValueError, match="session-factory misconfigured"):
        await worker_mod.run_demo_reseed({"redis": fake_redis})

    assert len(fake_redis.set_calls) == 1
    _key, raw_payload, _kwargs = fake_redis.set_calls[0]
    payload = json.loads(raw_payload)
    assert payload["status"] == "failed"
    assert "ValueError" in payload["failed_reason"]
    assert "session-factory misconfigured" in payload["failed_reason"]


@pytest.mark.asyncio
async def test_exception_barrier_does_not_close_arq_managed_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini PR #286 finding #8: don't close the worker-shared Redis.

    When ``ctx["redis"]`` is present, the barrier reuses it and MUST NOT
    call ``aclose()`` on it — closing Arq's shared pool would kill every
    other in-flight job. The ``created_redis`` flag guards this.
    """
    from backend.workers import demo_reseed as worker_mod

    _install_noop_deps(monkeypatch)
    monkeypatch.setattr(
        worker_mod,
        "get_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    fake_redis = _FakeAsyncRedis()

    with pytest.raises(RuntimeError):
        await worker_mod.run_demo_reseed({"redis": fake_redis})

    # The Arq-managed pool stays open.
    assert fake_redis.aclose_called is False


@pytest.mark.asyncio
async def test_exception_barrier_closes_self_created_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ctx has no redis, the barrier closes the one it created.

    The fallback path opens its own ``Redis.from_url`` and is responsible
    for closing it. We swap ``Redis.from_url`` for a factory that returns
    our fake, then induce a crash and assert ``aclose`` was called.
    """
    from backend.workers import demo_reseed as worker_mod

    _install_noop_deps(monkeypatch)

    fake_redis = _FakeAsyncRedis()

    class _FakeRedisClass:
        @staticmethod
        def from_url(_url: str, *, decode_responses: bool = False) -> _FakeAsyncRedis:
            assert decode_responses is False
            return fake_redis

    monkeypatch.setattr(worker_mod, "Redis", _FakeRedisClass)
    monkeypatch.setattr(
        worker_mod,
        "get_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        await worker_mod.run_demo_reseed({})  # no "redis" key → fallback path

    # The self-created Redis was closed in the finally block.
    assert fake_redis.aclose_called is True
    # And the barrier still wrote the failed-status payload before re-raise.
    assert len(fake_redis.set_calls) == 1
    _key, raw_payload, _kwargs = fake_redis.set_calls[0]
    payload = json.loads(raw_payload)
    assert payload["status"] == "failed"
