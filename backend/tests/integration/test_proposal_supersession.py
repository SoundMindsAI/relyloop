# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Repo unit-of-work tests for the Phase 3 supersession + reinstate helpers.

Exercises :func:`bulk_mark_superseded` (conditional UPDATE-RETURNING gated on
``WHERE status='pending'``) and :func:`reinstate_from_superseded`
(read-check-mutate per spec D-17, distinguishing 404 from 409). Tests run
against the real Postgres test DB (per spec D-20) because the conditional
``UPDATE … RETURNING`` semantics and the CHECK constraint behavior cannot
be accurately represented against an in-memory SQLite session.
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


async def _seed_minimal_chain() -> dict[str, str | None]:
    """Insert the minimal FK chain a proposal needs; return the IDs.

    Mirrors the helper in ``test_proposal_repo.py`` — kept local so the
    Phase 3 test file is self-contained.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sup-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sup-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sup-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"sup-jl-{uuid.uuid4().hex[:8]}",
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
            name=f"sup-study-{uuid.uuid4().hex[:8]}",
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
        await db.commit()
        return {
            "cluster_id": cluster.id,
            "template_id": template.id,
            "study_id": study.id,
        }


async def _create_proposal(ids: dict[str, str | None], status: str = "pending") -> str:
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
            status=status,
        )
        await db.commit()
        return p.id


# ---------------------------------------------------------------------------
# bulk_mark_superseded
# ---------------------------------------------------------------------------


async def test_bulk_mark_superseded_transitions_pending_returns_ids() -> None:
    """AC-3: the conditional UPDATE flips pending → superseded and returns IDs."""
    ids_a = await _seed_minimal_chain()
    ids_b = await _seed_minimal_chain()
    pa = await _create_proposal(ids_a)
    pb = await _create_proposal(ids_b)
    factory = get_session_factory()
    async with factory() as db:
        transitioned = await repo.bulk_mark_superseded(
            db,
            study_ids=[ids_a["study_id"], ids_b["study_id"]],  # type: ignore[list-item]
        )
        await db.commit()
    assert set(transitioned) == {pa, pb}
    # Subsequent reads see status='superseded'.
    factory2 = get_session_factory()
    async with factory2() as db:
        ra = await repo.get_proposal(db, pa)
        rb = await repo.get_proposal(db, pb)
    assert ra is not None and ra.status == "superseded"
    assert rb is not None and rb.status == "superseded"


async def test_bulk_mark_superseded_idempotent_on_rerun() -> None:
    """AC-3: re-running on already-superseded rows returns []."""
    ids = await _seed_minimal_chain()
    await _create_proposal(ids)
    factory = get_session_factory()
    async with factory() as db:
        first = await repo.bulk_mark_superseded(db, study_ids=[ids["study_id"]])  # type: ignore[list-item]
        await db.commit()
    assert len(first) == 1
    async with factory() as db:
        second = await repo.bulk_mark_superseded(db, study_ids=[ids["study_id"]])  # type: ignore[list-item]
        await db.commit()
    assert second == []


async def test_bulk_mark_superseded_skips_pr_opened() -> None:
    """AC-4 / D-5: pr_opened rows are NOT transitioned (system can't supersede a shipped PR)."""
    ids = await _seed_minimal_chain()
    pid = await _create_proposal(ids, status="pending")
    # Manually transition to pr_opened via the existing helper.
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_opened(db, pid, pr_url="https://example.com/pr/1")
        await db.commit()
    async with factory() as db:
        transitioned = await repo.bulk_mark_superseded(
            db,
            study_ids=[ids["study_id"]],  # type: ignore[list-item]
        )
        await db.commit()
    assert transitioned == []
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None and row.status == "pr_opened"


async def test_bulk_mark_superseded_skips_rejected() -> None:
    """AC-4 / D-6 / Q3: rejected rows are stronger than superseded; never auto-flipped."""
    ids = await _seed_minimal_chain()
    pid = await _create_proposal(ids, status="pending")
    factory = get_session_factory()
    async with factory() as db:
        await repo.reject_proposal(db, pid, reason="operator-rejected")
        await db.commit()
    async with factory() as db:
        transitioned = await repo.bulk_mark_superseded(
            db,
            study_ids=[ids["study_id"]],  # type: ignore[list-item]
        )
        await db.commit()
    assert transitioned == []
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None and row.status == "rejected"


async def test_bulk_mark_superseded_empty_study_ids_returns_empty() -> None:
    """Defensive: empty input never touches the DB."""
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.bulk_mark_superseded(db, study_ids=[])
    assert result == []


# ---------------------------------------------------------------------------
# reinstate_from_superseded
# ---------------------------------------------------------------------------


async def test_reinstate_from_superseded_happy_path() -> None:
    """AC-5: superseded → pending flip + returns the updated row."""
    ids = await _seed_minimal_chain()
    pid = await _create_proposal(ids, status="pending")
    factory = get_session_factory()
    async with factory() as db:
        await repo.bulk_mark_superseded(db, study_ids=[ids["study_id"]])  # type: ignore[list-item]
        await db.commit()
    async with factory() as db:
        row = await repo.reinstate_from_superseded(db, proposal_id=pid)
        await db.commit()
    assert row.status == "pending"
    async with factory() as db:
        fresh = await repo.get_proposal(db, pid)
    assert fresh is not None and fresh.status == "pending"


async def test_reinstate_from_superseded_raises_lookup_error_on_unknown_id() -> None:
    """D-17: unknown id → LookupError (distinct from wrong-status)."""
    factory = get_session_factory()
    bogus = str(uuid.uuid4())
    async with factory() as db:
        with pytest.raises(LookupError):
            await repo.reinstate_from_superseded(db, proposal_id=bogus)


async def test_reinstate_from_superseded_raises_invalid_state_on_pending() -> None:
    """AC-13: a pending (non-superseded) row → InvalidStateTransition."""
    ids = await _seed_minimal_chain()
    pid = await _create_proposal(ids, status="pending")
    factory = get_session_factory()
    async with factory() as db:
        with pytest.raises(InvalidStateTransition) as exc_info:
            await repo.reinstate_from_superseded(db, proposal_id=pid)
    assert exc_info.value.current_status == "pending"


async def test_reinstate_from_superseded_raises_invalid_state_on_pr_opened() -> None:
    """Defense: a pr_opened row stays pr_opened; reinstate refuses."""
    ids = await _seed_minimal_chain()
    pid = await _create_proposal(ids, status="pending")
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_opened(db, pid, pr_url="https://example.com/pr/1")
        await db.commit()
    async with factory() as db:
        with pytest.raises(InvalidStateTransition):
            await repo.reinstate_from_superseded(db, proposal_id=pid)
