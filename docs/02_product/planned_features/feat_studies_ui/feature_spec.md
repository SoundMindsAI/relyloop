# Feature Specification — feat_studies_ui

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-22, US-23, US-24 (also touches US-5, US-14 via cluster + judgment-review surfaces)
- [docs/01_architecture/ui-architecture.md](../../../01_architecture/ui-architecture.md) — Next.js + shadcn + TanStack Query patterns
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — API contracts the UI consumes
- Depends on: [`infra_foundation`](../infra_foundation/feature_spec.md), [`feat_study_lifecycle`](../feat_study_lifecycle/feature_spec.md), [`feat_digest_proposal`](../feat_digest_proposal/feature_spec.md), [`feat_llm_judgments`](../feat_llm_judgments/feature_spec.md), [`infra_adapter_elastic`](../infra_adapter_elastic/feature_spec.md)

---

## 1) Purpose

- **Problem:** Without a UI, every operation requires curl + jq. The relevance engineer needs a dashboard for studies, a create-study form, a live trial table, a digest view with parameter-importance chart, plus the supporting screens for clusters / query sets / templates / judgment review.
- **Outcome:** A Next.js app provides 9 of the 11 MVP1 routes from [`ui-architecture.md` §"Routes (MVP1)"](../../../01_architecture/ui-architecture.md): dashboard, clusters list/detail, query sets list/detail, judgment review, templates list/editor, studies list/detail, with the digest panel rendered on the study detail page. Live trial polling at 3s intervals while studies are running.
- **Non-goal:** No chat surface (`feat_chat_agent` owns `/chat/*`). No proposals UI (`feat_proposals_ui` owns `/proposals/*`). No `/audit` viewer (MVP4). No Playwright e2e (MVP3+ or `chore_tutorial_polish`). No login / role gates (single-tenant, no auth in MVP1).

## 2) Current state audit

After dependencies ship:
- The Next.js skeleton from `infra_foundation` exists with a placeholder `app/page.tsx` ("RelyLoop is running").
- `ui/` directory has `app/`, `components/ui/` (shadcn primitives can be added on demand via `npx shadcn-ui add`), `lib/`, `tests/`.
- All MVP1 backend APIs (clusters, query-sets, query-templates, studies, judgment-lists, digests) exist via the listed dependencies.
- No production UI screens yet. This feature creates them.

## 3) Scope

### In scope

- **Layout shell** (`app/layout.tsx`): shadcn theme provider, TanStack Query provider with default `staleTime: 30s` + `refetchOnWindowFocus: true`, Toaster for error/success notifications, top-nav with links to Dashboard / Clusters / Query Sets / Templates / Studies / Proposals (link out to `feat_proposals_ui`'s routes) / Chat (link out to `feat_chat_agent`'s routes).
- **Dashboard** (`/`): Recent studies (top 5 by `created_at desc`), open proposals count, total studies-completed count. Compact cards with click-throughs to detail.
- **Clusters list** (`/clusters`): table with name / engine_type / environment / health_check.status; "Register cluster" button → modal form.
- **Cluster detail** (`/clusters/{id}`): summary card + studies-by-this-cluster table + recent run-query history (if any).
- **Query Sets list** (`/query-sets`): cards/table with name / cluster / query count; "Create query set" button → modal form (with optional CSV upload).
- **Query Set detail** (`/query-sets/{id}`): list of queries with edit/delete; associated judgment lists with status + count breakdown.
- **Judgment Review** (`/judgments/{id}`): list of (query, doc, rating, source, notes); inline override (PATCH); calibration upload modal; calibration stats display when present.
- **Templates list** (`/templates`): table with name / version / engine_type; "Create template" button → modal with Monaco-style textarea (full Monaco editor reserved for GA v1 per umbrella §28; MVP1 uses a basic syntax-highlighted `<textarea>` via `prism-react-renderer` or similar).
- **Template detail** (`/templates/{id}`): view-only of body + declared_params (editing in MVP1 means creating a NEW version via the "Fork to v+1" button — preserves immutability per `feat_study_lifecycle` semantics).
- **Studies list** (`/studies`): cursor-paginated table with name / cluster / status badge / best_metric / created_at; status filter chips; "Create study" button → multi-step form modal.
- **Study detail** (`/studies/{id}`): live (3s polling while `running`) trials table sortable by primary_metric_desc; status badge; cancel button (when running); digest panel (when completed) with narrative + Recharts horizontal bar chart for parameter_importance + top-10 trials table + "Open PR" button (links into `feat_proposals_ui` for the action — this feature renders the button but the action lives in the proposals module).
- **TanStack Query hooks** in `ui/lib/api/` for every consumed endpoint: studies, trials, query-sets, queries, query-templates, judgment-lists, judgments, clusters, digests.
- **Cross-cutting components** in `ui/components/common/`: `<StatusBadge>`, `<MetricDelta>`, `<ParameterImportanceChart>`, `<TrialsTable>`, `<CursorPaginator>`.
- **API client** at `ui/lib/api-client.ts` injecting `X-Request-ID` (UUIDv7 generated client-side); intercepting 4xx/5xx responses and toasting structured `error_code` + `message`.
- **Type generation**: `openapi-typescript` script in `package.json` consumes the FastAPI-generated OpenAPI schema to produce `ui/lib/types.ts`. Generation is committed (no runtime fetch).

