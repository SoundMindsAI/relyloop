# RelyLoop API + worker image (infra_foundation Story 4.1).
#
# Multi-stage build:
#   1. base    — install Python + curl + uv (uv is the package manager)
#   2. deps    — sync runtime dependencies into /app/.venv from pyproject + uv.lock
#   3. runtime — copy app code + venv into a minimal runtime; non-root user;
#                inject RELYLOOP_GIT_SHA via build-arg.
#
# The same image powers the `api` and `worker` Compose services; the only
# difference is the command (`uvicorn` vs `arq`).
#
# Per docs/01_architecture/deployment.md §"MVP1 deployment shape" + the
# implementation_plan.md Story 4.1 "Decision rationale".
#
# ---------------------------------------------------------------------------
# Registry-prefix ARGs for corporate proxies (e.g., Artifactory).
# ---------------------------------------------------------------------------
# Defaults are EMPTY for Docker Hub and `ghcr.io/` for GHCR — so an unmodified
# build behaves exactly as before (and OSSF Scorecard's PinnedDependencies
# check still credits the inline `image@sha256:…` pins below; only the
# registry prefix is ARG-indirected, never the digest).
#
# Override examples:
#   # Single proxy fronting both Docker Hub and GHCR (typical Artifactory):
#   docker build \
#     --build-arg BASE_REGISTRY=artifactory.example.com/ \
#     --build-arg GHCR_REGISTRY=artifactory.example.com/ \
#     -t relyloop/api:dev .
#
#   # Separate proxies per upstream:
#   docker build \
#     --build-arg BASE_REGISTRY=docker.proxy.corp/ \
#     --build-arg GHCR_REGISTRY=ghcr.proxy.corp/ \
#     -t relyloop/api:dev .
#
# Trailing slash is REQUIRED on non-empty values — the FROM/COPY lines
# concatenate `${BASE_REGISTRY}python:…` without a separator.
ARG BASE_REGISTRY=
ARG GHCR_REGISTRY=ghcr.io/

# ---------------------------------------------------------------------------
# Corporate HTTP proxy — handled via BuildKit predefined ARGs + Compose
# `environment:`, NOT via Dockerfile ARG/ENV.
# ---------------------------------------------------------------------------
# Docker treats `http_proxy`, `https_proxy`, `no_proxy`, and their UPPERCASE
# siblings as **predefined ARGs**: BuildKit forwards them from `--build-arg`
# into every RUN step's environment automatically — no `ARG` declaration
# needed — and intentionally excludes them from `docker history` so the proxy
# URL never gets baked into the image. The `build.args:` block in
# `docker-compose.yml` is wired through; runtime egress is handled
# separately via each service's `environment:` block (also in
# docker-compose.yml). Override via `.env` or shell:
#
#   http_proxy=http://http.proxy.your-corp.com:8000
#   https_proxy=http://http.proxy.your-corp.com:8000
#   no_proxy=your-corp.com,.your-corp-cloud.com,localhost,127.0.0.1,
#            10.0.0.0/8,169.254.169.254,host.docker.internal,
#            postgres,redis,elasticsearch,opensearch,solr,api,worker,migrate
#
# IMPORTANT — `no_proxy` MUST include the Compose service names
# (postgres / redis / elasticsearch / opensearch / solr / api / worker /
# migrate) AND `host.docker.internal`. Without the Compose names, the
# worker's call to `http://elasticsearch:9200` (and similar in-network HTTP)
# gets routed to the corporate proxy, which has no path to those
# Compose-internal hostnames. Without `host.docker.internal`, local-LLM dev
# (Ollama / LM Studio / vLLM via `OPENAI_BASE_URL=http://host.docker.internal:…`)
# breaks. The recommended `.env.example` value bakes both in.

