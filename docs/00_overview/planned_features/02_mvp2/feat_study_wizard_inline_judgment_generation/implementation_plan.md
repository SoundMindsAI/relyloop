# Implementation Plan — Study wizard: inline judgment generation

- **Primary spec:** [`feature_spec.md`](feature_spec.md)
- **Feature slug:** `feat_study_wizard_inline_judgment_generation`
- **Bucket:** `02_mvp2`
- **Status:** Draft
- **Scope:** Frontend-only. No backend, no migration, no new endpoints (Alembic head unchanged at `0022`).

## 1) FR → story traceability

| FR | Story | Notes |
|---|---|---|
| FR-2 (pre-target + lock dialog `defaultTarget`) | 1.1 | Optional prop on `<GenerateJudgmentsDialog>`; lock + seed-on-open |
| FR-1 (persistent inline generate affordance) | 1.2 | Button beneath the judgment-list select in the wizard |
| FR-3 (refresh judgment-list query after dispatch) | 1.2 | `useQueryClient().invalidateQueries(['judgment-lists'])` on dialog close |
| FR-4 (status in option label + conditional poll) | 1.3 | `getLabel` shows status; `useJudgmentLists` gains optional `refetchInterval` |

All 4 FRs covered. No endpoints (0 new), no error codes (0 new), no audit events, no migration.

## 2) Stories

### Epic 1 — Inline judgment generation in the Create-Study wizard (frontend-only)

#### Story 1.1 — `<GenerateJudgmentsDialog>` gains a `defaultTarget` prop (lock + seed-on-open)

**Outcome:** The dialog accepts an optional `defaultTarget?: string`. When supplied, the dialog's `target` field is seeded from it on open (and whenever `defaultTarget` changes) via explicit form state, and rendered **read-only**. When omitted, behavior is byte-identical to today (`target` defaults to `''`, editable).

**Modified files:**

| File | Change |
|---|---|
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | Add `defaultTarget?: string` to `GenerateJudgmentsDialogProps` (lines 63-68); add a `useEffect` keyed on `[open, defaultTarget]` that `form.setValue('target', defaultTarget)` when `open && defaultTarget != null`; render the `gen-target` `<Input>` (lines 272-277) with `readOnly={!!defaultTarget}` + a muted style + `aria-readonly` when locked. |

**Key interfaces:**

```ts
export interface GenerateJudgmentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clusterId: string;
  querySetId: string;
  /** When set (wizard context), seeds + LOCKS the target field so the
   *  generated list matches the caller's target filter. Omitted elsewhere. */
  defaultTarget?: string;
}
```

```tsx
// Seed on open / when defaultTarget changes (NOT via defaultValues — RHF
// applies those only at mount; a persistently-mounted dialog would keep a
// stale target). FR-2 / AC-2 / D-8.
useEffect(() => {
  if (open && defaultTarget != null) {
    form.setValue('target', defaultTarget);
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [open, defaultTarget]);
```

**Tasks:**
1. Add the optional prop.
2. Add the seed-on-open `useEffect`.
3. Render `gen-target` `readOnly` + muted when `defaultTarget` is set; keep `register('target', { required: true })` so submit still validates.
4. Component tests (see DoD).

**DoD:**
- AC-2: opening with `defaultTarget="products"` → `gen-target` value is `products` AND is read-only (`readOnly` / `aria-readonly`); changing the prop to `"docs"` and reopening shows `docs`.
- AC-6: no `defaultTarget` → `gen-target` value is `''` and editable (no `readOnly`).
- `pnpm typecheck`, `pnpm lint`, `pnpm vitest run` green for the dialog test file.

#### Story 1.2 — Wizard: persistent inline generate button + refetch on close

**Outcome:** The Create-Study wizard renders a "Generate judgments for this query set" button beneath the judgment-list `EntitySelect` whenever a query set + target are selected (prominent when the dropdown has no lists, a lighter secondary action otherwise). Clicking it opens `<GenerateJudgmentsDialog>` pre-targeted (cluster + query set + target). On close, the wizard invalidates `['judgment-lists']` so a freshly-dispatched list appears.

