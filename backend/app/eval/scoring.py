"""pytrec_eval scoring helper (infra_optuna_eval Story 1.2 / FR-3 + FR-5).

Pure-functional layer. ``score(qrels, run, metrics)`` is the only function the
``run_trial`` worker calls; it owns the user-facing → pytrec_eval wire-name
translation so wire names never leak past this module (per spec §FR-3 last
paragraph).

The frozensets ``SUPPORTED_METRICS`` and ``SUPPORTED_K_VALUES`` are the
allowlist for ``studies.objective.metric`` / ``studies.objective.k`` (per
spec §8.4 source-of-truth row); ``feat_study_lifecycle`` Phase 2's API layer
imports them for request-time validation.

The ``objective_metric_key(objective)`` helper returns the user-facing key
used to index ``trials.metrics`` for denormalization into
``trials.primary_metric`` (per spec §FR-5).
"""

from __future__ import annotations

from typing import TypedDict

import pytrec_eval

SUPPORTED_METRICS: frozenset[str] = frozenset({"ndcg", "map", "precision", "recall", "mrr"})
"""Allowed values for ``studies.objective.metric``. ERR@k deferred to MVP2 (per spec §3)."""

SUPPORTED_K_VALUES: frozenset[int] = frozenset({1, 3, 5, 10, 20, 50, 100})
"""Allowed values for ``studies.objective.k`` when k is required or set."""

# Per-metric k requirement:
#   ndcg/precision/recall → k REQUIRED
#   map                    → k OPTIONAL (presence = map@k cut; absence = full-recall MAP)
#   mrr                    → k IGNORED  (always full-recall MRR)
_K_REQUIRED: frozenset[str] = frozenset({"ndcg", "precision", "recall"})
_K_NEVER: frozenset[str] = frozenset({"mrr"})

Qrels = dict[str, dict[str, int]]
"""``{query_id: {doc_id: rating}}`` — graded (0..3) or binary (0..1) ratings."""

Run = dict[str, dict[str, float]]
"""``{query_id: {doc_id: score}}`` — engine-returned similarity scores."""


class ScoreResult(TypedDict):
    """Return shape of ``score()``: aggregate (mean across queries) and per-query metrics."""

    aggregate: dict[str, float]
    per_query: dict[str, dict[str, float]]


def _translate_metric_name(user_facing: str) -> str:
    """Translate a user-facing metric name to pytrec_eval's wire name.

    Source of truth for the §FR-3 translation table. Wire names never leak
    past ``score()`` — this helper is module-private.

    Translation table::

        ndcg@<k>      → ndcg_cut_<k>
        map@<k>       → map_cut_<k>
        map           → map        (full-recall MAP)
        precision@<k> → P_<k>
        recall@<k>    → recall_<k>
        mrr           → recip_rank

    Raises:
        ValueError: on unparseable tokens or out-of-allowlist metrics/k values.
    """
    if user_facing == "mrr":
        return "recip_rank"
    if user_facing == "map":
        return "map"

    if "@" not in user_facing:
        raise ValueError(
            f"metric {user_facing!r} requires an @<k> cut (allowed bases: "
            f"{sorted(SUPPORTED_METRICS - _K_NEVER)})"
        )

    base, _, k_str = user_facing.partition("@")
    if base not in SUPPORTED_METRICS:
        raise ValueError(f"unknown metric base {base!r}; allowed: {sorted(SUPPORTED_METRICS)}")
    if base in _K_NEVER:
        raise ValueError(f"metric {base!r} does not accept an @<k> cut; use plain {base!r}")
    try:
        k = int(k_str)
    except ValueError as exc:
        raise ValueError(f"k value {k_str!r} in {user_facing!r} is not an integer") from exc
    if k not in SUPPORTED_K_VALUES:
        raise ValueError(
            f"k={k} in {user_facing!r} is not in the allowlist {sorted(SUPPORTED_K_VALUES)}"
        )

    if base == "ndcg":
        return f"ndcg_cut_{k}"
    if base == "map":
        return f"map_cut_{k}"
    if base == "precision":
        return f"P_{k}"
    if base == "recall":
        return f"recall_{k}"
    # _K_REQUIRED + map + mrr is exhaustive over SUPPORTED_METRICS; this is unreachable.
    raise ValueError(f"unexpected metric base {base!r}")  # pragma: no cover


