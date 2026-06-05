---
name: spec-gen
pipeline-stage: 1
pipeline-role: idea → feature_spec.md
description: "Generate, review, or reconcile feature specifications. Use when: creating new feature specs, reviewing existing specs for accuracy, reconciling input briefs against specs, auditing planned feature docs, or patching spec inaccuracies. Trigger phrases: review existing feature spec, spec accuracy audit, reconcile feature brief, planned feature review, generate feature spec."
argument-hint: "[path(s): single file for Generate/Review/Review & Patch, or 'input.md spec.md' for Reconcile]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent
model: claude-opus-4-7
user-invocable: true
---

# Feature Specification Generator & Reviewer

You are working with feature specifications for the RelyLoop project. Depending on the mode, you either generate a new spec, review an existing spec for accuracy, or reconcile an input brief against an existing spec.

## Mode selection

Before starting, determine which mode applies based on the user's request and the argument provided:

| Mode | When to use | Writing behavior |
|---|---|---|
| **Generate** | User provides an input brief (markdown describing a feature to be specified). No spec exists yet. | Creates a new spec file. |
| **Review** | User provides a path to an existing spec. Asks for accuracy review, audit, or findings. | Returns findings only — does NOT rewrite the spec unless the user explicitly asks. |
| **Reconcile** | User provides both an input brief and an existing spec, or asks to align them. | Returns findings on mismatches and proposes specific edits, but does NOT apply them without approval. |
| **Review & Patch** | User provides a spec and explicitly asks to fix/correct/apply findings. | Applies corrections to the spec file. |

**Default to Review mode if ambiguous.** Only write files when the mode clearly requires it.

## Inputs

- **$ARGUMENTS**: One or two file paths depending on mode:
  - **Generate**: single path to the input brief (e.g., `docs/.../input.md`)
  - **Review / Review & Patch**: single path to the existing spec (e.g., `docs/.../feature_spec.md`)
  - **Reconcile**: two paths separated by a space — input brief first, then spec (e.g., `docs/.../input.md docs/.../feature_spec.md`)
- **Spec template**: `docs/00_overview/planned_features/feature_templates/feature-spec-template.md`
- **Project context**: `CLAUDE.md`, `architecture.md`, `state.md`

## Workflow — Generate mode

### Step 1: Gather context

Read these files to understand the project:

1. `CLAUDE.md` — project conventions, absolute rules, data model, stack
2. `architecture.md` — system design, boundaries, critical flows
3. `state.md` — current priorities, recent changes, known debt
4. `docs/00_overview/planned_features/feature_templates/feature-spec-template.md` — the output template
5. The user's input document at $ARGUMENTS

### Step 2: Generate initial spec

Using the template structure, fill in every section with concrete, specific content derived from:

- The user's input document (the "what" and "why")
- The codebase context (the "how" — existing patterns, conventions, data model, API shapes)

**Critical rules for spec generation:**

- **Every file path, table name, column name, endpoint, and function reference must be verified against the actual codebase.** Do not assume — grep/glob/read to confirm.
- **Error shapes must be verified per-route, not assumed globally.** This repo has mixed patterns: some routes return structured `detail` objects via `error_detail()` / `error_envelope()` (e.g., `keywords.py:96`), while others return plain-string `detail` (e.g., `keywords.py:62`). For each endpoint referenced in the spec: (1) read the route's error handling code, (2) check for a contract test that asserts on the response shape, (3) copy the exact shape found. Do not invent a universal envelope — verify per-route.
- **Auth patterns must be verified per-route.** Read the actual route function signature and its `Depends()` chain. Do not assume `get_current_auth` or `x-tenant-id` — many tenant routes use `require_tenant_membership`. Check the imports at the top of the router file.
- **API conventions must match existing routers.** Read actual router files to confirm prefix patterns, auth dependencies, return type annotations, and response shapes.
- **Return type annotations on routes determine response shape.** If a route returns `list[dict]`, the response example must be an array, not a bare object. Read the function signature.
- **Data model references must match the current ORM models.** Read `backend/app/db/models/` to verify column names, types, and relationships.
- **Pipeline stage references must match** `backend/app/domain/pipeline/stages.py`.
- **Quota/plan references must match** `backend/app/domain/quotas/`.
- **Never hardcode LLM model names** (e.g., "gpt-5.5-nano"). The LLM provider is resolved dynamically via `create_llm_provider()` in `backend/app/integrations/llm/factory.py`. Always reference the `LLMProvider` abstraction.
- **E2E test coverage claims must distinguish real-backend from mocked tests.** Do not cite `page.route()`-based Playwright tests as true end-to-end coverage. Classify them as "mocked UI regression coverage" or "existing test debt." When recommending new E2E coverage, anchor to real-backend suites like `signup_flow.spec.ts`.

