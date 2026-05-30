# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``UbiReader`` (feat_ubi_judgments Story 2.1 / FR-1).

Exercises the reader end-to-end against a stubbed
:class:`SearchAdapter` that returns canned ``ubi_queries`` +
``ubi_events`` payloads. Mocks the adapter (not the underlying HTTP
transport) — the no-cluster-writes invariant is locked in the sibling
``test_ubi_reader_no_writes.py`` which mocks the transport.

Lives under ``backend/tests/unit/services/`` (not
``backend/tests/integration/services/`` as the plan §3.2 stated)
because the reader has no DB/Redis/engine dependency: a stub adapter
fully covers the surface. The codebase has no
``backend/tests/integration/services/`` folder convention; sibling
service-layer tests with no DB live under
``backend/tests/unit/services/`` (e.g.
``test_dispatch_run_query.py``, ``test_agent_judgments_dispatch.py``).

Test surface:

* Schema probe missing → :class:`UbiNotEnabledError`.
* Empty ``ubi_queries`` window → ``{}`` (race-condition fallback).
* Empty ``ubi_events`` window → ``{}``.
* Happy-path canned data → expected ``FeatureVec`` map shape, click/
  impression counts, dwell-mean computation.
* ``target`` propagation → both scans receive ``application == target``.
* ``query_filter`` propagation → ``ubi_queries`` scan adds a
  ``wildcard`` filter on ``user_query``.
* ``query_ids`` propagation → ``ubi_events`` scan filters on the
  step-1 query_id set.
* ``user_query`` map surfaces alongside features so Story 3.3's worker
  can apply ``mapping_strategy`` without re-scanning.
* Field-extraction robustness: nested ``event_attributes`` AND top-
  level fallback shapes both produce identical ``UbiEvent`` data.
* Position-bias prior reaches :func:`aggregate_features` — corrected
  CTR matches the informed-prior math.

These tests are pure-Python (no DB, no engine) — they exercise the
reader's API surface against a stub :class:`SearchAdapter`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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
    Schema,
    ScoredHit,
    TargetInfo,
)
from backend.app.services.ubi_errors import UbiNotEnabledError
from backend.app.services.ubi_reader import (
    ES_MAX_RESULT_WINDOW,
    UBI_EVENTS_INDEX,
    UBI_QUERIES_INDEX,
    UbiReader,
)

# ----------------------------------------------------------------------------
# Stub adapter — captures every search_batch call + lets tests script per-call
# canned ScoredHit responses keyed by the (target, query_id) pair the reader
# uses ("ubi_queries_scan" + "ubi_events_scan").
# ----------------------------------------------------------------------------


@dataclass
class _StubUbiAdapter:
    """Minimal :class:`SearchAdapter` stub for UbiReader tests.

    Records every call (target, body filters, top_k) so tests can assert
    the reader built the expected Query DSL. Exposes a ``schema_raises``
    knob so the probe-missing test can wire ``TargetNotFoundError``.
    """

    engine_type: EngineType = "opensearch"
    schema_raises: BaseException | None = None
    canned_query_hits: list[ScoredHit] = field(default_factory=list)
    canned_event_hits: list[ScoredHit] = field(default_factory=list)
    get_schema_calls: list[str] = field(default_factory=list)
    search_batch_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        self.get_schema_calls.append(target)
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
        assert len(queries) == 1, "UbiReader issues one NativeQuery per scan"
        native = queries[0]
        self.search_batch_calls.append(
            {
                "target": target,
                "query_id": native.query_id,
                "body": native.body,
                "top_k": top_k,
                "request_id": request_id,
            }
        )
        if native.query_id == "ubi_queries_scan":
            return {"ubi_queries_scan": list(self.canned_query_hits)}
        if native.query_id == "ubi_events_scan":
            return {"ubi_events_scan": list(self.canned_event_hits)}
        raise AssertionError(f"unexpected scan query_id {native.query_id!r}")

    # ----- Protocol-only stubs (UbiReader never touches these) -----
    # Implemented so the stub satisfies the full :class:`SearchAdapter`
    # Protocol shape (mypy --strict catches the substitution mismatch
    # without these — see test_protocol.py::_StubAdapter for the same
    # pattern).

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
    adapter = _StubUbiAdapter(canned_query_hits=[], canned_event_hits=[])
    reader = UbiReader(adapter)

    out = await reader.read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        until=datetime(2026, 5, 29, tzinfo=UTC),
    )

    assert out == {}
    # Reader probed, then issued the queries scan; did NOT issue the events scan
    # because the queries scan returned zero hits.
    scans = [call["query_id"] for call in adapter.search_batch_calls]
    assert scans == ["ubi_queries_scan"]


