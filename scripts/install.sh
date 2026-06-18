#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# RelyLoop install script (infra_foundation Story 4.4 / FR-3).
#
# Auto-generates the required + placeholder secret files mounted by Compose,
# validates the Compose config, then runs `docker compose up -d`. Idempotent:
# re-running does NOT regenerate or overwrite existing secret content.
#
# CLAUDE.md Absolute Rule #2: secrets live in mounted files (./secrets/<name>),
# never as bare env vars. Compose's `secrets:` directive errors out at startup
# if a source file is missing — even for "optional" secrets — so we create
# zero-byte placeholders for openai_key. The application layer (Pydantic
# Settings) treats empty content as "not configured". GitHub PATs are NOT
# global: each ``config_repos`` row carries its own ``auth_ref`` field naming
# a ``./secrets/<auth_ref>`` file, registered via POST /api/v1/config-repos.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# 0. Load the RELYLOOP_* install-time vars from .env (if present).
#    install.sh reads RELYLOOP_ENGINES + RELYLOOP_{ES,OS,SOLR}_VERSION from the
#    shell environment (the parse helpers below default `${RELYLOOP_*:-...}`),
#    but nothing else sources .env — so without this the documented
#    "set RELYLOOP_ENGINES in .env" path silently defaulted to all engines.
#    Selective extraction of ONLY the four known keys (never blind-sources
#    .env, which can hold proxy URLs / CSV no_proxy lists bash would
#    mis-parse). Shell env wins over .env: `RELYLOOP_ENGINES=es make up`
#    still beats a `.env` value. Defined in scripts/lib/relyloop_env_file.sh
#    so it is unit-testable in isolation
#    (scripts/ci/test_load_relyloop_env_file.sh).
# shellcheck source=lib/relyloop_env_file.sh
source "${REPO_ROOT}/scripts/lib/relyloop_env_file.sh"
load_relyloop_env_file "${REPO_ROOT}/.env"

# 1. Ensure ./secrets/ exists.
mkdir -p ./secrets

# 2. Generate postgres_password if missing or empty.
if [[ ! -s ./secrets/postgres_password ]]; then
  echo "Generating ./secrets/postgres_password (random base64)..."
  openssl rand -base64 32 | tr -d '\n' > ./secrets/postgres_password
  chmod 600 ./secrets/postgres_password
fi

# 3. Generate database_url if missing, empty, OR using a non-asyncpg driver.
#    The app reads this URL via SQLAlchemy; without `+asyncpg` the default
#    psycopg2 dialect is selected and the async event loop blocks on sync
#    DB-API calls (or, if psycopg2 isn't installed, ModuleNotFoundError at
#    /healthz). The early prefix-check catches stale stub files left behind
#    by manual `docker compose config` testing — a real bug surfaced during
#    PR #4 first-run testing.
if [[ ! -s ./secrets/database_url ]] || ! grep -q '^postgresql+asyncpg://' ./secrets/database_url; then
  echo "Generating ./secrets/database_url (asyncpg driver)..."
  PASSWORD="$(cat ./secrets/postgres_password)"
  printf 'postgresql+asyncpg://relyloop:%s@postgres/relyloop' "${PASSWORD}" \
    > ./secrets/database_url
  chmod 600 ./secrets/database_url
fi

