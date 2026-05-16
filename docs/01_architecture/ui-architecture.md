# UI Architecture

**Status:** Adopted for MVP1. Next.js 16 App Router (React 19, Turbopack) + shadcn/ui + Tailwind 4 (CSS-first) + TanStack Query + Vitest 4. Per-screen feature specs (`feat_studies_ui`, `feat_proposals_ui`, `feat_chat_agent`) implement the patterns documented here. Stack bumped from Next 14 / React 18 / Tailwind 3 / Vitest 2 on 2026-05-12 via `infra_frontend_stack_refresh` (the placeholder UI was the optimal upgrade window before `feat_studies_ui` adds component volume).
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §22](../00_overview/product/relevance-copilot-spec.md) ("UI screens") and §28 ("Frontend stack").

---

## Tech stack (recap)

Per [`tech-stack.md` §"Frontend"](tech-stack.md):

| Layer | Choice |
|---|---|
| Framework | Next.js 16 (App Router, Turbopack) — React 19 peer |
| Language | TypeScript 6 (`--strict` + `noUncheckedIndexedAccess`) |
| UI components | shadcn/ui (copied into repo, not npm dep) |
| Styling | Tailwind CSS 4 (CSS-first via `@import "tailwindcss"` in `globals.css`; no `tailwind.config.ts`) |
| Server state | TanStack Query (caching, retries, optimistic updates) |
| Forms | React Hook Form + Zod |
| Charts | Recharts |
| Streaming | `fetch()` with `ReadableStream` (SSE-framed body over POST). Native `EventSource` is GET-only and unsuitable for the chat surface where the user message is in the request body. |
| Testing | Vitest 4 + msw + jsdom 29 |
| Lint | ESLint 9 (flat config, `eslint.config.mjs`) + Next + security plugins |

## Routes (MVP1)

Per umbrella spec §22, MVP1 ships these top-level routes:

| Route | Screen | Owning feature |
|---|---|---|
| `/` | Dashboard (recent studies, open proposals, key metrics) | `feat_studies_ui` |
| `/chat/{conversation_id}` | Chat | `feat_chat_agent` |
| `/clusters` | Clusters list | `feat_studies_ui` (consumes `infra_adapter_elastic` API) |
| `/clusters/{id}` | Cluster detail | `feat_studies_ui` |
| `/query-sets` | Query Sets list | `feat_studies_ui` |
| `/query-sets/{id}` | Query Set detail | `feat_studies_ui` |
| `/judgments/{id}` | Judgment Review (LLM ratings + override UI + calibration) | `feat_studies_ui` |
| `/templates` | Templates list | `feat_studies_ui` |
| `/templates/{id}` | Template editor | `feat_studies_ui` |
| `/studies` | Studies list | `feat_studies_ui` |
| `/studies/{id}` | Study detail (live trial table + digest) | `feat_studies_ui` |
| `/proposals` | Proposals list | `feat_proposals_ui` |
| `/proposals/{id}` | Proposal detail (config diff + metric delta + PR link) | `feat_proposals_ui` |

Audit log (`/audit`) per §22 line 1621 is reserved for MVP4+ (when audit_log + admin role exist).

## Directory layout

The `ui/` workspace uses the **`src/` layout** — the `@/*` TypeScript alias
resolves to `ui/src/*`. Tailwind 4 is **CSS-first** (no `tailwind.config.ts`);
design tokens live in `ui/src/app/globals.css` under `@theme {}`.

