# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``classify_rung`` (feat_ubi_judgments Story 2.2 / FR-7)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.adapters.errors import TargetNotFoundError
from backend.app.adapters.protocol import (
    Document,
    DocumentPage,
    EngineType,
    ExplainTree,
    HealthStatus,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    ScanPage,
    Schema,
    ScoredHit,
    TargetInfo,
)
from backend.app.services.ubi_readiness import (
    CACHE_TTL_SECONDS,
    UbiReadiness,
    classify_rung,
    count_ubi_events_in_window,
)

# ----------------------------------------------------------------------------
# Stub adapter (mirrors test_ubi_reader._StubUbiAdapter, scoped here)
# ----------------------------------------------------------------------------


@dataclass
class _StubAdapter:
    engine_type: EngineType = "opensearch"
    schema_raises: BaseException | None = None
    canned_event_hits: list[ScoredHit] = field(default_factory=list)
    search_batch_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        if self.schema_raises is not None:
            raise self.schema_raises
        return Schema(name=target, fields=[])

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
                "query_id": queries[0].query_id,
                "body": queries[0].body,
                "top_k": top_k,
            }
        )
        return {queries[0].query_id: list(self.canned_event_hits)}

    # Protocol-only stubs.
    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        return HealthStatus(status="green", version="x", checked_at="2026-05-29T00:00:00Z")

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[TargetInfo]:
        return []

    def list_query_parsers(self) -> list[str]:
        return ["match"]

    def render(
        self, template: QueryTemplate, params: dict[str, ParamValue], query_text: str
    ) -> NativeQuery:
        return NativeQuery(query_id=template.name, body={})

    async def explain(
        self, target: str, query: NativeQuery, doc_id: str, *, request_id: str | None = None
    ) -> ExplainTree:
        return ExplainTree(doc_id=doc_id, matched=False, value=0.0, description="stub")

    async def get_document(
        self, target: str, doc_id: str, *, request_id: str | None = None
    ) -> Document | None:
        return None

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[object] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        return DocumentPage(hits=[], total=0)

    async def scan_all(
        self,
        target: str,
        body: dict[str, Any],
        *,
        page_size: int,
        cursor: object | None = None,
        fl: list[str] | None = None,
        request_id: str | None = None,
    ) -> ScanPage:
        # chore_ubi_reader_search_after_pagination Story 1.1 — added to the
        # Protocol. The readiness probe doesn't iterate (only get_schema +
        # count_ubi_events_in_window via search_batch), so this stub stays
        # an empty terminal page.
        return ScanPage(hits=[], cursor=None)

    async def close_scan(
        self,
        cursor: object | None,
        *,
        request_id: str | None = None,
    ) -> None:
        return None


def _hits(n: int) -> list[ScoredHit]:
    return [ScoredHit(doc_id=f"evt-{i}", score=0.0) for i in range(n)]


@dataclass
class _FakeRedis:
    store: dict[str, str] = field(default_factory=dict)
    get_calls: list[str] = field(default_factory=list)
    set_calls: list[tuple[str, str, int]] = field(default_factory=list)

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex or 0))
        self.store[key] = value


# ----------------------------------------------------------------------------
# Rung classification
# ----------------------------------------------------------------------------


async def test_classify_rung_0_when_ubi_queries_missing() -> None:
    adapter = _StubAdapter(schema_raises=TargetNotFoundError("ubi_queries"))
    redis = _FakeRedis()
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=[],
        target="products",
        redis=redis,  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_0"
    assert snapshot.covered_pairs_pct is None
    assert snapshot.head_covered is None
    # Cached.
    assert len(redis.set_calls) == 1
    key, payload, ttl = redis.set_calls[0]
    assert key == "ubi-readiness:c1:qs1:products"
    assert ttl == CACHE_TTL_SECONDS
    assert json.loads(payload)["rung"] == "rung_0"


async def test_classify_rung_1_when_below_threshold() -> None:
    adapter = _StubAdapter(canned_event_hits=_hits(50))  # default threshold 100
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=["q1", "q2"],
        target="products",
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_1"


async def test_classify_rung_2_at_threshold() -> None:
    adapter = _StubAdapter(canned_event_hits=_hits(200))  # >= 100, < 500
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=[],
        target="products",
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_2"


async def test_classify_rung_3_at_5x_threshold() -> None:
    adapter = _StubAdapter(canned_event_hits=_hits(500))  # == 5x
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=[],
        target="products",
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_3"


