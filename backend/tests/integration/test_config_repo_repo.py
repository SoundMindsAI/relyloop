"""Repo unit-of-work tests for feat_github_pr_worker Story 1.1 (config_repo extensions).

Exercises the 2 new functions added to :mod:`backend.app.db.repo.config_repo`:
* :func:`list_config_repos` — cursor pagination
* :func:`count_config_repos` — total count for X-Total-Count
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


async def _seed_config_repo(tag: str) -> str:
    """Insert a config_repo with a hex-suffixed name and return its id.

    Tests share the same Postgres test database and do NOT roll back rows
    inserted via raw ``get_session_factory()`` sessions (vs the
    ``db_session`` fixture's SAVEPOINT rollback). Use a per-test random
    hex suffix so concurrent runs + re-runs against a dirty DB don't
    collide on the ``config_repos_name_key`` UNIQUE constraint.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-{tag}-{suffix}",
            provider="github",
            repo_url=f"https://github.com/example/repo-{tag}-{suffix}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"pat-{tag}-{suffix}",
            webhook_secret_ref=None,
        )
        await db.commit()
        return cr.id


async def test_list_paginated_returns_newest_first() -> None:
    """list_config_repos returns rows newest-first by created_at DESC, id DESC."""
    a = await _seed_config_repo("a")
    b = await _seed_config_repo("b")
    c = await _seed_config_repo("c")

    factory = get_session_factory()
    async with factory() as db:
        rows = list(await repo.list_config_repos(db, limit=200))

    ids_in_order = [r.id for r in rows]
    # Newest-first; c was inserted last, so c should appear before b before a.
    assert ids_in_order.index(c) < ids_in_order.index(b)
    assert ids_in_order.index(b) < ids_in_order.index(a)


async def test_list_paginated_respects_cursor() -> None:
    """Passing a cursor returns rows strictly older than it."""
    a = await _seed_config_repo("a")
    b = await _seed_config_repo("b")
    c = await _seed_config_repo("c")

    factory = get_session_factory()
    async with factory() as db:
        # Pin the cursor to the row WE just inserted last (newest), not to
        # the global newest — other tests in the suite may have inserted
        # newer rows after our seed step (the test DB persists rows across
        # tests for raw-factory sessions).
        all_rows = list(await repo.list_config_repos(db, limit=200))
        c_index = next(i for i, r in enumerate(all_rows) if r.id == c)
        cursor = (all_rows[c_index].created_at, all_rows[c_index].id)
        page2 = list(await repo.list_config_repos(db, cursor=cursor, limit=200))
    page2_ids = [r.id for r in page2]
    assert c not in page2_ids
    assert b in page2_ids
    assert a in page2_ids


async def test_count_returns_total() -> None:
    """count_config_repos returns COUNT(*), monotonically increasing across inserts."""
    factory = get_session_factory()
    async with factory() as db:
        baseline = await repo.count_config_repos(db)
    await _seed_config_repo("a")
    await _seed_config_repo("b")
    async with factory() as db:
        after = await repo.count_config_repos(db)
    assert after == baseline + 2
