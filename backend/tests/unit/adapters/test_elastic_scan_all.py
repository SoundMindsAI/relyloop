# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.scan_all`` / ``close_scan`` unit tests
(``chore_ubi_reader_search_after_pagination`` Story 2.1, FR-2).

Locked behaviors (per plan §10 + spec §11):

* AC-2 — PIT open → search_after loop → terminal close. Exact ``sort``
  and ``search_after`` round-trip across pages.
* AC-2b — PIT id rotation + ``keep_alive`` on every continuation.
* AC-3 — narrow PIT-unsupported fallback uses a configured
  ``Settings.ubi_no_pit_tiebreaker_field`` for ``[timestamp, <field>]``
  pagination (no ``_id`` sort).
* AC-3b — when no tiebreaker is configured, the fallback degrades to a
  single sampled query + WARN log.
* AC-8 — a mid-scan engine error closes the PIT best-effort and
  re-raises the original exception (cleanup never masks the primary).
* AC-10 — OpenSearch endpoint branch differences: open
  ``POST /<idx>/_search/point_in_time``; close
  ``DELETE /_search/point_in_time`` with body ``{"pit_id": [<id>]}``;
  ES uses ``/_pit`` with body ``{"id": <id>}``. PIT-open response
  field is ``id`` on ES vs ``pit_id`` on OpenSearch (P2-A2).
* AC-11 — 401/403/404 propagate normally (no fallback).
* P3-A1 / P5-A1 — caller-supplied pagination keys (``pit``/``sort``/
  ``size``/``search_after``/``from``) are stripped before BOTH PIT and
  no-PIT request construction.
