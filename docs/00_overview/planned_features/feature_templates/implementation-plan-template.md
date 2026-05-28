# Implementation Plan — <Feature Name>

**Date:** <YYYY-MM-DD>
**Status:** <Draft | Ready for Execution | In Progress | Complete>
**Primary spec:** <feature-spec.md>
**Policy source(s):** <policy docs>

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Keep repository patterns consistent.
- Keep increments narrow enough to verify independently.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 | Epic <n> / Phase <n> | <note> |
| FR-2 | Epic <n> / Phase <n> | <note> |

**If any FRs are marked as out-of-scope for a future phase**, verify that a tracking artifact exists for the deferred work (`phase<N>_idea.md` in the feature directory — see `feature_templates/idea-template.md`). If not, create one before proceeding. Deferred FRs without a tracking file will be lost.

## 2) Delivery structure

Use one of:

- **Epic → Story → Tasks → DoD** (preferred for product-facing work)
- **Phase → Tasks → Checkpoint gate** (preferred for infra/migration-heavy work)

You may combine both, but every section must have measurable completion gates.

### Story-level detail requirements

Each story must include enough information for an engineer (or AI agent) to implement without
interpretation gaps. The minimum required sections per story are:

1. **Outcome** — user or system behavior achieved.
2. **New files** — every file the story creates, with path and purpose.
3. **Modified files** — every file the story changes, with description of change.
4. **Endpoints** — method, path, request body, success response shape, and error codes (if story adds/changes API surface).
5. **Key interfaces** — function signatures with type hints for domain, service, and repo layers.
6. **Pydantic schemas** — request/response models (if API-facing).
7. **UI element inventory** — complete list of UI elements being created, moved, or removed (if story has frontend scope). See below.
8. **State dependency analysis** — state variables, callbacks, or data flows that cross component/story boundaries (if story modifies shared state). See below.
9. **Tasks** — specific implementation steps.
10. **Definition of Done** — observable completion gates with test layer references.

Stories that are purely documentation, refactor, or test-only may omit Endpoints/Schemas sections
but must still include New/Modified files and Tasks/DoD.

### UI element inventory (for frontend stories)

For stories that create, move, or remove UI, include a complete inventory of every visual element.
This prevents functionality loss during refactors and gives implementers an unambiguous target.

For **creation/move** stories, list every card, form field, button, modal, alert, and interactive
element the component must render. Include:
- Element type (card, input, select, checkbox, button, modal, alert, etc.)
- Label/title text
- Data source (which state variable or API call)
- User interactions (click handlers, submit behavior, validation)

For **removal** stories, list every element being removed and every state variable / callback being
deleted. This serves as a cleanup checklist.

### State dependency analysis (for refactors)

When a story removes or moves state, list every other component, callback, or rendering path that
references that state. This catches cross-component breakage before implementation.

Format:
```
State being removed: <variable name>
Referenced by:
  - <component/function> at <file:line> — action needed: <remove ref / refactor / replace>
```

### Conventions (project-specific — customize per project)

Document the codebase conventions that stories must follow. This prevents drift across stories
and ensures consistency for AI agents and new contributors.

```
- All repo functions take `db: Session` as first arg; use `db.flush()` (caller commits)
- Services are async; create `job_run` at start where applicable
- Domain layer is pure — no DB access, no side effects
- Models use `Mapped[]` typed columns, `String(36)` UUIDs
- Routers return typed Pydantic response models; errors use `HTTPException` with structured detail
- Config via `pydantic-settings`
- All `__init__.py` exports updated via `__all__`
```

### AI Agent Execution Protocol (applies to every story)

If an AI agent will execute stories, include a prescribed execution order to reduce ambiguity:

0. **Load context first**: Read `architecture.md` and `state.md` before starting the first story.
   These provide system design context (page structure, data flows, component inventory) and current
   project state (active branch, recent changes, known debt) needed to implement correctly.
1. **Read scope**: verify story outcome + endpoints + interfaces + DoD.
2. **Implement backend first**: models → migration → repo → domain → service → router → schemas.
3. **Run backend tests** (minimum: unit + integration + contract subset for touched endpoints).
4. **Implement frontend** (if story includes UI scope).
5. **Run E2E scope** for touched UX paths.
6. **Update docs/checklists** impacted by behavior changes in same PR.
7. **Verify migration round-trip** if schema changed.
8. **Attach evidence** in PR description: commands run, pass/fail, and files changed.
9. **After the final story**, update `state.md` and `architecture.md` (see §4 Documentation update
   workstream for specific criteria).

