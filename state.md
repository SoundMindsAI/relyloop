# RelyLoop — Active State

> Read this first. Snapshots the active branch, what just shipped, what's in flight, what's queued, and where the project currently sits in the MVP1 → GA roadmap. Updated whenever a feature lands or a priority shifts.

**Last updated:** 2026-05-10 (after Phase 2 plan approval — `feat_study_lifecycle` Phase 2)

---

## Current branch / execution context

- **Branch:** `feature/feat-study-lifecycle-phase2` — Phase 2 plan approved 2026-05-10 via `/pipeline ... --auto` after 3 GPT-5.5 review cycles (21 findings, 19 accepted, 1 rejected with cited counter-evidence). Ready for `/impl-execute`.
- **Active feature:** `feat_study_lifecycle` Phase 2 (Orchestrator + API). Plan: [`phase2_implementation_plan.md`](docs/02_product/planned_features/feat_study_lifecycle/phase2_implementation_plan.md). 14 stories across 4 epics; covers FR-1 through FR-7 + all 10 ACs.
- **Alembic head:** unchanged at `0003_study_lifecycle_schema` — `infra_optuna_eval` added zero migrations (per spec §9 "this feature does NOT define new tables"). Optuna's own tables live in the `optuna.*` schema and are created lazily by `RDBStorage` on first use; not part of RelyLoop's Alembic chain.
- **Coverage:** above the 80% gate. `infra_optuna_eval` additions are heavily unit-tested: 5 new modules under `backend/app/eval/` (38 unit tests) + `backend/workers/trials.py` (10 unit tests) + 8 integration tests + 1 contract test + 1 benchmark.

## Most recent meaningful changes (newest first)

