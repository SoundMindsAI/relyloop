# Stop polling genuinely-closed-unmerged proposals (post-`bug_pr_reconciler_blocked_by_closed_fallback` polish)

**Date:** 2026-05-23
**Status:** Ready for /pipeline — Tier A scope locked; predicate `bug_pr_reconciler_blocked_by_closed_fallback` shipped (PR #204, merged 2026-05-23, commit `a0ca5b9`).
**Priority:** P2 — bounded daily cost. Real GitHub-API-budget concern at scale but not a blocker; depends on operator behavior (how many PRs they close unmerged).
**Origin:** Tangential observation from the `/bug-fix` flow shipping the fallback-closed recovery (PR #204). That bug fix widened `list_pr_opened_proposals_for_reconcile` to include `pr_state='closed'` rows so the eventual-consistency recovery path can fire. Side effect: genuinely-closed-unmerged proposals (case b — operator closed the PR without merging) now also enter the candidate set and get polled every reconciler tick for up to 90 days.
**Depends on:** [`bug_pr_reconciler_blocked_by_closed_fallback`](../../../00_overview/implemented_features/2026_05_23_bug_pr_reconciler_blocked_by_closed_fallback/) — **shipped** (PR #204).

## Problem

After `bug_pr_reconciler_blocked_by_closed_fallback` shipped (PR #204), the reconciler's candidate query at [`backend/app/db/repo/proposal.py:493-523`](../../../../backend/app/db/repo/proposal.py#L493-L523) returns BOTH:

- **Case (a) — fallback-closed, mergeable.** `(pr_opened, closed)` because the webhook's `merged_at=null` fallback fired. GitHub eventually returns `merged=true, merged_at=<ts>` and the reconciler recovers via `mark_proposal_pr_merged_from_closed`. ✓
- **Case (b) — genuinely closed unmerged.** `(pr_opened, closed)` because the operator (or another collaborator) closed the PR without merging. GitHub returns `merged=false, state=closed` on every poll. The existing `mark_proposal_pr_closed` helper's `pr_state='open'` guard turns the call into a benign no-op (`unchanged` counter increments). ✓ Correct behavior — but wasteful.

Case (b) burns one GitHub API call per stuck proposal per reconciler tick, indefinitely, until the row ages out of the 90-day window or an operator manually intervenes.

**Cost estimate:**

- Tick interval: 5 min (default `RELYLOOP_PR_POLL_MINUTES`)
- Window: 90 days
- API calls per stuck case-(b) row: 90 × 24 × 60 / 5 = ~25,920
- GitHub authenticated rate limit: 5,000/hour = 43.8M/year
- Threshold of concern: ~1,700 simultaneously stuck case-(b) rows would consume ~100% of the annual budget. Realistic deployments are far below that, but the cost is unbounded by current schema — a runaway "close-without-merge" workflow on the operator side would degrade the reconciler.

## Proposed capabilities

Tiered. Tier A is the cheap fix; Tier B is the proper terminal-state fix.

### Tier A — short-circuit the case-(b) no-op (cheap)  **[LOCKED SCOPE for /pipeline]**

Add a `last_polled_at` TIMESTAMPTZ column on `proposals` (nullable; never set for non-case-(b) rows). In the reconciler's `elif state == "closed":` branch at [`backend/workers/pr_reconcile.py:221`](../../../../backend/workers/pr_reconcile.py#L221), stamp `last_polled_at = now()` on the candidate row every time we observe `merged=false, state=closed` against a `(pr_opened, closed)` row. In `list_pr_opened_proposals_for_reconcile` ([`backend/app/db/repo/proposal.py:493-523`](../../../../backend/app/db/repo/proposal.py#L493-L523)), exclude rows where `pr_state='closed' AND last_polled_at IS NOT NULL AND last_polled_at > now() - interval '24 hours'`.

Locked decisions:

- **Column name:** `last_polled_at` (not `pr_state_observed_at`). Shorter; mirrors the `pr_merged_at` precedent on the same table.
- **Cadence:** 24 hours. One poll/day per stuck case-(b) row is a 288× reduction at the default 5-minute tick — sufficient headroom against the GitHub rate-limit budget without chasing diminishing returns.
- **Stamp site:** only in the reconciler's case-(b) branch (`state=closed AND not merged`). Case-(a) recovery is a one-shot terminal transition and doesn't need the stamp; case-(a) candidates that haven't recovered yet (still `pr_state='closed'`) get polled at the same 5-minute cadence as before because their `last_polled_at` stays NULL until we confirm `merged=false` once — but that's fine, because on case-(a) success the row exits the candidate set entirely.
- **NULL semantics:** NULL means "never stamped" — the row stays in the candidate set on every tick. Non-NULL but older than 24 hours means "stamped previously, due for re-check."

Effect: case (b) gets polled at most once per day instead of every 5 minutes. API cost drops by ~288× for stuck case-(b) rows.

- Backend: ~50 LOC (migration + repo + reconciler + tests).
- Migration: new nullable TIMESTAMPTZ column on `proposals`. Round-trip clean per CLAUDE.md Rule #5.
- Frontend: none.
- Tests: integration test with two ticks 30 minutes apart against a case-(b) row, asserts only the first tick polls (`unchanged` counter increments once, not twice). Plus a contract test that case-(a) rows still get polled every tick (their `last_polled_at` stays NULL).

### Tier B — terminal-state transition (proper)  **[DEFERRED — not in this /pipeline run]**

Add a `pr_closed_unmerged` terminal proposal status (or boolean `is_closed_unmerged`). When the reconciler observes `merged=false, state=closed` against a `(pr_opened, closed)` candidate, transition the proposal to the terminal status. The candidate query naturally excludes terminal rows; no polling cost beyond the first observation.

Trade-off vs Tier A:

- **Pro:** zero ongoing polling cost; cleaner state-machine semantics.
- **Con:** requires a status enum change (or a new boolean) + frontend display updates (the `/proposals` table needs to show "Closed without merge" rather than `pr_opened`); requires deciding whether the terminal is reopenable (if the operator re-opens the PR on GitHub, the webhook would need to flip back to `(pr_opened, open)`).

This is feature-scale; warrants `/pipeline` if Tier A doesn't suffice.

## Scope signals

- **Backend (Tier A):** ~50 LOC.
- **Backend (Tier B):** ~250 LOC + migration + frontend display work — likely escalate to `/pipeline`.
- **Frontend:** none for Tier A; new status display for Tier B.
- **Migration:** Tier A adds one nullable column. Tier B adds an enum value or boolean column.
- **Config:** none.
- **Audit events:** N/A (MVP1.5, pre-MVP2).
- **Tests:** integration coverage for the time-window exclusion (Tier A) or terminal-state transition (Tier B).

## Why deferred (historical — pre-pipeline)

The bug-fix that introduced this polling pattern (`bug_pr_reconciler_blocked_by_closed_fallback`, PR #204) is correct and complete on its own — case (b) polling is wasteful but bounded by the 90-day window. Filing this as a follow-up kept the bug-fix PR review surface focused on the actual eventual-consistency recovery; bundling polish work would have muddled the diff and the reviewer's mental model.

Status update (2026-05-23): the predicate bug-fix has merged. Operator approved picking up Tier A now while the reconciler is fresh in mind. Tier B remains deferred until a UX brief justifies the "closed without merge" status surface.

## Relationship to other work

- **Predicated on [`bug_pr_reconciler_blocked_by_closed_fallback`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md)** — the widened candidate query introduced the polling pattern this idea polishes away.
- **Coordinates with [`infra_per_trial_timeout`](../../../00_overview/implemented_features/2026_05_13_infra_per_trial_timeout/) precedent** — same shape: a `last_observed_at`-style column on a polling-driven state machine.
