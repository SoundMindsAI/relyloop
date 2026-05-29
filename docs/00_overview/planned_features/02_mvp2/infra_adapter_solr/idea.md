# Apache Solr adapter — MVP2 scope (bundled with UBI)

**Date:** 2026-05-27
**Status:** Idea — anchor feature for MVP2 / v0.2 "Three-Engine + Real Signals" (bundled with [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md))
**Priority:** P1 — MVP2 is named for the bundle of this adapter + UBI judgments; together they ship four of RelyLoop's six differentiators (all three OSS engines + hybrid UBI+LLM)
**Origin:** Positioning reframe on 2026-05-27 (see [`chore_drop_fusion_scope/idea.md`](../../../implemented_features/2026_05_28_chore_drop_fusion_scope/idea.md) for the paired Fusion-drop rationale — shipped 2026-05-28 — and [`docs/07_research/comparison.md`](../../../../07_research/comparison.md) for the moat analysis). Replaces the previously-planned Lucidworks Fusion adapter as the next engine target.
**Depends on:** MVP1 shipped (`ElasticAdapter`, `SearchAdapter` Protocol, study lifecycle, judgment lists, PR worker). Co-released with [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md): Solr's `solr.UBIComponent` writes the same `ubi_queries` + `ubi_events` schema, so the MVP2 `UbiReader` works unchanged against a Solr cluster from day one.

## Problem

After MVP1.5, RelyLoop runs against Elasticsearch and OpenSearch — but the "engine-neutral" positioning is aspirational until a third engine ships. Apache Solr is the right third engine because:

