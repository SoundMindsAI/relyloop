# Runbook: debugging judgment generation

Operator playbook for the `feat_llm_judgments` LLM-as-judge pipeline:
inspecting the worker, replaying failures, computing calibration, and
bulk-overriding judgments.

## Quick reference

| Symptom | First check |
|---|---|
| `POST /judgments/generate` returns 503 `OPENAI_NOT_CONFIGURED` | `./secrets/openai_api_key` is empty; populate it and `make up` |
| `POST /judgments/generate` returns 503 `LLM_PROVIDER_INCAPABLE` | The capability cache says `structured_output != ok`; check `make logs` for the WARN line emitted by `backend.app.llm.capability_check` |
| `POST /judgments/generate` returns 503 `UNKNOWN_MODEL_PRICING` | `OPENAI_MODEL` is not in `backend/app/llm/cost_model.py`'s pricing dict; add an entry or pin a known model |
| `POST /judgments/generate` returns 503 `OPENAI_BUDGET_EXCEEDED` (`retryable: true`) | Daily Redis counter at `openai:budget:YYYY-MM-DD` >= `OPENAI_DAILY_BUDGET_USD`; wait for rollover or raise the budget |
| `judgment_lists.status = 'failed'` with `failed_reason = 'OPENAI_BUDGET_EXCEEDED'` | Worker tripped the gate mid-loop; partial judgments persisted (idempotent re-run safe) |
| `POST /calibration` returns 400 `INSUFFICIENT_SAMPLES` after submitting >10 samples | Many samples reference rows that are `source='human'` (already overridden) — calibration filters to `source='llm'`. Run calibration BEFORE overrides |
| Worker not consuming `generating` rows | Confirm the worker boot sweep (in `backend/workers/all.py:on_startup`) re-enqueued in-flight lists; restart `worker` service if not |

## End-to-end flow walkthrough

```text
POST /api/v1/judgments/generate
  ↓ preflight (key / capability / pricing / budget peek / FK / oversized set)
  ↓ INSERT judgment_lists row (status='generating'); commit
  ↓ best-effort arq.enqueue_job('generate_judgments_llm', id)
worker.generate_judgments_llm:
  ↓ load row; bail if missing or already-terminal
  ↓ for each query in set:
    ↓ resume-skip: skip if count_judgments_for_list_and_query >= TOP_K (50)
    ↓ pre-call budget peek (raise BudgetExceededError on breach)
    ↓ adapter.search_batch (top-K hits)
    ↓ render_user_prompt (XML-delimited rubric/query/docs)
    ↓ rate_query_batch (strict JSON schema + retry on 429/5xx)
    ↓ record_cost (post-call INCRBYFLOAT)
    ↓ bulk_create_judgments (ON CONFLICT DO NOTHING)
  ↓ update_judgment_list_status(complete) — or failed_reason on Budget / Pricing / unexpected
```

## Resuming a stuck `generating` row manually

The worker's `on_startup` hook sweeps every `status='generating'` row at
boot and re-enqueues `generate_judgments_llm` for each (per the GPT-5.5
cycle 1 F14 / cycle 2 F1 design). If you need to nudge a single list
without restarting the worker, run an Arq enqueue directly from a Python
REPL inside the worker container:

```bash
docker compose exec worker python -c "
import asyncio
from arq.connections import RedisSettings, create_pool
from backend.app.core.settings import get_settings

async def main():
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await pool.enqueue_job('generate_judgments_llm', '<judgment-list-id>')
    await pool.aclose()

asyncio.run(main())
"
```

## Inspecting a list's state

```bash
curl -s http://127.0.0.1:8000/api/v1/judgment-lists/<id> | jq .
```

Key fields:

* `status` — `generating | complete | failed`.
* `failed_reason` — populated when `status='failed'`; one of
  `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `UNKNOWN_MODEL_PRICING`,
  `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, or
  `UNEXPECTED:<ExceptionType>`.
