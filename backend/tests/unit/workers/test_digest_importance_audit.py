"""Audit + routing tests for ``backend.workers.digest._compute_param_importance``.

Per the ``chore_digest_worker_narrow_except`` idea (idea.md in the same
session this test was authored in; moves to implemented_features at
finalization):

Story 1 — the audit. ``optuna.importance.get_param_importances`` raises in
three documented edge cases (zero completed trials, single trial, all
pruned). Each one MUST raise ``ValueError`` so the digest worker's
narrowed-except allowlist (``_PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS =
(ValueError,)``) is correct. If Optuna ever raises a different exception
type for these cases, this test fails loudly — operators can then expand
the allowlist with the new type. No silent fallback.

Story 2 — the routing. ``_compute_param_importance`` has a two-tier
fallback:
  * Allowlisted exception → ``digest_importance_failed`` WARN + return ``{}``.
  * Unexpected exception → ``digest_importance_failed_unexpected`` ERROR
    + return ``{}``.

Both tiers return ``{}`` (caller contract unchanged); only the log level +
event_type differ. The ERROR-level path is the key win — the canonical PR #92
``ImportError`` regression would have surfaced as ``ERROR`` on day one
under this contract, instead of silently shipping empty importance maps for
~2 days.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import optuna
import optuna.importance
import pytest

from backend.workers.digest import (
    _PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS,
    _compute_param_importance,
)

# Optuna is noisy by default; silence for the test session.
optuna.logging.set_verbosity(optuna.logging.ERROR)


class _RecordingLogger:
    """Tiny stub for ``structlog.BoundLogger`` that records calls.

    Replaces ``structlog.testing.capture_logs()`` in this file because the
    project's :func:`backend.app.core.logging.configure_logging` uses
    ``structlog.configure(cache_logger_on_first_use=True)``. Once a sibling
    integration test in the same pytest session warms the cache via
    FastAPI lifespan, ``capture_logs()`` cannot intercept the already-
    bound logger and returns an empty list. Locally (cache cold)
    capture_logs works; in CI (cache warm from prior integration tests)
    it doesn't. Same issue is silently lurking in any other test that
    uses ``capture_logs()`` on a cached logger.

    Monkeypatching the module-level ``logger`` attribute bypasses the
    cache entirely — the function under test reads ``logger`` through
    module attribute lookup at call time, so the replacement is seen
    immediately. See ``infra_structlog_test_level_helper/idea.md`` for
    the systematic follow-up that would factor this pattern repo-wide.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("warning", event, dict(kwargs)))

    def error(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("error", event, dict(kwargs)))

    def info(self, event: str, **kwargs: Any) -> None:
        # Helper doesn't emit info, but make the stub forgiving.
        self.calls.append(("info", event, dict(kwargs)))

    def find(self, *, level: str, event_type: str) -> list[dict[str, Any]]:
        """Return kwargs dicts for matching (level, event_type) calls."""
        return [
            kw
            for lvl, _evt, kw in self.calls
            if lvl == level and kw.get("event_type") == event_type
        ]


# ---------------------------------------------------------------------------
# Story 1 — Audit: Optuna's actual exception types
# ---------------------------------------------------------------------------


def test_zero_completed_trials_raises_value_error() -> None:
    """An Optuna study with no completed trials → ValueError.

    Documented message: "Cannot evaluate parameter importances without
    completed trials." This is the most common digest edge case (the
    digest worker's Step 5 zero-trials short-circuit catches the common
    case, but if a study somehow reaches Step 10 with zero completed
    trials, get_param_importances raises here).
    """
    study = optuna.create_study(direction="maximize")
    with pytest.raises(ValueError, match="without completed trials"):
        optuna.importance.get_param_importances(study)


def test_single_completed_trial_raises_value_error() -> None:
    """An Optuna study with exactly one completed trial → ValueError.

    Documented message: "Cannot evaluate parameter importances with only
    a single trial." Importance computation requires variance across
    multiple trials.
    """
    study = optuna.create_study(direction="maximize")

    def _objective(trial: optuna.Trial) -> float:
        return trial.suggest_float("x", 0.0, 1.0)

    study.optimize(_objective, n_trials=1)
    with pytest.raises(ValueError, match="with only a single trial"):
        optuna.importance.get_param_importances(study)


