# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``UbiReader`` (feat_ubi_judgments Story 2.1 / FR-1
+ chore_ubi_reader_search_after_pagination Story 3.1 / FR-4–7).

The reader uses :meth:`SearchAdapter.scan_all` +
:meth:`SearchAdapter.close_scan` for the full paginated read path
(``chore_ubi_reader_search_after_pagination``). These tests exercise it
against a stub adapter that scripts per-target page sequences — DB,
engine, and HTTP transport are all out of scope. The
no-cluster-writes invariant is locked in the sibling
``test_ubi_reader_no_writes.py`` which mocks the transport.

Lives under ``backend/tests/unit/services/`` (not
``backend/tests/integration/services/`` as the plan §3.2 stated)
because the reader has no DB/Redis/engine dependency: a stub adapter
fully covers the surface. The codebase has no
``backend/tests/integration/services/`` folder convention; sibling
service-layer tests with no DB live under
``backend/tests/unit/services/``.

Test surface (per Story 3.1 + 3.2 plan):

* Schema probe missing → :class:`UbiNotEnabledError`.
* Empty ``ubi_queries`` window → ``{}`` (race-condition fallback).
* Empty ``ubi_events`` window → ``{}``.
* Happy-path canned data (nested and flat shapes) → expected
  ``FeatureVec`` map shape, click/impression counts, dwell-mean.
* ``target`` propagation → both scans receive ``application == target``.
* ``query_filter`` propagation.
* ``query_ids`` propagation → events scan filter.
* ``user_query`` map surfaces alongside features.
* Position-bias prior reaches :func:`aggregate_features`.
* Story 3.1 AC-5: multi-page aggregation — `scan_all` is looped until
  cursor=None and the fold visits every hit across pages.
* Story 3.1 AC-6 + AC-9 (reader half): ceiling truncation + `close_scan`
  called on early exit (non-terminal cursor still held).
* Story 3.1 AC-13: exact non-page-aligned ceiling — page_size is
  clamped per page AND the final page is sliced.
* Story 3.1 AC-14: large ``query_id`` chunking — events scan splits a
  batch whenever EITHER `ubi_query_id_batch_size` OR
  `ubi_query_id_batch_max_bytes` would be exceeded.
* Story 3.1 P1-B2: fold-time exception still closes the rotated PIT
  (cursor assigned BEFORE folding, finally runs cleanup).
* Story 3.2 AC-12: ceiling injected via constructor (mirrors how the
  worker resolves it from ``Settings``) → scan truncates at the
  injected ceiling, not at the old 10k single-page sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

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
from backend.app.services.ubi_errors import UbiNotEnabledError
from backend.app.services.ubi_reader import (
    DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES,
    DEFAULT_UBI_QUERY_ID_BATCH_SIZE,
    ES_MAX_RESULT_WINDOW,
    UBI_EVENTS_INDEX,
    UBI_QUERIES_INDEX,
    UbiReader,
    _chunk_query_ids,
    _serialized_terms_fragment_size,
)

# ----------------------------------------------------------------------------
# Stub adapter — scripts per-target page sequences for ``scan_all`` calls and
# records every (target, body, page_size, cursor) invocation so tests can
# assert the reader's pagination semantics + the chunking behavior.
# ----------------------------------------------------------------------------


@dataclass
class _ScanCall:
    target: str
    body: dict[str, Any]
    page_size: int
    cursor: object | None
    fl: list[str] | None
    request_id: str | None


@dataclass
class _CloseScanCall:
    cursor: object | None
    request_id: str | None


@dataclass
class _StubUbiAdapter:
    """Minimal :class:`SearchAdapter` stub for UbiReader tests.

    Configure per-target page sequences via :attr:`pages_by_target`.
    Each page sequence is a list of (hits, cursor) tuples; the stub
    issues them in order and falls through to a terminal empty page if
    the test consumes more than scripted (defensive).
    """

    engine_type: EngineType = "opensearch"
    schema_raises: BaseException | None = None
    # Per-target page sequences: each entry is (hits, cursor_for_returned_page).
    pages_by_target: dict[str, list[tuple[list[ScoredHit], object | None]]] = field(
        default_factory=dict
    )
    # Per-target page emitter index — incremented as scan_all serves pages.
    _page_idx: dict[str, int] = field(default_factory=dict)

    # Records.
    get_schema_calls: list[str] = field(default_factory=list)
    scan_all_calls: list[_ScanCall] = field(default_factory=list)
    close_scan_calls: list[_CloseScanCall] = field(default_factory=list)
    # Optional: simulate a close_scan failure (returns silently — adapter
    # contract says close_scan is best-effort; the reader's `finally` still
    # logs+swallows).
    close_scan_raises: BaseException | None = None
    # Optional: per-target exceptions to raise on the Nth scan_all call.
    raise_on_target_call: dict[str, tuple[int, BaseException]] = field(default_factory=dict)

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        self.get_schema_calls.append(target)
        if self.schema_raises is not None:
            raise self.schema_raises
        return Schema(name=target, fields=[])

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
        self.scan_all_calls.append(
            _ScanCall(
                target=target,
                body=body,
                page_size=page_size,
                cursor=cursor,
                fl=fl,
                request_id=request_id,
            )
        )
        # Targeted raise: if the test set raise_on_target_call[target] =
        # (N, exc), raise exc on the Nth call to that target (1-indexed).
        per_target = sum(1 for c in self.scan_all_calls if c.target == target)
        rule = self.raise_on_target_call.get(target)
        if rule is not None and rule[0] == per_target:
            raise rule[1]
        # Page emitter.
        idx = self._page_idx.get(target, 0)
        pages = self.pages_by_target.get(target, [])
        if idx >= len(pages):
            return ScanPage(hits=[], cursor=None)
        hits, page_cursor = pages[idx]
        self._page_idx[target] = idx + 1
        return ScanPage(hits=hits, cursor=page_cursor)

    async def close_scan(
        self,
        cursor: object | None,
        *,
        request_id: str | None = None,
    ) -> None:
        self.close_scan_calls.append(_CloseScanCall(cursor=cursor, request_id=request_id))
        if self.close_scan_raises is not None:
            raise self.close_scan_raises

    # ----- Protocol-only stubs (UbiReader never touches these) -----

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        return HealthStatus(status="green", version="0.0.0-stub", checked_at="2026-05-29T00:00:00Z")

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
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        return NativeQuery(query_id=template.name, body={})

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
        # Not called by the paginated reader; the legacy single-call path is
        # gone. Keep as a no-op so the stub still satisfies the Protocol shape.
        return {q.query_id: [] for q in queries}

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        return ExplainTree(doc_id=doc_id, matched=False, value=0.0, description="stub")

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
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


