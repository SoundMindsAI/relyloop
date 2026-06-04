# Feature Specification — Overnight → final solution (autonomous cross-knob tuning)

**Date:** 2026-06-03
**Status:** Draft
**Owners:** Product: TBD · Engineering: TBD
**Related docs:**
- [`idea.md`](idea.md)
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)
- Shipped sibling: [`feat_overnight_autopilot`](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md) (the wizard relabel + `/chain` rollup this feature extends)
- Shipped sibling: [`feat_auto_followup_studies`](../../implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) (the chaining engine this feature deliberately departs from — see anti-pattern justification in §4)
- Shipped sibling: [`feat_digest_executable_followups`](../../implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md) + [`feat_digest_executable_followups_swap_template`](../../implemented_features/2026_05_24_feat_digest_executable_followups_swap_template/feature_spec.md) (the four-kind follow-up taxonomy + persisted-remap contract this spec consumes)
- Shipped sibling: [`feat_study_convergence_indicator`](../../implemented_features/2026_05_31_feat_study_convergence_indicator/feature_spec.md) (the per-link verdict that gates "final" semantics)
- Idea-stage sibling: [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) (the `/studies` list discoverability surface; this feature's Phase 2 coordinates with it)

---

## 1) Purpose

- **Problem:** The overnight autopilot ("🌙 Run overnight (compound automatically)") shipped as a deterministic narrowing loop — every chain link re-runs the *same* template with the *same* knobs, bounds tightened ±50% around the prior winner. The digest worker already produces **executable** follow-ups (`narrow` / `widen` / `swap_template`) with validated, remapped search spaces, but the autopilot never reads them; those cards are only reachable via the manual "Run this followup" button on the proposal page. The result: operators can sleep through a chain that hill-climbs one knob, but cannot sleep through a chain that *broadens* — switching to another parameter, or to a sibling template — because the autopilot doesn't know how. The user's stated goal is to "run the overnight process and in the morning have a final solution"; today's loop can only refine, not explore.
- **Outcome:** The wizard exposes a strategy choice alongside the existing depth: keep today's predictable `narrow` loop OR opt into `follow_suggestions`, which lets each chain link consume the parent digest's top **executable** follow-up — branching the chain across knobs and (when the digest emits a `swap_template`) across templates. The chain remains a single linear path (max 6 links per the engine's invariant), preserves every safety gate (lift, budget, depth, cancel cascade, idempotency), and adds a deterministic cycle guard so a swap → swap → swap can never ping-pong. The `/chain` endpoint and morning panel surface what each link did (`narrow_default` / `narrow` / `widen` / `swap_template`) so the operator can read the explored path before shipping the rolled-up winner.
- **Non-goal:** **Not** a global-optimality guarantee, **not** a rewrite of `evaluate_chain_gate`, **not** a new follow-up taxonomy. The existing four kinds, the existing gate decisions, the existing depth cap, the existing budget peek, and the existing cancel cascade all ship unchanged. The new strategy is **opt-in** behind a wizard toggle that defaults to today's `narrow` behavior — every existing study and every operator who doesn't change anything continues to see the loop they shipped to.

## 2) Current state audit

### Existing implementations

| Component | Path | Behavior relevant to this feature |
|---|---|---|
| Chain worker | [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py) | `enqueue_followup_study` dispatched by the digest worker. After the chain-gate + budget-peek + best-trial lookup, it ALWAYS composes `build_starter_search_space(template.declared_params)` + `narrow_bounds_around_winner(..., bracket=0.5)` and creates the child with `template_id=parent.template_id` ([line 238](../../../../backend/workers/auto_followup.py#L238)). The persisted digest's `suggested_followups` column is never read here — confirmed by `grep -n "suggested_followups" backend/workers/auto_followup.py` returning zero matches. |
| Chain gate (pure domain) | [`backend/app/domain/study/auto_followup.py`](../../../../backend/app/domain/study/auto_followup.py) | `evaluate_chain_gate` — SKIP_PARENT_FAILED → SKIP_DEPTH_EXHAUSTED → SKIP_NO_LIFT → ENQUEUE. Direction-aware lift via `_direction_normalized_lift`. Reused unchanged. |
| Followup taxonomy | [`backend/app/domain/study/followups.py`](../../../../backend/app/domain/study/followups.py) | `FOLLOWUP_KIND_VALUES = ("narrow", "widen", "text", "swap_template")` ([line 158](../../../../backend/app/domain/study/followups.py#L158)). `NarrowFollowup` + `WidenFollowup` + `SwapTemplateFollowup` each carry a validated `SearchSpace`; `TextFollowup` carries `search_space = None`. `parse_followup_list` is the defensive ingest path — never raises, downgrades invalid items to `text` or drops with a WARN. |
| Swap-template remap | [`backend/app/domain/study/template_swap.py`](../../../../backend/app/domain/study/template_swap.py) | `remap_search_space_for_swap_target` — already called by the **digest worker** BEFORE persisting (digest.py:372 `result = remap_search_space_for_swap_target(...)`). The persisted `suggested_followups` swap_template item therefore already carries a **remapped, ready-to-run** `SearchSpace` for the swap target. Consumer (this feature) does NOT need to re-remap. |
| Digest worker | [`backend/workers/digest.py`](../../../../backend/workers/digest.py) | Line 1289 reads `auto_followup_depth = study.config.get("auto_followup_depth")` and, if not None, enqueues `enqueue_followup_study` via Arq with deterministic `_job_id=f"enqueue_followup_study:{study_id}"`. The digest also persists `suggested_followups` as JSONB on the `digests` row before this dispatch. |
| Digest model | [`backend/app/db/models/digest.py`](../../../../backend/app/db/models/digest.py) | `Digest.suggested_followups: Mapped[list[dict[str, Any]]]` — NOT NULL, JSONB, server_default `'[]'::jsonb`. 1:1 with `studies` via UNIQUE FK on `study_id`. Consumers read via `parse_followup_list()` per spec D-defensive-ingest. |
| Study model | [`backend/app/db/models/study.py`](../../../../backend/app/db/models/study.py) | `studies.config: JSONB` carries `auto_followup_depth`. Self-FK `parent_study_id`. `parent_proposal_id` + `parent_proposal_followup_index` ([lines 86-97](../../../../backend/app/db/models/study.py#L86-L97)) are the lineage columns the manual "Run this followup" path uses — DB CHECK `studies_parent_proposal_pair_check` requires both-set-or-both-NULL. |
| Proposal model | [`backend/app/db/models/proposal.py`](../../../../backend/app/db/models/proposal.py) | `Proposal.status` CHECK constraint — `status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')` ([line 42](../../../../backend/app/db/models/proposal.py#L42)). **No `superseded` value today** — adding one requires a migration (deferred to Phase 3 `feat_overnight_final_solution_phase3/idea.md`). |
| Chain endpoint | [`backend/app/api/v1/studies.py:856-867`](../../../../backend/app/api/v1/studies.py#L856-L867) + Pydantic `StudyChainLink` at [`schemas.py:867-885`](../../../../backend/app/api/v1/schemas.py#L867-L885) | `GET /api/v1/studies/{id}/chain` returns `links: list[StudyChainLink]` with the rolled-up `best_link_id` + `cumulative_lift` + `stop_reason` + `proposal_id_for_best_link`. The `StudyChainLink` shape is explicitly extensible (the convergence-indicator spec FR-7 added `convergence_verdict` as a soft-contract additive field — see [`convergence.py:77-89`](../../../../backend/app/domain/study/convergence.py#L77-L89)). |
| Chain panel | [`ui/src/components/studies/auto-followup-chain-panel.tsx`](../../../../../ui/src/components/studies/auto-followup-chain-panel.tsx) | Calls `useStudyChain(studyId)` and renders the ordered link list + cumulative-lift + stop-reason + best-config CTA per feat_overnight_autopilot FR-4. Reusing this panel — no replacement. |
| Wizard depth selector | [`ui/src/components/studies/create-study-modal.tsx:1460-1468`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1460-L1468) | The `🌙 Run overnight (compound automatically)` label + `cs-auto-followup` testid + `InfoTooltip glossaryKey="overnight_autopilot"` + `Select` writing `auto_followup_depth: 0..5` into `config`. This feature ADDS a strategy toggle immediately below it. |
| Stop-condition presets | [`ui/src/components/studies/create-study-modal.tsx:113-115`](../../../../../ui/src/components/studies/create-study-modal.tsx#L113-L115) | `FOCUSED_WRITE` (50 trials), `STANDARD_WRITE` (200), `DEEP_WRITE` (1000 trials + 480 min). Unchanged by this spec. |
| Capability check / LLM client | [`backend/app/llm/`](../../../../backend/app/llm/) | The digest LLM call is already gated by the capability check (`feat_llm_judgments` infra). This spec does NOT add a new LLM call — it reads the digest the existing worker already persisted. |
| Schema validator | [`backend/app/api/v1/schemas.py:690-723`](../../../../backend/app/api/v1/schemas.py#L690-L723) | `StudyConfigSpec.auto_followup_depth: int \| None`, `_validate_auto_followup_depth` checks `0 ≤ depth ≤ 5`. **Adds** `auto_followup_strategy: str \| None = Field(default=None)` (per D-13 — `str | None`, NOT `Literal`, so the canonical error code path works) with a co-located `AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")` constant. Default `None` → behaves as `"narrow"`. |

### Navigation and link impact

No URL changes. The chain panel and the wizard mount at their existing positions.

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (none) | (none) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/workers/test_auto_followup.py`](../../../../backend/tests/unit/workers/test_auto_followup.py) (if exists; grep at impl time) | tests of `enqueue_followup_study` narrow path | TBD | Extend with `follow_suggestions` strategy coverage — narrow / widen / swap_template selection, fallback path, cycle-guard drop. Existing cases must continue passing (default strategy unchanged). |
| `backend/tests/integration/workers/test_chain_*` | DB-backed chain creation | TBD | Add integration coverage for the swap_template branch (child created with different `template_id` than parent). |
| `ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` | Wizard depth selector | TBD | Add strategy-toggle visibility tests (toggle hidden when `auto_followup_depth = 0`; toggle wire values `narrow` / `follow_suggestions`). |
| `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | Chain summary rendering | TBD | Add per-link strategy badge / column rendering coverage (new additive field on `StudyChainLink`). |
| `backend/tests/contract/test_studies_chain_contract.py` | `/chain` response schema | TBD | Extend to assert the new optional `selected_followup_kind` field on `StudyChainLink` (additive; existing assertions still pass). |

### Existing behaviors affected by scope change

- **`enqueue_followup_study` default behavior.** Current: always synthesizes a ±50% narrow on the parent's template. New: dispatches on `parent.config.auto_followup_strategy`; when missing or `"narrow"`, behaves exactly as today (zero behavioral change for existing studies). When `"follow_suggestions"`, reads the parent's persisted digest and consumes the top executable follow-up; on no candidate, falls back to today's narrow path. **Decision needed: no** — opt-in strategy is the locked default (idea Fork C recommended).
- **`auto_followup_strategy` is *inherited* down the chain.** Current: chain children inherit `auto_followup_depth` decremented from `parent.config` (verbatim copy minus the decrement). New: chain children also inherit `auto_followup_strategy` verbatim. **Decision needed: no** — strategy must be inherited; mid-chain mode-switching would break the cycle-guard contract.
- **`StudyChainLink` Pydantic shape.** Current: 12 fields including the soft-contract `convergence_verdict` from the indicator spec. New: 13 fields including an additive `selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] | None` (null for the anchor, which had no parent follow-up to consume). **Decision needed: no** — additive on a documented-extensible model.
- **Wizard step-5 visible controls.** Current: depth selector with `cs-auto-followup` testid. New: depth selector + a new strategy toggle directly beneath it, visible only when depth ≥ 1. **Decision needed: no** — locked by FR-2.
- **Daily-LLM budget peek.** Current: gates child creation against 80% of `OPENAI_DAILY_BUDGET_USD`. New: same gate, unchanged. The strategy-selection step happens **after** the budget gate — selection does NOT make a new LLM call (the digest's `suggested_followups` is persisted JSONB already paid for).

---

## 3) Scope

### In scope (Phase 1)

- **FR-1**: Add `auto_followup_strategy` config key — `Literal["narrow", "follow_suggestions"] | None` — to `StudyConfigSpec` with validator. Default `None` behaves as `"narrow"` (today's behavior, zero migration).
- **FR-2**: Wizard adds a strategy toggle directly beneath the existing depth selector, visible only when `auto_followup_depth >= 1`, with explicit copy explaining what "follow suggestions" means and that today's narrow remains the safe default.
- **FR-3**: Modify `enqueue_followup_study` to dispatch on `parent.config.auto_followup_strategy`. Existing `"narrow"` (or missing) path: zero behavior change. New `"follow_suggestions"` path: select the top executable follow-up from the parent's persisted digest; fall back to today's narrow if no candidate.
- **FR-4**: New pure-domain function `select_executable_followup(followups, visited_template_ids) -> SelectionResult | None` in `backend/app/domain/study/auto_followup_strategy.py` — filters to executable kinds, applies the cycle guard, returns a `SelectionResult` dataclass (item + source_index + candidate_count + dropped_template_ids) or `None`. Unit-testable; no I/O.
- **FR-5**: Cycle/no-regress guard — autopilot worker persists ordered-unique `auto_followup_visited_template_ids: list[str]` in `studies.config` JSONB. Anchor's missing key is treated as `[anchor.template_id]` by the worker (single-writer rule per D-14). Selection excludes any `swap_template` follow-up whose target is in the visited set.
- **FR-6**: Extend `StudyChainLink` Pydantic model with additive optional field `selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] | None`. Populated at chain-summary construction with defensive coercion against unknown values (per D-12).
- **FR-7**: Chain panel surfaces each link's `selected_followup_kind` as a compact badge / column entry so the operator can read the path the chain explored.
- **FR-8**: Telemetry — two new structlog events emitted AFTER child INSERT: `auto_followup_strategy_selected` (selection-driven paths) + `auto_followup_no_executable_candidate_fell_back_to_narrow` (fallback path). Each carries `dropped_template_ids` so cycle-guard activity is observable on the same line as the decision. Log-only (no `audit_log` until MVP3).
- **FR-9**: Tutorial section update + new glossary key `overnight_strategy` for the wizard toggle's `InfoTooltip`.

### Out of scope

- Any change to `evaluate_chain_gate`, the budget peek, the depth decrement, the cancel cascade, or the layer-1/layer-2 idempotency contract. The strategy dispatch happens AFTER all of these.
- A `superseded` value on `proposals.status` (Phase 3 → `feat_overnight_final_solution_phase3/idea.md`). MVP2 leans on the existing `/chain` endpoint's `best_link_id` + `proposal_id_for_best_link` to give the operator a single morning artifact; marking non-winning links' proposals `superseded` is a separate UX decision + migration that's not required for the core "explore + roll up" capability.
- A standalone morning summary card on the `/studies` list (Phase 2 → `feat_overnight_final_solution_phase2/idea.md`, coordinates with the existing `feat_overnight_studies_summary_card` sibling idea).
- A new follow-up kind, a change to the digest LLM prompt, or a change to the digest's structured-output schema.
- Multi-child fan-out per parent. The shipped engine's linear-chain invariant (D-7 of `feat_overnight_autopilot`) holds — strategy selection picks ONE follow-up per link.
- Operator-pickable mid-chain strategy switching. Strategy is set at study create and inherited verbatim by descendants.
- A new LLM call in the autopilot worker. This feature reads the digest already persisted by the digest worker.
- Auto-generating an `auto_followup_strategy` recommendation in the digest narrative. The strategy is the operator's choice up-front; the digest's existing convergence-aware ordering of follow-ups already biases selection toward the right kind per link.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` — confirmed against existing `studies.py` routers.
- **Router for this feature's endpoint changes:** [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) (the existing `/chain` endpoint's response model gains a soft-contract additive field; no new endpoint).
- **HTTP methods:** None new. This feature is a worker-internal change + a wizard form field + a soft-contract response extension.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — confirmed via `_err` helper at [`studies.py:93-97`](../../../../backend/app/api/v1/studies.py#L93-L97). This feature introduces one new validation error code (`AUTO_FOLLOWUP_STRATEGY_INVALID`) emitted by `_validate_auto_followup_strategy` in the same envelope shape as the existing `_validate_auto_followup_depth` (`AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`).
- **Auth error shape:** N/A. MVP1–MVP3 ship no auth surface.

### Phase boundaries

- **Phase 1 (this spec, MVP2):** FR-1 through FR-9 — the strategy wire contract, the wizard toggle, the worker dispatch, the cycle guard, the chain endpoint additive field, the panel badge, telemetry, tutorial, glossary key. Ships the autonomous cross-knob/cross-template exploration capability behind an opt-in toggle.
- **Phase 2 (deferred to [`feat_overnight_final_solution_phase2/idea.md`](../../planned_features/02_mvp2/feat_overnight_final_solution_phase2/idea.md)):** Dedicated morning summary card surfacing the rolled-up winner + the explored path + total lift, separate from the chain panel. Coordinates with [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md). Rationale for deferral: the existing `/chain` endpoint already exposes the data needed; a polished morning card is a UX add-on that should follow rather than block the capability.
- **Phase 3 (deferred to [`feat_overnight_final_solution_phase3/idea.md`](../../planned_features/02_mvp2/feat_overnight_final_solution_phase3/idea.md)):** Proposal `superseded` status value + state-transition logic that marks non-winning chain links' proposals `superseded` so the morning artifact is unambiguously *one* answer. Rationale for deferral: requires a migration that reopens shipped schema (CHECK constraint on `proposals.status`) and a UX decision on whether superseded proposals appear in the `/proposals` index at all. Phase 1 delivers cross-knob exploration; Phase 3 polishes the rollup. Build it when an incident or design partner asks for the cleaner index.

---

## 4) Product principles and constraints

- **Today's narrow loop is the safe default.** Operators who do nothing see exactly the loop they shipped to. Strategy is opt-in; `None` and missing both behave as `"narrow"`.
- **The chaining engine's linear-chain invariant holds.** Max chain length = anchor + 5 descendants = 6 links. Each link still has at most one child. The strategy dispatch picks ONE follow-up per link; the existing idempotency layers (`_job_id` + `list_children_of_study` backstop) prevent fan-out.
- **The strategy is inherited down the chain.** Mid-chain mode switching would break the cycle guard. Operators choose at study creation; descendants follow.
- **No new LLM call.** The digest worker already made the call and persisted the structured output. The autopilot reads `digest.suggested_followups` from the JSONB column — pure DB read.
- **Cycle guard is mandatory under `follow_suggestions`.** A `swap_template` whose target is already in `auto_followup_visited_template_ids` MUST be excluded from selection. Without this, the LLM could ping-pong template_A → template_B → template_A → template_B until depth is exhausted, producing no exploration value.
- **Fallback to narrow MUST be the safety net.** When `follow_suggestions` finds no executable candidate (digest has only `text` items, or every executable candidate was dropped by the cycle guard), the worker MUST run today's narrow path rather than emit SKIP_NO_LIFT. The chain never stalls on strategy.
- **Selection ordering MUST trust the digest's convergence-aware ordering** (per [`prompts/digest_narrative.system.md:99-121`](../../../../prompts/digest_narrative.system.md#L99-L121)). When the parent is `still_improving` / `too_few_trials`, the digest already demotes `narrow`/`widen` and leads with `text` ("re-run with a larger budget"); the autopilot picks the first **executable** item by index from that already-ordered list. No re-ranking, no kind-preference policy.

### Anti-patterns

- **Do not** modify `evaluate_chain_gate`. The strategy decision is downstream of the gate — if the gate says SKIP, no child is created regardless of strategy.

  *(The parent `feat_overnight_autopilot` spec lists "do not modify `enqueue_followup_study`" as an anti-pattern. This spec **deliberately departs** from that — the entire feature is teaching the autopilot to act on follow-ups that the parent's spec scope explicitly left for the manual "Run this followup" button. The departure is acceptable because (a) the change is purely additive and dispatched behind a new config key, (b) the default behavior with that key missing is byte-identical to today's loop, (c) the parent spec's anti-pattern guarded against "drift", not against deliberate capability extension. This justification is logged as D-1 in §19.)*

- **Do not** synthesize new search spaces for executable follow-ups. The digest worker already validated + remapped them (for swap_template) before persisting. The autopilot consumes them verbatim. Re-synthesizing would risk drift between what the operator saw on the proposal page and what the autopilot actually ran.
- **Do not** call the LLM from `enqueue_followup_study`. The digest is the LLM boundary; the autopilot is a pure-DB-read consumer of its output.
- **Do not** add a new follow-up kind. The taxonomy is locked at four (`narrow` / `widen` / `text` / `swap_template`) per `FOLLOWUP_KIND_VALUES`.
- **Do not** allow `text`-kind follow-ups to be selected. They carry `search_space = None`; there is nothing to run.
- **Do not** invent a per-kind priority order ("prefer narrow before widen before swap"). Trust the digest's ordering. Reordering inside the autopilot would force the autopilot to re-derive convergence-awareness — duplicating logic the digest already owns.
- **Do not** broaden the wizard's strategy enum beyond the two values. A future `follow_suggestions_with_text_capture` variant would be a separate spec, not a quiet third enum value.
- **Do not** persist the strategy on `studies` as a top-level column. It lives in `config` JSONB alongside `auto_followup_depth` — same pattern, no migration, zero schema risk.
- **Do not** populate `selected_followup_kind` on the anchor link. The anchor had no parent follow-up to consume; the field is `null` there by definition.
- **Do not** mark non-winning chain links' proposals `superseded` in this phase. The proposal status CHECK constraint does not include that value; adding it requires a migration that's deferred to Phase 3.

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| `feat_auto_followup_studies` (chain engine + `enqueue_followup_study`) | This feature dispatches on a new config key inside that worker. | Implemented (PR #223, 2026-05-24) | N/A — shipped. |
| `feat_digest_executable_followups` (the four-kind taxonomy + `parse_followup_list`) | Autopilot consumes the discriminated-union JSONB the digest worker writes. | Implemented (PR #225, 2026-05-24) | N/A — shipped. |
| `feat_digest_executable_followups_swap_template` (the `remap_search_space_for_swap_target` helper called by digest worker BEFORE persisting) | Without the persisted remap, the autopilot would have to redo it — adding LLM-output-validation surface inside the worker. With the remap, the autopilot consumes the validated search_space verbatim. | Implemented (PR #232, 2026-05-24) | High if removed — autopilot would need its own remap pass. Locked dependency. |
| `feat_overnight_autopilot` (wizard label, `/chain` endpoint, `StudyChainLink` extensibility, `auto-followup-chain-panel`) | This feature extends the wizard step, adds an additive field on `StudyChainLink`, and surfaces the new field in the existing panel. | Implemented (PR #343, 2026-05-31) | N/A — shipped. |
| `feat_study_convergence_indicator` (digest-narrative convergence-aware follow-up ordering) | The autopilot's "trust the digest's ordering" principle relies on the digest already demoting `narrow`/`widen` when convergence says re-run-with-bigger-budget. | Implemented (PR #352, 2026-05-31) | Low — without it, the autopilot still picks the first executable item, just without convergence-awareness shaping the upstream order. Quality degrades but the loop still functions. |
| `feat_study_baseline_trial` (`baseline_metric`) | Direction-normalized lift in the chain gate, unchanged. | Implemented (2026-05-25) | N/A — shipped, untouched. |

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (operator) creating a study with the overnight depth enabled and choosing a strategy. Returns the next morning to review the chain summary and ship the winner.
- **Role model:** N/A — RelyLoop MVP2 is single-tenant, no auth.
- **Permission boundaries:** N/A — no auth.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). This feature ships structlog telemetry only (FR-8); no `audit_log` rows. The state mutations this feature performs — child study creation by the autopilot — are already covered by the existing `feat_auto_followup_studies` audit-event obligations (currently also N/A pre-MVP3); this feature adds no NEW state mutations to that worker beyond the additional `studies.config` keys, which are already part of the existing INSERT.

## 7) Functional requirements

### FR-1: New `auto_followup_strategy` config key

- **Requirement:**
  - The system **MUST** add `auto_followup_strategy: str | None = Field(default=None)` to `StudyConfigSpec` at [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py). **The field type is `str | None` (NOT `Literal[...]`)** — this mirrors the existing `auto_followup_depth: int | None = Field(default=None)` at [`schemas.py:716`](../../../../backend/app/api/v1/schemas.py#L716), which deliberately omits the `Literal`/range constraint at field-level so the custom validator can produce the canonical error code. A `Literal[...]` at field-level would raise Pydantic's generic `VALIDATION_ERROR` envelope on bad inputs BEFORE the custom validator runs, violating §8.6's contract that bad strategy values return `AUTO_FOLLOWUP_STRATEGY_INVALID` (cycle 1 finding C1-A3).
  - The system **MUST** add a `_validate_auto_followup_strategy` validator (mirroring the existing `_validate_auto_followup_depth` at [`schemas.py:735-749`](../../../../backend/app/api/v1/schemas.py#L735-L749)) that:
    1. Returns early when `auto_followup_strategy is None` (no constraint).
    2. Raises `ValueError("AUTO_FOLLOWUP_STRATEGY_INVALID: ...")` when the value is neither `"narrow"` nor `"follow_suggestions"` (operator-facing message: *"auto_followup_strategy must be 'narrow' or 'follow_suggestions'; got '<value>'"*).
    3. Raises `ValueError("AUTO_FOLLOWUP_STRATEGY_INVALID: ...")` when the value is set but `auto_followup_depth` is `None` or `0` (operator-facing message: *"auto_followup_strategy only applies when auto_followup_depth >= 1"*).
  - The prefix is unwrapped by `backend.app.api.errors.validation_exception_handler` into the canonical envelope's `error_code` (same mechanism used by `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`).
  - The system **MUST** treat `None`, missing key, and `"narrow"` identically — all three branches dispatch the existing narrow path in FR-3. The wire contract therefore stays backward-compatible: every existing study (which carries no `auto_followup_strategy` key) keeps behaving exactly as it did pre-feature.
- **Notes:** Lives in JSONB `config`, no migration. The validator covers both the value-rule and the pair-rule; the `str | None` field type is non-negotiable because the error-code unwrap mechanism requires the message-prefix path. Contract test asserts both rules produce `AUTO_FOLLOWUP_STRATEGY_INVALID`.

### FR-2: Wizard strategy toggle

- **Requirement:**
  - The system **MUST** add a two-position toggle / `Select` directly beneath the existing depth selector at [`create-study-modal.tsx:1460`](../../../../../ui/src/components/studies/create-study-modal.tsx#L1460), with:
    - Label: `"Strategy"` and an `InfoTooltip glossaryKey="overnight_strategy"` (added in FR-9).
    - Wire values + display labels: `"narrow"` → `"Refine the same knobs (predictable)"`; `"follow_suggestions"` → `"Try suggested follow-ups (broader exploration)"`.
    - `data-testid="cs-overnight-strategy"`.
    - Helper text (exact): *"Refine: each follow-up tightens around the previous winner on the same knobs. Try suggestions: each follow-up acts on the digest's top runnable recommendation, which may switch knobs or templates. Refine is the safer default; Try suggestions explores broader."*
  - The system **MUST** render the toggle only when `auto_followup_depth >= 1` (matches the validator's pair rule from FR-1). When depth is `Off`, the toggle is hidden.
  - The system **MUST** default the toggle to `"narrow"` whenever it becomes visible (depth transitions from 0 → ≥ 1).
  - The system **MUST** write `config.auto_followup_strategy = "narrow"` or `"follow_suggestions"` on submit. **Omit the key from `config`** when the toggle is hidden (depth = 0) — matches the pattern at [`create-study-modal.tsx:728`](../../../../../ui/src/components/studies/create-study-modal.tsx#L728) for `auto_followup_depth`.
  - The system **MUST** ground the toggle's wire values via `OVERNIGHT_STRATEGY_VALUES` imported from `ui/src/lib/enums.ts` (form-select-discipline rule per CLAUDE.md). The new enum constant cites the backend source-of-truth file in a comment.
- **Notes:** Locked copy at "Wizard taxonomy" in §11. The form-select-discipline rule is non-negotiable — the lint guard at [`form-select-discipline.test.tsx`](../../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx) fails the test suite otherwise.

### FR-3: `enqueue_followup_study` dispatches on `auto_followup_strategy`

- **Requirement:**
  - The system **MUST** modify [`enqueue_followup_study`](../../../../backend/workers/auto_followup.py) so that, **after** the existing chain-gate and budget-peek pass and **after** loading `parent` + `best_trial` + `template`, it reads `parent.config.get("auto_followup_strategy")`.
  - When the strategy is `None`, missing, or `"narrow"`: the system **MUST** execute today's exact path — `build_starter_search_space(declared_params)` + `narrow_bounds_around_winner(...)` + child INSERT with `template_id=parent.template_id`. **The worker MUST NOT write `auto_followup_selected_kind` to `child_config` on this path** — the legacy contract has no per-link strategy field, and writing one would surface a `"refined"` badge on chains the operator never opted into broader exploration for. (Per D-1: the default path stays byte-identical.)
  - When the strategy is `"follow_suggestions"`: the system **MUST** load the parent's digest (`SELECT suggested_followups FROM digests WHERE study_id = :parent_study_id`), call `parse_followup_list(suggested_followups, study_id=parent_study_id)` to get the structured list, then call `select_executable_followup(...)` (FR-4) to obtain a `SelectionOutcome`.
  - When `outcome.selected` is a `NarrowFollowup` or `WidenFollowup`: the system **MUST** use the follow-up's `search_space` directly and keep `template_id=parent.template_id`. Set `child_config["auto_followup_selected_kind"] = "narrow"` or `"widen"` to match.
  - When `outcome.selected` is a `SwapTemplateFollowup`: the system **MUST** call `repo.get_query_template(db, outcome.selected.template_id)` defensively; on miss (deleted swap target), the system **MUST** log a WARN with `event_type = "auto_followup_swap_target_missing"` (FR-8) and fall back to narrow on `parent.template_id` (same fallback path as no-candidate). On hit, use the follow-up's `template_id` (the swap target) and the follow-up's `search_space` (already remapped by the digest worker). Set `child_config["auto_followup_selected_kind"] = "swap_template"`.
  - When `outcome.selected is None` (no executable candidate after cycle-guard filtering) — or the digest row is missing entirely (defensive — should not happen because the digest worker enqueues this worker AFTER persisting): the system **MUST** execute the narrow path AND set `child_config["auto_followup_selected_kind"] = "narrow_default"` (this marker DOES persist here — operator picked `follow_suggestions` but the autopilot had nothing executable to run, and the `"refined"` badge on this link is the audit signal). The system **MUST** log `auto_followup_no_executable_candidate_fell_back_to_narrow` (FR-8) **after** the child INSERT commits, so `child_study_id` is populated on the event, with `dropped_template_ids` carrying `outcome.dropped_template_ids` (so a chain that wanted to ping-pong but was guard-dropped is observable on the same line).
  - The system **MUST** inherit `auto_followup_strategy` verbatim into `child_config` alongside the decremented depth (mirrors the existing `child_config = {**parent.config, "auto_followup_depth": remaining}` pattern at [`auto_followup.py:223`](../../../../backend/workers/auto_followup.py#L223)).
  - **The system MUST NOT inherit `parent.config.auto_followup_selected_kind` into `child_config`.** That key is per-link state (records the path the worker took for *this* child). The worker MUST start from `child_config = {**parent.config, "auto_followup_depth": remaining}` and then **explicitly overwrite or remove** the inherited `auto_followup_selected_kind` before persist: under `"follow_suggestions"` the worker assigns the child's actual selection; under `"narrow"`/default the worker MUST `child_config.pop("auto_followup_selected_kind", None)` so the legacy chain remains clean. The integration tests (§14) MUST assert no parent-kind leakage on the child row.
  - The system **MUST NOT** touch `evaluate_chain_gate`, `peek_daily_total`, or `_BUDGET_THRESHOLD_PCT`. The strategy dispatch happens between step 7 (load template + winner) and step 8 (build child config) of the existing worker; all earlier guards run unchanged.
- **Notes:** A reviewer should be able to confirm by reading the worker file that adding `auto_followup_strategy = None` to a fixture's `parent.config` produces byte-identical behavior to a fixture without the key — neither `auto_followup_selected_kind` nor `auto_followup_visited_template_ids` is persisted on the legacy path. That equivalence is the spec's backward-compatibility contract.

### FR-4: Pure-domain `select_executable_followup`

- **Requirement:**
  - The system **MUST** add a pure-domain function `select_executable_followup(followups: list[FollowupItem], visited_template_ids: set[str]) -> SelectionOutcome` in a new module `backend/app/domain/study/auto_followup_strategy.py`. **The function always returns a `SelectionOutcome`** — never `None`. The "no executable candidate" case is encoded as `SelectionOutcome.selected is None` (cycle 2 finding C2-A1; carrying `dropped_template_ids` on the no-selection path is required by FR-8's fallback event contract).
  - `SelectionOutcome` is a frozen dataclass exposing:
    - `selected: FollowupItem | None` — the selected (executable) follow-up, OR `None` when no executable candidate remained after filtering;
    - `source_index: int | None` — the 0-based index of the selected item in the ORIGINAL `followups` list (not in the post-filter list), so telemetry can correlate with the digest's persisted order; `None` when `selected is None`;
    - `candidate_count: int` — count of executable items the function considered AFTER the cycle-guard filter (the number of items that were in contention for selection); `0` when no executable items remained;
    - `dropped_template_ids: list[str]` — the cycle-guard-dropped `SwapTemplateFollowup.template_id` values, sorted ascending for deterministic telemetry. **Always populated** when at least one swap_template was filtered, even if the outcome is `selected=None` (this is the contract that makes FR-8's fallback event line tell the full story).
  - The function **MUST**:
    1. Walk `followups` once, recording each item's original index.
    2. Drop `TextFollowup` items (no `search_space`). Drop `SwapTemplateFollowup` items whose `template_id` is in `visited_template_ids` — record the dropped `template_id` in `dropped_template_ids`.
    3. The first remaining (executable, non-cycle) item by original index is the selection. Compute `candidate_count` as the number of remaining items after filtering. Return `SelectionOutcome(selected=item, source_index=index, candidate_count=count, dropped_template_ids=sorted(dropped))`.
    4. When no executable item remains: return `SelectionOutcome(selected=None, source_index=None, candidate_count=0, dropped_template_ids=sorted(dropped))`.
  - The function **MUST** be pure: no DB, no async, no I/O. Deterministic — same input → same output. Unit-testable without fixtures.
  - The function **MUST** be exception-safe with respect to malformed `FollowupItem` instances: rely on Pydantic discriminated-union validity (which `parse_followup_list` already guarantees upstream); do not add defensive `try/except` inside the selector — let any anomalies surface as test failures at the unit-test layer.
- **Notes:** The `visited_template_ids` set is constructed by the worker from `parent.config.get("auto_followup_visited_template_ids", [parent.template_id])` (FR-5). The worker does NOT add the prospective child template to that set BEFORE calling the selector — the cycle guard's job is to look backward only. Worker dispatch on the result: if `outcome.selected is None` → fallback path (with `outcome.dropped_template_ids` populating the fallback event); else → selection-driven path (with `outcome.dropped_template_ids` populating the `auto_followup_strategy_selected` event).

### FR-5: Cycle-guard persisted state (`auto_followup_visited_template_ids`)

- **Requirement:**
  - The system **MUST** persist `auto_followup_visited_template_ids: list[str]` in `studies.config` for every chain link created by the autopilot worker under `follow_suggestions` strategy. Format: ordered-unique list of `query_templates.id` values (36-char UUIDs); first-occurrence wins for ordering.
  - **The wizard does NOT set this key.** The anchor (operator-created study) has the key absent. The autopilot worker treats absence as `[parent.template_id]` when constructing the cycle-guard input — keeping FR-1's API schema lean and ensuring only ONE writer (the worker) owns the visited-list state (cycle 1 finding C1-A4).
  - Each child created by the autopilot under `follow_suggestions` **MUST** persist `child.config.auto_followup_visited_template_ids = ordered_unique(parent_visited + [child.template_id])` where `parent_visited = parent.config.get("auto_followup_visited_template_ids", [parent.template_id])` and `ordered_unique` is the `list(dict.fromkeys(...))` idiom (insertion-order-preserving uniqueness). When `child.template_id == parent.template_id` (the digest emitted a `narrow` or `widen` that kept the same template), the list does NOT grow — `[parent.template_id]` stays `[parent.template_id]` (cycle 1 finding C1-A5).
  - The system **MUST also** persist `child.config.auto_followup_selected_kind: str` (one of `"narrow_default" | "narrow" | "widen" | "swap_template"`) capturing which path FR-3 took. Read by FR-6 to populate `StudyChainLink.selected_followup_kind`. (Stored as a bare string in JSONB; the `Literal` enforcement happens at the API-response layer per FR-6 with the defensive coercion at chain-summary construction.)
  - When `auto_followup_strategy` is `"narrow"` (or default / absent), neither key is persisted on the autopilot-created child — the legacy path stays clean.
- **Notes:** JSONB keys, no schema change. No index needed (the worker reads `parent.config` directly; no query filters on it). The single-writer rule for `auto_followup_visited_template_ids` means: contract tests for the create-study endpoint MUST assert that a wizard-submitted `auto_followup_visited_template_ids` key in `config` is silently dropped or 422-rejected (decision: 422-rejected via a `model_extra`-style validator addendum — keeps the wire contract tight; see Story 1 in §17 traceability).

### FR-6: `StudyChainLink.selected_followup_kind` additive field

- **Requirement:**
  - The system **MUST** extend the `StudyChainLink` Pydantic model at [`schemas.py:867-885`](../../../../backend/app/api/v1/schemas.py#L867-L885) with an optional additive field `selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] | None = None`.
  - The system **MUST** populate the field in `studies.py:867` chain-summary construction with a **defensive coercion** wrapper (cycle 1 finding C1-A6): read `raw = link.config.get("auto_followup_selected_kind")`; if `raw is None` OR `raw not in SELECTED_FOLLOWUP_KIND_VALUES`, set the field to `None` (and emit a structlog WARN `chain_selected_kind_unknown` with `study_id` + `raw` truncated to 64 chars when `raw` is non-None-and-unknown — a soft-corruption signal, not a 500). Otherwise pass `raw` through.
  - **Rationale for the coercion:** `studies.config` is JSONB with no CHECK constraint. A malformed value (manual DB INSERT, schema drift, future-version row read by an older deploy) would otherwise raise Pydantic's `ValidationError` at response-construction and 500 the chain endpoint. The coercion mirrors the defensive ingest contract `parse_followup_list` enforces for `digests.suggested_followups` ([`followups.py:247-345`](../../../../backend/app/domain/study/followups.py#L247-L345)).
  - The system **MUST NOT** make the field required. It is a soft-contract additive — frontends with no awareness of it still parse `StudyChainLink` correctly. Existing contract tests for the `/chain` endpoint continue passing.
  - The system **MUST** cite the backend Literal in a code comment at the frontend mapping site (per the Enumerated Value Contract Discipline rule).
- **Notes:** Pattern lifted verbatim from `feat_study_convergence_indicator`'s FR-7 soft-contract additive extension of `StudyChainLink`. Validates an established extensibility model. The new `SELECTED_FOLLOWUP_KIND_VALUES: tuple[str, ...]` constant lives in `backend/app/domain/study/auto_followup_strategy.py` (the same module as `select_executable_followup`) so the CI source-of-truth grep gate (`verify_enum_source_of_truth.sh`) resolves it cleanly.

### FR-7: Chain-panel surface for `selected_followup_kind`

- **Requirement:**
  - The system **MUST** render each link's `selected_followup_kind` in the chain panel at [`auto-followup-chain-panel.tsx`](../../../../../ui/src/components/studies/auto-followup-chain-panel.tsx) as a compact label or badge in the link list.
  - Display mapping:
    - `null` (or absent) → no badge (anchor; or narrow-strategy chain).
    - `"narrow_default"` → `"refined"` (lighter weight — the operator picked `follow_suggestions` but the autopilot fell back; the badge is the audit signal that suggestions were tried).
    - `"narrow"` → `"narrow ↓"` (digest suggested it).
    - `"widen"` → `"widen ↑"` (digest suggested broadening).
    - `"swap_template"` → `"swapped to {short_template_name}"`. The frontend resolves `short_template_name` by calling `GET /api/v1/query-templates/{link.template_id}` per `swap_template`-badged link and using the returned `name` (truncated to 30 chars + ellipsis if longer). Per OQ-1 resolution in §19: a per-link template fetch beats extending `StudyChainLink` with a `template_name` field because (a) at most 0–5 extra small fetches per chain (one per swap_template link), (b) the templates endpoint is already client-side cached by TanStack Query, (c) it keeps `/chain`'s response shape stable.
  - The system **MUST** add a `data-testid="chain-link-strategy-{link_id}"` per badge so vitest + Playwright can assert per-link strategy rendering.
  - The system **MUST** preserve every existing chain-panel test case unchanged.
- **Notes:** Hide-on-null behavior keeps narrow-strategy chains visually identical to today's chain panel. The per-link template-name fetch uses the existing `useQueryTemplate(id)` hook (if present) or a new minimal hook colocated with the panel; either approach is fine — defer to impl time.

### FR-8: Telemetry

- **Requirement:**
  - The system **MUST** emit **two new INFO `event_type` structlog events** AND **one new WARN `event_type`** from `enqueue_followup_study` under the `"follow_suggestions"` strategy. The two INFO events are emitted **AFTER** the child INSERT commits so `child_study_id` is populated; the WARN is emitted **before** the worker decides on the fallback path, so it carries `parent_study_id` only (no `child_study_id` — there isn't one yet at WARN time). All three events fold their selection metadata (`dropped_template_ids`) so a single chain-link decision produces a single canonical line (cycle 1 finding C1-B2 + cycle 2 finding C2-B1):
    - **INFO `auto_followup_strategy_selected`** — fires whenever the worker took a selection-driven path. Fields: `parent_study_id`, `child_study_id`, `strategy: "follow_suggestions"`, `selected_kind: "narrow"|"widen"|"swap_template"`, `source_index: int`, `candidate_count: int`, `dropped_template_ids: list[str]` (cycle-guard drops from the same selection — empty list when no swaps were dropped).
    - **INFO `auto_followup_no_executable_candidate_fell_back_to_narrow`** — fires when `outcome.selected is None` and the worker took the fallback-to-narrow path. Fields: `parent_study_id`, `child_study_id`, `digest_followup_kinds: list[str]` (the original kinds from the digest, for diagnostics), `visited_template_id_count: int`, `dropped_template_ids: list[str]` (from the partial selection — when all executable candidates were `swap_template` AND all were cycle-dropped, this list is non-empty, telling the operator "the chain wanted to ping-pong but the guard fired").
    - **WARN `auto_followup_swap_target_missing`** — fires when `outcome.selected` is a `SwapTemplateFollowup` but the defensive `repo.get_query_template` lookup returns `None` (deleted swap target). Fields: `parent_study_id`, `swap_target_template_id: str`. **No `child_study_id`** — the worker has not yet INSERTed the fallback child at this point; the subsequent `auto_followup_no_executable_candidate_fell_back_to_narrow` is NOT emitted (the candidate existed but its target was deleted — distinct event shape from "no candidate at all"). The WARN is the audit signal; the `auto_followup_enqueued` INFO event still fires on the fallback child's INSERT.
    - (The previous `auto_followup_cycle_guard_dropped_swap_template` event from earlier drafts is removed — its data folds into `dropped_template_ids` on the two INFO events above.)
  - The system **MUST NOT** emit these events when strategy is `"narrow"` (or default) — the legacy path stays log-quiet.
  - Existing 8 telemetry events from [`feat_auto_followup_studies` FR-9](../../implemented_features/2026_05_24_feat_auto_followup_studies/feature_spec.md) continue firing unchanged. The new 3 (2 INFO + 1 WARN) are additive and do not replace any existing event.
- **Notes:** Log-only, not `audit_log` (MVP3+). Runbook (FR-9 docs update) explains the new events and the operator-facing implication.

### FR-9: Glossary key + tutorial section

- **Requirement:**
  - The system **MUST** add the glossary key `overnight_strategy` to [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) under the same `feat_overnight_autopilot Story 3.1` block.
  - The entry **MUST** include `short` (≤ 120 chars) and `long` (paragraph). Suggested `short`: *"How each follow-up is chosen. Refine: tighter bounds on the same knobs. Try suggestions: digest's top runnable recommendation."*
  - The system **MUST** extend [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) Step 12 ("Run the loop overnight") with a sub-section on the strategy choice — explaining `"narrow"` (today's predictable refinement) vs `"follow_suggestions"` (broader exploration), naming the cycle guard, and stating that the chain always falls back to narrow if no executable follow-up exists.
  - The system **MUST** add (or extend) the existing autopilot runbook section explaining the three new structlog events (2 INFO + 1 WARN per FR-8) — how to grep, what each means operationally, and what to do when `auto_followup_no_executable_candidate_fell_back_to_narrow` fires frequently (signal that the digest is mostly emitting `text` follow-ups, which usually means a `still_improving` / `too_few_trials` study — operator should re-run with a larger budget rather than continue chaining). The runbook should also distinguish `auto_followup_swap_target_missing` (WARN — operator action: investigate why a template was deleted while a chain referenced it) from the routine fallback INFO.
- **Notes:** The glossary key value-lock test (`ui/src/__tests__/lib/glossary.test.ts` or equivalent) gains a new assertion per the existing pattern (`overnight_autopilot` already has one — mirror it).

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` (existing) | Accepts new `config.auto_followup_strategy` field. | `422 AUTO_FOLLOWUP_STRATEGY_INVALID` (new) |
| `GET` | `/api/v1/studies/{study_id}/chain` (existing) | Returns `StudyChainLink.selected_followup_kind` per link (additive). | `404 STUDY_NOT_FOUND` (unchanged) |

No new endpoints. Both modifications are additive on existing routes.

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code`.
- Status codes **MUST** be deterministic per scenario.
- `StudyChainLink.selected_followup_kind` is **optional** (`| None = None`) — existing API consumers parse the response without modification.
- `config.auto_followup_strategy` is **optional** at the API — clients that don't set it preserve today's behavior.

### 8.3 Response schema (additive deltas only)

**`StudyChainLink` — new fields:**

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `selected_followup_kind` | `Literal["narrow_default","narrow","widen","swap_template"]` | yes | The path FR-3 took when creating this link. Null for the anchor and for any link created under `"narrow"` strategy. |
| `template_id` | `str` | no | The link's `studies.template_id`. Added so FR-7's chain-panel swap_template badge can resolve the target template's display name via `GET /api/v1/query-templates/{id}` without a second `/chain` round-trip. Non-optional — every study has a template. (Added at plan-stage GPT-5.5 review P1-B5; the badge is otherwise not buildable.) |

All other `StudyChainLink` fields per [`feat_overnight_autopilot` §8.3](../../implemented_features/2026_05_31_feat_overnight_autopilot/feature_spec.md). All other `StudyChainResponse` fields unchanged.

**`StudyConfigSpec` — new optional field:**

| Pydantic field type | Accepted wire values | Nullable | Notes |
|---|---|---|---|
| `str \| None = Field(default=None)` | `"narrow"`, `"follow_suggestions"` | yes | Default `None` (key absent or explicit `null`). The Pydantic field type is **`str | None`**, NOT `Literal[...]`, per D-13 — the enum check happens in `_validate_auto_followup_strategy` so bad values surface as `AUTO_FOLLOWUP_STRATEGY_INVALID` rather than Pydantic's generic `VALIDATION_ERROR`. The two accepted wire values are exposed as a module-level constant `AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")` co-located with the validator (consumed by the CI source-of-truth grep gate and the frontend enum mirror). |

### 8.4 Response examples

**Success — chain endpoint returning a `follow_suggestions` chain that explored two strategies:**

```json
{
  "anchor_study_id": "01910000-0000-7000-8000-000000000001",
  "best_link_id": "01910000-0000-7000-8000-000000000003",
  "best_metric": 0.8421,
  "cumulative_lift": 0.1834,
  "direction": "maximize",
  "stop_reason": "no_lift",
  "proposal_id_for_best_link": "01910000-0000-7000-8000-0000000000a3",
  "links": [
    {
      "id": "01910000-0000-7000-8000-000000000001",
      "name": "anchor — title boost tune",
      "status": "completed",
      "best_metric": 0.6587,
      "baseline_metric": 0.6500,
      "direction": "maximize",
      "delta_from_prev": null,
      "proposal_id": "01910000-0000-7000-8000-0000000000a1",
      "auto_followup_depth_remaining": 3,
      "failed_reason": null,
      "created_at": "2026-06-01T22:14:03+00:00",
      "completed_at": "2026-06-02T01:02:11+00:00",
      "selected_followup_kind": null
    },
    {
      "id": "01910000-0000-7000-8000-000000000002",
      "name": "anchor — title boost tune (chain depth 2)",
      "status": "completed",
      "best_metric": 0.7421,
      "baseline_metric": null,
      "direction": "maximize",
      "delta_from_prev": 0.0834,
      "proposal_id": "01910000-0000-7000-8000-0000000000a2",
      "auto_followup_depth_remaining": 2,
      "failed_reason": null,
      "created_at": "2026-06-02T01:02:18+00:00",
      "completed_at": "2026-06-02T03:48:55+00:00",
      "selected_followup_kind": "narrow"
    },
    {
      "id": "01910000-0000-7000-8000-000000000003",
      "name": "anchor — title boost tune (chain depth 1, swapped to function-score-v1)",
      "status": "completed",
      "best_metric": 0.8421,
      "baseline_metric": null,
      "direction": "maximize",
      "delta_from_prev": 0.1000,
      "proposal_id": "01910000-0000-7000-8000-0000000000a3",
      "auto_followup_depth_remaining": 1,
      "failed_reason": null,
      "created_at": "2026-06-02T03:49:02+00:00",
      "completed_at": "2026-06-02T06:31:42+00:00",
      "selected_followup_kind": "swap_template"
    }
  ]
}
```

**Failure — invalid `auto_followup_strategy`:**

```json
{
  "detail": {
    "error_code": "AUTO_FOLLOWUP_STRATEGY_INVALID",
    "message": "auto_followup_strategy only applies when auto_followup_depth >= 1",
    "retryable": false
  }
}
```

HTTP `422`. Auth error shape: N/A.

### 8.5 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `config.auto_followup_strategy` | `narrow`, `follow_suggestions` (or absent / `null`) | `AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")` co-located with `_validate_auto_followup_strategy` in `backend/app/api/v1/schemas.py`. The Pydantic field itself is `str \| None` (per D-13) — the enum tuple is the source-of-truth that both the validator and the frontend mirror cite. Cite as `// Values must match backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES` in `ui/src/lib/enums.ts OVERNIGHT_STRATEGY_VALUES`. | Strategy `<Select>` at `ui/src/components/studies/create-study-modal.tsx` (FR-2). |
| `StudyChainLink.selected_followup_kind` | `narrow_default`, `narrow`, `widen`, `swap_template` (or `null`) | New module-level Literal `SELECTED_FOLLOWUP_KIND_VALUES: tuple[str, ...]` in `backend/app/domain/study/auto_followup_strategy.py`. Cite in `ui/src/lib/enums.ts` per the Story 2.13 lint guard. | Per-link badge in `auto-followup-chain-panel.tsx` (FR-7). |

The four `FOLLOWUP_KIND_VALUES` (`narrow`, `widen`, `text`, `swap_template`) at [`backend/app/domain/study/followups.py:158`](../../../../backend/app/domain/study/followups.py#L158) remain the source of truth for the digest's discriminated union — unchanged.

### 8.6 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `AUTO_FOLLOWUP_STRATEGY_INVALID` | `422` | `config.auto_followup_strategy` is set without `auto_followup_depth >= 1`, OR carries a value outside the allowed Literal. |

## 9) Data model and state transitions

### New/changed entities

**No schema changes. No migration.**

`studies.config` (JSONB) gains three optional keys, all written by the wizard or worker as part of the existing INSERT:

| Key | Type | Set by | Notes |
|---|---|---|---|
| `auto_followup_strategy` | `"narrow" \| "follow_suggestions" \| absent` | Wizard (FR-2), inherited by autopilot children (FR-3) | Absent + `"narrow"` are equivalent to the worker. |
| `auto_followup_visited_template_ids` | `list[str]` | Autopilot worker under `follow_suggestions` only (FR-5) | Never set under `"narrow"` strategy. |
| `auto_followup_selected_kind` | `"narrow_default" \| "narrow" \| "widen" \| "swap_template" \| absent` | Autopilot worker (FR-3 + FR-5) | Absent for anchor + for `"narrow"` strategy. |

The existing `studies.config.auto_followup_depth` is read + decremented unchanged.

The existing `digests.suggested_followups` is read (new consumer); never written by this feature.

### Required invariants

- **Strategy is inherited verbatim.** A chain's anchor sets `auto_followup_strategy` at study creation; every descendant under that chain MUST carry the same value in `child.config.auto_followup_strategy`. The worker is the only writer of this key on autopilot-created children; it copies `parent.config.auto_followup_strategy` without modification.
- **Visited-template guard MUST hold.** Under `follow_suggestions`, `select_executable_followup` MUST exclude any `SwapTemplateFollowup` whose `template_id` is already in `parent.config.auto_followup_visited_template_ids`. The set is constructed from the parent's persisted list (defaulting to `[parent.template_id]` when absent — the anchor case).
- **Fallback-to-narrow MUST run when no executable candidate is selected.** The worker MUST NOT emit SKIP_NO_LIFT or any non-ENQUEUE outcome because of an empty selection result. The narrow path is the safety net.
- **`selected_followup_kind` is informational only.** The field is on `StudyChainLink` for surfacing; the worker writes it to `child.config.auto_followup_selected_kind`. It MUST NOT be consulted by `evaluate_chain_gate` or any other gate — it's a post-decision audit field.
- **Wire backward compatibility.** A study created with `config = {auto_followup_depth: 3}` (no strategy key) MUST produce byte-identical worker behavior to today. The migration story is "no migration" — every existing row already satisfies the new contract.
- **`auto_followup_strategy` ⇒ depth ≥ 1.** Pair validator at the API. The `_validate_auto_followup_strategy` validator MUST raise the `AUTO_FOLLOWUP_STRATEGY_INVALID:` prefixed `ValueError` when the pair rule is violated.

### State transitions

`Study.status` transitions are unchanged. The strategy field doesn't move studies between states — it shapes which template/search-space the autopilot uses when creating the next link.

The worker's internal dispatch (added by FR-3) introduces these outcome paths. Note the **two distinct rows** for the narrow path — legacy-or-default chains (strategy `None` / `"narrow"`) persist NO `auto_followup_selected_kind` key, while `follow_suggestions`-fallback chains persist `"narrow_default"` (cycle 2 finding C2-A3 + D-12):

| Worker outcome | Strategy active | Telemetry event | `child.config.auto_followup_selected_kind` |
|---|---|---|---|
| **Legacy/default narrow path** | `None` or `"narrow"` | (no new event; existing `auto_followup_enqueued` only) | (key NOT persisted — worker pops before INSERT) |
| Follow-up consumed: `narrow` | `"follow_suggestions"` | `auto_followup_strategy_selected` + `auto_followup_enqueued` | `"narrow"` |
| Follow-up consumed: `widen` | `"follow_suggestions"` | same | `"widen"` |
| Follow-up consumed: `swap_template` (target exists) | `"follow_suggestions"` | same | `"swap_template"` |
| Swap target deleted → fallback | `"follow_suggestions"` | `auto_followup_swap_target_missing` (WARN) + `auto_followup_enqueued` | `"narrow_default"` |
| **`follow_suggestions` fallback (no candidate)** | `"follow_suggestions"` | `auto_followup_no_executable_candidate_fell_back_to_narrow` + `auto_followup_enqueued` | `"narrow_default"` |

### Idempotency/replay behavior

The strategy dispatch is **deterministic**. Given the same `parent.config`, `parent` row, `best_trial.params`, `template.declared_params`, and `digest.suggested_followups`, the worker produces the same child every invocation. Combined with the existing `_job_id`-based layer-1 idempotency at [`digest.py:1302`](../../../../backend/workers/digest.py#L1302) and the `list_children_of_study` layer-2 backstop at [`auto_followup.py:91-99`](../../../../backend/workers/auto_followup.py#L91-L99), replays produce identical results — no new replay risk introduced.

## 10) Security, privacy, and compliance

- **Threats:**
  - A malicious or compromised digest could persist a `SwapTemplateFollowup` pointing at an arbitrary `template_id`. The autopilot would create a child against that template. Mitigated by: (a) the digest worker already validates `template_id` (36-char UUID, must exist) via `remap_search_space_for_swap_target` before persisting, (b) RelyLoop's single-tenant MVP2 posture means there's no cross-tenant template surface to attack, (c) the cycle guard prevents repeated re-entry.
  - A misbehaving LLM output could cause the autopilot to always pick `swap_template` and starve narrowing chains. Mitigated by the `"narrow"` strategy remaining the default — operators opt in to the broader behavior explicitly.
- **Controls:** None new — relies on the digest worker's existing validation chain.
- **Secrets/key handling:** N/A — no secrets touched, no new LLM call.
- **Auditability:** Three new structlog events (2 INFO + 1 WARN per FR-8). `audit_log` lands at MVP3.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement (wizard):** Strategy toggle is a NEW row directly beneath the existing depth selector at Step 5 ("Objective + config"). Same modal, same step, no new screen.
- **Navigation placement (chain panel):** No change. The new `selected_followup_kind` badge renders inline within each link's existing list item.
- **Labeling taxonomy:**
  - Wizard depth label (existing, unchanged): `"🌙 Run overnight (compound automatically)"`.
  - **Strategy label (new):** `"Strategy"` (compact — the toggle's two display labels carry the explanation).
  - Strategy options: `"Refine the same knobs (predictable)"` (wire `"narrow"`) | `"Try suggested follow-ups (broader exploration)"` (wire `"follow_suggestions"`).
  - Helper text under the strategy toggle: per FR-2.
  - Chain panel per-link badges: `"refined"`, `"narrow ↓"`, `"widen ↑"`, `"swapped to {template_name}"` (per FR-7).
- **Content hierarchy (wizard):** Depth row first, strategy row immediately below — same visual cluster. The strategy row appears with the same `space-y-1.5` spacing used by other Step-5 controls.
- **Progressive disclosure:** Strategy toggle is hidden when depth = `Off` (matches the pair-validator semantic — no point picking a strategy for a one-shot study). Appears the moment depth ≥ 1 is selected.
- **Relationship to existing pages:** Pure additive surface — extends `feat_overnight_autopilot`'s wizard step + chain panel.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Wizard label `"Strategy"` | (short) How each follow-up is chosen. Refine: tighter bounds on the same knobs. Try suggestions: digest's top runnable recommendation. | hover/focus on info icon | right of label | `overnight_strategy` (NEW — FR-9) |
| Chain link badge `"swapped to {template_name}"` | (short) Try suggestions strategy: this link followed the digest's swap_template recommendation and ran against a different query template. | hover/focus | right of badge | `overnight_strategy` (existing, reused) |

### Primary flows

1. **Cross-knob overnight discovery flow.** Operator opens the create-study modal → Step 5 → picks `Deep (1000)` preset → sees the existing overnight hint → toggles `🌙 Run overnight` to depth 3 → new strategy toggle appears → picks `"Try suggested follow-ups (broader exploration)"` → submits. Anchor runs, completes overnight; the autopilot worker reads the anchor's digest, picks the top executable follow-up (say a `widen` on `title_boost`), creates link 2 with the widened bounds. Link 2 completes; the worker picks link 2's top executable (say a `swap_template` to `function-score-v1`), creates link 3 against that template. Link 3 plateaus (`no_lift`); chain stops. Operator wakes up to `/studies/{anchor_id}` → chain panel shows the three links with their `selected_followup_kind` badges → cumulative lift = +18% → best link is #3 with a proposal — clicks "Best config" CTA → lands on the proposal page → opens the PR.
2. **Cycle-guard prevention flow.** Anchor runs (template A), digest suggests `swap_template → B`. Worker creates link 2 against B. Link 2's digest suggests `swap_template → A` AND `narrow`. The autopilot's cycle guard sees A in `visited_template_ids` and drops the swap; picks the `narrow` instead. Link 3 runs against B with narrowed bounds. Operator sees the cycle-guard activity in the `dropped_template_ids` field of the `auto_followup_strategy_selected` log event for link 3 (`dropped_template_ids = ["TEMPLATE_A"]`, `selected_kind = "narrow"`) — one line tells the full story.
3. **Fallback-to-narrow flow.** Anchor runs, digest emits only `text` follow-ups ("re-run with bigger budget" — typical for `still_improving` verdict). Worker logs `auto_followup_no_executable_candidate_fell_back_to_narrow`, takes today's narrow path, creates link 2 with `selected_followup_kind = "narrow_default"`. Operator wakes up to a chain that still made progress (current behavior preserved); the chain panel renders link 2's badge as the lighter-weight `"refined"`.
4. **Backward-compatibility flow.** Operator picks `Off` depth → no strategy toggle visible → submits study with `config = {max_trials: 200, ...}` (no `auto_followup_depth`, no `auto_followup_strategy`). Worker behaves byte-identically to pre-feature. Zero observable change.
5. **Operator-pause-mid-chain flow.** Operator visits a mid-chain study → existing `POST /studies/{id}/cancel?cascade=true` halts pending children unchanged. The strategy doesn't affect the cancel path.

### Edge/error flows

- **Digest row missing under `follow_suggestions`.** Defensive: should not occur because the digest worker enqueues `enqueue_followup_study` AFTER persisting. If it does (e.g., manual digest deletion mid-chain): worker logs WARN, falls back to narrow.
- **Empty `suggested_followups` list.** `select_executable_followup` returns `None`; fallback fires. Chain continues with narrow.
- **All executable candidates filtered by cycle guard.** Same — `None` returned, fallback fires.
- **`SwapTemplateFollowup` references a deleted template.** Defensive: the worker's existing `repo.get_query_template` call at [`auto_followup.py:200`](../../../../backend/workers/auto_followup.py#L200) handles `None`; under `follow_suggestions` the worker MUST run the same defensive get against the swap target's `template_id` before INSERT. On miss: log WARN, fall back to narrow against `parent.template_id`.
- **`auto_followup_strategy = "follow_suggestions"` AND `auto_followup_depth = 0` at API.** Pair validator rejects at create with 422 `AUTO_FOLLOWUP_STRATEGY_INVALID`.
- **`auto_followup_strategy = "garbage_value"`.** Pair validator rejects at create with 422 `AUTO_FOLLOWUP_STRATEGY_INVALID`.

### Recovery

If the chain produces an unexpected swap_template result the operator wants to abort: existing cancel cascade (`POST /studies/{id}/cancel?cascade=true`) halts pending children — no change.

## 12) Given/When/Then acceptance criteria

### AC-1: Strategy validator pair-check (FR-1)

- Given a `POST /api/v1/studies` request with `config = {auto_followup_strategy: "follow_suggestions"}` and no `auto_followup_depth` (or depth = 0)
- When the request is validated
- Then the response is `422 { "detail": { "error_code": "AUTO_FOLLOWUP_STRATEGY_INVALID", "message": "auto_followup_strategy only applies when auto_followup_depth >= 1", "retryable": false } }`.

### AC-2: Strategy validator value-check (FR-1)

- Given a `POST /api/v1/studies` request with `config = {auto_followup_depth: 3, auto_followup_strategy: "broaden_everything"}`
- When the request is validated
- Then the response is `422 AUTO_FOLLOWUP_STRATEGY_INVALID`.

### AC-3: Default behavior unchanged (FR-3 backward compatibility)

- Given a study with `config = {auto_followup_depth: 3}` (no `auto_followup_strategy` key) and a completed parent with a winning trial
- When `enqueue_followup_study` runs
- Then the child is created with `template_id = parent.template_id`, the search space narrowed ±50% around the winner (existing behavior), AND `child.config` contains **neither** `auto_followup_selected_kind` **nor** `auto_followup_visited_template_ids` (the legacy path persists neither new key per FR-3 + FR-5; cycle 1 finding C1-A1). `GET /chain` returns this link with `selected_followup_kind = null`. The existing `auto_followup_enqueued` telemetry event fires; **no new event** fires.

### AC-4: Wizard toggle hidden when depth = 0 (FR-2)

- Given the create-study modal is open at Step 5 with `auto_followup_depth = "Off"`
- When the form renders
- Then no element with `data-testid="cs-overnight-strategy"` is present in the DOM. Setting depth to 1 makes the toggle appear with `"narrow"` selected by default.

### AC-5: Strategy persisted to config on submit (FR-2)

- Given the operator picks `auto_followup_depth = 3` and `Strategy = "Try suggested follow-ups (broader exploration)"`
- When the form submits
- Then the request body's `config` contains `auto_followup_depth: 3` AND `auto_followup_strategy: "follow_suggestions"`.

### AC-6: `follow_suggestions` consumes top executable narrow follow-up (FR-3 + FR-4)

- Given a parent study with `config = {auto_followup_depth: 3, auto_followup_strategy: "follow_suggestions"}` (no `auto_followup_visited_template_ids` key — anchor case), a completed digest carrying `suggested_followups = [{kind: "narrow", rationale: "...", search_space: {...}}, {kind: "text", rationale: "..."}]`, and the chain gate ENQUEUES
- When `enqueue_followup_study` runs
- Then the child is created with the `narrow` follow-up's `search_space` (verbatim, not re-narrowed), `template_id = parent.template_id`, `child.config.auto_followup_selected_kind = "narrow"`, `child.config.auto_followup_visited_template_ids = [parent.template_id]` (the ordered-unique list — since `child.template_id == parent.template_id` the list does not grow per FR-5 + cycle 1 finding C1-A5). Telemetry (emitted AFTER child INSERT): `auto_followup_strategy_selected` fires with `selected_kind = "narrow"`, `source_index = 0`, `candidate_count = 1`, `dropped_template_ids = []`, `child_study_id` populated. Existing `auto_followup_enqueued` also fires.

### AC-7: `follow_suggestions` consumes `swap_template` and branches template (FR-3 + FR-4)

- Given a parent study with `config = {auto_followup_depth: 2, auto_followup_strategy: "follow_suggestions", auto_followup_visited_template_ids: ["TEMPLATE_A"]}`, `parent.template_id = "TEMPLATE_A"`, and a digest with `suggested_followups = [{kind: "swap_template", template_id: "TEMPLATE_B", search_space: {...remapped...}, rationale: "..."}]`
- When `enqueue_followup_study` runs
- Then the child is created with `template_id = "TEMPLATE_B"`, the follow-up's `search_space` verbatim, `child.config.auto_followup_selected_kind = "swap_template"`, `child.config.auto_followup_visited_template_ids = ["TEMPLATE_A", "TEMPLATE_B"]`. Telemetry: `auto_followup_strategy_selected` fires with `selected_kind = "swap_template"`.

### AC-8: Cycle guard drops `swap_template` to already-visited template (FR-4 + FR-5)

- Given a parent study with `config.auto_followup_strategy = "follow_suggestions"`, `config.auto_followup_visited_template_ids = ["TEMPLATE_A", "TEMPLATE_B"]`, and a digest with `suggested_followups = [{kind: "swap_template", template_id: "TEMPLATE_A", ...}, {kind: "widen", search_space: {...}}]`
- When `select_executable_followup` runs
- Then the swap_template to TEMPLATE_A is dropped; the `widen` is selected (`SelectionResult.item.kind == "widen"`, `source_index == 1`, `candidate_count == 1` after filter, `dropped_template_ids == ["TEMPLATE_A"]`). The child runs the `widen` follow-up with `selected_kind = "widen"`. Telemetry: `auto_followup_strategy_selected` fires (AFTER child INSERT) with `selected_kind = "widen"`, `source_index = 1`, `candidate_count = 1`, `dropped_template_ids = ["TEMPLATE_A"]`, `child_study_id` populated.

### AC-9: Fallback-to-narrow on empty executable candidates (FR-3 + FR-4)

- Given a parent study with `config.auto_followup_strategy = "follow_suggestions"` and a digest with `suggested_followups = [{kind: "text", rationale: "re-run with bigger budget"}, {kind: "text", rationale: "..."}]` (no executable items)
- When `enqueue_followup_study` runs
- Then `select_executable_followup` returns `None`; the worker takes today's narrow path; child is created with `template_id = parent.template_id`, narrowed search space, `child.config.auto_followup_selected_kind = "narrow_default"`, `child.config.auto_followup_visited_template_ids = [parent.template_id]`. Telemetry: `auto_followup_no_executable_candidate_fell_back_to_narrow` fires AFTER child INSERT with `child_study_id` populated, `digest_followup_kinds = ["text", "text"]`, `visited_template_id_count = 1`, `dropped_template_ids = []`. The chain does not stall.

### AC-10: Strategy inherited verbatim (FR-3 + FR-5)

- Given a parent study with `config.auto_followup_strategy = "follow_suggestions"` and the worker successfully creates a child
- When the child row is inserted
- Then `child.config.auto_followup_strategy = "follow_suggestions"` (verbatim from parent). The child's own auto-followup, when it eventually runs, will also dispatch on the `follow_suggestions` branch.

### AC-11: `StudyChainLink.selected_followup_kind` populated (FR-6)

- Given a 3-link chain where link 2 has `config.auto_followup_selected_kind = "narrow"` and link 3 has `config.auto_followup_selected_kind = "swap_template"`
- When `GET /api/v1/studies/{any_link_id}/chain` is called
- Then `response.links[0].selected_followup_kind == null` (anchor), `response.links[1].selected_followup_kind == "narrow"`, `response.links[2].selected_followup_kind == "swap_template"`.

### AC-12: `StudyChainLink.selected_followup_kind` null for legacy chains (FR-6 backward compatibility)

- Given a 3-link chain created entirely under the legacy `narrow` strategy (no `config.auto_followup_selected_kind` key on any link)
- When `GET /api/v1/studies/{any_link_id}/chain` is called
- Then every `links[i].selected_followup_kind == null`. The existing chain-panel rendering tests continue to pass.

### AC-13: Chain panel renders strategy badges (FR-7)

- Given the chain endpoint returns the AC-11 payload
- When `<AutoFollowupChainPanel>` mounts under `/studies/{link_id}`
- Then for link 2 a badge with `data-testid="chain-link-strategy-{link_2_id}"` reading `"narrow ↓"` renders; for link 3 a badge `"swapped to {template_short_name}"` renders. Link 1 has no badge.

### AC-14: Chain panel preserved for legacy chains (FR-7 backward compatibility)

- Given the chain endpoint returns a payload where every link has `selected_followup_kind = null`
- When the panel mounts
- Then no `chain-link-strategy-*` testid is present; the existing rendering matches today's snapshot.

### AC-15: Tutorial section exists (FR-9)

- Given the tutorial page is rendered
- When an operator reaches Step 12 ("Run the loop overnight")
- Then a sub-section explains the strategy choice and explicitly names the cycle guard + the narrow-fallback contract.

### AC-16: Glossary key exists (FR-9)

- Given the glossary file `ui/src/lib/glossary.ts`
- When the value-lock test asserts on `glossary['overnight_strategy']`
- Then the entry has `short` (≤120 chars) and `long` (paragraph) fields; `short` includes both wire values verbatim (`"narrow"` and `"follow_suggestions"`) so frontend mapping never drifts silently.

### AC-17: Deleted swap target → defensive fallback (FR-3 + edge flow per cycle 1 finding C1-B4)

- Given a parent study with `config.auto_followup_strategy = "follow_suggestions"` and a digest whose top executable follow-up is a `swap_template` pointing at `template_id = "TEMPLATE_DELETED"` which no longer exists in `query_templates` (e.g., template was hard-deleted between digest generation and autopilot dispatch)
- When `enqueue_followup_study` runs and reaches the defensive `repo.get_query_template(db, "TEMPLATE_DELETED")` lookup per FR-3
- Then the worker logs a structlog WARN with `event_type = "auto_followup_swap_target_missing"`, `parent_study_id`, `swap_target_template_id = "TEMPLATE_DELETED"`. The worker falls back to the narrow path: child created with `template_id = parent.template_id`, narrowed search space, `child.config.auto_followup_selected_kind = "narrow_default"`. The chain does NOT 500 or SKIP; it continues with the same safety-net semantics as the empty-executable-candidates path. `auto_followup_no_executable_candidate_fell_back_to_narrow` is NOT emitted (the candidate existed but pointed at a deleted target — distinct telemetry shape), but the existing `auto_followup_enqueued` still fires.

### AC-18: Stale parent `selected_kind` does NOT leak to child (FR-3 inheritance + cycle 1 finding C1-B5)

- Given a parent study with `config = {auto_followup_depth: 3, auto_followup_strategy: "follow_suggestions", auto_followup_selected_kind: "widen"}` (the parent was itself a chain-child whose selection was `"widen"`) and a digest whose top executable follow-up is a `swap_template`
- When `enqueue_followup_study` runs and creates the child
- Then `child.config.auto_followup_selected_kind == "swap_template"` (overwrites the parent's `"widen"`, NEVER inherits it). On the legacy path (parent's strategy is `None` or `"narrow"`), `child.config` MUST NOT contain `auto_followup_selected_kind` at all (the worker pops it out before persist, even if `parent.config` happened to carry one from a prior strategy). Integration test asserts this directly on the child row.

## 13) Non-functional requirements

- **Performance:** The strategy dispatch adds **at most one extra DB SELECT** per chain link (the `digests` row lookup keyed by `study_id`, which is UNIQUE-indexed). p99 < 50ms additional latency per child enqueue. The `select_executable_followup` function is O(N) over follow-up list length (max 5 per digest worker structured-output schema cap), trivially fast.
- **Reliability:** The new branches in `enqueue_followup_study` MUST be exception-safe: any unexpected error in digest read / parse / select MUST be caught and fall back to today's narrow path with a WARN log. Chain reliability MUST NOT regress vs the legacy path.
- **Operability:** Three new structlog event types (2 INFO + 1 WARN per FR-8). Runbook update (FR-9) explains how to grep for them and how to distinguish the routine fallback from the deleted-swap-target WARN. No new env vars, no new metrics, no new alerts.
- **Accessibility:** Strategy toggle MUST carry an `aria-label` mirroring its visual label, and the `InfoTooltip` MUST include `ariaLabel` (existing pattern).

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `domain/study/test_auto_followup_strategy.py` (new) — `select_executable_followup` matrix: empty list → None; text-only list → None; mixed text + narrow → narrow selected at first executable index; mixed text + swap_template (visited) + widen → widen selected (cycle-guard drop); swap_template to non-visited template → swap selected; multiple executable candidates → first-by-index wins. Pure-function tests only.
  - `domain/study/test_auto_followup.py` — existing tests continue passing unchanged.
- **Integration tests (`backend/tests/integration/`):**
  - `workers/test_auto_followup_strategy.py` (new) — DB-backed: seed parent + digest with each executable kind; assert child row's `template_id`, `config.auto_followup_strategy`, `config.auto_followup_visited_template_ids`, `config.auto_followup_selected_kind`. Cover fallback-to-narrow when digest has only text. Cover cycle-guard drop. Cover legacy `narrow` strategy producing byte-identical state to pre-feature.
- **Contract tests (`backend/tests/contract/`):**
  - `test_studies_chain_contract.py` (extend) — assert `selected_followup_kind` optional field on `StudyChainLink`; assert `SELECTED_FOLLOWUP_KIND_VALUES` enum exposed via the domain module (CI source-of-truth grep gate per `verify_enum_source_of_truth.sh`).
  - `test_studies_create_contract.py` (extend) — assert `AUTO_FOLLOWUP_STRATEGY_INVALID` (422) on pair-rule violation and value-rule violation; assert `auto_followup_strategy: "follow_suggestions"` round-trips through study create with `auto_followup_depth: 3`.
- **Vitest (UI unit/component) (`ui/src/__tests__/`):**
  - `components/studies/create-study-modal.*.test.tsx` (extend) — toggle hidden when depth = 0; toggle visible with `"narrow"` default when depth ≥ 1; submit payload carries `auto_followup_strategy` (AC-4, AC-5).
  - `components/studies/auto-followup-chain-panel.test.tsx` (extend) — strategy badge per link; null link → no badge; mapping table (AC-13, AC-14).
  - `lib/enums-overnight-strategy-discipline.test.ts` (new) — value-lock for `OVERNIGHT_STRATEGY_VALUES` (mirrors the existing `enums-convergence-discipline.test.ts` pattern at [`feat_study_convergence_indicator`](../../implemented_features/2026_05_31_feat_study_convergence_indicator/feature_spec.md)).
  - `lib/glossary.test.ts` (extend) — value-lock for `overnight_strategy` glossary key (AC-16).
- **E2E (`ui/tests/e2e/`):**
  - `overnight-strategy.spec.ts` (new) — seed via API helpers: anchor study (status=completed, depth=2, strategy=follow_suggestions) + completed digest with a `swap_template` executable + a `narrow` executable persisted via the digest test-seeding helper. **Then explicitly enqueue `enqueue_followup_study` via the test harness's Arq pool helper** (per cycle 1 finding C1-B3 — directly seeding a digest does NOT trigger the digest-worker dispatch in tests, so the autopilot job would never run without explicit enqueue). Wait for the child row to land via a polling assertion on `repo.list_children_of_study(anchor.id)` (test helper). Assert child row has `selected_followup_kind = "swap_template"` AND a different `template_id` than the anchor. Navigate to anchor's `/studies/{id}` page; assert chain panel renders the swap_template badge with `data-testid="chain-link-strategy-{child_id}"`. Per `CLAUDE.md` E2E rules — real backend, no `page.route()` mocking.

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — add `AUTO_FOLLOWUP_STRATEGY_INVALID` to the error code table; mention `selected_followup_kind` as an additive field on `StudyChainLink`.
- `docs/01_architecture/data-model.md` — note the three new optional keys on `studies.config` (`auto_followup_strategy`, `auto_followup_visited_template_ids`, `auto_followup_selected_kind`). No schema diagram changes (JSONB inner shape only).
- `docs/01_architecture/ui-architecture.md` — describe the strategy toggle's pair-validator visibility and the chain-panel badge.
- `docs/03_runbooks/agent-debugging.md` (or a new `overnight-strategy-debugging.md`) — operator-facing playbook for the three new structlog events. Specifically: when `auto_followup_no_executable_candidate_fell_back_to_narrow` fires frequently, the upstream signal is usually "study did not converge — digest is leading with text follow-ups." Recommended action: re-run with a larger trial budget (matches the convergence-indicator's `still_improving` recommendation).
- `docs/04_security/` — no change.
- `docs/05_quality/testing.md` — no change.
- `docs/08_guides/tutorial-first-study.md` — extend Step 12 per FR-9 with the strategy sub-section.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The strategy is opt-in by design — operators see today's behavior unless they explicitly pick `"follow_suggestions"`. No flag needed.
- **Migration/backfill expectations:** None — no schema change. Existing rows satisfy the new contract (absent `auto_followup_strategy` == today's narrow path).
- **Operational readiness gates:** standard CI (lint + typecheck + tests + coverage + smoke) plus the new value-lock vitest + the existing CI enum source-of-truth grep gate.
- **Release gate:** all AC-1 through AC-18 pass; legacy chain-panel tests + legacy auto-followup tests continue passing unmodified.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (config key + validator) | AC-1, AC-2 | Story 1 (backend schemas) | `test_studies_create_contract.py`, schema unit tests | `api-conventions.md` |
| FR-2 (wizard toggle) | AC-4, AC-5 | Story 2 (UI) | `create-study-modal.*.test.tsx`, `enums-overnight-strategy-discipline.test.ts` | `ui-architecture.md` |
| FR-3 (worker dispatch) | AC-3, AC-6, AC-7, AC-9, AC-10, AC-17, AC-18 | Story 3 (backend worker) | `workers/test_auto_followup_strategy.py` (integration — including deleted-swap-target AC-17 + stale-kind-leak AC-18 coverage), `test_auto_followup.py` (existing — unchanged) | `data-model.md` |
| FR-4 (`select_executable_followup`) | AC-6, AC-7, AC-8, AC-9 | Story 3 (backend domain) | `domain/study/test_auto_followup_strategy.py` | — |
| FR-5 (cycle guard state) | AC-7, AC-8, AC-10, AC-11, AC-18 | Story 3 (backend worker) | `workers/test_auto_followup_strategy.py` | `data-model.md` |
| FR-6 (`StudyChainLink` additive field) | AC-11, AC-12 | Story 4 (backend schemas + studies router) | `test_studies_chain_contract.py` | `api-conventions.md` |
| FR-7 (chain panel badges) | AC-13, AC-14 | Story 4 (UI) | `auto-followup-chain-panel.test.tsx`, `overnight-strategy.spec.ts` | — |
| FR-8 (telemetry) | AC-6, AC-8, AC-9, AC-17 | Story 3 (backend worker) | unit + integration assertions on log events (incl. `auto_followup_swap_target_missing` WARN) | runbook |
| FR-9 (glossary + tutorial) | AC-15, AC-16 | Story 5 (docs + UI) | `glossary.test.ts` | `tutorial-first-study.md` |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-18) pass in CI.
- [ ] Backend unit + integration + contract layers green.
- [ ] UI vitest + Playwright E2E green; existing `auto-followup-chain-panel.test.tsx` + `create-study-modal.*.test.tsx` cases still pass unmodified.
- [ ] Coverage gate ≥ 80% holds.
- [ ] Rollout gates from §16 satisfied (no schema change, no migration, no flag).
- [ ] `docs/01_architecture/api-conventions.md` + `data-model.md` + `ui-architecture.md` + `tutorial-first-study.md` updated.
- [ ] Phase 2 + Phase 3 deferred-work tracking files exist as their own planned_features folders (`feat_overnight_final_solution_phase2/`, `feat_overnight_final_solution_phase3/`).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **OQ-1 (resolved at GPT-5.5 cycle 1, finding C1-B1)** — How does the chain-panel badge resolve the "short template name" for a `swap_template` link's display? **Resolved as D-11**: per-link `GET /api/v1/query-templates/{id}` fetch from the frontend (FR-7 updated). Rationale: at most 0–5 extra small fetches per chain, already TanStack-Query-cached client-side, keeps `/chain`'s response shape stable.
- **OQ-2 (resolved at GPT-5.5 cycle 2, finding C2-B3)** — Should the strategy toggle ALSO show as a read-only line on the study detail page? **Resolved as D-15**: deferred to Phase 2 (`feat_overnight_final_solution_phase2/idea.md`). The chain-panel badges per link (FR-7) already surface the strategy a chain link followed; an extra detail-page line would be a redundant secondary surface. If operator feedback during MVP2 says the chain panel is too far down the page to spot quickly, Phase 2 picks it up as part of the morning summary card scope.

_No open questions remain — §18's "no open questions" gate is satisfied._

### Decision log

- **D-1 (2026-06-03)** — Deliberately depart from `feat_overnight_autopilot`'s anti-pattern "do not modify `enqueue_followup_study`". Rationale: that anti-pattern guarded the parent spec's read-only/UI-only scope; this is a deliberate capability extension behind an opt-in toggle. The legacy `"narrow"` path is preserved byte-identically — every existing study and every operator who doesn't change anything keeps today's behavior. The departure is logged here so future readers don't mistake it for drift.
- **D-2 (2026-06-03)** — Strategy is **inherited verbatim** down the chain (idea Fork: locked). Rationale: mid-chain mode switching would break the cycle-guard contract — `visited_template_ids` would need conditional accumulation, which adds bug surface without clear operator value. Operators choose at create time.
- **D-3 (2026-06-03)** — On no executable candidate, **fall back to narrow** (idea Fork A: locked recommended default). Rationale: chain never stalls; depth budget is never wasted; the operator gets *some* exploration even when the digest is text-heavy. The fallback fires a distinct telemetry event so the operator can grep for "this chain didn't use the broader strategy at link N" without ambiguity.
- **D-4 (2026-06-03)** — Make `follow_suggestions` an **opt-in toggle**, not the new default (idea Fork C: locked recommended default). Rationale: the existing narrow loop works correctly and predictably; changing the default would surprise every existing operator. Opt-in lets new operators discover the broader behavior without breaking trust for current ones.
- **D-5 (2026-06-03)** — **Trust the digest's existing ordering**, not a kind-preference policy (idea Fork: trust digest order). Rationale: the digest's system prompt already encodes convergence-aware ordering ("lead with text re-run-with-bigger-budget when not converged; lead with narrow/widen when converged"). Re-ranking inside the autopilot would duplicate that logic AND require the autopilot to consume the convergence verdict — adding coupling without value. First-executable-by-index is the clean rule.
- **D-6 (2026-06-03)** — **No new follow-up kind.** The four-kind taxonomy is locked. Rationale: every new kind would change the digest's structured-output schema + the parse_followup_list contract + downstream consumers. Not justified by the cross-knob exploration goal.
- **D-7 (2026-06-03)** — **No new LLM call** in `enqueue_followup_study`. Rationale: the digest worker already paid the LLM cost and persisted structured output. The autopilot is a pure-DB-read consumer. Adding an LLM call here would re-introduce capability-check + budget-gate + retry surface that the digest already handles.
- **D-8 (2026-06-03)** — **No proposal `superseded` status in Phase 1.** Rationale: requires migration on the `proposals.status` CHECK constraint + a UX decision on whether superseded proposals appear in `/proposals`. Phase 1's `/chain` endpoint's `best_link_id` + `proposal_id_for_best_link` already give the operator a single morning artifact; Phase 3 polishes the rollup further when the friction is felt.
- **D-9 (2026-06-03)** — **Cycle guard is template-based, not search-space-based.** A re-narrowed visit to the *same* template with *different* bounds is allowed (the digest's `narrow`/`widen` on `parent.template_id` doesn't trigger the guard at all — only `swap_template` does, and only against the visited-template set). Rationale: bound-set comparison adds complexity for an attack the guard doesn't need to cover; the goal is preventing template ping-pong, not preventing legitimate re-narrows.
- **D-10 (2026-06-03)** — **Convergence-gated progression is provided by the existing `evaluate_chain_gate` SKIP_NO_LIFT branch — NOT a new stop reason.** When a chain link is `converged` per [`feat_study_convergence_indicator`](../../implemented_features/2026_05_31_feat_study_convergence_indicator/feature_spec.md) (trailing-window improvement ≤ epsilon `0.005`), its `best_metric − baseline_metric` is also ≤ epsilon by construction. The existing chain gate at [`backend/app/domain/study/auto_followup.py:127`](../../../../backend/app/domain/study/auto_followup.py#L127) already SKIPs with `no_lift` in that case, and the existing `/chain` endpoint already reports `stop_reason = "no_lift"`. Rationale: the chain naturally terminates at the converged link without modifying the gate; introducing a `"converged"` stop reason would duplicate the verdict the convergence indicator already surfaces per-link via FR-7 soft contract. The idea's Cap 2 goal is satisfied by composition, not by new infrastructure. (This also means the cross-model reviewer SHOULD NOT propose a new `"converged"` stop reason — it would be redundant with the existing `no_lift` value.)
- **D-11 (2026-06-03, GPT-5.5 cycle 1 finding C1-B1 accept)** — Frontend resolves the `swap_template` link's display name via a per-link `GET /api/v1/query-templates/{id}` fetch, NOT via a new `template_name` field on `StudyChainLink`. Rationale: at most 0–5 extra small fetches per chain (one per `swap_template`-badged link), already TanStack-Query-cached client-side, keeps `/chain`'s response shape stable, avoids forcing the backend chain-summary query to join `query_templates` for a value the frontend already loads in many adjacent contexts.
- **D-12 (2026-06-03, GPT-5.5 cycle 1 findings C1-A1 + C1-A5 accept)** — **Persistence contract for the new `studies.config` keys:**
  - `auto_followup_selected_kind` is persisted ONLY when the worker took a selection-driven path (`"narrow"` / `"widen"` / `"swap_template"`) OR a `follow_suggestions` fallback path (`"narrow_default"`). The **legacy/default path** (strategy `None` / `"narrow"`) persists **no key** — the worker explicitly pops it before INSERT so a parent's lingering value never leaks to the child. This keeps the chain panel byte-identical for legacy chains.
  - `auto_followup_visited_template_ids` is persisted ONLY under `"follow_suggestions"` strategy. The list is **ordered-unique** via `list(dict.fromkeys(...))`; appending a template equal to one already in the list is a no-op for the list contents.
  - Rationale: a single, unambiguous contract everywhere (FR-3, FR-5, FR-6, AC-3, AC-6, AC-9, AC-12, AC-18 all reconcile). The earlier draft had FR-3 and FR-5/AC-12 contradicting each other on the legacy-path persistence — D-12 resolves in favor of the clean-legacy contract.
- **D-13 (2026-06-03, GPT-5.5 cycle 1 finding C1-A3 accept)** — `auto_followup_strategy` field type is `str | None` (NOT `Literal[...]`). The pair-and-value check happens in the `_validate_auto_followup_strategy` model_validator with the message-prefix path so the canonical `AUTO_FOLLOWUP_STRATEGY_INVALID` error code reaches the response envelope. Mirrors the existing `_validate_auto_followup_depth` pattern — a Pydantic `Literal[...]` at field-level would surface generic `VALIDATION_ERROR` for unknown values, violating §8.6's error-code contract.
- **D-14 (2026-06-03, GPT-5.5 cycle 1 finding C1-A4 accept)** — The wizard does NOT write `auto_followup_visited_template_ids`. The worker is the sole writer. The anchor's missing key is treated as `[anchor.template_id]` by the worker. The create-study contract test asserts a wizard-submitted `auto_followup_visited_template_ids` is 422-rejected. Rationale: single-writer rule eliminates the "two writers must agree on the seed value" coordination surface.
- **D-15 (2026-06-03, GPT-5.5 cycle 2 finding C2-B3 accept)** — Strategy read-only line on the study detail page (OQ-2) is deferred to Phase 2 (`feat_overnight_final_solution_phase2/idea.md`). The FR-7 per-link chain-panel badges are sufficient for MVP2; an extra detail-page line is redundant and would crowd the existing detail-page layout. Phase 2 picks it up if operator feedback says the chain panel is too far down to spot quickly during morning review.
