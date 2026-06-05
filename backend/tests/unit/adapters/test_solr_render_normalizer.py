# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.render`` query_normalizer pre-render hook (AC-4, Story 2.3).

Mirrors ``test_elastic_render_normalizer.py`` against ``SolrAdapter``: absent
key pass-through, lowercase, expand-contractions + caller-dict immutability,
the FR-1 defense-in-depth default, and the invalid-value ValueError.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.protocol import QueryTemplate
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


def _edismax_template(declared: dict[str, str]) -> QueryTemplate:
    return QueryTemplate(
        name="edismax_q",
        engine_type="solr",
        body='{"defType": "edismax", "q": "{{ query_text }}", "qf": "title"}',
        declared_params=declared,
    )


def test_absent_query_normalizer_passes_through_verbatim(adapter) -> None:
    native = adapter.render(_edismax_template({}), params={}, query_text="HELLO World")
    assert native.body["q"] == "HELLO World"


def test_lowercase_choice_lowercases_q_ac4(adapter) -> None:
    # AC-4 verbatim.
    native = adapter.render(
        _edismax_template({"query_normalizer": "string"}),
        params={"query_normalizer": "lowercase"},
        query_text="HELLO",
    )
    assert native.body["q"] == "hello"


def test_expand_contractions_on_q(adapter) -> None:
    native = adapter.render(
        _edismax_template({"query_normalizer": "string"}),
        params={"query_normalizer": "lowercase+trim+expand_contractions"},
        query_text="What's GOOD?",
    )
    assert native.body["q"] == "what is good?"


def test_caller_params_dict_is_not_mutated(adapter) -> None:
    params = {"query_normalizer": "lowercase"}
    adapter.render(
        _edismax_template({"query_normalizer": "string"}),
        params=params,
        query_text="HELLO",
    )
    assert params == {"query_normalizer": "lowercase"}


def test_default_fallback_renders_verbatim_when_only_normalizer_declared(adapter) -> None:
    native = adapter.render(
        _edismax_template({"query_normalizer": "string"}),
        params={},
        query_text="HELLO",
    )
    assert native.body["q"] == "HELLO"


def test_invalid_normalizer_value_raises_value_error(adapter) -> None:
    with pytest.raises(ValueError) as exc:
        adapter.render(
            _edismax_template({"query_normalizer": "string"}),
            params={"query_normalizer": "stem"},
            query_text="HELLO",
        )
    assert "stem" in str(exc.value)
