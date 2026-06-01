# Feature Specification — CI gate for generated-artifact freshness (`types.ts` + `ui/public/docs`)

**Date:** 2026-06-01
**Status:** Draft
**Owners:** soundminds.ai (Product), RelyLoop maintainers (Engineering)
**Related docs:**
- [`idea.md`](idea.md) — origin + open-question defaults
- [`implementation_plan.md`](implementation_plan.md) — created by `/impl-plan-gen`
- Precedent: `scripts/gen_license_inventory.py --check` + the `license-inventory` job in [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml)
- Precedent: [`.github/workflows/secrets-defense.yml`](../../../../../.github/workflows/secrets-defense.yml) — the "own-workflow-file to escape `paths-ignore`" pattern

---

## 1) Purpose

Two tracked **generated artifacts** drift silently between the feature that should regenerate them and the next feature that happens to run the generator, because nothing in CI fails when a committed copy is stale.

- **Problem:** `ui/src/lib/types.ts` (regenerated from the backend OpenAPI via `pnpm types:gen`) and `ui/public/docs/*.md` (copied from `docs/08_guides/*.md` via `node scripts/copy-docs.mjs`) have no freshness gate. During `feat_overnight_autopilot`, a routine `pnpm types:gen` regenerated ~818 lines of `types.ts` that had accumulated drift from previously-merged features (Solr schemas, the `_SourceBreakdown.click` UBI bucket), and `copy-docs` revealed `tutorial-first-study.md` had never been re-synced after the Solr "Path C" section merged.
- **Outcome:** CI fails a PR whose committed `types.ts` does not match what the live OpenAPI schema would produce, and whose `ui/public/docs/*` copies do not match their `docs/08_guides/*` sources. Drift is caught at the PR that introduces it, not laundered into an unrelated later PR's diff.
- **Non-goal:** This feature does **not** auto-commit regenerated artifacts, does not change what the artifacts contain, and does not add any runtime behavior. It is a CI guard plus the minimal tooling needed to run the regeneration deterministically and offline.

## 2) Current state audit

### Existing implementations

- **`ui/scripts/gen-types.mjs`** — wraps `npx openapi-typescript <SOURCE_URL> -o src/lib/types.ts`, then re-prepends an SPDX + "GENERATED FILE" banner (openapi-typescript strips it on every run). `SOURCE_URL = process.env.OPENAPI_URL ?? 'http://localhost:8000/openapi.json'` ([`ui/scripts/gen-types.mjs:24`](../../../../../ui/scripts/gen-types.mjs)). The banner text **interpolates `${SOURCE_URL}`** into a `// Source: ...` line that lands in the committed file. The banner self-documents: *"CI does NOT regenerate this file — the committed version is the source of truth for the PR."* This spec changes that stance (CI regenerates to *compare*, never to commit).
- **`ui/scripts/copy-docs.mjs`** — pure-filesystem one-direction copy of a fixed `DOCS` array from `docs/08_guides/` → `ui/public/docs/`. Current array ([`ui/scripts/copy-docs.mjs:30-34`](../../../../../ui/scripts/copy-docs.mjs)): `tutorial-first-study.md`, `quick-tour.md`, `workflows-overview.md`. It also writes a generated `ui/public/docs/README.md` explaining the files are copied. Wired as `prebuild` + `predev` package scripts.
- **`ui/src/lib/types.ts`** — 165 KB tracked generated file; header says "GENERATED FILE — do not edit."
- **`ui/public/docs/`** — tracked copies: `README.md`, `quick-tour.md`, `tutorial-first-study.md`, `workflows-overview.md`.
- **`scripts/gen_license_inventory.py`** — **the closest precedent**. Supports `--check` (regenerate in memory, diff against the committed `docs/04_security/license-inventory.md`, exit nonzero on drift; fix by running without `--check` and committing). Critically, it had to **normalize platform-specific variants** to keep `--check` deterministic across the local-vs-CI runner ([`scripts/gen_license_inventory.py:172-173`](../../../../../scripts/gen_license_inventory.py)). The `license-inventory` job in `pr.yml` runs `uv run python scripts/gen_license_inventory.py --check`.
- **`.github/workflows/pr.yml`** — jobs: `backend-unit-fast`, `license-headers`, `license-inventory`, `static-checks-backend`, `static-checks-frontend`, `backend` (heavy, has Postgres + ES + OpenSearch service containers), `frontend` (heavy, `next build`), `smoke`, two `docker buildx`. The `pull_request` trigger carries `paths-ignore: ['docs/**', '*.md', '.gitignore', 'LICENSE', 'release-notes-*.md']` ([`.github/workflows/pr.yml:47-53`](../../../../../.github/workflows/pr.yml)). `static-checks-frontend` runs **service-free** (`prettier --check`, `eslint`, `tsc --noEmit`, `vitest`) — no API reachable.
- **`.github/workflows/secrets-defense.yml`** — established the "split into its own workflow file so it runs on EVERY PR regardless of `pr.yml`'s `paths-ignore`" pattern, explicitly motivated by `chore_ci_gitignore_paths_ignore_gap`.

### Navigation and link impact

N/A — no UI routes, links, or redirects change.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| (none) | — | 0 | No existing test asserts on `types.ts` or `ui/public/docs/*` freshness. New CI jobs + a `scripts/ci/*.sh` shell guard (or Python gate) are added; their behavior is exercised by CI itself, plus a small unit/shell self-test (see §14). |

### Existing behaviors affected by scope change

- **`gen-types.mjs` banner stance.** Current: banner asserts CI does not regenerate. New: CI regenerates *to compare only*. Decision needed: **no** — the banner text is updated in scope (§7 FR-5) to say the committed file is gate-enforced.
- **`copy-docs.mjs` invocation in CI.** Current: only runs locally via `prebuild`/`predev`. New: also runs in a CI freshness step. Decision needed: **no** — additive.

---

## 3) Scope

### In scope

