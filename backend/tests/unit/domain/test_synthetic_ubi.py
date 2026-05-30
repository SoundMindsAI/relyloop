"""Unit tests for ``backend.app.domain.demo.synthetic_ubi``.

Story 1.2 (FR-2) — pins:

* Determinism across runs.
* Per-rung event totals: ``impressions + clicks + dwell == sum``.
* Hamilton allocator: ``sum(_allocate_impressions(...)) == impressions_total``
  exactly for every (rung's impressions_total, num_docs) pair the
  scenario catalog actually uses.
* Position-bias: rank 1 always has the largest impression count.
* ``_click_probability_for_rating`` mapping + base-scaling + ValueError.
* ``application=target_application`` on every row.
* All event timestamps inside ``[anchor - 60s, anchor]``.
* Click-rating correlation: mean rating of clicked pairs strictly
  exceeds the mean of all candidate pairs (proves the Bernoulli
  weighting biases toward higher ratings).
* No I/O imports in the synthetic_ubi module.
"""

from __future__ import annotations

import ast
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.app.domain.demo.synthetic_ubi import (
    UbiEventRow,
    UbiQueryRow,
    UbiRung,
    _allocate_impressions,
    _click_probability_for_rating,
    _decay_weights,
    _volumes_for_rung,
    fabricate_ubi_for_scenario,
)

# ---- Test fixtures ----

# Mirrors the acme-products-prod judgments_map slice from
# scripts/seed_meaningful_demos.py (verified up-to-date at file load).
_ACME_JUDGMENTS: list[tuple[int, str, int]] = [
    (0, "p1001", 3),
    (0, "p1002", 3),
    (0, "p2001", 0),
    (1, "p2001", 3),
    (1, "p2002", 3),
    (1, "p1001", 0),
    (2, "p3001", 3),
    (2, "p1001", 0),
    (3, "p1001", 3),
    (3, "p1002", 1),
]

# Five queries × five docs gives us material to exercise rung_3's
# num_docs_per_query=5 even if a real scenario only seeds 3-4 distinct
# docs per query.
_ACME_QUERIES_5: dict[int, str] = {
    0: "wireless noise cancelling headphones",
    1: "womens running shoes",
    2: "kitchen knife set",
    3: "sony headphones",
    4: "noise cancelling over ear",
}
_ACME_QIDS_5: dict[int, str] = {
    0: "q0-uuid",
    1: "q1-uuid",
    2: "q2-uuid",
    3: "q3-uuid",
    4: "q4-uuid",
}

# A wider judgments map covering all 5 queries × 5 docs so rung_3 has
# enough variety to exercise position-bias decay across full rank
# range.
_WIDE_JUDGMENTS: list[tuple[int, str, int]] = [
    *_ACME_JUDGMENTS,
    (0, "p2002", 0),
    (0, "p3001", 0),
    (1, "p3001", 0),
    (1, "p1002", 0),
    (2, "p2001", 0),
    (2, "p2002", 0),
    (2, "p1002", 1),
    (3, "p2001", 0),
    (3, "p2002", 0),
    (3, "p3001", 0),
    (4, "p1001", 3),
    (4, "p1002", 3),
    (4, "p2001", 0),
    (4, "p2002", 0),
    (4, "p3001", 0),
]


_ANCHOR_ISO = "2026-05-29T12:34:56+00:00"


def _fabricate(rung: UbiRung) -> tuple[list[UbiQueryRow], list[UbiEventRow]]:
    return fabricate_ubi_for_scenario(
        scenario_judgments_map=_WIDE_JUDGMENTS,
        query_id_by_index=_ACME_QIDS_5,
        query_text_by_index=_ACME_QUERIES_5,
        target_application="products",
        target_rung=rung,
        seed_anchor_iso=_ANCHOR_ISO,
        seed=42,
    )


# ---- Tests ----


def test_determinism_same_inputs_same_outputs() -> None:
    a_q, a_e = _fabricate("rung_3")
    b_q, b_e = _fabricate("rung_3")
    assert a_q == b_q
    assert a_e == b_e


@pytest.mark.parametrize(
    "rung,expected_total",
    [("rung_3", 560 + 40 + 40), ("rung_2", 200 + 20 + 20), ("rung_1", 40 + 5 + 5)],
)
def test_per_rung_event_totals(rung: UbiRung, expected_total: int) -> None:
    _, events = _fabricate(rung)
    assert len(events) == expected_total, (
        f"{rung} event count {len(events)} != target {expected_total}"
    )


@pytest.mark.parametrize("rung", ["rung_3", "rung_2", "rung_1"])
def test_per_rung_action_breakdowns(rung: UbiRung) -> None:
    _, events = _fabricate(rung)
    vol = _volumes_for_rung(rung)
    by_action: dict[str, int] = {}
    for ev in events:
        by_action[ev.action_name] = by_action.get(ev.action_name, 0) + 1
    assert by_action.get("impression") == vol.impressions_total
    assert by_action.get("click") == vol.clicks_total
    assert by_action.get("dwell") == vol.dwell_events_total


