---
name: bug-fix
pipeline-stage: 1b
pipeline-role: "bug idea.md → bug_fix.md + branch with fix committed (default — hand off to /impl-execute --ad-hoc; with --ship — chain through merge)"
description: "Drive a medium-sized bug through CLAUDE.md's Bug Fix Protocol — reproduce first, root-cause to the right layer, lock any design forks with recommended defaults, write a focused ~80-line bug_fix.md (Problem / Repro / Root cause / Fix design / Regression test / Rollout), and implement the fix on a feature branch. The skill thinks about the bug and produces an artifact + committed code; by default it terminates at the handoff and /impl-execute --ad-hoc ships it. With the optional --ship flag, the skill chains directly into /impl-execute --ad-hoc (pre-push gate → push → PR → CI watch → Gemini adjudication → optional GPT-5.5 review → post-merge cleanup) for one-shot bug-to-merge. Sized for bugs with non-trivial design surface but smaller than features: too much for direct ad-hoc execution, too little for /pipeline scaffolding. Use when: a bug folder under planned_features/ has design surface (open forks, new migration, new prompt, cross-layer ownership), or the user asks 'fix this bug', 'take this bug through the protocol', or invokes /bug-fix on a bug folder. Trigger phrases: fix this bug, take this bug through review, run bug-fix on, investigate and fix, bug-fix protocol, ship this bug fix."
argument-hint: "[path to bug folder OR bug idea.md. If omitted, infer from the IDE-opened file] [--ship for end-to-end bug → merged PR] [--investigate for root-cause-only mode]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent, Skill, TodoWrite
model: claude-opus-4-7
user-invocable: true
---

# Bug Fix — drive a medium-sized bug from repro to committed fix

You take a bug that's been captured as a `bug_*` folder under
`docs/00_overview/planned_features/<bucket>/` (an MVP-grouping bucket like
`00_unsure/`, `01_mvp1/`, `02_mvp2/`, etc.) and drive it through CLAUDE.md's
**Bug Fix Protocol**. The skill produces two artifacts: a focused
`bug_fix.md` design doc that lives next to the original `idea.md`, AND
the actual code change committed on a feature branch. The next step
after this skill terminates is `/impl-execute --ad-hoc` to ship.

This skill is the missing middle between **direct ad-hoc execution**
(too informal for bugs with design surface) and **/pipeline**
(over-scaffolded for ~200-line bug fixes). It enforces the
reproduce-first discipline without the spec/plan ceremony.

## When to use this skill vs alternatives

Before starting, decide whether `/bug-fix` is the right tool:

| Bug shape | Use |
|---|---|
| Trivial — 1–3 line fix, no design surface, repro is the failing test that already exists | Direct edit + `/impl-execute --ad-hoc` (skip this skill) |
| **Medium — design fork to lock, new migration OR new prompt OR cross-layer ownership, ~50–500 LOC, single-file `bug_fix.md` captures the design** | **This skill** |
| Feature-scale — multi-story, UI surface, >500 LOC, multiple epics | `/pipeline` (escalate the bug to a feature) |
| Investigation-only — root cause unknown, fix scope undecided | This skill **— Investigation mode** (produces a root-cause section + open questions, stops before locking the fix) |

If the bug is trivial, **say so and stop** — recommend the user just
edit, commit, and run `/impl-execute --ad-hoc`. Don't run this skill
ceremonially on a one-line fix.

If the bug is feature-scale, **say so and stop** — recommend converting
the `bug_<slug>` folder to a `feat_<slug>` folder via `git mv`, then
running `/pipeline`.

## Inputs

- **Path to the bug folder** (preferred — `docs/00_overview/planned_features/<bucket>/bug_<slug>/`, where `<bucket>` is one of `00_unsure/`, `01_mvp1/`, `02_mvp2/`, `03_mvp3/`, `04_ga/`, `99_backlog/`) or the `idea.md` inside it. New bug folders captured by this skill default to `00_unsure/`; promote later when the release target is clear.
- **Project context (always read first):** `CLAUDE.md`, `architecture.md`, `state.md`.
- **Bug Fix Protocol section** of `CLAUDE.md` — the 6-step protocol is the spine of this skill's workflow.
- **The /idea-preflight output** if it was run on this bug recently — the patches it landed are the starting point for the `bug_fix.md`.