async def test_scan_top_k_never_exceeds_es_result_window() -> None:
    """Regression: a single search_batch is size-limited, not scrolling, so
    requesting size > the engine result-window makes the engine fail the
    query ("all shards failed") which the adapter swallows to empty — that
    surfaced as a spurious UBI_INSUFFICIENT_DATA on dense clusters (found via
    the rung-3 real-engine E2E). Both scans MUST clamp top_k to
    ES_MAX_RESULT_WINDOW even when a caller passes a larger cap.
    """
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[_nested_event(query_id="q-1", doc_id="d-a", action="click")],
    )
    await UbiReader(adapter).read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        max_queries=999_999,
        max_events=999_999,
    )
    for call in adapter.search_batch_calls:
        assert call["top_k"] <= ES_MAX_RESULT_WINDOW, (
            f"{call['query_id']} requested top_k={call['top_k']} > {ES_MAX_RESULT_WINDOW}"
        )


async def test_read_features_no_events_for_queries_returns_empty_dict() -> None:
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[],
    )
    reader = UbiReader(adapter)

    out = await reader.read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
    )

    assert out == {}
    # Both scans fired (queries scan returned 1 hit, events scan returned 0).
    scans = [call["query_id"] for call in adapter.search_batch_calls]
    assert scans == ["ubi_queries_scan", "ubi_events_scan"]


# ----------------------------------------------------------------------------
# read_features — happy path with canned data + field-extraction matrix
# ----------------------------------------------------------------------------


async def test_read_features_happy_path_nested_shape() -> None:
    """OpenSearch UBI plugin nested-shape — full pipeline → FeatureVec."""
    adapter = _StubUbiAdapter(
        canned_query_hits=[
            _query_hit("q-1", "red shoes"),
            _query_hit("q-2", "blue shirt"),
        ],
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
            _nested_event(query_id="q-1", doc_id="d-a", action="dwell", dwell_time_seconds=12.5),
            _nested_event(query_id="q-1", doc_id="d-b", action="impression", position=2),
            _nested_event(query_id="q-2", doc_id="d-c", action="impression", position=1),
            _nested_event(query_id="q-2", doc_id="d-c", action="click"),
        ],
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
    # Uninformed prior — corrected CTR equals raw CTR (1 click / 2 impressions).
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
        canned_query_hits=common_queries,
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
            _nested_event(query_id="q-1", doc_id="d-a", action="dwell", dwell_time_seconds=20.0),
        ],
    )
    flat_adapter = _StubUbiAdapter(
        canned_query_hits=common_queries,
        canned_event_hits=[
            _flat_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
            _flat_event(query_id="q-1", doc_id="d-a", action="click"),
            _flat_event(query_id="q-1", doc_id="d-a", action="dwell", dwell_seconds=20.0),
        ],
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
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[
            broken_hit,
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=1),
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
        ],
    )

    out = await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )

    # The broken event vanishes; the good (q-1, d-a) pair survives.
    assert list(out.keys()) == [("q-1", "d-a")]
    assert out[("q-1", "d-a")].click_count == 1


# ----------------------------------------------------------------------------
# Filter / propagation assertions — verify the reader builds the right DSL
# ----------------------------------------------------------------------------


def _filters_of(call: dict[str, Any]) -> list[dict[str, Any]]:
    return list(call["body"]["query"]["bool"]["filter"])


async def test_read_features_filters_propagate_target_and_window() -> None:
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
        ],
    )
    since = datetime(2026, 4, 1, tzinfo=UTC)
    until = datetime(2026, 5, 1, tzinfo=UTC)
    await UbiReader(adapter).read_features(target="articles", since=since, until=until)

    # ubi_queries scan
    qcall = next(c for c in adapter.search_batch_calls if c["query_id"] == "ubi_queries_scan")
    assert qcall["target"] == UBI_QUERIES_INDEX
    qfilters = _filters_of(qcall)
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in qfilters
    assert {"term": {"application": "articles"}} in qfilters

    # ubi_events scan
    ecall = next(c for c in adapter.search_batch_calls if c["query_id"] == "ubi_events_scan")
    assert ecall["target"] == UBI_EVENTS_INDEX
    efilters = _filters_of(ecall)
    assert {"range": {"timestamp": {"gte": since.isoformat(), "lt": until.isoformat()}}} in efilters
    assert {"term": {"application": "articles"}} in efilters
    # Events scan additionally filters on the query_id set from step 1.
    assert {"terms": {"query_id": ["q-1"]}} in efilters


