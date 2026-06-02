# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_summary``'s objective-direction extraction.

Per ``bug_ceiling_badge_assumes_maximize_direction``. The studies-list
``StudySummary`` must carry the objective ``direction`` so the UI can
decide whether the ``best_metric >= 0.99`` CEILING badge is meaningful
(it is for ``maximize``; for ``minimize`` a 0.99 is a *bad* score, not a
ceiling). ``direction`` arrived with ``feat_study_baseline_trial``, so
pre-existing studies whose ``objective`` JSON predates the key must
default to ``maximize``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.api.v1.studies import _summary
from backend.app.db.models import Study


def _study(objective: dict[str, Any]) -> Study:
    """Build an in-memory Study row carrying the given objective JSON.

    Only the columns ``_summary`` reads are populated; SQLAlchemy leaves
    the rest unset (no session/flush needed for attribute access).
    """
    return Study(
        id="study-1",
        name="demo",
        cluster_id="c1",
        status="completed",
        best_metric=0.995,
        objective=objective,
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
        completed_at=datetime(2026, 5, 29, tzinfo=UTC),
    )


def test_summary_surfaces_minimize_direction() -> None:
    """A minimize objective flows through to StudySummary.direction."""
    summary = _summary(
        _study({"metric": "ndcg", "k": 10, "direction": "minimize"}),
        trial_count=0,
        convergence_verdict=None,
    )
    assert summary.direction == "minimize"


def test_summary_surfaces_maximize_direction() -> None:
    summary = _summary(
        _study({"metric": "ndcg", "k": 10, "direction": "maximize"}),
        trial_count=0,
        convergence_verdict=None,
    )
    assert summary.direction == "maximize"


def test_summary_defaults_to_maximize_when_direction_absent() -> None:
    """Pre-feat_study_baseline_trial rows lack the key → default maximize.

    This is the backward-compat guard: an objective JSON written before
    the ``direction`` field existed must not blow up or mislabel — it
    defaults to the historical implicit behavior (maximize).
    """
    summary = _summary(
        _study({"metric": "ndcg", "k": 10}),
        trial_count=0,
        convergence_verdict=None,
    )
    assert summary.direction == "maximize"
