# Feature Specification — Judgment-list header renders the `click` (UBI) source bucket

**Date:** 2026-06-02
**Status:** Approved
**Owners:** Relevance Engineering (product), Frontend (engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md)
- [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)
- Originating feature: `feat_ubi_judgments` (shipped 2026-05-29)

---

## 1) Purpose

The judgment-list detail header at [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) renders a "source breakdown" card that shows only the `llm` and `human` buckets. Since `feat_ubi_judgments` (FR-10, shipped 2026-05-29) the wire shape `_SourceBreakdown` carries a third term, `click` (UBI-derived judgments), and the backend invariant is `llm + human + click == judgment_count`. The header silently drops `click`.

- **Problem:** A judgment list generated from UBI (or hybrid UBI+LLM) carries a non-zero `source_breakdown.click`, but the header card omits it. Operators reviewing a UBI list see only the LLM/human split and cannot tell how many judgments came from real click behavior — which is the entire value proposition of the UBI path. On a pure-CTR list (all `click`), the card reads `0 / 0`, which is actively misleading.
- **Outcome:** The header renders all three buckets (`llm`, `human`, `click`) so the displayed terms sum to the displayed total count, making the doc-comment claim ("the UI's source-breakdown card now renders all three buckets separately") true.
- **Non-goal:** No backend change, no new wire field, no migration, no new glossary key, no change to the source-filter chips in the judgments DataTable (that surface already honors `click` via `feat_ubi_judgments` FR-10).

## 2) Current state audit

### Existing implementations

- [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) — presentational header card. The breakdown cell (`<dd data-testid="header-breakdown">`, lines 61–67 at audit time) renders `list.source_breakdown.llm.toLocaleString() + ' / ' + list.source_breakdown.human.toLocaleString()`. The `<dt>` label reads `LLM / Human`. **This is the only file with the bug.** API: consumes the `list` prop typed `JudgmentListDetail`; no fetch of its own.
- [`ui/src/app/judgments/[id]/page.tsx`](../../../../ui/src/app/judgments/[id]/page.tsx) — `JudgmentListHeaderWithSyntheticChip` (lines 203–217) wraps the header and forwards the full `list` object. `list.source_breakdown.click` is already in the prop; **no plumbing change is needed.**
- [`backend/app/api/v1/judgments.py:148-152`](../../../../backend/app/api/v1/judgments.py) — `_detail()` populates `_SourceBreakdown(llm=…, human=…, click=…)` from `repo.source_breakdown_for_list`. Verified to return all three terms.
- [`backend/app/db/repo/judgment.py:282-307`](../../../../backend/app/db/repo/judgment.py) — `source_breakdown_for_list` returns `{"llm": N, "human": M, "click": K}` with invariant `llm + human + click == judgment_count`.
- [`backend/app/api/v1/schemas.py:1017-1029`](../../../../backend/app/api/v1/schemas.py) — Pydantic `_SourceBreakdown` declares `llm: int`, `human: int`, `click: int`. **Source-of-truth for the three display terms.**
- [`ui/src/lib/types.ts:3785-3792`](../../../../ui/src/lib/types.ts) — generated TS mirror `_SourceBreakdown` already has `click: number`. No `pnpm types:gen` regen needed.
- [`ui/src/lib/glossary.ts:454`](../../../../ui/src/lib/glossary.ts) — `judgment.source.click` glossary key already exists (short: "Inferred from production click logs. Lower confidence than human or LLM ratings."). Reused for the optional tooltip; no new key.

### Navigation and link impact

