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
* **Snippet ≡ runtime (I-4 / FR-5)** — :func:`build_python_snippet` and
  :func:`build_js_snippet` GENERATE copy-pasteable reference implementations
  from a winning label's step list (any of the 2^N powerset labels, not just
  the four Phase 1 bundles). ``test_normalizers_pr_snippets.py`` (Python) and
  ``ui/src/__tests__/normalizer-snippet-parity.test.ts`` (JS, over a committed
  shared corpus fixture) assert three-way output parity with
  :func:`normalize_pipeline`, so the PR body the operator copies can never
  drift from what the loop actually applied.
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


# --- Copy-pasteable reference snippet GENERATORS (FR-4) ---------------------
#
# The PR body embeds a Python AND a JS/TS reference implementation of the
# winning normalizer so the operator can reproduce it in their query layer.
# Because a typed pipeline can win on any of the 2^N powerset labels — not
# just Phase 1's four bundles — the snippets are GENERATED from the winning
# label's step list (not looked up from a fixed map). ``"none"`` has no
# snippet (the renderer short-circuits it). Both generators emit the
# contraction dict/pattern preamble ONLY when ``expand_contractions_en`` is
# present, and a commented no-op line for the inert
# ``expand_contractions_custom`` step, so the snippet stays faithful to
# :func:`normalize_pipeline` (FR-5 three-way output parity). Both INCLUDE the
# U+2019 smart-quote pre-normalization (FR-3), which is why they intentionally
# differ from Phase 1's original bundle snippets (which predate FR-3).


def _contraction_dict_lines(indent: str) -> list[str]:
    """Render the 30-entry contraction map as dict/object-literal lines.

    The ``"key": "value",`` form is valid in both Python and JS (trailing
    comma allowed in both), so one renderer serves both snippet generators.
    """
    return [f'{indent}"{k}": "{v}",' for k, v in _CONTRACTIONS_RAW.items()]


def build_python_snippet(steps: Sequence[NormalizerStep]) -> str:
    """Generate a self-contained ``normalize_query`` Python reference for ``steps``.

    Output-faithful to :func:`normalize_pipeline` over any input (FR-5).
    """
    ordered = [s for s in STEP_ORDER if s in set(steps)]
    needs_contractions = NormalizerStep.expand_contractions_en in ordered
    needs_re = needs_contractions or NormalizerStep.collapse_whitespace in ordered
    needs_punct = NormalizerStep.strip_punctuation in ordered

    head: list[str] = []
    if needs_re:
        head.append("import re")
        head.append("")
    if needs_punct:
        head.append(f"_PUNCTUATION = {_PUNCTUATION_TO_STRIP!r}")
    if needs_contractions:
        head.append("_CONTRACTIONS = {")
        head.extend(_contraction_dict_lines("    "))
        head.append("}")
        head.append(
            "_CONTRACTION_PATTERN = re.compile(\n"
            '    r"\\b(" + "|".join(map(re.escape, '
            'sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\\b"\n'
            ")"
        )
    if head and head[-1] != "":
        head.append("")
        head.append("")

    body = ["def normalize_query(query_text: str) -> str:", "    q = query_text"]
    for step in ordered:
        if step is NormalizerStep.lowercase:
            body.append("    q = q.lower()")
        elif step is NormalizerStep.strip_punctuation:
            body.append('    q = "".join(c for c in q if c not in _PUNCTUATION)')
        elif step is NormalizerStep.expand_contractions_en:
            body.append('    q = q.replace("\\u2019", "\'")')
            body.append("    q = _CONTRACTION_PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], q)")
        elif step is NormalizerStep.expand_contractions_custom:
            body.append("    # (custom contractions reserved — no-op)")
        elif step is NormalizerStep.collapse_whitespace:
            body.append('    q = re.sub(r"\\s+", " ", q)')
        elif step is NormalizerStep.trim:
            body.append("    q = q.strip()")
    body.append("    return q")
    return "\n".join(head + body) + "\n"


