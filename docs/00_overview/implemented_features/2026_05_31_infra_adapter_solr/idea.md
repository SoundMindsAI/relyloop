# Apache Solr adapter — MVP2 scope (bundled with UBI)

**Date:** 2026-05-27 · **Last refreshed:** 2026-05-30 (UBI-shipped reframe)
**Status:** Idea — sole remaining P1 anchor for MVP2 / v0.2 "Three-Engine + Real Signals" after [`feat_ubi_judgments`](../../../implemented_features/2026_05_29_feat_ubi_judgments/) shipped solo (PR #317, 2026-05-29). Landing Solr extends the just-shipped UBI path to a third engine with zero UBI code changes.
**Priority:** P1 — the "engine-neutral" claim is rhetorical until a third engine ships. With UBI already live on ES + OpenSearch, Solr is the single feature that flips four of RelyLoop's six differentiators from "two engines" to "all three OSS engines + hybrid UBI+LLM."
**Origin:** Positioning reframe on 2026-05-27 (see [`docs/07_research/comparison.md`](../../../../07_research/comparison.md) for the moat analysis). Apache Solr is the third and final supported engine, completing the OSS-engine sweep (ES + OpenSearch + Solr). Originally scoped as a co-released bundle with `feat_ubi_judgments`; that pairing dissolved when UBI shipped standalone on 2026-05-29 — this feature is now strictly the adapter, not the bundle.
**Depends on:** MVP1 shipped (`ElasticAdapter`, `SearchAdapter` Protocol, study lifecycle, judgment lists, PR worker) plus the already-shipped [`feat_ubi_judgments`](../../../implemented_features/2026_05_29_feat_ubi_judgments/) (`UbiReader`, `ubi_readiness` classifier, `POST /api/v1/judgments/generate-from-ubi`, hybrid UBI+LLM converter). Solr's `solr.UBIComponent` writes the same `ubi_queries` + `ubi_events` schema, so the live `UbiReader` works against a Solr cluster from day one — no new UBI work in this feature.

## Problem

After MVP1.5, RelyLoop runs against Elasticsearch and OpenSearch — but the "engine-neutral" positioning is aspirational until a third engine ships. Apache Solr is the right third engine because:

1. **It completes the OSS-engine sweep.** Elasticsearch, OpenSearch, and Apache Solr are the three engines OSC + Sease + Querqy + the Haystack community treat as the canonical OSS search stack. Supporting all three makes the "works wherever you are" pitch verifiable rather than rhetorical.
2. **UBI on Solr is first-party.** Solr ships `<searchComponent class="solr.UBIComponent">` in core ([Solr reference guide](https://solr.apache.org/guide/solr/latest/query-guide/learning-to-rank.html); [UBI tools index](https://www.ubisearch.dev/tools/)) using the same schema as the OpenSearch UBI plugin. The live `UbiReader` shipped in `feat_ubi_judgments` (2026-05-29) works against Solr unmodified — no Solr-specific UBI code is in scope here.
3. **Quepid + Chorus user base is Solr-native.** OSC's primary reference stack is Solr-based. Operators who already run Quepid for manual relevance evaluation are the natural adopters for RelyLoop's Bayesian-loop upgrade on the same engine they already manage.
4. **LTR is stable.** Solr 10 (March 2026) ships `modules/ltr` with `LinearModel`, `MultipleAdditiveTreesModel` (XGBoost-compatible), and `NeuralNetworkModel`. Stable since Solr 6. The de facto OSS LTR baseline outside ES native LTR ([Sease: Solr 10 LTR overview](https://sease.io/2026/03/apache-solr-10-what-is-new-for-vector-search-and-ltr.html)).


## Proposed capabilities

### `SolrAdapter` implementation

- **Location:** new module `backend/app/adapters/solr.py` implementing the `SearchAdapter` Protocol from [`backend/app/adapters/protocol.py`](../../../../../backend/app/adapters/protocol.py).
- **Engine support:** Solr 9.x (current widely-deployed) + Solr 10.x (released 2026-03). SolrCloud and standalone modes both supported. Solr 8.x and earlier explicitly out of scope.
- **`search_batch`:** parallel `/select` requests with a connection pool. Solr has no `_msearch` equivalent; the JSON Request API allows multi-query but is awkward and undertested across versions. Connection pool sized via the same inline `httpx.AsyncClient` pattern the ElasticAdapter uses today (`timeout=Timeout(10.0, connect=2.0)`, see [`backend/app/adapters/elastic.py:124`](../../../../../backend/app/adapters/elastic.py#L124)); a settings-level pool tunable can be introduced if Solr's per-query parallelism warrants it (open at spec time — there is no `HTTPX_POOL_LIMITS` setting today, verified 2026-05-30; [`mvp2-overview.md` Story A3](../../../../01_architecture/mvp2-overview.md) currently mis-states this setting as "existing" — flag for an arch-doc patch alongside `/spec-gen`).
- **`render`:** produces a Solr request parameter dict (later URL-encoded). Supports `edismax` (primary), `dismax`, and `lucene` parsers. **Template-path convention (locked):** Solr templates live at `samples/templates/solr/`, mirroring the locked ES/OpenSearch path. Decision rationale: the repo's only existing template is at [`samples/templates/product_search.j2`](../../../../../samples/templates/product_search.j2); the repo-root `templates/` directory is empty (`.keep` only); the sibling [`chore_template_library_expansion`](../chore_template_library_expansion/idea.md) explicitly extends `samples/templates/`; and [`mvp2-overview.md` Workstream C1](../../../../01_architecture/mvp2-overview.md) pins `samples/templates/` as canonical. Both adapters use the same root so a future per-engine reorganization can move them together. **Arch-doc drift to flag (out of scope of this feature):** [`mvp2-overview.md` Story A2](../../../../01_architecture/mvp2-overview.md) and the Story A3 row both reference `templates/solr/`, contradicting the same doc's own §C1; `/spec-gen` for this feature should land a one-line patch to that doc as part of its Verification Ledger.
- **`get_schema`:** uses Solr's Schema API (`/schema/fields`, `/schema/dynamicfields`, `/schema/fieldtypes`). Result shape matches `Schema` type unchanged.
- **`list_targets`:** uses CoresAdmin API (`/admin/cores?action=STATUS`) for standalone; CollectionsAdmin (`/admin/collections?action=LIST`) for SolrCloud. Selects automatically based on a startup capability probe.
- **`explain`:** uses `debugQuery=true&debug=results` and parses `debug.explain` from the response.
- **Authentication:** `auth_kind` extended to include `solr_basic` (HTTP Basic) and `solr_apikey` (Solr 9+ JWT through the security.json `JWTAuthPlugin`). PKI auth is internal-only and not exposed. Source-of-truth files to extend: backend `SUPPORTED_AUTH_KINDS` at [`backend/app/adapters/elastic.py:70`](../../../../../backend/app/adapters/elastic.py#L70) + the `auth_kind` CHECK at [`backend/app/db/models/cluster.py:42`](../../../../../backend/app/db/models/cluster.py#L42); frontend `AUTH_KIND_VALUES` at [`ui/src/lib/enums.ts:44`](../../../../../ui/src/lib/enums.ts#L44) (per CLAUDE.md "Enumerated Value Contract Discipline" — every frontend option must be grounded in a backend Literal with a `// Values must match` comment).
- **Capability probe at adapter construction:** detects Solr version, SolrCloud-vs-standalone, presence of `solr.UBIComponent`, presence of `ltr` module, and writes the result to the `clusters.engine_config` JSONB. Used by the search-space validator to reject studies that reference parameters the cluster can't honor.

### Cross-engine parameter map (additions)

The unified parameter vocabulary defined in [`docs/01_architecture/adapters.md` §"Cross-engine parameter naming"](../../../../01_architecture/adapters.md) gets a third column. The `field_boosts` / `phrase_field_boosts` / `tie_breaker` / `min_should_match` / `slop` / `boost_fn` / `rerank_model` parameters already had Solr `edismax` mappings documented in the original spec — they become real implementation, not architectural reference.

Solr-specific notes:

- **`mm` syntax is richer than ES `minimum_should_match`.** Solr's `mm` accepts arithmetic expressions (`2<-25% 9<-3`); the adapter accepts unified `int | float | str` and validates against the Solr syntax server-side.
- **Boosts in Solr are additive (`bf`) by default; multiplicative via `boost`.** ES `function_score` defaults to multiplicative. The unified `boost_fn` parameter carries an explicit `combine: "add" | "multiply"` field; the Solr adapter renders into `bf` or `boost` respectively.
- **LTR rescoring is `{!ltr model=... reRankDocs=...}` injected as `rq=`**, not the ES `rescore.learning_to_rank` shape. The adapter handles both at the unified `rerank_model` parameter.
- **No Solr-side "pipeline stage toggle" concept.** The unified vocabulary covers query-time parameters (boosts, minimum-should-match, rescore, LTR), not pipeline-stage toggles.

### LTR rescoring

- **In scope for MVP2:** apply a pre-existing `MultipleAdditiveTreesModel` (XGBoost-compatible) loaded via Solr's `/schema/model-store` as a rescore stage in a study trial. Training the model is out of scope (LTR training lands in v2 Path A as a cross-engine capability).
- The unified `rerank_model: {id, top_k}` parameter renders to Solr `rq={!ltr model=${id} reRankDocs=${top_k}}`.

### UBI on Solr

- **Layers on top of the already-shipped [`feat_ubi_judgments`](../../../implemented_features/2026_05_29_feat_ubi_judgments/) with zero changes to UBI code.** The `UbiReader` reads `ubi_queries` + `ubi_events` collections via `SearchAdapter.search_batch` — works against any adapter that implements the Protocol. The `solr.UBIComponent` writes the same schema as the OpenSearch UBI plugin. The moment this adapter lands, every live UBI path (`POST /api/v1/judgments/generate-from-ubi`, `generate_judgments_from_ubi` agent tool, hybrid UBI+LLM converter) extends to Solr.
- Operator-facing docs gain a section on enabling `<searchComponent class="solr.UBIComponent">` in `solrconfig.xml` and routing search requests through it (analogous to the OpenSearch UBI plugin enablement runbook). The seed-data side already has [`samples/ubi_index_mappings.json`](../../../../../samples/ubi_index_mappings.json) — the canonical UBI index mapping shipped with `feat_demo_ubi_study_comparison` (PR #320) — which the Solr integration tests can reuse for collection bootstrap.

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

## Why this still belongs in MVP2 (after UBI shipped solo)

The original "bundle UBI + Solr" framing dissolved when `feat_ubi_judgments` shipped standalone on 2026-05-29 (PR #317). The MVP2 home for this feature is now grounded in three different reasons:

1. **It's the only feature that flips the "engine-neutral" claim from two engines to three.** UBI shipped on ES + OpenSearch already; until Solr lands, RelyLoop is a two-engine tool with a third-engine pitch in the docs. Solr is the single change that makes the engine-sweep verifiable rather than rhetorical.
2. **Solr's `solr.UBIComponent` is first-party — so this feature is genuinely additive on UBI.** Zero `UbiReader` code touches; zero schema migrations for UBI; the reader and the hybrid converter extend to Solr automatically the moment `SolrAdapter` returns Protocol-conformant results. The MVP2 "Three-Engine + Real Signals" theme requires Solr to complete; UBI alone is half the headline.
3. **MVP3 is reserved for observability.** Langfuse + SigNoz + audit-log immutability + lineage is a foundational reliability layer that benefits every adapter and every judgment source. Landing the engine sweep first means MVP3 instruments three engines × two judgment sources in one pass, rather than retrofitting observability per engine.

**Technical compatibility:** no schema or Protocol changes are required to host this on the current MVP2 baseline. The `SearchAdapter` Protocol shape is engine-agnostic by design; the `judgments.source` CHECK at [`backend/app/db/models/judgment.py:50`](../../../../../backend/app/db/models/judgment.py#L50) already accepts `'llm' | 'human' | 'click'`; the one Alembic migration extends `clusters.engine_type` + `clusters.auth_kind` CHECKs only.

**Release size estimate:** ~2–3 engineer-weeks (solo). Roughly ~1,200 LOC backend (adapter ~600 + templates ~150 + capability probe ~100 + auth/connection ~150 + tests ~200), ~100 LOC frontend, one Alembic migration, one new Compose service, one new operator runbook + one tutorial extension. The earlier "4–5 weeks combined" figure assumed UBI was still in flight; the UBI workstream is now sunk cost.

## Relationship to other work

- **Extends the already-shipped [`feat_ubi_judgments`](../../../implemented_features/2026_05_29_feat_ubi_judgments/) to a third engine with zero UBI code changes.** Solr's `solr.UBIComponent` writes the same UBI schema; the live `UbiReader` and hybrid UBI+LLM converter work on Solr the moment `SolrAdapter` is Protocol-conformant.
- **Extends the live UBI on-ramp nudge ([`ui/src/components/clusters/ubi-onramp-nudge.tsx`](../../../../../ui/src/components/clusters/ubi-onramp-nudge.tsx)) to a third engine.** The engine-aware "enable real user signals" nudge that shipped with `feat_ubi_judgments` Capability B (which absorbed the former `feat_ubi_onramp` 2026-05-29) currently covers `elasticsearch | opensearch` (the engine_type CHECK at [`backend/app/db/models/cluster.py:34`](../../../../../backend/app/db/models/cluster.py#L34) and the frontend allowlist at [`ui/src/lib/enums.ts:40`](../../../../../ui/src/lib/enums.ts#L40)); the nudge spans all three engines once both the backend CHECK and the frontend `ENGINE_TYPE_VALUES` are extended here.
- **Pairs with [`chore_template_library_expansion`](../chore_template_library_expansion/idea.md)** (Workstream C in [`mvp2-overview.md`](../../../../01_architecture/mvp2-overview.md)) — that idea ships the curated multi-engine template library (including Solr templates) and the per-engine tunable-params cheatsheets. The template-path convention is locked to `samples/templates/<engine>/` (decision §"`render`" above) — both ideas use the same root.
- **Pairs with [`feat_demo_ubi_study_comparison`](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/)** (Phase 1 shipped 2026-05-30, PR #320) for the seed-data scaffold — Solr integration tests can reuse the canonical `samples/ubi_index_mappings.json` that feature established as the cross-language source of truth.
- **Multi-Git provider abstraction (GitLab, Bitbucket) is in the backlog** — it serves a smaller adopter axis than the engine sweep + observability path. GitHub remains the only Git provider through GA v1.
- **Unlocks the verifiable "engine-neutral" claim** in [`docs/07_research/comparison.md`](../../../../07_research/comparison.md) and the umbrella spec §1. The claim is rhetorical at MVP1; it becomes factual at MVP2 once this ships.
- **MVP3 "Observable" follows** — Langfuse + SigNoz + audit-log immutability + lineage layers on top of all three engines and both judgment sources in one go.

## Open questions for /spec-gen

1. **httpx pool tunable.** Introduce a settings-level pool limit (`HTTPX_POOL_LIMITS` or similar) as part of this work, or rely on the inline `AsyncClient` defaults the ElasticAdapter uses today? **Recommended default:** rely on the inline defaults for this feature; introduce `HTTPX_POOL_LIMITS` only if integration tests show contention under the planned per-trial parallelism. Either way, `mvp2-overview.md` Story A3 needs a one-line patch (it currently mis-states this setting as "existing").
2. **LTR test fixture** (also tracked in [`mvp2-overview.md` §10](../../../../01_architecture/mvp2-overview.md), open question 1) — load a real `MultipleAdditiveTreesModel` into Compose Solr for the E2E, or assert the `rq={!ltr …}` render shape only? **Recommended default:** render-shape-only for the E2E (cheap, deterministic, no model artifact in the repo); add one DB-backed integration test that exercises a model upload + rescore round-trip against a checked-in fixture if `/spec-gen` finds the render assertion insufficient.

**Locked since the original idea was written (no longer open):**

- ~~**Template-path convention.**~~ — **Locked at `samples/templates/<engine>/`** (decision §"`render`" above). Matches the sibling [`chore_template_library_expansion`](../chore_template_library_expansion/idea.md) and [`mvp2-overview.md` §C1](../../../../01_architecture/mvp2-overview.md). `mvp2-overview.md` Story A2 + Story A3 row both have a stale `templates/solr/` reference that contradicts §C1 — `/spec-gen` should land that one-line arch-doc patch in its Verification Ledger.
