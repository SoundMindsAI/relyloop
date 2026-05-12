"""Confirmation guard primitives (feat_chat_agent Story 2.5).

* :data:`MUTATING_TOOL_NAMES` — the 7-tool set requiring confirmation per spec
  FR-5 + §19 Decision log. ``create_query_set`` is intentionally NOT on this
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


def is_affirmative(text: str) -> bool:
    """Return ``True`` if ``text`` reads as user affirmation of a mutating action.

    Heuristic — acceptable for MVP1; a strict state-machine confirmation can
    land at MVP2 if the heuristic misfires. Case-insensitive; whole-word
    matching on single-word tokens so "yes" matches "Yes!" but not "yesterday".
    """
    if not text:
        return False
    lowered = text.lower()
    for phrase in _AFFIRMATIVE_PHRASES:
        if phrase in lowered:
            return True
    # Whole-word check on single-token affirmatives.
    words = set(re.findall(r"[a-z]+", lowered))
    return bool(_AFFIRMATIVE_TOKENS & words)
