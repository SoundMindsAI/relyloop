# Implementation Plan — Create-Study Search-Space Builder

**Date:** 2026-05-20
**Status:** Draft
**Primary spec:** [`feature_spec.md`](./feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) §"Enumerated Value Contract Discipline" + §"Frontend Conventions" · [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) §"Form dropdown primitive" + §"DataTable primitive"

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from `feature_spec.md`.
- Phase gates are hard stops — epic-level gates after Epic 1 (round-trip discipline must work end-to-end before per-row controls land) and after Epic 4 (regression net green).
- Fail-loud tests: assert explicit DOM, ARIA, and per-row test IDs — not just "the component renders."
- Keep repository patterns consistent — the builder consumes existing shadcn primitives (`Select`, `Input`, `Label`), the existing `InfoTooltip` + `HelpPopover`, and the existing `<Textarea>`. No new shadcn primitives. No new third-party deps.
- Keep increments narrow enough to verify independently — every story has its own vitest assertions; the e2e gate is the final story.
- **Zero backend changes.** This plan touches `ui/src/` exclusively (plus one new `ui/tests/e2e/` file). Backend code is read-only context for the parity test.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Spec requirement (short) | Epic / Story | Notes |
|---|---|---|---|
| FR-1 | Builder renders one row per declared parameter, keyed off `templateBody.declared_params` | Epic 1 / Story 1.2 | Row identity comes from template, content from parsed JSON |
| FR-2 | Type selector mirrors `ParamSpec` discriminator + cross-type stash | Epic 2 / Story 2.1 | Parity test reads `search_space.py`; stash is `useRef` Map |
| FR-3 | Float/int rows expose `low`/`high` with native spinners + 200ms onChange debounce | Epic 2 / Story 2.1 | `step="any"` (float) / `step="1"` (int) |
| FR-4 | Log toggle on float rows: `aria-disabled` + onChange gates false→true when low ≤ 0 | Epic 2 / Story 2.2 | NO native `disabled` attribute |
| FR-5 | Categorical rows expose chip-input; no auto-dedup; auto-coerce typed values | Epic 2 / Story 2.3 | Anti-dedup is a hard invariant — fixture in round-trip test |
| FR-6 | Per-row cardinality counter via new `estimateParamCardinality()` helper | Epic 2 / Story 2.3 | Pure-function extraction from existing `estimateCardinality()` loop body |
| FR-7 | Header cardinality counter; red + max-contributor hint at >1e6; warning-only (does NOT block Next) | Epic 2 / Story 2.3 | Server-side `_check_cardinality` remains the authoritative gate |
| FR-8 | Split-view ≥1024px, tab-toggle <1024px; textarea always in DOM | Epic 3 / Story 3.1 | Use Tailwind `lg:grid-cols-2`; `hidden` (CSS) on inactive tab, not unmount |
| FR-9 | Bidirectional round-trip discipline: builder→textarea debounced 200ms; textarea→builder no debounce; parse-fail → non-interactive placeholder | Epic 1 / Story 1.1 | Load-bearing invariant; 11-fixture round-trip test |
| FR-10 | Non-actionable "Add custom param" affordance — `aria-disabled` (no native `disabled`); tooltip + Next.js `<Link>` to `/templates/{template_id}` | Epic 2 / Story 2.4 | Hidden when `templateBody` null |
| FR-11 | Per-row tooltips wired to existing `study.search_space.{param_spec,log,cardinality}` glossary keys | Epic 2 / Stories 2.1, 2.2, 2.3 | All three keys already exist at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94); no glossary edits |

**Phase coverage:** single phase — entire spec is Phase 1. No deferred phases. No `phase<N>_idea.md` tracking files required.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** for a frontend-only feature; the Story numbering reflects intended execution order.

### Story-level detail requirements

Each story below carries: Outcome, New files, Modified files, UI element inventory, State dependency analysis, Tasks, DoD. Endpoints / Pydantic schemas / Key interfaces sections are N/A (zero backend changes). Where a story needs analogous markup, copy-pasteable JSX is embedded inline.

### Conventions (project-specific)

```
- Frontend TypeScript: strict mode + `noUncheckedIndexedAccess` on (per ui/tsconfig.json).
- No new third-party deps. Use shadcn primitives + Tailwind + native HTML controls only.
- Form state via React Hook Form (existing wiring on CreateStudyModal). Builder is a controlled
  component over `search_space_text: string`; never declares its own RHF field.
- Tooltips via existing `<InfoTooltip glossaryKey="..." />` + `<HelpPopover glossaryKey="..." />`
  primitives from ui/src/components/common/. Glossary keys live in ui/src/lib/glossary.ts.
- Component file structure: `ui/src/components/studies/search-space-builder/<file>.tsx`. Each
  file exports one component; named exports (NOT default).
- Test pattern: vitest + @testing-library/react; wrap with QueryClientProvider + TooltipProvider;
  mock @/components/ui/select via the shared helper at ui/src/__tests__/helpers/shadcn-select-mock.tsx
  for every modal-mounting test. Bare unit tests (no modal mount) skip the select mock.
- E2E: Playwright; real backend at http://127.0.0.1:8000; no page.route() mocking; use
  seedFullChain() from tests/e2e/helpers/seed.ts.
- Lint guards already in repo: form-select-discipline.test.tsx (skipped by enum source-of-truth
  policy since ParamSpec.type values are NOT in enums.ts — verified in Story 2.1 task list).
```

### AI Agent Execution Protocol (applies to every story)

0. Load context first: read `architecture.md` and `state.md` before starting Story 1.1.
1. Read scope: verify story outcome + UI element inventory + tasks + DoD.
2. **No backend implementation** in this plan — proceed straight to step 4.
3. (Skipped — no backend.)
4. Implement frontend per the story's New files + Modified files tables.
5. Run vitest scope (`pnpm test path/to/new/spec.test.tsx`); E2E only after Story 4.1.
6. Update docs/checklists for behavior changes in same PR (only Stories 4.1 + the finalization touch docs).
7. (Skipped — no schema changes.)
8. Attach evidence in PR description: vitest output, files changed.
9. After Story 4.1, update `state.md` (active branch, recently shipped) and `docs/01_architecture/ui-architecture.md` ("Form dropdown primitive" section gains a sibling pointer). `architecture.md` is intentionally unchanged per spec §15.

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Builder scaffolding & round-trip discipline

**Goal:** stand up the `<SearchSpaceBuilder>` shell, bidirectional textarea round-trip, and the 11-fixture round-trip parity test BEFORE any per-row controls land. This is the load-bearing invariant — the rest of the feature builds on it.

**Epic gate (hard stop):** Story 1.1 + 1.2 land; `round-trip.test.tsx` passes (11 fixtures + numeric normalization + duplicate-choices fixture); `create-study-modal.builder-rendering.test.tsx` passes (declared-param row count + tooltip slots). Verifiable with `cd ui && pnpm test ui/src/__tests__/components/studies/search-space-builder/ ui/src/__tests__/components/studies/create-study-modal.builder-rendering.test.tsx`.

### Story 1.1 — Builder shell + bidirectional textarea round-trip

**Outcome:** `<SearchSpaceBuilder value onChange templateBody />` exists, parses `value` (the textarea string), applies semantic round-trip discipline (parse → render → debounced stringify), and renders the non-interactive placeholder on JSON.parse failure. No row content yet — rows render as empty placeholder divs at this stage; per-row visual elements arrive in Story 1.2 + Epic 2.

**FRs:** FR-9 (full); FR-1 (skeleton — empty rows).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/index.tsx` | `<SearchSpaceBuilder>` top-level component — props: `{ value: string; onChange: (next: string) => void; templateBody: TemplateBody \| null; templateId: string \| undefined; templateFetchStatus: 'idle' \| 'ok' \| '404' \| 'transient'; }`. The `templateId` + `templateFetchStatus` props let the builder distinguish "no template selected yet" (`templateFetchStatus === 'idle'`) from "fetch failed" (`'transient'` / `'404'`) so the placeholder text can differ. Owns parse/stringify, debounce ref, non-interactive placeholder, stash `useRef<Map<string, StashEntry>>(new Map())`. Exports `parseSearchSpace()` and `stringifySearchSpace()` helpers (used by the round-trip parity test). |
| `ui/src/components/studies/search-space-builder/types.ts` | Re-exports `ParamSpec` and `SearchSpaceJson` from `@/lib/search-space-defaults` plus the local `StashEntry` and `StashMap` types used by the cross-type stash (see FR-2). |
| `ui/src/components/studies/search-space-builder/placeholder.tsx` | `<BuilderPlaceholder variant="parse-error" \| "no-template" \| "missing-params-wrapper" message? />` — single component for all four placeholder modes (parse-error per FR-9; missing-`params` per §11 edge flow; transient fetch per AC-11; empty no-template). `role="status" aria-live="polite"`. |
| `ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx` | 11-fixture round-trip parity per AC-7 + §4 product principles. **Mounts `<SearchSpaceBuilder>` for each fixture** (test consumes the canonical JSON via an `onChange` spy + `vi.advanceTimersByTime(250)` for the 200ms debounce), AND keeps 3 supplemental pure-helper assertions (`parseSearchSpace` / `stringifySearchSpace` empty/invalid/valid). Fixtures inline in a `const FIXTURES: { name: string; before: string; expectedAfter?: string }[]` constant. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Import `<SearchSpaceBuilder>` and wire it ABOVE the existing `<Textarea>` inside the `step === 3` block at [lines 530-594](../../../../ui/src/components/studies/create-study-modal.tsx#L530-L594). For Story 1.1, render the builder in single-column layout (Story 3.1 adds responsive split/tab); pass `value={values.search_space_text}`, `onChange={(next) => form.setValue('search_space_text', next)}`, `templateBody={templateBody}`, `templateId={values.template_id || undefined}`, `templateFetchStatus={templateFetchStatus}` (re-using the existing state machine at [lines 184-200](../../../../ui/src/components/studies/create-study-modal.tsx#L184-L200)). The builder writes back via the existing `form.setValue('search_space_text', …)` path — keeps the auto-fill effect at lines 205-259 and the Undo path intact. |

**UI element inventory**

The builder's visual surface at end of Story 1.1 is intentionally minimal — placeholder-only — so the round-trip discipline can be verified without confusing it with per-row rendering. Elements:

| Element type | Purpose | Source / data |
|---|---|---|
| `<div data-testid="cs-search-space-builder">` container | Top-level wrapper around all builder content | Always rendered (even when placeholder fires) |
| `<BuilderPlaceholder>` variants | "Pick a template to populate the builder" (templateBody null + parsed JSON empty); "JSON has syntax errors — fix in the textarea" (parse-error); "Wrap your JSON in a `params:` object — the rows above are empty because no `params` key was found." (missing-params); "Couldn't load the template. Server-side validation will still catch typos on submit." (transient/404 fetch — only after Story 2.4 wires templateBody fetch checks) | Renders based on `(templateBody, parsedResult, JSON.parse outcome)` triple |
| Empty row placeholders | `<div data-testid="cs-param-row-{name}">` per declared param key; visually shows just the param name + a "(content arrives in Story 1.2)" debug note in Story 1.1, replaced by Story 1.2's full row UI | Iterates `Object.keys(templateBody.declared_params)` |

**State dependency analysis**

State the builder OWNS (component-local, never persisted to form / localStorage):
- `parseResult: { ok: true; data: SearchSpaceJson } | { ok: false; error: string }` — derived synchronously via `useMemo` on `value`. Pure function of `value`.
- `debounceRef: useRef<ReturnType<typeof setTimeout> | null>` — holds the pending stringify-then-onChange timeout. Cleared on unmount + on every textarea-driven `value` change (last-edit-wins per FR-9).
- `stashRef: useRef<StashMap>` — initialized to `{}`; populated in Story 2.1. Story 1.1 only initializes the ref; consumers arrive later.

State the builder CONSUMES (from props):
- `value: string` — comes from `form.watch('search_space_text')` via React Hook Form (CreateStudyModal); changes on every textarea keystroke.
- `templateBody: TemplateBody | null` — comes from the existing `templateQuery.data` at [`create-study-modal.tsx:175-188`](../../../../ui/src/components/studies/create-study-modal.tsx#L175-L188); already in scope.

State the builder MUST NOT touch:
- `form` (React Hook Form instance), `searchSpaceError`, `placeholderWarning`, `autoFillSignatures`, `templateFetchStatus`, `autoFillTimeoutRef`. The builder communicates ONLY via the `onChange` callback.

**Analogous markup patterns (reused by Story 1.1)**

```tsx
{/* Pattern: empty/info placeholder card — adapted from ui/src/components/studies/create-study-modal.tsx:516-526 (templateHasNoDeclaredParams branch) */}
<p
  role="status"
  aria-live="polite"
  className="text-sm text-muted-foreground"
  data-testid="cs-search-space-builder-placeholder"
