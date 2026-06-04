# Implementation Plan — Overnight → final solution (autonomous cross-knob tuning)

**Date:** 2026-06-03
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rules), [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs from `feature_spec.md` §17.
- **No migration in Phase 1** — all new state is JSONB keys on `studies.config`. Alembic head stays `0022_solr_engine_auth_check`.
- The legacy `"narrow"` path must stay behaviorally byte-identical (per P1-B2): a parent with NO `auto_followup_strategy` key produces a child with identical search-space + template_id + telemetry + NO new config keys. A parent with explicit `"narrow"` produces an identical child EXCEPT it inherits the `auto_followup_strategy: "narrow"` key (the one expected config delta) — still no selected/visited keys, no new telemetry. Backward-compatibility is a hard gate proven by `test_auto_followup.py` passing unmodified.
- Pure-domain selection logic (`select_executable_followup`) is unit-tested without fixtures; the worker dispatch is integration-tested DB-backed.
- The `/chain` endpoint, `StudyChainLink`, `StudyChainResponse`, and `chain_summary.py` all already exist (shipped by `feat_overnight_autopilot`). This plan EXTENDS them additively — it does not create them.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (config key + validator) | Epic 1 / Story 1.1 | `auto_followup_strategy: str \| None` + `_validate_auto_followup_strategy` + `AUTO_FOLLOWUP_STRATEGY_VALUES` constant |
| FR-2 (wizard toggle) | Epic 1 / Story 1.2 | Strategy `<Select>` beneath depth selector, visible only when depth ≥ 1 |
| FR-4 (`select_executable_followup`) | Epic 2 / Story 2.1 | Pure-domain `SelectionOutcome` selector + `SELECTED_FOLLOWUP_KIND_VALUES` |
| FR-3 (worker dispatch) | Epic 2 / Story 2.2 | `enqueue_followup_study` dispatch on strategy |
| FR-5 (cycle-guard state) | Epic 2 / Story 2.2 | `auto_followup_visited_template_ids` + `auto_followup_selected_kind` persistence |
| FR-8 (telemetry) | Epic 2 / Story 2.2 | 2 INFO + 1 WARN events, emitted after child INSERT |
| FR-6 (`StudyChainLink` additive field) | Epic 3 / Story 3.1 | `selected_followup_kind` + defensive coercion at chain-summary construction |
| FR-7 (chain panel badges) | Epic 3 / Story 3.2 | Per-link strategy badge + per-link template-name fetch for swap |
| FR-9 (glossary key) | Epic 1 / Story 1.2 | `overnight_strategy` glossary key ships with the wizard toggle |
| FR-9 (tutorial + runbook) | Epic 4 / Story 4.1 | Tutorial Step 12 sub-section + autopilot runbook event section |

All spec FRs covered. No deferred FRs in Phase 1 (Phase 2 + Phase 3 tracked in `phase2_idea.md` + `phase3_idea.md`).

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Four epics:

- **Epic 1 — Strategy wire contract + wizard surface** (FR-1, FR-2, FR-9 glossary)
- **Epic 2 — Autopilot worker dispatch** (FR-4, FR-3, FR-5, FR-8) — the core capability
- **Epic 3 — Chain-summary surface** (FR-6, FR-7)
- **Epic 4 — Docs** (FR-9 tutorial + runbook)

### Conventions (project-specific)

```
- Domain layer is pure — no DB, no async, no I/O (auto_followup_strategy.py)
- Worker functions are async, accept ctx + args, create their own DB session via get_session_factory()
- StudyConfigSpec validators use @model_validator(mode="after") with the "CODE: message" prefix pattern
  so api/errors.py unwraps the canonical error_code envelope
- JSONB config keys are read with .get(...) defensively (config may be serialized exclude_none)
- Frontend <select> wire values import from ui/src/lib/enums.ts *_VALUES arrays (form-select-discipline rule)
- Glossary entries carry short (≤120 char) + long; value-lock vitest asserts the shape
- All new module-level enum constants carry a // source-of-truth comment + are grepped by
  scripts/ci/verify_enum_source_of_truth.sh
```

### AI Agent Execution Protocol

0. Read `architecture.md` + `state.md` before Story 1.1.
1. Implement Epic 1 (schema + wizard) → Epic 2 (worker — the core) → Epic 3 (chain surface) → Epic 4 (docs).
2. Backend order within a story: domain → schemas → worker → router.
3. Run `make test-unit` + targeted `make test-integration` + `make test-contract` after each backend story; `cd ui && pnpm test` after each frontend story.
4. No migration round-trip needed (no schema change).
5. After the final story, update `state.md` + `architecture.md` + run `bash scripts/regen-generated-artifacts.sh` (the `selected_followup_kind` additive field changes the OpenAPI snapshot + `types.ts`).

---

## Epic 1 — Strategy wire contract + wizard surface

### Story 1.1 — `auto_followup_strategy` config key + validator
**Outcome:** The API accepts `config.auto_followup_strategy ∈ {"narrow","follow_suggestions"}` (or absent/null), 422-rejects bad values + pair-rule violations with `AUTO_FOLLOWUP_STRATEGY_INVALID`, and 422-rejects an operator-submitted `auto_followup_visited_template_ids` (single-writer rule per D-14).

**New files**

| File | Purpose |
|---|---|
| (none) | All changes are additive edits to existing files. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Add `auto_followup_strategy: str \| None = Field(default=None)` to `StudyConfigSpec` (after `auto_followup_depth` at line 716); add module-level `AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")`; add `_validate_auto_followup_strategy` `@model_validator(mode="after")` after `_validate_auto_followup_depth` (line 736); add a SEPARATE `@model_validator(mode="before")` rejecting an operator-submitted `auto_followup_visited_template_ids` (see Task 4 — `mode="before"` is REQUIRED because `StudyConfigSpec` defaults to `extra="ignore"`, which silently drops unknown keys before any `mode="after"` validator runs). |
| [`backend/app/api/errors.py`](../../../../backend/app/api/errors.py) | Add `"AUTO_FOLLOWUP_STRATEGY_INVALID"` to `_CUSTOM_ERROR_CODE_ALLOWLIST` (frozenset at lines 63-68). **This is required** — the prefix unwrap is NOT automatic; the allowlist is the authoritative whitelist (errors.py:58-60 comment: "adding a new code requires adding it here in the same PR that introduces the validator"). Without this, `AUTO_FOLLOWUP_STRATEGY_INVALID:` surfaces as a generic `VALIDATION_ERROR`, breaking AC-1/AC-2. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` (existing) | `{..., config: {auto_followup_depth, auto_followup_strategy}}` | `201` (existing shape) | `AUTO_FOLLOWUP_STRATEGY_INVALID` (422) |

**Key interfaces**

```python
# backend/app/api/v1/schemas.py
AUTO_FOLLOWUP_STRATEGY_VALUES: tuple[str, ...] = ("narrow", "follow_suggestions")
# Source-of-truth for the frontend OVERNIGHT_STRATEGY_VALUES mirror.

class StudyConfigSpec(BaseModel):
    ...
    auto_followup_strategy: str | None = Field(default=None)
    # str | None (NOT Literal) per spec D-13 — the canonical error-code unwrap
    # requires the validator's message-prefix path.

    @model_validator(mode="after")
    def _validate_auto_followup_strategy(self) -> "StudyConfigSpec": ...
    # 1. None → return early.
    # 2. value not in AUTO_FOLLOWUP_STRATEGY_VALUES → raise ValueError(
    #    "AUTO_FOLLOWUP_STRATEGY_INVALID: auto_followup_strategy must be 'narrow' "
    #    "or 'follow_suggestions'; got '<value>'")
    # 3. value set but auto_followup_depth in (None, 0) → raise ValueError(
    #    "AUTO_FOLLOWUP_STRATEGY_INVALID: auto_followup_strategy only applies when "
    #    "auto_followup_depth >= 1")
```

**Tasks**
1. Add the `AUTO_FOLLOWUP_STRATEGY_VALUES` constant + source-of-truth comment.
2. Add the `auto_followup_strategy` field to `StudyConfigSpec`.
3. Add `_validate_auto_followup_strategy` `@model_validator(mode="after")` (value-rule + pair-rule, both raising the `AUTO_FOLLOWUP_STRATEGY_INVALID:` prefix).
4. Add the `auto_followup_visited_template_ids` reject guard as a `@model_validator(mode="before")` (operator may not seed the cycle-guard list — single-writer rule per D-14). **`mode="before"` is required**: `StudyConfigSpec` has NO `model_config` today (Pydantic default `extra="ignore"`), so an unknown key is dropped before a `mode="after"` validator could see it. The before-validator inspects the raw dict: if `"auto_followup_visited_template_ids" in values` (or `auto_followup_selected_kind`), raise `ValueError("AUTO_FOLLOWUP_STRATEGY_INVALID: auto_followup_visited_template_ids is worker-managed and may not be set at study creation")`. **Do NOT add blanket `extra="forbid"`** — it risks rejecting the worker's own JSONB keys if a stored config is ever re-validated through `StudyConfigSpec`, and broadens the blast radius beyond the two worker-managed keys.
5. **Add `"AUTO_FOLLOWUP_STRATEGY_INVALID"` to `_CUSTOM_ERROR_CODE_ALLOWLIST` in `backend/app/api/errors.py`** (lines 63-68). This is mandatory — the prefix unwrap is gated by this allowlist, not automatic. Verify with the existing `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` entry as the pattern.

**Definition of Done (DoD)**
- `make test-unit` green incl. new schema unit tests for the validator (value-rule, pair-rule, None-early-return).
- Contract test (`test_studies_create_contract.py`) asserts: (a) `auto_followup_strategy: "follow_suggestions"` + `auto_followup_depth: 3` round-trips 201 (AC-5 backend half); (b) `"follow_suggestions"` + no depth → 422 `AUTO_FOLLOWUP_STRATEGY_INVALID` (AC-1); (c) `"garbage"` + depth 3 → 422 `AUTO_FOLLOWUP_STRATEGY_INVALID` (AC-2); (d) operator-submitted `auto_followup_visited_template_ids` → 422 (D-14).
- `bash scripts/ci/verify_enum_source_of_truth.sh` passes for the new constant.

### Story 1.2 — Wizard strategy toggle + `overnight_strategy` glossary key
**Outcome:** Step 5 of the create-study modal shows a Strategy `<Select>` directly beneath the depth selector, visible only when depth ≥ 1, defaulting to `"narrow"`, writing `config.auto_followup_strategy` on submit. A new `overnight_strategy` glossary key powers its `InfoTooltip`.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/__tests__/lib/enums-overnight-strategy-discipline.test.ts`](../../../../../ui/src/__tests__/lib/enums-overnight-strategy-discipline.test.ts) | Value-lock vitest for `OVERNIGHT_STRATEGY_VALUES` (mirrors `enums-convergence-discipline.test.ts`). |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) | Add `OVERNIGHT_STRATEGY_VALUES = ['narrow', 'follow_suggestions'] as const` + `type OvernightStrategy` + source-of-truth comment `// Values must match backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES`. |
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../../ui/src/components/studies/create-study-modal.tsx) | Add the Strategy `<Select>` after the depth selector block (after line ~1490, after the depth `<Select>` closes); add `auto_followup_strategy` to the form schema (`0 \| 1 \|...` depth already at line 163); wire submit to write `config.auto_followup_strategy` only when depth ≥ 1 (mirror the depth-omit pattern at line 728); default to `"narrow"` when the toggle becomes visible. |
| [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) | Add `overnight_strategy` entry (short ≤120 + long) under the `feat_overnight_autopilot Story 3.1` block (near line 925). |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../../ui/src/__tests__/lib/glossary.test.ts) | Add value-lock assertion for `overnight_strategy` (short ≤120, includes both wire values verbatim per AC-16). |

