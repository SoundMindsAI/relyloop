# Feature Specification — Study convergence indicator

**Date:** 2026-05-31
**Status:** Draft
**Owners:** Product: TBD · Engineering: TBD
**Related docs:**
- [`idea.md`](idea.md)
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)
- Shipped sibling: [`feat_study_sub_warmup_guard`](../../../implemented_features/2026_05_29_feat_study_sub_warmup_guard/feature_spec.md) — owns the preventive (pre-run) warning; this spec owns the corrective (post-run) verdict.
- Shipped sibling: [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) — owns the existing `ConfidenceShape` on `StudyDetail`, which already carries a *different* `ConvergenceRegime` (winner-timing classifier). Naming collision avoided via dedicated `ConvergenceVerdict` namespace (see §2 / §9).
- Co-shipping sibling on the same branch: [`feat_overnight_autopilot`](../feat_overnight_autopilot/feature_spec.md) — its `StudyChainLink` Pydantic model explicitly invites additive fields (§11 IA line: *"leave room in `links[]` for additive fields"*). The per-link `convergence_verdict` is the field that fills that slot.
- Shipped sibling: [`feat_auto_followup_studies`](../../../implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) — defines the lift-epsilon (`0.005`) currently inlined as a kwarg default at [`auto_followup.py:121`](../../../../../backend/app/domain/study/auto_followup.py#L121). This spec hoists it to a shared module-level constant.

---

## 1) Purpose

- **Problem:** A study's detail page shows `best_metric` + a trials table but gives the operator no on-screen signal about whether that `best_metric` represents a converged optimization or a premature stop. Under-budgeted studies (e.g., 12 trials, well below the TPE warmup floor of 50) look identical to fully-converged ones (300+ trials with a long flat tail). Operators can't tell whether the digest's `narrow` / `widen` followups are the intended next step or a misattribution covering for "you just stopped too early."
- **Outcome:** Every completed study carries a plain-language **convergence verdict** — `converged` / `still_improving` / `too_few_trials` — backed by a best-metric-so-far curve. The verdict is computed deterministically from the trials series, surfaced on the study detail page (badge + collapsible curve panel), threaded through the digest narrative (so the LLM frames "re-run with a larger budget" *before* narrow/widen when the verdict says so), and exposed on each link of an overnight chain (extending `StudyChainLink` so a chained run can flag "link 2 was still improving"). No new orchestration, no migration.
- **Non-goals:** No new optimizer signal, no Optuna-internal `_is_converged` coupling (D-1), no auto-cancel of a "still improving" study, no auto-enqueue of a re-run with a larger budget (recommendation only — operator clicks), no per-trial verdict (study-level only), no proposal-page surface (digest narrative carries the framing).

## 2) Current state audit

### Existing implementations

| Component | Path | Behavior / shape relevant to this feature |
|---|---|---|
| Trials model | [`backend/app/db/models/trial.py:57-123`](../../../../../backend/app/db/models/trial.py#L57-L123) | Each row has `id`, `study_id`, **`optuna_trial_number: int NOT NULL`** (the canonical "trial order within a study"; line 76), `primary_metric: float \| None`, `status: text CHECK IN ('complete','failed','pruned')`, `is_baseline: bool DEFAULT FALSE`. The trials_study_metric index covers `(study_id, primary_metric DESC NULLS LAST)`. **`is_baseline=TRUE` rows MUST be filtered out** of every aggregate read (per `feat_study_baseline_trial` FR-11) — the convergence series consumes Optuna trials only. |
| Trial repo | [`backend/app/db/repo/trial.py:83-91`](../../../../../backend/app/db/repo/trial.py#L83-L91) | `list_trials_for_study(db, study_id) -> Sequence[Trial]` returns all rows for a study (no baseline filter — caller is responsible). `aggregate_trials_summary(db, study_id)` returns `TrialsSummary(total, complete, failed, pruned, best_primary_metric)` — does NOT carry the ordered series needed for convergence. |
| StudyDetail Pydantic | [`backend/app/api/v1/schemas.py:793-824`](../../../../../backend/app/api/v1/schemas.py#L793-L824) | Already carries `trials_summary: TrialsSummaryShape` and `confidence: ConfidenceShape \| None`. **Adds `convergence: ConvergenceShape \| None` in this spec** (additive, optional, backward-compatible). |
| StudyDetail builder | [`backend/app/api/v1/studies.py:125-158`](../../../../../backend/app/api/v1/studies.py#L125-L158) | `_detail(db, row)` currently calls `repo.aggregate_trials_summary` + `fetch_study_confidence`. **Will also call `fetch_study_convergence` in this spec.** |
| Confidence-shape namespace (collision risk) | [`backend/app/domain/study/confidence.py:117`](../../../../../backend/app/domain/study/confidence.py#L117) | Already defines `ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]` for `feat_pr_metric_confidence`. That regime classifies **winner-trial-number timing** ("did the winner show up early or late?"), NOT whether the best-metric tail has plateaued. **This spec uses a distinct name — `ConvergenceVerdict`** (with values `converged` / `still_improving` / `too_few_trials`) — and a distinct module path (`backend/app/domain/study/convergence.py`, new) so both shapes can coexist on `StudyDetail` without semantic confusion. |
| Confidence-shape constant collision risk | [`backend/app/domain/study/confidence.py:102`](../../../../../backend/app/domain/study/confidence.py#L102) | Already defines `CONVERGENCE_MIN_COMPLETE: int = 3`. **This spec MUST NOT redefine that name.** New constants use the `CONVERGENCE_FLAT_*` prefix (§9). |
| Auto-followup lift epsilon (the value this spec reuses) | [`backend/app/domain/study/auto_followup.py:74`, `:121`](../../../../../backend/app/domain/study/auto_followup.py#L74) | The literal `0.005` appears as the default value of `ChainGateOutcome.epsilon` (line 74) and the default kwarg of `evaluate_chain_gate(..., epsilon=0.005, ...)` (line 121). **There is no hoisted module-level constant** — the spec calls for hoisting it to `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005` and importing it from this feature's `convergence.py` so the two epsilons cannot drift. |
| TPE warmup floor (the value this spec reuses) | [`backend/app/eval/optuna_runtime.py:39`](../../../../../backend/app/eval/optuna_runtime.py#L39) | Module-level constant `STUDIES_TPE_WARMUP_FLOOR: int = 50` (added by shipped `feat_study_sub_warmup_guard`). Already imported by the wizard's frontend mirror with a value-lock unit test at [`backend/tests/unit/eval/test_optuna_runtime.py:209`](../../../../../backend/tests/unit/eval/test_optuna_runtime.py#L209). **This spec imports the same constant — does not redefine it.** |
| Study detail page mount points | [`ui/src/app/studies/[id]/page.tsx:109-110`](../../../../../ui/src/app/studies/%5Bid%5D/page.tsx#L109-L110) | `<AutoFollowupChainPanel>` mounts at line 109, `<ConfidencePanel>` at line 110, `<TrialsCard>` at line 111. **`<ConvergencePanel>` mounts between `<ConfidencePanel>` and `<TrialsCard>`** so the verdict sits near the operator's "is this number trustworthy?" reasoning. |
| Digest prompt | [`backend/app/llm/digest_prompt.py:115-167`](../../../../../backend/app/llm/digest_prompt.py#L115-L167) | `render_digest_user_prompt` already accepts `confidence: dict \| None` (line 116). **Adds `convergence: dict \| None`** following the same `ConfidenceShape.model_dump()` pattern, threaded through the worker call site. |
| Digest model | [`backend/app/db/models/digest.py:62-74`](../../../../../backend/app/db/models/digest.py#L62-L74) | `suggested_followups: JSONB NOT NULL DEFAULT '[]'` carries `FollowupItem` entries (`{kind: 'narrow'|'widen'|'text', rationale: str, search_space: SearchSpace \| null}`). **No new digest column.** The "re-run with larger budget" surfacing is a *narrative* + *recommended_action* via the existing prose path — no new `FollowupItem.kind`. (Open question Q-1; recommended default is **No** — see §19.) |
| Recharts canonical use | [`ui/src/components/studies/`](../../../../../ui/src/components/studies/) | Recharts is the project's chart library (confirmed by parameter-importance + trial-scatter on the study detail page). The convergence curve reuses the same library + visual style (light grid, axis ticks, blue line). |
| Overnight autopilot's `StudyChainLink` | [`docs/00_overview/planned_features/02_mvp2/feat_overnight_autopilot/feature_spec.md`](../feat_overnight_autopilot/feature_spec.md) §8.3 (lines 248-263) | 12 fields, explicitly designed for additive extension (`§11 IA: "leave room in links[] for additive fields"`). **This spec adds a 13th field, `convergence_verdict: ConvergenceVerdict \| None`** — non-breaking additive. |
| Tooltip / glossary pattern | [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) (906 entries) + `<InfoTooltip glossaryKey="...">` | Established `short` (≤140 char) + `long` pattern. This spec adds three new keys: `convergence_verdict`, `convergence_curve`, `convergence_window`. |

### Navigation and link impact

No URL changes. The new panel mounts inside the existing `/studies/{id}` page between `<ConfidencePanel>` and `<TrialsCard>`. No redirects, no removed routes.

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (none) | (none) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/contract/test_studies_api_contract.py`](../../../../../backend/tests/contract/test_studies_api_contract.py) | `StudyDetail` response shape assertions | 1 | Extend the response-shape assertion to allow the new optional `convergence` key. Existing fields untouched. |
| [`backend/tests/unit/domain/study/test_confidence.py:605`](../../../../../backend/tests/unit/domain/study/test_confidence.py#L605) | `assert CONVERGENCE_MIN_COMPLETE == 3` | 1 | No change — that constant continues to mean what it meant. This spec's constants live in a different module (`convergence.py`). |
| Any wizard/digest/proposal Playwright spec that hits `/studies/[id]` | DOM assertions on study-detail body | TBD — grep at impl time | No required change: the new panel is additive. Specs that count panels by index instead of `data-testid` MUST be updated to anchor on `data-testid` (recorded as test debt — see §14). |
| Auto-followup chain panel test | [`ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`](../../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx) | Renders chain rows | ~4 | No change required for this spec — autopilot owns the panel rewrite. The new `convergence_verdict` field on each link is rendered by *autopilot's* extended panel (this spec ships the data; autopilot ships the rendering). |

### Existing behaviors affected by scope change

- **`StudyDetail` JSON shape grows by one optional field.** Current: ends at `confidence: ConfidenceShape | None`. New: also carries `convergence: ConvergenceShape | None`. Backward-compatible (additive, nullable). Decision needed: no.
- **Digest prompt grows by one optional template variable.** Current: `{confidence}` block. New: also `{convergence}` block. The existing Jinja `{% if convergence %}` pattern (mirroring `{% if confidence %}`) keeps degraded-mode prompts unchanged. Decision needed: no.
- **Digest narrative's framing of "next step" shifts when verdict is `still_improving` or `too_few_trials`.** Current: the LLM is free to pick narrow/widen as the natural next step. New: the system prompt is patched to instruct the LLM that, when `convergence.verdict in {still_improving, too_few_trials}`, the lead recommendation is "re-run with a larger budget" — narrow/widen are still emitted as `FollowupItem` entries but framed as secondary. Decision needed: no (idea Q-2 default — this feature owns the post-run corrective; warmup-guard owns the pre-run preventive; non-overlapping).
- **Chain panel per-link rendering grows by an optional badge.** Each `StudyChainLink` carries a new optional `convergence_verdict` field. Autopilot's already-spec'd panel rewrite renders it when present (one extra cell per row). Decision needed: no — coordinated via autopilot §11 IA's "leave room for additive fields."

---

## 3) Scope

### In scope (Phase 1 — the only phase shipped under this spec)

- **FR-1**: New pure-domain classifier `classify_convergence(complete_trials, *, direction)` in `backend/app/domain/study/convergence.py` returning a `ConvergenceShape` (verdict + curve + window + epsilon snapshot).
- **FR-2**: Hoist `0.005` from inline kwarg defaults in `backend/app/domain/study/auto_followup.py` to a shared module-level constant `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005`. The new `convergence.py` module imports and re-exposes the same constant under the name `CONVERGENCE_FLAT_EPSILON` — both paths point at the same literal so the digest-vs-chain-gate epsilons cannot drift.
- **FR-3**: Read-side aggregator `fetch_study_convergence(db, study_row) -> ConvergenceShape | None` in `backend/app/services/study_convergence.py` that loads non-baseline complete trials, sorts by `optuna_trial_number ASC`, computes the best-so-far curve, and calls the FR-1 classifier.
- **FR-4**: Extend `StudyDetail` Pydantic with `convergence: ConvergenceShape | None = None`. Wire `_detail()` to populate it.
- **FR-5**: Frontend `<ConvergencePanel>` component (verdict badge always visible; curve always available; panel `<details>`-style collapsible, collapsed-by-default when `verdict == "converged"`, expanded-by-default for `still_improving` / `too_few_trials`).
- **FR-6**: Thread `convergence` through the digest prompt + worker — `render_digest_user_prompt(... convergence=convergence_payload, ...)` — and patch the digest **system** prompt with the framing rule for `still_improving` / `too_few_trials`. No new digest column, no new `FollowupItem.kind`.
- **FR-7**: Extend the autopilot `StudyChainLink` Pydantic with an optional `convergence_verdict: ConvergenceVerdict | None = None` field, populated by autopilot's `/chain` endpoint using the same FR-3 aggregator per link. (Wiring lands in the autopilot PR; this spec owns the field definition + classifier + the integration contract; the actual `/chain` endpoint call site lives in the autopilot codebase per its §8.3.)
- **FR-8**: Three new glossary keys (`convergence_verdict`, `convergence_curve`, `convergence_window`) with `short` (≤140 char) text per the existing pattern.
- **FR-9**: Operator-facing runbook entry under `docs/03_runbooks/` ("Interpreting the convergence verdict") covering all three verdicts + the "re-run with larger budget" copy.

### Out of scope

- Any change to the chaining engine (`evaluate_chain_gate`, `enqueue_followup_study`) beyond hoisting the epsilon literal to a named constant. The gate's behavior is byte-identical post-hoist.
- Any change to Optuna's sampler / pruner / warmup logic. The `STUDIES_TPE_WARMUP_FLOOR` constant is *read*, not modified.
- A new `FollowupItem.kind` for "re-run with larger budget." (Q-1 default — defer; the digest narrative + recommended_action prose carry the framing without a new wire enum.)
- Auto-cancel of a study mid-flight when the curve appears to still be climbing. The verdict is purely *post-completion* analysis; in-flight studies receive `verdict = null` (no premature judgment).
- A new endpoint. The verdict ships embedded in the existing `GET /api/v1/studies/{id}` response; no new route.
- A migration. The feature reads existing columns only (`trials.optuna_trial_number`, `trials.primary_metric`, `trials.status`, `trials.is_baseline`, `studies.objective`).
- Auto-suggested re-run study creation (a "Re-run with Standard budget" button that POSTs a child study). Reserved for a later feature; the digest narrative tells the operator what to do but does not do it.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` — confirmed by inspection of [`backend/app/api/v1/studies.py:199-723`](../../../../../backend/app/api/v1/studies.py#L199-L723). No new endpoint introduced; the convergence payload rides inside existing `GET /api/v1/studies/{id}`.
- **Router for this feature's payload:** [`backend/app/api/v1/studies.py`](../../../../../backend/app/api/v1/studies.py) (existing `_detail` builder).
- **HTTP methods:** N/A — no new endpoint.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — confirmed against the `_err` helper at [`studies.py:80-84`](../../../../../backend/app/api/v1/studies.py#L80-L84). No new error codes introduced; the existing `STUDY_NOT_FOUND` (404) covers the only failure path.
- **Auth error shape:** N/A — MVP2 ships no auth surface.

### Phase boundaries

Single-phase. No deferred phases. The runbook entry, glossary keys, classifier, panel, digest threading, and autopilot field extension all ship together. (Rationale: every piece is small; splitting them would land a verdict computation with no surface, or a surface with no data — neither delivers operator value.)

**Deferred phase tracking:** No `phase2_idea.md` needed — single-phase spec.

---

## 4) Product principles and constraints

- **Determinism over signal.** The verdict is a closed-form function of `(complete_trials, direction, CONVERGENCE_FLAT_EPSILON, CONVERGENCE_FLAT_WINDOW, STUDIES_TPE_WARMUP_FLOOR)`. Same inputs MUST yield the same verdict on every call — no randomness, no Optuna-internal probes (D-1).
- **Honest "we don't know."** Below the warmup floor, the verdict MUST be `too_few_trials` regardless of the curve's apparent shape — TPE has not yet started exploiting and a flat tail at trial 8 is meaningless.
- **No regressions on existing surfaces.** `StudyDetail` consumers that ignore the new `convergence` key MUST continue to work unchanged (`Optional` + default `None`).
- **Direction-aware.** Minimize objectives flip "improved by more than epsilon" so `still_improving` means the same thing for both directions (lower-is-better OR higher-is-better).
- **Verdict copy is operator-facing.** The four surfaces (wire value, badge label, tooltip short text, digest lead sentence, runbook heading) MUST follow the canonical copy table below — same canonical mapping per verdict, not literal string equality across surfaces (Cycle-1 GPT-5.5 F13 fix; earlier draft over-claimed "same exact strings" which was already false given the labelled distinctions in §11):

  | Wire value (`ConvergenceVerdict`) | Badge label | Badge variant | Tooltip short (glossary `convergence_verdict.short` fragment) | Digest lead sentence (FR-6 framing) | Runbook section heading |
  |---|---|---|---|---|---|
  | `converged` | `Converged` | `success` (green) | "Converged = yes" | "This study converged — the digest's recommended config below is the result of a complete optimisation." | "What `converged` means and when to trust it" |
  | `still_improving` | `Still improving when it stopped` | `warning` (amber) | "Still improving = stopped early" | "This study was still improving when it stopped — re-run with a Deep (1000) budget to give the optimizer room to converge." | "What `still_improving` means and what to do next" |
  | `too_few_trials` | `Too few trials to tell` | `warning` (amber) | "Too few trials = ran below the 50-trial warmup floor" | "This study ran below the 50-trial TPE warmup floor — re-run with at least the Standard (200) budget." | "What `too_few_trials` means and the warmup-floor link" |
  | `null` (in-flight: `status IN ('queued','running')`) | `Verdict pending — still running` | `neutral` | n/a | n/a (digest only runs post-completion) | n/a |
  | `null` (terminal but `trials_summary.complete < 5`) | `Verdict pending — not enough trials yet` | `neutral` | n/a | n/a (no digest for studies with < 5 complete trials per existing zero-trials AC-2 path) | n/a |
  | `null` (terminal AND `trials_summary.complete >= 5` — invalid persisted direction OR classifier-exception fallback path; Cycle-3 GPT-5.5 F2 fix) | `Verdict unavailable` | `neutral` | n/a | n/a | n/a |

### Anti-patterns

- **Do not** depend on Optuna's `study._is_converged` or any other internal/private Optuna API. They are not part of the stable Optuna contract; drift risk on every Optuna upgrade. The trailing-window classifier is fully driven by `trials` table state we already persist.
- **Do not** redefine `ConvergenceRegime` / `CONVERGENCE_MIN_COMPLETE` / any other symbol that already exists in `confidence.py`. Use the distinct `ConvergenceVerdict` namespace (§9). Two unrelated convergence concepts on `StudyDetail` is bad enough; collapsing them under one name would cause silent miscalculations in confidence.
- **Do not** classify in-flight studies. `study.status in ('queued','running')` MUST yield `verdict = null` — no premature judgment, no auto-cancel.
- **Do not** include `is_baseline=TRUE` trials in the curve or the classification. The baseline trial is an off-band non-Optuna sample (per `feat_study_baseline_trial` FR-11) and would corrupt both the curve's `optuna_trial_number` axis (sentinel value `-1`) and the window math.
- **Do not** add a new `FollowupItem.kind` for "re-run." The discriminated union is consumed by the proposal-page renderer and the search-space transform helper; a new kind would cascade through both. The digest's narrative + a top-of-narrative recommendation line is sufficient (and matches the warmup-guard's precedent of "framing only, no new control surface").
- **Do not** silently inline another `0.005` literal anywhere. The epsilon MUST be imported from `backend/app/domain/study/auto_followup.py::AUTO_FOLLOWUP_LIFT_EPSILON` (or re-exported `convergence.py::CONVERGENCE_FLAT_EPSILON`). A grep guard test (§14) asserts no other module declares a bare `0.005` in pursuit of a convergence-or-lift threshold.
- **Do not** wire the digest re-run framing through `suggested_followups` JSONB. That column's discriminated union doesn't carry "re-run with budget X" — the framing belongs in `narrative` prose + the LLM-authored lead line, both of which already ship.

## 5) Assumptions and dependencies

- Dependency: `feat_overnight_autopilot` (sibling, idea-stage in same branch)
  - Why required: this spec extends autopilot's `StudyChainLink` Pydantic model with a `convergence_verdict` field. The autopilot spec already authorizes additive fields (§11 IA) so the dependency is **soft** at design time but **hard at integration time**: the field MUST land in the same model the autopilot feature ships. Recommended landing order: autopilot's `/chain` endpoint + `StudyChainLink` ships first; this feature's PR adds the `convergence_verdict` field + the per-link populating call site. Both PRs are on the same branch sequence; this spec calls out the contract (additive optional field) so neither side surprises the other.
  - Status: planned (autopilot spec is written; this spec is being written now)
  - Risk if missing: low — the field is additive optional. If autopilot ships without it, this spec's PR adds it as a one-line schema change.
- Dependency: `feat_study_sub_warmup_guard` (shipped)
  - Why required: source-of-truth for the `STUDIES_TPE_WARMUP_FLOOR = 50` constant. This spec imports it; does not redefine.
  - Status: shipped 2026-05-29 (PR #316)
  - Risk if missing: N/A.
- Dependency: `feat_auto_followup_studies` (shipped)
  - Why required: source-of-truth for the `0.005` lift epsilon value (and `_direction_normalized_lift` helper). This spec hoists the literal to a named constant inside the same module.
  - Status: shipped 2026-05-24
  - Risk if missing: N/A.
- Dependency: `feat_pr_metric_confidence` (shipped)
  - Why required: shipped the existing `ConvergenceRegime` / `CONVERGENCE_MIN_COMPLETE` symbols this spec must NOT collide with. Also shipped the precedent for `confidence:` on `StudyDetail` (this spec uses the same shape for `convergence:`).
  - Status: shipped 2026-05-21
  - Risk if missing: N/A.

## 6) Actors and roles

- Primary actor(s): **Relevance engineer** (per CLAUDE.md §Personas) — runs studies, reviews the digest, decides whether to ship the recommended config or re-run with a larger budget.
- Role model: **N/A — single-tenant install, no auth surface** (per the canonical release matrix; RelyLoop is single-tenant through GA v1).
- Permission boundaries: N/A — no auth surface.

### Authorization

**N/A — single-tenant install, no auth surface.**

### Audit events

**N/A — `audit_log` lands at MVP3** per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). This feature adds no state-mutating endpoint or service function — the verdict is computed read-side from existing trials. The digest worker (which DOES mutate state, by writing the `digests` row) already runs pre-MVP3 and gets its audit instrumentation when the table lands; this spec's only delta to the worker is passing one extra optional argument to the prompt renderer.

---

## 7) Functional requirements

### FR-1: Pure-domain convergence classifier
- Requirement:
  - The system **MUST** expose `classify_convergence(complete_trials: Sequence[Trial], *, direction: Literal["maximize","minimize"]) -> ConvergenceShape | None` in `backend/app/domain/study/convergence.py`. Return type is `ConvergenceShape | None` (Cycle-1 GPT-5.5 F1 fix — `ConvergenceShape.verdict` is non-nullable, so the "too few rows to classify" branch is communicated by returning `None`, not by an internal `verdict=None`).
  - The function **MUST** be pure (no DB, no I/O, no async — per CLAUDE.md "Domain Layer").
  - The function **MUST** filter out `is_baseline == True` trials AND `status != 'complete'` trials AND `primary_metric IS NULL` rows before sorting (failed / pruned have no `primary_metric` to lean on; baseline rows carry sentinel `optuna_trial_number = -1`).
  - The function **MUST** sort by `optuna_trial_number ASC`, then build a best-so-far curve via running max (maximize) or running min (minimize) over `primary_metric`.
  - The function **MUST** return `None` when the filtered set has fewer than `CONVERGENCE_FLAT_MIN_COMPLETE` (defined §9, value 5) trials. `None` is the "we genuinely don't have enough rows to look at" branch; `too_few_trials` is the distinct "≥5 but <50" branch (handled by §9's decision matrix when the function does return a shape).
  - When the function returns a `ConvergenceShape`, every sub-field MUST be populated (no nullable sub-fields beyond what §8.3 declares nullable).
  - The function **MUST** apply the verdict rules in §9.
- Notes: The function returns shape, not status code. The HTTP layer's "did the study exist" check (404 STUDY_NOT_FOUND) is unchanged.

### FR-2: Shared lift / convergence epsilon constant
- Requirement:
  - The system **MUST** hoist the literal `0.005` currently inlined at [`backend/app/domain/study/auto_followup.py:74` (ChainGateOutcome default) and `:121` (evaluate_chain_gate kwarg default)](../../../../../backend/app/domain/study/auto_followup.py) into a new module-level constant `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005`.
  - The convergence module `convergence.py` **MUST** import and re-expose the same value as `CONVERGENCE_FLAT_EPSILON` via `from backend.app.domain.study.auto_followup import AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON`. Re-export only; no parallel literal definition.
  - A value-lock unit test **MUST** assert `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` AND `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` (value equality; Cycle-1 GPT-5.5 F7 fix — Python object identity (`is`) is too fragile for numeric floats across reload boundaries / re-import paths). The structural guarantee — that `convergence.py` aliases rather than redeclares — is enforced by a separate AST/grep guard test that fails if any module file under `backend/app/` (outside `auto_followup.py`'s declaration line) contains a bare `0.005` literal in a context resembling a convergence/lift epsilon.
- Notes: This is the only mechanical change to `auto_followup.py`. The kwarg signature stays `epsilon: float = AUTO_FOLLOWUP_LIFT_EPSILON` so existing callers (and the chain-summary helper in the autopilot spec) keep working byte-for-byte.

### FR-3: Read-side aggregator
- Requirement:
  - The system **MUST** expose `async def fetch_study_convergence(db: AsyncSession, study_row: Study) -> ConvergenceShape | None` in `backend/app/services/study_convergence.py`.
  - The aggregator **MUST** load complete non-baseline trials via a **new dedicated repo helper** `list_complete_optuna_trials_for_study(db, study_id) -> Sequence[Trial]` in `backend/app/db/repo/trial.py` that filters DB-side on `status = 'complete' AND is_baseline = FALSE AND primary_metric IS NOT NULL` and orders by `optuna_trial_number ASC`. Cycle-1 GPT-5.5 F3 fix — pushing the filter into SQL keeps the perf claim honest (§13), avoids loading thousands of irrelevant rows, and removes the in-caller filtering footgun the existing `list_trials_for_study` would otherwise force.
  - The aggregator **MUST** read direction via a helper `_resolve_direction(study_row.objective) -> Literal["maximize","minimize"] | None` that returns `"maximize"` when the key is absent (matching the precedent at [`studies.py:165`](../../../../../backend/app/api/v1/studies.py#L165)), the exact value for `"maximize"` / `"minimize"`, and `None` for any other string. When the helper returns `None`, the aggregator **MUST** log a single structured WARN (`event_type="convergence_invalid_direction"`, `study_id=`, `raw_direction=`) and return `None` — degrading gracefully without crashing the underlying detail GET (Cycle-1 GPT-5.5 F5 fix).
  - The aggregator **MUST** return `None` when `study_row.status in ("queued","running")` — no in-flight classification (per Anti-pattern §4).
  - The aggregator **MUST** call `classify_convergence(...)` and return its result for terminal studies.
  - The aggregator **MUST** wrap the classifier call in `try/except Exception` and on any caught exception emit a structured WARN (`event_type="convergence_classifier_exception"`, `study_id=`, `exception_type=`, `exception_str=`) and return `None`. The underlying `GET /api/v1/studies/{id}` **MUST NOT** 500 from a classifier bug (Cycle-1 GPT-5.5 F4 fix — single-source error handling).
- Notes: The service layer split (aggregator vs. classifier) mirrors the precedent at [`backend/app/services/study_confidence.py`](../../../../../backend/app/services/study_confidence.py). The new repo helper is additive — `list_trials_for_study` remains unchanged.

### FR-4: StudyDetail integration
- Requirement:
  - The Pydantic model `StudyDetail` at [`schemas.py:793`](../../../../../backend/app/api/v1/schemas.py#L793) **MUST** gain a new optional field `convergence: ConvergenceShape | None = None` immediately after the existing `confidence` field.
  - The `_detail` builder at [`studies.py:125`](../../../../../backend/app/api/v1/studies.py#L125) **MUST** call `fetch_study_convergence(db, row)` and pass the result as the new field.
  - Both the `GET /api/v1/studies/{id}` response AND the `POST /api/v1/studies/{id}/cancel` response (which already reuses `_detail`) **MUST** carry the new field with no further wiring.
- Notes: Backward-compatible (additive, default-None). No new error codes.

### FR-5: ConvergencePanel frontend
- Requirement:
  - The system **MUST** ship a new React component `<ConvergencePanel convergence={...} studyStatus={...} trialsSummary={...} />` at `ui/src/components/studies/convergence-panel.tsx` consuming the `ConvergenceShape` payload plus the parent study's `status` (StudyStatusWire) and `trials_summary` (for the complete-trial count). The two extra props are required because the spec's canonical copy table (§4) distinguishes two `null` cases (`"Verdict pending — still running"` for in-flight vs. `"Verdict pending — not enough trials yet"` for terminal-but-`<5`-complete), and the payload's `convergence === null` alone can't disambiguate them. (Cycle-2 GPT-5.5 F4 fix.)
  - The component **MUST** render a verdict badge (always visible) labeled per the §11 mapping table (`Converged` / `Still improving` / `Too few trials to tell` / "Verdict pending — still running" for `null`).
  - The component **MUST** render the curve inside a `<details>`/`<summary>` (or equivalent collapsible) element that is **collapsed by default** when `verdict === "converged"` and **expanded by default** otherwise (including `null` — keep operator-visible cues for in-flight or low-data cases).
  - The curve **MUST** be a Recharts `<LineChart>` plotting `optuna_trial_number` on X vs. best-so-far metric on Y, with the verdict's classification window highlighted (right-most N trials in a faint shaded band) when `verdict in {converged, still_improving}`.
  - The panel **MUST** mount between `<ConfidencePanel>` and `<TrialsCard>` at [`ui/src/app/studies/[id]/page.tsx`](../../../../../ui/src/app/studies/%5Bid%5D/page.tsx).
  - When `study.convergence === null` (e.g., in-flight, or completed with `< CONVERGENCE_FLAT_MIN_COMPLETE` trials), the panel **MUST** render the badge with the "Verdict pending" copy and an em-dash for the curve area — the panel does NOT vanish (consistent UX surface).
  - All option-list values surfaced as `data-testid` / `aria-label` attributes **MUST** be sourced from a `CONVERGENCE_VERDICT_VALUES` exported `as const` array in `ui/src/lib/enums.ts` with the `// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict` discipline comment (per CLAUDE.md "Enumerated Value Contract Discipline").
- Notes: No URL routing change; no navigation. The panel uses existing `<Card>` / `<CardHeader>` / `<CardContent>` shadcn primitives.

### FR-6: Digest narrative threading
- Requirement:
  - The digest worker call site at [`backend/workers/digest.py`](../../../../../backend/workers/digest.py) **MUST** call `fetch_study_convergence(db, study_row)` and pass the result, serialized via `ConvergenceShape.model_dump()`, to `render_digest_user_prompt(..., convergence=...)`.
  - The `render_digest_user_prompt` signature at [`digest_prompt.py:115`](../../../../../backend/app/llm/digest_prompt.py#L115) **MUST** gain `convergence: dict | None = None` matching the existing `confidence` parameter pattern.
  - The Jinja user template at [`prompts/digest_narrative.user.jinja`](../../../../../prompts/digest_narrative.user.jinja) **MUST** gain a `{% if convergence %}<convergence>...</convergence>{% endif %}` block following the existing `{% if confidence %}` precedent.
  - The system prompt file at [`prompts/digest_narrative.system.md`](../../../../../prompts/digest_narrative.system.md) **MUST** gain the framing rule: "When `<convergence><verdict>` is `still_improving` or `too_few_trials`, lead the recommendation with 're-run with a larger trial budget' and frame any `narrow` / `widen` followups as secondary."
  - The worker **MUST** stamp `digests.generated_by` per the existing convention (no change to that field).
- Notes: Digest re-generation (the runbook escape hatch) automatically picks up the new framing — no special migration. Studies whose digests were generated *before* this feature shipped continue to display their original narrative; no backfill.

### FR-7: Autopilot chain-link integration (soft contract — implementation lives in the autopilot PR)
- Requirement:
  - This spec **MUST** export `ConvergenceVerdict` (the `Literal["converged","still_improving","too_few_trials"]` symbol) from `backend/app/domain/study/convergence.py` so any downstream feature can type-import it.
  - This spec **MUST** document the soft contract that the autopilot Pydantic model `StudyChainLink` adds an additive optional `convergence_verdict: ConvergenceVerdict | None = None` field, populated by autopilot's `/chain` endpoint per-link assembly loop calling `fetch_study_convergence(db, link_study_row)` and projecting `.verdict` into the per-link slot. (When the link is in-flight or sub-MIN, the projected value is `null` — same semantics as for the standalone study-detail surface.)
  - This spec's PR **MUST NOT** itself wire the autopilot `/chain` endpoint or modify `StudyChainLink`. That wiring lives in the autopilot PR. AC-16 (the integration assertion) is therefore **conditional** — see §12 AC-16 for the gating rule (Cycle-1 GPT-5.5 F10 fix — earlier draft mis-assigned AC-16 to this spec's CI lane and would have blocked merge on a dependency that may land in either order).
- Notes: Without this split, this spec's PR couldn't pass CI if autopilot lands second (the autopilot endpoint wouldn't exist for AC-16 to assert against). With this split, the spec ships a documented contract + the building blocks (`ConvergenceVerdict` symbol, `fetch_study_convergence` helper) and the autopilot PR consumes them in its own CI lane.

### FR-8: Glossary keys
- Requirement:
  - The system **MUST** add three new glossary keys to [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) with `short` text ≤140 chars each (Cycle-2 GPT-5.5 F6 fix — the cycle-1 suggested copies all exceeded 140 chars; shortened versions below all fit):
    - `convergence_verdict` — used by the panel's verdict-badge `<InfoTooltip>`. Suggested copy (132 chars): *"Did this study's metric flatten before stopping? Converged = yes; Still improving = stopped early; Too few trials = below warmup."*
    - `convergence_curve` — used by the panel's curve-section header `<InfoTooltip>`. Suggested copy (130 chars): *"Best metric seen so far at each trial. Flat right edge = plateaued; rising right edge = still room to improve."*
    - `convergence_window` — used by the panel's badge subscript / aria-label. Suggested copy (138 chars): *"The verdict looks at the last N trials. N defaults to 20, clamped to max(5, total // 5) so very short studies don't false-positive."*
  - Any explanatory detail that doesn't fit in 140 chars MUST live in the optional `long` field or the FR-9 runbook, not the `short` field.
  - Each key **MUST** follow the existing two-shape pattern (object with `short` field; `long` optional).
- Notes: The "Learn more" link for `convergence_verdict` MUST point at the new runbook from FR-9.

### FR-9: Runbook entry
- Requirement:
  - The system **MUST** add `docs/03_runbooks/convergence-verdict.md` covering:
    - What each verdict means.
    - How the classifier works (one-paragraph plain-language description; not the algorithm).
    - The "re-run with larger budget" recommended action — including the exact wizard preset (`Standard (200 trials)` or `Deep (1000)`) the operator should pick.
    - Troubleshooting: noisy tail mis-classifying as "Still improving" — how to use the curve to verify.
  - The runbook **MUST** be linked from CLAUDE.md "Key Runbooks" table.
- Notes: Runbook is operator-facing, not API documentation; the doc updates table in §15 lists the architecture/data-model patches separately.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints.** The convergence payload is embedded in the existing `GET /api/v1/studies/{id}` and `POST /api/v1/studies/{id}/cancel` responses (both reuse the `_detail` builder).

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}` | (existing) — response gains `convergence: ConvergenceShape \| None` | `STUDY_NOT_FOUND` (404) — unchanged |
| `POST` | `/api/v1/studies/{id}/cancel` | (existing) — response gains `convergence: ConvergenceShape \| None` | unchanged |

### 8.2 Contract rules

- The `convergence` field **MUST** be omitted from request payloads (it's read-only output).
- The `convergence` field **MUST** be `null` for any study with `status in ('queued','running')`.
- The `convergence` field **MUST** be `null` when fewer than `CONVERGENCE_FLAT_MIN_COMPLETE` (§9) complete non-baseline trials exist.
- Otherwise, the field **MUST** be a complete `ConvergenceShape` object (all sub-fields populated per §9).

### 8.3 Response schema

**New nested Pydantic model `ConvergenceShape` (lives in `backend/app/domain/study/convergence.py`, re-exported via `schemas.py` per the `ConfidenceShape` precedent):**

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `verdict` | `ConvergenceVerdict` (`Literal["converged","still_improving","too_few_trials"]`) | no | Top-level operator-facing classification. |
| `direction` | `Literal["maximize","minimize"]` | no | Echoes `study.objective.direction` (default `"maximize"`). |
| `window_size` | `int` | no | Effective window the classifier used — `max(5, total_complete_trials // 5)` clamped at `CONVERGENCE_FLAT_WINDOW` (§9). |
| `epsilon` | `float` | no | Echoes `CONVERGENCE_FLAT_EPSILON` (the value at compute-time, snapshot for audit). |
| `warmup_floor` | `int` | no | Echoes `STUDIES_TPE_WARMUP_FLOOR` (the value at compute-time). |
| `total_complete_trials` | `int` | no | Count of `status='complete' AND is_baseline=False` rows fed to the classifier. |
| `best_so_far_curve` | `list[CurvePoint]` | no | Ordered list of `{trial_number: int, best_so_far: float}` — one entry per complete non-baseline trial. Length always `>= CONVERGENCE_FLAT_MIN_COMPLETE` (5) because no `ConvergenceShape` is emitted below that threshold (Cycle-1 GPT-5.5 F2 fix — earlier draft incorrectly described an "empty curve" case that the contract makes impossible). |
| `improvement_in_window` | `float` | no | Direction-normalized improvement of `best_so_far[-1] - best_so_far[-window_size]`. Always `≥ 0` post-normalization. `0.0` when `total_complete_trials < window_size + 1`. |

**Nested `CurvePoint`:**

| Field | Type | Notes |
|---|---|---|
| `trial_number` | `int` | `optuna_trial_number` — never `-1` (baseline rows filtered). |
| `best_so_far` | `float` | Running max (maximize) or running min (minimize) of `primary_metric`. |

### 8.4 Response examples

Success — a fully-converged study (verdict shown nested inside `StudyDetail`):

```json
{
  "id": "01890000-0000-7000-8000-000000000041",
  "name": "ecommerce-q3 v1",
  "status": "completed",
  "best_metric": 0.7421,
  "trials_summary": { "total": 280, "complete": 275, "failed": 3, "pruned": 2, "best_primary_metric": 0.7421 },
  "confidence": { "...": "elided" },
  "convergence": {
    "verdict": "converged",
    "direction": "maximize",
    "window_size": 20,
    "epsilon": 0.005,
    "warmup_floor": 50,
    "total_complete_trials": 275,
    "improvement_in_window": 0.0008,
    "best_so_far_curve": [
      { "trial_number": 0, "best_so_far": 0.6201 },
      { "trial_number": 1, "best_so_far": 0.6201 },
      "...",
      { "trial_number": 274, "best_so_far": 0.7421 }
    ]
  }
}
```

(`"..."` only shown here for readability; the wire response is the full curve.)

Success — a still-improving study:

```json
{
  "convergence": {
    "verdict": "still_improving",
    "direction": "maximize",
    "window_size": 20,
    "epsilon": 0.005,
    "warmup_floor": 50,
    "total_complete_trials": 130,
    "improvement_in_window": 0.0214,
    "best_so_far_curve": ["..."]
  }
}
```

Success — too few trials (12 trials; window clamped to `max(5, 12 // 5) == 5`; improvement computed against the window per §9 — note this is the actual computed value, not `0.0`):

```json
{
  "convergence": {
    "verdict": "too_few_trials",
    "direction": "maximize",
    "window_size": 5,
    "epsilon": 0.005,
    "warmup_floor": 50,
    "total_complete_trials": 12,
    "improvement_in_window": 0.0319,
    "best_so_far_curve": [
      { "trial_number": 0, "best_so_far": 0.4101 },
      { "trial_number": 1, "best_so_far": 0.4101 },
      "...",
      { "trial_number": 7, "best_so_far": 0.5201 },
      { "trial_number": 8, "best_so_far": 0.5320 },
      "...",
      { "trial_number": 11, "best_so_far": 0.5520 }
    ]
  }
}
```

(`improvement_in_window = curve[-1].best_so_far - curve[-5].best_so_far = 0.5520 - 0.5201 = 0.0319`; Cycle-2 GPT-5.5 F3 cleanup — earlier draft incorrectly showed `0.0` here.)

Success — null (in-flight or no usable trials):

```json
{
  "status": "running",
  "convergence": null
}
```

Non-auth failure example (unchanged — only the existing `STUDY_NOT_FOUND`):

```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01890000-0000-7000-8000-deadbeef0000 not found",
    "retryable": false
  }
}
```

Auth failure example: **N/A** — MVP2 ships no auth surface.

### 8.5 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `convergence.verdict` | `converged`, `still_improving`, `too_few_trials` | `backend/app/domain/study/convergence.py` — `ConvergenceVerdict = Literal["converged", "still_improving", "too_few_trials"]`. Cite as `// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict` in `ui/src/lib/enums.ts`. | `<ConvergencePanel>` badge mapping; `data-testid="cs-convergence-verdict"` attribute; runbook FR-9. |
| `convergence.direction` | `maximize`, `minimize` | Existing — `Study.objective['direction']` (defaulting to `"maximize"` per [`studies.py:165`](../../../../../backend/app/api/v1/studies.py#L165)). | `<ConvergencePanel>` sign-flip helper for `improvement_in_window` display. |
| `StudyChainLink.convergence_verdict` (FR-7) | same as above, plus `null` | Same `ConvergenceVerdict` symbol — re-used. | Autopilot chain-summary panel per-link cell. |

### 8.6 Error code catalog

This feature introduces **no new error codes** AND does not change any existing failure path on the affected endpoints. The existing `STUDY_NOT_FOUND` (404) on `GET /api/v1/studies/{id}`, the cancel endpoint's `InvalidStateTransition` (terminal-status cancel rejection), and any other pre-existing failure modes continue to behave exactly as today. Any classifier exception (e.g., a programmer bug producing an unexpected Literal value) is caught by the FR-3 aggregator's `try/except`, emits a structured WARN, and is converted to a `null` `convergence` field — the underlying GET continues to succeed. (Cycle-2 GPT-5.5 F7 cleanup — earlier draft over-claimed "only failure path is STUDY_NOT_FOUND" across both endpoints; the cancel endpoint has additional pre-existing failure modes this feature doesn't touch.)

## 9) Data model and state transitions

### New/changed entities

**No schema changes. No migration.**

The aggregator reads existing columns only:

- From `trials`: `id`, `study_id`, `optuna_trial_number`, `primary_metric`, `status`, `is_baseline`. All exist and ship via the model at [`backend/app/db/models/trial.py:57-123`](../../../../../backend/app/db/models/trial.py#L57-L123).
- From `studies`: `id`, `status`, `objective` (for `direction`). All exist.

**New domain symbols** (live in `backend/app/domain/study/convergence.py` — a new file, no schema delta):

```python
# convergence.py — pure domain (no DB, no I/O)
from backend.app.domain.study.auto_followup import AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON
from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR

CONVERGENCE_FLAT_WINDOW: int = 20
CONVERGENCE_FLAT_MIN_COMPLETE: int = 5  # below this the verdict is null, not "too_few_trials"
ConvergenceVerdict = Literal["converged", "still_improving", "too_few_trials"]
```

**Modified module: `backend/app/domain/study/auto_followup.py`** (FR-2 mechanical change only):

- Hoist the literal `0.005` into a new module-level constant `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005` above the `ChainGateOutcome` dataclass.
- Update `ChainGateOutcome.epsilon` default from `0.005` to `AUTO_FOLLOWUP_LIFT_EPSILON`.
- Update `evaluate_chain_gate(..., epsilon=0.005, ...)` default from `0.005` to `AUTO_FOLLOWUP_LIFT_EPSILON`.
- No behavioral change. All existing tests stay green.

### Required invariants

- The classifier **MUST** return identical results for byte-identical inputs (closed-form, no randomness, no time-dependence).
- The classifier **MUST** be called only on terminal studies (`status NOT IN ('queued','running')`); the aggregator (FR-3) is the only entry point that enforces this.
- The curve **MUST** be monotonic non-decreasing for `direction='maximize'` (`best_so_far[i+1] >= best_so_far[i]`) and monotonic non-increasing for `direction='minimize'`. Enforced by the running-max/min construction; asserted by a unit test.
- `improvement_in_window` **MUST** be `>= 0` after direction normalization. Enforced by `abs()` and direction sign-flip in the classifier; asserted by a unit test.
- The convergence epsilon (`CONVERGENCE_FLAT_EPSILON`) and the auto-followup lift epsilon (`AUTO_FOLLOWUP_LIFT_EPSILON`) **MUST** compare equal by value AND `convergence.py` **MUST** structurally alias (import-rename) the value from `auto_followup.py` — enforced by FR-2's import pattern + a value-equality assertion + the AST/grep guard. (Cycle-2 GPT-5.5 F1 cleanup — removed the residual "same Python object" language carried over from the cycle-0 draft; identity-check approach was retired in cycle 1.)
- `is_baseline=True` trials **MUST NOT** appear in the curve or count toward `total_complete_trials`. Asserted by a unit test using a mixed trial set.

### State transitions

The verdict is a function of state, not a state itself. The closed-form decision matrix (evaluated in order, first match wins):

| Condition (in order) | Resulting behavior |
|---|---|
| `study.status IN ('queued','running')` | aggregator returns `None` (short-circuits; classifier never invoked). |
| `total_complete_trials < CONVERGENCE_FLAT_MIN_COMPLETE` (5) | classifier returns `None` (single source of truth — FR-1). The aggregator's role is to delegate; the classifier is the only place this branch is implemented. (Cycle-2 GPT-5.5 F2 cleanup — earlier draft duplicated the check across both layers.) |
| `total_complete_trials < STUDIES_TPE_WARMUP_FLOOR` (50) | classifier returns `ConvergenceShape(verdict="too_few_trials", ...)`. |
| `improvement_in_window <= CONVERGENCE_FLAT_EPSILON` (0.005) — where `window_size = clamp(max(5, total_complete_trials // 5), upper=CONVERGENCE_FLAT_WINDOW)` | classifier returns `ConvergenceShape(verdict="converged", ...)`. |
| Otherwise | classifier returns `ConvergenceShape(verdict="still_improving", ...)`. |

**Window-indexing semantic (Cycle-2 GPT-5.5 F3 lock):** `window_size` counts plotted points. The look-back index is `curve[-window_size]` — i.e., the point exactly `window_size` positions before the tail. `improvement_in_window` is therefore the gap between two specific plotted points, representing the cumulative improvement over `(window_size - 1)` trial-to-trial steps. Worked example: for `total_complete_trials = 130` and `window_size = 20`, the indices used are `curve[-1]` (the 130th point — `optuna_trial_number = 129`) and `curve[-20]` (the 111th point — `optuna_trial_number = 110`). The shaded band on the UI covers trials 110..129 inclusive (a 20-trial window).

`improvement_in_window` is computed as:

- `maximize`: `curve[-1].best_so_far - curve[-window_size].best_so_far` (post-running-max, both values are non-decreasing → result is `>= 0`).
- `minimize`: `curve[-window_size].best_so_far - curve[-1].best_so_far` (sign-flipped so positive = "better than window-start").

**Boundary case — `len(curve) == window_size`:** `curve[-window_size]` is `curve[0]`; the improvement is computed against the very first plotted point (the full curve span). No special-case logic. (Cycle-2 GPT-5.5 F3 cleanup — removed the earlier "wraps at index 0 when `len < window_size + 1`, otherwise `0.0`" inconsistency. The window_size formula already clamps to `total_complete_trials // 5`'s minimum, so `len(curve) >= window_size` always holds when a `ConvergenceShape` is emitted.)

### Idempotency/replay behavior

The verdict is a deterministic function of persisted state. Re-rendering `GET /api/v1/studies/{id}` 10 times returns the byte-identical `convergence` payload. No replay surface.

## 10) Security, privacy, and compliance

- **Threats:**
  - The convergence payload exposes `best_so_far_curve` (up to thousands of points per study). Risk: payload size on the wire. Mitigated by the natural per-study bound (Optuna max trials ≤ `Deep (1000)` preset) and the fact that the data is already operator-accessible via `GET /api/v1/studies/{id}/trials`. Not a new exposure.
  - The digest LLM prompt now includes the verdict. Risk: prompt injection via study name. Mitigated by the existing prompt-construction pattern (verdict is a Literal pulled from server state, not from operator input).
- **Controls:** None new — single-tenant boundary unchanged.
- **Secrets/key handling:** N/A — no secrets touched.
- **Auditability:** N/A — `audit_log` lands at MVP3. The aggregator is read-only.
- **Data retention/deletion/export impact:** N/A — no new persisted state.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** `<ConvergencePanel>` mounts at `/studies/{id}` between `<ConfidencePanel>` (line 110) and `<TrialsCard>` (line 111) in [`page.tsx`](../../../../../ui/src/app/studies/%5Bid%5D/page.tsx). Same column, full width.
- **Labeling taxonomy:** Panel card title: `"Convergence"` (matches `"Confidence"` precedent above it). Collapsible toggle label: `"Show convergence curve"` (when collapsed) / `"Hide convergence curve"` (when expanded). **Verdict-mapped strings — wire value, badge label, badge variant, tooltip fragment, digest lead sentence, runbook heading — all sourced from the canonical copy table in §4** (single source of truth; do not duplicate the table here).
- **Content hierarchy:** Badge (top, always visible) → improvement-in-window line (`"Improved by 0.0008 in the last 20 trials"`) → collapsible curve section. Recharts chart fills the card width on expansion.
- **Progressive disclosure:** The panel is **collapsed by default for `converged`** (the badge alone is the answer) and **expanded by default for `still_improving`, `too_few_trials`, and `null`** (where seeing the curve aids interpretation). State is local to the component; not persisted across navigations (matches the existing `<ConfidencePanel>` pattern, which is also non-persistent).
- **Relationship to existing pages:** Sits alongside `<ConfidencePanel>` and `<DigestPanel>` — three lenses on the same study, no overlap. The verdict's "re-run with budget X" framing on the digest narrative ties them together at the prose level.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Panel card title `"Convergence"` | (short, FR-8) Did this study's metric flatten out before stopping? Converged = yes; Still improving = stopped early; Too few trials = ran below the 50-trial warmup floor. | hover/focus on info icon | right of title | `convergence_verdict` (NEW) |
| Verdict badge | (re-uses `convergence_verdict` tooltip) | hover/focus | inline | `convergence_verdict` |
| Curve section header (collapsible chevron + label) | (short, FR-8) Best metric seen so far at each trial. A flat right edge means the optimizer plateaued; a rising right edge means there was still room to improve. | hover/focus on info icon | right of label | `convergence_curve` (NEW) |
| `window_size` subscript on the improvement line | (short, FR-8) The verdict looks at the last N trials. N is normally 20, clamped to max(5, total_trials // 5) so very short studies don't false-positive. | hover/focus on info icon | inline | `convergence_window` (NEW) |

### Primary flows

1. **Converged study review.** Operator opens `/studies/{id}` for a 280-trial completed study → sees `Convergence` card with green `"Converged"` badge + collapsed curve + `"Improved by 0.0008 in the last 20 trials"` line → trusts the digest's narrow/widen followup → clicks through to the proposal → ships.
2. **Still-improving study review.** Operator opens `/studies/{id}` for a 130-trial completed study → sees amber `"Still improving when it stopped"` badge + **expanded** curve with a clearly rising right edge → reads the digest narrative whose lead recommendation is now `"re-run with Deep (1000)"` → creates a new study with the Deep preset rather than chasing narrow/widen.
3. **Sub-warmup study review.** Operator opens `/studies/{id}` for a 12-trial Custom-mode study → sees amber `"Too few trials to tell"` badge + expanded curve + digest narrative leading with `"re-run with at least Standard (200)"`. The `feat_study_sub_warmup_guard` preventive warning fired at create-time; the convergence verdict is the post-run confirmation that the warning was correct.
4. **In-flight study review.** Operator opens `/studies/{id}` while the study is `running` → sees neutral `"Verdict pending — still running"` badge → panel curve area shows em-dash. (No premature verdict.)
5. **Chain link review (autopilot integration, FR-7).** Operator opens `/studies/{any_chain_member_id}` next morning → autopilot chain panel summarises the chain; each link row carries a `convergence_verdict` cell (green tick for `converged`, amber dot for `still_improving` / `too_few_trials`, em-dash for `null`). Operator spots `"link 2 — still improving"` and considers a re-run of that link with a larger budget.

### Edge/error flows

- **Completed study with 4 complete trials.** `total_complete_trials < CONVERGENCE_FLAT_MIN_COMPLETE (5)` → aggregator returns `None` → panel shows `"Verdict pending — not enough trials yet"`. Distinguished from `too_few_trials` (which requires `>= 5` but `< 50`) so the panel doesn't lie about why it can't classify.
- **Completed study with only `is_baseline=True` rows.** After filtering, `total_complete_trials = 0` → aggregator returns `None` → panel shows `"Verdict pending — not enough trials yet"`. (Degenerate; should never occur in practice — the orchestrator persists at least one Optuna trial before terminal — but defensible.)
- **Completed study with `direction='minimize'` and noisy tail.** Classifier uses running min + sign-flipped improvement; same epsilon. Documented in the runbook with one concrete minimize example.
- **Completed study with `best_metric` set but every trial row has `primary_metric IS NULL`.** Should not happen (the orchestrator denormalises `best_metric` from `metrics[study.objective.metric]` and only when `primary_metric` is also set), but the classifier MUST defend: rows with `primary_metric IS NULL` are filtered from the curve before classification; if the curve ends up empty, aggregator returns `None`. No 500.
- **Completed but cancelled study.** `status = 'cancelled'` is terminal → classifier runs against whatever complete trials exist → may return any verdict (or `None` if too few). Runbook notes: `"cancelled studies are classified the same as completed — the badge tells you whether you cut things short or whether the optimizer was already done."`

### Recovery

If the verdict mis-classifies (e.g., a noisy tail flagged as `still_improving`), the operator's recourse is to inspect the curve, optionally compare against `<ConfidencePanel>`'s noise floor, and decide manually. No "force a verdict" API.

## 12) Given/When/Then acceptance criteria

### AC-1: Classifier — `converged` (FR-1)

- Given 275 complete non-baseline trials with `direction='maximize'`, sorted by `optuna_trial_number ASC`, where `primary_metric` rises from 0.62 to 0.74 over the first 50 trials and then stays within ±0.0005 of 0.7421 for trials 51–274
- When `classify_convergence(trials, direction='maximize')` is called
- Then the returned `ConvergenceShape` has `verdict == "converged"`, `window_size == 20`, `epsilon == 0.005`, `warmup_floor == 50`, `total_complete_trials == 275`, `improvement_in_window <= 0.005`, `best_so_far_curve[-1].best_so_far == 0.7421`.

### AC-2: Classifier — `still_improving` (FR-1)

- Given 130 complete non-baseline trials with `direction='maximize'`, where `best_so_far` at `optuna_trial_number = 110` is 0.55 and at `optuna_trial_number = 129` is 0.572 (i.e., `curve[-20].best_so_far == 0.55` and `curve[-1].best_so_far == 0.572`, per the §9 indexing semantic)
- When `classify_convergence(...)` is called
- Then the returned shape has `verdict == "still_improving"`, `total_complete_trials == 130`, `window_size == 20`, `improvement_in_window == 0.022` (> epsilon).

### AC-3: Classifier — `too_few_trials` (FR-1)

- Given 12 complete non-baseline trials with `direction='maximize'` (above MIN_COMPLETE but below the warmup floor)
- When `classify_convergence(...)` is called
- Then the returned shape has `verdict == "too_few_trials"`, `total_complete_trials == 12`, `window_size == max(5, 12 // 5) == 5`, regardless of how flat or steep the tail looks.

### AC-4: Aggregator returns `None` for in-flight study (FR-3)

- Given `study_row.status == 'running'` with 80 complete trials present
- When `fetch_study_convergence(db, study_row)` is called
- Then it returns `None`; the classifier is NOT invoked (asserted via a `unittest.mock.patch` spy in the integration test).

### AC-5: Aggregator returns `None` when too few rows (FR-3)

- Given `study_row.status == 'completed'` with 4 complete non-baseline trials
- When `fetch_study_convergence(db, study_row)` is called
- Then it returns `None`. `StudyDetail.convergence` is `null` on the wire.

### AC-6: Aggregator filters `is_baseline=True` trials (FR-1 + FR-3)

- Given a study with 50 Optuna trials + 1 baseline trial (51 rows total in `trials`)
- When the aggregator runs
- Then `ConvergenceShape.total_complete_trials == 50` (NOT 51) and `best_so_far_curve` contains no `trial_number == -1` entry. (The baseline row carries `optuna_trial_number = -1` per `feat_study_baseline_trial`.)

### AC-7: Direction-aware minimize (FR-1 + §9 invariants)

- Given 200 complete trials with `direction='minimize'`, where the running-min curve drops from 0.85 to 0.42 by trial 100 and stays within ±0.0003 of 0.42 for trials 100–199
- When `classify_convergence(trials, direction='minimize')` is called
- Then `verdict == "converged"`, `improvement_in_window` is `>= 0` (sign-flipped: `curve[-window].best_so_far - curve[-1].best_so_far`), the curve is monotonic non-increasing.

### AC-8: StudyDetail response carries the new field (FR-4)

- Given a completed study with 275 complete trials and a converged shape
- When `GET /api/v1/studies/{id}` is called
- Then HTTP `200` returns a JSON body whose top-level `convergence` key has `verdict: "converged"`, `direction`, `window_size: 20`, `epsilon: 0.005`, `warmup_floor: 50`, `total_complete_trials: 275`, `best_so_far_curve` (array of `{trial_number, best_so_far}` objects, length 275), `improvement_in_window` (float).

### AC-9: StudyDetail response carries `null` for in-flight (FR-4)

- Given `study.status == 'running'`
- When `GET /api/v1/studies/{id}` is called
- Then HTTP `200` returns `{"convergence": null, ...}` (the key is present, value is `null`).

### AC-10: Cancel endpoint also surfaces convergence on a successful running→cancelled transition (FR-4)

- Given a study with `status = 'running'` and 80 complete trials persisted (the orchestrator wrote each completed trial as it went)
- When the operator calls `POST /api/v1/studies/{id}/cancel`
- Then the cancel handler transitions the study to `status = 'cancelled'`, the `_detail` builder re-runs, and the response body carries `convergence` populated against the now-terminal study (the 80 complete trials feed the classifier — likely `still_improving` or `too_few_trials` depending on the curve).
- (Cycle-1 GPT-5.5 F6 fix — the earlier draft incorrectly assumed cancelling a completed study was idempotent; verifying against [`backend/app/services/study_state.py`](../../../../../backend/app/services/study_state.py) confirmed `cancel_study` raises `InvalidStateTransition` for terminal statuses, so this AC instead exercises the legitimate running→cancelled transition.)

### AC-11: Frontend renders verdict badge (FR-5)

- Given `study.convergence.verdict === "converged"` in TanStack Query cache
- When `<ConvergencePanel>` renders
- Then a `<Badge variant="success">Converged</Badge>` (or equivalent shadcn variant) is in the DOM with `data-testid="cs-convergence-verdict"` and the `aria-label` mirroring the verdict string. The curve section is collapsed (the `<details>` element has no `open` attribute).

### AC-12: Frontend renders expanded curve for `still_improving` (FR-5)

- Given `study.convergence.verdict === "still_improving"`
- When `<ConvergencePanel>` renders
- Then the `<details>` element has the `open` attribute (curve section is expanded by default).

### AC-13: Frontend renders pending verdict for in-flight (FR-5)

- Given `study.convergence === null` AND `study.status === 'running'`
- When `<ConvergencePanel convergence={null} studyStatus="running" trialsSummary={...} />` renders
- Then the badge shows `"Verdict pending — still running"`, the curve area shows an em-dash placeholder, no Recharts chart is mounted.

### AC-13b: Frontend renders pending verdict for terminal-but-too-few (FR-5)

- Given `study.convergence === null` AND `study.status === 'completed'` AND `study.trials_summary.complete === 4` (below MIN)
- When `<ConvergencePanel convergence={null} studyStatus="completed" trialsSummary={{complete: 4, ...}} />` renders
- Then the badge shows `"Verdict pending — not enough trials yet"` (not the in-flight variant), the curve area shows an em-dash placeholder, no Recharts chart is mounted. (Cycle-2 GPT-5.5 F4 — covers the second `null` case the canonical copy table distinguishes.)

### AC-13c: Frontend renders Verdict unavailable for terminal-with-enough-trials-but-null (FR-5)

- Given `study.convergence === null` AND `study.status === 'completed'` AND `study.trials_summary.complete === 100` (above MIN — so the null cause is invalid persisted direction OR a classifier-exception fallback from FR-3)
- When `<ConvergencePanel convergence={null} studyStatus="completed" trialsSummary={{complete: 100, ...}} />` renders
- Then the badge shows `"Verdict unavailable"` (third null-state variant per the §4 canonical copy table), the curve area shows an em-dash placeholder, no Recharts chart is mounted. (Cycle-3 GPT-5.5 F2 fix — the previous draft left the "terminal + ≥5 complete + null" case undefined, which would have rendered an undefined/misleading badge.)

### AC-14: Digest prompt receives convergence payload (FR-6)

- Given a completed study with `verdict == "still_improving"`
- When the digest worker enqueues its LLM call
- Then `render_digest_user_prompt(...)` is called with `convergence={"verdict":"still_improving", "direction":"maximize", "window_size":20, ...}` (asserted via a patch on `render_digest_user_prompt`), AND the rendered user prompt contains a `<convergence>` block with `<verdict>still_improving</verdict>`.

### AC-15: Digest system prompt carries the framing rule (FR-6)

- Given the digest system prompt file is loaded
- When the prompt string is asserted against
- Then it contains the substring `"still_improving"` AND the substring `"re-run with a larger trial budget"` (or the verbatim FR-6 framing rule, character-for-character).

### AC-16: Chain link carries convergence_verdict (FR-7) — CONDITIONAL ON AUTOPILOT PR

- Given a 3-link chain where link 1 converged, link 2 was still improving, link 3 is queued
- When `GET /api/v1/studies/{any_link_id}/chain` is called (the endpoint owned by `feat_overnight_autopilot`)
- Then `links[0].convergence_verdict == "converged"`, `links[1].convergence_verdict == "still_improving"`, `links[2].convergence_verdict == null`.
- **Conditional gating (Cycle-1 GPT-5.5 F10 fix):** this AC is asserted by autopilot's CI lane, not this spec's. This spec ships the `ConvergenceVerdict` type symbol + `fetch_study_convergence` helper; the autopilot PR consumes them and adds AC-16 to its own integration test suite. This spec's DoD §18 does NOT block on AC-16 passing in this spec's PR.

### AC-17: Lift epsilon hoist preserves chain-gate behavior (FR-2)

- Given the full existing `evaluate_chain_gate` test suite ([`backend/tests/unit/domain/study/test_auto_followup.py`](../../../../../backend/tests/unit/domain/study/) — confirm exact path at impl time)
- When the FR-2 hoist lands
- Then every existing test passes byte-for-byte (no behavioral change). A new test asserts `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` AND `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` (value equality; Cycle-1 GPT-5.5 F7 fix). A separate AST/grep guard test asserts no module file under `backend/app/` (outside `auto_followup.py`'s sole declaration line) contains a bare `0.005` literal in a context resembling a convergence/lift epsilon.

### AC-18: Enum discipline — value-lock test + discipline comment (CLAUDE.md "Enumerated Value Contract Discipline")

- Given `ui/src/lib/enums.ts` exports `CONVERGENCE_VERDICT_VALUES as const` with the discipline comment `// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict` above the array
- When a new value-lock vitest runs (`ui/src/__tests__/lib/enums-convergence-discipline.test.ts`)
- Then the test asserts `CONVERGENCE_VERDICT_VALUES.length === 3` AND the array values are exactly `["converged", "still_improving", "too_few_trials"]` in that order. A companion backend value-lock asserts the same on the Python `Literal` (Cycle-1 GPT-5.5 F12 fix — the earlier draft over-claimed that existing column/form-discipline guards would automatically catch inlined literals in arbitrary frontend files; that's only true for `*.column-config.{ts,tsx}` and form `*.tsx` files. The targeted value-lock test makes the contract enforceable without adding a new repo-wide AST guard.)

### AC-19: Runbook entry exists, is linked from CLAUDE.md, and is the glossary "Learn more" target (FR-8 + FR-9)

- Given the file `docs/03_runbooks/convergence-verdict.md` exists
- When CLAUDE.md "Key Runbooks" table is rendered
- Then it contains a row pointing at the runbook with the situation column reading `"Interpreting the convergence verdict"`.
- AND the `convergence_verdict` glossary entry in `ui/src/lib/glossary.ts` carries a `long` field or "Learn more" anchor whose href points at `/docs/03_runbooks/convergence-verdict.md` (or the equivalent rendered path) — asserted by a glossary unit test (Cycle-3 GPT-5.5 F4 fix — earlier draft required the link in FR-8 but had no AC to assert the wiring).

### AC-20: Chart accessibility label (FR-5 + §13 a11y)

- Given a converged study with `total_complete_trials = 275`, `window_size = 20`, `improvement_in_window = 0.0008`
- When `<ConvergencePanel>` mounts and the curve section is expanded
- Then the Recharts chart container's `aria-label` attribute MUST read exactly `"Convergence curve: converged after 275 trials; window 20; improvement 0.0008"` (or the equivalent template-substituted string per Cycle-1 GPT-5.5 F14 fix).

## 13) Non-functional requirements

- **Performance:** `fetch_study_convergence` MUST complete in `<= 50ms p99` for a 1000-trial study (the upper bound of the `Deep` preset). Achieved via the new repo helper `list_complete_optuna_trials_for_study` (FR-3) — a single SELECT that pushes `status = 'complete' AND is_baseline = FALSE AND primary_metric IS NOT NULL` into the WHERE clause and `ORDER BY optuna_trial_number ASC` into the SQL. The query is covered by the existing `trials.study_id` FK index; the row count is bounded by the `Deep (1000)` preset. The in-Python running-max over the returned rows is O(N) with N ≤ 1000. (Cycle-1 GPT-5.5 F3 fix — the earlier draft cited an index that ordered by `primary_metric DESC`, not by `optuna_trial_number`; the corrected design ships the explicit ORDER BY rather than depending on a covering index.)
- **Payload size:** The full curve at 1000 trials adds approximately 50–80 KB to the `StudyDetail` JSON response uncompressed (1000 × ~50 bytes per `{"trial_number":N,"best_so_far":0.xxxx}` entry including JSON syntactical overhead), reducing to ~10–20 KB after gzip (Cycle-1 GPT-5.5 F15 — the earlier 30 KB estimate undercounted key+syntactical bytes). Acceptable for MVP2 — the study-detail endpoint is operator-driven (one call per page view), not on any hot loop. The runbook (FR-9) documents the upper bound and notes that future endpoints which need only the verdict can read it from the projected per-link form on the chain endpoint instead.
- **Reliability:** A classifier exception MUST NOT 500 the underlying `GET /api/v1/studies/{id}` — `fetch_study_convergence` wraps the classifier call in a `try / except Exception` that logs WARN and returns `None`. Two separate tests cover the two distinct null-fallback paths (Cycle-3 GPT-5.5 F3 fix — earlier draft conflated them): (1) a malformed persisted `direction` exits via `_resolve_direction(...) -> None` and emits `event_type="convergence_invalid_direction"` *without* invoking the classifier; (2) a monkey-patched classifier raising `ValueError` exits via the `try/except` and emits `event_type="convergence_classifier_exception"`. Both ultimately return `convergence: null` on the wire.
- **Operability:** A single structured log line (`event_type="convergence_classified"`, `study_id=`, `verdict=`, `total_complete_trials=`, `window_size=`, `improvement_in_window=`) emits per successful aggregator call at DEBUG level (high-volume study-detail GETs would flood INFO). The two failure paths (`convergence_invalid_direction`, `convergence_classifier_exception`) emit at WARN level since they indicate either bad persisted data or a real bug.
- **Accessibility:** The verdict badge MUST have an `aria-label` mirroring the verdict copy (per AC-11). The collapsible curve section MUST use a native `<details>`/`<summary>` (or shadcn equivalent that preserves keyboard / screen-reader semantics). The Recharts chart container MUST have an `aria-label` describing the verdict + total_complete_trials + window_size + improvement_in_window (e.g., `aria-label="Convergence curve: converged after 275 trials; window 20; improvement 0.0008"`) so screen readers don't have to interpret the chart's visual band (Cycle-1 GPT-5.5 F14 fix).

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/domain/study/test_convergence.py`):**
  - All §9 decision-matrix branches (`converged`, `still_improving`, `too_few_trials`, `None`).
  - Direction-aware minimize.
  - `is_baseline=True` filtering (mixed set: Optuna trials + a baseline row carrying `optuna_trial_number=-1` should produce a curve that contains no `trial_number=-1` entry).
  - `primary_metric IS NULL` defensive filter.
  - Window clamp at very short studies — explicit cases at **N = 5, 7, 24, 49, 50, 51, 100, 200, 1000** trials (Cycle-1 GPT-5.5 F9 fix — boundary cases around the warmup floor + the realistic preset sizes catch the most likely operator-visible misclassifications).
  - **Slow-drift case:** 200 trials where each window-step gains 0.004 (just below epsilon) — verifies the verdict is `converged` and documents that the heuristic can swallow genuinely-slow improvement (Cycle-1 GPT-5.5 F8 fix). The runbook documents the limitation.
  - **Single-late-jump case:** 200 flat trials followed by 1 trial improving by 0.05 — verifies the verdict is `still_improving` (a single late lucky jump bumps it out of `converged`); documents that this is intentional (the operator should investigate).
  - **Noisy-tail case:** 100-trial baseline + 20 trials where each adds 0.001 noise around a fixed best — verifies the verdict is `converged` (improvement_in_window stays below epsilon).
  - Invalid `direction` (`"max"` / uppercase / empty string) → aggregator logs WARN + returns None (FR-3).
  - Value-lock test: `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` AND `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` (value equality).
  - Monotonicity invariant: every `best_so_far_curve` returned is monotonic in the right direction.
  - Grep/AST guard: no other module file under `backend/app/` (outside `auto_followup.py`'s sole declaration line) contains a bare `0.005` literal in a context that looks like a convergence/lift threshold. The test reads the repo and fails if a new bare literal appears.
- **Integration tests (`backend/tests/integration/test_study_convergence_integration.py`):**
  - Seed a study + N complete trials + 1 baseline row → `_detail()` returns the populated `convergence` field with the correct shape.
  - In-flight study → `convergence is None`.
  - Cancel endpoint surface (AC-10).
- **Contract tests (`backend/tests/contract/test_studies_api_contract.py` — extend the existing file):**
  - Assert `StudyDetail` JSON shape includes `convergence: object | null`.
  - Assert sub-fields match the §8.3 schema.
- **Frontend unit tests (`ui/src/__tests__/components/studies/convergence-panel.test.tsx`):**
  - Renders each verdict badge variant + label.
  - Curve section collapsed/expanded default per verdict.
  - `null` payload → "Verdict pending" path.
  - Recharts mock — assert curve data is fed to `<LineChart>` (not asserting visual pixels).
- **E2E tests (Playwright, real backend) — ONE lightweight smoke spec required** (Cycle-1 GPT-5.5 F11 fix; the earlier draft deferred too aggressively). The new spec at `ui/tests/e2e/convergence-panel.spec.ts` seeds a completed study via the API helpers (one converged shape + one still_improving shape, both with enough trials to clear MIN), navigates to `/studies/{id}` via real `page.goto()`, asserts the verdict badge text + `data-testid="cs-convergence-verdict"` are present in the rendered DOM, and asserts the `<details>` open state matches the spec (collapsed for `converged`, open for `still_improving`). NO `page.route()` mocking — backend wiring is what the smoke exists to validate. This is one spec, ~50 LOC of test, against the existing real-backend Playwright lane that `feat_studies_ui` ships.

## 15) Documentation update requirements

- `docs/01_architecture/` — patch `data-model.md` §"trials" with a one-line note that the convergence aggregator reads (no schema delta). Patch `ui-architecture.md` with the `<ConvergencePanel>` mount position.
- `docs/02_product/` — no patch (no new user story emerges; the existing study-lifecycle story implicitly covers this).
- `docs/03_runbooks/convergence-verdict.md` — new file (FR-9).
- `docs/04_security/` — no patch (no new threat surface).
- `docs/05_quality/testing.md` — no patch (existing test-layer convention covers the new tests; no new layer introduced).
- CLAUDE.md — add a row in the "Key Runbooks" table pointing at `convergence-verdict.md`.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The feature is additive and read-only — there is no risk-bearing rollout state. Operators see the new panel as soon as the PR merges.
- **Migration/backfill expectations:** **None.** No schema change. Existing study rows compute the verdict on first `GET /api/v1/studies/{id}` post-deploy.
- **Operational readiness gates:**
  - `make test-unit` covers the classifier + grep guard.
  - `make test-integration` covers the aggregator + `_detail` integration.
  - `make test-contract` covers the response shape.
  - `cd ui && pnpm test` covers the panel.
  - Manual smoke: open a converged demo study (any 200+ trial study from `make seed-demo`) → verdict shows. Open a 12-trial study (e.g., from a Custom-mode sub-warmup attempt) → `too_few_trials` shows.
- **Release gate:** All test layers green; no Gemini Code Assist High-severity unresolved; CLAUDE.md runbook table row added.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (impl-plan-gen) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (classifier) | AC-1, AC-2, AC-3, AC-6, AC-7 | Story 1.x | `backend/tests/unit/domain/study/test_convergence.py` | data-model.md §trials |
| FR-2 (epsilon hoist) | AC-17 | Story 1.x | `backend/tests/unit/domain/study/test_auto_followup.py` (extend), `test_convergence.py` (value-equality assertion + AST/grep guard) | — |
| FR-3 (aggregator) | AC-4, AC-5, AC-6, AC-10 | Story 2.x | `backend/tests/integration/test_study_convergence_integration.py` | — |
| FR-4 (StudyDetail) | AC-8, AC-9, AC-10 | Story 3.x | `backend/tests/contract/test_studies_api_contract.py` (extend) | ui-architecture.md |
| FR-5 (panel) | AC-11, AC-12, AC-13, AC-18, AC-20 | Story 4.x | `ui/src/__tests__/components/studies/convergence-panel.test.tsx` + `ui/tests/e2e/convergence-panel.spec.ts` (one lightweight real-backend smoke) | ui-architecture.md |
| FR-6 (digest) | AC-14, AC-15 | Story 5.x | integration test on the digest worker call site + assertion on the system prompt file | — |
| FR-7 (chain link) | AC-16 | Story 6.x (coordinated with autopilot) | integration test on the autopilot `/chain` endpoint after the field lands | feat_overnight_autopilot/feature_spec.md §8.3 (patch on landing) |
| FR-8 (glossary) | AC-11 (badge tooltip), AC-12 (curve tooltip) | Story 4.x | covered by panel unit test | — |
| FR-9 (runbook) | AC-19 | Story 7.x | docs assertion test (existing pattern) | CLAUDE.md Key Runbooks |

## 18) Definition of feature done

This spec's PR is "done" when:

- [ ] All acceptance criteria **AC-1 through AC-15, AC-17 through AC-20, AND AC-13b** pass in this spec's CI lane (AC-16 is conditional on the autopilot PR; see FR-7 + AC-16 gating note — it is NOT a merge-blocker for this spec). (Cycle-3 GPT-5.5 F1 fix — earlier draft accidentally omitted AC-20 from the DoD merge gate even though it's a non-functional accessibility requirement per §13.)
- [ ] All test layers (unit / integration / contract / frontend vitest / one lightweight Playwright smoke per §14) green.
- [ ] Documentation updates per §15 merged.
- [ ] Rollout gates from §16 satisfied.
- [ ] No open questions remain in §19.
- [ ] **(Non-blocking for this PR's merge — Cycle-2 GPT-5.5 F5 fix.)** The autopilot spec at [`docs/00_overview/planned_features/02_mvp2/feat_overnight_autopilot/feature_spec.md`](../feat_overnight_autopilot/feature_spec.md) §8.3 is patched in the autopilot PR (separately) to add the `convergence_verdict` field to `StudyChainLink`. This spec's PR ships the `ConvergenceVerdict` symbol + `fetch_study_convergence` helper + documented contract; the autopilot PR consumes them, patches its own spec, and asserts AC-16 in its own CI lane. This checkbox tracks the cross-PR coordination but does NOT gate this spec's merge.
- [ ] CLAUDE.md "Key Runbooks" table has the new row.

## 19) Open questions and decision log

### Open questions

(None remain open at spec-finalisation time. Each idea-stage open question is locked below.)

### Decision log

- **2026-05-31 — D-1: Classifier definition is trailing-window-flat, not Optuna-internal.** Idea Q-1 default accepted. A study is "Converged" when `improvement_in_window <= CONVERGENCE_FLAT_EPSILON (0.005)` over the last `window_size = clamp(max(5, total_complete_trials // 5), upper=CONVERGENCE_FLAT_WINDOW=20)` complete trials. Below `STUDIES_TPE_WARMUP_FLOOR=50`, verdict is `too_few_trials`. Below `CONVERGENCE_FLAT_MIN_COMPLETE=5`, verdict is `null`. Reused epsilon = `AUTO_FOLLOWUP_LIFT_EPSILON` (hoisted in FR-2). Rationale: deterministic, closed-form, no dependency on Optuna internals, identical epsilon as the chaining engine's lift gate so the "re-run vs follow-up" recommendations line up.
- **2026-05-31 — D-2: This feature owns the post-run "re-run with larger budget" framing.** Idea Q-2 default accepted. `feat_study_sub_warmup_guard` (shipped) owns the *pre-run* preventive warning on the create-study modal; this feature owns the *post-run* corrective framing in the digest narrative. Non-overlapping in time and surface — no double-ownership.
- **2026-05-31 — D-3: Curve always available; panel collapsed-by-default for `converged`, expanded-by-default for `still_improving` / `too_few_trials` / `null`.** Idea Q-3 default accepted. Rationale: for converged studies the curve is corroborating evidence (badge is enough); for ambiguous verdicts the curve is the disambiguator.
- **2026-05-31 — D-4: No new `FollowupItem.kind` for "re-run with larger budget".** The discriminated union is consumed by the proposal-page renderer and the search-space transform helper; a new kind would cascade through both. The digest narrative's lead recommendation line (FR-6 framing rule) carries the operator-facing intent without a wire-format change. Reserved for re-evaluation if an operator quantitatively reports "I keep missing the re-run framing because it's just prose."
- **2026-05-31 — D-5: No new `/convergence` endpoint.** The verdict ships inside the existing `GET /api/v1/studies/{id}` response — additive, optional, backward-compatible. A standalone endpoint would duplicate the studies router's existence check and the aggregator call without adding payload-shaping flexibility (the per-link slim variant for the chain endpoint already reuses the same aggregator).
- **2026-05-31 — D-6: Epsilon is shared by import alias + value-lock test + AST guard.** FR-2 re-exports via `from ... import AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON`. The value-lock test asserts equality `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005`; a separate AST/grep guard asserts no other module file redeclares the literal. (Cycle-1 GPT-5.5 F7 — Python's `is` identity check is too fragile for floats across re-import / reload boundaries; equality + structural enforcement is the durable contract.)
- **2026-05-31 — D-7: Classifier returns `None` (not `too_few_trials`) when `total_complete_trials < 5`.** The two cases are operationally distinct: "ran below warmup floor (50)" → `too_few_trials` + re-run recommendation; "we genuinely don't have enough rows to look at" → `null` + "Verdict pending — not enough trials yet" badge. Conflating them would mislabel a study with 3 complete trials as having explicitly under-budgeted, which it might not have (could be still queuing trials, or have hit an early-failure cluster).