## Workflow

The skill walks 6 phases, in order. Each phase has a hard gate — do not
proceed if the current phase fails. The whole flow is meant to land in
~30–60 minutes for a typical medium bug.

### Phase 1 — Triage (decide if this is the right skill)

1. Read the bug folder's `idea.md` in full. List sibling files
   (`ls <folder>/`); if `bug_fix.md` already exists, this is a re-entry
   — read it and resume from whichever phase last completed.
2. **Preflight freshness check.** The `idea.md` may have been written
   weeks or months ago and quietly drifted from the current code.
   Evaluate these signals **in order; the first match wins**:
   - `git status <folder>/idea.md` — any uncommitted `M` → preflight is
     already in flight (or someone just edited the file). **Skip.**
   - `git log --since="2 weeks ago" -- <folder>/idea.md` — at least
     one commit touching idea.md → recently refreshed. **Skip.**
   - Idea frontmatter `**Date:**` ≤ 2 weeks old → too fresh to justify
     ceremony. **Skip.**
   - Idea frontmatter 2–4 weeks old AND no recent commits → **Ask
     user** ("preflight first?"); recommend yes if anything in the idea
     references file:line specifics that may have shifted.
   - Idea frontmatter > 4 weeks old AND no recent commits → idea is
     stale-by-default. **Recommend preflight**; if autonomous-mode is
     on, default to "yes, run preflight."

   If the decision is "run preflight," invoke `/idea-preflight` via the
   `Skill` tool on the same folder, wait for completion, then resume at
   step 3 below — the post-preflight idea.md is the working content.
3. Read CLAUDE.md, architecture.md, state.md.
4. Run the "When to use" table against the bug. If it doesn't sit in
   the **Medium** row, stop and recommend the right alternative.
5. **Release-window check.** Look for `pre-MVP<N>`, `MVP<N>+`, or
   `deferred until <release>` markers in the idea's frontmatter, "Why
   deferred" section, or `**Type:**` line. If present, compare against:
   - current release: read from `state.md` "Last updated" + "Active
     feature" lines
   - canonical release matrix: `CLAUDE.md` § release matrix table
     (pointer to `docs/01_architecture/tech-stack.md`)

   If we haven't reached that window, stop and surface: "this bug is
   tagged for MVP<N>; we're currently on MVP<N-1>. Pull forward, or
   defer?" Don't pull MVP-N work into MVP-(N-1) without an explicit
   user "yes."
6. Confirm the prefix is `bug_`. If the folder is `chore_` or `infra_`
   but the work is actually a bug fix, surface and ask the user
   whether to rename via `git mv` before continuing.

**Phase 1 gate:** the skill confirms with the user (or auto-detects
from clear signals) that medium-bug scope applies, the idea is fresh
enough to trust, AND the bug is in-window for the current release
before any code is touched. Trivial-scope, feature-scope, stale-idea,
or out-of-window detection terminates the skill with a redirect — not
with `bug_fix.md`.

### Phase 2 — Reproduce first

Per CLAUDE.md Bug Fix Protocol Step 1: "Reproduce first. Confirm the
error exists — read logs, check the endpoint, or run the failing test.
Understand the exact failure before changing code."

1. **Locate or write a reproducer.** Options, in order of preference:
   - A failing test the bug report cites or that already exists.
   - A short shell command that demonstrates the failure
     (e.g., `make up && curl … | grep ERROR`).
   - A test you write *now* (a single failing pytest case in
     `backend/tests/<layer>/` or `ui/src/__tests__/`) that captures
     the bug. This test stays in the final PR as the regression
     guard (Phase 5).
2. **Run the reproducer.** Confirm it fails *for the reason the bug
   describes* — not for an unrelated reason. If you can't make it
   fail the right way, the bug report is wrong or the symptom has
   shifted; stop and surface.
