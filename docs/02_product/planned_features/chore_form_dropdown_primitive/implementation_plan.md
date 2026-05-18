# Implementation Plan — Form Dropdown Primitive (`<EntitySelect>`)

**Date:** 2026-05-18
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) §"Enumerated Value Contract Discipline" · [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) §"DataTable primitive" (parent pattern)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from the spec's §17 matrix.
- Three-tier delivery: Epic 1 ships the primitive + lint guard (no consumer migration yet); Epic 2 migrates four consumer modals; Epic 3 lands the doc updates. Each epic gate is a hard stop.
- All migrations preserve `data-testid` / `id` / `htmlFor` exactly — the spec FR-8 + AC-13 + AC-14 are the verifiable invariants.
- Fail-loud tests: vitest assertions are explicit about combobox role, data-testid presence, and lint-guard error messages.
- Behavior parity over component count: the lint-guard test (`form-select-discipline.test.tsx`) is more important than any single consumer migration because it locks the convention against future regression.
- Keep increments narrow: each consumer migration is one story so that a CI failure on one modal doesn't block the others.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Phase | Stories | Notes |
|---|---|---|---|
| FR-1 (`<EntitySelect>` primitive renders controlled shadcn `<Select>`) | Epic 1 | Story 1.1 | All baseline rendering behavior. |
| FR-2 (loading state) | Epic 1 | Story 1.1 | Verified by `entity-select.test.tsx`. |
| FR-3 (error state + retry) | Epic 1 | Story 1.1 | Inline retry button invokes `refetch()`. |
| FR-4 (empty state with CTA) | Epic 1 | Story 1.1 | Uses Next.js `<Link>`. |
| FR-5 (disabled subset) | Epic 1 | Story 1.1 | `disabledIds: ReadonlySet<string>` + `disabledReason?`. |
| FR-6 (status indicator opt-in) | Epic 1 | Story 1.1 | `getStatus` + status-sort + `inlineWarning`. |
| FR-7 (form-select-discipline lint guard) | Epic 1 | Story 1.2 | Mirrors `data-table-column-discipline.test.tsx`. |
| FR-8 (migrate 4 modals) | Epic 2 | Story 2.1 (create-query-set), Story 2.2 (create-study), Story 2.3 (register-cluster), Story 2.4 (generate-judgments) | Preserve `data-testid` + `id` + `htmlFor`. |
| FR-9 (docs) | Epic 3 | Story 3.1 (ui-architecture.md), Story 3.2 (CLAUDE.md), Story 3.3 (tutorial-first-study.md) | All ship in the same PR. |

All FRs covered. No deferred phases — the spec is single-phase per §3.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Three epics, 9 stories total.

### Story-level detail requirements

Every story below includes: Outcome · New files · Modified files · Endpoints (if API-touching — none in this plan) · Key interfaces (if introducing TypeScript types or function signatures) · UI element inventory (if frontend) · Tasks · Definition of Done.

### Conventions (RelyLoop frontend)

- `'use client'` directive at the top of every interactive component.
- Imports ordered: external (`react`, `lucide-react`, `@tanstack/react-query`) → internal absolute (`@/components/...`, `@/lib/...`) → relative.
- Path alias `@/` resolves to `ui/src/`.
- shadcn primitives composed from `@/components/ui/select`, `@/components/ui/button`, `@/components/ui/label`.
- TanStack hooks consumed unchanged (no new hook signatures); the primitive accepts the hook itself as a prop.
- Vitest tests co-located under `ui/src/__tests__/components/<resource>/<component>.test.tsx` mirror the structure used by the rest of the UI (3 existing form-modal test files already follow this pattern).
- Test wrapping: `QueryClient` with `retry: false` + `QueryClientProvider`; msw for backend mocking; `fireEvent` + `screen` from `@testing-library/react`.
- No new pnpm dependencies introduced — every primitive imports already exist in the repo.

### AI Agent Execution Protocol

For each story:

0. **Load context first**: read `architecture.md` and `state.md`. Confirm the branch is `claude/review-dropdown-ideas-M9Jon` and the current Alembic head is `0013` (no migration changes in this feature, but verify nothing else changed).
1. **Read scope**: confirm Outcome + New/Modified files + UI inventory + DoD.
2. **Implement** the story atomically — no half-finished commits.
3. **Run targeted tests**:
   - For Story 1.1: `cd ui && pnpm test src/__tests__/components/common/entity-select.test.tsx`.
   - For Story 1.2: `cd ui && pnpm test src/__tests__/components/common/form-select-discipline.test.tsx`.
   - For Stories 2.x: `cd ui && pnpm test src/__tests__/components/<resource>/`. Run the relevant E2E if a `data-testid` was touched: `cd ui && pnpm exec playwright test tests/e2e/guides/09_generate_judgments_llm.spec.ts` (Story 2.4 in particular).
4. **Run wider gates** before committing the story: `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`. All four must pass.
5. **No backend changes** in any story — `make test-unit`, `make test-integration`, `make test-contract` are unaffected. Run `make test-unit` once at the end of the epic anyway to confirm the cross-cutting nothing-broke property.
6. **Commit per story** with Conventional Commits: `feat(ui):` for the primitive, `test(ui):` for the lint guard, `refactor(ui):` for migrations, `docs:` for Epic 3.
7. **Run the column-discipline test alongside the new form-discipline test** to verify the two lint guards don't share file-walker assumptions that conflict.

---

## Epic 1 — Primitive + lint guard

### Story 1.1 — `<EntitySelect>` primitive with full FR-1 through FR-6 behavior

**Outcome:** A new generic React component `EntitySelect<T>` exists at `ui/src/components/common/entity-select.tsx`. The component renders a controlled shadcn `<Select>` family, accepts a TanStack listing hook as `useEntities`, handles loading / error / empty / disabled / status / warning slots, and is covered by a co-located vitest with ≥10 cases.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/entity-select.tsx` | The primitive. ~150-200 LOC. Generic over entity type `T`; consumes `useEntities` + `getId` + `getLabel` callbacks; renders shadcn `<Select>` with loading / error / empty / status / warning behaviors per FR-1 through FR-6. |
| `ui/src/__tests__/components/common/entity-select.test.tsx` | Vitest suite. ~250-350 LOC. Covers: controlled-value rendering, loading state, error state with retry, empty state with + without CTA, status dot rendering, status-sort, inline warning, disabled subset with tooltip, data-testid passthrough, id passthrough. |

**Modified files**

| File | Change |
|---|---|
| (none) | Story 1.1 is purely additive. No existing file is touched. |

**Endpoints**: N/A (frontend-only, consumes existing endpoints unchanged).

**Key interfaces**

```typescript
// ui/src/components/common/entity-select.tsx

import type { UseQueryResult } from '@tanstack/react-query';
import type { ApiError } from '@/lib/api-errors';

export type EntityStatus = 'green' | 'yellow' | 'red' | 'unknown';

export interface EntitySelectEmptyState {
  message: string;
  cta?: { label: string; href: string };
}

export interface EntitySelectProps<T> {
  /** The TanStack listing hook (passed as a value, called inside the primitive). */
  useEntities: () => UseQueryResult<{ data: T[]; next_cursor?: string | null; has_more?: boolean }, ApiError>;
  /** Required: extract the wire id used for value/onChange. */
  getId: (entity: T) => string;
  /** Required: extract the display label. */
  getLabel: (entity: T) => string;
  /** Controlled value (the selected entity's id, or undefined). */
  value: string | undefined;
  /** Controlled-value setter. */
  onChange: (next: string | undefined) => void;
  /** Optional: render a status dot (●) before the label and sort green-first. */
  getStatus?: (entity: T) => EntityStatus;
  /** Optional: render a warning under the trigger when the selected entity yields non-null. */
  inlineWarning?: (entity: T | undefined) => string | null;
  /** Optional: which entities render disabled. */
  disabledIds?: ReadonlySet<string>;
  /** Optional: tooltip text for a disabled item (via title attribute). */
  disabledReason?: (entity: T) => string | null;
  /** Optional: rendered when the loaded list is empty. */
  emptyState?: EntitySelectEmptyState;
  /** Optional: SelectTrigger placeholder when nothing is selected and the list is non-empty. Defaults to "Select…". */
  placeholder?: string;
  /** Optional: loading-state placeholder. Defaults to "Loading…". */
  loadingPlaceholder?: string;
  /** Optional: passthrough to the rendered SelectTrigger. */
  id?: string;
  /** Optional: passthrough to the rendered SelectTrigger. */
  'data-testid'?: string;
}

