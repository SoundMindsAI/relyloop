# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :func:`backend.app.eval.calibration.compute_calibration`.

Hand-computed kappa baselines verified against the standard formulas:

* ``kappa = (p_o - p_e) / (1 - p_e)`` for Cohen's.
* Weighted kappa uses linear weights ``w_ij = 1 - |i - j| / max_dist``
  (max_dist = 3 for the 0..3 scale).

Tolerances are ``1e-9`` for exact-arithmetic cases (perfect agree / disagree)
and ``1e-6`` for the mixed case.
"""

from __future__ import annotations

import pytest

from backend.app.eval.calibration import compute_calibration


def test_perfect_agreement_returns_kappa_one() -> None:
    """All 10 pairs agree: ``p_o = 1``, ``p_e < 1`` → kappa = 1.0 exactly."""
    pairs = [(r, r) for r in [0, 1, 2, 3, 0, 1, 2, 3, 0, 1]]
    result = compute_calibration(pairs)
    assert result["cohens_kappa"] == pytest.approx(1.0, abs=1e-9)
    assert result["weighted_kappa"] == pytest.approx(1.0, abs=1e-9)
    assert result["n_samples"] == 10
    assert result["warning"] is None
    # Every present rating shows 1.0 per-class agreement.
    for r in ("0", "1", "2", "3"):
        assert result["per_class"][r] == pytest.approx(1.0, abs=1e-9)


def test_no_variance_returns_none_with_warning() -> None:
    """All 10 pairs are (2, 2): marginals concentrated → kappa undefined."""
    pairs = [(2, 2)] * 10
    result = compute_calibration(pairs)
    assert result["cohens_kappa"] is None
    assert result["weighted_kappa"] is None
    assert result["warning"] == "no rating variance"
    assert result["per_class"]["2"] == pytest.approx(1.0, abs=1e-9)
    # Absent ratings report 0.0 per the stable-shape contract.
    assert result["per_class"]["0"] == 0.0
    assert result["per_class"]["1"] == 0.0
    assert result["per_class"]["3"] == 0.0


def test_mixed_case_hand_computed_kappa() -> None:
    """A canonical 2x2 mixed case with a known kappa for regression.

    Confusion matrix (human row, llm col):
        humans rate: 0 0 0 1 1 1 1 2 2 3  (10 samples)
        llm rates:   0 0 1 1 1 2 2 2 3 3

    matrix[h][l]: (0,0)=2, (0,1)=1, (1,1)=2, (1,2)=2, (2,2)=1, (2,3)=1, (3,3)=1

    p_o = (2 + 2 + 1 + 1) / 10 = 0.6
    human_marg = [3/10, 4/10, 2/10, 1/10]
    llm_marg   = [2/10, 3/10, 3/10, 2/10]
    p_e = 0.3*0.2 + 0.4*0.3 + 0.2*0.3 + 0.1*0.2 = 0.06+0.12+0.06+0.02 = 0.26
    cohens = (0.6 - 0.26) / (1 - 0.26) = 0.34 / 0.74 ≈ 0.45945945...
    """
    pairs = [
        (0, 0),
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 1),
        (1, 2),
        (1, 2),
        (2, 2),
        (2, 3),
        (3, 3),
    ]
    result = compute_calibration(pairs)
    assert result["cohens_kappa"] is not None
    assert result["cohens_kappa"] == pytest.approx(0.34 / 0.74, rel=1e-9)
    assert result["weighted_kappa"] is not None
    # Weighted kappa is strictly >= Cohen's kappa for this matrix because all
    # disagreements are adjacent (distance 1 of 3 = 2/3 weight). Sanity-check
    # the bound and a hand-computed value.
    assert result["weighted_kappa"] > result["cohens_kappa"]


def test_weighted_kappa_hand_computed() -> None:
    """Verify the weighted kappa formula against a fully hand-computed case.

    Confusion (h, l): (0,3), (3,0), (1,2), (2,1).  4 samples.

    human_marg = llm_marg = [1/4, 1/4, 1/4, 1/4].
    p_o = 0 (no diagonal). p_e = 4 * (1/16) = 1/4.
    cohens = (0 - 1/4) / (1 - 1/4) = -1/3.

    Weighted (linear weights, max_dist=3):
      w(0,3) = w(3,0) = 1 - 3/3 = 0
      w(1,2) = w(2,1) = 1 - 1/3 = 2/3
      p_o_w = (0 + 0 + 2/3 + 2/3) / 4 = (4/3) / 4 = 1/3.

      For p_e_w, sum_{i,j} (1 - |i-j|/3) * 1/4 * 1/4
        = (1/16) * sum_{i,j} (1 - |i-j|/3)
        sum over 16 cells of (1 - |i-j|/3) = 16 - (1/3) * sum_{i,j} |i-j|
        sum |i-j| for 4x4 with values 0..3 = 2*(1+2+3+1+2+1) = 20
        so sum cells = 16 - 20/3 = (48 - 20)/3 = 28/3
        p_e_w = (28/3) / 16 = 28/48 = 7/12.

      weighted = (1/3 - 7/12) / (1 - 7/12) = (-1/4) / (5/12) = -3/5 = -0.6
    """
    pairs = [(0, 3), (3, 0), (1, 2), (2, 1)]
    result = compute_calibration(pairs)
    assert result["cohens_kappa"] == pytest.approx(-1.0 / 3.0, rel=1e-9)
    assert result["weighted_kappa"] == pytest.approx(-0.6, rel=1e-9)


def test_per_class_shape_includes_all_four_ratings() -> None:
    """``per_class`` always has keys 0, 1, 2, 3 even when some are absent."""
    pairs = [(0, 0), (0, 1)]
    result = compute_calibration(pairs)
    assert set(result["per_class"].keys()) == {"0", "1", "2", "3"}
    assert result["per_class"]["0"] == pytest.approx(0.5, abs=1e-9)
    assert result["per_class"]["1"] == 0.0
    assert result["per_class"]["2"] == 0.0
    assert result["per_class"]["3"] == 0.0


def test_empty_input_returns_zero_samples_no_warning() -> None:
    result = compute_calibration([])
    assert result["cohens_kappa"] is None
    assert result["weighted_kappa"] is None
    assert result["n_samples"] == 0
    # Empty pairs is a degenerate input — caller (router) should reject before
    # reaching here, but the helper must not crash.
    assert result["warning"] is None
    assert result["per_class"] == {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0}


def test_out_of_range_pairs_are_dropped_silently() -> None:
    """Defensive: invalid ratings outside 0..3 are filtered from the matrix.

    The API schema rejects bad ratings upstream, but the helper must not
    crash on a malformed import.
    """
    pairs = [(0, 0), (5, 2), (1, -1), (2, 2)]
    result = compute_calibration(pairs)
    # n_samples still reflects what the caller submitted (audit trail).
    assert result["n_samples"] == 4
    # But only valid pairs (0,0) + (2,2) reach the matrix → perfect agreement
    # of those two → kappa = 1.0.
    assert result["cohens_kappa"] == pytest.approx(1.0, abs=1e-9)