### Step 3: Codebase accuracy review (Pass 1)

Systematically verify every claim in the spec against the codebase:

1. **File paths**: Glob for every file/directory referenced. Do they exist? Are the paths correct?
2. **Table/column names**: Read the ORM models for every table referenced. Do the columns exist with the stated types?
3. **API endpoints**: Read the router files. Do referenced endpoints exist? Are methods/paths correct? What is the return type annotation?
4. **Function names and behavior**: Grep for every function referenced. Does it exist? Is the signature correct? **Read the function body** for any function whose behavioral semantics are claimed in the spec (e.g., "create_study prevents overwriting"). Do not infer behavior from the function name alone.
5. **Domain rules**: Read domain layer files. Are transition rules, quota logic, and validation rules accurately described?
6. **Existing implementations (Section 2)**: Search for all existing code that the feature touches. Are there implementations the spec missed?
7. **Downstream consumers**: For every field being changed or added, grep for all code that *reads* that field — not just the code that writes it. A longer `Study.description` may affect digest prompt construction; an enriched `Judgment.rationale` may already be surfaced by the proposals UI. Missing downstream impact is a common spec failure.
8. **Navigation/link impact**: Search for URL references that will change.
9. **Test impact**: Search test files for references to affected pages/behaviors. Classify mocked Playwright tests (`page.route()`) as "mocked UI regression coverage" — not true E2E coverage. Prefer real-backend suites when recommending coverage.
10. **Information architecture (Section 11)**: If the feature adds UI, verify: (a) the spec's navigation placement matches the actual page structure in the codebase (read the relevant page/layout files), (b) labels in the spec match existing terminology (grep for similar labels to avoid inconsistency), (c) the spec defines where new elements sit relative to existing ones.
11. **Tooltips and contextual help (Section 11)**: If the feature adds settings, limits, status indicators, or actions with consequences, verify the spec includes a tooltip inventory **and that every entry cites either an existing glossary key (verifiable by `grep` of `ui/src/lib/glossary.ts`) or names a new key to be added in a specific story.** Tooltip text that doesn't trace back to the glossary source-of-truth reintroduces the drift risk that `feat_contextual_help` was designed to prevent. Check the existing codebase for tooltip patterns (`title` attributes, info icons, helper text) to confirm the spec's approach matches established patterns.
12. **Enumerated value contracts (Section 7.4 / §8)**: If the feature has filters, sort keys, status badges, role labels, or any other field the backend validates against a fixed allowlist, verify the spec enumerates the **exact wire values** (not just user-facing labels) for each field AND cites the backend source-of-truth file (enum, `frozenset`, `Literal[...]`, Pydantic `Field(pattern=...)`, or DB CHECK constraint). Grep the cited file to confirm every value is real and every real value is listed. If the spec contains plausible-sounding values without a source citation (e.g., a "Paused" status label with no grep target), flag it as a **High** severity finding — frontend option lists generated from unsourced spec values will drift and produce 422 VALIDATION_ERROR responses in production. This failure mode is documented from the sibling `creator-discovery-outreach` project (their PR #183 shipped four wrong allowlist values undetected).

Record every finding in the verification ledger (see below). Fix every inaccuracy found.

### Step 4: Architectural consistency review (Pass 2)

Review the spec for consistency with project architecture:

1. Does the spec respect all "Absolute Rules" from CLAUDE.md?
2. Does the data model follow conventions (tenant_id scoping, repo layer pattern, etc.)?
3. Does the API design follow conventions (auth patterns, error shapes, router structure)?
4. Are service layer patterns correct (job_run lifecycle, execution_id propagation, quota checks)?
5. Are migration requirements complete (downgrade, idempotency guards)?
6. Does the test strategy cover all required layers per project conventions?
7. **Invariant write-path audit**: For every new invariant stated in the spec (e.g., "`engine_version` must be set whenever `Result.score` is written"), grep for ALL existing code paths that write the related fields. If existing write paths would violate the new invariant after deploy, the spec must either: (a) include updating those write paths in scope, or (b) weaken the invariant to account for legacy behavior.
8. **Cross-feature dependencies**: If the spec references columns, tables, or behavior introduced by another planned feature, classify the dependency as **hard** (blocks implementation) or **soft** (works without, value reduced). Check the confirmed build order if known.
9. **Audit-event instrumentation** (MVP2+ — `audit_log` arrives at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../docs/01_architecture/data-model.md)). For MVP2+ specs: every endpoint or service function the spec adds or modifies that mutates state MUST populate the §6 "Audit-event instrumentation matrix" — choosing a new event type or citing an existing one, deciding visibility (system / tenant-visible), specifying metadata fields. RelyLoop's MVP2 audit-log is a single append-only `audit_log` table with a Postgres trigger blocking UPDATE/DELETE; no per-event-type allowlist machinery (the design is intentionally simpler than CDO's). If the spec proposes a mutation without addressing audit emission, that's a finding — flag as **High** severity. Forbidden in `metadata_json`: credentials, tokens, PII beyond display-name strings.