async def test_classify_rung_cache_hit_skips_probe() -> None:
    cached = UbiReadiness(
        rung="rung_3",
        covered_pairs_pct=None,
        head_covered=None,
        checked_at=datetime.now(UTC),
    ).to_cache_payload()
    redis = _FakeRedis(store={"ubi-readiness:c1:qs1:products": cached})
    adapter = _StubAdapter()
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=[],
        target="products",
        redis=redis,  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_3"
    # The adapter was not asked anything.
    assert adapter.search_batch_calls == []


async def test_classify_rung_cache_decode_failure_falls_through_to_probe() -> None:
    """Bad cache payload triggers fresh probe + write — no crash."""
    redis = _FakeRedis(store={"ubi-readiness:c1:qs1:products": "not-json"})
    adapter = _StubAdapter(canned_event_hits=_hits(200))
    snapshot = await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=[],
        target="products",
        redis=redis,  # type: ignore[arg-type]
    )
    assert snapshot.rung == "rung_2"
    # Fresh probe happened.
    assert len(adapter.search_batch_calls) == 1


# ----------------------------------------------------------------------------
# count_ubi_events_in_window (dispatcher's U-D2 helper)
# ----------------------------------------------------------------------------


async def test_count_ubi_events_returns_min_of_actual_and_cap() -> None:
    adapter = _StubAdapter(canned_event_hits=_hits(50))
    count = await count_ubi_events_in_window(
        adapter,
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        until=datetime(2026, 5, 29, tzinfo=UTC),
        cap=100,
    )
    assert count == 50

    adapter_full = _StubAdapter(canned_event_hits=_hits(100))
    count_at_cap = await count_ubi_events_in_window(
        adapter_full,
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        until=datetime(2026, 5, 29, tzinfo=UTC),
        cap=100,
    )
    assert count_at_cap == 100


async def test_count_ubi_events_builds_expected_filter() -> None:
    adapter = _StubAdapter(canned_event_hits=_hits(10))
    since = datetime(2026, 5, 1, tzinfo=UTC)
    until = datetime(2026, 5, 29, tzinfo=UTC)
    await count_ubi_events_in_window(
        adapter,
        target="articles",
        since=since,
        until=until,
        cap=100,
    )
    call = adapter.search_batch_calls[0]
    assert call["target"] == "ubi_events"
    assert call["top_k"] == 100
    # ES/OpenSearch path: bool/filter DSL with the half-open timestamp range.
    filters = call["body"]["query"]["bool"]["filter"]
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in filters
    assert {"term": {"application": "articles"}} in filters


async def test_count_ubi_events_builds_solr_native_body() -> None:
    """Regression: the count probe used to hand ES DSL to the SolrAdapter,
    which rejects it (InvalidQueryDSLError). On Solr it must emit Solr params."""
    adapter = _StubAdapter(engine_type="solr", canned_event_hits=_hits(10))
    since = datetime(2026, 5, 1, tzinfo=UTC)
    until = datetime(2026, 5, 29, tzinfo=UTC)
    count = await count_ubi_events_in_window(
        adapter,
        target="articles",
        since=since,
        until=until,
        cap=100,
    )
    assert count == 10  # result handling unchanged across engines

    body = adapter.search_batch_calls[0]["body"]
    assert {"query", "_source", "size", "track_total_hits"}.isdisjoint(body.keys()), body
    assert body["q"] == "*:*"
    assert body["rows"] == "100"
    assert body["fl"] == "id"
    assert "timestamp:[2026-05-01T00:00:00Z TO 2026-05-29T00:00:00Z}" in body["fq"]
    assert 'application:"articles"' in body["fq"]


async def test_count_ubi_events_solr_includes_query_id_clause() -> None:
    """classify_rung passes the query-set ids through to the count probe;
    on Solr they become a ``{!terms}`` query_id fq clause (NOT a boolean OR —
    that would exceed maxBooleanClauses on large query sets)."""
    adapter = _StubAdapter(engine_type="solr", canned_event_hits=_hits(50))
    await classify_rung(
        adapter=adapter,
        cluster_id="c1",
        query_set_id="qs1",
        query_set_query_ids=["q1", "q2"],
        target="products",
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    body = adapter.search_batch_calls[0]["body"]
    assert "{!terms f=query_id}q1,q2" in body["fq"]


# ----------------------------------------------------------------------------
# UbiReadiness dataclass round-trip
# ----------------------------------------------------------------------------


def test_ubi_readiness_cache_payload_round_trip() -> None:
    original = UbiReadiness(
        rung="rung_2",
        covered_pairs_pct=0.6,
        head_covered=True,
        checked_at=datetime(2026, 5, 29, 12, 0, tzinfo=UTC),
    )
    payload = original.to_cache_payload()
    rebuilt = UbiReadiness.from_cache_payload(payload)
    assert rebuilt == original
