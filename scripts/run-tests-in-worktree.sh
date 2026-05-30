#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Run tests inside a one-shot container that mounts the sibling worktree's
# source paths and joins the existing Compose network — without leaking writes
# to the operator's main checkout.
#
# This is the automated equivalent of the recipe documented in CLAUDE.md
# §"Working in sibling worktrees" (infra_agent_sibling_worktree_isolation
# Phase 1). Phase 2 codifies the recipe so future agents and operators don't
# have to re-type the 9 mount flags.
#
# Usage:
#   scripts/run-tests-in-worktree.sh                      # pytest backend/tests/unit/ -v
#   scripts/run-tests-in-worktree.sh --cmd "pytest backend/tests/integration -v"
#   scripts/run-tests-in-worktree.sh --dry-run            # print argv only
#   scripts/run-tests-in-worktree.sh --dry-run --cmd "..."
#
# Environment overrides:
#   RELYLOOP_GIT_SHA       — image tag (default "dev")
#   COMPOSE_PROJECT_NAME   — Compose project name; network resolves to
#                            ${COMPOSE_PROJECT_NAME:-relyloop}_default
#   RELYLOOP_MAIN_REPO     — explicit main-checkout path (override the
#                            `git worktree list | awk '{print $1; exit}'`
#                            autodetect)
#
# CLAUDE.md Absolute Rule #2: the DB secret is mounted as a file (`*_FILE`
# env var pointing at the bind-mounted secret), never a bare `DATABASE_URL=`
# env var.

set -euo pipefail

# ---------- Argument parsing ----------

DRY_RUN=0
CMD_OVERRIDE=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --cmd)
      if [[ -z "${2:-}" ]]; then
        echo "ERROR: --cmd requires a value, e.g. --cmd \"pytest backend/tests/integration -v\"" >&2
        exit 2
      fi
      CMD_OVERRIDE="$2"
      shift 2
      ;;
    --)
      # Everything after `--` is positional in-container command args; bash
      # array semantics preserve quoted args naturally. Prefer `--` over
      # `--cmd` when the in-container command needs quoted args like
      # `pytest -k 'foo bar'`.
      shift
      POSITIONAL=("$@")
      break
      ;;
    -h|--help)
      sed -n '/^# Run tests/,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; /^set -euo/d'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Run 'scripts/run-tests-in-worktree.sh --help' for usage." >&2
      exit 2
      ;;
  esac
done

