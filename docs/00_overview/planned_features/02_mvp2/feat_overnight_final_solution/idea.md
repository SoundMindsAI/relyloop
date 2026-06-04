# Overnight → final solution (autonomous cross-knob tuning to one ship-ready config)

**Date:** 2026-06-03
**Status:** Idea — user request during a Q&A session about the overnight autopilot's reach
**Priority:** P1
**Origin:** Operator stated goal: *"run the overnight process and in the morning have a final solution."* Surfaced while reviewing proposals at `/proposals/019e8e65-...` and learning that "Run overnight (compound automatically)" only narrows the anchor study's same knobs — it never branches to a different parameter or template, and it leaves a tree of per-link proposals rather than one answer.
**Depends on:** `feat_overnight_autopilot` (shipped 2026-05-31, PR #343) — this extends its chaining engine.

> **Priority guidance:** P1 — explicit operator-requested capability with a clear product goal ("morning = a final solution"). Scoped, high-value, ready to execute. Not P0 only because the narrow-only loop works correctly today and nothing is on fire.

## North-star goal

The operator starts an overnight run and, in the morning, has **one final, ship-ready tuned configuration** — explored across the relevant knobs and templates, converged, and packaged as a **single proposal/PR** — without babysitting the chain or choosing among a tree of intermediate proposals.

## Problem

Two gaps separate today's autopilot from that goal:

**Gap 1 — Reach (it only narrows the same knobs).** The overnight loop is a deterministic narrowing chain: each link re-runs the *same template* with the *same knobs*, bounds narrowed ±50% around the prior winner ([`backend/workers/auto_followup.py:211-215`](../../../../backend/workers/auto_followup.py#L211-L215) `narrow_bounds_around_winner(..., bracket=0.5)`; [`auto_followup.py:238`](../../../../backend/workers/auto_followup.py#L238) hardcodes `template_id=parent.template_id`). It **never reads** `digest.suggested_followups`, so the `widen` / `swap_template` cards the digest already produces — the only path to a *different* knob set or template — are dead for automation. A "final" answer can't be reached if the loop only ever refines the one knob the operator started with.

**Gap 2 — Rollup (no single answer).** Every completed study auto-creates its own `pending` proposal ([`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) `_on_study_complete`). An overnight chain of up to 6 studies (anchor + depth 1–5) therefore yields **up to 6 proposals**. There is no surface that says "across the whole chain, *this* is the winning config." The operator still has to compare links by hand in the morning — the opposite of "a final solution."

Delivering the goal requires closing **both** gaps: autonomous exploration across knobs/templates (so the result is actually complete), *and* a rollup that selects the global-best link and presents it as the one final proposal.

## Proposed capabilities

### Cap 1 — Autonomous cross-knob / cross-template exploration

- On each chain link, after the parent's digest is generated, the autopilot reads `digest.suggested_followups` and may act on the top-ranked **executable** follow-up (`narrow` | `widen` | `swap_template` — never `text`, which carries `search_space: null`) instead of always synthesizing a ±50% narrow.
- A `swap_template` link creates the child against the **proposed template** (not `parent.template_id`) with the digest's remapped search space — this is what lets the chain move onto a different knob set.
- `widen` / `narrow` links run the broadened / tightened bounds the digest emitted.
- Fall back to today's deterministic ±50% narrow when a link has no executable follow-up (chain never stalls; see Fork A).
- Honor the digest's convergence-aware ordering ([`prompts/digest_narrative.system.md:99-121`](../../../../prompts/digest_narrative.system.md#L99-L121)): when the parent is `still_improving` / `too_few_trials` the digest already demotes `narrow`/`widen` and leads with "re-run with a larger budget" — the autopilot should follow that rather than narrowing a study that hasn't converged.

### Cap 2 — Convergence-gated progression (so "final" means done, not just out of budget)

- Progression continues while there is forward lift AND an executable follow-up worth exploring; it stops when the tail link is `converged` AND no remaining executable follow-up adds lift above the epsilon.
- Preserve every existing stop condition (`depth_exhausted`, `no_lift`, `budget`, `parent_failed`, `cancelled`, `in_flight`) and the 6-study cap (`_validate_auto_followup_depth`, `0 ≤ depth ≤ 5`).
- Cycle / no-regress guard: a `swap_template` → `swap_template` ping-pong, or a `widen` that undoes a prior `narrow`, must be prevented via a visited-set threaded through `config` (like `auto_followup_depth`) so the chain makes monotonic progress and terminates.

### Cap 3 — Chain rollup → one final proposal (the morning artifact)

- When the chain terminates, select the **global-best link** across the entire tree (best `primary_metric` in the objective direction, convergence-confirmed) and surface it as **the** recommended proposal.
- Mark the intermediate links' proposals as `superseded` (or secondary) so the operator sees one ship-ready answer, with the others available as the explored path/history (see Fork B).
- The final proposal's `metric_delta` should be expressed against the **original anchor baseline**, not just the immediate parent — "here's the total lift from where you started" is the number the operator ships on.

### Cap 4 — Morning summary surface

- A single view (ties into [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/)) that shows: the final recommended config, total lift vs the anchor baseline, the convergence verdict, and the path the chain took (which knobs/templates it explored, link by link).
- The autopilot chain panel already surfaces per-link convergence verdicts (FR-7 soft contract) — extend it to mark the winning link and show each link's follow-up kind (narrow / widen / swap).

## Scope signals

- **Backend:** Core change in [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py) — replace the unconditional narrow with follow-up selection that can branch `template_id` and consume a `search_space` straight from the parent's persisted digest (today the worker only loads the parent study + best trial; it must now also load `digest.suggested_followups`). Selection/ranking + global-winner rollup are natural new **pure domain functions** under `backend/app/domain/study/` (unit-testable). Rollup likely needs a repo query that walks the chain by `parent_study_id` and ranks links. Proposal-supersede is a new status transition on the proposals aggregate.
- **Frontend:** Morning summary card + chain-panel winner marker (Cap 4). Possibly a wizard mode/toggle if cross-knob chaining is opt-in (Fork C).
- **Migration:** Possibly a `superseded` value added to the proposal status CHECK/enum (Cap 3) — confirm at spec time. The chain/visited-set state lives in `studies.config` JSONB, no column needed.
- **Config:** Likely a new `config` key (e.g. `auto_followup_strategy: "narrow" | "follow_suggestions"`) alongside `auto_followup_depth`. No new env var expected.
- **Audit events:** N/A pre-MVP3 (no `audit_log` until Observable). Existing structlog chain events should gain the selected follow-up kind, source→target template ids (for swaps), and the winning-link selection.

## Open forks to resolve at spec time

- **Fork A — no executable follow-up on a link.** Fall back to today's ±50% narrow (chain never stalls) vs stop with a new `no_executable_followup` reason. **Recommended: fall back to narrow** so depth budget is never wasted; record the per-link strategy.
- **Fork B — fate of intermediate proposals.** Mark non-winning links `superseded` (clean single answer, needs a status value + migration) vs leave them `pending` and just *badge* the winner (no migration, more morning clutter). **Recommended: supersede** — it's what delivers "one final solution," and the explored path stays visible as history.
- **Fork C — default vs opt-in.** Make follow-up-aware chaining the new default for the overnight mode, an opt-in toggle, or a distinct wizard mode. **Recommended: opt-in toggle** (`auto_followup_strategy`) so the predictable narrow-only behavior remains available.
- **Fork D — "final" definition / budget vs completeness.** Cap at depth 1–5 as today (predictable cost, may stop before fully converged) vs "run until converged or budget-capped" (truer to "final," less predictable cost). **Recommended: keep the depth + daily-budget caps** and define "final" honestly as *best config found across what was explored, convergence-confirmed* — not a provable global optimum.

## Honesty note on "final solution"

"Final" here means **the best configuration found across the knobs/templates the chain explored overnight, with convergence confirmed** — bounded by which follow-ups the digest surfaced and the depth/daily-budget caps. It is not a proof of global optimality across the entire possible search space. The morning artifact should state this plainly (e.g. "best of N configs explored; converged") so the operator ships with calibrated confidence.

## Relationship to other work

- **Extends** [`feat_overnight_autopilot`](../../implemented_features/2026_05_31_feat_overnight_autopilot/) — directly modifies its chaining worker.
- **Depends-on / feeds** [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/) (02_mvp2) — the morning summary surface; coordinate so the card renders the rolled-up winner.
- **Adjacent to** [`chore_auto_followup_parent_advisory_lock`](../chore_auto_followup_parent_advisory_lock/) (02_mvp2) — concurrency hardening on the same worker; land cleanly together.
- **Consumes** the existing follow-up taxonomy in [`backend/app/domain/study/followups.py`](../../../../backend/app/domain/study/followups.py) and digest generation in [`backend/workers/digest.py`](../../../../backend/workers/digest.py) — no new follow-up kinds; this teaches the autopilot to *act* on the kinds that already exist and to *roll them up* into one answer.
