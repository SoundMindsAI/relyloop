# Local Development Runbook

> Walkthrough for booting, debugging, and resetting the RelyLoop MVP1 stack on a developer laptop. Covers the AC-1 happy path from `infra_foundation`'s feature spec.

## Prerequisites

| Tool | Min version | Why |
|---|---|---|
| Docker | 24+ with Compose v2 | `services.depends_on: condition: service_healthy` requires Compose v2 |
| Python | **3.13** (soft-pinned via `.python-version`) | `pyproject.toml` `requires-python = ">=3.13"` is the floor; `.python-version` at repo root soft-pins **3.13** specifically so the host's `.venv` matches the dev-deps container's `ghcr.io/astral-sh/uv:python3.13-bookworm` image. uv auto-fetches Python 3.13 if your system doesn't have it. See [Local Python version](#local-python-version) below for why a newer Python on the host causes the in-container `uv sync` to silently rebuild `.venv` with broken symlinks (`infra_uv_sync_drops_precommit`). |
| Node | 20.18+ | Next.js 16 minimum (bumped from 18+ on 2026-05-12). Run `nvm use` from the repo root before `pnpm install` / `pnpm dev` — the `.nvmrc` selects Node 22, and `ui/.npmrc`'s `engine-strict=true` makes `pnpm install` hard-fail on the wrong Node. |
| pnpm | 9+ | Frontend package manager |
| 16 GB RAM | — | ES + OpenSearch each consume ~1 GB heap (`-Xms512m -Xmx512m`) |

If you don't have `uv` and `pnpm`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv
brew install pnpm                                  # pnpm (macOS)
```

### Local Python version

The repo's `.python-version` file pins local-dev Python to **3.13** to match
the dev-deps container image (`ghcr.io/astral-sh/uv:python3.13-bookworm`).
`uv sync` reads `.python-version`, fetches Python 3.13 if your system doesn't
have it, and creates `.venv` against it.

**Why the pin matters:** if your host runs a newer Python (say 3.14) and you
run the in-container integration-test pattern (per
[`bug_capability_check_test_isolation/idea.md`](../00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md)),
the container's `uv sync` rebuilds `.venv` against its own 3.13 with
container-only symlinks. When the container exits, your host's `git commit`
hits `No module named pre_commit` (and every other module in `.venv` is
similarly broken). Pinning host + container to the same Python eliminates
the rebuild.

**Migrating from an older `.venv`** (run once if you previously had `.venv`
built against a different Python):

```bash
rm -rf .venv
uv sync                # uv reads .python-version, fetches 3.13, rebuilds
```

Captured in [`infra_uv_sync_drops_precommit`](../02_product/planned_features/infra_uv_sync_drops_precommit/idea.md).

## First-run quickstart (AC-1)

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop
make up                                  # auto-generates required secrets, then docker compose up -d
curl -s http://localhost:8000/healthz | jq
```

Expected response within ~90 seconds (cold image pull) or ~60 seconds (warm cache):

```json
{
  "status": "ok",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "missing_key",
    "elasticsearch": "reachable",
    "opensearch": "reachable"
  },
  "openai_endpoint": "https://api.openai.com/v1",
  "openai_capabilities": { "chat": "untested", "function_calling": "untested", "structured_output": "untested" },
  "version": "<git-sha>",
  "uptime_seconds": 12
}
```

`subsystems.openai: "missing_key"` is expected on a fresh install — the OpenAI key file is empty by default. To exercise LLM-dependent features later, populate `./secrets/openai_key` with a real key (see "Operator setup checklist" below).

## Operator setup checklist (per `infra_foundation` §7.5)

These are the manual handoffs `make up` does NOT do for you:

1. **(Optional) Override Compose defaults.** If you need to point at a local LLM (Ollama, LM Studio, vLLM) or change `ES_HEAP_SIZE`:

   ```bash
   cp .env.example .env
   # edit .env — common overrides:
   #   OPENAI_BASE_URL=http://host.docker.internal:11434/v1   (Ollama)
   #   ES_HEAP_SIZE=1024m                                      (more headroom)
   ```

   Then `make down && make up` to pick up the change.

