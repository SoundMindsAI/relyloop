#!/usr/bin/env bash
# RelyLoop install script — invoked by `make up` on first run.
# Story 4.4 fills in: generate ./secrets/* files (postgres_password, database_url,
# openai_key, github_token, cluster_credentials.yaml), validate Compose config,
# then docker compose up -d.
#
# Until Story 4.4 lands, this stub prints a TODO and runs `docker compose up -d`
# (which will fail loudly on missing secret-file mounts — that's expected).

set -euo pipefail

echo "TODO: secrets generation lands in Story 4.4 (infra_foundation/implementation_plan.md)"
docker compose up -d
