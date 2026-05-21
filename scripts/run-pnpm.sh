#!/usr/bin/env bash
# run-pnpm.sh — invoke pnpm with the repo's nvm-pinned Node when available.
#
# Why: pre-commit hooks `prettier-ui` and `eslint-ui` shell out to pnpm,
# which runs in the parent shell's environment. That shell's PATH often
# puts a stale `nvm use`-pinned Node ahead of system Node — so pnpm hits
# `ui/package.json`'s `engines.node = ">=20.18"` floor with an older
# version and hard-aborts:
#
#   ERR_PNPM_UNSUPPORTED_ENGINE — Expected version: >=20.18 — Got: v18.20.8
#
# Without this wrapper, every UI-touching `git commit` from a host whose
# nvm default is an older Node fails the eslint-ui pre-commit hook unless
# the dev manually prefixes `PATH="$HOME/.nvm/versions/node/v22.../bin:$PATH"`
# on each commit. See `chore_precommit_node_path_resolution`.
#
# Mirrors the existing NVM_GUARD macro at Makefile:95-98 used by
# `ui-dev` — same shape, applied to a new surface (pre-commit hooks).
#
# Graceful fallback: if nvm isn't installed (e.g., CI runners that
# provision Node via actions/setup-node@v4), we exec pnpm with whatever
# Node is on PATH — that's already Node 22 on CI.

set -e

if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  . "$HOME/.nvm/nvm.sh"
  # nvm use reads .nvmrc (repo root pins 22); falls back to default if
  # nvm has no default set yet, which is harmless.
  nvm use --silent >/dev/null 2>&1 || nvm use --silent default >/dev/null 2>&1 || true
fi

exec pnpm "$@"
