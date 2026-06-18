#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/lib/relyloop_engine_versions.sh's
# `parse_relyloop_engine_versions` function.
#
# feat_engine_version_selection Story 1.3.
#
# Asserts:
#   - all three vars unset → no *_IMAGE_TAG exports, rc=0
#   - each engine's valid values (matrix [0] and [1]) → matching
#     *_IMAGE_TAG export, rc=0
#   - empty string treated as unset (matches Phase 1 convention)
#   - unknown value → rc=1, stderr names the engine + the rejected value
#     + the allowed list, *_IMAGE_TAG NOT exported
#   - multiple unknown values short-circuit at the first (ES first)
#   - all three set to valid values → all three *_IMAGE_TAG exports
#
# Run locally:  bash scripts/ci/test_parse_relyloop_engine_versions.sh
# Run in CI:    invoked by .github/workflows/pr.yml's static-checks-backend
#               job (this story).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT

PASS=0
FAIL=0

# expect_ok_unset <case_name> <env_setup>
#   Runs parse_relyloop_engine_versions, asserts rc=0 AND no *_IMAGE_TAG
#   exports. <env_setup> is a string passed to `bash -c` BEFORE the
#   source — e.g. "unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION
#   RELYLOOP_SOLR_VERSION" or "RELYLOOP_ES_VERSION=".
expect_ok_unset() {
  local name="$1"
  local env_setup="$2"
  local actual
  local actual_rc
  actual_rc=0
  actual="$(bash -c '
    set -eo pipefail
    '"${env_setup}"'
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_engine_versions.sh"
    parse_relyloop_engine_versions >/dev/null
    printf "ES=%s|OS=%s|SOLR=%s" "${ES_IMAGE_TAG:-}" "${OS_IMAGE_TAG:-}" "${SOLR_IMAGE_TAG:-}"
  ' 2>/dev/null)" || actual_rc=$?

  if [[ "$actual_rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${actual_rc}"
    FAIL=$((FAIL + 1))
    return
  fi
  if [[ "$actual" != "ES=|OS=|SOLR=" ]]; then
    echo "  FAIL ${name}: expected no *_IMAGE_TAG exports, got '${actual}'"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
}

# expect_ok_export <case_name> <env_setup> <expected_payload>
#   Runs the helper with the env, asserts rc=0 AND the resulting
#   payload string matches. <expected_payload> is the literal
#   "ES=…|OS=…|SOLR=…" string the inner bash prints.
expect_ok_export() {
  local name="$1"
  local env_setup="$2"
  local expected="$3"
  local actual
  local actual_rc
  actual_rc=0
  actual="$(bash -c '
    set -eo pipefail
    '"${env_setup}"'
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_engine_versions.sh"
    parse_relyloop_engine_versions >/dev/null
    printf "ES=%s|OS=%s|SOLR=%s" "${ES_IMAGE_TAG:-}" "${OS_IMAGE_TAG:-}" "${SOLR_IMAGE_TAG:-}"
  ' 2>/dev/null)" || actual_rc=$?

  if [[ "$actual_rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${actual_rc}"
    FAIL=$((FAIL + 1))
    return
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "  FAIL ${name}: expected '${expected}', got '${actual}'"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
}

# expect_fail <case_name> <env_setup> <stderr_substring>
#   Asserts non-zero rc AND stderr contains the expected substring AND
#   no *_IMAGE_TAG was exported.
expect_fail() {
  local name="$1"
  local env_setup="$2"
  local expected_stderr="$3"
  local stderr_path
  stderr_path="$(mktemp)"
  local rc
  rc=0
  bash -c '
    set -o pipefail
    '"${env_setup}"'
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_engine_versions.sh"
    parse_relyloop_engine_versions >/dev/null
  ' 2>"${stderr_path}" || rc=$?

  if [[ "$rc" -eq 0 ]]; then
    echo "  FAIL ${name}: expected non-zero rc, got 0"
    FAIL=$((FAIL + 1))
    rm -f "$stderr_path"
    return
  fi
  if ! grep -qF -- "$expected_stderr" "$stderr_path"; then
    echo "  FAIL ${name}: stderr missing expected substring"
    echo "    expected: $expected_stderr"
    echo "    actual:   $(tr '\n' ' ' < "$stderr_path")"
    FAIL=$((FAIL + 1))
    rm -f "$stderr_path"
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
  rm -f "$stderr_path"
}

echo "parse_relyloop_engine_versions regression cases:"

# Default — all three unset.
expect_ok_unset "all three unset" \
  "unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION"

# Empty string treated as unset (Phase 1 convention).
expect_ok_unset "all three empty strings" \
  "RELYLOOP_ES_VERSION='' RELYLOOP_OS_VERSION='' RELYLOOP_SOLR_VERSION=''"

# ES: each valid version.
# Note: prefix-style `VAR=value cmd` only sets VAR for that one command;
# use explicit assignments with semicolons so the var persists for the
# subsequent `source` and helper call below.
expect_ok_export "es valid latest (9.4.1)" \
  "RELYLOOP_ES_VERSION=9.4.1; unset RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION" \
  "ES=9.4.1|OS=|SOLR="
expect_ok_export "es valid older major (8.15.3)" \
  "RELYLOOP_ES_VERSION=8.15.3; unset RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION" \
  "ES=8.15.3|OS=|SOLR="

# OS: each valid version.
expect_ok_export "os valid latest (3.6.0)" \
  "unset RELYLOOP_ES_VERSION; RELYLOOP_OS_VERSION=3.6.0; unset RELYLOOP_SOLR_VERSION" \
  "ES=|OS=3.6.0|SOLR="
expect_ok_export "os valid older major (2.18.0)" \
  "unset RELYLOOP_ES_VERSION; RELYLOOP_OS_VERSION=2.18.0; unset RELYLOOP_SOLR_VERSION" \
  "ES=|OS=2.18.0|SOLR="

# Solr: each valid version.
expect_ok_export "solr valid latest (10.0)" \
  "unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION; RELYLOOP_SOLR_VERSION=10.0" \
  "ES=|OS=|SOLR=10.0"
expect_ok_export "solr valid older major (9.7)" \
  "unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION; RELYLOOP_SOLR_VERSION=9.7" \
  "ES=|OS=|SOLR=9.7"

# All three set to valid latest values.
expect_ok_export "all three valid latest" \
  "RELYLOOP_ES_VERSION=9.4.1; RELYLOOP_OS_VERSION=3.6.0; RELYLOOP_SOLR_VERSION=10.0" \
  "ES=9.4.1|OS=3.6.0|SOLR=10.0"

# Unknown — each engine individually.
expect_fail "es unknown (9.9.9)" \
  "RELYLOOP_ES_VERSION=9.9.9; unset RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION" \
  "Unknown elasticsearch version '9.9.9'. Allowed: 9.4.1, 8.15.3."
expect_fail "os unknown (4.0.0)" \
  "unset RELYLOOP_ES_VERSION; RELYLOOP_OS_VERSION=4.0.0; unset RELYLOOP_SOLR_VERSION" \
  "Unknown opensearch version '4.0.0'. Allowed: 3.6.0, 2.18.0."
expect_fail "solr unknown (8.5)" \
  "unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION; RELYLOOP_SOLR_VERSION=8.5" \
  "Unknown solr version '8.5'. Allowed: 10.0, 9.7."

# Short-circuit: ES is validated first; a downstream OS/Solr error never
# fires when ES is the first unknown.
expect_fail "mixed one unknown (es first)" \
  "RELYLOOP_ES_VERSION=9.9.9; RELYLOOP_OS_VERSION=4.0.0; RELYLOOP_SOLR_VERSION=8.5" \
  "Unknown elasticsearch version '9.9.9'. Allowed: 9.4.1, 8.15.3."

echo
if [[ "$FAIL" -gt 0 ]]; then
  echo "FAIL: ${FAIL} case(s) failed (${PASS} passed)"
  exit 1
fi
echo "ok: ${PASS} cases passed"
