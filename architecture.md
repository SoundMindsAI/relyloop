# RelyLoop — Architecture (one-screen pointer)

> Navigation hub for the topical architecture docs in [`docs/01_architecture/`](docs/01_architecture/). Read [`state.md`](state.md) for the active branch / what's just shipped, then use the table below to drill into the surface you need.

## High-level shape

RelyLoop is an **off-line** relevance-tuning tool for enterprise search
platforms. The architecture has four cooperating layers:

1. **Adapter** — a thin Protocol behind which engine differences
   (Elasticsearch / OpenSearch in MVP1; Apache Solr in MVP2) and LLM
   provider differences (OpenAI-compatible endpoints today; Anthropic /
   Bedrock / Vertex / Azure OpenAI in the backlog) are isolated.
2. **Domain** — pure Python (no I/O): study state machine, search-space
   rules, query rendering, evaluator helpers.
3. **Service** — orchestrators (study runner, judgment generation, digest,
   PR worker) that compose repos + domain + adapter calls.
4. **API + UI** — FastAPI routers + Next.js App Router; the API is the
   only surface external consumers (and the in-tool agent) use.

Every winning trial that survives the loop becomes a **Pull Request against
the operator's central search-config Git repo**. RelyLoop never sits on the
live search-serving path, never trains LTR models, never runs online A/B
tests, and never modifies cluster schema/mapping/analyzer settings.

## Topical architecture docs

| Doc | What it covers |
|---|---|
| [`mvp1-overview.md`](docs/01_architecture/mvp1-overview.md) | The MVP1 reading guide — start here if you're new |
| [`tech-stack.md`](docs/01_architecture/tech-stack.md) | Languages, frameworks, lockfiles, code organization, **canonical release matrix** |
| [`system-overview.md`](docs/01_architecture/system-overview.md) | Service inventory, how containers fit together |
| [`deployment.md`](docs/01_architecture/deployment.md) | Compose layout, secrets pattern, MVP1→GA v1 deployment evolution |
| [`api-conventions.md`](docs/01_architecture/api-conventions.md) | Endpoint conventions, error envelope, pagination, idempotency |
| [`data-model.md`](docs/01_architecture/data-model.md) | Per-table column-level reference; lineage; future audit_log |
| [`adapters.md`](docs/01_architecture/adapters.md) | The `SearchAdapter` Protocol shape |
| [`cluster-lifecycle.md`](docs/01_architecture/cluster-lifecycle.md) | What a "cluster" is, why registration probes, soft-delete + revival, the 6 cluster endpoints mapped to operator intent |
| [`llm-orchestration.md`](docs/01_architecture/llm-orchestration.md) | Capability check, function-calling, per-task LLM patterns |
| [`optimization.md`](docs/01_architecture/optimization.md) | Optuna sampler choice, RDBStorage, trial scheduling |
| [`ui-architecture.md`](docs/01_architecture/ui-architecture.md) | Next.js layout, streaming chat, server-state pattern |
| [`agent-tools.md`](docs/01_architecture/agent-tools.md) | The chat agent's tool registry contract |
| [`apply-path.md`](docs/01_architecture/apply-path.md) | How a winning config becomes a PR + how operator CI applies it |

## Critical flows (where to look in the topical docs)

- **First boot (`make up` → `make migrate` → `make seed-clusters` → `/healthz` 200):**
  [`deployment.md` §"MVP1 deployment shape"](docs/01_architecture/deployment.md)
  + [`infra_foundation` feature_spec.md §7.3](docs/00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md)
- **Cluster registration (POST /api/v1/clusters → adapter probe → DB insert):**
  [`backend/app/services/cluster.py`](backend/app/services/cluster.py) +
  [`docs/03_runbooks/cluster-registration.md`](docs/03_runbooks/cluster-registration.md)
- **OpenAI capability check at startup:**
  [`llm-orchestration.md` §"Capability check at startup"](docs/01_architecture/llm-orchestration.md)
