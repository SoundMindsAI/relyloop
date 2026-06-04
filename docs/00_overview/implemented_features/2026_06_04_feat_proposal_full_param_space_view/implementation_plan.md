# Implementation Plan — Proposal Full-Parameter-Space View

**Date:** 2026-06-04
**Status:** Complete (PR #446, squash-merged `3baea3f0` on 2026-06-04)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- **Spec traceability first.** Every story maps to one or more FRs from the spec's §17 traceability matrix.
- **Pure-helper-first.** The partition algorithm (FR-1) lands as a pure module in Story 1.2 (after Story 1.1 promotes `extractFromTo`) with full unit coverage *before* any UI lands. The component layer (Story 1.3) is a thin renderer over a tested contract.
- **No-backend, no-migration.** The feature consumes existing endpoints; no story modifies a backend file. Plan is frontend-only.
- **Fail-loud tests.** Unit tests assert explicit partition shape; component tests assert `data-testid` markers + DOM order; page-level vitest tests assert lifted-fetch behavior and race-gating; one Playwright E2E real-backend test asserts the panel renders against a seeded manual proposal.
- **Narrow stories.** Each story stands alone and is independently verifiable (lint, typecheck, the relevant test layer). The 4-story split lets each be a single small commit on the feature branch.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (pure partition helper + partition universe rule + drift handling) | Story 1.2 | The headline domain rule. Unit-tested via 8 cases (AC-1, AC-2, AC-3, AC-5, AC-6, D-9 search-space-drift drop, D-10 from===to anomaly, sort-stability). |
| FR-2 (`<FullParamSpacePanel>` renders three groups + empty state) | Story 1.3 | Component renderer + AC-1/AC-2/AC-5/AC-7 visual fidelity. Empty state requires BOTH `declaredParams` and `configDiff` to be empty per cycle-2 fix. |
| FR-3 (lift BOTH `useTemplate` AND `useStudy` gates) | Story 1.4 | Two-call refactor per D-13 (the cycle-3 F1 correctness fix). Page-level vitest tests cover the lifted cases (AC-3, AC-4, AC-10, AC-11). |
| FR-4 (race-aware conditional mount) | Story 1.4 | Panel waits for `parentTemplate.data` truthy AND, for study-backed proposals, `parentStudy.isPending === false`. Tested via the race-gating regression test (AC-11). |
| FR-5 (`extractFromTo` + `renderValue` promoted to `ui/src/lib/config-diff.ts`) | Story 1.1 | Shared utility extraction. `<ConfigDiffPanel>` re-imports; new panel imports. AC-9 locks the byte-identical behavior. |
| FR-6 (new glossary key `proposal.full_param_space`) | Story 1.3 | Landed alongside the panel that uses it (the existing AC-12 audience-language check in `glossary.test.ts` enforces user-visible-copy hygiene). |
| FR-7 (defensive empty states A–D) | Story 1.2 (helper edges) + Story 1.3 (panel-empty) + Story 1.4 (mount guards) | The pure helper covers A/C/D via partition algebra; the panel covers the full-partition-universe-empty case (AC-6 drift path takes precedence per cycle-2 fix); page-level mount covers B (template fetch failure → no mount). |
| FR-8 (prop contract) | Story 1.3 | `FullParamSpacePanelProps = { configDiff, declaredParams, searchSpaceParams? }`. tsc enforces; vitest exercises every prop combination. |

All 8 FRs covered. No FRs out-of-scope.

**Deferred work tracking:** Single-phase feature. Per D-8 and D-14 (cycle-3 F6, accepted), Caps 2 + 3 from the idea are explicitly NOT deferred via `phase*_idea.md` artifacts — they're closed-loop deferrals that reopen only on explicit operator feedback. No tracking files to create.

## 2) Delivery structure

**Single epic, four stories. No phases (single-phase feature per spec §3).**

### Story-level detail requirements

Each story below includes:
1. Outcome — observable behavior achieved
2. New files / Modified files — full paths verified against `ls` of the actual tree
3. UI element inventory (Stories 1.3 + 1.4) — every visual element being created
4. State dependency analysis (Story 1.4) — `useTemplate` / `useStudy` enabled-gate changes, race-gating prop chain
5. Tasks — specific, executable steps
6. Definition of Done — testable gates with cited test-layer references

This feature touches no backend files, so no API endpoints, Pydantic schemas, or key-interface signatures appear in stories. The relevant typed contracts (Pydantic shapes, generated TS types) are all stable upstream — `ProposalDetail`, `StudyDetail`, `QueryTemplateDetail` — and the spec's §2 Current state audit verified each.

### Conventions (project-specific)

- All new TS modules carry the SPDX header (`// SPDX-FileCopyrightText: 2026 soundminds.ai` + `// SPDX-License-Identifier: Apache-2.0`). The `reuse` pre-commit hook enforces this.
- Tests use `vitest` + `@testing-library/react`. Tooltips are rendered inside a `<TooltipProvider delayDuration={0}>` wrapper per the existing [`config-diff-panel.test.tsx:13-15`](../../../../ui/src/__tests__/components/proposals/config-diff-panel.test.tsx#L13-L15) pattern.
- Page-level tests follow the existing [`page.test.tsx:5-90`](../../../../ui/src/__tests__/app/proposals/[id]/page.test.tsx#L5-L90) pattern: MSW (`server.use(http.get(...))`) for HTTP mocks, `QueryClient({ retry: false })`, `vi.mock('next/navigation', ...)`, render `<ProposalDetailView proposalId="..." />` inside the providers.
- E2E follows the existing [`proposals.spec.ts`](../../../../ui/tests/e2e/proposals.spec.ts) pattern: real-backend, `seedTemplate` + `seedProposal` setup, `page` assertions only.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), [`CLAUDE.md`](../../../../CLAUDE.md), and the feature [`feature_spec.md`](feature_spec.md) before starting Story 1.1.
1. **Read scope**: verify story outcome + UI inventory + DoD.
2. **No backend**: skip backend test steps for this feature — no backend code is touched.
3. **Implement frontend** in the story order (1.1 → 1.2 → 1.3 → 1.4).
4. **Run vitest** (`cd ui && pnpm test --run <test-file>`) for each story's tests.
5. **Run lint + typecheck** (`cd ui && pnpm lint && pnpm typecheck`) per story.
6. **Run Playwright E2E** (Story 1.4 only — `cd ui && pnpm exec playwright test proposals.spec.ts`).
7. **Update docs** per §4 — only `state.md` at finalization.
8. **Attach evidence** in PR: commands run, files changed, vitest counts.
9. **After the final story (1.4)**, update `state.md` per §4.

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Full-parameter-space panel

> **Story ordering:** Stories are numbered in dependency order (1.1 → 1.2 → 1.3 → 1.4). Each story's exports are consumed by its successors. Story 1.1 (helper promotion) lands first because Story 1.2 (pure partition helper) imports from it.

### Story 1.1 — Promote `extractFromTo` + `renderValue` to a shared module

**Outcome:** The two helpers currently inside [`ui/src/components/proposals/config-diff-panel.tsx`](../../../../ui/src/components/proposals/config-diff-panel.tsx) (`renderValue` at lines 21-26, `extractFromTo` at lines 38-56) become named exports from a new shared module `ui/src/lib/config-diff.ts`. `<ConfigDiffPanel>` re-imports both from the new location with byte-identical behavior (AC-9). Both helpers travel together — extracting only one would leave the second-duplication risk for the new panel.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/config-diff.ts` | Exports `extractFromTo(raw: unknown): {from: unknown; to: unknown}` (the canonical `config_diff` normalizer — canonical `{from, to}` form, legacy 2-tuple `[before, after]` form, unknown-shape fallback) AND `renderValue(v: unknown): string` (the value→string renderer: `null` → `'—'`, primitives → `String(v)`, objects → `JSON.stringify(v)`). JSDocs unchanged from the in-component definitions. |
| `ui/src/__tests__/lib/config-diff.test.ts` | 7 cases — 3 covering `extractFromTo` (canonical, legacy 2-tuple, unknown shape) + 4 covering `renderValue` (null, string, number/boolean, JSON-stringified object). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/proposals/config-diff-panel.tsx` | (1) Remove the inline `renderValue` function (lines 21-26); (2) remove the inline `extractFromTo` function + its JSDoc (lines 28-56); (3) add `import { extractFromTo, renderValue } from '@/lib/config-diff';` to the import block (around line 16). The `<ConfigDiffPanel>` render code (lines 58-114) is unchanged — same call sites `renderValue(from)` / `renderValue(to)` at lines 103-104 and `extractFromTo(raw)` at line 99. |

**UI element inventory**

N/A — no visible UI change. Same `<ConfigDiffPanel>` rendering output. AC-9 locks byte-identical behavior verified by the existing test suite.

**Tasks**

1. Create `ui/src/lib/config-diff.ts` with SPDX header (`// SPDX-FileCopyrightText: 2026 soundminds.ai` + `// SPDX-License-Identifier: Apache-2.0`). Copy both function bodies verbatim from `config-diff-panel.tsx:21-26` (renderValue) and `:38-56` (extractFromTo). Preserve the JSDoc block on `extractFromTo`.
2. Edit `ui/src/components/proposals/config-diff-panel.tsx`:
   - Delete the local `renderValue` function (lines 21-26).
   - Delete the canonical-shape JSDoc comment block + the local `extractFromTo` function (lines 28-56).
   - Add `import { extractFromTo, renderValue } from '@/lib/config-diff';` after the existing import block (around line 16).
3. Create `ui/src/__tests__/lib/config-diff.test.ts` with 7 cases:
   - **extractFromTo Test 1 (canonical)**: `extractFromTo({from: 1.0, to: 1.98})` → `{from: 1.0, to: 1.98}`.
   - **extractFromTo Test 2 (legacy 2-tuple)**: `extractFromTo([50, 100])` → `{from: 50, to: 100}`.
   - **extractFromTo Test 3 (unknown shape)**: `extractFromTo({foo: 'bar'})` → `{from: null, to: {foo: 'bar'}}`. Also assert partial: `extractFromTo({to: 0.5})` → `{from: null, to: {to: 0.5}}`.
   - **renderValue Test 4 (null)**: `renderValue(null)` → `'—'`; `renderValue(undefined)` → `'—'`.
   - **renderValue Test 5 (string)**: `renderValue('foo')` → `'foo'`.
   - **renderValue Test 6 (number / boolean)**: `renderValue(42)` → `'42'`; `renderValue(true)` → `'true'`.
   - **renderValue Test 7 (object — JSON-stringified)**: `renderValue({a: 1})` → `'{"a":1}'`.

**Definition of Done (DoD)**
- `ui/src/lib/config-diff.ts` exists with `extractFromTo` AND `renderValue` exported; SPDX header present.
- `ui/src/components/proposals/config-diff-panel.tsx` no longer defines either helper locally and imports both from `@/lib/config-diff`.
- `ui/src/__tests__/lib/config-diff.test.ts` exists with 7 cases passing.
- **AC-9: `ui/src/__tests__/components/proposals/config-diff-panel.test.tsx` continues to pass byte-identically** (`cd ui && pnpm test --run src/__tests__/components/proposals/config-diff-panel.test.tsx` → 6 passed, no test source edits).
- `cd ui && pnpm test --run src/__tests__/lib/config-diff.test.ts` → 7 passed.
- `cd ui && pnpm lint && pnpm typecheck` → clean.

---

### Story 1.2 — Pure helper `partitionTemplateParams` + types

**Outcome:** A pure, unit-tested module at `ui/src/lib/proposal-param-space.ts` exposes `partitionTemplateParams({declaredParams, configDiff, searchSpaceParams})` returning `{tunedChanged, tunedUnchanged, untuned}` per FR-1's exact contract. The module is the spec's domain rule, isolated for testability. Depends on Story 1.1's `extractFromTo` export.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/proposal-param-space.ts` | Exports `partitionTemplateParams` (the pure helper), `ParamSpaceGroup` literal type, `TunedChangedRow` / `DeclaredRow` row types, `PartitionResult` shape. Imports `extractFromTo` from `ui/src/lib/config-diff.ts` (created in Story 1.1). |
| `ui/src/__tests__/lib/proposal-param-space.test.ts` | 8 unit tests per FR-1's listed cases (see DoD). No DOM, no MSW, no providers — pure data in / pure data out. |

**Modified files**

| File | Change |
|---|---|
| _(none)_ | Story 1.2 is purely additive. |

**UI element inventory (frontend story)**

N/A — Story 1.2 ships a pure helper, not UI. Listed here only because the helper output drives the panel; there are no rendered elements.

**Key interfaces**

```ts
// ui/src/lib/proposal-param-space.ts

import { extractFromTo } from './config-diff';

export type ParamSpaceGroup = 'tuned_changed' | 'tuned_unchanged' | 'untuned';

export interface TunedChangedRow {
  name: string;
  type: string;   // type-tag from declared_params, or '(unknown)' if drift
  from: unknown;
  to: unknown;
}

export interface DeclaredRow {
  name: string;
  type: string;
}

export interface PartitionResult {
  tunedChanged: TunedChangedRow[];
  tunedUnchanged: DeclaredRow[];
  untuned: DeclaredRow[];
}

export interface PartitionInput {
  declaredParams: Record<string, string>;
  configDiff: Record<string, unknown>;
  searchSpaceParams?: Record<string, unknown> | undefined;
}

export function partitionTemplateParams(input: PartitionInput): PartitionResult;
```

**Tasks**

1. Create `ui/src/lib/proposal-param-space.ts` with SPDX header + the type exports above.
2. Implement `partitionTemplateParams` with this algorithm (lock the partition universe to `declaredParams ∪ configDiff` per spec D-9). **TypeScript note**: `tsconfig.json` sets `noUncheckedIndexedAccess: true`, so `declaredParams[key]` returns `string | undefined`, but `DeclaredRow.type` is `string` (non-optional). Iterate via `Object.entries(declaredParams)` (which yields type-narrowed `[string, string]` tuples) rather than `Object.keys()` + indexed access — this avoids the build error without `!` non-null assertions.
   - Initialize `tunedChanged: TunedChangedRow[] = []`, `tunedUnchanged: DeclaredRow[] = []`, `untuned: DeclaredRow[] = []`.
   - Iterate `Object.entries(configDiff)`:
     - For each `[key, raw]`, resolve `type = declaredParams[key] ?? '(unknown)'` (the `??` handles the drift case AC-6 + satisfies `noUncheckedIndexedAccess`), resolve `{from, to} = extractFromTo(raw)`, push `{name: key, type, from, to}` to `tunedChanged`. (A `configDiff` key with `from === to` still classifies here per D-10.)
     - Track these keys in a `Set<string>` (`const seen = new Set(Object.keys(configDiff));`) for the next pass's skip-check.
   - Iterate `Object.entries(declaredParams)` (type-narrowed to `[string, string]` — no indexed-access narrowing issue):
     - If `seen.has(key)`, skip (already in `tunedChanged`).
     - Else if `searchSpaceParams !== undefined && key in searchSpaceParams`, push `{name: key, type}` to `tunedUnchanged`.
     - Else push `{name: key, type}` to `untuned`.
   - **Do NOT** iterate `searchSpaceParams` — keys only in `searchSpaceParams` (template-evolution drift) are silently dropped per D-9.
   - Sort each output array alphabetically by `name` (`arr.sort((a, b) => a.name.localeCompare(b.name))`).
3. Write the 8 unit tests in `ui/src/__tests__/lib/proposal-param-space.test.ts`:
   - Test 1 (AC-1 fixture): three non-empty groups, alphabetical within each.
   - Test 2 (AC-5 fixture): empty `configDiff`, populated `searchSpaceParams` and `declaredParams` → only `tunedUnchanged` + `untuned` populated; **assert alphabetical order `bar` then `foo` per the cycle-3 F3 correction**.
   - Test 3 (AC-3 / manual proposal): `searchSpaceParams === undefined` → `tunedUnchanged` empty; every non-`configDiff` declared key goes to `untuned`.
   - Test 4 (AC-6 / `configDiff` drift): `declaredParams = {}` + `configDiff = { removed_param: { from: 1, to: 2 } }` → `tunedChanged` contains `{name: 'removed_param', type: '(unknown)', from: 1, to: 2}`.
   - Test 5 (D-9 / `searchSpace` drift): `searchSpaceParams = { phantom: {...} }`, `declaredParams = { foo: 'int' }`, `configDiff = {}` → `phantom` silently dropped, `foo` in `untuned` (not in `searchSpaceParams`'s sense — but wait, `foo` is not in `searchSpaceParams` either, so `untuned`). Assert `phantom` does NOT appear in any of the three arrays.
   - Test 6 (AC-2 / legacy 2-tuple): `configDiff = { boost: [1.0, 1.5] }` → `tunedChanged` row has `from: 1.0, to: 1.5` (normalized via `extractFromTo`).
   - Test 7 (D-10 / `from === to` anomaly): `configDiff = { boost: { from: 1, to: 1 } }` → row still in `tunedChanged` (membership-based classification).
   - Test 8 (sort stability): three keys per group in scrambled input → outputs alphabetically ordered.

**Definition of Done (DoD)**
- `ui/src/lib/proposal-param-space.ts` exists with the exports above; SPDX header present.
- `ui/src/__tests__/lib/proposal-param-space.test.ts` exists with 8 tests passing.
- `cd ui && pnpm test --run src/__tests__/lib/proposal-param-space.test.ts` → 8 passed.
- `cd ui && pnpm lint && pnpm typecheck` → clean.
- No backend tests touched; story is purely TS-side.

---

### Story 1.3 — `<FullParamSpacePanel>` component + new glossary key

**Outcome:** A new component `<FullParamSpacePanel>` is implemented and ready to mount on `/proposals/[id]` (the actual page-level mount + integration is Story 1.4's responsibility). The component renders the three-state partition. The new glossary key `proposal.full_param_space` lands alongside it. Component has full vitest coverage against AC-1, AC-2, AC-5, AC-6, AC-7, AC-8.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/full-param-space-panel.tsx` | The new component. Consumes `partitionTemplateParams` (Story 1.1) + renders three labeled groups inside a `<Card>` per FR-2. Wraps an `<InfoTooltip glossaryKey="proposal.full_param_space" />` next to the card title per FR-6. |
| `ui/src/__tests__/components/proposals/full-param-space-panel.test.tsx` | Component tests covering AC-1, AC-2 (legacy 2-tuple round-trip via the panel), AC-5 (empty `configDiff`), AC-6 (drift key), AC-7 (visual states), AC-8 (tooltip resolves). Wraps tests in `<TooltipProvider delayDuration={0}>` per the existing `config-diff-panel.test.tsx:13-15` pattern. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | Add new entry `proposal.full_param_space` inside the "Phase 2 — Proposals" block (around line 651, just after `proposal.followup_declared_params_diff`). Entry shape: `{ short: 'Every parameter the template declares — grouped by whether the study tuned it and whether tuning changed the value.', ariaLabel: 'More information about the full parameter space' }`. |

**UI element inventory**

| Element | Type | Purpose | Data source |
|---|---|---|---|
| Card header "Full parameter space" + `<InfoTooltip>` | `<Card>` + title text + tooltip | Panel identification | Static |
| `param-space-group-tuned_changed` group header | `<h3>` (or visually-equivalent semantic element) — text label e.g. "Tuned (changed by this proposal) — N parameters" | First group label | `partition.tunedChanged.length` |
| `param-space-row-tuned_changed-<name>` per row | `<div>` / table row — param name (monospace), type (subtle), `from → to` columns matching `<ConfigDiffPanel>`'s value treatment | First group row | `partition.tunedChanged` entries |
| `param-space-group-tuned_unchanged` group header | `<h3>` — "Tuned (unchanged) — N parameters" | Second group label | `partition.tunedUnchanged.length` |
| `param-space-row-tuned_unchanged-<name>` per row | `<div>` — param name (monospace), type (subtle), "(no change)" annotation in muted text | Second group row | `partition.tunedUnchanged` entries |
| `param-space-group-untuned` group header | `<h3>` — "Not in search space — N parameters" | Third group label | `partition.untuned.length` |
| `param-space-row-untuned-<name>` per row | `<div>` — param name (monospace), type (subtle), `text-gray-700 italic` styling matching `<DeclaredParamsColumn>`'s non-shared treatment ([`suggested-followups-panel.tsx:377`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L377)) | Third group row | `partition.untuned` entries |
| `param-space-empty` empty state | `<p>` — "Template declares no parameters." | Defensive — `declaredParams.length === 0 && configDiff.length === 0` | Static |

All group headers and rows carry the `data-testid` markers shown above per FR-2.

**Key interfaces**

```ts
// ui/src/components/proposals/full-param-space-panel.tsx

import type { PartitionInput } from '@/lib/proposal-param-space';

export interface FullParamSpacePanelProps {
  configDiff: Record<string, unknown>;
  declaredParams: Record<string, string>;
  searchSpaceParams?: Record<string, unknown> | undefined;
}

export function FullParamSpacePanel(props: FullParamSpacePanelProps): React.ReactElement;
```

The prop contract matches the spec's FR-8 exactly. Internal: the component calls `partitionTemplateParams(props)` once per render (cheap — `O(declaredParams.length)` — no memoization needed at the panel level), then renders three groups via an exhaustive `switch (group)` with a `never`-typed default per D-12.

**Analogous markup patterns**

Pattern A — `<Card>` + header + `<InfoTooltip>` for the panel shell (from [`config-diff-panel.tsx:60-65`](../../../../ui/src/components/proposals/config-diff-panel.tsx#L60-L65) and [`suggested-followups-panel.tsx:108-115`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L108-L115)):

```tsx
{/* From config-diff-panel.tsx:60-65 (the InfoTooltip pattern is from suggested-followups-panel.tsx:111-114) */}
<Card>
  <CardHeader>
    <CardTitle className="flex items-center gap-1 text-base">
      Full parameter space
      <InfoTooltip glossaryKey="proposal.full_param_space" />
    </CardTitle>
  </CardHeader>
  <CardContent>
    {/* Three groups rendered here */}
  </CardContent>
</Card>
```

Pattern B — Per-row monospace name + type rendering (from [`suggested-followups-panel.tsx:374-382`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L374-L382)):

```tsx
{/* Adapted from <DeclaredParamsColumn> at suggested-followups-panel.tsx:370-384 */}
<ul className="mt-1 space-y-0.5">
  {rows.map(({ name, type }) => (
    <li
      key={name}
      data-testid={`param-space-row-${group}-${name}`}
      className={
        group === 'untuned' ? 'text-gray-700 italic' : 'text-gray-700'
      }
    >
      <code className="text-xs">{name}</code>: {type}
      {group === 'tuned_unchanged' && (
        <span className="ml-2 text-xs text-muted-foreground">(no change)</span>
      )}
    </li>
  ))}
</ul>
```

Pattern C — `tunedChanged` rows render the from→to delta in the same visual treatment as `<ConfigDiffPanel>`'s `From`/`To` columns (from [`config-diff-panel.tsx:98-107`](../../../../ui/src/components/proposals/config-diff-panel.tsx#L98-L107)):

```tsx
{/* tunedChanged rows — preserves <ConfigDiffPanel>'s visual treatment */}
{partition.tunedChanged.map((row) => (
  <div
    key={row.name}
    data-testid={`param-space-row-tuned_changed-${row.name}`}
    className="font-mono text-xs flex items-center gap-2"
  >
    <code>{row.name}</code>
    <span className="text-muted-foreground">{row.type}</span>
    <span>{renderValue(row.from)}</span>
    <span>→</span>
    <span>{renderValue(row.to)}</span>
  </div>
))}
```

Where `renderValue` is imported from `@/lib/config-diff` (Story 1.1 promotes it alongside `extractFromTo`).

**Layout and structure**

- Single `<Card>` containing the title (with adjacent `<InfoTooltip>`) and `<CardContent>` with three sequential group sections.
- Each group: `<h3>` (or visually-equivalent) for the label + a `<ul>` or `<div>` container for the rows. Groups with zero rows are omitted entirely (no "0 parameters" placeholder).
- No tabs, no toggles, no `<details>`/`<summary>` — everything visible inline.
- Responsive: same `max-w-7xl` container the page already uses; rows wrap naturally inside `<CardContent>`.

**Visual consistency**

| New UI element | CSS class / pattern source |
|---|---|
| Card shell | `<Card>` + `<CardHeader>` + `<CardTitle>` + `<CardContent>` — same as `<ConfigDiffPanel>` |
| Title + `<InfoTooltip>` | `flex items-center gap-1 text-base` — same as `<ConfigDiffPanel>`'s `<CardTitle>` |
| Group header | `<h3 className="text-sm font-semibold text-gray-900 mt-3 first:mt-0">` (semantic + sized one notch below `<CardTitle>`'s `text-base`) |
| `tunedChanged` row | `font-mono text-xs flex items-center gap-2` (from `<ConfigDiffPanel>`'s table cells at lines 102-104) |
| `tunedUnchanged` row | `text-gray-700` + a muted "(no change)" suffix (mirrors `<DeclaredParamsColumn>`'s non-shared treatment) |
| `untuned` row | `text-gray-700 italic` (italic added to reinforce "absent" framing — distinct from `tunedUnchanged`'s plain text) |
| Empty state | `<p className="py-6 text-center text-sm text-muted-foreground" data-testid="param-space-empty">` — same as `<ConfigDiffPanel>`'s empty state at lines 67-70 |

**Component composition**

- `<FullParamSpacePanel>` is a single component file. No child component extraction (the per-group rendering is 8-12 lines of JSX each; extracting a `<ParamGroup>` child would be over-engineering for this surface).
- The exhaustive `switch (group)` happens inside the component's render — see "Key interfaces" above.

**Interaction behavior**

| User action | Frontend behavior | API call |
|---|---|---|
| Hover/keyboard-focus the info icon next to "Full parameter space" | Radix Tooltip shows the FR-6 short copy | none (purely client) |
| (No other interactions) | Panel is passive — no clicks, no form fields | none |

**Tooltips and contextual help**

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment target | JSX snippet |
|---|---|---|---|---|---|---|
| Card title "Full parameter space" | `"Every parameter the template declares — grouped by whether the study tuned it and whether tuning changed the value."` | hover / focus | adjacent (inline-flex) to title | `proposal.full_param_space` | n/a — this is a **new** glossary key; no backend allowlist to mirror (the key is UI-only, like `proposal.suggested_followups`). No `// Source-of-truth: ...` comment required above the glossary entry. | `<InfoTooltip glossaryKey="proposal.full_param_space" />` immediately after the title text inside `<CardTitle>` |

**Enumerated value contract verification**

This story renders no `<select>` / filter dropdown / status badge whose value is sent to the backend. The `ParamSpaceGroup` type `'tuned_changed' | 'tuned_unchanged' | 'untuned'` is internal-only — used in `data-testid` markers and rendering branches, never serialized to the wire. Per the spec's §8.4 it is exempt from the CLAUDE.md "Enumerated Value Contract Discipline" rule, and per D-12 rows do NOT carry an on-row `state` discriminator (group identity comes from the containing array). No source-of-truth comment is required.

**Tasks**

1. Create `ui/src/components/proposals/full-param-space-panel.tsx` with SPDX header. Implement per the "Key interfaces" + "Analogous markup patterns" above. Import `partitionTemplateParams`, `ParamSpaceGroup`, the row types from `@/lib/proposal-param-space` (Story 1.2) and `renderValue` from `@/lib/config-diff` (Story 1.1). Use `<InfoTooltip glossaryKey="proposal.full_param_space" />`.
2. Edit `ui/src/lib/glossary.ts`: insert the new key inside the "Phase 2 — Proposals" block (around line 651, right after `proposal.followup_declared_params_diff`). Mirror the existing entries' two-field shape (`short`, `ariaLabel`).
3. Create `ui/src/__tests__/components/proposals/full-param-space-panel.test.tsx` with the test cases below. Each test wraps `<FullParamSpacePanel>` in a `<TooltipProvider delayDuration={0}>` (matching the `config-diff-panel.test.tsx:13-15` pattern).
   - Test 1 (AC-1): renders three groups with correct counts + alphabetical row order. Assert all 7 `data-testid` markers from the UI inventory.
   - Test 2 (AC-2): renders legacy 2-tuple `configDiff = { boost: [1, 1.5] }` correctly — `from` cell shows "1", `to` cell shows "1.5".
   - Test 3 (AC-5): empty `configDiff` + populated `searchSpaceParams` → `tunedChanged` group not rendered (`screen.queryByTestId('param-space-group-tuned_changed')` returns null); `tunedUnchanged` shows alphabetical `bar` then `foo`.
   - Test 4 (AC-6): `configDiff` drift key (in `configDiff`, not in `declaredParams`) renders under `tunedChanged` with type `(unknown)`. Empty `declaredParams` does NOT trigger the empty state when `configDiff` has keys.
   - Test 5 (AC-7): visual states are distinguishable — `tunedChanged` row has the from→to columns; `tunedUnchanged` row contains "(no change)" text; `untuned` row carries the `italic` class.
   - Test 6 (AC-8): tooltip resolves via real hover interaction. Assert the trigger is in the DOM (`screen.getByTestId('tooltip-trigger-proposal.full_param_space')`). Then perform a real hover with `@testing-library/user-event` (the existing test setup in `config-diff-panel.test.tsx` uses `vitest`'s `userEvent` — import from `@testing-library/user-event`): `await userEvent.hover(screen.getByTestId('tooltip-trigger-proposal.full_param_space'))`. Then `await screen.findByTestId('tooltip-body-proposal.full_param_space')` (use `findBy` because Radix Tooltip bodies are not in the DOM until triggered) and assert its text content matches the FR-6 short copy verbatim. The `<TooltipProvider delayDuration={0}>` wrapper from the existing pattern eliminates the 700ms default delay so the test is deterministic.
   - Test 7 (full-empty defensive): both `declaredParams = {}` and `configDiff = {}` → `data-testid="param-space-empty"` is rendered; no group headers present.
4. Verify the existing `glossary.test.ts` AC-12 audience-language check passes (the new entry uses no backend file paths, no symbol names, no implementation jargon).

**Definition of Done (DoD)**
- `ui/src/components/proposals/full-param-space-panel.tsx` exists; SPDX header present; renders all UI-inventory elements.
- `ui/src/lib/glossary.ts` has the new entry; `cd ui && pnpm test --run src/__tests__/lib/glossary.test.ts` passes (the existing AC-12 audience-language check runs against the new entry).
- `ui/src/__tests__/components/proposals/full-param-space-panel.test.tsx` exists with 7 tests passing.
- `cd ui && pnpm test --run src/__tests__/components/proposals/full-param-space-panel.test.tsx` → 7 passed.
- `cd ui && pnpm lint && pnpm typecheck` → clean.
- Panel is NOT yet mounted on `/proposals/[id]` — that's Story 1.4's job.

---

### Story 1.4 — Page-level integration: lifted fetches + race-aware mount + page tests + E2E

**Outcome:** `<FullParamSpacePanel>` mounts on `/proposals/[id]` directly below `<ConfigDiffPanel>`. Both `useTemplate(...)` and `useStudy(...)` are lifted to fire for every loaded proposal (FR-3 + D-13). The mount is gated per FR-4's race-aware logic. Page-level vitest tests cover the lifted fetches, the race gating, and the template-fetch-failure case. A Playwright E2E test exercises the panel against a seeded manual proposal.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | Story 1.4 modifies existing files. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/proposals/[id]/page.tsx` | (1) Change line 183 input to `useTemplate(...)` from `parentStudy.data?.template_id` to **`proposal?.template.id`** (null-safe via `?.` — `proposal` is `proposalQ.data ?? null` per page.tsx:165, so the unguarded `.template.id` would throw during the initial async-loading render; the hook's internal `enabled: Boolean(id)` short-circuits when the optional access returns undefined per [`query-templates.ts:58`](../../../../ui/src/lib/api/query-templates.ts#L58)) (FR-3 first lift); (2) Change line 177 `useStudy(...)`'s `enabled` from `parentStudyId !== null && hasActionableFollowup` to `parentStudyId !== null` (FR-3 second lift, D-13); (3) Mount `<FullParamSpacePanel>` directly below `<ConfigDiffPanel>` at line 319 with the race-aware gating per FR-4; (4) Import `FullParamSpacePanel` at the top. |
| `ui/src/__tests__/app/proposals/[id]/page.test.tsx` | Add **6 new test cases** per the spec's §14 page-level test plan (see Tasks below — Test 1 happy path / Test 2 manual / Test 3 template-404 / Test 4 race-gating dual-deferred / Test 5 cycle-3 F1 regression guard / Test 6 FR-7 edge case A study-error). The existing 11 tests stay byte-identical. |
| `ui/tests/e2e/proposals.spec.ts` | Add 1 new test asserting `<FullParamSpacePanel>` renders against a seeded manual proposal. |

**UI element inventory**

The story does not introduce new UI primitives — it mounts the existing `<FullParamSpacePanel>` (Story 1.3) into the existing page. The only page-level change is the mount itself and the gating expression around it.

| Element | Type | Insertion point | Mount condition |
|---|---|---|---|
| `<FullParamSpacePanel>` | mounted child component | `ui/src/app/proposals/[id]/page.tsx` directly after line 319 (`<ConfigDiffPanel diff={proposal.config_diff} />`) and before the metric-delta `<Card>` at line 320-345 | (`parentTemplateQuery.data`) AND, when `proposal.study_id !== null`, (`parentStudy.isPending === false`) |

**State dependency analysis (refactor)**

State variable changes — both are at file [`ui/src/app/proposals/[id]/page.tsx`](../../../../ui/src/app/proposals/[id]/page.tsx):

```
Modified: useStudy(...) `enabled` clause at line 176-178
  Current: enabled: parentStudyId !== null && hasActionableFollowup
  New:     enabled: parentStudyId !== null
  Rationale: D-13 — search-space-data needs to be loaded for the new panel too.
  Affected consumers (verified at line 365-378):
    - <SuggestedFollowupsPanel parentSearchSpace={...} parentTemplate={...} ...> — receives parentStudy.data?.search_space and parentTemplate
    - The CreateStudyModal's prefillValues useMemo at lines 185-268 — branches on parentStudy.data presence
    - The new <FullParamSpacePanel> (FR-4 mount-gating) — uses parentStudy.isPending + parentStudy.data?.search_space
  Verification: lifting the gate makes parentStudy fire for ALL study-backed proposals. For previously-disabled cases (text-only / empty digest), parentStudy.data now resolves, but the consumers above all branch defensively (the SuggestedFollowupsPanel uses `parentSearchSpace ?? undefined`; prefillValues exits early if `parentStudy.data` is undefined). No regression risk — the new value is "data present where before it was undefined," which is strictly more information.
```

```
Modified: useTemplate(...) input at line 183
  Current: useTemplate(parentStudy.data?.template_id)
  New:     useTemplate(proposal.template.id)
  Rationale: D-1 — the proposal's own template_id is the authoritative source; lifting from the
             study fetch removes the study-fetch dependency for the template fetch.
  Equivalence: For study-backed proposals, proposal.template.id === parentStudy.data?.template_id
               by construction in backend/workers/digest.py:488-494 — both resolve to the same template
               row. For manual proposals (study_id === null), the old expression evaluated to undefined
               (no fetch); the new expression evaluates to a real id (fetch fires).
  Affected consumers (verified at line 372-378):
    - <SuggestedFollowupsPanel parentTemplate={...} ...> — receives parentTemplateQuery.data
  Verification: D-11 (cycle-1 F8 rejection) — parentTemplate is structurally consumed only by
                <SwapTemplateCard> inside <SuggestedFollowupsPanel>. For non-swap-template followups
                (and for manual proposals which never have any followups), the prop is ignored. The
                lifted fetch covers the same swap-template case as before plus three new cases that
                are structurally indifferent to the prop. No regression risk.
```

New mount-gating expression (replaces the lone `<ConfigDiffPanel diff={proposal.config_diff} />` insertion):

```tsx
<ConfigDiffPanel diff={proposal.config_diff} />
{parentTemplateQuery.data &&
  (proposal.study_id === null || !parentStudy.isPending) && (
    <FullParamSpacePanel
      configDiff={proposal.config_diff}
      declaredParams={parentTemplateQuery.data.declared_params}
      searchSpaceParams={
        (parentStudy.data?.search_space as { params?: Record<string, unknown> } | undefined)?.params
      }
    />
  )}
```

The `parentStudy.isPending` check satisfies FR-4's race-aware gating for study-backed proposals; for manual proposals (`study_id === null`), the second clause short-circuits to true and only the template gate applies.

**Handler function patterns**

No new event handlers, no new mutations, no new state. Story 1.4 is pure plumbing — two input changes + one conditional mount.

**Information architecture placement**

Per spec §11, the new panel sits between `<ConfigDiffPanel>` (current line 319) and the metric-delta `<Card>` (lines 320-345). The full mount order on `/proposals/[id]` becomes:

```
<ProposalHeader>
<ConfigDiffPanel>
<FullParamSpacePanel>      ← NEW, this story
<Card>{metric-delta}</Card>
<PrPanel> + <RejectDialog>
<SuggestedFollowupsPanel>  ← when present
```

No tab/section/navigation changes. No new route. No sidebar entry.

**Tasks**

1. Edit `ui/src/app/proposals/[id]/page.tsx`:
   - Add `import { FullParamSpacePanel } from '@/components/proposals/full-param-space-panel';` to the import block.
   - Change line 177 `enabled: parentStudyId !== null && hasActionableFollowup` → `enabled: parentStudyId !== null`.
   - Change line 183 `useTemplate(parentStudy.data?.template_id)` → `useTemplate(proposal?.template.id)`. **The `?.` is required** — `proposal` is `proposalQ.data ?? null` per page.tsx:165, so the unguarded `.template.id` would throw a TypeError during the initial async-loading render. The hook short-circuits via `enabled: Boolean(id)` when the optional chain yields `undefined`.
   - Insert the mount-gating JSX from "State dependency analysis" above immediately after line 319 (`<ConfigDiffPanel diff={proposal.config_diff} />`).
2. Edit `ui/src/__tests__/app/proposals/[id]/page.test.tsx`. The existing helper `proposalDetailPayload` (lines 45-78) is reused — the new tests just override fields. Add a fourth describe block: `describe('Proposal detail page — Story 1.4 (full-param-space mount + lifted fetches)', () => { ... })` with **5 tests** (cycle-1 F2 fix — the cycle-3 F1 regression guard is its own dedicated test, not "bundled into Test 1"):
   - **Test 1 (AC-1 / happy path, swap_template digest)**: Seed a study-backed proposal with a `swap_template` followup (already actionable in current code) + a `useStudy` mock returning `search_space = { params: { boost: {...} } }` + a `useTemplate` mock returning `declared_params = { boost: 'float', other: 'int' }`. Assert `<FullParamSpacePanel>` mounts; `param-space-row-tuned_changed-boost` is present (boost is in config_diff); `param-space-row-untuned-other` is present (other is in declared_params but not in search_space). This test exercises the previously-working code path (swap_template is already actionable, so `useStudy` was firing before this PR too). It is NOT the regression guard — see Test 5.
   - **Test 2 (AC-3 / manual proposal)**: Seed `proposal.study_id = null` (manual proposal). Mock `useTemplate(proposal?.template.id)` to resolve immediately. `useStudy` is never called (its `enabled` gate short-circuits). Assert `<FullParamSpacePanel>` mounts as soon as the template resolves; `tunedUnchanged` group is absent (zero rows, no header); declared params NOT in `config_diff` appear under `untuned`.
   - **Test 3 (AC-4 / template 404)**: Mock `GET /api/v1/query-templates/<id>` to return 404 with `{detail: {error_code: 'TEMPLATE_NOT_FOUND', message: '...', retryable: false}}`. Assert `<FullParamSpacePanel>` is NOT in the DOM, but `<ConfigDiffPanel>`, the metric-delta card, and `<PrPanel>` continue to render.
   - **Test 4 (AC-11 / race-aware gating regression — D-13)**: Use a **dual deferred-resolver pattern** for `useTemplate` AND `useStudy` so the test deterministically controls the order of resolutions (cycle-3 F5: a single deferred study isn't sufficient — if the template is *also* still pending when we assert "panel absent," the test passes vacuously because BOTH gates are unmet, not because of the race-specific guard). Concretely:
     ```ts
     let resolveTemplate!: (resp: Response) => void;
     let resolveStudy!: (resp: Response) => void;
     const templatePromise = new Promise<Response>((r) => { resolveTemplate = r; });
     const studyPromise = new Promise<Response>((r) => { resolveStudy = r; });
     server.use(
       http.get(`${API_BASE}/api/v1/proposals/p1`, () => HttpResponse.json(proposalDetailPayload({ study_id: 's1' }))),
       http.get(`${API_BASE}/api/v1/query-templates/t1`, async () => templatePromise),
       http.get(`${API_BASE}/api/v1/studies/s1`, async () => studyPromise),
     );
     await renderPage('p1');
     // Both fetches pending. Proposal loaded (ConfigDiffPanel renders), neither downstream fetch settled.
     await waitFor(() => expect(screen.getByTestId('config-diff-table')).toBeInTheDocument());

     // === Step 1: resolve TEMPLATE only — study still pending. This is the race-specific state. ===
     resolveTemplate(HttpResponse.json(templateDetail({ declared_params: { foo: 'float' } })));
     // Wait until the template query is in 'success' state in the TanStack cache (not just the proposal).
     // Use the `qc` accessor from the test setup: `qc.getQueryState(['query-templates', 't1'])?.status === 'success'`.
     // Alternative: assert via a parentTemplate-dependent UI signal — e.g. wait briefly then verify the panel is still absent.
     await waitFor(() => expect(qc.getQueryState(['query-templates', 't1'])?.status).toBe('success'));
     // NOW assert the panel is absent — this is the race-specific gate (template resolved, study pending).
     expect(screen.queryByTestId('param-space-group-tuned_changed')).toBeNull();
     expect(screen.queryByTestId('param-space-group-untuned')).toBeNull();
     expect(screen.queryByTestId('param-space-empty')).toBeNull();

     // === Step 2: resolve STUDY — panel must now mount with correct classification. ===
     resolveStudy(HttpResponse.json(studyDetail({ search_space: { params: { foo: {min:0,max:1} } } })));
     await waitFor(() => expect(screen.getByTestId('param-space-row-tuned_unchanged-foo')).toBeInTheDocument());
     ```
     The dual-deferred pattern guarantees the assertion at step 1 exercises the exact race FR-4's gating defends against (template ✓, study still pending). The `qc.getQueryState(...)` check confirms TanStack moved the template query to 'success' before the test asserts — without that check, the panel-absent assertion could pass vacuously because the template was also still pending (cycle-3 F5).

   - **Test 6 (FR-7 edge case A — source study fetch error)**: Seed a study-backed proposal (`proposal.study_id = 's3'`). Mock `GET /api/v1/studies/s3` to return 404 with `{detail: {error_code: 'STUDY_NOT_FOUND', message: '...', retryable: false}}`. Mock `useTemplate` to return `declared_params = { foo: 'float', bar: 'int' }` (both NOT in `config_diff`). The `useStudy` query settles with an error → `parentStudy.isPending === false` AND `parentStudy.data === undefined`. Per FR-4's race-gating, the panel MUST mount (the `!parentStudy.isPending` gate is satisfied by the error settlement). Per FR-7 edge case A, `tunedUnchanged` is empty (no `searchSpaceParams`); `untuned` shows `foo` and `bar`. Assert `screen.getByTestId('param-space-row-untuned-foo')` and `screen.getByTestId('param-space-row-untuned-bar')` are present, and `screen.queryByTestId('param-space-group-tuned_unchanged')` is null. This is the dedicated regression guard for FR-7 edge case A (cycle-3 F6).
   - **Test 5 (FR-3 cycle-3 F1 regression guard — dedicated test, NOT bundled)**: Seed a study-backed proposal (`proposal.study_id = 's2'`) with a **digest that has zero actionable followups** — either `digest = null`, `digest.suggested_followups = []`, or `digest.suggested_followups = [{kind: 'text', ...}]` (text-only). Mock `useStudy` to return `search_space = { params: { foo: {min:0,max:1} } }` (non-empty), `useTemplate` to return `declared_params = { foo: 'float', bar: 'int' }` (`foo` is in search_space, `bar` is not), `config_diff = {}` (empty — no tuned values). Wait for BOTH fetches to settle. Assert `param-space-row-tuned_unchanged-foo` is in the DOM (NOT `param-space-row-untuned-foo`) and `param-space-row-untuned-bar` is in the DOM. **If the `useStudy` lift (FR-3 second clause) were missed, `useStudy` would never fire for this proposal because the digest has no actionable followups; `parentStudy.data` would stay undefined; `foo` would mis-classify as `untuned`; the assertion `screen.getByTestId('param-space-row-tuned_unchanged-foo')` would fail.** This is the dedicated regression guard for the cycle-3 F1 correctness bug — the one the cycle-1 F2 review correctly flagged as missing.
3. Edit `ui/tests/e2e/proposals.spec.ts`. Add a new test under the existing `test.describe('/proposals', () => { ... })`:
   - **E2E test**: `it('detail page renders the full-parameter-space panel for a manual proposal', async ({ page }) => { ... })`. Seed via `seedManualProposal()` (existing local helper at [`proposals.spec.ts:21-36`](../../../../ui/tests/e2e/proposals.spec.ts#L21-L36)). Navigate to `/proposals/<id>`. Assert `page.getByTestId('param-space-group-tuned_changed')` is visible (the seeded manual proposal has `config_diff` with title.boost + description.boost — both render under `tunedChanged` even with `(unknown)` type because the seeded template's `declared_params` is just `{ boost: 'float' }`, not `{ 'title.boost': 'float', 'description.boost': 'float' }`). Assert `page.getByTestId('param-space-group-untuned')` is visible (the seeded template's `boost` is NOT in `config_diff`, so it falls into `untuned`). Use `{ timeout: 5_000 }` on the `expect(...).toBeVisible()` calls.

**Definition of Done (DoD)**
- `ui/src/app/proposals/[id]/page.tsx` line 177 + line 183 + the mount-gating insertion all match the spec.
- All 6 new page-level vitest tests pass (Test 1 happy path + Test 2 manual + Test 3 template-404 + Test 4 race-gating dual-deferred + Test 5 cycle-3 F1 regression guard + Test 6 FR-7 edge case A study-error).
- The Playwright E2E test (1 new case) passes against the real backend.
- `cd ui && pnpm test --run src/__tests__/app/proposals/[id]/page.test.tsx` → 17 passed (11 existing + 6 new).
- `cd ui && pnpm exec playwright test tests/e2e/proposals.spec.ts` → 5 passed (4 existing + 1 new).
- `cd ui && pnpm lint && pnpm typecheck` → clean.
- `cd ui && pnpm build` → succeeds (catches any SSR / Next.js build issues with the new mount).

---

## UI Guidance (plan-level — REQUIRED for frontend-facing work)

### Reference: current component structure

**`ui/src/app/proposals/[id]/page.tsx`** — 402 lines total. Sections (line ranges):

- **Lines 1-33**: SPDX, imports, type aliases.
- **Lines 36-65**: `ACTIONABLE_FOLLOWUP_KINDS` lookup + `resolveTemplateIdForPrefill` exhaustive helper.
- **Lines 67-81**: `RouteProps` + `MetricDeltaShape` + `parseMetricDelta` helper.
- **Lines 83-158**: `ProposalDetailView` — open-PR mutation + polling + safety-cap setup. Includes `useProposal` at lines 106-114, the `proposalStatus` / `proposalPrOpenError` destructure at 118-119, `effectivePollingFlag` at 126-127, `fireOpenPR` at 133-147, unmount cleanup at 151-158.
- **Lines 160-184**: Followup orchestration setup — `runFollowupIndex` state, `followups` derivation, `hasActionableFollowup`, `useStudy(parentStudyId, { enabled: ... })` at 176-178, `useTemplate(parentStudy.data?.template_id)` at 183. **THIS IS THE BLOCK STORY 1.4 EDITS.**
- **Lines 185-268**: `prefillValues` useMemo — pure derivation of CreateStudyModal seed values.
- **Lines 270-287**: `?action=open_pr` auto-trigger effect.
- **Lines 288-392**: JSX — `<main>` wrapping `<DetailPageShell>` with the panel sequence (lines 318-379). **STORY 1.4 INSERTS `<FullParamSpacePanel>` AT LINE 319.**
- **Lines 394-401**: `ProposalDetailPage` default export with `<Suspense>` wrapper.

**`ui/src/components/proposals/config-diff-panel.tsx`** — 114 lines. Sections:

- **Lines 1-15**: SPDX, imports.
- **Lines 17-19**: `ConfigDiffPanelProps` interface.
- **Lines 21-26**: `renderValue` helper (4 lines) — **Story 1.1 promotes this**.
- **Lines 28-36**: JSDoc for `extractFromTo`.
- **Lines 38-56**: `extractFromTo` helper — **Story 1.1 promotes this**.
- **Lines 58-114**: `<ConfigDiffPanel>` component.

**`ui/src/components/proposals/suggested-followups-panel.tsx`** — 388 lines. Reference points for typography:
- Lines 67-72: `KIND_LABELS` (analogous to a future-proof per-group label map, though we keep ours inline).
- Lines 90-95: `SHOWS_DECLARED_PARAMS_DIFF` — the source for the D-11 rejection counter-evidence.
- Lines 119-130: per-kind branch where `parentTemplate` is structurally ignored for non-swap-template cards.
- Lines 346-388: `<DeclaredParamsColumn>` — the typography pattern this feature reuses.
- Line 377: `text-gray-700` for non-shared / non-tuned visual state.

### Analogous markup patterns

Already inlined in Story 1.3 — three patterns (Card shell, per-row typography, tuned-changed from→to row). Each pattern cites the codebase line that's being copied.

### Layout and structure

- The new panel mounts BETWEEN `<ConfigDiffPanel>` (current page line 319) and the metric-delta `<Card>` (current lines 320-345). The page's `<DetailPageShell>` wrapping at lines 298-302 doesn't change.
- The panel itself is a single `<Card>` with three sequential group sections inside `<CardContent>`. No horizontal columns, no responsive collapse — the panel is one column on every breakpoint (same as `<ConfigDiffPanel>`).
- Group sections are stacked vertically; each is `<h3>` header + row list. Spacing between groups: `mt-3` (matches the existing `space-y-3` pattern from `<SuggestedFollowupsPanel>`'s ul at line 117).

### Confirmation/modal dialog pattern

N/A — the panel has no dialogs, no mutations, no destructive actions.

### Visual consistency table

(Inlined in Story 1.3 — see the "Visual consistency" subsection.)

### Component composition

- `<FullParamSpacePanel>` is a single-file component (no child extraction). Rationale: per-group rendering is 8-12 lines of JSX each; extracting a `<ParamGroup>` would be 60 lines of plumbing to save 30 lines of inline rendering, with no reuse outside this panel. The panel stays a single file.
- The component imports `partitionTemplateParams` (Story 1.2), `extractFromTo` + `renderValue` (Story 1.1), `<InfoTooltip>` (existing primitive), `<Card>` + `<CardHeader>` + `<CardTitle>` + `<CardContent>` (existing shadcn primitives).

### Interaction behavior table

(Inlined in Story 1.3 — see the "Interaction behavior" subsection. The only interaction is the info-icon tooltip.)

### Handler function patterns

N/A — no event handlers, no mutations.

### Information architecture placement

(Inlined in Story 1.4 — see the "Information architecture placement" subsection.)

### Tooltips and contextual help

(Inlined in Story 1.3 — see the "Tooltips and contextual help" subsection.)

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.**

- `<ConfigDiffPanel>` (114 LOC total, under threshold) is unchanged in behavior. Story 1.2 only extracts two helpers (`extractFromTo` + `renderValue`) — the component re-imports them, and the test suite (`config-diff-panel.test.tsx`) continues to pass byte-identically per AC-9. Net delta on `<ConfigDiffPanel>`: ~20 LOC removed (the two helpers + their JSDoc), ~2 LOC added (the import statements).
- `<SuggestedFollowupsPanel>` (388 LOC) is unchanged — Story 1.4 only changes the `parentTemplate` *source* (lifted to come from `useTemplate(proposal.template.id)` instead of `useTemplate(parentStudy.data?.template_id)`); the component's API and rendering are byte-identical.
- The page (`page.tsx`, 402 LOC) gains ~10 LOC (the new import + the new mount JSX) and changes two existing lines (the `useStudy` enabled gate + the `useTemplate` input). No JSX is deleted.

### Client-side persistence

N/A — no localStorage, no sessionStorage. The panel has zero client-side state beyond per-render derivations.

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `ui/src/__tests__/lib/`
- Scope: pure helpers (`partitionTemplateParams`, `extractFromTo`, `renderValue`)
- Tasks:
  - [ ] Story 1.1 — `config-diff.test.ts` (7 cases: 3 for `extractFromTo` + 4 for `renderValue`).
  - [ ] Story 1.2 — `proposal-param-space.test.ts` (8 tests covering the FR-1 partition algorithm).
- DoD:
  - [ ] All critical branches covered; no helper claim untested.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: N/A — no backend changes.
- DoD:
  - [ ] N/A.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no new endpoints, no new error codes, no Pydantic schema changes.
- DoD:
  - [ ] N/A.

### 3.4 Component + Page tests (vitest)

- Location: `ui/src/__tests__/components/proposals/` (component) + `ui/src/__tests__/app/proposals/[id]/` (page)
- Scope: DOM rendering, mount conditions, race-gating, MSW-mocked fetches
- Tasks:
  - [ ] Story 1.3 — `full-param-space-panel.test.tsx` (7 tests covering AC-1, AC-2, AC-5, AC-6, AC-7, AC-8, plus the full-empty defensive case).
  - [ ] Story 1.4 — extend `page.test.tsx` with 6 new tests: Test 1 (AC-1 happy path, swap_template digest), Test 2 (AC-3 manual proposal), Test 3 (AC-4 template-404), Test 4 (AC-11 race-gating via dual-deferred resolver), Test 5 (FR-3 cycle-3 F1 regression guard — dedicated, no-actionable-followups digest), Test 6 (FR-7 edge case A — study-fetch error settlement).
- DoD:
  - [ ] All vitest files pass; no flaky timing.

### 3.5 E2E tests

- Location: `ui/tests/e2e/`
- Scope: real-backend Playwright; assert the panel renders end-to-end against a seeded manual proposal.
- **Rule: use Playwright's `page` for browser-visible assertions; `request` is for setup only (`seedManualProposal()` via existing helpers).**
- Tasks:
  - [ ] Story 1.4 — extend `proposals.spec.ts` with 1 new test under `test.describe('/proposals')`.
- DoD:
  - [ ] `cd ui && pnpm exec playwright test tests/e2e/proposals.spec.ts` → passes (including all existing tests).
  - [ ] No `page.route()` mocking.

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/proposals/config-diff-panel.test.tsx` | `extractFromTo`-dependent assertions (renders from/to columns from `config_diff` shapes) | 6 | **No change required.** AC-9 locks byte-identical pass. The helper moves files but is byte-identical in behavior. |
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | `parentTemplate` prop usage in `<SwapTemplateCard>` tests | ~30 | **No change.** The component's API is unchanged; Story 1.4 only changes the *source* of `parentTemplate` upstream. |
| `ui/src/__tests__/app/proposals/[id]/page.test.tsx` | Existing 11 tests for header / config-diff / metric-delta / followups / open-PR flow | 11 | **No change to existing tests.** Story 1.4 adds 6 new tests in a new `describe` block (5 from cycle-1 plus the cycle-3 F6 FR-7 edge case A regression guard for source-study-fetch failure). |
| `ui/tests/e2e/proposals.spec.ts` | Existing 4 tests for list filter / detail config-diff / reject / open-pr | 4 | **No change to existing tests.** Story 1.4 adds 1 new test in the same `test.describe('/proposals')`. |
| `ui/src/__tests__/lib/glossary.test.ts` | AC-12 audience-language check (no backend file paths / symbol names in `short` / `long` / `ariaLabel`) | (parametric — runs over every glossary entry) | **No change required.** The new `proposal.full_param_space` entry uses user-friendly language only. |

### 3.7 Migration verification

N/A — no schema changes.

### 3.8 CI gates

- [ ] `cd ui && pnpm lint` (ESLint flat-config)
- [ ] `cd ui && pnpm typecheck` (tsc strict + noUncheckedIndexedAccess)
- [ ] `cd ui && pnpm test` (vitest — runs ALL tests, including unit, component, page-level)
- [ ] `cd ui && pnpm exec playwright test proposals.spec.ts` (real-backend E2E for the proposals route)
- [ ] `cd ui && pnpm build` (Next.js production build — catches SSR / Turbopack issues)
- [ ] Backend test suite stays green (`make test-unit` / `make test-integration` / `make test-contract`) — no backend files touched but verify no incidental breakage from the dashboard regen pre-commit hook.

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — update at finalization (after PR merge):
- [ ] "Last 5 merges (newest first)" gets a new entry for this feature.
- [ ] "Current branch / execution context" updates to reflect `main` post-merge.
- [ ] Alembic head: NO CHANGE — stays at `0022_solr_engine_auth_check` (no migration in this PR).
- [ ] "In flight" entry for this feature removed.
- [ ] "Queued" backlog entry removed from MVP2 headliner list.

**`architecture.md`** — no update required. The feature adds no new top-level layer; existing `ui/src/components/proposals/` directory gains one file (`full-param-space-panel.tsx`) and two new shared lib files (`ui/src/lib/proposal-param-space.ts`, `ui/src/lib/config-diff.ts`) — none meet the criteria for adding a new architecture-doc entry.

**`CLAUDE.md`** — no update required. No new convention, no new env var, no new build command, no new release-matrix entry.

### 4.1–4.5 Topical docs

- `docs/01_architecture/` — no update. The feature's mount pattern matches the existing `<Card>` + `<InfoTooltip>` pattern already documented in `ui-architecture.md`.
- `docs/02_product/` — no update. No new user-story behavior; the proposal page exists and this is a polish addition.
- `docs/03_runbooks/` — no update. No operational footprint.
- `docs/04_security/` — no update. No new surface.
- `docs/05_quality/testing.md` — no update. Tests follow existing layer convention.

### 4.6 In-app tenant guides (`ui/public/docs/`)

- Possible regen impact: the proposal-detail screenshot in any guide that walks through `/proposals/<id>` will gain the new panel below `<ConfigDiffPanel>`. Per `/impl-execute`'s Step 2b "guide impact assessment," if any guide screenshots show the proposal detail page, regenerate them post-implementation. The current guides at `ui/public/docs/` (copied from `docs/08_guides/` via the `copy-docs-freshness` workflow) will be reviewed at finalization. If regeneration is warranted, the impl-execute skill handles it via `/guide-gen`.

### Documentation DoD
- [ ] `state.md` updated post-merge.
- [ ] No other docs/01-05 changes required.
- [ ] Guide impact assessed at finalization (regen via `/guide-gen` if warranted).

### 4.7 Finalization checklist (post-merge / `/impl-execute` Step 8)

These steps are repository-standard and handled by `/impl-execute`'s finalization stage. Listed here so the plan is self-contained and the implementer cannot accidentally skip them:

- [ ] Dashboard regen: the `mvp1-dashboard-regen` pre-commit hook fires on the finalization commit (the folder move triggers it) and regenerates `MVP2_DASHBOARD.md` + `mvp2_dashboard.html` + `DASHBOARD.md` + `dashboard.html`. Verify via `git diff` that the feature row moved from the Idea/Plan table to the Implemented table.
- [ ] Move the feature folder: `git mv docs/00_overview/planned_features/02_mvp2/feat_proposal_full_param_space_view docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_proposal_full_param_space_view` (the destination is FLAT — no bucket directory inside `implemented_features/`). Use the merge date as `<YYYY_MM_DD>`.
- [ ] **No `phase*_idea.md` files exist in the folder** before moving — verify via `ls`. Per D-8 + D-14, no deferred-phase artifacts are created for this feature.
- [ ] Update `pipeline_status.md` Implementation section to `Complete (PR #<N>)` with the merge date.
- [ ] Update `implementation_plan.md` header status to `Complete (PR #<N>)`.
- [ ] No GitHub tracking issue exists for this folder slug (verified during spec-gen Step 13).

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

The plan includes one mini-refactor: promoting `extractFromTo` + `renderValue` from `config-diff-panel.tsx` to `ui/src/lib/config-diff.ts` (Story 1.1). Goals:
- Eliminate duplication between `<ConfigDiffPanel>` and the new `<FullParamSpacePanel>`.
- Centralize the `{from, to}`-vs-2-tuple normalization in one tested module.
- Keep scope bounded — only the two helpers move, no other `<ConfigDiffPanel>` logic changes.

### 5.2 Planned refactor tasks

- [ ] Story 1.1 — promote `extractFromTo` + `renderValue` to `ui/src/lib/config-diff.ts`; update `<ConfigDiffPanel>` to re-import.
- [ ] No other refactor in scope.

### 5.3 Refactor guardrails

- **Behavioral parity proven by tests.** AC-9 locks byte-identical behavior of `<ConfigDiffPanel>` — its existing 6-test suite must pass without source edits. Plus 7 new tests at the helper level lock the contract for the second consumer.
- **Lint/typecheck remain green.** Standard pre-push gate.
- **No expansion of product scope.** The refactor is the minimum surface needed to support FR-5; no other helpers extracted.
- **No discovered-debt tracking needed.** The refactor is too small to surface tangential debt.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_proposal` (shipped 2026-05-11, PR #41) | Story 1.4 | implemented | none — defines `Proposal.config_diff` + `{from, to}` shape used by every story. |
| `feat_digest_executable_followups_swap_template` (shipped 2026-05-29) | Story 1.3 (visual fidelity reference) | implemented | none — provides `<DeclaredParamsColumn>` typography reference. |
| `feat_study_lifecycle` Phase 1 (shipped 2026-05-10, PR #18) | Story 1.4 | implemented | none — defines `Study.search_space.params` shape. |
| Soft: `feat_overnight_final_solution` Phase 1 + Phase 2 + summary card (PRs #440, #442, #444) | Story 1.4 | implemented | none — value compounds with the overnight autopilot; feature works without. |

All dependencies satisfied.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Story 1.4 race-gating regression — if `parentStudy.isPending === false` semantics differ from expected (e.g., TanStack returns `isPending === false` for disabled queries, masking the race), the panel mounts prematurely for study-backed proposals. | L | M | The page-level Test 4 (AC-11) explicitly verifies the race-gating against a never-resolving `useStudy` mock — if `isPending` doesn't behave as expected, the test fails. If TanStack's behavior surprises us, fall back to `parentStudy.fetchStatus !== 'idle'` or an explicit `data !== undefined \|\| error !== null` predicate. |
| `extractFromTo` extraction introduces import cycle (`config-diff-panel.tsx` ↔ `config-diff.ts`). | L | L | Cycle is impossible — `config-diff.ts` has no imports from `components/proposals/`. tsc + lint catch it if accidentally introduced. |
| `useStudy` lift on previously-disabled cases triggers downstream side effects (e.g., the `prefillValues` useMemo at lines 185-268 now branches differently). | L | L | The useMemo gates on `runFollowupIndex !== null` and `parentStudy.data` — the lift only changes "data present where before it was undefined." Same defensive gating still applies. Existing 11 page tests verify the actionable-followup path stays byte-identical. |
| Glossary key collision: `proposal.full_param_space` already exists elsewhere. | L | L | Mitigated — grep confirms no existing key. The naming convention follows the existing `proposal.*` namespace. |
| Playwright E2E flake from the new panel's render timing — the panel mounts after both `useTemplate` and `useStudy` settle, which may add a brief delay vs. the immediate `<ConfigDiffPanel>` mount. | L | L | Use `page.getByTestId('param-space-group-...').waitFor({ timeout: 5_000 })` rather than `toBeVisible()` without a wait. The existing `proposals.spec.ts` test for `config-diff-table` already uses `{ timeout: 5_000 }`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Template fetch 404 | `proposal.template.id` references a hard-deleted template | Panel does not mount; rest of page renders | none required — operator sees the proposal without the new panel |
| Source study fetch 404 | `proposal.study_id` references a hard-deleted study (studies have no `deleted_at` today; this is rare) | Panel mounts with `tunedUnchanged` empty; `untuned` shows every non-`config_diff` declared param | none required — degraded but coherent |
| Glossary key missing at runtime | `proposal.full_param_space` deleted from `glossary.ts` somehow | `<InfoTooltip>` returns `null` per its existing guard at [`info-tooltip.tsx:59`](../../../../ui/src/components/common/info-tooltip.tsx#L59); panel renders without the tooltip icon | none required — typing catches this at compile time |
| `partitionTemplateParams` receives malformed `declaredParams` (not a `Record<string, string>`) | Backend somehow returns a wrong shape on `/api/v1/query-templates/{id}` | The helper iterates `Object.keys()` which is safe; types are read via index access which returns `undefined` for non-keys; rows fall through to `'(unknown)'` type | none required — degraded but renders |

## 7) Sequencing and parallelization

### Suggested sequence

Story numbers ARE the execution order (dependency-ordered):

1. **Story 1.1** — promote `extractFromTo` + `renderValue` to `ui/src/lib/config-diff.ts`. Lands first; later stories import from it.
2. **Story 1.2** — pure helper `partitionTemplateParams`. Lands after Story 1.1 (depends on `extractFromTo`).
3. **Story 1.3** — `<FullParamSpacePanel>` component + glossary key. Lands after Story 1.2 (depends on the helper's typed exports).
4. **Story 1.4** — page-level integration + page tests + E2E. Lands last (depends on the panel component existing).

### Parallelization opportunities

For the four-story sequence above, parallelization is limited because each story depends on its predecessor's exports. However:

- Story 1.1's `extractFromTo` unit tests and Story 1.2's `partitionTemplateParams` unit tests can be authored in parallel once both stories' specs are read (both are pure helpers; no shared state).
- Story 1.3 component tests and Story 1.4 page tests can be authored in parallel after Story 1.3's component exists.

The four stories are small enough that linear execution is preferable — the whole plan is roughly 4-6 hours of work end-to-end, and the orchestration overhead of running stories in parallel exceeds the time saved.

## 8) Rollout and cutover plan

- **Rollout stages:** Single-stage merge to `main`. No feature flag (the feature is additive UI; rollback is a revert).
- **Feature flag strategy:** N/A.
- **Migration/cutover steps:** N/A — no schema changes.
- **Reconciliation/repair strategy:** N/A — no external systems involved.
- **Release gate:** Standard MVP2 PR.yml gates (backend lint/typecheck/tests/coverage, frontend lint/typecheck/vitest/build, full-stack smoke is opt-in per state.md). Cross-model review converged in the plan stage; final GPT-5.5 review in `/impl-execute`'s Step 6.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 — promote `extractFromTo` + `renderValue` to `ui/src/lib/config-diff.ts` + 7 unit cases
- [ ] Story 1.2 — pure helper `partitionTemplateParams` + 8 unit tests
- [ ] Story 1.3 — `<FullParamSpacePanel>` + glossary key + 7 component tests
- [ ] Story 1.4 — page-level integration + 6 page tests + 1 E2E test

### Blocked items
- _(none)_

### Done this sprint
- _(none yet)_

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables match the actual `git status` output).
- [ ] All tests for the story added/updated and passing.
- [ ] Commands executed and passed:
  - [ ] `cd ui && pnpm test --run <story-test-file>` (vitest for the new test file)
  - [ ] `cd ui && pnpm lint && pnpm typecheck` (clean)
  - [ ] For Story 1.4: `cd ui && pnpm exec playwright test tests/e2e/proposals.spec.ts` (5 passed — 4 existing + 1 new)
  - [ ] For Story 1.4: `cd ui && pnpm build` (succeeds)
- [ ] No backend test changes required (verified `make test-unit` etc. stay green if any backend changes happened incidentally — they shouldn't).
- [ ] No migration round-trip evidence required (no schema changes).
- [ ] Related docs/checklists updated in same PR when behavior/contract changed (only `state.md` at finalization).

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count**: Spec §8.1 lists 3 existing endpoints (`/api/v1/proposals/{id}`, `/api/v1/studies/{id}`, `/api/v1/query-templates/{id}`) — ALL consumed unchanged; ZERO new endpoints in this plan. Match: **3 = 3, 0 new = 0 new in plan**. ✅
2. **Spec ↔ plan error code coverage**: Spec §8.5 — N/A (no new error codes). Plan agrees. ✅
3. **Spec ↔ plan FR coverage**: 8 FRs in spec §7 — every one mapped to at least one story in §1 of this plan. ✅
4. **Story internal consistency**: Verified — no file is claimed by multiple stories (Story 1.1 owns `ui/src/lib/config-diff.ts` + test; Story 1.2 owns `ui/src/lib/proposal-param-space.ts` + test; Story 1.3 owns `ui/src/components/proposals/full-param-space-panel.tsx` + test + glossary diff; Story 1.4 owns the page edits + new page tests + new E2E test). ✅
5. **Test file count and assignment**:
   - `ui/src/__tests__/lib/config-diff.test.ts` → Story 1.1 ✓
   - `ui/src/__tests__/lib/proposal-param-space.test.ts` → Story 1.2 ✓
   - `ui/src/__tests__/components/proposals/full-param-space-panel.test.tsx` → Story 1.3 ✓
   - `ui/src/__tests__/app/proposals/[id]/page.test.tsx` (extension) → Story 1.4 ✓
   - `ui/tests/e2e/proposals.spec.ts` (extension) → Story 1.4 ✓
   - All 5 test surfaces assigned. ✅
6. **Gate arithmetic**: Plan has no multi-epic gates (single epic, single phase). No arithmetic to verify. ✅
7. **Open questions resolved**: Spec §19 has 0 unresolved open questions. All Q1/Q2/Q3 from the idea were locked as D-2/D-3/D-4. ✅
8. **Frontend UI Guidance completeness**: Plan-level UI Guidance section present with all required subsections (insertion point, analogous markup patterns, layout, visual consistency, component composition, interaction behavior, handler patterns — handler patterns marked N/A because no event handlers, IA placement, tooltips, legacy parity — marked "no >100 LOC component being deleted"). ✅
9. **Plan ↔ codebase verification** (Step 5 of skill):
   - Verified: Alembic head is `0022_solr_engine_auth_check.py` (cited in spec; matches `ls migrations/versions/`).
   - Verified: `ui/src/app/proposals/[id]/page.tsx` line 183 currently reads `useTemplate(parentStudy.data?.template_id)` (read at spec-time).
   - Verified: `ui/src/app/proposals/[id]/page.tsx` lines 176-178 currently gate `useStudy` with `enabled: parentStudyId !== null && hasActionableFollowup`.
   - Verified: `ui/src/components/proposals/config-diff-panel.tsx` lines 38-56 define `extractFromTo`; lines 21-26 define `renderValue`.
   - Verified: `ui/src/lib/glossary.ts` has the "Phase 2 — Proposals" block starting at line 558; the entry just before line 651 is `proposal.followup_declared_params_diff` (line 647).
   - Verified: `ui/tests/e2e/helpers/seed.ts:300` defines `seedTemplate` with `declared_params = { boost: 'float' }`.
10. **Enumerated value contract audit**: N/A — no backend allowlists consumed. The internal `ParamSpaceGroup` literal is exempt per spec §8.4 + D-12. ✅
11. **Audit-event coverage audit**: N/A — no state mutations. ✅
12. **Persistence scope consistency**: N/A — no localStorage / sessionStorage usage. ✅
13. **Legacy behavior parity**: Plan explicitly states "no >100 LOC component being deleted or migrated." ✅

All consistency checks pass. Plan is execution-ready pending the cross-model review pass.

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR (FR-1 through FR-8) is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, UI element inventory (where applicable), Tasks, and DoD.
- [x] Test layers (unit / component / page / E2E) are explicitly scoped — N/A integration + contract because backend is unchanged.
- [x] Documentation updates across docs/01-05 are planned — only `state.md` at finalization.
- [x] Lean refactor scope and guardrails are explicit (Story 1.2 helper promotion).
- [x] Single-phase plan has measurable per-story DoD gates.
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) has been performed with no unresolved findings.
- [ ] Cross-model GPT-5.5 review converged with no remaining High-severity findings (executed in spec-gen Step 6 — see pipeline_status.md cross-model summary).