1. **It completes the OSS-engine sweep.** Elasticsearch, OpenSearch, and Apache Solr are the three engines OSC + Sease + Querqy + the Haystack community treat as the canonical OSS search stack. Supporting all three makes the "works wherever you are" pitch verifiable rather than rhetorical.
2. **UBI on Solr is first-party.** Solr ships `<searchComponent class="solr.UBIComponent">` in core ([Solr reference guide](https://solr.apache.org/guide/solr/latest/query-guide/learning-to-rank.html); [UBI tools index](https://www.ubisearch.dev/tools/)) using the same schema as the OpenSearch UBI plugin. MVP1.5's `UbiReader` works unmodified — no Solr-specific UBI code.
3. **Quepid + Chorus user base is Solr-native.** OSC's primary reference stack is Solr-based. Operators who already run Quepid for manual relevance evaluation are the natural adopters for RelyLoop's Bayesian-loop upgrade on the same engine they already manage.
4. **LTR is stable.** Solr 10 (March 2026) ships `modules/ltr` with `LinearModel`, `MultipleAdditiveTreesModel` (XGBoost-compatible), and `NeuralNetworkModel`. Stable since Solr 6. The de facto OSS LTR baseline outside ES native LTR ([Sease: Solr 10 LTR overview](https://sease.io/2026/03/apache-solr-10-what-is-new-for-vector-search-and-ltr.html)).

The Lucidworks Fusion adapter that previously occupied this slot is dropped — see [`chore_drop_fusion_scope`](../../../implemented_features/2026_05_28_chore_drop_fusion_scope/idea.md) for the rationale (vendor entanglement, narrower audience overlap with the Quepid/Chorus community, materially higher build cost).

## Proposed capabilities

### `SolrAdapter` implementation

- **Location:** new module `backend/app/adapters/solr.py` implementing the `SearchAdapter` Protocol from [`backend/app/adapters/protocol.py`](../../../../../backend/app/adapters/protocol.py).
- **Engine support:** Solr 9.x (current widely-deployed) + Solr 10.x (released 2026-03). SolrCloud and standalone modes both supported. Solr 8.x and earlier explicitly out of scope.
- **`search_batch`:** parallel `/select` requests with a connection pool. Solr has no `_msearch` equivalent; the JSON Request API allows multi-query but is awkward and undertested across versions. Connection pool sized via the same inline `httpx.AsyncClient` pattern the ElasticAdapter uses today (`timeout=Timeout(10.0, connect=2.0)`, see [`backend/app/adapters/elastic.py:120`](../../../../../backend/app/adapters/elastic.py#L120)); a settings-level pool tunable can be introduced if Solr's per-query parallelism warrants it (open at spec time — there is no `HTTPX_POOL_LIMITS` setting today, verified 2026-05-29).
- **`render`:** produces a Solr request parameter dict (later URL-encoded). Supports `edismax` (primary), `dismax`, and `lucene` parsers. Templates live under `templates/solr/` as Jinja templates that emit parameter maps. **Template-path convention is unresolved as of 2026-05-29:** the repo's only existing template is at [`samples/templates/product_search.j2`](../../../../../samples/templates/product_search.j2); the repo-root `templates/` directory exists but is empty (`.keep` only). The sibling [`chore_template_library_expansion`](../chore_template_library_expansion/idea.md) proposes expanding `samples/templates/`, not introducing `templates/<engine>/`. Pick one convention in `/spec-gen` and apply it uniformly to both adapters (open question listed below).
- **`get_schema`:** uses Solr's Schema API (`/schema/fields`, `/schema/dynamicfields`, `/schema/fieldtypes`). Result shape matches `Schema` type unchanged.
- **`list_targets`:** uses CoresAdmin API (`/admin/cores?action=STATUS`) for standalone; CollectionsAdmin (`/admin/collections?action=LIST`) for SolrCloud. Selects automatically based on a startup capability probe.
- **`explain`:** uses `debugQuery=true&debug=results` and parses `debug.explain` from the response.
- **Authentication:** `auth_kind` extended to include `solr_basic` (HTTP Basic) and `solr_apikey` (Solr 9+ JWT through the security.json `JWTAuthPlugin`). PKI auth is internal-only and not exposed.
- **Capability probe at adapter construction:** detects Solr version, SolrCloud-vs-standalone, presence of `solr.UBIComponent`, presence of `ltr` module, and writes the result to the `clusters.engine_config` JSONB. Used by the search-space validator to reject studies that reference parameters the cluster can't honor.

### Cross-engine parameter map (additions)

The unified parameter vocabulary defined in [`docs/01_architecture/adapters.md` §"Cross-engine parameter naming"](../../../../01_architecture/adapters.md) gets a third column. The `field_boosts` / `phrase_field_boosts` / `tie_breaker` / `min_should_match` / `slop` / `boost_fn` / `rerank_model` parameters already had Solr `edismax` mappings documented in the original spec — they become real implementation, not architectural reference.

Solr-specific notes:

- **`mm` syntax is richer than ES `minimum_should_match`.** Solr's `mm` accepts arithmetic expressions (`2<-25% 9<-3`); the adapter accepts unified `int | float | str` and validates against the Solr syntax server-side.
- **Boosts in Solr are additive (`bf`) by default; multiplicative via `boost`.** ES `function_score` defaults to multiplicative. The unified `boost_fn` parameter carries an explicit `combine: "add" | "multiply"` field; the Solr adapter renders into `bf` or `boost` respectively.
- **LTR rescoring is `{!ltr model=... reRankDocs=...}` injected as `rq=`**, not the ES `rescore.learning_to_rank` shape. The adapter handles both at the unified `rerank_model` parameter.
- **No Solr-side "pipeline stage toggle" concept.** The `stage_enabled` parameter (was Fusion-only) is removed from the unified vocabulary as part of the Fusion drop.

### LTR rescoring

- **In scope for MVP2:** apply a pre-existing `MultipleAdditiveTreesModel` (XGBoost-compatible) loaded via Solr's `/schema/model-store` as a rescore stage in a study trial. Training the model is out of scope (LTR training lands in v2 Path A as a cross-engine capability).
- The unified `rerank_model: {id, top_k}` parameter renders to Solr `rq={!ltr model=${id} reRankDocs=${top_k}}`.

### UBI on Solr

- **Bundled with [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) in the same MVP2 release.** The `UbiReader` reads `ubi_queries` + `ubi_events` collections via `SearchAdapter.search_batch` — works against any adapter that implements the Protocol. The `solr.UBIComponent` writes the same schema as the OpenSearch UBI plugin. Once both this adapter and `feat_ubi_judgments` ship in MVP2, every UBI path (`POST /api/v1/judgment-lists/generate-from-ubi`, `generate_judgments_from_ubi` agent tool, hybrid UBI+LLM converter) works on all three engines from day one.
- Operator-facing docs gain a section on enabling `<searchComponent class="solr.UBIComponent">` in `solrconfig.xml` and routing search requests through it (analogous to the OpenSearch UBI plugin enablement runbook).

### Compose service + tests

- New Compose service `solr` (Apache 2.0 image, `solr:10`) bound to `127.0.0.1:8983`. Mirrors the existing `elasticsearch` and `opensearch` service shape.
- Sample collection `products` seeded from `samples/products.json` (the same dataset MVP1 uses for ES).
- Adapter unit tests under `backend/tests/unit/adapters/test_solr.py` (mocked HTTP; fast).
- Adapter integration tests under `backend/tests/integration/adapters/test_solr_live.py` against the Compose Solr service.
- Contract tests extending the existing `SearchAdapter` conformance suite — every Protocol method that ES + OpenSearch pass, Solr must also pass.
- E2E test: `ui/tests/e2e/solr-study-end-to-end.spec.ts` runs the full Karpathy loop (register Solr cluster → create study → generate judgments → run trials → open PR) against the live Compose Solr.

### Operator-facing documentation

- **New runbook:** `docs/03_runbooks/solr-cluster-registration.md` — how to register a Solr cluster, configure `edismax` defaults, enable `solr.UBIComponent`, upload an LTR model.
- **Tutorial extension:** `docs/08_guides/tutorial-first-study.md` gains a Step 0 Path C — "Run the tutorial against Solr instead of Elasticsearch." Demonstrates the same study, same loop, same PR — different engine.

## Scope signals

- **Backend:** ~1,200 LOC total. Adapter ~600 LOC; templates ~150 LOC; capability probe ~100 LOC; auth + connection handling ~150 LOC; ~200 LOC tests (unit + integration + contract). Roughly 40–50% conceptually shared with ES adapter (orchestration shell, validator hooks, error mapping); the rest is Solr-specific (parameter rendering, LTR injection, `mm` syntax handling, JSON Request API quirks).
- **Frontend:** ~100 LOC. New `engine_type` option in the cluster-registration form; engine-specific help text for Solr auth flows; engine badge on cluster cards / study headers (small Solr SVG).
- **Migration:** **one migration**. Extends the `clusters.auth_kind` CHECK constraint to accept `solr_basic` and `solr_apikey`; extends `engine_type` CHECK to accept `solr`. No new tables.
- **Config:** new optional env vars `SOLR_HOST` / `SOLR_PORT` / `SOLR_ADMIN_USERNAME_FILE` / `SOLR_ADMIN_PASSWORD_FILE` for the Compose Solr service. Mirrors the ES + OpenSearch settings pattern.
- **Audit events:** N/A at the engine-adapter layer. `audit_log` activates at MVP3 (Observable) and uses event names independent of engine; multi-tenancy is in the backlog.
- **Tests:**
  - Unit: parameter rendering for each `edismax` parameter, LTR rescore injection, `mm` arithmetic syntax, capability probe parsing, error mapping for 4xx/5xx
  - Integration: end-to-end search against Compose Solr; LTR model upload + rescore round-trip; UBI reader against seeded `ubi_queries`/`ubi_events`
  - Contract: `SearchAdapter` Protocol conformance — every method that ES + OpenSearch implement, Solr must implement with the same signature and error envelope
  - E2E: full Karpathy loop against the live Compose Solr (Step 0 Path C of the tutorial, automated)

## Why bundled with UBI into MVP2 (not split into two releases)

1. **Together they ship the engine-neutral story.** UBI alone catches up with OpenSearch SRW (which already has UBI-via-COEC GA). The Solr adapter alone is a third engine without a Real Signals story. Bundled, they ship "RelyLoop runs on all three OSS engines with UBI on every one of them" as a single coherent headline.
2. **Solr's `solr.UBIComponent` is first-party.** The `UbiReader` works against Solr unchanged the moment the adapter lands. Splitting them into two releases means one of the two would ship a half-finished UBI story (UBI without Solr support, or Solr without same-release UBI parity).
3. **MVP3 is reserved for observability.** Langfuse + SigNoz + audit-log immutability is a foundational reliability layer that benefits every adapter and every judgment source. Landing it after the engine sweep means MVP3 instruments three engines × two judgment sources in one release of work, rather than retrofitting observability per engine.
4. **No schema or Protocol changes are required.** The `SearchAdapter` Protocol shape is engine-agnostic by design; the `judgments.source` CHECK already accepts `click`. Both capabilities are additive — bundling them is a release-cadence decision, not a technical compromise.

**Release size estimate:** ~4–5 engineer-weeks combined (Solr adapter ~2–3, UBI ~2, ~1 week of co-integration testing + the engine-neutral tutorial extensions). Solo-engineer; ~3–4 weeks with two engineers working in parallel on the Solr and UBI tracks.

## Relationship to other work

- **Replaces the previously-planned Lucidworks Fusion adapter** as the next engine target. See [`chore_drop_fusion_scope`](../../../implemented_features/2026_05_28_chore_drop_fusion_scope/idea.md) (shipped 2026-05-28) for why Fusion was dropped.
- **Bundled with [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md)** in MVP2 — Solr's `solr.UBIComponent` writes the same UBI schema; the UBI reader and hybrid UBI+LLM converter work on Solr unchanged from day one.
- **Required by the UBI on-ramp** (the engine-aware nudge in [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) Capability B, which absorbed the former `feat_ubi_onramp` 2026-05-29) — the "enable real user signals" nudge spans all three engines only after the `engine_type` CHECK constraint extension here lands. Until then it covers `elasticsearch | opensearch` (current values at [`cluster.py:30`](../../../../../backend/app/db/models/cluster.py#L30)).
- **Pairs with [`chore_template_library_expansion`](../chore_template_library_expansion/idea.md)** (Workstream C in [`mvp2-overview.md`](../../../../01_architecture/mvp2-overview.md)) — that idea ships the curated multi-engine template library (including Solr templates) and the per-engine tunable-params cheatsheets. Coordinate the template-path convention with it (see open questions).
- **Multi-Git provider abstraction (GitLab, Bitbucket) is in the backlog** — was previously bundled with the Fusion-era MVP3; reframed as backlog because it serves a smaller adopter axis than the engine sweep + observability path. GitHub remains the only Git provider through GA v1.
- **Unlocks the verifiable "engine-neutral" claim** in [`docs/07_research/comparison.md`](../../../../07_research/comparison.md) and the umbrella spec §1. The claim is rhetorical at MVP1; it becomes factual at MVP2.
- **MVP3 "Observable" follows** — Langfuse + SigNoz + audit-log immutability + lineage layers on top of all three engines and both judgment sources in one go.

## Open questions for /spec-gen

1. **Template-path convention.** Adopt `templates/<engine>/` (this idea's current text) or extend `samples/templates/` (the convention `chore_template_library_expansion` proposes)? Whichever wins must apply uniformly — splitting "Solr at one path, ES/OS at another" is the worst outcome. Recommended: `samples/templates/<engine>/` (extends today's location without introducing a second top-level templates dir, and matches the sibling chore's path baseline).
2. **httpx pool tunable.** Introduce a settings-level pool limit (`HTTPX_POOL_LIMITS` or similar) as part of this work, or rely on the inline `AsyncClient` defaults the ElasticAdapter uses today? The latter ships sooner; the former is the right shape if Solr's parallel `/select` warrants per-engine tuning.
3. **LTR test fixture** (also tracked in [`mvp2-overview.md` §10](../../../../01_architecture/mvp2-overview.md)) — load a real `MultipleAdditiveTreesModel` into Compose Solr for the E2E, or assert the `rq={!ltr …}` render shape only?
