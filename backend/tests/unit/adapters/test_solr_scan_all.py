# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.scan_all`` / ``close_scan`` unit tests
(``chore_ubi_reader_search_after_pagination`` Story 2.2, FR-3).

Locked behaviors (per plan §10 + spec §11):

* AC-4 — open / continue / terminal lifecycle via Solr ``cursorMark``.
  First page sets ``cursorMark=*``; continuations round-trip the prior
  ``nextCursorMark``; terminal when ``nextCursorMark`` echoes the
  request's cursorMark OR the page is short.
* uniqueKey-terminated sort — cursorMark requires a deterministic
  total ordering. Sort is ``<unique_key> asc``.
* ``_validate_solr_param_values`` runs on the constructed request
  params (nested dicts → ``InvalidQueryDSLError``).
* AC-14 (Solr half) — request body is **POST form-encoded**, never
  GET. A multi-thousand-id ``{!terms f=query_id}`` ``fq`` therefore
  travels in the body, not the URL, and cannot overflow URL/header
  limits (P1-B1).
* ``close_scan`` is a no-op — ``cursorMark`` holds no server-side
  resource.
* P4-A2 — caller-supplied ``start`` / ``rows`` / ``cursorMark`` /
  ``sort`` are stripped before request construction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    TargetNotFoundError,
)
from backend.app.adapters.solr import SolrAdapter
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


