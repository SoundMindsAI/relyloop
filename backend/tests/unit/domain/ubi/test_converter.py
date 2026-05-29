"""Unit tests for ``backend.app.domain.ubi.converter`` (feat_ubi_judgments
Story 1.2 / FR-2).

Pure-domain — no DB, no HTTP, no openai. Asserts:

* CtrThresholdConverter maps the canonical default-threshold boundary
  values to {0, 1, 2, 3} exactly
* DwellTimeThresholdConverter does the same on its scale
* HybridUbiLlmConverter partitions head/tail correctly at the default
  llm_fill_threshold, calls the inner converter only on head, awaits
  the injected llm_rate callback only on tail, and merges results
  without dropping or double-counting
* Threshold override via ConverterConfig.extra['thresholds'] applied
* Threshold override validation: rejects non-dict, missing keys,
  non-monotonic values, non-numeric values, non-1/2/3 keys
* All-pairs-below-threshold hybrid → 100% LLM-fill
* Head-only hybrid → 0% LLM-fill (callback never awaited)
* HybridUbiLlmConverter.build_inner factory resolves correctly + raises
  on unknown kind
* Hybrid llm_fill_threshold override validation
* Pairs with impression_count == 0 routed to LLM-fill (hybrid) /
  dropped (pure UBI)
"""

from __future__ import annotations

import pytest

from backend.app.domain.ubi.converter import (
    ConverterConfig,
    CtrThresholdConverter,
    DwellTimeThresholdConverter,
    HybridUbiLlmConverter,
    LlmRateCallback,
)
from backend.app.domain.ubi.features import FeatureVec


def _fv(
    *,
    click_count: int = 0,
    impression_count: int = 0,
    corrected_ctr: float = 0.0,
    dwell_mean_seconds: float | None = None,
) -> FeatureVec:
    return FeatureVec(
        click_count=click_count,
        impression_count=impression_count,
        corrected_ctr=corrected_ctr,
        dwell_mean_seconds=dwell_mean_seconds,
    )


# ---------------------------------------------------------------------------
# CtrThresholdConverter
# ---------------------------------------------------------------------------