def objective_metric_key(objective: dict[str, object]) -> str:
    """Return the user-facing metric key used to index ``trials.metrics``.

    Per spec §FR-5: ``trials.primary_metric`` is denormalized from
    ``metrics[objective_metric_key(study.objective)]``. The contract:

    * cut-aware metrics (``ndcg``, ``precision``, ``recall``):
      returns ``f"{metric}@{k}"``; ``k`` is REQUIRED.
    * ``map``: returns ``f"map@{k}"`` if ``k`` is set in objective,
      else plain ``"map"`` (full-recall MAP).
    * ``mrr``: returns ``"mrr"``; any ``k`` in objective is ignored.

    Raises:
        ValueError: on unknown metric or missing-required-k.
    """
    metric = objective.get("metric")
    if not isinstance(metric, str):
        raise ValueError(f"objective.metric must be a string, got {type(metric).__name__}")
    if metric not in SUPPORTED_METRICS:
        raise ValueError(
            f"unknown objective.metric {metric!r}; allowed: {sorted(SUPPORTED_METRICS)}"
        )

    k = objective.get("k")

    if metric in _K_NEVER:
        # mrr — k ignored regardless of presence.
        return metric

    if metric == "map":
        if k is None:
            return "map"
        if not isinstance(k, int) or k not in SUPPORTED_K_VALUES:
            raise ValueError(
                f"objective.k={k!r} for metric 'map' must be in "
                f"{sorted(SUPPORTED_K_VALUES)} or omitted"
            )
        return f"map@{k}"

    # ndcg / precision / recall: k REQUIRED.
    if not isinstance(k, int):
        raise ValueError(f"objective.k is required for metric {metric!r} (got {type(k).__name__})")
    if k not in SUPPORTED_K_VALUES:
        raise ValueError(f"objective.k={k} not in allowlist {sorted(SUPPORTED_K_VALUES)}")
    return f"{metric}@{k}"


def score(qrels: Qrels, run: Run, metrics: set[str]) -> ScoreResult:
    """Score a run against qrels for the requested metric set.

    User-facing metric tokens are translated to pytrec_eval's wire names
    via ``_translate_metric_name``; the result is re-keyed back to the
    user-facing names so wire names never leak past this function.

    Args:
        qrels: ``{query_id: {doc_id: rating}}`` (graded 0..3 or binary 0..1).
        run: ``{query_id: {doc_id: score}}`` from the engine.
        metrics: user-facing metric tokens (e.g. ``{"ndcg@10", "map", "mrr"}``).

    Returns:
        ``{"aggregate": {metric: mean_value}, "per_query": {qid: {metric: value}}}``.
        Aggregate is the arithmetic mean across queries.

    Raises:
        ValueError: if any metric token is not in the allowlist.
    """
    # Map user-facing → wire; remember the reverse for re-keying.
    user_to_wire: dict[str, str] = {m: _translate_metric_name(m) for m in metrics}
    wire_set: set[str] = set(user_to_wire.values())

    evaluator = pytrec_eval.RelevanceEvaluator(qrels, wire_set)
    raw_per_query: dict[str, dict[str, float]] = evaluator.evaluate(run)

    # Re-key per_query from wire to user-facing names.
    per_query: dict[str, dict[str, float]] = {}
    for qid, wire_dict in raw_per_query.items():
        per_query[qid] = {
            user: float(wire_dict[wire]) for user, wire in user_to_wire.items() if wire in wire_dict
        }

    # Aggregate: arithmetic mean across queries, per user-facing metric.
    aggregate: dict[str, float] = {}
    if per_query:
        for user in user_to_wire:
            values = [q[user] for q in per_query.values() if user in q]
            if values:
                aggregate[user] = sum(values) / len(values)

    return {"aggregate": aggregate, "per_query": per_query}