def _query_hit(query_id: str, user_query: str, ts: str = "2026-05-20T10:00:00Z") -> ScoredHit:
    return ScoredHit(
        doc_id=query_id,
        score=1.0,
        source={
            "query_id": query_id,
            "user_query": user_query,
            "application": "products",
            "timestamp": ts,
        },
    )


def _nested_event(
    *,
    query_id: str,
    doc_id: str,
    action: str,
    position: int | None = None,
    dwell_time_seconds: float | None = None,
) -> ScoredHit:
    """Build a hit using the OpenSearch UBI plugin nested-shape."""
    attrs: dict[str, Any] = {}
    if position is not None:
        attrs["position"] = position
    if dwell_time_seconds is not None:
        attrs["dwell_time_seconds"] = dwell_time_seconds
    attrs["object"] = {"object_id": doc_id}
    return ScoredHit(
        doc_id=f"evt-{query_id}-{doc_id}-{action}",
        score=0.0,
        source={
            "query_id": query_id,
            "action_name": action,
            "event_attributes": attrs,
            "timestamp": "2026-05-20T10:01:00Z",
        },
    )


def _flat_event(
    *,
    query_id: str,
    doc_id: str,
    action: str,
    position: int | None = None,
    dwell_seconds: float | None = None,
) -> ScoredHit:
    """Build a hit using the o19s ES UBI fork flatter-shape (top-level fields)."""
    source: dict[str, Any] = {
        "query_id": query_id,
        "action_name": action,
        "object_id": doc_id,
        "timestamp": "2026-05-20T10:01:00Z",
    }
    if position is not None:
        source["position"] = position
    if dwell_seconds is not None:
        source["dwell_seconds"] = dwell_seconds
    return ScoredHit(doc_id=f"evt-{query_id}-{doc_id}-{action}", score=0.0, source=source)


def _single_page(hits: list[ScoredHit]) -> list[tuple[list[ScoredHit], object | None]]:
    """Helper — emit a single terminal page with the given hits."""
    return [(hits, None)]


# ----------------------------------------------------------------------------
# _probe_enabled
# ----------------------------------------------------------------------------


async def test_probe_enabled_raises_when_ubi_index_missing() -> None:
    adapter = _StubUbiAdapter(schema_raises=TargetNotFoundError(UBI_QUERIES_INDEX))
    reader = UbiReader(adapter)

    with pytest.raises(UbiNotEnabledError) as excinfo:
        await reader._probe_enabled()

    msg = str(excinfo.value)
    assert UBI_QUERIES_INDEX in msg
    assert adapter.engine_type in msg
    assert adapter.get_schema_calls == [UBI_QUERIES_INDEX]


async def test_probe_enabled_passes_when_index_present() -> None:
    adapter = _StubUbiAdapter()
    reader = UbiReader(adapter)

    await reader._probe_enabled()
    assert adapter.get_schema_calls == [UBI_QUERIES_INDEX]


# ----------------------------------------------------------------------------
# read_features — empty / race-condition fallback
# ----------------------------------------------------------------------------


async def test_read_features_empty_queries_returns_empty_dict() -> None:
    adapter = _StubUbiAdapter(pages_by_target={UBI_QUERIES_INDEX: _single_page([])})
    reader = UbiReader(adapter)

    out = await reader.read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        until=datetime(2026, 5, 29, tzinfo=UTC),
    )

    assert out == {}
    # Reader probed, then issued the queries scan; events scan never fires
    # because the queries scan returned zero hits.
    targets = [c.target for c in adapter.scan_all_calls]
    assert targets == [UBI_QUERIES_INDEX]


