# Feature Specification — Shared `<DataTable>` primitive

**Date:** 2026-05-15
**Status:** Draft
**Owners:** Product: Eric Starr · Engineering: Eric Starr
**Related docs:**
- [idea.md](./idea.md) — origin brief (preflighted 2026-05-15)
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — frontend stack + URL-state pattern this spec extends
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — cursor pagination + `X-Total-Count` contract this spec extends with `?q=`
- [`feat_contextual_help` Phase 1](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/) — `InfoTooltip` / `HelpPopover` / `glossary.ts` reused for column-header help
- [`feat_contextual_help` Phases 2+3](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help_mvp2/) — enum-grounded glossary discipline this spec extends to filter chips

---

## 1) Purpose

- **Problem.** 8 standalone list-shaped tables across the UI have sharply inconsistent affordances: only `trials-table.tsx` is sortable (and via a `<Select>`, not column-header clicks), three tables have filter chips, **zero** tables support text search, two pages URL-back their filters, the rest are React-state-only, and empty-state copy varies. Backend `?cursor` + `?limit` + `X-Total-Count` contract is already uniform per [`api-conventions.md`](../../../01_architecture/api-conventions.md) but the frontend doesn't expose `X-Total-Count` to most users. No project doc codifies "all tables must …" so each new screen ships another bespoke pattern.
- **Outcome.** A single `<DataTable>` primitive at [`ui/src/components/common/data-table.tsx`](../../../../ui/src/components/common/data-table.tsx) + co-located helpers + a `?q=` Postgres-FTS contract on 6 list endpoints. The 8 standalone tables migrate to the primitive in the same PR. Every list surface ships with sortable column headers, debounced text search (where supported), enum-grounded filter chips, total-count display, URL-backed state, sticky header, density toggle, column visibility, multi-row selection, and keyboard navigation. The 9th table (`studies-by-cluster-table.tsx`) inherits via its thin wrapping of `studies-table`.
- **Non-goal.** This spec **does not** add server-side bulk-action endpoints (the primitive surfaces `selectedIds` + `clearSelection` to consumers; if a consumer wants to wire `POST /studies/bulk-cancel`, that endpoint ships in a separate feature). It also **does not** introduce row virtualization (deferred — current page sizes are ≤200 and TanStack Table virtualization is a future opt-in), persisted-server-side column ordering, drag-resize columns, expandable row groups, or in-table inline editing. The `proposals` table gets **no FTS** (see §3 "Out of scope").

## 2) Current state audit

### Existing implementations

Every table the primitive touches, with the affordances each one ships today:

| Table file | Filter chips (today) | Sortable | Text search | Pagination | URL-backed |
|---|---|---|---|---|---|
| [`ui/src/components/studies/studies-table.tsx`](../../../../ui/src/components/studies/studies-table.tsx) | `?status` (via parent page) | ❌ | ❌ | Cursor (parent page) | Yes (`?status`) |
| [`ui/src/components/proposals/proposals-table.tsx`](../../../../ui/src/components/proposals/proposals-table.tsx) | `?status` + `?source` + `?cluster_id` (via parent page) | ❌ | ❌ | Cursor (parent page) | Yes (`?status`, `?source`, `?cluster_id`) |
| [`ui/src/components/judgments/judgments-table.tsx`](../../../../ui/src/components/judgments/judgments-table.tsx) | `source` chip (React state in parent) | ❌ | ❌ | Cursor (parent page, React state) | No |
| [`ui/src/components/studies/trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) | ❌ | ✅ 5 keys via `<Select>` | ❌ | Cursor (parent page) | Partial (sort key in React state only) |
| [`ui/src/components/query-sets/queries-table.tsx`](../../../../ui/src/components/query-sets/queries-table.tsx) | `?since` only (sub-resource) | ❌ | ❌ | Cursor (internal stack) | Partial |
| [`ui/src/components/clusters/clusters-table.tsx`](../../../../ui/src/components/clusters/clusters-table.tsx) | ❌ | ❌ | ❌ | None | — |
| [`ui/src/components/query-sets/query-sets-table.tsx`](../../../../ui/src/components/query-sets/query-sets-table.tsx) | ❌ | ❌ | ❌ | None | — |
| [`ui/src/components/templates/templates-table.tsx`](../../../../ui/src/components/templates/templates-table.tsx) | ❌ | ❌ | ❌ | None | — |
| [`ui/src/components/clusters/studies-by-cluster-table.tsx`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx) | Inherits from `studies-table` | Inherits | Inherits | Cursor | Inherits |

Reusable primitives that already exist and the DataTable will compose with:

- [`ui/src/components/common/cursor-paginator.tsx`](../../../../ui/src/components/common/cursor-paginator.tsx) — Prev/Next/page-size selector + total-count display; DataTable wraps it so consumers don't import it directly.
- [`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx) + [`help-popover.tsx`](../../../../ui/src/components/common/help-popover.tsx) — Phase-1 contextual-help wrappers reused on column headers and toolbar surfaces.
- [`ui/src/components/common/empty-state.tsx`](../../../../ui/src/components/common/empty-state.tsx) — title + message pattern the two new empty-state shapes consume.
- [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) — canonical source-of-truth allowlists; filter chips and sort keys must trace back here.
- [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) — tooltip copy reused on column headers.

Backend list endpoints (verified to match the contract in §1):

| Endpoint | Accepts today | New `?q=` adds | Notes |
|---|---|---|---|
| `GET /api/v1/clusters` | `?cursor`, `?limit`, `?since` | `?q` (≥2 chars) | `name + base_url` FTS |
| `GET /api/v1/studies` | `?cursor`, `?limit`, `?since`, `?status`, `?cluster_id` | `?q` (≥2 chars) | `name + target` FTS |
| `GET /api/v1/query-sets` | `?cursor`, `?limit`, `?since` | `?q` (≥2 chars) | `name` FTS |
| `GET /api/v1/query-templates` | `?cursor`, `?limit`, `?since` | `?q` (≥2 chars) | `name` FTS |
| `GET /api/v1/judgment-lists` | `?cursor`, `?limit` | `?q` (≥2 chars), `?since` (new — closes pre-existing api-conventions.md drift) | `name + target` FTS |
| `GET /api/v1/conversations` | `?cursor`, `?limit` | `?q` (≥2 chars), `?since` (new — closes pre-existing drift) | `coalesce(title, '')` FTS |
| `GET /api/v1/proposals` | `?cursor`, `?limit`, `?status`, `?cluster_id`, `?source` | `?template_id` (filter chip — not FTS) | No FTS — see §3 "Out of scope" |
| `GET /api/v1/query-sets/{set_id}/queries` | `?cursor`, `?limit`, `?since` (UUIDv7 lower bound) | None (queries are a sub-resource — preserves existing affordances) | Out of FTS scope |
| `GET /api/v1/studies/{study_id}/trials` | `?cursor`, `?limit`, `?since`, `?sort` | None (sort is column-header-driven via DataTable; existing `?sort` enum is preserved as the wire contract) | Sort kept; `<Select>` removed |

### Navigation and link impact

No URL renames. Existing `?status=`, `?source=`, `?cluster_id=` URL parameters on the studies and proposals pages remain wire-identical — the migration adds the additional `?q=`, `?sort=`, `?<other-filter>=` shapes without breaking any in-flight bookmarks. The `/studies/[id]?sort=primary_metric_desc` shape (already in `ui/src/lib/enums.ts` `TRIAL_SORT_VALUES`) graduates from "React state only" to URL-backed.

| Source file | Current link / param | New link / param |
|---|---|---|
| `ui/src/app/studies/page.tsx:38` | `/studies?status=<v>` | `/studies?status=<v>&sort=<col>:<dir>&q=<text>` (additive — existing shape preserved) |
| `ui/src/app/proposals/page.tsx:71` | `/proposals?status=<v>&source=<v>&cluster_id=<v>` | `/proposals?status=<v>&source=<v>&cluster_id=<v>&template_id=<v>&sort=<col>:<dir>` (additive) |
| `ui/src/app/studies/[id]/page.tsx` | `/studies/<id>` (sort in React state, existing combined wire shape) | `/studies/<id>?sort=<combined-wire-value>` e.g. `?sort=primary_metric_desc` (additive — existing trials combined wire shape preserved both in the URL and in the backend; sort now bookmarkable) |
| `ui/src/app/judgments/[id]/page.tsx` | `/judgments/<id>` (source filter + cursor in React state) | `/judgments/<id>?source=<v>&sort=<col>:<dir>` (additive — **no `?q=` on this route**; per-judgment FTS is out of scope per §3 and judgments-table is `searchable={false}`) |
| `ui/src/app/clusters/page.tsx` | bare path | `?sort=<col>:<dir>&q=<text>&engine_type=<v>&environment=<v>` becomes available (additive) |
| `ui/src/app/templates/page.tsx` | bare path | `?sort=<col>:<dir>&q=<text>&engine_type=<v>` becomes available (additive) |
| `ui/src/app/query-sets/page.tsx` | bare path | `?sort=<col>:<dir>&q=<text>` becomes available (additive) |

### Existing test impact

Vitest 285 tests / Playwright 8 specs (per `state.md` 2026-05-15). Tests that reference the 8 migrated tables will need updates — the testids stay (e.g., `data-testid="studies-table"`) but the wrapping DOM gains a toolbar (`data-testid="data-table-toolbar"`), search input (`data-testid="data-table-search"`), and column-visibility menu (`data-testid="data-table-column-visibility"`).

| Test file | Pattern | Required change |
|---|---|---|
| `ui/src/__tests__/components/studies/studies-table.test.tsx` (if exists) and `ui/src/__tests__/app/studies/page.test.tsx` | Asserts on `studies-table` testid + status chips | Continue asserting on `studies-table` (preserved); add assertions on toolbar elements |
| `ui/src/__tests__/components/proposals/proposals-table.test.tsx` + `app/proposals/page.test.tsx` | Status/source chip assertions | Preserved; new chip per `template_id` filter |
| `ui/src/__tests__/components/judgments/judgments-table.test.tsx` + `app/judgments/[id]/page.test.tsx` | Source-filter testids | Preserved; URL-backing added |
| `ui/src/__tests__/components/studies/trials-table.test.tsx` | `trial-sort` `<Select>` | **Behavior change** — replace `<Select>` assertions with column-header click assertions |
| `ui/tests/e2e/studies.spec.ts`, `proposals.spec.ts`, `judgments.spec.ts`, `templates.spec.ts`, `clusters_register.spec.ts`, `query_sets_create.spec.ts`, `query_set_detail.spec.ts`, `chat.spec.ts` | Page-level Playwright assertions on existing testids | Preserve all existing testids on the rows; add 1 new E2E spec per migrated table that exercises the new toolbar (sort, search, total count) |

### Existing behaviors affected by scope change

- **`trials-table` sort UI.** Current: `<Select>` above the table. New: column-header clicks cycle asc → desc → unsorted. The `?sort=` URL parameter wire value (`primary_metric_desc`, etc.) is **preserved** — the `<Select>` goes away but the URL shape and the backend wire contract don't change. **Decision needed: no.**
- **`judgments-table` source filter.** Current: React-state-only (clears on page navigation). New: URL-backed (`?source=`). **Decision needed: no** — this matches the locked URL-state encoding (§3 Locked decisions).
- **Empty-state copy across all migrated tables.** Current: each table has its own copy ("No studies match the current filters", "No clusters registered. Click 'Register cluster' to add one"). New: each table consumes the primitive's two empty-state slots (`<EmptyState kind="no-rows-match">` vs `<EmptyState kind="no-rows-exist">`) — the consumer supplies the copy + optional primary CTA. Existing copy is preserved on a per-table basis (no global string change). **Decision needed: no.**
- **Page-size defaults.** Current: each parent page sets its own default (`useState(50)` on `/studies`, `useState(25)` on `/clusters/[id]`, etc.). New: DataTable accepts `defaultPageSize` prop; existing defaults preserved. **Decision needed: no.**