export function EntitySelect<T>(props: EntitySelectProps<T>): React.JSX.Element;
```

**Pydantic schemas**: N/A.

**UI element inventory**

Story 1.1 creates these visible elements (composed from existing shadcn primitives, all already in the repo):

1. **SelectTrigger** (button rendered by shadcn `<SelectTrigger>` — Radix Trigger under the hood). Carries the consumer's `id` and `data-testid` props verbatim. Disabled when loading / error / empty / data unavailable. Renders the selected entity's label or the active placeholder.
2. **Selected-value display** (inside the SelectTrigger via shadcn `<SelectValue>`): the resolved label of the selected entity, or the placeholder text.
3. **SelectContent → SelectItem** (one per entity, sorted by status when `getStatus` is provided): renders `<span aria-hidden="true" className="<color>">●</span> <label>`. Carries `data-disabled` when in `disabledIds` and the `title` attribute when `disabledReason(entity)` returns non-null.
4. **Inline retry button** (rendered ONLY in error state, adjacent to the trigger): `<button type="button" onClick={refetch}>Retry</button>` with `text-xs` styling consistent with helper-text patterns elsewhere.
5. **Empty-state inline link** (rendered ONLY when `data.data.length === 0` and `emptyState.cta` is provided): `<Link href={cta.href} className="text-xs underline">{cta.label}</Link>`.
6. **Inline warning** (rendered ONLY when `inlineWarning(selectedEntity)` returns non-null): `<p className="text-xs text-amber-600 mt-1">{warningText}</p>` — styled to match the existing helper text at `create-study-modal.tsx:265-267`.

**State dependency analysis**

The primitive owns NO global or shared state. Its internal state is limited to the values returned by `useEntities()` (TanStack-managed) and the consumer-controlled `value` / `onChange` pair. There are no `useEffect` calls, no `useRef`, no cross-component state.

The single subtle case: status-sort needs a memoized array to avoid re-sorting on every render. Use `React.useMemo` keyed on `data.data` and `getStatus` identity.

```typescript
const sortedEntities = useMemo(() => {
  if (!getStatus || !data?.data) return data?.data ?? [];
  const order: Record<EntityStatus, number> = { green: 0, yellow: 1, red: 2, unknown: 3 };
  // Stable sort: pair each entity with its index, sort by status precedence then index.
  return [...data.data]
    .map((entity, index) => ({ entity, index, status: getStatus(entity) }))
    .sort((a, b) => order[a.status] - order[b.status] || a.index - b.index)
    .map(({ entity }) => entity);
}, [data?.data, getStatus]);
```

**Tasks**

1. Create `ui/src/components/common/entity-select.tsx`. Define the `EntitySelectProps<T>` interface exactly as above. Export `EntityStatus`, `EntitySelectEmptyState`, `EntitySelectProps`, and the `EntitySelect` component.
2. Implement the body:
   - Call `useEntities()` to obtain `{ data, isLoading, isError, refetch }`.
   - Compute `selectedEntity = data?.data.find((e) => getId(e) === value)` (memoized on `data?.data`, `getId`, `value`).
   - Compute `sortedEntities` via the `useMemo` block above.
   - Render the JSX tree:
     - If `isLoading`: `<SelectTrigger disabled>{loadingPlaceholder ?? 'Loading…'}</SelectTrigger>` only (no SelectContent).
     - If `isError`: `<div className="flex items-center gap-2"><SelectTrigger disabled>Failed to load — click retry</SelectTrigger><button type="button" onClick={() => refetch()} className="text-xs underline">Retry</button></div>`.
     - If `data?.data.length === 0`: `<SelectTrigger disabled>{emptyState?.message ?? 'No options'}</SelectTrigger>` followed by the empty-state CTA `<Link>` if provided.
     - Otherwise: `<Select value={value ?? ''} onValueChange={(v) => onChange(v || undefined)}><SelectTrigger id={id} data-testid={dataTestId}><SelectValue placeholder={placeholder ?? 'Select…'} /></SelectTrigger><SelectContent>{sortedEntities.map((entity) => { ... })}</SelectContent></Select>` plus the inline warning `<p>` if `inlineWarning(selectedEntity)` returns non-null.
   - For each `<SelectItem>`:
     - `disabled={disabledIds?.has(getId(entity))}`
     - `title={disabledReason?.(entity) ?? undefined}` (only when disabled)
     - Children: if `getStatus`, render `<span aria-hidden="true" className={statusColorClass(getStatus(entity))}>●</span> {getLabel(entity)}` else just `{getLabel(entity)}`.
3. Add a `statusColorClass(status: EntityStatus): string` helper at module scope that maps `green→'text-green-600'`, `yellow→'text-amber-600'`, `red→'text-red-600'`, `unknown→'text-muted-foreground'`. Keep it un-exported.
4. Add a `normalizeStatus(wire: string): EntityStatus` helper that maps `unreachable→unknown` and passes the other three values through. Document at the call site that this lets consumers pass `(c) => c.health_check.status` directly without a switch.
5. Wait — re-read FR-6: callers pass `getStatus: (entity: T) => EntityStatus` where `EntityStatus = 'green' | 'yellow' | 'red' | 'unknown'`. The mapping `unreachable→unknown` happens in **the caller's `getStatus` callback**, not in the primitive. Drop `normalizeStatus` from this story — it's a caller concern. Update the Story 2.1 + 2.2 migrations to use `(c) => c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status` (or a small helper if it's used in both).
6. Create the test file `ui/src/__tests__/components/common/entity-select.test.tsx`. Mock `useEntities` with a synthetic `() => ({ data: { data: fixtures }, isLoading: false, isError: false, refetch: vi.fn() }) as any` shape (the primitive only cares about the four fields, so casting is acceptable). Use `QueryClientProvider` only for the integration-shaped tests that go through actual hooks (none required here — the primitive consumes the hook value, not the hook).
7. Test cases (10+ required per DoD):
   - **AC-1 happy path**: renders 3 entities, click the trigger, dropdown opens, click an option, `onChange` fires with the id.
   - **AC-2 loading**: `isLoading: true` → trigger has `disabled` attribute, contains "Loading…", clicking does not open.
   - **AC-3 error**: `isError: true, refetch: vi.fn()` → trigger contains "Failed to load — click retry", clicking Retry button calls `refetch()`.
   - **AC-4 empty no CTA**: `data.data: []`, no `emptyState` prop → trigger disabled with "No options".
   - **AC-4 empty with CTA**: `data.data: []`, `emptyState: { message: 'No clusters registered', cta: { label: 'Register one', href: '/clusters' } }` → trigger disabled with the message; `<Link>` rendered with the CTA label + href.
   - **AC-5 status dots**: 3 entities with mixed health, `getStatus` provided → 3 dots rendered with the correct Tailwind color classes; dots are inside `<span aria-hidden="true">`.
   - **AC-6 status sort**: 5 entities with mixed status, `getStatus` provided → the rendered order is green entries first (preserving insertion order within tier), then yellow, then red, then unknown.
   - **AC-7 inline warning**: select an entity, `inlineWarning` returns a non-null string for that entity → `<p>` rendered with `text-amber-600 mt-1` classes and the warning text.
   - **AC-8 disabled subset**: `disabledIds: new Set(['e2'])`, `disabledReason: (e) => 'Archived'` → the `<SelectItem>` for `e2` has the disabled attribute AND a `title="Archived"`.
   - **AC-8 disabled does not fire onChange**: clicking the disabled item does NOT call `onChange`. (Shadcn's `data-[disabled]:pointer-events-none` enforces this; verify the assertion runs.)
   - **AC-13 data-testid passthrough**: pass `data-testid="my-test"` → `getByTestId('my-test')` finds the trigger element.
   - **AC-13 id passthrough**: pass `id="cs-cluster"` → the trigger button has `id="cs-cluster"`.
   - **Bonus: getStatus omitted**: no status sort, no dots rendered, items in insertion order.
8. Run `cd ui && pnpm test src/__tests__/components/common/entity-select.test.tsx`. All cases pass.
9. Run `cd ui && pnpm lint && pnpm typecheck && pnpm build`. All four green.

**Definition of Done**

- [ ] `ui/src/components/common/entity-select.tsx` exists with the full `EntitySelectProps<T>` interface.
- [ ] `ui/src/__tests__/components/common/entity-select.test.tsx` exists with ≥12 test cases covering FR-1 through FR-6 (one for each AC-1, AC-2, AC-3, AC-4-no-CTA, AC-4-with-CTA, AC-5, AC-6, AC-7, AC-8 disabled rendering, AC-8 click-does-not-fire-onChange, AC-13 data-testid, AC-13 id-passthrough). All pass.
- [ ] `cd ui && pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all pass.
- [ ] No new pnpm dependencies introduced (`git diff package.json pnpm-lock.yaml` is empty).
- [ ] Conventional Commit: `feat(ui): EntitySelect primitive for form-level FK dropdowns`.

---

### Story 1.2 — Form-select-discipline vitest lint guard

**Outcome:** A new vitest at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` scans all form components under `ui/src/components/**/*.tsx` (excluding `__tests__/`, `common/`, and `*.column-config.{ts,tsx}`) and fails when a form file inlines a `<SelectItem value="<literal>">` whose `<literal>` matches any backend enum wire value from `ui/src/lib/enums.ts`. The guard is invariant-preserving: ALL existing form modals must already pass it on Story 1.2 commit time (because the spec audit confirmed every one already imports from `@/lib/enums`).

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | The vitest lint guard. ~120-150 LOC (mirrors `data-table-column-discipline.test.tsx` structure). Exports `validateFormSelect(filePath, content, enumsContent)` for synthetic-regression testing. Top-level `describe` block runs the real-glob scan and the regression cases. |

**Modified files**

| File | Change |
|---|---|
| (none in Story 1.2 itself) | The guard is purely additive. |

**Endpoints / Pydantic schemas**: N/A.

**Key interfaces**

```typescript
// ui/src/__tests__/components/common/form-select-discipline.test.tsx

export interface ValidationError {
  file: string;
  message: string;
}

/**
 * Pure: walks a single file's content and the enums.ts content; returns
 * an array of validation errors. Empty array = pass.
 */
export function validateFormSelect(
  filePath: string,
  content: string,
  enumsContent: string,
): ValidationError[];
```

**UI element inventory**: N/A (this is a test file, not UI).

**Tasks**

1. Create `ui/src/__tests__/components/common/form-select-discipline.test.tsx`. Mirror the structure of [`data-table-column-discipline.test.tsx`](../../../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx):
   - `walkFormFiles(dir: string): string[]` — recursive walk excluding `__tests__/`, `common/`, and any file matching `*.column-config.{ts,tsx}`.
   - `extractEnumWireValues(enumsContent: string): Set<string>` — parse all `export const *_VALUES = [...] as const;` blocks and union the string literals into one set. Numbers (like `RATING_VALUES = [0, 1, 2, 3]`) are coerced to strings to match `<SelectItem value="0">`-style usage.
   - `validateFormSelect(filePath, content, enumsContent)` — the validator. Logic:
     - Check whether the file imports `SelectItem` from `'@/components/ui/select'`. If not, the file is irrelevant; return `[]`.
     - Check for a top-of-file `// no-enum-import: <reason>` comment. If present and `<reason>` is non-empty (≥1 non-whitespace character after the colon), return `[]` (file is opted out).
     - If present but `<reason>` is empty, return `[{file, message: 'The // no-enum-import: comment requires a non-empty reason after the colon.'}]`.
     - Otherwise, scan for `<SelectItem value="<literal>">` (and `<SelectItem value='<literal>'>`). For each match, if `<literal>` is in the enum-wire-values set, add an error.
2. Top-level `describe('Form-select discipline', () => { ... })`:
   - **It scans every form component — all pass.** Walk `ui/src/components/`, exclude the standard subdirs, read each file, run the validator, collect errors. Assert errors array is empty. (At commit time of Story 1.2, this must pass because every existing form modal already uses `*_VALUES.map(...)`.)