None. No URLs change.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/__tests__/components/judgments/judgment-list-header.test.tsx`](../../../../ui/src/__tests__/components/judgments/judgment-list-header.test.tsx) | `source_breakdown: { llm: 10, human: 2, click: 0 }` base fixture; 3 chip cases | 1 file | Add cases asserting the three-term render + updated label. Existing 3 chip cases unchanged. |
| [`ui/tests/e2e/judgments.spec.ts`](../../../../ui/tests/e2e/judgments.spec.ts) | `getByTestId('header-count')` | 2 refs | Unaffected (count testid unchanged). Optionally extend, but the canonical E2E goes through the UBI flow. |
| [`ui/tests/e2e/ubi-source-filter.spec.ts`](../../../../ui/tests/e2e/ubi-source-filter.spec.ts) | seeds UBI → pure-CTR list → `/judgments/[id]` | 1 file | Add a `header-breakdown` assertion (the new E2E reuses this exact seeding flow). |

### Existing behaviors affected by scope change

- Header breakdown cell label: Current: `LLM / Human`. New: `LLM / Human / Clicks`. Decision needed: no (locked D-1).
- Header breakdown cell value: Current: `{llm} / {human}`. New: `{llm} / {human} / {click}`. Decision needed: no (locked D-1).
- The `data-testid="header-breakdown"` attribute is **preserved** (no churn for existing selectors).

---

## 3) Scope

### In scope

- Render `source_breakdown.click` in the existing `header-breakdown` cell as a third slash-joined term, with the label updated to `LLM / Human / Clicks`.
- Add a source-of-truth comment above the breakdown render pointing at the backend `_SourceBreakdown` shape.
- Optionally surface the existing `judgment.source.click` glossary text via the established info-tooltip pattern on the breakdown label (D-2 default: yes).
- vitest coverage of the three-term render + updated label.
- Real-backend E2E coverage asserting the click count renders on a UBI-generated list.

### Out of scope

- Any backend change (the field is already on the wire and correct).
- A separate fourth grid cell for clicks (D-1 rejected this).
- A new glossary key (D-2 reuses the existing one).
- Changes to the judgments DataTable source-filter chips (already handle `click`).
- The stale module-level docstring at `backend/app/db/repo/judgment.py:24-27` (different subsystem; tracked in `idea.md` "Relationship to other work" for a future backend-touching PR).

### API convention check

No API endpoints added or modified. The component consumes the existing `GET /api/v1/judgment-lists/{id}` response (`JudgmentListDetail`), whose `source_breakdown` sub-shape is `_SourceBreakdown` (`backend/app/api/v1/schemas.py:1017-1029`). Endpoint prefix, error envelope, and pagination are unchanged. N/A for new routes.

### Phase boundaries (if multi-phase)

Single-phase. All work ships together. No deferred phases, no `phase<N>_idea.md` required.

## 4) Product principles and constraints

- The header card is **presentational** — it consumes the precomputed `list` prop and performs no fetch or business logic. Keep it that way (the FR-7 synthetic-chip decision already lives in the page-level wrapper).
- The displayed terms MUST sum to the displayed total (`judgment_count`) on a correct backend response — this is the backend invariant the card now faithfully reflects.
- Display-only integer counts are NOT enumerated wire values — no §7.4 allowlist discipline applies (D-3).

### Anti-patterns

- **Do not** fetch `source_breakdown` again or recompute it in the component — it is already on the `list` prop. Recomputing risks drift from the backend invariant.
- **Do not** add a backend field, migration, or `types:gen` regen — `click: number` already exists in `ui/src/lib/types.ts` and the wire shape.
- **Do not** mint a new glossary key for "clicks" — `judgment.source.click` already exists (D-2).
- **Do not** change or remove the `data-testid="header-breakdown"` attribute — existing and new selectors depend on it.
- **Do not** treat the three terms as a `<select>`/filter allowlist requiring source-of-truth-comment + enum-import discipline — they are read-only display counts, not wire values (D-3). A plain source-of-truth comment is sufficient.

## 5) Assumptions and dependencies

- Dependency: `feat_ubi_judgments` (the `click` bucket + three-term `_SourceBreakdown`).
  - Why required: provides the wire field this card must render.
  - Status: **implemented** (shipped 2026-05-29; verified at `schemas.py:1017-1029`, `judgments.py:148-152`, `judgment.py:282-307`, `types.ts:3785-3792`).
  - Risk if missing: none — it shipped.

## 6) Actors and roles

- Primary actor(s): Relevance Engineer / Viewer reviewing a judgment list detail page.
- Role model: N/A — single-tenant install, no auth surface (MVP2 per release matrix).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — this is a read-only render change. No state-mutating endpoint or service function is added or modified, so no `audit_log` emission applies.

## 7) Functional requirements

### FR-1: Render the `click` bucket in the source-breakdown card

- Requirement:
  - The header **MUST** render `list.source_breakdown.click` as a third term in the `header-breakdown` cell, formatted with `toLocaleString()` consistent with the existing `llm` and `human` terms.
  - The breakdown value **MUST** read `{llm} / {human} / {click}` (e.g. `10 / 2 / 5`).
  - The `data-testid="header-breakdown"` attribute **MUST** be preserved unchanged.
- Notes: The three displayed integers sum to `judgment_count` on a correct backend response (the backend invariant). The component does not assert the invariant; it faithfully renders whatever the wire provides.

### FR-2: Update the breakdown label

- Requirement:
  - The `<dt>` label **MUST** read `LLM / Human / Clicks` (replacing `LLM / Human`).
- Notes: Term order matches the value order (`llm`, `human`, `click`) so the label maps 1:1 to the slash-joined value.

### FR-3: Source-of-truth comment

- Requirement:
  - A source-of-truth comment **MUST** be added above the breakdown render: `// Terms mirror backend/app/api/v1/schemas.py _SourceBreakdown (llm + human + click)`.
