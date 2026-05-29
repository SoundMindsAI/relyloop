# Implementation Plan — Drop `push: branches: [main]` trigger from `pr.yml`

**Date:** 2026-05-28
**Status:** Ready for Execution
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md), [docs/01_architecture/tech-stack.md](../../../01_architecture/tech-stack.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Workflow YAML changes ship with their cross-cutting doc edits (CLAUDE.md note, release-checklist queries) in the same PR — separating them creates a window where the runbook is stale.
- Validation is observational (gh CLI commands run by the reviewer). No new test code.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 (trigger surface) | Epic 1 / Phase 1 → Story 1.1 | Delete `push:` block; preserve `pull_request:` block byte-identically. |
| FR-2 (comment hygiene) | Epic 1 / Phase 1 → Story 1.1 | Top-of-file rationale + the "Keep this list synchronized" comment. |
| FR-3 (runbook patch) | Epic 1 / Phase 1 → Story 1.2 | release-checklist.md §2 + §3 query rewrites. |
| FR-4 (no collateral changes) | Epic 1 / Phase 1 → Story 1.1 (negative DoD assertions) | Concurrency, permissions, paths-ignore, job definitions all untouched. |
| §10 merge-skew mitigation | Epic 1 / Phase 1 → Story 1.2 | CLAUDE.md one-sentence addition near line 7. |

All FRs covered by this plan. **No deferred phases** — spec is single-phase (per spec §3 "Phase boundaries"). No `phase2_idea.md` needed.

## 2) Delivery structure

**Delivery shape:** Single Epic → 2 Stories → no internal phase gates.

This feature is intentionally narrow:

- Story 1.1 — Workflow edit (`.github/workflows/pr.yml`).
- Story 1.2 — Doc/runbook edits (`docs/03_runbooks/release-checklist.md` + `CLAUDE.md`).

Stories execute sequentially. Story 1.1 ships the behavior change; Story 1.2 ships the cross-cutting doc updates that depend on the new behavior being live. Stories ship in the same PR / commit series — separating them creates a window where the runbook would query for runs that no longer exist.

### Conventions (project-specific)

- Workflow YAML — match existing indent (2-space) and key ordering in `pr.yml`. Do not reformat surrounding YAML.
- Markdown — match existing heading levels (`##` for section 2/3 in release-checklist.md) and code-block language hints (`bash` for shell snippets).
- CLAUDE.md — preserve the existing prose style (sentence rules, no bullet lists in the early "directly-to-main" section). New text matches the §1 voice that already exists at CLAUDE.md:5–7.

### AI Agent Execution Protocol

0. **Load context first**: Read `CLAUDE.md`, `architecture.md`, `state.md`, and the spec at [`feature_spec.md`](feature_spec.md) before starting Story 1.1.
1. **Read scope**: verify each story's New/Modified file list + DoD against the spec.
2. **Story 1.1**: Edit `.github/workflows/pr.yml` per Story 1.1 task list.
3. **Verify Story 1.1**: run the post-edit diff sanity checks listed in Story 1.1 DoD before moving on.
4. **Story 1.2**: Edit `docs/03_runbooks/release-checklist.md` §2 + §3 and `CLAUDE.md` per Story 1.2 task list.
5. **Pre-push verification**: run the doc-content sanity checks in Story 1.2 DoD (grep for forbidden phrases, verify code blocks are syntactically clean).
6. **Push + PR**: standard `impl-execute` push + Gemini watch + GPT-5.5 final review.

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Trigger surface narrowing + cross-cutting doc updates

### Story 1.1 — Drop `push: branches: [main]` from `pr.yml`

**Outcome:** `pr.yml` triggers only on `pull_request` events targeting `main`. Post-merge runs to `main` no longer fire. Top-of-file rationale comment reflects the new behavior.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) | Lines 29–36: delete entire `push:` block. Line 22: delete the `# Keep this list synchronized with the \`push\` trigger below.` comment. Lines 3–4: update rationale to drop "+ every push to main." (See "Exact diff" below for precise wording.) |

