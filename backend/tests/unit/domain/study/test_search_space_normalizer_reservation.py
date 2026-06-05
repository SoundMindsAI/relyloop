# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for validate_normalizer_reservation (FR-2, Story 1.3).

We construct a SearchSpace via model_validate and then call the validator
directly. NOTE (by design): SearchSpace.model_validate alone does NOT enforce
the reservation — Pydantic accepts any CategoricalParam with valid choices.
Only validate_normalizer_reservation enforces the NORMALIZER_CHOICES subset
constraint (spec §3 in-scope bullets), which is why the router invokes it as a
separate step after model_validate.
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.normalizers import (
    NORMALIZER_CHOICES,
    NormalizerChoiceInvalidError,
    NormalizerParamShapeError,
    validate_normalizer_reservation,
)
from backend.app.domain.study.search_space import SearchSpace


def _space(params: dict[str, object]) -> SearchSpace:
    return SearchSpace.model_validate({"params": params})


def test_valid_subset_returns_none() -> None:
    space = _space(
        {"query_normalizer": {"type": "categorical", "choices": ["none", "lowercase+trim"]}}
    )
    validate_normalizer_reservation(space)  # no raise


def test_full_allowlist_is_accepted() -> None:
    space = _space(
        {"query_normalizer": {"type": "categorical", "choices": list(NORMALIZER_CHOICES)}}
    )
    validate_normalizer_reservation(space)  # no raise


def test_absent_key_is_noop() -> None:
    space = _space({"title_boost": {"type": "float", "low": 0.1, "high": 1.0}})
    validate_normalizer_reservation(space)  # no raise (absent key)


def test_bad_choice_raises_choice_invalid_with_spec_message() -> None:
    space = _space({"query_normalizer": {"type": "categorical", "choices": ["none", "stem"]}})
    with pytest.raises(NormalizerChoiceInvalidError) as exc:
        validate_normalizer_reservation(space)
    msg = str(exc.value)
    assert "stem" in msg
    # Exact spec FR-2 format — names the offender + the full allowed set.
    assert (
        msg == "query_normalizer choice 'stem' is not in the allowed set: "
        "['none', 'lowercase', 'lowercase+trim', 'lowercase+trim+expand_contractions']"
    )


def test_wrong_shape_raises_param_shape_naming_actual_type() -> None:
    # query_normalizer declared as a FloatParam, not a CategoricalParam.
    space = _space({"query_normalizer": {"type": "float", "low": 0.1, "high": 1.0}})
    with pytest.raises(NormalizerParamShapeError) as exc:
        validate_normalizer_reservation(space)
    assert "FloatParam" in str(exc.value)
    assert str(exc.value) == "query_normalizer must be CategoricalParam (got FloatParam)"
