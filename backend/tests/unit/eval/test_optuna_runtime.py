"""Unit tests for backend.app.eval.optuna_runtime.

Story 2.1 covers sampler/pruner defaults + overrides + the spec §FR-2
auto-disable safeguard (AC-2, AC-6a, AC-6b at unit-layer; integration-layer
in Story 3.1's test_pruner_defaults.py).

URL composition is tested against the pure ``_compose_storage_url`` helper
so no real ``RDBStorage`` is constructed — spec FR-1/AC-1b explicitly does
not constrain whether construction opens a DB connection, so unit tests
that build a real storage would be brittle across Optuna versions.
``build_storage`` itself is verified by monkeypatching the constructor.
"""

from __future__ import annotations

from typing import Any

import optuna
import pytest
from optuna.pruners import MedianPruner, NopPruner
from optuna.samplers import RandomSampler, TPESampler

from backend.app.eval.optuna_runtime import (
    _compose_storage_url,
    build_pruner,
    build_sampler,
    build_storage,
)

# ---------------------------------------------------------------------------
# _compose_storage_url — pure URL composition
# ---------------------------------------------------------------------------


def test_compose_storage_url_strips_asyncpg_and_appends_search_path():
    """asyncpg URL → sync URL with options=-csearch_path=optuna appended."""
    result = _compose_storage_url("postgresql+asyncpg://u:p@h:5432/d")
    assert result == "postgresql://u:p@h:5432/d?options=-csearch_path=optuna"


def test_compose_storage_url_preserves_existing_query_params():
    """An existing query string is preserved; the option is appended with &."""
    result = _compose_storage_url("postgresql://u:p@h:5432/d?sslmode=require")
    assert result == "postgresql://u:p@h:5432/d?sslmode=require&options=-csearch_path=optuna"


def test_compose_storage_url_is_idempotent():
    """Re-composing an already-composed URL is a no-op."""
    composed = _compose_storage_url("postgresql+asyncpg://u:p@h:5432/d")
    assert _compose_storage_url(composed) == composed


def test_compose_storage_url_idempotent_when_option_already_present():
    """A URL that already contains the option (any position) is returned unchanged."""
    url = "postgresql://u:p@h:5432/d?options=-csearch_path=optuna&sslmode=require"
    assert _compose_storage_url(url) == url


def test_compose_storage_url_handles_no_userinfo():
    """A bare host URL (no user:pass) works correctly."""
    result = _compose_storage_url("postgresql://localhost:5432/d")
    assert result == "postgresql://localhost:5432/d?options=-csearch_path=optuna"


# ---------------------------------------------------------------------------
# build_storage — monkeypatched RDBStorage; verify the URL passed
# ---------------------------------------------------------------------------


def test_build_storage_calls_rdbstorage_with_composed_url(monkeypatch: pytest.MonkeyPatch):
    """build_storage delegates to RDBStorage(url=_compose_storage_url(...))."""
    recorded: dict[str, Any] = {}

    def fake_rdbstorage(*args: Any, **kwargs: Any) -> object:
        recorded["url"] = kwargs.get("url") or (args[0] if args else None)
        return object()

    monkeypatch.setattr(optuna.storages, "RDBStorage", fake_rdbstorage)

    build_storage("postgresql+asyncpg://u:p@h:5432/d")

    assert recorded["url"] == "postgresql://u:p@h:5432/d?options=-csearch_path=optuna"


# ---------------------------------------------------------------------------
# build_sampler — defaults + explicit + seed forwarding
# ---------------------------------------------------------------------------


def test_build_sampler_defaults_to_tpe_when_key_absent():
    """Spec §FR-2 default: sampler key absent → TPESampler."""
    sampler = build_sampler({}, seed=None)
    assert isinstance(sampler, TPESampler)


