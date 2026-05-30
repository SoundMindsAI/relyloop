# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``verify_webhook_signature`` (feat_github_webhook Story 1.2)."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import patch

import pytest

from backend.app.domain.git import verify_webhook_signature

_SECRET = "super-secret-string"
_BODY = b'{"action":"closed","pull_request":{"merged":true}}'


def _hmac_header(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_returns_true() -> None:
    header = _hmac_header(_SECRET, _BODY)
    assert verify_webhook_signature(_BODY, header, _SECRET) is True


def test_mismatched_signature_returns_false() -> None:
    header = _hmac_header("different-secret", _BODY)
    assert verify_webhook_signature(_BODY, header, _SECRET) is False


def test_missing_header_returns_false() -> None:
    assert verify_webhook_signature(_BODY, None, _SECRET) is False


def test_missing_sha256_prefix_returns_false() -> None:
    """Headers without the ``sha256=`` prefix are rejected outright."""
    digest = hmac.new(_SECRET.encode("utf-8"), _BODY, hashlib.sha256).hexdigest()
    # Same hex digest, no `sha256=` prefix.
    assert verify_webhook_signature(_BODY, digest, _SECRET) is False


def test_sha1_prefix_returns_false() -> None:
    """Legacy ``sha1=`` prefix is not accepted."""
    digest = hmac.new(_SECRET.encode("utf-8"), _BODY, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(_BODY, f"sha1={digest}", _SECRET) is False


def test_empty_signature_after_prefix_returns_false() -> None:
    """``sha256=`` with no hex content is rejected."""
    assert verify_webhook_signature(_BODY, "sha256=", _SECRET) is False


def test_empty_body_with_matching_signature_returns_true() -> None:
    """Edge case: GitHub may send an empty body; HMAC over b'' is still defined."""
    empty_body = b""
    header = _hmac_header(_SECRET, empty_body)
    assert verify_webhook_signature(empty_body, header, _SECRET) is True


def test_empty_secret_returns_false() -> None:
    """We refuse to verify with an empty secret — no unsigned acceptance."""
    header = _hmac_header(_SECRET, _BODY)
    assert verify_webhook_signature(_BODY, header, "") is False


def test_uses_constant_time_compare() -> None:
    """Sanity check: helper goes through :func:`hmac.compare_digest`."""
    header = _hmac_header(_SECRET, _BODY)
    # Patch the symbol where it's looked up (in the helper's module).
    with patch(
        "backend.app.domain.git.webhook_signature.hmac.compare_digest",
        wraps=hmac.compare_digest,
    ) as spy:
        assert verify_webhook_signature(_BODY, header, _SECRET) is True
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "tampered_header",
    [
        "sha256=00",  # too short — different length triggers length-mismatch path
        "sha256=" + "0" * 64,  # right length, wrong digest
        "sha256=NOT_HEX_CHARS_AT_ALL_zzzz",  # wrong length AND non-hex
    ],
)
def test_garbage_signatures_return_false(tampered_header: str) -> None:
    assert verify_webhook_signature(_BODY, tampered_header, _SECRET) is False
