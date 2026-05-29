# Feature Specification — Study Budget Sub-Warmup Guard

**Date:** 2026-05-29
**Status:** Approved (Opus + GPT-5.5 cross-model review converged at cycle 3 — 6 cycle-1 + 3 cycle-2 + 4 cycle-3 = **13 findings, all accepted**; 0 rejected with cited counter-evidence)
**Owners:** RelyLoop maintainers (eric.starr@soundminds.ai)
**Related docs:**
- [`idea.md`](./idea.md) — preflight-refreshed source brief (4 open questions, 3 with locked recommendations)
- [`docs/00_overview/implemented_features/2026_05_23_chore_study_default_stop_conditions/feature_spec.md`](../../../implemented_features/2026_05_23_chore_study_default_stop_conditions/feature_spec.md) — prerequisite that shipped the Focused/Standard/Deep/Custom preset surface this guard extends
- [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) — TPE warmup + MedianPruner activation semantics
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md) — Enumerated Value Contract Discipline (backend-grounded frontend constants)
- [`feature_templates/feature-spec-template.md`](../../feature_templates/feature-spec-template.md)

---

## 1) Purpose

The create-study wizard ships pre-2026-05-23 with no budget guidance and operators picked tiny numbers (the dogfood trace found 6 of 7 studies running 12–15 trials — well under the ~10-trial TPE warmup, so the Bayesian loop barely engaged). [`chore_study_default_stop_conditions`](../../../implemented_features/2026_05_23_chore_study_default_stop_conditions/feature_spec.md) closed the default path with Focused (50) / Standard (200) / Deep (1000) presets and a `max_trials=200` pre-fill. **The Custom escape hatch remains open** — an operator who clicks Custom (or whose values drift off any preset) can still type any `max_trials ≥ 1`, with no on-screen signal that values below 50 produce a study that won't converge.

- **Problem:** No warning when a Custom-mode `max_trials` falls below the TPE-warmup-derived floor; operators can silently re-introduce the exact failure mode the shipped presets prevent for everyone else.
- **Outcome:** A non-blocking inline warning appears under the `max_trials` input whenever the derived preset is `custom` AND `max_trials < STUDIES_TPE_WARMUP_FLOOR (= 50)`, naming Focused/Standard as one-click remediations. The submit path stays unchanged (smoke tests against template wiring are legitimate sub-warmup use). A single backend constant grounds the threshold so the warning text and the MedianPruner activation threshold cannot drift.
- **Non-goals:** Server-side rejection of sub-warmup `max_trials` (backend `_require_one_stop_condition` validator stays as-is — Custom is intentional), the agent-driven `create_study` tool (system prompt already teaches Standard=200; revisit only if telemetry shows the agent emitting sub-50 trial counts), the digest narrative "this study was pre-convergence" note (routed to [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) per §19 D-3).

## 2) Current state audit

### Existing implementations