**Modified files:**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Add `import { useQueryClient } from '@tanstack/react-query'` + `import { GenerateJudgmentsDialog } from '@/components/query-sets/generate-judgments-dialog'`; add `const qc = useQueryClient()` and `const [genOpen, setGenOpen] = useState(false)`; render the inline `<Button>` + mount the dialog beneath the judgment-list field (region lines 970-990). |

**Key interfaces / handler:**

```tsx
const qc = useQueryClient();
const [genOpen, setGenOpen] = useState(false);

// Beneath the judgment-list EntitySelect (after line 989):
{querySetId && target && (
  <Button
    type="button"
    variant={judgmentLists.data?.data?.length ? 'ghost' : 'secondary'}
    size="sm"
    data-testid="cs-generate-judgments"
    onClick={() => setGenOpen(true)}
  >
    Generate judgments for this query set
  </Button>
)}
<GenerateJudgmentsDialog
  open={genOpen}
  onOpenChange={(o) => {
    setGenOpen(o);
    // Refetch on close: covers the UBI dispatch path (useGenerateJudgmentsFromUbi
    // does NOT invalidate ['judgment-lists']) and the cancel/reopen case. The LLM
    // path already invalidates (judgments.ts:154); this is an idempotent refetch.
    if (!o) qc.invalidateQueries({ queryKey: ['judgment-lists'] });
  }}
  clusterId={clusterId}
  querySetId={querySetId}
  defaultTarget={target}
/>
```

**Tasks:**
1. Add the imports, `qc`, and `genOpen` state.
2. Render the inline button beneath the judgment-list `EntitySelect` (gated on `querySetId && target`; variant by whether lists exist).
3. Mount `<GenerateJudgmentsDialog>` with `clusterId`/`querySetId`/`defaultTarget={target}` and the invalidate-on-close handler.
4. Keep the existing `EntitySelect` `emptyState` `/judgments` link (secondary escape, D-5).
5. Component tests (see DoD).

**DoD:**
- AC-1: with a query set + target selected, the `cs-generate-judgments` button is present both when `judgmentLists` is empty AND when it lists only a `failed` list; clicking sets the dialog `open`.
- AC-3: after the dialog dispatches and closes, the wizard's judgment-list query is invalidated (assert `qc.invalidateQueries` called / refetch fired) and a newly-present list renders in the dropdown.
- AC-7: closing the dialog (`onOpenChange(false)`) invalidates `['judgment-lists']` independently of the LLM hook (covers the UBI path).
- The wizard does not unmount / lose Step-1 form state while the dialog is open.

#### Story 1.3 — Status in the option label + conditional poll

**Outcome:** The judgment-list dropdown shows a list's `status` in its label when it is not `complete` (`"<name> · generating"`, `"<name> · failed"`). While any list in the current filter is `generating`, `useJudgmentLists` polls (bounded `refetchInterval`) until none remain, so the label flips to `complete` without a manual refresh.