**Exact diff target** (verified by `cat -n .github/workflows/pr.yml` 2026-05-28):

Before (lines 3–4):
```yaml
# infra_foundation Story 5.1 / FR-4.
# Runs on every PR to main + every push to main.
```

After:
```yaml
# infra_foundation Story 5.1 / FR-4.
# Runs on every PR to main.
```

Before (lines 16–36 — the full `on:` block):
```yaml
on:
  pull_request:
    branches: [main]
    # Docs-only changes don't need backend tests / frontend build /
    # smoke / docker buildx. A PR that touches BOTH docs and code
    # still runs the full workflow (any non-ignored path matches).
    # Keep this list synchronized with the `push` trigger below.
    paths-ignore:
      - 'docs/**'
      - '*.md'
      - '.gitignore'
      - 'LICENSE'
      - 'release-notes-*.md'
  push:
    branches: [main]
    paths-ignore:
      - 'docs/**'
      - '*.md'
      - '.gitignore'
      - 'LICENSE'
      - 'release-notes-*.md'
```

After (becomes lines 16–28):
```yaml
on:
  pull_request:
    branches: [main]
    # Docs-only changes don't need backend tests / frontend build /
    # smoke / docker buildx. A PR that touches BOTH docs and code
    # still runs the full workflow (any non-ignored path matches).
    paths-ignore:
      - 'docs/**'
      - '*.md'
      - '.gitignore'
      - 'LICENSE'
      - 'release-notes-*.md'
```

**Endpoints**

N/A — no API changes.

**Key interfaces**

N/A — no code changes.

**Pydantic schemas**

N/A.

**UI element inventory**

N/A — no UI changes.

**State dependency analysis**

N/A — no state involved.

**Tasks**

1. Open [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml).
2. Apply the "Exact diff target" edits above:
   - Update line 4 rationale comment.
   - Delete the `# Keep this list synchronized with the \`push\` trigger below.` comment (currently line 22).
   - Delete the entire `push:` block (currently lines 29–36).
3. Verify file is still valid YAML: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pr.yml'))"` exits 0.
4. Verify no other `pr.yml` content was touched: `git diff .github/workflows/pr.yml` shows only the 3 targeted edits.
5. Verify byte-for-byte preservation of the `pull_request:` `paths-ignore` block (lines 23–28 pre-edit): `git diff .github/workflows/pr.yml | grep -E "^-\s+- 'docs/\*\*'|^-\s+- '\*\.md'|^-\s+- '\.gitignore'|^-\s+- 'LICENSE'|^-\s+- 'release-notes-\*\.md'"` shows ONLY the 5 deletions under the deleted `push:` block (i.e., 5 lines, not 10) — confirms the `pull_request:` block's `paths-ignore` lines were not deleted.

**Definition of Done (DoD)**

