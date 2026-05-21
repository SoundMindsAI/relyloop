"""Heuristic starter-search-space + ±50% narrowing helpers (feat_agent_propose_search_space).

Python port of ``ui/src/lib/search-space-defaults.ts``. The TS module is the
user-visible heuristic source for the create-study wizard's Step-4 auto-fill;
this Python sibling is consumed by the ``propose_search_space`` agent tool.
The two MUST produce byte-identical output for the same ``declared_params``;
``backend/tests/unit/domain/test_search_space_defaults_parity.py`` (Python half)
and ``ui/src/__tests__/lib/search-space-defaults.parity.test.ts`` (TS half) both
consume ``backend/tests/_fixtures/search_space_defaults_parity.json`` and fail
on any drift.

This module sits side-by-side with
:mod:`backend.app.domain.study.template_defaults` — they serve different
concerns: ``template_defaults.compute_default_params`` picks *single concrete
values* (midpoints, first categorical) for template rendering at digest /
judgment time, while this module picks *ParamSpec ranges* (``{type, low, high,
log}``) for Optuna search bounds. Do not merge or refactor either.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    InvalidSearchSpaceError,
    ParamSpec,
    SearchSpace,
)

logger = logging.getLogger(__name__)


# Naming-convention heuristic table — mirrors the TS source-of-truth at
# ``ui/src/lib/search-space-defaults.ts`` lines 38-55. Names are tested
# top-to-bottom; the first matching rule wins. The TS↔Python parity test
# enforces byte-identical behavior for every fixture row.
HEURISTIC_RULES: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    # field-boost-like (prefix) → log-uniform float in [0.5, 10.0]
    (
        re.compile(r"^(field_boost|boost_)"),
        {"type": "float", "low": 0.5, "high": 10.0, "log": True},
    ),
    # standalone `boost` OR `<field>_boost` suffix — ES multi_match per-field convention.
    (re.compile(r"^(boost|.+_boost)$"), {"type": "float", "low": 0.5, "high": 10.0, "log": True}),
    # tie-breaker / *_weight → uniform float in [0.0, 1.0]
    (re.compile(r"^(tie_breaker|.*_weight)$"), {"type": "float", "low": 0.0, "high": 1.0}),
    # slop / min_should_match / *_size → small int in [0, 5]
    (re.compile(r"^(slop|min_should_match|.*_size)$"), {"type": "int", "low": 0, "high": 5}),
    # fuzziness → categorical AUTO + integer-as-string choices
    (re.compile(r"^fuzziness$"), {"type": "categorical", "choices": ["AUTO", "0", "1", "2"]}),
]


# Fall-through default when no naming-convention rule matches.
_DEFAULT_FALLBACK: dict[str, Any] = {"type": "float", "low": 0.0, "high": 1.0}


def simple_form_spec(type_name: str) -> ParamSpec | None:
    """Simple-form ``declared_params`` value → ParamSpec mapping.

    Only consulted for names that did NOT match :data:`HEURISTIC_RULES`.
    Mirrors TS ``simpleFormSpec`` at ``ui/src/lib/search-space-defaults.ts:73-86``.
    The ``"string"`` case emits a degenerate single-choice categorical with a
    ``__placeholder__`` sentinel; the wizard renders a non-blocking amber
    warning so the user replaces it before submitting.
    """
    if type_name == "int":
        return IntParam(type="int", low=0, high=5)
    if type_name == "float":
        return FloatParam(type="float", low=0.0, high=1.0)
    if type_name == "bool":
        return CategoricalParam(type="categorical", choices=[True, False])
    if type_name == "string":
        return CategoricalParam(type="categorical", choices=["__placeholder__"])
    return None


def estimate_param_cardinality(spec: ParamSpec) -> int:
    """Per-param cardinality contribution — mirrors TS ``estimateParamCardinality``.

    Float counted as 100 (matches the SearchSpace source-of-truth at
    ``backend/app/domain/study/search_space.py:191``); Int counted as
    ``high - low + 1``; Categorical counted as ``len(choices)``.
    """
    if isinstance(spec, FloatParam):
        return 100
    if isinstance(spec, IntParam):
        return max(0, spec.high - spec.low + 1)
    return len(spec.choices)


@dataclass(frozen=True, slots=True)
class StarterSearchSpace:
    """Return type of :func:`build_starter_search_space`.

    Pairs the validated :class:`SearchSpace` with cap-aware-fallback metadata so
    the ``propose_search_space`` agent tool can populate
    ``grounding.cap_aware_fallback_param_names`` without duplicating fallback
    logic at the tool layer.
    """

    space: SearchSpace
    cap_aware_fallback_param_names: list[str]


def _match_heuristic_rule(name: str) -> dict[str, Any] | None:
    for pattern, spec in HEURISTIC_RULES:
        if pattern.match(name):
            return dict(spec)
    return None


def _spec_dict_to_param(spec: dict[str, Any]) -> ParamSpec:
    """Convert a heuristic-rule dict to a concrete Pydantic ParamSpec."""
    if spec["type"] == "float":
        return FloatParam(
            type="float",
            low=spec["low"],
            high=spec["high"],
            log=spec.get("log", False),
        )
    if spec["type"] == "int":
        return IntParam(type="int", low=spec["low"], high=spec["high"])
    return CategoricalParam(type="categorical", choices=list(spec["choices"]))


def _estimate_cardinality_from_dict(params_dict: dict[str, ParamSpec]) -> int:
    """Estimate cardinality from a dict of ParamSpecs — pre-SearchSpace construction."""
    total = 1
    for spec in params_dict.values():
        total *= estimate_param_cardinality(spec)
    return total


def build_starter_search_space(declared_params: dict[str, str]) -> StarterSearchSpace:
    """Build a starter search space from a template's ``declared_params``.

    Heuristic priority (spec FR-1):
      1. Try :data:`HEURISTIC_RULES` (naming convention).
      2. Else fall back to :func:`simple_form_spec` for simple-form types.
      3. Else use :data:`_DEFAULT_FALLBACK` (uniform float 0..1).

    Cap-aware fallback: if the candidate cardinality exceeds 10⁶, narrow it
    by converting float params to ``int[0, 5]`` in priority order — unmatched
    fall-through floats first (lex), then regex-matched floats (lex).
    Emits ``logger.warning`` when the fallback fires.

    Cap-aware overflow guard: if even after converting every float the
    cardinality is still > 10⁶, raises :class:`InvalidSearchSpaceError`.
    The ``propose_search_space`` tool surfaces this as ``HTTPException(400,
    INVALID_SEARCH_SPACE)``.

    Empty ``declared_params``: raises :class:`InvalidSearchSpaceError` (the
    underlying Pydantic ``min_length=1`` failure is caught and re-raised as
    a single exception type so the tool's error mapping is simple).
    """
    if not declared_params:
        raise InvalidSearchSpaceError(
            "empty declared_params: at least one declared param is required"
        )

    params: dict[str, ParamSpec] = {}
    regex_matched: set[str] = set()

    for name, type_name in declared_params.items():
        matched = _match_heuristic_rule(name)
        if matched is not None:
            params[name] = _spec_dict_to_param(matched)
            regex_matched.add(name)
            continue
        simple = simple_form_spec(type_name)
        params[name] = simple if simple is not None else _spec_dict_to_param(_DEFAULT_FALLBACK)

    cap_aware_fallback_param_names: list[str] = []

    if _estimate_cardinality_from_dict(params) > 1_000_000:
        # Cap-aware fallback: convert fall-through floats first (lex), then
        # regex-matched floats (lex), until cardinality ≤ 10⁶.
        fall_through_floats = sorted(
            n for n, p in params.items() if isinstance(p, FloatParam) and n not in regex_matched
        )
        regex_floats = sorted(
            n for n, p in params.items() if isinstance(p, FloatParam) and n in regex_matched
        )
        for name in [*fall_through_floats, *regex_floats]:
            params[name] = IntParam(type="int", low=0, high=5)
            cap_aware_fallback_param_names.append(name)
            if _estimate_cardinality_from_dict(params) <= 1_000_000:
                break

        if cap_aware_fallback_param_names:
            logger.warning(
                "search_space_defaults.cap_aware_fallback fired: "
                "converted=%s reason=cardinality_above_cap",
                cap_aware_fallback_param_names,
            )

        if _estimate_cardinality_from_dict(params) > 1_000_000:
            raise InvalidSearchSpaceError(
                f"cap-aware fallback exhausted: cardinality="
                f"{_estimate_cardinality_from_dict(params)} > 10^6 for "
                f"declared_params={sorted(declared_params.keys())}"
            )

    # Final Pydantic validation — catches anything the per-param construction missed.
    try:
        space = SearchSpace(params=params)
    except ValidationError as exc:
        raise InvalidSearchSpaceError(str(exc)) from exc

    return StarterSearchSpace(
        space=space,
        cap_aware_fallback_param_names=cap_aware_fallback_param_names,
    )


def _narrow_float_bounds(spec: FloatParam, winner: float, bracket: float) -> FloatParam | None:
    """Return the narrowed FloatParam, or None if winner is out of bounds.

    Linear path uses ``winner ± |winner| × bracket`` so negative winners get a
    valid (non-inverted) bracket. The ``abs(winner)`` symmetry was a Gemini
    Code Assist finding on PR #175 — without it, a winner of -2.0 with the
    naive ``winner * 0.5 / winner * 1.5`` formula produces ``new_low=-1.0,
    new_high=-3.0`` which is inverted and gets skipped.

    Log path uses a fixed √2 geometric factor regardless of ``bracket`` — the
    spec FR-3 locks √2 for log-uniform floats because the bracket parameter
    is linear-scale-only; widening or narrowing the log bracket independently
    would require a separate arg in a future revision.
    """
    if winner <= spec.low or winner >= spec.high:
        return None
    if spec.log:
        # Geometric bracket — fixed at √2 per spec FR-3.
        factor = math.sqrt(2.0)
        new_low = max(spec.low, winner / factor)
        new_high = min(spec.high, winner * factor)
    else:
        # Linear bracket — symmetric in absolute value so negatives narrow correctly.
        half_width = abs(winner) * bracket
        new_low = max(spec.low, winner - half_width)
        new_high = min(spec.high, winner + half_width)
    if new_low >= new_high:
        return None
    return FloatParam(type="float", low=new_low, high=new_high, log=spec.log)


def _narrow_int_bounds(spec: IntParam, winner: int, bracket: float) -> IntParam | None:
    """Return the narrowed IntParam, or None if winner is out of bounds.

    Uses ``winner ± |winner| × bracket`` for sign symmetry (see
    :func:`_narrow_float_bounds` for the negative-value Gemini finding).
    """
    if winner <= spec.low or winner >= spec.high:
        return None
    half_width = abs(winner) * bracket
    new_low = max(spec.low, math.floor(winner - half_width))
    new_high = min(spec.high, math.ceil(winner + half_width))
    if new_low > new_high:
        return None
    return IntParam(type="int", low=new_low, high=new_high)


def narrow_bounds_around_winner(
    space: SearchSpace,
    winning_params: dict[str, Any],
    bracket: float = 0.5,
) -> tuple[SearchSpace, list[str]]:
    """Narrow each numeric param's bounds around the prior winner.

    For each ``name`` in ``winning_params`` that also appears in ``space.params``:
    - **FloatParam linear**: new bounds = ``[winner − |winner| × bracket,
      winner + |winner| × bracket]`` clamped to original bounds. Sign-symmetric
      so negative winners narrow correctly. Skipped if winner is at/outside
      original bounds.
    - **FloatParam log-uniform**: geometric bracket using a fixed ``sqrt(2)``
      factor (spec FR-3 — log narrowing doesn't compose linearly with
      ``bracket``; a future revision can expose a separate arg if needed).
      Skipped if winner is at/outside original bounds.
    - **IntParam**: same sign-symmetric ``winner ± |winner| × bracket`` math,
      then ``floor``/``ceil`` clamped to original. Skipped if winner is
      at/outside original bounds.
    - **CategoricalParam**: not narrowed (FR-3 — removing options can hide
      useful signal; the math isn't symmetric with the numeric path).
    - **Non-numeric winner value** (FR-3 type guard): skipped (no exception).

    Returns ``(narrowed_space, narrowed_names)`` where ``narrowed_names`` is
    the sorted list of param names whose bounds were actually changed. FR-4
    invariant: cardinality is **non-increasing** — FloatParam cardinality stays
    at 100 regardless of bound width, and IntParam cardinality can only shrink
    under bracket clamping. Categoricals are untouched.

    The ``bracket`` argument controls the linear narrowing width; spec FR-3
    locks the default at 0.5. The log-uniform geometric factor stays at
    √2 regardless (documented above).
    """
    new_params: dict[str, ParamSpec] = dict(space.params)
    narrowed: list[str] = []

    for name, current_spec in space.params.items():
        if name not in winning_params:
            continue
        winner_value = winning_params[name]
        if isinstance(current_spec, FloatParam):
            if not isinstance(winner_value, (int, float)) or isinstance(winner_value, bool):
                continue
            narrowed_spec = _narrow_float_bounds(current_spec, float(winner_value), bracket)
            if narrowed_spec is None:
                continue
            new_params[name] = narrowed_spec
            narrowed.append(name)
        elif isinstance(current_spec, IntParam):
            if not isinstance(winner_value, int) or isinstance(winner_value, bool):
                continue
            narrowed_spec_int = _narrow_int_bounds(current_spec, winner_value, bracket)
            if narrowed_spec_int is None:
                continue
            new_params[name] = narrowed_spec_int
            narrowed.append(name)
        # CategoricalParam: never narrowed (FR-3).

    if not narrowed:
        return space, []

    return SearchSpace(params=new_params), sorted(narrowed)


__all__ = [
    "HEURISTIC_RULES",
    "StarterSearchSpace",
    "build_starter_search_space",
    "estimate_param_cardinality",
    "narrow_bounds_around_winner",
    "simple_form_spec",
]