Record every finding in the verification ledger. Fix any inconsistencies.

### Step 5: Input/spec reconciliation

Compare the input document ($ARGUMENTS) against the generated spec:

1. Does the input document scope features that the spec marks as out-of-scope? If so, the input document should be updated to match (or the scope decision should be flagged as an open question).
2. Does the input document use specific model names, cost figures, or technical details that the spec has corrected? Update the input document for consistency.
3. Are there claims in the input document that the codebase audit disproved? Update or annotate them.

The input document and spec must not contradict each other — the input is the "brief," the spec is the "contract."

### Step 6: Cross-model review (Opus ↔ GPT-5.5)

This step is **mandatory** when the GPT-5.5 review mechanism is configured and callable in the current runtime. The external reviewer is **GPT-5.5** (model: `gpt-5.5` via the OpenAI API). This is not configurable — the cross-model value comes from using a different model family, not a different instance of the same model.

**API key resolution:**
The `OPENAI_API_KEY` is stored in the project `.env` file (not automatically available in the shell environment). To resolve it:
1. Parse the key: `grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-`
2. Use it in API calls via a Python script with `urllib.request` or `curl`, passing the key as a `Bearer` token in the `Authorization` header.
3. Do NOT attempt to check `$OPENAI_API_KEY` from the shell — `.env` files are not sourced into the shell environment by default.

**API call mechanism:**
Use a Python script (via the Bash tool) with `urllib.request` to call the OpenAI Chat Completions API (`https://api.openai.com/v1/chat/completions`). Send the spec text as the user message, with review instructions in the system message. Request structured JSON output for findings.

**Important GPT-5.5 API notes:**
- Model ID is `gpt-5.5` (not `gpt-5.5-high` or `gpt-5.5-pro`)
- GPT-5.5 requires `max_completion_tokens` instead of `max_tokens` — using `max_tokens` returns a 400 error. Omit the parameter entirely to use the model's default, or use `max_completion_tokens` if a limit is needed.

