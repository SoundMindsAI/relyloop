# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Snippet ≡ runtime semantic-equality test (I-4 / AC-12).

For each non-``none`` choice, ``exec()`` the embedded PR-body snippet into a
fresh namespace, pull out its ``normalize_query``, and assert it produces
output identical to the production :func:`normalize` over a curated 10-element
corpus. Semantic — not byte — equality: the snippet inlines the dictionary
literal whereas the runtime imports the frozen ``_CONTRACTIONS``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.app.domain.study.normalizers import (
    _PR_BODY_NORMALIZER_SNIPPETS,
    normalize,
)

# 10-element corpus (spec AC-12): mixed-case, leading/trailing whitespace,
# ASCII-apostrophe contractions, the boundary cases "whatsoever" and
# "swhat's", the no-op input "", and a contraction-free / whitespace-free
# string.
_CORPUS = [
    "What's the BEST policy?",
    "  Trim Me  ",
    "MixedCaseNoSpaces",
    "whatsoever",
    "swhat's",
    "",
    "don't stop won't quit",
    "IT'S a TEST",
    "plainquery",
    "  they're HERE, we've ARRIVED  ",
]


def _load_snippet_fn(choice: str) -> Callable[[str], str]:
    snippet = _PR_BODY_NORMALIZER_SNIPPETS[choice]
    namespace: dict[str, object] = {}
    exec(snippet, namespace)  # noqa: S102 — trusted, in-repo static snippet
    fn = namespace["normalize_query"]
    assert callable(fn)
    return fn  # type: ignore[return-value]


@pytest.mark.parametrize("choice", list(_PR_BODY_NORMALIZER_SNIPPETS.keys()))
def test_snippet_matches_runtime_over_corpus(choice: str) -> None:
    snippet_fn = _load_snippet_fn(choice)
    for text in _CORPUS:
        assert snippet_fn(text) == normalize(text, choice), (
            f"snippet/runtime drift for choice={choice!r} on input {text!r}"
        )


def test_expand_contractions_snippet_produces_expected_output() -> None:
    # Anchor the semantic check with a concrete expectation, so a corpus that
    # accidentally matched a broken implementation can't pass silently.
    fn = _load_snippet_fn("lowercase+trim+expand_contractions")
    assert fn("  WHAT'S up  ") == "what is up"


def test_none_choice_has_no_snippet() -> None:
    # FR-5 short-circuit: "none" is intentionally absent from the snippet map.
    assert "none" not in _PR_BODY_NORMALIZER_SNIPPETS