>
  Pick a template to populate the builder.
</p>
```

```tsx
{/* Pattern: parse-error placeholder — `role="status" aria-live="polite"` per spec AC-12.
    The detailed parse error continues to flow through the existing
    `<p data-testid="cs-search-space-error">` block in CreateStudyModal
    (so a11y users don't double-announce). The builder placeholder is the
    UX cue; the inline alert is the actual error surface. */}
<div
  role="status"
  aria-live="polite"
  className="text-sm text-muted-foreground border border-dashed border-border rounded p-3"
  data-testid="cs-search-space-builder-parse-error"
>
  JSON has syntax errors — fix in the textarea to use the builder.
</div>
```

**Tasks**

1. Create the `ui/src/components/studies/search-space-builder/` directory; add `index.tsx`, `types.ts`, `placeholder.tsx`. Each file exports one component / type group.
2. Implement `parseSearchSpace(text: string): { ok: true; data: SearchSpaceJson } | { ok: false; error: string }`. Returns ok for `''`, `'{}'`, `'{"params":{}}'`, and any valid SearchSpace JSON. Returns `{ ok: false, error: e.message }` on `JSON.parse` failure.
3. Implement `stringifySearchSpace(data: SearchSpaceJson): string` — `JSON.stringify(data, null, 2)`. Pure wrapper for symmetry with parse.
4. In `index.tsx`, implement debounced builder→textarea write: when the builder needs to update content, schedule `setTimeout(() => onChange(stringifySearchSpace(updated)), 200)`. Cancel pending timeout on every `value` prop change (textarea-driven update) and on unmount. **Add a canonicalize-on-mount pass:** in a mount-only `useEffect`, parse `value`; if `parseResult.ok` AND the round-trip `stringifySearchSpace(parseResult.data) !== value`, call `emitBuilderWrite(stringifySearchSpace(parseResult.data))` exactly once. This is the mechanism Story 1.1's round-trip parity test exercises — it fires the canonicalize-on-mount, captures the emitted JSON via `onChange` spy, and asserts against expected. (For idempotent fixtures, the effect doesn't emit; the test asserts `onChange` was NOT called and the input is already canonical.)
5. Implement the placeholder cascade (per spec FR-9 + §11):
   - `parseResult.ok === false` → render `<BuilderPlaceholder variant="parse-error">` (the non-interactive placeholder — ONLY for unparseable JSON per FR-9).
   - `templateBody === null && templateFetchStatus === 'transient'` → render `<BuilderPlaceholder variant="transient">` (matches AC-11).
   - `templateBody === null && (templateFetchStatus === 'idle' || templateId === undefined)` → render `<BuilderPlaceholder variant="no-template">` (matches AC-1 boot state).
   - `templateBody !== null && parseResult.ok` → render rows for every `Object.keys(templateBody.declared_params)` key (using `parseResult.data?.params?.[name]` for spec content; `undefined` = empty/unset row per FR-1). If `parseResult.data.params === undefined` (parseable JSON missing the `params` wrapper), STILL render the rows (treating `params` as `{}`) AND render a foot hint "Wrap your JSON in a `params:` object — the rows above are empty because no `params` key was found." NEVER swap to the placeholder for this case (per spec §11 edge flow, "User pastes a JSON object missing `params` wrapper").
6. Wire the builder into [`create-study-modal.tsx:530-594`](../../../../ui/src/components/studies/create-study-modal.tsx#L530-L594): import + insert ABOVE the existing `<div className="space-y-1.5">` that wraps the InfoTooltip + Textarea (so the builder sits as a sibling above the JSON region). Single-column layout — Story 3.1 will add `lg:grid-cols-2` wrapper.
7. Write `round-trip.test.tsx` per spec AC-7 ("the parity test feeds 11 fixture shapes through JSON.parse → builder state → JSON.stringify"). Use a **builder-mount harness driven by the canonicalize-on-mount effect from Task 4**: render `<SearchSpaceBuilder value={fixture} onChange={spy} templateBody={fakeTemplateBody} templateId="t1" templateFetchStatus="ok" />` for each fixture. The mount effect fires immediately on render; capture the emitted JSON via the `onChange` spy. Fixtures (spec §4): (1) boost-only float, (2) mixed float+int, (3) fuzziness categorical, (4) log float, (5) log-with-low<=0, (6) multi-param hitting cap, (7) placeholder categorical, (8) empty params object `{"params":{}}`, (9) duplicate categorical choices `["AUTO","AUTO","BM25"]`, (10) numeric normalization `{"high":10.0}` → `{"high":10}`, (11) exponent normalization `{"low":1e-3}` → `{"low":0.001}`. Each fixture asserts:
   - For **already-canonical** fixtures (1–7, 9 with deterministic stringify output) → `onChange` was NOT called (mount effect detected no-op canonicalization); `deepEqual(JSON.parse(value), JSON.parse(stringifySearchSpace(parseSearchSpace(value).data)))` confirms semantic equality.
   - For **fixtures requiring normalization** (8 with `{}` ← `{params:{}}` equivalence; 10, 11) → `onChange` was called exactly once with the expected canonical string; subsequent re-mount with the canonical value emits nothing (idempotence).
   Supplement with `parseSearchSpace`/`stringifySearchSpace` pure-helper unit tests in the same file (3 assertions: parses empty/invalid/valid; stringifies symmetric).
8. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test`. Investigate and fix any test failures (including existing-test regressions — the builder modification at create-study-modal.tsx must not break the 7 existing modal tests).

**Definition of Done**

- `<SearchSpaceBuilder>` mounts inside CreateStudyModal at Step 4 without crashing the modal (vitest: render existing `create-study-modal.test.tsx` happy-path).
- `round-trip.test.tsx` passes: 11 fixtures, semantic equality on 1–7+9, textual normalization on 8, 10, 11.
- `parseSearchSpace('')` returns ok with the empty `SearchSpaceJson` `{params:{}}` representation (or alternatively `{ok: true, data: undefined}` — implementer's choice, documented in `types.ts`).
- `parseSearchSpace('{not valid json')` returns `{ok: false, error: ...}` with a non-empty `error` string.
- Debounced write fires exactly once 200ms after the last builder mutation (vitest with `vi.useFakeTimers()`).
- Pending debounced write is cancelled when `value` prop changes (vitest: assert `onChange` is NOT called after a textarea-driven `value` update).
- All 7 existing `create-study-modal.*.test.tsx` files continue to pass without modification (regression net).
- `pnpm typecheck` clean.
- `pnpm lint` clean.

### Story 1.2 — Per-row rendering keyed off `declared_params` + tooltip slots

**Outcome:** Each declared parameter renders as a recognizable row with a name chip, simple-form badge, type selector (read-only display only — full editable selector arrives in Story 2.1), and tooltip slots for `.param_spec` / `.log` / `.cardinality`. The row's spec content reads from the parsed JSON; row identity comes from `templateBody.declared_params`. "Empty/unset" state renders when a declared key has no JSON spec.

**FRs:** FR-1 (full); FR-11 (full — all three glossary subkeys wired); FR-2 (skeleton — type selector renders but is non-interactive in Story 1.2).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/param-row.tsx` | `<ParamRow paramName declaredType spec onSpecChange stashRef />` — single-row container. Renders name chip + simple-form badge + tooltip slots. In Story 1.2 the type/low/high/log/choices controls render as read-only displays; Stories 2.1–2.3 swap each in for editable controls. |
| `ui/src/__tests__/components/studies/create-study-modal.builder-rendering.test.tsx` | Vitest test asserting: declared-param rows render in `Object.keys` order; row container test IDs follow `cs-param-row-{name}` pattern (NOT `cs-row-`); simple-form badge appears next to name; all three `<InfoTooltip>` glossary keys are present in the DOM. Mocks shadcn select via shared helper. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/search-space-builder/index.tsx` | Replace the Story-1.1 empty row placeholders with `<ParamRow>` instances. Pass per-row spec from `parseResult.data.params[name]` if present, else `undefined` (which `<ParamRow>` interprets as "empty/unset"). Provide a stable `onSpecChange(name, nextSpec)` callback that constructs the next `SearchSpaceJson` and schedules the debounced write. |

**UI element inventory** (per row, Story 1.2 read-only stage)

| Element type | Label / data | Notes |
|---|---|---|
| Row container `<div data-testid="cs-param-row-{name}">` | Wraps the entire row | Distinct from `cs-row-{name}-{control}` test IDs used in Stories 2.x |
| Name chip `<span>` | `{paramName}` | Visual style matches existing badge pattern; use `<Badge variant="outline">` from `@/components/ui/badge` |
| Simple-form badge `<span>` | `{declaredType}` (e.g., `float`, `int`, `string`, `bool`) | Smaller; secondary color |
| Type selector (read-only display) | Shows current `spec.type` or "unset" | Story 2.1 swaps for editable `<Select>` |
| Low/high read-only display | Shows `low` / `high` for float/int specs | Story 2.1 swaps for `<Input type="number">` |
| Choices read-only display | Shows comma-joined choices for categorical | Story 2.3 swaps for chip input |
| `<InfoTooltip glossaryKey="study.search_space.param_spec" />` | Next to type label | FR-11 |
| `<InfoTooltip glossaryKey="study.search_space.log" />` | Next to log display (float rows only) | FR-11 |
| `<InfoTooltip glossaryKey="study.search_space.cardinality" />` | Next to per-row cardinality counter (cardinality counter itself arrives in Story 2.3 — Story 1.2 reserves the tooltip slot via a placeholder span "—") | FR-11 |

**State dependency analysis**

- `<ParamRow>` receives `spec: ParamSpec | undefined` from `<SearchSpaceBuilder>`. Never holds its own copy.
- `<ParamRow>` calls `onSpecChange(name, nextSpec)` to propagate edits; Story 1.2 does NOT invoke this callback (read-only rows). Story 2.1+ wires it.
- `stashRef` is passed through to `<ParamRow>` but unused in Story 1.2.

**Analogous markup patterns**

```tsx
{/* Pattern: row container — adapted from ui/src/components/studies/digest-panel.tsx:56 (grid section) + studies-table.column-config.tsx (badge usage) */}
<div
  data-testid={`cs-param-row-${paramName}`}
  className="rounded-md border border-border bg-card p-3 space-y-2"
>
  <div className="flex items-center gap-2">
    <Badge variant="outline" className="font-mono text-xs">{paramName}</Badge>
    <Badge variant="secondary" className="text-xs">{declaredType}</Badge>
  </div>
  <div className="grid gap-3 sm:grid-cols-2">
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <Label>Type</Label>
        <InfoTooltip glossaryKey="study.search_space.param_spec" />
      </div>
      {/* Story 2.1: <Select> swap; Story 1.2: read-only span */}
      <span className="text-sm font-mono">{spec?.type ?? 'unset'}</span>
    </div>
    {/* low/high/log/choices slots — placeholders in Story 1.2, real controls in Stories 2.x */}
  </div>
</div>
```

**Tasks**

1. Create `ui/src/components/studies/search-space-builder/param-row.tsx` with the read-only structure above.
2. In `index.tsx`, swap the empty row placeholders for `<ParamRow>` invocations. Iterate `Object.keys(templateBody.declared_params)`.
3. Build the `onSpecChange(name, nextSpec)` callback: derive the next `SearchSpaceJson` by `{...parseResult.data, params: {...parseResult.data.params, [name]: nextSpec}}`; schedule the debounced stringify+onChange. (Story 1.2 only sets up the callback wire — no internal control will trigger it until Story 2.1.)
4. Wire all three `<InfoTooltip>` glossary keys; verify they read from the existing `study.search_space.param_spec` / `.log` / `.cardinality` entries at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94) without modification.
5. Write `create-study-modal.builder-rendering.test.tsx` with 4 assertions: (a) given a 3-key `declared_params`, exactly 3 `[data-testid^="cs-param-row-"]` elements render; (b) row order matches `Object.keys` order; (c) each row has both a name chip and a simple-form badge; (d) `study.search_space.param_spec` glossary key resolves to non-empty text inside the row's tooltip surface (via `screen.getByText` against the short text).
6. Run `pnpm typecheck && pnpm lint && pnpm test`. Investigate failures.

**Definition of Done**

- `builder-rendering.test.tsx` passes (4 assertions).
- A template with `declared_params = {a: 'float', b: 'int', c: 'string'}` renders rows for a, b, c in that order, with `data-testid="cs-param-row-a"`, `cs-param-row-b`, `cs-param-row-c`.
- The three FR-11 glossary keys are present in the DOM via `<InfoTooltip>` invocations.
- AC-1 (FR-1) holds: rows render keyed off declared_params, not parsed JSON params. Verifiable by feeding `{"params": {"unknown": {"type":"float","low":0,"high":1}}}` and a `declared_params = {"a": "float"}` → exactly 1 row renders for `a` (empty/unset spec because `params.a` is absent); no row renders for `unknown`.
- All existing modal tests pass.

