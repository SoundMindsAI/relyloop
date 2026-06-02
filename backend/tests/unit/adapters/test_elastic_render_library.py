# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Render-validation tests for the ES/OpenSearch library templates
(`chore_template_library_expansion` Story 1.3, FR-6, AC-1).

For each of the four library templates under ``samples/templates/`` that
target both Elasticsearch 8.11+ and OpenSearch 2.x, this suite:

1. Loads the template body + the matching ``.search_space.json``.
2. Asserts the search-space keys EQUAL the declared params used by the
   render (no extra, no missing) — the platform-equality invariant
   enforced by ``backend.app.domain.study.search_space.validate_against_template``.
3. Samples one concrete scalar assignment per parameter (a representative
   value, not the ParamSpec dict itself — FR-6 / AC-1).
4. Calls ``ElasticAdapter.render(template, params, query_text)``.
5. Asserts the native block (`multi_match` / `function_score` / `bool` +
   `minimum_should_match` / `rescore`) is present in the parsed JSON.

The same body is then re-rendered as if ``engine_type='opensearch'`` — the
four library shapes are lexical / function-score / rescore DSL that is
identical and valid on both engines (FR-6 explicit engine-agnostic
assertion).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.protocol import ParamValue, QueryTemplate
from backend.app.core.settings import get_settings
from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    SearchSpace,
    validate_against_template,
)

_TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "samples" / "templates"


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


def _adapter(engine_type: str = "elasticsearch") -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type=engine_type,  # type: ignore[arg-type]
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
    )


def _sample_assignment(space: SearchSpace) -> dict[str, ParamValue]:
    """Pick one concrete scalar per param — first valid value in range / choices.

    Render needs concrete scalars (one float, one int, one categorical
    choice), NOT the ParamSpec dict itself. We pick the first choice for
    categoricals and the low bound for floats / ints — deterministic so the
    test is reproducible.

    Returns a `dict[str, ParamValue]` (the adapter's render() signature
    expects `bool | int | float | str | list[str]`). Categorical bool/None
    choices are not used in the library, so this works out cleanly.
    """
    out: dict[str, ParamValue] = {}
    for name, spec in space.params.items():
        if isinstance(spec, FloatParam):
            # Mid-range — avoid 0.0/0.5 which can produce JSON quirks.
            out[name] = round((spec.low + spec.high) / 2, 3)
        elif isinstance(spec, IntParam):
            out[name] = spec.low
        elif isinstance(spec, CategoricalParam):
            choice = spec.choices[0]
            # SearchSpace permits bool choices but the library doesn't use them;
            # cast keeps mypy happy without runtime conversion.
            assert isinstance(choice, (bool, int, float, str)), (
                f"Unexpected categorical choice type {type(choice).__name__}"
            )
            out[name] = choice
        else:  # pragma: no cover — closed pydantic discriminator union today
            # Defensive: if a new ParamSpec variant is added to SearchSpace
            # in the future, fail loudly rather than silently produce an
            # incomplete assignment that surfaces as a hard-to-debug Jinja
            # `UndefinedError` downstream. Gemini Code Assist finding on
            # PR #416 — accepted.
            raise TypeError(f"Unsupported parameter spec type: {type(spec).__name__}")
    return out


def _load_template_and_space(
    name: str,
) -> tuple[QueryTemplate, SearchSpace, dict[str, str]]:  # noqa: D401
    """Load the .j2 + .search_space.json; build a QueryTemplate.

    ``declared_params`` is derived from the search-space keys (declared and
    search-space must equal exactly per the platform invariant — that is
    test-enforced in :mod:`backend.tests.unit.docs.test_template_library_invariants`).
    The README registration block is the independent source of truth that
    invariant test parses; here we only need *some* declared_params map
    that the render's missing-params check is satisfied with.
    """
    body = (_TEMPLATES_DIR / f"{name}.j2").read_text()
    space_data = json.loads((_TEMPLATES_DIR / f"{name}.search_space.json").read_text())
    space = SearchSpace.model_validate(space_data)
    # `spec.type` is a Literal but `declared_params` accepts plain `str`;
    # widen the value type with `str(...)` so the dict invariance dance
    # mypy demands doesn't bleed into every caller.
    declared_params: dict[str, str] = {key: str(spec.type) for key, spec in space.params.items()}
    template = QueryTemplate(
        name=name,
        engine_type="elasticsearch",
        body=body,
        declared_params=declared_params,
    )
    # Sanity: equality holds. If this fires, the .search_space.json drifted
    # from the template's intent.
    validate_against_template(space, declared_params, name)
    return template, space, declared_params


# ---------------------------------------------------------------------------
# Per-template render cases
# ---------------------------------------------------------------------------


