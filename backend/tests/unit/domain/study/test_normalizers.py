# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the query-time normalizer library (AC-1).

Covers the four built-in choices over a representative input bank, the
word-boundary contraction guard, the smart-quote expansion (FR-3 — U+2019
is pre-normalized before matching), the unknown-choice ValueError, and the
exact-30-entry dictionary size.
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.normalizers import (
    _CONTRACTIONS,
    DEFAULT_NORMALIZER,
    NORMALIZER_CHOICES,
    normalize,
)


def test_normalizer_choices_are_the_four_canonical_values() -> None:
    assert NORMALIZER_CHOICES == (
        "none",
        "lowercase",
        "lowercase+trim",
        "lowercase+trim+expand_contractions",
    )


def test_default_normalizer_is_none() -> None:
    # Value-lock: the adapter fallback + compute_default_params both rely on
    # this being literally "none" (a no-op transform).
    assert DEFAULT_NORMALIZER == "none"


def test_contraction_dictionary_has_exactly_thirty_entries() -> None:
    assert len(_CONTRACTIONS) == 30


# --- AC-1 canonical examples -------------------------------------------------


def test_lowercase_trim_strips_and_folds() -> None:
    assert normalize("  Hello World  ", "lowercase+trim") == "hello world"
    # Spec AC-1 trailing-only whitespace example.
    assert normalize("Hello World ", "lowercase+trim") == "hello world"


def test_expand_contractions_canonical_example() -> None:
    assert (
        normalize("WHAT'S the deal?", "lowercase+trim+expand_contractions") == "what is the deal?"
    )
    assert (
        normalize("What's the BEST policy?", "lowercase+trim+expand_contractions")
        == "what is the best policy?"
    )


def test_expand_contractions_word_boundary_right() -> None:
    # "whatsoever" must NOT expand — no apostrophe, no boundary match.
    assert normalize("whatsoever", "lowercase+trim+expand_contractions") == "whatsoever"


def test_expand_contractions_word_boundary_left() -> None:
    # "swhat's" must NOT expand — the char before the alternative is a word
    # char, so there is no left word boundary.
    assert normalize("swhat's", "lowercase+trim+expand_contractions") == "swhat's"


def test_unknown_choice_raises_value_error_naming_the_choice() -> None:
    with pytest.raises(ValueError) as exc:
        normalize("anything", "stem")
    assert "stem" in str(exc.value)
    assert str(exc.value) == "unknown normalizer: stem"


def test_none_is_verbatim_passthrough() -> None:
    # Including whitespace + casing untouched — "none" is a true no-op.
    assert normalize("  HeLLo  What's ", "none") == "  HeLLo  What's "


def test_lowercase_only_does_not_trim() -> None:
    assert normalize("  HELLO  ", "lowercase") == "  hello  "


def test_smart_quote_contraction_now_expands() -> None:
    # feat_query_normalizer_typed_pipeline FR-3: U+2019 smart-quote
    # apostrophes ARE now pre-normalized to U+0027 before contraction
    # matching, so "what’s" expands identically to its ASCII form. (This
    # supersedes Phase 1's D-7 round-trips-unchanged behavior.)
    assert normalize("What’s up", "lowercase+trim+expand_contractions") == "what is up"


# --- Cartesian sweep: {4 choices} x {input bank} -----------------------------

_INPUT_BANK = [
    "Hello World",
    "  leading and trailing  ",
    "MixedCase QUERY",
    "",
    "a",
    "what's going on",
    "WHATSOEVER",
    "don't won't can't",
    "no contractions here",
    "What’s smart",
]


@pytest.mark.parametrize("choice", NORMALIZER_CHOICES)
@pytest.mark.parametrize("text", _INPUT_BANK)
def test_normalize_is_total_over_choices_and_inputs(text: str, choice: str) -> None:
    # Every (choice, input) pair returns a str and never raises.
    out = normalize(text, choice)
    assert isinstance(out, str)
    if choice == "none":
        assert out == text
    elif choice == "lowercase":
        assert out == text.lower()
    elif choice == "lowercase+trim":
        assert out == text.lower().strip()
    else:  # lowercase+trim+expand_contractions
        # At minimum, the result is lowercased + trimmed; expansion only
        # adds substitutions, never changes case/whitespace handling.
        assert out == out.strip()
        assert out == out.lower()
