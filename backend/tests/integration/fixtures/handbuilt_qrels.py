"""Hand-built qrels + canned hits used by infra_optuna_eval integration tests.

The qrels here mirror the unit-test fixture from
``backend/tests/unit/eval/test_scoring.py`` so the same hand-derived metric
values (EXPECTED_NDCG_AT_10, EXPECTED_MAP_AT_10) can be asserted at the
integration layer too. Three queries (q1/q2/q3), six total docs.

Story 3.1 tests monkeypatch ``backend.app.eval.qrels_loader.load_qrels`` to
return ``build_qrels(query_ids)`` so the run_trial worker can score without
the ``judgments`` table (which is owned by ``feat_llm_judgments`` and not
yet shipped — see ``qrels_loader.py`` docstring).

Helpers re-key the fixture to the real ``Query.id`` UUIDs created in each
test's setup, so the worker's ``score(qrels, run, ...)`` call sees matching
keys on both sides.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

# Positional ratings — q1/q2/q3 in test_scoring.py's fixture.
_RATINGS: list[dict[str, int]] = [
    {"d1": 3, "d2": 2, "d3": 1},  # q1 — perfect ranking
    {"d1": 2, "d2": 0},  # q2 — inverted, 1 relevant
    {"d1": 1},  # q3 — single relevant doc
]

# Positional hits — same fixture's ``run`` dict.
_HITS: list[list[tuple[str, float]]] = [
    [("d1", 0.9), ("d2", 0.8), ("d3", 0.7)],
    [("d1", 0.6), ("d2", 0.9)],
    [("d1", 0.5)],
]

# Hand-derived expected metric values (see test_scoring.py docstring for math).
EXPECTED_NDCG_AT_10 = (1.0 + (3.0 / math.log2(3)) / 3.0 + 1.0) / 3.0
EXPECTED_MAP_AT_10 = (1.0 + 0.5 + 1.0) / 3.0


def build_qrels(query_ids: Sequence[str]) -> dict[str, dict[str, int]]:
    """Re-key the positional handbuilt qrels to the test's real ``Query.id`` UUIDs.

    ``query_ids`` should have at least 3 entries (one per positional slot);
    extras are ignored.
    """
    return {str(qid): dict(_RATINGS[i]) for i, qid in enumerate(query_ids[: len(_RATINGS)])}


def build_hits_response(query_ids: Sequence[str], top_k: int = 10) -> dict[str, list[Any]]:
    """Return a ``search_batch``-shaped response keyed by the test's UUIDs.

    The stub adapter installed by integration tests calls this to fabricate
    a deterministic ``{query_id: [ScoredHit, ...]}`` response that matches
    the handbuilt qrels above.
    """
    from backend.app.adapters.protocol import ScoredHit

    out: dict[str, list[ScoredHit]] = {}
    for i, qid in enumerate(query_ids[: len(_HITS)]):
        hits = _HITS[i]
        out[str(qid)] = [ScoredHit(doc_id=doc_id, score=score) for doc_id, score in hits[:top_k]]
    return out
