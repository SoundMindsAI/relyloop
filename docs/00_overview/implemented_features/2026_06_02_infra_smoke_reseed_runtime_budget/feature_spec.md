<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Feature Specification — `infra_smoke_reseed_runtime_budget`

**Date:** 2026-06-02
**Status:** Draft
**Owners:** Eric Starr (engineering lead)
**Related docs:**
- [`idea.md`](./idea.md)
- [`infra_solr_smoke_stability` (shipped, PR #383)](../../../implemented_features/2026_06_02_infra_solr_smoke_stability/feature_spec.md)
- [`feat_demo_ubi_study_comparison` (shipped, PR #320)](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) — AC-8 reseed wall-clock ceiling
- [`docs/03_runbooks/smoke-solr-stability.md`](../../../../03_runbooks/smoke-solr-stability.md) — sibling runbook

---

## 1) Purpose

- **Problem:** The `pr.yml` `smoke (operator-path tutorial flow)` job's Playwright E2E step picks up [`ui/tests/e2e/demo-ubi.spec.ts`](../../../../../ui/tests/e2e/demo-ubi.spec.ts), whose `beforeAll` hook drives `POST /api/v1/_test/demo/reseed` to completion. The reseed touches all six demo scenarios (4 small + rich ESCI on ES + Solr's `acme-kb-docs-solr`) and its in-flight wall-clock is bounded by `feat_demo_ubi_study_comparison` AC-8 at **1140s / ~19 min hard ceiling** (per [feature_spec.md:324, 559-563](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md)), with that spec's §14 estimating **~28 min worst case** once the Solr scenario lights up. Adding Playwright setup + smoke-job overhead pushes total wall-clock past the smoke job's 25-min cap ([`pr.yml:523`](../../../../../.github/workflows/pr.yml#L523)). PR #383 surfaced this concretely: run 26790636716 hit the 25-min cap mid-reseed. Subsequently (2026-06-02) the smoke job was disabled by default ([`pr.yml:42-57`](../../../../../.github/workflows/pr.yml#L42-L57)) via a new `SMOKE_TEST` repo variable, **naming this idea** as the reason. Today's daily cost is zero (smoke is silent); the cost is signal loss — every PR runs without the full-stack Playwright tutorial-flow check.
- **Outcome:** The CI smoke job's Playwright run excludes `demo-ubi.spec.ts` via the existing `testIgnore` precedent in [`ui/playwright.config.ts:47-65`](../../../../../ui/playwright.config.ts#L47-L65), so the reseed-bound spec no longer participates in the smoke runtime budget. Local `make up` smoke (which runs with `CI=` unset) retains full demo-ubi coverage. The operator may then flip `SMOKE_TEST=true` to re-enable the smoke job per-PR; runtime is **expected to fit within 25 min pending operator verification** (see §16 — verified once via `playwright test --list` at PR review + one optional smoke run with `SMOKE_TEST=true` post-merge before the variable is left enabled).
- **Non-goal:** This spec does NOT (a) preserve per-PR demo-ubi smoke coverage (that's Option C in the idea — explicitly NOT pursued per D-2), (b) bump the smoke job's `timeout-minutes` (that's Option B — rejected per D-3), (c) flip `SMOKE_TEST=true` itself (operator decision after the runtime block is cleared), (d) change anything about Solr Compose service / heap / health (`infra_solr_smoke_stability`'s domain), or (e) change anything about the demo-reseed orchestrator, the seed scripts, or the in-flight reseed budget (Option C territory). The demo-ubi spec file itself is unchanged.

## 2) Current state audit

### Existing implementations

- [`ui/playwright.config.ts:25-66`](../../../../../ui/playwright.config.ts#L25-L66) — `testIgnore` array currently with two slots: (i) the always-ignored `'**/guides/**'` glob (outside the CI ternary), and (ii) a CI-gated branch (`process.env.CI ? [...] : []`) listing **6 spec files** the smoke job must skip: `dashboard.spec.ts`, `dashboard-reseed.spec.ts`, `auto-followup.spec.ts`, `index-document-browser.spec.ts`, `studies-create-builder.spec.ts`, `studies-create-target-dropdown.spec.ts`. The two comment blocks at lines 38-46 and 47-58 explain the precedent: the first set (`dashboard*.spec.ts`) was dropped by `chore_drop_demo_seed_from_ci`; the later 4 were added by PR #291's `RELYLOOP_SKIP_AUTO_SEED=1` change. After this work ships the CI-gated branch holds **7 spec files** (the 6 above plus `demo-ubi.spec.ts`); the `'**/guides/**'` always-ignored slot is unchanged.
- [`ui/tests/e2e/demo-ubi.spec.ts:1-50`](../../../../../ui/tests/e2e/demo-ubi.spec.ts#L1-L50) — the spec being excluded. Already carries a `test.skip(process.env.SKIP_HEAVY_CI === 'true', …)` gate at lines 33-36; this does NOT protect the smoke job because the smoke job's `if:` gate at [`pr.yml:50`](../../../../../.github/workflows/pr.yml#L50) already requires `vars.SKIP_HEAVY_CI != 'true'` — meaning whenever smoke is running, `SKIP_HEAVY_CI` is unset/false, so demo-ubi's file-level `test.skip` evaluates to `false` and the spec executes (including its `beforeAll` reseed). The `testIgnore` route is the reliable exclusion mechanism for the smoke-job context.
- [`.github/workflows/pr.yml:505-523`](../../../../../.github/workflows/pr.yml#L505-L523) — smoke-test job header. Comment names this idea by slug at line 511 and says "AC-8 bounds at 24 min" — drift from the actual spec (1140s = 19 min hard ceiling). The `timeout-minutes: 25` at line 523 stays; we don't bump it (D-3).
- [`.github/workflows/pr.yml:761-762`](../../../../../.github/workflows/pr.yml#L761-L762) — Playwright invocation: `pnpm --dir ui test:e2e` (the npm script at [`ui/package.json:16`](../../../../../ui/package.json#L16) = `"playwright test"`). No CLI flags — the spec exclusion lives entirely in `playwright.config.ts`. This means we do NOT need to edit `pr.yml` at all to skip demo-ubi.
- [`.github/workflows/pr.yml:42-57`](../../../../../.github/workflows/pr.yml#L42-L57) — top-of-file SMOKE_TEST opt-in note. Names this idea at line 47. After this work ships, the comment's framing shifts from "OFF because runtime exceeds budget" to "OFF by default but runtime budget is now under 25 min — operator can opt in".
- [`docs/03_runbooks/smoke-solr-stability.md`](../../../../03_runbooks/smoke-solr-stability.md) — sibling runbook. Owns the Solr-stability lever cascade. Per the idea's "Relationship to other work" section, this runbook needs a new section noting that reseed-runtime is a separate concern (now resolved via this spec).
- [`state.md:11-15`](../../../../../state.md#L11-L15) — `## CI note` and lines 56-57 — debt entry naming this idea. After ship, the entry updates to "resolved — operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke".

**Why this matters:** The exclusion mechanism is already established (testIgnore branch in playwright.config.ts); we extend it rather than invent a parallel mechanism (CLI flag in `pr.yml`). This is the lowest-LOC, most-conventional implementation — and it eliminates the D-4 coordination concern with `infra_smoke_fork_pr_secret_skip` (that idea will edit `pr.yml` without any risk of colliding with this idea's edits).

### Navigation and link impact

| Source file | Current reference | New reference |
|---|---|---|
| `docs/03_runbooks/smoke-solr-stability.md` | (no section about reseed runtime) | Add §4 "Reseed runtime (demo-ubi exclusion)" |
| `state.md` (Known debt) | `infra_smoke_reseed_runtime_budget` entry as P1 unresolved | Strike — resolved via this PR; note operator can flip `SMOKE_TEST=true` |
| `.github/workflows/pr.yml:44-47` | Comment: "demo-ubi reseed routinely hits the 25-min job cap" | Refresh: "demo-ubi reseed runtime previously blocked smoke; now CI-excluded via playwright.config.ts testIgnore — runtime budget is back under 25 min; operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke signal (expected to fit within the cap pending operator verification per §16)" |
| `.github/workflows/pr.yml:515-523` | Comment: "AC-8 bounds at 24 min" + the implicit "demo-ubi is what makes this take so long" | Refresh: "Playwright runtime is expected to fit within the 25-min cap post-demo-ubi-exclusion (verify once via `SMOKE_TEST=true` post-merge). The 25-min cap is now headroom against the remaining specs, not a regular threat." |

No UI, no API, no operator-facing URL repointing.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/tests/e2e/demo-ubi.spec.ts` | full file | 1 | No change to the spec file itself. CI execution context flips from "runs and times out" to "skipped by `testIgnore`". Local context unchanged (file still runs under `pnpm test:e2e` when `CI` is unset). |
| `ui/src/__tests__/playwright-config-test-ignore.test.ts` | new file | 1 | NEW vitest file — assert `'**/demo-ubi.spec.ts'` is present in the CI-gated branch of `testIgnore`, and that the existing 6 CI-gated entries are preserved. Regression guard against accidental re-addition. |
| `.github/workflows/pr.yml` | smoke-test job structure | — | No structural change. Comment refresh only (per the navigation table above). |

### Existing behaviors affected by scope change

- **CI smoke run scope.** Current: when `SMOKE_TEST=true`, the smoke job runs all `*.spec.ts` minus the 6 CI-gated specs in `testIgnore`'s CI branch (one of which — demo-ubi — times out the job because it is NOT in the CI branch today). New: 7 CI-gated specs (the 6 above plus `demo-ubi.spec.ts`); demo-ubi no longer participates in the smoke job's Playwright run. The always-ignored `'**/guides/**'` glob is unchanged. Decision needed: no — D-2 locked Option A.
- **Local `pnpm test:e2e` scope.** Unchanged — `CI=` (unset) keeps the spec in the run, preserving local coverage. Decision needed: no.
- **Demo-ubi.spec.ts code path.** Unchanged — the spec file, its `beforeAll` reseed, and its 5 assertions stay as-is. Only its CI participation changes. Decision needed: no.

---

## 3) Scope

### In scope

- Extend the `testIgnore` array's CI-gated branch in [`ui/playwright.config.ts`](../../../../../ui/playwright.config.ts) by one entry: `'**/demo-ubi.spec.ts'`, with a comment block (mirroring the existing two precedent comment blocks at lines 38-58) naming this idea, citing PR #383's run 26790636716, the AC-8 wall-clock budget mismatch, and pointing readers at the `smoke-solr-stability.md` runbook for the lever-cascade context.
- Add a vitest unit test at [`ui/src/__tests__/playwright-config-test-ignore.test.ts`](../../../../../ui/src/__tests__/) that:
  - Reads `ui/playwright.config.ts` as text.
  - Asserts the literal `'**/demo-ubi.spec.ts'` appears within the `process.env.CI ?` ternary branch (i.e., not in the always-ignored `**/guides/**` slot, not outside the branch).
  - Asserts the 6 pre-existing CI-gated entries remain present (regression guard — prevents accidental removal during a future refactor).
- Update [`docs/03_runbooks/smoke-solr-stability.md`](../../../../03_runbooks/smoke-solr-stability.md) — add a new section "§4 Reseed runtime (demo-ubi exclusion)" explaining: why demo-ubi is CI-excluded (AC-8 / smoke-cap mismatch); the mechanism (playwright.config.ts testIgnore); the local-coverage promise (file still runs under `pnpm test:e2e` when `CI` is unset); and the path forward if per-PR demo-ubi coverage is ever wanted (Option C — env-var scenario filter, deferred per D-2).
- Refresh the two comment blocks in `.github/workflows/pr.yml` named in §2's navigation table — they currently describe demo-ubi as the runtime-budget blocker; updated copy notes the block is cleared and `SMOKE_TEST=true` is expected to fit within the cap pending operator verification (per §16).
- Update [`state.md`](../../../../../state.md) — strike the `infra_smoke_reseed_runtime_budget` debt entry under "Known debt / fragility"; note this idea shipped and operator may flip `SMOKE_TEST=true` at their discretion to restore per-PR smoke signal.

### Out of scope

- **Option B (`timeout-minutes` bump).** Rejected per D-3 — spec's own §14 estimates ~28 min worst case; bumping to 35 leaves <7 min margin and erodes with each future demo scenario.
- **Option C (env-var scenario filter for the reseed orchestrator).** Rejected per D-2 — operator does not want per-PR demo-ubi smoke coverage preserved at this cost (~2-3 hours, multi-file). Captured in the runbook §4 update as the path forward IF the decision ever flips.
- **Flipping `SMOKE_TEST=true` on the repo.** Operator decision after this PR ships and CI is verified. Not in this PR's scope.
- **Changes to demo-ubi.spec.ts itself, the reseed orchestrator, the seed scripts, AC-8's actual values, or anything Solr-Compose related** (heap, healthcheck, permissions — `infra_solr_smoke_stability`'s domain).
- **AC-8 citation drift fix in `demo-ubi.spec.ts:11` (25-min ceiling vs 1140s/19 min hard).** Captured in idea, explicitly out of scope here — the demo-ubi spec file is not edited at all by this PR (it remains the canonical local-run target). The `pr.yml:515-523` comment block, by contrast, IS edited per FR-4 — that comment refresh is structural to this PR (it removes the now-misleading "demo-ubi reseed exceeds the cap" framing), and as a side effect the "24 min" reference in that block is replaced by the new framing. The pr.yml comment-text refresh is NOT a tangential AC-8-drift fix; it's the canonical comment for the smoke-job's now-cleared runtime concern.
- **Coordinating any pr.yml edit with `infra_smoke_fork_pr_secret_skip`.** D-4's concern was a CLI-flag collision on the Playwright invocation; this spec moves the exclusion to `playwright.config.ts` instead, so the D-4 collision risk is eliminated entirely. The sibling idea can edit `pr.yml`'s secret-sanity-check step without any awareness of this work. (Comment-block refreshes in `pr.yml:42-57` and `pr.yml:515-523` are textual only — no functional overlap with the sibling.)

### API convention check

N/A — no business endpoints, no operator-facing endpoints, no webhook endpoints. The Playwright `testIgnore` array is an internal test-runner configuration; the vitest regression test is an internal unit test. No `/api/v1/*` or `/healthz` or `/webhooks/*` surface is added or modified.

### Phase boundaries

Single-phase. The full deliverable ships in one PR: testIgnore extension + vitest regression guard + runbook section + pr.yml comment refresh + state.md update. No `phase2_idea.md` required.

---

## 4) Product principles and constraints

- **Match existing patterns over inventing new ones.** The CI-gated `testIgnore` branch already lists 6 specs with documented rationale. Demo-ubi joins as the 7th with the same kind of inline comment, in the same place. No new mechanism, no new env var, no new CLI flag in `pr.yml`.
- **Preserve local-dev coverage absolutely.** `pnpm test:e2e` with `CI=` (unset) MUST still execute `demo-ubi.spec.ts` — operators rely on it. The exclusion gate is `process.env.CI ? [...includesDemoUbi] : []`. The vitest regression test asserts this gating, not the static presence-of-string.
- **Single source of truth for "what does smoke skip on CI".** Anyone reading `ui/playwright.config.ts` sees the full list of CI-excluded specs with rationale. The runbook references it; `pr.yml` does NOT duplicate the spec name in YAML.
- **Honest documentation.** `state.md` and the two `pr.yml` comment blocks all currently say "demo-ubi reseed exceeds the 25-min cap" — that framing has to update in the same PR that ships the fix. Stale comments are next-quarter's confusion.

### Anti-patterns

- **Do not edit `pr.yml`'s Playwright invocation** to add `--grep-invert "demo-ubi"`. That would invent a parallel exclusion mechanism (CLI flag) when the existing one (config-level `testIgnore`) is already serving 6 sibling cases. It would also resurrect the D-4 collision concern with `infra_smoke_fork_pr_secret_skip`. The pr.yml edits in this PR are comment-only.
- **Do not delete or rename `demo-ubi.spec.ts`.** The file is real coverage that local `make up` smoke (with `CI=` unset) will continue to run unchanged. We exclude it from one execution context (any Playwright run where `CI=true`, which is every GHA runner), not from the repo. Note: a future nightly-on-GHA job would also exclude demo-ubi by the same mechanism unless it explicitly overrides `CI` or uses a separate Playwright config — captured in the runbook §4 as a "defer until needed" concern, NOT a guarantee made by this spec.
- **Do not add `'**/demo-ubi.spec.ts'` to the always-ignored slot** (the `'**/guides/**'` entry outside the CI ternary). That would silently kill local coverage. The vitest test asserts the entry is inside the CI branch, not the global branch.
- **Do not bump `timeout-minutes: 25`** in `pr.yml`'s smoke-test job. D-3 rejected this; the 25-min cap is now headroom against an excluded-demo-ubi runtime, not a regular threat.
- **Do not bundle `SMOKE_TEST=true` with this PR.** Flipping the variable is the operator's call after the §16 manual verification step and any optional smoke-runtime check. The PR clears the runtime block; the operator verifies and picks the moment.
- **Do not "fix while you're there" the AC-8 number drift in `demo-ubi.spec.ts:11`** (`25-minute ceiling per AC-8`). That file is not edited at all by this PR. The drift fix on the demo-ubi spec file is a separate concern and is deferred. **Note:** the comment text at `pr.yml:515-523` IS rewritten per FR-4 (structural to this PR's outcome — the "demo-ubi reseed exceeds the cap" framing has to come out in the same PR that ships the fix). The "24 min" reference at `pr.yml:519` is replaced as a side effect of that refresh, NOT as a tangential AC-8 edit.

---

## 5) Assumptions and dependencies

- **Dependency:** Playwright continues to evaluate `process.env.CI` at config-load time. **Status:** implemented (current behavior, no version-pin change in this PR). **Risk if missing:** none — the ternary pattern is upstream-stable; a Playwright major-version bump that broke `testIgnore` would also break the 6 existing CI-gated entries.
- **Dependency:** GitHub Actions sets `CI=true` automatically in every workflow runner (default GHA runner environment, [documented here](https://docs.github.com/en/actions/learn-github-actions/variables#default-environment-variables)). **Status:** GHA default — not workflow-overridden in `pr.yml`. **Risk if missing:** would also break the 6 existing CI-gated entries (no new risk introduced). Constraint: this workflow MUST NOT override `CI` to anything false-y in the `env:` block; the spec relies on the GHA default.
- **Dependency:** `infra_solr_smoke_stability` (shipped PR #383) made Solr actually boot, which is the proximate cause of the reseed runtime exceeding the cap. **Status:** implemented. **Risk if missing:** without it, the reseed's Solr scenario silently skipped and the smoke job stayed under 25 min, masking the underlying budget issue. The fact that Solr now boots is what makes this spec necessary.
- **Dependency:** vitest can read source files as text via `node:fs`. **Status:** implemented (standard Node API). **Risk if missing:** none.
- **No dependency** on `infra_smoke_fork_pr_secret_skip` (the sibling smoke-red issue). The two are independent failure modes; either can ship without the other.

---

## 6) Actors and roles

- **Primary actor(s):** RelyLoop maintainers (engineering team) who run CI on PRs.
- **Role model:** N/A — single-tenant install, no auth surface (MVP1-MVP3 per [`docs/01_architecture/tech-stack.md`](../../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** N/A — no API surface, no UI surface. The change is internal to CI test infrastructure.

### Authorization

N/A — single-tenant install, no auth surface. The PR's branch-protection + DCO + Conventional-Commits checks are unchanged.

### Audit events

N/A — no business state mutation. This change touches only CI test-runner configuration + documentation. `audit_log` does not exist yet (MVP2+); even when it does, CI infrastructure changes are not audit-event-emitting surfaces.

---

## 7) Functional requirements

### FR-1: Exclude `demo-ubi.spec.ts` from the CI Playwright run

- Requirement:
  - The CI-gated `testIgnore` branch in `ui/playwright.config.ts` **MUST** include the glob `'**/demo-ubi.spec.ts'`.
  - The entry **MUST** be added inside the `process.env.CI ? [...] : []` ternary, not in the always-ignored slot.
  - The change **MUST** be accompanied by an inline comment block in the same file, structured like the existing two precedent blocks (lines 38-46 and 47-58), naming this idea, citing PR #383 run 26790636716, summarising the AC-8 (1140s) / smoke-cap (25-min) mismatch, and pointing readers at `docs/03_runbooks/smoke-solr-stability.md` §4.
  - The 6 pre-existing CI-gated entries (`dashboard.spec.ts`, `dashboard-reseed.spec.ts`, `auto-followup.spec.ts`, `index-document-browser.spec.ts`, `studies-create-builder.spec.ts`, `studies-create-target-dropdown.spec.ts`) **MUST** be preserved unchanged.
- Notes: This is the entire functional fix. Local `pnpm test:e2e` (with `CI=` unset) keeps demo-ubi in the run.

### FR-2: Regression guard

- Requirement:
  - A new vitest unit test at `ui/src/__tests__/playwright-config-test-ignore.test.ts` **MUST** assert:
    - (a) `'**/demo-ubi.spec.ts'` appears in the `testIgnore` array's CI-gated branch in `playwright.config.ts` (the test reads the file as text from disk).
    - (b) All 7 expected CI-gated spec entries (the 6 pre-existing + `demo-ubi`) are present in that branch.
    - (c) `'**/demo-ubi.spec.ts'` does NOT appear outside the CI ternary (i.e., is not unconditionally ignored — local coverage stays intact).
  - The test **MUST** fail if any of the three assertions are violated.
  - **Path resolution.** The vitest run shape is `pnpm --dir ui test`, which sets cwd to `ui/`. The test **MUST** locate `playwright.config.ts` via a cwd-relative path (`path.resolve(process.cwd(), 'playwright.config.ts')`) OR via `import.meta.url` resolution to the package root. It **MUST NOT** assume cwd is the repo root (which would resolve to a non-existent `ui/ui/playwright.config.ts`).
- Notes: Text-grep approach is intentional — the lowest-coupling option, no module-reload tricks. The test serves as a regression guard against (i) accidental deletion of the entry during a config refactor, (ii) accidental promotion outside the CI branch, (iii) accidental deletion of a sibling CI-gated entry. It does NOT directly verify Playwright discovery behavior under `CI=true` / `CI=` unset — that's verified once at PR-review time via §16's manual `playwright test --list` step.

### FR-3: Runbook update

- Requirement:
  - `docs/03_runbooks/smoke-solr-stability.md` **MUST** receive a new section "§4 Reseed runtime (demo-ubi exclusion)" appended after the existing §3 (or wherever it fits the runbook's flow).
  - The section **MUST** describe: (i) why the exclusion exists (AC-8 mismatch with the smoke-job 25-min cap); (ii) where it lives (`ui/playwright.config.ts` testIgnore CI branch — single source of truth); (iii) the **local-coverage promise** — `demo-ubi.spec.ts` still runs under `pnpm test:e2e` when `CI=` unset (the normal local-dev case); (iv) the **nightly-CI caveat** — a future nightly-on-GHA job would also exclude demo-ubi by the same mechanism unless it explicitly overrides `CI` or uses a separate Playwright config (defer until needed, not a guarantee made here); (v) the path forward if per-PR demo-ubi smoke coverage is ever wanted (Option C from the idea — env-var scenario filter, deferred per D-2).
  - The section **MUST** cross-link to `ui/playwright.config.ts` and `ui/tests/e2e/demo-ubi.spec.ts`.
- Notes: The runbook is the human-facing place a maintainer looks first when smoke is red. The runtime-budget side of the lever cascade needs documentation parity with the heap-cap side.

### FR-4: `pr.yml` comment refresh

- Requirement:
  - The SMOKE_TEST opt-in note block at `.github/workflows/pr.yml:42-57` **MUST** be updated so the "demo-ubi reseed exceeds the 25-min cap" framing is replaced with "demo-ubi reseed is CI-excluded via playwright.config.ts testIgnore — runtime budget is expected to fit within 25 min pending operator verification (see `infra_smoke_reseed_runtime_budget` spec §16); operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke signal once verified".
  - The smoke-test job comment block at `.github/workflows/pr.yml:515-523` **MUST** be updated so the "AC-8 bounds at 24 min" + "Solr actually booting now pushes total wall-clock past the cap" framing is replaced with "Playwright runtime is expected to fit within the 25-min cap post-demo-ubi-exclusion (verify once via `SMOKE_TEST=true` post-merge per §16). The 25-min cap is expected headroom against the remaining specs."
  - The actual `if:` gate (`vars.SMOKE_TEST == 'true' && vars.SKIP_HEAVY_CI != 'true'`) **MUST NOT** change. The `timeout-minutes: 25` value **MUST NOT** change. No YAML structural change — comment text only.
- Notes: Stale comments outlive their accuracy. If shipped without this update, future maintainers reading `pr.yml` will be confused about why the smoke job is off and whether the runtime is still a problem.

### FR-5: `state.md` update

- Requirement:
  - The known-debt entry under "Known debt / fragility" naming `infra_smoke_reseed_runtime_budget` **MUST** be struck or rewritten as resolved, with a note that operator can flip `SMOKE_TEST=true` at their discretion to restore per-PR smoke signal.
  - The "Last 5 merges" block **MUST** be updated to include the merge per the standard `state.md` discipline (handled by the finalization step of `/impl-execute` — listed here only for traceability).
- Notes: `state.md` is the live snapshot. Leaving stale debt entries violates the "snapshot, not log" discipline.

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no API endpoints added or modified.

### 8.2 Contract rules

N/A.

### 8.3 Response examples

N/A.

### 8.4 Enumerated value contracts

N/A — no filter dropdowns, status enums, sort keys, or any other allowlist field added.

### 8.5 Error code catalog

N/A.

---

## 9) Data model and state transitions

N/A — no schema change, no Alembic migration, no ORM model change, no enum or CHECK constraint added. Alembic head stays `0022_solr_engine_auth_check` (unchanged).

### Required invariants

- **`'**/demo-ubi.spec.ts'` lives in the CI-gated `testIgnore` branch ONLY.** Enforced by FR-2's regression test. Violations produce either silent loss of local coverage (entry promoted outside the CI ternary) or silent loss of CI exclusion (entry removed).
- **`testIgnore` CI-gated branch lists ≥7 entries after this ships** (6 pre-existing + demo-ubi). Enforced by FR-2's regression test. A future PR that removes any of the 7 entries fails this test until it explicitly updates the assertion list.

### State transitions

N/A.

### Idempotency/replay behavior

N/A — single static config edit; no runtime state.

---

## 10) Security, privacy, and compliance

- **Threats:** None introduced. The change excludes a test spec from one CI execution context. No new data flow, no new secret, no new endpoint, no new dependency.
- **Controls:** N/A.
- **Secrets/key handling:** N/A — no `_FILE`-mounted secrets touched. No `OPENAI_API_KEY_TEST` interaction. The smoke job's secret-sanity-check step at `pr.yml:592` is untouched (that's `infra_smoke_fork_pr_secret_skip`'s domain).
- **Auditability:** N/A — no business state mutation.
- **Data retention/deletion/export impact:** N/A.

---

## 11) UX flows and edge cases

N/A — no user-facing UI. The "user" of this change is the maintainer running CI; their flow is unchanged (PR opens → CI runs → checks light up). The only behavioral change at the maintainer's level is: if they opt in to `SMOKE_TEST=true` (a separate operator action), the smoke job now completes within 25 min instead of being cancelled at the cap.

### Information architecture

N/A.

### Tooltips and contextual help

N/A.

### Primary flows

1. **Maintainer opens a PR.** Today: smoke job is off (`SMOKE_TEST` unset → false → `if:` gate skips the job). After this ships: same — operator hasn't flipped the variable yet. The CI checks that DO run (backend, frontend, both docker buildxes) are unchanged.
2. **Operator flips `SMOKE_TEST=true`** (separate action, after this PR ships and the §16 manual verification completes). Smoke job now runs on every PR; Playwright excludes 7 CI-gated specs (the 6 pre-existing + demo-ubi) plus the always-ignored `**/guides/**` glob; runtime is expected to fit within 25 min pending operator confirmation; the `smoke` check goes green when it does.
3. **Operator flips `SMOKE_TEST=` back to unset / `false`** if they want smoke quiet again. Same exclusion list, same runtime — no behavior change.
4. **Local developer runs `pnpm test:e2e`** (with `CI=` unset). Demo-ubi runs as today — no behavior change.

### Edge/error flows

- **A future PR re-adds `demo-ubi` to the smoke-CI run** (intentionally or by mistake). FR-2's vitest regression test catches it on the `frontend` job; the PR can't merge until the assertion is updated or the entry restored.
- **A future PR removes one of the 6 pre-existing CI-gated entries.** FR-2 also catches this. The assertion fails with a message naming which entry vanished. Either the PR is genuinely promoting that spec to per-PR smoke coverage (and the assertion is updated) or it's an accidental refactor break (and the entry is restored).
- **The smoke job remains red on a PR that has `SMOKE_TEST=true` set.** This spec does not promise smoke-green — it promises "runtime under 25 min for the Playwright step". Other failure modes (Solr crash, secret missing — `infra_smoke_fork_pr_secret_skip`'s domain, pytest smoke failure, Playwright assertion failure on one of the running specs) are independent.

---

## 12) Given/When/Then acceptance criteria

### AC-1: demo-ubi is excluded from the CI Playwright run

- Given a CI smoke run (`SMOKE_TEST=true`, runner with `CI=true`)
- When `pnpm --dir ui test:e2e` executes
- Then `demo-ubi.spec.ts` **MUST NOT** appear in Playwright's discovered-spec list (testIgnore prevents discovery, so the file is not reported as either run or skipped — it is absent)
- Example values:
  - Reporter stdout under `CI=true`: contains no occurrence of `demo-ubi.spec.ts`.
  - Verified once at PR review via `CI=true pnpm --dir ui exec playwright test --list 2>&1 | grep demo-ubi` returning no matches (see §16 release gate). Subsequent commits are guarded by FR-2's vitest regression test against the config file's text.
  - The 7 CI-gated specs (the 6 pre-existing — `dashboard.spec.ts`, `dashboard-reseed.spec.ts`, `auto-followup.spec.ts`, `index-document-browser.spec.ts`, `studies-create-builder.spec.ts`, `studies-create-target-dropdown.spec.ts` — plus `demo-ubi.spec.ts`) all stay excluded together — invariant preserved.

### AC-2: demo-ubi continues to run locally

- Given a local developer environment (`CI` env var is unset)
- When the developer runs `pnpm test:e2e` against a stack started by `make up`
- Then `demo-ubi.spec.ts` **MUST** appear in Playwright's discovered-spec list and **MUST** be eligible to run (subject to its own `SKIP_HEAVY_CI` opt-out, which is unrelated to this PR)
- Example values:
  - With `CI=` unset and `SKIP_HEAVY_CI=` unset: spec runs the `beforeAll` reseed and all 5 AC assertions per its existing implementation.
  - With `CI=` unset and `SKIP_HEAVY_CI=true`: spec skips at the file level via its own `test.skip(process.env.SKIP_HEAVY_CI === 'true', …)` gate (unchanged behavior).
  - Verified once at PR review via `pnpm --dir ui exec playwright test --list 2>&1 | grep demo-ubi` (with `CI=` unset) returning a match (see §16 release gate).

### AC-3: vitest regression test catches violations

- Given the FR-2 test file exists at `ui/src/__tests__/playwright-config-test-ignore.test.ts`
- When `pnpm --dir ui test` runs against the codebase
- Then the test **MUST** pass, asserting:
  - `'**/demo-ubi.spec.ts'` is present in the CI-gated branch.
  - All 7 expected entries are present in the CI-gated branch.
  - `'**/demo-ubi.spec.ts'` does not appear outside the CI ternary.
- Example values:
  - Mutation 1: remove `'**/demo-ubi.spec.ts'` from `playwright.config.ts` → test fails with a message naming the missing entry.
  - Mutation 2: move `'**/demo-ubi.spec.ts'` to the always-ignored slot (outside `process.env.CI ?`) → test fails with a message naming the leak.
  - Mutation 3: delete any sibling CI-gated entry → test fails with a message naming which entry vanished.

### AC-4: runbook §4 explains the exclusion

- Given `docs/03_runbooks/smoke-solr-stability.md` after this PR
- When a maintainer reads the file
- Then a section "§4 Reseed runtime (demo-ubi exclusion)" **MUST** be present and **MUST** contain:
  - Reason for exclusion (AC-8 vs smoke-cap mismatch — citing the actual 1140s/19 min hard ceiling from `feat_demo_ubi_study_comparison`'s spec).
  - Exclusion mechanism (`testIgnore` CI branch in `ui/playwright.config.ts`).
  - Local-coverage promise (file still runs under `pnpm test:e2e` when `CI=` unset — the normal local-dev case).
  - Nightly-CI caveat (a future nightly-on-GHA job would also exclude demo-ubi by the same mechanism unless it explicitly overrides `CI` or uses a separate Playwright config — defer until needed).
  - Path-forward note for Option C (env-var scenario filter) if per-PR coverage is ever needed.
- Example values: see §11 of `infra_solr_smoke_stability/feature_spec.md` for the runbook's existing tone and depth.

### AC-5: `pr.yml` comment blocks refreshed

- Given `.github/workflows/pr.yml` after this PR
- When a maintainer reads lines 42-57 and 515-523
- Then the comment text **MUST NOT** describe demo-ubi reseed as a runtime blocker
- And the comment text **MUST** acknowledge the exclusion + that `SMOKE_TEST=true` is **expected to fit within the cap pending operator verification** per §16 (NOT an unqualified "safe to enable")
- And the YAML structure (`if:`, `timeout-minutes:`, step list) **MUST NOT** have changed
- Example values:
  - Old (line 47): "demo-ubi reseed, which exceeds the per-PR budget"
  - New: "demo-ubi reseed is CI-excluded via playwright.config.ts testIgnore — runtime budget is expected to fit within 25 min; operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke signal (verify per the `infra_smoke_reseed_runtime_budget` spec §16)"

### AC-6: `state.md` debt entry struck

- Given `state.md` after this PR
- When a maintainer reads the "Known debt / fragility" section
- Then the `infra_smoke_reseed_runtime_budget` entry **MUST** be struck or rewritten as resolved, with operator's `SMOKE_TEST=true` opt-in path called out
- And the "Last 5 merges" section **MUST** include the new merge per standard discipline (handled by `/impl-execute` finalization)

### AC-7: no out-of-scope edits

- Given the PR's diff
- When a reviewer reads the changed files
- Then the diff **MUST NOT** include:
  - Any change to `ui/tests/e2e/demo-ubi.spec.ts` (the spec file itself stays unchanged; in particular the "25-minute ceiling per AC-8" line at `demo-ubi.spec.ts:11` is NOT touched here — that drift fix is the demo-ubi spec file's concern and is deferred per §3).
  - Any change to backend code under `backend/app/`
  - Any new env var (Option C is rejected per D-2)
  - Any change to `pr.yml`'s `timeout-minutes`, `if:` gate, secret-sanity-check step, Playwright invocation command (line 762), or any other YAML structural element
  - Any change to Alembic migrations
- And the diff **MUST** include exactly the 5 files named in FR-1..FR-5: `ui/playwright.config.ts`, `ui/src/__tests__/playwright-config-test-ignore.test.ts` (NEW), `docs/03_runbooks/smoke-solr-stability.md`, `.github/workflows/pr.yml` (comments only), `state.md`.
- And the `pr.yml` edits **MUST** be text-only inside the comment blocks at lines 42-57 and 515-523 (the rewrite per AC-5 incidentally removes the now-misleading "24 min" reference at line 519 as part of the comment refresh — this is structural to FR-4, NOT a tangential AC-8 drift fix).
- And the AC-5 replacement text **MUST** carry the qualified "expected to be safe pending operator verification" framing established in §1 and §16 — NOT an unqualified "safe to enable" claim.

---

## 13) Non-functional requirements

- **Performance:** When `SMOKE_TEST=true`, the smoke job's Playwright E2E step's wall-clock is **expected** to drop from "exceeds 25-min cap → cancelled" to fit within the cap, because the single largest consumer (demo-ubi's `beforeAll` reseed) is removed. The runtime of the remaining specs is not separately measured or budget-enforced by this PR — the §16 manual verification confirms the actual runtime once, and the optional post-merge `SMOKE_TEST=true` check confirms it under real GHA load. No new latency introduced; no new bound asserted on the surviving specs beyond what they already carry individually.
- **Reliability:** When `SMOKE_TEST=true`, the demo-ubi-shaped runtime failure mode is removed. Other failure modes (Solr boot, ES seed shards-race, individual spec flakes, total-runtime-budget breach from some other slow spec) are independent and unchanged by this PR.
- **Operability:**
  - Maintainer-facing log: Playwright's `testIgnore` prevents file discovery — excluded files do NOT appear as "skipped" in the reporter; they simply do not appear in the test list at all. The runbook §4 update is the durable explanation of why a maintainer searching the smoke-job log for `demo-ubi` finds nothing.
  - No new metrics, alerts, or logging emitted.
- **Accessibility/usability:** N/A — no UI surface.

---

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit tests (vitest, `ui/src/__tests__/`):**
  - `playwright-config-test-ignore.test.ts` (NEW) — per FR-2. Three assertions (AC-3 mutations 1-3 verifiable against a fixture-shaped re-implementation if needed; the actual test reads the production config file via `node:fs`).
- **Integration tests:** N/A — no DB-backed code, no service-layer code, no router code touched.
- **Contract tests:** N/A — no API contract change.
- **E2E tests:** N/A — the change IS to E2E configuration, but no new E2E spec is being added. The vitest regression test in §FR-2 is the canonical guard against config drift.
- **Backend tests:** N/A — no backend code path changed.

### Coverage gate impact

- **Backend `fail_under = 80`** — no impact. No backend code added or removed.
- **UI vitest** — 1 new test file. Vitest discovers it automatically via the standard `*.test.ts` glob.
- **UI ESLint / tsc / Next build** — no impact (config file edit doesn't change types or lint surface).

### Verification not covered by automated tests

AC-1 and AC-2 are about Playwright's discovery behavior under `CI=true` vs `CI=` unset, which the FR-2 vitest text-grep test does not directly exercise. These are verified once at PR review via the §16 release gate's manual `playwright test --list` step (one invocation per CI-context). Once verified, the FR-2 regression test holds the invariant on every subsequent commit by guarding the config file's text against accidental drift.

---

## 15) Documentation update requirements

- **`docs/01_architecture/`:** N/A — no architectural change.
- **`docs/02_product/`:** N/A — no user-facing capability change.
- **`docs/03_runbooks/smoke-solr-stability.md`:** FR-3 — append §4 "Reseed runtime (demo-ubi exclusion)" per AC-4 content requirements.
- **`docs/04_security/`:** N/A.
- **`docs/05_quality/`:** N/A.
- **`CLAUDE.md`:** No new convention introduced; the existing "Key Runbooks" table already lists `smoke-solr-stability.md`, which now picks up the §4 content via FR-3. No `CLAUDE.md` edit required.
- **`state.md`:** FR-5 — strike the debt entry; merge entry added by `/impl-execute` finalization.
- **`.github/workflows/pr.yml`:** FR-4 — comment-only refresh per AC-5.

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — the exclusion is unconditional under `CI=true`. No flag, no canary.
- **Migration/backfill expectations:** N/A — no schema change.
- **Operational readiness gates:** Operator decides when to flip `SMOKE_TEST=true` after this PR ships and CI is verified. The PR itself does not flip the variable.
- **Release gate:** The PR's `pr.yml` checks (backend, frontend including the new vitest test, both docker buildxes) **MUST** pass. The `smoke` check stays gated off as today (SMOKE_TEST unset). At PR review time the reviewer **MUST** run the two-step manual verification below to satisfy AC-1 + AC-2 (Playwright discovery behavior is not covered by the FR-2 vitest text-grep). The optional smoke-runtime end-to-end check is operator-driven post-merge.

  **Manual verification step (one-shot, at PR review):**
  ```bash
  # AC-1 — demo-ubi is NOT discovered when CI=true
  CI=true pnpm --dir ui exec playwright test --list 2>&1 | grep -c demo-ubi
  # expect: 0

  # AC-2 — demo-ubi IS discovered when CI is unset
  unset CI; pnpm --dir ui exec playwright test --list 2>&1 | grep -c demo-ubi
  # expect: > 0
  ```

  **Optional post-merge smoke-runtime verification (operator-driven):** Set `gh variable set SMOKE_TEST --body true` on a no-op PR; confirm the `smoke` check completes green within the 25-min cap. If green, leave SMOKE_TEST enabled (per-PR smoke restored). If still over budget (some other slow spec or runner regression), capture as a follow-up idea; the runtime block this PR clears is the demo-ubi-shaped one.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (testIgnore extension) | AC-1, AC-2, AC-7 | Story 1.1 | (verified by FR-2's vitest test; manual smoke verify per §16 release gate) | — |
| FR-2 (vitest regression guard) | AC-3 | Story 1.2 | `ui/src/__tests__/playwright-config-test-ignore.test.ts` (NEW) | — |
| FR-3 (runbook §4) | AC-4 | Story 1.3 | (none — doc edit) | `docs/03_runbooks/smoke-solr-stability.md` |
| FR-4 (pr.yml comment refresh) | AC-5, AC-7 | Story 1.4 | (none — comment-only YAML edit) | `.github/workflows/pr.yml` |
| FR-5 (state.md update) | AC-6 | Story 1.5 (+ `/impl-execute` finalization for the merge entry) | (none — doc edit) | `state.md` |

---

## 18) Definition of feature done

This feature is complete when:

- [ ] FR-1 ships: `'**/demo-ubi.spec.ts'` lives in the CI-gated `testIgnore` branch with an inline comment block matching the existing precedent shape.
- [ ] FR-2 ships: `ui/src/__tests__/playwright-config-test-ignore.test.ts` exists and passes `pnpm --dir ui test`.
- [ ] FR-3 ships: `docs/03_runbooks/smoke-solr-stability.md` has §4 with AC-4's content.
- [ ] FR-4 ships: `.github/workflows/pr.yml` comment blocks at lines 42-57 and 515-523 are refreshed per AC-5 (text only, no YAML structural change).
- [ ] FR-5 ships: `state.md` known-debt entry is struck/resolved per AC-6.
- [ ] All `pr.yml` checks green (backend, frontend including new vitest test, both docker buildxes). `smoke` stays gated off — the PR does NOT promise smoke-green; it promises "runtime budget block cleared".
- [ ] No out-of-scope edits per AC-7.
- [ ] No open questions remain in §19.

---

## 19) Open questions and decision log

### Open questions

_None._ All forks locked during idea-preflight 2026-06-02 (see Decision log below).

### Decision log

- **2026-06-02 — D-(-2) (cross-model cycle 3, this spec):** Final convergence cycle. One Medium finding: FR-4 + §13 retained unqualified "runtime budget is back under 25 min" / "well under 25 min" wording that the cycle-2 sweep didn't catch (those sections weren't on the cycle-1 patch list either, so they slipped through). Aligned with §1/§16's "expected to fit within 25 min pending operator verification" framing; struck the unverified "remaining specs are bounded individually" claim from §13 Performance. Convergence stop rule hit (3-cycle cap + only Medium finding outstanding). All cross-model findings accepted across all cycles.
- **2026-06-02 — D-(-1) (cross-model cycle 2, this spec):** Cycle-2 review surfaced 4 incomplete-fix issues from cycle 1's patches: (a) §4 Anti-patterns + D-6 still said "don't fix pr.yml AC-8 drift" while FR-4 mandated the comment-block rewrite — narrowed both to demo-ubi.spec.ts:11 only; pr.yml comment edits are structural to FR-4. (b) Unqualified "safe to enable" survived in §2 nav table, §3 In-scope, §4 Anti-patterns, AC-5 — aligned all instances with §1/§16's "expected to be safe pending operator verification". (c) "Future nightly job preserves demo-ubi coverage" was wrong — nightly-on-GHA would also have `CI=true`, so the testIgnore would still fire; corrected in §4 Anti-patterns + AC-4 (nightly caveat added as runbook §4 content) + FR-3. (d) §11 Primary flow #2 muddled "7-CI-gated-out specs minus demo-ubi (8 entries excluded total)" — rephrased to "7 CI-gated specs (6 pre-existing + demo-ubi) plus the always-ignored `**/guides/**` glob". All 4 cycle-2 findings accepted and applied.
- **2026-06-02 — D-0 (cross-model cycle 1, this spec):** Following GPT-5.5 review cycle 1: (a) §3 Out-of-scope and AC-7's "AC-8 drift fix is out of scope" was internally contradictory with FR-4's mandate to rewrite the `pr.yml:515-523` comment block; clarified that the demo-ubi.spec.ts:11 drift fix is the only deferred AC-8 edit, while the pr.yml comment refresh per FR-4 is structural to this PR. (b) Manual `playwright test --list` verification added at PR review for AC-1/AC-2 (the vitest text-grep doesn't directly verify Playwright discovery). (c) "Safe to enable" framing softened to "expected to be safe pending operator verification". (d) §13 Operability claim about "Skipped via testIgnore" reporter output struck (testIgnore prevents discovery, not skip-reporting). (e) §2 hook-order explanation corrected — the real reason demo-ubi runs in smoke is that smoke's `if:` already requires `SKIP_HEAVY_CI != 'true'`, so the file-level skip never fires. (f) CI-gated counts normalized to "6 spec files + `**/guides/**`" before / "7 spec files + `**/guides/**`" after. (g) §5 `CI=true` ownership corrected to GHA default env, not actions/checkout. (h) FR-2 path resolution from cwd=`ui/`. All 8 cycle-1 findings accepted and applied.
- **2026-06-02 — D-1 (from idea):** Option A is locked as the implementation. Rationale: simplest scope, single-file edit precedent, matches the existing CI-gated `testIgnore` pattern. Captured in the idea at preflight time.
- **2026-06-02 — D-2 (from idea):** Option C (env-var scenario filter for per-PR demo-ubi coverage preservation) is explicitly NOT pursued — operator decision. Per-PR demo-ubi smoke coverage is intentionally accepted as lost; local `make up` smoke retains coverage.
- **2026-06-02 — D-3 (from idea):** Option B (`timeout-minutes` bump 25 → 35) rejected. The spec's own §14 estimates ~28 min worst case; even 35 min leaves <7 min margin that erodes with each future demo scenario. Burning headroom delays the next failure rather than fixing the budget mismatch.
- **2026-06-02 — D-4 (from idea):** Coordination with `infra_smoke_fork_pr_secret_skip` (same `pr.yml` smoke-test job edits). **Resolved by mechanism choice:** moving the exclusion into `playwright.config.ts` instead of `pr.yml`'s Playwright invocation line eliminates the CLI-flag collision concern. The two ideas can ship in either order with zero coordination overhead. Comment refreshes in `pr.yml` (FR-4) are textual-only and live in different comment blocks than the sibling will touch.
- **2026-06-02 — D-5 (this spec):** Mechanism = `testIgnore` extension, NOT a `pr.yml` CLI flag. Rationale: the idea's "single-line YAML edit" framing was the cheapest verbal description; the existing codebase precedent (6 CI-gated specs in `playwright.config.ts`'s `testIgnore`) is a stronger constraint than the verbal description, and following it yields a single source of truth for "what specs CI smoke skips". This is a Minor refinement of the idea's edit-shape, not a scope change.
- **2026-06-02 — D-6 (this spec):** AC-8 citation drift in `demo-ubi.spec.ts:11` (25 min ceiling) vs. the spec's actual 1140s / ~19 min hard ceiling is captured but NOT corrected in this PR — the demo-ubi spec file is not edited at all here. The drift fix on that test file is a separate concern (the canonical fix is to update either the comment or the AC-8 number itself, both of which are scope-wider than this PR's "unblock smoke runtime" goal). The `pr.yml:519` "24 min" reference, by contrast, IS replaced as part of FR-4's structural comment refresh — it's incidental to the refresh, not a tangential AC-8 edit.
- **2026-06-02 — D-7 (this spec):** No new vitest helper / fixture / abstraction. The regression test in FR-2 uses `node:fs` to read `ui/playwright.config.ts` as text and grep for the expected entries. Rationale: the lowest-coupling option; no module-reload tricks; the test serves as both a structural assertion and a comment-anchor that future editors can't miss when they touch the config.
