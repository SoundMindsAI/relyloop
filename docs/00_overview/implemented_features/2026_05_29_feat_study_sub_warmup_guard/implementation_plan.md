# Implementation Plan — Study Budget Sub-Warmup Guard

**Date:** 2026-05-29
**Status:** Complete (PR #316, ready to merge 2026-05-29)
**Primary spec:** [`feature_spec.md`](./feature_spec.md) (Approved — Opus + GPT-5.5 converged at cycle 3, 13 findings accepted)

## Cross-model review log

- **Cycle 1 (2026-05-29):** GPT-5.5 returned 5 findings.
  - **C1-#1 (Pass A, Medium) — Accepted.** "Story 1.1 doesn't reliably satisfy FR-7's `floor - 1` boundary." Patched: Story 1.1 now adds **three** new tests (value lock + `floor-1=49` → NopPruner + `floor=50` → MedianPruner using the constant) instead of relying on the existing 30-trial test to cover the boundary.
  - **C1-#2 (Pass A, Medium) — Accepted.** "Story 1.2's `// Values must match` comment isn't the immediately-preceding line per spec FR-5." Patched: reordered the Key interfaces snippet + clarified Task 2 + added "Important" call-out.
  - **C1-#3 (Pass B, Medium) — Accepted.** "Story 1.2 DoD asks for lint-green but Task 4 acknowledges `no-unused-vars` may flag." Patched: Story 1.2 DoD now explicitly defers the lint gate to Story 1.3; the two stories ship as one commit.
  - **C1-#4 (Pass B, Medium) — Accepted.** "AC-6 vitest snippet guesses submit button label + MSW response shape." Patched: snippet now reuses the existing `mockBackend()` helper's `postBodies` capture + cites the existing submit query pattern at file line 364. Submit-button query verified: `getByRole('button', { name: /Create study/i })` at line 364.
  - **C1-#5 (Pass B, Low) — REJECTED with counter-evidence.** GPT-5.5 claimed the `STUDIES_TPE_WARMUP_FLOOR: int = 50` followed by attribute-style docstring `"""..."""` "may trip lint." Counter-evidence: this is the established pattern in the same file at [`optuna_runtime.py:30-31`](../../../../../backend/app/eval/optuna_runtime.py#L30-L31) (`_OPTUNA_SEARCH_PATH_OPTION` uses exactly this pattern; ruff + mypy accept it). Matching the existing module style is correct; deviating to a `#`-comment block would be inconsistent with the file's own convention. **No change.**
- **Cycle 2 (2026-05-29):** GPT-5.5 returned 3 findings, all "downstream propagation" / "snippet refinement" — none re-raising C1-#5.
  - **C2-#1 (Pass A, Medium) — Accepted.** "Story 1.1's cycle-1 patch didn't propagate to §3.1 Unit tests, §10 Verification Gate, and the §1 FR-7 row." Patched: §3.1 now says "3 new tests + 15 total"; §10 says "+3 new tests"; §1 FR-7 row enumerates all three new tests explicitly.
  - **C2-#2 (Pass B, Medium) — Accepted.** "AC-1..AC-4 vitest tests don't call `mockBackend()` but AC-6 does — inconsistent with the file's per-test pattern; `walkToStep5()` needs the helper's MSW handlers." Patched: every new test now calls `mockBackend()` at top; pattern note explains rationale + `beforeEach` consolidation option.
  - **C2-#3 (Pass B, Low) — Accepted.** "Empty `afterEach(() => {})` hook may trip `no-empty-function`." Patched: removed; pattern note states the file-level afterEach handles cleanup.
- **Cycle 3 (2026-05-29):** GPT-5.5 returned 1 finding — final follow-on propagation cleanup.
  - **C3-#1 (Pass A, Medium) — Accepted.** "Stale '+1 new test' references survive in §0 Planning principles, §11 Plan↔codebase verification, and the final Verification ledger." Patched all three sections to "3 new tests" / "15 total" matching the rest of the plan. **Cycle 3 is the cap per skill stop rule; convergence achieved.**
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) Absolute Rules; [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) §"Optuna configuration"; [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md) Enumerated Value Contract Discipline

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs and ACs.
- The deliverable is intentionally small: 1 backend constant hoist + 1 frontend conditional `<p>` + 5 vitest cases + 3 new backend assertions (constant value lock + `floor - 1` NopPruner boundary + `floor` MedianPruner boundary using the constant — per GPT-5.5 cycle-1 C1-#1). No new endpoint, no migration, no LLM, no audit_log.
- The shared `50` constant is the discipline-bearing piece — every other change references it.
- Single-phase, single-epic. Convergence is verifiable by running existing test suites with the new assertions appended.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Story | Notes |
|---|---|---|---|
| FR-1 (backend constant hoist) | Epic 1 / Phase 1 | Story 1.1 | Mechanical refactor of the inline `50` at [`optuna_runtime.py:121`](../../../../../backend/app/eval/optuna_runtime.py#L121) to module-level `STUDIES_TPE_WARMUP_FLOOR`. |
| FR-2 (conditional render) | Epic 1 / Phase 1 | Story 1.3 | New `<p data-testid="cs-sub-warmup-warning">` between modal lines 1282 and 1283; mount guard uses `activePreset === 'custom' && typeof watchedMaxTrials === 'number' && !Number.isNaN(watchedMaxTrials) && Number.isInteger(watchedMaxTrials) && watchedMaxTrials < SUB_WARMUP_FLOOR`. |
| FR-3 (warning copy) | Epic 1 / Phase 1 | Story 1.3 | Copy ships with the element (same JSX block); names "Focused (50)" and "Standard (200)" by exact `presetLabel` strings. |
| FR-4 (~~glossary~~) | — | **Dropped** | Per spec D-0a; no story. The FR-4 slot is retained for ID stability across FR-5/6/7. |
| FR-5 (frontend constant + comment) | Epic 1 / Phase 1 | Story 1.2 | `const SUB_WARMUP_FLOOR = 50;` near modal lines 91-110 with `// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR` immediately above. |
| FR-6 (vitest cases) | Epic 1 / Phase 1 | Story 1.4 | Five cases appended to `create-study-modal.stop-conditions.test.tsx`; reuses existing `walkToStep5` + preset helpers + MSW handler at line 138. |
| FR-7 (backend test) | Epic 1 / Phase 1 | Story 1.1 | Three new tests appended to `test_optuna_runtime.py` per GPT-5.5 cycle-1 C1-#1: (a) `test_studies_tpe_warmup_floor_constant_value` (value lock); (b) `test_build_pruner_below_floor_returns_nop` (the **exact `floor - 1 = 49` boundary** the spec mandates — stricter than the existing 30-trial test at line 136 which only covers "well below floor"); (c) `test_build_pruner_at_floor_returns_median` (re-asserting `floor = 50` using the constant; complements the existing literal-50 test at line 150). |

**All spec FRs covered.** No deferred phase. Per spec §3 "Phase boundaries (single-phase)" and D-3, the digest-narrative half is routed to [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) — no `phase2_idea.md` is needed for this feature.

## 2) Delivery structure

Single epic (Epic 1), single phase. Story order: 1.1 → 1.2 → 1.3 → 1.4.

### Story-level conventions

- All Python edits land on `feature/study-sub-warmup-guard` (the active branch carrying the spec + preflight changes).
- Backend follows existing `optuna_runtime.py` style: module-level constants near the top after imports, type-annotated, capitalized `SCREAMING_SNAKE_CASE`.
- Frontend follows `create-study-modal.tsx` style: `const NAME: type = value;` declared near `PRESET_VALUES` (lines 91-110); comments immediately above the declaration.
- Story-internal commit hygiene: each story is one commit. Per CLAUDE.md commit-msg hook, use Conventional Commits (`feat(...)`, `chore(...)`, `test(...)`).

### AI Agent Execution Protocol

0. **Load context first**: this plan + the spec already loaded by the pipeline orchestrator.
1. **Read story scope** (Outcome + Modified files + DoD).
2. **Story 1.1 (backend) first** — independent of frontend; can ship and merge a follow-up `chore(optuna): hoist warmup threshold constant` commit if desired.
3. **Story 1.2 (frontend constant)** — purely a declaration + comment; no behavior change yet.
4. **Story 1.3 (warning JSX)** — behavior change; the warning becomes visible in Custom-mode sub-warmup states.
5. **Story 1.4 (vitest cases)** — append 5 cases; existing helpers cover the setup. Verify `pnpm test` passes locally.
6. **Update docs**: this plan's §4 lists `docs/01_architecture/optimization.md` as the single doc update needed.

---

## Epic 1 — Sub-warmup guard for Custom mode

### Story 1.1 — Backend warmup-floor constant hoist + value-lock test

**Outcome:** `backend/app/eval/optuna_runtime.py` exposes a `STUDIES_TPE_WARMUP_FLOOR: int = 50` module-level constant; `build_pruner` references it instead of the inline literal `50`; the test suite asserts the constant value AND continues to pass its existing boundary tests (now refactored to use the constant). Per spec FR-1 + FR-7.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | Story 1.1 modifies existing files only. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/eval/optuna_runtime.py`](../../../../../backend/app/eval/optuna_runtime.py) | (1) Add `STUDIES_TPE_WARMUP_FLOOR: int = 50` near top — after imports + `_OPTUNA_SEARCH_PATH_OPTION` at the existing constants block (around line 32). (2) Update `build_pruner` at line 121 to reference `STUDIES_TPE_WARMUP_FLOOR` instead of literal `50`. |
| [`backend/tests/unit/eval/test_optuna_runtime.py`](../../../../../backend/tests/unit/eval/test_optuna_runtime.py) | (1) Add `STUDIES_TPE_WARMUP_FLOOR` to the existing `from backend.app.eval.optuna_runtime import (...)` block (line 25 area). (2) Append **three** new assertions per spec FR-7: (a) `test_studies_tpe_warmup_floor_constant_value` — `STUDIES_TPE_WARMUP_FLOOR == 50`; (b) `test_build_pruner_below_floor_returns_nop` — `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR - 1})` returns `NopPruner` (the exact `floor - 1 = 49` boundary the spec mandates — note: this is **stricter** than the existing 30-trial test at line 136, which only covers "well below floor"); (c) `test_build_pruner_at_floor_returns_median` — `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR})` returns `MedianPruner` (re-asserting at-floor boundary using the constant; complements the existing literal-50 test at line 150). (3) Optionally refactor `test_build_pruner_threshold_exactly_50_uses_median` (line 150) to use `STUDIES_TPE_WARMUP_FLOOR` in place of the literal — illustrative; functional coverage unchanged. |

**Endpoints** — N/A (no API surface).

**Key interfaces**

```python
# backend/app/eval/optuna_runtime.py — new module-level constant
STUDIES_TPE_WARMUP_FLOOR: int = 50
"""Trial-count floor below which MedianPruner cannot warm up (`NopPruner`
is substituted) AND the wizard's Custom-mode sub-warmup warning fires.
The frontend mirror at ui/src/components/studies/create-study-modal.tsx
carries a `// Values must match` comment per the Enumerated Value Contract
Discipline.
"""
```

```python
# backend/app/eval/optuna_runtime.py — build_pruner change at ~line 121
# BEFORE:
#   if config.get("max_trials", 0) < 50:
#       return NopPruner()
# AFTER:
if config.get("max_trials", 0) < STUDIES_TPE_WARMUP_FLOOR:
    return NopPruner()
