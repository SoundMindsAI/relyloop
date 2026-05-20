# chore_precommit_node_path_resolution

**Type:** chore — local-dev friction
**Date:** 2026-05-20
**Status:** Idea — captured during feat_cluster_target_filter impl session

## Origin

Surfaced repeatedly during `feat_cluster_target_filter` post-impl ceremony
when committing any UI change. The pre-commit hooks `prettier (ui/ entire
tree)` and `eslint-ui` invoke `pnpm` which runs in the OS default shell
environment (system Node 18.20.8 on this dev's macOS), but the repo's
`ui/package.json` declares `"engines": { "node": ">=20.18" }`, so pnpm
hard-aborts with:

```
ERR_PNPM_UNSUPPORTED_ENGINE — Expected version: >=20.18 — Got: v18.20.8
```

…even when the dev had Node 22 active in their interactive shell via nvm.
The pre-commit hook's subshell doesn't inherit nvm's PATH automatically.

Workaround: prefix every `git commit` with
`PATH="$HOME/.nvm/versions/node/v22.22.2/bin:$PATH"` so the subshell
inherits Node 22. Counted ~5 occurrences in a single feature impl session.

## Problem

Every UI-touching commit fails at the eslint-ui pre-commit hook unless
the developer remembers to inject the nvm Node into PATH manually.
The error message is clear, but the friction is constant.

CI doesn't hit this — it provisions Node 22 explicitly in
`actions/setup-node@v4`. Only the local commit path is affected.

## Why this is worth fixing

1. Every UI PR from a contributor whose system Node ≠ Node 22 hits this
2. The workaround (manual PATH prefix) is invisible to new contributors
3. The hooks could resolve Node themselves via a small helper

## Proposed solutions

### Option A: Pre-commit wrapper that sources nvm

Add a tiny `scripts/run-pnpm.sh` that sources nvm before invoking pnpm:

```bash
#!/usr/bin/env bash
set -e
[[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"
nvm use --silent 2>/dev/null || true
exec pnpm "$@"
```

Update `.pre-commit-config.yaml` to call `scripts/run-pnpm.sh` instead of
`pnpm` directly. Falls back gracefully if nvm isn't installed (uses
system pnpm).

### Option B: `make commit` wrapper

Add a `make commit` target that pins PATH:

```makefile
commit:
\tPATH="$$HOME/.nvm/versions/node/v22.22.2/bin:$$PATH" git commit
```

Cleaner separation but requires devs to use `make commit` instead of
`git commit`.

### Option C: `.envrc` / direnv

If devs use direnv, an `.envrc` could auto-load Node 22. Adds a new tool
dependency though.

### Option D: Document + add a fail-fast hook message

Add a pre-commit hook that detects Node < 20.18 and prints a friendly
error pointing at the workaround. Lowest impact; doesn't solve the
underlying issue.

## Scope signals

- Dev-infra
- Option A: ~30min (write script + update config + verify on a UI commit)
- Option D: ~15min (add a fail-fast hook)

## Sibling coordination

Pairs with [`infra_uv_sync_drops_precommit`](../infra_uv_sync_drops_precommit/idea.md)
— both are local-dev pre-commit friction. Could ship together as a single
`infra_local_dev_precommit_polish` PR.

## Related

- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)
- `ui/package.json` `engines.node` declaration