### Out of scope

- `/chat/*` routes — `feat_chat_agent`.
- `/proposals/*` routes — `feat_proposals_ui`.
- `/audit` — MVP4.
- Playwright e2e — MVP3+ or `chore_tutorial_polish`.
- Auth UI — MVP4.
- Containerized UI Compose service — late MVP1 polish.
- WCAG AA gating, i18n — never scheduled.
- Forking studies via UI — MVP2 (`fork_study` agent tool).
- LLM-driven judgment regeneration UI (with confirmation interrupt per umbrella §15) — GA v1.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). The UI consumes only documented endpoints; never reaches into Postgres directly.

### Phase boundaries

Single-phase. The MVP1 deliverable: "an engineer can complete the tutorial flow end-to-end through the UI without resorting to curl, in under 30 minutes on a fresh laptop."

## 4) Product principles and constraints

- **Server state only via TanStack Query.** No `useState` for server data. Local state (form values, modal open/closed, sort selection) goes through `useState` / `useReducer`.
- **Polling is bounded.** Running studies poll at 3s. Completed/cancelled/failed studies poll once on mount (no refetchInterval). The `useStudy(id)` hook accepts a `refetchInterval` arg; pages decide based on `data.status`.
- **No optimistic updates in MVP1.** Mutations show a loading state, then refetch. Optimistic updates risk inconsistent UI on rollback; reserved for MVP2+ if needed.
- **shadcn primitives copied, not imported.** `npx shadcn-ui add button card dialog ...` brings them into `ui/components/ui/`. Customizations happen in our copies; we control upgrades.
- **Cursor pagination, not page-numbers.** Per `api-conventions.md`. The `<CursorPaginator>` component handles next/prev.
- **No client-side filtering of large lists.** If the user filters studies by status, the UI re-fetches with `?status=...`. Don't pull 1000 studies and filter in JS.
- **Responsive but desktop-first.** Tested at 1280px+ widths. Mobile/tablet may render but isn't gated.

### Anti-patterns

- **Do not** poll completed studies. Wasteful.
- **Do not** import shadcn from npm. Copy via `npx shadcn-ui add`.
- **Do not** call `fetch` directly. Use the `apiClient` from `ui/lib/api-client.ts` so `X-Request-ID` injection + error toasts are uniform.
- **Do not** use page-number pagination. Cursor-only.
- **Do not** persist server state in the URL beyond simple filters (`?status=running`). Don't try to round-trip a cursor through the URL — cursors live in state.
- **Do not** invent Tailwind classes that don't exist (e.g., `text-primary-mid`). Use the design tokens from `tailwind.config.ts`.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation`** — Next.js scaffolding, pnpm lockfile, Tailwind, eslint, prettier configured.
- **Dependency: `feat_study_lifecycle`** — Studies API + state machine.
- **Dependency: `feat_digest_proposal`** — Digest API + parameter_importance JSON shape.
- **Dependency: `feat_llm_judgments`** — Judgment API + override + calibration endpoints.
- **Dependency: `infra_adapter_elastic`** — Clusters API.
- **`openapi-typescript`** in devDependencies for type generation from OpenAPI.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (uses every screen).

### Authorization

N/A — single-tenant install, no auth surface. The UI assumes full access; an MVP4 PR will introduce role-based UI gates.

### Audit events

N/A — `audit_log` is MVP2.

## 7) Functional requirements

