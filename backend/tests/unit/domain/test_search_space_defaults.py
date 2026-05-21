"""Unit tests for :mod:`backend.app.domain.study.search_space_defaults`.

Covers FR-1 (heuristic + overflow guard), FR-3 (narrowing math + skip rules),
FR-4 (cardinality non-increasing invariant) per
``docs/02_product/planned_features/feat_agent_propose_search_space/feature_spec.md``.

The TS↔Python parity assertions live in
``test_search_space_defaults_parity.py`` (Story 1.3). These tests cover the
Python-only branches (e.g., the logger.warning emission, the exception types).
"""

from __future__ import annotations

import logging
import math

import pytest

from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    InvalidSearchSpaceError,
    SearchSpace,
    estimate_cardinality,
)
from backend.app.domain.study.search_space_defaults import (
    HEURISTIC_RULES,
    StarterSearchSpace,
    build_starter_search_space,
    estimate_param_cardinality,
    narrow_bounds_around_winner,
    simple_form_spec,
)

# ---------------------------------------------------------------------------
# simple_form_spec
# ---------------------------------------------------------------------------


class TestSimpleFormSpec:
    def test_int(self) -> None:
        spec = simple_form_spec("int")
        assert isinstance(spec, IntParam)
        assert spec.low == 0 and spec.high == 5

    def test_float(self) -> None:
        spec = simple_form_spec("float")
        assert isinstance(spec, FloatParam)
        assert spec.low == 0.0 and spec.high == 1.0 and spec.log is False

    def test_bool(self) -> None:
        spec = simple_form_spec("bool")
        assert isinstance(spec, CategoricalParam)
        assert spec.choices == [True, False]

    def test_string(self) -> None:
        spec = simple_form_spec("string")
        assert isinstance(spec, CategoricalParam)
        assert spec.choices == ["__placeholder__"]

    def test_unknown(self) -> None:
        assert simple_form_spec("matrix") is None


# ---------------------------------------------------------------------------
# estimate_param_cardinality
# ---------------------------------------------------------------------------


class TestEstimateParamCardinality:
    def test_float_is_100(self) -> None:
        assert estimate_param_cardinality(FloatParam(type="float", low=0.0, high=1.0)) == 100

    def test_float_log_is_100(self) -> None:
        assert (
            estimate_param_cardinality(FloatParam(type="float", low=0.5, high=10.0, log=True))
            == 100
        )

    def test_int_range_plus_one(self) -> None:
        assert estimate_param_cardinality(IntParam(type="int", low=0, high=5)) == 6
        assert estimate_param_cardinality(IntParam(type="int", low=2, high=2)) == 1

    def test_categorical_length(self) -> None:
        assert (
            estimate_param_cardinality(
                CategoricalParam(type="categorical", choices=["a", "b", "c"])
            )
            == 3
        )


# ---------------------------------------------------------------------------
# HEURISTIC_RULES — every rule produces the expected spec
# ---------------------------------------------------------------------------


class TestHeuristicRules:
    @pytest.mark.parametrize(
        "name",
        ["field_boost_title", "field_boost_xxx", "boost_title", "boost_description"],
    )
    def test_field_boost_prefix(self, name: str) -> None:
        result = build_starter_search_space({name: "float"})
        spec = result.space.params[name]
        assert isinstance(spec, FloatParam)
        assert spec.low == 0.5 and spec.high == 10.0 and spec.log is True

    @pytest.mark.parametrize("name", ["boost", "title_boost", "description_boost"])
    def test_boost_standalone_or_suffix(self, name: str) -> None:
        result = build_starter_search_space({name: "float"})
        spec = result.space.params[name]
        assert isinstance(spec, FloatParam)
        assert spec.low == 0.5 and spec.high == 10.0 and spec.log is True

    @pytest.mark.parametrize("name", ["tie_breaker", "title_weight", "doc_weight"])
    def test_tie_breaker_and_weight(self, name: str) -> None:
        result = build_starter_search_space({name: "float"})
        spec = result.space.params[name]
        assert isinstance(spec, FloatParam)
        assert spec.low == 0.0 and spec.high == 1.0 and spec.log is False

    @pytest.mark.parametrize("name", ["slop", "min_should_match", "phrase_size", "window_size"])
    def test_slop_and_size(self, name: str) -> None:
        result = build_starter_search_space({name: "int"})
        spec = result.space.params[name]
        assert isinstance(spec, IntParam)
        assert spec.low == 0 and spec.high == 5

    def test_fuzziness(self) -> None:
        result = build_starter_search_space({"fuzziness": "string"})
        spec = result.space.params["fuzziness"]
        assert isinstance(spec, CategoricalParam)
        assert spec.choices == ["AUTO", "0", "1", "2"]

    def test_rule_order_count(self) -> None:
        """Lock the rule count so adding a rule requires updating tests + fixture."""
        assert len(HEURISTIC_RULES) == 5


