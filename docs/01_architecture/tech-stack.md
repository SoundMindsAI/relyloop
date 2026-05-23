# Tech Stack

**Status:** Adopted for MVP1. Revisited per release as new layers come online.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §28](../00_overview/product/relevance-copilot-spec.md) ("Tech stack & implementation decisions"). This document is the engineering-facing distillation of those decisions, scoped to what's relevant for MVP1 with explicit notes on what activates in later releases.

---

## Canonical release matrix

This is the source-of-truth release matrix that every other arch doc derives from. If a row in this table conflicts with another doc, this table wins. Sourced from umbrella spec lines 17–25 and §27 (per-release detail).

| Release | Theme | Adds on top of previous |
|---|---|---|
| **MVP1 / v0.1** | "The Loop" | ES + OpenSearch adapter (single `ElasticAdapter`); LLM via `openai` SDK pointed at any **OpenAI-compatible endpoint** (`OPENAI_BASE_URL` config; defaults to `https://api.openai.com/v1`; works against Ollama, LM Studio, vLLM, HuggingFace TGI for air-gapped evaluation); GitHub Git provider; single-tenant (no `tenants` table, no `tenant_id`); no auth; basic structured logging; Docker Compose; Apache 2.0 LICENSE; 80% backend coverage gate. **No** native non-OpenAI-compatible providers (Anthropic/Bedrock/Vertex SDKs ship at MVP4), **no** observability stack, **no** audit_log, **no** lineage, **no** Fusion, **no** SSO, **no** API keys. |
| **MVP2 / v0.2** | "Observable" | Langfuse + ClickHouse + SigNoz + OpenTelemetry exporters wired; canonical event catalog; **`audit_log` table + Postgres immutability trigger** (no users/tenants yet — `actor_id`/`tenant_id` nullable, no FKs; FKs added at MVP4); lineage columns (`langfuse_trace_id`, `prompt_version`, `input_hash`) on `judgments`/`digests`/`proposals`; PII redaction; trace context propagation through API → Redis → worker → adapter → engine. |
| **MVP3 / v0.3** | "Production Stacks" | **Lucidworks Fusion adapter** (`auth_kind = fusion_session` and `fusion_jwt`); multi-Git-provider abstraction (GitLab + Bitbucket alongside GitHub); adapter contract test suite; production-style install (TLS via Caddy + Let's Encrypt, managed Postgres/Redis); AWS managed OpenSearch (`auth_kind = opensearch_sigv4` activates). **No** SSO/auth yet (production-stack hardening only). |
| **MVP4 / v0.4** | "Multi-tenant, Multi-LLM" | `tenants` + `tenant_memberships` + `users` + `api_keys` tables; `tenant_id` columns on every user-facing table (with backfill); roles `viewer` / `runner` / `tenant_admin` (per-tenant) + `platform_admin` (cross-tenant); **SSO via reverse proxy** (oauth2-proxy or Authelia injecting `X-Auth-Email`); **Argon2id-hashed bearer API keys** for service accounts; **native non-OpenAI-compatible LLM providers via LangChain `BaseChatModel` abstraction** (Anthropic, AWS Bedrock, Google Vertex AI); per-tenant LLM provider selection + cost rollups; FK constraints added to `audit_log.actor_id` / `audit_log.tenant_id`. (OpenAI-compatible providers — including Ollama, LM Studio, vLLM, HuggingFace TGI — already work in MVP1 via `OPENAI_BASE_URL`.) |
| **GA v1 / v1.0** | "Production-ready" | **LangGraph orchestrator** (replaces plain `openai` SDK + function calling); `PostgresSaver` for resumable conversations; full RFC 7807 Problem Details on errors; `Idempotency-Key` header on POST/PATCH/DELETE; Helm 3 chart; container scanning (Trivy), deps audit (pip-audit/npm audit), image signing (cosign keyless OIDC); 90% backend coverage gate (up from 80% in MVP1). |
| **v1.5+** | post-GA | Helm chart maturity, Kubernetes-native operator. |
| **v2+** | post-GA | Apache Solr adapter (`auth_kind = solr_basic` activates). |

**Audit-without-users design:** MVP2 ships `audit_log` with `actor_id` / `tenant_id` as nullable UUIDs with **no FK constraints**, plus an `actor_type` ENUM constrained to `system` / `agent` / `anonymous`. MVP4 adds the FK constraints, extends `actor_type` to include `user`, and backfills `tenant_id` from the auto-created `default` tenant. Pre-MVP4 audit rows keep `actor_id = NULL`. See [`data-model.md` §"`audit_log`"](data-model.md) for the schema.

---

## Backend

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.13+ (async) | Type hints required; `mypy --strict` is enforced. Bumped from 3.12 → 3.13 on 2026-05-12 (current stable; 3.12 still works since `requires-python = ">=3.13"` is the new floor — 3.12 callers must upgrade). |
| Web framework | FastAPI | Auto-generates OpenAPI from Pydantic models. |
| ORM | SQLAlchemy 2.0 (async) | All queries through the ORM; no raw SQL except in migrations. |
| DB driver | asyncpg | Required by SQLAlchemy async. |
| Migrations | Alembic | `alembic revision --autogenerate` is the standard workflow. |
| Validation | Pydantic v2 | Used for: API request/response, tool args, eval datasets, settings. |
| Settings | Pydantic Settings | Loads from env + mounted secrets files. |
| HTTP client | httpx (async) | One client instance per upstream service (cluster, OpenAI, GitHub). |
| Logging | structlog | Structured JSON to stdout. |
| Queue / workers | Arq + Redis 7 | Async-native; workers are separate processes. |
| Optimization | Optuna with TPE sampler + RDBStorage | RDBStorage points at the same Postgres as the app. |
| IR evaluation | ir_measures | Provider-abstracted; wraps multiple IR-evaluation backends behind a typed metric-object DSL; consistent metrics across engines. |
| LLM SDK (MVP1) | `openai` Python SDK with function calling | LangGraph deferred to GA v1. No provider-abstraction layer in MVP1 — direct OpenAI calls. |
| Auth — humans (MVP4+) | SSO via reverse proxy (oauth2-proxy or Authelia); proxy injects `X-Auth-Email` header; API trusts the header only when verified by mTLS or a shared secret | Not present in MVP1–3. No password storage in RelyLoop itself — identity provider owns credentials. |
| Auth — service accounts (MVP4+) | Bearer API keys (`Authorization: Bearer <key>`); keys hashed with Argon2id (passlib) at rest | Not present in MVP1–3. Per-key role + scopes + expiration; revocation via `revoked_at`. |
| Testing | pytest + pytest-asyncio + pytest-mock + pytest-recording | `pytest-recording` cassettes are checked in for every external HTTP integration. |
| Coverage | coverage.py | CI gate: 80% backend Python (MVP1) → 90% (GA v1). |
| Linter / formatter | ruff (`check` + `format`) | Replaces flake8 + isort + black. |
| Type checker | mypy `--strict` | No `Any` without explicit annotation. |
| Dependency mgmt | uv | Lockfile-based; replaces pip + pip-tools + virtualenv. |
| Pre-commit | pre-commit framework | Hooks: ruff, mypy, eslint, prettier. |

## Frontend

| Layer | Choice | Notes |
|---|---|---|
| Language | TypeScript (`--strict` + `noUncheckedIndexedAccess`) | |
| Framework | Next.js 16 (App Router, Turbopack) | Bumped from 14 on 2026-05-12 (`infra_frontend_stack_refresh`); React 19 as a peer. |
| UI components | shadcn/ui | Components copied into the repo, not an npm dependency — fully customizable. |
| Styling | Tailwind CSS 4 (CSS-first config via `@import "tailwindcss"`) | Bumped from 3 on 2026-05-12; legacy `tailwind.config.ts` deleted, source paths auto-detected. |
| Server state | TanStack Query | Caching, retries, optimistic updates, mutations. |
| Forms | React Hook Form + Zod | Zod schemas can be reused for API request validation. |
| Charts | Recharts | Sufficient for parameter-importance bars, scatter plots, trial-progress lines. |
| Streaming | `fetch()` with `ReadableStream` (SSE-framed body over POST) | Native `EventSource` is GET-only; the chat surface POSTs the user message in the body so we use `fetch()` streaming. See [`ui-architecture.md` §"Streaming chat"](ui-architecture.md). |
| Testing | Vitest 4 + msw | msw mocks HTTP at the network layer. Vitest bumped from 2 on 2026-05-12. |
| Linter | ESLint 9 (flat config, `eslint.config.mjs`) + Next + security plugins | ESLint 10 was attempted but hit an `eslint-plugin-react` 7.37 vs ESLint-10 API incompat; backed off to 9 (matches `eslint-config-next` 16's tested baseline). |
| Formatter | prettier | |
| Type checker | `tsc --noEmit --strict` | Runs in CI. |
| Dependency mgmt | pnpm | Lockfile-based. |

## Infrastructure

| Layer | Choice | MVP1 status |
|---|---|---|
| Database (app) | Postgres 16 | Single instance. Holds app state + Optuna RDBStorage. |
| Cache / queue | Redis 7 | Used by Arq for the worker queue. |
| Search engines (targets) | Elasticsearch 8.11+ / 9.x; OpenSearch 2.x / 3.x | Lucidworks Fusion (MVP3) and Solr (v2+) are NOT in MVP1. |
| Reverse proxy | Caddy 2 | NOT in MVP1. **MVP3** adds Caddy + Let's Encrypt TLS for production-style network exposure (no SSO yet — trusted-network deployments only). **MVP4** adds oauth2-proxy or Authelia in front of Caddy for SSO. |
| Trace storage (LLM) | ClickHouse 24 | NOT in MVP1 (Langfuse is MVP2+). |
| Container runtime | Docker 24+ with Compose v2 | MVP1 deployment target. |
| Helm chart | Helm 3 | NOT in MVP1 (v1.5+). |
| Secrets at runtime | Mounted secret files | Never in env vars — see §"Secrets" below. |
| Backup target | Encrypted S3-compatible | NOT in MVP1 (operator's responsibility for laptop installs). |

## CI/CD

| Layer | Choice | MVP1 status |
|---|---|---|
| CI/CD platform | GitHub Actions | One workflow in MVP1 (`.github/workflows/pr.yml`); five workflows by GA v1. |
| Container scanning | Trivy | NOT in MVP1 (GA v1). |
| Python SAST | bandit | NOT in MVP1 (GA v1). |
| Python deps audit | pip-audit | NOT in MVP1 (GA v1). |
| TS deps audit | npm audit | NOT in MVP1 (GA v1). |
| Image signing | cosign (keyless OIDC via GitHub) | NOT in MVP1 (target: chore_tutorial_polish if cheap, otherwise MVP3). |
| Branching | Trunk-based | Short-lived feature branches off `main`. |
| Commit format | Conventional Commits | Auto-generated changelogs in GA v1; MVP1 enforces format via pre-commit. |
| Versioning | SemVer 2.0 | MVP1 = `0.1.0`; the leading zero signals pre-1.0 instability. |

## Conventions

### Code organization

- Single monorepo: `relyloop/relyloop` on GitHub.
- Top-level structure: `backend/`, `ui/`, `worker/`, `migrations/`, `prompts/`, `templates/`, `samples/`, `scripts/`, `docs/`, `tests/`.
- One test file per source file; mirror the source tree under `tests/`.
- Adapters live under `backend/app/adapters/` (engine), `backend/llm/` (LLM provider), `backend/git/` (Git provider).

### Python coding standards

- 100-character line limit (ruff default).
- Ruff rules: defaults + `B` (bugbear), `S` (security/bandit), `UP` (pyupgrade), `D` (docstrings on public APIs).
- mypy `--strict`; no `Any` without explicit annotation.
- Public functions, classes, modules have Google-style docstrings.
- All Pydantic models have field descriptions (used in OpenAPI auto-generation).
- snake_case for variables, functions, modules; PascalCase for classes; SCREAMING_SNAKE for constants.

### TypeScript coding standards

- 100-character line limit (prettier default).
- ESLint Next.js + security + react-hooks plugins.
- `tsc --strict` and `noUncheckedIndexedAccess`.
- camelCase for variables and functions; PascalCase for components and types.

### Database conventions

- **UUIDv7** primary keys on every table (lexicographically sortable, time-ordered, generated client-side).
- All timestamps `TIMESTAMPTZ`, stored UTC.
- Soft delete via `deleted_at` on user-facing tables; hard delete on internal append-only tables (e.g., `trials`).
- snake_case table and column names.
- JSONB for flexible structured fields (settings, params, metrics, payloads).
- All foreign keys explicit; no implicit relationships.
- Indexes on `(tenant_id, created_at)` for tenant-scoped tables — **MVP4+ only**; MVP1–3 has no `tenant_id` column.

### Logging conventions

- Structured JSON via structlog.
- Required fields: `ts`, `lvl`, `msg`, `service`, `trace_id`, `span_id`.
- `msg` field draws from a canonical event catalog in `backend/app/events.py` — **MVP2+**.
- PII redaction processor runs before emission — **MVP2+**.

### Secrets management

- Mounted secret files only — never set in environment variables.
- Source of truth: 1Password / Vault / SSM / equivalent (operator's choice).
- API keys hashed with Argon2id at rest — **MVP4+** (no auth in MVP1).
- For MVP1: `.env.example` enumerates every secret; `.env` is gitignored; Docker secrets mount each value as a file inside the container.

## Reserved for later releases

These appear in the umbrella spec because the spec covers all releases. None of them are MVP1 work. Per-release timing per the §"Canonical release matrix" above:

- **MVP2:** Langfuse + ClickHouse + SigNoz + OpenTelemetry exporters; canonical event catalog; `audit_log` table + immutability trigger (no users/tenants yet); lineage columns; PII redaction; trace context propagation through DB/Redis/worker/adapter/engine.
- **MVP3:** Lucidworks Fusion adapter; multi-Git-provider abstraction (GitLab, Bitbucket); production-style install (TLS via Caddy + Let's Encrypt, managed Postgres/Redis); AWS managed OpenSearch.
- **MVP4:** Multi-tenancy (`tenants`, `tenant_memberships`, `users`, `api_keys` tables; `tenant_id` columns); SSO via reverse proxy for humans; Argon2id-hashed bearer API keys for service accounts; roles `viewer/runner/tenant_admin/platform_admin`; multi-LLM provider abstraction (Anthropic, AWS Bedrock, Google Vertex, Ollama, vLLM); LangChain `RedisCache` for LLM responses.
- **GA v1:** LangGraph orchestrator + `PostgresSaver`; full RFC 7807 Problem Details on errors; `Idempotency-Key` header; Helm chart; container scanning (Trivy); deps audit (pip-audit/npm audit); image signing (cosign); 90% backend coverage gate.
- **Out of scope (no scheduled release):** Mobile UI, i18n, WCAG AA gating, Kubernetes-native operator, multi-region.

## Cross-references

- Per-service topology and message flow: [`system-overview.md`](system-overview.md)
- Postgres schema and conventions: [`data-model.md`](data-model.md)
- HTTP API conventions (endpoint prefixes, error envelope, pagination): [`api-conventions.md`](api-conventions.md)
- Engine adapter Protocol: [`adapters.md`](adapters.md)
- Docker Compose layout for local dev: [`deployment.md`](deployment.md)
