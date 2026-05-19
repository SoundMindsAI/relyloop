# Detail page shell primitive (`<DetailPageShell>`)

**Date:** 2026-05-18
**Status:** Idea — surfaced during a UI-refactor audit run after [`chore_form_dropdown_primitive`](../../../00_overview/implemented_features/2026_05_18_chore_form_dropdown_primitive/feature_spec.md) (PR #136) and [`feat_data_table_primitive`](../../../00_overview/implemented_features/2026_05_16_feat_data_table_primitive/feature_spec.md) (PR #126) merged.
**Origin:** Audit prompted by user question "are there other UI components that would benefit from refactoring or applying best practices across the app?" after the two prior primitive extractions shipped.
**Depends on:** None — purely additive frontend chore. Can ship any time after PR #146.

## Problem

Six of the seven `/{entity}/[id]` detail routes hand-roll the same three-state scaffold around their data query. The structure is **identical** down to the className strings, with two minor copy variants the migration can normalize (see table below — "deleted" vs "removed"):

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
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) | 26-33 | "Cluster not found" | Says "may have been **deleted**" |
| [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/[id]/page.tsx) | 65-72 | "Study not found" | Says "**deleted**"; also has `<Suspense fallback>` duplicated at line 116 (see "Adjacent duplication" below) |
| [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/[id]/page.tsx) | 138-148 | "Proposal not found" / "Backend unreachable" | Says "**deleted**". Variant — discriminates 404 from network error via `proposalQ.error?.errorCode === 'PROPOSAL_NOT_FOUND'` (line 145). Other 5 pages collapse both errors into the single "not found" branch — a latent UX bug captured below. |
| [`ui/src/app/query-sets/[id]/page.tsx`](../../../../ui/src/app/query-sets/[id]/page.tsx) | 33-40 | "Query set not found" | Says "**deleted**" |
| [`ui/src/app/templates/[id]/page.tsx`](../../../../ui/src/app/templates/[id]/page.tsx) | 31-38 | "Template not found" | Says "may have been **removed**" — copy variant |
| [`ui/src/app/judgments/[id]/page.tsx`](../../../../ui/src/app/judgments/[id]/page.tsx) | 58-65 | "Judgment list not found" | Says "**removed**" — copy variant |

The seventh detail route — [`ui/src/app/chat/[id]/page.tsx`](../../../../ui/src/app/chat/[id]/page.tsx) — is **out of scope** for this primitive. The chat surface is a stream-rendered conversation, not a card-based detail page; its loading and error UX is structurally different.

Adjacent duplication, surfaced but **out of scope** for this primitive:

- **Back-link header.** All 6 in-scope pages (and `chat/[id]`) precede the three-state branch with a `<div><Link href="/{list}" className="text-sm text-blue-600 underline-offset-4 hover:underline">← All {entities}</Link></div>` block. The primitive could expose a `backHref?` / `backLabel?` slot — see Open question Q2.
- **Suspense fallback** at `<Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>` appears in 3 of 6 in-scope pages: [`studies/[id]:116`](../../../../ui/src/app/studies/[id]/page.tsx), [`proposals/[id]:210`](../../../../ui/src/app/proposals/[id]/page.tsx), [`judgments/[id]:103`](../../../../ui/src/app/judgments/[id]/page.tsx). The other 3 (`clusters`, `templates`, `query-sets`) do not have a Suspense boundary. **The primitive cannot absorb this** — Next.js App Router requires a Suspense boundary around any component that calls `useSearchParams()` / `useParams()` during hydration, which is the reason the 3 affected pages have one. The Suspense wrapper serves Next.js's hydration contract, not the data-fetching loading state (that's `query.isPending`'s job). Leave the Suspense duplication alone in this PR; a separate idea can extract a `<PageSuspense>` wrapper if duplication grows.

## Proposed capability

Ship `ui/src/components/common/detail-page-shell.tsx` — a generic React component that wraps a TanStack `UseQueryResult<T, ApiError>` and renders the appropriate state. The consumer provides the entity label and a render function for the success case; the primitive owns loading + error + 404 routing.

### Shape

```tsx
interface DetailPageShellProps<T> {
  query: UseQueryResult<T, ApiError>;
  entityLabel: string;             // singular, e.g., "study", "proposal"; used in default message copy
  entityTitle?: string;            // optional title override — defaults to title-case of entityLabel.
                                   // Needed for cases like "Judgment list not found" where the
                                   // title and message use different casing/wording.
  notFoundErrorCode: string;       // e.g., "STUDY_NOT_FOUND" — per backend error envelope
  notFoundMessage?: string;        // optional override for the default "may have been deleted" copy
  unreachableMessage?: string;     // optional override for non-404 errors
  children: (data: T) => React.ReactNode;
}

<DetailPageShell
  query={studyQ}
  entityLabel="study"
  notFoundErrorCode="STUDY_NOT_FOUND"
>
  {(study) => (
    /* the actual content — identical to today's render path */
  )}
</DetailPageShell>
```