```

```python
# backend/tests/unit/eval/test_optuna_runtime.py — three new tests per FR-7

def test_studies_tpe_warmup_floor_constant_value() -> None:
    """FR-7 lock: the warmup floor is 50 (the MedianPruner activation
    threshold the wizard's Custom-mode sub-warmup warning also keys off).
    A change here must be intentional and paired with a frontend
    SUB_WARMUP_FLOOR + warning-copy update.
    """
    assert STUDIES_TPE_WARMUP_FLOOR == 50


def test_build_pruner_below_floor_returns_nop() -> None:
    """FR-7 boundary: max_trials == STUDIES_TPE_WARMUP_FLOOR - 1 (49) → NopPruner.

    Stricter than the existing 30-trial test at line 136 (which only covers
    "well below floor"); this asserts the exact boundary the spec mandates.
    """
    pruner = build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR - 1})
    assert isinstance(pruner, NopPruner)


def test_build_pruner_at_floor_returns_median() -> None:
    """FR-7 boundary: max_trials == STUDIES_TPE_WARMUP_FLOOR (50) → MedianPruner.

    Re-asserts the at-floor boundary using the named constant (complements
    the existing literal-50 test at line 150). If a future edit shifts the
    constant, this test follows it automatically.
    """
    pruner = build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR})
    assert isinstance(pruner, MedianPruner)
```

**Pydantic schemas** — N/A.

**Tasks**
1. Edit `backend/app/eval/optuna_runtime.py`:
   a. After the existing `_OPTUNA_SEARCH_PATH_OPTION` constant (around line 32), add the new `STUDIES_TPE_WARMUP_FLOOR: int = 50` constant with the attribute-style docstring shown above. (This pattern matches the existing `_OPTUNA_SEARCH_PATH_OPTION` declaration at lines 30-31 — same file, same module-level style.)
   b. Update `build_pruner` at line 121 to reference `STUDIES_TPE_WARMUP_FLOOR` instead of the literal `50`.
2. Edit `backend/tests/unit/eval/test_optuna_runtime.py`:
   a. Extend the existing `from backend.app.eval.optuna_runtime import (...)` block (around line 25) to add `STUDIES_TPE_WARMUP_FLOOR`.
   b. Append **three** new tests at the end of the `build_pruner` test group (after line 162's `test_build_pruner_explicit_median_overrides_small_study_safeguard`) per spec FR-7 + GPT-5.5 cycle-1 finding C1-#1: (i) `test_studies_tpe_warmup_floor_constant_value` (value lock), (ii) `test_build_pruner_below_floor_returns_nop` (the `floor - 1 = 49` boundary), (iii) `test_build_pruner_at_floor_returns_median` (re-asserting `floor = 50` using the constant). Exact source in Key interfaces above.
   c. Optionally refactor `test_build_pruner_threshold_exactly_50_uses_median` (line 150) to use `STUDIES_TPE_WARMUP_FLOOR` in place of the literal `50` — illustrative only.
3. Run `make test-unit backend/tests/unit/eval/test_optuna_runtime.py` (or `cd backend && uv run pytest backend/tests/unit/eval/test_optuna_runtime.py -v`). All 12 existing tests in the file plus the 3 new tests must pass — total 15 tests.
4. Run `make lint` and `make typecheck` to confirm the new constant + import survive ruff + mypy.

**Definition of Done (DoD)**
- [ ] `STUDIES_TPE_WARMUP_FLOOR` is defined as a module-level constant in `backend/app/eval/optuna_runtime.py` with the documented docstring.
- [ ] `build_pruner` references the constant (not the literal `50`) at the threshold check.
- [ ] Three new tests pass: `test_studies_tpe_warmup_floor_constant_value`, `test_build_pruner_below_floor_returns_nop` (asserting `floor - 1 = 49` → `NopPruner`), `test_build_pruner_at_floor_returns_median` (asserting `floor = 50` → `MedianPruner`). **All three FR-7 assertions covered → AC-5 fully covered.**
- [ ] All 4 existing `build_pruner` boundary tests (`test_build_pruner_omitted_with_small_max_trials_is_nop`, `test_build_pruner_omitted_with_large_max_trials_is_median`, `test_build_pruner_threshold_exactly_50_uses_median`, `test_build_pruner_explicit_median_overrides_small_study_safeguard`) continue to pass.
- [ ] `make lint` + `make typecheck` green.
- [ ] No remaining inline literal `50` on line 121 of `optuna_runtime.py` (mechanical inspection at PR review per spec D-0c; not a unit-test assertion).
- [ ] Commit message: `chore(optuna): hoist warmup floor literal to STUDIES_TPE_WARMUP_FLOOR constant` (Conventional Commits).

---

### Story 1.2 — Frontend `SUB_WARMUP_FLOOR` constant + cross-side comment

**Outcome:** `ui/src/components/studies/create-study-modal.tsx` exposes a `SUB_WARMUP_FLOOR: 50` constant near the existing preset declarations (lines 91-110), with the discipline-enforced `// Values must match` comment immediately above. The constant is declared but **not yet referenced** — Story 1.3 wires the warning's mount guard to it. Per spec FR-5.