```
ui/
  src/
    app/                              # Next.js 16 App Router pages
      layout.tsx                      # Root layout: ThemeProvider, QueryProvider, Toaster, TopNav
      page.tsx                        # Dashboard (Story 3.1)
      globals.css                     # Tailwind 4 base + `@theme {}` tokens
      clusters/
        page.tsx                      # List
        [id]/
          page.tsx                    # Detail (cluster summary + studies-by-cluster)
      studies/
        page.tsx                      # List
        [id]/
          page.tsx                    # Detail (header + trials + digest panel)
      query-sets/
        page.tsx
        [id]/
          page.tsx
      templates/
        page.tsx
        [id]/
          page.tsx                    # Read-only detail + Fork-to-v+1 button
      judgments/
        [id]/
          page.tsx
      # `proposals/` and `chat/` ship later (`feat_proposals_ui` + `feat_chat_agent`).

    components/
      ui/                             # shadcn primitives (Button, Card, Dialog, Select, ...)
      common/                         # StatusBadge, MetricDelta, CursorPaginator, EmptyState, ParameterImportanceChart
      layout/                         # TopNav
      providers/                      # ThemeProvider, QueryProvider
      dashboard/                      # CountCard, RecentStudiesCards
      studies/                        # StudiesTable, StudyHeader, TrialsTable, DigestPanel, CreateStudyModal, ...
      clusters/                       # ClustersTable, RegisterClusterModal, ClusterDetailSummary, StudiesByClusterTable
      query-sets/                     # QuerySetsTable, CreateQuerySetModal, AddQueriesDialog, AssociatedJudgmentLists, GenerateJudgmentsDialog
      templates/                      # TemplatesTable, CreateTemplateModal, ForkTemplateModal, TemplateBodyEditor (Prism), TemplateDetailView
      judgments/                      # JudgmentListHeader, JudgmentsTable, OverridePopover, CalibrationModal

    lib/
      api/                            # TanStack Query hooks per resource
        studies.ts                    # useStudies / useStudy / useStudyTrials / useCreateStudy / useCancelStudy
        clusters.ts                   # useClusters / useCluster / useRegisterCluster / useClusterSchema
        config-repos.ts               # useConfigRepos / useCreateConfigRepo
        query-sets.ts                 # useQuerySets / useQuerySet / useCreateQuerySet / useAddQueries
        query-templates.ts            # useTemplates / useTemplate / useCreateTemplate
        judgments.ts                  # useJudgmentLists / useJudgmentList / useJudgments / useOverrideJudgment / useCalibrate / useGenerateJudgments / useImportJudgmentList
        digests.ts                    # useStudyDigest
        proposals.ts                  # useProposals / useProposalForStudy
      api-client.ts                   # fetch wrapper with X-Request-ID, error-envelope translation, 503-retryable backoff
      api-errors.ts                   # ApiError class + isApiError + toToastMessage
      uuid.ts                         # UUIDv7 generator (RFC 9562 §5.7)
      types.ts                        # GENERATED from backend OpenAPI via `pnpm types:gen`
      enums.ts                        # CANONICAL wire-value allowlists (single source of truth comments live here)
      csv-validate.ts                 # UI-side CSV pre-submit guard
      utils.ts                        # shadcn-conventional cn() helper

    __tests__/                        # Vitest specs (glob: src/**/*.test.{ts,tsx})
      setup.ts                        # msw server + jsdom polyfills (matchMedia, scrollIntoView, pointer capture)
      lib/api/...                     # hook contract tests
      components/...                  # component tests with msw
      app/...                         # page-level component tests

  tests/
    e2e/                              # Playwright (MVP3+; MVP1 has no e2e)
```

## Server state pattern (TanStack Query)

**One hook per resource × operation.** Hooks live in `ui/lib/api/<resource>.ts`. Patterns:

```typescript
// ui/lib/api/studies.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api-client';

export function useStudies(filter?: { status?: StudyStatus }) {
  return useQuery({
    queryKey: ['studies', filter],
    queryFn: () => apiClient.get('/api/v1/studies', { params: filter }),
  });
}

export function useStudy(id: string, options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ['studies', id],
    queryFn: () => apiClient.get(`/api/v1/studies/${id}`),
    refetchInterval: options?.refetchInterval, // for polling running studies
  });
}

export function useCreateStudy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateStudyRequest) => apiClient.post('/api/v1/studies', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['studies'] }),
  });
}
```

**Polling for live data** (running studies): pass `refetchInterval: 3000` to `useStudy(id)`. Stop polling when `data.status !== 'running'`.

