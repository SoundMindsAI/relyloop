# Implementation Plan — Judgment-list header renders the `click` (UBI) source bucket

**Date:** 2026-06-02
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) (frontend conventions, enumerated-value discipline, test layers), [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Smallest correct diff: this is a P2 render bug; the fix is localized to one presentational component + its tests.
- Fail-loud tests: vitest asserts the exact three-term render + label; E2E asserts browser-visible behavior on a real UBI list.
- No backend change, no migration, no `types:gen` regen (the wire field and TS type already exist).
- Keep the component presentational — no fetch, no recompute of `source_breakdown`.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 (render `click` term) | Epic 1 / Story 1.1 | Add third slash-joined term in `header-breakdown` cell |
| FR-2 (update label) | Epic 1 / Story 1.1 | `LLM / Human` → `LLM / Human / Clicks` |
| FR-3 (source-of-truth comment) | Epic 1 / Story 1.1 | Comment pointing at backend `_SourceBreakdown` |
| FR-4 (tooltip, SHOULD) | Epic 1 / Story 1.1 | Reuse `judgment.source.click` glossary key, or record no-tooltip decision |
| FR-1, FR-2 (E2E coverage) | Epic 1 / Story 1.2 | Real-backend Playwright assertion on a UBI list |

Single phase. No deferred FRs — no `phase<N>_idea.md` required.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** One epic, two stories (component+vitest, then E2E).

### Conventions (project-specific)

```
- ui/src/components/** are presentational where possible; page-level wrappers do data decisions.
- Component tests live in ui/src/__tests__/components/<area>/<name>.test.tsx (vitest + @testing-library/react).
- E2E lives in ui/tests/e2e/*.spec.ts (Playwright, real backend, NO page.route() mocking).
- Glossary keys live in ui/src/lib/glossary.ts; reuse existing keys, never duplicate.
- Display-only counts are NOT enumerated wire values — no enums.ts import / source-of-truth-import
  discipline; a plain // comment pointing at the backend shape is sufficient (spec D-3).
- Number display uses Number.prototype.toLocaleString() (matches existing header terms).
```

### AI Agent Execution Protocol (applies to every story)

0. Read `architecture.md` + `state.md` first.
1. Read story scope (outcome + UI inventory + DoD).
2. This feature has NO backend scope — skip backend steps.
3. Implement frontend (Story 1.1).
4. Run vitest for the touched component (`cd ui && pnpm test src/__tests__/components/judgments/judgment-list-header.test.tsx`).
5. Run E2E scope (Story 1.2) against the running stack.
6. Run `cd ui && pnpm lint && pnpm typecheck && pnpm build`.
7. No migration — skip round-trip.
8. Attach evidence (commands + pass/fail + files changed) in the PR description.
9. After the final story, evaluate `state.md` / `architecture.md` updates (see §4).

---

## Epic 1 — Render the click bucket in the judgment-list header

**Gate:** the `header-breakdown` cell renders `{llm} / {human} / {click}` with label `LLM / Human / Clicks`; vitest covers AC-1/AC-2/AC-3/AC-5; a real-backend E2E asserts the click count on a UBI list; lint/typecheck/build green.

### Story 1.1 — Render the third (`click`) term + update label + tests

**Outcome:** The judgment-list detail header shows all three source buckets so the displayed terms sum to the displayed total, and the doc-comment claim ("renders all three buckets separately") becomes true.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) | In the `header-breakdown` cell (lines 61–67 at audit time): add the `click` term (`list.source_breakdown.click.toLocaleString()`) as a third slash-joined value; change the `<dt>` label `LLM / Human` → `LLM / Human / Clicks`; add a source-of-truth comment above the render; optionally add an info tooltip on the label keyed to `judgment.source.click` (FR-4). |
| [`ui/src/__tests__/components/judgments/judgment-list-header.test.tsx`](../../../../ui/src/__tests__/components/judgments/judgment-list-header.test.tsx) | Add a `describe` block for the three-term breakdown: AC-1 (non-zero click → `0 / 2 / 5`), AC-2 (`10 / 2 / 0`), AC-3 (testid preserved), AC-5 (locale-formatted via runtime-computed expected), and assert the label reads `LLM / Human / Clicks`. Keep the existing 3 chip cases unchanged. |