* P3-A2 — page-error-plus-close-error preserves the primary exception.
* P4-A3 — terminal-close error still returns the final page.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
from backend.app.adapters.protocol import EngineType
from backend.app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _stub_credentials(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("ref:\n  username: u\n  password: p\n")
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_adapter(handler, *, engine_type: EngineType = "elasticsearch") -> ElasticAdapter:
    auth_kind = "es_basic" if engine_type == "elasticsearch" else "opensearch_basic"
    return ElasticAdapter(
        cluster_id="cl-1",
        engine_type=engine_type,
        base_url="http://es:9200",
        auth_kind=auth_kind,
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _pit_search_response(
    *,
    hits: list[dict[str, Any]],
    pit_id: str | None,
) -> httpx.Response:
    """Build a PIT-mode ``_search`` response carrying ``pit_id`` rotation."""
    body: dict[str, Any] = {
        "took": 1,
        "timed_out": False,
        "hits": {
            "total": {"value": len(hits), "relation": "eq"},
            "max_score": None,
            "hits": hits,
        },
    }
    if pit_id is not None:
        body["pit_id"] = pit_id
    return httpx.Response(200, json=body)


def _no_pit_search_response(hits: list[dict[str, Any]]) -> httpx.Response:
    """Build a plain ``_search`` response (no PIT echo)."""
    return httpx.Response(
        200,
        json={
            "took": 1,
            "timed_out": False,
            "hits": {
                "total": {"value": len(hits), "relation": "eq"},
                "max_score": None,
                "hits": hits,
            },
        },
    )


# -----------------------------------------------------------------------------
# AC-2 + AC-2b — PIT open → search_after continuation → terminal close
# -----------------------------------------------------------------------------


class TestPitHappyPath:
    @pytest.mark.asyncio
    async def test_open_continue_terminal_three_pages(self) -> None:
        """Pages 1+2 are full; page 3 short → terminal close. pit_id rotates
        on every page; close uses the LAST rotated id with the ES wire body.
        """
        calls: list[tuple[str, str, dict[str, Any] | None]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content) if req.content else None
            calls.append((req.method, req.url.path, body))
            # PIT open.
            if req.method == "POST" and req.url.path == "/ubi_events/_pit":
                assert req.url.params.get("keep_alive") == "1m"
                return httpx.Response(200, json={"id": "pit-v1"})
            # PIT-mode search — INDEX-LESS path.
            if req.method == "POST" and req.url.path == "/_search":
                assert body is not None
                # ``pit.id`` reflects the most recently rotated id; sort and
                # size are adapter-owned.
                assert body["sort"] == [{"timestamp": "asc"}, {"_shard_doc": "asc"}]
                assert body["size"] == 2
                page_count = sum(1 for c in calls if c[1] == "/_search")
                if page_count == 1:
                    # First search → 2 hits (full page), rotate to pit-v2.
                    assert body["pit"] == {"id": "pit-v1", "keep_alive": "1m"}
                    assert "search_after" not in body
                    return _pit_search_response(
                        hits=[
                            {
                                "_id": "evt-1",
                                "_score": 0.0,
                                "_source": {"q": "alpha"},
                                "sort": [1000, "shard-a-0"],
                            },
                            {
                                "_id": "evt-2",
                                "_score": 0.0,
                                "_source": {"q": "beta"},
                                "sort": [2000, "shard-a-1"],
                            },
                        ],
                        pit_id="pit-v2",
                    )
                if page_count == 2:
                    # Second search continues with the rotated id + the last
                    # sort from page 1.
                    assert body["pit"] == {"id": "pit-v2", "keep_alive": "1m"}
                    assert body["search_after"] == [2000, "shard-a-1"]
                    return _pit_search_response(
                        hits=[
                            {
                                "_id": "evt-3",
                                "_score": 0.0,
                                "_source": {"q": "gamma"},
                                "sort": [3000, "shard-a-2"],
                            },
                            {
                                "_id": "evt-4",
                                "_score": 0.0,
                                "_source": {"q": "delta"},
                                "sort": [4000, "shard-a-3"],
                            },
                        ],
                        pit_id="pit-v3",
                    )
                # Third search → 1 hit (short page) → terminal.
                assert body["pit"] == {"id": "pit-v3", "keep_alive": "1m"}
                assert body["search_after"] == [4000, "shard-a-3"]
                return _pit_search_response(
                    hits=[
                        {
                            "_id": "evt-5",
                            "_score": 0.0,
                            "_source": {"q": "epsilon"},
                            "sort": [5000, "shard-a-4"],
                        },
                    ],
                    pit_id="pit-v4",
                )
            # Terminal close — adapter MUST send DELETE /_pit with the last
            # rotated id, NOT the one originally opened.
            if req.method == "DELETE" and req.url.path == "/_pit":
                assert body == {"id": "pit-v4"}
                return httpx.Response(200, json={"succeeded": True, "num_freed": 1})
            raise AssertionError(f"unexpected request to {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            # Page 1.
            p1 = await adapter.scan_all("ubi_events", {}, page_size=2)
            assert len(p1.hits) == 2
            assert p1.hits[0].doc_id == "evt-1"
            assert p1.cursor is not None
            assert isinstance(p1.cursor, dict)
            assert p1.cursor["pit_id"] == "pit-v2"
            assert p1.cursor["search_after"] == [2000, "shard-a-1"]
            assert p1.cursor["no_pit"] is False

            # Page 2.
            p2 = await adapter.scan_all("ubi_events", {}, page_size=2, cursor=p1.cursor)
            assert len(p2.hits) == 2
            assert p2.cursor is not None
            assert isinstance(p2.cursor, dict)
            assert p2.cursor["pit_id"] == "pit-v3"
            assert p2.cursor["search_after"] == [4000, "shard-a-3"]

            # Page 3 — terminal (short page).
            p3 = await adapter.scan_all("ubi_events", {}, page_size=2, cursor=p2.cursor)
            assert len(p3.hits) == 1
            assert p3.hits[0].doc_id == "evt-5"
            assert p3.cursor is None  # terminal sentinel
        finally:
            await adapter.aclose()

        # Verify the request sequence: 1 open, 3 searches, 1 terminal close.
        methods = [(m, p) for m, p, _ in calls]
        assert methods == [
            ("POST", "/ubi_events/_pit"),
            ("POST", "/_search"),
            ("POST", "/_search"),
            ("POST", "/_search"),
            ("DELETE", "/_pit"),
        ]


# -----------------------------------------------------------------------------
# AC-10 — OpenSearch endpoint + response-field + close-body branch
# -----------------------------------------------------------------------------


class TestOpenSearchBranch:
    @pytest.mark.asyncio
    async def test_opensearch_pit_endpoints_and_close_body(self) -> None:
        """OpenSearch uses /_search/point_in_time (open + close) with body
        ``{"pit_id": [<id>]}`` on close, NOT ES's ``/_pit`` with
        ``{"id": <id>}``. Open response field is ``pit_id`` (P2-A2).
        """
        calls: list[tuple[str, str, dict[str, Any] | None]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content) if req.content else None
            calls.append((req.method, req.url.path, body))
            if req.method == "POST" and req.url.path == "/ubi_events/_search/point_in_time":
                assert req.url.params.get("keep_alive") == "1m"
                # OpenSearch returns pit_id, not id.
                return httpx.Response(200, json={"pit_id": "os-pit-1"})
            if req.method == "POST" and req.url.path == "/_search":
                assert body is not None
                assert body["pit"] == {"id": "os-pit-1", "keep_alive": "1m"}
                return _pit_search_response(
                    hits=[
                        {
                            "_id": "evt-1",
                            "_score": 0.0,
                            "_source": {},
                            "sort": [100, "s-0"],
                        },
                    ],
                    pit_id="os-pit-2",
                )
            if req.method == "DELETE" and req.url.path == "/_search/point_in_time":
                # OpenSearch close wire body is a list under "pit_id".
                assert body == {"pit_id": ["os-pit-2"]}
                return httpx.Response(200, json={"succeeded": True})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler, engine_type="opensearch")
        try:
            # Short page → terminal on first call.
            page = await adapter.scan_all("ubi_events", {}, page_size=10)
            assert page.cursor is None  # terminal
            assert len(page.hits) == 1
        finally:
            await adapter.aclose()

        assert calls[0][:2] == ("POST", "/ubi_events/_search/point_in_time")
        assert calls[-1][:2] == ("DELETE", "/_search/point_in_time")

    @pytest.mark.asyncio
    async def test_opensearch_open_response_uses_pit_id_field(self) -> None:
        """If the response uses the ES ``id`` field on an OpenSearch
        adapter (shouldn't happen in practice but locks the per-engine
        parser), the adapter raises ClusterUnreachableError rather than
        silently using ``None``.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/ubi_events/_search/point_in_time":
                # Wrong field — ``id`` instead of ``pit_id``.
                return httpx.Response(200, json={"id": "wrong-field"})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler, engine_type="opensearch")
        try:
            with pytest.raises(ClusterUnreachableError, match="missing 'pit_id'"):
                await adapter.scan_all("ubi_events", {}, page_size=2)
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# P3-A1 / P5-A1 — pagination-key stripping (PIT + no-PIT paths)
# -----------------------------------------------------------------------------


class TestPaginationKeyStripping:
    @pytest.mark.asyncio
    async def test_caller_pagination_keys_stripped_in_pit_mode(self) -> None:
        """Caller body that smuggles ``pit``/``sort``/``size``/``search_after``/
        ``from`` MUST NOT override the adapter-owned keys."""
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "POST" and req.url.path == "/ubi_events/_pit":
                return httpx.Response(200, json={"id": "pit-1"})
            if req.method == "POST" and req.url.path == "/_search":
                captured_bodies.append(json.loads(req.content))
                # Return a short page → terminal.
                return _pit_search_response(hits=[], pit_id=None)
            if req.method == "DELETE" and req.url.path == "/_pit":
                return httpx.Response(200, json={})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            stray_body = {
                "query": {"match_all": {}},
                # All of these should be stripped:
                "from": 50,
                "size": 1234,
                "sort": [{"_id": "asc"}],
                "search_after": ["leaked"],
                "pit": {"id": "caller-leak", "keep_alive": "10m"},
            }
            await adapter.scan_all("ubi_events", stray_body, page_size=25)
        finally:
            await adapter.aclose()

        assert len(captured_bodies) == 1
        body = captured_bodies[0]
        # Adapter-owned keys are not the caller's values.
        assert body["pit"] == {"id": "pit-1", "keep_alive": "1m"}
        assert body["sort"] == [{"timestamp": "asc"}, {"_shard_doc": "asc"}]
        assert body["size"] == 25
        assert "from" not in body
        # First-page request has no search_after (cursor=None).
        assert "search_after" not in body
        # The caller's ``query`` is preserved (not a pagination key).
        assert body["query"] == {"match_all": {}}

    @pytest.mark.asyncio
    async def test_caller_pit_stripped_before_no_pit_fallback(self) -> None:
        """P5-A1 — a caller ``pit`` in the body MUST NOT leak into the no-PIT
        fallback ``POST /<target>/_search`` after PIT open returned 405.
        """
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "POST" and req.url.path == "/ubi_events/_pit":
                return httpx.Response(405, text="Method Not Allowed")
            if req.method == "POST" and req.url.path == "/ubi_events/_search":
                captured_bodies.append(json.loads(req.content))
                return _no_pit_search_response(hits=[])
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            stray_body = {
                "query": {"match_all": {}},
                "pit": {"id": "caller-leak", "keep_alive": "10m"},
                "sort": [{"_id": "asc"}],
            }
            page = await adapter.scan_all("ubi_events", stray_body, page_size=25)
            assert page.cursor is None  # sampled mode → single page
        finally:
            await adapter.aclose()

        assert len(captured_bodies) == 1
        body = captured_bodies[0]
        # No leaked PIT and no leaked sort — sampled mode emits NEITHER.
        assert "pit" not in body
        assert "sort" not in body
        assert body["size"] == 25
        assert body["query"] == {"match_all": {}}


# -----------------------------------------------------------------------------
# AC-3 / AC-3b — narrow PIT-unsupported fallback (tiebreaker + sampled)
# -----------------------------------------------------------------------------


class TestNoPitFallback:
    @pytest.mark.asyncio
    async def test_tiebreaker_path_paginates(self, monkeypatch) -> None:
        """When ``Settings.ubi_no_pit_tiebreaker_field`` is configured, the
        fallback paginates ``[timestamp, <tiebreaker>]`` with search_after.
        Never sorts on ``_id``.
        """
        monkeypatch.setenv("UBI_NO_PIT_TIEBREAKER_FIELD", "event_id")
        get_settings.cache_clear()

        captured: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "POST" and req.url.path == "/ubi_events/_pit":
                return httpx.Response(501, text="Not Implemented")
            if req.method == "POST" and req.url.path == "/ubi_events/_search":
                body = json.loads(req.content)
                captured.append(body)
                page_count = len(captured)
                if page_count == 1:
                    return _no_pit_search_response(
                        hits=[
                            {
                                "_id": "evt-1",
                                "_score": 0.0,
                                "_source": {},
                                "sort": [1000, "evt-1"],
                            },
                            {
                                "_id": "evt-2",
                                "_score": 0.0,
                                "_source": {},
                                "sort": [2000, "evt-2"],
                            },
                        ]
                    )
                # Page 2 short → terminal.
                return _no_pit_search_response(
                    hits=[
                        {
                            "_id": "evt-3",
                            "_score": 0.0,
                            "_source": {},
                            "sort": [3000, "evt-3"],
                        },
                    ]
                )
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            p1 = await adapter.scan_all("ubi_events", {}, page_size=2)
            assert len(p1.hits) == 2
            assert p1.cursor is not None
            assert isinstance(p1.cursor, dict)
            assert p1.cursor["no_pit"] is True
            assert p1.cursor["pit_id"] is None
            assert p1.cursor["search_after"] == [2000, "evt-2"]

            p2 = await adapter.scan_all("ubi_events", {}, page_size=2, cursor=p1.cursor)
            assert len(p2.hits) == 1
            assert p2.cursor is None  # terminal
        finally:
            await adapter.aclose()

        # Sort sequence: page 1 has [{timestamp:asc},{event_id:asc}] + size, no
        # search_after. Page 2 has the same sort + the page-1 last_sort.
        assert captured[0]["sort"] == [
            {"timestamp": "asc"},
            {"event_id": "asc"},
        ]
        assert "search_after" not in captured[0]
        # Never sort on _id (AC-3b precondition).
        for body in captured:
            assert not any("_id" in (k for k in s.keys()) for s in body["sort"]), body["sort"]
        assert captured[1]["search_after"] == [2000, "evt-2"]

    @pytest.mark.asyncio
    async def test_sampled_path_single_page_with_warn(self, monkeypatch, caplog) -> None:
        """When no tiebreaker is configured, the fallback is a single
        sampled query + WARN log. Cursor is None immediately (no second
        page available)."""
        # Settings default has ubi_no_pit_tiebreaker_field=None.
        get_settings.cache_clear()
        import logging

        caplog.set_level(logging.WARNING)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "POST" and req.url.path == "/ubi_events/_pit":
                return httpx.Response(405, text="Method Not Allowed")
            if req.method == "POST" and req.url.path == "/ubi_events/_search":
                body = json.loads(req.content)
                # Sampled mode emits NO sort + NO search_after.
                assert "sort" not in body
                assert "search_after" not in body
                assert body["size"] == 100
                return _no_pit_search_response(
                    hits=[
                        {
                            "_id": "evt-1",
                            "_score": 0.0,
                            "_source": {},
                            "sort": [42, "anything"],
                        },
                    ],
                )
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            page = await adapter.scan_all("ubi_events", {}, page_size=100)
        finally:
            await adapter.aclose()

        assert len(page.hits) == 1
        assert page.cursor is None  # sampled mode terminates immediately


# -----------------------------------------------------------------------------
# AC-11 — 401/403/404 do NOT trigger fallback
# -----------------------------------------------------------------------------


class TestAclAndNotFoundPropagate:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_pit_open_acl_denial_raises_targets_forbidden(self, status: int) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/ubi_events/_pit":
                return httpx.Response(status, text="denied")
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetsForbiddenError):
                await adapter.scan_all("ubi_events", {}, page_size=10)
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_pit_open_index_missing_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/ubi_events/_pit":
                return httpx.Response(
                    404,
                    json={
                        "error": {
                            "type": "index_not_found_exception",
                            "reason": "no such index [ubi_events]",
                        },
                    },
                )
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetNotFoundError):
                await adapter.scan_all("ubi_events", {}, page_size=10)
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# AC-8 / P3-A2 — mid-scan exception path closes PIT best-effort, re-raises
# -----------------------------------------------------------------------------


class TestExceptionPath:
    @pytest.mark.asyncio
    async def test_mid_scan_5xx_closes_pit_best_effort(self) -> None:
        """A 5xx on a page raises ClusterUnreachableError; the adapter
        still issues a DELETE /_pit for the latest known id."""
        calls: list[tuple[str, str]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append((req.method, req.url.path))
            if req.url.path == "/ubi_events/_pit":
                return httpx.Response(200, json={"id": "pit-doomed"})
            if req.url.path == "/_search":
                # PIT-mode search fails with 503.
                return httpx.Response(503, text="upstream out")
            if req.method == "DELETE" and req.url.path == "/_pit":
                body = json.loads(req.content)
                assert body == {"id": "pit-doomed"}
                return httpx.Response(200, json={})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.scan_all("ubi_events", {}, page_size=2)
        finally:
            await adapter.aclose()

        # Open + search-5xx + close were all called.
        assert ("POST", "/ubi_events/_pit") in calls
        assert ("POST", "/_search") in calls
        assert ("DELETE", "/_pit") in calls

    @pytest.mark.asyncio
    async def test_page_error_plus_close_error_preserves_primary(self) -> None:
        """P3-A2 — if the page raises AND the close also fails, the page's
        exception propagates (not the close's)."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/ubi_events/_pit":
                return httpx.Response(200, json={"id": "pit-x"})
            if req.url.path == "/_search":
                return httpx.Response(503, text="search failed")
            if req.method == "DELETE" and req.url.path == "/_pit":
                # Close also fails — must be swallowed.
                return httpx.Response(500, text="close failed too")
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            # The /_search 503 is the PRIMARY exception. The /_pit DELETE 500
            # is the secondary close error — it must NOT mask the primary.
            with pytest.raises(ClusterUnreachableError, match="503"):
                await adapter.scan_all("ubi_events", {}, page_size=2)
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_terminal_close_error_still_returns_final_page(self) -> None:
        """P4-A3 — when the FINAL page is short (terminal) but the
        PIT close DELETE fails, the page is still returned (cursor=None)."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/ubi_events/_pit":
                return httpx.Response(200, json={"id": "pit-t"})
            if req.url.path == "/_search":
                # Short page → terminal.
                return _pit_search_response(
                    hits=[
                        {
                            "_id": "evt-z",
                            "_score": 0.0,
                            "_source": {"final": True},
                            "sort": [99, "shard-z"],
                        },
                    ],
                    pit_id="pit-t2",
                )
            if req.method == "DELETE" and req.url.path == "/_pit":
                return httpx.Response(500, text="terminal close failed")
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler)
        try:
            page = await adapter.scan_all("ubi_events", {}, page_size=2)
            # Final page returned in full despite the close failure.
            assert len(page.hits) == 1
            assert page.hits[0].source == {"final": True}
            assert page.cursor is None  # still terminal
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# AC-9 adapter half — close_scan releases the latest PIT
# -----------------------------------------------------------------------------


class TestCloseScan:
    @pytest.mark.asyncio
    async def test_close_scan_none_is_noop(self) -> None:
        """No HTTP request is issued when cursor is None."""
        called = False

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        adapter = _build_adapter(handler)
        try:
            await adapter.close_scan(None)
        finally:
            await adapter.aclose()
        assert called is False

    @pytest.mark.asyncio
    async def test_close_scan_no_pit_cursor_is_noop(self) -> None:
        """A cursor produced by the no-PIT fallback does NOT issue DELETE."""
        called = False

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        adapter = _build_adapter(handler)
        try:
            await adapter.close_scan({"pit_id": None, "search_after": [1, "x"], "no_pit": True})
        finally:
            await adapter.aclose()
        assert called is False

    @pytest.mark.asyncio
    async def test_close_scan_deletes_latest_pit_es(self) -> None:
        """ES wire body shape on close."""
        deleted: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "DELETE" and req.url.path == "/_pit":
                deleted.append(json.loads(req.content))
                return httpx.Response(200, json={})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler, engine_type="elasticsearch")
        try:
            await adapter.close_scan(
                {"pit_id": "pit-last", "search_after": [1, "x"], "no_pit": False}
            )
        finally:
            await adapter.aclose()
        assert deleted == [{"id": "pit-last"}]

    @pytest.mark.asyncio
    async def test_close_scan_deletes_latest_pit_opensearch(self) -> None:
        """OpenSearch wire body shape on close (P2-A2)."""
        deleted: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "DELETE" and req.url.path == "/_search/point_in_time":
                deleted.append(json.loads(req.content))
                return httpx.Response(200, json={})
            raise AssertionError(f"unexpected {req.method} {req.url.path}")

        adapter = _build_adapter(handler, engine_type="opensearch")
        try:
            await adapter.close_scan(
                {"pit_id": "os-pit-last", "search_after": [1], "no_pit": False}
            )
        finally:
            await adapter.aclose()
        assert deleted == [{"pit_id": ["os-pit-last"]}]

    @pytest.mark.asyncio
    async def test_close_scan_swallows_errors(self) -> None:
        """A close failure is logged + swallowed (never re-raises) so it
        cannot mask a caller's primary exception (P3-A2 invariant)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="close server died")

        adapter = _build_adapter(handler)
        try:
            # No exception propagates.
            await adapter.close_scan({"pit_id": "pit-x", "search_after": None, "no_pit": False})
        finally:
            await adapter.aclose()