### FR-1: Layout + navigation
- The system **MUST** ship `app/layout.tsx` with: shadcn `ThemeProvider` (light theme default; dark theme available), TanStack Query `QueryClientProvider`, `<Toaster>`, top navigation with links to `/`, `/clusters`, `/query-sets`, `/templates`, `/studies`, `/proposals`, `/chat`. Active link highlighted.

### FR-2: Dashboard
- The dashboard at `/` **MUST** show: 5 most recent studies (cards: name, cluster, status, best_metric or progress); "Open proposals" count card linking to `/proposals?status=pr_opened`; "Studies completed in last 7 days" count.
- Initial load fetches:
  - `GET /api/v1/studies?limit=5` for the recent-studies cards
  - `GET /api/v1/proposals?status=pr_opened&limit=1` and reads the `X-Total-Count` response header for the open-proposals count
  - `GET /api/v1/studies?status=completed&since=<7d-ago-iso8601>&limit=1` and reads `X-Total-Count` for the 7-day count
- Per [`api-conventions.md` §"Pagination"](../../../01_architecture/api-conventions.md), every list endpoint returns `X-Total-Count` and accepts `?since=<iso8601>` — no dedicated count endpoints needed.

### FR-3: Studies list
- `/studies` **MUST** show a cursor-paginated table with columns: name (link), cluster, status badge, primary metric (best_metric or "—"), trials_summary (e.g., "23/100"), created_at.
- Status filter chips: `all`, `queued`, `running`, `completed`, `cancelled`, `failed`. Selecting a chip refetches with `?status=...`.
- "Create study" button opens the create modal.
- Notes: covers US-22.