# 4. Create empty placeholder files for optional secrets (Compose mounts them).
[[ -e ./secrets/openai_key ]]     || { touch ./secrets/openai_key;     chmod 600 ./secrets/openai_key;     }
# Optional corporate CA certificate (PEM format). Empty placeholder so
# Compose's `secrets:` block doesn't fail at startup; operators behind a
# corp HTTPS-interception proxy replace this with their real CA cert.
# See docs/03_runbooks/corporate-network-install.md.
[[ -e ./secrets/corp_ca.crt ]]    || { touch ./secrets/corp_ca.crt;    chmod 600 ./secrets/corp_ca.crt;    }
if [[ ! -e ./secrets/cluster_credentials.yaml ]]; then
  # Seed default credentials for the local Compose ES + OpenSearch + Solr
  # containers (well-known dev defaults — not production secrets). The
  # seed-clusters script (`make seed-clusters`) reads these refs to register
  # the three containers as cluster rows. Operators add real production
  # credentials by editing this file before `make seed-clusters` for
  # non-local clusters.
  #
  # All three local engines run security-disabled (see docker-compose.yml),
  # so these credentials are never actually checked — the adapter sends an
  # Authorization header the engine ignores. They exist only so the
  # credentials_ref resolution succeeds with a well-formed entry.
  cat > ./secrets/cluster_credentials.yaml <<'CLUSTER_CREDS_EOF'
local-es:
  username: elastic
  password: changeme
local-opensearch:
  username: admin
  password: admin
local-solr:
  username: solr
  password: solr
CLUSTER_CREDS_EOF
  chmod 600 ./secrets/cluster_credentials.yaml
fi

# 5a. Backfill the local-solr credentials entry into a PRE-EXISTING
#     cluster_credentials.yaml. The block above only writes the file when it
#     doesn't exist, so operators whose file predates the Solr feature
#     (local-es + local-opensearch only) would otherwise hit
#     `credentials_ref 'local-solr' not found` when `make seed-clusters` /
#     `make seed-demo` tries to register the local-solr cluster. Append the
#     entry idempotently if the key is absent.
if [[ -s ./secrets/cluster_credentials.yaml ]] && ! grep -q '^local-solr:' ./secrets/cluster_credentials.yaml; then
  echo "Backfilling local-solr entry into existing ./secrets/cluster_credentials.yaml..."
  printf '\nlocal-solr:\n  username: solr\n  password: solr\n' >> ./secrets/cluster_credentials.yaml
fi

# 5. Parse RELYLOOP_ENGINES into COMPOSE_PROFILES.
#
# feat_selective_engine_startup_and_demo Story 1.1. The three engine
# services (elasticsearch, opensearch, solr) carry `profiles:` blocks in
# docker-compose.yml; Compose treats unprofiled services as always-on and
# profiled services as opt-in. To preserve the current default (all three
# engines start on `make up`), the helper sourced below defaults
# RELYLOOP_ENGINES to `es,os,solr` when unset OR empty, then exports the
# resolved value as COMPOSE_PROFILES for every `docker compose` call below
# (config, build, up).
#
# Operators who want a single-engine evaluation set `RELYLOOP_ENGINES=es`
# (or any comma-separated subset) in `.env` — the unselected engines are
# never pulled or started, dramatically reducing first-run wall-clock.
#
# The function is defined in scripts/lib/relyloop_engines.sh so it can be
# unit-tested in isolation (scripts/ci/test_parse_relyloop_engines.sh)
# without install.sh's top-level secrets generation running.
# shellcheck source=lib/relyloop_engines.sh
source "${REPO_ROOT}/scripts/lib/relyloop_engines.sh"
# The lib's `return 1` on unknown engines bubbles up to `exit 1` here
# because install.sh runs under `set -e`.
parse_relyloop_engines

# 5b. Parse RELYLOOP_{ES,OS,SOLR}_VERSION into *_IMAGE_TAG exports.
#
# feat_engine_version_selection Story 1.3. The three engine services in
# docker-compose.yml interpolate `image: …:${X_IMAGE_TAG:-<default>}` so
# operators can pin to any maintainer-curated supported version (matrix
# at backend/app/core/engine_versions.py). The helper sourced below
# validates each set RELYLOOP_*_VERSION value against the matrix BEFORE
# any `docker compose pull` so unauthorized registry calls never happen.
# Unset / empty → no export, Compose's `:-` default applies (back-compat).
#
# The function is defined in scripts/lib/relyloop_engine_versions.sh so
# it can be unit-tested in isolation
# (scripts/ci/test_parse_relyloop_engine_versions.sh).
# shellcheck source=lib/relyloop_engine_versions.sh
source "${REPO_ROOT}/scripts/lib/relyloop_engine_versions.sh"
# The helper's `return 1` on unknown versions bubbles up to `exit 1`
# under install.sh's `set -e`.
parse_relyloop_engine_versions

