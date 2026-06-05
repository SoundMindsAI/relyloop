# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration test for the I-2 invariant (Stories 2.2 + 2.3, spec §14).

Seeds a normalizer-aware study (template declares ``query_normalizer`` and
references ``{{ query_text }}`` in its body), drives one trial through the
real ``run_trial`` worker with a REAL ``ElasticAdapter.render`` (only
``search_batch`` is stubbed), and asserts:

  * the persisted ``trials.params`` records a ``query_normalizer`` value that
    is one of ``NORMALIZER_CHOICES`` (the worker passed it through opaquely —
    I-2), and
  * the native query body the adapter rendered reflects the normalization
    (``query_text`` slot equals ``normalize(query_text, chosen)``).

Skips automatically when Postgres isn't reachable. The ES cluster is never
contacted — ``search_batch`` is monkeypatched to return handbuilt hits.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.domain.study.normalizers import NORMALIZER_CHOICES, normalize
from backend.app.eval.optuna_runtime import (
    build_pruner,
    build_sampler,
    build_storage,
    get_or_create_study,
)
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import (
    build_hits_response,
    build_qrels,
)
from backend.tests.integration.fixtures.run_trial_setup import TrialFixture, cleanup_fixture

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]

_NORMALIZER_TEMPLATE_BODY = '{"query": {"match": {"title": "{{ query_text }}"}}}'


@pytest.fixture()
def _cluster_credentials(tmp_path, monkeypatch):
    # Only stub the cluster-credentials mount — leave DATABASE_URL_FILE /
    # POSTGRES_PASSWORD_FILE as CI provides them so the worker talks to the
    # real test Postgres.
    creds = tmp_path / "creds.yaml"
    creds.write_text("ref:\n  username: u\n  password: p\n")
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed_normalizer_study() -> TrialFixture:
    from backend.app.core.settings import get_settings as _gs
    from backend.app.db.optuna_schema import init_optuna_schema
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    init_optuna_schema(_gs().database_url)

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"c-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"qt-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body=_NORMALIZER_TEMPLATE_BODY,
            declared_params={"query_normalizer": "string"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        # A single query with a contraction + casing so normalization is
        # observable in the rendered body.
        query = await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            query_text="What's BEST?",
            reference_answer=None,
            query_metadata=None,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        study_id = str(uuid.uuid4())
        study = await repo.create_study(
            db,
            id=study_id,
            name=f"s-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            search_space={
                "params": {
                    "query_normalizer": {
                        "type": "categorical",
                        "choices": list(NORMALIZER_CHOICES),
                    }
                }
            },
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 100, "sampler": "tpe"},
            status="running",
            optuna_study_name=study_id,
        )
        await db.commit()
    return TrialFixture(
        cluster_id=cluster.id,
        template_id=template.id,
        query_set_id=query_set.id,
        query_ids=[query.id],
        judgment_list_id=judgment_list.id,
        study_id=study.id,
        optuna_study_name=study.optuna_study_name,
    )


def _ask_normalizer_trial(storage, optuna_study_name: str) -> tuple[int, str]:
    """Simulate the orchestrator: ask() + suggest_categorical(query_normalizer)."""
    config = {"max_trials": 100, "sampler": "tpe"}
    sampler = build_sampler(config, seed=7)
    pruner = build_pruner(config)
    study = get_or_create_study(
        storage=storage,
        optuna_study_name=optuna_study_name,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
    )
    trial = study.ask()
    chosen = trial.suggest_categorical("query_normalizer", list(NORMALIZER_CHOICES))
    return trial.number, str(chosen)


async def test_trial_runner_records_and_normalizes_query_normalizer(
    monkeypatch: pytest.MonkeyPatch,
    _cluster_credentials,
) -> None:
    fixture = await _seed_normalizer_study()
    storage = build_storage(get_settings().database_url)
    trial_number, chosen = _ask_normalizer_trial(storage, fixture.optuna_study_name)

    # Real adapter so the REAL render hook runs; only search_batch is stubbed.
    adapter = ElasticAdapter(
        cluster_id=fixture.cluster_id,
        engine_type="elasticsearch",
        base_url="http://stub:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )

    rendered_bodies: list[dict] = []
    real_render = adapter.render

    def _recording_render(template, params, query_text):
        nq = real_render(template, params, query_text)
        rendered_bodies.append(nq.body)
        return nq

    hits = build_hits_response(fixture.query_ids)

    async def _fake_search_batch(target, queries, top_k, **kwargs):
        return {q.query_id: hits.get(q.query_id, []) for q in queries}

    monkeypatch.setattr(adapter, "render", _recording_render)
    monkeypatch.setattr(adapter, "search_batch", _fake_search_batch)
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _cluster: adapter)

    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=build_qrels(fixture.query_ids)),
    )

    from backend.workers.trials import run_trial

    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=trial_number,
    )

    # I-2: the worker passed query_normalizer through opaquely; it persisted.
    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials) == 1
    persisted = trials[0].params
    assert persisted["query_normalizer"] in NORMALIZER_CHOICES
    assert persisted["query_normalizer"] == chosen

    # The rendered native body reflects the chosen normalizer.
    assert rendered_bodies, "adapter.render was never called"
    title_slot = rendered_bodies[0]["query"]["match"]["title"]
    assert title_slot == normalize("What's BEST?", chosen)

    await cleanup_fixture(fixture)
