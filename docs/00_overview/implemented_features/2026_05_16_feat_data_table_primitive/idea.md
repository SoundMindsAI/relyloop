# feat — shared `<DataTable>` primitive (sort + filter + text search + URL state)

**Date:** 2026-05-15
**Preflighted:** 2026-05-15 — verified all 9 table-component paths, all 8 list-endpoint router paths, Alembic head (`0007_conversations_messages` → next is `0008`); recounted searchable-resources from 7 down to **6** after discovering `proposals` has no natural text column for FTS (`template_id` + `cluster_id` are FKs, not text); audited the 9th table (`studies-by-cluster-table.tsx`) — it's a thin wrapper around `studies-table.tsx`, no separate migration needed; verified `@tanstack/react-query` is installed but `@tanstack/react-table` is not (latest stable is `~8.21.3`); confirmed every cited column (`clusters.name + base_url`, `studies.name + target`, `conversations.title`, `query_sets.name`, `query_templates.name`, `judgment_lists.name`) exists in the ORM models. Locked decision #3 updated to drop FTS for proposals (use expanded filter chips instead).
**Status:** Idea — initiated after the contextual-help work surfaced an inconsistent-table-affordances gap. User invoked it the same day as `feat_contextual_help` Phases 1–3 shipped (PRs #122 / #124).
**Origin:** Conversation on 2026-05-15 after Phase 2 + 3 merged. The operator asked "do we have UI guidance for tables? All tables should include filtering (common options + text entry) and sortable columns." Audit showed 8 list-shaped tables in the codebase with sharply inconsistent affordances (only 1 sortable, 3 with filter chips, 0 with text search), and no project doc codifying the rule.
**Depends on:** Phase 1 of `feat_contextual_help` (shipped, PR #122) — the `InfoTooltip` / `HelpPopover` primitives will be reused inside `DataTable` column-header help where the column maps to a backend enum.

## Problem

9 list-shaped surfaces exist today, each with hand-rolled affordances:

| Table | Filter chips | Sortable cols | Text search | Pagination |
|---|---|---|---|---|
| [`studies-table.tsx`](../../../../ui/src/components/studies/studies-table.tsx) | Status (URL-backed via `studies-page`) | ❌ | ❌ | Cursor |
| [`proposals-table.tsx`](../../../../ui/src/components/proposals/proposals-table.tsx) | Status + Source (URL-backed) | ❌ | ❌ | Cursor |
| [`judgments-table.tsx`](../../../../ui/src/components/judgments/judgments-table.tsx) | Source (all/llm/human, React state) | ❌ | ❌ | partial |
| [`trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) | ❌ | ✅ 5 sort keys via `<Select>` | ❌ | Cursor |
| [`queries-table.tsx`](../../../../ui/src/components/query-sets/queries-table.tsx) | URL `?since=` only | ❌ | ❌ | Cursor |
| [`clusters-table.tsx`](../../../../ui/src/components/clusters/clusters-table.tsx) | ❌ | ❌ | ❌ | — |
| [`query-sets-table.tsx`](../../../../ui/src/components/query-sets/query-sets-table.tsx) | ❌ | ❌ | ❌ | — |
| [`templates-table.tsx`](../../../../ui/src/components/templates/templates-table.tsx) | ❌ | ❌ | ❌ | — |
| [`studies-by-cluster-table.tsx`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx) | inherits from `studies-table` | inherits | inherits | inherits |

The 9th (`studies-by-cluster-table.tsx`) is a thin wrapper around `studies-table.tsx` filtered by `cluster_id` — migrating `studies-table` cascades to it automatically, no separate work needed.

Only **`trials-table` is sortable** — and it uses a separate `<Select>` rather than the click-the-column-header convention users expect. **Zero tables support text search.** Filter-chip implementations are inconsistent (some URL-backed for back-button + shareable links, some React-state-only). Empty-state copy doesn't distinguish "no rows match filter" from "no rows exist" except on `studies-empty`.

The backend pagination contract is already uniform per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md): every list endpoint accepts `cursor` + `limit` + per-resource filters, returns `{ data, next_cursor, has_more }`, and emits the `X-Total-Count` header. The frontend's only consumer of `X-Total-Count` today is the dashboard count-cards; tables themselves don't display "Showing 1–50 of 312". The contract is already there — the UI just isn't using it.

No project doc codifies "all tables must…". CLAUDE.md §"Common UI Patterns" mentions detail modals, cursor pagination, and filter-chip allowlist grounding — but nothing about sortable columns, text search, density, column visibility, or selection. [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) example-mentions `<TrialsTable sortBy={...} onSort={...}>` without enforcing a project-wide contract.

## Proposed capability

A shared `<DataTable>` primitive at `ui/src/components/common/data-table.tsx` (and a small set of co-located pieces — `DataTableToolbar`, `DataTableEmpty`, `useDataTableUrlState`) that the 8 existing tables migrate to, plus all future tables.

The primitive is **column-config-driven** (the consumer supplies a typed column definition; the primitive renders the table) and **headless about server state** (the consumer provides a TanStack Query hook that takes `{ cursor, limit, sort, filters, q }` and returns `{ data, totalCount, has_more, next_cursor }`). The primitive contributes the table chrome — sortable header clicks, filter chips, debounced text-search input, total-count display, density toggle, column-visibility menu, sticky header, URL state sync — but knows nothing about specific resources.

### Capabilities (all in scope — single PR per locked decision #4)

Per the locked-max-capability directive (2026-05-15), all 13 capabilities ship **atomically in one PR**. The primitive, the ~8 Alembic FTS migrations, the backend `?q=` endpoint changes, and the 8-table migration all land in the same PR. No partial state where the primitive exists but consumers haven't been migrated yet; no partial state where some tables have search and others don't.

1. **Sortable column headers.** Each column declares `sortable: true` and a `sortKey` (the wire value the backend accepts). Clicking the header cycles `asc → desc → unsorted` and updates the URL `?sort=` param. Visible affordance: chevron-up/down/none next to the header text. TanStack Table's sort state model (locked decision #1) handles the cycling.
2. **Filter chips backed by backend enums.** Each filterable column declares `filter: { kind: 'enum', wireValues: STUDY_STATUS_VALUES, sourceOfTruth: 'backend/...py Symbol' }`. The primitive renders a chip row above the table; chips serialize to URL `?<column>=`. Source-of-truth comment is mandatory (extends the existing [`enums.ts`](../../../../ui/src/lib/enums.ts) discipline).
3. **Debounced text search via Postgres FTS.** A search input above the table. 300ms debounce. Sends `?q=<text>` to the backend; backend converts to `plainto_tsquery` against a generated `tsvector` column (locked decision #3). Results ranked by `ts_rank` desc. `min_length=2` validation on both sides.
4. **Total-count display.** Top-right of the toolbar: "Showing 1–50 of 312" derived from the `X-Total-Count` header.
5. **URL-backed state.** All four signals (sort, filters, q, cursor) serialize to query params using the canonical encoding (locked decision #5). Back button works; links are shareable; refresh preserves view.
6. **Two empty-state shapes.** "No rows match the current filter — [Clear filters]" vs. "No rows yet — [Primary CTA]". Consumer supplies both.
7. **Cursor pagination controls.** Prev / Next / page-size selector. Reuses the existing [`CursorPaginator`](../../../../ui/src/components/common/cursor-paginator.tsx) (now wrapped by DataTable so consumers don't import it directly).
8. **Sticky header on scroll.** One-line Tailwind addition (`sticky top-0 bg-background z-10` on the header).
9. **Tooltip-enabled column headers.** When a column maps to a backend enum (e.g., trial sort, proposal status), the column header gets an `<InfoTooltip>` reading from `ui/src/lib/glossary.ts`. Reuses the contextual-help work — no new primitives, just an opt-in prop on the column config.
10. **Multi-row selection + bulk-action toolbar.** Checkbox column on the left; "select all on page" header checkbox; bulk-action toolbar that lights up when ≥1 row is selected (locked decision #2). Selection state is React-only (never URL-encoded — anti-pattern). Semantics: selection clears when the cursor moves to another page; total-selected counter shows "5 selected on this page". Backend bulk endpoints are out of scope; the primitive exposes `selectedIds` + `clearSelection` to the consumer, which wires whichever bulk endpoint exists.
11. **Column visibility menu.** Eye-icon dropdown letting users hide/show columns. Persists to `localStorage` keyed by table id. Sticky columns (e.g., the selection checkbox, the first identifier column) are not hideable.
12. **Density toggle (comfortable/compact).** Two-position toggle in the toolbar. Persists to `localStorage`.
13. **Keyboard navigation.** Arrow keys move row focus; Enter opens detail-view via consumer-supplied `onRowActivate`; Space toggles row selection when selection is enabled. Opt out per table via `keyboardNav={false}` prop.

## Scope signals

- **Backend:** **substantial.** Three pieces:
  - **(a) `?q=` text search via Postgres FTS** on the 6 searchable list endpoints (per locked decision #3): clusters, query-sets, query-templates, studies, judgment-lists, conversations. Each adds a Pydantic `Field(min_length=2)` constraint + a `plainto_tsquery` clause against the table's `search_vector` column. ~30 LOC per endpoint × 6 endpoints = **~180 LOC** of router changes.
  - **(b) New filter-chip params for proposals** (replaces FTS for that resource, per locked decision #3): `?cluster_id=` already exists; add `?template_id=` query param. ~10 LOC in `proposals.py`. The proposals-table frontend migration adds the corresponding cluster + template filter chips.
  - **(c) Alembic migrations adding FTS infrastructure.** **6 migrations** (`0008_search_vector_clusters` through `0013_search_vector_conversations`), one per searchable table. Each adds a `search_vector` Postgres `tsvector` column (`GENERATED ALWAYS AS (to_tsvector('english', coalesce(<col_a>, '') || ' ' || coalesce(<col_b>, ''))) STORED`) + a `GIN(search_vector)` index. ~30 LOC of `op.execute()` SQL per migration. Each migration includes `downgrade()` per CLAUDE.md rule 5; round-trip verification required before merge.
- **Frontend:** primary surface. New `ui/src/components/common/data-table.tsx` (~600 LOC with selection + col-vis + density + keyboard nav all in Phase 1 per locked decision #2) + co-located `data-table-toolbar.tsx`, `use-data-table-url-state.ts` hook, `data-table-bulk-actions.tsx`, `data-table-column-visibility.tsx`, `data-table-empty.tsx`. ~6 new files + 1 vitest test file per primitive component (~5 test files). Adds `@tanstack/react-table` npm dep (locked decision #1, tilde-pin latest 8.x). The 8 existing table components migrate to the primitive in a **single bulk-migration PR** (locked decision #4) after the primitive itself lands — each table migration is ~100-200 LOC delta; the bulk PR is ~1500 LOC.
- **Migration:** **yes — 6 Alembic migrations** for the `search_vector` columns. All non-breaking (existing list endpoints still work; the new `?q=` param is optional). Revision IDs follow the sequential `00NN_<slug>` convention; current head verified at `0007_conversations_messages` so this work occupies **`0008_search_vector_clusters` through `0013_search_vector_conversations`** (6 revisions, not 8 — preflight correction).
- **Config:** none. URL state is local to the page; localStorage keys (column visibility, density) are namespaced per table id.
- **Audit events:** N/A — read-only UI; no state mutations beyond what bulk-action consumers wire to their own endpoints (and those callers handle their own audit emission when MVP2 lands).
- **CLAUDE.md absolute-rules walked:**
  - **Rule 5 (Alembic migrations include `downgrade()` + round-trip clean)** — all 8 FTS migrations comply. The `downgrade()` drops the GIN index then the `search_vector` column.
  - **Rule "Enumerated Value Contract Discipline"** — every column with a filter chip MUST cite a backend allowlist file. The TanStack Table column-config type encodes this as a required `sourceOfTruth: string` field on `filter` definitions.
  - **API conventions** — `?q=` follows the existing pagination param naming from [`api-conventions.md`](../../../01_architecture/api-conventions.md). New header semantics: continue returning `X-Total-Count` (already universal); add nothing.
  - **No other rule activates.** Pre-MVP2, so audit_log doesn't apply.

## Why now (vs. later)

- The 8 inconsistent tables compound every time a new screen ships. Phase 2 of `feat_contextual_help` already added a 9th filter pattern (the source-filter row on judgments-table) that the primitive would have absorbed. The next feature in this area will be the 10th.
- The contextual-help work just shipped the conventions this primitive consumes (glossary, source-of-truth comments, `InfoTooltip` for enum-backed columns). Building DataTable while those patterns are fresh keeps the design coherent.
- The backend `?q=` addition is genuinely cross-cutting work; doing it once for the DataTable rollout is cheaper than retrofitting search to each table separately later.
- **Sized vs. /pipeline:** ~2500 LOC across primitive + 8 Alembic migrations + 8 list-endpoint changes + 8 table-consumer migrations. Single PR per operator directive (locked decision #4). Warrants a full spec + plan via `/pipeline` — significantly larger than `feat_contextual_help` (which was ~3500 LOC across three PRs); this is roughly 2/3 of that volume in **one** PR, so the implementation plan must enforce tight per-commit scope so reviewers can navigate.

## Locked decisions (operator directive 2026-05-15: maximize capability)

1. **TanStack Table as the headless engine.** Battle-tested, ~30KB gz, headless (no styling — composes with shadcn). Built-in support for multi-column sort priority, column resizing, advanced filter models, and virtualization for large pages — all of which we'd reinvent if we built custom. New npm dep: **`@tanstack/react-table@~8.21.3`** (latest stable as of 2026-05-15; verified during preflight).

2. **Selection + bulk actions land in Phase 1, not Phase 2.** Checkbox column on the left, "select all on page" header checkbox, bulk-action toolbar that lights up when ≥1 row is selected. Semantics (select-all-on-page, undefined-across-pagination — when the cursor moves to page 2, the selection clears for that page; total-selected counter shows "5 selected on this page") are easier to get right when designed in than retrofitted. The primitive only manages `selectedIds` state — backend bulk endpoints are still out of scope, but consumers can wire `onBulkAction` to whatever endpoint they have.

3. **Postgres full-text search on 6 searchable resources, not ILIKE.** Each searchable table gets a generated `tsvector` column populated from its canonical name + secondary searchable fields (preflight-verified column inventory):

   | Resource | `search_vector` source columns |
   |---|---|
   | clusters | `name` + `base_url` |
   | query_sets | `name` |
   | query_templates | `name` |
   | studies | `name` + `target` |
   | judgment_lists | `name` + `target` |
   | conversations | `coalesce(title, '')` (title is nullable per `conversation.py:Mapped[str \| None]`) |

   GIN index on each `tsvector`. **6 Alembic migrations** (`0008_search_vector_clusters` through `0013_search_vector_conversations`), each ~30 LOC of `op.execute()` SQL. Frontend sends `?q=<text>`; backend converts to `plainto_tsquery` (safe against arbitrary user input) and orders by `ts_rank` desc. Ranked results + phrase matching come for free; the cost is the migration surface, which is a one-time hit.

   **Proposals get NO FTS** (preflight finding): the `proposals` table has no natural text column — `template_id` + `cluster_id` are UUID FKs, and denormalizing the resolved names onto proposals would require sync triggers when the source rows change (heavy). The proposals list already has working filter chips on status + source; preflight recommends adding a **cluster filter chip** (cluster_id is already in the schema) and a **template-name filter chip** to that page as the equivalent affordance. Trials similarly gets no FTS — search would be redundant given trial rows are sequence-numbered within a single study.

4. **One single PR — primitive + backend FTS + all table migrations land atomically.** No phased shipping; no "primitive first, migrations later"; no "land the primitive and migrate tables one at a time over weeks". Everything ships together in one PR with one Gemini cycle, one final-review cycle, one CI run. Operator directive 2026-05-15. **Revised diff estimate (preflight):** ~600 LOC new primitive infra + ~6 test files + **6 Alembic migrations** (~30 LOC each = ~180 LOC) + **~180 LOC backend `?q=` router changes** + ~10 LOC backend proposals filter-chip params + ~1500 LOC of frontend table-component migrations (covers all 8 standalone tables; the 9th `studies-by-cluster-table` inherits) = **~2400 LOC** total. Large but reviewable as long as it's organized into commit boundaries that map to the work units (one commit per primitive sub-component; one commit per Alembic migration; one commit per migrated table). The implementation plan locks the commit boundaries explicitly.

5. **Single canonical URL-state encoding across all DataTables.** `?sort=<col>:<asc|desc>&<col>=<value>&q=<text>&cursor=<...>`. Every DataTable uses the same shape so users develop muscle memory. The existing per-page URL patterns (`/studies?status=`, `/proposals?status=`) keep working because the column id IS `status` in those cases — the migration is a no-op for shareable URLs.

## Relationship to other work

- [`feat_contextual_help` Phase 1](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/) — provides `InfoTooltip` / `HelpPopover` + `ui/src/lib/glossary.ts` source-of-truth pattern that DataTable reuses for column-header help.
- [`feat_contextual_help` Phases 2 + 3](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help_mvp2/) — established the "every enum-backed UI element cites its backend allowlist" discipline that DataTable extends to filter chips.
- [`api-conventions.md`](../../../01_architecture/api-conventions.md) — defines the cursor pagination + `X-Total-Count` contract DataTable consumes. The `?q=` addition extends this doc.
- [`enums.ts`](../../../../ui/src/lib/enums.ts) — source-of-truth file for filter-chip wire values.
- All 8 existing table components — DataTable's eventual consumers. Each migration is its own follow-up PR.
- Future tables (audit log timeline at MVP2; admin user-list at MVP4; tenant switcher at MVP4) — they'll consume DataTable from day one rather than spawning a 9th, 10th, 11th hand-rolled pattern.

## Anti-patterns to call out in the spec

- **Do not** make DataTable own server state. It's a presentation primitive that takes data + signals from the consumer's TanStack Query hook. Otherwise the consumer can't share state with sibling components, and the primitive becomes the bottleneck.
- **Do not** wire selection state to URL params. Selection is ephemeral by design; persisting "5 rows selected" to a URL is a misfeature (the URL is stale the moment a row gets added/removed). Selection lives in React state only.
- **Do not** let `?q=` send shorter than 2 characters to the backend. Below that, every page-load triggers a useless full-table-scan. Frontend validates `min_length=2` AND the backend Pydantic `Field` enforces the same constraint.