# ---------------------------------------------------------------------------
# Stage 1 — base: Python + uv + system deps for healthcheck (curl)
# ---------------------------------------------------------------------------
# python:3.14-slim, digest-pinned (PinnedDependencies / OSSF Scorecard). The
# digest is written literally on the FROM (not via an ARG) because Scorecard's
# static parser only credits a pin it can see inline as `image@sha256:…`; an
# ARG-indirected digest reads as "unpinned". Writing the tag + digest together
# also removes the override footgun of a separate version/digest pair (the
# digest would silently win over a changed tag). Dependabot's docker ecosystem
# bumps the tag + digest together; refresh both when bumping Python. The
# `${BASE_REGISTRY}` prefix is the ONLY ARG-indirected part of the reference
# — Scorecard still sees `python:3.14-slim@sha256:…` and credits the pin.

# Alias the upstream uv image as a named stage so the COPY --from= below can
# reference it by stage name. Going through an aliased FROM (where ARG
# substitution is fully supported) instead of `COPY --from=${GHCR_REGISTRY}…`
# (where buildx's parser treats the ARG literally and rejects the reference
# as "invalid reference format") is the canonical workaround. Scorecard
# still credits the inline digest pin on this FROM line.
FROM ${GHCR_REGISTRY}astral-sh/uv:0.5.7@sha256:23272999edd22e78195509ea3fe380e7632ab39a4c69a340bedaba7555abe20a AS uv-source

FROM ${BASE_REGISTRY}python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS base

# UV_NATIVE_TLS=1: uv ships its OWN bundled root certificates (webpki-roots)
# and does NOT read the OpenSSL system trust store by default, so the corp CA
# installed via `update-ca-certificates` below would be invisible to `uv sync`
# (it would still fail with a TLS / self-signed-cert error behind a
# TLS-intercepting corp proxy). Enabling native TLS makes uv use the platform
# trust store, which now includes the appended corp CA. Harmless for OSS users
# — the native store already contains the public roots uv would otherwise use.
# See docs/03_runbooks/corporate-network-install.md.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_NATIVE_TLS=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# curl is required by the Compose API healthcheck (curl -fs /healthz)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Optional corporate CA certificate — for corp-firewall installs where an
# HTTPS proxy intercepts traffic with an internal CA. Mounted as a BuildKit
# secret (path: ./secrets/corp_ca.crt; scripts/install.sh creates an empty
# placeholder). When the file is non-empty, the cert is copied into the
# system trust store and `update-ca-certificates` rebuilds the bundle so
# every HTTPS tool in the image (curl, uv, pip, the runtime OpenAI/GitHub
# clients) trusts the corp CA at BOTH build time AND runtime. Empty file =
# no-op (OSS users unaffected). Inherits into the deps + runtime stages
# via `FROM base`, so this single block covers all backend build steps.
# See docs/03_runbooks/corporate-network-install.md.
RUN --mount=type=secret,id=corp_ca,target=/tmp/corp_ca.crt,required=false \
    if [ -s /tmp/corp_ca.crt ]; then \
        cp /tmp/corp_ca.crt /usr/local/share/ca-certificates/corp_ca.crt && \
        update-ca-certificates && \
        echo "✓ Corporate CA certificate installed"; \
    fi

# Install uv into /usr/local/bin/uv from the aliased uv-source stage above.
COPY --from=uv-source /uv /uvx /usr/local/bin/

WORKDIR /app

# ---------------------------------------------------------------------------
# Stage 2 — deps: install runtime dependencies into /app/.venv
# ---------------------------------------------------------------------------
FROM base AS deps

# IR-evaluation backend pulls a C-extension package transitively:
# infra_ir_measures_migration swapped scoring.py to `ir_measures`, which in
# turn resolves `pytrec-eval-terrier` (the actively-maintained PyTerrier fork
# of pytrec_eval) as a transitive backend. Like the abandoned pytrec_eval
# before it, pytrec-eval-terrier ships as an sdist with no prebuilt wheels
# for many Python versions — every install compiles its C extension on the
# fly. We install gcc + python-dev headers here, then this whole stage is
# discarded (the runtime stage copies only /app/.venv, not the build
# toolchain), so the final image stays slim. Verified at impl-plan time per
# feature_spec.md §19 Q3: `uv tree | grep pytrec_eval` returns the
# `pytrec-eval-terrier` transitive entry.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy lockfile + project metadata first so dependency-only layer caches well.
COPY pyproject.toml uv.lock README.md ./

