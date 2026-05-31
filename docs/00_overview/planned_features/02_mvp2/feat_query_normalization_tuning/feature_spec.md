# Feature Specification — Query normalization as a tunable, opt-in query-time parameter

**Date:** 2026-05-31
**Status:** Draft
**Owners:** Product — soundminds.ai · Engineering — RelyLoop core
**Related docs:**
- [`idea.md`](idea.md)
- [`pipeline_status.md`](pipeline_status.md)
- [`docs/01_architecture/optimization.md` §"Where RelyLoop fits in your relevance pipeline"](../../../../01_architecture/optimization.md)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (SearchAdapter Protocol)
- [`docs/01_architecture/apply-path.md`](../../../../01_architecture/apply-path.md) (Git-PR posture)

---

## 1) Purpose

- **Problem:** Relevance pipelines run in stages (query understanding → retrieval → ranking → re-ranking). RelyLoop tunes the ranking stage; the query-understanding stage — where light pre-query string rewriting (case-folding, whitespace trimming, contraction expansion) often hides the largest wins — is invisible to the loop. Operators tune it by hand because RelyLoop has no parameter representing it; `query_text` passes through verbatim ([`backend/app/adapters/elastic.py:547`](../../../../../backend/app/adapters/elastic.py), [`backend/app/adapters/solr.py:1108`](../../../../../backend/app/adapters/solr.py)).
- **Outcome:** A template that opts in by declaring `query_normalizer` as a Categorical param gets the Optuna loop deciding empirically — on the operator's judgment set — whether lowercasing, trimming, or contraction expansion improves nDCG/MAP/MRR. The winning normalizer travels in the proposal's `config_diff` and surfaces in the PR body as a copy-pasteable Python/JS snippet under a new "Operator-side requirement" section, so production parity is achievable without extending the apply path.
- **Non-goal (preserved):** Analyzer / index-mapping changes remain a permanent non-goal per umbrella spec §4. This feature touches only the query string before it reaches the engine — no cluster write, no schema change, no analyzer modification.

## 2) Current state audit

### Existing implementations

| File / symbol | What it does | Notes (relevant to this feature) |
|---|---|---|
| [`backend/app/domain/study/search_space.py:74`](../../../../../backend/app/domain/study/search_space.py) (`CategoricalParam`) | Discriminated-union member of `ParamSpec`; choices may be `str | int | float | bool`. | The exact shape this feature reuses — `query_normalizer` rides as a Categorical with four string choices. No new search-space type. |
| [`backend/app/domain/study/search_space.py:249`](../../../../../backend/app/domain/study/search_space.py) (`apply_search_space`) | Orchestrator calls `trial.suggest_categorical(name, list(spec.choices))`. | Already returns the chosen normalizer name in the suggested-params dict; no change required. |
| [`backend/app/domain/study/template_validator.py:57`](../../../../../backend/app/domain/study/template_validator.py) (`_IMPLICIT_PARAMS = frozenset({"query_text"})`) | Names every template implicitly receives. | This feature **does not extend** the implicit set — `query_normalizer` is opt-in via the template's `declared_params`. The unused-declared check at L127-131 (`unused_declarations = set(declared_params) - referenced`) would, however, reject any template that declares `query_normalizer` without referencing `{{ query_normalizer }}` in the body. The body never references it (the normalizer is consumed by the adapter, not the template). FR-2 introduces a new `_RESERVED_NONRENDER_PARAMS = frozenset({"query_normalizer"})` exemption so declared-but-unreferenced reserved keys pass. |
| [`backend/app/adapters/elastic.py:521-554`](../../../../../backend/app/adapters/elastic.py) (`ElasticAdapter.render`) | Builds Jinja context as `{**params, "query_text": query_text}` at L547 and renders. | The pre-render hook lives here — pop `query_normalizer` from `params`, apply it to `query_text`, inject the normalized value. Single class handles both ES and OpenSearch (per CLAUDE.md "Stack"). |
| [`backend/app/adapters/solr.py:1071-1127`](../../../../../backend/app/adapters/solr.py) (`SolrAdapter.render`) | Same context shape at L1108: `{**params, "query_text": query_text}`. | Same hook location. SolrAdapter shipped 2026-05-31 via `infra_adapter_solr` PR #336. |
| [`backend/app/adapters/protocol.py:219-226`](../../../../../backend/app/adapters/protocol.py) (`SearchAdapter.render`) | Protocol signature: `render(template, params, query_text) -> NativeQuery`. | Unchanged. The hook lives inside each implementation; no Protocol-level signature change. |
| [`backend/workers/trials.py:403`](../../../../../backend/workers/trials.py) | `adapter.render(template, snapshot.params, q.query_text)` per query in the trial batch. | Caller side untouched — `snapshot.params` already carries the chosen Categorical when `query_normalizer` is declared. |
| [`backend/workers/baseline.py:194`](../../../../../backend/workers/baseline.py) | Same `adapter.render` call shape for the baseline. | Baseline trial uses `template.default_param_values` (no Optuna suggestion); for a baseline run the operator's `default_param_values["query_normalizer"]` decides the baseline normalizer (typically `"none"`). |
| [`backend/workers/judgments.py:195`](../../../../../backend/workers/judgments.py) | LLM-judgment hits use `adapter.render(template, default_params, query.query_text)`. | Same path. Judgment generation runs against the template's defaults, so the baseline normalizer applies there too — the LLM never sees the choice space. |
| [`backend/workers/git_pr.py:540`](../../../../../backend/workers/git_pr.py) (`_render_pr_body_study_backed`) | Renders the study-backed proposal PR markdown body. | The new "Operator-side requirement" section lands here, after `## Config diff` and before `## Suggested follow-ups`, conditioned on `query_normalizer` appearing in `config_diff`. |
| [`backend/app/db/models/proposal.py:64`](../../../../../backend/app/db/models/proposal.py) (`Proposal.config_diff`) | `JSONB`, `{param: {from, to}}`. | Stores the winning normalizer name like any other param; no schema change. |
| [`backend/app/adapters/protocol.py:39-46`](../../../../../backend/app/adapters/protocol.py) (`FieldSpec.analyzer`) | `str | None` — populated by `ElasticAdapter.get_schema` from `_meta`. **`SolrAdapter` sets `analyzer=None` always** ([`solr.py:1064`](../../../../../backend/app/adapters/solr.py) comment block). | The "redundant-normalizer advisory" (Q3 default) consumes this. **Advisory is ES/OpenSearch-only in MVP2** — Solr's analyzer info is not surfaced by the `get_schema` shape and a fix is outside this feature's scope. |
| [`ui/src/components/studies/digest-panel.tsx:88`](../../../../../ui/src/components/studies/digest-panel.tsx) (`digest.recommended_config`) | Renders the winning config as JSON. | The "tuned-parameters panel" referenced in the idea. The advisory line lands above this JSON block. |
| [`ui/src/components/studies/search-space-builder/`](../../../../../ui/src/components/studies/search-space-builder/) (`row-categorical.tsx` et al.) | Operator-editable Categorical rows in the create-study modal. | A four-choice `query_normalizer` is just another Categorical row when the template declares it; the existing UI handles it without modification. |
| [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) | Source-of-truth for tooltip copy. | New keys `search_space.query_normalizer.choice.none / lowercase / lowercase_trim / lowercase_trim_expand_contractions`, `search_space.query_normalizer.row`, and `digest.normalizer_advisory` land here. |

**Why this matters:** Three render-call sites (trials/baseline/judgments) all pass through the adapter's `render()`. Putting the hook inside `render()` confines the change to two files (`elastic.py`, `solr.py`) and avoids touching the orchestrator/worker layer.

### Navigation and link impact

No URL changes. The feature does not move, rename, or remove any page or tab — the operator continues to access `query_normalizer` via the existing create-study modal's search-space builder, the existing study-detail page, and the existing proposal-detail page.

| Source file | Current link target | New link target |
|---|---|---|
| _none_ | _none_ | _none_ |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/domain/study/test_search_space.py`](../../../../../backend/tests/unit/domain/study/test_search_space.py) | `CategoricalParam` / `apply_search_space` assertions | unchanged | No change — `query_normalizer` reuses the existing Categorical path. |
| [`backend/tests/unit/domain/study/test_template_validator.py`](../../../../../backend/tests/unit/domain/study/test_template_validator.py) | `_IMPLICIT_PARAMS` cross-check assertions | unchanged | No change — `query_normalizer` is declared, not implicit. |
| [`backend/tests/unit/adapters/test_elastic.py`](../../../../../backend/tests/unit/adapters/test_elastic.py) (and the Solr equivalent) | `render(...)` shape assertions | augment | Add two test cases per adapter: (a) `query_normalizer` absent → `query_text` passes through verbatim; (b) `query_normalizer="lowercase+trim+expand_contractions"` → context's `query_text` is normalized. |
| [`backend/tests/integration/workers/test_trials_*.py`](../../../../../backend/tests/integration/workers/test_trials.py) | Trial-runner end-to-end DB-backed flow | augment | One new test: seed a template with `query_normalizer` declared, run a 4-trial study, assert each trial's recorded `params` contains the chosen normalizer and the issued native query body reflects normalization. |
| [`backend/tests/unit/workers/test_git_pr_body.py`](../../../../../backend/tests/unit/workers/test_git_pr_body.py) | PR markdown body assertions | augment | One new test: when `config_diff` contains `query_normalizer`, the rendered body includes the "Operator-side requirement" section with the named normalizer + snippet. |
| `ui/src/__tests__/components/studies/digest-panel.test.tsx` | Existing digest panel rendering | augment | Add a case asserting the advisory copy renders when `recommended_config.query_normalizer` is present AND the schema's matching field has `analyzer == "standard"` or another lowercase-applying analyzer. |
| `ui/tests/e2e/` (no existing spec covers normalization) | — | new | One new real-backend Playwright spec — see §14 below. |

### Existing behaviors affected by scope change

- **`adapter.render(template, params, query_text)`**: Current — `query_text` is injected into the Jinja context verbatim. New — when `params` contains a `query_normalizer` key matching one of the four built-in choices, the adapter pops the key, applies the named normalizer, and injects the normalized string. **Decision needed:** No — the behavior change is gated entirely on the template having `query_normalizer` in `declared_params`; existing templates are unaffected.
- **Trial recording**: Current — `trials.params` JSONB records the suggested categorical value. New — same shape; `query_normalizer="lowercase+trim+expand_contractions"` lands as a string value in the same column. **Decision needed:** No.
- **PR body rendering**: Current — `_render_pr_body_study_backed` emits sections {Metric delta, Confidence, Config diff, Suggested follow-ups, Parameter importance}. New — when `config_diff` contains `query_normalizer`, an "Operator-side requirement" section is inserted between `## Config diff` and `## Suggested follow-ups`. **Decision needed:** No — additive, conditional on a key being present.
- **Digest `recommended_config`**: Current — JSON block of the winning param map. New — same JSON block; an advisory line is rendered above when the chosen normalizer overlaps with the field analyzer's transforms. **Decision needed:** No — additive, ES/OpenSearch-only in MVP2 (Solr has no per-field analyzer in `get_schema`).

