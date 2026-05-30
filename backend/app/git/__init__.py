# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Git provider HTTP clients (feat_github_webhook Story 1.5).

CLAUDE.md "Repository Structure" reserves ``backend/app/git/`` as the
canonical home for Git provider clients. MVP1 ships only the GitHub
REST helpers extracted from ``backend/workers/git_pr.py``; MVP3 adds
GitLab + Bitbucket alongside (per the canonical release matrix).

Method-agnostic ``github_request`` (generalised from the POST-only
``_github_post`` that shipped with feat_github_pr_worker) carries the
established retry policy: RequestError + 5xx + 429 with Retry-After +
403 secondary-rate-limit detection.
"""

from __future__ import annotations

from backend.app.git.github_client import (
    HTTP_RETRY_BACKOFF_S,
    HTTP_RETRY_MAX,
    HTTP_TIMEOUT_S,
    RATE_LIMIT_CLAMP_S,
    body_mentions_rate_limit,
    github_request,
    is_secondary_rate_limit,
    parse_rate_limit_reset,
    parse_retry_after,
)
from backend.app.git.secrets import read_mounted_secret, secrets_dir

__all__ = [
    "HTTP_RETRY_BACKOFF_S",
    "HTTP_RETRY_MAX",
    "HTTP_TIMEOUT_S",
    "RATE_LIMIT_CLAMP_S",
    "body_mentions_rate_limit",
    "github_request",
    "is_secondary_rate_limit",
    "parse_rate_limit_reset",
    "parse_retry_after",
    "read_mounted_secret",
    "secrets_dir",
]