### FR-4: Create-study modal
- The modal **MUST** be a multi-step form (because of the 8 inputs):
  - Step 1: cluster + target (target dropdown loads on cluster select via `GET /api/v1/clusters/{id}/schema?...` to populate index list)
  - Step 2: query set + judgment list (judgment list dropdown filters by selected query_set_id)
  - Step 3: template (filter by selected cluster's engine_type)
  - Step 4: search space (JSON textarea with `prism-react-renderer` highlighting; pre-filled with template-derived defaults if available)
  - Step 5: objective (metric + k + direction) + config (max_trials, time_budget_min, parallelism, sampler, pruner, seed)
  - Submit → POST + on success close modal + invalidate the studies list query.
- Each step's "Next" button is disabled until current-step Zod validation passes.

### FR-5: Study detail
- `/studies/{id}` **MUST** show:
  - Header: name, cluster, target, status badge, created_at, started_at, completed_at
  - Action buttons: "Cancel" (when running, opens confirmation dialog) — disabled in other states
  - Trials section: cursor-paginated `<TrialsTable>` with sort dropdown (`primary_metric_desc` default); polls every 3s while `status === 'running'`
  - Digest panel (rendered only when `digests` row exists for this study):
    - Narrative (markdown rendered safely via `react-markdown` with no HTML allowed)
    - `<ParameterImportanceChart>` (Recharts horizontal bar chart from `digests.parameter_importance`)
    - Top-10 trials table
    - Metric delta card: baseline → achieved + delta_pct
    - Suggested follow-ups (bulleted list)
    - "Open PR" button (only when an associated `proposal` row exists with `status='pending'`) — links to `feat_proposals_ui`'s detail page with action prefilled
- Notes: covers US-10, US-23, US-24, US-16.

### FR-6: Clusters list + detail
- `/clusters` **MUST** show a table: name, engine_type, environment, health_check.status badge (green/yellow/red/unreachable), notes; "Register cluster" button → modal.
- `/clusters/{id}` **MUST** show summary + studies-by-this-cluster table (paginated, links to study detail).
- The "Register cluster" modal validates all fields per `infra_adapter_elastic` API contract; on submit, polls `health_check` until it returns; surfaces errors via toast.
- Notes: covers US-4, US-5, US-22.

### FR-7: Query sets + queries + CSV upload
- `/query-sets` table; "Create query set" modal accepts JSON body OR CSV file (drag-and-drop).
- `/query-sets/{id}` detail: list of queries with inline edit/delete; bulk-add CSV upload accessible via "Add queries" button.
- CSV parsing happens server-side per `feat_study_lifecycle` FR-3; the UI just submits the file with `Content-Type: text/csv`.

### FR-8: Templates list + detail (view-only + fork-to-new-version)
- `/templates` table.
- `/templates/{id}` view-only display of body + declared_params; "Fork to v+1" button creates a new template with `parent_id = current.id` and `version = current.version + 1`, opens it for editing in a modal. Editing the existing template in-place is NOT supported (immutability per `feat_study_lifecycle` semantics).
- Body editor uses `prism-react-renderer` for syntax highlighting (Jinja2 + JSON). Full Monaco is GA v1.

### FR-9: Judgment Review
- `/judgments/{id}` shows a paginated list of judgments grouped by query (or filterable by source).
- Each row displays: query text, doc_id, current rating + source badge, notes, "Override" inline action that opens a popover with rating select + notes textarea.
- "Calibrate" button opens a modal accepting a list of human-labeled (query, doc, rating) tuples (CSV or JSON paste); on submit, calls `POST /api/v1/judgment-lists/{id}/calibration`; displays results inline.
- Notes: covers US-14, US-15.

### FR-10: API client + error handling
- `ui/lib/api-client.ts` **MUST** inject `X-Request-ID: <UUIDv7>` on every request.
- The client **MUST** convert `error_code` + `message` from 4xx/5xx responses into a toast notification via the `<Toaster>`.
- The client **MUST** retry on 503 with `retryable: true` per [`api-conventions.md` §"Error envelope"](../../../01_architecture/api-conventions.md), up to 3 attempts with exponential backoff (1s, 2s, 4s).

## 8) API and data contract baseline

This feature does NOT add any backend endpoints. It consumes the documented endpoints from its dependencies. The OpenAPI schema generated by FastAPI is the source of truth; `ui/lib/types.ts` is generated from it.

### 7.4 Enumerated value contracts

The UI's filter chips, status badges, and dropdown options **MUST** match the backend allowlists exactly:

| UI surface | Backend source of truth |
|---|---|
| Studies status filter chips | `backend/db/models/study.py` (`StudyStatus` `Literal[...]`) |
| Trials sort dropdown | `backend/api/studies.py` (`TrialSortKey` `Literal[...]`) |
| Cluster engine_type select | `backend/adapters/protocol.py` (`EngineType` `Literal[...]`) |
| Cluster auth_kind select | `backend/adapters/elastic.py` (`SUPPORTED_AUTH_KINDS` frozenset) |
| Study sampler select | `backend/db/models/study.py` (`SamplerKind`) |
| Study pruner select | `backend/db/models/study.py` (`PrunerKind`) |
| Objective metric select | `backend/eval/scoring.py` (`SUPPORTED_METRICS`) |
| Objective k select | `backend/eval/scoring.py` (`SUPPORTED_K_VALUES`) |
| Judgment source filter | `backend/db/models/judgment.py` |
| Proposal status badge | `backend/db/models/proposal.py` |

The UI **MUST** add a source-of-truth comment above every option array (e.g., `// Values must match backend/db/models/study.py StudyStatus`).

## 9) Data model and state transitions

This feature has no backend schema. UI-side state lives in TanStack Query cache + local React state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. XSS via user-generated content in study names, query texts, judgment notes. **Mitigation:** React's default escaping; `react-markdown` configured with no HTML allowed for digest narratives.
  2. Cursor leakage in URL bar — cursors are opaque server tokens. **Mitigation:** UI keeps cursors in state, not URL.
  3. CSV upload of large file (DoS via OOM in browser). **Mitigation:** UI rejects files >10MB before submitting; backend has its own quota.
- **Auditability:** N/A — `audit_log` is MVP2. UI doesn't claim to provide audit; surfaces what the API exposes.

## 11) UX flows and edge cases

### Primary flows

1. **Tutorial flow:** Dashboard → Clusters → Register cluster → Query Sets → Create + upload CSV → Templates → Create → Judgment Review → Generate → Studies → Create → watch live → digest → Open PR (handed to `feat_proposals_ui`).
2. **Daily flow:** Dashboard → recent studies → study detail → digest review → cancel/retry/open PR.
3. **Calibration flow:** Judgment Review → "Calibrate" → upload human samples → review kappa stats → optionally override LLM ratings.

### Edge/error flows

- **Backend down.** All hooks fail; the layout shell renders, content area shows `<EmptyState>` with "Backend unreachable. Check `make logs`."
- **Cluster unreachable when registering.** Toast surfaces `CLUSTER_UNREACHABLE` from API; modal stays open with the error.
- **Live polling on a study that transitions to completed.** The `useStudy` hook detects the status change in next poll, re-renders without polling. Digest panel appears when `data.digest` is non-null on a subsequent poll.
- **CSV with malformed rows.** Backend returns `INVALID_CSV` with row numbers; toast displays the error; UI does not attempt partial-success display in MVP1.
- **OpenAI key missing during judgment generation.** The "Generate" button fires `POST /judgments/generate`, which returns `OPENAI_NOT_CONFIGURED` (503); toast prompts the user to configure the secret per the runbook.

## 12) Given/When/Then acceptance criteria

### AC-1: Tutorial flow end-to-end via UI

- Given a fresh `make up` install with `local-es` seeded.
- When the operator opens `http://localhost:3000` and follows the tutorial flow (cluster → query set with CSV → template → judgments → study → cancel/run-to-completion → digest).
- Then the entire flow completes in under 30 minutes WITHOUT any curl/CLI calls (operator can complete it from the UI alone). The "Open PR" button at the end is enabled.

### AC-2: Live trials table updates

- Given a `running` study with 4-worker parallelism.
- When the operator opens `/studies/{id}`.
- Then within 3s of each new trial completing, the trials table re-renders with the new row appended (or sorted in if sort is `primary_metric_desc`). The polling stops automatically when status flips to `completed`.

### AC-3: Digest renders parameter importance

- Given a completed study with a digest.
- When the operator opens `/studies/{id}`.
- Then the digest panel renders: narrative (markdown), `<ParameterImportanceChart>` with one horizontal bar per param sorted by importance descending, top-10 trials table, baseline → achieved metric delta with `+24.5%` style.

### AC-4: Override a judgment

- Given a complete judgment list.
- When the operator clicks "Override" on a row, changes the rating from 2 to 0, adds a note, hits Save.
- Then within 1s the row updates with the new rating, source badge flips to `human`, notes shows the new note. Refreshing the page persists the change.

### AC-5: Calibration modal computes kappa

- Given a judgment list and a CSV of 30 human-labeled samples.
- When the operator opens "Calibrate" → uploads CSV → submits.
- Then the modal displays the computed `cohens_kappa`, `weighted_kappa`, `n_samples`, and the per-class agreement breakdown. The judgment-list summary header reflects the calibration value persisted to `judgment_lists.calibration`.

### AC-6: Source-of-truth comments verified

- Given the developer adds a new value to `backend/db/models/study.py StudyStatus` (e.g., `'paused'`).
- When CI runs.
- Then a CI step (or pre-commit hook) flags any `.tsx` files with `// Values must match backend/db/models/study.py StudyStatus` whose adjacent option array does NOT include the new value. Build fails.
- Notes: this CI step is part of `infra_foundation` `pr.yml` extension OR added by this feature.

### AC-7: Cursor pagination on studies list

- Given 75 studies exist.
- When the operator opens `/studies` with `?limit=50`.
- Then the table shows the first 50 with a "Next" button; clicking loads the next 25 with "Next" disabled. Filter chip changes reset to first page.

### AC-8: Backend down state

- Given the API container is stopped (`docker compose stop api`).
- When the operator opens `/`.
- Then the dashboard shows an empty state with "Backend unreachable" rather than an infinite spinner. The retry mechanism per FR-10 attempted 3× before surfacing the error.

### AC-9: Status badges match backend allowlist

- Given the operator inspects `<StatusBadge>` usages across all pages.
- When CI greps for option-list patterns.
- Then every `StudyStatus` / `ProposalStatus` / `EngineType` / `AuthKind` value rendered matches the backend's `Literal[...]` exactly (no phantom values).

## 13) Non-functional requirements

- **Performance:** First contentful paint <2s on a 4G connection. Polling at 3s adds ~0.1ms CPU per tick (negligible). Bundle size <500KB gzipped.
- **Reliability:** API errors result in toasts, not page crashes. Network blips during polling resume seamlessly.
- **Operability:** `X-Request-ID` injected on every call enables backend-side log correlation when an operator reports a UI bug.
- **Accessibility:** Basic — keyboard nav for primary actions, semantic HTML, ARIA labels on interactive elements. WCAG AA NOT gated.

## 14) Test strategy requirements

- **Unit tests** (`ui/tests/unit/`):
  - `components/StatusBadge.spec.tsx` — every status enum renders the documented color
  - `components/ParameterImportanceChart.spec.tsx` — given canonical input, renders expected bars
  - `lib/api-client.spec.ts` — `X-Request-ID` injected; error responses toast; retry on 503-retryable
  - `lib/api/studies.spec.ts` — TanStack Query hook contracts (mocked via msw)
- **Component tests** (`ui/tests/unit/`):
  - `app/studies/[id]/page.spec.tsx` — renders running state, transitions to completed, shows digest
  - `app/judgments/[id]/page.spec.tsx` — override flow
  - `app/studies/page.spec.tsx` — filter chips trigger refetch
- **E2E tests:** N/A in MVP1 (Playwright lands at `chore_tutorial_polish` or MVP3+).

vitest + msw for everything in MVP1. Tests run in CI under `pnpm test`.

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` already documents the patterns; update if implementation diverges.
- `docs/03_runbooks/`: add `ui-debugging.md` — how to inspect TanStack Query cache (React Query Devtools), reproduce a polling bug.
- `docs/02_product/mvp1-user-stories.md`: mark US-22 / US-23 / US-24 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** N/A — frontend feature.
- **Operational readiness gates:** The tutorial flow at AC-1 succeeds on a fresh laptop install in <30 min; bundle size <500KB.
- **Release gate:** `feat_proposals_ui` and `feat_chat_agent` authors confirm cross-feature link points (`/proposals/...`, `/chat/...`) work as expected.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (layout) | AC-1 | TBD | `ui/tests/unit/app/layout.spec.tsx` | runbook |
| FR-2 (dashboard) | AC-1 | TBD | `ui/tests/unit/app/page.spec.tsx` | — |
| FR-3 (studies list) | AC-7 | TBD | `ui/tests/unit/app/studies/page.spec.tsx` | — |
| FR-4 (create modal) | AC-1 | TBD | `ui/tests/unit/app/studies/create-modal.spec.tsx` | — |
| FR-5 (study detail) | AC-2, AC-3 | TBD | `ui/tests/unit/app/studies/[id]/page.spec.tsx` | — |
| FR-6 (clusters) | AC-1 | TBD | `ui/tests/unit/app/clusters/*` | — |
| FR-7 (query-sets) | AC-1 | TBD | `ui/tests/unit/app/query-sets/*` | — |
| FR-8 (templates) | AC-1 | TBD | `ui/tests/unit/app/templates/*` | — |
| FR-9 (judgment review) | AC-4, AC-5 | TBD | `ui/tests/unit/app/judgments/[id]/page.spec.tsx` | — |
| FR-10 (api-client) | AC-8 | TBD | `ui/tests/unit/lib/api-client.spec.ts` | — |
| (CI gate) | AC-6, AC-9 | TBD | (GitHub Actions step) | `pr.yml` |

## 18) Definition of feature done

- [ ] AC-1 through AC-9 pass.
- [ ] Tutorial flow at AC-1 succeeds on a fresh laptop install in <30 min.
- [ ] Bundle size <500KB gzipped.
- [ ] Source-of-truth comments on every option array; CI gate (AC-6) passes.
- [ ] `docs/03_runbooks/ui-debugging.md` merged.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — Server state via TanStack Query only; no `useState` for server data — per [`ui-architecture.md` §"Server state pattern"](../../../01_architecture/ui-architecture.md).
- 2026-05-09 — shadcn primitives copied into repo, not npm-imported — per [`tech-stack.md`](../../../01_architecture/tech-stack.md) and [`ui-architecture.md`](../../../01_architecture/ui-architecture.md).
- 2026-05-09 — Cursor pagination, no page-numbers — per [`api-conventions.md`](../../../01_architecture/api-conventions.md).
- 2026-05-09 — Source-of-truth comments on every option array — drift-prevention.
- 2026-05-09 — Studies-completed count: **`X-Total-Count` response header on every list endpoint** (added in `feat_study_lifecycle` as a follow-up to its FR-1). Dashboard reads the header from `?status=completed&limit=1` calls.
- 2026-05-09 — Markdown sanitizer: **`react-markdown` + `remark-gfm`**; no raw HTML allowed.
- 2026-05-09 — CSV size cap: **10MB on the UI** (rejects before submitting); backend has its own quota.
- 2026-05-09 — Source-of-truth-comment CI gate: **shell script in `pr.yml`** that greps `// Values must match <path> <symbol>` comments and verifies the cited Literal contains the option list. Simpler than an eslint rule.
