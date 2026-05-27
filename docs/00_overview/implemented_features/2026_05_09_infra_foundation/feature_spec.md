# Feature Specification — infra_foundation

**Date:** 2026-05-08
**Status:** Draft
**Owners:** TBD (Eng Owner: TBD; Product Owner: TBD)
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-1, US-2, US-3
- [docs/01_architecture/mvp1-overview.md](../../../01_architecture/mvp1-overview.md) — MVP1 architecture entry point
- [docs/01_architecture/system-overview.md](../../../01_architecture/system-overview.md) — service topology this feature establishes
- [docs/01_architecture/tech-stack.md](../../../01_architecture/tech-stack.md) — stack choices this feature wires up
- [docs/01_architecture/deployment.md](../../../01_architecture/deployment.md) — Compose layout this feature implements
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — conventions the `/healthz` endpoint follows
- [docs/00_overview/relyloop-spec.md](../../../00_overview/relyloop-spec.md) §27 — MVP1 scope (umbrella)

---

## 1) Purpose

- **Problem:** RelyLoop has zero code today. Before any user-facing feature can be built, the project needs the skeleton: a repo layout, a Docker Compose stack that boots locally, a CI workflow, code-quality gates, and a health-check endpoint. Without these, every subsequent feature has to re-litigate "where do files go" and "how do we run tests."
- **Outcome:** A relevance engineer can `git clone`, `docker compose up`, see all subsystems healthy in <60s on a 16GB laptop, and have a CI pipeline that gates every PR on lint, type-check, test, and an 80% coverage minimum.
- **Non-goal:** No business logic. No agent code, no Optuna integration, no engine adapters — those are separate features that depend on this one. Health check is the only endpoint.

## 2) Current state audit

**N/A — pre-foundation feature.** No codebase exists. This spec describes the codebase that will exist after the foundation ships. The "current state" is zero files in `backend/`, `ui/`, `worker/`, `tests/`, `migrations/`.

The first feature establishes the patterns that all subsequent features will follow. There is nothing to audit, but every choice made here (directory layout, lint config, CI pipeline structure, secrets handling) will be referenced as the convention by every later feature spec's §3 API convention check and §9 data model section.

## 3) Scope

### In scope

- Monorepo layout per [`tech-stack.md` §"Code organization"](../../../01_architecture/tech-stack.md): `backend/`, `ui/`, `worker/`, `migrations/`, `prompts/`, `templates/`, `samples/`, `scripts/`, `docs/` (already present), `tests/`.
- Python project setup with `uv` (lockfile, `pyproject.toml`, `python>=3.12`).
- Backend skeleton: FastAPI app with one endpoint (`GET /healthz`), structured logging via `structlog`, Pydantic Settings configuration loaded from env vars.
- Postgres 16 + SQLAlchemy 2.0 async + Alembic per [`tech-stack.md`](../../../01_architecture/tech-stack.md). One initial migration that creates an empty `alembic_version` table only (no business tables yet — those land with their respective features).
- Redis 7 wired (no consumers yet — Arq workers come with `feat_study_lifecycle`).
- Docker Compose per [`deployment.md`](../../../01_architecture/deployment.md): `postgres`, `redis`, `api`, `worker`, `elasticsearch`, `opensearch`. The deferred services (Caddy, Langfuse, ClickHouse, SigNoz, fusion-mock, containerized UI) are documented in `deployment.md` §"Reserved for later releases" — none ship in this feature.
- TypeScript + Next.js 14 frontend skeleton (App Router) with one page (root `/` → "RelyLoop is running"). pnpm lockfile. Stack details in [`tech-stack.md` §"Frontend"](../../../01_architecture/tech-stack.md).
- Code quality per [`tech-stack.md`](../../../01_architecture/tech-stack.md): ruff (check + format), mypy `--strict`, pytest + pytest-asyncio + coverage.py for backend; eslint + prettier + tsc + vitest for frontend.
- Pre-commit framework with hooks for ruff, mypy, eslint, prettier.
- GitHub Actions workflow `pr.yml` running on every PR: backend lint+typecheck+test+coverage, frontend lint+typecheck+test+build, Docker image builds (no push). See [`tech-stack.md` §"CI/CD"](../../../01_architecture/tech-stack.md).
- 80% backend Python coverage gate per [`tech-stack.md`](../../../01_architecture/tech-stack.md).
- `.env.example` enumerating every env var the stack reads, with safe defaults where applicable. Secrets-via-files pattern per [`deployment.md` §"Secrets"](../../../01_architecture/deployment.md).
- `Makefile` with conventional targets: `make fmt`, `make lint`, `make typecheck`, `make test`, `make up`, `make down`, `make migrate`, `make migrate-create`.