**Epic 1 gate (hard stop):** Stories 1.1 + 1.2 complete; round-trip + rendering tests green; all 7 existing modal tests pass. `pnpm typecheck && pnpm lint && pnpm test` exit 0.

---

## Epic 2 — Per-row interactive controls

**Goal:** swap the read-only displays from Story 1.2 for editable controls — type selector with cross-type stash + parity test (FR-2), float/int spinners (FR-3), log toggle (FR-4), categorical chip-input (FR-5), cardinality counters (FR-6, FR-7), and the disabled "Add custom param" affordance (FR-10).

**Epic gate (hard stop):** Stories 2.1–2.4 all land; `param-spec-discriminator.parity.test.tsx` passes; `create-study-modal.builder-edits.test.tsx` passes 6 assertions; `estimateParamCardinality.test.ts` passes 6 assertions.

### Story 2.1 — Type selector + float/int spinners + cross-type stash + ParamSpec discriminator parity test

**Outcome:** Type selector becomes interactive. Float and int rows expose `<Input type="number">` for `low`/`high` with native spinners + 200ms debounce. Cross-type stash preserves the user's prior spec across type-switch sessions. A vitest parity test reads `backend/app/domain/study/search_space.py` and asserts the type-selector option array matches the discriminator Literals one-for-one.

**FRs:** FR-2 (full); FR-3 (full); FR-11 (verified — already in place from Story 1.2).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/row-type-selector.tsx` | `<RowTypeSelector value onChange paramName declaredType stashRef />` — shadcn `<Select>` wrapping the 3-option array `['float', 'int', 'categorical'] as const`. **Carries the source-of-truth comment** `// Values must match backend/app/domain/study/search_space.py ParamSpec discriminator` directly above the array. Implements the stash read/write logic on switch via `Map.get`/`Map.set`. |
| `ui/src/components/studies/search-space-builder/row-numeric.tsx` | `<RowNumeric paramType="float" \| "int" low high onChange onBlurFlush />` — paired `<Input type="number">` controls with `step="any"` (float) or `step="1"` (int). **No local debounce** — calls parent `onChange(nextSpec)` synchronously on every keystroke; the parent `<SearchSpaceBuilder>` is the single 200ms debounce boundary per FR-3. **`onBlur` calls `onBlurFlush()`** which the parent uses to cancel pending debounce + write synchronously. |
| `ui/src/components/studies/search-space-builder/stash.ts` | Stash types + helpers: `type StashEntry = Partial<Record<ParamType, ParamSpec>>;` and `type StashMap = Map<string, StashEntry>`. Pure-function helpers `stashGet(map, name, type)`, `stashSet(map, name, type, spec)`, `stashClearRow(map, name)`, `stashClearAll(map)`. No state — operates on the map by reference. |
| `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx` | The single most important test in Epic 2. Reads `backend/app/domain/study/search_space.py` from disk (via `fs.readFileSync(path.join(process.cwd(), '..', 'backend/app/domain/study/search_space.py'), 'utf-8')` — vitest cwd is `ui/`, so `..` resolves to repo root), extracts `Literal["..."]` values via regex, asserts the frontend's `TYPE_VALUES` array matches one-for-one in order. Fails fast on backend changes that don't update the frontend. |
| `ui/src/__tests__/components/studies/create-study-modal.builder-edits.test.tsx` | Story 2.1 creates the file with the first 5 assertions (see Tasks step 8). Story 2.2 appends one assertion; Story 2.3 appends two; final count = 8 assertions across Stories 2.1–2.3. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/search-space-builder/param-row.tsx` | Replace the read-only type/low/high spans with `<RowTypeSelector>` + `<RowNumeric>` for float/int rows. Wire `onSpecChange` to actually fire. Wire the stash ref via the `Map` helpers from `stash.ts`: on type-switch, call `stashSet(stashRef.current, paramName, priorType, priorSpec)` before constructing the next spec. Read `stashGet(stashRef.current, paramName, nextType)` first; fall back to `defaultSpecForType(nextType)` (target-type-only, ignores `declaredType`) if no stash entry. |
| `ui/src/components/studies/search-space-builder/index.tsx` | Add the stash invalidation effects: (a) when the textarea-driven `value` changes a specific row's spec, invalidate `stashRef.current[paramName]` for that row (compare prior `parseResult.data.params[name]` to new value); (b) when `templateBody` ref changes, clear the entire `stashRef.current = {}`. |

**UI element inventory** (additions vs Story 1.2)

| Element type | Label / data | Notes |
|---|---|---|
| Type `<Select>` | Values: `float` / `int` / `categorical` | source-of-truth comment required |
| Low `<Input type="number" data-testid="cs-row-{name}-low" step="any"\|"1">` | Float/int only | Browser spinners |
| High `<Input type="number" data-testid="cs-row-{name}-high" step="any"\|"1">` | Float/int only | Browser spinners |
| Row error `<p role="alert" data-testid="cs-row-error-{name}">` | "low must be < high" / "low must be ≤ high" | Renders on Pydantic-mirrored bound failure |

**State dependency analysis**

- `<RowTypeSelector>` is fully controlled — takes `value`/`onChange`, no internal state. Stash lookups happen via the `stashRef: useRef<StashMap>` passed from `<SearchSpaceBuilder>`.
- `<RowNumeric>` is fully controlled — no local debounce. Calls parent `onChange(nextSpec)` on every keystroke; calls `onBlurFlush()` on blur. The parent's single 200ms debounce ref is the only timer in play. Per spec FR-3: "MUST debounce the textarea round-trip on numeric input — write back on `onBlur` (synchronous) AND with a 200ms `setTimeout` on `onChange` (debounced)." `<SearchSpaceBuilder>` implements this: on every `onChange` call from a row, schedule `setTimeout(write, 200)` (cancelling prior); on `onBlurFlush()` call from a row, clear the pending timeout and `write()` synchronously.
- The stash is `useRef<StashMap>(new Map())` per spec §4 (Map, not Record/object — avoids `__proto__` collisions for arbitrary param names and matches the spec's explicit type signature).

**Enumerated value contract verification**

| Field | Accepted values (exact) | Backend source of truth | Frontend call site |
|---|---|---|---|
| `ParamSpec.type` | `float`, `int`, `categorical` | `backend/app/domain/study/search_space.py:83-89` (`ParamSpec` discriminated union; each variant's `Literal["..."]` at lines 40, 59, 79) | `ui/src/components/studies/search-space-builder/row-type-selector.tsx` |

**Grep verification:** `grep -n 'Literal\["float"\]\|Literal\["int"\]\|Literal\["categorical"\]' backend/app/domain/study/search_space.py` returns exactly 3 matches at lines 40, 59, 79 (verified at spec time). The parity test enforces this in CI by reading the file at runtime.

**Note on `enums.ts`:** `ParamSpec.type` values are NOT mirrored into `ui/src/lib/enums.ts` because they're wire-format on a JSONB column rather than a top-level filterable enum. The `form-select-discipline.test.tsx` lint guard (which scans for inline `<SelectItem value="X">` matching backend enums in `enums.ts`) does NOT flag this case. The parity test is the gate.

**Analogous markup patterns**

```tsx
{/* Pattern: shadcn Select with mapped values — adapted from ui/src/components/studies/create-study-modal.tsx:603-628 (metric selector) */}
// Values must match backend/app/domain/study/search_space.py ParamSpec discriminator
const TYPE_VALUES = ['float', 'int', 'categorical'] as const;
type ParamType = (typeof TYPE_VALUES)[number];

<Select value={value} onValueChange={(v) => onChange(v as ParamType)}>
  <SelectTrigger id={`cs-row-${paramName}-type`} data-testid={`cs-row-${paramName}-type`}>
    <SelectValue />
  </SelectTrigger>
  <SelectContent>
    {TYPE_VALUES.map((t) => (
      <SelectItem key={t} value={t}>{t}</SelectItem>
    ))}
  </SelectContent>
</Select>
```

```tsx
{/* Pattern: paired numeric inputs with row error — adapted from ui/src/components/studies/create-study-modal.tsx:716-733 (max_trials/time_budget pair).
    No local debounce; parent owns the 200ms debounce; blur flushes synchronously per FR-3. */}
<div className="grid gap-2 sm:grid-cols-2">
  <div className="space-y-1">
    <Label htmlFor={`cs-row-${paramName}-low`}>Low</Label>
    <Input
      id={`cs-row-${paramName}-low`}
      data-testid={`cs-row-${paramName}-low`}
      type="number"
      step={paramType === 'int' ? '1' : 'any'}
      value={low ?? ''}
      onChange={(e) => onChange({ low: e.target.value === '' ? undefined : Number(e.target.value), high })}
      onBlur={onBlurFlush}
    />
  </div>
  <div className="space-y-1">
    <Label htmlFor={`cs-row-${paramName}-high`}>High</Label>
    <Input
      id={`cs-row-${paramName}-high`}
      data-testid={`cs-row-${paramName}-high`}
      type="number"
      step={paramType === 'int' ? '1' : 'any'}
      value={high ?? ''}
      onChange={(e) => onChange({ low, high: e.target.value === '' ? undefined : Number(e.target.value) })}
      onBlur={onBlurFlush}
    />
  </div>
</div>
{rowError && (
  <p role="alert" aria-live="polite" className="text-sm text-destructive" data-testid={`cs-row-error-${paramName}`}>
    {rowError}
  </p>
)}
```

**Tasks**

1. Add `export` keyword to `simpleFormSpec()` in [`ui/src/lib/search-space-defaults.ts:68-81`](../../../../ui/src/lib/search-space-defaults.ts#L68-L81). Pure refactor; no behavior change. Verify existing `search-space-defaults.test.ts` still passes. (This is the minimal change needed to make Story 2.1's fallback logic legal — the spec FR-1 says rows initialize from `simpleFormSpec(declared_params[paramName])` when no JSON spec exists.)
2. Create `stash.ts` with `StashEntry`, `StashMap`, and pure-function helpers (`stashGet`, `stashSet`, `stashClearRow`, `stashClearAll`).
3. Create `row-type-selector.tsx` with the source-of-truth comment immediately above the `TYPE_VALUES` array. On type-switch: read prior spec, call `stashSet(stash, paramName, priorType, priorSpec)`; lookup `stashGet(stash, paramName, nextType)`; fall back to **`defaultSpecForType(nextType)`** (defined inline or in `stash.ts`) which returns: `{type: 'float', low: 0, high: 1}` for `'float'`; `{type: 'int', low: 0, high: 5}` for `'int'`; `{type: 'categorical', choices: ['__placeholder__']}` for `'categorical'`. **`defaultSpecForType` takes ONLY the target type** — it does NOT consult `declaredType` (the user has explicitly picked a new type; the simple-form heuristic from `simpleFormSpec()` would return the wrong discriminator). `simpleFormSpec()` from `search-space-defaults.ts` is still used by `<SearchSpaceBuilder>` for the **initial** empty/unset row rendering per FR-1 (where the row's spec is still undefined and the simple-form fallback is the correct seed).
4. Create `row-numeric.tsx` — **no local debounce**. Calls parent `onChange` synchronously on every keystroke; calls `onBlurFlush()` on blur. Parent (`<SearchSpaceBuilder>`) owns the only debounce timer.
5. Replace the read-only displays in `param-row.tsx` with the new editable controls for float/int rows. Wire `onSpecChange` to fire on every change; wire `onBlurFlush` to bubble up to `<SearchSpaceBuilder>` via a new prop callback.
6. Add the stash invalidation effects in `index.tsx`, **gated on a builder-write-source flag** so the builder's own writes (debounced AND synchronous blur-flush) don't clobber the stash they just populated:
   - Add `lastBuilderWriteRef: useRef<string | null>(null)`.
   - Centralize **every** builder→parent write through a single helper `emitBuilderWrite(canonicalJson: string): void` defined inside `<SearchSpaceBuilder>`. The helper sets `lastBuilderWriteRef.current = canonicalJson` immediately BEFORE calling `props.onChange(canonicalJson)`. Both code paths use this helper:
     - The debounced 200ms timer callback (`<RowNumeric>` onChange → debounce → emitBuilderWrite).
     - The synchronous blur flush (`<RowNumeric>` onBlurFlush → clear debounce timer → emitBuilderWrite).
     - Same for non-numeric edits (type switch, log toggle, categorical chip changes — all go through the same builder-level debounce or no-debounce path).
   - When the `value` prop changes (via React re-render), compare against `lastBuilderWriteRef.current`. If equal → this is a builder-originated round-trip; skip stash invalidation. If different → external (textarea / Undo / auto-fill / template-change-with-textarea-update) write; run invalidation.
   - (a) **Textarea-driven `value` change** (external): diff prior vs current `parseResult.data.params[name]` per row; call `stashClearRow(stashRef.current, name)` for any row whose spec changed externally.
   - (b) **`templateBody` reference change**: call `stashClearAll(stashRef.current)` unconditionally (different template = different param namespace).
   - (c) **Undo path**: naturally falls under (a) — Undo writes to `search_space_text` via `form.setValue` (external from the builder's perspective; `lastBuilderWriteRef.current` won't match), which triggers the diff.
   - (d) **Modal close**: handled by component unmount — `useRef` instance is destroyed automatically; new mount starts with empty stash.
7. Implement row-level error surface: `low >= high` (float) or `low > high` (int) renders the row error string. Error text mirrors Pydantic but is shortened for UI ("low must be < high" / "low must be ≤ high").
8. Write `param-spec-discriminator.parity.test.tsx`. Use `fs.readFileSync` to read `../backend/app/domain/study/search_space.py` (path relative to ui/ working directory; the vitest config's `cwd` is `ui/`, so traverse one up). Extract via `const matches = backendSrc.matchAll(/type:\s*Literal\["([^"]+)"\]/g);`. Assert the resulting array equals `TYPE_VALUES`.
9. Create `create-study-modal.builder-edits.test.tsx` with the FIRST 5 assertions covering Story 2.1's full FR-2 + FR-3 surface: (i) float low/high keystroke edits debounce 200ms and write back to textarea; (ii) `onBlur` flushes synchronously (cancels pending debounce); (iii) type switch float→int→float preserves low/high via stash; (iv) type switch float→categorical→float restores low/high via stash; (v) the 4 stash invalidation rules — (a) textarea-driven row spec change clears that row's stash, (b) templateBody change clears full stash, (c) Undo (simulated via direct `form.setValue('search_space_text', priorText)`) clears the relevant row's stash, (d) modal-close-then-reopen sees an empty stash (via `unmount` + remount). **Add an extra micro-assertion within (i) and (ii): after each builder-originated write (debounced AND blur-flush), perform a type switch and verify the stash entry IS available — this proves the `lastBuilderWriteRef` guard correctly excludes builder writes from invalidation.**
10. Run `pnpm typecheck && pnpm lint && pnpm test`. Fix.