- [ ] FR-1 — `pr.yml`'s `on:` block contains exactly one trigger (`pull_request`). Verified by `grep -cE "^  (pull_request|push):$" .github/workflows/pr.yml` returning `1`. (The 2-space-indent + colon-end anchors are required — a looser `^\s*(pull_request|push):` regex also matches `push: false` inside docker buildx steps, producing a false positive count.)
- [ ] FR-1 — The `pull_request.paths-ignore` block is byte-identical to the pre-edit version (5 paths in the same order). Verified by inspecting `git diff .github/workflows/pr.yml` and confirming no lines inside the `pull_request:` block were modified or deleted.
- [ ] FR-2 — Line 4 reads `# Runs on every PR to main.` (no "+ every push to main"). Verified by `grep -F "# Runs on every PR to main." .github/workflows/pr.yml` returning 1 match AND `grep -cF "push to main" .github/workflows/pr.yml` returning `0`.
- [ ] FR-2 — The `# Keep this list synchronized` comment is removed. Verified by `grep -cF "Keep this list synchronized" .github/workflows/pr.yml` returning `0`.
- [ ] FR-4 — Concurrency block untouched. Verified by `grep -A 3 "^concurrency:" .github/workflows/pr.yml` showing the exact pre-edit content (`group: ${{ github.workflow }}-${{ github.ref }}` + `cancel-in-progress: true`).
- [ ] FR-4 — All 6 jobs still present. Verified by `grep -cE "^  (backend-unit-fast|backend|frontend|smoke-test|docker|docker-ui):$" .github/workflows/pr.yml` returning `6` (the YAML job-key declarations, not display names — `^  <key>:$` matches a 2-space-indented top-level job key with nothing else on the line, which the `smoke-logs:` artifact at line 553 cannot accidentally match because it's nested deeper under `with:`).
- [ ] FR-4 — Job definitions untouched (no step changes). Verified by inspecting `git diff -- .github/workflows/pr.yml` and confirming the ONLY diff hunks are: (a) line 4 comment update, (b) line 22 sync-comment deletion, (c) lines 29–36 `push:` block deletion. No other hunks.
- [ ] FR-4 — Sibling workflows (`dco.yml`, `secrets-defense.yml`) unchanged. Verified by `git diff .github/workflows/dco.yml .github/workflows/secrets-defense.yml` being empty.
- [ ] AC-1 will fire on PR creation: this PR's own `pr.yml` run starts when the PR is pushed (observed live during `impl-execute` Step 4 push).

---

### Story 1.2 — Patch `release-checklist.md` queries + add `CLAUDE.md` merge-skew note

**Outcome:** [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) §2 and §3 query commands return non-empty results after the Story 1.1 change lands. [`CLAUDE.md`](../../../../CLAUDE.md) documents the merge-skew mitigation as a one-sentence operator-facing convention.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) | §2 (lines 23–36 pre-edit): replace the `gh run list --workflow=pr.yml --branch=main` query block with the merged-PR-driven 2-step query from feature_spec.md FR-3. §3 (lines 38–51 pre-edit): replace the `gh run list --workflow=pr.yml --commit="$MERGE_SHA"` query block with the mergedAt-sorted lookup from feature_spec.md FR-3. Add a one-sentence operator note clarifying that docs-only PRs are skipped (by `paths-ignore` design) for both gates. |
| [`CLAUDE.md`](../../../../CLAUDE.md) | After line 7 ("After creating or pushing to a PR, monitor the CI workflow..."), insert one sentence: *"Before merging any non-docs PR, verify the latest successful `pr.yml` run was produced against the current `main`. If `main` advanced after the last successful run, click \"Update branch\" on the PR (or rebase locally) to re-trigger CI before merging — this guards against merge-skew (PR head was validated against an older base) until branch protection becomes available post-public-launch."* |

**Exact target text — release-checklist.md §2 replacement**

