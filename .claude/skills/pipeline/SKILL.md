---
name: pipeline
pipeline-stage: 0
pipeline-role: orchestrator
description: "Orchestrate the full feature development pipeline from idea to staging deployment. Detects current stage, invokes the next skill (spec-gen, impl-plan-gen, impl-execute, guide-gen), and pauses for approval between stages. Use when: running a feature end-to-end, resuming a feature pipeline, checking pipeline status, or advancing a feature to the next stage. Trigger phrases: run pipeline, advance feature, pipeline status, idea to staging, full pipeline, resume pipeline."
argument-hint: "status | <path to feature directory> [--auto] [--from <stage>] [--to <stage>] [--status]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent, WebFetch, WebSearch, TodoWrite
model: claude-opus-4-7
user-invocable: true
---

# Feature Pipeline Orchestrator

You orchestrate the full feature development pipeline for the RelyLoop project. You do NOT duplicate the logic of individual skills — you detect the current stage of a feature, invoke the appropriate skill, pause for user approval, and advance to the next stage.

## Pipeline stages

```
  idea.md ──▶ /spec-gen ──▶ /impl-plan-gen ──▶ /impl-execute ──▶ deployed
     1            2               3                  4              5
   IDEA         SPEC            PLAN           IMPLEMENT        DONE
```

Each stage produces artifacts and requires approval before advancing:

| Stage | Input artifact | Skill invoked | Output artifact | Approval gate |
|-------|---------------|---------------|-----------------|---------------|
| **IDEA** | `idea.md` | — | — | Idea exists and is ready for spec |
| **SPEC** | `idea.md` | `/spec-gen` | `feature_spec.md` | User approves spec |
| **PLAN** | `feature_spec.md` | `/impl-plan-gen` | `implementation_plan.md` | User approves plan |
| **IMPLEMENT** | `implementation_plan.md` | `/impl-execute --all` | Code + PR + CI green | Phase gates + final review pass |
| **DONE** | PR merged | — | — | Staging deploy verified |

Guide generation is handled automatically by `/impl-execute` post-implementation workflow (Step 2b) — the orchestrator does not invoke `/guide-gen` separately.

## Inputs

`$ARGUMENTS` is one of:

- **`status`** (or empty) — **Project-wide status mode.** Enumerate every feature under `docs/00_overview/planned_features/`, sort by dependency-derived priority order, and render a status table with a single explicit "Next action" line. No skills are invoked. See [Project-wide status mode](#project-wide-status-mode-no-feature-path) below.
- **`<path to feature directory>`** — Single-feature mode. Detect the current stage and advance it. Path must be under `docs/00_overview/planned_features/`.
  - Example: `docs/00_overview/planned_features/EPIC_RBAC-GAPS_01-team_management_ui`
- **Optional flags** (appended after the path; ignored in `status` mode):
  - `--auto` — **Autonomous mode.** Run the entire pipeline (idea → spec → plan → implement → PR) without pausing for inter-stage approval. Cross-model review, verification gates, and test suites still run within each skill — those are hard gates, not skippable. In epic mode, `--auto` pauses only between features (not between stages within a feature). See "Autonomous mode" section below.
  - `--from <stage>` — Force start from a specific stage (`idea`, `spec`, `plan`, `implement`). Overrides auto-detection.
  - `--to <stage>` — Stop after completing a specific stage. Useful for generating just the spec or just the plan.
  - `--status` — Report current single-feature status without advancing. No skills invoked. (For project-wide status across all features, use the bare `status` argument instead.)

## Stage detection

On invocation, detect the current stage by examining the feature directory:

```
1. Read pipeline_status.md if it exists — this is the authoritative source
2. If no pipeline_status.md, infer from artifacts:
   a. implementation_plan.md exists AND has execution tracker with completed stories → IMPLEMENT (in progress or done)
   b. implementation_plan.md exists → PLAN complete, ready for IMPLEMENT
   c. feature_spec.md exists → SPEC complete, ready for PLAN
   d. idea.md exists → IDEA complete, ready for SPEC
   e. Nothing exists → ERROR: no idea.md found
```

**Important:** `pipeline_status.md` may not exist for features created before this orchestrator was added. Fall back to artifact detection gracefully.

### Status report format

When `--status` is passed or when reporting status before advancing:

```
Pipeline Status: <Feature Name>
Directory: <path>

  [x] Idea        idea.md
  [x] Spec        feature_spec.md (approved 2026-04-14, 2 GPT-5.5 cycles)
  [ ] Plan        Not started
  [ ] Implement   Not started
  [ ] Done        —

Next action: Generate implementation plan from approved spec
Command: /impl-plan-gen <path>/feature_spec.md
```

## Project-wide status mode (no feature path)

When `$ARGUMENTS` is the literal string `status` (or empty), render a project-wide pipeline status across **all** features in `docs/00_overview/planned_features/`. **Do not invoke any skills in this mode.** The user is asking "where are we and what's next" — give them an unambiguous answer.

**Scope:** `/pipeline status` mirrors the **Idea table** from [`MVP1_DASHBOARD.md`](../../../docs/00_overview/MVP1_DASHBOARD.md) — i.e., the prioritized backlog. The `#` column in the output IS the per-table ordinal from the dashboard's Idea table for the same working tree (not a global cross-stage ordinal). Spec/Plan/Implementing stages are typically empty or hold one in-flight item that the operator already knows about — surface those as a brief one-line "in flight" note above the Idea table rather than re-rendering them.

**Two distinct "what's next" answers — don't conflate them:**

- **`/pipeline status`'s Next action** (this skill) answers: "what's the next item from the prioritized backlog to work on?" The answer is the first row of the tier-sorted Idea table (`_md_sort_key`).
- **The dashboard's "Next up" callout** (rendered by `_next_action` in the regen script) answers a different question: "what scoped `feat_`/`infra_`/`epic_`/`chore_` feature is next to ship through the dependency DAG?" It excludes `idea`-stage rows and `bug_*` rows entirely (they're not nodes in the shipped-feature DAG), so when the backlog is all idea-stage / bug-stage items, the callout correctly reports "all scoped features shipped — pull from the Idea backlog."

