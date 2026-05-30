# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Story 1.4 — verify the global structlog chain redacts GitHub PATs.

The unit tests in ``backend/tests/unit/domain/test_redaction.py`` cover
the ``RedactTokensProcessor`` in isolation. This test verifies it is
actually wired into ``configure_logging`` (defense-in-depth check —
prevents the processor from silently being dropped from the chain in a
future logging refactor).
"""

from __future__ import annotations

import io
import logging

import structlog

from backend.app.core.logging import configure_logging
from backend.app.domain.git.redaction import REDACTED_PLACEHOLDER

# Constructed dynamically (prefix + body in separate string literals) so the
# gitleaks pre-commit hook doesn't false-positive on the test fixture.
_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz"


def test_configure_logging_wires_token_redactor() -> None:
    configure_logging(level=logging.INFO, json_output=True)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.getLogger().handlers[0].formatter)
    root = logging.getLogger()
    original_handlers = root.handlers
    root.handlers = [handler]
    try:
        log = structlog.get_logger("test_redaction_wiring")
        log.info(
            "outbound git push",
            argv=["git", "push", f"https://x:{_TOKEN}@github.com/o/r.git"],
            tail=f"failed because {_TOKEN} expired",
        )
    finally:
        root.handlers = original_handlers

    output = buf.getvalue()
    assert REDACTED_PLACEHOLDER in output
    assert _TOKEN not in output
    assert "ghp_" not in output
