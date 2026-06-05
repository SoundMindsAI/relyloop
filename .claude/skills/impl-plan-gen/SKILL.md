---
name: impl-plan-gen
pipeline-stage: 2
pipeline-role: feature_spec.md → implementation_plan.md
description: "Generate, review, or patch implementation plans from feature specs. Use when: creating implementation plans from approved specs, reviewing existing plans for accuracy, auditing plan-spec-codebase alignment, or patching plan inaccuracies. Trigger phrases: create implementation plan, review implementation plan, plan accuracy audit, plan-spec alignment, generate impl plan."
argument-hint: "[path(s): feature_spec.md for Generate, impl_plan.md for Review/Review & Patch, or 'feature_spec.md impl_plan.md' for Reconcile]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent
model: claude-opus-4-7
user-invocable: true
---

# Implementation Plan Generator & Reviewer

You are working with implementation plans for the RelyLoop project. Depending on the mode, you either generate a new plan from an approved feature spec, review an existing plan for accuracy, or reconcile a plan against its spec and the codebase.

The implementation plan is the bridge between "what to build" (the spec) and "how to build it" (the code). Every claim in the plan must be grounded in both the spec and the codebase.

## Mode selection

Before starting, determine which mode applies based on the user's request and the argument provided:

| Mode | When to use | Writing behavior |
|---|---|---|
| **Generate** | User provides a path to an approved feature spec. No implementation plan exists yet. | Creates a new plan file. |
| **Review** | User provides a path to an existing plan. Asks for accuracy review, audit, or findings. | Returns findings only — does NOT rewrite the plan unless the user explicitly asks. |
| **Reconcile** | User provides both a spec and a plan, or asks to check alignment between them. | Returns findings on mismatches between spec, plan, and codebase. Does NOT apply edits without approval. |
| **Review & Patch** | User provides a plan and explicitly asks to fix/correct/apply findings. | Applies corrections to the plan file. |

**Default to Review mode if ambiguous.** Only write files when the mode clearly requires it.

## Inputs

- **$ARGUMENTS**: One or two file paths depending on mode:
  - **Generate**: single path to the approved feature spec (e.g., `docs/.../feature_spec.md`)
  - **Review / Review & Patch**: single path to the existing plan (e.g., `docs/.../implementation_plan.md`)
  - **Reconcile**: two paths separated by a space — spec first, then plan (e.g., `docs/.../feature_spec.md docs/.../implementation_plan.md`)
- **Plan template**: `docs/00_overview/planned_features/feature_templates/implementation-plan-template.md`
- **Project context**: `CLAUDE.md`, `architecture.md`, `state.md`

---

## Workflow — Generate mode

### Step 1: Gather context

Read these files in order:

1. `CLAUDE.md` — project conventions, absolute rules, data model, stack
2. `architecture.md` — system design, boundaries, critical flows, frontend page structure
3. `state.md` — current priorities, recent changes, known debt, Alembic head
4. `docs/00_overview/planned_features/feature_templates/implementation-plan-template.md` — the output template
5. The approved feature spec at $ARGUMENTS — every FR, AC, data model change, API contract, and test requirement

### Step 2: Codebase exploration

Before writing any stories, explore the codebase to ground the plan in reality:

1. **Verify the spec's Section 2 (Current state audit)** — read every file referenced. Confirm paths, function signatures, and column names are still accurate.
2. **Read existing patterns for each layer the plan will touch:**
   - If the plan adds a migration: `ls` the actual Alembic versions directory, check the current head revision number.
   - If the plan adds a router: read `backend/app/main.py` to see how routers are registered (prefix, tags, dependencies).
   - If the plan adds a service: read an existing service to confirm the job_run lifecycle, quota check, and error handling patterns.
   - If the plan adds a repo function: read the relevant repo file to confirm conventions (db: Session first arg, flush vs commit, return types).
   - If the plan modifies frontend: read the target component to get current line count, section structure, state variables, props, and insertion points.
3. **Identify analogous implementations** — find the closest existing feature to the one being planned. Use it as the structural template for stories.

### Step 3: Generate the plan

Using the template structure, build the plan from the spec:

**Critical rules for plan generation:**

