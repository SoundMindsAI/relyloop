# Feature Specification — chore_e2e_seed_acme_idea_obsolete

**Date:** 2026-05-25
**Status:** Approved
**Owners:** Eric Starr (eng); soundminds.ai (product)
**Related docs:**
- [`idea.md`](idea.md)
- Target of closure: [`../chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md)
- Coverage audit being refreshed: [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md)
- Source of OBE: [`docs/00_overview/implemented_features/2026_05_21_chore_guide_06_screenshot_refresh_target_picker/`](../../../00_overview/implemented_features/2026_05_21_chore_guide_06_screenshot_refresh_target_picker/)
- [`MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) — surfaces the obsolete idea in the Idea backlog
- **Depends on:** none (single-PR doc-only chore)

---

## 1) Purpose

- **Problem:** The planned-feature idea [`chore_e2e_seed_acme_helper_dead`](../chore_e2e_seed_acme_helper_dead/idea.md) (dated 2026-05-21) is now OBE — its central premise that `seedAcmeProductsChain` has "0 Playwright spec callers" was contradicted between 2026-05-21 and 2026-05-23 by commit `2cbcb93b chore(guides): regen guide 06 with realistic seed data + new target …`, which wired the helper into [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts) (import at line 28, call at line 34). Two artifacts still describe the helper as dead code: the obsolete idea file itself, and [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md) (matrix row line 18; gaps section lines 22–28; verdict lines 36–37 still say "8 of 9 helpers … 9th is dead code").
- **Outcome:** Both stale artifacts updated to reflect reality. The obsolete idea is closed with a one-paragraph status block citing the OBE commit; the coverage audit's matrix row, gaps section, and verdict are refreshed to reflect 9-of-9 coverage. The chore folder is moved to `implemented_features/` per the standard planned→implemented lifecycle. Subsequent `/pipeline status` and `MVP1_DASHBOARD.md` regen runs no longer surface confusing "dead code" framing for a helper that has a real caller.
- **Non-goal:** Refactoring `seedAcmeProductsChain` itself, expanding its caller set, adjusting `coverage-audit.md`'s broader structure beyond the three rows/sections the idea names, or revisiting the Path A vs. Path B decision (Path B effectively shipped — Path A is no longer available).

## 2) Current state audit

### Existing implementations

