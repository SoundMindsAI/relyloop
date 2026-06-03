#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# infra_generated_artifact_freshness_gate / Story 2.2 — FR-7 + FR-6.
#
# Regenerates `ui/openapi.json` via the offline exporter (Story 2.1) and
# fails if `git status --porcelain -- ui/openapi.json` is non-empty
# (modified, untracked, or deleted). Catches the failure mode where a
# backend schema change ships without re-running the exporter, leaving
# the committed snapshot stale.
#
# Uses `git status --porcelain` (not `git diff --exit-code`) so the
# untracked-file regression (the FR-9 / AC-9 case — a first commit that
# forgot to `git add` the snapshot) is flagged.
#
# Usage:
#   bash scripts/ci/verify_openapi_snapshot_fresh.sh
#
# Override env vars (intended for the self-test harness, NOT production):
#
#   OPENAPI_SNAPSHOT_FRESH_REPO_ROOT
#       Override `git rev-parse --show-toplevel` so the guard operates
#       on a disposable fixture instead of the live repo.
#
#   OPENAPI_SNAPSHOT_REGEN_SCRIPT
#       Path to a bash script that performs the regen step. Defaults to
#       running `uv run python -m backend.app.openapi_export --out
#       ui/openapi.json` directly. The self-test points this at a small
#       fixture-local stub so it doesn't need uv + the project venv in
#       the fixture (the exporter has its own Story-2.1 unit test; the
#       guard's job is diff-detection). Path form (not a command string)
#       avoids `read -ra` word-splitting / quoting traps.
#
# Exits 0 when the snapshot is fresh, 1 when it is stale.

set -euo pipefail

if [[ -n "${OPENAPI_SNAPSHOT_FRESH_REPO_ROOT:-}" ]]; then
  REPO_ROOT="${OPENAPI_SNAPSHOT_FRESH_REPO_ROOT}"
else
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi
cd "${REPO_ROOT}"

# Resolve regen invocation. Override is a SCRIPT PATH (not a shell
# command string) so we don't have to navigate `read -ra` word-splitting
# or shell-quoting traps for an env var with embedded quotes / spaces.
# The default array form keeps the production path argv-clean.
if [[ -n "${OPENAPI_SNAPSHOT_REGEN_SCRIPT:-}" ]]; then
  REGEN_CMD=(bash "${OPENAPI_SNAPSHOT_REGEN_SCRIPT}")
else
  REGEN_CMD=(uv run python -m backend.app.openapi_export --out ui/openapi.json)
fi

"${REGEN_CMD[@]}"

DRIFT="$(git status --porcelain -- ui/openapi.json)"

if [[ -n "${DRIFT}" ]]; then
  echo "ERROR: ui/openapi.json is stale." >&2
  echo "Fix with the canonical chained regen (Story 2.4):" >&2
  echo "  bash scripts/regen-generated-artifacts.sh" >&2
  echo "(or this gate alone:" >&2
  echo "  uv run python -m backend.app.openapi_export --out ui/openapi.json && git add ui/openapi.json)" >&2
  echo >&2
  echo "Drift detected (diagnostic):" >&2
  printf '%s\n' "${DRIFT}" >&2
  exit 1
fi

echo "OK: ui/openapi.json is fresh."
