# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.render`` generalized hook — bundle OR pipeline label.

Mirrors ``test_elastic_render_normalizer_pipeline.py`` against ``SolrAdapter``
(feat_query_normalizer_typed_pipeline Story 1.4): a non-bundle powerset label
applies, bundles stay back-compatible through the new path, smart quotes
expand (FR-3), and the caller's params dict is not mutated (I-5).
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.protocol import QueryTemplate
from backend.app.adapters.solr import SolrAdapter
from backend.app.core.settings import get_settings
from backend.app.domain.study.normalizers import normalize_pipeline, steps_for_label


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


@pytest.fixture()
def adapter():
    a = SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )
    yield a


def _template() -> QueryTemplate:
    return QueryTemplate(
        name="edismax_q",
        engine_type="solr",
        body='{"defType": "edismax", "q": "{{ query_text }}", "qf": "title"}',
        declared_params={"query_normalizer": "string"},
    )


def test_non_bundle_pipeline_label_applies(adapter) -> None:
    label = "lowercase+strip_punctuation"
    native = adapter.render(_template(), params={"query_normalizer": label}, query_text="Hi, YOU!")
    assert native.body["q"] == normalize_pipeline("Hi, YOU!", steps_for_label(label)) == "hi you"


def test_bundle_label_back_compat(adapter) -> None:
    native = adapter.render(
        _template(),
        params={"query_normalizer": "lowercase+trim+expand_contractions"},
        query_text="What's GOOD?",
    )
    assert native.body["q"] == "what is good?"


def test_smart_quote_label_expands(adapter) -> None:
    native = adapter.render(
        _template(),
        params={"query_normalizer": "lowercase+trim+expand_contractions"},
        query_text="What’s up",
    )
    assert native.body["q"] == "what is up"


def test_caller_params_dict_unmutated_with_pipeline_label(adapter) -> None:
    params = {"query_normalizer": "lowercase+strip_punctuation"}
    adapter.render(_template(), params=params, query_text="Hi, there!")
    assert params == {"query_normalizer": "lowercase+strip_punctuation"}


def test_unknown_label_token_raises_value_error(adapter) -> None:
    with pytest.raises(ValueError, match="stem"):
        adapter.render(
            _template(), params={"query_normalizer": "lowercase+stem"}, query_text="HELLO"
        )
