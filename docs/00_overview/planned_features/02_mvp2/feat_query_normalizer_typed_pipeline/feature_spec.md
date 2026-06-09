# Feature Specification — Typed normalizer pipeline (ordered step list) + JS snippet + smart-quote contractions

**Date:** 2026-06-01
**Status:** Ready for Execution — Phase 1 (`feat_query_normalization_tuning`) merged (PR #459); Q-1 locked **include `expand_contractions_custom` as inert (6 steps)**, Q-2 locked **frontend vitest fixture** (2026-06-09).
**Owners:** Product — soundminds.ai · Engineering — RelyLoop core
**Related docs:**
- [`idea.md`](idea.md)
- **Phase 1 foundation:** [`feat_query_normalization_tuning/feature_spec.md`](../feat_query_normalization_tuning/feature_spec.md) — §3 "Phase boundaries", §19 D-4 (search-space shape), D-6 (snippet language), D-7 (smart-quote handling). **This spec extends Phase 1 and reuses every symbol Phase 1 defines.**
- Sibling Phase 3: [`feat_apply_path_normalizer_declaration/idea.md`](../feat_apply_path_normalizer_declaration/idea.md)
- [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) (Optuna sampler / search-space)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (SearchAdapter Protocol + pre-render hook contract added by Phase 1)
- [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) (Git-PR posture)

---

> ## ⚠️ DESIGN-AHEAD GATE — read before `/impl-execute`
>
> **Phase 1 (`feat_query_normalization_tuning`) is UNMERGED — still at the plan stage** (verified 2026-06-01). The following symbols this spec extends **do not yet exist in the tree**; they are *defined by Phase 1's spec*, not by shipped code:
>
> - `backend/app/domain/study/normalizers.py` (the whole module)
> - `NORMALIZER_CHOICES`, `DEFAULT_NORMALIZER`, `normalize(...)`, `validate_normalizer_reservation(...)`, `_CONTRACTIONS`, `_PR_BODY_NORMALIZER_SNIPPETS`
> - the `ElasticAdapter.render` / `SolrAdapter.render` pre-render hook
> - `_RESERVED_NONRENDER_PARAMS` in `template_validator.py`
> - the frontend `NORMALIZER_VALUES` / `NORMALIZER_GLOSSARY_KEYS` in `ui/src/lib/enums.ts`
> - the digest advisory + the `query_normalizer` Categorical row in `row-categorical.tsx`
>
> **`/impl-execute` against this plan MUST NOT begin until Phase 1 has merged to `main`.** The first story of the implementation plan is a hard precondition check (`backend/app/domain/study/normalizers.py` exists AND exports `NORMALIZER_CHOICES`). The symbols that DO exist today and that Phase 2 also extends — `ParamSpec`, `estimate_cardinality`, `apply_search_space`, the search-space-builder row dispatch — are cited with live `file:line` references and were verified against the current tree.

---

## 1) Purpose

- **Problem:** Phase 1 ships query normalization as a single reserved Categorical param (`query_normalizer`) with **exactly four hard-coded bundles** (`none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions`), an English-only ASCII-apostrophe contraction dictionary, and a Python-only PR-body reference snippet. Three follow-on capabilities are deferred in Phase 1's decision log until operator signal motivates them: operators cannot compose **arbitrary ordered step sequences** (e.g., `[trim, lowercase, expand_contractions]` without the bundles' fixed nesting); operators with Node/Bun query layers must hand-translate the Python snippet (D-6); and queries carrying the Unicode right-single-quote `U+2019` (`’`) miss contraction expansion that ASCII `U+0027` (`'`) queries get (D-7).
- **Outcome:** A new typed search-space member `NormalizerPipelineParam` lets a template declare an **ordered list of normalization steps**; the Optuna loop samples over the powerset of declared steps and proposes the winning sequence. The four Phase 1 bundles become **desugar aliases** the validator expands into step sequences, so Phase 1's wire contract continues to validate unchanged. The PR body offers **both a Python and a JS/TypeScript** reference snippet for the winning sequence, and the contraction matcher expands **both** ASCII and smart-quote apostrophes.
- **Non-goal (preserved):** Analyzer / index-mapping changes remain a permanent non-goal (umbrella spec §4). This feature touches only the query string before it reaches the engine. No cluster write, no schema change, no new LLM call, no new external dependency.

## 2) Current state audit

> **Audit framing:** Symbols marked **(Phase 1 — not yet in tree)** are defined by Phase 1's spec; their `file:line` references point at where Phase 1 *will* land them and are NOT verifiable against the current tree. Symbols marked **(LIVE)** were grepped/read against the current tree on 2026-06-01 and the cited lines are accurate today.

### Existing implementations

