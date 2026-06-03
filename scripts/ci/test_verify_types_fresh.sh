#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Self-test for `scripts/ci/verify_types_fresh.sh`
# (Story 2.3 of `infra_generated_artifact_freshness_gate`).
#
# Builds a disposable git fixture in a tmp directory containing a
# pre-committed `ui/src/lib/types.ts` (test bytes, NOT the real
# generated types) and exercises three cases via the guard's
# `TYPES_FRESH_REGEN_SCRIPT` path-override:
#
#   1. Clean tree           → override re-writes the same bytes, tree
#                             stays clean, guard exits 0
#   2. Source-drift         → override writes DIFFERENT bytes
#                             (simulating a snapshot change that
#                             produces different generated types),
#                             tree goes dirty, guard exits 1 with the
#                             canonical chained fix-command text
#   3. Untracked AC-9 case  → `git rm --cached` types.ts, override
#                             writes the same bytes, guard reports `??`
#                             and exits 1
#
# Using a script-path override avoids needing `pnpm` + `node_modules` +
# the project venv in the fixture — the banner has its own Story-2.3
# vitest; this self-test verifies the guard's diff-detection logic only.
#
# Run locally:  bash scripts/ci/test_verify_types_fresh.sh
# Run in CI:    invoked by the `generated-artifacts-fresh` job.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/scripts/ci/verify_types_fresh.sh"

PASS=0
FAIL=0

if [[ ! -r "${GUARD}" ]]; then
  echo "FATAL: cannot find guard at ${GUARD}" >&2
  exit 2
fi

CANONICAL_BYTES='// generated types — fixture v1'
DRIFTED_BYTES='// generated types — fixture v2-DRIFTED'

build_fixture() {
  local fixture="$1"
  mkdir -p "${fixture}/ui/src/lib"
  printf '%s\n' "${CANONICAL_BYTES}" > "${fixture}/ui/src/lib/types.ts"
  (
    cd "${fixture}"
    git init -q -b main
    git config user.email "selftest@local"
    git config user.name "self-test"
    git add ui/src/lib/types.ts
    git commit -q -m "init"
  )
}

write_regen_script() {
  local fixture="$1"
  local bytes="$2"
  local script="${fixture}/regen.sh"
  cat > "${script}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
mkdir -p ui/src/lib
printf '%s\\n' '${bytes}' > ui/src/lib/types.ts
EOF
  chmod +x "${script}"
  printf '%s\n' "${script}"
}

run_guard() {
  local fixture="$1"
  local regen_script="$2"
  local logfile="$3"
  (
    cd "${fixture}"
    TYPES_FRESH_REPO_ROOT="${fixture}" \
    TYPES_FRESH_REGEN_SCRIPT="${regen_script}" \
    bash "${GUARD}"
  ) >"${logfile}" 2>&1
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local name="$3"
  if [[ "${actual}" -eq "${expected}" ]]; then
    echo "  ok   ${name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL ${name} (expected exit ${expected}, got ${actual})"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local needle="$1"
  local file="$2"
  local name="$3"
  if grep -qF -- "${needle}" "${file}"; then
    echo "  ok   ${name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL ${name} (did not find '${needle}' in ${file})"
    FAIL=$((FAIL + 1))
  fi
}

trap 'rm -rf "${TMP1:-}" "${TMP2:-}" "${TMP3:-}"' EXIT

# --- Case 1: clean tree ---------------------------------------------------
echo "Case 1: clean tree"
TMP1="$(mktemp -d -t rl-types-fresh-1.XXXXXX)"
build_fixture "${TMP1}"
LOG1="${TMP1}.log"
CLEAN_SCRIPT="$(write_regen_script "${TMP1}" "${CANONICAL_BYTES}")"
actual=0
run_guard "${TMP1}" "${CLEAN_SCRIPT}" "${LOG1}" || actual=$?
assert_eq 0 "${actual}" "clean tree → exit 0"
assert_contains "OK: ui/src/lib/types.ts is fresh." "${LOG1}" "clean tree → success message"

# --- Case 2: source-drift -------------------------------------------------
echo "Case 2: source-drift"
TMP2="$(mktemp -d -t rl-types-fresh-2.XXXXXX)"
build_fixture "${TMP2}"
LOG2="${TMP2}.log"
DRIFT_SCRIPT="$(write_regen_script "${TMP2}" "${DRIFTED_BYTES}")"
actual=0
run_guard "${TMP2}" "${DRIFT_SCRIPT}" "${LOG2}" || actual=$?
assert_eq 1 "${actual}" "source-drift → exit 1"
assert_contains "ui/src/lib/types.ts is stale." "${LOG2}" "source-drift → error header"
assert_contains "scripts/regen-generated-artifacts.sh" \
  "${LOG2}" "source-drift → chained fix-command text"

# --- Case 3: untracked AC-9 ----------------------------------------------
echo "Case 3: untracked types.ts (git rm --cached)"
TMP3="$(mktemp -d -t rl-types-fresh-3.XXXXXX)"
build_fixture "${TMP3}"
( cd "${TMP3}" && git rm --cached -q ui/src/lib/types.ts )
LOG3="${TMP3}.log"
UNTRACKED_SCRIPT="$(write_regen_script "${TMP3}" "${CANONICAL_BYTES}")"
actual=0
run_guard "${TMP3}" "${UNTRACKED_SCRIPT}" "${LOG3}" || actual=$?
assert_eq 1 "${actual}" "untracked AC-9 → exit 1"
assert_contains "?? ui/src/lib/types.ts" "${LOG3}" \
  "untracked AC-9 → git status reports ?? marker"

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
