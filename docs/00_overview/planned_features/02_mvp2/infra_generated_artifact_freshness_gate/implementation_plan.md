# Implementation Plan — CI gate for generated-artifact freshness (`types.ts` + `ui/public/docs`)

**Date:** 2026-06-01
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rules #2 secrets-via-files, #7 conventional commits + DCO; "Common Pitfalls" hermetic-CI + local-stub hygiene); `scripts/gen_license_inventory.py --check` + the `license-inventory` job in [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml); [`.github/workflows/secrets-defense.yml`](../../../../../.github/workflows/secrets-defense.yml) (own-workflow-to-escape-`paths-ignore` precedent)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (FR-1 … FR-9).
- This is infra/CI work — no DB, no migration, no HTTP endpoints, no UI. Stories own shell/JS/Python tooling + workflow YAML + tests.
- **Determinism is load-bearing.** Every gate's regeneration step must produce byte-identical output across the macOS dev box and the Linux CI runner, or the gate flakes.
- The gate fails the human's PR; it never auto-commits. Each failure prints a one-paste fix command.
- Phase 1 (copy-docs) ships with zero new infra. Phase 2 (export + types) reuses the **already-proven** `app.openapi()`-with-stubbed-settings recipe from `backend/tests/contract/test_data_table_query_params.py`.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (copy-docs freshness gate) | Epic 1 / Story 1.2 | regenerate + `git status --porcelain` guard |
| FR-3 (paths-ignore escape) | Epic 1 / Story 1.2 | dedicated unfiltered workflow file |
| FR-9 (prune stale public docs) | Epic 1 / Story 1.1 | `copy-docs.mjs` prunes `ui/public/docs/` to exact set |
| FR-8 (canonical fix command — Phase 1 half) | Epic 1 / Story 1.2 | fix-command text in CI output + guard script |
| FR-4 (offline deterministic OpenAPI export) | Epic 2 / Story 2.1 | reuses stubbed-settings `app.openapi()` recipe; canonical JSON serialization |
| FR-7 (`openapi.json` snapshot freshness) | Epic 2 / Story 2.2 | regenerate + `git status --porcelain` guard, backend-toolchain job |
| FR-5 (banner determinism + `npx`→pinned binary + stance) | Epic 2 / Story 2.3 | `gen-types.mjs` edits |
| FR-2 (`types.ts` freshness gate) | Epic 2 / Story 2.3 | regenerate from snapshot + guard |
| FR-8 (canonical fix command — Phase 2 chained half) | Epic 2 / Story 2.4 | `scripts/regen-generated-artifacts.sh` + wiring |
| FR-6 (determinism verification) | Epic 1 Story 1.2 + Epic 2 Story 2.4 | clean-tree assertion in each gate's negative-test harness |

All spec FRs (FR-1 … FR-9) are covered. The spec defines two phases; **this plan covers both** (Epic 1 = Phase 1, Epic 2 = Phase 2). [`phase2_idea.md`](phase2_idea.md) remains as the standalone record if execution ships Epic 1 alone.

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD (two epics, one per spec phase).

### Conventions (project-specific)

```
- Shell guards live in scripts/ci/*.sh, are bash, carry the SPDX header (reuse-lint gate),
  and follow the verify_install_builds_all_services.sh structure (set -euo pipefail, a
  fail() helper, a final "OK" echo). Each has a sibling test_<name>.sh self-test
  (mirroring scripts/ci/test_check_no_env_files.sh).
- The cross-cutting regen wrapper lives at scripts/ (repo root), is bash, SPDX-headed.
- Backend Python is imported as `backend.app.*` (pyproject packages=["backend"]).
- The offline exporter reuses the PROVEN import-clean recipe: set DATABASE_URL_FILE,
  POSTGRES_PASSWORD_FILE (dummy tmpdir files), REDIS_URL, then `from backend.app.main import app;
  app.openapi()` — exactly as backend/tests/contract/test_data_table_query_params.py does.
  This is FR-4 path (a); no live DB/Redis/ES needed (settings only READ the files, no connection
  is opened at import or at app.openapi() time).
- Workflow YAML follows .github/workflows/secrets-defense.yml for the "own-file, runs-every-PR"
  pattern. New jobs added to pr.yml follow the license-inventory job structure.
- Every new tracked file carries the SPDX header (reuse-lint CI gate rejects missing headers).
- Commits: conventional-commit + `git commit -s` (DCO).
```

### AI Agent Execution Protocol (per story)

0. Read `architecture.md` + `state.md` first.
1. Read story scope + DoD.
2. Implement the tooling (JS/shell/Python).
3. Run the story's negative-test harness locally (dirty a target → assert fail; clean tree → assert pass).
4. Run `make lint` (ruff for any Python) + `cd ui && pnpm lint` (for JS edits) + `pnpm --dir ui exec prettier --check` on touched JS.
5. Verify determinism: on a clean checkout, run the regen step and assert `git status --porcelain` is empty for the gated paths.
6. Update docs (`docs/05_quality/testing.md`) in the same PR.
7. Attach evidence in the PR: commands run + pass/fail.

---

## Epic 1 — Phase 1: `copy-docs` freshness gate (FR-1, FR-3, FR-9, FR-8 Phase-1 half, FR-6 docs half)

