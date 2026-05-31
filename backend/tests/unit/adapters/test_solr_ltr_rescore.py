# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""SolrAdapter LTR rescore unit tests (infra_adapter_solr Story A7, FR-10).

* ``_render_rerank_model`` (already covered by ``test_solr_boost_fn_combine.py``
  + ``test_solr_render.py``) renders ``rerank_model: {id, top_k}`` to
  ``rq={!ltr model=ID reRankDocs=K}``.
* New here: render-time pre-flight validation. When ``engine_config.ltr_models``
  is populated by the capability probe AND the template emits a rerank_model
  whose ``id`` isn't in the list, ``LtrModelNotFoundError`` is raised (which
  the router translates to 400 ``LTR_MODEL_NOT_FOUND``).
* Skip cases: empty / missing ``ltr_models`` (probe didn't run); non-string
  ``id`` (the pivot itself will reject downstream).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import InvalidQueryDSLError, LtrModelNotFoundError
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


def _build(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
    *,
    ltr_models: list[str] | None = None,
) -> SolrAdapter:
    cfg: dict[str, object] | None = None
    if ltr_models is not None:
        cfg = {"ltr_models": ltr_models}
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=cfg,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler or (lambda r: httpx.Response(404)))
        ),
    )


def _rerank_template() -> QueryTemplate:
    return QueryTemplate(
        name="rerank_template",
        engine_type="solr",
        body=(
            '{"defType":"edismax","q":"{{ query_text }}",'
            '"rerank_model": {"id": "{{ model_id }}", "top_k": 100}}'
        ),
        declared_params={"model_id": "string"},
    )


# ---------------------------------------------------------------------------
# rerank_model render output (Solr {!ltr ...} param).
# ---------------------------------------------------------------------------


class TestRerankRenderOutput:
    def test_rerank_renders_to_rq(self) -> None:
        adapter = _build(ltr_models=["xgboost_v1"])
        nq = adapter.render(
            _rerank_template(),
            params={"model_id": "xgboost_v1"},
            query_text="laptop",
        )
        assert nq.body["rq"] == "{!ltr model=xgboost_v1 reRankDocs=100}"


# ---------------------------------------------------------------------------
# Pre-flight check against engine_config.ltr_models.
# ---------------------------------------------------------------------------


class TestPreflightLtrValidation:
    def test_known_model_passes(self) -> None:
        adapter = _build(ltr_models=["xgboost_v1", "lambdamart_v2"])
        nq = adapter.render(
            _rerank_template(),
            params={"model_id": "lambdamart_v2"},
            query_text="x",
        )
        assert "rq" in nq.body

    def test_unknown_model_raises_ltr_model_not_found(self) -> None:
        adapter = _build(ltr_models=["xgboost_v1"])
        with pytest.raises(LtrModelNotFoundError) as exc:
            adapter.render(
                _rerank_template(),
                params={"model_id": "xgboost_v2"},
                query_text="x",
            )
        assert exc.value.model_id == "xgboost_v2"
        assert exc.value.available == ["xgboost_v1"]
        assert "xgboost_v2" in str(exc.value)
        assert "xgboost_v1" in str(exc.value)


# ---------------------------------------------------------------------------
# Skip cases — no LTR models recorded → no validation.
# ---------------------------------------------------------------------------


class TestSkipCases:
    def test_no_ltr_models_in_engine_config_skips_validation(self) -> None:
        """When the capability probe didn't run / failed mid-way, the cluster
        has no ltr_models list. Render should NOT pre-empt with a false-positive
        400; Solr can surface the missing-model error at request time."""
        adapter = _build()  # engine_config=None
        nq = adapter.render(
            _rerank_template(),
            params={"model_id": "anything_v1"},
            query_text="x",
        )
        # Render completed without raising; the rq is present.
        assert "rq" in nq.body

    def test_empty_ltr_models_list_skips_validation(self) -> None:
        adapter = _build(ltr_models=[])
        nq = adapter.render(
            _rerank_template(),
            params={"model_id": "any"},
            query_text="x",
        )
        assert "rq" in nq.body


# ---------------------------------------------------------------------------
# Pivot still rejects malformed rerank_model dicts.
# ---------------------------------------------------------------------------


class TestPivotRejectsMalformed:
    def test_missing_top_k_raises_invalid_query_dsl(self) -> None:
        adapter = _build(ltr_models=["xgboost_v1"])
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"q":"{{ query_text }}","rerank_model": {"id": "xgboost_v1"}}',
            declared_params={},
        )
        with pytest.raises(InvalidQueryDSLError, match="top_k"):
            adapter.render(tpl, params={}, query_text="x")

    def test_empty_id_raises_invalid_query_dsl(self) -> None:
        adapter = _build(ltr_models=["xgboost_v1"])
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"q":"{{ query_text }}","rerank_model": {"id": "", "top_k": 10}}',
            declared_params={},
        )
        with pytest.raises(InvalidQueryDSLError, match="rerank_model.id"):
            adapter.render(tpl, params={}, query_text="x")
