# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.get_document`` + ``list_documents`` unit tests
(infra_adapter_solr Story A8, FR-9, AC-12 + AC-13).

* get_document via Solr RealTime Get (``/<target>/get?id=<doc_id>``).
* list_documents via Solr cursorMark — terminal-page rule (set
  ``next_cursor_token=None`` when nextCursorMark equals the current
  cursorMark, per spec FR-9 cycle-3 rule).
* uniqueKey resolution: ``uniqueKey=sku`` collections extract doc_id
  from the ``sku`` field (AC-12).
* New target post-registration: first call seeds the adapter-side cache
  via ``/schema/uniquekey``; second call within the adapter's lifetime
  skips the schema probe (FR-9 service-layer-only-write invariant).
* 101 docs / limit 25 → 5 pages without gaps (AC-13).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import ClusterUnreachableError, TargetNotFoundError
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
    engine_config_target: str | None = "products",
) -> SolrAdapter:
    cfg: dict[str, object] | None = None
    if engine_config_target is not None:
        cfg = {"unique_key_per_target": {engine_config_target: unique_key}}
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=cfg,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# get_document — RealTime Get.
# ---------------------------------------------------------------------------


class TestGetDocument:
    async def test_happy_path(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/solr/products/get"
            assert req.url.params.get("id") == "prod-001"
            return httpx.Response(200, json={"doc": {"id": "prod-001", "title": "Apple Watch"}})

        adapter = _build(handler)
        try:
            doc = await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()
        assert doc is not None
        assert doc.doc_id == "prod-001"
        assert doc.source == {"id": "prod-001", "title": "Apple Watch"}

    async def test_missing_doc_returns_none(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"doc": None})

        adapter = _build(handler)
        try:
            doc = await adapter.get_document("products", "missing")
        finally:
            await adapter.aclose()
        assert doc is None

    async def test_target_404_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build(handler)
        try:
            with pytest.raises(TargetNotFoundError):
                await adapter.get_document("products", "p1")
        finally:
            await adapter.aclose()

    async def test_401_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        adapter = _build(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter.get_document("products", "p1")
        finally:
            await adapter.aclose()

    async def test_uniquekey_sku(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"doc": {"sku": "ABC-001", "title": "Widget"}})

        adapter = _build(handler, unique_key="sku")
        try:
            doc = await adapter.get_document("products", "ABC-001")
        finally:
            await adapter.aclose()
        assert doc is not None
        assert doc.doc_id == "ABC-001"

    async def test_new_target_falls_back_to_schema_probe(self) -> None:
        """Targets created post-registration: cache miss → /schema/uniquekey
        → cached on the adapter instance per FR-9 service-layer-only-write."""
        paths: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            paths.append(req.url.path)
            if req.url.path.endswith("/schema/uniquekey"):
                return httpx.Response(200, json={"uniqueKey": "id"})
            return httpx.Response(200, json={"doc": {"id": "x1"}})

        adapter = _build(handler, engine_config_target=None)
        try:
            await adapter.get_document("new_target", "x1")
            await adapter.get_document("new_target", "x1")
        finally:
            await adapter.aclose()
        assert paths.count("/solr/new_target/schema/uniquekey") == 1
        assert paths.count("/solr/new_target/get") == 2


# ---------------------------------------------------------------------------
# list_documents — cursorMark + terminal-condition.
# ---------------------------------------------------------------------------


def _page_response(
    docs: list[dict[str, object]], *, num_found: int, next_cursor_mark: str
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "response": {"numFound": num_found, "docs": docs},
            "nextCursorMark": next_cursor_mark,
        },
    )


