# Deployment

**Status:** Adopted for MVP1. Local Docker Compose only; production-grade deployment activates as later releases add the missing pieces (TLS, SSO, observability).
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §25](../00_overview/relyloop-spec.md) ("Deployment").

---

## MVP1 deployment shape

Single VM (or a developer's laptop) running Docker Compose. No Kubernetes, no Helm, no multi-region. Seven containers (`postgres`, `redis`, `api`, `worker`, `elasticsearch`, `opensearch`, `ui`) per [`system-overview.md`](system-overview.md). The `ui` service was added in `chore_tutorial_polish` Story 2.3 so the tutorial works without a separate `pnpm dev` shell.

```yaml
# docker-compose.yml — MVP1 subset
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: relyloop
      POSTGRES_DB: relyloop
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes: [./data/postgres:/var/lib/postgresql/data]
    secrets: [postgres_password]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U relyloop -d relyloop"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7
    volumes: [./data/redis:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  migrate:
    # Init container — bug_worker_optuna_init_race. Runs alembic + optuna_schema
    # once at boot, then exits. api + worker block on its successful completion
    # via `service_completed_successfully`.
    image: relyloop/api:latest
    command: ["sh", "-c", "alembic upgrade head && python -m backend.app.db.optuna_schema"]
    depends_on:
      postgres: { condition: service_healthy }
    secrets: [database_url, postgres_password]
    restart: "no"

  api:
    image: relyloop/api:latest
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    environment:
      # Pydantic Settings reads `*_FILE`-suffixed vars and substitutes the file content.
      DATABASE_URL_FILE: /run/secrets/database_url
      REDIS_URL: redis://redis:6379/0
      # LLM provider: defaults to OpenAI; point at any OpenAI-compatible endpoint
      # (Ollama: http://host.docker.internal:11434/v1, LM Studio: :1234/v1, vLLM, TGI)
      # See docs/01_architecture/llm-orchestration.md §"OpenAI-compatible endpoints"
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
      OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-2024-08-06}
      OPENAI_MODEL_CHAT: ${OPENAI_MODEL_CHAT:-gpt-4o-mini-2024-07-18}
    ports: ["127.0.0.1:8000:8000"]
    secrets: [database_url, openai_key, cluster_credentials]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]

  worker:
    image: relyloop/api:latest
    command: ["arq", "workers.all.WorkerSettings"]    # MVP1: one process, all three queues
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
    environment:
      DATABASE_URL_FILE: /run/secrets/database_url
      REDIS_URL: redis://redis:6379/0
      OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
      OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-2024-08-06}
      OPENAI_MODEL_CHAT: ${OPENAI_MODEL_CHAT:-gpt-4o-mini-2024-07-18}
    secrets: [database_url, openai_key, cluster_credentials]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]

  elasticsearch:
    image: elasticsearch:9.4.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false      # local dev only
      - ES_JAVA_OPTS=-Xms512m -Xmx512m
    ports: ["127.0.0.1:9200:9200"]
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://localhost:9200/_cluster/health"]
      interval: 10s
      retries: 6

  opensearch:
    image: opensearchproject/opensearch:2.18.0
    environment:
      - discovery.type=single-node
      - DISABLE_SECURITY_PLUGIN=true       # local dev only
      - OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m
    ports: ["127.0.0.1:9201:9200"]         # different host port to coexist with ES

  ui:
    # NEXT_PUBLIC_API_BASE_URL is build-time (Next.js bakes NEXT_PUBLIC_*
    # into the client bundle at `pnpm build`). Compose `environment:` would
    # have NO effect — see chore_tutorial_polish §3 (decision log 2026-05-12 M3).
    image: relyloop/ui:${RELYLOOP_GIT_SHA:-dev}
    build:
      context: ./ui                         # ui/Dockerfile (Node 24 LTS multi-stage)
      args:
        NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000"
    depends_on:
      api: { condition: service_healthy }
    ports: ["127.0.0.1:3000:3000"]
    healthcheck:
      test: ["CMD-SHELL", "node -e \"require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))\""]
      interval: 10s
      retries: 3

secrets:
  postgres_password:    { file: ./secrets/postgres_password }
  database_url:         { file: ./secrets/database_url }     # contains: postgresql://relyloop:<pw>@postgres/relyloop
  openai_key:           { file: ./secrets/openai_key }
  cluster_credentials:  { file: ./secrets/cluster_credentials.yaml }
  # GitHub PATs are per-config_repo: see `feat_github_pr_worker`. Each
  # config_repos row carries an `auth_ref`; the PAT lives at
  # `./secrets/<auth_ref>` (chmod 600). Worker passes the resolved value
  # to git via env-var trio (NEVER argv / NEVER .git/config). See
  # docs/04_security/github-token-handling.md.
```

**Install script (`make up` first run)** generates the required + optional secret files, then runs `docker compose up -d`:

| File | Generated when missing | Why |
|---|---|---|
| `./secrets/postgres_password` | Random 32-byte password | Required: Postgres won't start without it. |
| `./secrets/database_url` | Templated from the password (`postgresql://relyloop:<pw>@postgres/relyloop`) | Required: API + worker won't start without it. |
| `./secrets/openai_key` | **Empty file** (zero bytes) | Optional secret — Compose `secrets:` directive needs the file to exist for the mount to succeed. The API reads the file content; an empty file triggers a startup warning and `subsystems.openai = missing_key` in `/healthz`, but does not crash the API. |
| `./secrets/<config_repo.auth_ref>` | **Not generated** — operator-managed | GitHub PATs are per `config_repos.auth_ref`, not global. Drop the PAT at the named path before `POST /api/v1/config-repos`; rotate by replacing the file in place. See `docs/04_security/github-token-handling.md`. |
| `./secrets/cluster_credentials.yaml` | **Empty YAML doc** (`{}\n`) | Same — required at mount time, but no clusters need credentials at install time (clusters are added later via `POST /api/v1/clusters`). |

Why placeholder empty files: Compose's `secrets:` directive evaluates the source file at startup and **errors out if the file is missing**, regardless of whether the application actually reads the secret. Optional-secret semantics live at the application layer (Pydantic Settings + Pydantic validators that treat empty content as "not configured"), not at the Compose layer.

A bare `docker compose up` from a fresh clone without the install script will fail with a clear "missing secrets file" error pointing at `make up`. (CI runs `make up` too.)

**Sizing rule of thumb:** 16 GB RAM laptop runs the full MVP1 stack comfortably. ES + OpenSearch each consume ~1 GB; Postgres + Redis are negligible; the API + worker are <500 MB each; the UI runtime image (Next.js standalone target) is ~300 MB resident.

The UI ships as a Compose service from `chore_tutorial_polish` onward (`make up` builds it on first run from `ui/Dockerfile`). Operators iterating on the UI itself can still run `pnpm dev` against the same backend for fast hot-reload — `make ui-dev` shells out to that.

## Secrets

**Mounted as files, never as env vars.** This is non-negotiable per [`tech-stack.md`](tech-stack.md) §"Secrets management."

For each secret:
1. The operator places the secret value at `./secrets/<name>` (gitignored).
2. Docker mounts it at `/run/secrets/<name>` inside the container.
3. The application reads via `Pydantic Settings` from a `_FILE`-suffixed env var (e.g., `OPENAI_API_KEY_FILE=/run/secrets/openai_key` → settings reads the file content).

`.env.example` ships with placeholder paths for every secret; the operator copies it to `.env`, generates the secret values into the corresponding file paths, and runs `make up`.

**MVP1 required secrets:** `postgres_password` (auto-generated by the install script if missing).
**MVP1 optional secrets:** `openai_key` (only needed once `feat_llm_judgments` ships; for local-LLM operators using Ollama / LM Studio / vLLM the file can contain any placeholder string since those servers don't validate the key), `cluster_credentials` (only needed for non-local clusters). GitHub PATs are per `config_repos.auth_ref` and dropped at `./secrets/<auth_ref>` lazily by the operator when registering a config repo — see `docs/04_security/github-token-handling.md`.

**Local-LLM operator workflow:** to evaluate against Ollama/LM Studio/vLLM/TGI instead of OpenAI:
1. Run the local LLM tool with its OpenAI-compatible endpoint enabled (e.g., `ollama serve` exposes `:11434/v1`).
2. Set `OPENAI_BASE_URL=http://host.docker.internal:11434/v1` (Ollama) or your tool's URL in `.env`.
3. Set `OPENAI_MODEL=llama3.1:70b-instruct` (or your loaded model name).
4. Write a placeholder string to `./secrets/openai_key` (any non-empty content; local servers don't validate).
5. `make up`.

The startup capability check (per `infra_foundation` FR-2 and [`llm-orchestration.md` §"Capability check at startup"](llm-orchestration.md)) verifies the chosen endpoint supports chat + function-calling + structured-output, surfacing degradation in `/healthz`.

The API logs warnings on startup if optional secrets are missing rather than refusing to start.

## Volumes

| Volume | Purpose | Persisted across restarts |
|---|---|---|
| `./data/postgres` | Database files | Yes |
| `./data/redis` | Redis AOF / dump (queue durability) | Yes |
| `./data/repo-clones` | Cloned config repos for the Git PR worker | Yes (cache; safe to delete) |
| `./secrets/` | Secret value files | Yes; gitignored |

Resetting state: `docker compose down -v && rm -rf ./data` returns to a clean install.

## Network exposure

**MVP1: all services bind to `127.0.0.1` only.** The API is reachable on `localhost:8000`; ES on `localhost:9200`; OpenSearch on `localhost:9201`. No service is reachable from the network beyond the host.

This is appropriate for laptop installs. **GA v1** adds a Caddy reverse proxy with TLS termination (Let's Encrypt) for production-style network exposure — but with **no authentication yet** (the API is reachable over TLS but unauthenticated; appropriate only for trusted-network deployments). SSO (oauth2-proxy or Authelia in front of Caddy) and bearer API keys ship when multi-tenancy is promoted from backlog.

## Reserved for later releases

The umbrella spec §25 lists the full GA v1 deployment (which includes Caddy, Langfuse, ClickHouse, SigNoz). MVP1 ships only the 6 containers above. The remaining services activate at:

| Service | Activates at | Why |
|---|---|---|
| `solr` | **MVP2** | Apache Solr 10 container, bound to `127.0.0.1:8983`; ships alongside the `SolrAdapter` and UBI judgments. |
| `langfuse-web`, `langfuse-worker`, `clickhouse` | **MVP3** | LLM observability theme ("Observable"). |
| `signoz`, `signoz-otel-collector` | **MVP3** | Distributed tracing also MVP3. |
| `caddy` (reverse proxy + Let's Encrypt TLS) | **GA v1** | Production-style install (TLS, network exposure) lands with GA v1 hardening. **No SSO yet** — Caddy alone provides TLS for trusted-network deployments. |
| `oauth2-proxy` / Authelia (SSO in front of Caddy) | **Backlog** | Auth surface arrives when multi-tenancy is promoted from backlog (`users` + `tenants` + API keys). |

## Operator workflow (MVP1)

```bash
# First-time setup
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
cp .env.example .env
# Edit .env: confirm OPENAI_API_KEY_FILE path (defaults match install.sh layout).
echo "<openai-key>" > ./secrets/openai_key
# GitHub PATs are per-repo: drop them lazily when registering a config_repo
# (POST /api/v1/config-repos with an explicit auth_ref). See
# docs/04_security/github-token-handling.md.
make up

# Daily use
make up            # docker compose build (all services) + up -d
make logs          # docker compose logs -f api worker
make down          # docker compose down (containers removed; data volumes preserved)
make migrate       # alembic upgrade head + optuna_schema — idempotent (also runs automatically via the migrate init container at boot)
make seed-clusters # populate local-es + local-opensearch as cluster rows
make seed-es       # seed local-es 'products' index from samples/products.json

# Reset
make reset         # docker compose down -v && rm -rf ./data
```

## Production deployment (post-MVP1)

Not in MVP1 scope. The supported production deployment lands incrementally:

- **MVP3** ("Production Stacks"): documented production install with Caddy + Let's Encrypt TLS, Postgres + Redis pointed at managed services. **TLS but no SSO yet** — appropriate for trusted-network deployments only.
- **MVP4** ("Multi-tenant, Multi-LLM"): SSO via oauth2-proxy or Authelia in front of Caddy; bearer API keys for service accounts. Completes the authenticated-install story.
- **GA v1.5+**: Helm chart for Kubernetes deployments.

Until then, MVP1 is explicitly evaluation-only — the README labels it "alpha" and warns against production rollout.

## Cross-references

- Service inventory and topology: [`system-overview.md`](system-overview.md)
- Stack choices (Docker, Compose, Postgres 16, Redis 7): [`tech-stack.md`](tech-stack.md)
- Health-check endpoint contract: [`api-conventions.md`](api-conventions.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
