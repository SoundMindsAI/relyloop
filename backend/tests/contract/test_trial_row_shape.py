"""Contract test for ``Trial`` row shape after a happy-path run_trial (Story 3.2).

Asserts every Trial column matches the spec §FR-5 contract:

* ``params`` is JSON-serializable (the JSONB round-trip must round-trip).
* ``metrics`` keys are user-facing names — pytrec_eval wire prefixes
  (``ndcg_cut_``, ``P_``, ``recall_``, ``recip_rank``, ``map_cut_``) must
  never leak into the persisted row.
* ``primary_metric == metrics[objective_metric_key(study.objective)]``
  (denormalization invariant per FR-5).
* ``status`` is in the DB CHECK allowlist ``{complete, failed, pruned}``.
* ``duration_ms`` is an int.

No Pydantic shape is exercised — this feature has no API surface; Phase 2
of feat_study_lifecycle owns the Pydantic Trial response model. The contract
test runs against the ORM Trial model directly.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.app.eval.scoring import objective_metric_key
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import (
    build_hits_response,
    build_qrels,
)
from backend.tests.integration.fixtures.run_trial_setup import (
    cleanup_fixture,
    create_optuna_trial_for_study,
    setup_study_with_cluster,
)
from backend.tests.integration.fixtures.stub_adapter import StubAdapter

# This contract test depends on Postgres + Optuna RDB (the row it asserts
# against is produced by a real run_trial execution).
pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


_PYTREC_EVAL_WIRE_PREFIXES = (
    "ndcg_cut_",
    "P_",
    "recall_",
    "recip_rank",
    "map_cut_",
)


async def test_trial_row_shape_after_happy_path_run_trial(
    monkeypatch: pytest.MonkeyPatch,
):
    """All FR-5 invariants hold on a persisted Trial row."""
    fixture = await setup_study_with_cluster(objective_metric="ndcg", objective_k=10)
    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response=build_hits_response(fixture.query_ids),
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _c: stub)
    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=build_qrels(fixture.query_ids)),
    )

    from backend.workers.trials import run_trial

    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
        study = await repo.get_study(db, fixture.study_id)
    assert len(trials) == 1
    assert study is not None
    t = trials[0]

    # --- FR-5 invariant set ---

    # 1. status is in the allowlist (DB CHECK + spec §8.4).
    assert t.status in {"complete", "failed", "pruned"}
    assert t.status == "complete"  # this is the happy path

    # 2. JSON-serializability — params and metrics must round-trip through
    #    json.dumps without raising (JSONB columns guarantee this on read,
    #    but the contract is that the *application* never persists values
    #    that would break re-serialization).
    json.dumps(t.params)
    json.dumps(t.metrics)

    # 3. Wire-name namespace — pytrec_eval prefixes must NOT appear in metrics.
    for key in t.metrics:
        for prefix in _PYTREC_EVAL_WIRE_PREFIXES:
            assert not key.startswith(prefix), (
                f"metrics key {key!r} starts with pytrec_eval wire prefix "
                f"{prefix!r} — wire names must never leak past scoring.score()"
            )

    # 4. Primary metric denormalized correctly.
    expected_key = objective_metric_key(study.objective)
    assert expected_key in t.metrics
    assert t.primary_metric is not None
    assert t.primary_metric == t.metrics[expected_key]

    # 5. duration_ms is int (spec §FR-5 schema; not float).
    assert t.duration_ms is not None
    assert isinstance(t.duration_ms, int)

    # 6. params and metrics are non-empty for the happy path.
    assert t.params  # populated by orchestrator simulation
    assert t.metrics  # populated by scorer

    await cleanup_fixture(fixture)