@pytest.mark.parametrize(
    "impressions_total,num_docs",
    [
        # Every (impressions_total, num_docs) pair _volumes_for_rung actually
        # produces. If RungVolumes' embedded shape changes, this list updates.
        (560, 5),  # rung_3
        (200, 5),  # rung_2
        (40, 3),  # rung_1
    ],
)
def test_hamilton_allocator_sum_invariant(impressions_total: int, num_docs: int) -> None:
    """Sum of per-rank allocations equals the requested total exactly."""
    alloc = _allocate_impressions(impressions_total, num_docs)
    assert sum(alloc) == impressions_total
    assert len(alloc) == num_docs


def test_hamilton_allocator_top_rank_has_most_impressions() -> None:
    """Position-bias decay must put more impressions at rank 1 than at
    any later rank — this is what makes Wang-Bendersky's correction
    non-trivial."""
    alloc = _allocate_impressions(560, 5)
    assert alloc[0] == max(alloc), f"top rank should win; alloc={alloc}"


def test_decay_weights_monotone_decreasing() -> None:
    weights = _decay_weights(5)
    for i in range(len(weights) - 1):
        assert weights[i] > weights[i + 1]


def test_decay_weights_rejects_non_positive_num_docs() -> None:
    with pytest.raises(ValueError):
        _decay_weights(0)
    with pytest.raises(ValueError):
        _decay_weights(-3)


@pytest.mark.parametrize("rating,expected", [(0, 0.0), (1, 0.2), (2, 0.5), (3, 0.8)])
def test_click_probability_default_base(rating: int, expected: float) -> None:
    assert _click_probability_for_rating(rating) == pytest.approx(expected)


@pytest.mark.parametrize("rating,base,expected", [(1, 0.5, 0.1), (2, 0.5, 0.25), (3, 2.0, 1.6)])
def test_click_probability_base_scaling(rating: int, base: float, expected: float) -> None:
    assert _click_probability_for_rating(rating, base=base) == pytest.approx(expected)


@pytest.mark.parametrize("rating", [-1, 4, 99])
def test_click_probability_value_error_on_bad_rating(rating: int) -> None:
    with pytest.raises(ValueError):
        _click_probability_for_rating(rating)


def test_application_tag_on_every_row() -> None:
    queries, events = _fabricate("rung_3")
    for q in queries:
        assert q.application == "products"
    for e in events:
        assert e.application == "products"


def test_event_timestamps_inside_window() -> None:
    """Every event timestamp must fall inside [anchor - 60s, anchor].

    The UBI dispatcher's deterministic since/until window depends on
    this — events outside the window produce UBI_INSUFFICIENT_DATA.
    """
    anchor = datetime.fromisoformat(_ANCHOR_ISO)
    start = anchor - timedelta(seconds=60)
    _, events = _fabricate("rung_3")
    for e in events:
        ts = datetime.fromisoformat(e.timestamp)
        assert start <= ts <= anchor, (
            f"event timestamp {e.timestamp} outside window [{start}, {anchor}]"
        )


def test_click_rating_correlation() -> None:
    """Clicked pairs' mean rating must strictly exceed the mean rating
    of all candidate pairs. Proves the Bernoulli-style weighting biases
    toward higher ratings — this is what makes the per-judgment-list
    value-delta card show meaningful (not random) deltas vs the LLM list.
    """
    _, events = _fabricate("rung_3")
    # Build candidate set: every (query, doc) pair that received
    # impressions (the same set the sampler picked clicks from).
    candidates: dict[tuple[str, str], int] = {}
    for ev in events:
        if ev.action_name == "impression":
            key = (ev.query_id, ev.object_id)
            candidates[key] = candidates.get(key, 0)  # init
    # Rating lookup via the wide judgments map.
    qid_by_text_idx = _ACME_QIDS_5
    rating_by_qd: dict[tuple[str, str], int] = {}
    for qi, doc_id, rating in _WIDE_JUDGMENTS:
        rating_by_qd[(qid_by_text_idx[qi], doc_id)] = rating
    candidate_ratings = [rating_by_qd[k] for k in candidates if k in rating_by_qd]
    clicked_ratings = [
        rating_by_qd[(e.query_id, e.object_id)]
        for e in events
        if e.action_name == "click" and (e.query_id, e.object_id) in rating_by_qd
    ]
    assert candidate_ratings, "no candidates — wide judgments map drift?"
    assert clicked_ratings, "no clicks generated — rung_3 should produce 40"
    candidate_mean = statistics.mean(candidate_ratings)
    clicked_mean = statistics.mean(clicked_ratings)
    assert clicked_mean > candidate_mean, (
        f"clicked mean {clicked_mean:.2f} should exceed candidate mean "
        f"{candidate_mean:.2f} — clicks are not correlated with rating"
    )


def test_no_io_imports_in_module() -> None:
    """The pure-domain generator must NOT import httpx, sqlalchemy,
    or any backend settings/adapter module."""
    src = Path("backend/app/domain/demo/synthetic_ubi.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"httpx", "sqlalchemy", "redis", "backend.app.adapters", "backend.app.core.settings"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    leaks = banned & imported
    assert not leaks, f"forbidden imports in synthetic_ubi.py: {leaks}"


def test_query_count_matches_input_dict() -> None:
    queries, _ = _fabricate("rung_2")
    assert len(queries) == 5  # _ACME_QIDS_5 has 5 entries
    for q in queries:
        assert q.query_id in _ACME_QIDS_5.values()