- **2026-05-10 — `feat_study_lifecycle` Phase 2 plan approved.** [`phase2_implementation_plan.md`](docs/02_product/planned_features/feat_study_lifecycle/phase2_implementation_plan.md) generated and reviewed via `/pipeline ... --auto`. 14 stories across 4 epics (foundations → orchestrator → API → docs). Covers FR-1..FR-7 + AC-1..AC-10 + all 12 spec endpoints + all 12 spec error codes. **3 GPT-5.5 review cycles**: 21 findings total — 19 accepted + applied (key design decisions: `pg_try_advisory_xact_lock` for orchestrator replenishment atomicity, durable digest handoff via atomic `proposals` INSERT inside `complete_study` transaction, Jinja2 AST walk catching `Call`/`Getattr`/dunder-name references before meta-vars cross-check for AC-7 sandbox, short-lived per-tick DB sessions in the orchestrator polling loop, model-level event listener with `event.contains(...)` idempotency); 1 rejected with cited counter-evidence (cycle-1 F2 — spec FR-3 says `cluster_id?` but Phase 1's schema is NOT NULL; captured as [`chore_spec_query_set_cluster_id_drift`](docs/02_product/planned_features/chore_spec_query_set_cluster_id_drift/idea.md) for spec patch). Pending: `/impl-execute` invocation.
- **2026-05-10 — `infra_optuna_eval` merged into `main`** as PR #23 (squash commit `c4f1aab`). 8 stories across 3 epics. Zero migrations (purely additive against the `0003` schema):
  - **Epic 1 (eval helpers):** `backend/app/eval/` package — `types.py` (SamplerKind, PrunerKind, TrialStatus Literals per spec §8.4) + `scoring.py` (pytrec_eval scorer + objective_metric_key + SUPPORTED_METRICS/SUPPORTED_K_VALUES frozensets + user-facing → wire-name translation table per FR-3). 38 unit tests; AC-3 hand-computed nDCG@10/MAP@10 baselines verified within 1e-6.
  - **Epic 2 (runtime):** `optuna_runtime.py` (`_compose_storage_url`, `build_storage`, `build_sampler`, `build_pruner`, `get_or_create_study`); `qrels_loader.py` (MVP1 stub raising `JudgmentsTableMissing` until `feat_llm_judgments` ships the `judgments` child table); `backend/workers/trials.py` (run_trial Arq job — idempotency check + spec §11 clause 1b reconciliation + happy path + state-specific reconstruction for COMPLETE/FAIL/PRUNED). `WorkerSettings.on_startup` boots Optuna `RDBStorage` once per worker (spec FR-1). `services.cluster._build_adapter` renamed to public `build_adapter`. Stale `optuna_trial_number` docstring on `trial.py:48` fixed.
  - **Epic 3 (tests/contract/benchmark/docs):** 6 integration tests covering AC-1a..AC-8b (including subprocess-driven partial-failure tests with env-var fault seams `after_trial_load_before_execute` and `after_tell_before_insert`); contract test for Trial row shape (FR-5 invariants); benchmark verifying score() < 100ms/query for 50q×top_k=10; `docs/03_runbooks/optuna-debugging.md` runbook; added `test_concurrent_ask_tell_does_not_deadlock` (final-review accept) verifying parallel `study.ask`/`study.tell` against Optuna's RDB locking.
  - **GPT-5.5 final review on merged diff (commit `3b112f9`):** 4 findings — 3 accepted (missing-ctx fail-loud check moved outside the trial-level try; default secondary metrics inventory `_DEFAULT_SECONDARY_METRICS = {"ndcg@10","map@10","mrr"}` when `config.secondary_metrics` is absent; concurrent ask/tell integration test); 1 rejected with cited counter-evidence (AC-7 covered at adapter+worker layer composition via `infra_adapter_elastic`'s `test_elastic_msearch.py`).
  - **CI iterations:** 4 runs total — first was the initial push (caught test pollution + missing `gcc`); next two added test-setup migrations/cleanup_fixture and gcc/python3-dev for `pytrec_eval`'s C extension; final run was the final-review fixes.
  - **Tangential discovery filed:** `chore_infra_optuna_eval_spec_text_drift` (spec §14 vs §11 wording drift around partial-failure retry contract; the plan implements per §11, recommended spec patch is documented).
  - Feature folder moved to [`docs/00_overview/implemented_features/2026_05_10_infra_optuna_eval/`](docs/00_overview/implemented_features/2026_05_10_infra_optuna_eval/).
- **2026-05-10 — `feat_study_lifecycle` Phase 1 (Schema) merged into `main`**
  as PR #18 (squash commit `d74e1be`). All 3 stories shipped in a single
  epic:
  - **Story 1.1** (`7bb9613`): 7 ORM models — `QueryTemplate`, `QuerySet`,
    `Query`, `Study`, `Trial`, `JudgmentList`, `Proposal` — registered with
    `Base.metadata`. The `Query` model uses Python attribute
    `query_metadata` with explicit DB column name `"metadata"` to avoid
    collision with SQLAlchemy's reserved `DeclarativeBase.metadata`.
  - **Story 1.2** (`b3be589`): Alembic migration `0003_study_lifecycle_schema`
    creating all 7 tables in FK-respecting order with 5 CHECK constraints
    (4 status enums + `proposals.pr_state`), 4 UNIQUE constraints, 16 FK
    targets (2 CASCADE on `queries`/`trials`, 14 NO ACTION elsewhere
    including 2 self-FKs on `query_templates` + `studies`), and the
    `trials_study_metric` index `(study_id, primary_metric DESC NULLS
    LAST)`.
  - **Story 1.3** (`7b4dd0a`): 15 minimal repo functions across 7 modules.
    Phase 1 ships exactly what `infra_optuna_eval`'s `run_trial` consumes;
    Phase 2 extends with cursor pagination + status filters + bulk CSV
    upload.
  - **Test fix** (`02bb382`): retarget `test_clusters_migration::
    test_downgrade_removes_both_tables` to use explicit `downgrade 0001`
    so it stays correct as the chain extends past `0002`.
  - **GPT-5.5 phase-diff review** (`08b8b30`): 5 findings — 4 accepted +
    landed (NOT NULL coverage via `information_schema.columns`, FK targets
    via `referential_constraints + key_column_usage`, UNIQUE inventory via
    `pg_constraint`, `judgment_lists.status` invalid-value `'archived' →
    'cancelled'`); 1 rejected with cited counter-evidence (the
    `test_clusters_migration` retarget — necessary forward-compat fix).
  - **GPT-5.5 final review** (`f5d3302`): 1 finding — accepted, doc
    straggler in spec phase-boundaries text (`11 → 12 endpoints`). Cycle 2
    converged.
  - 14 integration tests across 8 classes in
    `test_study_lifecycle_migration.py` + 11 round-trip tests in
    `test_study_repos.py`.
  - **Phase 2 (Orchestrator + API) is deferred** via
    [`phase2_idea.md`](docs/02_product/planned_features/feat_study_lifecycle/phase2_idea.md);
    the feature folder stays in `planned_features/` until Phase 2 ships.
- **2026-05-10 — `infra_adapter_elastic` merged into `main`** as PR #16
  (squash commit `43ab813`). All 20 stories across 5 epics shipped:
  - **Epic 1**: `SearchAdapter` Protocol + 8 Pydantic types + `clusters` /
    `config_repos` ORM models + Alembic migration `0002` (round-trip
    verified) + repo functions with cursor pagination.
  - **Epic 2**: `ElasticAdapter` for ES (8.11+/9.x) + OpenSearch (2.x),
    auth resolution (apikey / basic), `_request` with spec §13 single
    retry + 401/403/5xx translation, `health_check` with 30s Redis cache,
    `list_targets` / `get_schema` / `list_query_parsers`,
    `render` (Jinja → ES Query DSL), `search_batch` via single `_msearch`
    call, `explain`, engine-branch tests.
  - **Epic 3**: cluster service (registration probe + revival of soft-deleted
    rows + dispatch_run_query), 6 endpoints under `/api/v1/clusters` (POST
    register, GET list with cursor + `X-Total-Count`, GET detail, DELETE
    soft-delete, GET `/schema`, POST `/run_query`), `/healthz` extension
    with `subsystems.elasticsearch_clusters` aggregate field.
  - **Epic 4**: `make seed-clusters` (idempotent — `local-es` +
    `local-opensearch`), `scripts/install.sh` seeds the dev-default
    cluster credentials, `docs/03_runbooks/cluster-registration.md`,
    spec/adapters.md path patches (`backend/adapters/` →
    `backend/app/adapters/`, section §7.x → §8.x).
  - **Epic 5**: 8-code error envelope contract test, dispatch_run_query
    unit tests, coverage audit (90.85% — well above gate).
  - 19 GPT-5.5 plan-review findings (12 High / 7 Medium) all applied
    pre-implementation; final-cycle review of the merged diff raised 5
    findings (4 accepted + fixed in `1ce618f`, 1 rejected with cited
    counter-evidence — truncation artifact).
  - Refactor sweep (commit `c6758bd`): cross-product `engine_type ×
    auth_kind` allowlist (rejects misconfigurations like
    `opensearch + es_apikey` at registration); `acquire_adapter` async
    context manager dedupes the schema/run_query handlers'
    "build adapter, translate CredentialsMissing, finally aclose"
    boilerplate. Filed [`chore_test_both_engines`](docs/02_product/planned_features/chore_test_both_engines/idea.md)
    as a follow-up for parameterizing integration tests over both engines.
  - Operator-facing docs: [`docs/03_runbooks/cluster-registration.md`](docs/03_runbooks/cluster-registration.md)
    runbook + new conceptual overview at [`docs/01_architecture/cluster-lifecycle.md`](docs/01_architecture/cluster-lifecycle.md).
  - Operator-path verification: live ES 9.4.0 + OpenSearch 2.18.0
    exercised end-to-end via the dev-deps container; `/healthz` returns
    `subsystems.elasticsearch_clusters: {"registered": 2, "healthy": 2,
    "unreachable": 0}` after `make seed-clusters`.
  - Feature folder moved to [`docs/00_overview/implemented_features/2026_05_10_infra_adapter_elastic/`](docs/00_overview/implemented_features/2026_05_10_infra_adapter_elastic/).
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

- **`feat_study_lifecycle` Phase 2** on branch `feature/feat-study-lifecycle-phase2`. Plan approved 2026-05-10 via `/pipeline ... --auto`; **`/impl-execute` invocation pending**. 14 stories across 4 epics covering the 12 endpoints + orchestrator + state-transition guard + resume-after-restart loop. Plan: [`phase2_implementation_plan.md`](docs/02_product/planned_features/feat_study_lifecycle/phase2_implementation_plan.md).

## Queued (priority-ordered by dependency)

1. **`feat_llm_judgments`** — judgment-list LLM rubric runner; adds the `judgments` child table and replaces `backend/app/eval/qrels_loader.py`'s MVP1 stub with a real `SELECT`.
2. **`feat_digest_proposal`** — study-end digest narrative. **Must scan pre-existing `proposals WHERE status='pending'`** at boot — Phase 2's orchestrator pre-creates pending proposal rows (per the C2-F3/C3-F3 durable handoff design).
3. **`feat_github_pr_worker`** — GitHub PR creation Arq job.
4. **`feat_github_webhook`** — `/webhooks/github` (idempotent, signature-verified).
5. **`feat_studies_ui`** — UI shell + `/studies` + `/studies/[id]`.
6. **`feat_chat_agent`** — streaming chat orchestrator.
7. **`feat_proposals_ui`** — `/proposals` review surface.
8. **`chore_tutorial_polish`** — sample data + walkthrough.
9. **`chore_spec_query_set_cluster_id_drift`** — one-line spec patch for FR-3 wording (captured 2026-05-10 from GPT-5.5 cycle-1 F2 adjudication).

Run `/pipeline status` for the live view from spec dependencies.

## Known debt / fragility

- **`backend/app/eval/qrels_loader.py` is an MVP1 stub.** It raises `JudgmentsTableMissing` because the `judgments` child table (owned by `feat_llm_judgments`) hasn't shipped. Integration tests monkeypatch the loader; in production the only path that would call `load_qrels` is `feat_study_lifecycle` Phase 2's orchestrator (also deferred). The real implementation lands atomically with `feat_llm_judgments`.
- **`chore_infra_optuna_eval_spec_text_drift`** — spec §14 vs §11 wording drift around partial-failure retry; this feature implements per §11. Tracked at [`docs/02_product/planned_features/chore_infra_optuna_eval_spec_text_drift/idea.md`](docs/02_product/planned_features/chore_infra_optuna_eval_spec_text_drift/idea.md).
- **`infra_optuna_orphan_reaper`** — Phase 2 orchestrator can die between `study.ask()` and the enqueue commit, leaving orphan Optuna RUNNING trials. Operationally tolerated for MVP1 per spec §11 "Operational tolerance"; periodic reaper deferred.
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
