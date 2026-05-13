#!/usr/bin/env bash
# bug_env_file_corrupted_during_session — defense-in-depth CI guard.
#
# Fails when a PR diff (or commit on main) introduces or modifies any .env
# family file other than `.env.example`. Catches the failure mode where
# .gitignore is regressed or `git add -f` is used, even when gitleaks would
# pass (e.g. an empty .env.old still signals a rotated key).
#
# Usage:
#   bash scripts/ci/check-no-env-files.sh                      # derives diff from GITHUB_* env
#   bash scripts/ci/check-no-env-files.sh --from-stdin         # reads filenames on stdin (test mode)
#
# Denylist:  (^|/)(\.env(\.[^/]+)?|\.envrc)$
# Allowlist: (^|/)\.env\.example$
#
# Exits 0 when the diff is clean, 1 when a forbidden filename appears, 2 on
# invocation error.

set -euo pipefail

DENY_REGEX='(^|/)(\.env(\.[^/]+)?|\.envrc)$'
ALLOW_REGEX='(^|/)\.env\.example$'

usage() {
  cat >&2 <<'EOF'
Usage: check-no-env-files.sh [--from-stdin]

  (no args)      Derive the changed-files list from GitHub Actions env vars
                 (GITHUB_EVENT_NAME, GITHUB_BASE_REF, GITHUB_SHA).
  --from-stdin   Read newline-separated filenames on stdin (regression-test mode).
EOF
  exit 2
}

resolve_changed_files() {
  if [[ "${1:-}" == "--from-stdin" ]]; then
    cat
    return
  fi
  if [[ -n "${1:-}" ]]; then
    usage
  fi

  local event="${GITHUB_EVENT_NAME:-}"
  # --diff-filter=ACMR: Added, Copied, Modified, Renamed. R is non-obvious
  # but important — `git mv foo.txt .env.old` with high content similarity
  # is reported as a Rename, not Added; AM alone would miss it.
  case "${event}" in
    pull_request)
      local base="${GITHUB_BASE_REF:-main}"
      # Explicit refspec creates refs/remotes/origin/<base> deterministically.
      # actions/checkout's fetch-depth=50 usually populates this already, but
      # an explicit refspec makes the behavior robust to checkout-mode changes
      # and forked-PR semantics.
      git fetch --no-tags --depth=50 origin \
        "+refs/heads/${base}:refs/remotes/origin/${base}" >/dev/null 2>&1 || true
      if ! git rev-parse --verify --quiet "origin/${base}" >/dev/null; then
        echo "::error::check-no-env-files: cannot resolve origin/${base} — refusing to skip the guard. Check the workflow's fetch-depth or actions/checkout configuration." >&2
        exit 2
      fi
      git diff --name-only --diff-filter=ACMR "origin/${base}...HEAD"
      ;;
    push)
      git diff --name-only --diff-filter=ACMR HEAD~1 HEAD
      ;;
    "")
      echo "check-no-env-files: GITHUB_EVENT_NAME is unset; pass --from-stdin to test locally" >&2
      exit 2
      ;;
    *)
      echo "check-no-env-files: unsupported event ${event}" >&2
      exit 2
      ;;
  esac
}

CHANGED=$(resolve_changed_files "${1:-}")

# Filter denylist matches, then strip allowlist matches. The `|| true` keeps
# pipeline status zero when grep finds nothing — set -e would otherwise abort.
FORBIDDEN=$(printf '%s\n' "${CHANGED}" | grep -E "${DENY_REGEX}" | grep -vE "${ALLOW_REGEX}" || true)

if [[ -z "${FORBIDDEN}" ]]; then
  echo "check-no-env-files: clean (no forbidden .env* files in diff)"
  exit 0
fi

echo "::error::Forbidden .env file(s) in PR diff:"
# Use sed to prefix each newline-separated entry. Robust against filenames
# containing spaces (where unquoted printf word-splitting would mis-split).
printf '%s\n' "${FORBIDDEN}" | sed 's/^/  - /'
cat <<'EOF'

Only `.env.example` may be committed. The bare `.env` and any rotated
sibling (`.env.old`, `.env.bak`, `.env.local`, `.envrc`, etc.) carry
production-shaped values and are gitignored for a reason. See
`docs/02_product/planned_features/bug_env_file_corrupted_during_session/bug_fix.md`
for the incident this guard is defending against.

If you genuinely need to add a new template file, name it `.env.example`
(or `.env.<feature>.example`) and update this guard.
EOF
exit 1
