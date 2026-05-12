# bug_chat_long_conversation_truncation

**Type:** bug (latent — pre-MVP2)
**Date:** 2026-05-12
**Origin:** GPT-5.5 cycle-2 finding F14 against `feat_chat_agent` implementation plan; Story 5.1 capture.

## Problem

`backend/app/services/agent_chat.send_user_message` defensively caps the OpenAI
history at the most recent `HISTORY_MAX_MESSAGES = 100` messages and emits a
`chat_history_truncated` WARN structlog line on truncation. This is brute-force
truncation — old turns are dropped wholesale, which can hide context the LLM
needs (e.g., the original cluster name the operator was tuning, the
parameters of an earlier `create_study` confirmation, the specific judgment
list discussed several turns ago).

The MVP1 working assumption is that 100 messages × ~1K tokens average ≈ 100K
tokens — well below `gpt-4o-mini`'s 128K context window — so the cap rarely
fires in practice. But once a power user lets a long-running conversation
accumulate, the cap will start dropping load-bearing context silently.

## Why deferred

The full alternative (rolling summarization, smart pruning that preserves
mutating-tool context, or a separate history-summary table) is a meaningful
design effort: it needs its own LLM round-trip per truncation event, a
structured "summary" message type, and care about how the system prompt + the
summary interact. Holding it until MVP2 keeps Story 5.1's docs sweep simple
and avoids over-engineering the MVP1 surface.

## Proposed scope (MVP2)

1. Define a `ConversationSummary` JSONB column on `conversations` (or a
   separate `conversation_summaries` child table — TBD). Stores the rolling
   summary of dropped turns.
2. When `send_user_message` would otherwise truncate, instead invoke a
   summarization helper: feed the dropped turns + the existing summary into
   `gpt-4o-mini`, ask for a concise replacement summary, persist it, and use
   it as a system-message prefix on subsequent turns.
3. Capture summarization failures gracefully — fall back to the brute-force
   truncation behavior so the chat surface keeps working.
4. Add a unit test that verifies a 150-turn conversation summarizes the
   first 50 into a single system-prefix message and keeps the most recent
   100 turns intact.

## Scope signals

- Backend only (one new service helper, one new DB column or table, one
  migration). Optional touch to `agent_chat.send_user_message`.
- No new tools or routes.
- One new structlog event type (`chat_history_summarized`).

## Related work

- The original cap lives at
  [`backend/app/services/agent_chat.py`](../../../../backend/app/services/agent_chat.py)
  (`HISTORY_MAX_MESSAGES = 100`).
- Future PR-cleanup paired with [chore_chat_last_message_preview](../chore_chat_last_message_preview/idea.md)
  if MVP2's chat polish lands together.