---

## 3) Scope

### In scope

- A pure-domain normalizer library in a new file `backend/app/domain/study/normalizers.py` with **exactly four built-in choices** — `none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions` — and a `NORMALIZER_CHOICES: Final[tuple[str, ...]]` allowlist mirrored to the frontend via `ui/src/lib/enums.ts`.
- An English-only contraction dictionary embedded in the same module — **30 entries**, frozen as `_CONTRACTIONS: Mapping[str, str]`, listed in full in §9 below.
- A pre-render hook inside both `ElasticAdapter.render` and `SolrAdapter.render` that pops a reserved `query_normalizer` key from `params` before the Jinja render context is built, applies the named normalizer to `query_text`, and injects the normalized value at `context["query_text"]`. When the key is absent, behavior is identical to today.
- The reserved key name `query_normalizer` becomes a **reserved Categorical-param identifier** validated by a new pure-domain function `validate_normalizer_reservation(space)` invoked from the `POST /api/v1/studies` router AFTER `SearchSpace.model_validate` succeeds (see FR-2). If a template declares `query_normalizer` in `declared_params`, its `search_space.params["query_normalizer"]` must be a `CategoricalParam` whose `choices` are a subset of `NORMALIZER_CHOICES`. Direct calls to `SearchSpace.model_validate(...)` do NOT enforce the reservation — by design, so unit tests of `SearchSpace` itself stay focused on the discriminated-union mechanics; reservation tests target `validate_normalizer_reservation` directly + the router contract.
- Opt-in template adoption: the feature ships **no template change** in the demo seed; operators adopt by editing their template's `declared_params` + `search_space.params`. A one-paragraph runbook in [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) shows the diff.
- PR-body extension in `_render_pr_body_study_backed`: a new "Operator-side requirement" section renders **only when `config_diff` contains `query_normalizer`**, naming the chosen normalizer and embedding a copy-pasteable Python snippet implementing it (the language is fixed to Python for MVP2 — operators in JS/Node land lift the logic; this is documented).
- A non-blocking advisory above the `recommended_config` JSON in `digest-panel.tsx`, rendered when (i) `recommended_config.query_normalizer` ∈ {`lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions`} AND (ii) the study's target field schema has at least one field with `analyzer` matching a known lowercase-applying analyzer (`standard`, `english`, `simple`, or any custom name containing `lowercase`). The advisory is computed from the `Schema` payload the existing `GET /api/v1/clusters/{id}/targets/{target}/schema` endpoint already returns — no new endpoint, no extension to the capability probe.
- One new agent-tool-visible behavior: nothing. Existing tools that read `studies.search_space` and `proposals.config_diff` see `query_normalizer` as a string-valued Categorical / config-diff entry; no new agent tool ships.

### Out of scope

- Apply-path-side normalizer declaration (option (a) from the idea's gating fork). Deferred to `feat_apply_path_normalizer_declaration` — see §19 decision log.
- Operator-supplied contraction dictionaries, locale variants, spell correction, stemming, stopword removal, synonym expansion. None ship in MVP2.
- A new search-space type (typed sub-object representing an ordered list of normalization steps). Deferred to `phase2_idea.md`.
- Extending the capability probe to record analyzer redundancy. The advisory uses the existing `Schema` payload only.
- Adding a `SolrAdapter`-side analyzer-redundancy advisory. Deferred until `SolrAdapter.get_schema` populates `FieldSpec.analyzer` — a separate concern not in this scope.
- Changing the `SearchAdapter` Protocol signature.
- Any LLM call, any cluster write, any external dependency.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints; unprefixed for operator/webhook endpoints — per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md).
- **Router namespace for this feature's endpoints:** **None — no new endpoints.** The feature rides existing surfaces (`POST /api/v1/studies` validates the `query_normalizer` reservation through `SearchSpace.model_validate`; `GET /api/v1/studies/{id}` returns the existing study shape with `query_normalizer` riding inside `search_space.params`; `GET /api/v1/proposals/{id}` returns the existing shape with `query_normalizer` riding inside `config_diff`).
- **HTTP methods for CRUD:** N/A — no new CRUD surface.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md`. The two new error codes (§7.5) follow the same envelope as `INVALID_SEARCH_SPACE` today.
- **Auth error shape:** N/A — MVP1–MVP3 single-tenant, no auth surface.

### Phase boundaries

- **Phase 1 (MVP2 — this spec):** Normalizer library + pre-render hook + Categorical reservation + PR-body "Operator-side requirement" section + ES/OpenSearch redundancy advisory + Python snippet only. Rationale: this is the minimum coherent slice that lets the loop discover-and-propose a normalizer with a documented production-replication path. Option (b) hand-off path locks the deployment story; no apply-path extension required.
- **Phase 2 (deferred — [`feat_query_normalizer_typed_pipeline`](../feat_query_normalizer_typed_pipeline/idea.md)):** Typed sub-object representing an ordered list of normalization steps (the "more expressive" shape from idea Q4) AND a JS/TypeScript snippet in addition to Python. Rationale: holds until operator feedback proves the four built-in bundles are insufficient. A typed sub-object requires a new search-space discriminator and a migration; not warranted on day one.
- **Phase 3 (deferred — [`feat_apply_path_normalizer_declaration`](../feat_apply_path_normalizer_declaration/idea.md)):** Apply-path-side normalizer declaration (option (a) of the gating fork). The winning normalizer ships as a structured field in the config-repo PR (not just prose) so the operator's CI consumes it directly. Rationale: depends on operator adoption signal — if Phase 1's documentation hand-off proves frictionful (operator surveys / GitHub issues), Phase 3 ships; otherwise it stays deferred.

**Deferred phase tracking:** Phase 2 + Phase 3 were carved into their own sibling planned-features folders (`feat_query_normalizer_typed_pipeline`, `feat_apply_path_normalizer_declaration`) on 2026-05-31.

## 4) Product principles and constraints

- **Opt-in, off by default.** Templates that don't declare `query_normalizer` behave exactly as today. No demo-seed template ships with the reservation pre-declared (per scope).
- **Engine-neutral, adapter-confined.** The hook lives inside `ElasticAdapter.render` and `SolrAdapter.render`; no caller-side code, no Protocol signature change. The behavior is identical across ES, OpenSearch, and Solr because the hook applies to the `query_text` Jinja context value all three render shapes consume.
- **Pure-domain, deterministic, no I/O.** `backend/app/domain/study/normalizers.py` is a pure function module — no async, no DB, no network, no LLM call. Same input → same output, always.
- **No cluster writes.** Strictly query-time string rewriting. Analyzer / index-mapping changes remain a permanent non-goal per umbrella spec §4.
- **Production parity is documented, not engineered.** MVP2 ships the "Operator-side requirement" section in the PR body. The operator copies the snippet into their query layer. The PR description is the contract.
- **Reserved-key discipline.** `query_normalizer` becomes a single reserved Categorical-param identifier. The choices set is a fixed allowlist — any value outside it raises a 400 `NORMALIZER_CHOICE_INVALID` from `validate_normalizer_reservation` at the router boundary (NOT collapsed into the broader `INVALID_SEARCH_SPACE`).
- **Source-of-truth discipline (per CLAUDE.md "Enumerated Value Contract Discipline").** Backend `NORMALIZER_CHOICES: Final[tuple[str, ...]]` is the canonical allowlist; frontend `NORMALIZER_VALUES` in `ui/src/lib/enums.ts` mirrors it with the `// Values must match backend/...` comment, and the create-study modal's Categorical row consumes it via the `*_VALUES.map(...)` pattern.

### Anti-patterns

