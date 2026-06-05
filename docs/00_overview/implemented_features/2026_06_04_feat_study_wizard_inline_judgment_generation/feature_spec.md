# Feature Specification — Study wizard: inline judgment generation

- **Feature slug:** `feat_study_wizard_inline_judgment_generation`
- **Bucket:** `02_mvp2`
- **Status:** Draft (spec)
- **Priority:** P1
- **Depends on:** None (reuses shipped `<GenerateJudgmentsDialog>`, `useJudgmentLists`, `useGenerateJudgments`).

## 1) Purpose

When an operator opens the Create-Study wizard and selects a query set that has **no judgment list** for the chosen cluster + target, Step 1 dead-ends: the judgment-list dropdown is empty, "Next" stays disabled, and the only escape is a link that navigates away to `/judgments`, abandoning the half-filled wizard. This feature lets the operator generate judgments **inline, without leaving the wizard** — by surfacing a "Generate judgments" button in the empty-state that opens the existing `<GenerateJudgmentsDialog>` pre-targeted at the already-selected cluster + query set + target. After dispatch, the wizard's judgment-list list refreshes so the new list appears (with its live status), and the operator continues without restarting.

## 2) Current state audit

### Existing implementations

- **Wizard:** [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx).
  - Query-set select: `cs-qs` (lines 955-968). Filtered by cluster via `useQuerySets({ cluster_id, limit: 200 })` (line 380). Changing the query set clears `judgment_list_id` (lines 963-966).
  - Judgment-list select: `cs-jl` (lines 970-990). Fed by `useJudgmentLists({ query_set_id, cluster_id, target, limit: 200 })` (lines 386-391). Current empty-state (lines 985-988) shows copy + a single CTA `{ label: 'Generate judgments', href: '/judgments' }` — a navigate-away link.
  - Step-1 advance gate: `stepValid()` returns `Boolean(values.query_set_id && values.judgment_list_id)` (line 672). The "Next" button is disabled when this is false. The judgment-list select renders only once a `target` is set (Step is target-gated per `feat_study_target_judgment_mismatch_guard`, comment at lines 981-984).
- **Reusable dialog:** [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx). Props (lines 63-68): `open`, `onOpenChange`, `clusterId`, `querySetId`. Has its **own** `target` field defaulting to `''` (form `defaultValues`, line 129). On a successful generation dispatch it toasts, `form.reset()`s, and closes via `onOpenChange(false)` (lines 194-198 LLM path, 224-228 UBI path). It does **not** expose the new judgment-list id to the caller and does **not** navigate.
- **Hooks:** [`ui/src/lib/api/judgments.ts`](../../../../ui/src/lib/api/judgments.ts) — `useJudgmentLists` (lines 47-61, queryKey `['judgment-lists', {filter}]`); `useGenerateJudgments` invalidates `['judgment-lists']` on success (line 154). [`ui/src/lib/api/ubi.ts`](../../../../ui/src/lib/api/ubi.ts) — `useGenerateJudgmentsFromUbi` (UBI converters).
- **Backend study creation:** [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) lines 311-358 — validates query_set existence (404 `QUERY_SET_NOT_FOUND`), judgment_list existence (404 `JUDGMENT_LIST_NOT_FOUND`), judgment_list↔query_set match (422 `VALIDATION_ERROR`), judgment_list↔cluster match (422 `JUDGMENT_CLUSTER_MISMATCH`), judgment_list↔target match (422 `JUDGMENT_TARGET_MISMATCH`). It does **NOT** gate on judgment-list `status` — a study can be created against a `generating` list. `judgment_list_id` is required: [`schemas.py:875`](../../../../backend/app/api/v1/schemas.py) `judgment_list_id: str = Field(min_length=1, max_length=36)`.
- **Status enum:** `JUDGMENT_LIST_STATUS_VALUES = ['generating', 'complete', 'failed']` ([`ui/src/lib/enums.ts:156`](../../../../ui/src/lib/enums.ts)); backend CHECK `status IN ('generating', 'complete', 'failed')` ([`backend/app/db/models/judgment_list.py:41`](../../../../backend/app/db/models/judgment_list.py)).

### Navigation and link impact

