# Feature Specification — Baseline-trial computation (`feat_study_baseline_trial`)

**Date:** 2026-05-25
**Status:** Draft — pending GPT-5.5 cross-model review
**Owners:** Eric Starr (engineering), Eric Starr (product)
**Related docs:**

- Idea: [`idea.md`](idea.md)
- Phase 1 spec (shipped): [`feat_pr_metric_confidence/feature_spec.md`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md)
- Sibling that gates on this feature: [`feat_auto_followup_studies/feature_spec.md`](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) (FR-2b)
- Sibling that supplies lineage: [`feat_digest_executable_followups/feature_spec.md`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md)
- API conventions: [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- Data model: [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)

**Depends on:** Phase 1 of `feat_pr_metric_confidence` (PR #180, merged 2026-05-21). Additive — no API contract break, no migration to undo.

---

## 1) Purpose

- **Problem:** `studies.baseline_metric` is declared (`backend/app/db/models/study.py:95`) but never written. The PR body's `## Metric delta` section shows `baseline=None → achieved=X` with no `delta_pct`. Phase 1 of `feat_pr_metric_confidence` ships per-query analytics that compare the winner against the runner-up #2 trial — useful for "is this winner robust?" but not "does this regress queries production gets right?"
- **Outcome:** The orchestrator runs a single non-Optuna baseline trial before Optuna starts, persists it as a real `Trial` row, stamps `studies.baseline_metric` + `studies.baseline_trial_id`, and the confidence analytics + auto-followup gate + digest narrative + PR body all switch from "vs runner-up" to "vs baseline" automatically. The approver's central question — "does my candidate beat my current production behavior?" — becomes answerable on every PR.
- **Non-goal:** This feature does NOT redesign the orchestrator's polling loop, does NOT modify the search-space schema, does NOT add a new evaluation metric, and does NOT change Optuna's sampler/pruner behavior. The baseline trial is just one more `Trial` row that the runtime largely treats like any other — with a `is_baseline=true` flag and an off-band trial-number sentinel so the Optuna RDB never sees it.

## 2) Current state audit

### Existing implementations

| Surface | File:Line | What it does today | Why this feature touches it |
|---|---|---|---|
| `studies.baseline_metric` column | `backend/app/db/models/study.py:95` | Declared `Float NULL` with docstring "populated by the orchestrator (Phase 2)". Always `NULL` in production. | Phase 2 finally writes it. |
| `_compute_metric_delta` | `backend/workers/digest.py:510-522` | Reads `study.baseline_metric` into `baseline`, computes `delta_pct = (achieved - baseline) / baseline * 100` when non-zero baseline. Today both inputs are None. | After this feature, both inputs are populated → the PR body's metric-delta section gains real numbers automatically (zero code change). |
| Digest user prompt | `prompts/digest_narrative.user.jinja:10-13` | `<baseline_vs_achieved>` block already emits `baseline_metric: {{ baseline_metric if baseline_metric is not none else 'N/A (no baseline trial)' }}`. | The template is already future-proof — no change needed. |
| Digest system prompt | `prompts/digest_narrative.system.md:34-39` | Already documents `comparison_against` taking `runner_up` (MVP1) or `baseline` (Phase 2). | The framing guidance for "regressed vs production baseline" wording lives here — needs a 1–2 sentence addition (FR-7). |
| `compute_study_confidence` | `backend/app/domain/study/confidence.py:496-635` | Pure-domain orchestrator. Always emits `comparison_against="runner_up"` at line 624 with comment `# FR-3 locked for Phase 1`. | One-line conditional change to switch to `"baseline"` when `study.baseline_trial_id` is set AND the row has `per_query_metrics`. |
| `ComparisonAgainst` Literal | `backend/app/domain/study/confidence.py:114` | `Literal["runner_up", "baseline"]` — both values already wire-modeled. Docstring at line 115 explicitly states Phase 1 unconditionally emits `runner_up` and `baseline` is reserved for Phase 2. | No change. |
| `evaluate_chain_gate` | `backend/app/domain/study/auto_followup.py:91-169` | Computes `lift = parent.best_metric - first_decile_max` (implicit-baseline proxy from earliest decile of complete trials). Module docstring at lines 7-11 explicitly says: "When `feat_study_baseline_trial` ships and populates `studies.baseline_metric`, FR-2b activates and this module switches to 'lift-over-baseline' via a one-line change." | Touch points enumerated in FR-5 below. |
| `ConfidencePanel` UI | `ui/src/components/studies/confidence-panel.tsx:98,113` | Reads `per_query_outcomes.comparison_against` and calls `formatComparison()` — already handles both wire values. Test at `ui/src/__tests__/components/studies/confidence-panel.test.tsx:136` ("switches the comparison label to 'vs baseline' when comparison_against === 'baseline' (Phase 2 future)") already passes. | No code change. The label flip is data-driven and the future test is already green. |
| Frontend enum allowlist | `ui/src/lib/enums.ts:83-87` | `COMPARISON_AGAINST_VALUES = ['runner_up', 'baseline'] as const` with `// Values must match backend/app/domain/study/confidence.py ComparisonAgainst.` source-of-truth comment. | No change. |
| Glossary entry | `ui/src/lib/glossary.ts:676` | `confidence.comparison_against` entry already authored. | No change. |
| Frontend types | `ui/src/lib/types.ts:2135,2690` | `comparison_against: 'runner_up' \| 'baseline'` and `baseline_metric: number \| null` already typed. | Add `baseline_trial_id: string \| null` to `StudyDetail` (the openapi types regenerate from the FastAPI schema). |
| PR body confidence section | `backend/workers/git_pr.py:513` | `f"{outcomes.regressed} regressed (vs {outcomes.comparison_against})"` — template-driven. | No code change; the wire value flips. |
| `create_proposal_from_study` agent tool | `backend/app/agent/tools/proposals/create_proposal_from_study.py:62-68` | Already builds `metric_delta = {"baseline_metric": study.baseline_metric, "best_metric": study.best_metric}` when either is non-None. | No code change; today the dict is built only when `best_metric` is non-None and stamps `baseline_metric=None`. Post-feature, it contains both numbers. |
| `studies.py:_detail` | `backend/app/api/v1/studies.py:121-153` | Serializes `baseline_metric` onto `StudyDetail`. | Add `baseline_trial_id` to the serializer + `StudyDetail` schema. |
| Existing tests asserting `comparison_against == "runner_up"` | `backend/tests/unit/workers/test_digest_prompt_render.py:185,243`; `backend/tests/unit/domain/study/test_confidence.py:432`; `backend/tests/contract/test_pr_body_confidence_section.py:54,205`; `backend/tests/integration/test_studies_api_confidence.py:477` | 5 tests assert the literal value `"runner_up"` against fixtures that have no baseline. | NO change — these fixtures don't set `baseline_trial_id`, so the FR-4 conditional keeps them on the `"runner_up"` branch (regression coverage for the fallback path). |

### Navigation and link impact

N/A — no new pages, no URL changes. The feature is data-flow + worker-orchestration only.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/domain/study/test_confidence.py` | tests for `compute_study_confidence` with `comparison_against == "runner_up"` | 1 assertion (line 432) | Keep (regression coverage for FR-4 fallback). |
| `backend/tests/contract/test_pr_body_confidence_section.py` | tests for PR body confidence wording with `comparison_against="runner_up"` | 2 fixtures (lines 54, 205) | Keep (regression coverage). Add new fixture with `baseline_trial_id` set to cover FR-4 baseline branch. |
| `backend/tests/integration/test_studies_api_confidence.py` | integration test for `/api/v1/studies/{id}` confidence shape | 1 assertion (line 477) + 1 fixture (line 112 with `baseline_metric=None`) | Keep + add baseline-branch test. |
| `backend/tests/integration/test_existing_row_read_compat.py` | regression: rows pre-dating `baseline_metric` populate read correctly | line 117 sets `baseline_metric=None` | Keep — verifies the FR-7 fallback path. |
| `backend/tests/integration/test_open_pr_worker_confidence_plumbing.py` | open_pr worker confidence read-side plumbing | line 115 sets `baseline_metric=None` | Keep. Add a new test with baseline trial + non-None baseline_metric. |
| `backend/tests/integration/_digest_helpers.py` | shared helper `seed_completed_study(baseline_metric=0.612)` | already parameterised | No change. |
| `backend/tests/unit/workers/test_digest_prompt_render.py` | digest user-prompt render with `baseline_metric=0.612` | 2 assertions on `runner_up` (185, 243) | Keep — runner_up branch is hit when `baseline_trial_id IS NULL`. Add new test for the `baseline` branch. |

### Existing behaviors affected by scope change

- **`_compute_metric_delta` output**: Current: `{primary_metric_key: {baseline: None, achieved: 0.65, delta_pct: None}}`. New: `{primary_metric_key: {baseline: 0.51, achieved: 0.65, delta_pct: 27.5}}`. Decision: **yes**, this is the headline UX win — locked in §19 D-1.
- **`compute_study_confidence` comparison source**: Current: always runner-up #2. New: baseline trial when `baseline_trial_id IS NOT NULL` AND that row has `per_query_metrics`; runner-up #2 otherwise. Decision: **yes**, locked in §19 D-2.
- **Auto-followup gate's "lift" definition**: Current: `parent.best_metric - first_decile_max` (implicit-baseline from earliest decile). New: `parent.best_metric - parent.baseline_metric` when `parent.baseline_metric IS NOT NULL`; `first_decile_max` fallback otherwise. Decision: **yes**, locked in §19 D-3. This is the "one-line change" the `auto_followup.py:9-11` module docstring promised.
- **Trial-listing UI shows the baseline trial**: Current: nothing to show. New: depends on the UX decision in §19 Open Question 1 — filter out by default, or show with a "Baseline" badge. Decision: **deferred to spec**, recommended default in §19.

---

## 3) Scope

### In scope

- New column `studies.baseline_trial_id` (denormalized FK to the baseline trial row).
- New column `trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE` (sentinel marker for the off-band non-Optuna trial).
- Partial unique index `uq_trials_study_baseline_complete ON trials (study_id) WHERE is_baseline = TRUE AND status = 'complete'` (single-complete-baseline-per-study guarantee — see D-16).
- Alembic migration `0020_studies_baseline_trial` adding both columns + the partial index with reversible downgrade + idempotency guards.
- New worker function `run_baseline_trial(ctx, study_id, params)` in `backend/workers/baseline.py` mirroring `run_trial`'s render → search → score → persist shape but without `study.ask()` / `study.tell()`.
- Orchestrator change in `backend/workers/orchestrator.py:start_study` — resolve baseline params via the 4-tier fallback, enqueue `run_baseline_trial`, wait synchronously, stamp `study.baseline_metric` + `study.baseline_trial_id` BEFORE entering the Optuna polling loop.
- Pure-domain resolver `resolve_baseline_params` in `backend/app/domain/study/baseline_resolver.py` implementing the 4-tier fallback (D-2 below).
- One-line change in `backend/app/domain/study/confidence.py:624` to emit `comparison_against = "baseline"` when `baseline_trial_id` resolved AND the row has `per_query_metrics`.
- One-line change in `backend/app/domain/study/auto_followup.py:156` to switch lift computation when `parent.baseline_metric IS NOT NULL`.
- Optional `config.baseline_params: dict[str, str | int | float | bool | None] | None` field on `CreateStudyRequest.config` (operator-supplied override; 3rd tier of the fallback; lives inside `studies.config` JSONB per D-7).
- `StudyDetail.baseline_trial_id` exposure on the `/api/v1/studies/{id}` response.
- Digest system-prompt extension (1–2 sentences) for "regressed vs production baseline" narrative framing.
- Trial-listing UI: `is_baseline` filtering behavior (see §19 OQ-1).
- Test coverage at every layer (unit / integration / contract / E2E).

### Out of scope

- Re-running the baseline trial on parameter changes (it's a one-shot at study-create-time).
- Backfilling `baseline_trial_id` / `baseline_metric` for studies created before this feature lands. They stay `NULL` → confidence analytics fall back to runner-up; auto-followup gate falls back to first-decile-max.
- Multi-baseline comparison (e.g., compare against two production configs). Out of MVP1 scope.
- Updating the chat agent's `get_study` / `create_proposal_from_study` tools to expose `baseline_trial_id` beyond what the existing `baseline_metric` propagation already does (already wired — no change).
- Auto-fork detection that picks the parent-study's params automatically without operator input. Today's `feat_auto_followup_studies` already auto-spawns followups; this feature inherits its lineage logic for free via the 4-tier fallback resolver.
- Re-running the baseline when the operator edits the parent template post-study-creation. Studies are immutable post-create per `feat_study_lifecycle`.

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) and `backend/app/api/v1/studies.py`:

- **Endpoint prefix:** `/api/v1/studies` — confirmed at `backend/app/api/v1/studies.py:34` (router prefix).
- **Router namespace:** `backend/app/api/v1/studies.py` (existing — no new router file).
- **HTTP methods:** No new endpoint added by this feature. The change is on the response shape of existing `POST /api/v1/studies` + `GET /api/v1/studies/{id}` + agent tool boundaries.
- **Error envelope (non-auth):** `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` per `api-conventions.md`. Confirmed by reading `backend/app/api/errors.py` and the existing `_err()` helper at `backend/app/api/v1/studies.py:113`.
- **Auth error shape:** N/A — MVP1 has no auth surface per CLAUDE.md release matrix.

### Phase boundaries

This feature is a single phase. Phase 1 of `feat_pr_metric_confidence` (the parent feature) shipped 2026-05-21; this feature is its deferred Phase 2 split into its own `/pipeline` lifecycle for tracking discoverability. No further sub-phases.

## 4) Product principles and constraints

- **Backward-compatible by construction**: studies created before this migration stay `baseline_trial_id IS NULL` and continue to render `comparison_against = "runner_up"` (FR-4 fallback) and use `first_decile_max` for the auto-followup gate (FR-5 fallback). No backfill.
- **Failed baseline must not fail the study**: the baseline is informational, not load-bearing. A baseline trial that raises (cluster unreachable, query DSL invalid, scorer crash) results in a `Trial` row with `status='failed'`, `baseline_trial_id` stays NULL, the orchestrator logs and proceeds. Confidence + auto-followup gate fall back per FR-4 / FR-5.
- **Operator's "current production behavior" is what they declare it to be**: the 4-tier fallback (D-2) is opinionated. The operator's mental model — "what does this PR CHANGE vs. what's currently live?" — is preserved by routing through `parent_proposal_id` first (the digest-executable followup case) and falling back to template defaults only when nothing else is available.
- **One-line change rule**: the existing `feat_pr_metric_confidence` infrastructure was designed for this extension. Every cross-cutting consumer is data-driven; this feature should NOT need a multi-call cascade through services.
- **Single source of truth for `is_baseline`**: trials carry a boolean flag, not an `optuna_trial_number = -1` sentinel. Reason: Optuna's RDB does not tolerate negative trial numbers (verified via `optuna.study.Study.ask().number` always returning a non-negative int — and the existing `infra_optuna_eval` worker contract uses `study.trials[optuna_trial_number]` which expects non-negative indexes).
- **Baseline trial uses the same engine adapter contract as Optuna trials**: render → `search_batch` → score. No special-case path; just no `study.ask()` / `study.tell()`. This keeps the engine-adapter Protocol clean.
- **Always read settings from `Settings`**: `OPENAI_BASE_URL`, `OPENAI_MODEL`, etc. are never hardcoded (CLAUDE.md Absolute Rule #8). Same for `studies_default_timeout_s` — the baseline trial respects the same per-trial timeout the user's `studies.config.trial_timeout_s` carries.

### Anti-patterns

- **Do not** treat `optuna_trial_number = -1` as the *primary* baseline discriminator. The canonical flag is `trials.is_baseline = TRUE`. The `-1` sentinel exists only because the column is `NOT NULL` (column was declared NOT-NULL in `feat_study_lifecycle` Phase 1 migration; making it nullable now would be a backward-incompatible schema change for a single edge). Optuna's RDB never queries the app `trials` table, so the sentinel is purely an app-side filler. Every code path that filters or counts Optuna trials MUST do so by `is_baseline = FALSE`, never by the absence of `optuna_trial_number = -1`.
- **Do not** call `study.ask()` / `study.tell()` from `run_baseline_trial`. The baseline isn't an Optuna trial — it's a recording of a known parameter combination's performance. Tell-ing Optuna about it would either (a) prejudice the TPE sampler with a fixed-seed observation Optuna treats as a prior, or (b) raise on duplicate trial-number registration. **Persist directly to the `trials` table with `is_baseline=true` and skip Optuna entirely.**
- **Do not** make baseline-trial timeout configurable separately from `studies.config.trial_timeout_s`. Operators already tune that knob; a second timeout knob just for baseline is debt with no upside.
- **Do not** block on baseline failure with a hard error. The baseline is informational. If the adapter fails, score raises, or the timeout fires, persist the failed Trial row, leave `baseline_trial_id IS NULL`, log + proceed.
- **Do not** add a separate `baseline_trials` table. The denormalization-vs-normalization debate was settled in `feat_study_lifecycle`: trials are append-only and a `Trial` row is the canonical record. A second table would duplicate the schema and complicate cascade-delete semantics.
- **Do not** modify the existing 5 tests that assert `comparison_against == "runner_up"` to instead assert `"baseline"`. Those tests cover the FR-4 fallback path — they MUST keep failing on regressions to that path.

## 5) Assumptions and dependencies

- **Phase 1 (`feat_pr_metric_confidence`)**: ✅ shipped 2026-05-21 (PR #180). Required for `ComparisonAgainst` Literal, `ConfidenceShape`, `compute_study_confidence`, and the per-query-metrics column.
- **`feat_study_lifecycle` Phase 1+2**: ✅ shipped 2026-05-10/11 (PR #18 + #25). Required for the `studies` + `trials` tables, orchestrator, `run_trial` worker, `study_state` service.
- **`feat_digest_executable_followups`**: ✅ shipped 2026-05-24 (PR #225). Provides `studies.parent_proposal_id` + `parent_proposal_followup_index` for the 1st-tier fallback.
- **`feat_auto_followup_studies`**: ✅ shipped 2026-05-24 (PR #223). Provides `studies.parent_study_id` as an MVP1-active field for the 2nd-tier fallback.
- **`infra_adapter_elastic`**: ✅ shipped 2026-05-10 (PR #16). Required for the `SearchAdapter` Protocol the baseline trial uses.
- **`infra_optuna_eval`**: ✅ shipped 2026-05-10 (PR #23). The `score()` + `qrels_loader` infrastructure the baseline trial reuses.
- **`feat_llm_judgments`**: ✅ shipped 2026-05-11 (PR #35). Provides the judgments the baseline trial's qrels come from.

No external dependencies. No new SaaS accounts.

## 6) Actors and roles

- **Primary actor**: relevance engineer (the only user role in MVP1).
- **Role model**: N/A — single-tenant install, no auth surface (per CLAUDE.md release matrix; MVP1-3).
- **Permission boundaries**: every operator can read every study, including its baseline trial.

### Authorization

N/A — single-tenant install, no auth surface (MVP1-3 per CLAUDE.md).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) §"Reserved for later releases". A future spec note (deferred): when MVP2 lands, the baseline-trial completion + the `baseline_trial_id` stamp are state-mutations on the studies row and should both emit audit events. Capturing here so the MVP2 audit-emission sweep doesn't miss them.

## 7) Functional requirements

### FR-1: Migration adds `studies.baseline_trial_id`, `trials.is_baseline`, and a partial unique index
- Requirement:
  - The system **MUST** add an Alembic migration `0020_studies_baseline_trial` that:
    - Adds `studies.baseline_trial_id String(36) NULL` (not a formal FK — same rationale as `best_trial_id` at `study.py:99-103`).
    - Adds `trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE`.
    - Adds a **partial unique index** `uq_trials_study_baseline_complete ON trials (study_id) WHERE is_baseline = TRUE AND status = 'complete'`. This guarantees at most ONE complete baseline trial per study at the DB level — defense against the resume-race scenario where two orchestrator invocations both enqueue baseline jobs for the same study (per D-16). A second concurrent INSERT raises `IntegrityError`, which the worker catches, treats as "another worker already inserted", and exits cleanly without re-stamping.
    - Round-trips cleanly via `downgrade()` — drop index, drop column on trials, drop column on studies.
    - Uses idempotency guards (`DO $$ BEGIN ... IF NOT EXISTS ... END $$`) on every `ALTER TABLE` / `CREATE INDEX` so re-runs are no-ops.
- Notes: No backfill. Existing studies stay `baseline_trial_id IS NULL`. Existing trials stay `is_baseline=FALSE`. The partial unique index applies only to NEW baseline trials (existing trial rows all have `is_baseline=FALSE` and don't match the index predicate).

### FR-2: Orchestrator runs a single non-Optuna baseline trial before Optuna starts
- Requirement:
  - The system **MUST** insert a new phase in `backend/workers/orchestrator.py:start_study` between section "C. Parse search_space" (line 170) and section "D. Polling loop" (line 173) that:
    1. Resolves baseline params via `resolve_baseline_params(db, study)` (FR-3).
    2. If `params` is `None`, skip baseline entirely (preserve current behavior); log `event_type="baseline_skipped"` with reason.
    3. Else, generate a fresh `trial_id` (UUIDv7) and enqueue with a deterministic Arq job-id keyed on study: `arq_pool.enqueue_job("run_baseline_trial", study_id, trial_id, params, _job_id=f"baseline:{study_id}")`. The `_job_id` prevents Arq from accepting a duplicate enqueue if `resume_study` fires a second baseline-create before the first has landed an INSERT. When `enqueue_job` returns `None` (Arq rejected as duplicate), the orchestrator logs `event_type="baseline_enqueue_deduped"` and proceeds to the wait phase — the original enqueue's worker will land the row, and on observed `is_baseline=TRUE, status='complete'` row, FR-12 stamps it from whichever path observes it first.
    4. Wait for the baseline trial to terminal-out by polling the `trials` table for the row at `(study_id, trial_id, is_baseline=TRUE)` with `status IN ('complete', 'failed')`. Use a fresh session per poll tick (mirror the polling-loop pattern at orchestrator.py:182-188). Tick interval: 1 second (same `_REPLENISH_TICK_S`).
    5. Wait timeout: `wait_s = min(600, max(60, (study.config.trial_timeout_s or settings.studies_default_timeout_s) + 30))`. Floor 60s, ceiling 600s (10 min — long enough for slow engines, short enough that operators notice). For `trial_timeout_s ≤ 570s` (the common case), `wait_s` exceeds the worker's own per-trial timeout by ≥30s so the trial completes naturally before the wait gives up. For `trial_timeout_s > 570s` (rare; the `StudyConfigSpec` bound is 5..3600), the wait deliberately gives up before the worker — this is intentional: operators with extreme per-trial timeouts get the Optuna phase started promptly, and the worker self-stamps via FR-10 if the baseline eventually completes (per D-13).
    6. On timeout: log `event_type="baseline_wait_timeout"`, leave `baseline_trial_id IS NULL` (the worker will self-stamp later via FR-10 if it eventually completes), proceed to Optuna phase. The orchestrator does NOT attempt to cancel the in-flight baseline job — the worker is short-lived and the late stamp is correct behavior (operators get baseline data eventually even when the orchestrator gave up waiting; the Optuna loop is already running).
    7. On terminal row: if `status='complete'`, stamp `study.baseline_metric = trial.primary_metric` and `study.baseline_trial_id = trial.id`, commit. If `status='failed'`, log `event_type="baseline_failed"` with the trial's `error` text, leave `baseline_trial_id IS NULL`, proceed.
  - The orchestrator **MUST** continue to the Optuna polling loop regardless of baseline outcome.
- Notes: Synchronous wait, NOT parallel-with-Optuna. Rationale (D-4 below): the baseline is a one-shot fast trial (~1-5s); Optuna can wait. Running them in parallel risks both ending up `running` at the same time, which complicates UI ordering + leaks the baseline into the Optuna trial counter at the polling phase's first read.

### FR-3: Baseline-params resolution via 4-tier fallback
- Requirement:
  - The system **MUST** provide a pure-domain function `resolve_baseline_params(db, study) -> dict[str, Any] | None` in `backend/app/domain/study/baseline_resolver.py` (NOTE: takes `db` for the parent-row lookup; the function is async but pure of business logic — no service-layer side effects). Resolution order:
    1. **(d) Parent-proposal config** — if `study.parent_proposal_id IS NOT NULL`: load the parent proposal's `study_trial_id` (the best trial of the parent study). Return that trial's `params` dict. If the parent trial is missing/deleted, log `event_type="baseline_resolve_parent_proposal_missing"` and fall through to tier (c).
    2. **(c) Parent-study winner** — if `study.parent_study_id IS NOT NULL`: load the parent study and look up the trial at `parent.best_trial_id`. Return that trial's `params`. If missing, log + fall through to (b).
    3. **(b) Operator-supplied** — if `study.config["baseline_params"]` is set (operator passed `baseline_params` in the create-study request body), return it directly. Schema-level validation at `CreateStudyRequest` time guarantees the dict shape; the resolver does NOT re-validate against the search-space — that's by design (an operator may want to baseline against a config that isn't in the current study's search space, e.g. their actual production config).
    4. **(a) Template defaults** — return the deterministic middle-of-range for each declared param in `study.search_space.params`:
       - `FloatParam` → `(low + high) / 2.0` (with log-scale geometric mean when `log=true`: `sqrt(low * high)`).
       - `IntParam` → `(low + high) // 2` (Python integer division — picks the lower midpoint when the range is even-cardinality).
       - `CategoricalParam` → `choices[(len(choices) - 1) // 2]` (median index — picks the **lower** midpoint when even-cardinality; e.g., for `['a','b','c','d']` returns `'b'`).
    5. If after all four tiers the resolver returns `{}` (the template has no declared params), return `None` — no baseline trial runs.
  - The resolver **MUST** be invoked from `start_study` BEFORE the Optuna loop, AFTER `SearchSpace.model_validate` (orchestrator.py:170).
- Notes: Pure-domain so it's independently unit-testable. The async signature is needed because tiers (c) and (d) hit `repo.get_trial` / `repo.get_study` / `repo.get_proposal`.

### FR-4: `compute_study_confidence` switches comparison source when baseline trial available
- Requirement:
  - The system **MUST** modify `backend/app/domain/study/confidence.py:compute_study_confidence` so that when:
    - `study.baseline_trial_id IS NOT NULL`, AND
    - the corresponding trial row exists, AND
    - that trial has non-empty `per_query_metrics`,
    the per-query-outcomes comparison source becomes the baseline trial; `comparison_against = "baseline"`.
  - Otherwise (baseline missing / failed / row deleted / missing per_query_metrics): fall back to runner-up #2 (Phase 1 behavior); emit `comparison_against = "runner_up"`.
  - The function signature **MAY** add a new keyword-only argument `baseline_trial: Any | None = None` (paired with `runner_up_trial`). Callers (`backend.app.services.study_confidence.fetch_study_confidence`) pre-fetch the baseline trial in the same 4-query read pattern's Q-2 sibling.
- Notes: The single-line `comparison_against="runner_up"` literal at confidence.py:624 becomes a conditional. The `per_query_outcomes` block is otherwise unchanged. No API contract break — `ConfidenceShape.per_query_outcomes.comparison_against` is already typed `Literal["runner_up", "baseline"]`.

### FR-5: Auto-followup gate switches to lift-over-baseline when parent has baseline
- Requirement:
  - The system **MUST** modify `backend/app/domain/study/auto_followup.py:evaluate_chain_gate` to take a new `direction: Literal["maximize", "minimize"]` argument (defaulting to `"maximize"` for backward compat; caller passes `parent.objective["direction"]`). The lift computation becomes direction-aware:
    - **Maximize** direction (existing default — every MVP1 study today is maximize per inspection of `feat_study_lifecycle` examples):
      - If `parent.baseline_metric IS NOT NULL`: `lift = parent.best_metric - parent.baseline_metric`.
      - Otherwise: `lift = parent.best_metric - first_decile_max` (existing implicit-baseline behavior).
    - **Minimize** direction: signs flip — `lift = baseline_metric - parent.best_metric` (or `first_decile_min - parent.best_metric` for the implicit-baseline fallback; the `compute_first_decile_max` helper **MUST** also get a direction-aware sibling `compute_first_decile_extremum(complete_trials, direction)`).
  - The gate decision (`lift > epsilon` → ENQUEUE) stays unchanged — the lift value itself is always normalized so "better than baseline" is positive.
  - The `ChainGateOutcome.first_decile_max` field **MUST** be renamed to `first_decile_extremum` (forward-only rename; no callers depend on the field name yet — verified: only `evaluate_chain_gate` constructs `ChainGateOutcome`, only the test suite reads it).
  - The module docstring **MUST** be updated to reflect that FR-2b is now ACTIVE: delete the "When feat_study_baseline_trial ships..." sentence; replace with "FR-2b activated: when `parent.baseline_metric IS NOT NULL`, lift is computed directly against the baseline. Direction-aware via the `direction` argument (added 2026-05-25)."
- Notes: This is the "one-line change" the existing module docstring at `auto_followup.py:9-11` promised, plus the GPT-5.5-finding direction-awareness fix. Direction-awareness closes a latent bug in the Phase 1 `feat_auto_followup_studies` shipment that this feature is uniquely positioned to fix (because we're touching the same lines anyway).

### FR-6: `CreateStudyRequest` accepts optional `baseline_params`
- Requirement:
  - The system **MUST** add `config.baseline_params: dict[str, Any] | None = None` to the `StudyConfigSpec` schema (the nested `config` field of `CreateStudyRequest`). Stored as-is in `studies.config` JSONB.
  - The schema **MUST NOT** validate `baseline_params` against the current study's search space at create time — operators may legitimately want to baseline against a production config that's outside the current search space (e.g., to demonstrate the search space's win over a known-good config).
  - The schema **MUST** type `baseline_params` as `dict[str, str | int | float | bool | None] | None`. The discriminated value type forbids nested dicts / arrays — Pydantic enforces this at parse time and emits a `VALIDATION_ERROR` (422) on violation. The OpenAPI schema generated from this Pydantic type carries the constraint, and the frontend's `dict<string, primitive>` type-narrows correctly.
- Notes: `baseline_params` lands in `studies.config` (not a top-level column) because every study-tunable in MVP1 lives in `studies.config` and we don't want to grow the top-level schema for a per-study optional field.

### FR-7: Digest narrative system prompt extension
- Requirement:
  - The system **MUST** update `prompts/digest_narrative.system.md` to add a 1-2 sentence narrative-framing guideline:

    > When `<per_query_outcomes>` has `comparison_against = "baseline"`, regressors should be described as "regressed vs the operator's current production baseline" — not "vs the runner-up trial". Lead the narrative with this baseline framing when present, since it answers the approver's "does this change PROD?" question directly.

- Notes: No code change; prompt-only edit. Existing tests that snapshot the system prompt may need a fixture refresh (see §14 test strategy).

### FR-8: `StudyDetail.baseline_trial_id` exposure
- Requirement:
  - The system **MUST** add `baseline_trial_id: str | None` to the `StudyDetail` Pydantic schema at `backend/app/api/v1/schemas.py:668-698`, populated by `studies.py:_detail` at line 121.
  - The `TrialDetail` schema at `backend/app/api/v1/schemas.py:724-737` **MUST** add `is_baseline: bool` so the frontend can render the badge / filter behavior described in OQ-1.
- Notes: Forward-only — no migration story for downstream consumers. The frontend types regenerate from the FastAPI OpenAPI schema.

### FR-9: Frontend trial-listing filters baseline trials by default
- Requirement:
  - The trial-listing UI (`ui/src/components/studies/trials-table` or wherever the table lives — see §14 verification) **MUST** filter out `is_baseline=true` rows from the default view.
  - A new toggle / chip "Show baseline trial" **MUST** be available; when enabled, the baseline trial appears at the top of the table with a distinct "Baseline" badge.
  - The default filtered state is the unsurprising behavior: the baseline trial is a single one-shot that doesn't represent Optuna's exploration, so showing it inline with 100+ Optuna trials would confuse the trial-number ordering.
- Notes: This is the resolution of OQ-1 (default = filter out).

### FR-11: Downstream consumers MUST filter `is_baseline=FALSE` from Optuna-trial-counting paths

- Requirement:
  - The following code paths today aggregate or select from the `trials` table and assume every row is an Optuna trial. Each **MUST** filter `WHERE is_baseline = FALSE` after this feature lands:
    1. `backend/app/db/repo/trial.py:aggregate_trials_summary` — used by the orchestrator's stop-condition check (`_stop`), the `StudyDetail.trials_summary` API field, and the digest worker's "top trials" computation. Filtering on `is_baseline=FALSE` ensures `summary.total`, `summary.complete`, `summary.best_primary_metric`, and `summary.best_trial_id` describe ONLY the Optuna trials (the baseline appears under its own surface).
    2. `backend/app/db/repo/trial.py:list_complete_trials_for_confidence` (or however the 4-query read pattern's Q2 is named — see `backend/app/services/study_confidence.py:fetch_study_confidence`) — the `complete_trials_summary` input to `compute_study_confidence` MUST exclude baseline. Including the baseline would corrupt `runner_up_gap`, `convergence`, and `late_trial_stddev` aggregates.
    3. `backend/app/db/repo/trial.py:list_top_trials` (digest worker's top-10 list at `backend/workers/digest.py:_compute_top_trials`) — operators read this as "the top Optuna trials"; baseline appearing inline would conflate the two surfaces.
    4. Parameter-importance computation (`optuna.importance.get_param_importances`) — operates on Optuna's RDB, not the app trials table, so already safe by construction. Documented for completeness.
    5. `auto_followup.compute_first_decile_extremum` (renamed from `compute_first_decile_max` per FR-5) — already takes its iterable input from the caller. Caller MUST filter `is_baseline=FALSE` when fetching.
  - The orchestrator's `_last_n_all_failed` and `_last_n_all_zero` helpers (`backend/workers/orchestrator.py:320-371`) use `ORDER BY Trial.optuna_trial_number DESC LIMIT n`. In steady state (≥ N Optuna trials present), the `is_baseline=TRUE` row at `optuna_trial_number=-1` sorts last and never enters the window. **However**, during the brief window between baseline-trial completion and the first Optuna trial reaching terminal, the only matching row could be the baseline (because the helpers don't filter on status). **MUST add `WHERE is_baseline = FALSE` to both helpers** to prevent a failed baseline from triggering a spurious "5 consecutive failures" alert before any Optuna trial has even run.
- Notes: Each repo helper either adds the filter inline or accepts a new `include_baseline: bool = False` kwarg. The inline filter is preferred — operators never want baseline in these aggregates, so the kwarg is unused complexity.

### FR-12: Single stamping helper `services.study_state.stamp_baseline_trial`

- Requirement:
  - The system **MUST** add a service function `services.study_state.stamp_baseline_trial(db, study_id, trial_id, primary_metric) -> bool` that:
    1. Loads the candidate `Trial` row by `id = trial_id`; raises `BaselineTrialNotFound` if missing.
    2. Asserts `trial.study_id == study_id` and `trial.is_baseline == TRUE` and `trial.status == 'complete'`; raises `InvalidBaselineTrialState` on violation.
    3. Executes idempotent UPDATE: `UPDATE studies SET baseline_trial_id = $1, baseline_metric = $2 WHERE id = $3 AND baseline_trial_id IS NULL`.
    4. Returns `True` if a row was updated (this caller stamped), `False` if a sibling already stamped (race-tolerant — the return value is informational, not load-bearing).
    5. Commits the transaction (or leaves commit to the caller — locked in Story 1.4 implementation, defaulting to leave-to-caller for the existing `study_state` precedent at `services/study_state.py`).
  - The orchestrator (FR-2 step 7), `resume_study` (FR-2 implied via idempotency notes in §9), and `run_baseline_trial` (FR-10 step 7) **MUST** all stamp through this helper. No direct `UPDATE studies SET baseline_trial_id = ...` statements outside this helper.
- Notes: Mirrors the existing `services.study_state.complete_study` pattern — single chokepoint for state-mutation, easy unit-testable, easy to add audit_log emission at MVP2.

### FR-10: `run_baseline_trial` worker function
- Requirement:
  - The system **MUST** ship a new Arq job `run_baseline_trial(ctx, study_id, trial_id, params)` in `backend/workers/baseline.py` that:
    1. Loads the `Study` row + cluster + template + queries + qrels (same lookups as `run_trial`).
    2. Builds the adapter via `build_adapter(cluster)`.
    3. Renders the template via `adapter.render(template, params, q.query_text)` for each query.
    4. Calls `adapter.search_batch(target, native_queries, top_k, strict_errors=False, timeout=trial_timeout_s)`.
    5. Scores via `score(qrels, run_dict, metrics_set)` (same metric set as `run_trial`).
    6. Persists a `Trial` row with `is_baseline=TRUE` and `optuna_trial_number = -1` (NOT-NULL sentinel filler — see §4 Anti-patterns; the canonical discriminator is `is_baseline=TRUE`).
    7. On `status='complete'`: BEFORE returning, the worker **MUST** call the new service helper `services.study_state.stamp_baseline_trial(db, study_id, trial_id, primary_metric)` (FR-12) to durably stamp `studies.baseline_trial_id = trial_id` and `studies.baseline_metric = primary_metric`. The stamp is idempotent via `WHERE baseline_trial_id IS NULL` — if the orchestrator already stamped (fast path), the worker UPDATE is a no-op. This covers the late-completion case where the orchestrator's wait phase timed out but the worker eventually succeeded.
    8. Returns normally on success or persisted failure (Arq treats as success unless infrastructure raised).
  - The worker **MUST** use `trial_id`-based idempotency (NOT `(study_id, optuna_trial_number)`): on entry, check for an existing terminal `trials` row with `id = trial_id` (the orchestrator pre-generates the UUIDv7 in FR-2 and passes it as a job argument). If found, no-op and return. Rationale: `(study_id, -1)` is a poor uniqueness key because the orchestrator may re-enqueue baseline trials on retry — but `trial_id` is uniquely generated per orchestrator-decision-point.
  - The worker **MUST** be registered in `backend/workers/main.py` `WorkerSettings.functions`.
- Notes: The worker is `~80 LOC` (smaller than `run_trial` — no Optuna interaction, no reconciliation paths, no consecutive-failure tracking).

## 8) API and data contract baseline

### 8.1 Endpoint surface

No new endpoints. Existing surfaces gain new response fields:

| Method | Path | Response field added | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/studies` | request body gains `config.baseline_params: dict \| None`; response gains `baseline_trial_id: string \| null` | FR-6 + FR-8 |
| `GET` | `/api/v1/studies/{id}` | response gains `baseline_trial_id: string \| null` | FR-8 |
| `GET` | `/api/v1/studies/{id}/trials` | each row gains `is_baseline: bool` | FR-8 |

No new error codes introduced.

### 8.2 Contract rules

- Existing `ConfidenceShape.per_query_outcomes.comparison_against` Literal already includes both `"runner_up"` and `"baseline"` wire values — no contract break.
- `StudyDetail.baseline_trial_id` is nullable; clients **MUST** tolerate `null` and **MUST NOT** assume the FK target exists (denormalized, not enforced — same rationale as `best_trial_id`).
- `TrialDetail.is_baseline` is non-nullable bool (DB default `FALSE`).

### 8.3 Response examples

`GET /api/v1/studies/{id}` success (post-baseline-trial):

```json
{
  "id": "0192f24c-bce0-7e58-a6e8-b9c6a4def888",
  "name": "boost-titles-tune",
  "cluster_id": "0192f24c-bce0-7000-...",
  "target": "products",
  "template_id": "0192f24c-bce0-7100-...",
  "query_set_id": "0192f24c-bce0-7200-...",
  "judgment_list_id": "0192f24c-bce0-7300-...",
  "search_space": {"params": {"boost_title": {"type": "float", "low": 0.5, "high": 10.0}}},
  "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
  "config": {"max_trials": 100, "baseline_params": {"boost_title": 1.5}},
  "status": "completed",
  "failed_reason": null,
  "optuna_study_name": "0192f24c-bce0-7e58-a6e8-b9c6a4def888",
  "parent_study_id": null,
  "baseline_metric": 0.512,
  "baseline_trial_id": "0192f24c-bce0-7500-...",
  "best_metric": 0.671,
  "best_trial_id": "0192f24c-bce0-7800-...",
  "created_at": "2026-05-25T10:00:00Z",
  "started_at": "2026-05-25T10:00:01Z",
  "completed_at": "2026-05-25T10:08:32Z",
  "trials_summary": {"total": 100, "complete": 98, "failed": 2, "pruned": 0, "best_primary_metric": 0.671},
  "confidence": {
    "headline": {"metric": "ndcg", "value": 0.671, "k": 10, "n_queries": 200},
    "ci_95": {"low": 0.652, "high": 0.689, "method": "bootstrap_n1000", "n_samples": 200},
    "runner_up_gap": {"value": 0.012, "classification": "robust_plateau", "top10_within": 0.004, "runner_up_metric": 0.659},
    "late_trial_stddev": {"value": 0.008, "window_size": 20, "min_window_required": 10},
    "convergence": {"best_at_trial": 42, "total_trials": 100, "regime": "early_held"},
    "per_query_outcomes": {
      "improved": 137,
      "unchanged": 51,
      "regressed": 12,
      "comparison_against": "baseline",
      "top_regressors": [
        {"query_id": "0192f24c-bce0-7900-...", "query_text": "red shoes", "winner_score": 0.41, "comparison_score": 0.78, "delta": -0.37}
      ]
    }
  }
}
```

Non-auth failure example (from `backend/app/api/errors.py`):

```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "baseline_params must contain JSON-serializable primitives",
    "retryable": false
  }
}
```

Auth failure example: N/A — MVP1 has no auth.

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `confidence.per_query_outcomes.comparison_against` | `runner_up`, `baseline` | `backend/app/domain/study/confidence.py:114` (`ComparisonAgainst` Literal) | `ui/src/lib/enums.ts:83-87` (`COMPARISON_AGAINST_VALUES`); rendered in `ui/src/components/studies/confidence-panel.tsx:98,113` |
| `trials.is_baseline` | `true`, `false` (bool) | `backend/app/db/models/trial.py` (new column, FR-1) | `ui/src/lib/types.ts` (regenerated); filter chip in trials-table (FR-9) |

No new wire values introduced.

### 8.5 Error code catalog

No new error codes. The existing `VALIDATION_ERROR` (422) covers malformed `baseline_params` payloads.

## 9) Data model and state transitions

### New/changed entities

**Modified table: `studies`**
- Add `baseline_trial_id String(36) NULL` — denormalized "FK" to the baseline trial in this study (matches the `best_trial_id` pattern at study.py:99-103; not an enforced FK because the row is stamped post-creation by the orchestrator).

**Modified table: `trials`**
- Add `is_baseline BOOLEAN NOT NULL DEFAULT FALSE` — marker so the trials-listing UI / Optuna-RDB-join code paths can filter the baseline out.

**No new tables.**

### Required invariants

- For every `studies` row with `baseline_trial_id IS NOT NULL`, the referenced `trials` row exists, has `study_id = studies.id`, `is_baseline = TRUE`, AND `status = 'complete'`. Enforced at write time by the FR-12 service helper (single stamping path; no DB-level constraint because the FK isn't formal).
- For every `trials` row with `is_baseline = TRUE` AND `status = 'complete'`, the corresponding `studies` row converges to `baseline_trial_id = trials.id` once a stamping path runs (orchestrator fast-path in FR-2 OR worker self-stamp in FR-10). Briefly inconsistent during the wait phase of FR-2; converges within `_REPLENISH_TICK_S` after the trial reaches terminal OR at the worker's own commit time, whichever fires first. **Failed baseline trials (`is_baseline=TRUE AND status='failed'`) intentionally violate this — `baseline_trial_id` stays NULL by design per §4 principle "failed baseline must not fail the study".**
- A study has at most ONE **complete** baseline trial — enforced at the DB level by the partial unique index `uq_trials_study_baseline_complete` (FR-1). Failed baseline trials may coexist (e.g., one failure followed by a successful retry from a re-run, out of scope today); the partial index's `status = 'complete'` predicate scopes uniqueness to the canonical-success case only. **Resume-race guarantee**: orchestrator double-enqueue is prevented at three layers — (a) `_job_id=f"baseline:{study_id}"` Arq deduplication (FR-2 step 4); (b) the partial unique index on `(study_id) WHERE is_baseline AND status='complete'` (FR-1); (c) the FR-12 stamping helper's `WHERE baseline_trial_id IS NULL` predicate. Any one of the three would prevent corruption; all three in series make it impossible.
- Baseline `Trial` rows have `optuna_trial_number = -1` and `is_baseline = TRUE`. Optuna's RDB never queries these (it uses its own storage); any join from app `trials` to Optuna's RDB MUST filter `WHERE is_baseline = FALSE`.

### State transitions

No new state machines. The `Trial` rows for baseline use the existing `complete | failed | pruned` enum (CHECK constraint already in place).

### Idempotency/replay behavior

- The baseline-trial enqueue uses an explicit `trial_id` (UUIDv7) generated by the orchestrator. If `run_baseline_trial` retries due to Arq infrastructure failure (e.g., DB unreachable mid-INSERT), the worker checks for `(study_id, trial_id, is_baseline=TRUE)` and no-ops on existing terminal rows (mirrors the FR-1a clause in `run_trial`).
- The orchestrator's wait phase is idempotent — re-entering `start_study` for a study that already has a stamped `baseline_trial_id` skips FR-2 entirely and proceeds directly to the Optuna phase.
- A `resume_study` invocation after worker restart:
  - If a `Trial` row exists with `is_baseline=TRUE AND status='complete'` AND `baseline_trial_id IS NULL`: call `services.study_state.stamp_baseline_trial` (FR-12 enforces the precondition checks; idempotent via the `WHERE baseline_trial_id IS NULL` predicate).
  - If only failed/pruned baseline rows exist: skip baseline (per §4 principle; do NOT attempt a retry) and proceed to Optuna.
  - If no baseline row exists at all: run baseline from scratch via FR-2. The deterministic Arq `_job_id=f"baseline:{study_id}"` guarantees that re-enqueue is a no-op when an original baseline job is still queued/running (eliminating the double-baseline race that would otherwise occur if the orchestrator crashed between `enqueue_job` and `INSERT INTO trials`).

## 10) Security, privacy, and compliance

- **Threats**:
  - T1: `baseline_params` accepts arbitrary dict — could be used to log PII or secrets. **Mitigation**: Pydantic schema constrains to JSON primitives; the field is stored in `studies.config` JSONB, which already absorbs every other config knob. No NEW exposure.
  - T2: Baseline trial makes the same engine queries as Optuna trials — could leak unprivileged data if the operator has misconfigured cluster auth. **Mitigation**: Existing engine-adapter auth is unchanged; this feature does NOT add a new auth path. Same engine, same target, same query template.
  - T3: A long-running baseline trial could DoS the worker pool. **Mitigation**: FR-2 caps the orchestrator's wait at `min(600, max(60, trial_timeout_s + 30))` seconds (formula in FR-2 step 5); the worker honors `studies.config.trial_timeout_s` directly. Failed baselines don't fail the study (principle in §4); late completions self-stamp via FR-10 + FR-12 without blocking Optuna.
- **Controls**: All existing controls (per-trial timeout, qrels-loader sanitization, prompt redaction in logs) apply unchanged.
- **Secrets/key handling**: N/A — no new secrets.
- **Auditability**: N/A in MVP1 (audit_log lands at MVP2). Logged events: `baseline_skipped`, `baseline_failed`, `baseline_wait_timeout`, `baseline_stamped` — structlog only, not audit_log.
- **Data retention**: Baseline trial rows persist for the lifetime of the study (cascade-delete on study delete, same as Optuna trials).

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement**: No new navigation. All UX changes live in the existing study-detail page (`ui/src/app/studies/[id]/page.tsx`), the existing trials-table component, and the existing ConfidencePanel.
- **Labeling taxonomy**:
  - "Baseline trial" — the new is_baseline=TRUE row in the trials list.
  - "vs baseline" — the new ConfidencePanel label replacing "vs runner-up" when the data flips.
- **Content hierarchy**: ConfidencePanel renders the comparison label inline next to the per-query outcomes counts (lines 98 + 113 in confidence-panel.tsx) — no layout change.
- **Progressive disclosure**: Trial-listing UI defaults to filtering out the baseline row (FR-9). A "Show baseline trial" toggle/chip reveals it at the top of the table.
- **Relationship to existing pages**: Extends. No new pages.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| ConfidencePanel "vs baseline" label | "Compared against your production baseline — the no-tuning trial run with your declared `baseline_params` (or template defaults) before Optuna started." (`confidence.comparison_against` — UPDATE existing glossary entry) | `focus` on the InfoTooltip icon | `top` |
| ConfidencePanel "vs runner-up" label | Existing text retained: "Compared against the runner-up: the second-best trial in this study. Useful when no production baseline was configured." | `focus` | `top` |
| Trials-table "Baseline" badge | "A single non-Optuna trial run before Optuna started. Used as the comparison reference for the confidence outcomes." (new glossary key `trials.is_baseline`) | `hover` on the badge | `right` |
| Trials-table "Show baseline trial" toggle | "Show the one-time baseline trial inline with Optuna trials. Hidden by default because its trial number (-1) doesn't fit the Optuna sequence." | `hover` on the toggle | `top` |
| `baseline_params` form field (if surfaced in `feat_create_study_search_space_builder` modal — OQ-2) | "Optional: explicit params for the baseline trial. Leave blank to use the parent study's winner (or template defaults if no parent)." | inline helper | below field |

**Glossary keys to add to `ui/src/lib/glossary.ts`:**

- `trials.is_baseline` — new entry.
- `confidence.comparison_against` — REPLACE existing entry (line 676) with bi-state text that explains both wire values.

### Primary flows

1. **Operator creates a study with no `baseline_params`** (the most common case for studies forked from a digest followup): orchestrator resolves tier (d) parent_proposal config → enqueues baseline trial → waits → stamps `baseline_metric` + `baseline_trial_id` → Optuna runs → digest renders with `comparison_against="baseline"`. PR body shows `delta_pct`. Operator sees per-query regressors against THEIR PRODUCTION CONFIG.
2. **Operator manually creates a study with explicit `baseline_params`**: same as above but tier (b) fires. The resolved params are the operator's literal dict (e.g., `{"boost_title": 1.0}`).
3. **Operator creates a study with NO parent + NO baseline_params**: tier (a) fires (template defaults — middle-of-range). The baseline trial runs against the deterministic middle of every declared param.

### Edge/error flows

- **Baseline trial fails** (cluster unreachable, scorer crash, timeout): `Trial` row written with `status='failed'`, `is_baseline=TRUE`, `error=<message>`. `baseline_trial_id IS NULL`. Orchestrator proceeds. ConfidencePanel + auto-followup gate fall back to runner-up / first-decile-max.
- **Operator-supplied `baseline_params` contains a key NOT in the template's `declared_params`**: the `adapter.render()` call ignores extraneous keys (verified at the adapter Protocol level — render's contract is "use what's declared"). No error.
- **Operator-supplied `baseline_params` is missing a key the template requires**: `adapter.render()` raises `KeyError` or similar template-render error. The baseline trial fails with a clear error message. Treated like any other baseline failure (fall back). The operator can re-run the study with a fixed `baseline_params`.
- **`parent_proposal.study_trial_id` points at a deleted trial** (cascade race): tier (d) resolver logs + falls through to tier (c) → tier (b) → tier (a). No hard error.
- **Worker restart mid-baseline-trial**: `resume_study` re-enters orchestrator; if `baseline_trial_id IS NULL` AND no `is_baseline=TRUE` trial row exists for this study, baseline is re-run. If a row exists, the orchestrator just re-stamps (idempotent).
- **Empty `declared_params`** (template has zero params): resolver returns `None`; baseline skipped.

## 12) Given/When/Then acceptance criteria

### AC-1: orchestrator runs baseline trial first when `parent_proposal_id` is set
- Given a parent proposal exists with a known `study_trial_id` pointing at a trial with `params={"boost_title": 2.0}`
- And the operator creates a study with `parent.proposal_id = <id>, parent.followup_index = 0`
- When `start_study` runs
- Then the first row inserted into `trials` for this study has `is_baseline=TRUE`, `params={"boost_title": 2.0}`, `optuna_trial_number=-1`
- And `studies.baseline_trial_id` is set to that trial's ID
- And `studies.baseline_metric` is set to that trial's `primary_metric`
- And the row is inserted BEFORE any Optuna trial is enqueued.

### AC-2: orchestrator falls back to template defaults when no parent + no `baseline_params`
- Given a study has `parent_study_id=NULL`, `parent_proposal_id=NULL`, `config={"baseline_params": null}` (or absent)
- And `search_space.params = {"boost_title": {"type": "float", "low": 0.5, "high": 10.0}, "operator": {"type": "categorical", "choices": ["and", "or"]}}`
- When `start_study` runs
- Then the baseline trial's `params = {"boost_title": 5.25, "operator": "and"}` (middle of range for float `(0.5 + 10.0) / 2 = 5.25`; lower-midpoint categorical via `(len-1) // 2 = 0` → `"and"`)
- And `studies.baseline_trial_id` is stamped on completion.

### AC-3: failed baseline does NOT fail the study
- Given a study is created
- And the engine adapter raises `ClusterUnreachableError` on the baseline trial's `search_batch`
- When `start_study` runs
- Then a `Trial` row exists with `is_baseline=TRUE, status='failed', error='cluster unreachable: <details>'`
- And `studies.baseline_trial_id IS NULL`
- And `studies.baseline_metric IS NULL`
- And the Optuna polling loop proceeds and trials run normally.

### AC-4: confidence analytics switch to baseline comparison when baseline is set
- Given a study has `baseline_trial_id` set to a complete trial with `per_query_metrics={"q1": {"ndcg@10": 0.4}, "q2": {"ndcg@10": 0.6}}`
- And the winner trial has `per_query_metrics={"q1": {"ndcg@10": 0.7}, "q2": {"ndcg@10": 0.5}}`
- And the per-query `ndcg` threshold is `0.01` (from `REGRESSOR_THRESHOLDS` at `backend/app/domain/study/confidence.py:61-67` — shipped in Phase 1, `feat_pr_metric_confidence` D-2)
- When `compute_study_confidence` runs
- Then `per_query_outcomes.comparison_against == "baseline"`
- And `per_query_outcomes.improved == 1` (q1: 0.7 vs 0.4, +0.3 > threshold)
- And `per_query_outcomes.regressed == 1` (q2: 0.5 vs 0.6, -0.1 < -threshold).

### AC-5: confidence falls back to runner-up when baseline_trial_id is NULL
- Given a study has `baseline_trial_id=NULL`
- And the runner-up trial has `per_query_metrics` populated
- When `compute_study_confidence` runs
- Then `per_query_outcomes.comparison_against == "runner_up"`.

### AC-6: confidence falls back to runner-up when baseline trial has no per_query_metrics
- Given a study has `baseline_trial_id` set BUT the referenced trial has `per_query_metrics IS NULL` (e.g., the baseline failed mid-score)
- When `compute_study_confidence` runs
- Then `per_query_outcomes.comparison_against == "runner_up"`.

### AC-7: auto-followup gate uses baseline_metric when set
- Given parent study has `best_metric=0.65, baseline_metric=0.55`
- When `evaluate_chain_gate(parent, complete_trials, epsilon=0.005)` runs
- Then `outcome.lift == 0.10` (computed as best_metric - baseline_metric, not first_decile_max)
- And `outcome.decision == ChainGateDecision.ENQUEUE` (lift > epsilon).

### AC-8: auto-followup gate falls back to first-decile-max when baseline_metric is NULL
- Given parent study has `best_metric=0.65, baseline_metric=NULL, objective.direction="maximize"`
- And `compute_first_decile_extremum(complete_trials, direction="maximize") == 0.45`
- When `evaluate_chain_gate(parent, complete_trials, direction="maximize")` runs
- Then `outcome.lift == 0.20` (computed against first decile, existing FR-2a behavior)
- And `outcome.first_decile_extremum == 0.45`.

### AC-9: `StudyDetail` response exposes `baseline_trial_id`
- Given a study has `baseline_trial_id="0192...-7500"`
- When `GET /api/v1/studies/{id}` is called
- Then the response body contains `"baseline_trial_id": "0192...-7500"` (or `null` when not set).

### AC-10: trials-listing UI hides baseline row by default
- Given a study has 100 Optuna trials + 1 baseline trial
- When the operator opens `/studies/{id}` and the trials table loads
- Then 100 rows are visible
- And no row shows `optuna_trial_number=-1`
- When the operator clicks "Show baseline trial" toggle
- Then 101 rows are visible
- And the baseline row appears at the top with a "Baseline" badge.

### AC-11: digest user prompt renders correct comparison_against
- Given a study has `baseline_trial_id` set and both winner + baseline have `per_query_metrics`
- When the digest worker renders the user prompt
- Then the `<per_query_outcomes>` block contains `comparison_against: baseline`.

### AC-12: PR body emits "vs baseline" in confidence section
- Given a study has confidence with `comparison_against="baseline"` and 12 regressors
- When `open_pr` worker renders the PR body
- Then the body contains a line like `12 regressed (vs baseline)`.

### AC-13: migration round-trips cleanly
- Given the migration `0020_studies_baseline_trial` is applied (`alembic upgrade head`)
- When `alembic downgrade -1` is run
- Then both `studies.baseline_trial_id` and `trials.is_baseline` columns are removed
- And the schema matches the state at `0019_digests_suggested_followups_jsonb`
- When `alembic upgrade head` is re-run
- Then both columns are restored
- And the migration is idempotent on re-run with the columns already present (`alembic upgrade head` twice does not raise).

### AC-14: `baseline_params` operator override resolves to tier (b)
- Given a study has `parent_study_id=NULL, parent_proposal_id=NULL, config.baseline_params={"boost_title": 1.2}`
- When `start_study` runs and `resolve_baseline_params` is called
- Then the resolver returns `{"boost_title": 1.2}` (not the template midpoint).

### AC-16: late-completing baseline trial self-stamps via worker (FR-10 + FR-12)
- Given an orchestrator wait phase times out at `wait_s` seconds with `baseline_trial_id IS NULL`
- And the orchestrator proceeds to Optuna phase
- And the baseline `run_baseline_trial` job eventually completes successfully at `wait_s + 30` seconds
- When the worker calls `services.study_state.stamp_baseline_trial`
- Then `studies.baseline_trial_id` becomes set to the trial ID
- And `studies.baseline_metric` becomes set to the trial's `primary_metric`
- And the next `compute_study_confidence` call (e.g., from `GET /api/v1/studies/{id}`) renders `comparison_against = "baseline"`.

### AC-17: aggregate_trials_summary excludes baseline trial (FR-11)
- Given a study has 5 Optuna trials (`is_baseline=FALSE`) and 1 baseline trial (`is_baseline=TRUE, status='complete'`)
- And the baseline trial has the highest `primary_metric` (an edge case where the operator's production config beats every Optuna trial)
- When `aggregate_trials_summary(db, study_id)` is called
- Then `summary.total == 5`, `summary.complete == 5`
- And `summary.best_trial_id` points at the best Optuna trial (NOT the baseline)
- And `summary.best_primary_metric` is the best Optuna trial's metric.

### AC-18: evaluate_chain_gate is direction-aware (FR-5 minimize)
- Given a study has `objective={"metric": "ndcg", "direction": "minimize"}` (hypothetical — minimize objectives are wire-supported per `schemas.py:226` even though MVP1 examples are maximize-only)
- And `parent.best_metric = 0.30, parent.baseline_metric = 0.50` (lower is better, winner beats baseline by 0.20)
- When `evaluate_chain_gate(parent, complete_trials, direction='minimize', epsilon=0.005)` runs
- Then `outcome.lift == 0.20` (direction-normalized — always positive when winner beats baseline)
- And `outcome.decision == ChainGateDecision.ENQUEUE`.

### AC-15: baseline trial's `_compute_metric_delta` populates `delta_pct`
- Given `study.baseline_metric=0.50, study.best_metric=0.60`
- When `_compute_metric_delta(study)` runs (existing code path, no change)
- Then the result is `{"ndcg@10": {"baseline": 0.50, "achieved": 0.60, "delta_pct": 20.0}}`.

## 13) Non-functional requirements

- **Performance**: Baseline trial adds at most one engine round-trip per study creation — typically 1–5 seconds. Acceptable since study creation is operator-driven (not user-facing latency).
- **Reliability**: Failed baselines do not fail studies. The orchestrator's wait timeout (150s) prevents indefinite blocking.
- **Operability**: New structured-log events: `baseline_skipped`, `baseline_failed`, `baseline_stamped`, `baseline_wait_timeout`. Operators can grep these to triage. Add a 1–2 line entry in the study-lifecycle runbook.
- **Accessibility/usability**: The "Show baseline trial" toggle uses the existing `<Switch>` primitive in `ui/src/components/ui/` — accessibility properties inherit.

## 14) Test strategy requirements (spec-level)

- **Unit tests** (`backend/tests/unit/`) — all pure-Python, mocked externals, no DB:
  - `domain/study/test_baseline_resolver.py` — 4-tier fallback resolver, every tier transition, empty params handling. Inputs are `SimpleNamespace` stand-ins; no DB session. **Mocked**.
  - `domain/study/test_confidence.py` — extend with baseline branch tests for `compute_study_confidence` (AC-4, AC-5, AC-6). Pure-Python — pass `SimpleNamespace` trial rows. **Mocked**.
  - `domain/study/test_auto_followup.py` — extend with baseline branch tests for `evaluate_chain_gate` (AC-7, AC-8) AND direction-awareness tests for the minimize objective case (FR-5). **Mocked**.
  - `workers/test_baseline_trial.py` — `run_baseline_trial` happy path + failure path. Adapter/score/qrels-loader mocked via `monkeypatch`. **Mocked**.
  - `services/test_stamp_baseline_trial.py` — service helper FR-12: stamp success, stamp idempotent (already-stamped no-ops), stamp with invalid trial state raises. **Mocked**.
- **Integration tests** (`backend/tests/integration/`) — real Postgres + real Redis + real Arq workers (service containers in CI; `make test-integration` locally). Adapter HTTP calls mocked via `monkeypatch` per existing convention:
  - `test_orchestrator_baseline_trial.py` — **REAL BACKEND**: real Postgres + Arq orchestrator + Arq baseline worker. Studies create → baseline enqueues → terminal row written → orchestrator stamps → Optuna trials enqueue. Adapter mocked at the `search_batch` boundary (returns fixed hits). Asserts AC-1, AC-2, AC-3.
  - `test_baseline_late_completion_stamp.py` — **REAL BACKEND**: simulate the wait-timeout case by forcing the worker to delay until after the orchestrator's wait expires (`asyncio.sleep` injected via env-var fault seam in `run_baseline_trial`). Asserts the worker's FR-10 step 7 self-stamp lands the field even after orchestrator's wait gave up.
  - `test_studies_api_baseline.py` — **REAL BACKEND**: `GET /api/v1/studies/{id}` exposes `baseline_trial_id` (AC-9).
  - `test_studies_api_confidence_baseline.py` — **REAL BACKEND**: seeds a study with a complete baseline trial + winner trial both having `per_query_metrics`; asserts API confidence shape with `comparison_against='baseline'` (AC-4, AC-5, AC-6).
  - `test_create_study_baseline_params.py` — **REAL BACKEND**: `POST /api/v1/studies` with explicit `config.baseline_params`; assert it persists into `studies.config` and the orchestrator picks tier (b) (AC-14).
  - `test_baseline_migration_round_trip.py` — **REAL BACKEND**: real Alembic against real Postgres. Upgrade/downgrade/upgrade (AC-13).
  - `test_baseline_resume.py` — **REAL BACKEND**: orchestrator restart mid-baseline-trial resumes correctly (uses Arq job re-enqueue + the `resume_study` path).
  - `test_trials_aggregate_excludes_baseline.py` — **REAL BACKEND**: insert a study with 5 Optuna trials + 1 baseline trial; assert `aggregate_trials_summary` returns `total=5`, NOT 6 (FR-11 invariant).
- **Contract tests** (`backend/tests/contract/`):
  - `test_pr_body_confidence_section.py` — add new fixture with `baseline_trial_id` set; assert PR body contains "vs baseline" (AC-12). Existing 2 fixtures retained for `runner_up` regression coverage.
  - `test_study_detail_baseline_trial_id_field.py` — assert `StudyDetail.baseline_trial_id` is in the response schema and is `string | null`.
- **E2E tests** (`ui/tests/e2e/`) — real-backend (no `page.route()` mocking per CLAUDE.md):
  - Extend existing `studies-flow.spec.ts` (or whichever study-detail E2E file exists — plan-gen verifies). Test setup: seed the study via API (`page.request.post('/api/v1/studies', { data: { ..., config: { ..., baseline_params: {...} } } })`) since OQ-2 defers surfacing `baseline_params` in the create-study UI. Then UI assertions: (a) wait for completion, (b) navigate to study detail, (c) assert ConfidencePanel renders "vs baseline" label, (d) click "Show baseline trial" toggle, (e) assert baseline row appears with "Baseline" badge.

**Test coverage gate**: 80% backend (current MVP1 standard). New code in `baseline_resolver.py` + `workers/baseline.py` MUST be ≥ 90% covered (no fallback-only branches; every path is testable).

## 15) Documentation update requirements

- **`docs/01_architecture/data-model.md`**: Update §"studies" with `baseline_trial_id` column; update §"trials" with `is_baseline` column.
- **`docs/01_architecture/optimization.md`** (if exists): add a 2-3 sentence note about the baseline trial being non-Optuna.
- **`docs/03_runbooks/study-lifecycle-debugging.md`** (if exists; otherwise the runbook for `feat_study_lifecycle`): document the 4 new log event types (`baseline_skipped`, `baseline_failed`, `baseline_stamped`, `baseline_wait_timeout`) and what each implies.
- **`prompts/digest_narrative.system.md`**: per FR-7.
- **`architecture.md`** (root): no change.
- **`state.md`**: update once feature merges (post-impl, not pre-impl).
- **`CLAUDE.md`**: no new absolute rules. The "don't bypass orchestrator" rule already covers `run_baseline_trial`'s no-Optuna interaction.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout**: None. The feature is gated by the presence of the migration; pre-migration studies are unaffected.
- **Migration/backfill expectations**: Forward-only. No backfill. Existing studies stay `baseline_trial_id IS NULL` permanently (would require a re-study to populate retroactively, which is operationally cheaper than a migration backfill).
- **Operational readiness**: The orchestrator's wait phase is the new failure surface. The runbook update (§15) documents the four log events.
- **Release gate**: Standard MVP1 CI green + 80% coverage + GPT-5.5 cross-model review + Gemini PR adjudication.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-13 | Story 1.1 (migration) | `test_baseline_migration_round_trip.py` | data-model.md §studies + §trials |
| FR-2 | AC-1, AC-2, AC-3 | Story 1.2 (orchestrator) + Story 1.4 (resume) | `test_orchestrator_baseline_trial.py`, `test_baseline_resume.py` | runbook |
| FR-3 | AC-1, AC-2, AC-14 | Story 1.3 (resolver) | `test_baseline_resolver.py` | (none) |
| FR-4 | AC-4, AC-5, AC-6 | Story 2.1 (confidence) | `test_confidence.py`, `test_studies_api_confidence_baseline.py` | (none) |
| FR-5 | AC-7, AC-8, AC-18 | Story 2.2 (auto_followup gate) | `test_auto_followup.py` | auto-followup runbook |
| FR-6 | AC-14 | Story 1.5 (request schema) | `test_create_study_baseline_params.py` | (none) |
| FR-7 | AC-11 | Story 2.3 (system prompt) | snapshot test in `test_digest_prompt_render.py` | digest_narrative.system.md (the prompt itself IS the doc) |
| FR-8 | AC-9 | Story 2.4 (StudyDetail schema) | `test_study_detail_baseline_trial_id_field.py` | (none) |
| FR-9 | AC-10 | Story 3.1 (frontend trials-table filter) | E2E test | (none) |
| FR-10 | AC-1, AC-3, AC-16 | Story 1.4 (worker) | `test_baseline_trial.py`, `test_baseline_late_completion_stamp.py` | (none) |
| FR-11 | AC-17 | Story 1.6 (repo filter updates) | `test_trials_aggregate_excludes_baseline.py` + extensions of existing aggregate tests | (none) |
| FR-12 | AC-1, AC-16 | Story 1.5 (service helper) | `test_stamp_baseline_trial.py` | (none) |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-18) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Backend coverage ≥ 80% global; new files (`baseline_resolver.py`, `workers/baseline.py`) ≥ 90%.
- [ ] Documentation updates per §15 are merged.
- [ ] Rollout gates from §16 are satisfied.
- [ ] No open questions remain in §19.
- [ ] Migration round-trips cleanly via `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
- [ ] The PR body of the next study run against a `baseline_params`-equipped study shows non-None `delta_pct` (manual smoke test).

## 19) Open questions and decision log

### Open questions

- **OQ-1: Default filter behavior for the baseline trial in the trials-listing UI.** Locked: FILTER OUT by default (FR-9), with a "Show baseline trial" toggle to reveal. The baseline trial's `optuna_trial_number=-1` would confuse the Optuna trial-number ordering if shown inline. **Resolution**: confirmed FR-9 default = filter out.
- **OQ-2: Surface `baseline_params` in the create-study UI?** The `feat_create_study_search_space_builder` modal is the natural place. Locked decision: **defer to a follow-up idea** — `chore_create_study_baseline_params_ui` will be captured if the operator's first-time discovery of `baseline_params` requires UI affordance. For MVP, `baseline_params` is an advanced operator override accessible only via the API + the chat agent's `create_study` tool.
- **OQ-3: Should the digest worker LLM call know about baseline failures explicitly?** When `baseline_trial_id` is NULL because the baseline failed, should `<baseline_vs_achieved>` say "N/A (no baseline trial)" or "N/A (baseline trial failed: <reason>)"? Locked: the current "N/A (no baseline trial)" text is sufficient; the operator can dig into the failed `Trial` row if they want details. **Resolution**: no change to the digest user prompt for this edge.

All open questions resolved before plan-gen.

### Decision log

- **2026-05-25 — D-1**: Baseline trial uses real `Trial` rows with `is_baseline=TRUE` and `optuna_trial_number=-1` rather than a separate `baseline_trials` table. Rationale: keeps cascade-delete semantics simple, reuses every existing per-trial column (params, primary_metric, metrics, per_query_metrics, error, started_at, ended_at), and Optuna never queries the app trials table (it uses its own RDB), so the negative sentinel cannot pollute Optuna's state.
- **2026-05-25 — D-2**: Baseline-params resolver uses a 4-tier fallback (parent_proposal → parent_study → operator-supplied → template defaults), matching the operator's "what did I change?" mental model. Rationale: for digest-executable followups (the most common case once `feat_auto_followup_studies` chains start landing), the operator's mental baseline IS the parent proposal's config. Falling all the way through to template defaults is the safety net.
- **2026-05-25 — D-3**: Auto-followup gate switches from `first_decile_max` to `parent.baseline_metric` when the latter is set. Rationale: the `auto_followup.py:9-11` module docstring explicitly promised this. Backward-compatible because `parent.baseline_metric` is NULL for every study created before this feature lands.
- **2026-05-25 — D-4**: Baseline trial runs synchronously before Optuna, not in parallel. Rationale: a one-shot fast trial (~1-5s) doesn't need parallelism, and serial ordering simplifies the trial-counter / `_count_in_flight` invariants the orchestrator already depends on.
- **2026-05-25 — D-5**: Baseline trials use `optuna_trial_number = -1` as a sentinel filler for the NOT-NULL column; `is_baseline=TRUE` is the canonical discriminator. Rationale: the column is `NOT NULL` (declared in `feat_study_lifecycle` Phase 1) and Optuna's RDB never reads the app trials table. **Idempotency**: `run_trial` keeps its existing `(study_id, optuna_trial_number)` idempotency (Optuna trial numbers are always non-negative); `run_baseline_trial` uses `trial_id`-based idempotency (the orchestrator pre-generates a UUIDv7 in FR-2 and passes it as a job argument). The two code paths are disjoint and cannot collide.
- **2026-05-25 — D-6**: Failed baseline trials do not fail the study. Rationale: the baseline is informational. Failing the study because production-config-baseline failed would be a regression vs today (where studies run fine with no baseline). The fall-back paths in FR-4 + FR-5 handle missing baseline data gracefully.
- **2026-05-25 — D-7**: `baseline_params` lives in `studies.config` JSONB, not a top-level `studies.baseline_params` column. Rationale: every other study-tunable lives in `config`; growing the top-level schema for an optional advanced override is debt.
- **2026-05-25 — D-8**: Baseline trial uses the same per-trial timeout as Optuna trials (`studies.config.trial_timeout_s` or `Settings.studies_default_timeout_s` fallback). Rationale: no second knob.
- **2026-05-25 — D-9**: No backfill. Existing studies stay `baseline_trial_id IS NULL`. Rationale: backfilling would require re-running the engine queries for every historical study, which has runtime cost without comparable value (operators care about NEW studies, not historical confidence retroactively).
- **2026-05-25 — D-10**: Per-trial timeout for baseline is honored as-is (no separate baseline timeout). Rationale: same as D-8 — single knob, no debt.
- **2026-05-25 — D-11**: Audit-log emission is deferred. Rationale: MVP1 has no audit_log table; will be a sweep at MVP2.
- **2026-05-25 — D-12** (added after GPT-5.5 cycle-1 review F2/F14): The baseline-trial stamping path is single-chokepoint via `services.study_state.stamp_baseline_trial` (FR-12). The orchestrator's fast-path stamp (FR-2 step 7), the worker's self-stamp (FR-10 step 7), and the `resume_study` re-stamp all route through the same helper. Rationale: prevents three slightly-different UPDATE statements drifting; matches the existing `services/study_state.py` pattern; positions us for audit-event emission at MVP2.
- **2026-05-25 — D-13** (added after GPT-5.5 cycle-1 review F10): The orchestrator's wait phase is best-effort — if it times out, the `run_baseline_trial` worker is left running and stamps the study on its own success via FR-10/FR-12. Rationale: cancelling the in-flight Arq job is harder than letting it self-stamp; the operator gets baseline data eventually rather than losing it; if the worker never completes, the worker layer's own per-trial timeout fires and the row lands as `status='failed'` (which we already handle gracefully per §4 principle).
- **2026-05-25 — D-14** (added after GPT-5.5 cycle-1 review F15): `evaluate_chain_gate` becomes direction-aware in this feature. Rationale: we're touching the same lines anyway for the baseline switch; closing the latent minimize-direction bug in `feat_auto_followup_studies` while we're here is cheap (one extra `direction` argument + a sign flip). Rejecting "implement-over-defer" guidance in CLAUDE.md would have required capturing as `bug_auto_followup_minimize_direction` — but that's strictly worse than inlining the fix.
- **2026-05-25 — D-15** (added after GPT-5.5 cycle-1 review F8): The trials-aggregate read paths (`aggregate_trials_summary`, `list_top_trials`, `list_complete_trials_for_confidence`) ALL filter `is_baseline = FALSE` inline (FR-11). Rationale: operators NEVER want baseline in these aggregates — adding a kwarg `include_baseline=False` adds API surface without value, and an unfiltered query would corrupt confidence + auto-followup downstream.
- **2026-05-25 — D-16** (added after GPT-5.5 cycle-3 review F1): Double-baseline-on-resume race is prevented by three independent layers: (a) Arq `_job_id` deduplication (FR-2 step 4); (b) partial unique index `uq_trials_study_baseline_complete` (FR-1); (c) FR-12 stamping helper's `WHERE baseline_trial_id IS NULL` predicate. Rationale: a single layer would be sufficient in steady-state, but defense in depth makes the invariant hold across Arq driver changes (job-id format may change), partial-index maintenance (rebuilds), and edge-case race windows. The marginal complexity is one partial index + one `_job_id` argument.