**UI element inventory**
- **`<Select>` Strategy toggle** — label `"Strategy"` + `InfoTooltip glossaryKey="overnight_strategy"`; `data-testid="cs-overnight-strategy"`; options from `OVERNIGHT_STRATEGY_VALUES.map(...)` with display labels `"narrow"` → `"Refine the same knobs (predictable)"`, `"follow_suggestions"` → `"Try suggested follow-ups (broader exploration)"`; helper text per spec FR-2. Data source: form state. Interaction: writes `config.auto_followup_strategy` on submit.
- **Visibility:** rendered only when `values.auto_followup_depth >= 1` (mirror the FR-2 hint conditional at line 1443).

**State dependency analysis**
```
State added: auto_followup_strategy (form field, default "narrow")
Referenced by:
  - create-study-modal submit handler (~line 728) — action: write to config only when depth >= 1
  - the new <Select> — action: render + onValueChange
No cross-component state — fully local to the modal.
```

**Enumerated value contract**
| Field | Wire values | Backend source | Frontend site |
|---|---|---|---|
| `auto_followup_strategy` | `narrow`, `follow_suggestions` | `backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES` (Story 1.1) | `OVERNIGHT_STRATEGY_VALUES` in `enums.ts`; `<Select>` in `create-study-modal.tsx` |

