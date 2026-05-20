# Feature Specification — Create-Study Search-Space Builder (Step 4 visual editor)

**Date:** 2026-05-20
**Status:** Draft
**Owners:** Product — Relevance Engineer persona; Engineering — Frontend (Next.js / shadcn / TanStack Query)
**Related docs:**
- [`idea.md`](./idea.md) (this directory)
- [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/feature_spec.md) — foundational chore that shipped the defaults heuristic, validation mirror, and forward-compat glossary entries this feature consumes
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — §"Form dropdown primitive" defines the form-side primitives (`EntitySelect`) and modal-test conventions this spec extends
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — `studies.search_space` JSONB column shape

**Depends on:** [`chore_create_study_wizard_polish`](../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) (PR #157 `075c46b`, merged 2026-05-20 — **landed in `main`**).

---

## 1) Purpose

- **Problem.** Step 4 of the create-study wizard is a raw JSON textarea at [`ui/src/components/studies/create-study-modal.tsx:546-553`](../../../../ui/src/components/studies/create-study-modal.tsx#L546-L553). `chore_create_study_wizard_polish` pre-fills the textarea with sensible defaults via [`buildStarterSearchSpace()`](../../../../ui/src/lib/search-space-defaults.ts#L125), adds a client-side validation mirror at [`create-study-modal.tsx:265-299`](../../../../ui/src/components/studies/create-study-modal.tsx#L265-L299), and ships three forward-compat glossary entries at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94). Despite those affordances the surface still asks the relevance engineer to type numeric bounds, recognize log-uniform applicability, and estimate cardinality in their head while the 10⁶ cap (enforced server-side at [`backend/app/domain/study/search_space.py:110-118`](../../../../backend/app/domain/study/search_space.py#L110-L118)) silently disqualifies their submission.
- **Outcome.** Step 4 is rendered as a per-parameter visual editor — type selector, numeric inputs with spinners for `low`/`high`, a `log` toggle gated on `low > 0`, a multi-add chip input for `categorical.choices`, a live cardinality counter that highlights the 10⁶ cap, and inline validation per row. The canonical wire-format JSON remains the source of truth (round-trips bidirectionally between builder ↔ textarea); the builder is purely a presentation layer over the existing `search_space_text: string` form field.
- **Non-goal.** No backend changes. No template-schema extension (per-param descriptions stay deferred — see §19 open question 3). No two-handle range sliders. No engine-aware default overrides — the heuristic table at [`search-space-defaults.ts:38-55`](../../../../ui/src/lib/search-space-defaults.ts#L38-L55) is the only source of starter values, unchanged. The "Add custom param" affordance is intentionally **disabled** with a tooltip pointing users to the template detail page; templates remain the only mechanism for declaring tunable parameters.

## 2) Current state audit

### Existing implementations

- [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — 847 LOC modal. Step 4 (zero-indexed `step === 3`) lives at lines 530-594. Touch points the builder must integrate with:
  - **Form field:** `search_space_text: string` declared at line 85; default `'{}'` at line 124.
  - **Auto-fill effect:** lines 205-259. Keyed on `templateBody`; replaces empty/auto-signature content immediately, prompts an Undo toast for user-edited content. Builder MUST consume the same `search_space_text` string the effect writes — no parallel state path.
  - **Validation mirror:** `validateSearchSpaceAgainstTemplate()` at lines 265-299; called from `handleSearchSpaceBlur()` (306-309) and `handleStep4Next()` (311-317). Builder rows MUST surface the same `searchSpaceError` state via the existing `<p role="alert" data-testid="cs-search-space-error">` at lines 557-566.
  - **Placeholder warning:** `placeholderWarning` boolean state + `<p data-testid="cs-placeholder-warning">` at lines 567-575; fires when `__placeholder__` sentinel is present (emitted by `simpleFormSpec('string')` at [`search-space-defaults.ts:77`](../../../../ui/src/lib/search-space-defaults.ts#L77)).
  - **Template fetch recovery:** `templateFetchStatus` state machine at lines 184-200. 404 bumps to Step 3; transient surfaces a Retry button at lines 576-591. Builder renders only a non-interactive placeholder card (no rows, no header, no "Add custom param") while `templateFetchStatus !== 'ok'` and `templateBody` is null — the existing transient/Retry UI stays in place. See AC-11.
  - **Tooltips:** `<InfoTooltip glossaryKey="study.search_space" />` (line 539) and `<HelpPopover glossaryKey="study.search_space" />` (line 555) already wired. The three sub-keys (`.param_spec`, `.log`, `.cardinality`) at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94) are short-only and intended for per-row consumption.

- [`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts) — 189 LOC pure module. Builder consumes the existing exports verbatim:
  - `ParamSpec` discriminated union (lines 23-26) — same shape as builder row state.
  - `SearchSpaceJson` (line 29) — same shape as form-state JSON.
  - `HEURISTIC_RULES` (lines 38-55) — naming-convention table used to derive initial type-selector value when a row is rendered fresh.
  - `buildStarterSearchSpace()` (line 125) — unchanged; still consumed by the auto-fill effect.
  - `estimateCardinality()` (line 92) — consumed for the header counter. Per-param contribution math is factored out as a new sibling helper (`estimateParamCardinality(spec: ParamSpec): number`) in the same file.

- [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py) — 267 LOC. **No backend changes**. The discriminated union at lines 83-89 (`FloatParam | IntParam | CategoricalParam`) is the wire-format source of truth. The cardinality cap at lines 110-118 and `validate_against_template()` at lines 199-242 remain the canonical server-side gate.

- [`ui/src/lib/glossary.ts:62-94`](../../../../ui/src/lib/glossary.ts#L62-L94) — `study.search_space` dual entry (short + long) plus three short-only subkeys (`.param_spec`, `.log`, `.cardinality`) explicitly added as builder-row hooks. No glossary changes required.

- [`ui/src/__tests__/components/studies/create-study-modal.*.test.tsx`](../../../../ui/src/__tests__/components/studies/) — 7 existing component test files covering auto-fill, undo, client-side validation, metric/k tier rendering, template fetch error, zero-declared template guard. **Every existing test must continue to pass** — the canonical JSON textarea remains visible (split view) and bound to the same form field, so the existing assertions on `cs-search-space` textarea + `cs-search-space-error` + `cs-placeholder-warning` test IDs stay valid.

- [`ui/tests/e2e/studies-create-validation.spec.ts`](../../../../ui/tests/e2e/studies-create-validation.spec.ts) — real-backend e2e walking Steps 1–3 and asserting Step-4 auto-fill + client-side rejection of an unknown-param typo. Must continue to pass; existing test IDs preserved.

### Navigation and link impact

None. This feature is a presentational change inside the existing create-study modal at `/studies` (modal triggered by `data-testid="open-create-study"` on [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx)). No new routes, no link target changes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.test.tsx` | `cs-search-space` textarea content assertions | ~5 | No change — split-view keeps textarea visible. Auto-fill writes still go to `search_space_text`. |
| `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx` | `cs-search-space-error` assertions | ~3 | No change — error surface unchanged. |
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.undo.test.tsx` | Undo toast + `setValue('search_space_text', priorText)` | ~2 | No change — undo path still writes to `search_space_text`; builder re-renders from the new string. |
| `ui/src/__tests__/components/studies/create-study-modal.template-fetch-error.test.tsx` | `cs-template-retry` block | ~2 | No change — builder is conditional on `templateBody`. |
| `ui/src/__tests__/components/studies/create-study-modal.zero-declared.test.tsx` | `cs-zero-declared-error` | ~1 | No change — gating happens on Step 3 transition. |
| `ui/src/__tests__/components/studies/create-study-modal.metric-k.test.tsx` | Step-5 metric/k rendering | ~4 | No change — Step 5 untouched. |
| `ui/tests/e2e/studies-create-validation.spec.ts` | Real-backend walk through Steps 1–3 → Step 4 auto-fill → unknown-param typo | ~2 | No change — typing into `cs-search-space` textarea still drives validation (the builder mirrors it on every keystroke). |
| `ui/src/__tests__/lib/search-space-defaults.test.ts` | `buildStarterSearchSpace` + `HEURISTIC_RULES` parity | ~12 | No change — module is unchanged except for a new `estimateParamCardinality()` export. |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | Python ↔ TS parity via shared JSON fixture | ~1 | Augment with `estimateParamCardinality()` per-param assertions to keep the factored helper honest. |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | Lint guard scanning for inline `<SelectItem value="<literal>">` matching backend enums | full-tree scan | No change — `ParamSpec.type` values (`'float'`/`'int'`/`'categorical'`) are NOT in [`enums.ts`](../../../../ui/src/lib/enums.ts), so the lint guard does not flag them. Spec adds a sibling parity test (see §14). |

### Existing behaviors affected by scope change

- **Textarea remains canonical, gains a sibling.** Today the user edits JSON in `<Textarea data-testid="cs-search-space">`. New: on desktop (≥1024px) the builder renders to the LEFT, the textarea remains on the RIGHT — both bound to the same `search_space_text` form field. On viewports <1024px the surfaces tab between each other with a "Builder | JSON" toggle (default: Builder). Decision needed: No — locked default per idea §"Open questions" answer 1.

- **Builder ↔ textarea round-trip on every change.** Today the user types into the textarea; on blur, `validateSearchSpaceAgainstTemplate()` fires. New: every builder row edit (a) parses the textarea into `SearchSpaceJson`, (b) applies the row mutation, (c) `JSON.stringify(..., null, 2)` and writes back via `form.setValue('search_space_text', ...)`. Conversely, every keystroke in the textarea (a) parses, (b) renders into builder rows. **Invariant: whichever surface the user edits last is the source of truth for the next render.** If the textarea is malformed JSON, the builder switches to a non-interactive "JSON has syntax errors — fix in the textarea to use the builder" placeholder with the parse error inline. Decision needed: No — locked default per idea §"Open questions" answer 2.

- **Per-row error surface vs single error block.** Today client-side validation surfaces a single `searchSpaceError` string in one `<p data-testid="cs-search-space-error">` populated by `validateSearchSpaceAgainstTemplate()` at [`create-study-modal.tsx:265-299`](../../../../ui/src/components/studies/create-study-modal.tsx#L265-L299), which checks unknown-param + missing-declared-param + JSON parse — **NOT cardinality**. New: row-level errors (`low >= high`, `log: true with low <= 0`, empty `choices`) render inline within each row. The two existing cross-row error categories (unknown-param + missing-declared-param) continue to surface in the existing single block. Cardinality is **not** added to that block — it's surfaced solely via the new header counter per FR-7 (warning-only; the server-side `_check_cardinality` at [`search_space.py:111-118`](../../../../backend/app/domain/study/search_space.py#L111-L118) remains the authoritative blocking gate). Existing test IDs preserved; new per-row test IDs added (`cs-row-error-{paramName}`); new row-container test ID `cs-param-row-{paramName}` (see AC-1).

- **"Add custom param" button.** Today: no such affordance. New: the builder shows a **disabled** "Add custom param" button with a tooltip explaining that tunable params come from the template, and a link to the template detail page (`/templates/{template_id}`). This reinforces the existing `SEARCH_SPACE_UNKNOWN_PARAM` error (raised by [`search_space.py:140`](../../../../backend/app/domain/study/search_space.py#L140)) without trying to bypass it. Decision needed: No — disabled by design.

---

## 3) Scope

### In scope

1. **`<SearchSpaceBuilder>` component** under `ui/src/components/studies/search-space-builder/` rendering one row per declared parameter, bound bidirectionally to the existing `search_space_text: string` form field via parse/stringify.
2. **Per-row controls:**
   - Read-only param **name** chip with `declared_params[name]` simple-form badge (e.g., `name: boost_title  [float]`).
   - **Type selector** — three-option `<Select>` with values `float` / `int` / `categorical` (matches [`ParamSpec` discriminator](../../../../backend/app/domain/study/search_space.py#L83-L89)).
   - For `float`/`int`: `<Input type="number">` for `low` and `high`; native browser spinners.
   - For `float` only: `log` toggle (native `<input type="checkbox">` — same pattern as [`data-table-column-visibility.tsx`](../../../../ui/src/components/common/data-table-column-visibility.tsx); disabled when `low <= 0` with title attribute explaining why; the spec deliberately does NOT introduce a new shadcn Switch primitive).
   - For `categorical`: a multi-add input that builds the `choices` array as removable chips. Accepts strings, numbers (parsed as numbers when numeric), and booleans (`true`/`false` literal). Empty `choices` is invalid.
   - Per-row cardinality counter ("≈ 100 states" for floats; `high - low + 1` for ints; `choices.length` for categoricals).
3. **Header cardinality counter** — total search-space cardinality computed by `estimateCardinality()` (existing TS port at [`search-space-defaults.ts:92`](../../../../ui/src/lib/search-space-defaults.ts#L92)). Turns red when total exceeds 10⁶, identifies the largest-contribution param as a hint.
4. **Split-vs-tab layout** — split view on ≥1024px (`md:` Tailwind breakpoint is 768; the spec uses `lg:1024` per Tailwind's default), tab view on <1024px. The canonical JSON textarea stays visible/accessible on every viewport so the user never loses access to the wire-format source of truth.
5. **Inline per-row validation** mirroring the same predicates Pydantic enforces server-side:
   - `low < high` (float) / `low <= high` (int) — see `_check_bounds` at [`search_space.py:45-51`](../../../../backend/app/domain/study/search_space.py#L45-L51) (float) and [`:63-67`](../../../../backend/app/domain/study/search_space.py#L63-L67) (int).
   - `log: true` requires `low > 0` — see `_check_bounds` at [`search_space.py:49-50`](../../../../backend/app/domain/study/search_space.py#L49-L50).
   - `categorical.choices` non-empty — enforced by `Field(min_length=1)` at [`search_space.py:80`](../../../../backend/app/domain/study/search_space.py#L80).
6. **Disabled "Add custom param" button** with tooltip + Next.js `<Link>` to `/templates/{template_id}`.
7. **Source-of-truth parity test** for `ParamSpec.type` wire values at `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx`. Asserts the builder's type-selector option array is the literal `['float', 'int', 'categorical'] as const` matching the backend discriminator — keyed off a small grep-the-backend-file fixture so adding a fourth `ParamSpec` variant (e.g., `LogIntParam` in a future spec) fails the test and forces the spec discussion.
8. **Per-row tooltips wired to existing glossary subkeys** — `.param_spec` on the type selector, `.log` on the log toggle, `.cardinality` on the per-row + header counters.
9. **Unit + component + e2e tests** per the matrix in §14.

### Out of scope

- Backend schema, migration, or service changes (zero backend LOC).
- Template-schema extension for per-param descriptions (deferred — separate idea per §19).
- Dual-handle range sliders (recommended numeric inputs + spinners per idea §"Open questions" answer 4; revisit only if usage feedback warrants).
- Engine-aware default overrides (`HEURISTIC_RULES` is unchanged).
- A new shadcn Switch primitive (use native `<input type="checkbox">` per existing pattern at `data-table-column-visibility.tsx`).
- The `__placeholder__` sentinel handling in the builder UI — the existing placeholder warning at `create-study-modal.tsx:567-575` keeps firing on the global form state; the builder simply renders a single-choice categorical row labeled `[placeholder]` and lets the user replace it via the chip input.
- A multi-objective search space (deferred to MVP2+ per `infra_optuna_eval` spec; the `SearchSpace` model already gates on `min_length=1` for `params`, so the builder is forward-compatible with multi-param spaces today).
- "Reset to defaults" affordance inside the builder. The existing per-template auto-fill effect already handles template changes; the user can manually clear the textarea to re-trigger auto-fill if needed.

### API convention check

This feature adds **zero new endpoints** and modifies none. The existing `POST /api/v1/studies` endpoint at [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) continues to be the only consumer of the assembled `search_space` dict. The builder is a pure-frontend presentation layer.

- **Endpoint prefix convention:** N/A (no new endpoints).
- **Router namespace for this feature's endpoints:** N/A.
- **HTTP methods for CRUD:** N/A.
- **Error envelope shape:** N/A — server-side errors continue to flow through the existing path (`SEARCH_SPACE_UNKNOWN_PARAM` / `SEARCH_SPACE_MISSING_DECLARED_PARAM` / `INVALID_SEARCH_SPACE` per [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py)).
- **Auth error shape:** N/A — MVP1 has no auth surface.

### Phase boundaries

Single-phase feature. No deferred Phase 2.

> **Deferred phase tracking:** N/A — no phase beyond Phase 1.

## 4) Product principles and constraints

- **The canonical JSON wire format is the source of truth for rendered rows.** Builder row content is computed on every render by parsing `search_space_text`; builder edits write back via `JSON.stringify(..., null, 2)`. The exception — narrowly scoped — is the **ephemeral cross-type stash** allowed by FR-2: when the user switches a row's type via the type selector, the prior row's spec is stashed in a component-local `useRef` keyed by `paramName`. The stash is **NOT canonical**; it never participates in submit, JSON serialization, or validation. **Stash invalidation rules (mandatory):** (a) any textarea-driven keystroke that mutates the row's spec clears that row's stash entry, (b) a template-change event (`templateBody` ref changes) clears the full stash map, (c) the Undo toast action clears the stash for any param it restores, (d) closing the modal clears the entire stash map (component unmount). The vitest builder-edits test suite asserts each invalidation rule.
- **Server-side validation remains the authoritative gate.** Every client-side predicate is a UX affordance; if a builder row passes but Pydantic rejects, the existing `INVALID_SEARCH_SPACE` error path still surfaces the rejection. Builder predicates are intentionally a strict subset of Pydantic's — never tighter (e.g., the builder MUST allow `int` `low == high`, which Pydantic accepts).
- **Bidirectional round-trip is semantically loss-less for well-formed JSON.** Parsing and re-stringifying valid `SearchSpace` JSON produces a **semantically equivalent** object (`JSON.parse(after) ≡ JSON.parse(before)` by deep equality) but NOT necessarily textually identical output — JSON serializes `10.0` as `10`, drops the trailing `.0` on whole-number floats, normalizes exponent notation, and emits a deterministic 2-space indent. The invariant is therefore: "(a) `deepEqual(JSON.parse(stringify(parse(s))), JSON.parse(s))` for every valid `s`, AND (b) on first canonical pass the textarea content stabilizes to the `JSON.stringify(..., null, 2)` normal form — subsequent parse-then-stringify cycles are textually idempotent." **Vitest parity test required** at `ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx` exercising **11 representative fixture shapes**: (1) boost-only float, (2) mixed float+int, (3) fuzziness categorical, (4) log float, (5) log float with `low <= 0` (intentional invariant violation — builder accepts the JSON but the row error fires), (6) multi-param hitting cardinality cap, (7) placeholder categorical (the `__placeholder__` sentinel), (8) empty `params` object `{"params": {}}` (rows show as unset; NOT a placeholder mode), (9) duplicate categorical choices `{"choices": ["AUTO", "AUTO", "BM25"]}` (anchored to FR-5's no-dedup rule), (10) numeric normalization `{"high": 10.0}` → `{"high": 10}`, (11) exponent normalization `{"low": 1e-3}` → `{"low": 0.001}`. **Note: malformed JSON (unparseable) is NOT a round-trip fixture** — that case is covered by FR-9's non-interactive placeholder rule and AC-12, not by round-trip parity.
- **No new dependencies.** No shadcn Switch, no slider library, no drag-and-drop. Native HTML primitives + existing shadcn Select/Input/Label/Tooltip are sufficient.
- **Accessibility per existing form patterns.** Every `<Input>` has a `<Label htmlFor>`; row errors use `role="alert" aria-live="polite"` like the existing `cs-search-space-error`; the "Add custom param" button uses `aria-disabled="true"` WITHOUT native `disabled` so it remains focusable and the tooltip is keyboard-discoverable (see FR-10).

### Anti-patterns

- **Do not** introduce a parallel `search_space: ParamSpec` form field. The form continues to carry `search_space_text: string`; the builder is a controlled component over it. Reason: the existing auto-fill effect, validation mirror, undo flow, and submit serialization all bind to `search_space_text`. A parallel field would cascade across ~5 useEffect call sites and the `autoFillSignatures` set, multiplying breakage risk for zero functional gain.
- **Do not** make builder predicates stricter than Pydantic's. E.g., refusing `int` `low == high` would block a valid one-value search space the backend would accept. Reason: each tightening creates a UI-only false positive that the server-side gate would never have raised.
- **Do not** add a new shadcn Switch primitive for the `log` toggle. Reason: native `<input type="checkbox">` is the established pattern (`data-table-column-visibility.tsx`) — adding a new dep is out of scope and would require a separate spec.
- **Do not** introduce a slider primitive for `low`/`high`. Reason: log-scale sliders are a pixel-precision UX trap (jumping from 0.5 to 10 in 100 px gives ~5%-quantile steps near 0.5; users cannot land on round values). Idea §"Open questions" answer 4 locks numeric inputs + spinners for the MVP.
- **Do not** persist builder UI state (active tab on narrow viewports, advanced disclosure expansion) across modal closes. Reason: every modal open starts from a clean Step 1 → … walk; UI persistence creates ghost-state surprises when the user reopens after a session refresh.
- **Do not** call the backend for any builder-side validation. Reason: the cross-param identity checks (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) are already mirrored client-side in `validateSearchSpaceAgainstTemplate()`. The 10⁶ cardinality cap is NOT mirrored client-side as a blocker (only as a header-counter warning per FR-7) — the server-side `_check_cardinality` at [`search_space.py:111-118`](../../../../backend/app/domain/study/search_space.py#L111-L118) is the authoritative gate, surfaced via the existing `INVALID_SEARCH_SPACE` envelope on submit. A second round-trip per keystroke for any of these would burn API capacity for the same answer.
- **Do not** silently auto-correct user JSON. Reason: if the user types `low: 10, high: 5` (inverted), the builder must surface the row error — not silently swap them. Silent correction destroys typed mental models.
- **Do not** use `<SelectItem value="float">` / `value="int"` / `value="categorical"` inline literals if any of those values ever land in [`enums.ts`](../../../../ui/src/lib/enums.ts) in a later spec. Reason: the `form-select-discipline.test.tsx` lint guard would then fire. For now `ParamSpec.type` values are NOT in `enums.ts`, so inline literals are permitted — but the option list MUST carry the source-of-truth comment per §7.4.

## 5) Assumptions and dependencies

- **Foundational dependency: `chore_create_study_wizard_polish` is merged** (PR #157 `075c46b`, 2026-05-20). The builder consumes [`HEURISTIC_RULES`](../../../../ui/src/lib/search-space-defaults.ts#L38-L55), [`buildStarterSearchSpace()`](../../../../ui/src/lib/search-space-defaults.ts#L125), [`estimateCardinality()`](../../../../ui/src/lib/search-space-defaults.ts#L92), [`validateSearchSpaceAgainstTemplate()`](../../../../ui/src/components/studies/create-study-modal.tsx#L265-L299), and the three glossary subkeys at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94). All landed.  
  - Status: implemented.  
  - Risk if missing: hard block (would have to fork the heuristic, port the cardinality estimator a second time, and duplicate the glossary subkeys).

- **No cross-feature soft dependency.** The two sibling specs the idea calls out for composition are read-only:
  - [`feat_study_clone_from_previous`](../feat_study_clone_from_previous/) — when the clone lands, it pre-fills the same `search_space_text` form field; the builder renders the cloned params transparently.
  - [`feat_agent_propose_search_space`](../feat_agent_propose_search_space/) — when the agent lands, it writes to the same form field via a tool dispatch; the builder renders the agent's proposal transparently.
  - Status (both): not implemented; not required for this spec.

- **No engine adapter coupling.** The builder operates on the `dict[str, ParamSpec]` shape, which is engine-agnostic by design (see [`adapters.md`](../../../01_architecture/adapters.md)). Per-engine defaults are deliberately out of scope.

- **No LLM dependency.** Pure-frontend; no `OPENAI_API_KEY`, no streaming, no tool dispatch.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer creating a new study via the `/studies` page → "Create Study" modal → Step 4.
- **Role model:** N/A — MVP1 is single-tenant, no auth surface (per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. The builder is a pure presentation layer over an existing form field; even after MVP2 audit instrumentation lands on `POST /api/v1/studies`, the builder requires no per-row event emission (it never makes its own backend call).

## 7) Functional requirements

### FR-1: Builder renders one row per declared parameter

- Requirement:
  - The system **MUST** derive its row set from `templateBody.declared_params` keys — exactly one row per declared parameter, in `Object.keys(templateBody.declared_params)` iteration order. This is the **single source of truth** for which rows exist. The textarea's parsed `params` dict supplies each row's current spec content, NOT the row identity.
  - The system **MUST** match each row to its parsed-JSON spec by exact key. If a row's name is not present in the parsed JSON (e.g., the user manually deleted the row from the textarea), the builder renders the row as **"empty / unset — type to populate"** with the type selector defaulting to whatever `simpleFormSpec(declared_params[name])` would emit but no `low`/`high`/`choices` content; the row contributes nothing to the textarea until the user touches it.
  - The system **MUST NOT** render rows for keys present in the parsed JSON but absent from `declared_params` (such "extra" params surface through the existing single error block via `validateSearchSpaceAgainstTemplate()` — the unknown-param check fires server-side too).
  - The system **MUST** render the parameter name as a read-only chip alongside a small badge showing `declared_params[name]` simple-form (`int` / `float` / `bool` / `string`).
  - The system **MUST NOT** allow the user to add or remove rows. The "Add custom param" affordance (FR-10) is rendered non-disabled-but-non-actionable (per FR-10 a11y rules) pointing at the template detail page.
- Notes: For an empty `search_space_text` (initial mount before the auto-fill effect fires, or user-cleared content), the builder renders the row set keyed off `templateBody.declared_params` with each row in "empty / unset" state. The placeholder ("Pick a template to populate the builder") only renders when `templateBody` is null AND the textarea is empty.

### FR-2: Type selector drives row sub-shape

- Requirement:
  - The system **MUST** render a 3-option `<Select>` with the values `float` / `int` / `categorical` (the exact `ParamSpec.type` discriminator wire values from [`search_space.py:83-89`](../../../../backend/app/domain/study/search_space.py#L83-L89)).
  - The system **MUST** carry a source-of-truth comment immediately above the option array: `// Values must match backend/app/domain/study/search_space.py ParamSpec discriminator`.
  - The system **MUST** ship a parity test at `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx` that reads `backend/app/domain/study/search_space.py` and asserts the option array matches the discriminator literals one-for-one.
  - The system **MUST** preserve the user's prior row spec across type-switch sessions via the ephemeral cross-type stash defined in §4. Implementation: a `Map<paramName, {float?: FloatSpec, int?: IntSpec, categorical?: CategoricalSpec}>` held in a `useRef`, NOT in component state and NOT serialized to `search_space_text`. When the user switches from `float → int`, the current `FloatSpec` is stashed under `paramName.float` and the new row spec is initialized from `paramName.int` if present (else from `simpleFormSpec(declared_params[paramName])`).
  - The system **MUST** invalidate stash entries per the rules in §4 (textarea keystroke on the row's spec, template change, Undo, modal close). The vitest builder-edits suite asserts each invalidation rule.
  - The system **MUST NOT** persist the stash to `search_space_text`, to `localStorage`, to React Hook Form state, or to any other reachable surface. The stash is component-instance-scoped only.

### FR-3: Float/int rows expose low/high with spinners

- Requirement:
  - The system **MUST** render `<Input type="number" data-testid="cs-row-{name}-low" />` and `<Input type="number" data-testid="cs-row-{name}-high" />` with `step` attributes that match the type (`step="any"` for float, `step="1"` for int).
  - The system **MUST** render an inline row error when `low >= high` (float) or `low > high` (int), mirroring the Pydantic predicate from `_check_bounds`.
  - The system **MUST** debounce the textarea round-trip on numeric input — write back on `onBlur` (synchronous) AND with a 200ms `setTimeout` on `onChange` (debounced). Cancel any pending timeout on unmount.
- Notes: Native browser spinners are sufficient; no custom up/down controls. Browsers that suppress spinner UI (Safari) still accept arrow-key increment.

### FR-4: Log toggle on float rows

- Requirement:
  - The system **MUST** render a `<input type="checkbox" data-testid="cs-row-{name}-log" />` only on rows whose type is `float`.
  - The system **MUST NOT** use the native HTML `disabled` attribute on the checkbox (which would block both check-on and check-off, contradicting the gating semantic). Instead the system **MUST** intercept the `onChange` handler and refuse the `false → true` transition when the row's current `low <= 0` — the handler returns early without calling `form.setValue`, and the row surfaces the "Log scale requires low > 0" inline error. The check-off transition (`true → false`) is always honored.
  - The system **MUST** set `aria-disabled="true"` and `title="Log scale requires low > 0"` on the checkbox whenever `low <= 0` (regardless of current checked state) so the constraint is discoverable via screen reader and hover tooltip while the control remains focusable and clickable for the check-off path.
  - The system **MUST** surface the row error "Log scale requires low > 0" (UI text; the Pydantic message is "log-uniform float param: low must be > 0 (got X)") in two cases: (a) the user attempts the blocked transition; (b) the row's current state is `log: true` AND `low <= 0` (catches the case where the user sets `log` first then lowers `low`).
- Notes: This mirrors `FloatParam._check_bounds` at [`search_space.py:49-50`](../../../../backend/app/domain/study/search_space.py#L49-L50). The builder MAY shorten the UI text to "Log scale requires low > 0" for brevity (anti-pattern: do not invent a different invariant — only the wording differs).

### FR-5: Categorical rows expose a chip-input for choices

- Requirement:
  - The system **MUST** render a chip-input that accepts free-text entries: pressing Enter or comma adds the current input as a chip; clicking the `×` on a chip removes it.
  - The system **MUST** auto-coerce typed values: `"true"`/`"false"` → boolean; numeric strings (`/^-?\d+(\.\d+)?$/`) → number; everything else → string. This matches what `CategoricalParam.choices: list[str | int | float | bool]` at [`search_space.py:80`](../../../../backend/app/domain/study/search_space.py#L80) accepts.
  - The system **MUST** surface the row error "choices: at least 1 choice required" when the choices array would empty.
  - The system **MUST NOT** auto-deduplicate chips. The Pydantic schema enforces `min_length=1` only — it does NOT require unique choices, so a textarea-supplied `{"choices": ["AUTO", "AUTO"]}` is wire-valid and the builder must round-trip it semantically (per §4 invariant). When the user manually adds a duplicate chip via the chip input, the system **MAY** render a UI-only amber warning ("Duplicate value '<v>' — Optuna will treat them as one trial") but **MUST NOT** automatically remove the duplicate. The user controls the array contents.
  - The system **MUST** display a single-chip readout when the parameter is the auto-generated `__placeholder__` sentinel (preserving the existing placeholder warning UI).
- Notes: Optuna's `suggest_categorical` accepts mixed-type choices; the builder accepts them too. The dedup non-requirement is a hard invariant — the round-trip parity test at `round-trip.test.tsx` includes a `{"choices": ["AUTO", "AUTO", "BM25"]}` fixture to lock this in.

### FR-6: Per-row cardinality counter

- Requirement:
  - The system **MUST** render a small text node per row showing the param's cardinality contribution:
    - `float` (any) → "≈ 100 states" (constant; matches `estimate_cardinality` float weight at [`search_space.py:191`](../../../../backend/app/domain/study/search_space.py#L191)).
    - `int` → "{high − low + 1} states".
    - `categorical` → "{choices.length} states".
  - The system **MUST** consume a new sibling helper `estimateParamCardinality(spec: ParamSpec): number` from `search-space-defaults.ts` (extracted from the existing `estimateCardinality()` loop body — pure refactor, identical math).
  - The system **MUST** show a tooltip from the existing `study.search_space.cardinality` glossary key.

### FR-7: Header cardinality counter + cap enforcement

- Requirement:
  - The system **MUST** render a header element ("Search space: ~{N} combinations (cap: 1,000,000)") computed by `estimateCardinality()` over the current parsed `search_space_text`.
  - The system **MUST** turn the counter red, set `aria-invalid="true"`, and render a single inline hint identifying the param with the largest cardinality contribution ("Try narrowing `<name>` — currently {contribution} of {total}") whenever the total exceeds 1,000,000.
  - The system **MUST NOT** disable the "Next" button on the basis of cardinality — the existing client-side validation mirror (`handleStep4Next`) is unchanged; the server-side `_check_cardinality` at [`search_space.py:110-118`](../../../../backend/app/domain/study/search_space.py#L110-L118) is the authoritative gate. The visual cap signal is a UX warning, not a blocker.
- Notes: Disabling Next on cardinality alone would conflict with the existing `stepValid(3, ...)` predicate at [`create-study-modal.tsx:330-337`](../../../../ui/src/components/studies/create-study-modal.tsx#L330-L337), which only blocks on JSON parseability. Adding a second blocker creates two error UIs (the existing Pydantic-error inline alert + a new builder-cardinality gate) that disagree on threshold semantics.

### FR-8: Split-view (desktop) and tab-view (narrow viewport)

- Requirement:
  - The system **MUST** render the builder and textarea side-by-side at viewports ≥1024px using a Tailwind `lg:grid-cols-2` layout.
  - The system **MUST** render a "Builder | JSON" tab toggle at viewports <1024px with the Builder tab active by default. The user's tab selection **MUST NOT** persist across modal closes.
  - The system **MUST** keep the textarea (`data-testid="cs-search-space"`) in the DOM whenever the JSON tab is active, preserving every existing test selector.
  - The system **MUST** render the textarea in the DOM at all viewports (even when the Builder tab is active on narrow viewports). Use `hidden` (CSS `display: none`) on the inactive tab — NOT conditional rendering — so React Hook Form's `register` reference stays stable and existing component tests' `getByTestId('cs-search-space')` queries continue to resolve.

### FR-9: Bidirectional round-trip discipline

- Requirement:
  - The system **MUST** debounce builder → textarea writes (200 ms) and apply textarea → builder reads on every keystroke (no debounce), so a textarea edit immediately invalidates the builder's pending write (last-edit-wins; see §4 product principles).
  - The system **MUST** render the builder in a non-interactive "JSON has syntax errors — fix in the textarea" placeholder **only** when `JSON.parse(search_space_text)` throws. The textarea's existing `searchSpaceError` surfaces the parse error.
  - **Parseable-but-empty JSON does NOT trigger the placeholder.** When the textarea contains `{}`, `{"params": {}}`, or any other parseable object that lacks rows, the builder renders the declared-param rows in their "empty/unset" state per FR-1 (assuming `templateBody` is resolved). The placeholder is exclusively for JSON.parse failures.
  - The system **MUST NOT** silently auto-correct invalid JSON in the textarea — propagate the parse error verbatim to the existing inline alert.
- Notes: This is the load-bearing invariant. The round-trip parity test at `ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx` is the regression net.

### FR-10: Non-actionable "Add custom param" affordance

- Requirement:
  - The system **MUST** render an "Add custom param" `<button type="button">` at the foot of the builder rows. The button **MUST NOT** use the native HTML `disabled` attribute (which removes the element from tab order and prevents the tooltip from being focus-discoverable); instead it carries `aria-disabled="true"` and an `onClick` handler that does nothing but does not throw.
  - The system **MUST** keep the button in tab order (focusable). Focus triggers the same tooltip as hover.
  - The system **MUST** show a tooltip on hover or focus with the text "Tunable params come from the template's `declared_params`. To tune a new one, edit the template." and include a Next.js `<Link>` to `/templates/{template_id}` (target rendered as an `<a>` tag with `data-testid="cs-row-add-custom-link"`). The link IS interactive (the user can press Tab to move focus from the button to the link and Enter to follow it).
  - The system **MUST NOT** render the affordance when `templateBody` is null (e.g., `transient` / `404` fetch state) — the existing Retry block at [`create-study-modal.tsx:576-591`](../../../../ui/src/components/studies/create-study-modal.tsx#L576-L591) is the only surface during fetch failure (see AC-11). Once `templateBody` resolves, the affordance renders alongside the rows.

### FR-11: Per-row tooltips wired to existing glossary subkeys

- Requirement:
  - The system **MUST** render `<InfoTooltip glossaryKey="study.search_space.param_spec" />` next to the type selector label.
  - The system **MUST** render `<InfoTooltip glossaryKey="study.search_space.log" />` next to the log checkbox label.
  - The system **MUST** render `<InfoTooltip glossaryKey="study.search_space.cardinality" />` next to both the per-row and header cardinality counters.
- Notes: All three glossary keys already exist at [`glossary.ts:80-94`](../../../../ui/src/lib/glossary.ts#L80-L94) — no glossary edits required.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints.** This feature is a pure-frontend presentation layer over the existing `search_space` field of `POST /api/v1/studies`.

### 8.2 Contract rules

N/A — no contract changes. The existing `INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM` error codes at [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) continue to be the authoritative server-side rejection envelope.

### 8.3 Response examples

N/A — no new endpoints.

### 8.4 Enumerated value contracts

The builder uses **one** option list whose values must match a backend allowlist:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `ParamSpec.type` (type-selector `<Select>` in builder row) | `float`, `int`, `categorical` | [`backend/app/domain/study/search_space.py:83-89`](../../../../backend/app/domain/study/search_space.py#L83-L89) (`ParamSpec = Annotated[FloatParam \| IntParam \| CategoricalParam, Field(discriminator="type")]`; each `Literal["..."]` lives on the respective sub-class at lines 40, 59, 79) | `ui/src/components/studies/search-space-builder/row-type-selector.tsx` (new) |

**Rules:**
- The option array MUST carry the source-of-truth comment per §4 product principles.
- The values are NOT mirrored into [`enums.ts`](../../../../ui/src/lib/enums.ts) — they are baked into the Pydantic discriminated union and have no separate `frozenset` / `Literal` re-export. The parity test at `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx` (see FR-2) is the grep-the-backend-file gate.
- Adding a fourth `ParamSpec` variant (e.g., a `LogIntParam` in a future MVP2 spec) MUST update both the discriminator and this option list in the same PR; the parity test fails until both sides land.

The builder does NOT introduce any other filterable fields, sort keys, status badges, or wire-format dropdowns.

### 8.5 Error code catalog

No new error codes. The existing codes at [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) (`INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) continue to be the only ones the create-study endpoint emits for search-space failures.

## 9) Data model and state transitions

### New/changed entities

**None.** Zero schema changes, zero migrations, zero column additions, zero ORM model edits. The existing `studies.search_space` JSONB column at [`backend/app/db/models/study.py`](../../../../backend/app/db/models/study.py) is unchanged.

### Required invariants

- **Builder ↔ textarea bidirectional round-trip is semantically loss-less.** Per §4: `deepEqual(JSON.parse(stringify(parse(s))), JSON.parse(s))` for every well-formed `s`. Textual equality holds only after first canonical-pass normalization (e.g., `{"high": 10.0}` becomes `{"high": 10}` after first round-trip).
- **Builder predicates are a subset of Pydantic's.** Every row state the builder reports as valid SHOULD also pass `SearchSpace.model_validate`. Verification is split into two layers, neither of which is exhaustive on its own:
  - (a) **Frontend round-trip** — the `round-trip.test.tsx` parity test asserts the builder accepts (no row error surfaces) every fixture that is also valid `SearchSpace` JSON, where the fixture set was hand-validated against `SearchSpace.model_validate` by the spec author.
  - (b) **Real-backend smoke** — `studies-create-builder.spec.ts` is a single-path real-backend e2e (float-edit happy path); it confirms cross-layer agreement on the most common builder output but does NOT span every `ParamSpec` variant. It is a **smoke check on the dominant flow**, not a comprehensive subset proof.
  - The "subset" property is therefore a design claim asserted at spec-author time and re-validated on every PR via the spec author's manual review of the round-trip fixture set; a future spec extension (or this spec's plan) MAY add 3–4 additional real-backend e2e paths covering int-edit, categorical-edit, type-switch, and duplicate-choices submissions if observed regressions warrant the extra CI minutes.
- **Order preservation.** Builder row order matches `Object.keys(templateBody.declared_params)` iteration order — anchored to the template, NOT to the textarea's parsed JSON, so reordering the textarea's keys does not reorder the rows. Server-side `validate_against_template` at [`search_space.py:199-242`](../../../../backend/app/domain/study/search_space.py#L199-L242) uses `sorted()` for lexicographic comparison; the builder does NOT sort, so the visual order matches the template declaration while server-side errors continue to surface the lexicographically smallest offender.

### State transitions

The builder itself is stateless beyond its own input/output binding. The wider modal state machine (Step 0 → 1 → 2 → 3 → 4) is unchanged.

### Idempotency/replay behavior

N/A — no event-driven path. The builder is a synchronous controlled component.

## 10) Security, privacy, and compliance

- **Threats:**
  - **JSON injection / arbitrary key collisions** — the builder reads `JSON.parse(search_space_text)` and matches row content by exact key. Per FR-1, the builder's row identity comes from `templateBody.declared_params` only — so a textarea-injected `__proto__` row never renders as a builder row. The textarea path remains exposed to the server-side `extra="forbid"` Pydantic config at [`search_space.py:106`](../../../../backend/app/domain/study/search_space.py#L106) and to `validateSearchSpaceAgainstTemplate()`, both of which reject unknown keys.
  - **XSS via chip-input free text** — categorical choices are rendered into the DOM. Mitigation: React's default escaping handles all string content; the builder does NOT use `dangerouslySetInnerHTML`. No HTML interpretation.
  - **DoS via large `params` count** — the existing 10⁶ cardinality cap doesn't bound `len(params)` directly. A pathological 10,000-key dict would render 10,000 rows. Mitigation: not a real-world concern (templates declare ≤ ~20 params in practice); the existing Pydantic `min_length=1` lower bound is the only guard. If usage data ever justifies it, a row-count limit (e.g., `max_length=50`) can be added in a future spec.
- **Controls:** N/A beyond standard React rendering.
- **Secrets/key handling:** N/A — no secrets touched.
- **Auditability:** N/A — the audit event for `POST /api/v1/studies` is emitted by the existing endpoint (when audit_log lands at MVP2); the builder makes no additional backend calls.
- **Data retention/deletion/export impact:** N/A — no new data.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Builder lives **inside the existing create-study modal**, replacing the layout of Step 4 (zero-indexed `step === 3`). No new route, no new sidebar entry, no new top-level page.
- **Labeling taxonomy:**
  - Modal header (unchanged): "Step 4 of 5 — Search space"
  - Builder header: "Search space: ~{N} combinations (cap: 1,000,000)"
  - Per-row labels: parameter name as a chip + simple-form badge; "Type", "Low", "High", "Log scale", "Choices", "Cardinality" as field labels
  - "Add custom param" (disabled button) — matches the existing tone of disabled affordances elsewhere in the modal (e.g., the auto-disabled Next button via `stepValid`)
- **Content hierarchy:**
  1. Header counter (primary — always visible, scales red when cap is exceeded).
  2. Param rows (primary — one per declared param, in `Object.keys` order).
  3. Disabled "Add custom param" button (secondary — at the foot of the row list).
  4. Existing inline alerts (`cs-search-space-error`, `cs-placeholder-warning`, `cs-template-retry`) — keep their current visual hierarchy.
- **Progressive disclosure:** No "Advanced" disclosure in v1. The idea raised `step` as an Advanced candidate; the spec drops it entirely — `step` is omitted from the builder UI for v1 and remains accessible only via the textarea (Pydantic accepts `step` on `FloatParam`/`IntParam`? — actually NO; the current `FloatParam` / `IntParam` schemas at [`search_space.py:31-67`](../../../../backend/app/domain/study/search_space.py#L31-L67) do NOT carry a `step` field; the idea's mention was speculative). The builder simply renders no `step` control. If the backend schema grows `step` in a future spec, the builder gains it at the same time.
- **Relationship to existing pages:** Extends Step 4 of the create-study modal. The Step-3 template picker and Step-5 metric/k surface are untouched.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Type selector label | (glossary key `study.search_space.param_spec`) — "Each parameter is float (continuous), int (whole numbers), or categorical (pick from a fixed list)." | `<InfoTooltip>` hover/focus | inline-right of label |
| Log checkbox label | (glossary key `study.search_space.log`) — "Use log scale when the range spans more than 10× (e.g. 0.5–10). It samples small values as densely as large ones." | `<InfoTooltip>` hover/focus | inline-right of label |
| Per-row cardinality counter | (glossary key `study.search_space.cardinality`) — "Total combinations must stay under 1,000,000. Floats count as 100; ints as high - low + 1; categoricals as the number of choices." | `<InfoTooltip>` hover/focus | inline-right of counter |
| Header cardinality counter | same glossary key `study.search_space.cardinality` | `<InfoTooltip>` hover/focus | inline-right of header |
| Disabled "Add custom param" button | "Tunable params come from the template's `declared_params`. To tune a new one, edit the template." + inline link to `/templates/{template_id}` | button hover/focus | tooltip below button |
| Disabled log checkbox (low ≤ 0) | "Log scale requires low > 0." | native `title` attribute | browser tooltip on hover |
| Low/high input row error | "low must be < high" (float) / "low must be ≤ high" (int) | inline `role="alert"` | below the input pair |
| Empty choices row error | "choices: at least 1 choice required" | inline `role="alert"` | below the chip input |

### Primary flows

1. **Open create-study → reach Step 4** (existing flow): user picks cluster (Step 0), query-set + judgment-list (Step 1), template (Step 2), name (Step 3 name + Step 4 search-space). When Step 2 advances, the auto-fill effect at [`create-study-modal.tsx:205-259`](../../../../ui/src/components/studies/create-study-modal.tsx#L205-L259) writes the starter JSON to `search_space_text`. Builder renders one row per param on next render tick.
2. **Tune a float row** (new): user picks `float` (already default for most boost-like params), clicks the `high` spinner to bump from 10 to 20, toggles `log` on. Builder writes back debounced 200 ms. Header cardinality recomputes (still 100 for the single float). Cell error never fires (`low = 0.5, high = 20, log = true` passes both client + server predicates).
3. **Hit the cardinality cap** (new): the user's template has 4 declared params; the auto-fill cap-aware fallback at [`search-space-defaults.ts:148-171`](../../../../ui/src/lib/search-space-defaults.ts#L148-L171) has already converted two of them from floats to `int [0, 5]` to land under the 10⁶ cap (starting state: 2 floats × 100 each, 2 ints × 6 each = 10⁴ × 36 = 3.6 × 10⁵ — under cap, header green). Now the user widens one of the int rows to `int [0, 100]`: contribution becomes 101 instead of 6. Total = `100² × 6 × 101 = 6.06 × 10⁶`. Cap exceeded by 6×; header counter turns red; hint says "Try narrowing `<name>` — currently 101 of 6.06×10⁶". User narrows it back to `int [0, 5]` → counter recomputes to `3.6 × 10⁵`. Green. (Math identity: `estimateCardinality` multiplies the per-param contribution of EVERY param — when one param's type changes, only that param's contribution swaps; the others are unaffected.)
4. **Switch type** (new): user toggles a row from `float` to `categorical`. Builder stashes the current `FloatSpec` under `stashRef.current[paramName].float`, replaces the row's textarea content with `{type: 'categorical', choices: []}`, writes back. User adds three chips: `"AUTO"`, `"BM25"`, `"DFR"`. Counter goes to 3. User toggles back to `float` — builder reads `stashRef.current[paramName].float` and restores `{low: 0.5, high: 10.0, log: true}`. Per §4 invalidation rules: if the user instead edits the textarea directly to change the categorical row's spec before toggling back, the stash entry for `paramName.float` is invalidated and the float restore falls back to `simpleFormSpec(declared_params[paramName])` defaults.
5. **Edit textarea directly** (new): user clicks the JSON textarea (desktop split-view, or tab toggle on narrow viewport), edits the JSON. Builder reads on every keystroke, re-renders rows. If the user introduces a syntax error, the builder switches to the non-interactive placeholder and the existing `cs-search-space-error` surfaces the parse failure.

### Edge/error flows

- **Templates with zero `declared_params`** — the existing Step-2 gate `templateHasNoDeclaredParams` (see [`create-study-modal.tsx:516-526`](../../../../ui/src/components/studies/create-study-modal.tsx#L516-L526)) blocks the user from reaching Step 4. The builder never has to render in this state.
- **Template 404 mid-modal** — existing `templateFetchStatus === '404'` flow bumps to Step 3. Builder never renders.
- **Template fetch transient** — existing Retry button at [`create-study-modal.tsx:576-591`](../../../../ui/src/components/studies/create-study-modal.tsx#L576-L591) remains; the builder renders nothing (returns a placeholder) until `templateBody` resolves.
- **Textarea contains malformed JSON** — builder shows placeholder; existing inline alert surfaces the parse error; "Next" is already blocked by `stepValid(3, ...)` JSON-parse check.
- **User pastes a JSON object missing `params` wrapper** — parseable JSON, so the FR-9 placeholder does NOT fire. Instead the builder renders declared-param rows in "empty/unset" state (per FR-1) with an inline hint at the foot of the row list: "Wrap your JSON in a `params:` object — the rows above are empty because no `params` key was found." `validateSearchSpaceAgainstTemplate()` returns null (its first check at [`create-study-modal.tsx:274-276`](../../../../ui/src/components/studies/create-study-modal.tsx#L274-L276) bails on missing `params`), so the existing `cs-search-space-error` block stays empty — the unset rows + inline hint are the sole signal until the user adds the wrapper.
- **`__placeholder__` sentinel present** — builder renders the row as a categorical with a single `[placeholder]` chip; existing `placeholderWarning` continues to fire from the global state and surfaces the existing amber warning below the textarea.
- **Resize from desktop → narrow viewport mid-edit** — Tailwind's `lg:` responsive class flips the layout. The tab toggle initializes to the Builder tab; the user's last builder row state is preserved (it's all derived from `search_space_text`). No data loss.

## 12) Given/When/Then acceptance criteria

### AC-1: Builder renders one row per declared parameter (FR-1)

- **Given** the user reaches Step 4 with a template whose `declared_params = {"boost_title": "float", "min_should_match": "int", "operator": "string"}`
- **When** the auto-fill effect writes the starter JSON and the builder mounts
- **Then** the builder renders exactly 3 rows in `Object.keys(templateBody.declared_params)` order — `boost_title` (float), `min_should_match` (int), `operator` (categorical with `__placeholder__` chip)
- Example values:
  - Auto-fill JSON (after numeric normalization — `10.0` → `10`): `{"params": {"boost_title": {"type": "float", "low": 0.5, "high": 10, "log": true}, "min_should_match": {"type": "int", "low": 0, "high": 5}, "operator": {"type": "categorical", "choices": ["__placeholder__"]}}}` (with line breaks per `JSON.stringify(..., null, 2)`)
  - Expected DOM: 3 elements matching `[data-testid^="cs-param-row-"]` (NOT `cs-row-` — that prefix is shared with sub-control test IDs like `cs-row-boost_title-low`); each row container's `data-testid` follows the pattern `cs-param-row-{paramName}` (first row: `cs-param-row-boost_title`)

### AC-2: Type selector mirrors backend ParamSpec discriminator (FR-2)

- **Given** the parity test `param-spec-discriminator.parity.test.tsx` reads `backend/app/domain/study/search_space.py`
- **When** the test extracts the `Literal["..."]` values from each `ParamSpec` sub-class
- **Then** the test asserts the type-selector option array is `['float', 'int', 'categorical']` (exact, order-sensitive)
- Example values:
  - Backend at search_space.py: `type: Literal["float"]` on FloatParam (line 40), `Literal["int"]` on IntParam (line 59), `Literal["categorical"]` on CategoricalParam (line 79)
  - Frontend at row-type-selector.tsx: `const TYPE_VALUES = ['float', 'int', 'categorical'] as const` with the source-of-truth comment

### AC-3: Float row low/high spinner edits round-trip to JSON (FR-3, FR-9)

- **Given** the user is at Step 4 with a single auto-filled float row `boost_title: { low: 0.5, high: 10.0, log: true }`
- **When** the user clicks the `high` input's up-arrow 5 times (or types `15` directly)
- **Then** the textarea content updates within 200 ms to `"high": 15` (debounced builder → textarea write) and the row's per-row cardinality counter still reads "≈ 100 states" (floats are always 100)
- Example values:
  - Initial textarea: `{"params":{"boost_title":{"type":"float","low":0.5,"high":10.0,"log":true}}}` (formatted)
  - After 5 up-arrows: `{"params":{"boost_title":{"type":"float","low":0.5,"high":15,"log":true}}}` (formatted; note JSON serializes `15` without `.0`)

### AC-4: Log checkbox gates check-on transition when low ≤ 0 (FR-4)

- **Given** a float row with `low: 0, high: 10, log: false`
- **When** the builder renders the log checkbox
- **Then** the checkbox is NOT `disabled` (it is focusable + clickable), but carries `aria-disabled="true"` and `title="Log scale requires low > 0"`
- And **when** the user clicks the checkbox (attempts the `false → true` transition)
- **Then** the onChange handler returns early, `log` remains `false`, and the row error "Log scale requires low > 0" surfaces inline with `role="alert"`
- And **when** the user raises `low` to `0.1`, the checkbox's `aria-disabled` and `title` clear; subsequent click toggles `log: true`
- And **when** a row starts in state `{log: true, low: -1}` (e.g., textarea-injected), clicking the checkbox (attempting `true → false`) IS honored — only the check-on transition is gated; the same row also surfaces the row error until either `low > 0` or `log: false`
- Example values:
  - Initial DOM: `<input data-testid="cs-row-boost_title-log" type="checkbox" aria-disabled="true" title="Log scale requires low > 0" />` (note: NO `disabled` attribute)
  - After low=0.1: `aria-disabled` and `title` attributes removed

### AC-5: Categorical row chip input coerces types (FR-5)

- **Given** the user toggles a row to `categorical` and clicks the chip input
- **When** the user types `true`, presses Enter, types `1`, presses Enter, types `AUTO`, presses Enter
- **Then** the row's `choices` array is `[true, 1, "AUTO"]` (boolean, number, string in that order)
- And **when** the user clicks the `×` next to the `1` chip, the choices array becomes `[true, "AUTO"]`
- Example values:
  - After 3 entries: `{"type":"categorical","choices":[true,1,"AUTO"]}` in the textarea
  - After remove: `{"type":"categorical","choices":[true,"AUTO"]}`

### AC-6: Header cardinality counter turns red and identifies max contributor (FR-7)

- **Given** the user is editing a search space with 6 float params all at default bounds (each contributing 100 per `estimateCardinality` at [`search-space-defaults.ts:92`](../../../../ui/src/lib/search-space-defaults.ts#L92))
- **When** the user converts the 6th float to `int [0, 100_000]`
- **Then** the header counter shows `~1.0e15 combinations (cap: 1,000,000)` in red text with `aria-invalid="true"` and an inline hint "Try narrowing `<name of int row>` — currently 100,001 of ~1.0e15"  (math: `100^5 × 100,001 = 1.00001 × 10^15`)
- And the Next button **MUST remain enabled** (FR-7 explicitly does not block on cardinality client-side — the server's `_check_cardinality` is the authoritative gate)
- Example values (alternative for a smaller test fixture): with 4 float params + 1 `int [0, 999]` → counter shows `~1.0e11 combinations` red; max contributor "1,000 of 1.0e11" (math: `100⁴ × 1,000 = 10⁸ × 10³ = 10¹¹`)

### AC-7: Bidirectional round-trip parity (FR-9, §4 invariant)

- **Given** the parity test feeds 11 fixture shapes through `JSON.parse → builder state → JSON.stringify`
- **When** each fixture is round-tripped
- **Then** the resulting JSON is **semantically equivalent** to the input (`deepEqual(JSON.parse(after), JSON.parse(before))`); textual equality holds after the first canonical-pass normalization
- And **when** the 2 numeric-normalization fixtures (`{"high": 10.0}`; `{"low": 1e-3}`) are round-tripped
- **Then** the JSON normalizes to `{"high": 10}` and `{"low": 0.001}` on the first pass, and is textually idempotent on subsequent passes
- And **when** the duplicate-categorical fixture `{"choices": ["AUTO", "AUTO", "BM25"]}` is round-tripped
- **Then** the choices array remains `["AUTO", "AUTO", "BM25"]` (no de-duplication per FR-5)
- Example values: the 11 fixtures named in §4 product principles — (1) boost-only float, (2) mixed float+int, (3) fuzziness categorical, (4) log float, (5) log-with-low<=0, (6) multi-param hitting cap, (7) placeholder categorical (`__placeholder__` sentinel), (8) empty `params` object (rows in unset state, NOT placeholder mode), (9) duplicate categorical choices `["AUTO", "AUTO", "BM25"]`, (10) numeric normalization `{"high": 10.0}` → `{"high": 10}`, (11) exponent normalization `{"low": 1e-3}` → `{"low": 0.001}`

### AC-8: Non-actionable "Add custom param" links to template detail (FR-10)

- **Given** the user is at Step 4 with a known `template_id` and `templateBody` resolved
- **When** the user hovers OR keyboard-focuses the "Add custom param" button
- **Then** a tooltip appears with the message "Tunable params come from the template's `declared_params`. To tune a new one, edit the template." plus a focusable + clickable `<a data-testid="cs-row-add-custom-link" href="/templates/{template_id}">Edit template</a>`
- And the button is **focusable** (no native `disabled`), carries `aria-disabled="true"`, and its `onClick` is a no-op
- And **when** `templateBody` is null (transient or 404 fetch state)
- **Then** the affordance is NOT rendered — the existing Retry block at `cs-template-retry` is the only Step-4 surface

### AC-9: Split view at desktop, tab view at narrow (FR-8)

- **Given** the viewport is 1280×800 (desktop)
- **When** the user is at Step 4
- **Then** the builder appears in the LEFT column and the textarea in the RIGHT column under a `lg:grid-cols-2` Tailwind layout; both have content; both are interactive
- And **when** the viewport is resized to 600×800
- **Then** the layout collapses to a single column with a "Builder | JSON" tab toggle; the Builder tab is active; the textarea is hidden via CSS `display: none` but the underlying `<Textarea>` element with `data-testid="cs-search-space"` remains in the DOM

### AC-10: All existing Step 4 component tests continue to pass

- **Given** the 7 existing `create-study-modal.*.test.tsx` files and the e2e `studies-create-validation.spec.ts`
- **When** the builder lands
- **Then** every existing test passes without modification (the textarea remains in the DOM, the existing test IDs are preserved, the form state path is unchanged)
- This is a **regression net AC** — implementation MUST verify this before opening the PR.

### AC-11: Builder renders a single non-interactive placeholder during template fetch failure

- **Given** the template fetch is in `'transient'` state (`templateFetchStatus === 'transient'`, `templateBody` null)
- **When** the user lands on Step 4
- **Then** the builder renders a single non-interactive placeholder card with the text "Couldn't load the template. Server-side validation will still catch typos on submit." — no rows, no header counter, no "Add custom param" affordance
- And the existing Retry block at `cs-template-retry` (from [`create-study-modal.tsx:576-591`](../../../../ui/src/components/studies/create-study-modal.tsx#L576-L591)) is rendered as today
- And the textarea remains editable (existing behavior; the user can still type JSON directly and submit)
- And **when** the user clicks Retry and `templateBody` resolves to a valid object
- **Then** the full builder UI (rows + header counter + "Add custom param") swaps in on the next render

### AC-12: Builder is invisible to a11y users when textarea has malformed JSON (FR-9)

- **Given** the user types `{not valid json` into the textarea
- **When** the builder tries to parse `search_space_text`
- **Then** the builder renders a `<div role="status" aria-live="polite">` placeholder with the message "JSON has syntax errors — fix in the textarea to use the builder" and the existing `cs-search-space-error` block surfaces the parse exception
- And no row-level controls are interactive (no tabindex)

## 13) Non-functional requirements

- **Performance.** Builder render time MUST stay under 16 ms (single 60 Hz frame) for `≤ 20` rows on modern hardware. `JSON.parse` + `JSON.stringify` on a 5-param space is ≪ 1 ms; the bottleneck is React re-render. Achieve via stable row keys and `useMemo` on the parsed object.
- **Reliability.** Round-trip parity test MUST pass for all 11 fixture shapes; any breakage blocks merge.
- **Operability.** N/A — pure frontend, no logs/metrics.
- **Accessibility:**
  - Every form control has a `<Label htmlFor>` association.
  - Row errors use `role="alert" aria-live="polite"`.
  - Tab order: header counter (non-focusable text) → row 1 type → row 1 low → row 1 high → row 1 log → row 1 cardinality (non-focusable text) → row 2 … → "Add custom param" button (focusable per FR-10; pressing Enter / Space is a no-op via `aria-disabled` + no-op handler) → "Edit template" link inside its tooltip (focusable + Enter follows the link).
  - Color is not the only signal — the header counter's red state is accompanied by `aria-invalid="true"` and an inline hint text element.
- **Bundle size.** The builder MUST add ≤ 8 KB gzipped to the `/studies` route bundle (no new third-party deps; new components consume existing primitives only).

## 14) Test strategy requirements (spec-level)

| Layer | Path | Min tests | Coverage focus |
|---|---|---|---|
| Unit | `ui/src/__tests__/lib/search-space-defaults.estimateParamCardinality.test.ts` | 6 | Pure-function math for `estimateParamCardinality()` factored helper. Float = 100; int = high-low+1; categorical = choices.length. |
| Unit | `ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx` | 11 | 11 fixture **semantic** round-trip parity (see §4 product principles + AC-7) — `deepEqual(JSON.parse(stringify(parse(s))), JSON.parse(s))` for the 11 enumerated fixtures, plus textual idempotence assertions on the 2 numeric-normalization fixtures (`{"high": 10.0} → {"high": 10}` on first pass; idempotent after) and the duplicate-categorical fixture (`{"choices": ["AUTO", "AUTO", "BM25"]}` survives intact). |
| Unit | `ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx` | 1 | Reads `backend/app/domain/study/search_space.py`, extracts `Literal["..."]` discriminator values, asserts builder's `TYPE_VALUES` matches. |
| Component | `ui/src/__tests__/components/studies/create-study-modal.builder-rendering.test.tsx` | 4 | Builder renders rows in `Object.keys` order; type selector + simple-form badge present; cardinality header + per-row counters present; disabled "Add custom param" present. |
| Component | `ui/src/__tests__/components/studies/create-study-modal.builder-edits.test.tsx` | 6 | Float `low`/`high` spinner edits propagate to textarea; type switch preserves low/high in cross-type ref; chip input coerces types; log checkbox gated on `low > 0`; row error surfaces on `low >= high`; header cap turns red at 10⁶+1. |
| Component | `ui/src/__tests__/components/studies/create-study-modal.builder-textarea-roundtrip.test.tsx` | 4 | Textarea keystroke updates builder rows on next render; malformed JSON switches builder to placeholder; builder edit writes back debounced 200 ms; tab toggle on narrow viewport hides+shows surfaces without losing form state. |
| Component | `ui/src/__tests__/components/studies/create-study-modal.builder-a11y.test.tsx` | 4 | `<Label htmlFor>` associations; `role="alert"` on row errors; "Add custom param" button is focusable (no native `disabled`) and `aria-disabled="true"`; "Edit template" link inside its tooltip is keyboard-reachable. |
| E2E | `ui/tests/e2e/studies-create-builder.spec.ts` | 1 | **Real-backend** walk: seed template with `declared_params = { "boost": "float" }`, navigate `/studies`, open modal, reach Step 4, use the builder to change `high` to 15, observe textarea reflects the change, submit, assert the study is created with `search_space.params.boost.high === 15`. **No `page.route()` mocking** — uses the same `seedFullChain` helper as `studies-create-validation.spec.ts`. |
| Existing tests | (the 7 + 1 listed in §2 audit) | unchanged | MUST continue to pass without modification. |

**Coverage gate.** Repo-wide vitest coverage stays above 80% per CLAUDE.md. New builder code is purely UI — coverage on the new module MUST be ≥ 90% (every branch in the type-switch ref-stash logic, the chip coercion, the log gating, and the cap-counter color flip).

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` — add a one-paragraph entry under "Form dropdown primitive" or a new sibling section "Search-space builder" pointing at the new component module and noting that it consumes the existing `EntitySelect` family, the existing form-state contract (`search_space_text: string`), and the existing glossary subkeys. Cross-link the parity test.
- `docs/02_product/planned_features/feat_create_study_search_space_builder/` — finalization moves this directory under `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_create_study_search_space_builder/` when the PR merges.
- `docs/03_runbooks/` — N/A (no new operational surface).
- `docs/04_security/` — N/A (no new auth/data path).
- `docs/05_quality/testing.md` — add a one-line note under "Test layer convention" pointing at the new parity test as the source-of-truth pattern for non-`enums.ts` wire-value contracts (the type discriminator is in a Pydantic discriminated union, not a `Literal` import from `enums.ts`).
- `CLAUDE.md` — no change. The existing "Enumerated Value Contract Discipline" section already covers the source-of-truth comment pattern; this spec adds an example, not a new convention.
- `state.md` — update "Currently in flight" → "Recently shipped" when the PR merges; bump Alembic head note "no migrations changed" (already true).
- `architecture.md` — no change.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. MVP1 is single-tenant local-only; the builder is a UI replacement for an existing UI region. No flag, no canary, no gradual rollout.
- **Migration/backfill expectations:** none — zero schema changes.
- **Operational readiness gates:** none — no new operational surface.
- **Release gate:** all unit/component/e2e tests pass; ≥ 90% coverage on the new builder module; visual smoke walkthrough of Step 4 in dev (`make up && cd ui && pnpm dev`, open `/studies`, walk Steps 0-4 with the seeded sample template); `pnpm typecheck` + `pnpm lint` + `pnpm build` (catches SSR issues) all green; CI green on `pr.yml`.

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories | Test files |
|---|---|---|---|
| FR-1 | AC-1 | 1.2 | `create-study-modal.builder-rendering.test.tsx`, `studies-create-builder.spec.ts` |
| FR-2 | AC-2 | 1.2, 2.1 | `param-spec-discriminator.parity.test.tsx`, `create-study-modal.builder-edits.test.tsx` |
| FR-3 | AC-3 | 2.1 | `create-study-modal.builder-edits.test.tsx`, `studies-create-builder.spec.ts` |
| FR-4 | AC-4 | 2.1 | `create-study-modal.builder-edits.test.tsx` |
| FR-5 | AC-5 | 2.2 | `create-study-modal.builder-edits.test.tsx` |
| FR-6 | AC-6 (per-row part) | 2.3 | `search-space-defaults.estimateParamCardinality.test.ts`, `create-study-modal.builder-rendering.test.tsx` |
| FR-7 | AC-6 (header part) | 2.3 | `create-study-modal.builder-edits.test.tsx` |
| FR-8 | AC-9 | 3.1 | `create-study-modal.builder-textarea-roundtrip.test.tsx` |
| FR-9 | AC-7, AC-12 | 1.1, 3.1 | `round-trip.test.tsx`, `create-study-modal.builder-textarea-roundtrip.test.tsx` |
| FR-10 | AC-8 | 2.4 | `create-study-modal.builder-rendering.test.tsx` |
| FR-11 | AC-1 (tooltip slots) | 1.2, 2.3 | `create-study-modal.builder-rendering.test.tsx` |
| (regression net) | AC-10, AC-11 | 4.1 | all existing `create-study-modal.*.test.tsx` + `studies-create-validation.spec.ts` |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] All test layers (unit/component/e2e) are green per §14.
- [ ] Documentation updates from §15 are merged (`ui-architecture.md` + `testing.md` notes; finalization moves the folder under `implemented_features/`).
- [ ] Rollout gates from §16 satisfied (typecheck + lint + build + visual smoke walkthrough).
- [ ] Cross-model GPT-5.5 review passes; Gemini Code Assist comments adjudicated.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

*(All four open questions from the idea were locked to defaults during spec drafting — see Decision log below. No remaining open questions at plan-creation time.)*

### Decision log

- **2026-05-20** — **Split-view (≥1024px) vs tab-view (<1024px)** — locked default per idea §"Open questions" answer 1. Reason: desktop has the horizontal real estate; the canonical artifact (JSON) staying visible reinforces source-of-truth; narrow viewports can't fit both without truncation. Override only on UX-research evidence in a follow-up spec.
- **2026-05-20** — **Form state representation: keep `search_space_text: string`** — locked default per idea §"Open questions" answer 2. Reason: the existing auto-fill effect, validation mirror, Undo flow, and `autoFillSignatures` set all bind to `search_space_text`; migrating to a `search_space: ParamSpec` dict would cascade through ~5 useEffect call sites for zero functional gain.
- **2026-05-20** — **Per-param descriptions: defer** — locked default per idea §"Open questions" answer 3. Reason: the simple-form chip + heuristic-derived default convey intent. Adding descriptions touches backend schema, migration, query-templates UI, and this builder — too cross-cutting for inline scope. File a separate idea if usage feedback warrants.
- **2026-05-20** — **"Advanced" disclosure scope: drop entirely; no `step` field** — narrower than idea §"Open questions" answer 4. Reason: `step` is not a field on `FloatParam` / `IntParam` at [`search_space.py:31-67`](../../../../backend/app/domain/study/search_space.py#L31-L67), so exposing it would mislead users. Numeric inputs + spinners are the only `low`/`high` UI. `log` stays in the primary surface.
- **2026-05-20** — **Disabled "Add custom param" button stays disabled forever (no plans to enable)** — reason: the only way to declare a new tunable param is to edit the template's `declared_params`. Enabling this affordance would silently introduce a parallel path that bypasses the SEARCH_SPACE_UNKNOWN_PARAM gate; users would hit it server-side anyway.
- **2026-05-20** — **No new shadcn Switch primitive** — reason: native `<input type="checkbox">` is the established pattern at `data-table-column-visibility.tsx`. Adding a new primitive is out of scope.
- **2026-05-20** — **No `step` field, no dual-handle sliders, no drag-and-drop** — reason: log-scale sliders are a pixel-precision UX trap; the JSON textarea is the precision escape hatch.
- **2026-05-20** — **Test the parity, not the implementation** — the type-selector source-of-truth parity test (FR-2) reads `search_space.py` and extracts `Literal["..."]` values, not the variable name `TYPE_VALUES`. Reason: a future rename of the frontend constant should not break the test; only an actual divergence of values should.
