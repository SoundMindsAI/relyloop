# RelyLoop — Active State

> Read this first. Snapshots the active branch, what just shipped, what's in flight, what's queued, and where the project currently sits in the MVP1 → GA roadmap. Updated whenever a feature lands or a priority shifts.

**Last updated:** 2026-05-11 (after `feat_digest_proposal` implementation complete, PR pending)

---

## Current branch / execution context

- **Branch:** `feature/feat-digest-proposal` — 12 stories complete + Epic 4 docs/tests; PR not yet opened.
- **Active feature:** `feat_digest_proposal` in flight (study-end digest narrative + populates the pending proposal row).
- **Alembic head:** `0005_digests` (bumped by Story 1.1 of `feat_digest_proposal`).
- **Coverage:** above the 80% gate. 350 unit tests + 2 xpassed + 80+ integration (including 26 new for digest worker + API) + 6 contract (including 1 new for digest+proposals API).

## Most recent meaningful changes (newest first)

- **2026-05-11 — `feat_digest_proposal` implementation complete (PR pending)** on `feature/feat-digest-proposal`. 12 stories across 4 epics covering FR-1..FR-6 + FR-2b + AC-1..AC-11. **One migration (`0005_digests`).** Plan went through **3 GPT-5.5 review cycles** (20 findings, all accepted + applied) before execution.
  - **Epic 1 (foundations, 3 stories):** `0005_digests` migration creating the `digests` table per data-model.md (`id`, `study_id UNIQUE`, `narrative`, `parameter_importance JSONB`, `recommended_config JSONB`, `suggested_followups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]` per cycle-1 F1, `generated_by`, `generated_at`); `Digest` ORM model exported via `db/models/__init__.py`; new `db/repo/digest.py` (`create_digest`, `get_digest_for_study`) + 5 proposal repo extensions per FR-6 (`update_proposal_for_digest` conditional on `WHERE status='pending'` per cycle-3 F4, `list_proposals_paginated`, `count_proposals`, `reject_proposal` raises `InvalidStateTransition`, `list_pending_proposals_for_boot_scan`); `prompts/digest_narrative.system.md` + `digest_narrative.user.jinja` with `include_recommendation` toggle for the degraded path (cycle-3 F3); `backend/app/llm/digest_prompt.py` with `lru_cache`-cached `DigestPromptBundle` + `SandboxedEnvironment(autoescape=True)` mirroring `prompt_loader.py`.
  - **Epic 2 (worker, 2 stories):** `backend/workers/digest.py:generate_digest` (15-step contract) REPLACES `backend/workers/digest_stub.py` (file deleted) under the same Arq job name so the orchestrator's enqueue at `orchestrator.py:370` keeps firing. Key cycle revisions: pre-LLM idempotency guard via `get_digest_for_study` (cycle-1 F6); `pg_try_advisory_xact_lock` keyed on `blake2b("digest:{sid}")` held across LLM call + persist tx (cycle-2 F6 — prefix disjoint from orchestrator's replenish lock); zero-trials short-circuit moved BEFORE OpenAI preflights (cycle-2 F5 — AC-2 fires regardless of config); capability fallback as a mode flag, NOT short-circuit (cycle-3 F2 — pricing + budget still gate); deterministic `recommended_config` (cycle-1 F5 / cycle-2 F1 — best-trial params filtered to currently-declared template params; all-dropped sub-case persists empty-recommendation digest + DELETEs the pending proposal per cycle-2 F7); persist FIRST then `_safe_record_cost` (cycle-2 C2-F3 from feat_llm_judgments); conditional UPDATE on the pending proposal handles operator-reject-mid-LLM race (cycle-3 F4 — benign no-op). `WorkerSettings.on_startup` extended with the FR-2b boot scan (list_pending_proposals_for_boot_scan + deterministic `_job_id="generate_digest:{sid}"`).
  - **Epic 3 (API, 4 stories, 5 endpoints):** `backend/app/api/v1/proposals.py` (new router; registered in `main.py` alongside the existing v1 routers): `GET /studies/{id}/digest` (FR-3 / AC-3 / AC-4 — 404 STUDY_NOT_FOUND vs DIGEST_NOT_READY); `POST /proposals` (FR-4 / AC-6 — manual creation, study_id NULL); `GET /proposals` (cursor + status Literal + cluster_id filter + X-Total-Count); `GET /proposals/{id}` (detail with inline `study_summary` + `digest` to spare UI a fan-out query); `POST /proposals/{id}/reject` (FR-4 / AC-5 — pending → rejected; 409 INVALID_STATE_TRANSITION via repo's `InvalidStateTransition`). `ProposalStatusWire` and `ProposalPrStateWire` Literals carry source-of-truth comments per cycle-2 F4 / cycle-3 F1.
  - **Epic 4 (docs/tests/cleanup, 3 stories):** `docs/03_runbooks/digest-debugging.md` (operator playbook covering all 8 worker `event_type` markers + re-running deferred digests + force-regeneration + concurrency model + worker-side error code catalog); `docs/04_security/llm-data-flow.md` extended with "Digest path" section enumerating the smaller surface (no doc IDs / bodies / query text / rubric text); `docs/02_product/mvp1-user-stories.md` US-16 + US-17 → Implemented. **Lean refactor (inline during Story 2.1):** `_compute_default_params` lifted from `backend/workers/judgments.py` to `backend/app/domain/study/template_defaults.py` (consumed by both workers; eliminates duplication). Contract test `test_digest_proposal_api_contract.py` performs the cycle-2 F4 / cycle-3 F1 split static-grep audit (7 endpoint codes in router source; 5 internal codes in worker source; negative assertion that worker codes are NOT raised by the router). AC-8 token-budget benchmark uses `compute_call_cost(get_settings().openai_model, ...)` per cycle-1 F8.
  - **Tests:** 3 unit (`test_digest_prompt_render.py` 8 cases, `test_digest_response_format.py` 4 cases, `test_template_defaults.py` migrated from `test_judgment_default_params.py`) + 23 integration covering every AC + every cycle-N finding + 1 contract + 1 benchmark. Pre-existing tests patched: `test_migrations.py` Alembic-head expectation `0004 → 0005`; `judgments.py` now imports `compute_default_params` from the shared domain module.
  - **GPT-5.5 plan review:** 3 cycles to cap; 20 findings raised; all 20 accepted + applied (`/tmp/gpt55_review_cycle{1,2,3}.out`).
- **2026-05-11 — `feat_llm_judgments` merged into `main`** as PR #35 (squash commit `de0ecf8`). 16 stories across 4 epics covering FR-1..FR-6 + AC-1..AC-7. **One migration (`0004_judgments`).** GPT-5.5 final review converged in **10 cycles** (4 + 3 + 2 + 2 + 2 + 2 + 1 + 2 + 2 + 0 findings = 19 total; 18 applied + 1 rejected with cited counter-evidence on uuid_utils pre-existing dep).
  - **Epic 1 (foundations, 7 stories):** `0004_judgments` migration with UNIQUE `(judgment_list_id, query_id, doc_id)` + CHECK constraints + CASCADE FK; `Judgment` ORM model + `judgment` repo (bulk_create with ON CONFLICT DO NOTHING, upsert with `populate_existing=True` for identity-map correctness, source-breakdown folding `click` into `human` per cycle-2 F6); 4 `judgment_list` repo extensions including `list_generating_judgment_list_ids` for boot sweep; prompts/ directory at repo root with sandboxed Jinja2 renderer (`SandboxedEnvironment(autoescape=True)` per cycle-5 C5-F2) + FR-3c starter rubric verbatim; OpenAI judge client (`rate_query_batch`) with `response_format=json_schema strict=True`, `max_completion_tokens=2000`, exponential-backoff retry on RateLimitError/APITimeoutError/APIConnectionError/5xx (per cycle-6 C6-F2), per-item required-rationale validation (cycle-4 C4-F2), schema validation before iteration (cycle-3 C3-F2); cost model with `UnknownModelPricingError` fail-closed (cycle-2 C2-F4); Cohen's + linear-weighted kappa calibration helper (pure-Python, no NumPy); real `qrels_loader.py` SELECT replacing the MVP1 stub; Redis daily budget gate (`peek_daily_total` + `record_cost` with 26h TTL).
  - **Epic 2 (worker, 1 story):** `backend/workers/judgments.py:generate_judgments_llm` Arq job — short-lived per-query DB sessions; resume-skip on ANY existing judgments (cycle-1 F2); pre-call budget peek + post-call `_safe_record_cost` ordering (cycle-2 C2-F3 — persist judgments FIRST); ordinal prompt-IDs (`item-N`) to decouple LLM round-trip from XML-sensitive engine doc_ids (cycle-6 C6-F1); set-equality all-or-nothing per-query persistence (cycle-3 C3-F1 catches duplicate doc_ids); persistent-OpenAI-error propagation (cycle-2 C2-F1); `PARTIAL_LLM_FAILURE` terminal status when any query is skipped (cycle-8 C8-F1). `WorkerSettings.functions` registers `generate_judgments_llm` with 900s timeout; `on_startup` sweeps every `generating` row with deterministic `_job_id` for dedup (cycle-4 C4-F1).
  - **Epic 3 (API, 5 stories, 7 endpoints):** `POST /api/v1/judgments/generate` with 6-step preflight (OPENAI_NOT_CONFIGURED / LLM_PROVIDER_INCAPABLE strict cache-miss-OR-model-mismatch per cycle-8 C8-F2 / UNKNOWN_MODEL_PRICING / OPENAI_BUDGET_EXCEEDED peek / FK 404s / >10K-query 422 / query_set↔cluster + template engine consistency per cycle-9 C9-F1); `POST /api/v1/judgment-lists/import` (tutorial path with payload duplicate-pair detection per cycle-1 F3); `GET /api/v1/judgment-lists` (cursor + X-Total-Count); `GET /api/v1/judgment-lists/{id}` (detail with `_SourceBreakdown {llm, human}` + `judgment_count` + `calibration`); `GET /api/v1/judgment-lists/{id}/judgments` (cursor + typed `?source=llm|human` filter rejecting `click` per cycle-1 F1); `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` (UPSERT-replace, `INVALID_RATING` 400, `LIST_NOT_READY` 409); `POST /api/v1/judgment-lists/{id}/calibration` (filter pairs to `source='llm'` + dedup `(query_id, doc_id)` per cycle-9 C9-F2 + `INSUFFICIENT_SAMPLES` pre-check + post-match recheck).
  - **Epic 4 (docs, 3 stories):** `docs/04_security/llm-data-flow.md` enumerating what leaves the cluster per call + ZDR enrollment guidance; `docs/03_runbooks/judgment-generation-debugging.md` (quick-reference, resume CLI, calibration-from-CSV, bulk override loop); `docs/02_product/mvp1-user-stories.md` US-13/14/15 flipped to Implemented.
  - **Tests:** 9 new unit (default-params, prompt-render with autoescape canary, calibration, OpenAI judge, budget gate, qrels-loader seam) + integration coverage at every layer touched (`test_judgment_repo.py`, `test_qrels_loader.py`, `test_judgment_generate.py`, `test_budget_guardrail.py`, `test_judgments_api.py` 17 cases, `test_judgments_migration.py`) + contract (`test_judgments_api_contract.py` OpenAPI + 14-code error-catalog static grep). Pre-existing tests patched: `test_migrations.py` Alembic-head expectation `0003 → 0004`; `test_study_lifecycle_migration.py::test_downgrade_removes_seven_tables` retargeted to `downgrade 0002`; `test_workers.py` job-name set extended.
  - **GPT-5.5 final-review adjudication** (PR #35 comment): 10 cycles to convergence. 19 findings raised; **18 accepted + applied** (rubric-in-system-prompt, resume-skip-any, import-dup, AC-4 partial test, OpenAI-error-propagate, all-or-nothing-persist, persist-before-record, set-equality, schema-validate, Arq-job_id, required-rationale, max_completion_tokens, autoescape, ordinal-prompt-IDs, APIConnectionError retry, PARTIAL_LLM_FAILURE tracking, capability-model-match, consistency-check, calibration-dedup). **1 rejected** with cited counter-evidence (C7-F1 — `uuid_utils` dep declared at `pyproject.toml:37`). Cycle 10 = `{"findings":[]}` clean pass.
  - **Gemini Code Assist:** N/A on this repo — past PRs #25 / #23 / #18 / #16 / #4 all had 0 line comments confirming Gemini isn't installed.
  - **Follow-up idea files captured:** [`chore_spec_llm_judgments_endpoint_drift`](docs/02_product/planned_features/chore_spec_llm_judgments_endpoint_drift/idea.md) (§8.1 missing import endpoint row), [`chore_spec_llm_judgments_error_drift`](docs/02_product/planned_features/chore_spec_llm_judgments_error_drift/idea.md) (§8.5 missing QUERY_NOT_IN_SET + LIST_NOT_READY), [`chore_spec_llm_judgments_pricing_drift`](docs/02_product/planned_features/chore_spec_llm_judgments_pricing_drift/idea.md) (§8.5 missing UNKNOWN_MODEL_PRICING + FR-5 calibration-before-overrides guidance), [`chore_judgments_periodic_resume_sweep`](docs/02_product/planned_features/chore_judgments_periodic_resume_sweep/idea.md) (in-worker periodic re-enqueue; MVP1 ships boot-time sweep + REPL recovery only).
  - **CI iterations:** 8 total runs on the branch — initial push (5 failures: upsert identity-map + monkeypatch raising + migration head bumps); then 5 cycles of GPT-5.5-review-fix rounds; final finalize-metadata round.
  - Feature folder moved to [`docs/00_overview/implemented_features/2026_05_11_feat_llm_judgments/`](docs/00_overview/implemented_features/2026_05_11_feat_llm_judgments/).
- **2026-05-11 — `feat_study_lifecycle` Phase 2 merged into `main`** as PR #25 (squash commit `25bb5c9`). 14 stories across 4 epics covering FR-1..FR-7 + AC-1..AC-10. **Zero migrations.** GPT-5.5 final review converged in 4 cycles (10 + 3 + 2 + 0 findings). 10 findings applied; 6 follow-up idea files captured (`infra_per_trial_timeout`, `chore_openapi_contract_validation`, `infra_arq_subprocess_test`, `chore_trial_summary_single_query`, `chore_spec_trial_created_at_drift`, `chore_spec_query_set_cluster_id_drift`).
  - **Epic 1 (foundations, 5 stories):** SearchSpace Pydantic validator + Optuna sampler mapping (`domain/study/search_space.py`); Jinja2 SandboxedEnvironment template validator + AST walk for AC-7 (`domain/study/template_validator.py` + render.py sandbox swap); service-layer state machine + `before_flush` + `do_orm_execute` `StudyStateProtectionError` listeners (`services/study_state.py`, FR-7 / AC-6); Phase 2 repo extensions — `list_studies` / `list_running_study_ids` / `list_queued_study_ids` + `aggregate_trials_summary` / `list_trials_paginated` + `bulk_create_queries`; Settings additions `STUDIES_DEFAULT_PARALLELISM=4` + `STUDIES_DEFAULT_TIMEOUT_S=60`.
  - **Epic 2 (orchestrator, 3 stories):** `backend/workers/orchestrator.py` — `start_study` Arq job with short-lived sessions per tick, `pg_try_advisory_xact_lock` keyed by study_id for replenishment serialization, atomic durable digest handoff via pending proposal INSERT inside `complete_study` transaction, cancel-race tolerance, consecutive-failure detection (AC-5) ordered BEFORE max_trials so all-failed studies terminate as `failed` not `completed`, 30s `_drain_in_flight` on cancel; `resume_study` thin wrapper + `WorkerSettings.on_startup` sweep enqueuing resume for every running study AND start_study for every queued study (FR-5 / AC-4 + missed-enqueue recovery); `digest_stub.generate_digest` idempotent acknowledger; `WorkerSettings.functions` registers 4 jobs via `arq.func()` so only orchestrator jobs get 24h `timeout` and `run_trial` keeps Arq default.
  - **Epic 3 (API, 5 stories, 12 endpoints):** `/api/v1/query-templates` (POST/GET/GET, FR-2 + AC-7); `/api/v1/query-sets` (POST/GET/GET + bulk JSON/CSV upload, FR-3 + AC-8); `/api/v1/studies` (POST with key-omission `model_dump(exclude_none=True, exclude_unset=True)` + judgment_list↔query_set consistency + `ObjectiveSpec` model_validator requiring `k` for `ndcg`/`precision`/`recall`, GET list with typed `?status=StudyStatusWire` filter, GET detail with embedded `trials_summary`, POST cancel; FR-1 + AC-1/AC-3/AC-9); `/api/v1/studies/{id}/trials` (cursor + 5 sort variants + since, FR-6 + AC-10). All 12 spec §7.5 error codes covered.
  - **Epic 4 (docs):** `docs/03_runbooks/study-lifecycle-debugging.md` operator runbook.
  - **Tests:** 7 new unit (csv_parser) + 6 new integration test files (`test_study_lifecycle.py`, `test_study_cancel.py`, `test_study_resume.py`, `test_query_templates_api.py`, `test_csv_upload.py`, `test_studies_api.py`, `test_pagination.py`) + 2 new contract files. Integration tests use the `async_client` httpx + LifespanManager fixture from a new `tests/integration/conftest.py` (replaces sync TestClient to avoid nested-loop "Future attached to different loop" errors); autouse `_clean_phase2_tables` fixture wipes Phase 2 tables after each test.
  - **GPT-5.5 final review** (PR #25 adjudication summary comment): 4 cycles to convergence. Cycle 1 — 10 findings, 5 applied + 5 deferred to idea files. Cycle 2 — 3 new findings (broken `_job_timeout=` kwarg, bulk-update FR-7 bypass, missing `ObjectiveSpec` k-validator), all applied. Cycle 3 — 2 new findings (AC-5 priority over max_trials, untyped `?status=`), all applied. Cycle 4 — `{"findings": []}` clean pass.
  - Feature folder moved to [`docs/00_overview/implemented_features/2026_05_10_feat_study_lifecycle/`](docs/00_overview/implemented_features/2026_05_10_feat_study_lifecycle/).
- **2026-05-10 — `feat_study_lifecycle` Phase 2 plan approved.** Plan generated and reviewed via `/pipeline ... --auto`. 14 stories across 4 epics. **3 GPT-5.5 plan-review cycles**: 21 findings total — 19 accepted + applied, 1 rejected with cited counter-evidence (cycle-1 F2 — spec FR-3 says `cluster_id?` but Phase 1's schema is NOT NULL; captured as [`chore_spec_query_set_cluster_id_drift`](docs/02_product/planned_features/chore_spec_query_set_cluster_id_drift/idea.md) for spec patch).
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

- **`feat_digest_proposal`** on `feature/feat-digest-proposal` — 12 stories complete; PR pending. After merge, the queued list collapses to start with `feat_github_pr_worker`.

## Queued (priority-ordered by dependency)

1. **`feat_github_pr_worker`** — GitHub PR creation Arq job. (Now consumes the `proposals` shape that `feat_digest_proposal` populates.)
2. **`feat_github_webhook`** — `/webhooks/github` (idempotent, signature-verified).
3. **`feat_studies_ui`** — UI shell + `/studies` + `/studies/[id]`. Also lands the digest panel that consumes `GET /api/v1/studies/{id}/digest` shipped by `feat_digest_proposal`.
4. **`feat_chat_agent`** — streaming chat orchestrator.
5. **`feat_proposals_ui`** — `/proposals` review surface. Consumes the proposal CRUD endpoints `feat_digest_proposal` shipped (`GET /proposals`, `GET /proposals/{id}`, `POST /proposals`, `POST /proposals/{id}/reject`).
6. **`chore_tutorial_polish`** — sample data + walkthrough. Tutorial flow now has the `POST /judgment-lists/import` path it expects (FR-3b).
7. **`chore_judgments_periodic_resume_sweep`** — strategic in-worker resume sweeper (MVP1 ships boot-time sweep + REPL recovery only).

Run `/pipeline status` for the live view from spec dependencies.

## Known debt / fragility

- ~~**`backend/app/eval/qrels_loader.py` is an MVP1 stub.**~~ — **Resolved.** PR #35 replaced the stub with a real `SELECT query_id, doc_id, rating FROM judgments WHERE judgment_list_id = :id`. The legacy `JudgmentsTableMissing` symbol is retained as a no-op compat shim for any imported reference in older tests. Integration tests now seed real `judgments` rows; `run_trial` consumes the loader directly.
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
