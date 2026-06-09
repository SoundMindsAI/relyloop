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
import string
import types
from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import combinations
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from backend.app.domain.study.search_space import SearchSpace

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
# match input is always lowercase. The Unicode right single quote (U+2019)
# is pre-normalized to U+0027 by the expand-contractions step before this
# pattern runs (feat_query_normalizer_typed_pipeline FR-3), so smart-quote
# contractions ("what’s") now expand identically to their ASCII form.
# Source: spec §9.
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

# Unicode right single quotation mark → ASCII apostrophe. Only U+2019 is
# pre-normalized (FR-3 scope note): it is the dominant smart-quote produced
# by word processors and mobile keyboards; U+2018 / U+02BC are vanishingly
# rare in search queries and excluded by design.
_SMART_APOSTROPHE: Final[str] = "’"

# ASCII punctuation EXCLUDING the apostrophe (U+0027), which the contraction
# step needs intact. ``strip_punctuation`` removes this set.
_PUNCTUATION_TO_STRIP: Final[str] = string.punctuation.replace("'", "")
_PUNCTUATION_PATTERN: re.Pattern[str] = re.compile("[" + re.escape(_PUNCTUATION_TO_STRIP) + "]")


class NormalizerStep(StrEnum):
    """The six atomic normalizer steps a typed pipeline can declare.

    Wire values are mirrored to the frontend via
    ``ui/src/lib/enums.ts`` ``NORMALIZER_STEP_VALUES`` (source-of-truth
    comment points back here). ``expand_contractions_custom`` is reserved
    for Phase 2.5 / Capability D — in this phase it is **declared but
    inert**: declaring it is accepted and applies no transform (Q-1 locked
    2026-06-09; the glossary tooltip flags it "reserved / not yet active").
    """

    lowercase = "lowercase"
    trim = "trim"
    collapse_whitespace = "collapse_whitespace"
    strip_punctuation = "strip_punctuation"
    expand_contractions_en = "expand_contractions_en"
    expand_contractions_custom = "expand_contractions_custom"


# Canonical APPLICATION order (D-11). The two whitespace-cleanup steps
# (collapse_whitespace, trim) MUST run LAST because strip_punctuation and
# expand_contractions both perturb whitespace — running cleanup afterward
# guarantees no doubled/trailing spaces regardless of co-selected steps.
STEP_ORDER: Final[tuple[NormalizerStep, ...]] = (
    NormalizerStep.lowercase,
    NormalizerStep.strip_punctuation,
    NormalizerStep.expand_contractions_en,
    NormalizerStep.expand_contractions_custom,
    NormalizerStep.collapse_whitespace,
    NormalizerStep.trim,
)

# Serialized-LABEL order (D-12) — DECOUPLED from STEP_ORDER and kept
# Phase-1-compatible so the subset {lowercase, trim, expand_contractions_en}
# serializes to "lowercase+trim+expand_contractions" (byte-identical to
# Phase 1's bundle string). If the label used STEP_ORDER it would serialize
# to "lowercase+expand_contractions+trim", breaking backward compat.
LABEL_ORDER: Final[tuple[NormalizerStep, ...]] = (
    NormalizerStep.lowercase,
    NormalizerStep.trim,
    NormalizerStep.expand_contractions_en,
    NormalizerStep.collapse_whitespace,
    NormalizerStep.strip_punctuation,
    NormalizerStep.expand_contractions_custom,
)

# Each step's label token. expand_contractions_en serializes to the
# Phase-1-compatible "expand_contractions" (NOT "expand_contractions_en");
# all others use their own wire value. Tokens are pairwise distinct, so the
# subset↔label mapping is a bijection.
STEP_LABEL_TOKEN: Final[Mapping[NormalizerStep, str]] = types.MappingProxyType(
    {
        NormalizerStep.lowercase: "lowercase",
        NormalizerStep.trim: "trim",
        NormalizerStep.collapse_whitespace: "collapse_whitespace",
        NormalizerStep.strip_punctuation: "strip_punctuation",
        NormalizerStep.expand_contractions_en: "expand_contractions",
        NormalizerStep.expand_contractions_custom: "expand_contractions_custom",
    }
)

_TOKEN_TO_STEP: Final[Mapping[str, NormalizerStep]] = types.MappingProxyType(
    {token: step for step, token in STEP_LABEL_TOKEN.items()}
)

# Phase 1's four bundle strings → their equivalent step tuples. Lets the
# bundle path and the pipeline path share one execution engine.
_BUNDLE_TO_STEPS: Final[Mapping[str, tuple[NormalizerStep, ...]]] = types.MappingProxyType(
    {
        "none": (),
        "lowercase": (NormalizerStep.lowercase,),
        "lowercase+trim": (NormalizerStep.lowercase, NormalizerStep.trim),
        "lowercase+trim+expand_contractions": (
            NormalizerStep.lowercase,
            NormalizerStep.trim,
            NormalizerStep.expand_contractions_en,
        ),
    }
)


