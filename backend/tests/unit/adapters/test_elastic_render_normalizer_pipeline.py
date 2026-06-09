# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.render`` generalized hook — bundle OR pipeline label.

feat_query_normalizer_typed_pipeline Story 1.4: the pre-render hook now
resolves ANY query_normalizer value through ``steps_for_label`` →
``normalize_pipeline``, so a winning non-bundle powerset label (e.g.
``"lowercase+strip_punctuation"``) applies correctly instead of raising.
Covers the pipeline-label render, bundle back-compat through the new path,
smart-quote (FR-3), and caller-dict immutability (I-5).
"""

from __future__ import annotations

import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import ParamValue, QueryTemplate
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


def _adapter() -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
    )


def _template() -> QueryTemplate:
    return QueryTemplate(
        name="title_match",
        engine_type="elasticsearch",
        body='{"query": {"match": {"title": "{{ query_text }}"}}}',
        declared_params={"query_normalizer": "string"},
    )


def _rendered(query_text: str, label: str) -> str:
    native = _adapter().render(
        _template(), params={"query_normalizer": label}, query_text=query_text
    )
    return native.body["query"]["match"]["title"]


def test_non_bundle_pipeline_label_applies() -> None:
    # "lowercase+strip_punctuation" is NOT a Phase-1 bundle; the old hook
    # would have raised. It must now resolve and apply.
    label = "lowercase+strip_punctuation"
    out = _rendered("Hello, WORLD!!", label)
    assert out == normalize_pipeline("Hello, WORLD!!", steps_for_label(label)) == "hello world"


def test_bundle_label_back_compat_through_new_path() -> None:
    out = _rendered("What's the BEST policy?", "lowercase+trim+expand_contractions")
    assert out == "what is the best policy?"


def test_smart_quote_label_expands() -> None:
    out = _rendered("What’s up", "lowercase+trim+expand_contractions")
    assert out == "what is up"


def test_none_label_is_verbatim() -> None:
    assert _rendered("HELLO World", "none") == "HELLO World"


def test_caller_params_dict_unmutated_with_pipeline_label() -> None:
    params: dict[str, ParamValue] = {"query_normalizer": "lowercase+strip_punctuation"}
    _adapter().render(_template(), params=params, query_text="Hi, there!")
    assert params == {"query_normalizer": "lowercase+strip_punctuation"}


def test_unknown_label_token_raises_value_error() -> None:
    with pytest.raises(ValueError, match="stem"):
        _rendered("HELLO", "lowercase+stem")