**Fallback if GPT-5.5 is unavailable** — see CLAUDE.md §"Cross-model review policy" → "Environment-aware fallback" (authoritative source; this block defers to it):
- **Claude Code remote sandbox — the common case here: GPT-5.5 is *expected*-unreachable** (no `OPENAI_API_KEY` and/or `api.openai.com` egress-blocked). This is a SANCTIONED standing condition, not an error. Proceed with **Opus self-review** (run the verification passes yourself) and state in the output: `cross-model review: Opus self-review (GPT-5.5 unreachable)`. It is a documented *degradation* — Gemini Code Assist remains the cross-family gate at the code/PR stage. To restore real GPT-5.5 review, enable egress + `OPENAI_API_KEY` per CLAUDE.md "Durable fix".
- If the `.env` file does not contain `OPENAI_API_KEY`: alert the user and proceed with Opus self-review (as above).
- If the API call fails (auth error, timeout, model not available): log the failure, alert the user, and proceed with Opus-only internal review passes. Do NOT silently skip the step — the user must be informed that cross-model review was skipped and why.
- If the user explicitly opts out (e.g., "skip external review"): proceed without it, but note in the review log that cross-model review was skipped by user request.

**Reviewer roles (both fulfilled by GPT-5.5):**

GPT-5.5 reviews in two labeled passes within a single prompt (or two separate calls):

| Role | Focus areas |
|---|---|
| **Pass A: Contract & Data** | API endpoint shapes, auth patterns, error envelopes, data model accuracy, column existence, return type annotations, cross-feature dependencies |
| **Pass B: Impact & Coverage** | Downstream field consumers, test coverage claims (real vs mocked), UX flow completeness, rollout risk, invariant write-path coverage, input/spec scope drift |

**Review protocol:**

1. Send the full spec text to GPT-5.5 with both role focus areas. Request findings as structured output: claim, evidence (file:line), severity (High/Medium/Low), reviewer pass (A or B).

   **On cycle 2 and later — include the rejection log from earlier cycles in the system prompt**, structured as:

   ```
   ## Previously rejected findings (do NOT re-raise without new information)

   The following findings were raised in prior cycles and rejected by Opus with
   cited counter-evidence. Unless you have *new* evidence that materially changes
   the analysis, omit these from your cycle-N response:

   - Cycle 1 finding #{N}: "{short quote of the claim}"
     Rejection: {one-line counter-evidence, with file:line}
   ...

   You may re-raise a listed finding ONLY if you have new information (a code
   change since last cycle, a corrected citation, a genuinely different angle).
   If you re-raise, state the new information explicitly in the `finding` field.
   "Disagreeing with the rejection" is not new information.
   ```

   This prunes repeat findings. A repeats-only response in cycle N is valid — the convergence stop rule (Step 7) treats it as a clean pass without forcing another cycle.

2. **Opus adjudication:** For each GPT-5.5 finding, Opus must do one of:
   - **Accept** — cite the evidence, stage the correction for the findings gate (Step 8). Log in the verification ledger.
   - **Reject** — cite counter-evidence from the codebase (file:line) that disproves the finding. Log the rejection with the counter-evidence.
   - **Escalate** — if evidence is ambiguous or the finding requires a product decision, flag as an open question for the user.
3. Rejections without cited counter-evidence are not allowed. "I disagree" is not sufficient — show the code.

**Important:** Accepted corrections from the cross-model review are **staged, not applied immediately**. Major accepted corrections require user approval at the findings gate (Step 8) before being written. Minor accepted corrections may be applied without gating.

### Step 7: Cross-model convergence loop

After Opus adjudicates GPT-5.5 findings, determine whether another GPT-5.5 review cycle is needed:

**Re-review trigger:** If any accepted correction changed a **major** element (API contract, data model, auth pattern, error shape, invariant, acceptance criteria, or cross-feature dependency), send the corrected spec back to GPT-5.5 for a fresh review pass. Apply minor corrections before re-submitting so GPT-5.5 reviews the most current version.

