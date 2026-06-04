# UI Architecture

**Status:** Adopted for MVP1. Next.js 16 App Router (React 19, Turbopack) + shadcn/ui + Tailwind 4 (CSS-first) + TanStack Query + Vitest 4. Per-screen feature specs (`feat_studies_ui`, `feat_proposals_ui`, `feat_chat_agent`) implement the patterns documented here. Stack bumped from Next 14 / React 18 / Tailwind 3 / Vitest 2 on 2026-05-12 via `infra_frontend_stack_refresh` (the placeholder UI was the optimal upgrade window before `feat_studies_ui` adds component volume).
**Source of truth for product context:** [docs/00_overview/relyloop-spec.md §22](../00_overview/relyloop-spec.md) ("UI screens") and §28 ("Frontend stack").

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
| `/studies` | Studies list. Columns: name, cluster, status, best_metric (with `Pinned at metric ceiling` badge for `>=0.99` on `maximize` studies), `Trials` (non-baseline count), `Convergence` (badge — `Converged`/`Improving`/`Too few trials`/em-dash), created_at, completed_at. Trials + Convergence columns added by `feat_studies_convergence_visibility` Epic 1 (2026-06-02) — backend computes them via `count_trials_for_studies` + `resolve_list_convergence_verdicts` (bounded to 1–2 queries per page; FR-3). The Convergence badge reuses `CONVERGENCE_VERDICT_VALUES` (`ui/src/lib/enums.ts`) for source-of-truth discipline and the `convergence_verdict` glossary key for the tooltip — same taxonomy as the `<ConvergencePanel>` on the detail page. **Recent-chains card** (`feat_overnight_studies_summary_card`, 2026-06-04) renders above the table — a dismissible "Ran while you were away" card surfacing overnight follow-up chains that completed since the operator's last visit (FR-1). Self-contained: owns its data via `useRecentChains(since)` (TanStack hook against `GET /api/v1/studies/chains/recent`) + `useStudiesVisited()` (localStorage-backed visited-state with a +1ms exclusive dismissal nudge per FR-5). Early-returns `null` on pending / error / empty so the table beneath always renders predictably (best-effort discoverability per spec §10). Stop-reason phrasing reuses `CHAIN_STOP_REASON_PHRASE` from `ui/src/lib/chain-stop-reason.ts` — the same map shipped with `feat_overnight_final_solution_phase2` — so the card and the chain panel never drift. | `feat_studies_ui` |
| `/studies/{id}` | Study detail (live trial table + digest; the `AutoFollowupChainPanel` renders a rolled-up **Overnight chain** summary — ordered links, cumulative lift, best-config, stop reason — fed by `useStudyChain` against `GET /studies/{id}/chain`. Refetch contract per `feat_overnight_autopilot` D-10; render predicate D-13; best-config 3-branch D-11. **Per-link Strategy badge** added by `feat_overnight_final_solution` Story 3.2 (`feat_overnight_final_solution` FR-7) — a compact `narrow ↓` / `widen ↑` / `swapped to {short_template_name}` / `refined` label per link, sourced from `StudyChainLink.selected_followup_kind` (additive optional field with defensive coercion at chain-summary construction so unknown JSONB values become `null` + a `chain_selected_kind_unknown` WARN, never a 500). The swap_template badge resolves the target's display name via a per-link `useTemplate(link.template_id)` fetch (per OQ-1 / D-11). The `ConvergencePanel` mounts between `ConfidencePanel` and the trials table — verdict badge + best-so-far Recharts curve fed by `StudyDetail.convergence`, with three null-state branches (still_running / not_enough_trials / unavailable) per `feat_study_convergence_indicator` AC-13/13b/13c. The `ConvergenceVerdict` Literal flows via the FR-7 soft contract to the autopilot chain panel's per-link summary — the autopilot PR consumes the type symbol; AC-16 lives in the autopilot CI lane) | `feat_studies_ui` |
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

## Form dropdown primitive

`chore_form_dropdown_primitive` (2026-05-18) consolidates the form-side FK dropdowns into one shared primitive at [`ui/src/components/common/entity-select.tsx`](../../ui/src/components/common/entity-select.tsx). Peer to (NOT child of) [`data-table-fk-select.tsx`](../../ui/src/components/common/data-table-fk-select.tsx) — the two primitives have different rendering families and hook shapes, kept apart intentionally.

