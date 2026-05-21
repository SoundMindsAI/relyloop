# chore_precommit_node_path_resolution

**Type:** chore — local-dev friction
**Date:** 2026-05-20 (preflighted 2026-05-21)
**Status:** Idea — captured during feat_cluster_target_filter impl session; verified still recurring during PR #171 implementation

## Origin

Surfaced repeatedly during `feat_cluster_target_filter` post-impl ceremony
when committing any UI change. The pre-commit hooks `prettier (ui/ entire
tree)` and `eslint-ui` invoke `pnpm`, which runs in the parent shell's
environment. The shell's PATH typically puts a stale nvm-managed Node
ahead of the system Node:

```
$ echo $PATH | tr ':' '\n' | head -3
/Users/ericstarr/relyloop/.venv/bin
/Users/ericstarr/.nvm/versions/node/v18.20.8/bin   ← stale nvm pin
/Users/ericstarr/.codeium/windsurf/bin

$ node --version              # what pre-commit's subshell sees
v18.20.8
$ env -i PATH=/usr/local/bin bash -c 'node --version'   # bypassing nvm
v26.0.0
```

The repo's `ui/package.json` declares `"engines": { "node": ">=20.18" }`
and `ui/.npmrc` enables `engine-strict=true`, so pnpm hard-aborts:

```
ERR_PNPM_UNSUPPORTED_ENGINE — Expected version: >=20.18 — Got: v18.20.8
```

The repo's `.nvmrc` says `22` — so `nvm use` from the repo root would
fix it — but `git commit`'s pre-commit subshell doesn't `cd` into the
repo + doesn't source nvm, so it gets whatever PATH the parent shell
has set (which is whatever the last `nvm use` left active).

Workaround in active use: prefix every `git commit` with
`PATH="$HOME/.nvm/versions/node/v22.22.2/bin:$PATH"`. Counted ~5
occurrences in a single feature impl session; recurred during PR #171
this morning. Reproduced empirically on 2026-05-21 — friction is current.

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

## Locked decision (preflight 2026-05-21): Option A — wrapper script using the existing NVM_GUARD pattern

The Makefile **already** has the exact pattern this fix needs, in the
`NVM_GUARD` macro at [`Makefile:95-98`](../../../../Makefile#L95-L98)
(used today by `ui-dev`):

```makefile
NVM_GUARD = if [ -s "$$HOME/.nvm/nvm.sh" ]; then \
	  . "$$HOME/.nvm/nvm.sh"; \
	  nvm use --silent >/dev/null 2>&1 || nvm use --silent default; \
	fi
```

Extract that pattern into `scripts/run-pnpm.sh`, point the two
pre-commit hooks at it. Same shape, applied to a new surface.

```bash
#!/usr/bin/env bash
set -e
# Mirrors NVM_GUARD in Makefile:95-98 — sources nvm so `nvm use` resolves
# .nvmrc's pinned version (currently 22). Falls back to system pnpm if
# nvm isn't installed (e.g., CI runners that provision Node via
# actions/setup-node@v4 instead).
if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
  # shellcheck source=/dev/null
  . "$HOME/.nvm/nvm.sh"
  nvm use --silent >/dev/null 2>&1 || nvm use --silent default
fi
exec pnpm "$@"
```

Update `.pre-commit-config.yaml`'s `prettier-ui` + `eslint-ui` hooks to
invoke `scripts/run-pnpm.sh --dir ui ...` instead of `pnpm --dir ui ...`.

## Option disposition

| Option | Disposition |
|---|---|
| A — wrapper script sources nvm (mirrors Makefile's NVM_GUARD) | **Locked.** Zero new deps; reuses an existing precedent; fails gracefully when nvm is absent (system pnpm still runs); no behavior change for CI (it doesn't have nvm, falls through to system Node 22 from `actions/setup-node@v4`). |
| B — `make commit` wrapper that pins PATH | **Rejected.** Forces devs to remember `make commit` over `git commit`; doesn't help IDE-driven commits (VS Code's Source Control panel, lazygit, etc.). |
| C — `.envrc` / direnv | **Rejected.** Adds a new dev-tool dependency the repo doesn't require today; partial coverage (devs without direnv still hit the issue). |
| D — fail-fast hook with friendly error | **Rejected as standalone.** Doesn't fix the underlying issue; would force every UI commit to error first then succeed. Could be bundled as a one-line check inside Option A's script if useful, but isn't necessary. |

## Implementation shape

This is a **3-file ad-hoc change** (no /spec-gen + /impl-plan-gen ceremony):

| File | Change |
|---|---|
| `scripts/run-pnpm.sh` (new, executable) | The wrapper above, mirroring NVM_GUARD |
| `.pre-commit-config.yaml` | Two hook `entry:` lines change from `pnpm --dir ui ...` to `scripts/run-pnpm.sh --dir ui ...` |
| `docs/03_runbooks/local-dev.md` | Add a "Local Node version" subsection adjacent to the "Local Python version" section that PR #171 added — same pattern, parallel structure. Mention `.nvmrc` pins 22, the wrapper script handles the pre-commit subshell case, and devs without nvm fall through to system pnpm. |

Recommended ship path: `/impl-execute --ad-hoc` on
`infra/precommit-node-via-nvm`. ~20-30 min including a smoke test
(stale-Node shell → `git commit` on a `.ts` change → hook resolves
Node 22 via wrapper → green).

## Why this is worth fixing

1. Every UI PR from a contributor whose shell PATH has stale nvm Node ≠ 20.18 hits this — fresh failure mode for every onboarding contributor.
2. The workaround (manual PATH prefix on every commit) is invisible to new contributors AND IDE-driven workflows can't use it.
3. The fix has an existing precedent in the codebase (NVM_GUARD) — no design surface to debate.
4. CI doesn't hit it (`actions/setup-node@v4` puts the right Node first); only local commits suffer.

## Sibling coordination

[`infra_uv_sync_drops_precommit`](../../../00_overview/implemented_features/2026_05_21_infra_uv_sync_drops_precommit/idea.md)
**shipped 2026-05-21 as PR #171** (squash `861e354`) — the original
suggestion to bundle into a single PR has expired. This idea now ships
independently. The runbook section added by #171 ("Local Python version")
is the natural docs anchor — add a parallel "Local Node version"
subsection in the same area.

## Open questions for /spec-gen

None. Option A is locked, the precedent exists, the implementation is
3 files. Goes straight to `/impl-execute --ad-hoc`.

## Related

- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) — natural docs anchor (next to the "Local Python version" section added by PR #171)
- [`Makefile:95-98`](../../../../Makefile#L95-L98) — existing `NVM_GUARD` macro used by `ui-dev`; pattern to mirror
- [`ui/package.json`](../../../../ui/package.json) — `engines.node = ">=20.18"`
- [`ui/.npmrc`](../../../../ui/.npmrc) — `engine-strict=true` makes the engines check hard-fail
- [`.nvmrc`](../../../../.nvmrc) — pins `22` for `nvm use`
- [`infra_uv_sync_drops_precommit`](../../../00_overview/implemented_features/2026_05_21_infra_uv_sync_drops_precommit/idea.md) — sibling local-dev pre-commit friction, shipped as PR #171
