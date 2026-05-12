"""GitHub webhook HMAC-SHA256 signature verification (feat_github_webhook Story 1.2).

Pure-domain helper consumed by ``backend.app.api.webhooks.github`` (Story
2.1). No I/O, no DB; takes the raw request body, the ``X-Hub-Signature-256``
header value, and the per-repo webhook secret content, and returns a bool.

Constant-time comparison via :func:`hmac.compare_digest` prevents
length-comparison and partial-equality timing side-channels.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

_SIGNATURE_PREFIX = "sha256="


def verify_webhook_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verify GitHub's ``X-Hub-Signature-256`` HMAC-SHA256 against ``body``.

    Args:
        body: The exact request body bytes (must be the unparsed payload —
            JSON parsing happens AFTER signature verification).
        signature_header: The ``X-Hub-Signature-256`` header value, expected
            shape ``"sha256=<hex>"``. ``None`` returns ``False``.
        secret: The per-repo webhook secret content (operator-chosen string
            from ``./secrets/{webhook_secret_ref}``). Empty secret returns
            ``False`` — we never accept unsigned acceptance, even when no
            secret is configured.

    Returns:
        ``True`` iff the header is well-formed AND the HMAC-SHA256 digest
        of ``body`` under ``secret`` matches the header value. ``False`` on
        any of: missing header, missing/malformed ``sha256=`` prefix,
        empty secret, or digest mismatch.
    """
    if signature_header is None:
        return False
    if not secret:
        return False
    if not signature_header.startswith(_SIGNATURE_PREFIX):
        return False
    provided_hex = signature_header[len(_SIGNATURE_PREFIX) :]
    if not provided_hex:
        return False
    expected_hex = hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
    # `hmac.compare_digest` is constant-time over equal-length inputs and
    # short-circuits on length mismatch — exactly the property we want here.
    return hmac.compare_digest(provided_hex, expected_hex)
