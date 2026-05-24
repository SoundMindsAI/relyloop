# Auto-Followup Studies — autonomous study chaining with operator-set depth cap, the closest unintrusive analog to Karpathy compounding

**Date:** 2026-05-21 (preflight audit refreshed 2026-05-23)
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit. The highest-leverage recommendation from the audit's "across studies" section.
**Priority:** P2 — large-scope cross-study compounding feature. High potential value but needs `feat_study_baseline_trial` as substrate first (without it the gate condition degenerates) + design pass on the depth-cap + autonomous-action semantics. Multi-PR effort.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md` — recommendation #3. The audit's central finding: RelyLoop has a strong *within-study* loop but no *across-study* compounding. After a study completes, the operator must manually read the digest, decide to chain a followup, and configure it by hand. The agent doesn't observe study completion.
**Depends on:** [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) (substrate — populates `studies.baseline_metric` so the lift-gate has a real comparison point; today the column is always NULL, see [`backend/app/db/models/study.py:76`](../../../../backend/app/db/models/study.py#L76) + zero write sites per the `feat_study_baseline_trial` audit). Composes well with [`chore_study_default_stop_conditions`](../../../00_overview/implemented_features/2026_05_23_chore_study_default_stop_conditions/feature_spec.md) (shipped PR #215, 2026-05-23 — bounded stop conditions cap chain resource footprint), [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md), and [`feat_config_repo_baseline_tracking`](../../../00_overview/implemented_features/2026_05_23_feat_config_repo_baseline_tracking/feature_spec.md) (shipped PR #202, 2026-05-23 — provides the `config_repos.last_merged_proposal_id` reference for future UI annotations on the chain panel, but **not** a hard dependency of this feature's mechanics).

**Substrate already in place (verified 2026-05-23):**
- `studies.parent_study_id` self-FK column exists at [`backend/app/db/models/study.py:72-75`](../../../../backend/app/db/models/study.py#L72) (added by `feat_study_lifecycle` Phase 1 migration [`0003_study_lifecycle_schema.py:183-187`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183), docstring `"Self-FK for fork lineage (MVP2 surface)"`). **No schema migration needed to add the column** — only a possible ALTER if we choose `ON DELETE SET NULL` over the current default (see "Open questions for /spec-gen" §1 below).
- [`propose_search_space(prior_study_id=..., bracket=0.5)`](../../../../backend/app/agent/tools/studies/propose_search_space.py) ships the narrowing primitive (shipped PR #175, 2026-05-21 — `feat_agent_propose_search_space`).
- The daily-LLM-budget peek (`peek_daily_total`) is wired into the digest worker at [`backend/workers/digest.py:554-578`](../../../../backend/workers/digest.py#L554).

## Problem

Karpathy's autoresearch loop runs hundreds of experiments overnight and **compounds** improvements: each accepted change becomes the new baseline for the next experiment. RelyLoop's equivalent ("each merged proposal becomes the new baseline for the next study") is **manual at three gates**:

1. Operator reads the digest after study A completes (manual).
2. Operator clicks "Open PR" on the proposal (manual — verified at [`backend/app/api/v1/proposals.py:485-510`](../../../../backend/app/api/v1/proposals.py#L485)).
3. Operator merges the PR (out of RelyLoop's control — delegated to GitHub branch protection per CLAUDE.md persona note).
4. Operator manually creates study B with study A's winner as a starting point — typically by calling `propose_search_space(prior_study_id=A)` in chat then `create_study(...)` per the prompt at [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md). The agent never observes study A's completion: [`backend/app/agent/orchestrator.py:160`](../../../../backend/app/agent/orchestrator.py#L160) `run_turn` is only invoked via `send_user_message`. There is no background scheduler, no "study completed" event that wakes the agent, no auto-followup queue.

The audit's verdict: gates 2 and 3 are correctly human-in-the-loop (production config changes need human approval — umbrella spec §6 hard constraint). Gates 1 and 4 are the **exploration side** — and exploration is exactly where Karpathy's overnight compounding wins. An operator opting in to "run 3 chained studies overnight, each narrowing around the prior winner, with no PRs opened until I review in the morning" is fully compatible with the human-merge invariant.

The substrate for this already exists:

- [`propose_search_space`](../../../../backend/app/agent/tools/studies/propose_search_space.py) accepts an optional `prior_study_id` and narrows numeric bounds via `winner ± |winner| × bracket` (default bracket=0.5). This is exactly the "narrow around the winner" primitive a chained follow-up needs.
- The digest worker at [`backend/workers/digest.py`](../../../../backend/workers/digest.py) runs automatically after a study completes — it is the natural place to enqueue the follow-up.
- The orchestrator at [`backend/workers/orchestrator.py:93`](../../../../backend/workers/orchestrator.py#L93) `start_study` already runs studies headless (function body spans ~300 lines, terminating at the failure-cascade + stop-condition handling at line 305); one more study in the queue is no different from one fewer.

What's missing is a **trigger + a depth counter + a bound check**, all small additions.

## Proposed capabilities

Tiered. Tier A is the minimal opt-in loop. Tier B is the safety + visibility surface that makes Tier A operator-trustworthy.

### Tier A — opt-in `auto_followup_depth` on study config

- **New `studies.config.auto_followup_depth: int | None = None`** field on [`StudyConfigSpec`](../../../../backend/app/api/v1/schemas.py#L556) (class at line 556, body lines 556–586). Defaults to `None` = off; positive integer = depth cap (e.g., `3` chains up to 3 followups). Pydantic validator: `1 <= auto_followup_depth <= 10` when set.
- **Trigger** in the digest worker at [`backend/workers/digest.py`](../../../../backend/workers/digest.py), after the digest is persisted and the pending proposal is created: if `study.config.get("auto_followup_depth", 0) > 0` AND `study.best_metric is not None` (study completed with a winner) AND the gate condition below passes, enqueue a new Arq job `enqueue_followup_study(parent_study_id)`.
- **Gate condition** — the followup fires only if the winner is meaningfully above baseline. Default rule (tunable in feature spec): `study.best_metric > (study.baseline_metric or 0) + epsilon` where `epsilon = 0.005` (half-percent absolute lift). Studies whose winner did not beat the baseline by `epsilon` do **not** chain — the search space is exhausted or the optimizer got noise. **⚠️ Hard dependency:** as of 2026-05-23, [`studies.baseline_metric`](../../../../backend/app/db/models/study.py#L76) is declared but never written in production (zero write sites per the [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) audit). Until that feature ships, this formula silently collapses to `best_metric > 0.005`, which means "did the optimizer find anything?" rather than "did it beat the baseline." `feat_study_baseline_trial` must merge before this gate can do what it claims; otherwise the spec needs to lock an alternative gate (e.g., "winner beat the best trial of the parent's first 10% of trials" — surfaced as Open question §3 below).
- **Follow-up creation** in a new worker function `enqueue_followup_study` at [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py):
  1. Load parent study + best trial.
  2. Call `propose_search_space(template_id=parent.template_id, prior_study_id=parent.id, bracket=0.5)` — already implemented.
  3. Build a new `CreateStudyRequest` inheriting parent's `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective`, with `search_space` from step 2, `config.auto_followup_depth = parent.config.auto_followup_depth - 1`, all other `config` fields inherited (same `max_trials`, `time_budget_min`, `parallelism`, `trial_timeout_s`).
  4. Insert via `repo.create_study()` and enqueue `start_study(new_study_id)`.
- **Parent-child relationship** uses the **existing** `studies.parent_study_id` self-FK at [`backend/app/db/models/study.py:72-75`](../../../../backend/app/db/models/study.py#L72), declared by [`feat_study_lifecycle` Phase 1 migration 0003](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183) explicitly as the "MVP2 fork surface." The column is `String(36) NULL` with a plain `ForeignKey("studies.id")` (Postgres default ON DELETE is `NO ACTION`). **No new column-creation migration is needed.** A small ALTER would be required only if the spec locks `ON DELETE SET NULL` semantics for parent-deletion cascade — see Open question §1 below. The column enables the UI to render a chain ("Study A → Study A.1 → Study A.2") and lets `parameter_importance` analyses compose across the chain.
- **No autonomous PR opening.** The default behavior: each follow-up generates a digest + a pending proposal (per existing flow) but does NOT auto-call `open_pr`. The operator reviews all proposals in the morning. A separate later feature could add `auto_open_pr_on_followup: bool` once the trust model is established.

### Tier B — safety, visibility, and the global circuit breaker

- **Daily LLM budget integration.** The existing daily budget gate at [`backend/workers/digest.py:554-578`](../../../../backend/workers/digest.py#L554) already short-circuits digest LLM calls. `enqueue_followup_study` reads `peek_daily_total()` before enqueueing — if the gate is below 80% of `OPENAI_DAILY_BUDGET_USD`, proceed; otherwise log `auto_followup.budget_pre_empt` WARN event and do not enqueue. The follow-up study itself runs without LLM (Optuna + ir_measures are deterministic) but the **digest at its completion** will need LLM budget, so we gate at enqueue time.
- **Failure-aware halting.** If the parent study terminated via the 5-consecutive-failures circuit breaker (docstring at [`backend/workers/orchestrator.py:70`](../../../../backend/workers/orchestrator.py#L70), implementation at [`:212-225`](../../../../backend/workers/orchestrator.py#L212)), do NOT enqueue a followup. Logged as `auto_followup.parent_failed`. Same halt applies to the 20-zero-metric "no signal" termination at [`:243-244`](../../../../backend/workers/orchestrator.py#L243).
- **UI surface** on the study detail page at [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx): a new "Auto-follow-up chain" panel showing the parent + children + depth counter (e.g., "Auto-chain: 1 of 3 — next follow-up will narrow around current winner"). When a child study exists, link to it.
- **Cancellation cascade.** When a parent study is cancelled, the operator should be able to decide what happens to in-flight or queued children. Default: cancel the in-flight child; the depth counter is consumed. UI surface: a confirm-modal at cancel time.
- **Telemetry events** at the structlog layer: `auto_followup.enqueued`, `auto_followup.skipped_no_lift`, `auto_followup.skipped_budget`, `auto_followup.skipped_parent_failed`, `auto_followup.depth_exhausted`. Operator-greppable per the existing telemetry pattern.

### Out of scope

- **Auto-PR opening on followup chains.** Argued and explicitly deferred. Once the operator trusts the chain, a future feature could add `auto_open_pr_at_depth: int | None` ("open the PR only when the deepest member of the chain finishes"). For v1, every member of the chain produces a manual-review proposal.
- **Search-space *widening* on stagnation.** If three followups in a row produce no lift, the natural next move is to widen the search space and try a different region — but that needs a different heuristic than `propose_search_space`'s `prior_study_id` narrowing. Captured as a follow-up idea: `feat_search_space_stagnation_widening` (will write later if this v1 ships).
- **Cross-template chains.** Today `propose_search_space(prior_study_id=...)` only works when the followup uses the same template. Cross-template chains would require a `swap_template` heuristic that maps prior winners' params onto the new template's `declared_params`. Out of scope — composes with [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md) which already needs that primitive.
- **Multi-objective chains.** Single-objective only in MVP1 per umbrella spec §13. Out of scope.

## Scope signals

- **Backend:** ~565 LOC. Pydantic field + validator (~10) + `enqueue_followup_study` worker (~100) + digest-worker trigger integration (~30) + budget gate (~20) + telemetry events (~30) + cascade-cancel service logic (~50) + repo layer joins (~30) + tests across unit/integration/contract (~300). **No new column migration** (the `parent_study_id` self-FK already exists, see Substrate note in header). Optional small ALTER (~15 LOC) only if §1 below locks `ON DELETE SET NULL`.
- **Frontend:** ~300 LOC. Auto-follow-up chain panel (~200) + opt-in field in the create-study wizard with depth selector (~50) + cancel-cascade confirm modal (~50) + vitest coverage.
- **Migration:** **None for the column.** Conditional ~15-LOC `op.execute(...)` ALTER if the spec locks `ON DELETE SET NULL` on the existing FK (currently default `NO ACTION`). Round-trip-clean either way.
- **Config:** none new (uses existing `OPENAI_DAILY_BUDGET_USD`).
- **Audit events:** N/A (MVP1 has no audit_log). At MVP2 the followup-enqueue and budget-skip events become canonical audit events.
- **Tests:**
  - Unit: gate-condition arithmetic; depth decrement; parent-failure check.
  - Integration: parent study completes → child study enqueued + correct config inherited; budget exhausted → no enqueue; parent failed → no enqueue; depth-3 chain finishes correctly; cancelled parent halts in-flight child.
  - Contract: study detail response includes `parent_study_id` + `auto_followup_depth`.
  - End-to-end: a chained-study integration test that runs 3 stub-adapter studies in sequence and asserts each child's search space narrows around the parent's winner.

## Why not inline today

1. **Cross-subsystem, cross-stack.** Touches schema migration + worker logic + agent-tool composition + UI surface + operator telemetry. Far outside the inline-fix budget per [`CLAUDE.md`](../../../../CLAUDE.md) rubric.
2. **Multiple product-design forks.** The gate condition (epsilon threshold for "enough lift to chain"), the depth cap (how many is sane?), the inheritance rules (parallelism inherits or resets?), the budget-gate threshold (80% of daily? 90%?), and the cancellation cascade behavior (cancel children eagerly? let them finish?) all need spec-level decisions. None are obvious defaults.
3. **Trust-building substrate.** This feature changes RelyLoop's autonomy story materially — from "operator-initiated single studies" to "operator-initiated chains that compound overnight." The change deserves visible operator surfaces (the chain panel, the telemetry events, the cancellation cascade) that take real design effort. Shipping it as a chore would underweight the operator-trust dimension.
4. **Depends on a substrate that doesn't exist yet.** [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) populates `studies.baseline_metric` (currently always NULL in production — the deferred Phase 2 of `feat_pr_metric_confidence` never landed). Without it, the lift-gate `best_metric > (baseline_metric or 0) + epsilon` degenerates to `best_metric > 0.005`. Either `feat_study_baseline_trial` ships first, or this feature's spec locks an alternative gate (see Open question §3).

## Relationship to other work

- **Most-leveraged consumer of [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/feature_spec.md)** (shipped 2026-05-21). That feature provides the `prior_study_id` narrowing primitive in isolation; this feature builds the autonomous loop around it. Without auto-followup, `prior_study_id` requires manual operator chaining; with auto-followup, the same primitive compounds overnight.
- **Depends on [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md)** for the lift-gate to be meaningful — it populates the currently-NULL `studies.baseline_metric` column. Must ship first OR the spec locks an alternative gate (see Open question §3).
- **Composes with [`chore_study_default_stop_conditions`](../../../00_overview/implemented_features/2026_05_23_chore_study_default_stop_conditions/feature_spec.md)** (shipped PR #215, 2026-05-23) — every study in the chain now has a known finite stop condition (defaults: Standard preset = `max_trials=200`), so the chain's total resource footprint is predictable. The composition cost just dropped: this feature can rely on the new defaults instead of validating them itself.
- **Composes with [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md)** — that feature gives the LLM a structured "next followup" output; this feature acts on a *programmatic* default. The two coexist: the LLM-suggested followups remain advisory for the operator, while the auto-chain consumes the deterministic `propose_search_space(prior_study_id=...)` heuristic. Together they cover both the LLM-judgment-rich and the autonomous-deterministic paths.
- **Coordinates with [`feat_config_repo_baseline_tracking`](../../../00_overview/implemented_features/2026_05_23_feat_config_repo_baseline_tracking/feature_spec.md)** (shipped PR #202, 2026-05-23) — provides `config_repos.last_merged_proposal_id`, which the chain panel UI can use to annotate "this chain's parent was based on the currently-live PR." Not a mechanical dependency; just shared context.
- **Validates [`feat_pr_metric_confidence`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md)** (shipped 2026-05-21) — auto-chained studies generate the data substrate (multiple studies with the same template + cluster) that lets the convergence-trajectory and noise-floor analytics show real cross-study patterns.

## Open questions for /spec-gen

These are the design forks that genuinely need spec-time decisions. Each has a recommended default so the spec doesn't start from zero.

1. **`ON DELETE` semantics on `studies.parent_study_id`.** The existing FK uses Postgres default `NO ACTION` — deleting a parent that has children raises `IntegrityError`. Two options:
   - **(a, recommended) Keep `NO ACTION`.** Studies are soft-deleted via `deleted_at` (per CLAUDE.md "Database conventions"), not hard-deleted, so the FK strictness is mostly theoretical. The chain panel filters by `deleted_at IS NULL` and gets clean lineage. No migration needed.
   - **(b) ALTER to `ON DELETE SET NULL`.** Lets future hard-delete tooling break lineage rather than block. Costs one ~15-LOC migration. Pick this if the team plans to add a hard-delete path for studies in MVP2.
2. **Depth cap maximum.** The validator allows `1 <= auto_followup_depth <= 10`. Recommended default UI ceiling: `5`. Rationale: with `max_trials=200` per study (Standard preset default), depth=5 = 1,000 trials per chain — enough for meaningful overnight compounding, low enough that a single distracted operator cannot accidentally burn 10× the daily LLM budget.
3. **Gate-condition fallback if `feat_study_baseline_trial` does not ship first.** Two alternatives:
   - **(a, recommended) Lift-over-first-decile.** `best_metric > max(trial.primary_metric for trial in parent.first_10pct_complete_trials) + epsilon` — uses the parent's own early random-sample trials as an implicit baseline. No external dependency. Works for any study.
   - **(b) Lift-over-zero.** Current degenerate behavior (`best_metric > 0.005`). Effectively "did we find anything?" — too permissive.
4. **Inheritance rules for parallelism / time_budget / trial_timeout.** Two options:
   - **(a, recommended) Strict inherit.** The child uses identical `config` (excluding `auto_followup_depth`, which decrements). Predictable. Tested.
   - **(b) Reset-to-default.** The child reads `Settings.studies_default_parallelism` etc. Useful only if the parent's params were one-off overrides that shouldn't propagate. Hard to predict.
5. **Budget-gate threshold percentage.** Idea proposes 80% of daily budget. Two options:
   - **(a, recommended) 80%.** Headroom for the digest LLM call + any in-flight chat agent activity.
   - **(b) 90%.** Riskier (digest may be cut off) but extracts more chain depth on tight budgets.
6. **Cancellation cascade default.** Idea proposes "cancel the in-flight child; depth counter consumed." Confirm with operator UX: should the confirm-modal default the radio button to **cancel** or **let it finish**? Recommendation: default to **cancel** (consistent with "cancel" being the explicit user action).

## Sibling coordination notes

- **[`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md)** — the real metric-baseline dependency. If both end up in the same `/pipeline` queue, ship `feat_study_baseline_trial` first; otherwise this feature's spec must lock alternative gate §3a.
- **[`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md)** — orthogonal mechanism (LLM-suggested follow-ups vs. programmatic chain). Spec should reference the structured digest output as a future surface that could *override* the programmatic gate when the LLM proposes a different next study, but no coordination is required for v1.
- **[`feat_study_clone_from_previous`](../feat_study_clone_from_previous/idea.md)** — manual-clone UX. Once auto-chain ships, the manual clone wizard should set `auto_followup_depth = 0` by default (no inherited chain) but offer it as an opt-in.

## Karpathy-loop framing

Per the framing in the surfacing audit: this feature is the **single largest gap** between RelyLoop today and a Karpathy-style overnight loop. RelyLoop already runs hundreds of trials within a study, scores them against a single metric, persists results, and picks a winner. What it doesn't do is **compound** — each study is one-shot. This feature makes the compounding optional, operator-controlled, and bounded — three properties Karpathy's loop also has (he runs his loop in time-boxed batches, not unbounded). Shipping this turns RelyLoop's "Karpathy-loop scorecard" row from ❌ to ✅ on the "Compounding across experiments" dimension.