### Out of scope

- Business logic (engine adapters, Optuna, judgments, study orchestrator, agent, UI screens beyond the placeholder `/`) — all in subsequent features.
- Auth / RBAC — single-tenant install with no auth per §27. Login/sessions arrive in MVP4.
- Production-grade observability (Langfuse, SigNoz, OpenTelemetry exporters) — MVP2 per [`deployment.md` §"Reserved for later releases"](../../../01_architecture/deployment.md).
- TLS termination via Caddy — MVP1 binds directly to localhost. **MVP3** adds Caddy + Let's Encrypt TLS (trusted-network production install, no SSO). **MVP4** adds oauth2-proxy/Authelia SSO in front of Caddy. Per [`deployment.md` §"Reserved for later releases"](../../../01_architecture/deployment.md).
- Container image publishing to GHCR — MVP1 builds locally only; image-publish workflow lands as part of `chore_tutorial_polish` or a dedicated MVP1.5 ticket.
- Helm chart, Kubernetes manifests, multi-region — explicitly out per §28.

### API convention check

This feature **establishes** the conventions documented in [`api-conventions.md`](../../../01_architecture/api-conventions.md). Quick recap relevant to this feature:

- **Endpoint prefix:** `/api/v1/<resource>` for business endpoints. `/healthz` is unprefixed (operator-facing).
- **Router namespace:** `backend/app/api/health.py`. No other routers exist yet.
- **HTTP methods:** standard set per `api-conventions.md`. No CRUD endpoints in this feature.
- **Non-auth error envelope:** the structured shape from `api-conventions.md` §"Error envelope" — implemented in MVP1; full RFC 7807 alignment lands at GA v1.
- **Auth error shape:** N/A — no auth in MVP1.

### Phase boundaries

Single-phase. No deferred work; everything in scope ships in one PR.

## 4) Product principles and constraints

- **Boot fast.** `docker compose up` to "all healthy" in <60s on a 16GB laptop. Postgres + Redis + ES + OpenSearch + API + worker = 6 containers; they must come up in parallel, not sequentially-blocked on a long migration.
- **Zero ceremony.** A new contributor clones, copies `.env.example`, runs `make up`, and is productive. Any required manual step beyond that is a defect.
- **Convention over configuration.** Every choice (directory layout, lint config, test runner, migration tool) is documented in [`tech-stack.md`](../../../01_architecture/tech-stack.md) — not "whatever the first contributor preferred."
- **CI must mirror local.** If `make lint && make typecheck && make test` passes locally, CI must pass too. Same Python version, same dependency lockfile, same toolchain.
- **Secrets via files, not env vars** per [`deployment.md` §"Secrets"](../../../01_architecture/deployment.md) — even in MVP1, `.env.example` mounts files into containers via Docker secrets, not bare env vars. This sets the pattern correctly from day one.

### Anti-patterns

- **Do not** create per-developer `.env` files committed to git. Use `.env.example` as the only checked-in env template.
- **Do not** install ES + OpenSearch with security plugins enabled in the local Compose. Per [`deployment.md`](../../../01_architecture/deployment.md), local dev disables security; production-mode security configuration is a separate (MVP3+) concern.
- **Do not** add a CI gate that runs against a real cloud (AWS/GCP) in MVP1. CI must be hermetic — only services CI itself can spin up. ES + OpenSearch run as service containers in the GitHub Actions job, not against a managed cluster.
- **Do not** wire Langfuse, ClickHouse, or SigNoz into the Compose. Per [`deployment.md` §"Reserved for later releases"](../../../01_architecture/deployment.md) those services activate at MVP2; MVP1 ships only the 6-container subset.
- **Do not** require a `GITHUB_TOKEN_FILE` secret to boot the stack. The token is only consumed by `feat_github_pr_worker`; until that feature ships, the secret file is absent and the API logs a warning rather than refusing to start.
- **Do not** support raw env vars (`OPENAI_API_KEY=sk-...`) as a fallback. The `_FILE` mounted-secret pattern is the ONLY supported path — bare env vars defeat the secrets-management purpose (visible in container inspect, logs, ps).

