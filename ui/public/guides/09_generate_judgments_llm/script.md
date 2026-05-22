# Generate judgments via LLM

> 5-minute walkthrough — the LLM-as-judge ground-truth path.

Judgments are the relevance ratings every study scores against. Two paths
to populate them:

- **Import** (guide 05) — bulk-load pre-curated judgments via API, no LLM call
- **Generate** (this guide) — fire the LLM judge against every (query, doc)
  pair retrieved by your template

This guide covers the generate path against a real OpenAI endpoint. Cost
is bounded by `Settings.openai_daily_budget_usd`; per-run cost depends on
your query set size + template top-K + the model. With `gpt-4o-mini` and
3 queries × 10 docs, expect ~$0.02 per run.

## Steps

1. **Open a query set's detail page** at `/query-sets/{id}`.
2. **Click 'Generate judgments'** in the associated-judgment-lists card.
3. **Fill the form:**
   - **Judgment list name** — unique (the API rejects 409 on duplicate names)
   - **Target** — the cluster's index or collection (e.g., `products`)
   - **Current template** — the query template that produces candidate docs.
     The worker renders this template per query, runs the search, and rates
     every returned doc.
   - **Rubric** — the prompt-level instructions the LLM judge follows.
     Default is a 0–3 relevance scale. Customize for your domain.
4. **Submit.** Returns `202 ACCEPTED` immediately with the new
   `judgment_list_id`. The worker fires in background.
5. **Watch the status** transition `generating → complete | failed`.

## What the worker does

For each query in the set:

1. Render the template with the query (Jinja2 → engine DSL)
2. Run the search against the target index — returns top-K docs
3. For each (query, doc) pair, call OpenAI with the rubric + query text +
   document content → receive a structured `{rating: 0|1|2|3, reasoning: str}`
4. Insert the judgment row (idempotent — `ON CONFLICT DO NOTHING` on the
   `(judgment_list_id, query_id, doc_id)` unique constraint)
5. Increment the daily-cost counter; if it exceeds `openai_daily_budget_usd`,
   the list transitions to `failed` with `BUDGET_EXCEEDED`

## Failure modes + how to triage

| Symptom | Cause |
|---|---|
| `status=failed`, error mentions `CLUSTER_UNREACHABLE` | The cluster's `base_url` resolves from inside the API container but not from where the operator registered it (Docker network mismatch) |
| `status=failed`, error mentions `LLM_PROVIDER_INCAPABLE` | The configured model doesn't support `structured_output`. Switch model or path. |
| `status=failed`, error mentions `BUDGET_EXCEEDED` | Daily LLM spend cap hit. Raise `Settings.openai_daily_budget_usd` or wait until midnight UTC. |
| Stuck at `generating` for hours | Worker crashed mid-list. The periodic resume sweep (`feat_judgments_periodic_resume_sweep`) re-enqueues every 15 minutes, capped at 24/day. |

## Reference

- API: `POST /api/v1/judgments/generate` with `{name, query_set_id, cluster_id, target, current_template_id, rubric}`
- Worker: [`backend/workers/judgments.py`](../../backend/workers/judgments.py) — `generate_judgments_llm`
- Runbook: [`docs/03_runbooks/judgment-generation-debugging.md`](../03_runbooks/judgment-generation-debugging.md)
- Cost-tracking schema: [`docs/04_security/llm-data-flow.md`](../04_security/llm-data-flow.md) explains exactly what gets sent on each LLM call

> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
