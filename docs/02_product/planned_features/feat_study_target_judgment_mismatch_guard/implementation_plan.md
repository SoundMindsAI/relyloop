# Implementation Plan — feat_study_target_judgment_mismatch_guard

**Date:** 2026-05-21
**Status:** Draft
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [api-conventions.md](../../../01_architecture/api-conventions.md), [CLAUDE.md](../../../../CLAUDE.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from the spec.
- One epic, three stories — the feature is bounded enough that a single epic gate is sufficient.
- Backend wire surface ships before the frontend filter (Story 1.1 → Story 2.1 dependency).
- Backend validators (Story 1.2) are independent and can ship in any order vs Story 1.1, but conventionally land first because they're the contract.
- Single PR: all three stories land in one branch + one PR. The scope is small (~100 LOC + ~80 LOC tests) and the artifacts are tightly coupled (frontend depends on backend, contract tests assert on shipped envelopes).

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (target mismatch validator) | Epic 1 / Story 1.2 | New 422 `JUDGMENT_TARGET_MISMATCH` block after FR-1b cluster check. |
| FR-1b (cluster_id mismatch validator) | Epic 1 / Story 1.2 | New 422 `JUDGMENT_CLUSTER_MISMATCH` block before FR-1 target check. |
| FR-2 (`?target=` listing filter) | Epic 1 / Story 1.1 | Add wire param + thread through `list_judgment_lists` + `count_judgment_lists`. |
| FR-3 (`target` on `JudgmentListSummary`) | Epic 1 / Story 1.1 | Add field on Pydantic model + populate via `_summary()`. |
| FR-4 (frontend filter + cascade + empty state) | Epic 1 / Story 2.1 | Extend `useJudgmentLists` filter, cascade reset, empty-state copy. |

All 5 FRs covered. No phase boundary (single-phase ship per spec §3). No tracking file for deferred phases needed.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions (project-specific)

Honors all RelyLoop conventions from `CLAUDE.md`:
- All repo functions take `db: AsyncSession` as first arg; use `db.flush()` (caller commits)
- Routers return typed Pydantic response models; errors use the `_err(...)` helper at `studies.py:74-78` / `judgments.py:86-90` which raises `HTTPException` with the canonical `{detail: {error_code, message, retryable}}` envelope.
- Pydantic v2 models with non-optional fields when the underlying ORM column is `NOT NULL`.
- Frontend: `<select>` wire-value contracts grounded in backend source-of-truth files per CLAUDE.md "Enumerated Value Contract Discipline" — though this feature does not add new `<select>` options (only a filter param on an existing wire).
- Conventional Commits format for every commit (`feat(...)`, `test(...)`, `docs(...)`).

### AI Agent Execution Protocol

0. Load context: `architecture.md`, `state.md`, this plan, the spec.
1. Implement Story 1.1 first (backend listing extension) — frontend Story 2.1 depends on it.
2. Implement Story 1.2 (validators) — independent; runs in parallel with 1.1 if a second engineer is available.
3. Implement Story 2.1 (frontend filter + cascade + empty state).
4. Run backend tests (unit + integration + contract subset for touched endpoints) after Story 1.1 and Story 1.2.
5. Run frontend tests (vitest) after Story 2.1.
6. Regenerate OpenAPI types: `make openapi-export` (or the project's equivalent) — verify `ui/src/lib/types.ts` reflects the new `target` summary field + the new `?target=` query param.
7. Update `docs/01_architecture/api-conventions.md` (both new error code rows) and `state.md` (recent changes) in the same PR.
8. Run `make lint`, `make typecheck`, `cd ui && pnpm typecheck && pnpm lint && pnpm build`.
9. Attach evidence in the PR description.

---

## Epic 1 — Reject mismatched-target studies at create time

### Story 1.1 — Extend GET /api/v1/judgment-lists with target filter + summary field

**Outcome:** `GET /api/v1/judgment-lists?target=<X>` filters to lists with that target, with `X-Total-Count` mirroring the filter; `JudgmentListSummary` carries the new `target` field so the frontend can render target-aware UI without per-row detail fetches.

**Traces to:** FR-2, FR-3.

**New files**

None. All edits are additive to existing files.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `target: str` (non-nullable) to `JudgmentListSummary` at lines 760-769 (between `cluster_id` and `status` to mirror `JudgmentListDetail` order at lines 772-788). |
| `backend/app/api/v1/judgments.py` | Update `_summary(row)` at lines 113-122 to populate `target=row.target`. Add `target: Annotated[str \| None, Query(min_length=1, max_length=255)] = None` query param to `list_judgment_lists_endpoint` at lines 339-348 and thread to `repo.list_judgment_lists(target=target, ...)` + `repo.count_judgment_lists(target=target, ...)`. |
| `backend/app/db/repo/judgment_list.py` | Add `target: str \| None = None` keyword arg to `list_judgment_lists` (lines 58-68) and `count_judgment_lists` (lines 115-122). Apply `if target is not None: stmt = stmt.where(JudgmentList.target == target)` in BOTH functions (mirror the existing `query_set_id` / `cluster_id` pattern at lines 87-90 + 133-136). |
| `backend/app/db/repo/__init__.py` | No change — `list_judgment_lists` and `count_judgment_lists` are already exported. |
| `ui/src/lib/types.ts` | **Generated artifact** — regenerated from live OpenAPI as part of Story 1.1 Task #5. Owned by Story 1.1 because that's the story that changes the backend OpenAPI surface. Story 2.1 consumes the regenerated types. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/judgment-lists` | — (query params: `cursor`, `limit`, `since`, `q`, `sort`, `query_set_id`, `cluster_id`, **`target` (new)**) | `200` `JudgmentListListResponse` with `X-Total-Count` header. Each `data[].target: str` (new field). | `VALIDATION_ERROR` (422) via `errors.py:102-118` for cursor decode or bounds violations. No new error codes. |

**Pydantic schemas**

```python
# backend/app/api/v1/schemas.py
class JudgmentListSummary(BaseModel):
    """List-view row on ``GET /api/v1/judgment-lists``."""
    id: str
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str  # NEW — non-nullable, mirrors underlying Text NOT NULL column
    status: JudgmentListStatusWire
    created_at: datetime
```

**Key interfaces**

```python
# backend/app/db/repo/judgment_list.py
async def list_judgment_lists(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
    query_set_id: str | None = None,
    cluster_id: str | None = None,
    target: str | None = None,  # NEW
) -> list[JudgmentList]: ...

async def count_judgment_lists(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
    query_set_id: str | None = None,
    cluster_id: str | None = None,
    target: str | None = None,  # NEW
) -> int: ...
```

**Tasks**

1. Add `target: str` field to `JudgmentListSummary` in `schemas.py` (alphabetically positioned per existing convention).
2. Update `_summary(row)` in `judgments.py:113-122` to populate `target=row.target`.
3. Add `target` query param to `list_judgment_lists_endpoint` in `judgments.py` with the right `min_length=1, max_length=255` bounds.
4. Add `target` keyword arg to `list_judgment_lists` and `count_judgment_lists` repo functions; mirror the `WHERE judgment_lists.target = target` clause from the existing `query_set_id`/`cluster_id` filters.
5. Regenerate `ui/src/lib/types.ts` from live OpenAPI. The project's standard regen workflow is the canonical path (check `Makefile` and `package.json` scripts for the existing command; if none exists, this PR must wire one — manual hand-edits of `types.ts` are NOT permitted because they drift from the OpenAPI source).
6. Audit existing UI fixtures: `grep -rn "JudgmentListSummary\|JudgmentListListResponse" ui/src/ ui/tests/` to find every object literal constructed against the summary type. Add `target: '<something>'` to each (existing tests typically use `'products'` or `'e2e-target'`). This is an additive type change — `pnpm typecheck` will surface every drop.

**Definition of Done**

- [ ] `GET /api/v1/judgment-lists?target=products` returns only rows with `target=products` (integration test asserts data array AND `X-Total-Count` header match).
- [ ] `GET /api/v1/judgment-lists?target=products&cluster_id=C1&query_set_id=Q1` applies AND-semantics (integration test #5 from spec §14).
- [ ] `GET /api/v1/judgment-lists?target=&lt;empty&gt;` returns 422 with `error_code = "VALIDATION_ERROR"` (FastAPI `min_length` violation routed through `errors.py:validation_exception_handler`).
- [ ] `GET /api/v1/judgment-lists?target=&lt;256 chars&gt;` returns 422 with `error_code = "VALIDATION_ERROR"`.
- [ ] Every `JudgmentListSummary` response includes `target: str` (contract test asserts OpenAPI shape).
- [ ] OpenAPI snapshot contract test passes after `JudgmentListSummary.target` is recognized as required.
- [ ] `ui/src/lib/types.ts` regenerated and shows `target: string` on `JudgmentListSummary`.

---

### Story 1.2 — POST /api/v1/studies cross-entity validators (cluster + target)

**Outcome:** `POST /api/v1/studies` rejects mismatched-cluster and mismatched-target judgment-list pairings with two new specific 422 error codes (`JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`), in firing order: FR-1b (cluster) before FR-1 (target).

**Traces to:** FR-1, FR-1b.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | Insert two new `if`-blocks between the existing `query_set_id` check at lines 240-247 and the config serialization at line 249. Block 1 (FR-1b, cluster check) at the new lines 248-256 (approx). Block 2 (FR-1, target check) at the new lines 257-265 (approx). Both use the existing `_err(...)` helper at line 74. |
| `backend/tests/contract/test_studies_api_contract.py` | Add ordering-test cases asserting the firing sequence `JUDGMENT_LIST_NOT_FOUND` (404) → `VALIDATION_ERROR` (query_set mismatch, 422) → `JUDGMENT_CLUSTER_MISMATCH` (422) → `JUDGMENT_TARGET_MISMATCH` (422). Contract-layer assertion locks the order so a future refactor reordering the if-blocks fails CI. |
| `docs/01_architecture/api-conventions.md` | Add two new rows to the studies-endpoint error-code table (after `SEARCH_SPACE_MISSING_DECLARED_PARAM` at lines 76-77): `JUDGMENT_CLUSTER_MISMATCH` (422, retryable=false) and `JUDGMENT_TARGET_MISMATCH` (422, retryable=false), in firing order. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | `CreateStudyRequest` (unchanged shape from `schemas.py:589`) | `201` `StudyDetail` (unchanged) | **`JUDGMENT_CLUSTER_MISMATCH` (422 — new)**, **`JUDGMENT_TARGET_MISMATCH` (422 — new)**, plus existing: `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `INVALID_SEARCH_SPACE` (400), `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400), `VALIDATION_ERROR` (422). |

**Pydantic schemas**

No new schemas. `CreateStudyRequest` already has `cluster_id`, `target`, and `judgment_list_id` fields.

**Key interfaces**

No new functions. Two new `if`-blocks inside the existing `create_study` handler:

```python
# backend/app/api/v1/studies.py — between the existing query_set_id check
# (line 247) and the config serialization (line 249).

# FR-1b: cluster_id consistency. Fires BEFORE the target check because cluster
# mismatch is the broader failure — even with matching target name, distinct
# physical clusters have distinct doc IDs.
if judgment_list.cluster_id != body.cluster_id:
    raise _err(
        422,
        "JUDGMENT_CLUSTER_MISMATCH",
        (
            f"judgment_list cluster_id={judgment_list.cluster_id!r} does not "
            f"match study cluster_id={body.cluster_id!r}; judgments are scoped "
            f"to the cluster they were authored on. Pick a judgment list "
            f"created against cluster {body.cluster_id!r} or change the "
            f"study's cluster."
        ),
        False,
    )

# FR-1: target consistency. Fires AFTER the cluster check.
if judgment_list.target != body.target:
    raise _err(
        422,
        "JUDGMENT_TARGET_MISMATCH",
        (
            f"judgment_list target={judgment_list.target!r} does not match "
            f"study target={body.target!r}; judgments would have no overlap "
            f"with search results from the study's target. Use a judgment "
            f"list generated against {body.target!r} or change study.target "
            f"to {judgment_list.target!r}."
        ),
        False,
    )
```

**Tasks**

1. Add the two `if`-blocks to `studies.py` between lines 247 and 249. Cluster check first (FR-1b), then target check (FR-1).
2. Add two new rows to `docs/01_architecture/api-conventions.md` error-code table (after `SEARCH_SPACE_MISSING_DECLARED_PARAM` at lines 76-77). Both rows: HTTP 422, `retryable: false`, with the same message guidance as the spec §7.5.

**Definition of Done**

- [ ] `POST /api/v1/studies` with mismatched `cluster_id` returns 422 `JUDGMENT_CLUSTER_MISMATCH` AND no `studies` row is inserted AND no Arq job is enqueued (integration assertion uses an Arq spy/mock + `SELECT COUNT(*) FROM studies` before/after). Contract test locks envelope shape.
- [ ] `POST /api/v1/studies` with matching `cluster_id` but mismatched `target` returns 422 `JUDGMENT_TARGET_MISMATCH` AND no `studies` row + no Arq enqueue (same assertion pattern).
- [ ] `POST /api/v1/studies` with both matching returns 201 `StudyDetail` AND inserts the row with the requested target AND `start_study(study_id)` is enqueued exactly once (integration — happy path, AC-2).
- [ ] `POST /api/v1/studies` with a non-existent `judgment_list_id` returns 404 `JUDGMENT_LIST_NOT_FOUND` — the new validators never fire (integration AND contract — ordering test, AC-3).
- [ ] `POST /api/v1/studies` with mismatched `query_set_id` (existing check) returns 422 `VALIDATION_ERROR` — the new validators never fire (integration AND contract — ordering test, AC-4).
- [ ] `POST /api/v1/studies` with matching `target` but mismatched `cluster_id` returns `JUDGMENT_CLUSTER_MISMATCH` (NOT `JUDGMENT_TARGET_MISMATCH`) — verifies firing order (integration AND contract — AC-11). Contract-layer assertion locks the order so a future reordering breaks CI.
- [ ] `api-conventions.md` includes both new rows in firing order.
- [ ] `GET /api/v1/studies/{id}` for a pre-existing fixture row with mismatched target returns 200 (integration — AC-10 negative test).

---

### Story 2.1 — Create-study modal: target-aware filter + cascade reset + empty state

**Outcome:** The create-study modal Step-2 judgment-list dropdown filters by the Step-1 target via the new `?target=` wire param; changing target OR cluster cascade-resets `judgment_list_id`; an empty filter result renders an empty-state copy with a CTA linking to `/judgments`.

**Traces to:** FR-4.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/__tests__/create-study-modal.target-filter.test.tsx` | New vitest file with 5 cases per §3.5 (target-aware filter call shape, manual-mode cascade, dropdown-mode cascade, cluster-mode cascade regression-lock, empty-state copy + CTA). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | (a) Lines 190-193: extend `useJudgmentLists` call to pass `{ query_set_id, cluster_id, target, limit: 200 }`. `clusterId` is already in scope at line 142; `target` is already watched at line 143. (b) Line 527 (manual-mode `<Input>`) and lines 539-561 (dropdown-mode `<EntitySelect>`): extend both target-setting `onChange` handlers to ALSO call `form.setValue('judgment_list_id', '')`. The manual `<Input>` continues to use `form.register('target')` — pattern below preserves RHF's `name`/`ref`/`onBlur` wiring (see Story-2.1 task #3 for the exact JSX). (c) Lines 603-612: add `emptyState` prop to the `<EntitySelect>` rendering the judgment-list dropdown. Use the existing prop shape per [`entity-select.tsx:33-36`](../../../../ui/src/components/common/entity-select.tsx#L33-L36). |
| `ui/src/lib/api/judgments.ts` | (Owned by Story 2.1 only — removed from Story 1.1.) Lines 30-35: add `target?: string \| undefined` to `JudgmentListsFilter`. Lines 37-51: destructure `target` + thread through `params` AND `queryKey`. |
| `ui/src/lib/types.ts` | (Owned by Story 1.1 — not modified in Story 2.1.) Story 2.1 consumes the regenerated types. If existing TS fixtures construct `JudgmentListSummary` object literals without `target`, audit + add the field in this story (per §3.6 audit task) — but the fixtures live in `.test.tsx` files, not `types.ts` itself. |

**Endpoints**

No new endpoints. Consumes `GET /api/v1/judgment-lists?target=...&cluster_id=...&query_set_id=...` from Story 1.1.

**Pydantic schemas**

None — frontend-only story.

**Key interfaces**

```typescript
// ui/src/lib/api/judgments.ts
export interface JudgmentListsFilter {
  query_set_id?: string | undefined;
  cluster_id?: string | undefined;
  target?: string | undefined;  // NEW
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useJudgmentLists(
  filter: JudgmentListsFilter = {},
): UseQueryResult<JudgmentListsPage, ApiError> {
  const { query_set_id, cluster_id, target, cursor, limit } = filter;  // NEW: target
  return useQuery<JudgmentListsPage, ApiError>({
    queryKey: ['judgment-lists', { query_set_id, cluster_id, target, cursor, limit }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<JudgmentListListResponse>(
        '/api/v1/judgment-lists',
        { params: { query_set_id, cluster_id, target, cursor, limit } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}
```

**UI element inventory**

Per the spec's information-architecture section (§11):

| Element | Purpose | Current state | Change |
|---|---|---|---|
| Cluster picker (`EntitySelect` at lines 492-516) | Step-1 cluster selection | `onChange` at lines 502-514 already resets `target`, `query_set_id`, `judgment_list_id`, `template_id`, `manualMode` | **No change needed** — already resets `judgment_list_id` (verified). AC-12 covered. |
| Target manual `<Input>` (line 527) | Step-1 manual-mode target entry | `{...form.register('target')}` — no custom onChange | **Add custom onChange** that calls `form.setValue('target', v)` + `form.setValue('judgment_list_id', '')`. Or replace `register` usage with explicit Controller pattern. |
| Target dropdown `<EntitySelect>` (lines 539-561) | Step-1 dropdown-mode target entry | `onChange={(v) => form.setValue('target', v ?? '')}` at line 554 | **Extend onChange** to also call `form.setValue('judgment_list_id', '')`. |
| Query-set picker `<EntitySelect>` (lines 587-599) | Step-2 query-set selection | `onChange` at lines 594-597 already resets `judgment_list_id` | **No change needed**. |
| Judgment-list dropdown `<EntitySelect>` (lines 603-612) | Step-2 judgment-list selection | No `emptyState` prop set | **Add `emptyState` prop** with target-aware message + CTA href `/judgments`. |

**State dependency analysis**

State being touched: `form.setValue('judgment_list_id', '')` from a new cascade trigger.

```
State being modified: judgment_list_id (via react-hook-form)
Currently reset by:
  - cluster_id onChange (line 509) — survives
  - query_set_id onChange (line 596) — survives
New reset trigger:
  - target onChange (lines 527 manual + 554 dropdown) — added in Story 2.1
Referenced by:
  - Step-2 advance gate (line 386: Boolean(values.query_set_id && values.judgment_list_id))
  - Submit handler (line 455: judgment_list_id: values.judgment_list_id)
Action needed: resetting on target change is safe — Step-2 advance gate re-fires, the user re-picks.
```

**Tasks**

1. Extend `JudgmentListsFilter` in `ui/src/lib/api/judgments.ts` with `target?: string | undefined`. Update `useJudgmentLists` to destructure + thread `target` through `params` AND `queryKey`. (Moved from Story 1.1; sole owner is Story 2.1 to avoid ownership conflict.)
2. In `create-study-modal.tsx`, change the `useJudgmentLists` call (line 190) to pass `cluster_id: clusterId || undefined, target: target || undefined`.
3. In the manual-mode `<Input>` at line 527: keep RHF registration intact while adding the cascade reset. Pattern (preserves `name`, `ref`, `onBlur`, `validate`):
   ```tsx
   {(() => {
     const targetReg = form.register('target');
     return (
       <Input
         id="cs-target"
         {...targetReg}
         onChange={(e) => {
           targetReg.onChange(e);
           form.setValue('judgment_list_id', '');
         }}
         placeholder="products"
       />
     );
   })()}
   ```
   Or, equivalently, hoist `targetReg` into the component body before the JSX returns. The key invariant: `targetReg.onChange(e)` runs first so RHF's internal state (dirty/touched/validation) updates correctly; the `judgment_list_id` reset runs after.
4. In the dropdown-mode `<EntitySelect>` at lines 546-561: extend the `onChange` at line 554 to:
   ```tsx
   onChange={(v) => {
     form.setValue('target', v ?? '');
     form.setValue('judgment_list_id', '');
   }}
   ```
5. Add `emptyState` prop to the judgment-list `<EntitySelect>` at lines 603-612. Per spec FR-4: the "no target yet" branch is dead code (Step-2 advance gate requires `target` set at Step 1), so the empty-state message uses the watched `target` value unconditionally:
   ```tsx
   <EntitySelect
     id="cs-jl"
     data-testid="cs-jl"
     query={judgmentLists}
     getId={(j) => j.id}
     getLabel={(j) => j.name}
     value={values.judgment_list_id || undefined}
     onChange={(v) => form.setValue('judgment_list_id', v ?? '')}
     placeholder="Choose a judgment list"
     emptyState={{
       message: `No judgment lists for target "${target}" on this cluster + query set. Generate a new one from /judgments.`,
       cta: { label: 'Generate judgments', href: '/judgments' },
     }}
   />
   ```
6. Add vitest cases at `ui/src/components/studies/__tests__/create-study-modal.target-filter.test.tsx` (new file): 5 cases per spec §14 + plan §3.5. Use the existing modal test setup (msw mocks + `render` patterns from sibling test files in the same `__tests__/` directory).
7. Audit existing UI fixtures: `grep -rn "JudgmentListSummary\|judgmentLists\|/api/v1/judgment-lists" ui/src/ ui/tests/` to find every object literal returning a `JudgmentListSummary`. Add `target: '<value>'` to each — the `pnpm typecheck` gate will surface any missed fixtures because `target` is now a required field.

**Definition of Done**

- [ ] Modal Step-2 dropdown calls `useJudgmentLists` with `{ query_set_id, cluster_id, target, limit: 200 }` — vitest case 1.
- [ ] Changing `target` via the **dropdown** `<EntitySelect>` resets `judgment_list_id` to `''` — vitest case 2a (AC-9).
- [ ] Changing `target` via the **manual** `<Input>` resets `judgment_list_id` to `''` — vitest case 2b (AC-9). Separate case because manual + dropdown go through different handlers; testing only one branch can miss a regression on the other (especially after the RHF-preserving change in Task 3).
- [ ] Changing `cluster_id` resets `judgment_list_id` to `''` — vitest case 3 (AC-12). Note: this behavior already exists at line 509; the test exists to lock it down against regression.
- [ ] Empty filter result renders the empty-state copy with the target value substituted and CTA `href="/judgments"` — vitest case 4.
- [ ] Focused hook test in `ui/src/lib/api/__tests__/judgments.test.tsx` (or extend if it exists): assert `useJudgmentLists({ target: 'X' })` calls `apiClient.get` with `params.target = 'X'` AND includes `target` in the queryKey — vitest case 5. Proves wire filtering, not just hook invocation.
- [ ] All existing UI fixtures constructing `JudgmentListSummary` literals have been updated to include `target` (per Task 7 audit) — `pnpm typecheck` green.
- [ ] `pnpm typecheck` + `pnpm lint` + `pnpm build` all green.
- [ ] No new E2E spec — the existing `studies-create-validation.spec.ts` exercises the happy path with seed data that already has matching target (verified per spec §14 E2E row).

---

## UI Guidance

### Reference: current component structure

[`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) — 700+ lines, 5-step wizard.

Step structure:
- **Step 0** ('Cluster + target') — lines ~488-580
- **Step 1** ('Query set + judgments') — lines ~583-614
- **Step 2** ('Template') — lines ~616-649
- **Step 3** ('Search space') — lines ~651-...
- **Step 4** ('Objective + config') — final step

Relevant state variables (lines 142-146):
- `clusterId = form.watch('cluster_id')`
- `target = form.watch('target')`
- `querySetId = form.watch('query_set_id')`
- `templateId = form.watch('template_id')`

Form defaults at lines 124-139 (target = `''`, judgment_list_id = `''`).

Step-validation gate function `stepValid()` at lines 381-410:
- Step 0 advance requires `Boolean(values.cluster_id && values.target)` (line 384)
- Step 1 advance requires `Boolean(values.query_set_id && values.judgment_list_id)` (line 386)

### Insertion point

- **Line 190-193** (useJudgmentLists call): extend the filter object. What stays above: imports + form setup. What stays below: `useTemplates` call.
- **Line 527** (target manual-mode `<Input>`): keep `{...form.register('target')}` registration but hoist the register result (`targetReg = form.register('target')`) and override `onChange` with a wrapper that calls `targetReg.onChange(e)` first, then `form.setValue('judgment_list_id', '')`. Exact JSX in §"Handler function patterns" below. **Do NOT** replace with a bare value/onChange — that bypasses RHF's registered validation. Stays above: cluster picker. Stays below: TARGETS_FORBIDDEN inline hint at line 528-532.
- **Line 554** (target dropdown `<EntitySelect>` onChange): extend the arrow function to add the judgment_list_id reset. Stays above: `<EntitySelect id="cs-target">` opening JSX. Stays below: placeholder + emptyState props.
- **Lines 603-612** (judgment-list `<EntitySelect>`): add `emptyState` prop. Stays above: query-set picker. Stays below: the `</div>` closing Step 1.

### Analogous markup patterns

**Pattern 1: emptyState prop with CTA — from [`create-study-modal.tsx:556-561`](../../../../ui/src/components/studies/create-study-modal.tsx#L556-L561) (targets `target_filter` empty state):**

```tsx
emptyState={{
  message: selectedCluster?.target_filter
    ? `No targets match filter "${selectedCluster.target_filter}" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations.`
    : 'No targets found on this cluster.',
}}
```

Story 2.1 adapts this for the judgment-list dropdown. Note: spec FR-4 says Step-2 is target-gated (the user cannot reach the dropdown without `target` set), so the empty-state message is UNCONDITIONAL with no fallback branch — do not copy the targets-dropdown's `?  :` pattern verbatim. Story 2.1 also adds a `cta` field (already supported by [`entity-select.tsx:33-36`](../../../../ui/src/components/common/entity-select.tsx#L33-L36)):

```tsx
emptyState={{
  message: `No judgment lists for target "${target}" on this cluster + query set. Generate a new one from /judgments.`,
  cta: { label: 'Generate judgments', href: '/judgments' },
}}
```

**Pattern 2: cascade-reset onChange — from [`create-study-modal.tsx:594-597`](../../../../ui/src/components/studies/create-study-modal.tsx#L594-L597) (query-set picker resets judgment_list_id):**

```tsx
onChange={(v) => {
  form.setValue('query_set_id', v ?? '');
  form.setValue('judgment_list_id', '');
}}
```

Story 2.1 mirrors this on the target dropdown:

```tsx
onChange={(v) => {
  form.setValue('target', v ?? '');
  form.setValue('judgment_list_id', '');
}}
```

**Pattern 3: cluster-cascade onChange (already correct, no change needed) — from [`create-study-modal.tsx:502-514`](../../../../ui/src/components/studies/create-study-modal.tsx#L502-L514):**

```tsx
onChange={(v) => {
  form.setValue('cluster_id', v ?? '');
  form.setValue('target', '');
  form.setValue('query_set_id', '');
  form.setValue('judgment_list_id', '');
  form.setValue('template_id', '');
  setManualMode(false);
}}
```

This already covers AC-12 (cluster change resets judgment_list_id). The vitest test exists to lock the behavior against regression — no code change needed here.

### Layout and structure

No layout changes. The empty-state rendering is owned by the `<EntitySelect>` primitive ([`entity-select.tsx`](../../../../ui/src/components/common/entity-select.tsx)) — the modal just supplies the `emptyState` prop.

### Confirmation/modal dialog pattern

N/A — no new dialogs introduced.

### Visual consistency table

| New UI element | CSS class / pattern source |
|---|---|
| Empty-state copy + CTA in judgment-list dropdown | Reuses `EntitySelectEmptyState` interface from [`entity-select.tsx:33-36`](../../../../ui/src/components/common/entity-select.tsx#L33-L36); rendered by the existing `<EntitySelect>` empty-state branch — no new CSS needed. |

### Component composition

All changes are inline within the existing `<CreateStudyModal>` function component. No new extracted components.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Picks target in Step 0 (dropdown OR manual) | `target` form value set; `judgment_list_id` reset to `''`; Step-1 advance gate fails until user re-advances. | `GET /api/v1/judgment-lists?query_set_id=&lt;Q&gt;&cluster_id=&lt;C&gt;&target=&lt;T&gt;&limit=200` (fires only after the user advances to Step 1) |
| Changes target in Step 0 after having picked a judgment list in Step 1 | `judgment_list_id` reset; Step-1 shows the dropdown with the new filtered results. | Same as above with new target value. |
| No matching judgment lists for filter | Empty-state copy renders with exact target value + "Generate judgments" CTA to `/judgments`. | (no new call — `useJudgmentLists` returned `data: []`) |
| Changes cluster (any step) | All downstream form values reset (per existing handler at line 502-514). | `GET /api/v1/judgment-lists?query_set_id=&lt;new Q&gt;&cluster_id=&lt;new C&gt;&target=&lt;new T&gt;&limit=200` after the user re-advances. |

### Handler function patterns

The dropdown handler is straightforward `form.setValue` (already off-RHF-register — `<EntitySelect>` is a controlled component via `value`/`onChange` props):

```typescript
// Target dropdown onChange — pattern from line 594-597 (query-set picker)
const onTargetDropdownChange = (v: string | undefined): void => {
  form.setValue('target', v ?? '');
  form.setValue('judgment_list_id', '');
};
```

The manual-input handler MUST preserve RHF's registered `onChange` to keep `dirty`/`touched`/`validate` state correct. Hoist the register result and call its `onChange` first, then run the cascade reset:

```tsx
// In the modal body, BEFORE the JSX return:
const targetReg = form.register('target');

// In Step-0 manual-input JSX (replaces `{...form.register('target')}`):
<Input
  id="cs-target"
  {...targetReg}
  onChange={(e) => {
    targetReg.onChange(e);       // RHF: updates value + dirty/touched + runs registered validate
    form.setValue('judgment_list_id', '');  // cascade
  }}
  placeholder="products"
/>
```

**Do NOT** use the simpler `form.setValue('target', e.target.value)` pattern in the manual handler — it bypasses RHF's registered `onChange` and can break the existing TARGETS_FORBIDDEN auto-engage path at lines 170-173.

### Information architecture placement

No nav changes. Feature lives within the existing create-study modal (Step 0 → Step 1 cascade). No new routes, no new tabs.

### Tooltips and contextual help

No new tooltip placements per spec §11 ("Tooltips and contextual help" section says "no new tooltip placements; existing `study.judgment_list` glossary entry already explains the field"). The empty-state copy itself is the contextual help when the dropdown is empty.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** Story 2.1 extends three existing UI elements (judgment-list `<EntitySelect>`, target manual `<Input>`, target dropdown `<EntitySelect>`) in-place; no JSX is removed.

### Client-side persistence

N/A — no localStorage/sessionStorage usage in this feature.

### Enumerated value contract

No new enumerated `<select>` options. The new `?target=` wire param is a free-form string (255-char bounded), not an allowlisted enum. No source-of-truth comment needed on the frontend for option arrays because no option arrays are introduced.

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** `backend/tests/unit/`
- **Scope:** None new — no new pure-domain logic. The two validators are inline conditionals on the route handler.
- **Tasks:** none.
- **DoD:** N/A.

### 3.2 Integration tests

- **Location:** `backend/tests/integration/`
- **Scope:** DB-backed studies POST validation + judgment-lists filtering.
- **Tasks:**
  - [ ] In `test_studies_api.py`: add `test_create_study_rejects_target_mismatch()` — seeds matching cluster + mismatched target; asserts 422 + `JUDGMENT_TARGET_MISMATCH`. Assigned to Story 1.2 DoD.
  - [ ] In `test_studies_api.py`: add `test_create_study_rejects_cluster_mismatch()` — seeds 2 clusters + judgment list on C1 + study body with C2; asserts 422 + `JUDGMENT_CLUSTER_MISMATCH`. Assigned to Story 1.2 DoD.
  - [ ] In `test_studies_api.py`: add `test_create_study_cluster_mismatch_fires_before_target()` — both cluster AND target mismatch; asserts `JUDGMENT_CLUSTER_MISMATCH` (not target). Assigned to Story 1.2 DoD (AC-11).
  - [ ] In `test_studies_api.py`: add `test_create_study_happy_path_matching_target_and_cluster()` — asserts 201 with the existing `StudyDetail` shape (AC-2). Assigned to Story 1.2 DoD.
  - [ ] In `test_studies_api.py`: add `test_studies_get_does_not_validate_pre_existing_target_mismatch()` — seeds a study row with mismatched target via direct DB write; asserts `GET /api/v1/studies/{id}` returns 200 (AC-10). Assigned to Story 1.2 DoD.
  - [ ] In `test_judgments_api.py`: add `test_list_judgment_lists_target_filter()` — seeds 3 lists (2 with `target=A`, 1 with `target=B`); asserts `?target=A` returns 2 rows + `X-Total-Count: 2`; `?target=B` returns 1 row + `X-Total-Count: 1`. Assigned to Story 1.1 DoD (AC-5).
  - [ ] In `test_judgments_api.py`: add `test_list_judgment_lists_and_semantics()` — seeds 4 lists across 2 clusters × 2 query_sets × shared target `products`; asserts `?target=products&cluster_id=C1&query_set_id=Q1` returns exactly 1 row + `X-Total-Count: 1`. Assigned to Story 1.1 DoD (spec §14 integration case #5).
- **DoD:** Happy path + all critical failure paths covered; X-Total-Count matches data length under filter.

### 3.3 Contract tests

- **Location:** `backend/tests/contract/`
- **Scope:** Endpoint shape, status codes, machine-readable error codes, **firing-order locks**.
- **Tasks:**
  - [ ] In `test_studies_error_codes.py`: add `test_judgment_target_mismatch_envelope_shape()` — asserts the canonical envelope on the new 422. Assigned to Story 1.2.
  - [ ] In `test_studies_error_codes.py`: add `test_judgment_cluster_mismatch_envelope_shape()` — asserts the canonical envelope on the new 422. Assigned to Story 1.2.
  - [ ] In `test_studies_api_contract.py`: add `test_create_study_error_ordering()` — sets up scenarios where multiple errors could fire and asserts the priority: 404 `JUDGMENT_LIST_NOT_FOUND` > 422 `VALIDATION_ERROR` (query_set) > 422 `JUDGMENT_CLUSTER_MISMATCH` > 422 `JUDGMENT_TARGET_MISMATCH`. Assigned to Story 1.2. **Contract-layer assertion locks the order against future refactor.**
  - [ ] In `test_judgments_api_contract.py`: add `test_judgment_list_summary_includes_target()` — asserts `target` field present + type-`string` on the summary, and `?target=` query param exists. Assigned to Story 1.1.
  - [ ] In `test_openapi_surface.py`: verify the snapshot/schema check accepts the new `JudgmentListSummary.target` schema property AND the new `?target=` query param on `GET /api/v1/judgment-lists`. **NOT in scope:** enumerating the new error codes on the POST /studies row — the existing surface test (lines 75-82) only asserts `(method, path, success_status)` tuples and does not enumerate per-endpoint error responses (no route uses FastAPI `responses=` metadata to declare 4xx envelopes in OpenAPI). Error codes are locked at the runtime layer via `test_studies_error_codes.py` + the new ordering test in `test_studies_api_contract.py` + the `api-conventions.md` documentation row — that combination is sufficient and matches the existing repo pattern. Owned by Story 1.1 (the only story changing OpenAPI surface). Story 1.2 does not change OpenAPI surface (handler-body `_err(...)` raises don't appear in OpenAPI).
- **DoD:** Every accepted endpoint change has contract coverage. Both new error codes locked. Firing order locked at contract layer.

### 3.4 E2E tests

- **Location:** `ui/tests/e2e/`
- **Scope:** No new specs. Existing `ui/tests/e2e/studies-create-validation.spec.ts` exercises the happy path; the seed helper at [`ui/tests/e2e/helpers/seed.ts:400-413`](../../../../ui/tests/e2e/helpers/seed.ts#L400-L413) already creates judgment lists with `target: 'products'` matching the cluster's `products` index — verified compatible with the new wire filter.
- **Tasks:**
  - [ ] Run the existing `studies-create-validation.spec.ts` after the implementation lands; confirm it still passes. Assigned to Story 2.1 DoD.
  - [ ] Audit: confirm no other E2E spec relies on a judgment-list that has `target ≠ study.target` for the happy path. Audit scope: `grep -rn "judgment.*list\|judgmentList" ui/tests/e2e/` to enumerate touched specs.
- **DoD:** Existing Playwright suite passes; no new spec needed.

### 3.5 Frontend unit tests

- **Location:** `ui/src/components/studies/__tests__/` and `ui/src/lib/api/__tests__/`.
- **Tasks:**
  - [ ] New file `ui/src/components/studies/__tests__/create-study-modal.target-filter.test.tsx` with 5 vitest cases:
    1. Asserts `useJudgmentLists` is invoked with `{ query_set_id, cluster_id, target, limit: 200 }` when those values are set on the form.
    2a. Asserts `target` change via the **dropdown** `<EntitySelect>` (`data-testid="cs-target"`) clears `judgment_list_id`.
    2b. Asserts `target` change via the **manual** `<Input>` (`id="cs-target"` when manual mode is active) clears `judgment_list_id`. Separate from 2a because the handlers are different code paths.
    3. Asserts `cluster_id` change clears `judgment_list_id` (regression-lock — behavior already exists at line 509).
    4. Asserts the empty-state copy renders with the target value substituted and CTA `href="/judgments"` when the hook returns `{ data: [], next_cursor: null, has_more: false }`.
  - [ ] New file `ui/src/lib/api/__tests__/judgments.test.tsx` (or extend if it already exists — `grep -rn "useJudgmentLists" ui/src/lib/api/__tests__/` to check): add `test_useJudgmentLists_threads_target_param()` — spy on `apiClient.get` and assert that calling the hook with `{ target: 'X' }` results in a request where `params.target === 'X'` AND that `target` appears in the queryKey. This proves the wire-filtering contract, which the component-level test (case 1) only asserts at the hook-call boundary.

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| All UI fixtures constructing `JudgmentListSummary` literals (msw mocks, component test fixtures) | `JudgmentListSummary\|judgmentLists\|/api/v1/judgment-lists` | TBD — run `grep -rn "JudgmentListSummary\|judgmentLists\|/api/v1/judgment-lists" ui/src/ ui/tests/` and enumerate | **Update each** — `JudgmentListSummary.target` is now a required field. Object literals missing `target` will fail `pnpm typecheck` after `types.ts` is regenerated. Add `target: '<value>'` to each. Story 2.1 Task 7 owns this. |
| `ui/src/components/studies/__tests__/create-study-modal*.test.tsx` (and sibling files) | `useJudgmentLists` mock | 1 per file using the modal | Confirm each msw-style mock returns judgment lists shaped with the new `target` field (typecheck will fail otherwise). The `target` filter is optional and existing mocks pass-through regardless. |
| `ui/src/components/query-sets/associated-judgment-lists.tsx` (production caller) | `useJudgmentLists({ query_set_id, limit: 50 })` | 1 | No code change — additive `target` field on summary is ignored at the consumption site; no filter passed. Confirmed compatible. |
| `ui/src/app/page.tsx` (dashboard count widget) | `apiClient.get<JudgmentListListResponse>` | 1 | No code change — header-only call. |
| `backend/tests/contract/test_openapi_surface.py` | OpenAPI snapshot | 1 | **Update** — must regenerate the snapshot to include `JudgmentListSummary.target` + new `?target=` query param. (NOT the new error codes — the existing surface test at lines 75-82 only enumerates success-status tuples; per-endpoint error codes are locked at the runtime layer instead.) Owned by Story 1.1 alone. |
| `backend/tests/integration/test_judgments_api.py` | Existing list-endpoint tests | (existing) | No code change — new filter is additive; existing assertions remain valid. |
| `backend/tests/contract/test_studies_api_contract.py` | Existing endpoint contract | (existing) | **Add ordering tests** per §3.3. Story 1.2 owns. |

### 3.7 Migration verification

N/A — no schema changes.

### 3.8 CI gates

- [ ] `make lint` (ruff)
- [ ] `make typecheck` (mypy --strict)
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- [ ] Existing Playwright suite via `make test-e2e` (if available) or `cd ui && pnpm e2e`.

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update to:
  - Move feature into the "Most recent meaningful changes" section after PR merge.
  - Note: no Alembic head change.
- **`architecture.md`** — no change. Pure API-layer + frontend addition; no new service/layer/flow.
- **`CLAUDE.md`** — no change. No new convention, env var, or absolute rule.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `api-conventions.md` — add `JUDGMENT_CLUSTER_MISMATCH` + `JUDGMENT_TARGET_MISMATCH` to the studies-endpoint error-code table (after `SEARCH_SPACE_MISSING_DECLARED_PARAM` at lines 76-77). Assigned to Story 1.2.

### 4.2 Product docs (`docs/02_product`)

- This feature is the canonical doc. No other product doc changes.

### 4.3 Runbooks (`docs/03_runbooks`)

- No new runbook. The 422 envelopes are self-explanatory.

### 4.4 Security docs (`docs/04_security`)

- No change — no new attack surface, no new secret.

### 4.5 Quality docs (`docs/05_quality`)

- No change — existing test layers cover the feature.

**Documentation DoD**

- [ ] `state.md` reflects the merged PR.
- [ ] `api-conventions.md` carries both new error-code rows.
- [ ] No other doc touched.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. The feature is additive across all 3 stories — no refactor opportunity worth the scope expansion.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- N/A.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Story 1.1 `JudgmentListSummary.target` field + `?target=` filter | Story 2.1 | (in-PR — same branch) | Story 2.1's `useJudgmentLists({ target })` would silently filter nothing without the wire param; the OpenAPI types regen would also fail. Order Stories 1.1 → 2.1 within the branch. |
| GPT-5.5 cross-model review on the implementation | Final PR review | Configured per `.env` | If unavailable, fall back to Opus-only review with explicit log entry per `impl-execute` skill protocol. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pre-existing test fixtures across the repo use mismatched (cluster, target) judgment-list pairings and break after the new validators land | L | H | Story 1.2 task list includes a `grep` audit across `backend/tests/integration/` for `judgment_list_id` usage in study POST setups, and `ui/tests/e2e/helpers/seed.ts` for the same. Confirmed clean in spec §14 (seed helper uses matching `target='products'`). Re-verify during impl-execute. |
| OpenAPI types regen fails because the live dev container isn't running | L | L | Regen is part of Story 1.1; if the project's standard regen workflow isn't immediately available, wire it up in the PR (e.g., add a `make openapi-export` target or `pnpm run openapi:generate` script). **Manual hand-edits of `ui/src/lib/types.ts` are NOT permitted** — they drift from the OpenAPI source and miss new query params or required fields. |
| Cycle-1 GPT-5.5 review on the plan re-surfaces the cluster_id finding (since the spec review already raised it) | L | L | Plan explicitly carries FR-1b through Story 1.2 + tests + docs. Cycle-1 should converge fast. |
| Frontend regression: existing `register('target')` -> explicit Controller pattern change breaks form keyboard navigation | L | M | Vitest case 2 explicitly asserts the manual-input cascade. Real-backend Playwright spec exercises the manual-input path end-to-end. Mitigated by tests. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Mismatched cluster + target via chat agent `create_study` tool | LLM hallucinates a judgment_list_id from a different cluster | Backend 422 `JUDGMENT_CLUSTER_MISMATCH`; chat agent's existing error handler surfaces the message | Manual — operator picks correct judgment list |
| Mismatched target same cluster (rare — only chat agent could hit) | LLM picks a judgment_list with right cluster but wrong target | Backend 422 `JUDGMENT_TARGET_MISMATCH` | Manual — operator picks correct judgment list |
| Pre-existing studies with mismatched target (created before this feature) | Direct DB row | Read paths return 200 unchanged; orchestrator keeps producing 0-metric trials (out-of-scope; covered by `feat_orchestrator_zero_streak_abort` sibling) | Wait for mid-flight abort (sibling feature, MVP1) or manually cancel |
| Frontend race: user changes cluster mid-fetch | TanStack queryKey re-computes; old fetch result discarded | New filter applies; empty state may flash briefly | Auto — TanStack's stale-while-revalidate handles |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — backend listing surface extension (FR-2 + FR-3). Backend types must be live before frontend types regen.
2. **Story 1.2** — backend validators (FR-1 + FR-1b). Independent of Story 1.1.
3. **Story 2.1** — frontend filter + cascade + empty-state (FR-4). Depends on Story 1.1.

### Parallelization opportunities

- Story 1.1 and Story 1.2 can run in parallel for the production-code edits (different files, no shared state).
- Story 2.1 must wait for Story 1.1's `JudgmentListSummary.target` + `?target=` wire to land in the working tree before regenerating types.
- **`test_openapi_surface.py` is owned by Story 1.1 only** (Story 1.2 changes don't surface in OpenAPI — runtime `_err(...)` raises don't add `responses` metadata; the existing surface test only enumerates `(method, path, success_status)` tuples). No final joint sequencing needed.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single — merge to `main` triggers nothing for MVP1 (no remote staging). Operators pull on next `make up`.
- **Feature flag strategy:** None. Validation is a hard-gate at the API boundary; staged rollout would mean half the operators get the 422 and half don't.
- **Migration/cutover steps:** None — no schema changes.
- **Reconciliation/repair strategy:** None — no external systems involved.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Extend GET /judgment-lists with target filter + summary field
- [ ] Story 1.2 — Studies POST cluster + target validators
- [ ] Story 2.1 — Create-study modal: target filter + cascade + empty state

### Blocked items

- None.

### Done this sprint

- (none yet)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match story scope (New files / Modified files tables).
- [ ] Endpoint contract implemented exactly as documented (status codes + envelope shapes).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all applicable layers.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (subset for touched endpoints)
    - [ ] `make test-contract`
    - [ ] `cd ui && pnpm test` (if UI touched)
    - [ ] `cd ui && pnpm build` (if UI touched)
- [ ] Migration round-trip evidence: N/A (no schema changes).
- [ ] `docs/01_architecture/api-conventions.md` updated when Story 1.2 lands.

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:**
   - Spec §7.1 lists 2 endpoints (POST /studies, GET /judgment-lists).
   - Plan covers both — Story 1.2 (POST /studies), Story 1.1 (GET /judgment-lists). ✅ Match.

2. **Spec ↔ plan error code coverage:**
   - Spec §7.5 lists 2 new codes (`JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`).
   - Plan §3.3 has 2 envelope-shape contract tests + 1 ordering-priority contract test in `test_studies_api_contract.py` (locks 404 > VALIDATION_ERROR > CLUSTER_MISMATCH > TARGET_MISMATCH order). ✅ Match.
   - Existing codes (`VALIDATION_ERROR`, `JUDGMENT_LIST_NOT_FOUND`, etc.) are referenced in DoD ordering tests; the new ordering contract test exercises them as preconditions but doesn't re-cover their individual envelopes (already covered by existing `test_studies_error_codes.py` cases — verified at line 103-107).

3. **Spec ↔ plan FR coverage:**
   - FR-1: Story 1.2 ✅
   - FR-1b: Story 1.2 ✅
   - FR-2: Story 1.1 ✅
   - FR-3: Story 1.1 ✅
   - FR-4: Story 2.1 ✅
   - All 5 FRs covered.

4. **Story internal consistency:**
   - Story 1.1: Modified files exist (verified: `schemas.py`, `judgments.py`, `judgment_list.py`, `judgments.ts`). Pydantic schema field `target: str` matches the ORM `Text NOT NULL` column. ✅
   - Story 1.2: Modified files exist (verified: `studies.py`, `api-conventions.md`). The `_err(...)` helper at studies.py:74 matches the envelope shape. ✅
   - Story 2.1: Modified files exist (verified: `create-study-modal.tsx`, `judgments.ts`, `types.ts`). UI element inventory matches actual modal structure (verified by reading lines 488-614). ✅
   - No file ownership conflicts.

5. **Test file count and assignment:**
   - Backend integration: 7 cases across 2 files (test_studies_api.py: 5, test_judgments_api.py: 2). All assigned to Story 1.1 or 1.2. ✅
   - Backend contract: 5 cases across 4 files (test_studies_error_codes.py: 2, test_studies_api_contract.py: 1 ordering test, test_judgments_api_contract.py: 1, test_openapi_surface.py: 1 — final joint task). All assigned. ✅
   - Frontend vitest: 1 new test file (`create-study-modal.target-filter.test.tsx`, 5 cases) + 1 hook test case (in new-or-extended `ui/src/lib/api/__tests__/judgments.test.tsx`). All assigned to Story 2.1. ✅
   - No orphaned test files.

6. **Gate arithmetic:** No epic/phase gates beyond per-story DoD; single epic. N/A.

7. **Open questions resolved:**
   - Spec §19 lists no open questions. All decisions locked. ✅

8. **Plan ↔ codebase verification:**
   - `backend/app/db/repo/judgment_list.py` lines 58-140 verified — both `list_judgment_lists` and `count_judgment_lists` exist with `query_set_id` + `cluster_id` filter pattern to mirror. ✅
   - `backend/app/api/v1/schemas.py:760-769` `JudgmentListSummary` verified — has 7 fields, missing `target`. ✅
   - `backend/app/api/v1/studies.py:240-247` query_set_id cross-check verified. Insertion point at lines 247-249 is correct. ✅
   - `ui/src/components/studies/create-study-modal.tsx:502-514` cluster onChange verified — already resets `judgment_list_id`. AC-12 is regression-lock only. ✅
   - `ui/src/components/common/entity-select.tsx:33-36` `EntitySelectEmptyState` interface verified — already supports `cta`. ✅
   - `ui/tests/e2e/helpers/seed.ts:400-413` judgment-list seeds with `target='products'` matching its cluster's index. ✅
   - `backend/app/api/errors.py:102-118` `validation_exception_handler` confirmed to route FastAPI's `RequestValidationError` into the canonical envelope. ✅

9. **Infrastructure path verification:**
   - Migration directory: N/A (no migration).
   - Router registration: N/A (no new router; extending existing handlers).

10. **Frontend data plumbing verification:**
    - Story 2.1: `clusterId` is in scope at line 142 (`form.watch('cluster_id')`); `target` is in scope at line 143; `querySetId` at line 144. All three available for the `useJudgmentLists` filter. ✅

11. **Persistence scope consistency:** N/A — no localStorage/sessionStorage.

12. **Enumerated value contract audit:** N/A — no new `<select>` allowlists. The `?target=` wire param is a free-form bounded string, not an enum.

13. **Audit-event coverage:** N/A — pre-MVP2 (audit_log not yet active).

---

## 12) Definition of plan done

- [ ] Every FR is mapped to stories/tasks/tests/docs updates. ✅
- [ ] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD. ✅
- [ ] Test layers (unit/integration/contract/e2e) are explicitly scoped. ✅
- [ ] Documentation updates across docs/01-05 are planned and owned. ✅
- [ ] Lean refactor scope is "none" with stated reason. ✅
- [ ] Epic gates are measurable. ✅
- [ ] Story-by-Story Verification Gate is included. ✅
- [ ] Plan consistency review (§11) performed with no unresolved findings. ✅
