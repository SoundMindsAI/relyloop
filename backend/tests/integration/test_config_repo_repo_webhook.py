"""Repo unit-of-work tests for feat_github_webhook Story 1.4 (config_repo extensions).

Exercises the 2 new functions added to :mod:`backend.app.db.repo.config_repo`:

* :func:`set_webhook_registration_error` — UPDATE column + NULL-clears-on-retry
* :func:`lookup_config_repo_by_owner_repo` — case-insensitive ``(owner, repo)`` lookup
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


async def _seed_config_repo(*, owner: str, name: str, url_suffix: str = "") -> str:
    """Insert a config_repo with a deterministic repo_url and return its id.

    The repo name carries a per-test random suffix so the UNIQUE constraint
    on config_repos.name doesn't collide across runs.
    """
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:8]
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-{owner}-{name}-{suffix}",
            provider="github",
            repo_url=f"https://github.com/{owner}/{name}{url_suffix}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"pat-{suffix}",
            webhook_secret_ref=None,
        )
        await db.commit()
        return cr.id


async def test_set_webhook_registration_error_populates_column() -> None:
    """Happy path: populate then clear on subsequent successful retry."""
    cr_id = await _seed_config_repo(owner="acme", name="search-configs")

    factory = get_session_factory()
    async with factory() as db:
        updated = await repo.set_webhook_registration_error(
            db, cr_id, "GitHub returned 404 — PAT lacks admin:repo_hook scope"
        )
        await db.commit()
    assert updated is not None
    assert updated.webhook_registration_error == (
        "GitHub returned 404 — PAT lacks admin:repo_hook scope"
    )

    # Clear on successful retry.
    async with factory() as db:
        cleared = await repo.set_webhook_registration_error(db, cr_id, None)
        await db.commit()
    assert cleared is not None
    assert cleared.webhook_registration_error is None


async def test_set_webhook_registration_error_returns_none_on_missing_row() -> None:
    """Non-existent config_repo id → None (no exception)."""
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.set_webhook_registration_error(
            db, "00000000-0000-0000-0000-000000000000", "anything"
        )
    assert result is None


async def test_lookup_config_repo_by_owner_repo_happy_path() -> None:
    """Direct match on the canonical https URL."""
    cr_id = await _seed_config_repo(owner="acme-search", name="configs-prod")

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_config_repo_by_owner_repo(db, "acme-search", "configs-prod")
    assert row is not None
    assert row.id == cr_id


async def test_lookup_config_repo_by_owner_repo_matches_dot_git_suffix() -> None:
    """``https://github.com/owner/repo.git`` matches ``(owner, repo)``.

    ``validate_repo_url`` strips the ``.git`` suffix during parsing, so
    the lookup matches both forms.
    """
    cr_id = await _seed_config_repo(owner="example", name="dotgit-repo", url_suffix=".git")

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_config_repo_by_owner_repo(db, "example", "dotgit-repo")
    assert row is not None
    assert row.id == cr_id


async def test_lookup_config_repo_by_owner_repo_is_case_insensitive() -> None:
    """``Octocat/Hello-World`` matches the stored ``octocat/hello-world``."""
    cr_id = await _seed_config_repo(owner="OctoCat", name="Hello-World")

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_config_repo_by_owner_repo(db, "octocat", "hello-world")
    assert row is not None
    assert row.id == cr_id


async def test_lookup_config_repo_by_owner_repo_returns_none_on_miss() -> None:
    """No row whose ``repo_url`` parses to the needle → None."""
    await _seed_config_repo(owner="alpha", name="beta")

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.lookup_config_repo_by_owner_repo(db, "gamma", "delta")
    assert row is None
