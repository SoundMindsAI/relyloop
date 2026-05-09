---
name: impl-execute
pipeline-stage: 3
pipeline-role: implementation_plan.md → code + PR + CI
description: "Execute implementation plans story-by-story with enforced verification gates, cross-model code review, and progress tracking. Use when: implementing stories from an approved plan, executing a plan step by step, running a story with verification, or resuming implementation. Also supports an ad-hoc ship mode for small bug fixes / refactors that don't warrant /pipeline scaffolding — runs only the pre-push gate + PR ceremony + Gemini adjudication against changes already on the feature branch. Trigger phrases: execute implementation plan, implement story, run story, execute plan, resume implementation, implement next story, execute all stories, ship this change, take this through review."
argument-hint: "[path to implementation_plan.md] [optional: story ID like '1.1' | '--all' for batch mode] | --ad-hoc (no plan; ship pending changes through review/merge ceremony)"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, Agent, WebFetch, WebSearch, TodoWrite
model: claude-opus-4-7
user-invocable: true
---

# Implementation Plan Executor

You execute implementation plans for the RelyLoop project. Every story follows a prescribed workflow with mandatory verification gates. Code quality is enforced by lint/typecheck/test gates and cross-model code review via GPT-5.5.

## Inputs

- **Implementation plan path:** The path to the approved `implementation_plan.md` (omit when invoked with `--ad-hoc`).
- **Optional second argument:**
  - Story ID (e.g., `1.1`) — start at or resume from a specific story
  - `--all` — batch mode: execute all remaining incomplete stories automatically
  - Omitted — interactive mode: execute the next incomplete story, then pause for user direction
- **Ad-hoc mode:** invoke as `/impl-execute --ad-hoc` with no plan path. Requires changes already committed on a feature branch (the skill ships them through the standard review/merge ceremony — no story execution).
- **Project context:** `CLAUDE.md`, `architecture.md`, `state.md` (read before starting)

## Execution modes

| Mode | Invocation | Behavior |
|---|---|---|
| **Interactive** (default) | `/impl-execute path/to/plan.md` | Execute next incomplete story, report results, wait for user |
| **Resume** | `/impl-execute path/to/plan.md 2.1` | Start at story 2.1, then pause after completion |
| **Batch** | `/impl-execute path/to/plan.md --all` | Execute all remaining stories sequentially. Run phase gates between phases. Escalate to user ONLY on gate failures, manual steps, or ambiguous decisions. Report progress via TodoWrite. |
| **Ad-hoc** | `/impl-execute --ad-hoc` | No plan, no story execution. Runs ONLY the post-implementation ceremony (pre-push gate → push → PR → CI watch → Gemini adjudication → optional GPT-5.5 review → post-merge cleanup) against changes already committed to the current feature branch. For small bug fixes / refactors / Gemini-feedback follow-ups that don't warrant `/pipeline` scaffolding. See "Ad-hoc mode behavior" below. |

### Batch mode behavior

In batch mode, the executor loops through all incomplete stories:

```
for each incomplete story:
    1. Execute the story (Steps 1-8 from story execution workflow)
    2. If verification gate fails → STOP, escalate to user
    3. If story requires manual steps → STOP, guide user, wait for confirmation
    4. If all stories in a phase are now complete → run phase gate
    5. If phase gate fails → STOP, escalate to user
    6. Continue to next story

after all stories complete:
    1. Run test coverage audit (compare plan's testing workstream against written tests)
    2. Seed the post-implementation TodoWrite with ALL of these items (NOT optional — every
       item must be tracked before any post-impl work begins, so none are implicitly skipped):
          - Extract deferred work (Step 1)
          - Documentation updates (Step 2)
          - Tangential observations sweep (Step 2.5) — BLOCKING; capture every noticed-but-uncaptured issue per CLAUDE.md tangential-discoveries rule
          - Guide impact assessment + guide-gen run (Step 3) — MANDATORY gate
          - Push + open PR (Step 4)
          - Monitor CI (Step 5)
          - Adjudicate Gemini review (Step 6)
          - Final cross-model review (Step 7)
          - Finalize: verify completion, move to implemented_features (Step 8)
    3. Run each post-implementation step, marking the todo complete as you go
    4. Run finalization (Step 8: verify completion, update docs, move to implemented_features)
    5. Report final status to user
```

**Batch mode escalation rules:**
- **Always stop for:** verification gate failure, manual configuration steps, ambiguous implementation decisions, test failures that aren't obviously fixable
- **Never stop for:** successful story completion, lint auto-fixes, formatting changes, routine progress updates
- **Progress reporting:** Update TodoWrite after each story. The user can check progress at any time without interrupting execution.

### Ad-hoc mode behavior

Ad-hoc mode (`/impl-execute --ad-hoc`) is for changes that don't warrant `/pipeline` scaffolding: small bug fixes, refactors, Gemini-feedback follow-ups, infra-sweep PRs that combine 2–3 unrelated tiny fixes, etc. Anything where writing a `feature_spec.md` and `implementation_plan.md` would be more ceremony than the change itself.

**Preconditions (skill verifies before running):**
- Current branch is NOT `main` (CLAUDE.md rule). If on main, ad-hoc mode aborts with a prompt to create a feature branch first.
- The branch has at least one commit ahead of `origin/main` OR uncommitted-but-staged changes worth shipping. If the working tree is clean and the branch is up to date with main, abort with "nothing to ship."
- The user has already done the actual code work — ad-hoc mode does not implement; it ships.

**What ad-hoc mode SKIPS** (compared to plan-driven invocation):
- All of "Pre-execution setup" Step 3 (parse plan) and Step 4 (TodoWrite from stories) — there is no plan.
- The entire **Story execution workflow** (Steps 1–8 per story). No story loop runs.
- Post-implementation Step 0b (test coverage audit against the plan).
- Post-implementation Step 1 (extract deferred work from spec phases).
- Post-implementation Step 8 sub-steps that touch plan/pipeline_status/folder-move (`pipeline_status.md` update, `implementation_plan.md` status flip, folder move to `implemented_features/`). For ad-hoc fixes there is no folder to move.

