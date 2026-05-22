# Feature Specification — Home-page first-run demo nudge

**Date:** 2026-05-21
**Status:** Draft
**Owners:** Product: soundminds.ai; Engineering: relyloop-mvp1
**Related docs:**
- [idea.md](idea.md)
- [phase2_idea.md](phase2_idea.md) — deferred Phase 2 (reseed endpoint)
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- Auto-seed predecessor: PR #182 ([`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) + [`scripts/install.sh`](../../../../scripts/install.sh) step 8)
- Coordinates with: `feat_contextual_help_mvp2` Phase 3's [`StartHereChecklist`](../../../../ui/src/components/dashboard/start-here-checklist.tsx)

**Depends on:** PR #182 (auto-seed of meaningful demo data on `make up`). No backend planned-feature folder exists for it because it shipped in-line. Phase 1 of this spec adds zero backend code and does not require any new migration; it relies only on the existing `GET /api/v1/clusters?limit=200` endpoint to read the 4 demo slugs that PR #182 inserts.

---

## 1) Purpose

- **Problem:** PR #182 auto-seeds 4 meaningful demo *clusters + query sets + judgment lists + completed studies + digests + pending proposals* (per [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) module docstring) into a fresh stack so the dashboard isn't empty. But (a) nothing on the home page tells the operator that those clusters and studies are demos rather than their own work, and (b) the existing [`StartHereChecklist`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) auto-hides on a freshly-seeded stack (because all three of its "done" gates are already non-empty — clusters, judgment lists, *and* studies all exist post-seed), so the operator lands on a populated dashboard with no in-UI explanation of where the data came from.
- **Outcome:** An operator landing on a freshly-seeded stack sees an unambiguous banner above the dashboard's empty/populated content that names the present demo clusters, explains they ship with realistic queries + judgments + a winning study + a pending proposal, and offers a deep link to the create-study flow on `/studies`. Demo-tagged cluster rows are visually distinct (small "Demo" badge or `" (Demo)"` text suffix, depending on the surface's primitive) in cluster lists and pickers, so operator-authored data never gets confused with seed data. The banner stays visible until the operator explicitly dismisses it; dismissal is sticky per-browser via localStorage.
- **Non-goal:** This spec does NOT implement the "Reset to demo state" UI affordance (capability C in the idea). C is deferred to [`phase2_idea.md`](phase2_idea.md) because reseeding from inside the API container requires extracting [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s `_psql` helper out of its `docker compose exec` shell into an async-DB-driver code path — non-trivial scope that would balloon a polish-layer PR. Operators continue to use `make seed-demo FORCE=1` from the host for now.

## 2) Current state audit

### Existing implementations

| File / component | What it does | API it uses | Notes |
|---|---|---|---|
| [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx) | Dashboard root. TanStack-Query fetches: recent studies (limit=5), open proposals count, completed-recently count, clusters count, judgment-lists count. Renders `StartHereChecklist` only when all three "loaded" queries are `isSuccess`. | `GET /api/v1/studies` (limit=5 and limit=1 for counts), `GET /api/v1/proposals?status=pr_opened&limit=1`, `GET /api/v1/clusters?limit=1`, `GET /api/v1/judgment-lists?limit=1` | The current page is built around `X-Total-Count` header reads. The new banner must use the same pattern — no new endpoints. |
| [`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx) | 3-step first-run checklist (cluster → query set + judgments → study). Returns `null` when all three gates are non-empty (line 51 early-return). | N/A — pure prop-driven component. | On a fully auto-seeded fresh stack the checklist returns `null` (clusters + judgment lists + studies all non-empty from the seed). The new banner is rendered INDEPENDENTLY of the checklist — see §11 IA. On a partial state (e.g., operator deleted the seeded studies but kept the clusters), the checklist may render its standard "step 3 unchecked" view; the banner renders too because demos are still present. |
| [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py) | Test-only endpoint surface. 1 POST (`seed-completed`) + 6 DELETEs (proposals/digests/studies/judgment-lists/query-sets/query-templates). All gated by `_require_development_env` dependency — 404 outside dev. | `Settings.environment != "development"` → 404 `RESOURCE_NOT_FOUND` | Phase 1 adds no endpoints here. Phase 2 (deferred) will add `POST /api/v1/_test/demo/reseed` under the same gate. |
| [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) | CLI script: TRUNCATEs demo tables via `docker compose exec postgres psql -c ...`, then re-creates 4 clusters + indices + docs + query templates + query sets + judgment lists + completed studies + digests + pending proposals over the `/api/v1/...` HTTP surface. `--if-empty` makes the truncate-then-seed a no-op if any cluster already exists. | Mix of `docker compose exec psql` (TRUNCATE) + HTTP POST to `/api/v1/clusters` etc. | The 4 demo slugs are hardcoded at module top (lines 127, 245, 343, 456). Phase 1 mirrors those slugs in a new `ui/src/lib/demo-data.ts` constant. The `_psql` helper at line 702 is the reason the CLI cannot be invoked from inside the API container — and the reason Phase 2 is deferred. |
| [`backend/app/db/models/cluster.py`](../../../../backend/app/db/models/cluster.py) | Cluster ORM model. Columns: `id`, `name` (unique), `engine_type`, `environment`, `base_url`, `auth_kind`, `credentials_ref`, `config_repo_id` (FK), `config_path`, `engine_config` (JSONB), `notes`, `target_filter`, `created_at`, `deleted_at`. CHECK constraints on `engine_type`, `environment`, `auth_kind`. **No `tags` column exists.** | N/A — ORM only. | Phase 1 deliberately does NOT add a `tags` column (idea Path 2). The 4 demo slugs are detected by membership check against a frontend constant — no migration, no API change. |
| [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py) | Cluster CRUD + schema + targets + run_query routers. `GET /api/v1/clusters` supports cursor pagination, `?since`, `?q`, `?sort`, `?engine_type`, `?environment` filters. Returns `ClusterListResponse` = `{data: ClusterSummary[], next_cursor, has_more}` + `X-Total-Count` header. | `_err()` helper at line 93 returns the `{detail: {error_code, message, retryable}}` envelope. | No changes in Phase 1. |
| [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) | Canonical wire-value allowlists mirroring backend Literals. CI grep gate at [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh) enforces parity. | N/A — typed `as const` arrays. | Phase 1 adds NO new entries here. Demo slugs are NOT wire values — they're frontend-only UX hints (see Anti-patterns §4). Demo slugs go in a new `ui/src/lib/demo-data.ts` file. |

### Navigation and link impact

Phase 1 adds no new routes and renames no existing routes. It adds one new inbound link.

| Source file | Current link target | New link target |
|---|---|---|
| `ui/src/components/dashboard/demo-data-banner.tsx` (new) | — | `/studies` (the existing studies-list page hosts the create-study modal trigger — see [`ui/src/app/studies/page.tsx:14`](../../../../ui/src/app/studies/page.tsx) `setCreateOpen` button; there is intentionally no `/studies/new` route) |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/tests/e2e/dashboard.spec.ts`](../../../../ui/tests/e2e/dashboard.spec.ts) | `getByTestId('start-here-checklist')` (currently asserts the checklist renders on a fresh stack) | 1 file | Add coverage for the demo-data banner: (a) renders against the auto-seeded stack regardless of the fact that the seed creates studies; (b) dismiss persists across reload via localStorage; (c) banner does NOT render when localStorage is pre-set to `'1'` via `page.addInitScript`. No self-archive assertion — the spec deliberately has no study-count-based hide rule. |
| [`ui/src/__tests__/components/dashboard/`](../../../../ui/src/__tests__/components/dashboard/) | (folder does not currently exist) | 0 | Phase 1 creates this folder with `demo-data-banner.test.tsx` and updates to any new `start-here-checklist.test.tsx` if added. |
| [`ui/tests/e2e/global-teardown.ts`](../../../../ui/tests/e2e/global-teardown.ts) | Drains seeded rows via the 6 `_test` DELETE endpoints | 1 file | No change — Phase 1 introduces no new seed-table rows. |

### Existing behaviors affected by scope change

- **`StartHereChecklist` rendering on auto-seeded stacks.** Current: on a stack where `make up` ran the auto-seed, the checklist's three gates (`hasClusters`, `hasQuerySetsWithJudgments`, `hasStudies`) are ALL non-empty (the seed creates clusters AND judgment lists AND completed studies), so the checklist's line 51 early-return fires and the checklist renders `null`. New: the banner renders **independently** of the checklist — it appears whether or not the checklist is visible, since it is gated only on demo-slug presence + localStorage. On a partial state (e.g., operator manually deleted the seeded studies), the checklist may render with step 3 unchecked; the banner renders alongside if demos are still present. Decision needed: **no** — the banner and checklist are independent components.
- **Banner visibility lifecycle.** New behavior: the banner stays visible whenever demos are present and the operator has not dismissed it. The banner does NOT auto-hide when studies exist — the seed already creates studies on day 0, so a study-count-based hide rule is unsatisfiable on the canonical fresh stack. The only sticky off-switch is explicit dismissal (FR-1, FR-7). Decision needed: **no**.
- **Demo badge in cluster pickers/lists.** Current: cluster names appear unadorned in `/clusters`, the studies cluster filter, and the create-study modal. New: rows whose name is in the demo-slug constant render a small "Demo" badge alongside the name. The wire value (`name`) is unchanged — the badge is a pure render-time treatment. Decision needed: **no**.

---

## 3) Scope

### In scope (Phase 1)

- **A: Demo-data banner** — render an explanatory card above `<StartHereChecklist />`'s slot on the dashboard when (a) at least one of the 4 demo slugs appears in the first page of clusters AND (b) the operator has not dismissed it (localStorage key not `'1'`). The banner names the present demo clusters, links to `/studies`, and is dismissable + sticky-dismissed via a safe-localStorage wrapper.
- **B (Path 2 of idea): "Demo" indicator in cluster surfaces** — three surfaces, two rendering strategies:
  - **Cluster list page** ([`ui/src/components/clusters/clusters-table.column-config.tsx`](../../../../ui/src/components/clusters/clusters-table.column-config.tsx) name column cell) — renders the JSX `<DemoBadge />` component (small chip styled via shadcn `<Badge variant="secondary">`) inline next to the row's name link.
  - **Create-study modal cluster picker** ([`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) line 506 `<EntitySelect>`) — appends a `" (Demo)"` text suffix to the `getLabel` return string when the cluster's name is in `DEMO_CLUSTER_SLUGS`. JSX is not used here because `<EntitySelect>`'s `getLabel` prop returns `string`, not `ReactNode`; extending the primitive is out of scope for Phase 1 (text suffix conveys the same signal at lower risk).
  - **Proposals-table cluster filter dropdown** ([`ui/src/components/proposals/proposals-table.column-config.tsx`](../../../../ui/src/components/proposals/proposals-table.column-config.tsx) line 100 `fk-select`) — same `" (Demo)"` text-suffix strategy because the underlying [`<DataTableFkSelect>`](../../../../ui/src/components/common/data-table-fk-select.tsx) renders a native HTML `<select>`, which cannot accept JSX children in `<option>`.
  - **NOT** rendered on the studies list page — there is no cluster filter on `/studies` (the table only filters by status); the cluster column at [`ui/src/components/studies/studies-table.column-config.tsx:25-33`](../../../../ui/src/components/studies/studies-table.column-config.tsx) renders `cluster_id` (the UUID) verbatim with no `name` lookup, so a slug-based badge cannot fire there.
- **Source-of-truth constant** at [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts): exports `DEMO_CLUSTER_SLUGS = ['acme-products-prod', 'corp-docs-search', 'news-search-staging', 'jobs-marketplace-prod'] as const`. The file carries a `// Source: scripts/seed_meaningful_demos.py SCENARIOS slugs` comment so the next operator who renames a demo knows to update both files. Comment + CI grep gate (see §14) prevent drift.

### Out of scope (Phase 1 — deferred to Phase 2)

- **C: "Reset to demo state" UI affordance + `POST /api/v1/_test/demo/reseed` endpoint.** Tracked in [`phase2_idea.md`](phase2_idea.md). Requires refactoring [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s `_psql` helper (which currently uses `docker compose exec`) into an asyncpg-friendly module callable from inside the API container.
- **Path 1 of the idea (`clusters.tags JSONB` column + `?tag=demo` filter API).** Withdrawn: the idea's `tags` column proposal was originally compelling because of a hypothetical e2e-test isolation tag (per the idea's "Compositional claim withdrawn" note), which `chore_e2e_test_rows_isolation` (PR #186) did not adopt. With no second use case for tags, the migration + new API surface is unjustified — Path 2 (hardcoded slug constant) ships the same UX for ~80 fewer backend LOC.
- **Banner copy A/B testing.** The banner text is the operator's first impression. We pick one variant in §11 and commit to it.
- **Internationalization.** RelyLoop is English-only through MVP4.

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. **No new endpoints in Phase 1.** Phase 2's `POST /api/v1/_test/demo/reseed` follows the existing `_test/` test-only convention (see `_TEST_PREFIX = "/_test"` at [`backend/app/api/v1/_test.py:37`](../../../../backend/app/api/v1/_test.py)).
- **Router namespace:** N/A in Phase 1.
- **HTTP methods:** N/A in Phase 1.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per [`backend/app/api/v1/_test.py:40-53`](../../../../backend/app/api/v1/_test.py)'s `_err()` helper. (Phase 2 will use it; Phase 1 is read-only against the existing `/clusters` endpoint.)
- **Auth error shape:** N/A in MVP1–3 (no auth surface).

### Phase boundaries

- **Phase 1 (this spec):** A (banner) + B-path-2 (badges + frontend demo-slug constant). Pure frontend, ~200 LOC + ~6 vitest cases + 1 Playwright assertion add to the existing dashboard spec. Single PR target.
  - Rationale: Path 2 + banner + badges delivers ~80% of the UX value with zero backend risk. We can ship in days, observe, and decide whether the `tags` column + reseed endpoint are still worth doing.
- **Phase 2 (deferred to [`phase2_idea.md`](phase2_idea.md)):** C (reseed endpoint + UI button). Requires extracting [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s truncate + seed orchestration into an importable Python module (`backend/app/services/demo_seeding.py`) that uses an async SQLAlchemy session for TRUNCATE instead of `docker compose exec psql`. Estimated ~250 backend LOC + ~50 frontend LOC.

**Deferred phase tracking:** Phase 2 must be tracked in [`phase2_idea.md`](phase2_idea.md), created alongside this spec.

## 4) Product principles and constraints

- **Demo data must be unambiguous.** The first thing a new operator sees on the dashboard must answer "is this real or seeded data?" without needing to click into a row.
- **Dismissable, not invasive.** The banner is informational, not action-blocking. Once dismissed, it stays dismissed (per-browser via localStorage). The badge in cluster lists persists indefinitely — the operator might forget which clusters are demos even after the banner is gone.
- **Sticky-but-dismissable, no auto-archive on first study.** The seed already creates 4 completed studies, so a "hide after first study" rule never fires on the canonical fresh stack. The only off-switch is explicit dismissal (sticky via localStorage). Demo badges remain on the demo-named cluster rows even after dismissal so the seed origin is still visible at the row level.
- **Zero backend risk in Phase 1.** No migration, no new API endpoint, no new ORM field, no new error code, no new wire-value allowlist. Phase 1 is a pure frontend layer over data that already exists.
- **No accidental gate on demo presence.** The dashboard must still render correctly on a stack where the operator deleted all demo clusters or never had any (e.g., a non-`make up` install path). The banner gracefully omits itself.

### Anti-patterns

- **Do not** add a `tags` column to `clusters` or any other ORM model — Path 1 was withdrawn (see §3 Out of scope). A migration to support 4 hardcoded names is overkill.
- **Do not** put the demo slugs in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) — that file is for wire-value allowlists with a CI source-of-truth gate. Demo slugs are UX hints, not contracts. They belong in a separate `demo-data.ts` file. Placing them in `enums.ts` would invite the CI gate at [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh) to expect a matching backend Literal — there isn't one and never should be.
- **Do not** filter the banner by `engine_type` or `environment` — the demo slugs are the only signal. An operator who renamed a demo cluster (uncommon, but possible) breaks the badge gracefully; the banner stays unless ALL 4 demos are renamed/deleted, in which case the operator has clearly moved past onboarding.
- **Do not** read every cluster page to detect demos — the first 200 rows of `GET /api/v1/clusters` is more than enough. A stack with 200+ clusters has obviously moved past the first-run state.
- **Do not** dismiss the banner via a query param or cookie — localStorage is the established pattern (see [`ui/src/components/common/data-table.tsx:116`](../../../../ui/src/components/common/data-table.tsx), [`ui/src/components/guides/guide-viewer.tsx:27`](../../../../ui/src/components/guides/guide-viewer.tsx)). The localStorage key follows the `relyloop.<feature>.<key>` namespace convention.
- **Do not** auto-open the Create Study modal when the operator clicks the banner CTA — the CTA navigates to `/studies` (where the existing page-header button opens the modal) so the operator's existing patterns (back button, deep linking) keep working. There is intentionally no separate `/studies/new` route.
- **Do not** show the badge in pages where it adds noise — operator-authored studies, proposals, digests, and trial tables all reference cluster names but the user has already chosen the cluster; surfacing "Demo" there is visual clutter. Limit the badge to cluster *pickers* and the cluster *list* page.

## 5) Assumptions and dependencies

- **Dependency:** PR #182 auto-seed (merged 2026-05-21).
  - Why required: the 4 demo cluster slugs are detected by exact-name membership. If PR #182 is rolled back, the banner will simply never render (graceful degradation — no error state).
  - Status: implemented + merged.
  - Risk if missing: zero (graceful degradation).
- **Dependency:** `GET /api/v1/clusters?limit=200` returns demo clusters in the first page.
  - Why required: the banner needs to detect at least one demo slug to render.
  - Status: implemented. `limit=200` is the documented `MAX_PAGE_LIMIT` per [`backend/app/api/v1/clusters.py:83`](../../../../backend/app/api/v1/clusters.py). On a fresh stack the 4 demos are the only rows, well within page 1.
  - Risk if missing: a stack with >200 operator-authored clusters could mask demos if they sort to the back of the default `created_at:desc` order. Demos are typically the oldest rows (created at install time) so they DO sort to the back. **Mitigation:** explicit `?sort=name:asc&limit=200` filter in the banner's query — see §7 FR-2. The 4 demo slugs cluster lexicographically (`acme-`, `corp-`, `jobs-`, `news-`) so an `asc`-by-name page always surfaces them.
- **Dependency:** [`StartHereChecklist`](../../../../ui/src/components/dashboard/start-here-checklist.tsx).
  - Why required: the spec layers a banner above the checklist; ordering matters in §11.
  - Status: implemented (`feat_contextual_help_mvp2` Phase 3).
  - Risk if missing: cosmetic only.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (per CLAUDE.md persona model). Lands on the dashboard either for the first time after `make up` or returns to a long-lived dev stack and sees the banner.
- **Role model:** N/A — single-tenant install, no auth surface. RelyLoop MVP1–MVP3 has no roles.
- **Permission boundaries:** N/A — the dashboard is unauthenticated in MVP1.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. Phase 1 introduces no state-mutating endpoints. Phase 2 (`POST /_test/demo/reseed`) WILL need an `audit_log` entry when MVP2 ships — see [`phase2_idea.md`](phase2_idea.md) §"Audit events".

## 7) Functional requirements

### FR-1: Demo-data banner rendering trigger
- Requirement:
  - The system **MUST** render the `<DemoDataBanner />` component above `<StartHereChecklist />` on the dashboard when BOTH of the following hold:
    1. The first page of `GET /api/v1/clusters?sort=name:asc&limit=200` includes at least one row whose `name` matches a value in `DEMO_CLUSTER_SLUGS`.
    2. The (try/catch-wrapped) read of `localStorage.getItem('relyloop.home-first-run-demo-nudge.dismissed')` is anything other than the literal string `'1'`. (Throws are caught and treated as "not dismissed" — see FR-7.)
  - The system **MUST NOT** render the banner if either condition is false.
  - The system **MUST** render the banner regardless of whether `<StartHereChecklist />` itself is visible (the checklist has its own auto-hide logic; the banner does not depend on it) AND regardless of whether studies, proposals, or digests already exist (the seed script creates 4 completed studies, 4 digests, and 4 pending proposals — see [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) docstring — so a study-count-based trigger would never fire on the canonical auto-seeded stack).
- Notes:
  - The localStorage key uses the `relyloop.<feature>.<key>` namespace per the existing convention at [`ui/src/components/guides/guide-viewer.tsx:27`](../../../../ui/src/components/guides/guide-viewer.tsx).
  - **Why no "studies > 0 hides the banner" rule:** the seed already plants studies, so a study-presence trigger is unsatisfiable on the very stack we most want to explain. The only sticky off-switch is explicit dismissal. Once the operator dismisses, the banner is gone permanently (per-browser); demo badges remain so the seed origin is still visible at the row level.

### FR-2: Banner data source
- Requirement:
  - The component **MUST** issue a single additional TanStack-Query call on dashboard mount via the existing exported `useClusters({ sort: 'name:asc', limit: 200 })` hook from [`ui/src/lib/api/clusters.ts:55`](../../../../ui/src/lib/api/clusters.ts). The hook's standard `queryKey` (`['clusters', { cursor, limit, since, q, sort, engine_type, environment }]`) is the contract — no custom key segment is required (and adding one would defeat TanStack Query's natural deduplication with any other dashboard consumer using the same params).
  - It **MUST** compute demo presence by calling the FR-9 helper `clusters.data.data.some(c => isDemoClusterName(c.name))` — NOT `DEMO_CLUSTER_SLUGS.includes(c.name)` directly. (The `as const` tuple's `.includes` method narrows its parameter to the literal-union type in TypeScript's default lib; passing an unknown `string` would either trigger a TS error or force an unsafe cast at every call site.)
  - It **MUST NOT** issue any new backend endpoint call. The existing `/api/v1/clusters` endpoint is sufficient.
- Notes: `sort=name:asc` is in the documented `CLUSTER_SORT_VALUES` allowlist (see [`ui/src/lib/enums.ts:144-152`](../../../../ui/src/lib/enums.ts)). `limit=200` is the documented `MAX_PAGE_LIMIT` (see [`backend/app/api/v1/clusters.py:83`](../../../../backend/app/api/v1/clusters.py)).

### FR-3: Banner content
- Requirement:
  - The banner **MUST** include:
    - A heading: `"You're set up with demo data."`
    - A body paragraph that:
      - Names exactly the demo slugs PRESENT in the cluster list at render time, each in monospace styling (e.g., `<code>acme-products-prod</code>`).
      - Uses plural-aware prefix wording per the count of present demos: 1 → `"One sample cluster — <code>…</code> — is pre-loaded …"`; 2-3 → `"<N> sample clusters — <code>…</code>, <code>…</code> — are pre-loaded …"`; 4 → `"Four sample clusters — <code>…</code>, <code>…</code>, <code>…</code>, <code>…</code> — are pre-loaded …"`.
      - Ends with `"… are pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them."`
    - An inline link to `/studies` with text `"Create your first study →"`. (The create-study flow is a modal triggered from the `/studies` page header button — there is no `/studies/new` route, see [`ui/src/app/studies/page.tsx:1-40`](../../../../ui/src/app/studies/page.tsx).)
    - A `"Dismiss"` button (`<button>` with `aria-label="Dismiss demo data banner"`) that calls the safe-localStorage helper to set `'relyloop.home-first-run-demo-nudge.dismissed' = '1'`, AND updates component state to unmount the banner immediately — the component MUST NOT depend on the localStorage write succeeding to dismiss (see FR-7).
  - The banner **MUST** be rendered as a single `<Card>` matching the visual treatment of `<StartHereChecklist>` (border + padding) but with a distinct accent color (the project's `info` / blue tone per shadcn/ui defaults) so it's visually distinguishable from the checklist's emerald-green "done" states.
- Notes: copy is committed verbatim — no inline editing during implementation. If a wording revision is needed it goes through a follow-up PR. The plural-aware prefix is implemented via a pure helper (e.g., `formatDemoClusterPrefix(slugs: string[]): string`) that lives next to the component and gets a focused unit test (see §14).

### FR-4: Demo indicator rendering
- Requirement:
  - **JSX badge surface** — the system **MUST** render a `<DemoBadge />` component inline next to the cluster name link in [`/clusters`](../../../../ui/src/app/clusters/) list table (via [`ui/src/components/clusters/clusters-table.column-config.tsx`](../../../../ui/src/components/clusters/clusters-table.column-config.tsx) `name` column `cell`).
  - **Text-suffix surfaces** — the system **MUST** append the literal string `" (Demo)"` to the human-readable label in:
    1. The create-study modal cluster `<EntitySelect>` ([`ui/src/components/studies/create-study-modal.tsx:506-514`](../../../../ui/src/components/studies/create-study-modal.tsx)). The current label is `\`${c.name} (${c.engine_type})\``; the new label is `\`${c.name} (${c.engine_type})${isDemo(c.name) ? ' (Demo)' : ''}\``.
    2. The proposals-table cluster fk-select filter ([`ui/src/components/proposals/proposals-table.column-config.tsx:39-46`](../../../../ui/src/components/proposals/proposals-table.column-config.tsx) — the `useClusters` adapter hook that maps to `{id, label}[]`). Append `" (Demo)"` to `label` when `cluster.name` is in `DEMO_CLUSTER_SLUGS`.
  - The indicator **MUST** render only when `cluster.name` is in `DEMO_CLUSTER_SLUGS` (frontend membership check; no backend signal).
  - The indicator **MUST NOT** render in the cluster detail page header, the studies-table cluster column (renders UUID), proposals-table cluster column (renders UUID), digest views, or trial views — only the three surfaces enumerated above.
- Notes: `<DemoBadge />` is a thin wrapper around the existing `<Badge variant="secondary">` from [`ui/src/components/ui/badge.tsx`](../../../../ui/src/components/ui/badge.tsx) (named component for stable `data-testid="demo-badge"` + hoverable tooltip). The text-suffix-vs-JSX split is dictated by the underlying primitives: native `<select>` rejects JSX children; shadcn `<SelectItem>` accepts JSX but `<EntitySelect>`'s `getLabel: T => string` API would need extension to pass JSX (out of scope — see §3 Out of scope). The text suffix is unambiguous and announced by screen readers.

### FR-5: Demo badge tooltip
- Requirement:
  - The badge **MUST** include an accessible tooltip (`<Tooltip>` from [`ui/src/components/ui/tooltip.tsx`](../../../../ui/src/components/ui/tooltip.tsx)) explaining what "Demo" means.
  - Tooltip text: `"Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over."` (≤200 chars; placed `top` per established tooltip patterns in shadcn/ui).
- Notes: tooltip text mentions both `make up` (auto-seed path) and `make seed-demo` (manual path) because both produce the same 4 slugs.

### FR-6: Safe-localStorage wrapper
- Requirement:
  - The component **MUST** use a small helper (e.g., `safeLocalStorageGet(key)` / `safeLocalStorageSet(key, value)`) that wraps each `window.localStorage` call in a `try/catch` AND guards by `typeof window !== 'undefined'`.
  - The wrapper **MUST** return `null` on any read failure (SSR, `localStorage` undefined, Safari private-mode QuotaExceededError, SecurityError) and **MUST** swallow write failures silently.
  - The component **MUST NOT** depend on the wrapper's success for UI state — banner visibility is held in component state initialized once from the wrapper's read; the dismiss button updates state synchronously and best-effort writes to localStorage.
- Notes: this generalizes the existing pattern at [`ui/src/components/common/data-table.tsx:123`](../../../../ui/src/components/common/data-table.tsx) (which only guards by `typeof window` and does not catch throws). Safari's private mode historically threw `QuotaExceededError` on the very first `setItem` call; modern browsers vary. The wrapper is the spec contract; the lower-risk implementation is a single ~20-line file.

### FR-7: localStorage dismissal contract
- Requirement:
  - The dismissal key **MUST** be the literal string `relyloop.home-first-run-demo-nudge.dismissed`.
  - The dismissed value **MUST** be the literal string `'1'`. Any other value (including `'true'`, `'yes'`, or absent, or any read failure per FR-6) **MUST** be treated as "not dismissed".
  - SSR safety **MUST** be provided via FR-6's wrapper — direct `window.localStorage` calls outside the wrapper are forbidden in this component.
- Notes: the `'1'`-only contract matches the existing codebase convention (see [`ui/src/components/guides/guide-viewer.tsx:28-29`](../../../../ui/src/components/guides/guide-viewer.tsx) for the precedent).

### FR-8: Graceful absence of demo data
- Requirement:
  - When `clusters.data` returns successfully but contains zero demo-slug matches, the banner **MUST NOT** render and **MUST NOT** log an error.
  - When `clusters.data` returns an error (network failure, 5xx), the banner **MUST NOT** render and **MUST NOT** block the dashboard from rendering the rest of its content.
- Notes: graceful degradation is the explicit design — the banner is a polish layer, not a critical path.

### FR-9: Single source-of-truth for demo slugs + type-safe membership helper
- Requirement:
  - The 4 demo slugs **MUST** be defined exactly once in the frontend at [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts) as an `as const` array named `DEMO_CLUSTER_SLUGS`.
  - The same file **MUST** export a helper `isDemoClusterName(name: string): boolean` implemented over a widened lookup (`Set<string>` built from `DEMO_CLUSTER_SLUGS`, or `(DEMO_CLUSTER_SLUGS as readonly string[]).includes(name)`). Every call site that needs to check "is this a demo?" **MUST** use this helper — not `DEMO_CLUSTER_SLUGS.includes(...)` directly.
  - The file **MUST** carry a top-of-file comment: `// Source: scripts/seed_meaningful_demos.py SCENARIOS slugs (lines 129/245/343/456)`.
  - A CI guard **MUST** verify that the 4 frontend slugs match the 4 `"slug":` literals in [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py). See §14 test strategy.
- Notes: the helper exists for TypeScript ergonomics — TS narrows `Array<'a' | 'b'>.includes(x: 'a' | 'b')` to the literal union, and passing an arbitrary `string` would either fail typecheck or require unsafe casts at every call site. The helper widens once at the boundary. The CI guard prevents drift if a future PR adds a 5th demo scenario or renames one. The guard is a small bash script under [`scripts/ci/`](../../../../scripts/ci/) following the precedent at [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../scripts/ci/verify_enum_source_of_truth.sh).

## 8) API and data contract baseline

### 8.1 Endpoint surface

**Phase 1 introduces no new endpoints.** The banner reads `GET /api/v1/clusters?sort=name:asc&limit=200` (existing). The badge is pure frontend.

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| (none in Phase 1) | — | — | — |

Phase 2's `POST /api/v1/_test/demo/reseed` is documented in [`phase2_idea.md`](phase2_idea.md).

### 8.2 Contract rules

N/A — Phase 1 introduces no new contracts.

### 8.3 Response examples

N/A — Phase 1 introduces no new endpoints. The existing `GET /api/v1/clusters` response shape (per [`backend/app/api/v1/schemas.py:160-165`](../../../../backend/app/api/v1/schemas.py)) is consumed unchanged.

### 8.4 Enumerated value contracts

**No new wire-value allowlists.** The `DEMO_CLUSTER_SLUGS` constant is a frontend-only UX hint — slugs are NOT validated by the backend (cluster `name` is `Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")` per [`backend/app/api/v1/schemas.py:63`](../../../../backend/app/api/v1/schemas.py); the 4 demo slugs match this pattern but they are not an allowlist).

To keep the demo-slug contract auditable, the CI guard described in FR-9 enforces equality between:

| Field | Accepted values (exact) | Source of truth | Frontend call site(s) |
|---|---|---|---|
| `DEMO_CLUSTER_SLUGS` (frontend constant) | `acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod` | [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) `SCENARIOS[*]["slug"]` (lines 129, 245, 343, 456) | banner copy (FR-3), badge membership check (FR-4), CI parity guard |

### 8.5 Error code catalog

**No new error codes in Phase 1.** Phase 2 will add `RESOURCE_NOT_FOUND` when the dev-env guard fails on the new endpoint, reusing the existing code from [`backend/app/api/v1/_test.py:69`](../../../../backend/app/api/v1/_test.py).

## 9) Data model and state transitions

### New/changed entities

**Phase 1 adds no new tables, no new columns, no new migration.** Phase 2 may or may not require a migration depending on the seed-orchestration design chosen at plan time (see [`phase2_idea.md`](phase2_idea.md)).

### Required invariants

- **`DEMO_CLUSTER_SLUGS` equals `scripts/seed_meaningful_demos.py SCENARIOS slugs`.** Enforced by CI guard (FR-9). Drift fails CI.
- **Banner trigger is read-only.** No mutation of any DB row or any backend state from the banner's render path.

### State transitions

The banner has two states, driven by data + localStorage:

```
HIDDEN  (no demo slugs in cluster fetch, OR fetch failed, OR dismissed=='1')
   ↑                                                    ↓ demos present AND !dismissed
   ↓ click Dismiss (sets localStorage and unmounts)
VISIBLE
```

There is intentionally no "first study created" state — the seed creates studies on day 0 (FR-1 Notes). Demo badges (FR-4) are unaffected by banner state.

### Idempotency/replay behavior

N/A — no events, no mutations.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Demo data confused with production data.** A new operator might think the 4 demo clusters are real and study them as if for production. Mitigation: the banner's headline (`"You're set up with demo data."`) + the per-row "Demo" badge make the seed origin unmissable.
  2. **localStorage poisoning.** A malicious page on the same origin could pre-set the dismissal key to hide the banner. Impact: low — the banner is an onboarding nudge, not a security control. Mitigation: none required.
  3. **Slug-rename drift.** If a future PR renames `acme-products-prod` in the seed script but forgets the frontend constant, the badge silently disappears from that cluster. Mitigation: CI guard in FR-9.
- **Controls:** N/A — no auth, no PII, no secrets touched.
- **Secrets/key handling:** N/A.
- **Auditability:** N/A — no state mutations in Phase 1.
- **Data retention / deletion / export impact:** localStorage entries are user-local, no server-side retention concerns. The dismissal key is opaque text, not PII.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** dashboard root (`/`). The banner renders inside `<main>`, between the dashboard heading block and the existing `<StartHereChecklist>` placement (see [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx) lines 76-102). It is the first interactive element below the page heading.
- **Labeling taxonomy:**
  - Banner heading: `"You're set up with demo data."`
  - Banner body — plural-aware variants per the count of demo slugs present at render time (see FR-3):
    - **K=4 (canonical fresh stack):** `"Four sample clusters — acme-products-prod, corp-docs-search, news-search-staging, jobs-marketplace-prod — are pre-loaded with realistic queries, judgments, a winning completed study, and a pending proposal. Run your own optimization against any of them."`
    - **K=2 or K=3:** `"<N> sample clusters — <comma-joined slugs> — are pre-loaded …"` (rest of the sentence identical).
    - **K=1:** `"One sample cluster — <slug> — is pre-loaded …"` (`"cluster"` singular, verb `"is"`).
  - Primary CTA: `"Create your first study →"` (links to `/studies` — host of the create-study modal trigger).
  - Secondary CTA: `"Dismiss"` (sets localStorage; no navigation).
  - Badge label: `"Demo"`.
  - In-modal label suffix (create-study + proposals filter): `" (Demo)"` appended after the existing label text.
- **Content hierarchy:**
  1. Banner (this spec) — most prominent, first-time visitors only.
  2. `StartHereChecklist` (existing) — step-by-step guide; hides once all steps are done.
  3. Open-proposals + completed-recently `<CountCard>` row (existing).
  4. Recent studies card (existing).
- **Progressive disclosure:** the banner is a single card with everything in view. No collapse/expand. Dismissal is the only progressive action.
- **Relationship to existing pages:** the banner is **additive** above `StartHereChecklist`. It does NOT replace the checklist on any code path. The checklist's existing line 51 auto-hide is unchanged.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| `<DemoBadge>` | `"Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over."` | hover / focus | top |
| `"Dismiss"` button | `"Hide this banner in this browser. Clear browser storage to show it again."` | hover / focus | bottom |

The Dismiss tooltip describes the actual contract: dismissal is per-browser-storage. `make seed-demo FORCE=1` does NOT clear the localStorage key (the operator must clear it manually, e.g., via browser dev tools). Phase 2's reseed UI MAY adopt a "Reseed + show banner again" pattern that clears the key as a side effect; this is out of scope for Phase 1.

### Primary flows

1. **First-run after `make up`** (the bulk of the value):
   - Operator runs `make up`. Auto-seed plants 4 demos (clusters + query sets + judgment lists + completed studies + digests + pending proposals).
   - Operator opens `/`. Sees: page heading → demo banner (visible — demos present, never-dismissed) → `<StartHereChecklist>` returns `null` (all three gates already non-empty thanks to the seed) → 4 open proposals + 4 studies-completed count cards → 4 recent-seed studies in the card grid.
   - Operator clicks the banner's `"Create your first study →"` CTA, navigates to `/studies`, clicks the page-header `"Create study"` button, the modal opens with the 4 demo clusters labeled `"<slug> (<engine>) (Demo)"` in the cluster picker.
   - Operator picks a demo (or their own cluster), fills out the form, submits. Banner stays visible until the operator explicitly dismisses it.

2. **Operator dismisses without acting:**
   - Operator clicks "Dismiss". Banner unmounts. localStorage key is set.
   - Subsequent dashboard visits skip the banner indefinitely, even on the same demos-present state.
   - Reset via browser dev-tools `localStorage.removeItem('relyloop.home-first-run-demo-nudge.dismissed')` is the only recovery path. Phase 2's reseed UI button can optionally also clear the key — out of scope here.

3. **Operator deletes all demos:**
   - Operator deletes all 4 demo clusters via `/clusters/:id`. Now `clusters` is empty.
   - Dashboard re-fetches. Banner trigger (FR-1) fails on condition 2 (no demo slugs in cluster list). Banner does not render. Badge invisible everywhere.
   - `<StartHereChecklist>` returns to its full 3-step state with step 1 unchecked.
   - No error states. The operator has successfully exited the demo state.

### Edge / error flows

- **Cluster fetch fails (5xx, network):** banner does not render (FR-8). Existing dashboard error path is unchanged.
- **localStorage unavailable** (private-browsing in some browsers): the banner reads it via the SSR-safe guard (FR-7). If `window.localStorage` is missing, treat as "not dismissed" and render the banner. The Dismiss button still runs but the setItem call no-ops; banner re-renders on next mount.
- **Slug deleted then re-created with a different name:** the new name does not match `DEMO_CLUSTER_SLUGS`, so the banner counts that demo as absent. The other 3 demos can still trigger the banner. The badge will not show on the renamed cluster — operator owns the rename.
- **More than 200 clusters:** the banner's `?sort=name:asc&limit=200` does NOT paginate. If demos are not in the first 200 lexicographically-sorted names, the banner doesn't render. Mitigation: the 4 demo slugs (`acme-`, `corp-`, `jobs-`, `news-`) sort to positions 1–4 in any list including operator names starting with the same prefixes is extremely unlikely on a freshly-bootstrapped stack. A stack with 200+ operator-authored clusters is far past first-run anyway.
- **Operator renames a demo cluster but doesn't delete it:** the cluster's `name` no longer matches `DEMO_CLUSTER_SLUGS`. Badge disappears for that one cluster. If at least one other demo still has its original slug, the banner renders with the remaining 3 names. If all 4 are renamed, the banner does not render. Both behaviors are acceptable — slug rename is a signal the operator no longer treats it as a demo.

## 12) Given/When/Then acceptance criteria

### AC-1: Banner renders on a freshly auto-seeded stack
- **Given** the dashboard `/` is loading
- **And** `GET /api/v1/clusters?sort=name:asc&limit=200` returns at least one row whose `name` is in `DEMO_CLUSTER_SLUGS`
- **And** the safe-localStorage read of `'relyloop.home-first-run-demo-nudge.dismissed'` returns `null` (key absent or unreadable)
- **When** the page renders
- **Then** the `<DemoDataBanner data-testid="demo-data-banner">` is visible
- **And** its heading text is exactly `"You're set up with demo data."`
- **And** its body lists every present demo slug in `<code>` formatting using the FR-3 plural-aware prefix
- **And** the banner is rendered EVEN IF `GET /api/v1/studies?limit=5` returns a non-zero `X-Total-Count` (because the seed already creates studies)

### AC-2: Plural-aware banner copy
- **Given** the dashboard renders with `K` demo clusters present in the first cluster page (`K ∈ {1, 2, 3, 4}`)
- **When** the banner body renders
- **Then** the body text matches the FR-3 prefix variant for `K`: exactly one slug listed for `K=1` ("One sample cluster"), exactly `K` slugs listed and the word `"clusters"` plural for `K>=2`, with `"Four"` spelled out only when `K === 4`.

### AC-3: Dismiss button persists across reload
- **Given** the dashboard state from AC-1, with the banner visible
- **When** the operator clicks the `"Dismiss"` button
- **Then** `localStorage['relyloop.home-first-run-demo-nudge.dismissed']` is set to `'1'`
- **And** the banner unmounts immediately
- **And** on a subsequent `window.location.reload()` with the same state, the banner does NOT render

### AC-4a: Demo badge renders in cluster list
- **Given** the operator is on `/clusters`
- **And** the cluster list includes at least one row whose `name` is in `DEMO_CLUSTER_SLUGS` (e.g., `acme-products-prod`)
- **When** the row renders
- **Then** a `<DemoBadge data-testid="demo-badge">` is present in the row's name cell
- **And** rows whose name is NOT in `DEMO_CLUSTER_SLUGS` do NOT render a `<DemoBadge>`

### AC-4b: " (Demo)" suffix renders in create-study modal cluster picker
- **Given** the create-study modal is open on step 1 with the cluster `<EntitySelect>` populated
- **And** the cluster list includes `acme-products-prod` (engine_type `elasticsearch`)
- **When** the operator opens the dropdown
- **Then** the `<SelectItem>` for that cluster's text content includes the literal substring `"acme-products-prod (elasticsearch) (Demo)"`
- **And** non-demo clusters render as `"<name> (<engine_type>)"` with no `" (Demo)"` suffix

### AC-4c: " (Demo)" suffix renders in proposals-table cluster filter
- **Given** the operator is on `/proposals`
- **And** the cluster fk-select filter is populated via `useClusters({ limit: 200 })`
- **When** the operator opens the cluster filter dropdown
- **Then** each `<option>` whose underlying cluster `name` is in `DEMO_CLUSTER_SLUGS` carries a text label ending with `" (Demo)"`
- **And** non-demo `<option>`s render without the suffix

### AC-5: Demo badge tooltip
- **Given** a `<DemoBadge>` is visible
- **When** the operator hovers (or focuses) the badge
- **Then** a tooltip appears with text matching: `"Pre-loaded by 'make up' or 'make seed-demo'. Has realistic queries + judgments + a winning study. Safe to delete with 'make seed-demo FORCE=1' to start over."`

### AC-6: Banner does NOT render when localStorage dismissed
- **Given** demo clusters present AND the safe-localStorage read returns `'1'`
- **When** the dashboard renders
- **Then** `<DemoDataBanner>` does NOT render
- **And** the `StartHereChecklist` continues to render per its own visibility logic (unchanged by this feature)

### AC-7: Banner does NOT render on a stack with no demo data
- **Given** `GET /api/v1/clusters?sort=name:asc&limit=200` returns rows whose names are all outside `DEMO_CLUSTER_SLUGS` (study count is irrelevant — could be 0, 1, or many)
- **When** the dashboard renders
- **Then** `<DemoDataBanner>` does NOT render
- **And** no error is logged

### AC-8: Graceful degradation on cluster fetch error
- **Given** `GET /api/v1/clusters?sort=name:asc&limit=200` returns a 5xx (study count is irrelevant — banner is gated only on cluster fetch success + demo presence)
- **When** the dashboard renders
- **Then** `<DemoDataBanner>` does NOT render
- **And** the dashboard's existing "Backend unreachable" empty state behavior is unaffected (still gated on `allFailed`)

### AC-9: CTA navigates to Studies list
- **Given** the banner is visible
- **When** the operator clicks the `"Create your first study →"` CTA
- **Then** the browser navigates to `/studies` (where the existing "Create study" header button opens the create-study modal — there is no dedicated `/studies/new` route)
- **And** localStorage is NOT modified (the CTA is not equivalent to dismissal)

### AC-10: SSR + throwing-localStorage safety
- **Given** the dashboard is rendered on the server (Next.js SSR — though the dashboard is `'use client'`, the demo banner must still survive being imported by SSR-rendered ancestors)
- **And** at runtime, `window.localStorage.getItem` and `setItem` are stubbed to throw `QuotaExceededError`
- **When** the component reads then writes the dismissal key
- **Then** neither call propagates an exception (the safe-localStorage wrapper catches both)
- **And** the banner still unmounts when Dismiss is clicked (component state, not localStorage, drives unmount)

### AC-11: CI guard catches drift between frontend constant and seed script
- **Given** a PR that modifies [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) `SCENARIOS[i]["slug"]` without updating [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts) `DEMO_CLUSTER_SLUGS`
- **When** CI runs the new `scripts/ci/verify_demo_slug_parity.sh` guard
- **Then** the guard exits non-zero with a message naming both files

## 13) Non-functional requirements

- **Performance:** the banner adds one additional `GET /api/v1/clusters?sort=name:asc&limit=200` request on dashboard mount. Payload is bounded at ~200 cluster rows × ~600 bytes ≈ 120 KB per page. TanStack Query deduplicates concurrent observers and retains the result per the app's configured defaults (no explicit `staleTime` is set on this query — the implementation MAY add `staleTime: 60_000` for a 1-minute soft-stale window if the dashboard's request log shows excess refetches in practice). The request runs in parallel with the existing 5 dashboard queries — no blocking.
- **Reliability:** banner rendering is best-effort (FR-8). No SLO impact.
- **Operability:** no new metrics, no new alerts. The banner's render path is observable via the standard browser request logs.
- **Accessibility / usability:**
  - Banner is a `<section role="region" aria-labelledby="demo-banner-heading">` with the heading carrying `id="demo-banner-heading"`.
  - Dismiss button is a `<button>` with `aria-label="Dismiss demo data banner"`.
  - Demo badge has `aria-label="Demo cluster"` so screen readers announce the badge in context.
  - Tooltip uses Radix UI's accessible Tooltip primitive (see [`ui/src/components/ui/tooltip.tsx`](../../../../ui/src/components/ui/tooltip.tsx)).
  - Color is not the sole signal — both badge and banner carry text labels.

## 14) Test strategy requirements

| Layer | Coverage required |
|---|---|
| Unit (`backend/tests/unit/`) | N/A in Phase 1 — no backend logic changes. |
| Integration (`backend/tests/integration/`) | N/A in Phase 1 — no DB / service changes. |
| Contract (`backend/tests/contract/`) | N/A in Phase 1 — no new endpoints. |
| Vitest (`ui/src/__tests__/components/dashboard/`, `ui/src/__tests__/components/common/`) | Required. See below. |
| E2E (`ui/tests/e2e/dashboard.spec.ts`) | Required (extend existing file). See below. |
| CI guards (`scripts/ci/`) | Required: new `verify_demo_slug_parity.sh`. |

**Vitest minimum:**
1. `demo-data-banner.test.tsx` — banner renders when (demos>0, dismissed=null); does NOT render when (demos=0) or (dismissed='1'); dismiss writes localStorage AND unmounts immediately; banner survives both `typeof window === 'undefined'` AND `localStorage.getItem/setItem` throwing `QuotaExceededError`.
2. `demo-badge.test.tsx` — renders for slug in `DEMO_CLUSTER_SLUGS`; does not render for any other slug; tooltip text matches AC-5.
3. `demo-data.test.ts` — `DEMO_CLUSTER_SLUGS` is exactly the 4 expected values, in the documented order.
4. `safe-local-storage.test.ts` — the FR-6 wrapper returns `null` on SSR, returns `null` when reads throw, swallows write throws, and returns expected values on the happy path.
5. `format-demo-cluster-prefix.test.ts` — the FR-3 plural-aware prefix helper produces the exact 4 variants (K=1, K=2, K=3, K=4) per AC-2.
6. **Existing `create-study-modal.test.tsx`** (extend) — when the `clusters` query result includes a row whose `name` is in `DEMO_CLUSTER_SLUGS`, the rendered `<SelectItem>` text contains `" (Demo)"` suffix; non-demo rows do NOT carry the suffix.
7. **Existing proposals-table column-config vitest** (extend, or new file if none exists) — the `useClusters` adapter for the cluster fk-select maps demo `cluster.name` values to `label` with `" (Demo)"` suffix; non-demo names keep the bare `name` as label.

**E2E extension to `ui/tests/e2e/dashboard.spec.ts`:**
1. New spec block: on a freshly seeded stack (use existing global setup that has 4 demo clusters pre-seeded by CI), assert `getByTestId('demo-data-banner')` is visible with the expected heading AND that it remains visible even though `recent.data.totalCount > 0` (because the seed creates studies).
2. Click Dismiss, reload, assert the banner is gone.
3. Manually pre-set `localStorage['relyloop.home-first-run-demo-nudge.dismissed'] = '1'` via `page.addInitScript`, reload, assert the banner does NOT render.

**CI guard:**
1. `scripts/ci/verify_demo_slug_parity.sh` — parses `SCENARIOS[*]["slug"]` literals from [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py), parses `DEMO_CLUSTER_SLUGS` from [`ui/src/lib/demo-data.ts`](../../../../ui/src/lib/demo-data.ts), exits non-zero on mismatch. Wired into `pr.yml` after the existing `verify_enum_source_of_truth.sh` step.

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md`: add a "Demo data nudge" subsection under "Dashboard" describing the banner + badge surfaces and the `DEMO_CLUSTER_SLUGS` constant.
- `docs/03_runbooks/local-dev.md`: append a "Resetting demo state" paragraph explaining `make seed-demo FORCE=1` and clarifying that the localStorage banner-dismiss key persists across resets (this is the documented limitation that Phase 2 closes).
- `CLAUDE.md`: no changes required — the existing localStorage discipline and `relyloop.<feature>.<key>` namespace convention already cover the new key.
- No `docs/04_security/` updates (no new secrets, no auth).
- No `docs/05_quality/` updates (test conventions unchanged).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** none. The banner is gated by data (`demos > 0 && !dismissed`) — it self-rolls-out on demo-seeded stacks and is invisible on demo-less stacks. No flag.
- **Migration / backfill:** none. No schema change in Phase 1.
- **Operational readiness gates:** none beyond the standard CI green + Gemini Code Assist review.
- **Release gate:** PR-only. No staged release; this lands in `main` via the standard PR flow.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-6, AC-7 | Story 1.1 (banner trigger) | `demo-data-banner.test.tsx`, `dashboard.spec.ts` | `ui-architecture.md` |
| FR-2 | AC-1, AC-8 | Story 1.1 | `demo-data-banner.test.tsx`, `dashboard.spec.ts` | — |
| FR-3 | AC-1, AC-2, AC-9 | Story 1.2 (banner UI) + Story 1.3 (plural-aware copy helper) | `demo-data-banner.test.tsx`, `format-demo-cluster-prefix.test.ts` | — |
| FR-4 | AC-4a, AC-4b, AC-4c | Story 2.1 (cluster-list badge) + Story 2.2 (create-study modal label suffix) + Story 2.3 (proposals fk-select label suffix) | `demo-badge.test.tsx`, `clusters-data-table.spec.ts`, extended `create-study-modal.test.tsx`, extended proposals fk-select vitest | — |
| FR-5 | AC-5 | Story 2.1 | `demo-badge.test.tsx` | — |
| FR-6 | AC-10 | Story 1.4 (safe-localStorage helper) | `safe-local-storage.test.ts`, `demo-data-banner.test.tsx` (throwing-localStorage variants) | — |
| FR-7 | AC-3, AC-6, AC-10 | Story 1.1 + Story 1.4 | `demo-data-banner.test.tsx`, `dashboard.spec.ts` | — |
| FR-8 | AC-8 | Story 1.1 | `demo-data-banner.test.tsx` (error-state variant) | — |
| FR-9 | AC-11 | Story 3.1 (CI guard) | `scripts/ci/verify_demo_slug_parity.sh`, `demo-data.test.ts` | `ui-architecture.md` |

## 18) Definition of feature done

This feature (Phase 1) is complete when:

- [ ] All acceptance criteria (AC-1, AC-2, AC-3, AC-4a, AC-4b, AC-4c, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11) pass in CI.
- [ ] Vitest unit tests at `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx`, `ui/src/__tests__/components/common/demo-badge.test.tsx`, `ui/src/__tests__/lib/demo-data.test.ts`, `ui/src/__tests__/lib/safe-local-storage.test.ts`, `ui/src/__tests__/lib/format-demo-cluster-prefix.test.ts`, and the extended `create-study-modal` + proposals-fk-select tests are all green.
- [ ] Playwright E2E at `ui/tests/e2e/dashboard.spec.ts` covers banner-render-with-seeded-studies, dismiss-persistence, and pre-dismissed-on-load cases against the real backend (no `page.route()` mocking of `/api/v1/clusters`).
- [ ] `scripts/ci/verify_demo_slug_parity.sh` runs in CI and exits 0.
- [ ] Documentation updates per §15 are merged.
- [ ] [`phase2_idea.md`](phase2_idea.md) exists and tracks the deferred reseed-endpoint work.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

(none — all major design decisions are committed in §3, §4, §7)

### Decision log

- **2026-05-21** — Path 2 (frontend hardcoded slugs) chosen over Path 1 (backend `clusters.tags` column). Rationale: Path 1's original motivation (compositional reuse for `chore_e2e_test_rows_isolation`) was withdrawn by the idea author; with no second consumer for a tags column, the migration + ORM + Pydantic + filter-API LOC isn't justified for 4 stable hardcoded names. The CI parity guard in FR-9 prevents drift.
- **2026-05-21** — Capability C ("Reset to demo state") deferred to Phase 2. Rationale: implementing C from inside the API container requires extracting [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s `_psql` helper (which uses `docker compose exec`) into an asyncpg-friendly module — non-trivial scope (~250 backend LOC) that inflates a polish-layer PR. Tracked in [`phase2_idea.md`](phase2_idea.md).
- **2026-05-21** — Banner copy is committed verbatim in §11 and §FR-3. Rationale: prevents per-PR copy churn during implementation; future revisions go through a focused follow-up PR.
- **2026-05-21** — Banner uses `?sort=name:asc&limit=200` instead of relying on the dashboard's existing `?limit=1` clusters count. Rationale: the existing count query reads only `X-Total-Count` and not row contents, so it can't detect demo presence. A separate, slightly larger fetch is the cleanest path; TanStack Query caches it.
- **2026-05-21** — Demo badge surface limited to cluster list + 2 pickers. Rationale: surfacing "Demo" on studies, proposals, digests, and trial tables is visual clutter — by the time the operator is reading those, they've already chosen the cluster and the demo origin is no longer the salient question.
- **2026-05-21** — Banner trigger DROPS the "studies count == 0" condition (was in the idea; GPT-5.5 review caught it). Rationale: the auto-seed creates 4 completed studies + 4 digests + 4 pending proposals on a fresh stack — a study-count-based trigger would never fire on the very scenario we're trying to explain. The only sticky off-switch is explicit dismissal. (GPT-5.5 cycle 1, Finding #1, High.)
- **2026-05-21** — Banner CTA targets `/studies`, not `/studies/new`. Rationale: a `/studies/new` route does not exist — create-study is a modal triggered from the studies-list header (see [`ui/src/app/studies/page.tsx:14`](../../../../ui/src/app/studies/page.tsx)). (GPT-5.5 cycle 1, Finding #2, Medium.)
- **2026-05-21** — Adopt a safe-localStorage wrapper (FR-6) instead of bare `window.localStorage` calls. Rationale: Safari private mode and disabled-storage browsers throw on `setItem`/`getItem` rather than no-op; a try/catch wrapper avoids unhandled exceptions and keeps component state authoritative for visibility. (GPT-5.5 cycle 1, Finding #5, Medium.)
- **2026-05-21** — Plural-aware banner body (FR-3) via a pure helper. Rationale: hardcoding "Four sample clusters" became inaccurate if an operator deleted one demo before dismissing the banner. (GPT-5.5 cycle 1, Finding #7, Low.)
- **2026-05-21** — Demo membership goes through `isDemoClusterName(name)` helper, not direct `DEMO_CLUSTER_SLUGS.includes`. Rationale: TS's `.includes` on an `as const` tuple narrows the parameter to the literal-union type; an arbitrary `string` fails typecheck without a cast. The helper widens once at the boundary. (GPT-5.5 cycle 2, Finding #3, Medium.)
- **2026-05-21** — Scrubbed all stale "studies==0 / self-archive on first study" language from §2/§3/§4/§9/§11/§16. Single source of truth for trigger lives in FR-1 + AC-1. (GPT-5.5 cycle 2, Finding #1, High.)
- **2026-05-21** — Scrubbed remaining `/studies/new` references in §4 + §11. (GPT-5.5 cycle 2, Finding #2, Medium.)
- **2026-05-21** — Reconciled `StartHereChecklist` visibility: on the canonical auto-seeded stack the checklist returns `null` (all three gates non-empty); references to "steps 1+2 ✓, step 3 ⚪" replaced with the accurate "checklist auto-hides" description. (GPT-5.5 cycle 2, Finding #4, Low.)
