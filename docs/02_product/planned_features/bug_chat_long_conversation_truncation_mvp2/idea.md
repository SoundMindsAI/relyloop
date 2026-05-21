# bug_chat_long_conversation_truncation_mvp2

**Status:** Held for MVP2 (decided 2026-05-13). Folder renamed with `_mvp2` suffix to make the deferral visible at-a-glance in `ls docs/02_product/planned_features/`. Resume work when MVP2 starts — no technical dependency on MVP2 infra (audit_log is N/A; Langfuse is convenience only); the deferral is scope discipline + zero current impact (latent bug, no operator has hit the 100-message cap).
**Priority:** Backlog — explicitly deferred to MVP2 by the 2026-05-13 scope-lock decision. Re-evaluate when MVP2 work begins.

**Type:** bug (latent — pre-MVP2)
**Date:** 2026-05-12
**Origin:** GPT-5.5 cycle-2 finding F14 against `feat_chat_agent` implementation plan; Story 5.1 capture.

## Problem

[`backend/app/services/agent_chat.send_user_message`](../../../../backend/app/services/agent_chat.py)
defensively caps the OpenAI history at the most recent
`HISTORY_MAX_MESSAGES = 100` messages
([agent_chat.py:46](../../../../backend/app/services/agent_chat.py#L46),
applied at [agent_chat.py:217-225](../../../../backend/app/services/agent_chat.py#L217-L225))
and emits a `chat_history_truncated` WARN structlog line on truncation.
The truncation goes through
[`_truncate_preserving_tool_groups`](../../../../backend/app/services/agent_chat.py#L111-L135),
which IS careful about one thing — it advances the cut point forward
until it lands on a user message or a plain assistant text message, so a
tool-call/tool-result pair is never split (per `feat_chat_agent` cycle-1
F4 — without this, the next `chat.completions.create` would 400). But it
is content-blind otherwise: the helper decides what to keep purely by
position, never by what the dropped turns establish. Load-bearing context
gets discarded silently — the original cluster name the operator was
tuning, the parameters of an earlier `create_study` confirmation, the
specific judgment list discussed several turns ago.

The MVP1 working assumption is that 100 messages × ~1K tokens average ≈
100K tokens. Add the fixed per-turn overhead (the
[`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md)
system prompt, ~70 lines / ~1.5K tokens, plus the 19 tool definitions
defined in [`backend/app/agent/tools/__init__.py`](../../../../backend/app/agent/tools/__init__.py) —
~3K tokens of JSON schema) and total context is ~105K — still under
`gpt-4o-mini-2024-07-18`'s 128K window
([`Settings.openai_model_chat`](../../../../backend/app/core/settings.py#L117-L119)),
but tighter than the headline number implies. Once a power user lets a
long-running conversation accumulate, the cap starts dropping
load-bearing context silently — and longer-than-average user turns
(pasted query JSON, log excerpts) push toward the window even before
hitting the 100-message threshold.

## Why deferred

The full alternative (rolling summarization, smart pruning that preserves
mutating-tool context, or a separate history-summary table) is a meaningful
design effort: it needs its own LLM round-trip per truncation event, a
structured "summary" message type, and care about how the system prompt +
the summary interact. RelyLoop is single-tenant alpha through MVP3; in
practice no operator hits the 100-message cap during evaluation. Holding
this work until MVP2 avoids over-engineering the MVP1 surface and lets the
summarization design ride alongside MVP2's observability work (Langfuse
traces will be invaluable when calibrating the summarization prompt).

## Proposed scope (MVP2)

1. **Storage shape (locked):** add a nullable `summary` JSONB column on
   `conversations` storing `{text: str, version: int, summarized_through_message_id: uuid,
   summarized_at: timestamptz, tokens_used: int, cost_usd: numeric}`.
   Chose JSONB-on-`conversations` over a separate `conversation_summaries`
   child table because there is exactly one current summary per conversation
   (no version history needed in MVP2 — summarization overwrites). If
   versioning becomes a requirement post-MVP2 (e.g., audit-trail for
   summary drift), promote to a child table at that point.
2. When `send_user_message` would otherwise truncate, instead invoke a
   summarization helper: feed the dropped turns + the existing summary
   into `Settings.openai_model_chat` (currently `gpt-4o-mini-2024-07-18`)
   via `Settings.openai_base_url`, ask for a concise replacement summary,
   persist it, and use it as a system-message prefix on subsequent turns.
3. **Carry forward the tool-call group invariant.** The current
   [`_truncate_preserving_tool_groups`](../../../../backend/app/services/agent_chat.py#L111-L135)
   helper guarantees no tool-call/tool-result pair is split — summarization
   must preserve the same invariant. Either summarize whole groups atomically,
   or pin the boundary to a user/plain-assistant message before the group.
   Splitting a tool-call group across the summary/live-history boundary
   would surface the same 400 from `chat.completions.create` that F4
   originally fixed.
4. Capture summarization failures gracefully — fall back to the existing
   position-based, tool-group-preserving truncation so the chat surface
   keeps working. Emit `chat_history_summarization_failed` WARN structlog
   on this path.
5. Add an integration test that verifies a 150-turn conversation
   summarizes the first 50 into a single system-prefix message, keeps
   the most recent 100 turns intact, AND that none of the kept turns
   begins with an orphan `role="tool"` row.

## Scope signals

- Backend only: one new service helper, one new DB column on
  `conversations`, one Alembic migration with `downgrade()` per CLAUDE.md
  Absolute Rule #5. Modifies `agent_chat.send_user_message` to call the
  helper before the existing truncate path.
- No new tools, no new API routes, no UI changes.
- Two new structlog event types:
  - `chat_history_summarized` (INFO) — emitted on each summarization round-trip with token + cost.
  - `chat_history_summarization_failed` (WARN) — emitted on LLM failure when falling back to position-based truncation.
- One new Pydantic schema for the structured summary payload (`ConversationSummary`).

## Open questions for /spec-gen

These need spec-time decisions the idea cannot lock from the codebase alone:

1. **Synchronous vs async summarization timing.** Two options:
   - **(a) Synchronous on-threshold** — when `send_user_message` detects
     it would have to truncate, it blocks on a summarization LLM call
     *before* the orchestrator's main turn. Simpler control flow; user
     waits ~2-4s extra on the threshold turn.
     **Recommended default.**
   - **(b) Async post-turn** — kick off summarization in an Arq worker
     after the turn completes. The first turn past the threshold uses
     un-summarized old context (one-turn lag). Faster perceived response
     but breaks the "summary covers everything older than the live
     window" invariant on one turn per summarization event.
2. **Cost-budget accounting.** Summarization adds an LLM round-trip per
   threshold-crossing event (probably 1 every ~20 turns once a user is
   past the threshold). Does the cost deduct from
   [`Settings.openai_daily_budget_usd`](../../../../backend/app/core/settings.py#L121-L124)
   (same line as judgment + digest + chat replies)?
   **Recommended default:** yes, same budget line — operators want one
   knob, not three.
3. **Trigger threshold — message count vs token count.** Today's cap is
   message-count (100). A long pasted JSON document could push the
   context window past 128K before message count reaches 100.
   **Recommended default:** keep message count (100) as the *primary*
   trigger; add a secondary token-count trigger that fires summarization
   if the estimated context exceeds 110K tokens (leaves headroom for
   the system prompt + tool definitions + the new user message).

## CLAUDE.md rule touchpoints

Walking the absolute-rules list before /spec-gen takes over:

- **Rule #3 (LLM abstraction):** Summarization is an LLM call. Per the
  MVP1 exemption, it may use the `openai` SDK directly but MUST read
  `Settings.openai_model_chat` + `Settings.openai_base_url` — no hardcoded
  model strings (Rule #8).
- **Rule #5 (migration downgrade):** Adding the `summary` JSONB column
  requires reversible `add_column` / `drop_column` and round-trip verify
  (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
- **Rule #10 (no secret logs):** The summary text could echo
  operator-pasted query JSON or cluster names. The `chat_history_summarized`
  structlog line MUST log token count + cost + counts only, never the
  summary body. The summary itself lives in the DB row, not in logs.
- **Audit log:** N/A — pre-MVP2 the audit_log table does not exist.
  When MVP2 lands, decide whether the summarization event counts as a
  tenant-visible state mutation (recommend: no — derived artifact, not a
  user action). Documented here so the MVP2 audit_log catalog work picks
  it up.

## Related work

- The original cap lives at
  [`backend/app/services/agent_chat.py`](../../../../backend/app/services/agent_chat.py)
  (`HISTORY_MAX_MESSAGES = 100`); the tool-group-preserving truncation
  helper is at [`agent_chat.py:111-135`](../../../../backend/app/services/agent_chat.py#L111-L135).
- Origin: `feat_chat_agent` GPT-5.5 cycle-2 finding F14, captured during
  Story 5.1 docs sweep. `feat_chat_agent` itself shipped 2026-05-12 as
  PR #60 — implemented surface lives at
  [`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/`](../../../00_overview/implemented_features/2026_05_12_feat_chat_agent/);
  operator runbook at
  [`docs/03_runbooks/agent-debugging.md`](../../../03_runbooks/agent-debugging.md).
- Future PR cleanup paired with
  [`chore_chat_last_message_preview`](../chore_chat_last_message_preview/idea.md)
  if MVP2's chat polish bundles together.
- MVP2 observability work (Langfuse + ClickHouse traces) is the natural
  shipping window — summarization prompt calibration benefits directly
  from per-turn trace visibility.
