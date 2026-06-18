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

### Selective engine startup (`profiles:`)

The three engine services in `docker-compose.yml` (`elasticsearch`, `opensearch`, `solr`) carry Compose `profiles:` blocks (`["es"]`, `["os"]`, `["solr"]` respectively) so operators can opt into a subset of engines and skip the ones they don't need. Compose treats unprofiled services (`postgres`, `redis`, `api`, `worker`, `migrate`, `ui`) as always-on and profiled services as opt-in via `COMPOSE_PROFILES`.

`scripts/install.sh` reads `RELYLOOP_ENGINES` (a comma-separated subset of `{es, os, solr}` defined in `scripts/lib/relyloop_engines.sh`), validates against the allowlist, and exports the resolved value as `COMPOSE_PROFILES` before any `docker compose` call. The default when `RELYLOOP_ENGINES` is unset OR empty is `es,os,solr`, which preserves the project's three-engine startup behavior — a bare `make up` from a fresh clone boots all three engines unchanged.

This is purely additive: no engine service was removed; no default behavior changed. Unknown engine names exit 1 cleanly with a stderr message. See [`docs/03_runbooks/local-dev.md` §"Selecting a subset of engines"](../03_runbooks/local-dev.md) for the operator-facing usage and the `docker compose up -d` DX hazard (which is *not* a regression — it's the natural Compose semantics for profile-gated services and is documented prominently).

The application services do **not** `depends_on` any engine — verified at [`docker-compose.yml`](../../docker-compose.yml) on the `migrate` / `api` / `worker` / `ui` blocks — so profile-gating engines does not cascade-skip the application stack. If a future PR adds `depends_on: elasticsearch` (or similar) to any application service, the engine `profiles:` design must be revisited.

### Engine version matrix

RelyLoop ships a maintainer-curated `ENGINE_VERSION_MATRIX` at [`backend/app/core/engine_versions.py`](../../backend/app/core/engine_versions.py) listing the supported install-time engine versions. The matrix bound is the adapter compatibility window documented in [`adapters.md`](adapters.md): **one entry per supported major per engine** (latest patch). Operators select a version via `RELYLOOP_ES_VERSION` / `RELYLOOP_OS_VERSION` / `RELYLOOP_SOLR_VERSION` at install time — see the [local-dev runbook](../03_runbooks/local-dev.md) for usage. Default unset → the matrix's latest-major value applies, identical to today's behavior.

| Engine | Supported majors (adapters.md) | Matrix values | Compose default |
|---|---|---|---|
| Elasticsearch | 8.11+, 9.x | `9.4.1`, `8.15.3` | `9.4.1` |
| OpenSearch | 2.x, 3.x | `3.6.0`, `2.18.0` | `3.6.0` |
| Solr | 9.x, 10.x | `10.0`, `9.7` | `10.0` |

The matrix is intentionally NOT a "last N versions" count — it tracks the adapter window. When the adapter drops a major, the matrix row drops with it; when a new major is supported, a row is added. Per-minor versions within a single major are not offered (the adapter behaves identically across minors).

**Maintainer release-update process.** When upstream releases a new latest patch for a supported major:

1. Update the matrix entry at `backend/app/core/engine_versions.py`.
2. If the major changed, bump the `${X_IMAGE_TAG:-<default>}` literal in `docker-compose.yml`.
3. Regenerate the bash mirror at `scripts/lib/relyloop_engine_versions_matrix.sh` to match.
4. Verify the smoke job passes against the new tag.

The CI guard at `scripts/ci/verify_engine_version_matrix_parity.sh` enforces sync between the Python matrix, the Compose `:-` defaults, the bash mirror, AND the frontend mirror (`ui/src/lib/enums.ts`) on every PR.

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

## Corporate registry proxy support

Operators behind a corporate network — where Docker Hub and GHCR are reachable only through an Artifactory-style proxy — can route every base-image pull through that proxy without forking the Dockerfiles. Two env vars feed Compose `build.args` that the Dockerfile `FROM` lines consume:

| Env var | Default | Purpose |
|---|---|---|
| `BASE_REGISTRY` | empty (Docker Hub) | Prefix prepended to `python:3.14-slim@…` (backend `Dockerfile`) and `node:26-bookworm-slim@…` (`ui/Dockerfile`). |
| `GHCR_REGISTRY` | `ghcr.io/` | Prefix prepended to every GHCR-hosted image the build references. Currently used by the `astral-sh/uv:0.5.7@…` `uv-source` alias stage in the backend image; any future GHCR image lands under the same prefix. |

**Two override patterns:**

```bash
# Single proxy fronting both Docker Hub and GHCR (typical Artifactory setup)
BASE_REGISTRY=artifactory.example.com/ GHCR_REGISTRY=artifactory.example.com/ make up

# Persistent: uncomment the two lines in .env, set the values, then `make up`
```

**Trailing slash required** on non-empty values — the `FROM`/`COPY` lines concatenate the value directly onto the image reference (no separator).

**Pin posture preserved.** Tag + digest stay literal on every `FROM` line, so OSSF Scorecard's `PinnedDependencies` check still credits the pin; only the registry *prefix* is ARG-indirected. PR #430's collapse of `PYTHON_VERSION`/`PYTHON_DIGEST` into a single literal reference (to avoid digest-beats-tag silent footgun) is **not** undone by this — bumping Python or uv remains a Dependabot lockstep update on the literal FROM line.

See `.env.example` for the canonical comment + the override examples, and the top of the backend `Dockerfile` for the in-file rationale.

### Corporate HTTP proxy (apt / PyPI / npm + runtime egress)

A corp-proxy install almost always also needs an outbound HTTP proxy — the registry override above only fixes Docker image pulls; `apt-get`, `uv sync`, and `pnpm install` still reach Debian / PyPI / npm during the build, and the runtime API still calls OpenAI / GitHub / registered clusters. Three more env vars feed every service's `build.args` and end up as `ENV` in every stage of both Dockerfiles:

| Env var | Purpose |
|---|---|
| `http_proxy` / `HTTP_PROXY` | Outbound HTTP egress |
| `https_proxy` / `HTTPS_PROXY` | Outbound HTTPS egress |
| `no_proxy` / `NO_PROXY` | Comma-separated exemption list |

Both case variants are written by Compose because Linux tooling is split on the convention (apt + curl prefer lowercase; uv + pip + Python `requests` accept either; npm + pnpm prefer uppercase). The Dockerfile ENV blocks set both from the single lowercase ARG.

**The `no_proxy` gotcha — Compose service names + `host.docker.internal`.** Without `postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate` in `no_proxy`, the worker's `http://elasticsearch:9200` call (and similar in-network HTTP) gets routed through the corporate proxy, which has no path to those Compose-internal hostnames. Similarly, `host.docker.internal` must be exempted so a local-LLM setup pointing `OPENAI_BASE_URL` at Ollama / LM Studio / vLLM on the host doesn't get intercepted by the proxy. The recommended value in `.env.example` bakes all of these + `169.254.169.254` (EC2/cloud metadata) + `10.0.0.0/8` (internal VPC) into the default; if you set `no_proxy` manually, include them.

**Architecture: build-time vs runtime.** Build-time proxying uses Docker's [predefined proxy ARGs](https://docs.docker.com/build/building/variables/#predefined-args) (`http_proxy`/`https_proxy`/`no_proxy` + uppercase) — BuildKit forwards them from `--build-arg` into every `RUN` step's environment automatically, with no `ARG` declaration needed in the Dockerfile, and intentionally excludes them from `docker history` so the proxy URL never gets baked into the image. Runtime proxying is set via each Compose service's `environment:` block (also wired through to `${http_proxy:-}` / etc.), keeping the image portable. The two paths read the same `.env` values.

Example for the most common shape (HTTP proxy in front of open egress):

```bash
# In .env
http_proxy=http://http.proxy.your-corp.com:8000
https_proxy=http://http.proxy.your-corp.com:8000
no_proxy=your-corp.com,.your-corp-cloud.com,localhost,127.0.0.1,10.0.0.0/8,169.254.169.254,host.docker.internal,postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate
```

**The deeper Artifactory-mirror case.** If the corp network has no direct egress at all and Artifactory hosts virtual repos for Debian / PyPI / npm, `HTTP_PROXY` won't help — the build would need apt-source overrides, `UV_INDEX_URL` set to Artifactory's PyPI mirror, and `npm config set registry` pointing at Artifactory's npm mirror. That's a bigger change and isn't currently wired through the Dockerfiles; file an issue if you hit it.

### Corporate TLS interception (corp HTTPS proxy with internal CA)

Many corporate HTTPS proxies perform TLS interception: they terminate the TLS connection, inspect the traffic, then re-encrypt it with a corp-internal CA. The operator's host machine trusts that internal CA (it's pre-installed by IT), but **the container doesn't** — its trust store only has the public CAs that ship with `python:3.14-slim` and `node:26-bookworm-slim`. So every HTTPS tool inside the container (npm, pnpm, uv, pip, curl, the runtime OpenAI/GitHub clients) fails verification with errors like:

