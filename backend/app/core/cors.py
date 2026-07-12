# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""CORS policy helpers.

Kept out of ``main`` so they're importable without constructing ``Settings`` /
building the FastAPI app.
"""

from __future__ import annotations


def cors_allow_credentials(origins: list[str]) -> bool:
    """Return whether CORS credentials may be enabled for ``origins``.

    Security audit 2026-07-11 finding #10: a wildcard origin combined with
    ``allow_credentials=True`` is unsafe — Starlette reflects the request Origin
    (rather than sending a literal ``*``), which lets ANY site make credentialed
    cross-origin requests. So credentials are disabled whenever a wildcard is
    configured; MVP1 has no cookies/auth so nothing depends on credentialed CORS
    today. Explicit origins keep credentials.
    """
    return "*" not in origins
