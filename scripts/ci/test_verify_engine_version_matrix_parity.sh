#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/ci/verify_engine_version_matrix_parity.sh.
#
# feat_engine_version_selection Story 1.5.
#
# Asserts the guard:
#   - exits 0 against a clean (synced) tree
#   - exits 1 with the MATRIX-COMPOSE DRIFT message when the Compose `:-`
#     default is mutated away from ENGINE_VERSION_MATRIX[<engine>][0]
#   - exits 1 with the BASH-MIRROR DRIFT message when the bash mirror
#     diverges from the Python source
#
# Pattern: mktemp-d scratch tree with copies of the three load-bearing
# files (docker-compose.yml, scripts/lib/relyloop_engine_versions_matrix.sh,
# backend/app/core/engine_versions.py); mutate one per case; run the guard
# against the scratch tree. Never mutates the real repo tree.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/scripts/ci/verify_engine_version_matrix_parity.sh"

PASS=0
FAIL=0

# Build a scratch tree that mirrors the real repo's three load-bearing
# files. Returns the scratch root via stdout. Caller is responsible for
# cleanup (or relies on the trap below).
make_scratch_tree() {
  local scratch
  scratch="$(mktemp -d)"
  mkdir -p \
    "${scratch}/scripts/ci" \
    "${scratch}/scripts/lib" \
    "${scratch}/backend/app/core" \
    "${scratch}/ui/src/lib"
  cp "${REPO_ROOT}/docker-compose.yml" "${scratch}/docker-compose.yml"
  cp "${REPO_ROOT}/scripts/lib/relyloop_engine_versions_matrix.sh" \
     "${scratch}/scripts/lib/relyloop_engine_versions_matrix.sh"
  cp "${REPO_ROOT}/backend/app/core/engine_versions.py" \
     "${scratch}/backend/app/core/engine_versions.py"
  cp "${REPO_ROOT}/ui/src/lib/enums.ts" \
     "${scratch}/ui/src/lib/enums.ts"
  # Pre-create the backend.app.core import path so the guard's
  # `from backend.app.core.engine_versions import …` resolves.
  touch \
    "${scratch}/backend/__init__.py" \
    "${scratch}/backend/app/__init__.py" \
    "${scratch}/backend/app/core/__init__.py"
  printf '%s' "$scratch"
}

# Run the guard against a scratch tree. Returns rc + captures stderr.
# Sets the global $LAST_RC and $LAST_STDERR.
run_guard() {
  local scratch="$1"
  local stderr_path
  stderr_path="$(mktemp)"
  local rc
  rc=0
  # Copy the guard into the scratch tree so its REPO_ROOT derivation
  # (cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) yields the scratch
  # root, not the real repo root.
  cp "${GUARD}" "${scratch}/scripts/ci/verify_engine_version_matrix_parity.sh"
  bash "${scratch}/scripts/ci/verify_engine_version_matrix_parity.sh" \
    >/dev/null 2>"${stderr_path}" || rc=$?
  LAST_RC="$rc"
  LAST_STDERR="$(cat "${stderr_path}")"
  rm -f "${stderr_path}"
}

# expect_ok <case_name>
expect_ok() {
  local name="$1"
  if [[ "$LAST_RC" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${LAST_RC}"
    echo "    stderr: $LAST_STDERR"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
}

# expect_fail <case_name> <stderr_substring>
expect_fail() {
  local name="$1"
  local expected_stderr="$2"
  if [[ "$LAST_RC" -eq 0 ]]; then
    echo "  FAIL ${name}: expected non-zero rc, got 0"
    FAIL=$((FAIL + 1))
    return
  fi
  if ! echo "$LAST_STDERR" | grep -qF -- "$expected_stderr"; then
    echo "  FAIL ${name}: stderr missing expected substring"
    echo "    expected: $expected_stderr"
    echo "    actual:   $(echo "$LAST_STDERR" | tr '\n' ' ')"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
}

echo "verify_engine_version_matrix_parity regression cases:"

# Case 1: clean tree → guard exits 0.
SCRATCH_CLEAN="$(make_scratch_tree)"
trap 'rm -rf "${SCRATCH_CLEAN:-}" "${SCRATCH_COMPOSE_DRIFT:-}" "${SCRATCH_BASH_DRIFT:-}" "${SCRATCH_FRONTEND_DRIFT:-}"' EXIT
run_guard "${SCRATCH_CLEAN}"
expect_ok "clean synced tree"

# Case 2: inject Compose-default drift. Bump the matrix's elasticsearch[0]
# from 9.4.1 → 9.5.0 (but keep docker-compose.yml at 9.4.1) and expect the
# Part (a) drift message.
SCRATCH_COMPOSE_DRIFT="$(make_scratch_tree)"
# Use python to do the rewrite reliably (perl/sed have escaping pitfalls).
python3 - "${SCRATCH_COMPOSE_DRIFT}/backend/app/core/engine_versions.py" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
# Replace the elasticsearch tuple's first element.
new = text.replace('"elasticsearch": ("9.4.1", "8.15.3")',
                   '"elasticsearch": ("9.5.0", "8.15.3")')
assert new != text, "rewrite did not match — test data drifted"
p.write_text(new)
EOF
run_guard "${SCRATCH_COMPOSE_DRIFT}"
expect_fail "compose-default drift detected" \
  "MATRIX-COMPOSE DRIFT: engine 'elasticsearch' matrix[0]='9.5.0'"

# Case 3: inject bash-mirror drift. Bump the bash mirror's
# ES_VERSIONS to a value that doesn't match Python, expect the Part (b)
# drift message.
SCRATCH_BASH_DRIFT="$(make_scratch_tree)"
python3 - "${SCRATCH_BASH_DRIFT}/scripts/lib/relyloop_engine_versions_matrix.sh" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
new = text.replace('ES_VERSIONS="9.4.1 8.15.3"',
                   'ES_VERSIONS="9.4.1 8.15.2"')
assert new != text, "rewrite did not match — test data drifted"
p.write_text(new)
EOF
run_guard "${SCRATCH_BASH_DRIFT}"
expect_fail "bash-mirror drift detected" \
  "BASH-MIRROR DRIFT: engine 'elasticsearch'"

# Case 4: inject frontend-mirror drift. Mutate the TS mirror's
# elasticsearch entry to a value Python doesn't list, expect the Part (c)
# drift message.
SCRATCH_FRONTEND_DRIFT="$(make_scratch_tree)"
python3 - "${SCRATCH_FRONTEND_DRIFT}/ui/src/lib/enums.ts" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text()
new = text.replace("elasticsearch: ['9.4.1', '8.15.3']",
                   "elasticsearch: ['9.4.1', '8.15.2']")
assert new != text, "rewrite did not match — test data drifted"
p.write_text(new)
EOF
run_guard "${SCRATCH_FRONTEND_DRIFT}"
expect_fail "frontend-mirror drift detected" \
  "MIRROR-FRONTEND DRIFT: engine 'elasticsearch'"

echo
if [[ "$FAIL" -gt 0 ]]; then
  echo "FAIL: ${FAIL} case(s) failed (${PASS} passed)"
  exit 1
fi
echo "ok: ${PASS} cases passed"
