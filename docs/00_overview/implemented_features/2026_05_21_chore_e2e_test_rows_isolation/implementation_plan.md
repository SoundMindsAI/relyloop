# Implementation Plan — chore_e2e_test_rows_isolation

**Date:** 2026-05-21
**Status:** Complete (PR #186 squash `a444b94`, merged 2026-05-21)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [api-conventions.md](../../../01_architecture/api-conventions.md), [CLAUDE.md](../../../../CLAUDE.md), spec §19 Decision log

---

## 0) Planning principles

- Spec traceability first — every story maps to FRs.
- Single epic, two stories — chore scope; bundling backend + frontend into one PR is appropriate (no cross-PR coordination needed, no operator-facing API change to roll forward).
- Backend before frontend within the branch: the 6 new DELETE endpoints must be live in the local stack before the frontend `globalTeardown` calls them.
- Single PR. The drive-by behaviors (legacy-cleanup instruction in PR body, dashboard regen) are handled in the same commit.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (DELETE /_test/proposals/{id}) | Epic 1 / Story 1.1 | Hard-delete + 404 envelope |
| FR-2 (DELETE /_test/digests/{id}) | Epic 1 / Story 1.1 | Hard-delete + 404 envelope |
| FR-3 (DELETE /_test/studies/{id}) | Epic 1 / Story 1.1 | Cascade trials via existing FK; 409 for proposal/digest dependents |
| FR-4 (DELETE /_test/judgment-lists/{id}) | Epic 1 / Story 1.1 | Cascade judgments via existing FK; 409 for study dependents |
| FR-5 (DELETE /_test/query-sets/{id}) | Epic 1 / Story 1.1 | Cascade queries via existing FK; 409 for study/judgment_list dependents |
| FR-6 (DELETE /_test/query-templates/{id}) | Epic 1 / Story 1.1 | 409 for study/proposal/judgment_list dependents (fixed priority order: STUDY > PROPOSAL > JUDGMENT_LIST) |
| FR-7 (Cleanup registry + globalSetup/Teardown) | Epic 1 / Story 1.2 | Per-worker JSONL files + reporter |

All 7 FRs covered. Single phase per spec §3 — no `phase*_idea.md` tracking files needed.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions

- Repo functions: `db: AsyncSession` first arg; `db.flush()` (caller commits). Match the `soft_delete_cluster` / `soft_delete_conversation` patterns at [`backend/app/db/repo/cluster.py:163-168`](../../../../backend/app/db/repo/cluster.py#L163-L168) and [`backend/app/db/repo/conversation.py`](../../../../backend/app/db/repo/conversation.py).
- Router pattern: extend the existing `_test.py` file ([`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py)); single router, single `_TEST_PREFIX = "/_test"` constant, single `_require_development_env` dependency. Test-only endpoint precedent.
- Handler signature pattern: `@router.delete(f"{_TEST_PREFIX}/<resource>/{{<resource>_id}}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, tags=["test-only"], dependencies=[Depends(_require_development_env)])` per spec §7.5 lock.
- Error envelope: existing `_err(status_code, code, message, retryable)` helper at [`_test.py`] (NOT explicitly defined — copy the pattern from [`backend/app/api/v1/studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78)). The `_test.py` currently raises `HTTPException` inline at lines 46-54 for the env guard. Story 1.1 adds a `_err` helper to `_test.py` (mirror the studies-router pattern) so all 7 endpoints (1 existing seed-completed + 6 new) emit consistent envelopes.
- Conventional Commits per CLAUDE.md.

### AI Agent Execution Protocol

0. Load context: `architecture.md`, `state.md`, this plan, the spec.
1. Implement Story 1.1 (backend) first. Backend tests + lint + typecheck before moving to Story 1.2.
2. Restart `api` container with `docker compose up -d --build api` so the new endpoints are live before Story 1.2 starts.
3. Implement Story 1.2 (frontend) second. Run vitest + lint + build. The Playwright suite is exercised end-to-end as the final gate before push.
4. (Types regen is the FIRST task of Story 1.2 — see Story 1.2 task #8. Do NOT run `pnpm types:gen` here as a separate step; it would either be too early (Story 1.1's container rebuild hasn't landed yet) or duplicative.)
5. `state.md` + `api-conventions.md` updates land in the same PR (Story 1.1 DoD).
6. Attach evidence in the PR description (commands run, file inventory).

---

## Epic 1 — Cleanup polluted E2E seed rows

### Story 1.1 — Backend: 6 test-only DELETE endpoints + repo functions + docs

**Outcome:** `DELETE /api/v1/_test/{resource}/{id}` for proposals, digests, studies, judgment-lists, query-sets, query-templates — all gated by `_require_development_env`, returning 204 on success, 404 (`<RESOURCE>_NOT_FOUND` or env-guard `RESOURCE_NOT_FOUND`) on missing/outside-dev, 409 (`<RESOURCE>_HAS_DEPENDENT_<X>`) on FK violation.

**Traces to:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-6.

**New files**

None (extend existing `backend/app/api/v1/_test.py`).

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/_test.py` | Add `_err(...)` helper mirroring `studies.py:74-78`. Add 6 `@router.delete(...)` handlers per the spec §7.5 handler pattern. Each handler: preflight-EXISTS check for dependents → 409 if any exist; call repo's `hard_delete_<resource>(db, id)` → 404 if returns `False`; `await db.commit()`; return `Response(status_code=204)`. |
| `backend/app/db/repo/proposal.py` | Add `hard_delete_proposal(db: AsyncSession, proposal_id: str) -> bool`. Returns `True` on row deleted, `False` if not found. No FK preflight here — handler owns that. Use `await db.flush()`. |
| `backend/app/db/repo/digest.py` | Add `hard_delete_digest(db: AsyncSession, digest_id: str) -> bool`. Same shape. |
| `backend/app/db/repo/study.py` | Add `hard_delete_study(db: AsyncSession, study_id: str) -> bool`. Same shape. Trials cascade-delete via existing FK at `trial.py:60`. |
| `backend/app/db/repo/judgment_list.py` | Add `hard_delete_judgment_list(db: AsyncSession, judgment_list_id: str) -> bool`. Same shape. Judgments cascade-delete via existing FK at `judgment.py:61`. |
| `backend/app/db/repo/query_set.py` | Add `hard_delete_query_set(db: AsyncSession, query_set_id: str) -> bool`. Same shape. Queries cascade-delete via existing FK at `query.py:32`. |
| `backend/app/db/repo/query_template.py` | Add `hard_delete_query_template(db: AsyncSession, template_id: str) -> bool`. Same shape. |
| `backend/app/db/repo/__init__.py` | Export the 6 new functions in the `__all__` block. |
| `docs/01_architecture/api-conventions.md` | Append a "Test-only endpoints" subsection covering the 11 strictly new error codes per spec §7.5 + cross-reference the 4 reused codes (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `RESOURCE_NOT_FOUND`). |
| `backend/tests/contract/test_openapi_surface.py` | Add 6 new `("delete", "/api/v1/_test/<resource>/{<id>}", "204")` tuples to `EXPECTED_ENDPOINTS` (insert after the existing `("post", "/api/v1/_test/studies/seed-completed", "201")` at line 95). |
| `backend/tests/contract/test_test_endpoint_guard.py` | Add 6 new env-guard test cases — one per new endpoint — asserting `Settings.environment != "development"` → 404 `RESOURCE_NOT_FOUND`. |
| `backend/tests/integration/test_test_endpoints.py` (NEW) | 20 new integration cases per spec §14: 6 happy paths + 6 404s + 8 409s (full dependent-code coverage). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `DELETE` | `/api/v1/_test/proposals/{proposal_id}` | — | `204` (no body) | `PROPOSAL_NOT_FOUND` (404), `RESOURCE_NOT_FOUND` (404 — env guard) |
| `DELETE` | `/api/v1/_test/digests/{digest_id}` | — | `204` (no body) | `DIGEST_NOT_FOUND` (404), `RESOURCE_NOT_FOUND` (404 — env guard) |
| `DELETE` | `/api/v1/_test/studies/{study_id}` | — | `204` (no body) | `STUDY_NOT_FOUND` (404), `STUDY_HAS_DEPENDENT_PROPOSAL` (409), `STUDY_HAS_DEPENDENT_DIGEST` (409), `RESOURCE_NOT_FOUND` (404 — env guard) |
| `DELETE` | `/api/v1/_test/judgment-lists/{judgment_list_id}` | — | `204` (no body) | `JUDGMENT_LIST_NOT_FOUND` (404 — reused), `JUDGMENT_LIST_HAS_DEPENDENT_STUDY` (409), `RESOURCE_NOT_FOUND` (404 — env guard) |
| `DELETE` | `/api/v1/_test/query-sets/{query_set_id}` | — | `204` (no body) | `QUERY_SET_NOT_FOUND` (404 — reused), `QUERY_SET_HAS_DEPENDENT_STUDY` (409), `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST` (409), `RESOURCE_NOT_FOUND` (404 — env guard) |
| `DELETE` | `/api/v1/_test/query-templates/{template_id}` | — | `204` (no body) | `TEMPLATE_NOT_FOUND` (404 — reused), `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY` (409), `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL` (409), `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST` (409), `RESOURCE_NOT_FOUND` (404 — env guard) |

**Pydantic schemas**

No new request/response schemas — DELETE handlers take only a path parameter and return `204 No Content`. The error envelope is the standard `_err(...)` shape per `studies.py:74-78`.

**Key interfaces**

```python
# backend/app/db/repo/<resource>.py — one per resource, all identical shape:
async def hard_delete_<resource>(db: AsyncSession, <resource>_id: str) -> bool:
    """Hard-delete the row. Returns True if a row was deleted, False if no
    row existed. Caller commits. Cascade behavior: trials/judgments/queries
    cascade via existing FK ondelete="CASCADE"; no manual delete needed
    for those. Proposals/digests/studies/judgment_lists/query_sets/
    query_templates are themselves the cascade roots — the handler must
    preflight any non-cascade dependents and 409 before reaching here.
    """
```

```python
# backend/app/api/v1/_test.py — handler pattern for all 6 endpoints
# (identical shape; example shown for studies):
@router.delete(
    f"{_TEST_PREFIX}/studies/{{study_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
)
async def delete_study(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    # Preflight EXISTS checks for non-cascade dependents.
    from backend.app.db.models import Proposal, Digest
    from sqlalchemy import select, exists
    has_proposal = (await db.execute(
        select(exists().where(Proposal.study_id == study_id))
    )).scalar()
    if has_proposal:
        raise _err(409, "STUDY_HAS_DEPENDENT_PROPOSAL",
                   "study has dependent proposal; delete proposal(s) first", False)
    has_digest = (await db.execute(
        select(exists().where(Digest.study_id == study_id))
    )).scalar()
    if has_digest:
        raise _err(409, "STUDY_HAS_DEPENDENT_DIGEST",
                   "study has dependent digest; delete digest first", False)
    deleted = await repo.hard_delete_study(db, study_id)
    if not deleted:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

The other 5 handlers follow the same shape with resource-specific:
- preflight EXISTS checks (none for proposals + digests; 1 for judgment_lists + query_templates — actually 1 for JL, 2 for query-sets, 3 for query-templates)
- repo function name + 404 code
- preflight order for query_templates: STUDY → PROPOSAL → JUDGMENT_LIST (fixed priority per spec FR-6).

**Tasks**

1. Add `_err(...)` helper to `_test.py` (mirror `studies.py:74-78`).
2. Add `hard_delete_<resource>(db, id) -> bool` to each of the 6 repo files. Use `delete(<Model>).where(<Model>.id == id)` with `result.rowcount == 1` to determine `True/False`. Use `await db.flush()`. Verify: this approach avoids fetching the row first (one SQL roundtrip instead of two).
3. Add 6 DELETE handlers to `_test.py` following the pattern above.
4. Export new repo functions in `backend/app/db/repo/__init__.py`.
5. Append a "Test-only endpoints" subsection to `docs/01_architecture/api-conventions.md` documenting the **11 strictly new** codes (3 NOT_FOUND + 8 HAS_DEPENDENT) AND cross-referencing the 3 reused codes (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`) + the already-documented `RESOURCE_NOT_FOUND`. Match spec §15 wording.
6. Update `backend/tests/contract/test_openapi_surface.py:EXPECTED_ENDPOINTS` with the 6 new tuples.
7. Extend `backend/tests/contract/test_test_endpoint_guard.py` with 6 new env-guard cases (parameterize over the new endpoint paths).
8. Create `backend/tests/integration/test_test_endpoints.py` with the 20 cases per spec §14.
9. Run `make backend-fmt && make backend-lint && make backend-typecheck && make test-unit`.
10. Rebuild + restart the api container: `docker compose build api && docker compose up -d api`.
11. Run in-container integration + contract: `docker run --rm --network relyloop_default -v $(pwd):/app -v /app/.venv -w /app -e DATABASE_URL_FILE=/app/secrets/database_url -e POSTGRES_PASSWORD_FILE=/app/secrets/postgres_password ghcr.io/astral-sh/uv:python3.13-bookworm bash -c 'uv sync --quiet && uv run pytest backend/tests/integration/test_test_endpoints.py backend/tests/contract/test_test_endpoint_guard.py backend/tests/contract/test_openapi_surface.py -v --tb=short'`.
12. Curl-smoke each new endpoint against the live api container (operator-path verification per CLAUDE.md):
    ```bash
    # Happy path: create a proposal via the standard API, then delete it via /_test.
    # Verify 204 + row is gone.
    curl -X DELETE http://localhost:8000/api/v1/_test/proposals/{some_id} -i
    # Outside dev — should always be 404 RESOURCE_NOT_FOUND.
    # Cannot verify locally without spinning a non-dev container; rely on the
    # contract test for that surface.
    ```

**Definition of Done**

- [ ] All 6 endpoints return 204 on happy path (integration test asserts row count = 0 in the affected tables, including cascade children).
- [ ] All 6 endpoints return 404 with the right `<RESOURCE>_NOT_FOUND` code when the id doesn't exist.
- [ ] All 6 endpoints return 404 `RESOURCE_NOT_FOUND` outside `ENVIRONMENT=development` (contract test).
- [ ] All 8 dependent-row codes verified: `STUDY_HAS_DEPENDENT_PROPOSAL`, `STUDY_HAS_DEPENDENT_DIGEST`, `JUDGMENT_LIST_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST`, `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY`, `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL`, `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST` (each is a separate integration test).
- [ ] `make test-unit` (1040+ tests pass), in-container integration + contract (existing total + 20 new + 6 env-guard cases + 6 OpenAPI tuples) all green.
- [ ] `docs/01_architecture/api-conventions.md` includes the 11 strictly new codes + cross-references to 4 reused.
- [ ] `make backend-lint && make backend-typecheck` clean.
- [ ] Operator-path smoke verified: hit each endpoint once via curl against the live container.

---

### Story 1.2 — Frontend: cleanup registry + globalSetup/Teardown + reporter

**Outcome:** Every Playwright run, on success or assertion-failure, drains all rows seeded by `seedXxx()` helpers via the new test-only DELETE endpoints. Cleanup is suite-scoped (`globalTeardown`), file-backed (per-worker JSONL), and best-effort (failures logged to stdout + reporter assertion, never fail the suite exit code in v1).

**Traces to:** FR-7 (all sub-clauses).

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/helpers/cleanup-core.ts` | **Pure module** — types (`ResourceType`, `CleanupEntry`), constants (`RESOURCE_PATH_MAP`, `DRAIN_ORDER`), and pure functions (`dedupeEntries`, `orderEntries`, `buildDeleteUrl`). No fs/network. Testable in isolation. |
| `ui/tests/e2e/global-setup.ts` | Clear `test-results/.cleanup/` directory AND remove stale `test-results/cleanup-summary.json` + `test-results/cleanup-verification-failures.txt` at run start. Otherwise the reporter could read a prior run's summary if the current run's `globalTeardown` crashes before writing — producing a false `OK` reading. |
| `ui/tests/e2e/global-teardown.ts` | Thin orchestration wrapper around `cleanup-core`. Read every `test-results/.cleanup/worker-*.jsonl`, dedupe + order via `cleanup-core`, drain via `fetch` against URLs built from `resolveApiBaseUrl(config)` + `buildDeleteUrl()`. Write `test-results/cleanup-summary.json` artifact. Remove `test-results/.cleanup/` at exit. |
| `ui/tests/e2e/cleanup-reporter.ts` | New Playwright Reporter implementing `onEnd(result)` — reads `cleanup-summary.json` (written by globalTeardown), asserts the invariants `registered_deduped == attempted` AND `attempted == deleted + failed + skipped_404` AND `failed == 0`. Logs PASS/FAIL to stdout; writes `cleanup-verification-failures.txt` on failure. Does NOT alter exit code in v1 (developer-ergonomics gate). |
| `ui/tests/e2e/helpers/__tests__/cleanup-core.test.ts` | Vitest unit tests for `cleanup-core`'s pure functions: `dedupeEntries` (preserves stable order, dedupes by `(resource, id)`), `orderEntries` (FK-safe drain order), `buildDeleteUrl` (encodes id, handles base URL with/without trailing slash), `RESOURCE_PATH_MAP` exhaustiveness (every `ResourceType` has a path). |
| `ui/tests/e2e/helpers/__tests__/cleanup-registry.test.ts` | Vitest unit tests for `appendForCleanup` in `seed.ts`: creates dir, appends valid JSON-line, respects `TEST_WORKER_INDEX` env var (and falls back to `'0'`). Uses `tmp` fixture to avoid polluting real `test-results/`. |
| `ui/tests/e2e/__tests__/global-teardown.test.ts` | Vitest unit test for `global-teardown.ts` orchestration: spawns a tempdir with pre-populated `worker-0.jsonl` + `worker-1.jsonl`, mocks `fetch` via `vi.spyOn(global, 'fetch')`, runs the teardown's exported default function, asserts: (a) fetch was called in FK-safe order; (b) summary artifact has the right shape; (c) `.cleanup/` is removed at exit; (d) the `apiBaseUrl` resolution honors `config.metadata.apiBaseUrl`. |
| `ui/tests/e2e/helpers/coverage-audit.md` | Static doc enumerating which Playwright spec currently exercises each of the 9 `seedXxx()` helpers — produced by `grep -rn "<helperName>(" ui/tests/e2e/*.spec.ts` audit during Story 1.2. Any uncovered helper requires a targeted vitest case (see Tasks). |

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/helpers/seed.ts` | (1) Import `ResourceType` from new `./cleanup-core.ts`. (2) Add `appendForCleanup(resource: ResourceType, id: string)` exported function using `fs.appendFileSync(workerJsonlPath, JSON.stringify({resource, id}) + '\n')` with `TEST_WORKER_INDEX` env-var resolution. (3) Wire `appendForCleanup` into the **5 direct-create helpers**: `seedCluster`, `seedQuerySet` (cluster + query_set + optional judgment_list), `seedTemplate`, `seedJudgmentList`, `seedStudy`. (4) Wire `appendForCleanup` into the **2 seed-completed composites** `seedStudyCompletedWithDigest` and `seedStudyCompletedWithPerQueryMetrics`: extract `study_id` + `digest_id` + `proposal_id` from the existing `SeedCompletedStudyResponse` (per [`_test.py:100-105`](../../../../backend/app/api/v1/_test.py#L100-L105)) and append all 3 (or 2 if `with_pending_proposal: false`). (5) Wire `appendForCleanup` into `seedAcmeProductsChain` for every newly-inserted row (cluster + query_set + queries-cascade-noop + template + judgment_list + study). (6) **Do NOT wire into `seedFullChain`** — it's a pure delegated wrapper around sub-helpers per spec §2 ("delegated — sub-helpers register"). Adding `appendForCleanup` at the wrapper level would double-register; dedupe would mask the bug but `registered != registered_deduped` would surface anomalously. The 9th "helper" is the wrapper; the actual append-call count is 6 helpers (5 direct + 1 composite, which itself appends 1-3 times per call). |
| `ui/playwright.config.ts` | Add `globalSetup: './tests/e2e/global-setup.ts'`, `globalTeardown: './tests/e2e/global-teardown.ts'`, and extend `reporter` to include `cleanup-reporter.ts` alongside the existing `'github'`/`'list'`. The `reporter` field becomes an array: `[<existing>, ['./tests/e2e/cleanup-reporter.ts']]`. |
| `ui/src/lib/types.ts` | Regenerate from live OpenAPI (after Story 1.1 ships the new endpoints) so the type surface includes them. Generated artifact — owned by Story 1.1's backend-merge gate AND Story 1.2's consumption gate. |

**Endpoints**

No new endpoints from the frontend side — Story 1.2 consumes Story 1.1's endpoints.

**Pydantic schemas**

N/A — frontend-only story.

**Key interfaces**

```typescript
// ui/tests/e2e/helpers/cleanup-core.ts (NEW — pure module, no fs/network in
// its named exports; testable in isolation).

export type ResourceType =
  | 'proposal'
  | 'digest'
  | 'study'
  | 'judgment_list'
  | 'query_set'
  | 'query_template'
  | 'cluster';

export interface CleanupEntry {
  resource: ResourceType;
  id: string;
}

// Registry-resource → URL-path mapping (per spec §FR-7 table).
export const RESOURCE_PATH_MAP: Record<ResourceType, string> = {
  proposal: '/api/v1/_test/proposals',
  digest: '/api/v1/_test/digests',
  study: '/api/v1/_test/studies',
  judgment_list: '/api/v1/_test/judgment-lists',
  query_set: '/api/v1/_test/query-sets',
  query_template: '/api/v1/_test/query-templates',
  cluster: '/api/v1/clusters',  // existing soft-delete, NOT under /_test
};

// FK-safe drain order (children → parents).
export const DRAIN_ORDER: readonly ResourceType[] = [
  'proposal',
  'digest',
  'study',
  'judgment_list',
  'query_set',
  'query_template',
  'cluster',
] as const;

/** Dedupe entries by (resource, id). Stable order preserved. */
export function dedupeEntries(entries: readonly CleanupEntry[]): CleanupEntry[] {
  const seen = new Set<string>();
  const out: CleanupEntry[] = [];
  for (const e of entries) {
    const key = `${e.resource}:${e.id}`;
    if (!seen.has(key)) { seen.add(key); out.push(e); }
  }
  return out;
}

/** Sort entries by FK-safe DRAIN_ORDER (resource group); within a group,
 * preserve insertion order. */
export function orderEntries(entries: readonly CleanupEntry[]): CleanupEntry[] {
  return [...entries].sort((a, b) =>
    DRAIN_ORDER.indexOf(a.resource) - DRAIN_ORDER.indexOf(b.resource));
}

/** Build the absolute DELETE URL for a (resource, id). */
export function buildDeleteUrl(apiBaseUrl: string, entry: CleanupEntry): string {
  const path = RESOURCE_PATH_MAP[entry.resource];
  // encodeURIComponent the id so UUIDv7 / arbitrary strings don't break the URL.
  return new URL(`${path}/${encodeURIComponent(entry.id)}`, apiBaseUrl).toString();
}

/**
 * Read all worker-*.jsonl files under `cleanupDir`, parse JSON-line entries.
 * Returns the raw parsed entries (NOT yet deduped) + a parseFailures count
 * for diagnostics. Pure: only reads from disk; throws only if the directory
 * is unreadable (caller decides whether that's fatal).
 */
export function readCleanupEntriesFromDir(
  cleanupDir: string,
  fsModule: typeof import('node:fs') = require('node:fs'),
): { raw: CleanupEntry[]; parseFailures: number } {
  if (!fsModule.existsSync(cleanupDir)) return { raw: [], parseFailures: 0 };
  const files = fsModule.readdirSync(cleanupDir).filter((f) => /^worker-.+\.jsonl$/.test(f));
  const raw: CleanupEntry[] = [];
  let parseFailures = 0;
  for (const f of files) {
    const lines = fsModule.readFileSync(`${cleanupDir}/${f}`, 'utf8').split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try { raw.push(JSON.parse(line) as CleanupEntry); }
      catch { parseFailures += 1; }
    }
  }
  return { raw, parseFailures };
}
```

```typescript
// ui/tests/e2e/helpers/seed.ts — registry I/O. Imports types from cleanup-core.

import {
  type CleanupEntry,
  type ResourceType,
} from './cleanup-core';

/**
 * Resolve the cleanup JSONL path for the current worker. Playwright sets
 * `TEST_WORKER_INDEX` per worker process (@playwright/test contract — NOT
 * `PLAYWRIGHT_WORKER_INDEX` which was a misnomer in an earlier plan
 * revision). Fall back to '0' for unit-test contexts where Playwright
 * isn't driving (per spec §FR-7).
 */
function getWorkerJsonlPath(): string {
  const idx =
    process.env.TEST_WORKER_INDEX ??
    process.env.PLAYWRIGHT_WORKER_INDEX ??  // tolerate the misnomer if a future
                                            // PR's env honors both
    '0';
  return path.join(process.cwd(), 'test-results', '.cleanup', `worker-${idx}.jsonl`);
}

/**
 * Append a row to the worker's cleanup JSONL. Synchronous + atomic at the OS
 * level for sub-PIPE_BUF writes. Creates the directory if absent.
 */
export function appendForCleanup(resource: ResourceType, id: string): void {
  const filePath = getWorkerJsonlPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const line = JSON.stringify({ resource, id } satisfies CleanupEntry) + '\n';
  fs.appendFileSync(filePath, line);
}
```

```typescript
// ui/tests/e2e/global-teardown.ts — thin orchestration wrapper around the
// pure cleanup-core functions. Side effects only happen here.

import type { FullConfig } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';
import {
  type CleanupEntry,
  type ResourceType,
  RESOURCE_PATH_MAP,
  DRAIN_ORDER,
  dedupeEntries,
  orderEntries,
  buildDeleteUrl,
  readCleanupEntriesFromDir,  // NEW per cycle-2 export; cycle-3 verified the import.
} from './helpers/cleanup-core';

/**
 * Resolve the API base URL by reading Playwright's config metadata
 * (configured at ui/playwright.config.ts:45-47 as `metadata.apiBaseUrl`).
 * Falls back to PLAYWRIGHT_API_BASE_URL env var, then to the hardcoded
 * default 'http://127.0.0.1:8000'.
 */
function resolveApiBaseUrl(config: FullConfig): string {
  const fromMetadata = (config.metadata as { apiBaseUrl?: string } | undefined)?.apiBaseUrl;
  return (
    fromMetadata ??
    process.env.PLAYWRIGHT_API_BASE_URL ??
    'http://127.0.0.1:8000'
  );
}

const FETCH_TIMEOUT_MS = 5_000;  // per-DELETE timeout — short enough to not hang the suite

export default async function globalTeardown(config: FullConfig): Promise<void> {
  const cleanupDir = path.join(process.cwd(), 'test-results', '.cleanup');
  // Top-level try/catch/finally: ANY unexpected failure (fs unreadable,
  // writeSummary failure, etc.) MUST NOT reject the promise. Playwright
  // treats a rejected globalTeardown as a teardown failure and may alter
  // the exit code — violating the spec's best-effort contract.
  try {
    const { raw, parseFailures } = readCleanupEntriesFromDir(cleanupDir, fs);
    const registered = raw.length;
    const entries = orderEntries(dedupeEntries(raw));
    const registered_deduped = entries.length;
    const apiBaseUrl = resolveApiBaseUrl(config);

    // Empty-registry path: still emit the summary line + write a zero-count
    // artifact so the reporter has consistent evidence that teardown ran.
    if (entries.length === 0) {
      writeSummary({ registered, registered_deduped, attempted: 0,
                     deleted: 0, failed: 0, skipped_404: 0, parse_failures: parseFailures, details: [] });
      console.log(`cleanup: 0 rows deleted across 0 resources; 0 failures`);
      return;
    }

    // Drain. Best-effort; per-row failures logged + counted.
    // Parse-failed registry lines are counted toward `failed` so the reporter's
    // `failed === 0` invariant catches them (cycle-3 finding C3-P2-2). Without
    // this, malformed JSONL lines would silently slip past verification.
    let deleted = 0, failed = parseFailures, skipped_404 = 0;
    const details: Array<{
      resource: ResourceType | 'parse_failure';
      id: string;
      status: number;
      error_type?: 'error' | 'timeout' | 'parse_failure';
    }> = [];
    // Synthetic details entries so the reporter / future tooling can count
    // parse-failures by reading the summary alone.
    for (let i = 0; i < parseFailures; i++) {
      details.push({ resource: 'parse_failure', id: `<malformed-line-${i}>`, status: 0, error_type: 'parse_failure' });
    }
    for (const entry of entries) {
      const url = buildDeleteUrl(apiBaseUrl, entry);
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
      try {
        const resp = await fetch(url, { method: 'DELETE', signal: ctrl.signal });
        // status is always numeric per spec FR-7 cleanup-summary shape (cycle-3 C3-P1-1).
        details.push({ resource: entry.resource, id: entry.id, status: resp.status });
        if (resp.status === 204) deleted += 1;
        else if (resp.status === 404) skipped_404 += 1;
        else { failed += 1; console.warn(`cleanup-teardown: ${url} → ${resp.status}`); }
      } catch (e) {
        failed += 1;
        const error_type: 'timeout' | 'error' = (e as Error).name === 'AbortError' ? 'timeout' : 'error';
        details.push({ resource: entry.resource, id: entry.id, status: 0, error_type });
        console.warn(`cleanup-teardown: ${url} → ${error_type}: ${(e as Error).message}`);
      } finally {
        clearTimeout(timer);
      }
    }

    writeSummary({ registered, registered_deduped, attempted: registered_deduped,
                   deleted, failed, skipped_404, parse_failures: parseFailures, details });
    // Spec FR-7 stdout format: `<N> rows deleted across <M> resources` where M
    // is distinct resource types, not entry count (cycle-3 C3-P1-2).
    const resourceCount = new Set(entries.map((e) => e.resource)).size;
    console.log(`cleanup: ${deleted} rows deleted across ${resourceCount} resources; ${failed} failures, ${skipped_404} already-gone`);
  } catch (e) {
    console.error(`cleanup-teardown: unexpected error — ${(e as Error).message}`);
    // Attempt to write a failure summary so the reporter sees something.
    try {
      writeSummary({ registered: 0, registered_deduped: 0, attempted: 0,
                     deleted: 0, failed: 1, skipped_404: 0, parse_failures: 0,
                     details: [{ resource: 'cluster' as ResourceType, id: '<teardown-crash>', status: 'error' }] });
    } catch { /* swallow */ }
  } finally {
    // ALWAYS remove the .cleanup/ directory, even on unexpected failure.
    try { fs.rmSync(cleanupDir, { recursive: true, force: true }); } catch { /* swallow */ }
  }
}

function writeSummary(summary: object): void {
  const summaryPath = path.join(process.cwd(), 'test-results', 'cleanup-summary.json');
  fs.mkdirSync(path.dirname(summaryPath), { recursive: true });
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
}
```

```typescript
// ui/tests/e2e/cleanup-reporter.ts

import type { Reporter, FullResult } from '@playwright/test/reporter';

class CleanupReporter implements Reporter {
  onEnd(_result: FullResult): void {
    const summaryPath = path.join(process.cwd(), 'test-results', 'cleanup-summary.json');
    if (!fs.existsSync(summaryPath)) {
      console.warn('cleanup-reporter: cleanup-summary.json missing — globalTeardown did not run or write the artifact');
      return;
    }
    const summary = JSON.parse(fs.readFileSync(summaryPath, 'utf8'));
    const invariantOk =
      summary.registered_deduped === summary.attempted &&
      summary.attempted === summary.deleted + summary.failed + summary.skipped_404 &&
      summary.failed === 0;
    if (invariantOk) {
      console.log(`cleanup-reporter: OK — ${summary.deleted} rows deleted, ${summary.skipped_404} already-gone, ${summary.failed} failures`);
    } else {
      console.error('cleanup-reporter: VERIFICATION FAILED', summary);
      fs.writeFileSync(
        path.join(process.cwd(), 'test-results', 'cleanup-verification-failures.txt'),
        JSON.stringify(summary, null, 2),
      );
      // Do NOT throw — v1 is developer-ergonomics gate, not CI-strict.
    }
  }
}

export default CleanupReporter;
```

**UI element inventory**

N/A — no user-facing UI changes. All work is in `ui/tests/e2e/` (test infrastructure).

**State dependency analysis**

N/A — no React state changes.

**Tasks**

1. Add `ResourceType` type + `appendForCleanup()` function to `ui/tests/e2e/helpers/seed.ts`.
2. Wire `appendForCleanup` into all 9 existing `seedXxx()` helpers per the spec §2 inventory table. Particular attention:
   - `seedQuerySet(n, { withJudgmentList: true })`: register cluster + query_set + (conditionally) judgment_list.
   - `seedFullChain`: delegated to sub-helpers — verify each sub-helper registers.
   - `seedAcmeProductsChain`: register cluster + query_set + template + judgment_list + study + (conditional) proposal — currently returns these IDs at lines ~423-434, must add proposal/digest registration if those are created (verify by reading the function fully).
   - `seedStudyCompletedWithDigest`: extract `proposal_id` + `digest_id` + `study_id` from the existing `SeedCompletedStudyResponse` ([`_test.py:100-105`](../../../../backend/app/api/v1/_test.py#L100-L105)) and register all 3 (or all 2 if `with_pending_proposal: false`).
   - `seedStudyCompletedWithPerQueryMetrics`: same as above.
3. Create `ui/tests/e2e/global-setup.ts` — clears `test-results/.cleanup/` directory AND removes stale `test-results/cleanup-summary.json` + `test-results/cleanup-verification-failures.txt` at run start. Use `fs.rmSync(dir, { recursive: true, force: true })` for the directory and `fs.rmSync(file, { force: true })` for the files (force suppresses the not-found error so the call is idempotent against a clean slate).
4. Create `ui/tests/e2e/global-teardown.ts` — full implementation per the spec §FR-7 + key interfaces above.
5. Create `ui/tests/e2e/cleanup-reporter.ts` — Playwright Reporter implementing `onEnd`.
6. Update `ui/playwright.config.ts`:
   - Add `globalSetup: './tests/e2e/global-setup.ts'`.
   - Add `globalTeardown: './tests/e2e/global-teardown.ts'`.
   - Extend `reporter` to include `cleanup-reporter.ts`. Existing pattern: `reporter: process.env.CI ? 'github' : 'list'`. New: `reporter: [process.env.CI ? ['github'] : ['list'], ['./tests/e2e/cleanup-reporter.ts']]`.
7. Add vitest unit tests:
   - `ui/tests/e2e/helpers/__tests__/cleanup-registry.test.ts` — tests for `appendForCleanup` (file write atomicity, JSON-line shape) + `drainAllWorkerJsonl` (parse, dedupe).
   - `ui/tests/e2e/__tests__/global-teardown.test.ts` — tests for the FK-safe drain order with `fetch` mocked + tempdir fixture; asserts the exact call sequence: proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters.
8. **Regenerate `ui/src/lib/types.ts` from live OpenAPI** — this is the **FIRST** task of Story 1.2 (preceding the helper edits): `cd ui && pnpm types:gen`. Precondition: Story 1.1's container rebuild has landed and `curl http://localhost:8000/openapi.json | jq '.paths | keys[] | select(contains("/_test/"))'` lists all 7 test-only paths (1 existing seed-completed + 6 new DELETEs). Sole-ownership boundary: types regen happens here, not in the AI Agent Protocol's catch-all step.
9. Run frontend gates: `pnpm typecheck && pnpm lint && pnpm test && pnpm build`.
10. Run the full Playwright suite locally: `pnpm e2e`. Verify:
    - `test-results/.cleanup/worker-0.jsonl` is populated during the run.
    - `test-results/cleanup-summary.json` is written after the suite.
    - The `cleanup-reporter: OK` line appears in stdout.
    - `test-results/.cleanup/` is removed at exit.
    - `psql -c "SELECT COUNT(*) FROM studies WHERE name LIKE 'e2e-%'"` returns 0 after the run (the assertion from spec §18 DoD).

**Definition of Done**

- [ ] **8 of the 9 `seedXxx()` helpers call `appendForCleanup`** for every resource they directly create. The 9th helper (`seedFullChain`) is a pure delegated wrapper and MUST NOT call `appendForCleanup` itself — its sub-helpers (`seedCluster`, `seedQuerySet`, `seedTemplate`, `seedJudgmentList`) register on its behalf. Per-helper instrumentation table:

| Helper | Registers? | Resources appended |
|---|---|---|
| `seedCluster` | Yes | `cluster` |
| `seedQuerySet` | Yes | `cluster`, `query_set`, optional `judgment_list` |
| `seedTemplate` | Yes | `query_template` |
| `seedJudgmentList` | Yes | `judgment_list` |
| `seedFullChain` | **No** (delegated) | (sub-helpers register) |
| `seedStudy` | Yes | `study` |
| `seedAcmeProductsChain` | Yes | `cluster`, `query_set`, `query_template`, `judgment_list`, `study`, optional `proposal`, optional `digest` |
| `seedStudyCompletedWithDigest` | Yes | `study`, `digest`, optional `proposal` (extracted from `SeedCompletedStudyResponse`) |
| `seedStudyCompletedWithPerQueryMetrics` | Yes | same as `seedStudyCompletedWithDigest` |
- [ ] `test-results/.cleanup/worker-<idx>.jsonl` is created during a Playwright run with one valid JSON-line entry per seeded row.
- [ ] `globalTeardown` reads + drains the registry in FK-safe order (vitest assertion).
- [ ] `cleanup-summary.json` artifact has the required shape (`registered`, `registered_deduped`, `attempted`, `deleted`, `failed`, `skipped_404`, `details`).
- [ ] `cleanup-reporter` invariant assertions pass: `registered_deduped == attempted == deleted + failed + skipped_404` AND `failed == 0`.
- [ ] After a successful suite run, `psql -c "SELECT COUNT(*) FROM clusters WHERE name LIKE 'e2e-%' AND deleted_at IS NULL"` returns 0.
- [ ] After a successful suite run, `psql -c "SELECT COUNT(*) FROM studies WHERE name LIKE 'e2e-%'"` returns 0 (and similarly for query_sets, judgment_lists, query_templates, proposals; digests checked via the study FK predicate from spec §18).
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green.
- [ ] Playwright suite passes — reporter logs `cleanup-reporter: OK`.

---

## UI Guidance

No new user-facing UI elements. All Story 1.2 work lives in `ui/tests/e2e/` test-infrastructure files.

**No legacy behavior parity table — no user-facing component is being deleted or migrated.** Test-infrastructure file edits don't fall under the parity-table requirement.

**No enumerated value contracts to verify** — no new `<select>` options, status badges, or filter chips. The `ResourceType` Literal is internal to the test infrastructure; not sent to the backend as a wire value (it's mapped to URL paths via the `RESOURCE_PATH_MAP` constant before fetch).

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** None new on backend; new frontend vitest cases in `ui/tests/e2e/helpers/__tests__/` and `ui/tests/e2e/__tests__/`.
- **Scope:** Test the cleanup registry + globalTeardown + reporter logic in isolation (mocked `fetch`, tempdir fixture for JSONL files).
- **Tasks:**
  - [ ] `ui/tests/e2e/helpers/__tests__/cleanup-registry.test.ts` (new file): test `appendForCleanup` (creates dir + appends valid JSON-line), `drainAllWorkerJsonl` (parses + dedupes + handles missing/empty files), `RESOURCE_PATH_MAP` exhaustiveness (every key in `ResourceType` has a path). Assigned to Story 1.2 DoD.
  - [ ] `ui/tests/e2e/__tests__/global-teardown.test.ts` (new file): test the FK-safe drain order. Use a `tmp` fixture to stage a `.cleanup/worker-0.jsonl` with mixed-resource entries; mock `fetch` (e.g. via `vi.spyOn(global, 'fetch')`); call the teardown's drain function; assert the fetch call sequence matches `DRAIN_ORDER`. Assigned to Story 1.2 DoD.

### 3.2 Integration tests

- **Location:** `backend/tests/integration/test_test_endpoints.py` (new file).
- **Scope:** DB-backed verification of each new DELETE endpoint per spec §14.
- **Tasks:**
  - [ ] 6 happy-path tests (one per endpoint): seed parent + (where applicable) children → DELETE → assert 204 + row count = 0 + cascade children = 0.
  - [ ] 6 404-on-unknown-id tests (one per endpoint): assert envelope `{detail: {error_code, message, retryable}}` shape with the right `<RESOURCE>_NOT_FOUND` code.
  - [ ] 8 409-on-dependent-row tests:
    - `STUDY_HAS_DEPENDENT_PROPOSAL`: seed study + proposal → DELETE study → 409.
    - `STUDY_HAS_DEPENDENT_DIGEST`: seed study + digest (no proposal) → DELETE study → 409.
    - `JUDGMENT_LIST_HAS_DEPENDENT_STUDY`: seed judgment_list + study referencing it → DELETE judgment_list → 409.
    - `QUERY_SET_HAS_DEPENDENT_STUDY`: seed query_set + study referencing it → DELETE query_set → 409.
    - `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST`: seed query_set + judgment_list referencing it (NO study) → DELETE query_set → 409 with the JUDGMENT_LIST code (not STUDY — verifies independent preflight).
    - `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY`: seed template + study → DELETE template → 409.
    - `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL`: seed two templates `T_delete` and `T_study`; seed a study referencing `T_study` (so no study references `T_delete`); seed a proposal referencing `T_delete` directly (per `proposal.py:49` `study_id` is `nullable=True`, so the proposal can stand alone OR reference the `T_study`-bound study). Assert deleting `T_delete` returns 409 with `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL` (NOT `_STUDY` — proves the STUDY > PROPOSAL > JUDGMENT_LIST priority order falls through to the PROPOSAL preflight when no STUDY dependent exists for the template-under-delete).
    - `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST`: seed template + judgment_list with `current_template_id` set + NO study + NO proposal → DELETE template → 409 with JUDGMENT_LIST code (verifies the STUDY > PROPOSAL > JUDGMENT_LIST priority order falls through correctly).
  - All 20 cases assigned to Story 1.1 DoD.
- **DoD:** Happy path + all 404 paths + all 8 declared 409 codes covered.

### 3.3 Contract tests

- **Location:** `backend/tests/contract/`.
- **Scope:** Hermetic shape + env-guard tests.
- **Tasks:**
  - [ ] Extend `test_test_endpoint_guard.py` with 6 new cases: each new DELETE returns 404 with `RESOURCE_NOT_FOUND` (the env-guard envelope, NOT the `<RESOURCE>_NOT_FOUND` shape) when `Settings.environment != "development"`. Parameterize over endpoint paths to keep the test file tight. Assigned to Story 1.1.
  - [ ] Update `test_openapi_surface.py:EXPECTED_ENDPOINTS` with the 6 new `("delete", "/api/v1/_test/<resource>/{<id>}", "204")` tuples. The 204 tuples are EXEMPTED from the `test_endpoint_response_model_declared` parameterize at lines 155-170 (the existing pattern at line 164: `if status == "204": return`). Assigned to Story 1.1.
  - [ ] Add hermetic source-presence test at `backend/tests/contract/test_test_endpoints_contract.py` (NEW file): read `backend/app/api/v1/_test.py` as a string, assert each of the **11 strictly new** error-code literals appears (`PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `STUDY_NOT_FOUND`, `STUDY_HAS_DEPENDENT_PROPOSAL`, `STUDY_HAS_DEPENDENT_DIGEST`, `JUDGMENT_LIST_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST`, `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY`, `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL`, `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST`). Mirror the precedent at `test_judgments_api_contract.py:test_all_spec_error_codes_referenced_in_router_source`. Protects against accidental rename without going through the integration-test suite. Assigned to Story 1.1.
- **DoD:** Every accepted endpoint change has env-guard + OpenAPI shape coverage. The 11 strictly new error codes are locked at three layers: source-presence (hermetic), env-guard (404 outside dev), and runtime envelope (integration §3.2).

### 3.4 E2E tests

- **Location:** `ui/tests/e2e/`.
- **Scope:** Reporter-based verification (not in-spec assertion). Per spec §14 E2E row, a Playwright spec cannot assert state AFTER `globalTeardown`; instead, `cleanup-reporter.ts` reads `cleanup-summary.json` in its `onEnd` hook and asserts the invariants.
- **Tasks:**
  - [ ] **Helper-coverage audit first**: before relying on "existing specs collectively exercise every helper," run `grep -rn "seedCluster\|seedQuerySet\|seedTemplate\|seedJudgmentList\|seedFullChain\|seedStudy\|seedAcmeProductsChain\|seedStudyCompletedWithDigest\|seedStudyCompletedWithPerQueryMetrics" ui/tests/e2e/*.spec.ts | awk '{print $2}' | sort -u` against the 9 helper inventory. Produce `ui/tests/e2e/helpers/coverage-audit.md` listing which spec covers which helper. Any uncovered helper requires a targeted vitest case (registration-call assertion against a mocked POST) instead of being silently uncovered. Assigned to Story 1.2.
  - [ ] Run the existing Playwright suite (e.g. `studies.spec.ts`, `studies-create-builder.spec.ts`, etc.) and confirm `cleanup-reporter: OK` appears in stdout. The `cleanup-reporter` verifies the outcome.
  - [ ] Manual local verification per Story 1.2 task #10.
- **DoD:** `cleanup-reporter` logs `OK` on a clean run; `test-results/cleanup-verification-failures.txt` is NOT created; `coverage-audit.md` shows ≥1 spec exercising each of the 9 helpers (or a corresponding vitest case if uncovered).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/tests/e2e/helpers/seed.ts` | Every `seedXxx()` helper | 9 helpers | **Modify each** per the per-helper registration obligation in spec §2 — append to JSONL after a successful POST. |
| Every existing `ui/tests/e2e/*.spec.ts` that uses `seedFullChain` / `seedStudy` / etc. | (no code change) | ~10 specs | No code change — they consume the helpers and benefit from cleanup transparently. Verify behavior holistically by running the full suite at the end of Story 1.2. |
| `backend/tests/contract/test_openapi_surface.py` | `EXPECTED_ENDPOINTS` tuple list at lines 37-96 | 1 file | **Add 6 tuples** for the new DELETE endpoints. Assigned to Story 1.1. |
| `backend/tests/contract/test_test_endpoint_guard.py` | Existing env-guard test for seed-completed | 1 file | **Extend with 6 cases**. Assigned to Story 1.1. |
| `backend/tests/integration/test_test_seeding.py` | Existing seed-completed integration | 1 file | No change — the seed-completed endpoint isn't modified. Sibling new file `test_test_endpoints.py` covers the 6 new DELETE endpoints. |
| `ui/src/lib/types.ts` | Generated from OpenAPI | 1 file | **Regenerate** after Story 1.1 ships endpoints — types must include them. |

### 3.6 Migration verification

N/A — no schema changes.

### 3.7 CI gates

- [ ] `make backend-fmt && make backend-lint && make backend-typecheck`
- [ ] `make test-unit` (all existing pass)
- [ ] In-container integration + contract — `docker run --rm --network relyloop_default -v $(pwd):/app -v /app/.venv -w /app ... ghcr.io/astral-sh/uv:python3.13-bookworm bash -c 'uv sync --quiet && uv run pytest backend/tests/integration/test_test_endpoints.py backend/tests/contract/test_test_endpoint_guard.py backend/tests/contract/test_openapi_surface.py'`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- [ ] `pnpm e2e` (full Playwright suite passes locally + smoke job passes in CI).

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update post-merge in Step 8 finalization (add "Most recent meaningful changes" entry; bump 23 → 24 MVP1 features shipped; swap branch + active-feature lines).
- **`architecture.md`** — no change (no new layer; `_test.py` already exists).
- **`CLAUDE.md`** — no change (no new convention; the `/_test/` prefix is already a documented precedent).

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `api-conventions.md` — append "Test-only endpoints" subsection with 11 strictly new error codes per spec §15. Assigned to Story 1.1.

### 4.2 Product docs (`docs/02_product`)

- This spec + plan. No other product doc changes.

### 4.3 Runbooks (`docs/03_runbooks`)

- No new runbook. The cleanup is automatic; failures are visible in stdout.

### 4.4 Security docs (`docs/04_security`)

- No change — test-only endpoints, no new attack surface beyond the existing `seed-completed` precedent.

### 4.5 Quality docs (`docs/05_quality`)

- No change — existing test layers cover the new code.

**Documentation DoD**

- [ ] `state.md` reflects the merged PR (finalization step).
- [ ] `api-conventions.md` carries the 11 strictly new error codes.
- [ ] No other doc touched.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. The feature is additive: 6 new endpoints + 6 new repo functions + new test files + new Playwright config + new helpers. No existing code is restructured.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- N/A.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Story 1.1 endpoints live in api container | Story 1.2 | (in-PR — same branch) | Story 1.2's `globalTeardown` HTTP calls would return 404 from the FastAPI app instead of the env-guard 404 from the route. Order Stories 1.1 → 1.2; rebuild api container between them. |
| Live OpenAPI for `pnpm types:gen` | Story 1.2 task #8 | Requires Story 1.1's restart-api step | If `pnpm types:gen` runs against a stale container, `types.ts` won't include the new endpoints; downstream consumers may fail typecheck. Mitigation: explicit container rebuild in Story 1.1 task #10. |
| GPT-5.5 cross-model review on the implementation | Final PR review | Configured per `.env` | If unavailable, fall back to Opus-only review with explicit log entry per `impl-execute` skill protocol. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `seedAcmeProductsChain` creates a proposal/digest not currently registered | M | M | Story 1.2 task #2 explicitly enumerates the helper and requires registering every returned ID. Read the function fully before editing; verify via inspection of the return type. |
| Pre-existing `e2e-*` rows in operator dev DBs are not cleaned up by the new machinery | M | L | Documented as "One-time legacy cleanup" in spec §16 + PR description; operator runs `make seed-demo FORCE=1` once. |
| `fs.appendFileSync` for sub-PIPE_BUF writes — atomicity claim might not hold on every filesystem | L | L | JSON-line entries are ~80-200 bytes (well under POSIX 4 KiB). For non-POSIX (Windows CI), Playwright's `workers: 1` means there's never concurrent write contention. Document the assumption; if a future PR raises `workers > 1` on Windows, revisit. |
| Existing soft-delete of clusters leaves `deleted_at`-set rows in the table | (locked) | L | Acknowledged in spec §19 decision log. Operator-visible inventory filters `deleted_at IS NULL`; raw `clusters` table count stays positive. Operator can run `psql -c "DELETE FROM clusters WHERE deleted_at IS NOT NULL AND name LIKE 'e2e-%'"` if they want raw-table cleanliness, but this is out of scope for the feature. |
| Playwright `globalTeardown` doesn't run when the operator Ctrl-C's mid-run | (locked) | L | Acknowledged in spec §11. Manual reseed/reset covers the case. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cleanup HTTP call times out | API server slow or unreachable during teardown | Logged + counted as `failed`; teardown continues with next row | Manual `make seed-demo FORCE=1` |
| `cleanup-summary.json` missing | `globalTeardown` failed to run (e.g. crashed before writing) | Reporter logs warning; does NOT alter exit code | Investigate stdout for the crash; manual reseed if needed |
| 409 dependent row encountered during drain | Cleanup script ran out of order (bug in `DRAIN_ORDER`) | Logged + counted; next row attempted | Fix `DRAIN_ORDER` constant; rerun |
| API server down during entire teardown | All 6 endpoint paths fail | All entries counted as `failed`; `failed != 0`; reporter logs `cleanup-reporter: VERIFICATION FAILED` | Manual reseed; investigate API health |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (backend): all 6 endpoints + repo functions + tests + docs. Self-contained; nothing depends on Story 1.2.
2. **Container rebuild** — restart api container so new endpoints are live.
3. **Story 1.2** (frontend): registry + globalSetup/Teardown + reporter + helpers + tests + types regen.

### Parallelization opportunities

- Within Story 1.1, the 6 endpoints can be implemented in parallel by a second developer — they share no state, only a common pattern. The plan keeps them serial for the single-developer flow.
- Story 1.2 sub-tasks (helper edits across 9 helpers) can be batched by helper category (cluster/query_set/template/judgment_list/study → seed-completed composites).

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single. The endpoints are test-only-gated; staging/production return 404 by design. No staged rollout is meaningful.
- **One-time legacy cleanup:** developers with polluted dev DBs should run `make seed-demo FORCE=1` once after pulling this change. Document in the PR body.
- **Feature flag strategy:** None.
- **Migration/cutover steps:** None (no schema changes).
- **Reconciliation/repair strategy:** None.

---

## 9) Execution tracker

### Current sprint

- [x] Story 1.1 — Backend: 6 test-only DELETE endpoints + repo functions + docs
- [x] Story 1.2 — Frontend: cleanup registry + globalSetup/Teardown + reporter

### Blocked items

- None.

### Done this sprint

- (none yet)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match story scope.
- [ ] Endpoint contract implemented exactly as documented (status codes + envelope shapes per spec §7.5 handler pattern).
- [ ] Required tests added/updated for all applicable layers.
- [ ] Commands executed and passed:
    - [ ] `make backend-fmt && make backend-lint && make backend-typecheck`
    - [ ] `make test-unit`
    - [ ] In-container `pytest backend/tests/integration/test_test_endpoints.py backend/tests/contract/test_test_endpoint_guard.py backend/tests/contract/test_openapi_surface.py` (Story 1.1)
    - [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` (Story 1.2)
    - [ ] `pnpm e2e` (full suite passes; `cleanup-reporter: OK` in stdout)
- [ ] Migration round-trip evidence: N/A (no schema changes).
- [ ] `docs/01_architecture/api-conventions.md` updated (Story 1.1).
- [ ] Operator-path verification: curl-smoke each new endpoint once against the live container (Story 1.1).

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:**
   - Spec §7.1 lists 6 endpoints. Plan §1.1 Endpoint table lists 6. ✅ Match.

2. **Spec ↔ plan error code coverage:**
   - Spec §7.5 declares 11 strictly new codes (3 NOT_FOUND + 8 HAS_DEPENDENT) + 3 reused NOT_FOUND + RESOURCE_NOT_FOUND.
   - Plan §3.2 Integration tests has 6 happy paths + 6 404s + 8 409s = 20 cases covering every code. ✅ Match.
   - Plan §3.3 Contract tests covers env-guard `RESOURCE_NOT_FOUND` (6 cases) + OpenAPI shape (6 tuples). ✅

3. **Spec ↔ plan FR coverage:**
   - FR-1 → Story 1.1 ✅
   - FR-2 → Story 1.1 ✅
   - FR-3 → Story 1.1 ✅
   - FR-4 → Story 1.1 ✅
   - FR-5 → Story 1.1 ✅
   - FR-6 → Story 1.1 ✅
   - FR-7 → Story 1.2 ✅
   - All 7 FRs covered.

4. **Story internal consistency:**
   - Story 1.1: Modified files exist (verified: `_test.py`, 6 repo files, `__init__.py`, `api-conventions.md`, 2 contract test files). New `test_test_endpoints.py` is unique to this story. ✅
   - Story 1.2: Modified files exist (`seed.ts`, `playwright.config.ts`). New `global-setup.ts`, `global-teardown.ts`, `cleanup-reporter.ts`, and 2 vitest files unique to this story. ✅
   - No file ownership conflicts.

5. **Test file count and assignment:**
   - Backend integration: 1 new file (`test_test_endpoints.py`) with 20 cases. Assigned to Story 1.1. ✅
   - Backend contract: 2 modified files. Assigned to Story 1.1. ✅
   - Frontend vitest: 2 new files. Assigned to Story 1.2. ✅
   - No orphaned test files.

6. **Gate arithmetic:** Single epic with 2 stories; no phase boundaries. N/A.

7. **Open questions resolved:** Spec §19 has no open questions; all decisions locked. ✅

8. **Frontend UI Guidance section:** Story 1.2 is test-infrastructure only; no user-facing UI elements. The plan-level UI Guidance section explicitly notes "no new UI" and the absence of a Legacy Behavior Parity table is justified (no deleted/migrated component >100 LOC). ✅

9. **Plan ↔ codebase verification:**
   - `backend/app/api/v1/_test.py` exists (verified, `_TEST_PREFIX = "/_test"` confirmed at line 34). ✅
   - `backend/app/db/repo/{proposal,digest,study,judgment_list,query_set,query_template}.py` all exist (verified via earlier grep). ✅
   - `backend/tests/contract/test_test_endpoint_guard.py` exists (verified). ✅
   - `backend/tests/integration/test_test_seeding.py` exists (sibling to new file). ✅
   - `ui/tests/e2e/helpers/seed.ts` exists with 9 helpers (verified). ✅
   - `ui/playwright.config.ts` lacks `globalSetup`/`globalTeardown` today (verified at lines 14-48). ✅
   - FK cascade map (per spec §2) verified: trials/judgments/queries cascade; proposals/digests/studies/judgment_lists/query_sets/query_templates do not. ✅
   - Existing `_err` helper pattern at `studies.py:74-78` confirmed. ✅

10. **Infrastructure path verification:**
    - Migration directory: N/A (no migration).
    - Router registration: confirmed `_test_router` imported at `main.py:37` + mounted at `main.py:174-175` with prefix `/api/v1`. New endpoints inherit the prefix automatically.

11. **Frontend data plumbing verification:**
    - Story 1.2 doesn't add new props or component data flow — all changes are test-infrastructure files. N/A.

12. **Persistence scope consistency:** Per-worker JSONL files in `test-results/.cleanup/` are filesystem-scoped, NOT browser-storage-scoped (no `localStorage` or `sessionStorage` involved). Per-run lifecycle: cleared by `globalSetup` at start, removed by `globalTeardown` at exit. ✅

13. **Enumerated value contract audit:** `ResourceType` Literal in `seed.ts` is an internal type — not a wire value the backend validates. The `RESOURCE_PATH_MAP` constant maps internal names to URL paths. No backend allowlist drift risk. ✅ Skipped — no `<select>` / filter / status badge introduced.

14. **Audit-event coverage:** N/A — pre-MVP2 (audit_log not yet active). Even at MVP2+ these endpoints would not emit audit events (test-only, not tenant-visible). ✅

---

## 12) Definition of plan done

- [ ] Every FR is mapped to stories/tasks/tests/docs updates. ✅
- [ ] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD. ✅
- [ ] Test layers (unit/integration/contract/e2e) are explicitly scoped. ✅
- [ ] Documentation updates across docs/01-05 are planned and owned. ✅
- [ ] Lean refactor scope is "none" with stated reason. ✅
- [ ] Epic gates are measurable. ✅
- [ ] Story-by-Story Verification Gate is included. ✅
- [ ] Plan consistency review (§11) performed with no unresolved findings. ✅
