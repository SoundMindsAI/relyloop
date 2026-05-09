# Feature Specification — feat_chat_agent

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-25, US-26, US-27
- [docs/01_architecture/agent-tools.md](../../../01_architecture/agent-tools.md) — tool registry + dispatch pattern
- [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md) — OpenAI SDK + function-calling pattern
- [docs/01_architecture/ui-architecture.md](../../../01_architecture/ui-architecture.md) — chat surface UI patterns
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `conversations`, `messages` tables (extends from `feat_study_lifecycle` stub)
- Depends on: ALL prior backend features (the agent dispatches into them)

---

## 1) Purpose

- **Problem:** Without a chat surface, every operation requires the UI's structured forms. Chat lets the engineer describe the goal in plain language ("tune product_search overnight on staging-products-es") and let the agent translate that to API calls.
- **Outcome:** A chat surface at `/chat/{conversation_id}` streams OpenAI completions via SSE. The agent has a tool registry covering the 18 MVP1 tools (per [`agent-tools.md`](../../../01_architecture/agent-tools.md)). Conversation state persists in `conversations` + `messages` tables; tool calls are visible in expandable panels.
- **Non-goal:** No `propose_search_space` LLM tool (MVP2 — open question). No LangGraph state graph or subagents (GA v1). No human-in-the-loop interrupts (GA v1). No Fusion-specific tools (MVP3). No `fork_study` (MVP2). No multi-conversation parallelism enforcement (MVP4 with multi-tenant).

## 2) Current state audit

After all dependencies ship:
- Every consumed API endpoint exists.
- `conversations` and `messages` tables exist (created by `feat_study_lifecycle` per its stub-table responsibility) — this feature populates them.
- The Next.js skeleton + layout + nav (per `infra_foundation` + `feat_studies_ui`) include a `/chat` link that goes nowhere yet.
- `openai` Python SDK is installed; no LLM calls are being made yet beyond `feat_llm_judgments` and `feat_digest_proposal`.

## 3) Scope

### In scope

- **Backend**:
  - Tool registry at `backend/agent/tools/__init__.py` collecting the 18 MVP1 tools per [`agent-tools.md`](../../../01_architecture/agent-tools.md). Each tool is one Python module under `backend/agent/tools/<category>/<tool>.py`.
  - Orchestrator at `backend/agent/orchestrator.py` running the OpenAI function-calling loop (per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)).
  - SSE endpoint `POST /api/v1/conversations/{id}/messages` accepting a user message and streaming the assistant turn (token + tool_call + tool_result + done events per [`agent-tools.md` §"Streaming + SSE"](../../../01_architecture/agent-tools.md)).
  - REST endpoints:
    - `POST /api/v1/conversations` — create new conversation (returns `conversation_id`)
    - `GET /api/v1/conversations` — list (paginated)
    - `GET /api/v1/conversations/{id}` — detail with full message history
    - `DELETE /api/v1/conversations/{id}` — soft-delete
  - System prompt at `prompts/orchestrator.system.md` framing the agent's role + the available tools.
  - Per-call validation (Pydantic args schema) before dispatch; validation failures appended as tool_result with error payload (LLM gets a retry).
