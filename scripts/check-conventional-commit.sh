#!/usr/bin/env bash
# Conventional Commits format check (infra_foundation FR-6).
# Invoked by pre-commit's `commit-msg` stage with the path to the commit message
# file as $1. Exits 0 if the first line matches the regex; non-zero otherwise.
#
# Regex per spec FR-6:
#   ^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:

set -euo pipefail

COMMIT_MSG_FILE="${1:?usage: check-conventional-commit.sh <path-to-commit-msg>}"
FIRST_LINE="$(head -n 1 "$COMMIT_MSG_FILE")"

# Permit empty messages and merge/fixup/squash commits (git creates these
# automatically and they don't follow Conventional Commits).
if [[ -z "$FIRST_LINE" ]]; then
  exit 0
fi
if [[ "$FIRST_LINE" =~ ^(Merge|Revert|fixup!|squash!|amend!) ]]; then
  exit 0
fi

REGEX='^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:'

if [[ "$FIRST_LINE" =~ $REGEX ]]; then
  exit 0
fi

cat <<EOF
ERROR: Commit message does not follow Conventional Commits.

Expected format:
  <type>(<scope>): <subject>

Accepted types:
  feat       — new feature
  fix        — bug fix
  chore      — maintenance / housekeeping
  docs       — documentation only
  infra      — infrastructure / scaffolding
  refactor   — internal restructure (no behavior change)
  test       — tests only
  style      — formatting only (whitespace, semicolons)
  perf       — performance improvement
  build      — build system / dependencies
  ci         — CI configuration

Optional scope: lowercase letters, digits, hyphens, in parens.
Optional breaking-change marker: ! before the colon.

Examples:
  feat(adapter): add OpenSearch sigv4 auth
  fix(worker): handle Optuna ask deadlock under high parallelism
  docs(spec): clarify multi-tenancy isolation boundaries
  chore!: drop Python 3.11 support

Got:
  ${FIRST_LINE}

Fix the message and retry. Bypass requires --no-verify (forbidden per CLAUDE.md).
EOF

exit 1
