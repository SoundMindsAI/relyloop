# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Baseline-trial parameter defaults (feat_study_baseline_trial FR-3).

Pure-domain helpers for the non-Optuna baseline trial's parameter fallback:

1. **Tier (d) — Parent proposal config**: if ``study.parent_proposal_id``
   is set, return the params from the trial that the parent proposal
   would have shipped (``proposal.study_trial_id``).
2. **Tier (c) — Parent study winner**: if ``study.parent_study_id`` is
   set, return the params from the parent study's winning trial
   (``parent.best_trial_id``).
3. **Tier (b) — Operator-supplied**: if ``study.config['baseline_params']``
   is set, return it directly (Pydantic already validated the dict shape
   at create-time per ``CreateStudyRequest`` / ``StudyConfigSpec``).
4. **Tier (a) — Template defaults**: deterministic middle-of-range for
   every declared parameter in ``study.search_space.params``:

   - ``FloatParam`` → ``(low + high) / 2.0`` (geometric mean
     ``sqrt(low * high)`` when ``log=True``).
   - ``IntParam`` → ``(low + high) // 2``.
   - ``CategoricalParam`` → ``choices[(len(choices) - 1) // 2]``
     (lower midpoint for even-cardinality choice lists).

Returns ``None`` only when tier (a) would produce an empty dict. The async DB
lookups for tiers (d) and (c) live in
``backend.app.services.baseline_resolver`` so this module stays pure domain:
no database session, ORM models, repository imports, or I/O.

Spec: ``docs/00_overview/planned_features/feat_study_baseline_trial/feature_spec.md`` §FR-3.
Decision log entries D-2 (4-tier fallback ordering) and D-7
(``baseline_params`` lives in ``studies.config`` JSONB).
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER
from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    NormalizerPipelineParam,
    SearchSpace,
)


class BaselineStudyConfig(Protocol):
    """Study fields required by the pure baseline fallback rules."""

    config: dict[str, Any]
    search_space: dict[str, Any]


def resolve_baseline_params_from_candidates(
    study: BaselineStudyConfig,
    *,
    parent_proposal_params: dict[str, Any] | None = None,
    parent_study_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve baseline-trial params after parent DB candidates are loaded.

    Returns ``None`` only when no tier produced non-empty params (the
    study's search space has no declared params and no parent / operator
    override exists). Returns a non-empty dict otherwise.
    """
    # Tier (d) — parent proposal config.
    if parent_proposal_params:
        return dict(parent_proposal_params)

    # Tier (c) — parent study winner.
    if parent_study_params:
        return dict(parent_study_params)

    # Tier (b) — operator-supplied.
    params = _resolve_from_operator_supplied(study)
    if params is not None:
        return params

    # Tier (a) — template defaults.
    return _resolve_from_template_defaults(study)


def _resolve_from_operator_supplied(study: BaselineStudyConfig) -> dict[str, Any] | None:
    """Tier (b): ``study.config['baseline_params']`` if set + non-empty.

    Pydantic validated the dict[str, primitive] shape at create-time
    (``StudyConfigSpec.baseline_params``); no re-validation here.
    """
    config = study.config or {}
    params = config.get("baseline_params")
    if not isinstance(params, dict) or not params:
        return None
    return dict(params)


def _resolve_from_template_defaults(study: BaselineStudyConfig) -> dict[str, Any] | None:
    """Tier (a): middle-of-range for every declared search-space param.

    Returns ``None`` when the search space has no params (impossible in
    practice — ``SearchSpace.params`` is constrained `min_length=1` by
    Pydantic — but defensive in case future iterations relax that).
    """
    space = SearchSpace.model_validate(study.search_space)
    if not space.params:
        return None

    result: dict[str, Any] = {}
    for name, param in space.params.items():
        result[name] = _midpoint(param)
    return result


def _midpoint(param: FloatParam | IntParam | CategoricalParam | NormalizerPipelineParam) -> Any:
    """Deterministic mid-of-range per parameter kind.

    - ``FloatParam`` with ``log=False``: arithmetic mean ``(low + high) / 2``.
    - ``FloatParam`` with ``log=True``: geometric mean ``sqrt(low * high)``.
    - ``IntParam``: integer division ``(low + high) // 2``.
    - ``CategoricalParam``: ``choices[(len(choices) - 1) // 2]`` (lower
      midpoint for even-cardinality lists).
    - ``NormalizerPipelineParam``: the ``"none"`` label (empty-pipeline /
      un-normalized baseline) — always a member of the param's powerset
      label space, and consistent with ``compute_default_params`` (FR-7).
    """
    if isinstance(param, NormalizerPipelineParam):
        return DEFAULT_NORMALIZER
    if isinstance(param, FloatParam):
        if param.log:
            return math.sqrt(param.low * param.high)
        return (param.low + param.high) / 2.0
    if isinstance(param, IntParam):
        return (param.low + param.high) // 2
    if isinstance(param, CategoricalParam):
        return param.choices[(len(param.choices) - 1) // 2]
    raise TypeError(f"unknown ParamSpec subtype: {type(param)!r}")


__all__ = ["resolve_baseline_params_from_candidates"]
