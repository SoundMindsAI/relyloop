# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.domain.ubi.features`` (feat_ubi_judgments
Story 1.2 / FR-1 + FR-2 backing).

Pure-domain — no DB, no HTTP. Asserts:

* aggregate_features groups events by ``(query_id, doc_id)`` correctly
* click_count + impression_count match raw event sums
* Wang-Bendersky correction respects the position-bias prior
* Uninformed prior == raw CTR
* Sparse-prior ranks fall back to weight 1.0 (no silent zero-out)
* Edge cases: zero impressions, single-impression, no dwell events,
  no click events (conversion_rate None), no impressions
  (refinement_rate None), unknown event_types ignored
* corrected_ctr clipped at 1.0 when prior under-weights high-traffic
  positions

Locks the edge-case behaviors documented in
:func:`backend.app.domain.ubi.features.aggregate_features` so a future
refactor that "fixes" one of them (e.g., raising on zero impressions)
breaks the suite loudly.
"""

from __future__ import annotations

import pytest

from backend.app.domain.ubi.features import FeatureVec, UbiEvent, aggregate_features


def _click(query_id: str, doc_id: str) -> UbiEvent:
    return UbiEvent(
        query_id=query_id, doc_id=doc_id, event_type="click", position=None, dwell_seconds=None
    )


def _impression(query_id: str, doc_id: str, position: int) -> UbiEvent:
    return UbiEvent(
        query_id=query_id,
        doc_id=doc_id,
        event_type="impression",
        position=position,
        dwell_seconds=None,
    )


def _dwell(query_id: str, doc_id: str, seconds: float) -> UbiEvent:
    return UbiEvent(
        query_id=query_id, doc_id=doc_id, event_type="dwell", position=None, dwell_seconds=seconds
    )


def _conversion(query_id: str, doc_id: str) -> UbiEvent:
    return UbiEvent(
        query_id=query_id, doc_id=doc_id, event_type="conversion", position=None, dwell_seconds=None
    )


def _refinement(query_id: str, doc_id: str) -> UbiEvent:
    return UbiEvent(
        query_id=query_id, doc_id=doc_id, event_type="refinement", position=None, dwell_seconds=None
    )


class TestAggregateFeaturesBasicCounts:
    def test_empty_input_returns_empty_dict(self) -> None:
        assert aggregate_features({}, None) == {}

    def test_groups_events_by_query_doc(self) -> None:
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 1), _click("q1", "d1")],
            ("q1", "d2"): [_impression("q1", "d2", 2)],
            ("q2", "d1"): [_impression("q2", "d1", 1), _click("q2", "d1"), _click("q2", "d1")],
        }
        out = aggregate_features(events, None)
        assert set(out.keys()) == {("q1", "d1"), ("q1", "d2"), ("q2", "d1")}
        assert out[("q1", "d1")].click_count == 1
        assert out[("q1", "d1")].impression_count == 1
        assert out[("q1", "d2")].click_count == 0
        assert out[("q1", "d2")].impression_count == 1
        assert out[("q2", "d1")].click_count == 2
        assert out[("q2", "d1")].impression_count == 1

    def test_raw_ctr_when_prior_is_none(self) -> None:
        # 10 impressions at position 1, 3 clicks → raw CTR = 0.30 (uninformed).
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 1)] * 10 + [_click("q1", "d1")] * 3,
        }
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].corrected_ctr == pytest.approx(0.30, abs=1e-6)

    def test_raw_ctr_when_prior_is_empty_dict(self) -> None:
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 1)] * 10 + [_click("q1", "d1")] * 3,
        }
        out = aggregate_features(events, {})
        assert out[("q1", "d1")].corrected_ctr == pytest.approx(0.30, abs=1e-6)


class TestPositionBiasCorrection:
    def test_informed_prior_lowers_effective_denominator(self) -> None:
        # 10 impressions at position 2 (prior weight 0.5), 3 clicks.
        # Effective denominator: 10 * 0.5 = 5. corrected CTR: 3 / 5 = 0.60.
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 2)] * 10 + [_click("q1", "d1")] * 3,
        }
        prior = {1: 1.0, 2: 0.5, 3: 0.25}
        out = aggregate_features(events, prior)
        assert out[("q1", "d1")].corrected_ctr == pytest.approx(0.60, abs=1e-6)

    def test_sparse_prior_falls_back_to_weight_one_for_missing_ranks(self) -> None:
        # Prior only covers position 1; positions 2+ get weight 1.0 (raw CTR).
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 5)] * 10 + [_click("q1", "d1")] * 2,
        }
        prior = {1: 1.0}  # rank 5 not present
        out = aggregate_features(events, prior)
        # Effective denominator: 10 * 1.0 (fallback) = 10. CTR: 2/10 = 0.20.
        assert out[("q1", "d1")].corrected_ctr == pytest.approx(0.20, abs=1e-6)

    def test_mixed_positions_weighted_independently(self) -> None:
        # 5 impressions at position 1 (weight 1.0) + 5 at position 3 (weight 0.25)
        # → effective denominator = 5 + 1.25 = 6.25.
        # 4 clicks → corrected CTR = 4 / 6.25 = 0.64.
        events = {
            ("q1", "d1"): (
                [_impression("q1", "d1", 1)] * 5
                + [_impression("q1", "d1", 3)] * 5
                + [_click("q1", "d1")] * 4
            ),
        }
        prior = {1: 1.0, 2: 0.5, 3: 0.25}
        out = aggregate_features(events, prior)
        assert out[("q1", "d1")].corrected_ctr == pytest.approx(0.64, abs=1e-6)

    def test_corrected_ctr_clipped_at_one(self) -> None:
        # Under-weighted high-traffic position can make denominator < clicks.
        # 2 impressions at position 1 (weight 0.1) + 5 clicks
        # → effective denominator = 0.2, raw ratio = 25.0 → clipped to 1.0.
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 1)] * 2 + [_click("q1", "d1")] * 5,
        }
        prior = {1: 0.1}
        out = aggregate_features(events, prior)
        assert out[("q1", "d1")].corrected_ctr == 1.0


class TestEdgeCases:
    def test_zero_impressions_yields_zero_ctr_not_raise(self) -> None:
        # Pair with clicks but no impressions (operator bug, but the aggregator
        # must not raise). corrected_ctr = 0.0 (no impression-side signal).
        events = {("q1", "d1"): [_click("q1", "d1")] * 3}
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].impression_count == 0
        assert out[("q1", "d1")].corrected_ctr == 0.0
        assert out[("q1", "d1")].click_count == 3

    def test_single_impression_pair_normalizes_correctly(self) -> None:
        events = {("q1", "d1"): [_impression("q1", "d1", 1)]}
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].impression_count == 1
        assert out[("q1", "d1")].click_count == 0
        assert out[("q1", "d1")].corrected_ctr == 0.0

    def test_no_dwell_events_yields_none_not_zero(self) -> None:
        # Distinction matters: the dwell-time converter treats None as "no
        # signal" (skip the pair) whereas 0.0 means "user dwelled zero
        # seconds" (rate 0).
        events = {("q1", "d1"): [_impression("q1", "d1", 1), _click("q1", "d1")]}
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].dwell_mean_seconds is None

    def test_dwell_mean_of_multiple_values(self) -> None:
        events = {
            ("q1", "d1"): [
                _impression("q1", "d1", 1),
                _click("q1", "d1"),
                _dwell("q1", "d1", 10.0),
                _dwell("q1", "d1", 30.0),
                _dwell("q1", "d1", 50.0),
            ],
        }
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].dwell_mean_seconds == pytest.approx(30.0, abs=1e-6)

    def test_no_clicks_yields_none_conversion_rate(self) -> None:
        events = {("q1", "d1"): [_impression("q1", "d1", 1)] * 5}
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].conversion_rate is None

    def test_conversion_rate_with_clicks(self) -> None:
        events = {
            ("q1", "d1"): (
                [_impression("q1", "d1", 1)] * 10
                + [_click("q1", "d1")] * 4
                + [_conversion("q1", "d1")] * 1
            ),
        }
        out = aggregate_features(events, None)
        # 1 conversion / 4 clicks = 0.25
        assert out[("q1", "d1")].conversion_rate == pytest.approx(0.25, abs=1e-6)

    def test_no_impressions_yields_none_refinement_rate(self) -> None:
        # Refinement without impressions is weird but the aggregator handles it.
        events = {("q1", "d1"): [_refinement("q1", "d1")] * 2}
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].refinement_rate is None

    def test_refinement_rate_with_impressions(self) -> None:
        events = {
            ("q1", "d1"): ([_impression("q1", "d1", 1)] * 10 + [_refinement("q1", "d1")] * 3),
        }
        out = aggregate_features(events, None)
        # 3 refinements / 10 impressions = 0.30
        assert out[("q1", "d1")].refinement_rate == pytest.approx(0.30, abs=1e-6)

    def test_unknown_event_types_silently_ignored(self) -> None:
        # Operator emits a custom 'view' event the schema doesn't standardize.
        # The aggregator must not crash and must not double-count it as
        # an impression.
        custom_view = UbiEvent(
            query_id="q1", doc_id="d1", event_type="view", position=1, dwell_seconds=None
        )
        events = {
            ("q1", "d1"): [
                _impression("q1", "d1", 1),
                custom_view,
                custom_view,
                _click("q1", "d1"),
            ],
        }
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].impression_count == 1  # not 3
        assert out[("q1", "d1")].click_count == 1

    def test_dwell_event_with_none_seconds_skipped(self) -> None:
        # The dwell event arrived with dwell_seconds=None (operator emitted it
        # but didn't measure the value). Should be skipped, not crash.
        broken = UbiEvent(
            query_id="q1", doc_id="d1", event_type="dwell", position=None, dwell_seconds=None
        )
        events = {
            ("q1", "d1"): [_impression("q1", "d1", 1), _click("q1", "d1"), broken],
        }
        out = aggregate_features(events, None)
        assert out[("q1", "d1")].dwell_mean_seconds is None  # no valid dwell values


class TestFeatureVecModel:
    def test_rejects_negative_counts(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — Pydantic ValidationError
            FeatureVec(click_count=-1, impression_count=0, corrected_ctr=0.0)

    def test_rejects_ctr_above_one(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            FeatureVec(click_count=0, impression_count=0, corrected_ctr=1.5)

    def test_rejects_negative_ctr(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            FeatureVec(click_count=0, impression_count=0, corrected_ctr=-0.1)
