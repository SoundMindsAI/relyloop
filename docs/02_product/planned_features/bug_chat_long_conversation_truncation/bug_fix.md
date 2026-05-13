# Bug fix — bug_chat_long_conversation_truncation

**Source idea:** [idea.md](./idea.md)
**Branch:** (TBD — Investigation mode only; no branch yet)
**Type:** bug fix — medium (latent, pre-MVP2)
**Date:** 2026-05-13
**Mode:** Investigation — phases 1-3 complete; Fix design / Regression test / Rollout pending user decisions on the 3 open forks surfaced by `/idea-preflight`.

## Problem

Once a chat conversation exceeds `HISTORY_MAX_MESSAGES = 100`,
[`_truncate_preserving_tool_groups`](../../../../backend/app/services/agent_chat.py#L111-L135)
drops position-old messages wholesale. The helper is correct for what
it does — it advances the cut to a clean tool-call boundary, avoiding
the OpenAI 400 from a split assistant→tool pair (per `feat_chat_agent`
cycle-1 F4) — but it has no signal for *content* importance. Load-bearing
references mentioned early in a long conversation (the cluster name the
operator was tuning, the parameters of an earlier `create_study`
confirmation, the specific judgment list discussed several turns ago)
get dropped silently. The LLM then answers subsequent turns without the
context that motivated the conversation in the first place.

The bug is **latent**: in MVP1 single-tenant alpha, no operator hits the
100-message cap during evaluation. It activates at MVP2+ when
multi-tenant power users let conversations accumulate.

## Reproduction

Property test — demonstrates the condition under which the bug fires,
not a currently-failing assertion (latent bug). The test will live at
`backend/tests/unit/services/test_agent_chat_truncation.py` post-fix.

```python
def test_truncate_preserving_tool_groups_drops_content_blindly():
    """Latent bug: position-based truncation drops the first message's
    load-bearing reference once N > HISTORY_MAX_MESSAGES.
    After the fix lands, this assertion inverts — summarization should
    preserve `production-search-east` in the system-prefix summary."""
    messages = [_mk_user(text="tune cluster production-search-east please")]
    messages += [_mk_user(text=f"filler turn {i}") for i in range(149)]

    kept = _truncate_preserving_tool_groups(messages, max_kept=100)

    assert len(kept) <= 100
    kept_text = " ".join((m.content or {}).get("text", "") for m in kept)
    assert "production-search-east" not in kept_text  # bug condition
```

Run via:

```bash
pytest backend/tests/unit/services/test_agent_chat_truncation.py -v
```

The function's signature
([`agent_chat.py:111`](../../../../backend/app/services/agent_chat.py#L111))
takes `(messages: list[Message], max_kept: int)` — no content awareness
is possible without changing the signature.

## Root cause

- **Owning layer:** Service (`backend/app/services/agent_chat.py`).
- **Origin:** [`agent_chat.py:217-225`](../../../../backend/app/services/agent_chat.py#L217-L225)
  — the call site invokes `_truncate_preserving_tool_groups`
  unconditionally when `len(all_messages) > HISTORY_MAX_MESSAGES`. No
  branch tests "is the dropped portion important?"
- **The bug itself:** [`agent_chat.py:111-135`](../../../../backend/app/services/agent_chat.py#L111-L135)
  — `_truncate_preserving_tool_groups` is correct for tool-call group
  integrity but content-blind. The helper's design (position + role
  only, no content access) is what makes the bug structural rather
  than a coding mistake.
- **Propagation:** [`agent_chat.py:226-227`](../../../../backend/app/services/agent_chat.py#L226-L227)
  — the truncated list becomes the OpenAI `history` parameter. No
  downstream code can recover dropped context; once gone, gone.

Framing: the helper is *correct for what it does* but *insufficient for
what's needed*. The fix is additive — wrap the existing helper with a
summarization pre-step that condenses the dropped portion into a
single system-prefix message — not replace it.

## Fix design (locked decisions)

**TBD** — three forks surfaced by `/idea-preflight` need user calls
before this section can lock. See [idea.md §"Open questions for /spec-gen"](./idea.md):

1. Synchronous-on-threshold vs async-post-turn timing.
2. Cost-budget accounting — same `openai_daily_budget_usd` line, or its own?
3. Trigger threshold — message-count (100) only, or message-count + secondary token-count (110K)?

Per the idea, recommended defaults are:
1. Synchronous (simpler control flow, one-turn invariant).
2. Same budget line (single operator knob).
3. Message count primary + token count safety trigger.

If you accept all three defaults, re-invoke `/bug-fix` in **Default
mode** on this folder. The Resume detection (Phase 1 step 1 of the
skill) will pick up this file and complete phases 4-6.

## Regression test plan

**TBD** — pending Fix design. The reproducer test (above) becomes the
regression assertion once the fix lands; the assertion flips from
"`production-search-east` is absent" to "`production-search-east` is
present in the system-prefix summary."

Anticipated test inventory once locked:

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/services/test_agent_chat_truncation.py` | The (inverted) reproducer above + tool-call group invariant carries forward across the summary boundary |
| integration | `backend/tests/integration/services/test_agent_chat_summarization.py` | 150-turn conversation through real `send_user_message` → DB row written to `conversations.summary` → next turn's OpenAI call includes the summary prefix |
| contract | (none) | No API/SSE shape changes — internal mechanism only |

## Rollout

**TBD** — pending Fix design. Likely items:

- One Alembic migration adding `conversations.summary` JSONB column,
  reversible per CLAUDE.md Rule #5.
- New Jinja template at `prompts/conversation_summarization.{system,user}.md`.
- Settings field? None required if the summarization model is the
  existing `Settings.openai_model_chat`.
- Feature flag? Likely no — the existing 100-message cap continues to
  fire for conversations on the old code path; new code path activates
  per-conversation as conversations grow.
- Operator action? None — additive feature, automatic activation.

## Tangential observations

During Phases 1-3 tracing, none of the following turned into separate
idea files (already captured or out of scope):

- [`chore_chat_last_message_preview`](../chore_chat_last_message_preview/idea.md) — sibling MVP2 chat polish; coordinate landing if both ship together (already noted in idea.md §Related work).
- The orchestrator's tool-result wrapping invariant
  ([`orchestrator.py` `_wrap_tool_result_for_llm`](../../../../backend/app/agent/orchestrator.py))
  applies to **every replay** of every tool message. Summarization that
  re-rolls tool messages into the summary body must NOT strip the
  `<tool_result>` delimiters; otherwise a hostile tool output's
  prompt-injection payload would influence subsequent turns. Note this
  as a Fix-design constraint rather than a separate idea file.

---

**Investigation-mode termination:** `bug_fix.md` has Problem /
Reproduction / Root cause filled in; **Fix design / Regression test /
Rollout marked TBD pending user decisions on the 3 open forks**. Re-run
`/bug-fix docs/02_product/planned_features/bug_chat_long_conversation_truncation/`
in Default mode once the forks are locked (or accept the recommended
defaults inline and run `/bug-fix … --proceed`).
