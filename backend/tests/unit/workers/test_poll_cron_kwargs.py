# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.workers.pr_reconcile._poll_cron_kwargs``.

Covers every value in :data:`SUPPORTED_POLL_MINUTES` plus the documented
fallback for an unsupported value. The Settings field validator rejects
unsupported values at boot — these tests exercise the fallback branch
through the worker's own helper (the validator is bypassed by mutating
``settings.__dict__``, mirroring the digest_helpers pattern).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app.core.settings import get_settings
from backend.workers.pr_reconcile import (
    FALLBACK_POLL_MINUTES,
    SUPPORTED_POLL_MINUTES,
    _poll_cron_kwargs,
)


def _set_poll_minutes(value: int) -> None:
    """Set the cached Settings field without re-running the field_validator."""
    settings = get_settings()
    settings.__dict__["relyloop_pr_poll_minutes"] = value


@pytest.fixture(autouse=True)
def _settings_env_and_restore(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide required-secret env vars + snapshot/restore the cached field.

    Settings construction needs ``DATABASE_URL_FILE`` + ``POSTGRES_PASSWORD_FILE``
    per CLAUDE.md Rule #2. Point both at ``/dev/null`` — the cached_property
    accessors aren't invoked here. We mutate
    ``settings.__dict__["relyloop_pr_poll_minutes"]`` directly to dodge the
    Pydantic field_validator (testing the worker's runtime fallback against
    an "impossible" value).
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    settings = get_settings()
    original = settings.__dict__.get("relyloop_pr_poll_minutes")
    yield
    if original is None:
        settings.__dict__.pop("relyloop_pr_poll_minutes", None)
    else:
        settings.__dict__["relyloop_pr_poll_minutes"] = original
    get_settings.cache_clear()


@pytest.mark.parametrize("value", sorted(v for v in SUPPORTED_POLL_MINUTES if v <= 60))
def test_sub_hourly_values_emit_minute_set(value: int) -> None:
    """Divisors of 60: ``cron(minute=set(range(0, 60, n)))``."""
    _set_poll_minutes(value)
    kwargs = _poll_cron_kwargs()
    assert set(kwargs.keys()) == {"minute"}
    assert kwargs["minute"] == set(range(0, 60, value))
    # The set must be non-empty + sized correctly.
    assert len(kwargs["minute"]) == 60 // value


@pytest.mark.parametrize("value", sorted(v for v in SUPPORTED_POLL_MINUTES if v > 60))
def test_multi_hour_values_emit_hour_set(value: int) -> None:
    """Multi-hour values: ``cron(hour=set(range(0, 24, n // 60)), minute={0})``."""
    _set_poll_minutes(value)
    kwargs = _poll_cron_kwargs()
    assert set(kwargs.keys()) == {"hour", "minute"}
    assert kwargs["minute"] == {0}
    assert kwargs["hour"] == set(range(0, 24, value // 60))
    # 1440 is a special case: exactly one tick per day at hour 0.
    if value == 1440:
        assert kwargs["hour"] == {0}


def test_unsupported_value_falls_back_to_default() -> None:
    """Outside the whitelist → fallback to 15-min default.

    The fallback emits a ``pr_poll_minutes_unsupported`` WARN via
    structlog at the moment of invocation. We don't assert against
    capsys here because structlog's ``PrintLogger`` was already bound
    to a different stdout by ``configure_logging()`` earlier in the
    test session — see the same xpassed flake on
    ``test_capability_check`` and the tracking idea at
    ``docs/00_overview/planned_features/bug_capability_check_test_isolation/``.
    Functional contract (the fallback kwargs) is the real invariant.
    """
    _set_poll_minutes(7)  # 7 is not a divisor of 60
    kwargs = _poll_cron_kwargs()
    assert kwargs == {"minute": set(range(0, 60, FALLBACK_POLL_MINUTES))}


def test_supported_set_size_matches_documentation() -> None:
    """Sanity: the spec documents 18 supported values."""
    assert len(SUPPORTED_POLL_MINUTES) == 18
