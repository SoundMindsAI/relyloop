# Implementation Plan — `swap_template` LLM-Suggested Followups (Tier B)

**Date:** 2026-05-24
**Status:** Ready for Execution (GPT-5.5 cross-model review: 2 cycles — 7 accepted (cycle 1) / 4 rejected with cited counter-evidence (cycle 2 — convergence))
**Primary spec:** [`feature_spec.md`](./feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rules #1, #5, #8, #10; Enumerated Value Contract Discipline)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- Tier-A (sibling, shipped 2026-05-24): [`feat_digest_executable_followups/implementation_plan.md`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/implementation_plan.md) — structural template for this Tier-B plan
- Related implementations: `feat_agent_propose_search_space` (provides `build_starter_search_space`), `feat_create_study_search_space_builder` (search-space row primitive reuse)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from spec §17.
- Tier-A patterns are the structural template — story shapes (Domain → Worker/Prompts → API → Frontend → E2E), test-layer choice, and DoD style mirror the shipped Tier-A plan one-to-one.
- Fail-loud tests: assert explicit status, shape, error codes, and structlog reason codes.
- Keep increments narrow enough to verify independently — domain helper → discriminated-union widening → LLM schema/prompts → worker remap → API response widening → frontend card + prefill → E2E.
- **Single-phase delivery.** No deferred phases — Tier C (`edit_template`) lives at sibling [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md) and is not gated by this work.
- **No new migration.** Tier-A's JSONB column + lineage columns + CHECK constraint + BEFORE DELETE trigger apply unchanged (spec §3, FR-13).

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 (domain union) | Add `SwapTemplateFollowup` model, widen `FollowupItem` alias, widen `FOLLOWUP_KIND_VALUES` tuple, export from `__all__`. |
| FR-2 | Epic 1 / Story 1.1 (defensive parser pickup) | No new code path — `parse_followup_list` + `FollowupItemAdapter` pick up the variant automatically; downgrades work via the existing decision table; verified by unit tests. |
| FR-3 | Epic 1 / Story 1.2 (template_swap helper) | New pure-domain module `template_swap.py` exporting `remap_search_space_for_swap_target` + `RemapResult` (4 named lists). |
| FR-4 | Epic 1 / Story 1.1 (covered by FR-2 path) | Validator + downgrade at digest-persist time — no new validator wrapper required at this layer. |
| FR-5 | Epic 2 / Story 2.1 (worker schema + pre-clean) | Extend `DIGEST_RESPONSE_SCHEMA` items: `kind` enum gains `swap_template`; add `template_id: string` to properties + `required`; worker pre-cleans empty-string sentinel per D-29. |
| FR-6 | Epic 2 / Story 2.2 (LLM prompts) | Extend `prompts/digest_narrative.system.md` + `prompts/digest_narrative.user.jinja` with `<parent_template_declared_params>` + `<available_templates>` blocks + `swap_template` decision subsection. |
| FR-7 | Epic 2 / Story 2.3 (worker remap step) | Worker fetches parent template + catalogue; truncates to 5 FIRST per AC-15; runs per-`swap_template` existence/engine checks + remap on retained items only. |
| FR-8 | Epic 2 / Story 2.3 (worker existence + engine + remap checks) | Worker emits `digest_followup_validation_downgraded` directly with `reason` ∈ `{not_found, same_as_parent, engine_type_mismatch, remap_invalid_search_space}` per D-25 + D-32. |
| FR-9 | Epic 3 / Story 3.1 (FE enums + exhaustive switch refactor) | Widen `FOLLOWUP_KIND_VALUES` in `ui/src/lib/enums.ts`; refactor `SuggestedFollowupsPanel` per-kind branching to exhaustive `Record<FollowupKind, …>` lookup BEFORE adding swap_template branch per D-28. |
| FR-10 | Epic 3 / Story 3.2 (swap_template card + lazy template fetches) | Render `swap_template` card with badge, rationale, side-by-side declared_params diff (lazy `useTemplate(...)` × 2), "Show search space" expander, "Run this followup" button. |
| FR-11 | Epic 3 / Story 3.3 (prefill `template_id = swap target`) | Extend `prefillValues` `useMemo` at `ui/src/app/proposals/[id]/page.tsx:136-184` so swap_template branch seeds `template_id = followup.template_id`. |
| FR-12 | Epic 3 / Story 3.4 (glossary) | Add `proposal.followup_kind_swap_template` + `proposal.followup_declared_params_diff` to `ui/src/lib/glossary.ts` per spec §11. |
| FR-13 | (clarification, no new code) | Tier-A lineage columns + CHECK + trigger apply unchanged — verified by Story 4.2 integration assertion in the E2E happy-path setup. |
| FR-14 | Epic 3 / Story 3.5 (autofill suppression guard) | Add explicit guard to Step-4 autofill effect in `create-study-modal.tsx`: when `initialValues.search_space_text` is non-empty, suppress the autofill for that modal-open lifetime. Add regression vitest. |

**Spec endpoint count vs plan:** Spec §8.1 lists 3 endpoints, all response-shape widenings (no new endpoints). Plan covers all 3 via Story 4.1 (FollowupItem-union widening surfaces in `DigestResponse` + `_DigestEmbed` automatically — re-export already exists at `backend/app/api/v1/schemas.py:28`; contract tests assert the wider OpenAPI shape).

| Endpoint | Story |
|---|---|
| `POST /api/v1/studies` (unchanged, validates `body.parent` against widened union) | Story 4.2 (integration test only — no router code change) |
| `GET /api/v1/studies/{study_id}/digest` (response widened) | Story 4.1 (contract test only — schemas reference `FollowupItem` indirectly) |
| `GET /api/v1/proposals/{proposal_id}` (response widened) | Story 4.1 (contract test only) |

**Spec error-code coverage vs plan:** Spec §8.5 introduces **zero** new error codes. Worker-side validation failures downgrade in-band (no API error); `POST /api/v1/studies` flow uses existing Tier-A codes (`PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `FOLLOWUP_INDEX_OUT_OF_RANGE`, `TEMPLATE_NOT_FOUND`, `INVALID_SEARCH_SPACE`, etc.) verbatim. Match.

**Deferred phases verified:** N/A — single-phase delivery per spec §3 "Phase boundaries". Tier C (`edit_template`) lives at sibling [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md) folder and is explicitly NOT gated by this work.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (matches Tier-A's structure). No phase-gate sub-structure needed — this plan has no migration round-trip gates.

### Story-level conventions for this plan

- **Backend conventions:** repo functions take `db: AsyncSession` first arg, call `db.flush()` (caller commits). Services/workers are `async`. Domain layer is pure (no DB, no async, no I/O). Models use `Mapped[]` typed columns + `String(36)` UUIDv7. Routers raise via local `_err()` helpers. Settings via `pydantic-settings`; never instantiate `Settings()` directly. Per CLAUDE.md Absolute Rule #8 all LLM model identifiers read from `Settings.openai_model` (no hardcoded `"gpt-4o"`).
- **Frontend conventions:** Next.js 16 App Router, `'use client'` at top of interactive pages/components, TanStack Query hooks, shadcn `<Card>` / `<Button>` / `<Badge>` primitives, `<details>`/`<summary>` for collapsibles (matching Tier-A's panel — there is no shadcn `<Collapsible>` in this repo; the existing panel uses `<details>` per `ui/src/components/proposals/suggested-followups-panel.tsx:80-122`). All enum wire values import from `@/lib/enums` per CLAUDE.md "Enumerated Value Contract Discipline."
- **Discriminated-union exhaustiveness:** Per D-28, every per-kind branching site must use a `Record<FollowupKind, …>` lookup OR a `switch` with `default → assertNever(f satisfies never)`. `if (f.kind === 'narrow' || f.kind === 'widen')` chains are forbidden once the 4th kind lands.
- **No new LLM hardcodes:** all worker LLM calls continue to read `Settings.openai_model` (Tier-A pattern preserved).
- **No new migration; no new env vars; no new secrets.**

### AI Agent Execution Protocol (per story)

0. Load context (`architecture.md`, `state.md`, this plan).
1. Read scope (story outcome + key interfaces + DoD).
2. Implement backend bottom-up: domain → worker/prompts → API contract.
3. Run backend tests (`make test-unit` + targeted integration + targeted contract).
4. Implement frontend.
5. Run E2E for touched UX path.
6. Update docs in same PR (`state.md`, `architecture.md` if applicable, plus the docs/01–05 entries §4).
7. Attach evidence in PR description.
8. After final story: update `state.md` and `architecture.md` per §4 below.

Story completion is invalid if any step is skipped.

---

## Epic 1 — Domain: discriminated-union widening + cross-template remap helper

### Story 1.1 — Add `SwapTemplateFollowup` to `FollowupItem` union + widen `FOLLOWUP_KIND_VALUES`

**Outcome:** A new Pydantic `SwapTemplateFollowup` model is appended to the discriminated union at `backend/app/domain/study/followups.py`. The `FollowupItem` `Annotated` alias, `FollowupItemAdapter`, `FollowupListAdapter`, `parse_followup_list`, and `serialize_followup_list` automatically pick up the variant. The source-of-truth tuple `FOLLOWUP_KIND_VALUES` widens to 4 entries. The CI grep guard at `scripts/ci/verify_enum_source_of_truth.sh` continues to pass against the mirrored frontend tuple (frontend mirror lands in Story 3.1).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/followups.py` | (1) Add `class SwapTemplateFollowup(BaseModel)` with `model_config = ConfigDict(extra="forbid")`, fields `kind: Literal["swap_template"]`, `rationale: str`, `template_id: str = Field(min_length=36, max_length=36)`, `search_space: SearchSpace` — same shape used at the line-80 `NarrowFollowup` and line-90 `WidenFollowup` siblings. (2) Widen the `FollowupItem` type alias at line 110 to include the new variant in the union. (3) Widen the `FOLLOWUP_KIND_VALUES` tuple at line 123 to `("narrow", "widen", "text", "swap_template")`. (4) Export `SwapTemplateFollowup` from `__all__` (currently at lines 327-335). |
| `backend/tests/unit/domain/study/test_followups.py` | Add per-kind unit tests for `SwapTemplateFollowup`: valid `{kind, rationale, template_id, search_space}` round-trip; rejection of `template_id` shorter/longer than 36 chars; rejection of `search_space=None`; rejection of an `extra="forbid"` field; assertion that `FOLLOWUP_KIND_VALUES` has length 4 with the new value at the tail. |
| `backend/tests/unit/domain/study/test_followups_backcompat.py` | Add a parser case: a `swap_template` dict whose `template_id` is "too-short" downgrades to `text` with the `[validation failed:` rationale prefix and emits the existing `digest_followup_validation_downgraded` WARN with `original_kind="swap_template"`. (No legacy `list[str]` case for swap_template — the legacy path is text-only.) |

**Key interfaces**

```python
# backend/app/domain/study/followups.py
class SwapTemplateFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["swap_template"]
    rationale: str
    template_id: str = Field(min_length=36, max_length=36)
    search_space: SearchSpace


type FollowupItem = Annotated[
    NarrowFollowup | WidenFollowup | TextFollowup | SwapTemplateFollowup,
    Field(discriminator="kind"),
]

FOLLOWUP_KIND_VALUES: tuple[str, ...] = ("narrow", "widen", "text", "swap_template")
```

**Tasks**

1. Edit `backend/app/domain/study/followups.py` per the snippet above. Place `SwapTemplateFollowup` immediately after `TextFollowup` (line 100); widen the alias at line 110; widen the tuple at line 123; extend `__all__`.
2. Run `make typecheck` on the domain module (`mypy --strict`).
3. Extend `backend/tests/unit/domain/study/test_followups.py` with the swap_template tests. Use the existing test-class structure (per-variant test class pattern).
4. Extend `backend/tests/unit/domain/study/test_followups_backcompat.py` with the malformed-template_id downgrade case.
5. Run `make test-unit` against `backend/tests/unit/domain/study/` and confirm all four kinds pass.

**Definition of Done (DoD)**

- `SwapTemplateFollowup` exists in `followups.py` and is exported via `__all__`.
- `FollowupItem` discriminated union widens to 4 variants; `FollowupItemAdapter.validate_python({"kind": "swap_template", ...})` returns the new variant.
- `FOLLOWUP_KIND_VALUES` is the 4-tuple `("narrow", "widen", "text", "swap_template")`.
- `mypy --strict` clean on the module.
- New unit tests pass:
  - `backend/tests/unit/domain/study/test_followups.py` — covers AC-1 (round-trip), AC-14 (tuple length).
  - `backend/tests/unit/domain/study/test_followups_backcompat.py` — covers AC-2 (downgrade on bad template_id).

---

### Story 1.2 — `template_swap.py` domain helper (`remap_search_space_for_swap_target` + `RemapResult`)

**Outcome:** A new pure-domain module at `backend/app/domain/study/template_swap.py` exports the cross-template remap helper plus its result value-object. The helper computes trusted intersection / disjoint fill / dropped parent / ignored LLM param sets and returns a validated `SearchSpace`. Raises `InvalidSearchSpaceError` on the three failure modes (empty swap target, empty trusted intersection, post-remap cardinality blow-up).

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/template_swap.py` | Pure-domain module exporting `remap_search_space_for_swap_target(...)` + `RemapResult` (frozen, slotted dataclass per D-14). No DB access, no I/O, no async. Co-located with `search_space_defaults.py` as a sibling per D-5. |
| `backend/tests/unit/domain/study/test_template_swap.py` | Unit tests covering trusted-intersection-only / mixed-intersection-and-disjoint-fill / dropped-only cases; empty-swap-target raises; empty-trusted-intersection raises (AC-4b); cardinality-cap blowup raises; assertion that an LLM-emitted param outside `parent_names ∩ swap_names` lands in `ignored_llm_param_names` and NOT in `RemapResult.search_space.params` (cycle-1 F1 regression guard); assertion that `disjoint_fill_param_names` is empty when every swap-target param is in the trusted intersection AND `build_starter_search_space` is NOT called (cycle-1 F2 regression guard); resulting `RemapResult.search_space` is always `SearchSpace.model_validate`-passing. Per spec §14 + D-22: no empty-LLM-search_space test (helper signature already requires non-empty `SearchSpace`). |

**Modified files**

None.

**Key interfaces**

```python
# backend/app/domain/study/template_swap.py
from dataclasses import dataclass
from typing import Mapping

from backend.app.domain.study.search_space import (
    InvalidSearchSpaceError,
    SearchSpace,
)
from backend.app.domain.study.search_space_defaults import (
    build_starter_search_space,
)


@dataclass(frozen=True, slots=True)
class RemapResult:
    """Output of :func:`remap_search_space_for_swap_target`.

    All four name lists are sorted ascending so the worker's INFO log
    + the unit-test assertions are deterministic.
    """
    search_space: SearchSpace
    trusted_intersection_param_names: list[str]
    disjoint_fill_param_names: list[str]
    dropped_parent_param_names: list[str]
    ignored_llm_param_names: list[str]


def remap_search_space_for_swap_target(
    *,
    parent_declared_params: Mapping[str, str],
    swap_target_declared_params: Mapping[str, str],
    llm_search_space: SearchSpace,
) -> RemapResult:
    """Compute the merged SearchSpace for a swap_template followup.

    Trusted intersection = parent ∩ swap ∩ llm  (bounds copied from llm_search_space)
    Disjoint fill        = swap \\ (parent ∩ llm) (bounds from build_starter_search_space)
    Dropped parent       = parent \\ swap          (diagnostic only)
    Ignored LLM          = llm    \\ (parent ∩ swap) (diagnostic only)

    Raises InvalidSearchSpaceError when:
      - swap_target_declared_params is empty (swap target declares no params),
      - the trusted intersection is empty (no shared params with LLM bounds),
      - build_starter_search_space exhausts cap-aware fallback on the disjoint set,
      - the final merged SearchSpace fails Pydantic cardinality-cap validation.
    """
```

**Tasks**

1. Create `backend/app/domain/study/template_swap.py` per the snippet above. Compute the three sets with `set()` operations on dict keys; sort all four name lists ascending before returning so the worker's INFO log and the unit tests are deterministic. Per D-18: gate `build_starter_search_space(...)` with `if disjoint_fill_names:` — skip the call entirely when the set is empty (the helper raises `InvalidSearchSpaceError` on empty input). Per D-34: raise `InvalidSearchSpaceError("swap_template has no shared parameters with parent template")` when the trusted intersection is empty.
2. Combine trusted intersection bounds (LLM) + disjoint fill bounds (heuristic) into one `params` dict, then `SearchSpace(params=params)`. Catch `pydantic.ValidationError` and re-raise as `InvalidSearchSpaceError` so the worker's `except InvalidSearchSpaceError:` block catches both raise sites uniformly.
3. Write `backend/tests/unit/domain/study/test_template_swap.py` covering the cases enumerated in the spec §14 unit-test list. Use plain `dict[str, str]` for `*_declared_params` inputs and construct fixture `SearchSpace` instances via the existing `SearchSpace.model_validate({...})` pattern.
4. Run `make test-unit` against `backend/tests/unit/domain/study/test_template_swap.py`.

**Definition of Done (DoD)**

- `template_swap.py` exports `remap_search_space_for_swap_target` + `RemapResult`. Module is pure (no DB, no I/O, no async).
- All cases in spec §14 unit-test list pass:
  - AC-3: trusted intersection + disjoint fill + dropped parent + ignored LLM categorization
  - AC-4: empty swap-target raises
  - AC-4b: empty trusted intersection raises
  - Cardinality-cap blowup raises
  - `RemapResult.search_space.params.keys() ⊆ swap_target_declared_params.keys()` (constructor invariant)
  - `disjoint_fill_param_names == []` skips `build_starter_search_space` (cycle-1 F2 regression guard)
- `mypy --strict` clean.

---

## Epic 2 — Worker: LLM schema + prompts + remap orchestration

### Story 2.1 — Extend `DIGEST_RESPONSE_SCHEMA` with `kind="swap_template"` + uniform `template_id` field

**Outcome:** The OpenAI structured-output JSON schema at `backend/workers/digest.py:186-218` widens its `kind` enum to 4 values and adds a uniform `template_id: string` property on every `suggested_followups` item (in both `properties` AND `required`, per D-20 / FR-5 — no `oneOf`/`if`/`then` because strict mode rejects them). The worker pre-cleans the field deterministically per D-29 before passing each raw item to `parse_followup_list` via the existing `followup_dicts` accumulator.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/workers/digest.py` | (1) Edit `DIGEST_RESPONSE_SCHEMA` (lines 186-218): widen the `kind` enum from `["narrow", "widen", "text"]` to `["narrow", "widen", "text", "swap_template"]`; add `"template_id": {"type": "string", "description": "36-char query_templates.id for swap_template items; empty string for other kinds (worker drops the field before Pydantic dispatch per spec D-29/D-20)."}` to the items `properties`; add `"template_id"` to the items `required` list. (2) Update the worker's per-item translation loop at lines 840-865 (the existing `for raw_item in parsed.get("suggested_followups", []) or []:` block): for each item, read `template_id` once; when `kind == "swap_template"`, include `template_id` in the constructed dict + decode `search_space_json` per the existing narrow/widen branch; when `kind != "swap_template"` AND `template_id == ""`, drop the `template_id` key (the non-swap variants have `extra="forbid"`); when `kind != "swap_template"` AND `template_id != ""`, leave the field in the dict so `FollowupItemAdapter.validate_python(...)` raises and the existing decision-table downgrade runs (D-29 deterministic rule). |
| `backend/tests/contract/test_digest_response_format.py` (or wherever `DIGEST_RESPONSE_SCHEMA` is asserted today — `backend/tests/unit/workers/test_digest_response_format.py:2.7K`) | Extend the schema-shape test: assert the `kind` enum has the 4-value tuple, assert `template_id` is in items `properties` AND `required`, assert the schema still has `additionalProperties: false`. |

**Key interfaces**

```python
# backend/workers/digest.py — DIGEST_RESPONSE_SCHEMA (changed fragment)
"suggested_followups": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["narrow", "widen", "text", "swap_template"],
            },
            "rationale": {"type": "string"},
            "search_space_json": {
                "type": "string",
                "description": (
                    "JSON-encoded SearchSpace body for narrow/widen/swap_template items; "
                    "empty string for text items. Worker parses + validates "
                    "via backend.app.domain.study.followups.parse_followup_list."
                ),
            },
            "template_id": {
                "type": "string",
                "description": (
                    "36-char query_templates.id for swap_template items; "
                    "empty string for other kinds (worker drops before Pydantic dispatch per D-29)."
                ),
            },
        },
        "required": ["kind", "rationale", "search_space_json", "template_id"],
        "additionalProperties": False,
    },
    "maxItems": 5,
},
```

**Tasks**

1. Edit `DIGEST_RESPONSE_SCHEMA` per the snippet above.
2. Extend the per-item translation loop at `backend/workers/digest.py:840-865`. The cleanest shape (mirroring the existing narrow/widen branch):
   ```python
   for raw_item in parsed.get("suggested_followups", []) or []:
       if not isinstance(raw_item, dict):
           followup_dicts.append(raw_item)
           continue
       kind = raw_item.get("kind")
       rationale = raw_item.get("rationale")
       ss_json = raw_item.get("search_space_json", "")
       template_id_raw = raw_item.get("template_id", "")
       if kind in ("narrow", "widen", "swap_template"):
           try:
               ss_decoded = json.loads(ss_json) if ss_json else None
           except (json.JSONDecodeError, TypeError):
               ss_decoded = None
           item_dict: dict[str, Any] = {
               "kind": kind,
               "rationale": rationale,
               "search_space": ss_decoded,
           }
           if kind == "swap_template":
               item_dict["template_id"] = template_id_raw
           elif template_id_raw != "":
               # Non-empty template_id on a non-swap kind = protocol
               # violation; keep it so extra="forbid" rejects + the
               # downgrade decision table fires per D-29.
               item_dict["template_id"] = template_id_raw
           followup_dicts.append(item_dict)
       else:  # text
           item_dict_text: dict[str, Any] = {
               "kind": kind,
               "rationale": rationale,
               "search_space": None,
           }
           if template_id_raw != "":
               item_dict_text["template_id"] = template_id_raw
           followup_dicts.append(item_dict_text)
   ```
3. Add/extend the schema-shape contract test to assert the four-value enum + `template_id` field.
4. Run `make test-unit` (worker tests) + `make test-contract` (digest contract subset).

**Definition of Done (DoD)**

- `DIGEST_RESPONSE_SCHEMA` per the snippet above (4-value enum, `template_id` in `properties` AND `required`, `additionalProperties: false`).
- Worker translation loop preserves Tier-A narrow/widen/text behavior + handles swap_template + applies D-29 pre-clean deterministically.
- Schema contract test asserts the widened shape.
- `mypy --strict` + `make lint` clean.
- Capability-degraded path unchanged (still persists `[]` per Tier-A D-27).

---

### Story 2.2 — LLM prompts: `<parent_template_declared_params>` + `<available_templates>` + `swap_template` system-prompt section

**Outcome:** The system prompt teaches the model when to emit `swap_template` (parameter-importance skew, winning-trial cluster, dead-weight params) and what to emit (`template_id` from the catalogue, `search_space` covering intersection params only). The user prompt template renders two new Jinja blocks so the LLM has the required catalogue + parent declared_params. `render_digest_user_prompt()` accepts two new kwargs.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `prompts/digest_narrative.system.md` | Append a fourth subsection **`swap_template`** to the "Suggested follow-ups — three kinds" H2 (currently the H2 starting at line 60). Document selection criteria per FR-6: parameter-importance skew OR winning-trial param clustering OR most-important params live in a different template. Document the contract: `template_id` MUST be one of the IDs in `<available_templates>`; `search_space` covers intersection params only; rationale should note which params the LLM expects the swap target to declare anew. Document anti-patterns (hallucinated template_id, same-as-parent, cross-engine swap, emit when `<available_templates>` is absent). Per D-34: explicitly instruct the LLM to skip `swap_template` when no template in `<available_templates>` shares at least one declared_param with the parent. Update the H2 heading from "three kinds" to "four kinds." |
| `prompts/digest_narrative.user.jinja` | After the existing `<parent_search_space>` block (line 40), add two new optional blocks: `{% if parent_template_declared_params %}<parent_template_declared_params>...{% endif %}` always present (rendered as JSON via `tojson(indent=2)` per the existing pattern) and `{% if available_templates %}<available_templates>...{% endif %}` rendered per-entry as a compact `{id, name, version, declared_params}` JSON list. Preserve all other blocks verbatim. |
| `backend/app/llm/digest_prompt.py` | Extend `render_digest_user_prompt()` signature (line 67) with two new optional kwargs: `parent_template_declared_params: Mapping[str, str] | None = None` and `available_templates: Sequence[Mapping[str, Any]] | None = None`. Pass both into the Jinja render call at line ~145 verbatim. Update the docstring (around line 116) to describe the new kwargs and the FR-7 worker call site. |
| `backend/tests/unit/workers/test_digest_prompt_render.py` | Add render tests asserting the two new blocks appear when their kwargs are non-empty AND are absent when omitted/empty (covers AC-13 catalogue-empty path at the prompt level). |

**Key interfaces**

```python
# backend/app/llm/digest_prompt.py — extended signature
def render_digest_user_prompt(
    *,
    study_name: str,
    cluster_name: str,
    target: str,
    query_set_name: str,
    query_count: int,
    judgment_list_name: str,
    rubric_summary: str,
    baseline_metric: float | None,
    achieved_metric: float | None,
    top_trials: list[dict[str, Any]],
    parameter_importance: dict[str, float],
    recommended_config: dict[str, Any],
    dropped_template_params: list[str],
    include_recommendation: bool,
    confidence: dict[str, Any] | None,
    parent_search_space: Mapping[str, Any] | None = None,
    parent_template_declared_params: Mapping[str, str] | None = None,   # NEW (FR-6/FR-7)
    available_templates: Sequence[Mapping[str, Any]] | None = None,     # NEW (FR-6/FR-7)
) -> str: ...
```

**Tasks**

1. Edit `prompts/digest_narrative.system.md` per the description above. Use the existing fenced-code formatting + tone.
2. Edit `prompts/digest_narrative.user.jinja` to add the two new optional blocks immediately after `<parent_search_space>`. Render per-template entries as compact JSON: `{"id": "...", "name": "...", "version": N, "declared_params": {...}}` separated by newlines.
3. Extend `render_digest_user_prompt()` with the two new kwargs and pass them through.
4. Extend `backend/tests/unit/workers/test_digest_prompt_render.py` with the new block assertions.

**Definition of Done (DoD)**

- System prompt documents the 4th kind with selection criteria, contract, and skip rule per D-34.
- User-prompt template renders both new blocks when kwargs are present; omits them when absent/empty.
- `render_digest_user_prompt()` accepts the two new kwargs (backward-compatible defaults `None`).
- New unit tests pass (block presence/absence assertions).
- `make lint` + `mypy --strict` clean.

---

### Story 2.3 — Worker: fetch catalogue + parent template → truncate-to-5 → per-swap_template existence/engine/remap checks

**Outcome:** The digest worker fetches the parent template + a catalogue (filtered to parent cluster's `engine_type` and excluding the parent's own template) once per digest call and passes both into the user prompt. After Step 13's existing followup-merge + parse + `[:5]` truncation, the worker iterates the retained list and for each `swap_template` item lazily resolves the target template; downgrades on not-found / same-as-parent / engine-mismatch (FR-8); else calls `remap_search_space_for_swap_target` and replaces the item's `search_space` with the helper output. Downgrades emit `digest_followup_validation_downgraded` with `original_kind="swap_template"` and `reason ∈ {not_found, same_as_parent, engine_type_mismatch, remap_invalid_search_space}`. Successful remaps emit a structlog INFO `digest_followup_swap_template_remapped`.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/workers/test_digest_followup_validation.py` | New unit test file covering each of the 4 worker-side reason codes (`not_found`, `same_as_parent`, `engine_type_mismatch`, `remap_invalid_search_space`) using a worker-helper-extraction pattern (see Tasks below). Also covers AC-15 (truncate-to-5 happens BEFORE checks — no DB lookup for the 6th item) and AC-15b (`remap_invalid_search_space` reason). |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/digest.py` | (1) After the existing parent-template fetch at line 680 (`template_row = await repo.get_query_template(db, study.template_id)`), add a catalogue fetch via `repo.list_query_templates(db, engine_type=cluster_row.engine_type, limit=200)` (extend `list_query_templates` if needed — see verification ledger). Exclude the parent study's own template_id. Extract the catalogue payload as `list[{id, name, version, declared_params}]`. (2) Pass `parent_template_declared_params=template_row.declared_params` AND `available_templates=catalogue_payload` to `render_digest_user_prompt(...)` at line 735. When the catalogue payload is empty, pass `available_templates=None` (the Jinja `{% if available_templates %}` block then omits — see AC-13). (3) **After** the existing `parsed_followups = parsed_followups[:5]` truncation at line 871 and **before** `followups_json = serialize_followup_list(parsed_followups)` at line 873, add a new "Step 13.5 — swap_template existence + engine + remap" loop that iterates the retained list, lazily resolves swap targets (cache keyed by template_id within the call), downgrades on FR-8 conditions, calls `remap_search_space_for_swap_target` on success, and replaces the item's `search_space` with `RemapResult.search_space`. Emit `digest_followup_validation_downgraded` directly via the existing module-level `logger.warning(...)` with the 4-reason taxonomy + field set documented in spec §6. Emit `digest_followup_swap_template_remapped` INFO via `logger.info(...)` per AC-8 on success with the 4 sorted name lists from `RemapResult`. |
| `backend/app/db/repo/query_template.py` | Confirm `list_query_templates(db, *, engine_type=..., limit=200)` supports the filter + limit; the existing signature already accepts `engine_type` per line 63. If catalogue size > 200 ever becomes relevant, the limit can be raised; MVP1 single-tenant has ≤ dozens of templates per spec §10. No change expected. |
| `backend/tests/integration/test_digest_followup_roundtrip.py` | Extend with a `swap_template` happy-path: stub LLM emits one swap_template item against a fixture catalogue with one extra template; assert persisted JSONB contains the merged `search_space` (intersection bounds from LLM, disjoint bounds from heuristic); assert `GET /api/v1/studies/{id}/digest` returns the structured shape with all four fields per AC-9. Add an AC-13 case: only one template registered → no `<available_templates>` block in the rendered prompt → no swap_template items in the persisted digest. |
| `backend/tests/integration/test_studies_with_parent_followup.py` | Extend with a swap-template lineage case: parent study uses template A; create-study body uses template B (the swap target) AND `parent: {proposal_id, followup_index}`; assert the new row has `template_id = B` AND `parent_proposal_id = <pid>` AND `parent_proposal_followup_index = <i>` per FR-13 + AC-12. |

**Key interfaces** (worker pseudo-code inside `generate_digest`)

```python
# After parsed_followups[:5] truncation at line 871, BEFORE serialize_followup_list:
target_template_cache: dict[str, QueryTemplate | None] = {}
final_followups: list[FollowupItem] = []
for idx, item in enumerate(parsed_followups):
    if item.kind != "swap_template":
        final_followups.append(item)
        continue
    # Lazily resolve target template (cached per call).
    target = target_template_cache.get(item.template_id, "_unset")
    if target == "_unset":
        target = await repo.get_query_template(db, item.template_id)
        target_template_cache[item.template_id] = target
    # FR-8 reason cascade.
    if target is None:
        reason = "not_found"
    elif target.id == study.template_id:
        reason = "same_as_parent"
    elif target.engine_type != cluster_row.engine_type:
        reason = "engine_type_mismatch"
    else:
        reason = None
    if reason is not None:
        downgraded = _downgrade_swap_template_to_text(item, reason, target)
        logger.warning(
            "digest worker: swap_template followup downgraded",
            event_type="digest_followup_validation_downgraded",
            study_id=study_id,
            proposal_id=proposal.id,
            followup_index=idx,
            original_kind="swap_template",
            reason=reason,
            validation_error=truncate_validation_error(downgraded.rationale),
        )
        final_followups.append(downgraded)
        continue
    # Happy path — call the remap helper, downgrade on InvalidSearchSpaceError.
    try:
        result = remap_search_space_for_swap_target(
            parent_declared_params=template_row.declared_params,
            swap_target_declared_params=target.declared_params,
            llm_search_space=item.search_space,
        )
    except InvalidSearchSpaceError as exc:
        downgraded = _downgrade_swap_template_to_text(item, "remap_invalid_search_space", target, str(exc))
        logger.warning(
            "digest worker: swap_template remap failed",
            event_type="digest_followup_validation_downgraded",
            study_id=study_id,
            proposal_id=proposal.id,
            followup_index=idx,
            original_kind="swap_template",
            reason="remap_invalid_search_space",
            validation_error=truncate_validation_error(str(exc)),
        )
        final_followups.append(downgraded)
        continue
    # Replace search_space with merged result; emit INFO.
    merged = item.model_copy(update={"search_space": result.search_space})
    logger.info(
        "digest worker: swap_template remap success",
        event_type="digest_followup_swap_template_remapped",
        study_id=study_id,
        proposal_id=proposal.id,
        followup_index=idx,
        target_template_id=target.id,
        trusted_intersection_param_names=result.trusted_intersection_param_names,
        disjoint_fill_param_names=result.disjoint_fill_param_names,
        dropped_parent_param_names=result.dropped_parent_param_names,
        ignored_llm_param_names=result.ignored_llm_param_names,
    )
    final_followups.append(merged)

parsed_followups = final_followups
# … then existing serialize_followup_list + create_digest …
```

Per the spec's §3 "out of scope" + the worker's existing structure, `_downgrade_swap_template_to_text` is a private worker-module helper (not a domain function) — it constructs a `TextFollowup` with the rationale prefix from FR-8 (e.g., `f"[validation failed: swap_template target template not found: {item.template_id}] {item.rationale}"`). The helper lives at the worker layer per D-25.

**Truncation symbol provenance (per GPT-5.5 cycle-1 F6):** `_truncate` is a **private** helper at `backend/app/domain/study/followups.py:63` (`_TRUNCATE_LIMIT = 200` at line 60). The worker MUST NOT import the private symbol directly. Two acceptable options — pick one in Story 2.3 Task 4b below:

- **Option A (preferred):** Promote `_truncate` to a public re-export from `followups.py`: rename to `truncate_validation_error` (or similar non-leading-underscore name), update internal call sites, add to `__all__`, then import from the worker. This makes the canonical helper the single source of truth across both layers per D-33.
- **Option B (acceptable):** Define a worker-local helper at the top of `backend/workers/digest.py` with the exact head-and-tail 200+200 semantics, with a comment `# Mirrors backend/app/domain/study/followups.py _truncate per spec D-33.` This duplicates but is acceptable; the worker-local copy is small (~10 LOC) and the contract is locked by the canonical-`_truncate` reference in the spec.

The plan recommends Option A.

**Tasks**

1. Add the catalogue fetch right after the existing parent-template fetch (`backend/workers/digest.py:680`). Use `await repo.list_query_templates(db, engine_type=cluster_row.engine_type, limit=200)` (verify `cluster_row` is in-scope at that point; if not, fetch it via `await repo.get_cluster(db, study.cluster_id)` immediately before). Filter out the parent's own template_id. Build the catalogue payload as a list of compact dicts `{id, name, version, declared_params}`.
2. Pass `parent_template_declared_params=template_row.declared_params` and `available_templates=catalogue_payload or None` to `render_digest_user_prompt(...)`.
3. Add the "Step 13.5" loop AFTER `parsed_followups = parsed_followups[:5]` (line 871) and BEFORE `followups_json = serialize_followup_list(parsed_followups)` (line 873). Implement per the Key interfaces snippet above. Extract `_downgrade_swap_template_to_text(item, reason, target=None, validation_error="")` as a private module-level helper at the top of `backend/workers/digest.py` (alongside the existing `_safe_record_cost` helper around line 230).
4b. **Truncation symbol (F6 fix).** Apply Option A from the Truncation symbol provenance note above: promote `_truncate` to public — rename to `truncate_validation_error` in `backend/app/domain/study/followups.py`, drop the underscore prefix, update all internal call sites in `followups.py`, add to `__all__`. Import via `from backend.app.domain.study.followups import truncate_validation_error` in `backend/workers/digest.py`. Confirms the canonical helper (D-33) is the single source of truth.
4. **Per-kind metrics extension:** widen the existing per-kind counts at line 877 to include `followups_swap_template_count = sum(1 for f in parsed_followups if f.kind == "swap_template")`. Add it to the `digest_complete` info log payload alongside the existing three counts.
5. Create `backend/tests/unit/workers/test_digest_followup_validation.py`. Extract `_downgrade_swap_template_to_text` to module level so it's importable; the unit tests pass synthetic `SwapTemplateFollowup` items + fixture `QueryTemplate` rows (or `None`) and assert (a) the produced `TextFollowup` rationale prefix matches FR-8, (b) the structlog WARN field set matches (use `caplog` or `structlog.testing.capture_logs()`). Add a small wrapper that lets the test exercise the loop body without booting Arq — extract the loop into a private async helper `_apply_swap_template_remap(parsed_followups, *, study, template_row, cluster_row, db, proposal_id, logger)` that returns `list[FollowupItem]` so the unit tests can call it directly with a mock `db` / `repo`.
6. Add AC-15 truncate-before-checks assertion: feed 6 items where the 6th is a swap_template with a bogus template_id; assert no DB lookup happens for the 6th (mock `repo.get_query_template` and assert call count == 0 for the bogus id) and no WARN is emitted for it.
7. Extend `backend/tests/integration/test_digest_followup_roundtrip.py` with a swap_template happy-path + AC-13 catalogue-empty case.
8. Extend `backend/tests/integration/test_studies_with_parent_followup.py` with the swap-template lineage case per AC-12.
9. Run `make test-unit backend/tests/unit/workers/`, then `make test-integration backend/tests/integration/test_digest_followup_roundtrip.py backend/tests/integration/test_studies_with_parent_followup.py`.

**Definition of Done (DoD)**

- Worker fetches parent template + catalogue once per digest call; passes both into the user prompt.
- Step 13.5 loop runs ONLY after `[:5]` truncation per AC-15.
- Per FR-8 each downgrade reason maps to the exact `reason` sub-field (`not_found`, `same_as_parent`, `engine_type_mismatch`, `remap_invalid_search_space`) on `digest_followup_validation_downgraded`.
- Successful remap emits `digest_followup_swap_template_remapped` INFO with the 4 `RemapResult` name lists per AC-8 and D-30.
- New unit test file covers all 4 reason codes + AC-15 (no DB lookup for truncated items).
- Integration tests cover the happy path + lineage assertion + AC-13 catalogue-empty path.
- `digest_complete` info log carries the new `followups_swap_template_count` field.
- Capability-degraded path unchanged.
- `mypy --strict` + `make lint` clean.

---

## Epic 3 — Frontend: enums + panel branch + prefill + glossary + autofill guard

### Story 3.1 — `FOLLOWUP_KIND_VALUES` widening + `SuggestedFollowupsPanel` exhaustiveness refactor

**Outcome:** The frontend's `FOLLOWUP_KIND_VALUES` widens to the 4-tuple matching the backend; `KIND_LABELS` gains the swap_template entry; the panel's per-kind branching becomes exhaustive (`Record<FollowupKind, …>` lookups OR `switch` + `assertNever`) BEFORE the swap_template card is added per D-28. This story keeps the panel rendering only narrow/widen/text — the new swap_template card lands in Story 3.2.

**Reference: current component structure**

- **File:** `ui/src/components/proposals/suggested-followups-panel.tsx`
- **Current line count:** 146 (verified `wc -l`).
- **Current per-kind branching:** line 78 — `if (f.kind === 'narrow' || f.kind === 'widen') { … }` with implicit `text` fallback via JSX conditional rendering. This pattern does NOT exhaustiveness-check at the type level — adding a fourth kind silently falls into the text fallback.
- **Current `KIND_LABELS`:** lines 41-45, `Record<FollowupKind, string>`. Adding a new key here IS exhaustiveness-checked by TypeScript automatically.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | Line 248 — change `export const FOLLOWUP_KIND_VALUES = ['narrow', 'widen', 'text'] as const;` to `export const FOLLOWUP_KIND_VALUES = ['narrow', 'widen', 'text', 'swap_template'] as const;`. The source-of-truth comment at line 247 (`// Values must match backend/app/domain/study/followups.py FOLLOWUP_KIND_VALUES`) stays unchanged. `type FollowupKind = (typeof FOLLOWUP_KIND_VALUES)[number];` automatically widens. |
| `ui/src/components/proposals/suggested-followups-panel.tsx` | (1) Extend `KIND_LABELS` at line 41-45 to include `swap_template: 'Swap template'` — TypeScript automatically enforces exhaustiveness on the `Record<FollowupKind, string>` type. (2) Refactor the per-kind branching at line 78 from `if (f.kind === 'narrow' || f.kind === 'widen')` to an exhaustive shape. Recommended approach: extract two `Record<FollowupKind, boolean>` constants (`SHOWS_SEARCH_SPACE_EXPANDER` and `SHOWS_RUN_BUTTON`, both initially `{narrow: true, widen: true, text: false, swap_template: false}` — the swap_template entries flip to `true` in Story 3.2 once that card variant lands). Replace the line-78 `if` chain with `{SHOWS_SEARCH_SPACE_EXPANDER[f.kind] && (<>…</>)}`. This keeps Story 3.1 a no-op for runtime behavior (still only narrow+widen actionable) while making the discriminator-exhaustive shape mandatory. Per D-28, the existing tests must keep passing without modification. |
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | Extend with: assert `KIND_LABELS.swap_template === 'Swap template'` (smoke check on the constant); assert that adding a `swap_template` item with no other followups still renders the panel container (the panel doesn't crash on the new kind even before Story 3.2 lands the rich card — it falls through the `SHOWS_*` guards and renders rationale-only). |
| `ui/src/__tests__/lib/enums.test.ts` | Extend with: assert `FOLLOWUP_KIND_VALUES.length === 4`; assert `'swap_template' in FOLLOWUP_KIND_VALUES`. |

**Enumerated value contract verification (per CLAUDE.md)**

| Source | Wire values |
|---|---|
| Backend (`backend/app/domain/study/followups.py:123`) — `FOLLOWUP_KIND_VALUES` tuple | `narrow`, `widen`, `text`, `swap_template` |
| Spec §8.4 enumerated value contracts row 1 | `narrow`, `widen`, `text`, `swap_template` |
| Frontend (`ui/src/lib/enums.ts:248` after this story) | `narrow`, `widen`, `text`, `swap_template` |

Match: character-for-character. The frontend NEVER exposes `kind` as an option in any `<select>` (per spec §8.4 + Tier-A D-12 — the LLM is the producer, the UI only renders).

**Tasks**

1. Edit `ui/src/lib/enums.ts:248` to widen the tuple.
2. Extend `KIND_LABELS` in `suggested-followups-panel.tsx` (TypeScript will fail until you do — the `Record<FollowupKind, string>` becomes incomplete).
3. Refactor the line-78 `if (f.kind === 'narrow' || f.kind === 'widen')` chain into the two `Record<FollowupKind, boolean>` lookups per D-28. The two lookup constants are module-level alongside `KIND_LABELS`.
4. Run `cd ui && pnpm typecheck` — should pass with the exhaustive `Record<FollowupKind, …>` shape and fail visibly if any entry is missing.
5. Extend the panel test + enums test as described.
6. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- `FOLLOWUP_KIND_VALUES` is a 4-tuple matching backend.
- `KIND_LABELS` includes `swap_template: 'Swap template'`.
- Panel branching uses `Record<FollowupKind, …>` lookups (D-28); no `if (f.kind === '…')` chain remains.
- Existing panel behavior (narrow/widen render Show search space + Run button; text renders rationale only) preserved.
- Story-level tests pass.
- AC-14 (source-of-truth grep gate) passes — `scripts/ci/verify_enum_source_of_truth.sh` finds matching 4-tuples on both sides.

---

### Story 3.2 — Render `swap_template` card with side-by-side `declared_params` comparison

**Outcome:** The panel renders `swap_template` items as actionable cards with a Swap-template badge, rationale text, an expandable **Show declared params** detail (side-by-side parent vs swap-target, lazy-fetched via two `useTemplate(...)` calls), an expandable **Show search space** detail (proposed `search_space` JSON only — no parent diff because the param spaces differ), and a **Run this followup** primary button. The `SHOWS_SEARCH_SPACE_EXPANDER` and `SHOWS_RUN_BUTTON` lookups from Story 3.1 flip `swap_template: true`. Two new `data-testid` values land for the declared-params diff.

**Reference: current panel structure** (already documented in Story 3.1 reference).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/proposals/suggested-followups-panel.tsx` | (1) Flip `SHOWS_SEARCH_SPACE_EXPANDER.swap_template` and `SHOWS_RUN_BUTTON.swap_template` from `false` (set in Story 3.1) to `true`. (2) Add a third `Record<FollowupKind, boolean>` constant `SHOWS_DECLARED_PARAMS_DIFF` = `{narrow: false, widen: false, text: false, swap_template: true}`. (3) Add `parentTemplate?: { declared_params: Record<string, string> } | undefined` + `parentTemplateLoading?: boolean` + `parentTemplateError?: unknown` to `SuggestedFollowupsPanelProps`. **Per GPT-5.5 cycle-1 F2 + F3, the per-card swap target fetch happens INSIDE a new child component `SwapTemplateCard` (not via a parent-passed `swapTargetsByTemplateId` lookup map).** The page-level orchestrator (Story 3.3) only fetches the parent template; each swap_template card calls `useTemplate(f.template_id)` at its own top level — that satisfies the React Rules of Hooks (no hook calls inside `.map()` callbacks) AND scales to N distinct swap targets per digest without the multi-target single-shortcut limitation. (4) Extract a child component `SwapTemplateCard({ followup, index, parentTemplate, parentTemplateLoading, parentTemplateError, onRun })` that: calls `useTemplate(followup.template_id)` at its top; computes `sharedKeys` via `useMemo`; renders the badge + rationale + declared-params diff `<details>` + search-space expander + Run button. (5) Inside the existing `followups.map((f, i) => …)` block, when `f.kind === 'swap_template'`, render `<SwapTemplateCard followup={f} index={i} … />`; otherwise render the existing narrow/widen/text branches. (6) The swap_template card's "Show search space" expander renders the proposed `search_space` JSON ONLY — no parent diff column (the param spaces differ; spec FR-10). |
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | Extend with: render a `swap_template` followup; mock the per-card `useTemplate(...)` via `vi.mock('@/lib/api/query-templates', ...)` (or via the `<QueryClientProvider>` wrapper pattern used by the existing test); assert badge text "Swap template" + `aria-label="Swap template"`; assert `data-testid="followup-0-declared-params-diff"`, `followup-0-parent-declared-params`, `followup-0-swap-declared-params` all present; assert "Run this followup" button visible with `data-testid="followup-0-run"`; assert glossary tooltip `proposal.followup_kind_swap_template` present; assert "Could not load" error message renders when the per-card swap-target fetch errors; assert shared declared_params keys are visually distinguished (test by class presence). Multi-target case: render two swap_template followups pointing at different `template_id`s — assert both cards' declared-params diffs populate independently (per-card `useTemplate` returns each target's data correctly). |

**UI Guidance (this story's frontend scope)**

**Insertion point**

- Inside the existing `{followups.map((f, i) => (<li …>…</li>))}` block (lines 65-141 of the current file). The new declared-params diff `<details>` block goes immediately above the existing "Show search space" `<details>` (line 80) when `f.kind === 'swap_template'`. The existing search-space `<details>` becomes narrowed via `if (f.kind === 'swap_template')` so the parent-diff fallback only fires for narrow/widen.

**Analogous markup pattern** (copy from the existing line 80-122 `<details>` block):

```tsx
{/* Existing search-space <details> at lines 80-122 — used as the structural template */}
<details className="text-xs">
  <summary
    className="cursor-pointer text-gray-700 hover:text-gray-900"
    data-testid={`followup-${i}-show-search-space`}
  >
    Show search space
    <span className="ml-1 inline-block align-middle">
      <InfoTooltip glossaryKey="proposal.followup_search_space_diff" />
    </span>
  </summary>
  <div className="mt-2 space-y-2">
    {/* … parent + proposed JSON viewers … */}
  </div>
</details>
```

**New declared-params diff markup pattern** (this story adds, modeled on the above) — rendered INSIDE the new `SwapTemplateCard` child component so the per-card `useTemplate(...)` hook call is at component top level (React Rules of Hooks compliance, per GPT-5.5 cycle-1 F3):

```tsx
// Inside ui/src/components/proposals/suggested-followups-panel.tsx — new child component
interface SwapTemplateCardProps {
  followup: Extract<FollowupItem, { kind: 'swap_template' }>;
  index: number;
  parentTemplate?: { declared_params: Record<string, string> };
  parentTemplateLoading?: boolean;
  parentTemplateError?: unknown;
  onRun: (index: number) => void;
}

function SwapTemplateCard({
  followup,
  index,
  parentTemplate,
  parentTemplateLoading = false,
  parentTemplateError = null,
  onRun,
}: SwapTemplateCardProps) {
  // Per-card hook call — satisfies React Rules of Hooks AND scales to N
  // distinct swap targets per digest (GPT-5.5 cycle-1 F2 fix).
  const swapTargetQuery = useTemplate(followup.template_id);
  const swapTarget = swapTargetQuery.data;
  const swapTargetLoading = swapTargetQuery.isLoading;
  const swapTargetError = swapTargetQuery.error;

  const sharedKeys = useMemo(() => {
    if (!parentTemplate || !swapTarget) return [];
    return Object.keys(parentTemplate.declared_params)
      .filter((k) => k in swapTarget.declared_params)
      .sort();
  }, [parentTemplate, swapTarget]);

  return (
    <li
      key={`followup-${index}`}
      data-testid={`followup-${index}-card`}
      className="rounded-md border p-3 space-y-2"
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" aria-label={KIND_LABELS.swap_template}>
          {KIND_LABELS.swap_template}
        </Badge>
        <InfoTooltip glossaryKey="proposal.followup_kind_swap_template" />
      </div>
      <p className="text-sm">{followup.rationale}</p>

      <details className="text-xs" data-testid={`followup-${index}-declared-params-diff`}>
        <summary
          className="cursor-pointer text-gray-700 hover:text-gray-900"
          data-testid={`followup-${index}-show-declared-params`}
        >
          Show declared params
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_declared_params_diff" />
          </span>
        </summary>
        <div className="mt-2 grid grid-cols-2 gap-3">
          <DeclaredParamsColumn
            title="Parent template"
            params={parentTemplate?.declared_params}
            shared={sharedKeys}
            loading={parentTemplateLoading}
            error={parentTemplateError}
            data-testid={`followup-${index}-parent-declared-params`}
          />
          <DeclaredParamsColumn
            title="Swap target"
            params={swapTarget?.declared_params}
            shared={sharedKeys}
            loading={swapTargetLoading}
            error={swapTargetError ?? null}
            data-testid={`followup-${index}-swap-declared-params`}
          />
        </div>
      </details>

      {/* Show search space — proposed JSON only, no parent diff column */}
      <details className="text-xs">
        <summary
          className="cursor-pointer text-gray-700 hover:text-gray-900"
          data-testid={`followup-${index}-show-search-space`}
        >
          Show search space
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_search_space_diff" />
          </span>
        </summary>
        <pre className="mt-2 text-xs bg-muted p-2 rounded overflow-x-auto">
          {JSON.stringify(followup.search_space, null, 2)}
        </pre>
      </details>

      <div className="flex justify-end">
        <Button
          type="button"
          variant="default"
          size="sm"
          data-testid={`followup-${index}-run`}
          onClick={() => onRun(index)}
          aria-label="Run this followup — opens the create study form pre-filled with these settings"
        >
          Run this followup
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_run_button" />
          </span>
        </Button>
      </div>
    </li>
  );
}
```

`DeclaredParamsColumn` is an inline sub-component (kept in the same file — Tier-A composition precedent at plan §"Component composition") that renders title + loading state + error state + `{name: type-string}` rows with shared keys visually distinguished.

**Layout and structure**

- `grid grid-cols-2 gap-3` for the side-by-side panels (parent left, swap right). On narrow viewports the grid wraps to single-column via Tailwind's default responsive behavior; no special handling needed per spec §13.
- Card body padding unchanged from existing pattern (`p-3 space-y-2` on the `<li>`).
- Loading state: replace the params list with `<p className="text-xs text-gray-500" data-testid="followup-${i}-declared-params-loading">Loading template details…</p>`.
- Error state: replace the params list with `<p className="text-xs text-gray-500" data-testid="followup-${i}-declared-params-error">Could not load template details — submitting will still work; the comparison view is unavailable.</p>` (exact copy per spec §11).

**Modal pattern**

This story does NOT open the modal — the page orchestrator (Story 3.3) handles that via the existing `onRun(index)` callback from Story 3.1.

**Visual consistency table**

| New element | CSS class | Pattern source |
|---|---|---|
| Card border + padding (unchanged) | `rounded-md border p-3` | `ui/src/components/proposals/suggested-followups-panel.tsx:69` (existing) |
| Kind badge (extended `KIND_LABELS`) | shadcn `<Badge variant="outline">` | `ui/src/components/proposals/suggested-followups-panel.tsx:72` (existing) |
| Declared-params `<details>` wrapper | `text-xs` + matching `<summary>` cursor + hover classes | `ui/src/components/proposals/suggested-followups-panel.tsx:80-89` (existing search-space pattern) |
| Two-column grid | `grid grid-cols-2 gap-3` | Tailwind utility; no codebase precedent for declared-params yet — new convention. |
| Shared-key highlight | `font-semibold text-gray-900` | mirrors the existing `text-xs font-semibold text-gray-700` "Parent (current):" heading at line 109 |
| Loading message | `text-xs text-gray-500` | matches Tier-A loading text style at line 93 |
| Error message | `text-xs text-gray-500` | matches Tier-A error text style at line 101 |
| Run button (unchanged) | shadcn `<Button variant="default" size="sm">` | line 123-136 (existing) |

**Component composition**

- `SwapTemplateCard` is a **same-file child component** (not extracted to a separate file) — keeps the panel's mental model intact while satisfying the React Rules of Hooks (per GPT-5.5 cycle-1 F3). The panel was 146 LOC after Tier A; this story adds ~140 LOC for a final ~285 LOC — slightly above the Tier-A inline threshold but the child-component split keeps each function readable. Alternative (separate file) was rejected: the swap_template card is tightly coupled to `KIND_LABELS`, the per-card `data-testid` pattern, and the `onRun` callback shape — extracting to its own file would multiply imports without simplifying anything.
- `DeclaredParamsColumn` is also a same-file inline sub-component.
- Props on `SuggestedFollowupsPanel`: 3 new (`parentTemplate`, `parentTemplateLoading`, `parentTemplateError`). The page-level orchestrator (Story 3.3) populates them via a single `useTemplate(parentStudy.data?.template_id)` call. The per-swap-target fetches live INSIDE `SwapTemplateCard`, so the panel's prop surface stays narrow.

**Interaction behavior table**

| User action | Frontend behavior | API call |
|---|---|---|
| Click "Show declared params" | Toggle the new `<details>` open/close | None (template details already fetched on page mount per Story 3.3 lazy hook) |
| Click "Show search space" on a swap_template card | Toggle the existing `<details>`, renders proposed JSON only (no parent diff) | None |
| Click "Run this followup" on a swap_template card | Calls `onRun(index)` callback prop (page orchestrator opens modal with prefill where `template_id = followup.template_id`) | None at click time; the existing `useTemplate` queries are already warm; modal submit triggers `POST /api/v1/studies` in Story 3.3 |
| Hover any `InfoTooltip` icon | Show tooltip with glossary content | None |

**Handler patterns**

```tsx
// Inside SuggestedFollowupsPanel, per-card
const sharedKeys = useMemo(() => {
  if (f.kind !== 'swap_template') return [];
  const parent = parentTemplate?.declared_params;
  const swap = swapTargetsByTemplateId?.[f.template_id]?.declared_params;
  if (!parent || !swap) return [];
  return Object.keys(parent).filter((k) => k in swap).sort();
}, [f, parentTemplate, swapTargetsByTemplateId]);
```

**Information architecture placement**

- Same as Tier A — cards live inside the existing `SuggestedFollowupsPanel` on `/proposals/[id]`. No new routes, no nav changes. The "Run this followup" button opens the existing `<CreateStudyModal>` overlay (no navigation).

**Tooltips and contextual help**

| Element | Tooltip text | Glossary key | Trigger | Placement | Source-of-truth comment |
|---|---|---|---|---|---|
| "Swap template" badge (new) | "The LLM suggests trying a different query template entirely. The proposed search space covers params shared with the parent template; disjoint params get heuristic defaults you can edit before submitting." | `proposal.followup_kind_swap_template` (new in Story 3.4) | hover | top | `// Source-of-truth: backend/app/domain/study/followups.py SwapTemplateFollowup` |
| "Show declared params" expander (new) | "Compare the parent template's declared params against the proposed swap target's. Shared params take your LLM-proposed bounds; new params get heuristic defaults; dropped params are silently removed." | `proposal.followup_declared_params_diff` (new in Story 3.4) | hover | top | (UI-only) |
| Existing "Run this followup" button + "Show search space" expander tooltips | unchanged | `proposal.followup_run_button`, `proposal.followup_search_space_diff` | hover | top | (UI-only) |

Tooltips use the existing `<InfoTooltip glossaryKey="…">` primitive at `ui/src/components/common/info-tooltip.tsx`. The new glossary keys are added in Story 3.4.

**Legacy behavior parity**

- No legacy delete/replace in this story. The panel was last rewritten by Tier A (≤200 LOC after that rewrite); this story extends in-place via the new conditional rendering branches. State this explicitly: **No legacy behavior parity table required — no user-facing component >100 LOC is being deleted or migrated.** Tier A's parity table covered the pre-Tier-A panel deletion; this story is purely additive.

**Tasks**

1. Flip `SHOWS_SEARCH_SPACE_EXPANDER.swap_template` + `SHOWS_RUN_BUTTON.swap_template` to `true` (Story 3.1 set them to `false`).
2. Add the third lookup `SHOWS_DECLARED_PARAMS_DIFF`.
3. Extend `SuggestedFollowupsPanelProps` with the 7 new template-data fields documented above.
4. Add the `<details>` declared-params diff block inside the per-item map, gated by `SHOWS_DECLARED_PARAMS_DIFF[f.kind]`.
5. Narrow the existing "Show search space" `<details>` block: when `f.kind === 'swap_template'`, render the proposed JSON only (no parent diff column — the parent's bounds aren't directly comparable). Keep the existing narrow/widen branch unchanged.
6. Add `DeclaredParamsColumn` inline sub-component (loading / error / list rendering with shared-key highlighting).
7. Extend the panel vitest with the new swap_template assertions per the Modified files table.
8. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- Swap_template cards render badge + rationale + declared-params diff + search-space expander + Run button per AC-10.
- All required `data-testid` values present (`followup-${i}-card`, `followup-${i}-declared-params-diff`, `followup-${i}-parent-declared-params`, `followup-${i}-swap-declared-params`, `followup-${i}-show-search-space`, `followup-${i}-show-declared-params`, `followup-${i}-run`).
- Loading + error states for both template fetches render the exact spec §11 copy.
- Run button stays enabled regardless of template-fetch state per FR-10.
- Panel vitest covers the new branches.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.

---

### Story 3.3 — Page orchestration: widen actionable-followup gate + parent `useTemplate` + exhaustive prefill branching

**Outcome:** The proposal-detail page widens the `hasActionableFollowup` gate to include `swap_template` (per GPT-5.5 cycle-1 F1 — otherwise swap_template-only digests skip the parent-study fetch and break both the diff view AND the prefill); lazily fetches the parent template once (per-target swap fetches live INSIDE `SwapTemplateCard` per Story 3.2); extends the `prefillValues` `useMemo` so the swap_template branch seeds `template_id = followup.template_id` using an exhaustive `Record<FollowupKind, …>` shape (per GPT-5.5 cycle-1 F4 / D-28). The 200-char parent-name truncation + `parent: {proposal_id, followup_index}` lineage + all other prefill fields stay verbatim.

**Reference: current page structure**

- **File:** `ui/src/app/proposals/[id]/page.tsx`
- **Current line count:** 303 (verified `wc -l`).
- **Existing `hasActionableFollowup`:** computed inline at line ~127 (Tier-A pattern) as `followups.some((f) => f.kind === 'narrow' || f.kind === 'widen')`. **This MUST be widened to include `swap_template`** (per GPT-5.5 cycle-1 F1 — swap_template is actionable; otherwise a digest containing only `swap_template` items would skip the parent-study fetch and break the diff + prefill flow).
- **Existing lazy fetch:** `useStudy(parentStudyId ?? '', { enabled: parentStudyId !== null && hasActionableFollowup })` at line 132 — pattern unchanged after the gate widens.
- **Existing prefill `useMemo`:** lines 136-184. The swap_template branch enters at the existing `const f = followups[runFollowupIndex];` (line 139); current kind check `if (f.kind !== 'narrow' && f.kind !== 'widen') return undefined;` must be replaced by an exhaustive `Record<FollowupKind, boolean>` lookup per D-28.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/proposals/[id]/page.tsx` | (1) **Widen the `hasActionableFollowup` gate (F1 fix).** Extract a module-level `Record<FollowupKind, boolean>` constant `ACTIONABLE_FOLLOWUP_KINDS = {narrow: true, widen: true, text: false, swap_template: true}` and replace the inline `some` check with `followups.some((f) => ACTIONABLE_FOLLOWUP_KINDS[f.kind])`. The lookup is discriminator-exhaustive — TypeScript fails if a future kind is added without an entry. (2) Add a parent-template fetch: `const parentTemplateQuery = useTemplate(parentStudy.data?.template_id);` (gates internally on `Boolean(id)`). Pass `parentTemplate={parentTemplateQuery.data ? { declared_params: parentTemplateQuery.data.declared_params } : undefined}`, `parentTemplateLoading={parentTemplateQuery.isLoading}`, `parentTemplateError={parentTemplateQuery.error ?? null}` to `<SuggestedFollowupsPanel>` at line ~271. **No per-target fetches at the page level** — they live inside `SwapTemplateCard` per Story 3.2 (per GPT-5.5 cycle-1 F2). (3) **Refactor the prefill kind check to exhaustive shape (F4 fix).** Replace the line-~139 chain with the same `ACTIONABLE_FOLLOWUP_KINDS[f.kind]` lookup AND a kind-switch for the template_id assignment: extract a helper `function resolveTemplateIdForPrefill(f: FollowupItem, parentTemplateId: string): string` that uses a `Record<FollowupKind, (f, parentId) => string | null>` lookup so the swap_template case returns `f.template_id` and narrow/widen/text return `parentTemplateId` (text never reaches this code path because it's gated by `ACTIONABLE_FOLLOWUP_KINDS`; the helper returns `parentTemplateId` defensively). Document with a source-of-truth comment `// Values must match backend/app/domain/study/followups.py FollowupItem.kind`. |
| `ui/src/__tests__/app/proposals/page.followup-prefill.test.tsx` (extend existing if present; otherwise new) | Cover: (a) AC-11 — swap_template prefill seeds `template_id = followup.template_id`; (b) AC-12 — POST body carries `body.template_id = B` + `body.parent = {proposal_id, followup_index}`; (c) F1 regression — render a proposal whose digest contains ONLY swap_template followups (no narrow/widen) and assert the parent-study `useStudy` fetch enables (mock the hook call count or assert via the panel rendering parent-template-derived UI). |

**Key interfaces**

```tsx
// ui/src/app/proposals/[id]/page.tsx — module-level constants
// Values must match backend/app/domain/study/followups.py FollowupItem.kind
const ACTIONABLE_FOLLOWUP_KINDS: Record<FollowupKind, boolean> = {
  narrow: true,
  widen: true,
  text: false,
  swap_template: true,
};

// Exhaustive resolver for the prefill template_id (D-28 compliant).
function resolveTemplateIdForPrefill(
  f: FollowupItem,
  parentTemplateId: string,
): string {
  switch (f.kind) {
    case 'swap_template':
      return f.template_id;
    case 'narrow':
    case 'widen':
    case 'text':
      return parentTemplateId;
    default: {
      const _exhaustive: never = f;
      return parentTemplateId; // unreachable; satisfies typechecker
    }
  }
}

// Inside the component
const parentTemplateQuery = useTemplate(parentStudy.data?.template_id);
const hasActionableFollowup = followups.some((f) => ACTIONABLE_FOLLOWUP_KINDS[f.kind]);

// In the prefillValues useMemo
if (!ACTIONABLE_FOLLOWUP_KINDS[f.kind]) return undefined;
// … and template_id assignment:
template_id: resolveTemplateIdForPrefill(f, s.template_id),
```

**Tasks**

1. Add the module-level `ACTIONABLE_FOLLOWUP_KINDS` lookup + the `resolveTemplateIdForPrefill` helper.
2. Replace the inline `hasActionableFollowup` computation with the lookup-based version.
3. Add `const parentTemplateQuery = useTemplate(parentStudy.data?.template_id);` near the existing `useStudy` call.
4. Pass `parentTemplate` / `parentTemplateLoading` / `parentTemplateError` props into `<SuggestedFollowupsPanel>`.
5. Refactor the prefill `useMemo` to use the exhaustive lookup + helper.
6. Extend / create the vitest covering AC-11 + AC-12 + the F1 regression case.
7. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- `hasActionableFollowup` returns `true` for digests containing only swap_template followups (F1 regression covered).
- `useStudy(parentStudyId, { enabled: ... && hasActionableFollowup })` enables for swap_template-only digests.
- Page passes `parentTemplate` / `parentTemplateLoading` / `parentTemplateError` to the panel.
- Prefill seeds `template_id = followup.template_id` for swap_template per AC-11 via the exhaustive helper.
- POST body carries `body.template_id = swap target` AND `body.parent = {proposal_id, followup_index}` per AC-12.
- Both the `hasActionableFollowup` gate AND the prefill template_id resolver are discriminator-exhaustive (per D-28 + GPT-5.5 cycle-1 F4).
- `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.

---

### Story 3.4 — Glossary additions

**Outcome:** Two new glossary keys land in `ui/src/lib/glossary.ts` matching the spec §11 copy.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | After the existing `proposal.followup_search_space_diff` key (line 502), add two new keys: `proposal.followup_kind_swap_template` and `proposal.followup_declared_params_diff` with the exact spec §11 copy. Add a source-of-truth comment above `proposal.followup_kind_swap_template`: `// Source-of-truth: backend/app/domain/study/followups.py SwapTemplateFollowup`. |
| `ui/src/__tests__/lib/glossary.test.ts` | Extend with `proposal.followup_kind_swap_template` and `proposal.followup_declared_params_diff` presence assertions (the existing test pattern in this file asserts every glossary key resolves to non-empty `short` text). |

**Tasks**

1. Insert the two new keys with the exact spec §11 copy.
2. Add the source-of-truth comment above the kind key.
3. Extend the glossary test.
4. Run `cd ui && pnpm test ui/src/__tests__/lib/glossary.test.ts`.

**Definition of Done (DoD)**

- Both keys present with the spec §11 copy.
- Source-of-truth comment on the kind key.
- Glossary test passes.

---

### Story 3.5 — `create-study-modal` autofill suppression guard (FR-14)

**Outcome:** The existing Step-4 search-space autofill effect in `create-study-modal.tsx` (lines 425-465, from `feat_agent_propose_search_space`) is augmented with an explicit guard: when `initialValues` is non-null AND `initialValues.search_space_text` is non-empty (i.e., a followup prefill is active), the autofill is suppressed for that modal-open lifetime. The existing implicit guard (textarea === default `'{}'` or empty) likely already covers the case, but per spec D-26, this story makes the guard explicit so a future autofill rewrite can't regress AC-16.

**Reference: current modal structure**

- **File:** `ui/src/components/studies/create-study-modal.tsx`
- **Current line count:** 1274 (verified `wc -l`).
- **Existing prefill effect:** lines 290-318 (the `useEffect` keyed on `[open, initialValues]` that calls `form.reset(...)` when `initialValues` is provided — added by Tier-A Story 5.2).
- **Existing autofill effect:** lines ~420-465 — the block that calls `buildStarterSpaceForTemplate(...)`, computes `autoJson`, then writes it to the `search_space_text` field via `form.setValue(...)` when the current text is empty or matches a prior autofill signature.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Inside the autofill effect at lines ~420-465, **before** the existing `const trimmed = (current ?? '').trim(); const isEmpty = trimmed === '' || trimmed === '{}';` check, add an early return: `if (initialValues && initialValues.search_space_text && initialValues.search_space_text.trim() !== '' && initialValues.search_space_text.trim() !== '{}') { return; }`. This guard reads from the prop, not the form state, so it stays valid across re-renders within the same modal-open lifetime. The existing implicit "matchesPriorSignature" path remains untouched — operators editing manually still get the Undo-toast behavior. |
| `ui/src/__tests__/components/studies/create-study-modal.followup-prefill.test.tsx` (extend existing) | Add an AC-16 case: render the modal open with `initialValues.template_id = "B"` (different from the previously-selected template) AND `initialValues.search_space_text = '{"params":{"phrase_slop":{"type":"int","low":0,"high":5}}}'`. Stub the `useTemplate(B)` query to resolve with template B's declared_params. After all effects settle, assert the textarea bound to `search_space_text` still contains the prefilled JSON character-for-character (not the auto-generated starter space for template B). |

**Tasks**

1. Add the early-return guard in the autofill effect.
2. Extend the followup-prefill vitest with AC-16.
3. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- Autofill effect short-circuits when `initialValues.search_space_text` is non-empty per FR-14.
- AC-16 regression test passes.
- Existing autofill tests (`create-study-modal.auto-fill.test.tsx`, `create-study-modal.auto-fill.undo.test.tsx`) still pass — the new guard is strictly narrowing.

---

## Epic 4 — API contract assertions (no code change beyond Tier-A re-export)

### Story 4.1 — Contract tests assert widened `FollowupItem` union surfaces on `DigestResponse` + `_DigestEmbed`

**Outcome:** The widened `FollowupItem` union (Story 1.1) automatically flows through the existing re-export at `backend/app/api/v1/schemas.py:28` and the existing `list[FollowupItem]` field declarations at `schemas.py:981` (`DigestResponse`) + `schemas.py:1042` (`_DigestEmbed`). No router or schema code change is required. The contract tests in this story assert that the OpenAPI schema's `FollowupItem` oneOf now includes the `SwapTemplateFollowup` branch with `{kind, rationale, template_id, search_space}` per AC-9.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/contract/test_digest_response_shape.py` | Extend with: assert OpenAPI `FollowupItem` discriminated-union oneOf includes a branch with `kind: "swap_template"` AND `template_id: string` AND `search_space: object` per AC-9; assert a swap_template item round-trips through `DigestResponse.model_validate(...).model_dump_json()` deep-equal. |
| `backend/tests/contract/test_digest_proposal_api_contract.py` (the existing file covering proposal-detail digest embed — verified via `ls backend/tests/contract/`; spec §14 referred to it as `test_proposal_detail_shape.py`, which does not exist in the repo. Per GPT-5.5 cycle-1 F7, the canonical file is the one named here.) | Extend with the analogous oneOf assertion on `_DigestEmbed.suggested_followups`. |

**Tasks**

1. Extend both contract tests with the swap_template branch assertions. Use the existing OpenAPI-schema extraction pattern (e.g., `fastapi_app.openapi()`) per Tier-A pattern.
2. Run `make test-contract`.

**Definition of Done (DoD)**

- Both contract tests pass.
- OpenAPI `FollowupItem` includes the `SwapTemplateFollowup` branch.
- AC-9 satisfied.

---

### Story 4.2 — Integration test: `POST /api/v1/studies` with swap_template lineage

**Outcome:** A new integration test case in the existing `test_studies_with_parent_followup.py` covers AC-12: a `POST /api/v1/studies` request whose body has `template_id = <swap target>` AND `parent = {proposal_id, followup_index}` pointing at a parent proposal whose digest's `suggested_followups[i]` is a `swap_template` item. The endpoint succeeds with HTTP 201; the new study row has `template_id = <swap target>` AND `parent_proposal_id = <pid>` AND `parent_proposal_followup_index = i` (the Tier-A CHECK constraint + trigger continue to apply per FR-13).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_studies_with_parent_followup.py` | Add a test case: seed two templates A + B (same engine_type, B has at least one declared_param overlap with A); seed a parent study against A + proposal + digest whose `suggested_followups[0]` is a valid `swap_template` item pointing at B; POST `/api/v1/studies` with `body.template_id = B.id`, `body.parent = {proposal_id: <pid>, followup_index: 0}`, plus the other required fields from the parent study; assert 201; fetch the new study row directly via SQLAlchemy and assert all three lineage assertions. |

**Tasks**

1. Add the test case using existing fixture helpers in the file.
2. Run `make test-integration backend/tests/integration/test_studies_with_parent_followup.py`.

**Definition of Done (DoD)**

- Test passes against the existing schema (no schema change).
- AC-12 satisfied (lineage + cross-template `template_id` both verified at the DB layer).

---

## Epic 5 — E2E test

### Story 5.1 — Playwright happy path: swap_template card → Run → submit → land on new study with `template_id = B`

**Outcome:** The existing `ui/tests/e2e/followup_run.spec.ts` (from Tier A) gains a second test (or extends the existing one with a swap_template branch) driving the full "Run this followup" flow against the real backend with no `page.route()` mocking.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/followup_run.spec.ts` | Add a second test covering swap_template happy path: via API helpers seed two templates A (declared `title_boost: float`) + B (declared `title_boost: float, phrase_slop: int`) sharing one param + B having one extra; seed a parent study against A with one trial; seed a proposal + digest whose `suggested_followups` includes one valid `swap_template` item pointing at B (use a test-only direct-DB-seed helper since the digest worker isn't deterministic without an LLM stub — pattern matches Tier A's E2E fixture); navigate to `/proposals/<pid>`; assert the swap_template card renders (`page.locator('[data-testid=followup-0-card]')` + the "Swap template" badge); click `[data-testid=followup-0-run]`; assert the modal opens with template B selected (assert via the form field's selected value, not via `page.route()` mock); submit the form (filling any required fields not auto-populated); assert navigation to `/studies/<new id>`; via API helper assert `GET /api/v1/studies/{new_id}` returns `template_id = B.id` per AC-12 + spec §14 + D-27. **Lineage column assertions are out of scope here per D-27 — they live in Story 4.2 integration test where the fixture has direct DB-row access.** |
| `ui/tests/e2e/helpers/` (extend existing helpers) | Add a helper `seedDigestWithSwapTemplateFollowup(...)` that POSTs a fixture digest payload via a test-only DB-seed mechanism (the Tier-A `seedDigestFollowup(...)` helper is the closest analogous; extend or duplicate the pattern). |

**Tasks**

1. Extend the helpers (or add the new swap_template fixture helper).
2. Write the second E2E test case.
3. Run `cd ui && pnpm test:e2e:stable -g "swap_template"` (or the project's canonical stable-profile invocation for the new spec).

**Definition of Done (DoD)**

- Spec passes on the stable Playwright profile.
- No `page.route()` calls in the spec.
- All assertions use `page.locator(...)` for DOM checks; API `request` used only for fixture setup + final `GET /api/v1/studies/{id}` verification.
- AC-12 satisfied via E2E (`template_id = B` on the new study).

---

## 3) Testing workstream (required)

Tests are planned by layer; every test file has exactly one owner story.

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Files (one owner story each):
  - `backend/tests/unit/domain/study/test_followups.py` — Story 1.1 (extend; per-kind round-trip + tuple length)
  - `backend/tests/unit/domain/study/test_followups_backcompat.py` — Story 1.1 (extend; malformed-template_id downgrade)
  - `backend/tests/unit/domain/study/test_template_swap.py` — Story 1.2 (new; remap helper coverage)
  - `backend/tests/unit/workers/test_digest_prompt_render.py` — Story 2.2 (extend; new Jinja blocks)
  - `backend/tests/unit/workers/test_digest_followup_validation.py` — Story 2.3 (new; 4 reason codes + AC-15 truncate-before-checks)
- DoD: every row in spec §14 unit-test list covered; per-kind round-trip + rejection covered; helper failure modes covered.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Files (one owner story each):
  - `backend/tests/integration/test_digest_followup_roundtrip.py` — Story 2.3 (extend; swap_template happy path + AC-13 catalogue-empty)
  - `backend/tests/integration/test_studies_with_parent_followup.py` — Story 4.2 (extend; AC-12 cross-template lineage)
- DoD: happy path + AC-12 + AC-13 covered.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Files (one owner story each):
  - `backend/tests/contract/test_digest_response_shape.py` — Story 4.1 (extend; OpenAPI oneOf swap_template branch)
  - `backend/tests/contract/test_digest_proposal_api_contract.py` — Story 4.1 (extend; `_DigestEmbed.suggested_followups` shape)
- DoD: every endpoint touched by the plan has contract coverage of the widened union.

### 3.4 Schema-shape unit test
- Location: `backend/tests/unit/workers/test_digest_response_format.py` (existing)
- Owner story: Story 2.1 (extend; 4-value enum + `template_id` in `required`)

### 3.5 E2E tests
- Location: `ui/tests/e2e/`
- **Rule: real browser interactions via `page`; no `page.route()` mocking.** API `request` is for test setup only.
- Files (one owner story each):
  - `ui/tests/e2e/followup_run.spec.ts` — Story 5.1 (extend; swap_template happy path)
- DoD: stable Playwright profile pass; all assertions exercise the browser DOM.

### 3.6 Frontend component tests (vitest)
- Location: `ui/src/__tests__/`
- Files (one owner story each):
  - `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` — Story 3.1 (extend; KIND_LABELS smoke) AND Story 3.2 (extend; swap_template card branches)
  - `ui/src/__tests__/lib/enums.test.ts` — Story 3.1 (extend; 4-tuple)
  - `ui/src/__tests__/app/proposals/page.followup-prefill.test.tsx` — Story 3.3 (extend or new; AC-11 + AC-12 prefill)
  - `ui/src/__tests__/components/studies/create-study-modal.followup-prefill.test.tsx` — Story 3.5 (extend; AC-16)
  - `ui/src/__tests__/lib/glossary.test.ts` — Story 3.4 (extend; two new keys)

Note: the panel test file has two owner stories (3.1 + 3.2). Both stories' DoDs require the file to be in a passing state at story-completion — story 3.2 extends what 3.1 added.

### 3.7 Existing test impact audit

| Test file | Pattern | Required action |
|---|---|---|
| `backend/tests/integration/_digest_helpers.py` | LLM mock returning `{"suggested_followups": [{...}]}` for narrow/widen/text | Extend a helper variant to emit a `swap_template` item (with valid `template_id`). Existing helpers unchanged. |
| `backend/tests/integration/test_digest_template_drift*.py` | drift-followup as the first text item | No change — drift path is unaffected by the widening. |
| `backend/tests/unit/workers/test_digest_response_format.py` | `kind` enum length-3 assertion (if present) | Update to length-4 with `swap_template`. |
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | existing narrow/widen/text card assertions | No regression — Story 3.1 keeps runtime behavior; Story 3.2 adds new assertions. |
| `ui/tests/e2e/followup_run.spec.ts` (existing narrow/widen test) | navigates and asserts narrow/widen Run flow | No regression — Story 5.1 adds a second test, doesn't modify the first. |

### 3.8 Migration verification
- N/A — this plan ships **no migration** (FR-13 + spec §3). The Tier-A 0018 + 0019 migrations apply unchanged.

### 3.9 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm test:e2e:stable` (Story 5.1 spec must pass)
- [ ] `scripts/ci/verify_enum_source_of_truth.sh` (AC-14 — 4-tuple alignment)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`**
- [ ] After the final story merges: add a new entry to "Most recent meaningful changes" noting the feature shipped with its PR # and date.
- [ ] No Alembic head change (this plan ships no migration; head stays `0019_digests_suggested_followups_jsonb`).
- [ ] Update active-work / queued sections to mark `feat_digest_executable_followups_swap_template` complete.

**`architecture.md`**
- [ ] Update the `backend/app/domain/study/` line in the directory map to include `template_swap.py` (sibling to `followups.py` + `search_space_defaults.py`).
- [ ] Add a short note to the digest-worker section describing the new remap step + 4 reason codes.

**`CLAUDE.md`**
- [ ] No new conventions / rules / env vars / build commands.

### 4.1 Architecture docs (`docs/01_architecture/`)
- [ ] `data-model.md` — extend the `digests.suggested_followups` JSONB-shape note to include the `swap_template` variant payload shape; add an example payload mirroring spec §9.
- [ ] `llm-orchestration.md` — describe the new `swap_template` kind in the digest LLM output catalogue + the `<available_templates>` + `<parent_template_declared_params>` prompt blocks + the worker's remap step + the 4 reason-code taxonomy.
- [ ] `api-conventions.md` — no change (no new error codes).

### 4.2 Product docs (`docs/02_product/`)
- [ ] No change (this spec lives here; single-phase delivery).

### 4.3 Runbooks (`docs/03_runbooks/`)
- [ ] Extend the digest-debugging runbook (or `agent-debugging.md`) to mention the new structlog event `digest_followup_swap_template_remapped` (INFO) + the 4 downgrade `reason` codes for `swap_template` (`not_found` / `same_as_parent` / `engine_type_mismatch` / `remap_invalid_search_space`).

### 4.4 Security docs (`docs/04_security/`)
- [ ] No change (no new secret surface, no new data flow beyond the internal catalogue SELECT).

### 4.5 Quality docs (`docs/05_quality/`)
- [ ] No change (new test files follow the existing layer convention).

**Documentation DoD**
- [ ] `state.md` + `architecture.md` updated.
- [ ] `data-model.md` + `llm-orchestration.md` updated.
- [ ] Runbook entry added.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- The Story 3.1 panel exhaustiveness refactor is the only non-additive code change in this plan. It is required per D-28 to make the discriminator-exhaustive shape mandatory before the 4th kind variant is added.
- No new abstraction layers; no speculative redesign of the digest worker beyond what's needed for FR-7 / FR-8.

### 5.2 Planned refactor tasks

- [ ] (Frontend, Story 3.1) Refactor `SuggestedFollowupsPanel`'s `if (f.kind === 'narrow' || f.kind === 'widen')` chain into `Record<FollowupKind, boolean>` lookups.
- [ ] (Backend, Story 2.3) Extract `_downgrade_swap_template_to_text` as a private worker-module helper.
- [ ] (Backend, Story 2.3) Extract the per-`swap_template` loop body as a private async helper so it's directly unit-testable.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by Story 3.1 vitest (existing narrow/widen/text behavior unchanged after refactor).
- [ ] `make lint` + `make typecheck` + `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.
- [ ] No expansion of product scope (Tier C explicitly out — sibling backlog folder).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_executable_followups` (Tier A, PR #225) | All stories | Shipped 2026-05-24 | Blocker — entire substrate. Risk = none. |
| `feat_agent_propose_search_space` (PR #175) | Story 1.2 | Shipped 2026-05-21 | Blocker — provides `build_starter_search_space`. Risk = none. |
| `feat_digest_proposal` (PR #41) | Story 2.3 | Shipped 2026-05-11 | Blocker — provides digest worker scaffolding. Risk = none. |
| OpenAI-compatible endpoint with structured-output (`json_schema`) | Story 2.1 worker | Capability check gates | Risk = none — capability-degraded path persists `[]` (Tier-A D-27 preserved). |
| `useTemplate(id)` hook at `ui/src/lib/api/query-templates.ts:45` | Story 3.2 + 3.3 | Shipped (existing) | Risk = none. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM emits multiple distinct `swap_template` targets in a single digest, exceeding the single `useTemplate` hook call in Story 3.3 | L | M | Story 3.3 documents the single-target assumption; multi-target case falls through to loading-or-error UI (panel still renders, Run button still works because prefill uses `followup.template_id` directly). If observed in practice, extend to `useQueries` in a follow-up. Captured as a future enhancement note in the docs/03_runbooks update (Story 2.3 DoD). |
| LLM hallucinates `template_id` values not in the catalogue | M | L | Worker FR-8 downgrades to `text` with `reason="not_found"`; operator sees rationale prefix. Visible failure, not silent. |
| Catalogue payload large enough to cost extra tokens noticeably | L | L | Spec §10 + §13 note MVP1 catalogues are small (≤ dozens of templates). Existing daily budget gate at `backend/workers/digest.py` catches token-cost growth. |
| Worker's per-`swap_template` DB lookup adds noticeable latency | L | L | Spec §13: ≤ 100ms added at single-laptop scale; one cached lookup per distinct target id per call. |
| Tier-A panel exhaustiveness refactor regresses narrow/widen behavior | L | M | Story 3.1 DoD requires existing tests to keep passing without modification — the refactor is type-shape only, not runtime behavior. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| LLM emits `swap_template` with bogus `template_id` | LLM hallucination | Worker downgrades to `text` with `reason="not_found"`; WARN structlog event | Automatic — operator sees `Suggestion` card with `[validation failed: …]` prefix |
| LLM emits `swap_template` with `template_id == study.template_id` | LLM ignoring "skip same-as-parent" instruction | Downgrade with `reason="same_as_parent"` | Automatic |
| LLM emits `swap_template` whose target's `engine_type` differs from parent cluster | LLM ignoring catalogue filter | Downgrade with `reason="engine_type_mismatch"` | Automatic |
| LLM emits `swap_template` whose `search_space` post-remap exceeds cardinality cap | Heuristic-fill blow-up on disjoint params | `remap_search_space_for_swap_target` raises `InvalidSearchSpaceError`; worker downgrades with `reason="remap_invalid_search_space"` | Automatic |
| LLM emits `swap_template` whose `search_space.params` is empty | Should be impossible — Pydantic `min_length=1` rejects at parser layer | Downgrade via existing Tier-A decision-table path; `original_kind="swap_template"`, `reason` absent (parse-layer) | Automatic |
| LLM emits 6+ followups, 6th is bogus swap_template | LLM ignoring `maxItems: 5` (rare with strict mode) | Worker truncates to 5 BEFORE existence checks (AC-15); 6th item never reaches DB lookup | Automatic |
| `useTemplate(swap_target)` fetch fails | Network error / 500 | Panel renders error message inside declared-params diff; Run button stays enabled (prefill uses `followup.template_id` directly) | Manual — operator can retry or submit anyway |
| Swap target deleted between digest persist and operator click | Concurrent template hard-delete | `POST /api/v1/studies` returns 400 `TEMPLATE_NOT_FOUND` (existing); modal surfaces error | Manual — operator picks another template or abandons |
| Catalogue empty (only parent template registered) | Single-template install | Worker omits `<available_templates>` Jinja block; system prompt instructs LLM to skip `swap_template` | Automatic |
| `digests.suggested_followups` row contains a legacy shape (defensive) | Read of pre-Tier-A row | `parse_followup_list(...)` wraps strings as `text` items per Tier-A FR-2 | Automatic |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 — Domain** (Story 1.1 → 1.2) — pure domain, no DB. Unblocks everything else.
2. **Epic 2 — Worker** (Story 2.1 → 2.2 → 2.3) — depends on Epic 1. Story 2.3 depends on 2.1 + 2.2.
3. **Epic 4 — API contract assertions** (Story 4.1 → 4.2) — depends on Epic 1 + Epic 2 (worker persists swap_template items for the integration test).
4. **Epic 3 — Frontend** (Story 3.1 → 3.2 → 3.3 → 3.4 → 3.5) — depends on Epic 4 (typed OpenAPI surface). Story 3.4 (glossary) has no backend dep — can run earliest.
5. **Epic 5 — E2E** (Story 5.1) — depends on everything.

**Frontend story ordering note** (per GPT-5.5 cycle-1 F5): **Story 3.4 (glossary) MUST land before Story 3.1 + 3.2** because the panel renders `InfoTooltip glossaryKey={`proposal.followup_kind_${f.kind}`}` (line 75 of the current panel). Once Story 3.1 widens `FollowupKind` to include `swap_template`, the template literal resolves to `proposal.followup_kind_swap_template` which must exist in the glossary or the `InfoTooltip` will surface as a missing-key warning. The corrected within-Epic order is: **3.4 → 3.1 → 3.2 → 3.3 → 3.5**.

### Parallelization opportunities

- Story 1.1 (domain union) + Story 3.4 (glossary): both have no other dep — can run in parallel.
- Story 2.2 (prompts) can land while Story 2.1 (schema) is being implemented — different files.
- Story 3.2 (panel card) + Story 3.3 (page orchestration) can split between two agents; Story 3.2 ships the panel with `parentTemplate` / per-card `useTemplate(...)` props; Story 3.3 wires the page-level state.
- Story 3.5 (autofill guard) is independent of 3.1–3.4 — can run any time after Story 1.1.

---

## 8) Rollout and cutover plan

- Rollout stages: single PR; merge to `main` triggers no auto-deploy (MVP1 has no remote staging).
- Feature flag strategy: none. The widened union replaces the legacy in one PR; no flag.
- Migration/cutover steps: none — no schema change.
- Reconciliation/repair strategy: none — legacy `digests.suggested_followups` rows are already JSONB-shaped from Tier A; this plan only widens the discriminated union.

---

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — `SwapTemplateFollowup` + union widening
- [ ] Story 1.2 — `template_swap.py` helper + `RemapResult`
- [ ] Story 2.1 — `DIGEST_RESPONSE_SCHEMA` extension + worker pre-clean
- [ ] Story 2.2 — LLM prompts (system + user.jinja + `render_digest_user_prompt`)
- [ ] Story 2.3 — Worker catalogue fetch + remap step + reason codes
- [ ] Story 3.1 — `FOLLOWUP_KIND_VALUES` widening + panel exhaustiveness refactor
- [ ] Story 3.2 — Swap_template card with declared-params diff
- [ ] Story 3.3 — Page orchestration: lazy `useTemplate` + prefill `template_id = swap target`
- [ ] Story 3.4 — Glossary additions
- [ ] Story 3.5 — Autofill suppression guard (FR-14)
- [ ] Story 4.1 — Contract test assertions for widened union
- [ ] Story 4.2 — Integration test for cross-template lineage
- [ ] Story 5.1 — Playwright happy path

### Blocked items
- None.

### Done this sprint
- (filled by `/impl-execute` as stories ship)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented where applicable (no new endpoints in this plan — Story 4.1 / 4.2 verify the existing endpoints' widened response shape).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all four layers where applicable.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or targeted subset with explanation)
    - [ ] `make test-contract`
    - [ ] `cd ui && pnpm test` (if UI touched)
    - [ ] `cd ui && pnpm test:e2e:stable` (if E2E touched)
- [ ] No migration round-trip evidence required (no schema change).
- [ ] Related docs updated in same PR when behavior/contract changed.

---

## 11) Plan consistency review

Cross-checks performed:

1. **Spec ↔ plan endpoint count:** 3 endpoints in spec §8.1 (all response widenings); 3 covered by plan (Story 4.1 covers both GETs; Story 4.2 covers `POST /api/v1/studies` via integration test). Match.
2. **Spec ↔ plan error code coverage:** Spec §8.5 introduces 0 new error codes. Plan adds none. Match.
3. **Spec ↔ plan FR coverage:** All 14 FRs assigned to stories in §1 traceability table. Match.
4. **Story internal consistency:** Modified files verified to exist (file paths verified via `Read` + `Bash ls`); no file double-claimed except `suggested-followups-panel.test.tsx` which has two stories (3.1 + 3.2) — both extend, no ownership conflict.
5. **Test file count:** 5 unit (3 backend domain + 1 worker prompt + 1 worker validation) + 2 integration + 2 contract + 1 schema-shape unit + 1 E2E + 5 vitest = 16 test files. Each assigned to exactly one owner story (panel test has two owners, both extend; not a conflict).
6. **Gate arithmetic:** No per-epic numeric gates declared. Epic completes when all stories' DoDs satisfied.
7. **Open questions resolved:** Spec §19 has no open questions; D-1 through D-34 are decisions. Match.
8. **Frontend UI Guidance completeness (Story 3.2 + 3.3):** Insertion point ✓, Analogous markup ✓ (copy-pasteable JSX from existing line 80-122 search-space `<details>` block), Layout ✓ (`grid grid-cols-2 gap-3`), Modal pattern ✓ (deferred to Story 3.3 page orchestration — existing modal), Visual consistency table ✓, Component composition ✓ (inline rationale matches Tier A), Interaction behavior table ✓, Handler patterns ✓ (sharedKeys memo), IA placement ✓ (lives inside existing panel on `/proposals/[id]`), Tooltips ✓ with glossary keys + source-of-truth comments, Legacy behavior parity ✓ (explicit "N/A — no >100 LOC delete" note per template rules).
9. **Codebase accuracy** (verified via Bash):
    - Migration head: `0019_digests_suggested_followups_jsonb` (no migration needed; ✓).
    - `backend/app/domain/study/followups.py`: 335 lines; `FOLLOWUP_KIND_VALUES` at line 123 with 3 entries; `_TRUNCATE_LIMIT = 200` at line 60; `_truncate` at line 63; `_emit_downgrade_warn` at line 129 (private); `parse_followup_list` at line 217. ✓
    - `backend/app/domain/study/search_space_defaults.py`: 344 lines; `build_starter_search_space` at line 144; `InvalidSearchSpaceError` imported at line 34; raises on empty `declared_params` at line 167. ✓
    - `backend/workers/digest.py`: 1055 lines; `DIGEST_RESPONSE_SCHEMA` at lines 186-218; parent-template fetch at line 680; `render_digest_user_prompt` call at line 735; per-item translation loop at lines 840-865; `parsed_followups[:5]` truncation at line 871; `serialize_followup_list` at line 873; per-kind counts at line 877. ✓
    - `backend/app/db/repo/query_template.py`: `get_query_template` at line 41; `list_query_templates(db, *, engine_type=None, ...)` at line 55 with engine_type filter at line 70-71. ✓
    - `backend/app/db/models/query_template.py`: `engine_type: Mapped[str]` at line 29; `declared_params: Mapped[dict[str, Any]]` at line 34. ✓
    - `backend/app/api/v1/schemas.py`: `from backend.app.domain.study.followups import FollowupItem` at line 28 (re-export); `DigestResponse.suggested_followups: list[FollowupItem]` at line 981; `_DigestEmbed.suggested_followups: list[FollowupItem]` at line 1042; `ParentFollowupRef` at line 614; `CreateStudyRequest.parent: ParentFollowupRef | None = None` at line 655. ✓
    - `ui/src/components/proposals/suggested-followups-panel.tsx`: 146 lines; `KIND_LABELS` at lines 41-45; `if (f.kind === 'narrow' || f.kind === 'widen')` at line 78; `<details>` at line 80; `data-testid` patterns match plan. ✓
    - `ui/src/app/proposals/[id]/page.tsx`: 303 lines; `useStudy` import at line 18; `runFollowupIndex` state at line 124; `useStudy(parentStudyId ?? '', { enabled: ... })` at line 132; `prefillValues` memo at lines 136-184. ✓
    - `ui/src/components/studies/create-study-modal.tsx`: 1274 lines; `PrefillValues` at line 165; modal-open reset effect at lines 290-318; autofill effect block at lines ~420-465. ✓
    - `ui/src/lib/enums.ts`: `FOLLOWUP_KIND_VALUES` at line 248 with 3 entries; source-of-truth comment at line 247. ✓
    - `ui/src/lib/api/query-templates.ts`: `useTemplate(id)` at line 45 with internal `enabled: Boolean(id)` gating. ✓
    - `ui/src/lib/glossary.ts`: existing followup keys at lines 480-507 (insertion point after 502 verified). ✓
    - `prompts/digest_narrative.system.md`: 112 lines; the "three kinds" section starts around line 60. ✓
    - `prompts/digest_narrative.user.jinja`: 60 lines; `<parent_search_space>` block at line 40-44. ✓
10. **Enumerated value contract verification:** Story 3.1 cited; 3-column compare done (backend `FOLLOWUP_KIND_VALUES` ↔ spec §8.4 ↔ frontend `enums.ts`) all `narrow|widen|text|swap_template` after this plan. AC-14 grep gate enforced. No frontend `<select>` exposes `kind` (D-12 unchanged).
11. **Audit-event coverage:** MVP1 — N/A. Spec §6 widens Tier-A pre-shaped events' allowed value spaces (no new event types). Activates at MVP2.
12. **Persistence scope:** no `localStorage` / `sessionStorage` introduced.

No unresolved findings.

---

## 11b) Cross-model review log (GPT-5.5)

### Cycle 1 — 2026-05-24

7 findings. Opus adjudication:

| ID | Severity | Pass | Claim (short) | Verdict | Action |
|---|---|---|---|---|---|
| F1 | High | B | `hasActionableFollowup` excludes swap_template; swap-only digests skip parent-study fetch | **Accept** | Story 3.3 — added module-level `ACTIONABLE_FOLLOWUP_KINDS: Record<FollowupKind, boolean>` lookup with `swap_template: true`; widened the gate; added regression test for swap_template-only digest. |
| F2 | Medium | B | Single `useTemplate(swapTargetIds[0])` violates per-card FR-10 + can't render multi-target digests | **Accept** | Story 3.2 — extracted `SwapTemplateCard` child component that calls `useTemplate(followup.template_id)` at its own top level. Page no longer passes a `swapTargetsByTemplateId` map; per-card fetches are inside the card. Added multi-target vitest. |
| F3 | Medium | B | `useMemo` for `sharedKeys` placed inside `.map()` violates Rules of Hooks | **Accept** | Story 3.2 — `sharedKeys` `useMemo` now lives inside `SwapTemplateCard` (top-level hook). The map renders `<SwapTemplateCard ... />` per swap_template item. |
| F4 | Medium | B | Story 3.3 prefill check `if (f.kind !== 'narrow' && f.kind !== 'widen' && f.kind !== 'swap_template')` is not discriminator-exhaustive | **Accept** | Story 3.3 — replaced with `ACTIONABLE_FOLLOWUP_KINDS[f.kind]` lookup gate AND extracted `resolveTemplateIdForPrefill(f, parentId)` helper with exhaustive `switch` + `_exhaustive: never` line; satisfies D-28. |
| F5 | Medium | B | Story 3.4 (glossary) runs AFTER 3.1/3.2 which reference the new keys → typecheck/test failures | **Accept** | §7 Sequencing — added explicit "Frontend story ordering note" stating 3.4 MUST land BEFORE 3.1 + 3.2. Corrected within-Epic order: 3.4 → 3.1 → 3.2 → 3.3 → 3.5. |
| F6 | Medium | B | Worker pseudo-code uses private `_truncate` symbol without import | **Accept** | Story 2.3 — added "Truncation symbol provenance" note + Task 4b: promote `_truncate` to public `truncate_validation_error` in `followups.py` (rename + drop underscore + add to `__all__`), import from worker. |
| F7 | Low | A | Spec named contract test `test_proposal_detail_shape.py`; plan uses `test_digest_proposal_api_contract.py` | **Accept** | Story 4.1 modified-files table — added explicit note that `test_proposal_detail_shape.py` does not exist; canonical file is `test_digest_proposal_api_contract.py` (verified via `ls backend/tests/contract/`). |

**Cycle outcome:** 7 accepted, 0 rejected. **6 of 7 are MAJOR** (F1–F4, F6 change implementation contracts; F2/F3 change file ownership; F4 changes the exhaustiveness shape; F6 changes a public/private boundary). F5 is sequencing only. F7 is naming reconciliation.

Per Step 7 convergence loop rules: major accepted corrections trigger a re-review.

### Cycle 2 — 2026-05-24

4 findings. Opus adjudication:

| ID | Severity | Pass | Claim (short) | Verdict | Counter-evidence |
|---|---|---|---|---|---|
| F1 | Medium | A | `disjoint_fill_param_names` semantic mismatch — heuristic-filled set includes shared-but-LLM-omitted params, conflicting with operator prose "Shared params take your LLM-proposed bounds" | **Reject** | This is a SPEC-level finding (§7 FR-3 vs §11 tooltip prose), not a plan finding. The plan inherits the spec's contract verbatim. The semantics are correct per spec FR-3 step 3 (`disjoint_fill = swap_names \ (parent_names ∩ llm_names)`) — when the LLM omits bounds for a shared param, that param has no trusted bound and falls through to heuristic fill (the only safe behavior). The operator-facing tooltip simplifies for brevity. Spec cycle-1 D-19 already adjudicated the naming. Out of scope for plan review. |
| F2 | Low | B | Stale §2 test-impact prose lists `disjoint-only` / `empty swap_search_space` cases that §14 + D-22 + D-34 removed | **Reject** | Same — SPEC-level prose drift between §2 (audit input) and §14 (authoritative test inventory) is a spec finding. Plan §3.1 unit-test list correctly references the §14-aligned cases (cardinality blowup, no-trusted-intersection, mixed). Stated "is_reraise=true" in the model's response — re-raises a cycle-1-adjacent concern without new information about the plan. |
| F3 | Medium | A | Worker-side downgrade events for `not_found` / `same_as_parent` / `engine_type_mismatch` aren't required to include `validation_error` field | **Reject** | The plan's Story 2.3 "Step 13.5" worker pseudo-code explicitly emits `validation_error=truncate_validation_error(downgraded.rationale)` on ALL 4 reason codes (lines `logger.warning(...)` with `validation_error=...` in both the FR-8 cascade branch AND the FR-7 step 3 InvalidSearchSpaceError branch). The implementation contract is correct in the plan; only the spec ACs are loose. Out of scope for plan review. |
| F4 | Medium | B | Spec FR-10 phrasing risks implementers calling `useTemplate` inside `.map()` (Rules of Hooks violation) without a mandated safe pattern | **Reject** | The plan ALREADY mandates the safe pattern. Story 3.2 modified-files table line 4 reads "extract a child component `SwapTemplateCard` that: calls `useTemplate(followup.template_id)` at its top". The Story 3.2 "Analogous markup pattern" shows the full `SwapTemplateCard` component with `const swapTargetQuery = useTemplate(followup.template_id);` at the top of the component body. Story 3.2 Tasks explicitly require the extraction. F4 is a re-raise of cycle-1 F3 (Rules of Hooks) with no new information — the correction already addresses it. |

**Cycle outcome:** 0 accepted, 4 rejected (all 4 with cited counter-evidence; F1 + F3 are spec-cycle concerns outside plan scope; F2 + F4 are re-raises of issues already resolved in cycle 1). Per skill Step 7 stop rules: "Stop when GPT-5.5 returns only findings that Opus has already rejected with cited counter-evidence in a previous cycle (no new information)" — a rejections-only cycle is a clean pass.

### Convergence

Final tally: **2 cycles, 11 findings (7 accepted in cycle 1, 0 accepted in cycle 2 with 4 rejected).** All 7 cycle-1 accepted corrections applied to plan; cycle-2 returned no new actionable findings against the plan. Convergence reached.

---

## 12) Definition of plan done

- [x] Every FR (14) is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e + vitest) are explicitly scoped.
- [x] Documentation updates across docs/01–05 are planned and owned.
- [x] Lean refactor scope and guardrails are explicit.
- [x] Phase/epic gates are measurable (each story's DoD).
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
- [x] Cross-model review (GPT-5.5) on this plan complete and findings adjudicated (§11b — 2 cycles; 7 accepted (cycle 1) + 4 rejected with cited counter-evidence (cycle 2); convergence reached at the rejections-only stop rule).

**Status:** Ready for Execution (pending user approval at the pipeline plan gate).
