# Feature Specification — feat_chat_agent

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-25, US-26, US-27
- [docs/01_architecture/agent-tools.md](../../../01_architecture/agent-tools.md) — tool registry + dispatch pattern
- [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md) — OpenAI SDK + function-calling pattern
- [docs/01_architecture/ui-architecture.md](../../../01_architecture/ui-architecture.md) — chat surface UI patterns
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `conversations`, `messages` tables (created by THIS feature)
- Depends on: ALL prior backend features (the agent dispatches into them)

---

## 1) Purpose

- **Problem:** Without a chat surface, every operation requires the UI's structured forms. Chat lets the engineer describe the goal in plain language ("tune product_search overnight on local-es") and let the agent translate that to API calls.
- **Outcome:** A chat surface at `/chat/{conversation_id}` streams OpenAI completions via SSE. The agent has a tool registry covering the 19 MVP1 tools (per [`agent-tools.md`](../../../01_architecture/agent-tools.md) §"MVP1 tool inventory"). Conversation state persists in `conversations` + `messages` tables; tool calls are visible in expandable panels.
- **Non-goal:** No `propose_search_space` LLM tool (deferred to MVP2 per Decision log). No LangGraph state graph or subagents (GA v1). No human-in-the-loop interrupts (GA v1). No Fusion-specific tools (MVP3). No `fork_study` (MVP2). No multi-conversation parallelism enforcement (MVP4 with multi-tenant).

## 2) Current state audit

As of 2026-05-12, every dependency has shipped:

- **Every consumed API endpoint exists** and is verified by contract tests:
  - `GET /api/v1/clusters`, `GET /api/v1/clusters/{id}`, `GET /api/v1/clusters/{id}/schema`, `POST /api/v1/clusters/{id}/run_query` (all in `backend/app/api/v1/clusters.py` from `infra_adapter_elastic`).
  - `GET /api/v1/query-templates`, `GET /api/v1/query-templates/{id}` (from `feat_study_lifecycle` Phase 2).
  - `GET /api/v1/query-sets`, `POST /api/v1/query-sets`, `POST /api/v1/query-sets/{id}/queries` (from `feat_study_lifecycle` Phase 2).
  - `POST /api/v1/judgments/generate`, `GET /api/v1/judgment-lists/{id}` (from `feat_llm_judgments`).
  - `POST /api/v1/studies`, `GET /api/v1/studies/{id}`, `POST /api/v1/studies/{id}/cancel` (from `feat_study_lifecycle` Phase 2).
  - `GET /api/v1/proposals`, `GET /api/v1/proposals/{id}`, `POST /api/v1/proposals`, `POST /api/v1/proposals/{id}/open_pr` (from `feat_digest_proposal` + `feat_github_pr_worker`).
- `conversations` and `messages` tables do NOT exist yet — this feature creates them via Alembic revision `0007_conversations_messages` (the next sequential after `0006_proposals_pr_url_idx`), in the full MVP1 shape per [`data-model.md`](../../../01_architecture/data-model.md). They are terminal (no other features depend on them).
- The Next.js shell + nav include a `/chat` link in `ui/src/components/layout/top-nav.tsx:14` that currently routes to a 404 — this feature fills it (mirroring the `/proposals` shipping pattern from `feat_proposals_ui`).
- The OpenAI client + capability check (`backend/app/llm/openai_judge.py`, `backend/app/llm/capability_check.py`) and budget gate (`backend/app/llm/budget_gate.py`) are in place from `feat_llm_judgments`; this feature reuses them.
- `prompts/` already contains the system + user templates for `feat_llm_judgments` and `feat_digest_proposal`; this feature adds `prompts/orchestrator.system.md`.
- `backend/app/agent/` does NOT exist yet — this feature creates it.

## 3) Scope

### In scope

