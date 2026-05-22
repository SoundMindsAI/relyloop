"""Parity test: ir_measures ↔ pytrec_eval value equivalence + per-query shape.

Source-of-truth: infra_ir_measures_migration feature_spec.md FR-2 + FR-3 +
implementation_plan.md Stories 1.2 (fixture + skipped skeleton) and 1.4
(skips removed; assertions live as permanent CI gate).

In Story 1.2 every test is marked ``@pytest.mark.skip`` with a reason
pointing at Story 1.4 — collection works, fixture loads, both libraries
import side-by-side, but no assertion fires yet. Story 1.4 removes the
skips after scoring.py has been migrated (Story 1.3) so the assertions are
graded against the migrated implementation.

The PARITY_CASES list is the 30-case cross from spec FR-2:
    ndcg/precision/recall × 7 k-values = 21
    map × 7 k-values + plain map (no k) = 8
    plain mrr (k ignored) = 1
    total = 30

After Story 1.4 lands, this test runs on every CI invocation (permanent
gate). The dev-group pin in pyproject.toml's [dependency-groups.dev]
keeps pytrec_eval reachable so the side-by-side comparison stays alive.
"""

from __future__ import annotations

import pytest
import pytrec_eval

from backend.app.eval.scoring import (
    SUPPORTED_K_VALUES,
    SUPPORTED_METRICS,
    Qrels,
    Run,
    _translate_metric_name,
    score,
)
from backend.tests.unit.eval.fixtures.parity_qrels_run import QRELS, RUN

# Tolerance for floating-point equivalence (spec FR-2 lock).
_TOLERANCE: float = 1e-6


def _build_parity_cases() -> list[tuple[str, int | None]]:
    """Enumerate the 30 valid (metric, k) parametrize cases from spec FR-2.

    The cross respects per-metric k-rules:
        - ndcg/precision/recall require k (3 × 7 = 21 cases)
        - map accepts both: 7 cut-k cases + 1 plain (no k) = 8 cases
        - mrr ignores k: only (mrr, None) = 1 case
    Total = 30.
    """
    cases: list[tuple[str, int | None]] = []
    k_required = {"ndcg", "precision", "recall"}
    k_values = sorted(SUPPORTED_K_VALUES)
    for metric in sorted(SUPPORTED_METRICS):
        if metric == "mrr":
            cases.append((metric, None))
        elif metric == "map":
            cases.append((metric, None))
            cases.extend((metric, k) for k in k_values)
        elif metric in k_required:
            cases.extend((metric, k) for k in k_values)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected metric {metric!r}")
    return cases


PARITY_CASES: list[tuple[str, int | None]] = _build_parity_cases()
assert len(PARITY_CASES) == 30, (
    f"PARITY_CASES count drift: expected 30, got {len(PARITY_CASES)}. "
    f"See spec FR-2 cross calculation."
)


def _metric_token(metric: str, k: int | None) -> str:
    """Build the user-facing metric token from (metric, k) per scoring.py rules."""
    if metric == "mrr":
        return "mrr"
    if metric == "map" and k is None:
        return "map"
    assert k is not None, f"metric {metric!r} requires k"
    return f"{metric}@{k}"


def _pytrec_aggregate_for_token(token: str, qrels: Qrels, run: Run) -> float:
    """Compute the mean-across-queries aggregate that ``score()`` currently emits.

    Mirrors the re-keying + mean logic at the pre-migration
    ``backend/app/eval/scoring.py:172-192`` (read straight from pytrec_eval's
    output). This is the value the migrated ``score()`` must match to 1e-6.
    """
    # Translate user-facing token → pytrec_eval wire form. We reproduce the
    # pre-migration translation table inline here so the parity test does not
    # depend on the migrated _translate_metric_name's return type.
    wire = _pytrec_wire_name(token)
    evaluator = pytrec_eval.RelevanceEvaluator(qrels, {wire})
    raw_per_query = evaluator.evaluate(run)
    values = [float(per[wire]) for per in raw_per_query.values() if wire in per]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _pytrec_wire_name(user_facing: str) -> str:
    """Pre-migration scoring.py translation, kept INLINE for the parity test.

    Mirrors the lookup table at the (now-rewritten) ``_translate_metric_name``
    PRE-MIGRATION body — the parity test is the only consumer that still needs
    the pytrec_eval wire names. Tracking it here insulates the test from
    Story 1.3's rewrite.
    """
    if user_facing == "mrr":
        return "recip_rank"
    if user_facing == "map":
        return "map"
    base, _, k_str = user_facing.partition("@")
    k = int(k_str)
    if base == "ndcg":
        return f"ndcg_cut_{k}"
    if base == "map":
        return f"map_cut_{k}"
    if base == "precision":
        return f"P_{k}"
    if base == "recall":
        return f"recall_{k}"
    raise AssertionError(f"unexpected metric base {base!r}")  # pragma: no cover


