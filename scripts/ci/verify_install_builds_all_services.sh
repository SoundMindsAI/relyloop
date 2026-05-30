#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# bug_install_skip_ui_rebuild regression gate.
#
# Asserts that scripts/install.sh's `docker compose build` invocation covers
# every Compose service that declares a `build:` block. Catches the silent-drift
# class of bug where a service is added to docker-compose.yml but the build
# step in install.sh isn't updated, leaving `make up` with a stale image on
# subsequent runs (the smoke job runs on a fresh runner so it never sees this
# failure mode — only the second-run-after-edit operator does).
#
# Accepts two forms:
#   1. `docker compose build`           — no args, builds everything; OK
#   2. `docker compose build a b c`     — explicit list; must include every
#                                          service with a `build:` block

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"
INSTALL_FILE="${REPO_ROOT}/scripts/install.sh"

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "verify_install_builds_all_services: ${COMPOSE_FILE} not found" >&2
  exit 2
fi
if [[ ! -f "${INSTALL_FILE}" ]]; then
  echo "verify_install_builds_all_services: ${INSTALL_FILE} not found" >&2
  exit 2
fi

# Extract services with a `build:` block. Service headers are top-level keys
# at 2-space indent; build configs sit at 4-space indent inside them.
buildable=$(awk '
  /^[a-z][a-z0-9_-]*:$/ { in_services = ($0 == "services:") ? 1 : 0; next }
  in_services && /^  [a-z][a-z0-9_-]*:$/ {
    svc = $1; sub(/:$/, "", svc); next
  }
  in_services && /^    build:/ { print svc }
' "${COMPOSE_FILE}" | sort -u)

if [[ -z "${buildable}" ]]; then
  echo "verify_install_builds_all_services: no buildable services found in ${COMPOSE_FILE}" >&2
  exit 2
fi

# Extract the `docker compose build [args...]` line from install.sh.
# Match the bare command line (no pipes, no &&) — we want the operative build
# step, not commentary or shell-substitution variants.
# Allow leading whitespace so the line can sit inside an `if [[ ... ]]; then`
# block (the RELYLOOP_SKIP_BUILD escape hatch added in PR #291 wraps the
# build call in a conditional). Indentation is irrelevant to the drift this
# gate exists to catch — what matters is that the buildable-service list
# matches whatever args the line carries.
build_line=$(grep -E '^[[:space:]]*docker compose build( .*)?$' "${INSTALL_FILE}" || true)

if [[ -z "${build_line}" ]]; then
  echo "verify_install_builds_all_services: no 'docker compose build' line found in ${INSTALL_FILE}" >&2
  echo "  Expected a top-level invocation that builds images before 'up -d'." >&2
  exit 1
fi

# Strip the prefix to get the args (if any). Also strip any leading whitespace
# carried in by the matched line so the args parse cleanly.
args=$(echo "${build_line}" | sed -E 's/^[[:space:]]*docker compose build *//')

if [[ -z "${args}" ]]; then
  echo "verify_install_builds_all_services: OK (no-args = builds all)"
  exit 0
fi

# Explicit list — every buildable service must appear in args.
missing=()
for svc in ${buildable}; do
  if ! grep -qE "(^| )${svc}( |$)" <<<"${args}"; then
    missing+=("${svc}")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "verify_install_builds_all_services: FAIL" >&2
  echo "  install.sh build invocation: 'docker compose build ${args}'" >&2
  echo "  Missing services: ${missing[*]}" >&2
  echo "  Fix: either add the missing services, or drop all args so the line" >&2
  echo "  becomes 'docker compose build' (which builds every service that" >&2
  echo "  declares a build: block — preferred, drift-proof)." >&2
  exit 1
fi

echo "verify_install_builds_all_services: OK (explicit list covers all buildable services)"
