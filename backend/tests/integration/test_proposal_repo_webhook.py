"""Repo unit-of-work tests for feat_github_webhook Story 1.4 (proposal extensions).

Exercises the 5 new functions added to :mod:`backend.app.db.repo.proposal`:

* :func:`mark_proposal_pr_merged` — conditional UPDATE pr_opened+open → pr_merged
* :func:`mark_proposal_pr_closed` — conditional UPDATE pr_opened+open → pr_opened+closed
* :func:`mark_proposal_pr_reopened` — conditional UPDATE pr_opened+closed → pr_opened+open
* :func:`lookup_proposal_by_pr_url` — single-row SELECT keyed on pr_url
* :func:`list_pr_opened_proposals_for_reconcile` — polling-tick candidate list

All four conditional UPDATEs return ``None`` on a zero-row match so the
caller logs benignly and skips. Mirrors the cycle-3 F4 pattern from
``mark_proposal_pr_opened`` (feat_github_pr_worker Story 1.1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from backend.app.db import repo
from backend.app.db.models import Proposal
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_pr_opened_proposal(*, pr_url: str | None = None) -> str:
    """Seed FK chain + a pending proposal transitioned to pr_opened.

    Returns the proposal id. Status is ``pr_opened`` and ``pr_state``
    is ``open`` — the input shape for the closed/merged/reopened
    transitions.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"wh-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"wh-tmpl-{uuid.uuid4().hex[:8]}",
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
        pid = proposal.id

    final_pr_url = pr_url or f"https://github.com/example/repo/pull/{uuid.uuid4().int % 10_000}"
    async with factory() as db:
        await repo.mark_proposal_pr_opened(db, pid, pr_url=final_pr_url)
        await db.commit()
    return pid


async def test_mark_pr_merged_transitions_status() -> None:
    """Happy path: pr_opened+open → pr_merged + populates pr_merged_at."""
    pid = await _seed_pr_opened_proposal()
    merged_at = datetime.now(UTC).replace(microsecond=0)

    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.mark_proposal_pr_merged(db, pid, pr_merged_at=merged_at)
        await db.commit()
    assert updated is not None
    assert updated.status == "pr_merged"
    assert updated.pr_state == "merged"
    assert updated.pr_merged_at == merged_at


async def test_mark_pr_merged_no_ops_on_repeat_delivery() -> None:
    """Idempotent on duplicate merge events: second call returns None.

    Once a proposal is in pr_merged, the conditional WHERE doesn't match
    and the repo function reports the benign no-op via ``None``.
    """
    pid = await _seed_pr_opened_proposal()
    merged_at = datetime.now(UTC).replace(microsecond=0)

    factory = get_session_factory()
    async with factory() as db:
        first = await repo.mark_proposal_pr_merged(db, pid, pr_merged_at=merged_at)
        await db.commit()
    assert first is not None

    async with factory() as db:
        second = await repo.mark_proposal_pr_merged(db, pid, pr_merged_at=merged_at)
        await db.commit()
    assert second is None


async def test_mark_pr_closed_keeps_status_pr_opened() -> None:
    """Closed-without-merge: pr_state='closed' but status STAYS 'pr_opened'.

    Spec §11 downstream-invariant audit: the operator can re-open_pr,
    so we don't regress status back to pending or forward to pr_merged.
    """
    pid = await _seed_pr_opened_proposal()

    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()
    assert updated is not None
    assert updated.status == "pr_opened"
    assert updated.pr_state == "closed"


async def test_mark_pr_closed_no_ops_on_already_closed() -> None:
    """Idempotent: closed→closed second delivery returns None."""
    pid = await _seed_pr_opened_proposal()

    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()

    async with factory() as db:
        second = await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()
    assert second is None


async def test_mark_pr_reopened_returns_open() -> None:
    """closed → open: only matches when current state is closed."""
    pid = await _seed_pr_opened_proposal()

    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()

    async with factory() as db:
        reopened = await repo.mark_proposal_pr_reopened(db, pid)
        await db.commit()
    assert reopened is not None
    assert reopened.status == "pr_opened"
    assert reopened.pr_state == "open"


async def test_mark_pr_reopened_no_ops_when_already_open() -> None:
    """Re-opening an already-open PR matches zero rows → returns None."""
    pid = await _seed_pr_opened_proposal()
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.mark_proposal_pr_reopened(db, pid)
        await db.commit()
    assert result is None


async def test_lookup_proposal_by_pr_url_returns_match() -> None:
    """Happy path: registered pr_url maps back to the proposal id."""
    url = f"https://github.com/example/repo/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal(pr_url=url)

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_proposal_by_pr_url(db, url)
    assert row is not None
    assert row.id == pid


async def test_lookup_proposal_by_pr_url_returns_none_on_miss() -> None:
    """Unmapped URL → None (drives the router's "unknown_pr" override)."""
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_proposal_by_pr_url(db, "https://github.com/never/seen/pull/9999")
    assert row is None


async def test_list_pr_opened_for_reconcile_returns_recent_rows() -> None:
    """Returns rows with status=pr_opened, pr_state=open, pr_url set, <90 days."""
    pid = await _seed_pr_opened_proposal()

    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert any(r.id == pid for r in rows)


async def test_list_pr_opened_excludes_pr_merged() -> None:
    """Once merged, the proposal drops out of the reconcile candidate list."""
    pid = await _seed_pr_opened_proposal()

    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_merged(db, pid, pr_merged_at=datetime.now(UTC))
        await db.commit()

    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert all(r.id != pid for r in rows)


async def test_list_pr_opened_excludes_rows_older_than_90_days() -> None:
    """Hard cap at 90 days — spec FR-2 polling growth ceiling.

    Backdates the seeded proposal's created_at to 91 days ago via a
    direct UPDATE (the column is server_default; can't be set via
    ``create_proposal``). The row should not appear in the reconcile
    result.
    """
    pid = await _seed_pr_opened_proposal()
    cutoff = datetime.now(UTC) - timedelta(days=91)

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(update(Proposal).where(Proposal.id == pid).values(created_at=cutoff))
        await db.commit()

    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert all(r.id != pid for r in rows)
