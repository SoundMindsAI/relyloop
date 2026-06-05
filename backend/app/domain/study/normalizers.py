# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-time normalizer library (feat_query_normalization_tuning, MVP2).

A pure-domain module that turns light query-understanding-stage string
rewriting — case folding, whitespace trimming, English contraction
expansion — into a tunable, opt-in query-time parameter the Optuna loop
can search over. The reserved Categorical search-space key is
``query_normalizer``; the four built-in choices are listed in
``NORMALIZER_CHOICES``.

Module invariants (spec §7):

* **Pure** — no async, no DB, no httpx, no ``openai`` import. The
  ``_CONTRACTIONS`` mapping is a module-level constant (no runtime
  loading) frozen via :class:`types.MappingProxyType`.
* **Consumption is adapter-confined (I-2)** — only
  :meth:`ElasticAdapter.render` and :meth:`SolrAdapter.render` call
  :func:`normalize`. Workers pass ``params`` through opaquely.
* **Snippet ≡ runtime (I-4)** — ``_PR_BODY_NORMALIZER_SNIPPETS`` carries a
  copy-pasteable Python implementation per choice; a unit test
  (``test_normalizers_pr_snippets.py``) asserts each snippet's
  ``normalize_query`` produces output identical to :func:`normalize` over
  a curated corpus, so the PR body the operator copies can never drift
  from what the loop actually applied.
"""

from __future__ import annotations

import re
import types
from collections.abc import Mapping
from typing import Final

from backend.app.domain.study.search_space import CategoricalParam, SearchSpace

NORMALIZER_CHOICES: Final[tuple[str, str, str, str]] = (
    "none",
    "lowercase",
    "lowercase+trim",
    "lowercase+trim+expand_contractions",
)
"""The four built-in normalizer choices. Mirrored to the frontend via
``ui/src/lib/enums.ts`` ``NORMALIZER_VALUES`` (source-of-truth comment
points back here)."""

DEFAULT_NORMALIZER: Final[str] = "none"
"""The safe default when ``query_normalizer`` is absent from a params dict.
``normalize(qt, "none")`` returns ``qt`` verbatim, so applying the default
is a no-op for every template that hasn't opted in."""


# Exactly 30 entries — English-only, ASCII apostrophe (U+0027). Keys are
# lowercased because contraction expansion runs AFTER lowercasing, so the
# match input is always lowercase. Smart quotes (U+2019) are intentionally
# NOT matched in MVP2 (spec D-7; P3 deferred). Source: spec §9.
_CONTRACTIONS_RAW: dict[str, str] = {
    "ain't": "is not",
    "aren't": "are not",
    "can't": "cannot",
    "couldn't": "could not",
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "hadn't": "had not",
    "hasn't": "has not",
    "haven't": "have not",
    "he's": "he is",
    "i'd": "i would",
    "i'll": "i will",
    "i'm": "i am",
    "i've": "i have",
    "isn't": "is not",
    "it's": "it is",
    "let's": "let us",
    "shouldn't": "should not",
    "that's": "that is",
    "they're": "they are",
    "they've": "they have",
    "wasn't": "was not",
    "we're": "we are",
    "we've": "we have",
    "weren't": "were not",
    "what's": "what is",
    "won't": "will not",
    "wouldn't": "would not",
    "you're": "you are",
}

_CONTRACTIONS: Mapping[str, str] = types.MappingProxyType(_CONTRACTIONS_RAW)
"""Frozen 30-entry contraction map. Read-only — never mutate at runtime."""

# Built once at import. Sorted by key length descending so the longest
# contraction wins when one is a prefix of another. Word-boundary anchored
# (``\b...\b``) so ``what's`` expands but ``whatsoever`` / ``swhat's`` do
# not. Linear matching complexity — no ReDoS surface (spec §10 threat 2).
_CONTRACTION_PATTERN: re.Pattern[str] = re.compile(
    r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b"
)


def normalize(query_text: str, choice: str) -> str:
    """Apply the chosen normalizer to ``query_text``.

    Order for the bundled choices is always lowercase → trim → expand,
    each choice adding the next step:

    * ``none`` → returns ``query_text`` verbatim.
    * ``lowercase`` → ``query_text.lower()``.
    * ``lowercase+trim`` → ``.lower().strip()``.
    * ``lowercase+trim+expand_contractions`` → the above plus
      word-boundary-safe contraction expansion.

    Raises:
        ValueError: ``f"unknown normalizer: {choice}"`` when ``choice`` is
            not one of :data:`NORMALIZER_CHOICES`. The adapter render path
            surfaces this through the existing trial-failure handling.
    """
    if choice == "none":
        return query_text
    if choice == "lowercase":
        return query_text.lower()
    if choice == "lowercase+trim":
        return query_text.lower().strip()
    if choice == "lowercase+trim+expand_contractions":
        lowered = query_text.lower().strip()
        return _CONTRACTION_PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], lowered)
    raise ValueError(f"unknown normalizer: {choice}")


