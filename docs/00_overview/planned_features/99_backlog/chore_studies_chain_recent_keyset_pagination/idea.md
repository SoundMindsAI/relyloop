# Keyset pagination for the recent-chains discovery endpoint

**Date:** 2026-06-04
**Status:** Idea — deferred follow-on from `feat_overnight_studies_summary_card` Story 1.2
**Priority:** Backlog (defer-until-incident)
**Origin:** Carried out of [`feat_overnight_studies_summary_card/feature_spec.md`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/feature_spec.md) OQ-2 and the implementation_plan.md §1 deferred-ideas note.
**Depends on:** `feat_overnight_studies_summary_card` Phase 1 shipped (this PR).

> **Priority guidance:** Backlog — defer-until-incident. The discovery endpoint emits inert pagination (`next_cursor: null`, `has_more: false`) under a hard `limit ≤ 50` cap. Operators who want a full backlog can already filter via `?since=` to widen the window or shorten it. File once an operator reports being unable to see all relevant chains because the fixed cap clips the page.

## Problem

`GET /api/v1/studies/chains/recent` ships with a fixed `limit` ceiling of 50 and inert pagination fields kept on the wire for forward compatibility — `next_cursor` is always `null`, `has_more` is always `false`. The frontend hard-codes `limit: 20` for the "Ran while you were away" card, so MVP2-scale operators (single-tenant, hundreds of chains) see every relevant chain. Once an operator has thousands of chains in a single `?since=` window the cap silently clips, and they have no in-tool affordance to page further.

## Proposed capabilities

### Cap 1 — Keyset cursor on `(tail_completed_at, anchor_id)`

Promote the inert `next_cursor` to a real opaque cursor encoding `(tail_completed_at, anchor_id)` of the last row in the page. The endpoint already orders by tail-completion-DESC and dedupes by anchor; the cursor walks deterministically over that ordering.

- Backend: extend `list_recent_completed_chains` with a `cursor: tuple[datetime, str] | None` arg; add a row-value comparison (`(completed_at, id) < (cursor_ts, cursor_id)`) in the candidate query.
- Schema: `RecentChainsResponse.next_cursor` becomes a string when there are more pages; `has_more` flips to `true` accordingly.
- Frontend: add a `Load more` button below the card's row list that pushes the cursor through `useRecentChains` (or switch to TanStack's `useInfiniteQuery`).

### Cap 2 — Raise the per-page `limit` ceiling

Once the cursor exists the fixed `limit ≤ 50` cap can stay (50 cards per page is plenty) or be raised modestly. Worth re-evaluating once we have operator feedback on typical chain density.

## Scope signals

- **Backend:** repo + endpoint changes; pair with [`chore_studies_chain_recent_indexes`](../chore_studies_chain_recent_indexes/idea.md) (sibling deferred idea) so the cursor query has the supporting index.
- **Frontend:** `useRecentChains` becomes either cursor-aware or migrates to `useInfiniteQuery`. New "Load more" affordance on the card.
- **Migration:** none required for the endpoint itself; cap 1 of the sibling indexes idea materially helps performance once `Load more` lands.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

OQ-2 in the spec explicitly resolved this as limit-cap-only for v1: "Reserve `next_cursor`/`has_more` on the wire so a future MVP3 keyset story is additive, not breaking." At single-tenant on-laptop scale operators see every relevant chain in the default 20-row page; pagination would be ceremony with no user-visible benefit.

Pick this up when:
- an operator reports the card clips chains they want to see, OR
- the `?since=` window has to grow past a week or two to capture meaningful operator history, OR
- a frontend redesign wants infinite scroll on the card.

## Relationship to other work

- Pairs with [`chore_studies_chain_recent_indexes`](../chore_studies_chain_recent_indexes/idea.md) (the OQ-3 sibling). The keyset cursor's `(completed_at, id) < (cursor_ts, cursor_id)` predicate is the canonical motivator for the partial `completed_at DESC` index proposed there.
- Does NOT block `feat_overnight_studies_summary_card` shipping. The fixed limit + inert pagination contract is the documented v1 surface; cursor pagination would be an additive extension.
