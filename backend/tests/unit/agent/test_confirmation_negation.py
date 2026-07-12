# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Negation handling in is_affirmative (feat_chat_agent — GPT-5.5 final-review F2)."""

from __future__ import annotations

import pytest

from backend.app.agent.confirmation import is_affirmative


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "yes please",
        "go",
        "go ahead",
        "do it",
        "ship it",
        "okay proceed",
        "confirmed",
        "y",
        "yep",
        # "can"/"couldn" must NOT be treated as negations (Gemini review #1/#2):
        # these are valid affirmatives that merely contain "can".
        "yes you can",
        "I can confirm",
        "you can proceed",
        "yes, significant improvement — go ahead",  # "significant" contains "cant"
    ],
)
def test_clean_affirmative_passes(text: str) -> None:
    assert is_affirmative(text)


@pytest.mark.parametrize(
    "text",
    [
        "don't do it",
        "do not proceed",
        "no go",
        "stop, do it later",
        "cancel — go ahead never mind",
        "wait, don't",
        "nope",
        "never proceed",
        "no",
        "absolutely not",
        # Deferral / inability replies that carry an affirmative token but are
        # NOT authorizations (security audit 2026-07-11 finding #3).
        "can't do it right now",
        "cant do it right now",  # apostrophe-stripped form
        "cannot do it",
        "couldn't right now",
        # Unicode smart-apostrophe forms (iOS/macOS default U+2019) — must be
        # folded so they can't slip past the contraction check (audit 2026-07-12 F3).
        "can’t but yes",
        "couldn’t but yes go ahead",
        "do it later",
        "maybe do it tomorrow",
        "maybe later",
        "I will do it later myself",
        "not yet",
    ],
)
def test_negation_blocks_otherwise_affirmative_text(text: str) -> None:
    assert not is_affirmative(text)


@pytest.mark.parametrize(
    "text",
    [
        "here we go",  # mid-sentence phrase, no leading affirmative -> "go" token still hits
    ],
)
def test_phrase_matching_is_anchored_not_substring(text: str) -> None:
    """A mid-sentence 'do it' / 'go ahead' no longer matches as a substring.

    'here we go' still passes because the bare token 'go' is a legitimate
    single-word affirmative — the anchoring change only affects the multi-word
    *phrases*, verified by the deferral cases above ('do it later' etc.).
    """
    assert is_affirmative(text)


def test_empty_text_is_not_affirmative() -> None:
    assert not is_affirmative("")
    assert not is_affirmative("   ")
