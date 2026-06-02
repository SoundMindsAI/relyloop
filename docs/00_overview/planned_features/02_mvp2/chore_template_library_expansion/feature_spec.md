# Feature Specification — Curated query-template library + per-engine tunable-params cheatsheets

**Date:** 2026-06-02
**Status:** Approved
**Owners:** Relevance Engineering (Product), Search Platform (Engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) §"Cross-engine parameter naming"
- [`samples/templates/README.md`](../../../../../samples/templates/README.md)
- [`docs/06_vendor_docs/README.md`](../../../../06_vendor_docs/README.md)

---

## 1) Purpose

- **Problem:** RelyLoop ships only **lexical** demo query templates (`samples/templates/product_search.j2` for ES/OpenSearch + three Solr `defType` variants under `samples/templates/solr/`). A relevance engineer who wants to tune function-score decay, kNN, hybrid RRF, or phrase-rescore parameters must hand-write Jinja from scratch, and the per-engine native syntax + valid ranges live only in scattered vendor docs. The "tune any parameter" pitch is technically true but practically gated behind a research project per new tuning surface.
- **Outcome:** A curated, version-grounded **template library** of **6 runnable templates** (4 ES/OpenSearch: basic multi_match, function-score decay, bool-boosted, phrase rescore; 2 Solr: edismax basic, boost decay) — each with declared params, a README "when to use," and a checked-in starter search space — plus **two vector/hybrid reference snippets** (kNN, hybrid RRF) documented in the cheatsheets (not runnable today because the trial-runner render path injects no query vector); plus **three per-engine tunable-params cheatsheets** (`elasticsearch-`, `opensearch-`, `solr-tunable-params.md`) that enumerate each knob's native name, unified name, valid range, "when to tune," and caveats. An operator can pick a runnable template close to their need and tune it instead of authoring DSL blind.
- **Non-goal:** This feature does NOT add new tunable parameters to the adapters, does NOT add a `query_templates` schema column, does NOT auto-seed the new templates into demo installs, and does NOT build a Solr dense-vector / hybrid template (Solr's vector surface is owned by a separate future effort). It is **content + docs + render-validation tests**, with at most a small glossary "Learn more" link.

## 2) Current state audit

### Existing implementations

- `samples/templates/product_search.j2` — ES/OpenSearch `multi_match` demo template; 3 flat `*_boost` float params; `tie_breaker`/`fuzziness` hard-coded. Renders to a raw ES query body.
- `samples/templates/solr/products_edismax.j2`, `products_dismax.j2`, `products_lucene.j2` — Solr demo templates added by `infra_adapter_solr` (shipped 2026-05-31). Render to a **flat Solr request-parameter dict**.
- `samples/templates/README.md` — authoring rules: one `.j2` per template; strict-undefined; JSON output; no attribute access (flat params only); ES vs Solr render-shape difference; `<engine>/` subdir convention.
- `backend/app/db/models/query_template.py` — `query_templates` ORM: `id`, `name`, `engine_type` (Text), `body` (Jinja source), `declared_params` (JSONB `{name: type/range hint}`), `version`, `parent_id`, `created_at`. **No `description` column.** (Model docstring still says `elasticsearch | opensearch` only — stale vs `SUPPORTED_ENGINE_TYPES`; not this feature's concern, see §3 Out of scope.)
- `backend/app/adapters/registry.py:27` — `SUPPORTED_ENGINE_TYPES = frozenset({"elasticsearch", "opensearch", "solr"})` — the canonical engine allowlist.
- `backend/app/adapters/elastic.py:521 render()` — renders Jinja body to a JSON dict, returns it as the **raw native query body** passed to `_msearch`. No unified-param pivot. ES/OS template authors write native DSL directly.
- `backend/app/adapters/solr.py render()` — renders to a flat Solr param dict mixing native + unified-pivot keys (`field_boosts`→`qf`, `boost_fn`→`bf`/`boost`, `rerank_model`→`rq={!ltr ...}`).
- `backend/app/api/v1/query_templates.py` — `query_templates` CRUD router (`POST/GET /api/v1/query-templates`). Operators register templates here.
- `ui/src/components/studies/create-study-modal.tsx:383` — Step 3 picker calls `useTemplates({ engine_type: selectedCluster?.engine_type })`; the dropdown label is "Query template (filtered by engine)". Renders template name/version only — no description surfaced.
- `ui/src/lib/glossary.ts` — glossary with a `study.search_space` entry (shipped via `feat_create_study_search_space_builder`). InfoTooltip reads `short`; the builder uses the longer form.
- `docs/06_vendor_docs/` — exists with `README.md` index + `solr-9/`, `solr-10/` (Solr ref-guide asciidoc source), `relevance-tools/`. README "Coming with later features" reserves `elasticsearch-9x.md` / `opensearch-2x.md` (version-quirk notes — a different doc kind from tunable-params cheatsheets).
- `backend/tests/unit/adapters/test_solr_render.py` — existing render-validation unit-test harness for Solr templates.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `docs/06_vendor_docs/README.md` index table | (no tunable-params rows) | add 3 rows for `*-tunable-params.md` |
| `samples/templates/README.md` | (lexical-only layout) | extend layout block + author rules for the new shapes |
| `docs/08_guides/tutorial-first-study.md` | (no "Where to go next") | add section linking library + cheatsheets |
| `ui/src/lib/glossary.ts` `study.search_space` | (no Learn-more link) | add cheatsheet "Learn more" link (only if glossary supports a link field — see FR-7 fork) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/adapters/test_solr_render.py` | Solr render assertions | 1 file | add cases for new Solr-subdir templates |
| `samples/templates/*` (no direct test today) | render validation | — | add new per-template render-validation unit tests |

### Existing behaviors affected by scope change

- Step-3 template picker: Current — shows name/version, engine-filtered. New — MAY show a one-line summary IF the description is plumbable without a migration (FR-7 fork). Decision needed: yes — locked in §19.
- Demo seeding: Current — `seed_meaningful_demos.py` builds templates from inline bodies; `demo_seeding.py:1248` reads only `product_search.j2`. New — **unchanged** (locked: no auto-seed). Decision needed: no.

---

## 3) Scope

### In scope

- A curated set of **runnable** query templates under `samples/templates/` (ES/OS at top level; Solr variants under `samples/templates/solr/`) covering: basic lexical (new shape alongside the unchanged `product_search.j2`), function-score decay, bool-boosted, phrase rescore (ES/OS) + edismax basic, boost decay (Solr). Each with declared-param documentation + a checked-in `.search_space.json` starter.
- kNN + hybrid-RRF documented as engine-correct **reference snippets** in the ES + OpenSearch cheatsheets (FR-1b) — not runnable templates (no query-vector injection in the render path).
- A per-template README section (in the directory README, not a file-per-template — see §19) describing when to use it, expected metric behavior, and caveats.
- Three per-engine tunable-params cheatsheets in `docs/06_vendor_docs/`.
- Render-validation unit tests for every new template.
- Tutorial "Where to go next" section + vendor-docs README index rows.
- A glossary "Learn more" cheatsheet link (conditional — FR-7).

### Out of scope

- Adding tunable parameters to the adapters (the unified vocabulary is fixed at 8 in adapters.md).
- Any `query_templates` schema/migration change.
- Auto-seeding the library into demo/tutorial installs.
- A Solr kNN / hybrid-vector template (Solr's dense-vector + hybrid surface is materially different; owned by a separate future effort).
- Fixing the stale `query_template.py` model docstring (`elasticsearch | opensearch`) or the `list_templates` agent tool's `engine_type` Literal that omits `solr` — both are pre-existing source-code drift outside this content/docs chore. Captured as a sibling observation in §19, not patched here (this chore touches no source under `backend/app/`).
- LTR model training or upload.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints; verified in `backend/app/api/v1/`.
- **Router for template registration:** `backend/app/api/v1/query_templates.py` (existing — this feature adds NO new endpoint).
- **HTTP methods:** N/A — no new endpoints.
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md` (unchanged; this feature adds no error codes).
- **Auth error shape:** N/A — single-tenant, no auth surface (MVP2).

### Phase boundaries

Single phase. All in-scope work ships together. No deferred phases (the FR-7 inline-summary UI is a conditional within Phase 1, not a separate phase — if it can't ship without a migration, it is dropped, not deferred to a phase 2).

## 4) Product principles and constraints

- **Content fidelity over breadth.** Every cheatsheet entry MUST cite the engine's own reference docs (for Solr, the checked-in `docs/06_vendor_docs/solr-9|10/` asciidoc source; for ES/OpenSearch, the upstream URL + access date per the vendor-docs README convention). A wrong range that gets cited as canonical is worse than a missing entry.
- **Respect the two render contracts.** ES/OS templates render to raw native DSL; Solr templates render to a flat param dict. A single `.j2` cannot serve all three engines for non-trivial shapes.
- **Flat params only.** The Jinja sandbox forbids attribute access; every declared param is a flat name (`knn_num_candidates`, not `knn.num_candidates`). `field_boosts` is the one nested-dict the adapters already flatten.
- **No new tuning surface.** Templates expose only params the adapters already render (native DSL for ES/OS; the documented Solr pivot keys + native keys for Solr).
- **Three engines only.** ES, OpenSearch, Apache Solr. (RRF / Reciprocal Rank Fusion is an ES/OpenSearch ranking technique, unrelated to any removed product.)

### Anti-patterns

- **Do not** ship one cross-engine `.j2` per shape — because ES/OS and Solr have structurally different render outputs; a shared template would render invalid DSL on at least one engine.
- **Do not** auto-seed the library into `seed_meaningful_demos.py` — because it would clutter the tutorial's Step-3 picker and inflate the seed script; templates are files-on-disk registered on demand.
- **Do not** add a `description` column to `query_templates` — because this chore is explicitly migration-free; the inline-summary UI is conditional on plumbing the README content without a schema change.
- **Do not** invent tunable params not in the adapter's render path — because `StrictUndefined` will raise `UndefinedError` at render time, or the engine will reject the DSL.
- **Do not** use nested/dotted param names (`knn.k`) — because the Jinja sandbox forbids attribute access and the render will fail.
- **Do not** cite an ES range for a Solr knob (or vice versa) — engine-specific docs exist precisely because the divergence points matter.

## 5) Assumptions and dependencies

- Dependency: `query_templates` resource + `POST /api/v1/query-templates`.
  - Why required: operators register library templates through it.
  - Status: implemented (shipped).
  - Risk if missing: none — present in `main`.
- Dependency: ES/OpenSearch adapter `render()` (raw-DSL passthrough) + Solr adapter `render()` (flat-dict pivot).
  - Status: implemented.
  - Risk if missing: render-validation tests would fail; both are present.
- Dependency: `docs/06_vendor_docs/solr-9|10/` ref-guide source for grounding the Solr cheatsheet.
  - Status: implemented (checked in by `infra_adapter_solr`).
  - Risk if missing: Solr cheatsheet would lack a primary citation; present.
- Dependency: glossary link-field support (for FR-7).
  - Status: to be verified at plan time; if absent, FR-7's UI portion is dropped (locked in §19).

## 6) Actors and roles

- Primary actor(s): Relevance Engineer (browses the library, picks a template, reads the cheatsheet).
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this chore adds no state-mutating endpoint or service function. Template registration uses the existing `POST /api/v1/query-templates`, whose audit posture (MVP2 `audit_log` lands per data-model.md) is unchanged by this content/docs feature. No new mutation site is introduced.

## 7) Functional requirements

### FR-1: Locked RUNNABLE template set (ES/OpenSearch)

- Requirement:
  - The system **MUST** ship the following ES/OpenSearch templates at the top level of `samples/templates/`, each rendering to valid native ES/OpenSearch Query DSL from a render context of **only `query_text` + the declared tunable params** (the render path injects nothing else — see the render-context constraint below):
    1. `multi_match_basic.j2` — basic lexical multi_match. **Declared (tunable) params:** `tie_breaker`, `fuzziness`, plus per-field boosts (`title_boost`, `description_boost`, `bullet_points_boost` — flat scalar floats, matching the existing `product_search.j2` flat-boost convention). **Baked-in literals (in the Jinja body, NOT declared):** the field name list, `type: best_fields`. (`slop` is intentionally NOT exposed — it only affects `phrase`/`phrase_prefix` multi_match, not `best_fields`; cycle 3, GPT-5.5 F1. The phrase-slop knob lives on `rescore_phrase.j2` where it is valid.)
    2. `function_score_decay.j2` — function_score with a `gauss` decay over a numeric/date field. **Declared (tunable):** `decay_scale`, `decay_offset`, `decay_decay`, plus the field boosts. **Baked-in literals:** the decay field name (e.g. `created_at`), the decay function kind (`gauss`), `boost_mode` (e.g. `multiply`).
    3. `bool_boosted.j2` — bool `must`/`should`/`filter` with `minimum_should_match`. **Declared (tunable):** `min_should_match` (string, categorical choices), plus the should-clause boosts. **Baked-in literals:** the clause field names.
    4. `rescore_phrase.j2` — first-pass lexical + second-pass phrase rescore. **Declared (tunable):** `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop`, plus the field boosts (`title_boost`, `description_boost`, `bullet_points_boost`). **Baked-in literals:** the phrase field, the first-pass `type: best_fields`.
  - The system **MUST** keep the existing `product_search.j2` unchanged (do not rename it — `demo_seeding.py:1248` reads it by path; renaming would break demo reseed).
- Notes: Every param name is flat (no dots). All four shapes render purely from `query_text` + their declared tunable params — no dense query vector required — so they are runnable end-to-end through the existing trial-runner render path with their `.search_space.json` starters.

**Declared-param == search-space equality is a PLATFORM INVARIANT (added cycle 2, GPT-5.5 F1).** `backend/app/domain/study/search_space.py:230-246` (`validate_against_template`) enforces that `search_space.params` keys equal `declared_params` keys **exactly** — an extra search-space key raises `UnknownSearchSpaceParamError`, a declared param missing from the search space raises `MissingDeclaredParamError`. **There is no "fixed/constant declared param" mechanism.** Consequence: a template MUST declare *only* params it intends to tune; any structural value that should stay constant (field names, decay-function kind, `boost_mode`) **MUST be a Jinja literal baked into the template body, not a declared param.** This is why FR-1's templates split "declared (tunable)" from "baked-in literals." The §9 invariant restates this; FR-3's `.search_space.json` keys therefore equal the declared params exactly (not a subset).

**Render-context constraint (root of the kNN/hybrid decision — cycle 1, GPT-5.5 F2/F3):** The render context built by both adapters is exactly `{**params, "query_text": query_text}` (verified `backend/app/domain/query/render.py:55`). There is **no `query_vector` / embedding** injected, and wiring an embedding pipeline is out of scope. Therefore any template requiring a dense query vector (pure kNN, vector half of hybrid RRF) **cannot render a complete, runnable request** today. Such shapes ship as **reference snippets in the cheatsheets (FR-4), NOT as registerable `.j2` templates** — see FR-1b.

### FR-1b: kNN + hybrid RRF as reference snippets, not runnable templates

- Requirement:
  - The system **MUST NOT** ship `knn_only.j2` or `hybrid_rrf.j2` as registerable `samples/templates/*.j2` files with `.search_space.json` starters in this chore — because the render path supplies no query vector (FR-1 render-context constraint).
  - The system **MUST** instead document the kNN and hybrid-RRF DSL shapes as fully-worked **reference snippets inside the ES and OpenSearch cheatsheets** (FR-4), each clearly marked "reference shape — requires a query-vector injection mechanism not present in the current trial runner; provided for hand-authoring / future enablement."
  - The cheatsheets **MUST** document the ES-vs-OpenSearch hybrid divergence explicitly: **Elasticsearch 8.11+** offers the native `rrf` retriever; **OpenSearch 2.x** has no native `rrf` retriever and instead combines lexical + vector via a **search-pipeline normalization processor**. The two are NOT interchangeable — the ES snippet is invalid on OpenSearch and vice versa. Each engine's cheatsheet shows only its own valid construct.
- Notes: This resolves GPT-5.5 cycle-1 F1 (one ES-native body is not valid on OpenSearch) and F2 (no vector input contract) by removing the infeasible runnable templates while preserving the educational value as engine-correct reference snippets. If a future feature wires embedding injection, these snippets graduate to runnable templates.

### FR-2: Locked template set (Solr)

- Requirement:
  - The system **MUST** ship the following Solr templates under `samples/templates/solr/`, each rendering to a valid flat Solr request-parameter dict:
    1. `edismax_basic.j2` — edismax lexical (mirrors the existing `products_edismax.j2` shape with a wider tunable surface). **Declared (tunable):** `tie`, `mm` (categorical string choices), `ps`, plus the per-field boosts. **Baked-in literals:** `defType: edismax`, `fl`, the qf field names, **and `pf` (phrase fields)**. `pf` MUST be baked in so the declared-tunable `ps` actually takes effect — in edismax, `ps` (phrase slop) only applies to phrase queries generated from `pf`, so exposing `ps` without any `pf` would make `ps` a silent no-op (Gemini PR #413 finding — accepted). `pf` stays a baked-in literal (not a declared param) per the §9 declared-param == search-space equality invariant.
    2. `boost_decay.j2` — edismax with a recency/proximity boost. **Declared (tunable), exact set:** `boost_weight` (float — overall additive boost strength), `decay_scale` (float — the recip/decay scale), plus the per-field boosts (`title_boost`, `description_boost`, `bullet_points_boost`). **Baked-in literals:** `defType: edismax`, `fl`, the `bf` function-expression skeleton (e.g. `recip(...)`) + the decay field name; the tunable `boost_weight` and `decay_scale` are interpolated into that `bf` string. (Exact scalar names locked — cycle 3, GPT-5.5 F3.) The same `boost_weight`/`decay_scale` keys MUST appear identically in the README, `.search_space.json`, render test, and cheatsheet back-links.
  - The system **MUST NOT** ship a Solr kNN or Solr hybrid template (out of scope per §3).
  - The existing `products_edismax.j2`, `products_dismax.j2`, `products_lucene.j2` **MUST** remain unchanged.
- Notes: Solr templates use the documented pivot keys (`field_boosts`→`qf`, `boost_fn`→`bf`/`boost`) plus Solr-native keys (`defType`, `q`, `tie`, `mm`, `ps`, `pf`, `fl`). (`pf` is baked into `edismax_basic.j2` as the phrase-field source that makes `ps` meaningful — see FR-2 item 1.)

### FR-3: Per-template documentation + starter search space

- Requirement:
  - For each new **runnable** template (4 ES/OS + 2 Solr), the system **MUST** document (in `samples/templates/README.md` and `samples/templates/solr/README.md` — a new file): purpose / when to use, the declared params with one-line descriptions and ranges (marking structural-vs-tunable), expected metric behavior, and known caveats.
  - For each new runnable template, the system **MUST** ship a checked-in starter search space as `samples/templates/<name>.search_space.json` (top level) or `samples/templates/solr/<name>.search_space.json` — a human-tuned `SearchSpace`/`ParamSpec` dict an operator can paste into the Step-4 builder. (Co-locating `.search_space.json` next to the `.j2` avoids per-template subdirectories — see §19.)
  - For each new runnable template, the system **MUST** make it registerable from checked-in artifacts alone (no guessing). Because `query_templates` registration requires a `declared_params` map (`{name: type-string}`) which is a DIFFERENT shape from the `.search_space.json` ParamSpec, the README section per template **MUST** include a copy-paste registration block. Since the `query_templates.body` column stores the **actual Jinja source** (not a path), the block **MUST** be a runnable `curl` command that reads the checked-in `.j2` file into the `body` field at submit time — e.g. `jq -n --arg body "$(cat samples/templates/<name>.j2)" '{name:"...",engine_type:"...",declared_params:{...},body:$body}' | curl -X POST .../api/v1/query-templates -H 'Content-Type: application/json' --data-binary @-`. The `-H 'Content-Type: application/json'` header is REQUIRED — without it `curl` defaults to `application/x-www-form-urlencoded` and the FastAPI JSON endpoint returns 422 (cycle 6, GPT-5.5 F1). A path/reference as `body` is NOT accepted by the API and **MUST NOT** be documented as if it were (cycle 5, GPT-5.5 F1). The `declared_params` keys in that block MUST equal the `.search_space.json` keys exactly (cycle 4, GPT-5.5 F2).
- Notes: The starter search space MUST stay under the 10⁶ cardinality cap and its keys MUST equal the template's `declared_params` exactly (§9 platform-equality invariant). Constant structural values are Jinja literals in the body, not params. The FR-1b kNN/hybrid reference snippets are documented in the cheatsheets, not here, and have no `.search_space.json`.

### FR-4: Per-engine tunable-params cheatsheets

- Requirement:
  - The system **MUST** add three docs: `docs/06_vendor_docs/elasticsearch-tunable-params.md`, `opensearch-tunable-params.md`, `solr-tunable-params.md`.
  - Each cheatsheet **MUST** have one section per tunable knob containing: native engine name + RelyLoop unified name (if different); typical range / valid choices with a citation; "When to tune" (one line); "Caveats" (version availability, performance cliffs, common misconfigurations); "Templates that use this param" (back-link into the library).
  - Each cheatsheet **MUST** cover the 8 unified-vocabulary params (from adapters.md §"Cross-engine parameter naming") plus the engine-specific knobs the new runnable templates expose (~15–20 entries per engine).
  - The ES and OpenSearch cheatsheets **MUST** each include a "Vector & hybrid (reference shapes)" section with engine-correct kNN and hybrid-RRF DSL snippets per FR-1b, marked as not-yet-runnable, with the ES-`rrf`-retriever vs OpenSearch-normalization-processor divergence called out (FR-1b).
  - The Solr cheatsheet **MUST** ground its claims in the checked-in `docs/06_vendor_docs/solr-9/` + `solr-10/` ref-guide source; ES/OpenSearch cheatsheets **MUST** cite the upstream URL + access date per the vendor-docs README convention.
- Notes: Naming chosen to avoid colliding with the README-reserved `elasticsearch-9x.md` / `opensearch-2x.md` version-quirk files.

### FR-5: Vendor-docs README index + samples README layout

- Requirement:
  - The system **MUST** add one index-table row per new cheatsheet to `docs/06_vendor_docs/README.md` (Doc / What it covers / Used by columns) and remove or update the "Coming with later features" line if it would now be stale.
  - The system **MUST** update `samples/templates/README.md`'s layout block + authoring rules to reflect the new shapes and the `.search_space.json` co-location convention.

### FR-6: Render-validation tests

- Requirement:
  - For each new **runnable** template (4 ES/OS + 2 Solr — NOT the FR-1b reference snippets, which are doc content), the system **MUST** add a render-validation unit test that: feeds the template body + its declared params through the matching adapter `render()` (ES adapter for top-level templates, Solr adapter for Solr templates), asserts the result parses as JSON / a valid param dict, and asserts the expected native keys are present (e.g., `function_score` for `function_score_decay.j2`, `rescore` for `rescore_phrase.j2`, `bool`+`minimum_should_match` for `bool_boosted.j2`, `bf`/`boost` for `boost_decay.j2`).
  - Because the single `ElasticAdapter` serves both ES and OpenSearch and the two DIVERGE only on shapes excluded from the runnable set (hybrid RRF, kNN — now FR-1b reference-only), the four runnable ES/OS templates use lexical/function-score/rescore DSL that is **identical and valid on both ES 8.11+ and OpenSearch 2.x**. The render test **MUST** assert this explicitly (one parametrized case documenting that the rendered body is engine-agnostic for these four shapes) so the "works on both engines" claim is test-backed rather than asserted.
  - Tests **MUST** reuse the existing render-test harness pattern (`backend/tests/unit/adapters/test_solr_render.py` for Solr; the ES render unit tests for top-level).
- Notes: These are pure unit tests (no DB, no live cluster) — they validate render output shape, not engine execution. A live-cluster smoke test is out of scope (no Solr/ES service container is guaranteed in `pr.yml`; the demo-reseed engine-tolerance posture applies). The FR-1b kNN/hybrid reference snippets are validated by the FR-4 doc-consistency test (they parse as JSON), not by an adapter render test (they cannot render without a vector).

### FR-7: Step-3 inline summary + glossary cheatsheet link (conditional)

- Requirement:
  - The system **SHOULD** surface a one-line "when to use" summary in the Step-3 template picker, AND add a "Learn more" cheatsheet link to the `study.search_space` glossary entry keyed off the selected cluster's `engine_type`.
  - This FR is **conditional**: it ships ONLY if the summary text and cheatsheet link can be surfaced **without** a `query_templates` migration and **without** a new backend endpoint — i.e., the description is derivable client-side (a static `ui/src/lib/template-descriptions.ts`) and the glossary supports a link field.
  - **Keying (corrected cycle 1, GPT-5.5 F5):** because this chore does NOT auto-seed canonical template rows, an operator's registered template `name` is user-controlled and not guaranteed to match a recommended slug. The description map therefore **MUST** key on a **stable recommended registration name documented in the README** (e.g., the README instructs `--name multi-match-basic-v1` for `multi_match_basic.j2`), and the UI summary **MUST** degrade gracefully (render nothing) when the registered `name` has no map entry — never error, never show a wrong summary. The cheatsheet "Learn more" link keys on `engine_type` (one of the three `SUPPORTED_ENGINE_TYPES`), which is always present, so the link is unconditional even when the per-template summary is absent.
  - If neither piece is plumbable without schema/endpoint change, the UI portion **MUST** be dropped from this chore (the README files + cheatsheets remain the core deliverable). It is NOT deferred to a phase 2 — it is simply cut.
- Notes: The description-map values MUST carry a `// Source: samples/templates/README.md` comment so they don't drift, and the README MUST state the recommended `--name` for each template so the join key is documented in one place.

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — this feature adds no endpoints. Operators register templates via the existing `POST /api/v1/query-templates`.

### 7.2 Contract rules

N/A — no new contracts. Existing `query_templates` contract unchanged.

### 7.3 Response examples

N/A — no new endpoints.

### 7.4 Enumerated value contracts

The only enumerated value this feature interacts with is `engine_type` on templates and clusters.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `query_templates.engine_type` / cluster `engine_type` | `elasticsearch`, `opensearch`, `solr` | `backend/app/adapters/registry.py:27` (`SUPPORTED_ENGINE_TYPES` `frozenset`) | Step-3 picker filter `ui/src/components/studies/create-study-modal.tsx:383` (`useTemplates({ engine_type })`) |

- The FR-7 static description map (if it ships) is keyed by template `name` (a free-text string), NOT by an enum — so no allowlist drift risk there. The `engine_type`-keyed cheatsheet link MUST use exactly the three `SUPPORTED_ENGINE_TYPES` values; a `// Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES` comment is required above any `engine_type`→cheatsheet mapping.
- Observation (not in scope to fix): `backend/app/agent/tools/templates/list_templates.py:21` types `engine_type` as `Literal["elasticsearch","opensearch"]` — missing `"solr"`. Captured in §19; not patched by this content chore.

### 7.5 Error code catalog

N/A — no new error codes. Template render errors continue to surface as the existing `ValueError`→service-layer translation (missing/undefined param), unchanged.

## 9) Data model and state transitions

### New/changed entities

None. No table added, no column added, no migration. (This is a hard constraint — see §3 Out of scope and the FR-7 anti-pattern.)

### Required invariants

- A runnable template's `.search_space.json` keys MUST **equal** that template's `declared_params` keys exactly — because the platform validator `validate_against_template` (`backend/app/domain/study/search_space.py:230-246`) rejects both extra search-space keys and missing declared params. There is no fixed-constant-declared-param path. Any value that should stay constant (field names, decay-function kind, `boost_mode`, `defType`) MUST be a **Jinja literal in the template body, NOT a declared param**. Enforced by the FR-6 render test, which (a) asserts the `.search_space.json` keys equal the declared-param keys, then (b) **samples one concrete scalar assignment** from the `SearchSpace` semantics (one value per param — `render()` needs concrete scalars, NOT the ParamSpec dict itself; cycle 4, GPT-5.5 F1) and passes that assignment + `query_text` to the adapter `render()`, proving the body renders with no missing/undeclared param — plus the FR-4 doc-consistency test. *(Cycle 2, GPT-5.5 F1 — supersedes the cycle-1 "subset" framing, which was wrong: the platform enforces equality, so structural inputs must be literals, not loosely-declared params.)*
- Every runnable template's `.search_space.json` cardinality (product of per-param choice counts / discretized float buckets) MUST stay under 10⁶ — enforced by a doc-consistency test that computes cardinality via the same `SearchSpace` semantics the study builder uses (cycle 2, GPT-5.5 F3).
- Every cheatsheet "Templates that use this param" back-link MUST point at a template that actually declares that param — enforced by a doc-consistency test (see §14).

### State transitions

N/A — content + docs.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- Threats: (1) a cheatsheet citing a wrong range mis-tunes a production-bound config; (2) a template rendering invalid DSL silently produces zero results. Both are mitigated by citations (FR-4) and render-validation tests (FR-6).
- Controls: render-validation tests; doc-back-link consistency test; citation requirement.
- Secrets/key handling: N/A — no secrets touched. Templates contain no credentials.
- Auditability: N/A — no mutations.
- Data retention/deletion/export impact: none.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new navigation. The library lives in `samples/templates/` (filesystem, surfaced to operators via the existing templates list + Step-3 picker once registered). Cheatsheets live under `docs/06_vendor_docs/` (docs site / repo browse).
- **Labeling taxonomy:** Cheatsheets titled "Elasticsearch tunable parameters", "OpenSearch tunable parameters", "Apache Solr tunable parameters". Template README sections titled by template name + one-line purpose.
- **Content hierarchy:** Cheatsheet — intro paragraph, then one H2/H3 per knob. Samples README — layout block, authoring rules, then per-template "when to use" entries.
- **Progressive disclosure:** Step-3 picker (if FR-7 ships) shows the one-line summary inline under the selected template; the full cheatsheet is a "Learn more" link.
- **Relationship to existing pages:** Extends the existing `samples/templates/README.md`, `docs/06_vendor_docs/README.md`, the tutorial, and (conditionally) the Step-3 picker + glossary. Replaces nothing.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Step-3 template summary (FR-7, conditional) | one-line "when to use this template" from the description map | inline | inline helper text under the picker |
| `study.search_space` glossary entry "Learn more" (FR-7, conditional) | links to `<engine>-tunable-params.md` | info-icon / link click | within the existing glossary tooltip |

Glossary key: existing `study.search_space` (in `ui/src/lib/glossary.ts`). FR-7 adds a link field/value to that entry — no new glossary key.

### Primary flows

1. Operator browses `samples/templates/` + the engine cheatsheet, picks `function_score_decay.j2`, registers it via UI/API, pastes its `.search_space.json` starter into Step-4, runs a study.
2. Operator hovers the `search_space` glossary tooltip, clicks "Learn more", lands on the engine-appropriate cheatsheet (if FR-7 ships).

### Edge/error flows

- Operator registers a template but supplies params not matching `declared_params` → existing render `ValueError` (`missing required template params` / `undefined parameter`) — unchanged behavior.
- FR-7 not shippable without a migration → UI portion cut; README + cheatsheets still ship (no error surface — a scope decision, not a runtime path).

## 12) Given/When/Then acceptance criteria

### AC-1: ES/OpenSearch runnable templates render to valid, engine-agnostic DSL
- Given the four FR-1 runnable templates with their declared params and starter search spaces (render context = `query_text` + params only)
- When each is rendered via the ES adapter `render()`
- Then the output parses as JSON, contains the expected native block (`multi_match`, `function_score`, `bool`+`minimum_should_match`, or `rescore`), references no undeclared param, and the rendered body is valid on both ES 8.11+ and OpenSearch 2.x (lexical/function-score/rescore DSL is identical across both).
- Example: `rescore_phrase.j2` with `{title_boost: 2.0, description_boost: 1.0, bullet_points_boost: 1.0, rescore_window_size: 50, rescore_query_weight: 1.5, rescore_phrase_slop: 2}` → output has a `query` + a `rescore` block with `window_size=50`. (Flat scalar boosts, not a nested `field_boosts` object — cycle 3, GPT-5.5 F2.)

### AC-1b: kNN/hybrid ship as reference snippets, not runnable templates
- Given the feature branch
- When `samples/templates/` is inspected
- Then NO `knn_only.j2` or `hybrid_rrf.j2` registerable template exists, AND the ES + OpenSearch cheatsheets each contain an engine-correct kNN snippet and a hybrid snippet (ES uses the `rrf` retriever; OpenSearch uses a search-pipeline normalization processor), each marked "reference — not runnable without query-vector injection."

### AC-2: Solr templates render to valid param dicts
- Given the two FR-2 Solr templates with declared params
- When each is rendered via the Solr adapter `render()`
- Then the output is a flat dict with `defType` set, lexical keys present, and (for `boost_decay.j2`) a `bf` or `boost` key produced from the `boost_fn` pivot.

### AC-3: existing demo templates unchanged
- Given `product_search.j2` and the three `solr/products_*.j2`
- When the feature branch is diffed
- Then those four files are byte-identical to `main` (no rename, no edit) — protects `demo_seeding.py:1248` and the smoke path.

### AC-4: cheatsheets complete and consistent
- Given the three cheatsheets
- When each is checked
- Then each covers all 8 unified params + each template-exposed engine knob; every "Templates that use this param" back-link names a template that declares that param; and the vendor-docs README index has a row per cheatsheet.
- Example: `solr-tunable-params.md` cites `docs/06_vendor_docs/solr-10/` for `bf`/`boost` ranges.

### AC-5: no migration, no new endpoint
- Given the feature branch
- When migrations and routers are inspected
- Then no Alembic revision is added and `backend/app/api/v1/query_templates.py` gains no new route.

### AC-6: FR-7 fork resolves cleanly
- Given the glossary + Step-3 picker
- When FR-7 is implemented
- Then EITHER the inline summary + cheatsheet link ship via a client-side description map (with source-of-truth comment) and a glossary link field, OR the UI portion is absent and only README + cheatsheets ship — never a half-built UI requiring a migration.

## 13) Non-functional requirements

- Performance: N/A — static content; render-validation tests run in the unit suite (< a few seconds).
- Reliability: render-validation tests guard against invalid-DSL regressions.
- Operability: cheatsheets are the operability artifact (they tell operators how to tune).
- Accessibility/usability: if FR-7 ships, the inline summary is plain text under the picker; the "Learn more" link is keyboard-focusable (matches existing glossary link patterns).

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/adapters/`): one render-validation case per new template (FR-6) — each samples one concrete scalar assignment from the template's `.search_space.json` `SearchSpace`, passes it + `query_text` to the adapter `render()`, and asserts the native block; extend `test_solr_render.py` for Solr templates; new `test_elastic_render_library.py` (or extend the ES render test) for top-level templates. Also assert each template's README registration block `declared_params` keys equal the `.search_space.json` keys.
- Unit/doc-consistency test (`backend/tests/unit/docs/`): assert every cheatsheet "Templates that use this param" back-link points at a template whose declared params include that knob; assert the vendor-docs README index has a row per cheatsheet; assert each runnable template's `.search_space.json` keys **equal** its `declared_params` keys (platform-equality invariant, §9); assert each `.search_space.json` cardinality is < 10⁶ using the same `SearchSpace` cardinality semantics as the study builder (`backend/app/domain/study/search_space.py`); assert the FR-1b kNN/hybrid snippets in the cheatsheets parse as JSON.
- Integration tests: N/A — no DB-backed path added.
- Contract tests: N/A — no endpoint added.
- E2E tests: N/A by default. IF FR-7's UI ships, a single existing-suite assertion (the Step-3 summary text appears after picking a template) MAY be added against the real backend — but no new E2E suite is required for a content chore, and `page.route()` mocking is forbidden.

## 15) Documentation update requirements

- `docs/01_architecture`: no change required (adapters.md vocabulary is unchanged; the cheatsheets cite it).
- `docs/06_vendor_docs`: add 3 cheatsheets + README index rows (FR-4, FR-5).
- `docs/08_guides`: add "Where to go next" to `tutorial-first-study.md` (FR-5-adjacent).
- `samples/templates`: update `README.md` + add `solr/README.md` (FR-3, FR-5).
- `docs/03_runbooks`, `docs/04_security`, `docs/05_quality`: no change required.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: none — content + docs.
- Migration/backfill expectations: none (hard constraint).
- Operational readiness gates: render-validation + doc-consistency tests green in the unit suite.
- Release gate: unit suite green; AC-3 byte-identity check on the four existing templates; AC-5 no-migration check.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-3 | 1.1 | `backend/tests/unit/adapters/test_elastic_render_library.py` | `samples/templates/README.md` |
| FR-1b | AC-1b | 2.1, 2.2 | `backend/tests/unit/docs/test_tunable_params_cheatsheets.py` | `docs/06_vendor_docs/elasticsearch-tunable-params.md`, `opensearch-tunable-params.md` |
| FR-2 | AC-2, AC-3 | 1.2 | `backend/tests/unit/adapters/test_solr_render.py` | `samples/templates/solr/README.md` |
| FR-3 | AC-1, AC-2 | 1.1, 1.2 | render-validation tests | both samples READMEs |
| FR-4 | AC-4, AC-1b | 2.1, 2.2, 2.3 | `backend/tests/unit/docs/test_tunable_params_cheatsheets.py` | `docs/06_vendor_docs/*-tunable-params.md` |
| FR-5 | AC-4 | 2.4 | `backend/tests/unit/docs/test_tunable_params_cheatsheets.py` | `docs/06_vendor_docs/README.md`, `docs/08_guides/tutorial-first-study.md` |
| FR-6 | AC-1, AC-2 | 1.3 | render-validation tests | — |
| FR-7 | AC-6 | 3.1 | (conditional) existing-suite UI assertion | `ui/src/lib/glossary.ts`, `ui/src/lib/template-descriptions.ts` |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1, AC-1b, AC-2…AC-6) pass in CI.
- [ ] Unit + doc-consistency tests green; AC-3 byte-identity + AC-5 no-migration checks pass.
- [ ] All 6 runnable templates (4 ES/OS + 2 Solr) + their `.search_space.json` starters + per-template README registration blocks (`declared_params` keys == `.search_space.json` keys) checked in.
- [ ] kNN + hybrid-RRF reference snippets present in the ES + OpenSearch cheatsheets (FR-1b), engine-correct, marked not-runnable.
- [ ] Three cheatsheets + README index rows + tutorial "Where to go next" merged.
- [ ] FR-7 fork resolved one way or the other (no half-built UI).
- [ ] No Alembic revision, no new endpoint, four existing demo templates untouched.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None remaining — all forks below are locked.

### Decision log

- 2026-06-02 — **Runnable template set locked** to 4 ES/OS (`multi_match_basic`, `function_score_decay`, `bool_boosted`, `rescore_phrase`) + 2 Solr (`edismax_basic`, `boost_decay`). Rationale: these six render completely from `query_text` + tunable params alone, so they are runnable through the existing trial runner.
- 2026-06-02 (cycle 1, GPT-5.5 F1/F2) — **kNN + hybrid-RRF DEMOTED from runnable templates to cheatsheet reference snippets.** The render context is exactly `{**params, "query_text": query_text}` (`backend/app/domain/query/render.py:55`); no query vector is injected and wiring embeddings is out of scope. A pure-vector or hybrid template therefore cannot render a complete request today. Shipping them as runnable `.j2` + `.search_space.json` would produce invalid/empty results. Instead they are documented as engine-correct reference snippets in the ES + OpenSearch cheatsheets (FR-1b), with the ES-`rrf`-retriever vs OpenSearch-normalization-processor divergence spelled out — also resolving F1 (one ES body is NOT valid on OpenSearch). They graduate to runnable templates if a future feature wires query-vector injection.
- 2026-06-02 — **No auto-seed.** Templates are files-on-disk registered on demand via the existing endpoint/UI; `seed_meaningful_demos.py` and `demo_seeding.py` are NOT modified. Rationale: auto-seeding 8 templates would clutter the tutorial Step-3 picker and inflate the seed script.
- 2026-06-02 — **No migration / no `description` column.** Hard constraint. The Step-3 inline summary (FR-7) is plumbed via a static client-side description map keyed by template `name`, not a schema column.
- 2026-06-02 — **Cheatsheet count = 3** (`elasticsearch-`, `opensearch-`, `solr-tunable-params.md`), named to avoid colliding with the README-reserved `elasticsearch-9x.md`/`opensearch-2x.md` version-quirk files. Rationale: ES/OS overlap ~90% but the divergence points (ES native `rrf` retriever vs OpenSearch normalization-processor hybrid; Solr's `{!knn}`/`{!ltr}`) are the reason engine-specific docs exist; Solr is a wholly separate surface.
- 2026-06-02 — **README structure: directory README + co-located `.search_space.json`**, NOT a per-template subfolder. Rationale: a subfolder-per-template (idea's original "README.md next to the template") would fragment `samples/templates/` into 8 dirs; a single directory README with one section per template plus `<name>.search_space.json` siblings keeps the tree flat and matches the existing single-README layout.
- 2026-06-02 — **FR-7 is conditional, not deferred.** If the inline-summary + glossary-link cannot ship without a migration or new endpoint, the UI portion is CUT, not phase-2'd. Rationale: a content chore should not grow a schema change; the README + cheatsheets are the core value.
- 2026-06-02 — **Sibling source drift NOT fixed here.** `query_template.py` docstring (`elasticsearch | opensearch`) and `list_templates.py:21` `engine_type` Literal (missing `solr`) are pre-existing source-code drift. This content/docs chore touches no `backend/app/` source, so fixing them here would blur the PR's review boundary. Recommend a separate one-line `chore_` fix (or fold into `chore_solr_post_pipeline_followups`). Captured so it isn't lost.

### Cross-model review log

See the dedicated "Cross-model review log" section appended below.

---

## Cross-model review log (GPT-5.5)

**Reviewer:** GPT-5.5 (`gpt-5.5` via OpenAI Chat Completions, `max_completion_tokens`). API key resolved from `.env`. Two labeled passes (A: Contract & Data, B: Impact & Coverage) per call.

### Cycle 1 — 5 findings (2 High, 2 Medium, 1 Low) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | High | One ES-native `hybrid_rrf.j2` is not valid on OpenSearch 2.x (ES has native `rrf` retriever; OpenSearch uses search-pipeline normalization). | **Accept.** Demoted hybrid RRF to engine-split reference snippets (FR-1b); cheatsheets show each engine's own construct. |
| F2 | A | High | kNN/hybrid templates can't render a complete request — no query-vector input is defined; render context is `query_text` + params only. | **Accept.** Verified `render.py:55` injects only `{**params, "query_text"}`. Removed `knn_only.j2`/`hybrid_rrf.j2` as runnable templates; they ship as reference snippets (FR-1b). Render-context constraint documented in FR-1. |
| F3 | B | Med | Top-level templates tested only via ES adapter despite ES/OpenSearch divergence. | **Accept.** With kNN/hybrid removed, the 4 runnable ES/OS shapes are engine-agnostic lexical/function-score/rescore DSL. FR-6 now requires an explicit test asserting the rendered body is valid on both ES and OpenSearch. |
| F4 | A | Med | Invariant "`declared_params` keys MUST equal `.search_space.json` keys" wrongly forces structural inputs (`decay_field`, `knn_field`) to be tunable. | **Accept.** §9 invariant rewritten to "search-space keys ⊆ declared params"; structural/fixed render inputs are declared but excluded from the search space. |
| F5 | B | Low | FR-7 description map keyed by user-controlled `name`, but no canonical seed guarantees the name. | **Accept.** FR-7 now keys on a README-documented recommended `--name`, degrades gracefully (renders nothing) on a miss, and makes the `engine_type`-keyed cheatsheet link unconditional. |

### Cycle 2 — 3 findings (1 High, 1 Medium, 1 Low) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | High | Structural params declared-but-excluded-from-search-space have no runtime supply mechanism → StrictUndefined render failures; the cycle-1 "subset" invariant doesn't actually work. | **Accept — and it corrected my cycle-1 fix.** Verified `validate_against_template` (`search_space.py:230-246`) enforces declared==search-space **equality** (rejects extra AND missing). So there is NO fixed-param path. Resolution: structural values become **Jinja literals in the body, not declared params**; declared params == search-space exactly. FR-1/FR-2 now split "declared (tunable)" from "baked-in literals"; §9 invariant restated to equality. |
| F2 | A | Med | §14 still said "keys ==" while §9 (cycle-1) said "⊆" — contradiction. | **Accept.** Now both say equality (the platform-correct rule); §14 also adds the cardinality check. Contradiction removed. |
| F3 | B | Low | 10⁶ cardinality cap stated but no test covers it. | **Accept.** Added a doc-consistency assertion computing each `.search_space.json`'s cardinality via the study builder's `SearchSpace` semantics and failing > 10⁶ (§9 invariant + §14). |

### Cycle 3 — 3 findings (3 Medium) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | `multi_match_basic.j2` exposes `slop` while baking `type: best_fields`; `slop` only affects phrase multi_match. | **Accept.** Removed `slop` from `multi_match_basic.j2`; the phrase-slop knob stays on `rescore_phrase.j2` where it's valid. (Confirmed against existing `product_search.j2`, which uses `best_fields` and exposes no slop.) |
| F2 | A | Med | AC-1 example used nested `field_boosts: {title: 2.0}`, contradicting the flat-scalar-boost contract. | **Accept.** AC-1 example rewritten to flat `title_boost`/`description_boost`/`bullet_points_boost`. |
| F3 | A | Med | `boost_decay.j2` "any boost-strength scalar" is vague vs the exact-key equality contract. | **Accept.** Locked exact declared set: `boost_weight`, `decay_scale`, + field boosts; required identical keys across README / `.search_space.json` / render test / cheatsheet. |

### Cycle 4 — 2 findings (2 Medium) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | Render test "renders from the `.search_space.json` param set" conflates a ParamSpec/SearchSpace with concrete scalar render params. | **Accept.** §9 + §14 now require the test to **sample one concrete scalar assignment** from the SearchSpace and pass that (not the ParamSpec dict) to `render()`. |
| F2 | B | Med | Templates aren't registerable from checked-in artifacts: `query_templates` needs a `declared_params` map (different shape from `.search_space.json`); spec only mandated `.j2` + README prose + `.search_space.json`. | **Accept.** FR-3 now requires a per-template README copy-paste registration block (the exact `POST` body incl. `declared_params`), with a test asserting its keys equal the `.search_space.json` keys. Preserves no-endpoint/no-migration scope. |

### Cycle 5 — 1 finding (1 Medium) — Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | Registration block said "`body` reference"; `query_templates.body` stores actual Jinja source, so a path reference is not a valid payload. | **Accept.** FR-3 now mandates a runnable `curl` + `jq --arg body "$(cat ...j2)"` command that injects the source into `body` at submit; a path/reference as `body` is explicitly forbidden. |

### Cycle 6 — 1 finding (1 Medium) — Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | The registration `curl` example omitted `-H 'Content-Type: application/json'`; curl defaults to form-urlencoded → 422. | **Accept.** FR-3 example now includes `-H 'Content-Type: application/json' --data-binary @-` and notes the header is required. |

### Cycle 7 — convergence confirmed (no new High/Medium)

The cycle-5/6/7 findings progressively refined the *same* FR-3 registration-command example (path→source, then content-type header) — each a copyedit on one example, not an architectural change. The substantive design (template set, render-context constraint, declared-param equality, kNN/hybrid demotion, no-migration, FR-7 conditional) stabilized at cycle 3 and has not changed since. Convergence reached: the cross-model loop produced no new contract/data-model/acceptance-criteria changes after cycle 4; the final two cycles touched only one example command. Spec **Approved**.
