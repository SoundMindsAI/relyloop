#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# infra_generated_artifact_freshness_gate / Story 2.3 — FR-2 + FR-6.
#
# Regenerates `ui/src/lib/types.ts` from the committed `ui/openapi.json`
# snapshot via the package script `pnpm types:gen` (which wraps the
# lockfile-pinned `openapi-typescript` binary — Story 2.3 ditched the
# `npx` fallback per FR-5). Fails if `git status --porcelain -- ui/src/
# lib/types.ts` is non-empty.
#
# The regen uses the **absolute filesystem path** to the snapshot
# (`OPENAPI_URL="$PWD/ui/openapi.json"`) — `openapi-typescript@7.5.2`
# accepts that form directly (verified in Story 2.3 task 2; no `file://`
# fallback needed).
#
# Uses `git status --porcelain` (not `git diff --exit-code`) so the
# untracked-file regression (a fresh commit forgetting to `git add`
# `types.ts`) is flagged.
#
# Usage:
#   bash scripts/ci/verify_types_fresh.sh
#
# Override env vars (intended for the self-test harness, NOT production):
#
#   TYPES_FRESH_REPO_ROOT
#       Override `git rev-parse --show-toplevel` so the guard operates
#       on a disposable fixture instead of the live repo.
#
#   TYPES_FRESH_REGEN_SCRIPT
#       Path to a bash script that performs the regen step. Defaults to
#       running `OPENAPI_URL="$REPO_ROOT/ui/openapi.json" pnpm --dir ui
#       types:gen` directly. The self-test points this at a small
#       fixture-local stub so it doesn't need pnpm + node_modules in
#       the fixture (the banner has its own Story-2.3 vitest; the
#       guard's job is diff-detection).
#
# Exits 0 when types.ts is fresh, 1 when it is stale.

set -euo pipefail

if [[ -n "${TYPES_FRESH_REPO_ROOT:-}" ]]; then
  REPO_ROOT="${TYPES_FRESH_REPO_ROOT}"
else
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi
cd "${REPO_ROOT}"

if [[ -n "${TYPES_FRESH_REGEN_SCRIPT:-}" ]]; then
  REGEN_CMD=(bash "${TYPES_FRESH_REGEN_SCRIPT}")
else
  # Pass the absolute path to the snapshot (FR-2 source form). The
  # package script invokes `node scripts/gen-types.mjs`, which after
  # Story 2.3 uses the pinned `openapi-typescript` binary (no `npx`).
  REGEN_CMD=(env "OPENAPI_URL=${REPO_ROOT}/ui/openapi.json" pnpm --dir ui types:gen)
fi

"${REGEN_CMD[@]}"

DRIFT="$(git status --porcelain -- ui/src/lib/types.ts)"

if [[ -n "${DRIFT}" ]]; then
  echo "ERROR: ui/src/lib/types.ts is stale." >&2
  echo "Fix with:" >&2
  echo "  bash scripts/regen-generated-artifacts.sh && git add ui/openapi.json ui/src/lib/types.ts" >&2
  echo >&2
  echo "Drift detected (diagnostic):" >&2
  printf '%s\n' "${DRIFT}" >&2
  exit 1
fi

echo "OK: ui/src/lib/types.ts is fresh."