async def test_read_features_optional_query_filter_adds_wildcard() -> None:
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red running shoes")],
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
        ],
    )
    await UbiReader(adapter).read_features(
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        query_filter="running",
    )
    qcall = next(c for c in adapter.search_batch_calls if c["query_id"] == "ubi_queries_scan")
    qfilters = _filters_of(qcall)
    assert {"wildcard": {"user_query": "*running*"}} in qfilters


async def test_read_features_until_defaults_to_now_when_missing() -> None:
    adapter = _StubUbiAdapter(canned_query_hits=[], canned_event_hits=[])
    before = datetime.now(UTC)
    await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    after = datetime.now(UTC)

    qcall = next(c for c in adapter.search_batch_calls if c["query_id"] == "ubi_queries_scan")
    qfilters = _filters_of(qcall)
    range_filter = next(f for f in qfilters if "range" in f)
    until_iso = range_filter["range"]["timestamp"]["lt"]
    parsed = datetime.fromisoformat(until_iso)
    assert before <= parsed <= after


async def test_read_features_no_writes_in_search_body() -> None:
    """Static assertion: nothing in the reader builds a write-shaped body."""
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
        ],
    )
    await UbiReader(adapter).read_features(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    for call in adapter.search_batch_calls:
        body = call["body"]
        # Only read-shape — body has 'query' + '_source' + 'track_total_hits'.
        # No 'script', 'doc', 'upsert', 'index', or 'delete' keys.
        forbidden = {"script", "doc", "upsert", "index", "delete", "params"}
        assert forbidden.isdisjoint(body.keys()), body


# ----------------------------------------------------------------------------
# Position-bias prior reaches aggregate_features
# ----------------------------------------------------------------------------


async def test_read_features_position_bias_prior_applies() -> None:
    """Informed prior `{1: 1.0, 2: 0.5}` doubles corrected CTR for rank-2-only impressions."""
    adapter = _StubUbiAdapter(
        canned_query_hits=[_query_hit("q-1", "red shoes")],
        canned_event_hits=[
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=2),
            _nested_event(query_id="q-1", doc_id="d-a", action="impression", position=2),
            _nested_event(query_id="q-1", doc_id="d-a", action="click"),
        ],
    )
    reader = UbiReader(adapter, position_bias_prior={1: 1.0, 2: 0.5})
    out = await reader.read_features(target="products", since=datetime(2026, 5, 1, tzinfo=UTC))

    feat = out[("q-1", "d-a")]
    # Raw CTR = 1/2 = 0.5; with prior {2: 0.5} the denominator becomes 2 * 0.5 = 1.0,
    # so corrected CTR = 1.0 (clipped, since clicks > weighted-impressions).
    assert math.isclose(feat.corrected_ctr, 1.0)


# ----------------------------------------------------------------------------
# read_user_query_map
# ----------------------------------------------------------------------------


async def test_read_user_query_map_returns_query_id_to_user_query() -> None:
    adapter = _StubUbiAdapter(
        canned_query_hits=[
            _query_hit("q-1", "red shoes"),
            _query_hit("q-2", "blue shirt"),
        ],
    )
    mapping = await UbiReader(adapter).read_user_query_map(
        target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
    )
    assert mapping == {"q-1": "red shoes", "q-2": "blue shirt"}
    # No probe needed — caller is expected to have already called read_features
    # (which probes). Documented in the method docstring.
    assert adapter.get_schema_calls == []


# ----------------------------------------------------------------------------
# Protocol shape — UbiReader must NOT add an adapter method (Story 2.1 DoD).
# ----------------------------------------------------------------------------


def test_search_adapter_protocol_methods_unchanged() -> None:
    """Story 2.1 DoD: no new method added to SearchAdapter Protocol.

    Lock the current method names + the ``engine_type`` annotation so
    adding a UBI-specific Protocol member anywhere would fail this
    test. ``engine_type`` is an annotation-only attribute (no default),
    so it doesn't appear in ``dir(SearchAdapter)`` — checked via
    ``__annotations__`` instead.
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