---

## 3) Scope

### In scope (single PR per Locked Decision #4 — the 18 items below)

1. New `<DataTable>` primitive + co-located helpers (`DataTableToolbar`, `DataTableEmpty`, `DataTableColumnVisibility`, `DataTableBulkActions`, `useDataTableUrlState` hook) at `ui/src/components/common/data-table*.tsx` and `ui/src/hooks/use-data-table-url-state.ts`.
2. New npm dependency `@tanstack/react-table@~8.21.3` (tilde-pinned to the latest stable 8.x; matches the pinning style of `@tanstack/react-query@~5.62.16`).
3. **Sortable column headers** — click cycles `asc → desc → unsorted`; chevron-up/down/none affordance; URL `?sort=<col>:<asc|desc>`; backend wire value unchanged per resource.
4. **Filter chips backed by backend enums** — `filter: { kind: 'enum', wireValues: <SOURCE_OF_TRUTH_ARRAY>, sourceOfTruth: 'backend/...py <Symbol>' }` column-config field. Source-of-truth comment is mandatory; lint guard extends the existing `enums.ts` discipline.
5. **Debounced text search via Postgres FTS** — 300ms debounce; sends `?q=<text>` to the backend on the 6 searchable resources; backend converts to `plainto_tsquery('english', :q)` and orders by `ts_rank` desc. Both ends enforce `min_length=2`.
6. **Total-count display** — top-right of toolbar reads `X-Total-Count` from the response headers; renders "Showing 1–50 of 312" with the current page-window count.
7. **URL-backed state** — `sort`, filters, `q`, `cursor` serialize to query params using the canonical encoding (Locked Decision #5). Back button works; refresh preserves view; links are shareable.
8. **Two empty-state shapes** — `kind="no-rows-match"` (with `[Clear filters]` action) vs `kind="no-rows-exist"` (with consumer-supplied primary CTA).
9. **Cursor-pagination controls** — DataTable wraps the existing [`CursorPaginator`](../../../../ui/src/components/common/cursor-paginator.tsx); consumers don't import it directly.
10. **Sticky header on scroll** — `position: sticky; top: 0` Tailwind utility on the header row.
11. **Tooltip-enabled column headers** — opt-in `tooltipKey: GlossaryKey` field on the column config; reuses `InfoTooltip` + `glossary.ts`.
12. **Multi-row selection + bulk-action toolbar** — checkbox column + "select all on page" header checkbox; bulk-action toolbar lights up when `selectedIds.length >= 1`; selection is React-only (never URL-encoded); selection clears when the cursor moves to another page; counter renders "N selected on this page".
13. **Column visibility menu** — eye-icon dropdown; persists hidden-column set to `localStorage` keyed by table id; sticky columns (selection checkbox + first identifier column) are not hideable.
14. **Density toggle (`comfortable` / `compact`)** — two-position toggle in toolbar; persists to `localStorage` keyed by table id.
15. **Keyboard navigation** — Arrow up/down move row focus; Enter calls consumer-supplied `onRowActivate`; Space toggles row selection when selection is enabled; opt out via `keyboardNav={false}`.
16. **6 Alembic migrations** (`0008_search_vector_clusters` through `0013_search_vector_conversations`) — each adds a `search_vector` generated `tsvector` column + GIN index on its respective table. Round-trip clean per CLAUDE.md Absolute Rule #5.
17. **Backend query-parameter additions** across the affected list endpoints:
    - `?q=` (FTS, ≥2 chars) on the 6 searchable list endpoints (clusters, studies, query-sets, query-templates, judgment-lists, conversations).
    - `?since=` (ISO 8601 `created_at` lower bound) on judgment-lists and conversations (closes pre-existing api-conventions.md drift).
    - `?sort=<col>:<asc|desc>` on clusters, studies, query-sets, query-templates, judgment-lists, proposals, **and `/api/v1/judgment-lists/{judgment_list_id}/judgments`** (per-list judgment rows — sort by `created_at`, `rating`, `source`). Trials retains its existing combined-wire-value `?sort=` shape.
    - `?engine_type=` and `?environment=` on `GET /api/v1/clusters` (new enum-filter params backing the cluster DataTable's chips).
    - `?engine_type=` on `GET /api/v1/query-templates` (new enum-filter param).
    - `?template_id=<uuid>` on `GET /api/v1/proposals` (new FK-filter param replacing FTS for that resource).
18. **All 8 standalone table components migrate to the primitive** in the same PR; the 9th (`studies-by-cluster-table.tsx`) inherits via its existing thin-wrap pattern.

### Out of scope

- **FTS on `proposals`, `trials`, `queries`, or `judgments`.** Proposals has no natural text column (FK-only). Trials are sequence-numbered within a single study — search is redundant. Queries (sub-resource) and individual judgments (sub-resource) are not surfaced as their own list pages; their parent containers (`/query-sets/{id}` and `/judgments/{id}`) are the searchable surface, and the parent FTS covers the use case.
- **Server-side bulk-action endpoints** (e.g., `POST /studies/bulk-cancel`). The primitive exposes `selectedIds` + `clearSelection` for the consumer to wire to whatever endpoint they have. None of the migrated tables introduces a new bulk endpoint in this PR.
- **Row virtualization.** Current page sizes (≤200) don't warrant the complexity. Future opt-in via `virtual={true}` prop (not designed in this spec).
- **Column resizing, column drag-reorder, expandable rows, in-cell inline editing.** All deferred — no consumer needs them today.
- **Audit-event emission.** N/A — DataTable is read-only UI. Bulk-action consumers, when they exist, handle their own audit emission when MVP2 ships `audit_log`.
- **Visual regression / screenshot testing.** Deferred to a future infra feature; component + E2E coverage is sufficient for this PR.

### API convention check

- **Endpoint prefix:** `/api/v1/<resource>` per [api-conventions.md](../../../01_architecture/api-conventions.md). All affected endpoints already use this prefix; no new routers introduced.
- **Router files:** existing — `backend/app/api/v1/{clusters,studies,query_sets,query_templates,judgments,conversations,proposals}.py`. The new `?q=`, `?since`, and `?template_id=` params are additions to existing router functions, not new endpoints.
- **HTTP methods:** all affected endpoints are `GET`. No mutations.
- **Error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per api-conventions.md. The `?q=` param uses `Field(min_length=2)` so under-length queries surface as the standard `VALIDATION_ERROR` (HTTP 422). No new feature-specific error codes required.
- **Auth:** N/A — MVP1 has no auth surface.

### Phase boundaries

**Single-phase delivery** per Locked Decision #4 (idea.md line 41). The primitive, 6 Alembic migrations, 6 backend FTS endpoints, `?template_id=` filter on proposals, and 8 table-component migrations all land in **one PR**.

Rationale: the operator directive (2026-05-15) is to maximize capability. A phased approach (e.g., "primitive ships first, table migrations follow") would create a partial state where some tables have the new affordances and others don't — confusing for users and worse for review than landing the whole pattern at once. The implementation plan will enforce tight commit boundaries inside the single PR so reviewers can navigate (one commit per primitive sub-component, one per Alembic migration, one per migrated table).

No deferred phases. No `phase2_idea.md` to create.

## 4) Product principles and constraints

- **Consumer-supplied data.** DataTable is a presentation primitive. The consumer provides a TanStack Query hook that takes `{ cursor, limit, sort, filters, q }` and returns `{ data, totalCount, has_more, next_cursor }`. DataTable contributes chrome (sortable headers, filter chips, search input, toolbar, paginator, density toggle, column visibility) and never owns server state.
- **Source-of-truth grounding.** Every filter-chip option list and every sort key cites a backend allowlist file via the column config's `sourceOfTruth: string` field. Lint guard rejects column configs that name `wireValues` without `sourceOfTruth`.
- **URL is the contract for shareability.** `sort`, filters, `q`, and `cursor` always serialize to query params. Back-button + refresh + link-sharing all work.
- **Selection is ephemeral.** Selection state lives in React only; never URL-encoded. Selection clears on cursor movement (page change).
- **`min_length=2` on text search both ends.** Frontend Zod schema rejects shorter strings client-side; backend Pydantic `Field(min_length=2)` rejects shorter strings as `VALIDATION_ERROR`. Below 2 characters, every page-load would trigger a full-table-scan with no value.
- **All Alembic migrations include `downgrade()` and round-trip clean** per CLAUDE.md Absolute Rule #5.
- **No engine-specific code outside adapters.** N/A — DataTable is backend-engine-agnostic; FTS is Postgres-only (the system DB), not Elasticsearch.
- **`/healthz` is unaffected.** No new subsystem probes; no new boot-time checks.

### Anti-patterns

- **Do not** make DataTable own server state (e.g., DataTable internally calls `useQuery`). The primitive cannot share state with siblings if it owns the cache key; the consumer must own the hook. Pattern: consumer instantiates `useStudies(filter)`, passes `query.data`, `query.isPending`, `query.totalCount` to DataTable as props.
- **Do not** encode selection state to URL. Selection like "rows {A, B, C} selected" is stale the moment a row is added/deleted. Selection lives in `useState<Set<string>>` inside the primitive.
- **Do not** send `?q=` with fewer than 2 characters. Frontend AND backend reject; the debounce must wait for ≥2 chars before fetching. Below 2 chars produces a wasteful full-table-scan on the backend with no useful ranking signal.
- **Do not** invent filter-chip wire values from memory or guess. Every option list must be `as const`-typed from an enum array in `ui/src/lib/enums.ts`, which itself carries the `// Values must match backend/...py <Symbol>` comment. Lint guard scans column-config files for `wireValues:` arrays that don't reference an exported `enums.ts` symbol.
- **Do not** populate `search_vector` columns with anything other than the Postgres `GENERATED ALWAYS AS (...) STORED` clause. The values are derived from the source columns; manual updates would drift. Manual `INSERT … RETURNING search_vector` is not supported on generated columns and would fail.
- **Do not** add row-level FTS on `judgments`, `trials`, or `queries` (sub-resource lists). Parent FTS (`judgment_lists`, `studies`, `query_sets`) covers the search use case; per-row FTS would multiply migration surface for no operator value.
- **Do not** rename existing `?sort=`, `?status=`, `?source=`, `?cluster_id=` URL wire shapes. Existing bookmarks must keep working. The new URL shape is purely additive.

## 5) Assumptions and dependencies

- **Dependency: `feat_contextual_help` Phase 1 (PR #122, merged 2026-05-15).** Provides `InfoTooltip`, `HelpPopover`, and the `glossary.ts` source-of-truth file. **Status:** implemented. **Risk if missing:** column-header tooltips would need to be rebuilt — but the dep is already on main.
- **Dependency: `@tanstack/react-table@~8.21.3` npm package.** New dev dependency. **Status:** planned (this PR). **Risk if missing:** the primitive can't ship — the headless engine is non-trivial to reimplement (sort priority, filter models, virtualization hooks). The version is the latest stable 8.x as of 2026-05-15.
- **Dependency: Postgres 16 + the `pg_trgm` / `unaccent` extensions** (optional — `to_tsvector('english', …)` uses the built-in `english` dictionary; no extensions required). **Status:** Postgres 16 is the MVP1 stack baseline. **Risk if missing:** none for the planned migrations; if a future migration needs unaccent (e.g., accent-insensitive cluster names), a separate migration ships `CREATE EXTENSION IF NOT EXISTS unaccent` and the spec gets patched.
- **Soft dependency: backend `?since=` support on judgment-lists + conversations.** Per [api-conventions.md](../../../01_architecture/api-conventions.md) §"Filtering by recency", every list endpoint MUST accept `?since=`. The judgment-lists and conversations endpoints don't today (pre-existing drift). The DataTable spec closes this drift by adding `?since=` to both endpoints in this PR. **Risk if missing:** the DataTable URL state will request `?since=` and the backend will return 422 VALIDATION_ERROR on an unknown query param (FastAPI/Pydantic strict mode); fix is in-scope.

## 6) Actors and roles

- **Primary actor:** Relevance engineer (any user on the MVP1 install — single-tenant, no auth).
- **Role model:** N/A — single-tenant install, no auth surface (MVP1–MVP3 per [tech-stack.md canonical release matrix](../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. DataTable is read-only UI; bulk-action consumers (if any ship before MVP2) handle their own audit emission when MVP2 ships the table.

## 7) Functional requirements

### FR-1: `?q=` text-search query parameter on 6 list endpoints

- Requirement:
  - The system **MUST** accept a `?q=<text>` query parameter on `GET /api/v1/clusters`, `GET /api/v1/studies`, `GET /api/v1/query-sets`, `GET /api/v1/query-templates`, `GET /api/v1/judgment-lists`, and `GET /api/v1/conversations`.
  - The system **MUST** validate `?q=` via Pydantic `Field(min_length=2, max_length=200)`. Strings shorter than 2 characters or longer than 200 return HTTP 422 with `error_code: "VALIDATION_ERROR"`.
  - The system **MUST** translate non-null `?q=` into a SQL `WHERE` predicate `search_vector @@ plainto_tsquery('english', :q)` while **preserving the existing `created_at DESC, id DESC` ordering**. When `?q=` is absent or null, the same ordering applies. Results are filtered by FTS match but not re-sorted by `ts_rank` — this preserves the integrity of the `(created_at, id)` keyset cursor (see operability note below).
  - The system **MUST** combine `?q=` with all existing filter params via SQL AND. Examples: `GET /api/v1/studies?q=products&status=completed` returns only completed studies whose `search_vector` matches `plainto_tsquery('english', 'products')`.
  - The cursor encoding **MUST** continue to use `(created_at, id)` regardless of `?q=`. Cursor pagination through a `?q=`-filtered result set uses the same keyset predicate as the unfiltered list.
- Notes:
  - **Why not `ts_rank` ordering:** RelyLoop uses keyset cursor pagination (`(created_at, id)` opaque base64). A keyset cursor predicate only paginates correctly when the cursor includes the leading sort key. Re-ordering by `ts_rank` would either (a) require encoding rank into every cursor (custom serialization across 6 endpoints + brittle floating-point key boundaries) or (b) be replaced by offset/limit pagination — which is banned by [api-conventions.md "Anti-patterns"](../../../01_architecture/api-conventions.md). The simpler MVP1 design ships filter-only FTS (match-or-not) with newest-first ordering. Rank-ordered FTS is captured separately for MVP2+ when ClickHouse / a search-side ranking surface lands; the spec calls this out in §16 as a deferred follow-up.
  - Backend implementation reads the param at the router layer, threads it through to the repo layer's `list_*` function as a `q: str | None` keyword argument, and the repo composes the SQL clause via `sa.text("search_vector @@ plainto_tsquery('english', :q)")` (raw text fragment, not ORM column — the generated column is not in the ORM model per FR-2).
  - The repo's `count_*` function takes the same `q: str | None` arg so `X-Total-Count` matches the filtered set.

### FR-2: Six Alembic migrations adding generated `search_vector` columns + GIN indexes

- Requirement:
  - The system **MUST** ship 6 Alembic migrations: `0008_search_vector_clusters`, `0009_search_vector_studies`, `0010_search_vector_query_sets`, `0011_search_vector_query_templates`, `0012_search_vector_judgment_lists`, `0013_search_vector_conversations`.
  - Each migration **MUST** add a `search_vector` column declared `tsvector GENERATED ALWAYS AS (<expression>) STORED`, where `<expression>` is the per-table value below. The `to_tsvector(...)` wrapping is included inside `<expression>`; the migration template does **not** add a second outer wrapper.
  - Each migration **MUST** create a `GIN` index on the `search_vector` column named `<table>_search_vector_idx`.
  - Each migration **MUST** include a `downgrade()` that drops the GIN index THEN the column (FK order). For per-migration verification: `alembic upgrade <revision> && alembic downgrade -1 && alembic upgrade <revision>` MUST round-trip clean. For full-stack verification, `alembic upgrade head && alembic downgrade 0007 && alembic upgrade head` MUST round-trip clean (see AC-7 for the canonical assertion shape — single `downgrade -1` only reverts the *latest* revision and is insufficient to verify all six).
  - Per-table generated-column expressions (each one already includes the outer `to_tsvector('english', …)` wrapping):

    | Table | `<expression>` for `GENERATED ALWAYS AS (<expression>) STORED` |
    |---|---|
    | `clusters` | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(base_url, ''))` |
    | `studies` | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(target, ''))` |
    | `query_sets` | `to_tsvector('english', coalesce(name, ''))` |
    | `query_templates` | `to_tsvector('english', coalesce(name, ''))` |
    | `judgment_lists` | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(target, ''))` |
    | `conversations` | `to_tsvector('english', coalesce(title, ''))` |

- Notes:
  - All migrations are non-breaking — existing list endpoints continue to work without `?q=`.
  - The generated columns are populated automatically by Postgres on INSERT / UPDATE; no backfill required (Postgres recomputes when the source columns change).
  - The SQLAlchemy ORM model **MUST NOT** declare the `search_vector` column. The column is generated and not user-writable; declaring it would force SQLAlchemy to issue UPDATEs against it and fail. Instead, the FTS predicate is constructed via `sa.text("search_vector @@ plainto_tsquery('english', :q)")` in the repo layer.

### FR-3: New `?template_id=` filter on `GET /api/v1/proposals`

- Requirement:
  - The system **MUST** accept an optional `?template_id=<uuid>` query parameter on `GET /api/v1/proposals`.
  - The system **MUST** filter proposals via SQL AND on the existing `proposals.template_id` foreign-key column.
  - Invalid UUID values **MUST** return HTTP 422 with `error_code: "VALIDATION_ERROR"`.
  - The `count_proposals` repo function **MUST** accept the same `template_id` keyword argument so `X-Total-Count` matches the filtered set.
- Notes:
  - Adds 2 lines in `backend/app/api/v1/proposals.py` (query parameter + thread to repo) and ~5 lines in `backend/app/db/repo/proposal.py`.
  - This replaces the FTS deferral on proposals (proposals have no natural text column; FK filtering is the equivalent affordance).

### FR-3a: New backend `?sort=`, `?engine_type=`, `?environment=` filter parameters on list endpoints

- Requirement:
  - The system **MUST** add `?sort=<col>:<asc|desc>` typed as a Pydantic `Literal[...]` per endpoint, with allowed values listed in §8.4. Unknown values return HTTP 422 with `error_code: "VALIDATION_ERROR"`. The endpoints that gain `?sort=` are:
    - `/api/v1/clusters`, `/api/v1/studies`, `/api/v1/query-sets`, `/api/v1/query-templates`, `/api/v1/judgment-lists`, `/api/v1/proposals` (top-level list endpoints).
    - `/api/v1/judgment-lists/{judgment_list_id}/judgments` (per-list judgment rows — sort by `created_at`, `rating`, `source`).
    - Trials (`/api/v1/studies/{id}/trials`) retains its existing combined-wire `?sort=` Literal — no change.
  - The system **MUST** add `?engine_type=<engine>` (Literal `elasticsearch | opensearch`) on `/api/v1/clusters` and `/api/v1/query-templates`. The filter is applied via SQL AND on the existing `engine_type` column.
  - The system **MUST** add `?environment=<env>` (Literal `prod | staging | dev`) on `/api/v1/clusters`. The filter is applied via SQL AND on the existing `environment` column.
  - **Cursor-pagination correctness under `?sort=`:** the cursor encoding **MUST** be sort-aware. When `?sort=` is absent (or `?sort=created_at:desc` — the default ordering), the cursor preserves the legacy `(created_at, id)` shape. When `?sort=` is any other value, the cursor becomes `(sort_column_value, id)` so the keyset predicate matches the `ORDER BY` exactly. Pattern precedent: the existing trials endpoint already does this via `_decode_trial_cursor(cursor, sort)` at [`backend/app/api/v1/studies.py:402`](../../../../backend/app/api/v1/studies.py); the 7 new sortable endpoints follow the same shape. The opaque cursor wire shape stays base64-JSON; only the payload differs by sort. Repo-layer keyset predicates **MUST** apply explicit null-ordering (`NULLS LAST` on `DESC`, `NULLS FIRST` on `ASC`) to keep ties deterministic.
  - Each new parameter **MUST** be threaded to the matching `count_<resource>` repo function so `X-Total-Count` matches the filtered set.
  - Each `?sort=` Literal **MUST** be added to `backend/app/api/v1/schemas.py` as a typed symbol (e.g., `StudySortKey`, `ClusterSortKey`, etc.) and mirrored in `ui/src/lib/enums.ts` with the canonical `// Values must match …` source-of-truth comment (per the existing Story 4.2 grep gate at `scripts/ci/verify_enum_source_of_truth.sh`).
- Notes:
  - The repo-layer sort handler **MUST NOT** use a Python f-string or `.format()` to compose the `ORDER BY` clause — that would be a SQL-injection vector if the Literal is ever bypassed. Use a small `match/case` block or a `dict[SortKey, sa.ColumnElement]` lookup that returns SQLAlchemy column references; the secondary tie-breaker is always `id DESC`.
  - The new `?sort=` values for resources whose existing repo already has a default `created_at DESC` ordering preserve that ordering when `?sort=` is absent.
  - **Why sort-aware cursors matter:** without this, `?sort=name:asc&cursor=<old (created_at, id) cursor>` would skip or duplicate rows because the cursor predicate doesn't match the `ORDER BY` leading key. This is the same class of bug as `ts_rank` ordering (avoided in FR-1 by not re-ordering on rank); for `?sort=` we accept the cost of custom cursor codecs because operator-facing sort is high-value.

### FR-4: `<DataTable>` primitive — sortable column headers

- Requirement:
  - The primitive **MUST** render a clickable column header for each column where `column.sortable === true`.
  - Clicking a sortable header **MUST** cycle the column's sort state: `unsorted → <firstClickDirection> → <opposite> → unsorted`. The cycle's first direction defaults to `asc`, but each column **MAY** override via `column.firstClickDirection: 'asc' | 'desc'`. For metric-shaped columns (e.g., `trials.primary_metric`, `studies.best_metric`) the column config **SHOULD** set `firstClickDirection: 'desc'` so the first click surfaces the best rows.
  - Clicking a different sortable header **MUST** clear any other column's sort state (single-column sort priority — multi-column sort is out of scope for MVP1).
  - The primitive **MUST** render a chevron-up icon for `asc`, chevron-down for `desc`, and no icon (or a muted up-down icon) for `unsorted`.
  - The primitive **MUST** serialize the sort state to the URL using an **encoder supplied by the consumer's column-config** (omitted when unsorted). Two encoder shapes are supported:
    - **Default `<col>:<dir>` encoder** — used by clusters, studies, query-sets, query-templates, judgment-lists, proposals. The URL form `?sort=name:asc` is identical to the backend wire form (`?sort=name:asc` typed as `Literal["name:asc", "name:desc", "created_at:asc", "created_at:desc", ...]`).
    - **Trials combined-wire encoder** — used by `trials-table.column-config.ts` only. Maps the internal `(col='primary_metric', dir='desc')` representation to the existing combined wire value `primary_metric_desc`. Both the URL form AND the backend `?sort=` wire value are `primary_metric_desc`. The URL is **never** `primary_metric:desc` — that shape is the column-config's internal representation, never serialized to the URL.
  - All other DataTable consumers use the default encoder; only `trials-table.column-config.ts` overrides.
  - The primitive **MUST** support `column.sortable === false` (header not clickable; no chevron).
  - On initial load with `?sort=<key>:<dir>` in the URL, the primitive **MUST** apply that sort to the matching column.
- Notes:
  - TanStack Table's `getSortedRowModel()` and `state.sorting` handle the cycling logic; this FR is about wiring `?sort=` to/from that state via `useDataTableUrlState` and respecting `firstClickDirection`.

### FR-5: `<DataTable>` primitive — filter chips backed by backend enums

- Requirement:
  - The primitive **MUST** accept `column.filter` of either kind below:
    - `{ kind: 'enum', wireValues: readonly string[], sourceOfTruth: string, label?: (v: string) => string }` — for short, fixed allowlists (e.g., status, source, engine_type, environment). Rendered as a chip row in the toolbar with one chip per `wireValue` plus an "all" chip.
    - `{ kind: 'fk-select', useOptions: () => { data: { id: string; label: string }[]; isLoading: boolean }, sourceOfTruth: string }` — for foreign-key filters where the allowed values are loaded asynchronously (e.g., `cluster_id`, `template_id`). Rendered as a `<select>` dropdown in the toolbar with `"All <label>"` as the default option. Generalizes the existing pattern in [`ui/src/components/proposals/cluster-filter-select.tsx`](../../../../ui/src/components/proposals/cluster-filter-select.tsx).
  - Clicking a chip or selecting a dropdown option **MUST** set the URL to `?<column.id>=<wireValue>` (or remove the param when "all" is selected).
  - The primitive **MUST** render the chips disabled (visually muted, not clickable) while the underlying query is loading the next page; `fk-select` shows `"(loading…)"` while `useOptions().isLoading === true`.
  - The `sourceOfTruth: string` field is documentation — it appears in a JSDoc comment above the column config and is asserted by the lint guard in FR-17. The primitive itself does not validate it at runtime.
- Notes:
  - This FR generalizes the existing patterns in [`study-status-filter-chips.tsx`](../../../../ui/src/components/studies/study-status-filter-chips.tsx), [`proposal-status-filter-chips.tsx`](../../../../ui/src/components/proposals/proposal-status-filter-chips.tsx), [`proposal-source-filter-chips.tsx`](../../../../ui/src/components/proposals/proposal-source-filter-chips.tsx), and [`cluster-filter-select.tsx`](../../../../ui/src/components/proposals/cluster-filter-select.tsx) into one primitive.
  - For `fk-select`: page sizes are capped at `limit=200` (per the existing cluster-filter precedent in `cluster-filter-select.tsx:13`, which carries the same conservative cap with a "MVP1: <10 clusters per installer" comment). Full-list paging for installs with >200 clusters/templates is out of scope for this PR — the same comment-anchored caveat carries forward; if a future install hits the cap, the existing `cluster-filter-select` follow-up rationale (captured in [`feat_proposals_ui` implementation plan](../../../00_overview/implemented_features/2026_05_12_feat_proposals_ui/implementation_plan.md) §risks) covers it.

### FR-6: `<DataTable>` primitive — debounced text-search input

- Requirement:
  - When `props.searchable === true`, the primitive **MUST** render a text input in the toolbar (placeholder: "Search…").
  - The input **MUST** debounce by 300ms before emitting an `onSearchChange` callback to the consumer's hook.
  - The input **MUST** require `value.length >= 2` before emitting; for shorter values the primitive emits an empty string (clears the search).
  - The input **MUST** serialize the current value to the URL as `?q=<text>`.
  - The primitive **MUST** display a small "(N results)" indicator next to the input when a search is active, derived from `totalCount`.
  - When `props.searchable === false` (e.g., `trials-table`, `proposals-table`), the input is not rendered.
- Notes:
  - Frontend Zod schema enforces `min(2).max(200)`; matches backend Pydantic `Field(min_length=2, max_length=200)`.
  - Debounce hook lives at `ui/src/hooks/use-debounced-value.ts` (new — 30 LOC); the hook is general-purpose and not DataTable-specific.

### FR-7: Total-count display

- Requirement:
  - The primitive **MUST** render a total-count indicator in the top-right of the toolbar when `totalCount` is non-null.
  - On the **first page** (cursor stack length 1 — no `?cursor=` in the URL on initial load OR after a state change that cleared the cursor), the indicator **MUST** read `Showing 1–<rowsRendered> of <totalCount>`.
  - On **any subsequent page** (cursor stack length > 1, OR direct load of a URL containing `?cursor=<opaque>`), the indicator **MUST** read `Showing <rowsRendered> rows (of <totalCount> matching)`. The range `M–N` is intentionally omitted because the cursor's opaque encoding does not allow the primitive to reconstruct the absolute page index after a direct URL load — claiming "23–45 of 312" on a shared/refreshed link would be wrong when the user actually landed on page 2 fresh and not via in-app navigation.
  - When `totalCount === 0` the indicator reads `No matching rows`.
- Notes:
  - This wording reflects the fundamental limit of opaque-cursor pagination: total count is known (from `X-Total-Count`), but absolute window position is only known when the user navigated via in-app Next clicks (cursor stack length is tracked in React state, not URL).
  - Same total-count source used by the existing `CursorPaginator.totalCount` prop — no contract change.

### FR-8: URL-backed state for sort, filters, q, cursor

- Requirement:
  - The primitive's `useDataTableUrlState(tableId, columns)` hook **MUST** serialize the following to query params:
    - `?sort=<col>:<asc|desc>` — single-column sort (omitted when unsorted)
    - `?<column.id>=<wireValue>` — one param per active enum / fk-select filter
    - `?q=<text>` — active text search (omitted when empty or <2 chars)
    - `?cursor=<opaque>` — paginator cursor (omitted on first page)
  - **History strategy:**
    - **Cursor-page navigation (Next / Prev clicks)** **MUST** use `useRouter().push()` so the browser Back/Forward buttons step through page boundaries. Pressing Back after clicking Next returns to the prior page within the current `/studies` view.
    - **All other state changes** (filter toggle, sort click, search-input keystroke after debounce) **MUST** use `useRouter().replace()` so quick UI tweaks don't pollute the history stack with one entry per keystroke. Filter / sort / search changes also **MUST** clear `?cursor=` (page resets to first).
    - **Back-button semantics consequence:** because filter/sort/search use `replace()`, pressing Back from `/studies?status=completed&q=product` returns to whatever route preceded `/studies` (e.g., the dashboard) — not to a previous filter combination on the same `/studies` route. This is intentional: filter chips and the search input are committed-as-you-type UI state, not bookmarked-per-keystroke navigation. Users who want to compare two filter states open new tabs.
  - On initial mount, the hook **MUST** parse the URL and hydrate the primitive's internal state.
- Notes:
  - The `?cursor=` reset-on-filter-change rule is the convention already in use on `/studies` and `/proposals` (`setCursorStack([undefined])` on filter change). The hook centralizes it.
  - History tests: a vitest spec exercises a sequence of `push` (cursor) and `replace` (filter/sort/q) calls and asserts the call signatures on a mocked `useRouter()`.

### FR-9: Three empty-state shapes

- Requirement:
  - The primitive **MUST** render `<DataTableEmpty kind="no-rows-match" onClearFilters={() => void} />` when `data.length === 0 AND (any filter | q) is active`. **Sort does NOT trigger the no-rows-match state** — sort reorders rows but never filters; an empty resource sorted by `?sort=name:asc` is still an empty resource, not a "no match" situation.
  - The primitive **MUST** render `<DataTableEmpty kind="no-rows-exist" primaryCta={<Button>} />` when `data.length === 0 AND totalCount === 0 AND no filters/q are active` (sort presence does NOT change this branch).
  - The primitive **MUST** render `<DataTableEmpty kind="stale-cursor" onReturnToFirstPage={() => void} />` when `data.length === 0 AND totalCount > 0 AND ?cursor=` is in the URL state (i.e., the user landed on a now-empty page because the underlying rows shifted between page loads). Action: a "Return to first page" button that calls `useDataTableUrlState`'s `clearCursor()` and refetches. This branch is distinct from `no-rows-match` (which requires an active filter/q) and from `no-rows-exist` (which requires `totalCount === 0`).
  - The consumer supplies the empty-state title + message + (for `no-rows-exist`) the primary CTA via props. The `no-rows-match` clear-filters action and the `stale-cursor` return-to-first-page action are primitive-supplied (no consumer wiring needed).
- Notes:
  - This is a refinement of the existing inconsistency where `studies-empty` says "No studies match the current filters" regardless of whether filters are actually active.
  - "Filter active" means any column-filter param is non-empty in URL state. "Sort active" is excluded from this check by design.

### FR-10: Cursor pagination controls

- Requirement:
  - The primitive **MUST** internally render [`<CursorPaginator>`](../../../../ui/src/components/common/cursor-paginator.tsx) at the bottom of the table.
  - Consumers **MUST NOT** import `CursorPaginator` directly — it's an implementation detail of DataTable.
  - Page-size changes **MUST** reset the cursor stack (DataTable's `useDataTableUrlState` clears `?cursor=`).
- Notes:
  - Preserves the existing prev/next/page-size selector behavior; no UX change.

### FR-11: Sticky header on scroll

- Requirement:
  - The primitive **MUST** apply `position: sticky; top: 0; z-10` Tailwind classes to the `<TableHeader>` element.
  - The sticky header **MUST** sit above table-body rows on scroll within a constrained parent (e.g., a Card with `max-h-[600px] overflow-y-auto`).
- Notes:
  - One-line Tailwind addition; no JavaScript.

### FR-12: Tooltip-enabled column headers

- Requirement:
  - The primitive **MUST** render an `<InfoTooltip glossaryKey={column.tooltipKey} />` next to the column header text when `column.tooltipKey` is set.
  - The tooltip uses the existing `ui/src/lib/glossary.ts` glossary; columns that map to backend enums (e.g., `study.status`, `trial.status`) reuse existing glossary keys.
- Notes:
  - Zero new primitives — purely reuses `feat_contextual_help` Phase 1 work.

### FR-13: Multi-row selection + bulk-action toolbar

- Requirement:
  - When `props.selectable === true`, the primitive **MUST** render a checkbox column at the leftmost position.
  - The header row's checkbox **MUST** select/deselect all rows on the current page.
  - The bulk-action toolbar **MUST** render when `selectedIds.length >= 1` and contain consumer-supplied actions plus a counter ("N selected on this page").
  - Selection state **MUST** clear when the cursor moves (page change) or when filters/sort/q changes.
  - Selection state **MUST NOT** appear in the URL.
  - The primitive **MUST** call `props.onSelectionChange(selectedIds: string[])` on every change so the consumer can wire whatever bulk-action endpoint exists (e.g., `POST /studies/bulk-cancel`).
- Notes:
  - The primitive itself only manages the selection state — backend bulk endpoints are out of scope (none of the 8 migrated tables introduces one in this PR).

### FR-14: Column visibility menu

- Requirement:
  - The primitive **MUST** render an eye-icon dropdown in the toolbar listing every column with `column.hideable !== false`.
  - Toggling a column **MUST** show/hide it immediately and persist the hidden-set to `localStorage` under key `relyloop:datatable:<tableId>:hidden-columns`.
  - Sticky columns (the selection checkbox and the first identifier column, identified by `column.sticky === true`) **MUST NOT** appear in the dropdown.
  - On mount, the primitive **MUST** read the hidden-set from `localStorage` and apply it.
- Notes:
  - `tableId` is a required prop on `<DataTable>`. Conflict prevention: each migrated table chooses a stable `tableId` (`studies`, `proposals`, `trials`, etc.).

### FR-15: Density toggle (comfortable / compact)

- Requirement:
  - The primitive **MUST** render a two-position toggle in the toolbar with values `comfortable` (default) and `compact`.
  - The current density **MUST** apply via Tailwind classes: `comfortable` uses `py-3 px-4`, `compact` uses `py-1.5 px-3`.
  - The current density **MUST** persist to `localStorage` under key `relyloop:datatable:<tableId>:density`.
- Notes:
  - Adds two CSS class strings; not a deep change.

### FR-16: Keyboard navigation

- Requirement:
  - When `props.keyboardNav !== false`, the primitive **MUST** support:
    - Arrow Up / Arrow Down — move row focus (visible via `aria-selected` and a focus ring).
    - Enter — call `props.onRowActivate(rowId)` (typically navigates to the row's detail page).
    - Space — toggle row selection when `props.selectable === true`.
  - Focus management **MUST** wrap from last row to first (and vice versa) when arrow keys are pressed at the edges.
  - The primitive **MUST** render `tabIndex={0}` on rows so they're focusable.
- Notes:
  - Opt out per table via `keyboardNav={false}`.

### FR-17: Source-of-truth lint guard (column-config discipline)

- Requirement:
  - A vitest test **MUST** assert that every column config with `filter: { kind: 'enum', wireValues: <ARR> }` also has a non-empty `sourceOfTruth: string` field.
  - The test **MUST** scan every `*.column-config.ts` (or `*.tsx` containing a column-config export) file in `ui/src/components/`.
- Notes:
  - Lighter than a custom ESLint rule; reuses existing vitest infrastructure.

## 8) API and data contract baseline

### 8.1 Endpoint surface

All endpoints below are existing — the spec adds new query parameters. No new routes.

| Method | Path | New parameters (this PR) | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters` | `?q` (≥2 chars), `?sort` (Literal), `?engine_type` (Literal), `?environment` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/studies` | `?q` (≥2 chars), `?sort` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/query-sets` | `?q` (≥2 chars), `?sort` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/query-templates` | `?q` (≥2 chars), `?sort` (Literal), `?engine_type` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/judgment-lists` | `?q` (≥2 chars), `?since` (ISO 8601), `?sort` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/conversations` | `?q` (≥2 chars), `?since` (ISO 8601) — `?sort` deferred (no UI consumer in this PR; see scope note below) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/proposals` | `?template_id` (UUID), `?sort` (Literal) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/studies/{study_id}/trials` | (no new params — existing `?sort=<combined-wire-value>` Literal preserved) | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/judgment-lists/{judgment_list_id}/judgments` | `?sort` (Literal `created_at:asc \| created_at:desc \| rating:asc \| rating:desc \| source:asc \| source:desc`) | `VALIDATION_ERROR` (422) |

All endpoints continue to support their existing parameters (`?cursor`, `?limit`, `?since` where it exists, `?status`, `?cluster_id`, `?source`, etc.).

**Wire shape for `?sort=`:** for clusters, studies, query-sets, query-templates, judgment-lists, and proposals the new sort wire format is `<col>:<asc|desc>` (e.g., `?sort=name:asc`, `?sort=created_at:desc`). The URL form is **identical** to the wire form — no translation. The trials endpoint preserves its existing **combined** wire shape (`primary_metric_desc`, `ended_at_asc`, `optuna_trial_number_asc`, etc.) for backward compatibility with existing bookmarks; trials URLs also use the combined wire shape (`?sort=primary_metric_desc`, never `?sort=primary_metric:desc`). See §8.4 for the per-resource sort key table.

**Scope note on `conversations?sort=`:** the conversations list endpoint adds `?q=` and `?since=` in this PR but NOT `?sort=`. The conversations list surface is the chat sidebar, which is not migrated to DataTable in this PR (chat-sidebar is owned by `feat_chat_agent` and uses its own bespoke list rendering). `?q=` and `?since=` ship as backend-only additions to close the api-conventions.md drift and prepare for a future migration; no MVP1 UI consumer.

**Scope note on `judgment-lists?q=`:** the judgment-lists list endpoint adds `?q=` for backend completeness (matches the idea's "6 searchable resources" lock), but the existing `/judgments/{id}` route is a **detail page for a single judgment list** — it displays per-judgment rows, not a list of judgment lists. The migrated `judgments-table.tsx` is therefore `searchable={false}` (no text-search input in the toolbar). The new `?q=` endpoint has a backend integration test in this PR but no MVP1 frontend consumer; a future `/judgment-lists` index page will wire it up.

### 8.2 Contract rules

- `?q=` **MUST** be UTF-8. Pydantic auto-handles. No special quoting beyond standard URL-encoding.
- `?q=` **MUST** be combined with all other active filters via SQL AND.
- **Ordering and cursor encoding under FTS:** when `?q=` is active, results **MUST** be ordered by `created_at DESC, id DESC` (this PR ships filter-only FTS — no `ts_rank` re-ordering per FR-1). The `(created_at, id)` cursor remains valid because the ORDER BY leading key matches the cursor leading key.
- **Ordering and cursor encoding under `?sort=`:** the cursor encoding is sort-aware per FR-3a. When `?sort=` is absent or `?sort=created_at:desc`, the cursor is the legacy `(created_at, id)` shape. When `?sort=` is any other value, the cursor is `(<sort_col_value>, id)`. The repo applies a keyset predicate matching the current `ORDER BY` (including `NULLS LAST` / `NULLS FIRST` per direction) so pagination is correct.
- **Mutual exclusion:** at most one ORDER BY shape is active per request — `?q=` does not interact with `?sort=` (queries can combine both, but the active `?sort=` wins the ordering decision; `?q=` only filters). The cursor predicate matches whichever ORDER BY shape is in effect.

### 8.3 Response examples

Success (e.g., `GET /api/v1/studies?q=product&status=completed&limit=2`):

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-Total-Count: 12

{
  "data": [
    {
      "id": "01913dba-1234-7000-89ab-cdef01234567",
      "name": "Product search NDCG tuning",
      "cluster_id": "01913dba-2345-7000-89ab-cdef01234567",
      "status": "completed",
      "best_metric": 0.842,
      "created_at": "2026-05-14T10:00:00Z",
      "completed_at": "2026-05-14T11:30:00Z"
    },
    {
      "id": "01913dba-2345-7000-89ab-cdef01234567",
      "name": "Product catalog precision@10",
      "cluster_id": "01913dba-2345-7000-89ab-cdef01234567",
      "status": "completed",
      "best_metric": 0.731,
      "created_at": "2026-05-13T15:00:00Z",
      "completed_at": "2026-05-13T16:45:00Z"
    }
  ],
  "next_cursor": "<opaque>",
  "has_more": true
}
```

Failure — under-length search (`GET /api/v1/studies?q=p`):

```http
HTTP/1.1 422 Unprocessable Content
Content-Type: application/json

{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "Request validation failed: query.q: String should have at least 2 characters",
    "retryable": false
  }
}
```

> **Note on shape:** the existing `validation_exception_handler` in [`backend/app/api/errors.py:102-119`](../../../../backend/app/api/errors.py) intercepts FastAPI's raw `RequestValidationError` and re-shapes the per-field issues into the canonical envelope `{"detail": {"error_code": "VALIDATION_ERROR", "message": "Request validation failed: <field>: <msg>; ...", "retryable": false}}`. The per-field detail is summarized into the human-readable `message` string (full per-field structured detail arrives at GA v1 when RFC 7807 lands). Contract tests assert `error_code == "VALIDATION_ERROR"` and the `message` substring contains the offending field path (e.g., `query.q`).

Failure — invalid `?template_id=` UUID (`GET /api/v1/proposals?template_id=not-a-uuid`):

```http
HTTP/1.1 422 Unprocessable Content
Content-Type: application/json

{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "invalid template_id: not a valid UUID",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

The DataTable's filter chips and sort keys MUST trace back to backend allowlists. Below is the complete catalog of enumerated values across the 8 migrated tables.

#### Sort keys (per resource — `?sort=` wire values are the URL form too, except for trials which uses combined wire form)

**How to read this table:** the "Sortable columns" cell lists the column names allowed in `?sort=`. The accepted Literal values are the **cross-product** of each column with `:asc` / `:desc` — e.g., `name:asc`, `name:desc`, `created_at:asc`, `created_at:desc` are all accepted on `?sort=` for `studies`. Pydantic types this as `Literal["name:asc", "name:desc", "created_at:asc", ...]`. Trials is the sole exception — see its row.

| Table | Sortable columns | Backend source of truth | Frontend call site (this PR) |
|---|---|---|---|
| `studies` | `name`, `created_at`, `completed_at`, `best_metric`, `status` (× `:asc` / `:desc`) | New `StudySortKey` Literal in `backend/app/api/v1/schemas.py` — added in this PR | `<DataTable>` column config in `ui/src/components/studies/studies-table.tsx` |
| `trials` (combined wire — preserves existing shape) | Accepted `?sort=` values: `primary_metric_desc`, `primary_metric_asc`, `ended_at_desc`, `ended_at_asc`, `optuna_trial_number_asc` | Existing `TrialSortKey` in `backend/app/api/v1/schemas.py:181` — no change | `<DataTable>` column config in `ui/src/components/studies/trials-table.tsx` with consumer-supplied encoder mapping internal `(col, dir)` to the combined wire value (per FR-4) |
| `proposals` | `created_at`, `status`, `pr_state` (× `:asc` / `:desc`) | New `ProposalSortKey` Literal — added in this PR | column config in `ui/src/components/proposals/proposals-table.tsx` |
| `clusters` | `name`, `created_at`, `environment` (× `:asc` / `:desc`) | New `ClusterSortKey` Literal — added in this PR | column config in `ui/src/components/clusters/clusters-table.tsx` |
| `judgment_lists` (backend-only — no UI consumer in this PR) | `name`, `created_at`, `status` (× `:asc` / `:desc`) | New `JudgmentListSortKey` Literal — added in this PR; the endpoint accepts the param and the integration test exercises it. **No frontend consumer in this PR** — a future `/judgment-lists` index page or dashboard search card will wire it up. | None in this PR |
| judgments per-list rows (`GET /api/v1/judgment-lists/{id}/judgments`) | `created_at`, `rating`, `source` (× `:asc` / `:desc`) | New `JudgmentRowSortKey` Literal — added in this PR. Endpoint already accepts `?cursor`, `?limit`, `?source`; this PR adds `?sort`. | `<DataTable>` column config in `ui/src/components/judgments/judgments-table.tsx` |
| `query_sets` | `name`, `created_at` (× `:asc` / `:desc`) | New `QuerySetSortKey` Literal — added in this PR | column config in `ui/src/components/query-sets/query-sets-table.tsx` |
| `query_templates` | `name`, `created_at`, `engine_type`, `version` (× `:asc` / `:desc`) | New `QueryTemplateSortKey` Literal — added in this PR | column config in `ui/src/components/templates/templates-table.tsx` |

**Conversations sort:** explicitly deferred — `GET /api/v1/conversations` does **not** gain `?sort=` in this PR (conversations chat-sidebar is owned by `feat_chat_agent` and not migrated to DataTable here). No `ConversationSortKey` Literal added in this PR.

> **Source-of-truth convention for new sort enums:** every new `*SortKey` Literal in `schemas.py` carries an inline comment `# Wire values consumed by ui/src/lib/enums.ts <ARRAY_NAME>` immediately above its definition. The matching `ui/src/lib/enums.ts` export carries the `// Values must match backend/...py <Symbol>` comment per the existing enums.ts discipline. The Story 4.2 CI grep gate (already in place) catches drift.

#### Filter wire values (per resource — existing + new)

All values below already exist in `ui/src/lib/enums.ts` (verified during preflight). DataTable column configs reference the existing exports — no new value enums introduced.

| Filter | Accepted values (exact) | Backend source of truth | Frontend call site |
|---|---|---|---|
| `studies?status=` | `queued`, `running`, `completed`, `cancelled`, `failed` | `STUDY_STATUS_VALUES` in `ui/src/lib/enums.ts` ← `StudyStatusWire` in `backend/app/api/v1/schemas.py` | studies DataTable filter column |
| `proposals?status=` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `PROPOSAL_STATUS_VALUES` ← `ProposalStatusWire` | proposals DataTable filter column |
| `proposals?source=` | `study`, `manual` | **New** `PROPOSAL_SOURCE_VALUES` in `ui/src/lib/enums.ts` (added in this PR — wire values mirror `ProposalSourceWire` in `backend/app/api/v1/schemas.py:752`). The existing inline array in [`proposal-source-filter-chips.tsx:9`](../../../../ui/src/components/proposals/proposal-source-filter-chips.tsx) is removed when that component is replaced by the DataTable migration. A stale comment on line 5 ("backend has no `?source=` param") pre-dates PR #83 and dies with the file. | proposals DataTable filter column |
| `proposals?template_id=` | Any UUIDv7 from `query_templates.id` | DB FK on `proposals.template_id` | proposals DataTable filter column (queries `useTemplates()` to populate chip options) |
| `judgments?source=` | `llm`, `human` | `JUDGMENT_SOURCE_FILTER_VALUES` ← `JudgmentSourceFilterWire` | judgments DataTable filter column |
| `clusters?engine_type=` | `elasticsearch`, `opensearch` | `ENGINE_TYPE_VALUES` ← `EngineTypeWire` | clusters DataTable filter column (new — no current filter chip) |
| `clusters?environment=` | `prod`, `staging`, `dev` | `ENVIRONMENT_VALUES` ← `Environment` | clusters DataTable filter column (new) |
| `query-templates?engine_type=` | `elasticsearch`, `opensearch` | `ENGINE_TYPE_VALUES` ← `EngineTypeWire` | templates DataTable filter column (new) |

> **Important — clusters & templates filter additions:** `?engine_type=` is a new query parameter on `GET /api/v1/clusters` and `GET /api/v1/query-templates`. Both repos already filter by `engine_type` internally for join queries; surfacing it as a router param is +1 LOC each. `?environment=` is similarly +1 LOC on `clusters`. These additions are within scope per Locked Decision #4.

### 8.5 Error code catalog

No new error codes. Existing `VALIDATION_ERROR` (422) covers under-length `?q=`, invalid `?template_id=` UUID, and unknown `?sort=` wire values (the Literal-typed parameter handles unknown values automatically).

## 9) Data model and state transitions

### New/changed entities

**Modified table: `clusters`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(base_url, ''))) STORED`) — populated automatically; not in ORM model.
- Add `clusters_search_vector_idx` (`GIN(search_vector)`).

**Modified table: `studies`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(target, ''))) STORED`).
- Add `studies_search_vector_idx` (`GIN(search_vector)`).

**Modified table: `query_sets`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, ''))) STORED`).
- Add `query_sets_search_vector_idx` (`GIN(search_vector)`).

**Modified table: `query_templates`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, ''))) STORED`).
- Add `query_templates_search_vector_idx` (`GIN(search_vector)`).