**Endpoints**

N/A — no API surface added or modified. The component consumes the existing `GET /api/v1/judgment-lists/{id}` (`JudgmentListDetail.source_breakdown: _SourceBreakdown`).

**Key interfaces**

No new functions. The component signature is unchanged:

```tsx
// ui/src/components/judgments/judgment-list-header.tsx
export function JudgmentListHeader({
  list,                              // JudgmentListDetail — already carries source_breakdown.click
  showSyntheticUbiChip = false,
}: JudgmentListHeaderProps): JSX.Element
```

`list.source_breakdown.click` is type `number` (verified: `ui/src/lib/types.ts:3785-3792`), so no type change or `pnpm types:gen` is needed.

**Pydantic schemas**

N/A — no backend schema change. The contract source-of-truth remains `backend/app/api/v1/schemas.py:1017-1029` (`_SourceBreakdown`: `llm`/`human`/`click`).

**UI element inventory**

| Element | Type | Label/title | Data source | Interaction |
|---|---|---|---|---|
| Breakdown value cell (`data-testid="header-breakdown"`) | `<dd>` | renders `{llm} / {human} / {click}` | `list.source_breakdown.{llm,human,click}` | none (read-only) |
| Breakdown label | `<dt>` | `LLM / Human / Clicks` (was `LLM / Human`) | static | optional info tooltip (FR-4) |
| Info tooltip (FR-4, optional) | tooltip trigger (info icon) | text from `judgment.source.click` glossary | `ui/src/lib/glossary.ts:454` | `hover` / `focus` |