@pytest.mark.skip(reason="scoring.py not yet migrated to ir_measures — activate in Story 1.4")
@pytest.mark.parametrize(("metric", "k"), PARITY_CASES)
def test_score_matches_pytrec_eval_within_1e_minus_6(metric: str, k: int | None) -> None:
    """The migrated ``score()`` aggregate matches pytrec_eval direct to 1e-6.

    Per spec FR-2 / AC-2. The parity test compares ``score()``'s output value
    (computed via ir_measures.iter_calc + manual mean per spec FR-1) against
    a pytrec_eval direct evaluation. Both apply the mean-across-queries
    aggregate over the same qid universe.

    NB: this test does NOT call ``ir_measures.calc_aggregate(...)`` — that
    would test ir_measures' native aggregate, not the migrated ``score()``.
    See spec §19 + plan cycle-2 C2-F4.
    """
    token = _metric_token(metric, k)

    # Function under test — runs through the migrated scoring.py:
    actual = score(QRELS, RUN, {token})["aggregate"].get(token)

    # Reference value — pytrec_eval direct, mean-across-queries:
    expected = _pytrec_aggregate_for_token(token, QRELS, RUN)

    assert actual is not None, (
        f"score() did not emit aggregate for {token!r}; got keys "
        f"{sorted(score(QRELS, RUN, {token})['aggregate'].keys())}"
    )
    assert abs(actual - expected) < _TOLERANCE, (
        f"parity failure for {token!r}: "
        f"score()={actual!r}, pytrec_eval={expected!r}, diff={actual - expected!r}"
    )


@pytest.mark.skip(reason="scoring.py not yet migrated to ir_measures — activate in Story 1.4")
def test_per_query_shape_matches_pytrec_eval() -> None:
    """Per-query shape + per-(qid, metric) value parity per spec FR-3.

    Per spec FR-3 / plan cycle-1 F3 + cycle-2 C2-F1 + cycle-3 C3-F1:
      (a) outer qid set: identical between ``score()`` and pytrec_eval direct.
      (b) inner metric-key set for each qid: identical for every requested
          metric token.
      (c) per-(qid, metric) value parity: every present inner value matches
          pytrec_eval's value within 1e-6.

    The 6 edge cases in the fixture (no-relevant, qrel-only, run-only,
    zero-overlap, empty-inner-qrels, empty-inner-run) are the load-bearing
    coverage for the universe filter ``valid_qids = {qid for qid in
    qrels.keys() & run.keys() if qrels.get(qid) and run.get(qid)}`` in
    scoring.py (Story 1.3).
    """
    # Pick a representative set of tokens (a few cut-aware + plain + mrr).
    tokens = {"ndcg@10", "map@10", "map", "mrr", "precision@10", "recall@10"}
    wires = {_pytrec_wire_name(t): t for t in tokens}

    # score() output (function under test, post-Story-1.3):
    actual = score(QRELS, RUN, tokens)["per_query"]

    # pytrec_eval direct, re-keyed back to user-facing tokens (mirror the
    # pre-migration scoring.py:180-184 logic):
    evaluator = pytrec_eval.RelevanceEvaluator(QRELS, set(wires))
    raw = evaluator.evaluate(RUN)
    expected: dict[str, dict[str, float]] = {}
    for qid, per_wire in raw.items():
        inner: dict[str, float] = {}
        for wire, token in wires.items():
            if wire in per_wire:
                inner[token] = float(per_wire[wire])
        if inner:
            expected[qid] = inner

    # (a) Outer qid set parity.
    assert set(actual.keys()) == set(expected.keys()), (
        f"per_query qid set drift: score() has {sorted(actual.keys())!r}, "
        f"pytrec_eval has {sorted(expected.keys())!r}"
    )

    for qid in actual:
        # (b) Inner metric-key set parity.
        assert set(actual[qid].keys()) == set(expected[qid].keys()), (
            f"per_query[{qid!r}] metric-key set drift: "
            f"score()={sorted(actual[qid].keys())!r}, "
            f"pytrec_eval={sorted(expected[qid].keys())!r}"
        )
        # (c) Per-(qid, metric) value parity.
        for metric_token in actual[qid]:
            diff = abs(actual[qid][metric_token] - expected[qid][metric_token])
            assert diff < _TOLERANCE, (
                f"per_query[{qid!r}][{metric_token!r}] value drift: "
                f"score()={actual[qid][metric_token]!r}, "
                f"pytrec_eval={expected[qid][metric_token]!r}, "
                f"diff={diff!r}"
            )


def test_parity_cases_count_is_30() -> None:
    """Sanity check: PARITY_CASES enumerates exactly 30 cells per spec FR-2."""
    assert len(PARITY_CASES) == 30
    metrics_seen = {m for m, _ in PARITY_CASES}
    assert metrics_seen == SUPPORTED_METRICS
    # Spot-check a few edge cells of the cross.
    assert ("mrr", None) in PARITY_CASES
    assert ("map", None) in PARITY_CASES
    assert ("map", 10) in PARITY_CASES
    assert ("ndcg", 1) in PARITY_CASES
    assert ("precision", 100) in PARITY_CASES


def test_translate_metric_name_still_callable_at_import() -> None:
    """Sanity check: the scoring._translate_metric_name symbol still exists.

    Story 1.2 ships before Story 1.3's rewrite; this test pins the symbol's
    importability so Story 1.4's skip-removal doesn't fail at collection time
    because the symbol changed shape unexpectedly.
    """
    # Pre-migration: returns wire strings. Post-migration: returns metric
    # objects. We don't assert on the type — just that calling it on a valid
    # token doesn't raise.
    result = _translate_metric_name("ndcg@10")
    assert result is not None