No route changes. The `/judgments` deep link is retained as a secondary escape; the new primary affordance is in-place (modal-over-modal dialog). No URL the wizard depends on changes.

### Existing test impact

- `ui/src/__tests__/components/studies/` — existing create-study-modal component tests must continue to pass; the empty-state copy/CTA change touches assertions that reference the old `href: '/judgments'` CTA (audit + update during impl).
- Any existing real-backend study-creation E2E (`ui/tests/e2e/`) must still pass; the wizard's happy path (query set WITH judgment list) is unchanged.

### Existing behaviors affected by scope change

- The judgment-list dropdown currently renders option labels as `j.name` only (line 977, `getLabel={(j) => j.name}`) — no status shown. FR-4 augments this to surface status; existing label assertions update accordingly.
- The empty-state CTA changes from a navigate-away link to an in-wizard button + retained secondary link.

## 3) Scope

### In scope

- An inline "Generate judgments for this query set" affordance in the wizard's empty judgment-list state that opens `<GenerateJudgmentsDialog>` **without leaving the wizard**, pre-targeted at the selected cluster + query set + target.
- A new optional `defaultTarget?: string` prop on `<GenerateJudgmentsDialog>` so the dialog's target field is pre-filled with the wizard's already-chosen target (ensuring the generated list matches the wizard's `useJudgmentLists` target filter).
- Refresh of the wizard's judgment-list query after the dialog dispatches generation, so the new list appears in the dropdown.
- Surfacing judgment-list `status` in the dropdown option label, plus light auto-refetch while a `generating` list is present, so a freshly-generated list visibly progresses to `complete`.

### Out of scope

- **Any backend change.** No new endpoint, no schema change, no change to the study-creation status contract.
- Hard-blocking study creation when the selected judgment list is `generating` (the backend permits it and the existing wizard does not gate on status — see Decision D-3).
- Auto-selecting the newly generated list into the wizard form (operator selects it explicitly; see D-4).
- Migration, audit events, new enum wire values, multi-list management, or any change to `/judgments`.

### API convention check

No new endpoints. The reused generation flows hit existing `POST /api/v1/judgments/generate` (LLM) and `POST /api/v1/judgments/generate-from-ubi` (UBI), and the reused list flow hits `GET /api/v1/judgment-lists` — all unchanged. No auth/error-shape work required (this is single-tenant, no-auth MVP).

### Phase boundaries

Single phase. No deferred phases (no `phase*_idea.md`).

## 4) Product principles and constraints

- **Reuse, don't rebuild.** The generation UI already exists and is battle-tested (`<GenerateJudgmentsDialog>`); the wizard mounts it rather than duplicating form logic.
- **Never dead-end the operator.** Every empty-state must offer a forward path that doesn't discard in-progress work.
- **Honest async state.** A freshly-dispatched judgment list is `generating`, not ready; the UI must show that rather than implying it's selectable-and-ready.

### Anti-patterns

- Do not duplicate the generate-judgments form inside the wizard.
- Do not silently auto-select a `generating` list and let the operator believe the study will score against complete judgments.
- Do not remove the `/judgments` escape entirely — keep it as a secondary path for power users who want the full judgments surface.

## 5) Assumptions and dependencies

- `<GenerateJudgmentsDialog>` remains the canonical generation UI and accepts `clusterId`/`querySetId` (verified, lines 63-68). Adding an optional `defaultTarget` prop is backward-compatible (all existing call sites omit it → behaves exactly as today with `target: ''`).
- `useGenerateJudgments` invalidates `['judgment-lists']` on success (verified, judgments.ts:154), so the wizard's `useJudgmentLists` refetches automatically on the LLM path. The wizard additionally triggers a refetch on dialog close to cover the UBI path and cancel-then-reopen cases.
- The wizard's `target` is set before the judgment-list select (and thus before the inline-generate affordance) renders — target-gated per `feat_study_target_judgment_mismatch_guard`.

## 6) Actors and roles

Relevance Engineer (primary wizard user). No role/authorization changes — single-tenant, no auth.

### Authorization

N/A — MVP1/MVP2 single-tenant, no auth surface.

### Audit events

N/A — this feature adds no new state-mutating server surface. The reused generation endpoints already emit their own events; no audit-log instrumentation is introduced here.

## 7) Functional requirements

### FR-1: Persistent inline generate affordance in the wizard

Once a query set + target are selected (so the judgment-list field renders), the wizard presents a **"Generate judgments for this query set"** affordance that opens `<GenerateJudgmentsDialog>` in-place (modal over the wizard). It is rendered in two complementary forms so no case dead-ends:

- **Empty-state (primary):** when the dropdown has no judgment lists for the (query set, cluster, target), the empty-state shows the button prominently — this is the reported blocker.
- **Persistent secondary action:** when the dropdown *does* have lists (including when the only list is `failed` or `generating`), a smaller "Generate judgments" action remains available beneath the dropdown so the operator can retry a failed generation or create an alternative without leaving the wizard.

The existing "open the full judgments page" path is retained as a secondary link to `/judgments`. The wizard does not unmount or lose form state while the dialog is open.

### FR-2: Pre-target (and lock) the dialog from the wizard

`<GenerateJudgmentsDialog>` gains an optional `defaultTarget?: string` prop. When the wizard opens the dialog it passes `clusterId` (selected cluster), `querySetId` (selected query set), and `defaultTarget` (the wizard's selected target). When `defaultTarget` is supplied:

1. The dialog seeds its `target` form field from `defaultTarget` via **explicit form state on open** — a `useEffect`/`form.setValue` (or `form.reset`) keyed on `open` + `defaultTarget`, NOT solely the form `defaultValues` (which React Hook Form applies only at initial mount; a persistently-mounted dialog whose `defaultTarget` later changes would otherwise keep the stale value). The seed re-applies each time the dialog opens and whenever `defaultTarget` changes.
2. The `target` field is rendered **read-only (locked)** so it cannot drift from the wizard's target — guaranteeing the generated judgment list matches the wizard's `useJudgmentLists` target filter and is therefore selectable in the wizard.

Omitting the prop preserves today's behavior exactly: `target` defaults to `''` and remains operator-editable (existing `/judgments`-page call sites are unaffected).

### FR-3: Refresh the judgment-list list after dispatch

After the dialog dispatches generation and closes (`onOpenChange(false)`), the wizard ensures its `useJudgmentLists` query is refetched so the new list appears in the dropdown. The LLM path already invalidates `['judgment-lists']`; the wizard invalidates on dialog close as well (idempotent refetch) to cover the UBI path and the cancel/escape case.

### FR-4: Surface judgment-list status in the wizard (informational)

The judgment-list dropdown option label includes the list's `status` when it is not `complete` (e.g. `"<name> · generating"`, `"<name> · failed"`), so a freshly-generated `generating` list is visibly in progress and a `failed` list is visibly flagged. The status is **informational only** — selection is not hard-gated on it (D-3, D-7). While at least one judgment list for the current filter is `generating`, the wizard's `useJudgmentLists` query polls (bounded `refetchInterval`) until none remain `generating`, so the option flips to `complete` without a manual refresh.

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new or changed endpoints. Reused (all existing, unchanged):

| Method | Path | Used by |
|---|---|---|
| GET | `/api/v1/judgment-lists` | `useJudgmentLists` (wizard dropdown + status/poll) |
| POST | `/api/v1/judgments/generate` | `<GenerateJudgmentsDialog>` LLM path |
| POST | `/api/v1/judgments/generate-from-ubi` | `<GenerateJudgmentsDialog>` UBI path |

### 7.2 Contract rules

No contract changes. The wizard continues to submit `judgment_list_id` (required) to `POST /api/v1/studies` unchanged.

### 7.3 Response examples

N/A — no new/changed response shapes. Reused shapes (`JudgmentListSummary`, `GenerateJudgmentsResponse`) are unchanged.

### 7.4 Enumerated value contracts

| Field | Wire values | Source of truth |
|---|---|---|
| judgment list `status` (rendered in the option label, FR-4) | `generating`, `complete`, `failed` | `ui/src/lib/enums.ts:156` `JUDGMENT_LIST_STATUS_VALUES`; backend CHECK `backend/app/db/models/judgment_list.py:41`. The frontend reads `status` for display only (it is not sent back to the backend), so no new wire value is introduced; the option-label code MUST import the values from `@/lib/enums` rather than inlining string literals. |

No new dropdown/filter values flow to the backend from this feature.

### 7.5 Error code catalog

No new error codes. Existing study-creation errors (`JUDGMENT_LIST_NOT_FOUND`, `JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`) are unchanged and remain the backstop; the inline flow makes them less likely by pre-targeting the dialog (FR-2).

## 9) Data model and state transitions

### New/changed entities

None. No tables, columns, or migrations.

### Required invariants

- The inline-generated list's `target` MUST equal the wizard's selected target — **enforced** by FR-2 rendering the dialog's target field read-only (locked) when opened from the wizard, so it cannot drift from the wizard's target. This guarantees the new list matches the `useJudgmentLists` filter and is selectable.

### State transitions

The judgment list follows its existing lifecycle (`generating → complete | failed`); this feature only observes it.

### Idempotency/replay behavior

N/A — no event-driven server surface added. The on-close refetch (FR-3) is idempotent.

## 10) Security, privacy, and compliance

No change. No secrets, no PII, no new data leaving the cluster beyond what the reused generation endpoints already send (governed by `docs/04_security/llm-data-flow.md`).

## 11) UX flows and edge cases

### Information architecture

The inline affordance lives **inside Step 1 of the Create-Study wizard**, in the judgment-list field's empty-state (`create-study-modal.tsx` lines 985-988 region). The `<GenerateJudgmentsDialog>` opens as a modal layered over the wizard modal (the dialog is already a Radix `Dialog`; nesting is supported). On close, focus returns to the wizard Step 1. No top-level navigation entry is added.

### Tooltips and contextual help

No new glossary keys required. The empty-state copy is self-explanatory ("This query set has no judgment list for target X — generate one to continue"). If a one-line helper is added near the inline button, it reuses existing prose; no `ui/src/lib/glossary.ts` key is introduced (the existing `judgment.converter` key already documents generation methods inside the dialog).

### Primary flows

1. Operator opens Create-Study wizard, selects cluster → query set → target. The chosen query set has no judgment list for that target → dropdown empty-state shows the inline "Generate judgments for this query set" button.
2. Operator clicks it → `<GenerateJudgmentsDialog>` opens with cluster + query set + target pre-filled.
3. Operator picks a method (LLM / UBI / hybrid) and submits → generation dispatches, dialog closes, toast confirms.
4. Wizard refetches → the new list appears in the dropdown labelled `"<name> · generating"`; while generating, the list polls until `complete`.
5. Operator selects the (now `complete`) list → "Next" enables → continues the wizard.

### Edge/error flows

- **Operator cancels the dialog** (escape / cancel): wizard refetches (idempotent), dropdown stays empty (nothing generated), inline button remains. No state lost.
- **Generation fails** (worker error): the list appears `"<name> · failed"`; the dropdown is now non-empty, so retry uses the **persistent secondary "Generate judgments" action** (FR-1) — re-opening the dialog without leaving the wizard. Selection of a `failed` list is **not** hard-blocked in this feature (the backend study-creation guards validate only existence + query_set/cluster/target match — `studies.py:311-358` — and do NOT gate on `status`, so there is no backend backstop for a `failed` list; the `· failed` label is the operator's signal). Hard-disabling `failed`/`generating` options is an explicit non-goal here (D-7).
- **Operator selects a still-`generating` list and proceeds:** permitted (backend does not gate on status); polling flips the label to `complete` in place. See D-3 — informational, not hard-blocked.
- **Target cannot drift:** because FR-2 locks the dialog's target field to the wizard's target when opened from the wizard, the generated list always matches the wizard filter and appears. (Operators who want a *different* target still have the `/judgments` page, where the target field is fully editable.)

## 12) Given/When/Then acceptance criteria

### AC-1: Inline generate button is available (empty AND non-empty)
**Given** the wizard Step 1 with a cluster, a query set, and a target selected,
**When** the judgment-list field renders — whether the dropdown is empty OR already lists `failed`/`generating`/`complete` lists,
**Then** a "Generate judgments for this query set" affordance is present (prominent in the empty-state, a persistent secondary action otherwise), and clicking it opens `<GenerateJudgmentsDialog>` without navigating away or unmounting the wizard. A secondary `/judgments` link is also retained.

### AC-2: Dialog is pre-targeted and target-locked from the wizard
**Given** the wizard has cluster C, query set Q, and target T selected,
**When** the inline generate dialog opens,
**Then** the dialog receives `clusterId=C`, `querySetId=Q`, its target field shows `T` (seeded via explicit form state on open, not only `defaultValues`), and the target field is **read-only**; **and** if the wizard's target later changes to T2 and the dialog is reopened, the field reflects `T2` (not a stale `T`).

### AC-3: New list appears after dispatch
**Given** the inline dialog is open and the operator submits an LLM generation for (Q, C, T),
**When** the dialog dispatches and closes,
**Then** the wizard's judgment-list dropdown refetches and includes the newly created list for (Q, C, T).

### AC-4: Status is visible in the option label
**Given** a judgment list for the current filter whose `status` is `generating` (or `failed`),
**When** the dropdown renders its options,
**Then** that option's label includes the status (e.g. `"<name> · generating"`); a `complete` list shows just its name.

### AC-5: Generating list auto-progresses
**Given** the dropdown shows a list labelled `"<name> · generating"`,
**When** the underlying generation completes,
**Then** the wizard refetches on its bounded poll interval and the label updates to the plain name (`complete`) without a manual page refresh.

### AC-6: Backward-compatible dialog prop
**Given** any existing call site of `<GenerateJudgmentsDialog>` that does not pass `defaultTarget`,
**When** that dialog opens,
**Then** its target field defaults to `''` and remains operator-editable exactly as before (no behavior change).

### AC-7: Refetch on close covers the UBI path
**Given** the inline dialog is open and the operator dispatches generation via a **UBI** method (`useGenerateJudgmentsFromUbi`, which does NOT invalidate `['judgment-lists']`),
**When** the dialog closes (`onOpenChange(false)`),
**Then** the wizard invalidates/refetches its judgment-list query independently of the LLM hook's invalidation, so the new list still appears.

## 13) Non-functional requirements

- The status poll uses a bounded `refetchInterval` active **only** while a `generating` list is present in the current filter result (no unconditional polling), to avoid steady-state network churn on a wizard left open.
- No measurable change to wizard open/interaction latency; the dialog is lazy to the empty-state path.

## 14) Test strategy requirements (spec-level)

- **Component (vitest):**
  - AC-1: empty-state renders the inline generate button; clicking sets dialog `open`.
  - AC-2: dialog receives `clusterId`/`querySetId`/`defaultTarget` from the wizard's selected values; the target field is read-only and reflects `defaultTarget`; reopening after a target change shows the new target (seed-on-open, not stale `defaultValues`).
  - AC-4: option label includes status for `generating`/`failed`, plain name for `complete`.
  - AC-6: `<GenerateJudgmentsDialog>` with no `defaultTarget` still defaults target to `''` and stays editable.
  - AC-7: closing the dialog (`onOpenChange(false)`) invalidates/refetches the wizard's `['judgment-lists']` query — asserted independently of the LLM hook's invalidation (covers the UBI dispatch path).
  - AC-5: with fake timers + a mocked `useJudgmentLists` result that returns a `generating` list then a `complete` list on the next refetch, assert the option label transitions from `"<name> · generating"` to `"<name>"` (plain) via the bounded `refetchInterval`, with no manual refresh.
  - AC-1 (persistent affordance): the "Generate judgments" action is present both when the dropdown is empty AND when it lists only a `failed` list (retry path).
- **E2E (Playwright, real backend — no `page.route()` mocking):**
  - AC-1→AC-3→AC-5 end-to-end: open the wizard, select a cluster + a query set that has no judgment list for a fresh target, click the inline generate button, fill + submit the dialog, assert the new list appears in the dropdown, select it, and confirm "Next" enables. Setup (cluster/query-set seeding) via API helpers; all assertions via the `page` object (browser-visible behavior). Gate LLM-dependent generation behind the same env/availability guards existing judgment E2E uses, or use a UBI/import path that doesn't require a live LLM where feasible.
- Existing create-study-modal component tests updated for the new empty-state copy/CTA.

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` — note the wizard's inline-generate affordance and the `<GenerateJudgmentsDialog>` `defaultTarget` prop under the study-wizard / form-dialog section.
- Guide impact: the "create and monitor study" walkthrough (`ui/public/guides/06_create_and_monitor_study/`) may warrant a screenshot refresh if the empty-state is shown; assessed during impl (guide-gen gate).

## 16) Rollout and migration readiness

- No migration. No feature flag (pure UI enhancement, backward-compatible). Ships behind the normal PR + CI gates.
- Rollback is a straight revert of the frontend change; no data or schema state to unwind.

## 17) Traceability matrix

| FR | AC(s) | Code touch points |
|---|---|---|
| FR-1 inline affordance | AC-1 | `create-study-modal.tsx` empty-state (985-988) + dialog mount |
| FR-2 pre-target + lock dialog | AC-2, AC-6 | `generate-judgments-dialog.tsx` props (63-68) + defaultValues (129) + new `defaultTarget` (lock + seed-on-open via `form.setValue`/`useEffect`); wizard passes props |
| FR-3 refresh after dispatch | AC-3, AC-7 | wizard dialog `onOpenChange` → `queryClient.invalidateQueries(['judgment-lists'])`; existing `useGenerateJudgments` invalidation (judgments.ts:154); UBI path relies on the on-close invalidation (ubi.ts hook does not invalidate) |
| FR-4 status visibility + poll | AC-4, AC-5 | `create-study-modal.tsx` `getLabel` (977) reads `status` from `@/lib/enums`; `useJudgmentLists` conditional `refetchInterval` |

## 18) Definition of feature done

- All ACs implemented and covered by tests at the layers they touch (component + E2E).
- `<GenerateJudgmentsDialog>` `defaultTarget` is backward-compatible (existing call sites unchanged).
- No backend change; no migration; `make`/`pnpm` gates green (tsc, eslint, vitest, build); CI green.
- ui-architecture.md updated; guide impact assessed.

## 19) Open questions and decision log

### Open questions

- **OQ-1 (resolved by D-3):** Should the wizard hard-block selecting/proceeding with a `generating` judgment list? Resolved: no — surface status, do not block. Revisit only if operators report creating studies against incomplete judgments in practice.

### Decision log

- **D-1:** Reuse `<GenerateJudgmentsDialog>` rather than build a wizard-local generation form. Rationale: it is the canonical, tested generation UI; duplicating it would drift.
- **D-2:** Add `defaultTarget` as an **optional** prop (not required) so all existing call sites stay byte-compatible (AC-6).
- **D-3:** Do **not** hard-block study creation on judgment-list `status == complete`. Rationale: the backend permits it (studies.py validates only existence + query_set/cluster/target match, lines 311-358), and the existing wizard already does not gate on status — adding a gate is a separate behavior change beyond this feature's "don't dead-end" intent. Instead, surface status (FR-4) so the operator can choose to wait. Captured as OQ-1 for future revisit.
- **D-4:** Do **not** auto-select the newly generated list into the wizard form. Rationale: the list starts `generating`; auto-selecting + enabling "Next" would imply readiness. The operator selects it explicitly once it shows `complete`.
- **D-5:** Keep the `/judgments` link as a secondary escape rather than removing it. Rationale: power users may want the full judgments surface (calibration, overrides); removing it would regress that path.
- **D-6:** Status poll is conditional (only while a `generating` list is present), not unconditional. Rationale: avoids steady-state network churn on a wizard left open with only `complete` lists.
- **D-7:** Status (`generating`/`failed`) is **informational only** in the wizard dropdown — options are not hard-disabled. Rationale: backend study-creation does not gate on `status` (studies.py:311-358), and the existing wizard already permits selecting any list; adding selection-gating is a separate behavior change. The `· generating`/`· failed` labels give the operator the signal to wait/retry. The earlier draft's claim of a "backend backstop" for `failed` lists was inaccurate and was removed.
- **D-8:** When opened from the wizard (`defaultTarget` supplied), the dialog's target field is **locked read-only and seeded via explicit form state on open** (not RHF `defaultValues`, which only apply at mount). Rationale: makes the §9 target-match invariant actually hold for a persistently-mounted dialog and removes the footgun of an operator changing the target so the generated list silently won't appear. Omitting the prop leaves the field editable (backward-compatible, AC-6).
