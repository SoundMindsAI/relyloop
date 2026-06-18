#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# feat_engine_version_selection Story 1.5.
#
# Three-part regression gate covering the matrix's sync points:
#
# Part (a): Python ENGINE_VERSION_MATRIX[<engine>][0] vs. docker-compose.yml
#   `${X_IMAGE_TAG:-<default>}` literal.
#   The matrix's first tuple element for each engine MUST equal the
#   Compose `:-` default in the corresponding `image:` line, so an
#   operator who sets RELYLOOP_ES_VERSION=<matrix[0]> sees no change vs.
#   no env var at all (same image bytes).
#
# Part (b): Python ENGINE_VERSION_MATRIX vs. scripts/lib/relyloop_engine_versions_matrix.sh
#   The bash mirror is consumed by `parse_relyloop_engine_versions` to
#   validate operator input. If it diverges from the Python source, the
#   install.sh helper would accept a value the unit tests claim is
#   invalid (or vice versa).
#
# Part (c): Python ENGINE_VERSION_MATRIX vs. ui/src/lib/enums.ts
#   ENGINE_VERSION_MATRIX TypeScript mirror.
#   The frontend mirror is the source-of-truth for any UI that wants to
#   render version choices. The existing verify_enum_source_of_truth.sh
#   guard handles flat `as const` arrays — this matrix is a dict-shaped
#   `as const`, so its parity check lives here alongside Parts (a) + (b).
#
# Reads the Python source via `python3 -c ...` (no extra deps required —
# this guard is run in the static-checks-backend job which has uv +
# Python set up).
#
# Bash 3.2-safe: uses parallel indexed arrays instead of associative
# arrays (`declare -A` is bash 4+; macOS ships 3.2 by default). To add
# a new engine, extend ENGINES + COMPOSE_PATTERNS + BASH_VAR_NAMES in
# lockstep; indices must match.
#
# Run locally: bash scripts/ci/verify_engine_version_matrix_parity.sh
# Run in CI:   invoked by .github/workflows/pr.yml's static-checks-backend job.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"
BASH_MIRROR="${REPO_ROOT}/scripts/lib/relyloop_engine_versions_matrix.sh"
PYTHON_MATRIX="${REPO_ROOT}/backend/app/core/engine_versions.py"
FRONTEND_MIRROR="${REPO_ROOT}/ui/src/lib/enums.ts"

for f in "${COMPOSE_FILE}" "${BASH_MIRROR}" "${PYTHON_MATRIX}" "${FRONTEND_MIRROR}"; do
  if [[ ! -f "$f" ]]; then
    echo "verify_engine_version_matrix_parity: missing required file: $f" >&2
    exit 2
  fi
done

# Parallel indexed arrays. Indices 0..2 must align across all three.
ENGINES=("elasticsearch" "opensearch" "solr")
# Compose `image:` regex literal preceding `${X_IMAGE_TAG:-<default>}`.
COMPOSE_PATTERNS=(
  'elasticsearch:${ES_IMAGE_TAG:-'
  'opensearchproject/opensearch:${OS_IMAGE_TAG:-'
  'solr:${SOLR_IMAGE_TAG:-'
)
# Bash mirror variable names.
BASH_VAR_NAMES=("ES_VERSIONS" "OS_VERSIONS" "SOLR_VERSIONS")

# ----------------------------------------------------------------------
# Part (a): matrix[0] ↔ docker-compose.yml `:-` default sync.
# ----------------------------------------------------------------------

