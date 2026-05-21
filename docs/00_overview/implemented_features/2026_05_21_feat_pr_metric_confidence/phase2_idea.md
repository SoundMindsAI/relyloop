# Phase 2 — Baseline-trial computation for `feat_pr_metric_confidence`

**Date:** 2026-05-21
**Status:** Idea — deferred from Phase 1 of [`feat_pr_metric_confidence`](feature_spec.md) at spec-gen time (Decision D8 in §19).
**Origin:** [`feat_pr_metric_confidence/feature_spec.md`](feature_spec.md) §3 Out of scope + §19 Decision log D8. Phase 1 ships per-query analytics against the runner-up #2 trial as the comparison reference. Phase 2 adds a true production-baseline comparison.

**Depends on:** Phase 1 of `feat_pr_metric_confidence` must be merged first. Phase 2 is purely additive — no migration to undo, no API contract break.

## Problem

`studies.baseline_metric` exists as a column on the `studies` table (declared in `feat_study_lifecycle` Phase 1, [`backend/app/db/models/study.py:76`](../../../../backend/app/db/models/study.py#L76)) with the docstring "single non-Optuna trial run before Optuna starts; populated by the orchestrator (Phase 2)." However, **the orchestrator was never updated to populate this column** — `grep -rn "baseline_metric *=" backend/workers/ backend/app/services/` returns zero write sites. In production, `study.baseline_metric` is always `None`, and the PR body's `## Metric delta` section shows `baseline=None → achieved=X` with no `delta_pct`.

Phase 1 of `feat_pr_metric_confidence` ships per-query analytics that compare the winner against the **runner-up #2 trial** instead of a true baseline. That comparison answers "is the winner robust or fragile vs other tried configs?" but does NOT answer "does this config regress queries that the operator's current production search behavior gets right?" — which is the more directly actionable approver question.

Phase 2 closes this gap by:
1. Implementing the deferred orchestrator work — run a single non-Optuna baseline trial before Optuna starts, using the operator's current production query-template params as the "baseline" configuration.
2. Persisting that baseline as a real `Trial` row with its `per_query_metrics` populated.
3. Adding a new denormalized FK column `studies.baseline_trial_id String(36) NULL` so reads can fetch the baseline trial efficiently.
4. Switching `compute_study_confidence` to emit `comparison_against = "baseline"` when `study.baseline_trial_id IS NOT NULL`, falling back to `"runner_up"` otherwise.

## Why deferred from Phase 1

- **Cross-subsystem.** Touches the orchestrator (a new "run baseline first" code path), the trials worker (no change — baseline is just another Trial row), the studies schema (new column + migration), the digest worker prompt (potentially: distinguish "baseline" vs "runner_up" in the narrative framing), and the operator UX (what does the baseline config actually MEAN — is it the current template params with default values? the previous study's winning params? a no-op?).
- **Real product-design surface.** The semantics of "baseline" need a spec-shaped decision. Options include:
  - **(a) Template defaults.** The baseline trial uses the query template's `declared_params` with each param's middle-of-range value (`(low + high) / 2` for floats, the median choice for categoricals). Simple, deterministic, but may not reflect the operator's actual production config.
  - **(b) Operator-supplied baseline.** The create-study request body gains an optional `baseline_params: dict[str, Any] | None` field. When provided, the orchestrator runs a baseline trial with those params before Optuna starts. When absent, no baseline runs (status quo).
  - **(c) Previous study's winner.** If the study has `parent_study_id` (fork lineage, MVP2 surface), the baseline is the parent's winning trial's params. When no parent, no baseline runs.
- **Statistical design surface.** Once baseline data exists, the per-query delta semantics flip from "vs runner-up" to "vs production behavior" — the regressor framing changes from "winner sacrificed this query to other tried configs" to "winner makes this query worse than production." Both are valid signals; spec needs to lock which is the default surface (likely baseline when available, runner-up otherwise).
- **Compounding orchestrator complexity.** Adding a non-Optuna trial path means the orchestrator needs to (a) not increment Optuna's trial counter for the baseline, (b) handle baseline-trial failure differently than Optuna trial failure (a failed baseline should NOT block the study; just skip the comparison surface), (c) handle the baseline-trial timeout window separately from per-trial Optuna timeouts.

## Proposed capabilities

### Capability 1 — Migration: add `studies.baseline_trial_id`

- Alembic migration `00NN_studies_baseline_trial_id` (next available revision after Phase 1's `0015`).
- Schema: `baseline_trial_id String(36) NULL`. Not a formal FK (per the same rationale as `best_trial_id` in [`study.py:80-84`](../../../../backend/app/db/models/study.py#L80) — orchestrator stamps it after baseline trial completes; no enforce-at-DB constraint).
- Reversible `downgrade()` drops the column. Round-trip verified.
- No backfill — existing studies stay `baseline_trial_id IS NULL` and continue to show `comparison_against = "runner_up"` per Phase 1 fallback.

### Capability 2 — Orchestrator runs baseline trial before Optuna

- In [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) `start_study`, before entering the Optuna trial-enqueue loop:
  1. Resolve the baseline params (per the locked design decision from Phase 2 spec — options (a/b/c) above).
  2. If baseline params are non-empty, enqueue a single `run_baseline_trial(study_id, params)` Arq job. Wait for it to complete (synchronous within the start_study transaction OR await via Optuna's ask/tell sync mechanism — TBD by Phase 2 plan).
  3. Stamp `study.baseline_trial_id = <new_trial.id>` and `study.baseline_metric = <trial.primary_metric>`.
  4. Proceed to the Optuna loop.
- A new worker function `run_baseline_trial` mirrors `run_trial` but does NOT call `study.ask()` / `study.tell()` — it just renders the template with the baseline params, runs the engine query, scores via `pytrec_eval`, and persists a Trial row with `optuna_trial_number = -1` (sentinel) OR some other distinguishing marker. `per_query_metrics` is persisted just like Phase 1.
- Failed baseline trial: log + proceed with the study; `baseline_trial_id` stays NULL; comparison falls back to runner-up #2.

### Capability 3 — `compute_study_confidence` switches comparison source

- One-line change in `backend/app/domain/study/confidence.py`:
  - When `study.baseline_trial_id IS NOT NULL` AND that trial row exists AND has `per_query_metrics`: use it as the comparison reference; emit `per_query_outcomes.comparison_against = "baseline"`.
  - Otherwise: fall back to runner-up #2 (Phase 1 behavior); emit `comparison_against = "runner_up"`.
- The `ConfidenceShape` Literal `comparison_against: Literal["runner_up", "baseline"]` already exists from Phase 1 — Phase 2 just unlocks the second value.
- No API contract change; no migration to undo.

### Capability 4 — UI label switching

- ConfidencePanel reads `confidence.per_query_outcomes.comparison_against` and renders either "vs runner-up" or "vs baseline" as the label on the outcome chips + regressor table heading.
- Tooltip on the label distinguishes the two semantics ("Runner-up: the second-best trial in this study. Baseline: a no-tuning trial run with your production template params before Optuna started.").

### Capability 5 — Digest narrative prompt extension

- The `<per_query_outcomes>` block in `digest_narrative.user.jinja` already emits `comparison_against` from Phase 1 — no template change. The system prompt's confidence-framing guidance may benefit from a sentence about how the narrative should call out "regressed vs production baseline" differently from "regressed vs runner-up" — but that's a UX call for Phase 2 spec.

## Scope signals

- **Backend:** Migration (1 column) + orchestrator change (~50-100 LOC) + new `run_baseline_trial` worker (~150 LOC mirroring `run_trial`) + 1-line change in `compute_study_confidence` + new error paths (failed baseline) + tests at every layer. ~500-800 LOC.
- **Frontend:** ~20 LOC to switch the label in `<ConfidencePanel>` + tooltip text + 1 new test case.
- **Migration:** 1 additive Alembic migration adding `studies.baseline_trial_id`.
- **Config:** None.
- **Audit events:** N/A in MVP1; MVP2 may want to audit baseline_trial creation as part of the study lifecycle events.
- **New dependencies:** None.

## Relationship to other work

- **Builds on** [`feat_pr_metric_confidence`](feature_spec.md) (Phase 1 of this feature). Phase 1 must merge first so the `ConfidenceShape` and `compute_study_confidence` infrastructure exists for Phase 2 to extend.
- **Composes with** [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/feature_spec.md) — Phase 2 retroactively implements the "Phase 2" baseline-trial work that the study_lifecycle spec promised but deferred. Now it's a separate feature with its own spec cycle.
- **Composes with** [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/feature_spec.md) — if Phase 2 picks design option (b) (operator-supplied baseline_params), the create-study modal gains a new optional input. The search-space builder is the natural place for that input.

## Open questions for /spec-gen (Phase 2)

1. **Baseline semantics** — Which of (a) template defaults, (b) operator-supplied, (c) parent-study winner is the locked default? Recommended: (b) operator-supplied with a fallback to (a) template defaults when not provided.
2. **Synchronous vs async baseline** — Does the orchestrator BLOCK on the baseline trial completing before enqueueing Optuna trials, or does it dispatch both in parallel? Recommended: synchronous (the baseline is a one-shot fast trial; Optuna can wait the extra 2-5 seconds).
3. **Baseline-trial failure handling** — Does a failed baseline fail the study OR proceed without baseline data? Recommended: proceed without (the baseline is informational, not load-bearing; failing the entire study because production-config-baseline failed would be a regression).
4. **`optuna_trial_number = -1` sentinel** — How does the existing trial-listing UI handle a trial with `optuna_trial_number = -1`? The Optuna RDB may not tolerate negative trial numbers. Alternative: a separate `baseline_trials` table; or a `trials.is_baseline` boolean. Recommended: investigate during Phase 2 spec — likely a `trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE` flag is cleaner than a sentinel.

## Trigger to start Phase 2

Phase 2 unlocks once:
- Phase 1 (`feat_pr_metric_confidence`) is merged to main.
- Operator feedback on the runner-up comparison surface confirms that production-baseline comparison would be more valuable (i.e., operators ask for "compare to what we currently ship, not just other tried configs").
- A Phase 2 design call decides between the three baseline semantics options above.
