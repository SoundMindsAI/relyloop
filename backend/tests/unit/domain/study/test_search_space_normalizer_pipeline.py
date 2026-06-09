# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``NormalizerPipelineParam`` (feat_query_normalizer_typed_pipeline).

Covers AC-2 (discriminator parse + duplicate rejection + out-of-enum
rejection), AC-3 (cardinality ``2**n`` + cap trip), and AC-4 (exact
sampler label list via ``apply_search_space``).
"""

from __future__ import annotations

import optuna
import pytest
from pydantic import ValidationError

from backend.app.domain.study.search_space import (
    CategoricalParam,
    NormalizerPipelineParam,
    SearchSpace,
    apply_search_space,
    estimate_cardinality,
)


def _space(steps: list[str]) -> SearchSpace:
    return SearchSpace.model_validate(
        {"params": {"query_normalizer": {"type": "normalizer_pipeline", "steps": steps}}}
    )


# --- AC-2: discriminator parse + validation ---------------------------------


def test_discriminator_selects_pipeline_param() -> None:
    space = _space(["lowercase", "trim"])
    spec = space.params["query_normalizer"]
    assert isinstance(spec, NormalizerPipelineParam)
    assert [s.value for s in spec.steps] == ["lowercase", "trim"]


def test_duplicate_steps_rejected_with_named_step() -> None:
    with pytest.raises(ValidationError, match="duplicate step 'lowercase'"):
        NormalizerPipelineParam(type="normalizer_pipeline", steps=["lowercase", "lowercase"])  # type: ignore[list-item]


def test_out_of_enum_step_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizerPipelineParam(type="normalizer_pipeline", steps=["stem"])  # type: ignore[list-item]


def test_empty_steps_rejected_min_length() -> None:
    with pytest.raises(ValidationError):
        NormalizerPipelineParam(type="normalizer_pipeline", steps=[])


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        NormalizerPipelineParam(
            type="normalizer_pipeline",
            steps=["lowercase"],
            bonus="x",  # type: ignore[call-arg]
        )


# --- AC-3: cardinality -------------------------------------------------------


@pytest.mark.parametrize(
    "steps,expected",
    [
        (["lowercase"], 2),
        (["lowercase", "trim"], 4),
        (["lowercase", "trim", "strip_punctuation"], 8),
    ],
)
def test_cardinality_is_two_to_the_n(steps: list[str], expected: int) -> None:
    assert estimate_cardinality(_space(steps)) == expected


def test_cardinality_multiplies_with_other_params() -> None:
    space = SearchSpace.model_validate(
        {
            "params": {
                "operator": {"type": "categorical", "choices": ["and", "or", "phrase"]},
                "query_normalizer": {
                    "type": "normalizer_pipeline",
                    "steps": ["lowercase", "trim"],
                },
            }
        }
    )
    assert estimate_cardinality(space) == 3 * 4


def test_cardinality_cap_trips_for_oversized_pipeline_product() -> None:
    # A 6-step pipeline alone is only 2**6 = 64, so pair it with a big int
    # range so the product exceeds 10^6 and the SearchSpace validator rejects.
    with pytest.raises(ValidationError, match="cardinality estimate exceeds"):
        SearchSpace.model_validate(
            {
                "params": {
                    "n": {"type": "int", "low": 0, "high": 20000},
                    "query_normalizer": {
                        "type": "normalizer_pipeline",
                        "steps": [
                            "lowercase",
                            "trim",
                            "strip_punctuation",
                            "collapse_whitespace",
                            "expand_contractions_en",
                            "expand_contractions_custom",
                        ],
                    },
                }
            }
        )


# --- AC-4: sampler emits the exact powerset label list ----------------------


def test_apply_search_space_samples_exact_powerset_labels() -> None:
    space = _space(["lowercase", "trim"])
    study = optuna.create_study()
    seen: set[str] = set()
    for _ in range(40):
        trial = study.ask()
        suggested = apply_search_space(trial, space)
        seen.add(suggested["query_normalizer"])
        study.tell(trial, 0.0)
    # The distribution's choice list is the canonical powerset list.
    dist = study.trials[0].distributions["query_normalizer"]
    assert list(dist.choices) == ["none", "lowercase", "trim", "lowercase+trim"]
    assert seen <= {"none", "lowercase", "trim", "lowercase+trim"}


def test_categorical_param_still_works_unchanged() -> None:
    # Regression: adding the 4th union member must not break the existing 3.
    space = SearchSpace.model_validate(
        {"params": {"operator": {"type": "categorical", "choices": ["and", "or"]}}}
    )
    assert isinstance(space.params["operator"], CategoricalParam)
    assert estimate_cardinality(space) == 2