class TestCtrThresholdConverter:
    @pytest.mark.asyncio
    async def test_default_thresholds_boundary_values(self) -> None:
        # Default thresholds: {1: 0.05, 2: 0.15, 3: 0.30}.
        # Boundary semantics: strict <; threshold value itself earns the
        # next-higher rating (verified explicitly below).
        converter = CtrThresholdConverter()
        features = {
            ("q1", "d_zero"): _fv(impression_count=10, corrected_ctr=0.04),  # below 0.05 → 0
            ("q1", "d_low"): _fv(impression_count=10, corrected_ctr=0.05),  # == 0.05 → 1
            ("q1", "d_mid"): _fv(impression_count=10, corrected_ctr=0.10),  # 0.05 ≤ x < 0.15 → 1
            ("q1", "d_hi"): _fv(impression_count=10, corrected_ctr=0.20),  # 0.15 ≤ x < 0.30 → 2
            ("q1", "d_top"): _fv(impression_count=10, corrected_ctr=0.40),  # >= 0.30 → 3
            ("q1", "d_boundary_top"): _fv(impression_count=10, corrected_ctr=0.30),  # == 0.30 → 3
        }
        out = await converter.convert(features, ConverterConfig())
        assert out[("q1", "d_zero")] == 0
        assert out[("q1", "d_low")] == 1
        assert out[("q1", "d_mid")] == 1
        assert out[("q1", "d_hi")] == 2
        assert out[("q1", "d_top")] == 3
        assert out[("q1", "d_boundary_top")] == 3

    @pytest.mark.asyncio
    async def test_drops_pairs_with_zero_impressions(self) -> None:
        converter = CtrThresholdConverter()
        features = {
            ("q1", "d_no_impressions"): _fv(impression_count=0, corrected_ctr=0.0),
            ("q1", "d_present"): _fv(impression_count=10, corrected_ctr=0.20),
        }
        out = await converter.convert(features, ConverterConfig())
        assert ("q1", "d_no_impressions") not in out
        assert out[("q1", "d_present")] == 2

    @pytest.mark.asyncio
    async def test_threshold_override(self) -> None:
        converter = CtrThresholdConverter()
        config = ConverterConfig(extra={"thresholds": {1: 0.10, 2: 0.20, 3: 0.50}})
        features = {
            ("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.05),  # below 0.10 → 0
            ("q1", "d2"): _fv(impression_count=10, corrected_ctr=0.15),  # 0.10..0.20 → 1
            ("q1", "d3"): _fv(impression_count=10, corrected_ctr=0.30),  # 0.20..0.50 → 2
            ("q1", "d4"): _fv(impression_count=10, corrected_ctr=0.60),  # >= 0.50 → 3
        }
        out = await converter.convert(features, config)
        assert out[("q1", "d1")] == 0
        assert out[("q1", "d2")] == 1
        assert out[("q1", "d3")] == 2
        assert out[("q1", "d4")] == 3

    @pytest.mark.asyncio
    async def test_empty_features_returns_empty(self) -> None:
        out = await CtrThresholdConverter().convert({}, ConverterConfig())
        assert out == {}


# ---------------------------------------------------------------------------
# DwellTimeThresholdConverter
# ---------------------------------------------------------------------------


class TestDwellTimeThresholdConverter:
    @pytest.mark.asyncio
    async def test_default_thresholds_boundary_values(self) -> None:
        # Default thresholds: {1: 10.0, 2: 30.0, 3: 90.0}.
        converter = DwellTimeThresholdConverter()
        features = {
            ("q1", "d_zero"): _fv(impression_count=10, dwell_mean_seconds=5.0),  # below 10 → 0
            ("q1", "d_low"): _fv(impression_count=10, dwell_mean_seconds=10.0),  # == 10 → 1
            ("q1", "d_mid"): _fv(impression_count=10, dwell_mean_seconds=15.0),  # 10..30 → 1
            ("q1", "d_hi"): _fv(impression_count=10, dwell_mean_seconds=60.0),  # 30..90 → 2
            ("q1", "d_top"): _fv(impression_count=10, dwell_mean_seconds=120.0),  # >= 90 → 3
            ("q1", "d_top_boundary"): _fv(
                impression_count=10, dwell_mean_seconds=90.0
            ),  # == 90 → 3
        }
        out = await converter.convert(features, ConverterConfig())
        assert out[("q1", "d_zero")] == 0
        assert out[("q1", "d_low")] == 1
        assert out[("q1", "d_mid")] == 1
        assert out[("q1", "d_hi")] == 2
        assert out[("q1", "d_top")] == 3
        assert out[("q1", "d_top_boundary")] == 3

    @pytest.mark.asyncio
    async def test_drops_pairs_with_no_dwell_signal(self) -> None:
        converter = DwellTimeThresholdConverter()
        features = {
            ("q1", "d_no_dwell"): _fv(impression_count=10, dwell_mean_seconds=None),
            ("q1", "d_with_dwell"): _fv(impression_count=10, dwell_mean_seconds=60.0),
        }
        out = await converter.convert(features, ConverterConfig())
        assert ("q1", "d_no_dwell") not in out
        assert out[("q1", "d_with_dwell")] == 2


# ---------------------------------------------------------------------------
# Threshold-override validation (shared resolver)
# ---------------------------------------------------------------------------


class TestThresholdOverrideValidation:
    @pytest.mark.asyncio
    async def test_thresholds_not_a_dict_raises(self) -> None:
        config = ConverterConfig(extra={"thresholds": [0.05, 0.15, 0.30]})
        with pytest.raises(ValueError, match="must be a dict"):
            await CtrThresholdConverter().convert(
                {("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.20)}, config
            )

    @pytest.mark.asyncio
    async def test_thresholds_missing_keys_raises(self) -> None:
        config = ConverterConfig(extra={"thresholds": {1: 0.05, 2: 0.15}})  # missing 3
        with pytest.raises(ValueError, match="missing required keys"):
            await CtrThresholdConverter().convert(
                {("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.20)}, config
            )

    @pytest.mark.asyncio
    async def test_thresholds_non_monotonic_raises(self) -> None:
        config = ConverterConfig(extra={"thresholds": {1: 0.30, 2: 0.20, 3: 0.10}})
        with pytest.raises(ValueError, match="strictly increasing"):
            await CtrThresholdConverter().convert(
                {("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.20)}, config
            )

    @pytest.mark.asyncio
    async def test_thresholds_non_numeric_value_raises(self) -> None:
        config = ConverterConfig(extra={"thresholds": {1: "low", 2: 0.15, 3: 0.30}})
        with pytest.raises(ValueError, match="not a number"):
            await CtrThresholdConverter().convert(
                {("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.20)}, config
            )

    @pytest.mark.asyncio
    async def test_thresholds_extra_key_raises(self) -> None:
        # Rating 0 is implicit (below the rating-1 threshold) — explicit 0 in
        # the override dict is treated as invalid.
        config = ConverterConfig(extra={"thresholds": {0: 0.0, 1: 0.05, 2: 0.15, 3: 0.30}})
        with pytest.raises(ValueError, match="must be 1, 2, or 3"):
            await CtrThresholdConverter().convert(
                {("q1", "d1"): _fv(impression_count=10, corrected_ctr=0.20)}, config
            )


# ---------------------------------------------------------------------------
# HybridUbiLlmConverter
# ---------------------------------------------------------------------------


def _make_query_text_lookup(mapping: dict[str, str]):
    def _lookup(query_id: str) -> str:
        return mapping[query_id]

    return _lookup


def _make_recording_llm_rate(
    canned: dict[tuple[str, str], int],
) -> tuple[list[list[tuple[str, str, str]]], LlmRateCallback]:
    """Returns (calls_log, callback). The callback returns canned ratings and
    records each call so tests can assert the worker-side payload shape."""
    calls: list[list[tuple[str, str, str]]] = []

    async def _llm_rate(
        payload: list[tuple[str, str, str]],
    ) -> dict[tuple[str, str], int]:
        calls.append(payload)
        return {
            (query_id, doc_id): canned.get((query_id, doc_id), 0) for query_id, doc_id, _ in payload
        }

    return calls, _llm_rate


class TestHybridUbiLlmConverter:
    @pytest.mark.asyncio
    async def test_partitions_at_default_threshold_twenty(self) -> None:
        # 3 pairs: one above threshold (UBI), one below (LLM-fill), one
        # exactly at threshold (UBI — '>= 20' inclusive).
        features = {
            ("q1", "d_head"): _fv(impression_count=100, corrected_ctr=0.20),  # 100 >= 20 → head
            ("q1", "d_boundary"): _fv(impression_count=20, corrected_ctr=0.40),  # == 20 → head
            ("q1", "d_tail"): _fv(impression_count=5, corrected_ctr=0.0),  # 5 < 20 → tail
        }
        calls, llm_rate = _make_recording_llm_rate({("q1", "d_tail"): 1})
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({"q1": "query one"}),
        )
        out = await converter.convert(features, ConverterConfig())
        # Head ratings from CTR converter (default thresholds: 0.20 = rating 2; 0.40 = rating 3).
        assert out[("q1", "d_head")] == 2
        assert out[("q1", "d_boundary")] == 3
        # Tail rating from llm_rate canned response.
        assert out[("q1", "d_tail")] == 1
        # llm_rate was called exactly once with exactly the one tail pair, with
        # the resolved query_text.
        assert len(calls) == 1
        assert calls[0] == [("q1", "d_tail", "query one")]

    @pytest.mark.asyncio
    async def test_all_pairs_below_threshold_routes_to_llm(self) -> None:
        features = {
            ("q1", "d1"): _fv(impression_count=5, corrected_ctr=0.0),
            ("q1", "d2"): _fv(impression_count=10, corrected_ctr=0.0),
            ("q1", "d3"): _fv(impression_count=0, corrected_ctr=0.0),
        }
        calls, llm_rate = _make_recording_llm_rate(
            {("q1", "d1"): 1, ("q1", "d2"): 2, ("q1", "d3"): 0}
        )
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({"q1": "q1 text"}),
        )
        out = await converter.convert(features, ConverterConfig())
        assert out == {("q1", "d1"): 1, ("q1", "d2"): 2, ("q1", "d3"): 0}
        assert len(calls) == 1
        assert set(calls[0]) == {
            ("q1", "d1", "q1 text"),
            ("q1", "d2", "q1 text"),
            ("q1", "d3", "q1 text"),
        }

    @pytest.mark.asyncio
    async def test_head_only_skips_llm_callback(self) -> None:
        features = {
            ("q1", "d_head1"): _fv(impression_count=100, corrected_ctr=0.20),
            ("q1", "d_head2"): _fv(impression_count=50, corrected_ctr=0.10),
        }
        calls, llm_rate = _make_recording_llm_rate({})
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({"q1": "q1 text"}),
        )
        out = await converter.convert(features, ConverterConfig())
        assert out == {("q1", "d_head1"): 2, ("q1", "d_head2"): 1}
        assert calls == []  # llm_rate never awaited

    @pytest.mark.asyncio
    async def test_custom_llm_fill_threshold(self) -> None:
        # Lower the threshold to 5 so a 10-impression pair becomes head.
        config = ConverterConfig(extra={"llm_fill_threshold": 5})
        features = {
            ("q1", "d_head"): _fv(impression_count=10, corrected_ctr=0.20),  # 10 >= 5 → head
            ("q1", "d_tail"): _fv(impression_count=2, corrected_ctr=0.0),  # 2 < 5 → tail
        }
        calls, llm_rate = _make_recording_llm_rate({("q1", "d_tail"): 2})
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({"q1": "q1 text"}),
        )
        out = await converter.convert(features, config)
        assert out[("q1", "d_head")] == 2
        assert out[("q1", "d_tail")] == 2
        assert calls == [[("q1", "d_tail", "q1 text")]]

    @pytest.mark.asyncio
    async def test_negative_threshold_rejected(self) -> None:
        config = ConverterConfig(extra={"llm_fill_threshold": -1})
        calls, llm_rate = _make_recording_llm_rate({})
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({}),
        )
        with pytest.raises(ValueError, match="must be >= 1"):
            await converter.convert({}, config)

    @pytest.mark.asyncio
    async def test_non_integer_threshold_rejected(self) -> None:
        config = ConverterConfig(extra={"llm_fill_threshold": "twenty"})
        _, llm_rate = _make_recording_llm_rate({})
        converter = HybridUbiLlmConverter(
            inner=CtrThresholdConverter(),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({}),
        )
        with pytest.raises(ValueError, match="must be an int"):
            await converter.convert({}, config)

    @pytest.mark.asyncio
    async def test_dwell_inner_via_factory(self) -> None:
        features = {("q1", "d1"): _fv(impression_count=100, dwell_mean_seconds=60.0)}
        _, llm_rate = _make_recording_llm_rate({})
        converter = HybridUbiLlmConverter(
            inner=HybridUbiLlmConverter.build_inner("dwell_time"),
            llm_rate=llm_rate,
            query_text_lookup=_make_query_text_lookup({"q1": "q1 text"}),
        )
        out = await converter.convert(features, ConverterConfig())
        # 60s dwell → rating 2 with default thresholds.
        assert out[("q1", "d1")] == 2

    def test_build_inner_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="unknown hybrid inner converter kind"):
            HybridUbiLlmConverter.build_inner("ccm")  # type: ignore[arg-type]