**Cursor pagination**: use TanStack Query's `useInfiniteQuery` with `getNextPageParam: lastPage => lastPage.next_cursor ?? undefined`.

**Optimistic updates**: not used in MVP1 (the operations are too important to risk an inconsistent UI on rollback). Reserved for MVP2+.

**Mutations** invalidate queries via `qc.invalidateQueries({ queryKey: [...] })` on success.

## Form pattern (React Hook Form + Zod)

```typescript
// Zod schema reused from backend (or co-defined for now; MVP4 brings shared schema generation)
const CreateStudySchema = z.object({
  name: z.string().min(1).max(200),
  cluster_id: z.string().uuid(),
  // ...
});

function CreateStudyForm() {
  const form = useForm({ resolver: zodResolver(CreateStudySchema) });
  const create = useCreateStudy();

  return (
    <form onSubmit={form.handleSubmit((values) => create.mutate(values))}>
      {/* ... shadcn Form + Input + Select primitives */}
    </form>
  );
}
```

Validation errors from Zod show inline; backend `VALIDATION_ERROR` (422) responses are surfaced via toast + form-field highlighting.

## Streaming chat (fetch + SSE-framed POST response)

Per umbrella spec §22, the chat surface uses server-sent events for OpenAI streaming proxied through the API. **The implementation uses `fetch()` with a `ReadableStream` body — NOT native `EventSource`** — because the user message is in the request body and `EventSource` is GET-only.

```typescript
async function useChatStream(conversationId: string, userMessage: string, onEvent: (event: SSEEvent) => void) {
  const response = await fetch(`/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
      "X-Request-ID": crypto.randomUUID(),
    },
    body: JSON.stringify({ role: "user", content: { text: userMessage } }),
  });

  if (!response.ok || !response.body) {
    // surface error via toast + abort
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Split on SSE event delimiter (\n\n) and dispatch parsed events
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";  // keep partial event in buffer
    for (const raw of events) {
      const event = parseSSEEvent(raw);  // {event, data}
      onEvent(event);
    }
  }
}
```

The same SSE wire format (`event: <type>\ndata: <json>\n\n`) is used; only the transport changes. The chat surface is the only streaming consumer in MVP1.

## Component composition

**shadcn primitives** are copied into `ui/src/components/ui/` via `npx shadcn@latest add <component>`. Customizations happen in the copied source. We do NOT depend on `@shadcn/ui` from npm.

**Studies / Proposals / Chat compositions** live in `ui/src/components/<feature>/`. Each composition imports from `ui/src/components/ui/` for primitives and from `ui/src/components/common/` for cross-cutting (StatusBadge, MetricDelta, ParameterImportanceChart).

**Cross-cutting components** (used by 2+ features):
- `<StatusBadge status={...} />` — colored chip for `studies.status`, `proposals.status`, `pr_state`, etc.
- `<MetricDelta baseline={n} achieved={m} />` — formatted "0.612 → 0.762 (+24.5%)" with color
- `<ParameterImportanceChart data={...} />` — Recharts horizontal bar chart consuming `digests.parameter_importance`
- `<DataTable<T>>` — shared list-table primitive (see [§"DataTable primitive"](#datatable-primitive)). All 8 standalone tables now consume this; per-table thin wrappers like `<StudiesTable>` and `<TrialsTable>` only wire URL state and column configs.

## DataTable primitive

`feat_data_table_primitive` (2026-05-16) consolidated the 8 hand-rolled `<Table>` components into one shared primitive at [`ui/src/components/common/data-table.tsx`](../../ui/src/components/common/data-table.tsx) built on `@tanstack/react-table@~8.21.3` and the existing shadcn `<Table>` primitive.

**Shape.** The primitive is a controlled component — server state (`data`, `totalCount`, `has_more`, `next_cursor`) flows in from the consumer's TanStack Query hook, and URL state (`sort`, `filters`, `q`, `cursor`, `pageSize`) flows in from a page-level [`useDataTableUrlState(tableId, columns)`](../../ui/src/hooks/use-data-table-url-state.ts) hook. The primitive renders the toolbar (search input + filter chips/FK selects + density toggle + column-visibility menu + total-count display), the table body, and the wrapped `<CursorPaginator>`. Three empty-state shapes (`no-rows-exist`, `no-rows-match`, `stale-cursor`) cover the FR-9 branches.

**Column config interface.** Each consumer exports a co-located `<table>-table.column-config.tsx` that returns a `DataTableColumnDef<T>[]` — TanStack Table's `ColumnDef<T>` with RelyLoop extras (`sortable`, `sortKey`, `firstClickDirection`, `sortDirections`, `filter`, `tooltipKey`, `hideable`, `sticky`). Filters declare `kind: 'enum' | 'fk-select'`; enum filters carry `wireValues: readonly string[]` (imported from [`@/lib/enums`](../../ui/src/lib/enums.ts)) and FK filters carry `useOptions: () => { data: { id, label }[], isLoading }`.

**Source-of-truth discipline.** Every filter — enum or FK — declares a `sourceOfTruth: string` field pointing at the canonical backend allowlist (e.g., `'backend/app/api/v1/schemas.py StudyStatusWire'` or `'backend/app/db/models/proposal.py Proposal.template_id'`). The Story 2.13 lint guard at [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) scans every `*.column-config.{ts,tsx}` and fails the test suite if (a) any filter is missing `sourceOfTruth`, (b) `sourceOfTruth` doesn't start with `backend/`, (c) `wireValues` is an inline array rather than an imported identifier, or (d) the imported identifier's declaration in `enums.ts` is missing the canonical `// Values must match backend/...py <Symbol>` comment. This is the frontend half of the "Enumerated Value Contract Discipline" rule in CLAUDE.md — the lint guard catches drift CI-side; the CLAUDE.md rule and the `enums.ts` source-of-truth comment catch it review-side.