def test_build_sampler_forwards_seed_to_tpe():
    """TPESampler receives the seed for reproducibility."""
    sampler = build_sampler({}, seed=42)
    assert isinstance(sampler, TPESampler)
    # Optuna's TPESampler stores seed on _rng. Use the public-ish attr if available.
    # Cross-version-safe check: same seed produces the same first suggestion.
    sampler2 = build_sampler({}, seed=42)
    # Build two trivial studies with each sampler, ask both, and confirm same params.
    study1 = optuna.create_study(sampler=sampler, direction="maximize")
    study2 = optuna.create_study(sampler=sampler2, direction="maximize")
    t1 = study1.ask()
    t1.suggest_float("x", 0.0, 1.0)
    t2 = study2.ask()
    t2.suggest_float("x", 0.0, 1.0)
    assert t1.params == t2.params


def test_build_sampler_explicit_tpe():
    """Explicit ``sampler='tpe'`` → TPESampler."""
    sampler = build_sampler({"sampler": "tpe"}, seed=None)
    assert isinstance(sampler, TPESampler)


def test_build_sampler_random():
    """``sampler='random'`` → RandomSampler (baseline-comparison option)."""
    sampler = build_sampler({"sampler": "random"}, seed=42)
    assert isinstance(sampler, RandomSampler)


def test_build_sampler_rejects_unknown_value():
    """CMA-ES and other MVP2-reserved samplers raise ValueError."""
    with pytest.raises(ValueError, match=r"unsupported sampler 'cma-es'"):
        build_sampler({"sampler": "cma-es"}, seed=None)


# ---------------------------------------------------------------------------
# build_pruner — FR-2 two-pronged contract (AC-6a + AC-6b)
# ---------------------------------------------------------------------------


def test_build_pruner_omitted_with_small_max_trials_is_nop():
    """AC-6a: pruner key absent + max_trials < 50 → NopPruner (safeguard)."""
    pruner = build_pruner({"max_trials": 30})
    assert isinstance(pruner, NopPruner)


def test_build_pruner_omitted_with_large_max_trials_is_median():
    """pruner key absent + max_trials >= 50 → MedianPruner(n_warmup_steps=10)."""
    pruner = build_pruner({"max_trials": 100})
    assert isinstance(pruner, MedianPruner)
    # Verify n_warmup_steps per FR-2 default
    assert pruner._n_warmup_steps == 10


def test_build_pruner_threshold_exactly_50_uses_median():
    """Boundary: max_trials == 50 → MedianPruner (>= 50 is the rule per FR-2)."""
    pruner = build_pruner({"max_trials": 50})
    assert isinstance(pruner, MedianPruner)


def test_build_pruner_explicit_median_overrides_small_study_safeguard():
    """AC-6b: explicit ``pruner='median'`` + max_trials < 50 → MedianPruner.

    Operator override of the small-study auto-disable safeguard.
    """
    pruner = build_pruner({"max_trials": 30, "pruner": "median"})
    assert isinstance(pruner, MedianPruner)


def test_build_pruner_explicit_none():
    """``pruner='none'`` → NopPruner."""
    pruner = build_pruner({"max_trials": 100, "pruner": "none"})
    assert isinstance(pruner, NopPruner)


def test_build_pruner_rejects_unknown_value():
    """Hyperband and other MVP2-reserved pruners raise ValueError."""
    with pytest.raises(ValueError, match=r"unsupported pruner 'hyperband'"):
        build_pruner({"max_trials": 30, "pruner": "hyperband"})


def test_build_pruner_requires_max_trials_when_pruner_omitted():
    """Default-omitted path needs max_trials to apply the safeguard heuristic."""
    with pytest.raises(ValueError, match=r"max_trials is required"):
        build_pruner({})


def test_build_pruner_non_int_max_trials_rejected():
    """max_trials must be an int (JSONB may decode it as float; reject early)."""
    with pytest.raises(ValueError, match=r"max_trials is required"):
        build_pruner({"max_trials": "100"})
