# Idea — chore_query_inline_crud_table_integration_test

**Date:** 2026-05-13
**Origin:** GPT-5.5 phase-2 review F7 on `feat_query_inline_crud`. The delete-dialog component tests assert toast behavior in isolation; an integration-style test that renders `<QueriesTable>` + clicks Delete + asserts row-removed (204) vs row-still-present (409) would catch UX regressions the current tests miss.

## Problem

The current frontend test coverage is split:

* `delete-query-dialog.test.tsx` — renders `<DeleteQueryDialog>` standalone with a stub trigger. Asserts toast.error / toast.success call patterns, but does NOT render the table, so "row removed after 204" and "row still present after 409" are not directly verified.
* `queries-table.test.tsx` — renders `<QueriesTable>` but does not exercise the delete flow.

Both assert their own contracts correctly. What's missing is the integration: open the table, click the row's Delete icon, confirm in the alert dialog, and assert the row DOM state matches the response.

## Why deferred

* The unit behaviors are independently verified — the table renders rows from the cache, and the delete dialog invalidates the cache. The integration is the product of those two pieces.
* Writing an integration test that exercises both layers requires shimming `useRouter` + MSW the DELETE endpoint AND the subsequent re-GET that fires from cache invalidation. Doable but high-overhead.
* The real E2E coverage gap is the same one captured in `chore_query_inline_crud_e2e/idea.md` (deferred from spec §14): a Playwright test against the real backend would catch this regression too, and at a more authoritative layer.

## Proposed scope (when this idea graduates to a spec)

1. Add `ui/src/__tests__/components/query-sets/queries-table-delete-flow.test.tsx`:
   - Mounts `<QueriesTable>` with 3 rows.
   - Clicks the Delete icon on row #1.
   - Confirms the AlertDialog → DELETE returns 204.
   - Asserts the row is gone from the DOM after cache invalidation refetch (use msw to return the now-2-row list).
   - Second case: row #2 returns 409 from DELETE → assert the toast fires + the row is STILL in the DOM (no cache invalidation).
2. Add a third case asserting "Deleting…" button text + disabled state while DELETE is in-flight (use msw's `delay()`).

## Locked decisions

None.

## Open questions for /spec-gen

None.

## Relationship to other work

- Subsumes `chore_query_inline_crud_e2e/idea.md` if the latter ships first (the E2E coverage is strictly stronger).

## Dependencies

- None.

## References

- GPT-5.5 phase-2 review F7 on feat_query_inline_crud.
- `ui/src/__tests__/components/query-sets/delete-query-dialog.test.tsx` — current unit coverage.
- `ui/src/__tests__/components/query-sets/queries-table.test.tsx` — current table coverage.