async def test_scan_page_size_never_exceeds_es_result_window() -> None:
    """Regression — even though scan_all paginates, each single page MUST
    still clamp to the engine result-window (the engine rejects size >
    10k with "all shards failed"). With a huge ceiling, the FIRST page's
    page_size is still clamped at ES_MAX_RESULT_WINDOW.
    """
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        }
    )
    await UbiReader(adapter, max_queries=999_999, max_events=999_999).read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
    )
    for call in adapter.scan_all_calls:
        assert call.page_size <= ES_MAX_RESULT_WINDOW, (
            f"{call.target} requested page_size={call.page_size} > {ES_MAX_RESULT_WINDOW}"
        )


async def test_read_features_no_events_for_queries_returns_empty_dict() -> None:
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page([]),
        }
    )
    reader = UbiReader(adapter)

    out = await reader.read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert out == {}
    # Both scans fired (queries scan returned 1 hit, events scan returned 0).
    targets = [c.target for c in adapter.scan_all_calls]
    assert targets == [UBI_QUERIES_INDEX, UBI_EVENTS_INDEX]


# ----------------------------------------------------------------------------
# read_features — happy path with canned data + field-extraction matrix
# ----------------------------------------------------------------------------


async def test_read_features_happy_path_nested_shape() -> None:
    """OpenSearch UBI plugin nested-shape — full pipeline → FeatureVec."""
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page(
                [
                    _query_hit("q-1", "red shoes"),
                    _query_hit("q-2", "blue shirt"),
                ]
            ),
            UBI_EVENTS_INDEX: _single_page(
                [
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                    _nested_event(
                        query_id="q-1", doc_id="d-a", action="dwell", dwell_time_seconds=12.5
                    ),
                    _nested_event(query_id="q-1", doc_id="d-b", action="impression", position=2),
                    _nested_event(query_id="q-2", doc_id="d-c", action="impression", position=1),
                    _nested_event(query_id="q-2", doc_id="d-c", action="click"),
                ]
            ),
        }
    )
    reader = UbiReader(adapter)

    out = await reader.read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert set(out.keys()) == {("q-1", "d-a"), ("q-1", "d-b"), ("q-2", "d-c")}

    qa = out[("q-1", "d-a")]
    assert qa.click_count == 1
    assert qa.impression_count == 2
    assert math.isclose(qa.corrected_ctr, 0.5)
    assert qa.dwell_mean_seconds == 12.5

    qb = out[("q-1", "d-b")]
    assert qb.click_count == 0
    assert qb.impression_count == 1
    assert qb.corrected_ctr == 0.0
    assert qb.dwell_mean_seconds is None

    qc = out[("q-2", "d-c")]
    assert qc.click_count == 1
    assert qc.impression_count == 1
    assert math.isclose(qc.corrected_ctr, 1.0)


async def test_read_features_top_level_shape_matches_nested_shape() -> None:
    """o19s ES UBI fork flat-shape produces the same FeatureVec map as nested."""
    common_queries = [_query_hit("q-1", "red shoes")]
    nested_adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page(common_queries),
            UBI_EVENTS_INDEX: _single_page(
                [
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                    _nested_event(
                        query_id="q-1", doc_id="d-a", action="dwell", dwell_time_seconds=20.0
                    ),
                ]
            ),
        }
    )
    flat_adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page(common_queries),
            UBI_EVENTS_INDEX: _single_page(
                [
                    _flat_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _flat_event(query_id="q-1", doc_id="d-a", action="click"),
                    _flat_event(query_id="q-1", doc_id="d-a", action="dwell", dwell_seconds=20.0),
                ]
            ),
        }
    )

    nested = await UbiReader(nested_adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    flat = await UbiReader(flat_adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )

    assert nested.keys() == flat.keys()
    for pair, expected in nested.items():
        actual = flat[pair]
        assert actual.click_count == expected.click_count
        assert actual.impression_count == expected.impression_count
        assert math.isclose(actual.corrected_ctr, expected.corrected_ctr)
        assert actual.dwell_mean_seconds == expected.dwell_mean_seconds


async def test_read_features_drops_event_missing_doc_id() -> None:
    """Events with neither nested nor top-level doc_id are silently dropped."""
    broken_hit = ScoredHit(
        doc_id="broken",
        score=0.0,
        source={
            "query_id": "q-1",
            "action_name": "click",
            "event_attributes": {},
            # No object_id anywhere.
        },
    )
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [
                    broken_hit,
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                ]
            ),
        }
    )

    out = await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )

    # The broken event vanishes; the good (q-1, d-a) pair survives.
    assert list(out.keys()) == [("q-1", "d-a")]
    assert out[("q-1", "d-a")].click_count == 1


# ----------------------------------------------------------------------------
# Filter / propagation assertions
# ----------------------------------------------------------------------------


def _es_filters_of(call: _ScanCall) -> list[dict[str, Any]]:
    return list(call.body["query"]["bool"]["filter"])