- **A `copy-docs` freshness CI gate** (Phase 1): regenerate `ui/public/docs/*` from `docs/08_guides/*` in CI and fail if the working tree differs from the committed copies. Runs on every PR regardless of `paths-ignore` (see FR-3).
- **A deterministic, offline OpenAPI export** (Phase 2): a backend entrypoint that emits the canonical `openapi.json` **without a running server or live DB/ES/OpenSearch**, plus a committed `ui/openapi.json` snapshot.
- **A `types.ts` freshness CI gate** (Phase 2): regenerate `types.ts` from the committed (and itself freshness-checked) `openapi.json` snapshot and fail if the working tree differs.
- **Banner reconciliation** (FR-5): update the `gen-types.mjs` banner so it no longer contradicts the new CI behavior and so its interpolated `Source:` line is deterministic across local and CI runs.
- **Local-fix documentation** in each gate's CI step (the exact command a contributor runs to make the gate green), mirroring the `license-inventory` precedent.

### Out of scope

- Auto-committing regenerated artifacts (the gate fails; the human regenerates + commits).
- Changing the *content* of `types.ts`, the guides, or the OpenAPI schema.
- Standing up a live API service container in the frontend CI job (the offline-export approach in FR-4 deliberately avoids this).
- Adding new guides to the `copy-docs` `DOCS` array (a guide-authoring concern, tracked separately if needed).
- A pre-commit hook (a CI gate is the contract; a local pre-commit hook is an optional ergonomics follow-up — see §19 open questions).
- Gating any other generated artifact (e.g., dashboards) — those have their own regen hooks; only `types.ts` + `ui/public/docs` are in scope.

### API convention check

N/A — this feature adds **no HTTP endpoints**. The only backend addition is a CLI/console entrypoint that prints the OpenAPI schema FastAPI already builds from the existing route table. The error-envelope, auth, and pagination conventions do not apply.

### Phase boundaries

