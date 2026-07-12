# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""GitHub PAT redaction (feat_github_pr_worker Story 1.4 / FR-5).

Two surfaces: a string-level ``redact_token`` for ad-hoc redaction (used
by the worker when assembling PR bodies, commit messages, error strings,
and subprocess stdout/stderr capture), and a ``RedactTokensProcessor``
that wires into the structlog chain so EVERY log record (API, worker,
capability check, request-id middleware) is scrubbed.

Token-format coverage (cycle-3 F2 from spec review):

- ``github_pat_<82+ chars>`` — fine-grained PATs (newest, increasingly
  common in enterprise). Anchored on the ``github_pat_`` prefix; the
  body length floor is 20 to be conservative against future variants.
- ``gh[a-z]_<36+ chars>`` — covers the entire family of legacy + newer
  short-prefix tokens: ``ghp_`` (classic PAT), ``ghs_`` (installation
  token from a GitHub App), ``gho_`` (OAuth), ``ghu_`` (user access
  token), ``ghr_`` (refresh token).
- ``sk-<20+ chars>`` — OpenAI-family API keys, covering the legacy
  ``sk-<48>`` form and the newer prefixed forms (``sk-proj-…``,
  ``sk-svcacct-…``). This is the defense-in-depth backstop CLAUDE.md
  Rule #10 anticipates: call sites are disciplined (the capability
  check logs the endpoint URL but never the key), so this only fires
  if a *future* log line accidentally interpolates a key.

The GitHub replacement is a fixed ``[REDACTED-GH-TOKEN]`` and the
OpenAI replacement a fixed ``[REDACTED-OPENAI-KEY]`` so log diffs are
stable across runs (helpful for golden-output tests + grep).
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

_GH_TOKEN_PATTERN = re.compile(r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[a-z]_[A-Za-z0-9_]{36,})")
REDACTED_PLACEHOLDER = "[REDACTED-GH-TOKEN]"

# OpenAI-family API keys. ``sk-`` prefix followed by 20+ chars of the
# key alphabet (also matches the ``sk-proj-``/``sk-svcacct-`` prefixed
# forms since ``-`` is in the class). The 20-char floor keeps ordinary
# prose containing ``sk-`` from matching. The leading ``\b`` anchors the
# match to a word boundary so hyphenated words that merely *contain*
# ``sk-`` (``risk-assessment-questionnaire``, ``task-scheduling-service``)
# are NOT redacted — a real key always begins at a token boundary.
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")
REDACTED_OPENAI_PLACEHOLDER = "[REDACTED-OPENAI-KEY]"

# Credentials embedded in a connection URI: `scheme://user:password@host`.
# Redacts the password portion of a DSN — the Postgres password (RelyLoop's
# one boot-blocking secret) and any `redis://:pass@`, so an asyncpg/redis
# connection-error log line that echoes the DSN can't leak it (security audit
# 2026-07-12). Requires the trailing `@` (userinfo) so a plain `host:port/path`
# URL with no credentials never matches.
# The password class excludes ``]`` so this pattern never re-redacts an already
# substituted ``[REDACTED-GH-TOKEN]`` placeholder that sits in the userinfo of a
# git auth URL (``https://x:ghp_…@github.com`` → GH pattern runs first and wins).
_DSN_PASSWORD_PATTERN = re.compile(
    r"([a-z][a-z0-9+.\-]*://[^\s:/@]*:)[^\s@/\]]+(@)",
    re.IGNORECASE,
)
REDACTED_DSN_PLACEHOLDER = r"\1[REDACTED-URL-PASSWORD]\2"


def redact_token(text: Any) -> Any:
    """Replace any GitHub PAT / OpenAI key pattern with its placeholder.

    Non-string inputs are returned unchanged so callers can pass through
    arbitrary values without an isinstance dance — useful inside the
    structlog processor walking heterogeneous event_dict values.
    """
    if not isinstance(text, str):
        return text
    redacted = _GH_TOKEN_PATTERN.sub(REDACTED_PLACEHOLDER, text)
    redacted = _OPENAI_KEY_PATTERN.sub(REDACTED_OPENAI_PLACEHOLDER, redacted)
    return _DSN_PASSWORD_PATTERN.sub(REDACTED_DSN_PLACEHOLDER, redacted)


def _redact_value(value: Any) -> Any:
    """Recursively redact strings inside arbitrary nested structures."""
    if isinstance(value, str):
        return redact_token(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    return value


class RedactTokensProcessor:
    """structlog processor that redacts GitHub PATs from every event field.

    Walks the event_dict (including nested dicts/lists) and applies
    ``redact_token`` to every string value. Place this BEFORE the JSON
    renderer so the redaction is the last semantic transform on the
    record before serialization.
    """

    def __call__(
        self,
        _logger: object,
        _method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        """Apply ``redact_token`` to every string in ``event_dict`` (recursive)."""
        redacted = _redact_value(dict(event_dict))
        assert isinstance(redacted, dict)  # noqa: S101 — invariant: top-level is a dict
        return redacted
