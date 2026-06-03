#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Self-test for `scripts/ci/verify_copy_docs_fresh.sh`
# (Story 1.2 of `infra_generated_artifact_freshness_gate`).
#
# Builds a disposable git fixture in a tmp directory containing the real
# `ui/scripts/copy-docs.mjs` + the guard + a minimal source guide + the
# matching generated output (committed once at fixture-init so a clean run
# is a no-op), then exercises three cases:
#
#   1. Clean tree           → guard exits 0
#   2. Source-drift         → edit a source guide, the guard's regen
#                             rewrites the public copy, `git status`
#                             reports `M`, guard exits 1, stdout/stderr
#                             contains the canonical fix command
#   3. Untracked AC-9 case  → `git rm --cached` a public copy (the file
#                             stays on disk but leaves the index), guard
#                             reports `??`, exits 1
#
# Each case runs in a fresh fixture so the failure of one case never
# contaminates the next. The fixture uses git init / commit on disposable
# state — no operation touches the operator's primary checkout.
#
# Run locally:  bash scripts/ci/test_verify_copy_docs_fresh.sh
# Run in CI:    invoked by the `copy-docs-freshness` workflow.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/scripts/ci/verify_copy_docs_fresh.sh"
COPY_DOCS="${REPO_ROOT}/ui/scripts/copy-docs.mjs"

PASS=0
FAIL=0

if [[ ! -x "${GUARD}" && ! -r "${GUARD}" ]]; then
  echo "FATAL: cannot find guard at ${GUARD}" >&2
  exit 2
fi

# Build a self-contained, committed fixture in $1. The fixture seeds:
#   - docs/08_guides/quick-tour.md   (the only "DOCS" source the test exercises)
#   - ui/scripts/copy-docs.mjs       (real script, copied in)
#   - ui/public/docs/*               (committed after one no-op script run,
#                                     so a fresh re-run is clean)
# The other two DOCS entries (`tutorial-first-study.md`,
# `workflows-overview.md`) are intentionally absent in `docs/08_guides/`,
# so the script logs a WARNING for each and skips them — both `copied` and
# the prune set agree, leaving the working tree clean.
build_fixture() {
  local fixture="$1"
  mkdir -p "${fixture}/ui/scripts" "${fixture}/ui/public/docs"
  mkdir -p "${fixture}/docs/08_guides"

  cp "${COPY_DOCS}" "${fixture}/ui/scripts/copy-docs.mjs"
  echo "# quick-tour fixture body" > "${fixture}/docs/08_guides/quick-tour.md"

  # Seed the public copy by running the script once. The script writes
  # README.md + copies the one available guide; prune is a no-op because
  # the dir starts empty.
  ( cd "${fixture}/ui" && node scripts/copy-docs.mjs >/dev/null )

  # Commit the seed so subsequent `git status` baselines on this state.
  (
    cd "${fixture}"
    git init -q -b main
    git config user.email "selftest@local"
    git config user.name "self-test"
    git add .
    git commit -q -m "init"
  )
}

# Run the guard against $1 (a fixture path), capturing stdout+stderr to $2.
# Returns the guard's exit code via $? (caller checks).
run_guard() {
  local fixture="$1"
  local logfile="$2"
  ( cd "${fixture}" && \
    COPY_DOCS_FRESH_REPO_ROOT="${fixture}" \
    bash "${GUARD}" ) >"${logfile}" 2>&1
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

# --- Case 1: clean tree → guard exits 0 ----------------------------------
echo "Case 1: clean tree"
TMP1="$(mktemp -d -t rl-copy-docs-fresh-1.XXXXXX)"
trap 'rm -rf "${TMP1}" "${TMP2:-}" "${TMP3:-}"' EXIT
build_fixture "${TMP1}"
LOG1="${TMP1}.log"
actual=0
run_guard "${TMP1}" "${LOG1}" || actual=$?
assert_eq 0 "${actual}" "clean tree → exit 0"
assert_contains "OK: ui/public/docs/ is fresh." "${LOG1}" "clean tree → success message"

# --- Case 2: source-drift → guard exits 1 + fix-command text -------------
echo "Case 2: source-drift (edit source guide, leave public copy unchanged)"
TMP2="$(mktemp -d -t rl-copy-docs-fresh-2.XXXXXX)"
build_fixture "${TMP2}"
echo "# quick-tour DRIFTED" > "${TMP2}/docs/08_guides/quick-tour.md"
LOG2="${TMP2}.log"
actual=0
run_guard "${TMP2}" "${LOG2}" || actual=$?
assert_eq 1 "${actual}" "source-drift → exit 1"
assert_contains "ui/public/docs/ is stale." "${LOG2}" "source-drift → error header"
assert_contains "cd ui && node scripts/copy-docs.mjs && git add public/docs" "${LOG2}" \
  "source-drift → canonical fix-command text"

# --- Case 3: untracked AC-9 → guard exits 1 with `??` marker -------------
echo "Case 3: untracked public copy (git rm --cached leaves file on disk)"
TMP3="$(mktemp -d -t rl-copy-docs-fresh-3.XXXXXX)"
build_fixture "${TMP3}"
# `git rm --cached` removes the file from the index but keeps it on disk.
# After `copy-docs.mjs` re-runs, the file content matches the source so
# it isn't modified — it's just untracked (`??`).
( cd "${TMP3}" && git rm --cached -q ui/public/docs/quick-tour.md )
LOG3="${TMP3}.log"
actual=0
run_guard "${TMP3}" "${LOG3}" || actual=$?
assert_eq 1 "${actual}" "untracked AC-9 → exit 1"
# The diagnostic block emits `git status --porcelain` lines. An untracked
# file is reported as `?? <path>`; assert the marker is present.
assert_contains "?? ui/public/docs/quick-tour.md" "${LOG3}" \
  "untracked AC-9 → git status reports ?? marker"

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