# ---------------------------------------------------------------------------
# build_starter_search_space — fall-through + cap-aware fallback + overflow
# ---------------------------------------------------------------------------


class TestBuildStarterSearchSpace:
    def test_empty_declared_params_raises(self) -> None:
        with pytest.raises(InvalidSearchSpaceError, match="empty declared_params"):
            build_starter_search_space({})

    def test_fall_through_simple_form_int(self) -> None:
        result = build_starter_search_space({"some_thing": "int"})
        spec = result.space.params["some_thing"]
        assert isinstance(spec, IntParam) and spec.low == 0 and spec.high == 5

    def test_fall_through_simple_form_float(self) -> None:
        result = build_starter_search_space({"odd_name": "float"})
        spec = result.space.params["odd_name"]
        assert isinstance(spec, FloatParam) and spec.low == 0.0 and spec.high == 1.0

    def test_returns_starter_dataclass(self) -> None:
        result = build_starter_search_space({"x": "int"})
        assert isinstance(result, StarterSearchSpace)
        assert isinstance(result.space, SearchSpace)
        assert result.cap_aware_fallback_param_names == []

    def test_cap_aware_fallback_fires_safe(self, caplog: pytest.LogCaptureFixture) -> None:
        """4 fall-through floats → cardinality 100^4 = 10^8 > 10^6. Convert 2 in lex order →
        cardinality 6^2 * 100^2 = 360_000 ≤ 10^6."""
        caplog.set_level(logging.WARNING, logger="backend.app.domain.study.search_space_defaults")
        result = build_starter_search_space(
            {"alpha": "float", "beta": "float", "gamma": "float", "delta": "float"}
        )
        # Lex order: alpha, beta, delta, gamma. First 2 converted.
        assert result.cap_aware_fallback_param_names == ["alpha", "beta"]
        assert isinstance(result.space.params["alpha"], IntParam)
        assert isinstance(result.space.params["beta"], IntParam)
        assert isinstance(result.space.params["gamma"], FloatParam)
        assert isinstance(result.space.params["delta"], FloatParam)
        assert estimate_cardinality(result.space) == 6 * 6 * 100 * 100
        assert any("cap_aware_fallback fired" in record.message for record in caplog.records)

    def test_cap_aware_overflow_raises(self) -> None:
        """8 fall-through floats → after all 8 converted to int[0,5], cardinality is 6^8 =
        1_679_616 > 10^6. Helper raises."""
        with pytest.raises(InvalidSearchSpaceError, match="cap-aware fallback exhausted"):
            build_starter_search_space({chr(ord("a") + i): "float" for i in range(8)})

    def test_cap_aware_prefers_fall_through_before_regex_matched(self) -> None:
        """Mix of fall-through floats + regex-matched floats — fall-through gets converted first."""
        result = build_starter_search_space(
            {"alpha": "float", "title_boost": "float", "tie_breaker": "float", "zzz": "float"}
        )
        # 4 floats. Lex within fall-through: alpha, zzz. Lex within regex: tie_breaker, title_boost.
        # Cardinality before any conversion: 100^4 = 10^8 > 10^6.
        # After 1 conversion: 6 * 100^3 = 6_000_000 > 10^6.
        # After 2 conversions: 6^2 * 100^2 = 360_000 ≤ 10^6.
        # Fall-through come first → alpha (lex first among fall-through) then zzz.
        assert result.cap_aware_fallback_param_names == ["alpha", "zzz"]


# ---------------------------------------------------------------------------
# narrow_bounds_around_winner — math + skip rules + non-increasing invariant
# ---------------------------------------------------------------------------


