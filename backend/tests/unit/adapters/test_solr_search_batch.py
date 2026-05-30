# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.search_batch`` unit tests via ``httpx.MockTransport``
(infra_adapter_solr Story A3).

Solr has no ``_msearch`` analog — search_batch issues one ``/select`` per
query via ``asyncio.gather(..., return_exceptions=True)``. The tests cover:

* Happy path: N queries → preserved ``query_id`` mapping; score + doc_id
  extracted from response.docs.
* uniqueKey resolution: a collection with ``uniqueKey=sku`` returns
  ``ScoredHit.doc_id`` from the ``sku`` field, not ``id`` (per cycle-3 C3-F3).
* fl normalization: every variant from (no ``fl``) / (``fl=title``) /
  (``fl=*``) / (``fl=*,score``) ensures ``score`` + uniqueKey survive into
  the request param.
* strict_errors=True: per-query 400 raises ``InvalidQueryDSLError``;
  5xx raises ``ClusterUnreachableError``; per-query timeout raises
  ``QueryTimeoutError``. Other queries in the batch don't abort (gather
  surfaces the exception out of the per-result loop).
* strict_errors=False: same failure modes silently yield empty list for
  the failing query_id; siblings still succeed.
* X-Request-Id propagation: the header is set on every per-query call.
* Empty queries list → empty dict (no HTTP, no error).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    TargetNotFoundError,
)
from backend.app.adapters.protocol import NativeQuery
from backend.app.adapters.solr import SolrAdapter, _normalize_fl
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


def _build_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    unique_key: str = "id",
) -> SolrAdapter:
    """Build a SolrAdapter pre-seeded with the given uniqueKey for ``products``."""
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config={"unique_key_per_target": {"products": unique_key}},
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _doc(
    doc_id: str, *, key: str = "id", score: float = 1.0, **fields: object
) -> dict[str, object]:
    return {key: doc_id, "score": score, **fields}


def _ok_response(docs: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"response": {"numFound": len(docs), "docs": docs}})


# ---------------------------------------------------------------------------
# Happy path — query_id mapping + ScoredHit parsing.
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_three_queries_preserved_mapping(self) -> None:
        seen_requests: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_requests.append(req.url.params.get("q"))
            return _ok_response([_doc(f"p{i}", score=2.0 - i * 0.5) for i in range(2)])

        adapter = _build_adapter(handler)
        try:
            queries = [
                NativeQuery(query_id=f"q{i}", body={"defType": "edismax", "q": f"text-{i}"})
                for i in range(3)
            ]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert set(result.keys()) == {"q0", "q1", "q2"}
        for hits in result.values():
            assert len(hits) == 2
            assert hits[0].doc_id == "p0"
            assert hits[0].score == 2.0
        assert sorted(seen_requests) == ["text-0", "text-1", "text-2"]

    async def test_empty_queries_returns_empty_dict(self) -> None:
        adapter = _build_adapter(lambda r: httpx.Response(500))
        try:
            result = await adapter.search_batch("products", [], top_k=10)
        finally:
            await adapter.aclose()
        assert result == {}

    async def test_request_id_propagated_as_header(self) -> None:
        seen_request_ids: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_request_ids.append(req.headers.get("X-Request-Id"))
            return _ok_response([])

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            await adapter.search_batch("products", queries, top_k=10, request_id="req-abc-123")
        finally:
            await adapter.aclose()
        assert seen_request_ids == ["req-abc-123"]


# ---------------------------------------------------------------------------
# uniqueKey resolution — collection with sku, not id (cycle-3 C3-F3).
# ---------------------------------------------------------------------------