These two answers can legitimately diverge and that's the design — each is correct for its own question. `/pipeline status` always answers the first one. Don't try to merge the algorithms.

### Algorithm

1. **Enumerate feature directories.** `ls docs/00_overview/planned_features/`. Exclude `feature_templates/` and any non-feature folders (no `feature_spec.md` and no `idea.md`).

2. **Parse dependencies for each feature.** For each `<feature>/feature_spec.md`:
   - Read the first ~20 lines.
   - Look for a `Depends on:` line (typically near the top metadata block, e.g. `- Depends on: [\`infra_foundation\`](...)`).
   - Extract the list of referenced feature folder names. Treat phrases like "ALL prior backend features", "ALL prior MVP1 features", or "all backend" as a transitive dependency on every other feature whose folder name starts with `infra_` or `feat_`.
   - If the spec has no `Depends on:` line, treat it as a root (no dependencies).
   - If only `idea.md` exists (no spec), parse `idea.md` the same way; if neither exists, the feature is uncategorizable — list it separately under "Unparseable" at the bottom.

3. **Sort the pending-work list** with the canonical `_md_sort_key` from [`scripts/build_mvp1_dashboard.py:1799`](../../../scripts/build_mvp1_dashboard.py). The tuple is `(priority_value, type_order[prefix], short_name)`:
   - **Priority tier first** (P0 → P1 → P2 → Backlog). This is the high-stakes signal — within-tier ordering is the tiebreaker, not the headline.
   - **Then prefix order:** `feat → infra → epic → chore → bug` (the `type_order` map at line 1797 of the regen script). Note: this is **NOT** alphabetical-by-prefix; `feat` comes first because shipped-feature-shaped backlog items take priority over scaffolding/cleanup at the same tier.
   - **Then alphabetical** by `short_name` (the part after the prefix underscore).
   - If you find yourself wanting to reorder these tiebreaker layers in prose, **don't** — update `scripts/build_mvp1_dashboard.py` instead, regen, and let this skill follow.

   **Note about cycles in the dep graph:** the Idea-table sort doesn't run a topological sort — it doesn't need to, since the dashboard regen guarantees the dep DAG is acyclic for shipped features (where the "Next up" callout's `_priority_order` does run Kahn's). For Idea-stage work, deps are informational (rendered in the "Depends on" column) but don't change ordering. If an idea cites a sibling idea that hasn't shipped, that's surfaced in the column, not by row position.