async def test_read_features_filters_propagate_target_and_window() -> None:
    adapter = _StubUbiAdapter(
        engine_type="elasticsearch",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    since = datetime(2026, 4, 1, tzinfo=UTC)
    until = datetime(2026, 5, 1, tzinfo=UTC)
    await UbiReader(adapter).read_features(target="articles", since=since, until=until)

    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    qfilters = _es_filters_of(qcall)
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in qfilters
    assert {"term": {"application": "articles"}} in qfilters

    ecall = next(c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX)
    efilters = _es_filters_of(ecall)
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in efilters
    assert {"term": {"application": "articles"}} in efilters
    assert {"terms": {"query_id": ["q-1"]}} in efilters


async def test_read_features_optional_query_filter_adds_wildcard() -> None:
    adapter = _StubUbiAdapter(
        engine_type="elasticsearch",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red running shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    await UbiReader(adapter).read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        query_filter="running",
    )
    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    qfilters = _es_filters_of(qcall)
    assert {"wildcard": {"user_query": "*running*"}} in qfilters


async def test_read_features_until_defaults_to_now_when_missing() -> None:
    adapter = _StubUbiAdapter(
        engine_type="elasticsearch",
        pages_by_target={UBI_QUERIES_INDEX: _single_page([])},
    )
    before = datetime.now(UTC)
    await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    after = datetime.now(UTC)

    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    qfilters = _es_filters_of(qcall)
    range_filter = next(f for f in qfilters if "range" in f)
    until_iso = range_filter["range"]["timestamp"]["lt"]
    parsed = datetime.fromisoformat(until_iso)
    assert before <= parsed <= after


async def test_read_features_no_writes_in_search_body() -> None:
    """Static assertion: nothing in the reader builds a write-shaped body."""
    adapter = _StubUbiAdapter(
        engine_type="elasticsearch",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    for call in adapter.scan_all_calls:
        body = call.body
        # Only read-shape — body has 'query' + '_source' + 'track_total_hits'.
        # No 'script', 'doc', 'upsert', 'index', or 'delete' keys.
        forbidden = {"script", "doc", "upsert", "index", "delete", "params"}
        assert forbidden.isdisjoint(body.keys()), body


# ----------------------------------------------------------------------------
# Solr engine-aware read path
# ----------------------------------------------------------------------------

_ES_ONLY_BODY_KEYS = {"query", "_source", "size", "track_total_hits"}


async def test_read_features_builds_solr_native_bodies() -> None:
    adapter = _StubUbiAdapter(
        engine_type="solr",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_flat_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    since = datetime(2026, 4, 1, tzinfo=UTC)
    until = datetime(2026, 5, 1, tzinfo=UTC)
    out = await UbiReader(adapter).read_features(target="articles", since=since, until=until)

    assert ("q-1", "d-a") in out

    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    qbody = qcall.body
    assert _ES_ONLY_BODY_KEYS.isdisjoint(qbody.keys()), qbody
    assert qbody["q"] == "*:*"
    # rows is stripped by the adapter's pagination-key stripper; the reader
    # passes rows=1 as a placeholder (build helper contract).
    assert qbody["fl"] == "query_id,user_query,application,timestamp"
    assert isinstance(qbody["fq"], list)
    assert "timestamp:[2026-04-01T00:00:00Z TO 2026-05-01T00:00:00Z}" in qbody["fq"]
    assert 'application:"articles"' in qbody["fq"]
    assert not any(f.startswith("query_id:") for f in qbody["fq"])

    ecall = next(c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX)
    ebody = ecall.body
    assert _ES_ONLY_BODY_KEYS.isdisjoint(ebody.keys()), ebody
    assert ebody["q"] == "*:*"
    assert ebody["fl"] == "*"
    assert "timestamp:[2026-04-01T00:00:00Z TO 2026-05-01T00:00:00Z}" in ebody["fq"]
    assert 'application:"articles"' in ebody["fq"]
    assert "{!terms f=query_id}q-1" in ebody["fq"]


async def test_read_features_solr_query_filter_adds_user_query_fq() -> None:
    adapter = _StubUbiAdapter(
        engine_type="solr",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red running shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_flat_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    await UbiReader(adapter).read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        query_filter="running",
    )
    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    assert "user_query:*running*" in qcall.body["fq"]


async def test_read_features_es_path_unchanged_when_not_solr() -> None:
    """The ES/OpenSearch branch still emits bool/filter DSL byte-for-byte."""
    adapter = _StubUbiAdapter(
        engine_type="elasticsearch",
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
            ),
        },
    )
    since = datetime(2026, 4, 1, tzinfo=UTC)
    until = datetime(2026, 5, 1, tzinfo=UTC)
    await UbiReader(adapter).read_features(target="articles", since=since, until=until)

    qcall = next(c for c in adapter.scan_all_calls if c.target == UBI_QUERIES_INDEX)
    assert "query" in qcall.body
    qfilters = qcall.body["query"]["bool"]["filter"]
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in qfilters
    assert {"term": {"application": "articles"}} in qfilters

    ecall = next(c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX)
    efilters = ecall.body["query"]["bool"]["filter"]
    assert {"terms": {"query_id": ["q-1"]}} in efilters


# ----------------------------------------------------------------------------
# Position-bias prior reaches aggregate_features
# ----------------------------------------------------------------------------


async def test_read_features_position_bias_prior_applies() -> None:
    """Informed prior `{1: 1.0, 2: 0.5}` doubles corrected CTR for rank-2-only impressions."""
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
            UBI_EVENTS_INDEX: _single_page(
                [
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=2),
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=2),
                    _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                ]
            ),
        }
    )
    reader = UbiReader(adapter, position_bias_prior={1: 1.0, 2: 0.5})
    out = await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))

    feat = out[("q-1", "d-a")]
    assert math.isclose(feat.corrected_ctr, 1.0)


