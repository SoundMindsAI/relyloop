# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``backend.app.domain.study.search_space`` unit tests (Story 1.1).

Covers Pydantic schema validation (legal + illegal inputs), cardinality
cap (spec §10 Threat 1), and the ``apply_search_space`` Optuna mapping.
The mapping test uses an in-memory Optuna study so we exercise the
real ``suggest_*`` API rather than a mocked trial — Optuna sampling is
fast enough that a unit test can afford it.
"""

from __future__ import annotations

import optuna
import pytest
from pydantic import ValidationError

from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    SearchSpace,
    apply_search_space,
    estimate_cardinality,
)


def _make_in_memory_trial() -> optuna.Trial:
    """Build a single Optuna trial backed by in-memory storage.

    ``study.ask()`` returns a ``FrozenTrial`` we can hand to ``apply_search_space``
    so the suggest_* calls drive real sampler semantics.
    """
    study = optuna.create_study(direction="maximize")
    return study.ask()


def test_minimal_float_param() -> None:
    s = SearchSpace.model_validate(
        {"params": {"boost": {"type": "float", "low": 0.1, "high": 10.0}}}
    )
    assert isinstance(s.params["boost"], FloatParam)
    assert s.params["boost"].low == 0.1


def test_minimal_int_param() -> None:
    s = SearchSpace.model_validate({"params": {"k": {"type": "int", "low": 1, "high": 5}}})
    assert isinstance(s.params["k"], IntParam)
    assert s.params["k"].high == 5


def test_minimal_categorical_param() -> None:
    s = SearchSpace.model_validate(
        {"params": {"op": {"type": "categorical", "choices": ["and", "or"]}}}
    )
    assert isinstance(s.params["op"], CategoricalParam)
    assert s.params["op"].choices == ["and", "or"]


def test_discriminator_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        SearchSpace.model_validate({"params": {"x": {"type": "cma_es", "low": 0, "high": 1}}})


def test_float_param_rejects_low_ge_high() -> None:
    with pytest.raises(ValidationError, match="low.*must be < high"):
        SearchSpace.model_validate({"params": {"x": {"type": "float", "low": 1.0, "high": 0.5}}})


def test_int_param_rejects_low_gt_high() -> None:
    with pytest.raises(ValidationError, match="low.*must be <= high"):
        SearchSpace.model_validate({"params": {"x": {"type": "int", "low": 10, "high": 1}}})


def test_log_uniform_requires_positive_low() -> None:
    with pytest.raises(ValidationError, match="low must be > 0"):
        SearchSpace.model_validate(
            {"params": {"x": {"type": "float", "low": 0.0, "high": 10.0, "log": True}}}
        )


def test_empty_params_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchSpace.model_validate({"params": {}})


def test_empty_categorical_choices_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchSpace.model_validate({"params": {"op": {"type": "categorical", "choices": []}}})


def test_cardinality_at_boundary_passes() -> None:
    # 99 (int range) * 99 (int range) * 100 (float) = 980,100 — under 10^6.
    SearchSpace.model_validate(
        {
            "params": {
                "a": {"type": "int", "low": 1, "high": 99},
                "b": {"type": "int", "low": 1, "high": 99},
                "c": {"type": "float", "low": 0.1, "high": 10.0},
            }
        }
    )


def test_cardinality_over_boundary_rejected() -> None:
    # 100 (int range) * 100 (int range) * 101 (int range) = 1,020,000 — over 10^6.
    with pytest.raises(ValidationError, match="cardinality estimate exceeds 10\\^6"):
        SearchSpace.model_validate(
            {
                "params": {
                    "a": {"type": "int", "low": 1, "high": 100},
                    "b": {"type": "int", "low": 1, "high": 100},
                    "c": {"type": "int", "low": 1, "high": 101},
                }
            }
        )


def test_estimate_cardinality_float_categorical_int() -> None:
    s = SearchSpace.model_validate(
        {
            "params": {
                "boost": {"type": "float", "low": 0.1, "high": 10.0},
                "op": {"type": "categorical", "choices": ["and", "or", "xor"]},
                "k": {"type": "int", "low": 1, "high": 5},
            }
        }
    )
    # float=100 * categorical=3 * int=5 = 1500
    assert estimate_cardinality(s) == 1500


def test_apply_search_space_returns_suggested_values() -> None:
    space = SearchSpace.model_validate(
        {
            "params": {
                "boost": {"type": "float", "low": 0.1, "high": 10.0},
                "k": {"type": "int", "low": 1, "high": 5},
                "op": {"type": "categorical", "choices": ["and", "or"]},
            }
        }
    )
    trial = _make_in_memory_trial()
    suggested = apply_search_space(trial, space)

    assert set(suggested.keys()) == {"boost", "k", "op"}
    assert 0.1 <= suggested["boost"] <= 10.0
    assert 1 <= suggested["k"] <= 5
    assert suggested["op"] in {"and", "or"}


def test_apply_search_space_log_uniform_bounds() -> None:
    space = SearchSpace.model_validate(
        {"params": {"lr": {"type": "float", "low": 1e-4, "high": 1.0, "log": True}}}
    )
    trial = _make_in_memory_trial()
    suggested = apply_search_space(trial, space)
    assert 1e-4 <= suggested["lr"] <= 1.0
