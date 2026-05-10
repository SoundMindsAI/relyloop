"""Pruner-default integration test (Story 3.1 / AC-6a + AC-6b).

These exercise the FR-2 two-pronged contract at the data-path layer (config
dict → JSONB round-trip → loaded study row → pruner builder), complementing
the unit-layer tests in ``backend/tests/unit/eval/test_optuna_runtime.py``.

The integration variant catches drift in how ``studies.config`` JSONB
encoding/decoding might disturb the ``"pruner"`` key-presence-vs-absence
signal that ``build_pruner`` relies on (spec FR-2 + AC-6).
"""

from __future__ import annotations

import pytest
from optuna.pruners import MedianPruner, NopPruner

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_pruner
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.run_trial_setup import (
    cleanup_study,
    setup_study_with_cluster,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_pruner_omitted_with_small_max_trials_round_trips_to_nop():
    """AC-6a — config without ``pruner`` key + max_trials=30 → NopPruner.

    Verifies the JSONB round-trip preserves the key-absence signal that
    ``build_pruner`` uses to fire the small-study auto-disable safeguard.
    """
    fixture = await setup_study_with_cluster(max_trials=30, pruner=None)
    factory = get_session_factory()
    async with factory() as db:
        loaded = await repo.get_study(db, fixture.study_id)
    assert loaded is not None
    assert "pruner" not in loaded.config

    pruner = build_pruner(loaded.config)
    assert isinstance(pruner, NopPruner)

    await cleanup_study(fixture.study_id)


async def test_pruner_explicit_median_with_small_max_trials_round_trips_to_median():
    """AC-6b — explicit ``pruner='median'`` overrides the small-study safeguard.

    Verifies the JSONB round-trip preserves the key-presence signal.
    """
    fixture = await setup_study_with_cluster(max_trials=30, pruner="median")
    factory = get_session_factory()
    async with factory() as db:
        loaded = await repo.get_study(db, fixture.study_id)
    assert loaded is not None
    assert loaded.config.get("pruner") == "median"

    pruner = build_pruner(loaded.config)
    assert isinstance(pruner, MedianPruner)

    await cleanup_study(fixture.study_id)