**Why this story is separate from Story 1.3:** Constant + warning sit at very different line ranges in the same file (91-110 vs 1282-1283). Splitting them yields two clean focused diffs that each pass tsc independently and let a reviewer verify each piece in isolation. **However, the two stories ship in a single commit** (or one immediately after the other on the same branch) because the ESLint `no-unused-vars` rule will flag `SUB_WARMUP_FLOOR` as unused if Story 1.2 lands alone. Per GPT-5.5 cycle-1 finding C1-#3, the frontend lint gate is gated on Stories 1.2 + 1.3 both being in place — Story 1.2 has no independent lint-green checkpoint. The story split exists for review-time clarity (a reviewer can `git diff <commit>~..<commit> -- ui/...` and see the two changes side-by-side), not for time-separated merging.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) | Add `SUB_WARMUP_FLOOR` constant after the existing `DEEP_WRITE` declaration (line 110), before the `presetWrite()` function (line 112). Include the `// Values must match` comment per FR-5. |

**Endpoints** — N/A.

**Key interfaces**

```ts
// ui/src/components/studies/create-study-modal.tsx — new constant block
// (insertion point: after line 110 `const DEEP_WRITE: PresetWrite = { max_trials: 1000, time_budget_min: 480 };`,
// before line 112 `function presetWrite(preset: Exclude<PresetValue, 'custom'>): PresetWrite {`)

// chore_study_default_stop_conditions shipped 50 as the MedianPruner activation
// floor; feat_study_sub_warmup_guard piggybacks on the same threshold so the
// wizard's Custom-mode sub-warmup warning and the backend pruning floor stay
// in lockstep. See feature_spec.md FR-5 for the discipline.
// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR
const SUB_WARMUP_FLOOR: number = 50;
```

**Important:** the `// Values must match …` line MUST be the line **immediately preceding** the `const SUB_WARMUP_FLOOR` declaration (no blank lines, no other comments between them). The explanatory paragraph above the `// Values must match` line is fine — but the discipline comment is the one the spec FR-5 calls "the immediately-preceding line," and that's a hard contract.

**UI element inventory**

| Element | Element type | Label / data source | Interaction |
|---|---|---|---|
| `SUB_WARMUP_FLOOR` constant | (declaration, not a visible element) | numeric literal `50` | none |
| `// Values must match …` comment | source comment | discipline source-of-truth pointer | none — read by future implementers + code review |

**State dependency analysis** — none. Story 1.2 adds a top-level module constant; no React state, no props, no hooks involved.

**Tasks**
1. Open `ui/src/components/studies/create-study-modal.tsx`.
2. Insert the explanatory paragraph + `// Values must match` line + `const SUB_WARMUP_FLOOR: number = 50;` block (exact source in Key interfaces above) between the existing `DEEP_WRITE` constant on line 110 and the `presetWrite()` function on line 112. Confirm the `// Values must match …` line is IMMEDIATELY ABOVE the `const` line — zero intervening blank lines or other comments per spec FR-5's "immediately-preceding" clause.
3. Run `pnpm typecheck` to confirm tsc accepts the new declaration.
4. **Do NOT run `pnpm lint` as an independent gate for this story** — the new constant is unused until Story 1.3 lands, and the ESLint `no-unused-vars` rule will flag it. Defer the lint gate to Story 1.3's DoD (which adds the use).

**Definition of Done (DoD)**
- [ ] `SUB_WARMUP_FLOOR: number = 50` constant exists in `create-study-modal.tsx` between lines 110 and 112 (post-edit; actual line numbers will shift by ~6 lines for the explanatory comment + discipline comment + declaration).
- [ ] The `// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR` line is the IMMEDIATELY-PRECEDING line of the `const SUB_WARMUP_FLOOR` declaration — no blank or other-comment lines between them.
- [ ] `pnpm typecheck` green.
- [ ] **Frontend lint gate not run yet** — explicitly deferred to Story 1.3's DoD because `no-unused-vars` will flag the constant until Story 1.3 wires it. Stories 1.2 + 1.3 ship as one commit (or as two consecutive commits squashed at merge time).
- [ ] Commit message: `feat(ui/studies): declare SUB_WARMUP_FLOOR constant for sub-warmup guard` (Conventional Commits). May be folded into Story 1.3's commit if the implementer prefers a single squash.

---

### Story 1.3 — Conditional sub-warmup warning render

**Outcome:** When the operator's create-study modal is at Step 5 with `activePreset === 'custom'` and `watchedMaxTrials` is a finite integer strictly less than `SUB_WARMUP_FLOOR`, an inline amber warning appears between the Stop-condition preset button group and the numeric-inputs grid. The warning's text is the exact copy specified in FR-3, with the `{watchedMaxTrials}` value interpolated. Per spec FR-2 + FR-3.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) | Insert a new conditional `<p data-testid="cs-sub-warmup-warning">` JSX block immediately after the preset button group's closing `</div></div>` (currently line 1282) and before the `<div className="grid gap-3 sm:grid-cols-3">` that opens the numeric-inputs grid (currently line 1283). Render condition: `activePreset === 'custom' && typeof watchedMaxTrials === 'number' && !Number.isNaN(watchedMaxTrials) && Number.isInteger(watchedMaxTrials) && watchedMaxTrials < SUB_WARMUP_FLOOR`. |

**Endpoints** — N/A.

**Key interfaces**

```tsx
// ui/src/components/studies/create-study-modal.tsx
// (insertion point: between line 1282 closing the Stop-condition <div role="group"> block
//  and line 1283 opening the numeric-inputs <div className="grid gap-3 sm:grid-cols-3">)

{activePreset === 'custom' &&
  typeof watchedMaxTrials === 'number' &&
  !Number.isNaN(watchedMaxTrials) &&
  Number.isInteger(watchedMaxTrials) &&
  watchedMaxTrials < SUB_WARMUP_FLOOR && (
    <p
      role="status"
      className="text-sm text-amber-700 dark:text-amber-400"
      data-testid="cs-sub-warmup-warning"
    >
      <strong>
        The optimizer spends its first ~10 trials exploring randomly, and studies below 50
        trials skip RelyLoop's pruning floor.
      </strong>{' '}
      With {watchedMaxTrials} trials this study is unlikely to converge — switch to{' '}
      <strong>Focused (50)</strong> for a quick run or <strong>Standard (200)</strong> for a
      result worth turning into a PR.
    </p>
  )}
```

**UI element inventory**

| Element | Element type | Label / data source | Interaction |
|---|---|---|---|
| `cs-sub-warmup-warning` | `<p role="status">` advisory warning | static text + `{watchedMaxTrials}` interpolation | none (display-only; non-blocking) |
| Bold lead clause | `<strong>` inside the `<p>` | static text | none |
| `Focused (50)` reference | `<strong>` inside the `<p>` | literal "Focused (50)" matching `presetLabel('focused')` at modal line 97 | none (no click handler — the operator clicks the preset button above) |
| `Standard (200)` reference | `<strong>` inside the `<p>` | literal "Standard (200)" matching `presetLabel('standard')` at modal line 99 | none |

**State dependency analysis**

