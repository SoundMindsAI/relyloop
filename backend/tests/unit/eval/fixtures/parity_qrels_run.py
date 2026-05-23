"""Parity fixture for the pytrec_eval ↔ ir_measures value-equivalence test.

Source of truth for ``backend/tests/unit/eval/test_scoring_parity.py``
(infra_ir_measures_migration Stories 1.2 + 1.4 — see [implementation_plan.md]).

The fixture is hand-crafted to exercise every edge case the spec FR-2 / FR-3
parity contracts cover. Each query's role is documented inline; do not add
queries without updating the docstring.

The two ``Qrels``/``Run`` shapes here are exactly what
:func:`backend.app.eval.scoring.score` accepts; the test imports them and
calls both ``score()`` (the function under test) and ``pytrec_eval`` directly
to assert 6-decimal-place value equivalence + per-query shape parity.
"""

from __future__ import annotations

from backend.app.eval.scoring import Qrels, Run

# ---------------------------------------------------------------------------
# QRELS — {query_id: {doc_id: int rating}}
# ---------------------------------------------------------------------------
#
# Edge-case map (also documented in test_scoring_parity.py):
#
#   Case (a)  no-relevant-docs:   q_no_relevant       — all docs rated 0
#   Case (b)  qrel-only:          q_qrel_only         — present in qrels; missing from run
#   Case (c)  run-only:           q_run_only          — present in run; missing from qrels
#   Case (d)  zero-overlap:       q_zero_overlap      — both present; disjoint doc IDs
#   Case (e)  empty-inner-qrels:  q_empty_qrels       — qrels[qid] == {} but run[qid] non-empty
#   Case (f)  empty-inner-run:    q_empty_run         — run[qid] == {} but qrels[qid] non-empty
#
# Plus four "normal" queries with realistic graded ratings + non-trivial
# rankings, giving the parity test enough signal across the metric × k cross
# to catch most divergences.

QRELS: Qrels = {
    # ---- Normal queries (mixed graded ratings) ----
    "q1": {"d1": 3, "d2": 2, "d3": 1, "d4": 0, "d5": 1},  # 5 docs, 4 relevant
    "q2": {"d1": 2, "d2": 0, "d3": 3, "d4": 1, "d5": 0},  # 5 docs, 3 relevant
    "q3": {"d1": 1, "d2": 1, "d3": 1, "d4": 1, "d5": 1},  # binary-style, all relevant
    "q4": {"d1": 3, "d2": 0, "d3": 0, "d4": 0, "d5": 2},  # 5 docs, 2 relevant — tail skew
    # ---- Edge cases ----
    "q_no_relevant": {"d1": 0, "d2": 0, "d3": 0},  # Case (a): qrels exist but no relevance
    "q_qrel_only": {"d1": 2, "d2": 1, "d3": 3},  # Case (b): qrels with no matching run
    # q_run_only — INTENTIONALLY absent from QRELS (Case c is qrels-missing for that qid)
    "q_zero_overlap": {"d1": 3, "d2": 2},  # Case (d): qrels for d1/d2, run for d8/d9
    "q_empty_qrels": {},  # Case (e): empty inner dict
    "q_empty_run": {"d1": 2, "d2": 1},  # Case (f): qrels present, run will be empty
}

# ---------------------------------------------------------------------------
# RUN — {query_id: {doc_id: float score}}
# ---------------------------------------------------------------------------
RUN: Run = {
    # ---- Normal queries ----
    "q1": {"d1": 0.95, "d2": 0.85, "d3": 0.65, "d4": 0.55, "d5": 0.45},  # perfect-ish
    "q2": {"d2": 0.95, "d4": 0.85, "d1": 0.75, "d3": 0.65, "d5": 0.55},  # inverted
    "q3": {"d1": 0.9, "d2": 0.8, "d3": 0.7, "d4": 0.6, "d5": 0.5},  # full-recall ordering
    "q4": {"d2": 0.95, "d3": 0.85, "d1": 0.75, "d4": 0.65, "d5": 0.55},  # bad ordering
    # ---- Edge cases ----
    "q_no_relevant": {"d1": 0.9, "d2": 0.8, "d3": 0.7},  # Case (a): run present
    # q_qrel_only — INTENTIONALLY absent from RUN (Case b is run-missing for that qid)
    "q_run_only": {"d100": 0.95, "d101": 0.85},  # Case (c): run with no qrels for the qid
    "q_zero_overlap": {"d8": 0.9, "d9": 0.8},  # Case (d): different doc IDs than qrels
    "q_empty_qrels": {"d1": 0.9, "d2": 0.8},  # Case (e): non-empty run paired with empty qrels
    "q_empty_run": {},  # Case (f): empty inner dict
}

# Sanity-check at module-load time: ensure each case is actually present where
# the comments say it is. Catches accidental edits that defeat the fixture's
# purpose. (Asserts on import; pytest collection surfaces the failure.)
assert "q_qrel_only" in QRELS and "q_qrel_only" not in RUN, (
    "fixture broken: q_qrel_only should be qrels-only"
)
assert "q_run_only" in RUN and "q_run_only" not in QRELS, (
    "fixture broken: q_run_only should be run-only"
)
assert QRELS["q_empty_qrels"] == {} and RUN["q_empty_qrels"], (
    "fixture broken: q_empty_qrels needs empty qrels + non-empty run"
)
assert RUN["q_empty_run"] == {} and QRELS["q_empty_run"], (
    "fixture broken: q_empty_run needs empty run + non-empty qrels"
)