- **Subsystem health probes (DB / Redis / ES / OpenSearch):**
  [`backend/app/api/probes.py`](backend/app/api/probes.py) — implementation;
  contract in [`infra_foundation/feature_spec.md`](docs/00_overview/planned_features/infra_foundation/feature_spec.md) §7.3
- **Settings + secrets pattern:**
  [`backend/app/core/settings.py`](backend/app/core/settings.py) +
  [`deployment.md` §"Secrets"](docs/01_architecture/deployment.md)
- **Alembic baseline / migration policy:**
  CLAUDE.md Absolute Rule #5; first revision in
  [`migrations/versions/0001_baseline.py`](migrations/versions/0001_baseline.py)

## Invariants (CLAUDE.md Absolute Rules cross-link)

These are the rules that the architecture is built around — every PR is
expected to honor them. The full text lives in [`CLAUDE.md`](CLAUDE.md):

1. **Never commit directly to `main`** — feature branches + PRs only.
2. **Secrets via mounted files** (`*_FILE` env vars), never bare env vars.
3. LLM calls go through the `BaseChatModel` abstraction once it lands
   (backlog item — native non-OpenAI provider SDKs); until then services
   may use the `openai` SDK directly but always read model + base URL
   from `Settings`.
4. **Engine-specific code lives only in `backend/app/adapters/<engine>.py`**
   — the orchestrator and study runner consume the unified `SearchAdapter`
   Protocol.
5. **All Alembic migrations include `downgrade()`** and round-trip cleanly.
6. `/healthz` is **unauthenticated by design** (operator probe, unprefixed).
7. Conventional Commits format is enforced via `pre-commit` `commit-msg`
   hook — never bypass with `--no-verify`.
8. **Never hardcode LLM model names** — read from `Settings.openai_model` /
   `Settings.openai_model_chat`.
9. **Never implement plan stories manually** — always use `/impl-execute`.
10. **Never log or expose secrets.**
11. **Per-route LLM/network calls inside `/healthz` respect the 200ms
    timeout** — capability check runs once at startup, not on every probe.

## Where the code lives

