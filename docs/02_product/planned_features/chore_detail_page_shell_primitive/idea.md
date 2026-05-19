# Detail page shell primitive (`<DetailPageShell>`)

**Date:** 2026-05-18
**Status:** Idea — surfaced during a UI-refactor audit run after [`chore_form_dropdown_primitive`](../../../00_overview/implemented_features/2026_05_18_chore_form_dropdown_primitive/feature_spec.md) (PR #136) and [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/feature_spec.md) (PR #126) merged.
**Origin:** Audit prompted by user question "are there other UI components that would benefit from refactoring or applying best practices across the app?" after the two prior primitive extractions shipped.
**Depends on:** None — purely additive frontend chore. Can ship any time after PR #146.

## Problem

Six of the seven `/{entity}/[id]` detail routes hand-roll the same three-state scaffold around their data query. The pattern is **identical** down to the className strings and the exact text "Loading…" / "may have been deleted." — every site re-types it:

```tsx
{query.isPending ? (
  <Card>
    <CardContent>
      <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
    </CardContent>
  </Card>
) : query.isError ? (
  <EmptyState title="<Entity> not found" message="The <entity> may have been deleted." />
) : (
  /* the actual content */
)}
```

Concrete sites:

| File | Line | Entity label | Notes |
|---|---|---|---|
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) | 26-33 | "Cluster not found" | Exact pattern |
| [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/[id]/page.tsx) | 65-72 | "Study not found" | Exact pattern; also has `<Suspense fallback>` duplicated at line 116 |
| [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/[id]/page.tsx) | 138-148 | "Proposal not found" / "Backend unreachable" | Variant — distinguishes 404 from network error with **two** EmptyState branches. Other pages collapse both into a single "not found" message. UX inconsistency captured below. |
| [`ui/src/app/query-sets/[id]/page.tsx`](../../../../ui/src/app/query-sets/[id]/page.tsx) | 33-40 | "Query set not found" | Exact pattern |
| [`ui/src/app/templates/[id]/page.tsx`](../../../../ui/src/app/templates/[id]/page.tsx) | 31-38 | "Template not found" | Exact pattern |
| [`ui/src/app/judgments/[id]/page.tsx`](../../../../ui/src/app/judgments/[id]/page.tsx) | 58-65 | "Judgment list not found" | Exact pattern |

The seventh detail route — [`ui/src/app/chat/[id]/page.tsx`](../../../../ui/src/app/chat/[id]/page.tsx) — is **out of scope** for this primitive. The chat surface is a stream-rendered conversation, not a card-based detail page; its loading and error UX is structurally different.

Adjacent duplication, smaller scale but same cause:

- `<Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>` is duplicated in [`studies/[id]:116`](../../../../ui/src/app/studies/[id]/page.tsx), [`proposals/[id]:210`](../../../../ui/src/app/proposals/[id]/page.tsx), and [`judgments/[id]:103`](../../../../ui/src/app/judgments/[id]/page.tsx). The primitive can absorb this too — the Suspense outer wrapper is the page-level boundary; the inner three-state branch is the query boundary.

## Proposed capability

Ship `ui/src/components/common/detail-page-shell.tsx` — a generic React component that wraps a TanStack `UseQueryResult<T, ApiError>` and renders the appropriate state. The consumer provides the entity label and a render function for the success case; the primitive owns loading + error + 404 routing.

### Shape

```tsx
interface DetailPageShellProps<T> {
  query: UseQueryResult<T, ApiError>;
  entityLabel: string;          // e.g., "study", "proposal"
  notFoundMessage?: string;     // override for "may have been deleted"
  children: (data: T) => React.ReactNode;
}

<DetailPageShell query={studyQ} entityLabel="study">
  {(study) => (
    /* the actual content — identical to today's render path */
  )}
</DetailPageShell>
```

Behavior:

- `query.isPending` → render the `<Card><CardContent><p>Loading…</p></CardContent></Card>` placeholder.
- `query.isError && error.status === 404` → render `<EmptyState title="{Entity} not found" message="The {entity} may have been deleted." />`.
- `query.isError && error.status !== 404` (network / 5xx) → render `<EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />`. **This flattens the current UX inconsistency** — only `proposals/[id]` distinguishes today; all other pages collapse both errors into the "not found" branch, which is misleading when the API is just down.
- `query.data` defined → invoke `children(data)`.

### Lint guard

Add `ui/src/__tests__/components/common/detail-page-shell-discipline.test.tsx` paralleling [`data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) and [`form-select-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx).

The lint scans `ui/src/app/**/[id]/page.tsx` (excluding `chat/[id]`) and fails when:

- A file contains the literal string `"Loading…"` inside a JSX expression block (suggests hand-rolled loading state). Escape hatch: `// detail-page-shell-allow: <reason>` comment with a non-empty reason.
- A file contains `isPending ?` and `isError ?` ternaries on the same query without using `<DetailPageShell>`. (Direct AST match would be cleanest; a regex-based grep is fine for v1.)

This prevents future detail pages from reverting to inline scaffolding.

## Scope signals

- **Backend:** none.
- **Frontend:** new primitive (~80 LOC including loading Card + error routing), 6 page migrations (each loses ~10-15 LOC), one lint guard (~150 LOC paralleling the column-discipline guard).
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.
- **Tests:** existing E2E specs for the 6 affected detail routes continue to pass — the migration preserves all `data-testid` values and the visible "Loading…" / "<Entity> not found" copy. The lint guard adds one new vitest spec.
- **Docs:** [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) gains a "Detail page shell primitive" subsection paralleling the existing "DataTable primitive" and "Form dropdown primitive" entries. CLAUDE.md gains a one-line note that the lint covers detail pages in addition to column configs + form components.

## Why now (not skip, not defer)

The audit considered four candidates; three were rejected (confirm-to-delete dialogs — only 2 sites, wait for the 3rd; modal form scaffolding — fields too divergent; JSON/CSV/Jinja text editors — formats too different). Only this one cleared the duplication bar: **6 identical sites**, character-for-character duplication of the same className strings + copy.

This is the same shape that justified extracting `<DataTable>` (9 sites) and `<EntitySelect>` (7 FK sites + 1 UUID input). The primitive eliminates ~150-200 LOC of boilerplate, flattens the existing UX inconsistency between proposals and the other 5 pages, and locks down the 404 vs network-error distinction in one place.

Estimated PR size: ~350-450 LOC net (primitive + lint guard + 6 migrations). Single phase, no deferral, no spec-stage forks. Ships through `/pipeline` like its two predecessors.

## Relationship to other work

- **Extends:** `feat_data_table_primitive` (PR #126) and `chore_form_dropdown_primitive` (PR #136) — third primitive in the same extraction pattern.
- **Does not supersede:** [`ui/src/components/common/empty-state.tsx`](../../../../ui/src/components/common/empty-state.tsx) — the existing `<EmptyState>` primitive is consumed by `<DetailPageShell>`, not replaced.
- **Does not affect:** chat surface, list pages (those use `<DataTable>`), modal flows (those use `<EntitySelect>`).