Story completion is invalid if any step above is skipped.

---

## Epic 1 — <Name>

### Story 1.1 — <Outcome title>
**Outcome:** <user/system outcome>

**New files**

List every file the story creates. Include the full path and a short purpose description.

**IMPORTANT for migration files:** Verify the actual Alembic versions directory by running
`ls` on the migrations path (e.g., `backend/alembic/versions/`). Do not assume a path — some
projects use `backend/app/db/migrations/versions/`, others use `backend/alembic/versions/`.
Check the current head revision number and use the next sequential number.

| File | Purpose |
|---|---|
| `backend/app/domain/<module>/<file>.py` | <what this file provides — domain logic, data model, repo functions, etc.> |
| `backend/app/db/models/<model>.py` | <model name>: list key columns and constraints |
| `backend/app/db/repo/<repo>.py` | <list key functions> |
| `backend/app/services/<service>.py` | <orchestration scope> |
| `backend/app/api/<router>.py` | <endpoint group> |
| `web/src/app/<route>/page.tsx` | <page purpose> |

**Modified files**

List every file the story changes and describe the change.

| File | Change |
|---|---|
| `backend/app/db/models/__init__.py` | Export new models |
| `backend/app/db/repo/__init__.py` | Export new repo functions via `__all__` |
| `backend/app/core/config.py` | Add settings: <list key new config fields> |
| `backend/app/api/schemas.py` | Add <schema names> |

**Endpoints** (if story adds or modifies API endpoints)

Define each endpoint with enough precision to implement and test without ambiguity.

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/<resource>` | `{ field, field }` | `201` `{ id, field }` | `ERROR_CODE` (4xx) |
| `GET` | `/<resource>/{id}` | — | `200` `{ id, field, ... }` | `401`, `404` |

Note: Use the project's established endpoint prefix convention. Verify against existing routers.

**Key interfaces** (if story introduces domain/service/repo functions)

Provide function signatures with type hints. These are the contract that tests will validate.

```python
# domain/<module>/<file>.py
def function_name(arg: type, arg: type) -> return_type: ...   # brief purpose

# db/repo/<repo>.py
def repo_function(db: Session, key_arg: type) -> Model | None: ...

# services/<service>.py
async def service_function(db: Session, arg: type) -> dict: ...
```

**Pydantic schemas** (if story adds API request/response models)

```python
class RequestModel(BaseModel):
    field: type
    optional_field: type | None = None

class ResponseModel(BaseModel):
    id: str
    field: type
```

**Tasks**
1. <implementation task — specific enough to execute without further interpretation>
2. <implementation task>
3. <validation task>

**Definition of Done (DoD)**
- <observable done condition>
- <test condition — specify which test layer>
- <operational/doc condition>

(Repeat stories and epics as needed)

---

### Alternative: Phase → Tasks → Checkpoint gate

Use this structure for infra/migration-heavy work where sequential gating matters more than
user-facing story outcomes.

#### Phase 1 — <Name>

**Tasks**
1. <implementation task>
2. <implementation task>
3. <validation task>

**Checkpoint gate** (hard stop — do not proceed until all pass)
- [ ] <measurable gate condition>
- [ ] <test/operational condition>
- [ ] <doc/review condition>

#### Phase 2 — <Name>
(Repeat as needed)

---

## UI Guidance (required for frontend-facing work)

For features that add, move, or change UI, provide guidance that prevents ambiguity during
implementation. This section is especially important for AI agents that cannot visually verify
their output.

### Reference: current component structure

Before describing new UI, document the current state of every component being modified. This
prevents stale assumptions about existing markup, state variables, and insertion points.

For each component:
- **File path and total line count** — so the implementer knows the scale
- **Section/card structure** — what sections exist, in what order, with line ranges
- **State variables** — every `useState`, `useMemo`, `useCallback` with types
- **Props** — the full interface definition
- **Insertion points** — exact line numbers where new elements should go (e.g., "after line 286,
  before line 288")

### Analogous markup patterns (required for new UI sections)

When a new UI section should match an existing section's style, include the **actual markup** from
the analogous section — not just a reference to it. Copy the JSX with CSS classes, inline styles,
and component usage so the implementer has a copy-pasteable template.

**Why this matters:** Saying "follow the Resend pattern" is ambiguous. Showing the actual 20 lines
of JSX with `.progress-wrap`, `.progress-bar`, `AdminDataTable`, and `AdminStatusBadge` usage
eliminates interpretation and ensures visual consistency.

Format each pattern as:
```tsx
{/* Pattern name — from <file>:<lines> */}
<ActualJSX className="actual-class" style={{ actual: "styles" }}>
  {/* Include conditional logic, map() calls, and data bindings */}