**Shape.** `<EntitySelect<T>>` is generic over entity type. Required props: `query` (the consumer's `UseQueryResult` from `useClusters`, `useConfigRepos`, `useTemplates`, `useQuerySets`, or `useJudgmentLists`), `getId(entity) → string`, `getLabel(entity) → string`, controlled `value: string | undefined` + `onChange(next)`. Optional slots: `getStatus(entity) → 'green' | 'yellow' | 'red' | 'unknown'` (renders a status dot and sorts entries green-first with stable order within tiers; consumer maps the backend wire value `'unreachable'` to `'unknown'` per [`HEALTH_STATUS_VALUES`](../../ui/src/lib/enums.ts)), `inlineWarning(selected) → string | null` (renders an amber `<p class="text-amber-600 text-xs mt-1">` below the trigger), `disabledIds: ReadonlySet<string>` + `disabledReason(entity) → string | null` (renders `disabled` + `title=…` on the matching `<SelectItem>`), `emptyState: { message, cta?: { label, href } }` (renders the message in a disabled trigger and an inline Next.js `<Link>` CTA when the loaded list is empty), `placeholder`, `loadingPlaceholder`, `id`, `data-testid`.

**Shadcn vs native — asymmetry to `DataTableFkSelect`.** The form-side primitive renders shadcn `<Select>` / `<SelectTrigger>` / `<SelectContent>` / `<SelectItem>` (Radix under the hood) for visual consistency with the surrounding form ecosystem (`<Input>`, `<Textarea>`, `<Label>`). The DataTable-side primitive renders a native `<select>` because the filter strip introduced the convention before the column-config-side adopted Radix. Both primitives are first-class citizens; neither extends the other. New form-level FK pickers MUST use `<EntitySelect>`; new DataTable filter slots MUST use `<DataTableFkSelect>`.

**Source-of-truth discipline (forms).** The vitest lint guard at [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](../../ui/src/__tests__/components/common/form-select-discipline.test.tsx) scans every form `*.tsx` under `ui/src/components/` (excluding `__tests__/`, `common/`, and `*.column-config.{ts,tsx}`) and fails when a file imports `SelectItem` from `'@/components/ui/select'` AND inlines `<SelectItem value="<literal>">` where `<literal>` matches any backend enum wire value defined in [`enums.ts`](../../ui/src/lib/enums.ts). Escape hatch: a top-of-file `// no-enum-import: <non-empty reason>` comment. This is the form-level complement to the DataTable column-discipline guard — together they cover every UI surface where the frontend ships a wire value back to the backend.

**Modal-level testing.** The shadcn `<Select>` family crashes inside jsdom + Dialog focus traps (Radix `patchedFocus` infinite recursion). Every modal test that exercises an `<EntitySelect>` ships a `vi.mock('@/components/ui/select', ...)` block that replaces the Radix primitives with a native `<select>` shim — the canonical helper lives at [`ui/src/__tests__/helpers/shadcn-select-mock.tsx`](../../ui/src/__tests__/helpers/shadcn-select-mock.tsx) (`chore_extract_shadcn_select_test_mock`, 2026-05-19) and the per-test usage pattern is a 3-line dynamic-`import()` inside `vi.mock` to sidestep vitest's hoisting rule. The unit-level `<EntitySelect>` tests at [`ui/src/__tests__/components/common/entity-select.test.tsx`](../../ui/src/__tests__/components/common/entity-select.test.tsx) run against the real Radix primitives (no Dialog wrapper, no patchedFocus recursion).

**Manual-mode fallback pattern (target picker).** The create-study modal's Step-1 target field (added by `feat_create_study_target_autocomplete`, 2026-05-20) is the first surface that pairs `<EntitySelect>` with a free-text `<Input>` fallback toggled by an "Enter manually" button. Pattern: a `manualMode: boolean` state selects between the EntitySelect (default, when a cluster is picked + listing is permitted) and the original `<Input>` (when the operator opts in OR when the targets endpoint returns `TARGETS_FORBIDDEN`, which auto-flips the toggle). The toggle is reset on every modal open (via `useEffect([open], () => setManualMode(false))` — Radix `<Dialog>` keeps the component mounted across close/reopen so plain `useState` would persist) and on every cluster change (in the cluster `<EntitySelect>`'s `onChange` cascade). This pattern is the right call when an EntitySelect endpoint can legitimately fail in a way that doesn't preclude entering a value: the user still has an escape hatch, the dropdown is the discovery-cost-zero default, and a single retry-friendly UX hint replaces what used to be a 4-retry toast storm. See [`create-study-modal.tsx`](../../ui/src/components/studies/create-study-modal.tsx) Step 1 for the canonical implementation.