| File / surface | What it does | Notes |
|---|---|---|
| [`ui/src/components/studies/create-study-modal.tsx:91-110`](../../../../../ui/src/components/studies/create-study-modal.tsx#L91-L110) | `PRESET_VALUES` (`focused`/`standard`/`deep`/`custom`) + `FOCUSED_WRITE`/`STANDARD_WRITE`/`DEEP_WRITE` numeric writes | Shipped by `chore_study_default_stop_conditions`. Frontend-only state — preset wire values are NOT sent to backend. |
| [`ui/src/components/studies/create-study-modal.tsx:267-282`](../../../../../ui/src/components/studies/create-study-modal.tsx#L267-L282) | `watchedMaxTrials = form.watch('max_trials')` + `activePreset` `useMemo` that derives `'custom'` when the (max_trials, time_budget_min) tuple matches none of the 3 preset writes | The exact hook this spec extends: the warning's mount condition is `activePreset === 'custom' && watchedMaxTrials < STUDIES_TPE_WARMUP_FLOOR`. |
| [`ui/src/components/studies/create-study-modal.tsx:1257-1282`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1257-L1282) | Stop-condition preset button group (Step 5) — `role="group"` labeled "Stop condition" | The warning renders **between** this group and the numeric-inputs grid that immediately follows (line 1283). |
| [`ui/src/components/studies/create-study-modal.tsx:1283-1318`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1283-L1318) | Numeric inputs grid (`max_trials` / `time_budget_min` / `parallelism`) | Unmodified by this spec — the warning sits above this grid, not next to the input. |
| [`ui/src/components/studies/create-study-modal.tsx:1107-1115`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1107-L1115) | Existing inline-warning pattern (`cs-placeholder-warning`) — `<p className="text-sm text-amber-700 dark:text-amber-400" data-testid="cs-...">...</p>` | Exact pattern the sub-warmup warning reuses for visual + a11y consistency. |
| [`ui/src/lib/glossary.ts:172-176`](../../../../../ui/src/lib/glossary.ts#L172-L176) | `study.preset` glossary entry | This spec adds **no** new glossary key per D-0a (FR-4 dropped). The `study.preset` entry remains the canonical preset-discovery surface; a future `HelpPopover` story would own adding any new glossary key. |
| [`backend/app/eval/optuna_runtime.py:107`](../../../../../backend/app/eval/optuna_runtime.py#L107) | `TPESampler(seed=seed)` — uses Optuna default `n_startup_trials=10` (NOT overridden per-study) | Source for the "first ~10 trials are random" claim in the warning copy. |
| [`backend/app/eval/optuna_runtime.py:116-156`](../../../../../backend/app/eval/optuna_runtime.py#L116-L156) | `build_pruner` — branches on `config["max_trials"] < 50` → `NopPruner`; `>= 50` → `MedianPruner(n_warmup_steps=10)` | The literal `50` at line 121 is the canonical threshold. **This spec hoists the literal to a module-level `STUDIES_TPE_WARMUP_FLOOR = 50` constant** so `build_pruner` and the wizard share one source of truth. |
| [`backend/app/api/v1/schemas.py:629`](../../../../../backend/app/api/v1/schemas.py#L629) | `_require_one_stop_condition` Pydantic validator | Unchanged — server still only enforces "at least one of `max_trials` / `time_budget_min`"; sub-warmup is a UX warning, not a hard guard. |
| [`backend/app/llm/digest_prompt.py:121`](../../../../../backend/app/llm/digest_prompt.py#L121) | Digest LLM prompt — "narrow"/"widen" follow-up framing | Cited in idea as the misattribution failure mode; **not modified** by this spec (routed to `feat_study_convergence_indicator`). |
| [`ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`](../../../../../ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx) | Existing vitest scaffold with `walkToStep5()`, `getMaxTrialsInput()`, `getPresetButton(name)` helpers (383 lines) | New show/hide assertions append here — no new test file needed. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| — | (no URLs change; this is in-form UX) | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` | `walkToStep5` + preset-state assertions | 1 file | Append 5 new test cases (see §14): (1) show on Custom + max_trials<50 [AC-1], (2) hide on max_trials==50 [AC-2], (3) hide on non-Custom preset [AC-3], (4) hide on empty/NaN [AC-4], (5) submit non-blocking — MSW handler observes `config.max_trials===12` request body [AC-6]. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Main flow E2E-ish | 1 file | Verify the existing "Standard preset → submit" flow stays green (no new assertions needed; this is a regression-safety check that the new conditional render didn't break Step 5). |
| `backend/tests/unit/eval/test_optuna_runtime.py` (or equivalent — verify path at impl time) | `build_pruner` branch tests | grep at impl time | Existing `build_pruner` boundary tests (if any) pass unchanged because the hoist is semantic-preserving; FR-7 appends 3 new assertions (constant value + two boundary cases). Tests do not assert "references the constant not the literal" — that's a code-review concern, not unit-test surface. |

### Existing behaviors affected by scope change

- **Wizard Step 5 with Custom preset + `max_trials < 50`** → today: silent; new: inline amber warning under the preset group with one-click remediation hints. Decision needed: **no** (locked).
- **`build_pruner` literal `50`** → today: inline literal at `optuna_runtime.py:121`; new: `STUDIES_TPE_WARMUP_FLOOR` module constant referenced at the same call site. Behavior identical; this is a refactor for shared-source-of-truth. Decision needed: **no** (locked).
- **Submit handler** → unchanged. Sub-warmup `max_trials` still submits successfully. Decision needed: **no** (locked — non-blocking is the spec's principle).

---

## 3) Scope

### In scope

- **FR-1:** Hoist the literal `50` at [`backend/app/eval/optuna_runtime.py:121`](../../../../../backend/app/eval/optuna_runtime.py#L121) to a module-level constant `STUDIES_TPE_WARMUP_FLOOR = 50` defined near the top of the file (above `build_sampler` / `build_pruner`); update `build_pruner` to reference it. Frozen at 50 for parity with MedianPruner activation.
- **FR-2:** Render a conditional inline warning in the create-study modal Step 5, between the preset button group (line 1282) and the numeric-inputs grid (line 1283), shown when `activePreset === 'custom' && typeof watchedMaxTrials === 'number' && watchedMaxTrials < STUDIES_TPE_WARMUP_FLOOR`. Hidden in every other branch.
- **FR-3:** The warning copy names Focused (50) and Standard (200) as one-click remediations and explains **both** mechanisms that make sub-50 studies underperform — the ~10-trial random-search startup window AND the MedianPruner-50 pruning floor — without requiring the operator to know Optuna-specific jargon (no "TPE" / "MedianPruner" tokens in the copy).
- **FR-4:** ~~Glossary entry~~ — dropped per GPT-5.5 cycle-1 Finding #1; the warning copy is self-sufficient. (FR-4 slot retained as a numbered placeholder so FR-5/6/7 keep their IDs.)
- **FR-5:** Frontend constant `SUB_WARMUP_FLOOR = 50` (or equivalent name) in [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) carries a `// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR` comment per the Enumerated Value Contract Discipline. (No wire-level enum — the constant is a numeric threshold, not a backend-validated enum value, so no `/lib/enums.ts` entry and no router-side allowlist change.)
- **FR-6:** Vitest coverage in `create-study-modal.stop-conditions.test.tsx` for the 4 branch cases enumerated in §2 "Existing test impact" — show + hide + non-Custom hide + copy assertion.
- **FR-7:** A single backend unit test in `backend/tests/unit/eval/test_optuna_runtime.py` (or equivalent) asserts `STUDIES_TPE_WARMUP_FLOOR == 50`, that `build_pruner({"max_trials": floor - 1})` returns a `NopPruner`, and that `build_pruner({"max_trials": floor})` returns a `MedianPruner`. The "no remaining inline literal `50` at line 121" enforcement lives at code-review per D-0c — out of scope for the unit test layer.

### Out of scope

- Server-side rejection of sub-warmup `max_trials`. The backend `_require_one_stop_condition` validator at [`schemas.py:629`](../../../../../backend/app/api/v1/schemas.py#L629) keeps its current contract — "at least one of `max_trials` / `time_budget_min`" — and does not gain a sub-warmup branch. Custom is intentionally permissive; the warning makes the cost legible without blocking the legitimate quick-smoke-test use case (idea principle: "non-blocking").
- The agent-driven `create_study` tool. The orchestrator system prompt at [`prompts/orchestrator.system.md`](../../../../../prompts/orchestrator.system.md) was already updated by `chore_study_default_stop_conditions` to teach `max_trials=200` (Standard) as the recommended default. Telemetry showing the agent emitting sub-50 values would justify a future warning-emit-via-tool-response branch; absent that signal, the agent path stays unchanged.
- Digest narrative note when `trials_run < STUDIES_TPE_WARMUP_FLOOR`. **Routed to [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md)** per §19 D-3 — that feature already owns the "did this study plateau?" framing end-to-end and its idea §"Open questions" #2 explicitly asks to absorb the digest-note ownership. This spec is purely create-time UX.
- Convergence verdict on the study detail page. Same routing — `feat_study_convergence_indicator` owns the result-time surface.
- Per-study override of `n_startup_trials` in `optuna_runtime.py:107`. Not configurable today; making it configurable would change what "warmup floor" means and require re-deriving the constant per study. Out of scope; revisit if a future spec needs per-study sampler tuning.
- Tooltip on the warning itself. The warning copy IS the tooltip equivalent — it's already a full-sentence non-obscure explanation. Adding a `<InfoTooltip>` on a warning would be tooltip-on-tooltip.

### API convention check

- **Endpoint prefix convention:** N/A — this feature adds no endpoints. (Verified by walking §3 In scope — no FR creates a router method.)
- **Router namespace:** N/A.
- **Non-auth error envelope:** N/A. The wizard's existing client-side stop-condition guard (idea-cited at line 669-670 of the modal: `(values.max_trials > 0) || (values.time_budget_min > 0)`) plus the server-side `_require_one_stop_condition` validator at [`schemas.py:629`](../../../../../backend/app/api/v1/schemas.py#L629) — both unchanged by this spec — produce the standard envelope per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) on validation failure. No new error code is introduced.

### Phase boundaries (single-phase)

Single phase. The deliverable is:

- 1 backend constant hoist + 3 backend unit-test assertions (FR-1, FR-7)
- 1 frontend conditional warning + frontend constant + cross-side comment (FR-2, FR-3, FR-5)
- 5 vitest cases (FR-6 — 4 render-branch cases + 1 submit-non-blocking case for AC-6)

The digest-narrative half is **explicitly routed out** to `feat_study_convergence_indicator` (D-3), so there is no Phase 2 to defer. **No `phase2_idea.md` is required.**

## 4) Product principles and constraints

- **Non-blocking by design.** The warning never blocks submit. Smoke tests against template wiring (e.g., "does my Jinja syntax parse?" — 10 trials is sufficient) are legitimate uses of Custom mode; the warning must inform, not gatekeep.
- **Backend-canonical threshold, frontend mirrors with explicit comment.** The number `50` is defined in `STUDIES_TPE_WARMUP_FLOOR` in `optuna_runtime.py` and mirrored in the frontend as `SUB_WARMUP_FLOOR`, with a `// Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR` comment per the Enumerated Value Contract Discipline. The discipline + the backend test (FR-7) catch drift; the frontend cannot import the backend constant directly (no runtime endpoint round-trips a single integer). If the threshold ever changes, both sides move together by editing one Python line + one TypeScript constant whose comment pins to it.
- **Visual + a11y consistency with the existing inline-warning pattern.** Reuse the exact CSS classes and `<p data-testid="cs-..." className="text-sm text-amber-700 dark:text-amber-400">` shape that `cs-placeholder-warning` (line 1107) already uses. No new amber-warning component; no new styling token.
- **Copy that names the one-click remediation.** The operator who hits this warning is already typing low numbers — telling them "use a higher number" is unhelpful; telling them "click Focused (50) or Standard (200)" is.
- **Backend constant hoist is mechanical, not a refactor.** FR-1 changes a literal to a named reference at one call site. The constant value (50), the MedianPruner activation semantic, and the `build_pruner` branch logic are all identical pre and post. This is a foundation for FR-5's cross-side discipline, not a behavior change.

### Anti-patterns

- **Do not** add a server-side validator rejecting sub-warmup `max_trials`. That breaks legitimate smoke-test workflows and contradicts the non-blocking principle. The warning is at the wizard layer specifically because the operator must be able to override it.
- **Do not** show the warning when `watchedMaxTrials` is the empty string / NaN / undefined / non-integer. Custom mode with an empty or partial `max_trials` is a transient state during typing — the warning's `typeof watchedMaxTrials === 'number' && Number.isInteger(watchedMaxTrials)` guard is what suppresses it *until* the operator has committed a sub-warmup integer, not while they're mid-keystroke or typing a decimal. (Spec'd this way in FR-2.) This anti-pattern guards against an early implementation where the empty-string warning render would surface during ordinary typing — confusing and noisy.
- **Do not** add a new amber-warning component. Reuse the existing class string. Component abstractions for a single 1-off render produce churn without value; cite the existing pattern and inline.
- **Do not** hoist `n_startup_trials` (the literal `10` baked into TPESampler's default) to a constant. The "first ~10 trials" claim in the warning copy is an approximation of Optuna's TPE behavior, not a project-internal value — making it a constant would imply the project owns the number, which it doesn't.
- **Do not** make the warning's threshold a per-study override / config field. If different studies want different floors, the right answer is a different sampler; the floor is a property of the TPE+MedianPruner contract, not per-study tunable.
- **Do not** modify the digest prompt or proposal UI in this spec. Both belong to `feat_study_convergence_indicator` per D-3 — touching them here forks ownership.

## 5) Assumptions and dependencies

- **Dependency:** [`chore_study_default_stop_conditions`](../../../implemented_features/2026_05_23_chore_study_default_stop_conditions/) (shipped 2026-05-23). Provides `PRESET_VALUES`, `activePreset` derivation, the preset button group at modal lines 1257-1282, and the MedianPruner-50 calibration. **Status: shipped.** Hard dependency — the warning sits in the Step 5 preset surface this chore created. **Risk if missing:** None — already on main.
- **Dependency:** MVP1 study lifecycle (shipped). Provides `studies.config` schema with `max_trials` field, the create-study modal as a whole, and `optuna_runtime.py`'s `build_pruner` flow. **Status: shipped.**
- **No dependency** on MVP2 anchors (`infra_adapter_solr`, `feat_ubi_judgments`, `feat_ubi_onramp`). Composes with them — a converged study under any engine + judgment source benefits equally — but does not require any of them.
- **Coordination (not a blocking dependency):** [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md). That spec's idea §"Open questions" #2 explicitly asks to absorb digest-note ownership; this spec's D-3 confirms the routing. Neither spec blocks the other for code merging — this guard ships independently. **If `feat_study_convergence_indicator` declines the digest note at its own `/spec-gen` time,** route it back via a follow-up `phase2_idea.md` here. (Not anticipated — the sibling's own idea is set up to take it.)

## 6) Actors and roles

- Primary actor: **Relevance Engineer** (single role in MVP1–MVP3 per umbrella spec §6). Interacts with the wizard's Step 5 budget surface; sees and dismisses (by editing values) the new warning.
- Role model: **N/A — single-tenant install, no auth surface** (RelyLoop MVP1–MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../../01_architecture/tech-stack.md)).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this spec adds no state-mutating endpoint or service function. The warning is presentation-only; the existing `POST /api/v1/studies` mutation path (which is what eventually persists a sub-warmup study if the operator submits anyway) is unchanged and out of scope for this spec's audit-event matrix. **MVP2 audit_log activation applies to specs that mutate state; this one does not.**

## 7) Functional requirements

### FR-1: Backend constant hoist

- Requirement:
  - The system **MUST** define a module-level constant `STUDIES_TPE_WARMUP_FLOOR: int = 50` at the top of [`backend/app/eval/optuna_runtime.py`](../../../../../backend/app/eval/optuna_runtime.py) (after imports, before `build_sampler`).
  - The `build_pruner` function at [`backend/app/eval/optuna_runtime.py:116-156`](../../../../../backend/app/eval/optuna_runtime.py#L116-L156) **MUST** reference `STUDIES_TPE_WARMUP_FLOOR` instead of the inline literal `50` on line 121 (`config["max_trials"] < 50`).
  - The constant **MUST** be exported (top-level public symbol — no leading underscore) so the test in FR-7 can import it directly.
  - Behavior **MUST** be identical to current `build_pruner` semantics for every input (Phase 1: refactor only).
- Notes: This is a mechanical refactor with one user: the shared-source-of-truth contract in FR-5. Existing `build_pruner` tests should pass unchanged (or update from literal `50` to `STUDIES_TPE_WARMUP_FLOOR` — see FR-7).

### FR-2: Conditional warning render

- Requirement:
  - The create-study modal at [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) **MUST** render an inline warning between the Stop-condition preset button group (currently ending at line 1282) and the numeric-inputs grid (currently starting at line 1283).
  - The warning **MUST** render only when ALL of the following are true:
    - `activePreset === 'custom'` (the `useMemo` at line 269)
    - `typeof watchedMaxTrials === 'number'` AND `!Number.isNaN(watchedMaxTrials)` AND `Number.isInteger(watchedMaxTrials)` (the `form.watch('max_trials')` at line 267 — the integer guard suppresses warnings during transient decimal-typing states like `49.99`, which Pydantic also rejects on int coercion at submit per [`schemas.py:604`](../../../../../backend/app/api/v1/schemas.py#L604))
    - `watchedMaxTrials < SUB_WARMUP_FLOOR` (the frontend constant from FR-5)
  - The warning **MUST NOT** render in any other branch (non-Custom preset, empty `max_trials`, non-integer `max_trials`, or `max_trials >= SUB_WARMUP_FLOOR`).
  - The warning element **MUST** use `<p>` with `data-testid="cs-sub-warmup-warning"`, `className="text-sm text-amber-700 dark:text-amber-400"`, and `role="status"` (non-blocking advisory; not `role="alert"` since the operator did not commit an error).
- Notes: The mount condition is computed once per render via `useMemo`-derived `activePreset` + `watchedMaxTrials` already in scope at the function body — no new hook needed.

### FR-3: Warning copy

- Requirement:
  - The warning text **MUST** be exactly:
    > **The optimizer spends its first ~10 trials exploring randomly, and studies below 50 trials skip RelyLoop's pruning floor.** With `{watchedMaxTrials}` trials this study is unlikely to converge — switch to **Focused (50)** for a quick run or **Standard (200)** for a result worth turning into a PR.
  - The `{watchedMaxTrials}` placeholder **MUST** be interpolated as a literal integer (no thousand-separators, no decimal).
  - The bold spans on "The optimizer spends its first ~10 trials exploring randomly, and studies below 50 trials skip RelyLoop's pruning floor", "Focused (50)", and "Standard (200)" **MUST** be rendered via `<strong>` elements (not CSS `font-weight: bold` on a parent) so screen readers convey emphasis.
  - The preset names "Focused (50)" and "Standard (200)" in the copy **MUST** match `presetLabel('focused')` and `presetLabel('standard')` from [`create-study-modal.tsx:94-105`](../../../../../ui/src/components/studies/create-study-modal.tsx#L94-L105) — if a future spec ever renames the presets, both labels move together.
- Notes: Copy names **both** mechanisms that make sub-50 studies underperform — the TPE random-warmup period (which dominates for `max_trials` ≤ ~20) and the MedianPruner activation floor at 50 (which gates pruning for the full `< 50` range). This makes the warning accurate across the whole trigger range (1–49), not just the deepest portion of it. The leading `<strong>` clause is self-contained — the operator does not need to know what TPE / MedianPruner are; the recommendation is one-click-actionable.

### FR-4: ~~Glossary entry~~ — dropped per GPT-5.5 cycle-1 Finding #1

**Removed.** No glossary entry is shipped by this spec. The warning's own inline copy (FR-3) is the operator-facing explanation; adding an unwired glossary key for a hypothetical future `HelpPopover` was scope drift. If a future story wires a `HelpPopover` to this warning, that story owns adding the glossary key.

The FR-4 slot is intentionally retained as a numbered placeholder so FR-5 / FR-6 / FR-7 keep their original IDs and the traceability matrix at §17 doesn't need to renumber.

### FR-5: Frontend constant + cross-side comment

- Requirement:
  - A constant `SUB_WARMUP_FLOOR: number = 50` (or equivalent name — see story 1.2 for the exact identifier) **MUST** be defined in [`create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) near the existing `PRESET_VALUES` declaration (around lines 91-110).
  - The constant declaration **MUST** carry an immediately-preceding line comment of the form:
    ```
    // Values must match backend/app/eval/optuna_runtime.py STUDIES_TPE_WARMUP_FLOOR
    ```
    per the Enumerated Value Contract Discipline ([`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md), CLAUDE.md "Common Pitfalls").
  - The constant **MUST NOT** be added to [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) — that file is for backend-validated wire-value allowlists; this is a numeric threshold not sent over the wire.
- Notes: The comment is the lint-equivalent — frontend-side, there is no automated guard (the existing `data-table-column-discipline.test.tsx` and `form-select-discipline.test.tsx` guards are for `<select>`/`<DataTable>` enums, not numeric constants). The cross-side guard is the comment + the backend test in FR-7 that asserts the literal value, so a backend edit forces a test failure.

### FR-6: Vitest branch coverage

- Requirement:
  - New test cases **MUST** be appended to [`ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx`](../../../../../ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx) — no new test file.
  - The following branches **MUST** be asserted:
    - **Show (AC-1):** `walkToStep5()` → click `getPresetButton(/Focused/)` → edit `getMaxTrialsInput()` to `12` → `screen.findByTestId('cs-sub-warmup-warning')` resolves; assert the rendered text contains "Focused (50)" AND "Standard (200)" AND the integer "12".
    - **Hide on threshold (AC-2):** same setup, but edit to `50` → `screen.queryByTestId('cs-sub-warmup-warning')` returns null.
    - **Hide on non-Custom (AC-3):** click `getPresetButton(/Focused/)` → leave `max_trials=50` (Focused preset write) → `screen.queryByTestId('cs-sub-warmup-warning')` returns null (Custom inactive).
    - **Hide on empty (AC-4):** click `getPresetButton(/Standard/)` then edit `getMaxTrialsInput()` to empty/NaN → warning hidden (this guards against rendering during partial-keystroke states).
    - **Submit non-blocking (AC-6):** AC-1 state → click submit → assert the mocked `POST /api/v1/studies` MSW handler is called AND its observed request body's `config.max_trials === 12`. Response status is whatever the mock returns; the assertion is on the request firing, not on the server's verdict.
- Notes: All five assertions reuse the existing `walkToStep5` / preset-button / max-trials-input helpers + the file's existing MSW setup — no new test infra.

### FR-7: Backend constant contract test

- Requirement:
  - A test in `backend/tests/unit/eval/test_optuna_runtime.py` (verify path at impl time — file may be named differently; create if absent) **MUST** assert:
    - `STUDIES_TPE_WARMUP_FLOOR == 50` (the literal contract — locks the value so a silent threshold change forces a test update).
    - `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR - 1})` returns a `NopPruner` instance (boundary below the floor).
    - `build_pruner({"max_trials": STUDIES_TPE_WARMUP_FLOOR})` returns a `MedianPruner` instance (boundary at the floor).
  - The first assertion **MUST** import `STUDIES_TPE_WARMUP_FLOOR` directly from `backend.app.eval.optuna_runtime` — not re-derive it.
- Notes: The three assertions are pure behavior tests — they would pass equally well whether `build_pruner` uses the named constant or a re-introduced literal `50`. The "no remaining inline literal" enforcement lives at the **code-review** layer (PR review + the diff is small enough that a literal slip-through is mechanically obvious), not at the test layer — asserting source-code structure ("references the constant, not the literal") is brittle and out of scope for a unit test. Per GPT-5.5 cycle-1 Finding #3.

## 8) API and data contract baseline

### 7.1 Endpoint surface

**N/A — this feature adds no endpoints.** Verified against §3 In scope: all 7 FRs are file-level changes to existing code paths. The `POST /api/v1/studies` endpoint (the eventual recipient of a sub-warmup study if the operator submits) is unchanged.

### 7.2 Contract rules

N/A — no new API surface.

### 7.3 Response examples

N/A — no new API surface.

### 7.4 Enumerated value contracts

**This spec adds no `<select>`, filter dropdown, status badge, or wire-value enum.** The single numeric constant `SUB_WARMUP_FLOOR = 50` is a threshold, not an allowlist value — per FR-5, it's grounded in `STUDIES_TPE_WARMUP_FLOOR` via a `// Values must match` comment (the Enumerated Value Contract Discipline's mechanism for non-enum cross-side constants), but no `Literal[...]` or `frozenset` allowlist is introduced.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `SUB_WARMUP_FLOOR` (frontend) | `50` (single integer threshold; not an enum) | [`backend/app/eval/optuna_runtime.py`](../../../../../backend/app/eval/optuna_runtime.py) `STUDIES_TPE_WARMUP_FLOOR` (FR-1) | [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) — comparison in the warning's render guard (FR-2) |

### 7.5 Error code catalog

**No new error codes.** The wizard's existing client-side stop-condition guard (modal lines 669-670) and the server-side `_require_one_stop_condition` validator at [`schemas.py:629`](../../../../../backend/app/api/v1/schemas.py#L629) produce the canonical envelope per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) on existing failure modes — this spec adds no new failure mode.

## 9) Data model and state transitions

### New/changed entities

**None.** No migration. No ORM model changes. No column additions or renames. The `studies.config.max_trials` JSONB field is read by the warning's mount condition but is not written or schemas-changed by this spec.

### Required invariants

- **Threshold parity invariant:** The numeric threshold in `STUDIES_TPE_WARMUP_FLOOR` (backend constant, FR-1) and `SUB_WARMUP_FLOOR` (frontend constant, FR-5) **MUST** be equal at all times. Enforced via: (a) the `// Values must match` comment per FR-5, (b) the backend test asserting `STUDIES_TPE_WARMUP_FLOOR == 50` per FR-7, and (c) the warning copy in FR-3 hard-codes "Focused (50)" so a frontend-only drift would produce a self-contradictory warning that PR review catches.
- **Non-blocking submit invariant:** The wizard's submit handler **MUST NOT** branch on the warning's mount condition. The warning's appearance does not change the submit path. (Negative invariant: easy to assert via reading the changed code; no test required since it would be testing absence.)

### State transitions

N/A — no state machine touched. The wizard form's `activePreset` derivation is unchanged; this spec adds a render branch downstream of it.

### Idempotency/replay behavior

N/A — no event-driven path touched.

## 10) Security, privacy, and compliance

- **Threats:** None new. The warning is rendered client-side from form state already present in the operator's browser; no new data crosses the network. No new secrets, tokens, or PII paths. CLAUDE.md Absolute Rule #10 (never log/expose secrets) is unchanged.
- **Controls:** N/A.
- **Secrets/key handling:** N/A — no secrets touched.
- **Auditability:** N/A — the warning is a UI hint, not a state-mutating action. The eventual `POST /api/v1/studies` request (if the operator submits anyway) carries the operator's own choices and is logged per the existing request-id middleware path; no new audit field needed.
- **Data retention/deletion/export impact:** N/A — no new data stored.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Inside the existing create-study modal's Step 5 ("Objective + config"). The warning sits between the Stop-condition preset button group (line 1282) and the numeric-inputs grid (line 1283) — directly downstream of where the operator's preset selection produces the Custom state, and directly upstream of where they would adjust `max_trials` to address it.
- **Labeling taxonomy:** The warning is unlabeled (it IS the label of itself — a `<p>` with copy, not a labeled field). The text references "Focused (50)" and "Standard (200)" by their `presetLabel` exact strings (FR-3) so the operator's eye can match the in-warning recommendation to the buttons immediately above.
- **Content hierarchy:** The warning is **secondary**, visually subordinate to both the preset button group (primary action) and the numeric inputs (primary action). The amber color signals advisory, not error; the placement keeps it adjacent to but not occluding either primary action.
- **Progressive disclosure:** The warning IS the progressive disclosure — hidden by default (every non-Custom-sub-50 state), revealed only when the operator's combined inputs (`activePreset === 'custom'` + `max_trials < 50`) put them in the failure region. No expand/collapse; no "Learn more" link in MVP. A future story can wire a `HelpPopover` adjacent to the warning if operator research surfaces the need — that story would own adding any new glossary key (FR-4 is dropped from this spec per D-0a).
- **Relationship to existing pages:** Extends Step 5 of the create-study modal. Replaces nothing. Sits alongside the existing `cs-placeholder-warning` (same amber inline-warning visual treatment) — two warnings in different steps, with consistent style.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| The warning itself (`cs-sub-warmup-warning`) | (no tooltip — the warning's own copy IS the explanation; tooltip-on-tooltip is an anti-pattern per §4) | N/A | inline |

The `study.preset` glossary key (lines 172-176 of `glossary.ts`) already attached to the `InfoTooltip` on the preset group label remains the discovery surface for "what do these presets mean". This spec adds no new glossary key per D-0a; a future story that wires a `HelpPopover` to this warning would own adding one.

### Primary flows

1. **Custom + sub-warmup → warning fires.** Operator opens the create-study modal, walks to Step 5, clicks Focused (writes `max_trials=50`), then edits `max_trials` to `12` (or any value < 50). `activePreset` re-derives to `'custom'` (the (12, '') tuple matches no preset write). Warning appears between the preset group and inputs grid. Operator either: (a) clicks Focused again — `activePreset` returns to `'focused'`, `max_trials` writes back to 50, warning hides; (b) increases `max_trials` to ≥ 50 — `activePreset` stays `'custom'` but the threshold check fails, warning hides; (c) ignores the warning and submits — submit proceeds normally, study is created with the sub-warmup `max_trials`.
2. **Non-Custom → no warning ever.** Operator picks Focused / Standard / Deep — `activePreset !== 'custom'`, the render guard short-circuits, warning never mounts.
3. **Cleared inputs → no warning.** Operator clears `max_trials` while in Custom mode (transient typing state). `typeof watchedMaxTrials !== 'number'` (it's `NaN` or `''`), the second clause of the render guard short-circuits, warning hides.

### Edge/error flows

- **Operator types `max_trials = 0` (Pydantic would reject):** Warning's threshold check evaluates `0 < 50 === true`, so the warning fires. The operator sees the warning AND would hit the server-side `ge=1` validation on submit. Acceptable — the warning catches them upstream of the server error; no edge case to special-case.
- **Operator types `max_trials = 49.99` (floating-point — Pydantic rejects on `int` coercion):** Per FR-2's `Number.isInteger` guard, the warning **does NOT fire** for non-integer values — the transient decimal state is suppressed during typing. The operator's submit then surfaces Pydantic's 422 VALIDATION_ERROR at [`schemas.py:604`](../../../../../backend/app/api/v1/schemas.py#L604) (`Field(ge=1)` on `int | None`) as the authoritative reject. Per D-0g.
- **Operator switches from Custom-sub-50 to Custom-sub-50 with a different number (e.g., 12 → 15):** Warning re-renders with the new `{watchedMaxTrials}` interpolation; no flicker; visual continuity preserved.
- **`prefillValues` carries `max_trials=12` from a clone-from-previous flow:** The form's `useEffect` at lines 310-332 resets `max_trials=12`; `activePreset` derives to `'custom'` (12 matches no preset); warning fires immediately on Step 5 entry. Acceptable — the cloned study's under-budgeting is exactly what the warning should flag.

## 12) Given/When/Then acceptance criteria

### AC-1: Warning shows on Custom-mode sub-warmup max_trials

- Given the create-study modal is open at Step 5 and `activePreset` is `'custom'`
- And `watchedMaxTrials` is a finite number strictly less than 50
- When the render commits
- Then the element `data-testid="cs-sub-warmup-warning"` is present in the DOM
- And its text contains the interpolated `watchedMaxTrials` integer (e.g., "With 12 trials")
- And its text contains the exact strings "Focused (50)" and "Standard (200)"
- Example values:
  - Input: walkToStep5(); fireEvent.click(getPresetButton(/Focused/)); fireEvent.change(getMaxTrialsInput(), { target: { value: '12' } });
  - Expected: `await screen.findByTestId('cs-sub-warmup-warning')` resolves; its `textContent` includes "12", "Focused (50)", "Standard (200)".

### AC-2: Warning hides at the threshold boundary

- Given the create-study modal is open at Step 5 and `activePreset` is `'custom'`
- And `watchedMaxTrials === 50`
- When the render commits
- Then `cs-sub-warmup-warning` is NOT present in the DOM
- Example values:
  - Input: walkToStep5(); fireEvent.click(getPresetButton(/Focused/)); (no edit — Focused writes 50 directly, but Focused is non-Custom; use a Custom-50 path: click Standard → edit max_trials to 50 → activePreset becomes 'custom' because (50, '') ≠ STANDARD_WRITE (200, ''))
  - Expected: `screen.queryByTestId('cs-sub-warmup-warning')` returns `null`.

### AC-3: Warning hides on non-Custom preset regardless of max_trials

- Given the create-study modal is open at Step 5
- And `activePreset` is `'focused' | 'standard' | 'deep'` (any non-Custom)
- When the render commits
- Then `cs-sub-warmup-warning` is NOT present in the DOM
- Example values:
  - Input: walkToStep5(); fireEvent.click(getPresetButton(/Focused/));
  - Expected: `screen.queryByTestId('cs-sub-warmup-warning')` returns `null`.

### AC-4: Warning hides when max_trials is not a finite integer

- Given the create-study modal is open at Step 5 and `activePreset` is `'custom'`
- And `watchedMaxTrials` is the empty string, `NaN`, `undefined`, `null`, OR a non-integer number (e.g., `49.99`)
- When the render commits
- Then `cs-sub-warmup-warning` is NOT present in the DOM
- Example values:
  - Input A: walkToStep5(); fireEvent.click(getPresetButton(/Standard/)); fireEvent.change(getMaxTrialsInput(), { target: { value: '' } });
  - Expected A: `screen.queryByTestId('cs-sub-warmup-warning')` returns `null` (transient typing state — warning suppressed).
  - Input B (optional second assertion in the same test case): set `max_trials` to `49.99` programmatically.
  - Expected B: `screen.queryByTestId('cs-sub-warmup-warning')` returns `null` (non-integer suppression per `Number.isInteger` guard in FR-2).

### AC-5: Backend constant is the single source of truth

- Given `STUDIES_TPE_WARMUP_FLOOR` is imported from `backend.app.eval.optuna_runtime`
- When the constant is evaluated
- Then it equals exactly `50`
- And `build_pruner({"max_trials": 49})` returns a `NopPruner`
- And `build_pruner({"max_trials": 50})` returns a `MedianPruner`
- Example values:
  - Input: `from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR, build_pruner`
  - Expected: `STUDIES_TPE_WARMUP_FLOOR == 50`; `isinstance(build_pruner({"max_trials": 49}), NopPruner)`; `isinstance(build_pruner({"max_trials": 50}), MedianPruner)`.

### AC-6: Submit is non-blocking client-side when the warning is shown

- Given the warning is rendered (AC-1 preconditions met) AND all other Step 5 fields are valid
- When the operator clicks the modal's submit button
- Then the wizard's existing `useCreateStudy()` mutation fires with the operator's chosen `max_trials` value (no client-side gate against sub-warmup values)
- And the warning's presence does not appear in the request body or change the request shape
- And the eventual response is determined by the existing server-side validators (which already accept any `max_trials >= 1`); HTTP 201 vs 422 is the server's call, not the wizard's
- Example values:
  - Input: AC-1 state; click submit.
  - Expected (vitest assertion): the mocked `POST /api/v1/studies` handler observes a request body whose `config.max_trials === 12`; the mutation completes with whatever the mock returns (200/201/422 all acceptable — the assertion is on the request being made, not on the response status). Per GPT-5.5 cycle-1 Finding #6, **no real HTTP 201 is asserted at the vitest layer**; verifying actual server acceptance is covered by existing contract tests against `POST /api/v1/studies`.

## 13) Non-functional requirements

- **Performance:** N/A — adds a constant-time render branch (≤ 1 boolean comparison + 1 typeof check) per Step 5 render. No new network calls. No new memos beyond the already-present `activePreset` `useMemo`.
- **Reliability:** N/A — the warning's failure mode is "doesn't render when it should" (silent UI bug) or "renders when it shouldn't" (cosmetic noise). Neither affects study creation or submit. The backend FR-1 hoist is semantically identical to the literal — no new failure mode.
- **Operability:** N/A — no new logs, metrics, or alerts. Operator-facing behavior is the warning text.
- **Accessibility/usability:** The warning element uses `role="status"` (advisory, not error) per WAI-ARIA — screen readers announce it when it appears without using the assertive `role="alert"` reserved for errors. `<strong>` elements convey emphasis per FR-3. Color (amber) is supplemental to the text content — text alone communicates the warning per WCAG 1.4.1 (color not the sole indicator).

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit (`backend/tests/unit/eval/`):** FR-7's `STUDIES_TPE_WARMUP_FLOOR == 50` + boundary `build_pruner` tests. Verify the file path at impl time; create if absent.
- **Integration (`backend/tests/integration/`):** None required. FR-1 is a constant hoist with no behavior change; existing integration tests covering `build_pruner` (if any) pass unchanged.
- **Contract (`backend/tests/contract/`):** None required. No new endpoint, no new error code, no response shape change.
- **Vitest (`ui/src/__tests__/components/studies/`):** FR-6's five cases — (1) show on Custom + sub-warmup [AC-1], (2) hide on threshold boundary [AC-2], (3) hide on non-Custom preset [AC-3], (4) hide on empty/NaN max_trials [AC-4], (5) submit non-blocking with warning visible — asserts the mocked `POST /api/v1/studies` MSW handler observes `config.max_trials === 12` [AC-6] — appended to `create-study-modal.stop-conditions.test.tsx`.
- **E2E (`ui/tests/e2e/`):** None required. The warning is a presentation-only state derivation; E2E coverage would be redundant with vitest. The existing Step 5 E2E flow at `ui/tests/e2e/studies.spec.ts` (or equivalent — verify path at impl time) should continue to pass unchanged.

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md`: Update §"Optuna configuration" table row for "Pruner" — the literal `<50` reference becomes `< STUDIES_TPE_WARMUP_FLOOR` with a one-line callout that the constant is shared with the wizard's Custom-mode sub-warmup warning. Single-sentence update.
- `docs/01_architecture/ui-architecture.md`: Add a one-line note under §"Form dropdown primitive" or §"Enumerated Value Contract" (verify exact section at impl time) calling out the `// Values must match backend/...` pattern's use for numeric thresholds (not just enum allowlists). Optional but recommended for the discipline doc's completeness.
- `docs/02_product`: No update required (no new user-facing capability beyond a single inline warning; the existing create-study walkthrough doc remains accurate).
- `docs/03_runbooks`: No update required.
- `docs/04_security`: No update required.
- `docs/05_quality/testing.md`: No update required (test layers + coverage gate unchanged).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. This is a frontend warning + backend constant hoist; no operational risk justifies a flag. Ships on merge.
- **Migration/backfill expectations:** None — no schema change.
- **Operational readiness gates:** None new. The existing pre-commit hooks (`commit-msg`, ruff format/check, mypy, vitest, tsc) gate as usual.
- **Release gate:** Standard PR-merge gates per CLAUDE.md (CI green, Gemini review adjudicated, GPT-5.5 final review pass clean).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (backend constant hoist) | AC-5 | Story 1.1 — hoist literal + update `build_pruner` reference | `backend/tests/unit/eval/test_optuna_runtime.py` | `docs/01_architecture/optimization.md` §"Optuna configuration" |
| FR-2 (conditional render) | AC-1, AC-2, AC-3, AC-4 | Story 1.3 — insert conditional `<p>` between preset group and inputs grid | `ui/src/__tests__/components/studies/create-study-modal.stop-conditions.test.tsx` | — |
| FR-3 (warning copy) | AC-1 | Story 1.3 (same as FR-2 — copy + element ship together) | `create-study-modal.stop-conditions.test.tsx` (copy assertion in AC-1 test) | — |
| FR-4 (~~glossary~~) | — | **Dropped — no story** | — | — |
| FR-5 (frontend constant + comment) | AC-2 (threshold), AC-5 (parity) | Story 1.2 — define `SUB_WARMUP_FLOOR` constant + `// Values must match` comment | (covered by AC-2 + AC-5 tests) | `docs/01_architecture/ui-architecture.md` (optional — see §15) |
| FR-6 (vitest cases) | AC-1, AC-2, AC-3, AC-4, AC-6 | Story 1.4 (renumbered from 1.5 after FR-4 drop) — append 5 cases to `create-study-modal.stop-conditions.test.tsx` | `create-study-modal.stop-conditions.test.tsx` | — |
| FR-7 (backend test) | AC-5 | Story 1.1 (same as FR-1 — constant + test ship together) | `backend/tests/unit/eval/test_optuna_runtime.py` | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-6) pass in CI.
- [ ] `STUDIES_TPE_WARMUP_FLOOR` constant is defined and referenced by `build_pruner` (no remaining inline `50` literal at `optuna_runtime.py:121`).
- [ ] Frontend `SUB_WARMUP_FLOOR` constant carries the `// Values must match` comment per FR-5.
- [ ] All test layers (vitest unit + backend pytest unit) are green.
- [ ] `docs/01_architecture/optimization.md` §"Optuna configuration" reflects the constant name.
- [ ] No open questions remain in §19.
- [ ] PR cross-model review (Gemini + GPT-5.5 final) addressed.

## 19) Open questions and decision log

### Open questions

**None remain.** All 4 open questions from the idea were resolved in §"Decision log" below.

### Decision log

- **2026-05-29 (D-0c) — GPT-5.5 cycle-3 cross-model findings: 4/4 accepted (3 follow-on cleanup + 1 genuinely-new internal contradiction caught for the first time in cycle 3).**
  - **D-0c-i (Pass A, Medium):** §2 audit table row + §11 "Progressive disclosure" bullet still referenced the dropped `study.sub_warmup_warning` glossary key. Both fully scrubbed; §11 progressive-disclosure language replaced with "future story owns adding a glossary key if it wires a popover".
  - **D-0c-ii (Pass B, Low):** §2 "Existing test impact" row enumerated 4 vitest cases when FR-6 / §14 require 5. Aligned to 5 with AC mapping per case.
  - **D-0c-iii (Pass B, Medium) — NEW finding caught in cycle 3:** §4 anti-pattern bullet read "Do not hide the warning when `watchedMaxTrials` is the empty string / NaN / undefined" — which is the OPPOSITE of what FR-2 + AC-4 require ("Warning hides when max_trials is not a finite number"). Fixed: bullet reworded to "Do not show the warning when..." matching the actual contract. This contradiction was present from the original draft; cycle 1 and 2 missed it.
  - **D-0c-iv / D-0g (Pass B, Low) — NEW finding caught in cycle 3:** Decimal edge case. FR-2's original guard was `typeof watchedMaxTrials === 'number' && !Number.isNaN(watchedMaxTrials)`, but FR-3 required integer-only interpolation. §11 edge case said "49.99 → warning fires", which would render copy with a non-integer. Resolved by adding `Number.isInteger(watchedMaxTrials)` to the FR-2 mount condition (warning suppressed for non-integer transient typing); §11 edge case + AC-4 updated to reflect the integer guard; Pydantic's existing `int | None` coercion at [`schemas.py:604`](../../../../../backend/app/api/v1/schemas.py#L604) is the authoritative submit-time reject. Confidence in convergence: the new guard is a strict superset of the original (every state the original guard accepted is still accepted; decimal states are now suppressed).
- **2026-05-29 (D-0b) — GPT-5.5 cycle-2 cross-model findings: 3/3 accepted (all "the cycle-1 patch was incomplete" follow-ons).**
  - **D-0b-i (Pass A, Medium):** §3 In scope's FR-7 description still carried the brittle "references the constant (not the literal)" assertion that D-0c removed from §7 FR-7. Brought into alignment.
  - **D-0b-ii (Pass A, Medium):** §11 still referenced the dropped `study.sub_warmup_warning` glossary key (a future `HelpPopover` row + a sentence). Both removed; replaced with a one-line note that future stories own glossary additions if they wire a popover.
  - **D-0b-iii (Pass B, Low):** §14 test strategy still said "FR-6's four cases" but FR-6 was updated to 5 cases (with AC-6 submit-non-blocking) by D-0f. §14 corrected to enumerate all five cases with their AC mapping.
- **2026-05-29 (D-0) — GPT-5.5 cycle-1 cross-model findings: 6/6 accepted.**
  - **D-0a (Pass A, High):** Drop FR-4 (glossary entry) — unwired aspirational artifact. The warning copy is self-sufficient; a future `HelpPopover` story owns adding the glossary key if needed.
  - **D-0b (Pass A, Medium):** Reword §4's "single source of truth" claim to "backend-canonical, frontend mirrors with explicit comment" — the value IS duplicated (Python + TypeScript) by necessity; the discipline + cross-side comment + backend test catch drift.
  - **D-0c (Pass A, Medium):** Reduce FR-7 to value + boundary assertions; drop "test that build_pruner references the constant" — that's brittle source inspection. Code-review (small diff, mechanical inspection) catches literal-vs-constant slips.
  - **D-0d (Pass B, Medium):** Rewrite FR-3 warning copy to name **both** mechanisms (TPE random warmup at 10 + MedianPruner activation at 50) so the explanation is accurate across the full `<50` trigger range, not just the deepest portion.
  - **D-0e (Pass B, Low):** Drop "TPE" / "MedianPruner" jargon from the copy; use "the optimizer" + "RelyLoop's pruning floor". Resolves the internal contradiction where FR-3's preamble said "no jargon" but the copy opened with "TPE".
  - **D-0f (Pass B, Medium):** Reframe AC-6 + add a 5th vitest case asserting the wizard does not gate submit client-side (request body observation), without asserting a real HTTP 201 — that's covered by existing contract tests against `POST /api/v1/studies`.
- **2026-05-29 (D-1) — Threshold value: `< 50`.** Resolves idea Open Question #1. The MedianPruner activation threshold at [`optuna_runtime.py:121`](../../../../../backend/app/eval/optuna_runtime.py#L121) is `50`, the Focused preset (the one-click remediation named in the warning copy) writes `max_trials=50`, and the idea explicitly noted "lock unless `/spec-gen` finds an operator-research reason to differ" — no such reason found. Rejected alternative: `< 20` (= `2 × n_startup_trials`) — tighter, but introduces a second magic number unrelated to any shipped surface and contradicts the recommended remediation ("Focused (50)" would still be flagged at trials 21–49 even though Focused IS the recommendation).
- **2026-05-29 (D-2) — Warning copy as authored in FR-3.** Resolves idea Open Question #2. Two anchors honored: (a) names "Focused (50)" and "Standard (200)" as one-click remediations, (b) does not block submit. Copy emphasizes the *mechanism* (TPE random warmup) without requiring the operator to know what TPE is — the leading `<strong>` clause is self-contained. The `{watchedMaxTrials}` interpolation makes the cost concrete ("With 12 trials …") rather than abstract.
- **2026-05-29 (D-3) — Digest convergence note: out of scope; routed to [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md).** Resolves idea Open Question #3. The sibling's idea §"Open questions" #2 explicitly asks to absorb this; the convergence-indicator feature already owns "did this study plateau?" end-to-end, and splitting create-time + result-time guards across two specs lets each be sized + tested independently. Fallback: if `feat_study_convergence_indicator` declines at its own `/spec-gen` time, route back via a `phase2_idea.md` here. (Not anticipated.)
- **2026-05-29 (D-4) — Agent-tool guard: out of scope.** Resolves idea Open Question #4. The orchestrator system prompt already teaches `max_trials=200` (Standard) as the recommended default via the `chore_study_default_stop_conditions` shipping. The agent rarely picks sub-warmup values on its own; absent telemetry showing otherwise, the agent path stays unchanged. Revisit threshold: if any single `create_study` tool call emits `max_trials < 50` in production logs, file a follow-up.
- **2026-05-29 (D-5) — No new `enums.ts` entry.** The frontend `SUB_WARMUP_FLOOR` is a numeric threshold, not a backend-validated wire enum. [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) is for `<select>` / filter option lists whose wire values the backend validates against an allowlist (per CLAUDE.md "Enumerated Value Contract Discipline"); adding non-enum constants there would dilute the file's contract. The `// Values must match backend/...` comment per FR-5 is the discipline's mechanism for non-enum cross-side constants.
- **2026-05-29 (D-6) — Single phase, no `phase2_idea.md`.** Per §3 "Phase boundaries" — the digest narrative half is routed to D-3, so there is no Phase 2 to defer for this feature. The `pipeline_status.md` will list "Phases: 1 total, 1 covered by spec."

---

## Verification ledger (Pass 1 + Pass 2 — Opus internal)

| Claim | Verified by | Status |
|---|---|---|
| `optuna_runtime.py:107` — `TPESampler(seed=seed)` uses Optuna default `n_startup_trials=10` | Read file | Verified |
| `optuna_runtime.py:116-156` — `build_pruner` activates MedianPruner at `max_trials >= 50` | Read file | Verified |
| `optuna_runtime.py:121` — literal `50` is hardcoded at the branch condition today | Read file | Verified (will hoist to named constant per FR-1) |
| `schemas.py:629` — `_require_one_stop_condition` validator only enforces "at least one of `max_trials`/`time_budget_min`" | Read file | Verified |
| `digest_prompt.py:121` — narrow/widen framing exists | Grep | Verified (out of scope per D-3) |
| `create-study-modal.tsx:91-110` — `PRESET_VALUES` + `FOCUSED_WRITE`/`STANDARD_WRITE`/`DEEP_WRITE` constants | Read file | Verified |
| `create-study-modal.tsx:94-105` — `presetLabel` returns "Focused (50)" / "Standard (200)" / "Deep (1000)" / "Custom" | Read file | Verified (FR-3 references these labels) |
| `create-study-modal.tsx:267` — `watchedMaxTrials = form.watch('max_trials')` already in scope | Read file | Verified |
| `create-study-modal.tsx:269-282` — `activePreset` `useMemo` returns `'custom'` when no preset write matches | Read file | Verified |
| `create-study-modal.tsx:1257-1282` — Stop-condition preset button group, `role="group"` | Read file | Verified |
| `create-study-modal.tsx:1283-1318` — numeric-inputs grid follows the preset group | Read file | Verified |
| `create-study-modal.tsx:1107-1115` — existing inline-warning visual pattern (`text-amber-700 dark:text-amber-400`, `data-testid="cs-..."`) | Read file | Verified (FR-2 reuses this exact pattern) |
| `glossary.ts:172-176` — `study.preset` entry exists; adjacent space for new `study.sub_warmup_warning` key | Read file | Verified |
| `create-study-modal.stop-conditions.test.tsx` exists at 383 lines with `walkToStep5` / `getMaxTrialsInput` / `getPresetButton` helpers | Read file | Verified (FR-6 appends here) |
| `feat_study_convergence_indicator/idea.md` §"Open questions" #2 explicitly asks to absorb digest-note ownership | Read sibling idea | Verified (D-3 routes accordingly) |
| MVP2 is pre-`audit_log`; this feature mutates no state | CLAUDE.md + walk of §3 In scope | Verified (§6 Audit events N/A) |
| `infra/api-conventions.md` envelope unchanged; no new error code | §7.5 walk | Verified |
| CLAUDE.md Absolute Rules walked: #1 feature branch ✓, #2 secrets N/A, #3 LLM N/A, #4 adapter N/A, #5 migration N/A, #6 healthz N/A, #7 conventional commits ✓ (compliance at commit time), #8 model names N/A, #9 use `/impl-execute` ✓, #10 no secret exposure ✓, #11 healthz timeout N/A | Walk | Verified |
