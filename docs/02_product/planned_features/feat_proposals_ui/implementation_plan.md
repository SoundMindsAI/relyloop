# Implementation Plan — feat_proposals_ui

**Date:** 2026-05-12
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:**
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — Next.js + shadcn + TanStack Query patterns
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope + cursor pagination
- `feat_studies_ui` [implementation plan](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/implementation_plan.md) — sibling UI conventions (status filter chips, caller-driven polling, global error-toast wiring, enum source-of-truth gate)

---

## 0) Planning principles

- Single-phase, frontend-only feature: no migrations, no backend code, no new endpoints.
- Every story traces to one or more FRs from the spec.
- Reuse existing infrastructure (`<StatusBadge kind="proposal">`, `<MetricDelta>`, `<CursorPaginator>`, `<EmptyState>`, `apiClient`, global error-toast wiring, `PROPOSAL_STATUS_VALUES` / `PROPOSAL_PR_STATE_VALUES` from `ui/src/lib/enums.ts`).
- Extend `ui/src/lib/api/proposals.ts` — do NOT replace. Preserve `useProposals` and `useProposalForStudy` consumers (`feat_studies_ui` study-detail DigestPanel calls `useProposalForStudy`).
- Caller-driven polling via TanStack `refetchInterval` function form, mirroring `feat_studies_ui` Story 3.4.
- Client-side filtering for the proposal-source chip (study / manual / all) — backend has no `?source=` filter and the spec FR-1 only enumerates `?status=` and `?cluster_id=` as backend-driven. Pagination unaware of source filter accepted for MVP1 (logged in §6 risks).

## 1) Scope traceability (FR → epics/stories → tests)

| FR | Epic / Story | Test files | Spec ACs |
|---|---|---|---|
| FR-1 (list rendering + filters) | Epic 2 / Story 2.1 | `__tests__/app/proposals/page.test.tsx`, `__tests__/components/proposals/proposals-table.test.tsx`, `__tests__/components/proposals/proposal-filter-chips.test.tsx` | AC-6 |
| FR-2 (detail layout + 30s steady-state poll + pr_open_error Alert) | Epic 3 / Story 3.1 + 3.2 | `__tests__/app/proposals/[id]/page.test.tsx` | AC-3, AC-4 |
| FR-3 (Open-PR button: 3s post-click poll, hidden when not pending, toast on 503/422) | Epic 3 / Story 3.2 | `__tests__/components/proposals/pr-panel.test.tsx` | AC-1, AC-4 |
| FR-4 (Reject dialog + 409 refresh on concurrent merge) | Epic 3 / Story 3.3 | `__tests__/components/proposals/reject-dialog.test.tsx` | AC-2 |
| FR-5 (suggested followups → `/studies?hypothesis=`) | Epic 3 / Story 3.1 | `__tests__/app/proposals/[id]/page.test.tsx` (AC-5 case) | AC-5 |
| FR-6 (hook contracts: `useProposals` type-narrow + `useProposal` + `useOpenPR` + `useRejectProposal`) | Epic 1 / Story 1.1 | `__tests__/lib/api/proposals.test.tsx` | All |

No FRs are deferred — single-phase deliverable.

## 2) Delivery structure

**Conventions (project-specific):**

- All new files are TypeScript / TSX under `ui/src/`.
- Pages: `ui/src/app/<route>/page.tsx` (Next 16 App Router, `'use client'` on top, `useSearchParams` wrapped in `<Suspense>` per `feat_studies_ui` Story 3.2 idiom).
- Page-scoped components: `ui/src/components/proposals/<component>.tsx`.
- Shared primitives (already exist): `ui/src/components/common/<…>.tsx`.
- shadcn primitives (already exist): `ui/src/components/ui/<…>.tsx`.
- Hooks: `ui/src/lib/api/<resource>.ts` (one file per resource).
- Wire-value allowlists are consumed from `ui/src/lib/enums.ts` — never duplicate them.
- Wire-value typing must come from `ProposalStatus` (re-export from `enums.ts`), not `string`.
- Mutations let the global `MutationCache` onError handler toast (per `query-provider.tsx`). Per-mutation `onError` is reserved for control flow (modal close, list refresh on 409).
- Test files live at `ui/src/__tests__/<mirror-source-tree>/<file>.test.tsx`. Use msw with `http://api.test` as the base URL (already wired in `__tests__/setup.ts`).
- Date strings → ISO 8601; render via `new Date(s).toLocaleString()`.

**AI Agent Execution Protocol:**

0. Read `state.md` + `architecture.md` + this plan + the spec.
1. Implement Story 1.1 (hooks) first — every downstream story depends on the types.
2. Story 1.2 next (filter components) — page stories depend on them.
3. Stories 2.x + 3.x in dependency order.
4. Story 4.1 last (docs sweep + state/architecture updates).
5. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test` after each story.
6. Run `cd ui && pnpm build` after the last frontend story to catch SSR issues.
7. Run `bash scripts/ci/verify_enum_source_of_truth.sh` after Story 1.1 if `enums.ts` was edited (this plan does NOT edit it — all values are already there).

---

## Epic 1 — Hooks + filter components (foundation)

### Story 1.1 — Extend `lib/api/proposals.ts`: narrow `useProposals.filter.status`, add `useProposal`, `useOpenPR`, `useRejectProposal`

**Outcome:** `ui/src/lib/api/proposals.ts` exports the full 5-hook surface defined in spec FR-6. `useProposalForStudy` is preserved byte-for-byte. `useProposals.filter.status` is narrowed from `string` to `ProposalStatus | undefined`. `useProposal(id, opts)` accepts the TanStack v5 `refetchInterval` function form. `useOpenPR()` and `useRejectProposal()` mutations invalidate the right query keys on settle.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api/proposals.ts` | (a) narrow `ProposalsFilter.status` from `string` → `ProposalStatus`; (b) add `RefetchInterval<TData>` type alias mirroring `studies.ts:49`; (c) extend `useProposals(filter, options?)` with the optional second arg for FR-1's 30s pulse-refetch (single-arg signature preserved for non-polling callers); (d) add `useProposal(id, opts)`, `useOpenPR()`, `useRejectProposal()`. Keep `useProposalForStudy` unchanged. |

**Endpoints** — none (consuming existing).

**Key interfaces**

```typescript
// Already shipped — narrowing only.
export interface ProposalsFilter {
  status?: ProposalStatus | undefined;   // was: string
  cluster_id?: string | undefined;
  study_id?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

// New — mirrors useStudy's pattern (ui/src/lib/api/studies.ts:54-69).
type RefetchInterval<TData> =
  | number
  | false
  | ((query: { state: { data: TData | undefined } }) => number | false);

// useProposals gains an optional second argument so the list page can fire a
// 30s pulse-refetch when any visible row is pr_opened+open (FR-1). The bare
// `useProposals(filter)` signature still works — second arg is optional.
export interface UseProposalsOptions {
  refetchInterval?: RefetchInterval<ProposalsPage>;
}
export function useProposals(
  filter?: ProposalsFilter,
  options?: UseProposalsOptions,
): UseQueryResult<ProposalsPage, ApiError>;

export interface UseProposalOptions {
  refetchInterval?: RefetchInterval<ProposalDetail>;
}

export function useProposal(
  id: string,
  options?: UseProposalOptions,
): UseQueryResult<ProposalDetail, ApiError>;

export function useOpenPR(): UseMutationResult<OpenPrResponse, ApiError, string>;
//                                                                       ↑ proposalId

export function useRejectProposal(): UseMutationResult<
  ProposalDetail,
  ApiError,
  { proposalId: string; reason: string | null }
>;
```

**Pydantic schemas** — n/a (frontend consumes already-generated `components['schemas']['ProposalDetail']` / `OpenPrResponse` from `ui/src/lib/types.ts`).

**Tasks**

1. Import `ProposalStatus` from `@/lib/enums`. Replace `status?: string | undefined` with `status?: ProposalStatus | undefined` on `ProposalsFilter`.
2. Import `useMutation`, `useQueryClient`, `UseMutationResult` from `@tanstack/react-query` (currently only `useQuery` is imported).
3. Add `OpenPrResponse` type alias: `export type OpenPrResponse = components['schemas']['OpenPrResponse'];`.
4. Add the `RefetchInterval<TData>` type alias, `UseProposalOptions`, AND `UseProposalsOptions` interfaces (copy the shape from `studies.ts:49-56`).
5. Extend `useProposals(filter, options?)` to accept the optional second argument and pass `refetchInterval: options?.refetchInterval ?? false` into the underlying `useQuery` call. The single-arg call site signature is preserved — the cluster filter dropdown and existing tests do not need to pass `options`.
6. Add `useProposal(id, options)`:
   - `queryKey: ['proposal', id]`
   - `queryFn: apiClient.get<ProposalDetail>(\`/api/v1/proposals/${id}\`)`
   - `refetchInterval: options?.refetchInterval ?? false`
7. Add `useOpenPR()`:
   - `mutationFn: apiClient.post<OpenPrResponse>(\`/api/v1/proposals/${proposalId}/open_pr\`, {})`
   - `onSettled: (_data, _err, proposalId) => { qc.invalidateQueries({ queryKey: ['proposal', proposalId] }); qc.invalidateQueries({ queryKey: ['proposals'] }); }`
   - DO NOT set `meta.suppressGlobalErrorToast` — the global handler must toast `GITHUB_NOT_CONFIGURED` / `CLUSTER_HAS_NO_CONFIG_REPO` / `QUEUE_UNAVAILABLE` per FR-3.
8. Add `useRejectProposal()`:
   - `mutationFn: apiClient.post<ProposalDetail>(\`/api/v1/proposals/${proposalId}/reject\`, { reason })`
   - `onSettled: (_data, _err, { proposalId }) => { qc.invalidateQueries({ queryKey: ['proposal', proposalId] }); qc.invalidateQueries({ queryKey: ['proposals'] }); }`
   - On `INVALID_STATE_TRANSITION` (409), the invalidation in `onSettled` is what causes the FR-4 §11 "refresh the detail query on that 409" behavior — no special-case error code branching needed.
9. Run `cd ui && pnpm typecheck`. Confirm no callers regress (specifically `studies/[id]/page.tsx:42` and `digest-panel.tsx:10`).

**Definition of Done (DoD)**

