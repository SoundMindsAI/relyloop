# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.render`` unit tests (infra_adapter_solr Story A2, FR-4).

Render outputs a Solr request-parameter dict. The Jinja template body may
emit Solr-native keys (``defType``, ``q``, ``qf``, ``pf``, ``tie``, ``mm``,
``ps``, ``bf``, ``boost``, ``rq``, ``fl``, ``rows``, ``start``, ``sort``,
``fq``, ...) directly, OR unified keys (``field_boosts``, ``phrase_field_boosts``,
``tie_breaker``, ``min_should_match``, ``slop``, ``boost_fn``,
``rerank_model``) that ``render`` pivots into the Solr native equivalents
per the cross-engine parameter map in ``docs/01_architecture/adapters.md``.

Unrecognized keys raise ``InvalidQueryDSLError`` — ``fuzziness`` is
explicitly called out because it's the canonical ES-only param that has
no Solr edismax equivalent (handled via the ``~`` operator in the query
body instead).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.app.adapters.errors import InvalidQueryDSLError
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
    # Sync test; aclose is async — but the MockTransport client has no
    # outstanding sockets. Skipping aclose here is fine for unit-test scope.


# ---------------------------------------------------------------------------
# Sample-template rendering — proves the checked-in templates parse + pivot
# correctly. These templates are consumed by the demo seeding (A13) and the
# tutorial Path C (A12), so render-time errors here would break the demo.
# ---------------------------------------------------------------------------


def _solr_template(name: str, declared_params: dict[str, str]) -> QueryTemplate:
    body = (
        Path(__file__).resolve().parents[4] / f"samples/templates/solr/products_{name}.j2"
    ).read_text()
    return QueryTemplate(
        name=f"products_{name}",
        engine_type="solr",
        body=body,
        declared_params=declared_params,
    )


class TestSampleTemplates:
    def test_edismax_template_renders(self, adapter) -> None:
        tpl = _solr_template(
            "edismax",
            declared_params={
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "float",
                "tie": "float",
                "mm": "string",
            },
        )
        nq = adapter.render(
            tpl,
            params={
                "title_boost": 2.0,
                "description_boost": 1.0,
                "bullet_points_boost": 0.5,
                "tie": 0.3,
                "mm": "2<-25% 9<-3",
            },
            query_text="laptop",
        )
        assert nq.query_id == "products_edismax"
        assert nq.body["defType"] == "edismax"
        assert nq.body["q"] == "laptop"
        # field_boosts pivoted to qf with space-joined order preserved.
        assert nq.body["qf"] == "title^2.0 description^1.0 bullet_points^0.5"
        # tie_breaker pivoted to tie; format preserves the float.
        assert nq.body["tie"] == "0.3"
        # min_should_match arithmetic syntax preserved verbatim.
        assert nq.body["mm"] == "2<-25% 9<-3"
        assert nq.body["fl"] == "*,score"

    def test_dismax_template_renders(self, adapter) -> None:
        tpl = _solr_template(
            "dismax",
            declared_params={
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "float",
                "tie": "float",
                "mm": "string",
            },
        )
        nq = adapter.render(
            tpl,
            params={
                "title_boost": 3.0,
                "description_boost": 1.5,
                "bullet_points_boost": 0.8,
                "tie": 0.1,
                "mm": "75%",
            },
            query_text="phone",
        )
        assert nq.body["defType"] == "dismax"
        assert nq.body["qf"] == "title^3.0 description^1.5 bullet_points^0.8"
        assert nq.body["mm"] == "75%"

    def test_lucene_template_renders(self, adapter) -> None:
        tpl = _solr_template("lucene", declared_params={"field_query": "string"})
        nq = adapter.render(
            tpl,
            params={"field_query": "title:phone description:phone"},
            query_text="phone",  # unused by lucene template; still present in context
        )
        assert nq.body["defType"] == "lucene"
        assert nq.body["q"] == "title:phone description:phone"
        assert "qf" not in nq.body
        assert "tie" not in nq.body


