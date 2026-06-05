# Local Development Runbook

> Walkthrough for booting, debugging, and resetting the RelyLoop MVP1 stack on a developer laptop. Covers the AC-1 happy path from `infra_foundation`'s feature spec.

## Prerequisites

| Tool | Min version | Why |
|---|---|---|
| Docker | 24+ with Compose v2 | `services.depends_on: condition: service_healthy` requires Compose v2 |
| Python | **3.13** (soft-pinned via `.python-version`) | `pyproject.toml` `requires-python = ">=3.13"` is the floor; `.python-version` at repo root soft-pins **3.13** specifically so the host's `.venv` matches the dev-deps container's `ghcr.io/astral-sh/uv:python3.13-bookworm` image. uv auto-fetches Python 3.13 if your system doesn't have it. See [Local Python version](#local-python-version) below for why a newer Python on the host causes the in-container `uv sync` to silently rebuild `.venv` with broken symlinks (`infra_uv_sync_drops_precommit`). |
| Node | **22** (soft-pinned via `.nvmrc`) | Next.js 16 minimum is 20.18+; `.nvmrc` pins **22** specifically. Run `nvm use` from the repo root before `pnpm install` / `pnpm dev`, and `ui/.npmrc`'s `engine-strict=true` makes `pnpm install` hard-fail on the wrong Node. See [Local Node version](#local-node-version) below for why pre-commit hooks need help finding Node when the shell's PATH has a stale nvm-pinned older version. |
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

Captured in [`infra_uv_sync_drops_precommit`](../00_overview/planned_features/infra_uv_sync_drops_precommit/idea.md).

### Local Node version

The repo's `.nvmrc` file pins local-dev Node to **22**. Run `nvm use` from
the repo root once per shell session and `nvm` resolves it automatically.

**Why the pin matters for pre-commit hooks:** the `prettier-ui` and
`eslint-ui` pre-commit hooks shell out to `pnpm --dir ui …`. Pre-commit's
hook subshell inherits the parent shell's PATH — if your shell still has a
stale `nvm use`-pinned older Node (say `~/.nvm/versions/node/v18.20.8/bin`)
ahead of the system Node, pnpm sees the older version, hits
`ui/package.json`'s `engines.node = ">=20.18"` floor (enforced hard by
`ui/.npmrc`'s `engine-strict=true`), and aborts:

```
ERR_PNPM_UNSUPPORTED_ENGINE — Expected version: >=20.18 — Got: v18.20.8
```

To avoid hand-prefixing every commit with `PATH="$HOME/.nvm/versions/node/v22.../bin:$PATH"`,
the pre-commit hooks invoke `scripts/run-pnpm.sh` instead of `pnpm`
directly. That wrapper sources `~/.nvm/nvm.sh` and runs `nvm use` before
`exec pnpm`, mirroring the `NVM_GUARD` macro at
[`Makefile:95-98`](../../Makefile#L95-L98). CI is unaffected — it has no
nvm; the wrapper falls through to bare `pnpm` against the system Node
that `actions/setup-node@v4` provisions.

If you're not using nvm, install Node 22 directly (e.g.,
`brew install node@22`) and put it ahead of any other Node on PATH.

Captured in [`chore_precommit_node_path_resolution`](../00_overview/implemented_features/2026_05_21_chore_precommit_node_path_resolution/idea.md).

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

**Real-engine overlap-probe tests** (5 rewrites at AC-1..AC-4b in [`backend/tests/integration/test_studies_api.py`](../../backend/tests/integration/test_studies_api.py) + helper smoke tests in [`backend/tests/integration/test_es_overlap_probe_helpers.py`](../../backend/tests/integration/test_es_overlap_probe_helpers.py), landed by `infra_study_preflight_real_engine_integration`) need both ES reachable at `http://localhost:9200` (or `http://elasticsearch:9200` in-container) AND a `local-es:` entry in `./secrets/cluster_credentials.yaml`. Tests carry `@es_required` and skip cleanly when ES is unreachable; the helper calls `pytest.skip(...)` when `local-es` is missing locally and `RuntimeError` when missing under `CI=true`. Two CI-only sentinels (`test_overlap_probe_real_engine_sentinel` + `test_overlap_probe_real_engine_credentials_sentinel`) fail loudly in CI if either dependency regresses in the workflow.

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
[`infra_uv_sync_drops_precommit`](../00_overview/planned_features/infra_uv_sync_drops_precommit/idea.md)).
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

### Resetting demo state

`make up` auto-seeds 4 meaningful demo clusters (`acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`) on a fresh stack via `scripts/seed_meaningful_demos.py --if-empty`. If you wipe or modify that state and want to start over:

