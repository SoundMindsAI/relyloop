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

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------------------
# Stage 1 — base: Python + uv + system deps for healthcheck (curl)
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

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
COPY --from=ghcr.io/astral-sh/uv:0.5.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# ---------------------------------------------------------------------------
# Stage 2 — deps: install runtime dependencies into /app/.venv
# ---------------------------------------------------------------------------
FROM base AS deps

# pytrec_eval (added by infra_optuna_eval) ships as a sdist with NO prebuilt
# wheels for any Python version — every install compiles its C extension on
# the fly. We install gcc + python-dev headers here, then this whole stage is
# discarded (the runtime stage copies only /app/.venv, not the build toolchain),
# so the final image stays slim.
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
COPY --chown=relyloop:relyloop alembic.ini /app/alembic.ini
COPY --chown=relyloop:relyloop pyproject.toml uv.lock README.md LICENSE /app/

# Install the project package itself (deps already installed in deps stage).
RUN uv sync --frozen --no-dev

USER relyloop

EXPOSE 8000

# Default command for the `api` service. The `worker` service overrides via
# `command: ["arq", "backend.workers.all.WorkerSettings"]` in docker-compose.yml.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