4. **Cross-check against `docs/02_product/mvp1-user-stories.md`** §"Stories grouped by feature". That doc lists features in their canonical narrative order. Compare to the dep-derived order:
   - **If they match:** great — present the priority order without comment.
   - **If they disagree:** present the dep-derived order (it's authoritative because it's machine-verifiable from the specs), and add a single line below the table flagging the disagreement: `**Note:** dep-derived order differs from mvp1-user-stories.md (X is at position N here vs. M in the doc) — review the spec's "Depends on" line or the doc to reconcile.`

5. **Detect each feature's current stage** from artifacts in its directory:
   - Folder exists in `implemented_features/` for this slug AND no `phase*_idea.md` remains in the planned-features folder (or the planned-features folder is gone) → **DONE**.
   - `implementation_plan.md` exists with completed stories in execution tracker AND a `phase*_idea.md` file remains alongside it → **PARTIAL (Phase N done, Phase N+1 pending)**. The folder stays in `planned_features/` until every deferred phase ships, per `impl-execute` Step 8.6. The "Next action" for a partial feature is to run `/pipeline <feature>/phase<N+1>_idea.md` so a fresh spec/plan loop starts on the deferred phase.
   - `implementation_plan.md` exists with completed stories in execution tracker → **IMPLEMENT (in progress)**
   - `implementation_plan.md` exists, no completed stories → **PLAN complete, ready for IMPLEMENT**
   - `feature_spec.md` exists, no plan → **SPEC complete, ready for PLAN**
   - `idea.md` exists only → **IDEA complete, ready for SPEC**
   - Folder exists with no artifacts → **EMPTY**

6. **Pick the "Next action."** The next feature is the **first row of the tier-sorted Idea table** (`_md_sort_key` order — tier → prefix → alphabetical) whose stage is not DONE. This is `/pipeline status`'s answer; it does NOT delegate to `_priority_order` (that's the dashboard's "Next up" callout for shipped-feature DAG progression — a different question). For PARTIAL features (status = idea + a sibling `phase*_idea.md` exists), the next action targets the deferred phase's `phase*_idea.md`, not the original feature folder. Quote the exact `/pipeline <path>` command.

