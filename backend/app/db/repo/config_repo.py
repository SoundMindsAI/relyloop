# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Config-repo repository.

infra_adapter_elastic Story 1.4 shipped ``create_config_repo``,
``get_config_repo``, and ``get_config_repo_by_name`` for the adapter
feature's FK chain. feat_github_pr_worker Story 1.1 extends with
``list_config_repos`` + ``count_config_repos`` so the FR-3
``GET /api/v1/config-repos`` endpoint can paginate.

feat_config_repo_baseline_tracking Story 1.2 adds three helpers
for the ``last_merged_proposal_id`` denormalization:

* :func:`update_config_repo_last_merged_pointer` — row-locked
  conditional UPDATE with the strict-monotonic-timestamp guard.
* :func:`find_currently_live_proposal_ids` — set lookup for the
  per-row ``is_currently_live`` derivation in the proposals serializer.
* :func:`get_config_repo_with_last_merged_proposal` — detail-endpoint
  LEFT JOIN returning a tuple of the pointed-at proposal/cluster/template.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Cluster, ConfigRepo, Proposal, QueryTemplate
from backend.app.domain.git import UnsupportedProviderError, validate_repo_url

logger = structlog.get_logger(__name__)


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


async def update_config_repo_last_merged_pointer(
    db: AsyncSession,
    *,
    config_repo_id: str,
    proposal_id: str,
    pr_merged_at: datetime,
) -> bool:
    """Conditionally update ``config_repos.last_merged_proposal_id``.

    feat_config_repo_baseline_tracking FR-2 — the single write site for the
    pointer. Called from the webhook receiver (FR-3) and the PR reconciler
    (FR-3a) after a successful ``mark_proposal_pr_merged``.

    Sequence:

    1. ``SELECT … FOR UPDATE`` on the ``config_repos`` row (serializes
       concurrent merges on the same repo — mirrors the
       ``study_state.py:139`` precedent).
    2. If ``current.last_merged_proposal_id IS NULL``, write the new
       pointer; emit INFO ``config_repo_last_merged_pointer_updated``;
       return ``True``.
    3. Else fetch the currently-tracked proposal's ``pr_merged_at``; if
       ``pr_merged_at_new > pr_merged_at_current``, write the new pointer;
       emit INFO; return ``True``.
    4. Else no-op; emit DEBUG ``config_repo_last_merged_pointer_skipped_older``;
       return ``False``.

    Caller commits. The function uses ``db.flush()`` for staging.
    """
    stmt = select(ConfigRepo).where(ConfigRepo.id == config_repo_id).with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        # Defensive: the FK chain should make this unreachable in practice.
        logger.debug(
            "config_repo_last_merged_pointer_skipped_no_row",
            config_repo_id=config_repo_id,
            proposal_id=proposal_id,
        )
        return False

    previous_proposal_id: str | None = row.last_merged_proposal_id
    should_write: bool
    if previous_proposal_id is None:
        should_write = True
    else:
        current_ts_stmt = select(Proposal.pr_merged_at).where(Proposal.id == previous_proposal_id)
        current_ts = (await db.execute(current_ts_stmt)).scalar_one_or_none()
        # If the previously-tracked proposal was hard-deleted (ON DELETE SET NULL
        # should have nulled the pointer first; this branch is defense-in-depth)
        # or its pr_merged_at is NULL (cosmically unlikely after FR-1 backfill
        # guard), treat as NULL pointer and accept the new write.
        if current_ts is None:
            should_write = True
        else:
            should_write = pr_merged_at > current_ts

    if should_write:
        row.last_merged_proposal_id = proposal_id
        await db.flush()
        logger.info(
            "config_repo_last_merged_pointer_updated",
            config_repo_id=config_repo_id,
            previous_proposal_id=previous_proposal_id,
            new_proposal_id=proposal_id,
            pr_merged_at=pr_merged_at.isoformat(),
        )
        return True

    logger.debug(
        "config_repo_last_merged_pointer_skipped_older",
        config_repo_id=config_repo_id,
        previous_proposal_id=previous_proposal_id,
        rejected_proposal_id=proposal_id,
        rejected_pr_merged_at=pr_merged_at.isoformat(),
    )
    return False


async def find_currently_live_proposal_ids(
    db: AsyncSession,
    proposal_ids: Sequence[str],
) -> set[str]:
    """Return the subset of ``proposal_ids`` tracked as a live config_repo pointer.

    feat_config_repo_baseline_tracking FR-5 — pointer-only derivation
    used by the proposals list/detail serializer to set
    ``is_currently_live`` on each row. Symmetric with the
    ``?is_last_merged=true`` filter (FR-6): a proposal IS currently
    live iff a ``config_repos`` row points at it, independent of the
    proposal's current cluster wiring.

    Empty input returns the empty set without issuing SQL.
    """
    if not proposal_ids:
        return set()
    stmt = select(ConfigRepo.last_merged_proposal_id).where(
        ConfigRepo.last_merged_proposal_id.in_(list(proposal_ids))
    )
    result = await db.execute(stmt)
    return {pid for pid in result.scalars().all() if pid is not None}


async def get_config_repo_with_last_merged_proposal(
    db: AsyncSession,
    config_repo_id: str,
) -> tuple[ConfigRepo, Proposal | None, Cluster | None, QueryTemplate | None] | None:
    """Detail-endpoint helper for ``GET /api/v1/config-repos/{id}``.

    feat_config_repo_baseline_tracking FR-4. Returns:

    * ``None`` when the config_repo does not exist (the router preserves
      the existing 404 ``CONFIG_REPO_NOT_FOUND`` envelope).
    * ``(config_repo, None, None, None)`` when the pointer is NULL.
    * ``(config_repo, proposal, cluster, template)`` when the pointer is set
      AND all three FK targets resolve (referential integrity guarantees
      they will under normal operation).

    The embedded tuple lets the router construct the ``ProposalSummary``
    inline without a second round-trip to fetch cluster/template.
    """
    cr = (
        await db.execute(select(ConfigRepo).where(ConfigRepo.id == config_repo_id))
    ).scalar_one_or_none()
    if cr is None:
        return None
    if cr.last_merged_proposal_id is None:
        return (cr, None, None, None)

    stmt = (
        select(Proposal, Cluster, QueryTemplate)
        .join(Cluster, Cluster.id == Proposal.cluster_id)
        .join(QueryTemplate, QueryTemplate.id == Proposal.template_id)
        .where(Proposal.id == cr.last_merged_proposal_id)
    )
    embed = (await db.execute(stmt)).one_or_none()
    if embed is None:
        # Defensive: pointer references a row whose FK targets were broken.
        # Should not happen in practice (ON DELETE SET NULL on the pointer
        # itself, plus NOT NULL FKs on proposals.cluster_id +
        # proposals.template_id). Return tuple-with-Nones rather than
        # crashing the detail endpoint.
        return (cr, None, None, None)
    proposal_row, cluster_row, template_row = cast(tuple[Proposal, Cluster, QueryTemplate], embed)
    return (cr, proposal_row, cluster_row, template_row)


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
