#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

# Self-test for `scripts/ci/verify_build_guides_fresh.sh`
# (feat_website_walkthrough_guides / Story 2.2).
#
# Builds a disposable git fixture containing the real
# `website/scripts/build_guides.py` + the guard + a minimal source set
# (2 walkthrough decks + all 4 long-form guides + a minimal mkdocs.yml),
# seeds the generated output once (committed so a clean run is a no-op),
# then exercises FOUR cases:
#
#   1. Clean tree            → guard exits 0
#   2. Source-drift          → edit a deck metadata.json caption; the guard's
#                              regen rewrites the deck page; `git status`
#                              reports `M`; guard exits 1 + prints fix command
#   3. git rm --cached       → un-index an existing generated page (stays on
#                              disk); guard reports `??`; exits 1
#   4. Brand-new source deck → add a deck absent from fixture HEAD; the regen
#                              emits a never-tracked page; guard reports `??`
#                              for a pure-new path; exits 1 (C2-B2 — distinct
#                              from case 3's previously-tracked path)
#
# Each case runs in a fresh fixture. The fixture must seed ALL FOUR long-form
# guides (the generator fail-louds on a missing hard-coded source, C2-B3/C3-B4)
# plus a minimal mkdocs.yml with exactly one `- API Reference:` anchor (for the
# nav splice). The long-form stubs contain NO `../` links so the rewriter's
# path-existence check has nothing to resolve.
#
# Run locally:  bash scripts/ci/test_verify_build_guides_fresh.sh
# Run in CI:    invoked by the `build-guides-freshness` workflow.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${REPO_ROOT}/scripts/ci/verify_build_guides_fresh.sh"
GENERATOR="${REPO_ROOT}/website/scripts/build_guides.py"

PY="python3"
[[ -x "${REPO_ROOT}/.venv/bin/python" ]] && PY="${REPO_ROOT}/.venv/bin/python"

PASS=0
FAIL=0

if [[ ! -r "${GUARD}" ]]; then
  echo "FATAL: cannot find guard at ${GUARD}" >&2
  exit 2
fi

# 1x1 transparent PNG + a tiny WebM stub are enough — the generator copies
# bytes; it never decodes them (transcode is opt-in via --transcode, which the
# gate never passes).
_seed_deck() {
  local fixture="$1" slug="$2" title="$3"
  local d="${fixture}/ui/public/guides/${slug}"
  mkdir -p "${d}"
  printf '\x89PNG\r\n\x1a\n' >"${d}/01-first.png"
  printf 'webmstub' >"${d}/walkthrough.webm"
  cat >"${d}/metadata.json" <<JSON
{
  "title": "${title}",
  "estimated_time": "2 minutes",
  "tags": ["test"],
  "video": "walkthrough.webm",
  "screenshots": [
    {"file": "01-first.png", "caption": "The first screen of the test flow."}
  ]
}
JSON
  # A captions.vtt matching the single caption (no special chars → normalize+
  # escape is identity), so the generator emits the <track> + copies the vtt
  # and the vtt↔metadata consistency check passes (Story 2.2).
  cat >"${d}/captions.vtt" <<VTT
WEBVTT

00:00:00.000 --> 00:00:04.000
The first screen of the test flow.
VTT
}

build_fixture() {
  local fixture="$1"
  mkdir -p "${fixture}/website/scripts" "${fixture}/docs/08_guides"
  cp "${GENERATOR}" "${fixture}/website/scripts/build_guides.py"

  # All 4 hard-coded long-form guides (missing one fail-louds). No ../ links.
  for g in tutorial-first-study quick-tour workflows-overview llm-endpoint-setup; do
    printf '# %s\n\nA short body with no off-site links.\n' "${g}" \
      >"${fixture}/docs/08_guides/${g}.md"
  done

  # Two walkthrough decks.
  _seed_deck "${fixture}" "01_alpha" "Alpha deck"
  _seed_deck "${fixture}" "02_bravo" "Bravo deck"

  # Minimal mkdocs.yml with exactly one API Reference anchor + an Engines block
  # so the splice has its insertion point.
  cat >"${fixture}/website/mkdocs.yml" <<'YML'
site_name: RelyLoop
nav:
  - Home: index.md
  - Engines:
      - Elasticsearch: engines/elasticsearch.md
  - API Reference: api/index.md
  - Blog:
      - blog/index.md
YML

  # Seed the generated output once.
  ( cd "${fixture}" && "${PY}" website/scripts/build_guides.py >/dev/null )

  (
    cd "${fixture}"
    git init -q -b main
    git config user.email "selftest@local"
    git config user.name "self-test"
    git add .
    git commit -q -m "init"
  )
}

run_guard() {
  local fixture="$1" logfile="$2"
  ( cd "${fixture}" && \
    BUILD_GUIDES_FRESH_REPO_ROOT="${fixture}" \
    bash "${GUARD}" ) >"${logfile}" 2>&1
}

