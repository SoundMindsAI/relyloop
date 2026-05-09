# MVP1 Architecture — Navigation Summary

**Status:** This is the architecture as it exists in MVP1 ("The Loop"). Each topical doc covers all releases; this page is a fast entry point that filters them down to MVP1's active scope.

**For product context:** [docs/00_overview/product/relevance-copilot-spec.md §27](../00_overview/product/relevance-copilot-spec.md) ("MVP1 / v0.1 — The Loop").

---

## What MVP1 ships

A single `make up` (which auto-generates required secrets on first run, then invokes `docker compose up -d`) brings up 6 containers that demonstrate the Karpathy loop end-to-end on a developer's laptop. A relevance engineer registers a cluster, defines a query set, generates LLM judgments, runs a study, gets a digest, and opens a GitHub PR — all without leaving the browser.

**Active topics in MVP1:**

| Topic | Doc | What's MVP1-active |
|---|---|---|
| System topology | [`system-overview.md`](system-overview.md) | 6-container stack (Postgres, Redis, API, worker, ES, OpenSearch). UI runs via `pnpm dev` (not yet a Compose service). |
| Stack | [`tech-stack.md`](tech-stack.md) | Backend: Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + pytest + ruff + mypy. Frontend: Next.js 14 + shadcn/ui + Tailwind + TanStack Query. Infra: Postgres 16 + Redis 7 + Docker Compose. |
| API conventions | [`api-conventions.md`](api-conventions.md) | `/api/v1/<resource>` prefix; structured error envelope with `error_code` + `retryable`; cursor pagination; per-request `X-Request-ID` for log correlation. **No** `traceparent` propagation through downstream boundaries (MVP2). **No** rate limiting (MVP4). **No** auth surface (MVP4). |
| Data model | [`data-model.md`](data-model.md) | 13 application tables. NO `tenants`, NO `tenant_id`, NO `created_by`, NO `users`/`tenant_memberships`/`api_keys`/`audit_log`, NO lineage columns. UUIDv7 PKs; soft-delete via `deleted_at`; JSONB for flexible fields. |
| Engine adapters | [`adapters.md`](adapters.md) | One `ElasticAdapter` handling Elasticsearch (8.11+ / 9.x) AND OpenSearch (2.x / 3.x). Auth kinds: `es_apikey`, `es_basic`, `opensearch_basic`. |
| Deployment | [`deployment.md`](deployment.md) | Docker Compose, 6 containers bound to `127.0.0.1`. Secrets as mounted files. No TLS, no reverse proxy, no SSO. |

## What's NOT in MVP1

These appear in the topical arch docs because the docs cover all releases — but they're **not MVP1 work**. Skip them while building MVP1. Per-release timing is the canonical [`tech-stack.md` §"Canonical release matrix"](tech-stack.md); the lists below are derived from it.

### Reserved for MVP2 ("Observable")
- `langfuse-web`, `langfuse-worker`, `clickhouse` — LLM observability stack
- `signoz`, `signoz-otel-collector` — distributed tracing
- **`audit_log` table + Postgres immutability trigger** (no users/tenants yet — `actor_id`/`tenant_id` nullable, no FKs; `actor_type` ENUM (`system`, `agent`, `anonymous`); FKs added at MVP4)
- Lineage columns on `judgments`, `digests`, `proposals` (`langfuse_trace_id`, `prompt_version`, `input_hash`)
- PII redaction processor in structlog
- Canonical event catalog (`backend/app/events.py`)
- Trace context propagation through API → Redis → worker → adapter → engine (custom Arq enqueue→pickup serialization)
- Forking studies with narrowed search-space ranges
- Slack notifications on PR open
- Validation re-run on prod after staging win

### Reserved for MVP3 ("Production Stacks")
- **`LucidworksFusionAdapter`** (and the `fusion-mock` Compose service)
- GitLab and Bitbucket as Git providers; multi-Git-provider abstraction (`GitProvider` Protocol)
- Adapter contract test suite (every `SearchAdapter` and `GitProvider` runs the same conformance suite)
- AWS managed OpenSearch (`opensearch_sigv4` auth kind activates)
- Production-style install: Caddy + Let's Encrypt TLS, managed Postgres/Redis. **No SSO yet** — production-stack hardening only.
- Container image scanning (Trivy)
- Image signing (cosign) — *may slip earlier into chore_tutorial_polish if cheap*

### Reserved for MVP4 ("Multi-tenant, Multi-LLM")
- `tenants`, `tenant_memberships`, `users`, `api_keys` tables
- `tenant_id` column on every user-facing table (with backfill auto-creating a `default` tenant)
- FK constraints added to `audit_log.actor_id` and `audit_log.tenant_id`; `actor_type` ENUM extended to include `user`
- **SSO for humans** via reverse proxy (oauth2-proxy or Authelia injecting `X-Auth-Email`); proxy verified by mTLS or shared secret
- **Argon2id-hashed bearer API keys** for service accounts (`Authorization: Bearer <key>`)
- Roles: `viewer` / `runner` / `tenant_admin` (per-tenant) + `platform_admin` (cross-tenant)
- Multi-LLM provider abstraction (Anthropic, AWS Bedrock, Google Vertex, Ollama, vLLM) via LangChain provider packages
- LangChain `RedisCache` for LLM responses