```bash
make seed-demo FORCE=1   # TRUNCATE demo tables + reseed (skip confirmation)
```

After the reseed, the dashboard shows a "You're set up with demo data." banner above the StartHereChecklist. The banner is dismissable; once dismissed, the dismissal persists per-browser via the localStorage key `relyloop.home-first-run-demo-nudge.dismissed`. **`make seed-demo FORCE=1` does NOT clear that localStorage key** — to show the banner again after dismissal, clear the key via browser dev tools (`localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed')` in the JS console). A future Phase 2 "Reset to demo state" UI affordance (tracked in [`phase2_idea.md`](../00_overview/planned_features/feat_home_first_run_demo_nudge/phase2_idea.md)) will optionally clear the key as a side effect of reseeding.

### Demo seed produced fewer studies than expected

A full `make seed-demo FORCE=1` should leave **5 completed studies** — four small scenarios (`tune-product-title-boost-baseline`, `reduce-fuzziness-helpcenter-search`, `add-7day-freshness-decay-news`, `tune-jobtitle-vs-company-boost`) plus the rich 1000-doc ESCI scenario (`tune-acme-products-rich-boosts`). If you end up with fewer, the seed hit a per-scenario failure. The script now **continues past a failed scenario** and prints a `=== N scenario(s) FAILED — demo is incomplete ===` summary at the end (and exits non-zero), so scroll up to the summary to see which scenario failed and why.

The most common cause is the **engine disk flood-stage watermark**. `news-search-staging` is the only OpenSearch-backed scenario; the other four use Elasticsearch. When the Docker disk crosses ~95% used, Elasticsearch/OpenSearch auto-applies write blocks and rejects `PUT /<index>` with:

```
HTTP 403 index_create_block_exception:
  blocked by: [FORBIDDEN/10/cluster create-index blocked (api)]
```

Recovery:

```bash
# 1. See how full the engine's disk is (>~95% = flooded). Use 9201 for OpenSearch, 9200 for ES.
curl -s "http://127.0.0.1:9201/_cat/allocation?h=node,disk.percent,disk.avail&v"

# 2. Reclaim Docker disk (build cache + dangling images are safe to drop).
docker builder prune -f
docker image prune -f

# 3. Clear the blocks the watermark auto-applied (they do NOT self-clear).
curl -s -X PUT "http://127.0.0.1:9201/_cluster/settings" -H 'Content-Type: application/json' \
  -d '{"persistent":{"cluster.blocks.create_index":null}}'
curl -s -X PUT "http://127.0.0.1:9201/_all/_settings" -H 'Content-Type: application/json' \
  -d '{"index.blocks.read_only_allow_delete":null}'
# (repeat step 3 against :9200 if Elasticsearch was the one flooded)

# 4. Reseed.
make seed-demo FORCE=1
```

> **Note:** before the continue-on-failure fix, a single scenario failure hard-stopped the whole seed, so a flooded OpenSearch would silently leave you with only the *two* Elasticsearch studies seeded before `news-search-staging`. If you saw that symptom on an older checkout, it was this same disk-watermark cause.

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

## Opting a template into normalizer tuning

Shipped by [`feat_query_normalization_tuning`](../00_overview/planned_features/02_mvp2/feat_query_normalization_tuning/feature_spec.md). Templates are immutable, so you opt in by creating a **new** template whose `declared_params` includes the reserved key `query_normalizer` — and whose body does **NOT** reference `{{ query_normalizer }}` (the adapter consumes it; a reference is rejected with `RESERVED_PARAM_REFERENCED`):

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/query-templates \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "products-normalizer-tuning",
    "engine_type": "elasticsearch",
    "body": "{\"query\": {\"match\": {\"title\": \"{{ query_text }}\"}}}",
    "declared_params": {"query_normalizer": "string"}
  }'
```

Then create a study against that template whose `search_space.params` declares `query_normalizer` as a Categorical whose `choices` are a subset of the four built-ins:

```jsonc
"search_space": {
  "params": {
    "query_normalizer": {
      "type": "categorical",
      "choices": ["none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions"]
    }
  }
}
```

The loop tunes the normalizer like any categorical. A choice outside the allowlist returns `400 NORMALIZER_CHOICE_INVALID`; declaring `query_normalizer` as a non-Categorical returns `400 NORMALIZER_PARAM_SHAPE`. The winning choice rides in the proposal's `config_diff` and the PR body's **"Operator-side requirement"** section, where a copy-pasteable Python snippet shows how to reproduce the normalizer in your production query layer.

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
- [`docs/00_overview/planned_features/infra_foundation/`](../00_overview/planned_features/infra_foundation/) — the spec + plan that produced this stack
