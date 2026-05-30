# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Repo unit-of-work tests for the feat_digest_proposal Story 1.2 proposal extensions.

Exercises the 5 new functions added to :mod:`backend.app.db.repo.proposal`:

* :func:`update_proposal_for_digest` — conditional UPDATE (cycle-3 F4)
* :func:`list_proposals_paginated` — cursor + status + cluster_id filters
* :func:`count_proposals` — X-Total-Count
* :func:`reject_proposal` — pending → rejected; InvalidStateTransition otherwise
* :func:`list_pending_proposals_for_boot_scan` — FR-2b boot scan
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.db import repo
from backend.app.db.repo.proposal import InvalidStateTransition
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_minimal_chain(*, with_study: bool = True) -> dict[str, str | None]:
    """Insert the minimal FK chain a proposal needs; return the IDs.

    When ``with_study`` is False, the study_id is None (manual-proposal
    path — exercises the boot-scan study_id IS NOT NULL filter).
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"pr-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        ids: dict[str, str | None] = {
            "cluster_id": cluster.id,
            "template_id": template.id,
            "study_id": None,
        }
        if with_study:
            query_set = await repo.create_query_set(
                db,
                id=str(uuid.uuid4()),
                name=f"pr-qs-{uuid.uuid4().hex[:8]}",
                cluster_id=cluster.id,
            )
            jl = await repo.create_judgment_list(
                db,
                id=str(uuid.uuid4()),
                name=f"pr-jl-{uuid.uuid4().hex[:8]}",
                description=None,
                query_set_id=query_set.id,
                cluster_id=cluster.id,
                target="stub-index",
                current_template_id=template.id,
                rubric="r",
                status="complete",
            )
            study = await repo.create_study(
                db,
                id=str(uuid.uuid4()),
                name=f"pr-study-{uuid.uuid4().hex[:8]}",
                cluster_id=cluster.id,
                target="stub-index",
                template_id=template.id,
                query_set_id=query_set.id,
                judgment_list_id=jl.id,
                search_space={},
                objective={},
                config={},
                status="completed",
                optuna_study_name=str(uuid.uuid4()),
            )
            ids["study_id"] = study.id
        await db.commit()
        return ids


async def _create_pending_proposal(ids: dict[str, str | None]) -> str:
    factory = get_session_factory()
    async with factory() as db:
        p = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=ids["study_id"],
            study_trial_id=None,
            cluster_id=ids["cluster_id"],
            template_id=ids["template_id"],
            config_diff={},
            metric_delta=None,
            status="pending",
        )
        await db.commit()
        return p.id


async def test_update_for_digest_preserves_id_and_status() -> None:
    """AC-1: the orchestrator-inserted pending row is UPDATED in place.

    id unchanged, status still 'pending', but config_diff + metric_delta
    populated. No second row created.
    """
    ids = await _seed_minimal_chain()
    pid = await _create_pending_proposal(ids)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.update_proposal_for_digest(
            db,
            pid,
            config_diff={"field_boosts.title": {"from": 2.5, "to": 4.7}},
            metric_delta={"ndcg@10": {"baseline": 0.6, "achieved": 0.75, "delta_pct": 25.0}},
        )
        await db.commit()
        assert updated is not None
        assert updated.id == pid
        assert updated.status == "pending"
        assert updated.config_diff == {"field_boosts.title": {"from": 2.5, "to": 4.7}}
        assert updated.metric_delta is not None
        assert updated.metric_delta["ndcg@10"]["achieved"] == 0.75


async def test_update_for_digest_no_ops_when_status_is_not_pending() -> None:
    """Cycle-3 F4: operator rejected mid-LLM-call → UPDATE matches zero rows → None.

    The worker logs digest_proposal_no_longer_pending and persists the
    digest anyway (digest is per-study, not per-proposal).
    """
    ids = await _seed_minimal_chain()
    pid = await _create_pending_proposal(ids)
    factory = get_session_factory()
    # Simulate the operator rejection arriving mid-flight.
    async with factory() as db:
        await repo.reject_proposal(db, pid, reason="changed my mind")
        await db.commit()

    async with factory() as db:
        result = await repo.update_proposal_for_digest(
            db,
            pid,
            config_diff={"field_boosts.title": {"from": 2.0, "to": 4.0}},
            metric_delta={"ndcg@10": {"baseline": 0.6, "achieved": 0.7, "delta_pct": 16.7}},
        )
        await db.commit()
        assert result is None  # zero rows affected — benign race outcome


async def test_reject_pending_transitions_to_rejected() -> None:
    """AC-5: reject sets status='rejected' + populates rejected_reason."""
    ids = await _seed_minimal_chain()
    pid = await _create_pending_proposal(ids)
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.reject_proposal(db, pid, reason="metric delta too small")
        await db.commit()
        assert row.status == "rejected"
        assert row.rejected_reason == "metric delta too small"


async def test_reject_terminal_raises_invalid_state() -> None:
    """AC-5: second reject on a terminal proposal raises InvalidStateTransition."""
    ids = await _seed_minimal_chain()
    pid = await _create_pending_proposal(ids)
    factory = get_session_factory()
    async with factory() as db:
        await repo.reject_proposal(db, pid, reason="first")
        await db.commit()
    with pytest.raises(InvalidStateTransition) as excinfo:
        async with factory() as db:
            await repo.reject_proposal(db, pid, reason="second")
    assert excinfo.value.current_status == "rejected"
    assert excinfo.value.proposal_id == pid


async def test_reject_unknown_id_raises_lookup_error() -> None:
    """reject_proposal raises LookupError when the id does not exist."""
    factory = get_session_factory()
    with pytest.raises(LookupError):
        async with factory() as db:
            await repo.reject_proposal(db, str(uuid.uuid4()), reason="nope")


async def test_list_pending_proposals_for_boot_scan_excludes_proposals_with_digests() -> None:
    """FR-2b: boot scan returns only study_ids of pending proposals lacking a digest."""
    ids_with = await _seed_minimal_chain()
    ids_without = await _seed_minimal_chain()
    pid_with = await _create_pending_proposal(ids_with)
    pid_without = await _create_pending_proposal(ids_without)
    # Manual proposal (study_id NULL) — must NOT appear in the boot scan.
    manual_ids = await _seed_minimal_chain(with_study=False)
    await _create_pending_proposal(manual_ids)

    # Seed a digest only for the first pending row's study.
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=ids_with["study_id"],
            narrative="already digested",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[],
            generated_by="local:test",
        )
        await db.commit()

    async with factory() as db:
        study_ids = await repo.list_pending_proposals_for_boot_scan(db)

    assert ids_with["study_id"] not in study_ids  # excluded — digest exists
    assert ids_without["study_id"] in study_ids  # included — no digest
    # Manual proposal's study_id is None — should not appear.
    assert None not in study_ids
    # Confirm the proposals themselves are still in the table — boot scan
    # returns study_ids, not proposal_ids.
    _ = pid_with
    _ = pid_without


async def test_list_proposals_paginated_with_status_and_cluster_filters() -> None:
    """list_proposals_paginated honors status + cluster_id filters and orders DESC."""
    ids_a = await _seed_minimal_chain()
    ids_b = await _seed_minimal_chain()
    pid_a = await _create_pending_proposal(ids_a)
    pid_b = await _create_pending_proposal(ids_b)
    # Move ids_b's proposal to rejected so a status filter excludes it.
    factory = get_session_factory()
    async with factory() as db:
        await repo.reject_proposal(db, pid_b, reason="x")
        await db.commit()

    async with factory() as db:
        # status=pending → only pid_a
        pending = await repo.list_proposals_paginated(db, status="pending")
        pending_ids = [p.id for p in pending]
        assert pid_a in pending_ids
        assert pid_b not in pending_ids

        # cluster_id filter → only pid_a's cluster
        scoped = await repo.list_proposals_paginated(db, cluster_id=ids_a["cluster_id"])
        assert all(p.cluster_id == ids_a["cluster_id"] for p in scoped)

        total = await repo.count_proposals(db, status="pending")
        assert total == sum(1 for p in pending if p.status == "pending")
