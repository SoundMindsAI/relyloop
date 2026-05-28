# Curated template library + per-engine tunable-params cheatsheet

**Date:** 2026-05-19
**Status:** Idea — surfaced during a UX review of parameter-tuning ergonomics on 2026-05-19.
**Priority:** P2 — UX nicety. Unblocks "tune any parameter" without forcing operators to write Jinja from scratch, but the current single-template tutorial works; not a felt blocker.
**Origin:** Parameter-tuning UX review (conversation 2026-05-19). The MVP1 sample set ships exactly one template — [`samples/templates/product_search.j2`](../../../../../samples/templates/product_search.j2) — built for the tutorial's narrow demonstration (`tie_breaker` + `fuzziness` only, intentionally tiny to stay under the 10⁶ cardinality cap). Adding a parameter that isn't already on a template means writing a Jinja template from scratch. Without a curated library that covers the common shapes (basic lexical, function-score, hybrid lexical+vector, knn-only, knn-hybrid), the "tune any parameter you need" pitch is technically true but practically blocked behind a research project per new tuning surface.
**Depends on:** None for the templates themselves (the `query_templates` resource is shipped). Optional pairing with `chore_create_study_wizard_polish` for the glossary deep-links into the cheatsheet doc.

## Problem

Three connected gaps:

1. **One template in the box.** [`samples/templates/`](../../../../../samples/templates/) contains a single demo template. A relevance engineer who wants to tune `knn.num_candidates`, RRF weights, decay-function scale, or rescore-window size must hand-write the Jinja from scratch — and the per-engine quirks (ES vs OpenSearch hybrid syntax differences, RRF availability across versions) live only in vendor docs.

2. **No "canonical knobs" cheatsheet.** The unified parameter vocabulary in [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) §"Cross-engine parameter naming" maps unified names to per-engine native syntax for the *eight* core params (`field_boosts`, `phrase_field_boosts`, `tie_breaker`, `min_should_match`, `fuzziness`, `slop`, `boost_fn`, `rerank_model`). Helpful for engine adapter authors; insufficient for a relevance engineer who needs to know "for Elasticsearch 8.11+, the standard tunable knobs are X, Y, Z, with typical ranges A–B." That document doesn't exist.

3. **No engine-specific awareness in the wizard.** When the user picks a cluster of `engine_type: opensearch` in Step 1, Step 3 (template selection) is filtered by engine type — but Step 4 (search space) has no awareness that OpenSearch 2.x doesn't support some of the same RRF syntax as ES 8.11+. The cheatsheet would be the source of truth for these distinctions.

## Proposed capabilities

### Expand the curated template library

Ship 5–6 templates under [`samples/templates/`](../../../../../samples/templates/) covering the common search shapes. Each template has:

- A Jinja body with sensible default branches (`{% if %}` for optional clauses).
- A populated `declared_params` dict with one line of description per param.
- A `README.md` next to the template explaining when to use it, expected metric ceiling, and known caveats.
- A small `default_search_space.json` checked in alongside — the "good starter" ParamSpec dict that the wizard's auto-fill heuristic might land on, but human-tuned for that specific template.

Initial set (open to debate during spec):

| Template | Purpose | Key tunable params |
|---|---|---|
| `multi_match_basic.j2` | Existing `product_search.j2` rebranded | `field_boosts.*`, `tie_breaker`, `fuzziness`, `slop` |
| `function_score_decay.j2` | Recency / proximity boosting | `decay_scale`, `decay_offset`, `decay_decay_value`, `boost_mode` |
| `bool_boosted.j2` | `must` / `should` / `filter` with `minimum_should_match` | `min_should_match`, `should_clause_boost.*` |
| `knn_only.j2` | Pure vector retrieval | `knn.k`, `knn.num_candidates`, `knn.similarity` |
| `hybrid_rrf.j2` | Lexical + vector with Reciprocal Rank Fusion | `rrf_window_size`, `rrf_rank_constant`, lexical/vector weight |
| `rescore_phrase.j2` | First-pass lexical + second-pass phrase rescore | `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop` |

The seed script ([`scripts/install.sh`](../../../../../scripts/install.sh) or the tutorial bootstrap) installs all six by default so new operators see them in Step 3 immediately.

### Per-engine tunable-params cheatsheet

Add `docs/06_vendor_docs/elasticsearch-tunable-params.md` and `docs/06_vendor_docs/opensearch-tunable-params.md` (note: separate docs even if 90% overlap — the divergence points are the whole reason vendor docs exist).

Each cheatsheet has one section per tunable knob with:

- Native engine name + RelyLoop unified name (if different).
- Typical range / valid choices, with citation to the engine's reference docs.
- "When to tune" — one-line guidance on which kinds of relevance problems this knob addresses.
- "Caveats" — version availability, performance cliffs, common misconfigurations.
- "Templates that already use this param" — back-link into the library so the engineer can pick a template that exposes it.

Scope of knobs: the 8 unified-vocabulary params plus the ~10 engine-specific ones that the new templates expose (`knn.*`, `rrf_*`, `decay_*`, `rescore_*`, function-score `script_score`, etc.). Aim for ~15–20 entries per engine.

### Linkage from the wizard and tutorial

- The `search_space` glossary entry from `chore_create_study_wizard_polish` links to the engine-appropriate cheatsheet based on the selected cluster's `engine_type`.
- The tutorial at [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) gains a new "Where to go next" section pointing at the library and cheatsheet.
- The Step-3 template-picker shows the template's `README.md` summary inline (one-line "when to use this template" copy) so users can pick informed instead of guessing from the template name.

## Scope signals

- **Backend:** ~50 LOC. Seed script change to install the new templates on `make up` (or update the existing seed flow). Templates themselves are content, not code.
- **Frontend:** ~80 LOC. Template-picker inline summary (Step 3) + engine-aware cheatsheet link in the Step-4 glossary entry. Cheatsheet doc itself is markdown.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.
- **Content:** 6 templates × ~50 lines each = ~300 lines of Jinja + 6 README.md files + 2 cheatsheet docs (~400 lines each) = ~1,400 lines of content. The Jinja templates need an end-to-end smoke test (each one renders against the demo cluster with the default search space and produces non-empty results); reuse the integration test harness from `infra_adapter_elastic`.

## Why not implemented inline today

Three reasons:

1. **Content-heavy, opinionated.** Picking the "right" six templates and writing accurate per-engine cheatsheets is a domain-expertise call worth a spec round, not a single-LOC change. The wrong templates ship dead weight; the wrong cheatsheet entries get cited as canonical and propagate misunderstanding.
2. **Cross-version validation.** Each template needs to be exercised against both ES 8.11+ and OpenSearch 2.x to confirm the syntax works on both engines (or to explicitly document where they diverge). That's integration-test work, not a doc PR.
3. **Best landed after `chore_create_study_wizard_polish`.** The glossary deep-links to the cheatsheet, and the auto-fill defaults heuristic improves materially when there's a real library of templates to tune against. Sequence: wizard polish → this library → builder UI.

## Relationship to other work

- **Pairs with** `chore_create_study_wizard_polish`. The wizard's `search_space` glossary entry links into the cheatsheet doc this idea produces.
- **Pairs with** `feat_create_study_search_space_builder`. More templates = more variety in `declared_params` shapes = a stronger test surface for the builder's per-type rendering.
- **Pairs with** `feat_agent_propose_search_space`. A richer template library gives the agent's `propose_search_space` tool more substrate to ground its recommendations against.
- **Independent of** `feat_study_clone_from_previous` — cloning works on whatever templates exist.
