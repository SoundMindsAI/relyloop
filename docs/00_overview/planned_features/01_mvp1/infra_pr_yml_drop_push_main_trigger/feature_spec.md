# Feature Specification — Drop `push: branches: [main]` trigger from `pr.yml`

**Date:** 2026-05-28
**Status:** Approved
**Owners:** Eric Starr (engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml)
- [`docs/03_runbooks/local-dev.md`](../../../03_runbooks/local-dev.md)

---

## 1) Purpose

- **Problem:** [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) at lines 29–36 declares `on.push.branches: [main]` in addition to `on.pull_request.branches: [main]`. Every merge to `main` therefore re-runs the entire 5–6m CI pipeline on the merge commit even though the PR workflow already validated the same code tree (the merge commit's tree is derived from the validated PR state — modulo squash, the file tree at HEAD is functionally identical; the SHA itself differs). The redundant post-merge run is the source of the ~20 consecutive red badges on `main` between 2026-05-23 and 2026-05-28: when transient flakes (cold ES, network blips, GHA runner contention) hit a post-merge run, the badge stays red until the next successful push, eroding the signal value of "is `main` healthy."
- **Outcome:** `pr.yml` runs only on `pull_request` events. Each merge to `main` is gated by the PR-time validation against the same tree (different commit SHA after squash, identical tree contents). GHA minutes spent on redundant work drop by ~5–6m per merge. The post-merge state on `main` is reflected by the last passing PR workflow run, which is the meaningful signal.
- **Non-goal:** Fixing the underlying flake modes (cold ES shard activation, dashboard demo data) — those are owned by [`bug_smoke_seed_es_unavailable_shards_race`](../bug_smoke_seed_es_unavailable_shards_race/idea.md) (P1) and shipped sibling PRs (#290, #291). Also non-goal: splitting smoke into a separate workflow (rejected in idea § "Alternative considered").

## 2) Current state audit

### Existing implementations

The change touches exactly one file:

- [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) (28.4 KB, 28-line `on:` block) — declares both `pull_request` and `push` triggers. Lines 16–36:
  ```yaml
  on:
    pull_request:
      branches: [main]
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

  Verified by direct read 2026-05-28.

Sibling workflows that this change does NOT touch:

- [`.github/workflows/dco.yml`](../../../../../.github/workflows/dco.yml) — `on.pull_request.branches: [main]` only. No `push` trigger. No `workflow_run` dependency on `pr.yml`.
- [`.github/workflows/secrets-defense.yml`](../../../../../.github/workflows/secrets-defense.yml) — `on.pull_request` only. Mentions `pr.yml` in a comment (architectural rationale), not as a dependency.

Verified via `grep -rn "workflow_run\|workflows:" .github/workflows/` — no matches (no sibling workflow keys off `pr.yml`'s completion).

### Navigation and link impact

N/A — workflow-only change, no UI, no URLs.

### Existing test impact

N/A — no test code changes. The workflow file itself acts as the "test plan" for what gets validated.

### Existing behaviors affected by scope change

| Behavior | Current | New | Decision needed |
|---|---|---|---|
| `pr.yml` runs on every merge commit to `main` | YES — re-runs all 6 jobs on the merge SHA | NO — only the PR pre-merge run gates the merge | Already locked (operator approved the rewritten idea 2026-05-28) |
| GitHub Actions surface badge `pr` on `main` | Reflects most recent push-run on `main` (often flake-red even when PR was green) | Reflects most recent PR-run that targeted `main` (same SHA as the merge commit) | Already locked |
| Branch protection status checks | N/A — branch protection requires GitHub Pro for private repos; not available on this repo today (verified via `gh api repos/SoundMindsAI/relyloop/branches/main/protection` returning HTTP 403 with "Upgrade to GitHub Pro or make this repository public" 2026-05-28) | N/A — unchanged | None — the original idea's "branch protection" open question is moot pending the public-launch flip ([`chore_oss_public_launch_punchlist`](../../04_ga/chore_oss_public_launch_punchlist/idea.md)) |

---

## 3) Scope

### In scope

- Delete the `push:` block (lines 29–36 of `pr.yml`) and the now-redundant comment at line 22 referencing the push trigger (`# Keep this list synchronized with the \`push\` trigger below.`).
- Update the workflow's top-of-file rationale comment (lines 3–4) — currently says "Runs on every PR to main + every push to main." → "Runs on every PR to main."
- Patch [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) §2 ("Smoke reliability gate") and §3 ("80% coverage gate verification") — both currently query the post-merge push run via `--branch=main` and `--commit="$MERGE_SHA"`; after this change those queries return zero results because the merge commit's SHA is never re-validated by `pr.yml`. New query patterns documented in §15.

### Out of scope

- Splitting smoke into a separate workflow (rejected in idea § "Alternative considered").
- Setting up branch protection (unavailable on free-tier private repos; future work after [`chore_oss_public_launch_punchlist`](../../04_ga/chore_oss_public_launch_punchlist/idea.md) flips the repo public).
- Fixing [`bug_smoke_seed_es_unavailable_shards_race`](../bug_smoke_seed_es_unavailable_shards_race/idea.md) (owned separately, P1).
- Changing the `paths-ignore` list (unchanged from current behavior).
- Modifying any individual job's `timeout-minutes`, steps, or concurrency settings.

### API convention check

N/A — workflow YAML change, no HTTP API surface.

### Phase boundaries

Single-phase delivery — no Phase 2. The change is atomic (one PR, one commit). No deferred work, so no `phase2_idea.md` required.

## 4) Product principles and constraints

- **CI signal must reflect reality.** A red CI status on `main` should mean "the code on main is broken," not "a redundant post-merge run hit a transient flake." This change aligns CI semantics with the underlying truth.
- **Each code tree gets gated exactly once.** A squash-merge produces a new commit SHA on `main`, but the tree at that SHA is derived from the PR head that `pr.yml` already validated. Re-validating the same tree under a new SHA is structurally redundant work — it cannot uncover a regression the PR-time run missed.
- **Workflow changes must respect the project's only-feature-branch rule** (CLAUDE.md "Never commit directly to main"). The change lands via a feature-branch PR like any other code change.

### Anti-patterns

- **Do not** add a separate `main.yml` workflow to re-run smoke on push to main "just in case." That re-creates the exact problem we're fixing.
- **Do not** convert the `push:` trigger to a `workflow_dispatch:` "manual re-run" — the GitHub UI already supports re-running any workflow manually from the Actions tab without needing a declared trigger.
- **Do not** add a scheduled (`cron:`) trigger to give `main` a periodic health signal. The signal is already produced by the PR run before merge; periodic re-validation against an unchanged SHA adds noise without information.
- **Do not** skip the workflow file's top comment update. Stale rationale comments mislead future readers who grep for "push to main" trying to understand whether the workflow runs there.

## 5) Assumptions and dependencies

- **Assumption:** No sibling workflow keys off `pr.yml`'s `push` run. Verified via `grep -rn "workflow_run" .github/workflows/` — zero matches as of 2026-05-28.
- **Assumption:** No external service consumes the `pr.yml` push-run status (e.g., a deploy webhook, Slack notification, status badge embedded in an external site). The README badge at the repo root (if any) points to the workflow file, not a specific event type — it will render the most recent run of any type.
- **Dependency:** None blocking. The branch-protection coordination originally called out in the idea is moot per the §2 finding (free-tier private repo has no branch protection available).

## 6) Actors and roles

- **Primary actor:** Engineering operator (anyone with merge rights on `main`).
- **Role model:** N/A — single-tenant, no auth (RelyLoop MVP1–MVP3 per [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) canonical release matrix).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP3; this change predates it. Workflow YAML edits leave their own audit trail via git commit history.

## 7) Functional requirements

### FR-1: Workflow trigger surface

- Requirement:
  - The `pr.yml` workflow **MUST** trigger only on `pull_request` events targeting `main`.
  - The `pr.yml` workflow **MUST NOT** trigger on `push` events to `main`.
  - The `paths-ignore` filter on the remaining `pull_request` trigger **MUST** be byte-identical to the current configuration (lines 23–28 of `pr.yml`).

### FR-2: Comment hygiene

- Requirement:
  - The top-of-file rationale comment at `pr.yml:3-4` **MUST** be updated to remove the "+ every push to main" clause, matching the new behavior.
  - The "Keep this list synchronized with the `push` trigger below" comment at `pr.yml:22` **MUST** be deleted (the `push:` trigger it refers to no longer exists).

### FR-3: Release-checklist runbook patch

- Requirement:
  - [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) §2 "Smoke reliability gate" **MUST** be updated. The current `gh run list --workflow=pr.yml --branch=main --limit=20` returns no relevant rows after this change because (a) `--branch=main` filters by the workflow run's `headBranch`, which for PR-event runs is the source/PR branch not `main`, and (b) no push-event runs are created any longer. Replace with a two-step query that (i) derives the 5 most recently *merged* PRs (sorted by `mergedAt` to handle long-lived PRs merged out of creation order), (ii) for each, fetches the *completed* PR-event `pr.yml` run against that PR's head SHA, (iii) extracts the **per-job** `smoke` conclusion (not the workflow-run-level conclusion — `gh run list`'s `conclusion` field is workflow-level, not per-job):
    ```bash
    # 1. Get the 5 most recently merged PRs targeting main, sorted by mergedAt.
    gh pr list --state=merged --base=main --limit=20 \
      --json number,headRefOid,mergedAt \
      --jq 'sort_by(.mergedAt) | reverse | .[0:5][] | [.number, .headRefOid] | @tsv' \
      > /tmp/merged_prs
    # 2. For each PR's head SHA, find the latest completed pr.yml run + its smoke conclusion.
    SUCCESS_COUNT=0
    while IFS=$'\t' read -r pr_num head_sha; do
      RUN_ID=$(gh run list --workflow=pr.yml --event=pull_request \
                 --commit="$head_sha" --status=completed \
                 --json databaseId,createdAt \
                 --jq 'sort_by(.createdAt) | reverse | .[0].databaseId')
      [ -z "$RUN_ID" ] && { echo "PR #$pr_num: no completed pr.yml run"; continue; }
      CONCL=$(gh run view "$RUN_ID" --json jobs \
                --jq '.jobs[] | select(.name | test("smoke"; "i")) | .conclusion')
      echo "PR #$pr_num smoke: $CONCL"
      [ "$CONCL" = "success" ] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    done < /tmp/merged_prs
    # Expected: SUCCESS_COUNT == 5 (5 most-recent merged-PR smoke runs all green).
    [ "$SUCCESS_COUNT" -eq 5 ] && echo "GATE PASSED" || echo "GATE FAILED ($SUCCESS_COUNT/5)"
    ```
  - [`docs/03_runbooks/release-checklist.md`](../../../03_runbooks/release-checklist.md) §3 "80% coverage gate verification" **MUST** be updated. The current `gh run list --workflow=pr.yml --commit="$MERGE_SHA"` returns no rows because the merge-commit SHA on `main` is distinct from the PR head SHA that `pr.yml` actually validated. Replace with a query that resolves the most recently merged non-docs-only PR's head SHA (sorted by `mergedAt`; skips PRs that didn't trigger `pr.yml` because they were filtered by `paths-ignore`):
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
  - The runbook's intent (verify smoke reliability + coverage gate fired against the merged code) **MUST** be preserved — only the query mechanism changes. The runbook **MUST** explicitly document that docs-only PRs are skipped for both gates (because `paths-ignore` filters them out of `pr.yml`, by design).

### FR-4: No collateral changes

- Requirement:
  - The change **MUST NOT** modify any individual job definition (`backend-unit-fast`, `backend`, `frontend`, `smoke-test`, `docker`, `docker-ui`).
  - The change **MUST NOT** modify the `concurrency:` block at `pr.yml:41-44`.
  - The change **MUST NOT** modify the `permissions:` block at `pr.yml:38-39`.
  - The change **MUST NOT** touch [`.github/workflows/dco.yml`](../../../../../.github/workflows/dco.yml) or [`.github/workflows/secrets-defense.yml`](../../../../../.github/workflows/secrets-defense.yml).
  - The change **MUST NOT** modify the existing `paths-ignore` patterns on the `pull_request` trigger.

## 8) API and data contract baseline

N/A — no HTTP API, no data contract. Workflow YAML is the contract; the diff itself is the spec.

## 9) Data model and state transitions

N/A — no DB changes, no migrations.

## 10) Security, privacy, and compliance

- **Threats:**
  - **Skipped post-merge gate masks a regression.** Mitigation: the gate isn't actually skipped for the common case — `pr.yml` validates the PR head against the same code tree that becomes the merge commit (modulo the merge-skew edge case below).
  - **Merge skew: PR validated against stale base.** GitHub Actions `pull_request` workflows run against `refs/pull/<n>/merge`, the synthetic merge ref combining the PR head with `main` *at PR-event time*. If `main` advances after the last successful `pr.yml` run and the PR is merged without an "Update branch" or re-run, the merged tree (`new main` + PR changes) was never validated. The dropped `push:branches:[main]` trigger DID catch this case by re-running on the merge commit. Mitigation now: **project convention** — before merging any non-docs PR, the operator MUST verify the PR's latest successful `pr.yml` run was produced against the current `main`/base. If `main` advanced after the last successful run, click "Update branch" (or rebase) on the PR to re-trigger CI before merging. In practice this is low-risk for this repo today because: (a) single-developer cadence (typically 0–1 in-flight PRs at a time); (b) squash-merge as the default flow; (c) Claude-assisted CI watch on every PR. When the repo flips public ([`chore_oss_public_launch_punchlist`](../../04_ga/chore_oss_public_launch_punchlist/idea.md)) and branch protection becomes available, the "Require branches to be up to date before merging" setting MUST be enabled to make this mitigation mechanical rather than disciplinary. Until then, the §15 doc-update list adds a one-line CLAUDE.md note codifying the convention.
  - **Gate enforcement is convention, not branch protection.** Branch protection is unavailable on this free-tier private repo (verified 2026-05-28 via `gh api repos/.../branches/main/protection` returning HTTP 403). The gate-before-merge is therefore enforced by CLAUDE.md "Never commit directly to main" + reviewer discipline + CI run watched by the author, NOT by GitHub's required-status-checks mechanism. When the repo flips public, required status checks should be configured against the PR-context `pr.yml` jobs (NOT the now-removed push-context run).
  - **External badge or status surface stops updating on `main`.** Mitigation: badge audit performed 2026-05-28 — `grep -rnE "actions/workflows/pr\.yml/badge|/badge\.svg" README.md docs/` returned zero matches. No external surface depends on a `main`-scoped badge today. Future README badges (if added) MUST point at the workflow file without branch scoping, or document the PR-event scoping explicitly.
- **Secrets/key handling:** N/A — no secrets handled.
- **Auditability:** Workflow YAML changes leave a git commit trail; the diff itself is reviewable in the PR.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

N/A — no user-facing UI. The change is invisible to anyone except those reading the Actions tab.

## 12) Given/When/Then acceptance criteria

### AC-1: PR run still triggers

- Given a developer opens a PR targeting `main`.
- When the PR is created or new commits are pushed to the PR branch.
- Then `pr.yml` runs, executing all 6 jobs (`backend-unit-fast`, `backend`, `frontend`, `docker`, `docker-ui`, `smoke-test`).
- Example: open the implementation PR for this feature and observe the `pr` workflow running against the feature branch.

### AC-2: Push to main does NOT trigger

- Given a PR has been merged to `main` (any merge strategy: merge commit, squash, or rebase).
- When the merge commit lands on `main`.
- Then `pr.yml` does NOT run on the merge commit's SHA.
- Observable via two queries (both MUST be empty for the merge SHA):
  - `MERGE_SHA=$(git rev-parse main); gh run list --workflow=pr.yml --event=push --commit="$MERGE_SHA" --json databaseId,event` → `[]`
  - `gh run list --workflow=pr.yml --commit="$MERGE_SHA" --json databaseId,event` → `[]` (no run of any event type associated with the merge commit SHA, since squash-merges produce a SHA distinct from the PR head SHA that `pr.yml` actually validated)

### AC-3: paths-ignore still filters docs-only PRs

- Given a PR touches only files matching the `paths-ignore` patterns (`docs/**`, `*.md`, `.gitignore`, `LICENSE`, `release-notes-*.md`).
- When the PR is created.
- Then `pr.yml` does NOT run.
- Example: a docs-only PR like #292 (planned_features reorganization) — verify no `pr` workflow runs were created for it (existing behavior, regression-guard only).

### AC-4: Sibling workflows unaffected by PR-event firing

- Given the implementation PR is opened or updated against `main`.
- When the PR is created or new commits land on it.
- Then [`.github/workflows/dco.yml`](../../../../../.github/workflows/dco.yml) and [`.github/workflows/secrets-defense.yml`](../../../../../.github/workflows/secrets-defense.yml) both fire on the PR as they did before this change. Neither workflow's trigger surface is touched by this PR.
- Observable via `gh run list --workflow=dco.yml --branch=<pr-branch>` and `--workflow=secrets-defense.yml --branch=<pr-branch>` — each returns at least one run for the implementation PR.
- And: subsequent merge to `main` does NOT trigger new runs of either sibling workflow (both are `pull_request`-only — verified by `grep "on:" .github/workflows/dco.yml` and `.../secrets-defense.yml` showing no `push:` triggers).

### AC-5: Top-of-file rationale comment matches behavior

- Given a developer reads `pr.yml` from line 1.
- When they read the workflow's rationale comment.
- Then the comment accurately describes the trigger surface — "Runs on every PR to main." (no mention of "every push to main").

### AC-6: Release-checklist runbook queries return results

- Given the patched `docs/03_runbooks/release-checklist.md` §2 and §3 query commands.
- When a maintainer runs them after at least 5 PRs have merged to `main` post-change.
- Then both commands return non-empty results referencing the actual `pr.yml` runs that gated the merged PRs.
- Observable for §2: the loop prints 5 `PR #<n> smoke: success` lines (or one or more `failure`/`cancelled` lines, identifying which PR broke the gate) and a final `GATE PASSED` or `GATE FAILED (N/5)` line — derived from per-job `smoke` conclusions, not workflow-run-level.
- Observable for §3: a `HEAD_SHA` is resolved from the most-recent non-docs-only merged PR; `RUN_ID` is non-empty; `gh run view "$RUN_ID" --log | grep -E "TOTAL|fail_under"` shows the coverage report from the gating PR-event run.

## 13) Non-functional requirements

- **Performance:** No performance impact on the workflow itself. Reduces GHA-minute consumption by ~5–6m per merge to `main`. At the current cadence (~5–10 merges/day, per `git log --since="1 week ago" main --oneline | wc -l`), that's ~30–60 GHA-minutes/day recovered.
- **Reliability:** Improves the signal-to-noise ratio of the `pr / smoke` badge on `main` from current near-zero (chronically red from transient flakes) to high (reflects PR-time gating outcome).
- **Operability:** Zero ops burden. No alerts, no metrics, no runbook.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

The change is workflow YAML; there is no executable test surface. Validation is observational:

- **Unit / integration / contract / E2E:** None added. None affected.
- **Validation strategy:**
  - The feature PR itself triggers `pr.yml` via `pull_request` — that's the live AC-1 verification.
  - Post-merge, observe `gh run list --workflow=pr.yml --branch=main --limit=3` and confirm no new run was created for the merge SHA (AC-2).
  - Sibling workflows verified via separate `gh run list --workflow=dco.yml ...` and `--workflow=secrets-defense.yml ...` calls (AC-4).

## 15) Documentation update requirements

Verified by direct read 2026-05-28:

- **`CLAUDE.md`** — only reference today is "After creating or pushing to a PR, monitor the CI workflow" ([CLAUDE.md:7](../../../../CLAUDE.md)) — describes PR runs, not push-to-main runs. **Edit required:** add one sentence after that line codifying the merge-skew mitigation: *"Before merging any non-docs PR, verify the latest successful `pr.yml` run was produced against the current `main`. If `main` advanced after the last successful run, click \"Update branch\" on the PR (or rebase locally) to re-trigger CI before merging. This is enforced by convention until branch protection becomes available post-public-launch."*
- **`docs/03_runbooks/local-dev.md`** — only reference at [`local-dev.md:289`](../../../03_runbooks/local-dev.md) reads "Every PR runs `.github/workflows/pr.yml`" — already accurate. **No edit required.**
- **`docs/03_runbooks/release-checklist.md`** — §2 ([line 29](../../../03_runbooks/release-checklist.md#L29)) and §3 ([line 46](../../../03_runbooks/release-checklist.md#L46)) actively query the post-merge push run. **Edit required**, per FR-3 above:
  - §2 — replace `gh run list --workflow=pr.yml --branch=main --limit=20` with a PR-event query that finds the most recent 5 smoke-job conclusions across merged PRs targeting `main`.
  - §3 — replace `gh run list --workflow=pr.yml --commit="$MERGE_SHA"` with a two-step query: first `gh pr list --state=merged --base=main --limit=1 --json number,headRefOid`, then `gh run list --workflow=pr.yml --commit="$HEAD_SHA"` where `HEAD_SHA` is the PR's head-ref OID. The runbook's intent (verify smoke reliability + coverage gate fired) is preserved.
- **No other doc updates needed.** Grep across `docs/01_architecture/`, `docs/04_security/`, `docs/05_quality/` confirms no other doc references the push trigger.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — single-commit workflow change.
- **Migration/backfill expectations:** None.
- **Operational readiness gates:** The feature PR's own `pr.yml` run validates the change before merge by project convention (AC-1). When branch protection becomes available (post-public-launch flip), required status checks should be configured against the PR-context `pr.yml` jobs.
- **Release gate:** PR merged to `main`. No tag, no version bump — workflow changes don't get versioned.
- **Rollback:** If the change produces unexpected behavior (e.g., a hidden dependency on the push-context run that this audit missed), revert via a one-line PR re-adding the `push:` block. Total rollback time: minutes.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3 | Story 1.1 (workflow edit) | None (observational via `gh run list`) | None |
| FR-2 | AC-5 | Story 1.1 (workflow edit) | None (visual inspection of `pr.yml`) | None |
| FR-3 | AC-6 | Story 1.2 (runbook patch) | None (manual gh-command verification) | `docs/03_runbooks/release-checklist.md` §2 + §3 |
| FR-4 | AC-4 | Story 1.1 (workflow edit) | None (observational via `gh run list --workflow=dco.yml`) | None |
| §10 merge-skew mitigation | — | Story 1.2 (CLAUDE.md note) | None | `CLAUDE.md` (after line 7 — one-sentence "Update branch before merge if main advanced") |

## 18) Definition of feature done

- [ ] AC-1 verified: feature PR's own `pr.yml` run completed and passed.
- [ ] AC-2 verified: post-merge to `main`, both `gh run list --workflow=pr.yml --event=push --commit="$MERGE_SHA"` and `--workflow=pr.yml --commit="$MERGE_SHA"` return `[]`.
- [ ] AC-3 verified by static diff review: the `pull_request.paths-ignore` block in the post-change `pr.yml` is byte-identical to the pre-change configuration. (Later confirmation when the next organic docs-only PR lands is welcome but not blocking.)
- [ ] AC-4 verified: `gh run list --workflow=dco.yml --branch=<feature-branch>` and `--workflow=secrets-defense.yml --branch=<feature-branch>` each show ≥1 run for the implementation PR.
- [ ] AC-5 verified: `pr.yml:3-4` comment reads correctly.
- [ ] AC-6 verified: patched release-checklist.md §2 and §3 commands return non-empty results when run against the post-merge state.
- [ ] All `pr.yml`, `release-checklist.md`, and `CLAUDE.md` edits merged.
- [ ] PR merged to `main` via standard squash flow.

## 19) Open questions and decision log

### Open questions

None remaining. The original idea flagged "branch protection rule list" as an open question; resolved 2026-05-28 by the §2 audit (free-tier private repo, branch protection unavailable).

### Decision log

- **2026-05-28** — Drop the `push:` trigger entirely rather than gating it behind additional `paths-ignore` filters. Rationale: even with maximal ignores, every code-touching merge still re-runs the gate against an identical SHA, which is the structural problem. Filtering harder doesn't fix it.
- **2026-05-28** — Branch-protection coordination set aside (operational rather than permanent). Rationale: `gh api repos/SoundMindsAI/relyloop/branches/main/protection` returns HTTP 403 as of this date ("Upgrade to GitHub Pro or make this repository public") — branch protection isn't configurable on this repo under its current plan/visibility. The 403 is an operational signal (plan/token state), not a durable contract — if the repo's GitHub plan changes or the API check is repeated with different token scopes, the answer may differ. Recheck before the public-launch flip ([`chore_oss_public_launch_punchlist`](../../04_ga/chore_oss_public_launch_punchlist/idea.md)) and at that point configure required status checks against the PR-context `pr.yml` jobs (not the now-removed push-context run).
- **2026-05-28** — Rejected splitting smoke into a separate workflow (the original idea's Phase C). Rationale: wall-clock is now 5–6m thanks to PR #291's caching work; the split's cost (new YAML file, duplicated setup, harder debugging) exceeds the benefit. Revisit only if wall-clock regresses past 10m.
- **2026-05-28** — Rejected adding a scheduled (`cron:`) trigger to give `main` a periodic health signal. Rationale: the signal is produced by the PR run before merge; periodic re-validation against an unchanged SHA adds noise without information.
