#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# feat_website_walkthrough_guides — post-build asset-reference guard.
#
# `mkdocs build --strict` validates markdown links + image references, but it
# does NOT validate src/href attributes inside RAW HTML (the <video><source>
# and the download <a> emitted via md_in_html). A wrong relative depth there
# 404s in the browser yet passes --strict — exactly the video-404 bug this
# guard exists to catch.
#
# Given a built `site/` tree, this resolves every <source src="..."> and every
# <video>-block download <a href="..."> (relative paths only) against the
# filesystem, relative to the HTML file that contains it, and fails if any
# target is missing.
#
# Usage (run from repo root, after `mkdocs build` populated website/site/):
#   bash scripts/ci/verify_built_site_asset_refs.sh [SITE_DIR]
# SITE_DIR defaults to website/site.

set -euo pipefail

SITE_DIR="${1:-website/site}"
if [[ ! -d "${SITE_DIR}" ]]; then
  echo "ERROR: built site dir not found: ${SITE_DIR} (run 'mkdocs build' first)" >&2
  exit 2
fi

python3 - "${SITE_DIR}" <<'PY'
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

site = Path(sys.argv[1]).resolve()

# <source src="..."> anywhere, plus <a href="..."> that points at a
# walkthrough.{webm,mp4} (the video download link).
SOURCE_RE = re.compile(r'<source\s+[^>]*src="([^"]+)"', re.IGNORECASE)
DL_RE = re.compile(r'<a\s+[^>]*href="([^"]+walkthrough\.(?:webm|mp4))"', re.IGNORECASE)

broken: list[str] = []
checked = 0
for html in site.rglob("*.html"):
    text = html.read_text(encoding="utf-8")
    refs = SOURCE_RE.findall(text) + DL_RE.findall(text)
    for ref in refs:
        scheme, netloc, path, _, _ = urlsplit(ref)
        if scheme or netloc:
            continue  # absolute URL — not our concern
        if path.startswith("/"):
            target = (site / path.lstrip("/")).resolve()
        else:
            target = (html.parent / unquote(path)).resolve()
        checked += 1
        if not target.is_file():
            rel = html.relative_to(site)
            broken.append(f"  {rel}: '{ref}' -> {target} (NOT FOUND)")

if broken:
    print(
        f"ERROR: {len(broken)} raw-HTML asset reference(s) in the built site "
        f"resolve to a missing file:",
        file=sys.stderr,
    )
    print("\n".join(broken), file=sys.stderr)
    print(
        "\nThese are <video><source>/<a> refs that `mkdocs build --strict` does "
        "NOT validate. Fix the relative depth in build_guides.py.build_video_block.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"OK: {checked} raw-HTML asset reference(s) in the built site all resolve.")
PY
