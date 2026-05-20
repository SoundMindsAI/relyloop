# infra_uv_sync_drops_precommit

**Type:** infra — local-dev friction
**Date:** 2026-05-20
**Status:** Idea — captured during feat_cluster_target_filter impl session

## Origin

Surfaced during `feat_cluster_target_filter` post-impl ceremony — repeatedly
during a single session. After every `docker run … uv sync … pytest …`
invocation against the integration tests (the canonical pattern in
`docs/00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md`),
the next `git commit` from the host failed with:

```
/Users/ericstarr/relyloop/.venv/bin/python: No module named pre_commit
```

…even though `.venv/bin/pre-commit` had been installed earlier in the
session. Workaround in-session was a manual `uv pip install pre-commit`
each time. Counted at least 3 cycles in a single feature impl.

## Problem

The dev-deps container's `uv sync --quiet` rewrites the host's `.venv/`
(because the host repo is bind-mounted into the container at `/app`,
and `uv sync` is destructive about extras not declared in `pyproject.toml`).
`pre-commit` is not in `pyproject.toml` (it's developer-installed
ad-hoc per [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)
or via `make install-hooks`), so each container run silently drops it,
and the next `git commit` fails inside pre-commit's framework.

This is a real recurring friction multiplier: every backend feature that
runs integration tests in-container during impl hits this 3-5× per PR.

## Why this is worth fixing

The current workaround works (re-install pre-commit), but:

1. It's invisible to new contributors until they hit it
2. It silently fails commits with a non-obvious error message
3. Each occurrence costs 30-60 seconds of context-switching to debug+fix
4. CI doesn't hit it (CI doesn't bind-mount `.venv`)

## Proposed solutions

### Option A (recommended): Add `pre-commit` to `pyproject.toml` dev-deps

Add a `[project.optional-dependencies]` or `[dependency-groups]` block:

```toml
[dependency-groups]
dev = ["pre-commit>=4.0"]
```

Then `uv sync` from any context (host or container) installs it. CI is
unaffected — it doesn't `uv sync --extra dev`.

Single-line `pyproject.toml` change + maybe a `make install-hooks` tweak.

### Option B: Don't bind-mount `.venv`

Change the integration-test pattern to use a dedicated `--mount type=volume`
for `.venv` inside the container. Cleaner isolation but bigger change to
the documented integration-test command pattern.

### Option C: Detect-and-warn

Add a `.git/hooks/pre-commit` shim or a `make sync` target that detects
the missing `pre-commit` module and prints a friendly error pointing at
the workaround.

## Scope signals

- Backend / dev-infra
- Probably <60min to ship Option A (one-line `pyproject.toml` + verify
  with a fresh `uv sync` + document in runbook)

## Sibling coordination

None — independent infra concern.

## Related

- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) — install workflow
- [`docs/00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md`](../../../00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md) — canonical in-container pytest command
