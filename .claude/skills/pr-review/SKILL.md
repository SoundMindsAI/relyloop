---
name: pr-review
pipeline-stage: standalone
pipeline-role: "inbound PR → reviewed + merge decision (out-of-band; not part of the idea→spec→plan→impl pipeline)"
description: "Review an INBOUND pull request (often from an external fork) end-to-end and drive it to a merge decision. Sets up an isolated worktree on the PR head, gathers every reviewer comment (line-level + issue + formal reviews), verifies the change against the live codebase rather than trusting the PR description (dependency versions, completeness greps, affected tests + lint run locally), checks CONTRIBUTING-guide compliance (DCO sign-off, Conventional Commits, clean commit series, tests at every layer touched), adjudicates bot/human review comments with the four-quadrant rubric (and detects fixes the author already pushed by re-fetching the head + comparing SHAs), clears the pre-merge gates (merge-skew → Update branch; fork-PR workflow approval; fork-secret CI failures), captures tangential discoveries as idea files, then posts one adjudication summary and merges. Use when: a PR needs review before merge, the user asks 'review PR #N', 'look at this PR and its comments', 'is this OK to merge', 'should we approve and merge', or pastes a PR URL. Trigger phrases: review this PR, review PR, look at the PR comments, is this PR ok to merge, approve and merge, adjudicate the review, drive this PR to merge."
argument-hint: "[PR number OR GitHub PR URL. If omitted, infer from the current branch's open PR] [--no-merge to stop after adjudication] [--no-worktree to review in place]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent, Skill, TodoWrite
model: claude-opus-4-8
user-invocable: true
---

# PR Review — drive an inbound PR from review to merge decision

You review a pull request someone *else* opened (frequently an external
contributor on a fork) and drive it to a sound merge decision. This is the
**inbound** direction: you did not write the change, so the core discipline is
**verify, don't trust** — every claim in the PR description gets checked against
the live codebase before you sign off.

This is distinct from `/impl-execute --ad-hoc`, which ships *your own* committed
changes through the merge ceremony. Where the two overlap — adjudicating Gemini
Code Assist findings and posting the summary table — this skill **reuses**
`impl-execute` Step 6 by reference rather than restating it.

## When to use this skill vs alternatives