assert_eq() {
  local expected="$1" actual="$2" name="$3"
  if [[ "${actual}" -eq "${expected}" ]]; then
    echo "  ok   ${name}"; PASS=$((PASS + 1))
  else
    echo "  FAIL ${name} (expected exit ${expected}, got ${actual})"; FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local needle="$1" file="$2" name="$3"
  if grep -qF -- "${needle}" "${file}"; then
    echo "  ok   ${name}"; PASS=$((PASS + 1))
  else
    echo "  FAIL ${name} (did not find '${needle}' in ${file})"; FAIL=$((FAIL + 1))
  fi
}

# --- Case 1: clean tree → exit 0 -----------------------------------------
echo "Case 1: clean tree"
TMP1="$(mktemp -d -t rl-build-guides-1.XXXXXX)"
trap 'rm -rf "${TMP1}" "${TMP2:-}" "${TMP2B:-}" "${TMP3:-}" "${TMP4:-}"' EXIT
build_fixture "${TMP1}"
LOG1="${TMP1}.log"; actual=0
run_guard "${TMP1}" "${LOG1}" || actual=$?
assert_eq 0 "${actual}" "clean tree → exit 0"
assert_contains "OK: website Guides pages are fresh." "${LOG1}" "clean tree → success message"
# vtt coverage (Story 2.2): the generated deck page carries the <track> and the
# captions.vtt was copied into the website assets.
assert_contains '<track kind="captions"' \
  "${TMP1}/website/docs/guides/walkthroughs/01_alpha.md" "clean tree → deck page has <track>"
if [[ -f "${TMP1}/website/docs/assets/guides/01_alpha/captions.vtt" ]]; then
  echo "  ok   clean tree → captions.vtt copied into website assets"; PASS=$((PASS + 1))
else
  echo "  FAIL clean tree → captions.vtt NOT copied into website assets"; FAIL=$((FAIL + 1))
fi

# --- Case 2: source-drift → exit 1 + fix command -------------------------
# Drift a source SCREENSHOT (not the caption — editing the caption would trip
# the vtt↔metadata consistency check, a different exit-1 path). The regen
# re-copies the changed PNG into the website assets, so `git status` reports
# drift and the gate prints the canonical fix command.
echo "Case 2: source-drift (edit a source screenshot, leave generated copy unchanged)"
TMP2="$(mktemp -d -t rl-build-guides-2.XXXXXX)"
build_fixture "${TMP2}"
printf 'DRIFTED-PNG-BYTES' >"${TMP2}/ui/public/guides/01_alpha/01-first.png"
LOG2="${TMP2}.log"; actual=0
run_guard "${TMP2}" "${LOG2}" || actual=$?
assert_eq 1 "${actual}" "source-drift → exit 1"
assert_contains "website Guides pages are stale" "${LOG2}" "source-drift → error header"
assert_contains "bash scripts/regen-generated-artifacts.sh" "${LOG2}" \
  "source-drift → canonical fix-command text"

# --- Case 2b: caption drift → consistency check fails loudly -------------
echo "Case 2b: caption drift trips the vtt↔metadata consistency check"
TMP2B="$(mktemp -d -t rl-build-guides-2b.XXXXXX)"
build_fixture "${TMP2B}"
sed -i.bak 's/The first screen of the test flow./A DRIFTED caption./' \
  "${TMP2B}/ui/public/guides/01_alpha/metadata.json"
rm -f "${TMP2B}/ui/public/guides/01_alpha/metadata.json.bak"
LOG2B="${TMP2B}.log"; actual=0
run_guard "${TMP2B}" "${LOG2B}" || actual=$?
assert_eq 1 "${actual}" "caption drift → exit 1"
assert_contains "out of sync with metadata.json" "${LOG2B}" \
  "caption drift → consistency-check error"

# --- Case 3: git rm --cached an existing page → exit 1 (??) ---------------
echo "Case 3: un-index an existing generated page (stays on disk)"
TMP3="$(mktemp -d -t rl-build-guides-3.XXXXXX)"
build_fixture "${TMP3}"
( cd "${TMP3}" && git rm --cached -q website/docs/guides/walkthroughs/01_alpha.md )
LOG3="${TMP3}.log"; actual=0
run_guard "${TMP3}" "${LOG3}" || actual=$?
assert_eq 1 "${actual}" "git rm --cached → exit 1"
assert_contains "?? website/docs/guides/walkthroughs/01_alpha.md" "${LOG3}" \
  "git rm --cached → git status reports ?? marker"

# --- Case 4: brand-new source deck absent from HEAD → exit 1 (pure ??) ----
echo "Case 4: brand-new source deck (never tracked) → never-tracked dest ??"
TMP4="$(mktemp -d -t rl-build-guides-4.XXXXXX)"
build_fixture "${TMP4}"
_seed_deck "${TMP4}" "99_test_new_deck" "Brand new deck"
LOG4="${TMP4}.log"; actual=0
run_guard "${TMP4}" "${LOG4}" || actual=$?
assert_eq 1 "${actual}" "brand-new source deck → exit 1"
assert_contains "?? website/docs/guides/walkthroughs/99_test_new_deck.md" "${LOG4}" \
  "brand-new deck → regen emits a never-tracked page reported as ??"

echo
echo "${PASS} passed, ${FAIL} failed"
if [[ "${FAIL}" -gt 0 ]]; then
  exit 1
fi
