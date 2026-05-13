# chore_chat_last_message_preview

**Type:** chore (UX polish)
**Date:** 2026-05-12
**Origin:** GPT-5.5 cycle-2 finding F15 against `feat_chat_agent` implementation plan; Story 5.1 capture.

## Problem

The `/chat` list page (`ui/src/app/chat/page.tsx`) shows each conversation
row as `title + relative timestamp + "{N} messages"`. There is no preview of
the last message — operators with several similarly-titled conversations
("debug local-es relevance", "debug local-es relevance v2", "debug local-es
relevance v3") have to click into each to figure out which thread covers
which problem.

## Why deferred

MVP1 ships without a preview because:
1. The backend `ConversationSummary` doesn't expose `last_message_preview` /
   `last_message_at` — adding them would mean a new repo helper (LATERAL
   JOIN against the `messages` table for the most-recent row), an extra
   column on the API response, and a small Pydantic schema patch.
2. Auto-titling (FR-1 derives the title from the first user message)
   already gives a decent at-a-glance distinction for most cases.
3. No AC requires it; deferring keeps Story 4.2 small and ships the chat
   surface earlier.

## Proposed scope

1. Backend: add `last_message_preview: str | None` (truncated to 120 chars)
   and `last_message_at: datetime | None` to `ConversationSummary`. Source
   from a new repo helper `list_conversations_with_message_counts_and_preview`
   (or extend the existing JOIN with a SUBQUERY for the latest row).
2. Frontend: render the preview as a single muted-foreground line under the
   title; collapse to "(no messages yet)" when empty.
3. Unit + contract tests update accordingly.

## Scope signals

- Backend: one new repo helper, one Pydantic schema extension, one router
  change, one migration **only if** we choose to denormalize the preview
  onto `conversations` (subquery approach needs no migration).
- Frontend: one component change (`ConversationList`).
- No new tools, no new routes.

## Related work

- Companion deferred work: [`bug_chat_long_conversation_truncation_mvp2`](../bug_chat_long_conversation_truncation_mvp2/idea.md)
  — both are MVP2 chat polish items and could ship together.
