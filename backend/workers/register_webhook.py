# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotent webhook auto-registration (feat_github_webhook Story 4.1 / FR-3).

Enqueued by ``POST /api/v1/config-repos`` (Story 4.2) for any newly
created config_repo whose ``webhook_secret_ref`` is non-NULL. The job:

1. Loads the config_repo by id.
2. Reads the PAT (``auth_ref``) and webhook secret (``webhook_secret_ref``)
   from the mounted-secrets bundle.
3. Issues ``GET /repos/{owner}/{repo}/hooks?per_page=100`` and scans
   for an existing hook whose ``config.url`` matches our webhook URL.
4. If found → clear any prior ``webhook_registration_error`` and exit
   (status "exists"). Re-running the job for the same repo is a no-op.
5. Else → issue ``POST /repos/{owner}/{repo}/hooks`` with the
   FR-3 payload. On 2xx → clear the error column. On 4xx/5xx or
   ``RequestError``-after-budget → call
   :func:`set_webhook_registration_error` with the documented
   per-class message and return ``{"status":"failed"}``.

The handler never raises into the Arq retry loop — failures are
**durable on the column**. ``arq.Retry``-style retries would just
churn through the same error class. The operator drives recovery via
the runbook (Story 4.3).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.domain.git import UnsupportedProviderError, redact_token, validate_repo_url
from backend.app.git import HTTP_TIMEOUT_S, github_request, read_mounted_secret

logger = structlog.get_logger(__name__)


def _hook_url() -> str | None:
    """Return the URL GitHub will POST webhook deliveries to, or None.

    Constructed from ``Settings.relyloop_base_url``. ``None`` (the MVP1
    laptop default) → the job logs + sets a documented error so the
    operator knows GitHub can't reach back without a tunnel.
    """
    base = get_settings().relyloop_base_url
    if not base:
        return None
    return f"{base.rstrip('/')}/webhooks/github"


async def _persist_error(config_repo_id: str, message: str) -> None:
    """Best-effort UPDATE of ``webhook_registration_error``."""
    redacted = redact_token(message)
    factory = get_session_factory()
    try:
        async with factory() as db:
            await repo.set_webhook_registration_error(db, config_repo_id, redacted)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — last-resort error path
        logger.warning(
            "register_webhook_persist_failed",
            config_repo_id=config_repo_id,
            error_type=type(exc).__name__,
        )


async def _clear_error(config_repo_id: str) -> None:
    """Clear ``webhook_registration_error`` on a successful retry."""
    factory = get_session_factory()
    try:
        async with factory() as db:
            await repo.set_webhook_registration_error(db, config_repo_id, None)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — last-resort clear
        logger.warning(
            "register_webhook_clear_failed",
            config_repo_id=config_repo_id,
            error_type=type(exc).__name__,
        )


async def register_webhook(ctx: dict[str, Any], config_repo_id: str) -> dict[str, str]:
    """Idempotent GitHub webhook creation for a single config_repo.

    Returns ``{"status": "created" | "exists" | "skipped" | "failed"}``
    for observability. Never raises; failures are persisted on the
    config_repo's ``webhook_registration_error`` column.
    """
    factory = get_session_factory()
    async with factory() as db:
        config_repo_row = await repo.get_config_repo(db, config_repo_id)

    if config_repo_row is None:
        logger.warning("register_webhook_missing_row", config_repo_id=config_repo_id)
        return {"status": "skipped"}

    if not config_repo_row.webhook_secret_ref:
        # Defensive — POST /config-repos only enqueues us when this is set.
        return {"status": "skipped"}

    try:
        owner, repo_name = validate_repo_url(config_repo_row.repo_url)
    except UnsupportedProviderError as exc:
        await _persist_error(
            config_repo_id,
            f"Unsupported provider: {exc}",
        )
        return {"status": "failed"}

    token = read_mounted_secret(config_repo_row.auth_ref)
    if token is None:
        await _persist_error(
            config_repo_id,
            f"PAT not configured: ./secrets/{config_repo_row.auth_ref} is missing or empty.",
        )
        return {"status": "failed"}

    secret = read_mounted_secret(config_repo_row.webhook_secret_ref)
    if secret is None:
        await _persist_error(
            config_repo_id,
            (
                f"Webhook secret not configured: ./secrets/"
                f"{config_repo_row.webhook_secret_ref} is missing or empty."
            ),
        )
        return {"status": "failed"}

    target_url = _hook_url()
    if target_url is None:
        await _persist_error(
            config_repo_id,
            (
                "RELYLOOP_BASE_URL is not configured; GitHub cannot reach this "
                "install. Set Settings.relyloop_base_url and re-enqueue."
            ),
        )
        return {"status": "failed"}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        list_url = f"https://api.github.com/repos/{owner}/{repo_name}/hooks?per_page=100"
        try:
            list_response = await github_request(client, "GET", list_url, token=token)
        except httpx.RequestError as exc:
            await _persist_error(
                config_repo_id,
                f"GitHub unreachable — network error: {type(exc).__name__}",
            )
            return {"status": "failed"}

        if list_response.status_code >= 400:
            await _persist_error(
                config_repo_id,
                (
                    f"GitHub returned {list_response.status_code} listing webhooks — "
                    f"check PAT scope (admin:repo_hook required)."
                ),
            )
            return {"status": "failed"}

        try:
            existing_hooks = list_response.json()
        except ValueError:
            await _persist_error(
                config_repo_id,
                "GitHub returned non-JSON response listing webhooks.",
            )
            return {"status": "failed"}

        if isinstance(existing_hooks, list):
            for hook in existing_hooks:
                hook_config = hook.get("config") if isinstance(hook, dict) else None
                if isinstance(hook_config, dict) and hook_config.get("url") == target_url:
                    await _clear_error(config_repo_id)
                    logger.info(
                        "register_webhook_exists",
                        config_repo_id=config_repo_id,
                        hook_id=hook.get("id"),
                    )
                    return {"status": "exists"}

        create_url = f"https://api.github.com/repos/{owner}/{repo_name}/hooks"
        payload = {
            "name": "web",
            "active": True,
            "events": ["pull_request"],
            "config": {
                "url": target_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0",
            },
        }
        try:
            create_response = await github_request(
                client, "POST", create_url, json_body=payload, token=token
            )
        except httpx.RequestError as exc:
            await _persist_error(
                config_repo_id,
                f"GitHub unreachable — network error: {type(exc).__name__}",
            )
            return {"status": "failed"}

        if create_response.status_code in (200, 201):
            await _clear_error(config_repo_id)
            logger.info(
                "register_webhook_created",
                config_repo_id=config_repo_id,
                status_code=create_response.status_code,
            )
            return {"status": "created"}

        # Documented per-class error messages (spec §13 NFR-Operability).
        if create_response.status_code == 404:
            error_msg = (
                "GitHub returned 404 — PAT lacks admin:repo_hook scope or the "
                "configured repo doesn't exist."
            )
        elif create_response.status_code == 422:
            error_msg = (
                "GitHub returned 422 — webhook payload was rejected. "
                "Inspect the hook config (URL reachable from GitHub?)."
            )
        elif create_response.status_code >= 500:
            error_msg = (
                f"GitHub returned {create_response.status_code} — transient. "
                "Re-enqueue the job manually after GitHub's status recovers."
            )
        else:
            error_msg = f"GitHub returned {create_response.status_code} creating webhook."
        await _persist_error(config_repo_id, error_msg)
        return {"status": "failed"}