- **Do not** extend `_IMPLICIT_PARAMS` to include `query_normalizer` — that would make it implicit on every template, breaking opt-in.
- **Do not** apply the normalizer at the orchestrator (`backend/workers/orchestrator.py`) or trial runner (`backend/workers/trials.py:403`) — three call sites would have to duplicate the hook (`trials.py`, `baseline.py`, `judgments.py`). The single adapter-resident hook is the only correct location.
- **Do not** allow `query_normalizer` to be a `FloatParam` or `IntParam` — the reservation must enforce `CategoricalParam` with `choices ⊆ NORMALIZER_CHOICES`. Validation lives in `validate_normalizer_reservation` (new pure-domain function in `backend/app/domain/study/normalizers.py`), called from the studies router AFTER `SearchSpace.model_validate` succeeds. Pydantic's `@model_validator(mode="after")` is NOT used here because it wraps failures into `ValidationError` and that would re-collide with the existing `INVALID_SEARCH_SPACE` mapping.
- **Do not** extend the `SearchAdapter` Protocol signature. The hook is implementation-internal.
- **Do not** mutate the operator-supplied `params` dict in `render()` — pop the key into a local, leave the original dict unmodified. The orchestrator persists `params` as the trial's recorded suggestion; mutating it would corrupt the audit trail (`trials.params` is the canonical source for `digest.recommended_config`).
- **Do not** make the redundancy advisory blocking. It's informational. The loop runs the same trial budget regardless.
- **Do not** add a `SolrAdapter`-side redundancy advisory. `FieldSpec.analyzer` is `None` for Solr today; surfacing a partial advisory ("ES advised, Solr silent") would confuse operators. The advisory renders ES/OpenSearch-only and the digest UI states that scope.
- **Do not** introduce a JS snippet in the PR body. Python only for MVP2; the snippet is short enough that the operator can translate trivially, and supporting two languages doubles the test surface without an MVP2 use case.
- **Do not** introduce locale variants of the contraction dictionary, an operator-override mechanism for it, or a runtime-loaded dictionary. All four normalizers and the 30-entry dictionary are baked into the module.

## 5) Assumptions and dependencies

- Dependency: `infra_foundation`, `feat_study_lifecycle`, `feat_digest_proposal`, `feat_github_pr_worker` — all shipped (MVP1).
  - Why required: study creation, search-space validation, digest rendering, PR body rendering.
  - Status: implemented.
  - Risk if missing: none — all shipped.
