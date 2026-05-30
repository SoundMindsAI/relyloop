# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.render`` unit tests (Story 2.4 / spec §14).

Covers the canonical multi_match + function_score + field_boosts shapes
named in spec §14, plus the missing-required-param error path.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import QueryTemplate
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


def test_multi_match_canonical_template() -> None:
    template = QueryTemplate(
        name="multi_match",
        engine_type="elasticsearch",
        body=(
            '{"query": {"multi_match": {"query": "{{ query_text }}", '
            '"fields": ["title^{{ title_boost }}", "description"]}}}'
        ),
        declared_params={"title_boost": "float"},
    )
    native = _adapter().render(template, params={"title_boost": 2.0}, query_text="shoes")
    assert native.query_id == "multi_match"
    assert native.body == {
        "query": {
            "multi_match": {
                "query": "shoes",
                "fields": ["title^2.0", "description"],
            }
        }
    }


def test_function_score_template() -> None:
    template = QueryTemplate(
        name="function_score",
        engine_type="elasticsearch",
        body=(
            '{"query": {"function_score": {"query": '
            '{"match": {"title": "{{ query_text }}"}}, '
            '"boost": {{ boost_factor }}}}}'
        ),
        declared_params={"boost_factor": "float"},
    )
    native = _adapter().render(template, params={"boost_factor": 1.5}, query_text="shoes")
    assert native.body["query"]["function_score"]["boost"] == 1.5
    assert native.body["query"]["function_score"]["query"]["match"]["title"] == "shoes"


def test_missing_required_param_raises() -> None:
    template = QueryTemplate(
        name="needs_param",
        engine_type="elasticsearch",
        body='{"query": {"match": {"title": "{{ query_text }}"}}}',
        declared_params={"required_field": "string"},
    )
    with pytest.raises(ValueError, match="missing required template params"):
        _adapter().render(template, params={}, query_text="shoes")


def test_undefined_param_in_jinja_raises_value_error() -> None:
    """StrictUndefined surfaces as Jinja UndefinedError; adapter wraps as ValueError."""
    template = QueryTemplate(
        name="t",
        engine_type="elasticsearch",
        # Template references {{ extra }} but declared_params doesn't list it,
        # so the missing-required check passes — we exercise the StrictUndefined
        # path inside the renderer.
        body='{"q": "{{ extra }}"}',
        declared_params={},
    )
    with pytest.raises(ValueError, match="undefined parameter"):
        _adapter().render(template, params={}, query_text="shoes")