| Situation | Tool |
|---|---|
| An inbound PR (yours or a contributor's) needs review + a merge decision | **`/pr-review`** (this skill) |
| You wrote changes on a branch and want to ship them through review/merge | `/impl-execute --ad-hoc` |
| Pure code-smell/correctness pass on the working diff, no merge | `/code-review` |
| Manually exercise the change in the running app | `/verify` |

`/pr-review` composes the others: it leans on `impl-execute`'s adjudication
rubric, and may suggest `/verify` when a change needs runtime confirmation.

## Inputs

- **PR identifier:** a number (`387`), a URL, or — if omitted — infer the open PR
  for the current branch (`gh pr view --json number`). Resolve the repo `owner/name`
  from `gh repo view --json nameWithOwner` so every `gh api` call is unambiguous.
- **Flags:**
  - `--no-merge` — stop after posting the adjudication summary; leave the merge to the operator.
  - `--no-worktree` — review in the current checkout instead of an isolated worktree (use only when the operator's checkout is known-idle).
- **Project context:** read `CLAUDE.md` (the merge-ceremony rules, Absolute Rules, fork/secret pitfalls), `CONTRIBUTING.md`, and `state.md` before starting.

Track the run with `TodoWrite` — the steps below are the todo list.

## Step 0 — Isolate in a worktree

Never review on the operator's working checkout (you'll run tests, fetch refs, and
switch branches). Create a sibling worktree on the PR head:

```bash
gh pr checkout <N> --branch pr-<N>-review            # creates a local branch tracking the PR head
git worktree add /private/tmp/relyloop-pr-<N> pr-<N>-review
git checkout -                                        # restore the operator's original branch in the main checkout
```

If `gh pr checkout` switched the main checkout, switch it back immediately
(`git checkout -`). Do all subsequent work from the worktree directory. Honor the
sibling-worktree rules in `CLAUDE.md` ("Working in sibling worktrees") — never
write through a running shared Compose container; direct filesystem writes in the
worktree are safe.

> The operator's checkout is theirs. If it changes branches out from under you
> mid-run (concurrent activity), do not "fix" it — note it and leave it.

## Step 1 — Gather everything

Pull the full picture in one fan-out (independent calls, batch them):

```bash
gh pr view <N> --json number,title,author,state,body,headRefName,headRefOid,baseRefName,\
additions,deletions,changedFiles,files,mergeable,mergeStateStatus,isCrossRepository,\
maintainerCanModify,headRepositoryOwner,reviewDecision
gh api repos/<owner>/<repo>/pulls/<N>/comments   # line-level review comments (the substantive ones)
gh api repos/<owner>/<repo>/issues/<N>/comments  # general PR conversation
gh api repos/<owner>/<repo>/pulls/<N>/reviews    # formal review states (APPROVED / CHANGES_REQUESTED / COMMENTED)
```

For each line-level comment capture: author, `path`, `line`, `body`, `commit_id`,
and `in_reply_to_id`. The reply chain matters — an author reply often says "fixed
in <sha>", which Step 4 verifies. `author_association: NONE` / `isCrossRepository:
true` flags an external fork contributor (changes Step 5).

## Step 2 — Verify the change against the live codebase (trust nothing)

The PR description's "Verification" section is a claim, not evidence. Re-derive it:

1. **Core-change correctness.** Confirm the change does what it says against the
   *actual installed versions and code*, not from memory. Examples of the discipline:
   - A "deprecated API" claim → grep the dependency in `uv.lock`/`pyproject.toml`
     for the pinned version, then read the library's source for the deprecation
     decorator / changelog. (e.g. confirming `redis.Redis.close()` carries
     `@deprecated_function(..., reason="Use aclose() instead")` before accepting an
     `aclose()` migration.)
   - A behavioral fix → find the root cause at the layer the fix touches; confirm
     the fix is at the *right* layer (Bug Fix Protocol in `CLAUDE.md`).
2. **Completeness.** Grep for sibling sites the PR should have also changed
   (`grep -rn "<old pattern>" backend/ ui/`) and confirm none were missed — and that
   look-alikes that *shouldn't* change were correctly left alone (cite why).
3. **Run the affected layers locally** from the worktree:
   ```bash
   <project-venv>/bin/python -m pytest -o cache_dir=/tmp/.pytest-pr<N> <changed test files> -q
   <project-venv>/bin/ruff check <changed py files>
   # frontend changes: cd ui && pnpm lint && pnpm typecheck && pnpm test
   ```
   Use a `/tmp` cache dir, never the repo's. For broad changes, spawn parallel
   `Agent` verifiers (one per subsystem) and keep only their conclusions.
4. **Test-completeness rule (CLAUDE.md):** a change that touches DB/API/UI is not
   complete on unit tests alone. Confirm tests exist at every layer the PR touches
   (domain→unit, service→integration, endpoint→contract, UI→E2E). Missing a layer
   is an Accept-class finding, not a nit.

## Step 3 — CONTRIBUTING-guide + repo-convention compliance

Check the mechanical gates the contributor must satisfy (cite `CONTRIBUTING.md`):

- **DCO sign-off** on every commit: `git log --format='%(trailers:key=Signed-off-by)' <base>..<head>` — every commit needs a `Signed-off-by:` trailer.
- **Conventional Commits**: each subject matches the enforced prefix set (`feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci`).
- **Commit hygiene**: single logical commit or a clean series; no merge-commit noise the author should have rebased (an "Update branch" merge commit you create in Step 5 is fine — distinguish it).
- **Absolute Rules (CLAUDE.md)**: no secrets in code/logs, no bare-env-var secrets, no adapter-Protocol bypass, migrations have `downgrade()`, no hardcoded model names, enum/dropdown values grounded in a backend allowlist — only the ones the diff actually touches.

## Step 4 — Adjudicate the review comments

First, **detect already-applied fixes.** Re-fetch the head; if the author force-pushed
after the review (a reply said "fixed"), your worktree is stale:

```bash
git -C /private/tmp/relyloop-pr-<N> fetch origin pull/<N>/head
git -C /private/tmp/relyloop-pr-<N> reset --hard FETCH_HEAD
git diff <base>...HEAD          # confirm the suggested change is actually present
```

Compare each finding's `commit_id` against the current head SHA. A finding pinned
to a superseded SHA where the fix is now present → **Accept (addressed by author)**,
not an open item. (Gemini in particular often pins to the first-commit SHA — see the
`feedback_gemini_pins_to_first_sha` memory.)

Then adjudicate every remaining finding with the **four-quadrant rubric and the
common-failure-mode table in `impl-execute` SKILL.md Step 6** (Accept / Reject with
cited counter-evidence / Defer as non-regression follow-up / Escalate on a product
call). Do not restate the rubric here — apply it. Re-run the affected tests after any
fix that lands.

## Step 5 — Clear the pre-merge gates

1. **Merge-skew (CLAUDE.md pre-merge rule).** If `main` advanced past the PR base,
   the last green CI ran against a stale base. Update the branch (works on forks when
   `maintainerCanModify: true`):
   ```bash
   git merge-base --is-ancestor origin/main <head> && echo "no skew" || \
     gh api repos/<owner>/<repo>/pulls/<N>/update-branch -X PUT
   ```
2. **Fork-PR workflow approval.** External-contributor runs sit at conclusion
   `action_required` until a maintainer approves them — CI has *not* actually run yet.
   Find and approve them:
   ```bash
   gh run list --branch <headRefName> --json databaseId,headSha,workflowName,conclusion \
     --jq '.[] | select(.conclusion=="action_required" and .headSha=="<head>")'
   gh api repos/<owner>/<repo>/actions/runs/<id>/approve -X POST   # per run
   ```
3. **Watch CI; separate real reds from environmental ones.** `gh run watch <id> --exit-status`.
   Read results at the **job** level, not the overall conclusion. The known
   environmental non-blockers on this repo:
   - **Fork-secret failure** — forked PRs can't read repo secrets, so any job gated on
     one (e.g. the `smoke` job's `OPENAI_API_KEY_TEST` sanity-check) hard-fails before
     running. Tracked in `infra_smoke_fork_pr_secret_skip` (issue #410). Non-code.
   - **Smoke runtime-budget cancellation** — the `smoke` job can be `cancelled` by its
     25-min `timeout-minutes` cap. Tracked in `infra_smoke_reseed_runtime_budget`. Non-code.
   - There are currently **no required status checks on `main`** (`project_main_no_heavy_ci_gate`
     memory), so an `UNSTABLE` mergeable state from a non-required red does not block merge —
     but every *code-validating* job must be green before you sign off.

## Step 6 — Capture tangential discoveries

If the review surfaced an out-of-scope problem (a CI gap, a stale runbook, a missed
test layer that isn't this PR's job to add), file an idea file per the CLAUDE.md
"Tangential discoveries" rule + the implement-over-defer rubric — default bucket is
the active release from `state.md`. Cross-reference siblings bidirectionally. This is
how the fork-secret gap above got captured. Don't carry it in the PR description.

## Step 7 — Adjudication summary + merge

These steps publish to third parties / touch `main`. Per `CLAUDE.md` (and the
plain-language-status memory), **confirm with the operator before posting and before
merging** unless they've already said "drive it to merge."

1. **Post one summary comment** with a verdict table over every finding (the format
   in `impl-execute` Step 5.4 / the "Review adjudication" template). State the merge-skew
   resolution and the CI outcome (including any environmental red and *why* it's non-blocking).
2. **Merge** with the repo's default (`gh pr merge <N> --squash --delete-branch`).
   Verify it landed (`gh pr view <N> --json state,mergeCommit`) — `gh pr merge` can exit
   nonzero from a trailing sub-command even when the merge succeeded, so always confirm
   state is `MERGED` rather than trusting the exit code.
   With `--no-merge`, stop after step 1.

## Step 8 — Clean up

```bash
git worktree remove /private/tmp/relyloop-pr-<N> --force
git branch -D pr-<N>-review        # and any temp fetch branches
rm -f /tmp/pr-<N>-*.md /tmp/.pytest-pr<N> -r
```
Confirm `git worktree list` shows only the main checkout and the operator's checkout
is on its original branch.

## Output — the review verdict

Report conversationally (per the plain-language-status memory — sentences, not a Jira
changelog; the table goes on the PR, not in chat). Cover:

- **What the PR does** and whether it's **correct** (with the evidence you checked).
- **Completeness + convention compliance** (DCO, Conventional Commits, test layers).
- **Reviewer comments**: addressed / still-open, with your verdicts.
- **Pre-merge state**: merge-skew, CI (real vs environmental reds), mergeability.
- **Bottom line**: a clear merge recommendation, and what you did (posted / merged / held).

## Guardrails

- **Verify, don't trust.** The PR description is a claim. Never sign off on a version
  claim, a "no other call sites" claim, or a "tests pass" claim without re-deriving it.
- **Never echo secret-bearing files** (`feedback_never_echo_secret_files`) — verify by
  length/prefix/grep-for-presence, never by printing content.
- **Confirm before publishing/merging.** Posting a comment and merging to `main` are
  the two gated actions in `CLAUDE.md`; get the operator's go unless durably authorized.
- **Don't merge with a failing *code* job** even though `main` has no required checks —
  the absence of branch protection is not license to merge red code. Environmental reds
  (fork-secret, smoke timeout) are the only acceptable non-green at merge, and only with
  the reason stated in the summary comment.
- **One PR at a time** (`feedback_one_branch_per_session`) — don't open spin-off PRs
  mid-review; capture follow-ups as idea files, not parallel branches.