**Modified files:**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Import status values from `@/lib/enums` (no inline literals, spec §7.4); change the judgment-list `EntitySelect` `getLabel` (line 977) to append status when not `complete`; pass `refetchInterval` via the new `options` arg of `useJudgmentLists` (call at lines 386-391). |
| [`ui/src/lib/api/judgments.ts`](../../../../ui/src/lib/api/judgments.ts) | Add a SECOND optional `options` parameter to `useJudgmentLists(filter, options?)` carrying `refetchInterval`, threaded ONLY into the `useQuery` options — NOT into `JudgmentListsFilter`, the queryKey, or the request params (keeps the API filter surface clean; GPT-5.5 plan finding #1). Backward-compatible (omitted → no polling). |

**Key interfaces:**

```ts
// judgments.ts — separate query-behavior options from the API filter. Do NOT
// add refetchInterval to JudgmentListsFilter (it must not enter the queryKey or
// request params). GPT-5.5 plan finding #1.
import type { UseQueryOptions } from '@tanstack/react-query';

export interface UseJudgmentListsOptions {
  refetchInterval?: UseQueryOptions<JudgmentListsPage, ApiError>['refetchInterval'];
}

export function useJudgmentLists(
  filter: JudgmentListsFilter = {},
  options: UseJudgmentListsOptions = {},
): UseQueryResult<JudgmentListsPage, ApiError> {
  // ...existing queryKey/queryFn unchanged...
  // useQuery({ queryKey, queryFn, refetchInterval: options.refetchInterval })
}
```

```tsx
// create-study-modal.tsx — getLabel (line 977). Status compared via the
// imported source-of-truth values, NOT inline string literals (spec §7.4).
import { JUDGMENT_LIST_STATUS_VALUES, type JudgmentListStatus } from '@/lib/enums';
// Source-of-truth: ui/src/lib/enums.ts JUDGMENT_LIST_STATUS_VALUES
const COMPLETE: JudgmentListStatus = 'complete';
const GENERATING: JudgmentListStatus = 'generating';
// getLabel:
getLabel={(j) => (j.status && j.status !== COMPLETE ? `${j.name} · ${j.status}` : j.name)}

// useJudgmentLists call (lines 386-391) gains the options arg:
const judgmentLists = useJudgmentLists(
  { query_set_id: querySetId || undefined, cluster_id: clusterId || undefined, target: target || undefined, limit: 200 },
  { refetchInterval: (q) => (q.state.data?.data?.some((j) => j.status === GENERATING) ? 4000 : false) },
);
```

**Tasks:**
1. Add the optional `options` param + `UseJudgmentListsOptions` to `useJudgmentLists`; thread `refetchInterval` into `useQuery` only (not the filter/queryKey/params).
2. Update the wizard `getLabel` to surface non-`complete` status, importing the status values from `@/lib/enums` (no inline literals; spec §7.4) with a source-of-truth comment.
3. Pass the conditional `refetchInterval` fn via the new `options` arg from the wizard.
4. Component tests (see DoD).

**DoD:**
- AC-4: a `generating` list renders `"<name> · generating"`, a `failed` list `"<name> · failed"`, a `complete` list just `"<name>"`.
- AC-5 (label): with fake timers + a mocked `useJudgmentLists` returning `generating` then `complete`, the label transitions from `"<name> · generating"` to `"<name>"` with no manual refresh.
- AC-5 (plumbing): a hook-level test (`judgments.test.tsx`) with a real `QueryClient` + mocked `apiClient` + fake timers asserts a second fetch fires while a `generating` list is present and stops once all are `complete` — proving `refetchInterval` is wired through `useQuery` (not bypassed by a component-boundary mock).
- No unconditional polling: with only `complete` lists, `refetchInterval` resolves to `false` (D-6).
- Existing call sites of `useJudgmentLists` (judgments list page, etc.) are unaffected (no `refetchInterval` passed → undefined).

## 3) Testing workstream

| Layer | File | Story | Covers |
|---|---|---|---|
| Component (vitest) | `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` (extend existing) | 1.1 | AC-2, AC-6 (defaultTarget lock + seed-on-open; backward-compat) |
| Component (vitest) | `ui/src/__tests__/components/studies/create-study-modal.inline-generate.test.tsx` (new) | 1.2, 1.3 | AC-1, AC-3, AC-4, AC-5 (label transition), AC-7 |
| Hook (vitest) | `ui/src/__tests__/lib/api/judgments.test.tsx` (new) | 1.3 | `useJudgmentLists` `refetchInterval` plumbing — real `QueryClient` + mocked `apiClient` + fake timers: a SECOND fetch fires while a `generating` list is present and STOPS once all `complete` (anchored to `ui/src/__tests__/lib/api/clusters.test.tsx`). Proves the option is actually wired through `useQuery`, not bypassed by a boundary mock (GPT-5.5 plan finding, cycle 2). |
| E2E (Playwright, real backend) | `ui/tests/e2e/studies-create-inline-generate.spec.ts` (new) | 1.3 (DoD) | AC-1 → AC-3 + select list + Next enables |

**E2E shape** (anchored to `ui/tests/e2e/studies-create-validation.spec.ts` + `helpers/seed.ts`):
- Setup via API helpers: `seedCluster()` + `seedQuerySet(...)` (creates a query set with NO judgment list).
- Browser (`page`): open the Create-Study wizard, select the cluster → query set → a target; assert the `cs-generate-judgments` button is visible; click it; assert the dialog `gen-target` is pre-filled with the chosen target AND read-only; dispatch generation via a method; assert the new judgment list appears in the `cs-jl` dropdown (as `generating`); **select it and assert the Step-1 "Next" button enables** (`stepValid` only needs `query_set_id && judgment_list_id` — line 672 — so a `generating` list is selectable per D-3; this exercises the full continuation without waiting for `complete`).
- The generation dispatch hits the real worker. Gate the dispatch+appears+select assertion behind the same availability guard existing judgment E2E uses (`judgments.spec.ts` pattern); the button-visible + target-locked assertions (AC-1, AC-2) run unconditionally. Do NOT wait for `complete` in E2E — AC-5 (generating→complete relabel) is covered at the component layer with fake timers (documented exception to spec §14's "AC-5 via E2E"; the select/Next-enables browser assertion required by §14 IS included here).
- No `page.route()` mocking — real backend, browser assertions only.

## 4) UI Guidance

### Insertion point

In [`create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx), Step-1 block. The judgment-list field is lines 970-990 (Label `cs-jl` + `EntitySelect`). Insert the inline `<Button>` immediately after the `EntitySelect`'s closing tag (line 989) and the `<GenerateJudgmentsDialog>` mount within the same Step-1 fragment. Nothing above (query-set field, 955-968) or the Step gate (672) is removed.

### Analogous markup patterns

The wizard already imports `Button` (line 15) and `EntitySelect` (line 13) and mounts dialogs elsewhere. `<GenerateJudgmentsDialog>` is a Radix `Dialog` (verified) and is already mounted from the query-set detail page with `open`/`onOpenChange`/`clusterId`/`querySetId`; the wizard mounts it identically plus `defaultTarget`. Button variant pattern mirrors existing wizard secondary actions (`variant="ghost"`/`"secondary"`, `size="sm"`).

### Layout and structure

The inline button sits directly under the judgment-list dropdown, left-aligned, small. When `judgmentLists.data` is empty it reads as the primary next step (variant `secondary`); when lists exist it is a lighter `ghost` "generate another / retry" action. The dialog opens as a modal layered over the wizard modal; on close, focus returns to Step 1.

### Confirmation/modal dialog pattern

Reuses `<GenerateJudgmentsDialog>` verbatim (its own Radix `Dialog`). No new dialog scaffolding.

### Visual consistency table

| New element | Pattern source |
|---|---|
| `cs-generate-judgments` `<Button>` | `@/components/ui/button` `Button` (variant `ghost`/`secondary`, `size="sm"`) as used elsewhere in the wizard |
| Locked `gen-target` `<Input>` | `@/components/ui/input` `Input` + `readOnly` + muted class (mirrors existing read-only inputs) |
| Status suffix in option label | plain string interpolation in `getLabel` (no new component) |

### Component composition

Inline within `create-study-modal.tsx` (button + dialog mount) — no new component extracted (the generation UI is already a reusable component). Rationale: the only new markup is a button + an existing dialog instance; extraction would add indirection without reuse.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Selects a query set with no judgment list | dropdown empty-state + `cs-generate-judgments` button shown | `GET /api/v1/judgment-lists` (existing, via `useJudgmentLists`) |
| Clicks "Generate judgments for this query set" | `setGenOpen(true)` → dialog opens, target pre-filled + locked | none (until submit) |
| Submits generation in the dialog | dialog dispatches + closes; toast | `POST /api/v1/judgments/generate` (LLM) or `/generate-from-ubi` (UBI) — existing |
| Dialog closes | `qc.invalidateQueries(['judgment-lists'])` → dropdown refetches | `GET /api/v1/judgment-lists` |
| A list is `generating` | dropdown polls every 4s until none generating | `GET /api/v1/judgment-lists` (conditional `refetchInterval`) |

### Handler function patterns

(See Story 1.2 / 1.3 key-interface blocks above — `onOpenChange` invalidate-on-close, `getLabel` status suffix, conditional `refetchInterval` fn.)

### Information architecture placement

Inside Step 1 of the Create-Study wizard (`create-study-modal.tsx`), in the judgment-list field group. No new top-level nav. Discovery: the operator hits it exactly when blocked (empty judgment-list dropdown) — the affordance is co-located with the gap. Matches spec §11.

### Tooltips and contextual help

No new glossary keys (spec §11). The button label and the existing `EntitySelect` empty-state message are self-explanatory; the dialog carries its own `judgment.converter` `HelpPopover` (existing). No `ui/src/lib/glossary.ts` change.

### Enumerated value contracts

| Frontend usage | Wire values | Source of truth |
|---|---|---|
| `getLabel` status suffix (display only — `status` is NOT sent to the backend) | `generating`, `complete`, `failed` | `ui/src/lib/enums.ts:156` `JUDGMENT_LIST_STATUS_VALUES`; backend CHECK `backend/app/db/models/judgment_list.py:41`. Add a `// Source-of-truth: ui/src/lib/enums.ts JUDGMENT_LIST_STATUS_VALUES` comment above the `getLabel`/poll predicate; if a literal constant is referenced, import from `@/lib/enums`. |

No frontend option list whose value is sent to the backend is added (the status is read-only display). The `defaultTarget`/`target` value is a free-text index name (already operator-typed today), not an enum.

### Legacy behavior parity

N/A — no user-facing component >100 LOC is deleted or replaced. The change is additive (a button + a dialog mount + a label suffix + an optional hook param). The existing `EntitySelect` `emptyState` `/judgments` link is **retained** (D-5).

## 5) Sequencing

1. **Story 1.1** first — the dialog prop is a dependency for Story 1.2's mount (`defaultTarget`).
2. **Story 1.2** — mounts the dialog + inline button + refetch.
3. **Story 1.3** — status label + poll (independent of 1.2's button but shares the file; sequential, additive).
4. Tests land with their owning stories; the E2E lands with Story 1.3 (completes the testable surface).

No cross-subsystem dependency, no migration, no backend story.

## 6) Risks

| Risk | L | I | Mitigation |
|---|---|---|---|
| `defaultTarget` seed via `defaultValues` would go stale on a mounted dialog | M | M | Explicit `form.setValue` in a `useEffect` keyed on `[open, defaultTarget]` (Story 1.1) — NOT `defaultValues`. |
| Unconditional polling churns the network on an idle open wizard | M | L | `refetchInterval` is a function returning `false` unless a `generating` list is present (Story 1.3, D-6). |
| Query-behavior option pollutes the API filter / cache key | M | M | `refetchInterval` lives in a SEPARATE `options` param of `useJudgmentLists`, threaded only into `useQuery` — never into `JudgmentListsFilter`, the queryKey, or request params (Story 1.3; GPT-5.5 plan finding #1). |
| E2E flakiness from waiting on async generation | M | M | E2E asserts only up to "list appears (`generating`)"; the generating→complete transition is a component test with fake timers, not E2E. |
| Operator generates with a mismatched target | L | M | Target field is locked read-only when opened from the wizard (Story 1.1, FR-2). |

## 7) Plan consistency review

- **FR coverage:** all 4 FRs mapped to stories (§1). ✅
- **Endpoint/error-code parity:** spec has 0 new endpoints, 0 new error codes — plan adds none. ✅
- **File ownership:** `generate-judgments-dialog.tsx` (1.1), `create-study-modal.tsx` (1.2 then 1.3, sequential additive), `judgments.ts` (1.3) — no conflicting ownership. ✅
- **Test assignment:** dialog test (1.1), wizard component test (1.2+1.3), E2E (1.3). Every test file assigned. ✅
- **UI Guidance completeness:** all required subsections present (insertion point, analogous markup, layout, dialog pattern, visual table, composition, interaction table, handlers, IA, tooltips, enum contract, legacy parity N/A). ✅
- **Audit events:** none (no state-mutating server surface added). ✅
- **Migration:** none (head stays `0022`). ✅

## 8) Execution tracker

### Current sprint
- [x] Story 1.1 — `<GenerateJudgmentsDialog>` `defaultTarget` (lock + seed-on-open)
- [x] Story 1.2 — wizard inline generate button + refetch on close
- [x] Story 1.3 — status in option label + conditional poll

### Blocked items
- None.
