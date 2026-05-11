# Runbook: debugging digest generation

Operator playbook for the `feat_digest_proposal` worker
(`backend/workers/digest.py`): inspecting the digest pipeline, replaying
deferred runs, manually rejecting proposals, and recovering from the
worker-side terminal failure modes.

## Quick reference

| Symptom | First check |
|---|---|
| `GET /api/v1/studies/{id}/digest` returns 404 `DIGEST_NOT_READY` (`retryable: true`) | Either the study is not yet `completed`, or the worker hasn't run. Check `study.status` + `make logs api worker` for the latest digest event_type |
| `make logs worker` shows `digest_openai_not_configured` (`error_code=OPENAI_NOT_CONFIGURED`) | `./secrets/openai_api_key` is empty; populate it and restart the worker — the boot scan picks up the orphaned pending proposal |
| `make logs worker` shows `digest_capability_fail` (`error_code=LLM_PROVIDER_INCAPABLE`) | The capability cache says `structured_output != ok` OR `cap.model != Settings.openai_model`. Check `make logs api` for the WARN from `backend.app.llm.capability_check` |
| `make logs worker` shows `digest_unknown_pricing` (`error_code=UNKNOWN_MODEL_PRICING`) | `OPENAI_MODEL` is not in `backend/app/llm/cost_model.py`'s pricing dict. Add an entry or pin a known model |
| `make logs worker` shows `digest_budget_exceeded` (`error_code=OPENAI_BUDGET_EXCEEDED`) | Daily Redis counter at `openai:budget:YYYY-MM-DD` >= `OPENAI_DAILY_BUDGET_USD`; wait for rollover or raise the budget |
| `make logs worker` shows `digest_lock_contention` | Two workers tried to generate concurrently; the loser logs and exits. The winner persists. Benign |
| `make logs worker` shows `digest_template_drift_all_dropped` | Every best-trial param drifted out of the current template. Digest persisted with empty `recommended_config`; pending proposal DELETED. Operator must re-add the dropped params or treat the study as stale |
| `make logs worker` shows `digest_already_persisted` | Re-entry into a study that already has a digest. No-op. Benign |
| `make logs worker` shows `digest_proposal_no_longer_pending` | Operator rejected the proposal mid-LLM-call. Digest persisted; proposal stays rejected (per cycle-3 F4) |

## End-to-end flow walkthrough

```text
study completes (orchestrator commits status='completed' + INSERT pending proposal)
  ↓ best-effort arq.enqueue_job('generate_digest', study_id) at orchestrator.py:370
worker.generate_digest:
  ↓ Step 1: load study, bail if missing or != 'completed'
  ↓ Step 2: pre-LLM idempotency guard (get_digest_for_study)
  ↓ Step 3: pg_try_advisory_xact_lock(blake2b("digest:{sid}"))
  ↓ Step 4: locate pending proposal (defensive INSERT if missing)
  ↓ Step 5: zero-trials short-circuit (best_metric IS NULL → placeholder digest + DELETE proposal + return)
  ↓ Step 6: OpenAI key check
  ↓ Step 7: capability check → set structured_output_enabled flag (NOT short-circuit)
  ↓ Step 8: model-pricing check (applies to BOTH paths)
  ↓ Step 9: daily-budget peek (applies to BOTH paths)
  ↓ Step 10: optuna.importance.get_param_importances + load top-K trials
  ↓ Step 11: deterministic recommended_config (filter best_trial.params to declared)
              all-dropped → DELETE proposal + persist empty-recommendation digest
  ↓ Step 12: render prompt + OpenAI call (response_format=DIGEST_RESPONSE_FORMAT or omitted)
  ↓ Step 13: merge follow-ups (drift-followup prepended; cap at 5)
  ↓ Step 14: compute metric_delta + config_diff
  ↓ Step 15: persist FIRST then record_cost
              INSERT digest + UPDATE proposal (conditional WHERE status='pending')
```

## Re-running a deferred digest after fixing the upstream condition

1. Identify the affected study:
   ```bash
   docker compose exec api psql -U relyloop -c "
     SELECT p.id, p.study_id FROM proposals p
     LEFT JOIN digests d ON d.study_id = p.study_id
     WHERE p.status = 'pending' AND p.study_id IS NOT NULL AND d.id IS NULL;
   "
   ```