**Tasks**
1. Add `OVERNIGHT_STRATEGY_VALUES` to `enums.ts` + the discipline vitest.
2. Add the `overnight_strategy` glossary entry + the glossary value-lock assertion.
3. Add the Strategy `<Select>` to the modal, visible only when depth ≥ 1, using the `*_VALUES.map(...)` form-select-discipline pattern (NOT inline `<SelectItem value="...">`).
4. Wire the submit handler to write `config.auto_followup_strategy` only when depth ≥ 1; default `"narrow"` when toggle appears.
5. Confirm `make` / `pnpm lint` passes the form-select-discipline + data-table-column-discipline guards.

**Definition of Done (DoD)** — naming exact files (per P1-A5):
- `cd ui && pnpm test` green incl. these files: `create-study-modal.*.test.tsx` (toggle hidden when depth=0 AC-4; toggle visible w/ `"narrow"` default when depth≥1 AC-4; submit payload carries `auto_followup_strategy` AC-5); `glossary.test.ts` (`overnight_strategy` value-lock AC-16); `enums-overnight-strategy-discipline.test.ts` (`OVERNIGHT_STRATEGY_VALUES` value-lock).
- `cd ui && pnpm lint` + `pnpm typecheck` green (form-select-discipline guard passes).

---

## Epic 2 — Autopilot worker dispatch (core)

### Story 2.1 — Pure-domain `select_executable_followup` + `SelectionOutcome`
**Outcome:** A pure, deterministic selector that, given a digest's parsed follow-up list + the visited-template set, returns a `SelectionOutcome` (selected item or None + source_index + candidate_count + dropped_template_ids).

**New files**

| File | Purpose |
|---|---|
| [`backend/app/domain/study/auto_followup_strategy.py`](../../../../backend/app/domain/study/auto_followup_strategy.py) | `SelectionOutcome` dataclass, `select_executable_followup(...)`, `SELECTED_FOLLOWUP_KIND_VALUES` constant. Pure domain. |
| [`backend/tests/unit/domain/study/test_auto_followup_strategy.py`](../../../../backend/tests/unit/domain/study/test_auto_followup_strategy.py) | Unit tests for the selector matrix. |

**Modified files**

| File | Change |
|---|---|
| (none) | New module only. |

**Key interfaces**

```python
# backend/app/domain/study/auto_followup_strategy.py
from dataclasses import dataclass
from backend.app.domain.study.followups import (
    FollowupItem, NarrowFollowup, WidenFollowup, SwapTemplateFollowup, TextFollowup,
)

SELECTED_FOLLOWUP_KIND_VALUES: tuple[str, ...] = (
    "narrow_default", "narrow", "widen", "swap_template",
)
# Source-of-truth for StudyChainLink.selected_followup_kind + the frontend mirror.

@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    selected: FollowupItem | None
    source_index: int | None
    candidate_count: int
    dropped_template_ids: list[str]   # sorted ascending; always populated

def select_executable_followup(
    followups: list[FollowupItem],
    visited_template_ids: set[str],
) -> SelectionOutcome: ...
# Pure. Never None (the no-candidate case is SelectionOutcome(selected=None, ...)).
# Drops TextFollowup; drops SwapTemplateFollowup whose template_id ∈ visited
# (recording the dropped id); first remaining by original index is selected.
```

**Tasks**
1. Define `SELECTED_FOLLOWUP_KIND_VALUES` + source-of-truth comment.
2. Define `SelectionOutcome` frozen dataclass.
3. Implement `select_executable_followup` per spec FR-4 (single walk recording original index; text-drop; swap cycle-guard drop; first-executable-by-index selection; always-return-outcome).
4. Add `__all__` exports.
5. Write the unit-test matrix (see §3.1).

**Definition of Done (DoD)**
- `make test-unit` green incl. the selector matrix: empty list → `selected=None`; text-only → `selected=None`; mixed text+narrow → narrow at source_index; swap(visited)+widen → widen selected, swap in `dropped_template_ids` (AC-8); swap(non-visited) → swap selected (AC-7 selector half); all-swaps-cycle-dropped → `selected=None` with non-empty `dropped_template_ids` (AC-9 selector half); multiple executable → first-by-index wins.
- `bash scripts/ci/verify_enum_source_of_truth.sh` passes for `SELECTED_FOLLOWUP_KIND_VALUES`.
- Determinism: same input → same output (property-style assertion).

### Story 2.2 — `enqueue_followup_study` dispatch + cycle-guard state + telemetry
**Outcome:** Under `follow_suggestions`, the autopilot worker consumes the top executable follow-up (narrow/widen/swap_template), branches `template_id` on swap, persists the cycle-guard list + selected-kind, falls back to narrow on no candidate / deleted swap target, and emits the new telemetry. Under `"narrow"`/default, behavior is byte-identical to today.

