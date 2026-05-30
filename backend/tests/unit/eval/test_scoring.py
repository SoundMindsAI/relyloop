# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for backend.app.eval.scoring (infra_optuna_eval Story 1.2 / AC-3).

The nDCG@10 and MAP@10 expected values in this module are independently
hand-computed from the standard IR-evaluation formulas (NOT pinned from
implementation output), per the spec AC-3 contract and the plan's Story 1.2
task 5 hand-computation requirement. infra_ir_measures_migration verified
these hand-computed values match ir_measures' output via the parity test
at backend/tests/unit/eval/test_scoring_parity.py.

Hand-computation reference (see ``HANDBUILT_FIXTURE`` docstring below).
"""

from __future__ import annotations

import math

import pytest

from backend.app.eval.scoring import score

# ---------------------------------------------------------------------------
# Hand-curated fixture with independently hand-derived nDCG@10 and MAP@10.
# ---------------------------------------------------------------------------
#
# Three queries; the AC-3 expected values use the TREC nDCG formula
#
#     DCG = Σ (2^rel_i - 1) / log2(i + 1)        (i = 1..k)
#
# and the standard MAP formula
#
#     AP = (Σ precision_at_rank_i × is_rel_i) / num_relevant
#     MAP = mean(AP) over queries
#
# Aggregate metrics in score() are the arithmetic mean over queries.
#
# Query q1 — perfect ranking, 3 graded-relevance docs:
#   qrels  = {d1: 3, d2: 2, d3: 1}
#   run    = {d1: 0.9, d2: 0.8, d3: 0.7}          (returned ranking d1>d2>d3)
#   DCG_at_10  = (2^3-1)/log2(2) + (2^2-1)/log2(3) + (2^1-1)/log2(4)
#              = 7/1 + 3/1.5849625 + 1/2
#              = 7 + 1.8927893 + 0.5 = 9.3927893
#   IDCG_at_10 = same (perfect ranking) = 9.3927893
#   nDCG@10_q1 = 1.0
#   AP_q1     = (1/1 + 2/2 + 3/3) / 3 = 1.0
#
# Query q2 — inverted ranking, 1 relevant doc out of 2:
#   qrels  = {d1: 2, d2: 0}    (only d1 is relevant)
#   run    = {d1: 0.6, d2: 0.9}                    (returned ranking d2>d1)
#   DCG_at_10  = (2^0-1)/log2(2) + (2^2-1)/log2(3)
#              = 0 + 3/1.5849625 = 1.8927893
#   IDCG_at_10 = (2^2-1)/log2(2) = 3.0
#   nDCG@10_q2 = 1.8927893 / 3.0 = 0.6309298
#   AP_q2     = (1/2) / 1 = 0.5      (one relevant doc, found at rank 2)
#
# Query q3 — single relevant doc found at rank 1:
#   qrels  = {d1: 1}
#   run    = {d1: 0.5}
#   DCG_at_10  = (2^1-1)/log2(2) = 1.0
#   IDCG_at_10 = 1.0
#   nDCG@10_q3 = 1.0
#   AP_q3     = (1/1) / 1 = 1.0
#
# Aggregates:
#   nDCG@10 = (1.0 + 0.6309298 + 1.0) / 3 = 0.8769766
#   MAP@10  = (1.0 + 0.5      + 1.0) / 3 = 0.8333333
#   MAP     = same as MAP@10 here (every query's full ranking fits within top-10)


HANDBUILT_QRELS = {
    "q1": {"d1": 3, "d2": 2, "d3": 1},
    "q2": {"d1": 2, "d2": 0},
    "q3": {"d1": 1},
}

HANDBUILT_RUN = {
    "q1": {"d1": 0.9, "d2": 0.8, "d3": 0.7},
    "q2": {"d1": 0.6, "d2": 0.9},
    "q3": {"d1": 0.5},
}

# Hand-derived values (see fixture docstring).
EXPECTED_NDCG_AT_10 = (1.0 + (3.0 / math.log2(3)) / 3.0 + 1.0) / 3.0
EXPECTED_MAP_AT_10 = (1.0 + 0.5 + 1.0) / 3.0


def test_score_ndcg_at_10_matches_hand_computed_baseline():
    """AC-3 — nDCG@10 aggregate within 1e-6 of the independently hand-computed value."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg@10"})
    assert "ndcg@10" in result["aggregate"]
    assert abs(result["aggregate"]["ndcg@10"] - EXPECTED_NDCG_AT_10) < 1e-6