def build_js_snippet(steps: Sequence[NormalizerStep]) -> str:
    """Generate a self-contained ``normalizeQuery`` JS/TS reference for ``steps``.

    Output-faithful to :func:`normalize_pipeline` (FR-5); each runtime is
    parity-tested in its own suite (Q-2 — JS via a frontend vitest fixture).
    """
    ordered = [s for s in STEP_ORDER if s in set(steps)]
    needs_contractions = NormalizerStep.expand_contractions_en in ordered
    needs_punct = NormalizerStep.strip_punctuation in ordered
    # JS double-quoted literal of the punctuation set (escape " and \).
    punct_js = _PUNCTUATION_TO_STRIP.replace("\\", "\\\\").replace('"', '\\"')

    lines = ["function normalizeQuery(queryText) {", "  let q = queryText;"]
    if needs_punct:
        lines.append(f'  const PUNCTUATION = "{punct_js}";')
    if needs_contractions:
        lines.append("  const CONTRACTIONS = {")
        lines.extend(_contraction_dict_lines("    "))
        lines.append("  };")
        lines.append(
            "  const KEYS = Object.keys(CONTRACTIONS).sort((a, b) => b.length - a.length);"
        )
        lines.append('  const PATTERN = new RegExp("\\\\b(" + KEYS.join("|") + ")\\\\b", "g");')
    for step in ordered:
        if step is NormalizerStep.lowercase:
            lines.append("  q = q.toLowerCase();")
        elif step is NormalizerStep.strip_punctuation:
            lines.append('  q = q.split("").filter((c) => !PUNCTUATION.includes(c)).join("");')
        elif step is NormalizerStep.expand_contractions_en:
            lines.append('  q = q.replace(/\\u2019/g, "\'");')
            lines.append("  q = q.replace(PATTERN, (m) => CONTRACTIONS[m]);")
        elif step is NormalizerStep.expand_contractions_custom:
            lines.append("  // (custom contractions reserved — no-op)")
        elif step is NormalizerStep.collapse_whitespace:
            lines.append('  q = q.replace(/\\s+/g, " ");')
        elif step is NormalizerStep.trim:
            lines.append("  q = q.trim();")
    lines.append("  return q;")
    lines.append("}")
    return "\n".join(lines) + "\n"


class NormalizerChoiceInvalidError(ValueError):
    """A ``query_normalizer`` choice is not in :data:`NORMALIZER_CHOICES`.

    Router maps to HTTP 400 ``NORMALIZER_CHOICE_INVALID`` (spec §8.5).
    """


class NormalizerParamShapeError(ValueError):
    """``query_normalizer`` is neither a ``CategoricalParam`` nor a pipeline.

    Router maps to HTTP 400 ``NORMALIZER_PARAM_SHAPE`` (spec §8.5).
    """


class NormalizerPipelineMisplacedError(ValueError):
    """A ``normalizer_pipeline`` param is declared under a non-reserved key.

    The adapter pre-render hook only consumes the ``query_normalizer`` key,
    so a pipeline param anywhere else would be sampled + persisted but never
    applied — a silent no-op. Router maps to HTTP 400 ``INVALID_SEARCH_SPACE``
    (feat_query_normalizer_typed_pipeline FR-8, D-8 — no new error code).
    """


def validate_normalizer_reservation(space: SearchSpace) -> None:
    """Enforce the reserved ``query_normalizer`` key contract.

    Two rules:

    1. **Reserved-key-only (FR-8):** a ``normalizer_pipeline`` param is valid
       ONLY under ``query_normalizer``. Found under any other key, it raises
       :exc:`NormalizerPipelineMisplacedError` (the adapter only applies the
       reserved key, so it would otherwise be a silent no-op). A
       ``CategoricalParam`` under arbitrary keys remains valid.
    2. **Reserved-key shape:** when ``query_normalizer`` is present it MUST be
       either a :class:`NormalizerPipelineParam` (accepted — steps are already
       enum-constrained + duplicate-checked at the Pydantic boundary) or a
       :class:`CategoricalParam` whose ``choices`` subset
       :data:`NORMALIZER_CHOICES`.

    No-op when ``"query_normalizer"`` is absent and no misplaced pipeline
    param exists.

    Raises:
        NormalizerPipelineMisplacedError: a ``normalizer_pipeline`` param is
            declared under a non-``query_normalizer`` key. → ``INVALID_SEARCH_SPACE``.
        NormalizerParamShapeError: ``query_normalizer`` is present but is
            neither a ``CategoricalParam`` nor a ``NormalizerPipelineParam``.
        NormalizerChoiceInvalidError: a Categorical choice is outside the
            allowlist (names the first offender + the full allowed set).
    """
    # Function-local import breaks the module cycle: search_space.py imports
    # NormalizerStep / _pipeline_labels from this module at top level, so this
    # module must NOT import search_space at module level (the annotation is
    # lazy via `from __future__ import annotations`).
    from backend.app.domain.study.search_space import CategoricalParam

    # Rule 1 — reserved-key-only. Discriminate on the `type` discriminator
    # string (NOT isinstance) so no NormalizerPipelineParam import is needed,
    # keeping the module cycle-free.
    for name, spec in space.params.items():
        if name == "query_normalizer":
            continue
        if getattr(spec, "type", None) == "normalizer_pipeline":
            raise NormalizerPipelineMisplacedError(
                f"normalizer_pipeline params are only valid under the reserved key "
                f"'query_normalizer' (found under '{name}')"
            )

    param = space.params.get("query_normalizer")
    if param is None:
        return
    # Rule 2 — accept the typed pipeline shape under the reserved key.
    if getattr(param, "type", None) == "normalizer_pipeline":
        return
    if not isinstance(param, CategoricalParam):
        raise NormalizerParamShapeError(
            f"query_normalizer must be CategoricalParam or NormalizerPipelineParam "
            f"(got {type(param).__name__})"
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
    "build_python_snippet",
    "build_js_snippet",
    "NormalizerChoiceInvalidError",
    "NormalizerParamShapeError",
    "NormalizerPipelineMisplacedError",
    "validate_normalizer_reservation",
]