Before (lines 23–36 of `docs/03_runbooks/release-checklist.md` per direct read 2026-05-28; outer ````markdown fence is 4 backticks so inner ```bash renders literally):

````markdown
## 2. Smoke reliability gate (≥5 consecutive green smoke runs on main)

Per spec §13 NFR. The smoke job has a 15-minute budget; flake rate must be
zero across 5 consecutive runs before the tag goes out.

```bash
gh run list --workflow=pr.yml --branch=main --limit=20 \
  --json conclusion,name,headSha \
  | jq '[.[] | select(.name | startswith("smoke"))] | .[0:5] | map(.conclusion) | all(. == "success")'
# Expected: true
```

If the answer is `false`, identify the failing run, read its `smoke-logs`
artifact, fix or quarantine the cause, and re-run until 5-in-a-row green.
````

After (replacement block; outer ````markdown fence is 4 backticks):

````markdown
## 2. Smoke reliability gate (≥5 consecutive green smoke runs across merged PRs)

Per spec §13 NFR. The smoke job has a 15-minute budget; flake rate must be
zero across the 5 most recently merged PRs before the tag goes out.

`pr.yml` runs only on `pull_request` events (not on `push: main` —
see [`infra_pr_yml_drop_push_main_trigger`](../00_overview/implemented_features/<DATE>_infra_pr_yml_drop_push_main_trigger/idea.md)),
so the gate is computed from the most recently merged PRs' per-job smoke
conclusions rather than from push-event workflow conclusions.

```bash
# 1. Get up to 30 most recently merged PRs targeting main (oversample to
#    handle docs-only PRs that pr.yml skipped via paths-ignore).
gh pr list --state=merged --base=main --limit=30 \
  --json number,headRefOid,mergedAt \
  --jq 'sort_by(.mergedAt) | reverse | .[] | [.number, .headRefOid] | @tsv' \
  > /tmp/merged_prs
# 2. Walk PRs newest-first until we've evaluated 5 with a real pr.yml run.
#    Docs-only PRs (no completed pr.yml run) are skipped without counting.
CHECKED=0
SUCCESS_COUNT=0
while IFS=$'\t' read -r pr_num head_sha; do
  [ "$CHECKED" -ge 5 ] && break
  RUN_ID=$(gh run list --workflow=pr.yml --event=pull_request \
             --commit="$head_sha" --status=completed \
             --json databaseId,createdAt \
             --jq 'sort_by(.createdAt) | reverse | .[0].databaseId')
  if [ -z "$RUN_ID" ]; then
    echo "PR #$pr_num: skipped (docs-only or no completed pr.yml run)"
    continue
  fi
  CONCL=$(gh run view "$RUN_ID" --json jobs \
            --jq '.jobs[] | select(.name | test("smoke"; "i")) | .conclusion')
  echo "PR #$pr_num smoke: $CONCL"
  CHECKED=$((CHECKED + 1))
  [ "$CONCL" = "success" ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
done < /tmp/merged_prs
if [ "$CHECKED" -lt 5 ]; then
  echo "GATE INCONCLUSIVE: only $CHECKED code-bearing PRs found in last 30 merges"
elif [ "$SUCCESS_COUNT" -eq 5 ]; then
  echo "GATE PASSED"
else
  echo "GATE FAILED ($SUCCESS_COUNT/5)"
fi
```

If the gate fails, identify the failing PR's run, read its `smoke-logs`
artifact, fix or quarantine the cause, land the fix on `main`, and re-run.
Docs-only merged PRs are filtered out of `pr.yml` by `paths-ignore` (by
design) and the loop walks past them without counting them as failures.
````

**Exact target text — release-checklist.md §3 replacement**

Before (lines 38–51 of `docs/03_runbooks/release-checklist.md`):

````markdown
## 3. 80% coverage gate verification (AC-3)

The coverage gate already lives in `pyproject.toml`
(`[tool.coverage.report].fail_under = 80`). Verify it actually fired on the
merge commit:

```bash
MERGE_SHA=$(git rev-parse main)
RUN_ID=$(gh run list --workflow=pr.yml --commit="$MERGE_SHA" \
           --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --log | grep -E "TOTAL|fail_under" | tail
```

Expected: a `TOTAL` line ≥ 80% and no `fail_under` error.
````

After:

````markdown
## 3. 80% coverage gate verification (AC-3)

The coverage gate already lives in `pyproject.toml`
(`[tool.coverage.report].fail_under = 80`). After
[`infra_pr_yml_drop_push_main_trigger`](../00_overview/implemented_features/<DATE>_infra_pr_yml_drop_push_main_trigger/idea.md)
the merge SHA on `main` is never validated directly; instead, the coverage
gate fires on the most recently merged non-docs-only PR's head SHA. Verify
it actually fired:

```bash
# Iterate merged PRs newest-first; pick the first that has a pr.yml run.
HEAD_SHA=$(gh pr list --state=merged --base=main --limit=20 \
             --json headRefOid,mergedAt \
             --jq 'sort_by(.mergedAt) | reverse | .[].headRefOid' \
           | while read sha; do
               id=$(gh run list --workflow=pr.yml --event=pull_request \
                      --commit="$sha" --status=completed \
                      --json databaseId --jq '.[0].databaseId')
               [ -n "$id" ] && { echo "$sha"; break; }
             done)
RUN_ID=$(gh run list --workflow=pr.yml --event=pull_request --commit="$HEAD_SHA" \
           --json databaseId --jq '.[0].databaseId')
gh run view "$RUN_ID" --log | grep -E "TOTAL|fail_under" | tail
```

Expected: a `TOTAL` line ≥ 80% and no `fail_under` error.

Note: docs-only merged PRs are skipped (filtered out of `pr.yml` by
`paths-ignore`, by design); the loop's inner `while read` automatically
walks past them to find the most recent code-bearing PR.
````

**Exact target text — CLAUDE.md insertion**

Before (lines 5–8 of `CLAUDE.md` per direct read 2026-05-28):
```markdown
**Never commit directly to main.** Always create a feature branch, push it, and open a PR. CI runs on PRs to main — merging to main triggers staging deploy (when staging exists; MVP1 has no remote staging — local-only).

**After creating or pushing to a PR,** monitor the CI workflow. Use `gh run list --branch={BRANCH}` to find the run, then `gh run watch {RUN_ID}` to monitor. If CI fails, investigate and fix before moving on.
```

After:
```markdown
**Never commit directly to main.** Always create a feature branch, push it, and open a PR. CI runs on PRs to main — merging to main triggers staging deploy (when staging exists; MVP1 has no remote staging — local-only).

**After creating or pushing to a PR,** monitor the CI workflow. Use `gh run list --branch={BRANCH}` to find the run, then `gh run watch {RUN_ID}` to monitor. If CI fails, investigate and fix before moving on.

**Before merging any non-docs PR,** verify the latest successful `pr.yml` run was produced against the current `main`. If `main` advanced after the last successful run, click "Update branch" on the PR (or rebase locally) to re-trigger CI before merging — this guards against merge-skew (the PR head was validated against an older base) until branch protection becomes available post-public-launch.
```

**Endpoints / Key interfaces / Schemas / UI / State**

N/A — doc-only story.

**Tasks**

1. Open [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md).
2. Replace §2 (lines 23–36 pre-edit) with the "After" block above. Preserve the cross-reference path to the implemented_features folder — at execution time, fill `<DATE>` with today's `YYYY_MM_DD` (the same date the parent feature folder will be moved to under `implemented_features/`).
3. Replace §3 (lines 38–51 pre-edit) with the "After" block above. Same `<DATE>` substitution applies.
4. Open [`CLAUDE.md`](../../../../CLAUDE.md).
5. Insert the new paragraph after the existing "After creating or pushing to a PR" paragraph (current line 7). Preserve a blank line before and after the new paragraph.
6. Verify markdown integrity: run `grep -nE "^##|^###" docs/03_runbooks/release-checklist.md` to confirm heading order is unchanged (no new `##` levels introduced); confirm code blocks open + close correctly via `awk '/^\`\`\`/{n++} END{exit n%2}' docs/03_runbooks/release-checklist.md` (must exit 0 = even count of fences).
7. Verify CLAUDE.md voice consistency by reading the new paragraph aloud — it should sound continuous with lines 5 + 7 (no list bullets, no markdown headers, matches existing sentence shape).

**Definition of Done (DoD)**

- [ ] FR-3 — §2 block contains the new `gh pr list --state=merged --base=main` + `gh run view ... --jq '.jobs[]'` two-step pattern. Verified by `grep -F 'sort_by(.mergedAt)' docs/03_runbooks/release-checklist.md` returning 2 matches (§2 and §3 both use this sort).
- [ ] FR-3 — §3 block contains the new `mergedAt`-sorted lookup + docs-only-skip note. Verified by `grep -F 'while read sha' docs/03_runbooks/release-checklist.md` returning 1 match.
- [ ] FR-3 — Old query patterns removed. Verified by `grep -cF -- '--branch=main --limit=20' docs/03_runbooks/release-checklist.md` returning `0` AND `grep -cF -- '--commit="$MERGE_SHA"' docs/03_runbooks/release-checklist.md` returning `0`. (The `--` terminator is required because the patterns start with `--`; without it, grep parses them as flags and errors out before checking the file.)
- [ ] §10 merge-skew — `CLAUDE.md` contains the "Before merging any non-docs PR" paragraph. Verified by `grep -F 'Before merging any non-docs PR' CLAUDE.md` returning 1 match.
- [ ] §10 merge-skew — paragraph positioned after the "After creating or pushing to a PR" paragraph. Verified by `grep -n 'Before merging any non-docs PR\|After creating or pushing to a PR' CLAUDE.md` returning two lines where the "Before" line number is greater than the "After" line number.
- [ ] Markdown integrity — run `awk '/^\`\`\`/{n++} END{exit n%2}' docs/03_runbooks/release-checklist.md`; must exit 0.
- [ ] Cross-reference path placeholder `<DATE>` resolved to the actual `YYYY_MM_DD` (the date the feature folder will move to `implemented_features/` post-merge — typically today's UTC date). Verified by `grep -F '<DATE>' docs/03_runbooks/release-checklist.md` returning `0` matches.

---

## 3) Testing workstream

This feature has **no new test code**. Validation is observational:

- **Unit / integration / contract / E2E tests:** none added, none modified.
- **Coverage gate:** unaffected (no Python code touched).
- **AC verification:** performed manually post-merge by running the gh-CLI commands documented in the spec's AC-1 through AC-6.

The validation strategy is the workflow file itself — once the PR's `pr.yml` run succeeds (proving AC-1), the merged tree IS the deployed behavior.

## 4) Documentation update workstream

Story 1.2 lands all documentation updates in-flight:

- `CLAUDE.md` — one paragraph after line 7 (merge-skew mitigation).
- `docs/03_runbooks/release-checklist.md` — §2 + §3 query patterns rewritten.

No additional doc updates required at PR-merge time:

- `state.md` — will be updated by `/impl-execute` Step 7.5 (move feature folder + update state.md recent-changes section) as part of the standard finalization flow.
- `architecture.md` — no architectural change introduced.

## 5) Gate conditions

| Gate | Condition |
|---|---|
| Story 1.1 → 1.2 | Story 1.1 DoD checks all green AND `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pr.yml'))"` exits 0. |
| Epic 1 ship | All Story 1.1 (8 DoD items) and Story 1.2 (7 DoD items) checks green AND the feature PR's own `pr.yml` run is green (AC-1 live verification). |
| PR merge ready | All Epic 1 conditions met AND Gemini Code Assist comments adjudicated AND GPT-5.5 final review clean. |

Gate arithmetic: Story 1.1 has 8 DoD items + Story 1.2 has 7 DoD items = 15 observable conditions. Matches Epic 1's stated scope.

## 6) Plan consistency review (Section 11 from template)

| Check | Result |
|---|---|
| FRs covered: 4 spec FRs (FR-1 through FR-4) + §10 mitigation | All 5 mapped to a story in §1 |
| Endpoints: spec §8.1 declares 0 endpoints (`N/A`) | Plan endpoint tables across stories: 0. **Match.** |
| Error codes: spec §8.5 declares 0 codes | Plan contract-test task counts: 0. **Match.** |
| Files: spec §15 declares 3 doc-update files | Plan modified-file rows: 3 (`pr.yml` + `release-checklist.md` + `CLAUDE.md`). **Match.** |
| Test files: spec §14 declares 0 new test files | Plan §3 declares 0 new test files. **Match.** |
| Gate arithmetic | 2 stories × ~7 DoD = ~14 conditions. Plan §5 gate sums match. |
| Open questions resolved | Spec §19 lists none open. Plan inherits the same state. |
| Story file ownership | `pr.yml` owned by Story 1.1; `release-checklist.md` + `CLAUDE.md` owned by Story 1.2. No file appears in both stories' modified-files tables. |
| Frontend UI Guidance | N/A — no frontend scope. |
| Legacy behavior parity | N/A — no UI components deleted/replaced. |
| Enumerated value contracts | N/A — no filters/dropdowns/badges introduced. |
| Audit-event coverage | N/A — workflow YAML + doc edits; no state mutations. |
| Plan ↔ codebase: `.github/workflows/pr.yml` exists | Verified by `ls .github/workflows/pr.yml` — 28.4 KB. |
| Plan ↔ codebase: `docs/03_runbooks/release-checklist.md` exists | Verified by direct read at lines 23–36 + 38–51. |
| Plan ↔ codebase: `CLAUDE.md` line 7 reads as quoted | Verified by direct read 2026-05-28. |

No findings.

## 7) Verification ledger

| Claim | Verified by | Status |
|---|---|---|
| `pr.yml` `push:` block is at lines 29–36 | Direct read | Verified |
| `pr.yml` line 22 has the "Keep this list synchronized" comment | Direct read | Verified |
| `pr.yml` line 4 contains "every push to main" | Direct read | Verified |
| `pr.yml` concurrency block at lines 41–44 | Direct read | Verified |
| `pr.yml` has 7 `name:` declarations across 6 jobs | `grep -cE "^\s+name:" .github/workflows/pr.yml` → 7 (1 is the `smoke-logs` artifact at line 553, 6 are job names) | Verified |
| `dco.yml` and `secrets-defense.yml` are PR-event-only | `head -10` direct read of each | Verified |
| `release-checklist.md` §2 starts at line 23 | `grep -nF "## 2. Smoke reliability gate" docs/03_runbooks/release-checklist.md` → line 23 | Verified |
| `release-checklist.md` §3 starts at line 38 | `grep -nF "## 3. 80% coverage gate" docs/03_runbooks/release-checklist.md` → line 38 | Verified |
| `CLAUDE.md` line 7 contains "After creating or pushing to a PR" | Direct read | Verified |
| No workflow_run dependencies on `pr.yml` from sibling workflows | `grep -rn "workflow_run" .github/workflows/` → 0 matches | Verified |
| Repo branch protection unavailable on free-tier private repo | `gh api repos/SoundMindsAI/relyloop/branches/main/protection` → HTTP 403 | Verified |
| No README/docs badges pointing at `pr.yml` | `grep -rnE "actions/workflows/pr\.yml/badge\|/badge\.svg" README.md docs/` → 0 matches | Verified |

## 8) Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Merge-skew regression slips through (PR validated against stale base, merged anyway, breaks `main`) | Low (single-developer cadence + Claude CI watch) | Medium (transient `main` red until next merge re-validates) | Story 1.2 CLAUDE.md note. Manual "Update branch" before merge. Re-evaluate when branch protection becomes available post-public-launch. |
| Some other workflow or external surface depends on `pr.yml`'s push run that the audit missed | Very Low (grep-verified zero) | Low (revert in one-line PR) | Same-day rollback path: revert the workflow edit; runbook re-applies the old queries. |
| Future developer expects `pr.yml` to fire on direct push to `main` (e.g., post-rebase from CLI) | Low (CLAUDE.md "Never commit directly to main" already forbids) | Low (developer just opens a PR instead) | CLAUDE.md note + the workflow file's updated rationale comment both telegraph the new behavior. |

## 9) Implementation sequencing

```
Story 1.1 (workflow edit) ──▶ Story 1.2 (doc updates)
                                      │
                                      ▼
                              PR pushed, AC-1 lives
                                      │
                                      ▼
                              CI watch + Gemini + GPT-5.5 final
                                      │
                                      ▼
                                  Merge
                                      │
                                      ▼
                  Post-merge AC-2 + AC-6 manual verification
```

No parallelization opportunity (Story 1.2's release-checklist text references the Story 1.1 behavior change). Sequential within one PR.