# Copy-pasteable reference implementations embedded verbatim into the PR
# body (FR-5). Keyed on the three non-``none`` choices — ``none`` has no
# snippet (the PR-body renderer short-circuits it). The
# expand-contractions snippet inlines the 30-entry dictionary literal so
# the operator can paste a self-contained function; I-4's test keeps that
# inline literal semantically in sync with the production ``_CONTRACTIONS``
# above. The byte content here is what AC-5 asserts the PR body embeds.
_LOWERCASE_SNIPPET: Final[str] = """\
def normalize_query(query_text: str) -> str:
    return query_text.lower()
"""

_LOWERCASE_TRIM_SNIPPET: Final[str] = """\
def normalize_query(query_text: str) -> str:
    return query_text.lower().strip()
"""

_LOWERCASE_TRIM_EXPAND_SNIPPET: Final[str] = r"""import re

_CONTRACTIONS = {
    "ain't": "is not",
    "aren't": "are not",
    "can't": "cannot",
    "couldn't": "could not",
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "hadn't": "had not",
    "hasn't": "has not",
    "haven't": "have not",
    "he's": "he is",
    "i'd": "i would",
    "i'll": "i will",
    "i'm": "i am",
    "i've": "i have",
    "isn't": "is not",
    "it's": "it is",
    "let's": "let us",
    "shouldn't": "should not",
    "that's": "that is",
    "they're": "they are",
    "they've": "they have",
    "wasn't": "was not",
    "we're": "we are",
    "we've": "we have",
    "weren't": "were not",
    "what's": "what is",
    "won't": "will not",
    "wouldn't": "would not",
    "you're": "you are",
}
_PATTERN = re.compile(
    r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b"
)


def normalize_query(query_text: str) -> str:
    lowered = query_text.lower().strip()
    return _PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], lowered)
"""

_PR_BODY_NORMALIZER_SNIPPETS: Mapping[str, str] = types.MappingProxyType(
    {
        "lowercase": _LOWERCASE_SNIPPET,
        "lowercase+trim": _LOWERCASE_TRIM_SNIPPET,
        "lowercase+trim+expand_contractions": _LOWERCASE_TRIM_EXPAND_SNIPPET,
    }
)
"""PR-body Python snippets keyed on the three non-``none`` choices.
``"none"`` is intentionally absent — the FR-5 renderer short-circuits it."""


class NormalizerChoiceInvalidError(ValueError):
    """A ``query_normalizer`` choice is not in :data:`NORMALIZER_CHOICES`.

    Router maps to HTTP 400 ``NORMALIZER_CHOICE_INVALID`` (spec §8.5).
    """


class NormalizerParamShapeError(ValueError):
    """``query_normalizer`` is declared but is not a ``CategoricalParam``.

    Router maps to HTTP 400 ``NORMALIZER_PARAM_SHAPE`` (spec §8.5).
    """


def validate_normalizer_reservation(space: SearchSpace) -> None:
    """Enforce invariant I-1 on the reserved ``query_normalizer`` key.

    No-op when ``"query_normalizer"`` is absent from ``space.params``.
    Otherwise the param MUST be a :class:`CategoricalParam` whose ``choices``
    are a (non-empty) subset of :data:`NORMALIZER_CHOICES`.

    Raises:
        NormalizerParamShapeError: the param is present but not a
            ``CategoricalParam``. Message: ``"query_normalizer must be
            CategoricalParam (got <actual_type_name>)"``.
        NormalizerChoiceInvalidError: a choice is outside the allowlist.
            Message names the first offender and the full allowed set, per
            spec FR-2.
    """
    param = space.params.get("query_normalizer")
    if param is None:
        return
    if not isinstance(param, CategoricalParam):
        raise NormalizerParamShapeError(
            f"query_normalizer must be CategoricalParam (got {type(param).__name__})"
        )
    for choice in param.choices:
        if choice not in NORMALIZER_CHOICES:
            raise NormalizerChoiceInvalidError(
                f"query_normalizer choice '{choice}' is not in the allowed set: "
                f"{list(NORMALIZER_CHOICES)}"
            )


__all__ = [
    "NORMALIZER_CHOICES",
    "DEFAULT_NORMALIZER",
    "normalize",
    "NormalizerChoiceInvalidError",
    "NormalizerParamShapeError",
    "validate_normalizer_reservation",
]
