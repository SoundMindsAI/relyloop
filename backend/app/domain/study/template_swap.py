"""Cross-template ``search_space`` remap helper for ``swap_template`` followups.

Owner: ``feat_digest_executable_followups_swap_template`` (Tier B).

Pure-domain module (no I/O, no async, no DB). The digest worker calls
:func:`remap_search_space_for_swap_target` after parsing each
``SwapTemplateFollowup`` to merge:

- The LLM-proposed bounds (``llm_search_space``) for params declared by BOTH
  the parent template AND the swap target — the "trusted intersection."
- Heuristic defaults from
  :func:`backend.app.domain.study.search_space_defaults.build_starter_search_space`
  for any swap-target params NOT covered by the trusted intersection — the
  "disjoint fill."

It raises :class:`backend.app.domain.study.search_space.InvalidSearchSpaceError`
(re-using the existing error type so the worker's exception handler is
uniform) when:

- The swap target declares no params.
- The trusted intersection is empty (no shared params with LLM bounds).
- :func:`build_starter_search_space` exhausts its cap-aware fallback on the
  disjoint set.
- The final merged :class:`~backend.app.domain.study.search_space.SearchSpace`
  fails Pydantic cardinality-cap validation.

Spec:
``docs/02_product/planned_features/feat_digest_executable_followups_swap_template/feature_spec.md``
(FR-3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from backend.app.domain.study.search_space import (
    InvalidSearchSpaceError,
    ParamSpec,
    SearchSpace,
)
from backend.app.domain.study.search_space_defaults import (
    build_starter_search_space,
)


@dataclass(frozen=True, slots=True)
class RemapResult:
    """Output of :func:`remap_search_space_for_swap_target`.

    All four name lists are sorted ascending so the worker's INFO log
    + the unit-test assertions are deterministic.
    """

    search_space: SearchSpace
    trusted_intersection_param_names: list[str]
    disjoint_fill_param_names: list[str]
    dropped_parent_param_names: list[str]
    ignored_llm_param_names: list[str]


def remap_search_space_for_swap_target(
    *,
    parent_declared_params: Mapping[str, str],
    swap_target_declared_params: Mapping[str, str],
    llm_search_space: SearchSpace,
) -> RemapResult:
    r"""Compute the merged ``SearchSpace`` for a ``swap_template`` followup.

    Set algebra (param-name keys):

    - ``trusted_intersection = parent ∩ swap ∩ llm`` — bounds copied from
      ``llm_search_space``.
    - ``disjoint_fill        = swap \ (parent ∩ llm)`` — bounds from
      :func:`build_starter_search_space`.
    - ``dropped_parent       = parent \ swap``  — diagnostic only.
    - ``ignored_llm          = llm    \ (parent ∩ swap)`` — diagnostic only.

    Raises:
        InvalidSearchSpaceError: when the swap target declares no params,
            when the trusted intersection is empty, when ``build_starter_search_space``
            exhausts its cap-aware fallback on the disjoint set, or when the
            final merged ``SearchSpace`` fails Pydantic cardinality-cap
            validation.
    """
    if not swap_target_declared_params:
        raise InvalidSearchSpaceError("swap_template target template declares no params")

    parent_names = set(parent_declared_params.keys())
    swap_names = set(swap_target_declared_params.keys())
    llm_names = set(llm_search_space.params.keys())

    trusted_intersection_names = parent_names & swap_names & llm_names
    if not trusted_intersection_names:
        raise InvalidSearchSpaceError("swap_template has no shared parameters with parent template")

    # Disjoint fill = swap params NOT in the parent∩llm intersection.
    # (Per spec FR-3 step 3: a swap param the LLM forgot about — even if
    # the parent declares it — still falls to heuristic defaults because
    # there is no trusted LLM bound for it.)
    disjoint_fill_names = swap_names - (parent_names & llm_names)
    dropped_parent_names = parent_names - swap_names
    ignored_llm_names = llm_names - (parent_names & swap_names)

    merged_params: dict[str, ParamSpec] = {}

    # 1) Trusted intersection — copy LLM bounds verbatim.
    for name in trusted_intersection_names:
        merged_params[name] = llm_search_space.params[name]

    # 2) Disjoint fill — only call the heuristic helper when there is
    # actually something to fill. Per spec D-18 / cycle-1 F2 regression
    # guard: when every swap-target param is in the trusted intersection,
    # we MUST NOT invoke build_starter_search_space (it raises on empty
    # input). Filter the declared_params Mapping down to the disjoint
    # subset to keep the helper's heuristic inputs minimal.
    if disjoint_fill_names:
        disjoint_declared_params = {
            name: swap_target_declared_params[name] for name in disjoint_fill_names
        }
        try:
            starter = build_starter_search_space(disjoint_declared_params)
        except InvalidSearchSpaceError:
            raise
        for name, spec in starter.space.params.items():
            merged_params[name] = spec

    # 3) Final Pydantic validation — surfaces cardinality-cap blowups +
    # any other constructor-time check failures as InvalidSearchSpaceError
    # so the worker's single except block handles both raise sites.
    # Sort merged_params keys before constructing so the resulting
    # SearchSpace has a deterministic parameter order (per Gemini PR #232
    # feedback — mirrors the deterministic-ordering contract documented
    # on RemapResult itself; Python 3.7+ dicts preserve insertion order).
    try:
        merged_space = SearchSpace(params={k: merged_params[k] for k in sorted(merged_params)})
    except ValidationError as exc:
        raise InvalidSearchSpaceError(str(exc)) from exc

    return RemapResult(
        search_space=merged_space,
        trusted_intersection_param_names=sorted(trusted_intersection_names),
        disjoint_fill_param_names=sorted(disjoint_fill_names),
        dropped_parent_param_names=sorted(dropped_parent_names),
        ignored_llm_param_names=sorted(ignored_llm_names),
    )


__all__ = [
    "RemapResult",
    "remap_search_space_for_swap_target",
]