- Notes: Tracks the wire shape so a future fourth term is caught.

### FR-4: Contextual help (tooltip) for the click term

- Requirement:
  - The header **SHOULD** surface the existing `judgment.source.click` glossary text via the established info-tooltip pattern on the breakdown label.
  - The implementation **MUST NOT** mint a new glossary key (reuse `judgment.source.click`).
- Notes: D-2 default is to add the tooltip. If the established header pattern has no precedent for a label tooltip, the label may stay bare (low risk — "Clicks" is self-describing); record the choice in the plan. The component test already wraps in `TooltipProvider`, so a tooltip is renderable in unit tests.

## 8) API and data contract baseline

### 7.1 Endpoint surface (if applicable)

N/A — no endpoints added or modified. The component consumes the existing `GET /api/v1/judgment-lists/{id}` (`JudgmentListDetail` with `source_breakdown: _SourceBreakdown`).

### 7.2 Contract rules

N/A — no new contract. The existing `_SourceBreakdown` wire shape (`llm: int`, `human: int`, `click: int`) is the contract this render honors.

### 7.3 Response examples

The existing detail response (unchanged) — for reference, the `source_breakdown` sub-object on a UBI list:

```json
{
  "id": "0190...",
  "name": "demo-ubi-list",
  "status": "complete",
  "judgment_count": 7,
  "source_breakdown": { "llm": 0, "human": 2, "click": 5 },
  "calibration": null,
  "generation_params": { "generation_kind": "ubi" },
  "created_at": "2026-05-29T00:00:00Z"
}
```

No new failure shapes — the component renders client-side from an already-fetched response. The page-level `useJudgmentList` query already handles the `ApiError` envelope.

### 7.4 Enumerated value contracts (required for any feature with filters, status badges, sort keys, or dropdowns)

N/A — the three source terms (`llm`, `human`, `click`) are **display-only integer counts**, not wire values sent from the frontend to the backend. They are not a `<select>`, filter chip, sort key, or status badge. No allowlist-grounding (`Literal`/`frozenset`/`enums.ts` import) discipline applies (D-3).

The closest related enumerated contract — the judgments DataTable `?source=` filter chips (`llm` / `human` / `click`) — is **out of scope** and already grounded by `feat_ubi_judgments`; this feature does not touch it.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| N/A (display-only counts) | `llm`, `human`, `click` are object **keys**, not wire values | `backend/app/api/v1/schemas.py` (`_SourceBreakdown`) | `judgment-list-header.tsx` breakdown cell (read-only render) |

### 7.5 Error code catalog (if API-heavy)

N/A — no new error codes.

## 9) Data model and state transitions

### New/changed entities

None. No table, column, or migration. The `_SourceBreakdown` wire shape already carries `click`.

### Required invariants

- Display invariant (backend-enforced, not asserted by the component): `source_breakdown.llm + source_breakdown.human + source_breakdown.click == judgment_count`. The card renders all three so the sum is now visible.

### State transitions

N/A — read-only render.

### Idempotency/replay behavior (if event-driven)

N/A.

## 10) Security, privacy, and compliance

