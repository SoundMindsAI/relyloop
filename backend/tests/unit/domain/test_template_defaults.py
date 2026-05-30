# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :func:`backend.app.domain.study.template_defaults.compute_default_params`.

Originally inlined as ``backend.workers.judgments._compute_default_params``
(feat_llm_judgments Story 2.1; addresses GPT-5.5 cycle 2 F2). Lifted to
the shared domain module by feat_digest_proposal Story 2.1 so both the
judgments worker and the digest worker consume the same policy.

The worker picks "default params" for the template before running
``adapter.search_batch`` to seed the per-query top-K. The policy mirrors
common defaults: midpoint for numeric ranges, first option for
categoricals, ``False`` for booleans. Templates whose ``declared_params``
omit a param's required-by-spec key fall back to "param absent" so the
template's own ``{% if ... %}`` fallback applies.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.domain.study.template_defaults import compute_default_params


def _template(declared: dict[str, object]) -> object:
    return SimpleNamespace(declared_params=declared)


def test_int_range_returns_midpoint() -> None:
    template = _template({"k1": {"type": "int", "min": 0, "max": 10}})
    assert compute_default_params(template) == {"k1": 5}


def test_float_range_returns_midpoint_as_float() -> None:
    template = _template({"bm25_b": {"type": "float", "min": 0.5, "max": 1.5}})
    params = compute_default_params(template)
    assert params == {"bm25_b": 1.0}
    assert isinstance(params["bm25_b"], float)


def test_bool_returns_false() -> None:
    template = _template({"use_phrase": {"type": "bool"}})
    assert compute_default_params(template) == {"use_phrase": False}


def test_categorical_returns_first_value() -> None:
    template = _template({"operator": {"type": "categorical", "values": ["AND", "OR"]}})
    assert compute_default_params(template) == {"operator": "AND"}


def test_empty_declared_params_returns_empty_dict() -> None:
    assert compute_default_params(_template({})) == {}


def test_none_declared_params_returns_empty_dict() -> None:
    """A template with no declared_params (NULL JSONB) doesn't crash."""
    assert compute_default_params(_template(None)) == {}  # type: ignore[arg-type]


def test_missing_range_bounds_skipped() -> None:
    """A malformed declared_params entry without min/max is skipped, not
    midpointed against ``None``."""
    template = _template({"odd": {"type": "int"}})
    assert compute_default_params(template) == {}


def test_categorical_empty_values_skipped() -> None:
    template = _template({"choice": {"type": "categorical", "values": []}})
    assert compute_default_params(template) == {}


def test_mixed_param_types_resolve_independently() -> None:
    template = _template(
        {
            "k1": {"type": "int", "min": 1, "max": 9},
            "bm25_b": {"type": "float", "min": 0.0, "max": 1.0},
            "use_phrase": {"type": "bool"},
            "operator": {"type": "categorical", "values": ["AND", "OR"]},
            "unsupported": {"type": "regex", "pattern": ".*"},
        }
    )
    params = compute_default_params(template)
    assert params == {
        "k1": 5,
        "bm25_b": 0.5,
        "use_phrase": False,
        "operator": "AND",
    }


# Simple-form (`dict[str, str]`) regression tests for
# bug_judgment_template_default_params_contract. The
# `query_templates` API stores declared_params as
# `{name: type_name_string}`; without a fallback, `adapter.render`
# raised `missing required template params` for every API-created
# template that declared any params.


def test_simple_form_float_returns_neutral_fallback() -> None:
    template = _template({"title_boost": "float"})
    params = compute_default_params(template)
    assert params == {"title_boost": 1.0}
    assert isinstance(params["title_boost"], float)


def test_simple_form_int_returns_one() -> None:
    template = _template({"max_clauses": "int"})
    assert compute_default_params(template) == {"max_clauses": 1}


def test_simple_form_bool_returns_false() -> None:
    template = _template({"use_phrase": "bool"})
    assert compute_default_params(template) == {"use_phrase": False}


def test_simple_form_string_returns_empty_string() -> None:
    template = _template({"filter_field": "string"})
    assert compute_default_params(template) == {"filter_field": ""}


def test_simple_form_unknown_type_skipped() -> None:
    """Unrecognized simple-form type-names are omitted so the template's own
    Jinja fallback applies, matching the rich-form malformed-entry policy."""
    template = _template({"weird": "regex"})
    assert compute_default_params(template) == {}


def test_simple_form_mixed_with_rich_form_resolves_independently() -> None:
    """Templates whose declared_params mixes both shapes (test fixtures
    or hand-edited rows) resolve each entry under the matching policy."""
    template = _template(
        {
            "title_boost": "float",  # simple
            "k1": {"type": "int", "min": 1, "max": 9},  # rich
            "use_phrase": "bool",  # simple
        }
    )
    assert compute_default_params(template) == {
        "title_boost": 1.0,
        "k1": 5,
        "use_phrase": False,
    }
