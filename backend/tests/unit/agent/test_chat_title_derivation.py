# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Title-derivation rule (feat_chat_agent Story 2.6 — FR-1)."""

from __future__ import annotations

import pytest

from backend.app.services.agent_chat import _derive_title


def test_short_title_preserved_verbatim() -> None:
    assert _derive_title("tune product_search overnight") == "tune product_search overnight"


def test_short_title_stripped_of_surrounding_whitespace() -> None:
    assert _derive_title("  hello world  ") == "hello world"


def test_empty_user_text_returns_none() -> None:
    assert _derive_title("") is None
    assert _derive_title("   ") is None


@pytest.mark.parametrize("padding", [0, 1, 5, 100])
def test_long_user_text_truncated_with_ellipsis(padding: int) -> None:
    """A title longer than 80 chars truncates to 77 + '...' (length 80)."""
    text = "x" * (80 + padding + 1)
    if 80 + padding + 1 <= 80:
        # Defensive: never hit when padding >= 0.
        return
    derived = _derive_title(text)
    assert derived is not None
    assert derived.endswith("...")
    assert len(derived) == 80


def test_exact_80_char_text_kept_as_is() -> None:
    text = "x" * 80
    assert _derive_title(text) == text
