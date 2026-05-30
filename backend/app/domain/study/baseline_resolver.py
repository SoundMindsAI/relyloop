# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Baseline-trial parameter resolver (feat_study_baseline_trial FR-3).

Pure-domain async helper that resolves the parameter dict for the
non-Optuna baseline trial via a 4-tier fallback:

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

Returns ``None`` only when tier (a) would produce an empty dict (the
search space has no declared params), in which case the orchestrator
skips the baseline trial entirely (see :func:`backend.workers.
orchestrator._resolve_and_enqueue_baseline`).

The function is async because tiers (d) and (c) hit the DB to load
parent rows. It performs NO writes — pure read + compute.

Spec: ``docs/00_overview/planned_features/feat_study_baseline_trial/feature_spec.md`` §FR-3.
Decision log entries D-2 (4-tier fallback ordering) and D-7
(``baseline_params`` lives in ``studies.config`` JSONB).
"""

from __future__ import annotations

import math
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.domain.study.search_space import (
    CategoricalParam,
    FloatParam,
    IntParam,
    SearchSpace,
)

logger = structlog.get_logger(__name__)


async def resolve_baseline_params(
    db: AsyncSession,
    study: Study,
) -> dict[str, Any] | None:
    """Resolve baseline-trial params via the FR-3 4-tier fallback.

    Returns ``None`` only when no tier produced non-empty params (the
    study's search space has no declared params and no parent / operator
    override exists). Returns a non-empty dict otherwise.

    Logged structured events on fall-through:

    - ``baseline_resolve_parent_proposal_missing`` — tier (d) fell through
      because the parent proposal's referenced trial is missing.
    - ``baseline_resolve_parent_study_missing`` — tier (c) fell through
      because the parent study or its best trial is missing.
    """
    # Tier (d) — parent proposal config.
    if study.parent_proposal_id is not None:
        params = await _resolve_from_parent_proposal(db, study.parent_proposal_id)
        if params is not None:
            return params

    # Tier (c) — parent study winner.
    if study.parent_study_id is not None:
        params = await _resolve_from_parent_study(db, study.parent_study_id)
        if params is not None:
            return params

    # Tier (b) — operator-supplied.
    params = _resolve_from_operator_supplied(study)
    if params is not None:
        return params

    # Tier (a) — template defaults.
    return _resolve_from_template_defaults(study)


async def _resolve_from_parent_proposal(
    db: AsyncSession,
    parent_proposal_id: str,
) -> dict[str, Any] | None:
    """Tier (d): the parent proposal's ``study_trial_id`` is the baseline.

    Returns ``None`` when the proposal or its referenced trial is missing
    or has no params (cascade-delete race; treat as fall-through).
    """
    proposal = await repo.get_proposal(db, parent_proposal_id)
    if proposal is None or proposal.study_trial_id is None:
        logger.info(
            "baseline_resolve_parent_proposal_missing",
            event_type="baseline_resolve_parent_proposal_missing",
            parent_proposal_id=parent_proposal_id,
            reason="proposal_or_study_trial_id_missing",
        )
        return None
    trial = await repo.get_trial(db, proposal.study_trial_id)
    if trial is None or not trial.params:
        logger.info(
            "baseline_resolve_parent_proposal_missing",
            event_type="baseline_resolve_parent_proposal_missing",
            parent_proposal_id=parent_proposal_id,
            study_trial_id=proposal.study_trial_id,
            reason="trial_missing_or_empty_params",
        )
        return None
    return dict(trial.params)


async def _resolve_from_parent_study(
    db: AsyncSession,
    parent_study_id: str,
) -> dict[str, Any] | None:
    """Tier (c): the parent study's ``best_trial_id`` is the baseline."""
    parent = await repo.get_study(db, parent_study_id)
    if parent is None or parent.best_trial_id is None:
        logger.info(
            "baseline_resolve_parent_study_missing",
            event_type="baseline_resolve_parent_study_missing",
            parent_study_id=parent_study_id,
            reason="parent_or_best_trial_id_missing",
        )
        return None
    trial = await repo.get_trial(db, parent.best_trial_id)
    if trial is None or not trial.params:
        logger.info(
            "baseline_resolve_parent_study_missing",
            event_type="baseline_resolve_parent_study_missing",
            parent_study_id=parent_study_id,
            best_trial_id=parent.best_trial_id,
            reason="trial_missing_or_empty_params",
        )
        return None
    return dict(trial.params)


def _resolve_from_operator_supplied(study: Study) -> dict[str, Any] | None:
    """Tier (b): ``study.config['baseline_params']`` if set + non-empty.

    Pydantic validated the dict[str, primitive] shape at create-time
    (``StudyConfigSpec.baseline_params``); no re-validation here.
    """
    config = study.config or {}
    params = config.get("baseline_params")
    if not isinstance(params, dict) or not params:
        return None
    return dict(params)


def _resolve_from_template_defaults(study: Study) -> dict[str, Any] | None:
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


def _midpoint(param: FloatParam | IntParam | CategoricalParam) -> Any:
    """Deterministic mid-of-range per parameter kind.

    - ``FloatParam`` with ``log=False``: arithmetic mean ``(low + high) / 2``.
    - ``FloatParam`` with ``log=True``: geometric mean ``sqrt(low * high)``.
    - ``IntParam``: integer division ``(low + high) // 2``.
    - ``CategoricalParam``: ``choices[(len(choices) - 1) // 2]`` (lower
      midpoint for even-cardinality lists).
    """
    if isinstance(param, FloatParam):
        if param.log:
            return math.sqrt(param.low * param.high)
        return (param.low + param.high) / 2.0
    if isinstance(param, IntParam):
        return (param.low + param.high) // 2
    if isinstance(param, CategoricalParam):
        return param.choices[(len(param.choices) - 1) // 2]
    raise TypeError(f"unknown ParamSpec subtype: {type(param)!r}")


__all__ = ["resolve_baseline_params"]