2. **(Optional) Populate OpenAI key for capability check.** The Story 3.3 capability check runs once at startup if `./secrets/openai_key` is non-empty:

   ```bash
   echo "sk-...your-key..." > ./secrets/openai_key
   make down && make up
   # `/healthz` will report `subsystems.openai: configured` once the check
   # completes (~10s after API startup), and `openai_capabilities.*` will
   # populate from "untested" to "ok".
   ```

3. **GitHub branch protection (after the CI workflow is green on `main`).** Open
   `https://github.com/SoundMindsAI/relyloop/settings/branches`, edit the
   `main` rule, and require the `pr / backend`, `pr / frontend`, and
   `pr / docker` checks. This is the final operator-only gate before merging
   `infra_foundation`.

## Local-vs-CI test layers

| Layer | Local from host | CI |
|---|---|---|
| `make test-unit` | ✓ runs (no Docker, no DB) | ✓ runs |
| `make test-contract` | ✓ runs (no DB; mocked deps) | ✓ runs |
| `make test-integration` (`/healthz` shape) | ✓ runs if `make up` first; skips cleanly otherwise | ✓ skips (API not booted in CI) |
| `make test-integration` (Alembic round-trip) | ⚠ **skips** — Postgres is internal-only on the Compose network per CLAUDE.md "Ports". Migration tests can't reach `postgres:5432` from your shell. | ✓ runs (CI exposes Postgres on `localhost:5432` via service containers) |

**Migrations run automatically at boot.** The `migrate` Compose init container (added by `bug_worker_optuna_init_race`) runs `alembic upgrade head && python -m backend.app.db.optuna_schema` once between Postgres healthy and api/worker startup. `make migrate` stays available for re-runs after authoring a new revision without bouncing the stack:

```bash
make migrate           # idempotent re-run (no-op if already at head)
docker compose exec postgres psql -U relyloop -d relyloop -c '\dt'   # confirm alembic_version row
```

This exercises the same code path as the CI test (`alembic upgrade head` → `alembic_version` row at `0001`) without needing host-side Postgres.

If you want the round-trip test to actually run from your shell, you'd need to either expose Postgres on `127.0.0.1:5432` (changes spec — don't ship that) or run via the dev-deps container pattern below.

### In-container integration tests (canonical pattern)

When the host-skip rows above need to actually run (typically while debugging
a feature that touches DB or HTTP), use this command — it gives you a
one-shot Python 3.13 container with the project mounted and on the Compose
network so it can reach `postgres`, `elasticsearch`, and `opensearch`:

```bash
docker run --rm --network relyloop_default \
  -v "$(pwd):/app" -v /app/.venv -w /app \
  -e DATABASE_URL_FILE=/app/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/app/secrets/postgres_password \
  ghcr.io/astral-sh/uv:python3.13-bookworm \
  bash -c 'uv sync --quiet && uv run pytest -m integration backend/tests/integration/'
```

**The `-v /app/.venv` flag is load-bearing** (per
[`infra_uv_sync_drops_precommit`](../02_product/planned_features/infra_uv_sync_drops_precommit/idea.md)).
It mounts an anonymous Docker volume at `/app/.venv` *inside the container*,
masking the host's bind-mounted `.venv` for the duration of the run. Without
it, the container's `uv sync` rewrites the venv's `pyvenv.cfg` + script
shebangs (`#!/app/.venv/bin/python`) — those paths don't exist on the host,
so the next host-side `git commit` dies with `No module named pre_commit`
(and every other module is similarly broken until you `uv sync` again from
the host).