</ActualJSX>
```

### Layout and structure
- Describe the target layout pattern (flex, grid, stacked cards, tabs, etc.)
- Note responsive behavior (wrap, collapse, hide) if applicable
- Reference existing CSS classes/patterns to reuse

### Interaction behavior
- How do components on the same page communicate? (callback props, shared state, URL params)
- What happens when a user action on one tab affects another? (e.g., saving config then running discovery)
- Navigation within the page vs. between pages (use `openTab()` vs. `<Link>`)

### Component composition
- Which components are extracted vs. inline?
- What props does each component accept? What callbacks does it expose?
- Are there any circular dependencies between parent and child state?

### Information architecture placement
- Where does this feature live in the navigation hierarchy? (sidebar, tab, modal, settings subsection)
- If adding a new tab or section, state what comes before and after it in the existing tab/section order
- If moving elements between pages, list the old location → new location with rationale
- How does the user discover this feature? (direct nav link, contextual action from another page, settings toggle)

### Tooltips and contextual help
- For each non-obvious UI element, specify the tooltip text, trigger mechanism, and placement
- Use the tooltip inventory from the feature spec (§11) as the source of truth
- For implementation, use the project's existing tooltip pattern (check codebase for `title` attributes, custom tooltip components, or inline helper text patterns)
- Include the actual JSX/markup for tooltips so the implementer doesn't need to guess the pattern

Example:
```tsx
{/* Tooltip pattern — adapt to the project's existing primitive */}
<label>
  Max trials
  <span className="tooltip-trigger" title="Stop the study after this many trials, even if the time budget is unused. Recommended: 100-2000.">ⓘ</span>
