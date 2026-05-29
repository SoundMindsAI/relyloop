"""Snapshot test for ``prompts/orchestrator.system.md`` inventory (Story 4.1 / spec FR-5).

Locks the four AC-16 invariants:

1. Tool count phrasing names 20 tools (was 19 before feat_agent_propose_search_space).
2. Studies inventory line names ``propose_search_space`` FIRST in the
   "Studies (4)" row.
3. The mutation-set bullet (Rule #2) does NOT contain ``propose_search_space``
   (it's read-only).
4. The prompt contains a "before calling create_study" chain-guidance phrase
   so the LLM is steered to call propose first.

Failure means the prompt drifted from the implementation; update either the
prompt or this test, not both silently.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "orchestrator.system.md"


def _read_prompt() -> str:
    return _PROMPT_PATH.read_text()


def test_prompt_file_exists() -> None:
    assert _PROMPT_PATH.is_file(), f"orchestrator.system.md missing at {_PROMPT_PATH}"


def test_tool_count_says_twenty_one() -> None:
    """Locked: prompt says "You have 21 tools" — MVP1 = 20, +1 for UBI
    (feat_ubi_judgments Story 3.4)."""
    prompt = _read_prompt()
    assert "You have 21 tools" in prompt, (
        "Tool count phrase must match the registry's EXPECTED_TOOL_COUNT"
    )


def test_studies_section_includes_propose_search_space_first() -> None:
    """Locked: Studies row names propose_search_space first, before create_study/get/cancel."""
    prompt = _read_prompt()
    # Match either the exact bullet line or wrap-anywhere within the bullet.
    match = re.search(r"\*\*Studies \(4\):\*\*\s*`propose_search_space`", prompt)
    assert match is not None, (
        "Studies bullet must read '**Studies (4):** `propose_search_space`, ...'"
    )


def test_propose_search_space_not_in_mutation_list() -> None:
    """The 7-tool mutation set (Rule #2) MUST NOT include propose_search_space."""
    prompt = _read_prompt()
    # Pull Rule #2's text — it starts at "2. **Mutating tools" and runs until rule 3.
    rule_2_match = re.search(r"2\. \*\*Mutating tools.*?(?=\n3\. )", prompt, re.DOTALL)
    assert rule_2_match is not None, "Rule 2 (Mutating tools) section not found"
    rule_2_text = rule_2_match.group(0)
    assert "propose_search_space" not in rule_2_text, (
        "propose_search_space is read-only and MUST NOT appear in the mutation set"
    )


def test_chain_guidance_present() -> None:
    """The prompt instructs the LLM to call propose_search_space before create_study."""
    prompt = _read_prompt()
    # Match flexible phrasing — "before create_study", "Chain ... before",
    # "propose_search_space before create_study", etc.
    assert re.search(
        r"propose_search_space.*before.*create_study",
        prompt,
        re.DOTALL | re.IGNORECASE,
    ), "Prompt must direct the LLM to call propose_search_space before create_study"
