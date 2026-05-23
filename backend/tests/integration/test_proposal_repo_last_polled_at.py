"""Repo integration tests for chore_reconciler_terminal_closed_no_poll.

Exercises:

* :func:`list_pr_opened_proposals_for_reconcile` — the FR-3 24-hour exclusion.
* :func:`stamp_proposal_last_polled_at` — the FR-2 defensively-guarded UPDATE.

The 24-hour exclusion only applies to ``pr_state='closed'`` rows; ``pr_state='open'``
rows and rows with ``last_polled_at IS NULL`` are unaffected. The stamp helper
returns ``None`` (benign no-op) when the row is not in the ``(pr_opened, closed)``
shape — protects against the webhook-reopen race documented in FR-2 Notes.
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


async def _seed_pr_opened_proposal(
    *,
    pr_state: str = "open",
    last_polled_at: datetime | None = None,
) -> str:
    """Seed FK chain + a proposal in (pr_opened, <pr_state>) with optional stamp.

    Returns the proposal id. Always lands in ``status='pr_opened'``; the
    ``pr_state`` is set by an explicit UPDATE since ``mark_proposal_pr_opened``
    transitions to ``pr_state='open'`` and there is no helper for
    seeding closed-directly.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"lp-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"lp-tmpl-{uuid.uuid4().hex[:8]}",
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

    pr_url = f"https://github.com/example/repo/pull/{uuid.uuid4().int % 10_000}"
    async with factory() as db:
        await repo.mark_proposal_pr_opened(db, pid, pr_url=pr_url)
        await db.commit()

    # Override pr_state + last_polled_at if requested. Direct UPDATE because
    # the production helpers don't expose these knobs for seeding.
    if pr_state != "open" or last_polled_at is not None:
        async with factory() as db:
            stmt = (
                update(Proposal)
                .where(Proposal.id == pid)
                .values(pr_state=pr_state, last_polled_at=last_polled_at)
            )
            await db.execute(stmt)
            await db.commit()

    return pid


async def test_default_insert_leaves_last_polled_at_null() -> None:
    """A freshly-opened proposal has ``last_polled_at = None``.

    Verifies the column's default-NULL behavior at the ORM/DB layer. AC-2's
    strict "pre-migration rows keep NULL" assertion is structurally
    guaranteed by Alembic's ``add_column(nullable=True)`` (no
    ``server_default``) — Postgres has no other value to write.
    """
    pid = await _seed_pr_opened_proposal()
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.last_polled_at is None


async def test_list_excludes_recently_stamped_closed_rows() -> None:
    """AC-6: a (pr_opened, closed) row stamped 1h ago is excluded."""
    pid = await _seed_pr_opened_proposal(
        pr_state="closed",
        last_polled_at=datetime.now(UTC) - timedelta(hours=1),
    )
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert pid not in {r.id for r in rows}


async def test_list_includes_stamped_rows_older_than_24h() -> None:
    """AC-7: a (pr_opened, closed) row stamped 25h ago is included."""
    pid = await _seed_pr_opened_proposal(
        pr_state="closed",
        last_polled_at=datetime.now(UTC) - timedelta(hours=25),
    )
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert pid in {r.id for r in rows}


async def test_list_includes_closed_rows_with_null_last_polled_at() -> None:
    """Never-observed case: (pr_opened, closed, NULL) is included on every tick."""
    pid = await _seed_pr_opened_proposal(pr_state="closed", last_polled_at=None)
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert pid in {r.id for r in rows}


async def test_list_includes_open_rows_regardless_of_last_polled_at() -> None:
    """AC-8: pathological seed (pr_opened, open, last_polled_at=1h ago) — still included.

    The new exclusion only fires when ``pr_state='closed'``. An open row whose
    ``last_polled_at`` is somehow non-NULL must still be polled.
    """
    pid = await _seed_pr_opened_proposal(
        pr_state="open",
        last_polled_at=datetime.now(UTC) - timedelta(hours=1),
    )
    factory = get_session_factory()
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert pid in {r.id for r in rows}


async def test_stamp_proposal_last_polled_at_updates_closed_row() -> None:
    """FR-2 happy path: stamping a (pr_opened, closed) row writes last_polled_at."""
    pid = await _seed_pr_opened_proposal(pr_state="closed", last_polled_at=None)
    before = datetime.now(UTC)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.stamp_proposal_last_polled_at(db, pid)
        await db.commit()
    assert updated is not None
    assert updated.last_polled_at is not None
    assert updated.last_polled_at >= before

    # Confirm the value persisted.
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.last_polled_at is not None
    assert row.last_polled_at >= before


async def test_stamp_proposal_last_polled_at_no_op_on_open_row() -> None:
    """FR-2 defensive guard: stamping a (pr_opened, open) row returns None.

    Simulates the webhook-reopen race: between reconciler candidate
    selection (when the row was closed) and the worker's stamp call
    (executed inside the case-(b) branch), a ``pull_request.reopened``
    webhook flipped the row to ``pr_state='open'``. The stamp's
    ``WHERE pr_state='closed'`` guard returns None and the column stays NULL.
    """
    pid = await _seed_pr_opened_proposal(pr_state="open", last_polled_at=None)
    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.stamp_proposal_last_polled_at(db, pid)
        await db.commit()
    assert updated is None

    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.last_polled_at is None


async def test_stamp_proposal_last_polled_at_no_op_on_merged_row() -> None:
    """FR-2 defensive guard: a (pr_merged, merged) row is never stamped.

    Verifies the ``WHERE status='pr_opened'`` clause: even if some path
    accidentally calls the helper against a fully-merged row, the column
    stays NULL.
    """
    pid = await _seed_pr_opened_proposal()
    merged_at = datetime.now(UTC).replace(microsecond=0)
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_merged(db, pid, pr_merged_at=merged_at)
        await db.commit()

    async with factory() as db:
        updated = await repo.stamp_proposal_last_polled_at(db, pid)
        await db.commit()
    assert updated is None

    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.last_polled_at is None


async def test_reopen_reclose_within_24h_stays_excluded() -> None:
    """AC-9-reclose: reclose within 24h of last stamp keeps the row excluded.

    Sequence: stamp at T-1h → operator reopens (last_polled_at stays
    stale because ``mark_proposal_pr_reopened`` does not clear the
    column — invariant per spec §11 flow 2) → operator closes again at
    T → row is back to ``(pr_opened, closed)`` with ``last_polled_at``
    still ~1h old → candidate query excludes the row until the
    original 24-hour bucket expires.
    """
    pid = await _seed_pr_opened_proposal(
        pr_state="closed",
        last_polled_at=datetime.now(UTC) - timedelta(hours=1),
    )
    factory = get_session_factory()
    # Simulate reopen (sets pr_state='open' but does NOT clear last_polled_at).
    async with factory() as db:
        reopened = await repo.mark_proposal_pr_reopened(db, pid)
        await db.commit()
    assert reopened is not None
    assert reopened.last_polled_at is not None  # stamp preserved

    # Simulate reclose (back to pr_state='closed').
    async with factory() as db:
        reclosed = await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()
    assert reclosed is not None
    assert reclosed.pr_state == "closed"
    assert reclosed.last_polled_at is not None  # still the original ~1h-old stamp

    # Candidate query: row excluded because last_polled_at < 24h ago.
    async with factory() as db:
        rows = await repo.list_pr_opened_proposals_for_reconcile(db)
    assert pid not in {r.id for r in rows}