class TestNarrowBoundsAroundWinner:
    def test_linear_float_50_percent(self) -> None:
        """tie_breaker starter [0, 1], winner 0.4 → narrowed to [0.2, 0.6]."""
        space = SearchSpace(params={"tie_breaker": FloatParam(type="float", low=0.0, high=1.0)})
        narrowed, names = narrow_bounds_around_winner(space, {"tie_breaker": 0.4})
        assert names == ["tie_breaker"]
        spec = narrowed.params["tie_breaker"]
        assert isinstance(spec, FloatParam)
        assert spec.low == pytest.approx(0.2)
        assert spec.high == pytest.approx(0.6)

    def test_log_uniform_float_sqrt2(self) -> None:
        """title_boost starter [0.5, 10] log-uniform, winner 2.0 → [2/√2, 2*√2]."""
        space = SearchSpace(
            params={"title_boost": FloatParam(type="float", low=0.5, high=10.0, log=True)}
        )
        narrowed, names = narrow_bounds_around_winner(space, {"title_boost": 2.0})
        assert names == ["title_boost"]
        spec = narrowed.params["title_boost"]
        assert isinstance(spec, FloatParam) and spec.log is True
        assert spec.low == pytest.approx(2.0 / math.sqrt(2))
        assert spec.high == pytest.approx(2.0 * math.sqrt(2))

    def test_int_param_50_percent(self) -> None:
        """min_should_match starter [0, 10], winner 4 → [floor(4*0.5), ceil(4*1.5)] = [2, 6]."""
        space = SearchSpace(params={"min_should_match": IntParam(type="int", low=0, high=10)})
        narrowed, names = narrow_bounds_around_winner(space, {"min_should_match": 4})
        assert names == ["min_should_match"]
        spec = narrowed.params["min_should_match"]
        assert isinstance(spec, IntParam)
        assert spec.low == 2 and spec.high == 6

    def test_winner_at_low_boundary_skipped(self) -> None:
        """Winner equal to low → out of bounds; skip."""
        space = SearchSpace(params={"tie_breaker": FloatParam(type="float", low=0.0, high=1.0)})
        narrowed, names = narrow_bounds_around_winner(space, {"tie_breaker": 0.0})
        assert names == []
        assert narrowed.params["tie_breaker"] == space.params["tie_breaker"]

    def test_winner_above_high_skipped(self) -> None:
        """Winner outside the bracket → skipped (no exception)."""
        space = SearchSpace(params={"min_should_match": IntParam(type="int", low=0, high=5)})
        narrowed, names = narrow_bounds_around_winner(space, {"min_should_match": 8})
        assert names == []
        assert narrowed.params["min_should_match"] == space.params["min_should_match"]

    def test_categorical_not_narrowed(self) -> None:
        space = SearchSpace(
            params={"fuzziness": CategoricalParam(type="categorical", choices=["AUTO", "1", "2"])}
        )
        narrowed, names = narrow_bounds_around_winner(space, {"fuzziness": "1"})
        assert names == []
        assert narrowed.params["fuzziness"].choices == ["AUTO", "1", "2"]  # type: ignore[union-attr]

    def test_non_numeric_winner_skipped(self) -> None:
        """Winner stored as a string for an int param (template-shape drift) → skip safely."""
        space = SearchSpace(params={"x": IntParam(type="int", low=0, high=10)})
        narrowed, names = narrow_bounds_around_winner(space, {"x": "not-a-number"})
        assert names == []

    def test_bool_winner_for_int_skipped(self) -> None:
        """``True`` is technically an int in Python — guard via ``isinstance(... bool)``."""
        space = SearchSpace(params={"x": IntParam(type="int", low=0, high=10)})
        narrowed, names = narrow_bounds_around_winner(space, {"x": True})
        assert names == []

    def test_param_not_in_winner_passes_through(self) -> None:
        """Param exists in space but not in winning_params → untouched."""
        space = SearchSpace(
            params={
                "a": FloatParam(type="float", low=0.0, high=1.0),
                "b": IntParam(type="int", low=0, high=10),
            }
        )
        narrowed, names = narrow_bounds_around_winner(space, {"a": 0.4})
        assert names == ["a"]
        assert narrowed.params["b"] == space.params["b"]

    def test_no_overlap_returns_original_space(self) -> None:
        """Empty winning_params → returns original space + empty names."""
        space = SearchSpace(params={"a": FloatParam(type="float", low=0.0, high=1.0)})
        narrowed, names = narrow_bounds_around_winner(space, {})
        assert names == []
        # Same SearchSpace instance is acceptable since the function short-circuits.
        assert narrowed is space or narrowed.params == space.params

    def test_cardinality_non_increasing(self) -> None:
        """FR-4 invariant: cardinality_after <= cardinality_before for every input."""
        space = SearchSpace(
            params={
                "a": FloatParam(type="float", low=0.0, high=1.0),
                "b": IntParam(type="int", low=0, high=10),
                "c": CategoricalParam(type="categorical", choices=["x", "y", "z"]),
            }
        )
        before = estimate_cardinality(space)
        narrowed, _ = narrow_bounds_around_winner(space, {"a": 0.4, "b": 5})
        after = estimate_cardinality(narrowed)
        assert after <= before


# ---------------------------------------------------------------------------
# Integration: build_starter_search_space → narrow_bounds_around_winner chain
# ---------------------------------------------------------------------------


class TestChain:
    def test_starter_then_narrow_preserves_cardinality_cap(self) -> None:
        """A space that passes the build_starter cap MUST still pass after narrowing."""
        declared: dict[str, str] = {
            "title_boost": "float",  # log-uniform [0.5, 10]
            "min_should_match": "int",  # [0, 5]
            "fuzziness": "string",  # categorical 4-way
        }
        starter = build_starter_search_space(declared)
        before = estimate_cardinality(starter.space)
        narrowed, names = narrow_bounds_around_winner(
            starter.space, {"title_boost": 2.0, "min_should_match": 3}
        )
        after = estimate_cardinality(narrowed)
        assert after <= before <= 1_000_000
        assert "title_boost" in names and "min_should_match" in names