3. Regression cases (synthetic content; ≥6 cases):
   - **Regression 1: inline `<SelectItem value="completed">` matching `STUDY_STATUS_VALUES` fails.** Synthetic content imports `SelectItem` from `'@/components/ui/select'` and contains `<SelectItem value="completed">Completed</SelectItem>`. Validator should return an error naming the file and the offending value.
   - **Regression 2: inline `<SelectItem value="ndcg">` matching `OBJECTIVE_METRIC_VALUES` fails.** Identical structure, different enum.
   - **Regression 3: mapped-from-enum pattern passes.** Synthetic content imports `STUDY_STATUS_VALUES` from `'@/lib/enums'` and uses `{STUDY_STATUS_VALUES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}`. Validator returns empty array.
   - **Regression 4: indexed access passes.** Content uses `<SelectItem value={STUDY_STATUS_VALUES[0]}>...</SelectItem>`. Validator returns empty array (no string-literal match).
   - **Regression 5: escape hatch with reason passes.** Content has `// no-enum-import: legacy migration — see issue #99` at the top AND inline `<SelectItem value="completed">`. Validator returns empty array.
   - **Regression 6: escape hatch with no reason fails.** Content has `// no-enum-import:` (no reason) AND inline `<SelectItem value="completed">`. Validator returns an error about the missing reason.
   - **Regression 7: file without `SelectItem` import is ignored.** Content does NOT import `SelectItem` (e.g., column-config file that's been moved into a wrong dir). Validator returns empty array.
   - **Regression 8: file with `SelectItem` but no enum match is ignored.** Content imports `SelectItem` and has `<SelectItem value="custom-non-enum-value">` where `custom-non-enum-value` is not in any `*_VALUES` array. Validator returns empty array (the guard only catches drift against KNOWN backend enums, not arbitrary literals).
4. Run `cd ui && pnpm test src/__tests__/components/common/form-select-discipline.test.tsx`. All cases pass.
5. Run the column-discipline test in the same invocation: `pnpm test src/__tests__/components/common/data-table-column-discipline.test.tsx`. Both guards must pass — they don't share scan state but must coexist in CI.

**Definition of Done**

- [ ] `ui/src/__tests__/components/common/form-select-discipline.test.tsx` exists with ≥9 test cases (1 real-glob scan + 8 regression cases).
- [ ] The real-glob scan passes against the current codebase (no existing form modal triggers the guard).
- [ ] All ≥6 regression cases per AC-10 / AC-11 / AC-12 pass.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] Conventional Commit: `test(ui): form-select-discipline lint guard for inline-enum-literal regression`.

---

**Epic 1 gate (hard stop — do not proceed to Epic 2):**

- [ ] Story 1.1 (`<EntitySelect>` + tests) merged or committed on branch.
- [ ] Story 1.2 (`form-select-discipline.test.tsx` + tests) merged or committed on branch.
- [ ] `cd ui && pnpm test` runs ALL tests (entity-select + form-select-discipline + everything else) and all pass. No regression in the existing 368-passing test count baseline (per state.md as of 2026-05-17, post-PR #132); the new entity-select tests bring the total to ~380+.
- [ ] `cd ui && pnpm build` succeeds.

## Epic 2 — Migrate 4 form modals onto `<EntitySelect>`

Each Story 2.x is one migrated modal. All four stories preserve `data-testid` / `id` / `htmlFor` per FR-8. None of them touch the backend.

### Story 2.1 — Migrate `create-query-set-modal.tsx`: UUID `<Input>` → `<EntitySelect>`

**Outcome:** The cluster_id field in `create-query-set-modal.tsx` is no longer a free-text UUID `<Input>`. It's an `<EntitySelect>` that loads clusters via `useClusters({ limit: 200 })` and renders cluster names with health-status dots. The "Cluster ID" label changes to "Cluster" (no longer asking for an ID).

**New files**: (none — single-file migration).

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/query-sets/create-query-set-modal.tsx`](../../../../ui/src/components/query-sets/create-query-set-modal.tsx) | Lines 86-92: replace UUID `<Input id="qs-cluster">` with `<EntitySelect useEntities={useClusters} ... />`. Add `import { useClusters } from '@/lib/api/clusters';`. Add `import { EntitySelect } from '@/components/common/entity-select';`. Drop the `placeholder="UUIDv7 of the registered cluster"` text. Change the `<Label>` text from "Cluster ID" to "Cluster". |
| [`ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx`](../../../../ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx) | Update the cluster_id interaction: replace `fireEvent.change(screen.getByLabelText('Cluster ID'), { target: { value: 'c-1' } })` (line 35) with a combobox interaction. Add msw setup that mocks `GET /api/v1/clusters` to return a fixture with at least one cluster (id `c-1`, name `local-es`, health_check `green`). Open the combobox via `fireEvent.click(screen.getByRole('combobox', { name: /cluster/i }))` and select via `fireEvent.click(screen.getByRole('option', { name: /local-es/i }))`. Assert the submitted body still has `cluster_id: 'c-1'`. |

**Endpoints / Pydantic schemas**: N/A.

**Key interfaces**: N/A (consumer-side only).

**UI element inventory**

Removed:
- `<Input id="qs-cluster" {...form.register('cluster_id', { required: true })} placeholder="UUIDv7 of the registered cluster" />` at lines 87-91.

Added:
- `<EntitySelect<ClusterSummary> id="qs-cluster" data-testid="qs-cluster" useEntities={() => useClusters({ limit: 200 })} getId={(c) => c.id} getLabel={(c) => c.name} getStatus={(c) => c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status} value={form.watch('cluster_id') || undefined} onChange={(v) => form.setValue('cluster_id', v ?? '')} placeholder="Choose a cluster" emptyState={{ message: 'No clusters registered', cta: { label: 'Register a cluster', href: '/clusters' } }} />`.
- Label text changed: `<Label htmlFor="qs-cluster">Cluster</Label>` (was "Cluster ID").

**State dependency analysis**

The cluster_id field is registered via `form.register('cluster_id', { required: true })`. After migration, the field is no longer registered — instead, `form.watch('cluster_id')` reads the value and `form.setValue('cluster_id', v ?? '')` writes it. Submit validation that relied on `required: true` needs an explicit check at submit time (or a `useEffect` that updates `form.setError`).

Read the current submit handler (around lines 50-75) to confirm whether `react-hook-form` will still flag the field as required without explicit register. Plan task: add an explicit `if (!values.cluster_id) { form.setError('cluster_id', { message: 'Cluster is required' }); return; }` guard at the top of `submit()`. (Or use `form.register('cluster_id', { required: true })` as a hidden field; both patterns work in this codebase.)

**Tasks**

1. Read `ui/src/components/query-sets/create-query-set-modal.tsx` end-to-end to confirm the submit handler structure.
2. Add the two imports at the top: `import { EntitySelect } from '@/components/common/entity-select';` and `import { useClusters } from '@/lib/api/clusters';` and `import type { ClusterSummary } from '@/lib/api/clusters';`.
3. Replace lines 86-92 with the `<EntitySelect>` block (see UI element inventory).
4. Change the `<Label>` text at line 86 from "Cluster ID" to "Cluster".
5. Add the explicit required-field guard at the top of `submit()`: `if (!values.cluster_id) { form.setError('cluster_id', { type: 'required', message: 'Cluster is required' }); return; }`.
6. Run `cd ui && pnpm lint && pnpm typecheck`. Fix any TS errors (likely: explicit generic `EntitySelect<ClusterSummary>`, or absent import).
7. Update the test file at `ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx` per Modified files row above.
8. Run `cd ui && pnpm test src/__tests__/components/query-sets/create-query-set-modal.test.tsx`. Pass.
9. Run `cd ui && pnpm build`. Pass.

**Definition of Done**

- [ ] `create-query-set-modal.tsx` no longer contains the UUID placeholder text `"UUIDv7 of the registered cluster"`.
- [ ] The cluster field renders an `<EntitySelect>` with `data-testid="qs-cluster"` AND `id="qs-cluster"` (verified by updated test).
- [ ] The cluster `<Label>` text is "Cluster" (not "Cluster ID").
- [ ] Submitting without selecting a cluster shows the validation error and does NOT POST to `/api/v1/query-sets`.
- [ ] The updated unit test asserts the migration: combobox role exists, opening it loads options, selecting an option populates the form, submit body still includes `cluster_id: 'c-1'`.
- [ ] AC-1 + AC-13 pass.
- [ ] Conventional Commit: `refactor(ui): migrate create-query-set-modal cluster_id to EntitySelect`.

---

### Story 2.2 — Migrate `create-study-modal.tsx`: 4 FK SelectTriggers → 4 `<EntitySelect>` instances

**Outcome:** All four FK `<Select>` blocks in the 5-step wizard (cluster at step 1, query-set + judgment-list at step 2, template at step 3) consume `<EntitySelect>`. Child-field reset behavior is preserved via the consumer's `onChange` callback. The 5 Optuna enum selects are untouched.

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Add the `EntitySelect` import. Replace four hand-rolled blocks: cluster (lines 237-256, ~20 LOC), query set (276-293, ~17 LOC), judgment list (297-311, ~14 LOC), template (322-336, ~14 LOC). Total deletion ~65 LOC; total addition ~30 LOC; net -35 LOC. Preserve all four `data-testid`/`id` values: `cs-cluster`, `cs-qs`, `cs-jl`, `cs-tpl`. Preserve the cluster `onValueChange` child-field reset (resets `query_set_id`, `judgment_list_id`, `template_id` to empty when cluster changes). |
| [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) | Update DOM assertions tied to hand-rolled `<Select>`. Existing test fixtures may use `screen.getByLabelText('Cluster')` or `getByTestId('cs-cluster')` — preserve both. Update interactions to combobox role. Confirm child-field reset still works (selecting a new cluster resets the downstream selects). |

**UI element inventory**

Each of the four migrated FK SelectTriggers replaces its current `<Select>` ... `</Select>` block with:

- **`cs-cluster`** (line 237-256 → ~10 LOC):
  ```tsx
  <EntitySelect<ClusterSummary>
    id="cs-cluster"
    data-testid="cs-cluster"
    useEntities={() => useClusters({ limit: 200 })}
    getId={(c) => c.id}
    getLabel={(c) => `${c.name} (${c.engine_type})`}
    getStatus={(c) => (c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status)}
    value={values.cluster_id || undefined}
    onChange={(v) => {
      form.setValue('cluster_id', v ?? '');
      form.setValue('query_set_id', '');
      form.setValue('judgment_list_id', '');
      form.setValue('template_id', '');
    }}
    placeholder="Choose a cluster"
  />
  ```
- **`cs-qs`**: same pattern, `useEntities={() => useQuerySets({ cluster_id: clusterId || undefined, limit: 200 })}`, `getLabel={(q) => q.name}`, no `getStatus`, child reset only resets `judgment_list_id`.
- **`cs-jl`**: `useEntities={() => useJudgmentLists({ query_set_id: querySetId || undefined, limit: 200 })}`, `getLabel={(j) => j.name}`, no `getStatus`, no further child resets.
- **`cs-tpl`**: `useEntities={() => useTemplates({ engine_type: selectedCluster?.engine_type, limit: 200 })}`, `getLabel={(t) => `${t.name} (v${t.version})`}`, no `getStatus`, no further child resets.

**State dependency analysis**

State variables in `create-study-modal.tsx` that DataTable migration leaves UNCHANGED:

- `clusterId = form.watch('cluster_id')` (line 107).
- `selectedCluster = clusters.data?.data.find((c) => c.id === clusterId)` (line 113) — still needs to read from `clusters.data?.data` to derive `engine_type` for template filtering. **Important:** `clusters.data?.data` is now read in two places (`create-study-modal.tsx` body + inside `<EntitySelect>`'s call to `useClusters`). TanStack Query's cache ensures the same query is fetched only once (same query-key `['clusters', { limit: 200 }]`); the two reads share the same cached result. No double-fetch.

State that needs to stay correct after migration:

- `values.cluster_id` — still owned by react-hook-form, read by the wizard's downstream selects and the submit handler. The consumer's `onChange` callback writes to it via `form.setValue`.
- Same for `values.query_set_id`, `values.judgment_list_id`, `values.template_id`.

The hidden register for required-field validation: the four FK fields all have `required: true` semantics in the wizard's step validation logic (`stepValid` function at ~line 129). The plan must preserve those constraints — likely by keeping a `<input type="hidden" {...form.register('cluster_id', { required: true })}>` or by changing `stepValid` to read directly from `values.cluster_id`. Read the function body to confirm. **Task in this story: read `stepValid` and choose the simpler of the two preservation patterns.**

**Tasks**

1. Read the full `create-study-modal.tsx` end-to-end. Confirm: (a) the location of `stepValid`, (b) the location of all 4 FK SelectTriggers, (c) the location of `selectedCluster` derivation.
2. Add the `EntitySelect` import + `ClusterSummary` type import.
3. Replace the cluster block (lines 237-256) with the `<EntitySelect>` snippet from the UI inventory. Verify the `onChange` resets all 3 downstream form fields exactly as the current `onValueChange` does.
4. Replace the query-set block (276-293) with `<EntitySelect>`. Wire `onChange` to reset only `judgment_list_id`.
5. Replace the judgment-list block (297-311) with `<EntitySelect>`. No child reset.
6. Replace the template block (322-336) with `<EntitySelect>`. No child reset.
7. Preserve required-field validation: confirm `stepValid` reads from `values.<field>` (not `form.formState.errors.<field>`); if it relies on react-hook-form's register-side validation, add explicit value checks.
8. Run `cd ui && pnpm lint && pnpm typecheck`. Fix any errors.
9. Update `create-study-modal.test.tsx`. Run the test. Pass.
10. Run `cd ui && pnpm build`. Pass.

**Definition of Done**

- [ ] All four FK SelectTriggers in `create-study-modal.tsx` are `<EntitySelect>` instances.
- [ ] `data-testid` values preserved: `cs-cluster`, `cs-qs`, `cs-jl`, `cs-tpl`.
- [ ] `id` values preserved: same four strings.
- [ ] Child-field reset behavior: selecting a new cluster resets `query_set_id`, `judgment_list_id`, `template_id` to empty string. Selecting a new query set resets `judgment_list_id` to empty string. **Verified by an updated unit test in `create-study-modal.test.tsx` (the legacy-behavior parity item from §UI Guidance).**
- [ ] Wizard step validation still blocks "Next" when any required FK is unselected. **Verified by an updated unit test.**
- [ ] `pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] AC-9 + AC-13 pass.
- [ ] Conventional Commit: `refactor(ui): migrate create-study-modal 4 FK selects to EntitySelect`.