def _apply_step(text: str, step: NormalizerStep) -> str:
    """Apply a single normalizer step. Pure; no I/O."""
    if step is NormalizerStep.lowercase:
        return text.lower()
    if step is NormalizerStep.strip_punctuation:
        return _PUNCTUATION_PATTERN.sub("", text)
    if step is NormalizerStep.expand_contractions_en:
        pre = text.replace(_SMART_APOSTROPHE, "'")
        return _CONTRACTION_PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], pre)
    if step is NormalizerStep.expand_contractions_custom:
        return text  # inert in Phase 2 (Q-1: reserved, no-op)
    if step is NormalizerStep.collapse_whitespace:
        return re.sub(r"\s+", " ", text)
    if step is NormalizerStep.trim:
        return text.strip()
    raise ValueError(f"unknown normalizer step: {step!r}")  # pragma: no cover


def normalize_pipeline(query_text: str, steps: Sequence[NormalizerStep]) -> str:
    """Apply the declared ``steps`` to ``query_text`` in canonical order.

    The declared steps are filtered and reordered by :data:`STEP_ORDER`
    (NOT declaration order), so the result is permutation-invariant: the
    same set of steps always produces the same output (I-1). An empty step
    set returns ``query_text`` verbatim. Pure, deterministic, no I/O.
    """
    selected = set(steps)
    result = query_text
    for step in STEP_ORDER:
        if step in selected:
            result = _apply_step(result, step)
    return result


def _label_for_subset(subset: frozenset[NormalizerStep]) -> str:
    """Canonical ``+``-joined label for a step subset (``"none"`` if empty).

    Steps are ordered by :data:`LABEL_ORDER` and mapped through
    :data:`STEP_LABEL_TOKEN`, so the label is deterministic and independent
    of declaration order.
    """
    if not subset:
        return "none"
    return "+".join(STEP_LABEL_TOKEN[s] for s in LABEL_ORDER if s in subset)


def _pipeline_labels(steps: Sequence[NormalizerStep]) -> list[str]:
    """The deterministic powerset label list for ``steps``.

    One canonical label per subset (including the empty subset → ``"none"``),
    ordered ascending by subset size then lexicographically by label string,
    so Optuna sees a stable categorical choice order across runs.
    """
    items = [s for s in STEP_ORDER if s in set(steps)]
    sized_labels: list[tuple[int, str]] = []
    for r in range(len(items) + 1):
        for combo in combinations(items, r):
            sized_labels.append((r, _label_for_subset(frozenset(combo))))
    sized_labels.sort(key=lambda t: (t[0], t[1]))
    return [label for _, label in sized_labels]


def steps_for_label(label: str) -> tuple[NormalizerStep, ...]:
    """Reverse of :func:`_label_for_subset` — a label → its step tuple.

    Accepts both Phase 1 bundle strings and pipeline powerset labels (a
    bundle IS a label whose tokens are a subset of the step vocabulary).
    ``"none"`` → ``()``. Returned steps are ordered by :data:`STEP_ORDER`.
    Shared by the adapter pre-render hook (Story 1.4) and the PR-body
    snippet generator (Story 2.1).

    Raises:
        ValueError: a ``+``-delimited token is not a known label token.
    """
    if label == "none":
        return ()
    resolved: set[NormalizerStep] = set()
    for token in label.split("+"):
        step = _TOKEN_TO_STEP.get(token)
        if step is None:
            raise ValueError(f"unknown normalizer label token {token!r} in label {label!r}")
        resolved.add(step)
    return tuple(s for s in STEP_ORDER if s in resolved)


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

    Implemented as a thin wrapper over :func:`normalize_pipeline` via
    :data:`_BUNDLE_TO_STEPS` (D-6) — the bundle path and the typed-pipeline
    path share one execution engine. ``test_normalizers_bundle_compat.py``
    asserts byte-identical output to Phase 1's hand-rolled branches (I-3).
    """
    steps = _BUNDLE_TO_STEPS.get(choice)
    if steps is None:
        raise ValueError(f"unknown normalizer: {choice}")
    return normalize_pipeline(query_text, steps)


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
    # Function-local import breaks the module cycle: search_space.py imports
    # NormalizerStep / _pipeline_labels from this module at top level, so this
    # module must NOT import search_space at module level (the annotation is
    # lazy via `from __future__ import annotations`).
    from backend.app.domain.study.search_space import CategoricalParam

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
    "NormalizerStep",
    "STEP_ORDER",
    "LABEL_ORDER",
    "STEP_LABEL_TOKEN",
    "normalize",
    "normalize_pipeline",
    "steps_for_label",
    "NormalizerChoiceInvalidError",
    "NormalizerParamShapeError",
    "validate_normalizer_reservation",
]
