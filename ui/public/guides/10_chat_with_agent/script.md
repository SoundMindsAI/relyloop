# Chat with the agent

> 3-minute walkthrough — drive RelyLoop via natural language + tool dispatch.

The chat agent is RelyLoop's conversational layer. It has function-calling
access to 19 tools spanning cluster introspection, query/template/judgment
CRUD, study lifecycle, and proposal/PR management. The same things you can
do in the UI you can ask the agent to do for you — frequently with fewer
clicks.

## Tool inventory

Grouped by surface:

- **Cluster + schema:** `list_clusters`, `get_cluster`, `get_schema`
- **Templates:** `list_templates`, `get_template`
- **Query sets + judgments:** `list_query_sets`, `create_query_set`,
  `import_queries_from_csv`, `generate_judgments_llm`, `get_calibration`
- **Quick experiments:** `run_query` (ad-hoc top-K against any registered cluster)
- **Studies:** `create_study`, `get_study`, `cancel_study`
- **Proposals + PRs:** `list_proposals`, `get_proposal`,
  `create_proposal_from_study`, `create_proposal_manual`, `open_pr`

See [`docs/01_architecture/agent-tools.md`](../01_architecture/agent-tools.md)
for argument schemas + tool-level prompts.

## SSE event stream

The chat endpoint streams `text/event-stream` over POST. Four event types:

| Event | Payload | Frontend renders as |
|---|---|---|
| `token` | `{text: string}` | Appended to current assistant bubble |
| `tool_call` | `{id, name, arguments}` | Blue `<ToolCallCard>` with expandable args |
| `tool_result` | `{id, name, result?, error?}` | Green/red `<ToolResultCard>` |
| `done` | `{conversation_id, tokens_used?, cost_usd?, error?}` | Re-enables composer |

## Prompt patterns that reliably trigger tools

| Tool | Sample prompt |
|---|---|
| `list_clusters` | "What clusters do we have set up?" |
| `get_schema` | "Show me the fields on the 'products' index of the local-es cluster" |
| `run_query` | "Try a match query for 'running shoes' on products; top 5 hits" |
| `create_study` | "Tune product_search v1 against tutorial_queries on local-es:products, max 10 trials" |
| `get_study` | "What's the status of study abc-123?" |
| `open_pr` | "Open a PR for proposal xyz-456" |

The agent runs with `tool_choice='required'` for ambiguous prompts so it
prefers tool dispatch over freeform speculation. Explicit tool name hints
("Please use list_clusters") are honored.

## Performance + cost

- Simple text turn (no tools): ~1-2s
- Tool call latency: ~500ms to first event
- Tool execution: 100ms-5s (capped per tool — `run_query` is 5s max)
- Full single-tool turn: ~8-12s wall-clock with gpt-4o
- Cost: ~$0.01-0.05 per turn with gpt-4o-mini

## Persistence

Every message (role, content, tool_calls, tool_results) is persisted to
the `messages` table. The conversation list (`/chat`) shows preview text +
last-activity timestamp per row. Conversations survive stack restarts.

## Reference

- API send: `POST /api/v1/conversations/{id}/messages` (returns text/event-stream)
- API list: `GET /api/v1/conversations` — cursor-paginated with previews
- Backend: [`backend/app/services/agent_chat.py`](../../backend/app/services/agent_chat.py)
- Runbook: [`docs/03_runbooks/agent-debugging.md`](../03_runbooks/agent-debugging.md)
- Data-flow security: [`docs/04_security/llm-data-flow.md`](../04_security/llm-data-flow.md)