---

### Story 2.3 — Migrate `register-cluster-modal.tsx`: conditional `<Select>` → always-visible `<EntitySelect>` with empty-state CTA

**Outcome:** The config-repo `<Select>` (currently conditionally rendered when `configRepos.data?.data.length > 0`) is replaced with an always-visible `<EntitySelect>` that displays the empty-state slot when no repos are registered. UX change per spec §2 (existing behaviors affected by scope change).

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/clusters/register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx) | Add `EntitySelect` import. Remove the `{(configRepos.data?.data ?? []).length > 0 && ...}` conditional wrapper at line 211. Replace the `<Select>` block (lines 214-228, ~14 LOC) with `<EntitySelect>`. Preserve `data-testid="cl-repo"` (or `id="cl-repo"` per current pattern) on the SelectTrigger. |
| [`ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx`](../../../../ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx) | Update assertions: the config-repo field is now always rendered. Add a new test case for the empty state (mock `GET /api/v1/config-repos` to return `data: []` and assert the empty-state CTA link is rendered). |

**UI element inventory**

Removed:
- Entire `{(configRepos.data?.data ?? []).length > 0 && (<div>...</div>)}` block at lines 211-230.

Added (always-visible):
```tsx
<div className="space-y-1.5">
  <Label htmlFor="cl-repo">Config repo (optional)</Label>
  <EntitySelect<ConfigRepoDetail>
    id="cl-repo"
    data-testid="cl-repo"
    useEntities={() => useConfigRepos({ limit: 100 })}
    getId={(r) => r.id}
    getLabel={(r) => r.name}
    value={form.watch('config_repo_id') || undefined}
    onChange={(v) => form.setValue('config_repo_id', v || undefined)}
    placeholder="—"
    emptyState={{
      message: 'No config repos registered',
      cta: { label: 'Register a config repo', href: '/clusters' },
    }}
  />
</div>
```

Note: per spec §11 IA, the CTA destination is `/clusters` for now (clusters page also hosts repo registration). If a dedicated `/config-repos` route exists, update accordingly — task #1 below verifies this.

**State dependency analysis**

`configRepos` was previously read in two places: the conditional wrapper at line 211 (`configRepos.data?.data ?? []`).length check) AND the `.map(...)` inside the `<SelectContent>`. After migration, the consumer no longer calls `useConfigRepos` itself — `<EntitySelect>` calls it via the `useEntities` prop. TanStack Query's cache key is identical, so the new call still hits the same cache.

The submit handler reads `values.config_repo_id` (line ~80, optional). This is unchanged.

**Tasks**

1. Read `register-cluster-modal.tsx` to confirm the CTA destination. `grep -rn "register.*config.*repo\|/clusters\|/config-repos" ui/src/app/` to see where repo registration lives. Update the `emptyState.cta.href` to the verified route.
2. Add the `EntitySelect` import + `ConfigRepoDetail` type import.
3. Remove the existing `configRepos = useConfigRepos({ limit: 100 })` call at line 56 — the primitive now owns it. (Cache-share means there's no double-fetch.)
4. Remove the conditional wrapper at line 211. Replace lines 211-230 with the always-visible `<EntitySelect>` block from UI inventory.
5. Run `cd ui && pnpm lint && pnpm typecheck`. Fix errors.
6. Update `register-cluster-modal.test.tsx`. New test cases:
   - Empty-state case: mock `GET /api/v1/config-repos` to return `{ data: [], next_cursor: null, has_more: false }`. Assert the config-repo field is visible AND the empty-state CTA link `<a href="/clusters">Register a config repo</a>` is rendered.
   - Loaded case: mock the endpoint with two repos. Assert the field is visible, opening the combobox shows both options.
7. Run `cd ui && pnpm test src/__tests__/components/clusters/register-cluster-modal.test.tsx`. Pass.
8. Run `cd ui && pnpm build`. Pass.

**Definition of Done**

- [ ] The config-repo field in `register-cluster-modal.tsx` is always rendered.
- [ ] `data-testid="cl-repo"` and `id="cl-repo"` preserved.
- [ ] When `useConfigRepos()` returns an empty list, the empty-state CTA link is rendered (verified by new test case).
- [ ] When `useConfigRepos()` returns one or more repos, the dropdown shows them (verified by existing/updated test).
- [ ] `pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] AC-4 + AC-13 pass.
- [ ] Conventional Commit: `refactor(ui): migrate register-cluster-modal config-repo select to EntitySelect`.

---

### Story 2.4 — Migrate `generate-judgments-dialog.tsx`: template `<Select>` → `<EntitySelect>`

**Outcome:** The template selection field in `generate-judgments-dialog.tsx` consumes `<EntitySelect>`. The E2E spec at `ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts` continues to pass without modification (the `gen-template` data-testid is preserved on the SelectTrigger).

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | Add `EntitySelect` import. Replace the template `<Select>` block (lines 116-133, ~17 LOC) with `<EntitySelect>`. Preserve `id="gen-template"` AND `data-testid="gen-template"` (the latter may not exist yet — add it if missing, since the E2E spec uses it). |
| (new) `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` | **Optional new file** — Story 2.4 ships either (a) a small unit test that verifies the migration, OR (b) relies entirely on the existing E2E spec at `ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts`. Plan-stage decision: ship (b). Rationale: this component has shipped without a unit test through MVP1 (intentional — small, low-risk, fully E2E-covered); adding a unit test now is scope creep. The E2E spec exercises the real-backend interaction including template selection; if it passes after the migration, the migration is verified. |

**UI element inventory**

Removed:
- Existing `<Select>` block lines 116-133.

Added:
```tsx
<div className="space-y-1.5">
  <Label htmlFor="gen-template">Current template</Label>
  <EntitySelect<QueryTemplateSummary>
    id="gen-template"
    data-testid="gen-template"
    useEntities={() => useTemplates({ limit: 200 })}
    getId={(t) => t.id}
    getLabel={(t) => `${t.name} (v${t.version})`}
    value={form.watch('current_template_id') || undefined}
    onChange={(v) => form.setValue('current_template_id', v ?? '')}
    placeholder="Choose a template"
  />
</div>
```

**State dependency analysis**

The current code calls `templates = useTemplates({ limit: 200 })` at line 59 AND reads `templates.data?.data` inside the SelectContent map. After migration, the primitive owns the hook call; the outer scope no longer reads `templates.data` directly. The submit handler reads `values.current_template_id`, unchanged.

**Tasks**

1. Verify `gen-template` is in the E2E spec: `grep gen-template ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts`. Confirm.
2. Verify the current code has `data-testid="gen-template"` — if not, the E2E may use only the `id` selector. Read the spec file to check. **Plan decision: ensure both `id` AND `data-testid` are on the SelectTrigger post-migration.**
3. Add the `EntitySelect` import + `QueryTemplateSummary` type import (from `@/lib/api/query-templates`).
4. Remove the `useTemplates` call at line 59 (the primitive now owns it).
5. Replace lines 116-133 with the `<EntitySelect>` block from UI inventory.
6. Run `cd ui && pnpm lint && pnpm typecheck`. Fix errors.
7. Run `cd ui && pnpm build`. Pass.
8. Run the targeted E2E if a real backend is available locally: `cd ui && pnpm exec playwright test tests/e2e/guides/09_generate_judgments_llm.spec.ts`. (CI runs this; if local backend isn't running, defer to CI.)

**Definition of Done**

- [ ] `generate-judgments-dialog.tsx` template field is an `<EntitySelect>` with `id="gen-template"` AND `data-testid="gen-template"`.
- [ ] `pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] E2E spec `09_generate_judgments_llm.spec.ts` continues to pass (verified locally OR in CI).
- [ ] AC-13 passes.
- [ ] Conventional Commit: `refactor(ui): migrate generate-judgments-dialog template select to EntitySelect`.

