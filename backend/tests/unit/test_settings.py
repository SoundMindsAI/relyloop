# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Settings tests (infra_foundation Story 2.1).

Covers every ``*_FILE`` resolution path per spec FR-3:

- Required-secret missing → ``SettingsError``
- Required-secret empty → ``SettingsError``
- Optional-secret missing → ``None`` (no raise)
- Optional-secret empty → ``None`` (no raise)
- Valid content → returned stripped of trailing whitespace
- Trailing-newline content → returned without the newline

Plus default plain-value coverage so future refactors of Settings can't
silently change the OpenAI base URL or the chat-model default.

Tests use ``tmp_path`` + ``monkeypatch.setenv`` to construct a fresh
``Settings`` instance per case — never the cached ``get_settings()``.
"""

from pathlib import Path

import pytest

from backend.app.core.settings import Settings, SettingsError


def _make_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_url_file: Path | None = None,
    postgres_password_file: Path | None = None,
    openai_api_key_file: Path | None = None,
    cluster_credentials_file: Path | None = None,
) -> Settings:
    """Construct Settings with explicit secret-file paths via env vars."""
    if database_url_file is not None:
        monkeypatch.setenv("DATABASE_URL_FILE", str(database_url_file))
    if postgres_password_file is not None:
        monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(postgres_password_file))
    if openai_api_key_file is not None:
        monkeypatch.setenv("OPENAI_API_KEY_FILE", str(openai_api_key_file))
    if cluster_credentials_file is not None:
        monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(cluster_credentials_file))
    return Settings()


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Required secrets
# ---------------------------------------------------------------------------


class TestRequiredSecrets:
    def test_missing_database_url_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=tmp_path / "missing-db-url",  # file doesn't exist
            postgres_password_file=_write(tmp_path / "pw", "secret"),
        )
        with pytest.raises(SettingsError, match="DATABASE_URL"):
            _ = s.database_url

    def test_empty_database_url_file_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", ""),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
        )
        with pytest.raises(SettingsError, match="DATABASE_URL"):
            _ = s.database_url

    def test_whitespace_only_database_url_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Trailing-whitespace-only content stripped to empty string → still empty.
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "   \n  "),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
        )
        with pytest.raises(SettingsError, match="DATABASE_URL"):
            _ = s.database_url

    def test_missing_postgres_password_file_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=tmp_path / "missing-pw",
        )
        with pytest.raises(SettingsError, match="POSTGRES_PASSWORD"):
            _ = s.postgres_password


# ---------------------------------------------------------------------------
# Optional secrets — missing/empty resolves to None (no raise)
# ---------------------------------------------------------------------------


class TestOptionalSecrets:
    def test_unset_openai_api_key_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
        )  # OPENAI_API_KEY_FILE not set
        assert s.openai_api_key is None

    def test_missing_openai_api_key_file_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
            openai_api_key_file=tmp_path / "missing-key",
        )
        assert s.openai_api_key is None

    def test_empty_openai_api_key_file_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
            openai_api_key_file=_write(tmp_path / "key", ""),
        )
        assert s.openai_api_key is None

    def test_github_token_file_field_is_retired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """`GITHUB_TOKEN_FILE` was retired when feat_github_pr_worker shipped
        per-repo `auth_ref`. Settings ignores the env var (`extra="ignore"`
        config) and has no `github_token_file` / `github_token` accessor.
        Operators upgrading from pre-retirement installs see a startup WARN
        emitted from the API lifespan (verified in main.py integration)."""
        monkeypatch.setenv("GITHUB_TOKEN_FILE", str(tmp_path / "ghtoken"))
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
        )
        assert not hasattr(s, "github_token_file")
        assert not hasattr(s, "github_token")

    def test_empty_cluster_credentials_file_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # spec FR-3 says cluster_credentials.yaml is created as `{}\n` (empty doc).
        # Settings should treat the YAML body itself as content; the parser layer
        # (lands with infra_adapter_elastic) interprets `{}` as "no clusters yet".
        # For this story, just ensure the *_FILE accessor returns the YAML body.
        path = _write(tmp_path / "creds.yaml", "{}\n")
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "secret"),
            cluster_credentials_file=path,
        )
        # `{}\n` strips to `{}` — non-empty content, returned as-is.
        assert s.cluster_credentials_yaml == "{}"


# ---------------------------------------------------------------------------
# Valid content + trailing-whitespace handling
# ---------------------------------------------------------------------------


class TestValidContent:
    def test_database_url_content_returned(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(
                tmp_path / "db-url", "postgresql://relyloop:pw@postgres/relyloop"
            ),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.database_url == "postgresql://relyloop:pw@postgres/relyloop"

    def test_trailing_newline_stripped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Real-world: install script writes `printf "..."` (no newline) but
        # operators occasionally drop a key in via `echo "..." > ./secrets/key`
        # which appends \n. Strip transparently.
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
            openai_api_key_file=_write(tmp_path / "key", "sk-test-12345\n"),
        )
        assert s.openai_api_key == "sk-test-12345"

    def test_trailing_whitespace_stripped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
            openai_api_key_file=_write(tmp_path / "key", "sk-test  \n\t"),
        )
        assert s.openai_api_key == "sk-test"


# ---------------------------------------------------------------------------
# Default plain values — guard against silent default changes
# ---------------------------------------------------------------------------


class TestPlainValueDefaults:
    def test_default_redis_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # CI sets REDIS_URL to point at the service-container Postgres on
        # localhost; clear it before asserting the in-process default.
        monkeypatch.delenv("REDIS_URL", raising=False)
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.redis_url == "redis://redis:6379/0"

    def test_default_openai_base_url_is_openai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.openai_base_url == "https://api.openai.com/v1"

    def test_default_models_pinned_to_dated_tags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # CLAUDE.md Absolute Rule #8: never use floating tags like "gpt-4o".
        # Defaults must be dated.
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert "2024" in s.openai_model
        assert "2024" in s.openai_model_chat

    def test_env_override_redis_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6380/1")
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.redis_url == "redis://localhost:6380/1"

    # feat_study_lifecycle Phase 2 — Story 1.5 fallbacks.

    def test_default_studies_default_parallelism(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("STUDIES_DEFAULT_PARALLELISM", raising=False)
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.studies_default_parallelism == 4

    def test_default_studies_default_timeout_s(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("STUDIES_DEFAULT_TIMEOUT_S", raising=False)
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.studies_default_timeout_s == 60

    def test_env_override_studies_default_parallelism(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("STUDIES_DEFAULT_PARALLELISM", "8")
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.studies_default_parallelism == 8

    def test_env_override_studies_default_timeout_s(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("STUDIES_DEFAULT_TIMEOUT_S", "180")
        s = _make_settings(
            monkeypatch,
            database_url_file=_write(tmp_path / "db-url", "postgresql://x"),
            postgres_password_file=_write(tmp_path / "pw", "pw"),
        )
        assert s.studies_default_timeout_s == 180
