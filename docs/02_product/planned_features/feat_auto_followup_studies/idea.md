# Auto-Followup Studies — autonomous study chaining with operator-set depth cap, the closest unintrusive analog to Karpathy compounding

**Date:** 2026-05-21
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit. The highest-leverage recommendation from the audit's "across studies" section.
**Priority:** P2 — large-scope cross-study compounding feature. High potential value but needs `feat_config_repo_baseline_tracking` as substrate first + design pass on the depth-cap + autonomous-action semantics. Multi-PR effort.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md` — recommendation #3. The audit's central finding: RelyLoop has a strong *within-study* loop but no *across-study* compounding. After a study completes, the operator must manually read the digest, decide to chain a followup, and configure it by hand. The agent doesn't observe study completion.
**Depends on:** [`feat_config_repo_baseline_tracking`](../feat_config_repo_baseline_tracking/idea.md) (substrate — tells the followup what config is currently live). Composes well with [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/idea.md) and [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md).

## Problem

Karpathy's autoresearch loop runs hundreds of experiments overnight and **compounds** improvements: each accepted change becomes the new baseline for the next experiment. RelyLoop's equivalent ("each merged proposal becomes the new baseline for the next study") is **manual at three gates**:

1. Operator reads the digest after study A completes (manual).
2. Operator clicks "Open PR" on the proposal (manual — verified at [`backend/app/api/v1/proposals.py:474-502`](../../../../backend/app/api/v1/proposals.py)).
3. Operator merges the PR (out of RelyLoop's control — delegated to GitHub branch protection per CLAUDE.md persona note).
4. Operator manually creates study B with study A's winner as a starting point — typically by calling `propose_search_space(prior_study_id=A)` in chat then `create_study(...)` per the prompt at [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md). The agent never observes study A's completion: [`backend/app/agent/orchestrator.py:160-286`](../../../../backend/app/agent/orchestrator.py) is only invoked via `send_user_message`. There is no background scheduler, no "study completed" event that wakes the agent, no auto-followup queue.

The audit's verdict: gates 2 and 3 are correctly human-in-the-loop (production config changes need human approval — umbrella spec §6 hard constraint). Gates 1 and 4 are the **exploration side** — and exploration is exactly where Karpathy's overnight compounding wins. An operator opting in to "run 3 chained studies overnight, each narrowing around the prior winner, with no PRs opened until I review in the morning" is fully compatible with the human-merge invariant.

The substrate for this already exists:

- [`propose_search_space`](../../../../backend/app/agent/tools/studies/propose_search_space.py) accepts an optional `prior_study_id` and narrows numeric bounds via `winner ± |winner| × bracket` (default bracket=0.5). This is exactly the "narrow around the winner" primitive a chained follow-up needs.
- The digest worker at [`backend/workers/digest.py`](../../../../backend/workers/digest.py) runs automatically after a study completes — it is the natural place to enqueue the follow-up.
- The orchestrator at [`backend/workers/orchestrator.py:163-250`](../../../../backend/workers/orchestrator.py) already runs studies headless; one more study in the queue is no different from one fewer.

What's missing is a **trigger + a depth counter + a bound check**, all small additions.

## Proposed capabilities

Tiered. Tier A is the minimal opt-in loop. Tier B is the safety + visibility surface that makes Tier A operator-trustworthy.

### Tier A — opt-in `auto_followup_depth` on study config

- **New `studies.config.auto_followup_depth: int | None = None`** field on [`StudyConfigSpec`](../../../../backend/app/api/v1/schemas.py) (line 550–580). Defaults to `None` = off; positive integer = depth cap (e.g., `3` chains up to 3 followups). Pydantic validator: `1 <= auto_followup_depth <= 10` when set.
- **Trigger** in the digest worker at [`backend/workers/digest.py`](../../../../backend/workers/digest.py), after the digest is persisted and the pending proposal is created: if `study.config.get("auto_followup_depth", 0) > 0` AND `study.best_metric is not None` (study completed with a winner) AND the gate condition below passes, enqueue a new Arq job `enqueue_followup_study(parent_study_id)`.
- **Gate condition** — the followup fires only if the winner is meaningfully above baseline. Default rule (tunable in feature spec): `study.best_metric > (study.baseline_metric or 0) + epsilon` where `epsilon = 0.005` (half-percent absolute lift). Studies whose winner did not beat the baseline by `epsilon` do **not** chain — the search space is exhausted or the optimizer got noise.
- **Follow-up creation** in a new worker function `enqueue_followup_study` at [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py):
  1. Load parent study + best trial.
  2. Call `propose_search_space(template_id=parent.template_id, prior_study_id=parent.id, bracket=0.5)` — already implemented.
  3. Build a new `CreateStudyRequest` inheriting parent's `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective`, with `search_space` from step 2, `config.auto_followup_depth = parent.config.auto_followup_depth - 1`, all other `config` fields inherited (same `max_trials`, `time_budget_min`, `parallelism`, `trial_timeout_s`).
  4. Insert via `repo.create_study()` and enqueue `start_study(new_study_id)`.
- **Parent-child relationship** persisted via a new nullable column `studies.parent_study_id VARCHAR(36) NULL REFERENCES studies(id) ON DELETE SET NULL`. Enables the UI to render a chain ("Study A → Study A.1 → Study A.2") and lets `parameter_importance` analyses compose across the chain.
- **No autonomous PR opening.** The default behavior: each follow-up generates a digest + a pending proposal (per existing flow) but does NOT auto-call `open_pr`. The operator reviews all proposals in the morning. A separate later feature could add `auto_open_pr_on_followup: bool` once the trust model is established.

### Tier B — safety, visibility, and the global circuit breaker

- **Daily LLM budget integration.** The existing daily budget gate at [`backend/workers/digest.py`](../../../../backend/workers/digest.py) (lines 553–577) already short-circuits digest LLM calls. `enqueue_followup_study` reads `peek_daily_total()` before enqueueing — if the gate is below 80% of `OPENAI_DAILY_BUDGET_USD`, proceed; otherwise log `auto_followup.budget_pre_empt` WARN event and do not enqueue. The follow-up study itself runs without LLM (Optuna + pytrec_eval are deterministic) but the **digest at its completion** will need LLM budget, so we gate at enqueue time.
- **Failure-aware halting.** If the parent study terminated via the 5-consecutive-failures circuit breaker (per [`backend/workers/orchestrator.py:69-70`](../../../../backend/workers/orchestrator.py)), do NOT enqueue a followup. Logged as `auto_followup.parent_failed`.
- **UI surface** on the study detail page at [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx): a new "Auto-follow-up chain" panel showing the parent + children + depth counter (e.g., "Auto-chain: 1 of 3 — next follow-up will narrow around current winner"). When a child study exists, link to it.
- **Cancellation cascade.** When a parent study is cancelled, the operator should be able to decide what happens to in-flight or queued children. Default: cancel the in-flight child; the depth counter is consumed. UI surface: a confirm-modal at cancel time.
- **Telemetry events** at the structlog layer: `auto_followup.enqueued`, `auto_followup.skipped_no_lift`, `auto_followup.skipped_budget`, `auto_followup.skipped_parent_failed`, `auto_followup.depth_exhausted`. Operator-greppable per the existing telemetry pattern.

### Out of scope

- **Auto-PR opening on followup chains.** Argued and explicitly deferred. Once the operator trusts the chain, a future feature could add `auto_open_pr_at_depth: int | None` ("open the PR only when the deepest member of the chain finishes"). For v1, every member of the chain produces a manual-review proposal.
- **Search-space *widening* on stagnation.** If three followups in a row produce no lift, the natural next move is to widen the search space and try a different region — but that needs a different heuristic than `propose_search_space`'s `prior_study_id` narrowing. Captured as a follow-up idea: `feat_search_space_stagnation_widening` (will write later if this v1 ships).
- **Cross-template chains.** Today `propose_search_space(prior_study_id=...)` only works when the followup uses the same template. Cross-template chains would require a `swap_template` heuristic that maps prior winners' params onto the new template's `declared_params`. Out of scope — composes with [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md) which already needs that primitive.
- **Multi-objective chains.** Single-objective only in MVP1 per umbrella spec §13. Out of scope.

## Scope signals

- **Backend:** ~600 LOC. Pydantic field + validator (~10) + Alembic migration for `parent_study_id` (~30) + ORM model field (~5) + `enqueue_followup_study` worker (~100) + digest-worker trigger integration (~30) + budget gate (~20) + telemetry events (~30) + cascade-cancel service logic (~50) + repo layer joins (~30) + tests across unit/integration/contract (~300).
- **Frontend:** ~300 LOC. Auto-follow-up chain panel (~200) + opt-in field in the create-study wizard with depth selector (~50) + cancel-cascade confirm modal (~50) + vitest coverage.
- **Migration:** one Alembic migration adding `studies.parent_study_id`. Strictly additive, nullable, ON DELETE SET NULL. Round-trip-clean.
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
4. **Depends on a substrate that doesn't exist yet.** [`feat_config_repo_baseline_tracking`](../feat_config_repo_baseline_tracking/idea.md) provides the "what's the current baseline" answer that this feature needs for the gate condition's baseline comparison.

## Relationship to other work

- **Most-leveraged consumer of [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/)** (shipped 2026-05-21). That feature provides the `prior_study_id` narrowing primitive in isolation; this feature builds the autonomous loop around it. Without auto-followup, `prior_study_id` requires manual operator chaining; with auto-followup, the same primitive compounds overnight.
- **Depends on [`feat_config_repo_baseline_tracking`](../feat_config_repo_baseline_tracking/idea.md)** for the baseline-comparison gate. The latter must ship first.
- **Composes with [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/idea.md)** — if every study in the chain has a known finite stop condition (e.g., `max_trials=200`), the chain's total resource footprint is predictable. Without sane defaults, a 3-deep chain with no caps would be catastrophic.
- **Composes with [`feat_digest_executable_followups`](../feat_digest_executable_followups/idea.md)** — that feature gives the LLM a structured "next followup" output; this feature acts on a *programmatic* default. The two coexist: the LLM-suggested followups remain advisory for the operator, while the auto-chain consumes the deterministic `propose_search_space(prior_study_id=...)` heuristic. Together they cover both the LLM-judgment-rich and the autonomous-deterministic paths.
- **Validates [`feat_pr_metric_confidence`](../feat_pr_metric_confidence/idea.md)** — auto-chained studies generate the data substrate (multiple studies with the same template + cluster) that lets the convergence-trajectory and noise-floor analytics show real cross-study patterns.

## Karpathy-loop framing

Per the framing in the surfacing audit: this feature is the **single largest gap** between RelyLoop today and a Karpathy-style overnight loop. RelyLoop already runs hundreds of trials within a study, scores them against a single metric, persists results, and picks a winner. What it doesn't do is **compound** — each study is one-shot. This feature makes the compounding optional, operator-controlled, and bounded — three properties Karpathy's loop also has (he runs his loop in time-boxed batches, not unbounded). Shipping this turns RelyLoop's "Karpathy-loop scorecard" row from ❌ to ✅ on the "Compounding across experiments" dimension.