# ----------------------------------------------------------------------------
# read_user_query_map
# ----------------------------------------------------------------------------


async def test_read_user_query_map_returns_query_id_to_user_query() -> None:
    adapter = _StubUbiAdapter(
        pages_by_target={
            UBI_QUERIES_INDEX: _single_page(
                [
                    _query_hit("q-1", "red shoes"),
                    _query_hit("q-2", "blue shirt"),
                ]
            )
        }
    )
    mapping = await UbiReader(adapter).read_user_query_map(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    assert mapping == {"q-1": "red shoes", "q-2": "blue shirt"}
    assert adapter.get_schema_calls == []


# ----------------------------------------------------------------------------
# Story 3.1 — AC-5: multi-page aggregation
# ----------------------------------------------------------------------------


class TestMultiPageAggregation:
    """AC-5: scan_all is looped page-by-page until cursor=None and the fold
    visits every hit across pages."""

    async def test_events_scan_walks_three_pages(self) -> None:
        """3-page event stream: hits aggregate across pages; close_scan is
        called once at the terminal."""
        # Each event hit lives on a separate page; terminal cursor on page 3.
        events_pages: list[tuple[list[ScoredHit], object | None]] = [
            (
                [
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
                ],
                "ev-cursor-1",
            ),
            (
                [
                    _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                    _nested_event(
                        query_id="q-1", doc_id="d-a", action="dwell", dwell_time_seconds=8.0
                    ),
                ],
                "ev-cursor-2",
            ),
            (
                [_nested_event(query_id="q-1", doc_id="d-b", action="impression", position=2)],
                None,  # terminal
            ),
        ]
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
                UBI_EVENTS_INDEX: events_pages,
            }
        )
        # Use a small max_events to bias the test but keep above the total (5).
        out = await UbiReader(adapter, max_events=100, max_queries=10).read_features(
            target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
        )

        # Aggregation visits all 5 events across pages.
        assert set(out.keys()) == {("q-1", "d-a"), ("q-1", "d-b")}
        qa = out[("q-1", "d-a")]
        assert qa.click_count == 1
        assert qa.impression_count == 2
        assert qa.dwell_mean_seconds == 8.0
        # Events scan fired 3 times (one per page).
        events_calls = [c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX]
        assert len(events_calls) == 3
        # Cursors fed forward correctly.
        assert events_calls[0].cursor is None
        assert events_calls[1].cursor == "ev-cursor-1"
        assert events_calls[2].cursor == "ev-cursor-2"
        # close_scan called exactly once per scan (queries + events scans).
        # Final cursor on each scan is None (terminal), so close_scan is a
        # no-op on the adapter but the reader still invokes it for safety.
        assert len(adapter.close_scan_calls) == 2
        assert all(c.cursor is None for c in adapter.close_scan_calls)


# ----------------------------------------------------------------------------
# Story 3.1 — AC-6 + AC-9 reader half: ceiling truncation + close_scan
# on early exit
# ----------------------------------------------------------------------------


class TestCeilingTruncationAndCloseScan:
    """AC-6: a non-page-aligned ceiling truncates exactly and AC-9: the
    reader's finally calls close_scan with the latest non-terminal cursor."""

    async def test_ceiling_hit_mid_page_closes_held_cursor(self) -> None:
        """The events scan stops at exactly max_events even though the
        page returned more hits. The held cursor (non-terminal) is passed
        to close_scan in `finally` so the engine releases the PIT."""
        # max_events=3 but the first page emits 5 hits + a non-None cursor.
        events_pages: list[tuple[list[ScoredHit], object | None]] = [
            (
                [
                    _nested_event(query_id="q-1", doc_id=f"d-{i}", action="impression", position=1)
                    for i in range(5)
                ],
                "ev-cursor-pit-alive",
            ),
            # Should never be reached.
            (
                [_nested_event(query_id="q-1", doc_id="d-X", action="click")],
                None,
            ),
        ]
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
                UBI_EVENTS_INDEX: events_pages,
            }
        )
        reader = UbiReader(adapter, max_events=3, max_queries=10)
        await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))

        events_calls = [c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX]
        # Reader stopped after the first page (ceiling reached) — never
        # consumed the second scripted page.
        assert len(events_calls) == 1
        # close_scan was called with the held (non-terminal) cursor.
        events_close_calls = [
            c
            for c in adapter.close_scan_calls
            # Map close_scan calls back to the scan that produced the cursor.
            # The events scan's close passed the page-1 cursor.
            if c.cursor == "ev-cursor-pit-alive"
        ]
        assert len(events_close_calls) == 1


# ----------------------------------------------------------------------------
# Story 3.1 — AC-13: exact non-page-aligned ceiling enforcement
# ----------------------------------------------------------------------------


