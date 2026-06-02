# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pure shape invariants on the enriched demo SCENARIOS.

Lands with ``feat_studies_convergence_visibility`` Epic 2 Story 2.3 (per the
plan's Testing workstream §3.1). The engine-backed headroom test
(``backend/tests/integration/test_demo_scenarios_headroom.py``) is the
deterministic FR-5 gate, but it requires a running ES + OpenSearch (+ Solr
locally) and several seconds per scenario. These pure shape invariants run
in milliseconds with no engine, and catch the cheap regression modes that
would silently break the headroom test BEFORE it loads the slow path:

- A scenario lost docs and dropped below the D-8 floor.
- A scenario's judgments_map collapsed back to all-grade-3 (the degenerate
  state Story 2.1 fixed).
- A judgment row references a doc_id that no longer exists in ``docs``.
- A judgment row references a query_idx out of range.
- A judgment rating drifted out of {0, 1, 2, 3}.

The numbers below pin the D-8 / Story 2.1 enrichment targets — they must
match the spec's data-design recipe so a future edit can't silently
regress the data shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.seed_meaningful_demos import SCENARIOS

# D-8 spec targets (per ``feature_spec.md`` §FR-5 + the headroom test's
# data-design recipe). Lower bounds — the actual enrichment may exceed.
# D-8 / Story 2.1 / GPT-5.5 cycle-1 F4: enriched judgments must span the
# FULL rating range {0, 1, 2, 3} so a future regression that drops one
# rubric bucket (e.g., loses all grade-2 "okay" docs) fails the test even
# if total count stays the same. Requiring all 4 ratings keeps the
# decoy / best-answer headroom pattern intact.
_MIN_DOCS_PER_SCENARIO = 12
_MIN_GRADED_DOCS_PER_QUERY = 4
_VALID_RATINGS: frozenset[int] = frozenset({0, 1, 2, 3})
_REQUIRED_RATINGS_PER_QUERY: frozenset[int] = _VALID_RATINGS


def _scenarios_by_slug() -> dict[str, dict[str, Any]]:
    return {s["slug"]: s for s in SCENARIOS}


def _slugs() -> list[str]:
    """Return scenario slugs in their SCENARIOS-literal order.

    Parametrized tests below use ``ids=`` from this list so pytest output
    names each per-scenario case by slug — far easier to triage than a
    numeric index. Order tracks the literal so a regenerated test report
    matches a top-to-bottom read of ``scripts/seed_meaningful_demos.py``.
    """
    return [s["slug"] for s in SCENARIOS]


@pytest.mark.parametrize("slug", _slugs())
def test_scenario_doc_count_meets_d8_floor(slug: str) -> None:
    """Every enriched scenario carries at least ``_MIN_DOCS_PER_SCENARIO`` docs.

    Below the floor the headroom test runs out of decoy candidates and the
    BM25 distribution collapses (too few terms to differentiate ranking),
    putting the baseline NDCG back at 1.0.
    """
    scenario = _scenarios_by_slug()[slug]
    actual = len(scenario["docs"])
    assert actual >= _MIN_DOCS_PER_SCENARIO, (
        f"[{slug}] only {actual} docs — D-8 requires >= "
        f"{_MIN_DOCS_PER_SCENARIO} candidate docs per scenario for the "
        f"headroom test's decoy pool"
    )


@pytest.mark.parametrize("slug", _slugs())
def test_scenario_judgments_reference_valid_doc_and_query_ids(slug: str) -> None:
    """Every (query_idx, doc_id, rating) row resolves to an existing doc + query.

    A judgments_map entry that points at a removed doc would silently feed
    ``qrels`` a phantom doc_id; the headroom test's ``score()`` call would
    accept it (the eval engine's per-query universe is the intersection of
    qrels and run), and the score would skew without an actionable error
    message. This shape check raises that error at the unit-test layer.
    """
    scenario = _scenarios_by_slug()[slug]
    doc_ids = {d["id"] for d in scenario["docs"]}
    query_count = len(scenario["queries"])
    for query_idx, doc_id, rating in scenario["judgments_map"]:
        assert 0 <= query_idx < query_count, (
            f"[{slug}] judgment row references query_idx={query_idx} but "
            f"scenario only has {query_count} queries"
        )
        assert doc_id in doc_ids, (
            f"[{slug}] judgment row references doc_id={doc_id!r} which is "
            f"not in the scenario's docs list"
        )
        assert rating in _VALID_RATINGS, (
            f"[{slug}] judgment row carries rating={rating}, but the rubric "
            f"only allows {sorted(_VALID_RATINGS)}"
        )