- **State read:** `activePreset` (useMemo at line 269), `watchedMaxTrials` (form.watch at line 267) — both already in scope at the modal function body where the JSX renders.
- **State written:** none. The warning is purely derivative of existing form state.
- **Cross-component impact:** none. The warning is contained inside the create-study modal's Step 5 render block.

**Analogous markup patterns**

The existing inline-warning pattern in the same file at [`create-study-modal.tsx:1107-1115`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1107-L1115) (the `cs-placeholder-warning`):

```tsx
{/* Existing pattern — from create-study-modal.tsx:1107-1115 */}
{placeholderWarning && (
  <p
    className="text-sm text-amber-700 dark:text-amber-400"
    data-testid="cs-placeholder-warning"
  >
    Replace the &lsquo;__placeholder__&rsquo; value(s) before submitting — they
    are starter defaults for params with no inferable type.
  </p>
)}
```

Story 1.3's new warning matches this pattern character-for-character on `className` + `data-testid` shape; adds `role="status"` (the placeholder warning omits it because it's tied to submit-time validation, not advisory). Uses `<strong>` for emphasis where the placeholder warning uses no emphasis.

**Tasks**
1. Open `ui/src/components/studies/create-study-modal.tsx`.
2. Locate the closing `</div></div>` of the Stop-condition preset button group at lines 1281-1282 (post-Story-1.2 line numbers; verify visually).
3. Locate the next sibling element — the opening `<div className="grid gap-3 sm:grid-cols-3">` of the numeric-inputs grid at line 1283.
4. Insert the JSX block from "Key interfaces" above between those two lines.
5. Run `pnpm typecheck` — the JSX must compile against the existing component's types.
6. Run `pnpm lint` — should now resolve any `no-unused-vars` flagged for `SUB_WARMUP_FLOOR` in Story 1.2 (it's now referenced).
7. Local smoke check (optional but recommended): `cd ui && pnpm dev`; open the create-study modal; walk to Step 5; click Focused → edit `max_trials` to `12` → verify the warning appears below the preset group with the expected copy.

**Definition of Done (DoD)**
- [ ] The conditional JSX block exists at the specified location.
- [ ] Render guard is exactly `activePreset === 'custom' && typeof watchedMaxTrials === 'number' && !Number.isNaN(watchedMaxTrials) && Number.isInteger(watchedMaxTrials) && watchedMaxTrials < SUB_WARMUP_FLOOR`.
- [ ] Element has `role="status"`, `className="text-sm text-amber-700 dark:text-amber-400"`, `data-testid="cs-sub-warmup-warning"`.
- [ ] Copy uses three `<strong>` spans on the lead clause, "Focused (50)", "Standard (200)" per FR-3.
- [ ] The two preset labels in the copy match `presetLabel('focused')` and `presetLabel('standard')` character-for-character.
- [ ] `pnpm typecheck` green.
- [ ] `pnpm lint` green (and `no-unused-vars` for `SUB_WARMUP_FLOOR` resolved).
- [ ] Commit message: `feat(ui/studies): inline sub-warmup warning for Custom-mode max_trials < 50` (Conventional Commits).

---

### Story 1.4 — Vitest branch + submit coverage

**Outcome:** Five new test cases appended to [`create-study-modal.stop-conditions.test.tsx`](../../../../../ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx) covering AC-1 / AC-2 / AC-3 / AC-4 / AC-6. The existing `walkToStep5()`, `getPresetButton(name)`, `getMaxTrialsInput()` helpers and the MSW handler at line 138 supply the test infrastructure. Per spec FR-6.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`](../../../../../ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx) | Append a new `describe('sub-warmup warning', ...)` block at the end of the file with 5 `it(...)` test cases. Reuses the existing imports + helpers + MSW server; no new test infra. |

**Endpoints** — N/A (tests, not production code).

**Key interfaces**

```tsx
// ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx
// Append at end of file. Reuses walkToStep5, getPresetButton, getMaxTrialsInput,
// and the existing MSW server.

describe('sub-warmup warning (feat_study_sub_warmup_guard)', () => {
  // Per GPT-5.5 cycle-2 C2-#2: every test installs the file's existing
  // mockBackend() helper. The helper owns the MSW handlers for cluster
  // list / templates / query sets / judgment lists / POST /api/v1/studies
  // that walkToStep5() and the submit path depend on. Without it, the
  // wizard's Step-1 cluster picker can't populate and the test deadlocks
  // before reaching Step 5. Only AC-6 uses the returned `postBodies`;
  // AC-1..AC-4 still need the handlers installed, they just don't read
  // the captured bodies.

  it('AC-1: shows on Custom + sub-warmup max_trials with interpolation and preset labels', async () => {
    mockBackend();
    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));
    await walkToStep5();
    fireEvent.click(getPresetButton(/Focused/));
    fireEvent.change(getMaxTrialsInput(), { target: { value: '12' } });
    const warning = await screen.findByTestId('cs-sub-warmup-warning');
    expect(warning).toBeInTheDocument();
    expect(warning).toHaveTextContent(/12 trials/);
    expect(warning).toHaveTextContent(/Focused \(50\)/);
    expect(warning).toHaveTextContent(/Standard \(200\)/);
  });

  it('AC-2: hides at the SUB_WARMUP_FLOOR boundary (max_trials===50 in Custom mode)', async () => {
    mockBackend();
    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));
    await walkToStep5();
    // Path to Custom + 50: click Standard (writes 200), then edit max_trials to 50.
    // The (50, '') tuple matches no preset write, so activePreset becomes 'custom'.
    fireEvent.click(getPresetButton(/Standard/));
    fireEvent.change(getMaxTrialsInput(), { target: { value: '50' } });
    await waitFor(() => {
      expect(screen.queryByTestId('cs-sub-warmup-warning')).toBeNull();
    });
  });

  it('AC-3: hides when a non-Custom preset is active regardless of max_trials', async () => {
    mockBackend();
    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));
    await walkToStep5();
    fireEvent.click(getPresetButton(/Focused/));
    // Focused preset write is (50, ''); activePreset === 'focused'; warning suppressed.
    await waitFor(() => {
      expect(screen.queryByTestId('cs-sub-warmup-warning')).toBeNull();
    });
  });

  it('AC-4: hides on transient empty / NaN / non-integer max_trials', async () => {
    mockBackend();
    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));
    await walkToStep5();
    fireEvent.click(getPresetButton(/Standard/));
    // Empty
    fireEvent.change(getMaxTrialsInput(), { target: { value: '' } });
    await waitFor(() => {
      expect(screen.queryByTestId('cs-sub-warmup-warning')).toBeNull();
    });
    // Non-integer (49.99)
    fireEvent.change(getMaxTrialsInput(), { target: { value: '49.99' } });
    await waitFor(() => {
      expect(screen.queryByTestId('cs-sub-warmup-warning')).toBeNull();
    });
  });

  it('AC-6: submit fires with sub-warmup max_trials when the warning is visible (non-blocking)', async () => {
    // Reuse the existing mockBackend() helper — it exposes a `postBodies`
    // array that captures every POST /api/v1/studies request body via
    // `await request.json()` (handler at file line 138 returns
    // { id: 'st1', name: 'demo', status: 'queued' }). Do NOT override the
    // handler — that would risk drifting the response shape away from
    // the file's existing fixture.
    const { postBodies } = mockBackend();

    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));
    await walkToStep5();
    fireEvent.click(getPresetButton(/Focused/));
    fireEvent.change(getMaxTrialsInput(), { target: { value: '12' } });
    // Confirm warning is visible (binds this test to the warning's render contract)
    expect(await screen.findByTestId('cs-sub-warmup-warning')).toBeInTheDocument();
    // Submit query matches the existing pattern at file line 364
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));
    await waitFor(() => {
      expect(postBodies.length).toBeGreaterThanOrEqual(1);
      expect(postBodies[0]?.config?.max_trials).toBe(12);
    });
  });
});
```

**Pattern note** (per GPT-5.5 cycle-2 C2-#2 + C2-#3): every new test calls `mockBackend()` at the top — the helper is what installs the MSW handlers `walkToStep5()` depends on, and without it the wizard's Step-1 cluster picker won't populate. AC-1 through AC-4 don't read the returned `postBodies` (they only need the handlers installed); AC-6 destructures `{ postBodies }` to verify the submit payload. The implementer may consolidate the `mockBackend()` calls into a single `beforeEach(() => { mockBackend(); })` at the describe block's top **only if** the existing test file's existing tests follow that pattern; if the existing tests call `mockBackend()` per-test (the more common Vitest convention), match that. **Empty `afterEach` hook removed** — the file-level afterEach handles cleanup.

**Note for the implementer:** the snippet above assumes `mockBackend()` is the per-test setup helper already exported at the top of the file. If the file instead uses module-level MSW setup (no `mockBackend()` factory), capture `postBodies` via the file's existing pattern — read `screen.getByRole(...)` / `fireEvent.click(...)` from the file's existing submit-test at around line 363-364 (the `Submit with Standard active` test) and follow its exact submit-flow shape. The two anchors are: (1) reuse whatever helper the file's existing submit tests use to drive submit; (2) read the captured request body via the file's existing `postBodies`-equivalent array, not by overriding `server.use(...)`.

**UI element inventory** — N/A (test file, not production UI).

**State dependency analysis** — N/A (tests, not refactor).

**Tasks**
1. Open `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`.
2. Verify the file currently has the `walkToStep5()`, `getPresetButton(name)`, `getMaxTrialsInput()` helpers (existing per the file's line 50-ish helper block) and the MSW `server` import from `../../setup` (line 9).
3. Append the new `describe('sub-warmup warning', ...)` block at the end of the file with the 5 `it(...)` cases shown in Key interfaces above.
4. Run `cd ui && pnpm test create-study-modal.stop-conditions` (or `pnpm test:watch -- create-study-modal.stop-conditions` for iteration). All 5 new tests must pass. **All existing tests in the file must continue to pass** (Story 1.3's JSX insertion does NOT change any existing behavior; the existing tests should be unaffected).
5. Run `pnpm typecheck` to confirm the new test code's TypeScript is sound.

**Definition of Done (DoD)**
- [ ] Five new `it(...)` test cases exist in the appended `describe('sub-warmup warning', ...)` block.
- [ ] Each test maps to one AC: AC-1 (show), AC-2 (boundary), AC-3 (non-Custom), AC-4 (empty/non-integer), AC-6 (submit non-blocking).
- [ ] `pnpm test create-study-modal.stop-conditions` runs cleanly — all new tests pass AND all pre-existing tests in the file continue to pass.
- [ ] `pnpm typecheck` green.
- [ ] `pnpm lint` green.
- [ ] **AC-1, AC-2, AC-3, AC-4, AC-6 all covered by these vitest cases.** AC-5 is covered by Story 1.1's backend test.
- [ ] Commit message: `test(ui/studies): vitest coverage for sub-warmup warning branches + submit non-blocking` (Conventional Commits).

---

## UI Guidance

### Reference: current component structure

[`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) — **1,462 lines** as of the feature branch HEAD.

