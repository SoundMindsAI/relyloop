# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``dispatch_run_query`` builds the engine-native NativeQuery.body shape.

Regression for the infra_adapter_solr review F1: a Solr cluster's run_query
must pass the operator's query_dsl straight through as Solr request params,
NOT wrapped in the ES ``{"query": ..., "size": ...}`` body (which Solr would
receive as the meaningless params ``query`` + ``size``).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.adapters.protocol import NativeQuery, ScoredHit
from backend.app.services.cluster import dispatch_run_query


class _CapturingAdapter:
    """Minimal adapter stub that records the NativeQuery it was handed."""

    def __init__(self, engine_type: str) -> None:
        self.engine_type = engine_type
        self.captured: list[NativeQuery] = []

    async def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        self.captured = list(queries)
        return {q.query_id: [] for q in queries}


@pytest.mark.parametrize("engine", ["elasticsearch", "opensearch"])
async def test_es_engines_wrap_query_dsl(engine: str) -> None:
    adapter = _CapturingAdapter(engine)
    dsl: dict[str, Any] = {"match": {"title": "laptop"}}
    await dispatch_run_query(
        adapter,  # type: ignore[arg-type]
        target="products",
        query_dsl=dsl,
        top_k=10,
        timeout_s=5.0,
    )
    body = adapter.captured[0].body
    # ES/OpenSearch: wrapped into the search-request body shape.
    assert body == {"query": dsl, "size": 10}


async def test_solr_passes_dsl_through_as_params() -> None:
    adapter = _CapturingAdapter("solr")
    dsl: dict[str, Any] = {"defType": "edismax", "q": "laptop", "qf": "title^2"}
    await dispatch_run_query(
        adapter,  # type: ignore[arg-type]
        target="products",
        query_dsl=dsl,
        top_k=10,
        timeout_s=5.0,
    )
    body = adapter.captured[0].body
    # Solr: the dsl IS the request-param dict — no {"query": ..., "size": ...}
    # wrapper. A defensive copy, not the same object.
    assert body == dsl
    assert "query" not in body
    assert "size" not in body
    assert body is not dsl