**Cross-model loop stop rules:**
- **Stop** when GPT-5.5 reports no new High-severity findings AND Opus has no unresolved accepted changes.
- **Stop** when GPT-5.5 returns only findings that Opus has already rejected with cited counter-evidence in a previous cycle (no new information).
- **Stop** after a maximum of 3 Opus ↔ GPT-5.5 cycles. If convergence is not reached by cycle 3, present the remaining disagreements to the user for resolution.

**Internal convergence (Opus-only):** After the cross-model loop completes, Opus may run additional internal review passes (Steps 3–4) if needed:
- If two consecutive Opus-only passes produce only wording or formatting edits, stop.
- Maximum 2 additional Opus-only passes after the cross-model loop.

**Convergence criteria** (applies to both cross-model and internal passes): A pass is "clean" if it produces no changes to:
- Table/column definitions
- API endpoint definitions or response shapes
- Domain rules or state transitions
- Security or authorization model
- Acceptance criteria
- Required invariants or their write-path coverage

### Step 8: Findings gate

Before writing any files, classify all staged findings and corrections (from both Opus internal passes and GPT-5.5 cross-model review) into:

- **Major** (High severity): Changes to API contracts, data model, auth patterns, error shapes, invariants, acceptance criteria, or cross-feature dependencies. These change what gets built.
- **Minor** (Medium/Low severity): Wording, formatting, documentation consistency, cost estimates, non-functional details. These improve clarity but don't change the implementation contract.

**Gate rules:**
- **Major findings**: Present to the user for confirmation before applying. List each finding with its source (Opus internal or GPT-5.5 pass A/B) and the proposed correction. Do not write files until the user approves.
- **Minor findings**: May be applied without explicit confirmation, but include them in the review log so the user can see what changed.
- If there are no major findings, proceed directly to writing.

### Step 9: Write the spec

Write the final spec to the appropriate location:
- Default: `docs/00_overview/planned_features/<bucket>/` with a descriptive filename — `<bucket>` is the MVP grouping the feature belongs to (`00_unsure/`, `01_mvp1/`, `02_mvp2/`, `03_mvp3/`, `04_ga/`, `99_backlog/`). When unsure, default to `00_unsure/` and promote later.
- Ask the user if they have a preferred location/filename

### Step 10: Track deferred phases

**This step is MANDATORY when the spec defines multiple phases.** Deferred phases contain scoped, reviewed work that will be lost if not explicitly tracked as a separate artifact. The spec is where phases are *first defined* — this is the most important place to capture them.