**Custom sort wire formats.** Most consumers use the generic `?sort=<col>:<dir>` URL shape. Trials' backend predates this convention and uses fused tokens (`primary_metric_desc`, `optuna_trial_number_asc`); the primitive accepts an optional `sortCodec` prop (`{ encode, decode }`) that translates between the internal `(col, dir)` form and the legacy wire format without leaking the fork into the rest of the surface. See [`ui/src/components/studies/trials-table.column-config.tsx`](../../ui/src/components/studies/trials-table.column-config.tsx).

**Per-resource scoping.** Pages on resource-specific routes (`/studies/[id]`, `/judgments/[id]`, `/query-sets/[id]`, `/clusters/[id]`) scope the `tableId` with the URL parameter (`trials-${studyId}`, `judgments-${listId}`, etc.) so column-visibility and density preferences in `localStorage` don't bleed across different parent resources.

## Auth surface (MVP1)

**None.** No login, no sessions, no role gates. The UI assumes the operator has full access to everything the API exposes.

**X-Request-ID** is injected into every API call by `ui/lib/api-client.ts` for log correlation per [`api-conventions.md` §"Trace / request correlation"](api-conventions.md). Optionally accepts a server-supplied `X-Request-ID` if present in the response.

## Contextual help (tooltips and popovers)

`feat_contextual_help` Phase 1 (2026-05-14) added the project's first tooltip primitive plus two glossary-backed wrappers. New surfaces that need label-adjacent help should use these instead of inventing a pattern.

**Primitive:** [`ui/src/components/ui/tooltip.tsx`](../../ui/src/components/ui/tooltip.tsx) — shadcn-style re-export of `@radix-ui/react-tooltip` (`Tooltip` / `TooltipTrigger` / `TooltipContent` / `TooltipProvider`). `TooltipContent` carries `motion-reduce:animate-none` so the project respects `prefers-reduced-motion: reduce` (Radix does NOT auto-disable Tailwind animation classes added at the project layer). The `TooltipProvider` is mounted once in [`ui/src/app/layout.tsx`](../../ui/src/app/layout.tsx) inside `QueryProvider` with `delayDuration={700}` so every page has shared tooltip context.

