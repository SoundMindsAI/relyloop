# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for feat_home_demo_reseed_endpoint Story 1.0 Settings field.

One new field:

* ``demo_reseed_per_call_http_timeout_s: int`` with
  ``Field(default=120, ge=30, le=600, ...)`` — the hard ceiling per
  single httpx self-call inside the demo reseed orchestrator. Per FR-4
  this is the ONLY timeout (there is no outer wall-clock timeout).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from backend.app.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_required_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the lru_cache + provide the required-secret env vars."""
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_demo_reseed_per_call_http_timeout_s_defaults_to_120() -> None:
    assert get_settings().demo_reseed_per_call_http_timeout_s == 120


def test_demo_reseed_per_call_http_timeout_s_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_RESEED_PER_CALL_HTTP_TIMEOUT_S", "180")
    get_settings.cache_clear()
    assert get_settings().demo_reseed_per_call_http_timeout_s == 180


def test_demo_reseed_per_call_http_timeout_s_accepts_lower_bound() -> None:
    """``ge=30`` allows the minimum value."""
    s = Settings(demo_reseed_per_call_http_timeout_s=30)
    assert s.demo_reseed_per_call_http_timeout_s == 30


def test_demo_reseed_per_call_http_timeout_s_accepts_upper_bound() -> None:
    """``le=600`` allows the 10-minute max."""
    s = Settings(demo_reseed_per_call_http_timeout_s=600)
    assert s.demo_reseed_per_call_http_timeout_s == 600


def test_demo_reseed_per_call_http_timeout_s_rejects_below_lower_bound() -> None:
    """Below ``ge=30`` raises validation."""
    with pytest.raises(ValidationError):
        Settings(demo_reseed_per_call_http_timeout_s=29)


def test_demo_reseed_per_call_http_timeout_s_rejects_above_upper_bound() -> None:
    """Above ``le=600`` raises validation."""
    with pytest.raises(ValidationError):
        Settings(demo_reseed_per_call_http_timeout_s=601)


def test_demo_reseed_per_call_http_timeout_s_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        Settings(demo_reseed_per_call_http_timeout_s=0)