**What ad-hoc mode KEEPS** (the value of running this skill instead of doing it by hand):
- Pre-execution setup Step 1 (read CLAUDE.md, architecture.md, state.md) and Step 2 (check branch state).
- Post-implementation Step 0a (worktree pre-flight — surfaces locked sibling worktrees that would block branch ops in Step 8 finalization or Step 9 cleanup; same risk applies to ad-hoc fixes).
- Post-implementation Step 0b.1 (audit-event coverage audit — small fixes can still introduce new tenant-visible mutations).
- Post-implementation Step 2 (`state.md` update if completion-snapshot or active-priorities changed; only if applicable).
- Post-implementation Step 2.5 (**tangential-observations sweep — BLOCKING**). Bug fixes routinely surface unrelated bugs; capture them as idea files before push.
- Post-implementation Step 3 (guide impact assessment — MANDATORY GATE if frontend was touched).
- Post-implementation Step 4 (push + `gh pr create` with the standard Summary / Test plan template).
- Post-implementation Step 5 (CI watch).
- Post-implementation Step 6 (Gemini Code Assist adjudication with the four-quadrant rubric — accept/reject/defer/escalate; this is the highest-value piece for small fixes since drive-by bugs often slip past human review without the discipline).
- Post-implementation Step 7 (**OPTIONAL** — final cross-model review). Default to skipping for changes ≤30 LOC across ≤3 files; require for anything larger or anything touching `studies`, `judgments`, the engine adapter, the GitHub PR worker, or migrations. **In ad-hoc mode, the review is performed against CLAUDE.md rules + relevant architecture docs (`docs/01_architecture/`) + the actual diff (no `implementation_plan.md` exists to seed the system prompt).** The skill prompts the user when the diff threshold is crossed and confirms the review-input swap.
- Post-implementation Step 9 (post-merge local cleanup).

**Recommended PR-body shape for ad-hoc mode:**

```markdown
## Summary
<what changed and why — 1–3 bullets, plain prose>

## Test plan
- [x] <relevant tests run locally>
- [x] make lint && make typecheck (or web-side equivalents)
- [ ] <staging verification if applicable>
```

No "Test coverage" section (no plan to compare against). No "Idea file" section unless one exists for the change.

**When NOT to use ad-hoc mode:**
- The change introduces a new feature surface that future work will extend → use `/pipeline` so a spec exists for the next contributor.
- The change touches >5 files OR >100 LOC of non-test code → use `/pipeline` so phase gates and per-story commits run.
- The change requires a migration → use `/pipeline` so the spec captures the migration's downgrade + idempotency-guard discipline.
- The change introduces or modifies an absolute rule's surface (audit events, webhook idempotency, quota enforcement, pipeline stage transitions, etc.) → use `/pipeline` so the spec captures the rule compliance explicitly.

If the user invokes `/impl-execute --ad-hoc` for a change that hits any of the above, the skill flags it and asks whether to proceed anyway or fall back to `/pipeline`.

## Pre-execution setup

Before executing the first story:

1. **Read context files** in order:
   - `CLAUDE.md` — project conventions, absolute rules
   - `architecture.md` — system design, boundaries
   - `state.md` — current branch, Alembic head, active priorities
   - The implementation plan at the provided path

2. **Check branch state:**
   - Verify current branch (never commit to main — CLAUDE.md rule)
   - If on main, create a feature branch before proceeding
   - If a feature branch already exists for this plan, switch to it
   - Run `git status` to check for uncommitted changes

3. **Parse the plan:**
   - Identify all stories and their completion status from the execution tracker
   - Find the first incomplete story (or the story specified by the user)
   - Read the story's full scope: outcome, new/modified files, endpoints, key interfaces, tasks, DoD

4. **Set up progress tracking:**
   - Use TodoWrite to create a task list from the plan's stories
   - Mark already-completed stories as done

---

## Story execution workflow

> **Ad-hoc mode:** skip this entire section. Ad-hoc mode has no stories. Jump directly to "Post-implementation" below, starting at Step 0a (worktree pre-flight) — locked sibling worktrees can block Step 8/Step 9 branch ops just as easily for ad-hoc fixes as for plan-driven work, so the pre-flight runs first.

For each story, execute these steps **in order**. Each step is a hard gate — do not proceed to the next step if the current one fails.

### Step 1: Read and confirm scope

1. Read the story from the implementation plan
2. List: outcome, new files, modified files, endpoints (if any), key interfaces (if any)
3. Verify modified files still exist at the claimed paths (`glob` each one)
4. If the plan references line numbers, verify they are approximately correct (within ~20 lines)
5. Inform the user which story you are implementing and what it does

### Step 2: Implement backend changes

Order of operations (backend stories):
1. **Models** — add/modify ORM model columns
2. **Migration** — create Alembic migration if schema changed
3. **Repo** — add/modify repository functions
4. **Domain** — add/modify pure domain logic
5. **Service** — add/modify service layer functions
6. **Router/Schemas** — add/modify API endpoints and Pydantic schemas
7. **Config** — add settings fields, update `.env.example`

For each file change:
- Read the file first (never edit without reading)
- Make the minimal change described in the story
- Do not add features, refactors, or improvements beyond the story scope

### Step 3: Backend verification gate

**All of these must pass before proceeding.** If any fail, fix the issue and re-run.

```bash
make fmt                                  # ruff format (auto-fix) — run FIRST so the
                                          # subsequent checks see the canonical form
make lint                                 # ruff check
make typecheck                            # mypy
./.venv/bin/ruff format --check backend/  # CI parity — `ruff format --check` is exactly
                                          # what CI's "Format check (ruff)" job runs. If
                                          # this fails *after* `make fmt`, some file is
                                          # excluded from fmt scope; fix the config before
                                          # continuing, don't edit-around it.
```

Then run the targeted test layer:
```bash
make test-unit                    # always
make test-integration             # if story touches DB, services, or endpoints
make test-contract                # if story adds/modifies endpoints
```

If the story includes a migration:
```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head  # round-trip
```

**Operator-path verification — MANDATORY for any story that adds or modifies an operator surface.**

If the story added or changed any of the following, you MUST run the actual command end-to-end from the documented operator environment before marking the story complete. `make test-unit` and lint/typecheck passing are necessary but **not sufficient** — they cannot detect bugs in container plumbing, env-var propagation, image cache freshness, mounted-secret handling, alembic post-write hooks, Compose dependency ordering, or any other integration-boundary issue.

| Surface added/changed | Verification you must run |
|---|---|
| New `Makefile` target | Run the target end-to-end (`make <target>`); confirm exit 0 + observable side effect |
| New / modified `scripts/install.sh` (or any install/bootstrap script) | Run the script from a clean state; re-run to verify idempotency |
| Compose service / volume / healthcheck | `make up` (or `docker compose up -d`); `docker compose ps` shows the affected container healthy; targeted probe of the changed surface (e.g., `curl /healthz`, `docker compose exec <svc> <cmd>`) |
| Dockerfile change (new layer, deps, ENV) | Rebuild the image; run a smoke command in the resulting container |
| Migration via `make migrate` / `make migrate-create` | Run the actual `make` target; confirm the file landed at the expected host path with the expected revision ID format |
| Endpoint exposed publicly (FastAPI router, Compose port, etc.) | Hit the endpoint from the documented client environment (host shell, browser, sibling container) and confirm response shape |

