"""Git provider domain helpers (feat_github_pr_worker Story 1.4).

Pure-Python helpers shared between the open_pr worker, the config_repos
API surface, and any future Git provider integrations:

- ``redact_token`` + ``RedactTokensProcessor`` — strip GitHub PAT
  patterns from log messages / extra fields. The processor wires into
  the structlog chain in ``backend.app.core.logging`` so EVERY log line
  is token-redacted (FR-5 defense-in-depth, not just the worker's).
- ``validate_repo_url`` — assert the configured ``repo_url`` matches the
  MVP1 GitHub-only pattern; return the parsed ``(owner, repo)``.
- ``validate_config_path`` — reject path-traversal / shell-metacharacter
  attempts in ``clusters.config_path`` (spec §10 mitigation 2).
"""

from __future__ import annotations

from backend.app.domain.git.redaction import RedactTokensProcessor, redact_token
from backend.app.domain.git.repository_name import parse_repository_full_name
from backend.app.domain.git.validation import (
    InvalidConfigPathError,
    UnsupportedProviderError,
    validate_config_path,
    validate_repo_url,
)
from backend.app.domain.git.webhook_dispatch import (
    HANDLED_EVENT_TYPES,
    WEBHOOK_ACTION_VALUES,
    WebhookDecision,
    dispatch_event,
)
from backend.app.domain.git.webhook_signature import verify_webhook_signature

__all__ = [
    "HANDLED_EVENT_TYPES",
    "InvalidConfigPathError",
    "RedactTokensProcessor",
    "UnsupportedProviderError",
    "WEBHOOK_ACTION_VALUES",
    "WebhookDecision",
    "dispatch_event",
    "parse_repository_full_name",
    "redact_token",
    "validate_config_path",
    "validate_repo_url",
    "verify_webhook_signature",
]