## 5) Assumptions and dependencies

- **Docker 24+ with Compose v2** per [`tech-stack.md` §"Infrastructure"](../../../01_architecture/tech-stack.md). The stack uses `services.depends_on` healthcheck conditions that require Compose v2.
- **Python 3.12+** locally for development (CI provisions this; engineers install via pyenv or uv).
- **Node 20+** for the UI (CI provisions; engineers install via nvm or volta).
- **No external services required.** No OpenAI key needed to boot — only consumed by features that call OpenAI (judgments, digest, agent). The API logs a warning if `OPENAI_API_KEY_FILE` is unset rather than refusing to start.
- **GitHub repo with branch protection on `main`.** Already in place; CI workflow gates merges.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (also acts as Operator for the local install).
- **Role model:** Single-tenant, no auth. All users have full access. (MVP4 adds `tenants`, `tenant_memberships`, and roles `viewer` / `runner` / `tenant_admin` (per-tenant) + `platform_admin` (cross-tenant) per umbrella §18. Auth is SSO via reverse proxy for humans + Argon2id-hashed bearer API keys for service accounts. There is **no admin-impersonation model** in RelyLoop — that was a CDO concept that didn't carry over.)
- **Permission boundaries:** N/A.

### Admin control scope checklist

- [ ] Admin UI needed? **No** — no admin model in MVP1.
- [ ] Ceiling enforcement needed? **No** — no admin defaults vs. tenant overrides in MVP1.
- [ ] Override hierarchy documented? **No** — single-tenant install, no overrides.

### RBAC authorization matrix

**N/A — RelyLoop is single-tenant for MVP1–MVP3 with no auth.** RBAC matrix activates in MVP4. The `/healthz` endpoint is unauthenticated by design (operator-facing; standard convention).

### Audit-event instrumentation matrix

**N/A — RelyLoop has no audit-events subsystem yet.** This subsystem is a CDO concept inherited via the spec template; if RelyLoop adopts an analogous architecture in a later release, this section will be revisited per the porting-banner guidance in `feature_templates/feature-spec-template.md`.

## 7) Functional requirements

### FR-1: Boot a complete local stack with one command
- The system **MUST** start Postgres 16, Redis 7, the API, the worker process, Elasticsearch 9, and OpenSearch 2.18 via `make up` from a fresh clone (`make up` runs the install script then `docker compose up -d`).
- The system **MUST** report all six containers healthy within 60 seconds on a 16GB / 4-core developer laptop. (Healthchecks defined per service.)
- The API container **MUST** wait for Postgres healthy before accepting traffic (Compose `depends_on: condition: service_healthy`).
- Notes: covers US-1.

### FR-2: Health check endpoint reports subsystem status
- The system **MUST** expose `GET /healthz` returning JSON: `{ "status": "ok" | "degraded", "subsystems": { "db": "ok" | "down", "redis": "ok" | "down", "openai": "configured" | "missing_key" | "incapable", "elasticsearch": "reachable" | "unreachable", "opensearch": "reachable" | "unreachable" }, "openai_endpoint": "<base_url>", "openai_capabilities": {"chat": "ok" | "fail", "function_calling": "ok" | "fail" | "untested", "structured_output": "ok" | "fail" | "untested"} }` with HTTP 200 if `status=ok`, HTTP 503 if any subsystem is `down` or `unreachable`.
- The endpoint **MUST** complete in <500ms (each subsystem probe runs in parallel with a 200ms timeout).
- The `openai` subsystem **MUST** report `incapable` when `OPENAI_API_KEY_FILE` is configured but the capability check (per FR-7) reports degraded chat / function-calling / structured-output. `incapable` is non-blocking for the overall `status` (the system can run with degraded LLM features); `missing_key` likewise non-blocking.
- Notes: covers US-2.

### FR-3: Secrets via mounted files, never raw env vars
- The system **MUST** ship a `.env.example` at repo root listing every `*_FILE` env var the stack consumes, plus a `./secrets/` directory layout doc explaining which files Docker mounts to `/run/secrets/<name>` per [`deployment.md` §"Secrets"](../../../01_architecture/deployment.md).
- The system **MUST** ignore `.env` and `./secrets/*` in `.gitignore`.
- The system **MUST** read secrets via Pydantic Settings from `*_FILE`-suffixed env vars (e.g., `OPENAI_API_KEY_FILE=/run/secrets/openai_key` → settings reads the file content). **Bare env vars (e.g., `OPENAI_API_KEY=sk-...`) are NOT supported** — bare env names appear in container `inspect` output, container logs, and `ps`-style introspection, defeating the purpose of secrets management.
- The system **SHOULD** validate secret content (not just file presence) at API startup. For MVP1, `DATABASE_URL_FILE` and `POSTGRES_PASSWORD_FILE` content **MUST** be non-empty (required); `OPENAI_API_KEY_FILE`, `GITHUB_TOKEN_FILE`, and `CLUSTER_CREDENTIALS_FILE` content **MAY** be empty — empty content is treated as "not configured" with a startup warning, not a crash.
- The system **MUST** ship an install script (`make up` first run) that generates ALL secret files Compose declares, so a bare `docker compose up` against the generated layout works:
  - `./secrets/postgres_password` (random 32-byte) — required
  - `./secrets/database_url` (templated from the password: `postgresql://relyloop:<pw>@postgres/relyloop`) — required
  - `./secrets/openai_key` (**empty file**) — optional secret; empty so Compose's `secrets:` mount succeeds, then the API treats empty content as "not configured"
  - `./secrets/github_token` (**empty file**) — same
  - `./secrets/cluster_credentials.yaml` (**empty YAML doc** `{}\n`) — same
- A bare `docker compose up` from a fresh clone without `make up` first **MUST** fail with a clear "missing secrets file" error pointing at `make up`.
- Notes: covers US-3.

### FR-4: Code quality gates run in CI
- The system **MUST** ship a GitHub Actions workflow `.github/workflows/pr.yml` running on every PR that runs (in parallel jobs): backend `make lint typecheck test` (with 80% coverage gate), frontend `pnpm lint typecheck test build`, and `docker buildx build` for both `relyloop/api` and `relyloop/ui` images (no push).
- The system **MUST** fail the CI run if any gate fails.
- The system **MUST** report coverage as a workflow comment / summary (use Coverage Gutters–compatible LCOV or coverage.py XML output).

### FR-5: Migration scaffold
- The system **MUST** ship one Alembic migration that creates the `alembic_version` table only (no business tables).
- The system **MUST** provide a `make migrate` target that:
  1. Runs `alembic upgrade head` against the configured database (RelyLoop's `public.*` schema)
  2. Calls a Python helper that initializes Optuna's RDBStorage against the same Postgres under the `optuna.*` schema (creates Optuna's tables on first run; no-op on subsequent runs). Stub helper in MVP1 (no Optuna usage yet); becomes load-bearing when `infra_optuna_eval` ships.
- The system **MUST** provide `make migrate-create name=<slug>` running `alembic revision --autogenerate -m "<slug>"` for engineers adding the next migration.

### FR-6: Conventional Commits enforced via pre-commit
- The system **SHOULD** ship a pre-commit hook validating commit-message format against the Conventional Commits regex (`^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:`).
- Notes: per §28 "Conventional Commits" — auto-changelog generation (GA v1) depends on this.

### FR-7: OpenAI-compatible endpoint capability check
- The system **MUST** read `OPENAI_BASE_URL` (default `https://api.openai.com/v1`) and `OPENAI_MODEL` from settings at startup.
- The system **MUST** perform a capability self-test against `OPENAI_BASE_URL` once at startup IF `OPENAI_API_KEY_FILE` exists and is non-empty:
  - `GET {base_url}/models` — verify reachable
  - `POST {base_url}/chat/completions` with a 1-token prompt — verify chat works
  - `POST {base_url}/chat/completions` with a trivial `echo(text)` tool definition + `tool_choice="required"` — verify the response includes a parseable `tool_calls` field
  - `POST {base_url}/chat/completions` with `response_format={type: "json_schema", ...}` for a trivial Pydantic shape — verify the response parses
- The results **MUST** be cached in Redis under `openai:capabilities:{sha256(base_url)}` with 24h TTL.
- The capability check **MUST NOT** crash the API on failure — it logs at WARN and stores partial results. Downstream features (`feat_llm_judgments`, `feat_digest_proposal`, `feat_chat_agent`) read the capability cache and either gate themselves (judgment generation needs structured_output=ok) or degrade gracefully (chat agent works without function_calling, just refuses to dispatch tools).
- Per [`llm-orchestration.md` §"OpenAI-compatible endpoints"](../../../01_architecture/llm-orchestration.md). Covers part of US-32.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/healthz` | Probe subsystem health | `503 SERVICE_UNAVAILABLE` if any subsystem down |

### 7.2 Contract rules

- `/healthz` returns 200 on full health, 503 on any subsystem down. Body is always JSON with the same shape; the `status` field is the high-level summary.
- Health probes run in parallel with per-subsystem timeouts (200ms each) so a single slow subsystem can't block the response past 500ms.

### 7.3 Response examples

Success (200):
```json
{
  "status": "ok",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "configured",
    "elasticsearch": "reachable",
    "opensearch": "reachable"
  },
  "version": "0.1.0",
  "uptime_seconds": 1234
}
```

Degraded (503):
```json
{
  "status": "degraded",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "missing_key",
    "elasticsearch": "unreachable",
    "opensearch": "reachable"
  },
  "version": "0.1.0",
  "uptime_seconds": 1234
}
```

`openai: missing_key` does NOT mark the system degraded (it's optional pre-judgments-feature). Only `db: down`, `redis: down`, `elasticsearch: unreachable`, or `opensearch: unreachable` triggers 503.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth |
|---|---|---|
| `subsystems.db` | `ok`, `down` | `backend/app/api/health.py` (`SubsystemStatus` enum) |
| `subsystems.redis` | `ok`, `down` | same |
| `subsystems.openai` | `configured`, `missing_key` | same |
| `subsystems.elasticsearch` | `reachable`, `unreachable` | same |
| `subsystems.opensearch` | `reachable`, `unreachable` | same |
| `status` | `ok`, `degraded` | same |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `SERVICE_UNAVAILABLE` | 503 | One or more required subsystems is down |

## 9) Data model and state transitions

### New/changed entities

**No business tables.** The initial migration creates only `alembic_version` (Alembic's internal table tracking the applied head revision).

Subsequent feature specs add their own tables (e.g., `feat_study_lifecycle` adds `studies`, `trials`; `infra_adapter_elastic` adds `clusters`).

### Required invariants

- `alembic_version` table exists after migration.
- `database` named per `DATABASE_URL` exists and is reachable from the API container.

### State transitions

N/A — no entities with state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Committed secrets (e.g., `.env` accidentally committed). **Mitigation:** `.gitignore` blocks `.env`; pre-commit hook scans for secret patterns (gitleaks).
  2. Local ES/OpenSearch with security disabled accessible from the host network. **Mitigation:** Compose binds these to `127.0.0.1` only, not `0.0.0.0`. Documented in `.env.example` as local-dev-only.
  3. Health endpoint leaks information about subsystem topology. **Mitigation:** The shape is intentional (it's an operator probe, not a public endpoint). When TLS + auth land in MVP4, `/healthz` is gated to localhost or behind the reverse proxy.
- **Secrets handling:** `.env.example` documents every secret, with file-mount pattern (per §28). `.env` is gitignored.
- **Auditability:** N/A — no audit subsystem in MVP1.
- **Data retention:** N/A — no business data yet.

## 11) UX flows and edge cases

N/A for this feature — no UI surface beyond the placeholder `/` page that says "RelyLoop is running. See [docs/](docs/) for getting started." The placeholder is replaced by `feat_studies_ui` and other UI features.

### Edge/error flows

- **Postgres healthy slowly.** Compose `depends_on` retries the API health check; eventually API connects or fails the deploy with a clear error in `docker compose logs api`.
- **Port collision (5432, 6379, 9200, 9201, 3000, 8000 already in use).** Compose fails with a clear "port already allocated" error. README documents how to override via `.env`.
- **Insufficient memory (<8GB free).** ES container OOMs on startup; `/healthz` reports `elasticsearch: unreachable`. README documents the 16GB recommendation; `.env.example` includes `ES_HEAP_SIZE` knob to tune.

## 12) Given/When/Then acceptance criteria

### AC-1: Fresh-clone boot

- Given a clean machine with Docker installed, no prior RelyLoop containers, and no images cached.
- When the engineer runs `git clone https://github.com/SoundMindsAI/relyloop.git && cd relyloop && make up`.
- Then within 90 seconds (allowing for image pulls on first run), `curl http://localhost:8000/healthz` returns HTTP 200 with `status: ok` and all subsystems reporting healthy. The `make up` first-run install script auto-generated `./secrets/postgres_password` and `./secrets/database_url` before invoking `docker compose up -d`.
- Example values:
  - Input: `curl -s http://localhost:8000/healthz | jq .status`
  - Expected: `"ok"`

