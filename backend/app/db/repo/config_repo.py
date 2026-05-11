"""Config-repo repository.

infra_adapter_elastic Story 1.4 shipped ``create_config_repo``,
``get_config_repo``, and ``get_config_repo_by_name`` for the adapter
feature's FK chain. feat_github_pr_worker Story 1.1 extends with
``list_config_repos`` + ``count_config_repos`` so the FR-3
``GET /api/v1/config-repos`` endpoint can paginate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select
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


async def list_config_repos(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
) -> Sequence[ConfigRepo]:
    """Cursor-paginated config-repo list, newest first.

    Order: ``created_at DESC, id DESC``. ``cursor=(created_at, id)``
    returns rows strictly older than the cursor. Limit clamped at 200
    per api-conventions.md. Mirrors
    :func:`backend.app.db.repo.proposal.list_proposals_paginated` exactly.
    """
    stmt = select(ConfigRepo)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                ConfigRepo.created_at < cursor_at,
                and_(ConfigRepo.created_at == cursor_at, ConfigRepo.id < cursor_id),
            )
        )
    stmt = stmt.order_by(ConfigRepo.created_at.desc(), ConfigRepo.id.desc()).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_config_repos(db: AsyncSession) -> int:
    """COUNT(*) for the ``X-Total-Count`` header on ``GET /api/v1/config-repos``."""
    return int((await db.execute(select(func.count()).select_from(ConfigRepo))).scalar_one())