if [[ -n "$CMD_OVERRIDE" && ${#POSITIONAL[@]} -gt 0 ]]; then
  echo "ERROR: pass either --cmd \"<string>\" OR -- positional args, not both." >&2
  exit 2
fi

# ---------- Prerequisites ----------

# Sibling worktree = the invoking pwd's worktree root.
if ! WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "ERROR: scripts/run-tests-in-worktree.sh must be run from inside a git worktree." >&2
  echo "       Current pwd: $PWD" >&2
  exit 3
fi

# Main worktree = the first line of `git worktree list` (git convention).
# Operator can override via RELYLOOP_MAIN_REPO for unusual setups.
if [[ -n "${RELYLOOP_MAIN_REPO:-}" ]]; then
  MAIN_REPO="$RELYLOOP_MAIN_REPO"
else
  MAIN_REPO="$(git worktree list | awk '{print $1; exit}')"
fi

if [[ ! -d "$MAIN_REPO" ]]; then
  echo "ERROR: main worktree path does not exist: $MAIN_REPO" >&2
  echo "       Override with RELYLOOP_MAIN_REPO=/path/to/main-checkout if autodetect is wrong." >&2
  exit 3
fi

SECRET_FILE="$MAIN_REPO/secrets/database_url"
if [[ ! -r "$SECRET_FILE" ]]; then
  echo "ERROR: missing or unreadable DB secret at: $SECRET_FILE" >&2
  echo "       CLAUDE.md Absolute Rule #2 requires secrets-via-mounted-files; bare" >&2
  echo "       DATABASE_URL= env vars are forbidden. Regenerate via:" >&2
  echo "         bash $MAIN_REPO/scripts/install.sh" >&2
  echo "       (or 'make up' from the main worktree, which auto-generates secrets" >&2
  echo "       on first run by invoking scripts/install.sh)." >&2
  exit 4
fi

# POSTGRES_PASSWORD_FILE prerequisite: required for any test that uses
# postgres_reachable() (backend/tests/conftest.py:50-72), which gates on BOTH
# DATABASE_URL_FILE and POSTGRES_PASSWORD_FILE being present in env. Mirror
# the DB-secret check shape exactly (same indentation, same Rule #2 reference,
# same install.sh remediation pointer). Exit code 5 is the next sequential
# after the existing exits 2/3/4.
PG_PASSWORD_FILE="$MAIN_REPO/secrets/postgres_password"
if [[ ! -r "$PG_PASSWORD_FILE" ]]; then
  echo "ERROR: missing or unreadable Postgres password secret at: $PG_PASSWORD_FILE" >&2
  echo "       CLAUDE.md Absolute Rule #2 requires secrets-via-mounted-files; bare" >&2
  echo "       POSTGRES_PASSWORD= env vars are forbidden. Regenerate via:" >&2
  echo "         bash $MAIN_REPO/scripts/install.sh" >&2
  echo "       (or 'make up' from the main worktree, which auto-generates secrets" >&2
  echo "       on first run by invoking scripts/install.sh)." >&2
  exit 5
fi

# CLUSTER_CREDENTIALS_FILE probe: optional. Mount only when the host file is
# readable AND non-empty. When absent / empty / unreadable, skip silently
# (unit tests, contract tests, and DB-only integration tests don't need
# cluster credentials, and cluster-credential-dependent tests have their own
# test-side skip gates: @es_required, FR-6 helper guard at
# backend/tests/integration/test_es_overlap_probe_helpers.py:170-203).
# In --dry-run mode only, emit a single-line stderr hint so operators
# inspecting the constructed argv see what was skipped and why.
CLUSTER_CREDS_HOST="$MAIN_REPO/secrets/cluster_credentials.yaml"
CLUSTER_CREDS_ARGS=()
if [[ -r "$CLUSTER_CREDS_HOST" && -s "$CLUSTER_CREDS_HOST" ]]; then
  CLUSTER_CREDS_ARGS=(
    -e "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials"
    -v "$CLUSTER_CREDS_HOST:/run/secrets/cluster_credentials:ro"
  )
elif [[ "$DRY_RUN" -eq 1 ]]; then
  echo "# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present, empty, or unreadable at $CLUSTER_CREDS_HOST)" >&2
fi

# Compose network name follows Docker Compose's `${project_name}_default`
# convention. `relyloop` is the default project name when `make up` runs
# without an override.
NETWORK_NAME="${COMPOSE_PROJECT_NAME:-relyloop}_default"

# Image tag matches docker-compose.yml lines 54 / 81 / 136.
IMAGE="relyloop/api:${RELYLOOP_GIT_SHA:-dev}"

# Default in-container command if no override provided.
# The production image's venv is built with `uv sync --no-dev` (Dockerfile:107),
# so `pytest` is not on $PATH directly. `uv run` auto-installs missing dev deps
# from the bind-mounted pyproject.toml + uv.lock on first invocation (~1s
# cached, <30s cold) and then dispatches the command. Operators pass commands
# WITHOUT the `uv run` prefix; this script always prepends it.
#
# Two override paths:
#   --cmd "string"  — simple commands, word-split on whitespace (Makefile-friendly).
#   -- arg1 arg2…   — positional args preserved as-is; use for quoted args like
#                     `-- pytest -k 'foo bar'` (shell quoting survives).
if [[ ${#POSITIONAL[@]} -gt 0 ]]; then
  IN_CONTAINER_CMD=(uv run "${POSITIONAL[@]}")
elif [[ -n "$CMD_OVERRIDE" ]]; then
  # shellcheck disable=SC2206  # intentional word-split of --cmd value
  IN_CONTAINER_CMD=(uv run $CMD_OVERRIDE)
else
  IN_CONTAINER_CMD=(uv run pytest backend/tests/unit/ -v)
fi

# ---------- Build docker argv ----------

# Runs as the image's default `relyloop` user (UID 1000) — the Dockerfile
# fix for bug_dockerfile_venv_root_owned_after_user_switch ensures the venv
# is fully relyloop-owned, so `uv run`'s implicit sync against the lockfile
# succeeds without needing `--user root`. PYTHONDONTWRITEBYTECODE is already
# set in the image's base stage (Dockerfile:23), so no `-e` override needed.
ARGV=(
  run
  --rm
  --network "$NETWORK_NAME"
  -e "DATABASE_URL_FILE=/run/secrets/database_url"
  -e "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password"
  -e "RELYLOOP_IN_WORKTREE_CONTAINER=1"
  -v "$SECRET_FILE:/run/secrets/database_url:ro"
  -v "$PG_PASSWORD_FILE:/run/secrets/postgres_password:ro"
  "${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}"
  -v "$WORKTREE_ROOT/CLAUDE.md:/app/CLAUDE.md:ro"
  -v "$WORKTREE_ROOT/backend:/app/backend"
  -v "$WORKTREE_ROOT/migrations:/app/migrations"
  -v "$WORKTREE_ROOT/scripts:/app/scripts"
  -v "$WORKTREE_ROOT/pyproject.toml:/app/pyproject.toml:ro"
  -v "$WORKTREE_ROOT/uv.lock:/app/uv.lock:ro"
  -v "$WORKTREE_ROOT/alembic.ini:/app/alembic.ini:ro"
  -v "$WORKTREE_ROOT/docker-compose.yml:/app/docker-compose.yml:ro"
  -v "$WORKTREE_ROOT/Makefile:/app/Makefile:ro"
  -v "$WORKTREE_ROOT/samples:/app/samples:ro"
  "$IMAGE"
  "${IN_CONTAINER_CMD[@]}"
)

# ---------- Dispatch ----------

if [[ "$DRY_RUN" -eq 1 ]]; then
  # Prepend `docker` so the output is directly copy-pasteable into a shell.
  printf '%s\n' docker "${ARGV[@]}"
  exit 0
fi

echo "> running tests in one-shot container (worktree=$WORKTREE_ROOT, main=$MAIN_REPO, network=$NETWORK_NAME)"
echo "> command: ${IN_CONTAINER_CMD[*]}"
# Guard the docker invocation so set -e doesn't kill the script before
# printing the exit-line on a non-zero exit. We always want operators to see
# the final RC line.
if docker "${ARGV[@]}"; then
  RC=0
else
  RC=$?
fi
echo "> exited with code $RC"
exit "$RC"
