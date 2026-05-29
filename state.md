# RelyLoop — Active State

> Read this first. A one-page snapshot: current focus, the last few merges, what's in flight, what's queued, and where the project sits in the MVP1 → MVP2 → MVP3 → GA roadmap. **Historical feature-merge narrative + chained execution context lives in [`state_history.md`](state_history.md)** — new merge entries land there, not here (per `chore_state_md_size_compression`, 2026-05-29). Keep this file loadable in a single `Read` call.

**Last updated:** 2026-05-29 (after PR #310 — `01_mvp1/` planned-features bucket fully drained; the two remaining deferred-by-design folders reclassified to `99_backlog/` + `03_mvp3/`).

## Where the roadmap sits

MVP1 (v0.1) **shipped** — all six differentiators live (Bayesian/TPE optimizer, Git-PR apply path, conversational agent, ES + OpenSearch adapters, LLM judgments, local-first stack). The release matrix was compressed to four stops on 2026-05-27 — MVP1 → MVP2 (Three-Engine + Real Signals: Solr adapter + UBI judgments) → MVP3 (Observable) → GA v1 (hardening). Multi-tenant + multi-LLM + multi-Git + LTR + Path B are backlog. Canonical matrix: [`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md); full reshuffle rationale archived in [`state_history.md`](state_history.md).

## ⚠️ Active CI note — heavy jobs temporarily skipped

**`SKIP_HEAVY_CI=true` repo variable is set (2026-05-29, ~3-day GitHub Actions budget measure; PR #307).** The 5 `pr.yml` jobs over 1 min — `backend` (lint+typecheck+tests+coverage), `frontend`, `smoke`, both `docker buildx` — are **skipped** on every PR. Only the 4 sub-minute checks run (backend fast-lane unit tests, DCO, secrets guard, gitleaks). **While this is active, lean on local `make test` / `pnpm test` + review before merging — CI is not validating the full suite, coverage gate, smoke, or builds.** Scheduled to auto-restore on ~2026-06-01 (routine deletes the variable); restore manually anytime with `gh variable delete SKIP_HEAVY_CI`. The `if:` kill-switch stays in `pr.yml` as documented infra.

## Current branch / execution context

- **Branch:** working through the post-MVP1 `01_mvp1/` planned-features backlog (bugs + chores) via `/pipeline` — code PR + docs-only finalization PR per item. See `/pipeline status` for the live queue.
- **Active feature:** none in flight (MVP1 alpha shipped; draining the `01_mvp1/` backlog).
- **Alembic head:** `0020_studies_baseline_trial` (added by `feat_study_baseline_trial` PR #245 — `studies.baseline_trial_id` + `trials.is_baseline` + partial unique index `uq_trials_study_baseline_complete`).
- **Python:** 3.13. **Frontend stack:** Next 16 (App Router + Turbopack), React 19, Tailwind 4 (CSS-first), Vitest 4, ESLint 9 (flat), TypeScript 6, Playwright (chromium, single worker) for E2E.
- **Coverage gates:** backend 80% (`fail_under` in pyproject), UI vitest + tsc + ESLint + Next build, plus a full-stack smoke E2E job. Live pass counts: see the latest `pr.yml` run (the historical per-feature counts moved to `state_history.md`).

## Last 5 merges (newest first)

Detail + reasoning for each is in [`state_history.md`](state_history.md).

- **2026-05-29** — `docs: reclassify 2 deferred MVP1 items → 99_backlog/03_mvp3` (PR #310, docs-only). Empties `01_mvp1/` — MVP1 actionable backlog fully drained. `chore_demo_reseed_stale_recovery_atomic_cas` → `99_backlog/` (already Priority: Backlog); `infra_agent_sibling_worktree_isolation` → `99_backlog/` (phases 1+2 shipped, only phase3 remains, defer-until-incident). Dashboards regenerated.
- **2026-05-29** — `bug_smoke_studies_data_table_search_flake` (PR #308 + finalization #309). Hardened the flaky `studies-data-table.spec.ts:20` search-visibility assertion: scoped it to the `studies-table` element + 15s web-first timeout to ride out the debounce→refetch→render race on slow CI runners. e2e-only; no product change.
- **2026-05-29** — `ci(pr): SKIP_HEAVY_CI kill-switch` (PR #307, infra). Added an `if:` guard on the 5 `pr.yml` jobs over 1 min so a repo variable can skip them (temporary GitHub Actions budget measure). See the Active CI note above — variable currently set, auto-restores ~2026-06-01.
- **2026-05-29** — `bug_ceiling_badge_assumes_maximize_direction` (PR #305 + finalization #306). Studies-list CEILING badge (best_metric ≥ 0.99) mislabeled minimize studies (0.99 is a bad score there). Preflight found it had gone latent→live (feat_study_baseline_trial made `direction=minimize` creatable). Added `direction` to StudySummary (defaults maximize) + gated the badge on `direction !== 'minimize'` (rolling-deploy-safe per Gemini). 7 tests.
- **2026-05-29** — `chore_state_md_size_compression` (PR #303 + finalization #304). Split `state.md` (360 KB → 9.3 KB snapshot) from new `state_history.md` (append-only narrative, root); added `state-md-size-guard` pre-commit hook (60 KB cap) + CLAUDE.md snapshot-vs-history convention. **First merge under the new convention.**

## In flight

- None. MVP1 alpha shipped; the pre-MVP2 sweep drained the entire `01_mvp1/` backlog — that bucket is now empty (PR #310). Next work is the `02_mvp2/` queue below.

## Queued (priority-ordered by dashboard / dep graph)

**Source of truth:** [`docs/00_overview/DASHBOARD.md`](docs/00_overview/DASHBOARD.md) + [`docs/00_overview/MVP1_DASHBOARD.md`](docs/00_overview/MVP1_DASHBOARD.md) (regenerated by the `mvp1-dashboard-regen` pre-commit hook). Run `/pipeline status` for the live view.

**MVP1 backlog is fully drained** (`01_mvp1/` empty as of PR #310). The next stop is **MVP2 / v0.2 — "Three-Engine + Real Signals"**. The `02_mvp2/` bucket currently holds 11 folders (run `ls docs/00_overview/planned_features/02_mvp2/` for the live list):

- **Headliners:** `infra_adapter_solr` (Apache Solr adapter), `feat_ubi_judgments` (UBI judgment source), `feat_chat_last_message_preview`, `feat_fts_rank_ordering`.
- **Bugs held for MVP2:** `bug_chat_long_conversation_truncation` (investigation `bug_fix.md` exists; pullable forward but deferred for scope discipline — latency-of-impact is zero today), `bug_webhook_concurrent_merge_race_timing_sensitive`.
- **Chores:** `chore_auto_followup_parent_advisory_lock`, `chore_demo_seeding_integration_tests_rewrite`, `chore_studies_post_arq_spy_fixture`, `chore_template_library_expansion`, `infra_arq_subprocess_test`.

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
