# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-7 + cycle-1 F7 parameter-importance test for ``generate_digest``.

Seeds a study with 4 continuous params + ≥10 successful trials so
``optuna.importance.get_param_importances`` returns a meaningful map.
Asserts:
* All 4 expected param keys are present in ``digests.parameter_importance``.
* Values are floats in ``[0.0, 1.0]``.
* Sum is ≈ 1.0 within Optuna's tolerance.

Optuna is invoked through the production ``optuna_runtime`` helpers; we
seed the underlying ``optuna_trials`` rows by calling Optuna's own
``study.tell`` per trial so the importance computation has real data.
"""

from __future__ import annotations

import asyncio

import optuna
import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import (
    build_pruner,
    build_sampler,
    build_storage,
    get_or_create_study,
)
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import (
    make_openai_response,
    patch_async_openai,
    seed_completed_study,
    stub_capability,
)
from backend.workers.digest import generate_digest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_continuous_params_present_and_sum_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-7: parameter_importance has all 4 expected keys; values sum to ~1.0."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    declared = {
        "field_boosts.title": {"type": "float", "min": 1.0, "max": 5.0},
        "field_boosts.body": {"type": "float", "min": 0.5, "max": 3.0},
        "tie_breaker": {"type": "float", "min": 0.0, "max": 1.0},
        "fuzziness": {"type": "float", "min": 0.0, "max": 2.0},
    }
    seeded = await seed_completed_study(
        best_trial_params={
            "field_boosts.title": 4.7,
            "field_boosts.body": 2.0,
            "tie_breaker": 0.34,
            "fuzziness": 1.0,
        },
        declared_params=declared,
    )

    # Seed Optuna trials so importance has real data to compute against.
    storage = build_storage(settings.database_url)

    factory = get_session_factory()
    async with factory() as db:
        study = await repo.get_study(db, seeded["study_id"])
    assert study is not None
    sampler = build_sampler(study.config, seed=42)
    pruner = build_pruner(study.config)
    optuna_study = await asyncio.to_thread(
        get_or_create_study,
        storage=storage,
        optuna_study_name=study.optuna_study_name,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
    )

    def _seed_trials() -> None:
        # 12 trials with varied params; importance needs >=2 distinct values per param.
        for i in range(12):
            t = optuna_study.ask(
                {
                    "field_boosts.title": optuna.distributions.FloatDistribution(1.0, 5.0),
                    "field_boosts.body": optuna.distributions.FloatDistribution(0.5, 3.0),
                    "tie_breaker": optuna.distributions.FloatDistribution(0.0, 1.0),
                    "fuzziness": optuna.distributions.FloatDistribution(0.0, 2.0),
                }
            )
            optuna_study.tell(t, values=0.5 + (i * 0.02))  # monotone-ish

    await asyncio.to_thread(_seed_trials)

    patch_async_openai(monkeypatch, make_openai_response())

    await generate_digest({}, seeded["study_id"])

    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        importance = digest.parameter_importance
        # AC-7: all 4 declared continuous params appear.
        assert set(importance.keys()) == set(declared.keys())
        # Values are floats in [0.0, 1.0].
        for v in importance.values():
            assert isinstance(v, float)
            assert 0.0 <= v <= 1.0
        # Sum ≈ 1.0 (Optuna's importance is normalized).
        assert abs(sum(importance.values()) - 1.0) < 1e-3
