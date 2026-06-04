#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Story 2.4 of infra_generated_artifact_freshness_gate (FR-8 chained
# fix + FR-6 determinism).
#
# One-paste fix command that regenerates ALL four CI-freshness-gated
# generated artifacts in lockstep, then stages them for commit. When a
# freshness gate fails on a PR, the gate's diagnostic output points
# operators here so they don't have to chain the commands themselves.
#
# What it regenerates:
#
#   1. ui/openapi.json
#      via `uv run python -m backend.app.openapi_export --out ui/openapi.json`
#      (offline; no live services; canonical sort_keys=True JSON form per
#      Story 2.1 / FR-4).
#
#   2. ui/src/lib/types.ts
#      via `OPENAPI_URL="$PWD/ui/openapi.json" pnpm --dir ui types:gen`
#      (uses the lockfile-pinned `openapi-typescript` binary; reads
#      from the snapshot at step 1; source-invariant banner per
#      Story 2.3 / FR-5).
#
#   3. ui/public/docs/*.md
#      via `(cd ui && node scripts/copy-docs.mjs)`
#      (copies guides from docs/08_guides/ + prunes to exact set per
#      Story 1.1 / FR-9).
#
#   4. website/docs/guides/** + website/docs/assets/guides/** + the
#      website/mkdocs.yml managed nav fragment
#      via `python website/scripts/build_guides.py`
#      (mirrors the 10 walkthrough decks + 4 long-form guides onto the
#      public MkDocs site per feat_website_walkthrough_guides; default
#      invocation, no --transcode, so it never shells out to ffmpeg —
#      MP4s are produced separately/locally per spec D-2).
#
# Step ordering matters: types.ts is generated FROM the snapshot, so
# the snapshot must be regenerated first. copy-docs and the website
# generator are independent and run last so their diagnostic output
# appears at the bottom — easier to spot a missing source file.
#
# After running, the artifacts are `git add`ed so a subsequent
# `git commit` picks them up. Re-running on an up-to-date tree is a
# clean no-op.
#
# Usage (from anywhere in the repo):
#
#   bash scripts/regen-generated-artifacts.sh
#
# Honors REGEN_NO_STAGE=1 to skip the final `git add` (used by CI's
# clean-tree determinism assertion — it wants to inspect the working
# tree directly, not the index).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "[regen] 1/3: ui/openapi.json (offline exporter)"
uv run python -m backend.app.openapi_export --out ui/openapi.json

echo "[regen] 2/3: ui/src/lib/types.ts (from committed snapshot)"
( cd ui && OPENAPI_URL="${REPO_ROOT}/ui/openapi.json" pnpm types:gen )

echo "[regen] 3/4: ui/public/docs/ (from docs/08_guides/)"
( cd ui && node scripts/copy-docs.mjs )

echo "[regen] 4/4: website Guides pages (from ui/public/guides/ + docs/08_guides/)"
# The generator is stdlib-only; prefer the project venv when present, else
# plain python3. Default invocation (no --transcode) so this never shells out
# to ffmpeg — MP4s are produced separately/locally per spec D-2.
REGEN_PY="python3"
[[ -x "${REPO_ROOT}/.venv/bin/python" ]] && REGEN_PY="${REPO_ROOT}/.venv/bin/python"
"${REGEN_PY}" website/scripts/build_guides.py

if [[ "${REGEN_NO_STAGE:-}" != "1" ]]; then
  git add ui/openapi.json ui/src/lib/types.ts ui/public/docs \
    website/docs/guides website/docs/assets/guides website/mkdocs.yml
  echo "[regen] done — four artifacts regenerated and staged."
else
  echo "[regen] done — four artifacts regenerated (REGEN_NO_STAGE=1, not staged)."
fi
