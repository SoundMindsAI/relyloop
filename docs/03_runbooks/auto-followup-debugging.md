# Auto-followup chain debugging runbook

**Feature:** [`feat_auto_followup_studies`](../00_overview/implemented_features/) ·
**Spec:** [feature_spec.md](../00_overview/planned_features/feat_auto_followup_studies/feature_spec.md) ·
**Worker:** [`backend/workers/auto_followup.py`](../../backend/workers/auto_followup.py) ·
**Service:** [`backend/app/services/study_state.py:cancel_study_with_chain_cascade`](../../backend/app/services/study_state.py)

The auto-followup feature chains studies overnight by enqueueing a new study from the digest worker whenever a study completes with `config.auto_followup_depth` set. This runbook is the operator's quick-reference for diagnosing chain behavior via the structlog event catalog.

## Telemetry event catalog (FR-9, 8 events)

Every chain enqueue / skip / cancel branch emits a distinct `event_type` so a single `jq 'select(.event_type == "<name>")'` over `make logs` answers most questions. The chain trigger lives in `backend/workers/digest.py` at the bottom of `generate_digest`; the chain worker is `backend/workers/auto_followup.py`.

| # | Event | Emitted by | When |
|---|---|---|---|
| 1 | `auto_followup_enqueued` | worker (success path) | Child study created + `start_study` enqueued |
| 2 | `auto_followup_skipped_no_lift` | worker (gate) | Winner did not beat first-decile baseline by `epsilon = 0.005` |
| 3 | `auto_followup_skipped_budget` | worker (gate) | Daily LLM peek + max-call estimate would exceed 80% of `OPENAI_DAILY_BUDGET_USD` |
| 4 | `auto_followup_skipped_parent_failed` | worker (defensive) | Parent.status is `failed`/`cancelled` — does not fire in normal flow (digest doesn't run on failed studies; see AC-6) |
| 5 | `auto_followup_skipped_parent_missing` | worker (defensive) | `repo.get_study(parent_id)` returned `None` — hard-delete race; impossible in MVP1 (no hard-delete tooling) |
| 6 | `auto_followup_depth_exhausted` | worker (gate) | `config.auto_followup_depth == 0` (depth-0 leaf's own invocation; the natural chain terminator per D-12) |
| 7 | `auto_followup_enqueued_duplicate_dropped` | worker (layer-2 backstop) | Worker found existing children via `list_children_of_study` and refused to create a second — fires only on Arq `_job_id` dedup miss |
| 8 | `auto_followup_cancelled_with_parent` | cascade service | Direct child got cancelled as part of `cancel_study_with_chain_cascade` |

Plus 3 events added by `feat_overnight_final_solution` Story 2.2 (only emitted under the `auto_followup_strategy = "follow_suggestions"` path — the legacy/missing/`"narrow"` path stays log-quiet):

| Event | Where | When |
|---|---|---|
| `auto_followup_strategy_selected` | worker (post-INSERT) | The worker took a selection-driven path (narrow / widen / swap_template). Fields: `parent_study_id`, `child_study_id`, `strategy: "follow_suggestions"`, `selected_kind`, `source_index`, `candidate_count`, `dropped_template_ids`. The `dropped_template_ids` field carries cycle-guard activity on the same line — a non-empty list with `selected_kind = "narrow"` or `"widen"` means the chain wanted to swap to a visited template but the guard fired. |
| `auto_followup_no_executable_candidate_fell_back_to_narrow` | worker (post-INSERT) | `select_executable_followup` returned no candidate (digest had only `text` items, OR every executable was a swap to a visited template). The chain did NOT stall — fell back to today's narrow path. Frequent firing usually means the digest is text-heavy (typical of `still_improving` / `too_few_trials` parent verdicts); the operator should re-run with a larger trial budget rather than continue chaining. Fields: `parent_study_id`, `child_study_id`, `digest_followup_kinds`, `visited_template_id_count`, `dropped_template_ids`. |
| `auto_followup_swap_target_missing` | worker (pre-fallback WARN) | A `swap_template` follow-up pointed at a template that no longer exists (hard-deleted between digest persist and dispatch). Logged BEFORE the fallback decision so `child_study_id` is NOT populated (the fallback child gets created next). Operator action: investigate why a template was deleted while a chain referenced it. Fields: `parent_study_id`, `swap_target_template_id`. |

Plus 1 auxiliary error event from the same Story 2.2 defensive try/except:

| Event | Where | When |
|---|---|---|
| `auto_followup_strategy_dispatch_error` | worker (pre-fallback WARN) | An unexpected exception fired inside the `follow_suggestions` dispatch block (digest read / parse / select). The chain falls back to the narrow path; reliability does not regress vs the legacy path. Fields: `parent_study_id`, `error` (truncated to 200 chars). |

Plus 4 long-standing auxiliary events (intentionally outside the FR-9 catalog per cycle-1 C1-5 + cycle-2 C2-3 — they're warning paths, not chain-state events):

| Event | Where | When |
|---|---|---|
| `digest_followup_enqueue_pool_missing` | digest trigger | `ctx['arq_pool']` is `None` (test context without lifespan); chain ends here |
| `digest_followup_enqueue_failed` | digest trigger | `arq_pool.enqueue_job` raised; chain ends here, parent's proposal still ships |
| `digest_followup_start_study_enqueue_failed` | worker (post-create) | `arq_pool.enqueue_job('start_study', child.id)` raised; child row exists as `queued`, the `on_startup` boot-sweep at `backend/workers/all.py:138-151` recovers on next worker boot |
| `auto_followup_cancel_terminal_parent` | cascade service | Cascade traversed a `completed`/`cancelled`/`failed` ancestor (typical case: completed parent + running child) |

## Quick diagnostic recipes

### "I started a depth-3 chain — where is it?"

```bash
make logs | jq 'select(.event_type | startswith("auto_followup_"))' | jq -s 'sort_by(.timestamp)'
```

Walk the events. A clean depth-3 chain produces (in order):
1. `auto_followup_enqueued` for the original study → child A
2. `auto_followup_enqueued` for child A → child B
3. `auto_followup_enqueued` for child B → child C
4. `auto_followup_depth_exhausted` for child C (the terminal leaf)

If the chain stopped early, look for the skip event between the last `enqueued` and the missing next link.

### "Why didn't the chain start?"

The digest trigger fires on `auto_followup_depth is not None` AND `study.status == 'completed'`. If the chain didn't start at all:

```bash
make logs | jq 'select(.event_type == "digest_complete" and .study_id == "<id>")'
make logs | jq 'select(.event_type == "auto_followup_enqueued" and .parent_study_id == "<id>")'
```

If `digest_complete` fired but `auto_followup_enqueued` (or any skip event) didn't — the digest worker's trigger condition didn't match. Check `study.config.auto_followup_depth`:

```bash
docker compose exec postgres psql -U relyloop -c \
  "SELECT id, status, config->'auto_followup_depth' FROM studies WHERE id = '<id>';"
```

If it's `null`, the operator didn't opt in. If it's `0`, the chain already terminated (this study was the leaf — by design).

### "Why did the chain skip my last study?"

Match `parent_study_id`:

```bash
make logs | jq 'select(.parent_study_id == "<id>" and (.event_type | startswith("auto_followup_skipped_")))'
```

The skip event's metadata explains the gate:
- `auto_followup_skipped_no_lift` → fields `best_metric`, `first_decile_max`, `epsilon`. Lift was `best_metric - first_decile_max`; gate is `lift > epsilon`.
- `auto_followup_skipped_budget` → fields `peek_total`, `budget`, `threshold_pct`. The 80% threshold trips even before adding the per-call max cost.

### "I cancelled the chain — did it actually stop?"

Cancel cascade emits one event per touched node:

```bash
make logs | jq 'select(.event_type == "auto_followup_cancelled_with_parent" and .parent_study_id == "<id>")'
make logs | jq 'select(.event_type == "auto_followup_cancel_terminal_parent" and (.study_id == "<id>" or .parent_study_id == "<id>"))'
```

Every direct child + every grandchild walked by the cascade emits one of these two events. If you see neither for an in-flight study you expected to be cancelled, the cascade missed it (file a bug — see "Known limitations" below).

### "I want to stop a chain whose root is already `completed`"

**Known limitation** (captured as [`chore_auto_followup_completed_parent_stop_chain_race`](../00_overview/planned_features/chore_auto_followup_completed_parent_stop_chain_race/idea.md)): when a `completed` parent has only one in-flight descendant, navigating to the **completed root** and clicking Cancel won't stop the chain — the cascade traverses only direct children (per D-13), and a completed parent's direct child may itself be completed. **Workaround:** navigate down the chain (via the "Direct children" links on each study's detail page) until you find the study with `status='running'`, then click Cancel there. The cascade from the in-flight node stops the chain at that point.

### "A study completed but no digest fired"

The chain trigger lives inside `generate_digest`, so a missing digest means no chain. Check whether the digest worker is healthy:

```bash
make logs | jq 'select(.event_type == "digest_complete" or .event_type == "digest_failed")' | tail -10
```

If the digest worker is stuck on prior studies, the chain trigger is just waiting — let it catch up. Restart the worker (`docker compose restart worker`) if the Arq queue is hung.

## Schema invariants (worth verifying when debugging anomalies)

- `studies.parent_study_id` is a self-FK with default `ON DELETE NO ACTION` (per D-1). Studies that should be hard-deleted while having children must use the soft-delete path (`deleted_at`) — but MVP1 has no soft-delete on studies; only `hard_delete_study` for test cleanup. Hard-deleting a parent with extant children raises `IntegrityError`.
- `studies.config.auto_followup_depth` allowed range: `None | 0..5` (validator at `backend/app/api/v1/schemas.py:StudyConfigSpec._validate_auto_followup_depth`). Wire-`0` is the worker-internal terminal-state value; the wizard never sends it (uses `undefined` = "Off"). Per FR-1 + D-12.

## Manual mitigation: forcibly stop a runaway chain

If the operator notices an unintended chain (e.g., a mis-set depth=5), and the in-flight descendant isn't reachable through the UI walk (because the in-flight node is N hops deep):

1. Find the in-flight node:
   ```bash
   docker compose exec postgres psql -U relyloop -c \
     "SELECT id, name, status, parent_study_id, config->'auto_followup_depth' AS depth
      FROM studies WHERE name LIKE '<original-name>%' AND status IN ('queued', 'running');"
   ```
2. POST cancel directly:
   ```bash
   curl -X POST 'http://127.0.0.1:8000/api/v1/studies/<in-flight-id>/cancel?cascade=true'
   ```
   The `cascade=true` (default) ensures any pending grandchildren also get cancelled.

3. Verify no new child rows appear within 30s:
   ```bash
   docker compose exec postgres psql -U relyloop -c \
     "SELECT id, status, created_at FROM studies WHERE parent_study_id = '<in-flight-id>' ORDER BY created_at DESC;"
   ```
