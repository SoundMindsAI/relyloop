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

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import ConfigRepo
from backend.app.domain.git import UnsupportedProviderError, validate_repo_url


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
    returns rows strictly older than the cursor. Limit clamped at 201
    so the API endpoint's ``limit + 1`` over-fetch (used to compute
    ``has_more`` at ``MAX_PAGE_LIMIT=200``) survives the clamp — GPT-5.5
    final-review C2-F1.
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
    stmt = stmt.order_by(ConfigRepo.created_at.desc(), ConfigRepo.id.desc()).limit(min(limit, 201))
    return list((await db.execute(stmt)).scalars().all())


async def count_config_repos(db: AsyncSession) -> int:
    """COUNT(*) for the ``X-Total-Count`` header on ``GET /api/v1/config-repos``."""
    return int((await db.execute(select(func.count()).select_from(ConfigRepo))).scalar_one())


async def set_webhook_registration_error(
    db: AsyncSession,
    config_repo_id: str,
    error: str | None,
) -> ConfigRepo | None:
    """UPDATE the ``webhook_registration_error`` column on a single config_repo.

    feat_github_webhook Story 1.4 — ``register_webhook`` worker calls this
    on every failure class (4xx PAT-scope, 422 bad-payload, 5xx
    GitHub-down, network) AND with ``error=None`` after a subsequent
    successful retry to blank the stale message.

    Returns the updated row or ``None`` if the config_repo doesn't exist.
    Caller commits.
    """
    stmt = (
        update(ConfigRepo)
        .where(ConfigRepo.id == config_repo_id)
        .values(webhook_registration_error=error)
        .returning(ConfigRepo)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def lookup_config_repo_by_owner_repo(
    db: AsyncSession,
    owner: str,
    repo: str,
) -> ConfigRepo | None:
    """Locate a registered config_repo by ``(owner, repo)`` short form.

    feat_github_webhook — consumed by the webhook receiver (Story 2.1),
    the polling reconciler (Story 3.1), and the register_webhook worker
    (Story 4.1). Canonicalises every candidate row's ``repo_url`` via
    :func:`backend.app.domain.git.validate_repo_url` and compares
    case-insensitively against the provided ``(owner, repo)`` tuple.

    Returns the matching row or ``None``. Rows whose ``repo_url`` no
    longer parses via ``validate_repo_url`` (e.g. historic non-GitHub
    URLs from before MVP1 hardening) are skipped silently — they cannot
    receive GitHub webhook deliveries by construction.
    """
    needle = (owner.lower(), repo.lower())
    # The config_repos table has no soft-delete column (config_repo.py).
    # All registered rows are candidates.
    rows = (await db.execute(select(ConfigRepo))).scalars().all()
    for row in rows:
        try:
            parsed = validate_repo_url(row.repo_url)
        except UnsupportedProviderError:
            continue
        if (parsed[0].lower(), parsed[1].lower()) == needle:
            return row
    return None
