# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for feat_github_webhook Story 1.1 Settings field.

One new field:

* ``relyloop_pr_poll_minutes: int`` with ``Field(default=15, ge=1, le=1440, ...)``
  — the cron cadence for ``reconcile_pr_state``. Story 3.1 narrows the
  valid range to a whitelist of cron-expressible values; this story ships
  the broad ``ge/le`` bound that Story 3.1 will tighten.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from backend.app.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_required_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the lru_cache + provide the required-secret env vars.

    Settings construction requires DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE
    per infra_foundation Rule #2. Point both at /dev/null — the
    @cached_property accessors aren't invoked by these tests so the empty
    file content is never read.
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_relyloop_pr_poll_minutes_defaults_to_15() -> None:
    assert get_settings().relyloop_pr_poll_minutes == 15


def test_relyloop_pr_poll_minutes_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELYLOOP_PR_POLL_MINUTES", "30")
    get_settings.cache_clear()
    assert get_settings().relyloop_pr_poll_minutes == 30


def test_relyloop_pr_poll_minutes_accepts_lower_bound() -> None:
    """``ge=1`` allows the minimum value."""
    s = Settings(relyloop_pr_poll_minutes=1)
    assert s.relyloop_pr_poll_minutes == 1


def test_relyloop_pr_poll_minutes_accepts_upper_bound() -> None:
    """``le=1440`` allows the 24h max."""
    s = Settings(relyloop_pr_poll_minutes=1440)
    assert s.relyloop_pr_poll_minutes == 1440


def test_relyloop_pr_poll_minutes_rejects_zero() -> None:
    """Below the ``ge=1`` lower bound raises validation."""
    with pytest.raises(ValidationError):
        Settings(relyloop_pr_poll_minutes=0)


def test_relyloop_pr_poll_minutes_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Settings(relyloop_pr_poll_minutes=-1)


def test_relyloop_pr_poll_minutes_rejects_above_upper_bound() -> None:
    """Above ``le=1440`` (24h) raises validation."""
    with pytest.raises(ValidationError):
        Settings(relyloop_pr_poll_minutes=1441)