The trade: each container run does a fresh `uv sync` against the package
cache (~10-20s vs the bind-mount-and-reuse pattern's ~0s). Mount
`~/.cache/uv:/root/.cache/uv` if you want to share the wheel cache.

## Daily-use Make targets

| Target | What it does |
|---|---|
| `make up` | Generate secrets if missing → `docker compose build` (every buildable service) → `docker compose up -d` |
| `make down` | `docker compose down` (removes containers + network; preserves data volumes) |
| `make logs` | `docker compose logs -f api worker` |
| `make migrate` | `alembic upgrade head` + initialize Optuna RDB schema (idempotent — also runs automatically via the `migrate` init container at boot) |
| `make migrate-create name=<slug>` | New Alembic revision (autogenerate) |
| `make test-unit` | Backend unit tests (no Docker required) |
| `make test-integration` | Backend integration tests (requires running stack) |
| `make test-contract` | Backend contract tests |
| `make test` | All test layers in sequence |
| `make fmt` | Format Python (ruff) + frontend (prettier) |
| `make lint` | Lint Python (ruff) + frontend (eslint) |
| `make typecheck` | mypy --strict + tsc --noEmit |
| `make pre-commit` | Run all pre-commit hooks against the entire repo |
| `make pre-commit-install` | Install Git hooks (commit-msg + pre-commit) |
| `make reset` | **DESTRUCTIVE** — `docker compose down -v && rm -rf ./data` (prompts unless `FORCE=1`) |

`make` (no target) prints this list with descriptions.

## Debugging

### Stack won't start

```bash
make logs                # tail api + worker
docker compose ps        # see container health states
docker compose logs postgres redis elasticsearch opensearch
```

Common causes:

- **Port collision** — another Postgres / Redis / ES on the host. Check with
  `lsof -i :8000 -i :9200 -i :9201`. The Compose file binds API + ES + OpenSearch
  to host ports; Postgres + Redis are internal-only on the Compose network.
- **OOM (especially ES / OpenSearch)** — bump `ES_HEAP_SIZE` in `.env` to
  `1024m` or higher; `/healthz` will report `elasticsearch: unreachable` if it
  OOMs. Make sure you have ~8 GB of free RAM.
- **Missing secrets** — `bare docker compose up` from a fresh clone fails with
  `error mounting secrets: source file ./secrets/postgres_password does not
  exist`. Always use `make up` (which runs `scripts/install.sh`).

### Tests failing locally but green in CI (or vice versa)

- **Settings cache pollution.** `get_settings()` is `lru_cache`'d. Tests that
  modify `DATABASE_URL_FILE` etc. via `monkeypatch.setenv` should call
  `get_settings.cache_clear()`.
- **Database state.** `make test-integration` runs against the live Compose
  Postgres. Reset with `make reset` (destructive — drops volumes) if migrations
  diverge.
- **Pre-commit hooks.** Run `make pre-commit` before pushing — CI runs the
  same ruff/format-check/mypy gates and will reject formatting drift.

### Resetting

```bash
make reset             # interactive — type "yes" to confirm
make reset FORCE=1     # skip confirmation prompt
```

Removes all containers, volumes, and the `./data/` directory. `./secrets/` is
preserved (your generated postgres_password + database_url stay intact).

## Working with the OpenAI capability check (Story 3.3 / FR-7)

Once you populate `./secrets/openai_key`, the API runs a 4-step self-test
against `OPENAI_BASE_URL` at startup:

1. `GET /models` — endpoint reachable
2. `POST /chat/completions` — chat works
3. `POST /chat/completions` with a trivial tool — function-calling works
4. `POST /chat/completions` with `response_format=json_schema` — structured output works

Results are cached in Redis under `openai:capabilities:{sha256(base_url)}`
with a 24h TTL. To force a re-run after changing endpoints:

```bash
docker compose exec redis redis-cli DEL "openai:capabilities:*"
make down && make up
```

The check runs **non-blocking** (`asyncio.create_task`) so a slow LLM endpoint
never delays startup. WARN logs are emitted on any probe failure.

## Continuous integration

Every PR runs `.github/workflows/pr.yml`:

- **backend** — uv sync · ruff check · ruff format --check · mypy --strict ·
  pytest with 80% coverage gate · service containers for Postgres + Redis +
  ES + OpenSearch
- **frontend** — pnpm install · lint · typecheck · vitest · `next build`
- **docker** — `buildx build` for `relyloop/api` (no push)

The `docker` job depends on backend + frontend passing. CI is hermetic — no
managed cloud (CLAUDE.md "Common Pitfalls").

## Where to look next

- [`docs/05_quality/testing.md`](../05_quality/testing.md) — test layer conventions + 80% coverage gate
- [`docs/01_architecture/deployment.md`](../01_architecture/deployment.md) — the full Compose layout reference
- [`docs/01_architecture/llm-orchestration.md`](../01_architecture/llm-orchestration.md) — capability check + function-calling pattern
- [`docs/02_product/planned_features/infra_foundation/`](../02_product/planned_features/infra_foundation/) — the spec + plan that produced this stack
