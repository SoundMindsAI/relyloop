# chore_agent_confirmation_per_tool_binding — bind one affirmative to one specific mutating tool

> Renamed from `chore_agent_confirmation_tool_name_word_boundary` (preflight 2026-06-19): the old name captured only the word-boundary fix; the load-bearing change is binding a single "yes" to a single proposed tool (word-boundary matching is a prerequisite of that).

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

The prompt-injection-via-tool-result vector is **already defended** — `orchestrator.py` delimits tool/document content in the LLM history with an "ignore embedded instructions" note (spec §10 Threat 4), and the affirmative must come from the genuine user turn — so a malicious indexed document cannot itself supply the affirmation. That is why this is **Low/Medium**, not High. The `is_affirmative` helper is also already hardened against negation ("don't do it", "no go" → False, per `_NEGATION_TOKENS` at [confirmation.py:64-81](../../../../backend/app/agent/confirmation.py#L64-L81) + [`is_affirmative` at 84-103](../../../../backend/app/agent/confirmation.py#L84-L103)).

The function's own docstring frames the heuristic as MVP1-acceptable ("a strict state-machine confirmation can land at MVP2 if the heuristic misfires"), so this idea is the scheduled follow-up that docstring anticipates.

## Proposed capabilities

### Bind the confirmation to a specific proposed tool

- Switch the tool-name test from substring to whole-word/boundary matching. Note the matcher must preserve underscores: the `re.findall(r"[a-z]+", ...)` tokenizer used by `is_affirmative` would split `create_study` into `["create", "study"]`, so a full-name membership test against those tokens always fails. Use a `\b`-anchored regex directly on the tool name (`re.search(rf"\b{re.escape(name)}\b", text)`) — accepting both the underscored (`create_study`) and spaced (`create study`) forms — or tokenize with `[a-z_]+`.
- Tighten the model: require the assistant to have proposed a **single** specific tool (or track which tool the affirmative answers) so one "yes" cannot blanket-authorize multiple mutating calls emitted in the same step.
- Add unit tests for: multi-tool turn + generic "yes" (must NOT authorize all), substring-collision negative case, single-tool happy path, negation path (already covered — keep green).

#### Locked decision (preflight 2026-06-19) — binding model

**Lock Option A: "exactly-one-mutating-tool-name in the last assistant turn."** If the assistant turn names two or more mutating tool names (counted via the same `\b`-anchored regex over the `MUTATING_TOOL_NAMES` set), `_is_authorized_mutation` returns `False` for **all** of them — regardless of how affirmative the user reply reads. The model must then re-propose per-tool and the user must re-affirm per-tool.

**Why A over the active-tracking alternative (B):**
- Matches the existing shape of the heuristic — two stateless string checks on `(last_assistant_text, last_user_text)`. Option B (tracking which tool the affirmative answers across turns) would introduce per-conversation state in Redis or the DB, and the spec docstring explicitly anchors the design at "heuristic, acceptable for MVP1; a strict state-machine confirmation can land at MVP2 if the heuristic misfires" ([confirmation.py:87](../../../../backend/app/agent/confirmation.py#L87)). Adding state-machine surface here would over-shoot the docstring's MVP2 budget.
- The fail-safe direction is correct: ambiguous → reject. Mutations require an explicit per-tool re-prompt; never an implicit blanket "yes".
- Cheap to test: the multi-tool negative test the idea already proposes IS the acceptance test for Option A.

## Scope signals

- **Backend:** `backend/app/agent/orchestrator.py` (`_is_authorized_mutation`) + `backend/app/agent/confirmation.py`; unit tests in `backend/tests/unit/agent/`.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — `audit_log` activates at **MVP3** per [CLAUDE.md](../../../../CLAUDE.md) ("Activates at MVP3 (Observable)"). The confirmation gate sits **before** dispatch, so there is no mutation site here to emit from in the first place; once `audit_log` lands, the audit row is owned by the dispatched mutating-tool service (study/proposal/etc.), not by the gate.

## Why filed as an idea rather than fixed inline

The "bind one affirmative to one specific tool" change is a small **product/UX decision** about the agent's confirmation flow (how the assistant must phrase a multi-action proposal), not a mechanical correction — it warrants a spec so the conversational contract is decided deliberately. The pure word-boundary swap alone could be inline, but it is bundled here so the matching and the binding model are designed together rather than half-fixed.

## Open questions for /bug-fix

- **Error code for the ambiguous case.** When the assistant turn names two-or-more mutating tools, the gate now rejects all of them. What `error` token does the resulting `ToolResultEvent` carry? Two plausible choices: (a) reuse the existing `confirmation_required` so frontends and tests stay shape-compatible; (b) introduce a new `ambiguous_confirmation` so operator-facing telemetry can distinguish "user didn't affirm" from "model proposed too many actions at once". **Recommended default: (a)** — keep `confirmation_required` and rely on the `detail` field (which is human-text already, per [orchestrator.py:362-368](../../../../backend/app/agent/orchestrator.py)) to telegraph the ambiguous-multi-tool case. Adds zero new enum surface; the operator-telemetry concern can be filed as a follow-on idea if it ever bites.
- **Spaced-form match for multi-word tool names.** All current mutating tool names are two underscore tokens (e.g. `create_study` → `"create study"`), but a future three-token tool (e.g. a hypothetical `generate_judgments_from_clicks`) would have a spaced form `"generate judgments from clicks"` that an assistant prose paragraph might never produce verbatim. **Recommended default:** stay verbatim — match the spaced form only when the model actually writes it that way. Operators surface the mismatch via the test the idea already proposes (the substring-collision negative case).

## Relationship to other work

Part of the security-review idea sweep on branch `claude/codebase-security-review-6njwio`. Independent of the SSRF, request-ID, CORS, and test-router siblings ([`bug_cluster_url_ssrf_hostname_bypass`](../bug_cluster_url_ssrf_hostname_bypass/) — Phase 1 shipped PR #510, Phase 2 in-folder defer-until-incident; [`bug_request_id_header_unvalidated_log_injection`](../bug_request_id_header_unvalidated_log_injection/) — idea-stage; [`chore_cors_credentials_origin_hardening`](../../04_ga/chore_cors_credentials_origin_hardening/) — idea-stage; [`chore_test_router_conditional_mount`](../chore_test_router_conditional_mount/) — idea-stage).
