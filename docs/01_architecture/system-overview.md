# System Overview

**Status:** Adopted for MVP1. Each release adds services; this doc shows the full topology with MVP1-active services highlighted.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §7](../00_overview/product/relevance-copilot-spec.md) ("System architecture").

---

## MVP1 topology

The smallest stack that demonstrates the Karpathy loop end-to-end on a developer's laptop.

```
                         ┌──────────────────────┐
                         │   Web UI (Next.js)   │
                         └──────────┬───────────┘
                                    │  HTTP / SSE  (no TLS in MVP1)
                         ┌──────────▼───────────┐
                         │  API + agent backend │   (FastAPI)
                         │  - HTTP endpoints    │
                         │  - OpenAI agent      │
                         │  - Tool dispatch     │
                         │  - Adapter dispatch  │
                         └─┬───────┬───────┬────┘
                           │       │       │
              ┌────────────┘       │       └──────────────┐
              │                    │                      │
     ┌────────▼────────┐  ┌────────▼─────────┐   ┌────────▼─────────┐
     │   Postgres 16   │  │   Redis 7        │   │   OpenAI API     │
     │   - app state   │  │   - Arq queue    │   │   - GPT-4o tier  │
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
            │ Adapters  │  │ pytrec_  │ │ Git provider│
            │ - ES      │  │ eval     │ │ - GitHub    │
            │ - OpenSearch│ │          │ │ - PR API    │
            └─┬─────────┘  └──────────┘ └────────────┘
              │
   ┌──────────▼──────────────────────────┐
   │  Tuned clusters (operator's)        │
   │  - local Compose ES + OpenSearch    │
   │  - or remote ES / OpenSearch        │
   └─────────────────────────────────────┘
```

**MVP1 service inventory (6 containers):**

| Service | Role | Image / source |
|---|---|---|
| `postgres` | App state + Optuna RDBStorage | `postgres:16` |
| `redis` | Arq task queue | `redis:7` |
| `api` | FastAPI HTTP API + agent orchestrator | `relyloop/api:latest` (built from this repo) |
| `worker` | Arq workers (trial / digest / PR) | Same image as `api`, different command |
| `elasticsearch` | Local target cluster for the tutorial / dev | `elasticsearch:9.0.0` |
| `opensearch` | Local target cluster for the tutorial / dev | `opensearchproject/opensearch:2.18.0` |

The UI runs via `pnpm dev` during MVP1 (not yet a Compose service); a `ui` container ships when MVP1's release polish lands.

## Service responsibilities

| Service | Responsibility | Sole owner of |
|---|---|---|
| Web UI | Chat surface, study/proposal/cluster screens, judgment review | None — pure client; reads from API |
| API + agent backend | HTTP endpoints, OpenAI orchestration, tool dispatch, study lifecycle | API contracts; the OpenAI agent state |
| Postgres | App state + Optuna RDB | All persistent state |
| Redis | Arq task queue | Job orchestration |
| Worker pool | Trial execution, digest generation, Git PR creation | Long-running background work |
| Adapters | Engine-specific query rendering and execution | Every engine-specific code path |
| pytrec_eval | Universal IR evaluation (nDCG, MAP, P@K) | Metric computation |
| Git provider | GitHub PR + webhook handling | Outbound Git operations |

**Architectural principle:** the adapter layer is the *only* place engine-specific code lives. The orchestrator, study runner, evaluator, and UI are all engine-agnostic — they consume the unified vocabulary in [`adapters.md`](adapters.md) §"Cross-engine parameter naming."

## Communication patterns

| From → To | Protocol | Notes |
|---|---|---|
| Web UI → API | HTTP/JSON | Cursor pagination, structured error envelope per [`api-conventions.md`](api-conventions.md) |
| Web UI → API (chat) | SSE | OpenAI streaming proxied through FastAPI |
| API → Postgres | asyncpg via SQLAlchemy 2.0 async | One pooled connection per request |
| API → Redis | aioredis (via Arq) | Enqueue Arq jobs |
| Worker → Postgres | Same as API | Write trial results, study status |
| Worker → Redis | Arq dequeue | One worker process consumes one queue |
| Worker → Adapter → Cluster | httpx async | `_msearch` for ES/OpenSearch hot path |
| Worker → OpenAI | `openai` Python SDK | Function calling for the agent; chat completion for digests |
| Worker → GitHub | httpx async + `gh` CLI for clones | PR creation via REST API |
| GitHub → API (webhooks) | HTTP POST | `/webhooks/github` endpoint, signature verification |

**No internal RPC.** All inter-service communication is the patterns above. There is no gRPC, no message bus beyond the Arq queue, no service mesh.

## Worker pool detail

Three worker types share the same image but consume different Arq queues:

| Worker | Queue | Job kinds | Concurrency |
|---|---|---|---|
| Trial worker | `trials` | `run_trial(study_id, params)` | Scaled via `--scale worker=N`; one trial per slot |
| Digest worker | `digests` | `generate_digest(study_id)` | Single instance (digests are infrequent) |
| Git PR worker | `pr` | `open_pr(proposal_id)`, `update_pr_state(proposal_id)` | Single instance (Git ops are sequential per repo) |

In MVP1's local-laptop deployment, all three roles run as a single worker process for simplicity; horizontal scaling activates when the operator runs `docker compose up --scale worker=N` in MVP3+ deployments.

## Reserved for later releases

Services in the umbrella spec §25 deployment that are NOT in MVP1:

| Service | Activates at | Why deferred for MVP1 |
|---|---|---|
| `ui` (containerized) | Late MVP1 / chore_tutorial_polish | UI runs via `pnpm dev` during MVP1 development; containerization is a polish item. |
| `caddy` (reverse proxy + Let's Encrypt TLS) | MVP3 | Production-style install adds TLS + network exposure. **No SSO yet** — trusted-network deployments only. |
| `oauth2-proxy` / Authelia (SSO in front of Caddy) | MVP4 | Auth surface arrives with `users` + `tenants` + API keys per umbrella §18. |
| `langfuse-web`, `langfuse-worker`, `clickhouse` | MVP2 | LLM observability is the MVP2 theme ("Observable"). |
| `signoz`, `signoz-otel-collector` | MVP2 | Distributed tracing also MVP2. |
| `fusion-mock` | MVP3 | Ships with the Lucidworks Fusion adapter; mock service for UI/demo dev when shared dev cluster isn't reachable. |

## Deployment

The single deployment unit is a Docker Compose project. See [`deployment.md`](deployment.md) for the full Compose layout, secrets handling, and operator-facing setup.

## Cross-references

- Stack choices and per-layer rationale: [`tech-stack.md`](tech-stack.md)
- HTTP API conventions (envelope, pagination, error codes): [`api-conventions.md`](api-conventions.md)
- Postgres tables and conventions: [`data-model.md`](data-model.md)
- Engine adapter Protocol and pattern: [`adapters.md`](adapters.md)
- Docker Compose layout: [`deployment.md`](deployment.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
