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
# single-word tokens; substring presence is sufficient for the short phrases.
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
    for phrase in _AFFIRMATIVE_PHRASES:
        if phrase in lowered:
            return True
    return bool(_AFFIRMATIVE_TOKENS & words)
