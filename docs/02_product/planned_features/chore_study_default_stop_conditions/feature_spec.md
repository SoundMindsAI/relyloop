# Feature Specification — Study Default Stop Conditions

**Date:** 2026-05-23
**Status:** Approved (Opus + GPT-5.5 cross-model review converged at cycle 3 — 1 rejected with cited counter-evidence, 11 accepted + applied)
**Owners:** RelyLoop maintainers (eric.starr@soundminds.ai)
**Related docs:**
- [`idea.md`](./idea.md) — source planning brief (5 locked decisions + 5 spec-time questions, 4 with recommended defaults)
- [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) — TPE convergence + MedianPruner activation semantics
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — wizard step structure precedent
- [`feature_templates/feature-spec-template.md`](../feature_templates/feature-spec-template.md)

---

## 1) Purpose

The create-study wizard and the `create_study` agent tool currently leave the stop-condition fields (`max_trials` + `time_budget_min`) empty — operators and the LLM agent pick numbers by intuition, with no project guidance. The result is studies that either stop before TPE warms up (< 50 trials, MedianPruner auto-disables per [`backend/app/eval/optuna_runtime.py:154-156`](../../../../backend/app/eval/optuna_runtime.py#L154-L156)) or burn budget past TPE's diminishing returns.

- **Problem:** No opinionated defaults. Operator-supplied numbers correlate poorly with TPE convergence behavior; the system prompt's example (`max_trials: 100` per [`prompts/orchestrator.system.md:78`](../../../../prompts/orchestrator.system.md)) is a single number with no scaling guidance.
- **Outcome:** The wizard ships with `max_trials=200` pre-filled (typical 3–5 param case), a dimensionality-keyed preset selector (Focused 50 / Standard 200 / Deep 1000 / Custom) above the numeric fields, refreshed glossary copy explaining the convergence rationale, and an updated system prompt entry so the LLM agent picks the same numbers operators see in the UI.
- **Non-goals:** Changing the backend Pydantic default (the server-side validator at [`schemas.py:569-586`](../../../../backend/app/api/v1/schemas.py#L569-L586) keeps requiring an explicit value — only the wizard + system prompt opinion-set); adaptive parallelism; "Karpathy mode" auto-chained follow-ups (belongs to [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)).

## 2) Current state audit

### Existing implementations

| File / surface | What it does | Notes |
|---|---|---|
| [`ui/src/components/studies/create-study-modal.tsx:125-141`](../../../../ui/src/components/studies/create-study-modal.tsx#L125-L141) | `useForm<FormValues>` initialization with `defaultValues` block | `max_trials` and `time_budget_min` are NOT in the defaults (typed `number \| ''` at lines 99-100); render empty. `parallelism: 4`, `sampler: 'tpe'`, `pruner: 'median'` are pre-filled. |
| [`ui/src/components/studies/create-study-modal.tsx:892-927`](../../../../ui/src/components/studies/create-study-modal.tsx#L892-L927) | Step-5 stop-condition + parallelism inputs (`<Input type="number">` + `InfoTooltip`) | 3-column grid. Each input uses `form.register(<name>, { valueAsNumber: true })`. Glossary tooltips already wired (`study.max_trials`, `study.time_budget_min`, `study.parallelism`). |
| [`ui/src/components/studies/create-study-modal.tsx:415-460`](../../../../ui/src/components/studies/create-study-modal.tsx#L415-L460) | Submit handler — builds `config` object, validates "at least one stop condition" client-side before POST | Mirrors backend Pydantic validator. Submit blocks if neither `max_trials` nor `time_budget_min` is numeric > 0. |
| [`ui/src/lib/glossary.ts:160-169`](../../../../ui/src/lib/glossary.ts#L160-L169) | Existing `study.max_trials` + `study.time_budget_min` entries | Current short text: *"Maximum number of trials to run. 100–500 is typical for 3 search-space parameters; raise it for larger spaces."* No `long` form. |
| [`backend/app/api/v1/schemas.py:569-586`](../../../../backend/app/api/v1/schemas.py#L569-L586) | `StudyConfigSpec` Pydantic class + `_require_one_stop_condition` validator | Server requires at least one of `max_trials` / `time_budget_min`. **Do not change** — keep as the explicit-value safety net. |
| [`backend/app/agent/tools/studies/create_study.py:1-50`](../../../../backend/app/agent/tools/studies/create_study.py#L1-L50) | `create_study` agent tool | Re-exports `CreateStudyRequest` verbatim; no agent-side default-injection. Driven by the system prompt's `max_trials: 100` example. |
| [`prompts/orchestrator.system.md:71-79`](../../../../prompts/orchestrator.system.md#L71-L79) | System prompt confirmation-message example | Quotes `max_trials: 100` in the create-study confirmation template. Will need update to match the new recommended defaults. |
| [`backend/app/eval/optuna_runtime.py:116-157`](../../../../backend/app/eval/optuna_runtime.py#L116-L157) | `build_pruner` — MedianPruner auto-disable threshold | `max_trials < 50` → `NopPruner` (no warmup); `>= 50` → `MedianPruner(n_warmup_steps=10)`. The preset values (50/200/1000) are calibrated to this threshold. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| — | (no URLs change; this is in-form UX) | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (or whatever the existing test file is named) | `max_trials` form interaction | grep at impl time | Add test cases for default pre-fill + each preset's field-write behavior |
| `ui/tests/e2e/studies.spec.ts` | create-study modal end-to-end | grep at impl time | Existing E2E flow should keep passing; new presets are tested at vitest layer, not E2E |

### Existing behaviors affected by scope change

- **Wizard `max_trials` field empty by default → pre-filled with `200`.** Current: empty input, operator types a number. New: input renders `200`; operator may edit. Decision needed: **no** (locked — recommended default per idea).
- **Wizard `time_budget_min` field empty by default → stays empty by default, set to `480` by Deep preset only.** Current: empty. New: empty unless Deep preset is selected (which sets it to 8h as a safety cap). Decision needed: **no** (locked).
- **System prompt's `max_trials: 100` example → `max_trials: 200`.** Decision needed: **no** (locked — aligns the agent with the wizard).
- **Existing `study.max_trials` glossary text → new copy explaining preset semantics + convergence rationale.** Decision needed: **no** (locked — captured in FR-4).

---

## 3) Scope

### In scope

- **Tier A** — Pre-fill `max_trials = 200` in the wizard form `defaultValues`; refresh glossary entries for `study.max_trials` + `study.time_budget_min`; update system prompt to teach the agent the new recommended defaults.
- **Tier B** — Add a preset radio (Focused 50 / Standard 200 / Deep 1000 / Custom) on Step 5 above the numeric inputs. Selecting a preset writes the corresponding values to the form; Custom preserves whatever the operator has typed.
- Vitest coverage for the form default pre-fill (Tier A) and the preset radio's field-write behavior (Tier B).

### Out of scope

- Backend `StudyConfigSpec` Pydantic-layer defaults — the server keeps requiring an explicit value; the spec-rationale is that callers other than the wizard (the existing CLI / direct API users) shouldn't be silently opted into a wizard-shaped default.
- Adaptive parallelism based on observed trial latency.
- Auto-chained follow-up studies (separate feature: `feat_auto_followup_studies`).
- A combined "Karpathy mode" preset (also belongs to `feat_auto_followup_studies`).
- New backend endpoints, schema migrations, or domain rules.

### API convention check

- **Endpoint prefix convention:** N/A — this feature adds no endpoints.
- **Router namespace:** N/A.
- **Non-auth error envelope:** N/A — the wizard's client-side stop-condition guard predates this feature and is unchanged; the server-side `_require_one_stop_condition` validator returns the standard FastAPI 422 envelope and is also unchanged.

### Phase boundaries (single-phase)

Tier A + Tier B ship together in **Phase 1**. The idea's "ship as one unit" decision (idea §"Open questions for /spec-gen" question 1) is locked: splitting would produce two PRs for what is conceptually one operator-visible change, and Tier B's preset selector IS the headline UX add. Tier A alone would be operator-invisible polish (a number in a pre-filled field).

No Phase 2 deferral; no `phase2_idea.md` needed.

## 4) Product principles and constraints

- **Sensible defaults, operator override always available.** Every pre-filled value can be edited in Custom mode. Defaults guide; they don't constrain.
- **Preset names frame the search-space-fit dimension, not duration.** "Focused / Standard / Deep" maps directly to TPE convergence behavior for 1–2 / 3–5 / 6+ param spaces. Alternative names ("Fast / Default / Thorough" or "Quick / Recommended / Long") were considered and rejected (idea §"Open questions" question 3) because they invert framing toward wall-clock instead of search-space dimensionality.
- **Single source of truth for default numbers.** The 50/200/1000 trial counts live in:
  - The preset radio (`PRESET_VALUES` constant in the modal component) — primary
  - The form's `defaultValues.max_trials = 200` — derived from the Standard preset
  - The glossary `long` copy — narrative explaining when each preset fits
  - The system prompt's create-study example — derived from the Standard preset
  If the recommended default changes (e.g., 200 → 150), all four sites move together.
- **No new wire-value enum.** The preset is pure frontend state — the preset value (`focused` / `standard` / `deep` / `custom`) is NOT sent to the backend; only the resulting numeric `max_trials` / `time_budget_min` go over the wire. No backend allowlist needed for the preset.
- **Backend Pydantic stays explicit.** Per CLAUDE.md "make defaults visible to the operator, not silent in the backend" — the server-side `_require_one_stop_condition` validator at [`schemas.py:578-586`](../../../../backend/app/api/v1/schemas.py#L578-L586) is the guard against missing-stop-condition; only the wizard + system prompt opinion-set.

### Anti-patterns

- **Do not** add a backend Pydantic `default=200` to `StudyConfigSpec.max_trials` — silent backend defaults surprise non-wizard callers (CLI, direct API, tests fixtures) and break the existing "explicit value required" contract.
- **Do not** send the preset value (`focused` / `standard` / `deep` / `custom`) over the wire to `POST /api/v1/studies`. The preset is UX state only — it translates to existing `max_trials` + `time_budget_min` numeric fields the backend already accepts.
- **Do not** invent a new error code or status for the preset. The existing client-side + server-side "at least one stop condition required" guard at [`schemas.py:578-586`](../../../../backend/app/api/v1/schemas.py#L578-L586) + [`create-study-modal.tsx:417-419`](../../../../ui/src/components/studies/create-study-modal.tsx#L417-L419) is unchanged; with `max_trials=200` pre-filled the guard never trips in practice unless the operator deliberately clears both fields.
- **Do not** auto-switch presets when the operator manually edits numeric fields after picking a preset. Once an operator types into a numeric field, the radio jumps to **Custom** so the visible state matches the values about to be POSTed.
- **Do not** change `parallelism` or `trial_timeout_s` defaults as part of this feature — those are cluster-shape concerns, not stop-condition concerns. The preset writes only `max_trials` (+ `time_budget_min` for Deep).

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| `useForm` + `react-hook-form` | Form state management for the wizard | implemented (used throughout the modal) | — |
| `InfoTooltip` + `glossary.ts` | Tooltip rendering for the refreshed copy | implemented | — |
| Preset selector primitive (button-group with `aria-pressed`) | Preset selection control | **Pass-1 finding:** `@radix-ui/react-radio-group` is NOT in [`ui/package.json`](../../../../ui/package.json) and no `<RadioGroup>` shadcn primitive exists in `ui/src/components/ui/`. Adding a new npm dep is a borderline-operator-action per CLAUDE.md. **Locked path:** use a horizontal row of 4 `<Button variant="outline">` elements with `aria-pressed` toggling, sharing the existing shadcn `Button` primitive. Semantically equivalent to a radio group (mutually-exclusive selection); accessible via `aria-pressed`; no new dep. | — |
| MedianPruner threshold at 50 trials | Calibration anchor for the Focused preset value | implemented at [`optuna_runtime.py:147-149`](../../../../backend/app/eval/optuna_runtime.py#L147-L149); if the threshold ever changes the preset values must follow | low — change is unlikely; spec captures the link |

## 6) Actors and roles

- **Primary actor:** relevance engineer (creates studies via the wizard or the chat agent)
- **Role model:** N/A — single-tenant install, no auth surface (RelyLoop MVP1)

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md). No state-mutating endpoint added by this feature anyway; the existing `POST /api/v1/studies` write path is untouched (the values flowing into it just have different defaults).

## 7) Functional requirements

### FR-1: Wizard form pre-fills `max_trials = 200` by default
- Requirement:
  - The wizard's `useForm` `defaultValues` block in [`create-study-modal.tsx:125-141`](../../../../ui/src/components/studies/create-study-modal.tsx#L125-L141) **MUST** include `max_trials: 200`.
  - The wizard's `defaultValues` block **MUST NOT** include `time_budget_min` (stays empty by default; only Deep preset writes it).
- Notes: The existing form-input registrations at [lines 901, 913](../../../../ui/src/components/studies/create-study-modal.tsx#L901-L913) use `valueAsNumber: true` — type compatibility preserved.

### FR-2: Step-5 preset selector (button-group)
- Requirement:
  - Step 5 of the wizard **MUST** render a preset selector above the numeric `max_trials` + `time_budget_min` + `parallelism` 3-column input grid.
  - The selector **MUST** be implemented as a horizontal row of 4 `<Button variant="outline" type="button">` elements with `aria-pressed={preset === '<value>'}` and `role="button"` (NOT a radio group — see §5 dep finding: no `<RadioGroup>` primitive exists). The semantics are mutually-exclusive selection; clicking one button sets `aria-pressed=true` on it and `aria-pressed=false` on the other three.
  - **`type="button"` is REQUIRED on every preset button.** Default `<button>` inside a form has `type="submit"` — clicking a preset button without `type="button"` would submit the wizard prematurely. The shadcn `Button` primitive forwards `type` to the native element but does not change the default. Locked per GPT-5.5 cross-model review cycle 2, Finding #2.
  - The selector **MUST** have exactly 4 options in this visual order: **Focused** / **Standard** / **Deep** / **Custom**.
  - The default selection on modal-open **MUST** be **Standard** (matching the FR-1 pre-fill).
  - Each preset button **MUST** show its label as `<Name> (<trial count>)` (e.g., "Focused (50)", "Custom" — Custom has no trial count) and `aria-label` matching the visible text.
  - The active button **MUST** be visually distinguishable (e.g., filled background via the shadcn `Button` `variant="default"` swap, or `data-active` attribute styled via Tailwind).
- Notes: The selector is pure frontend state — its value is NOT included in the `POST /api/v1/studies` request body. The button-group pattern is the locked alternative to `<RadioGroup>`; rationale in §5.

### FR-3: Preset value mapping
- Requirement: Selecting a preset **MUST** write to the form fields per this table:

| Preset | `max_trials` | `time_budget_min` | Rationale (per glossary `long` copy) |
|---|---|---|---|
| **Focused** | `50` | clear to empty | 1–2 param search space; smallest preset that AVOIDS `NopPruner` (the `< 50` threshold at `optuna_runtime.py:154-156` is exactly avoided — at `max_trials=50` MedianPruner activates with `n_warmup_steps=10`, leaving 40 trials of pruned-eligible TPE search) |
| **Standard** (default) | `200` | clear to empty | 3–5 param search space; the typical shape. ~1 min on the dev stack with default parallelism. |
| **Deep** | `1000` | `480` (8 hours, as safety cap) | 6+ param search space; the `time_budget_min` is a circuit breaker that almost never fires |
| **Custom** | (no write — preserves manual edits) | (no write — preserves manual edits) | Operator overrides; numeric fields are the source of truth |

- Notes: Focused and Standard EXPLICITLY clear `time_budget_min` (set it back to empty via `form.setValue('time_budget_min', '')`) so the visible-preset state matches the values about to be POSTed. **Bug guard:** without this, an operator switching Deep → Standard would silently submit Standard's `max_trials=200` plus Deep's stale `time_budget_min=480` — confusing and contradicts the preset's stated semantics (caught by GPT-5.5 cross-model review cycle 1, Finding #3). Only Custom preserves; the three named presets are authoritative writes for the two fields they cover.

### FR-4: Form-state transition rules
- Requirement:
  - **Preset → numeric write:** Selecting a non-Custom preset **MUST** call `form.setValue` for each field listed in FR-3's table, with `shouldDirty: true` so subsequent submit-validity checks see the new value.
  - **Manual edit → Custom:** When the operator manually edits `max_trials` or `time_budget_min` while a non-Custom preset is active, the selected button **MUST** jump to **Custom** (`aria-pressed=true` flips to Custom; the previously-pressed button flips to `aria-pressed=false`) so the displayed state matches the values about to be POSTed.
  - **Modal-open reset:** On every modal-open (per existing AC-12 modal-open reset in [`create-study-modal.tsx:162-167`](../../../../ui/src/components/studies/create-study-modal.tsx#L162-L167)), the selected button **MUST** reset to **Standard** and the `max_trials` field **MUST** reset to `200`.
- Notes: The "manual edit → Custom" detection uses a `useEffect` watching the two numeric fields; comparing the current values against the active preset's expected values is the trigger. Watchers must be debounced or use `useEffect` deps correctly to avoid render loops.

### FR-5: Refreshed glossary copy for `study.max_trials` and `study.time_budget_min`
- Requirement: The existing entries at [`glossary.ts:160-169`](../../../../ui/src/lib/glossary.ts#L160-L169) **MUST** be updated:

```typescript
'study.max_trials': {
  short:
    'Total trials to run before stopping. Sized by your search-space dimensionality: ~50 for 1–2 params, 200 for 3–5 params (typical), 500–1000 for 6+ params.',
  long:
    'TPE\'s diminishing returns kick in past these counts. With default parallelism=4 and ~1s/trial cost on a small query set, 200 trials completes in under a minute; on a managed cluster with a large query set it\'s more like 25 minutes (wall-clock estimates measured against the local dev stack — production clusters may vary).',
  ariaLabel: 'More information about max trials',
},
'study.time_budget_min': {
  short:
    'Wall-clock safety cap, in minutes. Optional. Set this only if you want a hard ceiling on a slow cluster.',
  long:
    'Trials in RelyLoop are typically cheap (subsecond against local stacks, seconds against managed clusters), so the binding stop is almost always max_trials. Use this as a circuit breaker on managed clusters where per-trial cost might unexpectedly balloon.',
  ariaLabel: 'More information about time budget',
},
```

- Notes: The cluster-shape calibration caveat ("measured against the local dev stack") was locked in the idea preflight § question 5. Spec implementation must keep that caveat in the `long` form.

### FR-6: System prompt update for the chat agent
- Requirement: The `prompts/orchestrator.system.md` create-study confirmation example at [line 78](../../../../prompts/orchestrator.system.md#L78) **MUST** change from `max_trials: 100` to `max_trials: 200`. A new sentence **MUST** be added to the Studies section reading:

  > When the user does not specify a stop condition, propose `max_trials=200` for typical 3–5 param search spaces. Scale to ~50 for 1–2 params and ~1000 for 6+ params. Use `time_budget_min` only as a safety cap on slow clusters; trials are usually cheap.

- Notes: The exact placement is within the existing tool-list section near [line 17](../../../../prompts/orchestrator.system.md#L17) "Studies (4)" bullet so the LLM reads it at tool-routing time, not deep in the prompt body.

### FR-7: Tooltip + preset description copy
- Requirement: Each preset button **MUST** render its label as `<Name> (<trial count>)` for Focused/Standard/Deep, or `Custom` for the manual-edit mode. The button-group container **MUST** have an `InfoTooltip` with `glossaryKey="study.preset"` referring to a new glossary entry (FR-8) — placed adjacent to a "Stop condition" group label `<Label>`.
- Notes: The button label text is the wire-value-shaped string for testability (e.g., the vitest assertion can locate "Focused (50)" by accessible name); the InfoTooltip is the discoverability layer for "what do these presets mean."

### FR-8: New glossary entry `study.preset`
- Requirement: A new entry **MUST** be added to [`glossary.ts`](../../../../ui/src/lib/glossary.ts):

```typescript
'study.preset': {
  short:
    'Sized stop-condition recommendation matching your search-space dimensionality.',
  long:
    'Focused (50 trials) — 1–2 params; smallest preset where MedianPruner activates (avoids the <50 NopPruner threshold). Standard (200) — 3–5 params, the typical case. Deep (1000 + 8h cap) — 6+ params, complex tuning. Custom — preserves manual edits.',
  ariaLabel: 'More information about study presets',
},
```

- Notes: This entry's `long` text is the canonical narrative referenced by the `InfoTooltip` on the radio group label.

### FR-9: Vitest coverage
- Requirement:
  - At least **1 vitest case** **MUST** assert that the wizard renders with `max_trials=200` in the input field after modal-open (Tier A regression guard).
  - At least **4 vitest cases** **MUST** assert preset behavior: (a) Focused writes `max_trials=50` AND clears `time_budget_min` to empty, (b) Standard writes `max_trials=200` AND clears `time_budget_min` to empty, (c) Deep writes `max_trials=1000` AND `time_budget_min=480`, (d) Custom mode preserves whatever values are in the numeric fields.
  - At least **2 transition vitest cases** **MUST** assert the bug-guard from cycle-1 Finding #3: (a) Deep → Standard transition clears `time_budget_min` from `480` back to empty (no stale value bleed), (b) Deep → Focused transition clears `time_budget_min` from `480` back to empty.
  - At least **1 vitest case** **MUST** assert the manual-edit-→-Custom transition: type a different `max_trials` while Standard is active, expect the Custom button's `aria-pressed` to flip to `true`.
  - At least **1 vitest case** **MUST** assert the modal-open reset: open, change preset to Deep, close, re-open, expect Standard re-selected and `max_trials=200`.

## 8) API and data contract baseline

N/A — no new endpoints, no new wire-value enums, no backend code change beyond the `prompts/orchestrator.system.md` file.

### 7.4 Enumerated value contracts

The preset value (`focused` / `standard` / `deep` / `custom`) is **frontend-only state** and is NOT sent over the wire. No backend allowlist exists; no source-of-truth file applies. The four preset names live in the modal component's `PRESET_VALUES` constant (TypeScript `const`) with a comment marking them as frontend-only.

## 9) Data model and state transitions

N/A — no schema changes. The existing `studies.config` JSONB column at [`backend/app/db/models/study.py`](../../../../backend/app/db/models/study.py) continues to store `{max_trials, time_budget_min, ...}` exactly as it does today. The change is in how the wizard populates the form before the operator clicks "Create study."

## 10) Security, privacy, and compliance

- **Threats:** none introduced. Default numeric values cannot trigger new failure modes that the existing client-side + server-side stop-condition validators don't already catch.
- **Controls:** the existing `_require_one_stop_condition` validator at [`schemas.py:578-586`](../../../../backend/app/api/v1/schemas.py#L578-L586) is the safety net against silent missing-stop-condition bugs.
- **Secrets/key handling:** N/A.
- **Auditability:** N/A — MVP1 pre-`audit_log`.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Step 5 of the existing create-study wizard modal at [`create-study-modal.tsx:776+`](../../../../ui/src/components/studies/create-study-modal.tsx#L776). The wizard is triggered from `/studies` page's "Create study" button (existing surface, unchanged).
- **Labeling taxonomy:**
  - Section heading on Step 5: existing ("Objective + config" per [`STEP_TITLES` line 112](../../../../ui/src/components/studies/create-study-modal.tsx#L112)).
  - New element label: **"Stop condition"** (group label for the preset radio).
  - Preset options: **Focused (50)** / **Standard (200)** / **Deep (1000)** / **Custom**.
  - Per-option helper text under each: 1-line rationale + wall-clock estimate.
- **Content hierarchy:** The preset radio sits **above** the existing numeric inputs row (`max_trials` / `time_budget_min` / `parallelism`). Primary: preset radio (visible). Secondary: numeric inputs (visible — preset writes to them, operator can edit directly).
- **Progressive disclosure:** The numeric inputs are always visible. The preset radio doesn't hide them — it pre-fills them. Operators who know what they want bypass the radio and edit directly (the radio auto-flips to Custom).
- **Relationship to existing pages:** Extends the existing wizard; replaces nothing.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| **"Stop condition" radio group label** | `study.preset` (new entry — see FR-8) | `info icon click` (`InfoTooltip`) | top | `study.preset` |
| **"Max trials" input** (existing) | Refreshed `study.max_trials` (FR-5) | `info icon click` (existing `InfoTooltip` per line 896) | top | `study.max_trials` |
| **"Time budget (min)" input** (existing) | Refreshed `study.time_budget_min` (FR-5) | `info icon click` (existing `InfoTooltip` per line 907) | top | `study.time_budget_min` |
| **"Parallelism" input** (existing, unchanged) | Existing `study.parallelism` | `info icon click` (existing) | top | `study.parallelism` |

All four tooltip entries trace back to `ui/src/lib/glossary.ts` keys — no inline strings.

### Primary flows

1. **Operator opens the wizard → reaches Step 5.** Sees Standard pre-selected, `max_trials=200` in the input field, `time_budget_min` empty. Clicks "Create study." Study created with `max_trials=200`.
2. **Operator opens the wizard → switches preset to Focused.** `max_trials` input flips to `50` (`shouldDirty: true`). Operator clicks "Create study." Study created with `max_trials=50`.
3. **Operator opens the wizard → switches to Deep.** `max_trials` flips to `1000`, `time_budget_min` flips to `480`. Operator clicks "Create study." Study created with both fields populated.
4. **Operator opens the wizard → manually types `300` into `max_trials`** (Standard preset was active). Radio auto-flips to **Custom**. Operator clicks "Create study." Study created with `max_trials=300`.
5. **Operator asks the chat agent to start a study without specifying a stop condition.** Per FR-6, the system prompt instructs the agent to propose `max_trials=200` in the `create_study` tool call payload (Standard preset's value). The LLM's choice is non-deterministic — the prompt guides the agent toward 200; AC-7 tests the prompt content, not the model's behavior.

### Edge / error flows

- **Operator clears `max_trials` to empty in Custom mode (no other stop condition set).** The existing client-side guard at [`create-study-modal.tsx:417-419`](../../../../ui/src/components/studies/create-study-modal.tsx#L417-L419) catches this — submit button disabled until at least one of the two fields is numeric > 0. No new error path.
- **Operator types `0` in `max_trials`.** Caught by the existing Pydantic `ge=1` constraint at [`schemas.py:569`](../../../../backend/app/api/v1/schemas.py#L569). Server returns 422; existing error path.
- **Operator types `100001` in `max_trials`.** Caught by the existing Pydantic `le=100_000` constraint. Server returns 422.
- **Preset write + immediate operator edit race.** If an operator clicks Deep then immediately starts typing in the `max_trials` field, the preset's `setValue` fires first (synchronous), then the keystrokes overwrite. Acceptable behavior — the manual edit wins, and the FR-4 "manual edit → Custom" watcher fires to flip the radio.

## 12) Given/When/Then acceptance criteria

### AC-1: Modal opens with `max_trials=200` and Standard preset selected
- **Given** the create-study modal is closed
- **When** the operator clicks "Create study" to open it
- **Then** Step 5 renders with the Standard preset button having `aria-pressed=true` AND the `max_trials` input value is `200`
- **Example:** `screen.getByLabelText(/Max trials/i)` returns an element with `value="200"`; `screen.getByRole('button', { name: /Standard \(200\)/ })` has `aria-pressed="true"`.

### AC-2: Selecting the Focused preset writes `max_trials=50`
- **Given** the wizard is open on Step 5 with Standard active (Standard button `aria-pressed=true`)
- **When** the operator clicks the Focused button
- **Then** `max_trials` flips to `50`, `time_budget_min` stays empty, `parallelism` stays at `4`; Focused's `aria-pressed=true` and Standard's flips to `false`
- **Example:** vitest assertion on form state + button aria-pressed after `userEvent.click(screen.getByRole('button', { name: /Focused/ }))`.

### AC-3: Selecting the Deep preset writes both `max_trials=1000` and `time_budget_min=480`
- **Given** the wizard is open on Step 5 with Standard active
- **When** the operator clicks Deep
- **Then** `max_trials` flips to `1000` AND `time_budget_min` flips to `480` (8 hours)
- **Example:** form state assertion on both fields.

### AC-4: Custom preset preserves manual edits
- **Given** the wizard is open on Step 5 with Standard active; operator has manually typed `333` in `max_trials`
- **When** the operator clicks the Custom radio explicitly (or the radio auto-flips per AC-5)
- **Then** `max_trials` stays at `333`; no preset-driven overwrite fires
- **Example:** type `333` in the input then click Custom — `max_trials` should still be `333`.

### AC-5: Manual edit while non-Custom preset is active flips the active button to Custom
- **Given** the wizard is open on Step 5 with Standard active (`max_trials=200`, Standard `aria-pressed=true`)
- **When** the operator clears the `max_trials` field and types `300`
- **Then** the Custom button's `aria-pressed` flips to `true` (without the operator clicking it) and Standard's flips to `false`
- **Example:** vitest user-event type sequence; assert `screen.getByRole('button', { name: /Custom/ })` has `aria-pressed="true"`.

### AC-6: Modal-open reset re-selects Standard
- **Given** the wizard was previously open, the operator changed preset to Deep, closed the modal
- **When** the operator opens the modal again
- **Then** Step 5 renders with Standard re-selected, `max_trials=200`, `time_budget_min` empty
- **Example:** open-close-open sequence in vitest with `<Dialog>` controlled state.

### AC-7: System prompt content shows `max_trials=200` as the recommended default
- **Given** the merged `prompts/orchestrator.system.md` file
- **When** an operator (or a contract grep) inspects the Studies-tools section + the create-study confirmation example
- **Then** both surfaces show `max_trials=200` (not `100`) AND the new "Studies-tools" sentence reads `"When the user does not specify a stop condition, propose max_trials=200 ..."` per FR-6
- **Example:** `grep -E 'max_trials[:=][[:space:]]*100($|[^0-9])' prompts/orchestrator.system.md` returns zero matches (the `($|[^0-9])` alternation catches `100` at end-of-line too); `grep -E 'max_trials[:=][[:space:]]*200($|[^0-9])' prompts/orchestrator.system.md` returns at least one match. The boundary guards against the `~1000 for 6+ params` substring in the new Studies-tools sentence — locked per GPT-5.5 cross-model review cycle 2, Finding #6 + cycle 3 EOL refinement.
- **Note:** This AC tests the *prompt content* — the deterministic, file-grep-verifiable surface that this feature changes. The LLM's *actual* `max_trials` choice on any given call is non-deterministic (system prompts guide; they don't constrain), so a "the LLM emitted 200" assertion would be flaky. AC re-shaped per GPT-5.5 cross-model review cycle 1, Finding #2.

### AC-8: Refreshed glossary copy renders in tooltips
- **Given** the wizard is open on Step 5
- **When** the operator clicks the InfoTooltip icon next to "Max trials"
- **Then** the tooltip renders the new FR-5 `short` copy
- **Example:** vitest `userEvent.click(maxTrialsInfoIcon); expect(screen.getByText(/Total trials to run.*1–2 params, 200/)).toBeVisible()`.

### AC-9: Backend Pydantic validator unchanged behavior
- **Given** a client (CLI, direct API, test fixture) POSTs to `/api/v1/studies` with `config = {}` (no stop condition)
- **When** the server-side validator runs
- **Then** the server returns HTTP 422 with `error_code = VALIDATION_ERROR` and message naming the `_require_one_stop_condition` failure mode
- **Example:** the existing contract test (if any — verify at impl time) keeps passing; no change to error path.

### AC-10: Preset value is NOT sent over the wire
- **Given** the operator submits the wizard with the Standard preset selected
- **When** the `POST /api/v1/studies` request fires
- **Then** the request body's `config` object contains `max_trials: 200` and NO field named `preset` / `focused` / `standard` / `deep`
- **Example:** vitest network spy on the POST body.

## 13) Non-functional requirements

- **Performance:** No measurable impact. The preset selector is a 4-button group; the form's render path is unchanged in shape.
- **Reliability:** No new failure modes. Existing client-side + server-side stop-condition validators are the safety net.
- **Operability:** No new logs, metrics, or alerts.
- **Accessibility:**
  - Preset selector uses a button-group of 4 `<Button>` elements with `aria-pressed` semantics. The button row **MUST** be wrapped in a `<div role="group" aria-labelledby="stop-condition-group-label">` and a sibling `<span id="stop-condition-group-label">Stop condition</span>` (or equivalent visible-label element) provides the accessible name for the group. A plain `<Label>` adjacent to buttons is NOT sufficient — screen readers don't associate `<Label>` with non-input elements. Group labeling shape locked per GPT-5.5 cross-model review cycle 1, Finding #4.
  - Each preset button has an accessible name matching its visible label (e.g., "Focused (50)") and `aria-pressed={preset === '<value>'}`.
  - Each tooltip has the existing `ariaLabel` from the glossary entry.
  - The active preset button must be programmatically focusable; tab order: preset buttons (Focused → Standard → Deep → Custom) → max_trials → time_budget_min → parallelism (matching visual order).

## 14) Test strategy requirements (spec-level)

- **Unit tests:** N/A — no pure backend logic added.
- **Integration tests:** N/A — no DB / service / endpoint change.
- **Contract tests:** N/A — no API contract change. The existing studies-API contract test at `backend/tests/contract/test_studies_api_contract.py` (verify file exists at impl time) keeps passing without modification.
- **Vitest (UI unit):** ≥10 cases per FR-9:
  - `ui/src/__tests__/components/studies/create-study-stop-conditions.test.tsx` (NEW file, or extend the existing modal test file if shorter).
    - AC-1 default Standard + 200
    - AC-2 Focused write (`max_trials=50` AND `time_budget_min` cleared)
    - AC-3 Deep write (both fields: `max_trials=1000` + `time_budget_min=480`)
    - AC-4 Custom preserve
    - AC-5 manual-edit-→-Custom flip
    - AC-6 modal-open reset
    - **Transition Deep → Standard** (regression for cycle-1 Finding #3 — `time_budget_min` clears from `480` to empty)
    - **Transition Deep → Focused** (same bug-guard, second transition path)
    - AC-8 refreshed glossary tooltip renders
    - AC-10 wire-shape (no `preset` field in POST body)
- **E2E (Playwright):** N/A — the preset-write behavior is tested at the vitest layer where it's deterministic and fast. Adding a Playwright case would only re-test the form mechanics already covered by vitest. The existing `ui/tests/e2e/studies.spec.ts` create-study flow stays green without modification.

## 15) Documentation update requirements

- `docs/01_architecture/` — none. (No new architecture surface.)
- `docs/02_product/` — `mvp1-user-stories.md` not affected (no new user story).
- `docs/03_runbooks/` — none. (No new operator action.)
- `docs/04_security/` — none.
- `docs/05_quality/` — none.
- `CLAUDE.md` — none. (No new convention or rule.)
- `state.md` — prepend post-merge per the standard finalization convention.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none — the change is operator-facing UX polish that ships in one PR.
- **Migration / backfill:** none — no schema changes.
- **Operational readiness gates:** none beyond standard CI green.
- **Release gate:** standard CI + Gemini Code Assist adjudication + final GPT-5.5 review per `impl-execute --all`. No staging deploy gate (RelyLoop MVP1 has no remote staging).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (form pre-fill 200) | AC-1, AC-6 | Story 1.1 — form `defaultValues` | `create-study-stop-conditions.test.tsx` | — |
| FR-2 (preset radio surface) | AC-1 | Story 1.2 — preset radio component | `create-study-stop-conditions.test.tsx` | — |
| FR-3 (preset → field mapping) | AC-2, AC-3, AC-4 | Story 1.3 — preset value writes | `create-study-stop-conditions.test.tsx` | — |
| FR-4 (state transitions) | AC-4, AC-5, AC-6 | Story 1.4 — state transition watchers | `create-study-stop-conditions.test.tsx` | — |
| FR-5 (glossary copy refresh) | AC-8 | Story 1.5 — glossary updates | existing `glossary.test.ts` if present | `glossary.ts` |
| FR-6 (system prompt update) | AC-7 | Story 1.6 — prompt edit | manual verification | `prompts/orchestrator.system.md` |
| FR-7 (tooltip copy on preset radio) | AC-8 | bundled with Story 1.2 | `create-study-stop-conditions.test.tsx` | — |
| FR-8 (new `study.preset` glossary entry) | AC-8 | bundled with Story 1.5 | existing `glossary.test.ts` | `glossary.ts` |
| FR-9 (vitest coverage) | AC-1..AC-10 | bundled per story | `create-study-stop-conditions.test.tsx` | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1..AC-10) pass in CI.
- [ ] Vitest cases listed in §14 are written and green.
- [ ] Backend contract test for `POST /api/v1/studies` (unchanged) still passes.
- [ ] `state.md` prepended post-merge per the standard finalization convention.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None. The idea preflight locked 4 of the 5 spec-time questions (with the 5th — preset form-state-transition semantics — locked in FR-4 above as "manual edit flips radio to Custom"). All five are now decisions, not questions:

### Decision log

- **2026-05-23** — **Tier A + Tier B ship as one PR**, not split. Rationale: Tier A alone is operator-invisible polish (a different number in a pre-filled field); Tier B is the actual UX addition. Splitting would mean two PRs for what is conceptually one change. (Idea preflight question 1.)
- **2026-05-23** — **Default `max_trials = 200`.** Rationale: TPE convergence for 3–5 param search spaces (the typical shape per `query_template.declared_params` cardinality). 100/250/500 considered and rejected — 200 sits above MedianPruner's `< 50` auto-disable threshold by a comfortable margin and below the diminishing-returns zone. (Idea preflight question 2.)
- **2026-05-23** — **Preset names: Focused / Standard / Deep / Custom.** Rationale: search-space-fit framing (matches the idea's TPE convergence rationale). Alternative "Fast / Default / Thorough / Custom" reads as duration framing; "Quick / Recommended / Long / Custom" inverts the framing entirely. Search-space-fit framing wins. (Idea preflight question 3.)
- **2026-05-23** — **Preset selector lives above the numeric fields on Step 5; Standard selected by default; selecting a preset writes via `form.setValue` with `shouldDirty: true`; manual edit of a numeric field flips the radio to Custom.** Rationale: keeps the visible state in sync with the values about to be POSTed. (Idea preflight question 4 + FR-4.)
- **2026-05-23** — **Glossary cluster-shape ranges (Tier A bullet 3): keep the concrete dev-stack-calibrated wall-clock numbers in the `long` form with a caveat that they're measured against the local dev stack.** Rationale: concrete numbers are more useful to operators forming budgeting expectations than abstract framings; the caveat protects against mis-calibrating production. (Idea preflight question 5.)