* `judgment_count` + `source_breakdown` — `{ llm, human }`; invariant
  `llm + human == judgment_count`.
* `calibration` — JSONB with `cohens_kappa`, `weighted_kappa`,
  `per_class`, `n_samples`, optional `warning`. Null until
  `POST /calibration` runs.

## Computing kappa from a CSV of human samples

```bash
# Prepare a JSON body from a CSV with header `query_id,doc_id,rating`
python -c "
import csv, json, sys
rows = list(csv.DictReader(sys.stdin))
print(json.dumps({'human_samples': [
    {'query_id': r['query_id'], 'doc_id': r['doc_id'], 'rating': int(r['rating'])}
    for r in rows
]}))
" < samples.csv > samples.json

curl -s http://127.0.0.1:8000/api/v1/judgment-lists/<id>/calibration \
    -H 'Content-Type: application/json' \
    --data @samples.json | jq .
```

**Run calibration BEFORE any significant volume of human overrides.** The
endpoint filters pairs to `source='llm'` so already-overridden rows are
dropped — a list that's been heavily overridden first will likely return
400 `INSUFFICIENT_SAMPLES` even if you submit 30+ samples.

## Bulk-overriding judgments

The `PATCH /judgment-lists/{id}/judgments/{judgment_id}` endpoint accepts
one override at a time. For bulk operations, drive it from a shell loop:

```bash
# overrides.csv: judgment_id,rating,notes
while IFS=, read -r jid rating notes; do
    curl -sf -X PATCH http://127.0.0.1:8000/api/v1/judgment-lists/<id>/judgments/$jid \
        -H 'Content-Type: application/json' \
        -d "{\"rating\": $rating, \"notes\": \"$notes\"}" > /dev/null \
        || echo "failed: $jid"
done < overrides.csv
```

The list must be in `status='complete'` — overrides while `status='generating'`
return 409 `LIST_NOT_READY`.

## Re-running with a new rubric

The system never mutates a rubric in place — re-running creates a new list:

```bash
curl -s http://127.0.0.1:8000/api/v1/judgments/generate \
    -H 'Content-Type: application/json' \
    -d '{
      "name": "tutorial-v2",
      "description": "with tightened relevance criteria",
      "query_set_id": "<existing-qs-id>",
      "cluster_id": "<cluster-id>",
      "target": "products",
      "current_template_id": "<template-id>",
      "rubric": "<full v2 rubric body>"
    }' | jq .
```

The original `tutorial-v1` list is unchanged; existing studies referencing
it continue to use those judgments.

## Cost telemetry

The worker structured-logs one line per query at INFO level:

```text
event_type=judgment_query_complete
judgment_list_id=...
query_id=...
ratings_count=50
input_tokens=4123
output_tokens=987
cost_usd=0.02018
running_total_usd=0.45
duration_ms=5210
```

To compute per-list cost without parsing logs:

```sql
-- placeholder; the worker doesn't persist per-query token usage in MVP1.
-- MVP2 adds this via the audit_log table.
SELECT judgment_list_id, COUNT(*) AS judgment_count
FROM judgments
GROUP BY judgment_list_id;
```

## Known limitations (MVP1)

* No periodic in-worker resume sweep — only boot-time. A future
  `feat_judgments_periodic_resume_sweep` adds cron-based re-enqueueing
  for stuck `generating` rows (idea file lives in
  `docs/02_product/planned_features/`).
* The worker stores LLM rationales in `judgments.notes` but does not yet
  surface them via the API. Inspection requires direct DB access.
* No multi-LLM provider abstraction — every call goes through `openai.AsyncOpenAI`.
  `MVP4` adds the `BaseChatModel` abstraction (Anthropic, Bedrock, Vertex).

## See also

* [docs/04_security/llm-data-flow.md](../04_security/llm-data-flow.md) — what
  data leaves the cluster on every call
* [docs/01_architecture/llm-orchestration.md](../01_architecture/llm-orchestration.md) —
  capability check, model pinning, prompt directory layout