| Section | Approx. line range | Story 1.2 / 1.3 impact |
|---|---|---|
| Imports + top-level constants (`PRESET_VALUES`, `FOCUSED_WRITE`, `STANDARD_WRITE`, `DEEP_WRITE`) | 1-110 | **Story 1.2 inserts** `SUB_WARMUP_FLOOR = 50` after line 110. |
| Form type defs (`FormValues`, `STEP_TITLES`, `PrefillValues`) | 123-202 | unchanged. |
| `CreateStudyModal` function body — form init, `activePreset` useMemo, handlers | 216-650+ | unchanged (read-only consumers of `watchedMaxTrials` / `activePreset` that Story 1.3 will reference inside the JSX guard). |
| Step 5 JSX (Objective + config) | ~1140-1400 | **Story 1.3 inserts** the conditional warning between lines 1282 (end of Stop-condition preset group) and 1283 (start of numeric-inputs grid). |
| Numeric-inputs grid (`max_trials`/`time_budget_min`/`parallelism`) | 1283-1318 | unchanged. |

### Analogous markup patterns

Existing inline-warning pattern at [`create-study-modal.tsx:1107-1115`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1107-L1115) (the `cs-placeholder-warning`):

```tsx
{/* Pattern source — create-study-modal.tsx:1107-1115 */}
{placeholderWarning && (
  <p
    className="text-sm text-amber-700 dark:text-amber-400"
    data-testid="cs-placeholder-warning"
  >
    Replace the &lsquo;__placeholder__&rsquo; value(s) before submitting — they
    are starter defaults for params with no inferable type.
  </p>
)}
```

The Story 1.3 warning matches this pattern's CSS classes + `<p>` shape; differs by (a) `role="status"` for advisory semantics, (b) `<strong>` spans for emphasis, (c) `{watchedMaxTrials}` interpolation. See Story 1.3's "Key interfaces" for the full JSX.

### Layout and structure

- The warning sits in the natural vertical flow of Step 5: preset button group (above) → warning (new) → numeric inputs grid (below). No flex/grid reflow; the `<p>` is a block element occupying full width.
- Visual hierarchy: secondary advisory (amber `text-amber-700 dark:text-amber-400`) — subordinate to both the preset buttons and the numeric inputs in eye-priority.
- Responsive behavior: text wraps naturally; no breakpoint-specific layout changes needed.

### Confirmation/modal dialog pattern

N/A — this feature adds no dialog. The warning is inline.

### Visual consistency table

| New element | CSS class / pattern | Pattern source |
|---|---|---|
| `<p role="status" className="text-sm text-amber-700 dark:text-amber-400" data-testid="cs-sub-warmup-warning">` | `text-sm text-amber-700 dark:text-amber-400` + `data-testid="cs-..."` | [`create-study-modal.tsx:1107-1115`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1107-L1115) (`cs-placeholder-warning`) |
| `<strong>` spans | inline emphasis (no class) | standard HTML semantics; renders as `font-weight: bold` via default browser/Tailwind reset stylesheet |
| `{watchedMaxTrials}` interpolation | JSX expression | React standard |

### Component composition

The warning is **inline** in `create-study-modal.tsx` — NOT extracted into a separate component. Per spec §4 Anti-pattern "Do not add a new amber-warning component," a one-off render does not warrant extraction. The placeholder-warning pattern (lines 1107-1115) sets the precedent of inline-amber-`<p>`-with-data-testid.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Click `Focused` preset button | `form.setValue('max_trials', 50)` (existing handler at line 292); `activePreset` re-derives to `'focused'`; warning hides | none |
| Edit `max_trials` from 50 to 12 in Custom mode | `watchedMaxTrials` updates via `form.watch`; `activePreset` re-derives to `'custom'`; warning becomes visible | none |
| Click `Standard` preset button (from any other state) | `form.setValue('max_trials', 200)`; `activePreset === 'standard'`; warning hides | none |
| Click submit while warning is visible | Existing `useCreateStudy()` mutation fires with the operator's chosen `max_trials` value; warning's presence does not gate submit | `POST /api/v1/studies` with `config.max_trials: 12` (or whatever the operator typed) |

### Handler function patterns

No new handlers. Story 1.3's warning is purely a derived render; its mount/unmount is driven by `useMemo`-derived `activePreset` and `form.watch`-derived `watchedMaxTrials`, both of which are already wired in the modal at lines 267-282.

### Information architecture placement

- The warning lives **inside the create-study modal**, on **Step 5 (Objective + config)**.
- Within Step 5, the warning sits between the existing "Stop condition" preset button group and the numeric-inputs grid (max_trials / time_budget_min / parallelism).
- Discoverability: the operator does not navigate to find it; it appears when their inputs put them in the failure region (`activePreset === 'custom'` + `max_trials < 50`). No new navigation hierarchy.

