# Implementation Plan — Curated query-template library + per-engine tunable-params cheatsheets

**Date:** 2026-06-02
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) §"Cross-engine parameter naming"; [`samples/templates/README.md`](../../../../../samples/templates/README.md); [`docs/06_vendor_docs/README.md`](../../../../06_vendor_docs/README.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs.
- This is a **content + docs + render-validation-test** chore: NO migration, NO new endpoint, NO source change under `backend/app/`. The only Python written is test files under `backend/tests/`. The optional FR-7 is the sole frontend touch and is conditional.
- Fail-loud tests: render-validation tests sample one concrete assignment and assert the native block; doc-consistency tests assert equality + cardinality + back-links.
- The four existing demo templates (`product_search.j2`, `solr/products_{edismax,dismax,lucene}.j2`) stay byte-identical.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 (4 runnable ES/OS templates) | Epic 1 / Story 1.1 | content files + `.search_space.json` + README registration blocks |
| FR-1b (kNN/hybrid reference snippets) | Epic 2 / Stories 2.1, 2.2 | snippets live inside the ES + OpenSearch cheatsheets |
| FR-2 (2 runnable Solr templates) | Epic 1 / Story 1.2 | Solr-subdir content + `.search_space.json` + README |
| FR-3 (per-template docs + starter spaces + registration blocks) | Epic 1 / Stories 1.1, 1.2 | both samples READMEs |
| FR-4 (3 cheatsheets) | Epic 2 / Stories 2.1, 2.2, 2.3 | one story per engine cheatsheet |
| FR-5 (vendor README index + samples README + tutorial) | Epic 2 / Story 2.4 | index rows + tutorial "Where to go next" |
| FR-6 (render-validation tests) | Epic 1 / Story 1.3 | extend `test_solr_render.py`; new `test_elastic_render_library.py` |
| FR-7 (Step-3 summary + glossary link — conditional) | Epic 3 / Story 3.1 | ships only if no migration/endpoint needed; else cut |

Single phase — no deferred phases, so no `phase<N>_idea.md` tracking artifact is required. FR-7 is a conditional within Phase 1 (cut, not deferred, if infeasible).

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Conventions for this chore:

```
- Template files are pure Jinja2 .j2 content; flat params only (no dotted/attribute access — sandbox forbids it).
- Render output MUST parse as a JSON object (ES native body; Solr flat param dict).
- declared_params (registration) keys MUST EQUAL .search_space.json keys EXACTLY
  (platform invariant: backend/app/domain/study/search_space.py:230-246).
- Structural constants (field names, decay kind, boost_mode, defType) are Jinja LITERALS, NOT params.
- Test files: backend/tests/unit/adapters/ (render), backend/tests/unit/docs/ (doc-consistency).
- No source under backend/app/ is modified by Epics 1-2. Epic 3 (FR-7) is the only frontend touch.
```

### AI Agent Execution Protocol (applies to every story)

0. Load context: read `architecture.md`, `state.md`, the spec, `samples/templates/README.md`, `docs/06_vendor_docs/README.md`, `backend/app/adapters/elastic.py` (`render`), `backend/app/adapters/solr.py` (`render`), `backend/app/domain/study/search_space.py`.
1. Read story scope + DoD.
2. Write content files (templates / cheatsheets / READMEs).
3. Write/extend the render-validation + doc-consistency tests.
4. Run `make test-unit` (the only relevant layer — no DB/endpoint touched).
5. Run `make fmt` + `make lint` before pushing.
6. Confirm the four existing demo templates are byte-identical (`git diff --stat` shows them untouched).
7. (Epic 3 only) implement FR-7 if and only if it needs no migration/endpoint; otherwise mark cut.
8. Attach evidence in the PR.

---

## Epic 1 — Runnable template library (FR-1, FR-2, FR-3, FR-6)

### Story 1.1 — Four runnable ES/OpenSearch templates + starter spaces + registration blocks
**Outcome:** Four new ES/OS templates an operator can register and tune, each with a checked-in starter search space and a copy-paste registration command in the README.

**New files**

| File | Purpose |
|---|---|
| `samples/templates/multi_match_basic.j2` | best_fields multi_match. Declared (tunable): `tie_breaker`, `fuzziness`, `title_boost`, `description_boost`, `bullet_points_boost`. Literals: field list, `type: best_fields`. (NO `slop` — invalid on best_fields.) |
| `samples/templates/function_score_decay.j2` | function_score + `gauss` decay. Declared: `decay_scale`, `decay_offset`, `decay_decay`, `title_boost`, `description_boost`, `bullet_points_boost`. Literals: decay field name, `gauss`, `boost_mode`. |
| `samples/templates/bool_boosted.j2` | bool must/should/filter + minimum_should_match. Declared: `min_should_match` (categorical string), `title_boost`, `description_boost`, `bullet_points_boost`. Literals: clause field names. |
| `samples/templates/rescore_phrase.j2` | first-pass best_fields + phrase rescore. Declared: `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop`, `title_boost`, `description_boost`, `bullet_points_boost`. Literals: phrase field, first-pass `type`. |
| `samples/templates/multi_match_basic.search_space.json` | starter SearchSpace; keys == declared params; cardinality < 10⁶ |
| `samples/templates/function_score_decay.search_space.json` | starter SearchSpace (keys == declared params) |
| `samples/templates/bool_boosted.search_space.json` | starter SearchSpace (keys == declared params) |
| `samples/templates/rescore_phrase.search_space.json` | starter SearchSpace (keys == declared params) |

**Modified files**

| File | Change |
|---|---|
| `samples/templates/README.md` | Add a "Runnable library templates" section: one entry per template (when-to-use, declared params marked tunable, expected metric behavior, caveats) + a copy-paste `curl`+`jq` registration block per FR-3 (reads the `.j2` into `body`, includes `-H 'Content-Type: application/json' --data-binary @-`, recommends a stable `--name` for the FR-7 join key). Update layout block + authoring rules to cover the new shapes + `.search_space.json` co-location. |

**Key interfaces:** none — content only. The render contract is `ElasticAdapter.render(template, params, query_text)` (existing); these templates are exercised by Story 1.3 tests.

**Tasks**
1. Author the four `.j2` bodies as valid native ES/OpenSearch DSL renderable from `query_text` + the declared params alone. Verify each uses only lexical/function-score/rescore DSL valid on BOTH ES 8.11+ and OpenSearch 2.x (no `rrf` retriever, no `knn`).
2. Author each `.search_space.json` with keys equal to the template's declared params and cardinality < 10⁶.
3. Write the README section with per-template registration `curl` blocks; the `declared_params` map in each block MUST equal the template's `.search_space.json` keys. Because the four bodies are engine-agnostic but `query_templates.engine_type` is a single value per row, each block MUST parameterize the engine — `ENGINE_TYPE="elasticsearch"  # or opensearch` injected into the jq payload — so the operator registers the same body once per engine they run (cycle 4, GPT-5.5 F1). The README states explicitly that ES and OpenSearch share the body and the operator picks the engine at registration.
4. Record the recommended stable `--name` per template in the README (join key for FR-7).

**Definition of Done**
- Four `.j2` + four `.search_space.json` checked in; README updated.
- Each registration block's `declared_params` keys == that template's `.search_space.json` keys (asserted by Story 1.3 doc-consistency test).
- `multi_match_basic.j2` does NOT declare `slop`.
- Existing `product_search.j2` untouched (byte-identical).

### Story 1.2 — Two runnable Solr templates + starter spaces + registration blocks
**Outcome:** Two new Solr templates (edismax basic, boost decay) registerable + tunable, with starter spaces and a Solr-subdir README.

**New files**

| File | Purpose |
|---|---|
| `samples/templates/solr/edismax_basic.j2` | edismax lexical. Declared: `tie`, `mm` (categorical string), `ps`, `title_boost`, `description_boost`, `bullet_points_boost`. Literals: `defType: edismax`, `fl`, qf field names. |
| `samples/templates/solr/boost_decay.j2` | edismax + recency boost. Declared (EXACT): `boost_weight`, `decay_scale`, `title_boost`, `description_boost`, `bullet_points_boost`. Literals: `defType: edismax`, `fl`, the `bf` recip() skeleton + decay field name (tunable scalars interpolated). |
| `samples/templates/solr/edismax_basic.search_space.json` | starter SearchSpace (keys == declared params) |
| `samples/templates/solr/boost_decay.search_space.json` | starter SearchSpace (keys == declared params) |

**Modified files**

| File | Change |
|---|---|
| `samples/templates/solr/README.md` (NEW) | Solr-subdir README: per-template when-to-use, declared params (tunable vs literal), registration `curl` blocks (engine_type `solr`), caveats. (Listed here because the directory has no README today.) |

**Tasks**
1. Author `edismax_basic.j2` + `boost_decay.j2` rendering to valid flat Solr param dicts (mix native keys + the `field_boosts`→`qf` / `boost_fn`→`bf` pivots per adapters.md). For `boost_decay.j2`, express the `bf` as a rendered string with `boost_weight` + `decay_scale` interpolated.
2. Author each `.search_space.json` (keys == declared params; cardinality < 10⁶).
3. Write `samples/templates/solr/README.md` with registration blocks.

**Definition of Done**
- Two Solr `.j2` + two `.search_space.json` + `solr/README.md` checked in.
- `boost_decay.j2` declares exactly `boost_weight`, `decay_scale`, + the three field boosts.
- Existing `products_{edismax,dismax,lucene}.j2` untouched (byte-identical).

### Story 1.3 — Render-validation + doc-consistency tests
**Outcome:** Every runnable template is proven to render valid native output from a concrete sampled assignment; the equality + cardinality + back-link + registration-key invariants are test-enforced.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_elastic_render_library.py` | One case per ES/OS template: load `.j2` + `.search_space.json`, sample one concrete scalar assignment via `SearchSpace` semantics, call `ElasticAdapter.render(...)`, assert the native block (`multi_match` / `function_score` / `bool`+`minimum_should_match` / `rescore`). One parametrized assertion documents that the four bodies are engine-agnostic (valid on ES + OpenSearch). |
| `backend/tests/unit/docs/test_template_library_invariants.py` | **Epic-1 invariants only** (no cheatsheet dependency): for each runnable template, **parse the README registration block** to extract its `declared_params` keys, then assert those keys EQUAL the `.search_space.json` keys (NOT derived from the search space on both sides — the README block is the independent source, so a bad `curl` block fails the test; cycle 1, GPT-5.5 F3); assert each `.search_space.json` cardinality < 10⁶ via `SearchSpace` cardinality. |

(The cheatsheet-dependent doc-consistency test is created in Epic 2 / Story 2.4 — see F1 fix — because it asserts against files that don't exist until Epic 2.)

**Modified files**

| File | Change |
|---|---|
| `backend/tests/unit/adapters/test_solr_render.py` | Add cases for `edismax_basic.j2` + `boost_decay.j2`: sample a concrete assignment, call `SolrAdapter.render(...)`, assert flat dict with `defType` + (for boost_decay) a `bf`/`boost` key. |

**Key interfaces** (test-side helpers — reuse existing imports)
```python
# read template body + declared params from the registration block in the README OR a sidecar;
# the test derives declared_params from the .search_space.json keys (which the README block mirrors).
# sample one concrete assignment from the SearchSpace:
from backend.app.domain.study.search_space import SearchSpace  # parse .search_space.json
# compute cardinality via the same SearchSpace semantics used by the study builder
# (search_space.py exposes the cardinality computation referenced in spec §9).
```

**Tasks**
1. Implement the ES render-library test: for each of the four templates, parse `.search_space.json` → `SearchSpace`, sample one concrete value per param, build `params` dict, `render()`, assert native block + JSON parse + no missing/undeclared param.
2. Add the engine-agnostic parametrized assertion (rendered body identical/valid for ES + OpenSearch — same `ElasticAdapter`, lexical DSL).
3. Extend `test_solr_render.py` for the two new Solr templates.
4. Implement `test_template_library_invariants.py`: **parse the README registration block** per template, assert its `declared_params` keys == `.search_space.json` keys, assert cardinality < 10⁶, and assert each ES/OS template's registration block shows a parameterized `ENGINE_TYPE` covering both `elasticsearch` and `opensearch` (cycle 4, GPT-5.5 F1) while Solr blocks use `solr`. (Cheatsheet back-links + README-index rows + snippet JSON are deferred to the Epic-2 doc test per F1.)

**Definition of Done**
- `make test-unit` green with all new cases.
- Each runnable template renders successfully from a sampled `.search_space.json` assignment (FR-6, AC-1, AC-2).
- Epic-1 invariant test enforces registration-block↔search-space key equality (README block parsed independently) + cardinality.

**Epic 1 gate:** 6 runnable templates + 6 `.search_space.json` + 2 samples READMEs + render tests + Epic-1 invariant test all green; 4 existing templates byte-identical. (Cheatsheet doc-consistency runs at the Epic 2 gate, since cheatsheets are created in Epic 2.)

---

## Epic 2 — Cheatsheets + index/tutorial wiring (FR-1b, FR-4, FR-5)

### Story 2.1 — Elasticsearch tunable-params cheatsheet
**Outcome:** `docs/06_vendor_docs/elasticsearch-tunable-params.md` enumerating each ES tunable knob + the kNN/hybrid reference snippets.

**New files**

| File | Purpose |
|---|---|
| `docs/06_vendor_docs/elasticsearch-tunable-params.md` | ~15-20 knob sections (8 unified params + ES-specific: `decay_*`, `rescore_*`, `min_should_match`, `function_score`, etc.). Each: native name + unified name, range/choices + citation (upstream URL + access date), "When to tune", "Caveats", "Templates that use this param". Plus a "Vector & hybrid (reference shapes)" section with engine-correct `knn` + native `rrf`-retriever hybrid snippets, marked "reference — not runnable without query-vector injection". |

**Tasks**
1. Write one section per knob exposed by the four ES/OS runnable templates + the 8 unified params; cite upstream ES docs (URL + access date).
2. Add the kNN + ES-`rrf`-retriever hybrid reference snippets (valid JSON, marked not-runnable).
3. Back-link each knob to the template(s) declaring it.

**DoD:** cheatsheet present; back-links resolve (Story 1.3 test); kNN/hybrid snippets parse as JSON; no OpenSearch-only construct appears in the ES doc.

### Story 2.2 — OpenSearch tunable-params cheatsheet
**Outcome:** `docs/06_vendor_docs/opensearch-tunable-params.md`, including OpenSearch's distinct hybrid construct.

**New files**

| File | Purpose |
|---|---|
| `docs/06_vendor_docs/opensearch-tunable-params.md` | Same structure as 2.1. The "Vector & hybrid (reference shapes)" section uses OpenSearch's **search-pipeline normalization processor** (NOT the ES `rrf` retriever — they are not interchangeable, per FR-1b) + OpenSearch `knn` query. Marked reference-only. |

**Tasks**
1. Mirror 2.1's knob sections for OpenSearch (note the ~90% overlap but call out divergences in "Caveats").
2. Author the OpenSearch-correct hybrid (normalization processor) + `knn` reference snippets.
3. Back-link to templates.

**DoD:** cheatsheet present; hybrid section uses the normalization-processor construct (NOT `rrf`); snippets parse as JSON; back-links resolve.

### Story 2.3 — Apache Solr tunable-params cheatsheet
**Outcome:** `docs/06_vendor_docs/solr-tunable-params.md` grounded in the checked-in Solr ref-guide source.

**New files**

| File | Purpose |
|---|---|
| `docs/06_vendor_docs/solr-tunable-params.md` | Knob sections for the Solr runnable templates' params (`tie`, `mm`, `ps`, `qf`, `bf`/`boost`, `boost_weight`, `decay_scale`) + the unified-vocabulary pivots, citing `docs/06_vendor_docs/solr-9/` + `solr-10/`. Notes that Solr kNN (`{!knn}`) + hybrid are out of scope for the library (no Solr vector template ships). |

**Tasks**
1. Write Solr knob sections citing the checked-in `solr-9/`/`solr-10/` asciidoc source.
2. Back-link to `edismax_basic.j2` + `boost_decay.j2`.
3. State that Solr dense-vector/hybrid templates are not part of this chore (with the rationale).

**DoD:** cheatsheet present; citations point at the checked-in Solr ref-guide; back-links resolve.

### Story 2.4 — Vendor-docs README index + samples README + tutorial wiring
**Outcome:** The three cheatsheets are discoverable; the tutorial points operators at the library.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/docs/test_tunable_params_cheatsheets.py` | **Cheatsheet doc-consistency** (created here, in Epic 2, because it asserts against the cheatsheets + README rows that Stories 2.1-2.4 produce — F1 fix): (a) **required-knob inventory per cheatsheet** (AC-4 — cycle 3, GPT-5.5 F1): each cheatsheet has a section/anchor for all 8 unified params from `adapters.md` PLUS every declared param exposed by that engine's runnable templates; fail if any required knob section is missing; (b) every "Templates that use this param" back-link points at a template declaring that param; (c) the vendor-docs README index has a row per cheatsheet; (d) the FR-1b kNN/hybrid snippets in the ES + OpenSearch cheatsheets parse as JSON; (e) the OpenSearch hybrid snippet uses the normalization-processor construct (not `rrf`). |

**Modified files**

| File | Change |
|---|---|
| `docs/06_vendor_docs/README.md` | Add one index-table row per cheatsheet (Doc / What it covers / Used by). Update/remove the "Coming with later features" line if it would now read stale relative to the new tunable-params docs (they are a distinct kind from the reserved `*-9x.md`/`*-2x.md` version-quirk files — keep that distinction explicit). |
| `docs/08_guides/tutorial-first-study.md` | Add a "Where to go next" section linking the template library (`samples/templates/`) + the engine cheatsheets. |

**Tasks**
1. Add README index rows.
2. Add the tutorial "Where to go next" section.
3. Implement `test_tunable_params_cheatsheets.py` (back-links, README rows, snippet JSON parse, OpenSearch-hybrid-not-`rrf`).

**DoD:** README index has a row per cheatsheet; tutorial section links library + cheatsheets; cheatsheet doc-consistency test green.

**Epic 2 gate:** three cheatsheets present (each engine-correct, back-links resolving, kNN/hybrid snippets valid JSON where applicable); README index rows + tutorial section merged; cheatsheet doc test green.

---

## Epic 3 — Wizard linkage (FR-7, conditional)

### Story 3.1 — Step-3 inline summary + glossary "Learn more" cheatsheet link (conditional)
**Outcome:** When a template is picked in Step 3, a one-line "when to use" summary renders; the `study.search_space` glossary tooltip gains a "Learn more" link to the engine-appropriate cheatsheet. **Ships only if achievable without a migration or new endpoint; otherwise CUT (not deferred).**

**Feasibility gate (run FIRST):**
- The `query_templates` row has no `description` column and this chore adds none. The summary therefore comes from a **static client-side map** `ui/src/lib/template-descriptions.ts` keyed by the recommended template `name` (documented in the README, Story 1.1/1.2). If the registered `name` has no entry, render nothing (no error, no wrong summary).
- The cheatsheet "Learn more" link is engine-specific, so it MUST be resolved at the modal call site where `selectedCluster.engine_type` is in scope and passed as a prop into `InfoTooltip` — NOT stored statically on the engine-agnostic glossary entry (cycle 3, GPT-5.5 F2). Add an optional `learnMoreHref` prop to `InfoTooltip` (frontend-only, no backend change) and a `cheatsheetUrlFor(engineType)` resolver keyed on the three `SUPPORTED_ENGINE_TYPES`. `glossary.ts` itself is unchanged.
- **Both-or-neither (spec AC-6):** the inline summary AND the glossary cheatsheet link ship together client-side, OR the entire FR-7 UI portion is cut. No partial shipment. If either piece would need a migration/endpoint or a non-trivial shared-tooltip refactor, CUT both — README + cheatsheets remain the deliverable.

**New files (only if shipping)**

| File | Purpose |
|---|---|
| `ui/src/lib/template-descriptions.ts` | `Record<string, string>` keyed by recommended template `name` → one-line summary (`// Source: samples/templates/README.md`, graceful miss = no render), PLUS `cheatsheetUrlFor(engineType: 'elasticsearch'|'opensearch'|'solr'): string` resolving the engine cheatsheet URL (`// Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES`). |

**Modified files (only if shipping)**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | After the Step-3 template `<select>` (existing picker label "Query template (filtered by engine)" at line ~978), render the summary from `template-descriptions.ts` keyed by the selected template `name`; render nothing on a miss. Where the cheatsheet link is shown, resolve the URL from `selectedCluster.engine_type` (already in scope at line ~384). |
| `ui/src/components/common/info-tooltip.tsx` | Extend `InfoTooltip` (function at line 41) to accept an OPTIONAL `learnMoreHref?: string` PROP and render it as a focusable link. The href is passed IN by the caller — NOT read from a static glossary entry (cycle 3, GPT-5.5 F2: a global glossary entry cannot know the selected cluster's engine, so the cheatsheet link must be resolved at the call site where `selectedCluster.engine_type` is in scope). (If this needs a non-trivial shared-tooltip refactor, CUT both summary + link per the feasibility gate.) |
| `ui/src/components/studies/create-study-modal.tsx` (FR-7 link wiring) | Where the `study.search_space` InfoTooltip is rendered in the modal, pass `learnMoreHref={cheatsheetUrlFor(selectedCluster.engine_type)}` using a small local resolver. |

**Engine→cheatsheet resolver:** add a `cheatsheetUrlFor(engineType)` helper (in `template-descriptions.ts` or a sibling) that maps each of `elasticsearch`/`opensearch`/`solr` to its cheatsheet path, with a `// Values must match backend/app/adapters/registry.py SUPPORTED_ENGINE_TYPES` comment. Do NOT store a static `learnMoreHref` on the glossary entry — the glossary is engine-agnostic; the engine-specific href is supplied at the modal call site. (This means `glossary.ts` and `guide/glossary/page.tsx` need NO change for FR-7 — removed from the modified-files list per F2.)

**Enumerated value contract** (per spec §7.4): the `engine_type`→cheatsheet mapping MUST use exactly `elasticsearch`, `opensearch`, `solr` (source: `backend/app/adapters/registry.py:27` `SUPPORTED_ENGINE_TYPES`). The description map is keyed by free-text `name`, not an enum — no allowlist drift.

**Legacy behavior parity:** No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated (this story ADDS a summary line + a tooltip link to the existing modal).

**Tasks**
1. Run the feasibility gate. If infeasible → mark FR-7 CUT in the PR + decision log, skip to DoD.
2. (If shipping) add `template-descriptions.ts` + render the inline summary with graceful-miss.
3. (If shipping) add the glossary cheatsheet link keyed by `engine_type` with the source-of-truth comment.
4. (If shipping) add ONE assertion to an existing real-backend modal test (or vitest component test) that the summary text appears after picking a known template — no `page.route()` mocking.

**Definition of Done**
- Either: summary + glossary link ship client-side with no migration/endpoint AND a test asserts the summary renders for a known template AND degrades gracefully on a miss; OR: FR-7 UI is explicitly CUT with a decision-log note. (AC-6.)
- No `query_templates` migration, no new endpoint (AC-5) regardless of which branch is taken.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/adapters/`, `backend/tests/unit/docs/`
- Tasks:
  - [ ] `test_elastic_render_library.py` — one render case per ES/OS template (sampled assignment → `render()` → native block); engine-agnostic parametrized assertion. (Story 1.3)
  - [ ] Extend `test_solr_render.py` for the two Solr templates. (Story 1.3)
  - [ ] `test_template_library_invariants.py` — parse each README registration block, assert its `declared_params` keys == `.search_space.json` keys, assert cardinality < 10⁶. (Story 1.3, Epic 1 — no cheatsheet dependency)
  - [ ] `test_tunable_params_cheatsheets.py` — cheatsheet back-links, README-index rows, kNN/hybrid snippet JSON parse, OpenSearch-hybrid-not-`rrf`. (Story 2.4, Epic 2 — asserts against cheatsheets that exist only after Epic 2)
- DoD: every runnable template renders from its starter space; all invariants test-enforced; Epic-1 invariants do not depend on Epic-2 artifacts.

### 3.2 Integration tests
- N/A — no DB-backed path added. Explicitly out of scope (content + docs chore).

### 3.3 Contract tests
- N/A — no endpoint added. Existing `query_templates` contract unchanged.

### 3.4 E2E tests
- N/A by default. IF FR-7 ships, a single existing-suite assertion (summary text appears after picking a template) may be added against the real backend — no new E2E suite, no `page.route()` mocking.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/adapters/test_solr_render.py` | Solr render assertions | 1 | Extend (add 2 templates) — no existing assertion changes |
| `backend/tests/unit/adapters/test_elastic_render.py` | ES render | 1 | No change — new templates get a NEW test file; existing cases untouched |
| `backend/tests/smoke/test_tutorial_path.py` | reads `product_search.j2` | 1 | No change — `product_search.j2` is byte-identical (AC-3) |
| `backend/app/services/demo_seeding.py` (not a test) | reads `product_search.j2` at :1248 | 1 | No change — path + file untouched (AC-3) |

### 3.5 Migration verification
- N/A — no schema change (AC-5). The plan-consistency review explicitly verifies no Alembic revision is added.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make lint` / `make fmt`
- [ ] `cd ui && pnpm test` (only if FR-7 ships)

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — [ ] add the merge one-liner (newest-first) when finalized; no Alembic head change (no migration); note the new library + cheatsheets.
- **`architecture.md`** — [ ] optional: a one-line pointer that `docs/06_vendor_docs/` now holds per-engine tunable-params cheatsheets and `samples/templates/` holds a curated runnable library. No new service/flow/invariant.
- **`CLAUDE.md`** — [ ] no change required (no new convention/rule/env var; the template-authoring rules already live in `samples/templates/README.md`).

### 4.1 Architecture docs — [ ] no change (adapters.md vocabulary unchanged; cheatsheets cite it).
### 4.2 Product docs — [ ] no change.
### 4.3 Runbooks — [ ] no change.
### 4.4 Security docs — [ ] no change (no secrets, no new data flow).
### 4.5 Quality docs — [ ] no change (the render/doc tests are covered by the existing unit-test convention).

**Documentation DoD**
- [ ] `samples/templates/README.md` + `samples/templates/solr/README.md` + the three cheatsheets + the vendor README index + tutorial "Where to go next" are consistent with the shipped templates.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- None. This is additive content + tests.

### 5.2 Planned refactor tasks
- [ ] None.

### 5.3 Refactor guardrails
- [ ] Lint/typecheck green.
- [ ] No source under `backend/app/` modified by Epics 1-2 (only `backend/tests/` + `samples/` + `docs/`).
- [ ] Discovered debt (the stale `query_template.py` docstring + `list_templates.py` missing `solr` Literal) is NOT fixed here — recommend a separate one-line `chore_` (or fold into `chore_solr_post_pipeline_followups`) per spec §19.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `ElasticAdapter.render` / `SolrAdapter.render` | Story 1.3 | implemented | tests can't run |
| `SearchSpace` + cardinality semantics (`search_space.py`) | Story 1.3 | implemented | can't sample assignment / compute cardinality |
| `docs/06_vendor_docs/solr-9|10/` ref-guide source | Story 2.3 | implemented | Solr cheatsheet lacks primary citation |
| Glossary link-field support | Story 3.1 | absent today (feasibility gate) | FR-7 UI cut |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A template renders valid JSON but invalid engine DSL (unit test can't catch live rejection) | M | M | Constrain runnable set to lexical/function-score/rescore shapes known-valid on both ES + OpenSearch; cite upstream docs; live validation deferred (no guaranteed service container in `pr.yml`). |
| `boost_decay.j2` `bf` string mis-renders the Solr function | M | M | Render test asserts a `bf`/`boost` key is produced; ground the function in the Solr ref-guide. |
| FR-7 description map drifts from README | L | L | Source-of-truth comment + graceful-miss render; no wrong summary ever shown. |
| Operator clutters Step-3 picker by registering all 6 | L | L | Intentional no-auto-seed; operators register only what they tune. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Render test fails: missing param | `.search_space.json` keys ≠ declared params | `MissingDeclaredParamError`/`UnknownSearchSpaceParamError` surfaces in the test | fix the `.j2`/`.search_space.json` to equality |
| Cardinality > 10⁶ | starter space too wide | doc-consistency test fails | narrow the starter space |
| kNN/hybrid snippet invalid JSON | malformed cheatsheet snippet | doc-consistency test fails | fix the snippet |
| Operator registers with `body` = path | following a bad README example | API 422 (path is not Jinja source) | README mandates `curl`+`jq` reading the `.j2` into `body` |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (templates + starter spaces + render/doc tests) — foundational; cheatsheets back-link to these templates.
2. Epic 2 (cheatsheets + index/tutorial) — depends on Epic 1 template names for back-links.
3. Epic 3 (FR-7, conditional) — depends on Epic 1 recommended `--name` join keys + Epic 2 cheatsheet paths.

### Parallelization
- Stories 1.1 and 1.2 (ES/OS vs Solr templates) are independent and can run in parallel.
- Stories 2.1/2.2/2.3 (three cheatsheets) are independent once the template names exist.

## 8) Rollout and cutover plan

- Rollout: none — additive content. No feature flag, no migration, no cutover.
- Discoverability: templates appear in Step-3 only after an operator registers them; cheatsheets are browse/docs-site content.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — ES/OS templates + starter spaces + README registration blocks
- [ ] Story 1.2 — Solr templates + starter spaces + solr/README.md
- [ ] Story 1.3 — render-validation + doc-consistency tests
- [ ] Story 2.1 — ES cheatsheet (+ kNN/hybrid ref snippets)
- [ ] Story 2.2 — OpenSearch cheatsheet (+ normalization-processor hybrid snippet)
- [ ] Story 2.3 — Solr cheatsheet
- [ ] Story 2.4 — vendor README index + samples README + tutorial
- [ ] Story 3.1 — FR-7 (conditional: ship or cut with decision-log note)

### Blocked items
- None.

## 10) Story-by-Story Verification Gate

- [ ] Files created/modified match story scope.
- [ ] No source under `backend/app/` modified by Epics 1-2; no migration; no new endpoint.
- [ ] Render-validation tests pass (each template renders from a sampled `.search_space.json` assignment).
- [ ] Doc-consistency tests pass (equality, cardinality, back-links, README rows, snippet JSON).
- [ ] Four existing demo templates byte-identical (`git diff --stat`).
- [ ] `make test-unit` + `make lint` green; `pnpm test` green if FR-7 shipped.
- [ ] FR-7 explicitly shipped-or-cut with a decision-log note.

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** spec §7.1 = 0 new endpoints; plan adds 0. ✔ Match.
2. **Spec ↔ plan FR coverage:** FR-1, FR-1b, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7 each mapped in §1 + assigned to a story. ✔
3. **Story internal consistency:** No file is created by two stories (templates in 1.1/1.2; tests in 1.3; cheatsheets in 2.1-2.3; FR-7 files in 3.1). Modified files (`samples/templates/README.md`, `docs/06_vendor_docs/README.md`, `tutorial-first-study.md`, `test_solr_render.py`, `create-study-modal.tsx`, `glossary.ts`) verified to exist (or explicitly NEW: `solr/README.md`, `test_elastic_render_library.py`, `test_tunable_params_cheatsheets.py`, `template-descriptions.ts`). ✔
4. **Test file count:** Epic 1 = 2 new (`test_elastic_render_library.py`, `test_template_library_invariants.py`) + 1 extended (`test_solr_render.py`), all assigned to Story 1.3. Epic 2 = 1 new (`test_tunable_params_cheatsheets.py`), assigned to Story 2.4. Total = 3 new + 1 extended; 0 contract/integration/E2E (justified N/A); a conditional UI assertion to Story 3.1. (Arithmetic corrected after the Epic-2 test split — cycle 3, GPT-5.5 F3.) ✔
5. **Gate arithmetic:** Epic 1 gate = 6 runnable templates + 6 search spaces + 2 READMEs (matches Stories 1.1+1.2+1.3). Epic 2 gate = 3 cheatsheets + index + tutorial (matches 2.1-2.4). ✔
6. **Open questions resolved:** spec §19 has zero open questions; all forks locked in the decision log. ✔
7. **Plan ↔ codebase verification:** `test_elastic_render.py`, `test_solr_render.py`, `backend/tests/unit/docs/` exist (verified `ls`). `create-study-modal.tsx:978` picker label "Query template (filtered by engine)" + `engine_type` in scope at line ~384 verified. `InfoTooltip` at `ui/src/components/common/info-tooltip.tsx:41` (verified — FR-7 gains an optional `learnMoreHref` prop here; `glossary.ts` is NOT modified — the engine-specific href is resolved at the modal call site, not stored on the glossary entry). `SUPPORTED_ENGINE_TYPES` at `registry.py:27` = `{elasticsearch, opensearch, solr}` (verified). `validate_against_template` equality enforcement at `search_space.py:230-246` (verified). `demo_seeding.py:1248` reads `product_search.j2` (verified — drives AC-3). ✔
8. **Infrastructure path verification:** no migration dir touched (no migration). Test dirs verified (`backend/tests/unit/adapters/`, `backend/tests/unit/docs/`). ✔
9. **Frontend data plumbing:** FR-7 summary sourced from a static client map keyed by template `name` (already available in the picker via `useTemplates`); cheatsheet link keyed by `selectedCluster.engine_type` (already in the modal at line ~384). ✔
10. **Persistence scope:** N/A — no localStorage/sessionStorage.
11. **Enumerated value contract audit:** the only enum is `engine_type` (`registry.py:27` `SUPPORTED_ENGINE_TYPES` = `elasticsearch/opensearch/solr`); FR-7's engine→cheatsheet mapping must match exactly with a source-of-truth comment. The description map is `name`-keyed (free text), no allowlist. ✔
12. **Admin control audit:** N/A — no admin/tenant model (MVP2).
13. **Audit-event coverage audit:** N/A — no state-mutating endpoint/service added (spec §6). ✔

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, Tasks, DoD (Endpoints/Schemas N/A — no API surface).
- [x] Test layers scoped (unit + doc-consistency; integration/contract/E2E justified N/A).
- [x] Documentation updates planned.
- [x] Lean refactor scope (none) + guardrails explicit.
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed — no unresolved findings.

---

## Cross-model review log (GPT-5.5)

**Reviewer:** GPT-5.5 (`gpt-5.5` via OpenAI Chat Completions, `max_completion_tokens`). Plan sent with the full spec as context. Two passes (A: Structural & Contract, B: Implementation & Risk).

### Cycle 1 — 3 findings (2 Medium, 1 Low) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | B | Med | Epic-1 gate requires the doc-consistency test green, but that test (Story 1.3) checks cheatsheets/index/snippets that don't exist until Epic 2 — circular sequencing. | **Accept.** Split the test: Epic-1 `test_template_library_invariants.py` (template/search-space/cardinality only) at the Epic-1 gate; cheatsheet `test_tunable_params_cheatsheets.py` moved to Story 2.4 / Epic-2 gate. |
| F2 | B | Med | FR-7 adds a glossary link field + InfoTooltip rendering but doesn't list the InfoTooltip/type files; ambiguous whether frontend-only glossary-link support is in scope. | **Accept.** Confirmed frontend-only glossary support is the spec's intended path (no backend change). Listed `glossary.ts` (types at 23/27), `info-tooltip.tsx:41`, `guide/glossary/page.tsx:214` in FR-7 modified files; clarified the CUT trigger is only a non-trivial shared-tooltip refactor. |
| F3 | A | Low | Story 1.3 hinted the test could derive `declared_params` from `.search_space.json` on both sides → self-validating, wouldn't catch a bad README `curl` block. | **Accept.** `test_template_library_invariants.py` now PARSES the README registration block independently and compares its `declared_params` to the `.search_space.json` keys. |

### Cycle 2 — 1 finding (1 Medium) — Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | B | Med | Plan Story 3.1 allowed partial FR-7 shipment ("summary and link independent"), contradicting spec AC-6's both-or-neither. | **Accept.** Story 3.1 feasibility gate now states both-or-neither matching AC-6: summary + glossary link ship together client-side, or the entire FR-7 UI is cut. Aligned plan to spec (kept the stricter AC-6 rule). |

### Cycle 3 — 3 findings (3 Medium) — all Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | AC-4 cheatsheet-completeness (8 unified params + per-engine knobs) not test-enforced. | **Accept.** `test_tunable_params_cheatsheets.py` gains a required-knob inventory assertion per cheatsheet. |
| F2 | B | Med | A static `learnMoreHref` on a global glossary entry can't know the selected cluster's engine. | **Accept.** Cheatsheet link is now resolved at the modal call site via `cheatsheetUrlFor(selectedCluster.engine_type)` and passed as an `InfoTooltip` prop; `glossary.ts` is NOT modified. |
| F3 | A | Med | §11 test-file arithmetic stale after the Epic-2 test split. | **Accept.** §11 item 4 corrected: Epic 1 = 2 new + 1 extended; Epic 2 = 1 new; total 3 new + 1 extended. |

### Cycle 4 — 1 finding (1 Medium) — Accepted

| # | Pass | Sev | Finding | Adjudication |
|---|---|---|---|---|
| F1 | A | Med | ES/OS templates serve both engines but `engine_type` is single-valued per row; Story 1.1 didn't say how the registration block sets it (Solr blocks said `solr`). | **Accept.** Story 1.1 now requires a parameterized `ENGINE_TYPE="elasticsearch" # or opensearch` in each ES/OS block (register once per engine run); the invariant test asserts both engine types are covered. |

### Cycle 5 — 0 findings — convergence confirmed

GPT-5.5 returned an empty findings set on the corrected plan (High-only final pass). The cross-model loop converged: cycles 1-4 produced 8 findings total (5 Medium, 3 across passes), all Accepted and applied; no contract/structure/test-assignment change remained after cycle 4. Plan **Ready for Execution**.
