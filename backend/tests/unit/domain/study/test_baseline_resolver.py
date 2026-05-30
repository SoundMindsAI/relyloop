# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`backend.app.domain.study.baseline_resolver`.

Covers FR-3's 4-tier fallback resolver:

- Tier (d) parent proposal config
- Tier (c) parent study winner
- Tier (b) operator-supplied
- Tier (a) template defaults (middle-of-range)

Plus the fall-through cascades and the log emission for missing-parent
edges (cascade-delete races).
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.db import repo as _db_repo
from backend.app.domain.study import baseline_resolver  # noqa: F401  # exported for symmetry
from backend.app.domain.study.baseline_resolver import (
    _midpoint,
    _resolve_from_operator_supplied,
    _resolve_from_template_defaults,
    resolve_baseline_params,
)
from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
)


def _study(**overrides: Any) -> Any:
    """Build a SimpleNamespace stand-in for a Study row.

    Tests use SimpleNamespace because the resolver is duck-typed (per
    the same pattern as `compute_study_confidence`); no need to construct
    real ORM rows for unit tests.
    """
    base = {
        "id": "study-1",
        "parent_proposal_id": None,
        "parent_study_id": None,
        "config": {},
        "search_space": {
            "params": {
                "boost_title": {"type": "float", "low": 0.5, "high": 10.0},
            }
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Tier (a) — template defaults (pure; no DB)
# ---------------------------------------------------------------------------


class TestTemplateDefaultsMidpoint:
    def test_float_param_linear_midpoint(self) -> None:
        result = _midpoint(FloatParam(type="float", low=0.5, high=10.0, log=False))
        assert result == 5.25

    def test_float_param_log_midpoint_geometric_mean(self) -> None:
        # sqrt(0.1 * 10.0) = 1.0
        result = _midpoint(FloatParam(type="float", low=0.1, high=10.0, log=True))
        assert math.isclose(result, 1.0)

    def test_int_param_lower_midpoint_for_even_range(self) -> None:
        # (1 + 4) // 2 = 2 — lower midpoint between 2 and 3.
        result = _midpoint(IntParam(type="int", low=1, high=4))
        assert result == 2

    def test_int_param_midpoint_for_odd_range(self) -> None:
        # (1 + 5) // 2 = 3 — true median.
        result = _midpoint(IntParam(type="int", low=1, high=5))
        assert result == 3

    def test_categorical_param_lower_midpoint_for_even_choices(self) -> None:
        # ['a', 'b'] → (2-1)//2 = 0 → 'a' (lower midpoint).
        result = _midpoint(CategoricalParam(type="categorical", choices=["a", "b"]))
        assert result == "a"

    def test_categorical_param_lower_midpoint_for_four_choices(self) -> None:
        # ['a','b','c','d'] → (4-1)//2 = 1 → 'b' (lower midpoint between b/c).
        result = _midpoint(CategoricalParam(type="categorical", choices=["a", "b", "c", "d"]))
        assert result == "b"

    def test_categorical_param_median_for_odd_choices(self) -> None:
        # ['a','b','c'] → (3-1)//2 = 1 → 'b' (true median).
        result = _midpoint(CategoricalParam(type="categorical", choices=["a", "b", "c"]))
        assert result == "b"

    def test_template_defaults_returns_dict_for_multi_param_space(self) -> None:
        study = _study(
            search_space={
                "params": {
                    "boost_title": {"type": "float", "low": 0.5, "high": 10.0},
                    "min_should_match": {"type": "int", "low": 1, "high": 5},
                    "operator": {
                        "type": "categorical",
                        "choices": ["and", "or"],
                    },
                }
            }
        )
        result = _resolve_from_template_defaults(study)
        assert result == {
            "boost_title": 5.25,
            "min_should_match": 3,
            "operator": "and",  # lower midpoint of ['and','or']
        }


# ---------------------------------------------------------------------------
# Tier (b) — operator-supplied
# ---------------------------------------------------------------------------


class TestOperatorSupplied:
    def test_returns_dict_when_baseline_params_present(self) -> None:
        study = _study(config={"baseline_params": {"boost_title": 1.5}})
        assert _resolve_from_operator_supplied(study) == {"boost_title": 1.5}

    def test_returns_none_when_config_absent(self) -> None:
        study = _study(config={})
        assert _resolve_from_operator_supplied(study) is None

    def test_returns_none_when_baseline_params_null(self) -> None:
        study = _study(config={"baseline_params": None})
        assert _resolve_from_operator_supplied(study) is None

    def test_returns_none_when_baseline_params_empty_dict(self) -> None:
        # Empty dict means operator-supplied is treated as not-supplied;
        # resolver falls through to template defaults.
        study = _study(config={"baseline_params": {}})
        assert _resolve_from_operator_supplied(study) is None

    def test_returns_copy_not_alias(self) -> None:
        original = {"boost_title": 1.5}
        study = _study(config={"baseline_params": original})
        result = _resolve_from_operator_supplied(study)
        assert result == original
        assert result is not original  # defensive copy


# ---------------------------------------------------------------------------
# Top-level resolver — async dispatch through the 4 tiers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> Any:
    """Mock AsyncSession — never actually executes SQL because we
    monkeypatch repo functions."""
    return AsyncMock()


class TestTopLevelResolver:
    async def test_tier_d_parent_proposal_hits_when_set(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        study = _study(parent_proposal_id="proposal-1")
        proposal = SimpleNamespace(id="proposal-1", study_trial_id="trial-1")
        trial = SimpleNamespace(id="trial-1", params={"boost_title": 7.7})

        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=proposal),
        )
        monkeypatch.setattr(_db_repo, "get_trial", AsyncMock(return_value=trial))

        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 7.7}

    async def test_tier_d_falls_through_when_proposal_missing(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        study = _study(parent_proposal_id="proposal-missing")
        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=None),
        )
        # Falls through to tier (a) template defaults.
        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 5.25}

    async def test_tier_d_falls_through_when_trial_missing(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        study = _study(parent_proposal_id="proposal-1")
        proposal = SimpleNamespace(id="proposal-1", study_trial_id="trial-missing")
        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=proposal),
        )
        monkeypatch.setattr(_db_repo, "get_trial", AsyncMock(return_value=None))
        result = await resolve_baseline_params(mock_db, study)
        # Falls through to tier (a).
        assert result == {"boost_title": 5.25}

    async def test_tier_d_falls_through_when_proposal_has_no_study_trial_id(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        study = _study(parent_proposal_id="proposal-1")
        proposal = SimpleNamespace(id="proposal-1", study_trial_id=None)
        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=proposal),
        )
        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 5.25}

    async def test_tier_c_parent_study_winner_hits_when_set(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        study = _study(parent_study_id="parent-1")
        parent = SimpleNamespace(id="parent-1", best_trial_id="best-1")
        trial = SimpleNamespace(id="best-1", params={"boost_title": 3.3})

        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=parent))
        monkeypatch.setattr(_db_repo, "get_trial", AsyncMock(return_value=trial))

        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 3.3}

    async def test_tier_c_falls_through_when_parent_missing(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        study = _study(parent_study_id="parent-missing")
        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=None))
        result = await resolve_baseline_params(mock_db, study)
        # Falls through to tier (a).
        assert result == {"boost_title": 5.25}

    async def test_tier_b_operator_supplied_hits_when_present(self, mock_db: Any) -> None:
        study = _study(config={"baseline_params": {"boost_title": 1.5}})
        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 1.5}

    async def test_tier_a_falls_through_to_template_defaults(self, mock_db: Any) -> None:
        study = _study()  # no parent, no operator override
        result = await resolve_baseline_params(mock_db, study)
        # Tier (a) midpoint of [0.5, 10.0] = 5.25.
        assert result == {"boost_title": 5.25}

    async def test_full_fall_through_d_to_c_to_b_to_a(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier (d) misses → tier (c) misses → tier (b) present → returns tier (b)."""
        study = _study(
            parent_proposal_id="proposal-missing",
            parent_study_id="parent-missing",
            config={"baseline_params": {"boost_title": 2.2}},
        )
        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=None))
        result = await resolve_baseline_params(mock_db, study)
        assert result == {"boost_title": 2.2}

    async def test_tier_priority_d_beats_b(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both tier (d) and tier (b) are present, (d) wins."""
        study = _study(
            parent_proposal_id="proposal-1",
            config={"baseline_params": {"boost_title": 99.9}},
        )
        proposal = SimpleNamespace(id="proposal-1", study_trial_id="trial-1")
        trial = SimpleNamespace(id="trial-1", params={"boost_title": 7.7})
        monkeypatch.setattr(
            _db_repo,
            "get_proposal",
            AsyncMock(return_value=proposal),
        )
        monkeypatch.setattr(_db_repo, "get_trial", AsyncMock(return_value=trial))
        result = await resolve_baseline_params(mock_db, study)
        # Tier (d) wins, not 99.9.
        assert result == {"boost_title": 7.7}


# ---------------------------------------------------------------------------
# Defense-in-depth — empty search space
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_param_type_raises_typeerror(self) -> None:
        """The resolver dispatches on concrete subtypes; an unknown type
        should fail loud rather than silently returning None."""

        class UnknownParam:
            pass

        with pytest.raises(TypeError, match="unknown ParamSpec subtype"):
            _midpoint(UnknownParam())  # type: ignore[arg-type]
