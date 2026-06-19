#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Host-native Ollama detection for `RELYLOOP_LLM=ollama`.
#
# feat_bundled_llm_native_detection.
#
# `resolve_native_ollama` probes the host for a running native (Metal-accelerated
# on macOS) Ollama and, on a validated find, wires the app at it via
# `OPENAI_BASE_URL=http://host.docker.internal:11434/v1` + a sentinel key. On
# not-found it prints actionable guidance and returns 1 (install.sh then brings
# the stack up LLM-free). The slow Dockerized Ollama is a separate path
# (`RELYLOOP_LLM=ollama-docker`, handled by relyloop_llm.sh).
#
# Testability (the probe + key file are injectable so CI exercises every branch
# with NO real network or real ./secrets write):
#   - RELYLOOP_NATIVE_PROBE_FUNC : name of the probe function (default
#                                  `relyloop_native_probe`); tests set a mock.
#   - RELYLOOP_NATIVE_PROBE_URL  : the probed URL (default localhost:11434).
#   - RELYLOOP_OPENAI_KEY_FILE   : the sentinel key path (default ./secrets/openai_key).
#
# `set -e`/`set -u` are inherited from the caller (install.sh). Sourced, not run.

NATIVE_OLLAMA_PROBE_URL_DEFAULT="http://localhost:11434/api/tags"
NATIVE_OLLAMA_ENDPOINT="http://host.docker.internal:11434/v1"
NATIVE_OLLAMA_SENTINEL="ollama"

# Default probe — overridable via RELYLOOP_NATIVE_PROBE_FUNC for tests. Uses only
# curl (no jq/python host dependency). Prints the body on success.
relyloop_native_probe() {
  curl -fsS --max-time 2 "$1" 2>/dev/null
}

_native_key_file() {
  printf '%s' "${RELYLOOP_OPENAI_KEY_FILE:-./secrets/openai_key}"
}

# The unmistakable "no LLM" summary (NS-5 / FR-8). Sourceable → testable.
_native_summary_no_llm() {
  cat >&2 <<'EOF'
RELYLOOP_LLM=ollama: no usable native Ollama — the stack is up WITHOUT LLM features.
  - Install Ollama (https://ollama.com), then: ollama serve && ollama pull qwen3.5:4b, and re-run.
  - Or set OPENAI_BASE_URL in .env to any OpenAI-compatible endpoint (OpenAI cloud, LM Studio, ...).
  - Or for the slow zero-install Docker fallback: RELYLOOP_LLM=ollama-docker make up
EOF
}

# The container-can't-reach-host warning (NS-1 / FR-8). Sourceable → testable.
_native_warn_unreachable() {
  cat >&2 <<'EOF'
WARNING: a native Ollama was detected on the host but the RelyLoop containers cannot reach it.
  On Linux, host.docker.internal resolves to the bridge address, NOT loopback — bind Ollama to a
  non-loopback interface:  OLLAMA_HOST=0.0.0.0:11434 ollama serve
  Or use RELYLOOP_LLM=ollama-docker, or set an explicit reachable OPENAI_BASE_URL.
EOF
}

# Is $model present in the probe body? Matches the QUOTED model name (Ollama's
# `"name":"<model>"` value) so a model that's merely a substring of another
# doesn't false-positive (Ph-4). Normalizes the implicit `:latest` tag (an
# untagged `foo` is stored by Ollama as `foo:latest`).
_native_model_present() {
  local model="$1" body="$2"
  grep -qF "\"${model}\"" <<<"$body" && return 0
  [[ "$model" != *:* ]] && grep -qF "\"${model}:latest\"" <<<"$body" && return 0
  return 1
}

# Clear a stale sentinel key (iff its content == the sentinel) — so reverting to
# no-LLM doesn't leave `Bearer ollama` against the wrong endpoint.
_native_clear_stale_sentinel() {
  local kf
  kf="$(_native_key_file)"
  [[ -s "$kf" && "$(cat "$kf")" == "$NATIVE_OLLAMA_SENTINEL" ]] && : > "$kf"
  return 0
}

# resolve_native_ollama — returns 0 if a native Ollama was found + wired
# (OPENAI_BASE_URL exported, sentinel written), 1 if not found (guidance printed).
resolve_native_ollama() {
  # 0. An explicit endpoint wins — do NOT probe. Still clear a stale sentinel so
  #    `Bearer ollama` is never sent to the operator's endpoint (Ph-1).
  if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
    _native_clear_stale_sentinel
    return 0
  fi

  local probe_func="${RELYLOOP_NATIVE_PROBE_FUNC:-relyloop_native_probe}"
  local url="${RELYLOOP_NATIVE_PROBE_URL:-$NATIVE_OLLAMA_PROBE_URL_DEFAULT}"
  local body
  body="$("$probe_func" "$url")" || body=""

  # 2. Validate the Ollama shape: a `"models"` ARRAY (not just the substring).
  if ! grep -Eq '"models"[[:space:]]*:[[:space:]]*\[' <<<"$body"; then
    _native_clear_stale_sentinel
    _native_summary_no_llm
    return 1
  fi

  # 3. Found. Wire the app at the host-native Ollama; preserve operator models.
  export OPENAI_BASE_URL="$NATIVE_OLLAMA_ENDPOINT"
  export OPENAI_MODEL="${OPENAI_MODEL:-${OLLAMA_MODEL:-qwen3.5:4b}}"
  export OPENAI_MODEL_CHAT="${OPENAI_MODEL_CHAT:-${OLLAMA_MODEL:-qwen3.5:4b}}"

  # Sentinel key (the openai SDK + capability check refuse an empty key). Write
  # iff empty-or-sentinel — never clobber a real operator key.
  local kf
  kf="$(_native_key_file)"
  if [[ ! -s "$kf" || "$(cat "$kf")" == "$NATIVE_OLLAMA_SENTINEL" ]]; then
    mkdir -p "$(dirname "$kf")"
    printf '%s' "$NATIVE_OLLAMA_SENTINEL" > "$kf"
    chmod 600 "$kf" 2>/dev/null || true
  fi

  # Warn once per missing effective model (dedup OPENAI_MODEL == OPENAI_MODEL_CHAT).
  local m checked=""
  for m in "$OPENAI_MODEL" "$OPENAI_MODEL_CHAT"; do
    [[ -z "$m" ]] && continue
    case ",${checked}," in *",${m},"*) continue ;; esac
    checked="${checked:+$checked,}$m"
    if ! _native_model_present "$m" "$body"; then
      echo "RelyLoop: native Ollama is running but model '$m' is not pulled — run: ollama pull $m" >&2
    fi
  done

  echo "RelyLoop: using host-native Ollama at ${NATIVE_OLLAMA_ENDPOINT} (model: ${OPENAI_MODEL})."
  return 0
}