# 6. Validate Compose config (catches typos before pulling images).
docker compose config --quiet

# 7. Build images locally. `docker compose up -d` does NOT auto-rebuild after
#    code changes — it uses the cached `relyloop/api:dev` tag. Without an
#    explicit build step, contributors who pull new code and re-run `make up`
#    keep running the stale image (PR #4 first-run testing surfaced exactly
#    this — a stale image missing newly-added Python deps).
#    No-args = build every service that declares a `build:` block. The earlier
#    hardcoded `api worker` list silently skipped the `ui` service after it
#    joined Compose, leaving frontend changes invisible until manual rebuild.
#
#    CI escape hatch: set `RELYLOOP_SKIP_BUILD=1` to skip this step. CI pre-
#    builds the API + UI images in parallel `docker` + `docker-ui` jobs and
#    `docker load`s them before calling `make up`, so a second `docker compose
#    build` here would be ~3-5min of pure duplication. See
#    chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md.
# ----------------------------------------------------------------------
# Build-failure diagnostic wrapper.
# ----------------------------------------------------------------------
# `docker compose build` errors are produced by whichever tool inside the
# Dockerfile broke (npm, uv, apt, BuildKit). Their messages are technically
# correct but operationally useless — "SELF_SIGNED_CERT_IN_CHAIN" from npm
# does not tell a developer to drop a corp CA cert at ./secrets/corp_ca.crt.
# This wrapper captures the build output, and on failure scans it for known
# corp-network failure signatures, then prints an actionable diagnostic
# pointing at the specific runbook section. Fail-open: if no pattern
# matches, prints a generic pointer at the troubleshooting runbook.
# ----------------------------------------------------------------------

