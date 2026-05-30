# RelyLoop — Active State

> Read this first. A one-page snapshot: current focus, the last few merges, what's in flight, what's queued, and where the project sits in the MVP1 → MVP2 → MVP3 → GA roadmap. **Historical feature-merge narrative + chained execution context lives in [`state_history.md`](state_history.md)** — new merge entries land there, not here (per `chore_state_md_size_compression`, 2026-05-29). Keep this file loadable in a single `Read` call.

**Last updated:** 2026-05-30 (OSS public-launch punchlist complete — SPDX headers #322, license inventory #330, git-history audit runbook; repo cleared for the visibility flip pending operator media spot-check + flip).

## Where the roadmap sits

MVP1 (v0.1) **shipped** — all six differentiators live (Bayesian/TPE optimizer, Git-PR apply path, conversational agent, ES + OpenSearch adapters, LLM judgments, local-first stack). The release matrix was compressed to four stops on 2026-05-27 — MVP1 → MVP2 (Three-Engine + Real Signals: Solr adapter + UBI judgments) → MVP3 (Observable) → GA v1 (hardening). Multi-tenant + multi-LLM + multi-Git + LTR + Path B are backlog. Canonical matrix: [`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md); full reshuffle rationale archived in [`state_history.md`](state_history.md).

## ⚠️ Active CI note — heavy jobs temporarily skipped

**`SKIP_HEAVY_CI=true` repo variable is set (2026-05-29, ~3-day GitHub Actions budget measure; PR #307).** The 5 `pr.yml` jobs over 1 min — `backend` (lint+typecheck+tests+coverage), `frontend`, `smoke`, both `docker buildx` — are **skipped** on every PR. Only the 4 sub-minute checks run (backend fast-lane unit tests, DCO, secrets guard, gitleaks). **While this is active, lean on local `make test` / `pnpm test` + review before merging — CI is not validating the full suite, coverage gate, smoke, or builds.** Scheduled to auto-restore on ~2026-06-01 (routine deletes the variable); restore manually anytime with `gh variable delete SKIP_HEAVY_CI`. The `if:` kill-switch stays in `pr.yml` as documented infra.

## Current branch / execution context

- **Branch:** `docs/finalize-demo-ubi-study-comparison` — Phase 1 finalization (folder move + status flips); feature PR #320 squash-merged to `main` 2026-05-30 (merge commit `853a5053`). See `/pipeline status` for the next MVP2 item.
- **Active feature:** none in flight.
- **Alembic head:** `0021_judgment_lists_generation_params` (added by `feat_ubi_judgments` Story 1.1 — JSONB column for UBI worker resume payload).
- **Python:** 3.13. **Frontend stack:** Next 16 (App Router + Turbopack), React 19, Tailwind 4 (CSS-first), Vitest 4, ESLint 9 (flat), TypeScript 6, Playwright (chromium, single worker) for E2E.
- **Coverage gates:** backend 80% (`fail_under` in pyproject), UI vitest + tsc + ESLint + Next build, plus a full-stack smoke E2E job. Live pass counts: see the latest `pr.yml` run (the historical per-feature counts moved to `state_history.md`).

## Last 5 merges (newest first)

Detail + reasoning for each is in [`state_history.md`](state_history.md).

- **2026-05-30** — `chore_oss_public_launch_punchlist` (PRs #322, #330, + history-audit PR). Closed the 3-capability OSS public-launch gate. (1) SPDX headers via FSFE REUSE on every source file + `REUSE.toml` + `reuse-lint` pre-commit/CI gates (1477/1477 compliant). (2) Dependency license inventory (`scripts/gen_license_inventory.py` → `docs/04_security/license-inventory.md`, 786 deps / 0 violations, deterministic from locked closure) + `license-inventory` CI gate; 9 non-permissive licenses all adjudicated Accept (no GPL/AGPL ships). (3) Full-history `gitleaks` + manual sweep — 1 gitleaks finding + a few pickaxe hits, all confirmed false positives — captured in a repeatable runbook (`docs/03_runbooks/oss-history-audit.md`). Repo cleared for the visibility flip (operator action). NOTE: `SKIP_HEAVY_CI=true` during this work, so `license-headers`/`license-inventory` jobs were verified locally, not in CI.
- **2026-05-29** — `feat_ubi_judgments` (PR #317, squash-merged). MVP2 second feature: engine-neutral User Behavior Insights judgment generation, shipped end-to-end (all 13 stories incl. E2E + DB-backed integration tests + operator docs — none deferred). Migration 0021 (judgment_lists.generation_params JSONB) → domain/ubi/ pure-domain library (FeatureVec, async SignalsConverter Protocol + 3 impls, position-bias prior) → UbiReader (engine-neutral two-index scan + client-side join, no new adapter method) → ubi_readiness classifier (rung_0..rung_3, 60s Redis cache) → start_ubi_judgment_generation dispatcher (refactor extracts 5 shared helpers; LLM dispatcher parity preserved by all 12 existing tests) → 5 new wire Literals + _SourceBreakdown three-term evolution (FR-10) → GET /clusters/{id}/ubi-readiness + POST /judgments/generate-from-ubi endpoints → generate_judgments_from_ubi Arq worker with mapping_strategy + hybrid LLM-fill callback → 21st agent tool + orchestrator prompt update → frontend method picker dialog + on-ramp nudge + sparse-data card + value-delta + ambiguous-skip recovery cards → operator runbook + 3 FAQ entries + data-model patches → 4 Playwright E2E specs (rung_0/rung_3/hybrid/source-filter) green against the live ES-backed stack. **Real-engine E2E caught a production bug**: UbiReader requested `size=50000 > ES index.max_result_window (10000)` → "all shards failed" swallowed by the adapter → spurious `UBI_INSUFFICIENT_DATA` on dense clusters; fixed by clamping both index scans to `ES_MAX_RESULT_WINDOW=10000` + regression guard. Cross-model review: 6 Gemini findings + 6 GPT-5.5 findings all adjudicated (fixed or documented as working-as-designed). Remaining follow-ups are pure deferrals, not gaps: `chore_ubi_reader_search_after_pagination` (P2, >10k-event clusters), `chore_ubi_hybrid_template_render` (P3, vestigial-template contract cleanup — current behavior correct per FR-2), `feat_demo_ubi_study_comparison` (P1, side-by-side UBI-vs-LLM demo study).
- **2026-05-29** — `feat_study_sub_warmup_guard` (PR #316). First MVP2 feature ships. Closes the Custom-mode sub-warmup gap left open by `chore_study_default_stop_conditions` (2026-05-23): adds a non-blocking inline amber warning to the create-study modal's Step 5 when operators enter `max_trials < 50` in Custom mode. Hoists the inline `50` at `optuna_runtime.py:154` to a module-level `STUDIES_TPE_WARMUP_FLOOR` constant; frontend `SUB_WARMUP_FLOOR` mirrors with the `// Values must match` discipline comment + value-lock unit test. 3 new backend pytest assertions (value lock + `floor-1=49` boundary + `floor=50` boundary using constant); 5 new vitest cases (AC-1..AC-4 + AC-6 submit-non-blocking). Single-phase per spec D-6; digest narrative routed to `feat_study_convergence_indicator`. Cross-model review: spec converged at cycle 3 (13/13 accepted), plan converged at cycle 3 (8 accepted + 1 rejected with counter-evidence), phase-gate converged at cycle 2 (clean), final GPT-5.5 + 1 Gemini finding accepted.
- **2026-05-29** — `docs: reclassify 2 deferred MVP1 items → 99_backlog/03_mvp3` (PR #310, docs-only). Empties `01_mvp1/` — MVP1 actionable backlog fully drained. `chore_demo_reseed_stale_recovery_atomic_cas` → `99_backlog/` (already Priority: Backlog); `infra_agent_sibling_worktree_isolation` → `99_backlog/` (phases 1+2 shipped, only phase3 remains, defer-until-incident). Dashboards regenerated.
- **2026-05-29** — `bug_smoke_studies_data_table_search_flake` (PR #308 + finalization #309). Hardened the flaky `studies-data-table.spec.ts:20` search-visibility assertion: scoped it to the `studies-table` element + 15s web-first timeout to ride out the debounce→refetch→render race on slow CI runners. e2e-only; no product change.
- **2026-05-30** — `feat_demo_ubi_study_comparison` Phase 1 (PR #320, squash-merged `853a5053`). MVP2 third feature: the demo reseed now seeds **synthetic UBI clickstream** on 3 of 4 demo clusters so the on-ramp ladder (rung_0→rung_3) is browser-visible without operator setup, plus a "Synthetic demo data" disclosure chip on 5 UI surfaces. 14 stories across 4 epics: pure-domain generator (`backend/app/domain/demo/synthetic_ubi.py`) + allowlist-guarded writer (`demo_ubi_seed.py`) + canonical `samples/ubi_index_mappings.json` (single source of truth for the Python generator + Playwright helper) → SCENARIOS `ubi_target_rung`/`ubi_converter` keys (acme=rung_3/ctr_threshold, corp=rung_1/hybrid, jobs=rung_2/hybrid, news=rung_0 negative case) + module-level invariant → reseed orchestrator UBI seed + dispatch + dual (LLM)/(UBI) studies + `DEMO_ES_INDICES` cleanup → CLI parity via shared `_async_seed_synthetic_ubi` → `isDemoSyntheticUbiClusterName` helper + glossary key + CI parity guard + `<DemoBadge variant="synthetic-ubi">` on 5 surfaces (a11y: aria-label + keyboard focus + glossary tooltip) → fast-lane (always-on) + heavy-lane (`SKIP_HEAVY_CI`-gated) integration tests + real-backend E2E spec + docs. Cross-model review: 4 Gemini findings (all accepted, `b5b38dfb`) + 6 GPT-5.5 findings (5 accepted `6e55c32e` incl. a High-sev CLI host-path bug; 1 rejected as spec-vs-code drift — the chip can't sit by `<UbiRungBadge>` because that badge isn't on the cluster-detail page by design). Phase 2 (side-by-side LLM-vs-UBI comparison view) + the deferred cluster-detail rung badge split out to `feat_ubi_llm_study_comparison`.
- **2026-05-29** — `feat_ubi_judgments` (PR #317, squash-merged). MVP2 second feature: engine-neutral User Behavior Insights judgment generation, shipped end-to-end (all 13 stories incl. E2E + DB-backed integration tests + operator docs — none deferred). Migration 0021 (judgment_lists.generation_params JSONB) → domain/ubi/ pure-domain library + UbiReader (engine-neutral two-index scan) + ubi_readiness classifier (rung_0..rung_3) + dispatcher + endpoints + Arq worker + 21st agent tool + frontend method picker/nudge/value-delta + runbook + 4 E2E specs. Real-engine E2E caught a `size=50000 > max_result_window` bug; fixed by clamping to `ES_MAX_RESULT_WINDOW=10000`. Spun-out follow-ups: `chore_ubi_reader_search_after_pagination` (P2), `chore_ubi_hybrid_template_render` (P3).
- **2026-05-29** — `feat_study_sub_warmup_guard` (PR #316). First MVP2 feature. Non-blocking amber warning on the create-study modal's Step 5 when `max_trials < 50` in Custom mode. Hoisted the inline `50` to `STUDIES_TPE_WARMUP_FLOOR`; frontend `SUB_WARMUP_FLOOR` mirrors with discipline comment + value-lock test.
- **2026-05-29** — `docs: reclassify 2 deferred MVP1 items → 99_backlog/03_mvp3` (PR #310, docs-only). Empties `01_mvp1/` — MVP1 actionable backlog fully drained.
- **2026-05-29** — `bug_smoke_studies_data_table_search_flake` (PR #308 + finalization #309). Hardened the flaky `studies-data-table.spec.ts:20` search-visibility assertion (scoped to `studies-table` + 15s web-first timeout). e2e-only; no product change.

## In flight

- _None._ `feat_demo_ubi_study_comparison` Phase 1 (PR #320) merged 2026-05-30; finalization on `docs/finalize-demo-ubi-study-comparison` (this branch).

## Queued (priority-ordered by dashboard / dep graph)

**Source of truth:** [`docs/00_overview/DASHBOARD.md`](docs/00_overview/DASHBOARD.md) + [`docs/00_overview/MVP1_DASHBOARD.md`](docs/00_overview/MVP1_DASHBOARD.md) (regenerated by the `mvp1-dashboard-regen` pre-commit hook). Run `/pipeline status` for the live view.

**MVP1 backlog is fully drained** (`01_mvp1/` empty as of PR #310). The next stop is **MVP2 / v0.2 — "Three-Engine + Real Signals"**. With `feat_demo_ubi_study_comparison` Phase 1 merged (PR #320) and its Phase 2 split out to `feat_ubi_llm_study_comparison`, the `02_mvp2/` bucket holds 18 folders (run `ls docs/00_overview/planned_features/02_mvp2/` for the live list):

- **Headliners:** `infra_adapter_solr` (Apache Solr adapter), `feat_fts_rank_ordering`, `feat_chat_last_message_preview`, `feat_overnight_autopilot`, `feat_query_normalization_tuning`, `feat_study_convergence_indicator`, `feat_ubi_llm_study_comparison` (side-by-side UBI-vs-LLM study comparison view + deferred cluster-detail rung badge, P2 — Phase 2 split out of `feat_demo_ubi_study_comparison`).
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
