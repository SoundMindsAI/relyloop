# Curated template library + per-engine tunable-params cheatsheet

**Date:** 2026-05-19
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19.
**Priority:** P2 — UX nicety. Unblocks "tune any parameter" without forcing operators to write Jinja from scratch, but the current single-template tutorial works; not a felt blocker.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). The sample set ships a small fixed set of demo templates: [`samples/templates/product_search.j2`](../../../../../samples/templates/product_search.j2) (ES/OpenSearch `multi_match`) plus three Solr variants added by `infra_adapter_solr` (shipped 2026-05-31) under [`samples/templates/solr/`](../../../../../samples/templates/solr/) — `products_edismax.j2`, `products_dismax.j2`, `products_lucene.j2`. All four are tuned for the tutorial's narrow 3-float `*_boost` demonstration (intentionally tiny to stay under the 10⁶ cardinality cap; `tie_breaker`/`fuzziness` hard-coded on the ES one). They cover lexical retrieval only. Adding a parameter shape that isn't already on a demo template (function-score decay, knn, RRF hybrid, phrase rescore) means writing a Jinja template from scratch. Without a curated library that covers the common shapes (basic lexical, function-score, bool-boosted, knn-only, hybrid lexical+vector, phrase rescore), the "tune any parameter you need" pitch is technically true but practically blocked behind a research project per new tuning surface.

> **Preflight correction (2026-06-02):** the original idea claimed "exactly one template." Verified against `samples/templates/`: there are now **four** demo templates (one ES/OS + three Solr), all shipped before this idea entered the pipeline. The gap is real but narrower than stated — what's missing is **shape variety** (decay / knn / hybrid / rescore), not template count. The new library complements the existing four rather than replacing the single `product_search.j2`.

**Depends on:** None — the `query_templates` resource is shipped, and the four sibling features this idea originally listed as pairings have **all shipped already** (see "Relationship to other work"). No remaining blockers.

## Problem

Three connected gaps:

1. **Only lexical shapes in the box.** [`samples/templates/`](../../../../../samples/templates/) contains four demo templates (one ES/OS `multi_match`, three Solr `defType` variants), all lexical-only. A relevance engineer who wants to tune `knn.num_candidates`, RRF weights, decay-function scale, or rescore-window size must hand-write the Jinja from scratch — and the per-engine quirks (ES vs OpenSearch hybrid syntax differences, RRF availability across versions, Solr's `{!knn}`/`{!ltr}` parser surface) live only in vendor docs.

2. **No "canonical knobs" cheatsheet.** The unified parameter vocabulary in [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) §"Cross-engine parameter naming" maps unified names to per-engine native syntax (ES/OpenSearch `multi_match` and Solr `edismax` columns) for the *eight* core params (`field_boosts`, `phrase_field_boosts`, `tie_breaker`, `min_should_match`, `fuzziness`, `slop`, `boost_fn`, `rerank_model`). Helpful for engine adapter authors; insufficient for a relevance engineer who needs to know "for Elasticsearch 8.11+, the standard tunable knobs are X, Y, Z, with typical ranges A–B." That document doesn't exist.

3. **No engine-specific awareness in the wizard.** When the user picks a cluster of `engine_type: opensearch` in Step 1, Step 3 (template selection) is filtered by engine type (confirmed: `ui/src/components/studies/create-study-modal.tsx:383` calls `useTemplates({ engine_type })`) — but Step 4 (search space) has no awareness that OpenSearch 2.x doesn't support some of the same RRF syntax as ES 8.11+, nor that Solr uses a different hybrid construct entirely. The cheatsheet would be the source of truth for these distinctions.

### Architectural note (preflight 2026-06-02)

Two render contracts exist, and the template set must respect both:

- **ES / OpenSearch** (`backend/app/adapters/elastic.py:521 render()`): the Jinja body renders to a **raw engine-native Query DSL body** that is passed straight to `_msearch` — there is NO unified-param pivot for the Elastic adapter. So an ES template author writes native `knn`/`function_score`/`rescore`/`rrf` DSL directly. This makes every proposed shape feasible on ES/OS as long as the rendered JSON is valid native DSL.
- **Solr** (`backend/app/adapters/solr.py render()`): the Jinja body renders to a **flat Solr request-parameter dict** that mixes Solr-native keys (`defType`, `q`, `qf`, `pf`, `tie`, `mm`, `bf`, `boost`, `rq`, ...) with unified pivot keys (`field_boosts`→`qf`, `boost_fn`→`bf`/`boost`, `rerank_model`→`rq={!ltr ...}`). Solr templates live under `samples/templates/solr/`.

Consequence: the library cannot ship one `.j2` per shape that works on all three engines. Lexical/function-score/bool shapes get **both** an ES/OS top-level template and a Solr-subdir template; vector (knn / hybrid RRF) shapes are ES/OS-only in this chore because Solr's dense-vector + hybrid surface is materially different and is owned by a separate future effort. The spec locks exactly which shapes ship per engine.

## Proposed capabilities

### Expand the curated template library

Ship 5–6 templates under [`samples/templates/`](../../../../../samples/templates/) covering the common search shapes. Each template has:

- A Jinja body with sensible default branches (`{% if %}` for optional clauses).
- A populated `declared_params` dict with one line of description per param.
- A `README.md` next to the template explaining when to use it, expected metric ceiling, and known caveats.
- A small `default_search_space.json` checked in alongside — the "good starter" ParamSpec dict that the wizard's auto-fill heuristic might land on, but human-tuned for that specific template.

Initial set (the spec LOCKS the exact set — this table is the preflight-recommended starting point, refined to respect the two render contracts above):

| Template | Engine(s) | Purpose | Key tunable params |
|---|---|---|---|
| `multi_match_basic.j2` (top level) + `solr/edismax_basic.j2` | ES/OS + Solr | Basic lexical (extends the existing `product_search.j2` shape — does NOT rename it) | ES/OS: `field_boosts.*`, `tie_breaker`, `fuzziness`, `slop` · Solr: `field_boosts.*`, `tie`, `mm`, `ps` |
| `function_score_decay.j2` (top level) + `solr/boost_decay.j2` | ES/OS + Solr | Recency / proximity boosting | ES/OS: `decay_scale`, `decay_offset`, `decay_decay`, `boost_mode` · Solr: `bf` recip/decay via `boost_fn` pivot |
| `bool_boosted.j2` | ES/OS | `must` / `should` / `filter` with `minimum_should_match` | `min_should_match`, `should_clause_boost.*` |
| `knn_only.j2` | ES/OS | Pure vector retrieval | `knn_k`, `knn_num_candidates`, `knn_boost` |
| `hybrid_rrf.j2` | ES/OS | Lexical + vector with Reciprocal Rank Fusion (RRF) | `rrf_window_size`, `rrf_rank_constant`, `lexical_weight`, `vector_weight` |
| `rescore_phrase.j2` | ES/OS | First-pass lexical + second-pass phrase rescore | `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop` |

Param names are FLAT (no dots) per the Jinja sandbox rule — `knn_num_candidates`, not `knn.num_candidates`; the `field_boosts.*` shorthand denotes a flat `field_boosts` dict, which is the one nested-dict exception the adapters already handle. The exact engine split + flat param names are locked in the spec.

Seeding (preflight correction): templates are NOT seeded by reading `samples/templates/*.j2` generically. `scripts/install.sh` runs `scripts/seed_meaningful_demos.py --if-empty`, which builds templates from **inline bodies in the seed script** (verified: `scripts/seed_meaningful_demos.py` has hard-coded template bodies). Only the demo-reseed path in `backend/app/services/demo_seeding.py:1248` reads one file (`product_search.j2`) from disk. The spec must decide whether new library templates are (a) shipped as files-on-disk that operators register manually via `POST /api/v1/query-templates` / the UI, or (b) auto-seeded. **Locked default: (a) files-on-disk, no auto-seed** — auto-seeding six extra templates into every demo install would clutter the tutorial's Step-3 picker and inflate `seed_meaningful_demos.py`. The README documents the one-line registration command per template.

### Per-engine tunable-params cheatsheet

The vendor-docs directory already exists: [`docs/06_vendor_docs/`](../../../../06_vendor_docs/) (with `README.md` index + `solr-9/`, `solr-10/`, `relevance-tools/` subdirs). Its README "Coming with later features" section reserves `elasticsearch-9x.md` / `opensearch-2x.md` for version-quirk notes — those are a different doc kind. This idea adds **three** tunable-params cheatsheets (one per supported engine), named to avoid colliding with the reserved version-quirk filenames:

- `docs/06_vendor_docs/elasticsearch-tunable-params.md`
- `docs/06_vendor_docs/opensearch-tunable-params.md`
- `docs/06_vendor_docs/solr-tunable-params.md`

Three docs even though ES/OpenSearch overlap ~90% — the divergence points (ES 8.11+ native `rrf` retriever vs OpenSearch 2.x normalization-processor hybrid; Solr's entirely different `{!knn}`/`{!ltr}` surface) are the whole reason engine-specific vendor docs exist. The README index table gains a row per new doc.

Each cheatsheet has one section per tunable knob with:

- Native engine name + RelyLoop unified name (if different).
- Typical range / valid choices, with citation to the engine's reference docs.
- "When to tune" — one-line guidance on which kinds of relevance problems this knob addresses.
- "Caveats" — version availability, performance cliffs, common misconfigurations.
- "Templates that already use this param" — back-link into the library so the engineer can pick a template that exposes it.

Scope of knobs: the 8 unified-vocabulary params (from adapters.md §"Cross-engine parameter naming") plus the ~10 engine-specific ones the new templates expose (`knn_*`, `rrf_*`, `decay_*`, `rescore_*`, function-score `script_score`, Solr `bf`/`boost`/`{!ltr}`, etc.). Aim for ~15–20 entries per engine. The Solr cheatsheet is grounded in the already-checked-in Solr ref-guide source at `docs/06_vendor_docs/solr-9/` and `solr-10/`.

### Linkage from the wizard and tutorial

- The `search_space` glossary entry (shipped in `chore_create_study_wizard_polish` + `feat_create_study_search_space_builder`; key present in `ui/src/lib/glossary.ts`) gains a "Learn more" link to the engine-appropriate cheatsheet based on the selected cluster's `engine_type`.
- The tutorial at [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) gains a new "Where to go next" section pointing at the library and cheatsheet.
- The Step-3 template-picker shows the template's `README.md` summary inline (one-line "when to use this template" copy) so users can pick informed instead of guessing from the template name. **Preflight scope note:** the picker is engine-filtered today but renders only template name/version — adding an inline one-line summary requires the description to be available client-side. Since `query_templates` has no `description` column and this chore adds NO migration, the spec routes the one-liner through the template `README.md` content surfaced via the existing `GET /api/v1/query-templates` response (or, if that's not plumbed, defers the inline-summary UI to a follow-up and ships the README files + cheatsheets as the core deliverable). The spec locks this fork.

## Scope signals

- **Backend:** ~0–30 LOC. NO seed-script change (locked: files-on-disk, manual registration — see Seeding correction above). Templates are content. A render-validation unit test per template is the only backend code.
- **Frontend:** ~0–80 LOC. The Step-3 inline-summary UI is a locked fork (ship only if the template description is plumbable without a migration; otherwise defer to a follow-up). The cheatsheet "Learn more" link in the glossary entry is small if the glossary supports a link field. Cheatsheet docs are markdown.
- **Migration:** none. (No `query_templates` column added — the inline-summary fork is resolved without schema change.)
- **Config:** none.
- **Audit events:** N/A — this chore adds no state-mutating endpoint or service path. Operator template registration goes through the existing `POST /api/v1/query-templates`, whose audit posture is unchanged by this chore.
- **Content:** ~8 Jinja files (6 ES/OS top-level + 2 Solr-subdir for the lexical/decay shapes) × ~40–60 lines + per-template README sections + 3 cheatsheet docs (~300–400 lines each). Each Jinja template needs a render-validation test (renders against its declared params, produces valid native DSL / Solr param dict, parses as JSON); reuse the render unit-test harness already used by `backend/tests/unit/adapters/test_solr_render.py` and the ES render tests.

## Why not implemented inline today

Three reasons:

1. **Content-heavy, opinionated.** Picking the "right" six templates and writing accurate per-engine cheatsheets is a domain-expertise call worth a spec round, not a single-LOC change. The wrong templates ship dead weight; the wrong cheatsheet entries get cited as canonical and propagate misunderstanding.
2. **Cross-version validation.** Each template needs to be exercised against both ES 8.11+ and OpenSearch 2.x to confirm the syntax works on both engines (or to explicitly document where they diverge). That's integration-test work, not a doc PR.
3. **~~Best landed after `chore_create_study_wizard_polish`.~~** *(Obsolete as of preflight 2026-06-02 — that feature shipped 2026-05-20.)* The glossary, builder UI, and propose-search-space heuristic all exist now, so the sequencing rationale that originally deferred this idea is satisfied. This idea is now unblocked: the substrate it was meant to "land after" is in `main`.

## Relationship to other work

All four features this idea originally listed as pairings/dependencies have **shipped** (verified in `docs/00_overview/implemented_features/`):

- **Built on** `chore_create_study_wizard_polish` (shipped 2026-05-20). Adds the "Learn more" cheatsheet link to the wizard's already-shipped `search_space` glossary entry.
- **Built on** `feat_create_study_search_space_builder` (shipped 2026-05-20). The builder's per-type rendering already handles the `declared_params` shapes; richer templates exercise more of that surface.
- **Built on** `feat_agent_propose_search_space` (shipped 2026-05-21). A richer template library gives the agent's `propose_search_space` tool more substrate to ground recommendations against.
- **Independent of** `feat_study_clone_from_previous` (shipped 2026-05-25) — cloning works on whatever templates exist.
- **Sibling in flight:** `chore_ubi_hybrid_template_render` (`02_mvp2/`) touches hybrid template rendering — coordinate so the `hybrid_rrf.j2` library template and that chore's render path agree on param names. Coordinate-only, not blocking.
