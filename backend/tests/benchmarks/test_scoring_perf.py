# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Performance benchmark for ``backend.app.eval.scoring.score`` (Story 3.2).

Per spec §FR-3: scoring SHOULD complete in <100ms per query for a 50-query
fixture with top_k=10. This benchmark builds a deterministic fixture seeded
with ``random.seed(42)`` and measures the mean wall-clock time per query
across 5 timed iterations after a discarded warm-up call.

Marked ``@pytest.mark.benchmark`` so it doesn't run as part of
``make test-unit`` / ``make test-contract``; opt in via
``uv run pytest -m benchmark backend/tests/benchmarks/``.
"""

from __future__ import annotations

import random
import time

import pytest

from backend.app.eval.scoring import score

pytestmark = pytest.mark.benchmark


def _build_fixture(
    n_queries: int = 50, top_k: int = 10, n_total_docs: int = 30
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, float]]]:
    """Build a deterministic qrels + run fixture seeded with random.seed(42).

    Each query has ~half the docs rated 0..3 (graded) and the run returns
    ``top_k`` docs with synthetic scores.
    """
    rng = random.Random(42)
    qrels: dict[str, dict[str, int]] = {}
    run: dict[str, dict[str, float]] = {}
    for q in range(n_queries):
        qid = f"q{q}"
        # Sample ~n_total_docs/2 relevant docs (rating > 0), rest 0.
        docs = [f"d{q}-{d}" for d in range(n_total_docs)]
        rng.shuffle(docs)
        rated = {doc: rng.randint(0, 3) for doc in docs[: n_total_docs // 2]}
        qrels[qid] = rated
        # Run returns top_k docs from the same pool, with descending scores.
        ranked = list(docs)
        rng.shuffle(ranked)
        scored_docs = {doc: 1.0 / (i + 1) for i, doc in enumerate(ranked[:top_k])}
        run[qid] = scored_docs
    return qrels, run


def test_score_completes_under_100ms_per_query_at_50q_top10():
    """Mean wall-clock per query < 100ms (spec §FR-3 SHOULD)."""
    qrels, run = _build_fixture(n_queries=50, top_k=10)
    metrics = {"ndcg@10", "map", "mrr"}

    # Warm-up: discard first call's timing — the ir_measures transitive
    # backend may JIT-compile its metric implementations on first invocation.
    score(qrels, run, metrics)

    # Timed loop: 5 iterations.
    iterations = 5
    n_queries = len(qrels)
    started = time.perf_counter_ns()
    for _ in range(iterations):
        score(qrels, run, metrics)
    elapsed_ns = time.perf_counter_ns() - started

    total_query_evaluations = iterations * n_queries
    mean_per_query_ms = (elapsed_ns / total_query_evaluations) / 1e6

    # The spec budget is <100ms/query — assert with some headroom.
    assert mean_per_query_ms < 100.0, (
        f"scoring took {mean_per_query_ms:.2f}ms per query; spec §FR-3 SHOULD: <100ms"
    )