def _build(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    unique_key: str = "id",
    engine_config_target: str | None = "ubi_events",
) -> SolrAdapter:
    cfg: dict[str, object] | None = None
    if engine_config_target is not None:
        cfg = {"unique_key_per_target": {engine_config_target: unique_key}}
    return SolrAdapter(
        cluster_id="cl-1",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=cfg,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _select_response(*, docs: list[dict[str, Any]], next_cursor_mark: str | None) -> httpx.Response:
    """Build a Solr ``/select`` response with cursorMark continuation."""
    body: dict[str, Any] = {
        "responseHeader": {"status": 0, "QTime": 1},
        "response": {
            "numFound": len(docs),
            "start": 0,
            "docs": docs,
        },
    }
    if next_cursor_mark is not None:
        body["nextCursorMark"] = next_cursor_mark
    return httpx.Response(200, json=body)


def _form_params(req: httpx.Request) -> dict[str, list[str]]:
    """Parse the request's form body into a {key: [value, ...]} dict."""
    text = req.content.decode("utf-8") if req.content else ""
    # parse_qs returns lists; preserves repeated keys (fq is repeated).
    return parse_qs(text, keep_blank_values=True)


# -----------------------------------------------------------------------------
# AC-4 — open / continue / terminal cursorMark lifecycle
# -----------------------------------------------------------------------------


class TestCursorMarkLifecycle:
    async def test_open_continue_terminal(self) -> None:
        """Page 1: cursorMark=*. Page 2: previous nextCursorMark.
        Page 3: terminal (server echoes the request cursor → cursor=None).
        """
        recorded: list[dict[str, list[str]]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            assert req.method == "POST"
            assert req.url.path == "/solr/ubi_events/select"
            assert req.headers.get("Content-Type") == "application/x-www-form-urlencoded"
            params = _form_params(req)
            recorded.append(params)
            n = len(recorded)
            if n == 1:
                assert params["cursorMark"] == ["*"]
                return _select_response(
                    docs=[
                        {"id": "evt-1", "ts": "2026-05-01T00:00:00Z"},
                        {"id": "evt-2", "ts": "2026-05-01T00:00:01Z"},
                    ],
                    next_cursor_mark="cm-2",
                )
            if n == 2:
                assert params["cursorMark"] == ["cm-2"]
                return _select_response(
                    docs=[
                        {"id": "evt-3", "ts": "2026-05-01T00:00:02Z"},
                        {"id": "evt-4", "ts": "2026-05-01T00:00:03Z"},
                    ],
                    next_cursor_mark="cm-3",
                )
            # Terminal: Solr echoes the request cursor back as nextCursorMark.
            assert params["cursorMark"] == ["cm-3"]
            return _select_response(
                docs=[{"id": "evt-5", "ts": "2026-05-01T00:00:04Z"}],
                next_cursor_mark="cm-3",  # echo == terminal signal
            )

        adapter = _build(handler)
        try:
            p1 = await adapter.scan_all("ubi_events", {}, page_size=2)
            assert [h.doc_id for h in p1.hits] == ["evt-1", "evt-2"]
            assert p1.cursor == "cm-2"

            p2 = await adapter.scan_all("ubi_events", {}, page_size=2, cursor=p1.cursor)
            assert [h.doc_id for h in p2.hits] == ["evt-3", "evt-4"]
            assert p2.cursor == "cm-3"

            p3 = await adapter.scan_all("ubi_events", {}, page_size=2, cursor=p2.cursor)
            assert [h.doc_id for h in p3.hits] == ["evt-5"]
            assert p3.cursor is None  # terminal via echo
        finally:
            await adapter.aclose()

    async def test_short_page_terminates_secondary_guard(self) -> None:
        """When ``nextCursorMark`` differs from the request cursor but the
        page is short (``< page_size``), the adapter still treats it as
        terminal (mirrors ``list_documents`` review F3 guard)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return _select_response(
                docs=[{"id": "evt-1"}],  # 1 < page_size 10
                next_cursor_mark="cm-different",
            )

        adapter = _build(handler)
        try:
            page = await adapter.scan_all("ubi_events", {}, page_size=10)
            assert len(page.hits) == 1
            assert page.cursor is None  # short page → terminal
        finally:
            await adapter.aclose()

    async def test_missing_next_cursor_mark_terminates(self) -> None:
        """A response without ``nextCursorMark`` is treated as terminal."""

        def handler(req: httpx.Request) -> httpx.Response:
            return _select_response(docs=[{"id": "evt-1"}], next_cursor_mark=None)

        adapter = _build(handler)
        try:
            page = await adapter.scan_all("ubi_events", {}, page_size=10)
            assert page.cursor is None
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# AC-14 (Solr half) — POST (not GET); body, not URL
# -----------------------------------------------------------------------------


class TestPostFormBodyNotGet:
    async def test_large_terms_filter_travels_in_body(self) -> None:
        """A multi-thousand-id ``{!terms f=query_id}<ids>`` fq lives in the
        POST body, not the URL — so a long id list cannot overflow
        URL/header limits (P1-B1)."""
        # 5000 UUIDs ≈ 180 KB encoded — far beyond a typical 8 KB URL limit.
        big_ids = [f"q-{i:08d}" for i in range(5000)]
        terms_fq = "{!terms f=query_id}" + ",".join(big_ids)
        caller_body = {
            "q": "*:*",
            "fq": [
                "timestamp:[2026-04-01T00:00:00Z TO 2026-05-01T00:00:00Z}",
                'application:"products"',
                terms_fq,
            ],
        }

        captured_urls: list[str] = []
        captured_bodies: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_urls.append(str(req.url))
            captured_bodies.append(req.content.decode("utf-8") if req.content else "")
            return _select_response(docs=[], next_cursor_mark=None)

        adapter = _build(handler)
        try:
            await adapter.scan_all("ubi_events", caller_body, page_size=100)
        finally:
            await adapter.aclose()

        # The big terms fq travels in the request BODY, not the URL.
        assert len(captured_urls) == 1
        assert len(captured_urls[0]) < 200, (
            "URL must stay short — large fq must NOT be in the query string"
        )
        # And the body carries the encoded fq — comfortably above the typical
        # 8 KB URL limit this entire feature exists to dodge.
        assert len(captured_bodies[0]) > 50_000, (
            f"Body should carry tens of KB of encoded fq (got {len(captured_bodies[0])})"
        )
        # Sanity: the fq is actually present in the body.
        assert "terms+f%3Dquery_id" in captured_bodies[0]


# -----------------------------------------------------------------------------
# uniqueKey + sort + fl handling
# -----------------------------------------------------------------------------


class TestSortAndFl:
    async def test_sort_terminates_on_unique_key(self) -> None:
        """Sort MUST end on the resolved uniqueKey for cursorMark to be safe."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = _form_params(req)
            # Default uniqueKey is "id" → sort is "id asc".
            assert params["sort"] == ["id asc"]
            return _select_response(docs=[], next_cursor_mark=None)

        adapter = _build(handler)
        try:
            await adapter.scan_all("ubi_events", {"q": "*:*"}, page_size=10)
        finally:
            await adapter.aclose()

    async def test_sort_uses_custom_unique_key(self) -> None:
        """Sort uses ``<custom_unique_key> asc`` when the engine_config says so."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = _form_params(req)
            assert params["sort"] == ["sku asc"]
            return _select_response(docs=[], next_cursor_mark=None)

        adapter = _build(handler, unique_key="sku")
        try:
            await adapter.scan_all("ubi_events", {"q": "*:*"}, page_size=10)
        finally:
            await adapter.aclose()

    async def test_fl_default_wildcard(self) -> None:
        """When neither ``fl`` kwarg nor body[fl] is set, default to ``*``."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = _form_params(req)
            # _normalize_fl("*", "id") returns "*,score" — wildcard already covers uniqueKey.
            assert "*" in params["fl"][0]
            assert "score" in params["fl"][0]
            return _select_response(docs=[], next_cursor_mark=None)

        adapter = _build(handler)
        try:
            await adapter.scan_all("ubi_events", {"q": "*:*"}, page_size=10)
        finally:
            await adapter.aclose()

    async def test_fl_kwarg_override_includes_unique_key(self) -> None:
        """Explicit ``fl=[...]`` is normalized to ensure uniqueKey + score
        are present."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = _form_params(req)
            fl = params["fl"][0]
            assert "id" in fl
            assert "score" in fl
            assert "query_id" in fl
            return _select_response(docs=[], next_cursor_mark=None)

        adapter = _build(handler)
        try:
            await adapter.scan_all(
                "ubi_events",
                {"q": "*:*"},
                page_size=10,
                fl=["query_id", "timestamp"],
            )
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# P4-A2 — pagination-key stripping
# -----------------------------------------------------------------------------


class TestPaginationKeyStripping:
    async def test_caller_start_rows_cursor_sort_stripped(self) -> None:
        """Caller-supplied ``start``/``rows``/``cursorMark``/``sort`` are
        stripped — adapter-owned values win. ``start`` in particular is
        invalid combined with cursorMark and MUST never leak."""

        def handler(req: httpx.Request) -> httpx.Response:
            params = _form_params(req)
            # ``start`` MUST NOT appear in the outgoing request — it would
            # 400 or silently skip/duplicate rows when combined with
            # cursorMark.
            assert "start" not in params, (
                f"caller start leaked into request: {params.get('start')!r}"
            )
            # rows / cursorMark / sort are adapter-owned.
            assert params["rows"] == ["25"]
            assert params["cursorMark"] == ["*"]
            assert params["sort"] == ["id asc"]
            # Non-pagination caller keys (``q``) survive.
            assert params["q"] == ["*:*"]
            return _select_response(docs=[], next_cursor_mark=None)

        stray = {
            "q": "*:*",
            "start": "999",
            "rows": "9999",
            "cursorMark": "caller-leak",
            "sort": "_id asc",  # would also be unsafe — _id may not exist
        }
        adapter = _build(handler)
        try:
            await adapter.scan_all("ubi_events", stray, page_size=25)
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# Param validation
# -----------------------------------------------------------------------------


class TestParamValidation:
    async def test_nested_dict_param_raises(self) -> None:
        """A caller body that smuggles a nested dict (e.g. ES-style ``query``)
        fails ``_validate_solr_param_values`` → ``InvalidQueryDSLError``."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise AssertionError("Should not reach the engine — validation blocks first")

        adapter = _build(handler)
        try:
            with pytest.raises(InvalidQueryDSLError):
                await adapter.scan_all(
                    "ubi_events",
                    {"query": {"match": {"q": "shoes"}}},  # ES DSL fragment
                    page_size=10,
                )
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# Error envelope
# -----------------------------------------------------------------------------


class TestErrorEnvelope:
    async def test_404_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="no such collection")

        adapter = _build(handler)
        try:
            with pytest.raises(TargetNotFoundError):
                await adapter.scan_all("ubi_events", {}, page_size=10)
        finally:
            await adapter.aclose()

    @pytest.mark.parametrize("status", [401, 403])
    async def test_acl_denial_raises_cluster_unreachable(self, status: int) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="denied")

        adapter = _build(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter.scan_all("ubi_events", {}, page_size=10)
        finally:
            await adapter.aclose()

    async def test_5xx_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream out")

        adapter = _build(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.scan_all("ubi_events", {}, page_size=10)
        finally:
            await adapter.aclose()


# -----------------------------------------------------------------------------
# close_scan — no-op
# -----------------------------------------------------------------------------


class TestCloseScanIsNoop:
    async def test_close_scan_none(self) -> None:
        """No HTTP request — cursorMark holds no server-side resource."""
        called = False

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        adapter = _build(handler)
        try:
            await adapter.close_scan(None)
            await adapter.close_scan("cm-something")
        finally:
            await adapter.aclose()
        assert called is False
