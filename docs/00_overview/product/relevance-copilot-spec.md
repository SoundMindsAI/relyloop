# RelyLoop — Internal Tool Specification

**Status:** Draft v0.1
**Date:** 2026-05-07
**Owner:** Relevance team
**Audience:** Engineers and stakeholders building or evaluating the tool

---

## 1. Summary

RelyLoop is an open-source tool for enterprise search platform teams. It combines a conversational LLM agent with an automated overnight optimization loop ("Karpathy loop") to systematically tune query-time search relevance on Elasticsearch, OpenSearch, and Lucidworks Fusion (with pure-Solr support deferred to v2). Engineers describe relevance problems in chat; the agent introspects the cluster, proposes search-space parameters, and queues thousands of trials against `ir_measures`-computed metrics. Winning configurations are surfaced as Pull Requests / Merge Requests against a central search-config Git repo, where named approvers review and merge them into production.

The tool is a single, engine-agnostic, provider-agnostic system: one UI, one workflow, one schema. Differences between Elasticsearch / OpenSearch, Lucidworks Fusion, and any future engine (pure Solr, Vespa, etc.) are isolated behind a thin adapter interface — and the same adapter pattern applies to LLM providers (OpenAI, Anthropic, Bedrock, Azure OpenAI, Vertex, self-hosted Ollama/vLLM) and Git providers (GitHub, GitLab, Bitbucket). Multi-tenancy is supported from the schema level so a single deployment can serve many downstream customers in isolation.

**Delivery is incremental across six releases**, each meaningful as a discrete capability bundle:

- **MVP1 / v0.1 (5 weeks) — "The Loop":** Karpathy loop end-to-end on a laptop. ES + OpenSearch, OpenAI, GitHub, single-tenant, basic logging. Demonstrates the value prop.
- **MVP1.5 / v0.1.5 (+2 weeks) — "Real Signals":** OpenSearch UBI as a first-class judgment source. `UbiReader` (engine-agnostic) + pluggable `SignalsConverter` Protocol + hybrid UBI+LLM mode. Earns the evaluation of operators with real traffic who distrust LLM-as-judge as the primary trust anchor.
- **MVP2 / v0.2 (+3 weeks) — "Observable":** Langfuse + SigNoz + event catalog + audit immutability + lineage columns + PII redaction. Trustworthy enough for serious evaluation.
- **MVP3 / v0.3 (+3 weeks) — "Production Stacks":** Lucidworks Fusion adapter (and its native signals reader feeding the MVP1.5 Protocol) + multi-Git provider abstraction (GitLab, Bitbucket) + adapter contract tests. Works against real enterprise stacks.
- **MVP4 / v0.4 (+3 weeks) — "Multi-tenant, Multi-LLM":** Tenants + tenant-scoped API keys + multi-LLM provider abstraction (Anthropic, Bedrock, Azure OpenAI, Vertex, Ollama/vLLM). Platform-team scale.
- **GA v1 / v1.0 (+3 weeks) — "Production-ready":** LangGraph orchestrator + full agent-first API surface + four-layer test pyramid + full GitHub Actions CI/CD with security gates + complete OSS governance.

Total: ~19 weeks single-engineer, 12–14 weeks with two. Each release ships a coherent step-up in adopter value and audience reach.

The HTTP API is designed as a first-class product, not just the back end of the UI. Every operation a human or the in-tool orchestrator can perform is also callable by an external agent over plain REST, with bearer-token auth, OpenAPI 3.1 publication, idempotency keys, outgoing webhooks, SSE event streams, and machine-readable capability discovery. See §21 *Agent integration*.

The orchestrator itself is built on **LangGraph** with Postgres-backed state persistence; LLM observability uses **self-hosted Langfuse**, distributed observability uses **self-hosted SigNoz**. Nothing about LLM behavior or system telemetry leaves the deployment VM. See §15 *LLM orchestration & observability*.

Engineering quality is gated by a four-layer test pyramid (unit ≥90% coverage, contract, integration, end-to-end) and GitHub Actions CI/CD. See §23 *Non-functional requirements*.

Released under **Apache License 2.0**. Initial maintainer: soundminds.ai, with an explicit transition path to community maintainership over 12–24 months. See §28 *OSS positioning & governance*.

## 2. Context & motivation

Search relevance tuning at our organization is currently manual, ad-hoc, and engineer-time-bound. A relevance engineer hypothesizes a change, edits a query template, eyeballs a few queries, and either ships it or doesn't. Two things are missing:

1. **Systematic exploration.** The space of tunable parameters (field weights, boosts, tie-breakers, fuzziness, slop, function-score parameters, hybrid-search alphas) is too large to explore manually. We routinely ship the first plausible win rather than the best win.
2. **Quantified evaluation.** Without a standing query set and judgment list, we can't tell whether a change generalizes or just happens to fix the three queries the engineer noticed.

Off-the-shelf tools (Quepid, RRE, Chorus) cover the manual workbench problem well but don't drive automated overnight studies, and don't have an LLM in the loop to design the search space. The OpenSearch Relevance Agent does the LLM-and-conversation part but is OpenSearch-only and lacks the autonomous-optimization loop. This tool combines both.

## 3. Goals

The tool must enable the relevance team to:

- Define a query set and a calibrated judgment list once, reuse them across studies
- Conversationally describe a relevance problem and have an agent propose what to tune
- Run automated, parallelized, overnight studies of thousands of trials per query set
- Produce a parameter-importance analysis and an LLM-written digest by morning
- Open a Git PR against a central search-config repo with the winning configuration
- Track which proposals are pending, merged, deployed, or rejected — across multiple clusters and environments
- Operate identically against Elasticsearch and Lucidworks Fusion clusters, with a path to add pure Solr, Vespa, or others later

## 4. Non-goals

The tool will not:

- Run online A/B tests on production traffic. It evaluates offline against judgment lists.
- Train Learning-to-Rank (LTR) models in v1. The output is query-time DSL/edismax parameter changes, not learned reranker weights.
- Manage the search-config repo's CI/CD. The tool opens PRs; the user's existing CI handles deployment.
- Make schema/mapping/analyzer changes. Tuning is restricted to query-time parameters.
- Function as a search-engine UI. It does not show end-user search results; it shows experiment results.
- Modify production cluster configuration directly. All changes flow through Git.
- Provide an MCP server. The tool's HTTP API uses OpenAPI 3.1 + idiomatic REST + outgoing webhooks instead, which is testable with any HTTP client and consumable by any agent framework. The same operations the in-tool orchestrator uses are exposed externally — there is no second-class agent interface.
- **Sit on the live search-serving path.** The tool is for offline experimentation and change management. It does not score, rank, or rerank production search results in real time, and it is never an inline dependency of the search-serving infrastructure. Production search behavior is determined by the configs that have been merged into the config repo and deployed by the operator's CI — the tool's role ends at the PR.
- **Provide real-time production search-quality monitoring.** Streaming user signals into rolling-window quality metrics, alerting on degradation, and incident dashboards belong to operational observability tooling (APM, Fusion's own analytics, custom Grafana boards). The tool is deliberately scoped to the experimentation-and-change-management problem; expanding into production monitoring is a coherent v2 direction (see §27) but is **not** in v1.
- **Provide shadow validation against a live production traffic stream.** Pre-deploy validation in v1 is offline against query sets and judgment lists, plus the optional read-only "validate on prod" pass already in §17. Streaming a sample of live queries through a candidate config in real time is more confidence-building but requires stream-processing infrastructure that v1 deliberately avoids.
- **Auto-rollback merged proposals based on real-time metrics.** Even if v2 adds production monitoring, auto-rollback is explicitly rejected. False positives are common, and auto-reverting deliberate human-approved changes breaks the change-management posture the tool is built around. v2 will surface alerts and a one-click manual rollback path; the human stays in the loop.
- **Bandit-style online learning / continuous deployment of mixture configs.** This is the most attractive v2 candidate (multi-armed bandits routing real production traffic across promising configs and progressively shifting toward winners) but is explicitly rejected for v1. It requires real-time integration into the search-serving path, which v1's architecture deliberately stays out of. Documented as a v2 direction in §27.

## 5. Glossary

- **Cluster** — a single Elasticsearch, Lucidworks Fusion, or Solr deployment (e.g., `products-prod-es`, `inventory-staging-fusion`).
- **Target** — a specific index (ES) or collection (Fusion / Solr) on a cluster, plus a query template. For Fusion, the target also implies a Fusion app and (default) query pipeline.
- **Query set** — a named, versioned collection of queries used as the input population for evaluation.
- **Judgment list** — for each (query, document) pair in scope, a relevance rating (0–3 or binary). Sourced from LLM-as-judge initially; human-overridable.
- **Query template** — a parametrized query definition (Jinja-rendered) for a specific engine. Has named parameters that match the search space.
- **Search space** — the set of parameters and their bounds that an Optuna study will explore.
- **Study** — one optimization run: a query set + judgment list + template + search space + objective metric. Produces trials and a digest.
- **Trial** — one parameter assignment from the optimizer + the metric it produced. Studies have hundreds to thousands of trials.
- **Proposal** — a candidate configuration change ready for a Git PR. Either auto-generated by a study digest or hand-crafted from chat.
- **Approver** — a named individual with permission to merge proposal PRs into the production branch of the config repo. Enforced in GitHub, not in this tool.

## 6. Personas & user stories

### Personas

- **Relevance Engineer (primary user).** Runs studies, reviews digests, opens proposals. Multiple per team.
- **Approver.** Subset of relevance engineers (or platform engineers) who hold merge rights on protected branches in the config repo. Cannot be bypassed.
- **Viewer.** Anyone with read access (PMs, exec stakeholders). Read-only on studies, proposals, dashboards.

### Top user stories

1. *As a relevance engineer*, I open chat and say "tune our product-name template against `qs_modelnums` overnight on staging-products-es," and by morning I have a digest with a recommended config and an open PR.
2. *As a relevance engineer*, I take a study run on staging and re-run the same parameters against prod (validation pass) before opening the PR, to confirm the win generalizes.
3. *As an approver*, I receive a Slack message linking to a PR with the parameter-importance chart, top-10 trials, and metric delta in the PR description; I review the diff and merge.
4. *As a relevance engineer*, I fork a completed study with narrowed search-space ranges to refine the winner.
5. *As a relevance engineer*, I spot-check 20 LLM-generated judgments and override 3, then re-run my study against the corrected list.
6. *As a viewer*, I look at the dashboard for `products-prod-es` and see the last 30 days of merged proposals with their metric improvements.

## 7. System architecture

```
                         ┌──────────────────────┐
                         │   Web UI (Next.js)   │
                         └──────────┬───────────┘
                                    │  HTTPS / SSE
                         ┌──────────▼───────────┐
                         │  API + Agent backend │   (FastAPI)
                         │  - Orchestrator agent│
                         │  - Tool registry     │
                         │  - Adapter dispatch  │
                         └─┬───────┬───────┬────┘
                           │       │       │
              ┌────────────┘       │       └──────────────┐
              │                    │                      │
     ┌────────▼────────┐  ┌────────▼─────────┐   ┌────────▼─────────┐
     │   Postgres      │  │   Redis (queue)  │   │   OpenAI API     │
     │   - app state   │  │   - Arq jobs     │   │   - GPT-4o tier  │
     │   - Optuna RDB  │  │                  │   └──────────────────┘
     └─────────────────┘  └────────┬─────────┘
                                   │
                   ┌───────────────▼────────────────┐
                   │   Worker pool (Arq)            │
                   │   - Trial workers (×N)         │
                   │   - Digest worker              │
                   │   - Git PR worker              │
                   └─┬───────────┬──────────┬───────┘
                     │           │          │
            ┌────────▼──┐  ┌─────▼────┐ ┌───▼────────┐
            │ Adapters  │  │ ir_      │ │ Git provider│
            │ - ES      │  │ measures │ │ - GitHub    │
            │ - Fusion  │  │          │ │ - PR API    │
            │ - (Solr)  │  │          │ │             │
            └─┬─────────┘  └──────────┘ └────────────┘
              │
   ┌──────────▼──────────────────────────┐
   │  Tuned clusters                     │
   │  - ES: products-prod, products-staging, products-dev
   │  - Fusion: inventory-prod, inventory-staging, ...
   └─────────────────────────────────────┘
```

### Service responsibilities

| Service | Responsibility |
|---|---|
| Web UI | Chat surface, study/proposal/cluster screens, judgment review, auth handoff |
| API + agent backend | HTTP API, OpenAI orchestration, tool dispatch, study lifecycle |
| Postgres | App state (studies, trials, proposals, etc.) + Optuna RDB storage |
| Redis | Task queue (Arq) for studies and digests |
| Worker pool | Trial execution (against tuned clusters via adapters), digest generation, Git PR creation |
| Adapters | Engine-specific query rendering and execution; everything else is engine-agnostic |
| ir_measures | Universal IR evaluation (nDCG, MAP, P@K, ERR) — provider-abstracted, wraps multiple backends |

The single deployment unit is a Docker Compose project. Workers scale horizontally via `docker compose up --scale worker=N`.

## 8. Engine adapter specification

The adapter layer is the entire surface where engine-specific logic lives. Everything else in the system is engine-agnostic.

### Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SearchAdapter(Protocol):
    engine_type: str  # "elasticsearch" | "opensearch" | "solr" | "lucidworks_fusion"

    def health_check(self) -> HealthStatus: ...
    def list_targets(self) -> list[TargetInfo]: ...
    def get_schema(self, target: str) -> Schema: ...
    def list_query_parsers(self) -> list[str]: ...

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery: ...

    def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        request_id: str | None = None,
    ) -> dict[str, list[ScoredHit]]: ...
    # returns {query_id: [ScoredHit(doc_id, score, _explain?), ...]}

    def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
    ) -> ExplainTree: ...