## Search-space builder

`feat_create_study_search_space_builder` (2026-05-20) lands a per-parameter visual editor that sits ALONGSIDE the existing Step-4 `<Textarea>` in the create-study modal. The canonical JSON wire format remains the source of truth — the builder is a controlled component over the existing `search_space_text: string` RHF field. Module: [`ui/src/components/studies/search-space-builder/`](../../ui/src/components/studies/search-space-builder/).

**Shape.** `<SearchSpaceBuilder value onChange templateBody templateId templateFetchStatus />` renders one row per `templateBody.declared_params` key. Each row contains an editable type selector (`float` / `int` / `categorical`), low/high numeric spinners (float/int), a log-scale checkbox (float; aria-disabled when low ≤ 0), a chip input (categorical), and a per-row cardinality counter. Header cardinality counter sums per-row contributions; turns red + `aria-invalid="true"` at >10⁶ with a max-contributor hint (warning-only per FR-7 — does NOT block Next). A non-actionable "Add custom param" Popover points users at the template detail page to add new tunable params.

**Source-of-truth discipline — Pydantic discriminated unions.** `ParamSpec.type` wire values (`float` / `int` / `categorical`) live in `backend/app/domain/study/search_space.py`'s discriminated union, NOT in [`ui/src/lib/enums.ts`](../../ui/src/lib/enums.ts) — so the `form-select-discipline.test.tsx` lint guard does not catch drift. The dedicated parity test at [`ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx`](../../ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx) reads the backend file at runtime, extracts `Literal["..."]` values via regex, and asserts the frontend's `ROW_TYPE_VALUES` array matches one-for-one. This is the canonical pattern for any future wire values that live in a Pydantic discriminated union rather than `enums.ts`.

**Round-trip discipline.** The builder reads `value` (textarea string) on every render and writes back via a single 200ms debounce. Synchronous `onBlur` flush via `flushBuilderWrite()` reads the pending `SearchSpaceJson` from `pendingWriteRef` so the latest keystroke emits even when React's re-render hasn't yet propagated the prior `onChange`. A `lastBuilderWriteRef` guard prevents the builder's own writes from invalidating its cross-type stash. The round-trip parity test at [`round-trip.test.tsx`](../../ui/src/__tests__/components/studies/search-space-builder/round-trip.test.tsx) mounts the builder for 11 fixtures and verifies semantic equality + first-pass canonicalization (`10.0 → 10`, `1e-3 → 0.001`).

**Responsive layout.** [`responsive-layout.tsx`](../../ui/src/components/studies/search-space-builder/responsive-layout.tsx) renders builder + textarea side-by-side at ≥1024px (`lg:grid-cols-2`); tab toggle "Builder | JSON" at <1024px with Builder active by default. The textarea stays in the DOM at every viewport (CSS `hidden` on inactive tab, NOT conditional rendering) so React Hook Form's `register` reference stays stable and existing modal tests' `getByTestId('cs-search-space')` queries continue to resolve.

## Detail page shell primitive

`chore_detail_page_shell_primitive` (2026-05-19) consolidates the `isPending → isError → data` scaffolding shared by six `/{entity}/[id]` detail routes into one primitive at [`ui/src/components/common/detail-page-shell.tsx`](../../ui/src/components/common/detail-page-shell.tsx). Pre-migration, each of `clusters/[id]`, `studies/[id]`, `proposals/[id]`, `query-sets/[id]`, `templates/[id]`, and `judgments/[id]` hand-rolled the same ternary with identical className strings and slightly inconsistent copy ("deleted" vs "removed") — and only `proposals/[id]` bothered to discriminate 404 from network error. The primitive flattens that into one place.

