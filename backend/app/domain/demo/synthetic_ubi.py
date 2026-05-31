# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic UBI clickstream generator (Story 1.2 / FR-2).

Pure-domain — no I/O, no httpx, no Settings. Given a demo scenario's
existing rubric-graded judgments map plus the API-assigned query UUIDs,
returns deterministic ``UbiQueryRow`` + ``UbiEventRow`` lists that hit a
target ``UBI`` readiness rung when bulk-written to Elasticsearch.

Invariants pinned by ``backend/tests/unit/domain/test_synthetic_ubi.py``:

* Same inputs → identical row lists across runs (no ``time.time()``,
  no ``uuid4()``, only ``random.Random(seed)``).
* ``sum(impressions_by_rank) == _volumes_for_rung(rung).impressions_total``
  exactly, for every (rung, ``num_docs_per_query``) pair (Hamilton /
  largest-remainder allocator).
* Total event count per scenario matches the rung's target so the live
  ``classify_rung`` returns the expected rung after bulk-write.
* Every row carries ``application=target_application``.
* All event timestamps fall inside ``[seed_anchor - 60s, seed_anchor]``.

Reference: ``docs/00_overview/planned_features/02_mvp2/`` →
``feat_demo_ubi_study_comparison/`` (spec FR-2, plan Story 1.2).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

# Public ----------------------------------------------------------------

UbiRung = Literal["rung_1", "rung_2", "rung_3"]

# Per-rating click probability when ``base == 1.0`` (FR-2 / D-11).
_RATING_CLICK_PROB: Final[dict[int, float]] = {0: 0.0, 1: 0.2, 2: 0.5, 3: 0.8}

# Per-rating dwell-seconds (uniform-int range; rating 0 produces no
# clicks so it has no dwell entry).
_RATING_DWELL_RANGE: Final[dict[int, tuple[int, int]]] = {
    3: (30, 60),
    2: (10, 30),
    1: (3, 10),
}

# Position-bias decay base (D-10). Lower → steeper bias → bigger Wang-
# Bendersky correction in ``CtrThresholdConverter``.
_DECAY: Final[float] = 0.6


@dataclass(frozen=True)
class UbiQueryRow:
    """One ``ubi_queries`` document."""

    query_id: str
    user_query: str
    application: str
    timestamp: str  # ISO-8601 with timezone


@dataclass(frozen=True)
class UbiEventRow:
    """One ``ubi_events`` document.

    ``position`` is set on ``impression`` rows; ``dwell_seconds`` is set
    on ``dwell`` rows; ``click`` rows have neither. Matches the existing
    Playwright helper's row shape and the canonical mapping in
    ``samples/ubi_index_mappings.json``.
    """

    query_id: str
    action_name: Literal["impression", "click", "dwell"]
    object_id: str
    application: str
    timestamp: str
    position: int | None = None
    dwell_seconds: float | None = None


@dataclass(frozen=True)
class RungVolumes:
    """Per-rung event-count targets + the embedded scenario shape.

    ``num_queries`` and ``num_docs_per_query`` are part of the contract
    (FR-2) so a regression that changes the SCENARIOS catalog's
    queries-per-scenario or docs-per-query is caught at the generator
    level, not by an integration test.
    """

    impressions_total: int
    clicks_total: int
    dwell_events_total: int
    num_queries: int
    num_docs_per_query: int


# Helpers ----------------------------------------------------------------


def _volumes_for_rung(rung: UbiRung) -> RungVolumes:
    """Per-rung event-volume targets (D-9).

    Designed so the ``classify_rung`` thresholds at
    ``min_impressions_threshold=100`` (rung_2 floor) and
    ``5 × min_impressions_threshold=500`` (rung_3 floor) are cleared with
    headroom:

    * rung_3 → 560 + 40 + 40 = 640 events (28% above the 500 floor).
    * rung_2 → 200 + 20 + 20 = 240 events (140% above 100, 52% below 500).
    * rung_1 → 40 + 5 + 5 = 50 events (50% below 100).
    """
    if rung == "rung_3":
        return RungVolumes(
            impressions_total=560,
            clicks_total=40,
            dwell_events_total=40,
            num_queries=5,
            num_docs_per_query=5,
        )
    if rung == "rung_2":
        return RungVolumes(
            impressions_total=200,
            clicks_total=20,
            dwell_events_total=20,
            num_queries=5,
            num_docs_per_query=5,
        )
    if rung == "rung_1":
        return RungVolumes(
            impressions_total=40,
            clicks_total=5,
            dwell_events_total=5,
            num_queries=5,
            num_docs_per_query=3,
        )
    raise ValueError(f"unknown rung: {rung!r}")


