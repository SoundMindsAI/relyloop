"""IR-evaluation scoring helper (infra_optuna_eval Story 1.2 / FR-3 + FR-5).

Pure-functional layer. ``score(qrels, run, metrics)`` is the only function the
``run_trial`` worker calls; it owns the user-facing → ``ir_measures``
metric-object translation so library wire forms never leak past this module
(per spec §FR-3 last paragraph).

Migrated from ``pytrec_eval`` to ``ir_measures`` by infra_ir_measures_migration
(2026-05-22). The migration preserves every public-API surface byte-identically
— callers (run_trial, confidence.py, the studies endpoint, every test) need
zero source changes. ``ir_measures`` wraps multiple IR-evaluation backends
(including a transitive ``pytrec-eval-terrier`` for the cut-aware metrics we
use) behind a typed metric-object DSL: ``nDCG@10``, ``AP@10``, ``P@10``, etc.
Per the migration's parity test at
``backend/tests/unit/eval/test_scoring_parity.py``, every supported
``(metric, k)`` cell matches the legacy ``pytrec_eval`` output to 1e-6.

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

import ir_measures
from ir_measures import AP, RR, P, R, nDCG
from ir_measures.measures import Measure

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


def _translate_metric_name(user_facing: str) -> Measure:
    """Translate a user-facing metric token to an ``ir_measures`` metric object.

    Source of truth for the §FR-3 translation table. Returned metric objects
    are passed straight to ``ir_measures.iter_calc(...)``; ``ir_measures``'
    metric-object ``repr`` strings never leak past ``score()`` — this helper
    is module-private and ``score()`` re-keys per-(qid, metric) results back
    to the user-facing tokens before returning.

    Locked mapping table (infra_ir_measures_migration FR-1 / cycle-1 F3):

    +---------------------+----------------------+
    | User-facing token   | ``ir_measures`` obj  |
    +=====================+======================+
    | ``ndcg@<k>``        | ``nDCG @ k``         |
    +---------------------+----------------------+
    | ``map``             | ``AP``               |
    +---------------------+----------------------+
    | ``map@<k>``         | ``AP @ k``           |
    +---------------------+----------------------+
    | ``precision@<k>``   | ``P @ k``            |
    +---------------------+----------------------+
    | ``recall@<k>``      | ``R @ k``            |
    +---------------------+----------------------+
    | ``mrr``             | ``RR``               |
    +---------------------+----------------------+

    Uncut ``ndcg`` / ``precision`` / ``recall`` are still rejected — no new
    "plain metric" path is opened up by this migration (FR-1 / cycle-1 F1
    rejection: original behavior preserved).

    Raises:
        ValueError: on unparseable tokens or out-of-allowlist metrics/k values.
            Every triggering input from the pre-migration scoring.py is
            preserved byte-identically — same wording, same conditions.
    """
    if user_facing == "mrr":
        return RR
    if user_facing == "map":
        return AP

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
        return nDCG @ k
    if base == "map":
        return AP @ k
    if base == "precision":
        return P @ k
    if base == "recall":
        return R @ k
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

    User-facing metric tokens are translated to ``ir_measures`` metric
    objects via ``_translate_metric_name``; the per-(qid, measure) iteration
    is re-keyed back to user-facing tokens so library wire forms never leak
    past this function. The per-query universe is filtered to the historical
    ``pytrec_eval`` contract (qids that have at least one rated doc in qrels
    AND at least one scored entry in run) so the persisted JSONB key set on
    qrel-only / run-only / empty-overlap edge cases is preserved (FR-3 /
    plan cycle-2 C2-F1 + cycle-3 C3-F1).

    The aggregate is computed via per-query mean over this filtered universe
    — NOT via ``ir_measures.calc_aggregate(...)``, which aggregates over a
    different qid universe and would diverge from the persisted contract on
    edge cases (plan cycle-2 C2-F4).

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
    # Map user-facing token → ir_measures metric object; remember the reverse
    # for re-keying. We key the reverse map by repr(obj) rather than the obj
    # itself because ir_measures metric objects are not always reliably hashable
    # as dict keys across versions; their repr is stable (e.g. "nDCG@10").
    # Short-circuit on empty metric set — preserves the pre-migration behavior
    # of returning empty aggregate + per_query (ir_measures.iter_calc raises
    # IndexError on an empty measures list because its FallbackEvaluator
    # selects providers[0] unconditionally).
    if not metrics:
        return {"aggregate": {}, "per_query": {}}

    user_to_obj: dict[str, Measure] = {m: _translate_metric_name(m) for m in metrics}
    obj_repr_to_user: dict[str, str] = {repr(obj): user for user, obj in user_to_obj.items()}
    obj_list: list[Measure] = list(user_to_obj.values())

    # Universe filter: keep only qids that have at least one rated doc in
    # qrels AND at least one scored entry in run. Mirrors the legacy
    # pytrec_eval.RelevanceEvaluator(qrels, ...).evaluate(run) qid set so
    # the persisted JSONB key set is preserved on qrel-only / run-only /
    # empty-inner-dict edge cases (FR-3 / plan cycle-2 C2-F1 + cycle-3 C3-F1).
    valid_qids: frozenset[str] = frozenset(
        qid for qid in qrels.keys() & run.keys() if qrels.get(qid) and run.get(qid)
    )

    # Per-query: iterate ir_measures' Metric(query_id, measure, value) tuples;
    # filter to the legacy universe; re-key measure → user-facing token.
    per_query: dict[str, dict[str, float]] = {}
    for metric_tuple in ir_measures.iter_calc(obj_list, qrels, run):
        if metric_tuple.query_id not in valid_qids:
            continue
        user_token = obj_repr_to_user.get(repr(metric_tuple.measure))
        if user_token is None:
            # Defense in depth: ir_measures should only emit measures we
            # requested. If we see an unexpected measure (e.g. a backend
            # emitted an internal helper metric), skip silently rather than
            # corrupt the per_query shape.
            continue  # pragma: no cover
        per_query.setdefault(metric_tuple.query_id, {})[user_token] = float(metric_tuple.value)

    # Aggregate: arithmetic mean across queries, per user-facing metric —
    # matches the original logic at the pre-migration scoring.py:187-192 line
    # range. DO NOT delegate to ir_measures.calc_aggregate() (FR-1 / plan
    # cycle-2 C2-F4 contract).
    aggregate: dict[str, float] = {}
    if per_query:
        for user in user_to_obj:
            values = [q[user] for q in per_query.values() if user in q]
            if values:
                aggregate[user] = sum(values) / len(values)

    return {"aggregate": aggregate, "per_query": per_query}
