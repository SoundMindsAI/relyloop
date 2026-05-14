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

## Proposals routes (`/proposals` + `/proposals/{id}`)

Shipped with `feat_proposals_ui`. Two pages consume already-shipped backend endpoints (`GET /api/v1/proposals`, `GET /api/v1/proposals/{id}`, `POST /api/v1/proposals/{id}/reject`, `POST /api/v1/proposals/{id}/open_pr`) — there's no new backend surface here, so most issues fall into one of the categories below.

### Hook surface

All proposal queries / mutations live in [`ui/src/lib/api/proposals.ts`](../../ui/src/lib/api/proposals.ts):

| Hook | Purpose |
|---|---|
| `useProposals(filter, options?)` | List query. `filter.status` is narrowed to `ProposalStatus`. Optional `options.refetchInterval` (function form) for the list page's 30s pulse-refetch. |
| `useProposalForStudy(studyId)` | Preserved verbatim from before this feature — consumed by `feat_studies_ui`'s study-detail Open-PR button. Touch only if you know what you're doing. |
| `useProposal(id, options?)` | Detail query. `options.refetchInterval` (function form) drives the 3s / 30s / off cadence ladder on `/proposals/{id}`. |
| `useOpenPR()` | Mutation. POSTs to `/open_pr`. `onSettled` invalidates `['proposal', id]` + `['proposals']`. |
| `useRejectProposal()` | Mutation. POSTs `{ reason }` to `/reject`. Same invalidation set. |

### Polling cadence ladder (`/proposals/{id}`)

The detail page picks one of three rates per render based on the latest data + the page-state flag `postOpenPrPolling`:

| Trigger | Cadence | Source of truth |
|---|---|---|
| `postOpenPrPolling===true` AND `status==='pending'` AND `!pr_open_error` | **3 s** | `fireOpenPR`'s `onSuccess` flips `postOpenPrPolling` true; the refetchInterval function reads it on every tick. Cleared when status changes OR pr_open_error appears OR the 60 s safety `setTimeout` fires OR the page unmounts. |
| `status==='pr_opened'` AND `pr_state==='open'` | **30 s** | Steady-state webhook-fallback per FR-2. Inline check inside the refetchInterval function. |
| All other states | **off** | Function returns `false`. |

The 60 s safety cap is the only mechanism that flips `postOpenPrPolling` back to false. The cadence flips off inline inside the refetchInterval function when status changes, so the cap mostly matters for the "worker silently stuck" case.

### `?action=open_pr` auto-trigger

When the URL contains `?action=open_pr` AND the proposal is `pending`, the detail page calls `fireOpenPR()` once on mount and immediately runs `router.replace(\`/proposals/${id}\`)` to strip the param. A `useRef<boolean>` guards the in-mount Strict-Mode re-run. After firing, navigating away and back to the same proposal does NOT re-fire because the URL no longer carries the param.

This is the wire `feat_studies_ui`'s study-detail DigestPanel "Open PR" button uses — clicking that button navigates to `/proposals/{id}?action=open_pr`.

### Filter chips

Status filter is URL-backed via `?status=`. Cluster and source filters live in React state only.

- `?status=` is validated against `PROPOSAL_STATUS_VALUES` before being passed to `useProposals` — invalid values (e.g. `?status=invented`) are silently dropped client-side and the chip group falls back to "all" active. The chip won't 422 the backend.
- The **source filter** (study / manual / all) is a **client-side post-filter** over the fetched page. Backend has no `?source=` param. This means filtering to `manual` while paginating through many study-sourced proposals will show partial pages. Acceptable for MVP1 (<50 proposals/page realistically) — the [`chore_proposals_source_filter_server_side`](../02_product/planned_features/chore_proposals_source_filter_server_side/idea.md) idea file tracks the server-side follow-up.

### Common error codes surfaced as toasts

The UI uses `feat_studies_ui`'s global `MutationCache.onError` toast wiring — no per-mutation `onError` handlers. If a backend error surfaces, expect:

| error_code | Where it comes from | Fix |
|---|---|---|
| `PROPOSAL_NOT_FOUND` (404) | Detail page navigation to a deleted proposal | Empty state, no recovery needed |
| `INVALID_STATE_TRANSITION` (409) | Reject after webhook merged the PR, OR Open-PR on already-pr_opened proposal | UI auto-refetches the detail query; operator sees the new state |
| `CLUSTER_HAS_NO_CONFIG_REPO` (422) | Open PR on a cluster that has no `config_repo_id` | Operator must register a config_repo via `POST /api/v1/config-repos` first |
| `GITHUB_NOT_CONFIGURED` (503) | Per-repo PAT missing from `./secrets/<auth_ref>` | Populate the secret per `docs/04_security/github-token-handling.md` |
| `QUEUE_UNAVAILABLE` (503) | Arq pool absent OR enqueue raised | Check `docker compose logs worker`; verify Redis is reachable |