> **Canonical algorithm reference.** The algorithm above is implemented in [`scripts/build_mvp1_dashboard.py`](../../../scripts/build_mvp1_dashboard.py) at three specific call sites that MUST stay in sync:
>
> - **`_md_sort_key`** (line ~1799) — the canonical sort key for the Idea / Spec / Plan / Implementing tables in `MVP1_DASHBOARD.md`. The `#` column in those tables IS the position produced by this sort.
> - **`_priority_order`** (line ~1132) — the DAG-aware topological sort used by the `_next_action` "Next up" callout. Excludes `idea`-stage and `bug_*` features (they're not dependency-graph nodes). Uses `type_order` (a subset — feat → infra → epic → chore, no bug) as the within-DAG tiebreaker, but does NOT use the priority tier as a sort key — it sorts purely by (deps, prefix, name). This is intentional: `_priority_order` answers a different question than `_md_sort_key` ("what's the next scoped feature to SHIP through the DAG?" vs. "what's the highest-priority backlog item to WORK ON?"). The two can produce different answers for the same input, and that's correct.
> - **`_next_action`** (line ~1179) — picks the first non-done feature from `_priority_order` and emits the exact `/pipeline ...` command for the next stage.
>
> The dashboard is the durable artifact — `/pipeline status` is the live-conversation view that should match what the dashboard shows for the same working tree. If the two ever disagree on priority order, the `#` column, or stage detection, **the regen script is the source of truth**; update this skill's prose or shell out to the script, never let them drift. The regression test at [`backend/tests/unit/scripts/test_dashboard_priority_sort.py`](../../../backend/tests/unit/scripts/test_dashboard_priority_sort.py) locks the tiebreaker order so future edits to either side can't silently diverge.

### Required output format

```
Pipeline Status — MVP1 Priority Order

| #  | Priority | Feature                  | Type    | Depends on | Idea | Spec | Plan | Implement | Done |
|----|----------|--------------------------|---------|-----------|------|------|------|-----------|------|
| 1  | **P1**   | feat_ubi_judgments       | Feature | MVP1 ✓    |  ✓   |  —   |  —   |    —      |  —   |
| 2  | P2       | feat_auto_followup_studies | Feature | —       |  ✓   |  —   |  —   |    —      |  —   |
| ... (sorted by tier → feat→infra→epic→chore→bug → alphabetical)                              |
| 14 | Backlog  | chore_e2e_seed_acme_helper_dead | Chore | —      |  ✓   |  —   |  —   |    —      |  —   |

**Next action: advance #<n> `<feature>` from <STAGE> → <NEXT STAGE>.**

```
/pipeline docs/00_overview/planned_features/<feature>
```

Implemented: <count> · Planned: <count> · Cross-checked against `MVP1_DASHBOARD.md` Idea-table `#` column: <match | mismatch flagged inline above>
```

- The `#` column matches the dashboard's Idea-table `#` column for the same working tree (sort: priority tier → prefix order → alphabetical; see "Canonical algorithm reference" below).
- The `Priority` column makes the tier visible inline; the row order still tells the operator what to work on first.
- The `Depends on` column shows the `#` of each upstream feature, not the full slug, to keep the table tight. Use `—` for roots, `all backend` / `all MVP1` for transitive deps. For Idea-stage items the dep cell is informational only — deps don't change row order at the idea stage (sort is tier+prefix+alphabetical, not topological).
- Use `✓` for completed stages, `—` for not-started, `…` for in-progress (e.g. plan exists but stories are partial).
- File-link each feature name to its `feature_spec.md` (or `idea.md` if no spec yet) so the user can click through.
- The "Next action" line is mandatory and must contain exactly one feature, exactly one stage transition, and exactly one runnable command.

### Why this matters

The user explicitly asked never to have to guess what's next. A status table sorted by `ls` output forces them to mentally walk the dependency graph; a priority-sorted table with a single "Next action" line does that work for them.

## Workflow

### Step 0: Branch on `status` vs. feature path

If `$ARGUMENTS` is `status` (or empty), execute "Project-wide status mode" above and return. Do not proceed to Step 1.

Otherwise (a feature path was provided), continue to Step 1 below.

### Step 1: Read context and detect stage

1. Read `CLAUDE.md`, `architecture.md`, `state.md` for project context.
2. Read the feature directory contents (`ls` the directory).
3. Read `pipeline_status.md` if it exists.
4. If no `pipeline_status.md`, check for `idea.md`, `feature_spec.md`, `implementation_plan.md`.
5. Determine the current stage and the next stage to execute.
6. Apply `--from` override if provided (skip to that stage regardless of detection).
7. Apply `--to` limit if provided (plan to stop after that stage).
8. Report current status to the user.

### Step 2: Confirm advancement

**In `--auto` mode:** Skip this step entirely. Report what's about to happen (one line per stage), then begin executing immediately. Do not wait for user confirmation.

**In interactive mode (default):** Before invoking any skill, confirm with the user:

> **Pipeline will advance to: SPEC stage**
> - Input: `idea.md` (summarize the idea in 1-2 sentences)
> - Skill: `/spec-gen <path>/idea.md`
> - This will generate a feature specification with cross-model review (Opus creates, GPT-5.5 reviews, iterate until clean).
> - Estimated scope: <brief based on idea complexity>
>
> Proceed?

If the user has already indicated they want to run the full pipeline (e.g., "run the full pipeline" or "take this to staging"), treat that as blanket approval to advance through stages — but still pause at each approval gate (after each skill completes) to let the user review the output.

### Step 3: Execute stages sequentially

For each stage from current to target:

#### Stage: IDEA → SPEC

1. Verify `idea.md` exists and read it.
2. Invoke `/spec-gen <feature_dir>/idea.md`.
3. Spec-gen will:
   - Generate the spec from the idea
   - Run Opus verification passes
   - Run GPT-5.5 cross-model review (iterate until clean, max 3 cycles)
   - Present major findings for approval
   - Write `feature_spec.md`
   - Write `pipeline_status.md` with spec stage marked complete
4. **Approval gate:**
   - **`--auto` mode:** Log a brief summary of the spec (feature name, FR count, phase count, GPT-5.5 cycle count). Proceed immediately to the next stage. The cross-model review within spec-gen already caught major issues — no human pause needed.
   - **Interactive mode:** Present the spec to the user.
     > "Spec generated at `<path>/feature_spec.md`. Review the spec — particularly the API contracts (Section 8), data model (Section 9), and acceptance criteria (Section 12). Approve to continue to implementation plan, or request changes."
5. If the user requests changes (interactive only), re-invoke `/spec-gen <path>/feature_spec.md` in Review & Patch mode.
6. On approval (or auto-advance), proceed to next stage.

#### Stage: SPEC → PLAN

1. Verify `feature_spec.md` exists and read it.
2. Invoke `/impl-plan-gen <feature_dir>/feature_spec.md`.
3. Impl-plan-gen will:
   - Generate the plan from the spec
   - Verify spec-plan FR traceability
   - Run GPT-5.5 cross-model review (iterate until clean, max 3 cycles)
   - Present major findings for approval
   - Write `implementation_plan.md`
   - Update `pipeline_status.md` with plan stage marked complete
4. **Approval gate:**
   - **`--auto` mode:** Log a brief summary of the plan (story count, epic count, test layer coverage, GPT-5.5 cycle count). Proceed immediately to implementation. The cross-model review within plan-gen already caught major issues.
   - **Interactive mode:** Present the plan to the user.
     > "Plan generated at `<path>/implementation_plan.md`. Review the stories, endpoints, and key interfaces. The plan covers <N stories across M epics>. Approve to begin implementation, or request changes."
5. If the user requests changes (interactive only), re-invoke `/impl-plan-gen <path>/implementation_plan.md` in Review & Patch mode.
6. On approval (or auto-advance), proceed to next stage.

#### Stage: PLAN → IMPLEMENT

1. Verify `implementation_plan.md` exists and read it.
2. Create a feature branch if not already on one (never commit to main).
   - Branch naming: `feature/<feature-dir-slug>` (e.g., `feature/rbac-gaps-01-team-management-ui`)
   - If already on a feature branch, continue on it.
3. Invoke `/impl-execute <feature_dir>/implementation_plan.md --all`.
4. Impl-execute will:
   - Execute stories sequentially with verification gates
   - Run phase gate cross-model reviews (GPT-5.5)
   - Run test coverage audit
   - Extract deferred work
   - Update documentation
   - Assess guide impact (and optionally run `/guide-gen`)
   - Push and create PR
   - Monitor CI
   - Check Gemini review comments
   - Run final GPT-5.5 review
5. **Approval gate:**
   - **`--auto` mode:** Report the results (PR URL, CI status, test counts, review status). This is the end of autonomous execution for this feature — the user must merge the PR manually. In epic mode, pause here for the user to merge and confirm before starting the next feature.
   - **Interactive mode:** Report the results.
     > "Implementation complete.
     > - PR: #<number> (<url>)
     > - CI: <status>
     > - Tests: <unit count>, <integration count>, <contract count>, <e2e count>
     > - Cross-model reviews: <N> phase gates passed, final review clean
     > - Guide impact: <assessment>
     >
     > Review the PR. When CI is green and reviews are addressed, merge to main to trigger staging deploy."
6. **Finalize after CI + Gemini review pass** (impl-execute Step 7):
   - Verify all stories complete (execution tracker all `[x]`)
   - Update `pipeline_status.md` to `Implementation: Complete`
   - Update `implementation_plan.md` status to `Complete (PR #<N>)`
   - Update `state.md`: add to recent changes, update current focus + branch context
   - **Check for `phase*_idea.md` files** — if any exist, STOP and ask the user for instructions (the folder contains unimplemented future work)
   - Move feature folder: `planned_features/<dir>` → `implemented_features/<YYYY_MM_DD>_<short_name>/`
   - Commit and push the finalization changes

#### Stage: IMPLEMENT → DONE

This stage is manual — the user merges the PR and verifies the staging deploy. The orchestrator can help monitor:

1. If the user says "merged" or "PR is merged":
   - Check staging deploy status: `gh run list --branch=main --limit=3`
   - Monitor the deploy: `gh run watch <run_id>`
   - Verify staging health if health endpoint exists
2. Update `pipeline_status.md`:
   ```
   ## Done
   - Status: Deployed to staging
   - Date: <YYYY-MM-DD>
   - PR: #<number>
   - Release: <tag if applicable>
   ```

### Step 4: Report completion

After reaching the target stage (or DONE), report the full pipeline status:

```
Pipeline Complete: <Feature Name>

  [x] Idea        idea.md
  [x] Spec        feature_spec.md (approved, 2 GPT-5.5 cycles)
  [x] Plan        implementation_plan.md (approved, 1 GPT-5.5 cycle)
  [x] Implement   PR #XX merged, CI green, 12 stories, 47 tests
  [x] Done        Deployed to staging 2026-04-14

Deferred work: phase2_idea.md (if applicable)
Guide updates: Guide 08 regenerated (if applicable)
```

---

## Resuming a pipeline

When invoked on a feature that's mid-pipeline:

1. Detect the current stage (Step 1).
2. If a stage is in progress (e.g., impl-execute was interrupted):
   - For IMPLEMENT: invoke `/impl-execute <plan> <next-story-id>` to resume from the next incomplete story.
   - For SPEC or PLAN: re-invoke the skill — it will detect the existing file and enter Review mode.
3. If a stage is complete but the next hasn't started, advance normally.

---

## Multi-feature pipeline (epic mode)

When the feature directory contains multiple sub-features (e.g., an EPIC with numbered features):

1. The user invokes the pipeline on the parent epic concept, not individual features.
2. The orchestrator identifies each feature directory. Two layouts are supported:
   - **Flat siblings** with an epic prefix (e.g. `docs/00_overview/planned_features/EPIC_RBAC-GAPS_01-*`).
   - **Nested layout** where the epic is a parent folder containing numbered child phase folders (e.g. `docs/00_overview/planned_features/epic_account_security/phase_01_*`). Glob one level deeper into the parent folder and enumerate only child directories whose basename matches `phase_[0-9][0-9]_*`; sort lexicographically. Ignore `README.md`, `deferred_*` folders, and any other non-`phase_XX_*` planning material at the epic root.
3. Process features **sequentially** in numbered order — each feature goes through the full pipeline before the next starts.
4. Respect dependencies: if feature 02 depends on feature 01 (stated in its idea.md), ensure 01's PR is merged before starting 02.
5. Report aggregate status across the epic.

**In interactive mode:** The orchestrator processes one feature at a time and pauses for approval between features. The user can say "continue to the next feature" to advance.

**In `--auto` mode:** The orchestrator runs each feature end-to-end autonomously (idea → spec → plan → implement → PR), then **pauses between features**. This is the only pause point in `--auto` mode. The user must:
1. Review and merge the PR for the completed feature
2. Confirm the staging deploy succeeded
3. Say "continue" to start the next feature

This ensures dependent features (e.g., feature 02 depends on 01's PR being merged) don't start on stale code.

---

## Autonomous mode (`--auto`)

When `--auto` is passed, the pipeline runs the full lifecycle for each feature without pausing for inter-stage approval. This is the intended mode for running an epic end-to-end.

### What still runs (hard gates — never skipped)

These quality gates within each skill are **not affected** by `--auto`. They fire exactly as in interactive mode:

| Gate | Skill | What happens |
|------|-------|-------------|
| Opus verification passes (Pass 1 + 2) | spec-gen | Codebase accuracy + architectural consistency |
| GPT-5.5 cross-model review (max 3 cycles) | spec-gen | Contract, data model, impact, coverage |
| Opus convergence loop | spec-gen | Internal review until clean |
| Opus verification passes | impl-plan-gen | Plan-internal consistency + codebase accuracy |
| GPT-5.5 cross-model review (max 3 cycles) | impl-plan-gen | Structural, contract, implementation, risk |
| Story verification gates (lint, typecheck, tests) | impl-execute | Per-story quality gate |
| Phase gate cross-model review (GPT-5.5) | impl-execute | Per-phase cumulative diff review |
| Test coverage audit | impl-execute | All planned test files must exist |
| Final GPT-5.5 review | impl-execute | Complete PR diff review |
| CI pipeline | impl-execute | GitHub Actions must pass |
| Gemini Code Assist review check | impl-execute | Review comments addressed |

### What's skipped (inter-stage pauses only)

| Skipped | Why it's safe |
|---------|---------------|
| "Approve spec to continue?" pause | GPT-5.5 already reviewed the spec with max 3 convergence cycles |
| "Approve plan to continue?" pause | GPT-5.5 already reviewed the plan with max 3 convergence cycles |
| "Approve implementation to merge?" pause | PR is created but NOT merged — user still merges manually |

### When `--auto` stops (escalation triggers)

Even in `--auto` mode, the pipeline **stops and escalates to the user** when:

1. **Verification gate failure** — lint, typecheck, or test failure that can't be auto-fixed
2. **Cross-model review produces unresolved High-severity findings after 3 cycles** — convergence not reached
3. **CI failure** — GitHub Actions workflow fails
4. **Manual configuration required** — GitHub App registration, DNS changes, deployment-target env vars, registering an Elasticsearch/OpenSearch test cluster, etc.
5. **Missing prerequisites** — idea.md doesn't exist, spec has unresolved open questions
6. **Dependency not met (epic mode)** — prior feature's PR hasn't been merged yet

On escalation, the pipeline reports what happened, what needs to be resolved, and how to resume (`/pipeline <dir> --auto --from <stage>`).

### Example: autonomous epic run

```bash
/pipeline docs/00_overview/planned_features/EPIC_RBAC-GAPS_01-team_management_ui --auto
```

This will:
1. Read `idea.md` → run `/spec-gen` (Opus + GPT-5.5 review cycles) → write `feature_spec.md`
2. Immediately run `/impl-plan-gen` (Opus + GPT-5.5 review cycles) → write `implementation_plan.md`
3. Create feature branch → run `/impl-execute --all` (stories, phase gates, tests, GPT-5.5 reviews)
4. Push, create PR, monitor CI, check Gemini comments, run final GPT-5.5 review
5. **Stop.** Report: "Feature 01 complete. PR #XX ready for review. Merge and confirm to continue to feature 02."

---

## Error handling

### Skill failure
If a skill fails (e.g., spec-gen encounters unresolvable issues, impl-execute hits a verification gate failure):
1. Report what failed and why.
2. Do NOT advance to the next stage.
3. Suggest remediation (re-run with fixes, manual intervention needed, etc.).
4. The pipeline can be resumed after the issue is resolved.

### Missing artifacts
If expected artifacts are missing (e.g., `feature_spec.md` referenced but doesn't exist):
1. Report the gap.
2. Offer to start from the appropriate earlier stage.

### Branch conflicts
If the feature branch already exists or has diverged:
1. Check the branch state before creating a new one.
2. If a branch exists with work from a previous pipeline run, offer to continue on it or create a fresh branch.

---

## Rules

1. **Never duplicate skill logic.** The orchestrator invokes skills — it does not re-implement spec generation, plan generation, or story execution.
2. **Never skip approval gates in interactive mode.** Each stage completion requires user acknowledgment before advancing. In `--auto` mode, inter-stage pauses are skipped but all quality gates within skills (cross-model review, verification, tests) still fire. Auto mode still pauses between features in an epic.
3. **Never commit to main.** Feature branches only.
4. **Always report status before advancing.** The user must know what stage they're at and what's about to happen.
5. **Always use the correct skill.** spec-gen for specs, impl-plan-gen for plans, impl-execute for implementation. Never substitute.
6. **Respect `--to` limits.** If the user says `--to plan`, stop after plan approval — do not start implementation.
7. **Track progress in pipeline_status.md.** Update it at each stage transition so future conversations can resume.
8. **Handle missing pipeline_status.md gracefully.** Many features pre-date this orchestrator — fall back to artifact detection.
9. **One feature at a time.** In epic mode, complete one feature's full pipeline before starting the next.
10. **Inform the user at every transition.** What just completed, what's next, what they need to review.
11. **Project-wide status output is always priority-ordered with one explicit "Next action."** When invoked as `/pipeline status` (or with no arguments), sort features by dependency-derived order parsed from each spec's "Depends on:" line; never sort by directory listing, alphabet, or recency. End the output with a single bold "Next action:" line and the exact `/pipeline <path>` command to run. The user must not have to scan the table and guess.
