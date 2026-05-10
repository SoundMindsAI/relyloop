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
# zero-byte placeholders for openai_key + github_token. The application layer
# (Pydantic Settings) treats empty content as "not configured".

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
[[ -e ./secrets/github_token ]]   || { touch ./secrets/github_token;   chmod 600 ./secrets/github_token;   }
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
docker compose build api worker

# 7. Bring the stack up. `docker compose up -d` is itself idempotent.
exec docker compose up -d
