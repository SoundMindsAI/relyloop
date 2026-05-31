# Overnight autopilot — Phase 2: "Ran while you were away" card on the /studies list

**Date:** 2026-05-31
**Status:** Idea — deferred Phase 2 work from [`feat_overnight_autopilot/feature_spec.md`](../feat_overnight_autopilot/feature_spec.md) §3 Phase boundaries. Split into its own planned-features folder 2026-05-31 (was `feat_overnight_autopilot/phase2_idea.md`).
**Priority:** P2 — discoverability boost on top of an already-trust-restoring Phase 1 panel. Not blocking.
**Origin:** Phase 1 feature spec §3 ("Out of scope") + §3 ("Phase boundaries") — split out per idea Q1's recommended default ("treat the `/studies` 'ran while away' card as a P2 stretch — defer to a follow-on idea so MVP2 ships the trust-restoring panel without the discoverability magic").
**Depends on:** Phase 1 ([`feat_overnight_autopilot/feature_spec.md`](../feat_overnight_autopilot/feature_spec.md) + [`implementation_plan.md`](../feat_overnight_autopilot/implementation_plan.md)) must merge first. Phase 2 reuses the Phase 1 `GET /api/v1/studies/{id}/chain` endpoint.

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
- Phase 2 leans toward cookie-only for MVP2 (no auth) and revisits when multi-tenant lands.

## Scope signals

- **Backend:** none if cookie-only; small (new endpoint + new column or table) if server-side. Defer the decision to the Phase 2 spec.
- **Frontend:** moderate — new card component, new visited-state hook, integration with the existing `/studies` page.
- **Migration:** none (cookie-only) or small (server-side path).
- **Config:** none.
- **Audit events:** N/A pre-MVP3.

## Why deferred

The Phase 1 feature spec locks in idea Q1's recommended default: ship the trust-restoring panel first; treat discoverability as a P2 stretch. The reasoning:

1. The Phase 1 panel makes the chain reviewable in minutes once the operator lands on it — the marginal value of the dashboard card is "fewer clicks to get there," not "feature works at all."
2. The dashboard card carries a visited-state model that needs its own UX scoping pass (cookie vs server-side, dismissal semantics, badge counts, multi-tab behavior).
3. Pulling Phase 2 forward into Phase 1 doubles the surface area + scope of the create-PR; deferring keeps MVP2 reviewable and lets the Phase 1 panel get real operator usage before designing the discoverability layer.

## Relationship to other work

- **Built on:** Phase 1 of this feature (the chain endpoint + the chain-summary panel).
- **Composes with:** [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) — if convergence verdicts ship per link, the "ran while away" card can include a one-liner like "Link 2 still climbing — budget may have been short."
- **Bypassed by:** an outgoing-webhook MVP for chain-complete events (currently a backlog idea per Phase 1 spec §3 / idea Q3); a webhook ship would satisfy the "wake up to results" trigger without needing the in-app card.
