# UI debugging runbook

**Status:** Active — covers MVP1's Next.js + TanStack Query stack.
**Last updated:** 2026-05-12 (lands with `feat_studies_ui`).
**Audience:** operators running RelyLoop locally via `make up`; engineers triaging UI regressions.

---

## Stack quick reference

- Next.js 16 (App Router + Turbopack) under `ui/src/app/`.
- TanStack Query 5 for server state. All data hooks live in `ui/src/lib/api/<resource>.ts`.
- React 19 / Tailwind 4 (CSS-first; design tokens in `ui/src/app/globals.css` under `@theme {}`).
- shadcn primitives in `ui/src/components/ui/` (built on radix-ui).
- Generated OpenAPI types at `ui/src/lib/types.ts` (run `cd ui && pnpm types:gen` against a running backend).
- Wire-value allowlists in `ui/src/lib/enums.ts` — every option array sent to the backend MUST be grounded in one of these.

```bash
cd ui
pnpm dev          # http://localhost:3000 (Turbopack)
pnpm typecheck    # tsc --noEmit (strict)
pnpm lint         # eslint flat config (errors + warnings)
pnpm test         # vitest run (jsdom + msw)
pnpm build        # next build (catches SSR / RSC violations)
```

API base URL is taken from `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`). Vitest overrides this to `http://api.test` via `vitest.config.ts` so msw can mock without colliding with a running stack on 8000.

---

## Inspecting the TanStack Query cache

The dev build mounts `@tanstack/react-query-devtools` automatically (`QueryProvider` in `ui/src/components/providers/query-provider.tsx`). Open the devtools panel from the floating button at the bottom-right of any page.

- Each query is keyed by `["<resource>", <filter-object>]` — e.g. `["studies", {status: "running", cursor: undefined, limit: 50}]`.
- Mutations invalidate their owning keys on success (see the `onSuccess: qc.invalidateQueries(...)` blocks in each `lib/api/*.ts` file).
- Set `meta.suppressErrorCodes: ["DIGEST_NOT_READY"]` on a `useQuery` to silence the global toast for specific error codes (see `useStudyDigest`).
- Set `meta.suppressGlobalErrorToast: true` to skip the global toast entirely — useful when a form surfaces errors inline.

To force-refetch a query manually in devtools: click the query → "Refetch". To force-fail it: bring the dev server down or send the page to an unreachable host via `NEXT_PUBLIC_API_BASE_URL`.

---

## Reproducing a polling regression

Study detail polls trials at 3s while the study is in `running` state. Mechanism:

```ts
// ui/src/app/studies/[id]/page.tsx
const studyQ = useStudy(studyId, {
  refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
});
```

If polling fails to start or stop:

1. Open devtools → confirm `studies[<id>]` is being refetched at 3s. Devtools shows the next-refetch countdown on each query.
2. Check `studyQ.data?.status` in the React DevTools profiler / state inspector — the source-of-truth for the polling gate.
3. Verify the backend returns the expected status. `curl http://localhost:8000/api/v1/studies/<id>` from the dev shell.
4. If polling never stops after completion: confirm the backend actually transitioned the study to `completed`. The orchestrator may have crashed or be wedged on an Optuna ask/tell race (see `docs/03_runbooks/optuna-debugging.md`).

---

## Tracing a UI error back to backend logs via X-Request-ID

Every `apiClient` request injects an `X-Request-ID: <UUIDv7>` header (`ui/src/lib/api-client.ts`). The backend logs the value as `request_id` in structured logs and echoes it on the response.

1. Browser → Devtools → Network → click the failing request → Headers → copy `X-Request-ID`.
2. Backend logs: `docker compose logs api 2>&1 | rg "<request-id>"` (or `make logs`).
3. The matching log line includes the route, status code, and any `error_code` raised by the handler. Cross-reference with the API error catalog in `docs/01_architecture/api-conventions.md`.

