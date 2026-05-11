"""Repo unit-of-work tests for feat_github_pr_worker Story 1.1 (proposal PR extensions).

Exercises the 2 new functions added to :mod:`backend.app.db.repo.proposal`:
* :func:`mark_proposal_pr_opened` — conditional UPDATE WHERE status='pending'
* :func:`set_proposal_pr_open_error` — conditional UPDATE WHERE status='pending'

Both follow the cycle-3 F4 pattern: operator-reject mid-flight is a
benign no-op (returns None), the rejection stays.
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_pending_proposal() -> str:
    """Seed a minimal FK chain + pending proposal; return its id."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"prpr-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"prpr-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        proposal = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=None,
            study_trial_id=None,
            cluster_id=cluster.id,
            template_id=template.id,
            config_diff={},
            metric_delta=None,
            status="pending",
        )
        await db.commit()
        return proposal.id


async def test_mark_pr_opened_transitions_status() -> None:
    """mark_proposal_pr_opened: pending → pr_opened + pr_url + pr_state='open'.

    Also clears prior pr_open_error per spec FR-4 (successful retry blanks
    the stale failure message).
    """
    pid = await _seed_pending_proposal()
    # Pre-seed a stale error to verify it's cleared on success.
    factory = get_session_factory()
    async with factory() as db:
        await repo.set_proposal_pr_open_error(db, pid, error="stale prior error")
        await db.commit()

    async with factory() as db:
        updated = await repo.mark_proposal_pr_opened(
            db,
            pid,
            pr_url="https://github.com/example/repo/pull/42",
        )
        await db.commit()
    assert updated is not None
    assert updated.id == pid
    assert updated.status == "pr_opened"
    assert updated.pr_url == "https://github.com/example/repo/pull/42"
    assert updated.pr_state == "open"
    assert updated.pr_open_error is None


async def test_mark_pr_opened_no_ops_when_rejected() -> None:
    """Cycle-3 F4 pattern: operator-rejected proposal → mark_pr_opened returns None.

    The rejection rationale stays in `rejected_reason`; the worker's
    final UPDATE doesn't overwrite it. Worker logs
    `pr_open_proposal_no_longer_pending` (worker concern; this test
    verifies the repo-layer no-op).
    """
    pid = await _seed_pending_proposal()
    factory = get_session_factory()
    async with factory() as db:
        await repo.reject_proposal(db, pid, reason="operator changed mind")
        await db.commit()

    async with factory() as db:
        result = await repo.mark_proposal_pr_opened(
            db,
            pid,
            pr_url="https://github.com/example/repo/pull/42",
        )
        await db.commit()
    assert result is None  # zero rows matched the WHERE status='pending' guard

    # Reject sticks; nothing else mutated.
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "rejected"
    assert row.rejected_reason == "operator changed mind"
    assert row.pr_url is None


async def test_set_pr_open_error_populates_field() -> None:
    """Happy path: pending proposal → pr_open_error populated."""
    pid = await _seed_pending_proposal()
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.set_proposal_pr_open_error(
            db,
            pid,
            error="GitHub API returned 422: PR already exists",
        )
        await db.commit()
    assert updated is not None
    assert updated.status == "pending"
    assert updated.pr_open_error == "GitHub API returned 422: PR already exists"


async def test_set_pr_open_error_no_ops_when_rejected() -> None:
    """Cycle-3 F4 pattern: operator-rejected → set_pr_open_error returns None.

    Don't overwrite the rejection rationale with a stale worker-failure
    string when the operator already moved on.
    """
    pid = await _seed_pending_proposal()
    factory = get_session_factory()
    async with factory() as db:
        await repo.reject_proposal(db, pid, reason="not worth the churn")
        await db.commit()

    async with factory() as db:
        result = await repo.set_proposal_pr_open_error(
            db,
            pid,
            error="some worker error",
        )
        await db.commit()
    assert result is None

    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "rejected"
    assert row.rejected_reason == "not worth the churn"
    assert row.pr_open_error is None  # no error overwrite
