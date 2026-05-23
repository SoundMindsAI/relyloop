"""Unit tests for the metric → ir_measures metric-object mapper.

chore_create_study_wizard_polish Story 1.2 / AC-14 backend half.

Locks the metric+k tier semantics asserted by the frontend's
`K_REQUIRED` and `K_IGNORED` constants. The user-facing tokens scoring.py
returns are unchanged by infra_ir_measures_migration; only the internal
mapping behind score() switched from pytrec_eval wire strings to
ir_measures metric objects.

  * Required-k (ndcg / precision / recall): user-facing key is ``<metric>@<k>``.
  * Optional-k (map): with k → ``map@<k>``; without k → ``map`` (full-recall MAP).
  * Ignored-k (mrr): produces ``recip_rank`` regardless of k presence.

Source-of-truth comment block: ``backend/app/eval/scoring.py:30-34``.

Note: ``err`` is in ``ObjectiveMetric`` (the frontend allows users to pick
it), but it is NOT in ``SUPPORTED_METRICS`` — ERR@k is deferred to MVP2 per
infra_optuna_eval spec §3. So this test does NOT exercise the err case at
the scoring layer; the frontend's K_IGNORED predicate covers it anyway
because backend behavior for err on the create path is permissive (k is
silently accepted; the failure surfaces later at scoring time).
"""

from __future__ import annotations

import pytest

from backend.app.eval.scoring import (
    SUPPORTED_K_VALUES,
    SUPPORTED_METRICS,
    objective_metric_key,
)


@pytest.mark.parametrize("metric", ["ndcg", "precision", "recall"])
def test_required_k_metrics_with_k_produce_cut_token(metric: str) -> None:
    """Required-k tier: each metric returns f'{metric}@{k}' for the indexed key."""
    key = objective_metric_key({"metric": metric, "k": 10})
    assert key == f"{metric}@10"


@pytest.mark.parametrize("metric", ["ndcg", "precision", "recall"])
def test_required_k_metrics_without_k_raise(metric: str) -> None:
    """Required-k tier: missing k raises ValueError from objective_metric_key.

    This matches the backend ObjectiveSpec model_validator's behavior — the
    same set of metrics rejects None k.
    """
    with pytest.raises(ValueError, match="objective.k is required"):
        objective_metric_key({"metric": metric, "k": None})


def test_map_with_k_returns_map_cut_token() -> None:
    """Optional-k tier: map with k=10 produces map@10."""
    key = objective_metric_key({"metric": "map", "k": 10})
    assert key == "map@10"


def test_map_without_k_returns_full_recall_token() -> None:
    """Optional-k tier: map without k produces plain 'map' (full-recall MAP)."""
    key = objective_metric_key({"metric": "map", "k": None})
    assert key == "map"


def test_map_without_any_k_field_returns_full_recall_token() -> None:
    """Optional-k tier: omitting k entirely is equivalent to k=None."""
    key = objective_metric_key({"metric": "map"})
    assert key == "map"


@pytest.mark.parametrize("k", [None, 10])
def test_mrr_ignores_k_value(k: int | None) -> None:
    """Ignored-k tier: mrr returns 'mrr' regardless of k presence."""
    key = objective_metric_key({"metric": "mrr", "k": k})
    assert key == "mrr"


def test_supported_metrics_excludes_err() -> None:
    """Scoring layer does not support err (MVP2 deferral per infra_optuna_eval §3).

    The frontend K_IGNORED includes err so the wizard hides the k field for it,
    but err cannot reach scoring at runtime — if a study is created with
    metric=err, scoring fails before ir_measures is invoked. This assertion
    locks the deferral.
    """
    assert "err" not in SUPPORTED_METRICS


def test_supported_metrics_set() -> None:
    """Source-of-truth check: SUPPORTED_METRICS lists the 5 metrics we test above."""
    assert SUPPORTED_METRICS == frozenset({"ndcg", "map", "precision", "recall", "mrr"})


def test_supported_k_values_set() -> None:
    """Source-of-truth check: SUPPORTED_K_VALUES matches ObjectiveK Literal."""
    assert SUPPORTED_K_VALUES == frozenset({1, 3, 5, 10, 20, 50, 100})