3. **For latent bugs** (no live user impact yet, e.g. this is a
   prophylactic fix for a near-miss capacity issue), the reproducer
   may be a stress test or property test that demonstrates the
   condition under which the bug *would* fire. State explicitly that
   the bug is latent and document the threshold.

**Phase 2 gate:** the reproducer fails for the documented reason. If
no repro is possible (e.g. a race that can't be reliably triggered),
escalate to **Investigation mode** — produce a root-cause section in
`bug_fix.md` with open questions, stop before designing the fix.

### Phase 3 — Root-cause trace

Per CLAUDE.md Bug Fix Protocol Step 2: "Don't patch symptoms… Identify
which layer owns the bug."

1. Trace from the reproducer's failure site backward through the call
   stack. For each frame, note file + line.
2. Identify the **layer that owns the bug**: domain / repo / service /
   API / worker / UI / migration / settings / external integration.
   Each layer has a different fix pattern — wrong-layer fixes will
   leave the bug for the next caller.
3. Cite 2–4 specific code locations in the form `path/to/file.py:NNN`
   where the bug manifests, propagates, or fails to be caught.
4. Distinguish **root cause** from **secondary symptoms**. Symptoms
   are interesting but not load-bearing for the fix — note them in
   `bug_fix.md`'s "Tangential" section (Phase 5 will capture them as
   idea files if they warrant follow-up).

**Phase 3 gate:** the root cause is named with file:line citations,
and the layer ownership is explicit. "Probably something in
`agent_chat.py`" is not sufficient; "the truncation at
[agent_chat.py:217-225](…) is content-blind so it drops
load-bearing assistant turns" is.

### Phase 4 — Lock the design forks

Per CLAUDE.md Bug Fix Protocol Step 3: "Make the minimal change that
addresses the root cause."

Most medium bugs have 1–3 design forks. Walk each one:

1. Surface the fork in plain terms (Option A vs Option B vs …).
2. Identify which forks are **engineering judgment calls** — those you
   can lock yourself with cited rationale. Locked decisions go into
   `bug_fix.md` as decisions, not questions.
3. Identify which forks are **product/UX judgment calls** — those
   stay in "Open questions for the user" with a recommended default;
   require the user's confirmation before continuing to Phase 5.
4. For each locked decision, cite the rule it follows (CLAUDE.md
   Absolute Rule N, an architecture doc, a recent precedent in
   `implemented_features/`, etc.).

**Phase 4 gate:** every fork is either locked-with-rationale or
escalated-to-user. No fork left as "TBD" — that's the
state the original `idea.md` was in, and the whole point of this skill
is to advance it.

### Phase 5 — Write `bug_fix.md` and implement

Now you write the artifact and the code. The artifact and the
implementation reference each other; write them in parallel, not the
artifact first then the code.

1. **Write `bug_fix.md`** at `docs/00_overview/planned_features/<bucket>/<bug_folder>/bug_fix.md`
   using the template below. Keep it tight — the target is ~80 lines.
   Anything that would push past 150 lines is a signal the bug should
   have been a feature; escalate to /pipeline. **The 150-line cap
   applies to Default-mode final output** (Problem + Repro + Root cause
   + locked Fix design + Regression test + Rollout). Investigation-mode
   partials may approach 150 lines simply because TBD sections need
   explanatory prose; that's expected and not a /pipeline-escalation
   signal on its own.
