#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# feat_website_walkthrough_guides / Story 2.2 — the freshness gate.
#
# Regenerates the relyloop.com Guides pages from the in-repo source assets
# (ui/public/guides/ + docs/08_guides/) and fails if
# `git status --porcelain` over the gated scope is non-empty (modified,
# untracked, or deleted). Catches the failure mode where a contributor edits
# a source screenshot / metadata.json / long-form guide without re-running
# `python website/scripts/build_guides.py`.
#
# Gated scope (FR-6): the generated .md files, the copied PNG + WebM assets,
# and the managed mkdocs.yml nav fragment. MP4 copies are EXCLUDED via the
# `:!…/*.mp4` pathspec — they are a best-effort artifact (the Python-only
# deploy runner cannot transcode), per spec D-2 / D-18.
#
# Uses `git status --porcelain` (not `git diff --exit-code`) so untracked
# files — e.g. a freshly-renamed deck page the contributor forgot to
# `git add` — are flagged; `git diff` would silently miss those.
#
# Usage:
#   bash scripts/ci/verify_build_guides_fresh.sh                  # standard local/CI run
#   BUILD_GUIDES_FRESH_REPO_ROOT=/path/to/fixture bash …          # self-test override
#
# Exits 0 when the tree is fresh, 1 when it is stale.

set -euo pipefail

if [[ -n "${BUILD_GUIDES_FRESH_REPO_ROOT:-}" ]]; then
  REPO_ROOT="${BUILD_GUIDES_FRESH_REPO_ROOT}"
else
  REPO_ROOT="$(git rev-parse --show-toplevel)"
fi
cd "${REPO_ROOT}"

# Pick a python — prefer the project venv when present, else plain python3.
# The generator is stdlib-only, so any 3.x works.
PY="python3"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python"
fi

# Regenerate. The generator is idempotent on a fresh tree (emit + prune).
# Default invocation (no --transcode) so the gate never shells out to ffmpeg.
"${PY}" website/scripts/build_guides.py

# Gated scope with the MP4 exclude. `git status --porcelain` reports modified,
# deleted, AND untracked files under the pathspec.
DRIFT="$(git status --porcelain -- \
  website/docs/guides/ \
  website/docs/assets/guides/ \
  ':!website/docs/assets/guides/**/*.mp4' \
  website/mkdocs.yml)"

if [[ -n "${DRIFT}" ]]; then
  echo "ERROR: website Guides pages are stale (source changed without regen)." >&2
  echo "Fix with the canonical chained regen:" >&2
  echo "  bash scripts/regen-generated-artifacts.sh" >&2
  echo "(or this gate alone:" >&2
  echo "  python website/scripts/build_guides.py && \\" >&2
  echo "    git add website/docs/guides website/docs/assets/guides website/mkdocs.yml)" >&2
  echo >&2
  echo "Drift detected (diagnostic):" >&2
  printf '%s\n' "${DRIFT}" >&2
  exit 1
fi

echo "OK: website Guides pages are fresh."
