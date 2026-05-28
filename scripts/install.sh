#!/usr/bin/env bash
# RelyLoop install script (infra_foundation Story 4.4 / FR-3).
#
# Auto-generates the required + placeholder secret files mounted by Compose,
# validates the Compose config, then runs `docker compose up -d`. Idempotent:
# re-running does NOT regenerate or overwrite existing secret content.
#
# CLAUDE.md Absolute Rule #2: secrets live in mounted files (./secrets/<name>),
# never as bare env vars. Compose's `secrets:` directive errors out at startup
# if a source file is missing — even for "optional" secrets — so we create
# zero-byte placeholders for openai_key. The application layer (Pydantic
# Settings) treats empty content as "not configured". GitHub PATs are NOT
# global: each ``config_repos`` row carries its own ``auth_ref`` field naming
# a ``./secrets/<auth_ref>`` file, registered via POST /api/v1/config-repos.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# 1. Ensure ./secrets/ exists.
mkdir -p ./secrets

# 2. Generate postgres_password if missing or empty.
if [[ ! -s ./secrets/postgres_password ]]; then
  echo "Generating ./secrets/postgres_password (random base64)..."
  openssl rand -base64 32 | tr -d '\n' > ./secrets/postgres_password
  chmod 600 ./secrets/postgres_password
fi

# 3. Generate database_url if missing, empty, OR using a non-asyncpg driver.
#    The app reads this URL via SQLAlchemy; without `+asyncpg` the default
#    psycopg2 dialect is selected and the async event loop blocks on sync
#    DB-API calls (or, if psycopg2 isn't installed, ModuleNotFoundError at
#    /healthz). The early prefix-check catches stale stub files left behind
#    by manual `docker compose config` testing — a real bug surfaced during
#    PR #4 first-run testing.
if [[ ! -s ./secrets/database_url ]] || ! grep -q '^postgresql+asyncpg://' ./secrets/database_url; then
  echo "Generating ./secrets/database_url (asyncpg driver)..."
  PASSWORD="$(cat ./secrets/postgres_password)"
  printf 'postgresql+asyncpg://relyloop:%s@postgres/relyloop' "${PASSWORD}" \
    > ./secrets/database_url
  chmod 600 ./secrets/database_url
fi

# 4. Create empty placeholder files for optional secrets (Compose mounts them).
[[ -e ./secrets/openai_key ]]     || { touch ./secrets/openai_key;     chmod 600 ./secrets/openai_key;     }
if [[ ! -e ./secrets/cluster_credentials.yaml ]]; then
  # Seed default credentials for the local Compose ES + OpenSearch containers
  # (well-known dev defaults — not production secrets). The seed-clusters
  # script (`make seed-clusters`) reads these refs to register the two
  # containers as cluster rows. Operators add real production credentials
  # by editing this file before `make seed-clusters` for non-local clusters.
  cat > ./secrets/cluster_credentials.yaml <<'CLUSTER_CREDS_EOF'
local-es:
  username: elastic
  password: changeme
local-opensearch:
  username: admin
  password: admin
CLUSTER_CREDS_EOF
  chmod 600 ./secrets/cluster_credentials.yaml
fi

# 5. Validate Compose config (catches typos before pulling images).
docker compose config --quiet

# 6. Build images locally. `docker compose up -d` does NOT auto-rebuild after
#    code changes — it uses the cached `relyloop/api:dev` tag. Without an
#    explicit build step, contributors who pull new code and re-run `make up`
#    keep running the stale image (PR #4 first-run testing surfaced exactly
#    this — a stale image missing newly-added Python deps).
#    No-args = build every service that declares a `build:` block. The earlier
#    hardcoded `api worker` list silently skipped the `ui` service after it
#    joined Compose, leaving frontend changes invisible until manual rebuild.
#
#    CI escape hatch: set `RELYLOOP_SKIP_BUILD=1` to skip this step. CI pre-
#    builds the API + UI images in parallel `docker` + `docker-ui` jobs and
#    `docker load`s them before calling `make up`, so a second `docker compose
#    build` here would be ~3-5min of pure duplication. See
#    chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md.
if [[ "${RELYLOOP_SKIP_BUILD:-0}" != "1" ]]; then
  docker compose build
else
  echo "RELYLOOP_SKIP_BUILD=1 set — skipping 'docker compose build' (CI artifact-handoff path)"
fi

# 7. Bring the stack up. `docker compose up -d` is itself idempotent.
#    `--wait` blocks until every container's healthcheck passes (or fails) —
#    needed by step 8 below, which runs the seed against a healthy stack.
docker compose up -d --wait

# 8. Auto-seed meaningful demo data when the stack is empty (idempotent —
#    `--if-empty` is a no-op when clusters already exist, so re-running
#    `make up` against a populated stack preserves operator-mutable state).
#    Fixes the first-run UX where `make up` would land the operator on an
#    empty stack with no path to create a meaningful study until they
#    discovered `make seed-demo` on their own. Operators who explicitly
#    want to wipe + reseed still call `make seed-demo FORCE=1`.
#
#    The auto-seed is non-fatal: a failure here doesn't roll back the
#    stack startup. The operator can re-run `make seed-demo FORCE=1`
#    manually once the failure is understood.
#
#    CI escape hatch: set `RELYLOOP_SKIP_AUTO_SEED=1` to skip this step.
#    The smoke job sets this because the dashboard E2E specs that needed
#    the demo data were skipped in CI on 2026-05-28 (see
#    chore_drop_demo_seed_from_ci/idea.md). Without the skip, install.sh
#    would do ~5min of demo-seeding inside `make up` that no CI step
#    consumes. See chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md.
if [[ "${RELYLOOP_SKIP_AUTO_SEED:-0}" != "1" ]]; then
  echo "Checking demo state…"
  if ! python3 scripts/seed_meaningful_demos.py --if-empty; then
    echo "Warning: auto-seed failed (non-fatal). Run 'make seed-demo FORCE=1' manually."
  fi
else
  echo "RELYLOOP_SKIP_AUTO_SEED=1 set — skipping demo auto-seed (CI fast path)"
fi