**Modified files**

| File | Change |
|---|---|
| [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py) | Insert the strategy dispatch between step 7 (load template + winner, line 197) and step 8 (build child config, line 217). Read `parent.config.get("auto_followup_strategy")`; on `"follow_suggestions"` load the digest, `parse_followup_list`, `select_executable_followup`, dispatch per outcome; persist `auto_followup_selected_kind` + `auto_followup_visited_template_ids` into `child_config`; pop inherited `auto_followup_selected_kind` on the legacy path. **Telemetry timing (per P1-B1 + spec FR-8):** the two INFO events (`auto_followup_strategy_selected`, `auto_followup_no_executable_candidate_fell_back_to_narrow`) emit AFTER the child INSERT/commit (so `child_study_id` is populated); the WARN `auto_followup_swap_target_missing` emits BEFORE the fallback decision with parent-only fields (no `child_study_id` — none exists yet). Wrap the whole follow_suggestions block in a defensive try/except → narrow fallback + WARN (per P1-B4 + spec §13). |

**Key interfaces**

```python
# backend/workers/auto_followup.py (inside enqueue_followup_study, after step 7)
strategy = parent.config.get("auto_followup_strategy")  # None | "narrow" | "follow_suggestions"

# child_config baseline (existing pattern at line 223), then strategy-specific mutation:
child_config = {**parent.config, "auto_followup_depth": remaining}
child_config.pop("auto_followup_selected_kind", None)  # never inherit per-link state

if strategy == "follow_suggestions":
    digest = await repo.get_digest_for_study(db, parent_study_id)  # verify repo fn name
    followups = parse_followup_list(
        digest.suggested_followups if digest else [], study_id=parent_study_id,
    )
    visited = set(parent.config.get("auto_followup_visited_template_ids", [parent.template_id]))
    outcome = select_executable_followup(followups, visited)
    # dispatch: narrow/widen → keep parent.template_id + outcome.selected.search_space
    #           swap_template → repo.get_query_template defensive; on miss → fallback+WARN
    #           selected is None → fallback narrow + "narrow_default"
    # persist child_config["auto_followup_visited_template_ids"] = ordered_unique(...)
    # persist child_config["auto_followup_selected_kind"] = <kind>
# else: legacy narrow path UNCHANGED (no selected_kind key)
```

**Tasks**
1. Read the existing worker top-to-bottom; confirm the repo accessor for the digest row (`repo.get_digest_for_study` or equivalent — grep `backend/app/db/repo/` and fix the name in the interface above if different).
2. Insert the strategy read + dispatch between steps 7 and 8.
3. Implement the four sub-paths (narrow-suggested, widen, swap_template-with-defensive-get, fallback-to-narrow) per spec FR-3.
4. Implement the `ordered_unique` visited-list append (`list(dict.fromkeys(...))`).
5. Implement the legacy-path `pop("auto_followup_selected_kind", None)` so a parent's lingering value never leaks.
6. Emit the 2 INFO events (after child INSERT/commit) + the WARN (`auto_followup_swap_target_missing`, before fallback, parent-only fields) per FR-8 + P1-B1.
7. Inherit `auto_followup_strategy` verbatim into `child_config` (already covered by the `{**parent.config}` spread; verify the depth-decrement doesn't strip it).
8. **Wrap the follow_suggestions dispatch block in a defensive `try/except Exception`** (per P1-B4 + spec §13 Reliability): any unexpected error in digest read / parse / select → log a WARN + fall back to today's narrow path with `auto_followup_selected_kind = "narrow_default"`. Chain reliability must not regress vs the legacy path.

**Definition of Done (DoD)**
- `make test-integration` green incl. (DB-backed, in `backend/tests/integration/test_auto_followup_strategy.py` — flat path matching the existing `test_auto_followup.py` convention; NOT `integration/workers/`, per P1-A3): AC-3 (legacy: no new keys, byte-identical behavior), AC-6 (narrow consumed), AC-7 (swap branches template_id), **AC-8 worker-level** (swap-to-visited dropped → widen selected, visited list correct, `dropped_template_ids` in telemetry — per P1-B3), AC-9 (fallback on text-only), AC-10 (strategy inherited), AC-17 (deleted swap target → WARN + fallback), AC-18 (no parent selected_kind leak), **exception-fallback** (forced digest-parse error → narrow fallback + WARN, per P1-B4).
- Telemetry assertions: `auto_followup_strategy_selected` fires (AFTER INSERT) with `child_study_id` + `source_index` + `dropped_template_ids` (AC-6, AC-8); `auto_followup_no_executable_candidate_fell_back_to_narrow` fires AFTER INSERT (AC-9); `auto_followup_swap_target_missing` WARN fires BEFORE fallback with parent-only fields (AC-17).
- **Backward-compat gate (per P1-B2):** existing `backend/tests/integration/test_auto_followup.py` cases pass UNMODIFIED. Precise contract: for a parent with NO `auto_followup_strategy` key, the child's search-space + template_id + telemetry + `auto_followup_selected_kind`/`auto_followup_visited_template_ids` absence are byte-identical to pre-feature. For a parent with explicit `auto_followup_strategy: "narrow"`, the child additionally inherits the `auto_followup_strategy: "narrow"` key (the one expected config delta) but still adds NO selected/visited keys and emits NO new telemetry — behavior is identical, only the inherited strategy key differs.

---

## Epic 3 — Chain-summary surface

### Story 3.1 — `StudyChainLink.selected_followup_kind` additive field + defensive coercion
**Outcome:** The `/chain` endpoint returns each link's `selected_followup_kind` (null for anchor + legacy chains), with malformed JSONB values coerced to null + WARN rather than 500ing the endpoint.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Add TWO additive fields to `StudyChainLink` (after line 885): `selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] \| None = None` AND `template_id: str` (NON-optional — every study has a `template_id`; needed by Story 3.2's swap-badge name fetch per P1-B5). |
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | In the **per-link `StudyChainLink(...)` assembly** (the `for lk in traversal.links:` loop at lines ~856-880, VERIFIED — NOT in `chain_summary.py`, which only computes `stop_reason`/`cumulative_lift`/`best_link`): add `template_id=lk.template_id`; read `raw = lk.config.get("auto_followup_selected_kind")`, coerce to null + emit `chain_selected_kind_unknown` WARN when `raw not in SELECTED_FOLLOWUP_KIND_VALUES` and non-None, pass as `selected_followup_kind`. |

