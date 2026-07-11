# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Confirmation guard primitives (feat_chat_agent Story 2.5).

* :data:`MUTATING_TOOL_NAMES` — the 8-tool set requiring confirmation per spec
  FR-5 + §19 Decision log (+ ``generate_judgments_from_ubi`` from
  feat_ubi_judgments FR-6). ``create_query_set`` is intentionally NOT on this
  list (creating an empty container is cheap to undo).
* :func:`is_affirmative` — whole-word, case-insensitive matcher against a small
  affirmative-token vocabulary.
"""

from __future__ import annotations

import re

MUTATING_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "import_queries_from_csv",
        "generate_judgments_llm",
        # feat_ubi_judgments FR-6 — UBI judgment generation is equivalent to
        # the LLM path in operator commitment + data side-effects, so the
        # server-side confirmation guard enforces it too (not prompt-only).
        "generate_judgments_from_ubi",
        "create_study",
        "cancel_study",
        "create_proposal_from_study",
        "create_proposal_manual",
        "open_pr",
    }
)


# Single-word and short-phrase affirmatives. Whole-word matching against the
# single-word tokens; the short phrases match only when they LEAD the message
# (see ``_LEADING_AFFIRMATIVE_PHRASE``) so a mid-sentence occurrence in a
# non-authorizing reply does not count.
_AFFIRMATIVE_TOKENS: frozenset[str] = frozenset(
    {
        "yes",
        "y",
        "yep",
        "yeah",
        "ok",
        "okay",
        "go",
        "confirm",
        "confirmed",
        "proceed",
    }
)

_AFFIRMATIVE_PHRASES: tuple[str, ...] = (
    "go ahead",
    "do it",
    "ship it",
)

#: Regex matching an affirmative phrase only when it *leads* the message (after
#: optional leading punctuation/whitespace). Anchoring kills the false positive
#: where a phrase appears mid-sentence in a non-authorizing reply — e.g.
#: "maybe do it tomorrow" or "I'll do it later" contain "do it" as a substring
#: but are not authorizations. A leading "go ahead" / "do it" / "ship it" is a
#: genuine go-ahead. Built from :data:`_AFFIRMATIVE_PHRASES` so the two never drift.
_LEADING_AFFIRMATIVE_PHRASE = re.compile(
    r"^\W*(?:" + "|".join(re.escape(p) for p in _AFFIRMATIVE_PHRASES) + r")\b",
    re.IGNORECASE,
)


# Negation tokens that, if present, disqualify the message from being
# treated as affirmative — even if it also contains an affirmative token
# (per GPT-5.5 final-review F2 — without this, "don't do it" or "no go"
# matched the affirmative-phrase substring check and unlocked dispatch).
_NEGATION_TOKENS: frozenset[str] = frozenset(
    {
        "no",
        "not",
        "don",  # don't (apostrophe stripped by the [a-z] regex)
        "dont",
        "doesn",
        "doesnt",
        "won",  # won't
        "wont",
        "cancel",
        "stop",
        "abort",
        "wait",
        "nope",
        "never",
        # Deferral / inability tokens — a reply that contains these is not an
        # authorization even if it also carries an affirmative token ("ok" in
        # "ok thanks", "do it" in "can't do it right now" / "do it later").
        "can",  # can't (apostrophe stripped by the [a-z] regex) / "I can later"
        "cant",
        "cannot",
        "couldn",  # couldn't
        "couldnt",
        "maybe",
        "later",
    }
)


def is_affirmative(text: str) -> bool:
    """Return ``True`` if ``text`` reads as user affirmation of a mutating action.

    Heuristic — acceptable for MVP1; a strict state-machine confirmation can
    land at MVP2 if the heuristic misfires. Case-insensitive; whole-word
    matching on single-word tokens so "yes" matches "Yes!" but not "yesterday".
    Rejects messages containing negation tokens before checking for
    affirmation, so "don't do it", "no go", "stop, do it later" all return
    False even though they contain affirmative phrases.
    """
    if not text:
        return False
    lowered = text.lower()
    words = set(re.findall(r"[a-z]+", lowered))
    if _NEGATION_TOKENS & words:
        return False
    # Affirmative *phrases* must LEAD the message (anchored) so a mid-sentence
    # "do it" in "I'll do it later" doesn't unlock dispatch — the leading
    # negation/deferral tokens above already reject most of those, this closes
    # the residual where no negation token is present.
    if _LEADING_AFFIRMATIVE_PHRASE.match(lowered):
        return True
    return bool(_AFFIRMATIVE_TOKENS & words)