```

`search_batch` is the only hot-path method during a study. Everything else is define-time or debug-time.

### ElasticAdapter / OpenSearchAdapter

A single adapter handles both **Elasticsearch** and **OpenSearch**. The engine_type column distinguishes them at the database level (`elasticsearch` vs `opensearch`), and the adapter branches on that flag for the small set of behaviors that differ between the two engines. Reasons for one-adapter-two-engines:

- ES and OpenSearch share the same Query DSL — `multi_match`, `function_score`, `bool`, etc. work identically across both
- The `_msearch` and `_explain` endpoints exist on both with the same shape
- Engine-version differences (ES 9.x adds features, OpenSearch tracks ES 7.x semantics in some areas) are handled with minor version-aware branches
- A separate-adapter-per-engine approach would create near-duplicate code maintained in two places

Implementation notes:

- `search_batch` is implemented via the `_msearch` API for efficiency.
- `render` produces ES/OpenSearch Query DSL JSON; Jinja templates live under `templates/elasticsearch/` and work against both engines unmodified for the v1 query patterns.
- `explain` calls the `_explain` endpoint.
- Engine support: Elasticsearch 8.11+ and 9.x; OpenSearch 2.x (matches ES 7.10 baseline) and 3.x. Older versions explicitly out of scope.
- Authentication: ES uses API keys (or basic auth for older deployments); OpenSearch supports basic auth, API keys, and AWS SigV4 (when running in AWS managed OpenSearch). The adapter selects auth flow via `cluster.auth_kind`.

Why this matters for licensing and OSS positioning: Elasticsearch's Basic license is free for self-hosting but is not OSI-approved OSS. OpenSearch is Apache 2.0. Supporting both means RelyLoop adopters who care about the licensing distinction can choose OpenSearch without losing functionality, and adopters already on ES don't need to migrate.

### LucidworksFusionAdapter notes

The primary "Solr-side" adapter for v1. Lucidworks Fusion is built on Solr but exposes a different API surface centered on Query Pipelines. Pure-Solr deployments are supported architecturally (see SolrAdapter notes below) but are not in v1 scope.

- `search_batch` posts to Fusion's query API: `POST /api/apps/{app}/query/{collection}` with the request body holding query text and per-stage parameter overrides (`params.{stageId}.{paramName}`). Parallelism is handled with a small connection pool, similar to the Solr adapter.
- `render` produces a Fusion request body, **not** a raw Solr query. A "template" in Fusion is a query pipeline definition exported as JSON, plus a parameter-binding map that says which template parameters override which pipeline-stage parameters at request time. Rendering takes the pipeline definition + binding + parameter values and produces an override-laden Fusion request.
- `get_schema` queries Fusion's catalog API for the schema of the configured collection.
- `explain` uses Fusion's debug-enabled query (`params.solr.debugQuery=true`) and parses the `debug.explain` block returned through the Fusion gateway.
- **Authentication.** Fusion uses session-based auth (`POST /api/session` returning a session cookie) or JWT. The adapter manages a session pool; the `auth_kind` field on the cluster row distinguishes `fusion_session` vs `fusion_jwt`. Credentials referenced via the same `credentials_ref` pattern.
- **Pipeline export/import.** Apply path uses Fusion's `objects-export` and `objects-import` APIs (see §16). Pipeline JSON is the canonical Git artifact.
- **Signals** (v1.5+). Fusion's signals collections (`{app}_signals`) capture user click, view, and refinement events. The adapter exposes a `pull_signals` operation that returns aggregated signals over a window, suitable for click-derived judgment generation. Not on the v1 hot path because the user's deployment hasn't enabled signals yet.
- Supports Fusion 5.x (current). Fusion 4.x deferred until needed.

### SolrAdapter notes (architectural reference; not v1 scope)

Pure Apache Solr is supported by the same adapter pattern but is not built in v1 because the user's deployment is Lucidworks Fusion. The notes below describe what a SolrAdapter implementation would do, both as a future engine and as evidence that the architecture isn't Fusion-locked.

- `search_batch` is implemented via parallel `/select` requests, one per query, with a small connection pool. (Solr has no `_msearch` equivalent; the JSON Request API allows multi-query but is awkward.)
- `render` produces Solr query parameters as a dict (later URL-encoded); supports `lucene`, `edismax`, and `dismax` parsers.
- `explain` uses `debugQuery=true&debug=results` and parses the `debug.explain` block.
- Supports Solr 8.11+ and 9.x. SolrCloud and standalone both supported.
- Authentication via basic auth or API tokens.

### Cross-engine parameter naming

Each adapter maps a unified parameter vocabulary to native names. Templates use the unified names; rendering pivots them.

| Concept | Unified name | ES (`multi_match`) | Lucidworks Fusion | Solr (`edismax`) |
|---|---|---|---|---|
| Per-field weights | `field_boosts: {f: w}` | `fields: ["f^w"]` | stage param `searchFields.fields` or `params.solr.qf` override | `qf=f^w` |
| Phrase fields | `phrase_field_boosts` | nested `phrase` clause | `params.solr.pf` override | `pf` |
| Tie breaker | `tie_breaker` | `tie_breaker` | `params.solr.tie` override | `tie` |
| Min should match | `min_should_match` | `minimum_should_match` | `params.solr.mm` override | `mm` |
| Fuzziness | `fuzziness` | `fuzziness` | (manual via `~` in query parser) | (manual via `~`) |
| Slop | `slop` | `slop` | `params.solr.ps` override | `ps` |
| Boost function | `boost_fn: {field, type, params}` | `function_score` | boosting stage `bq` override | `boost`, `bf` |
| Reranker model | `rerank_model: {id, top_k}` | `rescore.window_size` + LTR | rerank stage `modelId`, `topK` | LTR plugin model |
| Pipeline stage toggle | `stage_enabled: {stage_id: bool}` | (n/a) | per-stage `enabled` param | (n/a) |

Where a concept doesn't exist natively (e.g., ES `function_score` rendered as Fusion `bq`), the adapter either provides a best-effort translation or raises `UnsupportedParameter` at render time and the search-space validator rejects the study before it runs. Fusion's `stage_enabled` parameter is unique to Fusion — it lets a study toggle individual pipeline stages on/off as a categorical parameter, which is a powerful and engine-specific tuning lever.

## 9. Data model (Postgres)

All tables use UUIDv7 primary keys (lexicographically sortable, time-ordered). Timestamps in UTC. Soft-delete via `deleted_at` on user-facing objects; hard-delete on internal trial records when retention expires.

### Core tables

```sql
-- Tenants — top-level isolation boundary for multi-tenant deployments
tenants (
    id              UUID PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,            -- "acme-corp", "internal-search-team"
    display_name    TEXT NOT NULL,
    settings        JSONB NOT NULL DEFAULT '{}',     -- per-tenant config (LLM provider override, cost cap, etc.)
    status          TEXT NOT NULL DEFAULT 'active', -- "active" | "suspended"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
-- Single-tenant deployments use a single row with name = "default" auto-created at install.

-- Cluster registry
clusters (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,                   -- "products-prod-es"
    engine_type     TEXT NOT NULL,                   -- "elasticsearch" | "opensearch" | "solr" | "lucidworks_fusion"
    environment     TEXT NOT NULL,                   -- "prod" | "staging" | "dev"
    base_url        TEXT NOT NULL,
    auth_kind       TEXT NOT NULL,                   -- "es_apikey" | "es_basic" | "opensearch_basic" | "opensearch_sigv4" | "solr_basic" | "fusion_session" | "fusion_jwt"
    credentials_ref TEXT NOT NULL,                   -- key into mounted secrets
    config_repo_id  UUID REFERENCES config_repos(id),
    config_path     TEXT NOT NULL,                   -- where in repo this cluster's templates live
    engine_config   JSONB,                           -- engine-specific settings (see below)
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);
-- engine_config shape per engine_type:
--   elasticsearch:    null or {api_version: "8" | "9"}
--   opensearch:       null or {os_version: "2" | "3"}
--   solr:             {solr_cloud: bool, default_collection: text}
--   lucidworks_fusion: {app: text, default_pipeline: text, signals_collection: text?, fusion_version: "5"}

-- Config repository registry
config_repos (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    provider        TEXT NOT NULL,                   -- "github" | "gitlab" | "bitbucket"
    repo_url        TEXT NOT NULL,
    default_branch  TEXT NOT NULL DEFAULT 'main',
    pr_base_branch  TEXT NOT NULL DEFAULT 'main',
    auth_ref        TEXT NOT NULL,                   -- token, app installation, or workspace credential ref
    webhook_secret_ref TEXT,                         -- secret used to verify incoming webhooks
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- Query templates
query_templates (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    engine_type     TEXT NOT NULL,
    body            TEXT NOT NULL,                   -- Jinja source
    declared_params JSONB NOT NULL,                  -- {param_name: type/range hints}
    version         INT NOT NULL DEFAULT 1,
    parent_id       UUID REFERENCES query_templates(id),  -- for forks
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Query sets
query_sets (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    description     TEXT,
    cluster_id      UUID REFERENCES clusters(id),    -- target cluster (judgments are cluster-specific)
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

queries (
    id              UUID PRIMARY KEY,
    query_set_id    UUID NOT NULL REFERENCES query_sets(id) ON DELETE CASCADE,
    query_text      TEXT NOT NULL,
    reference_answer TEXT,                           -- optional, for QA-style evaluation
    metadata        JSONB
);

-- Judgments
judgment_lists (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    query_set_id    UUID NOT NULL REFERENCES query_sets(id),
    description     TEXT,
    rubric          TEXT NOT NULL,                   -- the rubric used (LLM or human)
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

judgments (
    id              UUID PRIMARY KEY,
    judgment_list_id UUID NOT NULL REFERENCES judgment_lists(id) ON DELETE CASCADE,
    query_id        UUID NOT NULL REFERENCES queries(id),
    doc_id          TEXT NOT NULL,
    rating          SMALLINT NOT NULL,               -- 0-3
    source          TEXT NOT NULL,                   -- "llm" | "human" | "click"
    rater_ref       TEXT,                            -- model name or user id
    confidence      REAL,
    notes           TEXT,
    -- lineage (see §24)
    langfuse_trace_id TEXT,                          -- LLM call that produced this rating; null for human or click sources
    prompt_version  TEXT,                            -- short git SHA of prompts/ at call time
    input_hash      TEXT,                            -- SHA-256 of structured LLM input
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (judgment_list_id, query_id, doc_id)
);
```

### Study tables

```sql
studies (
    id                  UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    name                TEXT NOT NULL,
    cluster_id          UUID NOT NULL REFERENCES clusters(id),
    target              TEXT NOT NULL,               -- index or collection name
    template_id         UUID NOT NULL REFERENCES query_templates(id),
    query_set_id        UUID NOT NULL REFERENCES query_sets(id),
    judgment_list_id    UUID NOT NULL REFERENCES judgment_lists(id),
    search_space        JSONB NOT NULL,
    objective           JSONB NOT NULL,              -- {metric, k, direction}
    config              JSONB NOT NULL,              -- {max_trials, time_budget_min, parallelism, sampler, seed}
    status              TEXT NOT NULL,               -- queued|running|completed|cancelled|failed
    optuna_study_name   TEXT NOT NULL,
    parent_study_id     UUID REFERENCES studies(id), -- for forks
    baseline_metric     REAL,
    best_metric         REAL,
    best_trial_id       UUID,
    created_by          UUID NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ
);

trials (
    id              UUID PRIMARY KEY,
    study_id        UUID NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
    optuna_trial_number INT NOT NULL,
    params          JSONB NOT NULL,
    primary_metric  REAL,                            -- denormalized from `metrics` for fast sort; equals the study's objective metric
    metrics         JSONB NOT NULL,                  -- {ndcg@10: ..., map: ..., p@10: ...}
    duration_ms     INT,
    status          TEXT NOT NULL,                   -- complete | failed | pruned
    error           TEXT,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ
);

CREATE INDEX trials_study_metric ON trials (study_id, primary_metric DESC NULLS LAST);

digests (
    id                  UUID PRIMARY KEY,
    study_id            UUID NOT NULL REFERENCES studies(id) UNIQUE,
    narrative           TEXT NOT NULL,
    parameter_importance JSONB NOT NULL,
    recommended_config  JSONB NOT NULL,
    suggested_followups TEXT[],
    generated_by        TEXT NOT NULL,               -- LLM model name + version
    -- lineage (see §24)
    langfuse_trace_id   TEXT,
    prompt_version      TEXT,
    input_hash          TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Proposal tables

```sql
proposals (
    id                  UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    study_id            UUID REFERENCES studies(id),  -- null if hand-crafted from chat
    study_trial_id      UUID REFERENCES trials(id),  -- the specific winning trial that backs this proposal
    cluster_id          UUID NOT NULL REFERENCES clusters(id),
    template_id         UUID NOT NULL REFERENCES query_templates(id),
    config_diff         JSONB NOT NULL,              -- {param: {from, to}}
    metric_delta        JSONB,                       -- {ndcg@10: {baseline, achieved, delta_pct}}
    status              TEXT NOT NULL,
    -- pending → pr_opened → pr_merged → deployed
    -- or:     → rejected (user cancelled before PR)
    pr_url              TEXT,
    pr_state            TEXT,                        -- mirror of GitHub: open | closed | merged
    pr_merged_at        TIMESTAMPTZ,
    rejected_reason     TEXT,
    -- lineage (see §24)
    langfuse_trace_id   TEXT,                        -- digest trace, when proposal originated from a study
    prompt_version      TEXT,
    created_by          UUID NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Auxiliary tables

```sql
users (
    id              UUID PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE, -- can create tenants, manage all
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A user can belong to multiple tenants with different roles in each.
tenant_memberships (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    role            TEXT NOT NULL,                   -- "viewer" | "runner" | "tenant_admin"
    scopes          TEXT[],                          -- optional further narrowing of runner role
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id)
);

-- API keys for service accounts; tenant-scoped
api_keys (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    owning_user_id  UUID NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL,                   -- Argon2id
    role            TEXT NOT NULL,                   -- "viewer" | "runner"
    scopes          TEXT[] NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

audit_log (
    id              UUID PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),     -- null for platform-level events (tenant CRUD, user CRUD)
    actor_id        UUID REFERENCES users(id),       -- null for system actor
    actor_type      TEXT NOT NULL,                   -- user | system | agent
    action          TEXT NOT NULL,                   -- study.start, proposal.pr_opened, ...
    object_type     TEXT NOT NULL,
    object_id       UUID NOT NULL,
    payload         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

conversations (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                   -- user | assistant | tool
    content         JSONB NOT NULL,
    tool_calls      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Optuna's RDB schema lives alongside in the same Postgres instance under its own schema (`optuna.*`).

## 10. Query templates

Templates are Jinja2 source files. Storage: rows in `query_templates`, body is the Jinja text. Templates declare their parameters explicitly (`declared_params` JSONB), which the search-space validator checks against.

### Example: ES template

```jinja
{
  "size": {{ top_k | default(10) }},
  "query": {
    "multi_match": {
      "query": "{{ query_text }}",
      "fields": [
        "title^{{ field_boosts.title }}",
        "body^{{ field_boosts.body }}"
        {% if field_boosts.tags %}, "tags^{{ field_boosts.tags }}"{% endif %}
      ],
      "tie_breaker": {{ tie_breaker }},
      "type": "best_fields",
      "fuzziness": "{{ fuzziness }}"
    }
  }
}
```

### Example: Lucidworks Fusion template (Query Pipeline override)

A Fusion template stores the pipeline definition as a versioned blob in the config repo (canonical source of truth) and a Jinja-rendered request body that supplies parameter overrides at request time. The pipeline itself is unchanged by tuning — only its parameters at request time vary.

```jinja
{
  "params": [
    {"name": "q",                          "value": "{{ query_text }}"},
    {"name": "rows",                       "value": {{ top_k | default(10) }}},
    {"name": "params.solr.qf",             "value": "title^{{ field_boosts.title }} body^{{ field_boosts.body }}{% if field_boosts.tags %} tags^{{ field_boosts.tags }}{% endif %}"},
    {"name": "params.solr.tie",            "value": "{{ tie_breaker }}"},
    {"name": "params.solr.mm",             "value": "{{ min_should_match | default('2<-25%') }}"},
    {"name": "params.solr.ps",             "value": "{{ slop | default(0) }}"}
    {% if rerank_model and rerank_model.id %},
    {"name": "params.rerank.modelId",      "value": "{{ rerank_model.id }}"},
    {"name": "params.rerank.topK",         "value": "{{ rerank_model.top_k | default(50) }}"}
    {% endif %}
    {% for stage_id, enabled in stage_enabled.items() %},
    {"name": "params.{{ stage_id }}.enabled", "value": "{{ enabled }}"}
    {% endfor %}
  ]
}
```

This is dispatched via `POST /api/apps/{app}/query/{collection}` with the rendered body. The pipeline definition itself (the stages, their default parameters) lives in `pipeline.json` alongside the template — versioned together so a study is reproducible against a known pipeline shape.

### Example: Solr template (edismax) — reference for future engine support

```jinja
{
  "defType": "edismax",
  "qf": "title^{{ field_boosts.title }} body^{{ field_boosts.body }}{% if field_boosts.tags %} tags^{{ field_boosts.tags }}{% endif %}",
  "tie": "{{ tie_breaker }}",
  "mm": "{{ min_should_match | default('2<-25%') }}",
  "ps": "{{ slop | default(0) }}",
  "q": "{{ query_text }}",
  "rows": {{ top_k | default(10) }}
}
```

All three templates declare parameters using the unified vocabulary (`field_boosts.*`, `tie_breaker`, `min_should_match`, `slop`, etc.). Engine-unique parameters like `fuzziness` (ES) and `stage_enabled` (Fusion) are declared per template. The search space references these names.

### Authoring & versioning

- Templates are authored in the UI (Monaco editor) or imported from the config repo.
- Versioning: every save creates a new row with `parent_id` pointing to the previous version. Existing studies reference a specific version, so they remain reproducible.
- Validation on save: the template is rendered with stub parameters and dispatched to the matching adapter for syntax check before commit.

## 11. Search space & parameters

Search-space JSON shape (stored in `studies.search_space`):

```json
{
  "field_boosts.title":     {"type": "float", "low": 0.5, "high": 10.0, "log": true},
  "field_boosts.body":      {"type": "float", "low": 0.5, "high": 5.0},
  "field_boosts.tags":      {"type": "float", "low": 0.0, "high": 3.0, "step": 0.25},
  "tie_breaker":            {"type": "float", "low": 0.0, "high": 1.0},
  "fuzziness":              {"type": "categorical", "choices": ["AUTO", "0", "1", "2"]},
  "slop":                   {"type": "int", "low": 0, "high": 5}
}
```

Supported parameter types map directly to Optuna's distributions:

| Type | Optuna call | Notes |
|---|---|---|
| `float` | `suggest_float(low, high, log=...)` | `log=true` for boost-like params |
| `int` | `suggest_int(low, high, step=...)` | |
| `categorical` | `suggest_categorical(choices)` | |
| `bool` | `suggest_categorical([true, false])` | sugar |

Conditional parameters (parameter B only sampled if A is set) are deferred to v2.

The search-space validator runs at study-creation time:

1. All declared parameter names must appear in the template's `declared_params`.
2. All template parameters must be either declared in the search space or have a default value.
3. The adapter must support all parameters via its parameter vocabulary (raises `UnsupportedParameter` if not).
4. Parameter ranges must be non-empty and well-typed.

## 12. Study lifecycle

### States

```
queued → running → completed
            ↓
         cancelled
            ↓
          failed
```

- `queued`: created but not yet picked up by orchestrator.
- `running`: orchestrator has started workers; trials are flowing into the trial table.
- `completed`: stop condition met (max trials or time budget); digest job kicked off.
- `cancelled`: user-initiated cancellation; in-flight trials drained, partial results retained.
- `failed`: catastrophic error (DB unreachable, all workers crashed); manual investigation.

### Phase to state mapping

| Phase | State transition | Components touched |
|---|---|---|
| Define | (none — pre-creation) | UI, agent backend |
| Create | (none) → `queued` | API, Postgres |
| Enqueue | `queued` → `running` | Orchestrator, Redis, Postgres |
| Execute | `running` (steady) | Workers, Optuna RDB, Postgres trials |
| Stop | `running` → `completed` | Orchestrator |
| Digest | `completed` (with digest row) | Digest worker, OpenAI, Postgres |
| Proposal | (proposal row created) | Digest worker → Git PR worker |

## 13. Optuna integration

- **Storage:** `RDBStorage` with the same Postgres instance (separate schema, `optuna`).
- **Sampler:** TPE (`TPESampler`) by default. CMA-ES (`CmaEsSampler`) selectable for studies with ≥7 continuous parameters and no categoricals. Random sampler available for baseline runs.
- **Pruner:** `MedianPruner` with `n_warmup_steps=10` to kill obviously-bad trials early. Studies smaller than 50 trials disable pruning.
- **Parallelism:** N workers all share an Optuna study via the RDB storage. Each worker calls `study.ask()` / `study.tell()` independently. RDB locking handles concurrency.
- **Reproducibility:** seed is stored on the study; reruns of the same study with the same seed are deterministic up to RDB ordering effects.
- **Stop conditions:** the orchestrator is responsible for stopping. Workers respect a `study.should_stop()` poll that checks Postgres `studies.status` (cancelled or completed).
- **Multi-objective:** v2. v1 supports a single scalar objective.

## 14. Evaluation

### Engine: provider-abstracted IR evaluation via `ir_measures`

Workers always evaluate via `ir_measures`, never `_rank_eval`. This guarantees identical metric semantics across ES, Fusion, and Solr, and simplifies cross-engine comparisons. Reasoning:

- `ir_measures` (from the PyTerrier team) wraps multiple IR-evaluation backends behind a typed metric-object DSL (`nDCG@10`, `AP@5`, `RR`, `P@k`, `R@k`). The provider abstraction means swapping the underlying backend is a config change rather than a rewrite — protecting against future single-maintainer abandonment risk.
- ES `_rank_eval` and `ir_measures` don't always agree to many decimal places (different normalization conventions across engines).
- Per-query scores are inspectable, enabling deep debugging.

### Supported metrics

Primary metrics, all computed at trial time:

- `ndcg@k` (default k=10, configurable per study)
- `map`
- `precision@k`
- `recall@k`
- `mrr`
- `err@k`

Studies declare a single primary objective; secondary metrics are recorded in the trial row for analysis but don't drive optimization in v1.

### Judgment formats

Stored as `{judgment_list_id, query_id, doc_id, rating, source}` tuples. Ratings in `0..3` (graded) or `0..1` (binary). `ir_measures` is configured per metric to handle each.

The `source` field tracks judgment provenance:

- `llm` — generated by an LLM-as-judge call against a documented rubric
- `human` — entered or overridden by a relevance team member via the UI
- `click` — derived from real user behavior data (OpenSearch UBI primarily; engine-native streams where present)

A judgment list can mix sources. The Judgment Review UI surfaces source per row and the calibration stats account for source mix.

### Click-derived judgments — OpenSearch UBI as the engine-neutral primary path (MVP1.5)

**User Behavior Insights** is a standardized, engine-neutral schema (championed by Eric Pugh / OpenSource Connections) for capturing search events. The OpenSearch UBI plugin (2024) writes two indices into the cluster being tuned:

- `ubi_queries` — the searches users issued: query text, client ID, session ID, application, requested filters, response time, hit count.
- `ubi_events` — what users did next: click, view, dwell, add-to-cart, conversion, refinement; each event references a `query_id` from `ubi_queries`.

Because UBI is just two indices in the cluster RelyLoop is already adapting, the integration is engine-agnostic: a new `UbiReader` reads UBI indices via the existing `SearchAdapter.search_batch` and aggregates raw events into per-(query, doc) interaction features:

- click count
- impression count
- click-through rate (with position-bias correction)
- post-click dwell-time mean
- conversion rate (where the operator emits conversion events)
- query-refinement rate

The pluggable `SignalsConverter` then maps these features to a 0–3 rating. Initial converters: position-bias-corrected CTR threshold, dwell-time threshold, and **hybrid UBI+LLM** (UBI rates the dense head; LLM-as-judge fills the long tail for queries below an impression threshold). Counterfactual click models (CCM, DBN) are documented as v1.5+ post-GA extensions because they need enough impressions per (query, doc) to be statistically meaningful.

The judgments table accepts mixed-source lists today (the `source IN ('llm', 'human', 'click')` CHECK has shipped since MVP1) — no schema migration is required to turn this on. The MVP1.5 deliverable is the `UbiReader` + `SignalsConverter` + a new `POST /api/v1/judgment-lists/generate-from-ubi` endpoint + a new `generate_judgments_from_ubi` agent tool. See [`feat_ubi_judgments/idea.md`](../../02_product/planned_features/feat_ubi_judgments/idea.md) for the planned-feature scope.

Predicated on the operator having installed the OpenSearch UBI plugin and logged enough events to be statistically useful. Deployments without UBI continue to run LLM-as-judge unchanged.

**Engine-native readers as a drop-in extension.** Operators on engines that haven't adopted UBI but have their own behavioral-data stream — Elastic Behavioral Analytics for ES clusters, the Fusion `{app}_signals` collection for Fusion clusters — get a thin engine-specific reader feeding the same `SignalsConverter` Protocol. Reader work is local to the adapter that ships it (the Fusion reader rides MVP3 alongside the Fusion adapter; the ES Behavioral Analytics reader rides v2). The converter library, the API surface, and the storage shape are unchanged across all readers.

### LLM-as-judge

Initial judgment lists are generated by an LLM. The agent has a `generate_judgments_llm` tool:

- Input: query, retrieved hits (top 50 from current production query), rubric.
- Process: each (query, doc) is scored 0–3 with rationale. Calls are batched and parallelized.
- Output: judgments written to a new `judgment_lists` row with `source = "llm"`.

Rubric is stored on the judgment list. Re-generating with a changed rubric creates a new list (immutable).

### Calibration

Before a judgment list is used in an authoritative study, the relevance team should:

1. Sample 30–50 (query, doc) pairs uniformly.
2. Hand-label them, overriding the LLM rating where wrong.
3. Compute Cohen's kappa or Krippendorff's alpha between LLM and human.
4. If agreement is poor (<0.6), revisit the rubric.

The Judgment Review UI surfaces this workflow as a guided flow. A `judgment_list.calibration` JSONB field records the agreement statistics.

## 15. LLM orchestration & observability

The LLM-driven parts of the system — the orchestrator agent, the hypothesis-generation and evaluation subagents, judgment generation, search-space proposal, digest narrative — share a common stack. The decisions in this section are deliberate, not implementation defaults; they shape what's in `requirements.txt`, what services run in Docker Compose, and how the team debugs LLM behavior.

The whole stack is **local-first**: every component runs on your VM, no LLM trace data leaves your network for observability or evaluation purposes.

### Orchestration framework: LangGraph

LangGraph is the orchestration framework. The agent is modeled as a state graph rather than as a long system prompt with ad-hoc tool calls.

```
                  ┌─────────────────────────┐
                  │      Orchestrator       │
                  │  (router + tool node)   │
                  └────┬───────────┬────────┘
                       │           │
              ┌────────▼──┐   ┌────▼───────────┐
              │ Hypothesis│   │   Evaluation   │
              │   Gen     │   │    subagent    │
              │ subagent  │   │                │
              └────┬──────┘   └────┬───────────┘
                   │                │
              ┌────▼────────────────▼─┐
              │   Tool nodes          │
              │ - clusters/templates  │
              │ - studies/trials      │
              │ - judgments/proposals │
              │ - run_query / eval    │
              └───────────────────────┘
```

Nodes consume and emit a typed `AgentState` (Pydantic model) covering: conversation history, current cluster/template/study context, intermediate hypothesis candidates, in-flight tool results.

**State persistence** uses LangGraph's `PostgresSaver` against the same Postgres instance Optuna uses. Conversations are resumable across server restarts, replayable for debugging, and produce an automatic audit trail. The `conversations` and `messages` tables in §9 become a thin compatibility view over LangGraph's checkpoint tables.

**Human-in-the-loop interrupts** are used at three points:

- Before opening a Pull Request (`proposal.open_pr` confirmation)
- Before starting a study against a production cluster (vs. staging)
- Before regenerating a judgment list with a different rubric (overwrites existing data)

### LLM client: pluggable `ChatModel` adapter

Different enterprises have different LLM constraints — AWS shops use Bedrock, Microsoft shops use Azure OpenAI, GCP shops use Vertex, regulated shops use self-hosted models (Ollama, vLLM, LocalAI), and many are explicitly multi-provider. The tool treats LLM provider as a pluggable adapter, not a fixed dependency.

LangChain's `BaseChatModel` is the protocol. Out-of-the-box providers shipped in v1:

| Provider | Package | Notes |
|---|---|---|
| OpenAI | `langchain-openai` | Direct OpenAI; ZDR enrollable |
| Anthropic | `langchain-anthropic` | Direct Anthropic; supports Claude family |
| AWS Bedrock | `langchain-aws` | Anthropic Claude, Amazon Titan, Cohere — all behind one credential |
| Azure OpenAI | `langchain-openai` (Azure mode) | Same `ChatOpenAI` shape with Azure endpoint |
| Google Vertex AI | `langchain-google-vertexai` | Gemini models, AWS-equivalent regional control |
| Self-hosted (Ollama, vLLM) | `langchain-community` Ollama / `langchain-openai` (OpenAI-compatible mode) | Air-gapped deployments |

Selection is per-deployment via config:

```yaml
llm:
  provider: openai          # openai | anthropic | bedrock | azure_openai | vertex | ollama
  model: gpt-4o-2024-08-06  # provider-specific model name, version-pinned
  parameters:
    temperature: 0.0        # default for evaluation tasks
    max_tokens: 4096
  fallback:                 # optional secondary provider for rate-limit/outage failover
    provider: anthropic
    model: claude-sonnet-4-5-20250929
```

The application code only sees `BaseChatModel`; nothing references a specific provider directly. The provider selection happens once at startup; switching providers is a config change.

**What's required of every provider:**

- Native tool/function calling support (table stakes)
- `with_structured_output(PydanticModel)` for guaranteed JSON shape — used for `propose_search_space`, `generate_judgments_llm`, and the digest's recommended-config payload
- Configurable retries and timeouts
- Token streaming for chat responses
- A way to enumerate cost per call (for Langfuse cost dashboards)

Self-hosted providers (Ollama/vLLM) often have weaker tool-calling support; the spec validates the chosen provider supports structured outputs at startup and refuses to start if not. A capability matrix is published in the docs so adopters can pick a model that works.

**Model version pinning.** All persisted artifacts that depend on LLM behavior capture the model identifier as a string, including the provider prefix. `judgments.rater_ref` records `openai:gpt-4o-2024-08-06` or `bedrock:anthropic.claude-sonnet-4-5-v1`; `digests.generated_by` does the same. Floating tags (`gpt-4o`, `claude-sonnet-latest`) are forbidden in production code; CI rejects PRs that use them.

### Tool definitions: `@tool` as single source of truth

```python
from langchain_core.tools import tool
from pydantic import BaseModel

class CreateStudyRequest(BaseModel):
    name: str
    cluster_id: UUID
    target: str
    template_id: UUID
    query_set_id: UUID
    judgment_list_id: UUID
    search_space: SearchSpace
    objective: Objective
    config: StudyConfig

@tool(args_schema=CreateStudyRequest)
def create_study(...) -> Study:
    """Create and start a new optimization study against a cluster, query set, and judgment list."""
    ...
```

This single decorator yields:

- A LangChain tool the orchestrator can route to
- An OpenAI function-calling JSON schema (for `/tools.json`)
- An OpenAPI fragment (FastAPI auto-generates from the same Pydantic model)
- A type-checked Python signature for direct callers

Tools used by the in-tool orchestrator and tools exposed externally are identical. This delivers on the agent-first symmetry §21 commits to.

### Prompt management

Prompts live in `prompts/` in the repo, versioned with code:

```
prompts/
  search_space_proposal.system.md
  search_space_proposal.user.jinja
  judgment_generation.system.md
  judgment_generation.user.jinja
  judgment_generation.rubric_v3.md         # rubric stored alongside, version in name
  digest_narrative.system.md
  digest_narrative.user.jinja
  hypothesis_subagent.system.md
  evaluation_subagent.system.md
  orchestrator.system.md
```

Loaded at startup, rendered with Jinja per call. The repo is canonical. Langfuse independently captures the rendered prompt sent for each call (so you can see exactly what was sent at run time), but the version stored in Git is what gets reviewed in PRs.

### Caching

LangChain's `RedisCache` against the Redis we already use for the queue. Cacheable operations and TTLs:

- `propose_search_space` keyed on (template_id, cluster_id, query_set_id) — TTL 24h
- `generate_judgments_llm` keyed on (query_id, doc_id, rubric_hash, model_version) — TTL 7 days
- `get_schema` results keyed on (cluster_id, target) — TTL 1 hour

Not cached: orchestrator chat completions (depend on conversation state), digest narratives (run once per study), hypothesis generation (depends on study context).

The cost-impact lever is the judgment generation cache: a 200-query × 50-doc judgment regeneration costs ~$5–15 at OpenAI rates without caching. With caching, re-runs after small rubric tweaks become near-free.

### LLM observability: Langfuse (self-hosted)

[Langfuse](https://langfuse.com/self-hosting) is the LLM-specific observability tool. Self-hosted via Docker Compose; no LLM trace data leaves the VM.

What it captures:

- Every LLM call: rendered prompt, response, token counts, latency, cost
- Every chain/graph run: tool calls, intermediate states, errors, full hierarchy
- Per-conversation traces with parent/child relationships
- Prompt versions with diff view (Langfuse pulls the version captured at call time; repo remains canonical)
- Datasets + eval runs

Integration is one line per agent invocation:

```python
from langfuse.callback import CallbackHandler

handler = CallbackHandler(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    host="http://langfuse-web:3000",
)

graph.invoke(state, config={"callbacks": [handler]})
```

LangChain/LangGraph runs are auto-captured. Workers add the same handler to digest and judgment-generation calls.

Deployment adds three containers: `langfuse-web`, `langfuse-worker`, `clickhouse` (Langfuse uses ClickHouse for trace storage). Modest footprint — roughly 2 GB of memory total at expected scale.

**Eval datasets in Langfuse.** The LLM-critical operations get dedicated eval datasets:

- `search_space_proposal_eval` — 30 hand-crafted (template, cluster, problem statement) → expected-search-space pairs. Run via Langfuse experiments before any model upgrade.
- `judgment_generation_eval` — 200 (query, doc, rubric) → human-labeled rating tuples. Compute Cohen's kappa per model version; flag drops below 0.6.
- `digest_quality_eval` — 20 (study, expected key insights) pairs; LLM-judge scores narratives against a rubric.

Eval suite runs nightly and on every prompt change. Failures block prompt PRs.

### Distributed observability: SigNoz (self-hosted)

[SigNoz](https://signoz.io/) is the general distributed observability tool. Self-hosted via Docker Compose; OpenTelemetry-native by design. Replaces Prometheus + Loki + Tempo + Grafana with a single tool offering equivalent coverage.

What it captures:

- **Distributed traces** — auto-instrumentation for FastAPI, Postgres (asyncpg), Redis, OpenAI client, httpx (for adapter calls)
- **Metrics** — Prometheus-compatible exposition; SigNoz scrapes existing `/metrics` endpoints
- **Logs** — structured JSON ingestion via OTLP

Service maps and RED dashboards (Rate, Errors, Duration) come out of the box. Alerting is built in.

Instrumentation:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

FastAPIInstrumentor.instrument_app(app)
AsyncPGInstrumentor().instrument()
RedisInstrumentor().instrument()
```

OTLP exporter pointed at `http://signoz-otel-collector:4317`. One configuration block, three observability dimensions.

**Key spans worth instrumenting explicitly:** `trial.execute`, `agent.tool_call`, `digest.generate`, `adapter.search_batch`, `git.open_pr`. **Key metrics:**

- `relyloop_studies_total{status}`
- `relyloop_trials_duration_seconds` (histogram)
- `relyloop_trials_failed_total{reason}`
- `relyloop_pr_state_total{state}`
- `relyloop_openai_tokens_total{kind}`
- `relyloop_optuna_ask_duration_seconds`

W3C Trace Context (`traceparent`) is propagated through to ES / Fusion, so distributed traces span the full agent → API → engine boundary.

### How they fit together

```
Agent backend
  ├── LangGraph runs ──→ Langfuse (prompts, traces, costs, evals)
  └── HTTP / DB / queue ops ──→ OTLP ──→ SigNoz (traces, metrics, logs)

Workers
  ├── Trial executions ──→ OTLP ──→ SigNoz
  └── Digest LLM calls ──→ Langfuse handler (also OTLP for surrounding spans)

Adapters → ES / Fusion
  └── HTTP spans ──→ OTLP ──→ SigNoz (with traceparent propagated)
```

Two URLs to point services at. Two UIs to look at. Both running on the same VM as the rest of the system.

### Why not the alternatives

- **LangSmith** — best-in-class for LangGraph debugging but hosted-only. Fails the local-first requirement.
- **Phoenix (Arize)** — solid open-source LLM observability, but Langfuse's prompt management and cost dashboards are more polished for the workflows the team will lean on hardest.
- **Pure Grafana stack** (Prometheus + Loki + Tempo + Grafana) — works fine, but four containers to wire together and four UIs to operate. SigNoz pays for itself in onboarding time on a single-VM Docker Compose deployment.
- **Helicone self-hosted** — primarily SaaS; the self-hosted path is less mature.

## 16. Apply path: Git PR workflow

### Config repo conventions

The user nominates a Git repo (one or more) that holds canonical search-config files. Each cluster row references one repo and a path within it:

```
search-configs/
  products-prod-es/
    templates/
      product_search.yaml      ← canonical template + locked param values
      product_search.yaml.params.json
  products-staging-es/
    templates/
      product_search.yaml
      product_search.yaml.params.json
  inventory-prod-fusion/
    pipelines/
      product_search_pipeline.json
      product_search_pipeline.params.json
    profiles/
      product_search.profile.json
```

The `*.params.json` file holds the production parameter values that the deployment pipeline injects into the template at deploy time. **The tool only edits `*.params.json`; it does not edit templates themselves.**

This matters because:

- Template changes are structural (new fields, new clauses) and need engineer judgment in code review.
- Parameter changes are scalar and safely automatable.
- The PR diffs are small and reviewable.

### Engine-specific apply path details

**Elasticsearch.** The `*.params.json` file is read by the user's deployment pipeline and injected into the index template / search application configuration at deploy time. The tool does not interact with the cluster directly during apply.

**Lucidworks Fusion.** Fusion's pipelines are versioned objects in Fusion's own catalog, so the apply path is two-step:

1. Tool edits `*.params.json` and (where the change is large enough to warrant a new pipeline version) commits an updated `pipeline.json` to the same path. PR is opened.
2. After PR merge, the user's CI runs Fusion's `objects-import` API (or `fusion-cli`) to push the updated pipeline into Fusion. The tool does **not** push to Fusion directly — same principle as the ES case, the tool stops at the PR and CI handles deployment.

The conventions we recommend for the config repo when targeting Fusion:

```
search-configs/
  products-prod-fusion/
    pipelines/
      product_search_pipeline.json     ← canonical pipeline definition
      product_search_pipeline.params.json ← what the tool edits
    profiles/
      product_search.profile.json      ← optional: query profile binding
```

CI should verify that `pipeline.json` plus `params.json` together produce a valid Fusion pipeline before importing. A small validator script using Fusion's pipeline-validate API is recommended.

### PR creation flow

When a study completes and a digest produces a recommended config:

1. Git PR worker clones (or pulls) the config repo.
2. Creates a branch `relyloop/study-{study_id}` off the cluster's `pr_base_branch`.
3. Edits the `*.params.json` for the relevant template+cluster.
4. Commits with a structured message:

```
relevance: tune product_search params (study stu_01HXYZ)

Cluster: products-prod-es
Template: product_search v3
Metric: nDCG@10  0.612 → 0.762 (+24.5%)

Top params:
  field_boosts.title:  2.5 → 4.7
  tie_breaker:         0.1 → 0.34
  fuzziness:           "0" → "AUTO"

Study run by: alice@co
Trial count: 2000
Run duration: 7h 42m
Best trial: tri_01HXYZ_0987
```

5. Pushes branch.
6. Calls the Git provider's PR-or-MR API to open a pull request (or merge request). PR body includes:
   - Link back to the study in RelyLoop UI
   - Parameter importance chart (rendered as a PNG, attached as a comment)
   - Top-10 trials table (markdown)
   - Baseline vs achieved metrics table
   - Suggested follow-up studies
7. Stores `pr_url` and `pr_state = "open"` on the proposal row.

### Git provider abstraction

The Git provider is a pluggable adapter, not a hardcoded GitHub integration. The protocol:

```python
class GitProvider(Protocol):
    provider_type: str   # "github" | "gitlab" | "bitbucket"

    def clone_or_pull(self, repo: ConfigRepo) -> Path: ...
    def create_branch(self, base: str, name: str) -> str: ...
    def commit_files(self, files: dict[str, str], message: str) -> str: ...
    def push_branch(self, branch: str) -> None: ...
    def open_pull_request(self, title: str, body: str, base: str, head: str, draft: bool) -> PullRequest: ...
    def get_pull_request(self, pr_id: str) -> PullRequest: ...
    def list_codeowners(self, path: str) -> list[str]: ...   # who must review changes to this path

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent: ...   # provider-specific parsing
```

**v1 ships three implementations:**

| Provider | Auth | Webhook format | Approval mechanism |
|---|---|---|---|
| GitHub | App installation or PAT | GitHub webhook signature | CODEOWNERS + branch protection |
| GitLab | Project access token or app | GitLab webhook token | CODEOWNERS + merge-request approvals |
| Bitbucket | App password or workspace token | Bitbucket webhook UUID | Default reviewers + branch restrictions |

The `config_repos` table picks up a `provider` column (already present from earlier rev — confirmed `config_repos.provider`); the API adapts accordingly. Webhook endpoints are per-provider: `/webhooks/github`, `/webhooks/gitlab`, `/webhooks/bitbucket`.

### State tracking

`proposals.pr_state` is updated by:

- **Webhook** when the config repo is configured to send webhooks to the matching `/webhooks/{provider}` endpoint. The Git provider adapter parses provider-specific events into a normalized `WebhookEvent` shape.
- **Polling fallback** every 15 minutes if webhooks aren't configured.

State transitions:

```
pending  →  pr_opened (PR created)
pr_opened  →  pr_merged (someone merges)
pr_opened  →  rejected (PR closed without merge)
pr_merged  →  deployed (out of band: user's CI deploys; we don't track this in v1)
```

`deployed` state is aspirational in v1 — we don't have a reliable signal that downstream CI succeeded. Treat `pr_merged` as "the part RelyLoop is responsible for is done."

### Why we delegate approval to the Git provider

The "named approvers only" governance answer is implemented entirely in the Git provider's branch / merge protection rules — required reviewers (GitHub CODEOWNERS, GitLab approval rules, Bitbucket default reviewers + branch permissions). This means:

- The list of approvers lives in the config repo, not in this tool's config.
- Adding/removing approvers is a Git operation, not a tool-config operation.
- The tool can't be bypassed by anyone with API access.

The tool only enforces "who can *open* a PR" (any user with `runner` role + `proposals:write` scope on the relevant tenant).

## 17. Multi-tenancy, multi-cluster, multi-env

### Tenants

The top-level isolation boundary is the **tenant**. A tenant scopes everything a user-facing operation touches: clusters, query sets, judgment lists, templates, studies, proposals, conversations, audit log entries, API keys, costs.

**Single-tenant deployments** (the common case for an internal platform team) install with one tenant named `default` auto-created at first startup. Users and operations don't think about tenants explicitly — the UI hides the tenant context, the API has a `default` fallback, and it feels like the tool isn't multi-tenant at all.

**Multi-tenant deployments** (a search-services vendor or a platform team running for many customers) create one tenant per downstream customer. Each tenant gets:

- Its own clusters, query sets, judgment lists, templates, studies, proposals — fully isolated namespaces
- Its own user roster and roles (a person can be `runner` in tenant A and `viewer` in tenant B)
- Its own API keys, scoped exclusively to that tenant
- Its own cost tracking (LLM spend rolled up per tenant)
- Its own audit log view
- Optional per-tenant settings overrides (e.g., a different LLM provider, a different cost cap, a different default sampler)

There is one global role, `platform_admin`, held by a small set of people who can create tenants, manage users across tenants, and access platform-level audit events. Within each tenant, roles are `viewer | runner | tenant_admin`.

The reverse-proxy / SSO flow places the user into the tenant context they last used; an explicit tenant switcher in the UI lets multi-tenant users move between tenants. API requests carry tenant context via either:

- The `X-Tenant-ID` header (for service accounts whose API key is multi-tenant — uncommon; usually a key is bound to one tenant)
- Implicit from the API key's tenant binding (the common case)
- Implicit from the SSO session's last-active tenant

API keys default to single-tenant binding. Multi-tenant keys are an admin-only feature primarily for cross-tenant monitoring agents (which only need read access).

### Cluster registry

The `clusters` table holds every cluster the tool can talk to, scoped by tenant. Each cluster has an `environment` and points to a `config_repo` + `config_path`. Examples in a multi-tenant deployment:

| tenant | name | engine | env |
|---|---|---|---|
| acme-corp | products-prod-es | elasticsearch | prod |
| acme-corp | products-staging-es | elasticsearch | staging |
| acme-corp | inventory-prod-fusion | lucidworks_fusion | prod |
| beta-co | search-prod-fusion | lucidworks_fusion | prod |
| beta-co | search-staging-fusion | lucidworks_fusion | staging |
| internal-platform | docs-prod-es | elasticsearch | prod |

In single-tenant deployments the `tenant` column is implicit (always `default`), and the cluster name is the unique identifier on its own.

### Promotion path

The tool's natural workflow is:

1. **Tune on staging.** Studies run against the staging cluster. Trials hit real staging data without risk.
2. **Validate on prod (read-only).** Once a study identifies a winning config, the agent offers a "validate on prod" option: run the same query set + judgments + winning params against the prod cluster (read-only `_msearch` calls), confirm the metric holds.
3. **Open PR against staging's params file.**
4. **Once merged and deployed to staging**, manual or scripted promotion to prod (out of scope for this tool — handled by the user's existing CI/CD or manual ops).

The tool does **not** own the staging→prod promotion path. It only confirms reads against prod look comparable and opens the PR for the staging change. Promotion is a separate change, the user's responsibility.

### Cross-cluster studies

In v1, a study targets exactly one cluster. v1.5 may add "fan-out studies" that evaluate the same params against multiple clusters in parallel, useful when you want a single config that works for both prod-EU and prod-US. Out of scope for v1.

## 18. Governance & permissions

### Roles

Roles are tenant-scoped — a person's role applies within a specific tenant. A user can hold different roles in different tenants (`runner` in `acme-corp`, `viewer` in `beta-co`).

Three tenant-level roles:

- **viewer** — read-only access to studies, proposals, dashboards within the tenant. Cannot start studies or open PRs.
- **runner** — everything viewer can do, plus: start/cancel studies, edit query sets and templates, generate judgments, open PRs. Optional `scopes` further narrow what a runner can do.
- **tenant_admin** — everything runner can do, plus: manage clusters, manage tenant memberships, manage config repos within the tenant, view tenant audit log.

One platform-level role outside the tenant model:

- **platform_admin** — can create and delete tenants, manage users globally, view platform-level audit events. Held by a small set of operators (e.g., the platform team itself in a multi-tenant deployment). In a single-tenant install, the first user provisioned at startup is auto-promoted.

There is **no "approver" role in this tool**. Approval is enforced in the config repo's branch protection / merge protection rules. CODEOWNERS (GitHub), approval rules (GitLab), or default reviewers (Bitbucket) determine who must review what.

### Auth

There are two authentication paths, deliberately separated so that human and agent traffic can be governed independently.

**Human users** sign in via SSO (OIDC against Google, Okta, etc.) handled by a reverse proxy (oauth2-proxy or Authelia) in front of the API. The proxy injects authenticated user identity in headers (`X-Auth-Email`); the API trusts those headers only when they originate from the proxy (verified by mTLS or a shared secret).  First-time users are auto-provisioned with `viewer` role; an `admin` promotes them.

**Service accounts and agents** authenticate with bearer API keys via the standard `Authorization: Bearer <key>` header. Keys are issued by an admin via the UI or `POST /api/v1/api-keys`, and have the following properties:

- A name and an owning user (the human responsible for the key)
- A role: `viewer` | `runner` (admins are not exposable via API key in v1 — admin operations require a logged-in human)
- Optional **scopes** that further narrow what a `runner` key can do: `studies:read`, `studies:write`, `proposals:read`, `proposals:write`, `clusters:read`, `judgments:write`, `chat:write`. A key without explicit scopes inherits everything its role allows.
- An expiration timestamp (default 90 days, configurable, max 1 year)
- A revocable status — admins can revoke immediately

Every API key request writes to the audit log with `actor_type = "agent"` and the key's owning-user as `actor_id`. The audit row also records the API key ID so revocation forensics work.

The reverse proxy terminates TLS but does **not** intercept `Authorization: Bearer` headers — those pass through to the API service unchanged.

### Audit log

Every state-changing operation writes to `audit_log`. Log lines for proposals:

```
{
  actor_id: "alice@co",
  action: "proposal.create",
  object_type: "proposal",
  object_id: "pro_01H...",
  payload: { study_id: "stu_01H...", cluster_id: "..." },
  created_at: "..."
}
```

Audit log is append-only. Retention: 2 years (configurable).

## 19. Agent tools

The orchestrator agent in the API backend uses OpenAI function calling. Tool inventory for v1:

### Cluster & schema

- `list_clusters()` → `[ClusterSummary]`
- `get_cluster(cluster_id)` → `ClusterDetail`
- `get_schema(cluster_id, target)` → `Schema`
- `list_query_parsers(cluster_id)` → `[str]`

### Fusion-specific (Fusion clusters only)

- `list_pipelines(cluster_id)` → `[PipelineSummary]` — list query pipelines available in the Fusion app
- `get_pipeline(cluster_id, pipeline_id)` → `PipelineDefinition` — full pipeline JSON with stages
- `list_query_profiles(cluster_id)` → `[QueryProfileSummary]`
- `pull_signals(cluster_id, since, until?, query_filter?)` → `SignalsAggregate` — *(MVP3, requires Fusion Signals enabled)* aggregate raw Fusion `{app}_signals` events into per-(query, doc) interaction features. Engine-specific reader feeding the shared `SignalsConverter` Protocol introduced at MVP1.5; see §14 "Click-derived judgments from user behavior data".

### Templates

- `list_templates(engine_type?)` → `[TemplateSummary]`
- `get_template(template_id)` → `TemplateDetail`
- `validate_template(engine_type, body, declared_params)` → `ValidationResult`

### Query sets & judgments

- `list_query_sets()` → `[QuerySetSummary]`
- `create_query_set(name, queries[])` → `QuerySet`
- `import_queries_from_csv(query_set_id, csv_data)` → `int`
- `generate_judgments_llm(query_set_id, cluster_id, target, current_template_id, rubric)` → `JudgmentList`
- `generate_judgments_from_ubi(query_set_id, cluster_id, target, since, until?, converter, llm_fill_threshold?)` → `JudgmentList` — *(MVP1.5, requires OpenSearch UBI plugin)* read `ubi_queries` + `ubi_events`, aggregate per-(query, doc) features via `UbiReader`, run the named `SignalsConverter`, and (optionally) fill the long tail with LLM-as-judge when impression count < `llm_fill_threshold`. Emits a judgment list with mixed `source` rows (`click` + optional `llm`). See §14.
- `get_calibration(judgment_list_id)` → `CalibrationStats`

### Search space proposal

- `propose_search_space(template_id, cluster_id, target, query_set_id, observations?)` → `SearchSpaceProposal`
- `validate_search_space(template_id, search_space)` → `ValidationResult`

### Studies

- `create_study(name, cluster_id, target, template_id, query_set_id, judgment_list_id, search_space, objective, config)` → `Study`
- `get_study(study_id)` → `StudyDetail`
- `cancel_study(study_id)` → `Study`
- `fork_study(study_id, narrowed_search_space?, name?)` → `Study`

### Quick experiments (interactive, before going to a full study)

- `run_query(cluster_id, target, query_dsl)` → `[Hit]`
- `run_pairwise(cluster_id, target, query_a, query_b, query_text)` → `PairwiseResult`
- `run_rank_eval(cluster_id, target, template_rendered, query_set_id, judgment_list_id, metric)` → `EvalResult`

### Proposals & PRs

- `list_proposals(filter?)` → `[ProposalSummary]`
- `get_proposal(proposal_id)` → `ProposalDetail`
- `create_proposal_from_study(study_id)` → `Proposal`
- `create_proposal_manual(cluster_id, template_id, config_diff)` → `Proposal`
- `open_pr(proposal_id)` → `Proposal`  (transitions to pr_opened)

## 20. API surface

REST + JSON. SSE for streamed agent responses and study lifecycle events. All endpoints under `/api/v1`.

The API is the public surface for both the in-tool orchestrator and any external agent — there is no internal-only path. See §21 for the conventions that make this surface agent-friendly (idempotency, pagination, errors, OpenAPI publication, capability discovery, outgoing webhooks).

```
# Health, meta, discovery
GET    /health
GET    /me                                       # current principal (user or service account)
GET    /openapi.json                             # OpenAPI 3.1 spec
GET    /capabilities                             # machine-readable feature/cluster/template inventory
GET    /tools.json                               # OpenAI-function-calling-style tool definitions

# API keys (admin only)
GET    /api-keys                                 [admin]
POST   /api-keys                                 [admin]
DELETE /api-keys/{id}                            [admin]

# Clusters
GET    /clusters
POST   /clusters                                 [admin]
GET    /clusters/{id}
GET    /clusters/{id}/schema?target={t}

# Templates
GET    /templates?engine={e}
POST   /templates                                [runner]
GET    /templates/{id}
POST   /templates/{id}/validate

# Query sets & judgments
GET    /query-sets
POST   /query-sets                               [runner]
GET    /query-sets/{id}
GET    /query-sets/{id}/queries
POST   /query-sets/{id}/queries
POST   /judgments/generate                       [runner]
GET    /judgment-lists/{id}
PATCH  /judgments/{id}                           [runner]   # human override

# Studies
GET    /studies?status=&cluster_id=
POST   /studies                                  [runner]
GET    /studies/{id}
POST   /studies/{id}/cancel                      [runner]
POST   /studies/{id}/fork                        [runner]
GET    /studies/{id}/trials?cursor=&limit=
GET    /studies/{id}/digest
GET    /studies/{id}/events                      # SSE stream: lifecycle, trial counts, current best metric

# Proposals
GET    /proposals?status=&cluster_id=&cursor=&limit=
GET    /proposals/{id}
POST   /proposals/{id}/open-pr                   [runner]
POST   /proposals/{id}/cancel                    [runner]
GET    /proposals/{id}/events                    # SSE stream: pr_state changes

# Chat
POST   /conversations
POST   /conversations/{id}/messages              # SSE response
GET    /conversations/{id}/messages

# Webhook subscriptions (outgoing — for external agents)
GET    /webhook-subscriptions                    [runner]
POST   /webhook-subscriptions                    [runner]
DELETE /webhook-subscriptions/{id}               [runner]

# Webhooks (incoming — from GitHub)
POST   /webhooks/github
```

## 21. Agent integration

The same HTTP API serves human users (via the Web UI), the in-tool orchestrator agent, and any external agent. The conventions below make that single surface usable by agents without an MCP server, a custom protocol, or special-cased "agent endpoints."

### Auth model

Service accounts authenticate with bearer API keys (see §18 *Auth*). A typical agent provisioning flow:

1. Admin creates a service account user representing the agent (e.g., `nightly-tuner@svc`)
2. Admin issues an API key bound to that service account, with role `runner` and scopes `studies:write`, `proposals:write`, `chat:write`
3. The key is dropped into the agent's secret store (Vault, K8s secret, env var, etc.)
4. Agent sets `Authorization: Bearer <key>` on every request

Multiple keys per service account are supported for rotation.

### Discovery

Three endpoints let an agent learn what the API can do without out-of-band documentation:

- **`GET /api/v1/openapi.json`** — full OpenAPI 3.1 spec, generated from FastAPI. Every endpoint has an `operationId`, parameter and response schemas, descriptions written for agent consumption (not just human readers), and at least one example request/response.

- **`GET /api/v1/capabilities`** — a high-level inventory:

  ```json
  {
    "version": "1.0.0",
    "engines_supported": ["elasticsearch", "lucidworks_fusion"],
    "clusters": [
      {"id": "...", "name": "products-prod-es", "engine_type": "elasticsearch", "environment": "prod"},
      ...
    ],
    "templates_count": 12,
    "query_sets_count": 8,
    "samplers_supported": ["TPESampler", "CmaEsSampler", "RandomSampler"],
    "metrics_supported": ["ndcg", "map", "precision", "recall", "mrr", "err"],
    "default_objective": {"metric": "ndcg", "k": 10},
    "feature_flags": {"prod_validation": false, "multi_objective": false}
  }
  ```

- **`GET /api/v1/tools.json`** — OpenAI-function-calling-format definitions for every meaningful operation. Same information as OpenAPI, in a shape agents can hand directly to their LLM. Example:

  ```json
  [
    {
      "type": "function",
      "function": {
        "name": "create_study",
        "description": "Create and start a new optimization study against a cluster, query set, and judgment list.",
        "parameters": { "$ref": "https://relyloop/api/v1/openapi.json#/components/schemas/CreateStudyRequest" }
      }
    },
    ...
  ]
  ```

### Idempotency

All state-changing endpoints (`POST`, `PATCH`, `DELETE`) accept an `Idempotency-Key: <string>` header. The server stores the (key, request_hash, response) tuple for 24 hours. A repeat call with the same key returns the original response. A repeat call with the same key but a different request body returns `409 Conflict` with `error_code = idempotency_mismatch`.

Recommended pattern for agents: generate a UUIDv7 idempotency key per logical operation; reuse it on retries within the conversation; never reuse across logically different operations.

### Pagination

List endpoints use cursor-based pagination:

```
GET /studies?status=running&cursor=eyJ...&limit=50
```

Response envelope:

```json
{
  "items": [...],
  "next_cursor": "eyJ...",     // null when exhausted
  "limit": 50
}
```

Cursors are opaque, server-issued, and stable across paginated reads.

### Errors

All errors follow [RFC 7807 Problem Details](https://datatracker.ietf.org/doc/html/rfc7807) with two extension fields:

```json
{
  "type": "https://relyloop/errors/cluster-unreachable",
  "title": "Cluster unreachable",
  "status": 502,
  "detail": "Could not reach cluster 'products-prod-es' at the configured base URL. Last successful health check: 2026-05-07T03:11:42Z.",
  "instance": "/api/v1/studies",
  "error_code": "cluster_unreachable",
  "retryable": true
}
```

`error_code` is a stable, kebab-case enum (documented in OpenAPI). `retryable` tells the agent whether a backoff retry is appropriate (`true` for transient infrastructure issues, `false` for validation errors and permission failures).

### Outgoing webhooks

Agents that don't want to poll subscribe to events. A subscription:

```json
POST /api/v1/webhook-subscriptions
{
  "url": "https://my-agent/relyloop-events",
  "secret": "shared-hmac-secret",
  "events": ["study.completed", "digest.generated", "proposal.pr_opened", "proposal.pr_merged"]
}
```

Event payload (POSTed to the subscriber):

```json
{
  "event": "study.completed",
  "delivered_at": "2026-05-07T11:42:01Z",
  "data": {
    "study_id": "stu_01H...",
    "name": "Model-number boost tuning",
    "status": "completed",
    "best_metric": 0.762,
    "trial_count": 2000
  }
}
```

Each request includes `X-RelyLoop-Signature: sha256=<hmac>` computed over the body using the subscription's `secret`. Subscribers must verify before processing. Retries on 5xx with exponential backoff up to 24 hours; deliveries beyond that are dropped and surfaced in the subscription's failure log.

Event catalog (v1):

| Event | Payload focus |
|---|---|
| `study.created` | new study, ready to run |
| `study.started` | first trial recorded |
| `study.completed` | stop condition met, digest pending |
| `study.cancelled` | user cancellation |
| `study.failed` | catastrophic failure |
| `digest.generated` | digest written, recommended config available |
| `proposal.created` | proposal row created |
| `proposal.pr_opened` | PR opened, includes PR URL |
| `proposal.pr_merged` | PR merged in config repo |
| `proposal.rejected` | PR closed without merge |
| `judgment_list.created` | new list available |

### SSE streams

For sub-second-granularity progress, an agent can stream:

- `GET /api/v1/studies/{id}/events` — emits status changes, `trial.completed` ticks (sampled — every Nth trial in busy studies), parameter-importance updates as they're computed.
- `GET /api/v1/proposals/{id}/events` — emits PR state transitions.
- `POST /api/v1/conversations/{id}/messages` — emits agent reasoning and tool-call results during chat (already present).

Standard SSE format (`event:` + `data:` lines, JSON payloads).

### Observability

Agents can pass through W3C Trace Context:

```
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
```

The API and workers honor and propagate it, so distributed traces span the agent → API → ES/Fusion boundary. `X-Request-ID` is also accepted and echoed in responses.

Rate-limit headers are present on every response:

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 832
X-RateLimit-Reset: 1715090400
```

### A reference workflow

The expected sequence for an external agent that wants to tune a query template end-to-end:

```
1. GET  /capabilities                              → discover clusters, engines, samplers
2. GET  /clusters                                  → pick a target
3. GET  /templates?engine=elasticsearch            → pick a template (or POST to create one)
4. GET  /query-sets                                → pick a query set (or POST to create one)
5. POST /judgments/generate                        → if no judgment list exists for the query set
        with Idempotency-Key
6. POST /studies                                   → create study
        with Idempotency-Key                       (or POST /tools/propose-search-space first)
7. SSE  /studies/{id}/events                       → wait for `study.completed`
        OR poll GET /studies/{id}
        OR webhook on study.completed
8. GET  /studies/{id}/digest                       → fetch recommended config
9. POST /proposals/{id}/open-pr                    → create proposal + open PR
        with Idempotency-Key
10. SSE /proposals/{id}/events                     → wait for `pr_merged`
        OR webhook on proposal.pr_merged
```

This sequence is documented as a worked example in the published OpenAPI spec under the `x-agent-workflows` extension.

### Why no MCP

MCP is the right answer when you want zero-config integration with MCP-aware clients (Claude Desktop, Cursor, etc.) and don't want to write an HTTP client per consumer. For this tool's scope — an internal product with a known set of agent consumers and significant existing HTTP tooling — the simpler answer is OpenAPI 3.1 + REST + outgoing webhooks. We get:

- A wire format every agent framework already speaks
- Trivial testability (`curl`, Postman, Insomnia)
- A single source of truth (OpenAPI) that generates tool-definition JSON, client SDKs, and human-readable docs
- No protocol-version coupling to the MCP ecosystem

If a strong reason emerges later — e.g., an internal team building on Claude Code wants drop-in MCP support — an MCP server can be added as a thin facade over this same HTTP API without changing the API contract. Out of scope for v1; deliberately not on the v1.5 plan.

## 22. UI screens

Implemented as a Next.js single-page app. Top-level routes:

| Route | Screen | Purpose |
|---|---|---|
| `/` | Dashboard | Recent studies, open proposals, key metrics across clusters |
| `/chat/{conversation_id}` | Chat | Primary agent interaction surface |
| `/clusters` | Clusters list | Cluster registry, health, recent activity |
| `/clusters/{id}` | Cluster detail | Studies and proposals scoped to cluster |
| `/query-sets` | Query Sets | CRUD and import |
| `/query-sets/{id}` | Query Set detail | Queries, associated judgment lists |
| `/judgments/{id}` | Judgment Review | LLM ratings with override UI, calibration stats |
| `/templates` | Templates list | All templates by engine |
| `/templates/{id}` | Template editor | Monaco editor + declared params |
| `/studies` | Studies list | Filter by status, cluster, owner |
| `/studies/{id}` | Study detail | Live progress, trials table, digest, parameter importance, fork button |
| `/proposals` | Proposals list | Filter by status, cluster, PR state |
| `/proposals/{id}` | Proposal detail | Diff view, metric delta, PR link, audit trail |
| `/audit` | Audit log | [admin] |

## 23. Non-functional requirements

This section defines the system-level qualities the v1 build must satisfy, separate from the feature-level requirements above. Each subsection lists targets, validation methods, and what gets gated in CI.

### Performance

| Operation | Target |
|---|---|
| API p50 latency (non-LLM endpoints) | < 100 ms |
| API p99 latency (non-LLM endpoints) | < 500 ms |
| Trial execution per query (200-query set) | < 300 ms |
| Study lifecycle: define → first trial recorded | < 5 s |
| Chat first-token latency (orchestrator) | < 2 s |
| OpenAPI spec serving | < 50 ms |

LLM-call latency is passthrough — the tool adds no meaningful overhead beyond OpenAI's own SLAs. SLOs measured via SigNoz's RED dashboards.

Performance regressions are not actively gated in CI in v1 (no perf-test suite). v1.5 to add `pytest-benchmark`-based regression checks for the trial-execution hot path.

### Scalability

Sized for the relevance team (5–10 engineers, ~10–30 concurrent studies):

| Resource | Target |
|---|---|
| Concurrent active studies | 30 |
| Trial parallelism per study | up to 16 |
| Total concurrent trial workers | 100 |
| Query set size | up to 5,000 queries |
| Judgments per list | up to 1,000,000 (5,000 queries × 200 docs) |
| Active conversations | 200 |
| External agents calling API | 50 RPS |

Scale ceilings hold on the recommended single-VM deployment (8 vCPU / 32 GB RAM, plus the +4 GB observability overhead). Beyond that, the natural scale-out is sharding workers across multiple VMs — out of scope for v1.

### Availability & reliability

This is an internal tool used during business hours; targets reflect that.

- **Uptime SLO**: 99.5% during business hours (08:00–18:00 in the team's primary timezone). ~2.5 h/month allowed downtime.
- **Out-of-hours uptime**: 99% (background studies should still run; observability stack can be down).
- **Worker crash recovery**: trial state never lost. In-flight trial reissued by Optuna; persisted trials remain.
- **Graceful degradation**:
  - Langfuse down → LLM calls still succeed; observability traces queue locally and replay.
  - SigNoz down → spans buffer in OTel collector; metrics best-effort.
  - GitHub API down → proposal stays in `pending`; PR worker retries with backoff.
  - Single ES/Fusion target down → studies on that target fail; others unaffected.

Recovery objectives:

- **RTO** (Recovery Time Objective): 4 hours from total VM loss
- **RPO** (Recovery Point Objective): 24 hours (daily Postgres backup)

### Security

§18 *Auth* defines the authentication model (SSO for humans, bearer API keys for agents). Beyond that:

- All secrets mount as files; never set in environment variables.
- Bearer API keys are hashed at rest using Argon2id with per-row salt. Plaintext shown only once at creation.
- Session tokens for human users (managed by the reverse proxy / oauth2-proxy) have a 12-hour lifetime, refreshable.
- TLS terminates at the reverse proxy; internal service communication is plain HTTP within the Compose network.
- Postgres data volume is on an encrypted disk (configured at VM provisioning).
- Backups are encrypted before leaving the host (see *Backup & DR* below).

Authorization checks:

- Every state-changing endpoint checks both role and (where applicable) scope.
- Cluster-level access control: a runner who can write to `studies` for cluster A may be blocked from cluster B if scoped that way.
- All authorization decisions log a structured `authz.decision` audit-log entry.

Vulnerability management:

- CI runs `pip-audit` and `npm audit` on every PR; high-severity findings fail the build.
- Container images scanned with Trivy; CVEs above CVSS 7 fail the build.
- Static analysis: `bandit` for Python, ESLint security rules for JS/TS.
- Dependencies pinned via `uv lock` (Python) / `pnpm-lock.yaml` (JS); Dependabot enabled with weekly grouped PRs.

Tools must never print secrets in logs. CI runs a regex sweep on test-run log output to flag accidental leakage.

### Privacy & data handling

- **No PII in queries by default.** When users import query sets from production logs, a redaction step strips obvious PII patterns (emails, phone numbers, common name patterns) before storage. Configurable per cluster.
- **Documents are not stored in full.** Trial results store `doc_id` only. `_explain` debug output may contain document content; capped at 5 KB per row and gated behind a per-cluster setting.
- **OpenAI data policy.** API key is enrolled in OpenAI's Zero Data Retention (ZDR) program. Deployment refuses to start if ZDR is required by config but the key isn't enrolled.

### Code quality

| Concern | Tool | Gate |
|---|---|---|
| Python lint | `ruff check` (rules including `B`, `S`, `UP`) | error |
| Python format | `ruff format` | error |
| Python types | `mypy --strict` | error |
| Python imports | `ruff check --select I` | error |
| Python dead code | `ruff check --select F401,F841` | error |
| TypeScript lint | `eslint` (Next.js + security plugin) | error |
| TypeScript format | `prettier` | error |
| TypeScript types | `tsc --noEmit --strict` | error |
| Pre-commit hooks | `pre-commit` for all of the above | local |

Plus:

- All Python public functions, classes, and modules have docstrings (`ruff D` rules in non-test code).
- All Pydantic models have field descriptions (used as parameter docs in OpenAPI).
- Test files follow `test_*.py`; one test file per source file.

### Testing strategy

A four-layer test pyramid. Each layer has a distinct purpose, runtime profile, and CI gate.

#### Unit tests

- **Scope**: individual functions and classes in isolation.
- **Mocking**: all external dependencies mocked (DB, HTTP, OpenAI, search engines, queue, file system). Use `pytest` + `pytest-mock` for Python, `vitest` + `msw` for TypeScript.
- **Coverage gate**: **≥ 90% line coverage**, ≥ 85% branch coverage, measured by `coverage.py`. CI fails the PR if either drops.
- **Runtime**: full suite < 30 s on a developer laptop. Individual test < 100 ms.
- **Determinism**: no network, no time-of-day dependence, no randomness without a fixed seed.

#### Contract tests

- **Scope**: verify that interfaces between components honor their contracts.
- **Types**:
  - **Adapter contract tests** — every `SearchAdapter` implementation runs the same conformance suite. Lives in `tests/contracts/test_search_adapter_contract.py`, parameterized by adapter. Verifies `render`, `search_batch`, `explain`, `health_check` behavior.
  - **Tool definition contract tests** — every `@tool`-decorated function has its OpenAPI schema, OpenAI function-calling schema, and Python signature checked for mutual consistency.
  - **OpenAPI contract tests** — every endpoint listed in §20 is reachable, returns the documented schema, and accepts the documented parameters.
  - **External provider contract tests** — a small suite that hits OpenAI's API, GitHub's API, and (via cassette refresh) Fusion's gateway to confirm our assumptions about request/response shapes still hold. Run on the nightly schedule, not per-PR.
- **Mocking**: minimal — only mocks the layer below the contract boundary. Adapter contract tests use `pytest-recording` cassettes.
- **Coverage gate**: structural — every adapter implementation, every `@tool`, and every endpoint must have at least one contract test. Enforced by a custom CI check.
- **Runtime**: < 60 s in CI.

#### Integration tests

- **Scope**: multiple components composed together, with **only external systems mocked**. Internal services (Postgres, Redis, the agent backend, workers) run for real in CI via Docker Compose.
- **Mocking**: external HTTP only — OpenAI calls (cassetted via `vcrpy`), Fusion query gateway (cassetted), GitHub API (cassetted), ES (real, free, runs in CI Compose).
- **Examples**:
  - Full Optuna loop with a real Postgres but cassetted OpenAI / search-engine calls
  - LangGraph orchestrator processing a chat message end-to-end with cassetted LLM responses
  - Worker picks up a study, runs trials, writes results, triggers digest job
  - Proposal creation triggers PR worker; GitHub API call mocked
- **Coverage gate**: structural — covered by named scenarios in `tests/integration/`. PR review validates that new features have at least one integration test.
- **Runtime**: < 5 min in CI.

#### End-to-end tests

- **Scope**: full system, **no mocking, real external services**. Run against a dedicated test environment.
- **Live services used**:
  - Real OpenAI API (separate budget-capped API key for E2E)
  - The shared dev Fusion cluster (with namespaced test pipelines per CI run; see §25 *Deployment*)
  - A live Elasticsearch instance (free, deployed alongside)
  - A test config repo on GitHub (separate from the production config repo)
- **Examples**:
  - Run a 10-trial study against the staging Fusion cluster, verify metrics improve
  - Generate judgments via real OpenAI calls for a small fixed query set
  - Create a proposal that opens a real PR in the test config repo, then auto-close it
  - Drive a complete chat conversation with the orchestrator, verify expected tool calls
- **Mocking**: forbidden — if a test needs to mock something, it belongs in integration tests instead.
- **Cost containment**: E2E tests use cheap models where the test isn't model-quality-sensitive (e.g., `gpt-4o-mini`). Per-run OpenAI budget capped at $5; CI fails if exceeded.
- **Runtime**: < 20 min in CI.
- **Frequency**: every push to `main`; nightly full-suite run; opt-in per-PR via an `e2e` label.

#### Test layout

```
tests/
  unit/                   # mirror src/ structure
  contracts/              # adapter, tool, OpenAPI, external-provider contracts
  integration/            # Compose-based, external HTTP cassetted
  e2e/                    # full-stack, no mocks
  fixtures/
    fusion-cassettes/
    openai-cassettes/
    github-cassettes/
```

Each test file declares its layer in a top-of-file marker; CI's coverage tooling skips integration and E2E from the unit-coverage calculation.

### CI/CD pipeline (GitHub Actions)

Five workflows in `.github/workflows/`:

1. **`pr.yml`** — runs on every pull request:
   - Lint, format, type-check (Python + TypeScript)
   - Unit tests with 90% coverage gate
   - Contract tests
   - Integration tests
   - Security scans: `pip-audit`, `npm audit`, `bandit`, Trivy on built images
   - Secret-leak detection on test logs
   - Build Docker images (ephemeral; not pushed)
   - For prompt PRs only: run the Langfuse eval suite

2. **`main.yml`** — runs on every merge to `main`:
   - Same as `pr.yml`
   - Plus the full E2E suite
   - Push tagged images to the internal registry
   - Auto-deploy to a `staging` Compose host (via SSH or Watchtower)
   - Notify Slack with deployment summary

3. **`release.yml`** — runs on git tag `v*`:
   - Build release artifacts
   - Push semver-tagged images
   - Generate changelog from commit messages
   - Production deployment is **manual** — gated behind a "Deploy to prod" `workflow_dispatch` step

4. **`nightly.yml`** — runs at 02:00 UTC daily:
   - Full E2E suite against the test environment
   - Full Langfuse eval suite (LLM regression check)
   - Cassette freshness check: ping each external dependency, flag drift
   - Dependency vulnerability scan against the latest images

5. **`cassette-refresh.yml`** — manual `workflow_dispatch`:
   - Re-records cassettes for the named external service (Fusion, OpenAI, GitHub)
   - Opens a PR with the updated cassette files

Caching:

- Python deps: `actions/cache` keyed on `uv.lock` hash
- TypeScript deps: pnpm store keyed on `pnpm-lock.yaml` hash
- Docker layers: BuildKit cache export

Concurrency: PR checks cancel previous runs on the same PR; main and release pipelines do not cancel.

Branch protection rules on `main`:

- All `pr.yml` checks must pass
- At least one approval from CODEOWNERS for the touched paths
- Linear history (squash or rebase merges only)
- No force pushes

### Documentation

- **README** with a 5-minute quickstart for new engineers (clone, `docker compose up`, point at the local UI).
- **OpenAPI spec** auto-published at `/openapi.json` and rendered by Stoplight or Redoc at `/docs`.
- **ADRs** (Architecture Decision Records) for big choices: LangGraph, Langfuse, SigNoz, Fusion-as-primary-Solr-side-adapter, no-MCP, etc. One file per decision in `docs/09_decisions/`.
- **Runbooks** in `docs/03_runbooks/` for: cassette refresh, eval-suite failure investigation, Langfuse storage cleanup, Postgres restore, study cancellation cleanup.
- **Inline**: every Pydantic model has field descriptions; every public function has a docstring (enforced by `ruff D`).

### Backup & disaster recovery

- **Postgres**: daily logical dump (`pg_dump --format=custom`) to an off-host encrypted store (S3-compatible). Retention: 30 daily, 12 monthly. Restore tested manually quarterly, automated in CI semi-annually.
- **ClickHouse (Langfuse)**: weekly snapshots, 12 weekly retention. Lower priority — losing trace history is annoying, not catastrophic.
- **Config repos**: backed up by GitHub itself; no additional backup needed.
- **Cassette files**: in the source repo, backed up via Git.
- **Secrets**: stored in the chosen secrets manager (1Password, Vault, SSM); the deployment's secret files are restorable from there in < 30 minutes.

DR exercise: once per quarter, restore the Postgres backup to a fresh VM and verify the system comes up cleanly. Tracked in a runbook with a checklist.

### Resource limits & capacity

Per-container limits in `docker-compose.yml` (using `deploy.resources.limits`):

| Service | CPU limit | Memory limit |
|---|---|---|
| api | 2 vCPU | 2 GB |
| worker (each) | 1 vCPU | 1 GB |
| digest-worker | 0.5 vCPU | 1 GB |
| pr-worker | 0.5 vCPU | 512 MB |
| ui | 0.5 vCPU | 512 MB |
| postgres | 4 vCPU | 8 GB |
| redis | 1 vCPU | 1 GB |
| clickhouse | 2 vCPU | 4 GB |
| langfuse-web | 1 vCPU | 1 GB |
| langfuse-worker | 1 vCPU | 1 GB |
| signoz | 2 vCPU | 4 GB |

Default restart policy: `on-failure` with 5 retries, `restart_period: 60s`. Health checks defined for every service; unhealthy containers are restarted automatically.

## 24. Logging & traceability

The infrastructure for logging, tracing, and audit lives in §15 (Langfuse + SigNoz, OpenTelemetry, audit_log table) and §23 (NFRs). This section defines the *contracts* — what gets logged, in what shape, with what guarantees, and how observations correlate across systems. Without these, every engineer makes their own choices and queries become unreliable.

### Structured log schema

Every log line emitted by any service uses the same JSON shape, produced via `structlog` (Python) or `pino` (Node):

```json
{
  "ts": "2026-05-07T12:34:56.789Z",
  "lvl": "INFO",
  "msg": "trial.complete",
  "request_id": "req_01H...",
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "span_id": "b7ad6b7169203331",
  "user_id": "usr_...",
  "actor_type": "user|agent|system",
  "service": "api|worker|digest-worker|pr-worker|ui",
  "study_id": "stu_...",
  "trial_id": "tri_...",
  "duration_ms": 184,
  "kv": { "ndcg_at_10": 0.762, "cluster_id": "..." }
}
```

Required fields on every line: `ts`, `lvl`, `msg`, `service`. Required when in scope: `trace_id`, `span_id` (always set when emitted from within a traced operation), `request_id` (always set on API service), `user_id` + `actor_type` (always set on authenticated paths). Domain-scoped fields (`study_id`, `trial_id`, etc.) set when the log line happens within that scope. Free-form structured data goes under `kv`.

Log-level conventions:

- **DEBUG** — development-only diagnostic output. Off by default in production.
- **INFO** — normal operations: state transitions, completed trials, opened PRs. Default minimum level in production.
- **WARN** — recoverable issues: idempotency-key reuse, slow operations, retried failures.
- **ERROR** — operation failed but the service continues. Triggers alerts above threshold rate.
- **CRITICAL** — service-level failure: DB unreachable, configuration invalid at startup. Pages on-call.

### Event catalog

All log lines whose `msg` field is a structured event name draw from a single canonical list, owned in `src/events.py`. Adding a new event requires adding to this list (CI gate: `msg` values not in the catalog fail the build).

Event domains and a representative subset:

| Domain | Events |
|---|---|
| `auth.*` | `auth.signin_succeeded`, `auth.signin_failed`, `auth.signout`, `auth.api_key_created`, `auth.api_key_revoked`, `auth.api_key_used` |
| `authz.*` | `authz.allowed`, `authz.denied` |
| `cluster.*` | `cluster.created`, `cluster.updated`, `cluster.health_failed`, `cluster.health_recovered` |
| `template.*` | `template.created`, `template.updated`, `template.validated`, `template.validation_failed` |
| `query_set.*` | `query_set.created`, `query_set.imported`, `query_set.deleted` |
| `judgment.*` | `judgment.list_created`, `judgment.generated`, `judgment.overridden`, `judgment.calibration_computed` |
| `study.*` | `study.created`, `study.queued`, `study.started`, `study.trial_completed`, `study.trial_failed`, `study.completed`, `study.cancelled`, `study.failed`, `study.forked` |
| `digest.*` | `digest.requested`, `digest.generated`, `digest.failed` |
| `proposal.*` | `proposal.created`, `proposal.pr_open_requested`, `proposal.pr_opened`, `proposal.pr_merged`, `proposal.pr_closed`, `proposal.rejected`, `proposal.cancelled` |
| `agent.*` | `agent.conversation_started`, `agent.message_received`, `agent.tool_called`, `agent.tool_call_failed`, `agent.interrupt_requested`, `agent.interrupt_resolved` |
| `adapter.*` | `adapter.search_batch_started`, `adapter.search_batch_completed`, `adapter.session_renewed` (Fusion), `adapter.pipeline_drift_detected` (Fusion) |
| `worker.*` | `worker.started`, `worker.job_picked`, `worker.job_completed`, `worker.job_failed`, `worker.shutdown` |
| `git.*` | `git.clone_started`, `git.branch_created`, `git.commit_pushed`, `git.pr_created`, `git.webhook_received` |
| `system.*` | `system.startup`, `system.shutdown`, `system.config_loaded`, `system.config_invalid`, `system.slow_operation` |

The events module exports both the string names (used in `msg`) and Pydantic schemas for the `kv` payload. Tests verify that every emission site uses a registered event with a payload that matches its schema.

### Audit log immutability

The `audit_log` table is append-only by *enforcement*, not policy:

```sql
-- Trigger: reject UPDATE and DELETE on audit_log
CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (% on row %)', TG_OP, OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
```

The application connects with a role that has `INSERT`-only privileges on `audit_log`. Admins with broader DB access can `TRUNCATE` (which the trigger doesn't catch by default) — a separate role grants TRUNCATE only to a specifically named retention-cleanup user that runs once a year via cron, with the operation itself audited.

Tamper-evident chained hashes (each row hashes its content + the prior row's hash) are out of scope for v1; flagged for v2 if a compliance requirement emerges.

### Trace context propagation

W3C `traceparent` propagates through every service boundary:

| Boundary | Mechanism |
|---|---|
| HTTP request → API | OTel FastAPI instrumentation reads `traceparent` header |
| API → Postgres | OTel asyncpg instrumentation injects span context |
| API → Redis (queue enqueue) | Custom: serialize `traceparent` into Arq job headers |
| Redis → worker (job pickup) | Custom: deserialize `traceparent`, attach to worker span |
| Worker → adapter HTTP | OTel httpx instrumentation injects header |
| Adapter → ES / Fusion | Outbound `traceparent` header on every search call |
| API → Git provider | OTel httpx instrumentation injects header |
| API → OpenAI | Langfuse handler reads ambient OTel context, records as Langfuse trace metadata |

The Arq enqueue path is the one easy-to-miss boundary because Arq's default Python serializer doesn't carry headers. We serialize the active OTel context into the job payload at enqueue and rehydrate it at pickup. A small library (`relyloop.tracing.arq`) wraps both sides; tests verify the trace context survives an enqueue + pickup round-trip.

### Cross-system trace correlation (Langfuse ↔ SigNoz)

LLM calls produce both a Langfuse trace and a SigNoz span. To make these joinable from either side:

- The Langfuse callback handler annotates every Langfuse trace with metadata `signoz_trace_id` and `signoz_span_id`, read from the ambient OTel context at call time.
- The SigNoz span surrounding each LLM call is annotated with attribute `langfuse.trace_id` (the Langfuse trace ID returned by the handler).

This is one configuration line per service:

```python
def langfuse_handler():
    span_ctx = trace.get_current_span().get_span_context()
    return CallbackHandler(
        public_key=...,
        secret_key=...,
        host="http://langfuse-web:3000",
        metadata={
            "signoz_trace_id": format(span_ctx.trace_id, "032x"),
            "signoz_span_id": format(span_ctx.span_id, "016x"),
        },
    )
```

Result: any Langfuse trace links to its SigNoz parent in two clicks; any SigNoz span links to the Langfuse trace via the attribute. Crucial for the common debugging question "what did the LLM do during this study?"

### Lineage records

Every artifact whose existence depends on an LLM call carries enough information to reconstruct what produced it. The `judgments`, `digests`, and `proposals` tables in §9 carry three lineage columns each:

- **`langfuse_trace_id`** — Langfuse trace for the LLM call that produced this row. Null for rows produced by humans or click data.
- **`prompt_version`** — short git SHA of the `prompts/` directory at call time.
- **`input_hash`** — SHA-256 of the structured LLM input (judgments and digests). The proposal table additionally carries `study_trial_id` pointing at the specific winning trial that backs the proposal.

Effects:

- Six months from now, when a merged proposal is suspected of having hurt production relevance, every input that produced it (the LLM trace, the prompt source, the study, the specific trial) is reachable from the proposal row.
- Re-running a judgment with a newer model version produces a new row with the new `langfuse_trace_id` and `prompt_version`, while the old row is preserved — the override pattern is *additive*, not destructive.
- The `input_hash` doubles as a cache-debugging tool: if the cache is misbehaving, comparing input hashes shows exactly when inputs diverged.

### Retention policies (unified)

| Data | Retention | Storage |
|---|---|---|
| Audit log | 2 years | Postgres |
| Application logs (INFO and above) | 90 days | SigNoz |
| Application logs (DEBUG) | 7 days | SigNoz |
| Distributed traces | 90 days | SigNoz / ClickHouse |
| LLM traces (prompts + responses) | 90 days | Langfuse / ClickHouse |
| LLM eval results | indefinite | Langfuse |
| Postgres backups | 30 daily, 12 monthly | encrypted S3-compatible |
| Cassette fixtures | indefinite | Git |
| ClickHouse snapshots (Langfuse) | 12 weekly | encrypted S3-compatible |

Retention enforcement runs nightly. SigNoz and Langfuse have native TTL support; the audit_log retention is handled by the dedicated cleanup role mentioned above.

### PII redaction at log emission

A `structlog` processor scrubs sensitive content *before* a log line is emitted:

- API keys, bearer tokens, GitHub tokens, OpenAI keys (regex-based — token formats are well-defined)
- Cluster credentials (any field whose key matches `*credentials*`, `*password*`, `*secret*`, `*token*`)
- Email addresses (configurable; on by default)
- Query text (gated by per-cluster setting; off by default for staging clusters, on for production clusters)
- Document snippets and `_explain` output (capped at 5 KB; only emitted at DEBUG level)

The processor is centralized — every log line goes through it. CI runs a regex sweep of test logs to catch leakage of any of the above patterns; failure fails the build. The scrubber is itself unit-tested with synthetic secret-bearing log records.

### Slow-operation flagging

Any span exceeding 5× its operation's documented p99 SLO emits a `system.slow_operation` event with the span tree attached, regardless of trace sampling rate. This catches outliers that would otherwise be sampled out.

For example, the API non-LLM-endpoint p99 SLO is 500 ms; any non-LLM endpoint exceeding 2.5 s emits the event. Trial-execution p99 is 300 ms; any trial exceeding 1.5 s emits.

The event includes:
- The span name and full duration
- The chain of child spans contributing most to the latency
- Sufficient identifiers to find the trace in SigNoz

These events are exempted from sample-out by an OTel `AlwaysOnSampler` decision rule for the `system.slow_operation` span name.

## 25. Deployment (Docker Compose)

Single `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    volumes: [./data/postgres:/var/lib/postgresql/data]
    environment: [POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password]
    secrets: [postgres_password]

  redis:
    image: redis:7
    volumes: [./data/redis:/data]

  api:
    image: relyloop/api:latest
    depends_on: [postgres, redis]
    environment:
      DATABASE_URL: postgresql://...
      REDIS_URL: redis://redis:6379/0
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
    secrets: [openai_key, cluster_credentials, github_token]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]

  worker:
    image: relyloop/api:latest
    command: ["arq", "workers.trials.WorkerSettings"]
    deploy:
      replicas: 4              # scale via --scale worker=N
    depends_on: [postgres, redis]
    secrets: [openai_key, cluster_credentials]

  digest-worker:
    image: relyloop/api:latest
    command: ["arq", "workers.digest.WorkerSettings"]
    depends_on: [postgres, redis]
    secrets: [openai_key]

  pr-worker:
    image: relyloop/api:latest
    command: ["arq", "workers.pr.WorkerSettings"]
    depends_on: [postgres, redis]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]
    secrets: [github_token]

  ui:
    image: relyloop/ui:latest
    depends_on: [api]

  proxy:
    image: caddy:2
    ports: ["443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - ./data/caddy:/data
    depends_on: [api, ui]

  # --- LLM observability ---
  langfuse-web:
    image: langfuse/langfuse:3
    depends_on: [postgres, clickhouse]
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@postgres/langfuse
      CLICKHOUSE_URL: http://clickhouse:8123
      NEXTAUTH_URL: http://langfuse-web:3000
      TELEMETRY_ENABLED: "false"
    secrets: [langfuse_secret, langfuse_encryption_key, langfuse_salt]

  langfuse-worker:
    image: langfuse/langfuse-worker:3
    depends_on: [postgres, clickhouse, redis]
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@postgres/langfuse
      CLICKHOUSE_URL: http://clickhouse:8123
      REDIS_HOST: redis
    secrets: [langfuse_secret, langfuse_encryption_key, langfuse_salt]

  clickhouse:
    image: clickhouse/clickhouse-server:24
    volumes: [./data/clickhouse:/var/lib/clickhouse]

  # --- General observability (traces, metrics, logs) ---
  signoz:
    # Use SigNoz's official multi-service compose as a remote include.
    # See: https://github.com/SigNoz/signoz/tree/main/deploy/docker
    extends:
      file: signoz/docker-compose.yaml
      service: signoz

  signoz-otel-collector:
    extends:
      file: signoz/docker-compose.yaml
      service: otel-collector

secrets:
  postgres_password:           { file: ./secrets/postgres_password }
  openai_key:                  { file: ./secrets/openai_key }
  cluster_credentials:         { file: ./secrets/cluster_credentials.yaml }
  github_token:                { file: ./secrets/github_token }
  langfuse_secret:             { file: ./secrets/langfuse_secret }
  langfuse_encryption_key:     { file: ./secrets/langfuse_encryption_key }
  langfuse_salt:               { file: ./secrets/langfuse_salt }
```

In practice, the SigNoz deployment is its own Docker Compose project upstream (frontend, query-service, alertmanager, otel-collector, ClickHouse). Production deployment should either pull SigNoz's compose as a sibling project or merge their compose into ours via `docker compose -f docker-compose.yml -f signoz/docker-compose.yaml up`. Refer to [SigNoz's deployment docs](https://signoz.io/docs/install/docker/) for current best practices.

Sizing increase from the LLM/observability stack: roughly +4 GB RAM and +20 GB disk for traces/metrics retention at expected scale. The 8 vCPU / 32 GB rule of thumb still works comfortably.

The reverse proxy (Caddy) handles TLS and SSO via oauth2-proxy or similar. All secrets are file-mounted, never in environment variables.

Sizing rule of thumb: one VM with 8 vCPU + 32 GB RAM handles 10 concurrent studies at parallelism 4 against query sets of ~500 queries.

### Local development environment

Lucidworks Fusion has no free tier or community edition; the only supported paths are commercial licenses, evaluation licenses (30–90 days), and Fusion Cloud. To keep day-one onboarding friction low and avoid blocking on license requests, the development model **does not require a local Fusion instance**.

Three tiers of test/dev environment:

**Tier 1 — Local docker-compose (no Fusion).** The default `docker-compose.yml` adds three free-and-open engine containers: Elasticsearch (free Basic license), OpenSearch (Apache 2.0), and Apache Solr. ~80% of the system — data model, agent orchestrator, Optuna loop, ir_measures, UI, proposals, PR flow, agent integration layer — can be developed and tested entirely on this stack. New engineers clone, `docker compose up`, and are productive without any Lucidworks involvement. **For the MVP / v0.1 release, ES + OpenSearch are the only engines supported**; Fusion ships in GA v1 and Solr in v2.

```yaml
# docker-compose.yml additions for local dev
services:
  elasticsearch:
    image: elasticsearch:9.0.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    ports: ["9200:9200"]

  opensearch:
    image: opensearchproject/opensearch:2.18.0
    environment:
      - discovery.type=single-node
      - DISABLE_SECURITY_PLUGIN=true       # local dev only; production requires security plugin
    ports: ["9201:9200"]                   # different host port to coexist with ES

  solr:
    image: solr:9.5
    ports: ["8983:8983"]
    command: ["solr-precreate", "default-collection"]
```

**Tier 2 — Fusion adapter unit tests with replay fixtures.** When developing the `LucidworksFusionAdapter`, use [`pytest-recording`](https://pytest-recording.readthedocs.io/) (built on `vcrpy`). Tests run once against a real Fusion to record HTTP interactions into YAML cassettes (`tests/fixtures/fusion-cassettes/`), then replay deterministically without network access. Cassettes are checked into the repo and refreshed only when the upstream Fusion API contract changes. Engineers running just unit tests never need Fusion access.

```python
@pytest.mark.vcr  # replays from tests/fixtures/fusion-cassettes/test_query_pipeline.yaml
def test_fusion_query_pipeline_render(fusion_adapter, sample_template):
    result = fusion_adapter.search_batch(target="products", queries=[...], top_k=10)
    assert "products" in result
```

**Tier 3 — Integration tests against the shared dev Fusion cluster.** CI runs Fusion-touching integration tests against the org's existing Fusion dev environment. The integration test runner creates dedicated, namespaced pipelines (`relyloop-test-{branch}-{run_id}`) at setup and tears them down at teardown, so concurrent CI runs and engineer-driven manual tweaks never conflict. This is a hard requirement, not optional — without namespace isolation, the dev cluster's pipeline state will drift and tests will fail for unrelated reasons.

**Tier 4 (optional) — Mock Fusion service for UI/demo work.** A small companion overlay file `docker-compose.dev.yml` adds a `fusion-mock` service: ~200 lines of FastAPI emulating the Fusion query gateway with canned responses. Useful for UI development, screenshots, and demos when even the shared dev cluster isn't reachable (e.g., off-network, intermittent connectivity). Not used in unit or integration tests — those use cassettes or real Fusion.

```yaml
# docker-compose.dev.yml — opt-in via `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`
services:
  fusion-mock:
    build: ./fusion-mock
    ports: ["8764:8764"]
    environment:
      MOCK_FIXTURES_DIR: /fixtures
    volumes: [./fusion-mock/fixtures:/fixtures]
```

### When a real local Fusion is required

A handful of cases still need real Fusion locally; for these, request a 30-day Lucidworks evaluation license per engineer (renewable as needed):

- Initial Fusion adapter development — recording the first round of cassettes
- Adding new Fusion-specific search-space parameters (e.g., `stage_enabled` extensions)
- Reproducing Fusion-specific bugs that only manifest under specific cluster state
- Validating session-auth or JWT flows in a controlled environment

In each case, the org's existing Fusion dev cluster is usually a viable substitute for an eval license, depending on access policy.

## 26. Failure modes & edge cases

| Failure | Detection | Handling |
|---|---|---|
| ES/Fusion cluster down | Adapter `health_check()` fails or batch search returns 5xx | Trial marked failed; if 5+ consecutive trial failures, study auto-cancels |
| Fusion session expired mid-study | 401 from Fusion gateway | Adapter re-authenticates transparently and retries the trial; counts as one ordinary retry, not a failure |
| Fusion pipeline edited out of band during study | Same template, different upstream pipeline shape | Detected by hashing pipeline JSON at study start vs. trial time; mismatch fails the trial with `error_code = pipeline_drift` |
| Worker crashes mid-trial | Arq job failure; Optuna ask-without-tell | Trial lost; Optuna will re-suggest similar params; idempotent |
| Optuna RDB lock contention | Slow `study.ask()` calls | Backoff; if persistent, reduce study parallelism |
| OpenAI API rate-limit | Tool call fails | Exponential backoff; surface to user if all retries fail |
| OpenAI judges-list generation fails partway | Partial judgment list | Mark list `incomplete`, allow re-run, prevent use in studies |
| Git push conflict | Branch already exists | Append timestamp suffix and retry |
| Webhook delivery missed | Polling fallback | 15-minute reconciliation job |
| Trial template renders to invalid query | Adapter returns `RenderError` | Trial marked failed, not pruned; investigate |
| Judgment list tampered (LLM bias / prompt drift) | Calibration stats degrade | Block use in new studies if Cohen's kappa < threshold |
| Cancellation of running study | User clicks cancel | API sets status=cancelled; workers poll, drain in-flight, exit clean |
| Agent retry storm without idempotency keys | Same logical operation requested N times | API enforces `Idempotency-Key` requirement on POST/PATCH/DELETE in production; missing-key requests get a single warning, then 400 |
| Idempotency body mismatch | Same key, different body | 409 Conflict with `error_code = idempotency_mismatch`; agent regenerates key for the new request |
| Webhook delivery to subscriber fails | 5xx from subscriber | Retry with exponential backoff up to 24h; deliveries beyond that dropped and logged on subscription |
| API key compromise | Key leaked or suspected leak | Admin revokes via `DELETE /api-keys/{id}`; revocation is immediate (no cache) |
| API key expired during long study | Worker calls fail mid-execution | Workers use the system service account, not user keys, for internal operations; user keys are only checked at API ingress |

## 27. Phased delivery

Delivery is incremental: six releases (MVP1 → MVP1.5 → MVP2 → MVP3 → MVP4 → GA v1), each meaningful as a discrete capability bundle. Each release ships a coherent step-up in adopter value and audience reach, never a partial build. Total wall-clock estimate: **~19 weeks single-engineer**, or roughly **12–14 weeks with two engineers** working in parallel after MVP1.

| Release | Theme | Timeline | Audience |
|---|---|---|---|
| MVP1 / v0.1 | The Loop | 5 weeks | Technical evaluators willing to test on a laptop |
| MVP1.5 / v0.1.5 | Real Signals | +2 weeks | Operators running OpenSearch UBI; teams that want trust anchored in real user behavior, not LLM ratings |
| MVP2 / v0.2 | Observable | +3 weeks | Platform teams considering serious evaluation |
| MVP3 / v0.3 | Production Stacks | +3 weeks | Lucidworks shops, GitLab/Bitbucket enterprises |
| MVP4 / v0.4 | Multi-tenant, Multi-LLM | +3 weeks | Platform teams operating for many customers |
| GA v1 / v1.0 | Production-ready | +3 weeks | Production deployments, contributors, the community |

### MVP1 / v0.1 — "The Loop" (target: 5 weeks, 1 engineer — or ~3 weeks with two)

**Headline: The Karpathy loop, working.**

The smallest version of RelyLoop that demonstrates real value end-to-end on a developer's laptop, with no external infrastructure dependencies beyond OpenAI. Released as an alpha for evaluation, design-partner engagement, and internal-champion adoption — not for production rollout.

What MVP1 delivers: a relevance engineer can `docker compose up`, point at a local Elasticsearch or OpenSearch instance, define a query set, generate LLM judgments, run an overnight study, get a digest, and open a PR against a GitHub config repo. The full Karpathy loop, end-to-end, on a single laptop.

**MVP1 scope (in):**

- **Single adapter for Elasticsearch and OpenSearch** (one ElasticAdapter handling both via engine_type)
- **OpenAI** as the only LLM provider (no provider abstraction layer; direct `openai` Python client + function calling, no LangGraph)
- **GitHub** as the only Git provider (no provider abstraction layer)
- **Single-tenant** deployment — `tenants` table absent; data scoped to the install
- Postgres data model (without `tenant_id` columns; added in MVP4 as a migration)
- Optuna with TPE sampler
- ir_measures evaluation
- LLM-generated judgments + basic override UI
- Studies UI: create, run, view trials, view digest
- Proposals → GitHub PRs (single config repo)
- Chat interface (OpenAI function calling, no agent state graph)
- Basic structured logging via `structlog` (no Langfuse, no SigNoz; OTel exporter optional and pointed at nothing by default)
- Docker Compose deployment with ES + OpenSearch containers
- Apache 2.0 LICENSE + minimal README + CONTRIBUTING.md + CODE_OF_CONDUCT.md
- **Unit tests with 80% coverage gate** (raised to 90% by GA v1)
- Basic GitHub Actions CI: PR pipeline (lint, tests, build images locally)
- One worked tutorial with sample data — a 50-query set against a sample ES index, walking through the full loop

**MVP1 positioning:**

- Versioned `0.1.0` under SemVer (the leading zero signals pre-1.0 instability; no backwards-compatibility guarantees yet)
- Released as **"alpha"** in README and announcement materials — explicitly evaluation-only
- Audience: technical platform teams willing to live with rough edges in exchange for an early look at the core capability
- **Not** marketed to procurement, security review, or production-readiness audiences — those wait for GA v1
- Provides concrete demo material (videos, screenshots, before/after metrics, real PRs in real repos) that compounds across subsequent releases

**Strategic rationale:** Validates the core value proposition with real users in 5 weeks instead of 17. If the loop doesn't actually help, you find out 12 weeks earlier and can pivot. Identifies design partners — whoever installs MVP1 and runs it against real data is your design-partner candidate.

---

### MVP1.5 / v0.1.5 — "Real Signals" (target: +2 weeks)

**Headline: The loop, grounded in what users actually do.**

MVP1 ships with LLM-as-judge as the only authoritative judgment source. That's enough to demonstrate the optimization loop, but for operators with production traffic it's a weaker trust anchor than real user behavior. MVP1.5 closes that gap by making **OpenSearch UBI** (User Behavior Insights — a standardized, engine-neutral event-capture schema championed by Eric Pugh / OpenSource Connections, shipped as the OpenSearch UBI plugin in 2024) a first-class judgment source alongside LLM-as-judge.

**MVP1.5 adds on top of MVP1:**

- **`UbiReader`** (engine-agnostic) reads the standardized `ubi_queries` + `ubi_events` indices via any `SearchAdapter`'s `search_batch` — no engine-specific code, no new Compose service. Aggregates raw events over an operator-specified window into per-(query, doc) interaction features: click count, impression count, position-bias-corrected CTR, post-click dwell-time mean, conversion rate (where conversions are emitted), refinement rate.
- **Pluggable `SignalsConverter` Protocol** mapping features → 0–3 ratings. Initial implementations:
  - **Position-bias-corrected CTR threshold** (default, conservative)
  - **Dwell-time threshold** (good for content discovery / long-read use cases)
  - **Hybrid UBI+LLM** — UBI rates the dense head; LLM-as-judge fills the long tail for queries below an impression threshold. The mixed-`source` judgment list is the operating mode most adopters will ship to production.
- **No schema migration.** The `judgments.source` CHECK constraint accepts `click` today; a single judgment list can mix `llm` + `human` + `click` rows. The MVP1 schema was designed for this.
- **`POST /api/v1/judgment-lists/generate-from-ubi`** endpoint + **`generate_judgments_from_ubi`** agent tool. Same code path on both surfaces (agent-first symmetry per §21).
- **Calibration spot-check workflow** — same Cohen's kappa / agreement-stat surface as MVP1's LLM calibration, run between UBI-derived ratings and a 30–50 row hand-labeled sample. Catches mis-tuned converters (e.g., dwell-time threshold set too low for the traffic shape).
- **Operator docs** — runbook for installing the OpenSearch UBI plugin, configuring event capture in the application, choosing the right converter for the use case, and a tutorial extension to the MVP1 tutorial that swaps the LLM judgment list for a UBI-derived one once enough events have been captured.
- **Documented Phase 2 extensions** (NOT shipped at MVP1.5): counterfactual click models (CCM, DBN); engine-native behavioral-data readers for clusters that haven't adopted UBI — Elastic Behavioral Analytics and others — all feeding the same `SignalsConverter` Protocol unchanged.

**MVP1.5 does NOT include:**

- A second Compose service. `UbiReader` runs inside the existing API + worker containers.
- Real-time signal streaming. UBI ratings are computed batch-wise at judgment-list creation time, not on the live serving path — this is still strictly offline Path A (per §27 "Why the deferral is right today").
- Production quality monitoring or alerting (Path B, v2).
- A schema migration. UBI rides the existing `judgments` table.

**Audience expansion:** Operators with production search traffic and OpenSearch UBI logging enabled. These adopters disproportionately distrust LLM-as-judge ratings as a primary trust anchor; MVP1.5 is the release that earns their evaluation. Also: open-source signals that UBI is a first-class direction for RelyLoop, not deferred to a post-GA milestone — relevant for the OSC community where UBI was incubated.

**Strategic rationale:** The optimization loop's quality is bounded by the quality of the judgments it scores against. LLM-as-judge unblocks the MVP1 demonstration, but it caps the believability of every winning trial behind "did the LLM actually get the relevance call right?" UBI removes that ceiling for operators with real traffic. Shipping it as the very next release (rather than waiting for MVP2's observability layer or MVP3's Fusion work) keeps the focus on the core value proposition: trustworthy automated relevance tuning.

---

### MVP2 / v0.2 — "Observable" (target: +3 weeks)

**Headline: The loop you can audit.**

Without trustworthy observability, no platform team will run RelyLoop unattended overnight. v0.2 adds the full observability layer so adopters can see what the tool is doing, why, and what it produced — and have an immutable audit trail for governance.

**MVP2 adds on top of MVP1:**

- **Langfuse self-hosted** — every LLM call captured: prompts, responses, costs, token counts, latency. LangChain callback handler integrated. Eval datasets seeded for `propose_search_space`, `generate_judgments_llm`, `digest_narrative`.
- **SigNoz self-hosted** — distributed traces, metrics, logs via OpenTelemetry. Auto-instrumentation for FastAPI, Postgres, Redis, OpenAI client.
- **Structured event catalog** — `src/events.py` with ~50 named events across 13 domains (auth, study, proposal, agent, etc.), backed by Pydantic schemas. CI gate rejects unregistered event names.
- **Audit log immutability** — Postgres trigger blocking UPDATE/DELETE on `audit_log`. INSERT-only role for the API.
- **Lineage columns** — `langfuse_trace_id`, `prompt_version`, `input_hash` on judgments, digests, proposals. Full provenance for every LLM-produced artifact.
- **Trace context propagation** — W3C `traceparent` flows through API → Redis → worker → adapter → engine, including the Arq enqueue→pickup boundary that needs custom serialization.
- **Cross-system correlation** — Langfuse traces annotated with SigNoz span IDs and vice versa. Two-clicks navigation between the two observability stacks.
- **PII redaction processor** — centralized `structlog` processor scrubbing tokens, keys, credentials; configurable email and query-text redaction. CI runs a regex sweep of test logs to flag accidental leakage.
- **Slow-operation flagging** — spans exceeding 5× their p99 SLO emit `system.slow_operation` regardless of trace sampling rate.
- **Unified retention policy** — documented across audit log, application logs, traces, LLM traces, eval results, backups.

**Audience expansion:** Platform teams considering serious evaluation. Without observability, the tool is a curiosity; with it, the tool can be assessed for production-style operation.

**Strategic rationale:** Observability is a foundational reliability layer that benefits every adopter regardless of engine, LLM provider, or scale. Adding it before broadening engine support means all subsequent MVPs ship with full traceability from day one — no retrofit needed.

---

### MVP3 / v0.3 — "Production Stacks" (target: +3 weeks)

**Headline: Works against your real production stack — Fusion, GitLab, Bitbucket.**

v0.3 broadens the supported production stack by adding the Lucidworks Fusion adapter and the multi-Git-provider abstraction. After v0.3, RelyLoop can be evaluated against the search engine and Git provider you already run, not just ES + GitHub.

**MVP3 adds on top of MVP2:**

- **Lucidworks Fusion adapter** — full implementation:
  - `search_batch` via Fusion's gateway query API (`POST /api/apps/{app}/query/{collection}`)
  - `render` produces Fusion request bodies with parameter overrides; pipeline JSON is the canonical Git artifact
  - Auth via session cookies or JWT
  - Fusion-specific tools: `list_pipelines`, `get_pipeline`, `list_query_profiles`
  - Two-step apply path (PR edits pipeline params; CI runs `objects-import` to deploy)
  - `auth_kind = "fusion_session"` and `"fusion_jwt"` paths
- **Engine-native signals reader for Fusion** — aggregates events from the `{app}_signals` collection into the same per-(query, doc) feature shape MVP1.5's `UbiReader` produces. Reuses the MVP1.5 `SignalsConverter` Protocol unchanged; only the read path is Fusion-specific. Relevant for Fusion deployments that haven't adopted UBI.
- **Multi-Git-provider abstraction** — `GitProvider` Protocol with three implementations:
  - GitHub (already present from MVP1)
  - GitLab — token or app auth, project-level webhooks, MR + approval rules
  - Bitbucket — workspace tokens, webhook UUID, default reviewers + branch restrictions
  - Per-provider webhook endpoints (`/webhooks/github`, `/webhooks/gitlab`, `/webhooks/bitbucket`)
- **Adapter contract tests** — every `SearchAdapter` and `GitProvider` implementation runs the same conformance suite. Future community-contributed adapters pass the same suite to be merged.
- **Cassette-based testing infrastructure** — `pytest-recording` for Fusion adapter unit tests; deterministic replay without requiring a live Fusion instance.
- **Fusion-specific docs** — config-repo conventions for Fusion (pipelines + params + profiles directory layout), pipeline-validate CI integration, two-step apply path runbook.

**Audience expansion:** Lucidworks shops (a substantial enterprise-search audience), GitLab-using enterprises, Bitbucket-using enterprises. Roughly doubles the addressable adopter pool.

**Strategic rationale:** Engine and Git providers are the two interfaces that gate enterprise adoption. v0.3 removes both as blockers for the most common production deployments — and the adapter contract tests it introduces become the foundation for community-contributed adapters going forward.

---

### MVP4 / v0.4 — "Multi-tenant, Multi-LLM" (target: +3 weeks)

**Headline: Run RelyLoop for many customers, with the LLM provider you need.**

v0.4 enables platform-team-scale adoption: a single deployment serving many downstream customers in isolation, optionally with different LLM provider choices per tenant.

**MVP4 adds on top of MVP3:**

- **Multi-tenancy primitives** — `tenants` table, `tenant_id` columns across all user-facing tables (clusters, query_sets, judgment_lists, query_templates, studies, proposals, conversations, audit_log, config_repos), `tenant_memberships` junction table with per-tenant roles (`viewer`, `runner`, `tenant_admin`), `platform_admin` super-role for cross-tenant operations.
- **Tenant scoping on all operations** — list endpoints filter by tenant, write endpoints enforce tenant context, audit log rolls up per tenant.
- **Per-tenant configuration overrides** — `tenants.settings` JSONB allows different LLM providers, cost caps, default samplers per tenant.
- **Bearer-token API keys** — `api_keys` table with Argon2id-hashed keys, role + scopes (e.g., `studies:write`, `proposals:write`), expiration, revocation. Tenant-scoped by default. Service accounts get long-lived keys; admins issue and rotate.
- **Multi-LLM provider abstraction** — pluggable `ChatModel` adapter with implementations for OpenAI (already from MVP1), Anthropic, AWS Bedrock, Azure OpenAI, Google Vertex AI, and self-hosted (Ollama, vLLM). Provider selection per-tenant via config; capability validation at startup (refuses to start if the chosen provider lacks structured-output support).
- **Cost tracking** — Langfuse-derived per-tenant LLM cost rollups exposed in the UI.
- **Tenant switcher in UI** — for users who belong to multiple tenants.

**Migration:** Single-tenant MVP1-MVP3 deployments are migrated into the new schema with an auto-created `default` tenant and all existing rows backfilled with that tenant_id. The migration is documented and CI-tested.

**Audience expansion:** Platform teams running search for many internal/external customers (the target audience that motivated the project from the start); orgs with strict LLM provider policies (Bedrock-only AWS shops, Vertex-only GCP shops, air-gapped deployments on Ollama/vLLM).

**Strategic rationale:** Multi-tenancy is the boundary between "internal team tool" and "platform-team product." Multi-LLM is the boundary between "OpenAI-only" and "fits any enterprise's LLM strategy." Both are needed for the platform-team use case that motivated the project from the start.

---

### GA v1 / v1.0 — "Production-ready" (target: +3 weeks)

**Headline: The 1.0 release — production-ready, contributor-ready, fully governed.**

GA v1 layers in the polish that elevates RelyLoop from a working tool to a proper open-source product: orchestrator architecture migration to LangGraph, the full agent-first API surface, the four-layer test pyramid, complete CI/CD with security gates, and the OSS launch infrastructure (governance, docs, ADRs, distribution).

**GA v1 adds on top of MVP4:**

- **LangGraph orchestrator** — replaces MVP1's plain OpenAI function calling with a state graph (orchestrator + hypothesis-gen subagent + evaluation subagent). Postgres-backed state persistence via `PostgresSaver`; resumable conversations; human-in-the-loop interrupts at three points (PR open, prod-cluster studies, judgment regeneration).
- **Full agent-first API surface** — `/openapi.json`, `/capabilities`, `/tools.json`, idempotency keys with conflict semantics, RFC 7807 error format with `error_code` + `retryable` extensions, cursor pagination, rate-limit headers, outgoing webhook subscriptions with HMAC signing, SSE streams on `/studies/{id}/events` and `/proposals/{id}/events`.
- **Full four-layer test pyramid:**
  - Unit tests: **90% line coverage** (up from 80% in MVP1-4), 85% branch coverage
  - Contract tests: every adapter, every `@tool`, every endpoint covered (extends the contract-test foundation laid in MVP3)
  - Integration tests: Compose-based with cassetted external HTTP, < 5 min runtime
  - E2E tests: live OpenAI + shared Fusion dev cluster + test config repo, < 20 min runtime, $5/run budget cap
- **Full GitHub Actions CI/CD** — five workflows (`pr.yml`, `main.yml`, `release.yml`, `nightly.yml`, `cassette-refresh.yml`) with security scans (Trivy, bandit, pip-audit, npm audit), branch protection on `main`, auto-deploy to staging on merge, manual gate to prod on tag.
- **Complete code quality gates** — ruff, mypy strict, eslint, prettier, tsc strict, pre-commit hooks, secret-leak detection.
- **Backup & DR baseline** — daily Postgres dumps with 30-day retention, runbook for restore, quarterly DR exercise.
- **Complete OSS launch infrastructure:**
  - Apache 2.0 LICENSE + NOTICE + ADRs documenting major decisions
  - CONTRIBUTING.md (DCO model), CODE_OF_CONDUCT.md (Contributor Covenant 2.1), SECURITY.md, MAINTAINERS.md, GOVERNANCE.md
  - Issue and PR templates with DCO reminder
  - GitHub Container Registry image publication, signed with cosign, multi-arch (amd64 + arm64)
  - Comprehensive docs: README, `docs/08_guides/install.md`, `docs/03_runbooks/operate.md`, `docs/08_guides/tutorial-first-study.md`, `docs/01_architecture/architecture.md`, `docs/07_research/comparison.md`, `docs/08_guides/migration-from-quepid.md`, `docs/08_guides/cookbook.md`, `docs/08_guides/faq.md`, ADRs in `docs/09_decisions/`
  - API reference auto-generated from OpenAPI and rendered with Stoplight or Redoc
- **ZDR (Zero Data Retention) enforcement** — deployment refuses to start if ZDR is required by config but the LLM key isn't enrolled.
- **Telemetry stance** — explicit zero-telemetry commitment with CI grep gate against telemetry-pattern strings.
- **Public-launch readiness** — design partners onboarded and live, brand naming and trademark verifications complete (see §28 and §29 #23), at least one public reference customer with permission.

**Audience expansion:** Production deployment by enterprise platform teams; foundation for community contributors; long-term sustainability of the project.

**Strategic rationale:** GA v1 is the moment RelyLoop becomes a real open-source product, not just a working tool. It's contributor-ready (governance), production-ready (testing, security, observability already in place since MVP2), and adoption-ready (docs, distribution, design partners).

### v1.5+ (post-GA, target: +4 weeks)

Post-GA polish items. UBI (MVP1.5) and engine-native behavioral-data readers (MVP3 / v2) used to live here; they were promoted to the release timeline when MVP1.5 was introduced as a formal tier.

- Multiple config repos
- Outgoing webhooks for resource lifecycle events (study, digest, proposal, PR state) — replaces polling for both internal and external agents
- SSE streams on `/studies/{id}/events` and `/proposals/{id}/events`
- Prod-validation flow (run winning config read-only against the prod cluster before opening the staging PR)
- Calibration UI for judgment lists
- Audit log UI
- Performance hardening (worker pool tuning, RDB indexes)
- Cost dashboard and per-user OpenAI quotas
- W3C Trace Context (`traceparent`) propagation through to ES/Fusion
- Counterfactual click models (CCM, DBN) as additional `SignalsConverter` implementations on top of the MVP1.5 Protocol — relevant once enough impressions per (query, doc) have accumulated to make them statistically valid

### v2 (TBD)

#### Path A continuations — refinements to the experimentation-and-change-management tool

- Conditional parameters in search space
- Multi-objective optimization (nDCG vs latency Pareto)
- Pure-Solr adapter (when needed by a non-Fusion deployment)
- Elastic Behavioral Analytics integration (real click data → judgments) for ES clusters
- LTR plugin support (train + deploy XGBoost rerankers); Fusion ML reranker training integration
- Vespa adapter
- Cross-cluster fan-out studies

#### Path B — Search Quality Platform expansion

A coherent v2 direction is to expand from "experimentation and change management" into "experimentation and change management *plus* real-time production observability and online learning." This shifts the tool from Quepid-territory toward commercial-platform-territory (Coveo, Algolia, Bloomreach). It's deliberately deferred from v1 because:

- v1 is already substantial scope; piling Path B on top jeopardizes shipping
- Path A is independently valuable; Path B builds on Path A but isn't a prerequisite for it
- Path B requires stream-processing infrastructure (Kafka or Redis Streams + ClickHouse rolling-window aggregation), which is a meaningful architectural addition
- Path B changes the audience — Path A serves search engineers; Path B also serves search ops / SREs. Different mental model in the UI.

**Path B candidates, ordered by likely priority:**

- **Production quality monitoring.** Stream signals (Fusion `*_signals` collection or ES Behavioral Analytics) into rolling-window quality metrics — CTR, dwell time, refinement rate, zero-result rate, position-1 abandonment. Alert when metrics degrade beyond thresholds. Optionally trigger an LLM agent investigation that pulls recent failing queries and surfaces hypotheses. Most universally valuable Path B capability; turns the tool into a daily-driver for search platform teams, not just a tuning workbench.
- **Bandit-style online learning.** Multi-armed bandits (Thompson sampling, contextual bandits via Vowpal Wabbit or similar) routing live production traffic across promising candidate configs and progressively shifting toward winners. The offline Karpathy-loop studies feed the bandit candidates; the bandit produces real-time learning. This is the most ambitious Path B addition because it requires the tool to participate in (or coordinate with) the production search-serving path, not just sit alongside it. Architecturally, two viable shapes:
  - **External coordinator.** The tool maintains the bandit state and exposes a `/api/v1/bandit/select?cluster=X` endpoint the search service calls per query to choose which config to serve. Adds latency to the hot path; clean integration boundary.
  - **In-engine.** The bandit logic lives in the search engine itself (a Solr request handler or a Fusion stage), driven by a config the tool publishes. No hot-path latency; harder to debug.
  - The decision affects v2 scoping significantly. External-coordinator is the more natural OSS extension; in-engine implementations would likely be community-contributed adapters per engine.
- **Shadow validation pre-deploy.** When a PR is merged but before CI promotes it to live serving, run the new config against a sampled live-query stream (read-only, results discarded) for 30–60 minutes, compare metrics against the current production config, and either auto-approve the deploy or flag for human review. Stronger confidence than offline judgment-list eval, lower risk than direct deploy. Builds on production monitoring infra.
- **Fusion Experiments integration.** Online A/B testing of winning configs against current production via Fusion's native experiments feature; results flow back to the tool's experiment table.
- **Manual one-click rollback.** Surfaced from the production monitoring UI when metrics degrade. Opens a revert PR against the config repo, triggering the same review-and-deploy path. Auto-rollback explicitly rejected (see §4 Non-goals).

#### Why the deferral is right today

The honest reasoning, in case the priority changes later:

1. Shipping Path A as a focused, high-quality OSS release is more valuable than shipping a partial Path B that doesn't fully cover either side.
2. Path A has demonstrable value standalone — Quepid users get a meaningful upgrade, search platform teams get measurable relevance improvements, and the experimentation-and-change-management problem is real and underserved on its own.
3. Path B is a different *kind* of problem. It pulls in stream processing, real-time alerting, on-call operational thinking. Mixing both in v1 creates a product that's less coherent on each axis.
4. If the project succeeds in Path A, Path B becomes the natural roadmap. If Path A struggles (low adoption, slow community formation), Path B was never going to save it.

The bandit capability specifically has been called out as the single most interesting v2 candidate by the project sponsor; it's deliberately set aside for v1 to keep focus, with the explicit option to revisit after Path A ships.

## 28. Tech stack & implementation decisions

This section consolidates every implementation-level decision that shapes how RelyLoop is built. Read it before contributing code; reference it when reviewing PRs to confirm a choice is consistent with the project's stance. Where a section above (§7 architecture, §15 LLM orchestration, §22 UI, §23 NFRs, §25 Deployment) covers a specific area in depth, the entries here cross-reference rather than duplicate.

### Backend stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ (async) | Type-rich, FastAPI ecosystem, AI/ML library access |
| Web framework | FastAPI | Async-native, OpenAPI auto-generation, Pydantic integration |
| ORM | **SQLAlchemy 2.0** (async) | Mature, predictable, full Postgres feature support, industry default for async Python + Postgres |
| DB driver | asyncpg | Fastest async Postgres driver, used by SQLAlchemy async |
| Migrations | Alembic | Standard SQLAlchemy companion, autogenerate from models |
| Validation | Pydantic v2 | Already required by FastAPI, used for tool args, eval datasets, API request/response shapes |
| Settings | Pydantic Settings | Type-checked, env-var-friendly, integrated with Pydantic v2 |
| HTTP client | httpx (async) | Modern requests-equivalent with native async; used by adapters and OpenTelemetry instrumentation |
| Logging | structlog | Structured JSON logging, processor pipelines for PII redaction (§24) |
| Queue / workers | Arq + Redis 7 | Async-native, Redis-backed, simple API; trace context propagation handled by `relyloop.tracing.arq` (§24) |
| Optimization | Optuna with TPE sampler + RDBStorage | Established, well-tested, supports the parallel ask/tell pattern we need (§13) |
| IR evaluation | ir_measures | Provider-abstracted; wraps multiple IR-evaluation backends behind a typed metric-object DSL; gives identical metric semantics across engines (§14) |
| LLM orchestration | LangGraph (GA v1); plain `openai` SDK + function calling (MVP1) | LangGraph is overkill for the MVP loop; ships in GA v1 alongside subagents (§15) |
| LLM client (multi-provider) | LangChain provider packages — `langchain-openai`, `langchain-anthropic`, `langchain-aws`, `langchain-google-vertexai`, etc. (MVP4+) | Provider-agnostic abstraction with consistent `BaseChatModel` interface (§15) |
| LLM cache | LangChain `RedisCache` (MVP4+) | Reuses existing Redis; cache keys per (template, cluster, query_set) for cost-bound calls |
| Auth — passwords/keys | passlib with Argon2id | Standard recommendation for password/key hashing; salted per-row |
| Auth — JWT (MVP4+) | PyJWT or python-jose | Both fine; pick the one with the smallest dep tree at the time |
| Testing | pytest + pytest-asyncio + pytest-mock + pytest-recording | Standard async pytest stack; recording for HTTP cassettes (§22, §23) |
| Coverage | coverage.py | Default for Python; CI gate at 80% (MVP1) → 90% (GA v1) |
| Linter / formatter | ruff (check + format) | Replaces flake8 + isort + black; fastest in class |
| Type checker | mypy --strict | Industry standard; strict mode catches more bugs |
| Dependency mgmt | uv | Modern, fast, lockfile-based; replaces pip + pip-tools + virtualenv |
| Pre-commit | pre-commit framework | Standard tool for hooking ruff/mypy/eslint into commit flow |

### Frontend stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | TypeScript (strict) | Type safety, ecosystem standard |
| Framework | Next.js 14+ (App Router) | Server components, streaming, mature SSR/SSG; default for production React in 2026 |
| UI components | **shadcn/ui** | Components copied into the repo (not npm dep), fully customizable; modern default for developer-tool dashboards |
| Styling | **Tailwind CSS** | Utility-first, pairs natively with shadcn/ui |
| Server state / data fetching | **TanStack Query** | Caching, retries, optimistic updates, mutation handling — the React server-state default |
| Forms | React Hook Form + Zod | Modern default; Zod schemas can be reused for API request validation |
| Charts | Recharts | Sufficient for parameter-importance bars, scatter plots, trial-progress lines; mature React integration |
| Streaming | Native EventSource (browser) for SSE | No library needed for the modest SSE surface |
| Editor (template authoring, GA v1) | Monaco | VS Code's editor; supports JSON, YAML, Jinja syntax highlighting |
| Testing | vitest + msw | vitest is the modern jest-replacement; msw mocks HTTP at the network layer |
| Linter | eslint with Next.js + security plugins | Standard Next.js setup |
| Formatter | prettier | Standard; integrated with eslint |
| Type checker | tsc --noEmit --strict | Default; runs in CI |
| Dependency mgmt | pnpm | Fast, disk-efficient, lockfile-based |

### Infrastructure stack

| Layer | Choice | Versions / Notes |
|---|---|---|
| Database (app) | Postgres 16 | Primary application state + Optuna RDBStorage (single instance) |
| Cache / queue | Redis 7 | Arq queue + LangChain cache (MVP4+) |
| Trace storage (LLM) | ClickHouse 24 | Required by Langfuse (MVP2+) |
| Search engines (targets) | Elasticsearch 8.11+/9.x; OpenSearch 2.x/3.x; Lucidworks Fusion 5.x; Solr 9.x (v2+) | Per-engine version support documented in §8 |
| Reverse proxy | Caddy 2 | TLS termination, SSO via oauth2-proxy or Authelia |
| Container runtime | Docker 24+ with Compose | MVP1 deployment target |
| Helm chart (v1.5+) | Helm 3 | Kubernetes deployment for adopters that prefer it |
| Secrets at runtime | Mounted secret files | Never in env vars (§23 Security) |
| Backup target | Encrypted S3-compatible | Daily Postgres dumps (§23) |

### CI/CD and quality gates

| Layer | Choice | Notes |
|---|---|---|
| CI/CD platform | GitHub Actions | Five workflows in GA v1; one (`pr.yml`) in MVP1 |
| Container scanning | Trivy | CVE check on built images (GA v1) |
| Python SAST | bandit | Static analysis (GA v1) |
| Python deps audit | pip-audit | CVE check against locked dependencies (GA v1) |
| TS deps audit | npm audit | Same, for TS deps (GA v1) |
| Image signing | cosign | Keyless OIDC signing via GitHub OIDC (GA v1) |
| Build cache | BuildKit cache export | Speeds up CI image builds |
| Branching | Trunk-based | Short-lived feature branches off main |
| Commit format | Conventional Commits | Auto-generated changelogs and release notes |
| Versioning | SemVer 2.0 | Stable contracts: HTTP API, OpenAPI, schema, adapter Protocols, webhooks |

### Observability stack (MVP2+)

| Layer | Choice | Where it runs |
|---|---|---|
| LLM observability | Langfuse self-hosted | LangChain callback handler integration; ClickHouse-backed |
| Distributed observability | SigNoz self-hosted | OpenTelemetry-native; replaces Prometheus + Loki + Tempo + Grafana |
| Instrumentation | OpenTelemetry SDK | Auto-instrumentation for FastAPI, asyncpg, Redis, OpenAI, httpx |
| Trace propagation | W3C `traceparent` | Custom Arq wrapper for the queue boundary (§24) |

### Conventions and standards

**Code organization:**

- Single monorepo: `relyloop/relyloop` on GitHub
- Top-level structure: `backend/`, `ui/`, `worker/`, `migrations/`, `prompts/`, `templates/`, `samples/`, `scripts/`, `docs/`, `tests/`
- One test file per source file; mirror the source tree under `tests/`
- Adapters live under `backend/app/adapters/` (engine), `backend/llm/` (LLM provider), `backend/git/` (Git provider)

**Python coding standards:**

- 100-character line limit (ruff default)
- Ruff rule set: defaults + `B` (bugbear), `S` (security via bandit), `UP` (pyupgrade), `D` (docstrings on public APIs)
- mypy `--strict`, no `Any` without explicit annotation
- Public functions, classes, modules have Google-style docstrings
- All Pydantic models have field descriptions (used in OpenAPI auto-generation)
- snake_case for variables, functions, modules; PascalCase for classes; SCREAMING_SNAKE for constants

**TypeScript coding standards:**

- 100-character line limit (prettier default)
- ESLint Next.js + security + react-hooks plugins
- `tsc --strict` and `noUncheckedIndexedAccess`
- camelCase for variables and functions; PascalCase for components and types

**Database conventions:**

- **UUIDv7** primary keys on every table — lexicographically sortable, time-ordered, generated client-side
- All timestamps `TIMESTAMPTZ`, stored UTC
- Soft delete via `deleted_at` on user-facing tables; hard delete on internal audit-bypass tables (e.g., trials)
- Append-only `audit_log` with Postgres trigger blocking UPDATE/DELETE (§24)
- snake_case table and column names
- JSONB for flexible structured fields (settings, params, metrics, payloads)
- All foreign keys explicit; no implicit relationships
- Indexes on (tenant_id, created_at) for tenant-scoped tables (MVP4+)

**API conventions:**

- REST + JSON, URL-versioned at `/api/v1`
- RFC 7807 Problem Details for errors with `error_code` + `retryable` extensions (GA v1)
- Cursor pagination on list endpoints; opaque server-issued cursors
- `Idempotency-Key` header on POST/PATCH/DELETE (GA v1)
- W3C `traceparent` header propagated through every call boundary
- Rate-limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

**Logging conventions:**

- Structured JSON via structlog
- Required fields: `ts`, `lvl`, `msg`, `service`, `trace_id`, `span_id`
- `msg` field draws from canonical event catalog in `src/events.py` (MVP2+)
- PII redaction processor runs before emission (MVP2+)

**Secrets management:**

- Mounted secret files only — never set in environment variables
- 1Password / Vault / SSM / equivalent for the source of truth
- API keys hashed with Argon2id at rest

### Decision register summary

| # | Decision | Status | Rationale | Reference |
|---|---|---|---|---|
| 1 | Python 3.12+ async + FastAPI for backend | Locked | Mature ecosystem, async-native, OpenAPI integration | §7, §15 |
| 2 | Next.js 14+ for UI | Locked | App Router, mature SSR/SSG, ecosystem default | §7, §22 |
| 3 | Postgres 16 for state | Locked | Mature, supports all features needed (JSONB, triggers, RDBStorage for Optuna) | §9, §22 |
| 4 | SQLAlchemy 2.0 async + Alembic for ORM | Locked (this section) | Mature, predictable, full Postgres feature support | this §28 |
| 5 | shadcn/ui + Tailwind for UI | Locked (this section) | Modern default for developer-tool dashboards; fully customizable | this §28 |
| 6 | TanStack Query for data fetching | Locked (this section) | React server-state default; rich caching/retries | this §28 |
| 7 | Trunk-based + Conventional Commits | Locked (this section) | Fast iteration, auto-changelog | this §28 |
| 8 | LangGraph for orchestration in GA v1 | Locked | State graph fits multi-agent flow; PostgresSaver for persistence | §15 |
| 9 | OpenAI for LLM in MVP1; multi-provider in MVP4+ | Locked | Validated quality at start; adapter pattern enables provider neutrality | §15, §27 |
| 10 | Langfuse + SigNoz for observability (MVP2+) | Locked | Self-hosted, local-first, OTel-native | §15, §24 |
| 11 | Apache 2.0 license + DCO contributions | Locked | Patent grant, enterprise-friendly, OSS standard | §29 |
| 12 | RelyLoop as project name | Locked (pending TESS) | Earns its meaning twice; trademark verification underway | §29, §30 #23 |
| 13 | Docker Compose primary deployment; Helm in v1.5+ | Locked | Self-hosted, single-VM-friendly | §25 |
| 14 | Optuna + ir_measures for the loop | Locked | Provider-abstracted IR evaluation; well-tested; fits the parallel async pattern | §13, §14 |
| 15 | uv (Python) + pnpm (TS) for deps | Locked | Modern, fast, reproducible | this §28 |
| 16 | UUIDv7 for primary keys | Locked | Sortable, time-ordered, client-generatable | §9 |
| 17 | Trunk-based + Conventional Commits + DCO | Locked (this section) | Auto-changelog, audit-friendly, low-ceremony | this §28 |

### What's deliberately out of scope

To keep this register honest, a short list of choices that adopters might assume but aren't:

- **Kubernetes-native deployment** — not in v1; Helm chart added in v1.5+
- **Project-controlled SaaS or hosted offering** — explicitly rejected (§29 OSS positioning)
- **Multi-region / multi-cloud** — not supported; single-VM Compose deployment
- **Mobile UI** — not built; UI is responsive but desktop-first
- **i18n / localization** — UI is English-only in v1; community-driven later
- **WCAG AA compliance for the UI** — aspirational; not gated in v1 release criteria
- **Real-time production-search-path participation** — rejected per §4 Non-goals (Path B)

## 29. OSS positioning & governance

RelyLoop is built and released as open source for enterprise search platform teams. This section captures the project-level decisions that shape adoption, contribution, and long-term sustainability — distinct from the product spec above.

### Naming decision

The project is named **RelyLoop**. The name combines:

- **Rely** — reliability, dependability, trust. The brand promise: an automated relevance system platform teams can trust to run unattended overnight against production-bound configs without surprises.
- **Loop** — the Karpathy-style optimization loop, the agent feedback loop, the iterative tuning cycle. The technical core that differentiates the project from manual workbenches like Quepid.

The compound reads as "rely on the relevance loop" — earning its meaning from both the brand promise and the substance of what the tool does. Insiders catch the wordplay ("Rely" phonetically nods to "Relevance"); newcomers get a memorable name without needing to.

**Rejected alternatives:**

| Candidate | Why rejected |
|---|---|
| Relevance Copilot | Trademark risk — Microsoft has registered "Copilot" across software, AI assistants, and dev tools, and has been aggressive about defending it. Generic-sounding given the saturation of "<X> Copilot" naming in AI tooling. |
| SearchSmith | "Search<X>" prefix is heavily saturated; "Smith" suffix is overused in tech. Mild but real brand-flatness. |
| SearchTuner | Pure descriptive mark — weak trademark, no brand power, narrow scope ("Tuner" implies tuning only, undersells the eval/agent/lineage layers). |
| RelTuner | Better prefix than SearchTuner, but inherits the "Tuner" descriptive weakness. |
| RelLoop | Strong on substance but reads as an abbreviation, not a name. Verbal recall is weaker than RelyLoop. |

**Pre-launch verification:**

- Initial web searches found no existing software product named "RelyLoop" — trademark space appears clear.
- USPTO TESS lookup for "RELYLOOP" in software-related classes (9 and 42) is required pre-public-announcement and tracked as an open question in §29.
- Domain registration for `relyloop.com`, `relyloop.io`, and `relyloop.dev`, plus the `relyloop` GitHub organization, should be secured before public announcement to prevent squatting once the name is published.

The Microsoft Loop product (collaboration app, separate goods/services category) was considered for trademark conflict and assessed as low-risk: "RelyLoop" is a distinct compound that does not phonetically resemble or visually evoke "Microsoft Loop," and the categories of use are non-overlapping. Pre-launch TESS confirmation will resolve any residual uncertainty.

### Audience

The primary intended adopter is an internal search platform team at a medium-to-large enterprise that runs search engines (Elasticsearch, Lucidworks Fusion, Solr) for one or more downstream "customers" (other product teams, business units, or external clients). These teams typically share three pains:

- Manual relevance tuning is slow and expert-bound; doesn't scale across many indexes/customers
- Quantifying relevance improvements for stakeholders is hard without a standing eval harness
- AI/LLM tooling for search is hyped but practical, deployable, customer-data-respecting answers are scarce

Secondary adopters: search-as-a-service vendors building on top of OSS engines, and sophisticated single-product teams with one important search.

### License

**Apache License 2.0.** Standard `LICENSE` and `NOTICE` files at the repository root. The license choice is deliberate:

- The explicit patent grant matters for a project in the search and LLM space, where patent activity is high. Contributors grant patent licenses for any patents reading on their contributions, and patent litigation against users terminates that license — meaningful protection that MIT does not offer.
- Apache 2.0 is the de facto license for similar projects (OpenSearch, Solr, Lucene, Kubernetes, ClickHouse). Enterprise procurement and security review processes overwhelmingly accept it.
- Compatible with all upstream dependencies (LangChain, Langfuse, SigNoz, Optuna, ir_measures, FastAPI, Postgres are all permissively licensed).

If at some future date the project needs to consider relicensing (e.g., a community fork) the Apache 2.0 starting point gives clean optionality.

### Governance and maintainership

soundminds.ai bootstraps the project as the initial maintainer, with the explicit goal of transitioning to a community-maintained model over 12–24 months. The path forward:

- **Phase 1 (months 0–6).** soundminds.ai is sole maintainer. Focus on shipping v1, validating with 2–3 design-partner platform teams, hardening the docs.
- **Phase 2 (months 6–18).** Promote external contributors who have demonstrated sustained engagement (substantive PRs, issue triage, or adapter implementations) to maintainer status. Establish an RFC process for breaking changes. Publish a public roadmap.
- **Phase 3 (months 18+).** Consider donating to a foundation (Apache Software Foundation, LF AI & Data, or independent governance under a CNCF-style model) once the project has multiple companies meaningfully invested.

A `MAINTAINERS.md` file lists current maintainers with their areas of focus. A `GOVERNANCE.md` documents decision-making process and conflict resolution. Both updated as the project evolves.

### Contribution model

**DCO (Developer Certificate of Origin)**, not CLA. Every commit carries `Signed-off-by:` declaring the contributor has rights to contribute under the project license. This is simpler than a CLA, doesn't require contributors to sign a separate document, and is the model used by Linux, Kubernetes, and most modern OSS.

Required documents:

- `CONTRIBUTING.md` — how to set up dev environment, run tests, propose changes, sign commits
- `CODE_OF_CONDUCT.md` — adopted from Contributor Covenant 2.1
- `SECURITY.md` — how to report vulnerabilities (private email or GitHub Security Advisory; response SLA)
- Issue templates (bug, feature request, adapter contribution)
- PR template (with DCO reminder, test/docs checklist)

### Versioning and compatibility

**Semantic Versioning (SemVer 2.0.0)** for the project as a whole. The contracts that need backwards-compatibility guarantees:

- HTTP API surface (versioned via `/api/v1`, `/api/v2` — never break v1 within a major)
- OpenAPI schemas
- Database schema (migrations only forward; downgrades are documented best-effort)
- Adapter Protocol contracts (engine, LLM provider, Git provider) — additions are minor, removals or signature changes are major
- CLI flags (if a CLI exists)
- Webhook event payloads

Internal contracts (Python module imports, internal HTTP between services) are not stable across minor versions.

Release cadence: roughly monthly minor releases through Phase 1; cadence community-determined thereafter. Patch releases as needed for security and serious bugs.

### Distribution

- **Source.** GitHub repository under the `soundminds-ai` organization (or a project-dedicated organization once formed). Public from day one.
- **Container images.** Published to GitHub Container Registry (`ghcr.io/relyloop/api`, `…/worker`, `…/ui`). Signed with [cosign](https://github.com/sigstore/cosign). Multi-arch (amd64 + arm64).
- **Helm chart** (v1.5+). Published to a project-owned Helm repository on GitHub Pages or [ArtifactHub](https://artifacthub.io/). Tracks the same version cadence as the application.
- **Python SDK** for the API (v1.5+). Published to PyPI as `relyloop-sdk`. Auto-generated from the OpenAPI spec.

No project-controlled SaaS or hosted offering — the "pure OSS, no paid tier" stance. Operators can host their own.

### Telemetry stance

**The application emits zero project-level telemetry.** No anonymous usage data, no phone-home, no opt-in beacons. This is documented in the README, asserted in the privacy policy, and enforceable by the absence of telemetry-emitting code (CI grep gate against known telemetry-pattern strings: `posthog`, `segment.com`, `analytics.`, etc.).

The application *does* emit traces, logs, and LLM call data — but only to the operator's own self-hosted SigNoz and Langfuse, which never leave the operator's network.

### Adopter-facing documentation

Beyond this spec, the following ship with v1:

- `README.md` — 5-minute quickstart, value proposition, links
- `docs/08_guides/install.md` — full Docker Compose install with screenshots
- `docs/03_runbooks/operate.md` — production operator's guide (TLS, scaling, backup, monitoring, upgrade)
- `docs/08_guides/tutorial-first-study.md` — hands-on walkthrough with sample data
- `docs/01_architecture/architecture.md` — distilled version of this spec for deep-dive readers
- `docs/07_research/comparison.md` — vs. Quepid, RRE, LangSmith, vendor offerings (factual, not promotional)
- `docs/08_guides/migration-from-quepid.md` — for Quepid users, importing query sets and judgment lists
- `docs/08_guides/cookbook.md` — recipes for common patterns
- `docs/08_guides/faq.md`
- `docs/09_decisions/` — Architecture Decision Records for the major choices (LangGraph, Langfuse, SigNoz, Apache 2.0 license, no-MCP, etc.)

API reference is auto-generated from OpenAPI and rendered with Stoplight or Redoc at the operator's `/docs` URL.

### Design-partner engagement

Before the public launch, identify 2–3 platform teams willing to be design partners:

- They get pre-release access and direct support
- They commit to running v1 against a real (non-toy) workload and providing structured feedback
- Their use cases shape the early roadmap
- A public reference (with permission) at launch

Without design partners, OSS projects in this space often ship features that don't survive contact with real workloads. soundminds.ai is responsible for sourcing and managing the design-partner relationships through Phase 1.

### Comparison with alternatives

The README's `comparison.md` covers the full set; representative summary:

| Tool | OSS? | Multi-engine? | Karpathy loop? | Local LLM obs? | Apache 2.0? |
|---|---|---|---|---|---|
| RelyLoop | yes | ES + Fusion (+ Solr v2) | yes | yes | yes |
| Quepid | yes | yes | no | no LLM | yes |
| RRE | yes | yes | no | no LLM | Apache 2.0 |
| LangSmith | no | n/a | partial | hosted only | n/a |
| Phoenix (Arize) | yes | n/a | no | yes | Apache 2.0 |
| Lucidworks Springboard | no | Fusion only | partial | n/a | n/a |
| Coveo / Algolia / Bloomreach | no (SaaS) | vendor only | partial (proprietary) | n/a | n/a |

The defensible position: **Quepid + LLM-driven Karpathy loop + agent-first API + local-first observability + multi-engine + Git-as-source-of-truth**, all OSS under Apache 2.0. No other project covers this combination.

### Sustainability risks

A few honest acknowledgements:

- **Maintainer burnout.** Single-company OSS projects often stall when the sponsoring company shifts priorities. Phase 2 transition to multi-maintainer is the mitigation; Phase 3 foundation donation is the long-term backstop.
- **Vendor competition.** Coveo, Algolia, Bloomreach, Lucidworks, and AI-search vendors will add similar capabilities in commercial form. The OSS angle holds value if the community moves faster than any single vendor; it loses if the project stagnates.
- **LLM cost legibility.** Adopters need clear cost projection tooling (deferred to v1.5). Without it, LLM-driven tuning can produce sticker shock.
- **Eval set maintenance.** OSS contributors maintaining sample query sets / judgments is harder than maintaining code, because data goes stale and licensing is fuzzier. Document the contribution policy carefully, prefer contributor-owned local sets over project-wide reference sets.

## 30. Open questions

1. **OpenAI cost ceiling.** A single overnight study runs hundreds of LLM calls (search-space proposal, digest, judgment generation if regenerating). What's our monthly budget per relevance engineer? Need a cost dashboard and per-user quotas in v1.5.
2. **PR rate.** If the tool produces 5+ PRs per night per engineer, will the config repo's reviewers drown? May need batching or a "stage-then-promote" two-tier flow earlier than v2.
3. **Judgment freshness.** Judgments degrade as the index changes (new docs, deleted docs). What's our re-judgment cadence? Auto-trigger or manual?
4. **Production query set sourcing.** v1 assumes engineers hand-author or import query sets. Without behavior analytics, where do queries come from? Application logs? Recommend a one-shot log import tool early in v1.
5. **Template safety.** Could a Jinja template be malicious (SSRF via crafted JSON)? We sandbox via the adapter's render path, but worth a security review before exposing template editing to non-admins.
6. **Parameter ranges.** When the LLM proposes ranges, can it propose ranges that are out of bounds for the engine (e.g., negative boost)? Validator catches this, but worth defensive testing.
7. **Agent runtimes to test against in v1.5.** The API is framework-agnostic, but we should pick 2–3 reference agent runtimes (LangGraph? OpenAI Assistants? Bedrock Agents? Claude Agent SDK with HTTP tools? a hand-rolled agent?) to validate the workflow ergonomics on. Choice influences the worked example in `x-agent-workflows`.
8. **Service-account naming and rotation policy.** Are agent service accounts shared across multiple agent codebases or always one-per-agent? What's the rotation cadence and the rotation runbook? Affects API-key UX in v1.5.
9. **Fusion pipeline forking strategy.** When a study recommends parameter changes that effectively constitute a new pipeline shape (e.g., a previously-disabled stage now matters), should the tool propose creating a *new* pipeline version (new ID) or modifying the existing one in place? Implications for promotion across environments and for rollback. Default v1 stance: edit in place; revisit if it bites us.
10. **Fusion Signals enablement plan.** When does the user enable Signals in DEV, then STAGING, then PROD? What sample sizes do we need before signals-derived judgments are trustworthy enough to drive studies? Belongs in the v1.5 kickoff conversation.
11. **Fusion app/collection scoping.** Some Fusion installations use one app per collection; others use one app for many collections. Does our `clusters.engine_config.app` model fit, or do we need a finer-grained "app + collection" target? Currently spec'd as one app per cluster row; revisit if the user has multi-app clusters.
12. **Lucidworks eval license policy for engineers.** When a developer needs hands-on Fusion access (recording new cassettes, reproducing a bug, validating new adapter parameters), what's the request flow? Options: (a) negotiate a longer-term Lucidworks dev license that the team shares, (b) rely on the org's existing Fusion dev cluster with per-engineer scoped credentials, (c) per-engineer 30-day eval licenses on demand. Affects developer-onboarding ergonomics. Recommended default: option (b) for routine work, option (c) for engineers doing initial adapter implementation.
13. **Cassette refresh cadence and ownership.** Who is responsible for re-recording the Fusion replay cassettes when the upstream Fusion API changes (e.g., a Fusion version upgrade)? Include in the v1 runbook. Consider a quarterly cassette-freshness CI check that pings the dev cluster and flags drift.
14. **Mock Fusion fidelity scope.** The `fusion-mock` service emulates a small subset of the Fusion query gateway. How comprehensive should it be — just enough for UI demos, or a high-fidelity simulator suitable for some classes of integration testing? Bigger ambition increases maintenance burden. Recommended default: minimal, demo-only.
15. **LLM eval cadence and triggers.** The Langfuse eval suite runs nightly and on prompt PRs by default. Should it also run on every model-version bump? On every Langfuse upgrade? On a schedule independent of code changes (e.g., monthly model-drift checks against the same prompts)? Affects CI runtime and cost. Recommended default: nightly + on prompt PRs in v1; add monthly drift checks in v1.5 once we have baseline scores to compare against.
16. **Eval gold-set ownership.** Who maintains the `judgment_generation_eval` 200-tuple gold set? Refresh cadence? This is the single most important quality signal for the LLM-as-judge layer; if it drifts or rots, evals stop catching regressions. Recommended default: relevance team owns it, quarterly refresh, with a CI check that flags if the gold set hasn't been touched in 6 months.
17. **Langfuse retention policy.** ClickHouse storage for traces grows linearly with usage. What's the retention period — 30 days? 90 days? 1 year? Affects disk sizing. Recommended default: 90 days for traces, indefinite for eval results (low volume).
18. **v1 scope vs. team size.** v1 is now a 12-week single-engineer effort or ~7 weeks with two engineers. Three options: (a) commit two engineers and ship in 7 weeks, (b) accept 12 weeks for one engineer, (c) defer one major area (most reversibly: cut Langfuse and SigNoz from v1 — accept basic logging only — and add them in v1.5 once the core loop is proven; saves ~2 weeks). Recommended default: (a) if a second engineer is available, otherwise (b). Option (c) is structurally riskier because retrofitting observability is painful.
19. **E2E test budget and frequency.** E2E tests use real OpenAI calls (~$5/run cap) and hit the shared Fusion dev cluster. At per-merge-to-main + nightly cadence, this could be ~$200/month in OpenAI costs alone, plus Fusion dev cluster contention. Worth confirming the budget envelope and whether per-merge E2E is the right cadence (alternative: nightly only + on-demand via PR label).
20. **Performance benchmark suite for v1.5.** What hot paths are most worth regressionproofing — trial execution, OpenAPI serving, agent first-token, the digest LLM call? Pick 3–5 for v1.5 `pytest-benchmark` suite and decide pass/fail thresholds.
21. **Path A vs. Path B long-term commitment.** v1 is strictly Path A (experimentation and change management). Path B (production quality monitoring, bandit-style online learning, shadow validation) is documented as a v2 direction but explicitly deferred. The strategic question is whether soundminds.ai commits to Path B as the long-term direction once v1 is shipped and adopted, or stays focused on Path A and treats Path B as community-driven expansion / fork territory. Affects roadmap signals to early adopters and contributor recruitment. Recommended default: revisit after 2–3 design partners are running Path A in production and we have real signal on what they want next. Early bandit-capability scoping (which architectural shape — external coordinator vs. in-engine, see §27) can begin in parallel without committing to v2 timelines.
22. **Bandit architectural shape if Path B is pursued.** External coordinator (tool maintains bandit state, search service calls a tool endpoint per query) vs. in-engine (bandit logic embedded in Solr request handler or Fusion stage, driven by tool-published config). External coordinator is cleaner but adds hot-path latency; in-engine has no latency but is harder to debug and requires per-engine implementations. The bandit decision has the most architectural blast radius of any Path B capability — worth reaching alignment before any work begins.
23. **Pre-launch RelyLoop trademark and namespace verification.** Before public announcement, the following must be completed and signed off:
    - **USPTO TESS search** for "RELYLOOP" and stylization variants (RelyLoop, Rely Loop, Rely-Loop) in software-related classes (Class 9 — downloadable software; Class 42 — SaaS / IT services). If a live registration or pending application is found, escalate to legal review before proceeding.
    - **Domain registration** for `relyloop.com`, `relyloop.io`, `relyloop.dev`, and ideally `relyloop.org`. Cost is minimal; squatting after public announcement is expensive.
    - **GitHub organization** `relyloop` reserved (and `rely-loop` as a backup). Ditto for npm scope `@relyloop` and PyPI package prefix `relyloop-*` to prevent typosquatting.
    - **Social handles** (X / LinkedIn / Mastodon / Bluesky) reserved for project announcements, even if unused initially.
    - Recommended owner: soundminds.ai's legal/operations function, with a target completion 2–3 weeks before the v1 public announcement date.

---

*End of spec. Next steps: review with the team, lock open questions where possible, kick off v1 milestone planning.*