**Shape.** `<DetailPageShell<T>>` is generic over the resource type. Required props: `query: UseQueryResult<T, ApiError>` (the consumer's TanStack hook return), `entityLabel: string` (singular, e.g. `"study"`), `notFoundErrorCode: string` (e.g. `"STUDY_NOT_FOUND"` — matches the backend's `error_code` value, not HTTP status, per `api-errors.ts`). Optional props: `entityTitle?: string` (override default title-casing of `entityLabel`), `notFoundMessage?: string` and `unreachableMessage?: string` (override default copy). Children-as-function — consumer's render fires with the loaded data:

```tsx
<DetailPageShell query={studyQ} entityLabel="study" notFoundErrorCode="STUDY_NOT_FOUND">
  {(study) => (
    <>
      <StudyHeader study={study} />
      <TrialsTable studyId={study.id} />
    </>
  )}
</DetailPageShell>
```

**Behavior.** `isPending` → `<Card><CardContent><p>Loading…</p></CardContent></Card>`. `isError && error.errorCode === notFoundErrorCode` → `<EmptyState title="{Entity} not found" message="The {entity} may have been deleted." />`. `isError && error.errorCode !== notFoundErrorCode` (network / 5xx) → `<EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />`. Existing `<EmptyState>` primitive consumed unchanged.