**Why this gate exists** (canonical incident, infra_foundation PR #4 first-run testing, 2026-05-09): five integration-boundary bugs shipped through CI green and surfaced in the first 30 minutes of operator first-run testing — a stale image missing a Python dep, a stub secret without a driver prefix, two Make targets that assumed env vars only present in CI, and an alembic post-write hook that crashed inside the runtime image (no dev deps). Every one would have been caught by literally running `make up` once before declaring stories complete. CI's hermetic test layers cannot substitute for end-to-end operator-path execution. See [`docs/02_product/planned_features/infra_ci_smoke_makeup/idea.md`](../../../docs/02_product/planned_features/infra_ci_smoke_makeup/idea.md) for the systemic CI follow-up.

If you cannot run the operator-path verification (e.g., no Docker daemon available in the agent environment), **escalate to the user** rather than skip — do not silently mark the story complete.

**Hard stop:** Do not proceed to frontend or commit if any check fails — including the operator-path verification.

### Step 4: Implement frontend changes (if story has frontend scope)

1. Read the UI Guidance section of the implementation plan
2. Read the target component file(s) before editing
3. Implement the changes described in the story, using the JSX patterns from the UI Guidance section
4. **Implement tooltips and contextual help** — if the plan's UI Guidance includes a tooltip inventory, implement every tooltip listed. Use the exact text and markup pattern from the plan. Do not skip tooltips — they are part of the feature, not decoration.
5. **Verify IA placement** — confirm the new UI element appears in the correct navigation position (tab order, section order, sidebar placement) as specified in the plan's IA placement subsection.
6. **Grep-against-source for every option list / enum / dropdown** — before finalizing any component that renders a `<select>`, filter chip, status badge, sort control, or any array of `{value, label}` options whose wire value is sent back to the backend:
   - Identify the backend allowlist the values must match (cited in the plan's UI inventory or the spec's §7.4 "Enumerated value contracts").
   - `Grep` the cited backend file to enumerate the exact allowed values.
   - Compare character-for-character: every `value` in the frontend array must exist in the backend allowlist; every backend value the user should be able to select must appear in the frontend array.
   - Add a source-of-truth comment above the array pointing at `backend/<path>:<symbol>` so future edits don't drift (e.g., `// Values must match backend/db/models/study.py StudyStatus`).
   - If the plan omitted the backend source citation, STOP and update the plan before implementing — do not guess a plausible allowlist. This failure mode is documented from the sibling `creator-discovery-outreach` project (their PR #183 shipped four wrong allowlist values undetected).
7. Verify TypeScript compiles: `npx tsc --noEmit`
8. If the plan specifies analogous markup, use it — do not invent new patterns

### Step 5: Frontend verification gate (if frontend was touched)

```bash
npx tsc --noEmit                           # TypeScript check
npx next build                              # Full build (catches SSR issues)
```

If E2E tests are scoped for this story:
```bash
npx playwright test tests/e2e/<test_file>.spec.ts --reporter=line
```

**Hard stop:** Do not commit if TypeScript or build fails.

### Step 6: Write tests

Write tests required by the story's DoD and the plan's testing workstream:

- **Unit tests** — pure function tests, parametrized where appropriate
- **Integration tests** — DB-backed, using `db_session` + `client` fixtures from conftest
- **Contract tests** — response shape assertions, auth gating, error code verification
- **E2E tests** — Playwright, real backend (no `page.route()` mocking), **must use browser interactions** via `page` (navigate, fill forms, click buttons, assert DOM). API `request` is for test setup only — assertions must verify browser-visible behavior. Pattern: setup via API helpers → seed localStorage with real tokens via `addInitScript` → interact via `page`.

Follow existing test patterns in the codebase:
- Unit: `backend/tests/unit/domain/` — see `test_quota_enforcement.py` for style
- Integration: `backend/tests/integration/` — see `test_billing_integration.py` for style
- Contract: `backend/tests/contract/` — see `test_billing_overage_status_contracts.py` for style
- E2E: `web/tests/e2e/` — see `signup_flow.spec.ts` for the canonical real-browser pattern

Run the tests:
```bash
make lint                                      # re-check after test files added
.venv/bin/pytest <test_file> -v --tb=short     # targeted run
```

### Step 6b: Parallel test agents (optional optimization)

When a story requires tests across multiple layers (unit + integration + contract + E2E), the test layers can be written in parallel using worktree agents. Each test layer is independent — they test the same code but don't share files or state.

**When to use parallel agents:**
- Story requires 3+ test layers
- Each layer has a clear test file path and pattern from the testing workstream
- The code under test is committed and stable (tests read, don't write, the implementation)

**When NOT to use parallel agents:**
- Story requires only 1-2 test files (overhead exceeds benefit)
- Tests have dependencies on each other (e.g., integration test creates data that E2E test reads)
- Frontend code is still in flux (E2E tests will break on UI changes)

**Pattern:**

```
# Launch up to 4 agents in parallel, each in an isolated worktree
Agent({
  description: "Unit tests for story X.Y",
  subagent_type: "general-purpose",
  isolation: "worktree",
  prompt: "Write unit tests for [feature] in backend/tests/unit/domain/test_[name].py.
    Follow the pattern in test_quota_enforcement.py. Test: [list of behaviors].
    Run: .venv/bin/pytest backend/tests/unit/domain/test_[name].py -v --tb=short
    The code is already implemented on this branch. Read it first."
})

Agent({
  description: "Integration tests for story X.Y",
  subagent_type: "general-purpose",
  isolation: "worktree",
  prompt: "Write integration tests for [feature] in backend/tests/integration/test_[name].py.
    Follow the pattern in test_billing_integration.py. Use db_session + client fixtures from conftest.
    Test: [list of behaviors including endpoint calls].
    Run: .venv/bin/pytest backend/tests/integration/test_[name].py -v --tb=short"
})

Agent({
  description: "Contract tests for story X.Y",
  subagent_type: "general-purpose",
  isolation: "worktree",
  prompt: "Write contract tests for [feature] in backend/tests/contract/test_[name]_contracts.py.
    Follow the pattern in test_billing_overage_status_contracts.py. Assert response shapes, auth, error codes.
    Run: .venv/bin/pytest backend/tests/contract/test_[name]_contracts.py -v --tb=short"
})

Agent({
  description: "E2E tests for story X.Y",
  subagent_type: "general-purpose",
  isolation: "worktree",
  prompt: "Write E2E tests for [feature] in web/tests/e2e/[name].spec.ts.
    Follow the pattern in admin_console.spec.ts. Use seedAdminSession or createAdminTenant helpers.
    No page.route() mocking — tests run against real backend at localhost:4800.
    Run: npx playwright test tests/e2e/[name].spec.ts --reporter=line"
})
```

**After agents complete:**
1. Each agent returns its test file content and pass/fail result
2. If any agent's tests fail, review the failure before merging
3. Collect all test files from worktree agents into the main branch
4. Run `make lint` on the collected test files (agents may not match formatting)
5. Run the full targeted test suite to verify everything works together:
   ```bash
   .venv/bin/pytest backend/tests/unit/domain/test_[name].py \
     backend/tests/integration/test_[name].py \
     backend/tests/contract/test_[name]_contracts.py -v --tb=short
   ```

**Important:** Parallel agents are an optimization, not a requirement. If the story only needs a few tests, write them inline (Step 6) instead. The overhead of spawning agents is only worth it for 3+ independent test files.

### Step 7: Commit

1. Stage only the files listed in the story's "New files" and "Modified files" tables, plus test files
2. Verify nothing unexpected is staged: `git diff --cached --stat`
3. Commit with a descriptive message referencing the story:

```bash
git commit -m "$(cat <<'EOF'
feat(<scope>): <summary> (Story X.Y)

<bullet points of key changes>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Step 8: Update progress

1. Mark the story as complete in the implementation plan's execution tracker (`[x]`)
2. Update TodoWrite task list
3. Inform the user: story complete, what was done, what's next

---

## Phase gate workflow

When all stories in a phase are complete, execute the phase gate:

### Step 1: Full test suite

```bash
make test-unit
make test-integration
make test-contract
make lint
make typecheck
```

If frontend was touched in this phase:
```bash
npx tsc --noEmit
npx playwright test tests/e2e/<relevant_specs> --reporter=line
```

### Step 2: Cross-model code review (GPT-5.5)

**This step is MANDATORY.** The cross-model review catches implementation drift from the plan.

**What to review:** The cumulative `git diff` for the phase (all story commits since the phase started).

**API call setup:**
1. Parse the API key: `grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-`
2. Generate the diff: `git diff <phase_start_commit>..HEAD`
3. Send to GPT-5.5 with the implementation plan as context

**Review prompt for GPT-5.5:**

```
You are reviewing code changes against an implementation plan. The diff shows
what was actually implemented. The plan shows what SHOULD have been implemented.

Check for:
1. Plan drift — code that diverges from the plan's key interfaces, endpoint
   tables, or data model
2. Missing implementations — plan items that don't appear in the diff
3. Unplanned changes — code changes not described in any story
4. Test coverage gaps — stories with DoD test requirements that have no
   corresponding test in the diff
5. Security concerns — auth bypass, missing tenant_id scoping, unsanitized input
6. Convention violations — direct OpenAI/Optuna/engine-client calls bypassing
   the configured abstractions (`LLMProvider`, `EngineAdapter`,
   `OptimizerService`), missing error handling, mutable state outside the
   domain layer

Return findings as JSON: {"findings": [{"severity": "High/Medium/Low",
"file": "path", "issue": "description", "suggestion": "fix"}]}
```

**Model:** Always use `gpt-5.5` (not gpt-4o). Use `max_completion_tokens` if limiting output.

**On cycle 2 and later — include the rejection log from earlier cycles in the system prompt** so GPT-5.5 doesn't re-raise findings already adjudicated with counter-evidence:

```
## Previously rejected findings (do NOT re-raise without new information)

The following findings were raised in prior cycles and rejected by Opus
with cited counter-evidence. Unless you have *new* evidence that materially
changes the analysis, omit these from your cycle-N response:

- Cycle 1 finding #{N}: "{short quote}"
  Rejection: {one-line counter-evidence with file:line}
...

You may re-raise a listed finding ONLY if you have new information (a code
change since last cycle, a corrected citation, a genuinely different angle).
"Disagreeing with the rejection" is not new information.
```

A repeats-only response in cycle N is a clean pass — exit the loop and proceed to the gate checklist.

**Adjudication:** For each GPT-5.5 finding:
- **Accept** — fix the issue before proceeding
- **Reject** — cite counter-evidence from the codebase. Log the rejection.
- **Escalate** — present to the user for decision

**Major findings (High severity) block the phase gate.** Fix and re-review until clean.

### Step 3: Phase gate checklist

Verify every condition in the plan's phase gate section. Mark each as pass/fail.

---

## Post-implementation workflow

After all phases are complete:

### Step 0a: Worktree pre-flight — BLOCKING

Before anything else, audit the repo's worktrees. Stale locked worktrees
chronically block `git checkout main`, `git branch -d`, and finalization
branch creation later in Step 8. Catch them up front, not at the point of
failure.

Run:

```bash
git worktree list --porcelain | awk '/^worktree/ {print $2}'
```

For each worktree returned:

1. **Primary** (`<repo-root>`) — always keep. Never touched here.
2. **Named worktrees** (e.g., `/private/tmp/relyloop-release-main`, sibling
   checkouts) — check `stat -f %m <path>` (mtime). If older than 30 days,
   report to the user and ask: remove, fast-forward, or leave.
3. **Agent worktrees** (`.claude/worktrees/agent-*`) — these come from
   `Agent({ isolation: "worktree" })` calls that didn't clean up. For each
   locked `agent-*` worktree, verify the owning agent isn't running
   anymore, then offer to `git worktree remove --force <path>` *only*
   after user approval (CLAUDE.md rule: never force-remove locked
   worktrees without explicit approval, because they may hold
   uncommitted work).

**Never force-remove a worktree autonomously.** Report and wait for user
direction. The point of this step is surfacing the problem early, not
silently sweeping.

**Deliverable:** a short table in the chat like:

| Path | Branch | Age (days) | Recommendation |
|---|---|---|---|
| `/private/tmp/relyloop-release-main` | `main` | 5 | keep (recent release checkout) |
| `.claude/worktrees/agent-ae8b386d` | `worktree-agent-ae8b386d` | 0 | remove — agent completed |

User confirms → apply the recommendations → proceed to Step 0b.

### Step 0b: Test coverage audit

**This step is MANDATORY before documentation or PR.** Compare the plan's testing workstream (Section 3) against actually written test files. The testing workstream is the authoritative inventory — stories may only contain a subset of test tasks.

1. Read the plan's Section 3 (Testing workstream). List every test file it specifies across all layers (unit, integration, contract, E2E).
2. For each planned test file, check whether it exists on disk (`glob` the path).
3. Build a gap table:

| Planned test file | Exists? | Test count |
|---|---|---|
| `backend/tests/integration/test_foo.py` | Yes | 8 |
| `backend/tests/contract/test_foo_contracts.py` | **NO** | — |

4. If any planned test files are missing, write them before proceeding. Use parallel worktree agents (Step 6b pattern) for 3+ missing files.
5. Run the full test suite after writing missing tests to verify no regressions.

**Hard stop:** Do not proceed to documentation or PR if planned test files are missing.

#### Step 0b.1: Audit-event coverage audit

For every new `event_type` literal introduced by the diff (grep `git diff` for `create_audit_event(` calls and string literals matching `[A-Z_]+` that are passed as the `event_type` argument):

1. **Event-type catalog:** confirm any new event type has been added to the canonical `audit_log` event-type Literal/enum in `backend/db/models/audit_log.py`. Single source of truth per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../docs/01_architecture/data-model.md). RelyLoop's MVP2 audit-log is one append-only table; no per-event-type allowlist machinery exists.
2. **Frontend display (MVP2+ when the audit panel lands):** if the event surfaces in the UI, confirm a display-string mapping exists in the audit-event renderer component. RelyLoop scopes activity feeds per-study or per-proposal; no global tenant-timeline tab.
3. **Contract test:** confirm a contract test asserts the metadata shape on the audit row (mirroring `backend/tests/contract/test_study_audit.py`). Metadata canary check confirms no forbidden fields (credentials, tokens, PII beyond display-name strings) leak into `metadata_json`.
4. **Atomic emission:** confirm the `audit_log` INSERT happens inside the same transaction as the primary mutation (before `db.commit()`). (When MVP4 brings auth + tenants, expands to include `actor_id`/`tenant_id` FK resolution.)
5. Build a coverage table:

| New event_type | Allowlist? | Frontend IA case? | Contract test? | Atomic? |
|---|---|---|---|---|
| `STUDY_CREATED` | Yes | activity-tab.tsx:NNN | test_studies_audit.py | Yes |

**Hard stop:** Do not proceed to documentation or PR if any new tenant-visible event type is missing allowlist + IA + contract test coverage. Reference: [docs/01_architecture/audit_events.md](../../../docs/01_architecture/audit_events.md).

### Step 1: Extract deferred work

**This step is MANDATORY when the implementation plan covers only a subset of the spec's phases.** Deferred phases contain scoped, reviewed work that will be lost if not explicitly captured.

1. Read the feature spec's "Phase boundaries" and "Scope" sections. Identify any phases that were NOT included in the implementation plan (e.g., the plan covers Phase 1 but the spec defines Phase 2 work).
2. For each deferred phase, check whether a tracking file already exists:
   - `glob` for `*idea*.md` or `*phase*_idea.md` in the feature's `planned_features` directory
3. If no tracking file exists for a deferred phase, create one at `docs/02_product/planned_features/<feature_dir>/phase<N>_idea.md` with:
   - **Date** and **Status** (`Idea — deferred from Phase <N-1> implementation`)
   - **Origin** — pointer to the spec file and line numbers where the deferred work is defined
   - **Depends on** — which phase must be merged first
   - **Problem** — what gap remains after the implemented phase
   - **Proposed capabilities** — the FRs from the spec that were deferred, with enough context to generate a spec later
   - **Scope signals** — backend/frontend/migration/config impact hints
   - **Why deferred** — the rationale from the spec's phase boundary description
4. Commit the deferred work tracking file(s) with the documentation updates.

**Why this matters:** Spec phase boundaries represent reviewed, scoped work. Without an explicit tracking artifact, deferred phases exist only as prose inside a completed spec and are effectively invisible to future planning.

### Step 2: Documentation updates

Read the plan's documentation update workstream (Section 4). For each file:

- `state.md` — update completion snapshot, Alembic head, active priorities
- `architecture.md` — update if new services/layers/data flows were added
- `CLAUDE.md` — update if new conventions/endpoints/error codes were added

Commit documentation updates.

### Step 2.5: Tangential observations sweep — BLOCKING

Per the [tangential-discoveries rule in CLAUDE.md](../../../CLAUDE.md#tangential-discoveries--capture-as-idea-files-immediately), every issue you noticed during this implementation that was NOT part of the current plan must be captured as an idea file before push — not held in conversation memory, not deferred to "later in the PR description".

This step is a safety net for Rule #3 ("Capture, don't carry"). The discipline is to capture inline as you notice; this sweep is the last chance to flush anything you missed.

Walk back through this implementation session and ask:

1. **Did I `git stash` to verify a failure was pre-existing on `main`?** That's a tangential bug — it pre-existed and I confirmed it. If I didn't already file an idea, file one now.
2. **Did I see a test fail on first run, then pass on re-run, and "just re-run" without investigating?** That's a test-isolation bug. File an idea.
3. **Did I defer test coverage with "no framework available" / "manual smoke at staging" / "out of scope for a bug fix"?** That's an infra gap. File an idea.
4. **Did I read code that referenced a broken/stale path** (a TODO comment older than 6 months, a deprecated symbol still in use, an env var with no documentation)? Note it.
5. **Did I think "I should fix that someday" about anything**, even briefly? File the someday now.

For each, create `docs/02_product/planned_features/<bug_|chore_|infra_>_<slug>/idea.md` per [feature_templates/idea-template.md](../../../docs/02_product/planned_features/feature_templates/idea-template.md). Origin field MUST point at the PR or story that surfaced the observation, so the trace stays intact.

**If you have nothing to file, state explicitly: "Tangential observations sweep: none found." in your end-of-step summary.** Silence is suspicious — the sweep is supposed to find things.

Commit the idea files (separate `docs(planned): capture <N> in-flight-noticed issues` commit on the same branch is acceptable).

### Step 3: Guide impact assessment — MANDATORY GATE

**This step is a hard gate, not a sub-task.** It runs between documentation
and PR push, has its own number (promoted from the former "Step 2b" to make
it a first-class step), and **blocks Step 8 (Finalize) if skipped**. The
finalization pre-checks in Step 8.1 verify that this step ran; if it didn't,
finalization aborts with a clear error.

**This step is MANDATORY when the implementation touches tenant-facing UI.**

Evaluate whether any existing walkthrough guides need to be regenerated or new guides need to be created:

1. **Read `docs/08_guides/README.md`** to see the current walkthrough inventory.
2. **Read `web/src/components/guide-trigger.tsx`** to see the current route → guide mapping (`GUIDE_MAP`).
3. **For each modified frontend file in this implementation**, check:
   - Does the file appear in any guide's Playwright spec (`web/tests/e2e/guides/*.spec.ts`)? If yes, that guide's screenshots are likely stale — flag for regeneration.
   - Did the implementation add, remove, or rename UI elements (buttons, tabs, form fields, modals) that appear in existing guide screenshots? If yes, flag those guides.
   - Did the implementation add a new page or feature that tenants need to learn? If yes, flag for new guide creation.
4. **Report findings to the user:**
   - **Regenerate:** "Guide NN may need regeneration — [file] was modified and appears in the guide's Playwright spec."
   - **New guide:** "This feature adds [page/flow] that isn't covered by any existing guide. Consider creating guide NN."
   - **Route mapping:** "This feature adds/changes the [page] — verify `GUIDE_MAP` still maps the correct guides."
5. **If the user approves**, run `/guide-gen NN --regen` for stale guides or `/guide-gen "flow description"` for new guides.
6. **Update the `/guide` page** (`web/src/app/guide/page.tsx` → `GUIDE_CATALOG`) if a new guide was created.

### Step 4: Push and create PR

**Pre-push final gate.** Format + lint drift accumulates between the per-story Step 3 gate and now (test-file tweaks, review-finding fixes, commit-message retries all re-edit files). Re-run the full gate in CI-parity mode **before pushing** so you don't waste a CI round-trip on `ruff format --check` or `make lint`:

```bash
make fmt                                  # auto-fix any drift
make lint
make typecheck
./.venv/bin/ruff format --check backend/  # exactly what CI runs; must pass here too
```

If `make fmt` produced any diff, commit it first (`git add -A && git commit -m "style: apply ruff format (pre-push)"`) before pushing — that keeps the gate honest on the pushed SHA.

```bash
git push -u origin <branch_name>
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<bullet points>

## Test coverage
<test counts by layer>

## Test plan
- [x] make test-unit
- [x] make test-integration
- [x] make test-contract
- [x] make lint && make typecheck
- [ ] Staging verification after deploy

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 5: Monitor CI

```bash
gh run list --branch=<branch_name> --limit=3
gh run watch <run_id>
```

If CI fails, investigate and fix before moving on.

### Step 6: Adjudicate Gemini Code Assist review comments

After CI passes, Gemini Code Assist typically posts an automated review within ~2 minutes of the PR opening. Treat this review with the same rigor as the GPT-5.5 protocol: classify every finding, adjudicate with cited counter-evidence, and post a single summary comment before merge.

#### Step 5.1: Fetch findings

Two surfaces to check:

```bash
# Summary review body (themes, counts, overall verdict)
gh pr view <pr_number> --json reviews,comments --jq '{reviewCount: (.reviews | length), reviews: [.reviews[] | {author: .author.login, state, body: .body[0:500]}]}'

# Line-level inline comments (specific claims with path + line + severity icon)
gh api repos/SoundMindsAI/relyloop/pulls/<pr_number>/comments > /tmp/gemini_comments.json
python3 -c "
import json
with open('/tmp/gemini_comments.json') as f: c = json.load(f)
for i, x in enumerate(c):
    print(f'\n=== {i+1}: {x[\"user\"][\"login\"]} on {x[\"path\"]}:{x.get(\"line\", x.get(\"original_line\", \"?\"))} ===')
    print(x['body'][:1500])
"
```

Both are needed. The summary describes themes; the line comments are where the actual claims live. If no review has posted yet (~3 minutes after PR open), wait and retry — do not skip this step.

#### Step 5.2: Classify each finding

For each line-level finding, assign exactly one verdict:

- **Accept** — the finding is correct. Fix it. Accepted fixes require a commit, push, and a re-triggered CI run before merge.
- **Reject** — the finding is wrong. Cite counter-evidence from the codebase (file:line) that disproves the claim. The evidence rule from the GPT-5.5 protocol applies verbatim here: "I disagree" is not sufficient — show the code.
- **Defer** — the finding is valid but not a regression introduced by this PR (e.g., a pre-existing pattern, a UX improvement, an architectural suggestion for future work). Note it for a follow-up, do not fix in this PR.

**Common Gemini failure modes worth naming explicitly:**

| Failure mode | How to spot it | Default adjudication |
|---|---|---|
| **Hunk-isolated false positive** | Gemini claims a variable is undefined, a function call references a non-existent symbol, or imports are missing — but the surrounding (unchanged) code defines them. Gemini reviews diff hunks without the rest of the file. | **Reject.** Cite the defining line (e.g., "`_config_row` is defined at `discovery_service.py:181`"). |
| **Spec-vs-code drift** | Gemini claims the implementation disagrees with the spec. The spec may be wrong (pre-existing bug the frontend was living with — e.g., frontend calls `POST /archive` while the backend exposes `DELETE`). Verify against the actual backend route, not the spec. | **Reject** the claim against the implementation. Note the spec needs correction when the feature folder moves to `implemented_features`. |
| **Correctness-shaped UX suggestion** | Gemini uses High/Critical severity for what is actually a UX improvement (e.g., "add rollback on failure", "disable button during request", "validate client-side before POST"). Check whether the prior behavior was the same. | **Accept** if the PR introduced the regression (e.g., deleting a legacy component dropped the validation). **Defer** if the pattern pre-exists in the codebase. |
| **Severity inflation** | Gemini marks defensive-code suggestions as "Critical" even when the branch in question is unreachable (e.g., a NOT NULL column with a seeded default making a fallback branch impossible). | Verify reachability with a grep of the schema/migration. If unreachable, **reject** with the migration cite. |

#### Step 5.3: Apply accepted fixes

For each accepted finding:
1. Make the minimal change that addresses the root cause — not a defensive patch around it.
2. Re-run the frontend verification gate (`npx tsc --noEmit` plus any targeted E2E that covers the changed behavior).
3. Commit with a message that references the finding source (`fix(scope): <summary>` — include a body bullet per finding).
4. Push. The PR CI will re-run automatically; wait for green before the summary comment.

Group small related fixes into one commit when they touch the same file — don't spam the PR with one commit per finding.

#### Step 5.4: Post adjudication summary on the PR

Post **one** comment on the PR that tables every finding with its verdict, so the human reviewer can see the full picture without re-reading each inline thread. This replaces per-thread acknowledgment replies.

Template (fill in every row — rejected rows must include the counter-evidence cite):

````markdown
## Review adjudication (Gemini Code Assist + GPT-5.5 final review)

Commits landing fixes: `<sha1>`, `<sha2>`

### Gemini Code Assist (<N> findings)

| # | Sev | Location | Verdict | Notes |
|---|---|---|---|---|
| 1 | Critical | path/to/file.py:LN | **Rejected** | Counter-evidence: `<file>:<line>` defines `<symbol>`. Gemini reviewed hunk without surrounding function context. |
| 2 | High | path/to/file.ts:LN | **Accepted** | Fixed in `<short-sha>` — <one-line description of the fix>. |
| 3 | Medium | path/to/file.ts:LN | **Deferred** | UX improvement; matches prior component's behavior; not a regression. Follow-up tracked as <note/TODO>. |

### GPT-5.5 final review (<N> findings)

| # | Sev | Location | Verdict | Notes |
|---|---|---|---|---|
| … | … | … | … | … |

### Outcomes

- **Applied fixes (<N>):** <one-line list>
- **Rejected with cited counter-evidence (<N>):** <one-line list>
- **Deferred as non-regression follow-ups (<N>):** <one-line list>

Ready for human review + merge.
````

#### Step 5.5: Stop conditions

Proceed to Step 6 only when all of the following hold:
- Every Gemini line comment has a verdict entered in the adjudication table.
- Every Accept has a commit + green CI run.
- Every Reject has a file:line counter-evidence cite in the notes column.
- The summary comment has been posted on the PR.

If a finding is ambiguous (product decision, scope question), escalate to the user rather than forcing a verdict.

### Step 7: Final cross-model review

Run one final GPT-5.5 review of the complete PR diff:

```bash
git diff main..HEAD
```

Send to GPT-5.5 with the full implementation plan. This catches cross-story issues that per-phase reviews might miss.

**Include the phase-gate + Gemini rejection log in the system prompt** so the final review doesn't re-raise findings already adjudicated at the phase gate or in Gemini's review. Use the same "Previously rejected findings — do NOT re-raise without new information" block documented in Step 2 above. Merge both rejection logs (phase-gate + Gemini) into one list. A repeats-only final-review response is a clean pass — post the convergence note to the PR and proceed to Step 7 finalization.

### Step 8: Finalize — verify completion, update docs, move to implemented

> **Ad-hoc mode:** sub-steps 1, 3 (`pipeline_status.md`), 4 (`implementation_plan.md`), 6 (phase idea files), 7 (folder move) are SKIPPED — there is no plan, pipeline_status, or feature folder to update. Sub-steps 0 (post-merge branch setup — derive the finalization branch slug from the **feature branch name** instead of a feature directory; e.g., feature branch `bug_study_status_transition` → `docs/finalize-study-status-transition`), 1a / 2 (guide impact), 5 (`state.md` if applicable), 8 (commit + push), 9 (report completion) still apply.

**This step is MANDATORY after CI passes and Gemini review comments are addressed.** It closes out the feature lifecycle and ensures the feature is properly archived.

**0. Post-merge branch setup — BLOCKING if PR is merged.**

   Check the PR state:

   ```bash
   gh pr view <pr_number> --json state,mergedAt
   ```

   - **If `state == "OPEN"`** — stay on the feature branch. Proceed to 8.1.
   - **If `state == "MERGED"`** — the feature branch is dead (squash-merged).
     Do NOT commit finalization edits on it; they'd go nowhere useful.
     Instead:

     ```bash
     git fetch origin main
     git checkout -b docs/finalize-<feature-slug> origin/main
     ```

     Never attempt `git checkout main` directly — a sibling worktree at
     `/private/tmp/relyloop-release-main` (or similar) typically owns `main`
     and blocks the checkout (CLAUDE.md rule: do not force-remove
     locked worktrees). Creating a new branch from `origin/main`
     sidesteps the conflict cleanly.

   Slug convention: lowercase, kebab-case, derived from the feature
   directory name (e.g., `feat_study_lifecycle` →
   `docs/finalize-pr-worker-pat-rotation`).

   After this step, all subsequent finalization commits land on the new
   branch and are merged via a second, docs-only PR.

1. **Verify implementation completeness:**
   - Read the implementation plan's execution tracker (Section 9). Confirm every story is marked `[x]`.
   - For each story, spot-check that its key artifacts exist: new files created, modified files changed, test files present.
   - If any story is incomplete, stop and report the gap.

1a. **Pre-check: guide impact assessment must have run — BLOCKING.**
   Before proceeding to any of the steps below (pipeline_status, state.md,
   folder move), verify that Step 3 (Guide impact assessment) was executed
   earlier in this workflow. Check for one of the following pieces of
   evidence in the PR branch / recent commits:
   - A commit containing `docs(guides):` referencing a new or regenerated
     guide (`web/public/guides/<NN>_*/` asset additions), OR
   - An explicit user-acknowledged "no guide impact" note in the PR body
     or in a commit message (e.g., "Guide impact: no tenant-facing UI
     changes — no guide work needed").

   If neither is present AND the implementation touched any file under
   `web/src/` (other than tests), **STOP finalization**. Report:

   > "Step 3 (Guide impact assessment) has no recorded outcome. Finalization
   > is blocked until the guide gate runs. Run it now? (Y/n)"

   On "Y", run Step 2 below (guide impact assessment). On "n", require
   the user to paste a one-line rationale which you then record in the
   finalization commit body as `Guide impact: <rationale>` before
   continuing.

2. **Guide impact assessment (if frontend was touched):**
   This runs the same evaluation as Step 3 (post-implementation) but is
   placed here as a hard gate to ensure it is never skipped — even if the
   post-implementation workflow was interrupted or abbreviated.
   - Read `docs/08_guides/README.md` for the current walkthrough inventory.
   - Read `web/src/components/guide-trigger.tsx` for the route → guide mapping (`GUIDE_MAP`).
   - For each modified frontend file in this implementation, check:
     - Does the file appear in any guide's Playwright spec (`web/tests/e2e/guides/*.spec.ts`)? If yes, flag that guide for regeneration.
     - Did the implementation add, remove, or rename UI elements that appear in existing guide screenshots? If yes, flag those guides.
     - Did the implementation add a new page or feature that tenants need to learn? If yes, flag for new guide creation.
   - **Report findings to the user** before proceeding:
     - **Stale guides:** "Guide NN may need regeneration — [file] was modified and appears in its Playwright spec."
     - **New guide candidate:** "This feature adds [capability] not covered by any existing guide. Consider creating Guide NN."
     - **No impact:** "No existing guides affected. No new guide needed."
   - If the user approves guide work, run `/guide-gen` before continuing. If declined or deferred, note it in the commit message and move on.

3. **Update pipeline_status.md:**
   - Change `## Implementation` status from `PR created` to `Complete`.
   - Add: date, PR number, CI status, stories completed count, Gemini review status.

4. **Update implementation_plan.md:**
   - Change the `**Status:**` field in the header from `Ready for Execution` / `In Progress` to `Complete (PR #<number>, merged <date>)`.

5. **Update state.md:**
   - Add the feature to `## Most recent meaningful changes` with a summary paragraph (component changes, test counts, key decisions).
   - Update `**Current focus:**` line to include the feature as merged.
   - Update `## Current branch / execution context` to reflect the new state.

6. **Check for unimplemented phase idea files:**
   Before moving the folder, check for any `phase*_idea.md` files in the feature directory:
   ```bash
   ls docs/02_product/planned_features/<feature_dir>/phase*_idea.md 2>/dev/null
   ```
   - If any `phase*_idea.md` files exist, **STOP** — do not move the folder.
   - Report the found files to the user and ask for instructions. The folder contains future work that has not been implemented yet, so moving it to `implemented_features/` would be incorrect.
   - The user may choose to: (a) split the phase idea files out to a new planned feature folder before moving, (b) implement the remaining phases first, or (c) explicitly confirm the move anyway.
   - Only proceed with the move after the user gives explicit instructions.

7. **Move feature folder to implemented_features:**
   ```bash
   mv docs/02_product/planned_features/<feature_dir> \
      docs/00_overview/implemented_features/<YYYY_MM_DD>_<short_name>/
   ```
   - Date prefix uses the completion date (today).
   - Short name is a snake_case slug derived from the feature directory name.
   - The entire folder moves — spec, plan, pipeline_status, phase idea files all travel together.

8. **Commit and push** the finalization changes:
   ```bash
   git add <all changed files> && git commit -m "docs: move <feature> to implemented, update state.md"
   git push
   ```

9. **Report completion** to the user with the final PR URL and a summary of what was archived.

**Why this step exists:** Without explicit finalization, completed features linger in `planned_features/` and `pipeline_status.md` stays at "PR created" indefinitely. This creates stale state that confuses future planning sessions and the `/pipeline --status` command.

---

### Step 9: Post-merge local cleanup — BLOCKING

Run after both the feature PR and the finalization PR have merged. Closes
out the local git state so future sessions don't resume on a dead branch
and so stale agent worktrees don't accumulate.

**9.1 Fast-forward primary checkout.**

Because `/private/tmp/relyloop-release-main` (or a similar sibling worktree)
may own `main`, never attempt `git checkout main` in the primary
checkout when it's on a feature branch. Instead:

```bash
git fetch origin main
# Stay on the finalization branch (it's safe to delete in 9.2 once we've
# updated refs). The primary worktree remains on the feature branch
# until 9.2 — that's fine.
```

If the sibling worktree is stale and blocks you, fast-forward it in-place
without touching the primary:

```bash
git -C /private/tmp/relyloop-release-main pull --ff-only origin main
```

Never `git worktree remove --force` or `git worktree unlock` a sibling
without **explicit user approval** (CLAUDE.md rule — locked worktrees
may hold in-flight work).

**9.2 Delete merged local branches.**

```bash
# Feature branch (squash-merged — use -D because squash doesn't preserve ancestry).
git branch -D <feature_branch_name>

# Finalization branch (same reason if squash-merged, else -d).
git branch -d docs/finalize-<feature-slug> 2>/dev/null || git branch -D docs/finalize-<feature-slug>
```

If a branch is "already checked out in worktree at <path>" — one of the
`.claude/worktrees/agent-*` dirs still holds it. Proceed to 9.3.

**9.3 Agent worktree sweep.**

```bash
git worktree list --porcelain | awk '/^worktree/ {p=$2} /^branch / {print p, $2}' | grep '\.claude/worktrees/agent-'
```

For each `agent-*` worktree returned:

- Verify the agent isn't running anymore (check its task-id output file
  under `/private/tmp/claude-501/.../tasks/`; if its status is
  `completed`, the agent is done).
- If done and no uncommitted work is visible (`git -C <path> status -s`
  empty), offer to:
  ```bash
  git worktree remove --force <path>
  git branch -D <worktree-branch-name>
  ```
- Require **explicit user approval** before each force-remove. Do not
  batch-remove autonomously.

**9.4 Background process sweep.**

List any background bash processes this session started that are still
running (CI watchers, dev servers, etc.) and decide per-process whether
to keep them alive (e.g., `make restart` dev stack) or terminate them.

**9.5 Report.**

End-of-session summary:

- Feature branch: deleted (or still held by `<worktree>`).
- Finalization branch: deleted.
- Agent worktrees removed: N.
- Agent worktrees remaining: N (listed with paths).
- Background processes remaining: N (listed).

**Why this step exists:** without it, each completed feature leaves behind
a dead local branch + 1–3 locked agent worktrees. After 5–10 features that
becomes a full-day cleanup chore and `git branch --show-current` at
session resume reports stale branches that confuse future agents. Doing
it incrementally at merge time costs ~30 seconds.

---

## Error handling

### Lint/typecheck failure
1. Read the error message
2. Fix the specific issue (do not run `--fix` blindly for lint — review what it changes)
3. Re-run the check
4. If the fix requires changing code you didn't write, verify it doesn't break existing behavior

### Test failure
1. Read the test failure output
2. Determine: is the test wrong, or is the code wrong?
3. If the test is wrong (testing the old behavior that was intentionally changed): update the test
4. If the code is wrong: fix the code and re-run
5. Never delete a failing test without understanding why it fails

### Migration failure
1. If `upgrade head` fails: check the migration SQL for syntax errors
2. If `downgrade -1` fails: the `downgrade()` implementation is wrong — fix it
3. If round-trip fails: the upgrade creates state that downgrade doesn't fully reverse — fix the downgrade
4. Always verify with a fresh `alembic upgrade head` after fixing

### Frontend build failure
1. `npx tsc --noEmit` errors: fix TypeScript type issues
2. `npx next build` errors: may be SSR-related (using browser APIs in server context) or import issues
3. Read the full error — Next.js errors often point to the wrong line

---

## Manual steps

Some stories involve manual configuration outside the codebase (GitHub App registration + private-key install, deployment-target env vars, DNS changes for the demo install, configuring an Elasticsearch/OpenSearch test cluster, registering an LLM provider account or starting a local Ollama server). For these:

1. Read the relevant docs in `docs/01_architecture/` and any vendor links cited there
2. Present step-by-step instructions to the user
3. Wait for the user to confirm completion
4. Verify the configuration (e.g., hit `/api/v1/clusters/{id}/health` to confirm the registered cluster responds; round-trip a one-token prompt against the configured LLM provider)
5. Update the implementation plan tracker

---

## Rules

1. **Never commit to main.** Always use a feature branch.
2. **Never skip a verification gate.** If lint fails, fix it. If tests fail, fix them. No `--no-verify`.
3. **Never implement beyond the story scope. Capture, don't carry.** If you see a bug or improvement opportunity that's orthogonal to the current story, do NOT fix it in this story's commit AND do NOT just "note it for later" in conversation memory. **Create an idea file immediately** at `docs/02_product/planned_features/<bug_|chore_|infra_>_<slug>/idea.md` per the [tangential-discoveries protocol in CLAUDE.md](../../../CLAUDE.md#tangential-discoveries--capture-as-idea-files-immediately). Idea files surface in `/pipeline --status` and persist across sessions; chat-noticings evaporate. Step 1.5 below ("Tangential observations sweep") flushes any uncaptured noticings before push as a safety net, but the discipline is to capture inline as you notice.
4. **Always read before editing.** Never modify a file you haven't read in this session.
5. **Always use GPT-5.5 for cross-model review.** Model ID: `gpt-5.5`. Never substitute gpt-4o.
6. **Always update the plan tracker** after completing a story.
7. **Always run the full test suite** at phase gates — not just the tests you wrote.
8. **Frontend changes require the UI Guidance section.** If the plan doesn't have one, stop and ask the user to update the plan before implementing.
9. **Commit frequently** — one commit per story, not one giant commit per phase.
10. **Inform the user** at each story boundary: what was completed, what's next, any issues found.