- **Frontend** (`/chat/{conversation_id}` route in `feat_studies_ui`'s Next.js app):
  - Conversation list at `/chat` (sidebar). "New conversation" button.
  - Single-conversation view at `/chat/{conversation_id}`:
    - Message stream rendered in chronological order (user / assistant / tool messages).
    - Composer at the bottom (auto-grows; cmd+enter to send).
    - Tool calls rendered as collapsible `<Card>`s (default collapsed) showing `name` + `arguments` (JSON). Tool results render as a sibling `<Card>` (default collapsed) showing the JSON response.
    - Token streaming: assistant text appears character-by-character as the SSE delivers it.
    - Errors (network, 4xx, 5xx) surface as toast + an inline `<Alert>` below the conversation.
  - SSE consumer in `ui/lib/api/conversations.ts` using native `EventSource`.

### Out of scope

- `propose_search_space` tool — open question; recommend deferral to MVP2.
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
- **Do not** invent tools. The 18 MVP1 tools per [`agent-tools.md`](../../../01_architecture/agent-tools.md) are the complete set. New tools require their own feature spec.
- **Do not** dispatch tool calls in parallel. Sequential dispatch keeps the conversation auditable; the agent rarely needs parallelism. (LangGraph at GA v1 introduces parallel subagents.)
- **Do not** stream tool RESULTS to the client mid-execution. Wait for the tool to complete, then stream the result event. (This avoids partial-result races.)

## 5) Assumptions and dependencies

- **Dependency: ALL backend features** — the tool registry dispatches into every feature's API. Any feature that ships late breaks tools.
- **Dependency: `feat_studies_ui`** — provides the layout shell + nav + TanStack Query setup that the chat UI plugs into.
- **OpenAI API key** — required at chat time (returns `OPENAI_NOT_CONFIGURED` otherwise per `feat_llm_judgments` precedent).

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

### FR-2: SSE messages endpoint
- `POST /api/v1/conversations/{id}/messages` accepts `{role: 'user', content: {text: '...'}}` body and:
  - Persists the user message
  - Initiates the orchestrator loop (per FR-3)
  - Streams events (`token`, `tool_call`, `tool_result`, `done`) via SSE per [`agent-tools.md` §"Streaming + SSE"](../../../01_architecture/agent-tools.md)
- Returns 503 `OPENAI_NOT_CONFIGURED` if `OPENAI_API_KEY_FILE` is missing.

### FR-3: Orchestrator loop
- The orchestrator **MUST** call OpenAI's `chat.completions.create` with `model={settings.OPENAI_MODEL_CHAT}` (default `gpt-4o-mini-2024-07-18` for OpenAI; for local providers reuses `OPENAI_MODEL`), against the configured `OPENAI_BASE_URL`, with `tools=TOOLS`, `tool_choice='auto'`, `stream=True`.
- The orchestrator **MUST** read the capability cache (per `infra_foundation` FR-7). If `function_calling != "ok"` for the configured endpoint, the orchestrator runs WITHOUT tools (passes `tools=[]`); the agent can still chat but cannot dispatch. The first assistant turn in such a session emits a system-level message (visible in the chat UI) explaining: "Tool dispatch is unavailable on this LLM provider (`{base_url}` lacks reliable function-calling). Use the UI to create studies / open PRs."
- The orchestrator **MUST** stream tokens to the SSE connection as they arrive.
- The orchestrator **MUST** detect tool_calls in the stream and, after the stream ends:
  - Persist the assistant message (with `tool_calls` JSONB)
  - For each tool_call: validate arguments via the tool's Pydantic schema; on validation failure append a tool_result with `{error: 'validation_failed', detail: <pydantic_error>}` and continue the loop; on validation success, dispatch via `TOOL_REGISTRY[name](args)`, persist the tool result message, append to OpenAI messages
  - Re-call OpenAI with the augmented message list
- The loop terminates when OpenAI returns a turn with no tool_calls; the final assistant message is persisted; SSE `done` event sent.
- Loop limit: 10 iterations (prevents infinite loops); on exhaustion, send `done` with `error: 'tool_loop_limit_exceeded'`.
- Notes: covers US-25, US-26, US-27.

### FR-4: Tool registry
- The system **MUST** ship 18 MVP1 tools per [`agent-tools.md` §"MVP1 tool inventory"](../../../01_architecture/agent-tools.md):
  - `list_clusters`, `get_cluster`, `get_schema`
  - `list_templates`, `get_template`
  - `list_query_sets`, `create_query_set`, `import_queries_from_csv`, `generate_judgments_llm`, `get_calibration`
  - `run_query`
  - `create_study`, `get_study`, `cancel_study`
  - `list_proposals`, `get_proposal`, `create_proposal_from_study`, `create_proposal_manual`, `open_pr`
- Each tool is a separate module at `backend/agent/tools/<category>/<tool>.py` with a Pydantic args schema, an async impl function, and a `*_TOOL` constant.
- The registry collector at `backend/agent/tools/__init__.py` exports `TOOLS: list[ChatCompletionToolParam]` and `TOOL_REGISTRY: dict[str, Callable]`.

### FR-5: System prompt + confirmation rule
- The system **MUST** load `prompts/orchestrator.system.md` at startup.
- The system prompt **MUST** instruct the agent to:
  - Confirm before calling `create_study`, `cancel_study`, `generate_judgments_llm`, `open_pr`, `create_proposal_*` (the mutating tools).
  - Use `gpt-4o-mini` for cost reasons.
  - Surface tool errors to the user (don't silently retry).
  - Not invent tools beyond the 18 in the registry.

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

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `messages.role` | `user`, `assistant`, `tool` | `backend/db/models/message.py` |
| SSE event types | `token`, `tool_call`, `tool_result`, `done` | `backend/api/conversations.py` (`SSEEventType` `Literal[...]`) |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `CONVERSATION_NOT_FOUND` | 404 | Conversation ID not found / soft-deleted |
| `OPENAI_NOT_CONFIGURED` | 503 | API key missing |
| `OPENAI_BUDGET_EXCEEDED` | 503 | Daily budget hit; retryable in 24h |

## 9) Data model and state transitions

This feature populates `conversations` and `messages` (created by `feat_study_lifecycle` per stub responsibility). No new tables.

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
- **Multiple browser tabs open on the same conversation.** Both tabs receive `useConversation` polls; both attempt SSE on send; first one wins, second one gets a 409 `CONVERSATION_BUSY` (added — let me note this in §19 if needed). Recommend: simpler approach — both connections succeed; LLM messages interleave (rare in practice). Open question.

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
- Then the SSE response immediately delivers `event: done` with `error: 'OPENAI_NOT_CONFIGURED'`; the UI surfaces toast.

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

- **Unit tests** (`backend/tests/unit/`):
  - `agent/test_tool_registry.py` — every MVP1 tool is registered; each has a Pydantic args schema; each has a tool description.
  - `agent/test_dispatch_validation.py` — invalid args produce a tool_result with `validation_failed`.
  - `agent/test_tool_loop_limit.py` — 10-iteration cap is enforced.
- **Integration tests** (`backend/tests/integration/`):
  - `test_chat_simple.py` — single-turn conversation (read-only tool); asserts SSE framing.
  - `test_chat_create_study.py` — full flow: confirm + create_study; cassette-replayed OpenAI.
  - `test_chat_persistence.py` — conversation reconstructable across restart.
- **Contract tests:**
  - `test_conversations_api_contract.py` — REST endpoint shapes.
  - `test_sse_event_shapes.py` — every SSE event type matches the documented body shape.
- **E2E tests:** N/A in MVP1.

## 15) Documentation update requirements

- `docs/01_architecture/agent-tools.md` already documents the tool registry; update if inventory diverges.
- `docs/03_runbooks/`: add `agent-debugging.md` — replay a conversation, force a tool dispatch, inspect SSE events.
- `docs/02_product/mvp1-user-stories.md`: mark US-25 / US-26 / US-27 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** N/A — schema owned by `feat_study_lifecycle`.
- **Operational readiness gates:** Tutorial chat flow at AC-1 succeeds.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (CRUD) | AC-7 | TBD | `tests/integration/test_chat_persistence.py` | runbook |
| FR-2 (SSE) | AC-2, AC-5 | TBD | `tests/integration/test_chat_simple.py` | — |
| FR-3 (loop) | AC-1, AC-6, AC-8 | TBD | `tests/integration/test_chat_create_study.py`, `tests/unit/agent/test_tool_loop_limit.py` | — |
| FR-4 (tool registry) | AC-3 | TBD | `tests/unit/agent/test_tool_registry.py` | agent-tools.md |
| FR-5 (system prompt + confirmation) | AC-4 | TBD | `tests/integration/test_chat_create_study.py` | runbook |
| FR-6 (frontend) | AC-1, AC-2, AC-3 | TBD | `ui/tests/unit/app/chat/[id]/page.spec.tsx` | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/agent/`.
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
