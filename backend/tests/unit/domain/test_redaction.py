# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for backend.app.domain.git.redaction (Story 1.4 / FR-5).

Token-format coverage matrix from cycle-3 F2:

* ``ghp_<36>``       — classic personal access tokens
* ``ghs_<36>``       — installation tokens (GitHub Apps)
* ``gho_<36>`` / ``ghu_`` / ``ghr_`` — OAuth / user / refresh
* ``github_pat_<82>`` — fine-grained PATs (newest enterprise format)

The processor is also exercised against nested dict / list / tuple
structures so structlog ``extra={"a": {"b": "<token>"}}`` is scrubbed.
"""

from __future__ import annotations

import pytest

from backend.app.domain.git.redaction import (
    REDACTED_OPENAI_PLACEHOLDER,
    REDACTED_PLACEHOLDER,
    RedactTokensProcessor,
    redact_token,
)

# 36-char body for short-prefix tokens (ghp_/ghs_/gho_/ghu_/ghr_).
_BODY_36 = "A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz"
# 82-char body for fine-grained PATs (github_pat_<22>_<59>).
_BODY_82 = "abcdefghij1234567890_" + "Z9y8x7w6v5u4t3s2r1q0pPo9oN8mLkJiHgFeDcBaA1234567890ABCDEF7890"


def test_redacts_classic_pat() -> None:
    raw = f"token=ghp_{_BODY_36} suffix"
    out = redact_token(raw)
    assert REDACTED_PLACEHOLDER in out
    assert "ghp_" not in out
    assert out == f"token={REDACTED_PLACEHOLDER} suffix"


def test_redacts_installation_token() -> None:
    raw = f"ghs_{_BODY_36}"
    assert redact_token(raw) == REDACTED_PLACEHOLDER


@pytest.mark.parametrize("prefix", ["gho_", "ghu_", "ghr_"])
def test_redacts_other_short_prefix_tokens(prefix: str) -> None:
    raw = f"value={prefix}{_BODY_36}"
    out = redact_token(raw)
    assert REDACTED_PLACEHOLDER in out
    assert prefix not in out


def test_redacts_fine_grained_pat() -> None:
    """Cycle-3 F2: github_pat_<82> coverage for fine-grained PATs."""
    raw = f"Authorization: Bearer github_pat_{_BODY_82}"
    out = redact_token(raw)
    assert REDACTED_PLACEHOLDER in out
    assert "github_pat_" not in out


def test_redacts_openai_classic_key() -> None:
    """Defense-in-depth: an accidentally-logged legacy sk-<48> key is scrubbed."""
    raw = "openai_api_key=sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2"
    out = redact_token(raw)
    assert REDACTED_OPENAI_PLACEHOLDER in out
    assert "sk-A1b2" not in out
    assert out == f"openai_api_key={REDACTED_OPENAI_PLACEHOLDER}"


@pytest.mark.parametrize("prefix", ["sk-proj-", "sk-svcacct-"])
def test_redacts_openai_prefixed_key(prefix: str) -> None:
    raw = f"key={prefix}abcdefghij1234567890KLMNOPqrstuvwxyz tail"
    out = redact_token(raw)
    assert REDACTED_OPENAI_PLACEHOLDER in out
    assert prefix not in out


def test_redacts_both_token_families_in_one_string() -> None:
    body = _BODY_36
    raw = f"gh=ghp_{body} openai=sk-{body}0000"
    out = redact_token(raw)
    assert REDACTED_PLACEHOLDER in out
    assert REDACTED_OPENAI_PLACEHOLDER in out
    assert "ghp_" not in out
    assert "sk-" + body not in out


def test_does_not_redact_non_token_strings() -> None:
    samples = [
        "github.com/owner/repo",
        "ghi_short",  # too short to match the {36,} body floor
        "https://api.github.com/repos/foo/bar",
        "PR opened at https://github.com/foo/bar/pull/42",
        "relyloop-bot@example.com",
        "no tokens here at all",
        "sk-short",  # too short to match the {20,} OpenAI body floor
        "task-oriented workflow",  # 'sk-' substring inside a word, no key
    ]
    for s in samples:
        assert redact_token(s) == s


def test_redact_token_passes_non_strings_through() -> None:
    # The implementation accepts arbitrary types and returns them unchanged
    # (the structlog processor walks heterogeneous event_dict values).
    # Cast to Any so mypy doesn't object to the deliberate misuse.
    from typing import Any, cast

    fn = cast("Any", redact_token)
    assert fn(42) == 42
    assert fn(None) is None
    assert fn(["a", "b"]) == ["a", "b"]


def test_processor_walks_nested_dicts() -> None:
    """structlog extras can be nested arbitrarily — the processor must recurse."""
    proc = RedactTokensProcessor()
    event = {
        "event": f"PR open failed: ghp_{_BODY_36}",
        "extra": {
            "argv": ["git", "push", f"https://x:ghs_{_BODY_36}@github.com/foo/bar.git"],
            "nested": {"deeper": {"token": f"github_pat_{_BODY_82}"}},
        },
        "tuple_field": ("safe", f"ghu_{_BODY_36}"),
        "non_string": 42,
    }
    out = proc(None, "info", event)
    assert REDACTED_PLACEHOLDER in out["event"]
    assert "ghp_" not in out["event"]
    assert REDACTED_PLACEHOLDER in out["extra"]["argv"][2]
    assert "ghs_" not in out["extra"]["argv"][2]
    assert out["extra"]["nested"]["deeper"]["token"] == REDACTED_PLACEHOLDER
    assert out["tuple_field"][1] == REDACTED_PLACEHOLDER
    assert out["non_string"] == 42


def test_processor_handles_traceback_string() -> None:
    """format_exc_info renders tracebacks into the 'exception' string field —
    that field must also get scrubbed before the JSONRenderer sees it."""
    proc = RedactTokensProcessor()
    event = {
        "event": "subprocess failed",
        "exception": (
            "Traceback (most recent call last):\n"
            f'  File "git_pr.py", line 1, in run\n    subprocess.run(["git", "push", "https://x:ghp_{_BODY_36}@github.com/o/r.git"])\n'
            "RuntimeError: bad exit\n"
        ),
    }
    out = proc(None, "error", event)
    assert "ghp_" not in out["exception"]
    assert REDACTED_PLACEHOLDER in out["exception"]