- Dependency: `ElasticAdapter`, `SolrAdapter` (`infra_adapter_elastic` shipped MVP1, `infra_adapter_solr` PR #336 shipped 2026-05-31).
  - Why required: the pre-render hook lands inside both adapters.
  - Status: implemented.
  - Risk if missing: none — both shipped.
- Sibling MVP2 features (`feat_overnight_autopilot`, `feat_study_convergence_indicator`, `feat_ubi_llm_study_comparison`, `feat_fts_rank_ordering`, `chore_demo_seeding_integration_tests_rewrite`) are idea-stage on this branch. **None block this feature.** Composes with — does not depend on — any of them.
- No external service, no new third-party dependency.

## 6) Actors and roles

- Primary actor: **Relevance Engineer** (per umbrella §6) — declares `query_normalizer` in a template, runs a study, reviews the digest, opens the proposal PR, copies the snippet into their production query layer.
- Secondary actor: **Approver** — reviews the PR (including the "Operator-side requirement" section) and merges it in the config repo.
- Role model: N/A — single-tenant install, no auth surface (MVP1–MVP3 per [`docs/01_architecture/tech-stack.md`](../../../../01_architecture/tech-stack.md)).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — audit_log lands at MVP3.

## 7) Functional requirements

### FR-1: Normalizer library — pure-domain module

- Requirement:
  - The system **MUST** ship `backend/app/domain/study/normalizers.py` exposing:
    - `NORMALIZER_CHOICES: Final[tuple[str, str, str, str]] = ("none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions")`.
    - `DEFAULT_NORMALIZER: Final[str] = "none"` — the safe default applied at every consumption site when `query_normalizer` is absent from the params dict.
    - `def normalize(query_text: str, choice: str) -> str` — applies the named normalizer. Raises `ValueError("unknown normalizer: <choice>")` when `choice` ∉ `NORMALIZER_CHOICES`.
    - `_CONTRACTIONS: Mapping[str, str]` — the 30-entry frozen mapping listed in §9.
  - **`compute_default_params` extension** ([`backend/app/domain/study/template_defaults.py:59`](../../../../../backend/app/domain/study/template_defaults.py)): the function **MUST** be extended so that when a declared param's name is `"query_normalizer"` (regardless of whether the declaration is in simple-form `"string"` or rich-form `{"type": "categorical", ...}`), the returned default value is `DEFAULT_NORMALIZER` (`"none"`), NOT the simple-form fallback `""`. This guarantees baseline trials and LLM-judgment generation (which both consume `compute_default_params`) never pass an invalid choice to the adapter.
  - **Adapter pre-render hook fallback** (per FR-3/FR-4): the adapter's hook **MUST** also default to `DEFAULT_NORMALIZER` when `query_normalizer` is absent from `params`. Defense-in-depth — covers any future caller that bypasses `compute_default_params`.
  - The module **MUST** be pure: no async, no DB, no httpx, no `openai` import. The `_CONTRACTIONS` mapping **MUST** be a module-level constant — no runtime loading.
  - `normalize("Hello World ", "lowercase+trim")` **MUST** return `"hello world"`.
  - `normalize("what's the best policy?", "lowercase+trim+expand_contractions")` **MUST** return `"what is the best policy?"`.
  - Contraction expansion **MUST** be word-boundary safe — substitution only occurs when the contraction is surrounded by `\b` boundaries (regex), so `"what's"` expands but `"whatsoever"` does not. Implementation pattern: pre-build a single compiled `re.Pattern` from `r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b"`.
  - Contraction expansion **MUST** run AFTER lowercasing AND trim — the four choices are strict supersets in order.
  - Contraction matching **MUST** be case-insensitive against the lowercased input, which simplifies to "match against the lowercased input" since `lowercase+trim` runs first.

### FR-2: Reserved Categorical-param key — `query_normalizer`

- Requirement:
  - When `search_space.params` contains a key named `"query_normalizer"`, the system **MUST** require it to be a `CategoricalParam` and the `choices` set **MUST** be a non-empty subset of `NORMALIZER_CHOICES`.
  - Validation **MUST** live in a new pure-domain function `validate_normalizer_reservation(space: SearchSpace) -> None` in `backend/app/domain/study/normalizers.py`, raising two new domain-level exception subclasses of `ValueError`:
    - `NormalizerChoiceInvalidError` — choice ∉ `NORMALIZER_CHOICES`; message format: `"query_normalizer choice '<value>' is not in the allowed set: ['none', 'lowercase', 'lowercase+trim', 'lowercase+trim+expand_contractions']"`.
    - `NormalizerParamShapeError` — `space.params["query_normalizer"]` is not a `CategoricalParam`; message format: `"query_normalizer must be CategoricalParam (got <actual_type_name>)"`.
  - The `POST /api/v1/studies` router (at [`backend/app/api/v1/studies.py:213`](../../../../../backend/app/api/v1/studies.py)) **MUST** invoke `validate_normalizer_reservation` AFTER the existing `SearchSpace.model_validate(...)` call and catch both new exceptions by name, mapping to `error_code` `NORMALIZER_CHOICE_INVALID` / `NORMALIZER_PARAM_SHAPE` (HTTP 400) via the established `_err(...)` helper. The mapping mirrors the existing `UnknownSearchSpaceParamError` → `SEARCH_SPACE_UNKNOWN_PARAM` pattern at `studies.py:263-266` — domain ValueError subclass caught by name, no Pydantic-ValidationError-wrapping ambiguity.
  - **Precedence:** If `SearchSpace.model_validate` itself fails for unrelated reasons (cardinality cap, bad type), the existing `INVALID_SEARCH_SPACE` (400) fires first; `validate_normalizer_reservation` only runs on a successfully validated `SearchSpace`. The two new codes never collide with `INVALID_SEARCH_SPACE`.
  - The template's `declared_params` **MUST** include `"query_normalizer"` for the search-space entry to be accepted — the existing `validate_against_template` cross-check handles this without modification.
  - When `query_normalizer` is declared but `search_space.params["query_normalizer"]` is missing, the existing `MissingDeclaredParamError` → `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400) path fires unchanged.
  - **Template-validator extension** (resolves the unused-declared check from §2 audit AND the body-reference footgun): `backend/app/domain/study/template_validator.py` **MUST** gain a new module-level `_RESERVED_NONRENDER_PARAMS: frozenset[str] = frozenset({"query_normalizer"})`, and `validate_template_body` **MUST**:
    1. Exclude reserved-nonrender names from the `unused_declarations` set before the `DeclaredParamUnused` raise at L128-131 — so a template declaring `query_normalizer` without referencing `{{ query_normalizer }}` parses cleanly.
    2. **REJECT** any template body that references a reserved-nonrender name (i.e., `referenced ∩ _RESERVED_NONRENDER_PARAMS` is non-empty). Raise a new `ReservedParamReferenced(ValueError)` exception subclass with message `"template body references reserved non-render param(s): <sorted_list>; these are consumed by the adapter and MUST NOT appear in the template body"`. Mapped at the router to a new error code `RESERVED_PARAM_REFERENCED` (HTTP 400) at `POST /api/v1/query-templates`.
  - Add a unit test pair: (a) template body without `{{ query_normalizer }}` + `declared_params = {"query_normalizer": "string"}` → parses cleanly; (b) template body referencing `{{ query_normalizer }}` → raises `ReservedParamReferenced`.
  - **Coverage of non-API write paths:** Demo seeding routes through `POST /api/v1/studies` (per `backend/app/services/demo_seeding.py:739` "Build the search_space body for a POST /studies request"), so the validator covers seed studies. Test factories that construct `SearchSpace` directly via Pydantic in pytest are out of scope for the validator gate — the integration test at §14 includes a factory-level call to `validate_normalizer_reservation` to lock the contract.

### FR-3: Pre-render hook in `ElasticAdapter.render`

- Requirement:
  - At the top of `ElasticAdapter.render` (before the existing missing-params check and before context construction), the adapter **MUST**:
    1. Copy `params` into a local mutable dict (do NOT mutate the caller's dict).
    2. Pop `"query_normalizer"` from the local copy if present; default to `"none"` when absent.
    3. Apply `normalize(query_text, chosen)` to produce `normalized_query_text`.
    4. Build the context as `{**local_params, "query_text": normalized_query_text}` (the local copy without `query_normalizer`, plus the normalized string).
  - The missing-params check **MUST** run against `local_params` (post-pop), so a template that declares `query_normalizer` but no other params still validates correctly.
  - When `params["query_normalizer"]` holds a string outside `NORMALIZER_CHOICES`, `normalize` raises `ValueError`; `render` **MUST** wrap it as it does today (`ValueError("render: missing required template params: ...")` pattern) — the resulting error surfaces as the existing trial-failure path (per `trials.py` error handling), so a single bad trial fails without aborting the study. A new error code `NORMALIZER_CHOICE_INVALID` is reserved at the router for the create-study path; at trial-runtime, the existing `RUN_TRIAL_RENDER_FAILED` envelope subsumes.

### FR-4: Pre-render hook in `SolrAdapter.render`

- Requirement:
  - `SolrAdapter.render` **MUST** apply the identical pre-render hook (same algorithm as FR-3), at the same logical point — before context construction at `solr.py:1108`.
  - The hook **MUST** apply BEFORE the existing `_pivot_to_solr_params` / `_check_ltr_model_available` post-render steps; those steps consume the rendered dict, which is downstream of the `query_text` context substitution and therefore independent of normalization.
  - Behavior **MUST** be observable as identical across ES + OpenSearch (`ElasticAdapter`) and Solr (`SolrAdapter`) — the same `query_text` enters the template, regardless of engine.

### FR-5: PR-body "Operator-side requirement" section

- Requirement:
  - `_render_pr_body_study_backed` ([`backend/workers/git_pr.py:540`](../../../../../backend/workers/git_pr.py)) **MUST** insert a new section between `## Config diff` and `## Suggested follow-ups` (or before the `---` footer if no follow-ups) when `config_diff` contains a `query_normalizer` key.
  - **Important note on `config_diff` semantics:** `config_diff` is NOT a filtered-by-change diff. The digest worker builds it at [`backend/workers/digest.py:1156-1159`](../../../../../backend/workers/digest.py) as `{p: {"from": template_defaults.get(p), "to": v} for p, v in recommended_config.items()}` — every winning param lands as `{from, to}` regardless of whether `from == to`. The section therefore renders whenever the study tuned `query_normalizer`, including the no-op winner case (`from == "none" AND to == "none"`). FR-5's `none` branch below covers that case explicitly.
  - The chosen normalizer name **MUST** be read as `choice_name = config_diff["query_normalizer"]["to"]`. The implementation **MUST** validate `choice_name in NORMALIZER_CHOICES` before snippet lookup and raise a logged warning + fall through to the `none` branch if the value is invalid (defense-in-depth — by FR-2's gate, this is unreachable in normal flow).
  - The section title **MUST** be `## Operator-side requirement` (canonical, exact).
  - The section body **MUST** name the chosen normalizer in inline code, state the merge contract, and embed a Python snippet implementing the normalizer the operator can paste into their query layer.
  - Canonical body text:
    ```
    ## Operator-side requirement

    RelyLoop measured the gain above against a query-time normalizer it
    applied before the query reached the engine. To reproduce the gain
    in production, your query-serving layer **MUST** apply the same
    normalizer to incoming queries before they hit the engine.

    **Chosen normalizer:** `<choice_name>`

    Reference implementation (Python — adapt to your language as needed):

    ```python
    <inlined snippet — see §9 "Python snippet templates" below>
    ```
    ```
  - The Python snippet **MUST** be lifted verbatim from a static dict `_PR_BODY_NORMALIZER_SNIPPETS: Mapping[str, str]` in `backend/app/domain/study/normalizers.py` keyed on the four `NORMALIZER_CHOICES`. The same module owns both the runtime implementation AND the snippet — single source of truth.
  - When the chosen normalizer is `"none"`, the section **MUST** still render but the body **MUST** read `"**Chosen normalizer:** \`none\`. No production-side change is required — the loop confirmed the un-normalized query already wins."` (skip the Python snippet — there's nothing to copy).
  - When `config_diff` does NOT contain `query_normalizer`, the section **MUST NOT** render at all (no empty header, no placeholder).

### FR-6: Non-blocking analyzer-redundancy advisory in digest panel

- Requirement:
  - `digest-panel.tsx` **MUST** render an inline informational line immediately above the `digest.recommended_config` JSON block when ALL of:
    1. `recommended_config.query_normalizer` ∈ {`lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions`}.
    2. The study's target field schema has at least one `text`-typed field whose `analyzer` matches one of `{"standard", "english", "simple"}` OR contains the substring `"lowercase"`. **Note:** the ES/OpenSearch `whitespace` analyzer is **excluded** from this list — it tokenizes on whitespace but does NOT apply a lowercase token filter; including it would produce false-positive advisories.
    3. The engine is `elasticsearch` or `opensearch` (Solr's `FieldSpec.analyzer` is `None` per [`backend/app/adapters/solr.py:1064`](../../../../../backend/app/adapters/solr.py) and the advisory is meaningless on Solr).
  - **Frontend data flow:** the study-detail page (`ui/src/app/studies/[id]/page.tsx`) currently fetches study, trials, digest, proposal, children — **but not schema and not cluster**. Story 4 introduces two new TanStack Query calls at the page level once `study.cluster_id` is resolved:
    1. **`useCluster(study.cluster_id)`** — already exists at `ui/src/lib/api/clusters.ts:83`. The page reads `cluster.engine_type` from its result. No backend contract change — the existing `GET /api/v1/clusters/{id}` response already carries `engine_type`. §8.1 "No shape change" remains correct because no endpoint shape changes.
    2. **`useTargetSchema(clusterId: string, target: string)`** — new hook calling the existing `GET /api/v1/clusters/{id}/targets/{target}/schema` endpoint (verify name in Story 4 against `backend/app/api/v1/clusters.py`).
  - Both results are passed to `<DigestPanel>` as optional props (`engineType?: EngineType`, `schema?: Schema`). The advisory predicate evaluates to `false` when either prop is `undefined` (loading / error / not yet fetched).
  - **Failure / loading behavior:**
    - Schema query loading → advisory hidden (the predicate's second conjunct evaluates false).
    - Schema query 404 / error → advisory hidden (silent — the panel renders without it).
    - Schema query unauthorized / cluster unreachable → advisory hidden.
    - Solr engine → advisory hidden (predicate conjunct 3).
    - The advisory is informational only; a hidden advisory **MUST NOT** degrade the panel in any other way.
  - The advisory copy **MUST** be sourced from glossary key `digest.normalizer_advisory` (NEW key, added in this feature's story 4) and read as:
    `"The winning normalizer applies lowercasing, which your field analyzer already does. The loop still found a measurable gain — the duplication is harmless. Production parity is required for the gain to reproduce."`
  - The advisory **MUST NOT** block the digest from rendering, **MUST NOT** gate the "Open PR" button, and **MUST NOT** modify `recommended_config`.
  - The advisory **MUST** be styled as muted helper text (`text-sm text-muted-foreground`), placed above the `<pre>` JSON block.

### FR-7: Frontend enumerated value contract

- Requirement:
  - `ui/src/lib/enums.ts` **MUST** export `NORMALIZER_VALUES: readonly ["none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions"]` with a source-of-truth comment: `// Values must match backend/app/domain/study/normalizers.py NORMALIZER_CHOICES`.
  - `ui/src/lib/enums.ts` **MUST** also export an explicit value-to-glossary-key map (raw wire values contain `+` which is unsafe as a glossary identifier suffix):
    ```ts
    export const NORMALIZER_GLOSSARY_KEYS: Record<typeof NORMALIZER_VALUES[number], GlossaryKey> = {
      "none":                                "search_space.query_normalizer.choice.none",
      "lowercase":                           "search_space.query_normalizer.choice.lowercase",
      "lowercase+trim":                      "search_space.query_normalizer.choice.lowercase_trim",
      "lowercase+trim+expand_contractions":  "search_space.query_normalizer.choice.lowercase_trim_expand_contractions",
    };
    ```
  - **Conditional rendering in `row-categorical.tsx`** (corrects subset-override hazard):
    - The row is generic — used by every Categorical param. Default path renders `param.choices` exactly as declared, unchanged.
    - **When `paramName === "query_normalizer"`:** the row treats `NORMALIZER_VALUES` as the **canonical option universe** (the universal label/glossary source), but the **selectable / submittable set** remains the operator-declared `param.choices` (a subset of `NORMALIZER_VALUES`). Concretely:
      1. Validate at render time that `param.choices ⊆ NORMALIZER_VALUES` — if a stray choice is present (defense-in-depth; FR-2 already enforces this server-side), log a console warning and filter the stray.
      2. Render one `<SelectItem>` per value in `param.choices` (NOT per value in `NORMALIZER_VALUES`), preserving the operator's subset.
      3. Look up the label for each rendered choice via `NORMALIZER_GLOSSARY_KEYS[value]`.
    - A vitest regression test (Story 4) asserts: (a) a non-reserved Categorical param renders its declared `choices` verbatim; (b) `query_normalizer` with `choices = ["none", "lowercase+trim"]` renders exactly two `<SelectItem>` elements with the right values AND the right glossary-sourced labels; (c) the submitted payload contains the two-value subset, not the full four-value universe.
  - User-visible labels for each value live in the glossary under the keys listed above (four new keys). Wire values stay as-is in `<SelectItem value>`; labels render via the glossary key lookup.

### FR-8: Documentation updates

- Requirement:
  - [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) **MUST** be updated with a new sub-section under "Where RelyLoop fits in your relevance pipeline" pointing at this shipped feature.
  - [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) **MUST** include a paragraph describing the pre-render hook contract: "The `render()` implementation is permitted to apply a deterministic pure-function transform to `query_text` before injecting it into the Jinja context, provided the transform is recorded in the trial's `params` JSONB as a Categorical search-space value the operator declared. The `query_normalizer` key is the reserved canonical instance."
  - [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) **MUST** gain a one-paragraph section: "Opting a template into normalizer tuning" with the exact `declared_params` + `search_space.params` diff.
  - [`docs/04_security/llm-data-flow.md`](../../../../04_security/llm-data-flow.md) **MUST NOT** change — no LLM call is introduced.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints.** Existing endpoints affected:

| Method | Path | Affected behavior |
|---|---|---|
| `POST` | `/api/v1/query-templates` | Rejects template bodies that reference `{{ query_normalizer }}` (FR-2). New error code: `RESERVED_PARAM_REFERENCED` (HTTP 400). Accepts templates that DECLARE `query_normalizer` in `declared_params` without referencing it in the body — the `_RESERVED_NONRENDER_PARAMS` exemption in `validate_template_body`. |
| `POST` | `/api/v1/studies` | After `SearchSpace.model_validate` succeeds, the router invokes `validate_normalizer_reservation(space)`. New error codes: `NORMALIZER_CHOICE_INVALID`, `NORMALIZER_PARAM_SHAPE` (HTTP 400). |
| `GET` | `/api/v1/studies/{id}` | Returns the existing study shape; `query_normalizer` rides inside `search_space.params` as a Categorical entry. No shape change. |
| `GET` | `/api/v1/studies/{id}/digest` | Returns the existing digest shape; `query_normalizer` rides inside `recommended_config`. Frontend conditionally renders the advisory (FR-6). |
| `GET` | `/api/v1/proposals/{id}` | Returns the existing shape; `query_normalizer` rides inside `config_diff`. Frontend conditionally renders the "Operator-side requirement" section (FR-5) when the PR opens. |

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code` under `detail`.
- Status codes **MUST** be deterministic per scenario.
- N/A — no auth surface, no cross-tenant anti-enumeration concerns.

### 8.3 Response examples

The only new error responses are at `POST /api/v1/studies`. Both follow the existing envelope from [`backend/app/api/errors.py`](../../../../../backend/app/api/errors.py).

Failure example — `NORMALIZER_CHOICE_INVALID` (HTTP 400):
```json
{
  "detail": {
    "error_code": "NORMALIZER_CHOICE_INVALID",
    "message": "query_normalizer choice 'stem' is not in the allowed set: ['none', 'lowercase', 'lowercase+trim', 'lowercase+trim+expand_contractions']",
    "retryable": false
  }
}
```

Failure example — `NORMALIZER_PARAM_SHAPE` (HTTP 400):
```json
{
  "detail": {
    "error_code": "NORMALIZER_PARAM_SHAPE",
    "message": "query_normalizer must be CategoricalParam (got FloatParam)",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `search_space.params.query_normalizer.choices[*]` (POST body) | `none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions` | `backend/app/domain/study/normalizers.py` (`NORMALIZER_CHOICES: Final[tuple[str, ...]]`) | Create-study modal Categorical row in `ui/src/components/studies/search-space-builder/row-categorical.tsx` consumes `NORMALIZER_VALUES` from `ui/src/lib/enums.ts`. |
| `proposals[*].config_diff.query_normalizer.{from,to}` (GET response) | same four values | same — round-tripped from study trial via `trials.params` | PR-body render in `_render_pr_body_study_backed` consults `_PR_BODY_NORMALIZER_SNIPPETS` keyed on the same allowlist. |
| `studies[*].digest.recommended_config.query_normalizer` (GET response) | same four values | same — round-tripped from study | `digest-panel.tsx` advisory predicate checks against the three non-`none` values. |

User-visible labels (rendered via glossary, not wire-equal — note the sanitized glossary-key suffixes substitute `_` for `+`):

| Wire value | User-visible label | Glossary key |
|---|---|---|
| `none` | "None — pass query through verbatim" | `search_space.query_normalizer.choice.none` |
| `lowercase` | "Lowercase only" | `search_space.query_normalizer.choice.lowercase` |
| `lowercase+trim` | "Lowercase + trim whitespace" | `search_space.query_normalizer.choice.lowercase_trim` |
| `lowercase+trim+expand_contractions` | "Lowercase + trim + expand contractions (English)" | `search_space.query_normalizer.choice.lowercase_trim_expand_contractions` |

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `NORMALIZER_CHOICE_INVALID` | `400` | A `search_space.params.query_normalizer.choices` entry is not in `NORMALIZER_CHOICES`. Surfaced at `POST /api/v1/studies` from `validate_normalizer_reservation` (after `SearchSpace.model_validate` succeeds). |
| `NORMALIZER_PARAM_SHAPE` | `400` | `search_space.params.query_normalizer` is not a `CategoricalParam`. Surfaced at the same endpoint from the same function. |
| `RESERVED_PARAM_REFERENCED` | `400` | A query-template body references `{{ query_normalizer }}` — reserved non-render params are consumed by the adapter and forbidden in template bodies. Surfaced at `POST /api/v1/query-templates` from `validate_template_body` raising `ReservedParamReferenced`. |

The existing `INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`, `UNDECLARED_PARAM_USED`, `DECLARED_PARAM_UNUSED` codes remain unchanged and may also fire on adjacent failure paths.

## 9) Data model and state transitions

### New entities

**None.** The feature introduces no new tables and no new columns.

The `query_normalizer` Categorical value rides inside existing JSONB columns:
- `studies.search_space` — the operator-declared reservation (the choice set).
- `trials.params` — the trial-suggested choice (one of the four values, per trial).
- `digests.recommended_config` ([`backend/app/db/models/digest.py:58`](../../../../../backend/app/db/models/digest.py), `JSONB NOT NULL`) — the winning choice for the study, computed by the digest worker from the best trial's `params`. Rendered into `digest-panel.tsx` via the digests API.
- `proposals.config_diff` ([`backend/app/db/models/proposal.py:64`](../../../../../backend/app/db/models/proposal.py), `JSONB NOT NULL`) — the `{from, to}` change for the proposal, computed at digest time. Rendered into the PR body.

### Modified entities

**None.** No migration ships with this feature.

### Required invariants

- **I-1.** When `search_space.params["query_normalizer"]` is present, it is a `CategoricalParam` whose `choices` is a non-empty subset of `NORMALIZER_CHOICES`. Enforced at `POST /api/v1/studies` (FR-2). No legacy write path is in scope — `query_normalizer` is new; nothing in the DB carries it today.
- **I-2.** Consumption of `params["query_normalizer"]` is **adapter-confined**: only `ElasticAdapter.render` and `SolrAdapter.render` read the value. The orchestrator, trial runner (`backend/workers/trials.py:403`), baseline runner (`backend/workers/baseline.py:194`), and judgment generator (`backend/workers/judgments.py:195`) pass `params` through opaquely. Authoring sites (validator, PR-body renderer, frontend row, glossary, tests, docs) MAY reference the literal `query_normalizer` — the invariant scope is **consumption**, not all references. Audit: a `grep -r "query_normalizer" backend/app/services backend/app/agent backend/workers/trials.py backend/workers/baseline.py backend/workers/judgments.py backend/workers/orchestrator.py` MUST return zero hits beyond pass-through plumbing.
- **I-3.** `_render_pr_body_study_backed` is the only code path that adds the "Operator-side requirement" section. The section is conditional on `"query_normalizer" in config_diff`. `_render_pr_body_manual` is **explicitly excluded** — hand-crafted proposals never carry a normalizer because they don't pass through the loop.
- **I-4.** The Python snippet embedded in the PR body and the runtime `normalize(...)` implementation produce **identical output** over a curated fixture corpus of representative inputs (mix of contraction-bearing and contraction-free strings, mixed case, leading/trailing whitespace, the boundary cases `whatsoever` and `swhat's`). Enforced by `test_normalizers_pr_snippets.py` which (a) `exec()`s the snippet string into a sandboxed namespace, (b) calls both the snippet's `normalize_query` and the production `normalize(..., "lowercase+trim+expand_contractions")`, (c) asserts equality across the corpus. Semantic equality — not byte equality — because the snippet inlines the dictionary literal whereas the runtime imports it.

### State transitions

N/A — no new state machine; rides existing `study.state` and `proposal.status` machines untouched.

### Idempotency/replay behavior

N/A — no event-driven path; the feature is in-band on the synchronous study-creation + trial-runner + PR-worker paths.

### Built-in contraction dictionary (exactly 30 entries)

```
ain't       → is not
aren't      → are not
can't       → cannot
couldn't    → could not
didn't      → did not
doesn't     → does not
don't       → do not
hadn't      → had not
hasn't      → has not
haven't     → have not
he's        → he is
i'd         → i would
i'll        → i will
i'm         → i am
i've        → i have
isn't       → is not
it's        → it is
let's       → let us
shouldn't   → should not
that's      → that is
they're     → they are
they've     → they have
wasn't      → was not
we're       → we are
we've       → we have
weren't     → were not
what's      → what is
won't       → will not
wouldn't    → would not
you're      → you are
```

Notes:
- Encoded in `_CONTRACTIONS` as a frozen `Mapping[str, str]` (e.g., `types.MappingProxyType` wrapping a dict literal).
- Apostrophe is the **ASCII** `'` (U+0027). Smart quotes (`'` U+2019) are NOT matched in MVP2 — operators who pre-normalize smart quotes get the expected behavior; those who don't, don't. Captured as a P3 deferred follow-up in `phase2_idea.md` if needed.
- Word-boundary matching means `"what's"` expands but neither `"whatsoever"` nor `"swhat's"` does.

### Python snippet templates (the strings inlined into PR bodies)

The keys are the four `NORMALIZER_CHOICES` values. The strings are stored in `_PR_BODY_NORMALIZER_SNIPPETS` in `backend/app/domain/study/normalizers.py`:

`none` — no snippet (FR-5 short-circuit).

`lowercase`:
```python
def normalize_query(query_text: str) -> str:
    return query_text.lower()
```

`lowercase+trim`:
```python
def normalize_query(query_text: str) -> str:
    return query_text.lower().strip()
```

`lowercase+trim+expand_contractions`:
```python
import re

_CONTRACTIONS = {
    # ... 30 entries inlined here verbatim — kept in sync with the
    # production _CONTRACTIONS mapping by I-4's enforcement test.
}
_PATTERN = re.compile(
    r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b"
)

def normalize_query(query_text: str) -> str:
    lowered = query_text.lower().strip()
    return _PATTERN.sub(lambda m: _CONTRACTIONS[m.group(1)], lowered)
```

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Operator template injects an attacker-controlled `query_normalizer` value via the create-study API.** Mitigated by FR-2 — values outside `NORMALIZER_CHOICES` are rejected at the Pydantic boundary with `NORMALIZER_CHOICE_INVALID`. No string can reach `normalize()` without passing the allowlist.
  2. **A malformed contraction triggers a ReDoS-style regex blow-up.** Mitigated because `_PATTERN` is built once from a static 30-entry list of `re.escape`-d literals joined by `|`; the resulting regex has linear matching complexity. The build is at import time, not per-call.
  3. **An overlong query string sent to the loop exhausts memory.** Mitigated by the existing upstream `query_text` length cap in `Query` model validation (per `feat_study_lifecycle`); the normalizer adds no allocation beyond `str.lower()` + `str.strip()` + a single regex pass — all O(n) on the bounded input.
  4. **The Python snippet embedded in the PR body is misleading because it drifts from the runtime implementation.** Mitigated by I-4 — a unit test loads both and asserts equality.
  5. **An advisory false-positive misleads the operator into believing their analyzer already does the right thing when it doesn't.** Mitigated by phrasing the advisory as informational ("the duplication is harmless") rather than prescriptive, and by including the "Production parity is required" sentence so the operator never concludes from the advisory that no production change is needed.
- **Controls:**
  - Backend allowlist enforcement at the API boundary.
  - I-4 semantic-equivalence test (curated fixture corpus) between the runtime `normalize(...)` and the PR-body snippet's `normalize_query(...)`.
  - AC-5's separate byte-equality assertion verifies that `_render_pr_body_study_backed` embeds the selected `_PR_BODY_NORMALIZER_SNIPPETS[choice]` string verbatim in the PR body — distinct from I-4's semantic check.
  - Glossary-grounded advisory copy (no inline string in `digest-panel.tsx`).
- **Secrets/key handling:** N/A — no secrets, no keys.
- **Auditability:** The chosen normalizer is recorded in `trials.params` (per-trial) and `proposals.config_diff` (per-proposal). The PR body in GitHub is the human-readable record of the merged decision.
- **Data retention/deletion/export impact:** None — no new persisted state beyond what already lands in the JSONB columns.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Two surfaces:
  1. **Create-study modal → Step 4 (search-space builder).** A template that declares `query_normalizer` causes the modal to render a Categorical row labeled "Query normalizer" with four choices (per FR-7). The row sits in the existing parameter list, alphabetical with the others; no special placement.
  2. **Study-detail page → digest panel → recommended config block.** When the study is complete and `recommended_config.query_normalizer` is one of the three normalizing choices, the advisory line renders above the JSON block (per FR-6).
  3. **Proposal-detail page → existing PR body preview.** The "Operator-side requirement" section renders in the markdown preview after `## Config diff` (per FR-5).
- **Labeling taxonomy:**
  - Categorical row label: "Query normalizer" (sentence case, matches "Title boost", "Min should match", etc.).
  - Choice labels: per the glossary table in §8.4.
  - Digest advisory line: rendered text per FR-6.
  - PR section title: `## Operator-side requirement` (exact, per FR-5).
- **Content hierarchy:**
  - Create-study modal: the row sits in the search-space parameter list (no priority elevation).
  - Digest panel: advisory line above the recommended-config JSON; both above the "Open PR" button.
  - Proposal: "Operator-side requirement" section between `## Config diff` and `## Suggested follow-ups`.
- **Progressive disclosure:** None required. The Categorical row is hidden entirely when the template does not declare `query_normalizer`. The digest advisory is hidden entirely when the choice is `none` or the engine is Solr. The PR section is hidden entirely when `config_diff` does not carry the key.
- **Relationship to existing pages:** All three surfaces are extensions to existing pages; no new route, no new tab, no new modal.

### Tooltips and contextual help

All glossary entries below are NEW (do not exist today — verified via `grep` on `ui/src/lib/glossary.ts`). They land in Story 4.

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| "Query normalizer" Categorical row label | "Apply a lightweight transform to the user's query string before the engine sees it. Off by default; the loop will pick the best transform when this row is present." | hover info icon | top | `search_space.query_normalizer.row` (NEW) |
| Choice `none` label | "Pass the query through verbatim. The current default for every template." | hover info icon | top | `search_space.query_normalizer.choice.none` (NEW) |
| Choice `lowercase` label | "Apply `query.lower()`. Safe; usually redundant with a standard analyzer but rarely harmful." | hover info icon | top | `search_space.query_normalizer.choice.lowercase` (NEW) |
| Choice `lowercase+trim` label | "Apply `query.lower().strip()`. Strips leading/trailing whitespace and case-folds." | hover info icon | top | `search_space.query_normalizer.choice.lowercase_trim` (NEW, sanitized — `+` is unsafe in glossary identifiers; `NORMALIZER_GLOSSARY_KEYS` map in `ui/src/lib/enums.ts` resolves the wire value to this key) |
| Choice `lowercase+trim+expand_contractions` label | "Lowercase, trim, then expand 30 common English contractions (e.g., \"what's\" → \"what is\"). English-only." | hover info icon | top | `search_space.query_normalizer.choice.lowercase_trim_expand_contractions` (NEW, sanitized — same resolution mechanism) |
| Digest advisory line (FR-6) | "The winning normalizer applies lowercasing, which your field analyzer already does. The loop still found a measurable gain — the duplication is harmless. Production parity is required for the gain to reproduce." (the FR-6 canonical copy; the single `digest.normalizer_advisory` key serves both the inline render AND the tooltip — they share text) | hover the line's info icon | top | `digest.normalizer_advisory` (NEW) |

All six new keys ship in Story 4 (frontend + glossary). The lint guards in `ui/src/__tests__/lib/glossary.test.ts` validate length bounds.

### Operator adoption mechanism

Templates in RelyLoop are **immutable after creation** — there is no `PUT /api/v1/query-templates/{id}` or PATCH endpoint (verified: `backend/app/api/v1/query_templates.py` exposes POST/GET only). To opt in to normalizer tuning, the operator creates a **new template version** via `POST /api/v1/query-templates` whose `declared_params` includes `"query_normalizer": "string"` and whose body **MUST NOT** reference `{{ query_normalizer }}` directly — the adapter consumes the normalizer; references in the template body raise `RESERVED_PARAM_REFERENCED` (FR-2 + §8.5). The `_RESERVED_NONRENDER_PARAMS` exemption permits declared-but-unreferenced; references remain forbidden.

In MVP2 there is **no in-UI template builder**, so the operator either:
- Calls `POST /api/v1/query-templates` directly (curl / Postman / agent chat tool), OR
- Adds the new template to the demo-seed catalog at install time (out of scope for this feature; operators who want a pre-seeded normalizer-aware template author it themselves and place it in `samples/`).

The chat-agent tool family `backend/app/agent/tools/templates/` exposes a `create_query_template` tool — operators conversing with the agent can ask "register a new template with `query_normalizer` declared" and the agent invokes the same endpoint. No new agent tool ships in this feature; the existing one handles the new declared-param.

The runbook update per FR-8 (`docs/03_runbooks/local-dev.md`) documents the exact `POST /api/v1/query-templates` payload an operator copies.

### Primary flows

1. **Operator adopts normalizer tuning on their template.** Operator calls `POST /api/v1/query-templates` (or asks the chat agent to do it) with `declared_params` including `"query_normalizer": "string"` and a body that **does NOT reference `{{ query_normalizer }}`** (forbidden — would raise `RESERVED_PARAM_REFERENCED`). They create a study via the create-study modal selecting this new template; the modal's search-space builder shows a Categorical row for `query_normalizer` whose available options are bounded by `NORMALIZER_VALUES` AND the template's declared `choices` subset (operator-restricted subsets are honored — see FR-7). They submit via `POST /api/v1/studies`. `SearchSpace.model_validate` + `validate_normalizer_reservation` accept it.
2. **Loop runs.** Optuna's TPE sampler suggests one of the declared `choices` per trial (the operator-declared subset of `NORMALIZER_CHOICES` — three or four values, depending on whether `"none"` is included). The orchestrator passes `snapshot.params["query_normalizer"]` to `adapter.render`. The adapter normalizes `query_text` accordingly, issues the search batch, records the trial.
3. **Study completes; digest renders.** `digest.recommended_config["query_normalizer"]` = `"lowercase+trim+expand_contractions"` (winning choice). The advisory line renders if the field analyzer overlap predicate (FR-6) holds.
4. **Operator opens the proposal PR.** `_render_pr_body_study_backed` includes the "Operator-side requirement" section with the chosen normalizer + Python snippet. The operator copies the snippet into their query-serving layer, deploys it, merges the PR. Production parity achieved.

### Edge/error flows

- **Operator submits `query_normalizer` choices including `"stem"`** → `POST /api/v1/studies` returns 400 `NORMALIZER_CHOICE_INVALID`.
- **Operator submits `query_normalizer` as a `FloatParam`** → 400 `NORMALIZER_PARAM_SHAPE`.
- **Template declares `query_normalizer` but search-space omits it** → existing `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400) fires.
- **Template does not declare `query_normalizer` but search-space includes it** → existing `SEARCH_SPACE_UNKNOWN_PARAM` (400) fires.
- **Trial-time bad value (shouldn't happen given FR-2, but defense-in-depth)** → `adapter.render` raises `ValueError`; the trial fails per the existing render-failure path in `trials.py`. Study continues with remaining trials.
- **Winning choice is `none`** → PR-body section still renders, snippet omitted, copy reads "No production-side change is required" (per FR-5).
- **Engine is Solr** → digest advisory is hidden (no analyzer info in `FieldSpec`); PR section still renders.
- **Hand-crafted (manual) proposal** → no PR section (manual proposals don't pass through the loop; `_render_pr_body_manual` is not modified).

## 12) Given/When/Then acceptance criteria

### AC-1: Normalizer library — pure functions

- Given the new module `backend/app/domain/study/normalizers.py`
- When the test imports it and calls `normalize("  Hello World  ", "lowercase+trim")`
- Then the return value is `"hello world"` (no leading/trailing whitespace, lowercased)
- Example values:
  - Input: `normalize("WHAT'S the deal?", "lowercase+trim+expand_contractions")` → Expected: `"what is the deal?"`
  - Input: `normalize("whatsoever", "lowercase+trim+expand_contractions")` → Expected: `"whatsoever"` (word-boundary guard)
  - Input: `normalize("anything", "stem")` → Expected: raises `ValueError("unknown normalizer: stem")`

### AC-2: Router validates `query_normalizer` reservation via `validate_normalizer_reservation`

- Given a `POST /api/v1/studies` payload where `search_space.params.query_normalizer = {"type": "categorical", "choices": ["none", "stem"]}`
- When the router first invokes `SearchSpace.model_validate(...)` (which succeeds — Pydantic doesn't enforce the reservation) and then invokes `validate_normalizer_reservation(space)`
- Then the response is HTTP 400 with body `{"detail": {"error_code": "NORMALIZER_CHOICE_INVALID", ...}}`
- Example values:
  - Input: `choices = ["lowercase", "stem"]` → Expected: 400 `NORMALIZER_CHOICE_INVALID`, message includes `'stem'`
  - Input: `choices = ["lowercase", "lowercase+trim"]` → Expected: 201 study created
  - Input: `{"type": "float", "low": 0.1, "high": 1.0}` for `query_normalizer` → Expected: 400 `NORMALIZER_PARAM_SHAPE`

### AC-3: `ElasticAdapter.render` applies the chosen normalizer

- Given a template body `{"query": {"match": {"title": "{{ query_text }}"}}}`, declared_params `{"query_normalizer": "string"}`, params `{"query_normalizer": "lowercase+trim+expand_contractions"}`, query_text `"What's the BEST policy?"`
- When `ElasticAdapter.render(template, params, query_text)` is called
- Then the returned `NativeQuery.body["query"]["match"]["title"]` equals `"what is the best policy?"`
- Then the original `params` dict passed by the caller is unmutated (still contains `query_normalizer`)

### AC-4: `SolrAdapter.render` applies the chosen normalizer

- Given a Solr template body that renders to `{"defType": "edismax", "q": "{{ query_text }}", "qf": "title"}`, params `{"query_normalizer": "lowercase"}`, query_text `"HELLO"`
- When `SolrAdapter.render(template, params, query_text)` is called
- Then the returned `NativeQuery.body["q"]` equals `"hello"`

### AC-5: PR body — section appears when `query_normalizer` is in `config_diff`

- Given a proposal whose `config_diff` includes `{"query_normalizer": {"from": "none", "to": "lowercase+trim+expand_contractions"}}` and a non-trivial `metric_delta`
- When `_render_pr_body_study_backed` is invoked
- Then the markdown output contains the literal line `## Operator-side requirement`
- Then the markdown contains the line `**Chosen normalizer:** \`lowercase+trim+expand_contractions\``
- Then the markdown contains a fenced Python code block whose content is byte-equal to `_PR_BODY_NORMALIZER_SNIPPETS["lowercase+trim+expand_contractions"]`

### AC-6: PR body — section omitted when `query_normalizer` is absent

- Given a proposal whose `config_diff` does NOT include `query_normalizer`
- When `_render_pr_body_study_backed` is invoked
- Then the markdown output does NOT contain `## Operator-side requirement`

### AC-7: PR body — `none` choice renders without a snippet

- Given a proposal whose `config_diff` includes `{"query_normalizer": {"from": "lowercase", "to": "none"}}`
- When `_render_pr_body_study_backed` is invoked
- Then the markdown output contains `## Operator-side requirement`
- Then the markdown contains the literal line `**Chosen normalizer:** \`none\`. No production-side change is required — the loop confirmed the un-normalized query already wins.`
- Then the markdown does NOT contain a fenced Python code block in that section

### AC-8: Digest panel advisory — ES analyzer overlap predicate

- Given a study with `recommended_config.query_normalizer = "lowercase+trim"`, engine = `elasticsearch`, and target schema containing at least one field with `analyzer = "standard"`
- When the study-detail page renders the digest panel
- Then the advisory line is visible above the `recommended_config` JSON block
- Then the line's text matches glossary key `digest.normalizer_advisory`

### AC-9: Digest panel advisory — hidden for Solr

- Given a study with `recommended_config.query_normalizer = "lowercase"` and engine = `solr`
- When the study-detail page renders the digest panel
- Then the advisory line is NOT visible

### AC-10: Digest panel advisory — hidden for `none`

- Given a study with `recommended_config.query_normalizer = "none"` and engine = `elasticsearch`
- When the study-detail page renders the digest panel
- Then the advisory line is NOT visible (the predicate's first conjunct fails)

### AC-11: Frontend enum source-of-truth

- Given the test suite at `ui/src/__tests__/components/common/form-select-discipline.test.tsx`
- When it scans `row-categorical.tsx` for `<SelectItem value="...">` patterns
- Then no inline literal matches the four `NORMALIZER_VALUES` (all are sourced via `.map()` from the import)
- Given `ui/src/lib/enums.ts`
- Then `NORMALIZER_VALUES` exports the four values in the order `["none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions"]`
- Then the source-of-truth comment is present and points at `backend/app/domain/study/normalizers.py NORMALIZER_CHOICES`

### AC-12: Snippet round-trip — runtime ≡ embedded (semantic equality)

- Given the unit test asserting I-4 (`test_normalizers_pr_snippets.py`)
- When it `exec()`s `_PR_BODY_NORMALIZER_SNIPPETS["lowercase+trim+expand_contractions"]` into a sandboxed namespace AND calls `normalize(..., "lowercase+trim+expand_contractions")` from the production module
- Then both functions return identical output for each input in a curated 10-element fixture corpus including: mixed-case strings, leading/trailing whitespace, ASCII-apostrophe contractions, the word-boundary cases `"whatsoever"` and `"swhat's"`, the no-op input `""`, and a string with no contractions or whitespace
- Then the same equality holds for the `lowercase` and `lowercase+trim` snippets vs their runtime counterparts (driven by a parametrized test over `NORMALIZER_CHOICES`)

### AC-13: End-to-end — operator runs a normalizer-tuning study against the live stack

- **Scope:** AC-13 verifies the **UI-observable** end-to-end flow. Native-query normalization correctness at the engine boundary is covered by AC-3 / AC-4 (adapter unit tests) plus the integration test `test_trial_runner_normalizer.py` (per §14) which inspects the rendered query body. AC-13 does NOT introspect engine request logs.
- Given a fresh stack (`make up`), a registered ES cluster, and a template with `declared_params = {"query_normalizer": "string", ...other_params}` (seeded via `POST /api/v1/query-templates` from the test setup)
- When the operator creates a study via the create-study modal with the four-choice Categorical row populated
- When the orchestrator runs ≥ 4 trials
- Then the study-detail page reflects each trial's chosen `query_normalizer` value in the trials table's `params` column
- Then the digest renders with the advisory line if the analyzer-overlap predicate holds (target field with `analyzer="standard"`)
- Then opening the proposal PR (against the test config repo) produces a body containing the `## Operator-side requirement` section AND the Python snippet AND the literal `**Chosen normalizer:**` line
- Test path: `ui/tests/e2e/query-normalization.spec.ts` (NEW; real-backend per CLAUDE.md "E2E Testing Rules" — setup via API helpers, assertions via `page` object only, no `page.route()` mocking)

## 13) Non-functional requirements

- **Performance:** The hook adds one `str.lower()` + one `str.strip()` + one regex pass over a bounded `query_text` (cap enforced upstream). Worst-case overhead per trial query is sub-microsecond; immeasurable against the engine round-trip. No SLA impact.
- **Reliability:** No new failure mode at runtime — `normalize` is total over allowlisted inputs (validated at study-create time). The only way a bad value reaches `render` at trial time is via direct DB mutation, which is out of threat scope.
- **Operability:** No new metrics, no new alerts. The chosen normalizer is observable through existing trial/proposal records.
- **Accessibility/usability:** All six new glossary entries pass the existing length / no-jargon lint at `ui/src/__tests__/lib/glossary.test.ts`. The Categorical row uses the standard `<Select>` primitive, inheriting its keyboard/screen-reader support.

## 14) Test strategy requirements

Per CLAUDE.md "Testing Conventions" (every layer touched needs coverage):

- **Unit tests** (`backend/tests/unit/`):
  - `test_normalizers.py` (NEW) — `normalize` over the Cartesian product of {4 choices} × {bank of representative inputs including mixed-case, leading/trailing whitespace, contractions, `"whatsoever"`, empty string, single-char, ASCII vs smart quotes}. Covers AC-1.
  - `test_template_defaults_normalizer.py` (NEW) — `compute_default_params` with `declared_params = {"query_normalizer": "string", "title_boost": "float"}` returns `{"query_normalizer": "none", "title_boost": 1.0}` (NOT `{"query_normalizer": "", ...}`). Regression guard for the FR-1 extension. Plus parity case for the rich-form declaration.
  - `test_template_validator_reserved_param.py` (NEW) — (a) body without `{{ query_normalizer }}` + declared_params containing it → parses cleanly (no `DeclaredParamUnused`); (b) body referencing `{{ query_normalizer }}` → raises `ReservedParamReferenced`. Covers FR-2's template-validator extension.
  - `test_normalizers_pr_snippets.py` (NEW) — I-4 byte-equality between `_PR_BODY_NORMALIZER_SNIPPETS["lowercase+trim+expand_contractions"]` semantics and runtime `normalize`. Covers AC-12.
  - `test_search_space_normalizer_reservation.py` (NEW) — constructs a `SearchSpace` via `SearchSpace.model_validate` (which always succeeds, as `model_validate` does NOT enforce the reservation) and then calls `validate_normalizer_reservation` directly over {valid subset; invalid choice; wrong param shape}. Asserts `NormalizerChoiceInvalidError` / `NormalizerParamShapeError` raised on the bad cases and clean return on the good case. The contract test (`test_studies_normalizer_reservation_contract.py`) covers the router envelope mapping.
  - `test_elastic_render_normalizer.py` (NEW) — `ElasticAdapter.render` with and without `query_normalizer` in params; assertion on rendered query body AND immutability of caller's `params` dict. Covers AC-3.
  - `test_solr_render_normalizer.py` (NEW) — same shape for `SolrAdapter.render`. Covers AC-4.
  - `test_git_pr_body_normalizer.py` (NEW) — `_render_pr_body_study_backed` over {key absent → no section; key=`none` → no-snippet section; key=other → section + snippet}. Covers AC-5, AC-6, AC-7.
- **Integration tests** (`backend/tests/integration/`):
  - `test_trial_runner_normalizer.py` (NEW) — seed a template + study with the four-choice reservation, run the trial runner against the stack's mocked ES (existing fixture pattern in `test_trials_*.py`), assert each trial's `params` JSONB records a value from `NORMALIZER_CHOICES` and each native query body reflects the normalization. Covers I-2 invariant.
- **Contract tests** (`backend/tests/contract/`):
  - `test_studies_normalizer_reservation_contract.py` (NEW) — `POST /api/v1/studies` returns the canonical envelope for `NORMALIZER_CHOICE_INVALID` and `NORMALIZER_PARAM_SHAPE`. Verifies the error-shape match against `error_envelope()` helper.
- **E2E tests** (`ui/tests/e2e/`):
  - `query-normalization.spec.ts` (NEW, real-backend) — Covers AC-13. Setup via API helpers (create cluster, create template with `query_normalizer` declared, create query set, generate judgments); UI interaction via `page` (open create-study modal, populate the four-choice row, submit, wait for trials to complete, open digest panel, assert advisory line visibility, open the proposal preview, assert the "Operator-side requirement" section). No `page.route()` mocking.
- **Frontend vitest** (`ui/src/__tests__/`):
  - `digest-panel.normalizer-advisory.test.tsx` (NEW) — Covers AC-8, AC-9, AC-10 over rendered components with mocked digest props and schema props.
  - `row-categorical.normalizer-source-of-truth.test.tsx` (extension to existing form-select-discipline.test.tsx) — Covers AC-11.

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` — Add a sub-section under "Where RelyLoop fits in your relevance pipeline" titled "Normalizer tuning (MVP2)" linking the implemented feature.
- `docs/01_architecture/adapters.md` — Add a paragraph in the `SearchAdapter.render` section describing the `query_normalizer` pre-render hook contract (per FR-8).
- `docs/02_product/` — No update; the existing MVP1 user stories cover study creation + digest review; no new persona-level capability shifts.
- `docs/03_runbooks/local-dev.md` — Add a section "Opting a template into normalizer tuning" with the `declared_params` + `search_space.params` diff (per FR-8).
- `docs/04_security/` — No update; no new threat surface, no new data flow.
- `docs/05_quality/testing.md` — No update; existing convention covers the new test layers.
- `state.md` — Add the merge one-liner; archive longer narrative to `state_history.md`.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — the feature is gated by template adoption (the operator opts in by declaring `query_normalizer` in the template). No global flag.
- **Migration/backfill expectations:** None — no schema change.
- **Operational readiness gates:** None new — the loop runs on the same trial-runner / orchestrator path. No new metrics, no new alerts.
- **Release gate:**
  - All AC-* pass in CI (unit + integration + contract + 1 new E2E).
  - 80% backend coverage gate green.
  - Frontend ESLint + tsc + vitest + Next build green.
  - Glossary length lints green.
  - Cross-model GPT-5.5 spec review converged.
  - Adversarial run: `grep -r "query_normalizer" backend/app/services backend/app/agent backend/workers/trials.py backend/workers/baseline.py backend/workers/judgments.py backend/workers/orchestrator.py` returns zero non-pass-through hits (I-2 consumption-only invariant).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-12 | Story 1: normalizer library + snippet dict | `test_normalizers.py`, `test_normalizers_pr_snippets.py` | — |
| FR-2 | AC-2 | Story 2: `SearchSpace` reservation validator | `test_search_space_normalizer_reservation.py`, `test_studies_normalizer_reservation_contract.py` | — |
| FR-3 | AC-3, I-2 | Story 3: `ElasticAdapter.render` hook | `test_elastic_render_normalizer.py`, `test_trial_runner_normalizer.py` | `docs/01_architecture/adapters.md` |
| FR-4 | AC-4 | Story 3: `SolrAdapter.render` hook | `test_solr_render_normalizer.py` | `docs/01_architecture/adapters.md` |
| FR-5 | AC-5, AC-6, AC-7, I-3, I-4 | Story 5: PR-body section | `test_git_pr_body_normalizer.py` | — |
| FR-6 | AC-8, AC-9, AC-10 | Story 4: digest advisory | `digest-panel.normalizer-advisory.test.tsx`, E2E | — |
| FR-7 | AC-11 | Story 4: frontend enum + glossary | `row-categorical.normalizer-source-of-truth.test.tsx`, `glossary.test.ts` | — |
| FR-8 | — | Story 6: docs sweep | — | `optimization.md`, `adapters.md`, `local-dev.md` |
| — | AC-13 | Story 7: real-backend E2E | `query-normalization.spec.ts` | — |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-13) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates per FR-8 are merged.
- [ ] Rollout gates from §16 are satisfied.
- [ ] No open questions remain in §19.
- [ ] `phase2_idea.md` and `phase3_idea.md` exist alongside this spec.
- [ ] `state.md` updated with the merge one-liner.

## 19) Open questions and decision log

### Open questions

_None._ All four idea-stage open questions are resolved below.

### Decision log

- **2026-05-31 — D-1: Prod-reproducibility hand-off.** **Option (b) — documentation hand-off in the proposal body.** The proposal's PR body gets a new "Operator-side requirement" section naming the winning normalizer and embedding a copy-pasteable Python snippet (FR-5). The merge contract is: "RelyLoop measured X gain against this normalizer; you must replicate it in your query layer for production parity." Option (a) (apply-path carries a structured normalizer declaration) is deferred to `phase3_idea.md` — it materially expands apply-path scope; revisit if MVP2 adoption shows the manual replication is frictionful. Option (c) (engine-applied only) is rejected — it would exclude contraction expansion, which is the operator's headline ask. **Rationale for accepting option (b) as adequate:** the apply-path's existing posture is "the PR description is the merge contract"; this feature extends that posture rather than altering it. Operators already read PRs end-to-end before merging; a new mandatory section is the lowest-friction integration with their existing workflow.

- **2026-05-31 — D-2: Normalizer library scope.** Ship four built-in normalizers: `none`, `lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions`. English-only, 30-entry static contraction dictionary baked into `backend/app/domain/study/normalizers.py`. Spell-correction is out of scope (corpus-aware, crosses analyzer boundary). Operator-supplied dictionaries deferred to `phase2_idea.md`.

- **2026-05-31 — D-3: Analyzer-redundancy advisory.** Non-blocking advisory in `digest-panel.tsx` only — no capability-probe extension, no `get_schema` change. Predicate uses the `FieldSpec.analyzer` data the existing schema endpoint already returns. **ES/OpenSearch only in MVP2.** Solr advisory deferred until `SolrAdapter.get_schema` populates `FieldSpec.analyzer`.

- **2026-05-31 — D-4: Search-space shape.** `CategoricalParam` with named bundles. Zero schema change. A typed sub-object (ordered list of normalization steps) is more expressive but introduces a new search-space discriminator and forces a migration; deferred to `phase2_idea.md` if the four built-in bundles prove insufficient.

- **2026-05-31 — D-5: Hook location.** Inside `ElasticAdapter.render` and `SolrAdapter.render`. Caller-side (`trials.py`, `baseline.py`, `judgments.py`) hook rejected because it triples the implementation site and bypasses the adapter Protocol's intent (engine-specific behavior, including any pre-engine transform, lives in the adapter).

- **2026-05-31 — D-6: Snippet language scope.** Python only for MVP2. JS/TypeScript snippet deferred to `phase2_idea.md`. Rationale: the snippet is short; operators in JS land translate trivially. Supporting two languages doubles the test surface and risks drift between the runtime implementation and a non-runtime reference.

- **2026-05-31 — D-7: Smart-quote handling.** ASCII apostrophe only in MVP2. Smart-quote contractions are not expanded. Captured as a P3 deferral in `phase2_idea.md` if needed.

- **2026-05-31 — D-8: Implicit-params extension.** `query_normalizer` is **not** added to `_IMPLICIT_PARAMS`. Adoption is per-template via `declared_params` opt-in. Adding it to the implicit set would break the opt-in invariant.
