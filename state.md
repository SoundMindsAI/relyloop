# RelyLoop — Active State

> Read this first. A one-page snapshot: current focus, the last few merges, what's in flight, what's queued, and where the project sits in the MVP1 → MVP2 → MVP3 → GA roadmap. **Historical feature-merge narrative + chained execution context lives in [`state_history.md`](state_history.md)** — new merge entries land there, not here (per `chore_state_md_size_compression`, 2026-05-29). Keep this file loadable in a single `Read` call.

**Last updated:** 2026-05-31 (`feat_demo_reseed_solr_and_steplog` merged — completes the Solr demo-seed in the reseed (deferred A13) + fixes a UBI-on-Solr product bug + adds a reseed step-log; PR #348 squash-merged `66323aba`. `make seed-demo` now completes 6/6 incl. the Solr scenario.)

## Where the roadmap sits

MVP1 (v0.1) **shipped** — all six differentiators live (Bayesian/TPE optimizer, Git-PR apply path, conversational agent, ES + OpenSearch adapters, LLM judgments, local-first stack). The release matrix was compressed to four stops on 2026-05-27 — MVP1 → MVP2 (Three-Engine + Real Signals: Solr adapter + UBI judgments) → MVP3 (Observable) → GA v1 (hardening). Multi-tenant + multi-LLM + multi-Git + LTR + Path B are backlog. Canonical matrix: [`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md); full reshuffle rationale archived in [`state_history.md`](state_history.md).

## ⚠️ Active CI note — heavy jobs temporarily skipped

**`SKIP_HEAVY_CI=true` repo variable is set (2026-05-29, ~3-day GitHub Actions budget measure; PR #307).** The 5 `pr.yml` jobs over 1 min — `backend` (lint+typecheck+tests+coverage), `frontend`, `smoke`, both `docker buildx` — are **skipped** on every PR. Only the 4 sub-minute checks run (backend fast-lane unit tests, DCO, secrets guard, gitleaks). **While this is active, lean on local `make test` / `pnpm test` + review before merging — CI is not validating the full suite, coverage gate, smoke, or builds.** Scheduled to auto-restore on ~2026-06-01 (routine deletes the variable); restore manually anytime with `gh variable delete SKIP_HEAVY_CI`. The `if:` kill-switch stays in `pr.yml` as documented infra.

## Current branch / execution context

- **Branch:** `main` (clean). `feat_demo_reseed_solr_and_steplog` merged via PR #348 (squash, merge commit `66323aba`); finalization on `docs/finalize-demo-reseed-solr` (this branch).
- **Active feature:** _None in flight._ `feat_demo_reseed_solr_and_steplog` shipped — the async demo reseed now seeds the Solr scenario end-to-end (configset+collection create, engine-aware synthetic-UBI write **and** read, search-space cardinality fix), fixing a real UBI-on-Solr product bug (UBI judgment generation was ES-DSL-only → broke on Solr for all operators); plus a reseed step-history log surface. Verified by a live `make seed-demo` → 6/6. Next: pull from the MVP2 Idea backlog (run `/pipeline status`).
- **Alembic head:** `0022_solr_engine_auth_check` (added by `infra_adapter_solr` Story A6 — extends `clusters.engine_type` + `clusters.auth_kind` CHECK constraints for Solr).
- **Python:** 3.13. **Frontend stack:** Next 16 (App Router + Turbopack), React 19, Tailwind 4 (CSS-first), Vitest 4, ESLint 9 (flat), TypeScript 6, Playwright (chromium, single worker) for E2E.
- **Coverage gates:** backend 80% (`fail_under` in pyproject), UI vitest + tsc + ESLint + Next build, plus a full-stack smoke E2E job. Live pass counts: see the latest `pr.yml` run (the historical per-feature counts moved to `state_history.md`).

## Last 5 merges (newest first)

Detail + reasoning for each is in [`state_history.md`](state_history.md).

- **2026-05-31** — `feat_demo_reseed_solr_and_steplog` (PR #348, squash-merged `66323aba`). Completes the deferred `infra_adapter_solr` Story A13 — the async home-button demo reseed (`make seed-demo`) now seeds the **Solr** scenario (`acme-kb-docs-solr`) end-to-end, where before it crashed. Fixed layer by layer (each verified by the live reseed getting further): Solr host-URL→Compose-DNS mapping (`8983`); the dispatcher now creates the Solr collection from its configset + bulk-indexes (reusing `seed_solr_products`) instead of the ES `index_mapping` PUT; engine-aware **synthetic-UBI write** (`ubi_queries`/`ubi_events` Solr collections + Solr `/update`, per-engine ensure gate); study **search-space cardinality** (Solr scenario tunes 2 boosts, `estimate_cardinality` floats=100 → ≤3-float cap). **Surfaced + fixed a real product bug:** the UBI **read** path (`ubi_readiness`, `UbiReader`) built Elasticsearch query DSL → `UBI judgment generation was broken on Solr for every operator` (contradicting the "works everywhere from day one" claim); now builds Solr `q`/`fq`/`{!terms}`/`rows`/`fl` when `adapter.engine_type=="solr"`. Plus a **reseed step-history log** (worker accumulates `steps[]` → status endpoint → scrolling UI panel). **Verified by a live `make seed-demo` completing 6/6** (10 studies, 10 proposals). 8 commits; backend 2012 unit + frontend 983 vitest. Gemini: 3 findings accepted+fixed (`{!terms}` query_id vs maxBooleanClauses — verified live; collision-safe synthetic ids; scroll-on-reopen dep). Final GPT-5.5 review clean. Captured `bug_reseed_failure_blocks_retry_arq_singleton_dedup` (a failed reseed deduped retries for ~1h via the Arq singleton result).
- **2026-05-31** — `feat_overnight_autopilot` (PR #343, squash-merged `fe146950`). MVP2 ergonomics feature surfacing the shipped auto-followup chaining engine as a first-class "set it and wake up to results" path — **read-side + UI only, the engine stayed untouched**. New read-only `GET /api/v1/studies/{id}/chain` (pure-domain `chain_summary.py`: stop-reason matrix, universal cumulative-lift, best-link selection — reuses `compute_first_decile_max`/`_direction_normalized_lift` from `auto_followup.py`; + a bounded `parent_study_id` traversal repo helper with a 10-hop upward cap + cycle guard, `LIMIT 1` downward walk, `DISTINCT ON` newest-non-rejected proposal lookup). Frontend: create-study wizard relabel to "🌙 Run overnight (compound automatically)" + Deep-preset discoverability hint + `overnight_autopilot` glossary key; `AutoFollowupChainPanel` rolled-up summary (ordered links + deltas, cumulative lift, 3-branch best-config, stop-reason phrases) via a new `useStudyChain` TanStack hook (focus/cancel/transition refetch + 120s grace poll). Tutorial Step 12 + arch-doc notes. No migration (Alembic head stays `0022`). 7 stories / 4 epics. Tests: 30 unit + 31 chain integration/contract + frontend vitest (panel 13/wizard/glossary) + 1 real-backend E2E. Cross-model: GPT-5.5 Epic 1 (1 Low accepted) + Epics 2+3 clean + final (1 Medium rejected — SQLite-portability moot, Postgres-only); Gemini (1 High accepted — zero-row hydration guard `9b1d894f`). Phase 2 ("ran while away" card) deferred to `feat_overnight_studies_summary_card`. 4 tangential idea files captured (`infra_generated_artifact_freshness_gate`, `bug_judgment_header_omits_click_bucket`, `chore_arq_pool_aclose_deprecation`, `bug_e2e_teardown_chain_node_delete_500`).
- **2026-05-31** — `infra_adapter_solr` (PR #336 squash-merged `60aec9af` + demo-seed fix #337). MVP2 three-engine headliner: a single `SolrAdapter` implements the full `SearchAdapter` Protocol against Apache Solr 9.x/10.x (SolrCloud + standalone), pivoting on a construction-time capability probe. All 13 stories (A1–A13): adapter skeleton + probe, `edismax`/`dismax`/`lucene` render with unified-param pivots, parallel `/select` search_batch, get_schema/list_targets, explain (Lucene-escaped), get_document/list_documents (RealTime Get + cursorMark), LTR rescore (`rq={!ltr}`) + `LTR_MODEL_NOT_FOUND`, migration 0022 (engine_type + auth_kind CHECK extension) + `registry.py` allowlist relocation, `POST /clusters/{id}/reprobe` + `POST /clusters/test-connection`, Compose `solr:10.0` service + configsets + `/healthz` subsystems.solr, frontend wire literals + per-engine auth filtering + 3-engine `<EngineBadge>` + test-connection button, Guide 01 + runbook + tutorial Path C, and a 5th `acme-kb-docs-solr` demo scenario. **Live-Solr rework correction** (folded into the squash): local Solr runs security-DISABLED (parity with ES/OpenSearch), `bootstrap-security.sh` deleted, LTR via `SOLR_MODULES=ltr`; stock Solr ships **no** `solr.UBIComponent`, so UBI on Solr is read-path-only (demo synthesizes events, probe reports `ubi_component_present=false`). Cross-model review: GPT-5.5 F1/F2/F3 + 6 Gemini findings adjudicated. Post-pipeline followups tracked in `00_unsure/chore_solr_post_pipeline_followups` + `chore_solr_cred_backfill_needs_api_restart`.
- **2026-05-30** — `chore_oss_public_launch_punchlist` (PRs #322, #330, + history-audit PR). Closed the 3-capability OSS public-launch gate. (1) SPDX headers via FSFE REUSE on every source file + `REUSE.toml` + `reuse-lint` pre-commit/CI gates (1477/1477 compliant). (2) Dependency license inventory (`scripts/gen_license_inventory.py` → `docs/04_security/license-inventory.md`, 786 deps / 0 violations, deterministic from locked closure) + `license-inventory` CI gate; 9 non-permissive licenses all adjudicated Accept (no GPL/AGPL ships). (3) Full-history `gitleaks` + manual sweep — 1 gitleaks finding + a few pickaxe hits, all confirmed false positives — captured in a repeatable runbook (`docs/03_runbooks/oss-history-audit.md`). Repo cleared for the visibility flip (operator action). NOTE: `SKIP_HEAVY_CI=true` during this work, so `license-headers`/`license-inventory` jobs were verified locally, not in CI.
- **2026-05-29** — `feat_ubi_judgments` (PR #317, squash-merged). MVP2 second feature: engine-neutral User Behavior Insights judgment generation, shipped end-to-end (all 13 stories incl. E2E + DB-backed integration tests + operator docs — none deferred). Migration 0021 (judgment_lists.generation_params JSONB) → domain/ubi/ pure-domain library (FeatureVec, async SignalsConverter Protocol + 3 impls, position-bias prior) → UbiReader (engine-neutral two-index scan + client-side join, no new adapter method) → ubi_readiness classifier (rung_0..rung_3, 60s Redis cache) → start_ubi_judgment_generation dispatcher (refactor extracts 5 shared helpers; LLM dispatcher parity preserved by all 12 existing tests) → 5 new wire Literals + _SourceBreakdown three-term evolution (FR-10) → GET /clusters/{id}/ubi-readiness + POST /judgments/generate-from-ubi endpoints → generate_judgments_from_ubi Arq worker with mapping_strategy + hybrid LLM-fill callback → 21st agent tool + orchestrator prompt update → frontend method picker dialog + on-ramp nudge + sparse-data card + value-delta + ambiguous-skip recovery cards → operator runbook + 3 FAQ entries + data-model patches → 4 Playwright E2E specs (rung_0/rung_3/hybrid/source-filter) green against the live ES-backed stack. **Real-engine E2E caught a production bug**: UbiReader requested `size=50000 > ES index.max_result_window (10000)` → "all shards failed" swallowed by the adapter → spurious `UBI_INSUFFICIENT_DATA` on dense clusters; fixed by clamping both index scans to `ES_MAX_RESULT_WINDOW=10000` + regression guard. Cross-model review: 6 Gemini findings + 6 GPT-5.5 findings all adjudicated (fixed or documented as working-as-designed). Remaining follow-ups are pure deferrals, not gaps: `chore_ubi_reader_search_after_pagination` (P2, >10k-event clusters), `chore_ubi_hybrid_template_render` (P3, vestigial-template contract cleanup — current behavior correct per FR-2), `feat_demo_ubi_study_comparison` (P1, side-by-side UBI-vs-LLM demo study).
## In flight

- _None._ `feat_demo_reseed_solr_and_steplog` (PR #348) merged 2026-05-31; finalization on `docs/finalize-demo-reseed-solr` (this branch).

## Queued (priority-ordered by dashboard / dep graph)

**Source of truth:** [`docs/00_overview/DASHBOARD.md`](docs/00_overview/DASHBOARD.md) + [`docs/00_overview/MVP1_DASHBOARD.md`](docs/00_overview/MVP1_DASHBOARD.md) (regenerated by the `mvp1-dashboard-regen` pre-commit hook). Run `/pipeline status` for the live view.

**MVP1 backlog is fully drained** (`01_mvp1/` empty as of PR #310). We're inside **MVP2 / v0.2 — "Three-Engine + Real Signals"**, now **3/3 scoped items done** (`feat_contextual_help_mvp2`, `feat_demo_ubi_study_comparison`, `infra_adapter_solr` — the Solr headliner shipped via PR #336 on 2026-05-31, completing the three-engine reach). The remaining MVP2 work is all Idea-stage; the `02_mvp2/` bucket holds 17 folders (run `ls docs/00_overview/planned_features/02_mvp2/` for the live list):

- **Headliners (idea-stage):** `feat_fts_rank_ordering`, `feat_query_normalization_tuning`, `feat_study_convergence_indicator`, `feat_ubi_llm_study_comparison` (side-by-side UBI-vs-LLM study comparison view + deferred cluster-detail rung badge, P2 — Phase 2 split out of `feat_demo_ubi_study_comparison`), plus the Phase-2/3 split-outs from the 2026-05-31 planning batch (`feat_overnight_studies_summary_card`, `feat_query_normalizer_typed_pipeline`, `feat_apply_path_normalizer_declaration`). `feat_overnight_autopilot` shipped (PR #343, 2026-05-31).
- **Bugs held for MVP2:** `bug_chat_long_conversation_truncation` (investigation `bug_fix.md` exists; pullable forward but deferred for scope discipline — latency-of-impact is zero today), `bug_webhook_concurrent_merge_race_timing_sensitive`, `bug_seed_meaningful_demos_silent_bulk_errors`.
- **Chores/infra:** `chore_auto_followup_parent_advisory_lock`, `chore_demo_seeding_integration_tests_rewrite`, `chore_studies_post_arq_spy_fixture`, `chore_template_library_expansion`, `chore_ubi_reader_search_after_pagination` (P2, search_after for >10k-event clusters — spun out of `feat_ubi_judgments`), `chore_ubi_hybrid_template_render` (P3, vestigial-template contract cleanup — spun out of `feat_ubi_judgments`), `infra_arq_subprocess_test`.

**Other buckets:** `03_mvp3/` (Observable — includes `infra_optuna_orphan_reaper`, deferred from MVP1 per spec §11 operational tolerance), `04_ga/`, `99_backlog/` (4 defer-until-incident items), `00_unsure/` (`bug_seed_meaningful_demos_silent_bulk_errors`).

## Known debt / fragility

- ~~**`backend/app/eval/qrels_loader.py` is an MVP1 stub.**~~ — **Resolved.** PR #35 replaced the stub with a real `SELECT query_id, doc_id, rating FROM judgments WHERE judgment_list_id = :id`. The legacy `JudgmentsTableMissing` symbol is retained as a no-op compat shim for any imported reference in older tests. Integration tests now seed real `judgments` rows; `run_trial` consumes the loader directly.
- **`infra_optuna_orphan_reaper`** — Phase 2 orchestrator can die between `study.ask()` and the enqueue commit, leaving orphan Optuna RUNNING trials. Operationally tolerated for MVP1 per spec §11 "Operational tolerance"; periodic reaper deferred to MVP3 ([`03_mvp3/infra_optuna_orphan_reaper`](docs/00_overview/planned_features/03_mvp3/infra_optuna_orphan_reaper/idea.md)).
- ~~**CI lacks a `make up` smoke job.**~~ — **Resolved.** `infra_ci_smoke_makeup` shipped 2026-05-13; `pr.yml` now has a full-stack `smoke:` E2E job (see the coverage-gates line above).
- **Tangential bugs captured during the bootstrap:**
  - ~~`bug_env_file_corrupted_during_session`~~ — **Resolved.** Defense-in-depth `.env*` filename CI guard shipped in PR #94 + folder finalized to [`implemented_features/2026_05_13_bug_env_file_corrupted_during_session/`](docs/00_overview/implemented_features/2026_05_13_bug_env_file_corrupted_during_session/). Original local-tooling rename event remains undetermined (user-side investigation open).
  - ~~[`chore_starlette_422_deprecation`]~~ — **Resolved.** Shipped 2026-05-13 ([`implemented_features/2026_05_13_chore_starlette_422_deprecation`](docs/00_overview/implemented_features/2026_05_13_chore_starlette_422_deprecation/)).
- **Manual operator handoffs (per `infra_foundation` §7.5):** `.env` is
  not auto-created (operator opts in via `cp .env.example .env`); OpenAI
  key file is empty by default; GitHub branch protection requires repo-admin
  action after the CI workflow lands.
- **No DB revision guard at API startup** in MVP1 (would crash the dev
  stack on first boot before `make migrate` runs). Activates at MVP2 when
  the API can assume the operator has run migrations once.
- **No remote staging** in MVP1 — every contributor runs the stack locally.
  Remote staging + production install land at MVP3.

## Quick-reference commands

```bash
# Stack lifecycle
make up            # generate secrets if missing, then docker compose up -d
make down          # stop containers (preserve volumes)
make logs          # tail api + worker
make reset         # DESTRUCTIVE: drop volumes + ./data (FORCE=1 to skip prompt)

# Migrations
make migrate                        # alembic upgrade head + init optuna schema
make migrate-create name=<slug>     # new alembic revision

# Tests + quality gates
make test-unit
make test-integration
make test-contract
make lint && make typecheck
make pre-commit                     # run all pre-commit hooks against the repo
```

## Where to look next

- [`architecture.md`](architecture.md) — high-level design + topical doc pointers
- [`CLAUDE.md`](CLAUDE.md) — codebase conventions, absolute rules, MVP1 status
- [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md) — boot, debug, reset
- [`docs/05_quality/testing.md`](docs/05_quality/testing.md) — test layers + coverage gate
