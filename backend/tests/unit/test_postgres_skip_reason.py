"""Unit tests for `postgres_skip_reason()` in `backend/tests/conftest.py`.

Closes `chore_db_session_skip_reason_disambiguation` — the prior
`postgres_reachable()` helper returned a bool, and the `db_session`
fixture's hardcoded skip message `"Postgres not reachable"` was
correct only when TCP connect failed. When env vars were missing or
Settings construction failed, the message lied. The refactor split
the logic into:

- `postgres_skip_reason() -> str | None` — precise reason per failure mode
- `postgres_reachable() -> bool` — thin wrapper, kept for the 100+ callsites
  that consume `pytest.mark.skipif(not postgres_reachable(), ...)`.

These tests lock the precise reason strings so a future edit can't
silently regress the disambiguation.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from backend.tests.conftest import postgres_reachable, postgres_skip_reason


@pytest.fixture
def both_env_vars_present(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide both required env vars so case-1 (env-var missing) doesn't fire."""
    monkeypatch.setenv("DATABASE_URL_FILE", "/tmp/fake_db_url")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/tmp/fake_pg_pw")
    yield


class TestEnvVarMissing:
    """Case 1: DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE absent → distinct reason."""

    def test_both_env_vars_missing_yields_env_specific_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        reason = postgres_skip_reason()
        assert reason is not None
        assert "DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE" in reason
        assert "env var" in reason
        # The hint must mention the missing-flag-on-invocation failure mode.
        assert (
            "missing -e flag" in reason or "infra_test_worktree_missing_integration_envs" in reason
        )

    def test_only_database_url_file_missing_yields_env_specific_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
        monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/tmp/fake_pg_pw")
        reason = postgres_skip_reason()
        assert reason is not None
        assert "DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE" in reason

    def test_only_postgres_password_file_missing_yields_env_specific_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL_FILE", "/tmp/fake_db_url")
        monkeypatch.delenv("POSTGRES_PASSWORD_FILE", raising=False)
        reason = postgres_skip_reason()
        assert reason is not None
        assert "DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE" in reason


class TestSettingsConstructionFailure:
    """Case 2: Settings construction raises → distinct "Settings construction failed" reason."""

    def test_settings_failure_yields_settings_specific_reason(
        self, both_env_vars_present: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch get_settings to raise — mimics an unreadable secret file or
        # a malformed Pydantic-Settings load.
        def _raise() -> None:
            raise RuntimeError("simulated unreadable secret file")

        from backend.app.core import settings as settings_mod

        monkeypatch.setattr(settings_mod, "get_settings", _raise)
        reason = postgres_skip_reason()
        assert reason is not None
        assert "Settings construction failed" in reason
        assert "RuntimeError" in reason  # exception type name surfaces
        # Hint must point at the operator-actionable remediation.
        assert "scripts/install.sh" in reason


class TestTcpUnreachable:
    """Case 3: socket connect times out / fails → distinct "TCP connect" reason."""

    def test_tcp_failure_yields_tcp_specific_reason(
        self, both_env_vars_present: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force a Settings instance that points at a deliberately-unreachable host
        # (TEST-NET-1, RFC 5737 — guaranteed not to route).
        class _FakeSettings:
            database_url = "postgresql+asyncpg://x:y@192.0.2.1:5432/db"

        from backend.app.core import settings as settings_mod

        monkeypatch.setattr(settings_mod, "get_settings", lambda: _FakeSettings())
        # And force socket.create_connection to fail fast instead of waiting for
        # the 1s timeout (keeps the test fast + deterministic across platforms
        # that route TEST-NET-1 differently).
        with patch.object(
            socket, "create_connection", side_effect=TimeoutError("simulated TCP timeout")
        ):
            reason = postgres_skip_reason()
        assert reason is not None
        assert "TCP connect" in reason
        assert "192.0.2.1:5432" in reason
        # Hint must point at the operator-actionable remediation.
        assert "make up" in reason

    def test_oserror_also_yields_tcp_specific_reason(
        self, both_env_vars_present: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connection refused / no route are OSError subclasses — handled identically."""

        class _FakeSettings:
            database_url = "postgresql+asyncpg://x:y@192.0.2.1:5432/db"

        from backend.app.core import settings as settings_mod

        monkeypatch.setattr(settings_mod, "get_settings", lambda: _FakeSettings())
        with patch.object(socket, "create_connection", side_effect=ConnectionRefusedError("nope")):
            reason = postgres_skip_reason()
        assert reason is not None
        assert "TCP connect" in reason


class TestReachableHappyPath:
    """When everything works, both helpers return their reachable signal."""

    def test_reachable_returns_none_from_skip_reason(
        self, both_env_vars_present: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeSettings:
            database_url = "postgresql+asyncpg://x:y@127.0.0.1:5432/db"

        from backend.app.core import settings as settings_mod

        monkeypatch.setattr(settings_mod, "get_settings", lambda: _FakeSettings())

        # Mock create_connection to succeed (returns a mock socket-like object
        # supporting context-manager protocol).
        class _FakeSocket:
            def __enter__(self) -> _FakeSocket:
                return self

            def __exit__(self, *args: object) -> None:
                pass

        with patch.object(socket, "create_connection", return_value=_FakeSocket()):
            assert postgres_skip_reason() is None
            assert postgres_reachable() is True

    def test_postgres_reachable_is_true_iff_skip_reason_is_none(
        self, both_env_vars_present: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The boolean helper IS just `postgres_skip_reason() is None`."""
        monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
        # env var missing → skip reason present → reachable False
        assert postgres_skip_reason() is not None
        assert postgres_reachable() is False
