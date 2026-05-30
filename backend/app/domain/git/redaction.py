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

The replacement is a fixed string ``[REDACTED-GH-TOKEN]`` so log
diffs are stable across runs (helpful for golden-output tests + grep).
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

_GH_TOKEN_PATTERN = re.compile(r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[a-z]_[A-Za-z0-9_]{36,})")
REDACTED_PLACEHOLDER = "[REDACTED-GH-TOKEN]"


def redact_token(text: Any) -> Any:
    """Replace any GitHub PAT pattern with the canonical placeholder.

    Non-string inputs are returned unchanged so callers can pass through
    arbitrary values without an isinstance dance — useful inside the
    structlog processor walking heterogeneous event_dict values.
    """
    if not isinstance(text, str):
        return text
    return _GH_TOKEN_PATTERN.sub(REDACTED_PLACEHOLDER, text)


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