**Key interfaces**

```python
# backend/app/api/v1/schemas.py
class StudyChainLink(BaseModel):
    ...  # existing 12 fields
    template_id: str                       # NEW — non-optional; from studies.template_id (P1-B5)
    selected_followup_kind: Literal["narrow_default","narrow","widen","swap_template"] | None = None

# backend/app/api/v1/studies.py — inside the existing `for lk in traversal.links:` loop (~line 856)
raw = lk.config.get("auto_followup_selected_kind")
selected_kind = raw if raw in SELECTED_FOLLOWUP_KIND_VALUES else None
if raw is not None and raw not in SELECTED_FOLLOWUP_KIND_VALUES:
    logger.warning("chain_selected_kind_unknown", study_id=lk.id, raw=str(raw)[:64])
# ... StudyChainLink(..., template_id=lk.template_id, selected_followup_kind=selected_kind)
```

**Tasks**
1. Add the two additive fields (`template_id`, `selected_followup_kind`) to `StudyChainLink`.
2. Import `SELECTED_FOLLOWUP_KIND_VALUES` from `backend.app.domain.study.auto_followup_strategy` into `studies.py`.
3. In the existing per-link assembly loop (`for lk in traversal.links:`, VERIFIED at studies.py:856-880 — this is where `StudyChainLink` is built, NOT `chain_summary.py`), add `template_id=lk.template_id` + the coerce-unknown-to-null + WARN logic for `selected_followup_kind`.
4. Regenerate the OpenAPI snapshot + `types.ts` (`bash scripts/regen-generated-artifacts.sh`).

**Definition of Done (DoD)**
- `make test-contract` green: `test_studies_chain_contract.py` asserts `selected_followup_kind` optional (four values + null) AND `template_id` present non-null on every link (AC-11, AC-12).
- `make test-integration` green: `test_studies_chain_api.py` asserts a 3-link chain returns anchor `selected_followup_kind=null`, link2="narrow", link3="swap_template" + each link's `template_id` populated (AC-11); a legacy chain returns all `selected_followup_kind=null` (AC-12); a malformed `config.auto_followup_selected_kind` coerces to null without 500.
- Generated-artifacts freshness gate green (snapshot + `types.ts` regenerated).

### Story 3.2 — Chain-panel per-link strategy badge
**Outcome:** The chain panel renders a compact badge per link reflecting `selected_followup_kind`; swap_template links show the target template's short name via a per-link `GET /api/v1/query-templates/{id}` fetch.

**New files**

| File | Purpose |
|---|---|
| [`ui/src/__tests__/lib/enums-selected-followup-kind-discipline.test.ts`](../../../../../ui/src/__tests__/lib/enums-selected-followup-kind-discipline.test.ts) | Value-lock vitest for `SELECTED_FOLLOWUP_KIND_VALUES` (mirrors `enums-convergence-discipline.test.ts`) — per P1-A1. |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) | Add `SELECTED_FOLLOWUP_KIND_VALUES = ['narrow_default', 'narrow', 'widen', 'swap_template'] as const` + `type SelectedFollowupKind` + source-of-truth comment `// Values must match backend/app/domain/study/auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES` (P1-A1 — the second new enum needs a frontend mirror + discipline test, not just an inline comment). |
| [`ui/src/components/studies/auto-followup-chain-panel.tsx`](../../../../../ui/src/components/studies/auto-followup-chain-panel.tsx) | In the `chain.links.map((link) => {...})` block (line 191), add a badge per the FR-7 mapping keyed on `link.selected_followup_kind` (typed via the `SelectedFollowupKind` import); for `swap_template` links, fetch the template name via the existing query-template hook (or a minimal new one) using `link.template_id` (now present per Story 3.1); add `data-testid="chain-link-strategy-{link.id}"`. |
| [`ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`](../../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx) | Add badge-rendering cases (AC-13, AC-14); preserve all existing cases. |

**UI element inventory**
- **Per-link strategy badge** — mapping: `null`→no badge; `"narrow_default"`→`"refined"`; `"narrow"`→`"narrow ↓"`; `"widen"`→`"widen ↑"`; `"swap_template"`→`"swapped to {short_template_name}"` (truncate name to 30 chars). `data-testid="chain-link-strategy-{link.id}"`. Data source: `link.selected_followup_kind` + (for swap) a `GET /api/v1/query-templates/{link.template_id}` fetch.

**Enumerated value contract**
| Field | Wire values | Backend source | Frontend site |
|---|---|---|---|
| `selected_followup_kind` | `narrow_default`, `narrow`, `widen`, `swap_template`, null | `backend/app/domain/study/auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES` (Story 2.1) | badge mapping in `auto-followup-chain-panel.tsx` |

**Tasks**
1. Add `SELECTED_FOLLOWUP_KIND_VALUES` to `enums.ts` + the discipline vitest (`enums-selected-followup-kind-discipline.test.ts`).
2. Add the badge mapping in the link `.map(...)` block, keyed on `link.selected_followup_kind` (typed via `SelectedFollowupKind`), with the source-of-truth comment.
3. For swap_template links, resolve the template short name via the existing template-fetch hook (grep `ui/src/` for an existing `useQueryTemplate` / `GET /api/v1/query-templates/{id}` consumer; reuse it; if none, add a minimal colocated hook) using `link.template_id`.
4. Add `data-testid` per badge; preserve all existing panel tests.