- **Backend**:
  - Tool registry at `backend/app/agent/tools/__init__.py` collecting the 19 MVP1 tools per [`agent-tools.md` §"MVP1 tool inventory"](../../../01_architecture/agent-tools.md). Each tool is one Python module under `backend/app/agent/tools/<category>/<tool>.py`.
  - Orchestrator at `backend/app/agent/orchestrator.py` running the OpenAI function-calling loop (per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)).
  - SSE endpoint `POST /api/v1/conversations/{id}/messages` accepting a user message and streaming the assistant turn (token + tool_call + tool_result + done events per [`agent-tools.md` §"Streaming + SSE"](../../../01_architecture/agent-tools.md)).
  - REST endpoints:
    - `POST /api/v1/conversations` — create new conversation; returns the full `ConversationSummary` (`id`, `title`, `created_at`, `message_count = 0`), matching the shape of rows returned by `GET /api/v1/conversations`. Clients read `id` from the response to navigate to `/chat/{id}`.
    - `GET /api/v1/conversations` — list (cursor-paginated, soft-deleted rows filtered out)
    - `GET /api/v1/conversations/{id}` — detail with full message history
    - `DELETE /api/v1/conversations/{id}` — soft-delete (sets `deleted_at`; messages preserved via FK CASCADE on hard purge only)
  - Router file at `backend/app/api/v1/conversations.py` (matches the project's `backend/app/api/v1/<resource>.py` convention); registered in `backend/app/main.py` with `prefix="/api/v1"`.
  - System prompt at `prompts/orchestrator.system.md` framing the agent's role + the available tools.
  - Per-call validation (Pydantic args schema) before dispatch; validation failures appended as tool_result with error payload (LLM gets a retry).
- **Frontend** (`/chat/{conversation_id}` route in `feat_studies_ui`'s Next.js app):
  - Conversation list at `/chat` (sidebar). "New conversation" button.
  - Single-conversation view at `/chat/[id]/page.tsx`:
    - Message stream rendered in chronological order (user / assistant / tool messages).
    - Composer at the bottom (auto-grows; cmd+enter to send).
    - Tool calls rendered as collapsible `<Card>`s (default collapsed) showing `name` + `arguments` (JSON). Tool results render as a sibling `<Card>` (default collapsed) showing the JSON response.
    - Token streaming: assistant text appears character-by-character as the SSE delivers it.
    - Errors (network, 4xx, 5xx) surface as toast (via the central `MutationCache.onError` wiring shipped by `feat_studies_ui`) + an inline `<Alert>` below the conversation.
  - Streaming consumer in `ui/src/lib/api/conversations.ts` using `fetch()` with `ReadableStream` (per [`ui-architecture.md` §"Streaming chat"](../../../01_architecture/ui-architecture.md), lines 186-226). **Native `EventSource` is NOT used** — it's GET-only and the user message belongs in the POST body.

### Out of scope

- `propose_search_space` tool — deferred to MVP2 (per Decision log).
- `fork_study` tool — MVP2.
- Fusion-specific tools (`list_pipelines`, `get_pipeline`, `pull_signals`) — MVP3.
- LangGraph orchestrator + subagents + `PostgresSaver` — GA v1.
- Human-in-the-loop interrupts before `open_pr`, prod-cluster studies, judgment regen — GA v1.
- Multi-LLM provider abstraction — MVP4.
- Per-conversation cost tracking dashboard — MVP2 (Langfuse).
- Tool-result diff view (e.g., showing config_diff side-by-side) — MVP3 polish.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). All endpoints under `/api/v1/`. SSE response on the messages endpoint uses standard SSE framing (`Content-Type: text/event-stream`).

### Phase boundaries

Single-phase. The MVP1 deliverable: "the operator opens chat, types 'tune product_search overnight on local-es', the agent walks through clarifying questions (which template? which query set? which judgment list? confirm before kicking off the study?), then calls `create_study` with reasonable defaults, then offers to monitor via `get_study`."

## 4) Product principles and constraints

- **Tool calls are explicit and visible.** Every dispatched tool is rendered as a card the user can expand to see what was passed and what came back. The user must be able to audit the agent's actions.
- **Confirm before mutating tools.** The agent's system prompt explicitly instructs it to confirm with the user before calling `create_study`, `cancel_study`, `generate_judgments_llm`, `open_pr`, `create_proposal_*`. Read tools (`list_*`, `get_*`, `run_query`) need no confirmation.
- **Conversation state is durable.** Every assistant + tool message is persisted in `messages`; the entire conversation is reconstructable from the table. Server restarts don't lose state.
- **Streaming, not request/response.** The user sees tokens as they arrive; tool calls render as soon as the model emits the function-call delta.
- **Cost discipline.** The orchestrator uses `gpt-4o-mini-2024-07-18` (cheap, fast, function-calling-capable). The daily-budget gate per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md) applies.

### Anti-patterns

