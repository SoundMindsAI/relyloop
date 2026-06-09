# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Byte-parity guard: ``normalize`` (now a ``normalize_pipeline`` wrapper)
reproduces Phase 1's four-bundle outputs exactly (AC-5 / I-3, D-6).

``normalize`` was reimplemented over :func:`normalize_pipeline` via
``_BUNDLE_TO_STEPS`` to eliminate duplicate normalization logic. This test
pins the equivalence to a hand-rolled reference matching Phase 1's original
branch logic, so the refactor can never silently drift the bundle path.
"""

from __future__ import annotations

import re

import pytest

from backend.app.domain.study.normalizers import (
    _CONTRACTIONS,
    NORMALIZER_CHOICES,
    normalize,
)

_REF_PATTERN = re.compile(
    r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b"
)


def _phase1_reference(query_text: str, choice: str) -> str:
    """The exact branch logic Phase 1's ``normalize`` shipped (ASCII only)."""
    if choice == "none":
        return query_text
    if choice == "lowercase":
        return query_text.lower()
    if choice == "lowercase+trim":
        return query_text.lower().strip()
    if choice == "lowercase+trim+expand_contractions":
        lowered = query_text.lower().strip()
        return _REF_PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], lowered)
    raise ValueError(f"unknown normalizer: {choice}")


# Phase 1's AC-1 corpus is ASCII-apostrophe only (smart quotes are the FR-3
# delta and are intentionally NOT in the byte-parity corpus).
_ASCII_CORPUS = [
    "Hello World",
    "  leading and trailing  ",
    "MixedCase QUERY",
    "",
    "a",
    "what's going on",
    "WHATSOEVER",
    "don't won't can't",
    "no contractions here",
    "I'm sure it's fine",
    "  WHAT'S  the   policy  ",
]


@pytest.mark.parametrize("choice", NORMALIZER_CHOICES)
@pytest.mark.parametrize("text", _ASCII_CORPUS)
def test_normalize_byte_identical_to_phase1_reference(text: str, choice: str) -> None:
    assert normalize(text, choice) == _phase1_reference(text, choice)
