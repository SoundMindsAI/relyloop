# Postgres indexes for the recent-chains discovery query

**Date:** 2026-06-04
**Status:** Idea — deferred follow-on from `feat_overnight_studies_summary_card` Story 1.1
**Priority:** Backlog (defer-until-incident)
**Origin:** Carried out of [`feat_overnight_studies_summary_card/feature_spec.md`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/feature_spec.md) OQ-3 and the implementation_plan.md §1 deferred-ideas note.
**Depends on:** `feat_overnight_studies_summary_card` Phase 1 shipped (this PR).

> **Priority guidance:** Backlog — defer-until-incident. The discovery query in `list_recent_completed_chains` reads at most `limit * 5 = 100` candidate rows under default sizing. At MVP2's single-tenant scale this is a trivial scan even with no supporting index. File once an operator reports the discovery endpoint's tail latency materially impacting `/studies` first-paint, OR once a chain-heavy operator pushes total `studies` rows past ~50k.

## Problem

`list_recent_completed_chains` at [`backend/app/db/repo/study.py`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/) executes a single SQL query of the shape:

```sql
SELECT id FROM studies
WHERE parent_study_id IS NOT NULL
  AND completed_at IS NOT NULL
  AND status IN ('completed', 'cancelled', 'failed')
  AND (since IS NULL OR completed_at >= since)
ORDER BY completed_at DESC, id DESC
LIMIT 100
```

The `studies` table has no index on `parent_study_id` (the chain self-FK is unindexed) and none on `completed_at`. At MVP2 scale this is a sequential scan over a small table — fine. As `studies` grows past tens of thousands of rows AND chain density rises, the planner will spend nontrivial work on every `/studies` first-paint refresh of the card.

## Proposed capabilities

### Cap 1 — Add `ix_studies_parent_study_id`

A simple btree index on `studies.parent_study_id`. Helps the recent-chains discovery query's most selective predicate (only follow-up children qualify) and also benefits `list_children_of_study`'s `WHERE parent_study_id = :id` (which currently scans the same way).

### Cap 2 — Add a partial index on `(completed_at DESC) WHERE completed_at IS NOT NULL`

A descending partial index sized to the terminal subset of `studies`. Pairs with the ORDER BY in the discovery query and trims the index size to ~rows-with-completed-at, which is typically much smaller than the full table while a study is queued/running.

### Cap 3 — Optional: covering index `(parent_study_id, completed_at DESC, id)`

Index-only scan candidate. Worth it only if the discovery query becomes hot enough to justify the index-write overhead on every study completion. Probably overkill until cap 1 + cap 2 measurably stop helping.

## Scope signals

- **Backend:** new Alembic migration adding the index/indexes. Round-trip required per Absolute Rule #5 (`upgrade` creates, `downgrade` drops). No application code change.
- **Frontend:** none.
- **Migration:** required. New revision off the current Alembic head.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

OQ-3 in the spec explicitly deferred indexing until the discovery query becomes measurably slow: "Add indexes on `studies.parent_study_id` + `studies.completed_at` if/when the discovery query becomes slow at scale." The single-tenant on-laptop MVP scale is well below where a sequential scan on the candidate query matters.

Pick this up when:
- the discovery endpoint's tail latency materially affects `/studies` first paint (operator report), OR
- total `studies` row count crosses ~50k (estimated tipping point for the seq scan), OR
- a chain-heavy operator with depth-5 chains accumulates >10k chain children.

## Relationship to other work

- Pairs naturally with `chore_studies_chain_recent_keyset_pagination` (the sibling deferred idea from the same spec's OQ-2). If both ship together, the new indexes feed the keyset cursor predicates cleanly.
- Does NOT block `feat_overnight_studies_summary_card` shipping. The discovery endpoint works correctly without these indexes — they're a performance optimization, not a correctness requirement.
