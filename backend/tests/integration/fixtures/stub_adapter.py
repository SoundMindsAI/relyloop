# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Stub adapter used by infra_optuna_eval integration tests.

A minimal ``SearchAdapter`` implementation that returns deterministic
``search_batch`` responses from the ``HANDBUILT_HITS`` fixture, records
the calls it received (used to verify AC-7 — "exactly one _msearch, zero
_search"), and supports the ``aclose()`` lifecycle.

Tests install this via ``monkeypatch.setattr(
    "backend.workers.trials.build_adapter",
    lambda cluster: StubAdapter(...),
)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.adapters.protocol import (
    EngineType,
    ExplainTree,
    HealthStatus,
    NativeQuery,
    QueryTemplate,
    Schema,
    ScoredHit,
    TargetInfo,
)


@dataclass
class StubAdapter:
    """Test double that satisfies the ``SearchAdapter`` Protocol.

    Construct with ``search_batch_response`` keyed by the test's real
    ``Query.id`` UUIDs; the stub returns the matching hits when called.

    Records ``search_batch`` and ``search`` call counts so tests can
    assert AC-7 (exactly one ``_msearch``, zero ``_search``).
    """

    engine_type: EngineType = "elasticsearch"
    search_batch_response: dict[str, list[ScoredHit]] = field(default_factory=dict)
    raise_on_search: BaseException | None = None
    search_batch_calls: list[dict[str, Any]] = field(default_factory=list)
    aclose_called: bool = False

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        return HealthStatus(
            status="green",
            version="9.4.0-stub",
            checked_at=datetime.now(UTC).isoformat(),
        )

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[TargetInfo]:
        # `target_filter` accepted to match Protocol signature (feat_cluster_target_filter
        # FR-3); stub returns hardcoded data so the kwarg is intentionally unused.
        del target_filter  # silence unused-arg lint
        return [TargetInfo(name="stub-index", doc_count=100)]

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        return Schema(name=target, fields=[])

    def list_query_parsers(self) -> list[str]:
        return ["match"]

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, Any],
        query_text: str,
    ) -> NativeQuery:
        # Render is irrelevant for the stub — return a synthetic body that the
        # caller can immediately re-key. The worker re-sets query_id to the
        # real Query.id before calling search_batch (per trials.py step J).
        return NativeQuery(query_id="_pre_rekey_", body={"query": {"match_all": {}}})

    async def search_batch(
        self,
        target: str,
        queries: Sequence[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        self.search_batch_calls.append(
            {
                "target": target,
                "n_queries": len(queries),
                "top_k": top_k,
                "timeout": timeout,
            }
        )
        if self.raise_on_search is not None:
            raise self.raise_on_search
        # Return only the hits for the query_ids the worker actually passed in.
        return {q.query_id: self.search_batch_response.get(q.query_id, []) for q in queries}

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        return ExplainTree(doc_id=doc_id, matched=False, value=0.0, description="stub")

    async def aclose(self) -> None:
        self.aclose_called = True
