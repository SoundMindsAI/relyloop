# Implementation Plan — Study Default Stop Conditions

**Date:** 2026-05-23
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](./feature_spec.md) (Approved — 3 GPT-5.5 cycles)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to specific FR IDs from `feature_spec.md` §7.
- Single epic, 5 stories, strict sequencing (glossary + prompt → form → UI selector → tests). Each story is a single commit boundary.
- The whole plan is frontend + 1 prompt file. No backend code, no migration, no new endpoint.
- Vitest is the only test surface (per spec §14). The button-group's mechanics are deterministic and fast at the vitest layer; an E2E case would only duplicate coverage.
- Don't fight the conventions: the wizard already uses `react-hook-form`, shadcn `Button`, and `InfoTooltip` + `glossary.ts` for tooltip text. Build on these.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (form pre-fill 200) | Story 1.3 | One-line edit to `useForm` `defaultValues` block |
| FR-2 (button-group selector + group label) | Story 1.4 | Plan-level UI Guidance specifies analogous JSX |
| FR-3 (preset value mapping + `time_budget_min` clearing) | Story 1.4 | Locked-decision write rules per spec §7 FR-3 table |
| FR-4 (form-state transitions) | Story 1.4 | Manual-edit watcher + modal-open reset wiring |
| FR-5 (refreshed glossary `study.max_trials` + `study.time_budget_min`) | Story 1.1 | Pure text edits |
| FR-6 (system prompt update) | Story 1.2 | Two text edits to `prompts/orchestrator.system.md` |
| FR-7 (tooltip + preset description copy) | Story 1.4 | Bundled with the selector UI; references Story 1.1's `study.preset` key |
| FR-8 (new `study.preset` glossary entry) | Story 1.1 | New `long`/`short`/`ariaLabel` entry |
| FR-9 (vitest coverage, ≥10 cases) | Story 1.5 | All AC-1..AC-10 covered |

No deferred phases — single-phase plan covers the spec in full (spec §3 "Phase boundaries (single-phase)").

## 2) Delivery structure

Conventions for this plan:

- All frontend changes use `react-hook-form` v7 patterns: `form.setValue(name, value, { shouldDirty: true })` for programmatic writes; `form.watch(name)` for derived state in `useEffect`.
- Tooltips use `<InfoTooltip glossaryKey="<key>" />` exclusively — no inline text. Every `<InfoTooltip>` traces back to a key in `ui/src/lib/glossary.ts`.
- Source-of-truth comments: when an array of wire-shaped values lives in a frontend file, a `// Values must match <backend/path>` comment precedes it. For this feature there are NO wire-shaped enum arrays (preset values are frontend-only) — so no source-of-truth comment is required for the preset constants themselves; however, the `PRESET_VALUES` constant gets a comment marking the values as frontend-only state.
- TypeScript: prefer `as const` literals for fixed-set string unions (e.g., `const PRESET_VALUES = ['focused', 'standard', 'deep', 'custom'] as const`).
- Test file naming: `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` matches the existing `create-study-modal.<aspect>.test.tsx` convention (see siblings `*.client-validation.test.tsx`, `*.demo-suffix.test.tsx`, `*.builder-a11y.test.tsx`).

### AI Agent Execution Protocol

