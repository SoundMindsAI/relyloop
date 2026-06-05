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

## Automatic recovery — boot-time sweep + periodic cron

Two automatic recovery paths now cover stuck `status='generating'` rows;
operators rarely need the manual snippet below.

1. **Boot-time sweep** — the worker's `on_startup` hook at
   [`backend/workers/all.py:148-161`](../../backend/workers/all.py#L148-L161)
   sweeps every `status='generating'` row at worker boot and re-enqueues
   `generate_judgments_llm` for each. This covers the "worker crashed mid-run"
   case where a SIGKILL leaves a row without setting `failed_reason`.
   _Origin: per the GPT-5.5 cycle 1 F14 / cycle 2 F1 design from `feat_llm_judgments`._
2. **Periodic in-worker cron** — `resume_stuck_judgment_lists` (shipped by
   `feat_judgments_periodic_resume_sweep`) ticks every
   `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` minutes (default 15) and
   re-enqueues every `status='generating'` row via deterministic
   `_job_id="generate_judgments_llm:<jid>"`. Arq's `_job_id` dedup makes
   an already-in-flight or recently-completed job a no-op by construction.
   This covers the "Arq enqueue raised while the worker is running" case —
   e.g., a transient Redis hiccup during `POST /api/v1/judgments/generate`.

A Redis daily counter `judgments:resume:YYYY-MM-DD:<jid>` (26h TTL, mirrors
the budget-gate pattern at [`backend/app/llm/budget_gate.py:44-50`](../../backend/app/llm/budget_gate.py#L44-L50))
caps re-enqueues per `(id, UTC day)` at `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY`
(default 24). On cap-breach the cron emits `judgment_resume_capped` at WARN
and skips the row — see "Stuck-list cap-breach triage" below.

## Stuck-list cap-breach triage

If you see a `judgment_resume_capped` WARN log line, the periodic cron has
attempted to re-enqueue that `judgment_list_id` more than
`RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` times in the current UTC day and is
backing off. This signals one of two scenarios:

1. **Structurally-broken row** (most common) — bad rubric, missing query
   template, malformed query set. The `generate_judgments_llm` handler
   raises the same way on every retry, leaving the row stuck.
2. **Legitimately long-running job** — the handler is still working through
   a large query set × slow LLM upstream; each tick's attempted re-enqueue
   counts against the cap (per spec §10 Threat 5). The boot-time sweep on
   next worker restart heals this without a cap.

**Triage steps for scenario 1:**

```bash
# 1. Inspect the row state.
docker compose exec postgres psql -U relyloop -d relyloop -c \
  "SELECT id, status, failed_reason, created_at FROM judgment_lists \
   WHERE id = '<judgment-list-id>';"

# 2. If `failed_reason` is populated → the handler tripped a known
#    failure mode (BudgetExceededError, UnknownModelPricingError, etc.).
#    See "End-to-end flow walkthrough" above. Fix the underlying issue
#    (top up budget, pin a known model, etc.).

# 3. If `failed_reason` is NULL but `status='generating'` → the handler
#    is raising an unexpected exception before it can persist
#    failed_reason. Inspect worker logs:
docker compose logs --tail=200 worker | grep -E "(judgment|generate_judgments)"

# 4. After fixing, manually re-enqueue (the cap doesn't block the manual
#    snippet — only the cron is rate-limited). See below.
```

**Triage steps for scenario 2:**

```bash
# Raise the cap via env var, then `make restart api worker`.
# Example: set to 96 (every-tick-all-day at 15-min cadence) to disable
# the cap for legitimately long jobs while keeping the protection
# against runaway loops on broken rows for the rest of the deployment.
echo "RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY=96" >> .env
make restart api worker
```

The cap counter persists in Redis with a 26h TTL — it resets naturally at
UTC midnight. If you need to force a reset for a specific row:

```bash
docker compose exec redis redis-cli DEL "judgments:resume:$(date -u +%Y-%m-%d):<judgment-list-id>"
```

## Resuming a stuck `generating` row manually

The periodic cron resumes stuck rows automatically; this manual path is
needed only when (a) the cron has capped a row that's not actually broken
(see "Stuck-list cap-breach triage" above for the cleaner fix), (b) you
want to force an immediate re-enqueue without waiting for the next tick, or
(c) the cron itself is failing. Run an Arq enqueue directly from a Python
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

## UBI full-traffic scans + operator ceilings

(`chore_ubi_reader_search_after_pagination`)

UBI judgment generation no longer samples a single 10k-event page —
the reader (`backend/app/services/ubi_reader.py`) loops
`adapter.scan_all` until the engine signals terminal or the
configured per-window ceiling is hit. The ceilings live in
`Settings` so operators can tune them without a code change:

| Env var | Default | Effect |
|---|---|---|
| `UBI_MAX_EVENTS_SCAN` | `1_000_000` | High-but-finite ceiling on rows scanned from `ubi_events` per window. The reader truncates at this value and emits a `ubi_reader_scan_truncated` WARN with the exact count. |
| `UBI_MAX_QUERIES_SCAN` | `200_000` | Same for `ubi_queries`. |
| `UBI_QUERY_ID_BATCH_SIZE` | `1024` | Id-count ceiling per `{!terms f=query_id}` (Solr) / `terms` filter (ES) chunk on the events scan. |
| `UBI_QUERY_ID_BATCH_MAX_BYTES` | `32_768` | Encoded byte-length HARD ceiling per chunk — measured on the fully-serialized filter fragment. A batch splits whenever EITHER ceiling is breached. |
| `UBI_NO_PIT_TIEBREAKER_FIELD` | `None` | ES/OpenSearch doc-values unique field (e.g. `event_id`) used as the secondary `search_after` tiebreaker on the no-PIT fallback path. **Never `_id`** — ES 9 disables `_id` fielddata by default. Unset → fallback degrades to a single sampled 10k-row query + WARN. |

**Reading `ubi_reader_scan_truncated`.** Emitted at WARN when the
ceiling truncates a scan:

```json
{
  "event": "ubi_reader_scan_truncated",
  "target": "ubi_events",
  "ceiling": 1000000,
  "scanned": 1000000,
  "engine_type": "elasticsearch"
}
```

The aggregated `FeatureVec` map reflects what the reader saw —
operators with denser traffic should narrow the window via
`since`/`until` rather than raise the ceiling indefinitely.

**PIT-fallback WARN meaning.** The reader's adapter
(`ElasticAdapter.scan_all`) opens a Point-In-Time on the first page
so cursor continuations see a stable snapshot. When the cluster
returns 405/501/400-unsupported on `POST /<idx>/_pit` (e.g. older
OSS distribution without PIT), the adapter degrades:

* If `UBI_NO_PIT_TIEBREAKER_FIELD` is configured → paginated
  `[timestamp, <tiebreaker>]` with `search_after` (no PIT).
* Otherwise → a single sampled query bounded by the page size +
  this WARN:

  ```json
  {
    "event": "elastic_scan_no_pit_sampled_fallback",
    "engine_type": "elasticsearch",
    "target": "ubi_events",
    "reason": "pit_unsupported_and_no_tiebreaker_configured"
  }
  ```

  The WARN is the operator's signal that exact full-traffic
  aggregation is degraded on this cluster.

**Best-effort-under-live-writes caveat.** The PIT (ES/OS) gives the
scan a consistent snapshot for the duration of the lifecycle, so
concurrent writes during a scan don't disrupt continuation. Solr has
no PIT analog — its `cursorMark` is snapshot-exact only when the
window is **finalized** (no further commits inside it); under live
writes the scan is best-effort, like the ES no-PIT path. UBI
judgment windows are normally historical, so the precondition holds
operationally. If you must run a scan over a still-active window,
narrow `since`/`until` to a finalized prefix.

## Known limitations (MVP1)

* **Resolved** — boot-time + periodic-cron resume sweeps both ship in MVP1.
  See "Automatic recovery — boot-time sweep + periodic cron" above.
  Originally tracked as `feat_judgments_periodic_resume_sweep`; merged with
  this runbook update.
* The worker stores LLM rationales in `judgments.notes` but does not yet
  surface them via the API. Inspection requires direct DB access.
* No multi-LLM provider abstraction — every call goes through `openai.AsyncOpenAI`.
  `MVP4` adds the `BaseChatModel` abstraction (Anthropic, Bedrock, Vertex).

## See also

* [docs/04_security/llm-data-flow.md](../04_security/llm-data-flow.md) — what
  data leaves the cluster on every call
* [docs/01_architecture/llm-orchestration.md](../01_architecture/llm-orchestration.md) —
  capability check, model pinning, prompt directory layout
