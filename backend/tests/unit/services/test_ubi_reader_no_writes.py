# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``UbiReader`` write-safety invariant (feat_ubi_judgments §10 threat #2
+ chore_ubi_reader_search_after_pagination Story 3.1 / FR-6).

Boots a real :class:`ElasticAdapter` against a recording
:class:`httpx.MockTransport`, runs :meth:`UbiReader.read_features`
end-to-end against canned ``_mapping`` + PIT + ``_search`` responses,
and asserts that ZERO requests with write-shaped methods (``PUT``,
``DELETE`` against an INDEXED path, ``POST`` against write-only paths)
or write-shaped paths (``_bulk``, ``_update``, ``_doc``, ``_create``)
ever escape the reader's call boundary.

The pagination upgrade (FR-4) added two new request shapes to the
allowlist:

* ``POST /<idx>/_pit`` (ES open PIT) /
  ``POST /<idx>/_search/point_in_time`` (OpenSearch open PIT) — both
  open a read-only Point-In-Time snapshot.
* ``DELETE /_pit`` (ES close, **unindexed**) /
  ``DELETE /_search/point_in_time`` (OpenSearch close, **unindexed**)
  — release the snapshot. The unindexed-path constraint is the
  no-writes invariant: an indexed ``DELETE`` would be a real
  document-delete request; the unindexed PIT-close paths only
  release ephemeral read state.

Lives under ``backend/tests/unit/services/`` mirroring the sibling
``test_elastic_get_document.py`` pattern (httpx.MockTransport against
a real adapter; no DB/Redis/engine needed). Spec §13 + spec §10
threat #2 both lock the guarantee that RelyLoop NEVER writes to a
UBI-bearing cluster.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.core.settings import get_settings
from backend.app.services.ubi_reader import UbiReader

# ----------------------------------------------------------------------------
# Allow / forbid sets
# ----------------------------------------------------------------------------


WRITE_METHODS = frozenset({"PUT", "PATCH"})
"""HTTP methods that ALWAYS indicate a cluster write — never permitted.

``DELETE`` is NOT in this set because the PIT-close path uses
``DELETE`` against an UNINDEXED path (``/_pit`` /
``/_search/point_in_time``) to release a read snapshot. Indexed
``DELETE`` (e.g. ``DELETE /<idx>/_doc/<id>``) IS forbidden — the
``WRITE_PATH_SEGMENTS`` check below catches it via ``_doc``.
"""

WRITE_PATH_SEGMENTS = ("_bulk", "_update", "_create", "_doc")
"""Path segments that always indicate write-shaped intent on ES/OpenSearch."""

# PIT-close paths are exact strings — they MUST be unindexed for the
# no-writes invariant to hold.
ALLOWED_PIT_CLOSE_PATHS = frozenset({"/_pit", "/_search/point_in_time"})


def _is_allowed_request(method: str, path: str) -> tuple[bool, str | None]:
    """Return (allowed, reason-if-forbidden) for one request.

    Allowed shapes (all read-only):

    * ``GET /<idx>/_mapping`` (schema probe).
    * ``GET /<idx>/_settings`` (analyzer probe — called by get_schema).
    * ``POST /<idx>/_pit`` (ES PIT open).
    * ``POST /<idx>/_search/point_in_time`` (OpenSearch PIT open).
    * ``POST /_search`` (PIT-mode search — index-less).
    * ``POST /<idx>/_search`` (no-PIT fallback search).
    * ``DELETE /_pit`` (ES PIT close — unindexed).
    * ``DELETE /_search/point_in_time`` (OpenSearch PIT close — unindexed).
    """
    method_u = method.upper()
    if method_u in WRITE_METHODS:
        return False, f"forbidden write method {method_u}"
    for forbidden in WRITE_PATH_SEGMENTS:
        if forbidden in path.split("/"):
            return False, f"write-shaped path segment {forbidden!r}"
    # DELETE is allowed ONLY for the two unindexed PIT-close paths.
    if method_u == "DELETE":
        if path not in ALLOWED_PIT_CLOSE_PATHS:
            return False, f"DELETE on indexed path {path!r} is a write"
    return True, None


# ----------------------------------------------------------------------------
# Recording transport — serves PIT + paginated search responses
# ----------------------------------------------------------------------------


def _empty_pit_search_response() -> httpx.Response:
    """Return an empty terminal PIT-mode _search page."""
    return httpx.Response(
        200,
        json={
            "took": 1,
            "timed_out": False,
            "hits": {
                "total": {"value": 0, "relation": "eq"},
                "max_score": None,
                "hits": [],
            },
            "pit_id": "pit-1",
        },
    )


