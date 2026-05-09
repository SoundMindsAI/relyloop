"""Worker smoke tests (infra_foundation Story 4.3).

The MVP1 worker registers no functions. These tests verify the
``WorkerSettings`` class is importable, ``functions`` is empty, and
``redis_settings`` resolves the host from ``Settings.redis_url``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def _settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the required Settings inputs so import-time wiring works."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    # Reset get_settings cache so it re-reads our env vars
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()


def test_worker_settings_importable(_settings_env: None) -> None:
    """WorkerSettings should import without raising and expose `functions`."""
    from backend.workers.all import WorkerSettings

    assert WorkerSettings.functions == []


def test_worker_settings_redis_host_parsed(_settings_env: None) -> None:
    """RedisSettings.from_dsn should pull host=redis port=6379 db=0 from the URL."""
    # Re-import so the class-level redis_settings is rebuilt with our env
    import importlib

    import backend.workers.all as worker_module

    importlib.reload(worker_module)

    rs = worker_module.WorkerSettings.redis_settings
    assert rs.host == "redis"
    assert rs.port == 6379
    assert rs.database == 0


def test_worker_settings_redis_host_overridable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A different REDIS_URL should be reflected after a settings cache clear."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("REDIS_URL", "redis://other-host:6380/2")

    from backend.app.core.settings import get_settings

    get_settings.cache_clear()

    import importlib

    import backend.workers.all as worker_module

    importlib.reload(worker_module)

    rs = worker_module.WorkerSettings.redis_settings
    assert rs.host == "other-host"
    assert rs.port == 6380
    assert rs.database == 2

    # Restore for other tests
    os.environ.pop("REDIS_URL", None)
    get_settings.cache_clear()