### Reserved for GA v1 ("Production-ready")
- LangGraph orchestrator + `PostgresSaver` (replaces the plain `openai` SDK + function calling)
- Full RFC 7807 Problem Details for errors
- `Idempotency-Key` header on POST/PATCH/DELETE
- Helm 3 chart for Kubernetes deployments
- Container scanning, deps audit, image signing all operational
- 90% backend coverage gate (up from 80% in MVP1)

### Reserved for v2+
- `SolrAdapter` (pure Apache Solr support)

## MVP1 feature sequencing (locked)

The 12 MVP1 features have a partial-order dependency. Migration ownership per [`data-model.md` §"MVP1 table inventory + migration ownership"](data-model.md) determines the order:

```
infra_foundation
    ↓
infra_adapter_elastic           ← creates clusters + config_repos (full shape)
    ↓
feat_study_lifecycle (schema)   ← creates studies + trials + query_* + judgment_lists +
    ↓                              proposals (full shape, all 7 tables); NO orchestrator yet
infra_optuna_eval               ← reads studies, writes trials via run_trial worker
    ↓
feat_study_lifecycle (orch.)    ← study CRUD API + start_study orchestrator (enqueues run_trial)
    ↓
feat_llm_judgments              ← creates judgments (child); writes judgment_lists rows
    ↓
feat_digest_proposal            ← creates digests; INSERTs into proposals
    ↓
feat_github_pr_worker           ← writes proposals.pr_url + pr_open_error
    ↓
feat_github_webhook             ← writes proposals.pr_state + config_repos.webhook_registration_error

feat_studies_ui     (parallel after feat_study_lifecycle orchestrator + feat_digest_proposal + feat_llm_judgments)
feat_chat_agent     (parallel after feat_studies_ui)  ← creates conversations + messages tables
feat_proposals_ui   (parallel after feat_studies_ui + feat_github_pr_worker)
chore_tutorial_polish (last; depends on all)
```

**Note on feat_study_lifecycle split:** the spec ships as one feature folder but should be planned as two epics — (1) "schema" (just the migration + Pydantic models) which unblocks `infra_optuna_eval`, then (2) "API + orchestrator" which depends on `infra_optuna_eval`'s `run_trial` worker existing. See [`feat_study_lifecycle/feature_spec.md` §"Implementation sequencing within this feature"](../02_product/planned_features/feat_study_lifecycle/feature_spec.md).

Two-engineer compression: A drives the backend chain (study_lifecycle → optuna_eval → llm_judgments → digest_proposal → github_pr_worker → github_webhook); B drives the UI chain (studies_ui → chat_agent → proposals_ui) starting once the consumed APIs are stable. They re-converge on chore_tutorial_polish.

## Per-feature reading guide

When you start work on an MVP1 feature, read the topical arch docs in this order:

| Feature folder | Required reading |
|---|---|
| `infra_foundation` | [`tech-stack.md`](tech-stack.md), [`system-overview.md`](system-overview.md), [`deployment.md`](deployment.md), [`api-conventions.md`](api-conventions.md) |
| `infra_adapter_elastic` | [`adapters.md`](adapters.md), [`data-model.md`](data-model.md), [`api-conventions.md`](api-conventions.md) |
| `infra_optuna_eval` | [`tech-stack.md`](tech-stack.md), [`data-model.md`](data-model.md), plus the to-be-authored `optimization.md` |
| `feat_study_lifecycle` | [`data-model.md`](data-model.md), [`api-conventions.md`](api-conventions.md), [`system-overview.md`](system-overview.md) (worker pool detail) |
| `feat_llm_judgments` | [`data-model.md`](data-model.md), plus the to-be-authored `llm-orchestration.md` |
| `feat_digest_proposal` | [`data-model.md`](data-model.md), `llm-orchestration.md` |
| `feat_github_pr_worker` | [`data-model.md`](data-model.md), `apply-path.md` (TBA) |
| `feat_github_webhook` | [`api-conventions.md`](api-conventions.md), `apply-path.md` (TBA) |
| `feat_studies_ui` | [`tech-stack.md`](tech-stack.md) (frontend section), `ui-architecture.md` (TBA) |
| `feat_chat_agent` | [`tech-stack.md`](tech-stack.md), `llm-orchestration.md` (TBA), `agent-tools.md` (TBA) |
| `feat_proposals_ui` | [`tech-stack.md`](tech-stack.md) (frontend), `ui-architecture.md` (TBA) |
| `chore_tutorial_polish` | [`deployment.md`](deployment.md) — re-validates the full local-dev experience |

The "TBA" docs are authored alongside their corresponding feature spec.

## Cross-references

- All arch docs in this section: [`docs/01_architecture/`](./)
- MVP1 feature folders: [`docs/02_product/planned_features/`](../02_product/planned_features/)
- MVP1 user stories: [`docs/02_product/mvp1-user-stories.md`](../02_product/mvp1-user-stories.md)
- Umbrella spec MVP1 section: [`docs/00_overview/product/relevance-copilot-spec.md` §27](../00_overview/product/relevance-copilot-spec.md)
