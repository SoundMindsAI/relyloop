#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Selective .env loader for the RELYLOOP_* install-time vars.
#
# bug_install_sh_env_file_not_loaded.
#
# scripts/install.sh reads RELYLOOP_ENGINES + RELYLOOP_{ES,OS,SOLR}_VERSION
# from the SHELL environment (parse_relyloop_engines / parse_relyloop_engine
# _versions use `${RELYLOOP_*:-default}`), but nothing loaded `.env` into that
# shell — not the Makefile `up:` target, not install.sh. So the documented
# "set RELYLOOP_ENGINES in .env" path (`.env.example`, install.sh comments,
# `make help`, docs/03_runbooks/local-dev.md) silently did nothing and the
# stack defaulted to all three engines / the default image tags.
#
# This helper closes that gap WITHOUT blind-sourcing `.env`. `.env` legitimately
# holds values bash would mis-parse if sourced directly — proxy URLs with `&`,
# `no_proxy` CSV lists, `OPENAI_BASE_URL` with `?`/`#`, etc. — so we extract
# ONLY the four known RELYLOOP_* keys by name and export them.
#
# Precedence: the SHELL environment wins. A value already set + non-empty in
# the environment (e.g. `RELYLOOP_ENGINES=es make up`, or an `export` earlier
# in the session) is left untouched; `.env` only fills in the gaps. This
# matches the universal "explicit command-line beats config file" convention.

# `set -e` / `set -u` are inherited from the caller (install.sh runs
# `set -euo pipefail`). This file is sourced, never executed directly.

load_relyloop_env_file() {
  local env_file="${1:-.env}"
  [[ -f "$env_file" ]] || return 0

  local key
  for key in RELYLOOP_ENGINES RELYLOOP_ES_VERSION RELYLOOP_OS_VERSION RELYLOOP_SOLR_VERSION; do
    # Shell env wins: a non-empty already-set value is left untouched.
    # (Indirect expansion `${!key}` is bash 3.2-safe.)
    [[ -n "${!key:-}" ]] && continue

    # Grab the LAST uncommented `KEY=` line (dotenv "last assignment wins").
    # `^[[:space:]]*KEY=` tolerates leading indentation but never matches a
    # commented `# KEY=...` line (the `#` is not whitespace). Requires no
    # space before `=`, matching Compose's own dotenv parser.
    local line
    line="$(grep -E "^[[:space:]]*${key}=" "$env_file" | tail -n 1)" || true
    [[ -z "$line" ]] && continue

    # Strip the leading `KEY=`.
    local val="${line#*=}"
    # Trim surrounding whitespace (leading + trailing).
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    # Strip one layer of matching surrounding quotes (Compose-like).
    if [[ ${#val} -ge 2 && ( "$val" == \"*\" || "$val" == \'*\' ) ]]; then
      val="${val:1:${#val}-2}"
    fi

    export "$key=$val"
  done
}