---

**Epic 2 gate (hard stop — do not proceed to Epic 3):**

- [ ] All four migration stories (2.1, 2.2, 2.3, 2.4) committed.
- [ ] No existing `data-testid` value lost in the migration. Verified by: `grep -E "qs-cluster|cs-cluster|cs-qs|cs-jl|cs-tpl|cl-repo|gen-template" ui/src/components/ ui/tests/e2e/` returns at least the same number of matches it did pre-migration.
- [ ] `cd ui && pnpm test` green (all vitest tests).
- [ ] `cd ui && pnpm exec playwright test` green where backend is available (at minimum the guides spec passes).
- [ ] `form-select-discipline.test.tsx` real-glob scan still passes (no migrated modal accidentally introduced inline literals).

## Epic 3 — Documentation

### Story 3.1 — `ui-architecture.md` "Form dropdown primitive" subsection

**Outcome:** A new subsection adjacent to "DataTable primitive" in `docs/01_architecture/ui-architecture.md` documents the `<EntitySelect>` primitive: props API, consumer-supplied `useEntities` shape, status / warning / empty-state slots, asymmetry to `DataTableFkSelect` (shadcn vs native).

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) | Insert a "Form dropdown primitive (`<EntitySelect>`)" subsection between "DataTable primitive" (currently at line 240) and "Auth surface (MVP1)" (currently at line 254). Cite the spec FRs, link to the source file, name the asymmetry, list the optional props with one-line explanations. ~40-60 lines of new prose. |

**Tasks**

1. Read `ui-architecture.md` lines 240-260 to confirm the surrounding section's tone and structure.
2. Draft the new section. Required content:
   - One-paragraph intro stating: form-level FK dropdowns now use `<EntitySelect>` from `ui/src/components/common/entity-select.tsx` (link), generalizing the load/error/empty/disabled/status patterns that were duplicated across four form modals before PR #<plan-stage-TBD>.
   - **Props API** subsection: brief table of `useEntities`, `getId`, `getLabel`, `value`, `onChange`, `getStatus`, `inlineWarning`, `disabledIds`, `disabledReason`, `emptyState`, `placeholder`, `loadingPlaceholder`, `id`, `data-testid`. Mark required vs optional.
   - **Status indicator** subsection: explains the `getStatus` opt-in, status-sort (green-first stable), inline warning. Cites `HEALTH_STATUS_VALUES` from enums.ts.
   - **Empty-state contract** subsection: how `emptyState.cta` works with Next.js Link (no modal-close plumbing).
   - **Asymmetry to `DataTableFkSelect`** subsection: explicit statement that the two primitives are peers — `<EntitySelect>` is shadcn/Radix-based for form ecosystem consistency; `DataTableFkSelect` is native `<select>` for the DataTable filter strip; they share no code.
   - **Source-of-truth discipline** subsection: cites the new `form-select-discipline.test.tsx` lint guard and the parent column-discipline guard. Notes the convention now covers forms in addition to column configs.
3. Run `pnpm exec markdownlint docs/01_architecture/ui-architecture.md` if markdownlint is configured (check repo). Otherwise just human-review the diff.

**Definition of Done**

- [ ] `docs/01_architecture/ui-architecture.md` contains a "Form dropdown primitive" section between the existing DataTable section and the next section.
- [ ] The section links to `ui/src/components/common/entity-select.tsx`, names the asymmetry to `DataTableFkSelect`, and cites `HEALTH_STATUS_VALUES`.
- [ ] AC-15 passes.
- [ ] Conventional Commit: `docs: ui-architecture.md — form dropdown primitive section`.

---

### Story 3.2 — `CLAUDE.md` "Enumerated Value Contract Discipline" paragraph

**Outcome:** One new paragraph in CLAUDE.md notes the new form-select-discipline lint guard. The paragraph is appended to the existing "Enumerated Value Contract Discipline" section.

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`CLAUDE.md`](../../../../CLAUDE.md) | Append one paragraph to the "Enumerated Value Contract Discipline" section. ~6-8 lines. Reference the new lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` and state the rule: "Form components must not inline `<SelectItem value="literal">` for backend-validated enums; use `*_VALUES.map(...)` from `@/lib/enums` instead." |

**Tasks**

1. Read CLAUDE.md to locate the "Enumerated Value Contract Discipline" section (currently at line range that includes the existing column-discipline notes).
2. Append one paragraph at the end of the section:

   > **Form-level coverage (2026-05-18):** The form-select-discipline lint guard at [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](ui/src/__tests__/components/common/form-select-discipline.test.tsx) extends the discipline to form components. It scans `ui/src/components/**/*.tsx` (excluding `__tests__/`, `common/`, and `*.column-config.{ts,tsx}`) and fails when a file imports `SelectItem` from `'@/components/ui/select'` AND inlines `<SelectItem value="<literal>">` where `<literal>` matches any backend enum wire value defined in [`ui/src/lib/enums.ts`](ui/src/lib/enums.ts). Escape hatch: a top-of-file `// no-enum-import: <non-empty reason>` comment opts the file out. CI catches the regression in the same PR check as the column-discipline guard.

3. Verify no other location in CLAUDE.md needs updating (no Absolute Rule renumbering, no Common Pitfall additions — the new rule is documented under an existing convention header).

**Definition of Done**

- [ ] CLAUDE.md contains a new paragraph in the "Enumerated Value Contract Discipline" section referencing `form-select-discipline.test.tsx`.
- [ ] AC-16 passes.
- [ ] Conventional Commit: `docs(claude): CLAUDE.md — note form-select-discipline lint guard`.

---

### Story 3.3 — `tutorial-first-study.md` Step 5 reorder + curl pattern update

**Outcome:** Step 5 of the tutorial leads with the modal walkthrough; the curl example uses a `LOCAL_ES_ID=$(curl ... | jq -r ...)` shell substitution; the literal `<local-es-id>` placeholder is removed.

**New files**: (none).

**Modified files**

| File | Change |
|---|---|
| [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) | Reorder Step 5: (a) lead with "Open `/query-sets` → click 'New query set' → select cluster from dropdown → fill name → click Create"; (b) demote the curl example to a "Or via API" code block; (c) replace `cluster_id":"<local-es-id>"` (current literal at line 182) with the shell substitution pattern: first show how to capture `LOCAL_ES_ID=$(curl -s http://localhost:8000/api/v1/clusters | jq -r '.data[0].id')`, then use `cluster_id":"'$LOCAL_ES_ID'"` in the body. |

**Tasks**

1. Read Step 5 of the tutorial to confirm the current structure (~10-30 lines around line 182).
2. Rewrite Step 5 per the Modified files row.
3. Verify the surrounding step numbering and cross-references (other steps may reference "Step 5" content) are unchanged.

**Definition of Done**

- [ ] Tutorial Step 5 leads with the modal walkthrough.
- [ ] The `<local-es-id>` literal placeholder is gone.
- [ ] A new `LOCAL_ES_ID=$(curl ... | jq -r ...)` pattern is shown for the API path.
- [ ] AC-14 passes.
- [ ] Conventional Commit: `docs(tutorial): tutorial-first-study.md — Step 5 modal-first walkthrough`.

---

**Epic 3 gate (final gate before merge):**

- [ ] All three doc stories committed.
- [ ] Local docs read end-to-end for spelling / accuracy.
- [ ] All Epic-1 and Epic-2 gates still pass (regression check).
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- [ ] AC-14, AC-15, AC-16 all pass.

---

## UI Guidance

### Reference: current component structure

**`ui/src/components/common/entity-select.tsx`** — does not exist yet (created in Story 1.1).

**`ui/src/components/common/data-table-fk-select.tsx`** (sibling primitive — read for context):
- 67 LOC total.
- Single named export: `DataTableFkSelect` (function component) + `DataTableFkSelectProps` interface.
- Uses native `<select>` (NOT shadcn/Radix). Renders `<label>` + `<select>` + `<option>` directly.
- Hook shape: `useOptions: () => { data: { id, label }[]; isLoading: boolean }`.
- No status, no warning, no empty-state. Filter-strip-specific.

**`ui/src/components/query-sets/create-query-set-modal.tsx`** (target of Story 2.1):
- Current line count: 110 LOC (small).
- Top imports: shadcn `Dialog`, `Input`, `Label`, `Button`, `Textarea`. Reads `useCreateQuerySet` from `@/lib/api/query-sets`.
- State: react-hook-form `useForm<{ name, cluster_id, description }>` plus a `submitting` boolean.
- Insertion point: lines 86-92 (the cluster_id `<Input>`). After Story 2.1, lines 86-92 become an `<EntitySelect>` block of similar length.

**`ui/src/components/studies/create-study-modal.tsx`** (target of Story 2.2):
- Current line count: 556 LOC (large — 5-step wizard).
- Top imports: shadcn Dialog/Input/Label/Select/Textarea family, HelpPopover, InfoTooltip; multiple TanStack hooks (`useClusters`, `useClusterSchema`, `useQuerySets`, `useJudgmentLists`, `useTemplates`, `useCreateStudy`); enum arrays from `@/lib/enums`.
- State: react-hook-form with ~12 fields; `step` index; `submitting` flag; `clusterId`, `target`, `querySetId`, `metric` derived via `form.watch`; `selectedCluster` derived via `clusters.data?.data.find(...)`; `schema` from `useClusterSchema`.
- Insertion points: lines 237-256 (cs-cluster), 276-293 (cs-qs), 297-311 (cs-jl), 322-336 (cs-tpl).

**`ui/src/components/clusters/register-cluster-modal.tsx`** (target of Story 2.3):
- Current line count: 247 LOC.
- Top imports: shadcn Dialog/Input/Label/Select/Textarea; `useRegisterCluster`; `useConfigRepos`; enum arrays from `@/lib/enums`.
- State: react-hook-form with 7 fields; `submitting`. `configRepos = useConfigRepos({ limit: 100 })` at line 56.
- Insertion point: lines 211-230 (conditional config-repo block, REMOVED entirely and replaced with the always-visible block).