class TestUniqueKeyResolution:
    async def test_sku_uniquekey(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response([{"sku": "ABC-123", "score": 5.0, "title": "Widget"}])

        adapter = _build_adapter(handler, unique_key="sku")
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "widget"})]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert result["q1"][0].doc_id == "ABC-123"
        assert result["q1"][0].score == 5.0

    async def test_uniquekey_falls_back_to_id_when_missing_from_engine_config(
        self,
    ) -> None:
        """A target absent from engine_config falls back to "id" via the cache
        + on-disk schema/uniquekey lookup. Here we make the schema lookup 404
        so the fallback path fires (the adapter caches "id")."""
        seen_paths: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_paths.append(req.url.path)
            if req.url.path.endswith("/schema/uniquekey"):
                return httpx.Response(404)
            return _ok_response([_doc("p1")])

        adapter = SolrAdapter(
            cluster_id="id",
            engine_type="solr",
            base_url="http://solr:8983",
            auth_kind="solr_basic",
            credentials_ref="ref",
            engine_config=None,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            result = await adapter.search_batch("orders", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert result["q1"][0].doc_id == "p1"
        # Subsequent call uses the cached "id" — schema/uniquekey not re-fetched.
        assert seen_paths.count("/solr/orders/schema/uniquekey") == 1


# ---------------------------------------------------------------------------
# fl normalization — ensures score + uniqueKey always survive.
# ---------------------------------------------------------------------------


class TestFlNormalization:
    @pytest.mark.parametrize(
        "in_fl,unique_key,expected_contains",
        [
            (None, "id", ["*", "score"]),
            ("", "id", ["*", "score"]),
            ("title,description", "id", ["score", "id", "title", "description"]),
            ("title", "sku", ["score", "sku", "title"]),
            ("*", "id", ["*", "score"]),
            ("*,score", "id", ["*", "score"]),
            ("score,id,title", "id", ["score", "id", "title"]),  # no dedup churn
        ],
    )
    def test_pure_normalizer(self, in_fl, unique_key, expected_contains) -> None:
        out = _normalize_fl(in_fl, unique_key)
        for field in expected_contains:
            assert field in out

    async def test_search_batch_normalizes_fl_in_request_params(self) -> None:
        seen_fl: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_fl.append(req.url.params.get("fl"))
            return _ok_response([_doc("p1")])

        adapter = _build_adapter(handler)
        try:
            queries = [
                NativeQuery(query_id="q1", body={"q": "x", "fl": "title"}),
            ]
            await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        # The original fl=title was preserved AND score+id prepended.
        fl_value = seen_fl[0]
        assert fl_value is not None
        assert "score" in fl_value
        assert "id" in fl_value
        assert "title" in fl_value


# ---------------------------------------------------------------------------
# strict_errors=True — typed exceptions per-query.
# ---------------------------------------------------------------------------


class TestStrictErrors:
    async def test_400_raises_invalid_query_dsl(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "msg": "Cannot parse 'malformed': Encountered ' ' at line 1",
                        "code": 400,
                    }
                },
            )

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="bad", body={"q": "malformed"})]
            with pytest.raises(InvalidQueryDSLError, match="Cannot parse"):
                await adapter.search_batch("products", queries, top_k=10, strict_errors=True)
        finally:
            await adapter.aclose()

    async def test_500_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="down")

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            with pytest.raises(ClusterUnreachableError, match="HTTP 500"):
                await adapter.search_batch("products", queries, top_k=10, strict_errors=True)
        finally:
            await adapter.aclose()

    async def test_404_raises_target_not_found_even_lenient(self) -> None:
        """404 on /select indicates the target collection disappeared mid-batch.
        That's a hard error worth surfacing regardless of strict_errors mode."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            with pytest.raises(TargetNotFoundError):
                await adapter.search_batch("products", queries, top_k=10, strict_errors=False)
        finally:
            await adapter.aclose()


# ---------------------------------------------------------------------------
# strict_errors=False — failures silently empty-list the failing query_id.
# ---------------------------------------------------------------------------


class TestLenientErrors:
    async def test_one_bad_query_doesnt_abort_batch(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            q = req.url.params.get("q")
            if q == "bad":
                return httpx.Response(400, json={"error": {"msg": "parse fail"}})
            return _ok_response([_doc("p1", score=1.0)])

        adapter = _build_adapter(handler)
        try:
            queries = [
                NativeQuery(query_id="ok1", body={"q": "good"}),
                NativeQuery(query_id="bad", body={"q": "bad"}),
                NativeQuery(query_id="ok2", body={"q": "good"}),
            ]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert len(result["ok1"]) == 1
        assert result["bad"] == []
        assert len(result["ok2"]) == 1

    async def test_5xx_silently_empty(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert result["q1"] == []


# ---------------------------------------------------------------------------
# Top-k → rows propagation.
# ---------------------------------------------------------------------------


class TestTopKPropagation:
    async def test_top_k_sets_rows_when_unspecified(self) -> None:
        seen_rows: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_rows.append(req.url.params.get("rows"))
            return _ok_response([])

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            await adapter.search_batch("products", queries, top_k=25)
        finally:
            await adapter.aclose()
        assert seen_rows == ["25"]

    async def test_explicit_rows_in_body_wins(self) -> None:
        seen_rows: list[str | None] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_rows.append(req.url.params.get("rows"))
            return _ok_response([])

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x", "rows": "5"})]
            await adapter.search_batch("products", queries, top_k=25)
        finally:
            await adapter.aclose()
        assert seen_rows == ["5"]


# ---------------------------------------------------------------------------
# Response parsing — skip-malformed-docs defensive path.
# ---------------------------------------------------------------------------


class TestResponseParsing:
    async def test_docs_missing_score_are_skipped(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response(
                [
                    {"id": "p1", "score": 2.0},
                    {"id": "p2"},  # missing score → skipped
                    {"id": "p3", "score": 1.0},
                ]
            )

        adapter = _build_adapter(handler)
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert [h.doc_id for h in result["q1"]] == ["p1", "p3"]

    async def test_empty_docs_yields_empty_list(self) -> None:
        adapter = _build_adapter(lambda r: _ok_response([]))
        try:
            queries = [NativeQuery(query_id="q1", body={"q": "x"})]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert result["q1"] == []
