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
    ],
)
def test_negation_blocks_otherwise_affirmative_text(text: str) -> None:
    assert not is_affirmative(text)


def test_empty_text_is_not_affirmative() -> None:
    assert not is_affirmative("")
    assert not is_affirmative("   ")