2. **Implement the fix** in the smallest scope that addresses the root
   cause. Don't refactor surrounding code, don't add features, don't
   harden unrelated paths (per CLAUDE.md "Don't add features beyond
   what the task requires").
3. **Add the regression test** referenced in `bug_fix.md`. The
   reproducer from Phase 2 IS this test in most cases — formalize it,
   add fixtures, give it a name that explains *what the bug was*
   (`test_<feature>_handles_<bug_condition>`, not `test_fixes_bug_42`).
   Verify the test exercises the previously-buggy code path under
   coverage: `pytest --cov=backend.app.<module> --cov-report=term-missing`
   should show the new test hitting the lines you changed, not just
   passing in isolation. The 80% global coverage gate (Phase 5 step 4)
   is necessary but not sufficient — a regression test that passes
   without entering the fixed code is a useless guard.
4. **Run the relevant test suite** (`make test-unit`, `make test-contract`,
   `make lint`, `make typecheck` — and `make test-integration` if the
   bug touches DB / API / worker). Don't rely on CI alone.
5. **Format before committing** (`make fmt`).
6. **Commit on the feature branch** with Conventional Commits format
   (`fix(<scope>): <subject>` for the fix; `test(<scope>): <subject>`
   for the regression test if you split commits).
7. **Tangential-observations sweep.** Per CLAUDE.md
   "Tangential discoveries — fix inline by default, defer rarely",
   resolve every unrelated issue you noticed while tracing — either
   fix it inline on this same branch (the default, when the path is
   <60 min + same subsystem + no product/operator decision needed) or,
   when inline fix genuinely fails the rubric, capture as
   `bug_<slug>` / `chore_<slug>` / `infra_<slug>` idea files in the
   same branch. Bug fixes routinely surface adjacent bugs; the inline
   fix is almost always cheaper than the deferred-and-never-fixed
   idea file. Don't carry noticings in conversation memory.

**Phase 5 gate:** `bug_fix.md` is written, the fix is committed, the
regression test fails on `main` and passes on the branch, the test
suite is green locally, tangential issues are resolved (inline or captured).

### Phase 6 — Handoff (default) OR auto-ship (--ship)

This phase branches on whether `--ship` was passed in the skill's
arguments:

#### Default (no `--ship` flag)

1. Verify the branch is ahead of `origin/main` by at least one commit.
2. Surface the branch name + `bug_fix.md` path to the user.
3. Recommend `/impl-execute --ad-hoc` as the next command — it picks up
   the committed branch and ships through the standard ceremony
   (pre-push gate → push → PR → CI watch → Gemini adjudication →
   optional GPT-5.5 review → post-merge cleanup).
4. **Also surface the `--ship` option** so the user knows next time:
   "Next time, you can pass `--ship` to chain this automatically."

**Default-mode gate:** none — the skill terminates with a clean handoff.

#### `--ship` mode

When `--ship` was passed, do NOT terminate at the handoff. Instead,
chain directly into `/impl-execute --ad-hoc` via the Skill tool — the
same way Phase 1 invokes `/idea-preflight` when the idea is stale.

1. Verify Phase 5 left the branch in a shippable state: a commit ahead
   of `origin/main`, clean working tree, regression test green locally.
   If not, abort with a clear error explaining what needs fixing
   first (do NOT auto-ship a broken state).
2. Invoke `/impl-execute --ad-hoc` via the Skill tool. Pass no arguments
   (ad-hoc mode infers everything from the current branch). The
   invocation runs Steps 0a → 7 of the impl-execute ad-hoc flow
   synchronously (Step 9 is post-merge and runs on a later invocation,
   not as part of this one — see point 3 below):
   - **0a** Worktree pre-flight
   - **0b.1** Audit-event coverage audit (MVP2+; no-op in MVP1)
   - **2.5** Tangential observations sweep (BLOCKING — bug fixes
     routinely surface adjacent bugs; the sweep catches anything
     Phase 5 step 7 missed)
   - **3** Guide impact assessment (gate; only fires if frontend was
     touched)
   - **4** Pre-push gate (`make fmt` + `make lint` + `make typecheck`
     + `ruff format --check`) + push + open PR
   - **5** CI watch
   - **6** Gemini Code Assist adjudication with four-quadrant rubric
   - **7** Optional GPT-5.5 final review (auto-triggered if diff
     crosses 30 LOC / 3 files OR touches studies / judgments / engine
     adapter / GitHub PR worker / migrations)
3. After the impl-execute invocation returns, surface the final outcome
   to the user: PR URL, CI status, review adjudication results, any
   deferred follow-up idea files captured. Step 9 (post-merge cleanup —
   delete local feature branch, fetch main, sweep agent worktrees) is
   the post-merge handoff: tell the user "ping me after merge for Step
   9 cleanup, or it'll run automatically on the next invocation in
   this repo." Do NOT poll/sleep waiting for the merge.

**`--ship`-mode gate:** the impl-execute invocation returns successfully
(PR open + CI green + reviews adjudicated). Merge itself remains a
human action — the skill does NOT auto-merge.

#### When `--ship` should NOT be used

- **Investigation mode** — there's no fix to ship. `--ship` is silently
  ignored when `--investigate` is also passed.
- **First time using `/bug-fix` on an unfamiliar codebase** — let
  default mode pause at Phase 6 so you can read `bug_fix.md` and the
  staged commits before they're pushed publicly.
- **Bug touches a release-blocking surface** — pause at default
  Phase 6 so a human can sanity-check the design before CI/Gemini
  spin cycles burn on a PR that may need a teardown.

If the user invokes `--ship` for a bug that fits the second or third
case above, surface the concern and ask for explicit confirmation
before proceeding. (Investigation-mode handling is already covered by
the silent-ignore rule — no confirmation needed.)

## `bug_fix.md` template

```markdown
# Bug fix — <bug folder slug>

**Source idea:** [idea.md](./idea.md)
**Branch:** `<bug/branch-name>`
**Type:** bug fix — medium (this skill's scope)
**Date:** YYYY-MM-DD

## Problem

<1 paragraph. What's broken, who sees it, what's the impact?>

## Reproduction

<Exact command(s) or test file:line that fails. The reproducer must
fail on `main` and pass on this branch.>

```bash
# example
pytest backend/tests/unit/test_<file>.py::test_<case> -v
```

## Root cause

<2–4 sentences naming the responsible layer + the specific code
locations where the bug originates. Cite file:line.>

- Owning layer: <domain / repo / service / API / worker / UI / migration / settings>
- Origin: [<path/to/file.py:NNN](../../../../path/to/file.py#LNNN)
- Propagation: [<path/to/other.py:NNN](../../../../path/to/other.py#LNNN)

## Fix design (locked decisions)

<Each decision, one line. Cite the rule it follows.>

1. **<Decision A>** — <rationale>. Cites: <CLAUDE.md Rule N | architecture-doc-path | precedent in implemented_features/>.
2. **<Decision B>** — …
3. **<Decision C>** — …

### Open questions (if any)

<Only if Phase 4 escalated forks. Each with a recommended default.>

## Regression test plan

<Which layer, which file, what it asserts. The test must fail
without the fix and pass with it.>

| Layer | Path | What it asserts |
|---|---|---|
| <unit / integration / contract / e2e> | `backend/tests/<…>` | <one line> |

## Rollout

<Any data migration, feature flag, operator action, or sequencing
concern. "None — code-only change" is a valid answer.>

## Tangential observations

<Idea-file links for anything noticed in tracing but out-of-scope. If
empty, write "None.">

- [bug_<slug>](../bug_<slug>/idea.md) — <one line>
- [chore_<slug>](../chore_<slug>/idea.md) — <one line>
```

## Modes

- **Default** — full 6-phase flow. Produces `bug_fix.md` + committed
  fix on a feature branch. Terminates at Phase 6 with a handoff
  recommending `/impl-execute --ad-hoc` to ship.
- **`--ship`** — Default flow PLUS auto-chain into
  `/impl-execute --ad-hoc` at Phase 6 (push + PR + CI watch + Gemini
  adjudication + optional GPT-5.5 review + post-merge cleanup). One
  invocation takes the bug from `idea.md` to a merged PR. The skill
  does NOT auto-merge — the human still clicks the merge button.
  Skipped if `--investigate` is also passed. Invoke as
  `/bug-fix <path> --ship`.
- **Investigation** (`--investigate`) — phases 1–3 only. Produces a
  `bug_fix.md` with Problem / Reproduction / Root cause sections
  filled in and Fix design / Regression test / Rollout marked **TBD**.
  Use when the fix scope is genuinely undecided and you want a human
  to weigh in before committing to a design. Invoke as
  `/bug-fix … --investigate`. `--ship` has no effect here (nothing to
  ship; investigation produces docs only).
- **Resume** — re-entry on a folder that already has a partial
  `bug_fix.md`. Reads the existing artifact, identifies the
  highest-numbered completed phase, and continues from the next.
  Auto-detected on invocation if `bug_fix.md` exists. Respects
  `--ship` / `--investigate` on the re-entry invocation.

## What this skill does NOT do

- **Open PRs / push branches** in default mode — that's
  `/impl-execute --ad-hoc`'s job. In `--ship` mode the skill delegates
  push/PR work to `/impl-execute --ad-hoc` via the Skill tool; it does
  not reimplement the ceremony.
- **Auto-merge** — even in `--ship` mode, merging is a human action.
  The skill stops at "PR open, CI green, reviews adjudicated" and
  waits for the human to merge before running post-merge cleanup.
- **Decide product or UX forks** — those go to "Open questions" with
  a recommended default and require user confirmation.
- **Refactor adjacent code** — strictly minimal fix per CLAUDE.md.
- **Promote a bug to a feature** — escalating a `bug_` folder to a
  `feat_` folder is a user call. The skill recommends the
  conversion and stops; the user runs `git mv` and `/pipeline`.
- **Write a `feature_spec.md` or `implementation_plan.md`** — those
  are /pipeline artifacts. The bug-fix flow uses `bug_fix.md`
  exclusively.
- **Run /idea-preflight** — assume the input `idea.md` is already
  preflighted, or that the design surface in it is small enough that
  preflight isn't needed. If the `idea.md` is obviously stale (claims
  contradict the current code), suggest running /idea-preflight first
  and stop.

