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
  # `bin/solr auth enable-basic-auth` (which needs Solr already running),
  # plus an explicit anonymous allowlist for /admin/info/system.
  #
  # Solr's BasicAuthPlugin / Sha256AuthenticationProvider stores the
  # credential as:
  #     value = base64( sha256( sha256( salt_bytes || password ) ) )
  #             + " " + base64( salt_bytes )
  # NOTE the DOUBLE sha256 and that the salt is the RAW 32 bytes (not its
  # base64 text). Getting either wrong produces an admin user that can
  # never authenticate (every credentialed call 401s). See the Solr ref
  # guide "Basic Authentication Plugin" + Sha256AuthenticationProvider.
  if ! command -v openssl >/dev/null 2>&1; then
    echo "bootstrap-security.sh: openssl is required to hash the Solr admin password" >&2
    echo "  (the solr image must provide openssl; install it or pin a base image that has it)" >&2
    exit 1
  fi
  SALT_FILE="$(mktemp)"
  head -c 32 /dev/urandom > "${SALT_FILE}"
  SALT_B64="$(base64 < "${SALT_FILE}" | tr -d '\n')"
  # sha256(salt_bytes || password) -> raw digest -> sha256 again -> base64.
  HASH="$(
    { cat "${SALT_FILE}"; printf '%s' "${SOLR_PASS}"; } \
      | openssl dgst -sha256 -binary \
      | openssl dgst -sha256 -binary \
      | base64 | tr -d '\n'
  )"
  rm -f "${SALT_FILE}"
  cat > "${SECURITY_FILE}" <<EOF
{
  "authentication": {
    "blockUnknown": true,
    "class": "solr.BasicAuthPlugin",
    "credentials": {
      "${SOLR_USER}": "${HASH} ${SALT_B64}"
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