1. Read the spec's "Phase boundaries" section. List every phase beyond Phase 1 with its FRs.
2. For each deferred phase, check whether a tracking file already exists (`glob` for `*idea*.md` or `*phase*_idea.md` in the feature directory).
3. If no tracking file exists, create one at `docs/00_overview/planned_features/<bucket>/<feature_dir>/phase<N>_idea.md` (in the same bucket as the parent feature) following the idea template (`docs/00_overview/planned_features/feature_templates/idea-template.md`). Include:
   - Origin pointer to the spec file and line numbers where the deferred FRs are defined
   - The deferred FRs with enough context to generate a future implementation plan
   - Why the work was deferred (from the spec's phase boundary rationale)
   - Dependencies on the earlier phase(s)
4. Commit the tracking file with the spec.

**Why this matters:** Spec phase boundaries represent reviewed, scoped work. Without an explicit tracking artifact, deferred phases exist only as prose inside the spec and are effectively invisible to future planning sessions. The `impl-plan-gen` and `impl-execute` skills also enforce this at their respective stages, but the spec is the first line of defense.

### Step 11: Update project docs

Evaluate whether these files need updates based on the new spec:

- `state.md` — if this feature changes priorities or adds planned work
- `architecture.md` — if this feature introduces new services, data flows, or integrations
- `CLAUDE.md` — if this feature adds new conventions, rules, or environment variables

Present proposed doc updates to the user for approval before writing.

### Step 12: Update pipeline status

**This step is MANDATORY in Generate mode.** Write or update a `pipeline_status.md` file in the feature directory to record the spec stage completion. This file enables the `/pipeline` orchestrator to detect what stage a feature is at and resume automatically.

Write to `docs/00_overview/planned_features/<bucket>/<feature_dir>/pipeline_status.md`:

```markdown
# Pipeline Status — <Feature Name>

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: <YYYY-MM-DD>
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (<N> cycles)
- Phases: <N total, N covered by spec>

## Plan
- Status: Not started

## Implementation
- Status: Not started
```

If `pipeline_status.md` already exists (e.g., from a prior stage), update only the `## Spec` section — do not overwrite other sections.

### Step 13: Sync the tracking issue (if one exists)

**Generate mode only.** A folder may have a GitHub tracking issue mirroring it (the issue-coverage sweep). If so, keep it in step with the new spec per [`docs/00_overview/planned_features/feature_templates/tracking-issue-template.md`](../../../docs/00_overview/planned_features/feature_templates/tracking-issue-template.md):

1. Find it: `gh issue list --state all --limit 300 --json number,title --jq '.[] | select(.title|startswith("<feature-dir-slug>:")) | .number'` (anchored `startswith` — a bare `test()` substring-matches longer slugs). If none, skip (the `/pipeline` orchestrator owns creation).
2. Flip `Stage → SPEC`, **leave the stage label as `needs-preflight`** (it advances to `ready-to-execute` only at the PLAN stage, once the plan exists — `ready-to-execute` means spec+plan both present; or `blocked` if a `Blocked by:` gate is unmet), add the Spec artifact link, and backfill the inline DoD from the spec's acceptance criteria — replacing any "lives in the linked artifact" placeholder.
3. Re-verify any `file:line` you write into the issue against the current tree; never propagate stale artifact citations.

---

## Workflow — Review mode

When reviewing an existing spec (not generating a new one):

1. **Gather context**: Read `CLAUDE.md`, `architecture.md`, `state.md`, and the spec at $ARGUMENTS.
2. **Run Pass 1 and Pass 2** (Steps 3–4 above) against the existing spec.
3. **Build the verification ledger** for every material claim.
4. **Deferred phase audit**: If the spec defines multiple phases, check whether each deferred phase has a tracking artifact (`glob` for `*idea*.md` or `*phase*_idea.md` in the feature directory). Report any untracked deferred phases as a **Medium** finding: "Phase N defines FRs X-Y but has no tracking file — deferred work will be invisible to future planning."
5. **Cross-model review (optional but recommended):** If GPT-5.5 is available, send the spec for external review using the same protocol as Generate mode Step 6. This strengthens the audit by catching blind spots in the primary model's review. If unavailable, note in the review log.
6. **Return findings only.** Do not rewrite the spec. Present findings (from both Opus and GPT-5.5 if applicable) as:
   - Severity (High / Medium / Low)
   - Source (Opus internal / GPT-5.5 Pass A / GPT-5.5 Pass B)
   - Location (file:line)
   - What the spec claims vs. what the codebase shows
   - Suggested correction (if straightforward)
7. **Flag open questions** that need the user's input to resolve.

---

## Workflow — Reconcile mode

When reconciling an input brief against an existing spec:

1. **Read both documents** and the project context files.
2. **Diff scope**: List every capability the input promises that the spec marks out-of-scope (and vice versa).
3. **Diff technical claims**: List every technical detail (model names, cost figures, field names, API shapes) where the input and spec disagree.
4. **Deferred phase audit**: If the spec defines multiple phases, check whether each deferred phase has a tracking artifact. Flag untracked deferred phases in the alignment report.
5. **Return the diff** with a recommendation for each mismatch: update input, update spec, create tracking file, or flag as open question.

---

## Workflow — Review & Patch mode

When the user provides findings or explicitly asks to fix/correct an existing spec:

1. **Gather context**: Read `CLAUDE.md`, `architecture.md`, `state.md`, and the spec at $ARGUMENTS.
2. **Verify each finding** against the codebase. For each finding:
   - Read the referenced code to confirm the finding is accurate.
   - Record in the verification ledger as Verified, Partially Correct, or Incorrect.
   - If incorrect, cite counter-evidence (file:line).
3. **Classify findings** into Major and Minor (see Findings gate in Generate mode).
4. **Present Major findings** to the user with proposed corrections. Wait for approval.
5. **Apply approved corrections** to the spec file. Apply Minor corrections without gating.
6. **Run a single verification pass** (Steps 3–4 from Generate mode) on the patched spec to confirm corrections didn't introduce new issues.
7. **Update the input document** if corrections affect scope, technical claims, or cost figures that the input also states.
8. **Return the verification ledger** and a summary of what was changed.

---

## Output format

The spec must follow the template structure exactly. Every section must be filled in — use "N/A" with a brief reason only if a section genuinely does not apply.

## Verification ledger

For every material claim in the spec (API shapes, column existence, auth patterns, function behavior, test coverage, error shapes), maintain a ledger:

| Claim | Verified by | Status |
|---|---|---|
| `studies.description` is `sa.Text`, nullable | Read `backend/app/db/models/study.py:XX` | Verified |
| `create_study()` prevents non-null overwrites | Read `backend/db/repo/study_repo.py:36-49` — only guards `None` | **Corrected** — spec updated |
| `study_detail.spec.ts` provides live-trials-table E2E coverage | Read file — uses `page.route()` mocking | **Corrected** — reclassified as mocked UI debt |

Include the ledger in the review log output. This makes the review trustworthy and auditable.

## Common pitfalls to avoid

These are patterns that have caused spec inaccuracies in the past. Check for each one:

1. **Error shapes assumed globally** — This repo has mixed error patterns (structured `detail` objects and plain strings). Verify per-route by reading the handler and any contract test, not by assuming one global envelope.
2. **Assuming auth mechanism** — Don't write `x-tenant-id` header or `get_current_auth` without reading the actual route's `Depends()` chain. Most tenant routes use `require_tenant_membership`.
3. **Claiming repo-layer guards that don't exist** — If you say "create_study prevents X," read the function body to confirm. The guard may only cover `None` values, not all overwrites.
4. **Missing downstream field consumers** — When changing a field's content (e.g., longer description), search for every place that field is read, not just where it's written. Digest prompt construction, API serializers, and frontend renders may all be affected.
5. **Citing mocked Playwright tests as E2E coverage** — Any `page.route()` in E2E tests is mocked UI regression coverage, not true end-to-end coverage. Prefer real-backend suites like `signup_flow.spec.ts`.
6. **Response shape mismatch (object vs array)** — Check the route's return type annotation. `list[dict]` means the example must be `[{...}]`.
7. **Hardcoded LLM model names** — Always reference `LLMProvider` abstraction and `create_llm_provider()`, never a specific model.
8. **Unstated invariant violations** — When adding a new invariant, trace every existing write path. If the engine adapter writes `Result.score` without `engine_version`, the invariant is violated on day one.
9. **Input doc / spec scope drift** — The input doc may promise features the spec marks out-of-scope. Reconcile before finalizing.
10. **Invented enum / filter / dropdown values** — Specs that name filter options, sort keys, status badge variants, tier labels, or any other field the backend validates against a fixed allowlist MUST cite the backend source-of-truth file. If a value appears in the spec without a grep target, assume it was invented. Phantom values (e.g., "mid" tier when the backend only produces nano/micro/macro/mega) produce 422 errors or silent zero-result filters in production — TypeScript and unit tests do not catch them. Require §7.4 "Enumerated value contracts" for every feature with filters/dropdowns.

## Review log

At the end, provide a summary:
- Mode used (Generate / Review / Reconcile / Review & Patch)
- Number of review passes performed
- Verification ledger (material claims checked)
- Key inaccuracies found and corrected (or reported, in Review mode)
- Any open questions that need user input
- Proposed doc updates (if any)
