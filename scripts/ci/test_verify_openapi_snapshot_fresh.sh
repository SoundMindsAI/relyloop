#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Self-test for `scripts/ci/verify_openapi_snapshot_fresh.sh`
# (Story 2.2 of `infra_generated_artifact_freshness_gate`).
#
# Builds a disposable git fixture in a tmp directory containing a
# pre-committed `ui/openapi.json` (test bytes, NOT the real schema)
# and exercises three cases via the guard's
# `OPENAPI_SNAPSHOT_REGEN_CMD` override:
#
#   1. Clean tree           → override re-writes the same bytes, tree
#                             stays clean, guard exits 0
#   2. Source-drift         → override writes DIFFERENT bytes, tree
#                             goes dirty, guard exits 1 with the
#                             canonical fix-command text
#   3. Untracked AC-9 case  → `git rm --cached` the snapshot (file
#                             stays on disk but leaves the index),
#                             override writes the same bytes,
#                             guard reports `??` and exits 1
#
# The override is a script PATH (not a shell command string) so we
# don't have to navigate `read -ra` word-splitting on a regen command
# that itself uses quoted args. Each test seeds a tiny fixture-local
# `regen.sh` and points `OPENAPI_SNAPSHOT_REGEN_SCRIPT` at it.
#
# Using a script-path override avoids needing `uv` + the project venv
# in the fixture — the exporter has its own Story-2.1 unit test; this
# self-test verifies the guard's diff-detection logic, not the exporter.
#
# Run locally:  bash scripts/ci/test_verify_openapi_snapshot_fresh.sh
# Run in CI:    invoked by the `generated-artifacts-fresh` job.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/scripts/ci/verify_openapi_snapshot_fresh.sh"

PASS=0
FAIL=0

if [[ ! -r "${GUARD}" ]]; then
  echo "FATAL: cannot find guard at ${GUARD}" >&2
  exit 2
fi

# Deterministic test bytes — NOT the real schema. The guard's job is
# diff-detection; it doesn't care what the bytes mean. Keeping these
# small + obviously-fake makes the test self-explanatory.
CANONICAL_BYTES='{"openapi":"3.1.0","paths":{}}'
DRIFTED_BYTES='{"openapi":"3.1.0","paths":{"/drifted":{}}}'

build_fixture() {
  local fixture="$1"
  mkdir -p "${fixture}/ui"
  printf '%s\n' "${CANONICAL_BYTES}" > "${fixture}/ui/openapi.json"
  (
    cd "${fixture}"
    git init -q -b main
    git config user.email "selftest@local"
    git config user.name "self-test"
    git add ui/openapi.json
    git commit -q -m "init"
  )
}

# Write a tiny regen-stub script into $1/regen.sh that writes $2 (raw
# bytes) to ui/openapi.json on each invocation. Returns the script path.
write_regen_script() {
  local fixture="$1"
  local bytes="$2"
  local script="${fixture}/regen.sh"
  cat > "${script}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' '${bytes}' > ui/openapi.json
EOF
  chmod +x "${script}"
  printf '%s\n' "${script}"
}

# Run the guard against $1 (a fixture) with regen-script path $2,
# capturing stdout+stderr to $3.
run_guard() {
  local fixture="$1"
  local regen_script="$2"
  local logfile="$3"
  (
    cd "${fixture}"
    OPENAPI_SNAPSHOT_FRESH_REPO_ROOT="${fixture}" \
    OPENAPI_SNAPSHOT_REGEN_SCRIPT="${regen_script}" \
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

# Each test gets its own fixture so failures don't contaminate later cases.
trap 'rm -rf "${TMP1:-}" "${TMP2:-}" "${TMP3:-}"' EXIT

# --- Case 1: clean tree → guard exits 0 ----------------------------------
echo "Case 1: clean tree"
TMP1="$(mktemp -d -t rl-openapi-snapshot-fresh-1.XXXXXX)"
build_fixture "${TMP1}"
LOG1="${TMP1}.log"
# Regen writes the SAME bytes that are already committed → no drift.
CLEAN_REGEN_SCRIPT="$(write_regen_script "${TMP1}" "${CANONICAL_BYTES}")"
actual=0
run_guard "${TMP1}" "${CLEAN_REGEN_SCRIPT}" "${LOG1}" || actual=$?
assert_eq 0 "${actual}" "clean tree → exit 0"
assert_contains "OK: ui/openapi.json is fresh." "${LOG1}" "clean tree → success message"

# --- Case 2: source-drift → guard exits 1 + fix-command text -------------
echo "Case 2: source-drift (regen produces different bytes)"
TMP2="$(mktemp -d -t rl-openapi-snapshot-fresh-2.XXXXXX)"
build_fixture "${TMP2}"
LOG2="${TMP2}.log"
DRIFT_REGEN_SCRIPT="$(write_regen_script "${TMP2}" "${DRIFTED_BYTES}")"
actual=0
run_guard "${TMP2}" "${DRIFT_REGEN_SCRIPT}" "${LOG2}" || actual=$?
assert_eq 1 "${actual}" "source-drift → exit 1"
assert_contains "ui/openapi.json is stale." "${LOG2}" "source-drift → error header"
assert_contains "uv run python -m backend.app.openapi_export --out ui/openapi.json && git add ui/openapi.json" \
  "${LOG2}" "source-drift → canonical fix-command text"

# --- Case 3: untracked AC-9 → guard exits 1 with `??` marker -------------
echo "Case 3: untracked snapshot (git rm --cached leaves file on disk)"
TMP3="$(mktemp -d -t rl-openapi-snapshot-fresh-3.XXXXXX)"
build_fixture "${TMP3}"
( cd "${TMP3}" && git rm --cached -q ui/openapi.json )
LOG3="${TMP3}.log"
actual=0
# Regen writes the same bytes back; the file just isn't tracked anymore.
UNTRACKED_REGEN_SCRIPT="$(write_regen_script "${TMP3}" "${CANONICAL_BYTES}")"
run_guard "${TMP3}" "${UNTRACKED_REGEN_SCRIPT}" "${LOG3}" || actual=$?
assert_eq 1 "${actual}" "untracked AC-9 → exit 1"
assert_contains "?? ui/openapi.json" "${LOG3}" \
  "untracked AC-9 → git status reports ?? marker"

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
