#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap script for the Solr container (infra_adapter_solr Story A10).
#
# 1. Reads the SOLR_ADMIN_USERNAME / PASSWORD from the *_FILE-mounted Docker
#    secrets per CLAUDE.md Absolute Rule #2 (no bare env-var secrets).
# 2. On FIRST boot (no security.json yet), invokes `bin/solr auth enable-basic-auth`
#    with -blockUnknown true and patches the generated security.json to allowlist
#    /admin/info/system anonymously (so /healthz can probe reachability without
#    credentials per spec FR-3 + FR-11).
# 3. Hands off to the standard solr-foreground entrypoint via exec so PID 1
#    becomes Solr itself (graceful signal handling).
#
# Idempotent: subsequent boots see the persisted security.json and skip the
# `auth enable-basic-auth` step.

set -euo pipefail

SOLR_HOME="${SOLR_HOME:-/var/solr/data}"
SECURITY_FILE="${SOLR_HOME}/security.json"

if [[ -z "${SOLR_ADMIN_USERNAME_FILE:-}" || -z "${SOLR_ADMIN_PASSWORD_FILE:-}" ]]; then
  echo "bootstrap-security.sh: SOLR_ADMIN_USERNAME_FILE and SOLR_ADMIN_PASSWORD_FILE must be set" >&2
  exit 1
fi

if [[ ! -r "${SOLR_ADMIN_USERNAME_FILE}" || ! -r "${SOLR_ADMIN_PASSWORD_FILE}" ]]; then
  echo "bootstrap-security.sh: secret files unreadable; check mounts" >&2
  exit 1
fi

SOLR_USER="$(tr -d '\n' < "${SOLR_ADMIN_USERNAME_FILE}")"
SOLR_PASS="$(tr -d '\n' < "${SOLR_ADMIN_PASSWORD_FILE}")"

if [[ -z "${SOLR_USER}" || -z "${SOLR_PASS}" ]]; then
  echo "bootstrap-security.sh: empty username or password" >&2
  exit 1
fi

# Ensure the data dir exists with the right ownership before Solr starts.
mkdir -p "${SOLR_HOME}"

if [[ ! -s "${SECURITY_FILE}" ]]; then
  echo "bootstrap-security.sh: first-boot security.json install"
  # We assemble security.json directly rather than relying on
  # `bin/solr auth enable-basic-auth` since the latter requires Solr to be
  # running. Output mirrors what `enable-basic-auth -blockUnknown true`
  # produces, plus an explicit anonymous allowlist for /admin/info/system.
  #
  # Solr hashes BasicAuth passwords with PBKDF2 — we use the same form the
  # bundled CLI emits (`SHA-256(salt + password)` base64'd).
  SALT="$(head -c 32 /dev/urandom | base64)"
  HASH="$(printf '%s' "${SALT}${SOLR_PASS}" | openssl dgst -sha256 -binary | base64)"
  cat > "${SECURITY_FILE}" <<EOF
{
  "authentication": {
    "blockUnknown": true,
    "class": "solr.BasicAuthPlugin",
    "credentials": {
      "${SOLR_USER}": "${HASH} ${SALT}"
    },
    "realm": "RelyLoop Solr",
    "forwardCredentials": false
  },
  "authorization": {
    "class": "solr.RuleBasedAuthorizationPlugin",
    "permissions": [
      { "name": "all", "role": "admin" },
      { "name": "open-info-system", "path": "/admin/info/system", "role": null }
    ],
    "user-role": {
      "${SOLR_USER}": "admin"
    }
  }
}
EOF
  chmod 600 "${SECURITY_FILE}"
else
  echo "bootstrap-security.sh: security.json already present — skipping"
fi

# Hand off to the standard solr-foreground entrypoint.
exec docker-entrypoint.sh solr-foreground