### AC-2: Boot with cached images is fast

- Given images already pulled (subsequent boot, not first).
- When the engineer runs `docker compose up -d` from a stopped state.
- Then within 60 seconds, `/healthz` returns 200.

### AC-3: Health endpoint reports specific subsystem failure

- Given the stack is up.
- When the engineer runs `docker compose stop redis` and then `curl -s http://localhost:8000/healthz`.
- Then the response is HTTP 503 with `status: "degraded"` and `subsystems.redis: "down"`; all other subsystems still reflect their actual state.

### AC-4: Missing OpenAI key does not degrade the system

- Given `./secrets/openai_key` does not exist (and `OPENAI_API_KEY_FILE` therefore points at a missing file).
- When `/healthz` is queried.
- Then the response is HTTP 200 with `status: "ok"` and `subsystems.openai: "missing_key"`. (OpenAI is optional pre-judgments feature.) The API logged a startup warning naming the missing secret file path.

### AC-5: PR CI workflow runs all gates

- Given a PR is opened with a trivial backend change and an unintentional lint error.
- When CI runs.
- Then the `pr.yml` workflow fails on the lint job, and the check status on the PR shows "lint failed". The other jobs (typecheck, test, build) may or may not run depending on dependency configuration but the PR cannot merge.

### AC-6: 80% coverage gate enforced