- Threats: none introduced — rendering an integer that is already on the wire and already type-exposed to the component.
- Controls: N/A.
- Secrets/key handling: N/A — no secrets touched.
- Auditability: N/A — no mutation.
- Data retention/deletion/export impact: none.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No change. The header card sits at the top of `/judgments/[id]`, inside `JudgmentListHeader`, in the existing `dl` grid (`md:grid-cols-4`): Total judgments · LLM / Human / Clicks · Cohen's κ · Weighted κ.
- **Labeling taxonomy:** Breakdown label changes `LLM / Human` → `LLM / Human / Clicks`. "Clicks" matches the user-facing terminology already used for the `judgment.source.click` glossary entry and the DataTable source-filter chip.
- **Content hierarchy:** Unchanged — breakdown is the second cell in the four-cell grid, always visible.
- **Progressive disclosure:** None — all three terms shown inline.
- **Relationship to existing pages:** Extends the existing header in place; no new page or tab.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---------|-------------------|---------|-----------|--------------|
| `LLM / Human / Clicks` breakdown label | "Inferred from production click logs. Lower confidence than human or LLM ratings." (the `click` term's meaning) | `hover` / `focus` on an info icon next to the label | `top` / inline | `judgment.source.click` (existing — `ui/src/lib/glossary.ts:454`) |

The tooltip is FR-4 (SHOULD). It reuses the existing glossary key — no new key is added. If the existing header has no info-tooltip precedent on a `<dt>`, the plan may keep the label bare and record the decision; in that case the glossary key remains unused by this feature (acceptable).

### Primary flows

1. Operator opens a UBI-generated judgment list at `/judgments/[id]`. The header breakdown cell shows e.g. `0 / 2 / 5` under `LLM / Human / Clicks`, matching the total of 7. They can see 5 of 7 judgments came from real clicks.
2. Operator opens a pure-LLM list. The cell shows `10 / 2 / 0` — identical informational content to today for non-UBI lists, with the new trailing `/ 0`.

### Edge/error flows

- `source_breakdown.click === 0`: renders `… / 0` (consistent with how `llm`/`human` already render zeros). No special-casing.
- All three zero (empty list): renders `0 / 0 / 0` with `judgment_count` 0 — consistent and correct.
- Large counts: `toLocaleString()` applies thousands separators to all three terms, matching existing behavior.

## 12) Given/When/Then acceptance criteria

### AC-1: UBI list shows the click count in the header

- Given a judgment list with `source_breakdown = { llm: 0, human: 2, click: 5 }` and `judgment_count = 7`
- When the operator views `/judgments/[id]`
- Then the `header-breakdown` cell renders `0 / 2 / 5` and the label reads `LLM / Human / Clicks`
- Example values:
  - Input: `source_breakdown: { llm: 0, human: 2, click: 5 }`
  - Expected: `header-breakdown` text contains `0 / 2 / 5`; label text is `LLM / Human / Clicks`

### AC-2: Pure-LLM list still renders correctly with a trailing zero

- Given a judgment list with `source_breakdown = { llm: 10, human: 2, click: 0 }`
- When the operator views the header
- Then the `header-breakdown` cell renders `10 / 2 / 0`

### AC-3: testid preserved

- Given the header is rendered
- When a test selects `getByTestId('header-breakdown')`
- Then the element exists (the attribute is unchanged from the prior implementation)

### AC-4 (E2E): real UBI-generated list surfaces clicks browser-visibly

- Given a UBI generation seeded via `seedUbiForQuerySet` produces a pure-CTR list (`llm == 0`, `human == 0`, `click > 0`)
- When the test navigates to `/judgments/[id]` in a real browser against the real backend
- Then `getByTestId('header-breakdown')` is visible and renders the full three-term breakdown `0 / 0 / {clickCount}` (with `clickCount > 0`), and the breakdown label reads `LLM / Human / Clicks`
- Notes: assert the exact three-term shape (not merely "contains a non-zero number") so the E2E enforces the same `{llm} / {human} / {click}` contract as FR-1/FR-2. The exact `clickCount` may be read from the detail API in test setup, then asserted against the rendered cell.

### AC-5: thousands separators

- Given `source_breakdown = { llm: 1234, human: 0, click: 5678 }`
- When the header renders
- Then each term is locale-formatted via `toLocaleString()`, matching the existing formatting of the other terms (e.g. `1,234 / 0 / 5,678` in an en-US runtime)
- Notes: the vitest assertion **MUST compute the expected string at runtime** with the same `Number.prototype.toLocaleString()` call (e.g. `${(1234).toLocaleString()} / ${(0).toLocaleString()} / ${(5678).toLocaleString()}`) rather than hardcoding en-US punctuation — default-locale output varies by Node/CI locale, so a hardcoded `1,234` literal would be flaky. (Per GPT-5.5 cycle-1 finding F2.)

## 13) Non-functional requirements

- Performance: negligible — one additional `.toLocaleString()` call on a number already in memory.
- Reliability: no new failure mode; the component already renders from the fetched `list` prop.
- Operability: no logging/metrics change.
- Accessibility/usability: the label clearly enumerates all three sources; if the tooltip is added it must be keyboard-focusable (the established info-tooltip pattern already is).

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`): N/A — no backend change.
- Integration tests (`backend/tests/integration/`): N/A — no backend change. The backend three-term breakdown is already covered by `feat_ubi_judgments` tests.
- Contract tests (`backend/tests/contract/`): N/A — no API change.
- vitest (component) (`ui/src/__tests__/components/judgments/judgment-list-header.test.tsx`): MUST add cases asserting (a) three-term render `{llm} / {human} / {click}` for a non-zero-click fixture, (b) the label reads `LLM / Human / Clicks`, (c) `header-breakdown` testid preserved, (d) thousands separators (AC-5). Existing 3 chip cases stay green.
- E2E tests (`ui/tests/e2e/`): MUST assert the header click count on a real UBI-generated list (real backend, no `page.route()` mocking), reusing the `ubi-source-filter.spec.ts` UBI-seeding flow.

## 15) Documentation update requirements

- `docs/01_architecture`: optional — `ui-architecture.md` mentions the judgments header only in passing; a one-line note that the breakdown card shows all three source buckets is sufficient if any change is made. No mandatory update.
- `docs/02_product`: none.
- `docs/03_runbooks`: none.
- `docs/04_security`: none.
- `docs/05_quality`: none.

Note: per the task constraints, this planning artifact does not modify `state.md`, dashboards, or `CLAUDE.md`; the implementing PR will handle any doc/state updates.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: none — a pure render change, ships behind no flag.
- Migration/backfill expectations: none — no schema change.
- Operational readiness gates: vitest + E2E green; `pnpm lint` + `pnpm typecheck` green.
- Release gate: the `pr.yml` frontend job (lint + tsc + vitest + Next.js build) and the e2e suite for the affected spec.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3, AC-5 | Story 1.1 | `judgment-list-header.test.tsx`, `ubi-source-filter.spec.ts` (or sibling) | — |
| FR-2 | AC-1 | Story 1.1 | `judgment-list-header.test.tsx` | — |
| FR-3 | (covered by code review) | Story 1.1 | n/a (comment) | — |
| FR-4 | §18 DoD tooltip checkbox (not AC-1) | Story 1.1 | `judgment-list-header.test.tsx` (asserts the `judgment.source.click` help text is wired) **OR** the recorded no-tooltip decision in the plan if no header-label tooltip precedent exists | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] FR-1 through FR-3 implemented in `judgment-list-header.tsx`.
- [ ] FR-4 implemented (tooltip on the breakdown label reusing `judgment.source.click`), OR an explicit no-tooltip decision recorded in the plan if no suitable header-label tooltip precedent exists. (FR-4 is SHOULD-level per §7; this preserves its optionality — GPT-5.5 cycle-1 finding F1.)
- [ ] vitest cases for AC-1, AC-2, AC-3, AC-5 pass; existing chip cases stay green.
- [ ] Real-backend E2E asserts the click count renders on a UBI list (AC-4).
- [ ] `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` are green.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None. All forks were locked during idea-preflight.

### Decision log

- 2026-06-02 — **D-1: Three-term inline render in the existing `header-breakdown` cell** (slash-joined `{llm} / {human} / {click}`, label `LLM / Human / Clicks`), not a separate fourth grid cell. Rationale: minimal diff, preserves the `data-testid`, matches the existing two-term pattern; the grid is already full at four cells.
- 2026-06-02 — **D-2: Reuse the existing `judgment.source.click` glossary key for the optional tooltip; do not mint a new key.** Default is to add the tooltip on the breakdown label; if no header label-tooltip precedent exists, the plan may keep the label bare and record the choice.
- 2026-06-02 — **D-3: The three source terms are display-only integer counts, not wire values** — §7.4 enumerated-value-contract discipline does not gate this change. A plain source-of-truth comment pointing at `_SourceBreakdown` is added (FR-3).
- 2026-06-02 — Verified `click` is already on the wire (`schemas.py:1017-1029`, `judgments.py:148-152`, `judgment.py:282-307`) and in the generated TS type (`types.ts:3785-3792`); confirmed pure-frontend scope, no backend/migration/types-regen.

---

## Cross-model review log (spec-gen Step 6)

**Reviewer:** GPT-5.5 (`gpt-5.5`) via OpenAI Chat Completions API (`urllib`, `max_completion_tokens`). Key resolved from `.env`.

### Verification ledger (material claims)

| Claim | Verified by | Status |
|---|---|---|
| `_SourceBreakdown` has `llm`/`human`/`click` (int) | Read `backend/app/api/v1/schemas.py:1017-1029` | Verified |
| Detail serializer populates all three | Read `backend/app/api/v1/judgments.py:148-152` | Verified |
| `source_breakdown_for_list` returns 3-term dict, invariant `llm+human+click==count` | Read `backend/app/db/repo/judgment.py:282-307` | Verified |
| Generated TS `_SourceBreakdown` already has `click: number` | Read `ui/src/lib/types.ts:3785-3792` | Verified — no `types:gen` regen |
| Header renders only `llm`/`human` (the bug) | Read `ui/src/components/judgments/judgment-list-header.tsx:61-67` | Verified |
| `data-testid="header-breakdown"` exists today | Read same file | Verified — preserved by fix |
| Page wrapper already forwards full `list` (no plumbing change) | Read `ui/src/app/judgments/[id]/page.tsx:203-217` | Verified |
| `judgment.source.click` glossary key exists | Read `ui/src/lib/glossary.ts:454` | Verified — reused, no new key |
| Existing vitest only covers the FR-7 chip | Read `ui/src/__tests__/components/judgments/judgment-list-header.test.tsx` | Verified |
| Real-backend UBI E2E seeding flow exists | Read `ui/tests/e2e/ubi-source-filter.spec.ts` | Verified — extended for AC-4 |
| No endpoints/migration/audit added | Whole-spec audit | Verified — pure render change |

### GPT-5.5 review cycles

**Cycle 1** — 3 findings, all severity **Low**, all **Accepted**:

| # | Pass | Severity | Finding | Verdict | Action |
|---|---|---|---|---|---|
| F1 | B | Low | §18 DoD says "FR-1 through FR-4 implemented" but FR-4 is SHOULD-level — makes the optional tooltip effectively mandatory. | **Accept** | §18 reworded to "FR-1 through FR-3 implemented; FR-4 implemented OR explicit no-tooltip decision recorded." |
| F2 | B | Low | AC-5 hardcodes en-US `toLocaleString()` output; default locale varies by Node/CI runtime → flaky test. | **Accept** | AC-5 now requires the test to compute the expected string at runtime via `toLocaleString()` instead of hardcoding punctuation. |
| F3 | B | Low | AC-4 (E2E) only requires the cell to "contain a non-zero number," weaker than the FR-1/FR-2 three-term contract. | **Accept** | AC-4 strengthened to assert the exact `0 / 0 / {clickCount}` three-term shape + the `LLM / Human / Clicks` label on a pure-CTR list. |

No High or Medium findings.

**Cycle 2** — re-reviewed the patched spec. 1 finding, severity **Low**, **Accepted**:

| # | Pass | Severity | Finding | Verdict | Action |
|---|---|---|---|---|---|
| F4 | A | Low | §17 traceability maps FR-4 → AC-1, but AC-1 doesn't cover the tooltip/no-tooltip decision FR-4/§18 require. | **Accept** | §17 FR-4 row retargeted to the §18 DoD tooltip checkbox + the component test that wires `judgment.source.click` (or the recorded no-tooltip decision). |

No High or Medium findings in cycle 2. The F4 fix touched only the traceability matrix (not an endpoint, data-model, AC, or auth element), so no further cross-model cycle is triggered.

**Convergence:** reached after cycle 2 (two cycles produced only Low findings, all accepted and applied; no High/Medium in either cycle). Total: 2 cycles, 4 findings, 4 accepted, 0 rejected, 0 deferred.

**Note on review tooling:** during this session an external process intermittently rewrote the review script's system prompt to describe an unrelated backend test-isolation bug. The corrupted cycle produced 4 spurious "wrong subject" findings (3 High, 1 Medium) that were all **rejected as artifacts of the tampered prompt** — they complained the (correct) judgment-header spec did not match a feature it was never about. The review script was hardened with a subject-anchor guard and the genuine cycle-2 review (above) was run against the correct prompt. The 4 spurious findings are not counted in the convergence tally.
