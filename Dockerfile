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

# Single digest-pinned base image (PinnedDependencies / OSSF Scorecard).
# tag + digest in one ARG so an override (`--build-arg BASE_IMAGE=...`) is
# unambiguous — a separate version/digest pair would let the digest silently
# win over a changed tag. Dependabot's docker ecosystem keeps this fresh.
ARG BASE_IMAGE=python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97

# ---------------------------------------------------------------------------
# Stage 1 — base: Python + uv + system deps for healthcheck (curl)
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# curl is required by the Compose API healthcheck (curl -fs /healthz)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv via the official installer to /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:0.5.7@sha256:23272999edd22e78195509ea3fe380e7632ab39a4c69a340bedaba7555abe20a /uv /uvx /usr/local/bin/

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

# Default command for the `api` service. The `worker` service overrides via
# `command: ["arq", "backend.workers.all.WorkerSettings"]` in docker-compose.yml.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