**`ui/src/components/query-sets/generate-judgments-dialog.tsx`** (target of Story 2.4):
- Current line count: 150 LOC.
- Top imports: shadcn Dialog/Input/Label/Select/Textarea; `useGenerateJudgments` (inferred); `useTemplates`.
- State: react-hook-form with `name`, `target`, `current_template_id`, `rubric`; `submitting`. `templates = useTemplates({ limit: 200 })` at line 59.
- Insertion point: lines 116-133 (template `<Select>` block).

### Analogous markup patterns

#### Pattern 1 — basic field wrap (used by every migrated FK)

Source: `create-query-set-modal.tsx:81-92` (the surrounding wrapper that doesn't change).
```tsx
<div className="space-y-1.5">
  <Label htmlFor="<id>"><label-text></Label>
  <EntitySelect<EntityType>
    id="<id>"
    data-testid="<id>"
    useEntities={...}
    getId={(e) => e.id}
    getLabel={(e) => e.<name-field>}
    value={form.watch('<form-field>') || undefined}
    onChange={(v) => form.setValue('<form-field>', v ?? '')}
    placeholder="<placeholder>"
  />
</div>
```

#### Pattern 2 — FK with health status (clusters)

Source: derived from `<HealthCheckResult>` schema at `ui/src/lib/types.ts:1299`.
```tsx
getStatus={(c) => (c.health_check.status === 'unreachable' ? 'unknown' : c.health_check.status)}
inlineWarning={(c) => {
  if (!c || c.health_check.status === 'green') return null;
  return `Selected cluster is currently ${c.health_check.status}. Studies created against this cluster may fail until health recovers.`;
}}
```

(Helper: factor the `unreachable→unknown` logic into a small util `clusterHealthToEntityStatus(c)` if it appears in both `create-query-set-modal.tsx` and `create-study-modal.tsx`. Defer the factor until both stories ship — 2-line duplication doesn't yet warrant a util.)

#### Pattern 3 — empty-state CTA

Source: spec FR-4 + AC-4.
```tsx
emptyState={{
  message: 'No <entity-plural> registered',
  cta: { label: 'Register a <entity-singular>', href: '/<entity-route>' },
}}
```

#### Pattern 4 — child-field reset (cluster → query_set/judgment_list/template)

Source: `create-study-modal.tsx:239-244` (the existing onValueChange — preserve verbatim in the EntitySelect's onChange).
```tsx
onChange={(v) => {
  form.setValue('cluster_id', v ?? '');
  form.setValue('query_set_id', '');
  form.setValue('judgment_list_id', '');
  form.setValue('template_id', '');
}}
```

#### Pattern 5 — vitest mock for `useEntities`

Source: project pattern + spec FR-1.
```typescript
const useClustersMock = () => ({
  data: { data: clusterFixtures, next_cursor: null, has_more: false },
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
} as unknown as ReturnType<typeof useClusters>);

render(
  <EntitySelect<ClusterSummary>
    useEntities={useClustersMock}
    getId={(c) => c.id}
    getLabel={(c) => c.name}
    value={undefined}
    onChange={vi.fn()}
  />
);
```

(For modal-level integration tests, prefer msw-mocked `http.get('/api/v1/clusters', ...)` + real `useClusters` inside `<QueryClientProvider>` per the existing test pattern in `create-query-set-modal.test.tsx:11-15`.)

### Layout and structure

- All four migrated modals already use `<div className="space-y-1.5">` wrappers for each form field. The migration preserves this layout — `<EntitySelect>` slots into the same `<div>` the old `<Select>` or `<Input>` occupied.
- The `<EntitySelect>` itself does NOT introduce a new wrapping `<div>`. It renders the SelectTrigger as the root, plus optional siblings (retry button, CTA Link, inline warning) below the trigger.
- Responsive behavior: shadcn `<SelectTrigger>` is `w-full` by default; sibling elements (retry button, CTA) use `text-xs` and align with the helper-text convention.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Open create-query-set modal | TanStack `useClusters({ limit: 200 })` fires | `GET /api/v1/clusters?limit=200` |
| Click cluster trigger | shadcn `<Select>` opens dropdown; entities render in status-sorted order | (none — data already cached) |
| Click a cluster option | `onChange(id)` fires; consumer's handler runs `form.setValue('cluster_id', id)` | (none) |
| Click Retry on error state | `refetch()` fires | `GET /api/v1/clusters?limit=200` (retry) |
| Click empty-state CTA Link | Next.js routes to `cta.href`; modal unmounts via route change | (none — page change handles it) |
| Open create-study cluster picker, change cluster mid-wizard | `onChange(newId)`: consumer's handler resets `query_set_id` + `judgment_list_id` + `template_id` to empty string; child dropdowns refetch with new `cluster_id` filter | `GET /api/v1/query-sets?cluster_id=<new>&limit=200`, `GET /api/v1/judgment-lists?query_set_id=&limit=200`, `GET /api/v1/query-templates?engine_type=<new-cluster-engine>&limit=200` |

### Handler function patterns

```typescript
// Pattern A — simple onChange with no child reset
onChange={(v) => form.setValue('config_repo_id', v ?? undefined)}

// Pattern B — onChange with child reset (cluster picker in create-study)
onChange={(v) => {
  form.setValue('cluster_id', v ?? '');
  form.setValue('query_set_id', '');
  form.setValue('judgment_list_id', '');
  form.setValue('template_id', '');
}}

// Pattern C — onChange with one child reset (query-set picker in create-study)
onChange={(v) => {
  form.setValue('query_set_id', v ?? '');
  form.setValue('judgment_list_id', '');
}}

// Pattern D — explicit required-field guard in submit (Story 2.1)
function submit(values: QuerySetFormValues) {
  if (!values.cluster_id) {
    form.setError('cluster_id', { type: 'required', message: 'Cluster is required' });
    return;
  }
  // ... rest of submit
}
```

### Component composition

`<EntitySelect>` is intentionally a single named export from `ui/src/components/common/entity-select.tsx`. It does NOT export sub-components for separate use (no exported `EntitySelectTrigger`, `EntitySelectEmpty`, etc.). Composition complexity is internal to the primitive; consumers see one component with props.

Rationale: the four consumer use cases are similar enough that a flat prop-based API is simpler than a slot-based composition. If a future consumer needs deep customization (e.g., a non-shadcn rendering family), they should build their own primitive — not extend `<EntitySelect>` with override slots.

### Information architecture placement

No new routes, no navigation changes. Each migrated modal remains in its current location:

- `create-query-set-modal.tsx` → opened from `/query-sets` "New query set" button.
- `create-study-modal.tsx` → opened from `/studies` "New study" button.
- `register-cluster-modal.tsx` → opened from `/clusters` "Register cluster" button.
- `generate-judgments-dialog.tsx` → opened from `/query-sets/[id]` "Generate judgments" button.

Empty-state CTAs route the user to the right page for entity registration:

- "No clusters registered" → `/clusters` (for Story 2.1).
- "No config repos registered" → `/clusters` (for Story 2.3; verify this is the actual repo-registration route in task #1 of Story 2.3 — it might be `/config-repos` instead).

### Tooltips and contextual help

Per spec §11 tooltip inventory:

| Element | Tooltip text | Trigger | Placement | Implementation |
|---|---|---|---|---|
| Status dot `●` | Browser-native `title="Cluster health: <status>"` (via `title` attribute on the SelectItem) | hover on the item | inline | `title={`Cluster health: ${getStatus(entity)}`}` on the SelectItem |
| Inline warning under cluster trigger | "Selected cluster is currently <status>. Studies created against this cluster may fail until health recovers." | rendered as `<p>` when `inlineWarning(selectedEntity)` returns non-null | below the SelectTrigger | `<p className="text-xs text-amber-600 mt-1">{warning}</p>` |
| Empty-state CTA link | "No <entity-plural> registered — register one to enable <feature>." | always visible when data is empty | inline below trigger | `<p className="text-xs"><Link className="underline">{cta.label}</Link></p>` |
| Disabled SelectItem | `disabledReason(entity)` string | hover on the item | inline (browser-native via `title`) | `title={disabledReason(entity) ?? undefined}` |
| Retry button | "Click to retry loading the list." | hover on the button | inline (browser-native via `title`) | `<button title="Click to retry loading the list.">Retry</button>` |

All tooltip text is under 120 characters. No custom tooltip primitive is introduced — browser-native `title` attributes match the existing pattern (e.g., `cluster.target` glossary tooltip at `create-study-modal.tsx:261` uses an `InfoTooltip` component which itself wraps a `title` attr or similar).

### Visual consistency

| New element | Matches existing | Pattern source |
|---|---|---|
| SelectTrigger | shadcn `<SelectTrigger>` default | All existing `<SelectTrigger>` instances in form modals |
| SelectItem with status dot prefix | New (no existing pattern) | Custom — `<span aria-hidden="true" className="<color>">●</span> {label}` |
| Inline warning `<p>` | helper-text under inputs | `create-study-modal.tsx:265-267` (schema fields-discovered hint) |
| Empty-state CTA Link | text-xs underline | `associated-judgment-lists.tsx` (existing Link styling) |
| Retry button | text-xs underline | Custom (no exact match; close to underlined-link pattern) |

### Legacy behavior parity

**Not required for Story 1.1 / 1.2** — these are additive (no existing component deleted).

**Required for Story 2.1** (replacing the `<Input>` cluster_id field — small surface, not "user-facing component >100 LOC", but worth a partial table because user-visible behavior changes):

| # | Legacy behavior | Location | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | `cluster_id` field is required at submit | `create-query-set-modal.tsx:88-89` (`form.register('cluster_id', { required: true })`) | Preserved | Story 2.1 task #5 — explicit `if (!values.cluster_id)` check at top of `submit()`; updated unit test asserts the validation fires |
| 2 | Free-text UUID input | `create-query-set-modal.tsx:87-91` | Intentionally dropped | Spec §1 + §2 (this is the headline UX improvement — no source citation needed beyond the spec) |
| 3 | Placeholder "UUIDv7 of the registered cluster" | `create-query-set-modal.tsx:90` | Intentionally dropped | Spec §1 — operators no longer need to know the cluster's UUIDv7 format |
| 4 | Label "Cluster ID" | `create-query-set-modal.tsx:86` | Weakened | Renamed to "Cluster" — the "ID" suffix no longer applies since users select an entity, not type an ID |

**Required for Story 2.2** (4 hand-rolled `<Select>` blocks replaced — most behaviors are preserved 1:1, but the cluster `onValueChange` resetters are the high-leverage check):

| # | Legacy behavior | Location | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | Cluster change resets `query_set_id`, `judgment_list_id`, `template_id` | `create-study-modal.tsx:239-244` (inline `onValueChange`) | Preserved | Story 2.2 task #3 — consumer's `<EntitySelect>` `onChange` callback runs the same four `form.setValue` lines; DoD asserts the reset via updated unit test |
| 2 | Query-set change resets `judgment_list_id` | `create-study-modal.tsx:277-281` | Preserved | Same pattern in Story 2.2's query-set EntitySelect `onChange` |
| 3 | Wizard "Next" button disabled when required FK unselected | `create-study-modal.tsx` `stepValid()` function | Preserved | Story 2.2 task #7 — confirm `stepValid` reads from `values.<field>` directly; if not, add explicit checks. DoD asserts step blocking. |
| 4 | Loading state during data fetch ("Choose a cluster" placeholder) | `create-study-modal.tsx:247` | Strengthened | `<EntitySelect>` shows explicit "Loading…" instead of "Choose a cluster" while data is in flight (FR-2). Strictly better — no parity test needed, just visual confirmation. |
| 5 | Empty `<SelectContent>` when query errors | `create-study-modal.tsx:250` (silent fallback) | Strengthened | `<EntitySelect>` shows "Failed to load — click retry" with a working retry button (FR-3). Strictly better. |

**Required for Story 2.3** (config-repo Select replaced):

| # | Legacy behavior | Location | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | Config-repo field hidden when no repos exist | `register-cluster-modal.tsx:211` (`{... .length > 0 && ...}`) | Intentionally dropped | Spec §2 (existing behaviors affected by scope change) — discoverability win; the empty-state CTA is strictly more useful than hiding the field |
| 2 | Config-repo is optional | `register-cluster-modal.tsx:215-216` (`v \|\| undefined`) | Preserved | Story 2.3 — `<EntitySelect>` `onChange={(v) => form.setValue('config_repo_id', v \|\| undefined)}` preserves the optional/undefined semantics |
| 3 | Placeholder "—" when nothing selected | `register-cluster-modal.tsx:219` | Preserved | Story 2.3 — `placeholder="—"` passed to `<EntitySelect>` |

**Required for Story 2.4** (generate-judgments template Select replaced):

| # | Legacy behavior | Location | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | Template label format `{name} (v{version})` | `generate-judgments-dialog.tsx:127-128` | Preserved | Story 2.4 — `getLabel={(t) => `${t.name} (v${t.version})`}` |
| 2 | Required-field validation at submit | inferred from current code (template selection blocks submit) | Preserved | Story 2.4 — same submit-time validation pattern; no `<EntitySelect>`-side change required |
| 3 | E2E spec hook (`gen-template` data-testid) | `ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts` | Preserved | Story 2.4 task #2 — verify both `id` and `data-testid` are on the SelectTrigger post-migration |

### Client-side persistence

N/A — no localStorage / sessionStorage usage. All state is react-hook-form-managed and modal-scoped.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `ui/src/__tests__/components/`
- Scope: primitive behavior, lint-guard logic, modal-level behavior changes
- Tasks:
  - [ ] `ui/src/__tests__/components/common/entity-select.test.tsx` (Story 1.1) — ≥12 cases per FR-1 through FR-6 acceptance criteria. Synchronous mock for `useEntities`.
  - [ ] `ui/src/__tests__/components/common/form-select-discipline.test.tsx` (Story 1.2) — ≥9 cases (1 real-glob + 8 regression).
  - [ ] Update `ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx` (Story 2.1) — combobox interaction, required-field validation, submit body still has `cluster_id`.
  - [ ] Update `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (Story 2.2) — combobox interactions for all 4 FKs, child-field reset assertion, step-validation assertion.
  - [ ] Update `ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx` (Story 2.3) — always-visible config-repo field, empty-state CTA case.
- DoD:
  - [ ] All vitest suites green.
  - [ ] No existing passing test breaks.
  - [ ] Pre-feature passing baseline (per state.md `368 passing across 56 files` as of 2026-05-17) grows by ≥12 (new entity-select) + ≥9 (new lint guard) + ≥4 (updates to 3 modal tests) = ≥25 new cases. Final count ≥393.

### 3.2 Integration tests

N/A — no backend changes, no DB-backed workflow added.

### 3.3 Contract tests

N/A — no backend endpoint added or modified.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: existing real-backend specs continue to pass against the migrated modals
- Tasks:
  - [ ] No new E2E spec required. Existing specs that touch the four migrated modals (specifically `09_generate_judgments_llm.spec.ts` for `gen-template`) must continue to pass.
  - [ ] Run the targeted spec locally if backend is up: `cd ui && pnpm exec playwright test tests/e2e/guides/09_generate_judgments_llm.spec.ts`. Otherwise, defer to CI.
  - [ ] Run the full E2E suite once during the Epic 2 gate to verify no regression: `cd ui && pnpm exec playwright test` (subject to local backend availability; the maintainer's pre-merge walkthrough verifies this).
- DoD:
  - [ ] `09_generate_judgments_llm.spec.ts` passes.
  - [ ] Any other E2E spec that references `qs-cluster`, `cs-cluster`, `cs-qs`, `cs-jl`, `cs-tpl`, `cl-repo`, or `gen-template` data-testids passes.

### 3.5 Existing test impact audit

| Test file | Pattern | Count (verified at spec time) | Action |
|---|---|---|---|
| `ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx` | `getByLabelText('Cluster ID')` + `fireEvent.change(...{ value: 'c-1' })` | 1 file, 2 lines (35, 38) | Update per Story 2.1 |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Hand-rolled `<Select>` DOM assertions, child-field reset assertions | 1 file, TBD lines | Update per Story 2.2 |
| `ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx` | Conditional config-repo render assertions | 1 file, TBD lines | Update per Story 2.3 |
| `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` | **Does not exist** | 0 | No file to update |
| `ui/tests/e2e/guides/09_generate_judgments_llm.spec.ts` | `gen-template` data-testid usage | 1 file (verified) | **No change required** — data-testid preserved by Story 2.4 |
| Other `ui/tests/e2e/*.spec.ts` | Any FK data-testid usage | TBD via plan-stage grep at story start | Verify no change required |

### 3.5 Migration verification

N/A — no Alembic migration.

### 3.6 CI gates

- [ ] `make test-unit` (backend — sanity check; no backend changes expected to affect this)
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm build`
- [ ] `cd ui && pnpm exec playwright test` (subject to local backend availability)

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update after final PR merge:
- [ ] Add to recent changes: "PR #<N> merged — `chore_form_dropdown_primitive` shipped (Form Dropdown Primitive `<EntitySelect>` + lint guard + 4 modal migrations + docs)"
- [ ] Update active priorities / "What's next" if needed
- [ ] Alembic head: unchanged

**`architecture.md`** — update if needed:
- [ ] Frontend layer note about `<EntitySelect>` being the form-side peer to `DataTableFkSelect` (one bullet under the `ui/` section if the structure warrants it; likely just a one-line mention)

**`CLAUDE.md`** — update per Story 3.2:
- [ ] Append paragraph to "Enumerated Value Contract Discipline" section about the new lint guard.

### 4.1 Architecture docs

- [ ] `docs/01_architecture/ui-architecture.md` — new "Form dropdown primitive" subsection (Story 3.1).

### 4.2 Product docs

- [ ] Post-merge: move `docs/02_product/planned_features/chore_form_dropdown_primitive/` → `docs/00_overview/implemented_features/<YYYY_MM_DD>_chore_form_dropdown_primitive/` via the `/impl-execute` finalization step.

### 4.3 Runbooks

- [ ] No runbook update required (no operator-facing surface added).

### 4.4 Security docs

- [ ] No security doc update required.

### 4.5 Quality docs

- [ ] No testing-policy doc update required (the new lint guard is a vitest test, not a new test layer).

### 4.6 Guides

- [ ] `docs/08_guides/tutorial-first-study.md` — Step 5 reorder + curl pattern update (Story 3.3).

**Documentation DoD**

- [ ] state.md, architecture.md, CLAUDE.md consistent with shipped behavior.
- [ ] All 3 doc stories in Epic 3 land before merge.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

The primary refactor is the migration itself (replacing 4 hand-rolled FK Selects with the primitive). Additional refactor scope is bounded:

- Eliminate duplication of `unreachable→unknown` mapping if it appears in both `create-query-set-modal.tsx` and `create-study-modal.tsx` (defer until both stories ship; 2-line duplication doesn't yet warrant a util).
- Centralize the empty-state CTA copy if multiple migrations use identical strings (likely won't — each modal's CTA targets a different route).

### 5.2 Planned refactor tasks

- [ ] After Story 2.2 ships, evaluate whether `clusterHealthToEntityStatus(c)` deserves extraction. If yes: create `ui/src/lib/cluster-health.ts` with the one-line helper; update both modals to import. If no: leave the two-line ternary inline at both call sites.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by tests (legacy-behavior parity tables in §UI Guidance enumerate every preserved behavior).
- [ ] Lint/typecheck remain green at every story commit.
- [ ] No expansion of product scope (the spec explicitly excludes multi-select, async filtering, virtualized scrolling, and DataTableFkSelect unification).
- [ ] Track discovered debt: if a story surfaces a tangential bug or a needed cleanup, capture it as an idea file in `docs/02_product/planned_features/<bug-or-chore-slug>/idea.md` per the CLAUDE.md "Tangential discoveries" rule.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| shadcn `<Select>` primitives at `@/components/ui/select` | Story 1.1 | Implemented (used by all 4 modals today) | N/A |
| `useClusters`, `useConfigRepos`, `useTemplates`, `useQuerySets`, `useJudgmentLists` listing hooks | Stories 2.1-2.4 | Implemented (verified in spec §2) | N/A |
| `ui/src/lib/enums.ts` with 29 typed exports + `HEALTH_STATUS_VALUES` | Story 1.1 (for `EntityStatus` typing) + Story 1.2 (for lint-guard data source) | Implemented | N/A |
| `data-table-column-discipline.test.tsx` structure (template for Story 1.2) | Story 1.2 | Implemented (327 LOC) | N/A |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hidden child-field reset bug after Story 2.2 (e.g., `template_id` not reset when cluster changes, silently breaks wizard step 3) | Medium | Medium | Legacy behavior parity table forces test assertion per preserved row; updated unit test in Story 2.2 covers child-field reset explicitly |
| `data-testid` lost on migration, breaking E2E | Medium | High (breaks CI) | Epic 2 gate `grep -E "qs-cluster\|cs-cluster\|cs-qs\|cs-jl\|cs-tpl\|cl-repo\|gen-template" ui/src/components/` must return identical counts before and after |
| TanStack double-fetch (consumer's pre-migration `useConfigRepos` call + primitive's call) | Low | Low | TanStack Query cache key parity ensures one network call — verified in spec §2 audit |
| Required-field validation lost on Story 2.1 migration | Medium | Medium | Story 2.1 task #5 adds explicit guard at top of `submit()`; updated unit test asserts the guard fires |
| Empty-state CTA destination is wrong route (Story 2.3 assumes `/clusters` for repo registration) | Medium | Low | Story 2.3 task #1 verifies the actual route via grep before committing |
| Lint guard false-positive on a valid pattern not yet enumerated in the regression cases | Low | Low | Story 1.2 includes 8 regression cases covering known patterns; if a false-positive surfaces in Epic 2, refine the validator and add a regression case |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| TanStack hook returns `data === undefined` mid-render | Component re-renders before TanStack settles | `<EntitySelect>` treats undefined as `data.data === []` for empty-state purposes (since `data?.data ?? []` is `[]`). Trigger renders empty-state placeholder. | Auto-recovers when TanStack resolves |
| Backend returns 5xx | Cluster API down | `<EntitySelect>` renders error state with Retry button | Manual: user clicks Retry; or auto: user closes modal and reopens (refetch fires on remount) |
| Backend returns 2xx with malformed body (e.g., entity missing `id`) | Backend bug | `getId(entity)` returns undefined; `<SelectItem value={undefined}>` is invalid in shadcn → React error | Defensive: in `<EntitySelect>`, filter out entities where `getId(entity) == null` before rendering. Add to Story 1.1 task list. |
| `disabledIds` contains an id not in `data.data` | Caller bug | Disabled-state assertion silently does nothing for that id | Acceptable — the unmatched id has no visual or behavioral effect |
| Status sort runs on every render (perf concern at high entity counts) | Re-render storm | `useMemo` keyed on `data?.data` + `getStatus` identity prevents re-sort | Documented in §UI Guidance; spec §13 notes <200 entities is the MVP1 ceiling |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** in parallel (Story 1.1 and Story 1.2 are independent — primitive vs lint guard).
2. **Epic 2** in parallel after Epic 1 gate (Stories 2.1, 2.2, 2.3, 2.4 are independent — different modals, different test files).
3. **Epic 3** in parallel after Epic 2 gate (Stories 3.1, 3.2, 3.3 are independent — different doc files).

### Parallelization opportunities

- Story 1.1 (primitive) and Story 1.2 (lint guard) can ship in parallel commits — neither depends on the other. (The lint guard has zero behavioral coupling to the primitive; it only depends on `enums.ts`.)
- Stories 2.1, 2.2, 2.3, 2.4 can ship in any order after Epic 1. They touch four different files; their test files are also independent.
- Stories 3.1, 3.2, 3.3 can ship in any order; they touch three different doc files.

### Recommended single-commit-per-story sequence (for clarity in PR review)

1. Story 1.1 — `feat(ui): EntitySelect primitive for form-level FK dropdowns`
2. Story 1.2 — `test(ui): form-select-discipline lint guard for inline-enum-literal regression`
3. Story 2.1 — `refactor(ui): migrate create-query-set-modal cluster_id to EntitySelect`
4. Story 2.2 — `refactor(ui): migrate create-study-modal 4 FK selects to EntitySelect`
5. Story 2.3 — `refactor(ui): migrate register-cluster-modal config-repo select to EntitySelect`
6. Story 2.4 — `refactor(ui): migrate generate-judgments-dialog template select to EntitySelect`
7. Story 3.1 — `docs: ui-architecture.md — form dropdown primitive section`
8. Story 3.2 — `docs(claude): CLAUDE.md — note form-select-discipline lint guard`
9. Story 3.3 — `docs(tutorial): tutorial-first-study.md — Step 5 modal-first walkthrough`

Total: 9 commits / 9 stories. PR can be squashed at merge per maintainer preference.

## 8) Rollout and cutover plan

- **Rollout stages:** single-stage, no feature flag. Frontend-only refactor; merge to main → next dev-server reload picks up the new primitive.
- **Feature flag strategy:** not used.
- **Migration/cutover steps:** N/A.
- **Reconciliation/repair strategy:** N/A — no external systems involved.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — `<EntitySelect>` primitive
- [ ] Story 1.2 — form-select-discipline lint guard
- [ ] Story 2.1 — migrate create-query-set-modal
- [ ] Story 2.2 — migrate create-study-modal
- [ ] Story 2.3 — migrate register-cluster-modal
- [ ] Story 2.4 — migrate generate-judgments-dialog
- [ ] Story 3.1 — ui-architecture.md update
- [ ] Story 3.2 — CLAUDE.md update
- [ ] Story 3.3 — tutorial-first-study.md update

### Blocked items

— None.

### Done this sprint

— None yet.

## 10) Story-by-Story Verification Gate

Per story:

- [ ] Files created/modified match story scope (cross-reference New files / Modified files tables).
- [ ] No new pnpm dependency (`git diff package.json pnpm-lock.yaml` empty for stories 1.1, 1.2, 2.1-2.4, 3.1-3.3).
- [ ] `data-testid` and `id` preservation verified for stories 2.1-2.4.
- [ ] Test cases per the story DoD added and passing.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` pass.
- [ ] If Story 2.x, the matching unit test file is updated and passes.
- [ ] Conventional Commit format used.
- [ ] Legacy behavior parity table assertions (per §UI Guidance) tested for preserved rows.

## 11) Plan consistency review

**Plan-internal consistency (Pass 1):**

| Check | Status |
|---|---|
| Spec ↔ plan FR coverage | ✓ — all 9 FRs (FR-1 through FR-9) mapped to stories in §1 |
| Spec ↔ plan endpoint count | ✓ — both spec and plan have 0 new/modified endpoints (frontend-only) |
| Spec ↔ plan error code count | ✓ — both have 0 new error codes |
| Story new-files ownership | ✓ — 3 new files total (entity-select.tsx, entity-select.test.tsx, form-select-discipline.test.tsx); each assigned to exactly one story |
| Modified-files exist | ✓ — verified 4 modal files + 3 test files + 3 doc files (CLAUDE.md, ui-architecture.md, tutorial-first-study.md) exist |
| Test file count vs §3 testing workstream | ✓ — 5 test files modified/created (entity-select.test.tsx, form-select-discipline.test.tsx, 3 modal test updates) |
| Epic gate arithmetic | ✓ — Epic 1 gate covers 2 stories; Epic 2 covers 4; Epic 3 covers 3; sum = 9 = plan total |
| Spec §19 open questions resolved | ✓ — spec §19 lists all questions as locked at draft time |

**Codebase accuracy (Pass 2):**

| Check | Status |
|---|---|
| Migration directory and Alembic head | N/A — no migrations |
| Router registration | N/A — no router changes |
| State variable names in modals | ✓ — verified `form.watch('cluster_id')`, `clusters.data?.data`, `selectedCluster` against `create-study-modal.tsx:107-123` |
| Hook signatures match plan | ✓ — `useClusters(filter?) → UseQueryResult<ClusterListPage, ApiError>` verified at `clusters.ts:32-45`; matches `useEntities` prop shape |
| File line ranges in modals (insertion points) | ✓ — verified by spec-stage grep: cs-cluster=246, cs-qs=283, cs-jl=301, cs-tpl=326, cl-repo trigger=218, gen-template trigger=122, qs-cluster Label=86 |
| Existing `data-testid` values are findable | ✓ — verified by spec-stage grep for E2E coverage; `gen-template` exists in `09_generate_judgments_llm.spec.ts` |
| shadcn `<SelectTrigger>` forwards `id` + `data-testid` | ✓ — verified at `ui/src/components/ui/select.tsx:12-31` (forwardRef, `{...props}` spread to `<SelectPrimitive.Trigger>`) |
| Next.js `<Link>` import path | ✓ — confirmed `import Link from 'next/link'` is the project pattern (3 existing usages found) |
| `HEALTH_STATUS_VALUES` exports `'green' | 'yellow' | 'red' | 'unreachable'` | ✓ — verified at `enums.ts:53`; the `unreachable→unknown` mapping is the caller's responsibility per Story 1.1 task #5 |
| `ClusterSummary.health_check.status` shape | ✓ — verified at `types.ts:1304` |
| `data-table-column-discipline.test.tsx` template applicability | ✓ — read full 327 LOC; mirroring structure for Story 1.2 is straightforward |
| All four modified modals have co-located `.test.tsx` files | ✓ for 3 of 4 (create-query-set, create-study, register-cluster); ✗ for generate-judgments-dialog → Story 2.4 relies on existing E2E (decision documented in §UI Guidance "Modified files") |
| `enums.ts` has 29 `*_VALUES` exports | ✓ — verified by `grep -c "^export const " enums.ts` = 61 (29 typed arrays + types + sort arrays + etc.); spec-stage `grep -oE "export const [A-Z_]+_VALUES"` returned 29 distinct names |

**Enumerated value contract verification (Pass 2 §11):**

| Field | Backend source | Spec citation | Plan citation |
|---|---|---|---|
| `EntitySelect.getStatus` return | `ui/src/lib/enums.ts HEALTH_STATUS_VALUES` (mirrors `backend/app/api/v1/schemas.py HealthStatusValue`) | spec §7.4 + FR-6 | Story 1.1 key interfaces (`EntityStatus = 'green' | 'yellow' | 'red' | 'unknown'`) + §UI Guidance pattern 2 |
| `<SelectItem>` value matching across all 4 migrated modals | `enums.ts` exports (29 typed arrays) | spec §7.4 table (5 rows) | Story 1.2 (form-select-discipline.test.tsx scans the modals for inline literals matching any enum value) |

✓ All enumerated-value contracts match between spec and plan; no phantom values introduced.

**Audit-event coverage:** N/A — MVP1 (no `audit_log` yet); no state-mutating endpoints added.

---

## 12) Definition of plan done

- [x] Every FR (FR-1 through FR-9) is mapped to stories/tasks/tests/docs updates in §1.
- [x] Every story includes Outcome / New files / Modified files / Endpoints (or N/A) / Key interfaces (or N/A) / UI element inventory (for frontend stories) / Tasks / DoD.
- [x] Test layers (unit + lint guard) explicitly scoped per §3.
- [x] Documentation updates across docs/01, docs/08, and CLAUDE.md planned and assigned to Story 3.1, 3.3, and 3.2 respectively.
- [x] Lean refactor scope and guardrails explicit (§5).
- [x] Phase/epic gates measurable (§Epic-1-gate, §Epic-2-gate, §Epic-3-gate).
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed; no unresolved findings.
- [x] Legacy behavior parity tables for Stories 2.1, 2.2, 2.3, 2.4 in §UI Guidance.