def _decay_weights(num_docs: int, decay: float = _DECAY) -> list[float]:
    """Position-bias decay weights: ``weights[n] = decay**n``.

    Not normalized — the caller divides by ``sum(weights)`` to get
    fractional quotas. Top-ranked doc always carries the highest weight.
    """
    if num_docs <= 0:
        raise ValueError(f"num_docs must be positive, got {num_docs}")
    return [decay**n for n in range(num_docs)]


def _allocate_impressions(
    impressions_total: int, num_docs: int, decay: float = _DECAY
) -> list[int]:
    """Hamilton (largest-remainder) allocator.

    Returns a list of length ``num_docs`` whose ``sum == impressions_total``
    exactly. Distributes by floor of each rank's fractional quota, then
    assigns remainder impressions one-by-one to the ranks with the
    largest fractional parts (ties broken by lower rank index so the
    top-ranked doc wins).
    """
    weights = _decay_weights(num_docs, decay=decay)
    total_weight = sum(weights)
    quotas = [impressions_total * w / total_weight for w in weights]
    floors = [int(q) for q in quotas]
    remainder = impressions_total - sum(floors)
    # Pair each rank with its fractional remainder; sort descending by
    # fractional part, ties broken by lower rank index (so top doc wins).
    fractionals = sorted(
        ((q - int(q), i) for i, q in enumerate(quotas)),
        key=lambda t: (-t[0], t[1]),
    )
    for _, idx in fractionals[:remainder]:
        floors[idx] += 1
    if sum(floors) != impressions_total:
        # Hamilton allocator should be exact by construction; this is a
        # programming-error check, not a runtime branch we expect to hit.
        raise RuntimeError(f"Hamilton allocator drift: sum={sum(floors)} != {impressions_total}")
    return floors


def _click_probability_for_rating(rating: int, base: float = 1.0) -> float:
    """Maps a rubric rating to click probability scaled by ``base``.

    Per FR-2 / D-11:
        0 → 0.0 × base
        1 → 0.2 × base
        2 → 0.5 × base
        3 → 0.8 × base

    ``base`` lets callers parameterize correlation strength; the
    generator uses the default ``1.0`` and the click count is enforced
    via the Hamilton-allocator-style sampler in
    ``_sample_clicked_pairs`` (so the result count is exact regardless
    of ``base``).
    """
    if rating not in _RATING_CLICK_PROB:
        raise ValueError(f"rating must be 0..3, got {rating!r}")
    return _RATING_CLICK_PROB[rating] * base


def _sample_clicked_pairs(
    candidate_pairs: list[tuple[int, str, int]],
    clicks_total: int,
    rng: random.Random,
) -> list[tuple[int, str, int]]:
    """Pick clicked pairs weighted by rubric rating.

    Returns exactly ``clicks_total`` (query_index, doc_id, rating) pairs
    from ``candidate_pairs``. Implementation: rank candidates by
    ``(click_probability + deterministic_jitter)`` descending, take the
    top ``clicks_total``. Deterministic given ``rng``. Falls back to
    repeating the highest-probability pair if
    ``clicks_total > len(candidate_pairs)`` (which shouldn't happen with
    the current rung_1/2/3 targets and demo scenario sizes — but the
    fallback keeps the contract honest).
    """
    if clicks_total <= 0 or not candidate_pairs:
        return []
    scored: list[tuple[float, tuple[int, str, int]]] = []
    for qi, doc_id, rating in candidate_pairs:
        prob = _click_probability_for_rating(rating)
        # Jitter breaks ties deterministically so the same (rating, seed)
        # produces the same ordering across runs.
        jitter = rng.random() * 0.01
        scored.append((prob + jitter, (qi, doc_id, rating)))
    scored.sort(key=lambda t: -t[0])
    picked = [pair for _, pair in scored[:clicks_total]]
    # Fallback: top up by repeating the highest-prob pair (unlikely path).
    while len(picked) < clicks_total and picked:
        picked.append(picked[0])
    return picked


