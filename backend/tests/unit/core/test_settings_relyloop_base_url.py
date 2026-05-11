"""Unit tests for feat_github_pr_worker Story 1.3 Settings fields.

Three new fields:
* ``relyloop_base_url`` (None default; operator-set)
* ``relyloop_git_author_name`` (default "relyloop-bot")
* ``relyloop_git_author_email`` (default "relyloop-bot@example.com")
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_required_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the lru_cache + provide the required-secret env vars.

    Settings construction requires DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE
    to be set (per infra_foundation Rule #2). We point both at /dev/null —
    the @cached_property accessors aren't invoked by these tests so the
    empty-file content never gets read.
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_relyloop_base_url_defaults_to_none() -> None:
    s = get_settings()
    assert s.relyloop_base_url is None


def test_relyloop_base_url_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELYLOOP_BASE_URL", "https://relyloop.internal.acme.com")
    get_settings.cache_clear()
    assert get_settings().relyloop_base_url == "https://relyloop.internal.acme.com"


def test_relyloop_git_author_name_default() -> None:
    assert get_settings().relyloop_git_author_name == "relyloop-bot"


def test_relyloop_git_author_email_default() -> None:
    assert get_settings().relyloop_git_author_email == "relyloop-bot@example.com"


def test_relyloop_git_author_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELYLOOP_GIT_AUTHOR_NAME", "acme-relyloop")
    monkeypatch.setenv("RELYLOOP_GIT_AUTHOR_EMAIL", "bot@acme.internal")
    get_settings.cache_clear()
    s = get_settings()
    assert s.relyloop_git_author_name == "acme-relyloop"
    assert s.relyloop_git_author_email == "bot@acme.internal"
