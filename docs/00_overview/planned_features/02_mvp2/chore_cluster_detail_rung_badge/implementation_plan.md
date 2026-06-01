# Implementation Plan — chore_cluster_detail_rung_badge

**Date:** 2026-06-01
**Status:** Draft (post-GPT-5.5 convergence)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (Enumerated Value Contract Discipline; E2E real-backend rule); [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) (cluster-detail composition)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR-1 through FR-8 of the spec.
- Frontend-only chore: no backend, no migration, no new endpoints. The one shared-hook touch (`ui/src/lib/api/ubi.ts`) is isolated to its own story (Story 8) so it can be reviewed independently.
- Reuse over abstraction: the new card composes `Card` + `<UbiRungBadge>` + `<DemoBadge>` + the existing Select primitive; no new shared primitive is extracted.
- Tests sit at the boundaries the chore touches: vitest for component logic + summary regression; one Playwright spec exercising the auto-seeded demo path against a real backend.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (mount card on cluster-detail) | Story 1 | Add `<ClusterDetailUbiReadinessCard cluster={cluster} />` to `ClusterDetailView` between `ClusterActionBar` and `ClusterDetailIndicesCard` (D-2). |
| FR-2 (query-set picker, `limit=50` + `has_more` hint) | Story 2 | Picker call separate from auto-seed proof (D-14). |
| FR-3 (target input, free-form, length cap, debounce) | Story 3 | 200 ms debounce + 256-char cap matching backend (`backend/app/api/v1/clusters.py:420`). |
| FR-4 (auto-seed predicate, `limit=2` call, `length===1 && !has_more`) | Story 4 | Two separate `useQuerySets` calls (D-11 / D-14). |
| FR-5 (resolved render + dual gate + chip relocation) | Story 5 | Includes the leak guard (D-16) and the `<DemoBadge>` move out of `ClusterDetailSummary`. |
| FR-6 (empty state) | Story 2 | Bundled with the picker story (same code path — picker call returns 0 rows). |
| FR-7 (loading + error UX, unified 404/503 caption) | Story 6 | Caption gated on `covered_pairs_pct === null && head_covered === null` (D-10). |
| FR-8 (test coverage: vitest + Playwright) | Story 7 | All AC vitest assertions + the one Playwright spec. |
| Shared-hook patch (D-15) | Story 8 | One-line `placeholderData: keepPreviousData` in `useUbiReadiness`. Owned by its own story so the diff is unambiguous in review. |

All FRs covered; no deferred phase (single-phase chore per feature_spec.md §3). No `phase2_idea.md` required.

## 2) Delivery structure

**Single epic, 8 stories** — small frontend chore. Execute sequentially: Story 8 (shared-hook patch) first so AC-8 can land green; then Stories 1–7 in order.

**File ownership note (GPT-5.5 cycle-1 finding A1):** `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` is **created in Story 1** and **incrementally extended** in Stories 2, 3, 4, 5, 6. This is intentional — each story adds one self-contained branch to the same file (picker → input → auto-seed → resolved → caption) so each commit ships a reviewable slice. Story 1 owns the file (single "New" row across the plan); Stories 2–6 list it under "Modified" with the precise additive change described. Tests for the whole file land in Story 7. This is a normal pattern for incremental single-component UI builds and does not violate the "no shared file ownership" rule (which targets the case where two stories make conflicting changes to the same artifact).

### Story-level detail requirements

Each story below carries: Outcome, New files, Modified files, Tasks, DoD. There are no backend changes, so Endpoints / Key interfaces / Pydantic schemas sections are omitted unless a story modifies one.

### Conventions

- Frontend stories follow `'use client';` + named-export-of-Card-component shape per `ClusterDetailIndicesCard` ([`ui/src/components/clusters/cluster-detail-indices-card.tsx`](../../../../ui/src/components/clusters/cluster-detail-indices-card.tsx)).
- TanStack Query: `placeholderData: keepPreviousData` imported from `@tanstack/react-query` (Story 8).
- Wire-enum discipline: only enum surfaced is `UbiReadinessRung`, imported from `@/lib/enums`; the card touches no inline `<SelectItem value="<literal>">` for backend-bound wire values (the query-set `<select>` lists DB rows by id, target is free-form text).
- Tests follow the cluster-detail-summary vitest pattern (`render` from `@testing-library/react`, `screen.getByTestId`, `TooltipProvider` wrap if `HelpPopover` is in the tree).
- E2E follows the real-backend rule per CLAUDE.md "E2E Testing Rules" — no `page.route()` mocking; setup via API helpers, interaction via `page`.

### AI Agent Execution Protocol

Story execution order: **8 → 1 → 2 → 3 → 4 → 5 → 6 → 7**. Story 8 first because subsequent stories' AC-8 / AC-8b vitest assertions assume `keepPreviousData` is active in the shared hook. Stories 2/3/4/5/6 build the card incrementally; Story 7 ships the test suite. Story 7's Playwright spec is the last gate.

---

## Epic 1 — Cluster-detail UBI readiness card

### Story 8 — Patch `useUbiReadiness` to retain previous data across edits (D-15)

**Outcome:** The shared `useUbiReadiness` hook passes `placeholderData: keepPreviousData` to its internal `useQuery` call so the badge value persists across `(query_set_id, target)` edits without a skeleton flash. The generate-judgments dialog (the existing consumer) is functionally unaffected.

