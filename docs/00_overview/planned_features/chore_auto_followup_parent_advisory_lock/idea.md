# Chore — Postgres advisory lock on parent during followup-enqueue worker (layer-3 idempotency)

**Date:** 2026-05-26
**Status:** Idea — captured as a standalone file to resolve broken cross-references in `feat_auto_followup_studies` D-11 + plan F2 + `bug_auto_followup_completed_parent_stop_chain_race/idea.md`. The slug was coined 2026-05-24 in D-11 but only existed as descriptive prose across other documents until now.
**Priority:** Backlog — MVP2 hardening; no current operator-visible failure (layer 1 + layer 2 already close the only realistic duplicate-delivery vector in MVP1; this is preemptive coverage for MVP2 when autonomous re-trigger paths land).
**Origin:** [`feat_auto_followup_studies/feature_spec.md` §D-11](../../implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md), [`implementation_plan.md` §9 finding F2](../../implemented_features/2026_05_24_feat_auto_followup_studies/implementation_plan.md). Captured as standalone idea during `/bug-fix --ship` tangential-observations sweep on `bug_auto_followup_completed_parent_stop_chain_race`.

## Problem

The shipped `feat_auto_followup_studies` worker uses a two-layer idempotency scheme:

1. **Layer 1 — Arq deterministic `_job_id`** (`enqueue_followup_study:<parent_id>`). Closes the worker-restart-between-Redis-ack-and-DB-commit window, which is the only realistic duplicate-delivery vector in MVP1.
2. **Layer 2 — worker-level `list_children_of_study` backstop.** Catches the longer-tail case where the `_job_id` key expired between deliveries.

D-11 acknowledged a third race the two-layer scheme doesn't cover: **two concurrent worker invocations with the same `parent_id` can both see `[]` from `list_children_of_study` and both create a child.** Per the spec: "For MVP1, the two-layer scheme is sufficient — there is no autonomous re-triggering path; layer 1 covers the only known duplicate-delivery vector."

MVP2 will introduce autonomous re-trigger paths (auto-followup cron sweeps, retry-on-failure logic) that may invalidate the "no autonomous re-triggering" assumption. The race is theoretical in MVP1 and reachable in MVP2.

## Proposed approach

Acquire a Postgres advisory lock keyed on `hash(parent_study_id)` at the start of `enqueue_followup_study`. The lock serializes concurrent worker invocations against the same parent; the loser's transaction blocks until the winner commits, then observes the winner's child via `list_children_of_study` and short-circuits via layer 2.

Sketch:

```python
async with db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:pid))"), {"pid": parent_study_id}):
    existing_children = await repo.list_children_of_study(db, parent_study_id)
    if existing_children:
        # layer 2 short-circuit
        return
    # ... rest of gate + child creation
    await db.commit()  # releases the lock implicitly (xact_lock scope)
```

Lock scope is the transaction — `pg_advisory_xact_lock` is automatically released on commit/rollback. No explicit cleanup, no deadlock risk from long-held locks.

## Co-evolution with `bug_auto_followup_completed_parent_stop_chain_race`

This chore composes with the bug fix at [`bug_auto_followup_completed_parent_stop_chain_race`](../bug_auto_followup_completed_parent_stop_chain_race/idea.md) — both races have the same shape (cascade-vs-worker timing) but at different layers:

- The bug fix (Option A) zeroes `parent.config["auto_followup_depth"]` in the cascade to short-circuit the **pending worker's gate**.
- This chore (the advisory lock) coordinates **concurrent worker invocations** so the second one observes the first one's child.

Idea Option C in `bug_auto_followup_completed_parent_stop_chain_race` proposes a unified advisory-lock mechanism that obsoletes BOTH this chore AND the Option A fix. When Option C is ready to ship at MVP2, both deferred items are resolved at once.

## Dependencies

- MVP2 hardening window. No technical dependency on other MVP2 capabilities — can ship anytime after MVP2 work begins.
- Idea Option C in the cascade-race bug supersedes this chore. If Option C is picked up first, file this idea as closed-superseded.

## Scope signals

- **Backend:** ~10 LOC in `backend/workers/auto_followup.py` (wrap the existing transaction body in the lock acquisition).
- **Tests:** ~3 integration tests — single-worker happy path (lock acquire + release), concurrent-worker contention (loser observes winner's child via layer 2), lock-held duration (advisory lock doesn't outlast the transaction).
- **No schema change, no new ORM column, no UI impact.**
- **Audit events (MVP2+):** none new — the existing `auto_followup_enqueued` / `auto_followup_enqueued_duplicate_dropped` events already distinguish winner from loser.

## Why deferred from MVP1

- Two-layer scheme already covers the only realistic MVP1 duplicate-delivery vector (worker restart between Redis ack and DB commit). The third race is theoretical pre-MVP2.
- MVP1 has no autonomous re-triggering path that would exercise the race; an operator would need to manually re-enqueue the worker twice in a <100ms window to reach it.
- Adding the lock now without an observable failure to anchor against risks shipping the wrong granularity (per-parent vs per-cluster vs per-tenant) — better to wait for MVP2's autonomous re-trigger paths to inform the design.
