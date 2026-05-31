# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.explain`` unit tests (infra_adapter_solr Story A5, FR-8).

* Happy path: debugQuery=true response parses into ExplainTree (matched,
  value, description, details).
* Doc IDs containing Lucene metacharacters (``:``, ``+``, ``-``, ``(``,
  ``)``, spaces, backslashes) are escaped before injection into the fq
  pin so the parser can't reinterpret them.
* uniqueKey resolution: explain pins on the right field for the target's
  uniqueKey (sku vs id).
* 404 → TargetNotFoundError.
* unmatched doc → ExplainTree(matched=False, value=0.0).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import ClusterUnreachableError, TargetNotFoundError
from backend.app.adapters.protocol import NativeQuery
from backend.app.adapters.solr import SolrAdapter, _lucene_escape
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
    handler: Callable[[httpx.Request], httpx.Response], *, unique_key: str = "id"
) -> SolrAdapter:
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config={"unique_key_per_target": {"products": unique_key}},
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# Pure helper: _lucene_escape.
# ---------------------------------------------------------------------------


class TestLuceneEscape:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("simple", "simple"),
            ("with:colon", "with\\:colon"),
            ("a+b", "a\\+b"),
            ("a/b", "a\\/b"),
            ("(group)", "\\(group\\)"),
            ('quoted"value"', 'quoted\\"value\\"'),
            ("back\\slash", "back\\\\slash"),
            ("has space", "has\\ space"),
            ('multi: + and / quote"', 'multi\\:\\ \\+\\ and\\ \\/\\ quote\\"'),
        ],
    )
    def test_escapes_metacharacters(self, raw: str, expected: str) -> None:
        assert _lucene_escape(raw) == expected


# ---------------------------------------------------------------------------
# explain — happy path.
# ---------------------------------------------------------------------------


def _explain_response(doc_id: str, value: float, description: str = "sum of:") -> dict[str, object]:
    return {
        "debug": {
            "explain": {
                doc_id: {
                    "match": True,
                    "value": value,
                    "description": description,
                    "details": [
                        {
                            "match": True,
                            "value": value / 2,
                            "description": "weight(title:laptop)",
                            "details": [],
                        },
                        {
                            "match": True,
                            "value": value / 2,
                            "description": "weight(description:laptop)",
                            "details": [],
                        },
                    ],
                }
            }
        }
    }


class TestExplainHappyPath:
    async def test_matched_doc(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_explain_response("p001", 1.5))

        adapter = _build(handler)
        try:
            query = NativeQuery(query_id="q1", body={"defType": "edismax", "q": "laptop"})
            tree = await adapter.explain("products", query, "p001")
        finally:
            await adapter.aclose()
        assert tree.doc_id == "p001"
        assert tree.matched is True
        assert tree.value == 1.5
        assert tree.description.startswith("sum of:")
        assert len(tree.details) == 2

    async def test_uniquekey_sku_pins_correct_field(self) -> None:
        seen_fq: list[str | list[str]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            fq = req.url.params.get_list("fq")
            seen_fq.append(fq)
            return httpx.Response(200, json=_explain_response("ABC-001", 2.0))

        adapter = _build(handler, unique_key="sku")
        try:
            query = NativeQuery(query_id="q", body={"q": "x"})
            tree = await adapter.explain("products", query, "ABC-001")
        finally:
            await adapter.aclose()
        # The pinned fq uses sku, not id.
        assert any(
            "sku:" in fq for fqs in seen_fq for fq in (fqs if isinstance(fqs, list) else [fqs])
        )
        assert tree.doc_id == "ABC-001"


# ---------------------------------------------------------------------------
# explain — failure modes.
# ---------------------------------------------------------------------------


class TestExplainFailures:
    async def test_404_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build(handler)
        try:
            query = NativeQuery(query_id="q", body={"q": "x"})
            with pytest.raises(TargetNotFoundError):
                await adapter.explain("products", query, "p001")
        finally:
            await adapter.aclose()

    async def test_401_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        adapter = _build(handler)
        try:
            query = NativeQuery(query_id="q", body={"q": "x"})
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter.explain("products", query, "p001")
        finally:
            await adapter.aclose()

    async def test_unmatched_doc_returns_no_match(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            # Solr returns 200 with empty explain block when the fq pin
            # excludes the doc.
            return httpx.Response(200, json={"debug": {"explain": {}}})

        adapter = _build(handler)
        try:
            query = NativeQuery(query_id="q", body={"q": "x"})
            tree = await adapter.explain("products", query, "missing")
        finally:
            await adapter.aclose()
        assert tree.matched is False
        assert tree.value == 0.0
        assert tree.description == "no match"


# ---------------------------------------------------------------------------
# explain — doc_ids with Lucene metachars are safe.
# ---------------------------------------------------------------------------


class TestExplainEscaping:
    @pytest.mark.parametrize("raw_id", ["a:b", "a+b", "(group)", "a b", "back\\slash"])
    async def test_metacharacter_doc_ids_are_escaped(self, raw_id: str) -> None:
        seen_fq_pins: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            for fq in req.url.params.get_list("fq"):
                seen_fq_pins.append(fq)
            return httpx.Response(
                200,
                json={
                    "debug": {
                        "explain": {raw_id: {"match": True, "value": 1.0, "description": "x"}}
                    }
                },
            )

        adapter = _build(handler)
        try:
            query = NativeQuery(query_id="q", body={"q": "x"})
            await adapter.explain("products", query, raw_id)
        finally:
            await adapter.aclose()
        # The fq pin contains the escaped form, not the raw form.
        assert any(_lucene_escape(raw_id) in pin for pin in seen_fq_pins)
