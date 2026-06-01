# Overnight autopilot — Phase 2: "Ran while you were away" card on the /studies list

**Date:** 2026-05-31
**Status:** Idea — deferred Phase 2 work from [`feat_overnight_autopilot/feature_spec.md`](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md) §3 Phase boundaries. Split into its own planned-features folder 2026-05-31 (was `feat_overnight_autopilot/phase2_idea.md`).
**Priority:** P2 — discoverability boost on top of an already-trust-restoring Phase 1 panel. Not blocking.
**Origin:** Phase 1 feature spec §3 ("Out of scope") + §3 ("Phase boundaries") — split out per idea Q1's recommended default ("treat the `/studies` 'ran while away' card as a P2 stretch — defer to a follow-on idea so MVP2 ships the trust-restoring panel without the discoverability magic").
**Depends on:** Phase 1 — **MERGED** as PR #343 on 2026-05-31 ([`implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md`](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md) + [`implementation_plan.md`](../../implemented_features/2026_05_31_feat_overnight_autopilot/implementation_plan.md)). The dependency is satisfied; this idea is genuinely ready. Phase 2 reuses the Phase 1 `GET /api/v1/studies/{id}/chain` endpoint ([`backend/app/api/v1/studies.py:771`](../../../../backend/app/api/v1/studies.py)), which returns `anchor_study_id`, `best_metric`, `cumulative_lift`, derived `stop_reason`, and the ordered `links[]` (chain length = `len(links)`); the anchor's display name lives at `links[0].name`, not as a top-level field.

## Problem

Phase 1 makes the overnight chain reviewable from the study detail page — but the operator has to know to go to *some* study in the chain. If they wake up and load `/studies`, the list looks identical to yesterday: studies sorted by `created_at DESC`, no callout that 3 of them ran while the operator was asleep, no badge that a chain finished, no "you have unread results" affordance.

The Phase 1 panel solves the trust-and-reviewability barrier; Phase 2 solves the discoverability barrier.

## Proposed capabilities

### "Ran while you were away" card at the top of `/studies`

- Card surfaces at the top of `/studies` when at least one chain has completed since the operator's last visit.
- Lists each completed chain with anchor name, chain length, best metric, cumulative lift, and a one-click "Review chain" link to the anchor's detail page.
- Dismiss action ("Got it") hides the card until a new chain completes.

### Visited-state persistence

- Phase 2 needs a per-operator "last viewed `/studies` at" timestamp to compute "since the operator's last visit." Two viable approaches — both belong to the Phase 2 design review:
  - **Cookie-only** (lightweight, no schema): store `last_visited_studies_at` in a localStorage key; compute "what's new" client-side. Trade-off: cleared on browser data wipe; no multi-device sync.
  - **Server-side** (schema-backed): add a `studies_visits` table or a `last_visited_at` column to a future `users` model. Trade-off: requires the auth/users layer (currently backlog) OR a single-tenant "anonymous operator" row.
- **(LOCKED) Visited-state model: cookie-only / localStorage for MVP2.** RelyLoop is single-tenant with no auth through GA v1, so a server-side `last_visited_at` would only ever attach to an "anonymous operator" row — pure overhead for zero multi-device benefit until the backlog auth layer lands. Store `last_visited_studies_at` (ISO-8601 UTC) in localStorage; compute "what's new" client-side; revisit when multi-tenant ships. The visited-state write incurs no audit event (client-only, no tenant-visible mutation).

### Chain-discovery mechanism (the load-bearing design fork)

The Phase 1 `GET /api/v1/studies/{id}/chain` endpoint is **per-study** — it answers "summarize the chain this study belongs to," not "which chains completed recently." The card needs a discovery step the Phase 1 surface does not provide. Two grounded paths (resolve at spec time):

- **(RECOMMENDED DEFAULT) Add a thin list endpoint** `GET /api/v1/studies/chains/recent?since=<ts>` (read-only, cursor-paginated, no migration) that returns one row per completed **anchor-rooted chain** whose newest link completed at/after `since` — each row carrying `anchor_study_id`, anchor `name`, chain length, `best_metric`, `cumulative_lift`, and the best-link `proposal_id`. The card consumes this directly; localStorage holds `since`. Pure read over existing `studies` columns (`parent_study_id`, `completed_at`); reuses the Phase 1 `chain_summary.py` domain helpers per chain. Backend cost: ~1 repo helper + 1 router + 1 response schema + contract/integration tests.
- **(REJECTED) Pure client-side fan-out.** Fetch `GET /studies?sort=completed_at:desc`, identify chain leaves client-side, then call `/chain` per candidate. **Blocked by an enumerated gap:** `StudySummary` ([`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py)) does **not** expose `parent_study_id`, so the frontend cannot tell anchors/leaves from the list response without N extra round-trips. Adding `parent_study_id` to `StudySummary` + an N+1 fan-out is both a wire-contract change AND worse runtime behavior than one server-side aggregation. Rejected.

## Scope signals

- **Backend:** small — one read-only list endpoint (`GET /api/v1/studies/chains/recent`, per the recommended chain-discovery default above) + one repo helper that finds completed-anchor chains since `since` and reuses the Phase 1 `chain_summary.py` aggregation. No new column, no new table, no migration. (The earlier "none if cookie-only" estimate was wrong: cookie-only covers the *visited-state* model but does NOT remove the need for a server-side chain-discovery query, because `StudySummary` lacks `parent_study_id`.)
- **Frontend:** moderate — new "ran while away" card component on `/studies`, a `useRecentChains` TanStack hook, a localStorage visited-state hook, and a dismiss ("Got it") affordance. Integrates above the existing `StudiesTable` in [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — both new surfaces (the read-only list endpoint and the client-only visited-state write) are non-mutating; no tenant-visible state changes, so no `audit_log` emission is required even once audit_log lands at MVP3.

## Why deferred

The Phase 1 feature spec locks in idea Q1's recommended default: ship the trust-restoring panel first; treat discoverability as a P2 stretch. The reasoning:

1. The Phase 1 panel makes the chain reviewable in minutes once the operator lands on it — the marginal value of the dashboard card is "fewer clicks to get there," not "feature works at all."
2. The dashboard card carries a visited-state model that needs its own UX scoping pass (cookie vs server-side, dismissal semantics, badge counts, multi-tab behavior).
3. Pulling Phase 2 forward into Phase 1 doubles the surface area + scope of the create-PR; deferring keeps MVP2 reviewable and lets the Phase 1 panel get real operator usage before designing the discoverability layer.

## Relationship to other work

- **Built on:** Phase 1 of this feature (the chain endpoint + the chain-summary panel) — **shipped** as PR #343 ([`implemented_features/2026_05_31_feat_overnight_autopilot/`](../../implemented_features/2026_05_31_feat_overnight_autopilot/)).
- **Composes with:** [`feat_study_convergence_indicator`](../../implemented_features/2026_06_01_feat_study_convergence_indicator/feature_spec.md) — **shipped** as PR #352. Convergence verdicts (`converged` / `still_improving` / `too_few_trials`) now exist per study, so the "ran while away" card can include a one-liner like "Link 2 still climbing — budget may have been short." Optional enhancement, not a dependency.
- **Bypassed by:** an outgoing-webhook MVP for chain-complete events (currently a backlog idea per Phase 1 spec §3 / idea Q3); a webhook ship would satisfy the "wake up to results" trigger without needing the in-app card.
