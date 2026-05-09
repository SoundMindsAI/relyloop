# RelyLoop — Active State

> Read this first. Snapshots the active branch, what just shipped, what's in flight, what's queued, and where the project currently sits in the MVP1 → GA roadmap. Updated whenever a feature lands or a priority shifts.

**Last updated:** 2026-05-09

---

## Current branch / execution context

- **Branch:** `main` (clean; `infra_foundation` PR #4 merged 2026-05-09)
- **Active feature:** None in flight. Next up: [`infra_adapter_elastic`](docs/02_product/planned_features/infra_adapter_elastic/) — the engine adapter (Elasticsearch + OpenSearch) that unblocks every downstream MVP1 feature.
- **Alembic head:** `0001_baseline` (registers `alembic_version`; first
  business-table migration lands with `infra_adapter_elastic`)
- **Coverage:** 90.17% backend (gate is 80%); `health.py` + `probes.py` +
  `capability_models.py` + `errors.py` all at 100%.

## Most recent meaningful changes (newest first)

- **2026-05-09 — `infra_foundation` PR #4 merged to `main`** (squash commit
  `93eeb64`). Bootstrap complete: 6-service Compose stack, FastAPI +
  `/healthz`, OpenAI capability check at startup, Alembic baseline
  (`0001`), 80% coverage gate (currently at 90.17%), GitHub Actions
  `pr.yml` with three required-check jobs. Five first-run bugs surfaced
  during operator testing and were fixed inline (stale image, stale
  database_url stub, host-vs-container env var assumptions, alembic
  post-write hook crash, hashed rev-id); two process patches landed in
  the same PR (`impl-execute` operator-path verification gate +
  CLAUDE.md local-stub hygiene rule). Feature folder moved to
  [`docs/00_overview/implemented_features/2026_05_09_infra_foundation/`](docs/00_overview/implemented_features/2026_05_09_infra_foundation/).
- **2026-05-09 — `infra_foundation` Stories 3.3 / 4.1 / 4.2 / 4.3 / 4.4 / 5.1
  / 5.2 land on `feature/infra-foundation`.**
  - Story 3.3: OpenAI capability check at startup (4-step probe) + Redis
    24h cache + non-blocking `asyncio.create_task` startup wiring (FR-7).
  - Story 4.1: multi-stage Dockerfile (`relyloop/api`, 264 MB, non-root
    uid=1000, `RELYLOOP_GIT_SHA` build-arg).
  - Story 4.2: 6-service `docker-compose.yml` matching deployment.md;
    `127.0.0.1:` host binds only; healthchecks gate `worker → api → postgres`.
  - Story 4.3: Arq worker stub (`backend/workers/all.py`, empty
    `functions=[]`, `RedisSettings.from_dsn(Settings.redis_url)`).
  - Story 4.4: `.env.example` + idempotent `scripts/install.sh` (chmod 600
    on every secret) + `backend/tests/integration/test_health_integration.py`.
  - Story 5.1: `.github/workflows/pr.yml` (backend + frontend + docker
    jobs, 80% coverage gate via `pytest --cov`); `.github/dependabot.yml`
    (weekly updates). Also backfilled `test_probes.py` (17 cases) and
    `test_health_contract.py` (5 cases) — these were planned for Story 3.2
    but missed at the time.
  - Story 5.2: this `state.md`, `architecture.md`, `docs/03_runbooks/local-dev.md`,
    `docs/05_quality/testing.md`, expanded `README.md` Quickstart, root
    CLAUDE.md updates.
- **2026-05-09 — Stories 1.1 / 1.2 / 1.3 / 1.4 / 2.1 / 2.2 / 3.1 / 3.2 already
  merged earlier on the same branch** (Python toolchain, frontend, pre-commit,
  Settings, Alembic baseline, FastAPI skeleton, `/healthz`).

## In flight

None. `main` is clean post-merge of PR #4.

## Queued (priority-ordered by dependency)

1. **`infra_adapter_elastic`** ← **next up.** `clusters` + `config_repos`
   tables; `ElasticAdapter` covering ES 8.11+/9.x and OpenSearch 2.x/3.x.
   `infra_foundation` is now merged so this is unblocked. Run
   `/pipeline docs/02_product/planned_features/infra_adapter_elastic --auto`
   to start.
2. **`infra_optuna_eval`** — Optuna RDBStorage tables + pytrec_eval wiring.
3. **`feat_study_lifecycle`** — 7-table study/trial/proposal schema.
4. **`feat_llm_judgments`** — judgment-list LLM rubric runner.
5. **`feat_digest_proposal`** — study-end digest narrative.
6. **`feat_github_pr_worker`** — GitHub PR creation Arq job.
7. **`feat_github_webhook`** — `/webhooks/github` (idempotent, signature-verified).
8. **`feat_studies_ui`** — UI shell + `/studies` + `/studies/[id]`.
9. **`feat_chat_agent`** — streaming chat orchestrator.
10. **`feat_proposals_ui`** — `/proposals` review surface.
11. **`chore_tutorial_polish`** — sample data + walkthrough.

Run `/pipeline status` for the live view from spec dependencies.

## Known debt / fragility

- **CI lacks a `make up` smoke job.** All 5 first-run bugs in the
  `infra_foundation` PR surfaced after CI was green. Captured at
  [`infra_ci_smoke_makeup`](docs/02_product/planned_features/infra_ci_smoke_makeup/idea.md)
  with a ready-to-paste workflow YAML — should land before MVP1 ships
  to prevent recurrence.
- **Tangential bugs captured during the bootstrap:**
  - [`bug_env_file_corrupted_during_session`](docs/02_product/planned_features/bug_env_file_corrupted_during_session/idea.md) — operator's `.env` was renamed to `.env.old` mid-session by an unidentified tool. `.gitignore` patched defensively; root cause investigation deferred.
  - [`chore_starlette_422_deprecation`](docs/02_product/planned_features/chore_starlette_422_deprecation/idea.md) — `HTTP_422_UNPROCESSABLE_ENTITY` rename surfaces a `DeprecationWarning` on every test run; mechanical fix.
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