class TestMultiMatchBasic:
    def test_renders_to_native_multi_match(self) -> None:
        template, space, _ = _load_template_and_space("multi_match_basic")
        params = _sample_assignment(space)
        native = _adapter().render(template, params=params, query_text="laptop")
        assert native.query_id == "multi_match_basic"
        block = native.body["query"]["multi_match"]
        assert block["type"] == "best_fields"
        assert block["query"] == "laptop"
        assert "tie_breaker" in block
        # Engine-agnostic structure: no ES-only keys (`retriever`, `rrf`) leak in.
        assert "retriever" not in native.body
        assert "rrf" not in native.body

    def test_renders_identically_on_opensearch(self) -> None:
        template, space, _ = _load_template_and_space("multi_match_basic")
        params = _sample_assignment(space)
        es_body = _adapter("elasticsearch").render(template, params, "laptop").body
        os_body = _adapter("opensearch").render(template, params, "laptop").body
        assert es_body == os_body  # lexical DSL — byte-identical across engines


class TestFunctionScoreDecay:
    def test_renders_to_function_score_with_gauss(self) -> None:
        template, space, _ = _load_template_and_space("function_score_decay")
        params = _sample_assignment(space)
        native = _adapter().render(template, params=params, query_text="phone")
        block = native.body["query"]["function_score"]
        assert "functions" in block
        assert block["functions"][0]["gauss"]["created_at"]
        assert block["boost_mode"] == "multiply"
        # The inner lexical pass is best_fields lexical (engine-agnostic).
        assert block["query"]["multi_match"]["type"] == "best_fields"


class TestBoolBoosted:
    def test_renders_to_bool_with_min_should_match(self) -> None:
        template, space, _ = _load_template_and_space("bool_boosted")
        params = _sample_assignment(space)
        native = _adapter().render(template, params=params, query_text="shoes")
        block = native.body["query"]["bool"]
        assert "must" in block
        assert "should" in block
        # FR-1 names the must/should/filter shape — the filter clause is a
        # baked-in `exists` floor on `title` (GPT-5.5 cycle-3 finding).
        assert "filter" in block
        assert block["filter"][0]["exists"]["field"] == "title"
        assert "minimum_should_match" in block
        # All three field boosts wired through to the should clauses.
        should_fields = {list(c["match"].keys())[0] for c in block["should"]}
        assert should_fields == {"title", "description", "bullet_points"}


class TestRescorePhrase:
    def test_renders_with_rescore_block(self) -> None:
        template, space, _ = _load_template_and_space("rescore_phrase")
        params = _sample_assignment(space)
        native = _adapter().render(template, params=params, query_text="leather sofa")
        # First pass: best_fields lexical.
        assert native.body["query"]["multi_match"]["type"] == "best_fields"
        # Second pass: phrase rescore over the title field.
        rescore = native.body["rescore"]
        assert "window_size" in rescore
        assert rescore["query"]["rescore_query"]["match_phrase"]["title"]["query"] == "leather sofa"
        # phrase_slop is the canonical knob — confirm it landed in the phrase block.
        assert "slop" in rescore["query"]["rescore_query"]["match_phrase"]["title"]


# ---------------------------------------------------------------------------
# Engine-agnostic sweep — one assertion documenting that the 4 ES/OS library
# templates render identically for ES and OpenSearch (lexical / function-score
# / rescore DSL is shared between the two engines).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_name",
    ["multi_match_basic", "function_score_decay", "bool_boosted", "rescore_phrase"],
)
def test_es_and_opensearch_bodies_are_identical(template_name: str) -> None:
    template, space, _ = _load_template_and_space(template_name)
    params = _sample_assignment(space)
    es_body = _adapter("elasticsearch").render(template, params, "widget").body
    os_body = _adapter("opensearch").render(template, params, "widget").body
    assert es_body == os_body, f"{template_name} diverged between ES and OpenSearch"


# ---------------------------------------------------------------------------
# JSON-safety sweep — a query_text containing a double-quote, backslash, or
# newline must still render valid JSON (the templates wrap query_text via the
# Jinja `tojson` filter). GPT-5.5 cycle-3 finding — accepted: a naive
# `"{{ query_text }}"` would break `json.loads` on such input.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_name",
    ["multi_match_basic", "function_score_decay", "bool_boosted", "rescore_phrase"],
)
def test_renders_valid_json_for_query_with_special_chars(template_name: str) -> None:
    template, space, _ = _load_template_and_space(template_name)
    params = _sample_assignment(space)
    # Double-quote + backslash + newline — the canonical JSON-breaking trio.
    nasty = 'a "quoted" \\ value\nwith newline'
    native = _adapter().render(template, params=params, query_text=nasty)
    # render() already json.loads-es internally; reaching here means valid JSON.
    # Confirm the query text round-trips intact somewhere in the body.
    body_str = json.dumps(native.body)
    assert "quoted" in body_str
    # The literal newline survived as an escaped \n in the parsed structure.
    assert "with newline" in body_str
