# Feature Specification — feat_demo_ubi_study_comparison

**Date:** 2026-05-29
**Status:** Draft
**Owners:** RelyLoop maintainers (engineering + product)
**Depends on:** [`feat_ubi_judgments`](../../implemented_features/2026_05_29_feat_ubi_judgments/) (shipped, PR #317, 2026-05-29)
**Related docs:**
- [`idea.md`](./idea.md) (this folder; preflight-audited 2026-05-29)
- [`feat_ubi_judgments/feature_spec.md`](../../implemented_features/2026_05_29_feat_ubi_judgments/feature_spec.md) — the UBI engine this feature exercises
- [`docs/03_runbooks/ubi-judgment-generation.md`](../../../03_runbooks/ubi-judgment-generation.md) — runbook this feature updates with the synthetic-data section
- [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) Step 11 — tutorial UBI section this feature feeds

---

## 1) Purpose

- **Problem:** The home-page "force refresh demo data" reseed
  ([`backend/app/services/demo_seeding.py:1065`](../../../../backend/app/services/demo_seeding.py#L1065) →
  `reseed_demo_state`) seeds product docs + clusters + query sets + LLM
  judgment lists + studies across five scenarios, but writes **zero** UBI
  data. The product's runtime posture is read-only on UBI (Absolute Rule
  #4 — adapter Protocol is the only engine surface at runtime), so
  nothing in the product writes `ubi_queries`/`ubi_events` at runtime;
  those are operator-application-emitted at real sites. As a result a
  demo operator opening the generate-judgments dialog sees the rung_0
  on-ramp nudge on every cluster and can only exercise the LLM path —
  the just-shipped UBI feature is invisible in the demo.
- **Outcome:** After this feature, the home-button reseed (and the
  CLI's `make seed-demo`) populate **synthetic UBI clickstream**
  directly into the demo Elasticsearch container via the existing
  `engine_client: httpx.AsyncClient` pattern (the same precedent
  [`run_demo_reseed_cleanup`](../../../../backend/app/services/demo_seeding.py#L459)
  uses for index deletes — seed-side install code, NOT a runtime
  adapter call). Three of the five scenarios land at deliberately
  different UBI readiness rungs (rung_1 / rung_2 / rung_3) so every
  rung-conditional UX surface — the on-ramp nudge, the rung badge, the
  method-picker defaults, the sparse-data card, the hybrid LLM-fill
  path — is browser-visible in the demo. Each UBI-enabled scenario gets
  **two** judgment lists on the same query set (one LLM, one UBI) and
  **two** studies (same template, same Optuna config, same seed=42),
  so the existing per-judgment-list value-delta card lights up for free
  and the operator can manually open both study detail pages to
  compare digests / best configs / metric deltas.
- **Non-goal:** A dedicated side-by-side UBI-vs-LLM **study** comparison
  view (digest diff, best-config diff, convergence overlay) is deferred
  to Phase 2 — Phase 1 ships everything needed to do the comparison
  manually across two browser tabs.

## 2) Current state audit

### Existing implementations

| File / component | What it does | Notes |
|---|---|---|
| [`backend/app/services/demo_seeding.py:1065`](../../../../backend/app/services/demo_seeding.py#L1065) → `reseed_demo_state` | Orchestrates the wipe + reseed of the 4 small scenarios + the rich ESCI scenario | The natural seam for synthetic UBI is per-scenario, after the engine docs are indexed but before the API cluster registration |
| [`backend/app/services/demo_seeding.py:459`](../../../../backend/app/services/demo_seeding.py#L459) → `run_demo_reseed_cleanup` | DELETEs the demo ES + OS indices via the same `engine_client` | Precedent for seed-side engine writes; `ubi_queries` + `ubi_events` will be added to the cleanup list |
| [`backend/workers/demo_reseed.py:59`](../../../../backend/workers/demo_reseed.py#L59) → `run_demo_reseed` | Arq worker that constructs both `httpx.AsyncClient`s and invokes `reseed_demo_state` | No change required — feature is contained inside `reseed_demo_state` |
| [`scripts/seed_meaningful_demos.py:143`](../../../../scripts/seed_meaningful_demos.py#L143) `SCENARIOS` | Canonical scenario catalog (4 small) — imported by `demo_seeding.py:60` | Source of truth; per-scenario UBI configuration is added here, NOT in the orchestrator |
| [`scripts/seed_meaningful_demos.py:851`](../../../../scripts/seed_meaningful_demos.py#L851) `seed_scenario` | CLI's per-scenario flow used by `make seed-demo` | Per the home-button-vs-CLI parity policy (`bug_demo_reseed_fake_metric_regression`), the CLI must emit byte-equivalent demo state — both code paths share the synthetic-UBI generator (D-5 below) |
| [`backend/app/domain/ubi/converter.py:202`](../../../../backend/app/domain/ubi/converter.py#L202) `CtrThresholdConverter` | Wang-Bendersky position-bias-corrected CTR converter | Position bias in the synthetic generator is what makes this converter's correction demonstrable vs raw CTR (the idea cited line 203 — actual line is 202; cosmetic drift, no contract change) |
| [`backend/app/services/ubi_readiness.py:101`](../../../../backend/app/services/ubi_readiness.py#L101) `classify_rung` | Probes UBI indices + counts events; rung_0..rung_3 thresholds at `min_impressions_threshold` (default 100) and `5 × min_impressions_threshold` (500) | 60s Redis cache; key `ubi-readiness:{cluster_id}:{query_set_id}:{target}`. Cache naturally invalidates because reseed creates new cluster IDs every cycle |
| [`backend/app/api/v1/judgments.py:233`](../../../../backend/app/api/v1/judgments.py#L233) `POST /api/v1/judgments/generate-from-ubi` | Dispatches `start_ubi_judgment_generation` | The reseed calls this via `api_client` exactly once per UBI-enabled scenario; the Arq worker writes the second judgment list asynchronously |
| [`ui/tests/e2e/helpers/seed_ubi.ts`](../../../../ui/tests/e2e/helpers/seed_ubi.ts) | E2E helper that writes `ubi_queries` + `ubi_events` to the engine for Playwright specs | Today defines mapping shapes inline (lines 26–51); D-1 below extracts these into `samples/ubi_index_mappings.json` so the Python generator and TS helper share one source of truth. **Posture difference**: this helper does delete-then-recreate per spec (single tenant per index per test); the reseed needs additive multi-scenario writes (D-6) |
| [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts) `isDemoClusterName` | Recognizes the 4 demo cluster slugs (`acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`) | Existing demo-aware gate; this feature's synthetic-data disclaimer reuses it — no new per-cluster flag needed |
| [`ui/src/components/clusters/ubi-onramp-nudge.tsx`](../../../../ui/src/components/clusters/ubi-onramp-nudge.tsx) | Engine-neutral on-ramp nudge shown at rung_0 | Will render on `news-search-staging` (OS scenario stays rung_0 per D-2) — proves the engine-neutral copy works on OpenSearch |
| [`ui/src/components/clusters/ubi-rung-badge.tsx`](../../../../ui/src/components/clusters/ubi-rung-badge.tsx) | Per-cluster rung_0..rung_3 badge | Will render visually distinct on the three UBI-enabled clusters |
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | The method-picker dialog with `defaultMethodForRung` | Will offer `ctr_threshold` / `dwell_time` / `hybrid_ubi_llm` options as defaults that change with rung — visible on the three UBI clusters |
| [`ui/src/components/query-sets/ubi-sparse-data-card.tsx`](../../../../ui/src/components/query-sets/ubi-sparse-data-card.tsx) | Recovery card for the rung_1 (sparse) path | Renders on `corp-docs-search` |
| [`ui/src/components/judgments/value-delta-card.tsx`](../../../../ui/src/components/judgments/value-delta-card.tsx) | Shows per-(query, doc) rating deltas vs a prior list on the same query set | Lights up automatically when the UBI judgment list is opened, comparing against the LLM list on the same query set |
| [`ui/src/components/judgments/ambiguous-skip-recovery-card.tsx`](../../../../ui/src/components/judgments/ambiguous-skip-recovery-card.tsx) | Recovery card for UBI lists with ambiguous skips | Renders when the synthetic generator produces ambiguous skips (rare but possible) |

### Navigation and link impact

None — Phase 1 adds no new routes, no link targets, no menu items. The existing URLs `/clusters/{id}`, `/query-sets/{id}`, `/judgments/{id}`, `/studies/{id}` all become more interesting because they have UBI data on three of the demo clusters.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/services/test_demo_seeding_orchestrator.py` (if present — verify in plan) | `reseed_demo_state` invocation + assertions on scenarios_completed | TBD (~3-5) | Extend with assertions that the 3 UBI-enabled scenarios produced 2 judgment lists + 2 studies each; the OS + rich scenarios produced 1 each |
| `backend/tests/integration/scripts/test_seed_meaningful_demos.py` (if present — verify in plan) | CLI parity tests | TBD | Same dual-list + dual-study assertions for the CLI path |
| `ui/tests/e2e/dashboard.spec.ts` and `studies-data-table.spec.ts` | Counts of clusters / studies on the dashboard | Existing snapshots | Update study-count assertions (3 scenarios now ship 2 studies → +3 studies on the dashboard); rung-badge assertions added on the 3 UBI scenarios |
| `ui/tests/e2e/ubi-onramp-nudge*.spec.ts` (if present) | rung_0 nudge visibility | Existing | Pin the rung_0 assertion to `news-search-staging` (the only remaining rung_0 demo cluster) |

The plan-gen pass will glob `backend/tests/integration/` and `ui/tests/e2e/` for actual references and produce a concrete update list.

### Existing behaviors affected by scope change

- **Demo cluster rung state**: Current: every demo cluster reports rung_0. New: 3 demo ES clusters report rung_1 / rung_2 / rung_3 respectively; OS demo cluster reports rung_0; rich acme cluster reports rung_0 (LLM-only baseline preserved). **Decision needed:** no — locked in D-2.
- **Demo dataset judgment-list count**: Current: 1 LLM list per scenario (5 total). New: 1 LLM list per non-UBI scenario (2 lists: `news-search-staging` + `acme-products-rich-prod`) + 2 lists per UBI-enabled scenario (6 lists across the 3 ES scenarios) = **8 judgment lists total** (was 5). **Decision needed:** no — direct consequence of D-3.
- **Demo dataset study count**: Current: 5 studies (1 per scenario). New: **8 studies total** (1 each for `news-search-staging` + `acme-products-rich-prod` + 2 each for the 3 UBI-enabled ES scenarios). **Decision needed:** no — direct consequence of D-3.
- **`make seed-demo` parity**: Current: CLI and home-button produce byte-identical demo state per `bug_demo_reseed_fake_metric_regression`. New: same — both paths invoke the same synthetic-UBI generator (D-5 / D-7). **Decision needed:** no — locked in D-7.
- **Reseed wall-clock**: Current: ~10-15 min total (4 small + 1 rich at 5 min). New: +30-90s for the synthetic UBI generation + 30-60s × 3 for the second studies per UBI scenario. Estimated new wall-clock: ~13-19 min. The existing `DEMO_RESEED_JOB_TIMEOUT_S = 1200` (20-min) ceiling stays unchanged. **Decision needed:** no — fits inside the existing budget.
- **Synthetic-data disclosure**: Current: no demo disclaimers on UBI surfaces (no UBI in demo). New: five surfaces (GenerateJudgmentsDialog UBI options, JudgmentListHeader, Cluster detail page near UbiRungBadge, Study detail page header, DemoDataBanner) carry a "Synthetic demo data" badge gated by the **narrower** `isDemoSyntheticUbiClusterName(name)` helper (three-slug allowlist: `acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod`) — NOT by `isDemoClusterName(name)`. `news-search-staging` is a demo cluster but has no synthetic UBI; the chip must not appear there. **Decision needed:** no — locked in D-4 cycle-2 revision.

---

## 3) Scope

### In scope (Phase 1)

1. **Canonical UBI index-mapping file** at [`samples/ubi_index_mappings.json`](../../../../samples/) (D-1) consumed by both the Playwright helper [`ui/tests/e2e/helpers/seed_ubi.ts`](../../../../ui/tests/e2e/helpers/seed_ubi.ts) and the new Python synthetic generator.
2. **Pure-domain synthetic UBI generator** at `backend/app/domain/demo/synthetic_ubi.py` (D-5) — no I/O, no httpx, no settings. Takes a scenario configuration + a known relevance signal + a target rung and returns the lists of `ubi_queries` rows + `ubi_events` rows to be written. Unit-testable without fixtures.
3. **Engine-write helper** at `backend/app/services/demo_ubi_seed.py` (D-5) — `httpx.AsyncClient`-aware module that loads the canonical mapping, ensures the two indices exist (create-if-missing per D-6), and bulk-writes the synthetic rows additively per scenario (multiple `application=<target>` tagged into the same indices).
4. **Reseed orchestrator wiring** in [`backend/app/services/demo_seeding.py`](../../../../backend/app/services/demo_seeding.py): for each scenario flagged UBI-enabled, (a) call the engine-write helper after the engine docs are indexed; (b) after the LLM judgment list is imported, call `POST /api/v1/judgments/generate-from-ubi` and poll until that list reaches `status == "complete"` (the actual JudgmentList terminal-success enum per FR-4); (c) call `_seed_real_study_for_scenario` a second time against the UBI judgment list to produce the paired study.
5. **CLI parity** in [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) (D-7): per-scenario UBI seeding + dual lists + dual studies, sharing the same `synthetic_ubi.py` and `demo_ubi_seed.py` modules.
6. **Cleanup pass update**: add `ubi_queries` + `ubi_events` to `DEMO_ES_INDICES` in `scripts/seed_meaningful_demos.py` so the reseed wipes them at start — guaranteed clean slate per reseed (D-6).
7. **Synthetic-data disclaimer chips** on five UBI UX surfaces, gated by the narrower `isDemoSyntheticUbiClusterName(...)` helper (D-4):
   - GenerateJudgmentsDialog: "Synthetic demo data" badge next to the UBI method-picker options.
   - JudgmentListHeader: same badge for UBI lists on synthetic-UBI demo clusters.
   - Cluster detail page: same badge adjacent to the `<UbiRungBadge>`.
   - Study detail page: same badge next to the title for UBI studies on synthetic-UBI demo clusters.
   - DemoDataBanner: copy update — "includes simulated UBI clickstream on 3 of the 4 demo clusters".
8. **Per-scenario UBI configuration** added to each entry in `SCENARIOS` (D-2):
   - `acme-products-prod` (ES): `ubi_target_rung="rung_3"`, `ubi_converter="ctr_threshold"`.
   - `corp-docs-search` (ES): `ubi_target_rung="rung_1"`, `ubi_converter="hybrid_ubi_llm"`.
   - `jobs-marketplace-prod` (ES): `ubi_target_rung="rung_2"`, `ubi_converter="hybrid_ubi_llm"`.
   - `news-search-staging` (OS): no UBI config (stays rung_0).
   - (rich `acme-products-rich-prod`): no UBI config (LLM-only baseline preserved).

### Out of scope (deferred to Phase 2)

- Dedicated side-by-side UBI-vs-LLM **study** comparison page (digest diff, best-config diff, convergence overlay).
- Promoting the rich ESCI scenario (`acme-products-rich-prod`) to dual-judgment + dual-study.
- A persistent `cluster.is_demo_synthetic_ubi` column or DB flag — Phase 1 uses the existing `isDemoClusterName(...)` recognition for the disclaimer.
- Any production-cluster (non-demo) UBI seeding — RelyLoop never writes UBI on operator clusters; the synthetic generator is gated to demo-cluster slugs at the call site.
- Tutorial guide rewrite (`docs/08_guides/tutorial-first-study.md` Step 11 "compare two studies" subsection). The Step 11 UBI upgrade prose lands in Phase 1's documentation updates (§15), but a dedicated end-to-end "compare two studies" walkthrough is deferred to Phase 2 once the study-comparison view exists.

### Out of scope (always)

- Real (non-synthetic) UBI ingestion. RelyLoop's adapter Protocol is read-only at runtime — operator applications emit UBI; RelyLoop reads.
- LTR training, online A/B, production search-serving path. Per umbrella spec §4 non-goals.
- Multi-tenant or cross-tenant isolation of the synthetic data. Single-tenant through GA v1.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. ✓ Verified at [`backend/app/api/v1/judgments.py`](../../../../backend/app/api/v1/judgments.py).
- **Router namespace for this feature's endpoints:** **None** — Phase 1 adds no new endpoints. It calls the existing `POST /api/v1/judgments/generate-from-ubi` (Story 3.2 of `feat_ubi_judgments`).
- **HTTP methods for CRUD:** N/A — no new endpoints.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md). Phase 1 uses only existing endpoints so it inherits their existing envelopes.
- **Auth error shape:** N/A — single-tenant MVP2.

### Phase boundaries

| Phase | Capabilities | Rationale |
|---|---|---|
| **Phase 1 (this spec)** | Synthetic UBI generator + reseed wiring + CLI parity + dual judgment lists + dual studies + disclaimer chips (FR-1 → FR-12). | All UI surfaces light up "for free" the moment data is present; no frontend changes beyond the disclaimer chip. Operator can already manually open two browser tabs to compare the LLM vs UBI studies on the same scenario. |
| **Phase 2** | Dedicated side-by-side **study** comparison view: digest narrative diff, best-trial param diff, best-metric delta, convergence curve overlay. New route `/studies/compare?a={id_a}&b={id_b}`, new component. | Wraps Phase 1's manual cross-tab comparison in a single page. Justifies its own spec because it's net-new frontend (route + component + data hooks) that requires UX decisions independent of the seed work. **A `phase2_idea.md` tracking artifact is created in this folder by spec finalization (Step 10).** |

---

## 4) Product principles and constraints

- **Honesty over realism.** The synthetic clickstream MUST be labeled as such everywhere a demo operator sees it, gated by `isDemoSyntheticUbiClusterName(...)` (the three-slug helper for clusters that actually receive synthetic UBI). Production clusters and the no-UBI demo cluster (`news-search-staging`) never see the disclaimer.
- **Adapter posture unchanged.** RelyLoop's runtime adapter Protocol stays read-only on UBI per Absolute Rule #4. The synthetic generator runs as **install-side** seed code via the same `engine_client: httpx.AsyncClient` pattern `run_demo_reseed_cleanup` uses today — NOT as a new adapter method or service-layer write.
- **CLI / home-button parity.** Per `bug_demo_reseed_fake_metric_regression`: `make seed-demo` and the home-page "force refresh" button MUST produce **structurally-equivalent** demo state — same set of rows, same names, same configs, same rating values, same per-rung event counts. Timestamps (`created_at`, `judgment_lists.generation_params.since`, UUIDv7 `id` values that embed wall-clock) naturally differ across runs and are NOT part of the parity contract. The synthetic-UBI generator is invoked from both code paths.
- **Bounded wall-clock.** The reseed must complete inside the existing `DEMO_RESEED_JOB_TIMEOUT_S = 1200` (20-min) budget. Synthetic UBI generation per scenario MUST be < 90s wall-clock (incl. bulk write + readiness cache warm); the second study per UBI scenario reuses `_seed_real_study_for_scenario`'s existing 180s ceiling.
- **Engine-neutral generator.** The synthetic generator MUST emit the same shape on Elasticsearch and OpenSearch. Phase 1 only writes to ES because D-2 puts all UBI-enabled scenarios on ES, but the generator code MUST NOT assume ES.
- **Reproducible.** All synthetic data MUST be deterministic given the scenario config + a fixed seed. Phase 1 uses `random.Random(42)` (mirrors the Optuna `seed=42` already pinned for reproducibility).

### Anti-patterns

- **Do not** add a new `SearchAdapter` Protocol method like `write_ubi_events()` — that would violate Absolute Rule #4 by exposing a write path at runtime. The synthetic generator is install-side code only.
- **Do not** introduce a separate `is_demo_synthetic_ubi` column on `clusters` — the four demo slugs are already recognized via `isDemoClusterName(...)`; a new column duplicates state and creates a migration the feature doesn't need.
- **Do not** delete-and-recreate the `ubi_queries` / `ubi_events` indices once per scenario — the three UBI-enabled scenarios share the indices (different `application=<target>` filter values). Cleanup deletes at start; first scenario creates with canonical mapping; subsequent scenarios bulk-write additively (D-6).
- **Do not** inline the mapping JSON in both the TS helper and the Python generator — extract to `samples/ubi_index_mappings.json` (D-1) with a round-trip test pinning equality. Duplicate-source-of-truth is a future-drift hazard.
- **Do not** hardcode click counts or impression-per-pair values inside the orchestrator — encode them in `synthetic_ubi.py` per target rung (rung_1 / rung_2 / rung_3) so the unit tests pin the rung-classification math without spinning up an engine.
- **Do not** rely on Postgres to invalidate the `ubi_readiness:` Redis cache — the reseed creates fresh `cluster_id`s on every cycle (`TRUNCATE RESTART IDENTITY CASCADE`), so the cache key naturally changes. No explicit invalidation needed; verify in an integration test.
- **Do not** call the UBI dispatcher with `converter="hybrid_ubi_llm"` without `current_template_id` + `rubric` — the Pydantic `model_validator` on `CreateJudgmentListFromUbiRequest` ([`backend/app/api/v1/schemas.py:1419`](../../../../backend/app/api/v1/schemas.py#L1419)) will 422 the request. Pass the scenario's existing template_id and rubric through.

## 5) Assumptions and dependencies

- **Dependency:** [`feat_ubi_judgments`](../../implemented_features/2026_05_29_feat_ubi_judgments/) — `POST /api/v1/judgments/generate-from-ubi`, the rung classifier, the converters, the UI surfaces, the `UbiReader`'s `ES_MAX_RESULT_WINDOW=10000` clamp.
  - Why required: this feature exists to make that feature visible in the demo.
  - Status: **shipped (PR #317, 2026-05-29)**.
  - Risk if missing: feature is meaningless without it; will not start.
- **Dependency:** The demo Elasticsearch container (`localhost:9200` host-side, `elasticsearch:9200` Compose-side) MUST accept UBI bulk writes. This is already true — `seed_ubi.ts` writes the same indices today; `_resolve_engine_base_url` already does host→Compose-DNS translation.
  - Status: implemented.
  - Risk if missing: reseed fails on engine-write step; surfaces as `DemoSeedingError("ubi_seed/...")`.
- **Dependency:** Operator runs `make up` first so Postgres + Redis + Elasticsearch containers are healthy before the home-button reseed runs.
  - Status: documented in `local-dev.md`; no change required.
- **Co-tracked follow-ups** (informational only — not blockers):
  - [`chore_ubi_reader_search_after_pagination`](../chore_ubi_reader_search_after_pagination/idea.md) — independent. Synthetic generator volumes for rung_3 (event count ≤ ~640) are well below the `ES_MAX_RESULT_WINDOW=10000` clamp; no coordination needed at Phase 1. Explicit ceiling reaffirmed below in §13.
  - [`chore_ubi_hybrid_template_render`](../chore_ubi_hybrid_template_render/idea.md) — independent. The hybrid LLM-fill path uses the existing per-pair `get_document` callback; no change.

## 6) Actors and roles

- **Primary actor:** Demo operator (anyone running `make up` locally and clicking the home-page "force refresh demo data" button, or running `make seed-demo` from the CLI).
- **Role model:** N/A — single-tenant install, no auth surface (MVP2).
- **Permission boundaries:** N/A — single-tenant.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

The MVP2 `audit_log` table arrives with `feat_audit_log` (separate planned feature; see `state.md` for sequencing). This feature performs only seed-side writes against demo data — those are not state-mutating production endpoints subject to audit emission. Phase 1 emits **no** new audit events.

**Verification:** the only API mutations this feature triggers are `POST /api/v1/judgment-lists/import` and `POST /api/v1/judgments/generate-from-ubi` (both via the reseed's `api_client`) plus `POST /api/v1/studies`. Whether those existing endpoints emit audit events is the responsibility of their owning features (`feat_llm_judgments`, `feat_ubi_judgments`, `feat_study_lifecycle`), not this one — Phase 1 does not change their emission posture.

## 7) Functional requirements

### FR-1: Canonical UBI index mapping

- The system **MUST** ship a single canonical mapping file at `samples/ubi_index_mappings.json` containing the `ubi_queries` and `ubi_events` index mappings (keyword/text/date/integer/float per field) identical byte-for-byte to the shapes currently inlined in [`ui/tests/e2e/helpers/seed_ubi.ts`](../../../../ui/tests/e2e/helpers/seed_ubi.ts) at lines 26-51.
- The Playwright helper `seed_ubi.ts` **MUST** load mappings via `JSON.parse(readFileSync('samples/ubi_index_mappings.json', 'utf8'))` (path relative to repo root, via the existing Playwright `samples/` access pattern).
- The Python generator `backend/app/services/demo_ubi_seed.py` **MUST** load mappings via `json.loads(Path("/app/samples/ubi_index_mappings.json").read_text())` (the in-container `_SAMPLES_DIR = "/app/samples"` Compose mount used by `_seed_rich_scenario`).
- A unit test at `backend/tests/unit/services/test_demo_ubi_seed.py::test_mapping_file_round_trips_to_seed_ubi_helper_shape` **MUST** assert structural equality between the JSON file's parsed content and a pinned dict copy of the original `seed_ubi.ts` shape.

### FR-2: Pure-domain synthetic UBI generator

- The system **MUST** ship a pure-domain module at `backend/app/domain/demo/synthetic_ubi.py` (no I/O, no httpx, no settings) exposing:
  - `fabricate_ubi_for_scenario(*, scenario_judgments_map, query_id_by_index, target_application, target_rung, seed_anchor_iso, seed=42) -> tuple[list[UbiQueryRow], list[UbiEventRow]]` — given a scenario's existing `judgments_map: list[(query_index, doc_id, rating)]`, the API-assigned `query_id` per query index, and a `seed_anchor_iso` string that anchors all synthetic event timestamps (the reseed passes its own `started_at` ISO so events fall inside the dispatcher's lookback window — see FR-4), returns the lists of UBI rows.
  - Internal helpers `_volumes_for_rung(rung) -> RungVolumes`, `_decay_weights(num_ranks, decay=0.6) -> list[float]`, `_click_probability_for_rating(rating: int, base: float) -> float`.
- The generator **MUST** be deterministic given `(scenario_inputs, seed_anchor_iso, seed)`: same inputs → same outputs (use `random.Random(seed)` only, no `time.time()` / `uuid4()` / etc.). Different `seed_anchor_iso` values produce identical row counts and identical rating-correlation structure but shifted timestamps — this is the **structural** equivalence per §4 parity rule.
- **Volume math is independent of decay** (the decay shapes per-rank distribution; the rung target shapes total count). For each rung, `_volumes_for_rung` returns a `RungVolumes(impressions_total, clicks_total, dwell_events_total, num_queries, num_docs_per_query)`:
  - `rung_3`: `impressions_total=560`, `clicks_total=40`, `dwell_events_total=40` → **640 total events** (5 queries × 112 impressions/query + 5 × 8 clicks + 5 × 8 dwells). Floor is `5 × min_impressions_threshold = 500`; this clears it by 28% headroom.
  - `rung_2`: `impressions_total=200`, `clicks_total=20`, `dwell_events_total=20` → **240 total events**. Above `min_impressions_threshold = 100` (140% headroom); below the rung_3 cutoff of 500 (52% headroom).
  - `rung_1`: `impressions_total=40`, `clicks_total=5`, `dwell_events_total=5` → **50 total events**. Below `min_impressions_threshold = 100` (50% headroom).
  - These totals are within-per-scenario; per-target counts (the `application=<target>` filter the `UbiReader` applies) match these directly.
- The total event count per scenario **MUST** stay below `ES_MAX_RESULT_WINDOW=10000`. All three targets satisfy this trivially (max=640).
- **Impression distribution across ranks** uses decay weights with a **remainder-preserving (Hamilton / largest-remainder)** allocator so `sum(impressions_by_rank) == impressions_total` exactly: `weights = _decay_weights(num_docs, decay=0.6)`; per-rank quota = `impressions_total × weights[n] / sum(weights)`; floor each rank, then distribute the integer remainder one impression at a time to the ranks with the largest fractional parts (ties broken by lower rank index — top-ranked doc wins ties). A unit test pins `sum(_allocate_impressions(rung, num_docs)) == _volumes_for_rung(rung).impressions_total` for all three rungs and all five `num_docs` choices in the catalog. The decay shape is what makes `CtrThresholdConverter`'s Wang-Bendersky correction non-trivial vs raw CTR; the exact-sum invariant is what makes `classify_rung` deterministic.
- Clicks per (query, doc) pair **MUST** be proportional to the LLM-assigned rating from `scenario_judgments_map` (rating 0 → 0% click probability, 1 → 20%, 2 → 50%, 3 → 80%) so the derived UBI judgments correlate with the LLM ground truth — making the value-delta card show **meaningful** overlap + drift, not random noise. The click target `clicks_total` is reached by Bernoulli-sampling pairs weighted by rating until the count is met (with `random.Random(seed)`).
- Dwell events **MUST** be emitted per click with a per-rating dwell-seconds distribution (rating 3 → 30-60s, rating 2 → 10-30s, rating 1 → 3-10s, rating 0 → 0s — though rating 0 produces zero clicks so no dwell either). Total dwell events equals `clicks_total`.
- All synthetic event timestamps **MUST** fall inside `[seed_anchor - 60s, seed_anchor]` (per FR-4's UBI dispatcher window). Timestamps within the window are distributed deterministically via `random.Random(seed)`.
- All synthetic events **MUST** carry `application = target_application` (the value matching the `UbiReader`'s filter contract — verified by a unit test).
- The generator **MUST** be unit-testable without any engine, DB, or httpx fixtures. The fast-lane integration test (FR-11) cross-checks the math against the real `classify_rung` over a real ES container.

### FR-3: Engine-write helper

- The system **MUST** ship a service-layer module at `backend/app/services/demo_ubi_seed.py` exposing:
  - `DEMO_UBI_SCENARIO_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset({("acme-products-prod", "products"), ("corp-docs-search", "docs-articles"), ("jobs-marketplace-prod", "job-listings")})` — the three (`scenario_slug`, `target_application`) **pairs** that may legitimately carry synthetic UBI (the canonical D-2 set per the `SCENARIOS` catalog at `scripts/seed_meaningful_demos.py:143`). Gating on the **pair** (not the target alone) prevents the name-collision misuse mode where a future call site could register a non-demo cluster against target index `products` and pass the bare-target guard.
  - `async def seed_synthetic_ubi(*, engine_client: httpx.AsyncClient, engine_base_url: str, host_auth: tuple[str, str], scenario_slug: str, target_application: str, queries: list[UbiQueryRow], events: list[UbiEventRow]) -> int` — bulk-writes via `_bulk` returning the number of events written. **MUST** raise `ValueError(f"seed_synthetic_ubi refuses non-demo (scenario, target): ({scenario_slug!r}, {target_application!r}) not in DEMO_UBI_SCENARIO_ALLOWLIST")` if `(scenario_slug, target_application) not in DEMO_UBI_SCENARIO_ALLOWLIST`. Unit test pins both the allow-path (all 3 pairs) and the reject-path (a registered-production cluster passing `target_application="products"` with `scenario_slug="prod-acme-products"`).
  - `async def ensure_ubi_indices(*, engine_client: httpx.AsyncClient, engine_base_url: str, host_auth: tuple[str, str]) -> None` — create-if-missing per D-6 (PUT mapping; 400-on-already-exists is tolerated).
- The helper **MUST** use `application=<target_application>` to tag every row, matching the `UbiReader`'s filter contract.
- The helper **MUST NOT** delete the indices — cleanup happens once at reseed-start via the existing `DEMO_ES_INDICES` mechanism (D-6).
- The bulk write **MUST** use `?refresh=wait_for` so subsequent rung-classifier reads see the new data without timing flakiness.

### FR-4: Reseed orchestrator wiring

- The system **MUST** extend [`reseed_demo_state`](../../../../backend/app/services/demo_seeding.py#L1065) so for each scenario with a non-null `ubi_target_rung` in its `SCENARIOS` entry, after step 2a (engine docs indexed) but before step 2g (API judgments import):
  - Call `ensure_ubi_indices(...)` once per reseed (idempotent across calls).
  - Call `fabricate_ubi_for_scenario(...)` to build the rows.
  - Call `seed_synthetic_ubi(...)` to bulk-write them to the same engine container.
- The system **MUST** then, after step 2g (LLM judgment list imported), call `POST /api/v1/judgments/generate-from-ubi` via `api_client` with:
  - `name = f"{scenario['judgment_list_name']} (UBI)"`
  - `query_set_id = qset_id`, `cluster_id = cluster_id`, `target = scenario['target']`
  - **`since = seed_anchor - 60s`, `until = seed_anchor`** where `seed_anchor` is `reseed_demo_state`'s `started_at` (the same value the synthetic generator anchors event timestamps on, per FR-2). This bounded 60-second window deterministically captures every synthetic event written by the generator regardless of when the reseed runs — and the dispatcher persists the exact window into `generation_params.since` / `.until` so the worker's resume payload is reproducible.
  - `converter = scenario['ubi_converter']`
  - `mapping_strategy = "reject"` (synthetic generator emits one row per query — duplicates would be a generator bug)
  - For `converter == "hybrid_ubi_llm"`: `current_template_id = template_id`, `rubric = scenario["rubric"]`. For non-hybrid: both null.
- The system **MUST** poll the resulting `judgment_list_id` (GET `/api/v1/judgment-lists/{id}`) until `status == "complete"` or `status == "failed"` (`failed` raises `DemoSeedingError`). The wire enum is `generating | complete | failed` per the DB CHECK constraint at [`backend/app/db/models/judgment_list.py:37`](../../../../backend/app/db/models/judgment_list.py#L37) — earlier drafts of this spec mentioned a "ready" terminal state; that is not a value of the enum. Poll ceiling: 180s (mirrors the LLM-judgment poll budget); poll interval: 3s.
- The system **MUST** then call `_seed_real_study_for_scenario` a SECOND time with the UBI judgment-list id, study name `f"{scenario['study_name']} (UBI)"`, and otherwise identical arguments (same template_id, query_set_id, cluster_id, search_space, seed=42, max_trials=12, parallelism=2).
- For the LLM study created by the first `_seed_real_study_for_scenario` call, the system **MUST** rename it to `f"{scenario['study_name']} (LLM)"` in step 3 (study rename), so the tutorial-friendly names disambiguate the pair.

### FR-5: CLI parity

- The CLI [`scripts/seed_meaningful_demos.py:seed_scenario`](../../../../scripts/seed_meaningful_demos.py#L851) **MUST** invoke the same `synthetic_ubi.py` + `demo_ubi_seed.py` modules in the equivalent positions in its per-scenario flow.
- The CLI's `make seed-demo` output **MUST** match the home-button output for the same scenarios: same per-scenario event count, same dual-list, dual-study layout, same names.

### FR-6: Cleanup pass update

- The system **MUST** add `"ubi_queries"` and `"ubi_events"` to `DEMO_ES_INDICES` in [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) so the existing `run_demo_reseed_cleanup` deletes them at the start of every reseed.
- Subsequent first-write inside the reseed loop will re-create the indices with the canonical mapping.

### FR-7: Synthetic-data disclaimer (D-4)

- A new derived helper [`isDemoSyntheticUbiClusterName(name: string): boolean`](../../../../ui/src/lib/demo-data.ts) **MUST** be added alongside `isDemoClusterName` in [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts), returning `true` only for the three slugs that receive synthetic UBI: `acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod`. The exported tuple `DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS` mirrors the backend-side `DEMO_UBI_SCENARIO_ALLOWLIST` and is covered by the existing `scripts/ci/verify_demo_slug_parity.sh` CI guard (extend it in the same story).
- The UI **MUST** render a `<DemoBadge variant="synthetic-ubi">` chip with text `"Synthetic demo data"` (no period) in **five** surfaces:
  1. **GenerateJudgmentsDialog** — next to each UBI method-picker option (`ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`), gated by `isDemoSyntheticUbiClusterName(cluster.name)`. The chip MUST NOT appear on `news-search-staging` (rung_0 demo cluster — no synthetic UBI; the existing on-ramp nudge tells the operator "real UBI not configured", which is honest copy and shouldn't be contradicted by a "synthetic data" chip).
  2. **JudgmentListHeader** ([`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx)) — gated by `isDemoSyntheticUbiClusterName(cluster.name) && generation_params?.generation_kind === 'ubi'` (the existing UBI-vs-LLM discriminator — see [`ui/src/components/judgments/value-delta-card.tsx:31`](../../../../ui/src/components/judgments/value-delta-card.tsx#L31); **NOT** a `judgment_lists.source` column — that column does not exist; the `JudgmentList` model carries the discriminator inside the `generation_params` JSONB per [`backend/app/db/models/judgment_list.py:74-82`](../../../../backend/app/db/models/judgment_list.py#L74-L82)).
  3. **Cluster detail page** — adjacent to the `<UbiRungBadge>` on `isDemoSyntheticUbiClusterName(cluster.name)`. Without this, an operator on `/clusters/acme-products-prod` sees a `rung_3` badge and may infer real UBI traffic. `news-search-staging` (rung_0 demo cluster) does NOT get the chip. Component change: [`ui/src/components/clusters/cluster-detail-summary.tsx`](../../../../ui/src/components/clusters/cluster-detail-summary.tsx).
  4. **Study detail page header** — for any study whose `judgment_list.generation_params.generation_kind === 'ubi'` AND `isDemoSyntheticUbiClusterName(cluster.name)`. Chip appears next to the study title (or below it on narrow viewports). Component change: the studies detail page in [`ui/src/app/studies/[id]/`](../../../../ui/src/app/studies/%5Bid%5D/).
  5. **DemoDataBanner** ([`ui/src/components/dashboard/demo-data-banner.tsx`](../../../../ui/src/components/dashboard/demo-data-banner.tsx)) — existing copy extended with the sentence: "Three demo clusters include simulated UBI clickstream so the UBI judgment + study path is visible end-to-end." (The banner sentence is not chip-gated — it's prose that mirrors the three-slug allowlist.)
- Tooltip on hover: `"This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior."` The tooltip key is `ubi_synthetic_demo_data`; **a single story in the implementation plan adds this key to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts)** (already exists per `feat_contextual_help` discipline).
- Real operator clusters (non-demo) **MUST NEVER** see this chip, even if they happen to have a UBI list. Demo cluster `news-search-staging` (rung_0, no synthetic UBI) **MUST NOT** see the chip either. The `isDemoSyntheticUbiClusterName` check is the only gating mechanism — verified by the existing CI guard at [`scripts/ci/verify_demo_slug_parity.sh`](../../../../scripts/ci/verify_demo_slug_parity.sh) (extended in this feature to also pin `DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS` against `DEMO_UBI_SCENARIO_ALLOWLIST`).
- A vitest component test **MUST** pin THREE branches for each of the five surfaces: (a) synthetic-UBI demo cluster → chip visible; (b) demo cluster without synthetic UBI (`news-search-staging`) → chip absent; (c) non-demo cluster → chip absent.

### FR-8: Per-scenario configuration in SCENARIOS

- The system **MUST** extend each entry in `SCENARIOS` ([`scripts/seed_meaningful_demos.py:143`](../../../../scripts/seed_meaningful_demos.py#L143)) with two optional keys:
  - `ubi_target_rung: Literal["rung_1", "rung_2", "rung_3"] | None` — null means "no UBI for this scenario".
  - `ubi_converter: Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"] | None` — null iff `ubi_target_rung` is null.
- The system **MUST** populate them per D-2:
  - `acme-products-prod`: `ubi_target_rung="rung_3"`, `ubi_converter="ctr_threshold"`.
  - `corp-docs-search`: `ubi_target_rung="rung_1"`, `ubi_converter="hybrid_ubi_llm"`.
  - `jobs-marketplace-prod`: `ubi_target_rung="rung_2"`, `ubi_converter="hybrid_ubi_llm"`.
  - `news-search-staging`: both null.
- The system **MUST** validate at SCENARIOS-load time (or first use) that `ubi_converter is None ↔ ubi_target_rung is None`. Module-level assertion is acceptable; a unit test pins it.

### FR-9: Dual-study seeding & naming

- For each UBI-enabled scenario, the system **MUST** seed **two** studies on the same query set:
  - `f"{study_name} (LLM)"` — graded against the LLM judgment list.
  - `f"{study_name} (UBI)"` — graded against the UBI judgment list.
- Both studies **MUST** use identical Optuna config: `seed=42`, `max_trials=12`, `parallelism=2`, `sampler="tpe"`. Same `template_id`, same `query_set_id`, same `cluster_id`, same `search_space`, same `objective` (`{"metric": "ndcg", "k": 10, "direction": "maximize"}`).
- The system **MUST** poll both studies to terminal state (`completed` / `failed` / `cancelled`) before advancing to the next scenario, using `_seed_real_study_for_scenario`'s existing 180s ceiling. A `failed` LLM study still raises `DemoSeedingError` (matches current behavior); a `failed` UBI study **MUST** also raise (no silent skip).

### FR-10: Status reporting

- The reseed status reporting (the existing `ReseedStatusResponse` mechanism) **MUST** include UBI sub-step labels in `current_step`:
  - `f"{slug}: writing synthetic UBI ({rung}, {event_count} events)"`
  - `f"{slug}: dispatching UBI judgment generation ({converter})"`
  - `f"{slug}: polling UBI judgment list {id[:8]} for completion"`
  - `f"{slug}: creating UBI study (max_trials=12)"`
  - `f"{slug}: polling UBI study {id[:8]} for trial completion"`
- The `scenarios_total` count **MUST NOT** change — Phase 1 still has 5 scenarios; each UBI scenario just contains more sub-steps.

### FR-11: Synthetic-data integration test coverage

Phase 1 splits integration coverage into two lanes so the always-on lane stays under 60s while the full-reseed assertion survives the `SKIP_HEAVY_CI` gate:

- **Fast lane** (`backend/tests/integration/services/test_demo_seeding_ubi_fast.py`) — always-on (runs even with `SKIP_HEAVY_CI=true`):
  - Constructs one UBI-enabled scenario in isolation (the `acme-products-prod` rung_3 config) and invokes `seed_synthetic_ubi(...)` against the test ES container.
  - Calls `classify_rung(...)` against the seeded data; asserts `rung == "rung_3"`.
  - Asserts the canonical mapping file round-trips (FR-1).
  - Wall-clock target: < 60s. No `reseed_demo_state` invocation; no LLM calls.
- **Heavy lane** (`backend/tests/integration/services/test_demo_seeding_ubi_full.py`) — gated by `not os.environ.get("SKIP_HEAVY_CI")`; runs nightly + on demand:
  - Runs full `reseed_demo_state` against real Postgres + real ES + Redis.
  - Asserts the 3 UBI-enabled scenarios each produced exactly 2 judgment lists per AC-1's `generation_params`-based discriminator (LLM list: `generation_params IS NULL`; UBI list: `generation_params->>'generation_kind' = 'ubi'` AND `generation_params->>'converter' = <scenario["ubi_converter"]>`). **Do NOT reference a non-existent `judgment_lists.source` column.**
  - Asserts the rung classifier returns the **expected rung** per AC-2 for each UBI-enabled scenario (rung_3 for acme, rung_2 for jobs, rung_1 for corp).
  - Asserts the OS scenario reports `rung_0` (no UBI data on the OS cluster).
  - Asserts the AC-8 wall-clock ceiling (< 1140s per run; logs duration for separate trend monitoring).

### FR-12: E2E coverage for the UBI demo surfaces

- A new Playwright spec at `ui/tests/e2e/demo-ubi.spec.ts` **MUST** assert against the live reseeded stack with real backend, no `page.route()` mocking.
- **Precondition / `beforeAll`**: the spec **MUST** invoke `POST /api/v1/_test/demo/reseed` via Playwright's `request` fixture and then poll the existing reseed-status endpoint until `status === "complete"` or fail with a clear diagnostic. Poll budget: 25 minutes (matches the heavy-lane integration test's worst-case wall-clock from §14). Discover cluster / query-set / judgment-list IDs by GET-ing the API after reseed completion — no hardcoded UUIDs, no mocked routes.
- **Test cases** (each runs after `beforeAll` establishes the seeded stack):
  - Open `/clusters/{acme_id}` → the `<UbiRungBadge>` reads `"rung_3"` AND the synthetic-data chip is visible (FR-7 surface #3).
  - Open the generate-judgments dialog on the acme query set → the method picker defaults to `ctr_threshold` AND the synthetic-data chip is visible next to UBI options (FR-7 surface #1).
  - Open the UBI judgment-list detail page for the acme scenario → the `<ValueDeltaCard>` is visible AND shows non-zero per-(query, doc) deltas vs the LLM list; the synthetic-data chip is in the header (FR-7 surface #2).
  - Open the `(UBI)` study detail page for the acme scenario → the synthetic-data chip is visible next to the title (FR-7 surface #4).
  - Open `/clusters/{news_id}` → the `<UbiRungBadge>` reads `"rung_0"` AND the `<UbiOnrampNudge>` is visible (proves engine-neutral copy works on OpenSearch).
- **CI gating**: this spec joins the existing real-backend E2E suite that runs in the `pr.yml` heavy lane; under `SKIP_HEAVY_CI=true` it skips with a logged reason matching the pattern other heavy specs use. Local operators run it on demand via the existing `pnpm e2e` Playwright invocation after `make seed-demo`.

## 8) API and data contract baseline

### 8.1 Endpoint surface

**No new endpoints in Phase 1.** Phase 1 calls these existing endpoints internally via the reseed's `api_client`. The wire schemas are stable and owned by their source feature — Phase 1 inherits them unchanged:

| Method | Path | Source feature | Request / response schemas | Purpose in this feature |
|---|---|---|---|---|
| `POST` | `/api/v1/judgment-lists/import` | `feat_llm_judgments` | Request: `ImportJudgmentListRequest` ([schemas.py:987](../../../../backend/app/api/v1/schemas.py#L987)). Response: `JudgmentListDetail` ([schemas.py:919](../../../../backend/app/api/v1/schemas.py#L919)). Reseed reads `.id`. | Import the LLM judgment list (existing behavior; the reseed already uses this — see [demo_seeding.py:1284](../../../../backend/app/services/demo_seeding.py#L1284)) |
| `POST` | `/api/v1/judgments/generate-from-ubi` | `feat_ubi_judgments` | Request: `CreateJudgmentListFromUbiRequest` ([schemas.py:1393](../../../../backend/app/api/v1/schemas.py#L1393)). Response: `GenerateJudgmentsResponse` ([schemas.py:880](../../../../backend/app/api/v1/schemas.py#L880)). Reseed reads `.judgment_list_id`. | Dispatch the UBI judgment list generation |
| `GET` | `/api/v1/judgment-lists/{id}` | `feat_llm_judgments` | Response: `JudgmentListDetail` ([schemas.py:919](../../../../backend/app/api/v1/schemas.py#L919)). Reseed reads `.status` ∈ `{generating, complete, failed}` (DB CHECK at [judgment_list.py:37](../../../../backend/app/db/models/judgment_list.py#L37)) and `.failed_reason`. | Poll UBI list status |
| `POST` | `/api/v1/studies` | `feat_study_lifecycle` | Reseed already uses this — see [demo_seeding.py:655](../../../../backend/app/services/demo_seeding.py#L655). Reseed reads `.id`. | Create the UBI study |
| `GET` | `/api/v1/studies/{id}` | `feat_study_lifecycle` | Reseed already uses this — see [demo_seeding.py:686](../../../../backend/app/services/demo_seeding.py#L686). Reseed reads `.status` and `.trials_summary.total`. | Poll study terminal state |
| `GET` | `/api/v1/studies/{id}/digest` | `feat_digest_proposal` | Reseed already uses this — see [demo_seeding.py:717](../../../../backend/app/services/demo_seeding.py#L717). 404 (`DIGEST_NOT_READY`) is the expected polling state. | Poll digest ready |

The `import` sub-route (vs a plain `POST /api/v1/judgment-lists`) is deliberate — that's the existing endpoint the reseed already uses for the LLM list. Phase 1 does not introduce, rename, or duplicate it.

### 8.2 Contract rules

N/A — no new endpoints. Phase 1 inherits all existing contract rules from the listed source features.

### 8.3 Response examples

N/A — no new endpoints.

### 8.4 Enumerated value contracts

Phase 1 reads from and writes to these existing wire allowlists. Every value the reseed sends or recognizes is grounded in a backend `Literal[...]`:

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `converter` (UBI dispatch body) | `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm` | [`backend/app/api/v1/schemas.py:846`](../../../../backend/app/api/v1/schemas.py#L846) `UbiConverterKind` | `generate-judgments-dialog.tsx` method picker via `JUDGMENT_GENERATION_METHOD_VALUES` in `ui/src/lib/enums.ts` |
| `mapping_strategy` (UBI dispatch body) | `reject`, `first_match`, `most_recent` | [`backend/app/api/v1/schemas.py:864`](../../../../backend/app/api/v1/schemas.py#L864) `UbiMappingStrategyWire` | (frontend not yet a picker; Phase 1 uses backend default `reject`) |
| `rung` (UBI readiness + badge) | `rung_0`, `rung_1`, `rung_2`, `rung_3` | [`backend/app/api/v1/schemas.py:858`](../../../../backend/app/api/v1/schemas.py#L858) `UbiReadinessRungWire` | `UbiRungBadge` component |
| `ubi_target_rung` (NEW — in SCENARIOS) | `rung_1`, `rung_2`, `rung_3`, `None` | NEW: `scripts/seed_meaningful_demos.py` SCENARIOS entries; type checked by a module-level assertion (FR-8). **Not a backend wire value** — internal seed config only. | N/A — never sent to a router |
| `ubi_converter` (NEW — in SCENARIOS) | `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`, `None` | NEW: `scripts/seed_meaningful_demos.py` SCENARIOS entries; value MUST be one of `UbiConverterKind` Literals (constrained by assertion). | N/A — never sent to a router |
| `generation_params.generation_kind` (read by FR-7 disclaimer) | `'ubi'` (set by the UBI dispatcher) OR `null` (LLM lists leave the whole JSONB column NULL) | [`backend/app/db/models/judgment_list.py:74-82`](../../../../backend/app/db/models/judgment_list.py#L74-L82) docstring — Phase 1 reads, does not write. **There is no `judgment_lists.source` column** — the UBI/LLM discriminator lives inside the `generation_params` JSONB. | `judgment-list-header.tsx` — disclaimer chip visibility (mirrors `value-delta-card.tsx:31`) |

**Wire-value discipline reminder:** The two NEW SCENARIOS keys (`ubi_target_rung`, `ubi_converter`) are internal seed config, NOT wire values. They never leave the install-side seed code. The `ubi_converter` value DOES become a wire value when the reseed calls `POST /judgments/generate-from-ubi`, and at that boundary the constraint is enforced by the existing Pydantic Literal — the seed-side assertion is belt-and-suspenders.

### 8.5 Error code catalog

No new error codes. Phase 1 surfaces existing errors that follow the canonical `{ "detail": { "error_code", "message", "retryable" } }` envelope per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md). The reseed orchestrator handles each error by raising `DemoSeedingError(...)` with a per-step prefix so the route handler can return 503 `SEED_FAILED`:

| Code | HTTP Status | Source feature | When raised in Phase 1 |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | FastAPI / Pydantic | Hybrid converter dispatched without `current_template_id` or `rubric` (bug in seed config; caught by FR-8 assertion before dispatch) |
| `UBI_INSUFFICIENT_DATA` | 422 | `feat_ubi_judgments` | Should not occur in the demo — synthetic generator targets rung_3 / rung_2 / rung_1 deterministically. If it does, raises `DemoSeedingError("ubi_judgments/{slug}: 422 UBI_INSUFFICIENT_DATA — generator volumes drifted")` |
| `DemoSeedingError` (Python exception, mapped to 503 `SEED_FAILED` by the route handler) | 503 | this feature + existing | Any unrecoverable failure in the synthetic-UBI sub-steps |

## 9) Data model and state transitions

### New tables

**None.** Phase 1 adds zero database tables and zero migrations.

### Modified tables

**None at the schema level.** Phase 1 changes only the **content** seeded into existing tables (`clusters`, `query_sets`, `judgment_lists`, `studies`) and the **content** written to engine indices (`ubi_queries`, `ubi_events` on Elasticsearch).

### New seed-config keys (not DB columns)

Two new keys on each `SCENARIOS` entry in `scripts/seed_meaningful_demos.py`:

- `ubi_target_rung: Literal["rung_1", "rung_2", "rung_3"] | None`
- `ubi_converter: Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"] | None`

These are install-side Python literals; they do not appear in any DB table or API contract.

### New files

- `samples/ubi_index_mappings.json` — canonical UBI index mapping JSON (FR-1).
- `backend/app/domain/demo/synthetic_ubi.py` — pure generator (FR-2).
- `backend/app/services/demo_ubi_seed.py` — engine-write helper (FR-3).
- `backend/tests/unit/domain/test_synthetic_ubi.py` — unit tests for the generator.
- `backend/tests/unit/services/test_demo_ubi_seed.py` — unit tests including the mapping round-trip (FR-1).
- `backend/tests/integration/services/test_demo_seeding_ubi_fast.py` — fast-lane integration test (<60s, always-on; FR-11).
- `backend/tests/integration/services/test_demo_seeding_ubi_full.py` — heavy-lane integration test (full reseed, gated by `SKIP_HEAVY_CI`; FR-11).
- `ui/tests/e2e/demo-ubi.spec.ts` — E2E spec (FR-12).
- `docs/00_overview/planned_features/02_mvp2/feat_demo_ubi_study_comparison/phase2_idea.md` — phase 2 tracking artifact (spec-finalization Step 10).

### Required invariants

- **Generator determinism:** `fabricate_ubi_for_scenario(seed=42, ...)` is byte-identical across runs for the same input scenario. Unit test pins it via a `pytest.approx(...)`-tolerant total-event-count assertion plus a snapshot test on the first 10 rows.
- **Rung achievability:** Each rung's `_volumes_for_rung` output, when written for a single scenario with `application=<target>`, MUST classify to the target rung when read by `classify_rung(..., min_impressions_threshold=100)`. Integration test verifies (FR-11).
- **Cleanup safety:** After `run_demo_reseed_cleanup` runs, both `ubi_queries` and `ubi_events` are absent (HTTP 404 from `GET /ubi_queries`). The first UBI-enabled scenario re-creates them.
- **Demo-cluster gating:** The disclaimer chip renders if and only if `isDemoSyntheticUbiClusterName(cluster.name) === true` AND the surface is UBI-relevant (UBI method-picker option, UBI judgment list header, UBI study header, or cluster summary on a synthetic-UBI demo cluster). Vitest component tests pin all three branches per surface — synthetic-UBI demo cluster, demo cluster without synthetic UBI (`news-search-staging`), and non-demo cluster.
- **CLI / home-button output equivalence:** For identical seed input (env: same `OPENAI_BASE_URL`, same models), the CLI and home button produce the same set of `(cluster, judgment_list, study)` rows. Verified by a dual-path integration test (existing pattern from `bug_demo_reseed_fake_metric_regression`).
- **`application` filter consistency:** Every UBI event row written for a scenario MUST carry `application=<scenario["target"]>` (the same value the `UbiReader` filters on). Generator unit test pins it.

### State transitions

No new state machines. Phase 1 invokes existing transitions:

- `judgment_list.status: generating → complete | failed` (existing — DB CHECK enum per [`backend/app/db/models/judgment_list.py:37`](../../../../backend/app/db/models/judgment_list.py#L37); set by `feat_ubi_judgments` worker on terminal transition).
- `study.status: queued → running → completed` (existing — `feat_study_lifecycle`).
- `ubi_readiness.rung: rung_0 → rung_3` for a given `(cluster, query_set, target)` once the synthetic data lands (state transition is observational, not a write — the readiness classifier is read-only).

## 10) Security, privacy, and compliance

- **Threats:**
  - Synthetic data leaks into a production cluster registration. **Mitigation:** the generator runs only inside `reseed_demo_state` / `seed_meaningful_demos.py:seed_scenario`, both of which target the dev Compose Elasticsearch container. The `DEMO_UBI_SCENARIO_ALLOWLIST` guard in `seed_synthetic_ubi(...)` (FR-3) refuses any call with a `(scenario_slug, target_application)` pair outside the three demo entries — defense-in-depth against a future code path importing the helper. The UI disclaimer chip is gated by `isDemoSyntheticUbiClusterName(...)` (the three-slug allowlist), so an operator who somehow registers a production cluster with a demo-UBI slug name would see the disclaimer and be alerted.
  - The disclaimer copy is missed by a non-English operator. **Mitigation:** RelyLoop is English-only through GA v1; out of scope.
  - The CLI / home-button parity drift. **Mitigation:** existing `bug_demo_reseed_fake_metric_regression` test pattern is extended (FR-5).
- **Controls:** existing Compose-network isolation; no new secrets; no PII (synthetic data is by definition not user data).
- **Secrets / key handling:** none added. The reseed still uses the host's `OPENAI_API_KEY_FILE`-mounted key for the LLM judgment generation; the UBI generation does **not** call the LLM except in the hybrid path (`corp-docs-search` rung_1 + `jobs-marketplace-prod` rung_2), which uses the same already-configured key.
- **Auditability:** N/A — `audit_log` not yet shipped.
- **Data retention / deletion / export impact:** none. The synthetic data is wiped + re-created on every reseed.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new navigation. The synthetic-data chips render inline on existing pages (`/judgments/{id}`, the generate-judgments dialog, the home page's `DemoDataBanner`). No new sidebar entry, no new tab.
- **Labeling taxonomy:** Three new strings:
  - Chip label: `"Synthetic demo data"` (no period).
  - Chip tooltip: `"This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior."`
  - Banner sentence addition: `"Three demo clusters include simulated UBI clickstream so the UBI judgment + study path is visible end-to-end."`
- **Content hierarchy:** Existing surfaces unchanged. The disclaimer chip is a small, low-visual-weight element sized like the existing `DemoBadge` — never the page's primary focus, but always visible without scrolling on the affected surfaces.
- **Progressive disclosure:** No new disclosure. The synthetic state is the default state of the demo dataset; there is no "show synthetic / show real" toggle.
- **Relationship to existing pages:** This feature does **not** add or move pages — it makes the existing UBI-related pages (`/clusters/{id}`, `/query-sets/{id}`, `/judgments/{id}`, `/studies/{id}`) demonstrate end-to-end on the demo cluster set.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| `<DemoBadge variant="synthetic-ubi">` chip on UBI method-picker options (when `isDemoSyntheticUbiClusterName(cluster.name)`) | `"This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior."` | hover or keyboard focus | top |
| Same chip on `JudgmentListHeader` for UBI lists on synthetic-UBI demo clusters | same text | hover or keyboard focus | top |
| Same chip on Cluster detail page next to `<UbiRungBadge>` (synthetic-UBI demo clusters only) | same text | hover or keyboard focus | top |
| Same chip on Study detail page header (UBI study on a synthetic-UBI demo cluster) | same text | hover or keyboard focus | top |
| `DemoDataBanner` banner sentence extension | (no tooltip — banner already inline-explains itself) | — | — |

**Glossary key:** add `ubi_synthetic_demo_data: { label: "Synthetic demo data", helpText: "This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior." }` to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) — single story in the impl plan, scoped to the disclaimer-chip work.

### Primary flows

1. **Operator runs `make up` then clicks "Force refresh demo data" on the home page.**
   - Status banner shows reseed progress; new sub-steps surface UBI generation per scenario (FR-10).
   - On completion: the dashboard shows 5 clusters, 8 judgment lists, 8 studies (was 5 / 5 / 5). The 3 UBI-enabled clusters carry their rung badges; the OS cluster carries `rung_0` with the on-ramp nudge.
2. **Operator opens `/clusters/acme-products-prod` → "Generate judgments".**
   - Method picker defaults to `ctr_threshold` (rung_3).
   - The `<DemoBadge variant="synthetic-ubi">` chip is visible next to the UBI options.
   - Operator can submit and observe a new UBI list being created alongside the existing demo lists.
3. **Operator opens `/clusters/corp-docs-search` → "Generate judgments".**
   - Method picker defaults to `hybrid_ubi_llm` (rung_1).
   - The sparse-data card is visible above the form.
   - Same disclaimer chip; submit produces a hybrid list.
4. **Operator opens the UBI judgment list for `acme-products-prod`.**
   - JudgmentListHeader shows the chip.
   - Value-delta card lights up automatically — operator sees per-(query, doc) overlap and drift vs the LLM list on the same query set.
5. **Operator manually opens both `(LLM)` and `(UBI)` studies for acme in two browser tabs.**
   - Operator reads digest narratives, best-trial params, best-metric values side-by-side.
   - Phase 2 wraps this in a single page; Phase 1 ships the manual path.

### Edge / error flows

- **Synthetic UBI generation fails (engine 5xx):** Reseed raises `DemoSeedingError("ubi_seed/...")` and the route handler returns 503 `SEED_FAILED` with the existing recovery copy. Operator clicks "Force refresh" again.
- **UBI judgment generation worker fails (e.g., LLM timeout in hybrid mode):** Polling detects `judgment_list.status == "failed"`, reseed raises `DemoSeedingError("ubi_judgments/{slug}: failed")`. Same recovery as above.
- **UBI study fails:** Same as today's LLM-study-fail behavior — `DemoSeedingError` raised, 503 returned. Operator clicks again.
- **Rung classifier disagrees with the target rung after reseed (integration test discovers this):** Test fails CI before the PR can merge. No production exposure.
- **Operator inspects raw `ubi_queries`/`ubi_events` via curl during a partial reseed:** They may see only a subset of scenarios' rows. This is benign — the reseed is single-flight via the advisory lock, and the partial state is recovered on the next click.
- **Operator opens the value-delta card before the UBI list completes:** Existing component already handles `status === "generating"` (the in-progress enum value) with a skeleton; no new path.

## 12) Given/When/Then acceptance criteria

### AC-1: Reseed produces dual lists + dual studies on UBI-enabled scenarios

- **Given** a clean dev stack (`make up` completed; no prior reseed)
- **When** the operator clicks "Force refresh demo data" on the home page (or runs `make seed-demo`)
- **Then** after the reseed completes:
  - `SELECT COUNT(*) FROM judgment_lists` returns **8** (was 5: 1 per of 5 scenarios; now 1 + 2 + 2 + 2 + 1 = 8).
  - `SELECT COUNT(*) FROM studies` returns **8** (was 5; same distribution).
  - For each of `acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod`, exactly two `judgment_lists` rows exist with `query_set_id` equal to that scenario's query-set id — one with `generation_params IS NULL` (the imported LLM list — `judgment_lists.generation_params` is NULL for LLM lists per [`backend/app/db/models/judgment_list.py:74-82`](../../../../backend/app/db/models/judgment_list.py#L74-L82)) and one with `generation_params->>'generation_kind' = 'ubi'` AND `generation_params->>'converter'` equal to the scenario's `ubi_converter`.

### AC-2: Rung classifier returns the target rung per scenario

- **Given** the reseed just completed
- **When** `GET /api/v1/clusters/{id}/ubi-readiness?query_set_id=<id>&target=<target>` is called for each scenario
- **Then** the response `rung` field equals:
  - `"rung_3"` for `acme-products-prod`
  - `"rung_2"` for `jobs-marketplace-prod`
  - `"rung_1"` for `corp-docs-search`
  - `"rung_0"` for `news-search-staging`
  - `"rung_0"` for `acme-products-rich-prod`

### AC-3: Synthetic generator is deterministic

- **Given** a fixed scenario config (the `acme-products-prod` SCENARIOS entry) and `seed=42`
- **When** `fabricate_ubi_for_scenario(...)` is called twice
- **Then** both calls return the same lists in the same order, with identical row contents.

### AC-4: Disclaimer chip visibility is synthetic-UBI-demo-cluster-gated

- **Given** an operator viewing the `GenerateJudgmentsDialog` on a synthetic-UBI demo cluster (`acme-products-prod`)
- **When** the method picker is rendered
- **Then** the `Synthetic demo data` chip is visible next to the UBI options.
- **And given** an operator viewing the same dialog on the demo cluster without synthetic UBI (`news-search-staging`, rung_0)
- **When** the method picker is rendered
- **Then** the chip is NOT visible (gating helper `isDemoSyntheticUbiClusterName` returns `false`).
- **And given** an operator viewing the same dialog on a registered production cluster (`isDemoSyntheticUbiClusterName === false`)
- **When** the method picker is rendered
- **Then** the chip is NOT visible.

### AC-5: Value-delta card shows non-zero deltas on the UBI list

- **Given** the reseed completed for `acme-products-prod`
- **When** the operator opens the UBI judgment-list detail page
- **Then** the `ValueDeltaCard` is visible, AND it shows non-zero per-(query, doc) deltas for at least one pair (proving the UBI ratings differ from the LLM ratings — which they should, because position bias + click-rate correlation produce a different ranking than the LLM's rubric-based grading).

### AC-6: Engine-neutral on-ramp nudge renders on OpenSearch

- **Given** the reseed completed
- **When** the operator opens `/clusters/news-search-staging` (the OS demo cluster)
- **Then** the `UbiOnrampNudge` component is visible with its engine-neutral copy, AND the `UbiRungBadge` reads `"rung_0"`.

### AC-7: CLI parity

- **Given** a clean dev stack
- **When** `make seed-demo` is run
- **Then** the resulting `judgment_lists` and `studies` row counts match the home-button reseed AC-1 output (8 / 8).

### AC-8: Reseed wall-clock stays under the 20-min budget

- **Given** a typical dev laptop running `make seed-demo` (or the CI heavy-lane runner running the full reseed integration test)
- **When** the reseed completes
- **Then** the single run's wall-clock is **< 1140 seconds (19 min)** — a hard per-run ceiling enforced by `assert duration_s < 1140` in the heavy-lane integration test. This leaves 60s headroom below the `DEMO_RESEED_JOB_TIMEOUT_S = 1200` worker timeout.
- **Trend monitoring (separate from the AC):** the heavy-lane test also `log.info("demo_reseed_full_duration_s", duration_s)` so a separate nightly job (out of scope for Phase 1) can compute p95 across recent runs and surface drift. A single CI run cannot compute p95; the AC is the per-run ceiling, not a p95 calculation.

### AC-9: Failure modes raise DemoSeedingError, not silent skip

- **Given** the integration-test stack with the UBI judgment worker configured to fail (e.g., via fault-injection fixture)
- **When** the reseed runs
- **Then** the orchestrator raises `DemoSeedingError("ubi_judgments/...failed")` (NOT a soft-skip with a warning log).

### AC-10: Cleanup deletes UBI indices on reseed start

- **Given** a state where `ubi_queries` and `ubi_events` indices exist with stale data (e.g., from a prior reseed)
- **When** `reseed_demo_state` runs again
- **Then** the cleanup pass DELETEs both indices before the per-scenario loop begins.

## 13) Non-functional requirements

- **Performance:** Synthetic UBI write per scenario < 90s wall-clock (bulk write ≤ 640 events for the densest rung_3 scenario; engine `refresh=wait_for` adds ~1s). UBI judgment-list generation per scenario respects the existing 180s safety ceiling (typical wall-clock 30-60s; hybrid mode adds the LLM-fill cost on the sparse tail). Each UBI study reuses `_seed_real_study_for_scenario`'s existing 180s ceiling.
- **Reseed wall-clock budget (the headline risk).** Current reseed: 10-15 min typical for 5 LLM lists + 5 studies. Phase 1 adds:
  - 3 × synthetic UBI write (~90s × 3 = ~5 min worst case)
  - 3 × UBI judgment dispatch + poll (~60s × 3 = ~3 min typical; up to ~9 min worst case if all three hit the 180s ceiling)
  - 3 × additional UBI study (~90s × 3 = ~5 min typical; up to ~9 min worst case)
  - Estimated p95 total: ~18-19 min. Estimated worst case: ~28 min — exceeds the 20-min `DEMO_RESEED_JOB_TIMEOUT_S = 1200`.
  - **Mitigation gate (locked in plan-gen Step 1):** if the heavy-lane integration test (FR-11) ever reports a single run exceeding the AC-8 ceiling of 1140s on a representative dev laptop, the plan's first remediation lever is to lower UBI demo-study `max_trials` from 12 to 6 (preserves the value-delta comparison shape; the demo studies are demonstrations, not statistical-power runs). Second lever: drop the UBI sweep for `corp-docs-search` from Phase 1 (keep rung_3 + rung_2 only; rung_1's sparse-data card already renders on the LLM-list flow without UBI data present). Third lever: raise `DEMO_RESEED_JOB_TIMEOUT_S` to 1800 — but only with explicit operator opt-in, since it changes the dev-stack contract.
- **Reliability:** Failures in any UBI sub-step raise `DemoSeedingError` and bubble to the route handler's 503 `SEED_FAILED` response. The existing `docker compose restart api` recovery instruction remains correct.
- **Operability:**
  - New structured-log events: `demo_reseed_ubi_seed_started`, `demo_reseed_ubi_seed_complete`, `demo_reseed_ubi_judgment_dispatch_started`, `demo_reseed_ubi_study_complete`. Same format as existing reseed log events (`extra={"slug", "rung", "event_count", "duration_ms"}`).
  - Metrics: none added (MVP2 has no metrics emitter yet; reuses MVP1's log-only posture).
- **Accessibility:** the new `<DemoBadge variant="synthetic-ubi">` chip MUST be keyboard-focusable AND have an `aria-label` matching its visible text. Tooltip MUST be revealable via keyboard focus, not hover-only.

**Scale-headroom note (scoped per `UbiReader` call).** The `UbiReader` filter is `(application=<target>, timestamp ∈ [since, until], query_id IN <set>)`. Per scenario per call, the synthetic generator emits ≤ 640 events for rung_3 (the densest target) — well below the `UbiReader`'s `ES_MAX_RESULT_WINDOW=10000` per-call clamp. The aggregate across all three synthetic scenarios is ≤ ~930 events on the shared `ubi_events` index (partitioned by `application` filter), still far below 10,000. No coordination with [`chore_ubi_reader_search_after_pagination`](../chore_ubi_reader_search_after_pagination/idea.md) is required for Phase 1. If a Phase 2 expansion ever pushes per-scenario event count above ~9000, that chore becomes a blocker — the spec for Phase 2 will need to assert the bound.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `domain/test_synthetic_ubi.py` — generator determinism (AC-3), per-rung volume targets, position-bias decay math, click-probability-from-rating mapping, `application=<target>` consistency.
  - `services/test_demo_ubi_seed.py` — canonical-mapping round-trip (FR-1), `ensure_ubi_indices` create-if-missing logic, `seed_synthetic_ubi` bulk-write shape (via mocked `httpx.AsyncClient`).
  - Disclaimer-chip component test (vitest) — three visibility branches per surface: synthetic-UBI demo cluster (visible), demo cluster without synthetic UBI (`news-search-staging`, hidden), non-demo cluster (hidden) (AC-4).
- **Integration tests (`backend/tests/integration/`):** split into two lanes per FR-11.
  - **Fast lane**: `services/test_demo_seeding_ubi_fast.py` — always-on; <60s wall-clock; constructs one UBI-enabled scenario (acme rung_3) in isolation, calls `seed_synthetic_ubi(...)` against the test ES container, asserts the rung classifier returns `rung_3`, asserts the mapping-file round-trip. Runs under `SKIP_HEAVY_CI=true`.
  - **Heavy lane**: `services/test_demo_seeding_ubi_full.py` — gated by `not os.environ.get("SKIP_HEAVY_CI")`; full `reseed_demo_state` against real Postgres + ES + Redis; asserts AC-1, AC-2, AC-9, AC-10, AC-8 (wall-clock < 19 min p95).
  - **CLI parity**: `scripts/test_seed_meaningful_demos_ubi.py` (if the existing `test_seed_meaningful_demos.py` pattern is in place) — runs in the heavy lane alongside the full reseed; asserts AC-7 (CLI output structurally matches home-button output for the per-rung event counts, per-scenario list/study counts, and rating-correlation shape — NOT timestamp identity per §4).
- **Contract tests (`backend/tests/contract/`):**
  - No new contract tests — Phase 1 adds no new endpoints. Existing contracts for `POST /api/v1/judgments/generate-from-ubi`, `GET /api/v1/clusters/{id}/ubi-readiness`, etc., already cover their respective shapes.
- **E2E tests (`ui/tests/e2e/`):**
  - `specs/demo-ubi.spec.ts` — real-backend (not `page.route()`-mocked) — AC-2 (badge), AC-4 (disclaimer), AC-5 (value-delta), AC-6 (OS engine-neutral nudge).
  - Update `specs/dashboard.spec.ts` study-count assertion from 5 → 8.
- **Performance / wall-clock test:** the **heavy-lane** integration test for AC-1 asserts a per-run hard ceiling of < 1140s (AC-8) and logs the duration to a structured-log key (`demo_reseed_full_duration_s`) for separate nightly p95 trend monitoring (out of scope for Phase 1 — this feature ships only the ceiling assertion + the log line; p95 aggregation lands later if drift becomes a recurring issue). The fast-lane test does NOT exercise the wall-clock budget.

## 15) Documentation update requirements

- [`docs/01_architecture/mvp2-overview.md`](../../../../01_architecture/mvp2-overview.md) §4 "UBI on-ramp": add a paragraph noting that the demo dataset includes synthetic UBI on three of four clusters so the on-ramp ladder is browser-visible without operator setup. Cite this spec.
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) §"UBI on Solr / engine-agnostic UbiReader": no change required (the synthetic generator does not touch the adapter Protocol — it writes via the same install-side `engine_client` precedent the cleanup uses).
- `docs/02_product/`: no change. This feature does not introduce a new user-facing capability — it makes the existing UBI feature visible in the demo.
- [`docs/03_runbooks/ubi-judgment-generation.md`](../../../../03_runbooks/ubi-judgment-generation.md): add a "Diagnosing synthetic-data issues" section — how to confirm the indices exist, how to read the rung classifier output for a demo cluster, how to manually rerun the synthetic generator outside the reseed (for debugging).
- `docs/04_security/`: no change — no new secrets, no new threats.
- `docs/05_quality/testing.md`: add the new E2E spec to the "real-backend Playwright suites" inventory.
- `docs/08_guides/tutorial-first-study.md` Step 11: prose update on the demo's new UBI surfaces (1-2 paragraphs); a dedicated "compare two studies" subsection is deferred to Phase 2.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. This is a single-tenant demo-only change with no production exposure. The synthetic-data disclaimer chips ship in the same PR as the seed wiring.
- **Migration / backfill expectations:** none. No DB schema changes.
- **Operational readiness gates:** the integration test gating in CI (FR-11) replaces any manual operator checklist. After merge, the next `make seed-demo` or home-button click validates the change end-to-end.
- **Release gate:** all AC-1..AC-10 pass in CI; `pr.yml` green (currently with `SKIP_HEAVY_CI=true`, so local `make test` + cross-model review act as the heavy-job substitute per `state.md`); Gemini Code Assist comments adjudicated.

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories (filled in by impl-plan-gen) | Test files / suites | Docs to update |
|---|---|---|---|---|
| FR-1 (canonical mapping) | AC-3 (det.) indirectly | TBD | `unit/services/test_demo_ubi_seed.py` (round-trip) | `samples/ubi_index_mappings.json` (new) |
| FR-2 (synthetic generator) | AC-3, AC-5 | TBD | `unit/domain/test_synthetic_ubi.py` | — |
| FR-3 (engine-write helper) | AC-1, AC-10 | TBD | `unit/services/test_demo_ubi_seed.py`, `integration/services/test_demo_seeding_ubi_fast.py` + `_full.py` | — |
| FR-4 (reseed wiring) | AC-1, AC-9 | TBD | `integration/services/test_demo_seeding_ubi_full.py` | `docs/03_runbooks/ubi-judgment-generation.md` |
| FR-5 (CLI parity) | AC-7 | TBD | `integration/scripts/test_seed_meaningful_demos_ubi.py` (heavy lane) | — |
| FR-6 (cleanup) | AC-10 | TBD | `integration/services/test_demo_seeding_ubi_full.py` | — |
| FR-7 (disclaimer chip — 5 surfaces) | AC-4 | TBD | vitest component test (per surface); `e2e/specs/demo-ubi.spec.ts` | `ui/src/lib/glossary.ts`, `ui/src/lib/demo-data.ts` |
| FR-8 (SCENARIOS keys) | AC-2 | TBD | `unit/scripts/test_scenarios_ubi_config.py` | — |
| FR-9 (dual studies) | AC-1 | TBD | `integration/services/test_demo_seeding_ubi_full.py` | — |
| FR-10 (status sub-steps) | (visual; no AC) | TBD | manual verification + log inspection | — |
| FR-11 (integration test split) | AC-1..AC-10 | TBD | `integration/services/test_demo_seeding_ubi_fast.py` (AC-2 acme), `_full.py` (AC-1, AC-2 all, AC-8, AC-9, AC-10) | — |
| FR-12 (E2E spec) | AC-2, AC-4, AC-5, AC-6 | TBD | `e2e/specs/demo-ubi.spec.ts` | `docs/05_quality/testing.md` |

## 18) Definition of feature done

- [ ] All AC-1..AC-10 pass in CI.
- [ ] Unit + integration + E2E test layers green (contract tests N/A per §14).
- [ ] `docs/01_architecture/mvp2-overview.md` §4 "UBI on-ramp", `docs/03_runbooks/ubi-judgment-generation.md`, `docs/05_quality/testing.md`, `docs/08_guides/tutorial-first-study.md` Step 11 updated.
- [ ] `samples/ubi_index_mappings.json` lands and the existing `ui/tests/e2e/helpers/seed_ubi.ts` is migrated to load it (FR-1 round-trip test green).
- [ ] `phase2_idea.md` created in this folder before merge (per spec finalization Step 10).
- [ ] Gemini Code Assist findings on the PR adjudicated.
- [ ] GPT-5.5 final review pass clean.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

All previously open questions are locked in this draft. No questions remain open before plan generation.

### Decision log

- **D-1 (2026-05-29) — Canonical UBI index mapping at `samples/ubi_index_mappings.json`.** Single source-of-truth file consumed by both `ui/tests/e2e/helpers/seed_ubi.ts` and `backend/app/services/demo_ubi_seed.py`. Unit test pins round-trip equality. **Rationale:** duplicate-source-of-truth between TS and Python would drift; the existing e2e helper already inlines the mapping shape and a follow-on test file gives us the lock for free.
- **D-2 (2026-05-29) — Per-scenario UBI rung assignments locked.** acme=rung_3, corp=rung_1 (sparse path), jobs=rung_2 (mid/hybrid path), news=rung_0 (engine-neutral nudge on OS), rich-acme=rung_0 (LLM-only baseline preserved). **Rationale:** exercises every rung-conditional UX surface in the demo; keeps the rich scenario as a high-volume Optuna study baseline.
- **D-3 (2026-05-29) — Dual studies per UBI scenario with identical Optuna config (seed=42, max_trials=12, parallelism=2, sampler=tpe), only judgment-list source differs.** **Rationale:** apples-to-apples comparison makes the digest/best-config delta meaningful; reuses `_seed_real_study_for_scenario` unchanged.
- **D-4 (2026-05-29; revised after GPT-5.5 cycle 2) — Synthetic-data disclosure via `isDemoSyntheticUbiClusterName(...)`-gated chips on five surfaces** (GenerateJudgmentsDialog, JudgmentListHeader, Cluster detail, Study detail, DemoDataBanner). Chip text `"Synthetic demo data"`; tooltip per glossary key `ubi_synthetic_demo_data`. The gate is `isDemoSyntheticUbiClusterName(name)` (three-slug allowlist matching `DEMO_UBI_SCENARIO_ALLOWLIST`), NOT the broader `isDemoClusterName(name)` — `news-search-staging` is a demo cluster but has no synthetic UBI, so showing the chip there would be incorrect. Real operator clusters never see the chip. **Rationale:** piggybacks on the existing demo-aware mechanism — no new column, no new migration, no new persisted state. The chip is small enough not to disrupt the main flow but always visible without scrolling. The cycle-1 form said "three surfaces gated by isDemoClusterName"; cycle-2 review caught that (a) the cluster detail + study detail surfaces also need disclosure (operator could see a rung_3 badge or a UBI-graded study and infer real traffic), and (b) gating on the four-slug demo set would falsely flag `news-search-staging`.
- **D-5 (2026-05-29) — Synthetic generator split across `backend/app/domain/demo/synthetic_ubi.py` (pure) and `backend/app/services/demo_ubi_seed.py` (engine-write).** Both consumed by `demo_seeding.py` and the CLI. **Rationale:** domain/service split matches the repo's pure-vs-I/O convention (Absolute Rule + CLAUDE.md conventions); unit tests pin the generator without httpx fixtures.
- **D-6 (2026-05-29) — Cleanup adds `ubi_queries` + `ubi_events` to `DEMO_ES_INDICES`; per-scenario writes are additive (not delete-then-create).** **Rationale:** three UBI-enabled scenarios share the indices with different `application=<target>` tags; the e2e helper's delete-then-create posture (single tenant per test) doesn't apply here.
- **D-7 (2026-05-29) — CLI `scripts/seed_meaningful_demos.py:seed_scenario` invokes the same modules in the equivalent flow positions.** **Rationale:** `bug_demo_reseed_fake_metric_regression` policy: CLI and home button MUST produce byte-equivalent demo state.
- **D-8 (2026-05-29) — `mapping_strategy="reject"` for the UBI dispatch in the reseed.** The synthetic generator emits one UBI `query_id` per scenario query; duplicates would be a generator bug, not data we want to silently de-dupe. **Note:** the wire allowlist is `reject | first_match | most_recent` — the value `"exact"` mentioned in the idea draft does not exist in the backend Literal (`backend/app/api/v1/schemas.py:864`). **Rationale:** documented at the dispatch call site so the assumption is auditable.
- **D-9 (2026-05-29; revised after GPT-5.5 cycle 1) — Per-rung event totals decoupled from decay distribution.** rung_3: 640 events (560 impressions + 40 clicks + 40 dwells; 28% headroom above the 500 floor). rung_2: 240 events (140% headroom above 100; 52% below 500). rung_1: 50 events (50% below the 100 ceiling). All well below `ES_MAX_RESULT_WINDOW=10000`. Decay shapes per-rank distribution; rung target shapes total count. **Rationale:** GPT-5.5 review cycle 1 caught that applying decay to a fixed `impressions_per_pair` gave rung_3 only ~275 impressions — below the 500 floor. Decoupling makes the rung classification deterministic and unit-testable; the fast-lane integration test (FR-11) cross-checks against the real `classify_rung`.
- **D-10 (2026-05-29; revised after GPT-5.5 cycle 2) — Position-bias decay provides normalized weights only; per-rank impressions are allocated from the rung's fixed `impressions_total` via a Hamilton (largest-remainder) allocator so the per-rank sum equals `impressions_total` exactly.** `decay=0.6`. **Rationale:** the cycle-1 form `impressions_at_rank_N = round(base × decay^(N-1))` left the per-scenario total below the rung floor; the cycle-2 form `imp_at_rank_n = round(impressions_total × weights[n] / sum(weights))` was off-by-1 due to independent rounding (e.g., 243+146+87+52+31=559 ≠ 560). Hamilton allocation is the standard fix — distribute remainders by largest fractional part. Unit test pins the exact-sum invariant for every (rung, num_docs) pair.
- **D-11 (2026-05-29) — Click probability per rating: 0→0%, 1→20%, 2→50%, 3→80%.** Makes the derived UBI judgments correlate (imperfectly) with the LLM ground truth. **Rationale:** if clicks were random, the value-delta card would show pure noise and the demo would have zero educational value.
- **D-12 (2026-05-29) — Rich ESCI scenario stays LLM-only (no UBI).** **Rationale:** preserves the existing "high-volume real Optuna study" comparison baseline; promotion to UBI is explicitly a Phase 2 candidate per the idea.
- **D-13 (2026-05-29) — Dual studies named with `(LLM)` / `(UBI)` suffixes.** Existing `study_name` is suffixed in step 3 (rename) of the reseed. **Rationale:** disambiguates the pair on the studies dashboard and in the tutorial copy; reuses the existing rename step.