- **Every story must trace to at least one FR from the spec.** Use the spec's traceability matrix (Section 17) as the starting point for Section 1 of the plan.
- **Every endpoint in the spec's Section 8 must appear in exactly one story's endpoint table.** Count them and verify.
- **Every error code in the spec's Section 8.4 must appear in the plan's contract test tasks.** Count them and verify.
- **New file paths must match the actual project layout.** Do not guess migration directories, router paths, or test file locations — verify by reading the filesystem.
- **Modified file tables must reference files that actually exist.** Glob for each one.
- **Key interfaces must use types and patterns from the existing codebase.** Read the layer you're adding to and match signatures.
- **Frontend stories must include UI element inventories and state dependency analysis** when creating, moving, or removing components. Read the target component first to document its current state.
- **Analogous markup patterns must include actual JSX** copied from the codebase, not just "follow the X pattern" references.
- **Error shapes in endpoint tables must match the per-route verification from the spec.** Do not assume a universal envelope — copy the exact shape the spec documented for each route.
- **Auth dependencies in endpoint tables must match the spec's API convention check.** Use the exact `Depends()` chain documented in the spec.
- **E2E test tasks must run against the real backend and exercise the browser layer.** No `page.route()` mocking. Tests must use Playwright's `page` object for real browser interactions (navigate, fill forms, click buttons, assert DOM). API calls via `request` are acceptable for test setup only — assertions must verify browser-visible behavior. Anchor to `signup_flow.spec.ts` as the reference pattern: setup via API helpers → seed localStorage with real tokens via `addInitScript` → interact via `page`. Gate LLM/discovery-dependent tests behind env vars if needed.
- **Never hardcode LLM model names.** Reference `LLMProvider` abstraction and `create_llm_provider()`.

### Step 4: Plan-internal consistency review (Pass 1)

Execute the plan template's Section 11 (Plan consistency review) systematically:

1. **Spec ↔ plan endpoint count**: Count endpoints in the spec's Section 8.1 table. Count endpoints across all stories in the plan. They must match. List any gaps.
2. **Spec ↔ plan error code coverage**: Count error codes in the spec's Section 8.4. Verify each appears in a contract test task in the plan's Section 3.3.
3. **Spec ↔ plan FR coverage**: Verify every FR in the spec has a row in the plan's Section 1 traceability table and is assigned to at least one story.
4. **Story internal consistency**: For each story:
   - Endpoint table fields match Pydantic schema fields (names, types).
   - DoD assertions reference the correct error codes and HTTP status codes from the endpoint table.
   - New files are not claimed by multiple stories (no ownership conflict).
   - Modified files exist in the codebase (glob for each).
