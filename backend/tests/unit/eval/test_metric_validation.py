# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for scoring helper enum/k-allowlist enforcement.

Exercises ``SUPPORTED_METRICS`` / ``SUPPORTED_K_VALUES`` frozensets and the
``objective_metric_key()`` three-branch contract from spec §FR-5.

API-payload validation against ``studies.config`` / ``studies.objective`` is
Phase 2's concern, not this feature's — these tests cover the helper-level
boundary, where worker code calls ``score()`` and ``objective_metric_key()``.
"""

from __future__ import annotations

import pytest

from backend.app.eval.scoring import (
    SUPPORTED_K_VALUES,
    SUPPORTED_METRICS,
    objective_metric_key,
)

# ---------------------------------------------------------------------------
# Frozenset allowlists — exact wire values per spec §8.4
# ---------------------------------------------------------------------------


def test_supported_metrics_exact_set():
    """The five MVP1 metrics — no ERR@k (deferred to MVP2)."""
    assert SUPPORTED_METRICS == frozenset({"ndcg", "map", "precision", "recall", "mrr"})


def test_supported_k_values_exact_set():
    """The seven canonical k values."""
    assert SUPPORTED_K_VALUES == frozenset({1, 3, 5, 10, 20, 50, 100})


def test_supported_metrics_is_immutable():
    """``frozenset`` rejects mutation attempts (defensive: no accidental drift)."""
    with pytest.raises(AttributeError):
        SUPPORTED_METRICS.add("err")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# objective_metric_key — three branches (cut-required / map-optional / mrr-ignored)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metric", "k", "expected"),
    [
        ("ndcg", 10, "ndcg@10"),
        ("ndcg", 1, "ndcg@1"),
        ("ndcg", 100, "ndcg@100"),
        ("precision", 5, "precision@5"),
        ("recall", 20, "recall@20"),
    ],
)
def test_objective_metric_key_cut_required_metrics(metric: str, k: int, expected: str):
    """ndcg/precision/recall: returns ``f"{metric}@{k}"``."""
    assert objective_metric_key({"metric": metric, "k": k}) == expected


def test_objective_metric_key_map_with_k_returns_cut_form():
    """map + k → ``"map@k"``."""
    assert objective_metric_key({"metric": "map", "k": 10}) == "map@10"


def test_objective_metric_key_map_without_k_returns_full_recall():
    """map without k → plain ``"map"`` (full-recall MAP)."""
    assert objective_metric_key({"metric": "map"}) == "map"


def test_objective_metric_key_map_with_k_none_returns_full_recall():
    """map with k=None (key present but null) → plain ``"map"``."""
    assert objective_metric_key({"metric": "map", "k": None}) == "map"


def test_objective_metric_key_mrr_ignores_k_when_absent():
    """mrr without k → ``"mrr"``."""
    assert objective_metric_key({"metric": "mrr"}) == "mrr"


def test_objective_metric_key_mrr_ignores_k_when_present():
    """mrr WITH k → still ``"mrr"`` (k silently ignored per spec §8.4)."""
    # The spec says k SHOULD be omitted for mrr but IS ignored if present.
    assert objective_metric_key({"metric": "mrr", "k": 10}) == "mrr"


# ---------------------------------------------------------------------------
# objective_metric_key — error paths
# ---------------------------------------------------------------------------


def test_objective_metric_key_rejects_unknown_metric():
    """Any name outside SUPPORTED_METRICS → ValueError. (`err` is no longer in
    the wire enum — Pydantic rejects it before this function sees it — so we
    use a clearly synthetic sentinel here to exercise the unknown-metric
    branch directly.)"""
    with pytest.raises(ValueError, match=r"unknown objective.metric"):
        objective_metric_key({"metric": "made_up_metric", "k": 10})


def test_objective_metric_key_requires_k_for_ndcg():
    """ndcg without k → ValueError (k REQUIRED)."""
    with pytest.raises(ValueError, match=r"required for metric 'ndcg'"):
        objective_metric_key({"metric": "ndcg"})


def test_objective_metric_key_requires_k_for_precision():
    """precision without k → ValueError."""
    with pytest.raises(ValueError, match=r"required for metric 'precision'"):
        objective_metric_key({"metric": "precision"})


def test_objective_metric_key_requires_k_for_recall():
    """recall without k → ValueError."""
    with pytest.raises(ValueError, match=r"required for metric 'recall'"):
        objective_metric_key({"metric": "recall"})


def test_objective_metric_key_rejects_out_of_allowlist_k():
    """k=15 (not in SUPPORTED_K_VALUES) → ValueError."""
    with pytest.raises(ValueError, match=r"k=15 not in allowlist"):
        objective_metric_key({"metric": "ndcg", "k": 15})


def test_objective_metric_key_rejects_out_of_allowlist_k_for_map():
    """map with k=7 (not allowed) → ValueError."""
    with pytest.raises(ValueError, match=r"map.* must be in"):
        objective_metric_key({"metric": "map", "k": 7})


def test_objective_metric_key_rejects_non_string_metric():
    """objective.metric must be a string."""
    with pytest.raises(ValueError, match=r"must be a string"):
        objective_metric_key({"metric": 42})


def test_objective_metric_key_rejects_non_int_k_for_required():
    """For ndcg/precision/recall, k must be an int."""
    with pytest.raises(ValueError, match=r"required for metric 'ndcg'"):
        objective_metric_key({"metric": "ndcg", "k": "10"})
