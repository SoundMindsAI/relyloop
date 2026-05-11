"""Unit tests for :func:`backend.workers.judgments._compute_default_params`
(feat_llm_judgments Story 2.1; addresses GPT-5.5 cycle 2 F2).

The worker picks "default params" for the template before running
``adapter.search_batch`` to seed the per-query top-K. The policy mirrors
common defaults: midpoint for numeric ranges, first option for
categoricals, ``False`` for booleans. Templates whose ``declared_params``
omit a param's required-by-spec key fall back to "param absent" so the
template's own ``{% if ... %}`` fallback applies.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.workers.judgments import _compute_default_params


def _template(declared: dict[str, object]) -> object:
    return SimpleNamespace(declared_params=declared)


def test_int_range_returns_midpoint() -> None:
    template = _template({"k1": {"type": "int", "min": 0, "max": 10}})
    assert _compute_default_params(template) == {"k1": 5}


def test_float_range_returns_midpoint_as_float() -> None:
    template = _template({"bm25_b": {"type": "float", "min": 0.5, "max": 1.5}})
    params = _compute_default_params(template)
    assert params == {"bm25_b": 1.0}
    assert isinstance(params["bm25_b"], float)


def test_bool_returns_false() -> None:
    template = _template({"use_phrase": {"type": "bool"}})
    assert _compute_default_params(template) == {"use_phrase": False}


def test_categorical_returns_first_value() -> None:
    template = _template({"operator": {"type": "categorical", "values": ["AND", "OR"]}})
    assert _compute_default_params(template) == {"operator": "AND"}


def test_empty_declared_params_returns_empty_dict() -> None:
    assert _compute_default_params(_template({})) == {}


def test_none_declared_params_returns_empty_dict() -> None:
    """A template with no declared_params (NULL JSONB) doesn't crash."""
    assert _compute_default_params(_template(None)) == {}  # type: ignore[arg-type]


def test_missing_range_bounds_skipped() -> None:
    """A malformed declared_params entry without min/max is skipped, not
    midpointed against ``None``."""
    template = _template({"odd": {"type": "int"}})
    assert _compute_default_params(template) == {}


def test_categorical_empty_values_skipped() -> None:
    template = _template({"choice": {"type": "categorical", "values": []}})
    assert _compute_default_params(template) == {}


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
    params = _compute_default_params(template)
    assert params == {
        "k1": 5,
        "bm25_b": 0.5,
        "use_phrase": False,
        "operator": "AND",
    }
