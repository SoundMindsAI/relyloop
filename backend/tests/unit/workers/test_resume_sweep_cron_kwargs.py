"""Unit tests for ``backend.workers.judgments_resume._resume_sweep_cron_kwargs``.

Mirrors :mod:`backend.tests.unit.workers.test_poll_cron_kwargs` — the same
sub-hour / multi-hour / unsupported-fallback paths. Spec FR-2 + AC-8 +
locked-decision #1 (reuse the pr_reconcile precedent verbatim).

Settings construction needs DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE
per CLAUDE.md Rule #2 (no bare env vars for secrets) — both fields are
@cached_property and not invoked here, so /dev/null is sufficient. The
field_validator is bypassed for the fallback test via direct attribute
mutation (mirrors test_poll_cron_kwargs.py:24-27).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app.core.settings import get_settings
from backend.workers.judgments_resume import _resume_sweep_cron_kwargs
from backend.workers.pr_reconcile import (
    FALLBACK_POLL_MINUTES,
    SUPPORTED_POLL_MINUTES,
)


def _set_sweep_minutes(value: int) -> None:
    """Set the cached Settings field without re-running the field_validator."""
    settings = get_settings()
    settings.__dict__["relyloop_judgments_resume_sweep_minutes"] = value


@pytest.fixture(autouse=True)
def _settings_env_and_restore(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    settings = get_settings()
    original = settings.__dict__.get("relyloop_judgments_resume_sweep_minutes")
    yield
    if original is None:
        settings.__dict__.pop("relyloop_judgments_resume_sweep_minutes", None)
    else:
        settings.__dict__["relyloop_judgments_resume_sweep_minutes"] = original
    get_settings.cache_clear()


@pytest.mark.parametrize("value", sorted(v for v in SUPPORTED_POLL_MINUTES if v <= 60))
def test_sub_hourly_values_emit_minute_set(value: int) -> None:
    """Divisors of 60: ``cron(minute=set(range(0, 60, n)))``."""
    _set_sweep_minutes(value)
    kwargs = _resume_sweep_cron_kwargs()
    assert set(kwargs.keys()) == {"minute"}
    assert kwargs["minute"] == set(range(0, 60, value))
    assert len(kwargs["minute"]) == 60 // value


@pytest.mark.parametrize("value", sorted(v for v in SUPPORTED_POLL_MINUTES if v > 60))
def test_multi_hour_values_emit_hour_set(value: int) -> None:
    """Multi-hour values: ``cron(hour=set(range(0, 24, n // 60)), minute={0})``."""
    _set_sweep_minutes(value)
    kwargs = _resume_sweep_cron_kwargs()
    assert set(kwargs.keys()) == {"hour", "minute"}
    assert kwargs["minute"] == {0}
    assert kwargs["hour"] == set(range(0, 24, value // 60))
    if value == 1440:
        assert kwargs["hour"] == {0}


def test_unsupported_value_falls_back_to_default() -> None:
    """Outside the whitelist (e.g., 7) → fallback to 15-min default + WARN.

    The fallback path emits a structlog WARN. We assert the functional
    contract (the kwargs) rather than the log line — structlog's PrintLogger
    binding makes log-line capture flaky (see test_poll_cron_kwargs.py's
    matching comment at line 78-89 + bug_capability_check_test_isolation/).
    """
    _set_sweep_minutes(7)
    kwargs = _resume_sweep_cron_kwargs()
    assert kwargs == {"minute": set(range(0, 60, FALLBACK_POLL_MINUTES))}
