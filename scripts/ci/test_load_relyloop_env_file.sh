#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/lib/relyloop_env_file.sh's
# `load_relyloop_env_file` function.
#
# bug_install_sh_env_file_not_loaded.
#
# Asserts:
#   - a RELYLOOP_ENGINES= line in .env is exported into the environment
#   - a commented `# RELYLOOP_ENGINES=` line is NOT loaded
#   - the shell environment wins over .env (explicit `VAR=x` beats the file)
#   - the three RELYLOOP_*_VERSION keys load
#   - a missing .env file is a clean no-op (rc 0, nothing exported)
#   - leading indentation tolerated; trailing whitespace trimmed
#   - surrounding quotes stripped (Compose-like)
#   - last uncommented assignment wins (dotenv semantics)
#   - only the four known keys load — an unrelated KEY= line is ignored
#
# Run locally:  bash scripts/ci/test_load_relyloop_env_file.sh
# Run in CI:    invoked by .github/workflows/pr.yml's static-checks-backend job.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${REPO_ROOT}/scripts/lib/relyloop_env_file.sh"

PASS=0
FAIL=0

# expect <case_name> <env_setup> <env_file_contents> <expected_payload>
#   <env_setup>: shell prelude run before the load (e.g. clear/set the four
#                vars). <env_file_contents>: written to a temp .env (empty
#                string => no file written, exercising the missing-file path).
#   <expected_payload>: literal "ENGINES=…|ES=…|OS=…|SOLR=…" the inner shell
#                prints after the load.
expect() {
  local name="$1"
  local env_setup="$2"
  local env_contents="$3"
  local expected="$4"

  local tmpdir
  tmpdir="$(mktemp -d)"
  local env_path="${tmpdir}/.env"
  if [[ -n "$env_contents" ]]; then
    printf '%s\n' "$env_contents" > "$env_path"
  fi

  local actual
  local rc
  rc=0
  actual="$(bash -c '
    set -eo pipefail
    '"${env_setup}"'
    source "'"${HELPER}"'"
    load_relyloop_env_file "'"${env_path}"'"
    printf "ENGINES=%s|ES=%s|OS=%s|SOLR=%s" \
      "${RELYLOOP_ENGINES:-}" "${RELYLOOP_ES_VERSION:-}" \
      "${RELYLOOP_OS_VERSION:-}" "${RELYLOOP_SOLR_VERSION:-}"
  ')" || rc=$?
  # stderr is intentionally NOT silenced — a syntax/sourcing error in the
  # helper surfaces in the test output instead of being swallowed (Gemini
  # review #2). The helper is silent on success, so passing cases stay quiet.

  rm -rf "$tmpdir"

  if [[ "$rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${rc}"
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

# All four vars unset in the inner shell prelude so .env is the only source.
CLEAR="unset RELYLOOP_ENGINES RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION"

echo "load_relyloop_env_file regression cases:"

expect "engines loaded from .env" \
  "$CLEAR" \
  "RELYLOOP_ENGINES=solr" \
  "ENGINES=solr|ES=|OS=|SOLR="

expect "commented engines line is NOT loaded" \
  "$CLEAR" \
  "# RELYLOOP_ENGINES=es" \
  "ENGINES=|ES=|OS=|SOLR="

expect "shell env wins over .env" \
  "RELYLOOP_ENGINES=es; unset RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION" \
  "RELYLOOP_ENGINES=solr" \
  "ENGINES=es|ES=|OS=|SOLR="

expect "all three version vars load" \
  "$CLEAR" \
  "RELYLOOP_ES_VERSION=8.15.3
RELYLOOP_OS_VERSION=2.18.0
RELYLOOP_SOLR_VERSION=9.7" \
  "ENGINES=|ES=8.15.3|OS=2.18.0|SOLR=9.7"

expect "missing .env file is a clean no-op" \
  "$CLEAR" \
  "" \
  "ENGINES=|ES=|OS=|SOLR="

expect "leading indentation tolerated, trailing whitespace trimmed" \
  "$CLEAR" \
  "  RELYLOOP_ENGINES=es,solr   " \
  "ENGINES=es,solr|ES=|OS=|SOLR="

expect "surrounding double quotes stripped" \
  "$CLEAR" \
  'RELYLOOP_ENGINES="solr"' \
  "ENGINES=solr|ES=|OS=|SOLR="

expect "surrounding single quotes stripped" \
  "$CLEAR" \
  "RELYLOOP_SOLR_VERSION='9.7'" \
  "ENGINES=|ES=|OS=|SOLR=9.7"

expect "last uncommented assignment wins" \
  "$CLEAR" \
  "RELYLOOP_ENGINES=es
RELYLOOP_ENGINES=solr" \
  "ENGINES=solr|ES=|OS=|SOLR="

expect "unrelated KEY= line ignored, RELYLOOP_ENGINES still loaded" \
  "$CLEAR" \
  "UNRELATED_KEY=ignored
RELYLOOP_ENGINES=solr" \
  "ENGINES=solr|ES=|OS=|SOLR="

# A near-miss key (RELYLOOP_ENGINES_FOO) must not satisfy the RELYLOOP_ENGINES
# grep — the `=` anchor prevents prefix bleed.
expect "near-miss key does not bleed into RELYLOOP_ENGINES" \
  "$CLEAR" \
  "RELYLOOP_ENGINES_FOO=bar" \
  "ENGINES=|ES=|OS=|SOLR="

# --- feat_bundled_local_llm: the bundled-LLM keys (RELYLOOP_LLM + OPENAI_*/
#     OLLAMA_MODEL) load too, so install.sh's gating/precedence logic sees
#     `.env`-only values. Separate helper prints these five keys. ---
CLEAR_LLM="unset RELYLOOP_LLM OPENAI_BASE_URL OPENAI_MODEL OPENAI_MODEL_CHAT OLLAMA_MODEL"

# expect_llm <name> <env_setup> <env_contents> <expected: LLM=…|BASE=…|MODEL=…|CHAT=…|OLLAMA=…>
expect_llm() {
  local name="$1" env_setup="$2" env_contents="$3" expected="$4"
  local tmpdir env_path actual rc
  tmpdir="$(mktemp -d)"; env_path="${tmpdir}/.env"; rc=0
  [[ -n "$env_contents" ]] && printf '%s\n' "$env_contents" > "$env_path"
  actual="$(bash -c '
    set -eo pipefail
    '"${env_setup}"'
    source "'"${HELPER}"'"
    load_relyloop_env_file "'"${env_path}"'"
    printf "LLM=%s|BASE=%s|MODEL=%s|CHAT=%s|OLLAMA=%s" \
      "${RELYLOOP_LLM:-}" "${OPENAI_BASE_URL:-}" "${OPENAI_MODEL:-}" \
      "${OPENAI_MODEL_CHAT:-}" "${OLLAMA_MODEL:-}"
  ')" || rc=$?
  rm -rf "$tmpdir"
  if [[ "$rc" -ne 0 ]]; then
    echo "  FAIL ${name}: expected rc=0, got rc=${rc}"; FAIL=$((FAIL + 1)); return
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "  FAIL ${name}: expected '${expected}', got '${actual}'"; FAIL=$((FAIL + 1)); return
  fi
  echo "  ok   ${name}"; PASS=$((PASS + 1))
}

echo "load_relyloop_env_file (bundled-LLM keys) regression cases:"

expect_llm "RELYLOOP_LLM loads from .env" \
  "$CLEAR_LLM" \
  "RELYLOOP_LLM=ollama" \
  "LLM=ollama|BASE=|MODEL=|CHAT=|OLLAMA="

expect_llm "OPENAI_BASE_URL with ?/# loads intact (by-name, not blind-sourced)" \
  "$CLEAR_LLM" \
  "OPENAI_BASE_URL=http://h:11434/v1?x=1#frag" \
  "LLM=|BASE=http://h:11434/v1?x=1#frag|MODEL=|CHAT=|OLLAMA="

expect_llm "OLLAMA_MODEL + both model vars load" \
  "$CLEAR_LLM" \
  "OLLAMA_MODEL=qwen3.5:2b
OPENAI_MODEL=qwen3.5:4b
OPENAI_MODEL_CHAT=qwen3.5:4b" \
  "LLM=|BASE=|MODEL=qwen3.5:4b|CHAT=qwen3.5:4b|OLLAMA=qwen3.5:2b"

expect_llm "shell env wins for OPENAI_BASE_URL" \
  "OPENAI_BASE_URL=https://shell.example/v1; unset RELYLOOP_LLM OPENAI_MODEL OPENAI_MODEL_CHAT OLLAMA_MODEL" \
  "OPENAI_BASE_URL=http://envfile/v1" \
  "LLM=|BASE=https://shell.example/v1|MODEL=|CHAT=|OLLAMA="

expect_llm "commented RELYLOOP_LLM not loaded" \
  "$CLEAR_LLM" \
  "# RELYLOOP_LLM=ollama" \
  "LLM=|BASE=|MODEL=|CHAT=|OLLAMA="

echo
if [[ "$FAIL" -gt 0 ]]; then
  echo "FAIL: ${FAIL} case(s) failed (${PASS} passed)"
  exit 1
fi
echo "ok: ${PASS} cases passed"
