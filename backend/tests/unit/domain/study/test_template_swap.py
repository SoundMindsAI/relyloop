"""Unit tests for the ``template_swap`` domain helper (Story 1.2).

Owner: ``feat_digest_executable_followups_swap_template``.

Covers spec §14 unit-test list for FR-3:

- Trusted-intersection-only case.
- Mixed trusted-intersection + disjoint-fill case.
- Empty swap target raises.
- Empty trusted intersection raises (AC-4b).
- Cardinality-cap blowup raises.
- LLM-only param outside ``parent ∩ swap`` lands in ``ignored_llm_param_names``
  and NOT in ``RemapResult.search_space.params`` (cycle-1 F1 regression guard).
- Empty disjoint fill skips ``build_starter_search_space``
  (cycle-1 F2 regression guard).
- ``RemapResult.search_space`` always passes ``SearchSpace.model_validate``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.app.domain.study.search_space import (
    InvalidSearchSpaceError,
    SearchSpace,
)
from backend.app.domain.study.template_swap import (
    RemapResult,
    remap_search_space_for_swap_target,
)


def _ss(params: dict[str, dict[str, Any]]) -> SearchSpace:
    return SearchSpace.model_validate({"params": params})


class TestTrustedIntersection:
    def test_intersection_only_no_disjoint(self) -> None:
        """When swap target's params are a subset of (parent ∩ llm), no
        disjoint fill happens and ``build_starter_search_space`` is NOT
        invoked (cycle-1 F2 regression guard).
        """
        parent = {"title_boost": "float", "tie_breaker": "int"}
        swap = {"title_boost": "float"}
        llm = _ss(
            {
                "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
            }
        )

        with patch(
            "backend.app.domain.study.template_swap.build_starter_search_space"
        ) as mock_builder:
            result = remap_search_space_for_swap_target(
                parent_declared_params=parent,
                swap_target_declared_params=swap,
                llm_search_space=llm,
            )
            mock_builder.assert_not_called()

        assert isinstance(result, RemapResult)
        assert result.trusted_intersection_param_names == ["title_boost"]
        assert result.disjoint_fill_param_names == []
        assert result.dropped_parent_param_names == ["tie_breaker"]
        assert result.ignored_llm_param_names == []
        assert "title_boost" in result.search_space.params
        assert "tie_breaker" not in result.search_space.params

    def test_intersection_param_uses_llm_bounds(self) -> None:
        parent = {"title_boost": "float"}
        swap = {"title_boost": "float"}
        llm = _ss(
            {
                "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
            }
        )
        result = remap_search_space_for_swap_target(
            parent_declared_params=parent,
            swap_target_declared_params=swap,
            llm_search_space=llm,
        )
        title = result.search_space.params["title_boost"]
        # Use model_dump for typed access since ParamSpec is a discriminated
        # union; attribute-access would require a runtime narrow.
        title_dict = title.model_dump()
        assert title_dict["type"] == "float"
        assert title_dict["low"] == 0.5
        assert title_dict["high"] == 2.0


class TestDisjointFill:
    def test_mixed_intersection_and_disjoint_fill(self) -> None:
        """Swap target declares one shared + one new param: shared bounds
        from LLM, new param bounds from build_starter_search_space.
        """
        parent = {"title_boost": "float"}
        swap = {"title_boost": "float", "phrase_slop": "int"}
        llm = _ss(
            {
                "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
            }
        )
        result = remap_search_space_for_swap_target(
            parent_declared_params=parent,
            swap_target_declared_params=swap,
            llm_search_space=llm,
        )
        assert result.trusted_intersection_param_names == ["title_boost"]
        assert result.disjoint_fill_param_names == ["phrase_slop"]
        # phrase_slop got heuristic bounds.
        assert "phrase_slop" in result.search_space.params
        # title_boost preserved LLM bounds.
        title = result.search_space.params["title_boost"]
        assert title.model_dump()["low"] == 0.5
        # Result is constructor-valid.
        SearchSpace.model_validate(result.search_space.model_dump())

    def test_ignored_llm_param_does_not_land_in_result(self) -> None:
        """Cycle-1 F1 regression guard: an LLM-emitted param outside
        ``parent ∩ swap`` lands in ``ignored_llm_param_names`` and is NOT
        present in the merged search_space.params.
        """
        parent = {"title_boost": "float"}
        swap = {"title_boost": "float"}
        # LLM emits an extra param that exists in NEITHER parent nor swap.
        llm = _ss(
            {
                "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
                "rogue_param": {"type": "float", "low": 0.0, "high": 1.0},
            }
        )
        result = remap_search_space_for_swap_target(
            parent_declared_params=parent,
            swap_target_declared_params=swap,
            llm_search_space=llm,
        )
        assert result.ignored_llm_param_names == ["rogue_param"]
        assert "rogue_param" not in result.search_space.params


class TestFailureModes:
    def test_empty_swap_target_raises(self) -> None:
        """AC-4: swap target with no declared params raises."""
        parent = {"title_boost": "float"}
        llm = _ss({"title_boost": {"type": "float", "low": 0.0, "high": 1.0}})
        with pytest.raises(InvalidSearchSpaceError, match="no params"):
            remap_search_space_for_swap_target(
                parent_declared_params=parent,
                swap_target_declared_params={},
                llm_search_space=llm,
            )

    def test_empty_trusted_intersection_raises(self) -> None:
        """AC-4b: no shared parent ∩ swap ∩ llm names raises."""
        parent = {"title_boost": "float"}
        swap = {"phrase_slop": "int"}
        llm = _ss(
            {
                "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
            }
        )
        with pytest.raises(InvalidSearchSpaceError, match="no shared parameters with parent"):
            remap_search_space_for_swap_target(
                parent_declared_params=parent,
                swap_target_declared_params=swap,
                llm_search_space=llm,
            )

    def test_cardinality_cap_blowup_raises(self) -> None:
        """Heuristic disjoint fill that drives total cardinality > 10^6 raises.

        We supply an LLM bound for the shared param with a tiny cardinality,
        then add 20 disjoint float params — heuristic defaults push estimated
        cardinality above the cap.
        """
        parent = {"x": "float"}
        swap = {"x": "float", **{f"d{i}": "float" for i in range(20)}}
        llm = _ss({"x": {"type": "float", "low": 0.0, "high": 1.0}})
        with pytest.raises(InvalidSearchSpaceError):
            remap_search_space_for_swap_target(
                parent_declared_params=parent,
                swap_target_declared_params=swap,
                llm_search_space=llm,
            )