- `cd ui && pnpm typecheck` clean.
- `cd ui && pnpm lint` clean (no new rule violations).
- `cd ui && pnpm test __tests__/lib/api/proposals.test.tsx` passes the 5-hook contract test added in Story 1.1's test task below.
- `grep -n "useProposalForStudy" ui/src/app/studies/[id]/page.tsx` still resolves (the existing import remains usable; if it doesn't, the type narrow broke an existing call site and must be fixed before this story closes).
- `useProposals.filter.status` now refuses `'invented'` at the compiler level (i.e. `useProposals({ status: 'invented' })` is a TS error).

**Test tasks (in this story)**

- Add `ui/src/__tests__/lib/api/proposals.test.tsx` covering:
  - `useProposals({ status: 'pr_opened' })` → assert query parameter on the wire is `?status=pr_opened` (count msw handler hits).
  - `useProposals({}, { refetchInterval: () => 30_000 })` → assert the msw handler is hit twice within 30.1s using `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync(30_100)` (mirrors the polling pattern in `__tests__/app/studies/[id]/page.test.tsx`).
  - `useProposal('p1')` happy-path returns `ProposalDetail`.
  - `useProposal('p1', { refetchInterval: () => false })` does NOT refetch (advance timers 60s; assert handler hit count remains 1).
  - `useOpenPR()` POSTs to `/api/v1/proposals/p1/open_pr` with empty body. Invalidation assertion form: pre-seed an active `useProposal('p1')` query AND `useProposals({})` query (both with msw handlers that increment a counter), trigger the mutation, await settled state via `waitFor`, then assert each msw GET handler was called twice (initial load + post-invalidation refetch). This proves `invalidateQueries` ran and the active queries refetched — `queryClient.getQueryState` alone is not a reliable signal (per cross-model review B5).
  - `useRejectProposal()` POSTs to `/api/v1/proposals/p1/reject` with `{ reason: 'small delta' }`; apply the same active-query-refetch assertion as above.
  - 409 on reject does NOT set `meta.suppressGlobalErrorToast`. Assert form: spy on `MutationCache.onError` (or read `mutation.meta` directly) and assert the global toast handler fires exactly once.

---

### Story 1.2 — Filter-chip components: `ProposalStatusFilterChips` + `ProposalSourceFilterChips` + `ClusterFilterSelect`

**Outcome:** Three reusable filter primitives in `ui/src/components/proposals/`. The status chips render the 4 wire values from `PROPOSAL_STATUS_VALUES` plus an "all" sentinel. The source chips render the client-only `['all', 'study', 'manual']` tri-state. The cluster select is a native `<select>` populated by `useClusters({ limit: 200 })` (matches the digest-panel + create-study-modal conventions).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/proposal-status-filter-chips.tsx` | Status chips: `all` / `pending` / `pr_opened` / `pr_merged` / `rejected`. Mirrors `studies/study-status-filter-chips.tsx` shape. |
| `ui/src/components/proposals/proposal-source-filter-chips.tsx` | Source chips: `all` / `study` / `manual` (client-side). Same Button-pattern shape as status chips. |
| `ui/src/components/proposals/cluster-filter-select.tsx` | Native `<select>` populated from `useClusters({ limit: 200 })`. First option is `"All clusters"`. |

**Modified files** — none.

**Endpoints** — none (consume `useClusters`).

**Key interfaces**

```typescript
// proposal-status-filter-chips.tsx
export type ProposalStatusFilterValue = 'all' | ProposalStatus;
export interface ProposalStatusFilterChipsProps {
  value: string | null;
  onChange: (value: ProposalStatus | null) => void;
}

// proposal-source-filter-chips.tsx
export type ProposalSourceFilterValue = 'all' | 'study' | 'manual';
export interface ProposalSourceFilterChipsProps {
  value: ProposalSourceFilterValue;
  onChange: (value: ProposalSourceFilterValue) => void;
}

// cluster-filter-select.tsx
export interface ClusterFilterSelectProps {
  value: string | null;
  onChange: (clusterId: string | null) => void;
}
```

**Tasks**

1. Copy the shape of `ui/src/components/studies/study-status-filter-chips.tsx` to build `proposal-status-filter-chips.tsx`. Replace `STUDY_STATUS_VALUES` with `PROPOSAL_STATUS_VALUES`. Use `data-testid={\`proposal-status-chip-${chip}\`}`.
2. Build `proposal-source-filter-chips.tsx` with a 3-value array literal `['all', 'study', 'manual'] as const` — these values are client-only (never sent to the backend) so they do NOT belong in `enums.ts`. Add an inline comment: `// Client-side filter; backend has no ?source= param. Source is derived from proposal.study_id (non-null = study; null = manual).`
3. Build `cluster-filter-select.tsx` — fetch via `useClusters({ limit: 200 })`. Render a native `<select>` (same pattern as `cursor-paginator.tsx:32`). Disable while loading; show `"(loading…)"` placeholder option.
4. Each component is `'use client'`.
5. Each component uses `data-testid` for testability per `feat_studies_ui` conventions.

**Definition of Done (DoD)**

- `pnpm typecheck` clean.
- `pnpm lint` clean.
- `__tests__/components/proposals/proposal-filter-chips.test.tsx` (added with Story 2.1) renders both chip groups and invokes `onChange` with the correct wire value.

---

## Epic 2 — `/proposals` list route

### Story 2.1 — `/proposals` list page + `ProposalsTable` component

**Outcome:** Visiting `/proposals` renders a card with three filter rows (status / source / cluster), a `<ProposalsTable>` of cursor-paginated rows, and the `<CursorPaginator>`. Filter chips are URL-backed for status (mirrors StudiesPage) and React-state-only for source + cluster (since source is client-side and cluster_id is verbose in the URL bar — match the StudiesPage convention). The page auto-refetches every 30s when any visible row has `status='pr_opened' AND pr_state='open'`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/app/proposals/page.tsx` | Route entry. `<Suspense>`-wraps an inner `ProposalsPageInner()`. |
| `ui/src/components/proposals/proposals-table.tsx` | `<ProposalsTable rows={ProposalSummary[]}>` — 6 columns: source/study link, cluster name, template name, status badge, PR-state badge, metric delta, created_at. |

**Modified files** — none.

**Endpoints** (consumed)

| Method | Path | Request | Success | Error |
|---|---|---|---|---|
| `GET` | `/api/v1/proposals` | `?status=ProposalStatus&cluster_id=<id>&cursor=<opaque>&limit=<1..200>` | `200` `ProposalsListResponse` + `X-Total-Count` header | `VALIDATION_ERROR` (422 on bad status/cursor) |

**Key interfaces**

```typescript
export interface ProposalsTableProps {
  rows: readonly ProposalSummary[];
}
export function ProposalsTable({ rows }: ProposalsTableProps): JSX.Element;
```

**UI element inventory (creation)**

| # | Element | Source / Sink |
|---|---|---|
| 1 | Page title `<h1>Proposals</h1>` | static |
| 2 | Filters card with 3 rows | layout |
| 3 | `<ProposalStatusFilterChips>` row | URL `?status=` (write via `router.replace`) |
| 4 | `<ProposalSourceFilterChips>` row | React state |
| 5 | `<ClusterFilterSelect>` row | React state |
| 6 | `<ProposalsTable>` | `useProposals({ status, cluster_id, cursor, limit })` |
| 7 | `<CursorPaginator>` | cursorStack + pageSize React state |
| 8 | `<EmptyState>` when no proposals | branch on `query.isError` or `rows.length===0` |
| 9 | 30s auto-refetch trigger | TanStack `refetchInterval` function form |

**State dependency analysis** — none removed (greenfield route).

**Tasks**

1. Create `ui/src/app/proposals/page.tsx`. Default-export `ProposalsPage()` wrapping `ProposalsPageInner()` in `<Suspense>` (same shape as `studies/page.tsx`).
2. `ProposalsPageInner()` declares:
   - `useSearchParams` + `useRouter` for `?status=` URL-backing
   - **Validate the URL status param against `PROPOSAL_STATUS_VALUES`** before passing it to `useProposals`. `searchParams.get('status')` returns `string | null`; `ProposalsFilter.status` is narrowed to `ProposalStatus` in Story 1.1 (per GPT-5.5 cycle-1 A2). Use:
     ```tsx
     const rawStatus = searchParams.get('status');
     const status: ProposalStatus | undefined =
       rawStatus && (PROPOSAL_STATUS_VALUES as readonly string[]).includes(rawStatus)
         ? (rawStatus as ProposalStatus)
         : undefined;
     ```
     Invalid values (e.g. `/proposals?status=invented`) are silently ignored — they do NOT hit the backend (which would return 422). Per GPT-5.5 cycle-2 A2.
   - `useState` for `pageSize` (default 50), `cursorStack: (string | undefined)[]` (default `[undefined]`), `sourceFilter: ProposalSourceFilterValue` (default `'all'`), `clusterFilter: string | null` (default `null`).
3. Call `useProposals({ status, cluster_id: clusterFilter ?? undefined, cursor, limit: pageSize }, { refetchInterval: (q) => q.state.data?.data?.some(p => p.status === 'pr_opened' && p.pr_state === 'open') ? 30_000 : false })`. The optional `options` second argument lands in Story 1.1's hook extension — this story consumes it (no further hook-file edits in this story).
4. Render filter card, table card, paginator. Mirror the JSX structure of `studies/page.tsx:44-91`.
5. Apply client-side source filter AFTER fetch: `const visibleRows = rows.filter(r => sourceFilter === 'all' || (sourceFilter === 'study' ? r.study_id != null : r.study_id == null));`. Add a comment noting the pagination caveat (logged in §6 risks).
6. Build `proposals-table.tsx` mirroring `studies/studies-table.tsx`:
   - Row link: `/proposals/${p.id}`
   - Source column: study link (`/studies/${p.study_id}`) when `study_id` is non-null, else `"manual"` text
   - Cluster: `p.cluster.name` (use `_ClusterEmbed.name` — wire shape from `schemas.py:702`)
   - Template: `p.template.name` (wire shape from `schemas.py:711`)
   - Status: `<StatusBadge kind="proposal" value={p.status} />`
   - PR state: `<StatusBadge kind="proposal_pr" value={p.pr_state} />` (only when `pr_state` non-null)
   - Metric delta: render `<MetricDelta>` from `p.metric_delta` — handle the JSON shape (see "Metric-delta JSON shape" below)
   - Created: `new Date(p.created_at).toLocaleString()`
7. Use `data-testid={\`proposal-row-${p.id}\`}` for E2E hooks.
8. Empty-state component: `<EmptyState title="No proposals yet" message="They appear automatically when studies complete." />` per spec §3 in-scope text.

**Metric-delta JSON shape decision (logged):** Backend persists `proposals.metric_delta` as `JSONB`. The wire type is `dict[str, Any] | None` per `ProposalSummary.metric_delta` (schemas.py:753). `feat_digest_proposal` Story 2.x serializes `{ "primary": "ndcg@10", "baseline": 0.42, "best": 0.51, "delta": 0.09, "delta_pct": 21.4 }` (verified via `grep -rn "metric_delta" backend/workers/digest.py`). The list table shows `metric_delta.primary` + the absolute `baseline → best` + `delta_pct`. Use the existing `<MetricDelta baseline={md.baseline} achieved={md.best} />`.

**Definition of Done (DoD)**

- `cd ui && pnpm typecheck` clean.
- `cd ui && pnpm lint` clean.
- `cd ui && pnpm test __tests__/app/proposals/page.test.tsx` covers:
  - AC-6: filter chip click triggers refetch with new `?status=`; selecting `"all"` removes the param.
  - Cluster filter dropdown selection adds `cluster_id` to the wire request.
  - Source filter is client-side (verifies row count changes without a network call).
  - 30s auto-refetch fires when at least one row is `pr_opened+open` (mock with vi fake timers; assert the msw handler was hit twice within 30.1s).
  - Empty state renders for `data.length===0`.
- `pnpm test __tests__/components/proposals/proposals-table.test.tsx` covers row rendering for 4 status values + study-link vs manual.
- `pnpm test __tests__/components/proposals/proposal-filter-chips.test.tsx` covers status + source chip onChange.
- `cd ui && pnpm build` succeeds (catches SSR/Suspense regressions).

---

## Epic 3 — `/proposals/[id]` detail route

### Story 3.1 — Detail page shell: header + config-diff + metric-delta + suggested-followups + pr_open_error Alert

**Outcome:** Visiting `/proposals/{id}` renders four sections in order: header (back link, status badge, cluster/template names, created_at, optional red Alert when `pr_open_error` is populated AND status is `pending`), config-diff table, metric-delta panel, suggested-followups list. Polling is OFF for this story; Story 3.2 wires the PR-panel + polling cadence.

**New files**

| File | Purpose |
|---|---|
| `ui/src/app/proposals/[id]/page.tsx` | Route entry. Default-export `ProposalDetailPage({ params })`. Wraps a named export `ProposalDetailView({ proposalId })` so tests can render the view directly (mirrors `studies/[id]/page.tsx`). |
| `ui/src/components/proposals/proposal-header.tsx` | Header block: back link + h1 + status badge + cluster/template inline summary + created_at. |
| `ui/src/components/proposals/proposal-error-alert.tsx` | Red Alert div rendering `pr_open_error` (no shadcn `<Alert>` primitive exists in this repo; use a styled `<div role="alert">` matching `feat_studies_ui` `EmptyState` styling conventions). |
| `ui/src/components/proposals/config-diff-panel.tsx` | Renders `proposal.config_diff` JSONB as a 3-column table: key, from, to. |
| `ui/src/components/proposals/suggested-followups-panel.tsx` | Renders `proposal.digest.suggested_followups[]` as bullets; each has a `<Link href={\`/studies?hypothesis=${encodeURIComponent(f)}\`}>` "Create study from this hypothesis" action. |

**Modified files** — none.

**Endpoints** (consumed)

| Method | Path | Request | Success | Error |
|---|---|---|---|---|
| `GET` | `/api/v1/proposals/{id}` | — | `200` `ProposalDetail` (with inline `study_summary` + `digest`) | `404 PROPOSAL_NOT_FOUND` |

**Key interfaces**

```typescript
export interface ProposalDetailViewProps { proposalId: string; }
export function ProposalDetailView({ proposalId }: ProposalDetailViewProps): JSX.Element;

export interface ProposalHeaderProps { proposal: ProposalDetail; }
export interface ProposalErrorAlertProps { error: string; }
export interface ConfigDiffPanelProps { diff: Record<string, unknown>; }
export interface SuggestedFollowupsPanelProps { followups: readonly string[]; }
```

**UI element inventory (creation)**

| # | Element | Data source |
|---|---|---|
| 1 | Back link `← All proposals` | static `<Link href="/proposals">` |
| 2 | h1 `"Proposal detail"` | static |
| 3 | Status badge in header | `proposal.status` via `<StatusBadge kind="proposal">` |
| 4 | Inline cluster + template summary | `proposal.cluster.name` + `proposal.template.name + " v" + .version` |
| 5 | Created-at timestamp | `proposal.created_at` |
| 6 | Red error alert (conditional) | `proposal.pr_open_error` && `proposal.status === 'pending'` |
| 7 | Config-diff table | `proposal.config_diff` (JSONB) |
| 8 | Metric-delta panel | `proposal.metric_delta` (JSONB) via `<MetricDelta>` |
| 9 | Suggested-followups list | `proposal.digest?.suggested_followups` (skip section if empty/null) |

**`config_diff` JSON shape decision (logged):** Backend writes `proposals.config_diff` from `feat_digest_proposal` Story 2.x as a flat `{ "key": ["before_value", "after_value"] }` dict (verified via `grep -rn "config_diff" backend/workers/digest.py`). For manual proposals, the operator supplies the diff shape unchanged. Render as a 3-column table; `JSON.stringify(v)` for non-primitive values; muted-gray dash for missing sides.

**Tasks**

1. Create `ui/src/app/proposals/[id]/page.tsx`. Use `use(params)` to unwrap the Next 16 promise-form params (mirrors `studies/[id]/page.tsx:122`). **Wrap the inner client view in `<Suspense>`** — Story 3.2 adds `useSearchParams()` to the inner view, which in Next 16 App Router requires a Suspense boundary or the build fails. Structure:
   ```tsx
   export function ProposalDetailView({ proposalId }: { proposalId: string }) { /* uses useSearchParams in Story 3.2 */ }
   export default function ProposalDetailPage({ params }: RouteProps) {
     const { id } = use(params);
     return (
       <Suspense fallback={<main className="mx-auto max-w-7xl p-6">Loading…</main>}>
         <ProposalDetailView proposalId={id} />
       </Suspense>
     );
   }
   ```
   Mirror the `Suspense`-around-inner pattern from `studies/page.tsx:94-101` (where `useSearchParams` is used). Per GPT-5.5 cycle-2 B1.
2. `ProposalDetailView`:
   - `const proposalQ = useProposal(proposalId);` — refetchInterval intentionally omitted in this story; Story 3.2 wires it.
   - Conditional render: `isPending` → "Loading…", `isError` (with `errorCode === 'PROPOSAL_NOT_FOUND'`) → `<EmptyState title="Proposal not found">`, `isError` other → `<EmptyState title="Backend unreachable">`, success → 4 sections.
3. `ProposalHeader`: layout mirrors `studies/study-header.tsx` (read it for reference; copy the flex/spacing).
4. `ProposalErrorAlert`: styled `<div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">{error}</div>`. Render only when `proposal.status === 'pending' && proposal.pr_open_error`.
5. `ConfigDiffPanel`: use shadcn `<Table>` (already in `components/ui/table.tsx`). Three columns: Key / From / To. Sort keys alphabetically. Use `JSON.stringify(v)` for objects/arrays.
6. `MetricDeltaPanel`: inline in the page (5 lines of JSX); when `proposal.metric_delta` is null, render `"—"`. Otherwise `<MetricDelta baseline={md.baseline} achieved={md.best} />` with the primary metric name above.
7. `SuggestedFollowupsPanel`: render only when `proposal.digest?.suggested_followups?.length > 0`. Each is a bullet `<li>` with the text + a `<Link>` to `/studies?hypothesis=${encodeURIComponent(f)}` styled as a button via `<Button asChild variant="outline" size="sm">`.

**Definition of Done (DoD)**

- `pnpm typecheck` + `pnpm lint` clean.
- `pnpm test __tests__/app/proposals/[id]/page.test.tsx` covers (this story's slice):
  - Renders all 4 sections for a `pending` proposal with `digest.suggested_followups: ['try BM25 tweak']`.
  - Renders the red Alert when `status='pending' && pr_open_error='Branch already exists'` (AC-4).
  - Does NOT render the Alert when `status='pr_opened'` (even if pr_open_error is populated — defensive).
  - AC-5: clicking the suggested-followup link navigates to `/studies?hypothesis=try%20BM25%20tweak`.
  - 404 PROPOSAL_NOT_FOUND renders the EmptyState.

---

### Story 3.2 — PR panel + Open-PR button state machine + auto-trigger from `?action=open_pr`

**Outcome:** A `<PrPanel>` section beneath the metric-delta panel renders one of four state-based views: pending (Open PR button + optional retry-after-error), pr_opened (PR link + pr_state badge + auto-poll), pr_merged (PR link + pr_merged_at timestamp), rejected (rejected_reason + no actions). Polling cadences: **3s after Open-PR submit until the worker writes back** (status flips to `pr_opened` OR `pr_open_error` populated OR a 60s safety cap); 30s steady-state while `status='pr_opened' AND pr_state='open'`; off otherwise. When the URL contains `?action=open_pr` AND `status==='pending'` AND no in-flight mutation exists, fire the Open-PR mutation once on mount and immediately strip the `?action=` query param via `router.replace(\`/proposals/${id}\`)` so navigation back to the URL does NOT re-fire the mutation.

**Critical architecture decision (per GPT-5.5 cross-model review A1 + B1):** `useOpenPR()` is invoked in the **page component** (`[id]/page.tsx`), NOT in `<PrPanel>`. The page passes the mutation instance (or a `{ mutate, isPending }` adapter) into `<PrPanel>` as a prop. This is required because:
1. `useProposal`'s `refetchInterval` function (also living in the page) needs to read `openPr.isPending` to decide the 3s cadence — if `useOpenPR` were inside `<PrPanel>`, the page poller cannot see the panel's mutation state.
2. The auto-trigger `useEffect` from `?action=open_pr` needs the same mutation instance to fire it.

**Critical polling decision (per GPT-5.5 cross-model review B1):** Do NOT key the 3s cadence on `openPr.isPending` alone — `POST /open_pr` returns 202 immediately, so `isPending` flips false within ~50ms while the worker takes 5–30s. Instead, the page maintains a `postOpenPrPolling: boolean` React state that flips ON when the mutation succeeds with 202 AND flips OFF when EITHER:
- `proposal.status` transitions from `'pending'` (worker wrote back), OR
- `proposal.pr_open_error` becomes non-null (worker errored), OR
- 60s safety timer elapses (`setTimeout` cleared on flip-off paths).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/pr-panel.tsx` | The 4-state PR panel + Open-PR button + auto-trigger logic. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/proposals/[id]/page.tsx` | (a) Hoist `useOpenPR()` call to the page (was in PrPanel in earlier draft). (b) Add `postOpenPrPolling: boolean` React state + `safetyTimerRef: MutableRefObject<ReturnType<typeof setTimeout> \| null>`. (c) Define ONE page-local helper `fireOpenPR()` that (1) clears any existing safety timer, (2) calls `openPr.mutate(proposalId, { onSuccess: () => { setPostOpenPrPolling(true); safetyTimerRef.current = setTimeout(() => { setPostOpenPrPolling(false); safetyTimerRef.current = null; }, 60_000); } })`. (d) Add an unmount `useEffect` returning a cleanup that clears the safety timer on unmount (prevents "state update after unmount" warnings in tests). (e) Add a flip-off `useEffect` that calls `setPostOpenPrPolling(false)` + clears the timer when `status !== 'pending' \|\| pr_open_error`. (f) Compose `<PrPanel proposal={proposalQ.data} onOpenPR={fireOpenPR} openPrIsPending={openPr.isPending \|\| postOpenPrPolling} />` — BOTH the click path AND the `?action=open_pr` auto-trigger go through `fireOpenPR()` (per GPT-5.5 cycle-2 A1; do NOT call `openPr.mutate` directly anywhere). (g) Wire the polling `refetchInterval` to `useProposal` per the cadence table below. (h) Add the `useEffect` that calls `fireOpenPR()` for `?action=open_pr` AND strips the param via `router.replace(\`/proposals/${proposalId}\`)`. |

**Endpoints** (consumed)

| Method | Path | Request | Success | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/open_pr` | `{}` | `202` `{ proposal_id, status: "pending", message }` | `404 PROPOSAL_NOT_FOUND`, `409 INVALID_STATE_TRANSITION`, `422 CLUSTER_HAS_NO_CONFIG_REPO`, `503 GITHUB_NOT_CONFIGURED`, `503 QUEUE_UNAVAILABLE` |

**Key interfaces**

```typescript
export interface PrPanelProps {
  proposal: ProposalDetail;
  /** Page-owned mutation trigger; page lifts useOpenPR so the page-level
   *  refetchInterval can read mutation state without prop-drilling pending flags. */
  onOpenPR: () => void;
  /** True when the click-driven 3s polling cadence is active. Combines
   *  openPr.isPending (mutation flight) with postOpenPrPolling (post-202 wait
   *  for the worker writeback). */
  openPrIsPending: boolean;
}
export function PrPanel({ proposal, onOpenPR, openPrIsPending }: PrPanelProps): JSX.Element;
```

**Polling cadence (FR-2 + FR-3)** — driven by `useProposal(id, { refetchInterval: fn })` in the page

| Trigger | Cadence | Rationale |
|---|---|---|
| `openPrIsPending===true` AND `status==='pending'` AND `!pr_open_error` AND <60s since submit | **3 s** | Post-click webhook-wait — fires until worker writes back OR errors OR safety cap |
| `status==='pr_opened'` AND `pr_state==='open'` | **30 s** | Steady-state webhook-fallback per FR-2 |
| `pr_open_error` populated AND `status==='pending'` | **off** | Show retry-ready Alert; operator decides |
| All other states (`pr_merged`, `rejected`, etc.) | **off** | Terminal |

Implementation outline (in `[id]/page.tsx`) — destructured primitive dependencies per GPT-5.5 cycle-3 B1 to keep effect identities stable:

```tsx
const [postOpenPrPolling, setPostOpenPrPolling] = useState(false);
const openPr = useOpenPR();
const { mutate: mutateOpenPR } = openPr;   // stable function ref
const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

const proposalQ = useProposal(proposalId, {
  refetchInterval: (q) => {
    const p = q.state.data;
    if (!p) return false;
    if (postOpenPrPolling && p.status === 'pending' && !p.pr_open_error) return 3_000;
    if (p.status === 'pr_opened' && p.pr_state === 'open') return 30_000;
    return false;
  },
});

// Derive stable primitives from proposalQ.data so the flip-off effect doesn't
// fire on every refetch (the `data` reference changes even when status/error
// haven't moved).
const proposalStatus = proposalQ.data?.status;
const proposalPrOpenError = proposalQ.data?.pr_open_error ?? null;

// One helper used by BOTH the manual click and the `?action=open_pr` auto-trigger.
// Wraps openPr.mutate with the onSuccess that flips postOpenPrPolling on and
// installs the 60s safety cap. Clears any existing safety timer first so a
// rapid re-click doesn't leak a stale timeout. NEVER call openPr.mutate
// directly anywhere else (per GPT-5.5 cycle-2 A1).
const fireOpenPR = useCallback(() => {
  if (safetyTimerRef.current) {
    clearTimeout(safetyTimerRef.current);
    safetyTimerRef.current = null;
  }
  mutateOpenPR(proposalId, {
    onSuccess: () => {
      setPostOpenPrPolling(true);
      safetyTimerRef.current = setTimeout(() => {
        setPostOpenPrPolling(false);
        safetyTimerRef.current = null;
      }, 60_000);
    },
  });
}, [mutateOpenPR, proposalId]);

// Flip off the 3s cadence when the worker writes back (status flip or error).
// Depends on primitives only — proposalQ.data identity is NOT in the dep list.
useEffect(() => {
  if (!postOpenPrPolling) return;
  if (proposalStatus !== undefined && (proposalStatus !== 'pending' || proposalPrOpenError)) {
    setPostOpenPrPolling(false);
    if (safetyTimerRef.current) {
      clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
  }
}, [postOpenPrPolling, proposalStatus, proposalPrOpenError]);

// Unmount cleanup — prevents "state update after unmount" warnings in tests
// and dev navigation (per GPT-5.5 cycle-2 B2).
useEffect(() => {
  return () => {
    if (safetyTimerRef.current) {
      clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
  };
}, []);
```

**UI element inventory**

| # | Element | When rendered | Behavior |
|---|---|---|---|
| 1 | "Open PR" button | Always rendered when `proposal.status==='pending'`; hidden otherwise (per FR-3 — hidden, not just disabled, when `status!=='pending'`). | Disabled while `openPrIsPending` is true; label flips `"Open PR"` → `"Opening PR…"` during that window. The button remains in the DOM during the mutation + worker-wait (per GPT-5.5 cycle-3 B2). |
| 2 | Spinner row | `openPrIsPending` is true (covers both mutation flight AND post-202 worker-wait) | Shows "Working on it… (Xs)" beneath the disabled button |
| 3 | Red error Alert (retry-ready) | `status==='pending' && pr_open_error` | Same `<ProposalErrorAlert>` used in header; Story 3.1 covers the header copy; this duplicates here for visibility next to the button |
| 4 | PR link `<a target="_blank">{pr_url}</a>` | `pr_url` populated | Opens GitHub in new tab |
| 5 | PR state badge | `pr_state` non-null | `<StatusBadge kind="proposal_pr" value={pr_state} />` |
| 6 | Merged-at timestamp | `status==='pr_merged' && pr_merged_at` | `Merged on {toLocaleString()}` |
| 7 | Rejected reason | `status==='rejected'` | `rejected_reason ?? "No reason provided"` |

**Tasks**

1. Build `pr-panel.tsx` as a `'use client'` component. Props match the `PrPanelProps` interface above — `useOpenPR` is NOT called inside this component (lifted to the page).
2. The PrPanel button calls `props.onOpenPR()` on click. Button label flips to `"Opening PR…"` and `disabled` becomes true when `props.openPrIsPending` is true.
3. Page-level auto-trigger logic (lives in `[id]/page.tsx`, not PrPanel) — call the page's `fireOpenPR()` helper (NOT `openPr.mutate` directly) so both paths run the same `onSuccess` flip-on-polling logic. Use `useRef<boolean>(false)` for the Strict-Mode re-run guard AND `router.replace` to drop the URL param after firing so a remount/back-nav with the same URL no longer has `?action=open_pr` to react to:
   ```tsx
   const searchParams = useSearchParams();
   const router = useRouter();
   const action = searchParams.get('action');
   const autoFired = useRef(false);
   const { isPending: openPrMutationPending } = openPr;
   // proposalStatus already destructured in Pattern E (see Implementation outline)
   useEffect(() => {
     if (autoFired.current) return;
     if (action !== 'open_pr') return;
     if (proposalStatus !== 'pending') return;
     if (openPrMutationPending) return;
     autoFired.current = true;
     fireOpenPR();
     router.replace(`/proposals/${proposalId}`);
   }, [action, proposalStatus, openPrMutationPending, fireOpenPR, proposalId, router]);
   ```
   `fireOpenPR` is stable via `useCallback([mutateOpenPR, proposalId])` — both deps are stable function/string refs. The dep list contains only primitives + stable callbacks (no whole-object identities). Per GPT-5.5 cycle-1 B3 + cycle-3 B1.
4. The `useProposal` call lives in `page.tsx` (added in this story) — wire the `refetchInterval` function per the cadence table above plus the implementation outline.
5. After successful mutation, the page-managed `postOpenPrPolling` flag goes true; the 3s cadence runs until the worker writes back (status change OR pr_open_error) OR the 60s safety cap fires. The global mutation `onSettled` invalidates `['proposal', id]` → page refetches with the new state.
6. The button MUST be hidden (rendered conditionally) when `status !== 'pending'` per FR-3, not just disabled.

**Definition of Done (DoD)**

- `pnpm typecheck` + `pnpm lint` clean.
- `pnpm test __tests__/components/proposals/pr-panel.test.tsx` covers (PrPanel-only, with `onOpenPR` + `openPrIsPending` as props):
  - AC-1: button click invokes `onOpenPR`; when `openPrIsPending=true`, label flips to "Opening PR…" and `disabled` becomes true.
  - AC-4: `pr_open_error` populated AND `status='pending'` → red Alert visible, button visible + enabled (retry path).
  - FR-3: button hidden when `status='pr_opened'`, `pr_merged`, `rejected`.
  - PR link renders with `target="_blank" rel="noopener"` when `pr_url` populated.
- `pnpm test __tests__/app/proposals/[id]/page.test.tsx` (extends Story 3.1 file) covers:
  - AC-1 full flow: page-owned `useOpenPR` → 202 response → `postOpenPrPolling` flips on → msw handler hit ~3 times within 9s (3s cadence) → switch msw to return `pr_opened` payload → next refetch sees the state change → `postOpenPrPolling` flips off via the useEffect.
  - AC-3: 30s steady-state poll while `pr_opened+open`; assert msw handler hit twice within 30.1s using `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync(30_100)`.
  - 60s safety cap: simulate worker that NEVER writes back; assert polling stops after 60s and the operator can re-click Open PR.
  - Auto-trigger: URL `?action=open_pr` + `status=pending` → mutation fires exactly once on mount AND `router.replace` is called with `/proposals/{id}` (no query param). Unmount + remount with the same `/proposals/{id}` URL (no `?action=`) → mutation does NOT fire again.
  - FR-3 toast surface (asserted against the contract, not the formatted string per GPT-5.5 review B6): spy on `MutationCache.onError` and assert the `err` argument is an `ApiError` with `errorCode === 'GITHUB_NOT_CONFIGURED'` (and analogously for `CLUSTER_HAS_NO_CONFIG_REPO` 422 and `QUEUE_UNAVAILABLE` 503). The fact that `query-provider.tsx` then calls `toast.error(toToastMessage(err))` is already tested by the QueryProvider test suite — no need to re-assert toast formatting here.
- Manual smoke (operator step, not gated in CI): `make up` → visit `/proposals/{id}?action=open_pr` for a pending proposal → PR appears in <60s on GitHub.

---

### Story 3.3 — Reject confirm dialog + 409 INVALID_STATE_TRANSITION refresh

**Outcome:** When `status==='pending'`, a "Reject" button beside the PR panel opens an AlertDialog with a 0–500 char reason `<textarea>`. Confirming POSTs to `/api/v1/proposals/{id}/reject`. On success the proposal refreshes to `rejected`. On 409 (concurrent merge race per spec §11), the global toast fires AND the detail query is invalidated so the operator sees the new state instead of a stale dialog.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/reject-dialog.tsx` | Reject button + AlertDialog (mirrors `studies/study-action-bar.tsx`). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/proposals/[id]/page.tsx` | Compose `<RejectDialog proposal={proposal} />` in a flex container next to `<PrPanel>` (only renders the button when `status==='pending'`). |

**Endpoints** (consumed)

| Method | Path | Request | Success | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/reject` | `{ reason: string \| null }` | `200` `ProposalDetail` | `404 PROPOSAL_NOT_FOUND`, `409 INVALID_STATE_TRANSITION` |

**Key interfaces**

```typescript
export interface RejectDialogProps { proposal: ProposalDetail; }
export function RejectDialog({ proposal }: RejectDialogProps): JSX.Element;
```

**Tasks**

1. Copy the `<AlertDialog>` shape from `studies/study-action-bar.tsx:35-58`. Title: `"Reject this proposal?"`. Description: `"Rejected proposals cannot be re-pended. Provide an optional reason for the audit trail."`.
2. Add a `<textarea>` with `maxLength={500}` (matches backend's `RejectProposalRequest.reason` Field max_length, schemas.py:699). Local state `reason: string`.
3. Confirm action — the `<AlertDialogAction>` default closes the dialog on click; that's wrong here because we want to keep the dialog open while the mutation is in flight and only close on success. Per GPT-5.5 review B4:
   ```tsx
   <AlertDialogAction
     disabled={reject.isPending}
     data-testid="confirm-reject"
     onClick={(event) => {
       event.preventDefault();
       reject.mutate(
         { proposalId: proposal.id, reason: reason || null },
         {
           onSuccess: () => {
             toast.success('Proposal rejected');
             setOpen(false);
           },
           // No onError — global MutationCache handler toasts.
         },
       );
     }}
   >
     {reject.isPending ? 'Rejecting…' : 'Reject proposal'}
   </AlertDialogAction>
   ```
4. The 409 refresh behavior is delivered by Story 1.1's `useRejectProposal.onSettled` invalidation. The dialog stays open while the mutation is in flight (per `event.preventDefault()`), and stays open on error so the operator sees the new state when the detail query refetches. The user can click "Keep pending" to dismiss.
5. Render the trigger button only when `proposal.status==='pending'` (button vanishes after success because the detail query refetches and `status==='rejected'`).

**Definition of Done (DoD)**

- `pnpm typecheck` + `pnpm lint` clean.
- `pnpm test __tests__/components/proposals/reject-dialog.test.tsx` covers:
  - AC-2 happy path: reason text submits → success toast → dialog closes → proposal status flips to `rejected`.
  - `event.preventDefault()` keeps the dialog open during the in-flight POST — assert the dialog is still in the DOM immediately after click, before the msw handler resolves.
  - `disabled={reject.isPending}` — assert the confirm button is disabled mid-flight; assert clicking it again during the in-flight POST does NOT double-submit (count msw handler calls).
  - Spec §11 "concurrent merge during reject" — mount the detail view with an active `useProposal('p1')` query; the reject endpoint returns 409 `INVALID_STATE_TRANSITION`; subsequent `GET /proposals/p1` is configured to return the now-`pr_merged` payload. Assert: (a) the global `MutationCache.onError` fires once with `errorCode === 'INVALID_STATE_TRANSITION'`, (b) the msw handler for `GET /proposals/p1` is called a second time (invalidation triggered refetch), (c) the UI rerenders showing the `pr_merged` state. This methodology replaces the earlier `queryClient.getQueryState` assertion per GPT-5.5 review B5.
- Manual smoke (not CI-gated): operator can reject a pending proposal end-to-end via the UI.

---

## Epic 4 — Docs + cleanup

### Story 4.1 — Mark US-28 + US-29 implemented; update state.md / architecture.md / CLAUDE.md; add ui-debugging.md proposals section

**Outcome:** Project docs reflect the new pages. The MVP1 user stories file marks proposals UI as implemented. `state.md` adds the feature to "Most recent meaningful changes". `architecture.md` adds the proposals routes to the "Where the code lives" UI section. CLAUDE.md feature-status table flips `feat_proposals_ui` from "Spec approved, plan pending" to "Complete (PR #N, merged YYYY-MM-DD)" (the merge date is filled in at the finalization step by `/impl-execute`, not at story-implementation time).

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/mvp1-user-stories.md` | Mark US-28 (Open PR via UI) + US-29 (PR state mirror) as `Implemented` with a feature-link to `feat_proposals_ui`. |
| `docs/03_runbooks/ui-debugging.md` | Add a "Proposals routes" sub-section: where the hooks live, what `?action=open_pr` does, polling cadence table, where to look for the global error-toast wiring. |
| `state.md` | Add an entry to "Most recent meaningful changes" with the feature summary, stories count, tests count, GPT-5.5 cycle count (filled by `/impl-execute` finalization). |
| `architecture.md` | Add `/proposals` + `/proposals/[id]` to the "Where the code lives" `ui/` section. |
| `CLAUDE.md` | Flip the feature-status table row for `feat_proposals_ui` from "Spec approved, plan pending" to "Complete (PR #N, merged YYYY-MM-DD)". |
| `docs/02_product/planned_features/feat_proposals_ui/feature_spec.md` | §18 "Definition of feature done" — check the AC-1 through AC-7 box. |

**Tasks**

1. Edit `docs/02_product/mvp1-user-stories.md` — locate the US-28 + US-29 rows and add the Implemented status + feature link. Match the format used for US-13/14/15 (verified via `grep "Implemented" docs/02_product/mvp1-user-stories.md`).
2. Edit `docs/03_runbooks/ui-debugging.md` — append the proposals routes sub-section.
3. Capture follow-up idea file: `docs/02_product/planned_features/chore_proposals_source_filter_server_side/idea.md` documenting the client-side source filter's pagination caveat surfaced in §6 risks (per CLAUDE.md "Tangential discoveries — capture as idea files immediately" + GPT-5.5 review A5).
4. The state.md / architecture.md / CLAUDE.md updates are typically applied by `/impl-execute`'s finalization step (Step 7), not as a story task. This story documents the requirement; the finalization commit lands them.

**Definition of Done (DoD)**

- `docs/02_product/mvp1-user-stories.md` — US-28 + US-29 marked Implemented.
- `docs/03_runbooks/ui-debugging.md` — new proposals routes section added.
- After `/impl-execute` finalization runs: `state.md` + `architecture.md` + `CLAUDE.md` updated.
- Spec §18 DoD boxes checked.

---

## UI Guidance (required for frontend-facing work)

### Reference: current component structure

This feature is **greenfield** for `ui/src/app/proposals/` and `ui/src/components/proposals/` — no existing files to modify there. The modifications are scoped to `ui/src/lib/api/proposals.ts` only (extending, not replacing).

**Existing files this plan touches:**
- `ui/src/lib/api/proposals.ts` — 52 lines (verified via `wc -l`). Story 1.1 adds 3 new exports + narrows one type. Insertion points: end of file for the new hooks; line 17 for the `status` field narrowing.
- `ui/src/app/proposals/[id]/page.tsx` — Story 3.2 modifies the file Story 3.1 created (in-PR sequencing).

**Analogous file references (read these for pattern source):**
- `ui/src/lib/api/studies.ts` (125 lines) — exact analog for the hook shape (refetchInterval function form, mutation hooks, onSettled invalidation).
- `ui/src/app/studies/[id]/page.tsx` (125 lines) — exact analog for the detail page (back link, Loading / EmptyState / data branches, sections, caller-driven polling).
- `ui/src/app/studies/page.tsx` (102 lines) — exact analog for the list page (Suspense wrapping, useSearchParams URL-backed status filter, cursor stack, EmptyState branch).
- `ui/src/components/studies/study-action-bar.tsx` (59 lines) — exact analog for the reject confirm dialog (AlertDialog with reason inputs, mutation invocation).
- `ui/src/components/studies/digest-panel.tsx` (101 lines) — the source of the `/proposals/{id}?action=open_pr` link this feature consumes.
- `ui/src/components/studies/studies-table.tsx` (77 lines) — exact analog for the proposals table.
- `ui/src/components/studies/study-status-filter-chips.tsx` (41 lines) — exact analog for the proposal-status filter chips.

### Analogous markup patterns

**Pattern A — List page shell** (from `ui/src/app/studies/page.tsx:44-91`):

```tsx
<main className="mx-auto max-w-7xl space-y-6 p-6">
  <div className="flex items-center justify-between">
    <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>
  </div>
  <Card>
    <CardHeader>
      <CardTitle className="text-base">Filters</CardTitle>
    </CardHeader>
    <CardContent className="space-y-4">
      <ProposalStatusFilterChips value={statusParam} onChange={setStatus} />
      <ProposalSourceFilterChips value={sourceFilter} onChange={setSourceFilter} />
      <ClusterFilterSelect value={clusterFilter} onChange={setClusterFilter} />
    </CardContent>
  </Card>
  <Card>
    <CardContent className="pt-6">
      {query.isPending ? (
        <p className="py-12 text-center text-sm text-muted-foreground">Loading proposals…</p>
      ) : query.isError ? (
        <EmptyState
          title="Backend unreachable"
          message="Check `make logs` and confirm the API container is healthy."
        />
      ) : visibleRows.length === 0 ? (
        <EmptyState
          title="No proposals yet"
          message="They appear automatically when studies complete."
        />
      ) : (
        <>
          <ProposalsTable rows={visibleRows} />
          <CursorPaginator … />
        </>
      )}
    </CardContent>
  </Card>
</main>
```

**Pattern B — Filter chip group** (from `ui/src/components/studies/study-status-filter-chips.tsx:18-39`):

```tsx
<div className="flex flex-wrap items-center gap-2" role="group" aria-label="Status filter">
  {CHIP_VALUES.map((chip) => {
    const isActive = chip === active;
    return (
      <Button
        key={chip}
        type="button"
        variant={isActive ? 'default' : 'outline'}
        size="sm"
        data-testid={`proposal-status-chip-${chip}`}
        data-active={isActive ? 'true' : 'false'}
        onClick={() => onChange(chip === ALL ? null : chip)}
      >
        {chip}
      </Button>
    );
  })}
</div>
```

**Pattern C — Detail page shell** (from `ui/src/app/studies/[id]/page.tsx:44-117`; outer `<Suspense>` wrapping required because Story 3.2 adds `useSearchParams()` to the inner view — see Story 3.1 Task 1 for the outer page shell):

```tsx
<main className="mx-auto max-w-7xl space-y-6 p-6">
  <div>
    <Link href="/proposals" className="text-sm text-blue-600 underline-offset-4 hover:underline">
      ← All proposals
    </Link>
  </div>
  {proposalQ.isPending ? (
    <Card><CardContent><p className="py-12 text-center text-sm text-muted-foreground">Loading…</p></CardContent></Card>
  ) : proposalQ.isError ? (
    <EmptyState title="Proposal not found" message="The proposal may have been deleted." />
  ) : proposalQ.data ? (
    <>
      <ProposalHeader proposal={proposalQ.data} />
      <ConfigDiffPanel diff={proposalQ.data.config_diff} />
      <MetricDeltaPanel metricDelta={proposalQ.data.metric_delta} />
      <div className="flex items-center gap-3">
        <PrPanel proposal={proposalQ.data} />
        {proposalQ.data.status === 'pending' && <RejectDialog proposal={proposalQ.data} />}
      </div>
      {proposalQ.data.digest?.suggested_followups && proposalQ.data.digest.suggested_followups.length > 0 && (
        <SuggestedFollowupsPanel followups={proposalQ.data.digest.suggested_followups} />
      )}
    </>
  ) : null}
</main>
```

**Pattern D — Reject confirm dialog** (adapted from `studies/study-action-bar.tsx:22-58`; preventDefault + disabled-while-pending per GPT-5.5 review B4):

```tsx
<AlertDialog open={open} onOpenChange={setOpen}>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Reject this proposal?</AlertDialogTitle>
      <AlertDialogDescription>
        Rejected proposals cannot be re-pended. Provide an optional reason for the audit trail.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <div className="my-3">
      <Textarea
        value={reason}
        maxLength={500}
        placeholder="Optional reason…"
        onChange={(e) => setReason(e.target.value)}
        data-testid="reject-reason-input"
        disabled={reject.isPending}
      />
    </div>
    <AlertDialogFooter>
      <AlertDialogCancel disabled={reject.isPending}>Keep pending</AlertDialogCancel>
      <AlertDialogAction
        data-testid="confirm-reject"
        disabled={reject.isPending}
        onClick={(event) => {
          event.preventDefault();   // keep dialog open during mutation
          reject.mutate(
            { proposalId: proposal.id, reason: reason || null },
            {
              onSuccess: () => {
                toast.success('Proposal rejected');
                setOpen(false);
              },
              // No onError — global MutationCache handler toasts on 409/etc.
            },
          );
        }}
      >
        {reject.isPending ? 'Rejecting…' : 'Reject proposal'}
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

**Pattern E — Caller-driven refetchInterval function form with post-202 worker-wait flag** (Pattern E is unique to this feature — no exact analog in the codebase since `feat_studies_ui`'s `useStudy` keys polling on `data.status === 'running'`, a server-driven state, whereas Open-PR is a client-mutation-driven wait):

```tsx
// Lives in ui/src/app/proposals/[id]/page.tsx
const [postOpenPrPolling, setPostOpenPrPolling] = useState(false);
const openPr = useOpenPR();           // hoisted to page (NOT in PrPanel) per GPT-5.5 A1
const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

const proposalQ = useProposal(proposalId, {
  refetchInterval: (q) => {
    const p = q.state.data;
    if (!p) return false;
    // 3s: open_pr was submitted, worker hasn't written back yet
    if (postOpenPrPolling && p.status === 'pending' && !p.pr_open_error) return 3_000;
    // 30s: steady-state webhook-fallback per FR-2
    if (p.status === 'pr_opened' && p.pr_state === 'open') return 30_000;
    return false;
  },
});

// Stop the 3s cadence when worker writes back (status flips or pr_open_error set)
useEffect(() => {
  if (!postOpenPrPolling) return;
  const p = proposalQ.data;
  if (!p) return;
  if (p.status !== 'pending' || p.pr_open_error) {
    setPostOpenPrPolling(false);
    if (safetyTimerRef.current) {
      clearTimeout(safetyTimerRef.current);
      safetyTimerRef.current = null;
    }
  }
}, [postOpenPrPolling, proposalQ.data]);
```

**Why this is more correct than keying polling on `openPr.isPending`:** `POST /open_pr` returns 202 in <100ms. If the polling cadence were `if (openPr.isPending) return 3_000`, polling would stop ~50ms after submit while the worker still needs 5–30s to write back. The `postOpenPrPolling` flag bridges that gap; the 60s safety cap is the hard ceiling for a stuck worker.

**Pattern F — `?action=open_pr` auto-trigger via `fireOpenPR` helper + URL strip** (greenfield — no analogous pattern in the codebase yet; reference Pattern G's `useSearchParams` usage):

```tsx
// Lives in ui/src/app/proposals/[id]/page.tsx — uses fireOpenPR + destructured
// primitives from Pattern E so the dep list contains only stable references.
const searchParams = useSearchParams();
const router = useRouter();
const action = searchParams.get('action');
const autoFired = useRef(false);
const { isPending: openPrMutationPending } = openPr;   // destructured primitive
// proposalStatus is already declared in Pattern E above
useEffect(() => {
  if (autoFired.current) return;
  if (action !== 'open_pr') return;
  if (proposalStatus !== 'pending') return;
  if (openPrMutationPending) return;
  autoFired.current = true;
  fireOpenPR();
  // Strip the action query param so a remount or back-nav with the same URL
  // does NOT re-fire the mutation (the useRef guard alone only survives within
  // one mounted instance, per GPT-5.5 cycle-1 B2).
  router.replace(`/proposals/${proposalId}`);
}, [action, proposalStatus, openPrMutationPending, fireOpenPR, proposalId, router]);
```

Both the manual click (`<PrPanel onOpenPR={fireOpenPR}>`) and the auto-trigger run through the same `fireOpenPR` helper, ensuring the `postOpenPrPolling` flag flips on the success path for BOTH entry points (addresses GPT-5.5 cycle-2 A1).

**Pattern G — URL-backed status filter** (from `ui/src/app/studies/page.tsx:14-40`):

```tsx
const router = useRouter();
const searchParams = useSearchParams();
const statusParam = searchParams.get('status');

function setStatus(next: ProposalStatus | null) {
  const params = new URLSearchParams(searchParams.toString());
  if (next == null) params.delete('status');
  else params.set('status', next);
  const qs = params.toString();
  router.replace(qs ? `/proposals?${qs}` : '/proposals');
  setCursorStack([undefined]);
}
```

### Layout and structure

- List page: stacked cards inside `<main className="mx-auto max-w-7xl space-y-6 p-6">`. Filter card → list card → paginator (paginator lives inside the list card).
- Detail page: same `<main>` wrapper. Sections stack vertically with `space-y-6`. PR panel + Reject button live in a horizontal flex row (`flex items-center gap-3`).
- Responsive behavior inherited from existing shadcn primitives; no extra media queries required for MVP1.

### Confirmation/modal dialog pattern

Use shadcn `AlertDialog` (the project's standard for destructive confirms — see Pattern D above). No `<Dialog>` usage in this feature.

### Visual consistency table

| New UI element | CSS class / component source |
|---|---|
| Page wrapper | `<main className="mx-auto max-w-7xl space-y-6 p-6">` — from `studies/page.tsx:45` |
| Page title | `<h1 className="text-2xl font-semibold tracking-tight">` — same |
| Card | `<Card>` from `components/ui/card.tsx` |
| Filter chip | `<Button variant={active ? 'default' : 'outline'} size="sm">` — from `study-status-filter-chips.tsx:27` |
| Status badge | `<StatusBadge kind="proposal" value={…}>` — from `common/status-badge.tsx:19-24` (`proposal` kind already declared) |
| PR-state badge | `<StatusBadge kind="proposal_pr" value={…}>` — from same table, line 25-29 |
| Metric delta | `<MetricDelta baseline={…} achieved={…}>` — from `common/metric-delta.tsx` |
| Table | shadcn `<Table>` from `components/ui/table.tsx` |
| Native select | `<select className="rounded-md border border-gray-200 bg-white px-2 py-1">` — from `cursor-paginator.tsx:32` |
| Red Alert | inline `<div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">` (no shadcn `Alert` primitive in this repo; mirror error treatment from `query-provider.tsx`'s toast.error pattern) |
| Textarea | `<Textarea>` from `components/ui/textarea.tsx` |
| Loading text | `<p className="py-12 text-center text-sm text-muted-foreground">` — from `studies/[id]/page.tsx:53` |
| Back link | `<Link className="text-sm text-blue-600 underline-offset-4 hover:underline">` — from `studies/[id]/page.tsx:47` |

### Component composition

- `pr-panel.tsx`, `reject-dialog.tsx`, `proposal-header.tsx`, `proposal-error-alert.tsx`, `config-diff-panel.tsx`, `suggested-followups-panel.tsx`, `proposals-table.tsx` — extracted (testable in isolation; the detail page assembles them).
- `proposal-status-filter-chips.tsx`, `proposal-source-filter-chips.tsx`, `cluster-filter-select.tsx` — extracted (mirror `study-status-filter-chips.tsx`).
- `MetricDeltaPanel` (the small section wrapper around `<MetricDelta>`) — inline in `page.tsx` (~5 lines; no benefit to extracting).

### Interaction behavior table

| Action | UI behavior | Wire call | Cache invalidation |
|---|---|---|---|
| Click status chip | URL `?status=` updates; cursor stack resets to root | `GET /proposals?status=<v>` via `useProposals` refetch | none |
| Click source chip | React state updates; rows client-filtered | none | none |
| Change cluster select | React state updates; cursor stack resets | `GET /proposals?cluster_id=<id>` via refetch | none |
| Click "Next" | Push cursor onto stack | `GET /proposals?cursor=<v>` via refetch | none |
| Click row link | Navigate to `/proposals/{id}` | `GET /proposals/{id}` via `useProposal` | none |
| Open detail with `?action=open_pr` | Auto-fire Open-PR mutation once | `POST /proposals/{id}/open_pr` | `['proposal', id]`, `['proposals']` |
| Click "Open PR" | Disable button, show spinner | `POST /proposals/{id}/open_pr` | `['proposal', id]`, `['proposals']` |
| Click "Reject" → confirm | Close dialog, show success toast | `POST /proposals/{id}/reject` body `{ reason }` | `['proposal', id]`, `['proposals']` |
| Click suggested followup action | Navigate to `/studies?hypothesis=<encoded>` | none (page navigation) | n/a |
| Click PR link | Open GitHub in new tab (`target="_blank" rel="noopener"`) | n/a | n/a |
| 503 GITHUB_NOT_CONFIGURED on Open PR | Global toast shows `[GITHUB_NOT_CONFIGURED] …` | already sent | `onSettled` still invalidates → no stale data |

### Handler function patterns

**Open-PR click handler** (in `pr-panel.tsx` — `useOpenPR` is owned by the page; PrPanel just calls the prop):

```tsx
// PrPanel receives onOpenPR (provided by the page) and openPrIsPending.
function handleOpenPRClick() {
  props.onOpenPR();   // global onError toasts on 503/422; onSettled invalidates
}
```

**Reject submit handler** (in `reject-dialog.tsx` — see Pattern D for full JSX with `event.preventDefault()` + `disabled={reject.isPending}`).

**Page-level fetch + polling + auto-trigger** (in `[id]/page.tsx`) — see Pattern E and Pattern F above for the canonical wiring. The hoisted `useOpenPR()` instance is consumed by:
1. The `?action=open_pr` auto-trigger effect (Pattern F),
2. The `PrPanel` (via `onOpenPR={() => fireOpenPR()}` and `openPrIsPending={openPr.isPending || postOpenPrPolling}` props),
3. The polling cadence (indirectly via `postOpenPrPolling`, which `fireOpenPR` flips on after a successful 202 response).

The architecture decision to lift `useOpenPR` to the page is load-bearing: without it the polling function in the page cannot know whether the mutation in PrPanel is in flight, and the auto-trigger effect cannot fire the same mutation instance that PrPanel renders against.

### Information architecture placement

- Top-nav already contains `/proposals` (verified at `ui/src/components/layout/top-nav.tsx:13`); this feature converts that link from a 404 to a live route.
- Order in nav: Dashboard / Clusters / Query Sets / Templates / Studies / **Proposals** / Chat (existing order; unchanged).
- Inbound entry points to `/proposals/{id}`:
  - From `/proposals` list row link (this feature).
  - From `/studies/{id}` digest panel button (already implemented in `feat_studies_ui` Story 3.4 — opens `/proposals/{id}?action=open_pr`).

### Tooltips and contextual help

The spec §11 does not enumerate a tooltip inventory. None required for MVP1.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** This feature is greenfield for the `/proposals` routes. Story 1.1 modifies `proposals.ts` (52 LOC) by extension only — `useProposals` and `useProposalForStudy` are preserved verbatim except for the `filter.status` type narrowing, which is checked by TypeScript at every existing call site (verified: only call site is `useProposalForStudy` itself, which uses `status: 'pending'` — a valid `ProposalStatus`).

### Client-side persistence

This feature uses neither `localStorage` nor `sessionStorage`. All filter state lives in either the URL (`?status=`) or React state (source filter, cluster filter, cursor stack). No persistence story to verify.

---

## 3) Testing workstream

### 3.1 Unit tests (Vitest + msw + @testing-library/react under jsdom)

Location: `ui/src/__tests__/`. Already wired in `ui/vitest.config.ts` + `__tests__/setup.ts`.

| File | Story | Scope |
|---|---|---|
| `__tests__/lib/api/proposals.test.tsx` | 1.1 | 5-hook contract: `useProposals` (status narrowing + wire param), `useProposalForStudy` regression, `useProposal` (refetchInterval off-by-default), `useOpenPR` (POST shape + invalidation), `useRejectProposal` (POST shape + invalidation + 409 fallthrough to global onError) |
| `__tests__/components/proposals/proposal-filter-chips.test.tsx` | 1.2 | Status + source chip onChange semantics; 'all' chip clears |
| `__tests__/components/proposals/cluster-filter-select.test.tsx` | 1.2 | Cluster select onChange; loading state |
| `__tests__/components/proposals/proposals-table.test.tsx` | 2.1 | Row rendering (4 status variants + study-link vs manual); empty state |
| `__tests__/app/proposals/page.test.tsx` | 2.1 | AC-6 filter + pagination; 30s auto-refetch when row is `pr_opened+open` |
| `__tests__/app/proposals/[id]/page.test.tsx` | 3.1, 3.2 | Detail render for 4 status variants; AC-3 30s steady-state poll; AC-4 pr_open_error Alert; AC-5 followup link; `?action=open_pr` auto-trigger guard |
| `__tests__/components/proposals/pr-panel.test.tsx` | 3.2 | Button state machine; 3s post-click cadence; FR-3 hidden-not-disabled when `!pending`; 503/422 toast surface |
| `__tests__/components/proposals/reject-dialog.test.tsx` | 3.3 | AC-2 happy path; spec §11 concurrent-merge 409 → toast + refetch |

**DoD:** all 8 test files green; `cd ui && pnpm test` reports the new count alongside the existing 122.

### 3.2 Integration tests

N/A — feature is frontend-only against existing backend endpoints. Backend integration coverage already shipped in `feat_digest_proposal` PR #41 and `feat_github_pr_worker` PR #45.

### 3.3 Contract tests

N/A — no new endpoints, no new error codes. Existing contract tests in `backend/tests/contract/test_digest_proposal_api_contract.py` and `test_github_pr_worker_api_contract.py` cover the wire surface.

### 3.4 E2E tests

N/A per spec §14 "E2E tests: N/A" and §3 out-of-scope.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `__tests__/components/layout/top-nav.test.tsx` | `/proposals` link assertion | 1 | No change — link already present + tested |
| `__tests__/app/studies/[id]/page.test.tsx` | `useProposalForStudy` mock | 1 | No change — hook preserved byte-for-byte by Story 1.1 |
| `__tests__/components/studies/*` | `<DigestPanel … pendingProposal=…>` | 1 | No change — `ProposalSummary` wire shape unchanged |

### 3.5 Migration verification

N/A — no schema changes.

### 3.6 CI gates

- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm build`
- [ ] `bash scripts/ci/verify_enum_source_of_truth.sh` (no enum changes — should be no-op pass)
- [ ] `make lint && make typecheck && make test-unit && make test-contract` (backend gates — no backend code touched but the CI workflow runs them on every PR)

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — add a "Most recent meaningful changes" entry for `feat_proposals_ui` after merge (filled by `/impl-execute` finalization, not at story time)
- [ ] `architecture.md` — add `/proposals` + `/proposals/[id]` to the `ui/` "Where the code lives" listing
- [ ] `CLAUDE.md` — flip the Feature Status row from "Spec approved, plan pending" → "Complete (PR #N, merged YYYY-MM-DD)"

### 4.1 Architecture docs

- [ ] No new architecture topic doc — `ui-architecture.md` already captures the proposals routes at the planned level

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — mark US-28 + US-29 Implemented

### 4.3 Runbooks

- [ ] `docs/03_runbooks/ui-debugging.md` — append a "Proposals routes" section: polling cadence table, `?action=open_pr` auto-trigger semantics, where to find the hooks, where to find the global error-toast wiring, common-cause investigation table

### 4.4 Security docs

- [ ] No update — proposals UI doesn't introduce new secrets or threat-model entries; uses existing CSRF + XSS mitigations (umbrella spec)

### 4.5 Quality docs

- [ ] No update — testing.md already captures the four-layer convention; this feature is unit-only

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. The hook surface for `lib/api/proposals.ts` is being extended cleanly; no duplication to consolidate. The 9 new components are all single-purpose and used in one place each.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

Preserve `useProposalForStudy` shape (consumed by `feat_studies_ui` study-detail digest panel). TypeScript will catch any breakage at the `studies/[id]/page.tsx:42` call site.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_studies_ui` shell + `<StatusBadge>` + `<MetricDelta>` + `<CursorPaginator>` + `<EmptyState>` + global error-toast wiring + `apiClient` + `ui/src/lib/enums.ts` | All stories | **Shipped (PR #50, 2026-05-12)** | Blocked — cannot start any story |
| `feat_digest_proposal` `GET /api/v1/proposals/{id}` returning inline `study_summary` + `digest` | Story 3.1, 3.2 | **Shipped (PR #41, 2026-05-11)** | UI would need to fan out to `/digests/{id}` separately |
| `feat_github_pr_worker` `POST /api/v1/proposals/{id}/open_pr` + `pr_url`/`pr_state`/`pr_open_error` columns | Story 3.2 | **Shipped (PR #45, 2026-05-12)** | Open-PR button would dispatch into the void |
| `feat_github_webhook` `pr_state` mutator (webhook + polling reconciler) | Story 3.2 (FR-2 30s cadence is meaningful only when the backend mutates state) | **Shipped (PR #56, 2026-05-12)** | UI poll would never see state changes; cosmetic only |

All dependencies satisfied as of 2026-05-12.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pagination unaware of client-side source filter — operator filters to `manual` but page-2 also contains study-sourced rows | M | L | Capture an idea file at `docs/02_product/planned_features/chore_proposals_source_filter_server_side/idea.md` during Story 4.1 (per CLAUDE.md "Tangential discoveries — capture as idea files immediately"). Acceptable for MVP1 (<50 proposals/page realistically). |
| `?action=open_pr` auto-trigger fires twice during React 19 Strict Mode dev rerender | L | L | Guarded by `useRef<boolean>` one-shot flag; the unit test asserts the guard. |
| `useClusters({ limit: 200 })` misses clusters when an operator registers >200 | L | L | Captured as idea: `chore_cluster_filter_full_list`. MVP1 expects <10 clusters per installer. |
| 30s steady-state poll on `/proposals` list page is wasteful when no row is `pr_opened+open` | L | L | The `refetchInterval` function form returns `false` in that case → query goes idle. |
| Polling test flakiness under `vi.useFakeTimers()` + msw + TanStack Query | M | M | Mirror the timer-advance pattern from `__tests__/app/studies/[id]/page.test.tsx` (already proven against the same primitives). |
| GitHub `pr_state` mutates between detail-page load and Reject-confirm submit | M | L (spec §11 covers it) | Story 3.3 DoD asserts the 409 INVALID_STATE_TRANSITION → toast + refetch behavior. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Backend unreachable on list page | API container down | `<EmptyState title="Backend unreachable">` rendered; row table NOT shown | Operator restarts API; React Query auto-refetches on focus |
| `POST /open_pr` returns 503 `GITHUB_NOT_CONFIGURED` | Per-repo PAT missing | Global toast `[GITHUB_NOT_CONFIGURED] …`; button re-enables for retry | Operator populates `./secrets/{auth_ref}` and clicks Open PR again |
| `POST /open_pr` returns 422 `CLUSTER_HAS_NO_CONFIG_REPO` | Cluster not wired to a config_repo | Global toast `[CLUSTER_HAS_NO_CONFIG_REPO] …`; button re-enables | Operator registers a config_repo via the (existing) `POST /config-repos` endpoint |
| `POST /reject` returns 409 INVALID_STATE_TRANSITION | Webhook flipped status to `pr_merged` between page load and confirm | Global toast + `['proposal', id]` invalidate → page refetches → dialog closes naturally on next render | None — already-merged is a terminal state |
| Worker takes >60s to write `pr_open_error` | Network slowness OR worker stuck on a remote git push retry | At 60s, the page's `safetyTimerRef` callback flips `postOpenPrPolling` to false → the 3s cadence stops. The UI continues to show the spinner-replaced button (since openPr.isPending is also false by now AND status is still 'pending'). On the next page focus or 30s steady-state if `pr_state='open'` ever appears, the proposal refetches. | Operator clicks Open PR again to start a fresh 3s+60s window (salted `_job_id` retry key per backend C3-F1 lets the new mutation through Arq dedup) |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (hooks) — every downstream story imports from `lib/api/proposals.ts`
2. **Story 1.2** (filter components) — Epic 2 + 3 consume them
3. **Story 2.1** (list page) — independent of detail page
4. **Story 3.1** (detail page shell) — must precede 3.2 + 3.3 (they modify the same `page.tsx`)
5. **Story 3.2** (PR panel + auto-trigger + polling)
6. **Story 3.3** (reject dialog)
7. **Story 4.1** (docs)

### Parallelization opportunities

- Stories 2.1 and 3.1 can run in parallel after 1.2 lands (different files, no overlap).
- Stories 3.2 and 3.3 both modify `[id]/page.tsx` — serialize them.

---

## 8) Rollout and cutover plan

- **Feature flags:** none.
- **Migration/backfill:** none.
- **Rollout stages:** internal-only (single-tenant MVP1, no remote staging) — PR merge to `main` is the only ship.
- **Operational readiness gates:** AC-1 succeeds end-to-end against a real test repo (manual smoke per Story 3.2 DoD).

---

## 9) Execution tracker (copy/paste section)

### Current sprint (post `feat_github_webhook`)

- [ ] Story 1.1 — Extend `lib/api/proposals.ts`
- [ ] Story 1.2 — Filter chip components
- [ ] Story 2.1 — `/proposals` list page + ProposalsTable
- [ ] Story 3.1 — `/proposals/[id]` detail page shell
- [ ] Story 3.2 — PR panel + auto-trigger + polling
- [ ] Story 3.3 — Reject dialog
- [ ] Story 4.1 — Docs sweep

### Blocked items

None.

### Done this sprint

(populated by `/impl-execute`)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Each story must show:

- [ ] Files created/modified match the `New files` / `Modified files` tables
- [ ] `cd ui && pnpm lint` clean
- [ ] `cd ui && pnpm typecheck` clean
- [ ] `cd ui && pnpm test <touched-files>` green
- [ ] (Final story only) `cd ui && pnpm build` succeeds
- [ ] (Final story only) `bash scripts/ci/verify_enum_source_of_truth.sh` succeeds (no enum changes; should be a no-op pass)
- [ ] No backend code touched (this is a frontend-only feature; `git diff --stat backend/` must show 0 changes)

---

## 11) Plan consistency review

| Check | Result |
|---|---|
| **Spec ↔ plan endpoint count** | Spec §8 has no new endpoints (consumes existing). Plan lists 5 consumed endpoints (`GET /proposals`, `GET /proposals/{id}`, `POST /proposals/{id}/open_pr`, `POST /proposals/{id}/reject`, `GET /clusters` via `useClusters`). ✓ |
| **Spec ↔ plan error code coverage** | Spec §11 + FR-3 + FR-4 enumerate `GITHUB_NOT_CONFIGURED`, `CLUSTER_HAS_NO_CONFIG_REPO`, `QUEUE_UNAVAILABLE`, `INVALID_STATE_TRANSITION`, `PROPOSAL_NOT_FOUND`. Plan covers all 5 in Story 3.2 onError contract assertions (against `ApiError.errorCode` per GPT-5.5 B6) + Story 3.3 + Story 3.1 EmptyState branches. `DIGEST_NOT_READY` is NOT in scope for this feature — the standalone `GET /studies/{id}/digest` endpoint is consumed only by `feat_studies_ui`'s `useStudyDigest` hook; this feature consumes the inline `digest` field on `GET /proposals/{id}` (which never returns `DIGEST_NOT_READY`). ✓ |
| **Spec ↔ plan FR coverage** | All 6 FRs mapped to stories in §1. ✓ |
| **Story internal consistency** | Each story has Outcome / New files / Modified files / Endpoints / Key interfaces / Tasks / DoD. **No file is created by multiple stories** (each New file appears once). **`ui/src/app/proposals/[id]/page.tsx` IS modified by Stories 3.1 → 3.2 → 3.3 in sequence** — this is intentional (the detail page is incrementally assembled section by section). The §7 Suggested sequence pins the serialization; the Story 3.2 + Story 3.3 Modified-files rows are explicit about what each story adds. **`ui/src/lib/api/proposals.ts` is modified only by Story 1.1** — the earlier-draft conflict where Story 2.1 also extended the hook signature has been resolved (the `useProposals(filter, options?)` extension now lands in Story 1.1 per GPT-5.5 review A2). ✓ |
| **Test file count and assignment** | 8 test files, each assigned to exactly one story's DoD (Story 1.1 → 1, 1.2 → 2, 2.1 → 3, 3.1+3.2 → 1 shared, 3.2 → 1, 3.3 → 1). ✓ |
| **Gate arithmetic** | No epic-level "all N endpoints live" gates because no new endpoints. Phase gates are per-story DoD only. ✓ |
| **Open questions resolved** | Spec §19 lists "None — all resolved". Plan does not introduce new open questions. ✓ |
| **UI Guidance completeness** | Insertion points ✓ / Analogous markup (7 patterns) ✓ / Layout ✓ / Confirmation dialog ✓ / Visual consistency table ✓ / Component composition ✓ / Interaction behavior table ✓ / Handler function patterns ✓ / IA placement ✓ / Tooltips N/A (spec doesn't enumerate) ✓ / Legacy parity N/A (greenfield + 52-LOC hook extension) ✓ / Client-side persistence N/A ✓ |
| **Enumerated value contract audit** | Spec §7.4 cites `backend/app/api/v1/schemas.py ProposalStatusWire` (verified line 659) and `ProposalPrStateWire` (verified line 666). `ui/src/lib/enums.ts:101` (`PROPOSAL_STATUS_VALUES`) + `:105` (`PROPOSAL_PR_STATE_VALUES`) already carry the source-of-truth comments shipped by `feat_studies_ui` Story 1.3 + 4.2. Plan does NOT add a parallel option list. ✓ |
| **Audit-event coverage** | MVP1 (no `audit_log` table). N/A per CLAUDE.md "Activates at MVP2". ✓ |
| **Admin/ceiling enforcement** | MVP1 single-tenant; no admin model. N/A per CLAUDE.md "Activates at MVP4". ✓ |
| **Frontend data plumbing** | `<PrPanel>` receives `proposal` + `openPr` mutation instance via props from `[id]/page.tsx` — the page has both. `<RejectDialog>` receives `proposal`. `<ProposalsTable>` receives `rows`. All props verified against the page's accessible data. ✓ |
| **Infrastructure paths** | New files under `ui/src/app/proposals/`, `ui/src/components/proposals/`, `ui/src/__tests__/<mirror>` — all match Next 16 App Router conventions verified in the existing `studies/` layout. No backend paths. ✓ |
| **Persistence scope** | No localStorage / sessionStorage usage. ✓ |

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories + tests (§1)
- [x] Every story has New files / Modified files / Endpoints / Key interfaces / Tasks / DoD
- [x] Testing scope explicit (unit-only; integration/contract/E2E N/A explained)
- [x] Documentation updates planned (Story 4.1 + `/impl-execute` finalization for state/architecture/CLAUDE)
- [x] Lean refactor scope = none (justified)
- [x] Epic gates measurable per-story
- [x] Story-by-Story Verification Gate present (§10)
- [x] Plan consistency review with no unresolved findings (§11)

Plan is **Ready for Execution** pending GPT-5.5 cross-model review.
