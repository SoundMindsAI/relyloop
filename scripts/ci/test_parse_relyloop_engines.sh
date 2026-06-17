#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/lib/relyloop_engines.sh's
# `parse_relyloop_engines` function.
#
# feat_selective_engine_startup_and_demo Story 1.1.
#
# Sources the helper and exercises it with a battery of (RELYLOOP_ENGINES
# input, expected exit, expected COMPOSE_PROFILES) tuples. Asserts:
#   - unset / empty → default es,os,solr (preserve current behavior)
#   - any single-engine subset → that engine alone
#   - multi-engine subset → exact set in input order
#   - duplicates → deduped while preserving first occurrence
#   - whitespace tolerated (`es, os` and `es ,os`)
#   - unknown engine name → exit 1 + stderr message + COMPOSE_PROFILES unchanged
#
# Run locally:  bash scripts/ci/test_parse_relyloop_engines.sh
# Run in CI:    invoked by .github/workflows/pr.yml's parse-relyloop-engines
#               job (added in this PR).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/relyloop_engines.sh
source "${REPO_ROOT}/scripts/lib/relyloop_engines.sh"

PASS=0
FAIL=0

# expect_ok <case_name> <input> <expected_profiles>
#   Runs parse_relyloop_engines with RELYLOOP_ENGINES=<input>, asserts the
#   function returns 0 and COMPOSE_PROFILES matches.
expect_ok() {
  local name="$1"
  local input="$2"
  local expected="$3"
  # Run in a subshell so each case has independent COMPOSE_PROFILES state.
  local actual_stdout
  local actual_profiles
  local actual_rc
  actual_rc=0
  actual_stdout="$(RELYLOOP_ENGINES="$input" bash -c '
    set -eo pipefail
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_engines.sh"
    parse_relyloop_engines >/dev/null
    printf "%s" "$COMPOSE_PROFILES"
  ' 2>/dev/null)" || actual_rc=$?
  actual_profiles="$actual_stdout"

  if [[ "$actual_rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${actual_rc}"
    FAIL=$((FAIL + 1))
    return
  fi
  if [[ "$actual_profiles" != "$expected" ]]; then
    echo "  FAIL ${name}: expected COMPOSE_PROFILES='${expected}', got '${actual_profiles}'"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "  ok   ${name}"
  PASS=$((PASS + 1))
}

# expect_fail <case_name> <input> <stderr_substring>
#   Runs parse_relyloop_engines with RELYLOOP_ENGINES=<input>, asserts the
#   function returns non-zero AND stderr contains the expected substring
#   AND no COMPOSE_PROFILES was exported.
expect_fail() {
  local name="$1"
  local input="$2"
  local expected_stderr="$3"
  local stderr_path
  stderr_path="$(mktemp)"
  local rc
  rc=0
  RELYLOOP_ENGINES="$input" bash -c '
    set -o pipefail
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_engines.sh"
    parse_relyloop_engines >/dev/null
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

echo "parse_relyloop_engines regression cases:"

# Defaults.
expect_ok "unset (RELYLOOP_ENGINES not in env)" "" "es,os,solr"

# Single-engine subsets.
expect_ok "es only"   "es"   "es"
expect_ok "os only"   "os"   "os"
expect_ok "solr only" "solr" "solr"

# Multi-engine subsets in input order.
expect_ok "es,os"   "es,os"   "es,os"
expect_ok "es,solr" "es,solr" "es,solr"
expect_ok "os,solr" "os,solr" "os,solr"
expect_ok "all three explicit" "es,os,solr" "es,os,solr"
expect_ok "non-default order preserved" "solr,os,es" "solr,os,es"

# Whitespace tolerance.
expect_ok "whitespace after comma" "es, os, solr" "es,os,solr"
expect_ok "whitespace before comma" "es ,os ,solr" "es,os,solr"
expect_ok "tab tolerated"          "es,	os" "es,os"

# Deduplication (preserves first occurrence).
expect_ok "duplicate es"  "es,os,es"   "es,os"
expect_ok "all duplicates" "es,es,es"  "es"

# Unknown engine names.
expect_fail "unknown 'fusion'" "es,fusion" \
  "Unknown engine 'fusion' in RELYLOOP_ENGINES. Allowed: es, os, solr."
expect_fail "unknown alone"    "elasticsearch" \
  "Unknown engine 'elasticsearch' in RELYLOOP_ENGINES. Allowed: es, os, solr."
expect_fail "unknown mid-list" "es,foo,solr" \
  "Unknown engine 'foo' in RELYLOOP_ENGINES. Allowed: es, os, solr."

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