def test_score_map_at_10_matches_hand_computed_baseline():
    """AC-3 — MAP@10 aggregate within 1e-6 of the independently hand-computed value."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"map@10"})
    assert "map@10" in result["aggregate"]
    assert abs(result["aggregate"]["map@10"] - EXPECTED_MAP_AT_10) < 1e-6


def test_score_returns_per_query_keyed_by_user_facing_names():
    """per_query results re-keyed to user-facing names; wire names never leak."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg@10", "map@10"})
    for qid in ("q1", "q2", "q3"):
        assert qid in result["per_query"]
        assert "ndcg@10" in result["per_query"][qid]
        assert "map@10" in result["per_query"][qid]
        # Wire names MUST NOT appear in returned keys.
        assert "ndcg_cut_10" not in result["per_query"][qid]
        assert "map_cut_10" not in result["per_query"][qid]


def test_score_q1_ndcg_at_10_is_one():
    """q1 has perfect ranking — per-query nDCG@10 should be 1.0."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg@10"})
    assert abs(result["per_query"]["q1"]["ndcg@10"] - 1.0) < 1e-6


def test_score_q2_ndcg_at_10_matches_hand_computed():
    """q2 inverted-ranking nDCG@10 == 0.6309298... (hand-derived)."""
    expected_q2 = (3.0 / math.log2(3)) / 3.0  # 1.8927893 / 3 = 0.6309298
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg@10"})
    assert abs(result["per_query"]["q2"]["ndcg@10"] - expected_q2) < 1e-6


def test_score_q2_map_at_10_is_half():
    """q2 — one relevant doc found at rank 2 → AP = 0.5."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"map@10"})
    assert abs(result["per_query"]["q2"]["map@10"] - 0.5) < 1e-6


def test_score_supports_full_recall_map_distinct_from_map_at_k():
    """`map` (full recall) and `map@10` produce the same value when the run
    fits inside the top-k, but they translate to different wire names."""
    result_full = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"map"})
    result_cut = score(HANDBUILT_QRELS, HANDBUILT_RUN, {"map@10"})
    # Both metric keys present in their respective results.
    assert "map" in result_full["aggregate"]
    assert "map@10" in result_cut["aggregate"]
    # And neither has the OTHER key (showing the user-facing distinction is preserved).
    assert "map@10" not in result_full["aggregate"]
    assert "map" not in result_cut["aggregate"]


def test_score_handles_binary_relevance():
    """Binary 0/1 qrels work the same as graded — ir_measures auto-handles."""
    binary_qrels = {"q1": {"d1": 1, "d2": 0, "d3": 1}}
    binary_run = {"q1": {"d1": 0.9, "d2": 0.5, "d3": 0.1}}
    result = score(binary_qrels, binary_run, {"ndcg@10"})
    # d1 (rel) at rank 1, d3 (rel) at rank 3:
    #   DCG  = 1/log2(2) + 0 + 1/log2(4) = 1 + 0.5 = 1.5
    #   IDCG = 1/log2(2) + 1/log2(3)     = 1 + 0.6309 = 1.6309
    #   nDCG = 1.5 / 1.6309 = 0.9197
    expected = (1.0 + 1.0 / 2.0) / (1.0 + 1.0 / math.log2(3))
    assert abs(result["per_query"]["q1"]["ndcg@10"] - expected) < 1e-6


def test_score_mrr_translates_to_recip_rank():
    """`mrr` (user-facing) → ir_measures `RR` metric object; result re-keyed."""
    qrels = {"q1": {"d1": 0, "d2": 1}}
    run = {"q1": {"d1": 0.9, "d2": 0.5}}  # d2 (relevant) at rank 2 → RR = 1/2
    result = score(qrels, run, {"mrr"})
    assert "mrr" in result["aggregate"]
    assert "recip_rank" not in result["aggregate"]
    assert abs(result["aggregate"]["mrr"] - 0.5) < 1e-6


def test_score_empty_metrics_set_returns_empty_results():
    """Empty metric set returns empty aggregate."""
    result = score(HANDBUILT_QRELS, HANDBUILT_RUN, set())
    assert result["aggregate"] == {}


def test_score_rejects_unknown_metric_token():
    """Unknown metric base → ValueError."""
    with pytest.raises(ValueError, match=r"unknown metric base"):
        score(HANDBUILT_QRELS, HANDBUILT_RUN, {"err@10"})


def test_score_rejects_out_of_allowlist_k():
    """k not in SUPPORTED_K_VALUES → ValueError."""
    with pytest.raises(ValueError, match=r"k=15"):
        score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg@15"})


def test_score_rejects_mrr_with_cut_suffix():
    """`mrr@k` is invalid (mrr is always full-recall)."""
    with pytest.raises(ValueError, match=r"does not accept an @<k> cut"):
        score(HANDBUILT_QRELS, HANDBUILT_RUN, {"mrr@10"})


def test_score_rejects_ndcg_without_cut():
    """`ndcg` (no cut) is invalid — must be `ndcg@k`."""
    with pytest.raises(ValueError, match=r"requires an @<k> cut"):
        score(HANDBUILT_QRELS, HANDBUILT_RUN, {"ndcg"})
