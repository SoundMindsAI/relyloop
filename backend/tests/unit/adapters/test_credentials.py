# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``resolve_credentials`` unit tests (Story 2.1).

Covers:
* Missing YAML body (``Settings.cluster_credentials_yaml is None``) → raises.
* YAML that's not a top-level mapping → raises.
* Valid YAML, missing ref → raises.
* Valid YAML, present ref → returns the dict verbatim.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.credentials import CredentialsMissing, resolve_credentials
from backend.app.core.settings import get_settings


def _stub_settings(monkeypatch, tmp_path, body: str | None) -> None:
    """Force a specific cluster_credentials_yaml body via mounted file."""
    creds = tmp_path / "creds.yaml"
    if body is not None:
        creds.write_text(body)
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    if body is not None:
        monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    else:
        monkeypatch.delenv("CLUSTER_CREDENTIALS_FILE", raising=False)
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()


def test_missing_yaml_raises(tmp_path, monkeypatch) -> None:
    _stub_settings(monkeypatch, tmp_path, body=None)
    with pytest.raises(CredentialsMissing, match="not mounted"):
        resolve_credentials("es_basic", "any-ref")


def test_yaml_not_a_mapping_raises(tmp_path, monkeypatch) -> None:
    _stub_settings(monkeypatch, tmp_path, body="- just\n- a\n- list\n")
    with pytest.raises(CredentialsMissing, match="not a top-level mapping"):
        resolve_credentials("es_basic", "any-ref")


def test_missing_ref_raises(tmp_path, monkeypatch) -> None:
    _stub_settings(
        monkeypatch,
        tmp_path,
        body="other-ref:\n  username: u\n  password: p\n",
    )
    with pytest.raises(CredentialsMissing, match="not found"):
        resolve_credentials("es_basic", "missing-ref")


def test_returns_dict_for_present_ref(tmp_path, monkeypatch) -> None:
    _stub_settings(
        monkeypatch,
        tmp_path,
        body="ok:\n  username: alice\n  password: secret\n",
    )
    creds = resolve_credentials("es_basic", "ok")
    assert creds == {"username": "alice", "password": "secret"}


def test_empty_yaml_body_raises(tmp_path, monkeypatch) -> None:
    """Empty YAML parses as ``None`` → treat as missing ref."""
    _stub_settings(monkeypatch, tmp_path, body="")
    # An empty file's content is empty after strip — Settings reports
    # cluster_credentials_yaml as None, so the "not mounted" branch fires.
    with pytest.raises(CredentialsMissing, match="not mounted"):
        resolve_credentials("es_basic", "any-ref")