# Pull matrix[0] for each engine from Python, one value per line, in
# the ENGINES order above:
#   elasticsearch 9.4.1
#   opensearch    3.6.0
#   solr          10.0
PYTHON_DEFAULTS=$(cd "${REPO_ROOT}" && PYTHONPATH="${REPO_ROOT}" python3 -c '
from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX
for engine, versions in ENGINE_VERSION_MATRIX.items():
    print(f"{engine} {versions[0]}")
')

# Build a parallel array of defaults in ENGINES order. The lookup tolerates
# Python emitting in a different order than ENGINES (Python dict iteration
# order matches insertion order, but the contract is the matrix-key set
# match, not order).
PYTHON_DEFAULT_VALUES=()
for engine in "${ENGINES[@]}"; do
  default=""
  while read -r py_engine py_default; do
    if [[ "$py_engine" == "$engine" ]]; then
      default="$py_default"
      break
    fi
  done <<<"$PYTHON_DEFAULTS"
  PYTHON_DEFAULT_VALUES+=("$default")
done

drift_a=0
for i in "${!ENGINES[@]}"; do
  engine="${ENGINES[$i]}"
  default="${PYTHON_DEFAULT_VALUES[$i]}"
  pattern="${COMPOSE_PATTERNS[$i]}"
  if [[ -z "$default" ]]; then
    echo "MATRIX-COMPOSE DRIFT: engine '$engine' has no entry in ENGINE_VERSION_MATRIX." >&2
    drift_a=1
    continue
  fi
  full_pattern="${pattern}${default}}"
  if ! grep -qF -- "$full_pattern" "${COMPOSE_FILE}"; then
    echo "MATRIX-COMPOSE DRIFT: engine '$engine' matrix[0]='$default' but docker-compose.yml does not contain '$full_pattern'." >&2
    drift_a=1
  fi
done

if [[ "$drift_a" -ne 0 ]]; then
  echo "" >&2
  echo "Fix: update either backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX[<engine>][0]" >&2
  echo "or docker-compose.yml's matching image: line so they agree." >&2
  exit 1
fi

# ----------------------------------------------------------------------
# Part (b): Python matrix ↔ bash mirror sync.
# ----------------------------------------------------------------------

# Read the bash mirror in a subshell so its variables don't leak.
BASH_VALUES_LINE=$(set +u; source "${BASH_MIRROR}" && printf '%s|%s|%s\n' \
  "${ES_VERSIONS:-}" "${OS_VERSIONS:-}" "${SOLR_VERSIONS:-}")
IFS='|' read -r bash_es bash_os bash_solr <<<"$BASH_VALUES_LINE"
BASH_VERSION_VALUES=("$bash_es" "$bash_os" "$bash_solr")

# Pull the full Python matrix as space-separated values, in ENGINES order.
PYTHON_FULL=$(cd "${REPO_ROOT}" && PYTHONPATH="${REPO_ROOT}" python3 -c '
from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX
for engine, versions in ENGINE_VERSION_MATRIX.items():
    print(engine, *versions)
')

PYTHON_VERSION_VALUES=()
for engine in "${ENGINES[@]}"; do
  py_str=""
  while read -r py_engine rest; do
    if [[ "$py_engine" == "$engine" ]]; then
      py_str="$rest"
      break
    fi
  done <<<"$PYTHON_FULL"
  PYTHON_VERSION_VALUES+=("$py_str")
done

drift_b=0
for i in "${!ENGINES[@]}"; do
  engine="${ENGINES[$i]}"
  py_str="${PYTHON_VERSION_VALUES[$i]}"
  bash_str="${BASH_VERSION_VALUES[$i]}"
  if [[ "$py_str" != "$bash_str" ]]; then
    echo "BASH-MIRROR DRIFT: engine '$engine' python=[$py_str] bash=[$bash_str]." >&2
    drift_b=1
  fi
done

if [[ "$drift_b" -ne 0 ]]; then
  echo "" >&2
  echo "Fix: update scripts/lib/relyloop_engine_versions_matrix.sh to match" >&2
  echo "backend/app/core/engine_versions.py (the source of truth)." >&2
  exit 1
fi

# ----------------------------------------------------------------------
# Part (c): Python matrix ↔ ui/src/lib/enums.ts ENGINE_VERSION_MATRIX.
# ----------------------------------------------------------------------

# Extract the frontend mirror via a small Python parser. The ts const is
# small and well-shaped enough that we can regex it out without a real
# TS parser (same approach as verify_enum_source_of_truth.sh's flat-array
# parser, just dict-shaped).
#
# Quoted heredoc delimiter ('EOF') disables bash interpretation of the
# Python body — needed because the f-string at the bottom contains
# `${' '.join(es)}` style nested braces that bash would otherwise try
# to parse as variable expansions.
FRONTEND_VALUES_LINE=$(cd "${REPO_ROOT}" && PYTHONPATH="${REPO_ROOT}" python3 - "${FRONTEND_MIRROR}" <<'EOF'
import re, sys
mirror_path = sys.argv[1]
# Explicit utf-8 — prevents UnicodeDecodeError on non-UTF-8 default locales
# (minimal Docker containers, Windows). Gemini review #2.
text = open(mirror_path, encoding="utf-8").read()
m = re.search(
    r'export\s+const\s+ENGINE_VERSION_MATRIX\s*=\s*\{(.*?)\}\s*as\s+const\s*;',
    text,
    re.DOTALL,
)
if not m:
    sys.stderr.write(f"ENGINE_VERSION_MATRIX mirror not found in {mirror_path}\n")
    sys.exit(2)
body = m.group(1)
# Per-engine extraction: KEY: [ "v1", "v2" ],
def extract(key: str) -> list[str]:
    em = re.search(rf"{key}\s*:\s*\[(.*?)\]", body, re.DOTALL)
    if not em:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", em.group(1))
es = extract("elasticsearch")
os_v = extract("opensearch")
solr = extract("solr")
print(f"{' '.join(es)}|{' '.join(os_v)}|{' '.join(solr)}")
EOF
) || {
  echo "MIRROR-FRONTEND DRIFT: failed to parse ENGINE_VERSION_MATRIX from ${FRONTEND_MIRROR}." >&2
  echo "" >&2
  echo "Fix: ensure ui/src/lib/enums.ts has an 'export const ENGINE_VERSION_MATRIX = { … } as const;'" >&2
  echo "block with elasticsearch/opensearch/solr keys mirroring the Python source." >&2
  exit 1
}

IFS='|' read -r front_es front_os front_solr <<<"$FRONTEND_VALUES_LINE"
FRONTEND_VERSION_VALUES=("$front_es" "$front_os" "$front_solr")

drift_c=0
for i in "${!ENGINES[@]}"; do
  engine="${ENGINES[$i]}"
  py_str="${PYTHON_VERSION_VALUES[$i]}"
  front_str="${FRONTEND_VERSION_VALUES[$i]}"
  if [[ "$py_str" != "$front_str" ]]; then
    echo "MIRROR-FRONTEND DRIFT: engine '$engine' python=[$py_str] frontend=[$front_str]." >&2
    drift_c=1
  fi
done

if [[ "$drift_c" -ne 0 ]]; then
  echo "" >&2
  echo "Fix: update ui/src/lib/enums.ts ENGINE_VERSION_MATRIX to match" >&2
  echo "backend/app/core/engine_versions.py (the source of truth)." >&2
  exit 1
fi

echo "OK — ENGINE_VERSION_MATRIX in sync with Compose defaults, bash mirror, and frontend mirror."
