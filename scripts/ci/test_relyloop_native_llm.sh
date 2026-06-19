#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Regression test for scripts/lib/relyloop_native_llm.sh's `resolve_native_ollama`.
#
# feat_bundled_llm_native_detection. Exercises every branch with a MOCKED probe
# (RELYLOOP_NATIVE_PROBE_FUNC) + a temp key file (RELYLOOP_OPENAI_KEY_FILE) — no
# real network, no real ./secrets write. Asserts: shape validation, host wiring +
# sentinel write, not-found guidance + stale-sentinel clear, model-missing warning
# (+ `:latest` normalization), the OPENAI_BASE_URL probe-skip, and the FR-8
# message helpers.
#
# Run locally:  bash scripts/ci/test_relyloop_native_llm.sh
# Run in CI:    invoked by .github/workflows/pr.yml.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${REPO_ROOT}/scripts/lib/relyloop_native_llm.sh"

PASS=0
FAIL=0

# _run <prelude-env> <mock_body> <mock_fail 0|1> <preseed_key>
#   Sets globals RESULT="RC=..|BASE=..|KEY=..|MARK=.." and LAST_ERR=<stderr file>.
#   Called DIRECTLY (not in `$(...)`) so the globals persist. The mock touches
#   $MARKER so a test can assert the probe was (not) invoked.
RESULT=""
LAST_ERR=""
_run() {
  local prelude="$1" body="$2" fail="$3" preseed="$4"
  local tmpd keyf marker
  tmpd="$(mktemp -d)"
  keyf="${tmpd}/openai_key"
  marker="${tmpd}/probe_called"
  [[ -n "$preseed" ]] && printf '%s' "$preseed" > "$keyf"
  LAST_ERR="${tmpd}/err"
  RESULT="$(MOCK_BODY="$body" MOCK_FAIL="$fail" MARKER="$marker" RELYLOOP_OPENAI_KEY_FILE="$keyf" \
    bash -c '
      set -uo pipefail
      '"$prelude"'
      source "'"$HELPER"'"
      mock_probe() { : > "$MARKER"; [ "${MOCK_FAIL:-0}" = 1 ] && return 1; printf "%s" "${MOCK_BODY:-}"; }
      RELYLOOP_NATIVE_PROBE_FUNC=mock_probe
      resolve_native_ollama; rc=$?
      printf "RC=%s|BASE=%s|KEY=%s|MARK=%s" "$rc" "${OPENAI_BASE_URL:-}" \
        "$([ -f "'"$keyf"'" ] && cat "'"$keyf"'")" "$([ -f "$MARKER" ] && echo yes || echo no)"
    ' 2>"$LAST_ERR")"
}

assert() {  # assert <name> <actual> <contains>
  local name="$1" actual="$2" want="$3"
  if [[ "$actual" == *"$want"* ]]; then echo "  ok   ${name}"; PASS=$((PASS + 1));
  else echo "  FAIL ${name}: expected to contain '${want}', got '${actual}'"; FAIL=$((FAIL + 1)); fi
}
assert_err() {  # assert_err <name> <contains>
  local name="$1" want="$2"
  if grep -qF -- "$want" "$LAST_ERR"; then echo "  ok   ${name}"; PASS=$((PASS + 1));
  else echo "  FAIL ${name}: stderr missing '${want}' (got: $(tr '\n' ' ' < "$LAST_ERR"))"; FAIL=$((FAIL + 1)); fi
}

OLLAMA_BODY='{"models":[{"name":"qwen3.5:4b"},{"name":"llama3:latest"}]}'

echo "resolve_native_ollama regression cases:"

# (a) Ollama-shaped -> wired at host.docker.internal + sentinel written, rc 0.
_run "" "$OLLAMA_BODY" 0 ""
assert "found: rc 0"            "$RESULT" "RC=0"
assert "found: wires host"     "$RESULT" "BASE=http://host.docker.internal:11434/v1"
assert "found: sentinel key"   "$RESULT" "KEY=ollama"