class _RecordingTransport(httpx.MockTransport):
    """Mock transport that records every (method, path) and serves canned
    UBI responses through the PIT pagination path.
    """

    def __init__(self) -> None:
        super().__init__(self._handler)
        self.calls: list[tuple[str, str]] = []
        self._pit_id = "pit-ubi-1"

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path

        # Schema probe (UbiNotEnabled check) — ubi_queries /_mapping.
        if path.endswith("/_mapping"):
            return httpx.Response(
                200,
                json={
                    "ubi_queries": {
                        "mappings": {
                            "properties": {
                                "query_id": {"type": "keyword"},
                                "user_query": {"type": "text"},
                                "application": {"type": "keyword"},
                                "timestamp": {"type": "date"},
                            }
                        }
                    }
                },
            )
        # Analyzer probe (called by get_schema).
        if path.endswith("/_settings"):
            return httpx.Response(
                200,
                json={
                    "ubi_queries": {
                        "settings": {"index": {"analysis": {"analyzer": {"default": {}}}}}
                    }
                },
            )
        # PIT open — OpenSearch shape returns `pit_id`; ES returns `id`.
        # The fixture uses OpenSearch via the adapter, so respond with pit_id.
        if path.endswith("/_search/point_in_time"):
            return httpx.Response(200, json={"pit_id": self._pit_id})
        if path.endswith("/_pit"):
            return httpx.Response(200, json={"id": self._pit_id})
        # PIT-bound search — INDEX-LESS POST /_search.
        if path == "/_search":
            # Differentiate by call order — first PIT-mode search is the
            # ubi_queries scan; subsequent ones are the ubi_events scan.
            pit_searches = sum(1 for m, p in self.calls if p == "/_search")
            if pit_searches == 1:
                # ubi_queries scan — return ONE query hit, terminal page.
                return httpx.Response(
                    200,
                    json={
                        "took": 1,
                        "timed_out": False,
                        "hits": {
                            "total": {"value": 1, "relation": "eq"},
                            "hits": [
                                {
                                    "_id": "ubi-q-1",
                                    "_score": 0.0,
                                    "_source": {
                                        "query_id": "ubi-q-1",
                                        "user_query": "red shoes",
                                        "application": "products",
                                        "timestamp": "2026-05-20T10:00:00Z",
                                    },
                                    "sort": [1, "shard-0"],
                                }
                            ],
                        },
                        "pit_id": self._pit_id,
                    },
                )
            # ubi_events scan — return ONE event hit, terminal page.
            return httpx.Response(
                200,
                json={
                    "took": 1,
                    "timed_out": False,
                    "hits": {
                        "total": {"value": 2, "relation": "eq"},
                        "hits": [
                            {
                                "_id": "evt-1",
                                "_score": 0.0,
                                "_source": {
                                    "query_id": "ubi-q-1",
                                    "action_name": "click",
                                    "object_id": "doc-a",
                                    "timestamp": "2026-05-20T10:01:00Z",
                                },
                                "sort": [2, "shard-1"],
                            },
                            {
                                "_id": "evt-2",
                                "_score": 0.0,
                                "_source": {
                                    "query_id": "ubi-q-1",
                                    "action_name": "impression",
                                    "object_id": "doc-a",
                                    "position": 1,
                                    "timestamp": "2026-05-20T10:00:30Z",
                                },
                                "sort": [3, "shard-2"],
                            },
                        ],
                    },
                    "pit_id": self._pit_id,
                },
            )
        # PIT close — body shape verified by the adapter tests; here we just
        # echo OK so the reader's `finally` cleanup completes silently.
        if request.method == "DELETE" and path in ALLOWED_PIT_CLOSE_PATHS:
            return httpx.Response(200, json={"succeeded": True})
        raise AssertionError(f"unexpected request to {request.method} {path}")


class _EmptyTransport(httpx.MockTransport):
    """Variant: PIT scans return empty pages immediately."""

    def __init__(self) -> None:
        super().__init__(self._handler)
        self.calls: list[tuple[str, str]] = []
        self._pit_id = "pit-empty"

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/_mapping"):
            return httpx.Response(200, json={"ubi_queries": {"mappings": {"properties": {}}}})
        if path.endswith("/_settings"):
            return httpx.Response(200, json={"ubi_queries": {"settings": {"index": {}}}})
        if path.endswith("/_search/point_in_time"):
            return httpx.Response(200, json={"pit_id": self._pit_id})
        if path.endswith("/_pit"):
            return httpx.Response(200, json={"id": self._pit_id})
        if path == "/_search":
            return _empty_pit_search_response()
        if request.method == "DELETE" and path in ALLOWED_PIT_CLOSE_PATHS:
            return httpx.Response(200, json={"succeeded": True})
        raise AssertionError(f"unexpected request to {request.method} {path}")


# ----------------------------------------------------------------------------
# Settings stub — ElasticAdapter resolves credentials via Settings; provide a
# minimal env so the adapter constructs cleanly without touching real secrets.
# ----------------------------------------------------------------------------


