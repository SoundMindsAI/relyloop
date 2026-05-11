# LLM data flow — `feat_llm_judgments`

This doc enumerates exactly what tenant data leaves the local stack on a
single `POST /api/v1/judgments/generate` call and describes the controls in
place to bound exposure. It is the spec §15 prerequisite for shipping the
LLM-as-judge worker.

## Scope

Applies to every judgment-generation request — i.e. every invocation of
`backend/workers/judgments.py:generate_judgments_llm`. The import path
(`POST /api/v1/judgment-lists/import`) makes **no LLM call** and is not
covered here.

## Data sent to OpenAI (per query)

The worker makes one OpenAI Chat Completions call per query in the supplied
query set. Each call carries:

| Field | Source | Size |
|---|---|---|
| `system_prompt` | `prompts/judgment_generation.system.md` (operator-fixed) | ~250 tokens |
| Rubric text | `judgment_lists.rubric` (operator-set per list) | ~200–400 tokens |
| Query text | `queries.query_text` for one query in the set | depends on dataset; ~10–80 tokens |
| Per-doc bodies | First **500 chars** of each top-K hit's `_source.body` | ≤500 chars × top-K (typ. 50) |
| Per-doc ids | The engine's native document id for each hit (`_id` in ES) | small string per doc |

The XML-delimited `<rubric>` / `<query>` / `<doc id="...">` boundaries are
constructed by `prompt_loader.render_user_prompt` — variables render as
literal text (no recursive Jinja eval) so adversarial doc content cannot
inject template syntax. Doc bodies are trimmed to 500 chars to bound the
input token count and keep tutorial costs under $1.

## Data NOT sent

* `reference_answer` on `queries` is **never** forwarded to OpenAI. It's
  metadata-only for human curation.
* Full document JSON beyond the `body` field is **never** forwarded.
* No secrets are forwarded — the OpenAI key is the only credential in play,
  and it travels in the `Authorization` header (not in the message body).
* No tenant-level identifiers (tenant ids arrive at MVP4; not in scope here).

## Logging on the worker side

Per spec §13 the worker structured-logs one event per query with:

* `judgment_list_id`, `query_id` — primary keys for traceability.
* `tokens_used`, `cost_usd`, `duration_ms` — billing + perf telemetry.
* Model identifier — `Settings.openai_model` (pinned, no floating tag).

The worker does **NOT** log:

* Query text.
* Document bodies.
* LLM rationales (those are persisted to `judgments.notes` in the DB but
  not duplicated into the structured log stream).

Per CLAUDE.md Absolute Rule #10 secrets are never in any log line. The
capability-check WARN line includes the failing endpoint URL but never the
API key.

## OpenAI retention + Zero Data Retention (ZDR)

OpenAI's standard API retains prompts and responses for 30 days for abuse
monitoring. Operators with sensitive content should enroll in **Zero Data
Retention (ZDR)** — see
[OpenAI Trust & Security](https://openai.com/security/) — at which point
prompts and completions are not persisted server-side.

For local-LLM endpoints (Ollama / vLLM / TGI / LM Studio) the worker treats
the endpoint as a black box; data retention is whatever the operator's
deployment does. RelyLoop never logs the prompts itself.

## Operator controls

1. **Per-list rubric** — operators replace `judgment_lists.rubric` to scope
   the rating criteria; the v1 starter rubric ships verbatim from spec
   §FR-3c.
2. **`OPENAI_BASE_URL`** — point at a local LLM to avoid third-party data
   flow entirely (the SDK is OpenAI-compatible).
3. **`OPENAI_DAILY_BUDGET_USD`** — hard cap on daily spend; the worker's
   pre-call peek refuses to start a call when the projected total exceeds
   the budget. `0` disables the gate.
4. **Doc body trimming** — 500-char cap (constant in
   `backend/workers/judgments.py`); operators can lower it by editing the
   constant.

## Local development

The `make up` Compose stack does NOT forward LLM traffic anywhere — the
`OPENAI_API_KEY_FILE` is empty by default. Operators must opt in by
populating `./secrets/openai_api_key` and (optionally) setting
`OPENAI_BASE_URL` for a local LLM endpoint.

## Future work

* `feat_chat_agent` (next-up after `feat_llm_judgments`) adds a chat
  orchestrator that forwards user messages to the LLM. That feature will
  extend this doc with chat-orchestrator-specific flow.
* MVP2 adds `audit_log` + structured logging via Langfuse + ClickHouse.
  When that lands, the worker will emit one audit event per query so
  operators can trace exactly what data left at what time.

See also: [docs/03_runbooks/judgment-generation-debugging.md](../03_runbooks/judgment-generation-debugging.md)
for operator playbooks (replaying cassettes, computing kappa, bulk-overriding).