Behavior:

- `query.isPending` → render the `<Card><CardContent><p>Loading…</p></CardContent></Card>` placeholder.
- `query.isError && error.errorCode === notFoundErrorCode` → render `<EmptyState title="{Entity} not found" message="The {entity} may have been deleted." />`. The consumer passes the expected 404 error code (e.g., `'STUDY_NOT_FOUND'`, `'PROPOSAL_NOT_FOUND'`) — RelyLoop's `ApiError` discriminates by `errorCode` string per [`ui/src/lib/api-client.ts:72-92`](../../../../ui/src/lib/api-client.ts), not by HTTP status.
- `query.isError && error.errorCode !== notFoundErrorCode` (network / 5xx / non-404 server errors) → render `<EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />`. **This flattens the current UX inconsistency** — only `proposals/[id]` distinguishes today; the other 5 pages collapse both errors into "{Entity} not found", which is misleading when the API is just down.
- `query.data` defined → invoke `children(data)`.
- **Copy normalization:** the migration adopts a single canonical phrase "The {entity} may have been deleted." for the 404 message, replacing the templates/judgments "removed" variant. Decision locked — "deleted" is the majority (4 of 6) and matches the operator mental model (entities are soft-deleted, not "removed").

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

The audit considered four candidates; three were rejected (confirm-to-delete dialogs — only 2 sites, wait for the 3rd; modal form scaffolding — fields too divergent; JSON/CSV/Jinja text editors — formats too different). Only this one cleared the bar: **6 sites with identical structural scaffolding** (className strings + 3-state ternary verified character-for-character).

This is the same shape that justified extracting `<DataTable>` (8 column-config migrations + 1 thin-wrap inheritance) and `<EntitySelect>` (7 FK sites + 1 UUID input across 4 modals).

**The ROI is consistency, not LOC.** The inline scaffolding being removed is ~10 LOC × 6 sites = ~60 LOC at the call sites; the new primitive (~80 LOC) + lint guard (~150 LOC) makes this a +170 LOC PR, not a code-shrink. The wins are:

1. **Latent UX bug fixed in one place.** Today only `proposals/[id]` distinguishes "not found" from "backend unreachable"; after this PR all 6 pages do, behind one implementation that's testable in one place.
2. **Copy normalization.** "deleted" vs "removed" inconsistency disappears.
3. **Future detail pages get correct behavior for free.** Adding a new `/foo/[id]` page becomes a 3-line invocation, not a 30-line copy-paste plus another point of inconsistency.
4. **Lint guard locks the discipline in.** No regression-by-inlining when a future contributor copies an old page as a template.

Estimated PR size: ~350-450 LOC net (primitive + lint guard + 6 migrations). Single phase, no deferral, no spec-stage forks. Ships through `/pipeline` like its two predecessors.

## Open questions for /spec-gen

These need a spec-time decision with a recommended default:

- **Q1 — Children-as-function vs compound (`<DetailPageShell.Body>`) API.** Recommended default: `children: (data: T) => React.ReactNode` callback. Rationale: simpler signature, matches the existing render-props feel of `<EntitySelect>`, no need to learn a compound component API. Compound would be more flexible (e.g., separate slots for header, body, footer) but no current page needs that.
- **Q2 — Absorb the back-link header?** Recommended default: **no** for v1. Keep the primitive focused on the three-state branch; ship the back-link header as a separate `<DetailBreadcrumb>` follow-up if duplication actually grows (only 1 new detail route in MVP1 likely). Counter-argument: absorbing it now eliminates 6 more lines per page and would let `chat/[id]` consume the breadcrumb half of the primitive even though it doesn't consume the three-state half. Spec stage to decide.
- **Q3 — Lint guard implementation: regex vs AST.** Recommended default: regex-based scan of file contents for `isPending ?` adjacent to `isError ?` outside `<DetailPageShell>`. Cheaper to ship than AST-based, matches the existing `data-table-column-discipline.test.tsx` v1 style. Upgrade to AST only if false positives become a problem.

## Relationship to other work

- **Extends:** `feat_data_table_primitive` (PR #126) and `chore_form_dropdown_primitive` (PR #136) — third primitive in the same extraction pattern.
- **Does not supersede:** [`ui/src/components/common/empty-state.tsx`](../../../../ui/src/components/common/empty-state.tsx) — the existing `<EmptyState>` primitive is consumed by `<DetailPageShell>`, not replaced.
- **Does not affect:** chat surface, list pages (those use `<DataTable>`), modal flows (those use `<EntitySelect>`).
- **Sibling check (clean):** no overlapping planned features under `docs/02_product/planned_features/`. No coordination required.