0. Read `architecture.md`, `state.md`, `feature_spec.md` (already in spec-gen output context).
1. Verify story scope (Outcome + Files + Tasks + DoD).
2. Edit the file listed in the story's "Modified files" table.
3. Run `npx tsc --noEmit` after each frontend edit. Run targeted vitest after Story 1.5 lands.
4. Commit with `feat(<scope>): <subject> (Story X.Y)`.
5. After the final story, no `state.md` / `architecture.md` update needed — this is operator-facing UX polish without architectural impact (the `/impl-execute` post-impl gate may still touch `state.md` with a post-merge summary; that's separate from this plan).

---

## Epic 1 — Wizard preset selector + recommended defaults

### Story 1.1 — Glossary copy refresh + new `study.preset` entry
**Outcome:** The `study.max_trials` and `study.time_budget_min` glossary entries reflect the new dimensionality-keyed framing; a new `study.preset` entry provides the canonical description of the preset selector.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Refresh `study.max_trials` (line 160) + `study.time_budget_min` (line 165); insert new `study.preset` entry after `study.time_budget_min`. |

**Tasks**

1. Open `ui/src/lib/glossary.ts`. Locate the `study.max_trials` entry (line 160) and replace its `short` + add a `long` per spec §7 FR-5:
   - `short: 'Total trials to run before stopping. Sized by your search-space dimensionality: ~50 for 1–2 params, 200 for 3–5 params (typical), 500–1000 for 6+ params.'`
   - `long: 'TPE\'s diminishing returns kick in past these counts. With default parallelism=4 and ~1s/trial cost on a small query set, 200 trials completes in under a minute; on a managed cluster with a large query set it\'s more like 25 minutes (wall-clock estimates measured against the local dev stack — production clusters may vary).'`
2. Refresh `study.time_budget_min` (line 165) per spec §7 FR-5:
   - `short: 'Wall-clock safety cap, in minutes. Optional. Set this only if you want a hard ceiling on a slow cluster.'`
   - `long: 'Trials in RelyLoop are typically cheap (subsecond against local stacks, seconds against managed clusters), so the binding stop is almost always max_trials. Use this as a circuit breaker on managed clusters where per-trial cost might unexpectedly balloon.'`
3. Insert a new `study.preset` entry directly after `study.time_budget_min` per spec §7 FR-8:
   ```typescript
   'study.preset': {
     short:
       'Sized stop-condition recommendation matching your search-space dimensionality.',
     long:
       'Focused (50 trials) — 1–2 params; smallest preset where MedianPruner activates (avoids the <50 NopPruner threshold). Standard (200) — 3–5 params, the typical case. Deep (1000 + 8h cap) — 6+ params, complex tuning. Custom — preserves manual edits.',
     ariaLabel: 'More information about study presets',
   },
   ```

**Definition of Done (DoD)**
- All three glossary entries (`study.max_trials`, `study.time_budget_min`, `study.preset`) carry the new copy from spec §7 FR-5 + FR-8.
- `npx tsc --noEmit` passes (the glossary export type may have changed shape — confirm).
- `npx vitest run --no-coverage ui/src/__tests__/lib/glossary*.test.ts` (if a test file exists for glossary keys) still passes; if no such test exists, no new test added by this story (Story 1.5 covers tooltip-rendered-content assertions).

---

### Story 1.2 — System prompt update
**Outcome:** The chat agent's system prompt reflects the new recommended default (`max_trials=200`) and the dimensionality-keyed guidance.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) | (a) change `max_trials: 100` at line 78 → `max_trials: 200`; (b) add a Studies-section sentence near line 17 with the dimensionality scaling guidance. |

**Tasks**

1. Locate line 78 of `prompts/orchestrator.system.md` — the create-study confirmation example. Change `max_trials: 100` → `max_trials: 200`.
2. Locate the Studies section near line 17 (`**Studies (4):**` bullet). Insert a new sub-bullet under it (or a sentence at the end of the section, choose the position that reads natural):
   > When the user does not specify a stop condition, propose `max_trials=200` for typical 3–5 param search spaces. Scale to ~50 for 1–2 params and ~1000 for 6+ params. Use `time_budget_min` only as a safety cap on slow clusters; trials are usually cheap.
3. Verify no other `max_trials: 100` strings survive in the file:
   ```bash
   grep -E 'max_trials[:=][[:space:]]*100($|[^0-9])' prompts/orchestrator.system.md
   ```
   Expected: zero matches (per spec AC-7's locked grep recipe — the `($|[^0-9])` boundary catches end-of-line cases too).

**Definition of Done (DoD)**
- `grep -E 'max_trials[:=][[:space:]]*100($|[^0-9])' prompts/orchestrator.system.md` returns zero matches.
- `grep -E 'max_trials[:=][[:space:]]*200($|[^0-9])' prompts/orchestrator.system.md` returns ≥1 match.
- The Studies-section sentence with the scaling guidance is present — visually verified by reading the file (the sentence contains backticks around `max_trials=200`, which makes a robust `grep` command awkward; visual verification is the locked DoD per GPT-5.5 cross-model review cycle 1, Finding #3, which spotted that the previously-proposed `grep -F 'propose \`max_trials=200\`' …` was unreliable across markdown-rendered vs shell-literal copy paths).
- This satisfies AC-7 (spec §12).

---

### Story 1.3 — Form default `max_trials = 200`
**Outcome:** The create-study wizard renders with `200` pre-filled in the Max trials field on every modal-open.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | Add `max_trials: 200` to the `useForm` `defaultValues` block at line 126 (alphabetized neighbors permitting; otherwise after `direction: 'maximize'` at line 136). |

**Tasks**

1. Open `create-study-modal.tsx`. Locate the `useForm<FormValues>({ defaultValues: { ... } })` block at lines 125-141.
2. Add `max_trials: 200,` between `direction: 'maximize',` (line 136) and `parallelism: 4,` (line 137). Do NOT add `time_budget_min` — it stays empty by default (FR-1's MUST NOT clause).
3. Verify `FormValues` interface at line 99 still allows `number | ''` for `max_trials` (existing typing — no change needed). The new default `200` is a valid `number`; existing form-clearing behavior (`''`) remains valid.

**Definition of Done (DoD)**
- `defaultValues.max_trials === 200` per `npx vitest run` once Story 1.5 lands the assertion.
- `npx tsc --noEmit` passes.
- This satisfies AC-1 partially (the Standard-button-pressed half of AC-1 lands in Story 1.4).
- Visual sanity check: on local dev (`make up` + `/studies` → "Create study" → Step 5), the Max trials field shows `200` instead of empty. (Optional — the vitest assertion in Story 1.5 is the binding test.)

---

### Story 1.4 — Step-5 button-group preset selector + state transitions
**Outcome:** Step 5 renders a 4-button preset group (Focused 50 / Standard 200 / Deep 1000 / Custom) above the numeric inputs. Clicking a preset writes to the form fields per spec §7 FR-3. Manual edits flip the active preset to Custom. Modal-open resets the selector to Standard.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | (a) Add `PRESET_VALUES` + `PresetValue` type constants at module scope. (b) Add a `useState<PresetValue>` for the active preset, default `'standard'`. (c) Insert the button-group JSX above the existing line-892 numeric-inputs grid. (d) Wire selecting a preset to `form.setValue` calls per spec §7 FR-3. (e) Add a `useEffect` watching `max_trials` + `time_budget_min` that flips the active preset to `'custom'` on manual edits. (f) Add the active-preset reset to the existing modal-open-reset `useEffect` at lines 162-167. |

**UI element inventory**

| Element | Type | Label | Data source | Interactions |
|---|---|---|---|---|
| `Stop condition` group label | `<span id="stop-condition-group-label">` (visible label for accessibility group) | "Stop condition" | static | none |
| `study.preset` InfoTooltip | `<InfoTooltip glossaryKey="study.preset" />` | n/a (icon-triggered popover) | `glossary.ts` | click → reveal `long` text |
| Button group container | `<div role="group" aria-labelledby="stop-condition-group-label">` | wraps the 4 preset buttons | n/a | none |
| Focused preset button | `<Button variant="outline" type="button" aria-pressed={...}>` | "Focused (50)" | `activePreset` state | click → writes `max_trials=50` + clears `time_budget_min`; sets `activePreset='focused'` |
| Standard preset button (default) | same | "Standard (200)" | `activePreset` state | click → writes `max_trials=200` + clears `time_budget_min`; sets `activePreset='standard'` |
| Deep preset button | same | "Deep (1000)" | `activePreset` state | click → writes `max_trials=1000` + `time_budget_min=480`; sets `activePreset='deep'` |
| Custom preset button | same | "Custom" | `activePreset` state | click → no field writes; sets `activePreset='custom'` |

**State dependency analysis**

```
New state being added: activePreset (useState<PresetValue>)
Referenced by:
  - The 4 preset buttons' `aria-pressed` props
  - The active-button visual styling (`variant` swap or `data-active` attribute)
  - The modal-open reset useEffect at lines 162-167 — action: reset to 'standard' on every open

Form state being touched (via form.setValue):
  - max_trials — written by Focused/Standard/Deep buttons
  - time_budget_min — cleared by Focused/Standard; set to 480 by Deep
```

**Key interfaces**

```typescript
// At module scope, above the FormValues interface (~line 95):

// Source-of-truth: frontend-only state. Preset wire values are NOT sent to
// the backend — the preset is purely UX. The numeric max_trials +
// time_budget_min fields written by the preset are the contract surface.
const PRESET_VALUES = ['focused', 'standard', 'deep', 'custom'] as const;
type PresetValue = (typeof PRESET_VALUES)[number];

const PRESET_LABELS: Record<PresetValue, string> = {
  focused: 'Focused (50)',
  standard: 'Standard (200)',
  deep: 'Deep (1000)',
  custom: 'Custom',
};

// Preset → field-write contract (spec §7 FR-3)
type PresetWrite = { max_trials: number | ''; time_budget_min: number | '' };
const PRESET_WRITES: Record<Exclude<PresetValue, 'custom'>, PresetWrite> = {
  focused: { max_trials: 50, time_budget_min: '' },
  standard: { max_trials: 200, time_budget_min: '' },
  deep: { max_trials: 1000, time_budget_min: 480 },
};
```

```typescript
// Inside CreateStudyModal, near the existing useState declarations (~line 123-124):

const [activePreset, setActivePreset] = useState<PresetValue>('standard');

// Click handler for non-Custom preset buttons:
const handlePresetClick = (preset: PresetValue) => {
  setActivePreset(preset);
  if (preset !== 'custom') {
    const writes = PRESET_WRITES[preset];
    form.setValue('max_trials', writes.max_trials, { shouldDirty: true });
    form.setValue('time_budget_min', writes.time_budget_min, { shouldDirty: true });
  }
};

// Manual-edit watcher (placed alongside the existing form.watch(...) calls ~line 143-147):
// **Bug-guard:** `react-hook-form`'s `watch()` returns `undefined` for fields that
// have no `defaultValues` entry (here: `time_budget_min`). Naive comparison
// `undefined !== ''` would fire on every modal-open and flip Standard → Custom
// immediately. Normalize undefined/null/NaN → '' before comparison.
// Locked per GPT-5.5 cross-model review cycle 1, Finding #2.
const watchedMaxTrials = form.watch('max_trials');
const watchedTimeBudget = form.watch('time_budget_min');
useEffect(() => {
  if (activePreset === 'custom') return;
  const expected = PRESET_WRITES[activePreset];
  const norm = (v: unknown): number | '' =>
    v === undefined || v === null || (typeof v === 'number' && Number.isNaN(v)) ? '' : (v as number | '');
  const normMax = norm(watchedMaxTrials);
  const normTime = norm(watchedTimeBudget);
  if (normMax !== expected.max_trials || normTime !== expected.time_budget_min) {
    setActivePreset('custom');
  }
}, [watchedMaxTrials, watchedTimeBudget, activePreset]);
```

**Modal-open reset additions** (extend the existing reset at lines 162-167):

The existing reset useEffect already calls `form.reset()` on `open` transitions. Add `setActivePreset('standard')` to the same effect so the preset selector resets in sync. The form's `defaultValues` from Story 1.3 will land `max_trials=200`, matching Standard's expected values — no race between form reset and preset reset.

**Tasks**

1. Add `PRESET_VALUES`, `PresetValue`, `PRESET_LABELS`, `PRESET_WRITES`, and `PresetWrite` at module scope (above `FormValues` interface).
2. Add `useState<PresetValue>('standard')` near the existing `useState` calls.
3. Add the `handlePresetClick` callback (memoized via `useCallback` if needed to avoid re-render churn).
4. Add the manual-edit watcher `useEffect`.
5. Add `setActivePreset('standard')` to the existing modal-open reset `useEffect` (lines 162-167).
6. Insert the button-group JSX above the existing line-892 numeric-inputs grid. Structure:
   ```tsx
   {/* Stop condition preset group — sits above the Max trials / Time budget / Parallelism row */}
   <div className="space-y-2">
     <div className="flex items-center gap-1">
       <span id="stop-condition-group-label" className="text-sm font-medium">Stop condition</span>
       <InfoTooltip glossaryKey="study.preset" />
     </div>
     <div role="group" aria-labelledby="stop-condition-group-label" className="flex flex-wrap gap-2">
       {PRESET_VALUES.map((p) => (
         <Button
           key={p}
           type="button"
           variant={activePreset === p ? 'default' : 'outline'}
           aria-pressed={activePreset === p}
           aria-label={PRESET_LABELS[p]}
           onClick={() => handlePresetClick(p)}
         >
           {PRESET_LABELS[p]}
         </Button>
       ))}
     </div>
   </div>
   ```

**Definition of Done (DoD)**
- Selecting Focused writes `max_trials=50` AND clears `time_budget_min` (vitest assertion in Story 1.5 — AC-2).
- Selecting Standard writes `max_trials=200` AND clears `time_budget_min` (vitest — AC-1 second half).
- Selecting Deep writes `max_trials=1000` AND `time_budget_min=480` (vitest — AC-3).
- Selecting Custom does not write to either field (vitest — AC-4).
- Manually typing a different `max_trials` while Standard is active flips `activePreset` to `'custom'` (vitest — AC-5).
- Modal-open reset re-selects Standard and re-fills `max_trials=200` (vitest — AC-6).
- Switching Deep → Standard clears the stale `time_budget_min=480` to empty (vitest — bug-guard from cycle-1 Finding #3).
- Switching Deep → Focused clears the stale `time_budget_min=480` to empty (vitest — same bug-guard).
- All 4 preset buttons render with `aria-pressed` reflecting `activePreset`; the active button uses `variant="default"`, others `variant="outline"`.
- The button-group container has `role="group" aria-labelledby="stop-condition-group-label"` with the visible-label span carrying the matching `id`.
- Every button has `type="button"` (no `type="submit"` default that would prematurely submit the wizard).
- `npx tsc --noEmit` passes.
- `npx next build` passes (catches SSR issues — `useState` + `useEffect` are client-only; the component is already client-only per the `'use client'` directive at the top of the existing file).

---

### Story 1.5 — Vitest test suite for stop-condition preset behavior
**Outcome:** A new vitest file at `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` proves the spec §14 vitest set (AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, two Deep-transition bug-guards, AC-8, AC-10). AC-7 is verified by Story 1.2's prompt-content grep DoD; AC-9 is unchanged backend-validator behavior covered by existing backend contract tests. Locked per GPT-5.5 cross-model review cycle 1, Finding #4.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` | 10+ vitest cases covering form defaults + preset writes + manual-edit transition + modal-open reset + glossary tooltip render + wire-shape (no `preset` field in POST body). |

**Modified files**

None (the new test file is the only addition; sibling test files are not extended).

**Key interfaces (test pattern)**

Follow the pattern in [`ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx) for modal mounting + `userEvent` interaction. Specifically:
- Render `<CreateStudyModal open={true} onOpenChange={vi.fn()} />` wrapped in a query-client provider.
- Mock the API hooks (`useClusters`, `useClusterSchema`, etc.) per the existing test file's pattern.
- Use `screen.getByRole`, `screen.getByLabelText` for accessible-name queries.
- Use `userEvent.click`, `userEvent.clear` + `userEvent.type` for interactions.
- For the wire-shape test (AC-10), mock the POST handler with `vi.fn()` and assert the request body shape.

**Tasks**

1. Create `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`.
2. Add the top-of-file imports + mocks following the sibling `*.client-validation.test.tsx` pattern.
3. Add a `describe('create-study modal — stop condition presets', ...)` block with the following 10+ test cases:

   | # | Test name | AC | Asserts |
   |---|---|---|---|
   | 1 | renders Standard pressed + max_trials=200 by default | AC-1 | Standard button `aria-pressed="true"`; Max trials input value `"200"` |
   | 2 | Focused preset writes max_trials=50, clears time_budget_min | AC-2 | After click on Focused: max_trials="50", time_budget_min="", Focused pressed |
   | 3 | Deep preset writes max_trials=1000 + time_budget_min=480 | AC-3 | After click on Deep: max_trials="1000", time_budget_min="480", Deep pressed |
   | 4 | Custom preset preserves manual edits | AC-4 | Type 333 in max_trials while Standard active, click Custom — value stays 333 |
   | 5 | manual edit while non-Custom flips to Custom | AC-5 | Type 300 in max_trials while Standard active — Custom button's `aria-pressed` flips to `true` |
   | 6 | modal-open reset re-selects Standard + 200 | AC-6 | Open → click Deep → close → re-open — Standard pressed, max_trials="200", time_budget_min="" |
   | 7 | transition Deep → Standard clears time_budget_min | bug-guard | Click Deep, then Standard — time_budget_min should be "" (not the stale "480") |
   | 8 | transition Deep → Focused clears time_budget_min | bug-guard | Click Deep, then Focused — time_budget_min should be "" |
   | 9 | refreshed Max trials tooltip renders the new short copy | AC-8 | Click the `study.max_trials` InfoTooltip — assert visible text matches the FR-5 `short` copy |
   | 10 | wire-shape: no `preset` field in POST body | AC-10 | Mock the POST handler; submit with Standard active — assert the request body has `max_trials: 200` and NO `preset` field |

4. Each test uses `userEvent` for interactions (no direct DOM mutation) and `expect(...).toBe...` assertions on form state via `screen.getByRole` / `getByLabelText`.

5. Run `npx vitest run ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` — expect 10/10 green.

**Definition of Done (DoD)**
- The new file exists with ≥10 test cases covering AC-1..AC-10 plus the two bug-guard transitions.
- `npx vitest run ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` reports 10+ passed, 0 failed.
- `npx vitest run` for the whole suite remains green (no regression from sibling test files).
- `npx eslint ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` clean.

---

## UI Guidance

### Reference: current component structure

- **File:** [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — ~1100 lines total (verified at impl time).
- **Step-5 section** (`{step === 4 && (...)}` block starting at line 776):
  - Objective + metric/k/direction grid (3-column)
  - Numeric inputs grid (3-column): Max trials (line 892), Time budget (line 904), Parallelism (line 916)
  - Sampler/Pruner/Seed grid (3-column, line 928+)
- **Insertion point:** above the line-892 numeric-inputs `<div className="grid gap-3 sm:grid-cols-3">` — the preset selector renders as a 2-row block (group label + 4 buttons).
- **State variables added by this plan:** `activePreset: PresetValue` (one `useState`).
- **Props:** unchanged — no new props.

### Analogous markup patterns

The button-group pattern matches the project's existing shadcn `Button`-with-`variant`-swap precedent. Closest analogous use:

```tsx
{/* Analogous tab-style button pattern — from chat ExamplePrompts strip
    (ui/src/components/chat/example-prompts.tsx, used post-MVP1 PR #124).
    Adapt to the 4-button stop-condition selector by wrapping in
    role="group" aria-labelledby="...". */}
<div className="flex flex-wrap gap-2">
  {prompts.map((p) => (
    <Button key={p.id} type="button" variant="outline" onClick={() => handlePromptClick(p)}>
      {p.label}
    </Button>
  ))}
</div>
```

For the InfoTooltip + group-label header, mirror the existing labeled-input pattern at lines 894-897:

```tsx
{/* Analogous label + InfoTooltip pattern — from existing Step-5 Max trials field
    (create-study-modal.tsx:894-897). */}
<div className="flex items-center gap-1">
  <Label htmlFor="cs-max">Max trials</Label>
  <InfoTooltip glossaryKey="study.max_trials" />
</div>
```

Adapted to the preset group (uses `<span id="...">` instead of `<Label>` because the group label associates with a button group via `aria-labelledby`, not with a form input):

```tsx
{/* Preset group label + tooltip — adapted from the labeled-input pattern. */}
<div className="flex items-center gap-1">
  <span id="stop-condition-group-label" className="text-sm font-medium">Stop condition</span>
  <InfoTooltip glossaryKey="study.preset" />
</div>
```

### Layout and structure

- The preset selector adds a new 2-row block above the existing numeric-inputs grid:
  - Row 1: group label + InfoTooltip (flex row)
  - Row 2: 4 `<Button>` elements in a `flex flex-wrap gap-2` container
- Responsive: `flex-wrap` lets the buttons wrap on narrow viewports (modal max-width is typically 600-800px; 4 buttons with `(N)` labels fit on one line on most desktops).
- Vertical spacing: a `space-y-2` wrapper between the label row and the button row; the existing numeric-inputs grid sits below this with the modal's default vertical gap.
- **Per-option helper text — explicitly NOT rendered inline.** The spec's §11 IA prose mentions "per-option helper text under each: 1-line rationale + wall-clock estimate" descriptively, but the binding normative requirement is FR-7 ("each preset button MUST render its label as `<Name> (<trial count>)` … the button-group container MUST have an `InfoTooltip` with `glossaryKey='study.preset'`"). The InfoTooltip on the group label surfaces the per-preset rationales via the `study.preset` glossary entry's `long` field (which spells out "Focused (50) — 1–2 params; smallest preset where MedianPruner activates …" etc.). Adding inline helper text would clutter the compact button row and conflict with FR-7's label-only contract. Locked per GPT-5.5 cross-model review cycle 1, Finding #5.

### Confirmation/modal dialog pattern

N/A — this feature does not add or modify any confirmation dialogs.

### Visual consistency table

| New element | Pattern source | CSS class / variant |
|---|---|---|
| Group label `<span>` | matches existing Label-style typography | `text-sm font-medium` |
| InfoTooltip on group label | existing `<InfoTooltip>` at lines 896, 907, 919 | (component encapsulates style) |
| Button container `<div role="group">` | new — no precedent inside this modal | `flex flex-wrap gap-2` |
| Preset button (inactive) | existing shadcn Button | `variant="outline"` |
| Preset button (active) | existing shadcn Button | `variant="default"` |

### Component composition

- All new UI is **inline** in `create-study-modal.tsx`. No new component extraction.
- Rationale: the button-group has zero reuse potential elsewhere (it's specific to the create-study form's stop-condition contract) AND the modal is already a long single-purpose component. Extracting would add navigation cost without test or reuse benefit.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Open modal | `useForm` `defaultValues` lands `max_trials=200`; `activePreset='standard'` set via reset effect; Max trials input renders `200`; Standard button `aria-pressed="true"` | none |
| Click Focused | `setActivePreset('focused')` + `form.setValue('max_trials', 50)` + `form.setValue('time_budget_min', '')` | none (yet — preset is local state) |
| Click Standard | same shape; values 200 + clear | none |
| Click Deep | `setActivePreset('deep')` + `setValue('max_trials', 1000)` + `setValue('time_budget_min', 480)` | none |
| Click Custom | `setActivePreset('custom')` only — no field writes | none |
| Manually type a different `max_trials` while Standard active | Manual-edit watcher fires; `activePreset` flips to `'custom'`; Custom button `aria-pressed="true"` | none |
| Click "Create study" (existing submit) | Existing submit handler reads `max_trials` + `time_budget_min` from form state, sends `POST /api/v1/studies` with the numeric values | `POST /api/v1/studies` (existing endpoint, unchanged) |

### Handler function patterns

The two key handlers — `handlePresetClick` and the manual-edit watcher — are specified verbatim in Story 1.4's "Key interfaces" section. The `useEffect` watcher uses the existing `form.watch(name)` pattern (precedent at lines 143-147 of the same file).

### Information architecture placement

- **Section:** Step 5 of the create-study wizard (existing `STEP_TITLES[4] = 'Objective + config'` per [`create-study-modal.tsx:112`](../../../../ui/src/components/studies/create-study-modal.tsx#L112)).
- **Position:** above the existing numeric-inputs grid (Max trials / Time budget / Parallelism row at line 892). The preset selector is the new "primary" stop-condition control; the numeric inputs are the "detailed override" that operators reach to when Custom is selected.
- **What comes before:** the Objective + metric + k + direction row (existing).
- **What comes after:** the Max trials / Time budget / Parallelism row (existing — unchanged in layout but pre-filled by the preset).
- **Discovery:** operators reaching Step 5 see Standard pre-selected with a `200` Max trials value — the new default IS the discovery surface. The InfoTooltip on the group label provides the "what does this mean" affordance for operators who want to understand why 200.

### Tooltips and contextual help

| Element | Tooltip text source | Trigger | Placement | Glossary key | Source-of-truth comment target |
|---|---|---|---|---|---|
| "Stop condition" group label | `study.preset` | click InfoTooltip icon | top (default `<InfoTooltip>` placement) | `study.preset` (new entry from Story 1.1) | n/a — `study.preset` is a frontend-only key |
| Max trials input label | refreshed `study.max_trials` (Story 1.1) | click InfoTooltip icon | top (existing) | `study.max_trials` | n/a — refresh of an existing key |
| Time budget (min) input label | refreshed `study.time_budget_min` (Story 1.1) | click InfoTooltip icon | top (existing) | `study.time_budget_min` | n/a — refresh of an existing key |
| Parallelism input label | existing `study.parallelism` | click InfoTooltip icon | top (existing) | `study.parallelism` | n/a — unchanged |

All four glossary keys are looked up via the existing `<InfoTooltip glossaryKey={...} />` primitive. No inline tooltip text — every entry traces back to `ui/src/lib/glossary.ts`.

### Visual consistency

- **Active vs inactive buttons:** use shadcn `Button` `variant="default"` (filled, primary-color background) for the active preset; `variant="outline"` for the three inactive presets. This matches the existing shadcn variant vocabulary used throughout the modal.
- **Group label typography:** `text-sm font-medium` matches the existing `<Label>` styling at lines 894-897 (which itself uses shadcn's `Label` primitive that compiles to the same Tailwind classes).
- **Spacing:** `space-y-2` between label row and button row; `gap-2` between buttons. Matches the existing modal's vertical-section rhythm.

### Legacy behavior parity

No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. The feature ADDS a new selector above existing inputs; existing inputs (Max trials / Time budget / Parallelism) are unchanged in shape or behavior except that they may be pre-filled by the new preset writes.

### Client-side persistence

N/A — the preset state is React `useState` only. It resets on modal-close (via the existing modal-open reset effect). No `localStorage` or `sessionStorage` involvement.

---

## 3) Testing workstream

### 3.1 Unit tests

N/A — no pure backend logic added.

### 3.2 Integration tests

N/A — no DB / service / endpoint changes.

### 3.3 Contract tests

N/A — the existing `POST /api/v1/studies` contract is unchanged. The server-side `_require_one_stop_condition` validator at [`backend/app/api/v1/schemas.py:578-586`](../../../../backend/app/api/v1/schemas.py#L578-L586) remains the safety net; its existing contract test (verify file exists at impl time — likely `backend/tests/contract/test_studies_api_contract.py`) keeps passing without modification.

### 3.4 E2E tests

N/A — the preset selector's mechanics are fully deterministic at the vitest layer where they're tested. Adding a Playwright case would only duplicate coverage. The existing [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) create-study flow stays green without modification (vitest exists at impl time — verified at `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx` etc.).

### 3.5 Vitest (UI unit) — primary test surface

- Location: `ui/src/__tests__/components/studies/`
- Scope: form defaults, preset write behavior, state transitions, tooltip render, wire-shape (no `preset` in POST body)
- Tasks:
  - [ ] Write `create-study-modal.stop-conditions.test.tsx` with the 10 cases listed in Story 1.5's table.
- DoD:
  - [ ] All 10 cases green
  - [ ] No regression in sibling `create-study-modal.*.test.tsx` files

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx` | `max_trials` form-submit guard | grep at impl time | NO change needed — the validator still fires (empty `max_trials` + empty `time_budget_min` blocks submit). The new default `200` means the validator never trips in practice unless the operator clears both fields. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | modal-open reset state | grep at impl time | NO change unless this file's modal-open-reset assertion was previously testing that `max_trials` was empty. If so, update to `'200'`. Likely safe — earlier tests assert defaults dictionary shape, not specific stop-condition values. |
| `ui/tests/e2e/studies.spec.ts` | create-study end-to-end | grep at impl time | NO change needed — E2E tests run the existing flow; the new pre-fill is invisible to the assertion (the test doesn't read the Max trials field; it submits and verifies the study was created). |

### 3.6 Migration verification

N/A — no schema changes.

### 3.7 CI gates

- [ ] `cd ui && npx vitest run` (UI suite — including the new test file)
- [ ] `cd ui && npx tsc --noEmit` (TypeScript)
- [ ] `cd ui && npx eslint .` (lint)
- [ ] `cd ui && npx next build` (production build — catches SSR issues)
- [ ] `make backend-lint` (no backend code touched but pre-commit hook runs lint anyway)
- [ ] `make backend-typecheck` (same)

No backend tests are required by this plan; backend tests remain unchanged and pass without modification.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — no update required by this plan body itself; the `/impl-execute` post-merge finalization will prepend a brief merge summary to state.md per the established convention (similar to the bug-fix entries earlier this session). This is the post-PR finalization step, NOT a story.

**`architecture.md`** — no update. The feature does not change architecture (no new layer, no new flow, no new component extraction).

**`CLAUDE.md`** — no update. No new convention or rule.

### 4.1–4.5 Tier-specific docs

All N/A. The feature does not change architecture, product/user-facing surface beyond the wizard, runbook procedures, security model, or testing strategy beyond the new vitest case file.

**Documentation DoD:** All N/A for this plan.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

N/A — no refactor in scope.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [x] No expansion of product scope (locked at Tier A + Tier B per spec §3)
- [x] Behavioral parity preserved (existing wizard surface unchanged in shape; only pre-fills new defaults)

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `react-hook-form` `useForm` + `setValue` + `watch` | Story 1.4 | implemented (used throughout `create-study-modal.tsx`) | — |
| Shadcn `Button` primitive at `@/components/ui/button` | Story 1.4 | implemented (used throughout the modal) | — |
| `InfoTooltip` primitive at `@/components/common/info-tooltip` | Stories 1.1 + 1.4 | implemented (used at Step 5 already) | — |
| Glossary `study.preset` entry | Story 1.4 (Stop-condition InfoTooltip) | NEW — landed by Story 1.1 | Without Story 1.1 first, Story 1.4's InfoTooltip would fall through to glossary's default-key handler (likely a noop or "unknown key" — verify the existing fallback behavior at impl time). **Sequencing constraint: Story 1.1 MUST land before Story 1.4.** |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Manual-edit watcher fires on programmatic preset writes (race) | Low | Medium | The watcher guards on `activePreset !== 'custom'` AND compares current values against the expected preset values. Programmatic `form.setValue` calls write the EXPECTED values, so the watcher's "values differ from expected" branch doesn't fire on its own writes. Verify via vitest case 2/3/6. |
| Modal-open reset race between `form.reset()` and `setActivePreset('standard')` | Low | Low | Both are state updates within the same React render cycle. After the first commit, both states reflect their reset values. The vitest open-close-open case (test 6) catches any regression. |
| `useEffect` watcher creates an infinite render loop | Low | High | The watcher only sets state when the values mismatch; once `activePreset === 'custom'` (after the flip), the early-return branch guards against further re-fires. Verified by vitest case 5 (one flip, no loops). |
| Operator's eslint rules forbid `useState` + `useEffect` mid-component | Very Low | Low | Existing modal already uses both extensively; this story follows the established pattern. No new lint rule needed. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Operator clears `max_trials` to empty in Custom mode (no other stop condition set) | Manual clear of both numeric fields | Existing client-side guard at lines 417-419 disables the submit button; server-side `_require_one_stop_condition` would catch it as 422 if the client guard somehow missed | Operator types a value into either field |
| Operator types `0` or `100001` in `max_trials` | Manual entry outside Pydantic `ge=1, le=100_000` bounds | Server returns 422 with `VALIDATION_ERROR` envelope per `backend/app/api/errors.py:62, 118`; existing error path | Operator corrects the value |
| Preset write + immediate operator keystroke race | Click Deep, then start typing in max_trials within the same render frame | `form.setValue` runs first (synchronous); keystrokes overwrite; manual-edit watcher fires on the keystroke commit; `activePreset` flips to Custom. Acceptable. | No recovery needed — design as intended |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (glossary refresh + new `study.preset` entry) — must land first so Story 1.4 can reference the new key
2. **Story 1.2** (system prompt update) — independent of all others; can land before or after Story 1.1
3. **Story 1.3** (form default `max_trials = 200`) — must land before Story 1.4 so the modal-open-reset's expected `max_trials=200` value matches Standard's expected write
4. **Story 1.4** (button-group selector + state transitions) — depends on Stories 1.1 + 1.3
5. **Story 1.5** (vitest test suite) — depends on Stories 1.3 + 1.4 (asserts their behavior)

### Parallelization opportunities

- Stories 1.1, 1.2, 1.3 can run in parallel (no inter-dependency). All three are tiny single-file edits.
- Stories 1.4 + 1.5 are sequential (1.5 tests 1.4's behavior).

For `impl-execute --all` this sequence runs naturally — each story is short and the gating between them is at the per-story verification, not the cross-story sequencing.

## 8) Rollout and cutover plan

- **Rollout stages:** single-stage ship via the standard `/impl-execute --ad-hoc`-style flow (or `/impl-execute --all` since this came in via `/pipeline`). No staged rollout, no feature flag.
- **Migration / cutover steps:** N/A — no schema changes.
- **Reconciliation / repair strategy:** N/A — no external systems involved.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Glossary copy refresh + new `study.preset` entry (FR-5, FR-8)
- [ ] Story 1.2 — System prompt update (FR-6)
- [ ] Story 1.3 — Form default `max_trials = 200` (FR-1)
- [ ] Story 1.4 — Step-5 button-group preset selector + state transitions (FR-2, FR-3, FR-4, FR-7)
- [ ] Story 1.5 — Vitest test suite (FR-9)

### Blocked items

None.

### Done this sprint

None yet.

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (New files / Modified files tables)
- [ ] Endpoint contract implemented exactly as documented (N/A this plan — no endpoints)
- [ ] Key interfaces implemented with compatible signatures (Story 1.4: `PresetWrite` type, `handlePresetClick` callback, watcher useEffect)
- [ ] Required tests added/updated for the vitest layer (Story 1.5)
- [ ] Commands executed and passed:
    - [ ] `cd ui && npx tsc --noEmit`
    - [ ] `cd ui && npx eslint .` (or `npx eslint <touched-files>`)
    - [ ] `cd ui && npx vitest run ui/src/__tests__/components/studies/` (for Story 1.5 and any modal-test-impact)
    - [ ] `cd ui && npx next build` (Story 1.4 — SSR sanity)
- [ ] Migration round-trip evidence: N/A (no migration)
- [ ] Related docs/checklists updated: N/A (no doc updates in this plan)

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** Spec adds 0 endpoints; plan touches 0 endpoints. ✓ Match.
2. **Spec ↔ plan error code coverage:** Spec adds 0 new error codes; plan touches 0. ✓ Match.
3. **Spec ↔ plan FR coverage:** All 9 FRs from spec §7 traced to a story in plan §1. ✓ Match.
4. **Story internal consistency:**
   - Story 1.1: `ui/src/lib/glossary.ts` exists ✓ (verified by spec-gen)
   - Story 1.2: `prompts/orchestrator.system.md` exists ✓
   - Story 1.3 + 1.4: `ui/src/components/studies/create-study-modal.tsx` exists ✓ at lines cited (125-141 defaults, 162-167 reset, 892+ inputs)
   - Story 1.5: New test file path matches existing sibling-file naming convention `*.test.tsx` ✓
   - No file ownership conflicts (Story 1.1 owns glossary; Story 1.2 owns prompts; Stories 1.3-1.4 own the modal; Story 1.5 owns the new test).
5. **Test file count:** Plan §3.5 lists 1 new vitest file with 10 cases. Story 1.5 owns this file. ✓ Match.
6. **Gate arithmetic:** Single epic, 5 stories, 10 vitest cases. Gate at end of Epic 1 = "all 5 stories complete + all 10 vitest cases green + `tsc --noEmit` + `next build` + `eslint` clean." Matches.
7. **Open questions resolved:** Spec §19 has all 5 idea-preflight open questions resolved (decision-log entries). ✓ No unresolved questions.
8. **Frontend UI Guidance completeness:** Plan-level UI Guidance section present with all required subsections — insertion point, analogous markup patterns (with actual JSX from `chat/example-prompts.tsx` + the modal's existing label-tooltip pattern), layout/structure, visual-consistency table, component composition (inline rationale), interaction-behavior table, handler patterns (specified in Story 1.4's "Key interfaces"), IA placement, tooltip inventory with glossary keys, legacy-parity table explicitly N/A (no >100 LOC deletion), client-side persistence explicitly N/A. ✓
9. **Plan ↔ codebase verification:** All file paths verified to exist; line numbers within ~20 lines of cited locations (spec-gen Pass 1 already audited; this plan inherits those verifications).
10. **Persistence scope consistency:** N/A — no `localStorage` / `sessionStorage` usage.
11. **Enumerated value contract audit:** The preset values (`focused` / `standard` / `deep` / `custom`) are FRONTEND-ONLY (per spec §7.4 "no new wire-value enum"). Spec §4 anti-pattern locks the no-wire-shape rule. Plan §2 conventions notes the source-of-truth comment on `PRESET_VALUES` documents this. ✓ No backend allowlist to cross-check.
12. **Admin control audit:** N/A (MVP4+).
13. **Audit-event coverage audit:** N/A (MVP2+).

## 12) Definition of plan done

- [x] Every FR (FR-1..FR-9) mapped to a story
- [x] Every story includes New files / Modified files / Tasks / DoD
- [x] Test layer (vitest) explicitly scoped (Story 1.5)
- [x] Documentation updates: N/A explicitly stated
- [x] Lean refactor scope and guardrails: N/A explicitly stated
- [x] Epic gate is measurable: 5 stories complete + 10 vitest cases green + tsc + build + eslint clean
- [x] Story-by-Story Verification Gate included (§10)
- [x] Plan consistency review (§11) performed with no unresolved findings

**Plan is execution-ready.**
