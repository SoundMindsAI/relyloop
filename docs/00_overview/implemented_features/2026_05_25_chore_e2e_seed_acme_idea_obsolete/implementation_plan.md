# Implementation Plan — chore_e2e_seed_acme_idea_obsolete

**Date:** 2026-05-25
**Status:** Complete (PR #250 merged 2026-05-25; PR B finalization in flight)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) — "Tangential discoveries" rubric, two-PR finalization pattern; [`impl-execute SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) — Step 7 finalization

---

## 0) Planning principles

- Spec traceability first: every story maps to exactly one FR.
- Doc-only chore: no backend, no frontend, no migrations, no tests beyond grep verification.
- Atomic per-FR commits — each story is independently reviewable and revertible.
- Two-PR rollout per [`feature_spec.md` §3 "Phase boundaries"](feature_spec.md): PR A ships Epic 1 (FRs 1–4); PR B ships Epic 2 (FR-5, post-merge finalization).
- Never bypass pre-commit hooks (CLAUDE.md absolute rule 7).

## 1) Scope traceability (FR → epics)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | In-place edit of `**Status:**` line at file line 4 of obsolete idea |
| FR-2 | Epic 1 / Story 1.2 | Replace `seedAcmeProductsChain` matrix-row callers cell at coverage-audit.md line 18 |
| FR-3 | Epic 1 / Story 1.3 | Refresh `## Gaps` subsection body (lines 22–32) |
| FR-4 | Epic 1 / Story 1.4 | Refresh `## Verdict` first sentence (lines 36–38) |
| FR-5 | Epic 2 / Story 2.1 | Post-merge `git mv` folder to `implemented_features/`; state.md update |

All five FRs from [`feature_spec.md` §7](feature_spec.md) are covered. No deferred phases — single phase, two-PR rollout shape (not a deferred-capability phase boundary). No `phase2_idea.md` needed.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** pattern, with the two epics scoped to the two PRs:

- **Epic 1 (PR A — Content):** Stories 1.1 through 1.4. Edits 2 files (`chore_e2e_seed_acme_helper_dead/idea.md` and `ui/tests/e2e/helpers/coverage-audit.md`). Ships against `feature/chore-e2e-seed-acme-idea-obsolete`.
- **Epic 2 (PR B — Finalization):** Story 2.1. Folder move + state.md recent-changes entry. Ships against `feature/finalize-chore-e2e-seed-acme-idea-obsolete` (branch created after PR A merges).

### Conventions

- All edits use the project's standard pre-commit hook stack (gitleaks secret scan, dashboard regen, prettier/eslint where applicable, conventional-commit validator). Never invoke `--no-verify` (CLAUDE.md absolute rule 7).
- Conventional Commits subject prefix: `docs(seed-acme-obsolete): …` for content commits; `docs: finalize chore_e2e_seed_acme_idea_obsolete after PR #<A>` for the finalization commit (matching the recent main pattern at `8cded4ae`).
- Every commit body includes the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

### AI Agent Execution Protocol (applies to every story)

0. **Load context first** (already done — this plan was generated with full context).
1. **Read scope** — verify the story's FR, target file, target line range, and DoD.
2. **Re-Read the target file** to confirm the line range hasn't shifted since spec authoring (no parallel PR has touched the same file). `git log -1 -- <path>` should show the same commit as when the spec was authored, or any newer commit must be inspected for line-range drift.
3. **Apply the edit** via the `Edit` tool. Match the exact `old_string`/`new_string` shape described in the story's Tasks.
4. **Verify** with the grep assertions in the DoD.
5. **Commit** atomically (one story = one commit, except where two stories edit the same file — see Story 1.3/1.4 note).
6. **Run the full unit test suite once at the end of Epic 1** as a sanity check (`make test-unit` from repo root) — expected: no impact, doc-only.

Story completion is invalid if any step is skipped.

---

## Epic 1 — Content PR (FRs 1–4)

### Story 1.1 — Update obsolete idea's Status line in place
**Outcome:** [`docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md`](../chore_e2e_seed_acme_helper_dead/idea.md) line 4 is rewritten from `**Status:** Idea — surfaced during \`chore_e2e_test_rows_isolation\` Story 1.2 coverage audit` to a closure marker satisfying [`feature_spec.md` AC-1](feature_spec.md) (three signal substrings: `Closed`, `2026-05-25`, `2cbcb93b`). [`feature_spec.md` FR-1](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md` | Replace exactly line 4. No other lines change. |

**Endpoints / Pydantic schemas / Key interfaces:** N/A (doc-only).

**Tasks**

1. Re-Read the file to confirm line 4 still has the original `**Status:** Idea — surfaced during \`chore_e2e_test_rows_isolation\` Story 1.2 coverage audit` content. If drifted, escalate.
2. `Edit` the file with `old_string = "**Status:** Idea — surfaced during \`chore_e2e_test_rows_isolation\` Story 1.2 coverage audit"` and `new_string = "**Status:** Closed (2026-05-25) — superseded by guide-06 spec wiring (commit \`2cbcb93b\`, 2026-05-22). Real caller: \`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts\`. No further action beyond the coverage-audit refresh that ships in the same PR."`.
3. Verify line 4 now contains all three required signal substrings via `grep -E '^\*\*Status:\*\*.*Closed.*2026-05-25.*2cbcb93b' docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md`.
4. Verify `## Problem` (originally at line 9) has not shifted: `grep -n '^## Problem' docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md` should return `9:## Problem`.
5. Verify dashboard parser picks up the new line: `python3 -c "import sys; sys.path.insert(0, 'scripts'); from build_mvp1_dashboard import _extract_status_line; print(_extract_status_line(open('docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md').read()))"` must return a string starting with `Closed`.
6. Commit: `docs(seed-acme-obsolete): close chore_e2e_seed_acme_helper_dead per Option A (FR-1)`.

**Definition of Done**

- File line 4 satisfies the grep in task 3 (literal `^**Status:** … Closed … 2026-05-25 … 2cbcb93b …`).
- File line 9 still reads `## Problem` (no body shift).
- `_extract_status_line` returns a value starting with `Closed` (task 5 verification).
- `git diff --stat HEAD~1 -- docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md` shows exactly 1 file, 1 insertion, 1 deletion.
- File still ends with a single trailing newline (POSIX convention; required by FR-1): `tail -c1 docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md | od -c | head -1` returns `\n`.
- Pre-commit hooks pass (no `--no-verify`).

---

### Story 1.2 — Refresh seedAcmeProductsChain matrix-row callers cell
**Outcome:** [`ui/tests/e2e/helpers/coverage-audit.md`](../../../../ui/tests/e2e/helpers/coverage-audit.md) line 18 names the real caller spec basename `06_create_and_monitor_study.spec.ts` and no longer contains the strings `0 specs` or `currently uncalled`. [`feature_spec.md` FR-2 / AC-2](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/helpers/coverage-audit.md` | Replace line 18's callers cell text only. `Helper` cell and `Registers` cell unchanged. |

**Tasks**

1. Re-Read the file to confirm line 18 still has the original `seedAcmeProductsChain` row with `**0 specs** — currently uncalled (see "Gaps" below)`.
2. `Edit` with `old_string = "| \`seedAcmeProductsChain\` | **0 specs** — currently uncalled (see \"Gaps\" below) | \`cluster\`, \`query_set\`, \`query_template\`, \`judgment_list\`, \`study\` |"` and `new_string = "| \`seedAcmeProductsChain\` | \`guides/06_create_and_monitor_study.spec.ts\` | \`cluster\`, \`query_set\`, \`query_template\`, \`judgment_list\`, \`study\` |"`.
3. Verify the row contains `06_create_and_monitor_study.spec.ts` AND does NOT contain any of the three forbidden substrings from spec AC-2:
   - `grep -E 'seedAcmeProductsChain.*06_create_and_monitor_study\.spec\.ts' ui/tests/e2e/helpers/coverage-audit.md` returns the row.
   - `grep '0 specs' ui/tests/e2e/helpers/coverage-audit.md` returns nothing.
   - `grep 'currently uncalled' ui/tests/e2e/helpers/coverage-audit.md` returns nothing.
   - `grep 'see "Gaps" below' ui/tests/e2e/helpers/coverage-audit.md` returns nothing.
4. Verify the matrix row count remains 9 (header counts not included): `awk '/^\| \`seed/{c++} END{print c}' ui/tests/e2e/helpers/coverage-audit.md` must return `9`.
5. Commit: `docs(seed-acme-obsolete): refresh coverage-audit matrix row for seedAcmeProductsChain (FR-2)`.

**Definition of Done**

- Grep assertions in tasks 3–4 pass.
- Matrix structure (9 rows) preserved.
- Pre-commit hooks pass.

---

### Story 1.3 — Refresh `## Gaps` subsection to no-gap state
**Outcome:** The `## Gaps` header at line 22 of `coverage-audit.md` is preserved; the body (currently lines 24–32) is replaced with a two-sentence "no remaining gap" acknowledgement. [`feature_spec.md` FR-3 / AC-3](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/helpers/coverage-audit.md` | Replace lines 24–32 (the `## Gaps` body). Header at line 22 stays. |

**Tasks**

1. Re-Read the file (already done by Story 1.2; confirm line 22 is still `## Gaps` and the body still describes the helper as having no caller).
2. `Edit` with `old_string` matching the exact 9-line block from `\`seedAcmeProductsChain\` has no spec caller. The helper itself is correctly` (line 24) through `The follow-up will either delete the helper or wire a spec that uses it.` (line 32), and `new_string = "None as of 2026-05-25 — see commit \`2cbcb93b\` for the helper's first real caller wiring. The cleanup-registry pipeline remains correctly instrumented for every helper in the §2 inventory."`.
3. Verify `## Gaps` header still present: `grep -n '^## Gaps' ui/tests/e2e/helpers/coverage-audit.md` returns one line.
4. Verify forbidden substring absent: `grep 'no spec caller' ui/tests/e2e/helpers/coverage-audit.md` returns nothing.
5. Verify required substring present: `grep 'None as of 2026-05-25' ui/tests/e2e/helpers/coverage-audit.md` returns the line.
6. Commit: `docs(seed-acme-obsolete): refresh coverage-audit ## Gaps subsection (FR-3)`.

**Definition of Done**

- Grep assertions in tasks 3–5 pass.
- `## Gaps` header retained.
- Body length compressed from ~9 lines to 2 sentences.
- Pre-commit hooks pass.

---

### Story 1.4 — Refresh `## Verdict` to 9-of-9
**Outcome:** First sentence of `## Verdict` subsection (currently spans lines 36–38) is rewritten to `9 of 9 helpers in the spec §2 inventory are covered by at least one existing Playwright spec.`. Second sentence about the cleanup registry remains unchanged. [`feature_spec.md` FR-4 / AC-4](feature_spec.md).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/helpers/coverage-audit.md` | Replace the `8 of 9 …` sentence (lines 36–38) with the `9 of 9 …` sentence. Cleanup-registry sentence (lines 38–39) preserved. |

**Tasks**

1. Re-Read the file (line ranges may have shifted by ~7 lines due to Story 1.3's compression — `awk '/## Verdict/{print NR; exit}' ui/tests/e2e/helpers/coverage-audit.md` will give the post-Story-1.3 line for the Verdict header; re-locate the "8 of 9" sentence accordingly).
2. `Edit` with `old_string = "8 of 9 helpers in the spec §2 inventory are covered by at least one\nexisting Playwright spec; the 9th (\`seedAcmeProductsChain\`) is dead code,\ncaptured as a separate idea file."` and `new_string = "9 of 9 helpers in the spec §2 inventory are covered by at least one\nexisting Playwright spec."`.
3. Verify required substring present: `grep '9 of 9 helpers' ui/tests/e2e/helpers/coverage-audit.md` returns the line.
4. Verify forbidden substrings absent: `grep '8 of 9' ui/tests/e2e/helpers/coverage-audit.md` returns nothing; `grep 'dead code' ui/tests/e2e/helpers/coverage-audit.md` returns nothing.
5. Verify cleanup-registry sentence preserved: `grep 'cleanup registry will be exercised' ui/tests/e2e/helpers/coverage-audit.md` returns the original line.
6. Commit: `docs(seed-acme-obsolete): refresh coverage-audit ## Verdict to 9-of-9 (FR-4)`.

**Definition of Done**

- Grep assertions in tasks 3–5 pass.
- `## Verdict` header retained.
- Cleanup-registry sentence preserved verbatim.
- Pre-commit hooks pass.

---

### Epic 1 phase gate

Before opening PR A:

1. Re-run `make test-unit` from repo root — expected: green (doc-only changes, no Python paths touched).
2. Re-run `cd ui && pnpm typecheck && pnpm lint` — expected: green (no TS changes).
3. `git log --oneline origin/main..HEAD` — expected: 6 commits (spec commit + plan commit + 4 story commits).
4. Run [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 6's pre-push gate per the standard ad-hoc/full pipeline pattern (cumulative diff Gemini-via-GPT-5.5 phase-gate review against the cumulative Epic 1 diff). For a doc-only chore this should produce zero High-severity findings; any findings get adjudicated per CLAUDE.md "Cross-model review policy" four-quadrant rubric.
5. Push the branch (`git push -u origin feature/chore-e2e-seed-acme-idea-obsolete`) and open PR A via `gh pr create`.

---

## Epic 2 — Finalization PR (FR-5)

### Story 2.1 — Move chore folder to implemented_features (post-merge)
**Outcome:** After PR A merges to `main`, the chore folder is renamed under `implemented_features/` per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 7 finalization. `state.md` gets a recent-changes entry naming PR A's number. [`feature_spec.md` FR-5 / AC-5](feature_spec.md).

**Trigger:** PR A has been merged to `main`. The local main branch has been synced (`git fetch origin main && git rebase origin/main` or equivalent).

**New files:** None.

**Modified files**

| File | Change |
|---|---|
| `docs/00_overview/planned_features/chore_e2e_seed_acme_idea_obsolete/*` | Move (via `git mv`) the entire folder to `docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/`. |
| `state.md` | Append a recent-changes entry: `<PR-A-number> chore(seed-acme-obsolete): close OBE'd chore_e2e_seed_acme_helper_dead per Option A — coverage-audit refreshed to 9-of-9 (PR A merged; this finalize PR moves the folder under implemented_features/).` Note: PR B's own number is NOT included in the entry because PR B is not yet open at commit time. |

**Tasks**

1. From the main worktree (`/Users/ericstarr/relyloop`), sync main: `git fetch origin main && git checkout main && git pull --ff-only origin main`.
2. Create the finalization branch: `git checkout -b feature/finalize-chore-e2e-seed-acme-idea-obsolete`.
3. `git mv docs/00_overview/planned_features/chore_e2e_seed_acme_idea_obsolete docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete`.
4. Update `state.md` per the row in "Modified files" above. Insert at the top of the most recent recent-changes block.
5. `git add -A && git status -s` — expected: at least 4 files renamed (`idea.md`, `feature_spec.md`, `implementation_plan.md`, `pipeline_status.md` per spec AC-5's minimum) plus any other peer files the directory has accumulated by then (e.g., if subsequent stories added supplementary docs); plus 1 file modified (`state.md`). Verify the count matches `git status -s | wc -l`.
6. Commit: `docs: finalize chore_e2e_seed_acme_idea_obsolete after PR #<PR-A-number>` (matching the canonical finalization-commit subject pattern at recent main e.g. `8cded4ae docs: finalize feat_study_clone_narrow_bounds after PR #247 (#248)`).
7. Push and open PR B: `gh pr create --title "docs: finalize chore_e2e_seed_acme_idea_obsolete after PR #<PR-A-number>" --body …`.

**Definition of Done**

- `docs/00_overview/implemented_features/2026_05_25_chore_e2e_seed_acme_idea_obsolete/` exists on the finalize branch.
- `docs/00_overview/planned_features/chore_e2e_seed_acme_idea_obsolete/` does NOT exist on the finalize branch.
- `state.md` recent-changes entry references PR A's number.
- PR B is open, CI is green, and merge to main completes the chore.
- Both worktrees can be cleaned up after PR B merge per [`impl-execute` SKILL.md](../../../../.claude/skills/impl-execute/SKILL.md) Step 9.3 worktree cleanup.

---

## 3) Test workstream

This chore touches no Python or TypeScript code paths. Per [`feature_spec.md` §14](feature_spec.md):

| Test layer | Story | File | Status |
|---|---|---|---|
| Unit (backend) | — | — | N/A — no Python touched |
| Integration (backend) | — | — | N/A — no Python touched |
| Contract (backend) | — | — | N/A — no API surface |
| E2E (frontend) | — | — | N/A — no UI touched |
| **Doc verification** | 1.1–1.4 | grep assertions in each story's DoD | Embedded in story Tasks |

The existing `make test-unit` / `pnpm typecheck` / `pnpm lint` invocations in the Epic 1 phase gate exist as regression-prevention sanity checks against accidental file-scope creep — not because the chore adds testable code paths.

No new test files. No orphaned test files. Coverage gate (80% Python per CLAUDE.md) is unaffected.

## 4) Documentation update workstream

| Doc | Scope | Story |
|---|---|---|
| `docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md` | Status line update (FR-1) | 1.1 |
| `ui/tests/e2e/helpers/coverage-audit.md` | Matrix row + Gaps + Verdict (FRs 2–4) | 1.2, 1.3, 1.4 |
| `state.md` | Recent-changes entry (post-merge) | 2.1 |
| Folder move | `planned_features/` → `implemented_features/` | 2.1 |
**Not chore-authored content (downstream-of-pre-commit):** The `mvp1-dashboard-regen` pre-commit hook automatically refreshes `docs/00_overview/MVP1_DASHBOARD.md`, `mvp1_dashboard.html`, `DASHBOARD.md`, and `dashboard.html` on every commit that touches a feature folder's `Status:` metadata. These regenerated artifacts WILL appear in PR A's diff (this is unavoidable given CLAUDE.md absolute rule 7 forbids `--no-verify`) but they are NOT chore-authored deliverables — per [`feature_spec.md` §3 Out of scope](feature_spec.md) and D-3 the chore's deliverable is the 4 doc edits + folder move. No story calls `make dashboard` manually.

`architecture.md` and `CLAUDE.md` not updated — the chore introduces no new conventions, rules, services, layers, env vars, or build commands.

## 5) Plan consistency review

| Check | Method | Result |
|---|---|---|
| Every spec FR has a story | Spec §17 lists FR-1..FR-5; this plan §1 lists Stories 1.1, 1.2, 1.3, 1.4, 2.1 mapping to the same FRs | ✓ Match |
| Every spec endpoint has a story | Spec §8: 0 endpoints | ✓ N/A |
| Every spec error code is tested | Spec §8.5: 0 error codes | ✓ N/A |
| Every modified file actually exists | `docs/00_overview/planned_features/01_mvp1/chore_e2e_seed_acme_helper_dead/idea.md` ✓; `ui/tests/e2e/helpers/coverage-audit.md` ✓; `state.md` ✓ | ✓ |
| Every story's DoD has a verification gate | All 5 stories have explicit grep / functional / state assertions in their DoD | ✓ |
| Phase gate arithmetic | Epic 1 gate references "6 commits" (1 spec + 1 plan + 4 stories); Epic 2 gate references "5 files renamed + 1 modified" | Recounted: ✓ |
| Open questions resolved | Spec §19 lists 0 open questions; all 6 decisions logged | ✓ |
| Frontend UI Guidance | N/A — no story has frontend scope | ✓ skip |
| Audit-event coverage | N/A — pre-MVP2; spec §6 marks audit_log as N/A | ✓ skip |
| Enumerated value contracts | N/A — no `<select>` / filter / badge / sort surface | ✓ skip |
| Deferred phase tracking | Spec §3 explicitly notes "single phase, two-PR rollout — not a deferred-capability phase boundary" | ✓ no `phase2_idea.md` needed |

## 6) Sequencing and risk

- **Story ordering:** 1.1 → 1.2 → 1.3 → 1.4 within Epic 1. The order matters only between 1.3 and 1.4 because 1.3 compresses lines 24–32 (~9 lines → 2 sentences), causing the `## Verdict` header to shift up by ~7 lines. Story 1.4 explicitly re-locates the Verdict section post-1.3 via `awk` (see Task 1).
- **Cross-story file overlap:** Stories 1.2, 1.3, 1.4 all edit `coverage-audit.md` but at disjoint line ranges (row 18 / Gaps body / Verdict first sentence). Sequential `Edit` calls with re-Read between each story is sufficient — no merge conflicts possible since stories run on a single branch in sequence.
- **PR-A → PR-B dependency:** Epic 2 cannot start until PR A merges to main. Epic 2's branch (`feature/finalize-chore-e2e-seed-acme-idea-obsolete`) is created off the post-A `main`, not off the Epic 1 branch.
- **Risk: parallel edits to target files.** Mitigated by Task 1 in each story re-Reading the file and verifying the expected `old_string` is still present. If a parallel PR (e.g., another contributor or another agent) has touched the same line range, the `Edit` will error and the chore will escalate.
- **Risk: pre-commit hook regenerating MVP1_DASHBOARD.md after Story 1.1.** Expected behavior — the hook regenerates the dashboard whenever a feature folder's `Status:` line changes. The regen output should reflect `chore_e2e_seed_acme_helper_dead` moving out of the Idea (16) table. Each story's `git add` after the hook's auto-modification is handled by the standard re-stage pattern (see this branch's commit `27e597dd` for an example of the same pattern playing out on the spec commit).

## 7) Execution tracker

| Story | Status | Commit SHA |
|---|---|---|
| 1.1 — Close obsolete idea Status line | [x] | `69e89d8a` (post-rebase; orig `66d6ab75`) |
| 1.2 — Refresh matrix row | [x] | `9d36c2a5` (post-rebase; orig `10a4337a`) |
| 1.3 — Refresh ## Gaps body | [x] | `c4875efd` (post-rebase; orig `daf0ce86`) |
| 1.4 — Refresh ## Verdict | [x] | `1b7d1f53` (post-rebase; orig `b0a54fab`) |
| Epic 1 phase gate | [x] | 0 GPT-5.5 findings; 1427 unit tests passing; pnpm typecheck/lint clean |
| **PR A** | [x] | [#250](https://github.com/SoundMindsAI/relyloop/pull/250) merged 2026-05-25T20:47:32Z as squash `05f3d486` |
| 2.1 — git mv + state.md update | [x] | this finalization commit |
| **PR B** | [ ] | in flight |

## 8) Open questions

None. All decisions locked in [`feature_spec.md` §19](feature_spec.md) D-1 through D-6.
