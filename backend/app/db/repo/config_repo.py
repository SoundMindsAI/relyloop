"""Config-repo repository (infra_adapter_elastic Story 1.4).

Minimal CRUD on the ``config_repos`` aggregate. The full Git-provider lifecycle
(webhooks, PR worker) lands later via ``feat_github_pr_worker`` and
``feat_github_webhook`` — this story only needs create + lookup so the
adapter feature can FK clusters to repos.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import ConfigRepo


async def create_config_repo(db: AsyncSession, **fields: object) -> ConfigRepo:
    """Stage a new ``ConfigRepo`` row. Caller commits."""
    repo = ConfigRepo(**fields)
    db.add(repo)
    await db.flush()
    await db.refresh(repo)
    return repo


async def get_config_repo(db: AsyncSession, repo_id: str) -> ConfigRepo | None:
    """Fetch a config repo by id."""
    return (
        await db.execute(select(ConfigRepo).where(ConfigRepo.id == repo_id))
    ).scalar_one_or_none()


async def get_config_repo_by_name(db: AsyncSession, name: str) -> ConfigRepo | None:
    """Fetch a config repo by unique ``name``."""
    return (
        await db.execute(select(ConfigRepo).where(ConfigRepo.name == name))
    ).scalar_one_or_none()
