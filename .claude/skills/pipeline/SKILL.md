---
name: pipeline
pipeline-stage: 0
pipeline-role: orchestrator
description: "Orchestrate the full feature development pipeline from idea to staging deployment. Detects current stage, invokes the next skill (spec-gen, impl-plan-gen, impl-execute, guide-gen), and pauses for approval between stages. Use when: running a feature end-to-end, resuming a feature pipeline, checking pipeline status, or advancing a feature to the next stage. Trigger phrases: run pipeline, advance feature, pipeline status, idea to staging, full pipeline, resume pipeline."
argument-hint: "<path to feature directory> [--auto] [--from <stage>] [--to <stage>] [--status]"
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

- **`$ARGUMENTS`**: Required. Path to the feature directory under `docs/02_product/planned_features/`.
  - Example: `docs/02_product/planned_features/EPIC_RBAC-GAPS_01-team_management_ui`
- **Optional flags** (appended after the path):
  - `--auto` — **Autonomous mode.** Run the entire pipeline (idea → spec → plan → implement → PR) without pausing for inter-stage approval. Cross-model review, verification gates, and test suites still run within each skill — those are hard gates, not skippable. In epic mode, `--auto` pauses only between features (not between stages within a feature). See "Autonomous mode" section below.
  - `--from <stage>` — Force start from a specific stage (`idea`, `spec`, `plan`, `implement`). Overrides auto-detection.
  - `--to <stage>` — Stop after completing a specific stage. Useful for generating just the spec or just the plan.
  - `--status` — Report current pipeline status without advancing. No skills invoked.

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

## Workflow

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
   - **Flat siblings** with an epic prefix (e.g. `docs/02_product/planned_features/EPIC_RBAC-GAPS_01-*`).
   - **Nested layout** where the epic is a parent folder containing numbered child phase folders (e.g. `docs/02_product/planned_features/epic_account_security/phase_01_*`). Glob one level deeper into the parent folder and enumerate only child directories whose basename matches `phase_[0-9][0-9]_*`; sort lexicographically. Ignore `README.md`, `deferred_*` folders, and any other non-`phase_XX_*` planning material at the epic root.
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
/pipeline docs/02_product/planned_features/EPIC_RBAC-GAPS_01-team_management_ui --auto
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