```
backend/
  app/
    api/         routers (health.py with /healthz + v1/clusters.py +
                 v1/{query_templates,query_sets,studies}.py from
                 feat_study_lifecycle Phase 2 + v1/judgments.py from
                 feat_llm_judgments + v1/proposals.py from
                 feat_digest_proposal (digest fetch + proposal CRUD;
                 feat_github_pr_worker adds POST /proposals/{id}/open_pr) +
                 v1/config_repos.py from feat_github_pr_worker (GitHub
                 config-repo CRUD) + future webhooks/*)
    core/        settings, logging, request-id middleware, error envelope
    db/          base, session,
                 models/ (Cluster, ConfigRepo from infra_adapter_elastic;
                  QueryTemplate, QuerySet, Query, Study, Trial,
                  JudgmentList, Proposal from feat_study_lifecycle Phase 1;
                  Judgment from feat_llm_judgments),
                 repo/ (cluster.py + config_repo.py +
                  query_template.py, query_set.py, query.py, study.py,
                  trial.py, judgment_list.py, proposal.py from Phase 1;
                  judgment.py from feat_llm_judgments)
    services/    use-case orchestrators — cluster.py from infra_adapter_elastic;
                 study_state.py (state machine + FR-7 protection listener,
                 feat_study_lifecycle Phase 2);
                 study_confidence.py (async glue that runs the 4-query
                 read pattern from feat_pr_metric_confidence FR-2 and
                 hands pre-fetched data to the pure orchestrator —
                 consumed by studies._detail, the open_pr worker, and
                 the digest worker)
    domain/      pure business logic — query/render.py from
                 infra_adapter_elastic; study/{search_space,template_validator,
                 csv_parser}.py from feat_study_lifecycle Phase 2;
                 study/confidence.py (feat_pr_metric_confidence —
                 ConfidenceShape Pydantic model + 7 sub-shapes + bootstrap
                 CI / runner-up gap / late-trial 1σ / convergence regime /
                 per-query outcome helpers; pure-Python orchestrator
                 returning None on every FR-7 degraded path);
                 study/followups.py (feat_digest_executable_followups —
                 FollowupItem discriminated union (narrow/widen/text/
                 swap_template) + parse_followup_list defensive ingest +
                 serialize_followup_list JSONB serializer +
                 truncate_validation_error head-and-tail truncator promoted
                 to public for the worker per Tier-B swap_template spec
                 D-33; the worker validates LLM payloads through this
                 module, downgrading invalid narrow/widen/swap_template
                 items to text);
                 study/template_swap.py (feat_digest_executable_followups_swap_template —
                 remap_search_space_for_swap_target + RemapResult: computes
                 trusted-intersection / disjoint-fill / dropped-parent /
                 ignored-LLM name sets, calls build_starter_search_space
                 ONLY when disjoint_fill is non-empty (cycle-1 F2 regression
                 guard), raises InvalidSearchSpaceError on empty swap
                 target / empty trusted intersection / cardinality blowup);
                 git/{redaction,validation}.py from feat_github_pr_worker
                 (GitHub PAT redaction + repo_url + config_path validators)
    adapters/    engine adapters — protocol.py (SearchAdapter Protocol +
                 8 Pydantic types), elastic.py (ES + OpenSearch),
                 credentials.py, errors.py, health_cache.py
    eval/        ir_measures scoring + Optuna runtime helpers (from
                 infra_optuna_eval): types.py (SamplerKind/PrunerKind/
                 TrialStatus Literals), scoring.py (score, frozensets,
                 objective_metric_key, wire-name translation),
                 optuna_runtime.py (build_storage / build_sampler /
                 build_pruner / get_or_create_study),
                 qrels_loader.py (real SELECT against judgments —
                 replaced the MVP1 stub when feat_llm_judgments landed),
                 calibration.py (Cohen's + linear-weighted kappa,
                 feat_llm_judgments Story 1.5)
    scripts/     operator entrypoints — seed_clusters.py
    llm/         OpenAI-compatible client + capability check
                 (capability_check.py / capability_models.py from
                 infra_foundation; openai_judge.py + cost_model.py +
                 budget_gate.py + prompt_loader.py from feat_llm_judgments;
                 digest_prompt.py from feat_digest_proposal)
    git/         Git provider clients (placeholder — feat_github_pr_worker
                 ships its git invocations inline in workers/git_pr.py
                 via the GIT_CONFIG_* env-var auth pattern; a thin
                 client wrapper lands here when feat_github_webhook
                 needs a shared GitHub REST client)
  workers/       Arq WorkerSettings + run_trial Arq job (trials.py from
                 infra_optuna_eval) + orchestrator.py (start_study /
                 resume_study, feat_study_lifecycle Phase 2) +
                 digest.py (generate_digest, feat_digest_proposal —
                 replaces the prior digest_stub.py) +
                 judgments.py (generate_judgments_llm, feat_llm_judgments) +
                 git_pr.py (open_pr, feat_github_pr_worker — token-safe
                 git via GIT_CONFIG_* env vars + per-config-repo
                 advisory lock + GitHub REST PR creation) +
                 on_startup/on_shutdown hooks that build/dispose Optuna
                 RDBStorage once per worker AND sweep running studies
                 for resume_study enqueue (FR-5 / AC-4) AND sweep
                 generating judgment lists for re-enqueue (cycle 2 F1)
                 AND sweep pending proposals lacking a digest for
                 generate_digest re-enqueue (feat_digest_proposal FR-2b)
  tests/         unit / integration / contract layers
prompts/         Jinja2 templates for LLM calls (feat_llm_judgments —
                 judgment_generation.system.md / .user.jinja / .rubric_v1.md;
                 feat_digest_proposal — digest_narrative.system.md / .user.jinja)
ui/              Next.js 16 App Router (post infra_frontend_stack_refresh):
                 src/app/clusters/ + studies/ + query-sets/ + templates/ +
                 judgments/[id]/ + page.tsx (dashboard) from feat_studies_ui;
                 src/app/proposals/ + proposals/[id]/ from feat_proposals_ui
                 (list page with URL-backed status filter + 30s pulse-refetch
                 + cursor pagination; detail page with config-diff +
                 metric-delta + suggested-followups + PrPanel 4-state branch
                 + RejectDialog + ?action=open_pr auto-trigger + 3s/30s
                 polling ladder). Shared primitives in src/components/common/
                 (StatusBadge / MetricDelta / CursorPaginator / EmptyState /
                 ParameterImportanceChart / DataTable — the latter from
                 feat_data_table_primitive consolidates 8 hand-rolled tables
                 onto @tanstack/react-table with co-located column configs at
                 src/components/<resource>/<table>-table.column-config.tsx +
                 page-level useDataTableUrlState hook for the URL contract);
                 per-resource hooks in src/lib/api/ (clusters, config-repos,
                 digests, judgments, proposals, query-sets, query-templates,
                 studies); canonical wire-value allowlists in src/lib/enums.ts.
migrations/      Alembic config + versions/ (0001 baseline + 0002 clusters
                 + 0003 study_lifecycle_schema + 0004_judgments + 0005_digests
                 + 0006 proposals_pr_url_idx + 0007 conversations_messages +
                 0008–0013 search_vector + GIN indexes from
                 feat_data_table_primitive + 0014 clusters_target_filter
                 from feat_cluster_target_filter + 0015 trials_per_query_metrics
                 from feat_pr_metric_confidence — nullable JSONB column +
                 CHECK constraint enforcing IS NULL OR jsonb_typeof = 'object'
                 + 0018 studies_parent_proposal + 0019 digests_suggested_followups_jsonb
                 from feat_digest_executable_followups — paired
                 studies.parent_proposal_id/parent_proposal_followup_index
                 columns with CHECK + partial index + BEFORE DELETE trigger
                 + digests.suggested_followups column-type change to JSONB
                 via PL/pgSQL helper functions)
docs/            00_overview / 01_architecture / 02_product / 03_runbooks /
                 04_security / 05_quality / 08_guides
```