# (b) Malformed / non-Ollama 200 -> not found, no export, NO sentinel (P-3).
for bad in '{"models":"bad"}' '{"not_models":[]}' 'plaintext mentioning models but not json'; do
  _run "" "$bad" 0 ""
  assert "malformed [$bad]: rc 1"        "$RESULT" "RC=1"
  assert "malformed [$bad]: no wire"     "$RESULT" "BASE=|"
  assert "malformed [$bad]: no sentinel" "$RESULT" "KEY=|"
done

# (c) Probe fails (no native) -> rc 1 + guidance + stale sentinel cleared.
_run "" "" 1 "ollama"
assert "absent: rc 1"               "$RESULT" "RC=1"
assert "absent: stale sentinel cleared" "$RESULT" "KEY=|"
assert_err "absent: summary line"   "WITHOUT LLM features"

# (d) Found but the model isn't pulled -> exact `ollama pull` warning.
_run "OLLAMA_MODEL=missing-model:1b" "$OLLAMA_BODY" 0 ""
assert "model-missing: rc 0"        "$RESULT" "RC=0"
assert_err "model-missing: pull cmd" "ollama pull missing-model:1b"

# (e) `:latest` normalization — effective untagged `llama3` matches body `llama3:latest` (no warning).
_run "OLLAMA_MODEL=llama3" "$OLLAMA_BODY" 0 ""
assert "latest-norm: rc 0"          "$RESULT" "RC=0"
if grep -q "ollama pull llama3" "$LAST_ERR"; then
  echo "  FAIL latest-norm: warned for llama3 though llama3:latest present"; FAIL=$((FAIL + 1));
else echo "  ok   latest-norm: no false pull warning"; PASS=$((PASS + 1)); fi

# (f) Operator OPENAI_MODEL is the checked effective model.
_run "OPENAI_MODEL=not-in-body:7b" "$OLLAMA_BODY" 0 ""
assert_err "effective-model: checks OPENAI_MODEL" "ollama pull not-in-body:7b"

# (g) Explicit OPENAI_BASE_URL -> probe NOT invoked, env unchanged, rc 0 (P-2).
_run "OPENAI_BASE_URL=https://api.openai.com/v1" "$OLLAMA_BODY" 0 ""
assert "endpoint-set: rc 0"         "$RESULT" "RC=0"
assert "endpoint-set: probe NOT called" "$RESULT" "MARK=no"
assert "endpoint-set: base unchanged"   "$RESULT" "BASE=https://api.openai.com/v1"

# (i) Explicit OPENAI_BASE_URL + a PRESEEDED sentinel -> sentinel cleared so
#     `Bearer ollama` isn't sent to the operator's endpoint (Ph-1).
_run "OPENAI_BASE_URL=https://api.openai.com/v1" "$OLLAMA_BODY" 0 "ollama"
assert "endpoint-set: sentinel cleared" "$RESULT" "KEY=|"

# (j) Found + a PRESEEDED REAL key -> never clobbered (Ph-5 / secrets).
_run "" "$OLLAMA_BODY" 0 "sk-real-operator-key"
assert "found: real key preserved"  "$RESULT" "KEY=sk-real-operator-key"

# (h) FR-8 message helpers emit the exact upgrade/loopback substrings (P-6).
ERRH="$(bash -c 'source "'"$HELPER"'"; _native_summary_no_llm; _native_warn_unreachable' 2>&1)"
for sub in "WITHOUT LLM features" "ollama-docker" "OPENAI_BASE_URL" "OLLAMA_HOST=0.0.0.0"; do
  if [[ "$ERRH" == *"$sub"* ]]; then echo "  ok   fr8-msg: '$sub'"; PASS=$((PASS + 1));
  else echo "  FAIL fr8-msg: missing '$sub'"; FAIL=$((FAIL + 1)); fi
done

echo
echo "${PASS} passed, ${FAIL} failed"
[[ "${FAIL}" -gt 0 ]] && exit 1 || exit 0