**Wrappers:**

| Wrapper | Use for | Trigger | Glossary-key type |
|---|---|---|---|
| [`InfoTooltip`](../../ui/src/components/common/info-tooltip.tsx) | Short (≤140 char) factual help next to a label, column header, or section title | Hover OR keyboard focus | `ShortGlossaryKey` |
| [`HelpPopover`](../../ui/src/components/common/help-popover.tsx) | Multi-line guidance, multi-option comparisons (≤800 char), Markdown bullet lists | Click / Enter / Space | `LongGlossaryKey` |

`InfoTooltip` has two modes: **standalone** (default — renders its own `<button type="button" aria-label="...">` with a 14×14 lucide `<Info />` icon inside a 24×24 hit area; satisfies WCAG 2.2 SC 2.5.8 — Target Size Minimum), and **asChild** (set `asChild` prop; the caller-supplied child becomes the trigger via Radix `TooltipTrigger asChild`; the wrapper does NOT inject its own `data-testid` because a DOM node carries only one). asChild mode is for wrapping existing focusable elements like buttons or links; standalone mode is for label-adjacent placements.

**Glossary source-of-truth:** [`ui/src/lib/glossary.ts`](../../ui/src/lib/glossary.ts). All tooltip / popover copy lives here — never inline in components. The file mirrors the [`enums.ts`](../../ui/src/lib/enums.ts) pattern: a `// Source-of-truth: backend/.../path.py Symbol` comment above each enum-keyed group, with the parity test helper `expectGlossaryGroundedAgainstEnums(prefix, wireValues)` enforcing key-for-key alignment with the backend wire types. User-visible copy fields (`short`, `long`, `ariaLabel`) **MUST NOT** contain backend file paths or symbol names — citations go in the TypeScript comments only. The companion vitest at [`ui/src/__tests__/lib/glossary.test.ts`](../../ui/src/__tests__/lib/glossary.test.ts) enforces this contract.

When adding new tooltips on existing surfaces (Phase 2 / Phase 3 work — see [`feat_contextual_help/phase2_idea.md`](../02_product/planned_features/feat_contextual_help/phase2_idea.md) and [`phase3_idea.md`](../02_product/planned_features/feat_contextual_help/phase3_idea.md)), extend `glossary.ts` with new keys following the same naming convention (dotted, lowercase, `<scope>.<aggregate>` or `<scope>.<aggregate>.<wire_value>`) and add a parity-test case for any new enum group.

## Reserved for later releases

| Capability | Activates at |
|---|---|
| Containerized `ui` Compose service | Late MVP1 polish (`chore_tutorial_polish`) or post-MVP1 |
| Playwright e2e harness | MVP3+ (or earlier if `chore_tutorial_polish` adds it) |
| WCAG AA gating | NOT scheduled (aspirational per §28) |
| i18n / localization | NOT scheduled (English-only through GA) |
| Mobile UI | NOT scheduled (responsive but desktop-first) |
| Auth UI (login, role badges, tenant switcher) | MVP4 |
| Audit log viewer at `/audit` | MVP4 |
| Slack notification preferences | MVP2 |
| Forking studies via UI | MVP2 |
| Multi-cluster dashboard widgets | MVP3 |

## Cross-references

- Stack choices: [`tech-stack.md`](tech-stack.md)
- API conventions UI consumes: [`api-conventions.md`](api-conventions.md)
- Service topology (UI talks to API only): [`system-overview.md`](system-overview.md)
- Owning feature specs:
  - [`feat_studies_ui/feature_spec.md`](../02_product/planned_features/feat_studies_ui/feature_spec.md) — bulk of MVP1 screens
  - [`feat_proposals_ui/feature_spec.md`](../02_product/planned_features/feat_proposals_ui/feature_spec.md) — proposals list + detail
  - [`feat_chat_agent/feature_spec.md`](../02_product/planned_features/feat_chat_agent/feature_spec.md) — chat surface (also covers backend agent)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
