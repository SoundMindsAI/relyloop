#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Sourceable helper for RELYLOOP_LLM → COMPOSE_PROFILES translation.
#
# feat_bundled_local_llm Story 1.
#
# Defines `parse_relyloop_llm` — reads `$RELYLOOP_LLM` (allowlist: `ollama`,
# `ollama-docker`). `ollama` is NATIVE-first (no Compose profile — install.sh's
# resolve_native_ollama detects a host-native Ollama and wires the app at it);
# `ollama-docker` appends the `bundled-llm` profile to start the slow Dockerized
# Ollama (CPU-only fallback). OFF by default (unset RELYLOOP_LLM → no LLM).
# feat_bundled_llm_native_detection re-scoped this from the shipped
# feat_bundled_local_llm (where `ollama` meant the Docker container).
#
# Sourced from scripts/install.sh AFTER `parse_relyloop_engines` (so engine
# selection is resolved into COMPOSE_PROFILES first, then this appends to it);
# also sourced from scripts/ci/test_parse_relyloop_llm.sh so the function is
# testable in isolation.
#
# FR-4 precedence: an explicit `$OPENAI_BASE_URL` means the operator already
# has their own OpenAI-compatible endpoint — it WINS over RELYLOOP_LLM and the
# bundled container is never started. This check runs FIRST (before validating
# RELYLOOP_LLM) so a bring-your-own-endpoint install is never blocked by an
# unrelated RELYLOOP_LLM typo.

# `set -e` / `set -u` are inherited from the caller (install.sh runs
# `set -euo pipefail`). This file is sourced, never executed directly, so it
# does not re-`set -e` here.

parse_relyloop_llm() {
  # 1. FR-4 precedence FIRST. A non-empty OPENAI_BASE_URL → operator endpoint
  #    wins; do NOT append bundled-llm. Return 0 regardless of RELYLOOP_LLM's
  #    value (even an otherwise-unknown one — the endpoint is what matters).
  if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
    if [[ -n "${RELYLOOP_LLM:-}" ]]; then
      echo "RelyLoop: OPENAI_BASE_URL is set — using that endpoint; bundled LLM (RELYLOOP_LLM=${RELYLOOP_LLM}) not started." >&2
    fi
    # Defensive: guarantee the helper's contract "OPENAI_BASE_URL set ⇒
    # bundled-llm NOT in COMPOSE_PROFILES" even if a caller pre-seeded it
    # (in install.sh, parse_relyloop_engines already overwrites COMPOSE_PROFILES
    # first, so this is belt-and-suspenders — but it keeps the helper correct in
    # isolation and against future reordering).
    if [[ ",${COMPOSE_PROFILES:-}," == *",bundled-llm,"* ]]; then
      local stripped=",${COMPOSE_PROFILES},"
      stripped="${stripped//,bundled-llm,/,}"
      stripped="${stripped#,}"
      stripped="${stripped%,}"
      export COMPOSE_PROFILES="$stripped"
    fi
    return 0
  fi

  # 2. Strip all whitespace; unset/empty → lightweight default (no LLM).
  local input="${RELYLOOP_LLM:-}"
  input="${input// /}"
  input="${input//$'\t'/}"
  [[ -z "$input" ]] && return 0

  # 3. Validate against the allowlist + apply the per-value behavior BEFORE any
  #    docker compose call. feat_bundled_llm_native_detection:
  #      - `ollama`        → NATIVE-first. Do NOT append a Compose profile —
  #                          install.sh runs host-Ollama detection (no Docker
  #                          LLM container for this value).
  #      - `ollama-docker` → the bundled Dockerized Ollama (slow CPU fallback).
  #                          Append the `bundled-llm` profile.
  case "$input" in
  ollama)
    : # native path — no profile; install.sh's resolve_native_ollama handles it.
    ;;
  ollama-docker)
    # Append "bundled-llm" to COMPOSE_PROFILES, preserving existing engine
    # profiles. Comma-guarded substring match avoids a duplicate token.
    local profiles="${COMPOSE_PROFILES:-}"
    if [[ ",${profiles}," == *",bundled-llm,"* ]]; then
      : # already present — no-op
    elif [[ -z "$profiles" ]]; then
      export COMPOSE_PROFILES="bundled-llm"
    else
      export COMPOSE_PROFILES="${profiles},bundled-llm"
    fi
    echo "RelyLoop: bundled Docker LLM (ollama-docker) enabled — COMPOSE_PROFILES=${COMPOSE_PROFILES}"
    ;;
  *)
    echo "Unknown RELYLOOP_LLM '$input'. Allowed: ollama, ollama-docker." >&2
    return 1
    ;;
  esac
}
