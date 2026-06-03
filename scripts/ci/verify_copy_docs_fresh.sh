#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# infra_generated_artifact_freshness_gate / Story 1.2 — FR-1 + FR-3 + FR-8 (Phase-1 half).
#
# Regenerates `ui/public/docs/` from `docs/08_guides/` and fails if
# `git status --porcelain -- ui/public/docs/` is non-empty (modified,
# untracked, or deleted). Catches the failure mode where an operator
# edits a source guide without re-running `node ui/scripts/copy-docs.mjs`.
#
# Uses `git status --porcelain` (not `git diff --exit-code`) so untracked
# files (e.g., a freshly-added DOCS entry whose public copy was not staged)
# are flagged — `git diff` would silently miss those.
#
# Usage:
#   bash scripts/ci/verify_copy_docs_fresh.sh                    # standard local/CI run
#   COPY_DOCS_FRESH_REPO_ROOT=/path/to/wt bash …/verify_copy_docs_fresh.sh
#       # explicit repo-root override used by the self-test harness; the
#       # default discovers it via `git rev-parse --show-toplevel`.
#
# Exits 0 when the tree is fresh, 1 when it is stale.

set -euo pipefail

# Resolve repo root. The override env var lets the self-test point at a
# disposable fixture without polluting the operator's working tree.
if [[ -n "${COPY_DOCS_FRESH_REPO_ROOT:-}" ]]; then
  REPO_ROOT="${COPY_DOCS_FRESH_REPO_ROOT}"
else
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi
cd "${REPO_ROOT}"

# Regenerate. `copy-docs.mjs` is idempotent on a fresh tree (copy + prune).
# Run with `cd ui &&` so node resolves the script relative to that root —
# matches the canonical local-fix-command shape printed below.
( cd ui && node scripts/copy-docs.mjs )

# `git status --porcelain` reports modified, deleted, AND untracked files
# under the path. `git diff --exit-code` only catches modified/deleted —
# untracked-file regressions are the AC-9 case.
DRIFT="$(git status --porcelain -- ui/public/docs/)"

if [[ -n "${DRIFT}" ]]; then
  echo "ERROR: ui/public/docs/ is stale." >&2
  echo "Fix with the canonical chained regen (Story 2.4):" >&2
  echo "  bash scripts/regen-generated-artifacts.sh" >&2
  echo "(or this gate alone:" >&2
  echo "  cd ui && node scripts/copy-docs.mjs && git add public/docs)" >&2
  echo >&2
  echo "Drift detected (diagnostic):" >&2
  printf '%s\n' "${DRIFT}" >&2
  exit 1
fi

echo "OK: ui/public/docs/ is fresh."