**Definition of Done (DoD)**
- `cd ui && pnpm test` green incl. the named files: `auto-followup-chain-panel.test.tsx` (badge renders per-link AC-13; no badge when all links null AC-14; existing cases unchanged) + `enums-selected-followup-kind-discipline.test.ts` (value-lock).
- **E2E (owned by this story):** `ui/tests/e2e/overnight-strategy.spec.ts` (NEW, §3.4) — seed anchor (depth=2, strategy=follow_suggestions) + digest with swap_template + narrow executables via API helpers; explicitly enqueue `enqueue_followup_study` via the test Arq helper; poll `list_children_of_study` for the child; assert child `selected_followup_kind="swap_template"` + different `template_id`; navigate to `/studies/{anchor}`; assert the swap_template badge renders. Real backend, no `page.route()`.

---

## Epic 4 — Docs

### Story 4.1 — Tutorial strategy sub-section + autopilot runbook events
**Outcome:** The tutorial explains the strategy choice + the cycle guard + the narrow fallback; the autopilot runbook documents the 3 new telemetry events.

**Modified files**

| File | Change |
|---|---|
| [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) | Extend Step 12 ("Run the loop overnight") with a strategy sub-section per FR-9: `"narrow"` vs `"follow_suggestions"`, the cycle guard, the always-fall-back-to-narrow contract. |
| `docs/03_runbooks/agent-debugging.md` (or new `overnight-strategy-debugging.md`) | Document `auto_followup_strategy_selected`, `auto_followup_no_executable_candidate_fell_back_to_narrow`, `auto_followup_swap_target_missing` — grep patterns + operational meaning + "frequent fallback ⇒ digest is text-heavy ⇒ re-run with bigger budget". |
| [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) | Add `AUTO_FOLLOWUP_STRATEGY_INVALID` to the error code table; note `selected_followup_kind` additive on `StudyChainLink`. |
| [`docs/01_architecture/data-model.md`](../../../../01_architecture/data-model.md) | Note the 3 new optional `studies.config` keys. |
| [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md) | Describe the strategy toggle visibility + the chain-panel badge. |
| [`ui/public/docs/`](../../../../../ui/public/docs/) | Regenerated by `copy-docs` if the tutorial is mirrored (run `bash scripts/regen-generated-artifacts.sh`). |

**Tasks**
1. Write the tutorial sub-section (AC-15).
2. Write the runbook event section.
3. Update the three architecture docs.
4. Run `bash scripts/regen-generated-artifacts.sh` to refresh any mirrored docs.

**Definition of Done (DoD)**
- Tutorial Step 12 has the strategy sub-section naming the cycle guard + fallback (AC-15).
- Runbook documents all 3 events.
- `copy-docs-freshness` + `generated-artifacts-fresh` CI gates green.

---

## UI Guidance

### Reference: current component structure

**`ui/src/components/studies/create-study-modal.tsx`** (~1500+ lines). Step 5 ("Objective + config") contains: the preset selector, the `max_trials`/`seed` grid (lines ~1400-1435), the FR-2 overnight hint (lines 1439-1453), and the depth `<Select>` (lines 1460-~1490, label `🌙 Run overnight (compound automatically)`, `data-testid="cs-auto-followup"`, `InfoTooltip glossaryKey="overnight_autopilot"`). **Insertion point for the Strategy toggle:** immediately after the depth `<Select>`'s closing `</div>` (after ~line 1490), before whatever Step-5 element follows.

**`ui/src/components/studies/auto-followup-chain-panel.tsx`**. The link list is `chain.links.map((link) => {...})` at line 191. **Insertion point for the badge:** inside the per-link render, adjacent to the existing name/status/metric display.

### Analogous markup patterns

```tsx
{/* Strategy <Select> — mirror the existing depth selector at create-study-modal.tsx:1460-1490.
    Use the *_VALUES.map() form-select-discipline pattern (NOT inline <SelectItem value="...">). */}
{values.auto_followup_depth !== undefined && values.auto_followup_depth >= 1 && (
  <div className="space-y-1.5">
    <div className="flex items-center gap-1">
      <Label htmlFor="cs-overnight-strategy">Strategy</Label>
      <InfoTooltip glossaryKey="overnight_strategy" />
    </div>
    <Select
      value={values.auto_followup_strategy ?? 'narrow'}
      onValueChange={(v: string) => form.setValue('auto_followup_strategy', v as OvernightStrategy)}
    >
      <SelectTrigger id="cs-overnight-strategy" data-testid="cs-overnight-strategy">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {OVERNIGHT_STRATEGY_VALUES.map((s) => (
          <SelectItem key={s} value={s}>
            {s === 'narrow' ? 'Refine the same knobs (predictable)'
              : 'Try suggested follow-ups (broader exploration)'}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
    <p className="text-xs text-muted-foreground">
      Refine: each follow-up tightens around the previous winner on the same knobs.
      Try suggestions: each follow-up acts on the digest's top runnable recommendation,
      which may switch knobs or templates. Refine is the safer default; Try suggestions explores broader.
    </p>
  </div>
)}
```

```tsx
{/* Per-link strategy badge — inside chain.links.map at auto-followup-chain-panel.tsx:191.
    // Values must match backend/app/domain/study/auto_followup_strategy.py SELECTED_FOLLOWUP_KIND_VALUES */}
{link.selected_followup_kind && (
  <span data-testid={`chain-link-strategy-${link.id}`} className="text-xs text-muted-foreground ml-2">
    {link.selected_followup_kind === 'narrow_default' ? 'refined'
      : link.selected_followup_kind === 'narrow' ? 'narrow ↓'
      : link.selected_followup_kind === 'widen' ? 'widen ↑'
      : `swapped to ${swapTemplateName ?? '…'}`}
  </span>
)}
```

### Layout and structure
- Strategy toggle: same `space-y-1.5` vertical rhythm as adjacent Step-5 controls; stacked below the depth selector.
- Badge: inline, trailing the link's metric, muted text weight so it doesn't compete with the name.

