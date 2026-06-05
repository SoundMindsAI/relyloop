# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""DB-backed pairing/validation tests (feat_ubi_llm_study_comparison Story 1.1).

Covers ``find_paired_ubi_llm_study``, ``get_completed_study_for_judgment_list``,
and ``validate_compare_pair`` against real rows. Skips without Postgres.
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.services import study_comparison as sc
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


def _u() -> str:
    return str(uuid.uuid4())


async def _seed_cluster(db, *, name_suffix: str = ""):  # noqa: ANN001
    return await repo.create_cluster(
        db,
        id=_u(),
        name=f"c-{name_suffix}-{_u()[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://stub:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
    )


async def _seed_jl(db, *, cluster_id: str, query_set_id: str, kind: str, target: str = "products"):  # noqa: ANN001
    gp = {"generation_kind": "ubi", "target": target} if kind == "ubi" else None
    return await repo.create_judgment_list(
        db,
        id=_u(),
        name=f"jl-{kind}-{_u()[:8]}",
        description=None,
        query_set_id=query_set_id,
        cluster_id=cluster_id,
        target=target,
        current_template_id=None,
        rubric="hand-built",
        status="complete",
        failed_reason=None,
        calibration=None,
        generation_params=gp,
    )


async def _seed_study(  # noqa: ANN001
    db,
    *,
    cluster_id: str,
    query_set_id: str,
    judgment_list_id: str,
    template_id: str,
    status: str = "completed",
    target: str = "products",
    objective: dict[str, object] | None = None,
):
    sid = _u()
    return await repo.create_study(
        db,
        id=sid,
        name=f"s-{_u()[:8]}",
        cluster_id=cluster_id,
        target=target,
        template_id=template_id,
        query_set_id=query_set_id,
        judgment_list_id=judgment_list_id,
        search_space={"params": {"boost": {"type": "float", "low": 0.0, "high": 4.0}}},
        objective=objective or {"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 10, "sampler": "tpe"},
        status=status,
        optuna_study_name=sid,
    )


async def _seed_pair(*, same_cluster: bool = True, llm_status: str = "completed", **study_kw):
    from backend.app.core.settings import get_settings
    from backend.app.db.optuna_schema import init_optuna_schema
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    init_optuna_schema(get_settings().database_url)

    factory = get_session_factory()
    async with factory() as db:
        cluster = await _seed_cluster(db)
        cluster2 = cluster if same_cluster else await _seed_cluster(db, name_suffix="2")
        qs = await repo.create_query_set(db, id=_u(), name=f"qs-{_u()[:8]}", cluster_id=cluster.id)
        tpl = await repo.create_query_template(
            db,
            id=_u(),
            name=f"qt-{_u()[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"boost": "float"},
            version=1,
        )
        jl_llm = await _seed_jl(db, cluster_id=cluster.id, query_set_id=qs.id, kind="llm")
        jl_ubi = await _seed_jl(db, cluster_id=cluster2.id, query_set_id=qs.id, kind="ubi")
        llm = await _seed_study(
            db,
            cluster_id=cluster.id,
            query_set_id=qs.id,
            judgment_list_id=jl_llm.id,
            template_id=tpl.id,
            status=llm_status,
            **study_kw,
        )
        ubi = await _seed_study(
            db,
            cluster_id=cluster2.id,
            query_set_id=qs.id,
            judgment_list_id=jl_ubi.id,
            template_id=tpl.id,
        )
        await db.commit()
        return llm.id, ubi.id, jl_llm.id, jl_ubi.id, qs.id


async def test_find_paired_returns_counterpart() -> None:
    llm_id, ubi_id, _, _, _ = await _seed_pair()
    factory = get_session_factory()
    async with factory() as db:
        paired = await repo.find_paired_ubi_llm_study(db, llm_id)
        assert paired is not None and paired.id == ubi_id
        reverse = await repo.find_paired_ubi_llm_study(db, ubi_id)
        assert reverse is not None and reverse.id == llm_id


async def test_find_paired_none_when_source_not_completed() -> None:
    llm_id, _, _, _, _ = await _seed_pair(llm_status="running")
    factory = get_session_factory()
    async with factory() as db:
        assert await repo.find_paired_ubi_llm_study(db, llm_id) is None


async def test_find_paired_none_cross_cluster() -> None:
    # The UBI counterpart is on a different cluster → not a counterpart.
    llm_id, _, _, _, _ = await _seed_pair(same_cluster=False)
    factory = get_session_factory()
    async with factory() as db:
        assert await repo.find_paired_ubi_llm_study(db, llm_id) is None


async def test_get_completed_study_for_judgment_list() -> None:
    llm_id, _, jl_llm_id, _, _ = await _seed_pair()
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_completed_study_for_judgment_list(db, jl_llm_id)
        assert row is not None and row.id == llm_id
        assert await repo.get_completed_study_for_judgment_list(db, "nonexistent") is None


async def test_validate_compare_pair_happy_and_warnings() -> None:
    llm_id, ubi_id, _, _, qs_id = await _seed_pair()
    factory = get_session_factory()
    async with factory() as db:
        pairing = await sc.validate_compare_pair(db, llm_id, ubi_id)
        assert {pairing.a_kind, pairing.b_kind} == {"llm", "ubi"}
        assert pairing.query_set_id == qs_id


async def test_validate_compare_pair_cross_cluster_warning() -> None:
    llm_id, ubi_id, _, _, _ = await _seed_pair(same_cluster=False)
    factory = get_session_factory()
    async with factory() as db:
        pairing = await sc.validate_compare_pair(db, llm_id, ubi_id)
        assert "CROSS_CLUSTER" in [w.code for w in pairing.warnings]