- **Do not** allow the agent to mutate without confirmation (per system prompt). If the LLM tries to call `create_study` without the user's explicit "yes," dispatch returns an error appended as a tool_result; the LLM gets the message and asks for confirmation.
- **Do not** use the same OpenAI model as judgment generation (`gpt-4o-2024-08-06`). Chat orchestration is cost-sensitive; use `gpt-4o-mini-2024-07-18`.
- **Do not** invent tools. The 19 MVP1 tools per [`agent-tools.md` §"MVP1 tool inventory"](../../../01_architecture/agent-tools.md) are the complete set. New tools require their own feature spec.
- **Do not** dispatch tool calls in parallel. Sequential dispatch keeps the conversation auditable; the agent rarely needs parallelism. (LangGraph at GA v1 introduces parallel subagents.)
- **Do not** stream tool RESULTS to the client mid-execution. Wait for the tool to complete, then stream the result event. (This avoids partial-result races.)

## 5) Assumptions and dependencies

All dependencies shipped between 2026-05-09 and 2026-05-12; this section captures what each one delivered that this feature consumes.

- **`infra_foundation` (PR #4, merged 2026-05-09)** — `OPENAI_BASE_URL` + `openai_api_key_file` + `openai_model_chat` settings; capability cache infrastructure (`backend/app/llm/capability_check.py:read_capability_result(redis, base_url)`) populated at startup.
- **`infra_adapter_elastic` (PR #16, merged 2026-05-10)** — backs `list_clusters`, `get_cluster`, `get_schema`, `run_query` tools via `backend/app/api/v1/clusters.py`.
- **`feat_study_lifecycle` Phase 2 (PR #25, merged 2026-05-11)** — backs `list_templates`, `get_template`, `list_query_sets`, `create_query_set`, `import_queries_from_csv`, `create_study`, `get_study`, `cancel_study` via `backend/app/api/v1/query_templates.py`, `query_sets.py`, `studies.py`.
- **`feat_llm_judgments` (PR #35, merged 2026-05-11)** — backs `generate_judgments_llm` + `get_calibration` via `backend/app/api/v1/judgments.py`. Also: the OpenAI client + budget gate + capability check are reused here; `OPENAI_NOT_CONFIGURED` (503) + `OPENAI_BUDGET_EXCEEDED` (503) error precedents apply.
- **`feat_digest_proposal` (PR #41, merged 2026-05-11)** — backs `list_proposals`, `get_proposal`, `create_proposal_from_study`, `create_proposal_manual` via `backend/app/api/v1/proposals.py`.
- **`feat_github_pr_worker` (PR #45, merged 2026-05-12)** — backs `open_pr` via `POST /api/v1/proposals/{id}/open_pr`. The tool surfaces all 5 error codes the endpoint can return (`PROPOSAL_NOT_FOUND`, `INVALID_STATE_TRANSITION`, `CLUSTER_HAS_NO_CONFIG_REPO`, `GITHUB_NOT_CONFIGURED`, `QUEUE_UNAVAILABLE`) to the LLM as tool_result payloads.
- **`feat_studies_ui` (PR #50, merged 2026-05-12)** — provides the Next.js shell + nav (with the placeholder `/chat` link), TanStack Query setup, central `MutationCache.onError` toast wiring, and the `apiClient` singleton with `X-Request-ID` injection.
- **`feat_proposals_ui` (PR #58, merged 2026-05-12)** — frontend siblings the chat UI links to via tool-result deep links (e.g., after the agent calls `create_proposal_from_study`, it can offer a `/proposals/{id}` link in plain text).
- **OpenAI API key** — required at chat time (returns 503 `OPENAI_NOT_CONFIGURED` otherwise per the `feat_llm_judgments` precedent in `backend/app/api/v1/judgments.py:201`).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (chats with the agent).

### Authorization

N/A — single-tenant install, no auth surface. The agent dispatches tools as the system actor; no impersonation. MVP4 introduces per-tenant tool gating per [`agent-tools.md` §"Reserved for later releases"](../../../01_architecture/agent-tools.md).

### Audit events

N/A — `audit_log` is MVP2. When MVP2 ships, this feature's mutating tool dispatches (`create_study`, `cancel_study`, `generate_judgments_llm`, `open_pr`, `create_proposal_*`) will emit audit events through the underlying API endpoints' instrumentation — no separate audit-event emission from the chat layer.

## 7) Functional requirements

### FR-1: Conversation CRUD
- `POST /api/v1/conversations` creates a row with optional `title` (auto-generated from the first user message if not supplied).
- `GET /api/v1/conversations?cursor=&limit=` paginated list.
- `GET /api/v1/conversations/{id}` returns the conversation + all `messages` ordered by `created_at`.
- `DELETE /api/v1/conversations/{id}` soft-delete (`deleted_at` populated; messages cascade-deleted on hard purge — runbook covers).

### FR-2: Streaming messages endpoint
- `POST /api/v1/conversations/{id}/messages` accepts `{role: 'user', content: {text: '...'}}` body and:
  - Persists the user message
  - Initiates the orchestrator loop (per FR-3)
  - Returns HTTP 200 with `Content-Type: text/event-stream` and streams events (`token`, `tool_call`, `tool_result`, `done`) in standard SSE framing (`event: <type>\ndata: <json>\n\n`) per [`agent-tools.md` §"Streaming + SSE"](../../../01_architecture/agent-tools.md). Frontend consumes via `fetch() + ReadableStream` per [`ui-architecture.md` §"Streaming chat"](../../../01_architecture/ui-architecture.md) (NOT native `EventSource`, which is GET-only).
- Returns 503 `OPENAI_NOT_CONFIGURED` if `OPENAI_API_KEY_FILE` is missing.

### FR-3: Orchestrator loop
- The orchestrator **MUST** call OpenAI's `chat.completions.create` with `model=settings.openai_model_chat` (default `gpt-4o-mini-2024-07-18` per `backend/app/core/settings.py:117`; for local providers operators can override to reuse `openai_model`), against the configured `openai_base_url`, with `tools=TOOLS`, `tool_choice='auto'`, `stream=True`.
- The orchestrator **MUST** read the capability cache via `read_capability_result(redis_client, base_url)` from `backend/app/llm/capability_check.py:372`. If `function_calling != "ok"` for the configured endpoint, the orchestrator runs WITHOUT tools (passes `tools=[]`); the agent can still chat but cannot dispatch. The first assistant turn in such a session emits a system-level message (visible in the chat UI) explaining: "Tool dispatch is unavailable on this LLM provider (`{base_url}` lacks reliable function-calling). Use the UI to create studies / open PRs."
- The orchestrator **MUST** stream tokens to the SSE connection as they arrive.
- The orchestrator **MUST** detect tool_calls in the stream and, after the stream ends:
  - Persist the assistant message (with `tool_calls` JSONB)
  - For each tool_call: validate arguments via the tool's Pydantic schema; on validation failure append a tool_result with `{error: 'validation_failed', detail: <pydantic_error>}` and continue the loop; on validation success, dispatch via `TOOL_REGISTRY[name](args)`, persist the tool result message, append to OpenAI messages
  - Re-call OpenAI with the augmented message list
- The loop terminates when OpenAI returns a turn with no tool_calls; the final assistant message is persisted; SSE `done` event sent.
- Loop limit: 10 iterations (prevents infinite loops); on exhaustion, send `done` with `error: 'tool_loop_limit_exceeded'`.
- Notes: covers US-25, US-26, US-27.

### FR-4: Tool registry
- The system **MUST** ship 19 MVP1 tools per [`agent-tools.md` §"MVP1 tool inventory"](../../../01_architecture/agent-tools.md) (counted across the 6 categories below: 3 + 2 + 5 + 1 + 3 + 5 = 19):
  - **Cluster & schema (3):** `list_clusters`, `get_cluster`, `get_schema`
  - **Templates (2):** `list_templates`, `get_template`
  - **Query sets & judgments (5):** `list_query_sets`, `create_query_set`, `import_queries_from_csv`, `generate_judgments_llm`, `get_calibration`
  - **Quick experiments (1):** `run_query`
  - **Studies (3):** `create_study`, `get_study`, `cancel_study`
  - **Proposals & PRs (5):** `list_proposals`, `get_proposal`, `create_proposal_from_study`, `create_proposal_manual`, `open_pr`
- Each tool is a separate module at `backend/app/agent/tools/<category>/<tool>.py` with a Pydantic args schema, an async impl function, and a `*_TOOL` constant.
- The registry collector at `backend/app/agent/tools/__init__.py` exports `TOOLS: list[ChatCompletionToolParam]` and `TOOL_REGISTRY: dict[str, Callable]`.

### FR-5: System prompt + confirmation rule
- The system **MUST** load `prompts/orchestrator.system.md` at startup.
- The system prompt **MUST** instruct the agent to:
  - Confirm before calling `create_study`, `cancel_study`, `generate_judgments_llm`, `open_pr`, `create_proposal_*` (the mutating tools).
  - Use `gpt-4o-mini` for cost reasons.
  - Surface tool errors to the user (don't silently retry).
  - Not invent tools beyond the 19 in the registry.

### FR-6: Frontend chat surface
- `/chat` route shows the conversation list (sidebar) + "New conversation" button. Selecting a conversation routes to `/chat/{id}`.
- `/chat/{conversation_id}` renders:
  - Full message history (initial fetch via `useConversation(id)` query)
  - Composer at bottom (textarea + Send button + cmd+enter shortcut)
  - On Send: optimistic-append the user message to the local view; open SSE; render incoming tokens; render `tool_call` and `tool_result` events as collapsible cards
  - On `done`: refetch `useConversation(id)` to ensure server-persisted state matches
- Tool-call cards render: tool name (header), arguments (JSON, syntax-highlighted), expand/collapse toggle.
- Tool-result cards render: tool name + "✓" or "✗" badge, result JSON, expand/collapse.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/conversations` | Create conversation | (none) |
| `GET` | `/api/v1/conversations` | List | (none) |
| `GET` | `/api/v1/conversations/{id}` | Detail with messages | `CONVERSATION_NOT_FOUND` |
| `DELETE` | `/api/v1/conversations/{id}` | Soft-delete | `CONVERSATION_NOT_FOUND` |
| `POST` | `/api/v1/conversations/{id}/messages` | Send a user message; SSE response | `CONVERSATION_NOT_FOUND`, `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED` |

The SSE response body uses standard SSE framing per FR-2.

### 7.4 Enumerated value contracts

| Field | Accepted values | Backend wire-shape source of truth (gate-scanned) | DB-level source of truth (constraint) |
|---|---|---|---|
| `messages.role` | `user`, `assistant`, `tool` | `backend/app/api/v1/schemas.py` (`MessageRoleWire = Literal["user", "assistant", "tool"]`) | `backend/app/db/models/message.py` (CHECK constraint on the `role` column) |
| SSE event types | `token`, `tool_call`, `tool_result`, `done` | `backend/app/api/v1/schemas.py` (`SSEEventTypeWire = Literal["token", "tool_call", "tool_result", "done"]`) | — (no DB persistence) |

Frontend tests + components consuming these values MUST add `// Values must match backend/app/api/v1/schemas.py MessageRoleWire` and `// Values must match backend/app/api/v1/schemas.py SSEEventTypeWire` source-of-truth comments in `ui/src/lib/enums.ts` (mirroring the 19 allowlists shipped by `feat_studies_ui`'s Story 4.2). The CI gate at `scripts/ci/verify_enum_source_of_truth.sh` imports the cited module and validates that the enum array in `enums.ts` matches the Literal character-for-character. The wire-shape Literals live in `schemas.py` (where every other allowlist in the project lives, per the `feat_studies_ui` precedent — `STUDY_STATUS_VALUES`, `TRIAL_STATUS_VALUES`, etc.); the DB CHECK constraint on `messages.role` in `message.py` is a defense-in-depth duplicate that MUST agree with the schema Literal (drift between them would be a migration bug). Verified by visual inspection that both lists are identical (`user`, `assistant`, `tool`) at migration time.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `CONVERSATION_NOT_FOUND` | 404 | Conversation ID not found / soft-deleted |
| `OPENAI_NOT_CONFIGURED` | 503 | API key missing |
| `OPENAI_BUDGET_EXCEEDED` | 503 | Daily budget hit; retryable in 24h |

## 9) Data model and state transitions

This feature creates `conversations` and `messages` per [`data-model.md`](../../../01_architecture/data-model.md) via Alembic revision `0007_conversations_messages` (next sequential after `0006_proposals_pr_url_idx`). Both are terminal tables (no other MVP1 feature depends on them). Migration adds full MVP1 shape; no other features ALTER these tables.

**Required columns** (per CLAUDE.md conventions):
- `conversations`: `id UUID PK`, `title TEXT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `deleted_at TIMESTAMPTZ NULL` (soft-delete per CLAUDE.md "soft delete via `deleted_at` on user-facing tables").
- `messages`: `id UUID PK`, `conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE`, `role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool'))`, `content JSONB NOT NULL`, `tool_calls JSONB NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.

Both `created_at` columns use `TIMESTAMPTZ` storing UTC (per `data-model.md` §"Conventions"). Migration MUST include `downgrade()` per CLAUDE.md Absolute Rule #5; round-trip verified via `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. The agent calls a destructive tool (`cancel_study`, `open_pr`) without user confirmation. **Mitigation:** system prompt mandates confirmation; CI test asserts the system prompt contains the confirmation rule.
  2. The agent leaks API keys via tool results. **Mitigation:** structlog redaction filter; tool implementations never include credentials in their return values.
  3. The user pastes credentials into a chat message (e.g., asks the agent to "register a cluster with this token"). **Mitigation:** the chat UI shows a warning banner about not pasting secrets; the API does not specially scrub user message content (it's the user's data).
  4. Prompt injection via doc content fetched by `run_query` (the LLM might be tricked by hostile content). **Mitigation:** the orchestrator system prompt explicitly instructs the model to ignore instructions embedded in tool results; tool result content is wrapped in delimiters.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

### Primary flows

1. **Tutorial flow:** "tune product_search on local-es" → agent asks for query set + judgment list + budget → confirms → calls `create_study` → returns study_id → user asks "how is it going?" → agent calls `get_study` → reports.
2. **Override flow:** "the LLM rated query Q doc D as 2 but I think it's 0" → agent asks for the judgment_id → calls (well, we don't have a `override_judgment` tool in MVP1; the agent points the user to the UI). NOTE: MVP1 does NOT have a judgment-override tool — this is a deliberate scope decision (manual override happens in the Judgment Review UI, not chat).

### Edge/error flows

- **OpenAI rate-limit mid-stream.** SSE delivers a `done` event with `error: 'openai_rate_limited'`; UI surfaces toast.
- **Tool dispatch raises** (e.g., backend 500). Tool result event payload includes `{error: '<error_code>', message: '<human>'}`; LLM gets the message and either retries with corrections or surfaces to user.
- **Tool loop limit hit (10 iterations).** Loop terminates with `done.error = 'tool_loop_limit_exceeded'`; conversation is in a recoverable state — user can retry their request.
- **User reloads page mid-stream.** SSE connection drops; the assistant turn that was in flight is incomplete in the database (only the user message persisted). UI on reload shows the conversation up to the last completed turn; user can re-send the message.
- **Multiple browser tabs open on the same conversation.** Locked in §19 decision log (2026-05-09): **laissez-faire** — both connections succeed; LLM messages interleave (rare in practice). `CONVERSATION_BUSY` (409) deferred to MVP2 if real complaints emerge.

## 12) Given/When/Then acceptance criteria

### AC-1: Tutorial chat flow

- Given the operator opens `/chat`, clicks New conversation, types "tune product_search on local-es overnight against the tutorial query set and tutorial judgment list. budget 100 trials."
- When the agent responds.
- Then within 30s the agent confirms the parameters, asks for explicit go-ahead. After the operator types "yes", the agent calls `create_study` (visible as a tool_call card), receives the study response (visible as a tool_result card), and confirms in plain text. The actual `studies` row is created with the agreed config.

### AC-2: Streaming token-by-token

- Given any agent response.
- When the orchestrator streams.
- Then the UI renders tokens as they arrive (verifiable by network inspector showing `text/event-stream` with `event: token` framing every 100-300ms during a streaming response).

### AC-3: Tool-call card expand/collapse

- Given a conversation where the agent called `get_study`.
- When the operator clicks the tool-call card header.
- Then the card expands to show `name: get_study`, `arguments: {study_id: 'stu_...'}`, and the result JSON. Click again collapses.

### AC-4: Confirm-before-mutate

- Given the operator says "cancel study stu_X".
- When the agent processes.
- Then the agent first asks "Confirm cancel of study stu_X (status: running)?" (in plain text). Only after the operator says "yes" does the agent call `cancel_study`. Verifiable by inspecting the message history: the agent message preceding the tool_call must contain a confirmation prompt.

### AC-5: Reject when OpenAI key missing

- Given `./secrets/openai_key` is empty.
- When the operator sends any chat message.
- Then `POST /api/v1/conversations/{id}/messages` returns **HTTP 503** with a standard JSON envelope `{"detail": {"error_code": "OPENAI_NOT_CONFIGURED", "message": "...", "retryable": false}}` — the SSE stream never opens. The frontend's `streamChatMessage` consumer catches the non-OK response, throws `ApiError`, and `toast.error(toToastMessage(err))` surfaces the toast. This matches the FR-2 wording, the `feat_llm_judgments` precedent (`OPENAI_NOT_CONFIGURED` always returns 503 JSON at `backend/app/api/v1/judgments.py:201`), and the global `MutationCache`/manual-toast pattern shipped by `feat_studies_ui`. Resolved 2026-05-12 during cross-model review of the implementation plan — original wording in this AC suggested an in-stream SSE `done.error` payload, which contradicted FR-2 and the codebase precedent.

### AC-6: Tool validation failure surfaces to LLM

- Given the agent (incorrectly) generates a `create_study` call with `cluster_id: "not-a-uuid"`.
- When the dispatcher validates.
- Then a tool_result event is emitted with `{error: 'validation_failed', detail: 'cluster_id must be a valid UUID'}`. The LLM (in the next loop iteration) responds with a corrected call OR asks the user for clarification.

### AC-7: Conversation persistence across restart

- Given a conversation with 5 turns.
- When the API container restarts (`docker compose restart api`).
- Then opening `/chat/{conversation_id}` shows all 5 turns reconstructed from the database (via `GET /api/v1/conversations/{id}`).

### AC-8: Tool loop limit prevents infinite loops

- Given a deliberately-confused prompt that keeps invoking tools without converging.
- When the loop runs.
- Then after 10 iterations, the loop terminates with `done.error = 'tool_loop_limit_exceeded'`. Conversation history shows all 10 tool exchanges.

## 13) Non-functional requirements

- **Performance:** First token within 1.5s p99 of message send (limited by OpenAI's TTFT). Tool dispatch latency is the underlying API's latency (e.g., `get_study` is ~50ms).
- **Cost:** Average chat turn <$0.005 with `gpt-4o-mini` (assuming ~2K input tokens, 500 output, no tool loops).
- **Reliability:** Conversation history is never lost (atomic message persist).
- **Operability:** Every assistant turn logs `conversation_id`, `tokens_used`, `tool_calls_count`, `loop_iterations`, `duration_ms`, `cost_usd` at INFO.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/agent/`):
  - `test_tool_registry.py` — every MVP1 tool is registered; each has a Pydantic args schema; each has a tool description.
  - `test_dispatch_validation.py` — invalid args produce a tool_result with `validation_failed`.
  - `test_tool_loop_limit.py` — 10-iteration cap is enforced.
- **Integration tests** (`backend/tests/integration/`):
  - `test_chat_simple.py` — single-turn conversation (read-only tool); asserts SSE framing.
  - `test_chat_create_study.py` — full flow: confirm + create_study; cassette-replayed OpenAI.
  - `test_chat_persistence.py` — conversation reconstructable across restart.
  - `test_conversations_migration.py` — Alembic round-trip on `0007_conversations_messages` (mirror the `feat_llm_judgments` pattern at `backend/tests/integration/test_judgments_migration.py`).
- **Contract tests** (`backend/tests/contract/`):
  - `test_conversations_api_contract.py` — REST endpoint shapes + the 3 error codes (`CONVERSATION_NOT_FOUND`, `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`).
  - `test_sse_event_shapes.py` — every SSE event type (`token`, `tool_call`, `tool_result`, `done`) matches the documented body shape.
- **Frontend tests** (`ui/src/__tests__/`):
  - `app/chat/page.test.tsx` — conversation list rendering.
  - `app/chat/[id]/page.test.tsx` — message stream + composer + tool-call card expand/collapse + SSE consumer wiring.
- **E2E tests:** N/A in MVP1.

## 15) Documentation update requirements

- `docs/01_architecture/agent-tools.md` already documents the tool registry; update if inventory diverges.
- `docs/03_runbooks/`: add `agent-debugging.md` — replay a conversation, force a tool dispatch, inspect SSE events.
- `docs/02_product/mvp1-user-stories.md`: mark US-25 / US-26 / US-27 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Creates `conversations` and `messages` tables in their full MVP1 shape. No backfill (these tables start empty).
- **Operational readiness gates:** Tutorial chat flow at AC-1 succeeds.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (CRUD) | AC-7 | TBD | `tests/integration/test_chat_persistence.py` | runbook |
| FR-2 (SSE) | AC-2, AC-5 | TBD | `tests/integration/test_chat_simple.py` | — |
| FR-3 (loop) | AC-1, AC-6, AC-8 | TBD | `tests/integration/test_chat_create_study.py`, `tests/unit/agent/test_tool_loop_limit.py` | — |
| FR-4 (tool registry) | AC-3 | TBD | `tests/unit/agent/test_tool_registry.py` | agent-tools.md |
| FR-5 (system prompt + confirmation) | AC-4 | TBD | `tests/integration/test_chat_create_study.py` | runbook |
| FR-6 (frontend) | AC-1, AC-2, AC-3 | TBD | `ui/src/__tests__/app/chat/[id]/page.test.tsx` | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/app/agent/`.
- [ ] Tutorial chat flow demoable in <2 min.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — `gpt-4o-mini-2024-07-18` for orchestrator (vs. `gpt-4o-2024-08-06` for judgments/digest) — cost discipline.
- 2026-05-09 — Sequential tool dispatch only — auditability + simplicity. LangGraph at GA v1 brings parallel subagents.
- 2026-05-09 — No `override_judgment` tool in MVP1 — judgment override happens in the UI; chat agent points the user there.
- 2026-05-09 — `propose_search_space` tool: **defer to MVP2**. Without LangGraph (GA v1), the one-shot LLM call without state-graph review feels half-built; better to ship structured search-space proposal alongside the orchestrator that supports human-in-the-loop interrupts. The MVP1 chat agent helps fill the create-study form via dialogue, doesn't propose search spaces unaided.
- 2026-05-09 — Multi-tab handling: **laissez-faire** (allow concurrent tabs to both POST messages; LLM responses interleave; rare in practice). Add `CONVERSATION_BUSY` 409 at MVP2 if real complaints emerge.
- 2026-05-09 — Confirmation list expanded to include `import_queries_from_csv` (large bulk add risk).
- 2026-05-09 — Tool loop limit: **10** (per FR-3).
- 2026-05-12 — `/idea-preflight` ground-truth pass against the codebase after all 8 backend + 2 frontend dependencies shipped: §2 + §5 rewritten past-tense with merge dates; backend paths corrected from `backend/<x>/` → `backend/app/<x>/` (4 occurrences in §3 + FR-4 + §7.4); frontend path corrected from `ui/lib/api/` → `ui/src/lib/api/` (2 occurrences); test paths corrected from `ui/tests/unit/...` → `ui/src/__tests__/...` (§14 + §17); tool count corrected from "18" to "19" (§1 + §3 + FR-4 — 3 + 2 + 5 + 1 + 3 + 5 = 19); `settings.OPENAI_MODEL_CHAT` → `settings.openai_model_chat` (FR-3); capability cache citation tightened to `read_capability_result(redis_client, base_url)` at `capability_check.py:372`; §9 expanded with the full column inventory + `0007_conversations_messages` migration revision number + soft-delete `deleted_at` column requirement (per CLAUDE.md "soft delete via deleted_at"); §11 multi-tab "Open question" cleaned up to point at the 2026-05-09 lock; §14 added `test_conversations_migration.py` for Alembic round-trip per the `feat_llm_judgments` precedent; §7.4 cited the `verify_enum_source_of_truth.sh` CI gate that `feat_studies_ui` Story 4.2 shipped. Tutorial-flow language in §1 aligned to `local-es` (was `staging-products-es`; MVP1 has no staging).
- 2026-05-12 — Cross-model review of the `implementation_plan.md` (GPT-5.5, cycle 1) surfaced two spec patches: (a) FR-5 final straggler "18" → "19" (caught by Opus internal review before the GPT-5.5 call); (b) §3 `POST /conversations` return-shape prose tightened from "returns `conversation_id`" to "returns the full `ConversationSummary` (`id`, `title`, `created_at`, `message_count = 0`)" so the wire contract matches the GET-list row shape and the Pydantic schema in the plan; (c) AC-5 corrected from "SSE response immediately delivers `event: done` with `error: 'OPENAI_NOT_CONFIGURED'`" → "HTTP 503 JSON envelope" to match FR-2 and the `feat_llm_judgments` precedent at `backend/app/api/v1/judgments.py:201`. Both spec changes resolve in-spec contradictions that would have caused implementation drift.