**Epic gate (hard stop):** a docs-only PR that edits a `docs/08_guides/*.md` without re-syncing `ui/public/docs/` fails the dedicated `copy-docs-freshness` workflow; a clean tree passes; a removed `DOCS` entry leaves no stale `ui/public/docs/<old>.md`. No backend code, no new deps.

### Story 1.1 — `copy-docs.mjs` prunes to an exact generated set
**Outcome:** running `node ui/scripts/copy-docs.mjs` makes `ui/public/docs/` contain exactly `{README.md} ∪ {DOCS[].dest}` — copying current guides AND deleting any obsolete `*.md` left from a removed/renamed `DOCS` entry. (FR-9.)

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/scripts/copy-docs.prune.test.ts` | Vitest: assert that after a simulated `DOCS`-entry removal, the obsolete public copy is pruned; and that a clean run leaves the dir at the exact expected set. |

**Modified files**

| File | Change |
|---|---|
| `ui/scripts/copy-docs.mjs` | After the existing copy loop + README write, prune: read `ui/public/docs/*.md`, compute the expected set `{'README.md'} ∪ DOCS.map(d => d.dest)`, `unlinkSync` any `.md` not in the set. Keep the `import.meta.url`-based path resolution (already cwd-robust). |

**Key interfaces** (JS — no Python)

```js
// ui/scripts/copy-docs.mjs — added after the copy loop
const expected = new Set(['README.md', ...DOCS.map((d) => d.dest)]);
for (const f of readdirSync(destDir)) {
  if (f.endsWith('.md') && !expected.has(f)) {
    unlinkSync(join(destDir, f));
    console.log(`[copy-docs] pruned obsolete public/docs/${f}`);
  }
}
```

**Tasks**
1. Add the prune block to `copy-docs.mjs` (import `readdirSync`, `unlinkSync` from `node:fs`).
2. Confirm the script still runs idempotently on the current tree (no spurious deletes — the 3 current `DOCS` dests + `README.md` are the exact set).
3. Write the vitest in `ui/src/__tests__/scripts/` exercising prune (the test copies the script's `DOCS`-derived logic or runs the script against a tmp dir). Prefer running the script in a tmp `public/docs` via an `OPENAPI`/dir override or by invoking the prune logic directly if the script is refactored to export it; if neither is clean, drive it via a child-process run against a temp `ui/public/docs` symlink/copy and assert the resulting file set.

**Definition of Done**
- `(cd ui && node scripts/copy-docs.mjs)` on a clean tree leaves `git status --porcelain -- ui/public/docs/` empty (no spurious deletes). (FR-9, FR-6 docs-half.)
- Vitest proves: removing a `DOCS` entry → the obsolete `ui/public/docs/<old>.md` is deleted by the run (AC-11).
- Vitest (or the same test) proves cwd-robustness: running the script from the repo root and from `ui/` against the same fixture produces identical `ui/public/docs` output (FR-1 cwd-equivalence — the script resolves paths via `import.meta.url`).
- `cd ui && pnpm lint && pnpm --dir ui exec prettier --check scripts/copy-docs.mjs` clean; `pnpm test` green.

### Story 1.2 — dedicated `copy-docs-freshness` CI workflow
**Outcome:** a new workflow runs on **every** PR to `main` (no `paths` filter), regenerates the public docs, and fails — with a one-paste fix command — if `git status --porcelain -- ui/public/docs/` is non-empty (modified, untracked, or deleted). (FR-1, FR-3, FR-8 Phase-1, FR-6.)

**New files**

| File | Purpose |
|---|---|
| `.github/workflows/copy-docs-freshness.yml` | Standalone workflow (mirrors `secrets-defense.yml`): `on: pull_request: branches: [main]` with NO `paths`/`paths-ignore`; one job: checkout → pnpm/node setup → `pnpm --dir ui install --frozen-lockfile` → run the guard. |
| `scripts/ci/verify_copy_docs_fresh.sh` | Bash guard: `cd ui && node scripts/copy-docs.mjs` then fail if `git status --porcelain -- ui/public/docs/` is non-empty; on failure print the FR-8 Phase-1 fix command. SPDX-headed. |
| `scripts/ci/test_verify_copy_docs_fresh.sh` | Self-test (mirrors `test_check_no_env_files.sh`) in a temp git worktree: (1) clean tree → guard exits 0; (2) **source-drift case (NOT output-mutation)** — edit a **source** `docs/08_guides/quick-tour.md` while leaving the committed `ui/public/docs/quick-tour.md` unchanged, run the guard → it regenerates the public copy, the tree goes dirty, guard exits non-zero AND stdout contains the fix-command text. (Mutating the *output* `ui/public/docs/*.md` directly is INVALID — the guard runs `copy-docs.mjs` first, overwriting the edit back to clean bytes from the unchanged source.) (3) **genuine untracked AC-9 case** — `git rm --cached ui/public/docs/quick-tour.md` (file stays on disk, leaves the index), run the guard, assert `git status --porcelain` shows `?? ui/public/docs/quick-tour.md` and non-zero exit. **Note:** an arbitrary unexpected file like `zzz.md` is NOT a valid untracked test — Story 1.1's prune deletes it before the `git status` check. The prune-behavior assertion (add `zzz.md` → run deletes it → tree clean) lives in the Story 1.1 vitest. |

**Modified files**

| File | Change |
|---|---|
| `docs/05_quality/testing.md` | Add a "Generated-artifact freshness gates" subsection documenting this gate + its one-paste fix. |

**Endpoints / Schemas:** N/A (CI/tooling story).

**Key interfaces** (bash)

```bash
# scripts/ci/verify_copy_docs_fresh.sh
set -euo pipefail
( cd ui && node scripts/copy-docs.mjs )
if [[ -n "$(git status --porcelain -- ui/public/docs/)" ]]; then
  echo "ERROR: ui/public/docs/ is stale. Fix with:"
  echo "  cd ui && node scripts/copy-docs.mjs && git add public/docs"
  git status --porcelain -- ui/public/docs/   # diagnostic only
  exit 1
fi
echo "OK: ui/public/docs/ is fresh."
```

**Tasks**
1. Write `verify_copy_docs_fresh.sh` (SPDX header, `set -euo pipefail`, the check above; uses `git status --porcelain`, NOT `git diff`).
2. Write `test_verify_copy_docs_fresh.sh` covering clean / modified / untracked cases + fix-command-text assertion.
3. Add `.github/workflows/copy-docs-freshness.yml` — pull_request to main, NO `paths` filter, pnpm install --frozen-lockfile, run the guard.
4. Document in `docs/05_quality/testing.md`.

**Definition of Done**
- Workflow runs on a docs-only PR (verified by FR-3 logic: no `paths` filter) (AC-3).
- Guard fails when a **source** guide (`docs/08_guides/quick-tour.md`) is edited without re-syncing, with the fix command in output (AC-1); passes on a clean tree (AC-2); fails on a genuine untracked public-docs file (`git rm --cached` case) (AC-9).
- `bash scripts/ci/test_verify_copy_docs_fresh.sh` exits 0 (all sub-cases pass).
- Conventional-commit + `-s` DCO.

---

## Epic 2 — Phase 2: offline OpenAPI export + `types.ts` freshness gate (FR-4, FR-7, FR-5, FR-2, FR-8 Phase-2, FR-6 types half)

**Epic gate (hard stop):** the offline exporter emits canonical, deterministic `openapi.json` with **no** live DB/Redis/ES/OpenSearch and no running server; the committed `ui/openapi.json` snapshot is freshness-gated; `gen-types.mjs` uses the pinned binary + a source-invariant banner; `types.ts` is freshness-gated against the snapshot; the chained one-paste fix command makes both green. All artifacts freshened in the introducing PR.

### Story 2.1 — offline, deterministic OpenAPI exporter
**Outcome:** `python -m backend.app.openapi_export --out ui/openapi.json` (and stdout when `--out` omitted) writes the canonical OpenAPI schema with no live services, reusing the proven stubbed-settings recipe. (FR-4.)

**New files**

| File | Purpose |
|---|---|
| `backend/app/openapi_export.py` | CLI entrypoint. Sets dummy `*_FILE` env vars in a tmpdir if not already set (honoring Absolute Rule #2 — `*_FILE` mounted pattern, never bare secret), imports `from backend.app.main import app`, builds `app.openapi()`, emits canonical JSON. `--out <path>` writes atomically (tmp file + `os.replace`); no flag → stdout. All diagnostics → stderr. |
| `backend/tests/unit/test_openapi_export.py` | Unit: invoke the exporter's build function with no live services; assert the returned object is a dict with keys `openapi`, `info`, `paths` and at least one known route (`/api/v1/studies` or `/healthz`); assert canonical serialization is byte-stable across two calls. |

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | (Optional) add a `[project.scripts]` console entry `relyloop-openapi-export = "backend.app.openapi_export:main"` if a console script is preferred over `python -m`. Decide at implementation; `python -m` works without it. |

**Key interfaces** (Python)

```python
# backend/app/openapi_export.py
def build_openapi() -> dict:                      # import-clean; no live services
    # ensure dummy *_FILE env vars exist (tmpdir), then:
    from backend.app.main import app
    return app.openapi()

def serialize(schema: dict) -> str:               # canonical bytes
    import json
    return json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"

def main() -> None: ...                            # argparse --out; atomic write or stdout; diagnostics->stderr
```

> **Import-cleanliness (resolves spec §19 open question):** the proven recipe is already in `backend/tests/contract/test_data_table_query_params.py:27-43` — set `DATABASE_URL_FILE`, `POSTGRES_PASSWORD_FILE` (dummy tmpdir files), `REDIS_URL`, `get_settings.cache_clear()`, then `from backend.app.main import app; app.openapi()`. This is FR-4 **path (a)**. `app.openapi()` builds the schema from route signatures + Pydantic models; no asyncpg pool / Redis / ES / OpenSearch / Solr / OpenAI client is constructed at import or schema-build time (those are built in the `lifespan` startup, which `app.openapi()` does NOT trigger). The implementer MUST confirm this holds (the unit test asserts it by running with no service containers); if a router module is later changed to open a connection at import, that is a separate regression the unit test will catch.

**Tasks**
1. **Import-graph spike + decision artifact (FR-4 requirement).** Before writing the CLI, record a short decision block at the top of `openapi_export.py` (module docstring) capturing: the import target (`backend.app.main.app`); the exact env vars + dummy files the import requires (`DATABASE_URL_FILE`, `POSTGRES_PASSWORD_FILE` → tmpdir files; `REDIS_URL` → non-secret bare value, allowed because it is non-secret config per CLAUDE.md Settings rules); and the confirmed **absence** of asyncpg-pool / Redis / ES / OpenSearch / Solr / OpenAI-client construction during import and `app.openapi()` (those build in `lifespan`, which `app.openapi()` does not trigger). This is FR-4 path (a). The `test_openapi_export.py` unit test is the executable enforcement of this decision (runs with no service containers).
2. Write `backend/app/openapi_export.py` with `build_openapi()`, `serialize()`, `main()` (argparse `--out`, atomic write via tmp + `os.replace`, stdout otherwise, all diagnostics to stderr). Distinguish in code/comment the `*_FILE`-mounted secret stand-ins (DATABASE_URL_FILE, POSTGRES_PASSWORD_FILE — Absolute Rule #2) from the non-secret bare `REDIS_URL`.
3. Reuse the dummy-`*_FILE` env setup from `backend/tests/contract/test_data_table_query_params.py:27-43`; place the env-stub in `build_openapi()` (only setting vars not already present) so the CLI works on a bare CI runner.
4. Write `test_openapi_export.py`: parse-and-assert keys (NOT a string prefix — `sort_keys=True` alphabetizes top-level keys); assert byte-stability across two `serialize(build_openapi())` calls; assert it runs with no service containers reachable.
5. `make lint && make typecheck` (ruff + mypy --strict) clean for the new module.

**Definition of Done**
- `python -m backend.app.openapi_export` exits 0 and emits valid OpenAPI JSON with **no** Postgres/Redis/ES/OpenSearch/server (AC-4) — the unit test runs with no service containers.
- Output is byte-deterministic (canonical `json.dumps`, trailing newline) across repeated runs (AC-7 backend half).
- `test_openapi_export.py` asserts parsed keys, not a leading prefix (FR-4 / AC-4 corrected).
- mypy --strict + ruff clean.

### Story 2.2 — commit `ui/openapi.json` snapshot + snapshot-freshness gate
**Outcome:** a committed `ui/openapi.json` (exact exporter bytes) plus a CI guard that regenerates it and fails on `git status --porcelain` drift. (FR-7, FR-6.)

**New files**

| File | Purpose |
|---|---|
| `ui/openapi.json` | Committed canonical snapshot — the exact bytes `python -m backend.app.openapi_export` produces. SPDX header is N/A for a pure-JSON data file; confirm `REUSE.toml` covers it (add a `.license` / `REUSE.toml` annotation if reuse-lint flags it — see Risk R-3). |
| `scripts/ci/verify_openapi_snapshot_fresh.sh` | Bash guard: run the exporter to `ui/openapi.json`, fail if `git status --porcelain -- ui/openapi.json` non-empty; print FR-8 fix command. Needs the backend `uv` toolchain. |
| `scripts/ci/test_verify_openapi_snapshot_fresh.sh` | Self-test in a temp git worktree: (1) clean tree → exit 0; (2) **source-drift case** — change the OpenAPI schema at its source so regeneration produces different bytes (preferred: a small temp-worktree backend route/model edit that alters `app.openapi()`; fallback: the guard supports a test-only generator override so the self-test writes a different valid canonical JSON). Mutating the committed `ui/openapi.json` *output* directly is INVALID — the guard regenerates it from the unchanged backend, overwriting the edit. (3) **genuine untracked case** — `git rm --cached ui/openapi.json` (file stays on disk, leaves the index), run the guard, assert `git status --porcelain -- ui/openapi.json` reports `??` + non-zero exit. |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | Add a `generated-artifacts-fresh` job running the snapshot guard (2.2) + the types guard (2.3). Models the `license-inventory` job, which sets up **both** toolchains: `uv sync --frozen` (for the exporter) AND Node/pnpm + **`pnpm --dir ui install --frozen-lockfile`** (required so `gen-types.mjs`'s pinned `openapi-typescript` binary exists in `ui/node_modules` — a GHA job does not inherit the frontend job's install). Source paths (`backend/**`, `ui/**`) are NOT under `paths-ignore`, so no dedicated workflow needed. |
| `docs/05_quality/testing.md` | Extend the freshness-gates subsection with the snapshot + types gates + their chained fix command. |

**Key interfaces** (bash)

```bash
# scripts/ci/verify_openapi_snapshot_fresh.sh
set -euo pipefail
uv run python -m backend.app.openapi_export --out ui/openapi.json
if [[ -n "$(git status --porcelain -- ui/openapi.json)" ]]; then
  echo "ERROR: ui/openapi.json is stale. Fix with:"
  echo "  uv run python -m backend.app.openapi_export --out ui/openapi.json && git add ui/openapi.json"
  exit 1
fi
echo "OK: ui/openapi.json is fresh."
```

**Tasks**
1. Generate + commit `ui/openapi.json` via the exporter (the introducing PR must freshen it — §16 rollout).
2. Write `verify_openapi_snapshot_fresh.sh` + its self-test (clean / source-drift / untracked cases per §3.4).
3. Add the `generated-artifacts-fresh` job to `pr.yml`: `uv sync --frozen` + Node/pnpm + `pnpm --dir ui install --frozen-lockfile` (required for the types guard's pinned binary), running the snapshot guard first.
4. Verify `reuse-lint` accepts `ui/openapi.json` (Risk R-3); add the annotation if needed.

**Definition of Done**
- A backend schema change without regenerating the snapshot fails the gate with the fix command (AC-5).
- `bash scripts/ci/test_verify_openapi_snapshot_fresh.sh` exits 0.
- The committed `ui/openapi.json` matches the exporter output (clean `git status` on a fresh run).

### Story 2.3 — `gen-types.mjs` determinism fix + `types.ts` freshness gate
**Outcome:** `gen-types.mjs` invokes the lockfile-pinned `openapi-typescript` (not `npx`), emits a source-invariant banner, and the CI gate regenerates `types.ts` from the committed snapshot and fails on drift. (FR-5, FR-2, FR-6.)

**Modified files**

| File | Change |
|---|---|
| `ui/scripts/gen-types.mjs` | (1) Replace `execSync('npx openapi-typescript ...')` with the pinned binary: `pnpm exec openapi-typescript ...` (or `node_modules/.bin/openapi-typescript`), and fail if the binary is absent (no implicit `npx` download). (2) Make the banner source-invariant: drop the interpolated `${SOURCE_URL}` from the `Source:` line (use a stable phrase like `Source: backend OpenAPI schema (ui/openapi.json)`); remove the false "CI does NOT regenerate this file" sentence; state the file is CI-freshness-gated. (3) **Extract `buildBanner()` into a side-effect-free module** — `ui/scripts/gen-types-banner.mjs` (pure, no `OPENAPI_URL` input, no generation) imported by both `gen-types.mjs` and the test. Also guard `gen-types.mjs`'s generation behind an ESM entrypoint check (`import.meta.url === pathToFileURL(process.argv[1]).href`) so importing it never shells out to `openapi-typescript` or mutates `types.ts`. |
| `.github/workflows/pr.yml` | **(Cross-story sequential edit — intentional.)** Story 2.2 adds the `generated-artifacts-fresh` job with the snapshot guard step; this story appends the types-guard step to that same job. Listed here so the ownership boundary is explicit: 2.2 creates the job, 2.3 adds the second step. |

**New files**

| File | Purpose |
|---|---|
| `scripts/ci/verify_types_fresh.sh` | Bash guard: `OPENAPI_URL="$PWD/ui/openapi.json" pnpm --dir ui types:gen` (the spec-locked package-script invocation — FR-2; `gen-types.mjs` itself uses the pinned binary after Story 2.3), then fail if `git status --porcelain -- ui/src/lib/types.ts` non-empty; print the FR-8 chained fix command. |
| `scripts/ci/test_verify_types_fresh.sh` | Self-test in a temp git worktree: (1) clean tree → 0; (2) **source-drift case** — mutate the committed `ui/openapi.json` to a valid-but-different OpenAPI document (the *source* for `types:gen`), run the guard → `types.ts` regenerates differently, tree goes dirty, non-zero + fix-command text. (Mutating the `types.ts` *output* directly is INVALID — the guard regenerates it from the unchanged snapshot, overwriting the edit.) (3) untracked case — `git rm --cached ui/src/lib/types.ts`, run guard, assert `??` + non-zero. |
| `ui/scripts/gen-types-banner.mjs` | Pure, side-effect-free module exporting `buildBanner()` (source-invariant; no `OPENAPI_URL` input, no generation). Imported by `gen-types.mjs` + the test. |
| `ui/src/__tests__/scripts/gen-types-banner.test.ts` | Vitest: import `gen-types-banner.mjs` and assert `buildBanner()` is byte-identical regardless of any source value (AC-8 automated). Importing the module MUST NOT run `openapi-typescript` or touch `ui/src/lib/types.ts`. |

**Tasks**
1. Edit `gen-types.mjs`: pinned-binary invocation (`pnpm exec openapi-typescript` / `node_modules/.bin`, fail if missing — no `npx`) + extract `buildBanner()` (source-invariant) + stance reconciliation.
2. **Verify the source form** (spec §19 / FR-2 open item): confirm `openapi-typescript` accepts an absolute filesystem path (`OPENAPI_URL="$PWD/ui/openapi.json"`); if it requires `file://`, switch the command + banner phrasing + AC-8 accordingly. Document the verified form in `docs/05_quality/testing.md`.
3. Add `gen-types-banner.test.ts` asserting `buildBanner()` is invariant across `OPENAPI_URL` values (automated AC-8 — not a manual confirm). Also regenerate `ui/src/lib/types.ts` from the snapshot (freshen it in the introducing PR).
4. Write `verify_types_fresh.sh` using the canonical `pnpm --dir ui types:gen` invocation + its self-test (clean/mutated/untracked); append the types-guard step to the `generated-artifacts-fresh` job (add `pr.yml` to this story's Modified files — the cross-story sequential edit on top of Story 2.2's job).

**Definition of Done**
- `types.ts` drift against the snapshot fails the gate with the chained fix command (AC-6).
- Banner is byte-identical regardless of generation source (AC-8) — proven by the automated `gen-types-banner.test.ts`.
- **Importing `gen-types-banner.mjs` (or `gen-types.mjs`) runs no generation and does not modify `ui/src/lib/types.ts`** (generation is behind the ESM entrypoint guard).
- `gen-types.mjs` never shells out to `npx` (grep the file: no `npx`); fails loudly if the pinned binary is missing.
- `cd ui && pnpm --dir ui exec prettier --check scripts/gen-types.mjs` clean.

### Story 2.4 — canonical chained fix command + determinism wrap-up
**Outcome:** a single repo-root script regenerates all Phase-2 artifacts; CI failure output + docs reference it; a clean-tree determinism check passes. (FR-8 Phase-2, FR-6.)

**New files**

| File | Purpose |
|---|---|
| `scripts/regen-generated-artifacts.sh` | One-paste fix using the **canonical** invocations (matches CI + spec FR-2/FR-8): `uv run python -m backend.app.openapi_export --out ui/openapi.json && (cd ui && OPENAPI_URL="$PWD/openapi.json" pnpm types:gen && node scripts/copy-docs.mjs) && git add ui/openapi.json ui/src/lib/types.ts ui/public/docs`. SPDX-headed. Note: `types:gen` (package script) + `(cd ui && node scripts/copy-docs.mjs)` are the single canonical forms used identically in CI guards, this wrapper, and the docs. |

**Modified files**

| File | Change |
|---|---|
| `scripts/ci/verify_openapi_snapshot_fresh.sh`, `verify_types_fresh.sh` | Point the printed fix command at `scripts/regen-generated-artifacts.sh` so CI + docs reference one source of truth. |
| `docs/05_quality/testing.md` | Document `scripts/regen-generated-artifacts.sh` as the single regen command. |
| `CLAUDE.md` | (Optional, low-priority) add a one-line "Generated artifacts are CI-freshness-gated; regenerate via `scripts/regen-generated-artifacts.sh`" note under Key Conventions. |

**Tasks**
1. Write `scripts/regen-generated-artifacts.sh` (substitute the verified source form from Story 2.3).
2. Update the two guards' fix-command output to reference it.
3. Add a clean-tree determinism assertion to the `generated-artifacts-fresh` job (after both guards, assert `git status --porcelain -- ui/openapi.json ui/src/lib/types.ts ui/public/docs` empty) (AC-7).
4. Document; optional CLAUDE.md note.

**Definition of Done**
- Running `scripts/regen-generated-artifacts.sh` then committing makes both Phase-2 gates green (AC-10).
- Clean-tree determinism check passes in CI (AC-7).
- Conventional-commit + `-s`.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/`, `ui/src/__tests__/`
- Tasks:
  - [ ] `backend/tests/unit/test_openapi_export.py` — no-live-services build + canonical byte-stability + parsed-keys assertion (Story 2.1).
  - [ ] `ui/src/__tests__/scripts/copy-docs.prune.test.ts` — prune-on-removed-entry + exact-set + cwd-equivalence (Story 1.1).
  - [ ] `ui/src/__tests__/scripts/gen-types-banner.test.ts` — `buildBanner()` invariant across `OPENAPI_URL` (AC-8 automated, Story 2.3).
- DoD: exporter import-cleanliness + prune behavior + banner invariance covered deterministically.

### 3.2 Integration tests
- N/A — no DB-backed workflow. The "integration" surface here is the CI guards, covered by their shell self-tests (§3.4-equivalent below).

### 3.3 Contract tests
- N/A — no HTTP endpoints. (The existing `backend/tests/contract/test_openapi_surface.py` + `test_data_table_query_params.py` already assert OpenAPI shape; this feature adds no endpoints, so no new contract test. The exporter's output is the *same* `app.openapi()` those tests already validate.)

### 3.4 Shell-guard self-tests (this feature's "integration" layer)
- Location: `scripts/ci/test_*.sh` (mirrors `scripts/ci/test_check_no_env_files.sh`)
- Tasks:
  - [ ] `test_verify_copy_docs_fresh.sh` — clean / modified / untracked cases + fix-command text (Story 1.2).
  - [ ] `test_verify_openapi_snapshot_fresh.sh` — clean / mutated / deleted cases (Story 2.2).
  - [ ] `test_verify_types_fresh.sh` — clean / mutated cases + fix-command text (Story 2.3).
- DoD: each guard's failure path AND happy path is exercised in a temp git worktree; no guard uses a bare `git diff` (untracked-file regression guard).

### 3.5 E2E tests
- N/A — no user journey, no UI route.

### 3.5b Existing test impact audit
| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/contract/test_openapi_surface.py` | `app.openapi()` endpoint list | 1 | No change — the exporter emits the same schema; this test continues to guard endpoint presence. |
| `backend/tests/contract/test_data_table_query_params.py` | stubbed-settings `app.openapi()` | 1 | No change — the exporter reuses its import recipe; if anything, this test proves the recipe works. |
| `ui/src/lib/types.ts` consumers | generated types | many | No change — `types.ts` content is unchanged by this feature (only its banner + the freshness gate are added); the introducing PR regenerates it once so consumers see no semantic diff. |

### 3.6 Migration verification
- N/A — no schema change. Alembic head stays `0022_solr_engine_auth_check`.

### 3.6b CI gates (this feature)
- [ ] `bash scripts/ci/test_verify_copy_docs_fresh.sh`
- [ ] `bash scripts/ci/test_verify_openapi_snapshot_fresh.sh`
- [ ] `bash scripts/ci/test_verify_types_fresh.sh`
- [ ] `make test-unit` (picks up `test_openapi_export.py`)
- [ ] `cd ui && pnpm test` (picks up the prune vitest)
- [ ] `make lint && make typecheck`

---

## 4) Documentation update workstream

### 4.0 Core context files
- **`state.md`** — [ ] add the merge one-liner to "Last 5 merges"; note no Alembic move; no branch change beyond the feature branch.
- **`architecture.md`** — [ ] optional one-line note under "Dashboard regen" / a new "Generated artifacts" pointer that `ui/openapi.json` + `types.ts` + `ui/public/docs` are CI-freshness-gated.
- **`CLAUDE.md`** — [ ] optional Key-Conventions note (Story 2.4) naming `scripts/regen-generated-artifacts.sh`.

### 4.5 Quality docs (`docs/05_quality`)
- [ ] `testing.md` — "Generated-artifact freshness gates" subsection: the three gates, the dedicated `copy-docs-freshness` workflow, the `generated-artifacts-fresh` `pr.yml` job, and the single `scripts/regen-generated-artifacts.sh` fix command.

### 4.1–4.4
- `docs/01_architecture` — N/A (optional tech-stack one-liner). `docs/02_product` — N/A. `docs/03_runbooks` — N/A (the fix command is self-documenting in CI output; testing.md covers it). `docs/04_security` — N/A.

**Documentation DoD**
- [ ] `testing.md` documents all three gates + the one-paste fix.
- [ ] `state.md` merge one-liner added.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Centralize the three guards' "regenerate → `git status --porcelain` → print fix command → exit" shape; if the three `verify_*.sh` scripts share >15 lines, extract a `scripts/ci/_freshness_lib.sh` sourced helper. Bounded — do not redesign the existing `scripts/ci/` guards.

### 5.2 Planned refactor tasks
- [ ] (Optional) extract `scripts/ci/_freshness_lib.sh` with a `fail_if_dirty <fix-cmd> -- <paths...>` function if duplication crosses the threshold.
- [ ] `gen-types.mjs` `npx`→pinned-binary is the only behavior change to existing tooling; no dead branches removed.

### 5.3 Refactor guardrails
- [ ] Each guard's self-test proves behavioral parity (clean/dirty/untracked).
- [ ] `pnpm --dir ui exec prettier --check` + `make lint` green.
- [ ] No product-scope expansion.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `app.openapi()` import-clean via stubbed `*_FILE` env | Story 2.1 | **Proven** (`test_data_table_query_params.py`) | None — recipe exists; unit test re-verifies. |
| `openapi-typescript` pinned via `pnpm-lock.yaml` | Story 2.3 | Implemented (`ui/package.json`) | If absent, `pnpm exec` fails loudly (intended). |
| `secrets-defense.yml` unfiltered-workflow precedent | Story 1.2 | Implemented | None. |
| `license-inventory` job structure precedent | Story 2.2 | Implemented | None. |
| `uv sync --frozen` in CI | Story 2.2 | Implemented (used by backend jobs) | None. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| R-1: `openapi-typescript` / `app.openapi()` output non-deterministic across macOS↔Linux | M | H (gate flakes) | FR-4 canonical `json.dumps(sort_keys=True)` on the snapshot; AC-7 clean-tree assertion runs in CI on Linux; if `openapi-typescript` itself differs, add a normalization step (mirroring `gen_license_inventory.py` platform-collapse). Verify on the introducing PR's first CI run. |
| R-2: absolute-path source form not accepted by `openapi-typescript` | L | M | Story 2.3 Task 2 verifies the form; fall back to `file://` + update command/banner/AC-8. |
| R-3: `reuse-lint` rejects `ui/openapi.json` (no SPDX header possible in pure JSON) | M | L | Add a `REUSE.toml` annotation or `.license` sidecar for `ui/openapi.json` (the repo already uses `REUSE.toml`); verified in Story 2.2 Task 4. |
| R-4: the introducing PR's gate fails on its own stale artifacts | H (expected) | L | §16 rollout: freshen `ui/openapi.json` + `types.ts` + `ui/public/docs` in the introducing PR (the whole point). |
| R-5: a future router opens a connection at import time, breaking the offline exporter | L | M | `test_openapi_export.py` runs with no service containers and fails if a connection is attempted — turning the regression into a unit-test failure, not a silent CI hang. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Stale public doc | guide edited, public copy not re-synced | `copy-docs-freshness` workflow fails with fix command | Run `cd ui && node scripts/copy-docs.mjs && git add public/docs` |
| Stale snapshot | backend schema changed, snapshot not regenerated | `generated-artifacts-fresh` job fails (snapshot guard) | Run `scripts/regen-generated-artifacts.sh` |
| Stale types | snapshot changed, types not regenerated | `generated-artifacts-fresh` job fails (types guard) | Run `scripts/regen-generated-artifacts.sh` |
| Exporter import failure | a router opens a connection at import | exporter exits non-zero with the traceback | Fix the offending router (build-config bug, not drift) |
| Untracked generated file | new `DOCS` entry / first snapshot commit omitted | guard fails (uses `git status --porcelain`) | `git add` the new file |

## 7) Sequencing and parallelization

### Suggested sequence
1. Epic 1 (Story 1.1 → 1.2) — Phase 1, zero infra, immediately valuable.
2. Epic 2 (Story 2.1 → 2.2 → 2.3 → 2.4) — Phase 2, in order (exporter → snapshot+gate → types fix+gate → chained fix).

### Parallelization
- Story 1.1 and Story 2.1 are independent (JS prune vs Python exporter) and can run in parallel.
- Within Epic 2, 2.2/2.3/2.4 are sequential (each consumes the prior's artifact/script).

## 8) Rollout and cutover plan

- No feature flags. Additive CI jobs.
- **Introducing PR must freshen all artifacts** (`ui/public/docs/*`, `ui/openapi.json`, `ui/src/lib/types.ts`) so the new gates pass on their own PR (§16, R-4).
- **Branch protection (operator handoff):** these gates report but do not hard-block until the operator adds them as required status checks — `main` currently has no required-status-checks rule (removed 2026-05-31). The agent cannot change branch protection; surface this in the PR description as an operator follow-up. The unfiltered `copy-docs-freshness` workflow (FR-3) reports a real pass/fail on every PR, so if later made required it avoids GitHub's skipped-required-check pitfall.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — copy-docs prune
- [ ] Story 1.2 — copy-docs-freshness workflow + guard
- [ ] Story 2.1 — offline OpenAPI exporter
- [ ] Story 2.2 — snapshot + snapshot-freshness gate
- [ ] Story 2.3 — gen-types.mjs fix + types gate
- [ ] Story 2.4 — chained fix command + determinism wrap-up

## 10) Story-by-Story Verification Gate (Agent Checklist)

- [ ] Files created/modified match story scope.
- [ ] No HTTP endpoints / migrations introduced (verify: no new router, no new `migrations/versions/*`).
- [ ] Each guard uses `git status --porcelain` (grep the guard: no bare `git diff --exit-code` as the pass/fail check).
- [ ] Shell self-tests added + green for clean/dirty/untracked cases.
- [ ] `gen-types.mjs` has no `npx` (grep).
- [ ] Commands executed and passed: `make test-unit`, `cd ui && pnpm test`, `make lint`, `make typecheck`, the three `scripts/ci/test_*.sh`.
- [ ] No schema change (Alembic head unchanged).
- [ ] Docs (`testing.md`) updated in the same PR.

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** spec §8 has **0 HTTP endpoints** (only a CLI exporter). Plan adds 0 endpoints. Match.
2. **Spec ↔ plan FR coverage:** FR-1…FR-9 all mapped in §1 to a story. Verified.
3. **Story internal consistency:** file ownership is clean except two **intentional, declared** cross-story sequential edits: (a) `.github/workflows/pr.yml` — Story 2.2 creates the `generated-artifacts-fresh` job (snapshot step), Story 2.3 appends the types step (both stories list `pr.yml` in Modified files with the boundary noted); (b) `docs/05_quality/testing.md` — touched by 1.2/2.2/2.4 as additive sections (last writer reconciles). All other files have a single owner (1.1: `copy-docs.mjs` + prune/cwd test; 1.2: copy-docs workflow + guard + self-test; 2.1: exporter + its unit test; 2.2: snapshot + snapshot guard + self-test; 2.3: `gen-types.mjs` + types guard + banner test; 2.4: regen wrapper).
4. **Error code coverage:** spec §7.5 = N/A (no error codes). Match.
5. **Enumerated value contracts:** N/A — no `<select>`/filter/badge/sort values (spec §7.4 N/A). No source-of-truth comment needed.
6. **Audit-event coverage:** N/A — no state mutation (spec §6 N/A). No `audit_log` story needed.
7. **Test file assignment:** every test file (`test_openapi_export.py`, `copy-docs.prune.test.ts`, three `scripts/ci/test_*.sh`) is owned by exactly one story (2.1, 1.1, 1.2/2.2/2.3 respectively). No orphans.
8. **Gate arithmetic:** Epic 1 gate = copy-docs paths only (2 stories). Epic 2 gate = exporter + snapshot + types + chained fix (4 stories). Consistent.
9. **Infra path verification:** `scripts/ci/` exists (verified `ls`); `.github/workflows/` exists; backend import root is `backend.app.*` (verified `pyproject.toml packages=["backend"]`); no Alembic dir touched.
10. **Frontend data plumbing / persistence / legacy parity:** N/A — no React components, no `localStorage`, no user-facing component deleted. No Legacy Behavior Parity table required (no user-facing component >100 LOC deleted/migrated — only `copy-docs.mjs`/`gen-types.mjs` build scripts edited).
11. **Open questions resolved:** spec §19 FR-4 import-path question is resolved here (path (a), proven recipe from `test_data_table_query_params.py`); FR-2 source-form is locked to absolute path with a Story 2.3 verification task; the pre-commit-hook question stays deferred (out of scope per spec).

## 12) Definition of plan done

- [x] Every FR (FR-1…FR-9) mapped to stories/tests/docs.
- [x] Every story includes New/Modified files, Key interfaces, Tasks, DoD (Endpoints/Schemas N/A for this CI feature).
- [x] Test layers scoped (unit + shell-guard self-tests; integration/contract/E2E justified N/A).
- [x] Docs updates planned + owned (`testing.md`).
- [x] Lean refactor scope bounded (optional shared guard lib).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] §11 consistency review performed; no unresolved findings.
