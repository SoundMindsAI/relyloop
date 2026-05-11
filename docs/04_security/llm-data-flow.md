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

## Digest path (`feat_digest_proposal`)

The `backend/workers/digest.py:generate_digest` job makes **one** OpenAI
Chat Completions call per completed study. The surface is *smaller* than
the judgments path — no doc bodies, no query text, no doc ids — but
otherwise the controls map 1:1.

### Data sent to OpenAI per digest call

| Field | Source | Notes |
|---|---|---|
| `system_prompt` | `prompts/digest_narrative.system.md` (operator-fixed) | ~400 tokens |
| Study metadata | `studies` row + names of cluster / query_set / judgment_list | name strings only; no ids leaked into the narrative |
| Baseline + achieved metric | `studies.baseline_metric` + `studies.best_metric` | two floats |
| Top-10 trials | `(optuna_trial_number, params, primary_metric)` for the top-10 by primary_metric DESC | params are template-declared knobs (e.g. `field_boosts.title=4.7`); NO query / doc content |
| `parameter_importance` map | `optuna.importance.get_param_importances(...)` | `{param: float}` map; pure numerical |
| `recommended_config` | Worker-computed: best-trial params filtered to currently-declared template params | passed AS INPUT to the LLM, not generated by it (per spec FR-5) |
| `dropped_template_params` | Best-trial param keys absent from the current template | empty list when no drift |

### Data NOT sent on the digest path

* **No doc IDs.** The digest never references individual hits.
* **No doc bodies.** Trials store metrics, not raw retrieval content.
* **No query text.** The digest summarises *the study*, not *the queries*.
* **No rubric text.** The judgment-list's rubric is referenced by name
  only (`rubric_summary: "(see judgment list rubric)"`).
* **No secrets.** Same envelope as judgments — API key in
  `Authorization` header only.

### Logging on the digest path

The worker structured-logs one terminal event per study with
`study_id`, `digest_id`, `proposal_id`, `model`, `input_tokens`,
`output_tokens`, `cost_usd`, `duration_ms`,
`structured_output_enabled`, `template_drift_dropped`, `all_dropped`.
The narrative text and `suggested_followups` are persisted to `digests`
but never duplicated into the log stream.

### Capability-fallback path

When the OpenAI capability cache reports
`structured_output != 'ok'` OR `cap.model != Settings.openai_model`
(cycle-3 F2), the worker still makes the LLM call but WITHOUT
`response_format`. The narrative-only fallback STILL costs money so
pricing + budget preflights apply (cycle-3 F2). The persisted digest
has empty `recommended_config` and empty `suggested_followups`; only
`narrative` + `parameter_importance` populate.

### Zero-trials path

When `study.best_metric IS NULL`, the worker writes a placeholder
digest (`narrative = "No successful trials..."`,
`generated_by = "local:zero_trials"`) and DELETEs the pending proposal.
**No OpenAI call is made.** The path runs BEFORE the API-key /
capability / budget preflights (cycle-2 F5) so a misconfigured operator
still gets a clear failure-narrative artifact.

### Cost target

<$0.05 per digest at `gpt-4o-2024-08-06` rates. The pre-call
`peek_daily_total` + `estimated_max_call_cost(model)` gate refuses to
fire when the projected total would breach `OPENAI_DAILY_BUDGET_USD`.

## Future work

* `feat_chat_agent` (after `feat_digest_proposal`) adds a chat
  orchestrator that forwards user messages to the LLM. That feature will
  extend this doc with chat-orchestrator-specific flow.
* MVP2 adds `audit_log` + structured logging via Langfuse + ClickHouse.
  When that lands, the worker will emit one audit event per query so
  operators can trace exactly what data left at what time.

See also: [docs/03_runbooks/judgment-generation-debugging.md](../03_runbooks/judgment-generation-debugging.md)
for operator playbooks (replaying cassettes, computing kappa, bulk-overriding).