diagnose_build_failure() {
  local log="$1"
  local matched=0

  printf '\n' >&2
  printf '==========================================================\n' >&2
  printf '  Build failed - analyzing common corp-network causes\n' >&2
  printf '==========================================================\n' >&2

  # Pattern 1 - TLS interception (corp HTTPS proxy with internal CA)
  if grep -qE \
      'SELF_SIGNED_CERT_IN_CHAIN|self-signed certificate in certificate chain|unable to get local issuer certificate|CERTIFICATE_VERIFY_FAILED|certificate verify failed|x509: certificate signed by unknown' \
      "$log"; then
    cat >&2 <<'TLS_HINT'

  Detected: TLS interception (corporate HTTPS proxy with internal CA)

  Your corporate HTTPS proxy is intercepting traffic with an internal CA
  that the container does not trust. This breaks every HTTPS tool in the
  build (npm, pnpm, uv, pip, curl, the runtime OpenAI/GitHub clients).

  Fix:  run 'make corp-ca-extract' - it probes the live TLS chain and
        saves the corp root CA to ./secrets/corp_ca.crt automatically.
        Then re-run 'make up'.

  Fallback (rare): if 'make corp-ca-extract' picks the wrong cert (e.g.,
  your proxy doesn't include the root in the chain it serves), drop
  your PEM-format corporate CA cert at ./secrets/corp_ca.crt manually
  and re-run 'make up'.

  Docs: docs/03_runbooks/corporate-network-install.md
        Section: "TLS verification errors"

TLS_HINT
    matched=1
  fi

  # Pattern 2 - Registry blocked (BASE_REGISTRY / GHCR_REGISTRY not set
  # or set to a path that doesn't host the image)
  if grep -qE \
      'failed to resolve source metadata for docker\.io|registry-1\.docker\.io.*(401|403)|no such host: registry-1\.docker\.io|no such host: ghcr\.io' \
      "$log"; then
    cat >&2 <<'REGISTRY_HINT'

  Detected: Container registry blocked

  Your network is blocking direct access to docker.io or ghcr.io. If you
  are behind a corporate proxy (Artifactory, Nexus, Harbor, etc.), set
  these in your .env (trailing slash required):

    BASE_REGISTRY=<your-proxy>/
    GHCR_REGISTRY=<your-proxy>/

  Then re-run 'make up'. If only one of the registries is blocked, set
  just that one.

  Docs: docs/03_runbooks/corporate-network-install.md
        Section: "Registry pull failures"

REGISTRY_HINT
    matched=1
  fi

  # Pattern 3 - HTTP egress / DNS failures (apt/pip/npm can't reach upstream)
  if grep -qE \
      'Could not resolve host|Temporary failure resolving|dial tcp.*no such host|Connection refused|Connection timed out|ETIMEDOUT|ECONNREFUSED' \
      "$log"; then
    cat >&2 <<'PROXY_HINT'

  Detected: Outbound HTTP blocked (apt / PyPI / npm cannot reach upstream)

  Build steps cannot reach external package repos. If you are behind an
  HTTP proxy, set these in your .env:

    http_proxy=http://<proxy-host>:<port>
    https_proxy=http://<proxy-host>:<port>
    no_proxy=<your-corp-domains>,localhost,127.0.0.1,host.docker.internal,postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate

  The 'no_proxy' Compose-service-names list is REQUIRED to prevent
  internal cross-container HTTP from being routed to the proxy.

  Docs: docs/03_runbooks/corporate-network-install.md
        Section: "Egress / DNS failures"

PROXY_HINT
    matched=1
  fi

  if [[ "$matched" -eq 0 ]]; then
    cat >&2 <<'GENERIC_HINT'

  Could not auto-diagnose from the build output. See:

    docs/03_runbooks/corporate-network-install.md   (corp-network FAQ)
    docs/03_runbooks/local-dev.md                   (general troubleshooting)
                                                    Section: "Stack will not start"

GENERIC_HINT
  fi

  printf '==========================================================\n' >&2
  printf '\n' >&2
}

# Wrapped in a function so the actual `docker compose build` invocation sits
# on a bare line (no `if !` prefix, no pipes, no args). This is required by
# scripts/ci/verify_install_builds_all_services.sh's regex
# (`^[[:space:]]*docker compose build( .*)?$`) which enforces that the
# invocation either has no args (drift-proof — builds every buildable
# service) or explicitly lists every one. The wrapper-with-pipe is
# necessary to capture build output for the diagnostic, but the guard
# only inspects the bare command line in the function body.
do_compose_build() {
  docker compose build
}

if [[ "${RELYLOOP_SKIP_BUILD:-0}" != "1" ]]; then
  build_log="$(mktemp)"
  # trap EXIT guarantees cleanup on success, failure, OR signal (Ctrl-C
  # during a 5-minute uv sync). Adopted per Gemini #523 review (the bot's
  # exact suggestion regressed the function wrapper required by the
  # verify_install_builds_all_services CI guard — see commit f34a278e).
  trap 'rm -f "$build_log"' EXIT
  # set -e + pipefail (line 21) would normally abort the script on a
  # pipeline failure; the '|| build_status=$?' tail captures the exit so
  # we can run the diagnostic before exiting. PIPESTATUS[0] is the actual
  # function/build exit (tee is always 0 unless the log write fails).
  build_status=0
  do_compose_build 2>&1 | tee "$build_log" || build_status=$?
  if [[ "${PIPESTATUS[0]}" -ne 0 || "${build_status}" -ne 0 ]]; then
    diagnose_build_failure "$build_log"
    exit 1
  fi
else
  echo "RELYLOOP_SKIP_BUILD=1 set — skipping 'docker compose build' (CI artifact-handoff path)"
fi

# 7c. Pre-create the Solr data directory so its bind mount resolves to a real
#     host path. The solr image runs as UID/GID 8983 and writes each
#     collection's core data under /var/solr/data (bind-mounted from
#     ./data/solr — docker-compose.yml). When ./data/solr does NOT exist on the
#     host (fresh clone, or after `make reset` wipes ./data), Docker's
#     bind-mount-of-a-missing-source yields a mount the Solr process cannot
#     create children in, so every collection CREATE fails with "Underlying
#     core creation failed" / "Couldn't persist core properties" and the demo
#     reseed's Solr scenario dies. Mirrors the pr.yml smoke job's pre-create
#     step. On Linux the bind mount preserves host UIDs, so a chown to 8983 is
#     required for the container to write; on Docker Desktop (macOS/Windows)
#     ownership is virtualized and the mkdir alone suffices (a chown there
#     would needlessly prompt for sudo).
#     bug_reseed_resolve_engine_base_url_not_idempotent_in_container.
if [[ ",${COMPOSE_PROFILES:-es,os,solr}," == *",solr,"* ]]; then
  mkdir -p ./data/solr
  if [[ "$(uname -s)" == "Linux" && "$(stat -c '%u' ./data/solr 2>/dev/null)" != "8983" ]]; then
    chown 8983:8983 ./data/solr 2>/dev/null \
      || sudo chown 8983:8983 ./data/solr 2>/dev/null \
      || echo "WARN: could not chown ./data/solr to 8983:8983. If Solr fails to create collections, run: sudo chown -R 8983:8983 ./data/solr" >&2
  fi
fi

# 8. Bring the stack up. `docker compose up -d` is itself idempotent.
#    `--wait` blocks until every container's healthcheck passes (or fails) —
#    needed by step 8 below, which runs the seed against a healthy stack.
docker compose up -d --wait

# 9. Auto-seed meaningful demo data when the stack is empty (idempotent —
#    `--if-empty` is a no-op when clusters already exist, so re-running
#    `make up` against a populated stack preserves operator-mutable state).
#    Fixes the first-run UX where `make up` would land the operator on an
#    empty stack with no path to create a meaningful study until they
#    discovered `make seed-demo` on their own. Operators who explicitly
#    want to wipe + reseed still call `make seed-demo FORCE=1`.
#
#    The auto-seed is non-fatal: a failure here doesn't roll back the
#    stack startup. The operator can re-run `make seed-demo FORCE=1`
#    manually once the failure is understood.
#
#    CI escape hatch: set `RELYLOOP_SKIP_AUTO_SEED=1` to skip this step.
#    The smoke job sets this because the dashboard E2E specs that needed
#    the demo data were skipped in CI on 2026-05-28 (see
#    chore_drop_demo_seed_from_ci/idea.md). Without the skip, install.sh
#    would do ~5min of demo-seeding inside `make up` that no CI step
#    consumes. See chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md.
if [[ "${RELYLOOP_SKIP_AUTO_SEED:-0}" != "1" ]]; then
  echo "Checking demo state…"
  # Run inside the api container (Python 3.13 from the project Dockerfile)
  # rather than on the host. The host's `python3` may be a system version
  # too old (macOS Xcode CommandLineTools ships Python 3.9, missing
  # `datetime.UTC` from 3.11+). The script is bind-mounted into the api
  # container at /app/scripts/ via docker-compose.yml; the container's
  # `python` resolves to /app/.venv/bin/python via the Dockerfile's ENV
  # PATH, so the venv is active. `-T` disables TTY allocation for
  # non-interactive scripted use.
  if ! docker compose exec -T api python /app/scripts/seed_meaningful_demos.py --if-empty; then
    echo "Warning: auto-seed failed (non-fatal). Run 'make seed-demo FORCE=1' manually."
  fi
else
  echo "RELYLOOP_SKIP_AUTO_SEED=1 set — skipping demo auto-seed (CI fast path)"
fi
