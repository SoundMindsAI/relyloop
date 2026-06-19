#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Sourceable helper for RELYLOOP_LLM → COMPOSE_PROFILES translation.
#
# feat_bundled_local_llm Story 1.
#
# Defines `parse_relyloop_llm` — reads `$RELYLOOP_LLM` (allowlist: `ollama`)
# and appends the `bundled-llm` Compose profile to `$COMPOSE_PROFILES` so the
# bundled Ollama service starts. The bundled LLM is OFF by default (unset
# RELYLOOP_LLM → no profile, lightweight stack); `RELYLOOP_LLM=ollama make up`
# is the one-flag opt-in.
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
    return 0
  fi

  # 2. Strip all whitespace; unset/empty → lightweight default (no LLM).
  local input="${RELYLOOP_LLM:-}"
  input="${input// /}"
  input="${input//$'\t'/}"
  [[ -z "$input" ]] && return 0

  # 3. Validate against the allowlist BEFORE any docker compose call.
  if [[ "$input" != "ollama" ]]; then
    echo "Unknown RELYLOOP_LLM '$input'. Allowed: ollama." >&2
    return 1
  fi

  # 4. Append "bundled-llm" to COMPOSE_PROFILES, preserving existing engine
  #    profiles. Comma-guarded substring match avoids a duplicate token.
  local profiles="${COMPOSE_PROFILES:-}"
  if [[ ",${profiles}," == *",bundled-llm,"* ]]; then
    : # already present — no-op
  elif [[ -z "$profiles" ]]; then
    export COMPOSE_PROFILES="bundled-llm"
  else
    export COMPOSE_PROFILES="${profiles},bundled-llm"
  fi
  echo "RelyLoop: bundled LLM (ollama) enabled — COMPOSE_PROFILES=${COMPOSE_PROFILES}"
}