</label>
```

### Visual consistency
- Name the existing patterns or components to match (e.g., "use `btn btn-primary` / `btn btn-secondary` tab pattern from existing pages")
- Note any elements being ported between implementations with different styles (e.g., "range slider vs. number input — use the range slider version")

### Legacy behavior parity (required when a story deletes or replaces a user-facing component >100 LOC, or migrates significant UI functionality between files)

Before deleting or replacing an existing component, enumerate every user-observable behavior it ships: client-side validations (min/max length, regex, required), loading states, disabled conditions, error messages, button-label changes tied to state, optimistic updates with rollback, confirmation dialogs, tooltips, focus management, keyboard shortcuts. Each behavior gets a verdict.

**Why this matters:** Deleting 1,000+ LOC of JSX silently drops behaviors that tests don't assert. TypeScript compilation and happy-path rendering do not catch a missing `minLength={20}` check, a button that re-fires while a request is in flight, or a confirmation dialog that quietly disappeared. Cross-model code review repeatedly catches these post-hoc, which costs review cycles and risks shipping regressions to users.

How to build the table:
1. Read the full deleted/replaced component top-to-bottom.
2. Grep it for: `onChange`, `onClick`, `onSubmit`, `onBlur`, `maxLength=`, `minLength=`, `pattern=`, `disabled=`, `aria-disabled`, `role="alert"`, `catch (`, `setError`, `setLoading`, `confirm(`.
3. For each match, add a row. No match should be unlisted.

Table format:

| # | Legacy behavior | Location in deleted component | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | NL description 20-char minimum before POST | `PlatformsKeywordsTab.tsx:420-425` | Preserved | `SetupPlatformView.tsx:333-340` (validated in `suggestKeywords()` before fetch) |
| 2 | NL description 600-char maximum | `PlatformsKeywordsTab.tsx:426-431` | Preserved | `SetupPlatformView.tsx:341-346` |
| 3 | Run-discovery button disabled during inflight | `PlatformsKeywordsTab.tsx:780` | Preserved | `SetupPlatformView.tsx` — `runLoading` state gate + button `disabled` prop + "Starting…" label |
| 4 | "Copy keywords from Instagram to TikTok" quick action | `PlatformsKeywordsTab.tsx:890-920` | Intentionally dropped | Per-platform tab separation makes cross-platform copy confusing; authorized in spec §11 (IA decision 2026-04-16) |
| 5 | Confirm dialog on "Remove all keywords" | `PlatformsKeywordsTab.tsx:1010` | Preserved | `SetupPlatformView.tsx` — same `window.confirm()` wrapper on bulk-remove handler |

Rules:
- The assigned story's **DoD must include a test assertion** (unit, integration, or E2E) for every row marked "Preserved". A "Preserved" row without a corresponding DoD test assertion is an incomplete story.
- "Intentionally dropped" rows must cite **a specific spec section, idea section, or product-decision reference with a date** — not "not required for MVP" without a source.
- If a behavior is being **weakened** (e.g., "validation now only runs on blur, not on every keystroke"), list it as a new row with verdict "Weakened" and the rationale.

Omit this subsection only when the feature does NOT delete or migrate any user-facing component >100 LOC. State explicitly: "No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan."

### Client-side persistence (if applicable)

When a story uses client-side storage, explicitly state the persistence scope and mechanism:

- **`sessionStorage`** — cleared when the browser tab closes. Use for dismissals that should
  reappear on new visits (e.g., guidance banners).
- **`localStorage`** — persists indefinitely across sessions. Use for durable preferences
  (e.g., theme, dismissed-forever flags).
- **React state only** — cleared on navigation/remount. Use for transient UI state.

The DoD must match the mechanism: if the task says `sessionStorage`, the DoD must say
"persists for the browser session" (not "persists across visits").

---

## 3) Testing workstream (required)

Plan testing explicitly by layer and map to stories.

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: domain logic, pure helpers, policy decisions, guardrails
- Tasks:
  - [ ] <unit test task>
  - [ ] <unit test task>
- DoD:
  - [ ] Critical branches covered and deterministic

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: DB-backed workflows, transitions, migrations, idempotency
- Tasks:
  - [ ] <integration test task>
  - [ ] <integration test task>
- DoD:
  - [ ] Happy path + critical failure paths covered

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: endpoint shape, status codes, machine-readable error codes
- Tasks:
  - [ ] <contract test task>
- DoD:
  - [ ] No accepted endpoint without contract coverage

### 3.4 E2E tests
- Location: `web/tests/e2e/`
- Scope: critical user/admin journeys, discoverability, role gating
- **Rule: E2E tests must use real browser interactions via Playwright's `page` object.** API `request` is for test setup only (registering clusters, creating query sets, seeding judgments). Assertions must verify browser-visible behavior — navigate pages, fill forms, click buttons, assert DOM elements. Pattern: setup via API helpers → interact via `page`.
- Tasks:
  - [ ] <e2e test task>
- DoD:
  - [ ] Stable profile pass for critical flows
  - [ ] Tests use `page` for browser interactions, not just `request`

### 3.5 Existing test impact audit (required for refactors and UI changes)

Search all test files for references to pages, URLs, tab names, or behaviors that will change.
List every file, the pattern found, the occurrence count, and the required action.

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `<file>` | `<URL or assertion>` | <N> | `<update URL / update assertion / no change needed + why>` |

For files that need NO changes, explicitly state why they're safe (e.g., "uses `tab=usage` which
stays on Settings page"). This prevents false confidence from incomplete audits.

### 3.5 Migration verification (if schema changes)
- [ ] Alembic migration includes `downgrade()` implementation
- [ ] `alembic upgrade head` succeeds
- [ ] Round-trip verified: `alembic downgrade -1 && alembic upgrade head`
- [ ] DB revision guard passes at API startup

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd web && npm run test:e2e:stable`

---

## 4) Documentation update workstream (required)

### 4.0 Core context files (required for every implementation plan)

These files are read at the start of every task and must stay accurate:

**`state.md`** — update if any of the following changed:
- [ ] Active branch changed
- [ ] New features were completed or priorities shifted
- [ ] New debt was introduced
- [ ] Alembic head moved
- [ ] Current branch/execution context section needs updating

**`architecture.md`** — update if any of the following changed:
- [ ] New services, layers, or components were added
- [ ] New data flows were introduced
- [ ] New integrations were wired in
- [ ] Design decisions were made or invariants changed
- [ ] Frontend page structure changed (tabs added/removed/moved, new reusable components)

**`CLAUDE.md`** — update if any of the following changed:
- [ ] New conventions, rules, or coding patterns were established
- [ ] New environment variables or build commands were added
- [ ] Feature status section needs updating (planned features added/removed)

### 4.1 Architecture docs (`docs/01_architecture`)
- [ ] Update system boundaries and sequence/state diagrams
- [ ] Update API reference semantics where needed

### 4.2 Product docs (`docs/02_product`)
- [ ] Update user/admin behavior and UX flows
- [ ] Update role/action expectations

### 4.3 Runbooks (`docs/03_runbooks`)
- [ ] Add incident/remediation procedures
- [ ] Add rollback/replay/operational checks

### 4.4 Security docs (`docs/04_security`)
- [ ] Update threat model and control mapping
- [ ] Update secret/key handling guidance

### 4.5 Quality docs (`docs/05_quality`)
- [ ] Update testing strategy matrix
- [ ] Update release/quality checkpoints

**Documentation DoD**
- [ ] `state.md`, `architecture.md`, and `CLAUDE.md` are consistent with shipped behavior
- [ ] Docs across docs/01-05 are consistent with shipped behavior and test contracts
- [ ] Required runbooks are dry-run validated where practical

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals
- Eliminate duplication in critical code paths
- Centralize policy/authorization/error mapping logic
- Keep scope bounded (no speculative redesign)

### 5.2 Planned refactor tasks
- [ ] Backend refactor: <task>
- [ ] Frontend refactor: <task>
- [ ] Remove dead/legacy branches after cutover

### 5.3 Refactor guardrails
- [ ] Behavioral parity proven by tests
- [ ] Lint/typecheck remain green
- [ ] No expansion of product scope
- [ ] Track discovered debt with owner + disposition

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| <dependency> | <story> | <planned/implemented/blocked> | <impact> |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| <risk> | <L/M/H> | <L/M/H> | <plan> |

### Failure mode catalog

List expected failure modes and the system's required behavior for each. This is distinct from the
API error code catalog (which covers HTTP responses) — this section covers internal failures,
external service failures, and race conditions that the implementation must handle gracefully.

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| <failure description> | <what causes it> | <how the system should respond> | <auto/manual/alert> |

## 7) Sequencing and parallelization

### Suggested sequence
1. <epic/phase>
2. <epic/phase>
3. <epic/phase>

### Parallelization opportunities
- <what can run in parallel and why>

## 8) Rollout and cutover plan

- Rollout stages: <internal, limited, full>
- Feature flag strategy: <if used>
- Migration/cutover steps: <if needed>
- Reconciliation/repair strategy: <if external systems involved>

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] <story/task>
- [ ] <story/task>

### Blocked items
- <item> — blocker: <reason> — owner: <name>

### Done this sprint
- [x] <completed item>

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all four layers where applicable
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or targeted subset with explanation)
    - [ ] `make test-contract`
    - [ ] `cd web && npm run test:e2e:stable` (if UI touched)