- **Phase 1 (ships first): `copy-docs` freshness gate.** Pure-filesystem, no API, no service container, no new backend code. A CI job (in its own workflow file to escape `pr.yml`'s `docs/**` + `*.md` `paths-ignore`) runs `node ui/scripts/copy-docs.mjs` then `git diff --exit-code ui/public/docs/`. Rationale: zero infra dependency; immediately catches the recurring guide-sync drift; small, reviewable, low-risk.
- **Phase 2 (follows): offline OpenAPI export + `types.ts` freshness gate.** Adds the backend `openapi.json` exporter, the committed `ui/openapi.json` snapshot, and the `types.ts` regenerate-and-diff gate. Rationale: requires the import-cleanliness investigation (FR-4) and the banner-determinism fix (FR-5); larger surface; depends on Phase 1's gate-step pattern as a template.

**Deferred phase tracking:** Phase 2 is tracked in [`infra_openapi_types_freshness_gate`](../infra_openapi_types_freshness_gate/idea.md) (created with this spec). If the pipeline runs both phases in one implementation pass, the `infra_openapi_types_freshness_gate` is folded into the plan and may be retired at finalization; if Phase 1 ships alone, `infra_openapi_types_freshness_gate` remains the discoverable record of the deferred work.

## 4) Product principles and constraints

- **Hermetic CI.** No gate may depend on a live cloud, a managed cluster, or any service CI cannot spin up. The `types.ts` gate MUST NOT require api.openai.com, a live ES/OpenSearch cluster, or external network for schema generation (the OpenAPI schema is built from route signatures, not from any cluster).
- **Determinism is the gate's load-bearing property.** A freshness gate is only trustworthy if regeneration is byte-deterministic across local macOS and the CI Linux runner. The `license-inventory` precedent had to normalize platform variants for exactly this reason. Any non-determinism in `openapi-typescript` output, OpenAPI key ordering, or the banner's interpolated `Source:` line will turn the gate into a flake.
- **Local-fix command must be one paste.** Every failing gate prints the exact command (`cd ui && pnpm types:gen && git add ...` / `node ui/scripts/copy-docs.mjs && git add ...`) so a contributor fixes drift in one step, matching the `license-inventory` UX.
- **Single source of truth, single direction.** `docs/08_guides/*` is the source for `ui/public/docs/*`; the live route table is the source for `openapi.json`; `openapi.json` is the source for `types.ts`. The gate enforces the direction; it never edits a source from a generated copy.
- **No bare secrets.** Per CLAUDE.md Absolute Rule #2, if the offline exporter needs settings to import cleanly, any CI-side secret stand-ins MUST follow the `*_FILE` mounted-secret pattern (write a dummy file, set `*_FILE` to point at it) — never a bare `OPENAI_API_KEY=...` env var.

### Anti-patterns

- **Do not** run a live API container in the frontend CI job to feed `types:gen` — because the schema is fully determined by the route table; a server + DB + ES are unnecessary infra that slow CI and reintroduce flake surface (FR-4 resolves this offline).
- **Do not** auto-commit the regenerated artifact in CI — because that would silently rewrite a contributor's PR and mask the drift the gate exists to surface; the gate FAILS and the human regenerates.
- **Do not** diff a banner line that embeds a CI-specific URL — because if CI points `OPENAPI_URL` at a `file://` snapshot while the committed banner says `http://localhost:8000`, the `Source:` line diffs forever (FR-5 normalizes the banner).
- **Do not** put the `copy-docs` gate inside a `pr.yml` job gated by `paths-ignore: docs/**` — because a docs-only guide edit would not trigger it and the drift would never be caught at its source PR (FR-3 puts it in a workflow that fires on `docs/08_guides/**`).
- **Do not** assume `openapi-typescript` produces identical bytes across versions/platforms without verifying — because a version bump or platform difference would flip the gate red on an unrelated PR; pin the tool version (it's already in `ui/package.json` via the `pnpm install --frozen-lockfile` path) and verify determinism (FR-6).

## 5) Assumptions and dependencies

- Dependency: **`openapi-typescript`** (frontend dev dep, already used by `gen-types.mjs`).
  - Why required: produces `types.ts` from the OpenAPI schema.
  - Status: implemented (in `ui/package.json`; installed via `pnpm install --frozen-lockfile`).
  - Risk if missing: N/A — already present.
- Dependency: **FastAPI `app.openapi()`** (or an equivalent schema-builder that doesn't require importing the CORS-configured `app` singleton).
  - Why required: the offline exporter (FR-4) emits the same schema the live `/openapi.json` route serves.
  - Status: implemented (FastAPI built-in). **Import-cleanliness is the open risk** — `backend/app/main.py:195` calls `get_settings()` at module import time (for CORS origins), which reads `*_FILE`-mounted secrets and can raise `SettingsError` in a bare CI step (see FR-4 + §19).
  - Risk if missing: Phase 2 cannot run offline; would force the live-container fallback (rejected default).
- Dependency: **`scripts/gen_license_inventory.py --check` pattern** as the design template.
  - Why required: proven, shipped, reviewer-familiar regenerate-and-diff posture, including the determinism-normalization lesson.
  - Status: implemented (`chore_oss_public_launch_punchlist`, 2026-05-30).
- Dependency: **`secrets-defense.yml` "own-workflow-to-escape-paths-ignore" pattern** as the template for FR-3's docs gate.
  - Why required: the `copy-docs` source lives under `docs/**` + `*.md`, both `paths-ignore`'d on `pr.yml`.
  - Status: implemented.

## 6) Actors and roles

- Primary actor(s): **System (CI)** + the **contributor** whose PR the gate evaluates. No end-user surface.
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface. This feature touches only CI workflows + a CLI entrypoint.

### Audit events

N/A — this feature performs **no state mutation** (no DB writes, no tenant-visible resource changes). It is a read-only CI guard plus a stdout-emitting CLI exporter. No `audit_log` emission applies.

## 7) Functional requirements

### FR-1: `copy-docs` freshness gate (Phase 1)
- Requirement:
  - **Invocation form (locked):** CI and the local-fix command **MUST** use the same invocation — `pnpm --dir ui exec node scripts/copy-docs.mjs` (or equivalently `cd ui && node scripts/copy-docs.mjs`). `copy-docs.mjs` already resolves all paths from `import.meta.url`, so it is cwd-robust; the plan **SHOULD** add a small test asserting it produces identical output run from the repo root and from `ui/`, so the two command forms cannot diverge.
  - CI **MUST** regenerate the public docs and then fail the job if the working tree differs from its committed state for any path under `ui/public/docs/` — **including newly-generated untracked files**. The check **MUST** use `git status --porcelain -- ui/public/docs/` (catches untracked + deleted), NOT a bare `git diff --exit-code` (which silently ignores untracked files). Fail if it produces any output.
  - The gate **MUST** run on every PR to `main` regardless of which paths changed, so a docs-only guide edit cannot bypass it (see FR-3).
  - The failing step **MUST** print the exact local-fix command (FR-8 Phase 1): `cd ui && node scripts/copy-docs.mjs && git add public/docs`.
- Notes: `copy-docs.mjs` is idempotent and pure-filesystem; running it on an up-to-date tree leaves the working tree clean. The untracked-file requirement matters because a future addition to `copy-docs.mjs`'s `DOCS` array creates a brand-new `ui/public/docs/<name>.md` that `git diff` alone would not see. See FR-9 for the deleted/renamed-guide (stale-leftover) case.

### FR-2: `types.ts` freshness gate (Phase 2)
- Requirement:
  - CI **MUST** regenerate `ui/src/lib/types.ts` from the committed `ui/openapi.json` snapshot and fail if the result differs from the committed `types.ts`. The freshness check **MUST** use `git status --porcelain -- ui/src/lib/types.ts` (catches untracked, mirroring FR-1), not a bare `git diff`.
  - **Source-form (locked, see §19):** the regeneration **MUST** pass an **absolute filesystem path** to the committed snapshot: `OPENAPI_URL="$PWD/ui/openapi.json" pnpm --dir ui types:gen` (run from the repo root). The plan **MUST** verify that `openapi-typescript` (as invoked by `gen-types.mjs`) accepts a plain absolute path on the CI Linux runner; if it requires a `file://` URL, lock that form instead and update the command + AC-8 accordingly. Do not assume the input form — verify it.
  - The failing step **MUST** print the exact canonical local-fix command (see FR-8).
  - The gate **MUST NOT** require a running API server, a live DB, or a live ES/OpenSearch cluster.
- Notes: gating `types.ts` against the committed snapshot (rather than a live server) means FR-7's snapshot-freshness gate is what keeps the *snapshot* honest; the two gates compose (`route table → openapi.json → types.ts`).

### FR-3: Trigger placement that escapes `paths-ignore`
- Requirement:
  - The `copy-docs` gate (FR-1) **MUST** be reachable on PRs that change only files under `docs/**` or `*.md` (which `pr.yml` `paths-ignore`s). **Decision (locked, see §19): a dedicated workflow file** (mirroring `secrets-defense.yml`) that runs on **every** PR to `main` with **NO `paths` / `paths-ignore` filter at all**. Rationale: FR-1 requires the gate run on every PR; a `paths`-filtered workflow would (1) not run on a pure-code PR and (2) skip a PR that edits only the gate workflow itself. An unfiltered dedicated workflow satisfies "every PR," tests itself, and is cheap (a `node` run + a `git status` — no service containers, sub-second). The two contracts (FR-1's "every PR" and a `paths` filter) are mutually exclusive; this spec picks "every PR, no filter."
- Notes: the `types.ts` gate (FR-2) + `openapi.json` snapshot gate (FR-7) sources (`ui/**`, `backend/**`) are NOT under `paths-ignore`, so they MAY live in the existing `static-checks-frontend` job (frontend half) + a backend-toolchain job (FR-7), or a single sibling job — they do not need the dedicated-workflow escape (but see FR-4 for why FR-7 needs the backend `uv` toolchain).

### FR-4: Offline, deterministic OpenAPI export (Phase 2)
- Requirement:
  - The system **MUST** provide a backend entrypoint (e.g., `python -m backend.app.openapi_export` or a `scripts/` console script) that writes the canonical OpenAPI schema to stdout (or a named file via `--out`) **without** starting Uvicorn and **without** requiring a live DB/Redis/ES/OpenSearch connection.
  - The exporter **MUST** import cleanly in a bare CI step. Because `backend/app/main.py:195` invokes `get_settings()` at import time, the exporter **MUST** either: (a) write minimal dummy `*_FILE`-mounted secret stand-ins and set the corresponding `*_FILE` env vars before import (honoring Absolute Rule #2 — no bare secret env vars; stand-ins live in a tmpdir/`RUNNER_TEMP`, never the repo), or (b) build the schema via `fastapi.openapi.utils.get_openapi(...)` from the app's route table without importing the module-level CORS-configured `app`. **The plan's first Phase-2 story MUST run an import-graph spike and produce an explicit decision artifact:** which module the exporter imports, exactly which env vars / `*_FILE` files that import requires, and which live clients (asyncpg pool, Redis, ES/OpenSearch/Solr adapters, the OpenAI SDK client) are confirmed **not** constructed at import/schema-build time. Path (b) is only valid if route-table assembly is itself side-effect-clean (importing a router module must not open a connection or instantiate an adapter) — the spike must prove this, not assume it. The spec does not pre-commit to (a) vs (b); the spike picks the import-clean path.
  - **Canonical serialization (locked):** the exporter **MUST** emit byte-deterministic JSON: `json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` followed by a single trailing newline, with **nothing else on stdout** when stdout is the JSON stream (all log/diagnostic output goes to stderr). When writing to `--out`, write to a temp file and atomically replace the target (no partial snapshots). This guarantees the snapshot is reproducible across the macOS/Linux boundary independent of Python dict-insertion order.
  - The committed `ui/openapi.json` snapshot **MUST** be the exact bytes this exporter produces (so its own freshness is gate-checkable per FR-7).
- Notes: the schema FastAPI generates is a function of route signatures + Pydantic models only; no I/O is needed to build it. The obstacles are (1) the import-time settings load and (2) any import-time side effects in router modules — both addressed by the spike above.

### FR-5: Banner determinism + stance reconciliation (Phase 2)
- Requirement:
  - The `gen-types.mjs` banner **MUST** be deterministic regardless of the `OPENAPI_URL` used to generate (CI uses a `file://` snapshot path; a local dev run uses `http://localhost:8000`). The banner's `Source:` line **MUST NOT** embed the volatile `OPENAPI_URL` value (otherwise the committed `types.ts` diffs whenever the generation source differs). The banner **SHOULD** instead reference a stable phrase (e.g., "Source: backend OpenAPI schema (ui/openapi.json)").
  - The banner text **MUST** be updated to remove the now-false "CI does NOT regenerate this file" assertion and replace it with an accurate statement (CI regenerates only to verify freshness; the committed file is gate-enforced).
  - **`gen-types.mjs` MUST invoke the lockfile-pinned binary, not `npx`.** The current script shells out to `npx openapi-typescript ...`, which can resolve/download a tool version dynamically over the network — defeating both the hermetic-CI constraint (§4) and the byte-determinism the gate relies on (FR-6). The exporter wrapper **MUST** invoke the locally installed, `pnpm-lock.yaml`-pinned binary (e.g. `pnpm exec openapi-typescript` from `ui/`, or `node_modules/.bin/openapi-typescript`) and **MUST** fail loudly if the binary is missing (no implicit `npx` download fallback).
- Notes: this is the subtle correctness issue that would otherwise make FR-2 flake on the first CI run. The banner currently interpolates `${SOURCE_URL}` at two points (the `Source:` line and the `// Source: ${SOURCE_URL}` comment) — both must become source-invariant. The `npx`→pinned-binary change pairs with banner determinism as the two `gen-types.mjs` edits in Phase 2.

### FR-6: Determinism verification
- Requirement:
  - The implementation **MUST** demonstrate (in the plan's verification + in CI itself) that regenerating each artifact on a clean checkout produces zero diff: `copy-docs` on an up-to-date tree, and the offline OpenAPI export + `types:gen` on an up-to-date tree, both leave `git status` clean.
  - If `openapi-typescript` output or OpenAPI key ordering proves non-deterministic across the macOS/Linux boundary, the implementation **MUST** add a normalization step (mirroring `gen_license_inventory.py`'s platform-variant collapse) rather than weakening the gate.
- Notes: the `pnpm install --frozen-lockfile` path already pins `openapi-typescript`; FastAPI emits deterministically-ordered JSON for a fixed route table, but a `--sort-keys`-equivalent normalization on the snapshot is the safety net.

### FR-7: `openapi.json` snapshot freshness (Phase 2)
- Requirement:
  - The committed `ui/openapi.json` snapshot **MUST** itself be freshness-gated: CI runs the offline exporter (FR-4) to (re)write `ui/openapi.json` and fails if the working tree changes — using `git status --porcelain -- ui/openapi.json` (catches both modified and the first-commit untracked case, mirroring FR-1). This step needs the **backend** Python toolchain, so it runs in a job that has `uv`/`uv sync` available (e.g., alongside `static-checks-backend`, or a sibling job).
  - The failing step **MUST** print the canonical local-fix command (see FR-8).
- Notes: without this, `types.ts` could be "fresh" relative to a stale snapshot. The two gates (FR-2 + FR-7) together chain `route table → openapi.json → types.ts`.

### FR-8: Canonical one-paste local-fix commands
- Requirement:
  - Each failing gate step **MUST** print a single copy-pasteable command (or wrapper script) that makes the gate green, mirroring the `license-inventory` UX.
  - **Phase 1 (copy-docs):** `cd ui && node scripts/copy-docs.mjs && git add public/docs`
  - **Phase 2 (chained — snapshot + types):** a single canonical sequence run from the repo root, e.g.:
    ```
    uv run python -m backend.app.openapi_export --out ui/openapi.json \
      && (cd ui && OPENAPI_URL="$PWD/openapi.json" pnpm types:gen) \
      && git add ui/openapi.json ui/src/lib/types.ts
    ```
    The plan **MUST** substitute the actual exporter module/console-script name + verified source-form (per FR-2) and use the exact same text in both the CI failure output and the §15 docs. The plan **MAY** wrap this in a `scripts/` helper (e.g. `scripts/regen-generated-artifacts.sh`) so the fix is a single command and the CI gate + docs reference one source of truth.
- Notes: the Phase 2 fix spans the backend exporter + frontend `types:gen`, so a contributor needs the full chain, not just `pnpm types:gen` (which alone would regenerate types against a stale snapshot).

### FR-9: `ui/public/docs/` is an exact generated set (prune stale leftovers) (Phase 1)
- Requirement:
  - The `copy-docs` regeneration **MUST** treat `ui/public/docs/` as an **exact** generated directory: after regeneration, the only files present **MUST** be `README.md` plus exactly the `dest` files in `copy-docs.mjs`'s `DOCS` array. If a guide is removed or renamed in `DOCS` (or its `docs/08_guides/` source is deleted), any obsolete tracked `ui/public/docs/<old>.md` **MUST** be detected as drift.
  - The implementation **MUST** achieve this either by (a) `copy-docs.mjs` pruning any `*.md` under `ui/public/docs/` that is not in `{README.md} ∪ {DOCS[].dest}` before/after copying, or (b) the guard comparing the directory's tracked file set against the expected generated set and failing on extras. Decision (locked, see §19): **option (a)** — `copy-docs.mjs` prunes, so a single `node copy-docs.mjs` run both syncs and prunes, keeping one source of truth.
- Notes: without pruning, a renamed guide leaves a stale `ui/public/docs/<old>.md` that the FR-1 `git status` check would NOT flag (regeneration doesn't touch it, so the tree stays clean) — the public docs would silently ship a deleted/renamed guide. The plan **MUST** add a negative test: remove a `DOCS` entry, run `copy-docs.mjs`, assert the obsolete `ui/public/docs/<old>.md` is gone (clean tree only after the obsolete file is also removed).

## 8) API and data contract baseline

N/A — no HTTP endpoints, no request/response contracts, no error codes, no enumerated wire values. The only new code interface is a CLI entrypoint:

| Interface | Form | Purpose |
|---|---|---|
| OpenAPI exporter | `python -m <module>` (writes schema JSON to stdout or `--out <path>`) | Produce the canonical `openapi.json` offline for the snapshot + `types.ts` gates |

### 7.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, dropdowns, or backend-validated allowlists. This feature adds no UI option lists.

## 9) Data model and state transitions

N/A — **no schema changes, no migration, no ORM model changes.** Alembic head is unaffected (stays `0022_solr_engine_auth_check`).

The only new tracked file is `ui/openapi.json` (a generated snapshot, not a DB artifact). It is added to the repo and freshness-gated (FR-7).

### Required invariants

- The committed `ui/openapi.json` MUST equal the offline exporter's output (FR-7).
- The committed `ui/src/lib/types.ts` MUST equal `openapi-typescript`'s output from the committed snapshot (FR-2).
- Each file under `ui/public/docs/*` listed in `copy-docs.mjs`'s `DOCS` array MUST equal its `docs/08_guides/*` source (FR-1).

### State transitions

N/A.

### Idempotency/replay behavior

The gates are idempotent: re-running any regenerate-and-diff step on an up-to-date tree is a no-op (clean `git status`). This is exactly FR-6's determinism requirement.

## 10) Security, privacy, and compliance

- Threats:
  1. **Secret leakage via the offline exporter.** If FR-4 path (a) is chosen (dummy `*_FILE` stand-ins), a careless implementation could log or commit a real secret. Control: dummy files contain non-secret placeholder bytes; `*_FILE` env vars point at them; never a bare `OPENAI_API_KEY=...`; the dummy files live in `RUNNER_TEMP` (CI) or a tmpdir (local), never in the repo (per CLAUDE.md "Local-stub hygiene").
  2. **`openapi.json` exposing internal route detail.** The schema is already served publicly at `/openapi.json` by the running app (it powers the existing local `types:gen`), so committing it exposes nothing new.
  3. **Gate flake masking real drift.** A non-deterministic gate that contributors learn to ignore (re-run until green) defeats the purpose. Control: FR-6 determinism verification + normalization.
- Controls: hermetic CI (no external network for schema gen); `*_FILE`-mounted secret stand-ins only; deterministic regeneration.
- Secrets/key handling: no real secrets are needed to build the OpenAPI schema; any CI-side stand-ins follow the `*_FILE` pattern and live in ephemeral runner temp.
- Auditability: N/A (CI guard).
- Data retention/deletion/export impact: N/A.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI. The "user" is a contributor reading a failed CI check.

### Tooltips and contextual help

N/A — no UI elements, no glossary keys.

### Primary flows

1. **Drift introduced → caught at PR.** A contributor edits a backend Pydantic model (or a guide) and opens a PR without regenerating. The relevant gate runs, regenerates the artifact, the working tree goes dirty, the step fails with a one-line local-fix command. The contributor runs the command, commits, pushes; the gate goes green.
2. **No drift → silent pass.** A PR that doesn't touch any source leaves all regenerate steps producing zero diff; gates pass without comment.

### Edge/error flows

- **Docs-only PR.** A PR touching only `docs/08_guides/tutorial-first-study.md` would be `paths-ignore`'d by `pr.yml`, but the dedicated `copy-docs` workflow (FR-3) still fires and catches a missing `ui/public/docs/` sync.
- **Offline exporter import failure.** If the exporter cannot import cleanly (settings load raises), the FR-7 step fails loudly with the `SettingsError` — this is a build-config bug to fix in the exporter, not a drift signal. The plan's FR-4 verification must prove the exporter imports clean in a bare CI step before this gate ships.
- **`openapi-typescript` version bump.** A dependabot/manual bump that changes output bytes flips both FR-2 and FR-7 red; the fix is to regenerate + commit the new `types.ts` (+ snapshot if the schema serializer changed) in the same PR as the bump. This is correct behavior, not a flake.
- **Banner source-URL divergence.** Pre-FR-5, a CI run pointing `OPENAPI_URL` at a snapshot would rewrite the banner's `Source:` line and diff forever. FR-5 makes the banner source-invariant so this cannot happen.

## 12) Given/When/Then acceptance criteria

### AC-1: copy-docs gate catches a stale public doc
- Given a PR where `docs/08_guides/quick-tour.md` has been edited but `ui/public/docs/quick-tour.md` was not re-synced
- When the `copy-docs` freshness workflow runs in CI
- Then the job fails, and the failing step output contains the local-fix command `cd ui && node scripts/copy-docs.mjs && git add public/docs`
- Example values:
  - Input: a one-line edit to `docs/08_guides/quick-tour.md` only
  - Expected: CI status = failure; `git status --porcelain -- ui/public/docs/` produces output (non-empty) in the step log

### AC-2: copy-docs gate passes on an up-to-date tree
- Given a PR where all `ui/public/docs/*` files match their `docs/08_guides/*` sources
- When the `copy-docs` freshness workflow runs
- Then the job passes and `git status` after running `copy-docs.mjs` is clean

### AC-3: copy-docs gate is reachable on a docs-only PR
- Given a PR that changes only files under `docs/08_guides/` (which `pr.yml` `paths-ignore`s)
- When CI evaluates the PR
- Then the dedicated `copy-docs` workflow (FR-3) still runs (it is not gated by `pr.yml`'s `paths-ignore`)

### AC-4: offline OpenAPI export runs with no live services
- Given a CI runner with the backend Python toolchain (`uv sync`) but **no** Postgres/Redis/ES/OpenSearch service container and **no** running API server
- When the offline exporter entrypoint is invoked
- Then it exits 0 and writes a valid OpenAPI JSON document to stdout/file
- Example values:
  - Expected: the output **parses as JSON** and the resulting object contains top-level keys `openapi`, `info`, and `paths`, with at least one known route under `paths` (e.g., `/api/v1/studies`). The test **MUST** parse-and-assert keys, NOT assert a leading string prefix — under the FR-4 canonical `sort_keys=True` serialization, top-level keys are alphabetized, so the document begins with whichever key sorts first (e.g. `{"components":...` when `components` is present), not `{"openapi":...`.

### AC-5: openapi.json snapshot freshness gate catches a schema change
- Given a PR that adds or modifies a backend route/Pydantic model such that the OpenAPI schema changes, without regenerating `ui/openapi.json`
- When the snapshot-freshness step (FR-7) runs
- Then the job fails with `git status --porcelain -- ui/openapi.json` non-empty and prints the canonical local-fix command (FR-8)

### AC-6: types.ts gate catches drift against the snapshot
- Given a committed `ui/openapi.json` that differs from the committed `ui/src/lib/types.ts` (types not regenerated after a snapshot update)
- When the `types.ts` freshness step (FR-2) runs (`OPENAPI_URL="$PWD/ui/openapi.json" pnpm --dir ui types:gen` then `git status --porcelain -- ui/src/lib/types.ts`)
- Then the job fails (non-empty `git status --porcelain`) and prints the canonical local-fix command (FR-8)

### AC-7: regeneration is byte-deterministic across runners
- Given a clean checkout on the CI Linux runner with no source edits
- When `copy-docs`, the offline export, and `types:gen` are each run
- Then `git status --porcelain` is empty for `ui/public/docs/`, `ui/openapi.json`, and `ui/src/lib/types.ts`
- Example values:
  - Expected: empty `git status --porcelain` output for each path

### AC-8: banner is source-invariant
- Given `types.ts` is regenerated once with `OPENAPI_URL=http://localhost:8000/openapi.json` and once with `OPENAPI_URL="$PWD/ui/openapi.json"` (the locked absolute-path form per FR-2)
- When both outputs are compared
- Then the banner block (including the `Source:` line) is byte-identical between the two runs

### AC-9: gate catches an untracked generated file
- Given a gated path contains a newly-generated file that is **untracked** (e.g., a new `DOCS` entry produced `ui/public/docs/new-guide.md`, or the first commit of `ui/openapi.json` was omitted)
- When the corresponding freshness gate runs
- Then the gate fails (because it uses `git status --porcelain`, which reports untracked files; a bare `git diff --exit-code` would have passed incorrectly)
- Example values:
  - Expected: `git status --porcelain -- <gated path>` is non-empty → job failure

### AC-10: Phase 2 one-paste fix command makes the gates green
- Given a PR failing both the snapshot (FR-7) and types (FR-2) gates
- When the contributor runs the canonical Phase 2 fix command from FR-8 and commits the result
- Then both gates pass on the next CI run with `git status --porcelain` clean for `ui/openapi.json` and `ui/src/lib/types.ts`

### AC-11: removed/renamed guide is pruned from public docs
- Given a guide is removed from `copy-docs.mjs`'s `DOCS` array (or its `docs/08_guides/` source deleted), leaving a tracked `ui/public/docs/<old>.md`
- When `copy-docs.mjs` is run (regeneration)
- Then the obsolete `ui/public/docs/<old>.md` is removed, and the `copy-docs` gate (FR-1) reports drift until the deletion is committed
- Example values:
  - Input: remove the `quick-tour.md` entry from `DOCS`
  - Expected: `ui/public/docs/quick-tour.md` deleted by the run; `git status --porcelain -- ui/public/docs/` shows the deletion as drift

## 13) Non-functional requirements

- Performance: the `copy-docs` gate is sub-second (filesystem copy + `git diff`). The `types.ts` + snapshot gates add a `uv sync` + `pnpm install --frozen-lockfile` + one `openapi-typescript` invocation — bounded by the install steps already paid by sibling jobs; target < 2 minutes wall-clock for the Phase 2 job.
- Reliability: zero tolerance for flake — a flaky freshness gate is worse than none (contributors learn to ignore red). FR-6 determinism verification is the reliability gate.
- Operability: each failing step self-documents the local-fix command; no runbook lookup needed. A short note in `docs/03_runbooks/local-dev.md` (or `docs/05_quality/testing.md`) documents the gates.
- Accessibility/usability: N/A (no UI).

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`): a unit test asserting the offline OpenAPI exporter (FR-4) returns a dict with `openapi`, `info`, and `paths` keys and at least one known route path, **without** any DB/network — proving import-cleanliness and the no-live-services contract (AC-4). If FR-4 path (a) is chosen, the test sets the dummy `*_FILE` env vars via `monkeypatch`/`tmp_path`.
- Integration tests (`backend/tests/integration/`): N/A — no DB-backed workflow. (The "integration" here is CI-level, exercised by the workflows themselves.)
- Contract tests (`backend/tests/contract/`): optionally, a contract-style test asserting the exporter's output matches `app.openapi()` served at the live `/openapi.json` route shape (so the snapshot and the runtime schema cannot silently diverge). Recommended, not required.
- E2E tests (`ui/tests/e2e/`): N/A — no user journey.
- CI self-test (happy path): FR-6 determinism is validated by running the regen on a clean tree and asserting empty `git status` (AC-7).
- **Negative-path automated tests (required):** the gate logic MUST be wrapped in a `scripts/` guard (shell or Python, mirroring `scripts/ci/verify_install_builds_all_services.sh`) so the failure path is testable without a real PR. Add automated tests that, in a temp git worktree/repo: (1) dirty a generated target and assert the guard exits non-zero AND emits the expected fix-command text (covers AC-1, AC-5, AC-6); (2) introduce an **untracked** generated file under a gated path and assert the guard still fails (regression guard against reverting to a bare `git diff`); (3) run the guard on a clean tree and assert exit 0. These tests are the contract for the gate's failure behavior, which CI-on-clean-tree alone cannot exercise.

## 15) Documentation update requirements

- `docs/01_architecture`: N/A (no architectural surface; optionally a one-line note in `tech-stack.md` that generated artifacts are CI-freshness-gated).
- `docs/02_product`: N/A.
- `docs/03_runbooks`: add a short "Generated-artifact freshness gates" subsection to `local-dev.md` (or `docs/05_quality/testing.md`) listing the two gates and their one-paste local-fix commands.
- `docs/04_security`: N/A.
- `docs/05_quality`: update `testing.md` to mention the freshness gates alongside the existing coverage/lint gates.
- `CLAUDE.md`: optionally add a "Generated artifacts" note under Key Conventions naming `types.ts` (regen via `pnpm types:gen`) + `ui/public/docs` (regen via `node scripts/copy-docs.mjs`) + `ui/openapi.json` (regen via the exporter) and that each is CI-gated — so future contributors regenerate proactively. Decide at plan time (low priority).

## 16) Rollout and migration readiness

- Feature flags / staged rollout: none. The gates are additive CI jobs. **Before merging the PR that adds each gate, the corresponding artifact must already be fresh** (regenerate + commit `ui/public/docs/*`, `ui/openapi.json`, and `types.ts` in the same PR) — otherwise the new gate fails its own introducing PR. This is the rollout's only sharp edge.
- Migration/backfill expectations: none (no schema).
- Operational readiness gates: the new workflows must be green on the introducing PR (which means the artifacts were freshened in that PR).
- **Branch protection / required checks (operator discretion):** a CI gate only *blocks* a merge if it's a required status check. Per current repo state, `main` has **no required-status-checks rule** (the operator removed ruleset `protect-main-require-pr-ci`'s `required_status_checks` on 2026-05-31) — so these gates run and report but do not hard-block until/unless the operator re-adds required checks. The plan SHOULD note this as a follow-up for the operator (the agent cannot change branch protection — CLAUDE.md operator-handoff). If required checks are later re-enabled and the dedicated `copy-docs` workflow runs unfiltered (FR-3 locked decision: no `paths` filter), it reports a real pass/fail on every PR, avoiding GitHub's "skipped-check counts as required-not-satisfied" pitfall that a `paths`-filtered required check would hit.
- Release gate: all new gates green; no existing job regressed; `pnpm install --frozen-lockfile` + `uv sync --frozen` unaffected (no new runtime deps; the offline exporter uses only stdlib `json` + FastAPI's built-in `get_openapi`).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (copy-docs gate) | AC-1, AC-2, AC-9 | Phase 1: copy-docs freshness workflow + guard script | guard-script negative tests (§14) | `docs/05_quality/testing.md` |
| FR-2 (types.ts gate) | AC-6, AC-9 | Phase 2: types.ts freshness step | guard-script negative tests (§14) | `docs/05_quality/testing.md` |
| FR-3 (paths-ignore escape) | AC-3 | Phase 1: dedicated unfiltered workflow file | CI trigger config | `docs/05_quality/testing.md` |
| FR-4 (offline export) | AC-4 | Phase 2: import-graph spike + OpenAPI exporter entrypoint | `backend/tests/unit/test_openapi_export.py` (no-live-services + canonical-serialization) | — |
| FR-5 (banner determinism) | AC-8 | Phase 2: gen-types.mjs banner fix | (covered by AC-8 in CI) | — |
| FR-6 (determinism verify) | AC-7 | Phase 2 (+ Phase 1): determinism check | CI clean-tree assertion | — |
| FR-7 (snapshot freshness) | AC-5, AC-9 | Phase 2: openapi.json snapshot gate | guard-script negative tests (§14) | `docs/05_quality/testing.md` |
| FR-8 (canonical fix command) | AC-10 | Phase 1 + Phase 2: fix-command text in CI output + `scripts/` helper | guard-script negative tests assert fix-command text (§14) | `docs/05_quality/testing.md` |
| FR-9 (prune stale public docs) | AC-11 | Phase 1: copy-docs prune-to-exact-set | copy-docs removed-entry negative test (§14) | `docs/05_quality/testing.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] **All acceptance criteria in §12 (AC-1 … AC-11) pass in CI** — explicitly including AC-9 (untracked-file guard) and AC-11 (removed/renamed-guide prune), which must not be dropped during rollout.
- [ ] All applicable test layers are green: the exporter unit test (FR-4 no-live-services + canonical serialization), the guard-script negative tests (§14), and the `copy-docs` prune negative test (FR-9 / AC-11).
- [ ] Documentation updates (`docs/05_quality/testing.md`, optional runbook + CLAUDE.md note) are merged.
- [ ] Rollout gates from §16 are satisfied (artifacts freshened in the introducing PR; new gates green; no existing job regressed).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **FR-4 import path (a) vs (b)** — does importing the schema-builder import cleanly without triggering the module-level `get_settings()` in `backend/app/main.py:195`? Owner: implementer (plan-time spike). Due: before the Phase 2 implementation plan finalizes. Recommended default: try path (b) — call `fastapi.openapi.utils.get_openapi()` against an app/router assembled without the CORS `get_settings()` call; fall back to path (a) (`*_FILE` dummy stand-ins) only if the route table cannot be assembled without the configured `app` singleton. **This is a how question, not a what question** — it does not block Phase 1 and is resolvable inside the plan's first story.
- **Pre-commit hook (optional ergonomics)** — should the same regenerate-and-diff run as a local pre-commit hook so contributors catch drift before pushing? Owner: maintainers. Recommended default: **defer** — CI is the contract; a pre-commit hook is a separate ergonomics follow-up (capture as a `chore_` idea if desired). Out of scope for this spec.

### Decision log
- 2026-06-01 — **Gate mechanism = regenerate + `git status --porcelain -- <path>`** (not a per-generator `--check` flag, and NOT a bare `git diff --exit-code` — which misses untracked files). Rationale: generator-agnostic, matches the shipped `license-inventory` regenerate-and-compare UX, avoids adding flags to two separate JS generators, and catches the new-file case. `git diff` MAY be used only as optional human-readable diagnostic output AFTER `git status` reports drift.
- 2026-06-01 — **`types:gen` uses an offline committed `openapi.json` snapshot, not a live API container.** Rationale: hermetic CI, no service container in the frontend job, schema is a pure function of the route table. (FR-4 + FR-7.)
- 2026-06-01 — **FR-3 trigger placement = dedicated workflow file** (mirroring `secrets-defense.yml`), so the `copy-docs` gate escapes `pr.yml`'s `docs/**` + `*.md` `paths-ignore`. Rationale: established precedent for exactly this `paths-ignore` escape.
- 2026-06-01 — **Two-phase delivery: `copy-docs` gate first (no infra), `types.ts`/snapshot/export second.** Rationale: Phase 1 is zero-dependency and immediately valuable; Phase 2 carries the import-cleanliness + banner-determinism work.
- 2026-06-01 — **No auto-commit of regenerated artifacts.** Rationale: the gate's job is to surface drift to the human, not silently rewrite their PR.
- 2026-06-01 — **Banner must be made source-invariant (FR-5)** before FR-2 can ship without flaking. Rationale: the banner currently interpolates the volatile `OPENAPI_URL`, which would diff between local (`localhost:8000`) and CI (snapshot path).
- 2026-06-01 — **Freshness checks use `git status --porcelain`, not `git diff --exit-code`** (GPT-5.5 Pass A High). Rationale: `git diff` ignores untracked files, so a new `ui/openapi.json` (first commit) or a new `DOCS`-array guide copy could pass incorrectly. (FR-1/FR-2/FR-7 + AC-9.)
- 2026-06-01 — **Dedicated `copy-docs` workflow runs unfiltered (no `paths` filter), on every PR** (GPT-5.5 Pass A Medium). Rationale: resolves the FR-1 "every PR" vs FR-3 `paths`-filter contradiction; also lets the workflow test itself and avoids GitHub skipped-required-check semantics.
- 2026-06-01 — **Exporter emits canonical JSON** (`sort_keys=True, separators=(",",":")` + trailing newline, atomic write, stdout-clean) (GPT-5.5 Pass A Medium). Rationale: byte-determinism across macOS/Linux is the gate's load-bearing property.
- 2026-06-01 — **`types:gen` source-form locked to an absolute filesystem path** (`OPENAPI_URL="$PWD/ui/openapi.json"`), pending plan-time verification that `openapi-typescript` accepts it on the Linux runner (GPT-5.5 Pass A Low). Rationale: spec referenced both a plain path and `file://`; one form must be the contract.
- 2026-06-01 — **FR-4 requires an explicit import-graph spike** proving no live clients are constructed at schema-build time (GPT-5.5 Pass A Low). Rationale: route-table assembly side effects, not just `main.py`'s settings load, can break the offline contract.
- 2026-06-01 — **Gate failure path gets automated negative tests via a `scripts/` guard** (GPT-5.5 Pass B Medium). Rationale: CI-on-clean-tree proves only the happy path; the failure exit + fix-command text + untracked-file case need explicit tests.
- 2026-06-01 — **Branch-protection / required-check enablement is an operator follow-up** (GPT-5.5 Pass B Low). Rationale: `main` currently has no required-status-checks rule; the agent cannot change branch protection (operator handoff).
- 2026-06-01 (cycle 2) — **AC-1/AC-5/AC-6 + decision log reconciled to `git status --porcelain`** (GPT-5.5 cycle-2 Pass A Medium). Rationale: the cycle-1 FR fix left the ACs/decision-log still citing `git diff`, which would mislead test authors back into the untracked-file blind spot.
- 2026-06-01 (cycle 2) — **`copy-docs` invocation form locked to a single cwd** (`cd ui` / `pnpm --dir ui`) for both CI and the local fix (GPT-5.5 cycle-2 Pass A Medium). Rationale: FR-1 had a repo-root CI invocation but a `cd ui` fix command — divergence risk; script is cwd-robust via `import.meta.url` but the command text must match.
- 2026-06-01 (cycle 2) — **AC-4 asserts parsed JSON keys, not a string prefix** (GPT-5.5 cycle-2 Pass A Medium). Rationale: `sort_keys=True` (FR-4) alphabetizes top-level keys, so the document may begin with `{"components":...`, not `{"openapi":...` — a prefix assertion would falsely fail a correct exporter.
- 2026-06-01 (cycle 2) — **Added FR-9: `copy-docs` prunes `ui/public/docs/` to an exact generated set** (GPT-5.5 cycle-2 Pass B Medium). Rationale: a removed/renamed guide leaves a stale tracked public copy that the FR-1 `git status` check would not flag (regeneration doesn't touch it); pruning + AC-11 closes the gap.
- 2026-06-01 (cycle 3) — **`gen-types.mjs` must invoke the lockfile-pinned `openapi-typescript`, not `npx`** (GPT-5.5 cycle-3 Pass A Medium). Rationale: `npx` can resolve/download a tool version over the network, defeating hermetic CI (§4) + byte-determinism (FR-6); use `pnpm exec` / `node_modules/.bin` and fail if missing. (FR-5.)
- 2026-06-01 (cycle 3) — **§18 Definition of Done now requires all of AC-1 … AC-11** (GPT-5.5 cycle-3 Pass B Medium). Rationale: the prior DoD listed only AC-1…AC-8, which would let the new untracked-file (AC-9) + prune (AC-11) coverage be dropped while still "complete."