# ---------------------------------------------------------------------------
# Library templates (chore_template_library_expansion Story 1.3, FR-6) — the
# Solr ``edismax_basic.j2`` and ``boost_decay.j2`` library templates live
# directly under ``samples/templates/solr/`` (not under ``products_*`` like
# the demo trio) and pair with a checked-in ``<name>.search_space.json``.
# ---------------------------------------------------------------------------


def _solr_library_template(name: str, declared_params: dict[str, str]) -> QueryTemplate:
    """Like ``_solr_template`` but reads ``samples/templates/solr/<name>.j2``
    rather than the ``products_<name>.j2`` demo path."""
    body = (Path(__file__).resolve().parents[4] / f"samples/templates/solr/{name}.j2").read_text()
    return QueryTemplate(
        name=name,
        engine_type="solr",
        body=body,
        declared_params=declared_params,
    )


class TestSolrLibraryTemplates:
    def test_edismax_basic_renders(self, adapter) -> None:
        tpl = _solr_library_template(
            "edismax_basic",
            declared_params={
                "title_boost": "float",
                "description_boost": "categorical",
                "bullet_points_boost": "categorical",
                "tie": "categorical",
                "mm": "categorical",
                "ps": "int",
            },
        )
        nq = adapter.render(
            tpl,
            params={
                "title_boost": 2.0,
                "description_boost": 1.0,
                "bullet_points_boost": 0.5,
                "tie": 0.3,
                "mm": "75%",
                "ps": 2,
            },
            query_text="laptop",
        )
        assert nq.body["defType"] == "edismax"
        assert nq.body["q"] == "laptop"
        # field_boosts → qf (post-pivot, space-joined, source-order preserved).
        assert nq.body["qf"] == "title^2.0 description^1.0 bullet_points^0.5"
        # `pf` is baked in (literal) so the declared-tunable `ps` (phrase slop)
        # actually has phrase queries to act on (spec FR-2 / Gemini fix).
        assert nq.body["pf"] == "title description"
        assert nq.body["tie"] == "0.3"
        assert nq.body["mm"] == "75%"
        # slop → ps pivot.
        assert nq.body["ps"] == "2"
        assert nq.body["fl"] == "*,score"

    def test_boost_decay_renders_with_bf(self, adapter) -> None:
        tpl = _solr_library_template(
            "boost_decay",
            declared_params={
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "categorical",
                "boost_weight": "categorical",
                "decay_scale": "categorical",
            },
        )
        nq = adapter.render(
            tpl,
            params={
                "title_boost": 2.0,
                "description_boost": 1.0,
                "bullet_points_boost": 0.5,
                "boost_weight": 1.0,
                "decay_scale": "3e-11",
            },
            query_text="laptop",
        )
        assert nq.body["defType"] == "edismax"
        # field_boosts → qf.
        assert nq.body["qf"] == "title^2.0 description^1.0 bullet_points^0.5"
        # The bf string scales a 0→1 recip() decay curve by boost_weight via
        # product(...) so the max additive boost (at age 0) equals boost_weight.
        # m = decay_scale (string); recip numerator/denominator are fixed at 1.
        assert nq.body["bf"] == "product(1.0,recip(ms(NOW,created_at),3e-11,1,1))"


# ---------------------------------------------------------------------------
# Pivot helpers — individual coverage so a broken pivot surfaces in isolation.
# ---------------------------------------------------------------------------


class TestQfPivot:
    def test_basic(self) -> None:
        key, value = SolrAdapter._render_qf({"title": 2.0, "description": 1.0})
        assert key == "qf"
        assert value == "title^2.0 description^1.0"

    def test_int_boost_no_decimal_point(self) -> None:
        key, value = SolrAdapter._render_qf({"title": 2})
        assert value == "title^2"

    def test_preserves_insertion_order(self) -> None:
        # The Jinja template emits dict in source order; the pivot must
        # not re-sort — operators may intentionally place the strongest
        # boost first for documentation purposes (Solr semantics are order-
        # independent but the wire form should match the template).
        key, value = SolrAdapter._render_qf({"zzz": 1, "aaa": 2})
        assert value == "zzz^1 aaa^2"

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be a dict"):
            SolrAdapter._render_qf("title^2 description^1")

    def test_non_numeric_boost_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be a number"):
            SolrAdapter._render_qf({"title": "two"})

    def test_none_boost_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="missing boost"):
            SolrAdapter._render_qf({"title": None})


