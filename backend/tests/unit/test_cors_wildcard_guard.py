# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""CORS wildcard-credentials guard (audit 2026-07-11 #10 regression test)."""

from __future__ import annotations

import pytest

from backend.app.core.cors import cors_allow_credentials


@pytest.mark.parametrize(
    "origins,expected",
    [
        (["http://localhost:3000", "http://127.0.0.1:3000"], True),
        (["https://app.example"], True),
        ([], True),
        (["*"], False),
        (["http://localhost:3000", "*"], False),
    ],
)
def test_credentials_disabled_only_with_wildcard(origins: list[str], expected: bool) -> None:
    assert cors_allow_credentials(origins) is expected
