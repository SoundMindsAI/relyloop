"""Config-repo CRUD endpoints (feat_github_pr_worker Stories 3.2 + 3.3 / FR-3).

Three endpoints under ``/api/v1/config-repos``:

* ``POST /api/v1/config-repos`` (Story 3.2) — register a new config repo.
  ``provider`` is server-derived from ``repo_url`` via ``validate_repo_url``
  per spec cycle-2 F4 (NOT a payload field) so the API surface can't be
  used to claim "github" identity for a non-github URL.
* ``GET /api/v1/config-repos`` (Story 3.3) — cursor-paginated list with
  ``X-Total-Count`` header.
* ``GET /api/v1/config-repos/{id}`` (Story 3.3) — detail.

Helpers (``_err``, ``_encode_cursor``, ``_decode_cursor``) are copied
from :mod:`backend.app.api.v1.judgments` per the project's deferred-
hoist note (``chore_router_helpers_hoist`` follow-up).
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    ConfigRepoDetail,
    ConfigReposListResponse,
    CreateConfigRepoRequest,
)
from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.db.session import get_db
from backend.app.domain.git import UnsupportedProviderError, validate_repo_url

router = APIRouter()
logger = get_logger(__name__)

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def _encode_cursor(created_at: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at.isoformat(), row_id]).encode()).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        created_at = datetime.fromisoformat(decoded[0])
        row_id = str(decoded[1])
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    return created_at, row_id


def _auth_ref_exists(auth_ref: str) -> bool:
    """Existence check for ``./secrets/{auth_ref}``.

    Mirrors the worker's containment-check pattern. The non-empty
    contents check happens at PR-open time (the secret may be wired in
    via Compose secret reload between config-repo registration and the
    first PR-open).
    """
    if not auth_ref:
        return False
    override = os.environ.get("RELYLOOP_SECRETS_DIR")
    secrets_root = Path(override).resolve() if override else Path("./secrets").resolve()
    candidate = (secrets_root / auth_ref).resolve()
    try:
        candidate.relative_to(secrets_root)
    except ValueError:
        return False
    # GPT-5.5 final-review F4 — `is_file()` instead of `exists()` so
    # AUTH_REF_NOT_FOUND fires for a directory at that path (which would
    # later crash the worker's read_text() with IsADirectoryError).
    return candidate.is_file()


def _to_detail(row: object) -> ConfigRepoDetail:
    """Render an ORM row to the wire-shape ``ConfigRepoDetail``."""
    return ConfigRepoDetail(
        id=row.id,  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        provider=row.provider,  # type: ignore[attr-defined]
        repo_url=row.repo_url,  # type: ignore[attr-defined]
        default_branch=row.default_branch,  # type: ignore[attr-defined]
        pr_base_branch=row.pr_base_branch,  # type: ignore[attr-defined]
        auth_ref=row.auth_ref,  # type: ignore[attr-defined]
        webhook_secret_ref=row.webhook_secret_ref,  # type: ignore[attr-defined]
        webhook_registration_error=row.webhook_registration_error,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------
# POST /api/v1/config-repos  (Story 3.2, FR-3 / AC-8 / AC-9)
# ---------------------------------------------------------------------------


@router.post(
    "/config-repos",
    response_model=ConfigRepoDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["config-repos"],
)
async def create_config_repo_endpoint(
    body: CreateConfigRepoRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigRepoDetail:
    """Register a new config repo. ``provider`` is server-derived from ``repo_url``.

    Preflight order matches spec FR-3:

    1. ``validate_repo_url(repo_url)`` → 400 ``UNSUPPORTED_PROVIDER`` for
       non-GitHub URLs (AC-8). GitLab + Bitbucket arrive at MVP3.
    2. ``./secrets/{auth_ref}`` must exist → else 400 ``AUTH_REF_NOT_FOUND``
       (AC-9). The contents check defers to the worker — operators may
       populate the file between registration and first PR-open.
    3. ``name`` uniqueness check → 409 ``CONFIG_REPO_NAME_TAKEN`` on collision.
    4. Insert with server-derived ``provider="github"``.
    """
    try:
        validate_repo_url(body.repo_url)
    except UnsupportedProviderError as exc:
        raise _err(400, "UNSUPPORTED_PROVIDER", str(exc), False) from exc

    if not _auth_ref_exists(body.auth_ref):
        raise _err(
            400,
            "AUTH_REF_NOT_FOUND",
            f"auth_ref={body.auth_ref!r} does not exist at ./secrets/{body.auth_ref}; "
            "create the file (it can be empty for now) and retry",
            False,
        )

    existing = await repo.get_config_repo_by_name(db, body.name)
    if existing is not None:
        raise _err(
            409,
            "CONFIG_REPO_NAME_TAKEN",
            f"config_repo name {body.name!r} is already registered (id={existing.id})",
            False,
        )

    new_id = str(uuid_utils.uuid7())
    inserted = await repo.create_config_repo(
        db,
        id=new_id,
        name=body.name,
        provider="github",
        repo_url=body.repo_url,
        default_branch=body.default_branch,
        pr_base_branch=body.pr_base_branch,
        auth_ref=body.auth_ref,
        webhook_secret_ref=body.webhook_secret_ref,
    )
    await db.commit()
    return _to_detail(inserted)


# ---------------------------------------------------------------------------
# GET /api/v1/config-repos  (Story 3.3, FR-3)
# ---------------------------------------------------------------------------


@router.get(
    "/config-repos",
    response_model=ConfigReposListResponse,
    tags=["config-repos"],
)
async def list_config_repos_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> ConfigReposListResponse:
    """Cursor-paginated config-repo list, newest first."""
    decoded_cursor = _decode_cursor(cursor) if cursor else None
    rows = await repo.list_config_repos(db, cursor=decoded_cursor, limit=limit + 1)
    has_more = len(rows) > limit
    visible = rows[:limit]
    next_cursor: str | None = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
    response.headers["X-Total-Count"] = str(await repo.count_config_repos(db))
    return ConfigReposListResponse(
        data=[_to_detail(row) for row in visible],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/config-repos/{id}  (Story 3.3, FR-3)
# ---------------------------------------------------------------------------


@router.get(
    "/config-repos/{config_repo_id}",
    response_model=ConfigRepoDetail,
    tags=["config-repos"],
)
async def get_config_repo_endpoint(
    config_repo_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigRepoDetail:
    """Detail by id; 404 ``CONFIG_REPO_NOT_FOUND`` if missing."""
    row = await repo.get_config_repo(db, config_repo_id)
    if row is None:
        raise _err(
            404,
            "CONFIG_REPO_NOT_FOUND",
            f"config_repo {config_repo_id} not found",
            False,
        )
    return _to_detail(row)


__all__ = ["router"]