5. **Test file count and assignment**: Count test files across all stories. Verify they match the testing workstream (Section 3) inventory. **Every test file in Section 3 must be assigned to exactly one story's DoD** — orphaned test files in the testing workstream that aren't referenced by any story will be skipped during execution. If a test file doesn't naturally belong to a single story (e.g., integration tests spanning multiple stories), assign it to the last story in the epic that completes the testable surface, or create a dedicated "Write tests" story at the end of the epic.
6. **Gate arithmetic**: Verify epic/phase gate statements match actual endpoint/story counts.
7. **Open questions resolved**: Confirm every open question from the spec's Section 19 is resolved.
8. **Frontend UI Guidance completeness** (REQUIRED if any story has frontend scope): Verify the plan includes a plan-level "UI Guidance" section with ALL of the following subsections from the template. If any are missing, the plan is incomplete:
   - **Insertion point** — exact lines being replaced/modified, what stays above/below
   - **Analogous markup patterns** — actual copy-pasteable JSX (not just "follow the X pattern") for every new UI section, copied from the closest existing codebase pattern
   - **Layout and structure** — visual hierarchy, column arrangement, responsive behavior
   - **Confirmation/modal dialog pattern** — actual JSX if the feature includes any dialogs, following the codebase's existing modal pattern
   - **Visual consistency table** — maps every new UI element to its CSS class/pattern source
   - **Component composition** — whether new UI is inline or extracted, with rationale
   - **Interaction behavior table** — every user action → frontend behavior → API call
   - **Handler function patterns** — actual TypeScript for key event handlers (fetch calls, error handling, state updates)
   - **Information architecture placement** — where the feature lives in the navigation hierarchy, what comes before/after in tab/section order, how users discover it. If the spec (§11) defines navigation placement and labeling taxonomy, verify the plan preserves them.
   - **Tooltips and contextual help** — for every non-obvious UI element identified in the spec's tooltip inventory (§11), include the tooltip text, trigger, placement, **glossary key, source-of-truth comment target** (the `// Source-of-truth: <backend/path.py> <Symbol>` comment shape used in `ui/src/lib/glossary.ts` and `ui/src/lib/enums.ts`), and actual JSX/markup pattern from the codebase. Missing tooltips = missing UX — treat gaps the same as missing UI elements. A tooltip plan that omits the glossary key bypasses the source-of-truth discipline `feat_contextual_help` established; reject it the same way you'd reject a placeholder JSX snippet.
   - **Legacy behavior parity** (REQUIRED when any story deletes or replaces a user-facing component with >100 LOC of JSX, or migrates significant UI functionality between files): the plan MUST include a "Legacy behavior parity" table listing every validation, loading state, error handler, disabled condition, optimistic update, button-label-state change, tooltip, and confirmation dialog shipped in the deleted/moved component. Each row must state either (a) "Preserved in: `<file>:<symbol or line>`", or (b) "Intentionally dropped — reason: `<product/spec citation>`". The corresponding story's DoD must assert (unit, integration, or E2E) every "Preserved" row. This prevents silent UX regressions where client-side validations and inflight states get lost during component rewrites — a failure mode that reviewers (GPT-5.5, Gemini) repeatedly catch post-hoc. "TypeScript compiles" and "happy path renders" do not exercise a missing `minLength={20}` check or a button that re-fires while a request is in flight.
   This check exists because AI agents cannot visually verify their output. Without concrete markup and patterns, frontend stories produce ambiguous implementations that require rework.

Record every finding in the verification ledger.

### Step 5: Codebase accuracy review (Pass 2)

Verify the plan's claims against the actual codebase:

1. **Infrastructure paths**: Verify migration directory, Alembic head revision, router registration pattern, test file locations.
2. **State variable names and locations**: For frontend stories, grep for each state variable listed in removal/move lists. Verify it exists where claimed.
3. **Function names and signatures**: For key interfaces, grep to confirm the functions they extend/call actually exist.
4. **Line number references**: For insertion points and analogous patterns, verify line numbers are within ~20 lines of actual code.
5. **API endpoints in frontend**: Verify that fetch calls reference endpoints that exist in the backend routers.
6. **State dependencies**: For refactors, verify that state being removed isn't referenced by components the plan doesn't account for.
7. **Frontend data plumbing**: For every prop a story passes to a component, verify the parent has access to that data.
8. **Persistence scope**: For `localStorage`/`sessionStorage` usage, verify task description and DoD agree on persistence scope.
9. **Legacy-delete behavior parity**: For every story that deletes or replaces a user-facing component >100 LOC, confirm the plan includes a Legacy Behavior Parity table. For each table entry marked "Preserved in: …", verify the named file/symbol exists (glob/grep). For each entry marked "Intentionally dropped", verify the cited spec section or product-decision reference actually authorizes the drop. Additionally, grep the deleted file for `onChange\|onClick\|onSubmit\|onBlur\|maxLength\|minLength\|pattern=\|disabled=\|aria-disabled\|role="alert"\|catch \(\|setError\|setLoading\|confirm\(` and for each match check that the matched behavior appears in the parity table with a verdict. Unlisted behaviors indicate an incomplete table.