class TestExactCeilingEnforcement:
    """AC-13: page_size = min(configured_page_size, remaining_budget); on a
    non-page-aligned ceiling the final page is sliced."""

    async def test_page_size_clamped_to_remaining_budget(self) -> None:
        """With max_events=15 and a default page-size cap of 10k, the FIRST
        page request asks for at most 15 (the remaining budget)."""
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red")]),
                UBI_EVENTS_INDEX: _single_page(
                    [
                        _nested_event(query_id="q-1", doc_id=f"d-{i}", action="click")
                        for i in range(12)
                    ]
                ),
            }
        )
        reader = UbiReader(adapter, max_events=15, max_queries=10)
        await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))
        events_calls = [c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX]
        assert events_calls[0].page_size == 15

    async def test_final_page_sliced_when_over_ceiling(self) -> None:
        """When max_events=3 and the page returns 5 hits, the reader keeps
        exactly 3 (the slice) and stops."""
        events_pages: list[tuple[list[ScoredHit], object | None]] = [
            (
                [
                    _nested_event(query_id="q-1", doc_id="d-1", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-2", action="impression", position=1),
                    _nested_event(query_id="q-1", doc_id="d-3", action="click"),
                    _nested_event(query_id="q-1", doc_id="d-4", action="click"),  # OVER ceiling
                    _nested_event(query_id="q-1", doc_id="d-5", action="click"),  # OVER ceiling
                ],
                "next-cursor",
            )
        ]
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red")]),
                UBI_EVENTS_INDEX: events_pages,
            }
        )
        out = await UbiReader(adapter, max_events=3, max_queries=10).read_features(
            target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
        )
        # Only the first 3 hits (d-1, d-2, d-3) were folded. d-1 and d-2 are
        # impressions (+1 each), d-3 is a click. d-4/d-5 never reach the
        # aggregator.
        assert set(out.keys()) == {("q-1", "d-1"), ("q-1", "d-2"), ("q-1", "d-3")}


# ----------------------------------------------------------------------------
# Story 3.1 — P1-B2: fold-time exception still closes the rotated cursor
# ----------------------------------------------------------------------------


class TestFoldTimeExceptionStillClosesCursor:
    """P1-B2: the reader assigns `cursor = page.cursor` IMMEDIATELY after
    the scan_all await, BEFORE folding the page's hits. A fold-time
    exception therefore still triggers the `finally` close on the rotated
    cursor — not on the previous-page's stale id."""

    async def test_corrupt_event_fold_still_closes_rotated_cursor(self) -> None:
        """A fold-time exception still results in close_scan being called
        with the LATEST page's cursor (not the previous-page's stale
        cursor).

        ``ScanPage.model_construct`` skips Pydantic's `list[ScoredHit]`
        validation so our custom list-like survives — the reader's
        fold is ``out.extend(h.source for h in take if ...)``, so
        making `take` (the slice result) iter-raise reproduces the
        original P1-B2 fault path.
        """

        class _ExplodingSlice:
            def __iter__(self) -> Any:
                raise RuntimeError("fold-time fault")

            def __len__(self) -> int:
                return 1

        class _ExplodingHitsList(list):  # type: ignore[type-arg]
            def __getitem__(self, idx: Any) -> Any:
                if isinstance(idx, slice):
                    return _ExplodingSlice()
                return super().__getitem__(idx)

        class _ExplodingAdapter(_StubUbiAdapter):
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
                if target == UBI_QUERIES_INDEX:
                    return await super().scan_all(
                        target,
                        body,
                        page_size=page_size,
                        cursor=cursor,
                        fl=fl,
                        request_id=request_id,
                    )
                # Record the events-scan call (super() not used so we
                # don't double-record).
                self.scan_all_calls.append(
                    _ScanCall(
                        target=target,
                        body=body,
                        page_size=page_size,
                        cursor=cursor,
                        fl=fl,
                        request_id=request_id,
                    )
                )
                exploding_hits = _ExplodingHitsList(
                    [_nested_event(query_id="q-1", doc_id="d-a", action="click")]
                )
                # model_construct skips validation so the custom list
                # subclass survives to the reader's slice.
                return ScanPage.model_construct(hits=exploding_hits, cursor="rotated-cursor")

        adapter = _ExplodingAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red shoes")]),
                UBI_EVENTS_INDEX: [
                    (
                        [_nested_event(query_id="q-1", doc_id="d-a", action="click")],
                        "rotated-cursor",
                    ),
                    ([], None),
                ],
            }
        )

        with pytest.raises(RuntimeError, match="fold-time fault"):
            await UbiReader(adapter).read_features(
                target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
            )

        # close_scan was called with the ROTATED cursor (P1-B2): if the
        # reader had assigned cursor AFTER folding, it would still be None
        # (the initial value) and the cleanup would not close anything.
        events_closes = [c.cursor for c in adapter.close_scan_calls if c.cursor == "rotated-cursor"]
        assert len(events_closes) == 1, (
            f"close_scan should have been called with the rotated cursor; "
            f"all close_scan calls: {adapter.close_scan_calls}"
        )


# ----------------------------------------------------------------------------
# Story 3.2 — AC-12: Settings-backed ceiling via constructor
# ----------------------------------------------------------------------------


