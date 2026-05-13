# Idea — chore_query_inline_crud_e2e

**Date:** 2026-05-13
**Origin:** Deferred from `feat_query_inline_crud` spec §14 and implementation_plan §3.4. The feature ships with full unit + integration + contract + frontend-component coverage but no real-backend E2E test for `/query-sets/[id]` because no E2E suite for that route exists yet today.

## Problem

`/query-sets/[id]` does not have a Playwright spec at `ui/tests/e2e/`. The new per-query CRUD UX (Edit popover, Metadata dialog, Delete alert dialog with 409 toast) is only covered at the component / hook layer via msw mocks. The full operator path — open the page → click Delete → see 409 toast → click the action link → navigate to `/judgments/{id}` → delete the judgment list → return → retry delete → 204 — works against the running stack (verified manually during impl-execute operator-path checks) but has no automated regression coverage.

## Why deferred

* The `feat_query_inline_crud` spec §14 + implementation_plan §3.4 explicitly scoped this out: "Adding the first E2E test against a real backend on this feature is out of scope."
* Adding the first E2E spec for `/query-sets/[id]` requires Playwright fixture infrastructure (helper to seed a cluster + query set + queries + judgment list against a real backend) that doesn't exist yet. That's bigger than the per-query CRUD coverage gap on its own.

## Proposed scope (when this idea graduates to a spec)

1. Create `ui/tests/e2e/query_set_detail.spec.ts`:
   - Setup via API helpers: register a cluster, create a query set, bulk-add 3 queries via JSON, import a judgment list referencing query #1.
   - **Path 1 — inline edit:** open `/query-sets/{set_id}`, click row #2's Edit icon, fill `query_text="updated"`, click Save. Assert the row text changes in place.
   - **Path 2 — metadata clear:** open the metadata dialog on row #2, click "Clear metadata", assert the indicator changes to "—".
   - **Path 3 — delete-no-judgments:** open row #2's Delete dialog, confirm, assert 204 + row removed + table x-total-count decremented.
   - **Path 4 — delete-with-judgments-409:** open row #1's Delete dialog (which has the judgment from setup), confirm, assert the destructive toast contains "1 judgment list reference this query" + the action link to `/judgments/{list_id}`.
   - **Path 5 — click toast action → navigates** to `/judgments/{list_id}`. (Tests can stop there or chain to deletion + retry.)
2. The fixture for "register cluster + create query-set + bulk-add queries + import judgment-list" is reusable across other future E2E specs; build it in `ui/tests/e2e/helpers/`.
3. Tests run against the real backend at `http://localhost:8000`. CI gates added to `.github/workflows/pr.yml`.

## Locked decisions

None — design space is open until the wider Playwright infra ships.

## Open questions for /spec-gen

- Should E2E run on every PR or as a separate slow lane? Recommended default: on every PR for the canonical 5-path test, since the per-query CRUD surface is operator-visible and regressions ship to users.

## Relationship to other work

- Subsumes `chore_query_inline_crud_table_integration_test/idea.md` if shipped — the E2E covers the same row-removal / row-stays-present assertions at a more authoritative layer.
- Generic E2E infra (fixtures, helpers, CI lane) would benefit every future UI feature; landing it in this chore is appropriate.

## Dependencies

- Playwright already in `ui/package.json` and CI from `feat_studies_ui`. No new deps.

## References

- `feat_query_inline_crud/implementation_plan.md` §3.4 — original deferral.
- `feat_query_inline_crud/feature_spec.md` §14 — test strategy that defers E2E.
- `chore_query_inline_crud_table_integration_test/idea.md` — sibling for component-layer integration coverage.