class TestPfPivot:
    def test_basic(self) -> None:
        key, value = SolrAdapter._render_pf({"title": 4.0, "description": 2.0})
        assert key == "pf"
        assert value == "title^4.0 description^2.0"

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be a dict"):
            SolrAdapter._render_pf([])


class TestTiePivot:
    def test_float(self) -> None:
        key, value = SolrAdapter._render_tie(0.3)
        assert (key, value) == ("tie", "0.3")

    def test_int(self) -> None:
        key, value = SolrAdapter._render_tie(0)
        assert (key, value) == ("tie", "0")

    def test_string_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be a number"):
            SolrAdapter._render_tie("0.3")


class TestPsPivot:
    def test_int(self) -> None:
        assert SolrAdapter._render_ps(2) == ("ps", "2")

    def test_float_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be an int"):
            SolrAdapter._render_ps(2.0)


# ---------------------------------------------------------------------------
# render() top-level: unknown keys raise; fuzziness gets a custom message.
# ---------------------------------------------------------------------------


class TestRenderRejectsUnknownKeys:
    def test_fuzziness_has_custom_message(self, adapter) -> None:
        tpl = QueryTemplate(
            name="bad",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ query_text }}","fuzziness":"AUTO"}',
            declared_params={},
        )
        with pytest.raises(InvalidQueryDSLError, match="'~' operator"):
            adapter.render(tpl, params={}, query_text="laptop")

    def test_unknown_key_lists_valid_options(self, adapter) -> None:
        tpl = QueryTemplate(
            name="bad",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ query_text }}","banana":"yes"}',
            declared_params={},
        )
        with pytest.raises(InvalidQueryDSLError, match="banana") as exc:
            adapter.render(tpl, params={}, query_text="laptop")
        msg = str(exc.value)
        assert "field_boosts" in msg
        assert "rerank_model" in msg

    def test_missing_required_param_raises_value_error(self, adapter) -> None:
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ q }}"}',
            declared_params={"missing_param": "string"},
        )
        with pytest.raises(ValueError, match="missing required template params"):
            adapter.render(tpl, params={}, query_text="laptop")

    def test_undefined_jinja_var_raises_value_error(self, adapter) -> None:
        # Strict undefined: referencing a param not in declared_params and
        # not in params still surfaces as ValueError (the catch site wraps
        # UndefinedError).
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ not_provided }}"}',
            declared_params={},
        )
        with pytest.raises(ValueError, match="undefined parameter"):
            adapter.render(tpl, params={}, query_text="laptop")


# ---------------------------------------------------------------------------
# Native pass-through — values are coerced to strings (Solr URL params).
# ---------------------------------------------------------------------------


class TestNativeParamPassThrough:
    def test_rows_int_coerced_to_string(self, adapter) -> None:
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ query_text }}","rows":10}',
            declared_params={},
        )
        body = adapter.render(tpl, params={}, query_text="laptop").body
        assert body["rows"] == "10"

    def test_fl_string_passthrough(self, adapter) -> None:
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body='{"defType":"edismax","q":"{{ query_text }}","fl":"id,score,title"}',
            declared_params={},
        )
        body = adapter.render(tpl, params={}, query_text="laptop").body
        assert body["fl"] == "id,score,title"

    def test_fq_repeated_list_preserved(self, adapter) -> None:
        tpl = QueryTemplate(
            name="t",
            engine_type="solr",
            body=(
                '{"defType":"edismax","q":"{{ query_text }}",'
                '"fq":["category:laptops","price:[100 TO 1000]"]}'
            ),
            declared_params={},
        )
        body = adapter.render(tpl, params={}, query_text="laptop").body
        assert body["fq"] == ["category:laptops", "price:[100 TO 1000]"]
