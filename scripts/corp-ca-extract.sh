#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Auto-extract the corporate root CA cert from the live TLS chain.
#
# When a corp HTTPS proxy performs TLS interception, the cert chain it
# presents to clients includes the corp root CA (the trust anchor it used
# to sign the re-encrypted chain). This script:
#
#   1. Probes a public HTTPS endpoint via `openssl s_client`.
#   2. Walks the returned cert chain.
#   3. Saves the LAST cert in the chain to ./secrets/corp_ca.crt (typically
#      the corp root CA — the cert the proxy signed everything else with).
#
# Heuristics + escape hatches:
#   - If the last cert looks like a well-known public root (DigiCert, ISRG,
#     etc.), the script aborts with a "no MITM detected" message — your
#     network probably is not behind an intercepting proxy.
#   - If the chain has only one cert (the server cert with no roots
#     presented), we report what we found and exit non-zero.
#   - Override PROBE_HOST / PROBE_PORT / TARGET via env vars.
#
# Usage:
#   make corp-ca-extract
#   bash scripts/corp-ca-extract.sh                 # equivalent
#   PROBE_HOST=internal.your-corp.com bash scripts/corp-ca-extract.sh
#   TARGET=/tmp/my-corp-ca.crt bash scripts/corp-ca-extract.sh
#
# After successful extraction, `make up` reads ./secrets/corp_ca.crt at
# build time via a BuildKit secret and installs it into the system trust
# store. See docs/03_runbooks/corporate-network-install.md.

set -euo pipefail

PROBE_HOST="${PROBE_HOST:-www.google.com}"
PROBE_PORT="${PROBE_PORT:-443}"

# Defensive cleanup: operators frequently paste a full URL or host:port
# (e.g., PROBE_HOST=https://internal.corp/ or PROBE_HOST=internal.corp:8443).
# Strip scheme + path; extract embedded port into PROBE_PORT.
PROBE_HOST="${PROBE_HOST#http://}"
PROBE_HOST="${PROBE_HOST#https://}"
PROBE_HOST="${PROBE_HOST%%/*}"
if [[ "${PROBE_HOST}" == *:* ]]; then
  PROBE_PORT="${PROBE_HOST##*:}"
  PROBE_HOST="${PROBE_HOST%%:*}"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${TARGET:-${REPO_ROOT}/secrets/corp_ca.crt}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl is required but not installed." >&2
  echo "  macOS:  openssl ships with the system (or 'brew install openssl')." >&2
  echo "  Linux:  apt-get install openssl  (or yum install openssl)." >&2
  exit 1
fi

echo "Probing https://${PROBE_HOST}:${PROBE_PORT} for the cert chain ..."

# If an HTTPS proxy is configured (the typical corp setup — and the whole
# audience for this script), route the openssl probe through it via the
# `-proxy` flag. Without this, strict corp firewalls that block direct
# outbound 443 won't let the probe out at all. Only added when openssl
# supports `-proxy` (LibreSSL on macOS predates this in some versions).
proxy_args=()
active_proxy="${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}"
if [[ -n "${active_proxy}" ]] && openssl s_client -help 2>&1 | grep -q -- "-proxy"; then
  proxy_host_port="${active_proxy#http://}"
  proxy_host_port="${proxy_host_port#https://}"
  proxy_host_port="${proxy_host_port%%/*}"
  proxy_args=(-proxy "${proxy_host_port}")
  echo "  (routing through HTTPS proxy: ${proxy_host_port})"
fi
echo ""

# Capture the chain. `</dev/null` makes s_client exit after the handshake;
# `2>/dev/null` swallows the verbose connection log. `tr -d '\r'` strips
# any CRLF line endings so the awk + shell pattern comparisons below
# anchor correctly on Windows/WSL/old-openssl streams.
chain_pem="$(openssl s_client -showcerts \
              ${proxy_args[@]+"${proxy_args[@]}"} \
              -connect "${PROBE_HOST}:${PROBE_PORT}" \
              -servername "${PROBE_HOST}" \
              </dev/null 2>/dev/null \
            | tr -d '\r' \
            | awk '/-----BEGIN CERTIFICATE-----/,/-----END CERTIFICATE-----/' \
            || true)"

if [[ -z "${chain_pem}" ]]; then
  echo "ERROR: Could not retrieve any certs from ${PROBE_HOST}:${PROBE_PORT}." >&2
  echo "  Possible causes:" >&2
  echo "    - The host is unreachable from your network." >&2
  echo "    - The proxy is blocking outbound HTTPS entirely." >&2
  echo "    - openssl s_client is too old to support TLS 1.3." >&2
  echo "  Try a different host:  PROBE_HOST=internal.your-corp.com $0" >&2
  exit 1
fi

# Split the chain into individual cert files in a tmpdir.
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

