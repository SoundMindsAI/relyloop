# chore_agent_confirmation_tool_name_word_boundary — tighten the mutating-tool confirmation match

**Date:** 2026-06-09
**Status:** Idea — surfaced during a codebase-wide security review (branch `claude/codebase-security-review-6njwio`)
**Priority:** P2
**Origin:** Security review of the chat agent; finding in `backend/app/agent/orchestrator.py` + `backend/app/agent/confirmation.py`
**Depends on:** None

## Problem

The confirmation gate for the 8 mutating agent tools (`create_study`, `cancel_study`, `open_pr`, `create_proposal_*`, judgment generation, CSV import) is a two-condition heuristic: the last assistant message must "mention the tool name" AND the last user message must read as affirmative. Two aspects of the match are looser than the gate's intent:

`backend/app/agent/orchestrator.py:129-133` (`_is_authorized_mutation`)
```python
tool_name_spaced = tool_name.replace("_", " ")
assistant_lower = last_assistant_text.lower()
if tool_name not in assistant_lower and tool_name_spaced not in assistant_lower:
    return False
return is_affirmative(last_user_text)
```

1. **Substring (not word-boundary) match.** `tool_name in assistant_lower` is a bare substring test, so adjacent text can satisfy it unintentionally. Word-boundary matching is the documented intent (`is_affirmative` already uses `\b`-style whole-word matching for exactly this reason).
2. **Any-mutating-tool-named authorizes that tool with one generic affirmative.** If a single assistant turn names more than one mutating tool ("I can create a study and then open a PR for you") and the user replies "yes", the gate passes for **every** named tool the model subsequently emits in that step — the affirmative is not bound to a specific proposed action. The gate cannot distinguish "yes to create_study" from "yes, do all of that."

The prompt-injection-via-tool-result vector is **already defended** — `orchestrator.py` delimits tool/document content in the LLM history with an "ignore embedded instructions" note (spec §10 Threat 4), and the affirmative must come from the genuine user turn — so a malicious indexed document cannot itself supply the affirmation. That is why this is **Low/Medium**, not High. The `is_affirmative` helper is also already hardened against negation ("don't do it", "no go" → False, per `confirmation.py:64-99`).

The function's own docstring frames the heuristic as MVP1-acceptable ("a strict state-machine confirmation can land at MVP2 if the heuristic misfires"), so this idea is the scheduled follow-up that docstring anticipates.

## Proposed capabilities

### Bind the confirmation to a specific proposed tool

- Switch the tool-name test from substring to whole-word/boundary matching (mirror the `re.findall(r"[a-z]+", ...)` token approach already in `confirmation.py`).
- Tighten the model: require the assistant to have proposed a **single** specific tool (or track which tool the affirmative answers) so one "yes" cannot blanket-authorize multiple mutating calls emitted in the same step. A lightweight option: only authorize a mutating tool if exactly one mutating tool name appears in the last assistant turn; otherwise require an explicit per-tool re-prompt.
- Add unit tests for: multi-tool turn + generic "yes" (must NOT authorize all), substring-collision negative case, single-tool happy path, negation path (already covered — keep green).

## Scope signals

- **Backend:** `backend/app/agent/orchestrator.py` (`_is_authorized_mutation`) + `backend/app/agent/confirmation.py`; unit tests in `backend/tests/unit/agent/`.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP2-pre).

## Why filed as an idea rather than fixed inline

The "bind one affirmative to one specific tool" change is a small **product/UX decision** about the agent's confirmation flow (how the assistant must phrase a multi-action proposal), not a mechanical correction — it warrants a spec so the conversational contract is decided deliberately. The pure word-boundary swap alone could be inline, but it is bundled here so the matching and the binding model are designed together rather than half-fixed.

## Relationship to other work

Part of the security-review idea sweep on branch `claude/codebase-security-review-6njwio`. Independent of the SSRF, request-ID, CORS, and test-router siblings.