### Dashboard regen

`scripts/build_mvp1_dashboard.py` regenerates `docs/00_overview/MVP1_DASHBOARD.md` + `mvp1_dashboard.html` (and the cross-release `DASHBOARD.md` + `dashboard.html`) from the planned-features and implemented-features folder tree. Triggered automatically by the `mvp1-dashboard-regen` pre-commit hook when a feature folder changes. **`**PR:**` frontmatter convention** (chore_dashboard_pr_extraction_from_idea, 2026-05-23): legacy idea-only implemented features that don't fit the natural `**Status:** **Shipped** as PR #N` / `**Status:** **Implemented — PR #N**` / line-start `**shipped YYYY-MM-DD as PR #N**` patterns may opt into PR# extraction by adding a `**PR:** #N` line to their idea.md metadata block (alongside `**Date:**`, `**Status:**`, etc.). Search is bounded to the metadata block (contiguous metadata-key lines stopping at the first `## ` heading or any non-blank non-metadata line, capped at 30 lines) — body-section references are intentionally ignored.

## Where this file fits

`architecture.md` is **the navigation pointer**, not the source of truth.
The topical docs in `docs/01_architecture/` are the source of truth for
their respective surfaces. Update this file only when:

- A new topical doc lands under `docs/01_architecture/`
- A new top-level layer arrives (e.g., `backend/app/git/` when
  `feat_github_pr_worker` ships)
- A new critical flow worth quick-linking lands

For per-feature design, read the feature's
`docs/00_overview/planned_features/<feature>/feature_spec.md`.