### Reject dialog won't close

The `AlertDialogAction` confirm button calls `event.preventDefault()` before invoking the mutation, so the dialog stays open during the in-flight POST. It closes only via the mutation's `onSuccess` callback. If the request 4xx/5xx errors, the dialog stays open AND the global toast fires. The detail query's invalidation refetches the proposal; if status flipped to a terminal value (e.g. `pr_merged` because the webhook beat the operator's click), the Reject dialog vanishes on the next render because `RejectDialog` early-returns when `proposal.status !== 'pending'`.

---

## Per-query editing (`feat_query_inline_crud`)

`/query-sets/[id]` renders `<QueriesTable>` with paginated rows and three inline row-actions:

* **Edit** — opens an anchored `<EditQueryPopover>` for `query_text` + `reference_answer`. Submits a minimal PATCH body (only the keys that changed). Empty body = silent close (no PATCH).
* **Edit metadata** (also reachable by clicking the "Set"/"—" metadata badge) — opens `<EditMetadataDialog>` with a JSON textarea. Save validates the JSON is a plain object (rejects arrays, scalars, `null` literal inline). "Clear metadata" sends exactly `{"query_metadata": null}` (distinct from empty body, which is a no-op).
* **Delete** — opens `<DeleteQueryDialog>`. Confirm sends DELETE.

### Delete returns 409 `QUERY_HAS_JUDGMENTS`

The DELETE endpoint guards against orphaning judgments. If any `judgments` row references the query, the response is 409 with this detail shape:

```json
{
  "detail": {
    "error_code": "QUERY_HAS_JUDGMENTS",
    "message": "query <id> has N judgments across M judgment list(s); remove the parent judgment list(s) first",
    "retryable": false,
    "judgment_lists": [{"id": "...", "name": "..."}],
    "overflow_count": 0
  }
}
```

`useDeleteQuery` is the **single carve-out** from the global error toast — it sets `meta.suppressGlobalErrorToast: true` and renders the 409 as a destructive toast with a Sonner `action` slot. Click "Open `<first list name>` →" to navigate to `/judgments/{first_id}`; delete the parent judgment list there; come back and retry the per-query delete.

Non-409 errors (404 `QUERY_SET_NOT_FOUND`, 404 `QUERY_NOT_FOUND`, 422 `VALIDATION_ERROR`) fall through to `toToastMessage(err)` formatting for parity with the global handler.

### Common error codes (`/query-sets/{id}/queries*`)

| Code (HTTP) | Cause | Recovery |
|---|---|---|
| `QUERY_SET_NOT_FOUND` (404) | Parent set was deleted | Navigate back to `/query-sets` |
| `QUERY_NOT_FOUND` (404) | Query was deleted concurrently OR cross-set lookup (anti-enumeration) | Refetch the list — the row will disappear |
| `QUERY_HAS_JUDGMENTS` (409) | Delete blocked by FK to `judgments.query_id` | Follow the toast action link |
| `VALIDATION_ERROR` (422) | Bad cursor / out-of-range limit / malformed `?since` / extra PATCH field / explicit-null `query_text` | Toast surfaces the validation message |

### Anti-enumeration note

PATCH and DELETE on a `query_id` that exists in a **different** `query_set_id` than the one in the URL returns 404 `QUERY_NOT_FOUND` — same shape as a truly missing query. Operators see no information about whether the query exists elsewhere. Spec §10 Threat 2.

---

## See also

- [`docs/01_architecture/ui-architecture.md`](../01_architecture/ui-architecture.md) — design rationale
- [`docs/01_architecture/api-conventions.md`](../01_architecture/api-conventions.md) — error envelope + cursor pagination contract
- [`docs/03_runbooks/study-lifecycle-debugging.md`](study-lifecycle-debugging.md) — backend-side polling triage
- [`docs/03_runbooks/optuna-debugging.md`](optuna-debugging.md) — orchestrator wedges that look like stuck polling
- [`docs/03_runbooks/pr-open-debugging.md`](pr-open-debugging.md) — open_pr worker debugging when the UI surfaces `pr_open_error`
- [`docs/03_runbooks/webhook-debugging.md`](webhook-debugging.md) — GitHub webhook receiver triage when `pr_state` updates lag