### Information architecture placement
- Strategy toggle lives in Step 5 of the create-study modal, directly below the existing overnight depth selector — no new step, no new screen.
- Badge lives inline in the existing chain panel on `/studies/{id}` — no new surface.

### Tooltips and contextual help
| Element | Glossary key | Source-of-truth comment | Pattern |
|---|---|---|---|
| Strategy `<Select>` label | `overnight_strategy` (NEW) | n/a (glossary entry, not enum) | `<InfoTooltip glossaryKey="overnight_strategy" />` — same as the adjacent depth selector's `overnight_autopilot` tooltip |

### Legacy behavior parity
No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. Both frontend stories are additive (a new `<Select>` and a new badge); no component is removed or rewritten.

### Client-side persistence
Not applicable — no `localStorage`/`sessionStorage`. The strategy is form state submitted to the backend.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `domain/study/test_auto_followup_strategy.py` (NEW) — `select_executable_followup` matrix (Story 2.1 DoD list).
  - [ ] `api/` schema unit tests for `_validate_auto_followup_strategy` (Story 1.1) — value-rule, pair-rule, None-early-return.
- DoD: critical branches deterministic.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Tasks:
  - [ ] `backend/tests/integration/test_auto_followup_strategy.py` (NEW — flat path, matching the existing `test_auto_followup.py` convention; NOT under `integration/workers/`) — DB-backed worker dispatch: AC-3, AC-6, AC-7, AC-8 (worker-level), AC-9, AC-10, AC-17, AC-18 + exception-fallback + telemetry-event assertions. (Owned by Story 2.2 DoD.)
  - [ ] `backend/tests/integration/test_studies_chain_api.py` (EXTEND) — `selected_followup_kind` + `template_id` population (AC-11, AC-12) + malformed-config coercion. (Owned by Story 3.1 DoD.)
- DoD: happy path + fallback + cycle-guard + deleted-swap-target + exception-fallback + legacy-parity covered.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Tasks:
  - [ ] `test_studies_create_contract.py` (EXTEND) — `AUTO_FOLLOWUP_STRATEGY_INVALID` (AC-1, AC-2), round-trip (AC-5 half), visited-list reject (D-14).
  - [ ] `test_studies_chain_contract.py` (EXTEND) — `selected_followup_kind` optional field + enum values (AC-11).
- DoD: the one new error code (`AUTO_FOLLOWUP_STRATEGY_INVALID`) has contract coverage.

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- Tasks:
  - [ ] `ui/tests/e2e/overnight-strategy.spec.ts` (NEW) — seed anchor (depth=2, strategy=follow_suggestions) + digest with swap_template + narrow executables via API helpers; **explicitly enqueue `enqueue_followup_study` via the test Arq helper** (cycle 1 finding C1-B3); poll `list_children_of_study` for the child; assert child `selected_followup_kind = "swap_template"` + different `template_id`; navigate to `/studies/{anchor}`; assert the swap_template badge renders. Real backend, no `page.route()`. **Owned by Story 3.2 DoD** (per P1-A4).
- DoD: tests use `page` for browser assertions; setup via `request`.

### 3.5 Existing test impact audit
| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_auto_followup.py` | legacy narrow-path dispatch | ~existing | No change — legacy path is byte-identical; tests must stay green unmodified (the backward-compat gate). |
| `backend/tests/integration/test_studies_chain_api.py` | chain endpoint shape | ~existing | Extend with `selected_followup_kind` cases; existing assertions unchanged (additive field). |
| `backend/tests/contract/test_studies_chain_contract.py` | chain response schema | ~existing | Extend; existing assertions unchanged. |
| `ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx` | panel rendering | ~existing | Extend with badge cases; existing cases unchanged. |
| `ui/src/__tests__/components/studies/create-study-modal.*.test.tsx` | wizard | ~existing | Extend with strategy-toggle cases; existing depth-selector assertions unchanged. |

### 3.5 Migration verification
Not applicable — no schema change in Phase 1. Alembic head stays `0022_solr_engine_auth_check`.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm build`
- [ ] `bash scripts/regen-generated-artifacts.sh` (clean tree — `selected_followup_kind` changes the OpenAPI snapshot)

---

## 4) Documentation update workstream

### 4.0 Core context files
- [ ] `state.md` — update Last-5-merges + current-branch context on merge (Epic 4 / finalization).
- [ ] `architecture.md` — note the autopilot's strategy-aware dispatch + the `selected_followup_kind` surface.
- [ ] `CLAUDE.md` — no new Absolute Rule; optionally note the `auto_followup_strategy` config key under Settings conventions if warranted.

### 4.1 Architecture docs
- [ ] `api-conventions.md` (Story 4.1), `data-model.md` (Story 4.1), `ui-architecture.md` (Story 4.1).

### 4.3 Runbooks
- [ ] Autopilot strategy events runbook (Story 4.1).

### 4.6 Guides
- [ ] `tutorial-first-study.md` Step 12 strategy sub-section (Story 4.1).

**Documentation DoD**
- [ ] `state.md` + `architecture.md` consistent with shipped behavior.
- [ ] Docs/01 + /03 + /08 consistent with the contract.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- None required — this is a purely additive feature. The legacy narrow path is preserved verbatim (the backward-compat gate forbids refactoring it).

### 5.2 Planned refactor tasks
- [ ] None. Resist the temptation to "clean up" `enqueue_followup_study` while adding the dispatch — the byte-identical legacy-path requirement (AC-3) makes any refactor a regression risk.

### 5.3 Refactor guardrails
- [ ] `test_auto_followup.py` passes unmodified — proof the legacy path is untouched.

---

## 6) Dependencies, risks, and mitigations

