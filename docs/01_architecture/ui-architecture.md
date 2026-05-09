# UI Architecture

**Status:** Adopted for MVP1. Next.js 14 App Router + shadcn/ui + Tailwind + TanStack Query. Per-screen feature specs (`feat_studies_ui`, `feat_proposals_ui`, `feat_chat_agent`) implement the patterns documented here.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §22](../00_overview/product/relevance-copilot-spec.md) ("UI screens") and §28 ("Frontend stack").

---

## Tech stack (recap)

Per [`tech-stack.md` §"Frontend"](tech-stack.md):

| Layer | Choice |
|---|---|
| Framework | Next.js 14+ (App Router) |
| Language | TypeScript (`--strict` + `noUncheckedIndexedAccess`) |
| UI components | shadcn/ui (copied into repo, not npm dep) |
| Styling | Tailwind CSS |
| Server state | TanStack Query (caching, retries, optimistic updates) |
| Forms | React Hook Form + Zod |
| Charts | Recharts |
| Streaming | `fetch()` with `ReadableStream` (SSE-framed body over POST). Native `EventSource` is GET-only and unsuitable for the chat surface where the user message is in the request body. |
| Testing | vitest + msw |
| Lint | eslint (Next.js + security plugins) |

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

```
ui/
  app/                                # Next.js App Router pages
    layout.tsx                        # Root layout: shadcn theme provider, TanStack Query provider
    page.tsx                          # Dashboard
    chat/
      [conversation_id]/
        page.tsx
    clusters/
      page.tsx                        # List
      [id]/
        page.tsx                      # Detail
    studies/
      page.tsx
      [id]/
        page.tsx
        digest/
          page.tsx                    # Optional dedicated digest view
    proposals/
      page.tsx
      [id]/
        page.tsx
    query-sets/
      page.tsx
      [id]/
        page.tsx
    judgments/
      [id]/
        page.tsx
    templates/
      page.tsx
      [id]/
        page.tsx

  components/
    ui/                               # shadcn-generated primitives (Button, Card, Dialog, ...)
    studies/                          # study-specific compositions
    proposals/
    chat/
    common/                           # cross-cutting (StatusBadge, MetricDelta, ParameterImportanceChart)

  lib/
    api/                              # TanStack Query hooks per resource
      studies.ts                      # useStudies(), useStudy(id), useCreateStudy(), useCancelStudy()
      proposals.ts
      clusters.ts
      ...
    api-client.ts                     # base axios/fetch client with X-Request-ID injection
    types.ts                          # generated TS types from backend OpenAPI (via openapi-typescript)

  styles/
    globals.css                       # Tailwind base + theme overrides

  tests/
    e2e/                              # Playwright (MVP3+; MVP1 has no e2e)
    unit/                             # vitest specs co-located with components
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

**shadcn primitives** are copied into `ui/components/ui/` via `npx shadcn-ui add <component>`. Customizations happen in the copied source. We do NOT depend on `@shadcn-ui/<package>` from npm.

**Studies / Proposals / Chat compositions** live in `ui/components/<feature>/`. Each composition imports from `ui/components/ui/` for primitives and from `ui/components/common/` for cross-cutting (StatusBadge, MetricDelta, ParameterImportanceChart).

**Cross-cutting components** (used by 2+ features):
- `<StatusBadge status={...} />` — colored chip for `studies.status`, `proposals.status`, `pr_state`, etc.
- `<MetricDelta baseline={n} achieved={m} />` — formatted "0.612 → 0.762 (+24.5%)" with color
- `<ParameterImportanceChart data={...} />` — Recharts horizontal bar chart consuming `digests.parameter_importance`
- `<TrialsTable trials={...} sortBy={...} onSort={...} />` — sortable table with cursor pagination

## Auth surface (MVP1)

**None.** No login, no sessions, no role gates. The UI assumes the operator has full access to everything the API exposes.

**X-Request-ID** is injected into every API call by `ui/lib/api-client.ts` for log correlation per [`api-conventions.md` §"Trace / request correlation"](api-conventions.md). Optionally accepts a server-supplied `X-Request-ID` if present in the response.

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
