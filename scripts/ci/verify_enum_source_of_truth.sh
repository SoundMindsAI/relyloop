#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# feat_studies_ui Story 4.2 — source-of-truth comment grep gate (AC-6 + AC-9).
#
# Scans `ui/src/lib/enums.ts` for `// Values must match <path.py> <Symbol>`
# comments. For each match, reads the cited backend file and verifies the
# following `as const` array contains exactly the values the cited Literal /
# frozenset / tuple defines. Exits non-zero on any drift.
#
# The grep is intentionally narrow — only the canonical enums.ts file carries
# source-of-truth comments. Zod schemas and component option lists consume the
# typed arrays via `z.enum(STUDY_STATUS_VALUES)` / `STUDY_STATUS_VALUES.map(...)`
# without repeating the comment (keeps the gate simple + false-positive-free).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_FILE="${REPO_ROOT}/ui/src/lib/enums.ts"
HELPER_MODULE="backend.tests.contract.test_enum_source_of_truth_helpers"

if [[ ! -f "${TARGET_FILE}" ]]; then
  echo "verify_enum_source_of_truth: ${TARGET_FILE} not found" >&2
  exit 2
fi

# Resolve a python interpreter. Prefer the project venv (if present), then
# `uv run`, then fall back to system python3 — the helper has no external deps.
PYTHON_CMD=""
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_CMD="${REPO_ROOT}/.venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
  PYTHON_CMD="uv run python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
else
  echo "verify_enum_source_of_truth: no python interpreter available" >&2
  exit 2
fi

cd "${REPO_ROOT}"

failures=0
total=0

# Iterate every comment line of the canonical form. Use grep with line numbers
# so we can report the source location of each finding.
while IFS=: read -r line_no comment; do
  total=$((total + 1))
  # comment looks like "// Values must match backend/app/.../file.py SomeSymbol."
  # Capture the module file path + symbol via bash regex.
  if [[ ! "${comment}" =~ //[[:space:]]+Values[[:space:]]+must[[:space:]]+match[[:space:]]+([^[:space:]]+\.py)[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
    echo "verify_enum_source_of_truth: ${TARGET_FILE}:${line_no}: malformed comment: ${comment}" >&2
    failures=$((failures + 1))
    continue
  fi
  py_path="${BASH_REMATCH[1]}"
  symbol="${BASH_REMATCH[2]}"

  # Translate path → dotted module. Drop leading 'backend/' (it's already on
  # sys.path) and strip the '.py' suffix.
  module="${py_path%.py}"
  module="${module//\//.}"

  # Resolve the backend values via the helper.
  backend_values=$(${PYTHON_CMD} -m "${HELPER_MODULE}" "${module}" "${symbol}" 2>/dev/null) || {
    echo "verify_enum_source_of_truth: ${TARGET_FILE}:${line_no}: helper failed to resolve ${module}.${symbol}" >&2
    failures=$((failures + 1))
    continue
  }

  # Pull the values from the *next* `as const` array literal after the comment.
  frontend_values=$(${PYTHON_CMD} -c "
import re, sys
text = open('${TARGET_FILE}').read()
lines = text.split('\n')
start = ${line_no}  # 1-indexed line of the comment
# Find the next 'as const' block after the comment line.
rest = '\n'.join(lines[start:])
m = re.search(r'\[(.*?)\]\s*as\s+const', rest, re.DOTALL)
if not m:
    sys.stderr.write('no as const array after comment at line ${line_no}\\n')
    sys.exit(2)
body = m.group(1)
# Tokenize: pull every quoted string OR bare integer / float literal.
items = re.findall(r\"'([^']*)'|\\\"([^\\\"]*)\\\"|(-?\\d+(?:\\.\\d+)?)\", body)
out = []
for a, b, c in items:
    if a:
        out.append(a)
    elif b:
        out.append(b)
    elif c:
        # Preserve numeric semantics — int if integer-shaped, else float.
        out.append(int(c) if '.' not in c else float(c))
print('|'.join(repr(x) for x in out))
")

  # Sort both sides and compare as sets — wire-value contract doesn't care
  # about declaration order.
  if [[ "$(echo "${backend_values}" | tr '|' '\n' | sort)" != \
        "$(echo "${frontend_values}" | tr '|' '\n' | sort)" ]]; then
    echo "verify_enum_source_of_truth: drift at ${TARGET_FILE}:${line_no} (symbol=${symbol})" >&2
    echo "  backend  (${py_path}): ${backend_values}" >&2
    echo "  frontend (enums.ts):   ${frontend_values}" >&2
    failures=$((failures + 1))
  fi
done < <(grep -nE "^// Values must match" "${TARGET_FILE}" || true)

if [[ "${total}" -eq 0 ]]; then
  echo "verify_enum_source_of_truth: no 'Values must match' comments found in ${TARGET_FILE}" >&2
  exit 2
fi

if [[ "${failures}" -gt 0 ]]; then
  echo "verify_enum_source_of_truth: ${failures}/${total} mismatches" >&2
  exit 1
fi

echo "verify_enum_source_of_truth: ${total} allowlists verified — clean"