class TestListDocumentsCursorMark:
    async def test_first_page_uses_star_cursor(self) -> None:
        seen_cursor: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_cursor.append(req.url.params.get("cursorMark"))
            return _page_response(
                [{"id": f"p{i}"} for i in range(5)],
                num_found=5,
                next_cursor_mark="cmark-1",
            )

        adapter = _build(handler)
        try:
            page = await adapter.list_documents("products", limit=5)
        finally:
            await adapter.aclose()
        assert seen_cursor == ["*"]
        assert len(page.hits) == 5
        assert page.next_cursor_token == "cmark-1"
        assert page.total == 5

    async def test_subsequent_page_uses_search_after(self) -> None:
        seen_cursor: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_cursor.append(req.url.params.get("cursorMark"))
            # Full page (== limit) with a NEW mark → more to fetch. (A short
            # page would correctly terminate under the F3 short-page guard.)
            return _page_response(
                [{"id": f"p{i}"} for i in range(5)],
                num_found=11,
                next_cursor_mark="cmark-2",
            )

        adapter = _build(handler)
        try:
            page = await adapter.list_documents("products", search_after=["cmark-1"], limit=5)
        finally:
            await adapter.aclose()
        assert seen_cursor == ["cmark-1"]
        assert page.next_cursor_token == "cmark-2"

    async def test_terminal_page_sets_next_cursor_to_none(self) -> None:
        """Spec FR-9 cycle-3 rule: when nextCursorMark == current cursorMark,
        the page is terminal — next_cursor_token=None so has_more derives False."""

        def handler(req: httpx.Request) -> httpx.Response:
            current = req.url.params.get("cursorMark")
            # Return the SAME cursorMark to signal "no more results".
            return _page_response([], num_found=42, next_cursor_mark=current or "*")

        adapter = _build(handler)
        try:
            page = await adapter.list_documents("products", search_after=["cmark-final"], limit=5)
        finally:
            await adapter.aclose()
        assert page.next_cursor_token is None

    async def test_101_docs_limit_25_paginates_without_gaps(self) -> None:
        """AC-13: 101 docs / limit 25 → 5 pages (25+25+25+25+1), no doc repeats."""
        # Build a virtual 101-doc index keyed off cursorMark.
        all_docs: list[dict[str, object]] = [{"id": f"p{i:03d}"} for i in range(101)]

        def page_for(cursor: str | None, limit: int) -> httpx.Response:
            # Decode cursor: "*" → page 0, "p024" → after p024 → page 1, etc.
            start = 0
            if cursor and cursor != "*":
                # Cursor is the id of the last doc on the previous page.
                start = next(i for i, d in enumerate(all_docs) if d["id"] == cursor) + 1
            page_docs = all_docs[start : start + limit]
            if not page_docs:
                # Terminal: return same cursor.
                return _page_response([], num_found=len(all_docs), next_cursor_mark=cursor or "*")
            next_cursor = str(page_docs[-1]["id"])
            return _page_response(page_docs, num_found=len(all_docs), next_cursor_mark=next_cursor)

        def handler(req: httpx.Request) -> httpx.Response:
            return page_for(req.url.params.get("cursorMark"), 25)

        adapter = _build(handler)
        try:
            seen_ids: list[str] = []
            cursor: list[str] | None = None
            pages = 0
            while True:
                page = await adapter.list_documents("products", search_after=cursor, limit=25)
                pages += 1
                seen_ids.extend(h.doc_id for h in page.hits)
                if page.next_cursor_token is None:
                    break
                cursor = [page.next_cursor_token]
                if pages > 10:
                    pytest.fail("too many pages — terminal condition not detected")
        finally:
            await adapter.aclose()
        assert len(seen_ids) == 101
        assert len(set(seen_ids)) == 101  # no repeats


class TestListDocumentsFailures:
    async def test_404_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build(handler)
        try:
            with pytest.raises(TargetNotFoundError):
                await adapter.list_documents("products", limit=10)
        finally:
            await adapter.aclose()

    async def test_uniquekey_in_fl_when_caller_supplies_fields(self) -> None:
        seen_fl: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_fl.append(req.url.params.get("fl"))
            return _page_response([], num_found=0, next_cursor_mark="*")

        adapter = _build(handler, unique_key="sku")
        try:
            await adapter.list_documents("products", fields=["title"], limit=10)
        finally:
            await adapter.aclose()
        # Caller asked for title only — sku must be auto-included so doc_id
        # extraction works.
        assert seen_fl[0] is not None
        assert "sku" in seen_fl[0]
        assert "title" in seen_fl[0]


class TestListDocumentsShortPageTerminal:
    """Review F3: a short page (< limit) terminates even if Solr echoes a
    differently-normalized nextCursorMark that doesn't string-equal the
    request cursorMark."""

    async def test_short_page_nulls_next_cursor_even_when_marks_differ(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            # 2 docs for a limit-25 request, with a DIFFERENT (non-equal)
            # nextCursorMark — the == terminal check would miss this.
            return _page_response(
                [{"id": "p1"}, {"id": "p2"}],
                num_found=2,
                next_cursor_mark="AoIxOTk=normalized",
            )

        adapter = _build(handler)
        try:
            page = await adapter.list_documents("products", search_after=["AoIxOTk"], limit=25)
        finally:
            await adapter.aclose()
        assert len(page.hits) == 2
        assert page.next_cursor_token is None  # short page => terminal

    async def test_full_page_with_new_mark_keeps_cursor(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _page_response(
                [{"id": f"p{i}"} for i in range(5)],
                num_found=99,
                next_cursor_mark="next-mark",
            )

        adapter = _build(handler)
        try:
            page = await adapter.list_documents("products", limit=5)
        finally:
            await adapter.aclose()
        # Full page (== limit) + a new mark => more to fetch.
        assert page.next_cursor_token == "next-mark"
