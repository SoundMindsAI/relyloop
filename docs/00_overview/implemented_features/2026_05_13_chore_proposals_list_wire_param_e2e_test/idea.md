# Idea — verify list-page filter clicks send the new wire params end-to-end

**Date:** 2026-05-12
**Status:** Idea — deferred from `feat_proposals_ui` final GPT-5.5 review (finding #4)
**Origin:** PR #58 final review (`/tmp/gpt55_final_review.out`), adjudicated as a Low-severity coverage-improvement follow-up.

---

## Problem

The `__tests__/app/proposals/page.test.tsx` suite covers AC-6 by asserting:

1. The status chip click calls `router.replace('/proposals?status=pr_opened')`.
2. The cluster-filter-select onChange handler fires with the right value (covered in `cluster-filter-select.test.tsx`).

These prove the page wires the chip → router intent. They do NOT prove that the NEXT backend request after a URL update actually carries `?status=pr_opened` on the wire, because the mocked `useSearchParams()` is static per render — `router.replace` updates a captured string but the mock doesn't trigger a re-render with the new search params.

GPT-5.5 final review flagged this as a Low-severity DoD coverage gap.

## Why deferred

- The behavior is structurally correct: `useProposals(filter)` builds its `queryFn` from the `filter` object, and `filter.status` is derived from `useSearchParams().get('status')`. TypeScript guarantees the wire param matches the derived state.
- Round-tripping a URL change through the `useSearchParams` mock requires either (a) a custom mock that re-renders on `replace`, or (b) using Next's actual router test harness — both are more elaborate than the DoD warranted for a frontend-only feature in MVP1.
- The wire-param round-trip IS exercised end-to-end by the cluster-filter-select test (which seeds clusters via msw, clicks the select, and confirms the cluster_id wire param via the request URL) — partial coverage already exists.

## Proposed fix

Two equivalent paths:

**Option A** — Custom `useSearchParams` mock that re-renders:

```tsx
let mockSearch = '';
const subscribers: Array<() => void> = [];
vi.mock('next/navigation', () => ({
  useSearchParams: () => {
    const [, force] = useReducer((x) => x + 1, 0);
    useEffect(() => {
      subscribers.push(force);
      return () => { subscribers.splice(subscribers.indexOf(force), 1); };
    }, []);
    return new URLSearchParams(mockSearch);
  },
  useRouter: () => ({
    replace: (url: string) => {
      mockSearch = url.split('?')[1] ?? '';
      subscribers.forEach(fn => fn());
    },
  }),
}));
```

**Option B** — Playwright E2E (when E2E lands at MVP3+).

Option A is the cheaper near-term fix.

## Scope signals

- **Frontend impact:** ~20 lines in `__tests__/app/proposals/page.test.tsx` test setup.
- **Backend impact:** none.
- **Migration:** none.

## Dependencies

- `feat_proposals_ui` (this folder's parent) must be merged so the page tests exist.