@pytest.mark.parametrize("slug", _slugs())
def test_scenario_each_query_has_minimum_judgment_density(slug: str) -> None:
    """Every query has >= ``_MIN_GRADED_DOCS_PER_QUERY`` graded docs.

    Sparse coverage was the original degenerate state — a query with only
    one grade-3 doc judged makes baseline NDCG trivially 1.0 whenever the
    engine returns that doc anywhere in the top-K. Density is the
    pre-condition for headroom.
    """
    scenario = _scenarios_by_slug()[slug]
    per_query_counts: dict[int, int] = {}
    for query_idx, _doc_id, _rating in scenario["judgments_map"]:
        per_query_counts[query_idx] = per_query_counts.get(query_idx, 0) + 1
    for query_idx in range(len(scenario["queries"])):
        actual = per_query_counts.get(query_idx, 0)
        assert actual >= _MIN_GRADED_DOCS_PER_QUERY, (
            f"[{slug}] query #{query_idx} "
            f"({scenario['queries'][query_idx]['query_text']!r}) "
            f"has only {actual} graded judgments — D-8 requires >= "
            f"{_MIN_GRADED_DOCS_PER_QUERY} for the decoy / best-answer "
            f"pattern to land headroom"
        )


@pytest.mark.parametrize("slug", _slugs())
def test_scenario_each_query_spans_full_rubric(slug: str) -> None:
    """Every query's judgments span the full ``{0,1,2,3}`` rubric.

    The headroom test's data-design recipe (the comment block atop
    ``_BETTER_PARAMS`` in
    ``backend/tests/integration/test_demo_scenarios_headroom.py``) requires a
    grade-3 "best answer", a grade-1 "decoy", a grade-2 "okay", and a
    grade-0 "wrong" per query. The original ``>= 3 distinct ratings``
    formulation (pre-GPT-5.5-cycle-1-F4) allowed a future regression that
    dropped one rubric bucket while still passing — tightening to the full
    set catches that silent drift at the unit-test layer.
    """
    scenario = _scenarios_by_slug()[slug]
    ratings_per_query: dict[int, set[int]] = {}
    for query_idx, _doc_id, rating in scenario["judgments_map"]:
        ratings_per_query.setdefault(query_idx, set()).add(int(rating))
    for query_idx in range(len(scenario["queries"])):
        distinct = ratings_per_query.get(query_idx, set())
        missing = _REQUIRED_RATINGS_PER_QUERY - distinct
        assert not missing, (
            f"[{slug}] query #{query_idx} "
            f"({scenario['queries'][query_idx]['query_text']!r}) "
            f"is missing rating bucket(s) {sorted(missing)} "
            f"(spans {sorted(distinct)}) — D-8 / Story 2.1 requires the full "
            f"{sorted(_REQUIRED_RATINGS_PER_QUERY)} rubric per query so the "
            f"baseline-vs-better ranking gap can show through every gradation"
        )


def test_scenario_count_unchanged() -> None:
    """SCENARIOS still has the 5 expected demo scenarios.

    A future edit that drops a scenario silently shrinks the demo; this is
    the canary that the per-scenario parametrize blocks rely on (no
    scenario can hide from those checks if the count is locked).
    """
    expected = {
        "acme-products-prod",
        "corp-docs-search",
        "news-search-staging",
        "jobs-marketplace-prod",
        "acme-kb-docs-solr",
    }
    actual = {s["slug"] for s in SCENARIOS}
    assert actual == expected, (
        f"SCENARIOS slug set drifted — "
        f"missing: {expected - actual or '{}'} ; "
        f"unexpected: {actual - expected or '{}'}"
    )