# Public entry point -----------------------------------------------------


def fabricate_ubi_for_scenario(
    *,
    scenario_judgments_map: list[tuple[int, str, int]],
    query_id_by_index: dict[int, str],
    query_text_by_index: dict[int, str],
    target_application: str,
    target_rung: UbiRung,
    seed_anchor_iso: str,
    seed: int = 42,
) -> tuple[list[UbiQueryRow], list[UbiEventRow]]:
    """Build a deterministic ``(ubi_queries, ubi_events)`` row pair.

    Args:
        scenario_judgments_map: The scenario's existing LLM-judgments map
            as ``list[(query_index, doc_id, rating)]`` — same shape the
            reseed orchestrator already uses at
            ``backend/app/services/demo_seeding.py:1274``.
        query_id_by_index: API-assigned ``query_id`` per ``query_index``;
            built by the reseed from the ``GET /query-sets/{id}/queries``
            response.
        query_text_by_index: The displayable ``user_query`` text per
            ``query_index``; the reseed already has this in
            ``scenario["queries"]``.
        target_application: The UBI ``application`` filter — must equal
            the scenario's ``target`` (e.g., ``"products"``); the
            ``seed_synthetic_ubi`` helper additionally validates the
            (scenario_slug, target_application) pair against an
            allowlist.
        target_rung: ``"rung_1" | "rung_2" | "rung_3"`` — controls the
            event-count targets.
        seed_anchor_iso: ISO-8601 timestamp anchor for all synthetic
            events. The reseed passes its own ``started_at``; events
            land inside ``[anchor - 60s, anchor]`` so the
            ``POST /judgments/generate-from-ubi`` dispatcher's
            ``since/until`` window deterministically captures them.
        seed: Random seed for the Bernoulli-like sampling. Default 42
            matches the Optuna ``seed=42`` already pinned in the demo.

    Returns:
        Tuple of ``(ubi_queries, ubi_events)`` row lists ready for bulk
        write.
    """
    # ruff S311: synthetic demo data, not security-sensitive — see module docstring
    rng = random.Random(seed)  # noqa: S311
    volumes = _volumes_for_rung(target_rung)

    # Anchor + 60s window.
    seed_anchor = datetime.fromisoformat(seed_anchor_iso)
    if seed_anchor.tzinfo is None:
        seed_anchor = seed_anchor.replace(tzinfo=UTC)
    window_start = seed_anchor - timedelta(seconds=60)
    window_span_s = (seed_anchor - window_start).total_seconds()

    def _pick_ts() -> str:
        # Half-open ``[0, span)`` via ``random()`` (NOT ``uniform(0, span)``,
        # which is inclusive of the upper bound): events must stay strictly
        # BELOW ``seed_anchor`` so the UbiReader's half-open ``timestamp <
        # until`` scan (``until = seed_anchor``) never drops an event that
        # happened to jitter to exactly the upper bound.
        offset = rng.random() * window_span_s  # noqa: S311 — synthetic demo data
        return (window_start + timedelta(seconds=offset)).isoformat()

    # ---- 1. ubi_queries rows (one per query) ----
    # Stamp query rows at ``window_start`` (the INCLUSIVE lower bound), NOT at
    # ``seed_anchor`` (the upper bound). The UbiReader's ``ubi_queries`` scan
    # filters ``timestamp >= since AND timestamp < until`` (half-open), and the
    # demo dispatches ``until = seed_anchor``. A query row stamped at exactly
    # ``seed_anchor`` lands ON the exclusive upper bound and is dropped — which
    # made ``read_features`` return ``{}`` and the worker fail every UBI demo
    # scenario with UBI_INSUFFICIENT_DATA even though hundreds of events were
    # written (the sync count gate only inspects ``ubi_events``, which ARE
    # in-window, so it passed while the worker's query-first scan came up
    # empty). ``window_start`` is inside ``[since, until)`` for any window the
    # dispatcher derives from this same anchor.
    queries: list[UbiQueryRow] = []
    for query_index, query_id in sorted(query_id_by_index.items()):
        queries.append(
            UbiQueryRow(
                query_id=query_id,
                user_query=query_text_by_index.get(query_index, f"query-{query_index}"),
                application=target_application,
                timestamp=window_start.isoformat(),
            )
        )

    # ---- 2. Choose the docs each query gets events against ----
    # Build per-query doc lists from ``scenario_judgments_map``. Pick the
    # first ``num_docs_per_query`` distinct doc_ids that appear for each
    # query in the map; if a query has fewer, pad with the existing ones.
    # The judgments_map preserves rating ordering (high-rated first in
    # the SCENARIOS catalog), so this naturally puts the relevant docs
    # near the top ranks.
    docs_per_query: dict[int, list[tuple[str, int]]] = {}
    for qi, doc_id, rating in scenario_judgments_map:
        docs_per_query.setdefault(qi, [])
        if not any(d == doc_id for d, _ in docs_per_query[qi]):
            docs_per_query[qi].append((doc_id, rating))
    # Trim / pad to the rung's expected num_docs_per_query.
    target_docs = volumes.num_docs_per_query
    for qi, docs in list(docs_per_query.items()):
        if len(docs) > target_docs:
            docs_per_query[qi] = docs[:target_docs]
        elif len(docs) < target_docs and docs:
            # Repeat the last (lowest-rated) doc to pad. Slightly
            # degenerate, but unit-test-clear.
            pad = docs[-1]
            docs_per_query[qi] = docs + [pad] * (target_docs - len(docs))

    # ---- 3. Allocate impressions across queries and ranks ----
    # Split impressions_total evenly across the queries with leftover
    # going to the highest-index query (deterministic).
    query_indices = sorted(query_id_by_index)
    num_queries = len(query_indices)
    per_query_imp = volumes.impressions_total // num_queries
    leftover = volumes.impressions_total - per_query_imp * num_queries
    impression_budget_by_query = {qi: per_query_imp for qi in query_indices}
    if leftover:
        impression_budget_by_query[query_indices[-1]] += leftover

    events: list[UbiEventRow] = []
    candidate_click_pairs: list[tuple[int, str, int]] = []
    for qi in query_indices:
        query_id = query_id_by_index[qi]
        docs = docs_per_query.get(qi, [])
        if not docs:
            continue
        rank_alloc = _allocate_impressions(impression_budget_by_query[qi], len(docs))
        for rank, ((doc_id, rating), imp_count) in enumerate(zip(docs, rank_alloc, strict=True)):
            for _ in range(imp_count):
                events.append(
                    UbiEventRow(
                        query_id=query_id,
                        action_name="impression",
                        object_id=doc_id,
                        application=target_application,
                        timestamp=_pick_ts(),
                        position=rank + 1,
                    )
                )
            candidate_click_pairs.append((qi, doc_id, rating))

    # ---- 4. Pick exactly clicks_total clicks; emit click + dwell ----
    clicked_pairs = _sample_clicked_pairs(candidate_click_pairs, volumes.clicks_total, rng)
    for qi, doc_id, rating in clicked_pairs:
        query_id = query_id_by_index[qi]
        events.append(
            UbiEventRow(
                query_id=query_id,
                action_name="click",
                object_id=doc_id,
                application=target_application,
                timestamp=_pick_ts(),
            )
        )
        # Paired dwell event — rating 0 has no dwell range; if it somehow
        # slips into the clicked set (sampler shouldn't pick it, but
        # defensive), fall back to a 1-second dwell.
        dwell_range = _RATING_DWELL_RANGE.get(rating, (1, 1))
        dwell_seconds = float(rng.randint(*dwell_range))
        events.append(
            UbiEventRow(
                query_id=query_id,
                action_name="dwell",
                object_id=doc_id,
                application=target_application,
                timestamp=_pick_ts(),
                dwell_seconds=dwell_seconds,
            )
        )

    return queries, events


__all__ = [
    "UbiEventRow",
    "UbiQueryRow",
    "UbiRung",
    "RungVolumes",
    "fabricate_ubi_for_scenario",
]
