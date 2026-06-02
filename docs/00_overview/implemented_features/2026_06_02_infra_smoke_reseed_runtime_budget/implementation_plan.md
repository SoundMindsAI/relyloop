<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Implementation Plan — `infra_smoke_reseed_runtime_budget`

**Date:** 2026-06-02
**Status:** Complete (PR #424, squash-merged `035d7941` 2026-06-02)
**Primary spec:** [`feature_spec.md`](./feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../CLAUDE.md) "Never commit directly to main" + "Tangential discoveries — fix inline by default"
- [`docs/03_runbooks/smoke-solr-stability.md`](../../../../03_runbooks/smoke-solr-stability.md) — sibling runbook
- [`feat_demo_ubi_study_comparison/feature_spec.md`](../../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) — AC-8 reseed wall-clock ceiling

---

## 0) Planning principles

- Spec traceability first: every story maps to one FR.
- The plan is single-epic, single-phase, five stories — one per FR. Mechanical and linear.
- No backend, no migration, no API, no UI. Everything is config + test + docs.
- Verification gates are file-shape assertions (vitest text-grep) + manual Playwright `--list` verification at PR review (§16 of the spec).
- Keep PR diff to exactly 5 files (FR-1..FR-5). AC-7 is the contract.

## 1) Scope traceability (FR → epic/story)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (testIgnore extension) | Epic 1 / Story 1.1 | One-line addition + comment block. AC-1 (manual `--list`) + AC-2 (manual `--list`) + AC-7 (no out-of-scope edits). |
| FR-2 (vitest regression guard) | Epic 1 / Story 1.2 | New vitest file. Depends on Story 1.1 (asserts its output). AC-3 directly verified by this test. |
| FR-3 (runbook §4 update) | Epic 1 / Story 1.3 | Independent of code. AC-4. |
| FR-4 (pr.yml comment refresh) | Epic 1 / Story 1.4 | Two comment blocks at known line ranges. AC-5 + AC-7. |
| FR-5 (state.md update) | Epic 1 / Story 1.5 | Strike debt entry; merge entry added by `/impl-execute` finalization. AC-6. |

**No deferred phases.** The spec is single-phase. No `phase2_idea.md` is required.

## 2) Delivery structure

Single-epic, single-phase, five stories. Story order matches FR order. Each story is independently committable on the feature branch (`infra/smoke-reseed-runtime-budget`).

### Story-level detail requirements satisfied

This plan covers a config + docs change. Stories include **New files**, **Modified files**, **Tasks**, **DoD**. Sections that don't apply to this plan (Endpoints, Pydantic schemas, Key interfaces, UI element inventory, State dependency analysis, Legacy behavior parity) are explicitly marked N/A per the template's "purely documentation, refactor, or test-only" exemption.

### Conventions (project-specific)

- Vitest tests under `ui/src/__tests__/` use the `.test.ts` glob; vitest discovers them automatically.
- Vitest runs from `ui/` cwd via `pnpm --dir ui test`. Path resolution to `playwright.config.ts` is cwd-relative (`path.resolve(process.cwd(), 'playwright.config.ts')`) or via `import.meta.url`.
- `.github/workflows/pr.yml` comment blocks use the YAML `# `-prefix convention; never edit YAML keys to comment them out (use `if:` gates).
- Runbook sections under `docs/03_runbooks/` use `## §N <title>` heading style (e.g., `## §1 Why Solr heap is capped...`).
- `state.md` size is pre-commit hook-gated at 60 KB — keep edits surgical.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and [`feature_spec.md`](./feature_spec.md) before starting the first story.
1. **Read scope**: verify story outcome + Modified files + Tasks + DoD.
2. **Implement the story** (no backend in this plan, so no model/migration/repo step).
3. **Run targeted tests**:
   - Story 1.1: no vitest/Playwright test runs alone (verification of the config edit happens in Story 1.2's vitest assertions). `pnpm --dir ui lint` still runs per the Story 1.1 DoD — lint isn't a "test" but it's a mandatory gate.
   - Story 1.2: `pnpm --dir ui test playwright-config-test-ignore` (single-file vitest run) — must pass.
   - Story 1.3, 1.4, 1.5: no automated test; visual inspection of the modified file's section. Pre-commit hooks (markdownlint if wired, YAML syntax check) still run.
4. **No frontend run** — config-only change; no `pnpm dev` server needed.
5. **No E2E run alone** — Playwright is exercised by §16 manual `--list` verification at PR review time. Each story does NOT trigger E2E.
6. **Update docs/checklists** as defined by FR-3 (runbook), FR-4 (`pr.yml` comments), FR-5 (`state.md`).
7. **No migration** — `Alembic head stays 0022_solr_engine_auth_check` unchanged.
8. **Attach evidence in PR description**: command outputs from Story 1.2's vitest run + git diff stats per file. The PR description must include the §16 manual verification commands for the reviewer to run.
9. **After the final story**, update `state.md` (Story 1.5) and let `/impl-execute` finalization add the merge entry.

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Unblock the smoke job's Playwright runtime budget

**Goal:** Demo-ubi spec is excluded from the CI smoke Playwright run via the existing `testIgnore` precedent, with a vitest regression guard, runbook documentation, pr.yml comment refresh, and state.md debt strike — all on a single feature branch (`infra/smoke-reseed-runtime-budget`).

**Epic gate — pre-PR (hard stop before opening PR):**

- [ ] Stories 1.1–1.5 all complete.
- [ ] `pnpm --dir ui lint` clean.
- [ ] `pnpm --dir ui typecheck` clean (no .ts changes that affect types — the vitest file is a small additive).
- [ ] `pnpm --dir ui test` — full vitest suite passes (including the new file from Story 1.2).
- [ ] `make lint` + `make typecheck` clean (no backend changes, no Python lint regression).
- [ ] §16 manual verification: `CI=true pnpm --dir ui exec playwright test --list 2>&1 | grep -c demo-ubi` returns `0`; `unset CI && pnpm --dir ui exec playwright test --list 2>&1 | grep -c demo-ubi` returns a positive integer.
- [ ] Branch diff against `main` is exactly 5 files (per AC-7): `git diff --name-only main...HEAD` lists exactly `ui/playwright.config.ts`, `ui/src/__tests__/playwright-config-test-ignore.test.ts`, `docs/03_runbooks/smoke-solr-stability.md`, `.github/workflows/pr.yml`, `state.md`. (Use `main...HEAD` not `HEAD` — the worktree-only diff is empty once stories are committed.)
- [ ] `pr.yml` edits are text-only inside comment blocks at lines 42-57 and 515-523 — no YAML structural change. Verify with: `git diff main...HEAD -- .github/workflows/pr.yml | awk '/^[+-]/ && !/^([+-]{3})/ && $0 !~ /^[+-][[:space:]]*#/ { print }'` — expect zero output lines (every added/removed line must start with `#` or whitespace+`#`).

**Post-merge finalization checklist (handled by `/impl-execute` after PR merges; tracked here so the obligation is visible, not invisible inside the impl-execute machinery):**

- [ ] The "Last 5 merges (newest first)" block in `state.md` is updated with the merge entry for this PR per the project's `state.md` discipline ([`state.md` § "Last 5 merges"](../../../../state.md)). This satisfies AC-6 clause 2 (clause 1 — debt entry strike — shipped pre-PR in Story 1.5).
- [ ] Feature folder is moved from `planned_features/02_mvp2/infra_smoke_reseed_runtime_budget/` to `implemented_features/2026_<MM>_<DD>_infra_smoke_reseed_runtime_budget/` (date from merge day).
- [ ] Tracking issue #409 is closed with a link to the merged PR.

---

### Story 1.1 — Extend `testIgnore` CI branch with demo-ubi

**Outcome:** `ui/playwright.config.ts` excludes `demo-ubi.spec.ts` whenever `process.env.CI` is truthy, with an inline comment block matching the precedent shape at lines 38-46 and 47-58.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `ui/playwright.config.ts` | Add `'**/demo-ubi.spec.ts'` to the `testIgnore` ternary's CI-gated branch (currently lines 50-65). Add a new inline comment block above the new entry — matching the structural shape of the two existing precedent blocks (lines 38-46 and 47-58) — naming this idea (`infra_smoke_reseed_runtime_budget`), citing PR #383 run 26790636716, summarizing the AC-8 (1140s / ~19 min) vs smoke-cap (25-min) mismatch, and pointing readers at `docs/03_runbooks/smoke-solr-stability.md` §4. Do NOT move existing entries, do NOT change the `'**/guides/**'` always-ignored slot, do NOT change any other config field. |

**Endpoints:** N/A — config file only.

**Key interfaces:** N/A — config file only.

**Pydantic schemas:** N/A.

**UI element inventory:** N/A — no UI surface.

**State dependency analysis:** N/A — no shared state.

**Tasks**

1. Read [`ui/playwright.config.ts`](../../../../../ui/playwright.config.ts) lines 25-66 (the `testIgnore` block).
2. Identify the insertion point: just before the closing `]` of the CI-gated branch (currently around line 65, after the `studies-create-target-dropdown.spec.ts` entry).
3. Add a new comment block (4-6 lines) above the new entry, matching the prose style of the existing two precedent blocks. Mention: (a) the idea slug, (b) PR #383 + run 26790636716, (c) the AC-8 (1140s = ~19 min hard ceiling per `feat_demo_ubi_study_comparison`'s spec §AC-8 / lines 324, 559-563) vs smoke-job 25-min cap mismatch, (d) the local-coverage promise (`CI=` unset keeps the spec in), (e) cross-link to `docs/03_runbooks/smoke-solr-stability.md` §4 for the lever-cascade context.
4. Add the entry: `'**/demo-ubi.spec.ts',` matching the existing entry style (single-quoted glob, trailing comma).
5. Do NOT reformat the surrounding entries. Do NOT change `'**/guides/**'`. Do NOT change `fullyParallel`, `workers`, `timeout`, or any other config field.
6. Verify by reading the file — the CI-gated branch should now have 7 entries (the 6 pre-existing + demo-ubi).

**Definition of Done (DoD)**

- [ ] `ui/playwright.config.ts` contains the new entry `'**/demo-ubi.spec.ts'` inside the `process.env.CI ?` ternary's true branch.
- [ ] A new inline comment block names this idea + PR #383 + AC-8 mismatch + cross-link to the runbook §4.
- [ ] The 6 pre-existing CI-gated entries are unchanged in order, content, and quoting.
- [ ] `'**/guides/**'` always-ignored slot is unchanged.
- [ ] No other field in the config is touched.
- [ ] `pnpm --dir ui lint` passes against the modified file.
- [ ] `git diff ui/playwright.config.ts` shows additions only (new comment + new array entry); no line deletions.

---

### Story 1.2 — Vitest regression guard against testIgnore drift

**Outcome:** A new vitest test file asserts the post-Story-1.1 testIgnore shape — including the demo-ubi entry being in the CI-gated branch (not outside it), all 7 expected entries present, and no other regressions.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/playwright-config-test-ignore.test.ts` | Regression guard for the testIgnore CI-gated branch. Reads `playwright.config.ts` as text (cwd-relative, since vitest runs from `ui/`); asserts (a) demo-ubi entry is in the CI ternary branch, (b) all 7 expected CI-gated entries present, (c) demo-ubi does NOT appear outside the CI ternary (local coverage stays intact). |

**Modified files:** none.

**Endpoints:** N/A.

**Key interfaces** (vitest file only)

```typescript
// ui/src/__tests__/playwright-config-test-ignore.test.ts
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';

// Vitest runs from cwd=ui/, so playwright.config.ts is at the cwd root.
const CONFIG_PATH = path.resolve(process.cwd(), 'playwright.config.ts');

// Source of truth: the 7 spec files the CI-gated testIgnore branch must list
// after `infra_smoke_reseed_runtime_budget` ships.
const EXPECTED_CI_GATED_ENTRIES: readonly string[] = [
  "'**/dashboard.spec.ts'",
  "'**/dashboard-reseed.spec.ts'",
  "'**/auto-followup.spec.ts'",
  "'**/index-document-browser.spec.ts'",
  "'**/studies-create-builder.spec.ts'",
  "'**/studies-create-target-dropdown.spec.ts'",
  "'**/demo-ubi.spec.ts'",
];

describe('playwright.config.ts testIgnore CI-gated branch', () => {
  // ... 3 it() blocks per the DoD assertions below
});
```

**Pydantic schemas:** N/A.

**UI element inventory:** N/A.

**State dependency analysis:** N/A.

**Tasks**

1. Create the file `ui/src/__tests__/playwright-config-test-ignore.test.ts` with the key-interfaces skeleton above.
2. Implement assertion (a) — demo-ubi entry is in the CI-gated branch:
   - Read the config text once.
   - Locate the `process.env.CI` ternary substring (use a robust regex/string-search pattern, e.g. find `process.env.CI` then look for the next `? [` and the matching closing `] : []`).
   - Assert `'**/demo-ubi.spec.ts'` appears within the substring between the `[` and `]` of the true branch.
3. Implement assertion (b) — all 7 expected entries present: iterate `EXPECTED_CI_GATED_ENTRIES` and assert each substring is inside the CI-branch slice.
4. Implement assertion (c) — demo-ubi NOT outside the CI ternary: compute the slice BEFORE the CI ternary and the slice AFTER the closing `] : []`; assert `'**/demo-ubi.spec.ts'` does NOT appear in either slice. (Local coverage preservation guard.)
5. Run `pnpm --dir ui test playwright-config-test-ignore` — single-file run; must pass.
6. Run `pnpm --dir ui test` — full suite must pass with the new file included.

**Definition of Done (DoD)**

- [ ] The file `ui/src/__tests__/playwright-config-test-ignore.test.ts` exists with 3 assertions matching AC-3 (mutations 1, 2, 3 from the spec).
- [ ] Single-file run `pnpm --dir ui test playwright-config-test-ignore` passes.
- [ ] Full vitest suite `pnpm --dir ui test` passes (no regression in other tests).
- [ ] Manual mutation check (informal — not committed): temporarily remove the `'**/demo-ubi.spec.ts'` line from `playwright.config.ts` and rerun the test; expect a failure naming the missing entry. Restore the line before commit.
- [ ] Manual mutation check 2: temporarily move `'**/demo-ubi.spec.ts'` outside the CI ternary (next to `'**/guides/**'`); expect assertion (c) to fail. Restore before commit.
- [ ] Path-resolution check: confirm the test file uses `process.cwd()` (or `import.meta.url`) such that it works when vitest runs from `ui/` cwd; it MUST NOT hardcode `ui/playwright.config.ts` (which would resolve to `ui/ui/playwright.config.ts` and fail).
- [ ] `pnpm --dir ui lint` passes against the new file.
- [ ] `pnpm --dir ui typecheck` passes (no ts errors).

---

### Story 1.3 — Add `§4 Reseed runtime (demo-ubi exclusion)` to smoke-solr-stability runbook

**Outcome:** `docs/03_runbooks/smoke-solr-stability.md` gains a new section §4 explaining the demo-ubi exclusion, where the mechanism lives, the local-coverage promise, the nightly-CI caveat, and the Option C path-forward.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `docs/03_runbooks/smoke-solr-stability.md` | Append (or insert before the trailing material if the runbook has a closing section) a new section `## §4 Reseed runtime (demo-ubi exclusion)` per AC-4 content requirements. |

**Endpoints:** N/A.

**Key interfaces:** N/A.

**Pydantic schemas:** N/A.

**UI element inventory:** N/A.

**State dependency analysis:** N/A.

**Tasks**

1. Read [`docs/03_runbooks/smoke-solr-stability.md`](../../../../../docs/03_runbooks/smoke-solr-stability.md) in full — note the existing §1, §2, §3 structure and tone (concise prose, file:line citations).
2. Identify the insertion point: end of the document, OR before any final "Where to look next" / footer section if one exists. The new §4 should follow §3 in numeric order.
3. Write the §4 section. Required content (per spec §FR-3 + AC-4):
   - **Why the exclusion exists.** AC-8 vs smoke-cap mismatch — cite the actual 1140s (~19 min hard ceiling) from `feat_demo_ubi_study_comparison`'s spec lines 324, 559-563; note §14's ~28 min worst-case estimate; explain that Playwright + smoke-job setup overhead pushes total wall-clock past the 25-min smoke cap.
   - **Where the mechanism lives.** `ui/playwright.config.ts` testIgnore CI branch (single source of truth — `pr.yml` does NOT duplicate the spec name in YAML).
   - **Local-coverage promise.** The file still runs under `pnpm test:e2e` when `CI=` unset (the normal local-dev case).
   - **Nightly-CI caveat.** A future nightly-on-GHA job would also exclude demo-ubi by the same mechanism unless it explicitly overrides `CI` or uses a separate Playwright config — defer until needed, not a guarantee made here.
   - **Path forward for Option C** (env-var scenario filter on the reseed orchestrator) if per-PR demo-ubi smoke coverage is ever wanted (deferred per spec §19 D-2).
   - Cross-link to `ui/playwright.config.ts` and `ui/tests/e2e/demo-ubi.spec.ts`.
4. Match the existing runbook's tone — concise, file:line citations, no marketing language.
5. Confirm Markdown rendering is clean (`make lint` or `pre-commit run --files docs/03_runbooks/smoke-solr-stability.md` if markdownlint hook is wired).

**Definition of Done (DoD)**

- [ ] `docs/03_runbooks/smoke-solr-stability.md` has a new section `## §4 Reseed runtime (demo-ubi exclusion)`.
- [ ] All 5 AC-4 content elements (reason / mechanism / local-coverage promise / nightly-CI caveat / Option C path-forward) are present in the section.
- [ ] Cross-links to `ui/playwright.config.ts` and `ui/tests/e2e/demo-ubi.spec.ts` are present and resolvable (relative paths from the runbook).
- [ ] The actual `1140s (~19 min)` AC-8 number from `feat_demo_ubi_study_comparison/feature_spec.md:324` is cited, NOT the 24/25-min downstream drift.
- [ ] Existing §1, §2, §3 are unchanged.
- [ ] No other doc is edited as part of this story.
- [ ] If markdownlint is wired in pre-commit, the hook passes against the modified file.

---

### Story 1.4 — Refresh `.github/workflows/pr.yml` comment blocks

**Outcome:** Two comment blocks in `pr.yml` (lines 42-57 and 515-523) are refreshed to reflect the cleared runtime block. No YAML structural change — comments only.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | Refresh comment text at lines 42-57 (SMOKE-TEST opt-in switch note) and lines 515-523 (smoke-test job header / timeout-minutes comment) per spec AC-5. NO change to YAML structure: `if:`, `timeout-minutes:`, step list, env block, secret-sanity-check step, Playwright invocation line (762) — all unchanged. |

**Endpoints:** N/A.

**Key interfaces:** N/A.

**Pydantic schemas:** N/A.

**UI element inventory:** N/A.

**State dependency analysis:** N/A.

**Tasks**

1. Read `.github/workflows/pr.yml` lines 42-57 and 515-523 in full to understand the current comment shape.
2. Rewrite lines 42-57 (SMOKE-TEST opt-in switch note). Required content (per spec AC-5 + spec D-(-2)):
   - Replace "demo-ubi reseed, which exceeds the per-PR budget" framing.
   - New framing: "demo-ubi reseed is CI-excluded via `playwright.config.ts` testIgnore — runtime budget is **expected to fit within 25 min pending operator verification** (see `infra_smoke_reseed_runtime_budget` spec §16); operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke signal once verified".
   - Preserve the existing opt-in commands (`gh variable set SMOKE_TEST --body true` / `gh variable delete SMOKE_TEST`).
   - Preserve the cross-link to `SKIP_HEAVY_CI`.
3. Rewrite lines 515-523 (smoke-test job header / timeout-minutes comment). Required content (per spec AC-5):
   - Replace "AC-8 bounds at 24 min" + "Solr actually booting now pushes total wall-clock past the cap" framing.
   - New framing: "Playwright runtime is **expected to fit within the 25-min cap** post-demo-ubi-exclusion (verify once via `SMOKE_TEST=true` post-merge per the spec §16). The 25-min cap is expected headroom against the remaining specs."
   - Keep the `timeout-minutes: 25` value AND the explanation of how it was set (the line keeps the 15→25 bump story for archaeology).
4. Verify NO YAML structural change:
   - `git diff -U0 .github/workflows/pr.yml` — every added/removed line should start with `#`.
   - The `if:` gate at line 50 is unchanged.
   - The `timeout-minutes: 25` at line 523 is unchanged.
   - The `needs:`, `env:`, `permissions:`, `steps:` blocks are unchanged.
   - The secret-sanity-check step at line 592 is unchanged.
   - The Playwright invocation at line 762 (`run: pnpm --dir ui test:e2e`) is unchanged.

**Definition of Done (DoD)**

- [ ] Comment block at `pr.yml:42-57` is refreshed per AC-5 (qualified "expected to fit pending operator verification" framing, NOT unqualified "safe to enable").
- [ ] Comment block at `pr.yml:515-523` is refreshed per AC-5 (qualified runtime claim + the §16 verification reference).
- [ ] No YAML structural element changed: confirmed via `git diff -U0` — every changed line starts with `#`.
- [ ] The `if:`, `timeout-minutes:`, `needs:`, `env:`, `permissions:`, `steps:`, and the Playwright invocation line are byte-identical pre/post.
- [ ] No other comment block in `pr.yml` is touched. The edits are constrained STRICTLY to lines 42-57 and 515-523 per AC-7. The SKIP_HEAVY_CI note at the top of the file, the per-job env comments, the failure-diagnostics step comments, and every other comment block in `pr.yml` are byte-identical pre/post. (If any of those happen to cross-reference this idea by name, leave them untouched — they were captured at filing time and remain accurate as historical context.)
- [ ] The smoke-test job's `name:` (`smoke (operator-path tutorial flow)`) is unchanged.
- [ ] YAML syntax remains valid — verify with `python -c "import yaml; yaml.safe_load(open('.github/workflows/pr.yml'))"` or equivalent.

---

### Story 1.5 — Strike the smoke-runtime debt entry from `state.md`

**Outcome:** `state.md`'s "Known debt / fragility" section's entry for `infra_smoke_reseed_runtime_budget` is struck or rewritten as resolved, with the operator `SMOKE_TEST=true` opt-in path called out.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `state.md` | (i) Strike or rewrite-as-resolved the known-debt entry naming `infra_smoke_reseed_runtime_budget` (currently around lines 56-57 — verify exact location at story-start). Add a one-line note that operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke signal once they've completed the §16 manual verification. (ii) Refresh the "CI note" paragraph at lines 11-15 — specifically the stale sentences "drives the demo-ubi reseed, which routinely hits the 25-min job cap" and "Until the reseed-runtime fix lands, leave it off". Both become inaccurate once this PR ships. New framing must (a) preserve the SMOKE_TEST=OFF-by-default fact (operator-controlled), (b) name the demo-ubi exclusion as the now-shipped fix, (c) point at `infra_smoke_reseed_runtime_budget/feature_spec.md` §16 for the verification procedure. (iii) The "Last 5 merges" entry is NOT added in this story — `/impl-execute` finalization handles it after PR merge per the project's `state.md` discipline; see Epic gate item #9 below for the explicit tracking obligation. |

**Endpoints:** N/A.

**Key interfaces:** N/A.

**Pydantic schemas:** N/A.

**UI element inventory:** N/A.

**State dependency analysis:** N/A.

**Tasks**

1. Read [`state.md`](../../../../../state.md) in full — identify the current locations of both edit targets: (a) the `infra_smoke_reseed_runtime_budget` debt entry (snapshot says lines 56-57 — verify against current file), and (b) the "CI note" paragraph at lines 11-15.
2. **Edit (a) — strike or rewrite the debt entry as resolved.** Options:
   - **Strike** — replace with `~~**Old text**~~ — RESOLVED 2026-06-02 via this work (testIgnore exclusion). Operator may flip `SMOKE_TEST=true` to re-enable per-PR smoke once they verify per `infra_smoke_reseed_runtime_budget/feature_spec.md` §16.`
   - **Or rewrite** — replace with a brief "resolved" line referencing the PR + verification path.
   - Pick whichever shape matches the existing entries' style in the file.
3. **Edit (b) — refresh the "CI note" paragraph at lines 11-15.** Two stale sentences in particular MUST be replaced:
   - "drives the demo-ubi reseed, which routinely hits the 25-min job cap" → became inaccurate the moment Story 1.1 lands (the testIgnore exclusion removes the runtime block).
   - "Until the reseed-runtime fix lands, leave it off" → also stale (the fix IS landing in this PR).
   - New framing MUST preserve: (i) the SMOKE_TEST=OFF-by-default fact (operator-controlled, default state unchanged by this PR), (ii) name the demo-ubi exclusion as the now-shipped fix (cite `playwright.config.ts` testIgnore), (iii) point at `infra_smoke_reseed_runtime_budget/feature_spec.md` §16 for the manual verification procedure operators should run before flipping SMOKE_TEST.
   - Do NOT change the SMOKE_TEST flip commands (`gh variable set/delete SMOKE_TEST`).
4. Do NOT add a "Last 5 merges" entry — that's `/impl-execute` finalization's job after PR merges (per the project's state.md discipline; see Epic gate item #9).
5. Confirm size: `wc -c state.md` — must stay under 60 KB (pre-commit hook gate).

**Definition of Done (DoD)**

- [ ] The known-debt entry for `infra_smoke_reseed_runtime_budget` is struck or rewritten as resolved with the operator opt-in path called out.
- [ ] The "CI note" paragraph at lines 11-15 is refreshed: the two stale sentences ("drives the demo-ubi reseed, which routinely hits the 25-min job cap" and "Until the reseed-runtime fix lands, leave it off") are replaced with framing that (i) preserves the SMOKE_TEST=OFF-by-default fact (operator-controlled), (ii) names the demo-ubi exclusion as the shipped fix, (iii) points at `infra_smoke_reseed_runtime_budget/feature_spec.md` §16 for the verification procedure.
- [ ] The SMOKE_TEST flip commands in the CI note (`gh variable set/delete SMOKE_TEST`) are unchanged.
- [ ] No "Last 5 merges" entry added here (handled by `/impl-execute` finalization per Epic gate item #9).
- [ ] `wc -c state.md` is under 60 KB (the pre-commit `mvp1-dashboard-regen` / size-gate hook passes).
- [ ] No section of `state.md` OTHER than (a) the debt entry and (b) the CI note paragraph is touched.
- [ ] Pre-commit hooks run clean against the modified file (`pre-commit run --files state.md`).

---

## UI Guidance

**No UI Guidance required.** This plan does not add, move, or change any user-facing UI. Per the spec §11, the plan touches only CI test configuration + documentation + workflow comments. No JSX, no CSS, no React components, no Next.js pages, no tooltips, no glossary keys, no enumerated value contracts, no legacy-behavior-parity considerations.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `ui/src/__tests__/`
- Scope: Vitest regression guard for the playwright.config.ts testIgnore CI-gated branch.
- Tasks:
  - [ ] Add `ui/src/__tests__/playwright-config-test-ignore.test.ts` per Story 1.2.
- DoD:
  - [ ] Three assertions per AC-3: (a) demo-ubi in CI branch, (b) all 7 expected entries present, (c) demo-ubi NOT outside the CI ternary.
  - [ ] Full vitest suite passes.

### 3.2 Integration tests

- N/A — no DB, no service layer, no router.

### 3.3 Contract tests

- N/A — no API surface added or modified.

### 3.4 E2E tests

- N/A as automated coverage — but **AC-1 and AC-2 require one-shot manual `playwright test --list` verification at PR review** per spec §16. The Playwright suite is otherwise unaffected by this PR (the demo-ubi spec file itself is not edited; the smoke job stays gated off until the operator flips SMOKE_TEST).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/tests/e2e/demo-ubi.spec.ts` | full file | 1 | **No code change.** CI execution context flips from "runs and times out" to **absent from Playwright discovery** (`testIgnore` prevents discovery — the file is not run AND not reported as skipped; it simply doesn't appear in the test list). Local context unchanged: with `CI=` unset, the file is discovered normally. The file's `test.skip(SKIP_HEAVY_CI === 'true')` gate is unrelated and stays. |
| `ui/tests/e2e/*.spec.ts` (the 6 already-CI-gated ones) | full files | 6 | **No code change.** Each remains in the testIgnore CI branch with its existing rationale; the new entry is added below them in the same array. |
| `ui/tests/e2e/*.spec.ts` (the un-gated ones, e.g. `query-sets.spec.ts`) | full files | many | **No code change.** Their CI execution path is unaffected by this PR. |
| `backend/tests/**` | — | — | **No code change.** Zero backend impact. |

Why these files are safe: this PR adds exactly one line + comment block to a config file's testIgnore array. No existing test assertion path is altered.

### 3.5 Migration verification

- N/A — no schema change. Alembic head stays `0022_solr_engine_auth_check`.

### 3.6 CI gates

- [ ] `make lint` (backend ruff — no backend changes; runs as a no-op safety check).
- [ ] `make typecheck` (backend mypy — no backend changes; no-op safety check).
- [ ] `pnpm --dir ui lint` (ESLint flat — covers the new vitest file + the modified config file).
- [ ] `pnpm --dir ui typecheck` (tsc — covers the new vitest file).
- [ ] `pnpm --dir ui test` (full vitest suite, including the new file).
- [ ] `pnpm --dir ui build` (Next.js production build — defensive check; this PR doesn't touch Next.js but the gate stays).
- [ ] Backend test layers (`make test-unit`, `make test-integration`, `make test-contract`) — run on CI for the safety check; no scope changes in this plan.
- [ ] **Manual Playwright `--list` verification per spec §16** at PR review time (not a CI gate — a reviewer-administered check).

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — updated by Story 1.5 (debt entry strike). `/impl-execute` finalization adds the merge entry after PR merge.

**`architecture.md`** — **NOT updated.** No architectural change: CI config and test-runner exclusion logic don't qualify. The change is entirely covered by the runbook update (Story 1.3) + spec/plan docs (this artifact).

**`CLAUDE.md`** — **NOT updated.** No new convention introduced. The existing "Key Runbooks" table already lists `smoke-solr-stability.md`, which picks up the §4 content via Story 1.3. The existing `pr.yml` convention is unchanged.

### 4.1 Architecture docs (`docs/01_architecture/`)

- N/A — no architectural change.

### 4.2 Product docs (`docs/02_product/`)

- N/A — no user-facing capability change.

### 4.3 Runbooks (`docs/03_runbooks/`)

- [ ] Story 1.3 adds §4 to `smoke-solr-stability.md` (planned; not yet implemented).

### 4.4 Security docs (`docs/04_security/`)

- N/A.

### 4.5 Quality docs (`docs/05_quality/`)

- N/A.

**Documentation DoD**

- [ ] `state.md` is consistent with shipped behavior (debt entry struck).
- [ ] `smoke-solr-stability.md` §4 is consistent with the shipped `playwright.config.ts` mechanism.
- [ ] No other doc is touched.
- [ ] Pre-commit hooks pass against all modified docs.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- None. This PR adds a config entry + a vitest file + doc edits. There's nothing to refactor.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- The `testIgnore` array's existing entries are NOT reformatted or reordered (Story 1.1 DoD asserts this).
- The `playwright.config.ts` config object's other fields are NOT touched.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Playwright continues to evaluate `process.env.CI` at config-load time | Story 1.1 + AC-1 + AC-2 | Implemented (current behavior, no version bump) | None — the ternary pattern is upstream-stable; a Playwright bump that broke `testIgnore` would also break the 6 existing CI-gated entries. |
| `CI=true` set by GHA runner default env | AC-1 | Implemented (GHA documented default) | None — workflow does not override; would also break the 6 existing entries. |
| vitest can read source files via `node:fs` | Story 1.2 | Implemented (standard Node API) | None. |
| `infra_solr_smoke_stability` (shipped PR #383) made Solr actually boot | Spec rationale; no direct code dependency for this PR | Implemented (PR #383, merged 2026-06-02) | N/A — this PR ships regardless. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Operator flips `SMOKE_TEST=true` before §16 verification → smoke still red on first run | L | L | Spec §16 + pr.yml comment refresh both call out the verification step; the runbook §4 also names it. Worst case: one red CI run on a no-op PR; operator flips SMOKE_TEST back off and reads the §16 procedure. |
| Future PR re-adds demo-ubi to the smoke CI run (intentionally or by mistake) | L | M (smoke job times out again) | FR-2 vitest regression test catches it; the modifier must update both the config and the test assertion together. |
| Sibling `infra_smoke_fork_pr_secret_skip` lands first and conflicts | L | L | D-4 of the spec resolved this by moving the exclusion into `playwright.config.ts` (not `pr.yml`). The sibling's `pr.yml` edits are in different comment blocks + the secret-sanity-check step. Zero collision surface. |
| Playwright config edit accidentally reformats sibling entries (whitespace/quote drift) | L | L | Story 1.1 DoD asserts diff is additions-only. `git diff` review catches reformatting. |
| Manual `playwright test --list` verification skipped at PR review → AC-1/AC-2 not directly verified | M | L | DoD step lists it explicitly; PR description (Story 1.4 + impl-execute) will include the commands for the reviewer to run + paste output. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Vitest regression test fails on a future PR | Someone removes demo-ubi from testIgnore, or moves it outside the CI ternary, or removes a sibling CI-gated entry | Vitest reports the specific assertion failure with a message naming the missing/misplaced entry | The PR author either restores the entry or updates the test's `EXPECTED_CI_GATED_ENTRIES` array with a justification (commit message must explain why the entry is removed). |
| Playwright `testIgnore` no longer evaluates `process.env.CI` (upstream behavioral change) | Playwright major version bump | Both the 6 pre-existing entries and demo-ubi fail to gate properly | Would surface as a broken smoke job AND broken local-dev runs; not silent. Out-of-scope for this PR — handled when/if the Playwright bump happens. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. Story 1.1 (testIgnore extension) — foundational; must be in place before Story 1.2's vitest test can pass.
2. Story 1.2 (vitest regression guard) — depends on 1.1.
3. Stories 1.3, 1.4, 1.5 — independent of each other and of 1.1/1.2; can execute in any order.

### Parallelization opportunities

- Stories 1.3, 1.4, 1.5 are independent and can be implemented in any order or merged as a single commit. Per the project's "one commit per story" convention is overkill for doc-only edits — `/impl-execute` may bundle 1.3+1.4+1.5 into a single docs/comments commit for review tidiness.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single PR → merged → operator's choice when to flip `SMOKE_TEST=true`.
- **Feature flag strategy:** No new flag. Reuses the existing `SMOKE_TEST` repo variable shipped 2026-06-02 (no scope change to that variable; this PR just clears the technical block that prevented its use).
- **Migration/cutover steps:** None — no schema, no data migration.
- **Reconciliation/repair strategy:** None — no external system involved.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Extend `testIgnore` CI branch with demo-ubi
- [ ] Story 1.2 — Vitest regression guard against testIgnore drift
- [ ] Story 1.3 — Add `§4 Reseed runtime (demo-ubi exclusion)` to smoke-solr-stability runbook
- [ ] Story 1.4 — Refresh `.github/workflows/pr.yml` comment blocks
- [ ] Story 1.5 — Strike the smoke-runtime debt entry from `state.md`

### Blocked items

- _None._

### Done this sprint

- _None yet._

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (New files / Modified files tables).
- [ ] Endpoint contract implemented exactly as documented (N/A — no endpoints in this plan).
- [ ] Key interfaces implemented with compatible signatures (Story 1.2's vitest file shape).
- [ ] Required tests added/updated for all applicable layers (Story 1.2 adds the only test file).
- [ ] Commands executed and passed:
  - [ ] `pnpm --dir ui lint`
  - [ ] `pnpm --dir ui typecheck`
  - [ ] `pnpm --dir ui test` (full vitest suite)
  - [ ] `make lint` (backend; no-op safety check)
  - [ ] `make typecheck` (backend; no-op safety check)
- [ ] Migration round-trip evidence: N/A — no schema change.
- [ ] Related docs/checklists updated in same PR: Story 1.3 (runbook) + Story 1.4 (pr.yml comments) + Story 1.5 (state.md).
- [ ] **Manual Playwright `--list` verification recorded in PR description** per spec §16 (AC-1 + AC-2).
- [ ] AC-7 final check: `git diff --name-only main...HEAD` lists exactly 5 files (per the pre-PR epic gate). Do NOT use `git diff --stat HEAD` — that compares worktree to current branch HEAD and shows zero files once stories are committed.

---

## 11) Plan consistency review

### Spec ↔ plan FR coverage

| Spec FR | Plan story | Verified |
|---|---|---|
| FR-1 (testIgnore extension) | Story 1.1 | ✓ |
| FR-2 (vitest regression guard) | Story 1.2 | ✓ |
| FR-3 (runbook §4 update) | Story 1.3 | ✓ |
| FR-4 (pr.yml comment refresh) | Story 1.4 | ✓ |
| FR-5 (state.md update) | Story 1.5 | ✓ |

All 5 spec FRs covered. No orphans.

### Spec ↔ plan AC coverage

| Spec AC | Verification path |
|---|---|
| AC-1 (demo-ubi excluded under CI=true) | Manual `playwright test --list` at PR review (§16) + Story 1.2 vitest assertion (a) |
| AC-2 (demo-ubi included under CI=unset) | Manual `playwright test --list` at PR review (§16) + Story 1.2 vitest assertion (c) |
| AC-3 (vitest catches mutations) | Story 1.2 DoD includes manual mutation checks during implementation; ongoing guard is the vitest file itself |
| AC-4 (runbook §4 explains exclusion) | Story 1.3 DoD asserts the 5 required content elements |
| AC-5 (pr.yml comment blocks refreshed) | Story 1.4 DoD asserts text-only edit + qualified framing |
| AC-6 (state.md debt entry struck) | Story 1.5 DoD |
| AC-7 (no out-of-scope edits) | Epic gate asserts exactly 5 files changed; Story 1.4 DoD asserts pr.yml YAML structure unchanged |

All 7 ACs traced to either a story DoD or a §16 manual verification.

### Spec ↔ plan endpoint count

- Spec endpoints: 0 (N/A — no API surface).
- Plan endpoints: 0.
- Parity: ✓.

### Spec ↔ plan error code coverage

- Spec error codes: 0 (N/A).
- Plan contract tests: 0.
- Parity: ✓.

### Story internal consistency

- New files: 1 (`ui/src/__tests__/playwright-config-test-ignore.test.ts`, Story 1.2). No ownership conflicts.
- Modified files: 4 across Stories 1.1, 1.3, 1.4, 1.5. Each story owns exactly one file. No double-claims.
- Total files touched: 5. Matches AC-7's contract.
- Vitest test count: 1 (the new file). Matches §3.1 inventory.

### Gate arithmetic

- Epic gate lists 5 stories. Stories 1.1–1.5 below = 5. ✓
- Epic gate's "git diff is exactly 5 files" matches the AC-7 contract from the spec.

### Open questions resolved

- Spec §19 reports "_None._" — all forks locked in D-1..D-7. ✓

### Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| Vitest tests live in `ui/src/__tests__/` | `ls ui/src/__tests__/` shows `app/`, `components/`, `helpers/`, `lib/`, etc. as subdirs of __tests__ | Verified — placing the new file directly in `ui/src/__tests__/` matches the convention used by `playwright-config-discipline` siblings (see `data-table-column-discipline.test.tsx` placed at `ui/src/__tests__/components/common/...`) |
| Playwright config has 6 CI-gated entries in the ternary's true branch | Read `ui/playwright.config.ts:25-66` during spec phase | Verified |
| Alembic head is `0022_solr_engine_auth_check` | `ls migrations/versions/ \| sort \| tail -1` | Verified |
| No backend code touched | spec §3 In scope + Out of scope | Verified |
| `pr.yml:42-57` is the SMOKE-TEST opt-in switch comment block | Read during spec phase | Verified |
| `pr.yml:515-523` is the smoke-test job header / timeout-minutes comment block | Read during spec phase | Verified |
| `pr.yml:762` is `run: pnpm --dir ui test:e2e` (Playwright invocation — NOT to be edited) | Read during spec phase | Verified |
| `state.md` size constraint = 60 KB pre-commit hook | CLAUDE.md "## Active Work" section | Verified |
| `docs/03_runbooks/smoke-solr-stability.md` exists (118 lines) | `wc -l` during spec phase | Verified |

### Infrastructure path verification

- Migration directory: N/A — no migration.
- Alembic head: `0022_solr_engine_auth_check` (unchanged).
- Router registration: N/A — no router.
- Test file location: `ui/src/__tests__/playwright-config-test-ignore.test.ts` (sibling to other `*.test.ts` files under `ui/src/__tests__/`).

### Frontend data plumbing verification

- N/A — no frontend component touched.

### Persistence scope consistency

- N/A — no `localStorage` or `sessionStorage` usage.

### Enumerated value contract audit

- N/A — no `<select>`, filter dropdown, status badge, or sort control added or modified.

### Audit-event coverage audit

- N/A — no state mutation. The change touches only CI test-runner configuration + documentation. `audit_log` does not exist yet (MVP2+); even when it does, CI infrastructure changes are not audit-event-emitting surfaces.

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates (see §1 + §11).
- [x] Every story includes New files, Modified files, Tasks, and DoD. (Endpoints, Pydantic schemas, Key interfaces, UI element inventory, State dependency analysis are N/A by exemption — purely config + docs.)
- [x] Test layers explicitly scoped: only `unit` (vitest regression guard) applies; others marked N/A with justification.
- [x] Documentation updates across docs/01-05 are planned and owned (Story 1.3 → runbook).
- [x] Lean refactor scope: explicitly none.
- [x] Phase/epic gates measurable (epic gate has 9 checklist items: 5 story-complete checks + lint/typecheck/test + manual §16 verification + git-diff-5-files + YAML-comments-only check + finalization obligation #9).
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) performed with no unresolved findings.

---

## 13) Decision log

- **2026-06-02 — D-P1:** Single epic, single phase, 5 stories one-per-FR. Rationale: spec is tiny (no API, no schema, no UI); a fan-out beyond 1 epic adds ceremony without coverage value.
- **2026-06-02 — D-P2:** Story 1.2 vitest test reads `playwright.config.ts` as text via `node:fs` (cwd-relative resolution from `ui/`), NOT via module re-import. Rationale: lowest coupling, matches spec D-7, no module-cache invalidation tricks needed.
- **2026-06-02 — D-P3:** Stories 1.3/1.4/1.5 may be bundled into a single docs-and-comments commit during `/impl-execute` execution. Rationale: each is a small surgical edit on a single file; per-story commits are overkill for doc-only changes that ship together. The execution tracker still records them as separate stories for traceability; `/impl-execute` chooses the commit granularity.
- **2026-06-02 — D-P4:** No backend lint / typecheck / test surface change is asserted in the plan, but the gates still run as CI defaults — defensive. Rationale: if any of those fail unexpectedly, the cause is the test infrastructure (not this PR's changes), and the failure tells us the infra is degraded — useful signal.
- **2026-06-02 — D-P7 (cross-model cycle 3, this plan):** GPT-5.5 final convergence cycle surfaced 3 follow-on findings, all accepted: (a) Epic gate label said "hard stop before PR" but item #9 was a post-merge obligation → restructured into two checklists: pre-PR (items 1-8) and post-merge finalization (Last 5 merges, folder move, issue close). (b) §10 "AC-7 final check" command was `git diff --stat HEAD` which shows zero diff once stories are committed → corrected to `git diff --name-only main...HEAD`. Same correction propagated to the pre-PR epic gate's 5-file check and the YAML-comments-only awk command. (c) Story 1.4 DoD had an exception loosening AC-7's contract ("unless cross-references this idea, give a parenthetical") → removed; pr.yml edits are STRICTLY constrained to the two AC-5 comment blocks. 3-cycle convergence cap hit (cycle 3); cross-model loop terminates.
- **2026-06-02 — D-P6 (cross-model cycle 2, this plan):** GPT-5.5 surfaced 3 follow-on findings, all accepted: (a) Story 1.5's Tasks step 3 + DoD still said "verify CI note unchanged" while the cycle-1 Modified-files edit required the refresh — fixed by rewriting Tasks step 3 to explicitly describe both stale sentences to replace, and rewriting DoD to assert the refresh shape instead of "unchanged". (b) §12 Definition-of-plan-done said epic gate has 8 checkboxes; the cycle-1 patch added item #9 → updated to 9. (c) §4.3 Runbooks checkbox was marked `[x]` (complete) while the execution tracker had Story 1.3 unchecked → flipped to `[ ]` and labelled "planned". 3-cycle convergence cap is the next stop rule.
- **2026-06-02 — D-P5 (cross-model cycle 1, this plan):** GPT-5.5 review surfaced 5 findings, all accepted: (a) Story 1.5 expanded to also refresh `state.md` lines 11-15 CI-note stale framing (not just the debt entry); (b) Epic-gate item #9 added to explicitly track the post-merge "Last 5 merges" finalization obligation (AC-6 clause 2) so it's not silently delegated to `/impl-execute`'s internals; (c) Epic-gate YAML-structural-check command corrected from `grep -E '(?!...)'` (PCRE lookahead, unsupported in POSIX ERE) to portable `awk`; (d) AI Agent Execution Protocol Story 1.1 lint vs. test-run wording disambiguated; (e) §3.5 test impact audit terminology corrected from "skipped by testIgnore" to "absent from Playwright discovery" (matches the spec's cycle-1 correction).
