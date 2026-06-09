# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Snippet ≡ runtime semantic-equality test (I-4 / FR-5, Python side).

For each non-``none`` label, ``exec()`` the GENERATED Python snippet
(``build_python_snippet``) into a fresh namespace, pull out its
``normalize_query``, and assert it produces output identical to the
production :func:`normalize_pipeline` over a curated corpus. Semantic — not
byte — equality: the snippet inlines the dictionary literal whereas the
runtime imports the frozen ``_CONTRACTIONS``. The JS side of the three-way
parity lives in ``ui/src/__tests__/normalizer-snippet-parity.test.ts``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.app.domain.study.normalizers import (
    NormalizerStep,
    build_python_snippet,
    normalize_pipeline,
    steps_for_label,
)

S = NormalizerStep

# Corpus: mixed-case, leading/trailing whitespace, ASCII-apostrophe
# contractions, the boundary cases "whatsoever"/"swhat's", the no-op "",
# punctuation, doubled whitespace, and a U+2019 smart-quote input (FR-3).
_CORPUS = [
    "What's the BEST policy?",
    "  Trim Me  ",
    "MixedCaseNoSpaces",
    "whatsoever",
    "swhat's",
    "",
    "don't stop, won't quit!",
    "IT'S a TEST",
    "they’re HERE",
    "a , b  c",
]

# A representative label set spanning bundles, single steps, non-bundle
# combinations, and the inert custom step.
_LABELS = [
    "lowercase",
    "trim",
    "collapse_whitespace",
    "strip_punctuation",
    "expand_contractions",
    "expand_contractions_custom",
    "lowercase+trim",
    "lowercase+trim+expand_contractions",
    "collapse_whitespace+strip_punctuation",
    "expand_contractions+strip_punctuation",
    "lowercase+expand_contractions_custom",
]


def _load_snippet_fn(label: str) -> Callable[[str], str]:
    snippet = build_python_snippet(steps_for_label(label))
    namespace: dict[str, object] = {}
    exec(snippet, namespace)  # noqa: S102 — trusted, in-repo generated snippet
    fn = namespace["normalize_query"]
    assert callable(fn)
    return fn


@pytest.mark.parametrize("label", _LABELS)
def test_snippet_matches_runtime_over_corpus(label: str) -> None:
    snippet_fn = _load_snippet_fn(label)
    steps = steps_for_label(label)
    for text in _CORPUS:
        assert snippet_fn(text) == normalize_pipeline(text, steps), (
            f"snippet/runtime drift for label={label!r} on input {text!r}"
        )


def test_expand_contractions_snippet_produces_expected_output() -> None:
    # Anchor the semantic check with a concrete expectation.
    fn = _load_snippet_fn("lowercase+trim+expand_contractions")
    assert fn("  WHAT'S up  ") == "what is up"


def test_smart_quote_snippet_expands() -> None:
    # FR-3 parity: the generated snippet pre-normalizes U+2019.
    fn = _load_snippet_fn("lowercase+trim+expand_contractions")
    assert fn("what’s up") == "what is up"


def test_custom_step_renders_inert_no_op_comment() -> None:
    snippet = build_python_snippet([S.expand_contractions_custom])
    assert "custom contractions reserved" in snippet
    fn = _load_snippet_fn("expand_contractions_custom")
    assert fn("don't stop") == "don't stop"