# Touch a placeholder for the project package so `uv sync` (which builds
# the project itself) doesn't fail before the source is copied.
RUN mkdir -p backend && touch backend/__init__.py

# Install runtime deps only (no dev tools). Frozen mode = exact lockfile.
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 3 — runtime: copy app code + venv; run as non-root
# ---------------------------------------------------------------------------
FROM base AS runtime

ARG RELYLOOP_GIT_SHA=dev
ENV RELYLOOP_GIT_SHA=${RELYLOOP_GIT_SHA} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

# OCI image labels — standard provenance metadata recognized by registries,
# image scanners, and `docker inspect`. `revision` is the git SHA injected
# via build-arg; `source` and `licenses` are repo-stable. See the OCI image
# spec: https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.title="relyloop-api" \
      org.opencontainers.image.description="RelyLoop API + Arq worker runtime (FastAPI on Python 3.14-slim, uv-managed venv)." \
      org.opencontainers.image.source="https://github.com/SoundMindsAI/relyloop" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${RELYLOOP_GIT_SHA}"

# Create the unprivileged user the API runs as. uid 1000 is the conventional
# non-root mapping; the user owns /app so it can read application files but
# cannot write to system paths.
RUN groupadd --system --gid 1000 relyloop \
    && useradd --system --uid 1000 --gid relyloop --create-home --shell /usr/sbin/nologin relyloop

# Bring in the venv from the deps stage.
COPY --from=deps --chown=relyloop:relyloop /app/.venv /app/.venv

# Copy application source + project metadata (uv.lock + pyproject.toml are
# needed by `uv sync` to install the project itself into the venv).
COPY --chown=relyloop:relyloop backend/ /app/backend/
COPY --chown=relyloop:relyloop migrations/ /app/migrations/
COPY --chown=relyloop:relyloop prompts/ /app/prompts/
# scripts/ is needed at runtime because backend/app/services/demo_seeding.py
# imports SCENARIOS + TRUNCATE_TABLES + DEMO_ES_INDICES + DEMO_OS_INDICES
# from scripts/seed_meaningful_demos.py (per feat_home_demo_reseed_endpoint
# PR #228 locked decision D2: reuse the CLI's constants rather than
# refactor them into a shared module). Without this COPY the api container
# crashes on startup with `ModuleNotFoundError: No module named 'scripts'`.
COPY --chown=relyloop:relyloop scripts/ /app/scripts/
COPY --chown=relyloop:relyloop alembic.ini /app/alembic.ini
COPY --chown=relyloop:relyloop pyproject.toml uv.lock README.md LICENSE /app/

# Switch to the unprivileged user BEFORE the project-install `uv sync` so the
# `relyloop-0.1.0.dist-info/*` files it writes land as relyloop:relyloop.
# Doing this here instead of after the sync avoids a 385MB chown layer (a
# `RUN chown -R /app/.venv` step would copy-up the entire venv into a new
# overlay layer). All inputs uv sync touches are already relyloop-owned:
# /app/.venv via the COPY --chown above (line 89), source + project metadata
# via the chowned COPYs (lines 93-104), and /home/relyloop for uv's cache via
# useradd --create-home (line 86). UV_LINK_MODE=copy (base ENV, line 26)
# avoids hardlink-permission issues. See
# bug_dockerfile_venv_root_owned_after_user_switch.
USER relyloop

# Install the project package itself (deps already installed in deps stage).
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Intentionally no image-level HEALTHCHECK — this image is shared between the
# `api` (uvicorn on :8000) and `worker` (arq, no HTTP listener) Compose
# services. A baked-in `curl /healthz` probe would be inherited by the worker,
# which has no `healthcheck:` block in docker-compose.yml to override it, and
# would mark the worker container `unhealthy` forever. The Compose `api`
# service defines its own healthcheck (see docker-compose.yml); that's the
# single source of truth until a future split-image refactor makes a per-role
# image-level probe sensible.

# Default command for the `api` service. The `worker` service overrides via
# `command: ["arq", "backend.workers.all.WorkerSettings"]` in docker-compose.yml.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
