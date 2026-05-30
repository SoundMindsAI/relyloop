#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Developer Certificate of Origin (DCO) sign-off check.
# Invoked by pre-commit's `commit-msg` stage with the path to the commit message
# file as $1. Exits 0 if the message contains a Signed-off-by trailer; non-zero
# otherwise.
#
# RelyLoop uses DCO instead of a CLA. See CONTRIBUTING.md "Developer Certificate
# of Origin (DCO)" for the full text and rationale.
#
# The CI gate at .github/workflows/dco.yml enforces the same check on every PR
# commit; this hook catches the miss locally so contributors don't get a CI
# failure they could have prevented.

set -euo pipefail

COMMIT_MSG_FILE="${1:?usage: check-dco-signoff.sh <path-to-commit-msg>}"

# Permit merge/fixup/squash/amend commits (git creates these automatically and
# the DCO check is applied to the final squashed/amended message instead).
FIRST_LINE="$(head -n 1 "$COMMIT_MSG_FILE")"
if [[ "$FIRST_LINE" =~ ^(Merge|Revert|fixup!|squash!|amend!) ]]; then
  exit 0
fi

# Match a real Signed-off-by trailer: "Signed-off-by: Name <email@host>".
# Lenient on author/signer name+email match — the CI gate does the same. The
# intent of DCO is the attestation, not signature forensics.
if grep -qE '^Signed-off-by: .+ <.+@.+>$' "$COMMIT_MSG_FILE"; then
  exit 0
fi

cat <<EOF >&2
ERROR: Missing Signed-off-by trailer.

RelyLoop uses the Developer Certificate of Origin (DCO). Every commit must
include a Signed-off-by trailer. See CONTRIBUTING.md for the certification text.

Fix:
  git commit -s                     # add to new commit
  git commit --amend -s --no-edit   # add to the most recent commit
  git rebase --signoff <base>       # backfill across a range

Or configure your repo to always sign off:
  git config format.signoff true

Bypass requires --no-verify (forbidden per CLAUDE.md).
EOF

exit 1