Nothing removed. The grid stays `md:grid-cols-4` (Total · Breakdown · Cohen's κ · Weighted κ). No new grid cell (spec D-1).

**State dependency analysis**

None. The component is presentational and stateless except the `kappaDisplay` helper; `source_breakdown.click` is already on the `list` prop forwarded by `JudgmentListHeaderWithSyntheticChip` (`ui/src/app/judgments/[id]/page.tsx:216`). No cross-component state changes.

**Tasks**
1. Edit the `header-breakdown` `<dd>` (lines ~61–67) to render three terms: `{list.source_breakdown.llm.toLocaleString()} / {list.source_breakdown.human.toLocaleString()} / {list.source_breakdown.click.toLocaleString()}`.
2. Change the adjacent `<dt>` label from `LLM / Human` to `LLM / Human / Clicks`.
3. Add a source-of-truth comment immediately above the breakdown render: `{/* Terms mirror backend/app/api/v1/schemas.py _SourceBreakdown (llm + human + click) */}` (FR-3).
4. (FR-4, default yes) Add an info tooltip on the label using the existing tooltip primitive (`@/components/ui/tooltip`, already imported by the test's `TooltipProvider`) keyed to the `judgment.source.click` glossary text. If the existing header has no `<dt>` tooltip precedent and adding one is awkward, keep the label bare and record the no-tooltip decision in the PR body + the §4 decision note (FR-4 is SHOULD).
5. Extend the vitest: add fixtures with non-zero `click`, assert the three-term value (AC-1/AC-2), the label text (FR-2), testid presence (AC-3), and locale formatting via runtime-computed expected string (AC-5). If the tooltip is implemented, add an assertion that the `judgment.source.click` help text is reachable.
6. Run `cd ui && pnpm test src/__tests__/components/judgments/judgment-list-header.test.tsx`, then `pnpm lint && pnpm typecheck`.

**Definition of Done (DoD)**
- `header-breakdown` cell renders `{llm} / {human} / {click}` and the label reads `LLM / Human / Clicks` (FR-1, FR-2).
- Source-of-truth comment present above the render (FR-3).
- FR-4: tooltip implemented reusing `judgment.source.click` (no new key), OR an explicit no-tooltip decision recorded in the PR body and §4 below.
- vitest covers AC-1 (`0 / 2 / 5`), AC-2 (`10 / 2 / 0`), AC-3 (testid preserved), AC-5 (locale-formatted, runtime-computed expected); existing 3 chip cases stay green.
- `pnpm lint`, `pnpm typecheck` green; `data-testid="header-breakdown"` unchanged.

### Story 1.2 — Real-backend E2E asserts the click count on a UBI list

**Outcome:** A Playwright test against the real backend confirms the header surfaces the click count when a list is generated from UBI, so the render fix is verified end-to-end with no mocking.

**New files**

None required (extend an existing spec). Optionally a new `ui/tests/e2e/judgments-header-click-bucket.spec.ts` if the team prefers isolation; default is to extend the existing UBI spec to reuse its seeding flow.

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/ubi-source-filter.spec.ts`](../../../../ui/tests/e2e/ubi-source-filter.spec.ts) | Add a test (or extend the existing one) that, after seeding UBI via `seedUbiForQuerySet` and generating a pure-CTR list, navigates to `/judgments/{listId}` and asserts the `header-breakdown` cell renders the exact three-term breakdown `0 / 0 / {clickCount}` (clickCount > 0) and the breakdown label reads `LLM / Human / Clicks` (AC-4). |

**Endpoints**

N/A. Test setup reads `GET /api/v1/judgment-lists?query_set_id=…` (already used in the spec) and may read `GET /api/v1/judgment-lists/{id}` to learn the exact `source_breakdown.click` for the assertion.

**Key interfaces**

Reuse the existing E2E helpers (no new helpers):

```ts
// ui/tests/e2e/helpers/seed.ts
seedQuerySet(n: number): Promise<{ clusterId; querySetId; queryIds }>
// ui/tests/e2e/helpers/seed_ubi.ts
seedUbiForQuerySet(opts): Promise<void>
teardownUbi(): Promise<void>
```

**Pydantic schemas**

N/A.

**UI element inventory**

| Element | Type | Assertion |
|---|---|---|
| `getByTestId('header-breakdown')` | `<dd>` | visible; text equals `0 / 0 / {clickCount}` with clickCount > 0 |
| breakdown label | `<dt>` | text contains `LLM / Human / Clicks` |

**State dependency analysis**

None — E2E exercises the rendered DOM, not component internals.

**Tasks**
1. In the existing UBI spec, after the pure-CTR list reaches `complete` and the page navigates to `/judgments/{listId}`, read the detail (`GET /api/v1/judgment-lists/{listId}`) to capture `source_breakdown.click` for the expected value (setup-only API read).
2. Assert via `page.getByTestId('header-breakdown')` that the rendered text equals `0 / 0 / {clickCount}` (use the same locale-agnostic comparison the component produces — compare against `clickCount.toLocaleString()` if thousands separators are possible, though seeded counts stay small).
3. Assert the breakdown label text contains `LLM / Human / Clicks`.
4. Run the spec against the running stack: `cd ui && pnpm exec playwright test tests/e2e/ubi-source-filter.spec.ts` (the agent runs this during execution, not in this planning task).

**Definition of Done (DoD)**
- The E2E asserts `header-breakdown` shows the exact `0 / 0 / {clickCount}` three-term shape on a real UBI-generated list (AC-4) — browser-visible, no `page.route()` mocking.
- The breakdown label assertion passes (`LLM / Human / Clicks`).
- Test uses Playwright `page` for the assertion (API `request` only for setup/teardown).

---

## UI Guidance (required for frontend-facing work)

### Reference: current component structure

**`ui/src/components/judgments/judgment-list-header.tsx`** — 83 lines, presentational.
- Lines 1–4: SPDX header.
- Lines 5–21: imports + `JudgmentListHeaderProps` (props: `list: JudgmentListDetail`, `showSyntheticUbiChip?: boolean`).
- Lines 23–39: `kappaDisplay()` helper (pure).
- Lines 41–82: `JudgmentListHeader` component. The `<dl>` grid (lines 56–76) has four cells:
  - Total judgments (`header-count`, lines 57–60)
  - **LLM / Human breakdown (`header-breakdown`, lines 61–67) ← insertion point**
  - Cohen's κ (`header-kappa`, lines 68–71)
  - Weighted κ (`header-weighted-kappa`, lines 72–75)
- No `useState`/`useMemo`/`useCallback`. Stateless.

**Insertion point:** modify the existing `<div>` at lines 61–67 in place. Nothing is added above/below in the grid; the change is contained to the breakdown cell's `<dt>` and `<dd>`.

### Analogous markup patterns

The breakdown cell today (the exact block to edit):

```tsx
{/* From judgment-list-header.tsx:61-67 (current — two terms) */}
<div>
  <dt className="text-xs uppercase text-muted-foreground">LLM / Human</dt>
  <dd data-testid="header-breakdown">
    {list.source_breakdown.llm.toLocaleString()} /{' '}
    {list.source_breakdown.human.toLocaleString()}
  </dd>
</div>
```

Target (three terms; preserve the testid):

```tsx
{/* Terms mirror backend/app/api/v1/schemas.py _SourceBreakdown (llm + human + click) */}
<div>
  <dt className="text-xs uppercase text-muted-foreground">LLM / Human / Clicks</dt>
  <dd data-testid="header-breakdown">
    {list.source_breakdown.llm.toLocaleString()} /{' '}
    {list.source_breakdown.human.toLocaleString()} /{' '}
    {list.source_breakdown.click.toLocaleString()}
  </dd>
</div>
```

Optional FR-4 tooltip — reuse the project's `@/components/ui/tooltip` primitive (the component test already wraps in `<TooltipProvider>`, so it renders in unit tests). Pattern (adapt to the codebase's existing info-icon tooltip usage — grep `Tooltip` / `TooltipTrigger` / `TooltipContent` for the canonical shape before implementing):

```tsx
<dt className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
  LLM / Human / Clicks
  <Tooltip>
    <TooltipTrigger aria-label="What is the Clicks bucket?">ⓘ</TooltipTrigger>
    <TooltipContent>{glossary['judgment.source.click'].short}</TooltipContent>
  </Tooltip>
</dt>
```

### Layout and structure

Unchanged. The `<dl>` stays `grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-4`. The breakdown cell remains the second of four cells. The third term extends the existing slash-joined string inline — no wrapping concern for typical counts; `gap-x-6` already spaces the four cells.

### Interaction behavior

None — read-only render. No handlers, no navigation, no cross-component callbacks. (The unrelated synthetic-UBI chip decision continues to live in the page-level `JudgmentListHeaderWithSyntheticChip` wrapper; this story does not touch it.)

### Component composition

Stays inline within `JudgmentListHeader`. No extraction — the change is two lines of JSX plus an optional tooltip. Rationale: extraction would add indirection for a two-term-to-three-term render change.

### Information architecture placement

No change. Header card at the top of `/judgments/[id]`. The breakdown cell keeps its position; only its label and value gain a third term.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment target |
|---|---|---|---|---|---|
| `LLM / Human / Clicks` label | `glossary['judgment.source.click'].short` ("Inferred from production click logs. Lower confidence than human or LLM ratings.") | `hover` / `focus` on info icon | `top` | `judgment.source.click` (existing, `ui/src/lib/glossary.ts:454`) | reuse existing glossary entry — no new key, no new source-of-truth comment needed beyond the FR-3 breakdown comment |

FR-4 is SHOULD. If implemented, the vitest must assert the help text is reachable. If skipped (no `<dt>` tooltip precedent), record the decision; the glossary key stays as-is.

### Visual consistency

| New element | Matches pattern | Source |
|---|---|---|
| third breakdown term | existing two-term slash-join | `judgment-list-header.tsx:64-66` |
| label `text-xs uppercase text-muted-foreground` | existing `<dt>` styling | `judgment-list-header.tsx:62`, `:69`, `:73` |
| optional tooltip primitive | existing `@/components/ui/tooltip` usage | grep `TooltipTrigger` in `ui/src/components` |

### Legacy behavior parity

No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated. The change is a two-line in-place extension of an 83-line presentational component; the `data-testid="header-breakdown"` attribute and all existing cells are preserved.

### Client-side persistence

N/A — no `localStorage`/`sessionStorage`/state.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: N/A — no backend change. The backend three-term breakdown is already covered by `feat_ubi_judgments` tests.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: N/A — no backend change.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: N/A — no API change.

### 3.4 vitest (component) — Story 1.1
- Location: `ui/src/__tests__/components/judgments/judgment-list-header.test.tsx`
- Tasks:
  - [ ] AC-1: fixture `{ llm: 0, human: 2, click: 5 }` → `header-breakdown` contains `0 / 2 / 5`.
  - [ ] AC-2: fixture `{ llm: 10, human: 2, click: 0 }` → `header-breakdown` contains `10 / 2 / 0`.
  - [ ] AC-3: `getByTestId('header-breakdown')` resolves (testid preserved).
  - [ ] FR-2: breakdown label text is `LLM / Human / Clicks`.
  - [ ] AC-5: fixture `{ llm: 1234, human: 0, click: 5678 }` → expected computed at runtime via `(1234).toLocaleString()` etc. (no hardcoded en-US punctuation).
  - [ ] FR-4 (if tooltip implemented): the `judgment.source.click` help text is reachable.
- DoD:
  - [ ] All new cases green; existing 3 chip cases unchanged and green.

### 3.4b E2E tests — Story 1.2
- Location: `ui/tests/e2e/ubi-source-filter.spec.ts` (extend) — real backend, no `page.route()` mocking.
- Tasks:
  - [ ] After the pure-CTR list completes, navigate to `/judgments/{listId}` and assert `header-breakdown` shows `0 / 0 / {clickCount}` (clickCount > 0) and the label reads `LLM / Human / Clicks` (AC-4).
- DoD:
  - [ ] Browser-visible assertion via `page`; `request` used only for setup/teardown.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/components/judgments/judgment-list-header.test.tsx` | base fixture `click: 0`; 3 chip cases | 1 | Add three-term + label cases; chip cases need NO change (they don't assert the breakdown text). |
| `ui/tests/e2e/judgments.spec.ts` | `getByTestId('header-count')` | 2 | No change — `header-count` testid is unaffected; `header-breakdown` is not asserted there. |
| `ui/tests/e2e/ubi-source-filter.spec.ts` | UBI seed → `/judgments/[id]` | 1 | Extended in Story 1.2 to add the `header-breakdown` assertion. |
| `ui/tests/e2e/demo-ubi.spec.ts` | `gen-method` etc. | — | No change — does not assert `header-breakdown`. |

### 3.5 Migration verification
- N/A — no schema change.

### 3.6 CI gates
- [ ] `cd ui && pnpm test` (vitest, includes the new cases)
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm build`
- [ ] `cd ui && pnpm exec playwright test tests/e2e/ubi-source-filter.spec.ts` (E2E, run against the stack)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — likely a one-line "Last 5 merges" entry when the fix merges (handled by the implementing PR, not this planning artifact). No Alembic head change, no branch-reality change beyond the merge.

**`architecture.md`** — no change required (no new service/flow/component).

**`CLAUDE.md`** — no change required (no new convention/env var; this fix follows existing frontend conventions).

### 4.1–4.5 Topical docs
- `docs/01_architecture/ui-architecture.md`: optional one-line note that the judgments header breakdown card shows all three source buckets. Not mandatory.
- `docs/02_product` / `03_runbooks` / `04_security` / `05_quality`: none.

**Documentation DoD**
- [ ] `state.md` "Last 5 merges" updated by the implementing PR.
- [ ] No other doc drift introduced.

### FR-4 decision note (to be finalized during execution)
- Default: implement the tooltip reusing `judgment.source.click`. If skipped, record here: "No tooltip added — rationale: `<no existing <dt> tooltip precedent / scope>`."

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals
- None beyond the fix. The change is minimal and in-place.

### 5.2 Planned refactor tasks
- [ ] None. (The stale backend docstring at `backend/app/db/repo/judgment.py:24-27` is a separate-subsystem tangential discovery tracked in `idea.md`; it is NOT bundled here because this is a frontend-only PR.)

### 5.3 Refactor guardrails
- [ ] Behavioral parity: existing chip cases stay green; `header-count`/`header-kappa`/`header-weighted-kappa` testids untouched.
- [ ] Lint/typecheck remain green.
- [ ] No product-scope expansion.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_ubi_judgments` (`click` term on `_SourceBreakdown` + TS type) | Story 1.1 | implemented (shipped 2026-05-29; verified) | none — shipped |
| Running stack with UBI seeding (ES/OpenSearch reachable) for E2E | Story 1.2 | available locally | E2E skips if no engine; vitest still proves the render |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Existing snapshot/test asserts the old two-term `header-breakdown` text | L | L | Impact audit (§3.5) confirms no test asserts the breakdown text today; only the new cases do. |
| `toLocaleString()` locale flakiness in CI | L | L | AC-5 mandates runtime-computed expected (per GPT-5.5 F2), not hardcoded en-US. |
| FR-4 tooltip has no `<dt>` precedent → awkward | M | L | FR-4 is SHOULD; fall back to bare label and record the decision (§4). |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| `source_breakdown.click` absent on an old cached response | stale client cache predating UBI | TS type guarantees `click: number`; backend always sends it now | n/a — backend invariant holds |
| All three buckets zero (empty list) | brand-new empty list | renders `0 / 0 / 0` with count 0 | n/a — correct |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 (component + vitest) — proves the render in isolation.
2. Story 1.2 (E2E) — proves it browser-visibly on a real UBI list.

### Parallelization opportunities
- Story 1.1 and the E2E assertion can be written in parallel, but 1.1 should land first so the testid/label the E2E asserts is stable.

## 8) Rollout and cutover plan

- Rollout: pure render change, no flag. Ships with the merge.
- Feature flag: none.
- Migration/cutover: none.
- Reconciliation: none — no external system.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — render `click` term + label + vitest
- [ ] Story 1.2 — real-backend E2E assertion

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate (Agent Checklist)

- [ ] Files modified match story scope (`Modified files` tables): `judgment-list-header.tsx`, its vitest, `ubi-source-filter.spec.ts`.
- [ ] No endpoint contract (N/A — no API surface).
- [ ] Key interfaces unchanged (component signature stable; `click` already typed).
- [ ] Tests added: vitest (AC-1/2/3/5 + label) + E2E (AC-4).
- [ ] Commands executed and passed:
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm lint`
  - [ ] `cd ui && pnpm typecheck`
  - [ ] `cd ui && pnpm build`
  - [ ] `cd ui && pnpm exec playwright test tests/e2e/ubi-source-filter.spec.ts` (if engines reachable)
- [ ] No migration (N/A).
- [ ] FR-4 decision recorded (tooltip implemented or no-tooltip rationale).

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** spec §7.1 = 0 endpoints; plan = 0 endpoints. Match.
2. **Spec ↔ plan error code coverage:** spec §7.5 = none; plan = none. Match.
3. **Spec ↔ plan FR coverage:** FR-1, FR-2, FR-3, FR-4 all mapped to Story 1.1; FR-1/FR-2 E2E to Story 1.2. All four FRs covered.
4. **Story internal consistency:** no schema (N/A); DoD references AC-1/2/3/5 + AC-4; no file owned by two stories (1.1 owns the component + vitest, 1.2 owns the E2E); modified files verified to exist (`judgment-list-header.tsx`, its test, `ubi-source-filter.spec.ts`).
5. **Test file count:** 2 frontend test files touched (1 vitest, 1 E2E) — matches §3.4 / §3.4b inventory.
6. **Gate arithmetic:** epic gate references the render + vitest + 1 E2E — matches the two stories.
7. **Open questions resolved:** spec §19 has none open; D-1/D-2/D-3 logged.
8. **Plan ↔ codebase verification:** `judgment-list-header.tsx` breakdown at lines 61–67 (Read-verified); `source_breakdown.click` typed `number` at `types.ts:3785-3792` (verified); page wrapper forwards full `list` at `page.tsx:216` (verified); glossary key `judgment.source.click` at `glossary.ts:454` (verified); `seedUbiForQuerySet`/`teardownUbi` exist in `ubi-source-filter.spec.ts` imports (verified).
9. **Frontend data plumbing:** `source_breakdown.click` already on the `list` prop — no new prop, no new fetch. Verified.
10. **Persistence scope:** N/A — no storage.
11. **Enumerated value contract audit:** the three source terms are display-only integer counts, NOT a `<select>`/filter/badge wire value (spec §7.4, D-3). No `enums.ts` import / source-of-truth-import discipline applies; a plain `// comment` pointing at `_SourceBreakdown` suffices (FR-3). The related `?source=` filter chips are out of scope and already grounded by `feat_ubi_judgments`. No drift risk introduced.
12. **Admin/ceiling audit:** N/A (no admin model pre-MVP4).
13. **Audit-event coverage audit:** N/A — no state-mutating endpoint or service function added or modified (read-only render). Spec §6 = N/A.

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR (FR-1…FR-4) mapped to stories/tasks/tests.
- [x] Every story includes New/Modified files, (N/A) Endpoints/Schemas, Tasks, DoD.
- [x] Test layers scoped: vitest (component) + E2E (real backend); backend layers N/A with justification.
- [x] Documentation updates planned (minimal — `state.md` merge line; optional ui-architecture note).
- [x] Lean refactor scope + guardrails explicit.
- [x] Epic gate measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed, no unresolved findings.

---

## Cross-model review log (impl-plan-gen Step 6)

**Reviewer:** GPT-5.5 (`gpt-5.5`) via OpenAI Chat Completions API (`urllib`, `max_completion_tokens`). Key resolved from `.env`. The plan was sent with the source spec as context.

### Verification ledger (material claims)

| Claim | Verified by | Status |
|---|---|---|
| Breakdown cell is at `judgment-list-header.tsx:61-67` | Read component | Verified |
| `source_breakdown.click` typed `number` in generated TS | Read `ui/src/lib/types.ts:3785-3792` | Verified — no `types:gen` |
| Page wrapper forwards full `list` (no plumbing change) | Read `ui/src/app/judgments/[id]/page.tsx:216` | Verified |
| Glossary key `judgment.source.click` exists | Read `ui/src/lib/glossary.ts:454` | Verified — reused |
| `seedUbiForQuerySet`/`teardownUbi` available for E2E | Read `ui/tests/e2e/ubi-source-filter.spec.ts:19,41` | Verified |
| Existing vitest covers only the FR-7 chip | Read `judgment-list-header.test.tsx` | Verified — extended |
| No endpoints / migration / audit / enumerated-value contract | Spec §7.x/§9/§6 + whole-plan audit | Verified |

### GPT-5.5 review cycles

**Cycle 1** — plan + source spec submitted. **0 findings.** GPT-5.5 returned `{"findings": []}` — no High/Medium/Low findings.

**Convergence:** reached after cycle 1 (zero findings → no corrections → no re-review trigger). Total: 1 cycle, 0 findings, 0 accepted, 0 rejected, 0 deferred.

**Note on review tooling:** the review script was hardened with a subject-anchor guard after an external process intermittently rewrote the spec-review prompt to an unrelated subject during the spec phase (see the spec's review log for detail). The plan-review cycle ran with the guard intact (`GUARD_INTACT` confirmed) and the correct judgment-header subject prompt.
