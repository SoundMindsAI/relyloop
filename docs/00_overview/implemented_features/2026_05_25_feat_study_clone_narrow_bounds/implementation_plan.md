# Implementation Plan — feat_study_clone_narrow_bounds

**Date:** 2026-05-25
**Status:** Complete (PR #247, squash-merged 2026-05-25 as `8b58d3d9`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Single-phase delivery (no deferred phase gates).
- Pure frontend feature: no backend changes, no migration, no new endpoints, no schema diff.
- Fail-loud tests: assert explicit JSON shapes against `SearchSpace` validator semantics.
- Keep increments narrow enough to verify independently.

---

## 1) Scope traceability (FR → stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (gate) | Story 1.2 + 1.3 | Hook signature widen (1.2) → modal gate consumption (1.3) |
| FR-2 (default unchecked) | Story 1.3 | Local React state initial value |
| FR-3 (label + tooltip) | Story 1.3 | Glossary key added in same story |
| FR-4 (check → rewrite) | Story 1.3 | Includes the no-op gate from D-11 and toast on `SyntaxError` |
| FR-5 (uncheck → restore) | Story 1.3 | `originalSpaceJsonRef.current` invariant |
| FR-6 (manual edits discarded on uncheck) | Story 1.3 | Vitest cases assert this; glossary text warns |
| FR-7 (modal close resets) | Story 1.3 | `useEffect` cleanup on `open` transition |
| FR-8 (reference panel) | Story 1.3 | Native `<details>`; same gate as checkbox |
| FR-9 (helper contract) | Story 1.1 | Pure helper file + types |
| FR-10 (clamp algorithm) | Story 1.1 | Includes negative-winner / zero-winner branches (D-10) |
| FR-11 (winner outside bounds) | Story 1.1 | `degenerate_intersection` skip path |
| FR-12 (submit validation unchanged) | Story 1.4 | E2E asserts server returns 201 |
| FR-13 (glossary key added) | Story 1.3 | One entry: `study.narrow_bounds_checkbox` |
| FR-14 (ui-architecture.md paragraph) | Story 1.4 | Documents the "Step-4 derived-value toggle" pattern |

**Deferred-phase tracking:** N/A — single-phase feature. No `phase2_idea.md` needed.

---

## 2) Delivery structure

**Epic → Story → Tasks → DoD.**

**Story sequence (single epic):**

1. **Story 1.1** — Pure helper `narrowBoundsAroundWinner` in `ui/src/lib/narrow-bounds.ts` + unit tests in `ui/src/__tests__/lib/narrow-bounds.test.ts`. No UI yet. (FR-9, FR-10, FR-11.)
2. **Story 1.2** — Extend `useStudyDigest(studyId, { enabled? })` (additive opts arg, mirroring `useStudy(id, { enabled })`). No new UI. (D-12, gate prerequisite for FR-1.)
3. **Story 1.3** — Step-4 checkbox + reference panel + glossary entry + state management. (FR-1 through FR-8, FR-13.)
4. **Story 1.4** — Playwright E2E real-backend spec + `ui-architecture.md` doc paragraph + v1-clone-spec forward-pointer. (FR-12, FR-14.)

### Conventions (project-specific)

```
- Pure helpers live in ui/src/lib/<topic>.ts; tests in ui/src/__tests__/lib/<topic>.test.ts
- TanStack Query hooks live in ui/src/lib/api/<topic>.ts; consume the project's apiClient
- React components: function components with hooks; no class components
- TypeScript strict; no `any` (use `Record<string, unknown>` for opaque JSON);
  no `noUncheckedIndexedAccess` violations
- Glossary keys are kebab/snake-case under namespaces (e.g., `study.narrow_bounds_checkbox`)
- Source-of-truth comments above generated option arrays (N/A here — no <select>)
- shadcn/ui primitives: <Checkbox>, <Label>, <InfoTooltip>
- Native HTML <details>/<summary> for collapsible disclosures (no headless-ui dep)
```

### AI Agent Execution Protocol (applies to every story)

0. **Load context first:** Read `architecture.md` and `state.md` before starting Story 1.1.
1. **Read scope:** verify story outcome + interfaces + DoD.
2. **Implement code** (no backend in this plan — all stories are frontend).
3. **Run unit tests** (`cd ui && pnpm test`).
4. **Run typecheck** (`cd ui && pnpm typecheck`).
5. **Run lint** (`cd ui && pnpm lint`).
6. **Run E2E scope** in Story 1.4 only.
7. **Update docs** in same PR for Story 1.4 only.
8. **Attach evidence** in PR description.
9. **After the final story**, update `state.md` and add an `implemented_features` folder pointer (see §4).

---

## Epic 1 — Narrow-bounds smart-rewrite for cloned studies

### Story 1.1 — Pure helper `narrowBoundsAroundWinner` + unit tests

**Outcome:** A unit-tested pure helper that transforms a `search_space` JSON to clamp numeric `low/high` to ±20% around the source's winning param values, returning a structured `NarrowBoundsResult`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/narrow-bounds.ts` | Pure helper `narrowBoundsAroundWinner` + `NarrowBoundsResult` interface (FR-9, FR-10, FR-11). |
| `ui/src/__tests__/lib/narrow-bounds.test.ts` | Vitest unit tests covering every algorithm branch (positive/negative winners, float/int/categorical, log-uniform, degenerate cases). |

**Modified files**

None.

**Key interfaces**

```typescript
// ui/src/lib/narrow-bounds.ts

export type SkipReason =
  | 'categorical'
  | 'missing_winner'
  | 'non_numeric_winner'
  | 'degenerate_intersection'
  | 'log_uniform_zero_floor';

export interface NarrowBoundsResult {
  /** The rewritten search_space JSON (valid SearchSpace shape). */
  json: string;
  /** Param names whose bounds were narrowed (sorted by Object.keys order in input). */
  narrowed: string[];
  /** Params skipped, with reason. */
  skipped: { name: string; reason: SkipReason }[];
}

export function narrowBoundsAroundWinner(
  spaceJson: string,
  winnerParams: Record<string, unknown>,
  percent?: number, // default 20
): NarrowBoundsResult;
```

**Tasks**

1. Create `ui/src/lib/narrow-bounds.ts` with the `NarrowBoundsResult` interface and the `narrowBoundsAroundWinner` function implementing FR-10's algorithm verbatim, including:
   - `JSON.parse(spaceJson)` (throws `SyntaxError` to caller on malformed input — do NOT catch).
   - Iterate `parsed.params` via `Object.entries`.
   - For each entry, branch on `spec.type` and `winnerParams[name]` presence/type per FR-10.
   - **Negative-winner safety (D-10):** compute `a = w * (1 - p)`, `b = w * (1 + p)`, then `targetLow = Math.min(a, b)`, `targetHigh = Math.max(a, b)`. For `w === 0`, both = 0 → skip with `degenerate_intersection`.
   - **Log-uniform floor:** for `spec.type === 'float'` AND `spec.log === true`, after computing `newLow`, apply `newLow = Math.max(newLow, 1e-12)`. If post-floor `newLow >= newHigh`, skip with `log_uniform_zero_floor`.
   - **Int rounding:** `newLow = Math.ceil(newLow)`, `newHigh = Math.floor(newHigh)`. If `newLow > newHigh`, skip with `degenerate_intersection`. (`newLow === newHigh` is valid — single-value range.)
   - Mutate `parsed.params[name].low/high` only when not skipped; never touch `type`, `log`, or `choices`.
   - Return `{ json: JSON.stringify(parsed, null, 2), narrowed, skipped }`.

2. Create `ui/src/__tests__/lib/narrow-bounds.test.ts` with the following test groups (each as a `describe` block):
   - **Float — positive winner inside old bounds:** `{low: 0.5, high: 5.0, log: false}`, winner=2.34, p=20 → `narrowed: ['title_boost']`, parsed result has `low=1.872, high=2.808`.
   - **Float — negative winner inside old bounds:** `{low: -20, high: 0, log: false}`, winner=-10, p=20 → `narrowed: ['x']`, parsed result has `low=-12, high=-8`.
   - **Float — winner = 0:** `degenerate_intersection`.
   - **Float — winner below `oldLow`:** `{low: 5, high: 10}`, winner=1, p=20 → `degenerate_intersection` (target [0.8, 1.2], clamped [5, 1.2] → invalid).
   - **Float — winner above `oldHigh`:** `{low: 0, high: 1}`, winner=10, p=20 → `degenerate_intersection`.
   - **Float log-uniform — clamped low > 0 preserved:** `{low: 1e-6, high: 100, log: true}`, winner=0.001, p=20 → `narrowed` (assert `low > 0`).
   - **Float log-uniform — clamped low ≤ 0 → `log_uniform_zero_floor` skip.**
   - **Int — simple clamp + rounding:** `{low: 1, high: 10}`, winner=5, p=20 → narrowed with `low = ceil(4) = 4`, `high = floor(6) = 6`.
   - **Int — single-value result is valid:** `{low: 1, high: 5}`, winner=3, p=20 → narrowed with `low = high = 3`.
   - **Int — degenerate after ceil/floor:** `{low: 1, high: 10}`, winner=2.5, p=20 (target [2, 3], ceil=2, floor=3 → narrowed [2, 3] — NOT degenerate; pick a different scenario): `{low: 1, high: 10}`, winner=2.5, p=4 (target [2.4, 2.6], ceil=3, floor=2 → degenerate). Skip reason: `degenerate_intersection`.
   - **Int — negative winner:** `{low: -10, high: 10}`, winner=-3, p=20 → narrowed (target [-3.6, -2.4], ceil(-3.6)=-3, floor(-2.4)=-3 → `[-3, -3]`).
   - **Categorical → skip with `categorical`.**
   - **Param in space but not in `winnerParams` → skip with `missing_winner`.**
   - **Param in `winnerParams` with non-numeric value** (string, bool, null) on a numeric spec → `non_numeric_winner`.
   - **Multiple params — mix of narrowed + skipped:** assert `result.narrowed` and `result.skipped` shapes.
   - **All-skipped input** (all categorical): `result.narrowed === []`, `result.skipped` populated.
   - **Custom percent:** p=10 narrower than p=50.
   - **Malformed JSON input:** `expect(() => narrowBoundsAroundWinner('not json', {})).toThrow(SyntaxError)`.

**Definition of Done**

- [ ] `ui/src/lib/narrow-bounds.ts` exports `narrowBoundsAroundWinner`, `NarrowBoundsResult`, `SkipReason`.
- [ ] `cd ui && pnpm test ui/src/__tests__/lib/narrow-bounds.test.ts` green (all ~18 test cases pass).
- [ ] `cd ui && pnpm typecheck` green.
- [ ] `cd ui && pnpm lint` green.
- [ ] Line/branch coverage on `narrow-bounds.ts` ≥ 95% (verify via `pnpm test --coverage` scoped to the file).
- [ ] No console.log / no commented-out code / no `any` types.
- [ ] Validates FR-9, FR-10, FR-11, D-10.

---

### Story 1.2 — Extend `useStudyDigest(studyId, { enabled? })` (additive opts arg)

**Outcome:** `useStudyDigest` accepts an optional second argument `{ enabled?: boolean }` that gates the underlying `useQuery` request, mirroring the established `useStudy(id, { enabled })` pattern. Existing single-argument callers are unaffected.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/lib/api/digests.test.ts` | Vitest tests for `useStudyDigest` (verified absent at plan time — see §11 plan ↔ codebase verification). 3 cases: enabled-by-default fires; `useStudyDigest(undefined)` does NOT fire; `useStudyDigest('foo', { enabled: false })` does NOT fire. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/digests.ts` | Widen `useStudyDigest` signature: `(studyId: string \| undefined, opts?: { enabled?: boolean })`. Pass `enabled: opts?.enabled ?? Boolean(studyId)` to the inner `useQuery`. The `queryFn` early-returns or asserts `studyId` is truthy under the enabled gate. |

**Key interfaces**

```typescript
// ui/src/lib/api/digests.ts (modified signature)

export function useStudyDigest(
  studyId: string | undefined,
  opts?: { enabled?: boolean },
): UseQueryResult<DigestResponse, ApiError>;
```

**Implementation pattern** (analogous to `useStudy` at [`ui/src/lib/api/studies.ts:67-88`](../../../../ui/src/lib/api/studies.ts#L67-L88)):

```typescript
export function useStudyDigest(
  studyId: string | undefined,
  opts?: { enabled?: boolean },
): UseQueryResult<DigestResponse, ApiError> {
  return useQuery<DigestResponse, ApiError>({
    queryKey: ['studies', studyId ?? '', 'digest'],
    queryFn: async () => {
      // The enabled gate below ensures we only reach here with a truthy studyId.
      if (!studyId) throw new Error('useStudyDigest: studyId required when enabled');
      const { data } = await apiClient.get<DigestResponse>(
        `/api/v1/studies/${studyId}/digest`,
      );
      return data;
    },
    enabled: opts?.enabled ?? Boolean(studyId),
    meta: { suppressErrorCodes: ['DIGEST_NOT_READY'] },
    retry: false,
  });
}
```

**Tasks**

1. Edit `ui/src/lib/api/digests.ts` to widen the signature and apply the pattern above. Preserve the existing `meta.suppressErrorCodes` and `retry: false` options.
2. Create or extend `ui/src/__tests__/lib/api/digests.test.ts` with three cases:
   - `useStudyDigest(undefined)` — assert no fetch fires (mock `apiClient.get` and verify zero calls).
   - `useStudyDigest('foo', { enabled: false })` — assert no fetch fires.
   - `useStudyDigest('foo')` — assert one fetch fires to `/api/v1/studies/foo/digest`.
3. Verify no other existing caller of `useStudyDigest` breaks. Grep for callers and confirm they use the single-argument form (still valid).

**Definition of Done**

- [ ] `grep -rn "useStudyDigest" ui/src/` returns existing callers AND no compile errors.
- [ ] `cd ui && pnpm typecheck` green.
- [ ] `cd ui && pnpm test ui/src/__tests__/lib/api/digests.test.ts` green (3 cases).
- [ ] `cd ui && pnpm lint` green.
- [ ] Validates D-12 hook signature widen.

---

### Story 1.3 — Step-4 checkbox + reference panel + glossary entry + state management

**Outcome:** When the engineer cloning a `completed` study with a digest advances to Step 4 of `CreateStudyModal`, they see (a) a checkbox labeled "Narrow bounds around the source study's winning params (±20%)" with an `InfoTooltip`, and (b) a collapsed `<details>` panel showing the source's `recommended_config` rows. Checking the box rewrites `search_space_text` to the narrowed JSON; unchecking restores the captured baseline; modal close resets state. The non-clone flow shows neither element.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.narrow-bounds.test.tsx` | Vitest component tests for visibility gating, check/uncheck behavior, reference panel content, state reset, banner stability (uses `cloneSource.name` not form `name`), and the no-op toast path. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Add Step-4 checkbox + reference panel (see "UI Guidance" below). Add `useStudyDigest` call at top of component (always called, gated via `enabled`). Add `originalSpaceJsonRef = useRef<string \| null>(null)` + `narrowBoundsChecked` local state. Wire check/uncheck handlers per FR-4/FR-5. Reset state via `useEffect` on `open → false` transition. |
| `ui/src/lib/glossary.ts` | Add one entry: `'study.narrow_bounds_checkbox': "Rewrites the cloned search space so each numeric range tightens to ±20% around the source study's winning param values. Categorical params and params not present in the winner are left untouched. Uncheck to restore the source's bounds — any manual edits made to the rewritten JSON will be discarded."` |
| `ui/src/__tests__/lib/glossary.test.ts` | Assert the new key exists and the description matches the source-of-truth pattern. |

**Key interfaces** (in-component, no exported new APIs)

```typescript
// Inside CreateStudyModal — near the existing form/state declarations:

const [narrowBoundsChecked, setNarrowBoundsChecked] = useState(false);
const originalSpaceJsonRef = useRef<string | null>(null);

// Always called per Rules of Hooks; enabled gate suppresses non-clone requests
const cloneSourceId = initialValues?.cloneSource?.id;
const sourceDigest = useStudyDigest(cloneSourceId, {
  enabled: Boolean(cloneSourceId),
});

// FR-1 gate: checkbox + reference panel render iff both conditions hold
const narrowBoundsGateOpen =
  Boolean(initialValues?.cloneSource) &&
  sourceDigest.status === 'success' &&
  sourceDigest.data !== undefined &&
  Object.keys(sourceDigest.data.recommended_config).length > 0;

// Reset on modal close
useEffect(() => {
  if (!open) {
    setNarrowBoundsChecked(false);
    originalSpaceJsonRef.current = null;
  }
}, [open]);

// FR-4 + FR-5: check/uncheck handler
const handleNarrowBoundsToggle = (next: boolean) => {
  if (next) {
    // false → true.
    // §4 Anti-pattern precondition guard: do not invoke the rewrite when the
    // textarea is in a known-malformed state.
    if (searchSpaceError !== null) {
      toast.error('Resolve the search-space JSON error before narrowing bounds.');
      originalSpaceJsonRef.current = null;
      // Stay unchecked.
      return;
    }
    const currentText = form.getValues('search_space_text');
    originalSpaceJsonRef.current = currentText;
    try {
      const result = narrowBoundsAroundWinner(
        currentText,
        sourceDigest.data!.recommended_config,
        20,
      );
      if (result.narrowed.length === 0) {
        toast(
          'No params narrowed — every param is categorical, missing from the winner, or its winner is outside the current bounds.',
        );
      } else {
        form.setValue('search_space_text', result.json);
      }
      setNarrowBoundsChecked(true);
    } catch (err) {
      const msg = err instanceof SyntaxError
        ? "Couldn't narrow bounds: search-space JSON is invalid — fix it and try again."
        : `Couldn't narrow bounds: ${err instanceof Error ? err.message : String(err)}`;
      toast.error(msg);
      originalSpaceJsonRef.current = null;
      // Stay unchecked.
    }
  } else {
    // true → false.
    if (originalSpaceJsonRef.current !== null) {
      form.setValue('search_space_text', originalSpaceJsonRef.current);
      originalSpaceJsonRef.current = null;
    }
    setNarrowBoundsChecked(false);
  }
};
```

**Tasks**

1. **Imports.** Add to `create-study-modal.tsx`:
   ```typescript
   import { useRef, useEffect } from 'react'; // if not already imported
   import { Checkbox } from '@/components/ui/checkbox';
   import { useStudyDigest } from '@/lib/api/digests';
   import { narrowBoundsAroundWinner } from '@/lib/narrow-bounds';
   ```
2. **State + hook.** Add `narrowBoundsChecked`, `originalSpaceJsonRef`, `sourceDigest`, and `narrowBoundsGateOpen` near the existing state declarations (above the `useEffect` that seeds `initialValues` at line ~309).
3. **Reset effect.** Add the `useEffect(() => { if (!open) reset… }, [open])` block alongside the existing open-handlers.
4. **Toggle handler.** Implement `handleNarrowBoundsToggle` as above. Use the existing `toast` import (already present per other modal flows).
5. **UI insertion.** In the Step-4 block (`step === 3`, line ~921), insert the checkbox + reference panel **above** the `<ResponsiveLayout>` (see "UI Guidance" section below).
6. **Glossary update.** Add `study.narrow_bounds_checkbox` entry to `ui/src/lib/glossary.ts`. Verify in `ui/src/__tests__/lib/glossary.test.ts` (extend existing tests).
7. **Existing-test audit (per §3.6).** Grep `grep -rn "cloneSource" ui/src/__tests__/` and identify any test that seeds `initialValues.cloneSource`. For each, ensure the TanStack Query test wrapper has a default `useStudyDigest` mock or MSW handler. Default behavior to keep the FR-1 gate closed in pre-existing tests: return `status: 'error'` with code `DIGEST_NOT_READY` (matches the suppressed-toast path the hook already declares via `meta.suppressErrorCodes`). Apply this change in this story so cycle-2 testing doesn't surface unexpected fetch errors from unrelated tests.
8. **Vitest component tests.** Create `create-study-modal.narrow-bounds.test.tsx` covering:
   - Checkbox absent in bare "New study" open (no `initialValues`).
   - Checkbox absent when `initialValues.cloneSource` set but `useStudyDigest` returns 404 (mock TanStack Query result with `status: 'error'`).
   - Checkbox absent when digest is loading (`status: 'pending'`).
   - Checkbox absent when `recommended_config` is `{}` (success but empty).
   - Checkbox present when gate passes; default unchecked.
   - On check: textarea value updates to the narrowed JSON (parse it; assert numeric bounds narrowed).
   - On uncheck: textarea restores to the captured baseline.
   - Check → manual edit textarea → uncheck: textarea restores to the pre-rewrite baseline (manual edits discarded).
   - All-categorical winner: toast surfaces; textarea unchanged.
   - Malformed JSON in textarea + check: error toast surfaces; checkbox reverts to unchecked; textarea unchanged.
   - Banner-style stability: when the form's `name` field is edited, the reference panel summary text continues to read from `cloneSource.name`.
   - Reference panel: rows match `Object.entries(recommended_config)` sorted alphabetically by key.
   - Modal close resets state: re-open clone → checkbox unchecked, textarea is fresh prefill.
   - Submit after check sends the narrowed JSON in the POST body (regression on payload serializer hygiene).

**Definition of Done**

- [ ] `grep -n "narrowBoundsAroundWinner" ui/src/components/studies/create-study-modal.tsx` returns ≥1 match.
- [ ] `grep -n "study.narrow_bounds_checkbox" ui/src/lib/glossary.ts` returns 1 match.
- [ ] `cd ui && pnpm test ui/src/__tests__/components/studies/create-study-modal.narrow-bounds.test.tsx` green.
- [ ] `cd ui && pnpm test ui/src/__tests__/lib/glossary.test.ts` green.
- [ ] `cd ui && pnpm typecheck` green.
- [ ] `cd ui && pnpm lint` green.
- [ ] Manual visual check on the storybook/dev server (or via vitest snapshot): checkbox renders above `<ResponsiveLayout>` in Step 4; `<details>` is collapsed by default.
- [ ] Validates FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-13, D-1, D-11.

---

### Story 1.4 — Playwright E2E real-backend + `ui-architecture.md` paragraph + v1 spec forward-pointer

**Outcome:** A real-backend Playwright spec exercises the full clone → narrow-bounds → submit flow and asserts the persisted `search_space` matches the ±20% clamp shape. Architecture docs gain a one-paragraph entry documenting the "Step-4 derived-value toggle" pattern.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` | Real-backend Playwright spec (AC-12). Seeds a `completed` study with a digest via `seedStudyCompletedWithDigest`, clicks "Clone study", checks the narrow-bounds box on Step 4, submits, asserts the resulting study's `search_space.params.title.boost.low/high` match the ±20% clamp computed from `recommended_config = { "title.boost": 2.5 }`. |

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/ui-architecture.md` | Add a "Step-4 derived-value toggles" paragraph documenting the `narrowBoundsAroundWinner` pattern as the canonical example. (FR-14.) |
| `docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md` | Add a single line under "Out of scope" pointing forward to this feature now that it's implemented. |

**Tasks**

1. Create `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` modeled on `ui/tests/e2e/study-clone.spec.ts` and `ui/tests/e2e/auto-followup.spec.ts`. Outline:

   ```typescript
   import { test, expect } from '@playwright/test';
   import { seedFullChain, seedStudyCompletedWithDigest } from './helpers/seed';

   test('AC-12 clone with narrow-bounds checkbox produces clamped search_space', async ({ page, request }) => {
     // Setup via API helpers (test setup only — assertions are via `page`).
     const chain = await seedFullChain();
     const seeded = await seedStudyCompletedWithDigest({
       clusterId: chain.clusterId,
       querySetId: chain.querySetId,
       templateId: chain.templateId,
       judgmentListId: chain.judgmentListId,
       withPendingProposal: false,
     });

     // Navigate to the source study detail page.
     await page.goto(`/studies/${seeded.studyId}`);

     // Click "Clone study" — opens /studies?clone_from=...
     await page.getByTestId('clone-study').click();

     // Modal opens; advance through Steps 1, 2, 3 → 4 (Step indices are 0-based; Step 4 is `step === 3`).
     // Use the "Next" button (existing testid from the v1 modal).
     await page.getByRole('button', { name: 'Next' }).click(); // 1 → 2
     await page.getByRole('button', { name: 'Next' }).click(); // 2 → 3
     await page.getByRole('button', { name: 'Next' }).click(); // 3 → 4

     // Assert checkbox is visible.
     const checkbox = page.getByLabel(/Narrow bounds around the source/);
     await expect(checkbox).toBeVisible();

     // Check it.
     await checkbox.check();

     // Read the textarea content; parse; assert numeric clamp.
     // Fixture provenance: backend/app/services/test_seeding.py:75-88 seeds
     // `search_space.params['title.boost'] = { type: 'float', low: 0.5,
     // high: 5.0, log: false }`; the same file at :188 seeds
     // `recommended_config = { 'title.boost': 2.5 }`. The ±20% clamp around
     // 2.5 → [2.0, 3.0], which fits inside [0.5, 5.0]. If the seed helper
     // changes, this test should fail loudly.
     const textareaValue = await page.getByTestId('cs-search-space').inputValue();
     const parsed = JSON.parse(textareaValue);
     expect(parsed.params['title.boost'].low).toBeCloseTo(2.0, 6);
     expect(parsed.params['title.boost'].high).toBeCloseTo(3.0, 6);

     // Submit.
     await page.getByRole('button', { name: 'Create study' }).click();

     // Wait for the new study detail page to load. Capture the new study id from the URL.
     await page.waitForURL(/\/studies\/[^\/]+$/);
     const newStudyId = page.url().split('/').pop()!;

     // Confirm via API: GET the new study and assert search_space.params.title.boost narrowed.
     const detailResp = await request.get(`/api/v1/studies/${newStudyId}`);
     const detail = await detailResp.json();
     expect(detail.search_space.params['title.boost'].low).toBeCloseTo(2.0, 6);
     expect(detail.search_space.params['title.boost'].high).toBeCloseTo(3.0, 6);
   });
   ```

2. Add the `docs/01_architecture/ui-architecture.md` paragraph. Verify the doc exists; identify the closest section (likely under "Wizards" or "Create-study wizard"); add a new subsection "Step-4 derived-value toggles" with this content:

   > Step-4 of the create-study modal supports opt-in transformations of the prefilled `search_space_text` field. The canonical example is `feat_study_clone_narrow_bounds`'s narrow-bounds checkbox: when checked, the textarea is rewritten via a pure helper (`ui/src/lib/narrow-bounds.ts`); when unchecked, the captured baseline is restored from a `useRef`. The pattern uses **capture-on-true** for the baseline (always overwrite the ref on `false → true`) and **clear-on-false** (always nullify on `true → false` and on modal close). Post-rewrite manual edits are discarded on uncheck — intentional per [feat_study_clone_narrow_bounds spec FR-6](../02_product/planned_features/feat_study_clone_narrow_bounds/feature_spec.md).

3. Add the forward-pointer line to the v1 clone spec at `docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md`. Find the bullet `"Narrow bounds" smart action — deferred to feat_study_clone_narrow_bounds (per D-3).` Append a second line below:

   > **Update (2026-05-25):** the narrow-bounds smart action shipped via [`feat_study_clone_narrow_bounds`](../../../02_product/planned_features/feat_study_clone_narrow_bounds/feature_spec.md). See its FR-1 through FR-14 for the implemented surface.

4. Run the Playwright spec locally against the dev stack: `cd ui && pnpm test:e2e -- study-clone-narrow-bounds`. Confirm one passing case.

**Definition of Done**

- [ ] `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` exists.
- [ ] `cd ui && pnpm test:e2e -- study-clone-narrow-bounds` green against `make up` stack (one case).
- [ ] `docs/01_architecture/ui-architecture.md` gains the "Step-4 derived-value toggles" subsection.
- [ ] `docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md` gains the forward-pointer line.
- [ ] Validates FR-12, FR-14, AC-12.

---

## UI Guidance (required for frontend-facing work)

### Reference: current `create-study-modal.tsx` structure

- **File:** [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)
- **Total lines:** ~1000+ (long file; section anchors are by `step === N` blocks and form-state declarations)
- **Step-4 anchor:** `step === 3` block starts at line ~921, currently contains in order:
  1. `<div className="space-y-1.5">` with the `Study name` `<Label>` + `<Input>` (line ~923–926)
  2. `<ResponsiveLayout builder={<SearchSpaceBuilder ... />} textarea={<Textarea ... />} />` (line ~927+) — the search-space editor split (rich builder + JSON textarea)
- **State variables** (relevant ones near declaration block):
  - `templateBody`, `templateFetchStatus`, `searchSpaceError`, `placeholderWarning`, `autoFillSignatures`, `autoFillTimeoutRef`
  - Form: `useForm<FormValues>(…)` with `values` via `form.watch()`
- **PrefillValues interface** at line 165–211, contains `cloneSource?: { id: string; name: string }` at line 196.
- **Autofill suppression** at lines 442–445: `if (initialValues && prefillSearchSpace !== '' && prefillSearchSpace !== '{}') return;` — narrow-bounds operates inside this clone-suppressed path, no interaction.
- **Insertion point for new checkbox + reference panel:** **between the Study name input block (line ~926, after the input's closing `</div>`) and the `<ResponsiveLayout>` opening (line ~927)**. The narrow-bounds card sits **above the search-space editor** (per spec §2 IA — "above the existing `ResponsiveLayout`") and **below the Study name input** (preserving the spec's labeling taxonomy: name first, then search-space). NOT the first child of the Step-4 container.

### Analogous markup patterns

**Checkbox pattern** — adapted from the existing `Checkbox` usage in [`ui/src/components/studies/create-study-modal.auto-followup`](../../../../ui/src/components/studies) and the shadcn-ui primitive at `ui/src/components/ui/checkbox.tsx`. Insertion:

```tsx
{narrowBoundsGateOpen && (
  <div
    className="rounded-md border border-border bg-muted/40 p-3 space-y-2"
    data-testid="narrow-bounds-section"
  >
    <div className="flex items-start gap-2">
      <Checkbox
        id="cs-narrow-bounds"
        checked={narrowBoundsChecked}
        onCheckedChange={(next) => handleNarrowBoundsToggle(Boolean(next))}
        data-testid="narrow-bounds-checkbox"
      />
      <div className="flex-1">
        <Label
          htmlFor="cs-narrow-bounds"
          className="text-sm font-medium leading-snug flex items-center gap-1"
        >
          {"Narrow bounds around the source study's winning params (±20%)"}
          <InfoTooltip glossaryKey="study.narrow_bounds_checkbox" />
        </Label>
      </div>
    </div>

    {/* FR-8: collapsible reference panel — native <details> */}
    <details
      className="text-xs text-muted-foreground"
      data-testid="narrow-bounds-reference-panel"
    >
      <summary className="cursor-pointer select-none hover:text-foreground">
        Best-trial values from <strong>{initialValues!.cloneSource!.name}</strong>
      </summary>
      <table className="mt-2 w-full text-left">
        <thead>
          <tr>
            <th className="font-medium pr-4">Param</th>
            <th className="font-medium">Winning value</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(sourceDigest.data!.recommended_config)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([name, value]) => (
              <tr key={name} data-testid="narrow-bounds-reference-row">
                <td className="pr-4 font-mono">{name}</td>
                <td className="font-mono">{JSON.stringify(value)}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </details>
  </div>
)}
```

**Critical positioning notes:**
- The block above is inserted **between the Study name input's closing `</div>` and the `<ResponsiveLayout>`** — i.e., the second child of the Step-4 container, sitting between the name input and the search-space editor. Above the rich builder + JSON textarea, below the name input.
- The whole block is wrapped in `{narrowBoundsGateOpen && (…)}` so the non-clone flow and the digest-not-ready flow render nothing at all (per FR-1 / D-1).
- The `data-testid="narrow-bounds-section"` allows the E2E spec to scope its query.
- **Label text uses ASCII apostrophe (`'`), not curly (`&rsquo;`)** — match the spec exactly so accessible-name lookups via `getByLabelText("Narrow bounds around the source study's winning params (±20%)")` resolve. In JSX, render via a string-literal expression to avoid the `react/no-unescaped-entities` lint rule: `{"Narrow bounds around the source study's winning params (±20%)"}` (the `±` is the Unicode plus-minus, kept verbatim).

### Layout and structure

- Single column inside Step 4; the narrow-bounds section is a bordered card (`rounded-md border border-border bg-muted/40 p-3`) above the existing layout.
- The reference panel is collapsed by default (`<details>` without the `open` attribute).
- No responsive-layout-specific behavior — the section is full-width regardless of viewport.

### Confirmation/modal dialog pattern

N/A — no new dialog. The narrow-bounds toggle is inline UI; toasts handle error messaging.

### Visual consistency table

| New element | CSS class / pattern source |
|---|---|
| Bordered section card | `rounded-md border border-border bg-muted/40 p-3` — matches the `auto_followup_depth` card pattern in the same modal |
| Checkbox + label row | `flex items-start gap-2` — shadcn-ui convention |
| Tooltip icon next to label | `<InfoTooltip glossaryKey="...">` — existing primitive used throughout the modal |
| Reference panel disclosure | Native `<details>`/`<summary>` — matches FAQ disclosure pattern in `ui/src/app/guide/faq/page.tsx` |
| Reference table | Plain `<table>` + Tailwind utility classes — no shadcn `<Table>` needed for 2-column inline data |

### Component composition

- Narrow-bounds section is **inline** in `create-study-modal.tsx`. Not extracted to a child component for v1 — the logic is tightly coupled to the modal's form state and the rewrite ref. Extraction would add prop-drilling cost without reuse value (no other surface uses this).
- If a future feature needs the same pattern, extract to `ui/src/components/studies/narrow-bounds-section.tsx` then. Premature abstraction not warranted.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Modal opens with `cloneSource` set | `useStudyDigest(cloneSourceId, { enabled: true })` fires | `GET /api/v1/studies/{id}/digest` |
| Modal opens with no `cloneSource` | Hook fires with `enabled: false` (no-op) | None |
| Engineer checks the box | `handleNarrowBoundsToggle(true)` runs synchronously | None (pure frontend transformation) |
| Engineer unchecks | `handleNarrowBoundsToggle(false)` restores ref | None |
| Engineer submits Step 4 | Existing `_create_study` POST flow | `POST /api/v1/studies` (existing endpoint, no new surface) |
| Modal closes | `useEffect` resets `narrowBoundsChecked` + clears ref | None |

### Handler function patterns

See the `Key interfaces` block in Story 1.3 for the full `handleNarrowBoundsToggle` implementation. The pattern:
1. On `false → true`: capture baseline → try helper → branch on `narrowed.length` → set state.
2. On `true → false`: restore baseline → clear ref → set state.
3. Errors from `JSON.parse` are caught at the helper boundary; the toast surfaces and the checkbox stays unchecked.

### Information architecture placement

- **Location:** Step 4 of `CreateStudyModal`, above the existing search-space input.
- **Discoverability:** the checkbox appears only when cloning a `completed` study with a digest. The engineer arrives at Step 4 via the standard wizard flow (Step 1: cluster + target; Step 2: query set + judgment list; Step 3: template; Step 4: search space + objective + config). The narrow-bounds card draws attention by being the first element in the step.
- **No new top-level nav** — the feature lives entirely inside an existing wizard step.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment | JSX pattern |
|---|---|---|---|---|---|---|
| Narrow-bounds checkbox label | (from glossary entry — see below) | `InfoTooltip` icon click | inline-right of label | `study.narrow_bounds_checkbox` | `// Source-of-truth: ui/src/lib/glossary.ts (added in Story 1.3)` | `<InfoTooltip glossaryKey="study.narrow_bounds_checkbox" />` — existing primitive |

**Glossary entry added in Story 1.3:**

```typescript
// ui/src/lib/glossary.ts — added under the "study" namespace cluster
'study.narrow_bounds_checkbox':
  "Rewrites the cloned search space so each numeric range tightens to " +
  "±20% around the source study's winning param values. Categorical " +
  "params and params not present in the winner are left untouched. Uncheck " +
  "to restore the source's bounds — any manual edits made to the " +
  "rewritten JSON will be discarded.",
```

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** This feature is purely additive (new checkbox + new disclosure panel inside an existing Step-4 block); no existing UI is removed, replaced, or refactored.

### Client-side persistence

**None.** The checkbox state and `originalSpaceJsonRef` are React state / refs — cleared on modal close. No `localStorage`, no `sessionStorage`. Per spec D-6.

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** `ui/src/__tests__/lib/narrow-bounds.test.ts` (Story 1.1)
- **Scope:** every algorithm branch in FR-10 — float/int/categorical, positive/negative/zero winners, log-uniform floor, missing-from-winner, non-numeric-winner, degenerate, custom percent, malformed JSON throws
- **Tasks:**
  - [ ] ~18 test cases per Story 1.1 "Tasks" §2
- **DoD:**
  - [ ] All branches covered; coverage ≥ 95% on `narrow-bounds.ts`

### 3.2 Integration tests

None new. This feature has no backend code.

### 3.3 Contract tests

None new. No new endpoints, no new error codes. Existing contract tests on `POST /api/v1/studies` and `GET /api/v1/studies/{id}/digest` continue to cover the request/response shapes the rewrite consumes/produces.

### 3.4 Component (vitest) tests

- **Location:** `ui/src/__tests__/components/studies/create-study-modal.narrow-bounds.test.tsx` (Story 1.3) and `ui/src/__tests__/lib/api/digests.test.ts` (Story 1.2)
- **Scope:** modal gate visibility, check/uncheck flow, restore semantics, banner stability, no-op toast path, malformed-JSON toast path, hook signature extension
- **Tasks:**
  - [ ] Story 1.2 — 3 hook test cases
  - [ ] Story 1.3 — ~12 modal test cases
- **DoD:**
  - [ ] All cases pass via `cd ui && pnpm test`

### 3.5 E2E tests

- **Location:** `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` (Story 1.4)
- **Scope:** one real-backend happy-path case (AC-12). Seed → click → check → submit → assert persisted shape.
- **Rule compliance:** uses Playwright's `page` for browser interactions (click, fill, expect); `request` only for setup (seed) + final assertion (GET the new study).
- **Tasks:**
  - [ ] Story 1.4 — one test case
- **DoD:**
  - [ ] `cd ui && pnpm test:e2e -- study-clone-narrow-bounds` green against `make up` stack

### 3.6 Existing test impact audit

**Important context for this audit:** After Story 1.3, `useStudyDigest(cloneSourceId, { enabled: Boolean(cloneSourceId) })` is called **unconditionally** at the top of `CreateStudyModal`. Any existing test that opens the modal with `initialValues.cloneSource` set (whether or not the test advances to Step 4) will trigger that hook call. Tests that don't have a TanStack Query / MSW mock for `GET /api/v1/studies/{id}/digest` may surface as unmocked fetch errors. Story 1.3 owns the audit + fix.

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.clone.test.tsx` | clone flow with `cloneSource` set | several | **Audit during Story 1.3.** The hook will fire even if the test doesn't navigate to Step 4. Add a default `useStudyDigest` mock (returning `status: 'error'` with `DIGEST_NOT_READY`, or `status: 'success'` with `recommended_config: {}` to keep the gate closed) in the test's TanStack Query wrapper. The narrow-bounds checkbox stays absent in either case; verbatim-clone assertions remain unchanged. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | bare "New study" flow | several | **No change.** No `initialValues` means `cloneSourceId === undefined` means `enabled: false` means no fetch fires. Hook returns idle state; gate naturally closed. |
| `ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` (other variants — `auto-fill`, `auto-followup`, `builder-*`, `client-validation`, `demo-suffix`, `followup-prefill`, `metric-k`, `stop-conditions`, `target-filter*`, `template-fetch-error`, `zero-declared`) | various Step-4 flows | many | **Audit during Story 1.3.** Most do NOT pass `cloneSource` (they exercise bare or auto-followup flows, not clone), so the `enabled: false` path applies and no fetch fires. The `followup-prefill` test passes `initialValues.parent` (proposal-followup) but typically not `cloneSource`. If any test happens to seed `cloneSource`, apply the same default digest mock. |
| `ui/tests/e2e/study-clone.spec.ts` | v1 clone E2E (real backend) | 1 case | **No change.** Real backend will respond to the digest request with the seeded study's digest (or 404 if not present). The spec doesn't navigate to Step 4, so the response is silently ignored. |
| All other E2E specs | various flows | many | **No change.** Real backend; same reasoning. |

**Audit task added to Story 1.3:** grep `cloneSource` across `ui/src/__tests__/`, identify any test that seeds `initialValues.cloneSource`, and add a default `useStudyDigest` mock to its wrapper if not already present.

### 3.7 Migration verification

N/A — no migration.

### 3.8 CI gates

- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm test:e2e -- study-clone-narrow-bounds` (Story 1.4)
- [ ] `make test-unit && make test-integration && make test-contract` (no new backend tests, but verify nothing regressed)

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — add a "Recently shipped" entry pointing at PR #(TBD) for `feat_study_clone_narrow_bounds` after merge (post-implementation handoff to /pipeline finalization).
- [ ] **`architecture.md`** — no change required (the feature doesn't introduce new services, layers, or data flows; the new helper and toggle are documented in `ui-architecture.md` per Story 1.4).
- [ ] **`CLAUDE.md`** — no change required (no new conventions or environment variables).

### 4.1 Architecture docs (`docs/01_architecture/`)

- [x] **`ui-architecture.md`** — add "Step-4 derived-value toggles" subsection (Story 1.4, FR-14).

### 4.2 Product docs (`docs/02_product/`)

- [x] **`docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md`** — add forward-pointer line under "Out of scope" (Story 1.4).

### 4.3 Runbooks (`docs/03_runbooks/`)

- [ ] None. No new operator-facing surface; no new env vars; no new debugging surface.

### 4.4 Security docs (`docs/04_security/`)

- [ ] None. Pure frontend transformation; no new secrets, no new data flow.

### 4.5 Quality docs (`docs/05_quality/`)

- [ ] None. Test layer matrix unchanged (unit + component + E2E only; no new contract/integration tests).

**Documentation DoD**

- [ ] `state.md` updated after merge with the implemented-features pointer
- [ ] `ui-architecture.md` paragraph reviewed by the implementing engineer for accuracy

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- One light refactor: widen `useStudyDigest` to accept the `{ enabled }` option (Story 1.2). This aligns the hook with the established `useStudy(id, { enabled })` pattern at [`ui/src/lib/api/studies.ts:67-88`](../../../../ui/src/lib/api/studies.ts#L67-L88). All existing single-arg callers continue to work unchanged.

### 5.2 Planned refactor tasks

- [x] Story 1.2 — `useStudyDigest` signature widen (backward-compatible additive)

### 5.3 Refactor guardrails

- [ ] Existing `useStudyDigest` callers (grep `useStudyDigest` across `ui/src/`) compile without changes
- [ ] No new dependencies added
- [ ] Lint/typecheck remain green

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_study_clone_from_previous` (v1) — `cloneSource` UI metadata + `?clone_from` deep-link + `buildPrefillFromStudy` | Story 1.3 | Shipped (PR #243, 2026-05-25) | Hard — no clone flow to extend |
| `feat_digest_proposal` — `GET /studies/{id}/digest` + `recommended_config` shape | Story 1.2, 1.3, 1.4 | Shipped (PR #41, 2026-05-11) | Hard — no winning-params source |
| `feat_agent_propose_search_space` — Step-4 autofill suppression on non-empty prefill | Story 1.3 | Shipped (PR #175, 2026-05-21) | Soft — feature still works without, but autofill could overwrite the rewrite |
| `seedStudyCompletedWithDigest` helper | Story 1.4 | Exists at `ui/tests/e2e/helpers/seed.ts:716` | Hard — required for the E2E seed setup |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Helper produces a JSON that fails server-side `SearchSpace.model_validate` | Low | Medium (failed POST → toast + retry) | FR-10 algorithm mirrors every constraint from `search_space.py`; unit tests exercise every branch; AC-12 E2E confirms representative happy path |
| `useStudyDigest` signature change breaks an unanticipated caller | Low | Medium | Additive change with `enabled: opts?.enabled ?? Boolean(studyId)` default; existing single-arg callers unaffected (grep confirmed) |
| Reference panel breaks on very long param names or large numeric values | Low | Low | Use `font-mono` + table layout; `JSON.stringify` handles formatting; the existing design tolerates ~20-char names cleanly |
| Engineer confuses verbatim-clone with narrow-clone | Low | Low | Default unchecked; explicit checkbox label + tooltip; reference panel shows what's actually winning |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Helper throws `SyntaxError` from `JSON.parse` | Engineer hand-edits textarea into broken JSON, then checks the box | Toast surfaces; checkbox reverts to unchecked; textarea untouched; ref cleared | User-driven: fix the JSON, re-check |
| `recommended_config` is empty `{}` | Source study has a digest but no winning config (shouldn't happen in normal flow; defensive) | FR-1 gate fails (`Object.keys(...).length > 0` check); checkbox absent | None needed — verbatim-clone works |
| Digest 404 mid-flow (e.g., concurrent delete by another operator) | Race between `useStudyDigest` resolving success and another tab deleting the digest | `useStudyDigest` may re-fetch on focus and flip to error; checkbox disappears; if already checked, textarea retains the narrowed JSON | None needed — submit still works with the narrowed JSON; consistency is per-modal-open |
| All-skipped result on check (every param categorical / missing-winner) | Source has a digest where no numeric param has a winner value | Toast: "No params narrowed — every param is categorical, missing from the winner, or its winner is outside the current bounds." Textarea unchanged. Checkbox stays checked. | None — engineer unchecks if desired |
| Auto-fill suppression breaks (regression elsewhere) | Story unrelated to this one removes the `if (initialValues && prefillSearchSpace !== '') return` guard in the autofill effect | Autofill could overwrite the narrowed JSON | Mitigation: AC-2 in spec covers the bare "New study" → no checkbox path; the AC-12 E2E exercises the clone-flow autofill-suppression invariant indirectly |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — Pure helper (independent; can ship alone if desired).
2. **Story 1.2** — `useStudyDigest` widen (independent; can ship before 1.1).
3. **Story 1.3** — Modal UI (depends on 1.1 + 1.2).
4. **Story 1.4** — E2E + docs (depends on 1.3).

### Parallelization opportunities

- Stories 1.1 and 1.2 are independent and can be developed concurrently by different agents/branches. In a single-agent flow they're sequential but small.
- Story 1.4 docs sub-tasks (ui-architecture paragraph + v1-spec forward-pointer) can be written in parallel with the Playwright test development.

---

## 8) Rollout and cutover plan

- **Rollout stages:** none — single PR ships the feature end-to-end. No feature flag.
- **Migration / cutover:** none.
- **Reconciliation:** none.
- **Release gate:** CI green (`make test-unit`, vitest, lint, typecheck, AC-12 E2E green on `make up` stack) → reviewer approval → merge.

---

## 9) Execution tracker

### Stories (sequential)

- [ ] Story 1.1 — Pure helper `narrowBoundsAroundWinner` + unit tests
- [ ] Story 1.2 — `useStudyDigest` signature widen
- [ ] Story 1.3 — Step-4 checkbox + reference panel + glossary
- [ ] Story 1.4 — Playwright E2E + ui-architecture.md + v1 spec forward-pointer

### Blocked items

None.

### Done this sprint

(populated post-execution)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] All new functions exported via the file's `__all__` or default-export convention (TypeScript: named exports as documented)
- [ ] All new tests pass:
  - [ ] `cd ui && pnpm test <test-file-path>`
  - [ ] `cd ui && pnpm test:e2e -- <spec-name>` (Story 1.4 only)
- [ ] `cd ui && pnpm typecheck` green
- [ ] `cd ui && pnpm lint` green
- [ ] `make test-unit && make test-integration && make test-contract` green (regression — should be no-op for this feature but verify)
- [ ] DoD assertions in the story are all checked

---

## 11) Plan consistency review (executed before write)

### Spec ↔ plan FR coverage

| Spec FR | Plan story | Status |
|---|---|---|
| FR-1 | Story 1.2 (gate prereq) + Story 1.3 (gate consumption) | ✓ |
| FR-2 | Story 1.3 (default unchecked) | ✓ |
| FR-3 | Story 1.3 (label + tooltip) | ✓ |
| FR-4 | Story 1.3 (check → rewrite, no-op gate, error toast) | ✓ |
| FR-5 | Story 1.3 (uncheck → restore) | ✓ |
| FR-6 | Story 1.3 (manual-edits discarded; glossary text) | ✓ |
| FR-7 | Story 1.3 (modal-close reset) | ✓ |
| FR-8 | Story 1.3 (reference panel) | ✓ |
| FR-9 | Story 1.1 (helper contract) | ✓ |
| FR-10 | Story 1.1 (clamp algorithm) | ✓ |
| FR-11 | Story 1.1 (winner outside bounds) | ✓ |
| FR-12 | Story 1.4 (E2E confirms server accepts) | ✓ |
| FR-13 | Story 1.3 (glossary entry) | ✓ |
| FR-14 | Story 1.4 (ui-architecture.md doc) | ✓ |

### Spec ↔ plan endpoint count

Spec §8.1 lists **0 new endpoints** (read-only consumption of two existing endpoints). Plan adds **0 new endpoints**. ✓ Match.

### Spec ↔ plan error code coverage

Spec §8.5 lists **0 new error codes**. Plan adds **0 new error codes** and **0 new contract tests**. ✓ Match.

### Test file count

| Test file | Story | Assigned? |
|---|---|---|
| `ui/src/__tests__/lib/narrow-bounds.test.ts` | 1.1 | ✓ |
| `ui/src/__tests__/lib/api/digests.test.ts` | 1.2 | ✓ |
| `ui/src/__tests__/components/studies/create-study-modal.narrow-bounds.test.tsx` | 1.3 | ✓ |
| `ui/src/__tests__/lib/glossary.test.ts` (existing — extend) | 1.3 | ✓ |
| `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` | 1.4 | ✓ |

No orphan test files.

### Story internal consistency

- **Story 1.1:** new file `narrow-bounds.ts` not claimed by any other story. ✓
- **Story 1.2:** modifies only `digests.ts` + the digest test file. ✓
- **Story 1.3:** modifies `create-study-modal.tsx` + `glossary.ts` + creates one new test file. No file-ownership overlap with 1.4. ✓
- **Story 1.4:** creates one new E2E spec; modifies two doc files. No overlap. ✓

### Open questions resolved

Spec §19 "Open questions": **none**. All 12 decisions D-1 through D-12 are locked. ✓

### Plan ↔ codebase verification

- `ui/src/lib/api/digests.ts` exists and contains the current `useStudyDigest(studyId)` single-arg signature. ✓
- `ui/src/components/studies/create-study-modal.tsx` exists; Step-4 block starts at `step === 3` (line ~921). ✓
- `ui/src/lib/glossary.ts` exists; existing keys like `study.search_space` follow the documented namespace pattern. ✓
- `ui/tests/e2e/helpers/seed.ts:716` exports `seedStudyCompletedWithDigest` returning `{ studyId, digestId, proposalId }`. ✓
- `backend/app/services/test_seeding.py:188` seeds `recommended_config={"title.boost": 2.5}` and `search_space.params['title.boost'] = {low: 0.5, high: 5.0, log: false}` — the AC-12 E2E math is verified. ✓
- `backend/app/api/v1/_test.py:170` exposes `POST /api/v1/_test/studies/seed-completed` under `_require_development_env`. ✓
- `backend/app/api/v1/schemas.py:991-1008` declares `DigestResponse.recommended_config: dict[str, Any]`. ✓
- `backend/app/domain/study/search_space.py` declares `FloatParam`, `IntParam`, `CategoricalParam`, cardinality cap 10⁶. ✓

### Infrastructure path verification

- No migration in this plan — Alembic directory check N/A.
- Router registration N/A — no new router.
- Frontend test file convention verified by listing `ui/src/__tests__/components/studies/` (existing `create-study-modal.<feature>.test.tsx` pattern).

### Frontend data plumbing

- `useStudyDigest` is invoked inside `CreateStudyModal` — the modal has `initialValues` prop carrying `cloneSource` per FR-5 of v1 clone spec. ✓
- `narrowBoundsAroundWinner` is a pure helper — no plumbing dependencies. ✓
- `originalSpaceJsonRef` lives in the same component scope as the form state. ✓

### Persistence scope

- All state is React-internal (useState + useRef). No localStorage, no sessionStorage. Task descriptions and DoD agree. ✓

### Enumerated value contract audit

- No new `<select>`, filter, status badge, or sort key. ✓ Not applicable.

### Audit-event coverage audit

- Pre-MVP2; no `audit_log` table. ✓ Not applicable.

### Frontend UI Guidance completeness

All required subsections present:
- ✓ Insertion point (line ~922, first child of Step-4 div)
- ✓ Analogous markup patterns (full JSX for checkbox + reference panel)
- ✓ Layout and structure
- ✓ Confirmation/modal dialog pattern (N/A justified)
- ✓ Visual consistency table
- ✓ Component composition (inline; rationale provided)
- ✓ Interaction behavior table
- ✓ Handler function patterns (full `handleNarrowBoundsToggle`)
- ✓ Information architecture placement
- ✓ Tooltips and contextual help (glossary key, source-of-truth, JSX)
- ✓ Legacy behavior parity (explicit N/A justified)

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates (see §11 FR coverage table).
- [x] Every story includes New files, Modified files, Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/component/E2E) are explicitly scoped.
- [x] Documentation updates are planned and owned (Story 1.4).
- [x] Lean refactor scope and guardrails are explicit (Story 1.2 `useStudyDigest` widen).
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) performed; no unresolved findings.
- [x] Plan is ready for `/impl-execute --all`.