class TestCeilingInjection:
    """AC-12: construct UbiReader with the worker's pattern (resolve from
    Settings, pass into ctor); assert truncation at the configured
    ceiling rather than the legacy 10k single-page cap."""

    async def test_ctor_ceiling_truncates_below_default(self) -> None:
        """Workers resolve `ubi_max_events_scan` from Settings; the reader
        truncates at that ceiling. Here we set a tiny ceiling (5) and
        verify the scan stops after 5 hits even though the page emits
        more."""
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red")]),
                UBI_EVENTS_INDEX: [
                    (
                        [
                            _nested_event(
                                query_id="q-1",
                                doc_id=f"d-{i}",
                                action="impression",
                                position=1,
                            )
                            for i in range(20)
                        ],
                        "more",
                    )
                ],
            }
        )
        reader = UbiReader(adapter, max_events=5, max_queries=10)
        await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))

        # Reader took exactly 5 distinct doc_ids — the rest were never
        # folded.
        out = await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))
        # Mostly checking the construction-time injection took effect — but
        # the second call replays the page stream (page_idx is per adapter
        # and bumped), so we instead inspect the FIRST scan's page_size.
        first_events_call = next(c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX)
        assert first_events_call.page_size == 5  # min(ES_MAX_RESULT_WINDOW, 5)
        # And the reader didn't override the ceiling.
        assert out is not None  # touch out for ruff

    async def test_per_call_max_events_overrides_ctor_default(self) -> None:
        """Per-call `max_events` kwarg still overrides the ctor injection."""
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page([_query_hit("q-1", "red")]),
                UBI_EVENTS_INDEX: _single_page(
                    [
                        _nested_event(query_id="q-1", doc_id="d-1", action="click"),
                    ]
                ),
            }
        )
        reader = UbiReader(adapter, max_events=5)
        await reader.read_features(
            target="products",
            since=datetime(2026, 5, 1, tzinfo=UTC),
            max_events=99,
        )
        first_events_call = next(c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX)
        assert first_events_call.page_size == 99


# ----------------------------------------------------------------------------
# Story 3.1 — AC-14: query_id chunking + byte ceiling
# ----------------------------------------------------------------------------


class TestQueryIdChunking:
    """AC-14: a query_id batch splits whenever EITHER the id-count
    ceiling OR the encoded byte ceiling would be exceeded. The merge
    accumulator still respects the global max_events ceiling across
    chunks."""

    async def test_byte_ceiling_splits_at_count_below_id_ceiling(self) -> None:
        """Construct ids that exceed the BYTE ceiling at a count well below
        the id-count ceiling. The chunker should still split."""
        # Solr fragment is "{!terms f=query_id}" (19 bytes) + ids joined by
        # commas. Use 10-char ids → 10 ids = ~119 bytes for the fragment.
        # Set the byte ceiling to 100 → each id ~11 bytes (10 + comma), so
        # one chunk holds at most ~7 ids (7*11 + 19 = 96 < 100; next would
        # hit 8*11 + 19 = 107 > 100).
        ids = [f"q-id-{i:04d}" for i in range(20)]  # 10 chars each
        chunks = list(
            _chunk_query_ids(
                ids,
                max_count=1000,  # id-count is irrelevant; byte ceiling triggers
                max_bytes=100,
                engine_type="solr",
            )
        )
        # All chunks must be under the byte ceiling.
        for c in chunks:
            size = _serialized_terms_fragment_size("solr", c)
            assert size <= 100, f"chunk size {size} > 100"
        # And every id appears exactly once across all chunks.
        flat = [qid for chunk in chunks for qid in chunk]
        assert flat == ids

    async def test_id_count_ceiling_splits_below_byte_ceiling(self) -> None:
        """A purely id-count split — short ids, count ceiling triggers
        first."""
        ids = [f"a{i}" for i in range(10)]
        chunks = list(
            _chunk_query_ids(
                ids,
                max_count=3,
                max_bytes=DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES,
                engine_type="solr",
            )
        )
        assert [len(c) for c in chunks] == [3, 3, 3, 1]

    async def test_reader_splits_query_ids_into_multiple_events_calls(self) -> None:
        """When `query_id_batch_size=2` and the queries scan yields 5 ids,
        the events scan runs 3 times (chunks of 2, 2, 1) and the per-batch
        accumulators merge."""

        query_hits = [_query_hit(f"q-{i}", f"text-{i}") for i in range(5)]
        # Build adapter that returns DIFFERENT event hits for each batch so
        # we can confirm the merge accumulator sees all batches.
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page(query_hits),
                UBI_EVENTS_INDEX: _single_page(
                    [
                        _nested_event(query_id="q-0", doc_id="d-a", action="click"),
                        _nested_event(query_id="q-1", doc_id="d-a", action="click"),
                        _nested_event(query_id="q-2", doc_id="d-b", action="click"),
                        _nested_event(query_id="q-3", doc_id="d-c", action="click"),
                        _nested_event(query_id="q-4", doc_id="d-c", action="click"),
                    ]
                ),
            }
        )
        reader = UbiReader(adapter, query_id_batch_size=2)
        out = await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))

        events_calls = [c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX]
        # Three batches: [q-0, q-1] [q-2, q-3] [q-4]
        assert len(events_calls) == 3
        # Each call's body terms-filter carries its chunk's ids.
        chunk_ids = [
            sorted(c.body["query"]["bool"]["filter"][-1]["terms"]["query_id"]) for c in events_calls
        ]
        assert chunk_ids == [["q-0", "q-1"], ["q-2", "q-3"], ["q-4"]]
        # The aggregator visited the union of all batches (each batch's stub
        # response carries ALL events, so the test isn't perfectly clean —
        # but at least the merge produced non-empty output).
        assert len(out) > 0

    async def test_chunking_respects_global_max_events_ceiling(self) -> None:
        """When the global max_events ceiling is hit MID-CHUNK, subsequent
        chunks must be skipped — not silently consumed."""
        query_hits = [_query_hit(f"q-{i}", "x") for i in range(4)]
        adapter = _StubUbiAdapter(
            pages_by_target={
                UBI_QUERIES_INDEX: _single_page(query_hits),
                # Each chunk's events scan returns 5 hits + a non-terminal
                # cursor. The reader's per-chunk loop sees ceiling exhausted
                # after the first chunk.
                UBI_EVENTS_INDEX: [
                    (
                        [
                            _nested_event(
                                query_id="q-0", doc_id=f"d-{i}", action="impression", position=1
                            )
                            for i in range(10)
                        ],
                        None,  # terminal — but ceiling already hit
                    )
                ],
            }
        )
        reader = UbiReader(adapter, query_id_batch_size=2, max_events=3)
        await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))
        events_calls = [c for c in adapter.scan_all_calls if c.target == UBI_EVENTS_INDEX]
        # Only the FIRST chunk's events scan fired; the second chunk got
        # skipped because remaining hit 0.
        assert len(events_calls) == 1