| Tool | Error signature |
|---|---|
| npm / pnpm | `SELF_SIGNED_CERT_IN_CHAIN`, `self-signed certificate in certificate chain` |
| OpenSSL / curl | `unable to get local issuer certificate` |
| Python (`requests`, `httpx`, `openai`) | `CERTIFICATE_VERIFY_FAILED`, `certificate verify failed` |
| Go | `x509: certificate signed by unknown authority` |

**Solution: install the corp CA cert into the container's trust store at build time.** The cert lands at `./secrets/corp_ca.crt`. `make up` reads it at build time via a BuildKit `--mount=type=secret`, copies it into `/usr/local/share/ca-certificates/`, and runs `update-ca-certificates` to rebuild `/etc/ssl/certs/ca-certificates.crt`. Every HTTPS tool in the container then trusts the corp CA — at build time AND runtime, because the cert is baked into the system trust bundle. Empty placeholder file = no-op (OSS users unaffected). The cert is NOT shipped through Compose's `environment:` block (it's a build-time-only file via `build.secrets:`), so the URL or content never leaks into logs or `docker inspect`.

**One-time setup — recommended:**

```bash
make corp-ca-extract    # probes the live TLS chain, saves the corp root to ./secrets/corp_ca.crt
make up                 # cert is installed during 'docker compose build'
```

`make corp-ca-extract` runs [`scripts/corp-ca-extract.sh`](../../scripts/corp-ca-extract.sh) which probes a public HTTPS endpoint via `openssl s_client -showcerts`, walks the chain, and identifies the corp root by comparing the last cert's Subject against ~27 known public CAs (DigiCert, ISRG, Google Trust Services, etc.). If the network isn't MITM-ing TLS, it exits cleanly with "No corporate TLS interception detected". See [`docs/03_runbooks/corporate-network-install.md` §2](../03_runbooks/corporate-network-install.md) for the algorithm + override knobs.

**One-time setup — manual fallback** (when auto-extract picks the wrong cert):

```bash
# Get your corp CA cert in PEM format. Common sources:
#   - Ask IT for the corporate root CA cert.
#   - Linux: ls /usr/local/share/ca-certificates/   (usually exactly your corp CAs)
#   - macOS: security find-certificate -p -c "Corp Root CA"    (searches default keychain list — login + system)
#   - Chrome / Edge → Settings → Privacy/Security → Manage certificates → export.
cp /path/to/corp-ca.crt ./secrets/corp_ca.crt

make up    # cert is installed during 'docker compose build'
```

**Verifying.** After `make up`, run:

```bash
docker run --rm relyloop/api:dev openssl x509 -in /usr/local/share/ca-certificates/corp_ca.crt -noout -subject
```

You should see your corp CA's subject line. If the file isn't there, the secret wasn't propagated — re-check `./secrets/corp_ca.crt` exists and is non-empty.

**The complete symptom → fix guide** for every corp-network failure mode lives in [`docs/03_runbooks/corporate-network-install.md`](../03_runbooks/corporate-network-install.md) (registry blocked, TLS interception, proxy DNS failure, runtime unhealthy worker).

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