- [`docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md): 62-line idea file. Status line reads `Idea — surfaced during chore_e2e_test_rows_isolation Story 1.2 coverage audit`; Priority `Backlog`. Body proposes Path A (delete the helper, "probably correct") and Path B (wire a spec). Lines 11–16 describe the helper as a 140-line helper with no spec callers; line 6 cites `ui/tests/e2e/helpers/seed.ts:378` (stale — the helper actually lives at `seed.ts:441` with the interface `AcmeProductsChainSeed` at `seed.ts:407`, function body ~133 LOC). The stale line number is **not in scope to fix** — it lives in historical content of a file we're marking closed.
- [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md): 9-row coverage matrix. Row for `seedAcmeProductsChain` at line 18 lists spec callers as `**0 specs** — currently uncalled (see "Gaps" below)`. `## Gaps` subsection (lines 22–32) describes the helper as having no caller. `## Verdict` (lines 34–39) reports "8 of 9 helpers in the spec §2 inventory are covered" and labels the 9th as "dead code, captured as a separate idea file." The `seedAcmeProductsChain` definition still lives at [`ui/tests/e2e/helpers/seed.ts:441`](../../../../ui/tests/e2e/helpers/seed.ts#L441).
- [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts): real caller at line 28 (`import { seedAcmeProductsChain } from '../helpers/seed';`) and line 34 (`const chain = await seedAcmeProductsChain();`). Not modified by this chore — verified-only.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| N/A | doc-only chore; no URL refs change | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| N/A | doc-only chore; no tests affected | — | — |

### Existing behaviors affected by scope change

- **Idea-stage backlog rendering:** Current: `chore_e2e_seed_acme_helper_dead` shows as `Backlog` in [`MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md) Idea table row 16. New: the idea file's `Status:` line changes from `Idea — surfaced during chore_e2e_test_rows_isolation Story 1.2 coverage audit` to `Closed (2026-05-25) — superseded by guide-06 spec wiring (commit 2cbcb93b)`. The dashboard regen script will pick up the new status on next `make dashboard` run. Decision needed: **no** — locked in §19 D-1.
- **Coverage matrix verdict claim:** Current: "8 of 9 helpers … 9th is dead code." New: "9 of 9 helpers covered." Decision needed: **no** — direct factual update.

---

## 3) Scope

### In scope

- A. **Close the obsolete idea.** Update the existing `**Status:**` line at file line 4 of [`chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) in place — from `Idea — surfaced during …` to a closure marker citing the OBE commit (`2cbcb93b`) and the real caller (`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts`). Leave the rest of the body (including the `## Problem`, Path A, Path B, and remaining sections) intact as historical content. Rationale for in-place edit vs. prepended block: see §19 D-5.
- B. **Refresh the coverage audit.** Update three regions of [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md): (1) replace the `seedAcmeProductsChain` matrix row's `0 specs` text with a real caller citation; (2) replace the `## Gaps` subsection body to reflect no remaining gap; (3) update the `## Verdict` count from "8 of 9" to "9 of 9" and drop the "dead code" framing.
- C. **Move this chore's folder** from `planned_features/chore_e2e_seed_acme_idea_obsolete/` to `implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` as the final step of the chore's PR ceremony (per `impl-execute` Step 7 finalization).

### Out of scope

- Fixing the stale `seed.ts:378` line citation inside `chore_e2e_seed_acme_helper_dead/idea.md` (lives in historical content of a closed file — harmless and not load-bearing).
- Moving `chore_e2e_seed_acme_helper_dead/` to `implemented_features/` itself (Option B in [`idea.md`](idea.md) §"Proposed capabilities" — explicitly rejected because the recommendation locked Option A, which is a lower-ceremony closure).
- Any change to `seedAcmeProductsChain` itself, `seed.ts`, or any spec that exercises it.
- Refactoring `coverage-audit.md`'s broader structure (column set, header levels, file naming).
- Dashboard regeneration — `make dashboard` runs are out-of-scope; the next time anyone runs it, the new idea status will be picked up automatically.

### API convention check

N/A — doc-only chore; no API endpoints added or modified.

### Phase boundaries (if multi-phase)

Single phase, two PRs (matching the repo's standard finalization pattern observed in recent main: e.g., `8cded4ae docs: finalize feat_study_clone_narrow_bounds after PR #247 (#248)`):

- **PR A — Content PR.** Ships capabilities A and B (FR-1 through FR-4). Edits two files: `chore_e2e_seed_acme_helper_dead/idea.md` (FR-1) and `ui/tests/e2e/helpers/coverage-audit.md` (FRs 2–4). Plus the chore's own scaffolding (`feature_spec.md`, `implementation_plan.md`, `pipeline_status.md`).
- **PR B — Finalization PR.** Ships capability C (FR-5). One commit: `git mv docs/02_product/planned_features/chore_e2e_seed_acme_idea_obsolete/ docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` plus the standard `state.md` recent-changes update per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7. Opens against `main` only after PR A merges.

The two-PR split is the canonical RelyLoop finalization shape — not a phase boundary in the "deferred capability" sense (so no `phase2_idea.md` is needed).

---

## 4) Product principles and constraints

- **Doc-only changes.** No code paths affected, no migrations, no schema, no Compose changes.
- **Minimal-ceremony closure for OBE'd ideas.** Per [`idea.md`](idea.md) Recommendation: Option A (one-paragraph status block + coverage refresh). Heavyweight ceremony (move to `implemented_features/` with `pipeline_status.md` shim) was explicitly rejected as disproportionate.
- **Preserve historical content.** Do not delete or rewrite the body of `chore_e2e_seed_acme_helper_dead/idea.md` — the Path A / Path B framing remains as historical record of the original deliberation. Only the existing `**Status:**` line at file line 4 is mutated; nothing else changes.
- **Conventional Commits** (per CLAUDE.md absolute rule 7). Commit subject prefix is `chore:` or `docs:` per existing planned-feature folder convention.

### Anti-patterns

- **Do not** edit any line of `chore_e2e_seed_acme_helper_dead/idea.md` other than file line 4 (the existing `**Status:**` line). Preserving the body intact is the contract for closed-historical ideas, and rewriting it would obscure the original Path A/B deliberation. A prepended block above line 4 is *also* forbidden — see §19 D-5 for why in-place edit is the only correct form (the dashboard regex doesn't match parenthesized-header variants).
- **Do not** move `chore_e2e_seed_acme_helper_dead/` to `implemented_features/` — that's Option B, explicitly rejected in [`idea.md`](idea.md) Recommendation. Leaving the folder under `planned_features/` with a `Closed` status header gives the dashboard regen + future infra-sweep agents enough signal without the extra folder shuffle.
- **Do not** regenerate the dashboard or rebuild `MVP1_DASHBOARD.md` as part of this chore — that's a separate process (`make dashboard` or the pre-commit hook). Coupling them creates spurious diff churn unrelated to the chore's deliverable.
- **Do not** add a `tenant_id` column or any data-model touch — RelyLoop is single-tenant pre-MVP4 (CLAUDE.md absolute rule 2 activation context); doc-only chores must not introduce schema drift.

## 5) Assumptions and dependencies

- **Idea file at [`chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) still exists at planning time.** Status: verified (Read on 2026-05-25). Risk if missing: chore work item A becomes void — would need to escalate as "target already moved." Mitigation: pre-execution Read in the implementation plan re-verifies presence.
- **`coverage-audit.md` still contains the three regions named in §3 capability B** (matrix row, `## Gaps` subsection, `## Verdict` subsection). Status: verified (Read on 2026-05-25 — lines 18, 22–32, 34–39). Risk if missing: chore work item B becomes void or partially void — would need to escalate. Mitigation: pre-execution Read in the implementation plan re-verifies the exact line ranges.
- **No other in-flight PR is editing either target file.** Status: confirmed by `git log --since="2026-05-23" -- docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md ui/tests/e2e/helpers/coverage-audit.md` (no commits since the OBE). Risk: rebase conflicts if a parallel PR edits the same regions — low for both files at this time.

## 6) Actors and roles

- **Primary actor:** Internal contributor (one of: Eric Starr, future infra-sweep agent, or any human reviewer).
- **Role model:** N/A — single-tenant install, no auth surface. RelyLoop is single-tenant + no auth through MVP3 per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md).
- **Permission boundaries:** N/A. Both target files are checked-in markdown; standard repo permissions apply (PR → review → merge).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2; this chore is MVP1-era and touches no state-mutating code paths regardless.

---

## 7) Functional requirements

### FR-1: Update the obsolete idea's Status line to Closed

- Requirement:
  - The system (i.e., the PR) **MUST** edit the existing `**Status:**` line at file line 4 of [`docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) — currently `**Status:** Idea — surfaced during \`chore_e2e_test_rows_isolation\` Story 1.2 coverage audit` — to a closure marker containing three signals: (a) the literal substring `Closed`, (b) the literal substring `2026-05-25` (the closure date), and (c) the literal substring `2cbcb93b` (the OBE commit short SHA). A representative target form is: `**Status:** Closed (2026-05-25) — superseded by guide-06 spec wiring (commit \`2cbcb93b\`, 2026-05-22). Real caller: \`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts\`. No further action beyond the coverage-audit refresh that ships in the same PR.`
  - The system **MUST NOT** modify any line of the file *other than* line 4. The existing `## Problem`, Path A, Path B, `## Scope signals`, `## Why deferred`, and `## Relationship to other work` body remains intact as historical content of the original deliberation.
  - The system **MUST** preserve the file's existing trailing newline (POSIX text-file convention).
- Notes: The dashboard regen at [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) parses the FIRST line matching the regex `^\*\*Status:\*\*\s*(.+)$` via [`_extract_status_line`](../../../../scripts/build_mvp1_dashboard.py#L211) (line 213). Updating line 4 in place is the canonical way to mark closure — a parenthesized variant like `**Status (updated ...):**` is NOT picked up by the regex (literal `**Status:**` is required). Prepending a new block above line 4 with a different header form would leave the original `Idea` status as the dashboard's parsed value.

### FR-2: Refresh coverage-audit matrix row for seedAcmeProductsChain

- Requirement:
  - The system **MUST** replace the spec-callers cell on line 18 of [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md) from `**0 specs** — currently uncalled (see "Gaps" below)` to a real caller citation listing `guides/06_create_and_monitor_study.spec.ts` (matching the listing style of the other 8 helper rows — relative-to-`ui/tests/e2e/` paths, comma-separated, no markdown link wrapping).
  - The system **MUST NOT** change the `Helper` cell (`seedAcmeProductsChain`) or the `Registers` cell on the same row.
- Notes: The existing rows (lines 12–20) use plain-text spec basenames; the new entry must match that style for grep consistency. The matrix row count remains 9.

### FR-3: Refresh coverage-audit `## Gaps` subsection

- Requirement:
  - The system **MUST** replace the body of the `## Gaps` subsection (lines 22–32 inclusive) with the literal text `None as of 2026-05-25 — see commit \`2cbcb93b\` for the helper's first real caller wiring.` (or substantially equivalent two-sentence prose acknowledging closure of the prior gap).
  - The system **MUST** preserve the `## Gaps` header itself.
  - The system **MUST NOT** delete the `## Gaps` section entirely — keeping the header with an explicit "no gaps" body is the chore's deliverable per [`idea.md`](idea.md) §"Proposed capabilities" Option A bullet 2.
- Notes: Deleting the section would cause grep-based audits looking for the `## Gaps` anchor to silently miss the audit's clean state.

### FR-4: Refresh coverage-audit `## Verdict` subsection

- Requirement:
  - The system **MUST** update the first sentence of the `## Verdict` subsection (currently spans lines 36–38: `8 of 9 helpers in the spec §2 inventory are covered by at least one existing Playwright spec; the 9th (\`seedAcmeProductsChain\`) is dead code, captured as a separate idea file.`) to read `9 of 9 helpers in the spec §2 inventory are covered by at least one existing Playwright spec.`
  - The system **MUST NOT** modify the second sentence (currently spans lines 38–39: `The cleanup registry will be exercised on every run by ≥1 caller for every code path the system needs to drain.`) — that claim is still accurate.
- Notes: Counted via the matrix at lines 12–20 (verified 9 helpers).

### FR-5: Move chore folder to implemented_features after PR merge

- Requirement:
  - After the PR for this chore lands on `main`, the post-merge finalization step **MUST** `git mv` the folder `docs/02_product/planned_features/chore_e2e_seed_acme_idea_obsolete/` to `docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` per the standard planned→implemented lifecycle (per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7).
  - The system **MUST** then push the rename as a finalization commit (separate from the chore's content commits).
- Notes: This is the only FR that fires post-merge; FRs 1–4 fire pre-merge inside the PR.

## 8) API and data contract baseline

N/A — doc-only chore; no API surface, no data contract.

### 7.1–7.5

All subsections N/A. No endpoints, no error envelopes, no enumerated values, no error codes.

## 9) Data model and state transitions

N/A — doc-only chore; no schema changes, no new entities, no state transitions.

## 10) Security, privacy, and compliance

- **Threats:** None — both target files are non-secret markdown, no PII, no credentials in scope.
- **Controls:** N/A.
- **Secrets/key handling:** N/A.
- **Auditability:** Standard `git log` for the chore PR is sufficient.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

N/A — no UI changes. Two files are edited; one folder is renamed post-merge; no user-visible product surface changes.

## 12) Given/When/Then acceptance criteria

### AC-1: Obsolete idea's Status line updated to Closed

- Given the worktree at `feature/chore-e2e-seed-acme-idea-obsolete` immediately before the FR-1 edit.
- When the PR's FR-1 commit is applied.
- Then file line 4 of [`docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) **MUST** start with the literal prefix `**Status:**` AND contain all three required signal substrings:
  - Example values:
    - Required signal 1 (literal substring on line 4): `Closed`
    - Required signal 2 (literal substring on line 4): `2026-05-25`
    - Required signal 3 (literal substring on line 4): `2cbcb93b`
    - (A representative form: `**Status:** Closed (2026-05-25) — superseded by guide-06 spec wiring (commit \`2cbcb93b\`, 2026-05-22). Real caller: \`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts\`. No further action beyond the coverage-audit refresh that ships in the same PR.`)
  - And the file's `## Problem` section header **MUST** remain present at its original location (no body content shifted).
  - And running `git diff --stat HEAD~1 -- docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md` **MUST** show exactly 1 file changed with 1 insertion and 1 deletion (the single line-4 swap).
  - And [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py)'s `_extract_status_line` (line 213) **MUST** parse the new line as the canonical Status when run against the edited file (verified by `python3 -c 'from scripts.build_mvp1_dashboard import _extract_status_line; print(_extract_status_line(open(...).read()))'` returning a string starting with `Closed`).

### AC-2: Coverage-audit matrix row refreshed

- Given `ui/tests/e2e/helpers/coverage-audit.md` immediately before the FR-2 edit.
- When the PR's FR-2 commit is applied.
- Then the matrix row for `seedAcmeProductsChain` **MUST** name the real caller spec basename `06_create_and_monitor_study.spec.ts` AND **MUST NOT** contain the strings `0 specs`, `currently uncalled`, or `see "Gaps" below`.
  - Example values:
    - Required substring in the `seedAcmeProductsChain` row: `06_create_and_monitor_study.spec.ts`
    - Forbidden substring in the row: `0 specs`

### AC-3: `## Gaps` subsection refreshed to no-gap state

- Given `coverage-audit.md` immediately before the FR-3 edit.
- When the PR's FR-3 commit is applied.
- Then the `## Gaps` header **MUST** still be present.
  - And the body following the header **MUST** acknowledge the closure (literal substring `None as of 2026-05-25` or equivalent two-sentence prose).
  - And the body **MUST NOT** contain the prior dead-code claim (forbidden substring: `no spec caller`).

### AC-4: `## Verdict` subsection refreshed to 9-of-9

- Given `coverage-audit.md` immediately before the FR-4 edit.
- When the PR's FR-4 commit is applied.
- Then the `## Verdict` section's first sentence **MUST** start with `9 of 9 helpers`.
  - And the section **MUST NOT** contain the prior "8 of 9" framing (forbidden substring: `8 of 9`).
  - And the section **MUST NOT** contain the prior "dead code" framing (forbidden substring: `dead code`).
  - And the second sentence about the cleanup registry **MUST** remain present unchanged.

### AC-5: Folder moved to implemented_features after merge

- Given the chore PR is merged to `main` and CI is green.
- When the post-merge finalization commit (per `impl-execute` Step 7) is pushed.
- Then `docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` **MUST** exist on `main`.
  - And `docs/02_product/planned_features/chore_e2e_seed_acme_idea_obsolete/` **MUST NOT** exist on `main`.
  - And the moved folder **MUST** contain at minimum `idea.md`, `feature_spec.md`, `implementation_plan.md`, and `pipeline_status.md`.

## 13) Non-functional requirements

- **Performance:** N/A (doc-only).
- **Reliability:** N/A.
- **Operability:** The new `Closed` status line on the obsolete idea is parsed by `scripts/build_mvp1_dashboard.py:240-245` priority/status logic on the next `make dashboard` regen — verified that the script's `_load_planned` walks the `Status:` line. No alerting changes.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

- **Unit tests:** None — doc-only chore, no Python or TypeScript code paths added.
- **Integration tests:** None.
- **Contract tests:** None.
- **E2E tests:** None.
- **Doc verification:** Implementation plan will include a manual `grep` check after each FR's edit (the same grep targets named in §12 AC-1 through AC-4 — "required substring present" / "forbidden substring absent"). No automated test harness is added; the verification is human-readable diff inspection plus the explicit grep checks.

Rationale: per CLAUDE.md "test completeness rule" — a feature must have tests at every layer it touches. This chore touches only the docs layer; the verification approach is grep-based diff inspection.

## 15) Documentation update requirements

- `docs/01_architecture/`: no updates required.
- `docs/02_product/`: this chore *is* the doc update. Specifically:
  - Update `docs/02_product/planned_features/chore_e2e_seed_acme_helper_dead/idea.md` (FR-1).
  - This chore's folder moves to `docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` post-merge (FR-5).
- `docs/03_runbooks/`: no updates required.
- `docs/04_security/`: no updates required.
- `docs/05_quality/`: no updates required.
- `ui/tests/e2e/helpers/coverage-audit.md`: updated by FRs 2–4. Lives under `ui/` not `docs/`, but is the audit doc for the E2E helper layer per `chore_e2e_test_rows_isolation` Story 1.2 §3.4.
- `state.md`: not updated by this chore's content commits. `state.md` updates are handled by the standard post-merge finalization step in [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7, which fires after FR-5's `git mv` lands on `main`. Listing `state.md` as a chore-scope deliverable here would double-count the finalization work and create spec-scope drift from the in-scope items in §3.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — doc-only chore ships across two PRs (see §3 Phase boundaries). PR A = content (FRs 1–4); PR B = finalization (FR-5).
- **Migration/backfill expectations:** N/A — no schema changes.
- **Operational readiness gates:** standard CI gate (`.github/workflows/pr.yml` — lint/format/typecheck/tests + frontend build) on both PRs. Neither PR touches Python or TypeScript, so the test layer should be a no-op pass on both.
- **Release gate (PR A):** green CI; Gemini Code Assist review adjudicated per CLAUDE.md "Cross-model review policy"; merge to main triggers PR B preparation.
- **Release gate (PR B):** green CI; PR A must be merged first (PR B's folder-move base is the post-A `main`); standard impl-execute Step 7 finalization commit included.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1 | Story 1.1 — Edit the `**Status:**` line at line 4 of `chore_e2e_seed_acme_helper_dead/idea.md` in place | grep verification only (doc-only) | `chore_e2e_seed_acme_helper_dead/idea.md` |
| FR-2 | AC-2 | Story 1.2 — Edit matrix row in `coverage-audit.md` | grep verification only | `ui/tests/e2e/helpers/coverage-audit.md` |
| FR-3 | AC-3 | Story 1.3 — Refresh `## Gaps` subsection | grep verification only | `ui/tests/e2e/helpers/coverage-audit.md` |
| FR-4 | AC-4 | Story 1.4 — Refresh `## Verdict` subsection | grep verification only | `ui/tests/e2e/helpers/coverage-audit.md` |
| FR-5 | AC-5 | Story 1.5 — Post-merge: `git mv` folder to `implemented_features/` + push finalization commit | n/a (post-merge) | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] AC-1 through AC-5 all pass per the grep-based verification.
- [ ] PR CI is green.
- [ ] Gemini Code Assist review comments (if any) are adjudicated using the four-quadrant rubric in [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) Step 6.
- [ ] PR is merged to `main`.
- [ ] Folder rename (FR-5) committed and pushed to `main`.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all decisions locked at idea-stage Recommendation (Option A) and re-confirmed during /idea-preflight (2026-05-25).

### Decision log

- **D-1 (2026-05-25):** Option A (one-paragraph status block + coverage-audit refresh) is the closure ceremony — not Option B (move to `implemented_features/` with `pipeline_status.md` shim). Rationale: from [`idea.md`](idea.md) Recommendation — "The original idea was correctly captured as a small chore; it just got OBE'd by adjacent work. A one-paragraph status update + a coverage-audit refresh is the right ceremony for that shape." Option B is more discoverability overhead than the chore's tiny scope warrants.
- **D-2 (2026-05-25):** The stale `seed.ts:378` line citation inside `chore_e2e_seed_acme_helper_dead/idea.md` (line 6) is **out of scope**. Rationale: lives in historical content of a file we're marking closed; the line drift is harmless (file is now archived), and patching it would inflate the diff with edits to historical body content (an explicit anti-pattern per §4).
- **D-3 (2026-05-25):** No `make dashboard` regen in this PR. Rationale: dashboard regen is a separate workflow (pre-commit hook + `make dashboard` target) that the operator drives on a cadence; coupling it to this chore would create unrelated diff churn. The next regen run after merge picks up the new `Status: Closed` automatically.
- **D-4 (2026-05-25):** Edit order is FR-1 → FR-2 → FR-3 → FR-4 (one story per FR, four content commits) followed by FR-5 (post-merge finalization). Rationale: each FR is independently grep-verifiable; small atomic commits make Gemini Code Assist's per-file diff review tractable and let any single FR be cleanly reverted if Gemini flags it.
- **D-5 (2026-05-25):** FR-1 updates the existing `**Status:**` line in place rather than prepending a new status block. Rationale: GPT-5.5 cross-model review cycle 1 (Pass B Medium finding) caught that the dashboard regen's `_extract_status_line` at [`scripts/build_mvp1_dashboard.py:213`](../../../../scripts/build_mvp1_dashboard.py#L213) uses `re.search` on the regex `^\*\*Status:\*\*\s*(.+)$`, which would return the FIRST match. A prepended `**Status (updated ...):**` variant doesn't match the regex (parenthesized text breaks the literal `**Status:**` prefix), so the old `Status: Idea` line would still win the dashboard parse. In-place edit is the only form that guarantees the closure is reflected in the next `make dashboard` regen.
- **D-6 (2026-05-25):** `state.md` is intentionally NOT a chore-scope doc-update item. Rationale: GPT-5.5 cross-model review cycle 1 (Pass B Low finding) caught the scope drift. `state.md` updates fire automatically via [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7 finalization after FR-5's folder move lands; listing it in §15 would double-count the work and conflict with §3's in-scope set.
