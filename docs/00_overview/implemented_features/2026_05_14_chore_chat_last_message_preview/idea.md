# chore_chat_last_message_preview

**Type:** chore (UX polish)
**Date:** 2026-05-12 (refreshed by `/idea-preflight` 2026-05-14 — verified against the shipped `feat_chat_agent` surface; backend approach locked, two UX decisions surfaced)
**Origin:** GPT-5.5 cycle-2 finding F15 against `feat_chat_agent` implementation plan; Story 5.1 capture (now [`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md`](../../00_overview/implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md)).

## Status

Held for MVP2 — companion to [`bug_chat_long_conversation_truncation_mvp2`](../bug_chat_long_conversation_truncation_mvp2/idea.md). Both are chat-surface polish items deferred from `feat_chat_agent`. No technical blocker on MVP2 infra (this work is pure read-side; no audit_log, no Langfuse dependency). Can ship as a standalone `/impl-execute --ad-hoc` once MVP2 starts, OR bundle with the companion bug.

## Problem

The `/chat` list page renders each conversation row as `title + relative timestamp (created_at) + count` via [`ui/src/components/chat/conversation-list.tsx:30-49`](../../../ui/src/components/chat/conversation-list.tsx#L30-L49). The count text uses three variants from [`formatCount`](../../../ui/src/components/chat/conversation-list.tsx#L12-L16):

- `"Empty"` when count is 0
- `"1 message"` when count is 1
- `"{N} messages"` otherwise

There is no preview of the last message, and the timestamp shown is the conversation's `created_at`, not the most recent message time. Two consequences:

1. **Disambiguation cost.** Operators with similarly-titled conversations (auto-titles often share prefixes — "debug local-es relevance", "debug local-es relevance v2", "debug local-es relevance v3") have to click each thread to figure out which is which.
2. **Misleading timestamp.** Listing rows by `created_at` (which is also the sort key per [`list_conversations_with_message_counts` repo helper](../../../backend/app/db/repo/conversation.py#L120-L154)) means a thread created last week but actively used 5 minutes ago sorts BELOW a freshly-spawned empty thread. The list doesn't answer "what did I work on most recently."

## Why deferred

MVP1 ships without it because:

1. The backend `ConversationSummary` (4 fields: `id, title, created_at, message_count` at [`schemas.py:991-997`](../../../backend/app/api/v1/schemas.py#L991-L997)) doesn't expose the data. Adding it means extending the existing repo helper, expanding the schema, and updating the contract tests.
2. Auto-titling ([`agent_chat.py`](../../../backend/app/services/agent_chat.py) FR-1) gives a decent at-a-glance distinction for most cases.
3. No AC required it; deferring kept Story 4.2 small and shipped chat earlier.

## Current state (refresh 2026-05-14)

| Surface | Status |
|---|---|
| `ConversationSummary` Pydantic schema | 4 fields: `id, title, created_at, message_count` — [`schemas.py:991-997`](../../../backend/app/api/v1/schemas.py#L991-L997) |
| Repo helper | `list_conversations_with_message_counts(db, cursor, limit)` returns `Sequence[tuple[Conversation, int]]` — [`conversation.py:120-154`](../../../backend/app/db/repo/conversation.py#L120-L154) |
| List endpoint | `GET /api/v1/conversations` paginated, returns `ConversationsListResponse` — [`conversations.py:104-141`](../../../backend/app/api/v1/conversations.py#L104) |
| Create endpoint | `POST /api/v1/conversations` returns `ConversationSummary` with `message_count=0` hardcoded — [`conversations.py:91-95`](../../../backend/app/api/v1/conversations.py#L91-L95) |
| Messages table index | `messages_conversation_idx` on `(conversation_id, created_at)` — [`0007_conversations_messages.py:87-90`](../../../migrations/versions/0007_conversations_messages.py#L87-L90). **No new index needed** — this one supports the LATERAL-JOIN lookup. |
| `messages.content` shape | JSONB; user/assistant rows have `{"text": "..."}`; assistant rows MAY have `{"text": "...", "kind": "system_notice"}` (degraded-mode notice per FR-3); tool rows have `{"result": ...}` or `{"error": "..."}` — [`message.py:9-13`](../../../backend/app/db/models/message.py) |
| Contract test | [`test_conversations_api_contract.py`](../../../backend/tests/contract/test_conversations_api_contract.py) pins shape via `ConversationSummary.model_fields` (line 90) — additive fields don't break the existing assertions but a new field name must be added |
| Frontend renderer | [`conversation-list.tsx`](../../../ui/src/components/chat/conversation-list.tsx) — single file, ~62 LOC, two exports (`ConversationList` + `ConversationListCard` wrapper) |
| Frontend type | `ConversationSummary` re-defined in [`ui/src/lib/api/conversations.ts:41`](../../../ui/src/lib/api/conversations.ts#L41) AND in the generated [`ui/src/lib/types.ts:1027`](../../../ui/src/lib/types.ts#L1027) — both must add the new fields |

## Proposed scope

### Backend

1. **Extend the repo helper.** Rename `list_conversations_with_message_counts` → `list_conversations_with_preview_data` (or extend in place; the locked decision below picks "extend in place"). Return shape changes from `Sequence[tuple[Conversation, int]]` to `Sequence[tuple[Conversation, int, str | None, datetime | None]]` (conversation, count, preview, last_at).
2. **Add the LATERAL JOIN.** PostgreSQL-only (the project is Postgres-only). Uses the existing `messages_conversation_idx`:
   ```sql
   LEFT JOIN LATERAL (
     SELECT content->>'text' AS preview_text, created_at AS last_at
     FROM messages
     WHERE conversation_id = conversations.id
       AND role IN ('user', 'assistant')
       AND content ? 'text'
       AND COALESCE(content->>'kind', '') != 'system_notice'
     ORDER BY created_at DESC
     LIMIT 1
   ) m ON true
   ```
3. **Truncate at the repo layer.** Cap preview at 120 chars; append `…` if truncated.
4. **Extend `ConversationSummary`.** Add `last_message_preview: str | None` and `last_message_at: datetime | None`.
5. **Update both endpoints.** `GET /api/v1/conversations` populates the new fields from the repo helper. `POST /api/v1/conversations` returns `last_message_preview=None, last_message_at=None` (mirrors the existing `message_count=0` hardcode for a brand-new row).

### Frontend

1. Extend the `ConversationSummary` TypeScript type in [`ui/src/lib/api/conversations.ts:41`](../../../ui/src/lib/api/conversations.ts#L41) (the hand-rolled type) AND regenerate [`ui/src/lib/types.ts`](../../../ui/src/lib/types.ts) from the new OpenAPI schema.
2. Render preview as a single muted line under the title.
3. Per the locked decision below, **replace the displayed timestamp with `last_message_at` (fall back to `created_at` for empty rows)**.

### Tests

- Backend integration: extend `test_conversation_repo.py` (or equivalent) with cases: empty conversation, single user message, mixed user+assistant+tool, system_notice as last (should be skipped), 121-char message (verify truncation).
- Backend contract: update [`test_conversations_api_contract.py`](../../../backend/tests/contract/test_conversations_api_contract.py) to assert `last_message_preview` and `last_message_at` are in `ConversationSummary.model_fields`.
- Frontend unit: extend conversation-list test with preview rendering + fallback timestamp.

## Decisions locked (refresh 2026-05-14)

- **(locked)** Backend approach: **LATERAL JOIN** against `messages` using the existing `messages_conversation_idx` index. No migration; no `conversations`-table denormalization. Alternatives considered:
  - Correlated subquery: works, same index lookup, slightly less idiomatic in SQLAlchemy 2.0.
  - Denormalize `last_message_preview`/`last_message_at` columns on `conversations`: rejected — adds write-path complexity (every message-insert must update parent), needs a migration + backfill, and the read win is irrelevant at MVP1 scale (single-tenant, low message volume).
- **(locked)** Preview extraction rule: pick the most recent row where `role IN ('user', 'assistant')` AND `content ? 'text'` AND `content->>'kind' != 'system_notice'`. Skip tool rows (no human-readable text) and system_notice rows (transient degraded-mode banners, not real content).
- **(locked)** Truncation at the repo layer, 120 chars, `…` suffix when cut. Avoids per-renderer drift and keeps the API wire shape deterministic.
- **(locked)** Repo helper name: **extend `list_conversations_with_message_counts` in place** to also return preview + last_at. Rename to `list_conversations_with_preview_data` so the symbol reflects the broader return shape. Update both call sites ([`conversations.py:113`](../../../backend/app/api/v1/conversations.py#L113) is the only one). Avoid creating a parallel `_with_preview` helper — one query, one helper.
- **(locked)** `POST /api/v1/conversations` returns `last_message_preview=None, last_message_at=None` (matches the hardcoded `message_count=0` pattern for a brand-new conversation).
- **(locked)** Migration policy: NO migration. The LATERAL-JOIN read is supported by the index that already exists.

## Open questions for /spec-gen

- **Frontend timestamp policy.** Three options:
  - **A (recommended):** Replace the displayed timestamp with `last_message_at` for rows with messages; fall back to `created_at` for empty rows. The list answers "when was this last touched."
  - **B:** Keep `created_at` as primary; show `last_message_at` as tooltip or secondary line.
  - **C:** Keep `created_at`; add preview only.
  Recommend A. The deferred sort-order change (use `last_message_at DESC` for the list query) is a separate question — see below.
- **List sort order.** Currently sorted by `created_at DESC, id DESC` in [`list_conversations_with_message_counts:151-152`](../../../backend/app/db/repo/conversation.py#L151-L152). Should this also switch to `last_message_at DESC` (with `COALESCE(last_message_at, created_at)` to handle empty conversations)? Recommend: defer this — sort-order changes affect cursor-pagination semantics (cursors are `(created_at, id)` tuples per the repo helper) and changing the sort key is a bigger refactor than this chore. File as a follow-up bug/chore if operators ask. Lock the timestamp DISPLAY change in Option A above without changing the sort order.
- **Preview-title duplication.** When auto-titled (FR-1 derives title from the first user message) AND there's only one message, the preview line will repeat the title verbatim. Two options:
  - **A (recommended):** Always render the preview, even if it equals the title. Operator quickly learns the pattern; the cost is one repeated line at the start of a thread; the value is layout consistency.
  - **B:** Skip the preview when it equals the title (case-insensitive trim compare).
  Recommend A. B's logic adds frontend complexity for cosmetic gain.
- **Empty-state line.** When a conversation has zero messages, render the preview row as `"(no messages yet)"` muted, or omit the line entirely? Recommend: **omit**. The existing `formatCount(0)` already shows `"Empty"`; a second muted line is redundant. Conditional: `{row.last_message_preview && <preview-line />}`.

## Sibling coordination

- **[`bug_chat_long_conversation_truncation_mvp2`](../bug_chat_long_conversation_truncation_mvp2/idea.md)** — companion MVP2 chat polish item, also held for MVP2. Different surfaces (truncation is `send_user_message` behavior; this is the list-page read). Could ship in the same MVP2 chat-polish PR or independently. No technical coupling.

## Scope signals

- **Backend:** ~30 LOC repo extension + ~5 LOC schema extension + ~10 LOC endpoint hookup = ~45 LOC net. 1 file each: `repo/conversation.py`, `schemas.py`, `api/v1/conversations.py`.
- **Frontend:** ~20 LOC component change + 2 LOC type extension = ~22 LOC. Files: `conversation-list.tsx`, `lib/api/conversations.ts`. Plus regenerate `lib/types.ts` from OpenAPI.
- **Tests:** ~6 new integration cases on the repo helper + 2 contract-field assertions + 2 frontend render cases.
- **No migration. No new index. No new tool. No new route. No new dep.**
- **CLAUDE.md absolute rules:**
  - Audit-log emission: N/A — read-only feature.
  - Engine adapter: N/A.
  - Webhook signature: N/A.
  - State machine: N/A.
  - Option lists / enums: N/A — no `<select>` or status badge.
  - LLM call: N/A — pure DB read.
  - API conventions: extends existing endpoint, no new shape concerns.

## References

- [`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md`](../../00_overview/implemented_features/2026_05_12_feat_chat_agent/implementation_plan.md) — GPT-5.5 cycle-2 finding F15 origin (folder moved to `implemented_features/` on 2026-05-12 finalization)
- [`bug_chat_long_conversation_truncation_mvp2/idea.md`](../bug_chat_long_conversation_truncation_mvp2/idea.md) — companion held-for-MVP2 chat item
- Postgres LATERAL JOIN docs: https://www.postgresql.org/docs/current/queries-table-expressions.html#QUERIES-LATERAL
