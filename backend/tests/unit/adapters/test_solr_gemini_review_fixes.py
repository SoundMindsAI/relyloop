# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regressions for the Gemini Code Assist review fixes on PR #336.

* Gm-2: explain requests ``debug.explain.structured=true`` (Solr returns
  plain-text explanations otherwise → every explain would be unmatched).
* Gm-3: a read timeout in ``search_batch`` surfaces as ``QueryTimeoutError``
  (504), not ``ClusterUnreachableError`` (503).
* Gm-4: ``health_check`` treats any ``httpx.HTTPError`` (incl. PoolTimeout /
  WriteTimeout / NetworkError) as ``unreachable`` rather than 500-ing.
* Gm-5: a boolean ``field_boosts`` value is rejected (bool is an int subclass).
* Gm-6: ``_normalize_fl`` joins a list-valued ``fl`` instead of ``str([...])``.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
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


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> SolrAdapter:
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config={"unique_key_per_target": {"products": "id"}},
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# Gm-2 ----------------------------------------------------------------------


async def test_explain_requests_structured_debug() -> None:
    seen: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params.get("debug.explain.structured"))
        return httpx.Response(
            200,
            json={
                "debug": {
                    "explain": {"p1": {"match": True, "value": 1.5, "description": "sum of:"}}
                }
            },
        )

    adapter = _adapter(handler)
    try:
        tree = await adapter.explain("products", NativeQuery(query_id="q", body={"q": "x"}), "p1")
    finally:
        await adapter.aclose()
    assert seen[0] == "true"  # structured form requested
    assert tree.matched is True
    assert tree.value == 1.5


# Gm-3 ----------------------------------------------------------------------


async def test_read_timeout_maps_to_query_timeout_not_unreachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)

    adapter = _adapter(handler)
    try:
        queries = [NativeQuery(query_id="q1", body={"q": "x"})]
        with pytest.raises(QueryTimeoutError):
            await adapter.search_batch("products", queries, top_k=10, strict_errors=True)
    finally:
        await adapter.aclose()


async def test_read_timeout_lenient_yields_empty() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)

    adapter = _adapter(handler)
    try:
        queries = [NativeQuery(query_id="q1", body={"q": "x"})]
        result = await adapter.search_batch("products", queries, top_k=10)
    finally:
        await adapter.aclose()
    assert result["q1"] == []


# Gm-4 ----------------------------------------------------------------------


async def test_health_check_pool_timeout_is_unreachable_not_500() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.PoolTimeout("pool exhausted", request=req)

    adapter = _adapter(handler)
    try:
        status = await adapter.health_check()
    finally:
        await adapter.aclose()
    assert status.status == "unreachable"
    assert status.error is not None


# Gm-5 ----------------------------------------------------------------------


def test_bool_field_boost_rejected() -> None:
    with pytest.raises(InvalidQueryDSLError, match="must be a number"):
        SolrAdapter._render_qf({"title": True})


# Gm-6 ----------------------------------------------------------------------


def test_normalize_fl_joins_list() -> None:
    out = _normalize_fl(["id", "title"], "id")
    # Comma-joined, not str([...]); score injected; uniqueKey present.
    assert "[" not in out
    assert "id" in out.split(",")
    assert "title" in out.split(",")
    assert "score" in out.split(",")


def test_normalize_fl_str_unchanged_behaviour() -> None:
    out = _normalize_fl("title", "sku")
    parts = out.split(",")
    assert "title" in parts
    assert "sku" in parts
    assert "score" in parts


# Belt-and-suspenders: ClusterUnreachableError still maps to 503 path.
async def test_cluster_unreachable_still_503_path() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    adapter = _adapter(handler)
    try:
        queries = [NativeQuery(query_id="q1", body={"q": "x"})]
        with pytest.raises(ClusterUnreachableError):
            await adapter.search_batch("products", queries, top_k=10, strict_errors=True)
    finally:
        await adapter.aclose()
