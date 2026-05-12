# Agent debugging

Operator runbook for the `feat_chat_agent` chat surface. Three common
debugging tasks: replay a conversation, force a specific tool dispatch via
the chat UI, inspect SSE events directly via `curl`.

The chat-feature surface lives entirely in:

- Router: [`backend/app/api/v1/conversations.py`](../../backend/app/api/v1/conversations.py)
- Service (sole persistence owner): [`backend/app/services/agent_chat.py`](../../backend/app/services/agent_chat.py)
- Pure orchestrator: [`backend/app/agent/orchestrator.py`](../../backend/app/agent/orchestrator.py)
- 19 tools: [`backend/app/agent/tools/`](../../backend/app/agent/tools/)
- System prompt: [`prompts/orchestrator.system.md`](../../prompts/orchestrator.system.md)
- Frontend: [`ui/src/app/chat/`](../../ui/src/app/chat/), [`ui/src/lib/api/conversations.ts`](../../ui/src/lib/api/conversations.ts)

---

## 1. Replay a conversation

Conversations + messages are persisted in two tables:

```sql
-- All non-soft-deleted conversations newest first.
SELECT id, title, created_at, deleted_at
  FROM conversations
  WHERE deleted_at IS NULL
  ORDER BY created_at DESC
  LIMIT 20;

-- Full message history of one conversation in turn order.
SELECT id, role, content, tool_calls, created_at
  FROM messages
  WHERE conversation_id = '<conv_uuid>'
  ORDER BY created_at ASC, id ASC;
```

Open a psql shell with:

```bash
docker compose exec postgres psql -U relyloop relyloop
```

The orchestrator emits a `chat_turn_complete` structlog INFO line on every
completed turn. Filter the API container logs with:

```bash
docker compose logs api 2>&1 | rg chat_turn_complete | rg <conv_uuid>
```

Each line carries `tokens_used`, `cost_usd`, `tool_calls_count`,
`loop_iterations`, `duration_ms` so you can spot expensive turns.

---

## 2. Force a specific tool dispatch via the chat UI

The agent dispatches mutating tools only after the two-condition
confirmation guard fires (per spec FR-5):

1. The most-recent assistant message must mention the tool name.
2. The most-recent user message must contain an affirmative token
   (`yes` / `confirm` / `proceed` / `go ahead` / etc).

To force `cancel_study` from a conversation:

1. Type a message such as: `Please call cancel_study with study_id=<uuid>.`
2. Wait for the assistant's confirmation prompt (it should propose
   `cancel_study` explicitly).
3. Reply `yes`.

If you skip step (1) or reply with `cancel it` (which doesn't match the
exact tool name), the dispatcher returns
`tool_result.error="confirmation_required"` and the impl is never invoked.
This is by design — see `_is_authorized_mutation` in
[`orchestrator.py`](../../backend/app/agent/orchestrator.py).

To force a read-only tool (no confirmation gate), just ask for the data:
`What clusters are registered?` triggers `list_clusters`.

---

## 3. Inspect SSE events directly via `curl`

The streaming endpoint is `POST /api/v1/conversations/{id}/messages` with
content-type `application/json` and an SSE-framed body. The `-N` flag
disables curl's output buffering so events appear as they arrive.

```bash
# Create a conversation first.
CONV=$(curl -s -X POST http://localhost:8000/api/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{"title": "debug session"}' | jq -r .id)

# Stream the user message and watch raw SSE events.
curl -N -X POST "http://localhost:8000/api/v1/conversations/$CONV/messages" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"role": "user", "content": {"text": "list clusters"}}'
```

Expected output looks like:

```
event: token
data: {"text": "I'll list "}

event: token
data: {"text": "the clusters."}

event: tool_call
data: {"id": "call_...", "name": "list_clusters", "arguments": {}}

event: tool_result
data: {"id": "call_...", "name": "list_clusters", "result": {"clusters": []}}

event: token
data: {"text": "There are no clusters registered."}

event: done
data: {"conversation_id": "...", "tokens_used": 145, "cost_usd": 0.000012}
```

### Common failures observed in the SSE stream

| Symptom | Likely cause | Fix |
|---|---|---|
| `event: done` with `error: "openai_rate_limited"` | OpenAI 429 — daily / per-minute quota hit | Wait for quota reset or raise `OPENAI_DAILY_BUDGET_USD` if budget gate triggered |
| `event: done` with `error: "tool_loop_limit_exceeded"` | Agent looped 10 iterations without converging | Inspect the conversation history; if it's looping on a `validation_failed` tool result, the tool's args schema may have drifted from the system-prompt examples |
| `event: tool_result` with `error: "confirmation_required"` | Mutating tool dispatched without confirmation | Re-read the assistant message before yours — did it actually propose this specific tool? |
| `event: tool_result` with `error: "validation_failed"` | LLM-supplied args failed Pydantic validation | The detail field carries the ValidationError; usually a typo in the tool name or a malformed UUID |
| 503 `OPENAI_NOT_CONFIGURED` (plain JSON, no stream) | `OPENAI_API_KEY_FILE` empty or missing | Populate `./secrets/openai_api_key` and restart the API container |
| 503 `OPENAI_BUDGET_EXCEEDED` (plain JSON, no stream) | Daily LLM cost cap reached | Raise `OPENAI_DAILY_BUDGET_USD` or wait for the daily Redis key to roll over (26h TTL) |

### Capability degraded mode

If the OpenAI capability cache reports `function_calling != "ok"` (e.g.,
running against a local Ollama that doesn't support tool dispatch), the
orchestrator runs without tools and the FIRST assistant message of the
session emits a `system_notice`:

```
event: token
data: {"text": "Tool dispatch is unavailable on this LLM provider..."}
```

Subsequent turns suppress the notice (it's persisted as a
`content.kind = "system_notice"` row in `messages`, and the orchestrator's
`degraded_notice_already_sent` flag reads from that).

---

## 4. Common architecture invariants worth knowing

- **`agent_chat.send_user_message` is the SOLE writer of `messages` rows.**
  A grep across `backend/app/agent/` and `backend/app/api/v1/conversations.py`
  for `repo.create_message(` should find zero hits outside `agent_chat.py`.
  Fixing a bug by inserting a row from somewhere else will violate the
  invariant — investigate why `agent_chat` isn't being told about the row
  instead.
- **The orchestrator is a pure async generator.** No DB writes. It yields
  events; `agent_chat` consumes them. Adding a `db.commit()` to
  `orchestrator.py` would couple the two layers.
- **Tool results in OpenAI history are wrapped in `<tool_result>...</tool_result>`
  delimiters with an "ignore embedded instructions" trailer (spec §10
  Threat 4).** If you're seeing the LLM follow instructions from cluster
  data (e.g., a doc body that says "ignore prior instructions"), the wrap
  helper is missing or broken — see `_wrap_tool_result_for_llm` in
  `orchestrator.py`.

---

## See also

- [`docs/01_architecture/agent-tools.md`](../01_architecture/agent-tools.md)
  — the canonical 19-tool inventory.
- [`docs/01_architecture/llm-orchestration.md`](../01_architecture/llm-orchestration.md)
  — capability check + budget gate.
- [`docs/04_security/llm-data-flow.md`](../04_security/llm-data-flow.md)
  — what data the chat agent sends to the LLM provider.
