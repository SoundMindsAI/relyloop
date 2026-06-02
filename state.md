# RelyLoop — Active State

> Read this first. A one-page snapshot: current focus, the last few merges, what's in flight, what's queued, and where the project sits in the MVP1 → MVP2 → MVP3 → GA roadmap. **Historical feature-merge narrative + chained execution context lives in [`state_history.md`](state_history.md)** — new merge entries land there, not here (per `chore_state_md_size_compression`, 2026-05-29). Keep this file loadable in a single `Read` call.

**Last updated:** 2026-06-02 (`chore_template_library_expansion` PR #416 `24568c8e` merged — 6 runnable query templates + 3 per-engine tunable-params cheatsheets + FR-7 client-side template summaries. No source under `backend/app/`, no migration.)

## Where the roadmap sits

MVP1 (v0.1) **shipped** — all six differentiators live (Bayesian/TPE optimizer, Git-PR apply path, conversational agent, ES + OpenSearch adapters, LLM judgments, local-first stack). The release matrix was compressed to four stops on 2026-05-27 — MVP1 → MVP2 (Three-Engine + Real Signals: Solr adapter + UBI judgments) → MVP3 (Observable) → GA v1 (hardening). Multi-tenant + multi-LLM + multi-Git + LTR + Path B are backlog. Canonical matrix: [`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md); full reshuffle rationale archived in [`state_history.md`](state_history.md).

## CI note — full suite active

**Heavy CI is ON.** `SKIP_HEAVY_CI` was deleted 2026-05-31 — the full `pr.yml` suite (backend lint/typecheck/tests/coverage, frontend, smoke, both `docker buildx`) runs on every PR again. The earlier ~3-day skip (2026-05-29, PR #307) was a private-repo GHA-budget measure; it no longer applies now that the repo is **public** — standard GitHub-hosted runners (`ubuntu-latest`/`ubuntu-24.04`, all jobs) are unlimited-free on public repos. The `if:` kill-switch stays in `pr.yml` as documented infra; re-enable only with a fresh budget reason by setting `SKIP_HEAVY_CI=true`.

## Current branch / execution context

- **Branch:** `main` (PR #416 `chore_template_library_expansion` just merged, `24568c8e`). All `pr.yml` checks green except `smoke` (cancelled at the 25-min cap — the known, deferred `infra_smoke_reseed_runtime_budget` issue, unrelated to this content/docs PR; merged on the D-6 fast lane).
- **Active feature:** _None in flight._ `chore_template_library_expansion` shipped 2026-06-02 (PR #416). `infra_solr_smoke_stability` shipped 2026-06-02 (PR #383); Phase 1 sibling `infra_solr_ci_readiness` shipped 2026-06-01 (PR #367). The remaining `smoke` redness is the Playwright reseed runtime budget (captured as [`infra_smoke_reseed_runtime_budget`](docs/00_overview/planned_features/02_mvp2/infra_smoke_reseed_runtime_budget/idea.md) — P1). Next: pull from the MVP2 Idea/Plan backlog (run `/pipeline status`).
- **Alembic head:** `0022_solr_engine_auth_check` (added by `infra_adapter_solr` Story A6 — extends `clusters.engine_type` + `clusters.auth_kind` CHECK constraints for Solr).
- **Python:** 3.13. **Frontend stack:** Next 16 (App Router + Turbopack), React 19, Tailwind 4 (CSS-first), Vitest 4, ESLint 9 (flat), TypeScript 6, Playwright (chromium, single worker) for E2E.
- **Coverage gates:** backend 80% (`fail_under` in pyproject), UI vitest + tsc + ESLint + Next build, plus a full-stack smoke E2E job. Live pass counts: see the latest `pr.yml` run (the historical per-feature counts moved to `state_history.md`).

## Last 5 merges (newest first)

Detail + reasoning for each is in [`state_history.md`](state_history.md).

- **2026-06-02** — `chore_template_library_expansion` (PR #416, squash-merged `24568c8e`). Ships a curated **runnable query-template library** + per-engine **tunable-params cheatsheets**: 6 templates (4 engine-agnostic ES/OS — `multi_match_basic`, `function_score_decay`, `bool_boosted`, `rescore_phrase`; 2 Solr — `edismax_basic`, `boost_decay`), each with a co-located `.search_space.json` starter (cardinality < 10⁶, test-enforced) + a copy-paste `curl` registration block; three `docs/06_vendor_docs/*-tunable-params.md` cheatsheets covering the 8 unified params + per-engine knobs with kNN/hybrid reference snippets (ES native `rrf` retriever vs OpenSearch normalization-processor — test-asserted not interchangeable); vendor README index rows + tutorial "Where to go next". FR-7 **shipped** client-side: `ui/src/lib/template-descriptions.ts` (recommended-name→summary map + `cheatsheetUrlFor` resolver) + additive `learnMoreHref` prop on `InfoTooltip` (Popover-mode for a11y when set) + Step-3 modal summary wiring (graceful miss on unknown name). **No source under `backend/app/`, no migration** (head stays `0022`); 4 demo templates byte-identical (AC-3). 8 stories / 3 epics; +34 backend tests (render + invariants + cheatsheet doc-consistency) + 7 frontend vitest. Cross-model: Gemini (4 findings — 3 accepted incl. Popover a11y, 1 rejected as sibling-convention) + GPT-5.5 final review converged after 5 cycles (6 accepted-and-fixed across cycles 1–4: cheatsheet-heading test, FR-7 modal test, cardinality<10⁶, bool filter clause, JSON-safe `query_text` via `tojson`, Solr `boost_weight` magnitude via `product()`; 0 in cycle 5). `smoke` cancelled at the cap (deferred reseed-runtime issue); merged on the D-6 fast lane. Captured `bug_studies_detail_vitest_intermittent_timeout`.
- **2026-06-02** — `infra_solr_smoke_stability` (PR #383, squash-merged `d32b9714`, smoke RED on merge per D-6 fast-lane posture). Smoke-job half of the Solr CI debt (sibling of `infra_solr_ci_readiness` Phase 1 / PR #367). Diagnostics fold-in (FR-1): smoke-test job's failure-diagnostics step now captures `solr` + `opensearch` Compose logs + per-container `docker inspect` exit-state (exit/oom/error/health/started/finished). Lever 1 heap-cap (FR-2): `SOLR_HEAP_SIZE: "256m"` step-env on `make up` + `COMPOSE_PROJECT_NAME: "relyloop"` at job-level env. Plus new runbook [`docs/03_runbooks/smoke-solr-stability.md`](docs/03_runbooks/smoke-solr-stability.md) with evidence-mapped lever cascade + CLAUDE.md Key Runbooks row. **The interesting story is the inline-fix iteration during CI watch:** the spec's locked lever cascade (heap/start_period/smoke-tolerance) all assumed JVM crash modes; the diagnostics fold-in immediately surfaced THREE failure modes the cascade never anticipated — (1) Solr container exited (1) in 542ms with filesystem permissions error (`Cannot write to /var/solr as 8983:8983`); (2) Playwright `beforeAll` 30s timeout (Solr unblocked → reseed seeds Solr scenario → longer wall-clock); (3) job-level `timeout-minutes: 15` cap. All three fixed inline per the new fix-inline-by-default rule (canonical "implement-over-defer" example). The fourth iteration timed out the new 25-min cap — Playwright demo-ubi reseed exceeds any reasonable per-PR smoke budget. Captured as the follow-up [`infra_smoke_reseed_runtime_budget`](docs/00_overview/planned_features/02_mvp2/infra_smoke_reseed_runtime_budget/idea.md) (linked from PR body before merge per D-6 forcing function — three candidate fixes documented with Option A as default). 6 commits + 1 follow-up commit. No migration (head stays `0022`). Cross-model: spec GPT-5.5 3 cycles (15 → 16 → 10 findings, all accepted); plan GPT-5.5 3 cycles (13 → 10 → 6, all accepted).
- **2026-06-01** — `infra_solr_ci_readiness` Phase 1 (PR #367, squash-merged `214cdfcd`). Makes the demo reseed **engine-tolerant** so the `pr.yml` backend job is green again without a Solr service container: the orchestrator + CLI probe each engine before dispatch (`is_engine_reachable` / `snapshot_engine_reachability`, total never-raises probe, slug-keyed, covers the 5 `SCENARIOS` + the separately-seeded rich ESCI scenario) and **skip** unreachable engines instead of `ConnectError`-ing the whole reseed. Partial completion → `status="complete"` + additive `ReseedStatusResponse.scenarios_skipped` (the `ReseedStatusLiteral` enum is unchanged) + one summary WARN; all-engines-unreachable → typed `AllEnginesUnreachableError` → `status="failed"` + stable `failed_reason="all_engines_unreachable"` token + skip list (avoids the Arq `keep_result` retry wedge). The heavy-lane `test_demo_seeding_ubi_full` now computes counts dynamically (8/8 with Solr absent, 10/10 with Solr). Dashboard reseed dialog shows a "partial completion — N scenario(s) skipped" hint → new runbook. No migration (head stays `0022`). 6 stories / 1 epic; 2095 unit + 327 contract + 998 UI vitest. Cross-model: GPT-5.5 phase-gate (5 findings — incl. the all-unreachable path not being total until the pre-loop wipes were gated) + Gemini (3, probe-caching) + GPT-5.5 final (2 fixed, 1 rejected as a stdlib-vs-structlog mis-read) — all adjudicated, CI-verified. **Phase 2 (smoke Solr stability) deferred** to `phase2_idea.md`; the `smoke` job stays red. Captured `chore_demo_reseed_partial_completion_fast_test`.
- **2026-06-01** — MVP2 backlog batch (PR #364). Fixed the **P1 caplog-isolation bug** (`bug_backend_suite_nondeterministic_caplog_isolation`): root cause was `configure_logging()` replacing the structlog processors *list instance* on every call (not `pytest-randomly`, which isn't installed) — loggers cached against the stale instance went blind to `capture_logs()`; fixed by mutating the list in place + fixing a second polluter fixture in `test_position_bias_prior.py`; regression test added. Also fixed 3 other pre-existing bugs to green the suite: `bug_contract_allowlists_outdated_after_mvp2_features` (3 stale `'solr'`/endpoint allowlists), the `test_judgment_generate` `click:0` source-breakdown drift, and the `test_migration_0021` downgrade target (was `-1` assuming 0021 was head; head is now 0022). Landed **6 cross-model-reviewed spec/plan pairs** (idea-preflight → spec-gen → impl-plan-gen, each GPT-5.5-reviewed) for `feat_apply_path_normalizer_declaration` (design-ahead), `feat_overnight_studies_summary_card`, `feat_query_normalizer_typed_pipeline` (design-ahead), `infra_generated_artifact_freshness_gate`, `chore_arq_pool_aclose_deprecation`, `chore_cluster_detail_rung_badge`. 3168 backend tests pass; merged over 2 pre-existing Solr-CI reds (`infra_solr_ci_readiness`). Gemini: 1 finding (defensive fixture guard) accepted.
_(older entries — full narrative in [`state_history.md`](state_history.md): `feat_study_convergence_indicator` PR #352, `feat_demo_reseed_solr_and_steplog` PR #348, `feat_overnight_autopilot` PR #343, `infra_adapter_solr` PR #336, …)_

## In flight

- _None._ `infra_solr_smoke_stability` (PR #383) merged 2026-06-02. The remaining smoke debt is the Playwright reseed runtime budget, captured as P1 Idea-stage folder `02_mvp2/infra_smoke_reseed_runtime_budget/` (three candidate fixes documented; Option A — skip demo-ubi on smoke — recommended as the inline-cheap default).
- **Plan-stage, `/impl-execute`-ready (no gates):** the 4 remaining PR #413 (2026-06-02) spec/plan pairs in `02_mvp2/` (`chore_template_library_expansion` shipped via PR #416): `chore_studies_post_arq_spy_fixture`, `bug_judgment_header_omits_click_bucket`, `bug_baseline_phase_test_isolation`, `chore_ubi_reader_search_after_pagination`. Plus the 6 pairs from PR #364 — of which two are **design-ahead** (`feat_apply_path_normalizer_declaration` + `feat_query_normalizer_typed_pipeline`, both gated on `feat_query_normalization_tuning` Phase 1 merging — do not `/impl-execute` until then); the other four (`feat_overnight_studies_summary_card`, `infra_generated_artifact_freshness_gate`, `chore_arq_pool_aclose_deprecation`, `chore_cluster_detail_rung_badge`) are ungated.

## Queued (priority-ordered by dashboard / dep graph)

**Source of truth:** [`docs/00_overview/DASHBOARD.md`](docs/00_overview/DASHBOARD.md) + [`docs/00_overview/MVP1_DASHBOARD.md`](docs/00_overview/MVP1_DASHBOARD.md) (regenerated by the `mvp1-dashboard-regen` pre-commit hook). Run `/pipeline status` for the live view.

**MVP1 backlog is fully drained** (`01_mvp1/` empty as of PR #310). We're inside **MVP2 / v0.2 — "Three-Engine + Real Signals"**, now **3/3 scoped items done** (`feat_contextual_help_mvp2`, `feat_demo_ubi_study_comparison`, `infra_adapter_solr` — the Solr headliner shipped via PR #336 on 2026-05-31, completing the three-engine reach). The remaining MVP2 work is all Idea-stage; the `02_mvp2/` bucket holds 17 folders (run `ls docs/00_overview/planned_features/02_mvp2/` for the live list):

- **Headliners (idea-stage):** `feat_fts_rank_ordering`, `feat_query_normalization_tuning`, `feat_study_convergence_indicator`, `feat_ubi_llm_study_comparison` (side-by-side UBI-vs-LLM study comparison view + deferred cluster-detail rung badge, P2 — Phase 2 split out of `feat_demo_ubi_study_comparison`), plus the Phase-2/3 split-outs from the 2026-05-31 planning batch (`feat_overnight_studies_summary_card`, `feat_query_normalizer_typed_pipeline`, `feat_apply_path_normalizer_declaration`). `feat_overnight_autopilot` shipped (PR #343, 2026-05-31).
- **Bugs held for MVP2:** `bug_chat_long_conversation_truncation` (investigation `bug_fix.md` exists; pullable forward but deferred for scope discipline — latency-of-impact is zero today), `bug_webhook_concurrent_merge_race_timing_sensitive`, `bug_seed_meaningful_demos_silent_bulk_errors`.
- **Chores/infra:** `chore_auto_followup_parent_advisory_lock`, `chore_demo_seeding_integration_tests_rewrite`, `chore_studies_post_arq_spy_fixture`, `chore_template_library_expansion`, `chore_ubi_reader_search_after_pagination` (P2, search_after for >10k-event clusters — spun out of `feat_ubi_judgments`), `chore_ubi_hybrid_template_render` (P3, vestigial-template contract cleanup — spun out of `feat_ubi_judgments`), `infra_arq_subprocess_test`.

**Other buckets:** `03_mvp3/` (Observable — includes `infra_optuna_orphan_reaper`, deferred from MVP1 per spec §11 operational tolerance), `04_ga/`, `99_backlog/` (4 defer-until-incident items), `00_unsure/` (`bug_seed_meaningful_demos_silent_bulk_errors`).

## Known debt / fragility

- ~~**Solr is not CI-ready (P1) — `pr.yml` backend + smoke are red on every branch.**~~ — **Backend half RESOLVED** (`infra_solr_ci_readiness` Phase 1, PR #367, 2026-06-01). **Smoke half partially resolved** (`infra_solr_smoke_stability`, PR #383, 2026-06-02): the actual Solr crash mode was filesystem permissions (Solr container UID 8983 couldn't write to root-owned `./data/solr/`) — fixed inline as Lever 0 (`mkdir + chown` before `make up`). Diagnostics fold-in + Lever 1 heap-cap + COMPOSE_PROJECT_NAME pin all shipped. Remaining smoke debt is the **Playwright `demo-ubi.spec.ts` `beforeAll` reseed runtime** — designed when Solr was crashing in 542ms (reseed only did ES+OpenSearch); now Solr boots and the reseed runs the full 6-scenario set, exceeding the 25-min smoke-job cap. Tracked as [`infra_smoke_reseed_runtime_budget`](docs/00_overview/planned_features/02_mvp2/infra_smoke_reseed_runtime_budget/idea.md) (P1, three candidate fixes — Option A "skip demo-ubi on smoke" recommended as the inline-cheap default). Until it ships, `smoke` stays red on every PR; merge on the fast lane per D-6.

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