- [ ] Migration round-trip evidence included if schema changed
- [ ] Related docs/checklists updated in same PR when behavior/contract changed

## 11) Plan consistency review (required before execution)

Before marking the plan as "Ready for Execution," perform a cross-reference review:

1. **Spec ↔ plan endpoint count**: count the endpoints in the spec's §7.1 table and verify the
   plan covers every one. Check that error codes listed in the spec's error catalog (§7.4) appear
   in the plan's endpoint tables and contract test descriptions.

2. **Spec ↔ plan FR coverage**: verify every FR in the spec has a row in the plan's §1 traceability
   table and is assigned to at least one story.

3. **Story internal consistency**: for each story, verify:
   - The endpoint table matches the Pydantic schemas (field names, types).
   - The DoD assertions reference the correct error codes and HTTP status codes.
   - New files listed in the story are not also listed as new files in another story (no ownership conflict).
   - Modified files match reality (don't invent paths the codebase doesn't use).

4. **Test file count**: count the test files listed across all stories and verify the total matches
   the testing workstream (§3) inventory. Check the contract test file explicitly covers every error
   code in the spec's catalog.

5. **Gate arithmetic**: verify that epic/phase gate statements (e.g., "all 8 endpoints live") match
   the actual endpoint count from the stories below the gate.

6. **Open questions resolved**: confirm every open question from the spec's §18 is marked resolved
   with a decision log entry. Unresolved questions block plan execution.