10. **Enumerated value contract verification**: For every filter dropdown, sort control, status badge, tier/bucket label, role selector, platform identifier, or other `<select>` whose wire value the backend validates against a fixed allowlist:
    - Confirm the spec has a §7.4 "Enumerated value contracts" table (or equivalent) citing the backend source-of-truth file (enum, `frozenset`, `Literal[...]`, Pydantic `Field(pattern=...)`, or DB CHECK constraint).
    - Grep that backend file to enumerate the exact wire values. Build a 3-column verification: (1) values in backend, (2) values in spec, (3) values the plan's frontend story will render. All three columns MUST match character-for-character.
    - Flag any story that adds a frontend `<select>` / filter chip / badge variant without explicitly listing the wire values AND the backend source file in the UI element inventory.
    - Require the plan to specify a source-of-truth comment above each generated option array (e.g., `// Values must match backend/db/models/study.py StudyStatus`). Missing comments make future drift harder to prevent.
    **Why:** This is the highest-leverage check for frontend/backend contract drift. The the sibling project (PR #183) filter-bar shipped with a phantom "mid" tier and four wrong stage-bucket values (PR #183) — none caught by TypeScript, lint, unit tests, or contract tests. Only a grep-against-source audit surfaces this class of bug before production.

11. **Audit-event coverage verification**: For every endpoint or service function the plan adds or modifies that mutates state:
    - Confirm the spec's §6 "Audit-event instrumentation matrix" lists the mutation site with a chosen event type (new or existing).
    - For new event types: verify the plan has a story to add the type to the canonical `audit_log` event-type Literal/enum in `backend/db/models/audit_log.py`. RelyLoop's MVP2 audit-log is a single append-only table per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../docs/01_architecture/data-model.md); no separate allowlist machinery, no per-event UI category mapping, no admin timeline tab.
    - Confirm the emission story specifies atomic emission: the `audit_log` INSERT happens inside the same transaction as the primary mutation, before `db.commit()`. (When MVP4 brings auth + tenants, this story expands to include `actor_id`/`tenant_id` FK resolution.)
    - Confirm the plan includes a contract test asserting metadata shape on the audit row (mirror the canary pattern in `backend/tests/contract/test_study_audit.py`).
    - Mutations that do NOT need an audit event must be explicitly justified in the plan (e.g. "internal cache update", "covered by existing `STUDY_STARTED` emission"). Silent gaps are findings.
    **Why:** Audit-event capture gaps are silent — tests pass, the feature ships, and only weeks later does someone ask "who changed this study?" with no record. Reference: [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../docs/01_architecture/data-model.md). (Activates at MVP2 when audit_log lands.)

Record every finding in the verification ledger.

### Step 6: Cross-model review (Opus ↔ GPT-5.5)

This step is **mandatory** when the GPT-5.5 review mechanism is configured and callable in the current runtime. The external reviewer is **GPT-5.5** (model: `gpt-5.5` via the OpenAI API). This is not configurable — the cross-model value comes from using a different model family, not a different instance of the same model.

**API key resolution:**
The `OPENAI_API_KEY` is stored in the project `.env` file (not automatically available in the shell environment). To resolve it:
1. Parse the key: `grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-`
2. Use it in API calls via a Python script with `urllib.request` or `curl`, passing the key as a `Bearer` token in the `Authorization` header.
3. Do NOT attempt to check `$OPENAI_API_KEY` from the shell — `.env` files are not sourced into the shell environment by default.

**API call mechanism:**
Use a Python script (via the Bash tool) with `urllib.request` to call the OpenAI Chat Completions API (`https://api.openai.com/v1/chat/completions`). Send the plan text and source spec as the user message, with review instructions in the system message. Request structured JSON output for findings.

**Fallback if GPT-5.5 is unavailable** — see CLAUDE.md §"Cross-model review policy" → "Environment-aware fallback" (authoritative source; this block defers to it):
- **Claude Code remote sandbox — the common case here: GPT-5.5 is *expected*-unreachable** (no `OPENAI_API_KEY` and/or `api.openai.com` egress-blocked). This is a SANCTIONED standing condition, not an error. Proceed with **Opus self-review** (run the verification passes yourself) and state in the output: `cross-model review: Opus self-review (GPT-5.5 unreachable)`. It is a documented *degradation* — Gemini Code Assist remains the cross-family gate at the code/PR stage. To restore real GPT-5.5 review, enable egress + `OPENAI_API_KEY` per CLAUDE.md "Durable fix".
- If the `.env` file does not contain `OPENAI_API_KEY` **in a non-sandbox environment** (key unexpectedly missing — distinct from the sandbox case above, where its absence is expected and silent): alert the user, then proceed with Opus self-review.
- If the API call fails (auth error, timeout, model not available): log the failure, alert the user, and proceed with Opus-only internal review passes. Do NOT silently skip the step — the user must be informed that cross-model review was skipped and why.
- If the user explicitly opts out (e.g., "skip external review"): proceed without it, but note in the review log that cross-model review was skipped by user request.

**Reviewer roles (both fulfilled by GPT-5.5):**

GPT-5.5 reviews in two labeled passes within a single prompt (or two separate calls):

| Role | Focus areas |
|---|---|
| **Pass A: Structural & Contract** | Spec-plan FR traceability, endpoint count parity, error code coverage, story endpoint/schema consistency, gate arithmetic, migration path accuracy |
| **Pass B: Implementation & Risk** | Key interface feasibility, frontend state dependencies, analogous pattern accuracy, test layer completeness, sequencing risks, downstream impact of story ordering |

**Review protocol:**

1. Send the full plan text AND the source spec to GPT-5.5 with both role focus areas. Request findings as structured output: claim, evidence (file:line), severity (High/Medium/Low), reviewer pass (A or B).

   **On cycle 2 and later — include the rejection log from earlier cycles in the system prompt**, structured as:

   ```
   ## Previously rejected findings (do NOT re-raise without new information)

   The following findings were raised in prior cycles and rejected by Opus with
   cited counter-evidence. Unless you have *new* evidence that materially changes
   the analysis, omit these from your cycle-N response:

   - Cycle 1 finding #{N}: "{short quote of the claim}"
     Rejection: {one-line counter-evidence, with file:line}
   - Cycle 1 finding #{M}: "{short quote of the claim}"
     Rejection: {one-line counter-evidence, with file:line}
   ...

   You may re-raise a listed finding ONLY if you have new information (a code
   change since last cycle, a corrected citation, a genuinely different angle).
   If you re-raise, state the new information explicitly in the `finding` field.
   "Disagreeing with the rejection" is not new information.
   ```

   This prunes repeat findings that burned time in the OAuth-disconnect session (the label-string and FR-9 findings got re-raised in cycles 2 and 3 with no new information). Repeats-only cycles are still valid — the convergence stop rule (Step 7) treats a repeats-only response as a clean pass.

2. **Opus adjudication:** For each GPT-5.5 finding, Opus must do one of:
   - **Accept** — cite the evidence, stage the correction for the findings gate (Step 8). Log in the verification ledger.
   - **Reject** — cite counter-evidence from the codebase (file:line) that disproves the finding. Log the rejection with the counter-evidence.
   - **Escalate** — if evidence is ambiguous or the finding requires a product/architecture decision, flag as an open question for the user.
3. Rejections without cited counter-evidence are not allowed. "I disagree" is not sufficient — show the code.

**Important:** Accepted corrections from the cross-model review are **staged, not applied immediately**. Major accepted corrections require user approval at the findings gate (Step 8) before being written. Minor accepted corrections may be applied without gating.

### Step 7: Cross-model convergence loop

After Opus applies accepted corrections from GPT-5.5, determine whether another GPT-5.5 review cycle is needed:

**Re-review trigger:** If any accepted correction changed a **major** element (endpoint table, key interface, file path, migration detail, story scope, gate condition, or test strategy), send the corrected plan back to GPT-5.5 for a fresh review pass. Apply minor corrections before re-submitting so GPT-5.5 reviews the most current version.

**Cross-model loop stop rules:**
- **Stop** when GPT-5.5 reports no new High-severity findings AND Opus has no unresolved accepted changes to apply.
- **Stop** when GPT-5.5 returns only findings that Opus has already rejected with cited counter-evidence in a previous cycle (no new information).
- **Stop** after a maximum of 3 Opus ↔ GPT-5.5 cycles. If convergence is not reached by cycle 3, present the remaining disagreements to the user for resolution.

**Internal convergence (Opus-only):** After the cross-model loop completes, Opus may run additional internal review passes (Steps 4–5) if needed:
- If two consecutive Opus-only passes produce only wording or formatting edits, stop.
- Maximum 2 additional Opus-only passes after the cross-model loop.

**Convergence criteria** (applies to both cross-model and internal passes): A pass is "clean" if it produces no changes to:
- Story endpoint tables or Pydantic schemas
- New/Modified file tables
- Key interface signatures
- Migration file paths or revision numbers
- Epic/phase gate conditions
- Test task scope or file assignments
- Sequencing or dependency declarations

### Step 8: Findings gate

Before writing any files, classify all staged findings and corrections (from both Opus internal passes and GPT-5.5 cross-model review) into:

- **Major** (High severity): Changes to endpoint contracts, key interfaces, file ownership, migration details, story scope, sequencing, or gate conditions. These change what gets implemented.
- **Minor** (Medium/Low severity): Wording, formatting, DoD phrasing, documentation references, task ordering within a story. These improve clarity but don't change the implementation.

**Gate rules:**
- **Major findings**: Present to the user for confirmation before applying. List each finding with its source (Opus internal or GPT-5.5 Pass A/B) and the proposed correction. Do not write files until the user approves.
- **Minor findings**: May be applied without explicit confirmation, but include them in the review log.
- If there are no major findings, proceed directly to writing.

### Step 9: Write the plan

Write the final plan to the appropriate location:
- Default: same directory as the feature spec, named `implementation_plan.md`
- Ask the user if they have a preferred location/filename

### Step 10: Track deferred phases

**This step is MANDATORY when the plan covers only a subset of the spec's phases.** Deferred phases contain scoped, reviewed work that will be lost if not explicitly tracked as a future work artifact.

1. Read the spec's "Phase boundaries" section. Identify any phases NOT covered by this implementation plan.
2. For each deferred phase, check whether a tracking file already exists (`glob` for `*idea*.md` or `*phase*_idea.md` in the feature directory).
3. If no tracking file exists, create one at `docs/00_overview/planned_features/<bucket>/<feature_dir>/phase<N>_idea.md` (in the same MVP bucket as the parent feature: `00_unsure/`, `01_mvp1/`, `02_mvp2/`, `03_mvp3/`, `04_ga/`, or `99_backlog/`) following the `idea.md` template pattern (see `docs/00_overview/planned_features/feature_templates/idea-template.md`). Include:
   - Origin pointer to the spec file and line numbers
   - The deferred FRs with enough context to generate a future spec/plan
   - Why the work was deferred (from the spec's phase boundary rationale)
   - Dependencies on the implemented phase
4. Inform the user about the deferred work tracking file so they know where to find it.

**Why this matters:** Spec phase boundaries represent reviewed, scoped work. Without an explicit tracking artifact, deferred phases exist only as prose inside a completed spec and are effectively invisible to future planning sessions.

### Step 11: Update project docs

Evaluate whether these files need updates:

- `state.md` — if this plan changes active priorities or introduces new planned work
- `architecture.md` — if the plan reveals architectural decisions not yet documented

Present proposed doc updates to the user for approval before writing.

### Step 12: Update pipeline status

**This step is MANDATORY in Generate mode.** Update the `pipeline_status.md` file in the feature directory to record the plan stage completion. This file enables the `/pipeline` orchestrator to detect what stage a feature is at and resume automatically.

Update the `## Plan` section in `docs/00_overview/planned_features/<bucket>/<feature_dir>/pipeline_status.md`:

```markdown
## Plan
- Status: Approved
- Date: <YYYY-MM-DD>
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (<N> cycles)
- Stories: <N total across M epics>
- Phases covered: <list of phases>
```

If `pipeline_status.md` does not exist yet (e.g., spec-gen was run before this step was added), create the full file with the Idea and Spec sections populated based on existing artifacts in the directory:
- Check for `idea.md` → mark Idea as Complete
- Check for `feature_spec.md` → mark Spec as Approved (date from file modification time)
- Fill in the Plan section with current data

### Step 13: Sync the tracking issue (if one exists)

**Generate mode only.** If the folder has a GitHub tracking issue, keep it in step with the new plan per [`docs/00_overview/planned_features/feature_templates/tracking-issue-template.md`](../../../docs/00_overview/planned_features/feature_templates/tracking-issue-template.md):

1. Find it: `gh issue list --state all --limit 300 --json number,title --jq '.[] | select(.title|startswith("<feature-dir-slug>:")) | .number'` (anchored `startswith` — a bare `test()` substring-matches longer slugs). If none, skip.
2. Flip `Stage → PLAN`, swap the stage label `needs-preflight` → `ready-to-execute` (now that spec+plan are both present), or set `blocked` if a `Blocked by:` gate is unmet — never `ready-to-execute` for a gated/design-ahead feature. Add the Plan artifact link, and ensure the inline DoD reflects the plan's stories/ACs.
3. Re-verify any `file:line` you write into the issue against the current tree.

---

## Workflow — Review mode

When reviewing an existing plan (not generating a new one):

1. **Gather context**: Read `CLAUDE.md`, `architecture.md`, `state.md`, the plan at $ARGUMENTS, and the plan's referenced feature spec (`Primary spec` field in the plan header).
2. **Run Pass 1 (plan-internal consistency)** and **Pass 2 (codebase accuracy)** against the existing plan.
3. **Build the verification ledger** for every material claim.
4. **Deferred phase audit**: Read the source spec's "Phase boundaries" section. If the plan covers only a subset of phases, check whether each deferred phase has a tracking artifact (`glob` for `*idea*.md` or `*phase*_idea.md` in the feature directory). Report untracked deferred phases as a **Medium** finding: "Spec Phase N (FR-X through FR-Y) has no tracking file — deferred work will be invisible to future planning."
5. **Cross-model review (optional but recommended):** If GPT-5.5 is available, send the plan and its source spec for external review using the same protocol as Generate mode Step 6. This strengthens the audit by catching blind spots in the primary model's review. If unavailable, note in the review log.
6. **Return findings only.** Do not rewrite the plan. Present findings (from both Opus and GPT-5.5 if applicable) as:
   - Severity (High / Medium / Low)
   - Source (Opus internal / GPT-5.5 Pass A / GPT-5.5 Pass B)
   - Location (file:line in the plan)
   - What the plan claims vs. what the spec or codebase shows
   - Suggested correction (if straightforward)
7. **Flag open questions** that need the user's input to resolve.

---

## Workflow — Reconcile mode

When checking alignment between a spec and a plan:

1. **Read both documents** and the project context files.
2. **Spec → plan traceability**: List every FR, endpoint, error code, and AC from the spec. For each, check whether the plan covers it. Flag gaps.
3. **Plan → spec traceability**: List every story endpoint, key interface, and new file from the plan. For each, check whether it traces to a spec FR. Flag orphaned stories (plan work with no spec backing).
4. **Deferred phase audit**: If the spec defines phases not covered by the plan, check whether each deferred phase has a tracking artifact. Flag untracked deferred phases in the alignment report.
5. **Codebase drift**: If time has passed since the spec was written, check whether the codebase has changed in ways that affect the plan (e.g., new migrations, renamed functions, moved files).
6. **Return the alignment report** with recommendations: add to plan, remove from plan, create tracking file, update spec, or flag as open question.

---

## Workflow — Review & Patch mode

When the user provides findings or explicitly asks to fix an existing plan:

1. **Gather context**: Read `CLAUDE.md`, `architecture.md`, `state.md`, the plan at $ARGUMENTS, and the plan's referenced feature spec.
2. **Verify each finding** against the codebase and spec. For each finding:
   - Read the referenced code to confirm accuracy.
   - Record in the verification ledger as Verified, Partially Correct, or Incorrect.
   - If incorrect, cite counter-evidence (file:line).
3. **Classify findings** into Major and Minor (see Findings gate).
4. **Present Major findings** to the user with proposed corrections. Wait for approval.
5. **Apply approved corrections** to the plan file. Apply Minor corrections without gating.
6. **Run a single verification pass** on the patched plan to confirm corrections didn't introduce new issues.
7. **Return the verification ledger** and a summary of what was changed.

---

## Verification ledger

For every material claim in the plan (file paths, endpoint tables, key interfaces, migration details, state variables, test file assignments), maintain a ledger:

| Claim | Verified by | Status |
|---|---|---|
| Migration dir is `backend/alembic/versions/` | `ls backend/alembic/versions/` | Verified |
| Alembic head is `0022_llm_routing_cfg` | `ls backend/alembic/versions/ \| sort \| tail -1` | Verified |
| `create_study()` accepts `contact_source` kwarg | Read `backend/db/repo/study_repo.py:43` — uses `**kwargs` | Verified — kwargs pass-through |
| Story 1.2 modifies `platforms-keywords-tab.tsx` | `glob web/src/components/settings/platforms-keywords-tab.tsx` | Verified |
| Frontend `best_metric` available in StudiesPage | Read `web/src/app/studies/page.tsx` — not currently fetched | **Corrected** — story must add fetch |

Include the ledger in the review log output.

## Common pitfalls to avoid

These are patterns that have caused plan inaccuracies in past projects. Check for each one:

1. **Wrong migration directory** — Do not assume `backend/app/db/migrations/versions/`. This project uses `backend/alembic/versions/`. Always `ls` the actual path.
2. **Wrong Alembic head** — Check the actual versions directory, not `state.md` (which may be stale). Use the next sequential number.
3. **Router registration assumptions** — Read `backend/app/main.py` to see how routers are mounted. Don't assume prefix patterns.
4. **Frontend stories without reading the component first** — Never write a UI element inventory or state dependency analysis without reading the actual component file. Line counts, state variables, and section structures change frequently.
5. **"Follow the X pattern" without copying the markup** — Always include the actual JSX/CSS from the analogous section. References are ambiguous; copied code is unambiguous.
6. **Endpoint tables that don't match the spec** — The plan's endpoint tables must exactly match the spec's Section 8. If they diverge, the contract tests will be wrong.
7. **Stories that claim to modify files they don't need to** — Grep for actual usage before listing a file in "Modified files." False entries waste implementation time.
8. **Test tasks pointing at mocked E2E suites** — `study_detail.spec.ts` uses `page.route()` mocking. Anchor new E2E tasks to real-backend suites like `signup_flow.spec.ts`.
9. **Key interfaces that don't match existing layer conventions** — Repo functions take `db: Session` first. Services are async. Domain functions are pure (no DB, no async). Read the layer before writing signatures.
10. **Frontend data plumbing gaps** — If a story says "pass X as a prop," verify the parent component actually has X. This is the most common frontend plan failure.
11. **Missing plan-level UI Guidance section** — If any story has frontend scope, the plan MUST include a top-level "UI Guidance" section with actual JSX patterns, layout description, visual consistency table, interaction behavior table, and handler function code. Story-level UI element inventories are necessary but NOT sufficient — the plan-level section provides the unambiguous markup patterns that prevent implementation rework. This was the #1 failure mode on the Wave 2.0b plan.
12. **Persistence scope mismatch** — `localStorage` persists forever; `sessionStorage` clears on tab close. If the task says one and the DoD says the other, that's a bug in the plan.
13. **Gate arithmetic errors** — If a gate says "all 8 endpoints live" but the stories below only define 6, the gate is wrong.
14. **Invented enum / filter / dropdown values in frontend stories** — Frontend stories that define a `<select>`, filter dropdown, status badge, sort control, or any option list whose values are sent back to the backend MUST enumerate the exact wire values AND cite the backend source-of-truth file (enum, `frozenset`, `Literal[...]`, `Field(pattern=...)`, or DB CHECK). Grep the cited file to verify every option is real. Plans that only specify the user-facing labels (e.g., "Paused" without `paused` being in the backend's `StudyStatus` Literal) without the wire values and source file produce frontend bugs that TypeScript, lint, and unit tests will not catch — the bug only surfaces as a 422 VALIDATION_ERROR or a silent zero-result filter in the browser. Require a source-of-truth comment in the story's task list (e.g., `// Values must match backend/db/models/study.py StudyStatus`). This failure mode is documented from the sibling `creator-discovery-outreach` project (their PR #183 shipped four wrong allowlist values undetected).

15. **Missing Legacy Behavior Parity table on delete-and-replace stories** — When a story deletes or replaces a user-facing component >100 LOC, omitting the parity table is how client-side validations, inflight-disable states, and confirmation dialogs silently disappear. "TypeScript compiles" does not exercise a missing `minLength={20}` check or a button that re-fires while a POST is pending. This was the failure mode on the Setup IA overhaul (Story 4.1 deleted `PlatformsKeywordsTab` and dropped NL-description length validation + Run-discovery button inflight disable; both were caught post-hoc by Gemini).

## Review log

At the end, provide a summary:
- Mode used (Generate / Review / Reconcile / Review & Patch)
- Source spec referenced
- Number of review passes performed
- Verification ledger (material claims checked)
- Key inaccuracies found and corrected (or reported, in Review mode)
- Spec-plan alignment status (all FRs covered / gaps found)
- Any open questions that need user input
- Proposed doc updates (if any)