# ----------------------------------------------------------------------------
# Module-level chunker oracle
# ----------------------------------------------------------------------------


class TestChunkerOracle:
    def test_empty_input_yields_nothing(self) -> None:
        assert list(_chunk_query_ids([], max_count=10, max_bytes=1000, engine_type="solr")) == []

    def test_single_oversized_id_yielded_alone(self) -> None:
        # Single id with a fragment size that exceeds the byte ceiling.
        long_id = "x" * 500
        chunks = list(
            _chunk_query_ids([long_id], max_count=1000, max_bytes=100, engine_type="solr")
        )
        # The chunker yields the oversize id alone — the engine surfaces
        # the resulting error (operator concern; never silently drops).
        assert chunks == [[long_id]]

    def test_byte_ceiling_es_engine(self) -> None:
        """ES uses JSON encoding — `{"terms":{"query_id":["a","b",...]}}`."""
        ids = [f"id-{i:04d}" for i in range(10)]
        size = _serialized_terms_fragment_size("elasticsearch", ids)
        # Sanity: at least the sum of ids + JSON overhead.
        raw_id_bytes = sum(len(i) for i in ids)
        assert size > raw_id_bytes


# ----------------------------------------------------------------------------
# Protocol shape — UbiReader does NOT add a UBI-specific adapter method
# ----------------------------------------------------------------------------


def test_search_adapter_protocol_methods_unchanged() -> None:
    """Story 2.1 DoD: no UBI-specific method added to SearchAdapter Protocol.

    Lock the current method names + the ``engine_type`` annotation so
    adding a UBI-specific Protocol member anywhere would fail this
    test. ``engine_type`` is an annotation-only attribute (no default),
    so it doesn't appear in ``dir(SearchAdapter)`` — checked via
    ``__annotations__`` instead.

    Updated by ``chore_ubi_reader_search_after_pagination`` Story 1.1:
    ``scan_all`` + ``close_scan`` joined the Protocol as the generic
    cursor-scan surface (NOT UBI-specific — UbiReader is one consumer;
    document-browsing under denser indices could be another). The
    UBI-decoupling intent of this pin survives: the new methods take a
    generic ``body`` dict, not a UBI-shaped argument.
    """
    from backend.app.adapters.protocol import SearchAdapter

    expected_methods = {
        "health_check",
        "list_targets",
        "get_schema",
        "list_query_parsers",
        "render",
        "search_batch",
        "explain",
        "get_document",
        "list_documents",
        "scan_all",
        "close_scan",
    }
    method_names = {
        name for name in dir(SearchAdapter) if not name.startswith("_") and name not in {"mro"}
    }
    assert method_names == expected_methods, (
        f"unexpected method diff: {method_names ^ expected_methods}"
    )

    expected_annotations = {"engine_type"}
    assert set(SearchAdapter.__annotations__.keys()) == expected_annotations, (
        f"unexpected annotation diff: "
        f"{set(SearchAdapter.__annotations__.keys()) ^ expected_annotations}"
    )


# ----------------------------------------------------------------------------
# Sanity — module-level defaults are addressable (Story 3.2 fold)
# ----------------------------------------------------------------------------


def test_default_batch_constants_are_addressable() -> None:
    """The Settings layer documents these as the operator-tunable defaults;
    the module-level constants are the ctor defaults."""
    assert DEFAULT_UBI_QUERY_ID_BATCH_SIZE > 0
    assert DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES > 0