## Common gotchas

- **The "patch the symptom" trap.** When the reproducer's failure
  site is in module A but the root cause is in module B, fixing A is
  cheaper today and more expensive forever. Phase 3 exists to force
  the right layer; if you find yourself adding a defensive guard in
  a caller, stop and look at the callee.
- **The "fix while you're in there" trap.** While tracing in Phase 3
  you'll notice 3 other bugs. Capture them as idea files in Phase 5
  step 7 — don't fold them into this fix. A bug-fix PR with 4
  unrelated changes is the same shape as an unreviewed PR.
- **The "exhaustive test coverage" trap.** The regression test
  proves the fix works. One test per bug — not "while I'm in here,
  let me add coverage for the surrounding 6 cases." Coverage gaps
  are a separate `chore_test_coverage_<area>` idea file.
- **The "trivially small fix that needs no skill" trap.** If Phase 1
  triage takes 30 seconds and you're already typing the patch, you
  picked the wrong skill — abort and use direct edit + ad-hoc.
- **The "investigation that became a fix" reversal.** If you start in
  Investigation mode and Phase 3 makes the design obvious, don't
  switch modes mid-flow; complete Investigation, save the artifact,
  let the user say "OK ship it" and re-enter in Default mode. That
  re-entry forces a second pair of eyes on the locked design.

## Termination

End with one of:

- **"Bug fix ready. `bug_fix.md` written, branch `<name>` has the
  fix + regression test committed. Run `/impl-execute --ad-hoc` to
  ship — or next time, pass `--ship` to chain automatically."** —
  Default-mode success.
- **"Bug shipped to PR #<N>. CI green, reviews adjudicated, awaiting
  human merge. Run `/impl-execute --ad-hoc` after merge for Step 9
  cleanup — or it'll happen automatically on the next invocation."** —
  `--ship`-mode success (PR open + reviews resolved; merge is the
  human's call).
- **"Investigation complete. `bug_fix.md` has Problem / Reproduction /
  Root cause filled in; Fix design needs your call on N open
  questions before continuing. Re-run `/bug-fix … ` (Default mode)
  once decided."** — Investigation-mode termination.
- **"Bug is trivial — use direct edit + `/impl-execute --ad-hoc`,
  this skill is overkill."** — Triage redirect.
- **"Bug is feature-scale — rename `bug_<slug>` → `feat_<slug>` via
  `git mv` and run `/pipeline`."** — Triage escalation.
- **"Cannot reproduce. Need <specific info> from you before
  continuing."** — Phase 2 failure.
