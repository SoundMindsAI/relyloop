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

# 3. Generate database_url if missing or empty (templated from password).
if [[ ! -s ./secrets/database_url ]]; then
  echo "Generating ./secrets/database_url..."
  PASSWORD="$(cat ./secrets/postgres_password)"
  printf 'postgresql+asyncpg://relyloop:%s@postgres/relyloop' "${PASSWORD}" \
    > ./secrets/database_url
  chmod 600 ./secrets/database_url
fi

# 4. Create empty placeholder files for optional secrets (Compose mounts them).
[[ -e ./secrets/openai_key ]]     || { touch ./secrets/openai_key;     chmod 600 ./secrets/openai_key;     }
[[ -e ./secrets/github_token ]]   || { touch ./secrets/github_token;   chmod 600 ./secrets/github_token;   }
if [[ ! -e ./secrets/cluster_credentials.yaml ]]; then
  printf '{}\n' > ./secrets/cluster_credentials.yaml
  chmod 600 ./secrets/cluster_credentials.yaml
fi

# 5. Validate Compose config (catches typos before pulling images).
docker compose config --quiet

# 6. Bring the stack up. `docker compose up -d` is itself idempotent.
exec docker compose up -d
