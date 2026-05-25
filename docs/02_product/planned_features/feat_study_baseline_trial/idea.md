# Baseline-trial computation — fill in the deferred Phase 2 of `feat_pr_metric_confidence`

**Date:** 2026-05-22 (originally drafted 2026-05-21 as `phase2_idea.md` inside `2026_05_21_feat_pr_metric_confidence/`; split to this dedicated planned folder 2026-05-22 so it surfaces in `/pipeline --status`.)
**Status:** Idea — deferred Phase 2 work from `feat_pr_metric_confidence` (Phase 1 merged 2026-05-21 as PR #180 squash `d0a8358`).
**Priority:** P2
**Origin:** [`feat_pr_metric_confidence/feature_spec.md`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) §3 Out of scope + §19 Decision log D8. Phase 1 ships per-query analytics against the runner-up #2 trial as the comparison reference. Phase 2 adds a true production-baseline comparison.

**Depends on:** Phase 1 of `feat_pr_metric_confidence` (PR #180) — merged. Phase 2 is purely additive — no migration to undo, no API contract break.

**Still-needed verification (re-confirmed 2026-05-25 against `main` HEAD `ba224865`):**
- `studies.baseline_metric` column exists at [`backend/app/db/models/study.py:95`](../../../../backend/app/db/models/study.py#L95). No code path WRITES to it during a study workflow (`grep -rn 'baseline_metric' backend/workers backend/app/services` returns only **read** sites: [`digest.py:517`](../../../../backend/workers/digest.py#L517) reads it into a local `baseline` var, [`digest.py:948`](../../../../backend/workers/digest.py#L948) passes it as a kwarg to the LLM prompt, [`api/v1/studies.py:139`](../../../../backend/app/api/v1/studies.py#L139) serializes it onto the StudyDetail response). The column stays `NULL` forever in production.
- `backend/workers/digest.py:517` reads `study.baseline_metric` into a local + line 948 passes it through to the digest-narrative LLM prompt; both render `baseline=None` today.
- `ComparisonAgainst = Literal["runner_up", "baseline"]` exists at [`backend/app/domain/study/confidence.py:114`](../../../../backend/app/domain/study/confidence.py#L114) but only `"runner_up"` is emitted (hardcoded at [`confidence.py:624`](../../../../backend/app/domain/study/confidence.py#L624) with comment `# FR-3 locked for Phase 1`).
- `studies.baseline_trial_id` column does NOT exist on the Study model (`grep` returns zero matches across the codebase).

All 4 still-needed signals from the original draft remain accurate; line citations refreshed against `main` HEAD on 2026-05-25.

## Problem

`studies.baseline_metric` exists as a column on the `studies` table (declared in `feat_study_lifecycle` Phase 1, [`backend/app/db/models/study.py:95`](../../../../backend/app/db/models/study.py#L95)) with the docstring "single non-Optuna trial run before Optuna starts; populated by the orchestrator (Phase 2)." However, **the orchestrator was never updated to populate this column** — grep across `backend/workers/`, `backend/app/services/`, `backend/app/api/` finds only **read** sites (digest worker + studies API response serialization), no path that assigns to `study.baseline_metric` during a workflow. In production, `study.baseline_metric` is always `None`, and the PR body's `## Metric delta` section shows `baseline=None → achieved=X` with no `delta_pct`.

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
  - **(c) Previous study's winner.** If the study has `parent_study_id` (fork lineage — now MVP1-active via `feat_auto_followup_studies` PR #223, merged 2026-05-24), the baseline is the parent's winning trial's params. When no parent, no baseline runs. **Note (refreshed 2026-05-25):** original draft marked this "MVP2 surface" because parent_study_id was unused at draft time; that's now obsolete.
  - **(d) Parent proposal's config.** If the study has `parent_proposal_id` + `parent_proposal_followup_index` (the digest-executable-followups lineage added by `feat_digest_executable_followups` PR #225, merged 2026-05-24; see [`study.py:82-91`](../../../../backend/app/db/models/study.py#L82-L91)), the baseline is the config that the parent proposal would apply (i.e., the parent study's best trial). Distinct from (c): (c) chains studies; (d) chains across the digest→study→proposal→new-study handoff. Most directly answers "what does this followup CHANGE vs the current best?" for the digest-executable-followups flow.
- **Statistical design surface.** Once baseline data exists, the per-query delta semantics flip from "vs runner-up" to "vs production behavior" — the regressor framing changes from "winner sacrificed this query to other tried configs" to "winner makes this query worse than production." Both are valid signals; spec needs to lock which is the default surface (likely baseline when available, runner-up otherwise).
- **Compounding orchestrator complexity.** Adding a non-Optuna trial path means the orchestrator needs to (a) not increment Optuna's trial counter for the baseline, (b) handle baseline-trial failure differently than Optuna trial failure (a failed baseline should NOT block the study; just skip the comparison surface), (c) handle the baseline-trial timeout window separately from per-trial Optuna timeouts.

## Proposed capabilities

### Capability 1 — Migration: add `studies.baseline_trial_id`

- Alembic migration `00NN_studies_baseline_trial_id` (next available revision after the current head `0019_digests_suggested_followups_jsonb`; so `0020_*`).
- Schema: `baseline_trial_id String(36) NULL`. Not a formal FK (per the same rationale as `best_trial_id` in [`study.py:99`](../../../../backend/app/db/models/study.py#L99) — orchestrator stamps it after baseline trial completes; no enforce-at-DB constraint).
- Reversible `downgrade()` drops the column. Round-trip verified.
- No backfill — existing studies stay `baseline_trial_id IS NULL` and continue to show `comparison_against = "runner_up"` per Phase 1 fallback.

### Capability 2 — Orchestrator runs baseline trial before Optuna

- In [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) `start_study`, before entering the Optuna trial-enqueue loop:
  1. Resolve the baseline params (per the locked design decision from Phase 2 spec — options (a/b/c) above).
  2. If baseline params are non-empty, enqueue a single `run_baseline_trial(study_id, params)` Arq job. Wait for it to complete (synchronous within the start_study transaction OR await via Optuna's ask/tell sync mechanism — TBD by Phase 2 plan).
  3. Stamp `study.baseline_trial_id = <new_trial.id>` and `study.baseline_metric = <trial.primary_metric>`.
  4. Proceed to the Optuna loop.
- A new worker function `run_baseline_trial` mirrors `run_trial` but does NOT call `study.ask()` / `study.tell()` — it just renders the template with the baseline params, runs the engine query, scores via `ir_measures`, and persists a Trial row with `optuna_trial_number = -1` (sentinel) OR some other distinguishing marker. `per_query_metrics` is persisted just like Phase 1.
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

- **Builds on** [`feat_pr_metric_confidence`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) (Phase 1 of this feature, shipped 2026-05-21 as PR #180). Phase 1 must merge first so the `ConfidenceShape` and `compute_study_confidence` infrastructure exists for Phase 2 to extend.
- **Composes with** [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/feature_spec.md) — Phase 2 retroactively implements the "Phase 2" baseline-trial work that the study_lifecycle spec promised but deferred. Now it's a separate feature with its own spec cycle.
- **Composes with** [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/feature_spec.md) — if Phase 2 picks design option (b) (operator-supplied baseline_params), the create-study modal gains a new optional input. The search-space builder is the natural place for that input.
- **Composes with** [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md) (PR #225, merged 2026-05-24) — added the `studies.parent_proposal_id` + `parent_proposal_followup_index` lineage that powers option (d) "parent proposal's config" baseline. The most directly actionable baseline for a digest-executable followup study is "the config the parent proposal would have shipped"; before Phase 2, that comparison is impossible.
- **Composes with** [`feat_auto_followup_studies`](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) (PR #223, merged 2026-05-24) — promoted `studies.parent_study_id` from "MVP2 surface" to MVP1-active via auto-enqueued follow-up studies. The original draft's option (c) marker is updated above.

## Open questions for /spec-gen (Phase 2)

1. **Baseline semantics** — Which of (a) template defaults, (b) operator-supplied, (c) parent-study winner, **(d) parent-proposal config** is the locked default? Recommended: a multi-tier fallback — (d) parent_proposal config when the study has `parent_proposal_id` set (auto-followup / digest-executable-followups studies); (c) parent_study winner when `parent_study_id` is set (manual forks); (b) operator-supplied when the create-study request carries `baseline_params`; (a) template-defaults as final fallback. This ordering matches the operator's "what did I change?" mental model — for a digest-executable followup the most actionable baseline is "the config that the parent proposal would have shipped." Spec needs to confirm the order.
2. **Synchronous vs async baseline** — Does the orchestrator BLOCK on the baseline trial completing before enqueueing Optuna trials, or does it dispatch both in parallel? Recommended: synchronous (the baseline is a one-shot fast trial; Optuna can wait the extra 2-5 seconds).
3. **Baseline-trial failure handling** — Does a failed baseline fail the study OR proceed without baseline data? Recommended: proceed without (the baseline is informational, not load-bearing; failing the entire study because production-config-baseline failed would be a regression).
4. **`optuna_trial_number = -1` sentinel** — How does the existing trial-listing UI handle a trial with `optuna_trial_number = -1`? The Optuna RDB may not tolerate negative trial numbers. Alternative: a separate `baseline_trials` table; or a `trials.is_baseline` boolean. Recommended: investigate during Phase 2 spec — likely a `trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE` flag is cleaner than a sentinel.

## Trigger to start Phase 2

Phase 2 unlocks once:
- Phase 1 (`feat_pr_metric_confidence`) is merged to main.
- Operator feedback on the runner-up comparison surface confirms that production-baseline comparison would be more valuable (i.e., operators ask for "compare to what we currently ship, not just other tried configs").
- A Phase 2 design call decides between the three baseline semantics options above.
