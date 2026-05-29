#!/usr/bin/env bash
# Fail the commit if state.md grows past the snapshot threshold.
#
# Per chore_state_md_size_compression (2026-05-29): state.md is a one-page
# fast-path snapshot that MUST stay loadable in a single Read tool call (the
# Read tool caps at 256 KB). Before the split it had ballooned to 360 KB of
# chained feature-merge narrative, which forced offset-based reads and defeated
# its stated purpose. The append-only history lives in state_history.md instead.
#
# Threshold rationale: a healthy snapshot (current focus + last 5 merges +
# in-flight/queued + known debt + quick-ref) lands around 9-12 KB. 60 KB leaves
# generous headroom for growth while firing LONG before the 256 KB Read cap, so
# an agent never silently loses the ability to load it whole. When this trips,
# the fix is to move the oldest "Last 5 merges" rows + any bloated narrative
# into state_history.md — never to raise the cap.

set -euo pipefail

STATE_FILE="state.md"
MAX_BYTES=$((60 * 1024)) # 60 KB

if [[ ! -f "$STATE_FILE" ]]; then
  # Nothing to check (e.g., running from a worktree without state.md).
  exit 0
fi

# Portable byte count (macOS `stat -f%z`, GNU `stat -c%s`, `wc -c` fallback).
if size=$(stat -f%z "$STATE_FILE" 2>/dev/null); then
  :
elif size=$(stat -c%s "$STATE_FILE" 2>/dev/null); then
  :
else
  size=$(wc -c <"$STATE_FILE" | tr -d '[:space:]')
fi

if ((size > MAX_BYTES)); then
  echo "ERROR: $STATE_FILE is ${size} bytes, over the ${MAX_BYTES}-byte (60 KB) snapshot cap." >&2
  echo "" >&2
  echo "state.md must stay a one-page snapshot loadable in a single Read call." >&2
  echo "Move the oldest 'Last 5 merges' rows and any long narrative into" >&2
  echo "state_history.md (append-only, newest first). See CLAUDE.md" >&2
  echo "\"Active Work — Read This First\" / \"Compressed Context First\"" >&2
  echo "for the snapshot-vs-history convention." >&2
  echo "Do NOT raise this cap — the point is to force the split." >&2
  exit 1
fi

exit 0
