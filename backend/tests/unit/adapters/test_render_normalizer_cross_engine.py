# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cross-engine portability proof for the normalizer hook (FR-3 ≡ FR-4).

Spec FR-4: "Behavior MUST be observable as identical across ES + OpenSearch
and Solr." This parametrized test runs the same query_text through both
adapters' render() with the full expand-contractions normalizer and asserts
the query_text substitution slot is identical ("what is good?") regardless of
engine — locking the invariant that the SAME normalized string enters the
template on every engine.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import NativeQuery, QueryTemplate
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


def _elastic() -> tuple[ElasticAdapter, QueryTemplate, str]:
    adapter = ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
    )
    template = QueryTemplate(
        name="es_q",
        engine_type="elasticsearch",
        body='{"query": {"match": {"title": "{{ query_text }}"}}}',
        declared_params={"query_normalizer": "string"},
    )
    return adapter, template, "elasticsearch"


def _solr() -> tuple[SolrAdapter, QueryTemplate, str]:
    adapter = SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )
    template = QueryTemplate(
        name="solr_q",
        engine_type="solr",
        body='{"defType": "edismax", "q": "{{ query_text }}", "qf": "title"}',
        declared_params={"query_normalizer": "string"},
    )
    return adapter, template, "solr"


def _extract_query_text(engine: str, native: NativeQuery) -> str:
    if engine == "elasticsearch":
        return native.body["query"]["match"]["title"]
    return native.body["q"]


@pytest.mark.parametrize("factory", [_elastic, _solr], ids=["elasticsearch", "solr"])
def test_same_normalized_query_text_across_engines(factory) -> None:
    adapter, template, engine = factory()
    native = adapter.render(
        template,
        params={"query_normalizer": "lowercase+trim+expand_contractions"},
        query_text="What's GOOD?",
    )
    assert _extract_query_text(engine, native) == "what is good?"
