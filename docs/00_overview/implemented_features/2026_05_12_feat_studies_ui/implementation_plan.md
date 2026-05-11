# Implementation Plan — feat_studies_ui

**Date:** 2026-05-12
**Status:** Complete (PR #50, pending merge 2026-05-12). 13 of 13 stories shipped via `/impl-execute --all`. 3 GPT-5.5 plan-review cycles pre-execution; 32 of 33 findings accepted + applied, 1 rejected with cited counter-evidence.
**Primary spec:** [feature_spec.md](feature_spec.md) (drift-patched 2026-05-12 in this session)
**Policy sources:**
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — Next 16 + TanStack Query + shadcn patterns (the architecture doc's directory-layout block is stale — `ui/src/` is canonical per the 2026-05-12 frontend refresh; the plan follows the actual `ui/src/` layout)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — cursor pagination, error envelope, `X-Request-ID`
- [CLAUDE.md](../../../../CLAUDE.md) — frontend conventions, source-of-truth comment rule, never-bypass-LLM-abstraction rule (LLM-agnostic at this layer — the UI doesn't talk to OpenAI directly)

---

## 0) Planning principles

- **Server state is TanStack Query only.** No `useState` for server data. Mutations invalidate the relevant query keys on success.
- **Backend allowlists are the source of truth.** Every `<select>` / chip / badge that ships wire values to the backend MUST be grounded in an enumerated value from `backend/app/api/v1/schemas.py` (wire-side Literals). **Source-of-truth comments live ONLY in `ui/src/lib/enums.ts`** above the exported `as const` array. Zod schemas and component option lists consume the typed arrays via `z.enum(STUDY_STATUS_VALUES)` and `STUDY_STATUS_VALUES.map(...)` — they don't repeat the comment. The Story 4.2 CI grep gate scans `ui/src/lib/enums.ts` only (narrow, well-defined scope; no false positives on Zod call sites).
- **Cursor pagination contract.** Backend uses **forward-only opaque cursors** (`?cursor=<token>` → response `next_cursor` + `has_more`). The list-page pattern is **single-page `useQuery` keyed by the current cursor + client-side cursor stack** (NOT `useInfiniteQuery`, which is designed for infinite-scroll concatenation, not Prev/Next page-at-a-time tables and would require `getPreviousPageParam` the backend doesn't support). Pattern:

  ```ts
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursorStack[cursorStack.length - 1];
  const q = useQuery({
    queryKey: ["studies", { status, cluster_id, cursor, limit, since }],
    queryFn: () => apiClient.get("/api/v1/studies", { params: { status, cluster_id, cursor, limit, since } }),
  });
  // Page = q.data.data (single page); hasNext = q.data.has_more; totalCount = q.headers.get("X-Total-Count")
  // onNext: setCursorStack(s => [...s, q.data.next_cursor])
  // onPrev: setCursorStack(s => s.slice(0, -1))   // pops back to previous cursor
  // onFilterChange: setCursorStack([undefined])   // resets to first page
  ```

  `<CursorPaginator>` (Story 1.3) accepts `hasMore` + `onNext` + `onPrev` + `pageSize` + `onPageSizeChange` + `totalCount`. The stack-management logic lives in each page (small enough to inline).
- **Polling is bounded and caller-driven** (per spec §4): `useStudy(id, options?: { refetchInterval?: number })` and `useStudyTrials(id, options?: { sort?, cursor?, limit?, refetchInterval?: number })` accept an explicit `refetchInterval` arg. Pages compute the 3s-while-running rule themselves from `data?.status`. This matches the spec's hook contract and keeps the hook layer policy-free. The Study Detail page (Story 3.4) wraps the two hooks with `useEffect(() => setInterval(studyQuery.status === "running" ? 3000 : 0))` semantics via TanStack Query's `refetchInterval` derived from cached status — see Story 3.4 for the exact pattern.
- **No optimistic updates in MVP1.** Mutations show a loading state, then refetch on success. Reserved for MVP2+.
- **No `page.route()` mocking.** MVP1 has no E2E; component tests use msw for HTTP mocking inside Vitest, not Playwright route interception.
- **The `ui/` workspace uses the `src/` layout.** Everything new lives under `ui/src/`. The `@/` alias resolves to `ui/src/` (set in `ui/vitest.config.ts`).
- **Tailwind 4 CSS-first.** Design tokens live in `ui/src/app/globals.css` under `@theme {}` when needed. There is no `tailwind.config.ts`.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Layout + nav) | Epic 1 / Story 1.2 | Top nav with active-link highlight; shadcn `ThemeProvider`, TanStack Query `QueryClientProvider`, Toaster |
| FR-2 (Dashboard) | Epic 3 / Story 3.1 | Recent studies cards + open-proposals count + 7-day-completed count (all via `X-Total-Count`) |
| FR-3 (Studies list) | Epic 3 / Story 3.2 | Status filter chips grounded in `StudyStatusWire`; cursor pagination |
| FR-4 (Create-study modal) | Epic 3 / Story 3.3 | 5-step Zod-validated form; loads target list from `/clusters/{id}/schema` |
| FR-5 (Study detail) | Epic 3 / Story 3.4 | Live trials polling; cancel; digest panel with Recharts `<ParameterImportanceChart>` + Open-PR link-out |
| FR-6 (Clusters list+detail) | Epic 2 / Story 2.1 | Register-cluster modal; health-status badge |
| FR-7 (Query sets + CSV) | Epic 2 / Story 2.2 | Create modal w/ JSON or CSV upload; queries CRUD on detail |
| FR-8 (Templates view + fork) | Epic 2 / Story 2.3 | Fork-to-v+1 (immutability); prism-react-renderer syntax highlight; no in-place edit |
| FR-9 (Judgment Review) | Epic 2 / Story 2.4 | Source filter (`llm`/`human`); override popover; calibration modal w/ kappa display |
| FR-10 (API client + errors) | Epic 1 / Story 1.1 | `X-Request-ID` injection (UUIDv7), error toast, 503-retryable backoff (1s/2s/4s) |
| CI gate (AC-6, AC-9) | Epic 4 / Story 4.2 | `pr.yml` shell-grep job verifying source-of-truth comments |
| Docs | Epic 4 / Story 4.1 | `docs/03_runbooks/ui-debugging.md` + mvp1-user-stories.md US-22..US-24 marked Implemented |

**Single phase.** Spec §3 "Phase boundaries" defines one phase: ship the tutorial flow end-to-end in the UI. No deferred phases — nothing to track in a `phase2_idea.md`.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Four epics, 13 stories. Epic 1 ships foundations; Epic 2 ships the supporting screens (clusters/query-sets/templates/judgments); Epic 3 ships the studies surface (dashboard/list/create/detail); Epic 4 wraps with docs + the source-of-truth CI gate.

### Story-level requirements

Every story below specifies New files, Modified files, Endpoints consumed (no new endpoints — UI feature), Key interfaces (TS types + hook signatures), UI element inventory where applicable, Tasks, and Definition of Done.

### Project conventions (frontend)

```
- Server state via TanStack Query. No `useState` for fetched data.
- Mutations invalidate query keys on success via `qc.invalidateQueries({ queryKey: [...] })`.
- Use `apiClient` from `ui/src/lib/api-client.ts` — never bare `fetch`. The client injects `X-Request-ID` and wires error→toast.
- Pages live in `ui/src/app/<route>/page.tsx` (Next 16 App Router).
- Hooks live in `ui/src/lib/api/<resource>.ts` and are typed against `ui/src/lib/types.ts` (generated from OpenAPI).
- Cross-cutting components: `ui/src/components/common/`.
- Feature-specific components: `ui/src/components/studies/`, `ui/src/components/clusters/`, etc.
- shadcn primitives: `npx shadcn@latest add <name>` writes to `ui/src/components/ui/`.
- Every option array whose values are sent to the backend MUST have a source-of-truth comment: `// Values must match backend/app/api/v1/schemas.py StudyStatusWire`.
- Vitest tests live at `ui/src/**/*.test.{ts,tsx}` (the config glob — not `.spec.tsx`).
- No emoji in code or copy unless the user explicitly asks. shadcn primitives use Lucide icons.
- Tailwind 4 utilities are auto-detected from source paths. Custom tokens go in `globals.css` under `@theme {}`.
- Never hardcode model names. The UI never calls LLMs directly — judgment generation is a backend call.
```

### AI agent execution protocol

Standard execution order per the template:
0. Load `architecture.md`, `state.md`, this plan, and the spec.
1. Read story scope (Outcome, New files, Endpoints, DoD).
2. Implement: types/schemas → hooks → components → pages → tests.
3. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test` after each story.
4. Verify each new option array carries a source-of-truth comment matching the grep gate in Story 4.2.
5. Update `state.md` after the final story per §4.

---

## Epic 1 — Foundations

Outcomes from this epic:
- API client with `X-Request-ID` injection, error→toast wiring, 503 retry.
- Generated TypeScript types from the FastAPI OpenAPI schema (`ui/src/lib/types.ts`).
- Layout shell with providers (theme, TanStack Query, Toaster) and top nav.
- Cross-cutting components (`<StatusBadge>`, `<MetricDelta>`, `<CursorPaginator>`, `<EmptyState>`, plus the enum allowlists used everywhere).

**Epic 1 gate:** `pnpm typecheck && pnpm lint && pnpm test` green, `pnpm dev` renders the new layout with the placeholder route still working as a child page.

### Story 1.1 — API client + generated types + dev dependencies

**Outcome:** A typed `apiClient` exists at `ui/src/lib/api-client.ts` injecting `X-Request-ID: <UUIDv7>`, intercepting structured error envelopes, and retrying 503-retryable + network-failure responses with exponential backoff. **Retry contract: 1 initial attempt + 3 retries = 4 total attempts, with waits of 1000ms / 2000ms / 4000ms before retries #1, #2, #3.** OpenAPI types are generated into `ui/src/lib/types.ts` via an `openapi-typescript` script.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api-client.ts` | Base fetch wrapper: `X-Request-ID` injection, JSON encode/decode, 4xx/5xx → `ApiError` with `error_code` + `message` + `retryable`, 503-retryable backoff |
| `ui/src/lib/api-errors.ts` | `ApiError` class + `isApiError` type guard + `toToastMessage(error)` helper |
| `ui/src/lib/uuid.ts` | UUIDv7 generator (small inline impl or `uuid-utils` equivalent — see Tasks) |
| `ui/src/lib/types.ts` | **Generated** from FastAPI OpenAPI; committed (no runtime fetch). Header comment: `// GENERATED FILE — do not edit. Regenerate via: pnpm types:gen` |
| `ui/src/__tests__/lib/api-client.test.ts` | Vitest+msw: `X-Request-ID` header present on every request; 4xx body translated to `ApiError`; 503-retryable invokes **4 total attempts (1 initial + 3 retries with 1s/2s/4s waits)** with mocked timers; 503-non-retryable invokes 1 attempt; network failure (`HttpResponse.error()`) invokes 4 total attempts |
| `ui/src/__tests__/lib/api-errors.test.ts` | `isApiError` recognizes the envelope; `toToastMessage` formats `error_code` + `message` |

**Modified files**

| File | Change |
|---|---|
| `ui/package.json` | Add deps + scripts. **Tilde-pin frontend libraries that move fast**: `"@tanstack/react-query": "~5.62.0"`, `"@tanstack/react-query-devtools": "~5.62.0"`, `"sonner": "~1.7.0"`, `"react-hook-form": "~7.54.0"`, `"@hookform/resolvers": "~3.10.0"`, `"zod": "~3.24.0"`, `"recharts": "~2.15.0"`, `"react-markdown": "~9.0.0"`, `"remark-gfm": "~4.0.0"`, `"prism-react-renderer": "~2.4.0"`. Dev deps: `"openapi-typescript": "~7.5.0"`, `"msw": "~2.7.0"`. Add scripts: `"types:gen": "openapi-typescript http://localhost:8000/openapi.json -o src/lib/types.ts"` and `"test:watch": "vitest"`. Tilde-pinning isolates patches within a minor (`~5.62.0` accepts `5.62.x` but not `5.63.0`) to neutralize the TanStack-minor-drift risk in §6. |
| `ui/src/__tests__/setup.ts` | Add msw server setup (`beforeAll`/`afterAll`/`afterEach`) — referenced by every component test |

**Endpoints**

None added. The client *consumes* the existing backend; this story does not change the API surface.

**Key interfaces**

```ts
// ui/src/lib/api-client.ts
export type ApiClientOptions = {
  baseUrl?: string;          // default: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
  fetchImpl?: typeof fetch;  // injection point for tests (msw uses global fetch by default)
};

export interface ApiClient {
  get<T>(path: string, init?: RequestInit & { params?: Record<string, string | number | undefined> }): Promise<{ data: T; headers: Headers }>;
  post<T>(path: string, body: unknown, init?: RequestInit): Promise<{ data: T; headers: Headers }>;
  patch<T>(path: string, body: unknown, init?: RequestInit): Promise<{ data: T; headers: Headers }>;
  delete<T>(path: string, init?: RequestInit): Promise<{ data: T; headers: Headers }>;
  postCsv<T>(path: string, csvBody: string, init?: RequestInit): Promise<{ data: T; headers: Headers }>;
}

export function createApiClient(options?: ApiClientOptions): ApiClient;
export const apiClient: ApiClient;  // default singleton

// ui/src/lib/api-errors.ts
export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;     // e.g. "CLUSTER_UNREACHABLE"
  readonly retryable: boolean;
  readonly requestId: string | null;  // from response X-Request-ID
}
export function isApiError(value: unknown): value is ApiError;
export function toToastMessage(err: unknown): string;

// ui/src/lib/uuid.ts
export function uuidv7(): string;
```

**Tasks**
1. `cd ui && pnpm add @tanstack/react-query @tanstack/react-query-devtools sonner zod react-hook-form @hookform/resolvers recharts react-markdown remark-gfm prism-react-renderer && pnpm add -D openapi-typescript msw`
2. Write `ui/src/lib/uuid.ts` — inline UUIDv7 generator per RFC 9562 §5.7. **Byte layout (16 bytes total):** bytes 0-5 = `unix_ts_ms` (48 bits big-endian); byte 6 = `(0x70 | (rand_a_high4 & 0x0F))` (high nibble = version 7, low nibble = `rand_a[0:4]`); byte 7 = `rand_a[4:12]` (low 8 bits of the 12-bit rand_a); byte 8 = `(0x80 | (rand_b_high6 & 0x3F))` (top two bits = variant `10`, bottom 6 = `rand_b[0:6]`); bytes 9-15 = `rand_b[6:62]` (remaining 56 bits of the 62-bit rand_b). Generate randomness via `crypto.getRandomValues(new Uint8Array(10))` then mask in the version + variant bits. Format output as the canonical hyphenated 8-4-4-4-12 hex string. No external dep needed. Add a unit test asserting (a) the first 12 hex chars match the unix-ms timestamp, (b) the version nibble equals `7`, (c) the variant high-2-bits equal `10`.
3. Write `ui/src/lib/api-errors.ts` with `ApiError`, `isApiError`, `toToastMessage`.
4. Write `ui/src/lib/api-client.ts`:
   - Each method composes URL: `${baseUrl}${path}${searchParams ? "?" + qs : ""}`
   - Headers always include `Content-Type: application/json` (except `postCsv` which uses `text/csv`), `Accept: application/json`, `X-Request-ID: uuidv7()`.
   - `postCsv(path, csvBody)` specifically: pass `csvBody` as the raw request body (not JSON-stringified), set `Content-Type: text/csv`, accept `application/json` for the response. Used by `POST /query-sets` and `POST /query-sets/{id}/queries` when the operator uploads CSV.
   - On non-2xx: parse JSON body; if matches `{detail: {error_code, message, retryable}}`, throw `ApiError`; otherwise throw `ApiError` with `errorCode='INTERNAL_ERROR'`.
   - **Retry policy (covers spec FR-10 + AC-8):**
     - **Contract:** 1 initial attempt + up to 3 retries = **4 total attempts max**, with waits of 1000ms / 2000ms / 4000ms before retries #1 / #2 / #3.
     - **503 + `retryable=true`:** apply the retry contract above. After the 4th attempt fails, throw the last `ApiError`.
     - **Network failure** (`fetch` rejects with `TypeError` — connection refused, DNS, AbortError other than user-issued): apply the same retry contract. After the 4th attempt fails, throw `ApiError(errorCode='SERVICE_UNAVAILABLE', retryable=true, status=0)`.
     - **4xx (non-503) and 5xx (non-503-retryable):** throw immediately (no retries).
     - Per-attempt timeout: `AbortSignal.timeout(30_000)`.
   - Return `{data, headers}` so callers can read `X-Total-Count`.
5. Write `ui/src/__tests__/setup.ts`: msw server `setupServer()`, `beforeAll(() => server.listen())`, `afterEach(() => server.resetHandlers())`, `afterAll(() => server.close())`.
6. Write `ui/src/__tests__/lib/api-client.test.ts`: verify X-Request-ID always present; verify 4xx envelope → `ApiError`; verify 503-retryable → **4 total attempts (1 initial + 3 retries, with `vi.advanceTimersByTime(1000)` / `2000` / `4000` between retries)**; verify 503-non-retryable → 1 attempt only; verify network failure (`HttpResponse.error()`) → 4 total attempts then `ApiError(SERVICE_UNAVAILABLE)`; verify `X-Total-Count` is exposed on `headers`.
7. Write `ui/src/__tests__/lib/api-errors.test.ts`.
8. Generate `ui/src/lib/types.ts`:
   - **Prerequisite:** the backend must be running at `http://localhost:8000` (`make up` succeeded, `/healthz` returns 200). If a contributor regenerates locally without `make up`, the script fails with a clear error.
   - Run `cd ui && pnpm types:gen` to fetch `http://localhost:8000/openapi.json` and write `src/lib/types.ts`.
   - Prepend a `// GENERATED FILE — do not edit. Regenerate via: cd ui && pnpm types:gen` banner.
   - Commit the file. CI does NOT regenerate (no `make up` in CI) — the committed file is the source of truth for the PR.
9. Run `pnpm typecheck && pnpm lint && pnpm test`.

**Definition of Done**
- [ ] `apiClient` available; all five methods (`get` / `post` / `patch` / `delete` / `postCsv`) covered by unit tests.
- [ ] Every `apiClient` request sends `X-Request-ID` (test asserts via msw handler inspecting headers).
- [ ] 503-retryable executes 4 total attempts (1 initial + 3 retries with 1s/2s/4s waits) then fails with the last `ApiError` (test uses fake timers).
- [ ] Network failure (msw `HttpResponse.error()`) executes 4 total attempts then throws `ApiError(errorCode='SERVICE_UNAVAILABLE', status=0)`.
- [ ] 503-non-retryable and other 4xx/5xx throw on the first attempt.
- [ ] `ui/src/lib/types.ts` exists and is committed.
- [ ] `pnpm typecheck` green; `pnpm lint` green; `pnpm test` green.

**Centralized error-toast wiring (FR-10).** The `apiClient` throws `ApiError`; the `QueryProvider` in Story 1.2 constructs a `QueryClient` with **QueryCache + MutationCache global error handlers** (TanStack Query v5 removed `defaultOptions.queries.onError`; the cache-level handlers are the canonical v5 pattern):

```ts
// ui/src/components/providers/query-provider.tsx
import { QueryCache, QueryClient, MutationCache, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import { isApiError, toToastMessage } from "@/lib/api-errors";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: true },
  },
  queryCache: new QueryCache({
    onError: (err, query) => {
      if (!isApiError(err)) {
        toast.error("Unknown error");
        return;
      }
      const suppress = (query.meta?.suppressErrorCodes as string[] | undefined) ?? [];
      if (suppress.includes(err.errorCode)) return;
      if (query.meta?.suppressGlobalErrorToast) return;
      toast.error(toToastMessage(err));
    },
  }),
  mutationCache: new MutationCache({
    onError: (err, _vars, _ctx, mutation) => {
      if (!isApiError(err)) {
        toast.error("Unknown error");
        return;
      }
      if (mutation.meta?.suppressGlobalErrorToast) return;
      toast.error(toToastMessage(err));
    },
  }),
});
```

**Suppression mechanisms:**
- `meta.suppressErrorCodes: ["DIGEST_NOT_READY"]` — query-level; the named codes don't toast (used by `useStudyDigest` in Story 3.4 — the 404-while-running case stays silent).
- `meta.suppressGlobalErrorToast: true` — for mutations or queries whose callers handle error display via inline form state instead of toasting. **Modal mutation callers do NOT add their own `toast.error` in `onError`** — they let the global handler toast and use their `onError` only to keep the modal open / set inline error state. This avoids duplicate toasts (one global, one local).

### Story 1.2 — Layout shell + providers + top navigation

**Outcome:** `ui/src/app/layout.tsx` mounts a `<QueryClientProvider>`, shadcn `<ThemeProvider>`, and `<Toaster>` (sonner) around a top-nav scaffolded with shadcn primitives. Active-link highlighting via `usePathname()`. Placeholder home page from `infra_foundation` is replaced by the new dashboard (Story 3.1) — for this story, `page.tsx` becomes a TanStack-Query-aware "Welcome — see /studies" stub that will be overwritten in Story 3.1.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/providers/query-provider.tsx` | `"use client"` — wraps children in `<QueryClientProvider>` with `staleTime: 30_000`, `refetchOnWindowFocus: true`; mounts `<ReactQueryDevtools>` in development |
| `ui/src/components/providers/theme-provider.tsx` | `"use client"` — thin re-export of `next-themes`'s `ThemeProvider`; default `attribute="class"`, `defaultTheme="light"`, `enableSystem` |
| `ui/src/components/layout/top-nav.tsx` | `"use client"` — top bar with links to `/`, `/clusters`, `/query-sets`, `/templates`, `/studies`, `/proposals`, `/chat`. Active link highlighted via `usePathname()`. Uses shadcn `<NavigationMenu>` primitive |
| `ui/src/components/ui/sonner.tsx` | shadcn-generated Toaster wrapper (via `npx shadcn@latest add sonner`) |
| `ui/src/components/ui/button.tsx` | shadcn `Button` primitive (`npx shadcn@latest add button`) — used by every page |
| `ui/src/components/ui/navigation-menu.tsx` | shadcn `NavigationMenu` primitive |
| `ui/src/lib/utils.ts` | shadcn-conventional `cn()` helper combining `clsx` + `tailwind-merge` |
| `ui/src/__tests__/components/layout/top-nav.test.tsx` | Renders 7 links; `usePathname()` mocked → active link gets `data-state="active"` |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/layout.tsx` | Wrap `{children}` in `<ThemeProvider><QueryProvider><Toaster /><TopNav />{children}</QueryProvider></ThemeProvider>` |
| `ui/src/app/page.tsx` | Replace placeholder with a "Welcome — Studies coming online" card linking to `/studies`. (Real dashboard lands in Story 3.1; this avoids a 404 on `/` between stories.) |
| `ui/package.json` | Add `next-themes` `^0.4` to dependencies |
| `ui/src/app/globals.css` | Add shadcn-conventional `@theme {}` block defining the CSS variables shadcn uses (`--background`, `--foreground`, `--primary`, etc.); add `.dark` overrides |

**Endpoints**

None consumed by the layout shell itself. (Top nav is static link list.)

**Key interfaces**

```ts
// ui/src/components/providers/query-provider.tsx
export function QueryProvider({ children }: { children: React.ReactNode }): JSX.Element;

// ui/src/components/layout/top-nav.tsx
export const NAV_ITEMS: readonly { href: string; label: string }[];
export function TopNav(): JSX.Element;
```

**UI element inventory (top-nav)**

| Element | Type | Source | Behavior |
|---|---|---|---|
| Logo / brand | `<Link href="/">` text "RelyLoop" | static | Click → home |
| "Dashboard" link | `<NavigationMenuLink href="/">` | static | Active when `pathname === "/"` |
| "Clusters" link | `<NavigationMenuLink href="/clusters">` | static | Active when `pathname.startsWith("/clusters")` |
| "Query Sets" link | `<NavigationMenuLink href="/query-sets">` | static | Active when `pathname.startsWith("/query-sets")` |
| "Templates" link | `<NavigationMenuLink href="/templates">` | static | Active when `pathname.startsWith("/templates")` |
| "Studies" link | `<NavigationMenuLink href="/studies">` | static | Active when `pathname.startsWith("/studies")` |
| "Proposals" link | `<NavigationMenuLink href="/proposals">` | static | Active when `pathname.startsWith("/proposals")` — links into `feat_proposals_ui`'s routes which 404 in MVP1 until that feature ships; acceptable |
| "Chat" link | `<NavigationMenuLink href="/chat">` | static | Active when `pathname.startsWith("/chat")` — same caveat |

**Tasks**
1. `cd ui && pnpm add next-themes && npx shadcn@latest init` (accept defaults — writes `components.json`, updates `globals.css` with shadcn variables, creates `lib/utils.ts`).
2. `npx shadcn@latest add button navigation-menu sonner` — copies primitives into `ui/src/components/ui/`.
3. Write `query-provider.tsx`. Mount Devtools only when `process.env.NODE_ENV === "development"`.
4. Write `theme-provider.tsx`.
5. Write `top-nav.tsx` with the `NAV_ITEMS` array and `usePathname()` active-link logic. Use `cn()` from `lib/utils.ts` to merge active vs inactive classes.
6. Update `layout.tsx` — wrap providers in order: `<ThemeProvider><QueryProvider><TopNav />{children}<Toaster richColors closeButton /></QueryProvider></ThemeProvider>`. **Set `<html lang="en" suppressHydrationWarning>`** — `next-themes` injects a `class` attribute on `<html>` from inline script before React hydrates, and without `suppressHydrationWarning` React 19's strict-mode rendering logs an `Extra attributes from the server` console warning that fails the `pnpm build` strict-mode SSR pass. This is the standard `next-themes` integration pattern.
7. Replace `page.tsx` body with a small `<Card>`-based welcome panel.
8. Write `top-nav.test.tsx` — mock `usePathname` (Vitest `vi.mock('next/navigation', ...)`); assert 7 links rendered; assert active item carries `data-active="true"` (or whatever attr `<NavigationMenuLink>` sets).
9. Manual smoke: `pnpm dev` → `/` renders welcome panel inside the layout; clicking each nav link navigates correctly (proposals/chat 404 expected).

**Definition of Done**
- [ ] `/` renders the welcome panel inside the new layout shell.
- [ ] All 7 nav links present; active highlighting works (verified by test).
- [ ] `<Toaster />` is mounted (no visible toast, but the DOM contains the toaster portal — assert by rendering a triggering child in the test).
- [ ] `<QueryClientProvider>` available to all child trees (assert by rendering a `useQuery` consumer in the test and verifying it doesn't throw "No QueryClient set").
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green (build catches SSR / RSC violations).

### Story 1.3 — Cross-cutting components + canonical enum allowlists

**Outcome:** `<StatusBadge>`, `<MetricDelta>`, `<CursorPaginator>`, `<EmptyState>` available for every page. A single `ui/src/lib/enums.ts` file holds the wire-value arrays mirroring the backend Literals — each with the required source-of-truth comment. Every status badge variant maps to a documented color.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/enums.ts` | All UI-side wire-value arrays. One exported `const` array per backend Literal, each preceded by a `// Values must match …` comment. See "Enumerated value contract" below. |
| `ui/src/components/common/status-badge.tsx` | `<StatusBadge kind="study" value={status} />` — renders shadcn `<Badge>` with variant determined by kind+value. Supports `kind` = `"study"` \| `"trial"` \| `"proposal"` \| `"proposal_pr"` \| `"judgment_list"` \| `"health"`. |
| `ui/src/components/common/metric-delta.tsx` | `<MetricDelta baseline={n} achieved={m} />` — formats "0.612 → 0.762 (+24.5%)" with green/red sign |
| `ui/src/components/common/cursor-paginator.tsx` | `<CursorPaginator hasMore={bool} onPrev={?fn} onNext={?fn} pageSize=50 onPageSizeChange={fn} totalCount={?n} />` |
| `ui/src/components/common/empty-state.tsx` | `<EmptyState title message action? />` — used by every "Backend unreachable" and "No data yet" fallback (AC-8) |
| `ui/src/components/ui/badge.tsx` | shadcn primitive |
| `ui/src/components/ui/card.tsx` | shadcn primitive |
| `ui/src/components/ui/select.tsx` | shadcn primitive |
| `ui/src/__tests__/lib/enums.test.ts` | Asserts each exported array contains exactly the expected wire values (a contract-style frontend assertion to catch local drift even before CI grep) |
| `ui/src/__tests__/components/common/status-badge.test.tsx` | For each kind+value combo, asserts the rendered badge has the documented color class / variant |
| `ui/src/__tests__/components/common/metric-delta.test.tsx` | Formatting: positive, negative, zero, baseline=0 (no-delta case) |
| `ui/src/__tests__/components/common/cursor-paginator.test.tsx` | Prev/Next disabled states; page-size select change fires callback; total count display |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/layout/top-nav.tsx` | Use `<Badge>` from new shadcn primitive if any nav-badge work needs it (likely no change — kept for symmetry) |

**Endpoints**

None.

**Key interfaces**

```ts
// ui/src/lib/enums.ts

// Values must match backend/app/api/v1/schemas.py StudyStatusWire.
export const STUDY_STATUS_VALUES = ["queued", "running", "completed", "cancelled", "failed"] as const;
export type StudyStatus = (typeof STUDY_STATUS_VALUES)[number];

// Values must match backend/app/api/v1/schemas.py TrialStatusWire.
export const TRIAL_STATUS_VALUES = ["complete", "failed", "pruned"] as const;

// Values must match backend/app/api/v1/schemas.py TrialSortKey.
export const TRIAL_SORT_VALUES = [
  "primary_metric_desc",
  "primary_metric_asc",
  "created_at_desc",
  "created_at_asc",
  "trial_number_asc",
] as const;

// Values must match backend/app/api/v1/schemas.py EngineTypeWire.
export const ENGINE_TYPE_VALUES = ["elasticsearch", "opensearch"] as const;

// Values must match backend/app/api/v1/schemas.py AuthKind.
export const AUTH_KIND_VALUES = ["es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4"] as const;

// Values must match backend/app/api/v1/schemas.py Environment.
export const ENVIRONMENT_VALUES = ["prod", "staging", "dev"] as const;

// Values must match backend/app/api/v1/schemas.py HealthStatusValue.
export const HEALTH_STATUS_VALUES = ["green", "yellow", "red", "unreachable"] as const;

// Values must match backend/app/eval/types.py SamplerKind.
// (Re-exported by backend/app/api/v1/schemas.py — eval/types.py is the canonical definition per spec §8.1.)
export const SAMPLER_VALUES = ["tpe", "random"] as const;

// Values must match backend/app/eval/types.py PrunerKind.
export const PRUNER_VALUES = ["median", "none"] as const;

// Values must match backend/app/api/v1/schemas.py ObjectiveMetric.
export const OBJECTIVE_METRIC_VALUES = ["ndcg", "map", "precision", "recall", "mrr", "err"] as const;

// Values must match backend/app/api/v1/schemas.py ObjectiveK.
export const OBJECTIVE_K_VALUES = [1, 3, 5, 10, 20, 50, 100] as const;

// Values must match backend/app/api/v1/schemas.py ObjectiveDirection.
export const OBJECTIVE_DIRECTION_VALUES = ["maximize", "minimize"] as const;

// Values must match backend/app/api/v1/schemas.py JudgmentListStatusWire.
export const JUDGMENT_LIST_STATUS_VALUES = ["generating", "complete", "failed"] as const;

// Values must match backend/app/api/v1/schemas.py JudgmentSourceFilterWire.
export const JUDGMENT_SOURCE_FILTER_VALUES = ["llm", "human"] as const;

// Values must match backend/app/api/v1/schemas.py JudgmentSourceWire.
export const JUDGMENT_SOURCE_VALUES = ["llm", "human", "click"] as const;

// Values must match backend/app/api/v1/schemas.py RatingWire.
export const RATING_VALUES = [0, 1, 2, 3] as const;

// Values must match backend/app/api/v1/schemas.py ProposalStatusWire.
export const PROPOSAL_STATUS_VALUES = ["pending", "pr_opened", "pr_merged", "rejected"] as const;

// Values must match backend/app/api/v1/schemas.py ProposalPrStateWire.
export const PROPOSAL_PR_STATE_VALUES = ["open", "closed", "merged"] as const;

// Values must match backend/app/api/v1/schemas.py ConfigRepoProviderWire.
export const CONFIG_REPO_PROVIDER_VALUES = ["github"] as const;
```

**Status-badge color mapping** (documented so visual reviewers know what's intended):

| Kind | Value | Variant |
|---|---|---|
| study | queued | secondary (gray) |
| study | running | default (blue) |
| study | completed | success (green) |
| study | cancelled | outline (muted) |
| study | failed | destructive (red) |
| trial | complete | success |
| trial | pruned | secondary |
| trial | failed | destructive |
| proposal | pending | secondary |
| proposal | pr_opened | default |
| proposal | pr_merged | success |
| proposal | rejected | outline |
| proposal_pr | open | default |
| proposal_pr | closed | outline |
| proposal_pr | merged | success |
| judgment_list | generating | default |
| judgment_list | complete | success |
| judgment_list | failed | destructive |
| health | green | success |
| health | yellow | warning (amber) |
| health | red | destructive |
| health | unreachable | secondary |

**Tasks**
1. `npx shadcn@latest add badge card select` — primitives.
2. Write `lib/enums.ts` exactly as shown above (each block with the source-of-truth comment line above it).
3. Write `status-badge.tsx`. Implement a lookup table for the 22 (kind,value) combinations. Add `warning` variant to shadcn `Badge` if missing (small extension; document in the file).
4. Write `metric-delta.tsx`. Format: `{baseline.toFixed(3)} → {achieved.toFixed(3)} ({sign}{deltaPct.toFixed(1)}%)`. `baseline === 0` case shows "(new)" instead of an infinite percent.
5. Write `cursor-paginator.tsx`. Prev disabled when no `onPrev` provided; Next disabled when `hasMore === false`. Page-size select uses `{50, 100, 200}`.
6. Write `empty-state.tsx`. Centered title + message + optional action button.
7. Write the four test files. The `enums.test.ts` test is a belt-and-braces check that runs locally before the CI grep gate fires.
8. `pnpm typecheck && pnpm lint && pnpm test`.

**Definition of Done**
- [ ] All four cross-cutting components plus enums published; no other epic blocks on them.
- [ ] `enums.test.ts` asserts the wire-value arrays match the documented spec table (catches drift before CI).
- [ ] StatusBadge tests cover every (kind, value) combo in the table above.
- [ ] CursorPaginator tests verify Prev/Next disabled states and page-size callback.

---

## Epic 2 — Clusters + Query Sets + Templates + Judgments

Outcomes from this epic:
- All non-study screens shipped: clusters list+detail, query-sets list+detail+queries, templates list+detail+fork, judgments review+override+calibration.
- Every fetch goes through `apiClient`; every mutation invalidates the right query keys.
- Spec FRs 6, 7, 8, 9 fully covered.

**Epic 2 gate:** From a fresh `make up` + seeded `local-es`, an operator can register a cluster, create a query set with CSV upload, fork a template, generate judgments, and override a judgment — all via the UI. `pnpm test` green.

### Story 2.1 — Clusters list + register modal + detail page

**Outcome:** `/clusters` lists registered clusters with health badges; "Register cluster" opens a modal that POSTs to `/api/v1/clusters`, polls health, surfaces `CLUSTER_UNREACHABLE` toasts, and refreshes the list. `/clusters/{id}` shows summary + studies-by-this-cluster table.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/clusters.ts` | TanStack Query hooks: `useClusters({cursor?, limit?, since?})`, `useCluster(id)`, `useRegisterCluster()`, `useClusterSchema(id, target?)` |
| `ui/src/lib/api/config-repos.ts` | `useConfigRepos()`, `useCreateConfigRepo()` (used by the register modal's repo-association dropdown) |
| `ui/src/app/clusters/page.tsx` | Server component shell + client child loading clusters via hook |
| `ui/src/app/clusters/[id]/page.tsx` | Detail page |
| `ui/src/components/clusters/clusters-table.tsx` | Client component rendering the list table with status badges |
| `ui/src/components/clusters/register-cluster-modal.tsx` | shadcn `<Dialog>` + React Hook Form + Zod validation |
| `ui/src/components/clusters/cluster-detail-summary.tsx` | Summary card |
| `ui/src/components/clusters/studies-by-cluster-table.tsx` | Filtered studies list (calls `useStudies({cluster_id})`) |
| `ui/src/components/ui/dialog.tsx` | shadcn primitive |
| `ui/src/components/ui/input.tsx` | shadcn primitive |
| `ui/src/components/ui/form.tsx` | shadcn primitive (React Hook Form wrapper) |
| `ui/src/__tests__/app/clusters/page.test.tsx` | List rendering + filter chip behavior |
| `ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx` | Form validation; `CLUSTER_UNREACHABLE` toast on backend rejection |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/status-badge.tsx` | (no change — health kind already supported in Story 1.3) |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/clusters?cursor&limit&since` | List page data + dashboard recent studies' cluster names |
| `GET` | `/api/v1/clusters/{cluster_id}` | Detail page |
| `POST` | `/api/v1/clusters` | Register cluster |
| `GET` | `/api/v1/clusters/{cluster_id}/schema` | Used by create-study Step 1 (Story 3.3) — exported here for reuse |
| `GET` | `/api/v1/config-repos` | Register modal's repo-association dropdown (`config_repo_id` is optional on `CreateClusterRequest`) |
| `POST` | `/api/v1/config-repos` | Inline "Create new config repo" action in the modal (optional) |

**Error codes surfaced via toast:** `VALIDATION_ERROR`, `CLUSTER_NAME_TAKEN`, `CLUSTER_UNREACHABLE`, `AUTH_REF_NOT_FOUND`, `INVALID_AUTH_CONFIG`, `CONFIG_REPO_NOT_FOUND`, `RESOURCE_NOT_FOUND`, `INTERNAL_ERROR` — all delegated to `toToastMessage(err)`.

**Key interfaces**

```ts
// ui/src/lib/api/clusters.ts
import { components } from "@/lib/types";
type ClusterSummary = components["schemas"]["ClusterSummary"];
type ClusterDetail  = components["schemas"]["ClusterDetail"];
type CreateClusterRequest = components["schemas"]["CreateClusterRequest"];

export function useClusters(filter?: { cursor?: string; limit?: number; since?: string }): UseQueryResult<{data: ClusterSummary[]; next_cursor: string | null; has_more: boolean; totalCount: number}>;
export function useCluster(id: string): UseQueryResult<ClusterDetail>;
export function useRegisterCluster(): UseMutationResult<ClusterDetail, ApiError, CreateClusterRequest>;
export function useClusterSchema(id: string, target?: string): UseQueryResult<ClusterSchemaResponse>;
```

**Zod schema for register-cluster form** (mirrors `CreateClusterRequest` shape but with frontend-friendly defaults):

```ts
// Wire-value arrays are imported from `@/lib/enums` (where the canonical
// source-of-truth comments live). Zod schemas just reference the typed arrays.
const RegisterClusterSchema = z.object({
  name: z.string().min(1).max(120),
  engine_type: z.enum(ENGINE_TYPE_VALUES),
  environment: z.enum(ENVIRONMENT_VALUES),
  endpoint_url: z.string().url(),
  auth_kind: z.enum(AUTH_KIND_VALUES),
  auth_ref: z.string().min(1),
  config_repo_id: z.string().uuid().optional(),
  notes: z.string().max(2000).optional(),
});
```

**UI element inventory (register-cluster modal)**

| Element | Type | Source | Behavior |
|---|---|---|---|
| Name | `<Input>` | form | Required; 1–120 chars |
| Engine type | `<Select>` | `ENGINE_TYPE_VALUES` | Required |
| Environment | `<Select>` | `ENVIRONMENT_VALUES` | Required |
| Endpoint URL | `<Input type="url">` | form | Required; http/https |
| Auth kind | `<Select>` | `AUTH_KIND_VALUES` | Required; constrained by chosen engine (see backend `_VALID_AUTH_FOR_ENGINE`) — show inline help text |
| Auth ref (file name) | `<Input>` | form | Required; must exist as `./secrets/<auth_ref>` server-side |
| Config repo (optional) | `<Select>` with "Create new…" | `useConfigRepos()` | Optional; "Create new…" opens secondary modal |
| Notes | `<Textarea>` | form | Optional |
| Submit button | `<Button>` | form | Disabled when invalid or in-flight; shows "Registering…" |

**Tasks**
1. `npx shadcn@latest add dialog input form textarea` — primitives (textarea ships under `form` or via `add textarea`).
2. Write `clusters.ts` hooks. Use single-page `useQuery` keyed by `{cursor, limit, since}` for the list (per §0 cursor-pagination contract — NOT `useInfiniteQuery`); `useQuery` for detail. Mutation invalidates `["clusters"]`.
3. Write `config-repos.ts` hooks similarly.
4. Write `register-cluster-modal.tsx` with React Hook Form + Zod resolver. On submit: `mutate(values)`. **Error toasts come from the global MutationCache handler** — the modal does not call `toast.error` itself. On error the modal stays open (no `onError` close handler), surfacing whatever inline form state is appropriate. On success:
   - Backend returns the new `ClusterDetail` with the synchronous `health_check` populated by its registration probe (per `infra_adapter_elastic` Story 3.2 — registration probes inline and stores the result).
   - **If `health_check.status` is non-null on the create response**: `toast.success("Cluster registered — health: {status}")`; close modal; invalidate `["clusters"]`.
   - **If `health_check.status` is null/missing** (edge case where probe didn't run synchronously): poll `GET /api/v1/clusters/{id}` every 2s up to 15s via `setTimeout` + `queryClient.fetchQuery`; on first non-null `health_check`, toast success + close + invalidate; on timeout, `toast.warning("Registered but health probe timed out")` + close + invalidate. Validates spec FR-6's "polls health_check until it returns" requirement.
5. Write `clusters-table.tsx` rendering name / engine / environment / health badge / notes / "View" link from `q.data.data` (single-page response).
6. Write `cluster-detail-summary.tsx` rendering the summary card + the studies-by-cluster table.
7. Write `studies-by-cluster-table.tsx`. **Prerequisite:** Story 3.2 already shipped `useStudies({cluster_id, status, cursor, limit, since})` and `useStudy(id)` in `ui/src/lib/api/studies.ts`. This story consumes the existing hook — no new files in that path. If 3.2 hasn't landed, this story is blocked (per §7 sequencing).
8. Write `/clusters/page.tsx` and `/clusters/[id]/page.tsx` shells.
9. Write tests: list rendering with msw mock, modal validation, error toast for `CLUSTER_UNREACHABLE`.

**Definition of Done**
- [ ] `/clusters` renders the list with health badges.
- [ ] "Register cluster" modal validates client-side then POSTs; success closes modal + refreshes list.
- [ ] Backend `CLUSTER_UNREACHABLE` surfaces as a toast; modal stays open.
- [ ] `/clusters/{id}` renders summary + studies-by-this-cluster.
- [ ] Tests cover register-form happy path and `CLUSTER_UNREACHABLE` error path.

### Story 2.2 — Query sets list + create modal + detail + bulk-add CSV/JSON + judgment-lists section

**Outcome:** `/query-sets` lists query sets; create modal accepts both JSON body and CSV upload; `/query-sets/{id}` shows the queries list (read-only + bulk-add), an "Associated judgment lists" section with status badges and counts, and a "Generate judgments" action that fires `POST /api/v1/judgments/generate`.

**Scope-deferral note:** Spec FR-7 mentions "inline edit/delete" per query, but the backend does NOT expose per-query PATCH/DELETE endpoints (only `POST /query-sets/{id}/queries` for bulk add). Inline edit/delete is **deferred to a follow-up `chore_query_inline_edit_delete` idea file** (created alongside this plan). For MVP1, the queries table is view-only with "Add queries" the only mutation path.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/query-sets.ts` | `useQuerySets()`, `useQuerySet(id)`, `useCreateQuerySet()`, `useAddQueries(id)` (POST bulk JSON or CSV) |
| `ui/src/app/query-sets/page.tsx` | List page |
| `ui/src/app/query-sets/[id]/page.tsx` | Detail page |
| `ui/src/components/query-sets/query-sets-table.tsx` | List table |
| `ui/src/components/query-sets/create-query-set-modal.tsx` | Two-tab modal: "Paste JSON" or "Upload CSV" |
| `ui/src/components/query-sets/queries-table.tsx` | Queries view-only table on detail |
| `ui/src/components/query-sets/add-queries-dialog.tsx` | Bulk-add (CSV or JSON) on detail |
| `ui/src/components/query-sets/associated-judgment-lists.tsx` | Section showing judgment lists scoped to this query-set with status badges + source breakdown (calls `useJudgmentLists({query_set_id})` from Story 2.4's hook) + "Generate judgments" button |
| `ui/src/components/query-sets/generate-judgments-dialog.tsx` | Confirms params (model defaults from `Settings.openai_model` on backend side; the dialog only collects `name` for the new list + judgment-list-scope flags); POSTs `/judgments/generate`; on success, invalidates `["judgment-lists"]` + toasts |
| `ui/src/components/ui/tabs.tsx` | shadcn primitive (for modal tabs) |
| `ui/src/components/ui/table.tsx` | shadcn primitive |
| `ui/src/lib/csv-validate.ts` | Pure helper: detect rows, validate header (`query_text,doc_id?,metadata?`), enforce 10MB pre-submit cap |
| `ui/src/__tests__/lib/csv-validate.test.ts` | Header validation; size cap (10MB rejected pre-submit per spec §10) |
| `ui/src/__tests__/components/query-sets/create-query-set-modal.test.tsx` | Both tabs submit correctly; CSV >10MB rejected pre-submit |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/api-client.ts` | Already exports `postCsv` — no change |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/query-sets?cursor&limit&since&cluster_id` | List + filter |
| `GET` | `/api/v1/query-sets/{query_set_id}` | Detail |
| `POST` | `/api/v1/query-sets` | Create (JSON body OR CSV via `Content-Type: text/csv`) |
| `POST` | `/api/v1/query-sets/{query_set_id}/queries` | Bulk-add JSON or CSV |
| `GET` | `/api/v1/judgment-lists?query_set_id=` | Associated judgment lists section (consumes Story 2.4's `useJudgmentLists`) |
| `GET` | `/api/v1/query-templates?engine_type=` | Generate-judgments dialog template dropdown (consumes Story 2.3's `useTemplates`) |
| `POST` | `/api/v1/judgments/generate` | Generate-judgments dialog submit |

**Error codes surfaced:** `VALIDATION_ERROR`, `INVALID_CSV`, `QUERY_SET_NAME_TAKEN`, `RESOURCE_NOT_FOUND`, `INTERNAL_ERROR`, plus generate-judgments-specific: `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`.

**Tasks**
1. `npx shadcn@latest add tabs table` — primitives.
2. Write `query-sets.ts` hooks. Detect JSON-vs-CSV content type at hook level via discriminated input.
3. Write `csv-validate.ts`: parse first row, check headers, count rows, reject if `file.size > 10 * 1024 * 1024`. Note: CSV size cap is a UI-side guard per spec §10; the backend has its own quota. Header allowlist: `query_text` (required), `doc_id` (optional), `metadata` (optional, JSON string per backend `csv_parser`).
4. Write `create-query-set-modal.tsx`. Two `<TabsContent>`: JSON paste (textarea) and CSV upload (`<input type="file" accept=".csv">`). On submit, route to the correct API call.
5. Write `queries-table.tsx` for detail page — view-only (per scope-deferral note above; per-query edit/delete deferred to `chore_query_inline_edit_delete`). Columns: query_text, doc_id (or "—"), metadata-keys (truncated). "Add queries" button opens the bulk dialog.
6. Write `associated-judgment-lists.tsx` calling `useJudgmentLists({query_set_id: id})` (the hook ships in Story 2.4; if 2.4 hasn't landed yet, Story 2.2 ships a minimal hook skeleton that 2.4 extends — but per the revised sequence, both run in parallel after Epic 1, so the team coordinates via a small foundational PR or sequences 2.4 first). Render each judgment list as a card with name + status badge + source breakdown (llm/human counts) + "Open" link to `/judgments/{id}`. Section header has a "Generate new judgment list" button.
7. Write `generate-judgments-dialog.tsx`: collect `name` (text input); POST `/judgments/generate` with `query_set_id` (current) + `template_id` (selected from a dropdown filtered by the cluster's engine — fetched via `useTemplates({engine_type})`) + `name`. On success: toast ("Generation started — refresh in a few minutes") + close + invalidate `["judgment-lists"]`. On error: toast (handles `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `LLM_PROVIDER_INCAPABLE` per spec §11 edge flows).
8. Write tests for csv-validate, create-query-set-modal, associated-judgment-lists, generate-judgments-dialog.

**Definition of Done**
- [ ] Create-query-set modal supports JSON and CSV tabs.
- [ ] CSV >10MB rejected client-side (test asserts the error toast).
- [ ] Detail page shows queries (view-only) + "Add queries" bulk dialog + Associated judgment lists section + Generate-judgments dialog.
- [ ] Backend `INVALID_CSV` errors with row numbers display via toast.
- [ ] Generate-judgments dialog handles `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `LLM_PROVIDER_INCAPABLE` toasts.
- [ ] Per-query edit/delete out of scope (see `chore_query_inline_edit_delete` follow-up).

### Story 2.3 — Templates list + view + fork-to-version

**Outcome:** `/templates` lists templates; `/templates/{id}` is view-only (immutability per `feat_study_lifecycle`); "Fork to v+1" creates a new template with `parent_id = current.id` and version bumped. Body editor uses `prism-react-renderer` for highlighting (no Monaco in MVP1).

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/query-templates.ts` | `useTemplates()`, `useTemplate(id)`, `useCreateTemplate()` |
| `ui/src/app/templates/page.tsx` | List page |
| `ui/src/app/templates/[id]/page.tsx` | Detail (view-only) + Fork button |
| `ui/src/components/templates/templates-table.tsx` | List table |
| `ui/src/components/templates/create-template-modal.tsx` | Name / engine_type / body / declared_params form |
| `ui/src/components/templates/fork-template-modal.tsx` | Pre-fills name (suffixed) + body + declared_params from parent; sets `parent_id` |
| `ui/src/components/templates/template-body-editor.tsx` | `<textarea>` + `<Highlight>` from `prism-react-renderer` rendering Jinja2/JSON |
| `ui/src/components/templates/template-detail-view.tsx` | View-only body + declared_params |
| `ui/src/__tests__/components/templates/template-body-editor.test.tsx` | Renders highlighted tokens; textarea remains writable |
| `ui/src/__tests__/components/templates/fork-template-modal.test.tsx` | Fork pre-fills correctly; submit POSTs with `parent_id` set |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/query-templates?cursor&limit&engine_type` | List |
| `GET` | `/api/v1/query-templates/{template_id}` | Detail |
| `POST` | `/api/v1/query-templates` | Create or Fork |

**Tasks**
1. Write `query-templates.ts` hooks.
2. Write `template-body-editor.tsx`. Use `prism-react-renderer`'s `<Highlight>` overlaid behind a transparent `<textarea>` (standard pattern). Language: `jsx` or `jinja2`-flavored — Prism doesn't ship Jinja2; use the `jsx` token set (closest fit) and add a comment explaining the choice.
3. Write `create-template-modal.tsx` and `fork-template-modal.tsx`.
4. Tests.

**Definition of Done**
- [ ] List + detail render.
- [ ] Fork creates a new template with `parent_id` and version increment (verify via msw mock asserting POST body).
- [ ] Body editor renders highlighted content (test asserts at least one token classname appears in the DOM).

### Story 2.4 — Judgment Review page + override popover + calibration modal

**Outcome:** `/judgments/{id}` shows the judgment list summary + paginated judgments with source badge; clicking "Override" opens a popover for rating + notes; "Calibrate" opens a modal accepting a CSV/JSON of human samples and displays kappa stats.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/judgments.ts` | `useJudgmentLists()`, `useJudgmentList(id)`, `useJudgments(id, {cursor?, limit?, source?})`, `useOverrideJudgment(listId)`, `useCalibrate(listId)`, `useGenerateJudgments()`, `useImportJudgmentList()` |
| `ui/src/app/judgments/[id]/page.tsx` | Page shell |
| `ui/src/components/judgments/judgment-list-header.tsx` | Header card: name, status badge, source breakdown, calibration kappa (if present) |
| `ui/src/components/judgments/judgments-table.tsx` | Paginated judgments w/ source filter chips |
| `ui/src/components/judgments/override-popover.tsx` | shadcn `<Popover>` containing rating select + notes textarea + Save |
| `ui/src/components/judgments/calibration-modal.tsx` | CSV/JSON paste; displays returned kappa + per-class breakdown |
| `ui/src/components/ui/popover.tsx` | shadcn primitive |
| `ui/src/__tests__/app/judgments/[id]/page.test.tsx` | Page-level: header renders status + breakdown; source filter chips trigger refetch with `?source=`; override popover integration; calibration kappa appears in header after submit |
| `ui/src/__tests__/components/judgments/override-popover.test.tsx` | **AC-4 strengthened:** msw returns updated row on PATCH; refetch fires; rendered row shows `rating: 0`, `source: human` badge, and the new notes within the test timeout. **Persistence assertion:** unmount and remount the page → updated values still rendered (TanStack Query cache persists across remount). |
| `ui/src/__tests__/components/judgments/calibration-modal.test.tsx` | Submits sample CSV; displays `cohens_kappa` from mock response; `judgment-lists` query invalidated (header refetches kappa) |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/judgment-lists` | (used in Story 3.3 create-study Step 2 too — exported here for reuse) |
| `GET` | `/api/v1/judgment-lists/{judgment_list_id}` | Header data |
| `GET` | `/api/v1/judgment-lists/{judgment_list_id}/judgments?cursor&source` | Table data; `source` is `JudgmentSourceFilterWire` (`llm` or `human` — `click` is read-only per spec) |
| `PATCH` | `/api/v1/judgment-lists/{judgment_list_id}/judgments/{judgment_id}` | Override |
| `POST` | `/api/v1/judgment-lists/{judgment_list_id}/calibration` | Calibrate |
| `POST` | `/api/v1/judgments/generate` | Tutorial flow's "Generate" button (in create-judgment-list flow, surfaced from query-set detail) |
| `POST` | `/api/v1/judgment-lists/import` | Tutorial flow's import path |

**Error codes surfaced:** `VALIDATION_ERROR`, `RESOURCE_NOT_FOUND`, `INVALID_RATING`, `LIST_NOT_READY`, `INSUFFICIENT_SAMPLES`, `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`, `INTERNAL_ERROR`.

**Tasks**
1. `npx shadcn@latest add popover textarea` — primitives.
2. Write `judgments.ts` hooks.
3. Write `judgments-table.tsx` with source filter chips: only render two chip values (`llm`, `human`) — pulled from `JUDGMENT_SOURCE_FILTER_VALUES`. Display source badge using full `JUDGMENT_SOURCE_VALUES` (which includes `click`).
4. Write `override-popover.tsx`: rating `<Select>` over `RATING_VALUES`; notes `<Textarea>`; Save → `mutate({rating, notes})` → invalidate `["judgments", listId]`.
5. Write `calibration-modal.tsx`: textarea for JSON paste OR file input for CSV. POSTs to calibration endpoint. Renders `cohens_kappa`, `weighted_kappa`, `n_samples`, per-class agreement table.
6. Tests.

**Definition of Done**
- [ ] Override updates the row within 1s of save with rating 0, source badge `human`, and updated notes (AC-4 — full assertion per spec §12).
- [ ] After unmount/remount the override persists (TanStack Query cache + backend round-trip both verified).
- [ ] Calibration modal shows `cohens_kappa`, `weighted_kappa`, `n_samples`, per-class breakdown after submission (AC-5).
- [ ] Calibration success invalidates `["judgment-lists", id]` so the header's kappa display refreshes.
- [ ] Source filter chips trigger refetch with `?source=llm` / `?source=human`.
- [ ] Page-level test (`app/judgments/[id]/page.test.tsx`) covers header + filter + override integration + calibration end-to-end.

---

## Epic 3 — Dashboard + Studies surface

Outcomes from this epic:
- Dashboard with recent studies + count widgets driven by `X-Total-Count`.
- Studies list with status filter chips + cursor pagination.
- Create-study 5-step modal.
- Study detail with live polling, cancel, and digest panel (Recharts `<ParameterImportanceChart>` + Open-PR link).

**Epic 3 gate:** AC-1 through AC-3, AC-7, AC-8 all pass. Tutorial flow runs end-to-end from `/` to digest in a fresh `make up` install.

### Story 3.1 — Dashboard `/`

**Outcome:** `/` shows three sections: top-5 recent studies (cards), "Open proposals" count card, "Studies completed in last 7 days" count card. Loads quickly via three parallel queries; uses `X-Total-Count` for both count cards.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/dashboard/recent-studies-cards.tsx` | Cards for top-5 recent studies |
| `ui/src/components/dashboard/count-card.tsx` | Reusable count-with-label card |
| `ui/src/__tests__/app/page.test.tsx` | Dashboard renders all three sections; backend-down state from AC-8 |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/page.tsx` | Replace welcome-stub from Story 1.2 with the real dashboard |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/studies?limit=5` | Recent studies; reads `data` |
| `GET` | `/api/v1/proposals?status=pr_opened&limit=1` | Open proposals count via `X-Total-Count` header |
| `GET` | `/api/v1/studies?status=completed&since=<7d-iso>&limit=1` | 7-day count via `X-Total-Count` |

**Tasks**
1. Write `count-card.tsx` and `recent-studies-cards.tsx`.
2. Update `page.tsx` to fire three parallel queries.
3. Test for AC-8 (backend down → `<EmptyState>` rendered after 4 total attempts = 1 initial + 3 retries). Configure msw to simulate **network failure** (msw's `HttpResponse.error()` which produces a `TypeError` in `fetch`) for all three endpoints. With fake timers, advance through the 1s/2s/4s backoff windows — verify the dashboard shows `<EmptyState title="Backend unreachable" />` after the 4th attempt fails. Per FR-10's retry contract.

**Definition of Done**
- [ ] Dashboard renders three sections with live data.
- [ ] Backend-down state shows the empty state per AC-8.
- [ ] `X-Total-Count` header is correctly read for the count cards.

### Story 3.2 — Studies list `/studies`

**Outcome:** `/studies` is a cursor-paginated table with status filter chips; clicking a chip refetches with `?status=...`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/studies.ts` | `useStudies({status?, cluster_id?, cursor?, limit?, since?})`, `useStudy(id, {refetchInterval?})`, `useCreateStudy()`, `useCancelStudy(id)`, `useStudyTrials(id, {sort?, cursor?, limit?, refetchInterval?})` |
| `ui/src/app/studies/page.tsx` | List page |
| `ui/src/components/studies/studies-table.tsx` | Cursor-paginated table |
| `ui/src/components/studies/study-status-filter-chips.tsx` | Filter chips (`all` + 5 `StudyStatusWire` values) |
| `ui/src/__tests__/app/studies/page.test.tsx` | Filter chips trigger refetch (AC-7 cursor pagination + filter reset) |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/studies?status&cluster_id&cursor&limit&since` | List |

**Tasks**
1. Write `studies.ts` hooks. The list uses single-page `useQuery` keyed by `{status, cluster_id, cursor, limit, since}` (per §0 cursor-pagination contract); response includes `data`, `next_cursor`, `has_more`, plus `totalCount` parsed from the `X-Total-Count` header.
2. Write `study-status-filter-chips.tsx` — six chips (including "all") rendered from `["all", ...STUDY_STATUS_VALUES]`. Selecting a chip sets URL `?status=...` (using `next/navigation` `useSearchParams` + `router.replace`). `all` clears the param.
3. Write `studies-table.tsx`. Columns per spec §FR-3.
4. Test filter→refetch and pagination Prev/Next.

**Definition of Done**
- [ ] All 6 chips render and refetch (AC-7 partial: filter chip changes reset to first page).
- [ ] Cursor pagination renders Prev/Next correctly (AC-7).

### Story 3.3 — Create-study 5-step modal

**Outcome:** "Create study" button opens a multi-step modal; each step's "Next" button gated on Zod validation. Submit POSTs to `/studies` and invalidates the list.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Stepper container; renders one of five step components based on local state |
| `ui/src/components/studies/create-study-steps/step1-cluster-target.tsx` | Step 1: cluster select → loads `/clusters/{id}/schema` to populate target index list |
| `ui/src/components/studies/create-study-steps/step2-query-set-judgment.tsx` | Step 2: query set + judgment list (filtered by `query_set_id`) |
| `ui/src/components/studies/create-study-steps/step3-template.tsx` | Step 3: query template (filtered by chosen cluster's `engine_type`) |
| `ui/src/components/studies/create-study-steps/step4-search-space.tsx` | Step 4: search-space JSON textarea with `prism-react-renderer` highlighting |
| `ui/src/components/studies/create-study-steps/step5-objective-config.tsx` | Step 5: objective (metric + k + direction) + config (max_trials, time_budget_min, parallelism, sampler, pruner, seed) |
| `ui/src/components/studies/create-study-zod.ts` | Zod schemas for each step + composed schema for final submit |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Walk through all 5 steps; assert backend POST body matches `CreateStudyRequest` |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/clusters` | Step 1 cluster dropdown |
| `GET` | `/api/v1/clusters/{cluster_id}/schema?target=` | Step 1 target dropdown |
| `GET` | `/api/v1/query-sets?cluster_id=` | Step 2 |
| `GET` | `/api/v1/judgment-lists?query_set_id=` | Step 2 |
| `GET` | `/api/v1/query-templates?engine_type=` | Step 3 |
| `POST` | `/api/v1/studies` | Submit |

**Zod schemas (excerpt)**

```ts
// step5 — mirrors backend/app/api/v1/schemas.py ObjectiveSpec + StudyConfigSpec.
// Wire-value arrays imported from @/lib/enums (source-of-truth comments live there).
const Step5Schema = z.object({
  objective: z.object({
    metric: z.enum(OBJECTIVE_METRIC_VALUES),
    k: z.union([z.literal(1), z.literal(3), z.literal(5), z.literal(10), z.literal(20), z.literal(50), z.literal(100)]).optional(),
    direction: z.enum(OBJECTIVE_DIRECTION_VALUES).default("maximize"),
  }).refine(
    obj => !(["ndcg", "precision", "recall"].includes(obj.metric) && obj.k == null),
    "k is required for ndcg/precision/recall"
  ),
  config: z.object({
    // Bounds match backend StudyConfigSpec field constraints.
    max_trials: z.number().int().min(1).max(100_000).optional(),
    time_budget_min: z.number().positive().optional(),  // backend: float, gt=0, no upper bound
    parallelism: z.number().int().min(1).max(64).optional(),
    trial_timeout_s: z.number().int().min(5).max(3600).optional(),
    sampler: z.enum(SAMPLER_VALUES).optional(),
    pruner: z.enum(PRUNER_VALUES).optional(),
    seed: z.number().int().optional(),
  }).superRefine((cfg, ctx) => {
    // Mirrors StudyConfigSpec._require_one_stop_condition.
    if (cfg.max_trials == null && cfg.time_budget_min == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Specify at least one of `max_trials` or `time_budget_min` — the study needs a stop condition.",
        path: ["max_trials"],
      });
    }
  }),
});
```

**Form-display defaults** (applied via `useForm({ defaultValues })`, NOT in the Zod schema — so they're omitted from the POST body when the user doesn't change them, letting the backend Settings defaults apply): `objective.direction = "maximize"`, `config.parallelism = 4`, `config.sampler = "tpe"`, `config.pruner = "median"`. Step 5 submit calls `form.handleSubmit(values => mutate(values))` after passing values through `JSON.parse(JSON.stringify(values))` so `undefined` keys are stripped (matches the backend's `model_dump(exclude_none=True, exclude_unset=True)` contract from `feat_study_lifecycle` Phase 2 PR #25).

**Tasks**
1. Write `create-study-zod.ts` mirroring the backend `CreateStudyRequest` Pydantic model field-by-field.
2. Write each step component. Use React Hook Form's `useFormContext()` to share form state.
3. Wire the stepper. Validate the current step's slice via `form.trigger(["field1", "field2"])` before enabling Next.
4. On final submit: `mutate(values)`; on success: toast + close + invalidate `["studies"]`.
5. Test: navigate all 5 steps with valid data; assert msw handler received correct body.

**Definition of Done**
- [ ] Modal validates per-step; Next disabled until current step is valid.
- [ ] Submit POSTs the correct `CreateStudyRequest` body (test asserts payload shape).
- [ ] Backend `VALIDATION_ERROR` surfaces inline + toast.

### Story 3.4 — Study detail + live trial polling + digest panel + Open-PR

**Outcome:** `/studies/{id}` shows header, action buttons, trials table polling at 3s while running, and a digest panel (when complete) with `<ParameterImportanceChart>` + top-10 trials + metric delta + **"Open PR" button linking to `/proposals/{proposalId}?action=open_pr`** (the action button itself lives in `feat_proposals_ui`, which reads `?action=open_pr` from the search params and pre-focuses the Open-PR primary action on its detail page).

**Cross-feature contract:** the `?action=open_pr` query param is the agreed link between this feature and `feat_proposals_ui`. When `feat_proposals_ui`'s spec is drafted, it MUST honor `?action=open_pr` on `/proposals/{id}` by pre-focusing or auto-triggering the Open-PR call-to-action. This plan records the contract; `feat_proposals_ui` realizes it. Until `feat_proposals_ui` ships, the link 404s — acceptable per the MVP1 sequencing.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/digests.ts` | `useStudyDigest(studyId)` |
| `ui/src/lib/api/proposals.ts` | `useProposalForStudy(studyId)` (filtered list) — used to find the proposal id for the "Open PR" link |
| `ui/src/app/studies/[id]/page.tsx` | Detail page |
| `ui/src/components/studies/study-header.tsx` | Header card: name, cluster, target, status badge, timestamps |
| `ui/src/components/studies/study-action-bar.tsx` | Cancel button (only enabled when `status === 'running'`) with confirmation dialog |
| `ui/src/components/studies/trials-table.tsx` | Sortable cursor-paginated table; accepts `refetchInterval` |
| `ui/src/components/studies/digest-panel.tsx` | Narrative + chart + top-10 + metric delta + Open-PR button |
| `ui/src/components/common/parameter-importance-chart.tsx` | Recharts horizontal `BarChart` from `digests.parameter_importance` |
| `ui/src/components/ui/alert-dialog.tsx` | shadcn primitive (for cancel confirmation) |
| `ui/src/__tests__/app/studies/[id]/page.test.tsx` | Running state polls every 3s (use fake timers); transitions to complete → polling stops + digest panel appears |
| `ui/src/__tests__/components/common/parameter-importance-chart.test.tsx` | Given canonical input, renders one bar per param sorted descending |

**Endpoints consumed**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/studies/{study_id}` | Header + status; polls every 3s while `running` |
| `POST` | `/api/v1/studies/{study_id}/cancel` | Cancel |
| `GET` | `/api/v1/studies/{study_id}/trials?sort&cursor&limit` | Trials table; polls every 3s while parent `running` |
| `GET` | `/api/v1/studies/{study_id}/digest` | Digest panel data (404 `DIGEST_NOT_READY` is expected while running — UI doesn't render the panel until 200) |
| `GET` | `/api/v1/proposals?study_id={id}&status=pending` | Find proposal for Open-PR button |

**Key interfaces**

```ts
// ui/src/lib/api/studies.ts (hook ships in Story 3.2)
export function useStudy(id: string, options?: { refetchInterval?: number | false }): UseQueryResult<StudyDetail> {
  return useQuery({
    queryKey: ["studies", id],
    queryFn: () => apiClient.get<StudyDetail>(`/api/v1/studies/${id}`).then(r => r.data),
    refetchInterval: options?.refetchInterval ?? false,
  });
}

// Page-side polling decision (Story 3.4's /studies/[id]/page.tsx):
function StudyDetailPage({ id }: { id: string }) {
  const [pollingMs, setPollingMs] = useState<number | false>(false);
  const studyQ = useStudy(id, { refetchInterval: pollingMs });
  // Flip polling on/off as status transitions; effect re-runs only on status change.
  useEffect(() => {
    setPollingMs(studyQ.data?.status === "running" ? 3000 : false);
  }, [studyQ.data?.status]);
  // ...
}
```

The page owns the polling decision; the hook stays policy-free per spec §4.

**Tasks**
1. Write `useStudyDigest(studyId)` — note: `GET /studies/{id}/digest` returns 404 `DIGEST_NOT_READY` while running; the hook suppresses that specific code from the global toast handler via TanStack Query `meta`. **Do NOT define a local `onError`** — the QueryCache global handler (Story 1.2) already toasts, and reads `query.meta.suppressErrorCodes` to opt out. Pattern: `useQuery({ queryKey: ["digest", studyId], queryFn: ..., meta: { suppressErrorCodes: ["DIGEST_NOT_READY"] } })`.
2. Write `parameter-importance-chart.tsx`. Recharts `<BarChart layout="vertical">` with `<XAxis type="number">`, `<YAxis dataKey="param" type="category">`, `<Bar dataKey="importance">`. Sort input by importance descending.
3. Write `digest-panel.tsx`. Markdown rendered via `<ReactMarkdown remarkPlugins={[remarkGfm]} components={{...}} />` with `disallowedElements={["script", "iframe"]}` (extra paranoia even though the renderer is safe by default).
4. Write `trials-table.tsx` with sort dropdown using `TRIAL_SORT_VALUES`.
5. Write `study-action-bar.tsx` with confirmation dialog using `<AlertDialog>`.
6. Tests: use fake timers to verify polling starts at 3s while running and stops on status transition.

**Definition of Done**
- [ ] AC-2 passes — trials table updates within 3s of new trials and stops polling on completion.
- [ ] AC-3 passes — digest panel renders narrative + chart + top-10 + metric delta with `+24.5%` style.
- [ ] "Open PR" button is disabled when no `pending` proposal exists; linked to `/proposals/{id}?action=open_pr` when one does (cross-feature contract).
- [ ] Cancel button confirms then POSTs; on success refetches study + trials.

---

## Epic 4 — Documentation + CI gate

### Story 4.1 — `docs/03_runbooks/ui-debugging.md` + mvp1-user-stories.md updates

**Outcome:** New operator runbook explaining how to inspect TanStack Query cache (Devtools), reproduce a polling bug, and read X-Request-ID across browser → backend logs. US-22/23/24 marked Implemented.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/ui-debugging.md` | Sections: "Inspecting TanStack Query cache", "Reproducing a polling regression", "Tracing a UI error back to backend logs via X-Request-ID", "Common gotchas (CORS, stale types.ts, secrets-not-mounted)" |

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/mvp1-user-stories.md` | Flip US-22 (Dashboard), US-23 (Studies list+detail), US-24 (Live trial polling) from Planned → Implemented |
| `docs/01_architecture/ui-architecture.md` | Update §Directory layout block to reflect actual `ui/src/` layout (the current block is stale — references `ui/app/`, `ui/lib/`, `ui/components/` without the `src/` prefix). Also fix the `npx shadcn-ui add` references to `npx shadcn@latest add`. |
| `docs/03_runbooks/README.md` | Index the new runbook |
| `CLAUDE.md` | Feature-status table — flip the `feat_studies_ui` row from "Spec approved, plan pending" → "Complete (PR #N)" at the finalization commit |
| `state.md` | Add a Recent-changes entry for the feature; flip the "active feature" line; note Alembic head unchanged (`0005_digests`) |

**Tasks**
1. Write the runbook.
2. Patch ui-architecture.md directory layout + shadcn CLI references (this is a docs-only fix surfacing in this story; the spec drift was caught in this session's spec-patch).
3. Update mvp1-user-stories.md.
4. Index in README.

**Definition of Done**
- [ ] Runbook merged at `docs/03_runbooks/ui-debugging.md`.
- [ ] ui-architecture.md no longer references `ui/app/` or `npx shadcn-ui add`.
- [ ] mvp1-user-stories.md US-22/23/24 marked Implemented with PR number.

### Story 4.2 — CI source-of-truth comment grep gate (AC-6 + AC-9)

**Outcome:** A shell-grep job in `.github/workflows/pr.yml` that, for every `// Values must match <path> <symbol>` comment in `ui/src/**/*.ts(x)`, reads the cited backend file and verifies the next array literal contains exactly the values the cited Literal defines. Fails CI when a value is added on one side but not the other.

**New files**

| File | Purpose |
|---|---|
| `scripts/ci/verify_enum_source_of_truth.sh` | Bash script invoked by `pr.yml`. Greps `// Values must match <path> <symbol>` markers; for each, runs `python -c "from backend.app.api.v1.schemas import <symbol>; print(get_args(<symbol>))"` to dump the wire values; compares to the adjacent TS array; exits non-zero on mismatch |
| `backend/tests/contract/test_enum_source_of_truth_helpers.py` | Python helper invoked by the bash script — extracts `get_args` from a typing Literal or a frozenset |

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | Add a new job step `Verify source-of-truth enum comments` running `bash scripts/ci/verify_enum_source_of_truth.sh` after the frontend test step |

**Tasks**
1. Write the helper Python module — accepts `module.symbol` string, returns the literal-arg tuple or frozenset contents.
2. Write the shell script. Algorithm:
   - **Narrow scope:** only scan `ui/src/lib/enums.ts` for source-of-truth comments. Other files MAY reference the typed arrays via `z.enum(...)` but do NOT carry comments — keeps the gate simple and false-positive-free.
   - `grep -nE "// Values must match (\S+\.py) (\S+)" ui/src/lib/enums.ts`
   - For each match, parse `(file, symbol)`. Resolve `file` to repo root.
   - Run `python -m backend.tests.contract.test_enum_source_of_truth_helpers "<module>" "<symbol>"` to get the backend values. The helper supports BOTH symbol kinds: `typing.Literal[...]` (resolved via `typing.get_args`) and `frozenset[...]` / `set[...]` / `tuple[...]` module-level constants (resolved via `ast.literal_eval` of the right-hand side, or `getattr(module, symbol)` with type discrimination).
   - In the TS source, find the next `as const` array after the comment (use a small awk or python regex). Extract its string/int literals.
   - Compare as **unordered sets** (order doesn't matter for the wire-value contract — both sides are allowlists). Mismatches print `FILE:LINE: drift — backend=[...] frontend=[...]` and exit 1.
3. Wire into `pr.yml`.
4. Run locally against the current `enums.ts` to verify clean pass.

**Definition of Done**
- [ ] Local invocation of the script against the merged branch passes.
- [ ] Manually adding a phantom value to `STUDY_STATUS_VALUES` (e.g., `"paused"`) makes the script exit non-zero with a clear drift message.
- [ ] CI job invokes the script; the job appears in the PR's checks list.

---

## UI Guidance (plan-level, required for frontend-facing work)

### Reference: current component structure

The frontend canvas is essentially empty before this feature:
- `ui/src/app/layout.tsx` (15 lines) — minimal `<html><body>{children}</body></html>` with metadata.
- `ui/src/app/page.tsx` (25 lines) — placeholder home from `infra_foundation` Story 1.3 (`"RelyLoop is running"` card).
- `ui/src/app/globals.css` (27 lines) — Tailwind 4 import + basic body styles.
- `ui/src/__tests__/` — exists with vitest setup; no production-code tests yet.
- No `ui/src/components/` or `ui/src/lib/` directories. Story 1.1 and 1.2 create them.

**Insertion point:** every new page lands under `ui/src/app/<route>/page.tsx`; every shared component lands under `ui/src/components/<area>/`; every hook under `ui/src/lib/api/<resource>.ts`. The existing placeholder `page.tsx` is overwritten in Story 1.2 (welcome stub) then again in Story 3.1 (real dashboard).

### Analogous markup patterns

Because the project's UI canvas is empty, there are no in-repo analogues to copy. The plan instead anchors to shadcn's documented patterns (the upstream-canonical reference) and the Tailwind 4 `@theme {}` convention. Concrete starter JSX patterns:

**List page with cursor pagination (used by Studies/Clusters/QuerySets/Templates lists):**

```tsx
// ui/src/app/studies/page.tsx
"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/common/status-badge";
import { CursorPaginator } from "@/components/common/cursor-paginator";
import { EmptyState } from "@/components/common/empty-state";
import { apiClient } from "@/lib/api-client";
import type { components } from "@/lib/types";

export default function StudiesPage() {
  const [pageSize, setPageSize] = useState(50);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursorStack[cursorStack.length - 1];

  const q = useQuery({
    queryKey: ["studies", { status: statusFilter, cursor, limit: pageSize }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<components["schemas"]["StudyListResponse"]>(
        "/api/v1/studies",
        { params: { status: statusFilter ?? undefined, cursor, limit: pageSize } },
      );
      return { ...data, totalCount: Number(headers.get("X-Total-Count") ?? 0) };
    },
  });

  if (q.isLoading) return <Card><CardContent>Loading…</CardContent></Card>;
  if (q.isError) return <EmptyState title="Backend unreachable" message="Check `make logs`." />;

  const rows = q.data?.data ?? [];
  return (
    <main className="mx-auto max-w-7xl p-6 space-y-6">
      <Card>
        <CardHeader><CardTitle>Studies</CardTitle></CardHeader>
        <CardContent>
          {/* status filter chips — onChange: setStatusFilter(v); setCursorStack([undefined]); */}
          <Table>
            <TableHeader><TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Cluster</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Best metric</TableHead>
              <TableHead>Trials</TableHead>
              <TableHead>Created</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map(s => (
                <TableRow key={s.id}>
                  <TableCell><a href={`/studies/${s.id}`} className="text-blue-600 underline-offset-4 hover:underline">{s.name}</a></TableCell>
                  <TableCell>{s.cluster_name}</TableCell>
                  <TableCell><StatusBadge kind="study" value={s.status} /></TableCell>
                  <TableCell>{s.best_metric?.toFixed(3) ?? "—"}</TableCell>
                  <TableCell>{s.trials_summary?.completed ?? 0} / {s.config?.max_trials ?? "—"}</TableCell>
                  <TableCell>{new Date(s.created_at).toLocaleString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <CursorPaginator
            hasMore={q.data?.has_more ?? false}
            onNext={() => setCursorStack(s => [...s, q.data?.next_cursor ?? undefined])}
            onPrev={cursorStack.length > 1 ? () => setCursorStack(s => s.slice(0, -1)) : undefined}
            pageSize={pageSize}
            onPageSizeChange={(n) => { setPageSize(n); setCursorStack([undefined]); }}
            totalCount={q.data?.totalCount}
          />
        </CardContent>
      </Card>
    </main>
  );
}
```

**Modal pattern (used by Register-Cluster / Create-Study / Create-QuerySet / Create-Template / Calibration):**

```tsx
// ui/src/components/<area>/<name>-modal.tsx
"use client";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

export function RegisterClusterModal({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const form = useForm({ resolver: zodResolver(RegisterClusterSchema) });
  const register = useRegisterCluster();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register a cluster</DialogTitle>
          <DialogDescription>Configure connection + auth + (optional) config repo.</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={form.handleSubmit(values => register.mutate(values, {
            // The global MutationCache toasts on error automatically — we do NOT call
            // toast.error here (would double-toast). We only handle success + modal lifecycle.
            // On error, the modal stays open via the natural `isPending → isError` state flow;
            // the global toast surfaces the error_code + message.
            onSuccess: () => { toast.success("Cluster registered"); onOpenChange(false); },
          }))}
          className="space-y-4"
        >
          {/* Input + Select fields from form */}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={!form.formState.isValid || register.isPending}>
              {register.isPending ? "Registering…" : "Register"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

**Polling pattern (used by Study Detail trials + status — caller-driven per spec §4):**

```tsx
// ui/src/lib/api/studies.ts — hook is policy-free
export function useStudy(id: string, options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: ["studies", id],
    queryFn: () => apiClient.get<StudyDetail>(`/api/v1/studies/${id}`).then(r => r.data),
    refetchInterval: options?.refetchInterval ?? false,
  });
}

// ui/src/app/studies/[id]/page.tsx — page decides via state + effect
function StudyDetailPage({ id }: { id: string }) {
  const [pollingMs, setPollingMs] = useState<number | false>(false);
  const studyQ = useStudy(id, { refetchInterval: pollingMs });
  useEffect(() => {
    setPollingMs(studyQ.data?.status === "running" ? 3000 : false);
  }, [studyQ.data?.status]);
  // …trials table uses the same pattern with useStudyTrials(id, { refetchInterval: pollingMs })
}
```

### Layout and structure

- **Page chrome:** every page renders inside the layout's top nav + body container (`max-w-7xl mx-auto p-6`).
- **Card-based:** primary content lives in a shadcn `<Card>`. Lists use `<Table>` from the same primitive.
- **Modals not new pages:** create/edit forms open in `<Dialog>` overlays, not new routes. Exceptions: Study Detail and Judgment Review are full pages because they have rich content beyond a form.
- **Desktop-first:** tested at 1280px+; mobile not gated.

### Interaction behavior

Every user-visible action maps to a frontend behavior and, where applicable, an API call. The table below is the canonical reference for cross-story interactions.

| User action | Frontend behavior | API call | Invalidates query keys |
|---|---|---|---|
| Click nav link | Next route push | — | — |
| Open "Register cluster" modal | Show `<Dialog>` | — | — |
| Submit register-cluster form | Disable Submit, show "Registering…" | `POST /api/v1/clusters` | `["clusters"]` |
| Click cluster name in list | Navigate to `/clusters/{id}` | — | — |
| Open "Create query set" modal → JSON tab | Show JSON `<Textarea>` | — | — |
| Submit query-set JSON form | Disable Submit | `POST /api/v1/query-sets` (Content-Type: application/json) | `["query-sets"]` |
| Submit query-set CSV upload | Validate ≤10MB + headers; disable Submit | `POST /api/v1/query-sets` (Content-Type: text/csv) | `["query-sets"]` |
| "Fork to v+1" on a template | Open Fork modal pre-filled from parent | (form action) `POST /api/v1/query-templates` with `parent_id` set | `["templates"]` |
| Click "Override" on a judgment row | Show `<Popover>` with rating + notes | — | — |
| Save override | Disable Save during in-flight | `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` | `["judgments", listId]` |
| "Calibrate" → submit samples | Disable Submit; show kappa on success | `POST /api/v1/judgment-lists/{id}/calibration` | `["judgment-lists", id]` |
| Submit Create-Study form (Step 5) | Disable Submit | `POST /api/v1/studies` | `["studies"]` |
| Click chip on Studies list | Update URL `?status=<value>`; refetch | `GET /api/v1/studies?status=…` | (refetch, not invalidate) |
| Click "Cancel" on running study | Show `<AlertDialog>` confirm | (after confirm) `POST /api/v1/studies/{id}/cancel` | `["studies", id]`, `["studies", id, "trials"]` |
| Study detail open while running | Polling tick every 3s | `GET /api/v1/studies/{id}` + `GET /api/v1/studies/{id}/trials` | (refetch each tick) |
| Click "Open PR" on digest panel | Navigate to `/proposals/{proposalId}?action=open_pr` (cross-feature contract — `feat_proposals_ui` honors the param to pre-focus the Open-PR action) | — | — |
| Backend returns 503-retryable | apiClient retries 3× (1s/2s/4s); on final failure → toast | — | — |
| Backend returns any 4xx with `error_code` | apiClient throws `ApiError`; caller toasts via `toToastMessage()` | — | — |

### Component composition

| Component | Type | Used by | Notes |
|---|---|---|---|
| `<TopNav>` | extracted client component | layout.tsx | Single source of nav truth |
| `<StatusBadge kind value />` | extracted, prop-driven | every list + detail page | Variant from kind+value lookup |
| `<MetricDelta baseline achieved />` | extracted | digest panel, study list (best metric) | Formatting helper + color |
| `<CursorPaginator hasMore onPrev onNext pageSize onPageSizeChange totalCount? />` | extracted | every list page | Prev/Next + page-size select |
| `<EmptyState title message action? />` | extracted | dashboard, every empty/error fallback | Title + message + optional action |
| `<ParameterImportanceChart data />` | extracted | digest panel only | Recharts SVG; client-only |
| `<TrialsTable trials sort onSort />` | extracted | study detail | Cursor-paginated sortable table |
| Modals (`Register*`, `Create*`, `Fork*`, `Calibration`) | inline within their owning components | parent pages | Each modal owns its form state |

No circular dependencies between parent and child state — parents fetch via hooks, children receive data via props.

### Information architecture placement

- Top nav order (left→right): Dashboard → Clusters → Query Sets → Templates → Studies → Proposals → Chat. This matches spec FR-1 and gives the operator the create→use→observe flow at a glance.
- Discovery: the dashboard's "Recent studies" cards link directly into Study Detail. The "Open proposals" count card links to `/proposals` (handled by feat_proposals_ui).

### Tooltips and contextual help

Spec §11 doesn't enumerate tooltips; the plan uses minimal inline help text via shadcn `<FormDescription>` for non-obvious fields:

- `auth_kind` (Register Cluster): "ES uses `es_apikey` or `es_basic`; OpenSearch uses `opensearch_basic` or `opensearch_sigv4`." — text only, no separate tooltip primitive needed.
- `parallelism` (Create Study Step 5): "How many trials run concurrently. Default 4. Higher values speed up the study but may overwhelm the cluster."
- `max_trials` vs `time_budget_min`: inline help text explaining either stops the study; both gates apply.

### Legacy behavior parity

**No legacy behavior parity table** — no user-facing component >100 LOC is being deleted or migrated in this plan. The only existing user-facing artifact is the `ui/src/app/page.tsx` placeholder (25 LOC). It is intentionally replaced in Story 1.2 (welcome stub) and again in Story 3.1 (real dashboard); no legacy validation/loading/error behavior exists to preserve.

### Visual consistency

- Use shadcn primitives exclusively for buttons, inputs, dialogs, selects, badges, cards, tables, popovers, tabs.
- Status colors are documented in Story 1.3's color-mapping table.
- Tailwind 4 design tokens (when needed beyond shadcn defaults) live in `globals.css` under `@theme {}`.

### Client-side persistence

- Cursor values: React state only — cleared on navigation/remount, per spec §4 "Anti-patterns" rule against round-tripping cursors through the URL.
- Status filter: URL search params (`?status=running`) so deep links are shareable.
- No `localStorage`/`sessionStorage` in MVP1.

---

## 3) Testing workstream

### 3.1 Unit tests (`ui/src/__tests__/`)
Pure helpers and atomic components.
- [ ] `lib/uuid.test.ts` — UUIDv7 timestamp prefix + version=7 + variant=10 asserts (Story 1.1)
- [ ] `lib/api-client.test.ts` — `X-Request-ID` injection, error envelope translation, 503-retryable backoff + network-failure retry with fake timers (Story 1.1)
- [ ] `lib/api-errors.test.ts` — `isApiError` + `toToastMessage` (Story 1.1)
- [ ] `lib/api/studies.test.ts` — query keys, cursor params, X-Total-Count, invalidation, polling-via-options (Story 3.2)
- [ ] `lib/enums.test.ts` — every wire-value array matches the documented spec table (Story 1.3)
- [ ] `lib/csv-validate.test.ts` — header validation + 10MB size cap (Story 2.2)
- [ ] `components/common/status-badge.test.tsx` — every (kind, value) combo (Story 1.3)
- [ ] `components/common/metric-delta.test.tsx` — formatting cases (Story 1.3)
- [ ] `components/common/cursor-paginator.test.tsx` — disabled states, page-size callback, cursor-stack Prev behavior (Story 1.3)
- [ ] `components/common/parameter-importance-chart.test.tsx` — Recharts SVG output (Story 3.4)
- [ ] `components/layout/top-nav.test.tsx` — links + active highlight (Story 1.2)

### 3.2 Component tests (`ui/src/__tests__/app/` and `__tests__/components/`)
DB-free; msw-mocked.
- [ ] `app/page.test.tsx` — dashboard sections + backend-down state (Story 3.1, AC-8)
- [ ] `app/studies/page.test.tsx` — filter chips + cursor pagination (Story 3.2, AC-7)
- [ ] `app/studies/[id]/page.test.tsx` — polling + complete transition + digest panel + `?action=open_pr` link (Story 3.4, AC-2 + AC-3)
- [ ] `app/judgments/[id]/page.test.tsx` — page-level: header, filter chips, override integration, calibration kappa refresh (Story 2.4, AC-4 + AC-5)
- [ ] `app/clusters/page.test.tsx` — list (Story 2.1)
- [ ] `components/clusters/register-cluster-modal.test.tsx` — happy path + `CLUSTER_UNREACHABLE` error + health-check polling (Story 2.1)
- [ ] `components/query-sets/create-query-set-modal.test.tsx` — JSON tab + CSV tab + 10MB pre-submit reject (Story 2.2)
- [ ] `components/query-sets/generate-judgments-dialog.test.tsx` — POST shape + `OPENAI_NOT_CONFIGURED` toast (Story 2.2)
- [ ] `components/query-sets/associated-judgment-lists.test.tsx` — renders judgment-list cards filtered by query_set_id (Story 2.2)
- [ ] `components/templates/template-body-editor.test.tsx` — Prism highlight tokens render (Story 2.3)
- [ ] `components/templates/fork-template-modal.test.tsx` — POST body has `parent_id` (Story 2.3)
- [ ] `components/judgments/override-popover.test.tsx` — override + refetch + persistence (Story 2.4, AC-4 strengthened)
- [ ] `components/judgments/calibration-modal.test.tsx` — submit + kappa render + cache invalidation (Story 2.4, AC-5)
- [ ] `components/studies/create-study-modal.test.tsx` — 5-step walkthrough + POST shape (Story 3.3)

### 3.3 Contract tests
No backend changes — no new contract tests. The existing `test_*_api_contract.py` files still apply.

### 3.4 E2E tests
N/A in MVP1 (Playwright lands at `chore_tutorial_polish` or MVP3+). Per spec §14.

### 3.5 Existing test impact audit

No existing UI tests reference removed behavior (only the infra_foundation health-check test exists and it touches the backend, not the UI). Backend tests are unaffected by this UI-only feature.

| Test file | Pattern | Count | Action |
|---|---|---|---|
| (none) | — | — | No existing UI test code touches files this feature modifies. The infra_foundation tests under `ui/src/__tests__/` (if any) verify the placeholder render; this plan removes that placeholder in Story 1.2 — if a smoke test referencing "RelyLoop is running" exists, Story 1.2 updates it. Story 1.2 task list includes "search for any `RelyLoop is running` test assertions and update or delete." |

### 3.5 Migration verification

No schema changes — no migrations.

### 3.6 CI gates
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm build` (catches SSR issues)
- [ ] `bash scripts/ci/verify_enum_source_of_truth.sh` (Story 4.2)

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — flip the "active feature" line, add Recent changes entry, note Alembic head unchanged (`0005_digests`).
- [ ] `architecture.md` — if applicable, note that the UI shell now exists. The umbrella doc already references this feature.
- [ ] `CLAUDE.md` — flip the `feat_studies_ui` feature-status row from "Spec approved, plan pending" → "Implementation in flight" then → "Complete (PR #N)" at finalization.

### 4.1 Architecture docs
- [ ] `docs/01_architecture/ui-architecture.md` — patch the directory-layout block (Story 4.1)

### 4.2 Product docs
- [ ] `docs/02_product/mvp1-user-stories.md` — mark US-22/23/24 Implemented (Story 4.1)

### 4.3 Runbooks
- [ ] `docs/03_runbooks/ui-debugging.md` — new file (Story 4.1)
- [ ] `docs/03_runbooks/README.md` — index entry (Story 4.1)

### 4.4 Security docs
No changes — the UI doesn't introduce new attack surface beyond what the backend already enforces.

### 4.5 Quality docs
- [ ] `docs/05_quality/testing.md` — if it doesn't already mention the source-of-truth grep gate, add a line pointing at `scripts/ci/verify_enum_source_of_truth.sh`.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- No backend refactor in scope.
- Frontend is greenfield; no legacy code to clean up.

### 5.2 Planned refactor tasks
- [ ] Patch `docs/01_architecture/ui-architecture.md` directory-layout block (Story 4.1 — drift fix surfacing during this plan's writing).

### 5.3 Refactor guardrails
- [ ] No expansion of product scope.
- [ ] All drift fixes captured as small commits within their owning story.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` | All stories | Complete (PR #4) | Build/lint/test toolchain broken |
| `infra_adapter_elastic` | Stories 2.1, 3.3 | Complete (PR #16) | Clusters endpoints unavailable |
| `feat_study_lifecycle` | Stories 3.2, 3.3, 3.4 | Complete (PR #25) | Studies endpoints unavailable |
| `feat_llm_judgments` | Story 2.4 | Complete (PR #35) | Judgments endpoints unavailable |
| `feat_digest_proposal` | Story 3.4 | Complete (PR #41) | Digest endpoint + `proposals` filter unavailable |
| `infra_frontend_stack_refresh` | All stories | Complete (PR #49) | Stack mismatch (Tailwind config, Vitest version) |

All dependencies merged. No external blockers.

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `useInfiniteQuery` v5 API changes between minor versions | L | M | Pin `@tanstack/react-query` to a single minor (`^5.0.0` not `^5`) |
| Recharts SSR/RSC hydration mismatch | M | L | Render chart inside a `"use client"` component only; assert via `pnpm build` step |
| Prism + Tailwind 4 PostCSS plugin interaction breaks highlight CSS | L | L | Validate locally before Story 2.3 lands; Tailwind 4's CSS-first pipeline isolates Prism's styles |
| Backend renames a Literal value and frontend silently drifts | M | M | Story 4.2 source-of-truth CI gate fails the PR |
| msw + Vitest 4 ESM friction | L | L | Vitest 4 ships native ESM; msw v2 supports ESM. Pinning both in Story 1.1 |
| Toast spam if backend is down and dashboard fires three parallel queries | M | L | `apiClient` only toasts on the final attempt of a 503-non-retryable; dashboard uses `<EmptyState>` for the persistent-failure case |
| Open-PR button stale-state — proposal status changes server-side mid-render | L | L | Button uses `useProposalForStudy()` with `staleTime: 0` for the action moment; user feedback acceptable for MVP1 |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Backend reachable but returns 503-retryable | Postgres restart, transient | apiClient retries 3× with backoff; final failure → toast | Auto |
| Backend unreachable (connection refused) | API container stopped | apiClient throws `INTERNAL_ERROR` after retries; page shows `<EmptyState>` (dashboard) or empty list (other pages) | Manual: `make up` |
| OPENAI_NOT_CONFIGURED during Generate | Empty `openai_api_key` file | Toast: "OpenAI key missing — see runbook" | Manual: mount the key |
| LLM_PROVIDER_INCAPABLE on Generate | Local LLM doesn't support strict JSON schema | Toast with backend message + link to runbook | Manual |
| CSV with malformed rows | User uploads bad CSV | Backend returns `INVALID_CSV` with row numbers; toast displays them | User: fix and retry |
| Study transitions to `failed` mid-polling | All trials failed | Polling stops; status badge → failed; "Cancel" button disabled | Operator: read logs, retry |
| Proposal becomes `rejected` after operator opened Study Detail | Other operator | Open-PR button disabled on next refetch | Operator: refresh page |

## 7) Sequencing and parallelization

### Suggested sequence (revised after cross-model review)

The studies hook is consumed by **two** stories (2.1's cluster-studies table and 3.2's list). To avoid merge conflicts on `ui/src/lib/api/studies.ts` and a parallelization land-mine, sequence the studies hook first:

1. **Epic 1** (Stories 1.1 → 1.2 → 1.3) — foundations. Everything else depends on it.
2. **Epic 3 Story 3.2** — owns `ui/src/lib/api/studies.ts` (full hook surface). Lands first after Epic 1.
3. **Epic 2 Story 2.3** (templates) — owns `ui/src/lib/api/query-templates.ts` (`useTemplates` is consumed by Story 2.2's generate-judgments dialog and Story 3.3's create-study modal).
4. **Epic 2 Story 2.4** (judgments) — owns `ui/src/lib/api/judgments.ts` (`useJudgmentLists` is consumed by Story 2.2's associated-judgment-lists section and Story 3.3's create-study Step 2).
5. **Epic 2 Story 2.1** (clusters) — owns `ui/src/lib/api/clusters.ts` + `config-repos.ts`. Independent of 2.3/2.4. Can land in parallel with 2.3/2.4.
6. **Epic 2 Story 2.2** (query sets) — depends on 2.3's `useTemplates` and 2.4's `useJudgmentLists`. Sequenced after both.
7. **Epic 3 Story 3.3** (create-study modal) — uses 3.2 + 2.3 + 2.4 hooks; sequenced after 2.4.
8. **Epic 3 Story 3.4** (study detail + digest) — uses 3.2 hooks + proposals hook (small new file). Can land alongside 3.3.
9. **Epic 3 Story 3.1** (dashboard) — uses 3.2 + proposals hooks. Can land alongside 3.3/3.4.
10. **Epic 4** — finalization, lands last.

### Parallelization opportunities
- 2.1 can run in parallel with 2.3 + 2.4 (no shared file ownership).
- After 2.4 lands: 2.2, 3.3, 3.4, 3.1 can run in parallel.
- Each story owns the file it creates; no two stories share creation of the same `ui/src/lib/api/*.ts` file.

## 8) Rollout and cutover plan

- **Rollout stages:** local dev only (MVP1 has no remote staging). Operator runs `cd ui && pnpm dev` after `make up`.
- **Feature flag strategy:** none.
- **Migration/cutover steps:** none.
- **Reconciliation:** none.

## 9) Execution tracker

### Current sprint (revised order after cycle-2 — owners of `ui/src/lib/api/*.ts` files lead)
- [ ] Epic 1 — Story 1.1 (API client + types + deps)
- [ ] Epic 1 — Story 1.2 (Layout shell + providers + top nav + central toast wiring via QueryCache/MutationCache)
- [ ] Epic 1 — Story 1.3 (Cross-cutting components + enums.ts)
- [ ] Epic 3 — Story 3.2 (Studies list + full `studies.ts` hook surface)
- [ ] Epic 2 — Story 2.3 (Templates list + view + fork — ships `query-templates.ts` hook)
- [ ] Epic 2 — Story 2.4 (Judgment Review + override + calibration — ships `judgments.ts` hook)
- [ ] Epic 2 — Story 2.1 (Clusters list + register modal w/ health-check polling + detail — independent of 2.3/2.4)
- [ ] Epic 2 — Story 2.2 (Query sets list + create + detail + judgment-lists section + Generate-judgments — depends on 2.3 + 2.4 hooks)
- [ ] Epic 3 — Story 3.3 (Create-study 5-step modal — depends on 2.3 + 2.4 hooks)
- [ ] Epic 3 — Story 3.4 (Study detail + live polling + digest panel + `?action=open_pr` link)
- [ ] Epic 3 — Story 3.1 (Dashboard)
- [ ] Epic 4 — Story 4.1 (Docs + ui-architecture.md patch + US flips + state.md/CLAUDE.md)
- [ ] Epic 4 — Story 4.2 (Source-of-truth CI grep gate)

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (New/Modified file tables).
- [ ] Every option array with values sent to the backend carries the `// Values must match …` comment.
- [ ] Endpoints consumed match exactly what's documented (verified by msw handler URLs in tests).
- [ ] `pnpm typecheck` green.
- [ ] `pnpm lint` green.
- [ ] `pnpm test` green.
- [ ] `pnpm build` green (catches SSR / RSC issues that vitest doesn't).
- [ ] Manual smoke for the touched routes (`pnpm dev` → click through).
- [ ] If new shadcn primitive added: `components.json` updated (auto-handled by `shadcn add`).
- [ ] If new backend Literal consumed: source-of-truth comment present + Story 4.2 grep script passes locally.

## 11) Plan consistency review

Performed before marking the plan Ready for Execution.

**Counts to verify:**

- **Spec FRs:** 10 (FR-1..FR-10) + 2 CI ACs (AC-6, AC-9) → all mapped in §1 traceability table. ✓
- **Spec ACs:** 9 (AC-1..AC-9). All assigned: AC-1 across multiple (tutorial flow E2E); AC-2 → 3.4; AC-3 → 3.4; AC-4 → 2.4; AC-5 → 2.4; AC-6 → 4.2; AC-7 → 3.2; AC-8 → 3.1; AC-9 → 4.2. ✓
- **Endpoints consumed:** 27 distinct endpoints across stories (clusters: 4 [POST, GET list, GET detail, GET schema]; query-sets: 4; query-templates: 3; studies: 5; judgments: 7; proposals: 2 [GET `/studies/{id}/digest`, GET `/proposals` — POST/GET-detail/reject/open_pr left to `feat_proposals_ui`]; config-repos: 2). The backend exposes 34 total endpoints across these 7 routers; the 7 unused by this feature are: `DELETE /clusters/{id}` (no delete UI), `POST /clusters/{id}/run_query` (no run-query UI in MVP1), `GET /config-repos/{id}` (not needed by the cluster modal), `POST /proposals` + `GET /proposals/{id}` + `POST /proposals/{id}/reject` + `POST /proposals/{id}/open_pr` (all owned by `feat_proposals_ui`). **The digest endpoint is in `backend/app/api/v1/proposals.py:229`, not a separate digests router** — RelyLoop has no `digests.py` file (verified: `ls backend/app/api/v1/` lists 8 files, none named `digests.py`). No new backend endpoints added by this feature. ✓
- **Test files:** 21 listed in §3.1 + §3.2. All assigned to specific stories. ✓
- **Backend wire Literals consumed via `lib/enums.ts`:** 19 (`StudyStatusWire`, `TrialStatusWire`, `TrialSortKey`, `EngineTypeWire`, `AuthKind`, `Environment`, `HealthStatusValue`, `SamplerKind`, `PrunerKind`, `ObjectiveMetric`, `ObjectiveK`, `ObjectiveDirection`, `JudgmentListStatusWire`, `JudgmentSourceFilterWire`, `JudgmentSourceWire`, `RatingWire`, `ProposalStatusWire`, `ProposalPrStateWire`, `ConfigRepoProviderWire`). Each carries the source-of-truth comment. ✓

**Open spec questions:** None remaining per spec §19. ✓

**Codebase verification:**

| Claim | Verified by | Status |
|---|---|---|
| `ui/` uses the `src/` layout | `ls ui/src` | Verified — `app/`, `__tests__/` present |
| `ui/vitest.config.ts` glob is `src/**/*.test.{ts,tsx}` | Read of config | Verified |
| Tailwind 4 CSS-first, no `tailwind.config.ts` | `ls ui/` | Verified — no config file; `globals.css` has `@import 'tailwindcss'` |
| `backend/app/api/v1/schemas.py` exports all 19 Literals | grep | Verified |
| Endpoint paths match what the spec consumes | grep `@router.(get\|post\|patch\|delete)` over `backend/app/api/v1/*.py` | Verified — 28 endpoints, all listed in story consumption tables |
| Health-status badge variant names match shadcn `Badge` API | shadcn `Badge` ships `default`, `secondary`, `destructive`, `outline` — we add `success` and `warning` variants in Story 1.3 | Verified — extension noted in Story 1.3 |
| `next-themes` is needed | shadcn `init` requires `next-themes` for dark mode | Verified — included in Story 1.2 deps |
| `prism-react-renderer` works with React 19 | Latest version supports React 18+ | Verified — semver-compatible |
| Recharts works with React 19 | Recharts 2.13+ supports React 19 | Verified — included `recharts ^2` |
| Backend has no per-query DELETE endpoint on query sets | Read `query_sets.py` routes — only POST `/queries`, no DELETE | Verified — Story 2.2 task notes the limitation; per-query delete deferred to a follow-up idea file if operators request it |
| Backend `POST /clusters/{id}/run_query` exists but has no "history" endpoint | Read `clusters.py` | **Drift fix:** Story 2.1's cluster-detail does NOT render a run-query history table (spec §3 said "recent run-query history (if any)" — there's no such endpoint). Cluster detail shows summary + studies-by-this-cluster only. This deviates slightly from spec §3 wording; captured as a tangential observation. |

**Enum contract verification (Pass 2 §10):**

For each Literal used in the UI, the plan asserts the exact wire values + a source-of-truth comment. Spot-check three:

- `StudyStatusWire` (`backend/app/api/v1/schemas.py:164`) = `Literal["queued", "running", "completed", "cancelled", "failed"]`. Plan's `STUDY_STATUS_VALUES` = same 5 strings. ✓
- `ProposalStatusWire` (`backend/app/api/v1/schemas.py:659`) = `Literal["pending", "pr_opened", "pr_merged", "rejected"]`. Plan's `PROPOSAL_STATUS_VALUES` = same 4. ✓
- `ObjectiveK` (`backend/app/api/v1/schemas.py:170`) = `Literal[1, 3, 5, 10, 20, 50, 100]`. Plan's `OBJECTIVE_K_VALUES` = same 7 integers. ✓

The other 16 Literals follow the same pattern (verified during writing).

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests.
- [x] Every story specifies New/Modified files, Endpoints consumed, Key interfaces, Tasks, DoD.
- [x] Test layers (unit, component) scoped; contract + E2E correctly marked N/A.
- [x] Documentation updates across docs/01-05 are planned and assigned.
- [x] Lean refactor scope bounded (only the ui-architecture.md drift fix).
- [x] Epic gates measurable.
- [x] Verification gate (§10) included.
- [x] Consistency review (§11) performed.