def test_all_pruned_trials_raises_value_error() -> None:
    """An Optuna study where every trial was pruned → ValueError.

    Optuna treats pruned trials as "not completed," so this collapses to
    the same "no completed trials" case as ``test_zero_completed_trials_raises_value_error``.
    """
    study = optuna.create_study(direction="maximize")

    def _always_prune(_trial: optuna.Trial) -> float:
        raise optuna.TrialPruned()

    study.optimize(_always_prune, n_trials=3)
    with pytest.raises(ValueError, match="without completed trials"):
        optuna.importance.get_param_importances(study)


def test_value_error_is_in_allowlist() -> None:
    """The narrowed-except allowlist must contain ValueError.

    All three audited Optuna edge cases raise ValueError. If this assertion
    fails, the allowlist is wrong and benign small-study cases would
    incorrectly land in the ERROR-level fallback path.
    """
    assert ValueError in _PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS


# ---------------------------------------------------------------------------
# Story 2 — Routing: the two-tier fallback in _compute_param_importance
# ---------------------------------------------------------------------------


def _stub_study() -> optuna.Study:
    """Build a minimal Optuna Study for passing into the helper as-typed.

    The routing tests monkeypatch the actual ``optuna.importance.get_param_importances``
    call inside the helper; the study argument is only used for its type/identity.
    """
    return optuna.create_study(direction="maximize")


def test_routing_success_path_returns_actual_dict() -> None:
    """When the underlying call succeeds, the helper passes the result through.

    Validates the success path of the two-tier fallback — no log emitted,
    real dict returned. Casts the underlying Any through ``cast(dict[str, float], ...)``.
    """
    study = _stub_study()
    expected = {"alpha": 0.6, "beta": 0.4}
    with patch.object(
        optuna.importance,
        "get_param_importances",
        return_value=expected,
    ):
        result = _compute_param_importance(study, study_id="study-abc")
    assert result == expected


def test_routing_allowlisted_value_error_logs_warning_and_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError → ``digest_importance_failed`` at WARN + ``{}`` return.

    The benign small-study path. The legacy event_type (``digest_importance_failed``)
    is preserved unchanged for grep continuity in operator logs.
    """
    study = _stub_study()
    rec = _RecordingLogger()
    monkeypatch.setattr("backend.workers.digest.logger", rec)
    with patch.object(
        optuna.importance,
        "get_param_importances",
        side_effect=ValueError("Cannot evaluate parameter importances with only a single trial."),
    ):
        result = _compute_param_importance(study, study_id="study-warn")

    assert result == {}
    warn_calls = rec.find(level="warning", event_type="digest_importance_failed")
    assert len(warn_calls) == 1
    assert warn_calls[0]["study_id"] == "study-warn"
    assert warn_calls[0]["error_type"] == "ValueError"
    # The unexpected event_type did NOT fire on this path.
    assert not rec.find(level="error", event_type="digest_importance_failed_unexpected")


@pytest.mark.parametrize(
    "exc",
    [
        ImportError("No module named 'sklearn'"),  # the canonical PR #92 regression
        RuntimeError("Optuna RDB schema not initialized"),
        TypeError("internal Optuna API drift"),
    ],
    ids=["ImportError-PR92-canary", "RuntimeError-rdb-drift", "TypeError-api-drift"],
)
def test_routing_unexpected_exception_logs_error_and_returns_empty(
    exc: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything outside the allowlist → ``digest_importance_failed_unexpected`` ERROR + ``{}``.

    The load-bearing assertion of this whole chore: a regression like PR
    #92's ``ImportError`` (sklearn missing) would have surfaced as ERROR
    on day one under this contract, with a distinct event_type that
    observability can alarm on. Parametrized over three flavors of
    "unexpected" so we don't accidentally only catch the literal
    ImportError case.
    """
    study = _stub_study()
    rec = _RecordingLogger()
    monkeypatch.setattr("backend.workers.digest.logger", rec)
    with patch.object(optuna.importance, "get_param_importances", side_effect=exc):
        result = _compute_param_importance(study, study_id="study-error")

    assert result == {}
    error_calls = rec.find(level="error", event_type="digest_importance_failed_unexpected")
    assert len(error_calls) == 1
    assert error_calls[0]["study_id"] == "study-error"
    assert error_calls[0]["error_type"] == type(exc).__name__
    # The allowlisted event_type did NOT fire on this path.
    assert not rec.find(level="warning", event_type="digest_importance_failed")