If the toast in the UI shows an `error_code` that doesn't match the backend log, the front-end is likely sending a different request than you expect — verify the Network tab path + payload before chasing a backend bug.

---

## Common gotchas

### "Unknown error" toast / `INTERNAL_ERROR` shown for every request

Either the backend isn't running, the API base URL is misconfigured, or the response shape doesn't match the standard error envelope (`{ detail: { error_code, message, retryable } }`). Verify:

```bash
curl -i http://localhost:8000/healthz   # should return 200 + JSON
echo $NEXT_PUBLIC_API_BASE_URL           # should be unset or http://localhost:8000
```

### `ApiError(errorCode='SERVICE_UNAVAILABLE', status=0)` toast

`fetch` rejected with `TypeError` — backend unreachable. The api-client retried 4 times (1s/2s/4s backoff) before surfacing the toast. Restart the stack with `make up` or check `make logs`.

### Stale `ui/src/lib/types.ts`

The committed `types.ts` was generated from a backend OpenAPI snapshot. If a new endpoint is added or an existing one renamed, regenerate from a live backend:

```bash
make up                   # ensure backend is on http://localhost:8000
cd ui && pnpm types:gen
git diff src/lib/types.ts # review
```

CI does NOT regenerate (no `make up` in the workflow) — the committed file is the source of truth for PR review.

### Enum drift between frontend and backend

If a backend Literal gains or loses a value (e.g., `StudyStatusWire` adds `"paused"`), the frontend will silently accept it on read but reject it on write — or render a broken filter chip. The Story 4.2 grep gate scans `ui/src/lib/enums.ts` and fails CI when the documented backend symbol doesn't match the local array. To debug locally:

```bash
bash scripts/ci/verify_enum_source_of_truth.sh
```

### Sonner toast doesn't appear

The `<Toaster />` is mounted in `ui/src/app/layout.tsx` (added by Story 1.2). If you removed or moved the layout wrapper, restore the `<ThemeProvider><QueryProvider><Toaster /><TopNav />{children}</QueryProvider></ThemeProvider>` ordering — Toaster must be inside the QueryProvider so the global error handler can fire toasts.

### Radix Select / Popover / AlertDialog crashes in vitest

jsdom 29 doesn't ship `Element.scrollIntoView` / `hasPointerCapture` / `releasePointerCapture` — radix calls these inside effects when items focus. The polyfills live in `ui/src/__tests__/setup.ts`. If you add a new shadcn primitive whose behaviour calls another browser API jsdom is missing, extend the setup file.

### Secrets-not-mounted causing tutorial flow to fail

The UI surfaces backend `error_code` toasts verbatim. Common ones during the tutorial flow:

| error_code | Fix |
|---|---|
| `OPENAI_NOT_CONFIGURED` | Mount the OpenAI key per `docs/01_architecture/llm-orchestration.md`. |
| `LLM_PROVIDER_INCAPABLE` | Local LLM doesn't support strict JSON schema. Switch model or run capability check. |
| `OPENAI_BUDGET_EXCEEDED` | Daily budget cap reached. Raise the limit or wait until midnight UTC. |
| `CLUSTER_UNREACHABLE` | Verify the registered cluster's `base_url` + credentials. See `docs/03_runbooks/cluster-registration.md`. |
| `AUTH_REF_NOT_FOUND` | The cluster's `credentials_ref` points at `./secrets/<name>` which doesn't exist. Create the file. |

---

## See also

- [`docs/01_architecture/ui-architecture.md`](../01_architecture/ui-architecture.md) — design rationale
- [`docs/01_architecture/api-conventions.md`](../01_architecture/api-conventions.md) — error envelope + cursor pagination contract
- [`docs/03_runbooks/study-lifecycle-debugging.md`](study-lifecycle-debugging.md) — backend-side polling triage
- [`docs/03_runbooks/optuna-debugging.md`](optuna-debugging.md) — orchestrator wedges that look like stuck polling
