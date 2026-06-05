# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.render`` query_normalizer pre-render hook (AC-3, Story 2.2).

Covers: absent key (backward-compat verbatim pass-through), lowercase,
the full expand-contractions bundle (AC-3 verbatim), caller-dict immutability,
the FR-1 defense-in-depth default fallback, and the invalid-value ValueError.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import ParamValue, QueryTemplate
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


def _adapter() -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
    )


def _title_match_template(declared: dict[str, str]) -> QueryTemplate:
    return QueryTemplate(
        name="title_match",
        engine_type="elasticsearch",
        body='{"query": {"match": {"title": "{{ query_text }}"}}}',
        declared_params=declared,
    )


def test_absent_query_normalizer_passes_through_verbatim() -> None:
    # Backward-compat: no key -> query_text untouched (existing templates).
    template = _title_match_template({})
    native = _adapter().render(template, params={}, query_text="HELLO World")
    assert native.body["query"]["match"]["title"] == "HELLO World"


def test_lowercase_choice_lowercases_query_text() -> None:
    template = _title_match_template({"query_normalizer": "string"})
    native = _adapter().render(
        template,
        params={"query_normalizer": "lowercase"},
        query_text="HELLO",
    )
    assert native.body["query"]["match"]["title"] == "hello"


def test_full_bundle_expands_contractions_ac3() -> None:
    # AC-3 verbatim.
    template = _title_match_template({"query_normalizer": "string"})
    native = _adapter().render(
        template,
        params={"query_normalizer": "lowercase+trim+expand_contractions"},
        query_text="What's the BEST policy?",
    )
    assert native.body["query"]["match"]["title"] == "what is the best policy?"


def test_caller_params_dict_is_not_mutated() -> None:
    # AC-3 second clause — the adapter copies params before popping.
    template = _title_match_template({"query_normalizer": "string", "title_boost": "float"})
    template = QueryTemplate(
        name="t",
        engine_type="elasticsearch",
        body=(
            '{"query": {"match": {"title": {"query": "{{ query_text }}", '
            '"boost": {{ title_boost }}}}}}'
        ),
        declared_params={"query_normalizer": "string", "title_boost": "float"},
    )
    params: dict[str, ParamValue] = {"query_normalizer": "lowercase", "title_boost": 2.0}
    _adapter().render(template, params=params, query_text="HELLO")
    assert params == {"query_normalizer": "lowercase", "title_boost": 2.0}


def test_defense_in_depth_default_when_key_absent_but_declared() -> None:
    # FR-1 second clause: a caller that bypasses compute_default_params and
    # omits query_normalizer still renders — the hook defaults to "none"
    # (verbatim) and the missing-check flags title_boost, NOT query_normalizer.
    template = QueryTemplate(
        name="t",
        engine_type="elasticsearch",
        body=(
            '{"query": {"match": {"title": {"query": "{{ query_text }}", '
            '"boost": {{ title_boost }}}}}}'
        ),
        declared_params={"query_normalizer": "string", "title_boost": "float"},
    )
    with pytest.raises(ValueError) as exc:
        _adapter().render(template, params={}, query_text="HELLO")
    msg = str(exc.value)
    assert "title_boost" in msg
    assert "query_normalizer" not in msg


def test_default_fallback_renders_verbatim_when_only_normalizer_declared() -> None:
    # declared_params has ONLY query_normalizer; params empty -> no missing,
    # query_text passes through verbatim (default "none").
    template = _title_match_template({"query_normalizer": "string"})
    native = _adapter().render(template, params={}, query_text="HELLO")
    assert native.body["query"]["match"]["title"] == "HELLO"


def test_invalid_normalizer_value_raises_value_error() -> None:
    template = _title_match_template({"query_normalizer": "string"})
    with pytest.raises(ValueError) as exc:
        _adapter().render(
            template,
            params={"query_normalizer": "stem"},
            query_text="HELLO",
        )
    assert "stem" in str(exc.value)