| File / symbol | What it does | Notes (relevant to this feature) |
|---|---|---|
| **(LIVE)** [`backend/app/domain/study/search_space.py:87-90`](../../../../../backend/app/domain/study/search_space.py) (`ParamSpec`) | `Annotated[FloatParam \| IntParam \| CategoricalParam, Field(discriminator="type")]`. | This feature adds a fourth member, `NormalizerPipelineParam`, to this union. Discriminator key is `type`; the new member's `type` literal is `"normalizer_pipeline"`. |
| **(LIVE)** [`backend/app/domain/study/search_space.py:74-84`](../../../../../backend/app/domain/study/search_space.py) (`CategoricalParam`) | `type: Literal["categorical"]`, `choices: list[str\|int\|float\|bool]` (min_length 1), `extra="forbid"`. | The Phase 1 `query_normalizer` reservation rides on this. Phase 2 keeps it working unchanged — `NormalizerPipelineParam` is an *additional* way to express normalizer tuning, not a replacement. |
| **(LIVE)** [`backend/app/domain/study/search_space.py:181-200`](../../../../../backend/app/domain/study/search_space.py) (`estimate_cardinality`) | Product of per-param cardinalities: Float→100, Int→`high-low+1`, Categorical→`len(choices)`. `isinstance` chain. | **MUST** gain a `NormalizerPipelineParam` branch contributing `2**len(steps)` (powerset). Without it, the new type contributes the default `1` and the 10^6 cap (`_check_cardinality`, L114-122) is silently under-counted. |
| **(LIVE)** [`backend/app/domain/study/search_space.py:249-270`](../../../../../backend/app/domain/study/search_space.py) (`apply_search_space`) | `isinstance` dispatch to `trial.suggest_float/int/categorical`. | **MUST** gain a `NormalizerPipelineParam` branch: `trial.suggest_categorical(name, _powerset_labels(steps))` where each label is a canonical serialization of an ordered step subset (see FR-2). The suggested value is the canonical label string, recorded in `trials.params` like any categorical. |
| **(LIVE)** [`backend/app/domain/study/search_space.py:114-122`](../../../../../backend/app/domain/study/search_space.py) (`SearchSpace._check_cardinality`) | Rejects spaces with estimate > 1_000_000. | No change needed beyond the `estimate_cardinality` branch above — the cap fires automatically once the powerset is counted. |
| **(Phase 1 — not yet in tree)** `backend/app/domain/study/normalizers.py` (`NORMALIZER_CHOICES`, `normalize`, `_CONTRACTIONS`, `_PATTERN`, `_PR_BODY_NORMALIZER_SNIPPETS`, `validate_normalizer_reservation`) | Phase 1's pure-domain normalizer library. | Phase 2 adds: `NormalizerStep` enum, `STEP_ORDER`, `normalize_pipeline(query_text, steps)`, smart-quote handling inside the contraction path, a JS snippet generator, and the bundle→step-sequence desugar map. The four Phase 1 bundles MUST remain importable + behavior-identical. |
| **(LIVE)** [`backend/app/domain/study/template_defaults.py:59-115`](../../../../../backend/app/domain/study/template_defaults.py) (`compute_default_params`) | Picks single concrete default values per declared param (Float→midpoint, Int→midpoint, Categorical→first value). Phase 1 extends it so `"query_normalizer"` → `DEFAULT_NORMALIZER`. | Phase 2 **MUST** extend it again: a declared param of type `normalizer_pipeline` defaults to the **empty step list** (canonical label for "apply no steps" — semantically identical to Phase 1's `"none"`). |
| **(LIVE)** [`backend/app/domain/study/template_validator.py`](../../../../../backend/app/domain/study/template_validator.py) (`validate_template_body`, `_RESERVED_NONRENDER_PARAMS` added by Phase 1) | Validates Jinja body references against declared params; Phase 1 adds the reserved-nonrender exemption + the `ReservedParamReferenced` rejection. | Phase 2 reuses Phase 1's `_RESERVED_NONRENDER_PARAMS` mechanism unchanged — a `normalizer_pipeline` param is consumed by the adapter, never referenced in the body, so it must also be in the reserved-nonrender set. |
| **(Phase 1 — not yet in tree)** `ElasticAdapter.render` / `SolrAdapter.render` pre-render hook | Phase 1's hook pops `query_normalizer`, applies `normalize(query_text, choice)`, injects the normalized string. | Phase 2 generalizes the hook: when the reserved param value is a pipeline label (vs. a bundle string), apply `normalize_pipeline(query_text, steps)`. The hook reads the **same reserved key name** (`query_normalizer`); a single key serves both representations — the value's shape (bundle string vs. pipeline label) selects the code path. |
| **(Phase 1 — not yet in tree)** `_render_pr_body_study_backed` "Operator-side requirement" section | Phase 1 emits Python snippet only. | Phase 2 emits BOTH Python and JS snippets under the same section. |
| **(LIVE)** [`ui/src/components/studies/search-space-builder/row-type-selector.tsx:40`](../../../../../ui/src/components/studies/search-space-builder/row-type-selector.tsx) (`TYPE_VALUES = ['float', 'int', 'categorical']`) | The param-type dropdown options in the create-study builder. | Phase 2 adds `'normalizer_pipeline'` to this list, with the source-of-truth comment updated. |
| **(LIVE)** [`ui/src/components/studies/search-space-builder/param-row.tsx:116-145`](../../../../../ui/src/components/studies/search-space-builder/param-row.tsx) (row dispatch) | Renders `RowNumeric` / `RowCategorical` based on `spec.type`. | Phase 2 adds a `spec?.type === 'normalizer_pipeline'` branch rendering a new `RowNormalizerPipeline` (a multi-select ordered step picker). |
| **(LIVE)** [`ui/src/components/studies/search-space-builder/stash.ts:61-66`](../../../../../ui/src/components/studies/search-space-builder/stash.ts) (default-spec factory) | Returns a default spec per type when the operator switches a row's type. | Phase 2 adds `case 'normalizer_pipeline': return { type: 'normalizer_pipeline', steps: [] }`. |
| **(LIVE)** [`ui/src/components/studies/search-space-builder/cardinality.tsx:43-45`](../../../../../ui/src/components/studies/search-space-builder/cardinality.tsx) (frontend cardinality preview) | Mirrors `estimate_cardinality` for the live builder preview. | Phase 2 adds a `normalizer_pipeline` branch contributing `2 ** steps.length` so the preview matches the backend cap. |
| **(LIVE)** [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) | Canonical wire-value allowlists (Phase 1 adds `NORMALIZER_VALUES` + `NORMALIZER_GLOSSARY_KEYS`). | Phase 2 adds `NORMALIZER_STEP_VALUES` (ordered) + `NORMALIZER_STEP_GLOSSARY_KEYS` with the source-of-truth comment pointing at the backend `NormalizerStep` enum. |
| **(LIVE)** [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) | Source-of-truth for tooltip copy. | Phase 2 adds one key per `NormalizerStep` value + one row-level key for the pipeline row. |

**Why this matters:** The typed pipeline touches **three live backend dispatch sites** (`ParamSpec` union, `estimate_cardinality`, `apply_search_space`) that already have a clean `isinstance`/discriminator pattern — adding a fourth member is mechanical and well-bounded. The **frontend builder** has a parallel five-site dispatch (`row-type-selector`, `param-row`, `stash`, `cardinality`, plus the new row component). The Phase-1-defined surfaces (normalizer library, adapter hook, PR body) extend cleanly but **cannot be implemented until Phase 1 lands them**.

### Navigation and link impact

No URL changes. The feature extends the existing create-study modal's search-space builder, the existing study-detail digest panel, and the existing proposal-detail PR body. No page moved, renamed, or removed.

| Source file | Current link target | New link target |
|---|---|---|
| _none_ | _none_ | _none_ |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| **(LIVE)** [`backend/tests/unit/domain/study/test_search_space.py`](../../../../../backend/tests/unit/domain/study/test_search_space.py) | `ParamSpec` discriminator + `estimate_cardinality` + `apply_search_space` assertions | augment | Add cases: (a) `NormalizerPipelineParam` parses via the discriminator; (b) `estimate_cardinality` counts `2**len(steps)`; (c) a pipeline whose powerset × other params > 10^6 raises the cardinality error. |
| **(Phase 1 — not yet in tree)** `backend/tests/unit/domain/study/test_normalizers.py` | Phase 1's `normalize` over the choice × input matrix | augment | Add `normalize_pipeline` cases over ordered step subsets + smart-quote-bearing inputs. |
| **(Phase 1 — not yet in tree)** `backend/tests/unit/adapters/test_elastic_render_normalizer.py` / Solr equivalent | Phase 1's adapter hook render assertions | augment | Add a case where the reserved value is a pipeline label → `query_text` reflects `normalize_pipeline`. |
| **(Phase 1 — not yet in tree)** `backend/tests/unit/workers/test_git_pr_body_normalizer.py` | Phase 1's PR-body assertions | augment | Add an assertion that the JS snippet block renders alongside the Python block. |
| **(LIVE)** `ui/src/__tests__/components/studies/search-space-builder/*.test.tsx` (Phase 1 adds `row-categorical.normalizer-source-of-truth.test.tsx`) | Builder row dispatch + enum-discipline assertions | augment + new | New `row-normalizer-pipeline.test.tsx`; extend the `form-select-discipline` guard so `NORMALIZER_STEP_VALUES` is sourced via `.map()`. |
| **(LIVE)** `ui/tests/e2e/query-normalization.spec.ts` (Phase 1) | Real-backend normalizer E2E | augment | Extend (or add a sibling spec) to drive a `normalizer_pipeline` row through study creation → digest → PR body assertion. |

### Existing behaviors affected by scope change

- **`adapter.render(...)` pre-render hook (Phase 1):** Current (Phase 1) — pops `query_normalizer`, applies `normalize(query_text, bundle_string)`. New — when the value is a **pipeline label** (canonical step-subset serialization), applies `normalize_pipeline(query_text, steps)` instead. **Decision needed:** No — gated on the value's shape; bundle strings continue to route to `normalize`. See D-2 below for the single-key vs. two-key fork (locked: single key).
- **`estimate_cardinality` (LIVE):** Current — three `isinstance` branches. New — a fourth branch counting `2**len(steps)`. **Decision needed:** No — additive, mirrors existing pattern.
- **`apply_search_space` (LIVE):** Current — three `suggest_*` branches. New — a fourth branch suggesting over the powerset-label list. **Decision needed:** No.
- **PR body (Phase 1):** Current — Python snippet only. New — Python + JS. **Decision needed:** No — additive (D-6 unlocked by this phase).
- **Contraction matcher (Phase 1):** Current — ASCII `'` only. New — ASCII `'` AND smart `’`. **Decision needed:** No — additive; Phase 1 inputs continue to pass (D-7 unlocked). See D-3 for the pre-normalize-vs-extend-pattern fork (locked: pre-normalize).

---

## 3) Scope

### In scope

- **Capability A — Typed `NormalizerPipelineParam`:** A new discriminated-union member of `ParamSpec` (`type: Literal["normalizer_pipeline"]`, `steps: list[NormalizerStep]`), a `NormalizerStep` `StrEnum` (the six step values in §8.4), backend cardinality + sampler integration, the bundle→step-sequence desugar map (so Phase 1's four bundles remain valid wire input), `compute_default_params` extension (empty step list default), and the frontend builder row + dispatch + enum mirror + glossary keys.
- **Capability B — JS/TypeScript PR-body snippet:** Extend Phase 1's `_PR_BODY_NORMALIZER_SNIPPETS` (or add a parallel `_PR_BODY_NORMALIZER_SNIPPETS_JS`) so the "Operator-side requirement" section emits both languages. A semantic-equivalence test asserts the JS snippet's output matches the Python snippet's output over Phase 1's AC-12 fixture corpus (the curated 10-element corpus defined in Phase 1 spec AC-12).
- **Capability C — Smart-quote contraction matching:** Pre-normalize `U+2019` (`’`) to ASCII `U+0027` (`'`) inside the contraction code path **before** the contraction regex runs (the additive, lower-risk option from idea Capability C). Phase 1's existing inputs continue to expand identically; new `’`-bearing inputs now expand.
- A pure-domain `normalize_pipeline(query_text: str, steps: Sequence[NormalizerStep]) -> str` that applies steps **in a canonical order** (not declaration order — see FR-2 ordering rule), reusing Phase 1's `_CONTRACTIONS` / `_PATTERN` for the contraction step.
- Documentation: extend Phase 1's `optimization.md` / `adapters.md` / `local-dev.md` updates with the typed-pipeline shape; add a runbook paragraph showing the `normalizer_pipeline` `declared_params` + `search_space.params` diff.

### Out of scope

- **Capability D — Operator-supplied / runtime-loaded contraction dictionaries** (cluster- or template-level custom dictionaries). Recommended **scoped OUT** of this phase (see §19 D-5); revisit as a Phase 2.5 sub-phase only if operator signal proves it.
- Locale variants of the contraction dictionary, spell correction, stemming, stopword removal, synonym expansion. (Same as Phase 1 — permanent non-goals for the normalizer surface.)
- Apply-path-side structured normalizer declaration — that is Phase 3 (`feat_apply_path_normalizer_declaration`).
- Any migration. The `NormalizerPipelineParam` rides inside the existing `studies.search_space` / `trials.params` / `digests.recommended_config` / `proposals.config_diff` JSONB columns; the JSONB shape is forward-compatible.
- Removing or deprecating the Phase 1 four-bundle Categorical representation. Both coexist; bundles become desugar aliases.
- Changing the `SearchAdapter` Protocol signature.
- Any LLM call, cluster write, or external dependency.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints; unprefixed for operator/webhook endpoints — per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md).
- **Router namespace for this feature's endpoints:** **None — no new endpoints.** The feature rides the existing `POST /api/v1/studies` validation path (extended `validate_normalizer_reservation`), the existing `GET /api/v1/studies/{id}` / `/digest` / `GET /api/v1/proposals/{id}` read shapes (the pipeline label rides inside existing JSONB fields), and the existing `POST /api/v1/query-templates` reserved-param exemption.
- **HTTP methods for CRUD:** N/A — no new CRUD surface.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }`. **This feature introduces no new error code** (§8.5, D-8) — every new validation failure rides the existing `INVALID_SEARCH_SPACE` or Phase 1's `NORMALIZER_PARAM_SHAPE`, both already on this envelope.
- **Auth error shape:** N/A — single-tenant, no auth surface (MVP1–MVP3).

### Phase boundaries

This spec is **Phase 2** of `feat_query_normalization_tuning`. It has no further internal phases except the optional, recommended-deferred **Capability D** (operator-supplied dictionaries), which — if pursued — is tracked as `phase2_5_idea.md` per §19 D-5 and §10 below.

- **Phase 2 (this spec):** Capabilities A + B + C. Rationale: these three are the deferred items Phase 1 explicitly enumerated (D-4, D-6, D-7) and they share the normalizer-library implementation surface, so shipping them together amortizes the test-corpus and adapter-hook work.
- **Phase 2.5 (deferred — `phase2_5_idea.md`, created only if pursued):** Capability D. Rationale: custom dictionaries introduce per-cluster/template persisted state (a new column or metadata shape) and an operator-authoring UX — materially larger surface; defer until A/B/C adoption proves it.

**Deferred phase tracking:** Capability D's tracking artifact (`phase2_5_idea.md`) is created in §10 only if the user elects to pursue it; the default is to keep it as a documented out-of-scope note in this spec (§19 D-5).

## 4) Product principles and constraints

- **Backward-compatible with Phase 1.** Every Phase 1 wire input (the four bundle strings as `CategoricalParam.choices`) MUST continue to validate and behave identically. The typed pipeline is additive.
- **Opt-in, off by default.** Templates that declare neither `query_normalizer` (Phase 1) nor a `normalizer_pipeline` param behave exactly as today.
- **Engine-neutral, adapter-confined.** The generalized hook lives only in `ElasticAdapter.render` and `SolrAdapter.render` (Phase 1's locations). No caller-side code, no Protocol signature change.
- **Pure-domain, deterministic, no I/O.** `normalize_pipeline` and the step enum live in `backend/app/domain/study/normalizers.py` (Phase 1's module). No async, no DB, no network.
- **Canonical step ordering.** Steps apply in a fixed canonical order regardless of declaration order, so two declarations of the same step set produce the same normalized output and the same canonical label (avoids 2^N × permutations cardinality blowup and label ambiguity). See FR-2.
- **Single reserved key.** The reserved param key remains `query_normalizer` (Phase 1's name). A pipeline declaration uses that key with `type: "normalizer_pipeline"`; the bundle declaration uses it with `type: "categorical"`. One adapter hook serves both (D-2 locked).
- **Source-of-truth discipline.** Backend `NormalizerStep` `StrEnum` is canonical; frontend `NORMALIZER_STEP_VALUES` mirrors it with the `// Values must match backend/...` comment; the builder row consumes it via `*_VALUES.map(...)`.
- **Snippet/runtime parity.** The JS snippet's output MUST equal the Python snippet's output MUST equal the runtime `normalize_pipeline` output over the shared fixture corpus (extends Phase 1's I-4).

### Anti-patterns

- **Do not** begin implementation before Phase 1 merges. The module, hook, and frontend enum this phase extends do not exist until then.
- **Do not** replace or deprecate the Phase 1 four-bundle Categorical path. The bundles desugar into step sequences; both representations coexist.
- **Do not** apply steps in declaration order. Use the canonical `STEP_ORDER` so output is order-independent and the label space is the powerset (2^N), not permutations (N!·…).
- **Do not** introduce a second reserved key (e.g., `query_normalizer_pipeline`). One key (`query_normalizer`), two value shapes (D-2). A second key would require a second adapter-hook pop, a second validator branch, and a second frontend mirror.
- **Do not** count `NormalizerPipelineParam` as cardinality 1 in `estimate_cardinality`. Omitting the `2**len(steps)` branch silently under-counts the 10^6 cap.
- **Do not** add the JS snippet by hand-translating the Python. Generate both from the same step-sequence source so they cannot drift; assert equivalence over the corpus.
- **Do not** match smart quotes by adding `’`-keyed entries to `_CONTRACTIONS`. Pre-normalize `’`→`'` before the regex (additive, single substitution) — duplicating every dictionary key doubles the entry count and the drift surface (D-3).
- **Do not** add a `normalizer_pipeline` row to the builder without adding the matching `cardinality.tsx` branch — the live preview would under-count and mislead the operator.
- **Do not** extend `_IMPLICIT_PARAMS`. A `normalizer_pipeline` param is declared, opt-in, and reserved-nonrender (reuses Phase 1's `_RESERVED_NONRENDER_PARAMS`).

## 5) Assumptions and dependencies

- **HARD dependency: Phase 1 (`feat_query_normalization_tuning`) merged.**
  - Why required: Phase 2 extends Phase 1's `normalizers.py` module, adapter pre-render hook, `validate_normalizer_reservation`, `_RESERVED_NONRENDER_PARAMS`, PR-body section, frontend `NORMALIZER_VALUES`, and digest advisory. None exist until Phase 1 lands.
  - Status: **NOT merged — plan stage** (verified 2026-06-01; `backend/app/domain/study/normalizers.py` absent from the tree).
  - Risk if missing: **total blocker.** `/impl-execute` cannot run; the implementation plan's Story 1 is a precondition gate that fails closed if Phase 1's symbols are absent.
- Dependency: `infra_foundation`, `feat_study_lifecycle`, `feat_digest_proposal`, `feat_github_pr_worker`, `infra_adapter_elastic`, `infra_adapter_solr` — all shipped (MVP1 + Solr PR #336).
  - Status: implemented. Risk if missing: none.
- Dependency: the live search-space dispatch sites (`ParamSpec`, `estimate_cardinality`, `apply_search_space`) and the frontend builder (`row-type-selector`, `param-row`, `stash`, `cardinality`).
  - Status: implemented (verified live 2026-06-01). Risk if missing: none.
- No external service, no new third-party dependency.

## 6) Actors and roles

- Primary actor: **Relevance Engineer** — declares a `normalizer_pipeline` param in a template, runs a study, reviews the digest, opens the proposal PR, copies the Python **or** JS snippet into their production query layer.
- Secondary actor: **Approver** — reviews and merges the PR (including the "Operator-side requirement" section with both snippets).
- Role model: N/A — single-tenant install, no auth surface (MVP1–MVP3).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this feature mutates no tenant-visible state beyond what already lands in existing JSONB columns via the existing study-creation / trial-runner / PR-worker paths (no new mutation site). The `audit_log` table lands at MVP3; when it does, the existing study-create and proposal paths gain audit emission as part of the MVP3 instrumentation sweep — Phase 2 introduces no new mutation endpoint that would need its own row.

## 7) Functional requirements

### FR-1: `NormalizerStep` enum + `NormalizerPipelineParam` search-space type

- Requirement:
  - The system **MUST** add a `NormalizerStep` `StrEnum` to `backend/app/domain/study/normalizers.py` (Phase 1's module) with **exactly six** members and these exact wire values: `lowercase`, `trim`, `collapse_whitespace`, `strip_punctuation`, `expand_contractions_en`, `expand_contractions_custom`. (`expand_contractions_custom` is reserved for Phase 2.5/Capability D; in Phase 2 it is a **declared but inert** value — declaring it is accepted, but it applies no transform and the validator emits no error. See §19 D-5. **Decision candidate, see Open Questions Q-1.**)
  - The system **MUST** define `STEP_ORDER: Final[tuple[NormalizerStep, ...]]` — the canonical application order: `(lowercase, strip_punctuation, expand_contractions_en, expand_contractions_custom, collapse_whitespace, trim)`. `normalize_pipeline` applies the declared steps **filtered and reordered by `STEP_ORDER`**, never in declaration order. **Ordering rationale (resolves the whitespace-interaction footgun):** `strip_punctuation` and `expand_contractions_en` both perturb whitespace (punctuation removal can leave doubled/trailing spaces; contraction expansion lengthens tokens), so the two whitespace-cleanup steps `collapse_whitespace` then `trim` MUST run **last** in canonical order. This guarantees that when an operator selects a whitespace step alongside `strip_punctuation`, the final output has no doubled or trailing spaces — the user-visible semantics of "collapse internal whitespace" and "trim" hold regardless of which other steps are co-selected.
  - **Label ordering is SEPARATE from application ordering (critical — do not conflate).** The system **MUST** define TWO independent orderings:
    1. `STEP_ORDER` (above) — the order steps are **applied** in `normalize_pipeline`. Whitespace cleanup runs last (D-11).
    2. `LABEL_ORDER: Final[tuple[NormalizerStep, ...]]` — the order steps appear in the serialized `query_normalizer` **label**. This **MUST** be the Phase-1-compatible order: `(lowercase, trim, expand_contractions_en, collapse_whitespace, strip_punctuation, expand_contractions_custom)`, so the subset `{lowercase, trim, expand_contractions_en}` serializes to `"lowercase+trim+expand_contractions"` — byte-identical to Phase 1's bundle string. **If the label used `STEP_ORDER` instead, it would serialize to `"lowercase+expand_contractions+trim"` (trim runs last in application order), breaking Phase 1 backward-compat.** The two orderings differ precisely because Phase 1's bundle vocabulary was authored with `trim` adjacent to `lowercase`, while correct *application* requires whitespace cleanup last.
  - The system **MUST** define a `STEP_LABEL_TOKEN: Mapping[NormalizerStep, str]` mapping each step to its **label token**. The token for `expand_contractions_en` **MUST** be `"expand_contractions"` (NOT `"expand_contractions_en"`); `lowercase`/`trim` map to themselves. Steps with no Phase 1 bundle equivalent (`collapse_whitespace`, `strip_punctuation`, `expand_contractions_custom`) use their own wire value as the token. **The label is the subset's steps reordered by `LABEL_ORDER`, mapped through `STEP_LABEL_TOKEN`, joined by `+`** (empty subset → `"none"`) — deterministic and ordering-independent. Together with the token map, this makes the pipeline label space a strict superset of Phase 1's bundle vocabulary (FR-2 / I-3).
  - The system **MUST** add `NormalizerPipelineParam` to `search_space.py`: `type: Literal["normalizer_pipeline"]`, `steps: Annotated[list[NormalizerStep], Field(min_length=1)]`, `model_config = ConfigDict(extra="forbid")`, with a `@model_validator(mode="after")` rejecting duplicate steps (`ValueError("normalizer_pipeline: duplicate step '<step>'")`).
  - The system **MUST** add `NormalizerPipelineParam` as the fourth member of the `ParamSpec` discriminated union (`search_space.py:87-90`).
  - The system **MUST** add a `normalize_pipeline(query_text: str, steps: Sequence[NormalizerStep]) -> str` pure function that applies each canonical-ordered step. `lowercase`→`str.lower()`; `trim`→`str.strip()`; `collapse_whitespace`→`re.sub(r"\s+", " ", s)`; `strip_punctuation`→removes a defined ASCII punctuation set (excluding the apostrophe, which the contraction step needs); `expand_contractions_en`→Phase 1's `_PATTERN.sub` over `_CONTRACTIONS` (after smart-quote pre-normalization per FR-3); `expand_contractions_custom`→inert no-op in Phase 2.
- Notes: The function is pure, deterministic, no I/O. Per the `STEP_ORDER` above, `lowercase` runs first (so contraction matching is against the lowercased string, matching Phase 1's invariant) and the whitespace-cleanup steps `collapse_whitespace`/`trim` run **last** (after `strip_punctuation` and `expand_contractions_en`, both of which perturb whitespace — D-11). `expand_contractions_en` therefore runs *before* the whitespace cleanup, not after — the contraction step does not introduce leading/trailing whitespace, so running cleanup afterward is correct and the lowercase-before-contraction invariant still holds.

### FR-2: Sampler + cardinality + desugar integration

- Requirement:
  - `apply_search_space` (`search_space.py:249-270`) **MUST** gain a branch: `isinstance(spec, NormalizerPipelineParam)` → `trial.suggest_categorical(name, _pipeline_labels(spec.steps))`. `_pipeline_labels(steps)` returns the deterministic list of **powerset labels** — one canonical string per subset of `steps`, including the empty subset. The canonical label for a subset is the subset's steps **reordered by `LABEL_ORDER`** (NOT `STEP_ORDER`), mapped through `STEP_LABEL_TOKEN`, joined by `+` (e.g., `{trim, lowercase}` → `"lowercase+trim"`; `{expand_contractions_en, lowercase, trim}` → `"lowercase+trim+expand_contractions"`, **byte-identical to Phase 1's bundle string**). The empty subset's label is the literal `"none"`. **The returned label LIST is ordered ascending by subset size, then lexicographically by label string within each size** (a single deterministic rule, so Optuna sees a stable categorical choice order across runs and AC-4 can assert an exact list).
  - `estimate_cardinality` (`search_space.py:181-200`) **MUST** gain a branch: `isinstance(spec, NormalizerPipelineParam)` → `total *= 2 ** len(spec.steps)`.
  - The system **MUST** provide a desugar map `_BUNDLE_TO_STEPS: Mapping[str, tuple[NormalizerStep, ...]]` keyed on Phase 1's four `NORMALIZER_CHOICES` bundle strings → their equivalent step tuples (`"none"`→`()`, `"lowercase"`→`(lowercase,)`, `"lowercase+trim"`→`(lowercase, trim)`, `"lowercase+trim+expand_contractions"`→`(lowercase, trim, expand_contractions_en)`). This lets the adapter hook resolve a Phase 1 bundle value into a step tuple and call `normalize_pipeline`, so the bundle path and the pipeline path share one execution engine. **Phase 1's `normalize(query_text, bundle)` MAY be reimplemented as a thin wrapper over `normalize_pipeline(query_text, _BUNDLE_TO_STEPS[bundle])` — this is RECOMMENDED to eliminate duplicate normalization logic; the change is internal and MUST preserve Phase 1's AC-1 outputs byte-for-byte.**
  - The label space `_pipeline_labels` produces **MUST** be a strict superset of Phase 1's bundle vocabulary for the canonical bundles' step sets, so a `query_normalizer` value recorded by a pipeline trial (e.g., `"lowercase+trim"`) is indistinguishable from the same value recorded by a Phase 1 bundle trial — `digest.recommended_config["query_normalizer"]` and `proposals.config_diff` carry the identical string in both cases.

### FR-3: Smart-quote contraction matching

- Requirement:
  - The `expand_contractions_en` step (and Phase 1's `expand_contractions` bundle behavior, via the shared engine) **MUST** pre-normalize the Unicode right single quotation mark `U+2019` (`’`) to ASCII apostrophe `U+0027` (`'`) **before** the `_PATTERN` regex runs. Implementation: a single `query_text.replace("’", "'")` (or `str.translate` over a frozen map including only `’`→`'`) at the top of the contraction step.
  - Phase 1's existing fixture inputs (ASCII apostrophe) **MUST** continue to expand identically — the pre-normalization is a no-op on ASCII-only input.
  - `normalize_pipeline("what’s the policy?", [lowercase, trim, expand_contractions_en])` **MUST** return `"what is the policy?"` (identical to the ASCII `'` case).
  - **Scope note:** Only `U+2019` is pre-normalized. Other Unicode quote variants (`U+2018` left single quote, `U+02BC` modifier letter apostrophe) are **out of scope** — `U+2019` is the dominant smart-quote produced by word processors and mobile keyboards; the rest are vanishingly rare in search queries and add map entries without measurable benefit.

### FR-4: PR-body JS/TypeScript snippet

- Requirement:
  - The "Operator-side requirement" section in `_render_pr_body_study_backed` (Phase 1's FR-5) **MUST** embed **both** a Python and a JS/TypeScript reference snippet for the winning `query_normalizer` value (bundle string OR pipeline label).
  - **The snippet source MUST be a label-driven GENERATOR, not a four-key static dict (closes the four-bundle-only-dispatch gap).** Because a pipeline can win on labels Phase 1 never enumerated (e.g., `"lowercase+strip_punctuation"`, `"collapse_whitespace+trim"`, any of the 2^N powerset labels), the Python and JS snippet text **MUST** be generated from the winning label's **step list** (parse label → tokens → `NormalizerStep` set → emit the per-step code lines in `STEP_ORDER`), NOT looked up from a fixed map keyed on the four Phase 1 bundles. A `build_python_snippet(steps)` / `build_js_snippet(steps)` pair in `backend/app/domain/study/normalizers.py` emits the reference implementation for any step subset. Phase 1's four `_PR_BODY_NORMALIZER_SNIPPETS` entries become outputs of this generator (a parametrized test asserts the generator reproduces Phase 1's four snippets byte-for-byte). `expand_contractions_custom`, being inert in Phase 2, emits a commented `# (custom contractions reserved — no-op)` line in both languages so the snippet stays faithful to runtime.
  - When the winning value is `"none"` (empty step set), the section **MUST** render Phase 1's no-snippet body (no Python, no JS — "no production-side change required").
  - The section layout **MUST** be: the chosen-normalizer line, then a `### Python` sub-heading with the Python fenced block, then a `### JavaScript / TypeScript` sub-heading with the JS fenced block. (Sub-headings disambiguate the two blocks for the operator.)
  - The JS snippet **MUST** produce output semantically identical to the Python snippet and to runtime `normalize_pipeline` over the shared fixture corpus (FR-5 / I-2). The JS snippet's contraction matcher MUST include the same smart-quote pre-normalization (FR-3 parity).

### FR-5: Snippet parity invariant (extends Phase 1 I-4)

- Requirement:
  - A unit test **MUST** assert three-way equivalence over a shared fixture corpus (Phase 1's AC-12 corpus extended with `U+2019`-bearing inputs) for an **enumerated set of label cases that MUST cover, at minimum:** (i) Phase 1's four bundles; (ii) every single-step subset (`{lowercase}`, `{trim}`, `{collapse_whitespace}`, `{strip_punctuation}`, `{expand_contractions_en}`, `{expand_contractions_custom}`); (iii) at least one multi-step non-bundle combination exercising `strip_punctuation` + `collapse_whitespace` together (the whitespace-interaction path) and one exercising `expand_contractions_en` + `strip_punctuation`; (iv) a label containing `expand_contractions_custom` (asserting the inert no-op renders as the commented line in BOTH languages and produces output identical to runtime). For each (input, label) pair: `runtime normalize_pipeline(input, steps)` == `python_snippet` output == `js_snippet` output. The JS path MUST specifically include a `U+2019`-bearing input to verify the JS smart-quote pre-normalization matches the Python/runtime (FR-3 parity in JS).
  - The Python side is exercised by `exec()`-ing the snippet string into a sandbox (Phase 1's pattern). The JS side is exercised by executing the snippet under Node via a subprocess **OR**, if a Node subprocess in the backend test suite is undesirable, by a vitest test on the frontend side that imports the JS snippet string from a generated fixture and runs it against the same corpus. **Decision candidate — see Open Questions Q-2.**

### FR-6: Frontend builder row + enum mirror + glossary

- Requirement:
  - `ui/src/lib/enums.ts` **MUST** export `NORMALIZER_STEP_VALUES: readonly NormalizerStep[]` in `STEP_ORDER` with the comment `// Values must match backend/app/domain/study/normalizers.py NormalizerStep`.
  - `ui/src/lib/enums.ts` **MUST** export `NORMALIZER_STEP_GLOSSARY_KEYS: Record<NormalizerStepValue, GlossaryKey>` (the `+`-free glossary identifiers for each step).
  - `row-type-selector.tsx` **MUST** add `'normalizer_pipeline'` to `TYPE_VALUES` (and update the source-of-truth comment to cite the backend `ParamSpec` union).
  - `param-row.tsx` **MUST** render a new `<RowNormalizerPipeline>` for `spec?.type === 'normalizer_pipeline'` — an ordered multi-select of `NORMALIZER_STEP_VALUES` (labels via `NORMALIZER_STEP_GLOSSARY_KEYS`), enforcing no-duplicate selection.
  - `stash.ts` **MUST** add `case 'normalizer_pipeline': return { type: 'normalizer_pipeline', steps: [] }` — the **initial** spec when the operator first switches a row to this type, paralleling the existing categorical default's `choices: ['__placeholder__']` sentinel at [`stash.ts:66`](../../../../../ui/src/components/studies/search-space-builder/stash.ts) (an intentionally-incomplete starting state the operator then fills in).
  - **Backend-invalid-until-filled gating (closes the `steps: []` vs `min_length=1` gap):** Because `NormalizerPipelineParam.steps` is `Field(min_length=1)` (FR-1), a `steps: []` row would be rejected by `SearchSpace.model_validate` (→ `INVALID_SEARCH_SPACE`). The builder **MUST** therefore prevent submitting an empty-`steps` pipeline row: the implementer audits the existing builder's submit-gating in `index.tsx` (how it handles a categorical row still holding the `__placeholder__` sentinel) and applies the same treatment to an empty-`steps` pipeline row — an inline "Select at least one step" helper + the row counted as incomplete by whatever validity check the builder already uses. **The story MUST verify the existing gating mechanism by reading `index.tsx` before implementing; no new submission-gating mechanism is introduced.** A vitest case asserts an empty-`steps` row is flagged incomplete and not submittable.
  - `cardinality.tsx` **MUST** add a branch contributing `2 ** spec.steps.length` so the live preview matches the backend `estimate_cardinality`.
  - **Digest advisory predicate broadening (Phase 1 FR-6):** the advisory predicate in `digest-panel.tsx` **MUST** be changed from "membership in the three non-`none` bundle strings" to "`label !== "none"` AND the `+`-split label includes the `lowercase` token", so a pipeline winning on e.g. `"lowercase+strip_punctuation"` still triggers the lowercasing-redundancy advisory while a pipeline winning on `"strip_punctuation"` alone (no lowercasing) correctly does not. The Solr-hidden and analyzer-overlap conjuncts (Phase 1 FR-6) are unchanged.
  - A vitest regression test **MUST** assert: (a) the step values render via `.map()` from the enum (no inline `<SelectItem>` literals — passes `form-select-discipline`); (b) selecting `[lowercase, trim]` submits a spec `{type:"normalizer_pipeline", steps:["lowercase","trim"]}`; (c) the cardinality preview reads `4` (=2²) for a two-step pipeline; (d) an empty-`steps` pipeline row is flagged incomplete and not submittable (FR-6 gating); (e) the advisory fires for the label `"lowercase+strip_punctuation"` and does NOT fire for `"strip_punctuation"`.

### FR-7: `compute_default_params` extension

- Requirement:
  - `compute_default_params` (`template_defaults.py:59-115`) **MUST** return the canonical empty-pipeline default **label string `"none"`** (NOT an empty `steps` list) for a declared param whose type is `normalizer_pipeline`. **Locked to a single wire shape (D-7):** the adapter hook, `trials.params`, `digests.recommended_config`, and `proposals.config_diff` all carry the `query_normalizer` value as a **label string** in every code path — bundle, pipeline-winning-label, and default alike. Emitting `[]` here would create a second wire shape for the same key that consumers would have to branch on; the `"none"` string is identical to what a winning empty-subset trial records (FR-2) and to Phase 1's default, so there is exactly one shape end-to-end. This guarantees baseline trials + LLM-judgment generation never pass an undeclared/invalid/heterogeneous value to the adapter. (Mirrors Phase 1's `query_normalizer`→`DEFAULT_NORMALIZER` extension.)

### FR-8: Validation reservation extension

- Requirement:
  - Phase 1's `validate_normalizer_reservation(space)` **MUST** be extended so that when `space.params["query_normalizer"]` is a `NormalizerPipelineParam`, it is accepted (the steps are already type-constrained by the `NormalizerStep` enum at the Pydantic boundary). When it is a `CategoricalParam`, Phase 1's bundle-subset check applies unchanged. Any other param shape raises `NormalizerParamShapeError` (Phase 1's `NORMALIZER_PARAM_SHAPE`, extended message: `"query_normalizer must be CategoricalParam or NormalizerPipelineParam (got <type>)"`).
  - **`normalizer_pipeline` is reserved-key-only (closes the misplaced-pipeline-param hole).** Because the adapter pre-render hook only consumes the `query_normalizer` key (I-5), a `NormalizerPipelineParam` declared under **any other key** would be sampled and persisted but **never applied by the adapter** — a silent no-op that wastes trials and produces a label in `trials.params` no consumer reads. `validate_normalizer_reservation` **MUST** therefore raise a new `NormalizerPipelineMisplacedError` (mapped to the existing `INVALID_SEARCH_SPACE`, HTTP 400, message: `"normalizer_pipeline params are only valid under the reserved key 'query_normalizer' (found under '<name>')"`) when any `space.params[name]` with `name != "query_normalizer"` is a `NormalizerPipelineParam`. (`CategoricalParam` under arbitrary keys remains valid — only the new pipeline type is reserved-key-bound.) The router already calls `validate_normalizer_reservation` after `SearchSpace.model_validate`, so this requires no new router wiring beyond catching the new subclass — and since it maps to `INVALID_SEARCH_SPACE`, the existing handler covers it.
  - `template_validator._RESERVED_NONRENDER_PARAMS` (Phase 1) already contains `query_normalizer`; since the pipeline reuses that key, **no template-validator change is needed** beyond what Phase 1 ships.
  - The duplicate-step case **rides the existing `INVALID_SEARCH_SPACE` (400)** code (locked, D-8). The duplicate-step check is a Pydantic `@model_validator` on `NormalizerPipelineParam`, which raises inside `SearchSpace.model_validate` — already mapped to `INVALID_SEARCH_SPACE` at the router (Phase 1's precedence rule). No distinct code ships; the human `message` names the offending step (`"normalizer_pipeline: duplicate step '<step>'"`). The enum-rejection and cardinality-cap cases ride `INVALID_SEARCH_SPACE` the same way. **No new error code is introduced by this feature.**

### FR-9: Documentation updates

- Requirement:
  - [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) **MUST** gain a paragraph under the Phase-1 normalizer section describing the typed pipeline (powerset sampling, canonical step order, bundle-desugar equivalence).
  - [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) **MUST** note that the pre-render hook accepts both a bundle string and a pipeline label for the `query_normalizer` key.
  - [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) **MUST** gain a `normalizer_pipeline` `declared_params` + `search_space.params` example diff alongside Phase 1's bundle diff.
  - [`docs/04_security/llm-data-flow.md`](../../../../04_security/llm-data-flow.md) **MUST NOT** change — no LLM call introduced.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints.** Existing endpoints affected:

| Method | Path | Affected behavior |
|---|---|---|
| `POST` | `/api/v1/studies` | `validate_normalizer_reservation` (Phase 1) extended to accept a `NormalizerPipelineParam` under the `query_normalizer` key (and to reject it under any other key, → `INVALID_SEARCH_SPACE`). Duplicate-step / out-of-enum / cardinality-cap all ride the existing `INVALID_SEARCH_SPACE` (400). **No new error code.** |
| `GET` | `/api/v1/studies/{id}` | Returns the existing study shape; a `normalizer_pipeline` param rides inside `search_space.params`. No shape change. |
| `GET` | `/api/v1/studies/{id}/digest` | `recommended_config.query_normalizer` carries the winning canonical label (e.g., `"lowercase+trim"` OR a new label like `"lowercase+strip_punctuation"`). Phase 1's advisory predicate checked membership in the three non-`none` bundle strings; Phase 2 **MUST** broaden it to "the label is not `"none"` AND the label's token set includes `lowercase`" (parse the `+`-joined label, check for the `lowercase` token) — see FR-6 advisory note. The advisory stays ES/OpenSearch-only and informational. |
| `GET` | `/api/v1/proposals/{id}` | `config_diff.query_normalizer` carries the canonical label. PR body renders both snippets (FR-4). |
| `POST` | `/api/v1/query-templates` | Unchanged from Phase 1 — `query_normalizer` is already in `_RESERVED_NONRENDER_PARAMS`. Declaring it (bundle or pipeline form) without referencing `{{ query_normalizer }}` in the body is accepted; referencing it raises Phase 1's `RESERVED_PARAM_REFERENCED`. |

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code` under `detail`.
- Status codes **MUST** be deterministic per scenario.
- N/A — no auth surface.

### 8.3 Response examples

**This feature introduces no new error code** (D-8). The duplicate-step, out-of-enum, cardinality-cap, and misplaced-pipeline-key failures all surface as the existing `INVALID_SEARCH_SPACE` (400) at `POST /api/v1/studies`, with the human `message` distinguishing the cause.

Failure example — duplicate step (HTTP 400):
```json
{
  "detail": {
    "error_code": "INVALID_SEARCH_SPACE",
    "message": "normalizer_pipeline: duplicate step 'lowercase'",
    "retryable": false
  }
}
```

Failure example — `normalizer_pipeline` under a non-reserved key (HTTP 400):
```json
{
  "detail": {
    "error_code": "INVALID_SEARCH_SPACE",
    "message": "normalizer_pipeline params are only valid under the reserved key 'query_normalizer' (found under 'boost_title')",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `search_space.params.<name>.type` (when pipeline) | `normalizer_pipeline` | `backend/app/domain/study/search_space.py` (`NormalizerPipelineParam.type` `Literal`) | `row-type-selector.tsx` `TYPE_VALUES` |
| `search_space.params.<name>.steps[*]` | `lowercase`, `trim`, `collapse_whitespace`, `strip_punctuation`, `expand_contractions_en`, `expand_contractions_custom` | `backend/app/domain/study/normalizers.py` (`NormalizerStep` `StrEnum`) | `RowNormalizerPipeline` multi-select consuming `NORMALIZER_STEP_VALUES` from `ui/src/lib/enums.ts` |
| `*.query_normalizer` (recommended_config / config_diff / trial label) | any `LABEL_ORDER`-joined `+` label (tokens via `STEP_LABEL_TOKEN`) OR `none` (powerset of declared steps; superset of Phase 1's four bundles) | `backend/app/domain/study/normalizers.py` (`_pipeline_labels` / `LABEL_ORDER` / `STEP_LABEL_TOKEN` / `NORMALIZER_CHOICES`) | PR-body `build_python_snippet` / `build_js_snippet` (label→steps); digest advisory predicate (label includes `lowercase` token) |

User-visible step labels (rendered via glossary, not wire-equal):

| Wire value | User-visible label | Glossary key |
|---|---|---|
| `lowercase` | "Lowercase" | `search_space.normalizer_step.lowercase` |
| `trim` | "Trim leading/trailing whitespace" | `search_space.normalizer_step.trim` |
| `collapse_whitespace` | "Collapse internal whitespace runs" | `search_space.normalizer_step.collapse_whitespace` |
| `strip_punctuation` | "Strip ASCII punctuation (keeps apostrophes)" | `search_space.normalizer_step.strip_punctuation` |
| `expand_contractions_en` | "Expand English contractions" | `search_space.normalizer_step.expand_contractions_en` |
| `expand_contractions_custom` | "Expand custom contractions (reserved)" | `search_space.normalizer_step.expand_contractions_custom` |

### 8.5 Error code catalog

**No new error codes.** (D-8) Every Phase 2 validation failure reuses an existing code:

| Failure | Code (existing) | HTTP Status |
|---|---|---|
| Duplicate step in `normalizer_pipeline.steps` | `INVALID_SEARCH_SPACE` (Pydantic `@model_validator`) | `400` |
| Step value outside the six-member `NormalizerStep` enum | `INVALID_SEARCH_SPACE` (Pydantic enum rejection) | `400` |
| Powerset × other params exceeds 10^6 | `INVALID_SEARCH_SPACE` (`_check_cardinality`) | `400` |
| `normalizer_pipeline` under a non-`query_normalizer` key | `INVALID_SEARCH_SPACE` (`NormalizerPipelineMisplacedError` → mapped) | `400` |
| `query_normalizer` is neither `CategoricalParam` nor `NormalizerPipelineParam` | `NORMALIZER_PARAM_SHAPE` (Phase 1, broadened message) | `400` |

Phase 1's `NORMALIZER_CHOICE_INVALID`, `NORMALIZER_PARAM_SHAPE`, `RESERVED_PARAM_REFERENCED`, and the pre-existing `INVALID_SEARCH_SPACE` / `SEARCH_SPACE_*` codes remain unchanged. `NORMALIZER_PARAM_SHAPE`'s message broadens to mention `NormalizerPipelineParam` (FR-8).

## 9) Data model and state transitions

### New/changed entities

**None.** No new tables, no new columns, no migration. The `NormalizerPipelineParam` and its winning label ride inside existing JSONB:
- `studies.search_space` — the operator-declared pipeline (`{type, steps}`).
- `trials.params` — the per-trial winning powerset label (a `+`-joined string or `"none"`).
- `digests.recommended_config` — the study's winning label.
- `proposals.config_diff` — the `{from, to}` label change.

### Required invariants

- **I-1.** `normalize_pipeline(text, steps)` applies steps **only** in `STEP_ORDER`, never declaration order. For any permutation of the same step set, the output is identical. (Unit-tested over permutations.)
- **I-2.** Three-way snippet/runtime parity (FR-5): runtime `normalize_pipeline` == Python snippet == JS snippet over the shared corpus.
- **I-3.** Phase 1 backward-compat: `normalize(text, bundle)` (Phase 1 API, possibly reimplemented as a `normalize_pipeline` wrapper per FR-2) produces byte-identical output to Phase 1's AC-1 expectations for all four bundles.
- **I-4.** `estimate_cardinality` counts `2**len(steps)` for every `NormalizerPipelineParam`; the 10^6 cap fires when the product across all params exceeds it.
- **I-5.** Consumption of the `query_normalizer` value remains adapter-confined (Phase 1's I-2) — only `ElasticAdapter.render` and `SolrAdapter.render` read and apply it. Authoring sites (validator, PR-body, frontend row, glossary, tests, docs) may reference the key; the orchestrator / trial runner / baseline / judgment workers pass it through opaquely.

### State transitions

N/A — rides existing `study.state` and `proposal.status` machines untouched.

### Idempotency/replay behavior

N/A — in-band on the synchronous study-create + trial-runner + PR-worker paths; no event-driven path.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Cardinality blow-up via a many-step pipeline.** A pipeline with all six steps is 2⁶ = 64 labels — trivial. The 10^6 cap (I-4) catches any pathological combination with other params. Mitigated.
  2. **ReDoS via the contraction regex.** Unchanged from Phase 1 — `_PATTERN` is built once at import from a static 30-entry `re.escape`-d list; smart-quote pre-normalization is a single `str.replace`, O(n). Mitigated.
  3. **JS snippet drifts from runtime / Python.** Mitigated by I-2's three-way parity test.
  4. **Attacker-supplied step value.** The `NormalizerStep` `StrEnum` rejects any value outside the six at the Pydantic boundary (`INVALID_SEARCH_SPACE`). No arbitrary string reaches `normalize_pipeline`.
- **Controls:** Pydantic enum/discriminator enforcement at the API boundary; the cardinality cap; the three-way parity test; glossary-grounded labels.
- **Secrets/key handling:** N/A.
- **Auditability:** The winning label is recorded in `trials.params` + `proposals.config_diff`; the GitHub PR body (now bilingual) is the human-readable merge record.
- **Data retention/deletion/export impact:** None — no new persisted state.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Two surfaces (both extensions of existing pages):
  1. **Create-study modal → search-space builder.** The param-type dropdown gains a "Normalizer pipeline" option; selecting it renders an ordered step multi-select row.
  2. **Proposal-detail page → PR body preview.** The "Operator-side requirement" section now shows Python AND JavaScript sub-sections.
- **Labeling taxonomy:**
  - Param-type option label: "Normalizer pipeline".
  - Step labels: per the §8.4 glossary table.
  - PR sub-headings: `### Python`, `### JavaScript / TypeScript`.
- **Content hierarchy:** The pipeline row sits in the search-space parameter list like any other param row (no elevation). The PR section keeps Phase 1's placement (between `## Config diff` and `## Suggested follow-ups`).
- **Progressive disclosure:** The step multi-select renders only after the operator picks the "Normalizer pipeline" type for a row; otherwise hidden.
- **Relationship to existing pages:** All surfaces extend existing pages; no new route, tab, or modal.

### Tooltips and contextual help

All keys below are NEW (verify absence via `grep` on `ui/src/lib/glossary.ts` at implementation time). They ship in the FR-6 story.

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| "Normalizer pipeline" row label | "Compose an ordered sequence of query-string transforms. The loop tries every subset and picks the best. Steps always apply in a fixed canonical order." | hover info icon | top | `search_space.normalizer_pipeline.row` (NEW) |
| Step `lowercase` | "Apply `query.lower()`." | hover info icon | top | `search_space.normalizer_step.lowercase` (NEW) |
| Step `trim` | "Strip leading and trailing whitespace." | hover info icon | top | `search_space.normalizer_step.trim` (NEW) |
| Step `collapse_whitespace` | "Collapse internal runs of whitespace to a single space." | hover info icon | top | `search_space.normalizer_step.collapse_whitespace` (NEW) |
| Step `strip_punctuation` | "Remove ASCII punctuation, keeping apostrophes so contraction expansion still works." | hover info icon | top | `search_space.normalizer_step.strip_punctuation` (NEW) |
| Step `expand_contractions_en` | "Expand 30 common English contractions, e.g. \"what's\" → \"what is\". Matches both straight and smart apostrophes." | hover info icon | top | `search_space.normalizer_step.expand_contractions_en` (NEW) |
| Step `expand_contractions_custom` | "Reserved for operator-supplied dictionaries (not yet active)." | hover info icon | top | `search_space.normalizer_step.expand_contractions_custom` (NEW) |

All NEW keys must pass the existing length / no-jargon lint at `ui/src/__tests__/lib/glossary.test.ts`.

### Primary flows

1. **Operator declares a typed pipeline.** Operator calls `POST /api/v1/query-templates` declaring `"query_normalizer": "string"` (the declared-params type stays `"string"` — the rich shape lives in the study's `search_space`), body NOT referencing `{{ query_normalizer }}`. They create a study; the builder offers "Normalizer pipeline" as a row type; they pick steps `[lowercase, trim, expand_contractions_en]`. `validate_normalizer_reservation` accepts the `NormalizerPipelineParam`.
2. **Loop runs.** Optuna samples over the 2³ = 8 powerset labels. The orchestrator passes the suggested label to `adapter.render`; the hook resolves the label → step tuple and applies `normalize_pipeline`.
3. **Study completes; digest renders.** `recommended_config.query_normalizer = "lowercase+trim+expand_contractions"` (the canonical winning label). Phase 1's advisory predicate fires if the analyzer overlaps.
4. **Operator opens the PR.** The "Operator-side requirement" section shows the chosen label + a Python snippet AND a JS snippet. The operator copies whichever matches their query layer.

### Edge/error flows

- **Pipeline declares a duplicate step** → 400 `INVALID_SEARCH_SPACE` (Pydantic `@model_validator`; message names the step) (D-8).
- **`normalizer_pipeline` declared under a non-`query_normalizer` key** → 400 `INVALID_SEARCH_SPACE` (`NormalizerPipelineMisplacedError`) (D-10).
- **Pipeline declares a step outside the six** → 400 `INVALID_SEARCH_SPACE` (Pydantic enum rejection).
- **Pipeline × other params exceeds 10^6** → 400 `INVALID_SEARCH_SPACE` (cardinality cap).
- **Winning label is `"none"` (empty subset wins)** → PR section renders, both snippets omitted, "no production change required" copy.
- **Engine is Solr** → digest advisory hidden (Phase 1 behavior — no `FieldSpec.analyzer` on Solr); PR section still renders both snippets.
- **`expand_contractions_custom` declared in Phase 2** → accepted, applies no transform (inert), no error (per FR-1 / Q-1).
- **Query carries `’` (U+2019)** → expands identically to `'` (FR-3).

## 12) Given/When/Then acceptance criteria

### AC-1: `normalize_pipeline` applies steps in canonical order

- Given the extended `normalizers.py`
- When `normalize_pipeline("  What's   the BEST policy?  ", [expand_contractions_en, lowercase, collapse_whitespace, trim])` is called (declaration order deliberately scrambled)
- Then the result is `"what is the best policy?"` (steps applied in `STEP_ORDER`, not declaration order)
- Example values:
  - `normalize_pipeline("HELLO", [lowercase])` → `"hello"`
  - `normalize_pipeline("a , b !", [strip_punctuation])` → `"a  b "` (punctuation removed; this step alone leaves the doubled space)
  - `normalize_pipeline("a , b !", [strip_punctuation, collapse_whitespace, trim])` → `"a b"` (whitespace steps run LAST in `STEP_ORDER`, so the spaces `strip_punctuation` introduced are collapsed/trimmed — covers D-11)
  - `normalize_pipeline("x", [])` → `"x"` (empty pipeline is identity)

### AC-2: `NormalizerPipelineParam` parses via the discriminator + rejects duplicates

- Given a `SearchSpace.model_validate({"params": {"query_normalizer": {"type": "normalizer_pipeline", "steps": ["lowercase", "trim"]}}})`
- Then it parses and `params["query_normalizer"]` is a `NormalizerPipelineParam`
- Given the same with `"steps": ["lowercase", "lowercase"]`
- Then `model_validate` raises (duplicate-step validator)
- Given `"steps": ["stem"]`
- Then `model_validate` raises (enum rejection)

### AC-3: Cardinality counts the powerset

- Given a `SearchSpace` with one `normalizer_pipeline` of 3 steps and one `FloatParam`
- When `estimate_cardinality(space)` is called
- Then it returns `2**3 * 100 == 800`
- Given a pipeline whose `2**len(steps)` × other params exceeds 1_000_000
- Then `SearchSpace.model_validate` raises the cardinality error

### AC-4: Sampler suggests over powerset labels

- Given a `NormalizerPipelineParam` with steps `[lowercase, trim]`
- When `apply_search_space` runs against a stubbed Optuna trial
- Then `trial.suggest_categorical` is called with the 4-element label list `["none", "lowercase", "trim", "lowercase+trim"]` — ordered ascending by subset size (size 0: `none`; size 1: `lowercase`, `trim` lexicographically; size 2: `lowercase+trim`), exact ordering asserted against `_pipeline_labels`

### AC-5: Bundle backward-compat (I-3)

- Given Phase 1's four bundle strings
- When `normalize(text, bundle)` is called (possibly via the `normalize_pipeline` wrapper)
- Then the output is byte-identical to Phase 1's AC-1 expectations for every bundle over Phase 1's fixture corpus

### AC-6: Smart-quote expansion (FR-3)

- Given `normalize_pipeline("What’s up", [lowercase, expand_contractions_en])` (U+2019)
- Then the result is `"what is up"` — identical to the ASCII `'` input

### AC-7: PR body emits both snippets

- Given a proposal whose `config_diff.query_normalizer.to == "lowercase+trim+expand_contractions"`
- When `_render_pr_body_study_backed` runs
- Then the markdown contains `## Operator-side requirement`, a `### Python` heading + Python fenced block, AND a `### JavaScript / TypeScript` heading + JS fenced block
- Given `to == "none"`
- Then the section renders with neither snippet block and the "no production change required" copy

### AC-8: Three-way snippet parity (I-2)

- Given the parity test over the shared corpus (Phase 1 AC-12 corpus + U+2019 inputs) across the enumerated label cases per FR-5 (four bundles + every single-step subset + `strip_punctuation`+`collapse_whitespace` + `expand_contractions_en`+`strip_punctuation` + an `expand_contractions_custom` label)
- When runtime `normalize_pipeline`, the generated+`exec()`-ed Python snippet, and the generated+executed JS snippet each process every (input, label) pair
- Then all three outputs are equal for every pair, INCLUDING a `U+2019` input through the JS path (FR-3 parity in JS) and the inert `expand_contractions_custom` rendering identically in both languages

### AC-9: Frontend builder row (FR-6)

- Given the create-study builder with a row whose type is set to "Normalizer pipeline"
- When the operator selects steps `[lowercase, trim]`
- Then the submitted spec is `{type:"normalizer_pipeline", steps:["lowercase","trim"]}`
- Then the live cardinality preview reads `4`
- Then the rendered step options come via `.map()` from `NORMALIZER_STEP_VALUES` (no inline `<SelectItem>` literals — `form-select-discipline` passes)

### AC-10: `compute_default_params` empty-pipeline default (FR-7)

- Given a template declaring `query_normalizer` consumed as a `normalizer_pipeline`
- When `compute_default_params` runs for a baseline/judgment render
- Then the default value resolves to the empty pipeline (`"none"` label / empty steps) — never an invalid value

### AC-12: `normalizer_pipeline` rejected under a non-reserved key (D-10)

- Given a `POST /api/v1/studies` payload where `search_space.params` contains `{"boost_title": {"type": "normalizer_pipeline", "steps": ["lowercase"]}}`
- When the router runs `SearchSpace.model_validate` (succeeds) then `validate_normalizer_reservation`
- Then the response is HTTP 400 `{"detail": {"error_code": "INVALID_SEARCH_SPACE", "message": "normalizer_pipeline params are only valid under the reserved key 'query_normalizer' (found under 'boost_title')", ...}}`
- Given the same pipeline under the key `"query_normalizer"`
- Then it is accepted (201)

### AC-13: New (non-bundle) winning label is fully handled

- Given a proposal whose `config_diff.query_normalizer.to == "lowercase+strip_punctuation"` (a label Phase 1 never enumerated)
- When `_render_pr_body_study_backed` runs
- Then the `## Operator-side requirement` section renders with a `### Python` block AND a `### JavaScript / TypeScript` block, each generated from the step set `{lowercase, strip_punctuation}` (NOT a four-bundle dict lookup that would `KeyError`/fall through)
- Given a digest with `recommended_config.query_normalizer == "lowercase+strip_punctuation"`, engine `elasticsearch`, analyzer overlap present
- Then the lowercasing-redundancy advisory IS shown (label includes the `lowercase` token)
- Given `recommended_config.query_normalizer == "strip_punctuation"` (no lowercasing)
- Then the advisory is NOT shown

### AC-11: End-to-end — typed pipeline study against the live stack

- **Scope:** UI-observable end-to-end; native-query correctness is covered by the adapter unit tests + the trial-runner integration test.
- Given a fresh stack, a registered ES cluster, and a template declaring `query_normalizer`
- When the operator creates a study with a "Normalizer pipeline" row of `[lowercase, trim, expand_contractions_en]` and the loop runs ≥ 4 trials
- Then the trials table reflects each trial's chosen powerset label
- Then the digest renders (with Phase 1's advisory if the analyzer overlaps)
- Then opening the proposal PR produces a body with the `## Operator-side requirement` section AND both `### Python` and `### JavaScript / TypeScript` snippet blocks
- Test path: extend `ui/tests/e2e/query-normalization.spec.ts` (Phase 1) or add `query-normalizer-pipeline.spec.ts` (real-backend; no `page.route()` mocking)

## 13) Non-functional requirements

- **Performance:** `normalize_pipeline` adds at most six O(n) passes over a length-bounded `query_text`; sub-microsecond against the engine round-trip. No SLA impact.
- **Reliability:** `normalize_pipeline` is total over enum-validated steps (validated at study-create time). No new runtime failure mode.
- **Operability:** No new metrics or alerts. The winning label is observable through existing trial/proposal records.
- **Accessibility/usability:** The step multi-select uses the standard primitives (keyboard/screen-reader support inherited). All NEW glossary keys pass the length/no-jargon lint.

## 14) Test strategy requirements

Per CLAUDE.md "Testing Conventions":

- **Unit tests** (`backend/tests/unit/`):
  - `test_normalizers_pipeline.py` (NEW) — `normalize_pipeline` over step subsets, permutation-invariance (I-1), smart-quote inputs (AC-6), empty pipeline. Covers AC-1, AC-6.
  - `test_search_space_normalizer_pipeline.py` (NEW) — discriminator parse, duplicate-step rejection, enum rejection, `estimate_cardinality` powerset, `apply_search_space` label list. Covers AC-2, AC-3, AC-4.
  - `test_normalizers_bundle_compat.py` (NEW) — `normalize(text, bundle)` byte-identical to Phase 1 expectations. Covers AC-5 / I-3.
  - `test_normalizers_pr_snippets_js.py` (NEW or extend Phase 1's `test_normalizers_pr_snippets.py`) — three-way parity (runtime / Python / JS). Covers AC-8 / I-2. (JS-execution mechanism per Q-2.)
  - `test_template_defaults_normalizer_pipeline.py` (NEW) — empty-pipeline default. Covers AC-10.
- **Integration tests** (`backend/tests/integration/`):
  - `test_trial_runner_normalizer_pipeline.py` (NEW) — seed a template + study with a `normalizer_pipeline` reservation, run the trial runner, assert each trial's `params` records a powerset label and each native query body reflects `normalize_pipeline`. Covers I-5.
- **Contract tests** (`backend/tests/contract/`):
  - `test_studies_normalizer_pipeline_contract.py` (NEW) — `POST /api/v1/studies` envelope for the duplicate-step path (asserts `INVALID_SEARCH_SPACE` per D-8) AND the misplaced-pipeline-key path (asserts `INVALID_SEARCH_SPACE` per D-10). Verifies the canonical envelope.
- **E2E tests** (`ui/tests/e2e/`):
  - `query-normalizer-pipeline.spec.ts` (NEW, real-backend) — covers AC-11. Setup via API helpers; UI interaction + assertions via `page`. No `page.route()`.
- **Frontend vitest** (`ui/src/__tests__/`):
  - `row-normalizer-pipeline.test.tsx` (NEW) — covers AC-9 (row dispatch, enum-sourced options, submitted spec, cardinality preview).
  - extend the `form-select-discipline` guard so `NORMALIZER_STEP_VALUES` is `.map()`-sourced.

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` — typed-pipeline paragraph (powerset sampling, canonical order, bundle equivalence).
- `docs/01_architecture/adapters.md` — note the hook accepts a bundle string OR a pipeline label.
- `docs/02_product/` — no update (no persona-level capability shift beyond Phase 1).
- `docs/03_runbooks/local-dev.md` — `normalizer_pipeline` declaration example diff.
- `docs/04_security/` — no update (no new threat surface, no new data flow).
- `docs/05_quality/testing.md` — no update (existing conventions cover the new layers).
- `state.md` — merge one-liner; narrative to `state_history.md`.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — gated by template adoption (operator opts in by declaring a `normalizer_pipeline` param). No global flag.
- **Migration/backfill expectations:** None — no schema change.
- **Operational readiness gates:** None new — same trial-runner / orchestrator / PR-worker path.
- **Release gate:**
  - **Phase 1 merged to `main`** (HARD precondition — Story 1 of the plan fails closed otherwise).
  - All AC-* pass in CI (unit + integration + contract + 1 new/extended E2E).
  - 80% backend coverage gate green.
  - Frontend ESLint + tsc + vitest + Next build green; glossary length lints green.
  - Cross-model GPT-5.5 spec + plan review converged.
  - I-5 adversarial grep: `grep -r "query_normalizer\|normalize_pipeline" backend/app/services backend/app/agent backend/workers/trials.py backend/workers/baseline.py backend/workers/judgments.py backend/workers/orchestrator.py` returns zero non-pass-through hits.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-6 | Story 2: step enum + `normalize_pipeline` | `test_normalizers_pipeline.py` | — |
| FR-2 | AC-3, AC-4, AC-5 | Story 3: search-space type + sampler + cardinality + desugar | `test_search_space_normalizer_pipeline.py`, `test_normalizers_bundle_compat.py` | `optimization.md` |
| FR-3 | AC-6 | Story 2: smart-quote pre-normalization | `test_normalizers_pipeline.py` | — |
| FR-4 | AC-7, AC-13 | Story 5: PR-body JS snippet + label-driven snippet generator | `test_normalizers_pr_snippets_js.py` (PR-body assertions, incl. non-bundle label) | `adapters.md` |
| FR-5 | AC-8, I-2 | Story 5: three-way parity test | `test_normalizers_pr_snippets_js.py` | — |
| FR-6 | AC-9, AC-13 | Story 4: frontend builder row + enum + glossary + advisory broadening | `row-normalizer-pipeline.test.tsx`, `form-select-discipline`, `digest-panel.normalizer-advisory.test.tsx` | — |
| FR-7 | AC-10 | Story 3: `compute_default_params` extension | `test_template_defaults_normalizer_pipeline.py` | — |
| FR-8 | AC-2, AC-12 | Story 3: reservation-validator extension (incl. reserved-key-only check) | `test_search_space_normalizer_pipeline.py`, `test_studies_normalizer_pipeline_contract.py` | — |
| FR-9 | — | Story 6: docs sweep | — | `optimization.md`, `adapters.md`, `local-dev.md` |
| — | AC-11 | Story 7: real-backend E2E | `query-normalizer-pipeline.spec.ts` | — |

## 18) Definition of feature done

- [ ] **Phase 1 merged to `main`** (hard precondition).
- [ ] All acceptance criteria (AC-1 through AC-13) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) green.
- [ ] Documentation updates per FR-9 merged.
- [ ] Rollout gates from §16 satisfied.
- [ ] All open questions (§19) resolved before plan-stage finalization.
- [ ] If Capability D is elected, `phase2_5_idea.md` exists; otherwise the §19 D-5 note stands.
- [ ] `state.md` updated with the merge one-liner.

## 19) Open questions and decision log

### Open questions

These three remain for plan-time / product resolution. Each carries a recommended default so `/impl-plan-gen` does not start from zero — but they are genuine forks, not engineering-locked.

- **Q-1 — Ship `expand_contractions_custom` as an inert reserved step, or omit it entirely until Phase 2.5?** **LOCKED 2026-06-09 (operator decision): include it as an inert, declared-but-no-op value (6 steps)** so the enum and frontend don't churn when Phase 2.5 activates it. The glossary tooltip says "(reserved / not yet active)" to mitigate the silent-no-op risk. The plan body is written against six steps; no plan patch needed. **Owner:** Product. _(Recommended default accepted.)_
- **Q-2 — JS-snippet test execution: Node subprocess in the backend suite, or a frontend vitest fixture?** **LOCKED 2026-06-09 (engineering decision): frontend vitest fixture** — the backend test suite has no Node toolchain dependency today, and adding a Node subprocess to the Python test run introduces a cross-runtime dependency in CI. A vitest test imports the JS snippet string (from a generated fixture / checked-in golden) and runs it against a single committed JSON corpus shared by both runtimes. **Owner:** Engineering. _(Recommended default accepted.)_
_(Q-3 — duplicate-step error code — is now **locked** as D-8 below: ride `INVALID_SEARCH_SPACE`, no new code.)_

### Decision log

- **2026-06-01 — D-1: Phase 2 = Capabilities A + B + C; Capability D deferred.** The three deferred items Phase 1 enumerated (D-4 typed shape, D-6 JS snippet, D-7 smart quotes) ship together because they share the normalizer-library surface and the test corpus. Operator-supplied dictionaries (Capability D) introduce persisted per-cluster/template state + an authoring UX — materially larger; deferred to a recommended-out Phase 2.5.

- **2026-06-01 — D-2: One reserved key (`query_normalizer`), two value shapes.** A pipeline declaration uses the Phase 1 reserved key `query_normalizer` with `type: "normalizer_pipeline"`; the bundle declaration uses it with `type: "categorical"`. The single adapter hook dispatches on the value's shape. Rejected: a second key `query_normalizer_pipeline` — it would double the adapter pop, the validator branch, and the frontend mirror, and split the winning-label vocabulary across two columns. The single-key choice also keeps `digest.recommended_config` / `config_diff` carrying one `query_normalizer` string regardless of which representation the operator used (FR-2).

- **2026-06-01 — D-3: Smart quotes via pre-normalization, not dictionary duplication.** A single `’`→`'` `str.replace` at the top of the contraction step (the additive option from idea Capability C). Rejected: doubling every `_CONTRACTIONS` key with a `’` variant — it doubles the entry count and the drift surface for zero added expressiveness. Only `U+2019` is handled (FR-3 scope note); other Unicode apostrophe variants are vanishingly rare in queries.

- **2026-06-01 — D-4: Canonical step ordering (`STEP_ORDER`), not declaration order.** `normalize_pipeline` filters + reorders declared steps by a fixed `STEP_ORDER`. This makes output permutation-invariant (I-1) and bounds the label space to the powerset (2^N) rather than ordered subsets (which would explode cardinality and split the winning-label vocabulary across permutations). Rejected: honoring declaration order — it would make `[trim, lowercase]` and `[lowercase, trim]` distinct labels with possibly-identical output, confusing the digest and the cardinality estimate.

- **2026-06-01 — D-5: Capability D (operator-supplied dictionaries) scoped OUT of Phase 2.** Kept as a documented out-of-scope note; `phase2_5_idea.md` is created only if the user elects to pursue it. `expand_contractions_custom` ships as an inert reserved enum value (pending Q-1) so the enum/frontend don't churn when/if Phase 2.5 activates it.

- **2026-06-01 — D-7: Single wire shape for the `query_normalizer` value — always a label string.** Bundle values, pipeline winning labels, and the `compute_default_params` default all carry the value as a `+`-joined label string (or `"none"`), never an empty `steps` list. One shape end-to-end through `trials.params` / `recommended_config` / `config_diff`, so no consumer branches on shape. (Resolves the FR-7 heterogeneous-default ambiguity.)

- **2026-06-01 — D-8: No new error code — every Phase 2 validation failure rides an existing code (Q-3 locked).** Duplicate-step, out-of-enum, cardinality-cap, and misplaced-pipeline-key all surface as `INVALID_SEARCH_SPACE` (the Pydantic-ValidationError mapping Phase 1 already wires); the wrong-param-shape case rides Phase 1's `NORMALIZER_PARAM_SHAPE` (broadened message). Rejected: a distinct `NORMALIZER_PIPELINE_DUPLICATE_STEP` code — it would require the out-of-Pydantic-boundary plumbing Phase 1 reserved for the bundle-allowlist check, for a low-value machine-readable distinction the human `message` already conveys.

- **2026-06-01 — D-9: Canonical labels use Phase-1-compatible tokens (`STEP_LABEL_TOKEN`).** `expand_contractions_en` serializes to the label token `expand_contractions` so the subset `{lowercase, trim, expand_contractions_en}` produces the byte-identical Phase 1 bundle string `"lowercase+trim+expand_contractions"`. Without this, the step's wire value (`expand_contractions_en`) would leak into the label and break the strict-superset / indistinguishable-label guarantee (FR-2 / I-3) that lets bundle trials and pipeline trials share one `query_normalizer` vocabulary. Steps with no Phase 1 equivalent use their own wire value as the token.

- **2026-06-01 — D-10: `normalizer_pipeline` is reserved-key-only.** A `NormalizerPipelineParam` is valid **only** under the reserved `query_normalizer` key; declared under any other key it is rejected (`INVALID_SEARCH_SPACE`) by `validate_normalizer_reservation`. Because the adapter hook consumes only `query_normalizer`, a pipeline param elsewhere would be sampled + persisted but never applied — a silent no-op. (`CategoricalParam` under arbitrary keys stays valid — only the new pipeline type is bound.)

- **2026-06-01 — D-12: Label order (`LABEL_ORDER`) is decoupled from application order (`STEP_ORDER`).** The serialized `query_normalizer` label orders steps by `LABEL_ORDER` (Phase-1-compatible: lowercase, trim, expand_contractions, …) while `normalize_pipeline` *applies* steps by `STEP_ORDER` (whitespace cleanup last, D-11). Conflating the two would serialize `{lowercase, trim, expand_contractions_en}` as `"lowercase+expand_contractions+trim"` (trim runs last in application order), breaking the byte-identical Phase 1 bundle string `"lowercase+trim+expand_contractions"` and the single-vocabulary guarantee (FR-2 / I-3). The `_pipeline_labels` LIST is additionally ordered ascending by subset size then lexicographically, so Optuna's categorical choice order is stable and AC-4 can assert an exact list.

- **2026-06-01 — D-13: Snippet text is label-driven-generated, not bundle-dict-looked-up.** `build_python_snippet(steps)` / `build_js_snippet(steps)` emit the reference implementation for ANY powerset label (e.g. `"lowercase+strip_punctuation"`), so a pipeline winning on a non-Phase-1 label still produces a faithful, copy-pasteable snippet. Phase 1's four bundle snippets become outputs of this generator (byte-parity test). Similarly the digest lowercasing-advisory predicate is broadened from four-bundle membership to "label includes the `lowercase` token", so new labels are handled and `strip_punctuation`-only (no lowercasing) correctly suppresses the advisory.

- **2026-06-01 — D-11: Whitespace-cleanup steps run last in `STEP_ORDER`.** `collapse_whitespace` then `trim` are the final two canonical steps, after `strip_punctuation` and `expand_contractions_en` (both of which perturb whitespace). This guarantees the user-visible "collapse internal whitespace" / "trim" semantics hold no matter which steps are co-selected — punctuation removal can no longer leave doubled/trailing spaces in the final output.

- **2026-06-01 — D-6: `normalize` MAY be reimplemented over `normalize_pipeline`.** Phase 1's `normalize(text, bundle)` is RECOMMENDED to become a thin wrapper over `normalize_pipeline(text, _BUNDLE_TO_STEPS[bundle])` to eliminate duplicate normalization logic. The change is internal and MUST preserve Phase 1's AC-1 outputs byte-for-byte (I-3). If preserving byte-parity proves fiddly, the implementer MAY keep the two implementations separate — the parity test (I-2/I-3) is the gate either way.
