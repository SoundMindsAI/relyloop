# infra_uv_sync_drops_precommit

**Type:** infra — local-dev friction
**Date:** 2026-05-20 (preflighted 2026-05-21 — original diagnosis was wrong; see Re-diagnosis below)
**Status:** Idea — captured during feat_cluster_target_filter impl session; root cause re-grounded after preflight

## Origin

Surfaced during `feat_cluster_target_filter` post-impl ceremony — repeatedly
during a single session. After every `docker run … uv sync … pytest …`
invocation against the integration tests (the canonical pattern in
[`bug_capability_check_test_isolation/idea.md`](../../../00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md)),
the next `git commit` from the host failed with:

```
/Users/ericstarr/relyloop/.venv/bin/python: No module named pre_commit
```

…even though `.venv/bin/pre-commit` had been installed earlier in the
session. Workaround in-session was a manual `uv pip install pre-commit`
each time. Counted at least 3 cycles in a single feature impl.

## Re-diagnosis (preflight 2026-05-21)

The original "Problem" section in this idea (now superseded below) claimed
`pre-commit` is missing from `pyproject.toml`. **That's false** —
[`pyproject.toml:63`](../../../../pyproject.toml#L63) already has
`"pre-commit>=4.6.0"` in `[dependency-groups].dev`, and uv installs the
`dev` group by default during `uv sync`. The proposed "Option A" fix was
already in place when the friction started; adding it again would do
nothing.

The **real** root cause is a **Python version mismatch between the host
and the dev-deps container**:

| Layer | Python version | Source |
|---|---|---|
| Repo requirement | `>=3.13` | [`pyproject.toml:7`](../../../../pyproject.toml#L7) |
| Host (this dev's mac) | `3.14.4` | Homebrew `python@3.14` |
| Container image | `3.13` (bookworm) | `ghcr.io/astral-sh/uv:python3.13-bookworm` per the canonical command in `bug_capability_check_test_isolation` |

Mechanism (verified by inspecting `.venv/bin/python` after a session):

1. Host's `uv sync` creates `.venv/bin/python` as a symlink to
   `/usr/local/opt/python@3.14/bin/python3.14` (host's only Python).
2. Container runs `uv sync --quiet` with the repo bind-mounted at `/app`.
   uv sees the existing `.venv` was built for 3.14, the container has 3.13,
   so uv rebuilds `.venv` at `/app/.venv` using container's 3.13.
3. The rebuilt `.venv/bin/python` is now a symlink to a container-only
   path (e.g., `/usr/local/bin/python3.13`).
4. Container exits. Host runs `git commit`; pre-commit's hook shim calls
   `.venv/bin/python`. The symlink target doesn't exist on the host →
   broken `.venv` from the host's perspective.
5. Manual `uv pip install pre-commit` on host re-binds `.venv` to the
   host's 3.14 (because that's the only Python uv can find on the host),
   fixing it — until the next container run breaks it again.

The "pre-commit specifically went missing" symptom is a red herring: the
ENTIRE `.venv` is broken from the host's perspective after every container
run; pre-commit is just the first thing the host's `git commit` reaches
for.

## Why this matters

The friction count from the original idea stands (3-5 occurrences per
backend feature that runs in-container integration tests). What changes
is the solution space — none of the original three options actually fix
the issue.

1. Invisible to new contributors until they hit it (worse now — the error
   message points at pre-commit but the cause is venv-wide).
2. Silent break of every host-side `.venv`-using command after each
   container run.
3. ~30-60 seconds of context-switch debugging per occurrence.
4. CI doesn't hit it (CI runs ONLY in containers, never bind-mounts a host
   venv into a container).

## Locked decision (operator call, 2026-05-21): bundle Option A + Option B

Operator directive: "we need to be at 3.13 not 3.14" locked Option A.
**Smoke test during /impl-execute ad-hoc proved Option A alone is
insufficient** — the container's `uv sync` rewrites
`.venv/pyvenv.cfg` + script shebangs (`#!/app/.venv/bin/python`)
regardless of Python version match, breaking host-side `git commit`
afterward. Operator approved bundling Option B (`-v /app/.venv`
anonymous volume in the canonical container command) into the same
PR. Both ship together as `infra_local_dev_venv_isolation`.

**What ships:**

1. Add `.python-version` file at repo root containing `3.13` so `uv sync`
   picks 3.13 even on hosts that have a newer Python installed. `uv` reads
   `.python-version` and downloads / selects 3.13 automatically — no
   `brew install python@3.13` required (uv-managed pythons), though brew
   install works too.
2. Update [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)
   to state Python 3.13 is the canonical local-dev Python, matching the
   container image (`ghcr.io/astral-sh/uv:python3.13-bookworm`). Mention
   the `requires-python = ">=3.13"` floor exists for CI hermeticity, NOT
   as license to use newer Python locally — local dev must match the
   container.
3. **Operator-environment step (out-of-scope for the PR):** the dev who
   currently has 3.14 will need to `rm -rf .venv && uv sync` once after
   pulling the `.python-version` file, so uv rebuilds the venv against
   3.13. uv handles this transparently if `.python-version` says `3.13`.

**Final option disposition** (re-evaluated after the smoke-test surprise — Gemini PR #171 caught the previous version of this table contradicting the "Locked decision" header):

| Option | Disposition |
|---|---|
| A — pin host Python via `.python-version` | **Bundled into this PR.** Necessary but not sufficient on its own; provides forward consistency with the container. |
| B — narrow bind-mount (anonymous `-v /app/.venv` volume) | **Bundled into this PR.** Smoke test proved this is what actually stops the host-side `.venv` from being rewritten. Trade: ~10-20s fresh sync per container run. |
| C — pre-baked `relyloop/dev-deps` image | **Rejected.** Right answer for MVP3 deployment work, but builds + publishes + cache-invalidation logic is way beyond this friction's scope. |
| D — host-side recovery wrapper | **Rejected.** Too clever; easy to forget the wrapper; doesn't fix the underlying issue. |

The `requires-python = ">=3.13"` floor at [`pyproject.toml:7`](../../../../pyproject.toml#L7)
stays — that's a hard floor for CI + production. The `.python-version`
file at `3.13` is a soft pin for local-dev consistency with the container.

## Implementation shape (post-decision)

This is now a **2-file ad-hoc change** + an operator-environment step.
Does not need full /spec-gen + /impl-plan-gen ceremony:

| File | Change |
|---|---|
| `.python-version` (NEW) | One line: `3.13` |
| `docs/03_runbooks/local-dev.md` | Add a "Local Python version" section noting the soft-pin + the `rm -rf .venv && uv sync` step for devs currently on a different Python |

Recommended ship path: `/impl-execute --ad-hoc` on a `infra/pin-python-313`
branch. ~15-30 min including the operator-side rebuild + smoke verification
(run the integration tests in-container, then `git commit` from host, then
confirm pre-commit doesn't die).

## Sibling coordination

[`chore_precommit_node_path_resolution`](../chore_precommit_node_path_resolution/idea.md)
is a sibling pre-commit-from-host friction (subshell PATH lacks nvm's
Node 22; pnpm aborts on `engines.node`). **Decoupled after the Python
3.13 pin** — pinning Python doesn't help Node at all; the two now have
non-overlapping fixes. Ship the Node sibling separately under its own
existing folder. Coordinate only via shared adjacency in the runbook
(both are "local-dev: pre-commit-hook prerequisites" — same section).

## Open questions for /spec-gen

None. The original three open questions are all resolved:

1. ~~Solution path~~ → **Locked 2026-05-21: Option A (pin host Python
   via `.python-version` = `3.13`).**
2. ~~Bundle with `chore_precommit_node_path_resolution`?~~ → **No** —
   the Python pin doesn't affect the Node-PATH issue; sibling ships
   separately on its own branch.
3. ~~Runbook canonicalization~~ → **Yes** — `local-dev.md` will host the
   3.13-pin section + the post-pull `rm -rf .venv && uv sync` migration
   step.

## Scope signals

- Backend / dev-infra (no application-code change)
- 2 files: new `.python-version` + edit `docs/03_runbooks/local-dev.md`
- ~15-30 min total via `/impl-execute --ad-hoc` (no /spec-gen ceremony)
- Operator-environment step: dev currently on 3.14 runs `rm -rf .venv && uv sync`
  once after pulling the change. uv auto-fetches Python 3.13 if it's not
  already installed.

## Related

- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md) — install workflow
- [`bug_capability_check_test_isolation/idea.md`](../../../00_overview/implemented_features/2026_05_12_bug_capability_check_test_isolation/idea.md) — canonical in-container pytest command (Reproducer section)
- [`pyproject.toml:7`](../../../../pyproject.toml#L7) — `requires-python = ">=3.13"`
- [`pyproject.toml:53-66`](../../../../pyproject.toml#L53-L66) — `[dependency-groups].dev` already includes `pre-commit>=4.6.0`
- [`Makefile:70`](../../../../Makefile#L70) — `make pre-commit-install` (the actual target name; original idea cited the wrong `make install-hooks`)
- [`chore_precommit_node_path_resolution`](../chore_precommit_node_path_resolution/idea.md) — sibling friction; bundle candidate
