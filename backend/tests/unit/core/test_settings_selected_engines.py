# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Settings.selected_engines parsing.

bug_healthz_degraded_blocks_ui_engine_subset — /healthz uses
`selected_engines` (derived from COMPOSE_PROFILES) to treat an
intentionally-excluded engine's unreachability as non-blocking. These
tests pin the parser's behavior, especially the all-engines fallback that
preserves the default (no-selection) behavior.
"""

from __future__ import annotations

import pytest

from backend.app.core.settings import Settings


def _settings(tmp_path, monkeypatch: pytest.MonkeyPatch, compose_profiles: str) -> Settings:
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.setenv("COMPOSE_PROFILES", compose_profiles)
    return Settings()


@pytest.mark.parametrize(
    ("compose_profiles", "expected"),
    [
        ("es,os,solr", {"es", "os", "solr"}),
        ("solr", {"solr"}),
        ("es", {"es"}),
        ("es,solr", {"es", "solr"}),
        ("es, solr", {"es", "solr"}),  # whitespace tolerated
        (" es , os , solr ", {"es", "os", "solr"}),
        ("solr,solr,solr", {"solr"}),  # dedup via set
    ],
)
def test_selected_engines_parses_subset(
    tmp_path, monkeypatch: pytest.MonkeyPatch, compose_profiles: str, expected: set[str]
) -> None:
    s = _settings(tmp_path, monkeypatch, compose_profiles)
    assert set(s.selected_engines) == expected


@pytest.mark.parametrize("compose_profiles", ["", "   ", "bogus", "es-typo,fusion"])
def test_selected_engines_falls_back_to_all_when_no_recognized_names(
    tmp_path, monkeypatch: pytest.MonkeyPatch, compose_profiles: str
) -> None:
    """Empty / unrecognized → all three engines.

    This preserves the default (no-selection) behavior: a stack that doesn't
    set COMPOSE_PROFILES, or sets it to something the api doesn't recognize,
    treats all engines as selected — exactly as before this fix. Fail-safe:
    when unsure, probe everything (the conservative, pre-fix behavior).
    """
    s = _settings(tmp_path, monkeypatch, compose_profiles)
    assert set(s.selected_engines) == {"es", "os", "solr"}


def test_selected_engines_default_when_unset(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """COMPOSE_PROFILES unset entirely → field default 'es,os,solr' → all three."""
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    monkeypatch.delenv("COMPOSE_PROFILES", raising=False)
    s = Settings()
    assert set(s.selected_engines) == {"es", "os", "solr"}
