# Feature Specification — Orchestrator zero-metric streak abort

**Date:** 2026-05-22
**Status:** Draft
**Owners:** Product/Engineering: soundminds.ai (single-developer + GPT-5.5 cross-model reviewer)
**Related docs:**
- [`idea.md`](idea.md) — origin brief (Tier 3 fail-fast, defense-in-depth)
- [`pipeline_status.md`](pipeline_status.md) — stage tracking
- [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) — surface being extended
- Tier 1 sibling (shipped): [`feat_study_target_judgment_mismatch_guard`](../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md)
- Tier 2 sibling (planned): [`feat_study_preflight_overlap_probe/idea.md`](../feat_study_preflight_overlap_probe/idea.md)
- Pattern precedent: existing `_last_n_all_failed` guard at `backend/workers/orchestrator.py:188-210`

---

## 1) Purpose

- **Problem.** Even with the Tier 1 create-time judgment mismatch guard (`feat_study_target_judgment_mismatch_guard`, PR #184, 2026-05-21) and the still-planned Tier 2 preflight overlap probe (`feat_study_preflight_overlap_probe`), a study can still burn its full trial budget on no-signal runs whenever the failure becomes observable only mid-flight: a `DELETE` against the target index after the study starts, an auth credential silently expiring and the adapter falling back to anonymous, a template body that becomes a zero-result query at a specific param value Optuna keeps sampling, or a preflight probe that ran before the index degraded. In each case trials complete with `status='complete'` but `primary_metric == 0.0`, the existing `_last_n_all_failed` guard does NOT fire (no `failed` status — the score is 0, not an exception), and the operator returns to 1000 zero-metric trials and has to start over.
- **Outcome.** The orchestrator aborts the study after **20 consecutive `status='complete'` trials with `primary_metric == 0.0`**, terminating it as `failed` with `failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"`. Wasted budget capped at 20 trials; the existing `failed`-status UI surface (`StudyHeader` failed-reason renderer) carries the explanation to the operator with no frontend change required.
- **Non-goal.** This feature is NOT a replacement for the Tier 1 / Tier 2 create-time guards. Those guards are deterministic and free; this guard costs N trials of wasted budget before triggering and only catches what slipped past them. The "Tier 1 → Tier 2 → Tier 3" framing is a **product-sequencing preference** (which guard delivers the most value first), NOT a code-level prerequisite or release gate for this PR. Tier 1 (`feat_study_target_judgment_mismatch_guard`) is already shipped (PR #184, 2026-05-21). Tier 2 (`feat_study_preflight_overlap_probe`) is planned but **does NOT need to ship before this feature merges** — the three guards compose at runtime without coupling at the code level. See §5 for the formal dependency classification.

## 2) Current state audit

### Existing implementations

| File/component | What it does | Notes |
|---|---|---|
| [`backend/workers/orchestrator.py:188-210`](../../../../backend/workers/orchestrator.py) | Existing `_last_n_all_failed` check: aborts study as `failed` after 5 consecutive `status='failed'` trials, calls `study_state.fail_study(...,failed_reason="5 consecutive trial failures")` then exits the loop. Emits structlog `event_type="stop_condition_fired", reason="consecutive_failures"`. | The pattern precedent. The new check sits adjacent to this block, runs on the same tick, uses the same exit mechanic. |
| [`backend/workers/orchestrator.py:268-284`](../../../../backend/workers/orchestrator.py) (`_last_n_all_failed`) | Selects the most recent `n` trial statuses by `optuna_trial_number DESC`; returns True iff all `n` are `'failed'` (and at least `n` exist). | New `_last_n_all_zero` helper mirrors this exactly — same query shape, same insufficient-data semantics (return False when fewer than `n` terminal trials exist). The SQL `WHERE` clause selects on `study_id` ONLY (no status/metric filter in SQL); the helper then evaluates the predicate `status == 'complete' AND primary_metric IS NOT NULL AND primary_metric == 0.0` on each of the limited `n` rows in Python. (Pre-filtering by status/metric in SQL before `LIMIT` would change the semantics from "last `n` trials are zero" to "last `n` zero trials exist anywhere in the table" — a non-zero / failed / NULL row inside the recent window would be skipped, producing false-positive aborts. The Python-side predicate evaluation is what guarantees the boundary cases hold.) |
| [`backend/workers/orchestrator.py:69`](../../../../backend/workers/orchestrator.py) (`_CONSECUTIVE_FAILURE_THRESHOLD = 5`) | Module-level constant for the existing failure-streak guard. Not a `Settings` field. | The new `_ZERO_STREAK_THRESHOLD = 20` constant lives adjacent to it, with the same scope and rationale. |
| [`backend/app/services/study_state.py:233-256`](../../../../backend/app/services/study_state.py) (`fail_study`) | Service-layer `running → failed` transition; sets `failed_reason` + `completed_at`. Logs `event_type="study_state_transition", to_status="failed"`. Raises `InvalidStateTransition` on cancel-race. | Reused verbatim with the new `failed_reason` string. No service-layer changes. |
| [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py) (`aggregate_trials_summary`) | Already polled by the orchestrator each tick to compute `complete/failed/pruned/terminal` counts + winner. No `primary_metric` zero-tally — the new helper needs its own query. | Re-used for tick context; the new `_last_n_all_zero` is an independent query. |
| [`ui/src/components/studies/study-header.tsx:85-90`](../../../../ui/src/components/studies/study-header.tsx) (`StudyHeader`) | Renders `study.failed_reason` in the destructive-text "Failed reason" row of the header when present. Shape-agnostic — any string the orchestrator writes is displayed verbatim. | Carries the new "no signal: …" string with zero frontend code change. |
| [`backend/app/db/models/study.py:67-69`](../../../../backend/app/db/models/study.py) (`status`, `failed_reason` columns) | `status` CHECK enforces `{queued, running, completed, cancelled, failed}`; `failed_reason: Text \| nullable`. | The terminal `failed` state and `failed_reason` string field are already the canonical surface. No migration needed. |
| [`backend/app/db/models/trial.py:74-94`](../../../../backend/app/db/models/trial.py) (`Trial.primary_metric`, `Trial.status`) | `primary_metric: Float \| nullable`; `status` CHECK enforces `{complete, failed, pruned}`. Denormalized index `trials_study_metric` on `(study_id, primary_metric DESC NULLS LAST)`. | The new helper's **SQL WHERE clause filters on `study_id` ONLY**. After the `ORDER BY optuna_trial_number DESC LIMIT n` returns the recent-`n` window, the helper evaluates the predicate `row.status == 'complete' AND row.primary_metric is not None AND row.primary_metric == 0.0` in Python — guarding against `NULL` primary_metric paths (e.g., adapter completed but scorer wrote NULL) without pre-filtering them out of the window. |

### Navigation and link impact

None. The feature ships no new UI route, no new API endpoint, and no new linkable artifact. The new `failed_reason` string surfaces through the existing study-detail page.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/integration/test_study_lifecycle.py:218-251`](../../../../backend/tests/integration/test_study_lifecycle.py) | `test_ac5_five_consecutive_failures_fail_the_study` — drives `start_study` with a stub adapter that raises `ClusterUnreachableError` on every call, asserts the existing AC-5 failure-streak abort. | 1 | No change — this is the sibling failure-streak test. The new integration tests in this feature live alongside it as `test_zero_streak_*` and reuse the same `seed_study` / `_running_orchestrator` / `_wait_for_status` helpers. |
| Orchestrator's `event_type="stop_condition_fired"` log assertions (if any) | structlog assertions in `backend/tests/integration/test_study_lifecycle.py` happy-path tests | 0 (no existing assertion of the `reason=` taxonomy) | None. The new path emits `reason="no_signal"` as a new taxonomy value alongside `consecutive_failures` / `max_trials_reached` / `time_budget_exceeded` (already in `_stop`). |

### Existing behaviors affected by scope change

- **Orchestrator tick loop ordering.** Current order at `orchestrator.py:182-220`: (1) consecutive-failure check (`_last_n_all_failed`), (2) stop conditions (`max_trials_reached`, `time_budget_exceeded`). New: insert the zero-streak check between (1) and (2), in that order. Current: Existing failure-streak fires first; max_trials second. New: failure-streak first; zero-streak second; max_trials/time_budget third. Decision needed: **No** — ordering is locked (see §19 decision log).

- **`stop_reason` / `reason=` taxonomy.** Current values in structlog `event_type="stop_condition_fired"` payloads: `"consecutive_failures"`, `"max_trials_reached"`, `"time_budget_exceeded"`. New: adds `"no_signal"` as a fourth value. Decision needed: **No** — extending a structlog tag taxonomy is additive; no other consumer.

- **Cancel-race tolerance.** Current (precedent at [`orchestrator.py:202-209`](../../../../backend/workers/orchestrator.py)): the `_last_n_all_failed` block wraps `study_state.fail_study` in `try/except InvalidStateTransition`, rolls back, **logs `event_type="orchestrator_race_lost"` at INFO**, and exits the loop. New: identical handling for the zero-streak path, with `attempted_reason="no_signal"` in the log payload to distinguish it from the failure-streak race log. Decision needed: **No** — mirrors precedent exactly.

---

## 3) Scope

### In scope

- New module constant `_ZERO_STREAK_THRESHOLD: int = 20` in `backend/workers/orchestrator.py`, adjacent to `_CONSECUTIVE_FAILURE_THRESHOLD`.
- New helper `async def _last_n_all_zero(db: AsyncSession, study_id: str, *, n: int) -> bool` in `backend/workers/orchestrator.py`, alongside `_last_n_all_failed`. The helper SELECTs `(status, primary_metric)` rows `WHERE study_id = :study_id ORDER BY optuna_trial_number DESC LIMIT :n` (no status/metric predicate in the SQL), then in Python returns True iff `len(rows) == n AND all(row.status == 'complete' AND row.primary_metric is not None AND row.primary_metric == 0.0 for row in rows)`. Returns False when fewer than `n` rows exist or any row in the recent-`n` window fails the predicate (insufficient signal — a single non-zero, failed, pruned, or NULL-metric row resets the streak; this mirrors `_last_n_all_failed`'s contract).
- New zero-streak abort block in `start_study`'s polling loop, immediately AFTER the existing `_last_n_all_failed` block (which itself runs before the `max_trials` / `time_budget_min` checks per the comment at `orchestrator.py:182-187`). The new block calls `study_state.fail_study(db, study_id, failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study")`, commits, logs structlog `event_type="stop_condition_fired", reason="no_signal"` at WARNING, and returns from the loop. On `study_state.InvalidStateTransition` (cancel-race), the block rolls back, logs structlog `event_type="orchestrator_race_lost", study_id, attempted_reason="no_signal"` at INFO, and returns from the loop — matching the existing failure-streak cancel-race path at [`orchestrator.py:202-209`](../../../../backend/workers/orchestrator.py) verbatim except for the `attempted_reason` payload value.
- Three integration tests in `backend/tests/integration/test_study_lifecycle.py` covering: 20-streak fires + correct `failed_reason`; non-zero outlier inside the recent-20 window does not fire (boundary); interleaved failures + zeros do not fire (the failure-streak guard counts separately, the zero-streak guard counts separately, and neither reaches its own threshold).
- Three additional integration tests covering: helper boundary semantics (FR-1 + FR-5 SQL/order/LIMIT/NULL matrix); AC-5 precedence (failure-streak block runs before zero-streak block — asserted via monkeypatched helpers + a spy); AC-4 cancel-race (`InvalidStateTransition` from `fail_study` exits the loop cleanly with the `orchestrator_race_lost` INFO log). Total: 6 new integration tests in `backend/tests/integration/test_study_lifecycle.py`.

### Out of scope

- `Settings`-level configurability of the threshold. Locked at the module-level constant pattern (see §19 decision log "20-trial threshold" and "module-level constant"). Operator-tunable knobs are reserved for surfaces operators actually tune at deploy time (`openai_daily_budget_usd`, base URLs, etc.); orchestrator thresholds are project-internal tuning.
- A new error code in `docs/01_architecture/api-conventions.md`. There is no API surface change — `failed_reason` is a string column already documented; no new HTTP error envelope is emitted. (See §3 "API convention check" + §7.5 below.)
- A migration. No schema change. The `status='failed' + failed_reason='no signal: …'` shape uses existing columns.
- A frontend code change. The existing `StudyHeader` renderer (`ui/src/components/studies/study-header.tsx:85-90`) displays any string the orchestrator writes verbatim. Tooltip / FAQ surfacing of "no signal" is deferred to `chore_guides_faq` when that ships.
- Telemetry beyond structlog. MVP1 has no `audit_log` (lands at MVP2 per `docs/01_architecture/data-model.md`); we don't add structured metrics emission here.
- Tier 1 / Tier 2 create-time guards. Tier 1 shipped 2026-05-21 (PR #184); Tier 2 is `feat_study_preflight_overlap_probe` (planned, separate spec).

### API convention check

This feature adds NO HTTP endpoint and NO new error envelope.

- **Endpoint prefix convention:** N/A — no endpoint touched.
- **Router namespace:** N/A — change is confined to `backend/workers/orchestrator.py` + `backend/tests/integration/test_study_lifecycle.py`.
- **HTTP methods:** N/A.
- **Non-auth error envelope shape:** N/A — the operator-facing surface is the `Study.failed_reason` string column, already shipped as part of `feat_study_lifecycle`. The wire shape on `GET /api/v1/studies/{id}` is unchanged: `failed_reason` continues to be a `string | null` field on `StudyDetail`. No `error_code` is allocated.
- **Auth error shape:** N/A.

This passes the §3 check because the contract is invariant — only the value the orchestrator writes into an existing field changes.

### Phase boundaries

**Phase 1 (this spec):** all in-scope work above. There is no Phase 2 — the feature ships in one phase. The tier-3 framing in the idea refers to the position behind Tier 1 / Tier 2 create-time guards (which are separate features), not phases within this feature.

## 4) Product principles and constraints

- **Defense in depth, not replacement.** This guard is the third tier behind Tier 1 (create-time mismatch reject) and Tier 2 (preflight overlap probe). It costs 20 trials of wasted budget before triggering; it must not push the front-line checks into being skipped or weakened.
- **Mirror precedent.** The existing 5-consecutive-failures pattern is the architectural template. New constant alongside the old; new helper alongside the old; new block in the same loop position as the old; same cancel-race handling.
- **No new wire contract.** The operator surface is the existing `failed_reason` string. Frontend renders it verbatim. No new error code, no new column, no new endpoint.
- **No new operator-tunable knob.** The threshold is a project-internal tuning constant, not a deploy-time setting.
- **Idempotency-safe.** A second `start_study` invocation on an already-`failed` study trips `InvalidStateTransition` on the queued→running entry transition and exits cleanly (existing behavior at `orchestrator.py:115-124`). The new block doesn't change this.

### Anti-patterns

- **Do not** make the threshold a `Settings` field — the precedent (`_CONSECUTIVE_FAILURE_THRESHOLD`) is a module-level constant for a reason (project-internal tuning surface, not operator knob). Mixing the two creates a precedent question on every future tuning constant.
- **Do not** allocate a new `error_code` value (e.g., `STUDY_NO_SIGNAL`) in `docs/01_architecture/api-conventions.md`. There is no HTTP failure being emitted — the operator surface is the existing `failed_reason` string column. Allocating an error code that never appears in any 4xx/5xx envelope creates spec / runbook clutter.
- **Do not** count `failed` or `pruned` trials toward the zero-streak. The helper's predicate (evaluated in Python after the SQL `LIMIT n`, NOT in the SQL `WHERE` clause) MUST be `row.status == 'complete' AND row.primary_metric is not None AND row.primary_metric == 0.0`. A `failed` trial is already caught by `_last_n_all_failed` (with its own threshold of 5); counting it here would either double-count toward both guards (inflating false positives) or mask the failure-streak guard's earlier fire. Equally important: **do NOT pre-filter to `status='complete'` rows in SQL** — that would change the semantics from "last n trials are zero" to "last n complete-zero trials exist", skipping any failed/pruned trial inside the recent window and producing false positives.
- **Do not** include `primary_metric IS NULL` rows in the zero-streak count. A NULL metric belongs to a `failed` or `pruned` trial (or to a hypothetical scorer-write race) — the failure-streak guard is the right tool. Explicitly require `primary_metric IS NOT NULL` in the Python predicate.
- **Do not** insert the new zero-streak block BEFORE `_last_n_all_failed`. If failure-streak and zero-streak both reach threshold in the same tick (a 20-trial run where the last 5 happen to be `failed` and the first 15 were `complete` with `primary_metric=0.0` — possible if the cluster degraded partway through), the failure-streak abort is the more specific and earlier-defined diagnosis. Maintain the precedence: failure-streak first, then zero-streak, then max_trials / time_budget.
- **Do not** add a frontend code path keyed on the substring `"no signal:"`. The frontend treats `failed_reason` as an opaque display string; coupling UI behavior to the orchestrator's exact wording is a fragile contract. The "FAQ link from a no-signal banner" idea belongs in `chore_guides_faq`, not here.
- **Do not** emit the abort INSIDE the `_try_replenish_xact_lock` block. The check belongs in the cancel-detect / aggregate-summary section (the same place `_last_n_all_failed` runs), using its own short-lived session — not inside the replenish-lock-protected critical section.

## 5) Assumptions and dependencies

- **Depends on (composes with):** `feat_study_lifecycle` Phase 2 orchestrator + `services.study_state.fail_study`. Status: **implemented and shipped** (PR #25, 2026-05-11).
- **Depends on (composes with):** the existing `_last_n_all_failed` block being the immediate precedent. Status: **implemented and shipped**.
- **Does NOT depend on:** Tier 1 (`feat_study_target_judgment_mismatch_guard`, shipped PR #184) or Tier 2 (`feat_study_preflight_overlap_probe`, planned). The three tiers compose — each catches a different class — but none is a prerequisite for the others at the code level. Tier 1 reduces the false-positive surface this guard might trip on, but cannot eliminate the mid-flight cases this guard is designed for.
- **Does NOT depend on:** `chore_study_default_stop_conditions` (proposed server-side defaults for `max_trials` / `time_budget_min`). If that chore lands, this guard's framing (20 trials caps 20% of a 100-trial floor) aligns more cleanly; if it doesn't, the threshold itself is unchanged.
- **Does NOT depend on:** `chore_guides_faq` (planned). A future FAQ entry titled "My study failed with `failed_reason='no signal: …'`" is a natural surface but ships independently.
- **Risk if missing:** The Tier 1 / Tier 2 guards do most of the work; without them, this guard catches the remaining mid-flight cases but burns 20 trials per false detection. With Tier 1 shipped, the false-positive surface is small (operator deletes index / template breaks at edge param / auth degrades mid-flight).

## 6) Actors and roles

- Primary actor: **operator** (relevance engineer running studies on the local stack). Observes the abort via the existing `Study.status='failed'` + `failed_reason` surface in `GET /api/v1/studies/{id}` and `StudyHeader`.
- Role model: N/A — single-tenant install, no auth surface (MVP1 per `docs/01_architecture/tech-stack.md`).
- Permission boundaries: N/A — the change is internal to the orchestrator worker; no API surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2 (`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"). For MVP1, the abort produces structlog records:
- `event_type="stop_condition_fired", reason="no_signal", study_id=<id>` at **WARNING** level, emitted by the new orchestrator block immediately before the loop return. Matches the existing precedent at [`backend/workers/orchestrator.py:196-201`](../../../../backend/workers/orchestrator.py) where the failure-streak guard emits `event_type="stop_condition_fired", reason="consecutive_failures"` via `logger.warning(...)`.
- `event_type="study_state_transition", from_status="running", to_status="failed", failed_reason="no signal: …", study_id=<id>` at **WARNING** level, emitted by `study_state.fail_study` per existing behavior at [`backend/app/services/study_state.py:248-255`](../../../../backend/app/services/study_state.py).
- On cancel-race (FR-3): `event_type="orchestrator_race_lost", study_id=<id>, attempted_reason="no_signal"` at **INFO** level, matching the failure-streak precedent at [`backend/workers/orchestrator.py:202-209`](../../../../backend/workers/orchestrator.py).

## 7) Functional requirements

### FR-1: Zero-metric streak detection helper

- Requirement:
  - The system **MUST** provide an async function `_last_n_all_zero(db: AsyncSession, study_id: str, *, n: int) -> bool` in `backend/workers/orchestrator.py`.
  - The function **MUST** select `(status, primary_metric)` from the `trials` table for the given `study_id`, ordered by `optuna_trial_number DESC`, limited to `n` rows.
  - The function **MUST** return `True` if and only if the result set contains exactly `n` rows AND every row satisfies `status == 'complete' AND primary_metric IS NOT NULL AND primary_metric == 0.0`. (Mirrors `_last_n_all_failed`'s insufficient-data semantics: fewer than `n` terminal trials → False.)
  - The function **MUST NOT** count trials with `status IN ('failed', 'pruned')` toward the streak.
  - The function **MUST NOT** count trials where `primary_metric IS NULL` toward the streak.
- Notes: equality on `Float` is correct here because `primary_metric == 0.0` is the exact value emitted by `backend.app.eval.scoring.score()` when every (query, doc) pair has zero overlap with the qrels — no floating-point near-zero noise to defend against. (NDCG, MAP, MRR, precision, recall are all bounded `[0, 1]` and degenerate to exactly 0.0 on empty qrels-intersected runs.)

### FR-2: Module-level threshold constant

- Requirement:
  - The system **MUST** define a module-level integer constant `_ZERO_STREAK_THRESHOLD = 20` in `backend/workers/orchestrator.py`, adjacent to `_CONSECUTIVE_FAILURE_THRESHOLD = 5`.
  - The constant **MUST NOT** be sourced from `Settings`, env vars, `study.config`, or any per-deploy override.
  - The constant **MUST** carry an inline docstring referencing this spec's FR-2 + the threshold rationale below.
- Notes: precedent set by `_CONSECUTIVE_FAILURE_THRESHOLD` (`orchestrator.py:69-73`).

### FR-3: Mid-flight abort in the polling loop

- Requirement:
  - The orchestrator's `start_study` polling loop **MUST** check `_last_n_all_zero(db, study_id, n=_ZERO_STREAK_THRESHOLD)` on every tick, AFTER the existing `_last_n_all_failed` check and BEFORE the `max_trials` / `time_budget_min` checks. (Loop position: in the same `async with session_factory() as db:` block that already houses `_last_n_all_failed`, immediately after the failure-streak `return`.)
  - On True, the orchestrator **MUST** call `study_state.fail_study(db, study_id, failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study")`, commit, log `event_type="stop_condition_fired", reason="no_signal"` at WARNING level, and `return` from the loop.
  - On `study_state.InvalidStateTransition` (cancel-race), the orchestrator **MUST** `db.rollback()`, log `event_type="orchestrator_race_lost", study_id, attempted_reason="no_signal"` at INFO, and `return` from the loop. (Same handling as `_last_n_all_failed`.)
- Notes: the `failed_reason` string is exact and stable — operators can grep for it; future FAQ links can quote it.

### FR-4: Failure-streak precedence preserved

- Requirement:
  - The orchestrator **MUST** evaluate `_last_n_all_failed` BEFORE `_last_n_all_zero`. If both would fire on the same tick, the failure-streak abort wins (`failed_reason="5 consecutive trial failures"`, `reason="consecutive_failures"`).
- Notes: this preserves the existing AC-5 behavior of `feat_study_lifecycle` and prevents the new guard from masking the more specific diagnosis (real adapter failures emitting `status='failed'`).

### FR-5: No-op when fewer than 20 trials have terminated

- Requirement:
  - When the count of terminal trials (`status IN ('complete','failed','pruned')`) is `< _ZERO_STREAK_THRESHOLD`, the new abort path **MUST NOT** fire, regardless of how many of the existing terminal trials are zero-metric.
  - When the most recent `_ZERO_STREAK_THRESHOLD` terminal trials include even one row with `status='complete' AND primary_metric > 0.0`, the abort path **MUST NOT** fire.
  - When the most recent `_ZERO_STREAK_THRESHOLD` terminal trials include even one row with `status='complete' AND primary_metric IS NULL`, the abort path **MUST NOT** fire (NULL is not "zero" — it's a missing metric and belongs to the failure-streak surface).
- Notes: enforced by the helper's **Python-side predicate** (`row.status == 'complete' AND row.primary_metric is not None AND row.primary_metric == 0.0`) evaluated on the SQL-ordered + LIMITed recent-`n` window. The SQL WHERE clause filters on `study_id` ONLY — see FR-1. The required helper-boundary integration tests in §14 cover the fewer-than-`n`, NULL, failed, and non-zero cases.

## 8) API and data contract baseline

### 8.1 Endpoint surface

None added. The behavioral change surfaces via existing endpoints:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}` | Returns the study row with `status="failed"` + `failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"` after the abort fires. | Existing `STUDY_NOT_FOUND` (404). No new code. |
| `GET` | `/api/v1/studies` | Lists the aborted study with `status="failed"` matched by the existing `?status=failed` filter. | Existing. No new code. |

### 8.2 Contract rules

- The existing `Study.failed_reason` field is a free-form string. The orchestrator commits to writing the exact string `"no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"` on this abort path; tests assert byte-equality so the string is stable.
- No new `error_code` is allocated. (See §7.5.)
- The `failed_reason` string is treated as an opaque display value by the frontend (existing `StudyHeader` behavior). Spec promises the exact string but anti-pattern §4 forbids the frontend from branching on its substring.

### 8.3 Response examples

GET `/api/v1/studies/{id}` after a zero-streak abort fires (only the fields whose values are directly affected by this feature are shown; the remaining `StudyDetail` fields keep their pre-existing shape from `feat_study_lifecycle`):

```json
{
  "id": "01999999-9999-7999-9999-999999999999",
  "name": "rerank-tuning-2026-05-21",
  "status": "failed",
  "failed_reason": "no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study",
  "completed_at": "2026-05-22T14:23:11.412+00:00",
  "best_metric": null,
  "best_trial_id": null
}
```

(Additional unchanged `StudyDetail` fields — `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `search_space`, `objective`, `config`, `optuna_study_name`, `parent_study_id`, `baseline_metric`, `created_at`, `started_at`, `confidence` — keep their existing shapes per `docs/01_architecture/data-model.md` §"studies" + `feat_pr_metric_confidence` spec.)

Failure example (no new shape — same `STUDY_NOT_FOUND` envelope from `docs/01_architecture/api-conventions.md` standard codes):

```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01999999-9999-7999-9999-999999999999 not found",
    "retryable": false
  }
}
```

Auth failure example: N/A — MVP1 has no auth.

### 8.4 Enumerated value contracts

This feature touches one enumerated surface — the `Study.status` CHECK allowlist — without adding a new value.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `Study.status` | `queued`, `running`, `completed`, `cancelled`, `failed` | `backend/app/db/models/study.py` — `Study.status` column declaration + the `studies_status_check` CHECK constraint in `__table_args__` (same model file referenced by §2 Current state audit) + the Pydantic `StudyStatus` literal in `backend/app/api/v1/schemas.py` | `ui/src/components/studies/study-header.tsx:24` (`failed: 'study.status.failed'`) — used in the existing failed-state badge. |

The abort path uses the existing `failed` value. The `reason="no_signal"` structlog token is NOT a wire enum — it's an internal log taxonomy, not a value any client validates against an allowlist.

### 8.5 Error code catalog

None. No new HTTP error code is allocated. (Repeated from §3 / §4 anti-pattern for emphasis.)

## 9) Data model and state transitions

### New/changed entities

None. No migration. The change writes pre-existing columns:
- `studies.status` — transitions to `'failed'` via the existing `study_state.fail_study` service.
- `studies.failed_reason` — populated with the new exact string.
- `studies.completed_at` — set by `study_state.fail_study` per its existing behavior.

### Required invariants

- After the abort fires, `studies.status='failed' AND studies.failed_reason='no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study'`.
- The count of trial rows where `study_id = <aborted study> AND status='complete' AND primary_metric = 0.0` is `≥ _ZERO_STREAK_THRESHOLD` at the moment of abort. (The orchestrator may continue to enqueue trials between the abort decision and the loop exit IF the tick interleaves a replenishment block — but per the loop order at `orchestrator.py:222-249`, replenishment runs AFTER the cancel/abort checks; once `_last_n_all_zero` is True and `fail_study` commits, the loop returns and no further replenishment happens on the current orchestrator instance.)
- `_last_n_all_failed` precedence: in any tick where both `_last_n_all_failed` and `_last_n_all_zero` would return True, the abort that fires is the failure-streak (`failed_reason="5 consecutive trial failures"`).

### State transitions

- `studies.status`: `running → failed` via `study_state.fail_study`. No new transition; the existing one is reused.
- Cancel race: if the operator cancels between the polling-loop status read and the `fail_study` call, the service raises `InvalidStateTransition`; the orchestrator rolls back, logs `orchestrator_race_lost`, and exits. (Mirrors the existing pattern at `orchestrator.py:202-210`.)

### Idempotency/replay behavior

The polling loop only enters the new check when the study is observed as `status='running'` on the current tick (existing gate at `orchestrator.py:165-176`). A retried `start_study` job on an already-`failed` study returns at the entry-transition check (`orchestrator.py:111-124`) without entering the loop.

## 10) Security, privacy, and compliance

- **Threats.**
  - T1: A misconfigured study could mask a real adapter failure by tripping the zero-streak abort first. Mitigated by FR-4 precedence (failure-streak fires first).
  - T2: The `failed_reason` string could leak operationally sensitive context. Mitigated by writing only a generic string ("judgment overlap likely lost mid-study") — no doc IDs, no query text, no cluster URL, no auth context.
  - T3: A noisy/false abort could be triggered by a study legitimately exploring a search space where many param combinations score 0.0 in early TPE warm-up. Mitigated by the 20-trial threshold (TPE warm-up default is 10 random + 10 informed per `TPESampler` defaults — the spec FR-3 default sampler — so a 20-streak covers BOTH classes; if both score 0.0 the search space genuinely can't produce signal).
- **Controls.** No new auth/RBAC surface. No new secret. No new external network call.
- **Secrets/key handling.** N/A — change is in-process.
- **Auditability.** Two structlog records (see §6 Audit events). Operators can grep `event_type=stop_condition_fired AND reason=no_signal` for occurrences.
- **Data retention/deletion/export impact.** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** None added. The new failure mode surfaces via the existing `/studies/[id]` page's `StudyHeader` "Failed reason" row.
- **Labeling taxonomy:** the `failed_reason` string is the only operator-facing label, rendered verbatim by `StudyHeader` (`ui/src/components/studies/study-header.tsx:85-90`). The string is engineered to be self-explanatory.
- **Content hierarchy:** unchanged. The existing `Failed reason` `<dd>` row in the header is the primary surface; the status badge ("Failed") and "Completed" timestamp are the secondary cues.
- **Progressive disclosure:** none added.
- **Relationship to existing pages:** purely additive on the existing study-detail page. No replacement, no extension of layout. No new tab, no new modal.

### Tooltips and contextual help

This feature ships no new tooltips. The existing `StudyHeader` failed-reason row uses no tooltip today; introducing one is out of scope (deferred to `chore_guides_faq` per idea §"Surface alignment").

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| (none) | — | — | — |

### Primary flows

1. **Operator starts a study with stale judgment data.** Operator hits `POST /api/v1/studies` with a judgment-list whose target index has lost the documents that were judged (e.g., index recreated mid-week). Tier 1 mismatch guard passes (the judgment-list's `cluster_id` + `target` still match). Tier 2 preflight (if shipped) probes the live index and either fails fast or passes if doc IDs haven't fully diverged yet. Orchestrator dispatches; first 20 `run_trial` jobs return `status='complete' AND primary_metric=0.0` because the (qrels ∩ search-results) intersection is empty for every trial. On tick 20 (or shortly after — the orchestrator's tick cadence is `_REPLENISH_TICK_S=1s` and the orchestrator polls), `_last_n_all_zero` returns True, `fail_study` is called, `failed_reason="no signal: …"` is committed, study transitions to `failed`. Operator opens `/studies/{id}` and sees the failed-reason row.

2. **Operator runs a legitimate study, search space yields slow-start exploration.** TPE warm-up phase samples 10 random points (Optuna default). Several early trials score `> 0.0` (real signal); the zero-streak guard never reaches 20. Study runs to `max_trials` and completes normally. No false positive.

### Edge/error flows

- **Streak is broken by a single non-zero trial.** A run of 19 zero-metric trials followed by a `primary_metric=0.05` trial resets the streak. The next 20 trials are evaluated independently. (Covered by integration test `test_zero_streak_19_then_nonzero_does_not_fire`.)
- **Streak is broken by a single `failed` trial.** A run of 18 zero-metric trials, one `failed` trial, one more zero-metric trial → `_last_n_all_zero` looks at the most recent 20: includes the 1 `failed` (skipped — fails the `status='complete'` predicate), so the function returns False. Meanwhile `_last_n_all_failed` looks at the most recent 5: that 1 `failed` is followed by zero-metric `complete` rows, so its streak isn't satisfied either. Neither guard fires. (Covered by `test_zero_streak_interleaved_failures_does_not_fire`.)
- **Operator cancels mid-abort.** `study_state.fail_study` raises `InvalidStateTransition` because the operator's `cancel_study` call transitioned `running → cancelled` first. Rollback, log `orchestrator_race_lost`, exit. Study ends in `cancelled` state. (Same handling as the existing `_last_n_all_failed` cancel-race path.)
- **Trial 0 was a non-zero outlier, trials 1–20 all zero.** First 20 trials, looking at recent 20 = trials 1–20 (since the helper orders `optuna_trial_number DESC` and limits to 20, the helper sees trials 20 → 1, all zero). Returns True. Abort fires. The non-zero trial 0 is outside the window and irrelevant. (This is correct: the operator cares whether the CURRENT search-space exploration is producing signal, not whether one early trial got lucky.)
- **`primary_metric IS NULL` on one of the recent 20 trials.** A trial where the scorer wrote `NULL` (e.g., the scorer raised before computing the metric, but the worker still committed a row — this is unusual but representable). The helper's `primary_metric IS NOT NULL` predicate excludes it; the helper returns False (insufficient pure-zero rows). No false positive. (Covered indirectly by reviewing the helper's SQL in `test_last_n_all_zero_unit`.)
- **Atomic completion race.** `_stop` (the completion path at `orchestrator.py:304-379`) commits study + pending proposal atomically. If the orchestrator decides on this same tick that the study should also abort via zero-streak, the precedence is: `_last_n_all_zero` fires BEFORE the `max_trials_reached` / `time_budget_exceeded` checks → `_stop` doesn't run that tick → `fail_study` runs instead → study terminates as `failed`, no proposal row written. Consistent with `feat_pr_metric_confidence`'s FR-7 graceful-degradation contract for the proposal panel (the `ConfidencePanel` and proposal-list filters already handle `status='failed'` cases without a proposal row).

## 12) Given/When/Then acceptance criteria

### AC-1: Zero-streak abort fires on exactly 20 zero-metric complete trials

- Given a study seeded via `seed_study(max_trials=30, parallelism=1)` whose stub adapter returns hits that score `primary_metric=0.0` against the qrels for every trial
- And the orchestrator is started against this study
- When 20 consecutive `status='complete'` trials with `primary_metric=0.0` have been written
- Then the study transitions to `status='failed'` with `failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"`
- And the `summary.complete >= 20 AND summary.failed == 0 AND summary.pruned == 0` (no orphan failures or prunes)
- Example values:
  - Input: stub adapter where `build_hits_response` returns docs that have zero qrels overlap (e.g., the stub returns doc IDs `["miss-1","miss-2","miss-3"]` while the qrels reference `d1`/`d2`/`d3`)
  - Expected: `study.status='failed' AND study.failed_reason` matches the exact string above (byte equality assertion)

### AC-2: A single non-zero trial inside the most-recent-20 window keeps the study alive (boundary)

- Given a study seeded via `seed_study(max_trials=30, parallelism=1)` whose stub adapter returns a **non-zero** scoring response for one trial at adapter-invocation #10 (the 11th `search_batch` call, 0-indexed → `optuna_trial_number=10`) and a **zero** scoring response for every other call
- And the orchestrator is started and observed at the snapshot when exactly 20 trials have terminated
- When the helper is evaluated at that snapshot — `_last_n_all_zero(db, study_id, n=20)` covers `optuna_trial_number=0..19`, which includes the non-zero outlier at `optuna_trial_number=10`
- Then `_last_n_all_zero` returns False
- And the study **remains `status='running'`** at the snapshot (max_trials=30 is not yet reached, no other guard qualifies)
- And the study terminates via the existing `max_trials_reached` stop condition (NOT via the zero-streak path): once 30 trials have been written, the recent-20 window is `optuna_trial_number=10..29` which STILL includes the non-zero outlier at #10, so `_last_n_all_zero` returns False at every snapshot; the existing `max_trials` stop condition completes the study with `status='completed'` and `best_metric > 0.0` (the outlier wins) — the zero-streak guard never fires in this scenario, which is the point of the boundary AC
- Example values:
  - Input: stub adapter switches behavior on the 11th `search_batch` invocation (`optuna_trial_number=10`) to return the non-zero-scoring response from `build_hits_response(query_ids)`; every other invocation returns the zero-scoring response
  - Expected at terminal-20 snapshot: `study.status='running' AND _last_n_all_zero(db, study_id, n=20) == False`
  - Expected at terminal-30 (run-to-completion) snapshot: `study.status='completed' AND study.failed_reason IS NULL AND best_metric > 0.0`

### AC-3: Interleaved failures + zeros does not fire either guard

- Given a study seeded via `seed_study(max_trials=24, parallelism=1)` where the stub adapter alternates: 1 zero-metric `complete` trial, then 1 `failed` trial (`raise_on_search=ClusterUnreachableError`), repeating 12 times (= 24 total trials)
- When the orchestrator runs to terminal
- Then **neither** guard fires:
  - `_last_n_all_failed` sees the most-recent 5 trials = `[failed, complete, failed, complete, failed]` (alternating), all-failed predicate is False
  - `_last_n_all_zero` sees the most-recent 20 trials = alternating `complete`(zero) / `failed`, the failures fail the `status='complete'` predicate, all-zero predicate is False
- And the study terminates as `status='completed'` via `max_trials_reached` with `best_metric=0.0` (every successful trial scored 0)
- Example values:
  - Input: stub adapter with `raise_on_search` toggled on every other call (the test installs a custom stub variant that flips its `raise_on_search` per call); `max_trials=24`
  - Expected: `study.status='completed' AND study.failed_reason IS NULL AND best_metric=0.0`

### AC-4: Cancel-race during zero-streak abort exits cleanly without escalating

- Given the orchestrator's tick about to call `study_state.fail_study(...)` for the zero-streak abort
- When `study_state.fail_study` raises `InvalidStateTransition` (simulating the operator's `cancel_study` having transitioned `running → cancelled` between the polling-loop status read and the `fail_study` call — see precedent at [`orchestrator.py:202-209`](../../../../backend/workers/orchestrator.py))
- Then the orchestrator catches the exception, rolls back the session, logs `event_type="orchestrator_race_lost", attempted_reason="no_signal"` at INFO, and returns from the polling loop with **no exception escaping the Arq job**
- Production-state note: in the real production race, the operator's `cancel_study` is what raised the `InvalidStateTransition`, so the durable outcome is `status='cancelled'`. The AC's test (§14 test 5) verifies only the orchestrator's exception-handling and logging behavior — not the production cancel transition — because synthesizing the real race (cancel arriving in a specific µs-window inside `fail_study`'s service-layer transaction) is not feasible in a test fixture. The "operator cancel is durable" invariant is covered separately by the existing `feat_study_lifecycle` cancel acceptance criteria.
- Example values:
  - Input: monkeypatched `study_state.fail_study` set to `AsyncMock(side_effect=study_state.InvalidStateTransition("cancelled"))`; orchestrator running against a `seed_study(status='queued')` row with `_last_n_all_zero` monkeypatched to return `True`
  - Expected: the orchestrator's `start_study` task terminates without raising; structlog records contain an INFO `event_type="orchestrator_race_lost", attempted_reason="no_signal", study_id=<id>` entry; the `study` row's terminal status is NOT asserted by this test (the simulated raise leaves the row in `status='running'` because the test does not perform a real cancel transition).

### AC-5: Precedence — failure-streak block evaluates before zero-streak block (code-structure assertion)

- Given the orchestrator's tick loop with both helpers monkey-patched: `_last_n_all_failed` patched to return `True`, AND `_last_n_all_zero` patched to a spy that records every invocation
- And a study row in `status='running'`
- When one tick of the polling loop runs
- Then `study_state.fail_study` is called with `failed_reason="5 consecutive trial failures"` (the failure-streak path's exact string from `orchestrator.py:193`)
- And the structlog `event_type="stop_condition_fired", reason="consecutive_failures"` event is emitted at WARNING
- And `_last_n_all_zero` is **never invoked** (the failure-streak block returns from the loop before the new check is reached)
- Notes: This AC asserts code structure (block ordering), not a data state. The "both qualify simultaneously" scenario from earlier drafts is impossible in the trials-data domain because the failure-streak predicate (`status='failed'` on the recent 5) and the zero-streak predicate (`status='complete'` on the recent 20) are mutually exclusive on any shared row. Asserting ordering via mocked helpers is the only meaningful test of FR-4 precedence.
- Example values:
  - Test: a unit test on the orchestrator's tick block (or a focused integration test using `monkeypatch.setattr` on both helpers and a `study_state.fail_study` spy)
  - Expected: `fail_study.call_args.kwargs['failed_reason'] == "5 consecutive trial failures" AND zero_streak_spy.call_count == 0`

## 13) Non-functional requirements

- **Performance.** The new `_last_n_all_zero` query is one `SELECT status, primary_metric FROM trials WHERE study_id = :id ORDER BY optuna_trial_number DESC LIMIT 20`. There is **no dedicated `(study_id, optuna_trial_number DESC)` index** in MVP1 — the only `trials` index defined in [`migrations/versions/0003_study_lifecycle_schema.py:232-234`](../../../../migrations/versions/0003_study_lifecycle_schema.py) is `trials_study_metric` on `(study_id, primary_metric DESC NULLS LAST)`, whose leading column matches the WHERE clause but whose sort order does NOT satisfy `ORDER BY optuna_trial_number DESC`. The Postgres planner may use the existing index to filter by `study_id` and then sort the filtered rows, or it may choose a sequential scan depending on table statistics — either plan is acceptable for MVP1 study-scoped row counts (a single study typically has hundreds to a few thousand rows, study-scoped sorts complete sub-millisecond on dev-laptop hardware). The existing `_last_n_all_failed` helper at [`backend/workers/orchestrator.py:268-284`](../../../../backend/workers/orchestrator.py) uses the same access pattern without a dedicated index and has shown no orchestrator-tick perf impact in the eight months it's been running. **No new migration / no new index is in scope for this feature**; if post-deploy telemetry shows the orchestrator tick budget impacted, add the index in a follow-up `chore_*` PR.
- **Reliability.** The new guard adds one DB query per tick. The query's failure modes (Postgres unavailable, statement timeout) are the same as the existing `_last_n_all_failed` and `aggregate_trials_summary` calls — the surrounding session-context-manager handles `OperationalError` by re-raising for Arq retry, which restarts the orchestrator.
- **Operability.** Two new structlog records (see §6 Audit events). Grep recipe for ops: `event_type=stop_condition_fired AND reason=no_signal` to enumerate aborts. No new metric is emitted (MVP1 has no Prometheus/SigNoz integration; that lands at MVP2).
- **Accessibility/usability.** N/A — no UI change.

## 14) Test strategy requirements (spec-level)

**Test layers required by `docs/05_quality/testing.md` for an orchestrator change:**

- **Unit tests** (`backend/tests/unit/`): not required at the unit layer because RelyLoop's unit suite is strictly DB-free (`docs/05_quality/testing.md`), and every test below seeds real trial rows or runs the real orchestrator's polling loop. The two precedence/cancel-race tests below live in the **integration** layer accordingly (renamed from "unit" in earlier drafts of this spec — the seam GPT-5.5 cycle-2 finding F6 flagged is the `_running_orchestrator` context manager + monkeypatched helpers + `seed_study(status='queued')`, identical to how `test_ac5_five_consecutive_failures_fail_the_study` works today).
- **Integration tests** (`backend/tests/integration/test_study_lifecycle.py`): mandatory. **Six** new tests total — three end-to-end orchestrator tests, two precedence/cancel-race tests, and one helper-boundary test:

  **End-to-end orchestrator behavior** (modeled on `test_ac5_five_consecutive_failures_fail_the_study`, using `seed_study(status='queued')` + `_running_orchestrator` + `_wait_for_status`):

  1. `test_zero_streak_20_consecutive_zeros_fails_the_study` — AC-1 + FR-3 structlog contract. Uses the new `build_zero_scoring_hits_response(query_ids)` stub-hits builder (returns hits whose doc IDs do NOT appear in `build_qrels(query_ids)`'s qrels, so pytrec_eval's intersection is empty and `primary_metric == 0.0`); `max_trials=25, parallelism=1`; asserts (a) terminal `study.status='failed' AND study.failed_reason == "no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"`; AND (b) via the structlog test helpers (`backend/tests/_log_helpers.py`) that a record was emitted with `event_type="stop_condition_fired", reason="no_signal", study_id=<id>` at WARNING level.
  2. `test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire` — AC-2 boundary. Stub returns the **non-zero** `build_hits_response` on the 11th `search_batch` invocation and the new **zero**-scoring response on every other invocation; `max_trials=30, parallelism=1`; asserts that at the terminal-20 snapshot `study.status='running' AND _last_n_all_zero(db, study_id, n=20) == False`; and asserts that at the terminal-30 run-to-completion snapshot `study.status='completed' AND failed_reason IS NULL AND best_metric > 0.0`.
  3. `test_zero_streak_interleaved_failures_does_not_fire` — AC-3. Stub alternates one zero-metric scoring response, one `ClusterUnreachableError` (via a custom alternating-stub variant); `max_trials=24, parallelism=1`; asserts neither guard fires; study terminates via `max_trials_reached` with `best_metric=0.0`.

  **Code-structure assertions on the orchestrator loop block** (use `monkeypatch.setattr` on the helpers + a `seed_study(status='queued')` row + `_running_orchestrator`; the orchestrator naturally performs its entry transition `queued → running` and then enters the polling loop where the monkeypatched helpers fire on the first tick):

  4. `test_zero_streak_precedence_failure_streak_runs_first` — AC-5. Monkeypatch both `_last_n_all_failed` → True and `_last_n_all_zero` → a spy that records every call. Start the orchestrator against a `seed_study(status='queued')` row. Wait for terminal status; assert `study.status='failed' AND study.failed_reason == "5 consecutive trial failures"` AND the zero-streak spy's `call_count == 0`.
  5. `test_zero_streak_cancel_race_during_abort` — AC-4. Monkeypatch `_last_n_all_zero` → True AND `study_state.fail_study` → an `AsyncMock` that raises `InvalidStateTransition("cancelled")`. Start the orchestrator against a `seed_study(status='queued')` row. Wait for the orchestrator task to terminate; assert NO exception escapes the task, AND the structlog test helpers (`backend/tests/_log_helpers.py`) confirm an `event_type="orchestrator_race_lost", attempted_reason="no_signal"` event was emitted at INFO. (The study row stays at `status='running'` in this synthetic test because `fail_study` raised — that's correct; the operator's cancel that "won the race" is simulated by the raise, not by an actual cancel transition.)

  **Helper boundary semantics** (per cycle-2 F5, the most error-prone contract is the SQL/order/LIMIT/NULL semantics, so it gets a dedicated focused test):

  6. `test_last_n_all_zero_helper_boundary_cases` — FR-1 + FR-5. **Fixture isolation contract**: each matrix sub-case below runs against its OWN study (a fresh `seed_study(...)` call per parameterized case via `@pytest.mark.parametrize`), with trials inserted directly via `repo.create_trial` / `db.execute(insert(Trial))` using deterministic `(optuna_trial_number, status, primary_metric)` tuples. No two sub-cases share a study row — this is required because the helper's contract is "recent-n on this study", and a shared study would make `ORDER BY optuna_trial_number DESC LIMIT 20` order-dependent across sub-cases. The matrix:
     - 0 trials → False
     - 19 zero-metric `complete` trials → False (insufficient)
     - 20 zero-metric `complete` trials → True
     - 20 trials where one row at `optuna_trial_number=10` has `primary_metric=0.5` → False
     - 20 trials where one row at `optuna_trial_number=10` has `status='failed'` → False
     - 20 trials where one row at `optuna_trial_number=10` has `status='pruned'` → False
     - 20 trials where one row at `optuna_trial_number=10` has `primary_metric IS NULL` → False
     - 25 trials: trial 0–4 are non-zero, trials 5–24 are all zero-metric `complete` → True (the older outlier is outside the recent-20 window)

- **Contract tests** (`backend/tests/contract/`): not required. No API surface change.
- **E2E tests** (`ui/tests/e2e/`): not required. No new UI route. The existing `StudyHeader` failed-reason rendering is already covered by failure-state component tests against the same DOM.

A new stub-hits builder `build_zero_scoring_hits_response(query_ids)` (returns hits whose doc IDs do NOT appear in `build_qrels(query_ids)`'s qrels, so pytrec_eval's intersection is empty and `primary_metric == 0.0`) lives alongside `build_hits_response` in `backend/tests/integration/fixtures/handbuilt_qrels.py`.

## 15) Documentation update requirements

- `docs/01_architecture/`: **no change required**. No new endpoint, no new error code, no new column.
- `docs/02_product/planned_features/feat_orchestrator_zero_streak_abort/`: this spec + `pipeline_status.md` (created by spec-gen).
- `docs/03_runbooks/`: **no change required** for MVP1. (A future addition to a not-yet-existing `study-debugging.md` runbook could mention the new `failed_reason` string — but that runbook doesn't exist yet, and adding a section for one string is not warranted.)
- `docs/04_security/`: **no change required**. No new threat surface.
- `docs/05_quality/`: **no change required**. Integration tests follow the existing pattern.
- `state.md`: updated when the feature ships (at finalization), per the existing convention.
- `CLAUDE.md`: **no change required**. No new convention, env var, or build command.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. The change is a hardcoded guard in the orchestrator. Rolling back means reverting the commit.
- **Migration/backfill expectations:** none. No schema change.
- **Operational readiness gates:** all six new integration tests listed in §14 must pass — the three end-to-end orchestrator tests (AC-1, AC-2, AC-3), the two code-structure assertions (AC-4 cancel-race, AC-5 precedence), and the helper-boundary parameterized test (FR-1 + FR-5). `make test` (unit + integration + contract) must be green; `make lint` + `make typecheck` clean. The existing `test_ac5_five_consecutive_failures_fail_the_study` must continue to pass (FR-4 precedent preservation).
- **Release gate:** standard PR gates per CLAUDE.md — CI green, Gemini Code Assist review adjudicated, GPT-5.5 final review adjudicated, branch protection rules respected on `main`.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (`_last_n_all_zero` helper) | AC-1, AC-2, AC-5 | Story 1.1 (helper) | `backend/tests/integration/test_study_lifecycle.py::test_zero_streak_20_consecutive_zeros_fails_the_study`, `::test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire`, `::test_last_n_all_zero_helper_boundary_cases`, `::test_zero_streak_precedence_failure_streak_runs_first` | none |
| FR-2 (`_ZERO_STREAK_THRESHOLD = 20`) | AC-1, AC-2 | Story 1.1 (constant) | (constant value asserted indirectly by AC-1 / AC-2 integration tests) | none |
| FR-3 (abort block + structlog) | AC-1, AC-4 | Story 1.2 (loop wiring) | `::test_zero_streak_20_consecutive_zeros_fails_the_study`, `::test_zero_streak_cancel_race_during_abort` | none |
| FR-4 (failure-streak precedence) | AC-3, AC-5 | Story 1.2 (loop order) | `::test_zero_streak_interleaved_failures_does_not_fire`, `::test_zero_streak_precedence_failure_streak_runs_first`, `::test_ac5_five_consecutive_failures_fail_the_study` (existing, asserts precedent still wins) | none |
| FR-5 (no-op below threshold) | AC-2 | Story 1.1 + 1.2 | `::test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire`, `::test_last_n_all_zero_helper_boundary_cases` | none |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 … AC-5) pass in CI.
- [ ] `make test-unit`, `make test-integration`, `make test-contract`, `make lint`, `make typecheck` are green.
- [ ] Gemini Code Assist review adjudicated.
- [ ] GPT-5.5 final-pass review adjudicated.
- [ ] No open questions remain in §19.
- [ ] `state.md` updated at finalization with the new feature entry.

## 19) Open questions and decision log

### Open questions

None. All forks identified during idea preflight have been locked:

- Threshold value: **20** (idea §"Threshold rationale", locked).
- Configurability: **module-level constant**, NOT `Settings` field (idea §"Configurability", locked — mirrors `_CONSECUTIVE_FAILURE_THRESHOLD = 5` precedent).
- Loop position: **after `_last_n_all_failed`, before `max_trials` / `time_budget_min`** (this spec FR-4, locked).
- Frontend code change: **none** (this spec §3 Out of scope, locked — existing `StudyHeader.failed_reason` renderer covers it).
- New error code: **none** (this spec §3 Out of scope + §4 Anti-patterns, locked).
- Migration: **none** (this spec §9, locked).

### Decision log

- 2026-05-21 — **Threshold = 20** — Optuna TPE warm-up default is 10 random samples; 20 covers BOTH the 10 random and 10 informed phases. If both classes score 0.0, the search space genuinely can't produce signal. (Source: idea §"Threshold rationale (locked at 20)".)
- 2026-05-21 — **Module-level constant, not `Settings`** — mirrors the existing `_CONSECUTIVE_FAILURE_THRESHOLD = 5` precedent at `orchestrator.py:69`. Operator-tunable knobs are reserved for surfaces operators actually tune at deploy time. (Source: idea §"Configurability".)
- 2026-05-22 — **Loop ordering: failure-streak → zero-streak → max_trials/time_budget** — preserves the existing AC-5 (`feat_study_lifecycle`) behavior and prevents the new guard from masking real adapter failures with a less-specific diagnosis. (This spec FR-4.)
- 2026-05-22 — **No `STUDY_NO_SIGNAL` error code** — the idea floated allocating one, but on closer inspection there's no HTTP 4xx/5xx envelope to attach it to (the operator surface is the existing `failed_reason` string column, not a new error). Allocating an error code that never appears in any envelope creates spec/runbook clutter. The exact `failed_reason` string is the stable contract for tests and future FAQ entries. (This spec §3 Out of scope + §4 Anti-pattern + §7.5.)
- 2026-05-22 — **No frontend tooltip / FAQ link** — the existing `StudyHeader.failed_reason` row renders any string verbatim; coupling UI behavior to the orchestrator's exact wording is fragile and is the wrong layer for FAQ surfacing. Future FAQ work belongs in `chore_guides_faq`. (This spec §11.)
- 2026-05-22 — **Equality on `Float` (`primary_metric == 0.0`) is the right predicate** — `backend.app.eval.scoring.score()` emits exactly `0.0` (not a near-zero float) for the empty-qrels-intersection degenerate case across NDCG/MAP/MRR/precision/recall. No floating-point tolerance band needed. (This spec FR-1 Notes.)