**Definition of Done**

- `simpleFormSpec()` exported from `search-space-defaults.ts`; existing tests pass.
- `param-spec-discriminator.parity.test.tsx` passes against the current backend file.
- AC-2 holds (parity test enforces type values).
- AC-3 holds (float low/high edits write back to textarea within 200ms; **on blur, the write flushes synchronously**).
- Cross-type stash: float→int→float restores the original `{low, high, log}`; vitest assertion in `builder-edits.test.tsx`.
- All 4 stash invalidation rules verified (textarea-driven change, template change, Undo via setValue, modal close via unmount).
- Row error fires on inverted bounds (`low: 10, high: 5`); vitest assertion.
- All existing modal tests pass.

### Story 2.2 — Log toggle with onChange gating

**Outcome:** Float rows expose a `log` checkbox. The check-on transition is gated when `low <= 0` (refused by onChange handler — checkbox is NOT marked native-`disabled`). Row error surfaces when `log: true` AND `low <= 0`.

**FRs:** FR-4 (full); FR-11 (log glossary key already wired in Story 1.2).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/row-log-toggle.tsx` | `<RowLogToggle paramName log low onChange />` — native `<input type="checkbox">` with `aria-disabled` + `title` gating per FR-4. onChange handler refuses false→true when `low <= 0`. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/search-space-builder/param-row.tsx` | For float rows, render `<RowLogToggle>` next to the low/high pair. Wire to `onSpecChange(name, {...spec, log: nextLog})`. Hold per-row `attemptedInvalidLogEnable: boolean` state in `param-row.tsx` (reset to false whenever `low > 0` OR `log === true` after a successful enable); pass to `<RowLogToggle>`. |
| `ui/src/__tests__/components/studies/create-study-modal.builder-edits.test.tsx` | Append the log-toggle assertion (#6) covering THREE cases: (a) clicking checkbox with `low=0` → `log` remains `false`, row error renders ("Log scale requires low > 0"), `aria-disabled="true"` present, native `disabled` absent; (b) raising `low` to `0.1` clears `aria-disabled` and the row error; subsequent click toggles `log: true`; (c) a row that starts `{log: true, low: -1}` (from textarea) renders the row error on render — separate from the blocked-click path. |

**UI element inventory**

| Element type | Label / data | Notes |
|---|---|---|
| `<input type="checkbox" data-testid="cs-row-{name}-log" />` | Float rows only | NO native `disabled`; `aria-disabled="true"` + `title` when low ≤ 0 |
| `<Label htmlFor="cs-row-{name}-log">Log scale</Label>` | adjacent | Existing `<InfoTooltip glossaryKey="study.search_space.log" />` from Story 1.2 |
| Row error (existing slot from Story 2.1) | "Log scale requires low > 0" | Inline `role="alert"` |

**Analogous markup patterns**

```tsx
{/* Pattern: native checkbox with aria-disabled + title — adapted from
    ui/src/components/common/data-table-column-visibility.tsx:61 (native
    `<input type="checkbox">` inside a Popover). Note: NO native `disabled`
    attribute. The parent `<ParamRow>` owns the `attemptedInvalidLogEnable`
    flag so the row error renders after a blocked-click attempt (when
    `log` remains `false` after refusal, the derived state `log:true && low<=0`
    alone wouldn't trigger the error). */}
const lowInvalid = typeof low !== 'number' || low <= 0;
const showRowError =
  (log === true && lowInvalid) ||  // existing-invalid-state case
  attemptedInvalidLogEnable;        // blocked-click case
<div className="flex items-center gap-2">
  <input
    id={`cs-row-${paramName}-log`}
    data-testid={`cs-row-${paramName}-log`}
    type="checkbox"
    checked={log === true}
    aria-disabled={lowInvalid || undefined}
    title={lowInvalid ? 'Log scale requires low > 0' : undefined}
    onChange={(e) => {
      const next = e.target.checked;
      if (next && lowInvalid) {
        // Refuse the false→true transition; row error surfaces via the flag.
        onAttemptedInvalidLogEnable();  // parent sets attemptedInvalidLogEnable=true
        return;
      }
      // Valid transition — clear the flag and propagate.
      onClearAttemptedInvalidLogEnable();
      onChange({ log: next });
    }}
  />
  <Label htmlFor={`cs-row-${paramName}-log`}>Log scale</Label>
  <InfoTooltip glossaryKey="study.search_space.log" />
</div>
```

**Tasks**

1. Create `row-log-toggle.tsx` accepting `{ paramName, log, low, attemptedInvalidLogEnable, onAttemptedInvalidLogEnable, onClearAttemptedInvalidLogEnable, onChange }` props.
2. Wire into `param-row.tsx` for float rows only. Add `attemptedInvalidLogEnable` local `useState<boolean>(false)` per row; auto-clear it when `low > 0` (via `useEffect` keyed on `low`).
3. Implement the onChange gating: refuse false→true when low ≤ 0 (call `onAttemptedInvalidLogEnable()` instead of writing); always honor true→false (call `onClearAttemptedInvalidLogEnable()` + propagate the change).
4. Surface row error "Log scale requires low > 0" when EITHER (a) blocked-click flag is true, OR (b) row's stored state is `log: true` AND `low <= 0`.
5. Append assertion #6 to `builder-edits.test.tsx` (3 cases per the Modified files description above): blocked click, subsequent unlock, pre-existing-invalid render.
6. Run tests; fix.

**Definition of Done**

- AC-4 holds: checkbox is NOT `disabled`, has `aria-disabled="true"` + `title="Log scale requires low > 0"` when low ≤ 0; false→true transition refused; true→false always honored; raising low to 0.1 clears `aria-disabled` and unlocks the transition.
- Row error renders on both refused-transition and pre-existing-invalid-state cases.
- All existing modal tests + Story 1.1/1.2/2.1 tests pass.

### Story 2.3 — Categorical chip-input + cardinality counters (per-row + header)

**Outcome:** Categorical rows expose a chip-input that auto-coerces typed values to `string | number | boolean`, allows duplicates per FR-5, and renders the empty-choices row error. Per-row + header cardinality counters render via a new `estimateParamCardinality()` helper. Header counter turns red + identifies max contributor when total > 1e6.

**FRs:** FR-5 (full); FR-6 (full); FR-7 (full); FR-11 (cardinality glossary key already wired in Story 1.2).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/row-categorical.tsx` | `<RowCategorical paramName choices onChange />` — chip input with Enter/comma to add, × to remove. Type-coercion logic inline. No auto-dedup; optional amber UI warning on duplicate adds. |
| `ui/src/components/studies/search-space-builder/cardinality.tsx` | Two exports: `<RowCardinality spec />` (per-row contribution counter) and `<HeaderCardinality space />` (total + cap-warning). Both consume the new `estimateParamCardinality()` helper. |
| `ui/src/__tests__/lib/search-space-defaults.estimateParamCardinality.test.ts` | 6 assertions: float = 100; int = high − low + 1; categorical = choices.length; float with negative low still = 100; int low=high = 1; categorical with single choice = 1. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/search-space-defaults.ts` | Add `export function estimateParamCardinality(spec: ParamSpec): number`. Pure-function extraction from the existing `estimateCardinality()` loop body at [`search-space-defaults.ts:92-104`](../../../../ui/src/lib/search-space-defaults.ts#L92-L104) — refactor `estimateCardinality()` to call `estimateParamCardinality()` per param. Identical math; no behavior change. Add a doc comment marking the extraction. |
| `ui/src/components/studies/search-space-builder/param-row.tsx` | For categorical rows, render `<RowCategorical>`. Render `<RowCardinality>` at the foot of every row regardless of type. |
| `ui/src/components/studies/search-space-builder/index.tsx` | Render `<HeaderCardinality space={normalizedSpace} />` at the top of the rows, where `normalizedSpace = { ...parseResult.data, params: parseResult.data?.params ?? {} }`. This guarantees `<HeaderCardinality>` never receives an undefined `.params` (which would throw inside `estimateCardinality()`'s iteration) — covers the "parseable JSON missing `params` wrapper" edge case from spec §11. Empty `{}` returns cardinality `1` from `estimateCardinality` (the existing `total = 1` initialization). |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | Existing parity test against the shared JSON fixture — verify it still passes after the refactor (the refactor must NOT change `estimateCardinality` math). Augment with a sanity test verifying `estimateCardinality(space) === sum/product of estimateParamCardinality(p)`. |
| `ui/src/__tests__/components/studies/create-study-modal.builder-edits.test.tsx` | Append assertions #7 and #8: (#7) cardinality counter turns red at >1e6, has `aria-invalid="true"`, identifies max contributor; **(#8) the "Next" button (Step 4 → Step 5) remains enabled even when cardinality exceeds 10⁶ — verifying FR-7's warning-only contract.** |

**UI element inventory**

| Element type | Label / data | Notes |
|---|---|---|
| Chip input `<div data-testid="cs-row-{name}-choices">` (categorical only) | Chips render as removable badges + a text input | Enter/comma adds; × on chip removes |
| Coercion: `"true"` → `true` (boolean); `/^-?\d+(\.\d+)?$/` → number; else string | — | Matches `CategoricalParam.choices` accepted types |
| Row error (existing slot) | "choices: at least 1 choice required" | When choices array would empty |
| Per-row cardinality `<span data-testid="cs-row-{name}-cardinality">` | "≈ 100 states" / "{high − low + 1} states" / "{n} states" | with `<InfoTooltip>` |
| Header cardinality `<div data-testid="cs-builder-header-cardinality">` | "Search space: ~{N} combinations (cap: 1,000,000)" | Red + `aria-invalid="true"` at >1e6 |
| Max-contributor hint `<p data-testid="cs-builder-cap-hint">` | "Try narrowing `<name>` — currently {contribution} of {total}" | Only when total > 1e6 |

**Analogous markup patterns**

```tsx
{/* Pattern: chip input — there is no existing chip input in the repo. Build
    from scratch using <Badge> + <Input> + native key handling. Roughly:  */}
const [draft, setDraft] = useState('');
function commit(): void {
  if (draft.trim() === '') return;
  const coerced =
    draft === 'true' ? true :
    draft === 'false' ? false :
    /^-?\d+(\.\d+)?$/.test(draft) ? Number(draft) :
    draft;
  onChange([...choices, coerced]);  // NO dedup — duplicates preserved per FR-5
  setDraft('');
}
return (
  <div data-testid={`cs-row-${paramName}-choices`} className="space-y-2">
    <div className="flex flex-wrap gap-1.5">
      {choices.map((c, idx) => (
        <Badge key={`${idx}-${typeof c}-${String(c)}`} variant="secondary" className="gap-1">
          <span className="font-mono text-xs">{typeof c === 'string' ? c : JSON.stringify(c)}</span>
          <button
            type="button"
            onClick={() => onChange(choices.filter((_, i) => i !== idx))}
            aria-label={`Remove choice ${String(c)}`}
            className="text-muted-foreground hover:text-foreground"
          >×</button>
        </Badge>
      ))}
    </div>
    <Input
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          commit();
        }
      }}
      placeholder="Type a value and press Enter…"
    />
  </div>
);
```

```tsx
{/* Pattern: header counter — adapted from
    ui/src/components/studies/create-study-modal.tsx:557-566 (color flip via Tailwind text-destructive). */}
const total = estimateCardinality(space);
const overCap = total > 1_000_000;
const maxParam = overCap
  ? Object.entries(space.params)
      .map(([name, spec]) => ({ name, contribution: estimateParamCardinality(spec) }))
      .reduce((a, b) => (a.contribution > b.contribution ? a : b))
  : null;
<div className="space-y-1">
  <p
    data-testid="cs-builder-header-cardinality"
    aria-invalid={overCap || undefined}
    className={overCap ? 'text-sm text-destructive font-medium' : 'text-sm text-muted-foreground'}
  >
    Search space: ~{total.toExponential(2)} combinations (cap: 1,000,000)
    <InfoTooltip glossaryKey="study.search_space.cardinality" />
  </p>
  {overCap && maxParam && (
    <p data-testid="cs-builder-cap-hint" className="text-sm text-destructive">
      Try narrowing <code>{maxParam.name}</code> — currently {maxParam.contribution.toLocaleString()} of ~{total.toExponential(2)}
    </p>
  )}
</div>
```

**Tasks**

1. Refactor `ui/src/lib/search-space-defaults.ts`: extract the per-param math from `estimateCardinality()` into a new exported `estimateParamCardinality(spec: ParamSpec): number`. Update `estimateCardinality()` to call the new helper in a `reduce`. Identical math.
2. Write `estimateParamCardinality.test.ts` (6 assertions). Verify existing `search-space-defaults.cardinality.test.ts` still passes (the shared-fixture Python/TS parity invariant).
3. Create `row-categorical.tsx` with chip-input logic. Allow duplicates (no dedup). On duplicate add, render an amber `<p>` warning ("Duplicate value '<v>' — Optuna will treat them as one trial") — but do NOT auto-remove.
4. Create `cardinality.tsx` exporting `<RowCardinality>` + `<HeaderCardinality>`.
5. Wire into `param-row.tsx` (categorical chip input + per-row cardinality counter) and `index.tsx` (header cardinality counter at top of rows).
6. Append assertions #7 + #8 to `builder-edits.test.tsx`: (#7) build a space with 5 floats + 1 int [0, 100,000]; assert the header counter renders `~1.0e15` style text, `aria-invalid="true"` is present, and the max-contributor hint identifies the int row. (#8) In the same fixture, locate the modal's Next button and assert `expect(button).not.toBeDisabled()` — the cardinality cap is warning-only per FR-7; the existing `stepValid(3, ...)` predicate at [`create-study-modal.tsx:330-337`](../../../../ui/src/components/studies/create-study-modal.tsx#L330-L337) only blocks on JSON parse failure.
7. Run tests; fix.

**Definition of Done**

- `estimateParamCardinality` helper exported and tested (6 unit tests).
- `estimateCardinality` returns identical values pre/post refactor — verified by the existing `search-space-defaults.cardinality.test.ts` continuing to pass.
- AC-5 holds: typing `true`/`1`/`AUTO` produces `[true, 1, "AUTO"]`; removing the `1` produces `[true, "AUTO"]`.
- AC-6 holds: 5 floats + 1 int [0, 100,000] → header counter shows ~1.0e15 in red text with `aria-invalid="true"`; max-contributor hint identifies the int row at "100,001 of ~1.0e15"; **AND the Next button remains enabled** (FR-7 warning-only contract).
- Duplicate categorical choices `["AUTO", "AUTO", "BM25"]` round-trip intact via the round-trip test (already a fixture from Story 1.1).
- All existing tests pass.

### Story 2.4 — Non-actionable "Add custom param" affordance

**Outcome:** The disabled-but-focusable "Add custom param" button renders at the foot of the row list (when `templateBody` is resolved). Tooltip + Next.js `<Link>` to `/templates/{template_id}` are keyboard- and screen-reader-discoverable.

**FRs:** FR-10 (full).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/add-custom-param.tsx` | `<AddCustomParam templateId />` — focusable button (`aria-disabled="true"`, NO native `disabled`) with adjacent tooltip + `<Link>`. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/search-space-builder/index.tsx` | Render `<AddCustomParam templateId={templateId} />` at the foot of the rows when **both** `templateBody !== null` and `templateId !== undefined`. Uses the dedicated `templateId` prop on `<SearchSpaceBuilder>` (NOT `templateBody.id` — `templateId` is the canonical form-state value the user selected on Step 3). Suppress when either is missing (transient/404 fetch state per FR-10 + AC-11). |

**UI element inventory**

| Element type | Label / data | Notes |
|---|---|---|
| `<button type="button" data-testid="cs-add-custom-param" aria-disabled="true">` | "Add custom param" | NO native `disabled`; click opens the Popover (no other side effect) |
| `<PopoverContent>` | "Tunable params come from the template's `declared_params`. To tune a new one, edit the template." | shadcn `<Popover>` — chosen over `<Tooltip>` because Popover is designed for keyboard-interactive content (Tab/Enter chain works correctly with focusable children) |
| `<Link href="/templates/{template_id}" data-testid="cs-row-add-custom-link">` | "Edit template" | Inside the PopoverContent; focusable + clickable via Tab/Enter |

**Analogous markup patterns**

```tsx
{/* Pattern: focusable aria-disabled button as Popover trigger — Popover
    (NOT Tooltip) is the right primitive because PopoverContent is designed
    to hold interactive focusable children (per @radix-ui/react-popover docs).
    Spec FR-10/AC-8 require the surface to appear on hover OR focus — Radix
    Popover's default trigger is click, so we drive `open` via a controlled
    state hook to satisfy hover + focus contracts. */}
const [popoverOpen, setPopoverOpen] = useState(false);

<Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
  <PopoverTrigger asChild>
    <button
      type="button"
      data-testid="cs-add-custom-param"
      aria-disabled="true"
      onClick={(e) => e.preventDefault()}
      onMouseEnter={() => setPopoverOpen(true)}
      onMouseLeave={(e) => {
        // Only close if focus didn't move into the popover content
        if (!e.currentTarget.contains(document.activeElement)) {
          setPopoverOpen(false);
        }
      }}
      onFocus={() => setPopoverOpen(true)}
      onBlur={(e) => {
        // Close only if focus leaves the trigger AND its popover content;
        // relatedTarget will be the "Edit template" link if Tab moved focus there.
        const next = e.relatedTarget as HTMLElement | null;
        if (!next || !next.closest('[data-radix-popper-content-wrapper]')) {
          setPopoverOpen(false);
        }
      }}
      className="text-sm text-muted-foreground border border-dashed border-border rounded px-3 py-1.5 hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      + Add custom param
    </button>
  </PopoverTrigger>
  <PopoverContent
    className="max-w-xs space-y-2"
    side="top"
    align="start"
    onMouseEnter={() => setPopoverOpen(true)}
    onMouseLeave={() => setPopoverOpen(false)}
  >
    <p className="text-sm">
      Tunable params come from the template's <code>declared_params</code>. To tune a new one, edit the template.
    </p>
    <Link
      href={`/templates/${templateId}`}
      data-testid="cs-row-add-custom-link"
      className="text-sm text-primary underline inline-block"
      onBlur={() => setPopoverOpen(false)}
    >
      Edit template
    </Link>
  </PopoverContent>
</Popover>
```

**Tasks**

1. Create `add-custom-param.tsx` with the controlled-Popover hover/focus pattern from the analogous markup above.
2. Wire into `index.tsx` — render only when BOTH `templateBody !== null` AND `templateId !== undefined`. (The dedicated `templateId` prop on `<SearchSpaceBuilder>` carries the canonical form value.)
3. Add component test inside `create-study-modal.builder-rendering.test.tsx` (extend the file from Story 1.2 with 3 more assertions): button has `aria-disabled="true"` AND NO native `disabled`; "Edit template" link href is `/templates/<id>` and is keyboard-reachable via Tab from the trigger button; affordance is suppressed when `templateBody === null` **OR** `templateId === undefined`.
4. Run tests; fix.

**Definition of Done**

- AC-8 holds: button is focusable, `aria-disabled="true"`, no native `disabled`, tooltip + link render on hover/focus.
- AC-11 holds: `templateBody === null` → no `[data-testid="cs-add-custom-param"]` in DOM; only the existing Retry block at `cs-template-retry` is rendered as today.
- All existing tests pass.

**Epic 2 gate (hard stop):** Stories 2.1–2.4 land. `pnpm test ui/src/__tests__/components/studies/search-space-builder/ ui/src/__tests__/components/studies/create-study-modal.builder-*.test.tsx ui/src/__tests__/lib/search-space-defaults.estimateParamCardinality.test.ts` exits 0.

---

## Epic 3 — Responsive split/tab layout

**Goal:** integrate the builder into a responsive layout — split view on ≥1024px, tab toggle on <1024px. The textarea stays in the DOM at every viewport (CSS `display: none` on inactive tab, NOT conditional rendering).

**Epic gate:** Story 3.1 lands; `create-study-modal.builder-textarea-roundtrip.test.tsx` passes (4 assertions).

### Story 3.1 — Split-view (desktop) / tab-view (narrow viewport) integration

**Outcome:** at ≥1024px, builder appears LEFT and textarea RIGHT under `lg:grid-cols-2`. Below 1024px, a "Builder | JSON" tab toggle renders; builder is active by default. The textarea (`data-testid="cs-search-space"`) remains in the DOM at every viewport — `hidden` (CSS) on inactive tab, not unmounted — so React Hook Form's `register` stays stable.

**FRs:** FR-8 (full).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/responsive-layout.tsx` | `<ResponsiveLayout builder textarea />` — renders both children in a `lg:grid-cols-2` wrapper. Below `lg:`, renders a tab toggle; the inactive tab's child gets `className="hidden"`. Uses Tailwind responsive classes; no JS viewport detection. |
| `ui/src/__tests__/components/studies/create-study-modal.builder-textarea-roundtrip.test.tsx` | 4 assertions: textarea remains in DOM at all viewport sizes (via `getByTestId('cs-search-space')` always resolving); tab toggle hides/shows surfaces via CSS class (verify `className` contains `hidden`); textarea keystroke updates builder rows (Story 1.1 round-trip behavior; reverify in modal context); malformed JSON keystroke switches builder to parse-error placeholder. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Wrap the Story 1.1 inline-rendered `<SearchSpaceBuilder>` + the existing `<Textarea>` in `<ResponsiveLayout>`. Move the existing tooltip + textarea (lines 537-553) into the layout's textarea slot. Preserve all existing test IDs + ARIA attributes. |

**UI element inventory**

| Element type | Label / data | Notes |
|---|---|---|
| `<div className="grid gap-4 lg:grid-cols-2">` wrapper | Holds builder slot + textarea slot | Single-column on <1024px |
| Tab toggle (visible <1024px only via `lg:hidden`) | "Builder | JSON" buttons | Active state stored in a local `useState<'builder' \| 'json'>('builder')`; persists ONLY for the mounted modal session |
| Builder slot | Always in DOM; `className="hidden"` when narrow + JSON tab active | |
| Textarea slot | Always in DOM; `className="hidden"` when narrow + Builder tab active | Critical — preserves React Hook Form `register` |

**State dependency analysis**

- `<ResponsiveLayout>` owns the tab state (`activeTab: 'builder' | 'json'`). Local `useState`; never persisted to the form, localStorage, or React state outside the modal.
- Tab state resets to `'builder'` on every modal mount (per spec §4 anti-pattern: "Do not persist builder UI state ... across modal closes").
- Textarea `data-testid="cs-search-space"` stays the same. Existing modal tests' `getByTestId('cs-search-space')` queries continue to resolve.

**Analogous markup patterns**

```tsx
{/* Pattern: responsive grid with Tailwind — adapted from
    ui/src/components/studies/digest-panel.tsx:56 (grid gap-6 md:grid-cols-2). */}
const [activeTab, setActiveTab] = useState<'builder' | 'json'>('builder');
<div className="space-y-3">
  {/* Tab toggle: only visible <1024px */}
  <div className="lg:hidden flex gap-2 border-b border-border" role="tablist">
    <button
      type="button"
      role="tab"
      aria-selected={activeTab === 'builder'}
      onClick={() => setActiveTab('builder')}
      className={activeTab === 'builder' ? 'border-b-2 border-primary px-3 py-1.5' : 'px-3 py-1.5 text-muted-foreground'}
    >
      Builder
    </button>
    <button
      type="button"
      role="tab"
      aria-selected={activeTab === 'json'}
      onClick={() => setActiveTab('json')}
      className={activeTab === 'json' ? 'border-b-2 border-primary px-3 py-1.5' : 'px-3 py-1.5 text-muted-foreground'}
    >
      JSON
    </button>
  </div>
  {/* Split: visible side-by-side at ≥1024px; tabbed below. The `hidden`
      class on inactive tabs is CSS-only — keeps the textarea in the DOM. */}
  <div className="grid gap-4 lg:grid-cols-2">
    <div className={activeTab === 'json' ? 'hidden lg:block' : 'lg:block'}>{builder}</div>
    <div className={activeTab === 'builder' ? 'hidden lg:block' : 'lg:block'}>{textarea}</div>
  </div>
</div>
```

**Tasks**

1. Create `responsive-layout.tsx`.
2. Refactor `create-study-modal.tsx` Step 4 block: extract the existing tooltip + textarea into a JSX slot, pass to `<ResponsiveLayout>`. Pass `<SearchSpaceBuilder>` as the builder slot. Move single-column inline placement from Story 1.1.
3. Write `builder-textarea-roundtrip.test.tsx` with 4 assertions: (a) at desktop viewport, both `[data-testid="cs-search-space-builder"]` and `[data-testid="cs-search-space"]` resolve; (b) at narrow viewport (use vitest CSS matchers / DOM class checks rather than actual viewport resize — assert `lg:hidden` class is present on the tab toggle); (c) clicking JSON tab adds `hidden` class to builder slot but `cs-search-space` still resolves via `getByTestId`; (d) typing `{not valid}` into the textarea (a) switches the builder to `cs-search-space-builder-parse-error` placeholder IMMEDIATELY (the builder reads on every keystroke), then (b) blurring the textarea fires `handleSearchSpaceBlur` (per [`create-study-modal.tsx:306-309`](../../../../ui/src/components/studies/create-study-modal.tsx#L306-L309)) which surfaces the existing `cs-search-space-error` alert. Asserts BOTH surfaces appear post-blur, satisfying spec AC-12 + the existing parse-error contract.
4. Run tests; fix.

**Definition of Done**

- AC-9 holds: both surfaces visible at desktop; tab toggle present at narrow viewport; textarea always in DOM.
- AC-12 holds: parse-failure switches builder to non-interactive placeholder.
- All 7 existing modal tests continue to pass — verifiable by running `pnpm test ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` and checking exit 0.

**Epic 3 gate:** Story 3.1 lands. Textarea is in the DOM at every viewport; existing tests still resolve `cs-search-space` via `getByTestId`.

---

## Epic 4 — Regression net + e2e + accessibility

**Goal:** lock in the regression net via a real-backend e2e + accessibility test. Final epic before merge.

**Epic gate (hard stop):** Story 4.1 lands. All test layers green (`pnpm test` + `pnpm test:e2e` on the new spec).

### Story 4.1 — Builder a11y + real-backend e2e + final wiring

**Outcome:** new vitest `builder-a11y.test.tsx` asserts the accessibility invariants (Label associations, role="alert" on errors, focusable disabled button); new Playwright `studies-create-builder.spec.ts` walks the full Step-1-to-Step-5 flow against the real backend (no `page.route()` mocking) — seeds a template via `seedFullChain`, navigates to `/studies`, opens the modal, drives the builder to set `high = 15` on the `boost` float, submits, and asserts the study is created with the expected `search_space`. `state.md` + `docs/01_architecture/ui-architecture.md` + `docs/05_quality/testing.md` are updated as part of this story (the documentation workstream — finalization). `architecture.md` is **not** updated per spec §15.

**FRs:** AC-7 (regression check via existing round-trip fixtures); AC-10 (regression net for the 7+1 existing tests); AC-11/AC-12 (already validated by Story 3.1, double-checked here); FR-1 / FR-3 in the e2e path.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.builder-a11y.test.tsx` | 4 assertions: every `<Input>` has `<Label htmlFor>`; row errors use `role="alert"`; "Add custom param" button is focusable (no native `disabled`) and `aria-disabled="true"`; "Edit template" link inside its tooltip is keyboard-reachable (focus chain). |
| `ui/tests/e2e/studies-create-builder.spec.ts` | Single real-backend e2e: seed cluster + query-set + template (`declared_params = { boost: 'float' }`) + judgment-list; `page.goto('/studies')`; open modal; walk Steps 1–3 with the EntitySelect-toBeEnabled-then-dispatchEvent pattern from `studies-create-validation.spec.ts:43-59`; on Step 4, use the builder to set `boost.high = 15` via the `cs-row-boost-high` input; assert textarea reflects the change; submit; assert the created study's `search_space.params.boost.high === 15` via `GET /api/v1/studies/{id}`. |

**Modified files**

| File | Change |
|---|---|
| `state.md` | Bump "Recently shipped" to include the search-space builder feature; note that no Alembic head moved. |
| `docs/01_architecture/ui-architecture.md` | Add a new sibling section under "Form dropdown primitive" titled "Search-space builder" with: one paragraph pointing at the new module; a note that the type-selector parity test pattern (read-the-backend-source + grep Literal) is the source-of-truth gate for fields not mirrored in `enums.ts`; cross-link the round-trip parity test. |
| `docs/05_quality/testing.md` | One-line note under "Test layer convention": the search-space builder ships a parity test pattern (grep-the-backend-source) for fields whose wire values live in Pydantic discriminated unions rather than `enums.ts`. |

**Note on `architecture.md`:** spec §15 explicitly says "architecture.md — no change" — the feature adds no new top-level layer, no new service, no new data flow. Skipped per spec.

**UI element inventory**

No new UI elements. This story is test + docs only.

**State dependency analysis**

N/A.

**Tasks**

1. Write `builder-a11y.test.tsx` — 4 assertions per outcome.
2. Write `studies-create-builder.spec.ts` mirroring `studies-create-validation.spec.ts` structure. Reuse the `pickEntity()` helper pattern (toBeEnabled + dispatchEvent('click')). Use `seedFullChain(numQueries=2)` for setup. Submit + GET-back assertion.
3. Update `state.md` per the Modified files table.
4. Update `docs/01_architecture/ui-architecture.md` and `docs/05_quality/testing.md`.
5. Run the full vitest suite + the e2e spec: `cd ui && pnpm test && pnpm test:e2e tests/e2e/studies-create-builder.spec.ts`.
6. Run `pnpm typecheck && pnpm lint && pnpm build` to catch SSR + production-build issues.

**Definition of Done**

- `builder-a11y.test.tsx` passes 4 assertions.
- `studies-create-builder.spec.ts` passes against a real backend (`make up` running).
- `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all exit 0.
- All 7 existing `create-study-modal.*.test.tsx` files + `studies-create-validation.spec.ts` continue to pass without modification (AC-10 regression net).
- `state.md` + `ui-architecture.md` + `testing.md` updated (NOT `architecture.md` per spec §15).

**Epic 4 gate (hard stop / PR gate):** Story 4.1 complete. Full `pnpm test` green. New e2e green against a real backend. All 7 existing modal tests + the existing e2e still pass. Coverage on `ui/src/components/studies/search-space-builder/` ≥ 90% per spec §13.

---

## UI Guidance (plan-level)

This section consolidates UI guidance referenced by individual stories. Read this before starting Story 1.1.

### Reference: current component structure

**[`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)** — 847 LOC modal.

| Section | Lines | Role |
|---|---|---|
| Imports + types | 1-85 | RHF, shadcn primitives, API hooks |
| FormValues + defaults | 85-130 | `search_space_text: '{}'` default at line 124 |
| Queries + state machine | 130-200 | Cluster/template/QuerySet/JudgmentList queries; `templateFetchStatus` |
| Auto-fill effect | 205-259 | Writes starter JSON to `search_space_text` |
| Validation mirror | 265-299 | `validateSearchSpaceAgainstTemplate()` |
| Step transitions + submit | 311-408 | `handleStep4Next()`, `stepValid()`, `onSubmit` |
| Step 0 (cluster + target) | 426-462 | |
| Step 1 (query-set + judgment-list) | 463-495 | |
| Step 2 (template) | 496-529 | `templateHasNoDeclaredParams` block at 516-526 |
| **Step 3 (search space + name)** | **530-594** | **Builder lives here** |
| Step 4 (metric/k/direction + budget) | 595-810 | Existing; untouched |
| Submit footer | 810-847 | |

**Insertion point for `<SearchSpaceBuilder>`** (Story 1.1): inside the `step === 3` block, between the `<Label>Study name</Label>` group (lines 532-535) and the `<Label>Search space (JSON)</Label>` group (lines 536-553). Story 3.1 then wraps the latter group + builder in `<ResponsiveLayout>`.

### Analogous markup patterns

All listed inline in each story's "Analogous markup patterns" section. The shared anchors:

- Row-error pattern: `create-study-modal.tsx:557-566`
- Metric `<Select>` mapped from an `as const` array: `create-study-modal.tsx:603-628`
- Numeric input pair: `create-study-modal.tsx:716-733`
- Native checkbox (no native `disabled`): `data-table-column-visibility.tsx:61`
- Tooltip + glossary key: `<InfoTooltip>` / `<HelpPopover>` patterns at `create-study-modal.tsx:539, 555`
- Responsive grid: `digest-panel.tsx:56` (`grid gap-6 md:grid-cols-2`)

### Layout and structure

- **Step 4 surface** = builder slot + textarea slot, arranged via `<ResponsiveLayout>`:
  - Desktop (≥1024px): split via `lg:grid-cols-2 gap-4`. Builder left, textarea right.
  - Narrow (<1024px): single column. Tab toggle ("Builder | JSON"), Builder active by default. Textarea kept in DOM with CSS `hidden` class on inactive tab.
- **Inside the builder slot:** vertical stack — `<HeaderCardinality>` → `<ParamRow>` × N (Object.keys order) → `<AddCustomParam>` (only when templateBody resolved).
- **Inside each `<ParamRow>`:** vertical stack — name + simple-form badges → `<RowTypeSelector>` → type-specific control (`<RowNumeric>` for float/int with `<RowLogToggle>` for float; `<RowCategorical>` for categorical) → `<RowCardinality>` → optional row error.

### Confirmation/modal dialog pattern

N/A — no new modals. The feature is rendered INSIDE the existing `<Dialog>` from `create-study-modal.tsx:413` and reuses it.

### Visual consistency table

| New UI element | CSS class / pattern source |
|---|---|
| Row container | `rounded-md border border-border bg-card p-3 space-y-2` — adapted from `digest-panel.tsx` card style |
| Name chip | `<Badge variant="outline" className="font-mono text-xs">` — `studies-table.column-config.tsx` badge pattern |
| Simple-form badge | `<Badge variant="secondary" className="text-xs">` — same |
| Row error | `<p role="alert" className="text-sm text-destructive">` — `create-study-modal.tsx:557-566` |
| Header cardinality (normal) | `text-sm text-muted-foreground` |
| Header cardinality (red) | `text-sm text-destructive font-medium` |
| Max-contributor hint | `text-sm text-destructive` |
| Per-row cardinality counter | `text-xs text-muted-foreground` |
| "Add custom param" button | `text-sm text-muted-foreground border border-dashed border-border rounded px-3 py-1.5 hover:bg-muted/30` |
| Tab toggle (narrow viewport) | `flex gap-2 border-b border-border` (container); active tab: `border-b-2 border-primary px-3 py-1.5`; inactive: `px-3 py-1.5 text-muted-foreground` |

### Component composition

| Component | Inline / extracted | Rationale |
|---|---|---|
| `<SearchSpaceBuilder>` | Extracted (`search-space-builder/index.tsx`) | New top-level surface; reused below; owned-state lives here |
| `<ParamRow>` | Extracted | One per declared param; reuses logic across all row types |
| `<RowTypeSelector>` | Extracted | Carries source-of-truth comment + stash logic |
| `<RowNumeric>` | Extracted | Fully controlled; no local debounce; defers timer ownership to `<SearchSpaceBuilder>` per FR-3 |
| `<RowLogToggle>` | Extracted | Float-only; isolation simplifies the onChange-gate logic |
| `<RowCategorical>` | Extracted | Chip input state is local |
| `<RowCardinality>` / `<HeaderCardinality>` | Extracted (`cardinality.tsx`) | Pure presentational; consumes `estimateParamCardinality` helper |
| `<AddCustomParam>` | Extracted | Self-contained tooltip + link |
| `<ResponsiveLayout>` | Extracted | One responsibility: split-vs-tab decision |
| `<BuilderPlaceholder>` | Extracted | One component, multiple variants |

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Type in `cs-row-{name}-low` numeric input | `<RowNumeric>` calls `onChange(nextSpec)` synchronously per keystroke → `<SearchSpaceBuilder>.onSpecChange` builds next `SearchSpaceJson` and schedules a single 200ms debounce → on debounce fire (or earlier `<RowNumeric>` blur → `onBlurFlush`), `form.setValue('search_space_text', stringify(...))` writes synchronously | None |
| Type in textarea | RHF `register` onChange fires → `value` prop updates → `<SearchSpaceBuilder>` re-renders, cancels any pending builder debounced write, re-parses, re-renders rows | None |
| Click type `<Select>` → switch to `int` | `<RowTypeSelector>` stashes prior `FloatSpec` via `stashSet(stashRef.current, paramName, 'float', priorSpec)`, reads `stashGet(stashRef.current, paramName, 'int')` or falls back to `defaultSpecForType('int')` (= `{type: 'int', low: 0, high: 5}`) → calls `onSpecChange` with the new int spec | None |
| Click `log` checkbox while `low <= 0` | onChange handler refuses the false→true transition; sets row error to "Log scale requires low > 0"; `aria-disabled="true"` + `title` remain | None |
| Press Enter in categorical chip input | Coerce typed value → push to `choices` (no dedup) → call `onSpecChange` | None |
| Resize from desktop to narrow viewport mid-edit | Tailwind responsive class flips layout; tab toggle initializes to Builder tab; row state preserved (all derived from `search_space_text`) | None |
| Click JSON tab in narrow viewport | `setActiveTab('json')` → builder slot gets `hidden` class; textarea slot becomes visible | None |
| Click Next on Step 4 | Existing `handleStep4Next()` calls `validateSearchSpaceAgainstTemplate()` (unchanged) → if no error, transition to Step 5 | None until Step 5 submit |
| Click "Add custom param" button | `onClick={(e) => e.preventDefault()}` — no-op | None |
| Press Enter on "Add custom param" button | No-op (aria-disabled focusable button) | None |
| Tab into "Edit template" link inside tooltip + Enter | Next.js `<Link>` navigates to `/templates/{template_id}` | (Next.js client-side route) |

### Handler function patterns

```tsx
// SearchSpaceBuilder.onSpecChange — wired in Story 1.2, fully exercised by Story 2.1
function onSpecChange(paramName: string, nextSpec: ParamSpec | undefined): void {
  if (!parseResult.ok) return;  // can't compose into a malformed object
  const nextParams = { ...parseResult.data.params };
  if (nextSpec === undefined) {
    delete nextParams[paramName];
  } else {
    nextParams[paramName] = nextSpec;
  }
  const next: SearchSpaceJson = { ...parseResult.data, params: nextParams };
  if (debounceRef.current) clearTimeout(debounceRef.current);
  debounceRef.current = setTimeout(() => {
    onChange(stringifySearchSpace(next));
    debounceRef.current = null;
  }, 200);
}

// RowTypeSelector type-switch handler — wired in Story 2.1
// Uses the Map-based stash helpers from `stash.ts` (NOT object indexing)
function handleTypeSwitch(nextType: ParamType): void {
  // Stash prior spec via the Map helper
  if (spec) {
    stashSet(stashRef.current, paramName, spec.type, spec);
  }
  // Restore from stash or fall back to target-type-only defaults
  const stashed = stashGet(stashRef.current, paramName, nextType);
  const nextSpec = stashed ?? defaultSpecForType(nextType);
  onSpecChange(paramName, nextSpec);
}

// RowLogToggle onChange — wired in Story 2.2
function handleLogChange(e: ChangeEvent<HTMLInputElement>): void {
  const next = e.target.checked;
  const lowInvalid = typeof spec.low !== 'number' || spec.low <= 0;
  if (next && lowInvalid) {
    // Refuse the transition; row error renders from the derived rowError prop
    return;
  }
  onSpecChange(paramName, { ...spec, log: next });
}
```

### Information architecture placement

- **Location:** inside the existing create-study modal (`ui/src/components/studies/create-study-modal.tsx`), Step 4 of 5 ("Search space" — modal header at line 416 unchanged).
- **Navigation:** users reach Step 4 by clicking through the wizard from Step 0 (cluster) → Step 1 (query-set / judgment-list) → Step 2 (template) → Step 3 (name + search space). No new top-level routes; no new sidebar entries; no new tabs on the `/studies` page.
- **Order relative to existing elements:** unchanged. Builder + textarea replace the existing single-textarea Step-4 region.
- **Discovery:** identical to today — users reach Step 4 via the wizard. The builder is the new default surface they see when they hit that step.

### Tooltips and contextual help

All tooltip slots already specified in Story 1.2 + spec §11. The tooltip patterns reused:

```tsx
{/* InfoTooltip pattern — from ui/src/components/studies/create-study-modal.tsx:539 */}
<div className="flex items-center gap-1">
  <Label htmlFor="…">…</Label>
  <InfoTooltip glossaryKey="study.search_space.param_spec" />
</div>
```

All three glossary keys (`study.search_space.param_spec`, `.log`, `.cardinality`) are already in [`ui/src/lib/glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94). **No glossary edits** in this plan.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** The builder ADDS a new surface above and beside the existing textarea; the existing textarea remains in the DOM at every viewport and continues to serve all current behaviors. The 7 existing modal tests + `studies-create-validation.spec.ts` are the regression net for unchanged behaviors.

### Client-side persistence

None. The builder uses only React Hook Form state (existing) and component-local `useState` / `useRef` (cleared on modal close). No `localStorage`, no `sessionStorage`.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `ui/src/__tests__/lib/`, `ui/src/__tests__/components/studies/search-space-builder/`
- Scope: pure helpers (`estimateParamCardinality`, `parseSearchSpace`, `stringifySearchSpace`); round-trip parity; type-discriminator parity.
- Tasks:
  - [ ] **Story 1.1**: write `ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx` (11 fixtures)
  - [ ] **Story 2.1**: write `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx` (1 assertion, reads backend source)
  - [ ] **Story 2.3**: write `ui/src/__tests__/lib/search-space-defaults.estimateParamCardinality.test.ts` (6 assertions)
- DoD:
  - [ ] All three test files exit 0 under `pnpm test`
  - [ ] Coverage on the new builder module ≥ 90%

### 3.2 Integration tests
- Location: N/A — no DB-backed workflows touched. The integration layer is exercised exclusively via the e2e (Story 4.1).
- Tasks:
  - [ ] N/A
- DoD:
  - [ ] Explicitly N/A: feature is pure-frontend; integration coverage handled by Story 4.1's real-backend e2e.

### 3.3 Contract tests
- Location: N/A — no new endpoints introduced. Existing contract tests at `backend/tests/contract/test_studies_*.py` continue to cover `POST /api/v1/studies` and its error codes (`INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) without modification.
- Tasks:
  - [ ] N/A
- DoD:
  - [ ] Confirmed existing contract tests still pass under `make test-contract` after the merge.

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- Scope: real-backend single-path happy-path walking Steps 1–4 → builder edit → submit → assert created study's `search_space` field.
- **Rule:** real backend at `http://127.0.0.1:8000`; no `page.route()` mocking; use `seedFullChain()` helper.
- Tasks:
  - [ ] **Story 4.1**: write `ui/tests/e2e/studies-create-builder.spec.ts`
- DoD:
  - [ ] Spec passes under `pnpm test:e2e tests/e2e/studies-create-builder.spec.ts` with a real backend running.

### 3.4-component (component layer)
- Location: `ui/src/__tests__/components/studies/`
- Scope: modal-mounting tests that exercise the builder inside the full CreateStudyModal tree.
- Tasks:
  - [ ] **Story 1.2**: `create-study-modal.builder-rendering.test.tsx` (4 + 2 added by Story 2.4 = 6 total)
  - [ ] **Story 2.1**: `create-study-modal.builder-edits.test.tsx` (5 assertions; Story 2.2 appends #6 = 6; Story 2.3 appends #7 + #8 = 8 total)
  - [ ] **Story 3.1**: `create-study-modal.builder-textarea-roundtrip.test.tsx` (4 assertions)
  - [ ] **Story 4.1**: `create-study-modal.builder-a11y.test.tsx` (4 assertions)
- DoD:
  - [ ] All four component test files exit 0 under `pnpm test`.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | `cs-search-space` textarea references | ~5 | **No change** — split-view keeps the textarea in the DOM; `getByTestId` continues to resolve |
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.test.tsx` | `cs-search-space` content assertions | ~5 | **No change** — auto-fill writes still go to `search_space_text`; builder re-renders from the new string |
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.undo.test.tsx` | Undo toast + `setValue('search_space_text', priorText)` | ~2 | **No change** — undo path still writes to `search_space_text`; builder re-renders |
| `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx` | `cs-search-space-error` assertions | ~3 | **No change** — error surface unchanged; cross-row errors continue to surface in the existing single block |
| `ui/src/__tests__/components/studies/create-study-modal.metric-k.test.tsx` | Step-5 metric/k rendering | ~4 | **No change** — Step 5 untouched |
| `ui/src/__tests__/components/studies/create-study-modal.template-fetch-error.test.tsx` | `cs-template-retry` block | ~2 | **No change** — builder is conditional on `templateBody`; builder renders only the noninteractive placeholder during transient/404 |
| `ui/src/__tests__/components/studies/create-study-modal.zero-declared.test.tsx` | `cs-zero-declared-error` | ~1 | **No change** — gating happens on Step 3 transition; builder never has to render in this state |
| `ui/src/__tests__/lib/search-space-defaults.test.ts` | `buildStarterSearchSpace` + `HEURISTIC_RULES` parity | ~12 | **No change** — module is unchanged except for the new `estimateParamCardinality()` export |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | Python ↔ TS parity via shared JSON fixture | ~1 | **Verify still passes** post-refactor (Story 2.3); the refactor extracts the per-param math but must NOT change `estimateCardinality()` totals |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | Lint guard scanning inline `<SelectItem value="<literal>">` against `enums.ts` | full-tree scan | **No change** — `ParamSpec.type` values (`'float'`/`'int'`/`'categorical'`) are NOT in `enums.ts`, so the lint guard does not flag them. The parity test (Story 2.1) is the dedicated source-of-truth gate |
| `ui/tests/e2e/studies-create-validation.spec.ts` | Real-backend walk through Steps 1–3 → Step 4 auto-fill → unknown-param typo via textarea | ~2 | **No change** — typing into `cs-search-space` textarea still drives validation; the builder mirrors it on every keystroke |

### 3.5 Migration verification
- [ ] N/A — no schema changes.

### 3.6 CI gates
- [ ] `cd ui && pnpm typecheck` exits 0
- [ ] `cd ui && pnpm lint` exits 0
- [ ] `cd ui && pnpm test` exits 0 (all unit + component tests)
- [ ] `cd ui && pnpm build` exits 0 (SSR + production build sanity)
- [ ] `cd ui && pnpm test:e2e tests/e2e/studies-create-builder.spec.ts` exits 0 with a real backend
- [ ] CI `pr.yml` workflow exits 0

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** (Story 4.1):
- [ ] "Recently shipped" updated with PR # + feature name + 1-line summary
- [ ] "Currently in flight" cleared of the in-progress entry that this feature replaces
- [ ] No Alembic head bump (no migration)

**`architecture.md`** (Story 4.1):
- [ ] No change. Spec §15 explicitly states no architecture.md update; the feature is contained inside an existing component and adds no new top-level layer.

**`CLAUDE.md`**:
- [ ] No change. The existing "Enumerated Value Contract Discipline" already covers the source-of-truth-comment pattern; the parity test (Story 2.1) is a concrete example of an enum NOT in `enums.ts` — the convention is unchanged.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] **Story 4.1**: update [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — add a new section titled "Search-space builder" as a sibling of "Form dropdown primitive" and "DataTable primitive". Content: one paragraph linking to the new module; a paragraph documenting the parity-test pattern (grep-the-backend-source) for fields not mirrored in `enums.ts`; cross-link to `param-spec-discriminator.parity.test.tsx`.

### 4.2 Product docs (`docs/02_product`)

- [ ] **Finalization** (after PR merge): move `docs/02_product/planned_features/feat_create_study_search_space_builder/` under `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_create_study_search_space_builder/` per the impl-execute skill's standard finalization step.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No new runbook needed. The feature is pure-frontend with no operational surface.

### 4.4 Security docs (`docs/04_security`)

- [ ] No change. No new auth/data path.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] **Story 4.1**: add a one-line note to [`docs/05_quality/testing.md`](../../../05_quality/testing.md) under "Test layer convention" — the parity-test pattern (grep-the-backend-source) is the source-of-truth gate for wire values living in Pydantic discriminated unions rather than `enums.ts`. Reference the new `param-spec-discriminator.parity.test.tsx` as the canonical first instance.

**Documentation DoD**
- [ ] `state.md`, `ui-architecture.md`, `testing.md` consistent with shipped behavior (`architecture.md` intentionally unchanged per spec §15)
- [ ] Feature folder moved under `implemented_features/` post-merge (impl-execute Step 7 standard)

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Extract the per-param math from `estimateCardinality()` into a pure-function `estimateParamCardinality()` helper (Story 2.3). This is the only refactor; rest of the feature is greenfield additions.

### 5.2 Planned refactor tasks

- [ ] **Story 2.3** — extract `estimateParamCardinality(spec: ParamSpec): number` from [`ui/src/lib/search-space-defaults.ts:92-104`](../../../../ui/src/lib/search-space-defaults.ts#L92-L104). Refactor `estimateCardinality()` to call the new helper. Identical math. No behavior change.

### 5.3 Refactor guardrails

- [ ] **Behavioral parity proven by tests:** existing `search-space-defaults.cardinality.test.ts` (Python ↔ TS shared JSON fixture parity) MUST continue to pass post-refactor. If it fails, the refactor changed the math — revert and fix.
- [ ] **Lint/typecheck remain green** after the refactor.
- [ ] **No expansion of product scope** — `estimateCardinality()` keeps its public signature; new helper is additional, not replacement.
- [ ] **Track discovered debt** — none expected; pure extraction.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `chore_create_study_wizard_polish` (PR #157 `075c46b`) | Story 1.1 | **Implemented** (merged 2026-05-20) | Hard block — without it, no `HEURISTIC_RULES`, no `buildStarterSearchSpace`, no `estimateCardinality`, no glossary subkeys |
| `chore_extract_shadcn_select_test_mock` | Stories 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 4.1 (all modal-mounting tests) | **Implemented** (helper at `ui/src/__tests__/helpers/shadcn-select-mock.tsx`) | Medium block — without it, modal tests crash on Radix `patchedFocus` infinite recursion |
| Existing `<Textarea>`, `<Input>`, `<Select>`, `<Label>`, `<Badge>`, `<Tooltip>`, `<Popover>`, `<InfoTooltip>`, `<HelpPopover>` primitives | All frontend stories | **Implemented** | No risk |
| Backend `search_space.py` discriminated union | Story 2.1 parity test | **Implemented** (the spec validates it lives at lines 83-89) | Parity test would fail if backend file were renamed/restructured — the test is the deliberate canary |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Single 200ms builder debounce + synchronous onBlur flush could cause test timing flakiness | Low | Low | Story 2.1 component tests use `vi.useFakeTimers()` + explicit `vi.advanceTimersByTime(250)` to drain the single timer; blur-flush tests assert synchronous behavior with no timer advance needed |
| Stash invalidation effect in `index.tsx` could fire infinitely if not stable-ref-keyed | Low | Medium | Stash invalidation effect's deps array is `[parseResult, templateBody]` — both are derived (parseResult via `useMemo`) or stable (templateBody is the same object until the query refetches), so no infinite loop. Vitest assertion at Story 2.1 covers stable behavior with rapid textarea edits |
| Tab toggle (Story 3.1) using CSS `hidden` instead of conditional rendering could trip a future a11y audit (screen readers vary on hidden-but-rendered) | Low | Low | The pattern matches `data-table-column-visibility.tsx`'s approach and is explicitly required by FR-8 to keep the textarea's RHF `register` stable. Documented in spec §4 and AC-9. If a screen-reader audit ever flags it, the fix is `display: none` (already what `hidden` resolves to) + `aria-hidden="true"` on the inactive tab; that's a minor follow-up, not a blocker |
| Parity test at Story 2.1 brittle to whitespace changes in `search_space.py` | Low | Medium | Test uses `matchAll(/type:\s*Literal\["([^"]+)"\]/g)` with flexible whitespace — only the Literal contents need to be stable. If the backend rewrites to a non-Literal pattern (e.g., StrEnum), the test fails fast and the spec discussion happens |
| Tailwind `lg:` breakpoint = 1024 px (project uses Tailwind 4 CSS-first config); a future override of the breakpoint via `@theme` would silently shift the responsive cutover | Low | Low | The CLAUDE.md "Tailwind 4 (CSS-first config)" note documents the default; no override exists today. If one is added later, the `lg:` semantics carry through |
| Builder render time exceeds 16 ms with ≥ 20 rows | Low | Low | Spec §13 caps at 16 ms for ≤ 20 rows; reach via stable `paramName` keys + `useMemo` on parseResult. Story 4.1 a11y test doesn't measure perf; future tickets can add a perf budget if regressions surface |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Textarea contains unparseable JSON | User typed an obvious syntax error | Builder renders `<BuilderPlaceholder variant="parse-error">`; existing `cs-search-space-error` surfaces the JS parse exception; Next stays blocked by existing `stepValid(3, ...)` predicate | User fixes the JSON or undoes the edit |
| Parseable JSON missing `params` wrapper | User pasted a half-formed object | Builder renders declared-param rows in "empty/unset" state + inline hint "Wrap your JSON in a `params:` object — the rows above are empty because no `params` key was found"; existing single error block stays empty (per `validateSearchSpaceAgainstTemplate` short-circuit at line 274) | User wraps in `params:{...}` |
| Cardinality exceeds 1 × 10⁶ | User widened bounds aggressively | Header counter turns red + `aria-invalid="true"`; max-contributor hint identifies the row; Next button **stays enabled**; server-side `_check_cardinality` rejects on submit via existing `INVALID_SEARCH_SPACE` envelope | User narrows; or user submits anyway and gets the existing 400 error |
| Template fetch transient failure | Network blip or backend hiccup | Builder renders single non-interactive placeholder "Couldn't load the template. Server-side validation will still catch typos on submit."; existing Retry button at `cs-template-retry` renders; textarea remains editable | User clicks Retry |
| Template fetch 404 (template deleted mid-wizard) | Backend returned 404 | Existing flow handles: bumps user back to Step 3; existing `templateFetchStatus === '404'` block fires; builder never renders | Existing recovery |
| User toggles type via the selector and immediately types in the textarea before debounce fires | Race condition | Textarea-driven change wins (last-edit-wins per FR-9); builder's pending debounced write is cancelled; row re-renders from the new textarea state | No user action needed |
| Stash entry from prior modal-open session leaks into a new session | Race condition | Cannot happen — `stashRef` is `useRef<{}>()` inside `<SearchSpaceBuilder>`, which unmounts when the modal closes (per CreateStudyModal's `<Dialog>` tree). New mount = fresh ref | Verified by Story 2.1 vitest assertion: open modal → switch types → close modal → reopen → verify stash is empty (asserted via the absence of the prior float spec on re-switch) |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Stories 1.1, 1.2) — scaffolding + round-trip discipline. Hard prerequisite for everything else.
2. **Epic 2** (Stories 2.1 → 2.2 → 2.3 → 2.4) — strict sequential. 2.2 depends on 2.1 (param-row owns the log toggle slot); 2.3 depends on 2.1 (chip input lives in param-row); 2.4 is standalone but logically follows 2.3 (rendered at the foot of the rows).
3. **Epic 3** (Story 3.1) — responsive integration. Depends on builder being feature-complete from Epic 2.
4. **Epic 4** (Story 4.1) — a11y + e2e + docs. Last.

### Parallelization opportunities

- Stories 2.2 (log toggle) and 2.4 (add-custom-param button) are largely independent of each other. Could be parallelized if two engineers were on the project. **For single-agent execution: sequential is simpler — no merge conflicts on `param-row.tsx`.**
- The `estimateParamCardinality` refactor (Story 2.3 task 1) can be done first and merged separately if desired; it's a pure-function extraction with zero behavior change. **For this plan: keep it inside Story 2.3 to avoid a separate PR.**

## 8) Rollout and cutover plan

- **Rollout stages:** N/A. MVP1 is local-only single-tenant; no staged rollout, no canary, no flag.
- **Feature flag strategy:** none. The builder ships as the default Step-4 surface on merge.
- **Migration/cutover steps:** none — zero schema changes.
- **Reconciliation/repair strategy:** none — no external systems involved.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — Builder shell + bidirectional round-trip
- [ ] Story 1.2 — Per-row rendering + tooltip slots
- [ ] Story 2.1 — Type selector + spinners + stash + parity test
- [ ] Story 2.2 — Log toggle
- [ ] Story 2.3 — Categorical chip input + cardinality counters
- [ ] Story 2.4 — Add-custom-param affordance
- [ ] Story 3.1 — Responsive split/tab layout
- [ ] Story 4.1 — A11y + e2e + docs

### Blocked items
- (none)

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] UI element inventory implemented
- [ ] Tests added/updated per the story's DoD
- [ ] Commands executed and passed:
    - [ ] `cd ui && pnpm typecheck`
    - [ ] `cd ui && pnpm lint`
    - [ ] `cd ui && pnpm test <story-specific path>`
    - [ ] `cd ui && pnpm test:e2e tests/e2e/studies-create-builder.spec.ts` (Story 4.1 only)
    - [ ] `cd ui && pnpm build` (Story 4.1 only)
- [ ] N/A: migration round-trip evidence (no schema changes)
- [ ] Related docs/checklists updated in same PR when behavior changed (Story 4.1)

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** 0 endpoints in spec §8.1 → 0 endpoints in plan. ✅
2. **Spec ↔ plan error code coverage:** 0 new error codes in spec §8.5 → 0 new error codes in plan. ✅ (existing `INVALID_SEARCH_SPACE` etc. still covered by existing contract tests, per §3.3.)
3. **Spec ↔ plan FR coverage:** 11 FRs in spec → 11 rows in §1 traceability table → every FR assigned to at least one story. ✅
4. **Story internal consistency:**
   - File ownership: each new file is owned by exactly one story (verified by reading the New files tables across all stories — no overlaps).
   - Modified files: `create-study-modal.tsx` modified by Stories 1.1 + 3.1 only (insertion in 1.1, wrap in `<ResponsiveLayout>` in 3.1); `param-row.tsx` modified by Stories 2.1, 2.2, 2.3 (sequential additions); `search-space-defaults.ts` modified by Story 2.3 only.
   - DoD references the correct ACs: AC-1 (Story 1.2), AC-2 (Story 2.1), AC-3 (Story 2.1), AC-4 (Story 2.2), AC-5 (Story 2.3), AC-6 (Story 2.3), AC-7 (Story 1.1 round-trip + Story 4.1 e2e), AC-8 (Story 2.4), AC-9 (Story 3.1), AC-10 (Stories 1.1/4.1 regression-net), AC-11 (Story 2.4 — invariant; Story 3.1 — verification), AC-12 (Story 3.1).
5. **Test file count:** 5 unit/component test files (round-trip, param-spec-discriminator, estimateParamCardinality, builder-rendering, builder-edits) + 2 more component test files (builder-textarea-roundtrip, builder-a11y) + 1 e2e file. Total: 8 new test files. Each is assigned to exactly one story.
6. **Gate arithmetic:** Epic 1 gate references 2 stories + 2 test files; Epic 2 gate references 4 stories + 3 test files; Epic 3 gate references 1 story + 1 test file; Epic 4 gate references 1 story + 2 test files. Arithmetic verified.
7. **Open questions resolved:** spec §19 has zero open questions (all 4 locked to defaults during spec drafting). ✅
8. **Frontend UI Guidance completeness:** plan-level "UI Guidance" section above includes Insertion point ✅, Analogous markup patterns ✅, Layout and structure ✅, Confirmation/modal dialog pattern (N/A — documented) ✅, Visual consistency table ✅, Component composition ✅, Interaction behavior table ✅, Handler function patterns ✅, Information architecture placement ✅, Tooltips and contextual help ✅, Legacy behavior parity (explicit N/A statement) ✅.
9. **Persistence scope:** None (no `localStorage` / `sessionStorage`).
10. **Enumerated value contract verification:** §7.4 of the spec has the single enumerated-value table (`ParamSpec.type`); the plan's Story 2.1 enumerates the same three values + cites the backend source-of-truth file + ships the parity test as the gate. ✅
11. **Audit-event coverage:** N/A — MVP1, no `audit_log` table; spec §6 explicitly states N/A.

This plan is execution-ready.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories (11 FRs across 8 stories).
- [x] Every story includes New files, Modified files, UI element inventory, Tasks, DoD.
- [x] Test layers explicitly scoped (Unit, Component, E2E; Integration + Contract explicit N/A).
- [x] Documentation updates planned (state.md, ui-architecture.md, testing.md; architecture.md intentionally unchanged per spec §15).
- [x] Lean refactor scope explicit (`estimateParamCardinality` extraction in Story 2.3).
- [x] Phase/epic gates measurable (vitest exit codes + e2e exit codes).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