**Out of scope.** The `chat/[id]` detail route is structurally different (stream-rendered conversation, not a card-based scaffold) and not migrated. The shared back-link header (`<Link>← All {entities}</Link>`) is also not absorbed by this primitive — left as a per-page concern; revisit if a 7th detail route adds the same shape (Q2's deferred follow-up).

**Source-of-truth discipline (detail pages).** The vitest lint guard at [`ui/src/__tests__/components/common/detail-page-shell-discipline.test.tsx`](../../ui/src/__tests__/components/common/detail-page-shell-discipline.test.tsx) scans every `src/app/<entity>/[id]/page.tsx` (excluding `chat/[id]`) and fails when a file uses both `isPending ?` and `isError ?` ternaries without importing `<DetailPageShell>`. Escape hatch: a `// detail-page-shell-allow: <non-empty reason>` comment. Companion to the DataTable column-discipline and form-select-discipline guards; together they pin the three primitive extractions against regression-by-inlining.

## Study detail page — vertical stack

[`/studies/[id]`](../../ui/src/app/studies/[id]/page.tsx) renders a top-down stack: `<StudyHeader>` → `<OvernightResultCard>` (added by `feat_overnight_final_solution_phase2`, 2026-06-04) → `<LinkedEntitiesRow>` → optional proposal link → `<AutoFollowupChainPanel>` → `<ConfidencePanel>` → `<ConvergencePanel>` → `<TrialsCard>` → `<DigestPanel>` (gated on `status === 'completed'`). Each panel is independently mountable / hideable so a study that's still running shrinks gracefully without empty surfaces.

**Morning result card.** `<OvernightResultCard>` ([`ui/src/components/studies/overnight-result-card.tsx`](../../ui/src/components/studies/overnight-result-card.tsx)) returns `null` unless the auto-followup chain has terminated AND has at least 2 links. The predicate `shouldShowOvernightResultCard(chain)` is exported for direct unit testing. When visible, the card surfaces the rolled-up answer in one glance — headline lift via `formatSignedLift` (shared with the chain panel; see below), explored path tokens, best-config CTA (three-case render matrix per Phase 2 D-13), stop-reason phrase (shared map; see below), winning-link convergence chip (`<Badge variant="secondary">`), and a truncated narrative excerpt with a "View full digest →" link to `#digest` on the winning link's page. Hook order is invariant per Phase 2 D-19 (`useStudyChain` → `useStudyDigest` → predicate → early return); per-link `useTemplate` calls live in child components (`<PathTokenChip>`, `<WinningLinkConvergenceChip>`) per the Rules-of-Hooks discipline established by the chain panel's existing `<ChainLinkStrategyBadge>`.

**Shared chain-summary modules.** `feat_overnight_final_solution_phase2` Story 1 / FR-8 extracted two helpers previously inline in `<AutoFollowupChainPanel>` into shared modules consumed by both surfaces:
- [`ui/src/lib/chain-stop-reason.ts`](../../ui/src/lib/chain-stop-reason.ts) — `CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string>` mapping the six wire values to friendly phrases. Source-of-truth: [`backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS`](../../backend/app/domain/study/chain_summary.py).
- [`ui/src/lib/format-lift.ts`](../../ui/src/lib/format-lift.ts) — `formatSignedLift(value): string` returning `+0.NNNN` / `-0.NNNN` / `—` (4-decimal signed, no percent). Both the chain panel's cumulative-lift line and the new card's headline pull from this helper so the same number never appears in two different formats on the same page (Phase 2 D-12).

**Strategy line.** `<LinkedEntitiesRow>` gains a read-only `<StrategyLine>` after the four FK chips that surfaces `study.config.auto_followup_strategy` when set. Display mapping (`narrow` → *"Refine same knobs"*, `follow_suggestions` → *"Try suggested follow-ups"*) is keyed by the typed `OvernightStrategy` literal via `Record<OvernightStrategy, string>` exhaustiveness; unknown wire values are silently hidden per the spec's defensive-coercion contract. Glossary key `auto_followup_strategy_line` lives in `ui/src/lib/glossary.ts` alongside `overnight_result` (the card-title key).

## Dashboard demo-data nudge

`feat_home_first_run_demo_nudge` (2026-05-21) added a first-run experience layer on top of PR #182's `make up` auto-seed (`scripts/seed_meaningful_demos.py --if-empty`). Two surfaces:

**`<DemoDataBanner />`** — a self-contained dashboard banner mounted at [`ui/src/components/dashboard/demo-data-banner.tsx`](../../ui/src/components/dashboard/demo-data-banner.tsx). Renders above `<StartHereChecklist />` when (a) the first page of `GET /api/v1/clusters?sort=name:asc&limit=200` includes any name in `DEMO_CLUSTER_SLUGS` AND (b) the operator has not dismissed it via localStorage key `relyloop.home-first-run-demo-nudge.dismissed`. Hydration uses `useSyncExternalStore` with a conservative server snapshot (`true`) so pre-dismissed users never flash. Plural-aware body copy (1 / 2-3 / 4 demos present) via a pure helper at [`ui/src/lib/format-demo-cluster-prefix.ts`](../../ui/src/lib/format-demo-cluster-prefix.ts).

**Cluster demo indicator** — three rendering strategies depending on the underlying primitive:
1. `/clusters` list — renders `<DemoBadge />` JSX next to demo cluster names (via the `name` column cell in [`clusters-table.column-config.tsx`](../../ui/src/components/clusters/clusters-table.column-config.tsx)). Tooltip explains the seed origin; the badge is keyboard-focusable (`tabIndex={0}` + `role="img"` + `aria-label`).
2. Create-study modal cluster picker (`<EntitySelect>`) — appends `" (Demo)"` text suffix to the option label string (the primitive's `getLabel` returns `string`, not JSX).
3. Proposals-table cluster fk-select (`<DataTableFkSelect>` over native `<select>`) — same text-suffix strategy because native `<select>` doesn't accept JSX in `<option>`.

**Source-of-truth + CI guard.** The 4 demo cluster slugs (`acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`) live in exactly one frontend file ([`ui/src/lib/demo-data.ts`](../../ui/src/lib/demo-data.ts)) with a top-of-file comment citing the seed script's `SCENARIOS[*]["slug"]` literals (lines 129/245/343/456). A CI guard at [`scripts/ci/verify_demo_slug_parity.sh`](../../scripts/ci/verify_demo_slug_parity.sh) (wired into `.github/workflows/pr.yml` adjacent to `verify_enum_source_of_truth.sh`) fails the build if the two sides drift. The slugs are NOT wire values — they're frontend-only UX hints, deliberately separate from [`ui/src/lib/enums.ts`](../../ui/src/lib/enums.ts).

**Safe localStorage wrapper.** [`ui/src/lib/safe-local-storage.ts`](../../ui/src/lib/safe-local-storage.ts) wraps `getItem`/`setItem` with `typeof window` + try/catch, swallowing throws from Safari private mode and `QuotaExceededError`. The banner uses it through `useSyncExternalStore`; same-tab dismissals are tracked in a `useState` because the `storage` event doesn't fire for the writer tab.

**Phase 2 (shipped).** The "Reset to demo state" button + `POST /api/v1/_test/demo/reseed` endpoint shipped as [`feat_home_demo_reseed_endpoint`](../00_overview/implemented_features/2026_05_24_feat_home_demo_reseed_endpoint/feature_spec.md) (2026-05-24) — it refactored the CLI seed script's `docker compose exec psql` truncate path into an asyncpg-friendly module, the non-trivial scope originally split from the polish-layer PR.

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

When adding new tooltips on existing surfaces (Phase 2 / Phase 3 work — see [`feat_contextual_help/phase2_idea.md`](../00_overview/implemented_features/2026_05_15_feat_contextual_help_mvp2/phase2_idea.md) and [`phase3_idea.md`](../00_overview/implemented_features/2026_05_15_feat_contextual_help_mvp2/phase3_idea.md)), extend `glossary.ts` with new keys following the same naming convention (dotted, lowercase, `<scope>.<aggregate>` or `<scope>.<aggregate>.<wire_value>`) and add a parity-test case for any new enum group.

**Dual entries** (both `short` and `long` populated, type `GlossaryEntryDual`) feed both `InfoTooltip` and `HelpPopover` from a single key. The canonical example is `study.search_space` (added by `chore_create_study_wizard_polish`, 2026-05-19): the create-study wizard renders an `<InfoTooltip glossaryKey="study.search_space" />` adjacent to the Step-4 "Search space (JSON)" label and a `<HelpPopover glossaryKey="study.search_space" />` below the textarea — InfoTooltip reads `short`, HelpPopover reads `long`. Use this dual-entry pattern when a single concept benefits from both a label-adjacent one-liner AND a multi-paragraph reference body, rather than maintaining two separate keys with overlapping copy.

### Step-4 auto-fill (`chore_create_study_wizard_polish`)

The create-study wizard's Step 4 ("Search space") pre-fills the textarea from the selected template's `declared_params` using a deterministic naming-convention heuristic exported from [`ui/src/lib/search-space-defaults.ts`](../../ui/src/lib/search-space-defaults.ts) (`buildStarterSearchSpace`). The same module exports a TypeScript port of the backend's `estimate_cardinality()` (frozen against the Python source-of-truth via the shared JSON fixture at [`backend/tests/_fixtures/search_space_cardinality_fixtures.json`](../../backend/tests/_fixtures/search_space_cardinality_fixtures.json)), so the wizard guarantees its output validates against `SearchSpace.model_validate` (cardinality ≤ 10⁶) before the user ever clicks Next.

New glossary keys (all under `study.search_space.*`):

| Key | Shape | Surface |
|---|---|---|
| `study.search_space` | `GlossaryEntryDual` | Step-4 `<InfoTooltip>` (short) + `<HelpPopover>` (long) |
| `study.search_space.param_spec` | `GlossaryEntryShort` | Forward-compat hook — not surfaced by this chore; reserved for `feat_create_study_search_space_builder`'s per-row tooltips |
| `study.search_space.log` | `GlossaryEntryShort` | Same forward-compat hook |
| `study.search_space.cardinality` | `GlossaryEntryShort` | Same forward-compat hook |

The 6 existing `study.metric.<m>` entries gained a tier-specific k-applicability clause appended to `short`:

- `ndcg` / `precision` / `recall` — "Requires a top-k cutoff."
- `map` — "Top-k cutoff optional — set it for map@k, leave blank for full-recall MAP."
- `mrr` / `err` — "Top-k cutoff is not used."

These pair with the Step-5 tri-state k field, which renders required / optional (with a clearable "—" option) / hidden-with-caption based on a new `kTier(metric)` helper. Frontend / backend parity is locked by paired tests:

- `K_REQUIRED` (frontend) ↔ `_K_REQUIRED_METRICS` ([`backend/app/api/v1/schemas.py:474`](../../backend/app/api/v1/schemas.py)) — asserted by `ui/src/__tests__/components/studies/k-required.test.ts` and `backend/tests/contract/test_k_required_membership.py`.
- `K_IGNORED` (frontend) ↔ the metric token mapper at `backend/app/eval/scoring.py:32` — asserted by `ui/src/__tests__/components/studies/k-ignored.test.ts` and `backend/tests/unit/eval/test_scoring_metric_tokens.py`.

### Deep-link `?clone_from=<id>` (`feat_study_clone_from_previous`)

The `/studies` page reads an optional `?clone_from=<source_study_id>` query param. When present, it fetches `GET /api/v1/studies/{id}`, builds prefill via [`buildPrefillFromStudy`](../../ui/src/components/studies/prefill-from-study.ts), opens `CreateStudyModal` with `initialValues`, and clears the param via `router.replace('/studies')` so refresh / back-navigation doesn't reopen the modal. The reader lives inside `StudiesPageInner` under the `<Suspense>` boundary required by Next 16 `useSearchParams`, and uses a `useRef` one-shot so the effect doesn't re-fire on its own state writes. Invalid params (empty after trim, non-36-char length) and source-fetch errors (404 on a 36-char id that doesn't exist) all converge on the same "toast.error + `router.replace` + open empty modal" UX. The banner copy reads from the UI-only `PrefillValues.cloneSource` field — never from the editable `name` form value — so editing the name leaves the lineage label intact (D-12 in the feat spec). The submit-payload serializer is field-by-field on purpose: `cloneSource` is never spread into the wire payload, but both `parent` (proposal-followup lineage) and `parent_study_id` (clone lineage) are forwarded when set (the two axes are independent per D-5 / FR-10).

The entry-point button lives in `StudyActionBar` on the study-detail page (NOT on the digest panel — D-7 / FR-2 regression assertion guards this). Cloning a `running` source opens an `AlertDialog` (`data-testid="clone-running-confirm"`) before navigation (FR-11); terminal-state sources navigate directly.

### Step-4 derived-value toggles (`feat_study_clone_narrow_bounds`)

When the create-study wizard is in clone mode and the source study has a digest, Step 4 renders an opt-in "Narrow bounds around the source study's winning params (±20%)" checkbox above the existing search-space editor. The toggle is the canonical "derived-value" pattern: an opt-in transformation of a prefilled form field with restore-on-uncheck via a `useRef`. The transformation logic is a pure helper at [`ui/src/lib/narrow-bounds.ts`](../../ui/src/lib/narrow-bounds.ts) (`narrowBoundsAroundWinner(spaceJson, winnerParams, percent)`) that mirrors every per-type `SearchSpace.model_validate` constraint (FloatParam `low < high`, log-uniform `low > 0`, IntParam `low <= high`, categorical untouched) so the rewritten JSON is structurally valid by construction. On the modal side, the invariant is **capture-on-true** for the baseline (overwrite the ref on every `false → true`) and **clear-on-false** (nullify on every `true → false` and on modal close). Post-rewrite manual edits to the textarea are discarded on uncheck — intentional per the [feat_study_clone_narrow_bounds spec FR-6](../00_overview/implemented_features/2026_05_25_feat_study_clone_narrow_bounds/feature_spec.md). The FR-1 visibility gate (`cloneSource` present AND `useStudyDigest` success AND `recommended_config` non-empty) **hides** the surface entirely rather than disabling it when the gate is closed — a disabled affordance would falsely imply the operator could enable it.

The widened `useStudyDigest(studyId, { enabled? })` signature (mirroring `useStudy(id, { enabled })` at [`ui/src/lib/api/studies.ts`](../../ui/src/lib/api/studies.ts)) is what makes Rules-of-Hooks compliance work alongside the conditional gate: the hook is called unconditionally at the top of `CreateStudyModal`, and `enabled: Boolean(initialValues?.cloneSource?.id)` suppresses the network request on the non-clone path. Existing single-argument callers are unaffected by the additive opts arg.

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
  - [`feat_studies_ui/feature_spec.md`](../00_overview/implemented_features/2026_05_12_feat_studies_ui/feature_spec.md) — bulk of MVP1 screens
  - [`feat_proposals_ui/feature_spec.md`](../00_overview/implemented_features/2026_05_12_feat_proposals_ui/feature_spec.md) — proposals list + detail
  - [`feat_chat_agent/feature_spec.md`](../00_overview/implemented_features/2026_05_12_feat_chat_agent/feature_spec.md) — chat surface (also covers backend agent)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
