"""Smoke test proving the toolchain is wired (Story 1.2).

Also exercises the laptop-dev path: `pytest backend/tests/unit/test_smoke.py`
must succeed without `DATABASE_URL_FILE` / `POSTGRES_PASSWORD_FILE` set in
the shell environment (CI provides them, but local devs shouldn't have to).
The autouse fixture below stubs them with throwaway tmp-files. Mirrors the
pattern in `backend/tests/unit/test_workers.py:_settings_env`.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub required-secret Settings inputs so module-load import succeeds."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()


def test_python_works() -> None:
    """The simplest possible test: `1 + 1 == 2`. If this fails, pytest itself is broken."""
    assert 1 + 1 == 2


def test_app_import() -> None:
    """The FastAPI app stub from Story 1.2 imports cleanly."""
    from backend.app.main import app

    assert app.title == "RelyLoop"
    assert app.version == "0.1.0"
