# RelyLoop — Architecture (one-screen pointer)

> Navigation hub for the topical architecture docs in [`docs/01_architecture/`](docs/01_architecture/). Read [`state.md`](state.md) for the active branch / what's just shipped, then use the table below to drill into the surface you need.

## High-level shape

RelyLoop is an **off-line** relevance-tuning tool for enterprise search
platforms. The architecture has four cooperating layers:

1. **Adapter** — a thin Protocol behind which engine differences
   (Elasticsearch / OpenSearch / Lucidworks Fusion) and provider differences
   (OpenAI / Anthropic / Bedrock / Ollama / Vertex) are isolated.
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
| [`deployment.md`](docs/01_architecture/deployment.md) | Compose layout, secrets pattern, MVP1→MVP4 deployment evolution |
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
  contract in [`infra_foundation/feature_spec.md`](docs/02_product/planned_features/infra_foundation/feature_spec.md) §7.3
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
3. LLM calls go through the `BaseChatModel` abstraction once it lands at
   MVP4; until then services may use the `openai` SDK directly but always
   read model + base URL from `Settings`.
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
    api/         routers (health.py with /healthz + v1/clusters.py + future
                 webhooks/*)
    core/        settings, logging, request-id middleware, error envelope
    db/          base, session,
                 models/ (Cluster, ConfigRepo from infra_adapter_elastic;
                  QueryTemplate, QuerySet, Query, Study, Trial,
                  JudgmentList, Proposal from feat_study_lifecycle Phase 1),
                 repo/ (cluster.py + config_repo.py +
                  query_template.py, query_set.py, query.py, study.py,
                  trial.py, judgment_list.py, proposal.py from Phase 1)
    services/    use-case orchestrators — cluster.py from infra_adapter_elastic;
                 future ones arrive with their owning features
    domain/      pure business logic — query/render.py from
                 infra_adapter_elastic
    adapters/    engine adapters — protocol.py (SearchAdapter Protocol +
                 8 Pydantic types), elastic.py (ES + OpenSearch),
                 credentials.py, errors.py, health_cache.py
    eval/        pytrec_eval scoring + Optuna runtime helpers (from
                 infra_optuna_eval): types.py (SamplerKind/PrunerKind/
                 TrialStatus Literals), scoring.py (score, frozensets,
                 objective_metric_key, wire-name translation),
                 optuna_runtime.py (build_storage / build_sampler /
                 build_pruner / get_or_create_study),
                 qrels_loader.py (MVP1 stub raising JudgmentsTableMissing
                 — real impl lands with feat_llm_judgments)
    scripts/     operator entrypoints — seed_clusters.py
    llm/         OpenAI-compatible client + capability check
    git/         Git provider clients (lands with feat_github_pr_worker)
  workers/       Arq WorkerSettings + run_trial Arq job (trials.py from
                 infra_optuna_eval) + on_startup/on_shutdown hooks that
                 build/dispose Optuna RDBStorage once per worker
  tests/         unit / integration / contract layers
ui/              Next.js 14 App Router (placeholder page in MVP1)
migrations/      Alembic config + versions/ (0001 baseline + 0002 clusters
                 + 0003 study_lifecycle_schema)
docs/            00_overview / 01_architecture / 02_product / 03_runbooks /
                 05_quality / 08_guides
```

## Where this file fits

`architecture.md` is **the navigation pointer**, not the source of truth.
The topical docs in `docs/01_architecture/` are the source of truth for
their respective surfaces. Update this file only when:

- A new topical doc lands under `docs/01_architecture/`
- A new top-level layer arrives (e.g., `backend/app/git/` when
  `feat_github_pr_worker` ships)
- A new critical flow worth quick-linking lands

For per-feature design, read the feature's
`docs/02_product/planned_features/<feature>/feature_spec.md`.
