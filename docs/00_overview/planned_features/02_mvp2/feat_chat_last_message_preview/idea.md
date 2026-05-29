# feat_chat_last_message_preview

**Type:** feat (chat UX polish — deferred)
**Status:** Held for MVP2 (decided 2026-05-13). No technical dependency on MVP2 infra; bundling with [`bug_chat_long_conversation_truncation_mvp2`](../bug_chat_long_conversation_truncation/idea.md) as chat polish. `feat_chat_agent` has been live since 2026-05-12 (PR #60) and no operator has asked for the preview yet. Folder renamed from `chore_chat_last_message_preview` 2026-05-14 per `/idea-preflight` audit — `chore_` is reserved for changes with no user-visible behavior per [feature_templates/README.md](../../feature_templates/README.md).
**Date:** 2026-05-12
**Origin:** GPT-5.5 cycle-2 finding F15 against `feat_chat_agent` implementation plan ([deferred-work entries](../../../implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md), F15 row in the rating table); Story 5.1 capture.

## Problem

The `/chat` list page ([ui/src/app/chat/page.tsx](../../../../../ui/src/app/chat/page.tsx))
renders each conversation row as `title + relative timestamp + "{N} messages"`
via [`ConversationList`](../../../../../ui/src/components/chat/conversation-list.tsx).
There is no preview of the last message — operators with several similarly-titled
conversations ("debug local-es relevance", "debug local-es relevance v2",
"debug local-es relevance v3") have to click into each to figure out which
thread covers which problem.

## Why deferred

MVP1 shipped without a preview because:
1. The backend `ConversationSummary` ([backend/app/api/v1/schemas.py:991-997](../../../../../backend/app/api/v1/schemas.py#L991-L997))
   exposes only `id`, `title`, `created_at`, `message_count` — no
   `last_message_preview` / `last_message_at`. Adding them means a new repo
   helper (or extending [`list_conversations_with_message_counts`](../../../../../backend/app/db/repo/conversation.py#L120-L154)
   with a correlated SUBQUERY for the latest row), an extra column on the API
   response, and a Pydantic schema patch.
2. Auto-titling (FR-1 derives the title from the first user message via
   [`_derive_title`](../../../../../backend/app/services/agent_chat.py#L54-L67))
   already gives a decent at-a-glance distinction for most cases.
3. No AC required it in `feat_chat_agent`. That feature has now shipped
   (PR #60, merged 2026-05-12) and no operator has filed a bug or feature
   request for the preview — keep deferred until the MVP2 polish bundle.

## Proposed scope

1. **Backend:** add `last_message_preview: str | None` (truncated to 120 chars,
   markdown-stripped) and `last_message_at: datetime | None` to
   `ConversationSummary`. Source from a new repo helper
   `list_conversations_with_message_counts_and_preview` (subquery approach —
   see Decisions locked).
2. **Frontend:** render the preview as a single muted-foreground line under
   the title in [`ConversationList`](../../../../../ui/src/components/chat/conversation-list.tsx);
   collapse to `(no messages yet)` when empty.
3. **Tests:** extend [`backend/tests/contract/test_conversations_api_contract.py`](../../../../../backend/tests/contract/test_conversations_api_contract.py)
   to assert the two new fields; add a unit test for the SUBQUERY repo helper
   (filters role, picks the latest row, truncates at 120); add a vitest case
   for the empty-state rendering.

## Decisions locked

1. **Subquery, not denormalize.** The preview is computed via a correlated
   SUBQUERY against `messages` in the repo helper — no migration, no
   write-path complexity. Denormalized `last_message_preview` /
   `last_message_at` columns on `conversations` were considered and rejected:
   they would require synchronized writes in every `create_message` path
   (`agent_chat`, future webhook ingestion) and a backfill migration.
   Single-tenant alpha at ≤50 conversations × 1 subquery per page is fine;
   revisit only if list latency exceeds 200ms once multi-tenant lands at
   MVP4.
2. **Truncation length: 120 chars.** Headroom over the auto-title cap
   (`TITLE_MAX_LENGTH = 80`, [agent_chat.py:43](../../../../../backend/app/services/agent_chat.py#L43))
   — long enough to disambiguate similar threads, short enough to fit on one
   muted-foreground line.
3. **Empty state: `(no messages yet)`.** Renders when `last_message_preview`
   is `None` (just-created conversations before the first user turn —
   `useCreateConversation` creates an empty row before navigation).

## Open questions for /spec-gen

These need spec-time decisions the idea cannot lock from the codebase alone:

1. **Which role's last message do we preview?** Last message of any role
   would include `tool` rows (raw JSON tool results) and could surface
   noisy delimiters from the `<tool_result>` wrapping
   ([agent_chat.py:70-80](../../../../../backend/app/services/agent_chat.py#L70-L80)).
   **Recommended default:** preview the last `user` or `assistant` message,
   skipping `tool` rows — the SUBQUERY's WHERE clause filters
   `role IN ('user', 'assistant')`.
2. **Markdown stripping for assistant messages.** Assistant replies often
   contain markdown (code fences, bullet lists, bold). Render raw, or strip?
   **Recommended default:** strip via a small regex pass (collapse code
   fences to `…`, drop list markers, drop bold/italic asterisks) before
   truncation. No markdown rendering inside the row — the row is plain
   muted text.
3. **What to extract from `content`.** User messages carry `{text: str}`;
   assistant messages can carry text alongside tool-call metadata.
   **Recommended default:** read `content.text` if present; fall back to
   `""` (rendered as the empty-state) for messages whose `content` shape
   has no text field. Defensive: should not happen for `user`/`assistant`
   rows under the schemas in [`MessageWire`](../../../../../ui/src/lib/api/conversations.ts#L24-L30)
   but keeps the helper robust to future content-type extensions.

## CLAUDE.md rule touchpoints

- **Rule #5 (migration downgrade):** N/A under the locked subquery approach
  — no migration. If the denormalize alternative is revisited later, that
  path would require reversible `add_column` / `drop_column` plus the
  round-trip `alembic downgrade -1 && alembic upgrade head` verification.
- **Audit log:** N/A — read-path only; `ConversationSummary` extension
  does not mutate tenant-visible state. (Pre-MVP2 the `audit_log` table
  does not exist anyway.)
- **Rule #10 (no secret logs):** The preview echoes operator chat content.
  Keep the value confined to the API response + DB query — never log it
  in structlog `extra={}` or error messages.

## Scope signals

- **Backend:** one new repo helper, one Pydantic schema extension, one
  router change in [`backend/app/api/v1/conversations.py`](../../../../../backend/app/api/v1/conversations.py)
  (the existing `list_conversations_endpoint` already constructs
  `ConversationSummary` rows — just pass the two new fields). No migration
  under the locked subquery approach.
- **Frontend:** one component change ([`ConversationList`](../../../../../ui/src/components/chat/conversation-list.tsx)).
- No new tools, no new routes, no new tests file (extend existing contract
  + unit + vitest suites).

## Folder/type history

Originally captured as `chore_chat_last_message_preview` (Story 5.1, 2026-05-12).
Renamed to `feat_chat_last_message_preview` on 2026-05-14 per `/idea-preflight`
audit: [feature_templates/README.md](../../feature_templates/README.md) reserves
`chore_` for "Refactor, rename, dead-code removal, tech debt — no user-visible
behavior change," and a preview line in the conversation list is a user-visible
addition. Mirrors the 2026-05-13 `bug_chat_long_conversation_truncation` →
`_mvp2` rename precedent (state.md ledger). Implemented-features archive
references (`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md`
F15 row, deferred-work table) left untouched as frozen-at-ship-time.

## Related work

- Implemented chat surface this idea extends:
  [`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/`](../../../implemented_features/2026_05_12_feat_chat_agent/).
  The deferral rationale lives in
  [`implementation_plan.md`](../../../implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md)
  (cycle-2 F15 row + Story 5.1 deferred-work table).
- Companion deferred work:
  [`bug_chat_long_conversation_truncation_mvp2`](../bug_chat_long_conversation_truncation/idea.md)
  — both are MVP2 chat polish items and could ship together.
