"""Mounted-secrets bundle reader (feat_github_webhook Story 1.5 hoist).

Shared helper for reading per-repo PATs and webhook HMAC secrets from
the mounted bundle at ``./secrets/{name}`` (Compose secrets volume,
CLAUDE.md "Secrets via mounted files"). The webhook router (Story 2.1),
polling reconciler (Story 3.1), and register-webhook worker (Story 4.1)
all consume this — keeping one definition avoids the path-containment
check drifting between call sites.

Mirrors the contract of ``backend.workers.git_pr._read_pat`` (the inline
copy that shipped with feat_github_pr_worker):

* Containment check rejects ``../etc/passwd``-style refs.
* Directory at the target path → ``None``.
* ``OSError`` on read → ``None``.
* Empty content → ``None``.

The ``RELYLOOP_SECRETS_DIR`` env var overrides the default mount root
for test isolation (same convention as ``_read_pat``).
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_SECRETS_DIR = Path("./secrets")


def secrets_dir() -> Path:
    """Resolved mounted-secret directory (``RELYLOOP_SECRETS_DIR`` override)."""
    override = os.environ.get("RELYLOOP_SECRETS_DIR")
    return Path(override) if override else _DEFAULT_SECRETS_DIR


def read_mounted_secret(name: str) -> str | None:
    """Read ``./secrets/{name}`` content; return ``None`` on any failure.

    Args:
        name: A ``config_repos.auth_ref`` (PAT) or ``webhook_secret_ref``
            (HMAC secret). Empty string returns ``None`` immediately.

    Returns:
        The trimmed file content, or ``None`` for missing / empty /
        directory / OSError / path-escape cases.
    """
    if not name:
        return None
    root = secrets_dir().resolve()
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        # Escaped the secrets root — refuse silently. Callers log the
        # operator-visible error via their own structured-log channel.
        return None
    if not candidate.is_file():
        return None
    try:
        content = candidate.read_text().strip()
    except OSError:
        return None
    return content or None
