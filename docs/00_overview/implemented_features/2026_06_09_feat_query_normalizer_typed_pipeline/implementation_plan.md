# Implementation Plan — Typed normalizer pipeline (ordered step list) + JS snippet + smart-quote contractions

**Date:** 2026-06-01 (gates cleared + shipped 2026-06-09)
**Status:** Complete (PR #509, squash-merged `7a24849`, merged 2026-06-09). Q-1 locked (include `expand_contractions_custom` inert, 6 steps) + Q-2 locked (frontend vitest fixture); all 8 stories shipped.
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Phase 1 foundation:** [`../feat_query_normalization_tuning/feature_spec.md`](../feat_query_normalization_tuning/feature_spec.md) (UNMERGED — plan stage), [`../feat_query_normalization_tuning/implementation_plan.md`](../feat_query_normalization_tuning/implementation_plan.md)
**Policy source(s):** CLAUDE.md (Absolute Rules #3, #4, #8 — adapter-confined, no hardcoded models, source-of-truth enum discipline), `docs/01_architecture/optimization.md`, `docs/01_architecture/adapters.md`

---

> ## ✅ EXECUTION GATE CLEARED (2026-06-09)
>
> Phase 1 (`feat_query_normalization_tuning`) **has merged to `main`** (PR #459). Story 0's precondition symbols were re-verified present 2026-06-09: `backend/app/domain/study/normalizers.py` exists and exports `NORMALIZER_CHOICES` / `normalize` / `_CONTRACTIONS` / `_PR_BODY_NORMALIZER_SNIPPETS`; `ui/src/lib/enums.ts` exports `NORMALIZER_VALUES`; both adapter pre-render hooks consume `query_normalizer`. Q-1 (include `expand_contractions_custom` inert — 6 steps) and Q-2 (frontend vitest fixture) are locked. The plan is now executable.
>
> **Story 0** remains a precondition gate run first: it asserts Phase 1's symbols exist and aborts the run otherwise.

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (§1).
- The Phase-1-merged precondition is a hard stop (Story 0).
- No migration — the Alembic head stays `0022_solr_engine_auth_check` (verified). The typed pipeline rides existing JSONB columns (`studies.search_space`, `trials.params`, `digests.recommended_config`, `proposals.config_diff`).
- No new error code (D-8) — every new validation failure rides `INVALID_SEARCH_SPACE` or Phase 1's `NORMALIZER_PARAM_SHAPE`.
- Pure-domain core (`normalize_pipeline`, enums) — no async, no DB, no I/O (CLAUDE.md domain-layer convention).
- Adapter-confined consumption (CLAUDE.md Absolute Rule #4 + spec I-5).

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| (precond) | Epic 0 / Story 0 | Phase-1-merged gate — asserts `normalizers.py` exists + exports `NORMALIZER_CHOICES`. |
| FR-1 (`NormalizerStep` enum + `normalize_pipeline` + `STEP_ORDER`/`LABEL_ORDER`/`STEP_LABEL_TOKEN`) | Epic 1 / Story 1.1 | Pure-domain core, extends Phase 1's `normalizers.py`. |
| FR-3 (smart-quote pre-normalization) | Epic 1 / Story 1.1 + 1.4 | Folded into `normalize_pipeline`'s contraction step (1.1); reaches the engine via the generalized adapter hook (1.4). |
| FR-3/FR-4 (adapter hook generalization) | Epic 1 / Story 1.4 | Extends Phase 1's `ElasticAdapter.render` / `SolrAdapter.render` to resolve bundle OR pipeline labels via `steps_for_label`→`normalize_pipeline`. |
| FR-2 (`NormalizerPipelineParam` + sampler + cardinality + desugar) | Epic 1 / Story 1.2 | Extends the three LIVE `search_space.py` dispatch sites. |
| FR-7 (`compute_default_params` empty-pipeline default) | Epic 1 / Story 1.2 | Same domain edit cluster. |
| FR-8 (reservation-validator extension + reserved-key-only) | Epic 1 / Story 1.3 | Extends Phase 1's `validate_normalizer_reservation`; router wiring. |
| FR-4 (PR-body JS snippet + label-driven generator) | Epic 2 / Story 2.1 | Extends Phase 1's `_render_pr_body_study_backed`. |
| FR-5 (three-way snippet parity invariant) | Epic 2 / Story 2.1 | Parity test over enumerated label cases. |
| FR-6 (frontend builder row + enum mirror + glossary + advisory broadening) | Epic 3 / Story 3.1 | Extends LIVE builder + Phase 1's enums/glossary/advisory. |
| FR-9 (docs sweep) | Epic 4 / Story 4.1 | optimization.md / adapters.md / local-dev.md. |
| — (AC-11 E2E) | Epic 3 / Story 3.2 | Real-backend Playwright. |

**Deferred-phase tracking:** Capability D (operator-supplied dictionaries) is a recommended-out Phase 2.5 kept as a documented §19 D-5 note in the spec; no `phase2_5_idea.md` is created unless the user elects to pursue it (per the spec's default). No other phase is deferred by this plan.

## 2) Delivery structure

**Conventions (project-specific):**
- Domain layer is pure — no DB, no async, no I/O (`backend/app/domain/study/normalizers.py`, `search_space.py`, `template_defaults.py`).
- Search-space dispatch uses `isinstance` over the `ParamSpec` discriminated union — match the existing Float/Int/Categorical pattern at `search_space.py:181-200` (cardinality) and `:249-270` (sampler).
- Router maps domain `ValueError` subclasses to error codes by name via the `_err(...)` helper at `studies.py` (the pattern Phase 1 uses for `validate_normalizer_reservation`).
- Frontend enum allowlists live in `ui/src/lib/enums.ts` with `// Values must match backend/...` comments; `<select>` options use `*_VALUES.map(...)` (CLAUDE.md Enumerated Value Contract Discipline + `form-select-discipline` lint guard).
- No hardcoded LLM model names — N/A here (no LLM call).
- `__all__` updated for any new public symbol.

**AI Agent Execution Protocol:** per template §AI Agent Execution Protocol. Story 0 runs first and aborts the entire run if Phase 1 is absent. Backend stories (Epic 1, 2) before frontend (Epic 3). Docs (Epic 4) last.

---

## Epic 0 — Precondition gate

### Story 0 — Phase 1 merged precondition
**Outcome:** The run aborts immediately with a clear message unless Phase 1's normalizer surface is present in the tree.

**New files:** none.

**Modified files:** none.

**Tasks**
1. Assert `backend/app/domain/study/normalizers.py` exists.
2. Assert it exports `NORMALIZER_CHOICES`, `DEFAULT_NORMALIZER`, `normalize`, `validate_normalizer_reservation`, `_CONTRACTIONS`, `_PATTERN`, `_PR_BODY_NORMALIZER_SNIPPETS`.
3. Assert `backend/app/domain/study/template_validator.py` exports `_RESERVED_NONRENDER_PARAMS` containing `"query_normalizer"`.
4. Assert `ui/src/lib/enums.ts` exports `NORMALIZER_VALUES` and `NORMALIZER_GLOSSARY_KEYS`.
5. Assert the adapter pre-render hook exists (grep `query_normalizer` in `backend/app/adapters/elastic.py` and `backend/app/adapters/solr.py`).
6. If ANY assertion fails: stop the run, report "Phase 1 (feat_query_normalization_tuning) is not merged — this plan is design-ahead and cannot execute yet."

**Definition of Done (DoD)**
- All six assertions pass against the working tree, OR the run is aborted with the precondition message.
- No code is written if the gate fails.

---

## Epic 1 — Backend domain: typed pipeline + smart quotes (FR-1, FR-2, FR-3, FR-7, FR-8)

### Story 1.1 — `NormalizerStep` enum + `normalize_pipeline` + ordering/label maps + smart quotes
**Outcome:** A pure-domain step engine: an operator-declared ordered step set normalizes a query string deterministically, with smart-quote-aware contraction expansion, reusing Phase 1's `_CONTRACTIONS`/`_PATTERN`.

**New files:** none (all additions land in Phase 1's `backend/app/domain/study/normalizers.py`).

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/normalizers.py` | Add `NormalizerStep(StrEnum)` (6 members), `STEP_ORDER`, `LABEL_ORDER`, `STEP_LABEL_TOKEN`, `_BUNDLE_TO_STEPS`, `normalize_pipeline(...)`, `_label_for_subset(...)`, `_pipeline_labels(...)`; smart-quote pre-normalization in the contraction step; optionally reimplement `normalize(text, bundle)` as a `normalize_pipeline` wrapper (D-6, preserve AC-1 byte-output). Update `__all__`. |

**Key interfaces**
```python
# backend/app/domain/study/normalizers.py  (additions to Phase 1's module)
from enum import StrEnum
from collections.abc import Sequence, Mapping
from typing import Final

class NormalizerStep(StrEnum):
    lowercase = "lowercase"
    trim = "trim"
    collapse_whitespace = "collapse_whitespace"
    strip_punctuation = "strip_punctuation"
    expand_contractions_en = "expand_contractions_en"
    expand_contractions_custom = "expand_contractions_custom"

# application order — whitespace cleanup LAST (D-11)
STEP_ORDER: Final[tuple[NormalizerStep, ...]] = (
    NormalizerStep.lowercase, NormalizerStep.strip_punctuation,
    NormalizerStep.expand_contractions_en, NormalizerStep.expand_contractions_custom,
    NormalizerStep.collapse_whitespace, NormalizerStep.trim,
)
# label order — Phase-1-compatible (D-12); decoupled from STEP_ORDER
LABEL_ORDER: Final[tuple[NormalizerStep, ...]] = (
    NormalizerStep.lowercase, NormalizerStep.trim,
    NormalizerStep.expand_contractions_en, NormalizerStep.collapse_whitespace,
    NormalizerStep.strip_punctuation, NormalizerStep.expand_contractions_custom,
)
STEP_LABEL_TOKEN: Final[Mapping[NormalizerStep, str]] = {  # expand_contractions_en -> "expand_contractions" (D-9)
    NormalizerStep.lowercase: "lowercase", NormalizerStep.trim: "trim",
    NormalizerStep.collapse_whitespace: "collapse_whitespace",
    NormalizerStep.strip_punctuation: "strip_punctuation",
    NormalizerStep.expand_contractions_en: "expand_contractions",
    NormalizerStep.expand_contractions_custom: "expand_contractions_custom",
}
_BUNDLE_TO_STEPS: Final[Mapping[str, tuple[NormalizerStep, ...]]] = {
    "none": (), "lowercase": (NormalizerStep.lowercase,),
    "lowercase+trim": (NormalizerStep.lowercase, NormalizerStep.trim),
    "lowercase+trim+expand_contractions": (NormalizerStep.lowercase, NormalizerStep.trim, NormalizerStep.expand_contractions_en),
}

def normalize_pipeline(query_text: str, steps: Sequence[NormalizerStep]) -> str: ...  # apply by STEP_ORDER; pure
def _label_for_subset(subset: frozenset[NormalizerStep]) -> str: ...  # LABEL_ORDER + STEP_LABEL_TOKEN, "+"-joined; () -> "none"
def _pipeline_labels(steps: Sequence[NormalizerStep]) -> list[str]: ...  # powerset; ordered by |subset| then lexicographic
def steps_for_label(label: str) -> tuple[NormalizerStep, ...]: ...  # reverse of _label_for_subset (token-aware); "none" -> (); shared by the adapter hook (1.4) and PR-body generator (2.1)
```

**Note:** `steps_for_label` is authored HERE in Story 1.1 (not 2.1) because both Story 1.4 (adapter hook) and Story 2.1 (PR-body generator) consume it.

**Tasks**
1. Add `NormalizerStep`, `STEP_ORDER`, `LABEL_ORDER`, `STEP_LABEL_TOKEN`, `_BUNDLE_TO_STEPS`.
2. Implement `normalize_pipeline`: filter declared steps to `STEP_ORDER`, apply each — `lowercase`→`.lower()`; `strip_punctuation`→`re.sub` over a defined ASCII punctuation class EXCLUDING apostrophe; `expand_contractions_en`→ `s.replace("’","'")` then Phase 1's `_PATTERN.sub`; `expand_contractions_custom`→identity; `collapse_whitespace`→`re.sub(r"\s+"," ", s)`; `trim`→`.strip()`.
3. Implement `_label_for_subset` (LABEL_ORDER ordering, token map, `"none"` for empty) and `_pipeline_labels` (powerset; list ordered ascending by subset size then lexicographic).
4. (Optional, D-6) reimplement `normalize` over `normalize_pipeline(_BUNDLE_TO_STEPS[bundle])`; verify Phase 1 AC-1 byte-parity; if fiddly, keep separate.
5. Update `__all__`.

**DoD**
- `test_normalizers_pipeline.py` (unit) covers AC-1 (canonical-order application incl. scrambled declaration), AC-6 (U+2019), permutation-invariance (I-1), empty-pipeline identity, the `strip_punctuation`+`collapse_whitespace`+`trim` whitespace-interaction example.
- `test_normalizers_bundle_compat.py` (unit) covers AC-5 / I-3 (byte-identical to Phase 1's four-bundle outputs).
- `mypy --strict` clean; module remains import-pure (no DB/httpx/openai import).

### Story 1.2 — `NormalizerPipelineParam` search-space type + sampler + cardinality + default
**Outcome:** A template can declare a `normalizer_pipeline` param; the Optuna loop samples over the powerset of declared steps; the live cardinality cap counts it; baseline/judgment renders default to `"none"`.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/search_space.py` | Add `NormalizerPipelineParam` (`type: Literal["normalizer_pipeline"]`, `steps: Annotated[list[NormalizerStep], Field(min_length=1)]`, `extra="forbid"`, `@model_validator` rejecting duplicate steps). Add it as the 4th member of `ParamSpec` (L87-90). Add the `isinstance(spec, NormalizerPipelineParam)` branch to `estimate_cardinality` (L181-200, `total *= 2 ** len(spec.steps)`) and to `apply_search_space` (L249-270, `trial.suggest_categorical(name, _pipeline_labels(spec.steps))`). Import the new symbols from `normalizers.py`. |
| `backend/app/domain/study/template_defaults.py` | In `compute_default_params` (L59-115): when a declared param is consumed as `normalizer_pipeline`, return the `"none"` label string (D-7), not `[]`. |

**Key interfaces**
```python
# backend/app/domain/study/search_space.py
class NormalizerPipelineParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["normalizer_pipeline"]
    steps: Annotated[list[NormalizerStep], Field(min_length=1)]
    @model_validator(mode="after")
    def _no_duplicate_steps(self) -> "NormalizerPipelineParam": ...  # raises ValueError("normalizer_pipeline: duplicate step '<s>'")

ParamSpec = Annotated[FloatParam | IntParam | CategoricalParam | NormalizerPipelineParam, Field(discriminator="type")]
```

**Tasks**
1. Define `NormalizerPipelineParam` + duplicate-step validator; add to `ParamSpec` union.
2. Extend `estimate_cardinality` and `apply_search_space` with the new `isinstance` branch (import `_pipeline_labels`).
3. Extend `compute_default_params` to return `"none"` for the pipeline case.

**DoD**
- `test_search_space_normalizer_pipeline.py` (unit) covers AC-2 (discriminator parse + duplicate rejection + enum rejection), AC-3 (cardinality `2**n`; cap trips), AC-4 (exact `_pipeline_labels` list `["none","lowercase","trim","lowercase+trim"]`).
- `test_template_defaults_normalizer_pipeline.py` (unit) covers AC-10 (`"none"` default).
- No migration (Alembic head unchanged); `mypy --strict` clean.

### Story 1.3 — Reservation validator extension + reserved-key-only + router wiring
**Outcome:** `POST /api/v1/studies` accepts a `NormalizerPipelineParam` under `query_normalizer`, rejects it under any other key, and broadens the wrong-shape message — all riding existing error codes.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/normalizers.py` | Extend `validate_normalizer_reservation`: accept the pipeline shape under `query_normalizer`; add `NormalizerPipelineMisplacedError(ValueError)` raised when a pipeline param appears under any non-`query_normalizer` key; broaden `NormalizerParamShapeError` message. **Circular-import avoidance (closes the dependency cycle):** `search_space.py` imports `NormalizerStep`/`_pipeline_labels` FROM `normalizers.py`, so `normalizers.py` MUST NOT import `NormalizerPipelineParam` FROM `search_space.py` at module level. `validate_normalizer_reservation` therefore discriminates on the **discriminator string** — `getattr(spec, "type", None) == "normalizer_pipeline"` — rather than `isinstance(spec, NormalizerPipelineParam)`. No class import needed; the discriminator value is the contract. (If a typed `isinstance` is preferred, use a function-local deferred import of `NormalizerPipelineParam` inside `validate_normalizer_reservation` — but the string check is simpler and cycle-free.) |
| `backend/app/api/v1/studies.py` | After the existing `SearchSpace.model_validate` (L222-226) / `validate_against_template` (L269) calls and the Phase-1 `validate_normalizer_reservation` invocation, ensure `NormalizerPipelineMisplacedError` maps to `INVALID_SEARCH_SPACE` (400). Since it subclasses `ValueError` and rides `INVALID_SEARCH_SPACE`, the existing handler at L226 may already cover it if reservation runs inside the same try — confirm the catch covers the new subclass; no new error code. |

**Endpoints**

| Method | Path | Request body | Success | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | existing study-create body; `search_space.params.query_normalizer` MAY be `{type:"normalizer_pipeline", steps:[...]}` | `201` existing study shape | `INVALID_SEARCH_SPACE` (400 — duplicate step, out-of-enum, cardinality cap, misplaced pipeline key), `NORMALIZER_PARAM_SHAPE` (400 — neither Categorical nor pipeline). **No new code.** |

**Key interfaces**
```python
# backend/app/domain/study/normalizers.py
class NormalizerPipelineMisplacedError(ValueError): ...  # → INVALID_SEARCH_SPACE
def validate_normalizer_reservation(space: SearchSpace) -> None: ...  # extended: accept pipeline under reserved key; reject elsewhere
```

**Tasks**
1. Extend `validate_normalizer_reservation` + add `NormalizerPipelineMisplacedError`; broaden `NORMALIZER_PARAM_SHAPE` message.
2. Confirm the studies router catches the new subclass → `INVALID_SEARCH_SPACE` (read studies.py:222-270 first; wire only if the existing catch doesn't already cover the `ValueError` subclass).

**DoD**
- `test_studies_normalizer_pipeline_contract.py` (contract) covers: (a) AC-12 misplaced-key → `INVALID_SEARCH_SPACE`; (b) duplicate-step → `INVALID_SEARCH_SPACE`; (c) a `query_normalizer` declared as a `FloatParam` (wrong shape) → `NORMALIZER_PARAM_SHAPE` with the broadened message naming `NormalizerPipelineParam`; (d) a valid pipeline → `201`. Asserts the canonical `error_envelope()` shape for each. This verifies the D-8 no-new-error-code contract across both the `INVALID_SEARCH_SPACE` and `NORMALIZER_PARAM_SHAPE` paths.
- `test_search_space_normalizer_pipeline.py` extended with the reserved-key-only + wrong-shape unit cases (AC-2, AC-12).

### Story 1.4 — Generalize the adapter pre-render hook to resolve pipeline labels
**Outcome:** Both `ElasticAdapter.render` and `SolrAdapter.render` apply the correct normalization for ANY winning `query_normalizer` value — a Phase 1 bundle string OR a pipeline powerset label (including non-bundle labels like `"lowercase+strip_punctuation"`) — so trial/baseline/judgment rendering never raises or no-ops on a new label. **(Closes the highest-risk gap: without this, the loop samples pipeline labels the adapter cannot apply.)**

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | In the Phase-1 pre-render hook: instead of (or in addition to) calling `normalize(query_text, value)` (which only accepts the four bundle strings), resolve `value` → step tuple via `steps_for_label(value)` and call `normalize_pipeline(query_text, steps)`. Bundle strings resolve through `_BUNDLE_TO_STEPS` (a bundle IS a label whose tokens are a subset of the bundle vocabulary), so a single `steps_for_label` → `normalize_pipeline` path serves both representations. `"none"` → empty steps → identity. Default to `"none"` when `query_normalizer` absent (Phase 1 behavior preserved). |
| `backend/app/adapters/solr.py` | Identical hook generalization at the Phase-1 hook site (`solr.py` render context construction). |

**Key interfaces** (`steps_for_label` is authored in Story 1.1 and consumed here; no new public symbol is introduced by Story 1.4)
```python
# adapter hook (both elastic.py and solr.py), pseudo:
raw = local_params.pop("query_normalizer", "none")
normalized = normalize_pipeline(query_text, steps_for_label(raw))   # bundle OR pipeline label, both resolve
context = {**local_params, "query_text": normalized}
```

**Tasks**
1. Generalize the `elastic.py` hook to `normalize_pipeline(query_text, steps_for_label(value))` (consuming `steps_for_label` authored in Story 1.1); preserve the absent→`"none"` default and the caller-dict-immutability rule (Phase 1).
2. Generalize the `solr.py` hook identically.

**DoD**
- `test_elastic_render_normalizer_pipeline.py` (unit) — render with a bundle value AND a non-bundle pipeline label (`"lowercase+strip_punctuation"`); assert the rendered `query_text` reflects `normalize_pipeline`; assert caller's `params` dict unmutated. Covers AC-3-analog for pipeline labels + I-5.
- `test_solr_render_normalizer_pipeline.py` (unit) — same shape for Solr. Covers AC-4-analog.
- `test_trial_runner_normalizer_pipeline.py` (integration) — seed a template+study with a `normalizer_pipeline` reservation, run the trial runner against the mocked-ES fixture, assert each trial's `params` records a powerset label AND each issued native query body reflects `normalize_pipeline`. Covers I-5 (the trial→adapter→normalize_pipeline end-to-end path that Story 1.4 completes). **This integration test is owned by Story 1.4** (the story that finishes the runtime surface it exercises), not Story 1.2.
- Phase 1's bundle-render tests still pass (a bundle value routes through `steps_for_label` → `_BUNDLE_TO_STEPS` → identical output).

---

## Epic 2 — PR body: bilingual snippet + parity (FR-4, FR-5)

### Story 2.1 — Label-driven Python + JS snippet generators + three-way parity
**Outcome:** The proposal PR body's "Operator-side requirement" section renders Python AND JS reference snippets for ANY winning powerset label, with a test proving runtime/Python/JS output parity.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/normalizers.py` | Add `build_python_snippet(steps) -> str` and `build_js_snippet(steps) -> str` (label/steps-driven, emit per-step lines in `STEP_ORDER`; `expand_contractions_custom`→commented no-op line; smart-quote pre-normalization in both languages' contraction path). Phase 1's four `_PR_BODY_NORMALIZER_SNIPPETS` become outputs of `build_python_snippet`. |
| `backend/workers/git_pr.py` | In `_render_pr_body_study_backed` (L540): parse `config_diff["query_normalizer"]["to"]` label → step set (via `STEP_LABEL_TOKEN` reverse map), emit the `## Operator-side requirement` section with a `### Python` block (from `build_python_snippet`) AND a `### JavaScript / TypeScript` block (from `build_js_snippet`). `"none"` → no-snippet body (Phase 1 copy). `_render_pr_body_manual` (L595) is NOT touched (I-3). |

**Key interfaces**
```python
# backend/app/domain/study/normalizers.py
def build_python_snippet(steps: Sequence[NormalizerStep]) -> str: ...  # any subset; faithful to normalize_pipeline
def build_js_snippet(steps: Sequence[NormalizerStep]) -> str: ...      # same logic in JS/TS
# steps_for_label(...) is authored in Story 1.1 (shared with Story 1.4); this story consumes it.
```

**Tasks**
1. Add `build_python_snippet` / `build_js_snippet` (consuming `steps_for_label` from Story 1.1).
2. Wire `_render_pr_body_study_backed` to emit both sub-sections; keep the `none` short-circuit.
3. Verify Phase 1's four bundle snippets are reproduced byte-for-byte by `build_python_snippet` (parametrized assertion).

**DoD**
- `test_git_pr_body_normalizer_pipeline.py` (unit) covers AC-7 (both blocks render; `none` → neither), AC-13 (non-bundle label `"lowercase+strip_punctuation"` renders both blocks, no `KeyError`).
- `test_normalizers_pr_snippets_js.py` (unit) covers AC-8 / I-2 / FR-5: three-way parity over the enumerated label set (four bundles + every single-step subset + `strip_punctuation`+`collapse_whitespace` + `expand_contractions_en`+`strip_punctuation` + an `expand_contractions_custom` label), including a `U+2019` input through the JS path. JS execution mechanism per **Open Question Q-2** (recommended: frontend vitest fixture reading a committed JSON corpus — if locked to the backend Node-subprocess path instead, this test gates on a Node binary in CI).
- Phase 1's four-bundle PR-body assertions still pass (no regression).

---

## Epic 3 — Frontend: builder row + enum + glossary + advisory + E2E (FR-6, AC-11)

### Story 3.1 — `RowNormalizerPipeline` builder row + enum mirror + glossary + advisory broadening
**Outcome:** The create-study search-space builder offers a "Normalizer pipeline" row type (ordered step multi-select), the cardinality preview counts `2^N`, the digest advisory fires on any label containing the `lowercase` token, and an empty-`steps` row blocks submission.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/search-space-builder/row-normalizer-pipeline.tsx` | `<RowNormalizerPipeline>` — ordered multi-select of `NORMALIZER_STEP_VALUES`, labels via `NORMALIZER_STEP_GLOSSARY_KEYS`, no-duplicate enforcement, "select at least one step" incomplete-state helper. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | Add `NORMALIZER_STEP_VALUES` **in `STEP_ORDER`** (spec FR-6 requires `STEP_ORDER`; this is the canonical application order, so the multi-select shows steps in the order they apply) with `// Values must match backend/app/domain/study/normalizers.py NormalizerStep (STEP_ORDER)`, and `NORMALIZER_STEP_GLOSSARY_KEYS`. |
| `ui/src/lib/glossary.ts` | Add 6 step keys + 1 row key (§8.4 / §11 tables) with the source-of-truth comment. |
| `ui/src/components/studies/search-space-builder/row-type-selector.tsx` | Add `'normalizer_pipeline'` to `TYPE_VALUES` (L40); update the source-of-truth comment to cite the backend `ParamSpec` union. |
| `ui/src/components/studies/search-space-builder/param-row.tsx` | Add a `spec?.type === 'normalizer_pipeline'` branch (near L144) rendering `<RowNormalizerPipeline>`. |
| `ui/src/components/studies/search-space-builder/stash.ts` | Add `case 'normalizer_pipeline': return { type: 'normalizer_pipeline', steps: [] }` (L66 area). |
| `ui/src/components/studies/search-space-builder/cardinality.tsx` | Add a `spec.type === 'normalizer_pipeline'` branch contributing `2 ** spec.steps.length` (L43-45 area). |
| `ui/src/components/studies/search-space-builder/types.ts` | Extend the local `ParamSpec` TS type with the `normalizer_pipeline` shape. |
| `ui/src/components/studies/search-space-builder/index.tsx` | Reuse the EXISTING submit-gating mechanism (read first) so an empty-`steps` pipeline row is counted incomplete, paralleling the categorical `__placeholder__` sentinel handling. |
| `ui/src/components/studies/digest-panel.tsx` | Broaden the Phase 1 advisory predicate from four-bundle membership to `label !== "none" && label.split("+").includes("lowercase")`; Solr-hidden + analyzer-overlap conjuncts unchanged (Phase 1 FR-6). |

**UI element inventory (creation)**
- `<RowNormalizerPipeline>`: a row mirroring `<RowCategorical>` layout — param-name field (inherited from `<ParamRow>`), an ordered multi-select of the six steps (checkboxes or a chip multi-select), per-step label via glossary, inline "Select at least one step" helper when `steps.length === 0`. Data source: the row's `spec.steps`. Interactions: toggle a step → update `spec.steps` (preserve `STEP_ORDER`); duplicate selection impossible by construction (toggle, not add).

**State dependency analysis**
- `row-type-selector` `TYPE_VALUES` is consumed by `param-row` dispatch and `stash` default factory — adding `'normalizer_pipeline'` requires the matching `param-row` branch + `stash` case + `cardinality` branch in the same story (all listed above), or the live preview under-counts and the row won't render.

**Tasks**
1. Add `NORMALIZER_STEP_VALUES` + `NORMALIZER_STEP_GLOSSARY_KEYS` to `enums.ts`; 7 glossary keys to `glossary.ts`.
2. Add `'normalizer_pipeline'` to `row-type-selector` `TYPE_VALUES`; build `<RowNormalizerPipeline>`; wire `param-row` dispatch + `stash` default + `cardinality` branch + `types.ts`.
3. Read `index.tsx` submit-gating, apply the same incomplete-row treatment to empty-`steps` pipeline rows.
4. Broaden the `digest-panel.tsx` advisory predicate.

**DoD**
- `row-normalizer-pipeline.test.tsx` (vitest) covers AC-9: (a) options `.map()`-sourced from `NORMALIZER_STEP_VALUES` (passes `form-select-discipline`); (b) `[lowercase,trim]` → submitted spec `{type:"normalizer_pipeline",steps:["lowercase","trim"]}`; (c) cardinality preview reads `4`; (d) empty-`steps` row flagged incomplete + not submittable.
- `digest-panel.normalizer-advisory.test.tsx` (vitest, extend Phase 1's) covers AC-13: advisory fires for `"lowercase+strip_punctuation"`, NOT for `"strip_punctuation"`.
- `form-select-discipline.test.tsx` extended so `NORMALIZER_STEP_VALUES` is recognized as a `.map()` source.
- `glossary.test.ts` length/no-jargon lint green for the 7 new keys.
- ESLint + tsc + Next build green.

### Story 3.2 — Real-backend E2E
**Outcome:** A Playwright spec drives a typed-pipeline study end-to-end against the live stack.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/query-normalizer-pipeline.spec.ts` | Real-backend E2E covering AC-11. |

**Modified files:** none (or extend Phase 1's `query-normalization.spec.ts` if it exists at execution time — check first).

**Tasks**
1. Setup via API helpers: register ES cluster, create a template declaring `query_normalizer`, create query set, generate judgments (mock LLM per existing E2E fixture pattern).
2. Via `page`: open create-study modal, add a row, switch type to "Normalizer pipeline", select `[lowercase, trim, expand_contractions_en]`, submit.
3. Wait for ≥4 trials; assert the trials table shows the chosen powerset labels; open the digest; open the proposal PR preview; assert `## Operator-side requirement` + `### Python` + `### JavaScript / TypeScript` blocks.

**DoD**
- E2E passes against the real backend (no `page.route()` mocking; assertions via `page`).
- AC-11 satisfied.

---

## Epic 4 — Documentation (FR-9)

### Story 4.1 — Docs sweep
**Outcome:** Architecture + runbook docs reflect the typed pipeline.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/optimization.md` | Paragraph: powerset sampling, canonical `STEP_ORDER` vs Phase-1-compatible `LABEL_ORDER`, bundle-desugar equivalence. |
| `docs/01_architecture/adapters.md` | Note the pre-render hook accepts a bundle string OR a pipeline label under the `query_normalizer` key. |
| `docs/03_runbooks/local-dev.md` | Add a `normalizer_pipeline` `declared_params` + `search_space.params` example diff. |
| `state.md` / `state_history.md` | Merge one-liner (newest-first) + narrative (at finalization). |

**Tasks**
1. Patch the three architecture/runbook docs.
2. Add the `state.md` one-liner at finalization.

**DoD**
- Docs consistent with shipped behavior; no `docs/04_security/llm-data-flow.md` change (no LLM call — FR-9).
- If a `test_docs_*` unit guard exists for these doc sections, it passes.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/domain/study/` + `backend/tests/unit/workers/`)
- [ ] `test_normalizers_pipeline.py` — AC-1, AC-6, I-1, whitespace-interaction (Story 1.1)
- [ ] `test_normalizers_bundle_compat.py` — AC-5 / I-3 (Story 1.1)
- [ ] `test_search_space_normalizer_pipeline.py` — AC-2, AC-3, AC-4, AC-12 unit cases (Stories 1.2, 1.3)
- [ ] `test_template_defaults_normalizer_pipeline.py` — AC-10 (Story 1.2)
- [ ] `test_git_pr_body_normalizer_pipeline.py` — AC-7, AC-13 (Story 2.1)
- [ ] `test_normalizers_pr_snippets_js.py` — AC-8 / I-2 / FR-5 three-way parity (Story 2.1)
- [ ] `test_elastic_render_normalizer_pipeline.py` — bundle + non-bundle label render + caller-dict immutability (Story 1.4)
- [ ] `test_solr_render_normalizer_pipeline.py` — same for Solr (Story 1.4)
- DoD: critical branches deterministic; domain modules import-pure; no module-level cycle between `normalizers.py` and `search_space.py` (discriminator-string check in `validate_normalizer_reservation`).

### 3.2 Integration tests (`backend/tests/integration/workers/`)
- [ ] `test_trial_runner_normalizer_pipeline.py` — seed template+study with a `normalizer_pipeline` reservation, run the trial runner against the mocked-ES fixture, assert each trial's `params` records a powerset label and each native query body reflects `normalize_pipeline`; covers I-5. **Owned by Story 1.4's DoD** (the story that completes the trial→adapter→normalize_pipeline runtime path it exercises).
- DoD: happy path + a bad-trial-render path covered.

### 3.3 Contract tests (`backend/tests/contract/`)
- [ ] `test_studies_normalizer_pipeline_contract.py` — duplicate-step → `INVALID_SEARCH_SPACE`; misplaced-key (AC-12) → `INVALID_SEARCH_SPACE`; asserts `error_envelope()` shape (Story 1.3)
- DoD: every failure path rides an existing, asserted code (no new code per D-8).

### 3.4 E2E tests (`ui/tests/e2e/`)
- [ ] `query-normalizer-pipeline.spec.ts` — AC-11, real-backend, `page`-driven (Story 3.2)
- DoD: stable pass; browser-visible assertions only.

### 3.5 Frontend vitest (`ui/src/__tests__/`)
- [ ] `row-normalizer-pipeline.test.tsx` — AC-9 (Story 3.1)
- [ ] `digest-panel.normalizer-advisory.test.tsx` (extend Phase 1's) — AC-13 (Story 3.1)
- [ ] `form-select-discipline.test.tsx` (extend) — `NORMALIZER_STEP_VALUES` `.map()` recognition (Story 3.1)
- [ ] `glossary.test.ts` (extend) — 7 new keys length/no-jargon (Story 3.1)

### 3.5b Existing test impact audit
| Test file | Pattern | Count | Action |
|---|---|---|---|
| Phase 1's `test_normalizers*.py` | `normalize` / bundle assertions | TBD at exec | No change if `normalize` reimplemented over `normalize_pipeline` preserves byte-output (Story 1.1 verifies); else augment. |
| Phase 1's `test_search_space*.py` | `ParamSpec` discriminator | existing | Augment — add the 4th-member cases (Story 1.2); existing Float/Int/Categorical cases unaffected. |
| Phase 1's `test_git_pr_body_normalizer.py` | PR-body Python-only assertions | existing | Augment for the JS block; ensure the Python block still asserts (Story 2.1). |
| Phase 1's `query-normalization.spec.ts` | normalizer E2E | existing | Extend or add sibling spec (Story 3.2) — confirm presence at exec. |

### 3.6 Migration verification
- N/A — no schema change. Alembic head stays `0022_solr_engine_auth_check`.

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` (+ `pnpm lint && pnpm typecheck && pnpm build`)
- [ ] E2E: `query-normalizer-pipeline.spec.ts` in the smoke E2E job

---

## 4) Documentation update workstream

### 4.0 Core context files
- [ ] `state.md` — merge one-liner (Alembic head unchanged; no new branch debt beyond the Phase-1 gate).
- [ ] `architecture.md` — no new layer (extends existing domain module + adapter hook + builder); update only if a new critical flow warrants. Likely no change.
- [ ] `CLAUDE.md` — no new convention (reuses existing enum-discipline + adapter-confined rules). Likely no change.

### 4.1 Architecture docs
- [ ] `docs/01_architecture/optimization.md`, `adapters.md` (Story 4.1).

### 4.2–4.5
- [ ] `docs/03_runbooks/local-dev.md` (Story 4.1). No product/security/quality doc change (FR-9: `llm-data-flow.md` MUST NOT change).

**Documentation DoD:** docs consistent with shipped behavior; `local-dev.md` diff dry-run-validated.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Eliminate duplicate normalization logic by reimplementing Phase 1's `normalize(text, bundle)` over `normalize_pipeline` (D-6) — single execution engine for bundle + pipeline paths.

### 5.2 Planned refactor tasks
- [ ] (Story 1.1) `normalize` → `normalize_pipeline(_BUNDLE_TO_STEPS[bundle])` wrapper, IF byte-parity (I-3) holds; otherwise keep separate and lean on the parity test.

### 5.3 Guardrails
- [ ] Phase 1 AC-1 byte-output parity proven by `test_normalizers_bundle_compat.py`.
- [ ] No product-scope expansion.
- [ ] `mypy --strict` + ESLint/tsc green.

---

## 6) Dependencies, risks, and mitigations

### Dependencies
| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Phase 1 (`feat_query_normalization_tuning`) merged | Story 0 (all stories) | **NOT merged — plan stage** | **Total blocker** — Story 0 aborts the run. |
| LIVE `ParamSpec` / `estimate_cardinality` / `apply_search_space` (`search_space.py`) | Story 1.2 | implemented (verified) | none |
| LIVE builder (`row-type-selector`/`param-row`/`stash`/`cardinality`) | Story 3.1 | implemented (verified) | none |

### Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 1's final symbol names drift from this plan's assumptions | M | M | Story 0 asserts the exact symbol set; if names changed, the gate fails loudly and the plan is patched before execution. |
| Label/application order conflated → Phase 1 byte-compat break | M | H | Two explicit orderings (`STEP_ORDER` vs `LABEL_ORDER`, D-12) + `test_normalizers_bundle_compat.py` byte-parity gate. |
| JS-snippet test infra (Q-2) adds a Node dependency to the backend suite | M | M | Recommended default: frontend vitest fixture over a committed JSON corpus — keeps each runtime in its own suite. Locked at plan-finalization. |
| Cardinality under-count if `estimate_cardinality` branch omitted | L | M | Story 1.2 DoD asserts AC-3 (cap trips); spec anti-pattern called out. |

### Failure mode catalog
| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Trial-time invalid `query_normalizer` value | direct DB mutation (out of threat scope) | `normalize_pipeline`/`normalize` raises `ValueError`; adapter wraps; single trial fails per existing render-failure path | study continues with remaining trials |
| Empty-`steps` pipeline row submitted | frontend gating bypassed | backend `min_length=1` → `INVALID_SEARCH_SPACE` (400) | operator fixes the row |
| Pipeline under non-reserved key | operator/agent declares it elsewhere | `validate_normalizer_reservation` → `INVALID_SEARCH_SPACE` (400) | operator moves it to `query_normalizer` |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 0 (gate).
2. Epic 1 (1.1 → 1.2 → 1.3 → 1.4) — domain core, then validator, then the adapter-hook generalization (1.4 depends on 1.1's `steps_for_label` + `normalize_pipeline`).
3. Epic 2 (2.1) — PR body (depends on 1.1's `steps_for_label` + label/step helpers).
4. Epic 3 (3.1 → 3.2) — frontend (depends on 1.2's wire shape + 1.1's step values).
5. Epic 4 (4.1) — docs.

### Parallelization
- Epic 2 (PR body) and Epic 3 Story 3.1 (frontend) can proceed in parallel once Epic 1 is done — they touch disjoint files.
- Epic 4 docs can be drafted any time after Epic 1.

## 8) Rollout and cutover plan
- No feature flag — gated by template adoption (operator declares a `normalizer_pipeline` param).
- No migration, no backfill.
- Backward-compatible with Phase 1: bundle declarations keep working (desugar + label superset).

## 9) Execution tracker

### Current sprint
- [ ] Story 0 — Phase-1-merged gate (BLOCKED until Phase 1 merges)

### Blocked items
- All stories — blocker: Phase 1 (`feat_query_normalization_tuning`) unmerged — owner: pipeline (Phase 1 ships first).

### Done this sprint
- (none — design-ahead)

## 10) Story-by-Story Verification Gate
Per template §10 — each story attaches: files match scope, contract implemented as documented (no new error code — assert `INVALID_SEARCH_SPACE`/`NORMALIZER_PARAM_SHAPE`), key interfaces match, four-layer tests where applicable, commands run + passed, no migration round-trip needed (no schema change), docs updated in the same PR when behavior changed.

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** Spec §8.1 affected-endpoint count = 5 (studies POST, studies GET, digest GET, proposals GET, query-templates POST). Plan adds API surface only at `POST /api/v1/studies` (Story 1.3); the other four are read-shape/unchanged (no new endpoint). **No new endpoints** — consistent.
2. **Spec ↔ plan error-code coverage:** Spec introduces NO new code (D-8). Plan's contract test (Story 1.3 / §3.3) asserts the existing `INVALID_SEARCH_SPACE` for duplicate-step + misplaced-key, and `NORMALIZER_PARAM_SHAPE` for wrong shape. Consistent.
3. **Spec ↔ plan FR coverage:** All 9 FRs mapped in §1; each assigned to ≥1 story. AC-11 (E2E) assigned to Story 3.2.
4. **Story internal consistency:** No file is owned (created) by two stories — only `row-normalizer-pipeline.tsx` and `query-normalizer-pipeline.spec.ts` are NEW (Story 3.1 / 3.2 respectively); all other touches are modifications of LIVE or Phase-1 files. Modified files verified to exist (LIVE) or are Phase-1-shipped (gated by Story 0).
5. **Test file assignment:** 8 unit (`test_normalizers_pipeline`, `test_normalizers_bundle_compat`, `test_search_space_normalizer_pipeline`, `test_template_defaults_normalizer_pipeline`, `test_git_pr_body_normalizer_pipeline`, `test_normalizers_pr_snippets_js`, `test_elastic_render_normalizer_pipeline`, `test_solr_render_normalizer_pipeline`) + 1 integration + 1 contract + 1 E2E + 4 frontend vitest, each assigned to exactly one story's DoD — the two adapter render tests AND `test_trial_runner_normalizer_pipeline.py` (integration) are all owned by Story 1.4 (the story that completes the runtime path they exercise).
6. **Gate arithmetic:** No "N endpoints live" gate (no new endpoints). Story 0 is the only hard gate.
7. **Open questions:** Q-1 (inert `expand_contractions_custom`) and Q-2 (JS-test infra) remain as genuine forks with recommended defaults — both MUST be locked at plan-finalization before `/impl-execute`. Q-3 was locked to D-8. **Flagged for the user (see below).**
8. **Frontend UI Guidance:** present (§UI Guidance below) — insertion points, analogous markup (RowCategorical), layout, interaction, glossary keys + source-of-truth comment, no legacy-delete (>100 LOC) so no parity table required.
9. **Frontend data plumbing:** the advisory broadening (Story 3.1) reuses the schema/cluster props Phase 1's FR-6 already plumbs into `<DigestPanel>` — no new data fetch (gated by Story 0; confirm at exec).
10. **Enumerated value contract audit:** §8.4 cites `NormalizerStep` (`StrEnum`) and `NormalizerPipelineParam.type` `Literal` as backend source; frontend `NORMALIZER_STEP_VALUES` mirrors with the `// Values must match backend/...` comment + `.map()` discipline (Story 3.1). The six step wire values match the enum character-for-character.
11. **Audit-event coverage:** N/A — no new mutation site (rides existing study-create/trial/PR paths; `audit_log` lands MVP3).

### Legacy behavior parity
No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. `<RowNormalizerPipeline>` is a NEW additive row; `digest-panel.tsx` gets a one-line predicate broadening (not a rewrite).

---

## UI Guidance

### Reference: current component structure
- `ui/src/components/studies/search-space-builder/param-row.tsx` — dispatches on `spec?.type` (float/int at L116-139, categorical at L144-145). Insertion: add a `normalizer_pipeline` branch adjacent to the categorical branch (~L144).
- `row-type-selector.tsx` — `TYPE_VALUES = ['float','int','categorical']` at L40. Add `'normalizer_pipeline'`.
- `stash.ts` — default-spec factory L61-66; add `case 'normalizer_pipeline'`.
- `cardinality.tsx` — type-switch at L43-45; add the `2 ** steps.length` branch.
- `digest-panel.tsx` — Phase 1's advisory predicate (line TBD at exec; Phase 1 FR-6 lands it above the `recommended_config` `<pre>` block).

### Analogous markup pattern (copy `<RowCategorical>`)
`<RowNormalizerPipeline>` should mirror `row-categorical.tsx`'s row chrome (param-name field + the choice editor area), substituting an ordered six-step multi-select for the free-text choices list. At execution, read `row-categorical.tsx` in full and copy its wrapper JSX + class names; replace the choices editor with a step toggle list whose labels come from `glossaryFor(NORMALIZER_STEP_GLOSSARY_KEYS[step])`.

### Layout and structure
- The row sits in the existing `<SearchSpaceBuilder>` parameter list, no elevation. The step multi-select renders only when the row type is `normalizer_pipeline`.

### Interaction behavior
| User action | Frontend behavior | API call |
|---|---|---|
| Switch row type to "Normalizer pipeline" | `stash` returns `{type:"normalizer_pipeline", steps:[]}`; row renders empty multi-select + "select at least one step" helper; row counted incomplete (submit disabled) | none |
| Toggle a step | update `spec.steps` (no duplicates by construction); cardinality preview recomputes `2^N` | none |
| Submit study | builder serializes the row into `search_space.params.query_normalizer` | `POST /api/v1/studies` |

### Tooltips and contextual help
Per spec §11 — 7 NEW glossary keys (`search_space.normalizer_pipeline.row` + 6 `search_space.normalizer_step.*`). Source-of-truth comment in `enums.ts`: `// Values must match backend/app/domain/study/normalizers.py NormalizerStep`. Tooltip markup follows the existing builder-row info-icon pattern (read `row-categorical.tsx` for the exact primitive).

### Visual consistency
| New element | Pattern source |
|---|---|
| `<RowNormalizerPipeline>` chrome | `row-categorical.tsx` |
| Step multi-select labels | `glossary.ts` via `NORMALIZER_STEP_GLOSSARY_KEYS` |
| Cardinality preview | existing `cardinality.tsx` text |
| Advisory line | Phase 1's `digest-panel.tsx` advisory (predicate broadened only) |

---

## 12) Definition of plan done

- [ ] Every FR (1–9) mapped to stories/tests/docs (§1). ✓
- [ ] Every story includes New/Modified files, Tasks, DoD (backend stories add Endpoints/Interfaces where API-facing). ✓
- [ ] Test layers (unit/integration/contract/e2e/vitest) scoped (§3). ✓
- [ ] Docs updates planned (§4, Story 4.1). ✓
- [ ] Lean refactor scope explicit (§5 — `normalize` wrapper). ✓
- [ ] Story 0 precondition gate is the hard stop; no endpoint gates needed. ✓
- [ ] Verification gate included (§10). ✓
- [ ] Plan consistency review performed (§11). ✓
- [x] **BLOCKER CLEARED (2026-06-09):** Open Questions Q-1 (include `expand_contractions_custom` inert — 6 steps) + Q-2 (frontend vitest fixture) locked; Phase 1 (`feat_query_normalization_tuning`) merged (PR #459).
