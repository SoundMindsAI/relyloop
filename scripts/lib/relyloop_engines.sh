#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Sourceable helper for RELYLOOP_ENGINES → COMPOSE_PROFILES translation.
#
# feat_selective_engine_startup_and_demo Story 1.1.
#
# Defines `parse_relyloop_engines` — reads `$RELYLOOP_ENGINES` (comma-
# separated subset of `es`, `os`, `solr`), validates against the allowlist,
# deduplicates while preserving first-occurrence order, and exports the
# resolved value as `COMPOSE_PROFILES`. Defaults to all three engines when
# the env var is unset OR empty so a bare `make up` preserves the project's
# current three-engine startup behavior.
#
# Sourced from scripts/install.sh; also sourced from
# scripts/ci/test_parse_relyloop_engines.sh so the function is testable in
# isolation (without install.sh's top-level secrets generation and Compose
# invocations).
#
# Validation MUST happen BEFORE any `docker compose` call. An unknown
# engine name in `RELYLOOP_ENGINES` exits 1 with a clear stderr message
# rather than silently producing an unexpected Compose set.

# `set -e` / `set -u` are inherited from the caller (install.sh runs
# `set -euo pipefail`). This file is sourced, never executed directly, so
# it does not re-`set -e` here.

parse_relyloop_engines() {
  local default="es,os,solr"
  local input="${RELYLOOP_ENGINES:-$default}"
  # Treat an explicitly-empty value as "unset" so `RELYLOOP_ENGINES=` in
  # .env behaves like commenting the line out.
  [[ -z "$input" ]] && input="$default"

  # Split on comma; tolerate `es, os` style whitespace.
  local IFS=','
  read -ra requested <<< "$input"
  unset IFS

  local valid=("es" "os" "solr")
  local cleaned=()
  for raw in "${requested[@]}"; do
    # Strip ALL whitespace from the value, not just outer trim. Tolerates
    # `es, os` and `es ,os` equally.
    local eng="${raw// /}"
    eng="${eng//$'\t'/}"
    [[ -z "$eng" ]] && continue
    local ok=0
    for v in "${valid[@]}"; do
      if [[ "$eng" == "$v" ]]; then
        ok=1
        break
      fi
    done
    if [[ "$ok" -eq 0 ]]; then
      echo "Unknown engine '$eng' in RELYLOOP_ENGINES. Allowed: es, os, solr." >&2
      return 1
    fi
    cleaned+=("$eng")
  done

  # Deduplicate (preserves first-occurrence order). Uses the bash-3.2-safe
  # `${arr[@]+"${arr[@]}"}` empty-array form documented in CLAUDE.md
  # "Working in sibling worktrees" — bare `"${arr[@]}"` errors under
  # `set -u` on macOS bash 3.2 when the array has never had an element.
  local seen=() out=()
  for e in "${cleaned[@]+"${cleaned[@]}"}"; do
    local hit=0
    for s in "${seen[@]+"${seen[@]}"}"; do
      if [[ "$e" == "$s" ]]; then
        hit=1
        break
      fi
    done
    if [[ "$hit" -eq 0 ]]; then
      seen+=("$e")
      out+=("$e")
    fi
  done

  if [[ "${#out[@]}" -eq 0 ]]; then
    # Defensive — should be unreachable (the all-whitespace input would
    # have been replaced by the default earlier). Fall back rather than
    # silently start no engines.
    out=("es" "os" "solr")
  fi

  local joined
  local IFS=','
  joined="${out[*]}"
  unset IFS

  export COMPOSE_PROFILES="$joined"
  echo "RelyLoop: starting engines: $COMPOSE_PROFILES"
}