2. Fix the upstream condition:
   - **OPENAI_NOT_CONFIGURED** — populate `./secrets/openai_api_key`, then `docker compose restart api worker` (the API rebuilds the capability cache; the worker picks up the new key on next tick).
   - **LLM_PROVIDER_INCAPABLE** — verify `OPENAI_BASE_URL` is reachable + the model supports structured output. Re-run the capability check by restarting the API.
   - **UNKNOWN_MODEL_PRICING** — add the model to `backend/app/llm/cost_model.py:_MODEL_USD_PER_1K_INPUT` + `_OUTPUT`, redeploy.
   - **OPENAI_BUDGET_EXCEEDED** — wait for UTC rollover OR raise `OPENAI_DAILY_BUDGET_USD` in `.env` and `docker compose up -d`.
3. **The worker's boot-time scan re-enqueues automatically.** A `docker compose restart worker` is sufficient — `backend/workers/all.py:on_startup` calls `repo.list_pending_proposals_for_boot_scan` and re-enqueues `generate_digest:{study_id}` for each.
4. Optional: manually trigger a single re-run via the Arq REPL (not needed if you restarted the worker):
   ```bash
   docker compose exec api python -c "
   import asyncio
   from arq.connections import RedisSettings, create_pool
   from backend.app.core.settings import get_settings
   async def go():
       pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
       await pool.enqueue_job('generate_digest', '<study_id>', _job_id='generate_digest:<study_id>')
   asyncio.run(go())
   "
   ```

## Force-regenerating a digest

The system enforces one digest per study (UNIQUE on `digests.study_id`).
Re-running `generate_digest` for a study that already has a digest is a
no-op (the Step 2 idempotency guard short-circuits with
`digest_already_persisted`).

To force a regeneration (e.g. after editing the prompt files):

```bash
docker compose exec api psql -U relyloop -c "DELETE FROM digests WHERE study_id = '<study_id>';"
docker compose restart worker  # boot scan re-enqueues
```

If the operator also wants to reset the proposal's `config_diff` /
`metric_delta` (e.g. after fixing a template-drift case):

```sql
UPDATE proposals SET config_diff = '{}'::jsonb, metric_delta = NULL
  WHERE study_id = '<study_id>' AND status = 'pending';
```

## Inspecting the parameter_importance JSON

```bash
docker compose exec api psql -U relyloop -c "
  SELECT jsonb_pretty(parameter_importance) FROM digests WHERE study_id = '<study_id>';
"
```

Values sum to ~1.0 (Optuna normalizes). Only continuous params with ≥2
distinct sampled values appear.

## Manually rejecting a proposal

UI lands with `feat_proposals_ui`; until then, use the API directly:

```bash
curl -X POST http://localhost:8000/api/v1/proposals/<proposal_id>/reject \
  -H 'Content-Type: application/json' \
  -d '{"reason": "metric delta too small to justify churn"}'
```

The transition is `pending → rejected`. A second reject returns 409
`INVALID_STATE_TRANSITION`.

## Concurrency model

The worker holds a Postgres advisory lock keyed on
`blake2b("digest:{study_id}")` across the entire LLM-call + persist
transaction (cycle-2 F6). Two concurrent `generate_digest` invocations
for the same study see exactly one acquire the lock; the loser logs
`digest_lock_contention` and returns. The lock is xact-scoped (releases
on commit/rollback), so no `pg_advisory_unlock` is needed.

The lock prefix (`digest:`) keeps the lock space disjoint from
`backend/workers/orchestrator.py:_try_replenish_xact_lock` (which uses
the bare `study_id`), so the orchestrator's replenishment lock and the
digest worker's lock can be held simultaneously on the same study.

## Worker-side error codes (not API-visible)

These appear ONLY in worker logs as `error_code=<CODE>` alongside the
structured `event_type`:

| Code | Meaning | API surfacing |
|---|---|---|
| `OPENAI_NOT_CONFIGURED` | `Settings.openai_api_key` is None | `GET /studies/{id}/digest` returns 404 `DIGEST_NOT_READY` |
| `LLM_PROVIDER_INCAPABLE` | Capability cache miss / model mismatch / structured_output=fail | Capability fallback persists a narrative-only digest; visible via `digest.recommended_config = {}` |
| `UNKNOWN_MODEL_PRICING` | `OPENAI_MODEL` not in `cost_model.known_models()` | `GET /studies/{id}/digest` returns 404 `DIGEST_NOT_READY` |
| `OPENAI_BUDGET_EXCEEDED` | Pre-call peek + estimated_max > `openai_daily_budget_usd` | `GET /studies/{id}/digest` returns 404 `DIGEST_NOT_READY` |
| `INVALID_STUDY_STATE` | Internal — worker received a non-completed study | Defense-in-depth; should never happen since orchestrator only enqueues on `completed` |