7. **Plan ↔ codebase verification** (required for refactors): verify key claims in the plan against
   the actual codebase. At minimum:
   - State variable names and locations match (grep for each variable listed in removal/move lists).
   - Function names exist where claimed (e.g., don't reference `normalizeSettingsTab()` if it's inline logic).
   - Line number references are approximately correct (within ~20 lines of the actual code).
   - API endpoints used in the frontend match the backend router definitions.
   - State dependencies between components are correctly identified (check that state being removed
     isn't referenced by components/callbacks the plan doesn't account for).

   Document each verification with a finding (confirmed/corrected/flagged).

8. **Infrastructure path verification**: verify that file paths in "New files" tables match the
   actual project layout. Common mistakes:
   - Migration directory: check `alembic.ini` or `ls` the versions directory — don't assume
     `backend/app/db/migrations/versions/` vs `backend/alembic/versions/`.
   - Revision numbering: check the current Alembic head and use the next sequential number.
   - Router registration: verify how new routers are mounted (e.g., included in `main.py`
     with a prefix) by reading the existing registration pattern.

9. **Frontend data plumbing verification**: for every prop a story adds to a component, verify:
   - The parent component actually has access to that data (or the plan includes fetching it).
   - The data isn't only available in a sibling or unrelated component tree.
   - If a story says "pass X from page.tsx", confirm page.tsx currently fetches or can derive X.
   This prevents plans that claim "pass `best_metric` from the parent" when the parent fetches
   only the study summary (no metric details).

10. **Persistence scope consistency**: for stories that use `localStorage` or `sessionStorage`,
    verify that the task description and DoD agree on persistence scope. `localStorage` persists
    across sessions; `sessionStorage` clears when the tab closes. A mismatch between "use
    localStorage" in a task and "stays dismissed for the session" in the DoD is a bug.

11. **Enumerated value contract audit**: for every filter, sort key, status badge, tier/bucket
    label, role string, platform identifier, or other field the backend validates against a fixed
    allowlist, verify that the plan's frontend option lists match the backend source character-for-
    character:
    - The spec's §7.4 (Enumerated value contracts) table must be present and cite concrete backend
      source files for every enumerated field the feature touches.
    - For each frontend story that renders a `<select>`, filter dropdown, badge, or sort control
      whose values are sent back to the backend, the story's UI element inventory must enumerate
      every wire value (not just user-facing labels) and cite the backend source file.
    - Grep the cited backend source file(s) to confirm the exact allowlist. Flag any frontend option
      the backend does not accept, and any backend value the frontend fails to surface.
    - Require the plan to specify a source-of-truth comment above each generated option array
      (e.g., `// Values must match backend/db/models/study.py StudyStatus`) so
      future edits don't silently drift.
    **Why this matters:** Phantom values ("mid" tier, "drafting" bucket) look plausible but produce
    422 VALIDATION_ERROR responses or silent zero-result filters. TypeScript, lint, and unit tests
    do not catch this class of drift — only a grep-against-source audit does.

12. **Admin control and ceiling enforcement audit** (MVP4+ only — RelyLoop has no admin/tenant model in MVP1–MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../../01_architecture/tech-stack.md)). For MVP4+ plans that add admin-configurable defaults with tenant-level overrides: verify the plan includes a story for the platform_admin UI panel, ceiling validation on both create and update endpoints (not just Pydantic — values come from the DB), frontend input caps, and contract tests for ceiling boundaries (at ceiling → 200, above ceiling → 422).

13. **Audit-event coverage audit** (MVP2+ only — `audit_log` arrives at MVP2 per [`docs/01_architecture/data-model.md`](../../../../01_architecture/data-model.md)). For MVP2+ plans: for every endpoint or service function the plan adds or modifies that mutates state, verify the spec's §6 audit-event matrix lists the mutation site with a chosen event_type, the story includes an atomic `audit_log` INSERT inside the primary mutation's transaction, the metadata schema contains no credentials/tokens/PII beyond display-name strings, and the plan includes a contract test asserting the audit row's metadata shape. Mutations that do not need an audit event must be explicitly justified.


This review catches mismatches between the spec, plan, and codebase that would otherwise surface as
bugs or missing coverage during implementation.

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [ ] Every FR is mapped to stories/tasks/tests/docs updates.
- [ ] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD.
- [ ] Test layers (unit/integration/contract/e2e) are explicitly scoped.
- [ ] Documentation updates across docs/01-05 are planned and owned.
- [ ] Lean refactor scope and guardrails are explicit.
- [ ] Phase/epic gates are measurable and agreed by product + engineering.
- [ ] Story-by-Story Verification Gate is included.
- [ ] Plan consistency review (§11) has been performed with no unresolved findings.
