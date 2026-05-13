#!/usr/bin/env bash
# Regression test for check-no-env-files.sh.
#
# Feeds synthetic file lists through the guard in --from-stdin mode and
# asserts pass/fail. Doubles as the bug_env_file_corrupted_during_session
# regression guard: each ALLOW case must exit 0, each DENY case must exit 1.
#
# Run locally:  bash scripts/ci/test_check_no_env_files.sh
# Run in CI:    invoked by the secrets-files-guard job in .github/workflows/pr.yml

set -euo pipefail

GUARD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-no-env-files.sh"
PASS=0
FAIL=0

# expect_exit <expected_code> <case_name> <input...>
expect_exit() {
  local expected="$1"
  local name="$2"
  shift 2
  local input
  input="$(printf '%s\n' "$@")"
  local actual=0
  printf '%s' "${input}" | bash "${GUARD}" --from-stdin >/dev/null 2>&1 || actual=$?
  if [[ "${actual}" -eq "${expected}" ]]; then
    echo "  ok   ${name}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL ${name} (expected exit ${expected}, got ${actual})"
    FAIL=$((FAIL + 1))
  fi
}

echo "check-no-env-files regression cases:"

# Allow cases — exit 0.
expect_exit 0 "empty diff"
expect_exit 0 "unrelated files only" "README.md" "backend/app/api/health.py"
expect_exit 0 ".env.example at repo root" ".env.example"
expect_exit 0 ".env.example under subdir" "backend/.env.example"
expect_exit 0 "doc file foo.env (no leading dot-env)" "docs/foo.env"
expect_exit 0 ".environment.yml (env-prefix but not .env)" ".environment.yml"

# Deny cases — exit 1.
expect_exit 1 "bare .env" ".env"
expect_exit 1 ".env.old (the canonical incident)" ".env.old"
expect_exit 1 ".env.bak" ".env.bak"
expect_exit 1 ".env.local" ".env.local"
expect_exit 1 ".envrc" ".envrc"
expect_exit 1 ".env.production" ".env.production"
expect_exit 1 "nested .env" "secrets/.env"
expect_exit 1 "nested .env.old" "backend/.env.old"
expect_exit 1 "mixed legit + bad (.env.example + .env.old)" ".env.example" ".env.old"
expect_exit 1 ".env.foo bar.bak (space in name)" ".env.foo bar.bak"
# chore_env_guard_extend_deny_pattern — non-dotted backup/rotation spellings.
expect_exit 1 ".env-old (dash separator)" ".env-old"
expect_exit 1 ".env_bak (underscore separator)" ".env_bak"
expect_exit 1 ".env~ (tilde — vim/emacs backup)" ".env~"
expect_exit 1 ".env~bak (tilde + suffix variant)" ".env~bak"
expect_exit 1 "backend/.env-prod (nested dash variant)" "backend/.env-prod"
# False-positive guards that must still PASS after broadening.
expect_exit 0 ".envoy.conf (letter after .env)" ".envoy.conf"
expect_exit 0 ".env3.yml (digit after .env, no separator)" ".env3.yml"

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
