---
name: bug-dashboard-reset-disclosure-gating-too-strict
description: StartHereChecklist's "Reset to demo state" disclosure only renders for truly-pristine stacks (no clusters AND no query_sets AND no studies) — operators stuck with orphan data but no live clusters can't see the in-product self-rescue affordance
metadata:
  type: bug
---

# Bug — Dashboard "Reset to demo state" disclosure gating hides the self-rescue affordance from realistic stuck states

**Date:** 2026-05-26
**Status:** Idea — surfaced during interactive debugging of "no clusters after `make down` + `make up`" (operator session 2026-05-26 evening, immediately after PRs #265/#266 landed).
**Priority:** P2 — UX trap that turns a self-recoverable state into "operator must know `make seed-demo FORCE=1` exists." The disclosure was designed (per `feat_home_demo_reseed_endpoint` PR #228) to be the in-product recovery path; the gating condition is stricter than the spec's intent.
**Depends on:** None.

## Origin

Surfaced during interactive debugging of an empty dashboard after `make down && make up`. The operator's state:

- `hasClusters: false` (correctly — all clusters were soft-deleted by earlier E2E test cleanup; public API correctly filters)
- `hasQuerySetsWithJudgments: true` (5 query_sets in DB from prior runs, not cleaned up by the test teardown)
- `hasStudies: true` (5 studies in DB, also orphaned)

The "Get started" checklist correctly showed Step 1 (Register cluster) as NOT done, Steps 2 + 3 as Done. But the "Reset to demo state" disclosure that the operator remembered (and that `feat_home_demo_reseed_endpoint` PR #228 explicitly shipped as the self-rescue affordance) was hidden — because the gating predicate requires ALL THREE to be empty.

## Problem

[`ui/src/components/dashboard/start-here-checklist.tsx:150-160`](../../../ui/src/components/dashboard/start-here-checklist.tsx#L150-L160):

```jsx
{!hasClusters && !hasQuerySetsWithJudgments && !hasStudies && (
  <details className="mt-4 border-t pt-4 text-sm" data-testid="reset-demo-state-disclosure">
    <summary className="cursor-pointer text-muted-foreground">
      or skip ahead — reset to demo state
    </summary>
    <div className="mt-3">
      <ResetDemoStateButton />
    </div>
  </details>
)}
```

The 3-way AND gate models a "truly pristine, first-run-ever stack." But the realistic stuck state — **data orphaned without any live clusters** — is the situation where the operator actually needs the rescue affordance most. Without live clusters, the orphan studies + query_sets are unusable (every cluster-scoped operation will fail), so showing the disclosure would still be correct: the operator can't make progress with their existing data.

How operators get into this state:
- E2E tests that soft-delete clusters but don't clean up child rows (studies, query_sets).
- Operator manually deletes a cluster via `DELETE /api/v1/clusters/{id}` (soft-delete) without touching dependent rows.
- Half-completed `make reset` (volumes preserved, but cluster rows tombstoned for some other reason).

In all cases the operator sees a dashboard that looks "partly populated" but is functionally unusable, with no in-product way to start over.

## Proposed fix

Tighten the disclosure's gating predicate to fire whenever the operator has **no live clusters**, regardless of orphan data:

```diff
-{!hasClusters && !hasQuerySetsWithJudgments && !hasStudies && (
+{!hasClusters && (
   <details ... data-testid="reset-demo-state-disclosure">
     <summary>or skip ahead — reset to demo state</summary>
     ...
   </details>
 )}
```

Rationale: `hasClusters` is the load-bearing predicate. Without live clusters, no other piece of data can be used productively, so the operator's only forward path is either "Register a cluster" (Step 1's CTA) or "Reset to demo state" (the disclosure). Both should be available simultaneously.

### Regression test

Extend [`ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx`](../../../ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx) with one new case:

```tsx
test('disclosure renders when clusters are absent even if orphan studies + query_sets exist', () => {
  render(<StartHereChecklist
    hasClusters={false}
    hasQuerySetsWithJudgments={true}
    hasStudies={true}
  />);
  expect(screen.getByTestId('reset-demo-state-disclosure')).toBeInTheDocument();
});
```

The existing test file at line 67 asserts the opposite behavior under the current too-strict predicate; that assertion would need to flip in lockstep with the predicate change.

## Why deferred from this session

Surfaced during operator debugging, not during a planned bug-fix flow. The immediate operator unblock (CLI `make seed-demo FORCE=1`) bypassed the disclosure entirely. The disclosure gating fix is a focused UI predicate change + 1 test case that should ship as its own PR rather than mixing into the active session.

## Scope signals

- **Backend:** None.
- **Frontend:** ~3 LOC change to predicate, 1 new vitest case + 1 updated case in `start-here-checklist.test.tsx`.
- **Migration:** None.
- **Config:** None.
- **Audit events:** None (pre-MVP2).
- **Tests:** vitest unit test for the predicate change. No E2E spec change needed — the existing `tests/e2e/dashboard-reseed.spec.ts` already exercises the disclosure-visible path against a truly-empty stack.

## Relationship to other work

- **Sibling bug:** [`bug_seed_demo_if_empty_counts_soft_deleted`](../bug_seed_demo_if_empty_counts_soft_deleted/idea.md) — auto-seed-on-empty also false-skips when soft-deleted clusters exist. Together these two bugs leave operators with no recovery path. Fixing either bug alone restores recovery; fixing both is cleaner.
- **Origin feature:** `feat_home_demo_reseed_endpoint` PR #228 (merged 2026-05-24) shipped the disclosure + button + endpoint. The current gating predicate matches that spec literally, but the spec's intent was "show when the operator can't use the stack" — which is broader than "first-run-ever pristine."
