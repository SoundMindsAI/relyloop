# Deployment

**Status:** Adopted for MVP1. Local Docker Compose only; production-grade deployment activates as later releases add the missing pieces (TLS, SSO, observability).
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §25](../00_overview/product/relevance-copilot-spec.md) ("Deployment").

---

## MVP1 deployment shape

Single VM (or a developer's laptop) running Docker Compose. No Kubernetes, no Helm, no multi-region. Six containers per [`system-overview.md`](system-overview.md).

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

  api:
    image: relyloop/api:latest
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    environment:
      # Pydantic Settings reads `*_FILE`-suffixed vars and substitutes the file content.
      DATABASE_URL_FILE: /run/secrets/database_url
      REDIS_URL: redis://redis:6379/0
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
      GITHUB_TOKEN_FILE: /run/secrets/github_token
    ports: ["127.0.0.1:8000:8000"]
    secrets: [database_url, openai_key, cluster_credentials, github_token]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]

  worker:
    image: relyloop/api:latest
    command: ["arq", "workers.all.WorkerSettings"]    # MVP1: one process, all three queues
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    environment:
      DATABASE_URL_FILE: /run/secrets/database_url
      REDIS_URL: redis://redis:6379/0
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
      GITHUB_TOKEN_FILE: /run/secrets/github_token
    secrets: [database_url, openai_key, cluster_credentials, github_token]
    volumes: [./data/repo-clones:/var/lib/relyloop/repos]

  elasticsearch:
    image: elasticsearch:9.0.0
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

secrets:
  postgres_password:    { file: ./secrets/postgres_password }
  database_url:         { file: ./secrets/database_url }     # contains: postgresql://relyloop:<pw>@postgres/relyloop
  openai_key:           { file: ./secrets/openai_key }
  cluster_credentials:  { file: ./secrets/cluster_credentials.yaml }
  github_token:         { file: ./secrets/github_token }
```

**Install script (`make up` first run)** generates the required + optional secret files, then runs `docker compose up -d`:

| File | Generated when missing | Why |
|---|---|---|
| `./secrets/postgres_password` | Random 32-byte password | Required: Postgres won't start without it. |
| `./secrets/database_url` | Templated from the password (`postgresql://relyloop:<pw>@postgres/relyloop`) | Required: API + worker won't start without it. |
| `./secrets/openai_key` | **Empty file** (zero bytes) | Optional secret — Compose `secrets:` directive needs the file to exist for the mount to succeed. The API reads the file content; an empty file triggers a startup warning and `subsystems.openai = missing_key` in `/healthz`, but does not crash the API. |
| `./secrets/github_token` | **Empty file** | Same — Compose-mount-friendly. The API logs a warning and `feat_github_pr_worker` (when it ships) gates PR-creation on the token being non-empty. |
| `./secrets/cluster_credentials.yaml` | **Empty YAML doc** (`{}\n`) | Same — required at mount time, but no clusters need credentials at install time (clusters are added later via `POST /api/v1/clusters`). |

Why placeholder empty files: Compose's `secrets:` directive evaluates the source file at startup and **errors out if the file is missing**, regardless of whether the application actually reads the secret. Optional-secret semantics live at the application layer (Pydantic Settings + Pydantic validators that treat empty content as "not configured"), not at the Compose layer.

A bare `docker compose up` from a fresh clone without the install script will fail with a clear "missing secrets file" error pointing at `make up`. (CI runs `make up` too.)

**Sizing rule of thumb:** 16 GB RAM laptop runs the full MVP1 stack comfortably. ES + OpenSearch each consume ~1 GB; Postgres + Redis are negligible; the API + worker are <500 MB each.

The UI is NOT a Compose service in MVP1 — it runs via `pnpm dev` from the `ui/` directory during development. Adding it as a Compose service is a polish item for `chore_tutorial_polish` or post-MVP1.

## Secrets

**Mounted as files, never as env vars.** This is non-negotiable per [`tech-stack.md`](tech-stack.md) §"Secrets management."

For each secret:
1. The operator places the secret value at `./secrets/<name>` (gitignored).
2. Docker mounts it at `/run/secrets/<name>` inside the container.
3. The application reads via `Pydantic Settings` from a `_FILE`-suffixed env var (e.g., `OPENAI_API_KEY_FILE=/run/secrets/openai_key` → settings reads the file content).

`.env.example` ships with placeholder paths for every secret; the operator copies it to `.env`, generates the secret values into the corresponding file paths, and runs `make up`.

**MVP1 required secrets:** `postgres_password` (auto-generated by the install script if missing).
**MVP1 optional secrets:** `openai_key` (only needed once `feat_llm_judgments` ships), `github_token` (only needed once `feat_github_pr_worker` ships), `cluster_credentials` (only needed for non-local clusters).

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

This is appropriate for laptop installs. **MVP3** adds a Caddy reverse proxy with TLS termination (Let's Encrypt) for production-style network exposure — but with **no authentication yet** (the API is reachable over TLS but unauthenticated; appropriate only for trusted-network deployments). **MVP4** adds SSO (oauth2-proxy or Authelia in front of Caddy) and bearer API keys, completing the authenticated-install story per umbrella §18.

## Reserved for later releases

The umbrella spec §25 lists the full GA v1 deployment (which includes Caddy, Langfuse, ClickHouse, SigNoz, fusion-mock). MVP1 ships only the 6 containers above. The remaining services activate at:

| Service | Activates at | Why |
|---|---|---|
| `langfuse-web`, `langfuse-worker`, `clickhouse` | **MVP2** | LLM observability theme. |
| `signoz`, `signoz-otel-collector` | **MVP2** | Distributed tracing theme. |
| `caddy` (reverse proxy + Let's Encrypt TLS) | **MVP3** | Production-style install (TLS, network exposure) lands with production-stack hardening. **No SSO yet** at MVP3 — Caddy alone provides TLS for trusted-network deployments. |
| `fusion-mock` | **MVP3** | Lucidworks Fusion adapter ships here; mock service for UI/demo dev when shared dev cluster isn't reachable. |
| `oauth2-proxy` / Authelia (SSO in front of Caddy) | **MVP4** | Auth surface arrives with `users` + `tenants` + API keys; SSO completes the authenticated-install story per umbrella §18. |
| `ui` (containerized) | Late MVP1 polish or post-MVP1 | UI runs via `pnpm dev` during MVP1 dev; containerization is a polish item. |

## Operator workflow (MVP1)

```bash
# First-time setup
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
cp .env.example .env
# Edit .env: set OPENAI_API_KEY_FILE path, GITHUB_TOKEN_FILE path
echo "<openai-key>" > ./secrets/openai_key
echo "<gh-pat>" > ./secrets/github_token
make up

# Daily use
make up            # docker compose up -d
make logs          # docker compose logs -f api worker
make down          # docker compose stop
make migrate       # alembic upgrade head (in api container)
make seed-clusters # populate local-es + local-opensearch as cluster rows

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
