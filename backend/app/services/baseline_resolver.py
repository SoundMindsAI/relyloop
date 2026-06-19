# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""DB-backed baseline-trial parameter resolver."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.domain.study.baseline_resolver import resolve_baseline_params_from_candidates

logger = structlog.get_logger(__name__)


async def resolve_baseline_params(
    db: AsyncSession,
    study: Study,
) -> dict[str, Any] | None:
    """Resolve baseline-trial params via the FR-3 4-tier fallback.

    The parent proposal / parent study tiers require DB reads, so this service
    owns those lookups and delegates the deterministic ordering/default math to
    ``backend.app.domain.study.baseline_resolver``.

    Logged structured events on fall-through:

    - ``baseline_resolve_parent_proposal_missing`` — tier (d) fell through
      because the parent proposal's referenced trial is missing.
    - ``baseline_resolve_parent_study_missing`` — tier (c) fell through
      because the parent study or its best trial is missing.
    """
    parent_proposal_params: dict[str, Any] | None = None
    if study.parent_proposal_id is not None:
        parent_proposal_params = await _resolve_from_parent_proposal(db, study.parent_proposal_id)

    parent_study_params: dict[str, Any] | None = None
    if parent_proposal_params is None and study.parent_study_id is not None:
        parent_study_params = await _resolve_from_parent_study(db, study.parent_study_id)

    return resolve_baseline_params_from_candidates(
        study,
        parent_proposal_params=parent_proposal_params,
        parent_study_params=parent_study_params,
    )


async def _resolve_from_parent_proposal(
    db: AsyncSession,
    parent_proposal_id: str,
) -> dict[str, Any] | None:
    """Tier (d): the parent proposal's ``study_trial_id`` is the baseline."""
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


__all__ = ["resolve_baseline_params"]