**New files:** _None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/ubi.ts` | Add `placeholderData: keepPreviousData` to the `useQuery` options inside `useUbiReadiness`. One-line change. |

**Tasks**

1. In `ui/src/lib/api/ubi.ts`, add `keepPreviousData` to the imports from `@tanstack/react-query`:
   ```ts
   import { useMutation, useQuery, keepPreviousData, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query';
   ```
2. Inside the `useQuery` call at `ubi.ts:78-104`, add `placeholderData: keepPreviousData,` after the `staleTime: UBI_READINESS_STALE_MS,` line.
3. No JSDoc edit required — the comment block already documents graceful-degrade behavior, and `keepPreviousData` is a refinement, not a contract change.

**Definition of Done**

- `ui/src/lib/api/ubi.ts` imports `keepPreviousData` from `@tanstack/react-query`.
- The `useUbiReadiness` `useQuery` options object contains `placeholderData: keepPreviousData`.
- Existing generate-judgments dialog vitest tests pass unchanged (no `page.route` or hook-mocking changes needed — `placeholderData` is a no-op for cold-mount cases the existing tests cover).
- `cd ui && pnpm typecheck` passes.
- `cd ui && pnpm lint` passes.

---

### Story 1 — Mount `<ClusterDetailUbiReadinessCard>` on `/clusters/[id]`

**Outcome:** A new card is unconditionally mounted on the cluster-detail page between `<ClusterActionBar>` and `<ClusterDetailIndicesCard>` (D-2). The card's interior is initially a thin shell (Story 2 fills it in); Story 1 ships the composition wiring + the component scaffold + the type-level props contract.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | New card component exporting `ClusterDetailUbiReadinessCard({ cluster })`. Story 1 ships the `'use client'` scaffold + `<Card>/<CardHeader>/<CardTitle>/<CardContent>` shell + the `cluster: ClusterDetail` prop interface + a placeholder body ("UBI readiness pickers — coming soon" comment + a `data-testid="cluster-detail-ubi-readiness-card"` anchor). Stories 2–6 replace the placeholder body. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/clusters/[id]/page.tsx` | Add the import `import { ClusterDetailUbiReadinessCard } from '@/components/clusters/cluster-detail-ubi-readiness-card';` and mount `<ClusterDetailUbiReadinessCard cluster={cluster} />` in `ClusterDetailView` between line 35 (`<ClusterActionBar cluster={cluster} />`) and line 36 (`<ClusterDetailIndicesCard clusterId={cluster.id} />`). |

**UI element inventory (Story 1 only — scaffold)**

| Element | Type | Label/title | Data source | Interactions |
|---|---|---|---|---|
| Card outer | `<Card>` | — | n/a | — |
| Card header | `<CardHeader>` + `<CardTitle>` with adjacent `<HelpPopover glossaryKey="cluster.ubi_readiness">` | "UBI readiness" | static title + existing glossary entry | hover/focus on `ⓘ` icon shows the existing rung-ladder description |
| Card body | `<CardContent>` | empty placeholder w/ comment | static | — |

**Note (GPT-5.5 cycle-2 C-2):** The `<HelpPopover>` MUST mount on the card title — not just on the badge inside the resolved row. The spec §11 tooltip table says "Card header 'UBI readiness': re-uses the existing `cluster.ubi_readiness` glossary entry" — that copy is intentionally placed at the card-header level so the help is reachable in the empty / pickers-unset / error states where the badge does not render. Without this, those states have no contextual help for "what is UBI readiness?"

**State dependency analysis:** Story 1 introduces no state.

**Tasks**

1. Create `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` with the scaffold per the "Analogous markup patterns" section of UI Guidance below.
2. Edit `ui/src/app/clusters/[id]/page.tsx` to import + mount the card as the third child of `<DetailPageShell>`'s render-prop after `<ClusterActionBar>`.
3. Verify `cd ui && pnpm typecheck` succeeds (the `cluster: ClusterDetail` prop type comes from `@/lib/api/clusters`).
4. Verify `cd ui && pnpm lint` succeeds (no console warnings; no unused imports).

**Definition of Done**

- The new file exists with the scaffold + `data-testid="cluster-detail-ubi-readiness-card"` on the outer Card.
- Visiting `/clusters/[id]` in `pnpm dev` shows the empty card mounted in the documented position (verified manually via the dev server; automated assertion lands in Story 7).
- Typecheck + lint green.

---

### Story 2 — Query-set picker (`limit=50`) + empty state + `has_more` hint

**Outcome:** The card's interior renders one of three branches based on the picker call's settled response: (a) empty state with "Create a query set" hint + Link when the cluster has zero query sets, (b) `<Select>` populated from the picker call's `data.data` rows when ≥1 row, (c) a "Showing first 50; refine your query in the search field" footer hint when `has_more === true`. Triggers no readiness call yet (Story 3 wires the target input; Story 4 the auto-seed).

**New files:** _None._ (continues editing the file Story 1 created)

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | Replace the placeholder body with the picker branch logic. Import `useQuerySets` from `@/lib/api/query-sets`, the `Select` primitives from `@/components/ui/select`, and `Link` from `next/link`. Introduce React state `const [querySetId, setQuerySetId] = useState<string>('')`. |

**UI element inventory**

| Element | Type | Label/title | Data source | Interactions |
|---|---|---|---|---|
| Picker label | `<Label>` | "Query set" | static | — |
| Picker | `<Select value={querySetId} onValueChange={setQuerySetId}>` | placeholder "Select a query set" | `pickerQuery.data.data` (after settled) | `onValueChange` sets local React state |
| Clear button | `<Button size="sm" variant="ghost">` | "Clear" — only visible when `querySetId !== ''` | `querySetId` | `onClick={() => setQuerySetId('')}` resets to empty. Required because Radix `<Select>` forbids an empty-string `<SelectItem value="">` option (cycle-3 D-1), so the only reachable path to `querySetId === ''` post-selection is this button. Without it, AC-8b's "clearing the query-set picker hides the badge" assertion would be unreachable from the UI. |
| `has_more` footer | `<p>` + inline `<Link>` | "Showing first 50 query sets. [Browse all](/query-sets?cluster_id={id})" — link to the full list page where the `?q=` substring filter lives | `pickerQuery.data.has_more` | click on Link navigates to `/query-sets?cluster_id={id}` |
| Empty-state hint | `<p>` + `<Link>` | "Create a query set to check UBI readiness for this cluster." + Link to `/query-sets/new?cluster_id={id}` | `pickerQuery.data.data.length === 0 && pickerQuery.status === 'success'` | clicking Link navigates |
| Loading indicator | `<p>` | "Loading query sets…" | `pickerQuery.isPending` | — |
| Error state | `<p>` + `<Button>` | "Couldn't load query sets" + Retry | `pickerQuery.isError` | Retry calls `pickerQuery.refetch()` |

**Wire-enum discipline:** The `<Select>` lists rows by `QuerySetSummary.id` (DB row id, not an enum literal) — no `enums.ts` allowlist applies. No new inline `<SelectItem value="<literal>">` for backend-bound wire values; the option values are dynamic ids fetched from the API.

**Tasks**

1. Declare `const PICKER_LIMIT = 50;` at the top of the card module.
2. Add `const pickerQuery = useQuerySets({ cluster_id: cluster.id, limit: PICKER_LIMIT });`.
3. Render the branches in priority order: loading → error → empty (`pickerQuery.data.data.length === 0`) → picker (with `has_more` footer when applicable).
4. Confirm the `Link` href: read `ui/src/app/query-sets/` to confirm whether the create flow is `/query-sets/new?cluster_id={id}` or a different path; cite the actual path in the code.

**Definition of Done**

- AC-4 vitest assertion (empty-state path) passes once Story 7 lands.
- Lint + typecheck green.
- Manual `pnpm dev` smoke: empty cluster renders the hint; populated cluster renders the picker.

---

### Story 3 — Target input + 200 ms debounce + 256-char cap

**Outcome:** The card adds the free-form `<Input>` for the readiness target. Input is empty by default; placeholder is `cluster.target_filter ?? "index or collection name"`. A 200 ms debounce trims and propagates the value to the readiness fetch only when both controls are non-empty (Story 5 hooks up the actual fetch call).

**New files:** _None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | Add `const [targetRaw, setTargetRaw] = useState<string>('')` + a `useDebounce(targetRaw, 200)` (lookup the existing debounce helper in `ui/src/hooks/` at impl time; if none exists, inline a minimal `useEffect` debounce). Add the `<Label>` + `<Input>` pair. Enforce `maxLength={256}` matching backend cap. |

**UI element inventory**

| Element | Type | Label/title | Data source | Interactions |
|---|---|---|---|---|
| Target label | `<Label>` | "Target" | static | — |
| Target input | `<Input maxLength={256}>` | placeholder = `cluster.target_filter ?? "index or collection name"` | `targetRaw` React state | `onChange` updates `targetRaw` |

**Tasks**

1. Add the input with `maxLength={256}` and `placeholder={cluster.target_filter ?? 'index or collection name'}`.
2. Implement debounce. Prefer reusing an existing hook (grep `ui/src/hooks/` for `useDebounce`); fallback to an inline `useEffect` setting a `targetDebounced` state after 200 ms.
3. Compute `const target = targetDebounced.trim();` — this is the value passed to the readiness hook in Story 5.

**Definition of Done**

- Lint + typecheck green.
- AC-8 manually verifiable in `pnpm dev` (the badge would re-fetch on edit — full assertion lands in Story 7's vitest).

---

### Story 4 — Auto-seed proof (separate `limit=2` call; `length===1 && !has_more && target_filter`)

**Outcome:** A second `useQuerySets({ cluster_id, limit: 2 })` call drives the auto-seed predicate. When the predicate holds on first settled response, the picker and target input are initialized to that pair via a `useEffect` that runs once when the proof transitions to settled+matching.

**New files:** _None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | Add `const autoSeedProbe = useQuerySets({ cluster_id: cluster.id, limit: 2 });` + a `useEffect` that fires once on **first-settle** (regardless of outcome) and conditionally calls `setQuerySetId` / `setTargetRaw` per the FR-4 predicate. Track `const [didEvaluateAutoSeed, setDidEvaluateAutoSeed] = useState(false)` (GPT-5.5 cycle-1 B4 — auto-seed is an initial-mount decision; later refetches of the probe MUST NOT trigger a delayed auto-seed even if the row count changes). |

**UI element inventory:** _None._ (logic-only)

**State dependency analysis**

```
State being added: didEvaluateAutoSeed (boolean, local to the card)
Referenced by:
  - The auto-seed useEffect, gate condition `!didEvaluateAutoSeed`
  - Set to true once the FIRST settled probe response is observed,
    regardless of whether the predicate matched
Removed by: unmount; no cross-component dependency
```

**Tasks**

1. Add the proof call + the seed effect (canonical version — GPT-5.5 cycle-1 B4 + B5):

   ```ts
   const autoSeedProbe = useQuerySets({ cluster_id: cluster.id, limit: 2 });
   const [didEvaluateAutoSeed, setDidEvaluateAutoSeed] = useState(false);

   useEffect(() => {
     if (didEvaluateAutoSeed) return;
     // GPT-5.5 cycle-2 C-1: lock the decision on BOTH success and error.
     // If the probe errors first and later refetches successfully, we still
     // must NOT trigger a delayed auto-seed (initial-mount decision only).
     if (autoSeedProbe.status === 'pending') return;

     if (autoSeedProbe.status === 'success') {
       const rows = autoSeedProbe.data.data;
       const hasMore = autoSeedProbe.data.has_more;
       const trimmedTargetFilter = (cluster.target_filter ?? '').trim();
       const shouldSeed =
         rows.length === 1 && !hasMore && trimmedTargetFilter.length > 0;
       if (shouldSeed && rows[0]) {
         setQuerySetId(rows[0].id);
         setTargetRaw(trimmedTargetFilter);
       }
     }
     // status === 'error' → lock without seeding (initial decision = "do not seed").
     setDidEvaluateAutoSeed(true);
   }, [autoSeedProbe.status, autoSeedProbe.data, cluster.target_filter, didEvaluateAutoSeed]);
   ```

   Why this is the canonical form (resolving GPT-5.5 cycle-1 B5 + cycle-2 C-1):
   - The dep array lists every value the effect reads — `autoSeedProbe.status`, `autoSeedProbe.data`, `cluster.target_filter`, and `didEvaluateAutoSeed`. No exhaustive-deps lint suppression needed.
   - `setDidEvaluateAutoSeed(true)` runs unconditionally on the first `success` OR `error` settle, locking out later refetches (cycle-2 C-1 — auto-seed is an initial-mount decision; a probe that errors then succeeds must NOT trigger a delayed seed that overwrites operator-entered state).
   - The `shouldSeed && rows[0]` guard prevents a TypeScript narrowing failure if `rows[0]` is `undefined` (defensive — `rows.length === 1` already implies non-empty).

2. Confirm the two `useQuerySets` calls have distinct React Query cache keys (`['query-sets', { cluster_id, cursor, limit: 50, ... }]` vs `['query-sets', { cluster_id, cursor, limit: 2, ... }]`) — they do, per the existing keying in `ui/src/lib/api/query-sets.ts:57`.

**Definition of Done**

- AC-2 + AC-3 vitest assertions pass after Story 7 lands.
- Lint + typecheck green.

---

### Story 5 — Resolved render (`<UbiRungBadge>` + relocated `<DemoBadge>` + dual leak gate)

**Outcome:** When both picker controls hold non-empty values, the card calls `useUbiReadiness(cluster.id, querySetId, target)` and renders the `<UbiRungBadge>` + (conditionally) the `<DemoBadge variant="synthetic-ubi">` adjacent. The dual gate (D-16) prevents a stale badge from rendering after the operator clears a control. The synthetic-data chip is **removed** from `ClusterDetailSummary` in the same story.

**New files:** _None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | Wire `useUbiReadiness`; render the badge + chip under the dual-gate condition. Import `UbiRungBadge`, `DemoBadge`, `isDemoSyntheticUbiClusterName`, `useUbiReadiness`. |
| `ui/src/components/clusters/cluster-detail-summary.tsx` | Remove the `showSyntheticUbiChip` block (lines 18–30 area) — delete the `import { DemoBadge } from '@/components/common/demo-badge';` line if `DemoBadge` is unused elsewhere in the file (it is — only the synthetic-UBI usage), delete the `import { isDemoSyntheticUbiClusterName } from '@/lib/demo-data';` line, delete the FR-7 comment block + the `const showSyntheticUbiChip = …` + the conditional `<DemoBadge>` JSX inside `<CardTitle>`. After this story `<CardTitle>` is `<span>{cluster.name}</span> + <StatusBadge>` only. |

**UI element inventory (resolved branch)**

| Element | Type | Label/title | Data source | Interactions |
|---|---|---|---|---|
| Badge | `<UbiRungBadge rung={readinessQuery.data.rung}>` | text from `RUNG_LABELS[rung]` | readiness response | tooltip via existing `HelpPopover` |
| Synthetic chip | `<DemoBadge variant="synthetic-ubi">` | "Synthetic demo data" | `isDemoSyntheticUbiClusterName(cluster.name)` | hover tooltip from `DemoBadge` |

**Tasks**

1. Compute picker-ready state first (GPT-5.5 cycle-1 B1 — FR-2 requires the readiness fetch to be disabled while `useQuerySets` is loading or has errored):
   ```ts
   const pickerReady = pickerQuery.status === 'success';
   ```
2. Add the readiness call gated on `pickerReady`:
   ```ts
   const readinessQuery = useUbiReadiness(
     cluster.id,
     pickerReady ? (querySetId || null) : null,
     pickerReady ? (target || null) : null,
   );
   ```
3. Compute the dual leak gate (D-16):
   ```ts
   const pickerStateValid = pickerReady && querySetId !== '' && target.length > 0;
   const showBadge = pickerStateValid && readinessQuery.data != null;
   ```
4. Render the badge row only when `showBadge` is true; render the chip inside the same row gated on `isDemoSyntheticUbiClusterName(cluster.name)`.
5. Edit `cluster-detail-summary.tsx` to delete the chip + its supporting state + unused imports per the Modified-files table.

**Definition of Done**

- AC-2, AC-5, AC-6, AC-8b vitest assertions pass after Story 7 lands.
- `ClusterDetailSummary` no longer references `DemoBadge` / `isDemoSyntheticUbiClusterName` / `showSyntheticUbiChip`.
- Vitest summary regression test (Story 7) asserts the chip is absent from the summary card.
- Lint + typecheck green.

---

### Story 6 — Unified fallback caption + inline error UX

**Outcome:** When the readiness hook returns the synthetic `rung_0` fallback (`covered_pairs_pct === null && head_covered === null`), the card shows the unified caption "Couldn't refresh UBI status (cluster unreachable or query set missing)" next to the badge. On unrecognized error codes (anything other than 404/503 that the hook re-throws), the card renders a small inline error with a one-click retry.

**New files:** _None._

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/cluster-detail-ubi-readiness-card.tsx` | Add the caption + error rendering branches. Use the existing `Button` primitive for retry. |

**UI element inventory**

| Element | Type | Label/title | Data source | Interactions |
|---|---|---|---|---|
| First-fetch skeleton | `<div>` w/ `Skeleton` primitive | aria-label "Loading UBI readiness" | `pickerStateValid && readinessQuery.isPending && readinessQuery.data == null` | static |
| Fallback caption | `<p>` | "Couldn't refresh UBI status (cluster unreachable or query set missing)." | `readinessQuery.data != null && readinessQuery.data.covered_pairs_pct === null && readinessQuery.data.head_covered === null` | static text |
| Inline error + retry | `<div>` + `<Button>` | "Couldn't load UBI readiness" + Retry | `readinessQuery.isError` | Retry invalidates the readiness query key via `queryClient.invalidateQueries({ queryKey: ['ubi-readiness', cluster.id, querySetId, target] })` per spec FR-7 (GPT-5.5 cycle-1 B3) |

**Tasks**

1. Add the readiness skeleton branch first (GPT-5.5 cycle-1 B2 — FR-7 explicitly requires a small inline skeleton while in-flight). The skeleton renders only when (a) `pickerStateValid` is true, (b) `readinessQuery.isPending` is true, AND (c) `readinessQuery.data == null` — the `data == null` clause ensures the skeleton does NOT replace a `placeholderData`-preserved previous badge during a target edit (AC-8 invariant). Use the existing `<Skeleton>` primitive from `@/components/ui/skeleton` if present; otherwise inline `<div className="h-5 w-32 animate-pulse rounded bg-muted" aria-label="Loading UBI readiness" />`.
2. Add the caption gate. Render the caption as a sibling of the badge row (same `flex` row, `text-xs text-muted-foreground`).
3. Add the inline error branch above the caption branch — `isError` takes precedence (this only triggers on unrecognized codes; the hook absorbs 404/503). The retry button calls `queryClient.invalidateQueries({ queryKey: ['ubi-readiness', cluster.id, querySetId, target] })` to satisfy the spec FR-7 "invalidate the React Query cache" requirement (NOT `readinessQuery.refetch()` — that would refetch without honoring the cache invariant the spec asks for; GPT-5.5 cycle-1 B3). The card imports `useQueryClient` from `@tanstack/react-query` and uses `const queryClient = useQueryClient();` at the top.

**Definition of Done**

- AC-7 vitest assertions pass after Story 7 lands (covers: skeleton on first fetch, unified caption on 404/503 fallback, inline error + invalidate-on-retry).
- Lint + typecheck green.

---

### Story 7 — Vitest + Playwright coverage

**Outcome:** Ship the test suite that proves every AC.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/clusters/cluster-detail-ubi-readiness-card.test.tsx` | Vitest spec for the new card. Covers AC-1 (mount — implicit via render), AC-2 (auto-seed on `acme-products-prod` fixture), AC-3 (no auto-seed on multi-row OR `has_more`), AC-4 (empty state), AC-5 (chip relocates), AC-6 (no chip on non-demo), AC-7 (unified caption on fallback + skeleton on first fetch), AC-8 (placeholder data — assert badge text persists during a target edit), AC-8b (leak guard — clearing **either** control via the target input OR the "Clear" button on the picker hides the badge + chip), AC-9 (enum discipline — static-source regex assertion: `/['"\`]rung_[0-3]['"\`]/` matches **zero times** in the card file. The import-existence assertion was dropped in plan-review cycle 1 finding B7 — the card does not need to explicitly import `UbiReadinessRung` because it only flows the rung value through `<UbiRungBadge>`). |
| `ui/tests/e2e/cluster-detail-ubi-readiness.spec.ts` | Playwright E2E spec — real backend, no `page.route()` mocking. Visits `/clusters/{acme-products-prod-id}` after `make seed-demo` has run; asserts the badge is mounted with `data-rung` ≠ `"rung_0"`, that exactly one synthetic-UBI chip is present and is contained inside the new card (not inside `ClusterDetailSummary`). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/__tests__/components/clusters/cluster-detail-summary.test.tsx` | Add a test case asserting `queryByTestId('demo-badge-synthetic-ubi')` returns `null` even for a demo synthetic-UBI cluster name (the chip moved out of the summary in Story 5). |

**Tasks**

1. Set up the vitest spec with the standard `<TooltipProvider>` wrapper (the badge's `HelpPopover` needs it) plus a real `<QueryClientProvider>` wrapping the rendered tree (GPT-5.5 cycle-1 B6 — AC-8 specifically validates `placeholderData: keepPreviousData`, so the spec MUST exercise real TanStack Query semantics; mocking `useQuery` directly would bypass exactly the behavior under test). Anchor the canonical setup to `cluster-detail-indices-card.test.tsx`.
2. **Network-layer mocking only.** Mock the `apiClient` (e.g., via `vi.spyOn(apiClient, 'get').mockResolvedValueOnce(…)` per endpoint), NOT `useQuery` / `useMutation` / `keepPreviousData`. Forbidden: `vi.mock('@tanstack/react-query', …)`. Permitted: mocking `apiClient.get` to return staged responses for `/api/v1/query-sets` and `/api/v1/clusters/{id}/ubi-readiness`.
3. For AC-8 (`placeholderData` persistence): seed an initial response (e.g., `{rung: 'rung_1'}`), wait for the badge to render, fire a target-input change, assert via `waitFor` that the badge's `data-rung` attribute remains `"rung_1"` until the second response (`{rung: 'rung_2'}`) resolves, then assert it transitions to `rung_2`. The assertion is "the `ubi-rung-badge` element never unmounts during the transition."
4. For AC-8b (leak guard): seed a resolved state; call `fireEvent.change(targetInput, { target: { value: '' } })`; assert `queryByTestId('ubi-rung-badge')` returns `null` AND `queryByTestId('demo-badge-synthetic-ubi')` returns `null`. The hook's `enabled` predicate ensures no new fetch fires.
5. For AC-9 (enum discipline — relaxed per GPT-5.5 cycle-1 B7): the test uses `fs.readFileSync` to read the card source and assert NO inline rung-string literals appear in the JSX. Specifically: the regex `/['"`]rung_[0-3]['"`]/` should match zero times in the card source. The card does not need to explicitly import `UbiReadinessRung` (it only flows `readinessQuery.data.rung` into the badge), so the import-existence assertion is dropped — the no-inline-literal assertion is the substantive guardrail.
6. Write the Playwright spec. Use `request.newContext` for setup (resolve the acme cluster id by GETting `/api/v1/clusters` and filtering by `name: 'acme-products-prod'`) and `page` for all assertions. Anchor selectors to `data-testid` (`cluster-detail-ubi-readiness-card`, `ubi-rung-badge`, `demo-badge-synthetic-ubi`) and the `data-rung` attribute — not text content.
7. Run `cd ui && pnpm test cluster-detail-ubi-readiness-card` and confirm all AC assertions green.
8. Run the Playwright spec via the project's standard E2E command (read `ui/package.json` `scripts` block at impl time; common patterns are `pnpm test:e2e` or `pnpm playwright test`).

**Definition of Done**

- Vitest spec passes; coverage hits all of AC-1 through AC-9.
- Vitest summary regression passes (chip absent from `ClusterDetailSummary`).
- Playwright spec passes against a live backend with `make seed-demo` data.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all green.

---

## UI Guidance

### Reference: current component structure

**`ui/src/app/clusters/[id]/page.tsx` (55 lines, [page.tsx](../../../../ui/src/app/clusters/[id]/page.tsx))** — the cluster-detail page.
- Section structure (lines 24–48 in `ClusterDetailView`):
  - L25: outer `<main>` wrapper
  - L26-29: "← All clusters" back link
  - L31-47: `<DetailPageShell>` render-prop block
    - L33: `<ClusterDetailSummary cluster={cluster} />`
    - L34: `<ClusterActionBar cluster={cluster} />`
    - L35: `<ClusterDetailIndicesCard clusterId={cluster.id} />`
    - L36-44: "Studies using this cluster" Card with `<StudiesByClusterTable>`
- **Insertion point:** new card mounts between line 35 and 36 — replace L35-36 with the new sequence:
  ```tsx
  <ClusterActionBar cluster={cluster} />
  <ClusterDetailUbiReadinessCard cluster={cluster} />
  <ClusterDetailIndicesCard clusterId={cluster.id} />
  ```
- State variables: none (page is purely composition).
- Props: `RouteProps { params: Promise<{ id: string }> }` (App Router pattern).

**`ui/src/components/clusters/cluster-detail-summary.tsx` (87 lines, [cluster-detail-summary.tsx](../../../../ui/src/components/clusters/cluster-detail-summary.tsx))** — summary card.
- Section structure (lines 18–86):
  - L18-22: `showSyntheticUbiChip` derivation
  - L25-32: `<CardHeader>` with `<CardTitle>` containing name + `StatusBadge` + (conditionally) the synthetic-UBI chip
  - L33-83: `<CardContent>` with the dl/dt/dd grid
- State variables: none.
- Props: `ClusterDetailSummaryProps { cluster: ClusterDetail }`.
- **Lines to remove in Story 5:** L18-23 (the comment + `showSyntheticUbiChip` const), L30 (the conditional `<DemoBadge>`), the `DemoBadge` import on L7, the `isDemoSyntheticUbiClusterName` import on L11.

**`ui/src/components/clusters/ubi-rung-badge.tsx` (49 lines, [ubi-rung-badge.tsx](../../../../ui/src/components/clusters/ubi-rung-badge.tsx))** — text badge.
- Props: `{ rung: UbiReadinessRung }` (single field). Reused unchanged.

**`ui/src/lib/api/ubi.ts` ([ubi.ts](../../../../ui/src/lib/api/ubi.ts))** — readiness hook.
- Single-line touch in Story 8: adds `placeholderData: keepPreviousData` to the `useQuery` options at lines 78–104.

### Analogous markup patterns

**Pattern A — Card with data-fetching hook + multi-branch body (from `cluster-detail-indices-card.tsx:34-90`):**

```tsx
'use client';

import Link from 'next/link';
import { useMemo } from 'react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useClusterTargets } from '@/lib/api/clusters';

export interface ClusterDetailUbiReadinessCardProps {
  cluster: ClusterDetail;
}

export function ClusterDetailUbiReadinessCard({ cluster }: ClusterDetailUbiReadinessCardProps) {
  const pickerQuery = useQuerySets({ cluster_id: cluster.id, limit: 50 });
  // … auto-seed proof, readiness hook, debounced target, etc.

  const renderBody = () => {
    if (pickerQuery.isPending) {
      return <p className="text-sm text-muted-foreground">Loading query sets…</p>;
    }
    if (pickerQuery.isError) {
      return (
        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">Couldn&apos;t load query sets.</p>
          <Button size="sm" variant="outline" onClick={() => pickerQuery.refetch()}>Retry</Button>
        </div>
      );
    }
    const rows = pickerQuery.data?.data ?? [];
    if (rows.length === 0) {
      return (
        <p className="text-sm text-muted-foreground">
          Create a query set to check UBI readiness for this cluster.{' '}
          <Link className="text-blue-600 underline-offset-4 hover:underline" href={`/query-sets/new?cluster_id=${cluster.id}`}>
            Create a query set →
          </Link>
        </p>
      );
    }
    return <PickerAndResultBody rows={rows} hasMore={pickerQuery.data?.has_more ?? false} />;
  };

  return (
    <Card data-testid="cluster-detail-ubi-readiness-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span>UBI readiness</span>
          <HelpPopover glossaryKey="cluster.ubi_readiness" />
        </CardTitle>
      </CardHeader>
      <CardContent>{renderBody()}</CardContent>
    </Card>
  );
}
```

The `HelpPopover` is imported from `@/components/common/help-popover` (same component the badge already uses at `ubi-rung-badge.tsx:46`). Mounting it on the card header guarantees the glossary copy is reachable in **every** card state (empty / loading / error / picker-unset / resolved) — GPT-5.5 cycle-2 C-2.

(The exact branch logic for `PickerAndResultBody` lives in Stories 2/3/4/5/6 — the pattern above is the analogous shell.)

**Pattern B — Select primitive (from `ui/src/components/ui/select.tsx` + canonical consumer):**

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

<div className="space-y-1">
  <Label htmlFor="cluster-detail-ubi-query-set">Query set</Label>
  <Select value={querySetId} onValueChange={setQuerySetId}>
    <SelectTrigger id="cluster-detail-ubi-query-set" data-testid="cluster-detail-ubi-query-set-trigger">
      <SelectValue placeholder="Select a query set" />
    </SelectTrigger>
    <SelectContent>
      {rows.map((row) => (
        <SelectItem key={row.id} value={row.id}>{row.name}</SelectItem>
      ))}
    </SelectContent>
  </Select>
</div>
```

**Pattern C — Resolved row layout (badge + chip + caption):**

```tsx
<div className="flex flex-row items-center gap-2" data-testid="cluster-detail-ubi-result-row">
  <UbiRungBadge rung={readinessQuery.data.rung} />
  {isDemoSyntheticUbiClusterName(cluster.name) && <DemoBadge variant="synthetic-ubi" />}
  {readinessQuery.data.covered_pairs_pct === null && readinessQuery.data.head_covered === null && (
    <span className="text-xs text-muted-foreground">
      Couldn&apos;t refresh UBI status (cluster unreachable or query set missing).
    </span>
  )}
</div>
```

### Layout and structure

- Card outer: standard `<Card>` from `@/components/ui/card`. No special margin / padding overrides; it inherits the cluster-detail page's `space-y-6` vertical rhythm.
- Card body:
  - Branch (empty): single `<p>` with inline Link.
  - Branch (loading): single `<p>`.
  - Branch (error): `<p>` + `<Button>` row.
  - Branch (picker + maybe-resolved):
    - **Row 1** (`flex flex-col gap-3 md:flex-row md:items-end md:gap-4`): picker `<Select>` (left, `md:flex-1`) + target `<Input>` (right, `md:flex-1`).
    - **Row 2** (the resolved-row layout above) — visible only when `showBadge` is true (Story 5 dual gate).
    - **Row 3** (`has_more` hint, optional): `<p className="text-xs text-muted-foreground">` with Link to `/query-sets?cluster_id={id}`.

Responsive behavior: stacks vertically on mobile (the `md:flex-row` collapse to `flex-col` default).

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Page mounts | `useQuerySets({cluster_id, limit:50})` + `useQuerySets({cluster_id, limit:2})` fire | 2× `GET /api/v1/query-sets?cluster_id=...&limit=...` |
| Auto-seed predicate holds | `setQuerySetId(row.id)` + `setTargetRaw(cluster.target_filter)` | none (state-only) |
| Auto-seed triggers readiness call (because querySetId + target now set) | `useUbiReadiness` enables | `GET /api/v1/clusters/{id}/ubi-readiness?query_set_id=...&target=...` |
| User picks a different query set | `setQuerySetId(newId)` | new readiness fetch after 0 ms (no debounce on picker) |
| User types into target input | `setTargetRaw(newValue)` → debounced 200 ms → new readiness fetch | one fetch per debounce window |
| User clears target input | dual gate hides badge + chip immediately (no fetch) | none |
| Readiness 404/503 | hook synthesizes `rung_0` fallback | (none beyond the original failed call) |
| Readiness other error | card shows inline error + Retry button | Retry calls `queryClient.invalidateQueries({ queryKey: ['ubi-readiness', cluster.id, querySetId, target] })` per spec FR-7 (cycle-1 B3; not `readinessQuery.refetch()`) |
| Clear query-set picker | dual gate hides badge + chip immediately (no fetch); picker `<Select>` returns to placeholder state | `setQuerySetId('')` via the "Clear" `<Button>` (cycle-3 D-1 — Radix Select can't hold an empty `<SelectItem>` so an explicit Clear button is the only reachable path) |

### Handler function patterns

The card's auto-seed effect (key handler — canonical form, lint-clean deps, error-or-success lock):

```tsx
useEffect(() => {
  if (didEvaluateAutoSeed) return;
  if (autoSeedProbe.status === 'pending') return;
  if (autoSeedProbe.status === 'success') {
    const rows = autoSeedProbe.data.data;
    const hasMore = autoSeedProbe.data.has_more;
    const trimmedTargetFilter = (cluster.target_filter ?? '').trim();
    const shouldSeed = rows.length === 1 && !hasMore && trimmedTargetFilter.length > 0;
    if (shouldSeed && rows[0]) {
      setQuerySetId(rows[0].id);
      setTargetRaw(trimmedTargetFilter);
    }
  }
  // status === 'success' OR 'error': lock the decision now.
  setDidEvaluateAutoSeed(true);
}, [autoSeedProbe.status, autoSeedProbe.data, cluster.target_filter, didEvaluateAutoSeed]);
```

The readiness-fetch wiring (Story 5 gates readiness on `pickerReady` per GPT-5.5 cycle-1 B1):

```tsx
const pickerReady = pickerQuery.status === 'success';
const target = useDebounce(targetRaw, 200).trim();
const readinessQuery = useUbiReadiness(
  cluster.id,
  pickerReady ? (querySetId || null) : null,
  pickerReady ? (target || null) : null,
);
const pickerStateValid = pickerReady && querySetId !== '' && target.length > 0;
const showBadge = pickerStateValid && readinessQuery.data != null;
```

### Component composition

- The card is a **single component** — not extracted into sub-components. Internal branches (loading, error, empty, picker, resolved) are inlined via a `renderBody()` local helper or `&&` JSX gates. Rationale: the entire card is ~150 LOC and reads top-to-bottom; sub-extraction would add files without clarity gain.
- The card accepts `{ cluster: ClusterDetail }` and exposes no callback props (read-only view).

### Information architecture placement

- **Where:** between `<ClusterActionBar>` and `<ClusterDetailIndicesCard>` on `/clusters/[id]`.
- **Discovery:** the operator already lands on the cluster-detail page from `/clusters` or after registering a cluster; the card is unconditionally mounted so it's discoverable on first visit. No new sidebar entry, no new tab.
- **Adjacent surfaces unchanged:** the generate-judgments dialog still consumes `<UbiRungBadge>` (unchanged); the `<UbiOnrampNudge>` stays inside the dialog and is NOT mounted on cluster-detail (D-4).

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key | Source-of-truth |
|---|---|---|---|---|---|
| Rung badge | (existing) — long-form description of all four rungs | hover/focus on `HelpPopover` `ⓘ` | top | `cluster.ubi_readiness` | Already grounded in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) (existing entry, no edit) |
| Synthetic-UBI chip | (existing) "Synthetic demo data" | hover/focus | top | n/a (chip text is self-explanatory; no glossary key needed) | Existing `DemoBadge` |
| Fallback caption | "Couldn't refresh UBI status (cluster unreachable or query set missing)." | inline (no hover) | inline (next to badge) | n/a (operator-facing error text, not a domain term) | New copy — does not need a glossary entry per the spec's tooltip table |
| Empty-state hint | "Create a query set to check UBI readiness for this cluster." | inline | inline (replaces card body) | n/a (instruction text, not a domain term) | New copy |

No new glossary keys are added. The `HelpPopover` inside `<UbiRungBadge>` already keys off `cluster.ubi_readiness` (verified `ui/src/components/clusters/ubi-rung-badge.tsx:46`) — the card inherits this for free.

### Visual consistency

| New element | CSS class / pattern | Source |
|---|---|---|
| Card outer | `<Card>` | `@/components/ui/card`, used by `ClusterDetailSummary`, `ClusterDetailIndicesCard`, `StudiesByClusterTable` parent |
| Card title text | `className="text-base"` on `<CardTitle>` | Matches `ClusterDetailIndicesCard:CardHeader` |
| Picker `<Select>` | shadcn primitives from `@/components/ui/select` | Pattern B above |
| Target `<Input>` | `<Input>` from `@/components/ui/input` | Standard form input |
| `<Label>` pairs | `<Label htmlFor>` | shadcn standard |
| Helper / caption text | `text-xs text-muted-foreground` | Matches the existing health-error caption in `ClusterDetailSummary` |
| Retry `<Button>` | `size="sm" variant="outline"` | Matches `ClusterDetailIndicesCard` retry button |

### Legacy behavior parity

**Not applicable.** No user-facing component >100 LOC is being deleted in this plan. The only deletion is the ~5-line synthetic-UBI chip block inside `ClusterDetailSummary` (the `showSyntheticUbiChip` const + the conditional `<DemoBadge>` JSX + two imports). The deleted behavior is **explicitly preserved** at the new placement inside `ClusterDetailUbiReadinessCard` (Story 5 + AC-5), guarded by the same `isDemoSyntheticUbiClusterName(cluster.name)` predicate.

Mini-parity table (single row, for clarity):

| # | Legacy behavior | Location in deleted code | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | `<DemoBadge variant="synthetic-ubi">` adjacent to cluster name when `isDemoSyntheticUbiClusterName(cluster.name)` is true | `cluster-detail-summary.tsx:23-30` | **Relocated** | `cluster-detail-ubi-readiness-card.tsx` resolved row — Pattern C above; gate `isDemoSyntheticUbiClusterName(cluster.name)` unchanged. AC-5 asserts the relocation; AC-6 asserts absence on non-demo clusters; the summary regression test (Story 7) asserts the chip is no longer inside the summary card. |

### Client-side persistence

**Not applicable.** No `localStorage` / `sessionStorage` — picker state is component-local React state only. Deep-linking the picker state via URL params was explicitly rejected (D-7).

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/` — _N/A._ No backend changes; no domain logic added.
- DoD: not applicable.

### 3.2 Integration tests

- Location: `backend/tests/integration/` — _N/A._ No backend changes.
- DoD: not applicable.

### 3.3 Contract tests

- Location: `backend/tests/contract/` — _N/A._ No new endpoints / response shapes; the existing `ubi_readiness` contract test continues to assert the unchanged endpoint.
- DoD: not applicable.

### 3.4 Vitest / E2E tests

- **Vitest location:** `ui/src/__tests__/components/clusters/`.
- **E2E location:** `ui/tests/e2e/`.
- **Scope:** all assertions land in Story 7. No additional test files outside Story 7's New/Modified files tables.
- **Tasks:**
  - [ ] (Story 7) Write `cluster-detail-ubi-readiness-card.test.tsx` covering AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-8b, AC-9.
  - [ ] (Story 7) Add the summary regression test case to `cluster-detail-summary.test.tsx` asserting the chip is no longer rendered in the summary card on demo clusters.
  - [ ] (Story 7) Write `cluster-detail-ubi-readiness.spec.ts` Playwright spec — real backend, no `page.route()` mocking.
- **E2E rule reminder:** the Playwright spec uses `page.goto`, `page.getByTestId`, `page.locator` for assertions. API setup (e.g., resolving the acme cluster id) is acceptable via `request.newContext` but assertions must use `page`.
- **DoD:**
  - [ ] Vitest spec exercises all AC.
  - [ ] Playwright spec passes against `make seed-demo` data with `data-rung` ≠ `"rung_0"`.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/clusters/cluster-detail-summary.test.tsx` | renders summary with cluster name + status | 3 cases today | **Update** — add one case asserting the synthetic-UBI chip is **not** rendered inside the summary even for demo cluster names (Story 5 + Story 7 coverage). |
| `ui/src/__tests__/components/clusters/ubi-rung-badge.test.tsx` | renders RUNG_LABELS by `rung` prop | 1 case | **No change** — the badge component is unchanged. |
| `ui/src/__tests__/components/clusters/cluster-detail-indices-card.test.tsx` | analogous card pattern | n/a | **No change** — referenced as a template only. |
| Phase-1 `feat_demo_ubi_study_comparison` E2E (if any references `demo-badge-synthetic-ubi` adjacent to cluster name on `/clusters/[id]`) | `data-testid="demo-badge-synthetic-ubi"` | grep at impl time | **Update selector anchor** — re-anchor to the new placement inside the readiness card. Confirm at impl time via `grep -r 'demo-badge-synthetic-ubi' ui/tests/`. |

### 3.6 Migration verification

_N/A — no schema changes._

### 3.7 CI gates

- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm build` (Next.js production build)
- [ ] `cd ui && pnpm test:e2e` (or the project's standard Playwright command — confirmed at impl time)
- [ ] Backend gates run by CI but expected to be no-ops: `make test-unit`, `make test-integration`, `make test-contract`.

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update the "Last 5 merges" entry on finalization (move oldest line to `state_history.md`, prepend the chore line-item with PR # + one-sentence summary).
- **`architecture.md`** — no update (no new layer / data flow).
- **`CLAUDE.md`** — no update (no new convention).

### 4.1 Architecture docs

- `docs/01_architecture/ui-architecture.md` — **optional, low priority.** If this doc enumerates the cluster-detail page's children (read at impl time), add a one-line entry for `ClusterDetailUbiReadinessCard` between `ClusterActionBar` and `ClusterDetailIndicesCard`. If the doc only describes patterns and does not enumerate per-page composition, skip.

### 4.2 Product docs (`docs/02_product`)

- No update.

### 4.3 Runbooks (`docs/03_runbooks`)

- No update.

### 4.4 Security docs (`docs/04_security`)

- No update.

### 4.5 Quality docs (`docs/05_quality`)

- No update.

### Documentation DoD

- [ ] `state.md` reflects the merged chore in its "Last 5 merges" section.
- [ ] `ui-architecture.md` updated if it enumerates cluster-detail children (verified at impl time).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Eliminate the dual-placement workaround for the synthetic-UBI chip (chip currently lives at the wrong spec-stated location).
- Centralize the `keepPreviousData` UX (Story 8 patches the shared hook so all `useUbiReadiness` consumers benefit consistently).

### 5.2 Planned refactor tasks

- [ ] (Story 5) Delete the chip render block from `cluster-detail-summary.tsx` (+ unused imports) — does not get re-added at the new placement until Story 5 completes. Care: ensure `pnpm dev` between Story 5 and Story 7 still renders sensibly (the chip will be visible at the new location once Story 5 lands; intermediate commits are fine).
- [ ] (Story 8) Promote `placeholderData: keepPreviousData` to the shared hook rather than wrapping it per consumer.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by vitest summary regression test + AC-5 / AC-6 assertions (chip relocation, not duplication).
- [ ] Lint + typecheck remain green at every story boundary.
- [ ] No expansion of product scope (the on-ramp nudge does NOT migrate to cluster-detail — D-4).
- [ ] No new shared primitives extracted.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `GET /api/v1/clusters/{id}/ubi-readiness` | Story 5 | Implemented (`feat_ubi_judgments`) | N/A — already in prod |
| `useUbiReadiness` hook | Story 5, Story 8 (patched in-place) | Implemented | N/A |
| `useQuerySets({ cluster_id, limit })` | Stories 2, 4 | Implemented; `cluster_id` filter + `limit` filter active | N/A |
| `<UbiRungBadge>` (single-prop) | Story 5 | Implemented | N/A |
| `<DemoBadge variant="synthetic-ubi">` + `isDemoSyntheticUbiClusterName` | Story 5 | Implemented (Phase-1, PR #320) | N/A |
| `acme-products-prod` demo seed at `rung_3` | Story 7 (Playwright) | Implemented (`demo_ubi_seed.py:74`); rung anchored by `test_scenarios_ubi_config.py:99` | If the seed is broken locally, the Playwright spec fails — mitigate by re-running `make seed-demo` (the spec is robust to rung-value drift via D-12). |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vitest mocking of TanStack Query is inconsistent across the repo, causing AC-8 (placeholder data) assertion flakiness | M | L | Reuse the canonical setup from `cluster-detail-indices-card.test.tsx` exactly; if it doesn't include the canonical QueryClient setup, anchor to `studies-by-cluster-table.test.tsx` at impl time. |
| The Playwright project doesn't have a stable command for real-backend specs against `make seed-demo` data | M | M | The repo's `make seed-demo` is the canonical source; Story 7 includes a step to confirm the Playwright command by reading `ui/package.json` `scripts`. If no real-backend command exists, fall back to a backend-up + targeted `playwright test` invocation. |
| `keepPreviousData` import name varies between TanStack Query v4 and v5 | L | L | The repo is on v5 per `ui/package.json` (the project uses `useMutation`/`useQuery` v5 patterns throughout); `keepPreviousData` is the v5 export. Story 8 grep-confirms at impl time. |
| The auto-seed effect dependency array (`[canAutoSeed, didAutoSeed]`) misses re-render reactivity if `candidateRows` identity changes | L | L | The effect is gated on `!didAutoSeed`, so it only ever fires once per mount. Re-runs after `setDidAutoSeed(true)` are no-ops. |
| The query-set create-flow URL (`/query-sets/new?cluster_id={id}`) may not exist as a clean route | M | L | Story 2 includes a step to verify the actual URL by reading `ui/src/app/query-sets/`. If the create flow is a modal triggered from `/query-sets`, link to `/query-sets?cluster_id={id}` with copy "Pick the cluster and click 'New query set'". |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Readiness endpoint returns 503 | Cluster unreachable | Hook degrades to `rung_0` fallback; card renders badge + unified caption per FR-5 / AC-7 | Auto-recovers when the cluster comes back; staleTime 60s |
| Readiness endpoint returns 404 (e.g., query set deleted between picker render and fetch) | Race condition | Hook degrades to `rung_0` fallback; card renders the same unified caption (D-10 — frontend can't distinguish) | Operator picks another query set; the picker re-renders with the fresh `useQuerySets` data |
| `useQuerySets` errors | Network / backend down | Card body shows inline error + Retry button | Operator clicks Retry; `useQuerySets.refetch()` re-issues |
| `useQuerySets` returns >50 rows for cluster | Operator created 51+ query sets | Picker shows first 50 + footer hint pointing to `/query-sets?cluster_id={id}` | Operator filters via `?q=` on the query-sets list, then returns to cluster-detail with that query set picked |
| Operator clears target during a resolved render | UI action | Dual gate (D-16) hides badge + chip immediately; no new fetch fires (`enabled` false on empty target) | Operator re-types; readiness fetches again after debounce |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 8** (shared-hook patch) — first so subsequent stories' AC-8 assertions hold.
2. **Story 1** (mount scaffold) — places the empty card on the page.
3. **Story 2** (picker + empty state) — fills the loading / error / empty / picker branches.
4. **Story 3** (target input + debounce) — adds the second control.
5. **Story 4** (auto-seed) — wires the auto-seed effect.
6. **Story 5** (resolved render + chip relocation) — the user-visible reward.
7. **Story 6** (unified caption + inline error) — fallback UX polish.
8. **Story 7** (tests) — vitest + Playwright suite, summary regression. Last.

### Parallelization opportunities

This chore is small enough that strict serial execution wins. The only safe parallelizable pair would be **Story 8** ↔ **Story 1** (no overlap), but Story 1 is so small (≤20 LOC) that the parallelism overhead exceeds the gain.

## 8) Rollout and cutover plan

- Rollout stages: none — single PR, single merge to `main`.
- Feature flags: none.
- Migration / cutover: none.
- Reconciliation: none.

## 9) Execution tracker

### Current sprint

- [ ] Story 8 — patch `useUbiReadiness` to retain previous data
- [ ] Story 1 — mount card scaffold
- [ ] Story 2 — picker + empty state + `has_more` hint
- [ ] Story 3 — target input + debounce
- [ ] Story 4 — auto-seed effect
- [ ] Story 5 — resolved render + chip relocation
- [ ] Story 6 — unified fallback caption + inline error
- [ ] Story 7 — vitest + Playwright coverage

### Blocked items

_None._

### Done this sprint

_None yet._

## 10) Story-by-Story Verification Gate

### Per-story gate (every story must satisfy)

- [ ] Files created/modified match the story's New/Modified tables.
- [ ] No backend changes outside the explicit scope (`git diff --stat backend/` should be empty for every story; the only `ui/` touch in Story 8 is `ui/src/lib/api/ubi.ts`).
- [ ] `cd ui && pnpm lint && pnpm typecheck` green.
- [ ] `cd ui && pnpm test` green at the end of each story (vitest may show ~0 new cases for Stories 1–6 until Story 7 adds the suite, but the existing test suite MUST stay green).
- [ ] Manual `pnpm dev` smoke for stories with visible UI changes (Stories 1, 2, 5).

### Final-release gate (apply after Story 7)

- [ ] All per-story gates above are green.
- [ ] Story 7's vitest spec exists and passes — every AC (AC-1 through AC-10) asserted.
- [ ] Story 7's Playwright spec passes against a live backend with `make seed-demo` data (CLAUDE.md "E2E real backend" rule — no `page.route()` mocking).
- [ ] `cd ui && pnpm build` green (Next.js production build).
- [ ] `state.md` "Last 5 merges" updated on finalization.

## 11) Plan consistency review

Performed during plan generation; findings:

1. **Spec ↔ plan endpoint count**: spec defines **0 new endpoints** + consumption of 1 existing endpoint (`GET /clusters/{id}/ubi-readiness`). Plan defines **0 new endpoints** and Story 5 wires the consumption. ✅ Match.
2. **Spec ↔ plan error code coverage**: spec catalog has **0 new error codes** (consumes existing 4 codes: `CLUSTER_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `VALIDATION_ERROR`, `CLUSTER_UNREACHABLE`); the hook absorbs 404/503 into `rung_0` fallback and re-throws others. Story 6 covers the inline-error branch for re-thrown errors; Story 7 vitest asserts the fallback caption. ✅ Match.
3. **Spec ↔ plan FR coverage**: FR-1 through FR-8 (and the D-15 shared-hook touch) each map to exactly one story in §1's traceability table. ✅ Match.
4. **Story internal consistency**: each story's Modified files list references real files (verified: `cluster-detail-ubi-readiness-card.tsx` is new; `clusters/[id]/page.tsx`, `cluster-detail-summary.tsx`, `ubi.ts`, `cluster-detail-summary.test.tsx` all exist).
5. **Test file count**: 1 new vitest spec (`cluster-detail-ubi-readiness-card.test.tsx`), 1 modified vitest spec (`cluster-detail-summary.test.tsx`), 1 new Playwright spec (`cluster-detail-ubi-readiness.spec.ts`). All three are assigned to Story 7. ✅ Match.
6. **Gate arithmetic**: §0 "Frontend-only chore" matches the §1 traceability; no story claims a backend / migration / endpoint count.
7. **Open questions resolved**: spec §19 has no open questions (Q-1/Q-2/Q-3 all locked as D-1/D-8/D-9; cycle-1/2/3 findings all addressed as D-10 through D-17). ✅
8. **Plan ↔ codebase verification**:
   - `ui/src/components/clusters/ubi-rung-badge.tsx` exists (verified ✅).
   - `ui/src/app/clusters/[id]/page.tsx` line numbers (L33-36 composition) verified against the live file ✅.
   - `ui/src/components/clusters/cluster-detail-summary.tsx` L18-30 chip block verified ✅.
   - `useQuerySets({ cluster_id, limit })` signature verified at `ui/src/lib/api/query-sets.ts:52` ✅.
   - `useUbiReadiness` signature + 404/503 fallback verified at `ui/src/lib/api/ubi.ts:72-101` ✅.
   - `QuerySetSummary` shape verified at `backend/app/api/v1/schemas.py:510-516` ✅.
   - `acme-products-prod` seed → rung_3 verified at `backend/app/services/demo_ubi_seed.py:74` + `backend/tests/unit/scripts/test_scenarios_ubi_config.py:99` ✅.
   - `<DemoBadge variant="synthetic-ubi">` + `isDemoSyntheticUbiClusterName` verified at `ui/src/components/common/demo-badge.tsx:41, 64` + `ui/src/lib/demo-data.ts` (existing helper) ✅.
9. **Infrastructure path verification**: not applicable (no migration / no router).
10. **Frontend data plumbing verification**: every prop the new card needs (`cluster: ClusterDetail`) is already available in `ClusterDetailView` from `useCluster(clusterId)`. ✅
11. **Persistence scope consistency**: no `localStorage` / `sessionStorage`. ✅
12. **Enumerated value contract audit**: only wire enum surfaced is `UbiReadinessRung` (already grounded in `ui/src/lib/enums.ts:158-160` with the source-of-truth comment). The picker lists DB rows by `id` (not enum literals), the target is free-form text. No new dropdown of backend-bound literals; no new source-of-truth comments needed. ✅
13. **Admin control audit**: N/A — MVP1–MVP3 single-tenant, no auth.
14. **Audit-event coverage audit**: N/A — read-only view; pre-MVP3 audit_log.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Tasks, and DoD (Endpoints / Key interfaces / Pydantic schemas omitted per the "frontend-only chore" framing).
- [x] Test layers (vitest + Playwright) are explicitly scoped; backend layers documented as N/A.
- [x] Documentation updates across docs/01-05 are planned (with most marked N/A).
- [x] Lean refactor scope is explicit (chip relocation + hook patch).
- [x] Sequencing is explicit (Story 8 → 1 → 2 → 3 → 4 → 5 → 6 → 7).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed; no unresolved findings.
