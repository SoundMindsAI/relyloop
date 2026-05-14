"""Unit tests for feat_judgments_periodic_resume_sweep Story 1.1 Settings fields.

Two new Settings fields:

* ``relyloop_judgments_resume_sweep_minutes: int`` with the same whitelist as
  ``relyloop_pr_poll_minutes`` (FR-3 of feat_judgments_periodic_resume_sweep).
* ``relyloop_judgments_resume_max_per_day: int`` with broad ``ge=1, le=10000``
  bounds (FR-4).

Mirrors the test shape of
:mod:`backend.tests.unit.core.test_settings_pr_poll` so the two cron-config
fields stay behaviourally interchangeable in the operator's mental model
(spec locked decision #1 — reuse the reconcile_pr_state precedent).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from backend.app.core.settings import Settings, get_settings
from backend.workers.pr_reconcile import SUPPORTED_POLL_MINUTES


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_required_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the lru_cache + provide required-secret env vars.

    Settings construction requires DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE
    per infra_foundation Rule #2. Point both at /dev/null — the
    @cached_property accessors aren't invoked here, so empty content is fine.
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_sweep_minutes_default_15() -> None:
    assert get_settings().relyloop_judgments_resume_sweep_minutes == 15


def test_sweep_minutes_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES", "30")
    get_settings.cache_clear()
    assert get_settings().relyloop_judgments_resume_sweep_minutes == 30


@pytest.mark.parametrize("value", sorted(SUPPORTED_POLL_MINUTES))
def test_sweep_minutes_accepts_whitelist_values(value: int) -> None:
    """Every value in the shared SUPPORTED_POLL_MINUTES frozenset is accepted."""
    s = Settings(relyloop_judgments_resume_sweep_minutes=value)
    assert s.relyloop_judgments_resume_sweep_minutes == value


def test_sweep_minutes_rejects_unsupported_value() -> None:
    """Outside the whitelist (e.g., 7) raises with a message listing the supported set."""
    with pytest.raises(ValidationError) as exc:
        Settings(relyloop_judgments_resume_sweep_minutes=7)
    # The error message must list the supported set so operators have an
    # actionable next step. Spec FR-3 requires a clear boot-time error.
    assert "RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=7" in str(exc.value)
    assert "1440" in str(exc.value)  # the largest supported value


def test_max_per_day_default_24() -> None:
    assert get_settings().relyloop_judgments_resume_max_per_day == 24


def test_max_per_day_rejects_zero_and_above_ceiling() -> None:
    """Bounds: ``ge=1, le=10000``. Anything outside raises ValidationError."""
    with pytest.raises(ValidationError):
        Settings(relyloop_judgments_resume_max_per_day=0)
    with pytest.raises(ValidationError):
        Settings(relyloop_judgments_resume_max_per_day=10001)