### Dependencies
| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_executable_followups_swap_template` (persisted remap) | Story 2.2 | Implemented (PR #232) | High — without persisted remap the worker would need to re-remap. Locked. |
| `feat_overnight_autopilot` (`/chain` + `StudyChainLink` + panel) | Story 3.1, 3.2 | Implemented (PR #343) | N/A — shipped. |
| `parse_followup_list` defensive ingest | Story 2.2 | Implemented (PR #225) | N/A — shipped. |

### Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Refactoring the legacy worker path while inserting the dispatch breaks byte-identical behavior | M | H | `test_auto_followup.py` unmodified-pass gate; dispatch inserted as a discrete branch, not a rewrite. |
| `repo.get_digest_for_study` accessor name wrong in the plan | M | L | Story 2.2 Task 1 greps the repo layer to confirm the actual name before coding. |
| `StudyConfigSpec` not `extra="forbid"` → visited-list reject (D-14) needs a targeted guard | M | L | Story 1.1 Task 4 reads the model first; chooses targeted check vs `extra="forbid"` based on what won't break existing keys. |

### Failure mode catalog
| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Digest row missing under follow_suggestions | manual digest deletion mid-chain | WARN + fall back to narrow | auto (chain continues) |
| Swap target template deleted | template hard-deleted between digest + dispatch | `auto_followup_swap_target_missing` WARN + fall back to narrow | auto |
| Malformed `config.auto_followup_selected_kind` in DB | manual INSERT / schema drift | coerce to null + `chain_selected_kind_unknown` WARN; no 500 | auto |
| All executable candidates cycle-dropped | digest emits only swap_templates to visited templates | `selected=None` → fallback narrow; `dropped_template_ids` populated on the fallback event | auto |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 Story 1.1 (schema — unblocks the wire contract).
2. Epic 2 Story 2.1 (pure selector — unblocks 2.2; parallelizable with 1.2).
3. Epic 2 Story 2.2 (worker dispatch — the core; depends on 1.1 + 2.1).
4. Epic 1 Story 1.2 (wizard — depends on 1.1's enum constant; parallelizable with Epic 2).
5. Epic 3 Story 3.1 (chain field — depends on 2.1's `SELECTED_FOLLOWUP_KIND_VALUES`).
6. Epic 3 Story 3.2 (panel badge — depends on 3.1).
7. Epic 4 Story 4.1 (docs — last).

### Parallelization opportunities
- Story 2.1 (pure domain) + Story 1.2 (wizard) can run in parallel after 1.1.
- Story 3.1 can start once 2.1's enum constant lands (doesn't need 2.2).

## 8) Rollout and cutover plan

- **Rollout:** no flag, no migration. The strategy is opt-in by design — operators see today's behavior until they pick `"follow_suggestions"`.
- **Cutover:** none. Existing chains continue on the legacy path.
- **Reconciliation:** none — no external systems.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — config key + validator
- [ ] Story 1.2 — wizard toggle + glossary key
- [ ] Story 2.1 — pure-domain selector
- [ ] Story 2.2 — worker dispatch + cycle guard + telemetry
- [ ] Story 3.1 — `StudyChainLink.selected_followup_kind` + coercion
- [ ] Story 3.2 — chain-panel badge
- [ ] Story 4.1 — docs (tutorial + runbook + arch)

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

Per story: files match scope; the one new endpoint-affecting change (`POST /studies` accepting `auto_followup_strategy`) + the `/chain` additive field implemented exactly; key interfaces match; tests at every touched layer; `make test-unit` + targeted `make test-integration` + `make test-contract` + `cd ui && pnpm test` pass; no migration (verify Alembic head unchanged at `0022`); docs updated in the same PR when the contract changed.

## 11) Plan consistency review

1. **Endpoint count:** spec §8.1 lists 2 affected endpoints (`POST /studies` additive field, `GET /chain` additive field) — both covered (Story 1.1 + Story 3.1). No new endpoint. ✓
2. **Error code coverage:** spec §8.6 lists 1 new code `AUTO_FOLLOWUP_STRATEGY_INVALID` — covered by Story 1.1 contract test (AC-1, AC-2). ✓
3. **FR coverage:** all 9 FRs in §1 traceability table, each assigned to ≥1 story. ✓
4. **Story internal consistency:** no new-file ownership conflicts (only `auto_followup_strategy.py` + 2 new test files are net-new; all else are edits). ✓
5. **Test file assignment:** every test file assigned to a story's DoD (§3 inventory ↔ stories). ✓
6. **Gate arithmetic:** no numeric gates beyond AC-1..18, all mapped in §17 of the spec. ✓
7. **Open questions:** spec §19 OQ-1 + OQ-2 both resolved (D-11, D-15). ✓
8. **Infra paths:** Alembic head `0022` verified (no migration); `auto_followup_strategy.py` path matches the `backend/app/domain/study/` layout; `studies.py` chain builder + `schemas.py` `StudyChainLink` verified to exist. ✓
9. **Frontend plumbing:** `link.selected_followup_kind` flows from the `/chain` response (Story 3.1) to the panel (Story 3.2); `OVERNIGHT_STRATEGY_VALUES` flows from `enums.ts` to the modal. ✓
10. **Enumerated value contracts:** two enumerated fields (`auto_followup_strategy`, `selected_followup_kind`) both have backend source-of-truth constants (`AUTO_FOLLOWUP_STRATEGY_VALUES`, `SELECTED_FOLLOWUP_KIND_VALUES`) + frontend mirrors + discipline tests. ✓
11. **Audit-event coverage:** the autopilot's child-study creation is an existing mutation covered by `feat_auto_followup_studies`' obligations (currently N/A pre-MVP3 — no `audit_log` until MVP3). This feature adds no new `audit_log`-requiring mutation; the 3 new events are structlog-only. Explicitly justified. ✓

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, (endpoints where applicable), key interfaces, tasks, DoD.
- [x] Test layers (unit/integration/contract/e2e) explicitly scoped + assigned.
- [x] Doc updates planned (Story 4.1 + finalization).
- [x] Lean refactor scope = none (additive feature; legacy path frozen).
- [x] Epic gates measurable (per-story DoD).
- [x] Story-by-Story Verification Gate included.
- [ ] Plan consistency review (§11) performed — pending GPT-5.5 cross-model pass.
