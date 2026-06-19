#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/lib/relyloop_llm.sh's `parse_relyloop_llm`.
#
# feat_bundled_local_llm Story 1.
#
# Exercises the helper with (RELYLOOP_LLM, preset COMPOSE_PROFILES,
# OPENAI_BASE_URL) tuples. Asserts:
#   - unset / empty RELYLOOP_LLM → COMPOSE_PROFILES unchanged (no bundled-llm)
#   - ollama → appends "bundled-llm" preserving existing engine profiles
#   - already-present bundled-llm → not duplicated
#   - whitespace tolerated
#   - FR-4 precedence: OPENAI_BASE_URL set → no bundled-llm + notice, rc 0
#     (even when RELYLOOP_LLM holds an otherwise-unknown value)
#   - unknown RELYLOOP_LLM (no OPENAI_BASE_URL) → rc 1 + allowlist message
#
# Run locally:  bash scripts/ci/test_parse_relyloop_llm.sh
# Run in CI:    invoked by .github/workflows/pr.yml.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PASS=0
FAIL=0

# expect_profiles <name> <RELYLOOP_LLM> <preset_profiles> <openai_base_url> <expected_profiles>
expect_profiles() {
  local name="$1" llm="$2" preset="$3" base_url="$4" expected="$5"
  local actual rc
  rc=0
  actual="$(RELYLOOP_LLM="$llm" COMPOSE_PROFILES="$preset" OPENAI_BASE_URL="$base_url" bash -c '
    set -eo pipefail
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_llm.sh"
    parse_relyloop_llm >/dev/null 2>&1
    printf "%s" "${COMPOSE_PROFILES:-}"
  ')" || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${rc}"; FAIL=$((FAIL + 1)); return
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "  FAIL ${name}: expected COMPOSE_PROFILES='${expected}', got '${actual}'"; FAIL=$((FAIL + 1)); return
  fi
  echo "  ok   ${name}"; PASS=$((PASS + 1))
}

# expect_fail <name> <RELYLOOP_LLM> <stderr_substring>  (OPENAI_BASE_URL unset)
expect_fail() {
  local name="$1" llm="$2" expected_stderr="$3"
  local stderr_path rc
  stderr_path="$(mktemp)"; rc=0
  RELYLOOP_LLM="$llm" bash -c '
    set -o pipefail
    unset OPENAI_BASE_URL
    source "'"${REPO_ROOT}"'/scripts/lib/relyloop_llm.sh"
    parse_relyloop_llm >/dev/null
  ' 2>"${stderr_path}" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    echo "  FAIL ${name}: expected non-zero rc, got 0"; FAIL=$((FAIL + 1)); rm -f "$stderr_path"; return
  fi
  if ! grep -qF -- "$expected_stderr" "$stderr_path"; then
    echo "  FAIL ${name}: stderr missing '${expected_stderr}' (got: $(tr '\n' ' ' < "$stderr_path"))"
    FAIL=$((FAIL + 1)); rm -f "$stderr_path"; return
  fi
  echo "  ok   ${name}"; PASS=$((PASS + 1)); rm -f "$stderr_path"
}

echo "parse_relyloop_llm regression cases:"

# Default OFF — unset/empty leaves engine profiles untouched.
expect_profiles "unset → no bundled-llm"      ""       "solr"        "" "solr"
expect_profiles "empty → no bundled-llm"      ""       "es,os,solr"  "" "es,os,solr"

# Opt-in appends, preserving engine profiles.
expect_profiles "ollama + solr"               "ollama" "solr"        "" "solr,bundled-llm"
expect_profiles "ollama + all engines"        "ollama" "es,os,solr"  "" "es,os,solr,bundled-llm"
expect_profiles "ollama + empty profiles"     "ollama" ""            "" "bundled-llm"

# Idempotent — no duplicate token.
expect_profiles "already present"             "ollama" "solr,bundled-llm" "" "solr,bundled-llm"

# Whitespace tolerated.
expect_profiles "whitespace ' ollama '"       " ollama " "solr"      "" "solr,bundled-llm"

# FR-4 precedence: OPENAI_BASE_URL wins → no bundled-llm, rc 0.
expect_profiles "endpoint set beats ollama"   "ollama" "solr"        "http://host.docker.internal:11434/v1" "solr"
expect_profiles "endpoint set beats typo"     "vllm"   "solr"        "https://api.openai.com/v1"            "solr"
# Defensive: a pre-seeded bundled-llm is STRIPPED when OPENAI_BASE_URL is set,
# so the helper's contract holds in isolation (PG-2).
expect_profiles "endpoint strips pre-set bundled-llm" "ollama" "solr,bundled-llm" "https://api.openai.com/v1" "solr"
expect_profiles "endpoint strips lone bundled-llm"    "ollama" "bundled-llm"      "http://h/v1"               ""

# Unknown value (no endpoint) → fail fast.
expect_fail "unknown 'vllm'"                  "vllm"   "Unknown RELYLOOP_LLM 'vllm'. Allowed: ollama."
expect_fail "unknown 'lmstudio'"              "lmstudio" "Allowed: ollama."

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