cert_count=0
in_cert=0
cur=""
while IFS= read -r line; do
  if [[ "${line}" == "-----BEGIN CERTIFICATE-----" ]]; then
    in_cert=1
    cur="${line}"$'\n'
    continue
  fi
  if [[ "${in_cert}" -eq 1 ]]; then
    cur+="${line}"$'\n'
    if [[ "${line}" == "-----END CERTIFICATE-----" ]]; then
      cert_file="${tmpdir}/cert-$(printf '%03d' "${cert_count}").pem"
      printf '%s' "${cur}" > "${cert_file}"
      cert_count=$((cert_count + 1))
      in_cert=0
      cur=""
    fi
  fi
done <<< "${chain_pem}"

if [[ "${cert_count}" -eq 0 ]]; then
  echo "ERROR: Parsed 0 certs from the chain output." >&2
  exit 1
fi

echo "Found ${cert_count} cert(s) in the chain:"
echo ""

# Print all certs in the chain with subject + issuer so the operator can
# verify which one was identified as the corp root.
i=0
last_cert=""
for cert_file in "${tmpdir}"/cert-*.pem; do
  subject="$(openssl x509 -in "${cert_file}" -noout -subject 2>/dev/null | sed 's/^subject=[ ]*//')"
  issuer="$(openssl x509 -in "${cert_file}" -noout -issuer 2>/dev/null | sed 's/^issuer=[ ]*//')"
  printf '  [%d] %s\n' "${i}" "$(basename "${cert_file}")"
  printf '      Subject: %s\n' "${subject}"
  printf '      Issuer:  %s\n' "${issuer}"
  echo ""
  last_cert="${cert_file}"
  i=$((i + 1))
done

# Inspect the last cert (typically the root used to sign the chain).
last_subject="$(openssl x509 -in "${last_cert}" -noout -subject 2>/dev/null | sed 's/^subject=[ ]*//')"
last_subject_lower="$(echo "${last_subject}" | tr '[:upper:]' '[:lower:]')"

# Heuristic: if the LAST cert in the chain looks like a well-known PUBLIC
# root CA, there is no corp MITM happening. Abort.
public_root_patterns=(
  "digicert"
  "let's encrypt"
  "isrg root"
  "globalsign"
  "sectigo"
  "baltimore cybertrust"
  "verisign"
  "comodo"
  "entrust"
  "amazon root ca"
  "google trust services"
  "microsoft rsa"
  "microsoft ecc"
  "starfield"
  "go daddy"
  "usertrust"
  "wo sign"
  "geotrust"
  "thawte"
  "rapidssl"
  "addtrust"
  "quovadis"
  "actalis"
  "trustcor"
  "buypass"
  "swisssign"
  "certum"
)

for pat in "${public_root_patterns[@]}"; do
  if [[ "${last_subject_lower}" == *"${pat}"* ]]; then
    echo "==========================================================="
    echo "  No corporate TLS interception detected."
    echo "==========================================================="
    echo ""
    echo "  The root cert at the end of the chain is a known PUBLIC CA:"
    echo "    ${last_subject}"
    echo ""
    echo "  This means your network is NOT MITM-ing TLS traffic — you do"
    echo "  not need a corporate CA cert in ./secrets/corp_ca.crt."
    echo ""
    echo "  If you DO know you are behind a corp proxy, the proxy may be"
    echo "  configured to relay traffic without re-signing (transparent"
    echo "  proxying). In that case, no cert install is needed."
    echo ""
    echo "  If your build still fails with TLS errors, try a different"
    echo "  probe host:  PROBE_HOST=registry.npmjs.org bash $0"
    echo ""
    exit 0
  fi
done

# Last cert is NOT a known public root → likely the corp CA. Save it.
echo "==========================================================="
echo "  Corporate CA detected at end of chain — saving."
echo "==========================================================="
echo ""
echo "  Subject:    ${last_subject}"
echo "  Saving to:  ${TARGET}"
echo ""

mkdir -p "$(dirname "${TARGET}")"

# If the target already has content AND it matches the new cert exactly,
# don't churn the file's mtime — operators may have set up the cert by hand.
if [[ -s "${TARGET}" ]] && cmp -s "${last_cert}" "${TARGET}"; then
  echo "  (Existing file matches — no change.)"
else
  cp "${last_cert}" "${TARGET}"
  chmod 600 "${TARGET}"
  echo "  ✓ Saved."
fi

echo ""
echo "Next step:  run 'make up'."
echo ""
echo "The cert will be installed into the image's system trust store"
echo "during 'docker compose build' so every HTTPS tool in the container"
echo "(npm, pnpm, uv, pip, curl, runtime OpenAI/GitHub/cluster clients)"
echo "trusts it."
echo ""
echo "If the wrong cert was picked, edit ${TARGET} manually (e.g., copy"
echo "your corp root CA from /usr/local/share/ca-certificates/ on Linux"
echo "or extract it from the macOS keychain — see the runbook at"
echo "docs/03_runbooks/corporate-network-install.md §2)."
