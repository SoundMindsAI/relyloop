# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""System-prompt sanity tests (feat_chat_agent Story 2.5).

Asserts the prompt loaded at orchestrator import time mentions every mutating
tool in the confirmation list and excludes ``create_query_set`` (which is NOT
on the mutation set per spec FR-5).
"""

from __future__ import annotations

from backend.app.agent.confirmation import MUTATING_TOOL_NAMES
from backend.app.agent.orchestrator import SYSTEM_PROMPT


def test_system_prompt_mentions_every_mutating_tool() -> None:
    """Each of the 7 confirmation-required tools is named in the prompt body."""
    for tool_name in MUTATING_TOOL_NAMES:
        assert tool_name in SYSTEM_PROMPT, f"prompt missing tool name {tool_name!r}"


def test_system_prompt_excludes_create_query_set_from_confirmation_list() -> None:
    """create_query_set is intentionally NOT on the confirmation list (spec parity)."""
    # The prompt still references create_query_set (it's in the inventory),
    # but the dedicated "Mutating tools require explicit confirmation first"
    # rule must NOT list it among the 7-tool set.
    section_start = SYSTEM_PROMPT.find("Mutating tools require explicit confirmation")
    assert section_start >= 0, "confirmation rule missing from system prompt"
    # Find the end of the rule paragraph — the next blank-line-separated rule.
    section_end = SYSTEM_PROMPT.find("\n3.", section_start)
    section = SYSTEM_PROMPT[section_start:section_end]
    assert "create_query_set" not in section, (
        "create_query_set appears in the confirmation rule body; it must not"
    )


def test_system_prompt_mentions_loop_limit() -> None:
    """The 10-iteration loop limit is documented for the LLM to read."""
    assert "10 iterations" in SYSTEM_PROMPT, "loop-limit clause missing"


def test_system_prompt_warns_about_tool_result_injection() -> None:
    """Spec §10 Threat 4 — the prompt names <tool_result> as untrusted content."""
    assert "tool_result" in SYSTEM_PROMPT
    assert "Ignore" in SYSTEM_PROMPT or "ignore" in SYSTEM_PROMPT