**Modified table: `judgment_lists`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(target, ''))) STORED`).
- Add `judgment_lists_search_vector_idx` (`GIN(search_vector)`).

**Modified table: `conversations`**
- Add `search_vector` (`tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, ''))) STORED`).
- Add `conversations_search_vector_idx` (`GIN(search_vector)`).

No new tables. No `tenant_id` column (MVP1–3 is single-tenant per `data-model.md`).

### Required invariants

- The `search_vector` columns are **generated** and **MUST NOT be writable** from application code. The ORM models do not declare them. Any attempt to write fails at the Postgres layer with `ERROR: column "search_vector" can only be updated to DEFAULT` — this is a Postgres invariant, not an application one, but the spec calls it out so future implementers don't accidentally try to set the column.
- **Cursor leading key matches ORDER BY leading key.** When `?sort=` is absent or `?sort=created_at:desc`, both are `(created_at, id)`. When `?sort=<col>:<dir>` is non-default, both are `(<col>, id)`. This is enforced at the repo layer in the cursor encode/decode helpers and verified by integration tests that fetch multiple pages and assert no duplicates and no skips.
- The `?q=` parameter is rejected by Pydantic at the router boundary for `len < 2` or `len > 200`. The repo layer's `q: str | None` is therefore either `None`, or a string of length 2–200, but the repo does not re-validate.

### State transitions

N/A — this feature adds query-time filtering, not state-bearing entities.

### Idempotency/replay behavior

N/A — DataTable is read-only UI. All affected endpoints are `GET`.

## 10) Security, privacy, and compliance

- **Threats considered:**
  1. **`?q=` injection via crafted text.** Mitigated: Postgres `plainto_tsquery` is the safe-to-use FTS parser; it does not allow operator characters or arbitrary expressions. Pydantic `Field(min_length=2, max_length=200)` caps the input size. SQLAlchemy parameter binding (`:q`) prevents SQL injection.
  2. **`?q=` exposing rows via FTS the user shouldn't see.** N/A — MVP1 is single-tenant; every authenticated session sees every row. When auth lands at MVP4, the per-request tenant filter is applied at the repo layer **before** the FTS clause (existing pattern), so FTS cannot leak cross-tenant.
  3. **Denial-of-service via expensive FTS queries.** Mitigated by the `min_length=2, max_length=200` cap, the GIN index (sub-millisecond on rows ≤10K), and MVP1's single-tenant install (no concurrent attacker load).
  4. **`localStorage`-stored column visibility / density leaking across users.** N/A — single-tenant; the localStorage key is scoped per `tableId`. If a future shared-browser MVP4 install needs eviction, the keys can be cleared on logout.
- **Controls:** parameter binding, length cap, GIN index, `plainto_tsquery` (no operator parsing).
- **Secrets/key handling:** N/A.
- **Auditability:** N/A — read-only endpoints; audit_log lands at MVP2.
- **Data retention / export impact:** none.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement.** No new pages. The DataTable replaces the rendering of 8 existing list pages and inherits to a 9th wrapper. Page-level routes (`/studies`, `/proposals`, `/clusters`, `/templates`, `/query-sets`, `/query-sets/{id}`, `/judgments/{id}`, `/studies/{id}` for trials) are unchanged.
- **Labeling taxonomy:**
  - Toolbar search input: placeholder `"Search…"` (lowercase per shadcn convention).
  - Sort column header chevron: visually-hidden text `"Sorted ascending"` / `"Sorted descending"` / `"Not sorted"` for screen readers.
  - Filter chip: chip label = the wire value verbatim (e.g., "completed", "queued"). Matches existing studies/proposals chip behavior.
  - "Showing 1–N of M" total-count indicator: this exact phrasing.
  - Bulk-action toolbar counter: "N selected on this page".
  - Density toggle: labels "Comfortable" / "Compact".
  - Column visibility dropdown trigger: an Eye icon (lucide-react `<Eye />`); the dropdown items label each column with its header text.
- **Content hierarchy:** Toolbar (search + filters + total count + density + column visibility + bulk-action toolbar when active) at top; table body with sticky header below; cursor paginator at bottom.
- **Progressive disclosure:** Column visibility menu hides behind the eye icon; density toggle is always visible; bulk-action toolbar appears only when ≥1 row is selected.
- **Relationship to existing pages:** all 8 migrated tables continue to live in their existing routes; the migration changes the rendering of the table component, not the page surrounding it.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| Sortable column header (any column) | "Click to sort ascending. Click again to reverse, click a third time to clear." | hover/focus | top |
| Filter chip row label | Reuses existing per-resource glossary entries (e.g., `study.status` for studies table) | hover/focus | top |
| Search input | "Type at least 2 characters to search by name." | focus | inline below input |
| Total count "Showing 1–N of M" | "M is the total across all pages matching the current filter." | hover | top |
| Density toggle | "Switch between comfortable and compact row heights." | hover | top |
| Column visibility menu | "Show or hide columns. Choices persist on this device." | hover | top |
| Selection checkbox column header | "Select all rows on this page. Selection clears when you change page." | hover/focus | top |
| Bulk-action toolbar | (consumer-supplied per action) | per consumer | per consumer |

**New glossary keys** in `ui/src/lib/glossary.ts` for the primitive-level tooltips above:

| Glossary key | `short` text |
|---|---|
| `datatable.sort.toggle` | "Click to sort ascending. Click again to reverse, click a third time to clear." |
| `datatable.search.min_length` | "Type at least 2 characters to search by name." |
| `datatable.total_count` | "M is the total across all pages matching the current filter." |
| `datatable.density.toggle` | "Switch between comfortable and compact row heights." |
| `datatable.column_visibility` | "Show or hide columns. Choices persist on this device." |
| `datatable.selection.all_on_page` | "Select all rows on this page. Selection clears when you change page." |

### Primary flows

1. **Sort + filter + search a list (Studies as canonical example).**
   - User navigates to `/studies`.
   - URL: `/studies` (no filters).
   - User clicks "completed" filter chip → URL `/studies?status=completed`, cursor reset.
   - User types "product" in the search input → 300ms debounce → URL `/studies?status=completed&q=product`, cursor reset.
   - User clicks "Created" column header → URL `/studies?status=completed&q=product&sort=created_at:desc`.
   - User clicks "Next" page → URL `/studies?status=completed&q=product&sort=created_at:desc&cursor=<opaque>`.
   - User refreshes browser → same view; user shares URL → recipient sees same view.

2. **Select rows and trigger a bulk action (hypothetical — no consumer ships one in this PR).**
   - User checks 3 study rows → toolbar lights up: "3 selected on this page" + consumer-supplied actions.
   - User clicks "Cancel selected" → consumer's `onBulkAction` callback fires with `selectedIds`.
   - User navigates to next page → selection clears.

3. **Column visibility persistence.**
   - User hides "Cluster" and "Completed" columns on `/studies` via the eye-icon menu.
   - User navigates away and returns → hidden columns are still hidden (localStorage `relyloop:datatable:studies:hidden-columns = ["cluster_id", "completed_at"]`).

### Edge/error flows

- **Backend 422 on `?q=` shorter than 2 chars:** the frontend debounce + Zod `min(2)` guard prevents the call; this is a defense-in-depth only.
- **Backend 422 on unknown `?sort=` value:** if a stale URL bookmark contains a sort key the new schema doesn't list, FastAPI Literal validation returns 422 `VALIDATION_ERROR`. Frontend catches via the existing global error toast (per `query-provider.tsx`).
- **Backend 5xx during a search:** the global error toast renders; the table shows `<EmptyState>` "Backend unreachable" (existing convention).
- **`localStorage` quota exceeded:** column visibility / density write fails silently (try/catch in the hook); subsequent reads return the default values. No user-visible error.
- **Multiple browser tabs disagree on column visibility:** last-write-wins; no cross-tab sync. Acceptable for MVP1.
- **Stale cursor (cursor advances past `totalCount` due to concurrent insert/delete, or a shared URL points to a deleted page):** DataTable detects this when `data.length === 0 AND totalCount > 0 AND ?cursor=` is in the URL. It renders a dedicated `<DataTableEmpty kind="stale-cursor" onReturnToFirstPage={() => clearCursor()} />` shape with copy "This page is no longer available. Return to the first page." plus a primary action button. This branch does **not** reuse `no-rows-match` (which requires an active filter/q per FR-9). Mitigated in MVP2 by trace-correlated dashboards.

## 12) Given/When/Then acceptance criteria

### AC-1: Sortable column header cycles through three states

- Given a relevance engineer is on `/studies` viewing a DataTable with `name` as a sortable column.
- When they click the "Name" column header three times.
- Then the URL transitions: `/studies` → `/studies?sort=name:asc` → `/studies?sort=name:desc` → `/studies`.
- And the chevron icon transitions: none → up → down → none.

### AC-2: Filter chip selection resets cursor

- Given a relevance engineer is on `/studies?cursor=<opaque>&status=completed` viewing page 2.
- When they click the "queued" filter chip.
- Then the URL becomes `/studies?status=queued` (no `cursor=` param).
- And the table renders page 1 of queued studies.

### AC-3: Text-search input debounces and rejects under-length

- Given a relevance engineer is on `/studies`.
- When they type "p" → wait 400ms → type "r" → wait 400ms.
- Then no `?q=` request fires after typing "p" (under min length).
- And `GET /api/v1/studies?q=pr` fires once after typing "r" + debounce.
- And the URL becomes `/studies?q=pr`.

### AC-4: Backend rejects `?q=` under 2 characters

- Given the backend API is up.
- When a client sends `GET /api/v1/studies?q=p`.
- Then the response is 422 `VALIDATION_ERROR` with the under-length detail.
- Example: see §8.3 Failure response.

### AC-5: `?q=` returns FTS-matched results (newest-first)

- Given the `studies` table contains rows with `name` values: "Product search NDCG" (created earlier), "Product catalog precision" (created later), "Cart checkout latency".
- When a client sends `GET /api/v1/studies?q=product`.
- Then the response `data` contains the two matching rows (both match `product` after stemming).
- And the third row ("Cart checkout latency") is excluded.
- And `X-Total-Count: 2`.
- And the rows are ordered `created_at DESC, id DESC` — so "Product catalog precision" (later-created) comes before "Product search NDCG" (earlier-created). Note: this PR ships filter-only FTS (no `ts_rank` re-ordering) per FR-1 and §16; rank-ordered ranking is a deferred follow-up.

### AC-6: `?q=` combines with `?status=` and `?cluster_id=`

- Given studies of multiple statuses and clusters exist.
- When a client sends `GET /api/v1/studies?q=product&status=completed&cluster_id=<X>&limit=10`.
- Then the response `data` contains only completed studies in cluster X whose `search_vector` matches `plainto_tsquery('english', 'product')`.
- And `X-Total-Count` is the count of that intersection (not the total of any individual filter).

### AC-7: Alembic migrations round-trip clean across all six revisions

- **Full-stack round-trip:**
  - Given a fresh database at Alembic revision `0007_conversations_messages`.
  - When the operator runs `alembic upgrade head && alembic downgrade 0007 && alembic upgrade head` (using the explicit `0007` target so all six new revisions roll back, not just the latest).
  - Then the operation completes without error.
  - And the 6 GIN indexes (`clusters_search_vector_idx`, `studies_search_vector_idx`, `query_sets_search_vector_idx`, `query_templates_search_vector_idx`, `judgment_lists_search_vector_idx`, `conversations_search_vector_idx`) exist after the second `upgrade head` (verified via `pg_indexes`).
  - And no `search_vector` column remains on any of the 6 tables after the `downgrade 0007` step (verified via `information_schema.columns`).
- **Per-migration round-trip** (asserted independently for each of the 6 new revisions, so a regression on any single migration surfaces immediately):
  - Given the database is at the migration's `down_revision`.
  - When the test runs `alembic upgrade <revision> && alembic downgrade -1 && alembic upgrade <revision>`.
  - Then the migration's specific `search_vector` column and `<table>_search_vector_idx` exist after the second upgrade.
  - And neither the column nor the index exists after the `downgrade -1` step.

### AC-8: `search_vector` column is not application-writable

- Given the `studies` table has the `search_vector` generated column.
- When application code attempts `await db.execute(update(Study).values(search_vector=...))`.
- Then Postgres returns an error: `column "search_vector" can only be updated to DEFAULT`.
- And no test fixture or ORM model attempts to write the column (assertion: search for `search_vector` in `backend/app/db/models/`; the result MUST be empty).

### AC-9: Filter chips reflect backend allowlist exactly

- Given the studies DataTable column config declares `filter: { kind: 'enum', wireValues: STUDY_STATUS_VALUES, sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire' }`.
- When the test `ui/src/__tests__/components/common/data-table-column-discipline.test.tsx` runs.
- Then it scans every `*.column-config.ts` (or `*.tsx` containing an exported column config) file under `ui/src/components/**` and for each column with `filter.kind === 'enum'`:
  - Asserts `column.filter.sourceOfTruth` is non-empty.
  - Asserts the array referenced by `column.filter.wireValues` is the same `as const` symbol imported from `ui/src/lib/enums.ts` (i.e., the column does NOT inline its own array literal).
  - Asserts the matching `enums.ts` symbol carries the canonical `// Values must match backend/...py <Symbol>` source-of-truth comment.
- For `filter.kind === 'fk-select'` columns, the test asserts `sourceOfTruth` is non-empty (e.g., `"DB FK on proposals.template_id"`) without further structural assertion.
- The test scope is dynamic — adding a new DataTable consumer automatically picks up the parity check, no manual list maintenance required.

### AC-10: Selection clears on cursor movement

- Given a relevance engineer is on `/studies?status=completed` with rows A, B, C selected.
- When they click "Next" page.
- Then the URL gains `?cursor=<opaque>`.
- And `selectedIds` becomes `[]`.
- And the bulk-action toolbar is hidden.

### AC-11: Column visibility persists across page reloads

- Given a relevance engineer hides the "Cluster" column on `/studies` via the eye-icon menu.
- When they refresh the browser.
- Then the "Cluster" column is still hidden.
- And `localStorage["relyloop:datatable:studies:hidden-columns"]` contains `["cluster_id"]`.

### AC-12: Keyboard navigation moves row focus

- Given a relevance engineer focuses the first row on `/studies` via Tab.
- When they press Arrow Down.
- Then focus moves to the second row (visible focus ring).
- When they press Enter.
- Then the route navigates to `/studies/<second-row-id>`.

### AC-13: Trials table sort URL migrates from `<Select>` to column-header (combined-wire form preserved)

- Given a relevance engineer is on `/studies/<id>` viewing the trials table.
- Given the trials column config sets `column.firstClickDirection = 'desc'` on the "Primary metric" column (per FR-4 metric-shaped column convention).
- When they click the "Primary metric" column header twice.
- Then the URL transitions: `/studies/<id>` → `/studies/<id>?sort=primary_metric_desc` → `/studies/<id>?sort=primary_metric_asc`.
- And the URL form is identical to the backend `?sort=` wire value (combined "name-direction" shape — see FR-4 "Trials combined-wire encoder" branch and §8.4 trials row).
- And the existing `TrialSortKey` Literal `primary_metric_desc / primary_metric_asc / ended_at_desc / ended_at_asc / optuna_trial_number_asc` continues to be accepted by `GET /api/v1/studies/{id}/trials?sort=` without modification.

### AC-14: Total-count display reflects filtered count (with cursor-pagination caveat)

- Given the `studies` table has 100 rows, 12 of which have status `completed`.
- When a relevance engineer navigates fresh to `/studies?status=completed&limit=10` (page 1, no `?cursor=` in URL).
- Then the toolbar reads `Showing 1–10 of 12` (range form — first page, cursor stack length 1).
- When they click "Next" page (in-app navigation; the cursor stack grows to length 2 in React state, URL gains `?cursor=<opaque>`).
- Then the toolbar reads `Showing 2 rows (of 12 matching)` per FR-7's subsequent-page wording — the absolute window position cannot be reliably reconstructed from the opaque cursor on direct URL reloads, so the toolbar omits the `M–N` range claim on all post-first pages to keep the display correct regardless of how the user arrived.

### AC-15: Empty-state shape distinguishes "no match" from "no rows exist"

- Given the `clusters` table is empty (no clusters registered).
- When the user visits `/clusters`.
- Then the table renders `<DataTableEmpty kind="no-rows-exist">` with copy "No clusters registered" and a "Register cluster" CTA.
- Given the `clusters` table has 5 rows, none matching `?q=zzzz`.
- When the user types "zzzz".
- Then the table renders `<DataTableEmpty kind="no-rows-match">` with "Clear filters" action.

### AC-16: Source-of-truth lint guard catches missing `sourceOfTruth`

- Given a developer adds a new column config with `filter: { kind: 'enum', wireValues: [...] }` but forgets `sourceOfTruth: string`.
- When the vitest test in `ui/src/__tests__/components/common/data-table-column-discipline.test.tsx` runs.
- Then the test fails with a clear message: "Column config in `<file>` has `filter.kind='enum'` but no `sourceOfTruth` field — every enum filter must cite a backend allowlist file."

## 13) Non-functional requirements

- **Performance.**
  - FTS query p95 latency on each searchable table: <30ms for rows up to 10K (GIN index lookup only — no `ts_rank` sort cost per FR-1; MVP1's typical scale).
  - DataTable first-paint after data ready: <100ms for pages of 200 rows (TanStack Table row model is O(n) on row count).
  - Debounce window: 300ms ± 30ms.
  - `localStorage` read on mount: synchronous, <5ms.
- **Reliability.**
  - No new failure modes introduced. Existing backends keep working without `?q=`; sticky-header CSS is fail-safe.
  - The 6 Alembic migrations are independent — failure of any one rolls back the transaction; the rest of the head remains at the prior revision.
- **Operability.**
  - No new metrics. Existing structlog access-log middleware captures `?q=` as a request param like any other.
  - No new alerts. FTS endpoint failures show up in the existing error rates.
- **Accessibility.**
  - Sortable column headers: `<button role="columnheader" aria-sort="ascending|descending|none">` so screen readers announce sort state.
  - Filter chips: existing `role="group" aria-label="..."` pattern preserved.
  - Search input: `<label for="data-table-search">Search</label>` — visually hidden but present.
  - Sticky header: `position: sticky` does not break tab order (rows remain focusable in document order).
  - Keyboard navigation: focus ring uses Tailwind `focus-visible:ring-2` per existing convention.

## 14) Test strategy requirements (spec-level)

- **Unit tests** (`backend/tests/unit/`):
  - Pydantic schema validation: `?q=` rejects under-length, over-length, non-string; accepts 2–200 chars.
  - Pydantic schema validation: each new `*SortKey` Literal accepts canonical values and rejects unknowns.
  - Repo-layer (mockable parts): query builder produces the expected SQL fragment shape for `q + sort + filter` combinations. (Pure unit — no DB needed; SQLAlchemy `.compile(compile_kwargs={"literal_binds": True})`.)
- **Integration tests** (`backend/tests/integration/`):
  - Per searchable resource: seed N rows with known text values, hit `GET /<resource>?q=<term>`, assert the response matches the expected FTS-filtered subset (newest-first ordering — no `ts_rank` per FR-1).
  - Per searchable resource: `?q=` combines with all existing filters via AND.
  - Per searchable resource: `X-Total-Count` matches the filtered set.
  - Per resource with new `?sort=`: assert each `<col>:<dir>` Literal value produces the expected ordering.
  - `proposals?template_id=` filter returns the expected subset; `?engine_type=` and `?environment=` filters return the expected subset on clusters/templates.
  - **Alembic round-trip — two shapes:**
    - Full-stack: `upgrade head && downgrade 0007 && upgrade head` asserts all 6 GIN indexes + 6 columns exist after the second upgrade and none exist after the downgrade 0007 step. Uses `pg_indexes` + `information_schema.columns`.
    - Per-migration: for each of the 6 new revisions, `upgrade <revision> && downgrade -1 && upgrade <revision>` asserts only that revision's column + index are present/absent at each step. Six tests, one per revision.
- **Contract tests** (`backend/tests/contract/`):
  - `?q=` under-length → 422 with the canonical envelope shape `{"detail": {"error_code": "VALIDATION_ERROR", "message": "Request validation failed: query.q: …", "retryable": false}}` (per `backend/app/api/errors.py:validation_exception_handler`). Tests assert `detail.error_code == "VALIDATION_ERROR"`, `detail.retryable === false`, and `"query.q"` substring in `detail.message`.
  - `?q=` over-length → 422 (same envelope shape).
  - Unknown `?sort=` value → 422 (same envelope shape).
  - Unknown `?engine_type=` or `?environment=` value → 422 (same envelope shape).
  - `?template_id=` invalid UUID → 422 (same envelope shape).
  - All new params appear in OpenAPI schema (one assertion per endpoint in the existing `test_openapi_surface.py`).
- **Component tests** (vitest, `ui/src/__tests__/components/common/`):
  - `data-table.test.tsx`: renders rows, sortable column-header click cycles state, filter chip click sets URL, search input debounces 300ms + rejects <2 chars, empty-state shapes.
  - `data-table-bulk-actions.test.tsx`: toolbar appears when ≥1 row selected; counter shows correct N; clears on `clearSelection` callback.
  - `data-table-column-visibility.test.tsx`: dropdown lists hideable columns; localStorage persistence.
  - `use-data-table-url-state.test.ts`: hydrates from URL on mount; serializes to URL on state change; clears `?cursor=` on filter/sort/q change.
  - `data-table-column-discipline.test.tsx`: scans every column config for `filter.kind === 'enum'` → asserts non-empty `sourceOfTruth`.
- **E2E tests** (`ui/tests/e2e/`): one new spec per migrated table, tailored to that table's actual affordances. All use the real backend (no `page.route()` mocks).

  | Spec | Search | Sort | Filter chip(s) | FK select | Pagination |
  |---|---|---|---|---|---|
  | `studies-data-table.spec.ts` | ✓ | ✓ | `?status=` | — | ✓ |
  | `proposals-data-table.spec.ts` | ✗ (no FTS per §3) | ✓ | `?status=`, `?source=` | `?cluster_id=`, `?template_id=` | ✓ |
  | `clusters-data-table.spec.ts` | ✓ | ✓ | `?engine_type=`, `?environment=` | — | (no paginator today; new — verify cursor works) |
  | `templates-data-table.spec.ts` | ✓ | ✓ | `?engine_type=` | — | (new) |
  | `query-sets-data-table.spec.ts` | ✓ | ✓ | — | — | (new) |
  | `judgments-data-table.spec.ts` (per-list `/judgments/[id]` route — `searchable={false}`) | ✗ (assert input absent) | ✓ | `?source=` | — | ✓ |
  | `trials-data-table.spec.ts` (replaces `<Select>` with column-header sort) | ✗ (assert input absent) | ✓ (column-header click) | — | — | ✓ |
  | `studies-by-cluster-data-table.spec.ts` | inherits from studies | inherits | inherits | — | inherits |

  Each searchable-spec exercises search → sort → filter → pagination → URL state survives refresh. Each non-searchable-spec asserts the search input is absent and exercises sort + filter (where applicable) + pagination + URL state survives refresh.
- **Coverage gate:** existing 80% backend coverage gate must not regress. Frontend has no coverage gate (per existing project policy).

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md`: add `?q=` paragraph under §"Pagination" describing the FTS contract and the 6 searchable resources. Add `?since=` to the MVP1-status row for judgment-lists + conversations (the pre-existing drift this PR closes).
- `docs/01_architecture/ui-architecture.md`: new §"DataTable primitive" documenting the primitive's shape, the column-config interface, and the source-of-truth discipline.
- `docs/01_architecture/data-model.md`: per-table column tables get a row for `search_vector` (generated) + the GIN index name.
- `docs/00_overview/planned_features/feat_data_table_primitive/feature_spec.md`: this file.
- `docs/03_runbooks/local-dev.md`: optional — add a "FTS performance" subsection if the integration tests surface any operability gotchas. Likely not needed.
- `docs/04_security/`: no update — no new threat surfaces.
- `docs/05_quality/testing.md`: optional — note the new component-test discipline file `data-table-column-discipline.test.tsx`.
- `CLAUDE.md` "Common Pitfalls" section: add "Do not write to `search_vector` columns — they are generated; the ORM models do not declare them."
- `CLAUDE.md` "Frontend Conventions" §"Enumerated Value Contract Discipline": cross-reference the new `data-table.tsx` `column.filter.sourceOfTruth` field as another enforcement point.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. MVP1 is local-only (no staging environment); the operator either has the new primitive or they don't.
- **Migration / backfill expectations:** the 6 Alembic migrations are non-blocking — `GENERATED ALWAYS AS … STORED` runs at INSERT/UPDATE time, so the only cost on first deploy is rewriting existing rows. For MVP1's typical row counts (≤1000 rows per table on an alpha install), this completes in <1s per table. **No backfill script required** — Postgres auto-populates on the column add.
- **Deferred follow-up (post-MVP1): rank-ordered FTS results.** Per FR-1, this PR ships filter-only FTS (results match `?q=` and are ordered by `created_at DESC, id DESC`). True rank-ordered FTS (`ORDER BY ts_rank DESC`) would require either encoding `ts_rank` into the opaque cursor (custom serialization across 6 endpoints + brittle floating-point key boundaries) or replacing keyset cursor pagination with offset/limit (banned by [api-conventions.md "Anti-patterns"](../../../01_architecture/api-conventions.md)). Capture as a follow-up idea file (`feat_fts_rank_ordering_mvp2`) at PR finalization if not already captured.
- **Operational readiness gates:**
  - All 6 Alembic migrations round-trip clean.
  - All new component tests pass.
  - All new E2E specs pass against `make up` stack.
  - `make typecheck` clean (TanStack Table types resolve).
- **Release gate:**
  - CI green (lint + typecheck + tests on both backend and frontend; Docker build; smoke).
  - Gemini Code Assist review comments adjudicated per project policy.
  - GPT-5.5 final review clean.
  - At least one operator-verified path: `make up` → register a cluster → search for it by name in the `/clusters` DataTable → result returns.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (impl plan) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (`?q=` on 6 endpoints) | AC-3, AC-4, AC-5, AC-6, AC-14 | Stories 2.1–2.6 (one per searchable router) | `backend/tests/contract/test_<resource>_api_contract.py`, `backend/tests/integration/test_<resource>_fts.py` (new) | api-conventions.md §"Pagination" |
| FR-2 (6 Alembic migrations) | AC-7, AC-8 | Stories 1.1–1.6 (one per migration) | `backend/tests/integration/test_search_vector_migrations.py` (new) | data-model.md per-table tables |
| FR-3 (`?template_id` on proposals) | AC-6 (analogous) | Story 2.7 | `backend/tests/contract/test_digest_proposal_api_contract.py`, `backend/tests/integration/test_proposals_template_filter.py` (new) | api-conventions.md §"Pagination" |
| FR-3a (`?sort`, `?engine_type`, `?environment` filter params) | AC-1 (sort cycle), AC-9 (allowlist parity) | Stories 2.8–2.10 (one per backend filter param family) | contract: `test_<resource>_api_contract.py` for unknown-sort/engine/environment values; integration: per-resource sort + filter assertions | api-conventions.md §"Pagination", data-model.md per-table tables |
| FR-4 (sortable headers) | AC-1, AC-13 | Stories 3.1–3.2 (primitive sort + URL wiring) | `ui/src/__tests__/components/common/data-table.test.tsx` (sort cases) | ui-architecture.md §"DataTable primitive" |
| FR-5 (filter chips) | AC-2, AC-9 | Story 3.3 | `data-table.test.tsx` (filter cases), `data-table-column-discipline.test.tsx` | ui-architecture.md |
| FR-6 (debounced search) | AC-3 | Story 3.4 | `data-table.test.tsx` (search debounce) | ui-architecture.md |
| FR-7 (total-count display) | AC-14 | Story 3.5 | `data-table.test.tsx` (total-count cases) | ui-architecture.md |
| FR-8 (URL-backed state) | AC-1, AC-2, AC-13 | Story 3.6 | `use-data-table-url-state.test.ts` (new) | ui-architecture.md |
| FR-9 (two empty states) | AC-15 | Story 3.7 | `data-table.test.tsx` (empty cases) | ui-architecture.md |
| FR-10 (cursor paginator) | AC-2 | Story 3.8 (wrap CursorPaginator) | `data-table.test.tsx` (pagination cases) | ui-architecture.md |
| FR-11 (sticky header) | (visual; covered by E2E) | Story 3.9 | E2E specs | ui-architecture.md |
| FR-12 (tooltip headers) | (visual; covered by component tests + glossary parity) | Story 3.10 | `data-table.test.tsx` (tooltip cases) | ui-architecture.md, glossary parity test |
| FR-13 (selection + bulk-actions) | AC-10 | Stories 3.11–3.12 | `data-table-bulk-actions.test.tsx` (new) | ui-architecture.md |
| FR-14 (column visibility) | AC-11 | Story 3.13 | `data-table-column-visibility.test.tsx` (new) | ui-architecture.md |
| FR-15 (density toggle) | (visual; covered by component tests) | Story 3.14 | `data-table.test.tsx` (density cases) | ui-architecture.md |
| FR-16 (keyboard nav) | AC-12 | Story 3.15 | `data-table.test.tsx` (keyboard cases) | ui-architecture.md |
| FR-17 (source-of-truth lint guard) | AC-16 | Story 3.16 | `data-table-column-discipline.test.tsx` | CLAUDE.md cross-ref |
| (8 table migrations) | AC-1 through AC-15 (all migrated tables exercised) | Stories 4.1–4.8 (one per migrated table) | E2E specs + per-table component tests | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All AC-1 through AC-16 pass in CI (component, integration, contract, E2E).
- [ ] All test layers green (unit/integration/contract/E2E).
- [ ] All 6 Alembic migrations round-trip clean (asserted in integration tests).
- [ ] Documentation updates merged: api-conventions.md, ui-architecture.md, data-model.md, CLAUDE.md.
- [ ] CI pipeline green on the feature branch's final commit.
- [ ] Gemini Code Assist findings adjudicated.
- [ ] Final GPT-5.5 review pass clean.
- [ ] No open questions remain in §19.
- [ ] Operator manual verification: `make up` → register a cluster → search by name in `/clusters` DataTable → result returns.

## 19) Open questions and decision log

### Open questions

None. The idea preflight (2026-05-15) locked all 5 decision forks (TanStack Table engine; selection in Phase 1; Postgres FTS + 6 migrations; single-PR delivery; canonical URL-state encoding). The spec inherits those locks verbatim.

### Decision log

- **2026-05-15** — TanStack Table 8.x as the headless engine (Locked Decision #1) — battle-tested + headless + built-in sort/filter models; alternative was a custom sort/filter implementation but estimated cost too high vs. the ~30KB dep.
- **2026-05-15** — Selection + bulk-actions in Phase 1, not deferred (Locked Decision #2) — semantics (select-all-on-page, clears-on-cursor-move) are easier to design in than to retrofit.
- **2026-05-15** — Postgres FTS over ILIKE (Locked Decision #3) — ranked results + phrase matching come for free; one-time migration cost on 6 tables; proposals deferred-to-filter-chips (no natural text column).
- **2026-05-15** — Single-PR atomic delivery (Locked Decision #4) — operator directive 2026-05-15; reviewer navigation via tight commit boundaries inside the PR.
- **2026-05-15** — Single canonical URL-state encoding `?sort=<col>:<asc|desc>&<col>=<v>&q=<text>&cursor=<...>` (Locked Decision #5) — uniform muscle memory across all DataTable consumers; existing per-page wire shapes (`?status=`, `?source=`, `?cluster_id=`) preserved because the column id IS the param name in those cases.
- **2026-05-15** — Drop FTS for proposals; expand filter chips instead (preflight finding) — proposals has no natural text column; denormalizing template/cluster names would require sync triggers; chip filtering is the operator-equivalent affordance.
- **2026-05-15** — `?since=` added to judgment-lists + conversations endpoints in scope (preflight finding) — closes pre-existing drift from api-conventions.md "MUST accept `?since=`" requirement; ~2 LOC each.
