#!/usr/bin/env bash
# feat_home_first_run_demo_nudge — Story 4.2.
#
# Verifies the 4 demo cluster slugs in the frontend constant
# (ui/src/lib/demo-data.ts DEMO_CLUSTER_SLUGS) match the 4 "slug":
# literals in the canonical seed script (scripts/seed_meaningful_demos.py
# SCENARIOS). Modeled on verify_enum_source_of_truth.sh — same exit-code
# contract (0 clean / 1 drift / 2 setup error).
#
# A 5th demo (or a renamed slug) on either side without an updated
# counterpart fails CI. The error message names both files.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FE_FILE="${REPO_ROOT}/ui/src/lib/demo-data.ts"
PY_FILE="${REPO_ROOT}/scripts/seed_meaningful_demos.py"

if [[ ! -f "${FE_FILE}" ]]; then
  echo "verify_demo_slug_parity: frontend file not found: ${FE_FILE}" >&2
  exit 2
fi
if [[ ! -f "${PY_FILE}" ]]; then
  echo "verify_demo_slug_parity: python file not found: ${PY_FILE}" >&2
  exit 2
fi

# Extract frontend slugs: lines between `DEMO_CLUSTER_SLUGS = [` and
# `] as const;`, each containing a single 'slug'. Accept BOTH single and
# double quotes — prettier or a manual edit could legitimately switch
# style without breaking the contract.
fe_slugs=$(awk '/^export const DEMO_CLUSTER_SLUGS = \[/,/\] as const;/' "${FE_FILE}" \
  | grep -oE "['\"][a-z0-9-]+['\"]" \
  | tr -d "'\"" \
  | sort)

# Extract python slugs: lines like `"slug": "acme-products-prod",`
py_slugs=$(grep -oE '"slug":[[:space:]]*"[a-z0-9-]+"' "${PY_FILE}" \
  | grep -oE '"[a-z0-9-]+"$' \
  | tr -d '"' \
  | sort)

if [[ -z "${fe_slugs}" ]]; then
  echo "verify_demo_slug_parity: failed to parse frontend slugs from ${FE_FILE}" >&2
  echo "  expected pattern: 'export const DEMO_CLUSTER_SLUGS = [...] as const;'" >&2
  exit 2
fi
if [[ -z "${py_slugs}" ]]; then
  echo "verify_demo_slug_parity: failed to parse python slugs from ${PY_FILE}" >&2
  echo '  expected pattern: \"slug\": \"<slug>\",' >&2
  exit 2
fi

if [[ "${fe_slugs}" != "${py_slugs}" ]]; then
  echo "verify_demo_slug_parity: DRIFT between frontend constant and seed script" >&2
  echo "" >&2
  echo "  Frontend (${FE_FILE}):" >&2
  echo "${fe_slugs}" | sed 's/^/    - /' >&2
  echo "" >&2
  echo "  Python   (${PY_FILE}):" >&2
  echo "${py_slugs}" | sed 's/^/    - /' >&2
  echo "" >&2
  echo "  Fix: update both files to match, OR (if intentional) update both" >&2
  echo "       AND the demo-data.ts source-of-truth comment cite." >&2
  exit 1
fi

count=$(echo "${fe_slugs}" | wc -l | tr -d ' ')
echo "verify_demo_slug_parity: ${count} demo slugs verified — clean"