### Tooltips and contextual help

Per spec §11: no tooltip on the warning itself (the warning copy IS the explanation). The existing `<InfoTooltip glossaryKey="study.preset">` at modal line 1262 continues to be the preset-discovery tooltip; no changes to it. No new glossary key per D-0a / D-0c-i — FR-4 was dropped, and the spec explicitly routes any future tooltip work to a follow-up story.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** Story 1.3 inserts a single JSX block; no existing markup is removed or restructured.

### Client-side persistence

N/A — no `localStorage` / `sessionStorage` / React-state changes outside the modal's existing form.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: [`backend/tests/unit/eval/test_optuna_runtime.py`](../../../../../backend/tests/unit/eval/test_optuna_runtime.py) (existing file at 7.3K, 12 tests)
- Scope: `STUDIES_TPE_WARMUP_FLOOR` value lock + the exact `floor - 1` and `floor` boundary assertions FR-7 mandates (per GPT-5.5 cycle-1 C1-#1) + optional refactor of an existing literal-50 test to use the constant.
- Tasks:
  - [ ] Append `test_studies_tpe_warmup_floor_constant_value` — asserts `STUDIES_TPE_WARMUP_FLOOR == 50` (1 new test)
  - [ ] Append `test_build_pruner_below_floor_returns_nop` — asserts `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR - 1})` returns `NopPruner` at the exact `49` boundary (1 new test)
  - [ ] Append `test_build_pruner_at_floor_returns_median` — asserts `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR})` returns `MedianPruner` at the exact `50` boundary using the constant (1 new test)
  - [ ] Optionally refactor existing `test_build_pruner_threshold_exactly_50_uses_median` at line 150 to use `STUDIES_TPE_WARMUP_FLOOR` in place of the literal — illustrative, no behavior change
- DoD:
  - [ ] `STUDIES_TPE_WARMUP_FLOOR == 50` asserted (FR-7)
  - [ ] The two `floor - 1 = 49` and `floor = 50` boundary assertions pass using the constant (FR-7 stricter boundary, per C1-#1)
  - [ ] All 12 existing tests in `test_optuna_runtime.py` continue to pass
  - [ ] **Total: 15 tests in the file post-story** (12 existing + 3 new)

### 3.2 Integration tests
- **None required.** FR-1's hoist is semantic-preserving; existing integration tests covering `build_pruner` (none directly target it from the integration layer — it's a pure-Python helper) pass unchanged.

### 3.3 Contract tests
- **None required.** Spec §7.5 explicitly says no new error codes. No new endpoint surface; no contract test required.

### 3.4 E2E tests
- **None required.** Spec §14 explicitly defers verification of the warning's presence to vitest (where the existing modal-test scaffold already exercises Step 5). The existing Step 5 E2E flow at `ui/tests/e2e/studies.spec.ts` (or equivalent — verify path at implementation time if a Step 5 E2E exists) should continue to pass unchanged because the warning is a non-blocking advisory `<p>` that does not change the submit path.

### 3.5 Vitest / component tests
- Location: [`ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`](../../../../../ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx) (existing file at 383 lines)
- Scope: 5 new branch + submit-coverage cases per FR-6
- Tasks:
  - [ ] Append `describe('sub-warmup warning', ...)` block with 5 `it(...)` cases (Story 1.4)
- DoD:
  - [ ] All 5 new vitest cases pass: AC-1 (show), AC-2 (boundary), AC-3 (non-Custom), AC-4 (empty/non-integer), AC-6 (submit non-blocking)
  - [ ] All pre-existing tests in the file continue to pass

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/eval/test_optuna_runtime.py` | `build_pruner` boundary literals (`30`, `50`) | 4 tests at lines 136, 142, 150, 156 | Refactor `test_build_pruner_threshold_exactly_50_uses_median` (line 150) to use `STUDIES_TPE_WARMUP_FLOOR`; optionally refactor `test_build_pruner_omitted_with_small_max_trials_is_nop` (line 136) to use `STUDIES_TPE_WARMUP_FLOOR - 20`. The other two (`...omitted_with_large_max_trials_is_median` at 142 and `...explicit_median_overrides_small_study_safeguard` at 156) use values not tied to the floor — no change. **All four tests continue to assert the same behaviors post-hoist.** |
| `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` | `walkToStep5`, preset clicks, `getMaxTrialsInput` | existing helpers at ~line 50 + tests throughout file | No changes to existing tests. Story 1.4 appends a new `describe` block. **Pre-existing tests must continue to pass** (Story 1.3's JSX insertion is additive; it doesn't change existing behavior). |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Main create-study flow | 1 file | **No changes needed.** The warning is conditional on `activePreset === 'custom' && max_trials < 50` — the main flow's happy paths use Focused/Standard/Deep presets that all satisfy `max_trials >= 50`, so the warning never renders in those tests. If the file has a Custom-mode test that happens to use `max_trials < 50`, it will now also render the warning (no behavior change; the warning is non-blocking). Verify by running the test file post-Story-1.3. |

### 3.7 Migration verification
- **N/A.** No migration in this plan. Alembic head stays at `0020_studies_baseline_trial`.

### 3.8 CI gates

- [ ] `make test-unit` (covers Story 1.1)
- [ ] `cd ui && pnpm test` (covers Story 1.4 + ensures Story 1.3 didn't break existing tests)
- [ ] `make lint` (covers Story 1.1's ruff)
- [ ] `cd ui && pnpm lint` (covers Story 1.2 + 1.3's ESLint)
- [ ] `cd ui && pnpm typecheck` (covers Story 1.2 + 1.3 + 1.4's tsc)
- [ ] `cd ui && pnpm build` (catches SSR + production-build issues)

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] **`state.md`** — Update at finalization time (post-PR-merge): add to "Last 5 merges" + update "Active feature" line to "none in flight".
- [ ] **`architecture.md`** — No change required (no new layer, no new topical doc).
- [ ] **`CLAUDE.md`** — No change required (no new convention; the Enumerated Value Contract Discipline already covers the cross-side constant pattern in §"Common Pitfalls" and §"Frontend Conventions").

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] **`docs/01_architecture/optimization.md`** — Update §"Optuna configuration" table row for "Pruner" to reference `STUDIES_TPE_WARMUP_FLOOR` instead of the inline `<50`. One-line callout that the constant is shared with the wizard's Custom-mode sub-warmup warning. **Story 1.1's commit OR a separate final-doc-update commit.**
- [ ] **`docs/01_architecture/ui-architecture.md`** — Optional (per spec §15): add a one-line note about the `// Values must match backend/...` pattern for numeric thresholds (not just enum allowlists). Skip if `ui-architecture.md` doesn't already have a "Form dropdown primitive" or equivalent section to anchor to.

### 4.2 Product docs (`docs/02_product`) — none.
### 4.3 Runbooks (`docs/03_runbooks`) — none.
### 4.4 Security docs (`docs/04_security`) — none.
### 4.5 Quality docs (`docs/05_quality`) — none.

### Documentation DoD

- [ ] `docs/01_architecture/optimization.md` references `STUDIES_TPE_WARMUP_FLOOR` (replacing the inline `<50` mention).
- [ ] `state.md` updated at finalization (post-merge) per the `impl-execute` Step 7 protocol.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Hoist a magic-number literal (`50`) to a named constant. That's the entire refactor scope.

### 5.2 Planned refactor tasks
- [ ] Story 1.1 task 1 — hoist `50` to `STUDIES_TPE_WARMUP_FLOOR` in `optuna_runtime.py`.
- [ ] Story 1.1 task 2c — refactor `test_build_pruner_threshold_exactly_50_uses_median` to use the constant.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven: all 4 existing `build_pruner` boundary tests continue to pass with the constant substitution.
- [ ] No expansion of product scope: the hoist does not change `build_pruner` semantics.
- [ ] Linted/typechecked: `make lint` + `make typecheck` green.
- [ ] No dead-code removal needed.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| [`chore_study_default_stop_conditions`](../../../implemented_features/2026_05_23_chore_study_default_stop_conditions/) (shipped 2026-05-23) | Story 1.3 — preset button group + `activePreset` derivation | **Shipped** — already on main | None — prerequisite already in tree. |
| MVP1 study lifecycle (shipped) | Story 1.1 — `build_pruner` infrastructure | **Shipped** — already on main | None. |
| Backend test scaffold at `test_optuna_runtime.py` (existing) | Story 1.1 — append-only | **Exists** (7.3K, 12 tests) | None. |
| Frontend test scaffold at `create-study-modal.stop-conditions.test.tsx` (existing) | Story 1.4 — append-only | **Exists** (383 lines with `walkToStep5` + MSW handlers) | None. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Line numbers in the modal shift between feature-branch HEAD and PR-merge time | Low | Low | The plan cites approximate line ranges (e.g., "between 1282 and 1283") and structural landmarks ("after the Stop-condition preset group's `</div></div>`, before the numeric-inputs grid's `<div className="grid">`). Implementation finds the landmarks, not the exact line. |
| Custom-mode tests in the unrelated `create-study-modal.test.tsx` happen to use `max_trials < 50` and now render the warning | Low | Low | The warning is non-blocking — it does not change form values or submit behavior. Worst case is a brand-new DOM node that the existing test doesn't query; no assertion would fail unless a test asserted the **absence** of any element matching `data-testid="cs-..."` (unlikely; `cs-placeholder-warning` already exists). Verify by running the test file post-Story-1.3. |
| `no-unused-vars` ESLint rule trips on Story 1.2 because Story 1.3 hasn't landed yet | Medium | Low | Either (a) merge Story 1.2 + 1.3 into one commit (most likely outcome), or (b) the project's ESLint config tolerates an unused top-level constant for one commit before the use lands. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Operator types `max_trials = 12`, the warning renders, operator submits | Sub-warmup Custom-mode submit | Submit proceeds; `POST /api/v1/studies` request body has `config.max_trials: 12`; server's existing `_require_one_stop_condition` validator at `schemas.py:629` accepts (12 satisfies "at least one of max_trials/time_budget_min"); study runs but barely engages TPE. | No automated recovery — the operator's choice was informed. The digest narrative's "narrow"/"widen" framing may misattribute the result; closing that gap is `feat_study_convergence_indicator`'s scope. |
| Operator types `max_trials = 49.99` (decimal) | Transient typing state | `Number.isInteger(49.99) === false` → warning suppressed. On submit, Pydantic's `int | None` coercion at `schemas.py:604` rejects with 422 VALIDATION_ERROR. | Operator corrects to an integer. The wizard's existing client-side validation (around modal lines 669-670) may also catch this before submit. |
| `STUDIES_TPE_WARMUP_FLOOR` and `SUB_WARMUP_FLOOR` drift to different values | Future edit changes only one side | Story 1.1's `test_studies_tpe_warmup_floor_constant_value` asserts backend value; the `// Values must match` comment + code-review attention catch the frontend. If both slip past, the warning's mount condition references a different threshold than the MedianPruner activation threshold → confusing UX but not broken. | Restore parity in a follow-up PR. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1 (backend)** — Independent. Can ship as a separate commit/PR if desired (mechanical refactor with backward-compatible tests).
2. **Story 1.2 (frontend constant)** — Inserts the constant. May produce a transient `no-unused-vars` ESLint warning until Story 1.3 lands.
3. **Story 1.3 (frontend warning)** — Wires the constant into the JSX render guard. Resolves any 1.2 lint warning.
4. **Story 1.4 (vitest)** — Asserts the warning's behavior. Requires Stories 1.2 + 1.3 in place to pass.

### Parallelization opportunities

- Stories 1.1 (backend) and 1.2 (frontend constant) can be implemented in parallel — they touch separate files with no dependency.
- Stories 1.2 + 1.3 are typically one PR's worth of work; commit-level separation is for review clarity, not for time-parallel development.

---

## 8) Rollout and cutover plan

- **Rollout stages:** N/A. Single-stage merge to `main` → staging (when staging exists; MVP1 has no remote staging — local-only).
- **Feature flag strategy:** None. The warning is a conditional render on existing form state — no flag warranted for a one-`<p>` change.
- **Migration/cutover steps:** None.
- **Reconciliation/repair strategy:** N/A.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Backend warmup-floor constant hoist + value-lock test
- [ ] Story 1.2 — Frontend `SUB_WARMUP_FLOOR` constant + cross-side comment
- [ ] Story 1.3 — Conditional sub-warmup warning render
- [ ] Story 1.4 — Vitest branch + submit coverage
- [ ] Update `docs/01_architecture/optimization.md` to reference `STUDIES_TPE_WARMUP_FLOOR`

### Blocked items

- _(none)_

### Done this sprint

- _(none — pending execution)_

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match the story's `New files` / `Modified files` tables.
- [ ] Endpoint contract — N/A (no endpoints in this plan).
- [ ] Key interfaces — implemented with the exact signatures shown.
- [ ] Required tests added/updated:
  - Story 1.1 → `backend/tests/unit/eval/test_optuna_runtime.py` (+3 new tests per FR-7 / C1-#1: value lock + `floor - 1` boundary + `floor` boundary; optional refactor of existing literal-50 test).
  - Story 1.4 → `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` (+5 new test cases).
- [ ] Commands executed and passed:
  - Story 1.1: `make test-unit` (or `cd backend && uv run pytest backend/tests/unit/eval/test_optuna_runtime.py -v`), `make lint`, `make typecheck`.
  - Stories 1.2 + 1.3: `cd ui && pnpm typecheck && pnpm lint`.
  - Story 1.4: `cd ui && pnpm test create-study-modal.stop-conditions && pnpm typecheck`.
- [ ] Migration round-trip — N/A.
- [ ] Related docs updated (`docs/01_architecture/optimization.md` — see §4.1).

---

## 11) Plan consistency review

### Spec ↔ plan endpoint count

- Spec §8.1: **0 endpoints** added or modified.
- Plan stories: **0 endpoints** added or modified.
- **Match.** ✓

### Spec ↔ plan error code coverage

- Spec §7.5: **0 new error codes.**
- Plan: **0 new error codes.**
- **Match.** ✓

### Spec ↔ plan FR coverage

| FR | Plan coverage | Stories |
|---|---|---|
| FR-1 | ✓ | Story 1.1 |
| FR-2 | ✓ | Story 1.3 |
| FR-3 | ✓ | Story 1.3 |
| FR-4 | ✗ — dropped per spec D-0a | (no story) |
| FR-5 | ✓ | Story 1.2 |
| FR-6 | ✓ | Story 1.4 |
| FR-7 | ✓ | Story 1.1 |

**All non-dropped FRs covered.** ✓

### Story internal consistency

- Story 1.1: 0 new files, 2 modified files (both existing); endpoint table N/A; key interfaces specified. ✓
- Story 1.2: 0 new files, 1 modified file; no endpoint; no state dependency. ✓
- Story 1.3: 0 new files, 1 modified file; no endpoint; state dependencies declared (read-only on existing `activePreset` + `watchedMaxTrials`). ✓
- Story 1.4: 0 new files, 1 modified file (existing test file); no endpoint. ✓
- **No new file ownership conflicts** — all 4 stories modify distinct files (1 backend code + 1 backend test + 1 frontend code + 1 frontend test). Story 1.2 and 1.3 modify the same frontend code file but at non-overlapping line ranges (lines 110 vs 1282-1283).

### Test file count and assignment

- Backend test file `test_optuna_runtime.py` → Story 1.1 DoD ✓
- Frontend test file `create-study-modal.stop-conditions.test.tsx` → Story 1.4 DoD ✓
- **No orphaned test files.**

### Gate arithmetic

- Epic 1 has 4 stories. Gate: all 4 stories complete + docs updated. ✓

### Open questions resolved

- Spec §19: **0 open questions remain.** All 4 idea-stage open questions were resolved as D-1 through D-4 in the spec's decision log. Cycle-1/2/3 GPT-5.5 findings (D-0, D-0b, D-0c) all accepted.
- **All clear.** ✓

### Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| Alembic head is `0020_studies_baseline_trial` | `ls migrations/versions/ \| sort \| tail -3` | Verified |
| `backend/app/eval/optuna_runtime.py` has constants block at top around line 32 | Read file lines 1-90 | Verified |
| `build_pruner` references inline `50` at line 121 | Read file lines 116-156 | Verified |
| `backend/tests/unit/eval/test_optuna_runtime.py` exists at 7.3K with 12 tests | `wc -l` + grep | Verified — existing tests at lines 136 (`30 → NopPruner` "well below floor") + 150 (`50 → MedianPruner` literal-50 at-floor) **complement** but do NOT satisfy FR-7's stricter `floor - 1 = 49` boundary requirement. Story 1.1 adds 3 new tests per C1-#1 to cover the exact boundaries using the named constant. |
| `ui/src/components/studies/create-study-modal.tsx` line 1462 total | `wc -l` | Verified |
| `PRESET_VALUES` + 3 write constants at lines 91-110 | Read file lines 80-160 | Verified |
| `activePreset` useMemo at line 269 | grep + read | Verified |
| `watchedMaxTrials` at line 267 | grep | Verified |
| Stop-condition preset button group at lines 1257-1282 | Read file lines 1253-1318 | Verified |
| Numeric-inputs grid starts at line 1283 | Read file lines 1283-1318 | Verified |
| Existing inline-warning pattern `cs-placeholder-warning` at lines 1107-1115 | Read file lines 1075-1124 | Verified — matches the `text-amber-700 dark:text-amber-400` + `data-testid="cs-..."` pattern Story 1.3 reuses |
| Frontend test scaffold has `walkToStep5`/`getPresetButton`/`getMaxTrialsInput` helpers + MSW handler at line 138 | Read file lines 1-50, 138 | Verified |

### Infrastructure path verification

- Migration directory: `migrations/versions/` (verified by `ls`). **N/A for this plan** — no migration.
- Router registration: **N/A** — no router added.
- Test directories: `backend/tests/unit/eval/` ✓ exists. `ui/src/__tests__/components/studies/` ✓ exists.

### Frontend data plumbing verification

- Story 1.3's JSX guard reads `activePreset` and `watchedMaxTrials`. Both are derived inside the same `CreateStudyModal` function body at lines 267-282 — directly in scope at the Step 5 render block where the new JSX inserts. **No prop plumbing required.**

### Persistence scope consistency

- N/A — no `localStorage` / `sessionStorage` use in this plan.

### Enumerated value contract audit

- This plan adds no `<select>`, filter dropdown, status badge, or wire-value enum.
- The single shared numeric constant (`50`) is grounded backend-canonical (`STUDIES_TPE_WARMUP_FLOOR`) and mirrored frontend-side (`SUB_WARMUP_FLOOR`) with the discipline-required `// Values must match backend/...` comment per FR-5. Story 1.2 specifies the comment shape verbatim.
- **No drift surface.** ✓

### Audit-event coverage audit (MVP2+)

- The plan adds **no state-mutating endpoint or service function.** Story 1.1 is a constant hoist (no behavior change). Stories 1.2-1.4 are frontend / test changes. The eventual `POST /api/v1/studies` request that a sub-warmup study triggers is unchanged — its audit emission (when MVP2's `audit_log` lands) belongs to a separate spec, not this one.
- **No audit-event matrix required for this plan.** ✓

---

## 12) Definition of plan done

- [x] Every FR (FR-1, FR-2, FR-3, FR-5, FR-6, FR-7 — FR-4 dropped) is mapped to a story.
- [x] Every story includes New files (none), Modified files, Endpoints (N/A), Key interfaces, Tasks, DoD.
- [x] Test layers explicitly scoped: backend pytest unit (Story 1.1) + vitest (Story 1.4). Integration, contract, E2E all justified as N/A.
- [x] Documentation updates planned and owned: `docs/01_architecture/optimization.md` (required); `docs/01_architecture/ui-architecture.md` (optional).
- [x] Lean refactor scope explicit: hoist literal `50` → named constant; refactor 1-2 existing tests to use it.
- [x] Phase/epic gates measurable: 4 stories, each with verifiable DoD assertions.
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.

---

## Verification ledger (Pass 1 + Pass 2 — Opus internal)

| Claim | Verified by | Status |
|---|---|---|
| Alembic head `0020_studies_baseline_trial` | `ls migrations/versions/` | Verified |
| `optuna_runtime.py` line 121 has inline `50` | Read file | Verified — to be hoisted in Story 1.1 |
| `optuna_runtime.py` has a clean constants-block insertion point around line 32 | Read file header | Verified |
| `test_optuna_runtime.py` exists with 12 tests including 4 `build_pruner` boundary tests at lines 136-162 | `grep "def test"` + read | Verified — Story 1.1 appends **3 new tests per FR-7 / C1-#1** (constant value lock + `floor - 1 = 49` NopPruner boundary + `floor = 50` MedianPruner boundary using the constant) + optionally refactors the existing literal-50 test at line 150. Total post-story: 15 tests. |
| `create-study-modal.tsx` is 1462 lines | `wc -l` | Verified |
| Preset constants block at lines 91-110 (Story 1.2 insertion site) | Read file | Verified |
| `activePreset` useMemo at line 269, `watchedMaxTrials` at line 267 | Read file lines 260-285 | Verified — both in scope at Step 5 render |
| Stop-condition preset group ends at line 1282; numeric inputs grid starts at line 1283 (Story 1.3 insertion site) | Read file lines 1253-1320 | Verified |
| Existing inline-warning pattern `cs-placeholder-warning` at lines 1107-1115 (analogous markup source) | Read file | Verified — same `className` + `data-testid` shape |
| `create-study-modal.stop-conditions.test.tsx` exists with 383 lines, `walkToStep5`/`getPresetButton`/`getMaxTrialsInput` helpers, MSW `server` import, `http.post(API_BASE/api/v1/studies)` handler at line 138 | `wc -l` + grep + read | Verified — Story 1.4 appends 5 cases reusing all of this |
| Spec §17 traceability matrix → plan §1 traceability — exact 1:1 mapping | Both read | Verified |
| Spec §8 endpoint count = 0; plan endpoint count = 0 | Both read | Verified |
| Spec §7.5 error codes = 0; plan error codes = 0 | Both read | Verified |
| Spec §19 open questions = 0 (all resolved D-0/D-0b/D-0c/D-1/D-2/D-3/D-4/D-5/D-6) | Spec read | Verified |
| FR-4 dropped per spec D-0a — no plan story | Cross-check spec ↔ plan §1 | Verified — FR-4 row marked "Dropped, no story" |
| `STUDIES_TPE_WARMUP_FLOOR` ↔ `SUB_WARMUP_FLOOR` parity enforced by (a) `// Values must match` comment, (b) Story 1.1's value-lock test, (c) PR review (small diff, mechanically inspectable) | Cross-check FR-1 + FR-5 + FR-7 | Verified |
| MVP2 audit_log activation status: not yet active; this plan adds no state-mutating endpoint | Cross-check CLAUDE.md + spec §6 | Verified |
| CLAUDE.md Absolute Rules walked: #1 (feature branch) ✓, #2 (secrets) N/A, #3 (LLM) N/A, #4 (adapter) N/A, #5 (migration) N/A, #6 (healthz) N/A, #7 (conv commits) ✓ planned, #8 (model names) N/A, #9 (`/impl-execute`) ✓ planned, #10 (no secret log) N/A, #11 (healthz 200ms) N/A | Walk | Verified |