@pytest.fixture
def _stub_credentials(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("ubi-test:\n  username: u\n  password: p\n")
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_adapter(transport: httpx.MockTransport) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="ubi-test",
        engine_type="opensearch",
        base_url="http://opensearch:9200",
        auth_kind="opensearch_basic",
        credentials_ref="ubi-test",
        engine_config=None,
        client=httpx.AsyncClient(transport=transport),
    )


# ----------------------------------------------------------------------------
# The invariant: zero write-shaped requests escape the reader's call boundary.
# ----------------------------------------------------------------------------


async def test_read_features_issues_no_write_shaped_requests(
    _stub_credentials,  # noqa: ARG001 — autouse-like fixture
) -> None:
    """Full read pipeline → no write-shaped HTTP methods or paths.

    Allowlist includes the new PIT pagination shapes (open / search /
    close) — verifies the reader stays read-only AND the new request
    shapes still respect the unindexed-DELETE constraint for PIT close.
    """
    from datetime import UTC, datetime

    transport = _RecordingTransport()
    adapter = _build_adapter(transport)
    try:
        reader = UbiReader(adapter)
        out = await reader.read_features(
            target="products",
            since=datetime(2026, 5, 1, tzinfo=UTC),
            until=datetime(2026, 5, 29, tzinfo=UTC),
        )
    finally:
        await adapter.aclose()

    # Sanity — the pipeline actually ran end-to-end.
    assert ("ubi-q-1", "doc-a") in out
    feat = out[("ubi-q-1", "doc-a")]
    assert feat.click_count == 1
    assert feat.impression_count == 1

    # Invariant: every recorded call is READ-shaped.
    for method, path in transport.calls:
        allowed, reason = _is_allowed_request(method, path)
        assert allowed, f"reader issued forbidden request {method} {path}: {reason}"

    # Exact expected call profile — one mapping probe, one settings lookup,
    # one PIT open per scan (ubi_queries + ubi_events = 2 opens), two PIT-
    # bound searches (one per scan), two PIT closes (one per scan terminal).
    methods_and_paths = transport.calls
    assert ("GET", "/ubi_queries/_mapping") in methods_and_paths
    assert ("GET", "/ubi_queries/_settings") in methods_and_paths
    # PIT opens are indexed at /<idx>/_search/point_in_time (OpenSearch).
    pit_opens = [
        c for c in methods_and_paths if c[0] == "POST" and c[1].endswith("/_search/point_in_time")
    ]
    assert len(pit_opens) == 2  # queries + events scans
    # PIT-bound searches are INDEX-LESS POST /_search.
    pit_searches = [c for c in methods_and_paths if c == ("POST", "/_search")]
    assert len(pit_searches) == 2  # queries + events scans
    # PIT closes are UNINDEXED DELETEs (the no-writes invariant relies on
    # the unindexed shape — an indexed DELETE would be a write).
    pit_closes = [c for c in methods_and_paths if c == ("DELETE", "/_search/point_in_time")]
    assert len(pit_closes) >= 2  # one per terminal scan


async def test_read_features_zero_writes_when_window_empty(
    _stub_credentials,  # noqa: ARG001
) -> None:
    """Even when the reader bails on an empty queries scan, no writes leak."""
    from datetime import UTC, datetime

    transport = _EmptyTransport()
    adapter = _build_adapter(transport)
    try:
        out = await UbiReader(adapter).read_features(
            target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
        )
    finally:
        await adapter.aclose()

    assert out == {}
    # The reader short-circuits after the empty queries scan — only one
    # PIT lifecycle fires (queries scan), not two.
    pit_opens = [
        c for c in transport.calls if c[1].endswith("/_search/point_in_time") and c[0] == "POST"
    ]
    assert len(pit_opens) == 1
    pit_searches = [c for c in transport.calls if c == ("POST", "/_search")]
    assert len(pit_searches) == 1

    # Same invariant.
    for method, path in transport.calls:
        allowed, reason = _is_allowed_request(method, path)
        assert allowed, f"reader issued forbidden request {method} {path}: {reason}"


# ----------------------------------------------------------------------------
# Static — verify the allow / forbid taxonomy itself
# ----------------------------------------------------------------------------


def test_indexed_delete_is_forbidden() -> None:
    """The taxonomy MUST reject an indexed DELETE — that would be a write
    even though DELETE is conditionally permitted for PIT close."""
    allowed, reason = _is_allowed_request("DELETE", "/products/_doc/abc")
    assert not allowed
    # The check fires on `_doc` segment before the DELETE-path check
    # (write-shape path segments are checked first).
    assert reason is not None


def test_unindexed_pit_delete_is_allowed() -> None:
    allowed, _ = _is_allowed_request("DELETE", "/_pit")
    assert allowed
    allowed, _ = _is_allowed_request("DELETE", "/_search/point_in_time")
    assert allowed


def test_put_is_always_write() -> None:
    allowed, reason = _is_allowed_request("PUT", "/_anywhere")
    assert not allowed
    assert reason is not None