- Given a PR adds 50 lines of backend code with only 20 lines covered by tests (40% coverage on the new code; project total falls below 80%).
- When CI runs.
- Then the test job fails with a coverage-gate error showing actual vs. required percentage.

### AC-7: Migration scaffold works

- Given a fresh database.
- When the engineer runs `make migrate`.
- Then `alembic_version` is created and shows the head revision; subsequent `make migrate` is a no-op.

### AC-8: Make targets are discoverable

- Given the engineer runs `make` (no target).
- Then the output lists all available targets with one-line descriptions: `fmt`, `lint`, `typecheck`, `test`, `up`, `down`, `migrate`, `migrate-create`.

## 13) Non-functional requirements

- **Performance:** `/healthz` responds in <500ms p99. Boot time <60s on cached images.
- **Reliability:** Stack survives `docker compose restart` cleanly (no manual db reset needed).
- **Operability:** Structured logs in JSON to stdout; `docker compose logs api` shows API logs in tail-friendly format.
- **Accessibility/usability:** N/A — no user-facing UI in this feature.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`): `test_health.py` — unit-test the `/healthz` handler with mocked subsystem probes (verify status mapping, parallel execution, timeout behavior). Target: 100% coverage of `backend/app/api/health.py`.
- **Integration tests** (`backend/tests/integration/`): `test_health_integration.py` — boot the full Compose stack via `docker compose up -d` in a CI service, hit `/healthz`, assert HTTP 200 and JSON shape. Mark with `@pytest.mark.integration` so the unit test job runs without Docker.
- **Contract tests** (`backend/tests/contract/`): `test_health_contract.py` — assert the `/healthz` response shape matches the documented OpenAPI schema (auto-generated by FastAPI). Pin the JSON shape via Pydantic model.
- **E2E tests** (`web/tests/e2e/`): N/A — no UI flows in this feature.
- **Other:** GitHub Actions workflow runs lint+typecheck+test+coverage in parallel jobs; expect total wall-clock <5 minutes on a fresh Linux runner.

## 15) Documentation update requirements

- `docs/01_architecture/system-overview.md` already exists and describes the topology; this feature *implements* it. Update §"MVP1 service inventory" if the actual container set diverges from what the doc currently shows.
- `docs/01_architecture/deployment.md` already exists and describes the Compose layout; same — update if the implementation diverges.
- `docs/03_runbooks/README.md` + new `docs/03_runbooks/local-dev.md`: how to boot, restart, debug, and reset the local stack.
- `docs/05_quality/README.md` + new `docs/05_quality/testing.md`: the test-layer convention (unit/integration/contract/e2e) and the 80% coverage gate.
- `docs/08_guides/`: NOT touched by this feature — the worked tutorial is owned by `chore_tutorial_polish`.
- Root `README.md`: update the "What's in this repo today" section to point to the new infra; add a quickstart pointing at `make up`.

## 16) Rollout and migration readiness

- **Feature flags:** None. This feature is not gated.
- **Migration/backfill:** First migration in repo history. No backfill needed (no prior data).
- **Operational readiness gates:**
  - `docs/03_runbooks/local-dev.md` exists and the maintainer can boot from clean clone using only that doc.
  - GitHub repo branch protection updated to require the `pr.yml` workflow.
- **Release gate:** First commit on `main` after this feature ships is the v0.0.1 tag (placeholder for the eventual v0.1.0 MVP1 release). README marks status as "MVP1 in progress" rather than "pre-MVP1."

## 17) Traceability matrix

| FR ID | AC IDs | Planned story IDs (filled in by impl-plan-gen) | Test files | Docs to update |
|---|---|---|---|---|
| FR-1 (boot) | AC-1, AC-2 | TBD | `tests/integration/test_health_integration.py` | `docs/03_runbooks/local-dev.md` |
| FR-2 (healthz) | AC-3, AC-4 | TBD | `tests/unit/test_health.py`, `tests/contract/test_health_contract.py` | `docs/01_architecture/system-overview.md` |
| FR-3 (.env.example) | AC-1 | TBD | `tests/unit/test_settings.py` | `docs/03_runbooks/local-dev.md`, root README |
| FR-4 (CI) | AC-5, AC-6 | TBD | (workflow itself) | `docs/05_quality/testing.md` |
| FR-5 (migration) | AC-7 | TBD | (smoke test in `tests/integration/test_migrations.py`) | `docs/03_runbooks/local-dev.md` |
| FR-6 (Conventional Commits) | (no AC; pre-commit hook) | TBD | N/A | root CONTRIBUTING.md |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-8) pass in CI.
- [ ] All test layers (unit + integration + contract) green; 80% coverage on `backend/app/api/health.py` and `backend/app/core/settings.py`.
- [ ] Documentation updates merged: system-overview diagram, local-dev runbook, testing-conventions doc, README quickstart.
- [ ] `pr.yml` workflow added to branch protection on `main`.
- [ ] Maintainer can clone-and-boot from clean state following only `docs/03_runbooks/local-dev.md`.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-08 — Single-tenant + no auth for MVP1 — confirmed by umbrella spec §27 line 2299.
- 2026-05-08 — MVP1 ships ES + OpenSearch only (no Fusion, no Solr) — confirmed by umbrella spec §27 line 2296 and §25 line 2192.
- 2026-05-08 — Langfuse, ClickHouse, SigNoz, Caddy excluded from MVP1 Compose — derived from §27 line 2308.
- 2026-05-09 — Pre-commit secret scanning: **gitleaks** (industry standard, single binary, fastest of the three).
- 2026-05-09 — Docker image base: **`python:3.12-slim`** (Alpine's musl libc has surprised real Python projects; distroless adds CI complexity).
- 2026-05-09 — Lockfile workflow: **uv-only** (uv handles lockfile + venv + install in one tool).
- 2026-05-09 — `/healthz.version` source: **`importlib.metadata.version("relyloop")` + git SHA injected at build via `RELYLOOP_GIT_SHA` Docker ARG**, formatted as `0.1.0+abc1234`.
