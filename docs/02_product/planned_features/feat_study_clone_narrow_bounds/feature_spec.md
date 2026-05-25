# Feature Specification — Clone study: "narrow bounds" smart-rewrite action

**Date:** 2026-05-25
**Status:** Draft (pending GPT-5.5 cycle 1)
**Owners:** soundminds.ai (engineering)
**Related docs:**
- [idea.md](idea.md) — preflighted 2026-05-25
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — wizard / modal patterns
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope
- [`docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md`](../../../00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md) — v1 clone spec this extends

**Depends on (shipped):**
- [`feat_study_clone_from_previous`](../../../00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/) — `?clone_from` deep-link + `buildPrefillFromStudy` helper + `cloneSource` UI metadata + the wizard banner (PR #243, 2026-05-25)
- [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/) — `GET /api/v1/studies/{id}/digest` with `recommended_config: dict[str, Any]` (PR #41, 2026-05-11)
- [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/) — Step-4 autofill pipeline this rewrite must compose with (PR #175, 2026-05-21)
- [`chore_create_study_wizard_polish`](../../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/) — Step-4 declared-params validation that the rewritten space must continue to pass (PR #157, 2026-05-20)

---

## 1) Purpose

- **Problem:** After cloning a study via the v1 surface, the engineer's most common follow-up action is to narrow the `search_space` bounds around the winning trial's values ("exploit, don't explore" mode per the 2026-05-19 UX review). Today that means a manual JSON edit — opening the recommended config, reading each winning value, and rewriting `low`/`high` per param. Several minutes of error-prone bookkeeping per iteration.
- **Outcome:** A new opt-in checkbox on Step 4 of the cloned `CreateStudyModal` rewrites the prefilled `search_space_text` JSON so each numeric `low/high` clamps to ±20% around the source study's winning param value (read from `GET /api/v1/studies/{id}/digest` → `recommended_config`). Categorical params and missing-from-winner params are skipped. An optional read-only reference panel surfaces the winning values so the engineer can eyeball the rewrite before opting in. Pure frontend; no backend, no migration, no new endpoints.
- **Non-goal:** Smart-variance derived clamp ratios (e.g., narrower for low-variance params, wider for high-variance) — v1 uses a fixed ±20%. Categorical-choice narrowing (subsetting `choices` based on best-trial value) — out of scope; categoricals are skipped. Cloning from a `running` / `cancelled` / `failed` source whose digest doesn't exist — the checkbox is hidden; verbatim-clone still works. No backend changes; no new endpoints; no audit-event emission (pre-MVP2 per [CLAUDE.md](../../../../CLAUDE.md) "Activates at MVP2").

---

## 2) Current state audit

### Existing implementations to extend

- **`ui/src/components/studies/create-study-modal.tsx`** — `CreateStudyModal` at [line 214](../../../../ui/src/components/studies/create-study-modal.tsx#L214). Step 4 renders at `step === 3` (zero-indexed; [line 921](../../../../ui/src/components/studies/create-study-modal.tsx#L921)) with `<SearchSpaceBuilder>` + `<Textarea>` both synced through the `search_space_text` form field. The new checkbox + reference panel slot into this block, above the search-space body.
- **`ui/src/components/studies/create-study-modal.tsx:165-211`** — `PrefillValues` interface. v1 already declares `cloneSource?: { id: string; name: string }` (the gate this feature reads). No interface change required — the narrow-bounds toggle is local component state, not part of the prefill contract.
- **`ui/src/components/studies/prefill-from-study.ts`** — `buildPrefillFromStudy(source: StudyDetail)` at [line 38](../../../../ui/src/components/studies/prefill-from-study.ts#L38) copies `source.search_space` verbatim into `search_space_text`. The narrow-bounds rewrite consumes that verbatim JSON as its baseline and mutates it on opt-in. The helper itself is unchanged.
- **`ui/src/lib/api/digests.ts:10`** — `useStudyDigest(studyId)` already exists, queries `GET /api/v1/studies/{id}/digest`, returns `DigestResponse` with `recommended_config: dict[str, Any]` (per [`backend/app/api/v1/schemas.py:991-1008`](../../../../backend/app/api/v1/schemas.py#L991-L1008)). Pre-existing `meta: { suppressErrorCodes: ['DIGEST_NOT_READY'] }` + `retry: false` keep the global toast quiet when the digest hasn't been written yet. **Hook signature change required (Story 1.2):** the current signature `useStudyDigest(studyId: string)` always fires the request. This spec extends it to `useStudyDigest(studyId: string | undefined, opts?: { enabled?: boolean })`, mirroring the `useStudy(id, { enabled })` pattern at [`ui/src/lib/api/studies.ts:67-88`](../../../../ui/src/lib/api/studies.ts#L67-L88). The TanStack Query `useQuery` call gates on `enabled: opts?.enabled ?? Boolean(studyId)` so the modal can call the hook unconditionally (Rules of Hooks) while suppressing the request in the non-clone path. This is a backward-compatible additive change — existing single-argument callers are unaffected.
- **`backend/app/domain/study/search_space.py`** — pure-domain `SearchSpace` model with discriminated union `FloatParam | IntParam | CategoricalParam` (lines 31–86). The rewrite must produce JSON that passes `SearchSpace.model_validate` server-side; the per-type rules (FloatParam: `low < high`, `log → low > 0`; IntParam: `low <= high`; cardinality cap 10⁶) constrain the rewrite logic.
- **`ui/src/components/studies/search-space-builder.tsx`** (auto-updates from `search_space_text`) — no direct change needed; the builder rebuilds from JSON whenever the textarea content changes.

### Existing tests to extend

| Test file | Purpose | Change needed |
|---|---|---|
| `ui/src/components/studies/__tests__/create-study-modal.test.tsx` | Vitest for the modal | Add: checkbox visibility gating (cloneSource present AND digest ready), narrowed `search_space_text` on check, restore-on-uncheck, no checkbox in bare "New study" flow |
| `ui/src/__tests__/lib/narrow-bounds.test.ts` (NEW) | Pure-helper unit tests for `narrowBoundsAroundWinner` | Float clamp, int clamp+round, log-uniform `low > 0` preservation, categorical skip, missing-param skip, winner-outside-current-bounds edge case |
| `ui/tests/e2e/study-clone-narrow-bounds.spec.ts` (NEW) | Real-backend Playwright | Seed a `completed` study with a digest; click "Clone study"; check the narrow-bounds checkbox on Step 4; submit; assert the resulting study's `search_space` matches the clamp shape |

### Downstream consumers (must not regress)

- **`backend/app/api/v1/studies.py:_create_study`** — server-side `SearchSpace.model_validate` runs on every POST regardless of how the operator constructed the space. The rewrite must produce JSON that passes this validation (else 400 `INVALID_SEARCH_SPACE`). The rewrite logic respects every constraint in `search_space.py` (see §4 Anti-patterns).
- **`backend/app/domain/study/search_space.py:estimate_cardinality`** — cardinality cap 10⁶ ([line 113](../../../../backend/app/domain/study/search_space.py#L113)). Narrowing is cardinality-**non-increasing**: it can reduce the integer term (`high - low + 1`), leaves the float term unchanged (estimator uses a constant 100 regardless of width), and leaves categoricals unchanged. Across all branches the cardinality estimate never grows. Safe.
- **`backend/app/domain/study/search_space.py:validate_against_template`** — declared-params keys must match exactly. The rewrite never adds or removes params from `params: dict[...]`; it only mutates the `low/high` of existing entries. Safe.
- **`ui/src/components/studies/create-study-modal.tsx:447-463`** — `feat_agent_propose_search_space` autofill. When the engineer is in clone mode AND the prefilled `search_space_text` is non-empty (per [line 442-445](../../../../ui/src/components/studies/create-study-modal.tsx#L442-L445)), autofill is suppressed. The narrow-bounds rewrite operates on the prefilled JSON; autofill stays out of the way. Verified safe.

### Navigation and link impact

None. No new route, no nav-menu change, no query-param addition. The checkbox is a Step-4 affordance inside the existing `CreateStudyModal`.

### Information architecture

- **Checkbox placement:** Step 4 of `CreateStudyModal`, **above** the existing `ResponsiveLayout` (SearchSpaceBuilder + Textarea split). One line: `[ ] Narrow bounds around the source study's winning params (±20%)` + `<InfoTooltip glossaryKey="study.narrow_bounds_checkbox" />`. Visible **only** when `initialValues?.cloneSource` is set AND `useStudyDigest(initialValues.cloneSource.id)` has resolved successfully (status === 'success' AND `data.recommended_config` is a non-empty object). Hidden entirely otherwise — not disabled, not greyed out. (D-1: hide-vs-disable.)
- **Reference panel placement:** Directly below the checkbox, collapsible via a native `<details>` element (`<summary>Best-trial values from {source.name}</summary>` + a small two-column table showing param → winning value). Default collapsed (per idea Recommended: bundle but don't expand on first render). Visible whenever the checkbox is visible (same digest-ready gate).
- **Labeling taxonomy:**
  - Checkbox label: `"Narrow bounds around the source study's winning params (±20%)"`
  - Reference-panel summary: `"Best-trial values from {source.name}"` (truncated to fit; uses `cloneSource.name` for stability across edits to the form's `name` field, mirroring the v1 banner discipline at FR-12 of the clone spec)
  - Glossary entry: `study.narrow_bounds_checkbox` — "Rewrites the cloned search space so each numeric range tightens to ±20% around the source study's winning param values. Categorical params and params not present in the winner are left untouched. Uncheck to restore the source's bounds."

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Source |
|---|---|---|---|---|
| Checkbox label | (uses existing glossary entry — see below) | `InfoTooltip` icon click | inline-right of label | new glossary key |
| Reference panel summary | (no tooltip — the summary text is self-describing) | — | — | — |

**Glossary entries (single addition):**

| Key | Definition |
|---|---|
| `study.narrow_bounds_checkbox` | `"Rewrites the cloned search space so each numeric range tightens to ±20% around the source study's winning param values. Categorical params and params not present in the winner are left untouched. Uncheck to restore the source's bounds — any manual edits made to the rewritten JSON will be discarded."` |

Added to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) in Story 1.5 (see §17 traceability).

### Enumerated value contracts

None. This feature has no `<select>`, no filter, no status badge, no sort key. The checkbox is a boolean; the reference panel is read-only display. No values flow to the backend that aren't already covered by the v1 clone spec's `parent_study_id` field and the existing `search_space` JSON validation.

---

## 3) Scope

### In scope (single phase — no phase split)

- **`narrowBoundsAroundWinner(spaceJson, winnerParams, percent?): NarrowBoundsResult`** — pure helper in `ui/src/lib/narrow-bounds.ts`. Returns the structured `NarrowBoundsResult` defined in FR-9 (`{ json, narrowed, skipped }`). Callers consume `result.json` for the rewritten JSON; `result.narrowed` and `result.skipped` are for tests, toast messages, and the no-op detection in FR-4. Categorical params, missing-from-winner params, non-numeric winner values, and degenerate-intersection / log-uniform-zero-floor cases are passed through untouched and surfaced in `skipped`.
- **Step-4 checkbox** in `CreateStudyModal`, gated on `cloneSource` presence + `useStudyDigest` success.
- **Collapsible reference panel** rendering the source's `recommended_config` as a flat name→value table.
- **State management:** local component state tracking (a) the original cloned `search_space_text` (so unchecking restores it) and (b) the checkbox's checked state. No new `PrefillValues` fields.
- **Tests:** unit tests for `narrowBoundsAroundWinner`, vitest component tests for visibility + check/uncheck behavior, one Playwright real-backend E2E that clones → narrows → submits → asserts the persisted `search_space` matches the clamp shape.
- **Glossary:** one new entry (`study.narrow_bounds_checkbox`).
- **Docs:** brief paragraph in [`ui-architecture.md`](../../../01_architecture/ui-architecture.md) documenting the smart-rewrite pattern as the canonical example of "Step-4 derived-value toggle"; a one-line note in the v1 clone spec linking forward to this feature now that it's implemented.

### Out of scope (deferred / cross-feature)

- **Smart-variance clamp ratios** — fixed ±20% in v1 per OQ-N3 lock. Variance-derived widths are a v2 elaboration.
- **Categorical-choice narrowing** — categoricals are skipped per OQ-N2 lock. Subsetting `choices` based on a winning value is a separate UX question.
- **Trials-list fallback read path** — per OQ-N4 lock, the checkbox is hidden when the source has no digest. The trials-list fallback (read `params` of the row matching `best_trial_id`) is intentionally not implemented in v1; the simpler digest-only gate keeps the UX honest about what "narrow around the winner" means.
- **Customizable percent** — fixed 20%; no UI to adjust.
- **Persisting the narrow-bounds toggle across sessions** — checkbox state is per-modal-open and resets when the modal closes.
- **Audit event `study.cloned_with_narrowed_bounds`** — pre-MVP2, no audit_log table.
- **Reference panel for the non-clone "New study" flow** — invisible there because there is no source study to reference.

### API convention check

- **No new endpoints.** This spec reads from one existing endpoint (`GET /api/v1/studies/{id}/digest`, owned by `feat_digest_proposal`) and writes to one existing endpoint (`POST /api/v1/studies`, owned by `feat_study_lifecycle` + `feat_study_clone_from_previous`). Both endpoints are unmodified.
- **Error envelope:** N/A — no new error codes. The existing `INVALID_SEARCH_SPACE` (400) error fires from the server's `SearchSpace.model_validate` if the rewrite ever produces malformed JSON (it shouldn't; see Anti-patterns).
- **Auth surface:** N/A in MVP1 — no auth.

### Phase boundaries

Single-phase delivery. No deferred phase; no `phase2_idea.md` needed.

---

## 4) Product principles and constraints

- **Pure frontend transformation.** The rewrite produces JSON that `SearchSpace.model_validate` accepts; the server is the canonical validator and the rewrite must never construct an invalid space. Every constraint in `backend/app/domain/study/search_space.py` is mirrored by the helper (see Anti-patterns).
- **Opt-in, never automatic.** Default unchecked. The engineer affirmatively chooses to narrow. Cloning still works verbatim by default.
- **Restorable.** Unchecking the box restores the original (verbatim source) `search_space_text`. The user's choice is reversible inside the same modal-open lifecycle.
- **Hide-don't-disable.** When the digest isn't ready, the checkbox is absent — not greyed out. (D-1: a disabled checkbox is a UI affordance signaling "you could do this but can't right now," which falsely implies the operator's main flow is degraded; hiding makes it clear that this is an optional smart-rewrite that requires a completed source study.)
- **Banner-style stability.** The reference panel reads `cloneSource.name` (UI-only metadata seeded by `buildPrefillFromStudy`), not the form's `name` field, so user edits to the prefilled name don't corrupt the panel header. Mirrors the v1 clone spec's FR-12 banner discipline.
- **No regression to autofill.** Step-4 autofill ([line 442-445](../../../../ui/src/components/studies/create-study-modal.tsx#L442-L445)) is suppressed when the clone's prefilled `search_space_text` is non-empty. This feature operates on the same already-suppressed path; autofill never fires during a clone-with-narrow-bounds flow. No interaction risk.

### Anti-patterns

- **Do not** widen `low/high` under any circumstance. The rewrite is monotonically narrowing — every clamp must satisfy `new_low >= old_low` AND `new_high <= old_high`. If the winner is outside the current bounds (operator manually-narrowed the source before the winning trial was scored, or resumed a study with prior history), the rewrite **MUST** clamp the new bounds to the intersection of `[old_low, old_high]` and `[winner ± percent]`. Never produce a range disjoint from the source's.
- **Do not** silently invert `low` and `high`. If, after clamping, `new_low > new_high` (degenerate case — possible if winner is outside current bounds AND ±percent doesn't bridge to either side), **leave the param's bounds untouched** rather than producing an invalid pair. Surface a warning in the helper's return metadata (see §7.4 helper contract).
- **Do not** breach `log=true` requires `low > 0`. For log-uniform float params, if the winner-clamped `new_low <= 0`, fall back to `max(new_low, EPSILON)` where `EPSILON = 1e-12` matches the practical lower bound, OR if the original `low` was already very small, just leave the param untouched and surface a warning.
- **Do not** mutate `params[name].type`, `params[name].log`, or `params[name].choices`. The rewrite only mutates `low/high` on `float` / `int` params. Categorical params are passed through identically.
- **Do not** read the winning values from `parameter_importance`. `parameter_importance` is a `dict[str, float]` of feature-importance scores, not parameter values. The rewrite reads from `recommended_config` only.
- **Do not** invoke the rewrite when the textarea is in a known-malformed state (`searchSpaceError !== null`). The engineer fixes the JSON first, then opts in. Surface this gracefully: when JSON.parse throws, the checkbox triggers a toast ("Resolve the search-space JSON error before narrowing bounds") and reverts to unchecked.
- **Do not** introduce a new endpoint. The digest endpoint already exists; the trials-list endpoint already exists. This feature is read-only against existing surfaces.

---

## 5) Assumptions and dependencies

- **Hard dependencies (shipped, must not regress):**
  - `feat_study_clone_from_previous` — `cloneSource` UI metadata on `PrefillValues`; `?clone_from` deep-link; `buildPrefillFromStudy` helper.
  - `feat_digest_proposal` — `GET /studies/{id}/digest` endpoint returning `recommended_config` shape `dict[str, Any]`. The endpoint is gated on study.status === 'completed' + digest existence; both gates determine the checkbox visibility.
  - `feat_study_lifecycle` — `studies.search_space` JSONB column; `SearchSpace` Pydantic validator.
- **Soft coordinations:**
  - `feat_agent_propose_search_space` — Step-4 autofill suppression on non-empty prefilled `search_space_text` (existing behavior). This feature relies on that suppression already being in effect during a clone flow.
- **Operator environment:** no new env vars, no new secrets, no new compose services, no migration.
- **Test infrastructure:** existing Playwright real-backend pattern (e.g., `ui/tests/e2e/study-clone.spec.ts` from v1) is reused. No new test helpers required beyond seeding a `completed` study with a digest (existing `seed_meaningful_demos` patterns cover this; verified at [`backend/app/services/demo_seeding.py`](../../../../backend/app/services/demo_seeding.py)).

---

## 6) Actors and roles

- **Relevance Engineer (primary):** clicks "Clone study" on the study-detail page; lands in Step 1 of `CreateStudyModal` with prefilled fields and the v1 "Cloned from {name}" banner; advances to Step 4; sees the new checkbox + reference panel; opts into narrowing; submits; sees a new study whose `search_space` reflects the ±20% clamp.
- **Approver / Viewer:** unaffected.
- **`auto_followup` worker:** unaffected — never touches Step 4 UI or the new helper.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — audit_log lands at MVP2. Pre-MVP2, no event emission.

---

## 7) Functional requirements

- **FR-1 — Step-4 checkbox visible only when cloning AND digest is ready.** The checkbox renders if and only if **both** of the following hold:
  1. `initialValues?.cloneSource` is present (i.e., the modal is in clone mode);
  2. `useStudyDigest(initialValues?.cloneSource?.id, { enabled: Boolean(initialValues?.cloneSource?.id) })` returned `status === 'success'` AND `data.recommended_config` is a non-empty object (i.e., the source has at least one winning param).

  The hook is **always called unconditionally** at the top of the modal component (Rules of Hooks); the `enabled` option suppresses the request in the non-clone path. When either gate fails (no `cloneSource`, OR digest is loading / error / 404, OR `recommended_config` is empty), the checkbox is **absent from the DOM** — not disabled (per D-1). The reference panel inherits the same gate.

- **FR-2 — Default unchecked.** The checkbox initializes to `false` on every modal open. Submitting and reopening the modal does not persist the prior choice (no `localStorage`, no `PrefillValues` field). Per-modal-open ephemeral.

- **FR-3 — Checkbox label and tooltip.** Label text: `"Narrow bounds around the source study's winning params (±20%)"`. A trailing `<InfoTooltip glossaryKey="study.narrow_bounds_checkbox" />` renders the glossary definition.

- **FR-4 — On check, rewrite `search_space_text`.** When the engineer transitions the checkbox `false → true`:
  1. Capture the current `search_space_text` value as the baseline: `originalSpaceJsonRef.current = form.getValues('search_space_text')`. The ref is overwritten on every `false → true` transition so the baseline always equals what the textarea showed at the moment of opt-in.
  2. Call `result = narrowBoundsAroundWinner(originalSpaceJsonRef.current, recommended_config, 20)`.
  3. **No-op gate:** if `result.narrowed.length === 0` (every numeric param skipped — all-categorical space, all-missing-winner, all-degenerate, etc.), **do NOT** call `form.setValue`. Leave the textarea bytes exactly as the engineer wrote them; do NOT canonicalize. Surface a non-error toast: `"No params narrowed — every param is categorical, missing from the winner, or its winner is outside the current bounds."` The checkbox stays checked (the engineer's choice to opt in is preserved; uncheck still works the usual way).
  4. Otherwise (`result.narrowed.length > 0`): call `form.setValue('search_space_text', result.json)` so both the textarea and the rich `SearchSpaceBuilder` reflect the narrowed bounds.
  5. If the helper throws (malformed JSON in the textarea — `SyntaxError` from `JSON.parse`), surface a toast (`"Couldn't narrow bounds: search-space JSON is invalid — fix it and try again."`), revert the checkbox to unchecked, leave `search_space_text` untouched, and clear `originalSpaceJsonRef.current` (no baseline captured). Do NOT throw past the checkbox handler.

- **FR-5 — On uncheck, restore from the captured baseline.** When the engineer transitions the checkbox `true → false`, call `form.setValue('search_space_text', originalSpaceJsonRef.current)` to restore the value that was in the textarea at the most-recent `false → true` capture, then clear the ref (`originalSpaceJsonRef.current = null`). On the typical clone flow (capture happened with the verbatim-cloned JSON in the textarea), this returns the engineer to the verbatim-source baseline.

- **FR-6 — Manual edits made AFTER checking are discarded on uncheck.** If the engineer checks the box (rewrite applies), then manually edits the rewritten textarea, then unchecks, the manual post-rewrite edits are discarded — the textarea restores to `originalSpaceJsonRef.current`. Pre-check manual edits (those made BEFORE checking, captured into the baseline at the moment of opt-in) ARE preserved because they're in the captured baseline. This is the right tradeoff: "uncheck" means "back out the smart-rewrite," not "keep my partial post-rewrite edits." Document this in the glossary tooltip (see FR-13).

- **FR-7 — Modal close resets the toggle.** Closing the modal (Cancel button, ESC, submit, or `open=false` prop transition) discards the checkbox state AND the `originalSpaceJson` ref. The next modal open re-initializes to unchecked.

- **FR-8 — Reference panel shows the source's winning values.** Below the checkbox (whether checked or not, as long as the gate in FR-1 passes), render:

  ```
  ▶ Best-trial values from {cloneSource.name}      ← <details> summary, collapsed by default

      Param           Winning value
      ─────────────────────────────
      title_boost     2.34
      fuzziness       "AUTO"
      min_should_match  3
  ```

  Source: `recommended_config` from `useStudyDigest`. Rendered as a small two-column `<table>` inside the `<details>` element. Param names sorted alphabetically. Values rendered via `JSON.stringify(v)` so strings are quoted and booleans/numbers are visible. `data-testid="narrow-bounds-reference-panel"` on the `<details>` element; `data-testid="narrow-bounds-reference-row"` on each `<tr>`.

- **FR-9 — Narrow helper contract.** `narrowBoundsAroundWinner` in `ui/src/lib/narrow-bounds.ts` has the signature:

  ```typescript
  export interface NarrowBoundsResult {
    /** The rewritten search_space JSON (valid SearchSpace shape). */
    json: string;
    /** Params whose bounds were narrowed. */
    narrowed: string[];
    /** Params skipped because they were categorical, missing from winnerParams, had a non-numeric winner value, or hit a degenerate case (winner outside bounds AND ±% disjoint from current). */
    skipped: { name: string; reason: 'categorical' | 'missing_winner' | 'non_numeric_winner' | 'degenerate_intersection' | 'log_uniform_zero_floor' }[];
  }

  export function narrowBoundsAroundWinner(
    spaceJson: string,
    winnerParams: Record<string, unknown>,
    percent?: number, // default 20
  ): NarrowBoundsResult;
  ```

  Throws `SyntaxError` only if `spaceJson` is not parseable JSON. Never throws on a structurally-valid space — degenerate cases surface in `skipped` so the caller (and tests) can assert on them.

- **FR-10 — Clamp algorithm (numeric params).** For each entry `(name, spec)` in `parsed.params`:
  - If `spec.type === 'categorical'`: skip with `reason: 'categorical'`.
  - Else if `name not in winnerParams`: skip with `reason: 'missing_winner'`.
  - Else if `typeof winnerParams[name] !== 'number'`: skip with `reason: 'non_numeric_winner'`.
  - Else let `w = winnerParams[name]`, `oldLow = spec.low`, `oldHigh = spec.high`, `p = percent / 100`.
    - **Compute the unordered ±p% target pair (negative-safe):** `a = w * (1 - p)`, `b = w * (1 + p)`. Then `targetLow = Math.min(a, b)`, `targetHigh = Math.max(a, b)`. For `w > 0`: `a < b` (the obvious case). For `w < 0`: `a > b` (e.g., `w = -10, p = 0.20 → a = -8, b = -12 → targetLow = -12, targetHigh = -8`). For `w === 0`: `a = b = 0`, the param is skipped with `reason: 'degenerate_intersection'` since no positive-width range exists.
    - Clamp to old bounds: `newLow = max(oldLow, targetLow)`, `newHigh = min(oldHigh, targetHigh)`.
    - If `spec.type === 'float'` AND `spec.log === true`: `newLow = max(newLow, 1e-12)`. If after that `newLow >= newHigh`, skip with `reason: 'log_uniform_zero_floor'`.
    - If `spec.type === 'int'`: `newLow = Math.ceil(newLow)`, `newHigh = Math.floor(newHigh)`. If `newLow > newHigh`, skip with `reason: 'degenerate_intersection'`.
    - If `newLow >= newHigh` (float case) OR `newLow > newHigh` (int case caught above): skip with `reason: 'degenerate_intersection'`. (For ints, `newLow === newHigh` is valid — single-value range — and is NOT a skip.)
    - Otherwise: set `parsed.params[name].low = newLow`, `parsed.params[name].high = newHigh`. Add `name` to `narrowed`.

  Return `JSON.stringify(parsed, null, 2)` as `json`.

- **FR-11 — Winner-outside-current-bounds handling.** If the winner is below `oldLow` (e.g., source had `low=5` but the recommended_config value is 3 due to a manually-narrowed source space + a winning trial from before the narrowing), the clamp `newLow = max(oldLow, targetLow)` and `newHigh = min(oldHigh, targetHigh)` naturally produces `newLow = oldLow`, `newHigh = min(oldHigh, w * 1.2)`. If `w * 1.2 < oldLow`, `newHigh < oldLow` → degenerate, skip with `degenerate_intersection`. **No invalid range is ever produced.** Same logic applies symmetrically for winners above `oldHigh`.

- **FR-12 — Submit-time validation unchanged.** The rewritten `search_space_text` flows through the existing Step-4 submit path: JSON.parse → backend `SearchSpace.model_validate` → server-side `validate_against_template`. The narrow-bounds rewrite produces JSON that passes every existing check (FloatParam: low < high, log → low > 0; IntParam: low ≤ high; cardinality cap 10⁶; declared-params match). No new server-side validation is required.

- **FR-13 — Glossary key added.** Single new entry: `study.narrow_bounds_checkbox` (text per §2 "Tooltips and contextual help"). Owner: Story 1.5.

- **FR-14 — UI architecture doc updated.** Add a paragraph to [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) under "Step-4 search-space patterns" (or a new subsection if none exists), documenting `narrowBoundsAroundWinner` as the canonical "derived value toggle" pattern: an opt-in transformation of a prefilled form field, with the original value held in a ref for restoration on uncheck.

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

No new endpoints. This feature consumes two pre-existing endpoints:

| Method | Path | Purpose | Key error codes (existing — surfaced by hooks) |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/digest` | Read `recommended_config` for the source study | `404 STUDY_NOT_FOUND`, `404 DIGEST_NOT_READY` (retryable) |
| `POST` | `/api/v1/studies` | Submit the cloned study (existing v1 path) | `400 INVALID_SEARCH_SPACE`, `400 SEARCH_SPACE_UNKNOWN_PARAM`, `400 SEARCH_SPACE_MISSING_DECLARED_PARAM`, `404 PARENT_STUDY_NOT_FOUND`, `422 PARENT_STUDY_WRONG_CLUSTER`, `422 VALIDATION_ERROR` |

### 8.2 Contract rules

- The rewritten `search_space_text` MUST parse to a valid `SearchSpace` (per `backend/app/domain/study/search_space.py`).
- `recommended_config` is a flat `dict[str, Any]` per [`backend/app/api/v1/schemas.py:1005`](../../../../backend/app/api/v1/schemas.py#L1005). Values may be `number | string | boolean | null`. The helper rejects non-numeric values for numeric params via the `non_numeric_winner` skip reason; no runtime crash.
- `useStudyDigest` already suppresses the global error toast for `DIGEST_NOT_READY` ([digests.ts:20](../../../../ui/src/lib/api/digests.ts#L20)) — the FR-1 gate uses `status === 'success'` to detect the ready state without surfacing the underlying 404 to the operator.

### 8.3 Response examples

**Source study's digest (sample, with three params):**

```json
{
  "id": "01935a40-...",
  "study_id": "01935a30-...",
  "narrative": "Best trial achieved nDCG@10 of 0.74 ...",
  "parameter_importance": { "title_boost": 0.42, "fuzziness": 0.31, "min_should_match": 0.27 },
  "recommended_config": {
    "title_boost": 2.34,
    "fuzziness": "AUTO",
    "min_should_match": 3
  },
  "suggested_followups": [],
  "generated_by": "openai:gpt-4o-2024-08-06",
  "generated_at": "2026-05-25T18:30:42Z"
}
```

**Source study's `search_space` (sample, verbatim-cloned into the textarea):**

```json
{
  "params": {
    "title_boost":      { "type": "float",       "low": 0.5, "high": 5.0,    "log": false },
    "fuzziness":        { "type": "categorical", "choices": ["AUTO", "0", "1", "2"] },
    "min_should_match": { "type": "int",         "low": 1,   "high": 5 }
  }
}
```

**After `narrowBoundsAroundWinner(spaceJson, recommended_config, 20)`** (`result.json`):

```json
{
  "params": {
    "title_boost":      { "type": "float",       "low": 1.872, "high": 2.808, "log": false },
    "fuzziness":        { "type": "categorical", "choices": ["AUTO", "0", "1", "2"] },
    "min_should_match": { "type": "int",         "low": 3,     "high": 3 }
  }
}
```

Computation:

- `title_boost`: winner=2.34, ±20% → `[1.872, 2.808]` ⊂ `[0.5, 5.0]` → narrowed.
- `fuzziness`: categorical → skipped with `reason: 'categorical'`.
- `min_should_match`: winner=3, ±20% → target `[2.4, 3.6]` → `Math.ceil(2.4)=3`, `Math.floor(3.6)=3` → single-value range `[3, 3]`. Per `IntParam`'s validator (`low <= high` allows equality), this is valid → narrowed.

`result.narrowed === ["min_should_match", "title_boost"]` (sorted by insertion order in `params`); `result.skipped === [{ name: "fuzziness", reason: "categorical" }]`.

### 8.4 Enumerated value contracts

None. (See §2 "Enumerated value contracts".)

### 8.5 Error code catalog

No new error codes.

---

## 9) Data model and state transitions

**No schema changes.** No new tables, no new columns, no new migrations. The feature reads from existing tables (`digests` via the API) and writes to existing columns (`studies.search_space` via the existing POST path).

### Required invariants

- **Narrowing never widens.** Every clamped `new_low >= old_low`; every clamped `new_high <= old_high`. Verified by the FR-10 algorithm; enforced by unit tests (AC-4).
- **Rewritten JSON validates server-side.** Every output of `narrowBoundsAroundWinner` on a structurally-valid input passes `SearchSpace.model_validate`. Verified by the contract-level invariant test (AC-7).
- **Per-modal-open ephemerality.** Checkbox state and `originalSpaceJson` ref are reset on every modal `open=false → open=true` transition. No global state, no localStorage.

### State transitions

Checkbox state machine (per-modal-open). The invariant: `originalSpaceJsonRef.current` is captured fresh on every `false → true` transition and cleared on every `true → false` transition or modal close.

```
INITIAL  [unchecked, ref = null]

  ↓ user clicks (false → true)
  ↓ capture: ref = current textarea value
  ↓ rewrite path branches:
  │
  ├─ result.narrowed.length > 0
  │     → form.setValue(search_space_text, result.json)
  │     → [checked, ref = pre-rewrite JSON, textarea = rewritten JSON]
  │
  ├─ result.narrowed.length === 0
  │     → no setValue; toast "No params narrowed: ..."
  │     → [checked, ref = pre-rewrite JSON, textarea = unchanged]
  │
  └─ helper throws (SyntaxError)
        → no setValue; toast "Couldn't narrow bounds: ..."
        → revert checkbox to unchecked
        → clear ref
        → [unchecked, ref = null]  (no state mutation beyond toast)

CHECKED  [either narrowed or no-op]

  ↓ user unchecks (true → false)
  ↓ form.setValue(search_space_text, ref)  (restore captured baseline)
  ↓ ref = null
  ↓ [unchecked, ref = null]

CHECKED  [either narrowed or no-op]

  ↓ user closes the modal (Cancel, ESC, submit success, open=false transition)
  ↓ both checkbox state AND ref discarded
  ↓ next modal open re-initializes to INITIAL
```

**Pre-check manual edits ARE preserved** (they live in the captured ref). **Post-check manual edits are discarded on uncheck** (the ref holds the pre-check value, not the post-rewrite-then-edited value). Per FR-6 lock — documented in the glossary tooltip.

### Idempotency / replay behavior

N/A — synchronous frontend transformation, no events, no enqueue.

---

## 10) Security, privacy, and compliance

- **Threats:**
  - **T1 — Operator confusion ships an unintended search space.** The rewrite could surprise an engineer who doesn't realize the textarea was mutated. Mitigation: the checkbox is opt-in (default unchecked); unchecking restores the original; the reference panel shows the winning values inline so the engineer can sanity-check before submitting.
  - **T2 — Helper produces an invalid space that bypasses validation.** The server-side `SearchSpace.model_validate` is the canonical guard (400 `INVALID_SEARCH_SPACE`). Even a bug in `narrowBoundsAroundWinner` cannot ship an invalid space — the server rejects it. Mitigation: helper unit tests cover every constraint mirrored from `search_space.py`; contract-level invariant test asserts every output of the helper passes server validation (AC-7).
- **Controls:** None new. The feature is a pure frontend transformation of operator-supplied JSON, no new secrets, no new auth surface.
- **Secrets / key handling:** N/A.
- **Auditability:** N/A — audit_log lands at MVP2.
- **Data retention:** N/A.

---

## 11) UX flows and edge cases

### Primary flow

1. Engineer opens study X (status=`completed`) detail page.
2. Clicks "Clone study" → navigates to `/studies?clone_from=X`.
3. Page fetches study X via `useStudy(X)`, builds `PrefillValues` via `buildPrefillFromStudy`, opens `CreateStudyModal` with `initialValues`.
4. Modal shows the v1 "Cloned from study X (name)" banner above Step 1. Engineer leaves Steps 1–3 unchanged.
5. Engineer advances to Step 4. The modal also fires `useStudyDigest(X)` in the background; while it loads, Step 4 renders without the new checkbox (FR-1 gate not yet ready).
6. Digest resolves successfully. Step 4 now shows: `[ ] Narrow bounds around the source study's winning params (±20%)` above the search-space body, and a collapsed `▶ Best-trial values from {source.name}` disclosure below it.
7. Engineer expands the disclosure, reviews the winning values.
8. Engineer checks the box. Textarea + builder update to show narrowed bounds. Visual confirmation that the rewrite landed.
9. Engineer optionally edits one param manually (e.g., loosens `title_boost` from `[1.87, 2.81]` to `[1.5, 3.0]`).
10. Engineer clicks Submit. POST flows through the existing v1 clone path; server validates the (narrowed + manually-tweaked) `search_space`; new study persists.

### Edge / error flows

- **Source not completed:** `useStudyDigest` returns 404 `DIGEST_NOT_READY` → FR-1 gate fails → checkbox and reference panel are absent. The clone still works as verbatim-copy.
- **Source completed but digest hasn't been written yet** (worker lag): same as above — gate fails, checkbox absent. Engineer can refresh later if they want to opt in.
- **Source has zero numeric params** (e.g., all categorical): `recommended_config` is non-empty, gate passes, checkbox renders. On check, every param is skipped with `reason: 'categorical'`; per FR-4 step 3, `form.setValue` is NOT called (the textarea bytes stay exactly as the engineer wrote them — no whitespace normalization), and a non-error toast surfaces: `"No params narrowed — every param is categorical, missing from the winner, or its winner is outside the current bounds."` The checkbox stays checked. Acceptable — the engineer is informed why nothing changed and can uncheck if desired. (Optional follow-up: hide the checkbox entirely when every param is categorical. Out of scope for v1.)
- **Helper throws (malformed JSON in textarea):** the engineer has manually edited the textarea into a syntactically-broken state. Toast: `"Couldn't narrow bounds: search-space JSON is invalid — fix it and try again."` Checkbox reverts to unchecked. Original ref is not captured (no rewrite happened).
- **Engineer checks → unchecks → checks again:** on the second check, `originalSpaceJsonRef.current` is freshly recaptured from the current textarea (which is the restored captured-baseline value — typically the verbatim source). The rewrite re-runs. Multiple toggle cycles are stable.
- **Engineer checks → manually edits → unchecks:** the manual edits are discarded; the textarea restores to the verbatim source. Per FR-6, this is intentional. The glossary tooltip warns: "Uncheck to restore the source's bounds."
- **All params skipped (degenerate case):** if every numeric param hits `degenerate_intersection` or `log_uniform_zero_floor`, the rewrite is byte-identical. The engineer sees no visible change. Same outcome as zero-numeric-params case; acceptable for v1.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Checkbox visible when cloning a completed study with a digest

- **Given** a `completed` study X with a digest containing `recommended_config = {"title_boost": 2.34}`
- **When** the engineer clicks "Clone study" on X's detail page, lands in the modal, and advances to Step 4
- **Then** the checkbox labeled "Narrow bounds around the source study's winning params (±20%)" is present in the DOM at Step 4, AND a collapsed `<details>` element with summary "Best-trial values from {X.name}" is present below it.
- **Example values:**
  - Selector: `getByLabelText(/Narrow bounds around the source/)` → resolves
  - Selector: `getByTestId('narrow-bounds-reference-panel')` → resolves

### AC-2: Checkbox absent on bare "New study" flow

- **Given** the engineer clicks "New study" (no `?clone_from`) on the studies list
- **When** Step 4 renders
- **Then** the narrow-bounds checkbox is absent from the DOM (`queryByLabelText` returns null).

### AC-3: Checkbox absent when source study has no digest

- **Given** a `running` study Y (digest endpoint returns 404 `DIGEST_NOT_READY`)
- **When** the engineer clones Y and advances to Step 4
- **Then** the narrow-bounds checkbox is absent from the DOM, AND the verbatim clone flow continues to work — `search_space_text` is the source's verbatim JSON, and the engineer can submit unchanged.

### AC-4: On check, numeric bounds clamp to ±20%

- **Given** source study X with `search_space = {"params": {"title_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": false}}}` and `recommended_config = {"title_boost": 2.34}`
- **When** the engineer checks the narrow-bounds box
- **Then** the textarea's parsed content has `params.title_boost.low === 1.872` AND `params.title_boost.high === 2.808` (winner * 0.8, winner * 1.2; both within the source's old bounds).
- **Example values:**
  - Input JSON: as above
  - Expected JSON (whitespace-tolerant): `params.title_boost = { type: "float", low: 1.872, high: 2.808, log: false }`

### AC-5: On uncheck, original bounds restore

- **Given** AC-4's post-check state (textarea showing narrowed bounds)
- **When** the engineer unchecks the box
- **Then** the textarea's parsed content has `params.title_boost.low === 0.5` AND `params.title_boost.high === 5.0` (restored to the verbatim source).

### AC-6: Categoricals and missing-from-winner params are skipped

- **Given** source X with `search_space = {"params": {"title_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": false}, "fuzziness": {"type": "categorical", "choices": ["AUTO", "0", "1"]}, "unrelated_param": {"type": "int", "low": 1, "high": 10}}}` and `recommended_config = {"title_boost": 2.34, "fuzziness": "AUTO"}` (`unrelated_param` absent from winner)
- **When** the engineer checks the box
- **Then** `title_boost` is narrowed; `fuzziness` is unchanged (still `choices: ["AUTO", "0", "1"]`); `unrelated_param` is unchanged (`low=1, high=10`).

### AC-7: Rewritten JSON passes server-side validation (representative scenarios)

- **Given** the representative scenarios covered by the AC-12 Playwright E2E (a `completed` study with a mixed float/int/categorical search space and a populated `recommended_config`) AND the spectrum of helper outputs covered by the AC-4 / AC-6 / AC-8 / AC-9 unit tests
- **When** the rewritten JSON is POSTed to `/api/v1/studies`
- **Then** the server returns 201 (or any non-422 / non-400 error path); the response is NOT `INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, or `SEARCH_SPACE_MISSING_DECLARED_PARAM`.
- **Scope note:** this AC asserts validity over the *test fixtures* and the *E2E happy path*, not over the universe of structurally-valid inputs. The helper's algorithm in FR-10 is designed so that every output is a structurally-valid `SearchSpace` (every per-type constraint mirrored from `search_space.py`); unit tests in AC-4 / AC-6 / AC-8 / AC-9 exercise every algorithm branch, providing the de-facto property coverage without a property-based test layer.

### AC-8: Log-uniform float param preserves `low > 0`

- **Given** a float param `boost = {type: "float", low: 1e-6, high: 100, log: true}` and winner value `boost = 0.001`
- **When** the helper runs
- **Then** the result either narrows to a valid range with `new_low > 0` (e.g., `[0.0008, 0.0012]` if both fall above 1e-12), OR skips with `reason: 'log_uniform_zero_floor'` if `new_low` would land below the EPSILON floor. **Never** produces `new_low <= 0` for `log=true`.

### AC-9: Winner outside current bounds → degenerate skip, no invalid range

- **Given** a float param `x = {type: "float", low: 5.0, high: 10.0, log: false}` and winner `x = 1.0` (below the current low)
- **When** the helper runs
- **Then** the result skips with `reason: 'degenerate_intersection'` (because `targetHigh = 1.2`, `newHigh = min(10, 1.2) = 1.2 < oldLow=5` → `newLow=5, newHigh=1.2` → invalid → skip). The param's `low/high` in the output JSON are byte-identical to the input.

### AC-10: Reference panel renders the winning values

- **Given** AC-1's setup
- **When** the engineer expands the `<details>` panel
- **Then** each row in the panel shows `{param_name} | {JSON.stringify(winner_value)}`, sorted alphabetically by param name, AND the panel's summary text is `"Best-trial values from {cloneSource.name}"` (NOT the form's edited `name` value — banner-style stability per the v1 clone spec FR-12).

### AC-11: Checkbox state and originalSpaceJson reset on modal close

- **Given** the engineer has checked the box (textarea is narrowed)
- **When** the engineer closes the modal (clicks Cancel, presses ESC, or submits successfully)
- **And** the engineer re-opens the clone of the same source
- **Then** the checkbox is unchecked, the textarea shows the verbatim source's `search_space_text` (per FR-7), and the original-ref state is freshly empty.

### AC-12: Real-backend E2E — clone with narrow bounds persists correctly

- **Given** a real-backend stack with a seeded `completed` study X (digest written, `recommended_config` populated)
- **When** the engineer clicks "Clone study", advances to Step 4, checks the narrow-bounds box, and submits
- **Then** `GET /api/v1/studies/{new_id}` returns a study whose `search_space.params` contain the clamped numeric bounds (matching the ±20% clamp computed from X's `recommended_config`).

---

## 13) Non-functional requirements

- **Performance:** the rewrite is synchronous JSON.parse + Object.entries map + JSON.stringify. Sub-millisecond on a realistic search-space (≤ 10 params). No user-visible latency.
- **Reliability:** the helper is pure (no I/O, no async, no DB). 100% deterministic; trivially unit-testable. Server-side validation is the canonical guard.
- **Operability:** no new metrics, no new log events, no new alerts. The feature is silent from the backend's perspective — the same `POST /studies` log line fires whether the search space was narrowed or not.
- **Accessibility:** the checkbox uses the existing shadcn-ui `<Checkbox>` primitive with proper `aria-label` from its associated `<Label>`. The reference panel uses native `<details>` which is keyboard-accessible by default. Both elements are reachable by tab.

---

## 14) Test strategy requirements (spec-level)

### Unit tests (`ui/src/__tests__/lib/narrow-bounds.test.ts`)

Pure-helper tests for every algorithm branch in FR-10 + edge cases in §11:

- Float param: simple positive winner inside old bounds → narrowed `[w*0.8, w*1.2]`
- Float param: **negative winner** (e.g., `w = -10`, `oldLow = -20, oldHigh = 0`) → narrowed `[-12, -8]` (negative-safe min/max per FR-10)
- Float param: winner = 0 → skip with `degenerate_intersection` (no positive-width range)
- Float param: winner below `oldLow` → degenerate skip
- Float param: winner above `oldHigh` → degenerate skip
- Float param with `log=true`: clamped `low` > 0 → preserved
- Float param with `log=true`: clamped `low` would be ≤ 0 → skip with `log_uniform_zero_floor`
- Int param: simple clamp with rounding → ceil(low) / floor(high)
- Int param: **negative winner** (e.g., `w = -3`, `oldLow = -10, oldHigh = 10`) → narrowed (target `[-3.6, -2.4]`, ceil/floor → `[-3, -3]`)
- Int param: degenerate after ceil/floor (e.g., `[2.4, 2.6]` → `[3, 2]`) → skip with `degenerate_intersection`
- Int param: single-value range result (e.g., winner=3 → `[3, 3]`) → narrowed
- Categorical param → skip with `categorical`
- Param in `space` but not in `winnerParams` → skip with `missing_winner`
- Param in `winnerParams` with non-numeric value (string, bool, null) on a numeric spec → skip with `non_numeric_winner`
- Multiple params: mix of narrowed + skipped; assert `result.narrowed` and `result.skipped` shapes
- All-skipped input (e.g., all categorical): `result.narrowed === []`, `result.skipped` populated
- Custom percent (e.g., 10%, 50%)
- Malformed JSON input → throws `SyntaxError`

### Component tests (`ui/src/components/studies/__tests__/create-study-modal.test.tsx`)

Extend the existing test file with cases:

- Checkbox absent on bare "New study" open (no `initialValues`)
- Checkbox absent when `initialValues.cloneSource` set but `useStudyDigest` returns error (mocked via TanStack Query test wrapper)
- Checkbox present when both gates pass; default unchecked
- On check: textarea content updates to the narrowed JSON (assert via parsing `getByLabelText('Search space (JSON)').value`)
- On uncheck: textarea restores to verbatim source's JSON
- Submit after check sends the narrowed JSON in the POST body (regression on the `_serializePayload` discipline established by v1 clone Story 2.2)
- Reference panel renders rows sorted alphabetically; row count matches `Object.keys(recommended_config).length`
- Banner stability: editing the form's `name` field does not change the reference panel's summary text (uses `cloneSource.name`)

### Contract tests

None new. (No backend changes; existing contract tests on `POST /studies` already cover the request shape and error envelope.)

### E2E tests (`ui/tests/e2e/study-clone-narrow-bounds.spec.ts` — NEW)

Real-backend Playwright spec, one happy-path case:

1. Use the demo-reseed endpoint (`POST /api/v1/_test/demo/reseed`) to seed a `completed` study with a digest. Alternatively, use the existing `seedStudyCompletedWithDigest` helper from `infra_e2e_seed_completed_study` if it covers digest seeding.
2. Navigate to `/studies/{seeded_id}`.
3. Click "Clone study"; verify modal opens with the cloned-from banner.
4. Click "Next" through Steps 1–3.
5. On Step 4, assert the narrow-bounds checkbox is visible.
6. Check the box.
7. Read the `search_space_text` textarea value, parse it, assert at least one numeric param has bounds narrower than the source's.
8. Click Submit.
9. Wait for navigation to `/studies/{new_id}`.
10. Call `GET /api/v1/studies/{new_id}` via the request fixture; assert `search_space.params.<any_numeric_param>.low/high` matches the ±20% clamp computed from the source's `recommended_config`.

Per CLAUDE.md "E2E Testing Rules": no `page.route()` mocking. Real backend, real digest, real POST.

### Coverage gate

No new gate. The existing 80% coverage gate covers the new helper file via the unit tests above (target: 100% line/branch on `narrow-bounds.ts`).

---

## 15) Documentation update requirements

- **`docs/01_architecture/ui-architecture.md`**: add a paragraph under (or create) a "Step-4 derived-value toggles" subsection documenting `narrowBoundsAroundWinner` as the canonical pattern for opt-in transformations of prefilled form fields with restore-on-uncheck via a `useRef`. Cross-link to this spec.
- **`docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md`**: add a single line under "Out of scope" pointing forward to this feature as the now-implemented follow-up (`feat_study_clone_narrow_bounds`).
- **`docs/02_product/planned_features/feature_templates/`**: no changes.
- **`docs/03_runbooks/`**: no changes (no new operator-facing surface).
- **`docs/04_security/`**: no changes (no new secrets, no new data flow).
- **`docs/05_quality/`**: no changes.
- **Guide update assessment:** the existing tutorial guide (`docs/08_guides/tutorial-first-study.md`) walks through the first study but doesn't cover cloning. No regression. A future "Iterate on a study with narrow bounds" guide is captured as a deferred idea (out of scope for this spec; no `phase2_idea.md` required since this is single-phase).

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. Pure frontend; ships behind no flag.
- **Migration / backfill:** none. No schema changes.
- **Operational readiness gates:** none.
- **Release gate:** CI green (lint, typecheck, vitest, Playwright E2E in the dedicated lane) before merge.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories | Test files |
|---|---|---|---|
| FR-1 (gate) | AC-1, AC-2, AC-3 | Story 1.3 | `create-study-modal.test.tsx` + E2E |
| FR-2 (default unchecked) | AC-1 | Story 1.3 | `create-study-modal.test.tsx` |
| FR-3 (label + tooltip) | AC-1 | Story 1.3, 1.5 | `create-study-modal.test.tsx` |
| FR-4 (check → rewrite) | AC-4, AC-6, AC-12 | Story 1.3 | `create-study-modal.test.tsx` + E2E |
| FR-5 (uncheck → restore) | AC-5, AC-11 | Story 1.3 | `create-study-modal.test.tsx` |
| FR-6 (manual edits discarded on uncheck) | AC-5 (covered via the restore semantics) | Story 1.3 | `create-study-modal.test.tsx` |
| FR-7 (modal close resets) | AC-11 | Story 1.3 | `create-study-modal.test.tsx` |
| FR-8 (reference panel) | AC-10 | Story 1.4 | `create-study-modal.test.tsx` + E2E |
| FR-9 (helper contract) | AC-4, AC-6, AC-8, AC-9 | Story 1.1 | `narrow-bounds.test.ts` |
| FR-10 (clamp algorithm) | AC-4, AC-6, AC-8, AC-9 | Story 1.1 | `narrow-bounds.test.ts` |
| FR-11 (winner outside bounds) | AC-9 | Story 1.1 | `narrow-bounds.test.ts` |
| FR-12 (submit validation unchanged) | AC-7, AC-12 | Story 1.6 | E2E + existing contract tests |
| FR-13 (glossary key) | AC-1 (via tooltip reachability) | Story 1.5 | `create-study-modal.test.tsx` |
| FR-14 (doc update) | — | Story 1.6 | manual review |

**Story breakdown anchor** (final stories assigned in `/impl-plan-gen`):

- **Story 1.1:** Pure helper `narrowBoundsAroundWinner` + unit tests (covers FR-9, FR-10, FR-11; includes negative-winner and zero-winner cases).
- **Story 1.2:** Extend `useStudyDigest(studyId, { enabled? })` (backward-compat additive opts arg) AND wire it into `CreateStudyModal` Step 4 with the gate computation (no UI changes yet).
- **Story 1.3:** Checkbox UI + check/uncheck handlers + state management (FR-1 through FR-7).
- **Story 1.4:** Reference panel (FR-8).
- **Story 1.5:** Glossary entry + tooltip wiring (FR-3, FR-13).
- **Story 1.6:** Playwright E2E + documentation updates (FR-12, FR-14).

---

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] Unit tests for `narrowBoundsAroundWinner` achieve ≥95% line/branch coverage.
- [ ] Vitest component tests cover all FR-1 through FR-7 behaviors.
- [ ] One Playwright real-backend E2E spec asserts the happy path end-to-end.
- [ ] Glossary entry `study.narrow_bounds_checkbox` is in `ui/src/lib/glossary.ts`.
- [ ] `docs/01_architecture/ui-architecture.md` gains the "Step-4 derived-value toggles" paragraph.
- [ ] `docs/00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/feature_spec.md` "Out of scope" gains the forward-pointer line.
- [ ] CI green on the feature branch.
- [ ] No open questions remain in §19.

---

## 19) Open questions and decision log

### Open questions

None at spec-finalization time. All four open questions from the idea (OQ-N1 through OQ-N4) are locked in the Decision log below.

### Decision log

- **2026-05-25 — D-1 (hide-vs-disable when digest is unavailable):** Hide the checkbox + reference panel entirely when `useStudyDigest` is not in success state. Rationale: a disabled checkbox falsely implies the operator could enable it under unclear conditions; hiding signals "smart-rewrite requires a completed source with a digest, and this source doesn't have one." Verbatim-clone still works in that flow. (From idea OQ-N4 default.)

- **2026-05-25 — D-2 (clamp ratio is fixed ±20%):** v1 ships with a hardcoded `percent=20` constant. Variance-derived or operator-configurable clamp ratios are out of scope. Rationale: keeps the surface minimal and the helper trivially unit-testable; the 20% default is calibrated from the 2026-05-19 UX review's "exploit, don't explore" framing. (From idea OQ-N3.)

- **2026-05-25 — D-3 (categoricals are passed through untouched):** The helper never mutates `params[name].choices` or the categorical `type`. Rationale: "narrow" doesn't translate cleanly to "subset choices"; subsetting introduces a new UX question (which choices to keep?) that doesn't have an obvious heuristic; the operator can manually edit categoricals if they want to constrain them. (From idea OQ-N2.)

- **2026-05-25 — D-4 (skip params missing from `recommended_config`):** Per FR-10, params present in `search_space.params` but absent from `winnerParams` are skipped with `reason: 'missing_winner'`. Rationale: the most likely cause of this absence is a param added to the search_space after the winning trial was scored; clamping around a non-existent winner would silently corrupt the bounds. Surfacing as a skip is honest. (From idea OQ-N1.)

- **2026-05-25 — D-5 (winner-outside-current-bounds degrades gracefully):** When `[w*(1-p), w*(1+p)]` doesn't intersect `[oldLow, oldHigh]`, the param is skipped with `reason: 'degenerate_intersection'` rather than producing an out-of-range clamp. Rationale: the only way `new_low > new_high` arises is when the intersection is empty; any other outcome would produce a SearchSpace that fails server-side validation. (Forced lock — Anti-pattern.)

- **2026-05-25 — D-6 (per-modal-open ephemerality, no persistence):** Checkbox state and `originalSpaceJson` ref are reset on every modal close. No localStorage; no `PrefillValues` field. Rationale: the smart-rewrite is a derived-value toggle, not a study-level setting; persisting it would create a hidden state the operator can't see across sessions. (Spec-time lock.)

- **2026-05-25 — D-7 (manual edits post-check are discarded on uncheck):** Per FR-6, unchecking restores `originalSpaceJson` verbatim. Rationale: "uncheck" semantically means "I want the verbatim source back"; preserving partial post-rewrite edits would require complex merge logic with no clear correct behavior. Document in the glossary tooltip. (Spec-time lock.)

- **2026-05-25 — D-8 (reference panel collapsed by default):** Uses native `<details>`/`<summary>` with no `open` attribute. Rationale: keeps Step 4 visually quiet for engineers who already know what they want to narrow around; one-click disclosure is sufficient progressive reveal. (From idea "collapsed panel" wording.)

- **2026-05-25 — D-9 (no audit event):** Pre-MVP2, no audit_log table. The narrow-bounds opt-in is not separately auditable; the resulting study's `search_space` carries the narrowed shape, which is observable. (Forced lock — Activates at MVP2.)

- **2026-05-25 — D-10 (negative-winner clamp uses unordered min/max):** The clamp formula in FR-10 computes `a = w*(1-p)` and `b = w*(1+p)` then takes `targetLow = min(a, b)`, `targetHigh = max(a, b)` so a negative winner produces a correctly-ordered target range. A winner of exactly `0` produces `a === b === 0` which collapses to a zero-width target and skips with `degenerate_intersection`. Rationale: relevance-tuning params can be negative (offsets, signed weights); inverted clamps would silently degrade-skip every negative-winner param without narrowing. (From GPT-5.5 cycle-1 finding F2.)

- **2026-05-25 — D-11 (no-op narrowing leaves the textarea byte-exact):** When `result.narrowed.length === 0` (every numeric param skipped — all categorical / all missing-winner / all degenerate), the FR-4 handler does NOT call `form.setValue`. The textarea bytes stay exactly as the engineer wrote them — no JSON.stringify whitespace normalization. A non-error toast surfaces to explain why nothing changed. Rationale: pretending the rewrite ran by canonicalizing the JSON would surprise the engineer with a textarea diff (whitespace, key order) for an opt-in that had no functional effect. (From GPT-5.5 cycle-1 finding F7.)

- **2026-05-25 — D-12 (`useStudyDigest` signature is additively extended):** Story 1.2 widens `useStudyDigest(studyId: string)` to `useStudyDigest(studyId: string | undefined, opts?: { enabled?: boolean })` with `useQuery({ enabled: opts?.enabled ?? Boolean(studyId), ... })`. Existing single-argument callers (e.g., the digest panel on the studies-detail page) are unaffected. Rationale: the modal must call the hook unconditionally per Rules of Hooks but suppress the network request on the non-clone path; mirrors the `useStudy(id, { enabled })` pattern at [`ui/src/lib/api/studies.ts:67-88`](../../../../ui/src/lib/api/studies.ts#L67-L88). (From GPT-5.5 cycle-1 finding F5.)
