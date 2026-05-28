# Feature Specification — chore_e2e_test_rows_isolation

**Date:** 2026-05-21
**Status:** Draft
**Owners:** RelyLoop maintainers
**Related docs:**
- [idea.md](idea.md)
- [api-conventions.md](../../../01_architecture/api-conventions.md)
- [data-model.md](../../../01_architecture/data-model.md)
- [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py) — existing test-only endpoint precedent (`POST /api/v1/_test/studies/seed-completed`)
- Shipped: [`2026_05_21_feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — downstream symptom catch (PR #184)
- Sibling planned: [`feat_study_preflight_overlap_probe`](../feat_study_preflight_overlap_probe/idea.md), [`feat_orchestrator_zero_streak_abort`](../feat_orchestrator_zero_streak_abort/idea.md)

**Depends on:** None. Single-phase, single-PR ship. Coordinates with the now-shipped target-mismatch guard but is not blocked by anything in flight.

---

## 1) Purpose

- **Problem:** Playwright E2E seed helpers in [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) create `e2e-cluster-*`, `e2e-qs-*`, `e2e-tmpl-*`, `e2e-jl-*` rows on every run AND **never clean them up**. After every dev-cycle E2E pass, the operator-visible `clusters`, `query_sets`, `query_templates`, `judgment_lists`, `studies`, `proposals`, `digests` tables accumulate test fixtures that surface in the create-study modal's dropdowns. PR #184 (`ce3fcf4`) shipped `feat_study_target_judgment_mismatch_guard` which catches the data-correctness symptom at create time (operator can no longer submit a mismatched-target study), but the operator can still **see** and **try to pick** the polluted rows in the modal. The drive-by `seedJudgmentList` default change in PR #184 (target `'e2e-target'` → `'products'`) made this worse: e2e rows now share target naming with real data, so the operator can no longer eyeball-distinguish test fixtures from real entities.
- **Outcome:** Every Playwright spec that creates rows registers them against a file-based cleanup registry (per-worker JSONL files); a `globalTeardown` hook in `playwright.config.ts` reads + merges + drains the registry in FK-safe order at the end of the run and DELETEs each row via a new set of test-only `/api/v1/_test/*` endpoints. After a successful E2E run, the dev DB returns to its pre-test row inventory. **Behavior on test failure:** Playwright's `globalTeardown` ALWAYS runs (whether the suite passed or failed), so failed-spec rows are also cleaned up — failure-of-assertion doesn't pollute. The only pollution path is a hard interruption (Ctrl-C, OS kill, process crash) before `globalTeardown` fires; in that case rows persist until the operator runs `make reset` or `make seed-demo FORCE=1`. There is no automatic "next run cleans up prior run's leftovers" — the registry is per-run.
- **Non-goal:** Closing the data-correctness gap that PR #184 already closed (the mismatch validator catches the bad submission). This spec is purely about operator-visible UI pollution. Not in scope: a `__test_only` column on every table (Approach B from the idea), a `make purge-test-rows` operator target (Approach C; covered by existing `make reset` + `make seed-demo FORCE=1`), or migrating soft-delete to all entities. Also out of scope: operator-facing public DELETE endpoints (these new endpoints are test-only gated).

## 2) Current state audit

### Existing implementations

- **`ui/tests/e2e/helpers/seed.ts`** — entry point for all Playwright seeding. NINE exported helpers (per `grep -n "^export async function seed" ui/tests/e2e/helpers/seed.ts`):

| # | Helper | Resources it creates | Registration obligation |
|---|---|---|---|
| 1 | `seedCluster()` | 1 cluster | Register `(cluster, cluster.id)` |
| 2 | `seedQuerySet(n, { withJudgmentList })` | 1 cluster + 1 query_set + N queries + (optional) 1 judgment_list | Register `(cluster, ...)`, `(query_set, ...)`, optionally `(judgment_list, ...)`. Queries cascade via FK; do NOT register individually. |
| 3 | `seedTemplate()` | 1 query_template | Register `(query_template, tpl.id)` |
| 4 | `seedJudgmentList({ clusterId, querySetId, queryIds, target })` | 1 judgment_list | Register `(judgment_list, jl.id)` |
| 5 | `seedFullChain(n, { judgmentListTarget })` | cluster + query_set + N queries + template + judgment_list (calls helpers 1-4) | Delegated — sub-helpers register; this wrapper adds nothing |
| 6 | `seedStudy({ ..., target })` | 1 study (with trials cascade) | Register `(study, study.id)`. Trials cascade via FK on study delete. |
| 7 | `seedAcmeProductsChain()` | realistic-naming cluster + query_set + queries + template + judgment_list + study + (optional) proposal | Register each newly created row; the helper currently includes `studyId` in the return — must add `proposalId` / `digestId` to the return + registration if those are created. |
| 8 | `seedStudyCompletedWithDigest({ clusterId, querySetId, templateId, judgmentListId })` | 1 study + 2 trials + 1 digest + (optional) 1 proposal — via `POST /api/v1/_test/studies/seed-completed` | Register `(study, ...)`, `(digest, ...)`, AND `(proposal, ...)` if `withPendingProposal` (the existing `SeedCompletedStudyResponse` at [`_test.py:100-105`](../../../../backend/app/api/v1/_test.py#L100-L105) already returns all 3 IDs — extract them and register). Critical: missing `proposal` / `digest` registration here causes the FR-3 409 path during teardown. |
| 9 | `seedStudyCompletedWithPerQueryMetrics({ ... })` | same as #8 but with `winner_per_query` + `runner_up_per_query` payload | Same as #8 — register study + digest + proposal. |

Every helper creates rows with `randomUUID().slice(0, 8)`-suffixed `e2e-*` names; NONE of them call DELETE on shutdown today. The most recent edits (PR #184) added optional `target` overrides + changed `seedJudgmentList` default to `'products'`.
- **`backend/app/api/v1/_test.py`** — established test-only endpoint precedent. `POST /api/v1/_test/studies/seed-completed` uses `_TEST_PREFIX = "/_test"` + `Depends(_require_development_env)` (which returns 404 outside dev — see lines 37-54). Same pattern is the lock for the 6 new endpoints in this feature.
- **`backend/app/api/v1/clusters.py:280-293`** — existing `DELETE /api/v1/clusters/{cluster_id}` is operator-facing **soft-delete** (sets `deleted_at`; list/detail queries filter by `Cluster.deleted_at.is_(None)`). The cleanup-registry path uses this existing endpoint for cluster cleanup — no new cluster DELETE needed.
- **`backend/app/api/v1/conversations.py:192-211`** — existing operator-facing soft-delete on conversations. Out of scope for this feature (conversations aren't seeded by `seedFullChain`).
- **`backend/app/api/v1/query_sets.py:483`** — existing operator-facing `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` for per-query hard delete. There is **no** full-query-set DELETE today — needs to be added under the test-only prefix (FR-6).
- **FK cascade map** (from `backend/app/db/models/`): `trials → studies` (`ondelete="CASCADE"`), `judgments → judgment_lists` (`ondelete="CASCADE"`), `queries → query_sets` (`ondelete="CASCADE"`). `proposals` and `digests` reference `studies` but **without** cascade — they must be deleted before their parent study. `studies` references `clusters` + `templates` + `query_sets` + `judgment_lists` (all non-nullable, no cascade); `judgment_lists` references `query_sets` + `clusters` + `query_templates` (the last is nullable, no cascade); `query_sets` references `clusters` (no cascade). This dictates the cleanup order: **proposals + digests → studies (cascades trials) → judgment_lists (cascades judgments) → query_sets (cascades queries) → query_templates → clusters (existing soft-delete)**.
- **`ui/playwright.config.ts`** — does NOT currently define `globalTeardown`. The hook must be added by this feature.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | — | — |

No navigation or URL changes. No operator-facing UI changes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/tests/e2e/helpers/seed.ts` | Every `seedXxx()` helper listed in the 9-row inventory above | **9 helpers** | **Modify each** per the per-helper registration obligation in the inventory table — append to `test-results/.cleanup/worker-<idx>.jsonl` after a successful POST. |
| `ui/playwright.config.ts` | (no `globalTeardown` today) | 1 | **Add** `globalTeardown: './tests/e2e/global-teardown.ts'`. |
| `ui/tests/e2e/global-teardown.ts` | (new file) | — | **New** — walks the registry in FK-safe reverse order and calls the new test-only DELETE endpoints. |
| `backend/app/api/v1/_test.py` | Existing `POST /_test/studies/seed-completed` | 1 | **Extend** with 6 new `@router.delete(f"{_TEST_PREFIX}/<resource>/{{id}}")` handlers + their request/response shapes. |
| `backend/tests/contract/test_test_endpoint_guard.py` | Env-guard contract (currently asserts 404 outside `development` for `seed-completed`) | (existing) | **Extend** to assert the same env-guard on each new DELETE endpoint. |
| `backend/tests/integration/test_test_seeding.py` | Integration coverage of `seed-completed` | (existing) | **Add** integration cases per new DELETE endpoint — happy path, cascade-children-deleted, 404 on unknown id. |
| `backend/tests/contract/test_openapi_surface.py` | OpenAPI tuple registry at lines 75-96 | 1 | **Add** 6 new `("delete", "/api/v1/_test/<resource>/{<id>}", "204")` tuples to `EXPECTED_ENDPOINTS`. |

### Existing behaviors affected by scope change

- **`seedFullChain` callers**: Currently every spec that calls `seedFullChain` leaks 5+ rows per invocation. New: rows are tracked and cleaned up on suite teardown. **Decision needed: no** — additive instrumentation; helpers' return types unchanged.
- **`make reset`**: Drops the dev DB and re-seeds via `install.sh` → `make seed-demo --if-empty`. The new cleanup machinery composes cleanly with `make reset`: after a teardown-aware spec run, `make reset` is still the nuclear option. **Decision needed: no**.
- **Failed-spec rows ARE cleaned up**: Playwright's `globalTeardown` runs after the entire suite regardless of pass/fail (verified per [Playwright docs](https://playwright.dev/docs/test-global-setup-teardown)). Assertion failures in specs do NOT preserve rows. Only **hard interruptions** (Ctrl-C, OS kill, process crash before teardown) or API-down teardown failures can leave rows behind, and those are cleaned via `make seed-demo FORCE=1` / `make reset`. **Decision needed: no — locked behavior per FR-7.**

---

## 3) Scope

### In scope

- **(B1) 6 new test-only DELETE endpoints** in `backend/app/api/v1/_test.py`, gated by `Depends(_require_development_env)`:
  - `DELETE /api/v1/_test/proposals/{proposal_id}`
  - `DELETE /api/v1/_test/digests/{digest_id}`
  - `DELETE /api/v1/_test/studies/{study_id}` (cascades trials via existing FK)
  - `DELETE /api/v1/_test/judgment-lists/{judgment_list_id}` (cascades judgments via existing FK)
  - `DELETE /api/v1/_test/query-sets/{query_set_id}` (cascades queries via existing FK)
  - `DELETE /api/v1/_test/query-templates/{template_id}`
- **(B2) New repo functions** in the existing repo modules (`backend/app/db/repo/proposal.py`, `digest.py`, `study.py`, `judgment_list.py`, `query_set.py`, `query_template.py`): one `hard_delete_<resource>(db: AsyncSession, id: str) -> bool` each. Returns `True` if a row was deleted, `False` if no row existed (used by the router to emit 404).
- **(B3) OpenAPI surface tuple registry** — register all 6 new endpoint tuples in `backend/tests/contract/test_openapi_surface.py:EXPECTED_ENDPOINTS`.
- **(F1) Cleanup registry as per-worker JSONL files in `ui/tests/e2e/helpers/seed.ts`.** Playwright runs each spec file in its own worker process — a module-scoped JS `Map` populated in one worker is NOT visible to other workers or to `globalTeardown` (which runs in the orchestrator process). The registry MUST be **file-based**: each worker appends `{"resource": "<r>", "id": "<i>"}\n` JSONL lines to `test-results/.cleanup/worker-<PLAYWRIGHT_WORKER_INDEX>.jsonl`. `registerForCleanup(resource, id)` uses `fs.appendFileSync` (synchronous; atomic at the OS level on POSIX for `<PIPE_BUF`-sized writes). Every existing seed helper calls `registerForCleanup` immediately after a successful create.
- **(F2) `globalTeardown` script** at `ui/tests/e2e/global-teardown.ts` — reads every `test-results/.cleanup/worker-*.jsonl` file, dedupes by `(resource, id)`, drains in FK-safe order (proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters), calls the new test-only DELETE endpoints for the first 6 and the existing operator-facing soft-delete for clusters. Logs the cleanup outcome (`<count> rows deleted, <count> failures`) to stdout for debuggability. Removes the `test-results/.cleanup/` directory at exit. **Does NOT fail the suite on cleanup errors** — cleanup failure is logged but doesn't mask test failures (developer-ergonomics gate). CI can opt into strict cleanup via the `PLAYWRIGHT_CLEANUP_STRICT=1` env var (deferred to a follow-up — out of scope for v1; see §19).
- **(F3) `playwright.config.ts` wiring** — add `globalTeardown: './tests/e2e/global-teardown.ts'` to the config.
- **(T1) Contract tests** in `backend/tests/contract/test_test_endpoint_guard.py` asserting each new DELETE returns 404 outside `ENVIRONMENT=development`.
- **(T2) Integration tests** in `backend/tests/integration/test_test_seeding.py` (rename optional — could be `test_test_endpoints.py` if scope expands beyond seeding) — happy-path DELETE + cascade verification + 404 on unknown id, per endpoint.
- **(T3) Frontend smoke** — extend an existing Playwright spec (or add a tiny dedicated one) to assert the registry was populated + drained after a successful seed call. Not strictly a new spec; one assertion in an existing `seedFullChain`-using spec is sufficient.

### Out of scope

- **Operator-facing public DELETE endpoints** for studies / judgment_lists / query_templates / proposals / digests / query_sets. Approach A explicitly scopes these endpoints to test-only. Operators who want to delete production data go through soft-delete on clusters (which leaves orphan children in the DB — that's a separate operator concern, not this chore's responsibility).
- **`__test_only` column on every table** (Approach B from the idea). 5 migrations + 5 endpoint filters; significantly heavier than the cleanup-registry approach. Rejected per locked Approach A choice.
- **Automatic purge of legacy `e2e-*` rows** that already exist in the dev DB. Operator runs `make seed-demo FORCE=1` (TRUNCATE + reseed) or `make reset` to wipe; the cleanup-registry approach prevents *future* accumulation.
- **CI-side cleanup**: CI uses ephemeral service containers (per [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml)) so accumulation only matters for local dev. The `globalTeardown` still fires in CI but its cleanup is a no-op against a per-job database.
- **Cleanup on Ctrl-C / SIGINT**: Playwright's `globalTeardown` doesn't run on hard interruption. Failed-run rows persist **until the operator runs `make seed-demo FORCE=1` or `make reset`** — there is NO automatic "next successful run cleans up prior interrupted run" because the per-run registry lifecycle (cleared by `globalSetup`) means the next run has no IDs to delete.
- **Soft-delete migration for studies/judgment_lists/etc.**: Out of scope. Hard-delete on test-only endpoints is the right level of complexity.

### API convention check

- **Endpoint prefix convention:** `/api/v1/_test/<resource>` for test-only endpoints, matching the existing precedent at [`backend/app/api/v1/_test.py:34`](../../../../backend/app/api/v1/_test.py#L34) (`_TEST_PREFIX = "/_test"`).
- **Router file:** `backend/app/api/v1/_test.py` (single file; all 6 endpoints + the existing `seed-completed` POST live here).
- **HTTP methods:** `DELETE` for each new endpoint; returns 204 No Content on success, 404 with canonical envelope on missing id or outside-dev env.
- **Non-auth error envelope shape:** `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` per [`_test.py:46-54`](../../../../backend/app/api/v1/_test.py#L46-L54) and the canonical handler at [`backend/app/api/errors.py:102-118`](../../../../backend/app/api/errors.py#L102-L118).
- **Auth error shape:** N/A in MVP1.
- **Test-only gate:** `Depends(_require_development_env)` on every new route — returns 404 `RESOURCE_NOT_FOUND` outside development (NOT 403 — intentional indistinguishability per the existing precedent's docstring).

### Phase boundaries

Single phase. The entire feature ships in one PR. No deferred phases.

## 4) Product principles and constraints

- **Test infrastructure stays out of the operator API**. The 6 new DELETE endpoints are `/_test/*`-prefixed and 404 outside `ENVIRONMENT=development`. Operators must never discover or call them.
- **Cleanup is best-effort, not blocking**. A `globalTeardown` failure must NOT mask a real test failure; the suite exit code is determined by test results, not cleanup outcomes.
- **Cleanup runs in FK-safe order**. Hard-coded in `global-teardown.ts` against the FK map documented in §2 and §9 below. Operations that violate FK ordering MUST surface as a teardown error (logged), not a silent foreign-key constraint failure later.
- **Registry is suite-scoped, not test-scoped**. A `seedFullChain` call in one spec file followed by a study POST in another should result in BOTH being cleaned up — not just the latter. Per-worker JSONL files + `globalTeardown` merging them give cross-worker visibility that an in-memory Map could never provide.
- **Failed-spec rows are cleaned up**. Playwright's `globalTeardown` runs after the entire suite, regardless of whether individual specs passed or failed. Only **hard interruptions** (Ctrl-C, OS kill, process crash) leave rows behind.

### Anti-patterns

- **Do not** add a `__test_only` column to every table. That's Approach B; rejected for migration cost.
- **Do not** expose the new DELETE endpoints as operator-facing public API. They're gated under `/_test/*` for a reason — operators don't need them, and surfacing them encourages misuse.
- **Do not** soft-delete in the test-only endpoints. Soft-delete leaves rows in the DB (just hidden from filtered queries) — that defeats the purpose of cleanup. Hard-delete only.
- **Do not** allow the registry to grow unbounded across runs. The lifecycle is strictly per-run: `globalSetup` clears `test-results/.cleanup/` at run start (so prior interrupted-run JSONL files don't get re-processed) and `globalTeardown` removes the directory at exit. There is no shared state between runs — no in-memory Map, no persistent state in `node_modules`, no dev-server tie-in. Each `pnpm e2e` invocation gets a fresh empty registry.
- **Do not** fail the test suite when cleanup fails. Log the failure, continue. Cleanup is downstream of correctness.
- **Do not** add an "auto-purge `e2e-*` prefix" backend job. Two reasons: (1) cluster-naming convention isn't enforced (operator could legitimately name a real cluster `e2e-something`), and (2) PR #184's drive-by `seedJudgmentList` change broke the convention — e2e rows now share target naming with real data.

## 5) Assumptions and dependencies

- **`Settings.environment` is set to `"development"` on the dev stack.** The test-only gate returns 404 otherwise. Verified at [`backend/app/api/v1/_test.py:46`](../../../../backend/app/api/v1/_test.py#L46). The Compose file sets this via `.env`; CI sets it for the smoke job; staging/prod will explicitly set `staging`/`production`.
- **`POST /api/v1/_test/studies/seed-completed` continues to exist.** This feature extends `_test.py`; it doesn't replace the existing endpoint.
- **Playwright `globalTeardown` runs once per suite invocation**, not per spec. Per [Playwright docs](https://playwright.dev/docs/test-global-setup-teardown). This is the intended cleanup boundary.
- **FK cascades on `trials`, `judgments`, `queries` are stable**. The migrations that established them (per `judgment.py:61`, `query.py:32`, `trial.py:60`) are not in scope here. If a future migration changes cascade behavior, this feature's cleanup order needs revisiting.

## 6) Actors and roles

- **Primary actor:** Playwright E2E test infrastructure (system).
- **Secondary actor:** Backend developer running `pnpm e2e` locally (sees cleanup logs in stdout).
- **Role model:** N/A — single-tenant install, no auth surface.
- **Permission boundaries:** Test-only endpoints are 404 outside `ENVIRONMENT=development`. No other gating.

### Authorization

N/A — single-tenant install, no auth surface (per [`docs/01_architecture/tech-stack.md` "Canonical release matrix"](../../../01_architecture/tech-stack.md)). The environment guard is the sole gate.

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md). Pre-MVP2, mutations do not emit audit events. **And even at MVP2+, these endpoints would not emit audit events** — they're test-only, never accessible outside dev, and their mutations are not tenant-visible.

## 7) Functional requirements

### FR-1: DELETE /api/v1/_test/proposals/{proposal_id}

- Requirement:
  - The system **MUST** hard-delete the proposal row with the given id when called against `ENVIRONMENT=development`.
  - The system **MUST** return HTTP 204 No Content on success (no body).
  - The system **MUST** return HTTP 404 with `error_code = "PROPOSAL_NOT_FOUND"` when the proposal does not exist.
  - The system **MUST** return HTTP 404 with `error_code = "RESOURCE_NOT_FOUND"` (the env-guard envelope, NOT `PROPOSAL_NOT_FOUND`) when `Settings.environment != "development"`.
  - The endpoint **MUST** be gated by `Depends(_require_development_env)`.
- Notes: Proposals have no FK children — hard-delete is direct.

### FR-2: DELETE /api/v1/_test/digests/{digest_id}

- Requirement:
  - The system **MUST** hard-delete the digest row with the given id under the same env gate.
  - Status codes mirror FR-1: 204 / 404 `DIGEST_NOT_FOUND` / 404 `RESOURCE_NOT_FOUND` outside dev.
- Notes: Digests have no FK children. The 1:1 UNIQUE constraint with studies (per [`digest.py:36-39`](../../../../backend/app/db/models/digest.py#L36-L39)) means deletion of a digest before its study is required to allow the study delete to proceed.

### FR-3: DELETE /api/v1/_test/studies/{study_id}

- Requirement:
  - The system **MUST** hard-delete the study row under the env gate.
  - The system **MUST** cascade-delete `trials` rows automatically via the existing `ondelete="CASCADE"` FK at [`trial.py:60`](../../../../backend/app/db/models/trial.py#L60). The handler does NOT need to delete trials manually.
  - The system **MUST** return 409 `STUDY_HAS_DEPENDENT_PROPOSAL` / `STUDY_HAS_DEPENDENT_DIGEST` if a `proposals` or `digests` row still references the study. **Implementation pattern**: pre-flight `SELECT EXISTS` checks for each dependent table BEFORE attempting the DELETE — this is more reliable than catching `IntegrityError` because `IntegrityError` doesn't always carry the FK constraint name in a portable way across psycopg/asyncpg versions. The handler MUST emit the resource-specific 409 code, not a generic one.
  - Status codes: 204 / 404 `STUDY_NOT_FOUND` / 404 `RESOURCE_NOT_FOUND` outside dev / 409 on dependent-row violation.
- Notes: The cleanup registry MUST delete proposals and digests BEFORE studies. The 409 is a safety net — the cleanup script's ordering should make it unreachable in normal flow.

### FR-4: DELETE /api/v1/_test/judgment-lists/{judgment_list_id}

- Requirement:
  - The system **MUST** hard-delete the judgment_list row under the env gate.
  - The system **MUST** cascade-delete `judgments` rows automatically via the existing FK at [`judgment.py:61`](../../../../backend/app/db/models/judgment.py#L61).
  - The system **MUST** return 409 `JUDGMENT_LIST_HAS_DEPENDENT_STUDY` if a `studies` row still references the judgment_list. Same translation pattern as FR-3.
  - Status codes: 204 / 404 `JUDGMENT_LIST_NOT_FOUND` / 404 `RESOURCE_NOT_FOUND` outside dev / 409 on dependent-study violation.

### FR-5: DELETE /api/v1/_test/query-sets/{query_set_id}

- Requirement:
  - The system **MUST** hard-delete the query_set row under the env gate.
  - The system **MUST** cascade-delete `queries` rows automatically via the existing FK at [`query.py:32`](../../../../backend/app/db/models/query.py#L32).
  - The system **MUST** return 409 `QUERY_SET_HAS_DEPENDENT_STUDY` if a `studies` row references the query_set, OR 409 `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST` if a `judgment_lists` row does. Preflight-EXISTS pattern per FR-3.
  - Status codes: 204 / 404 `QUERY_SET_NOT_FOUND` / 404 `RESOURCE_NOT_FOUND` outside dev / 409 on dependents.

### FR-6: DELETE /api/v1/_test/query-templates/{template_id}

- Requirement:
  - The system **MUST** hard-delete the query_template row under the env gate.
  - The system **MUST** return 409 `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY` (if a `studies` row references the template), 409 `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL` (if a `proposals` row does), OR 409 `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST` (if a `judgment_lists.current_template_id` does). Preflight-EXISTS pattern per FR-3. If multiple dependents exist, return the code with the **fixed priority order: STUDY first, then PROPOSAL, then JUDGMENT_LIST** (NOT lexicographic — explicit ordering chosen because operator cleanup-script behavior is more predictable when the resource-most-likely-to-be-orphaned comes first).
  - Status codes: 204 / 404 `TEMPLATE_NOT_FOUND` / 404 `RESOURCE_NOT_FOUND` outside dev / 409 on dependents.

### FR-7: Playwright cleanup registry + globalTeardown

- Requirement:
  - The frontend test infrastructure **MUST** maintain a **file-based** cleanup registry: per-worker JSONL files at `test-results/.cleanup/worker-<PLAYWRIGHT_WORKER_INDEX>.jsonl`. Each line is a complete `{"resource": "<r>", "id": "<i>"}` JSON object. An in-memory JS structure is NOT a contract requirement — workers run in separate processes and any module-scoped state is invisible to `globalTeardown`.
  - Every existing `seedXxx()` helper in `seed.ts` **MUST** call `appendForCleanup(resource: ResourceType, id: string)` after a successful POST, before returning the seed result. The append **MUST** use `fs.appendFileSync` (synchronous; atomic at the OS level on POSIX for sub-PIPE_BUF writes).
  - `playwright.config.ts` **MUST** declare both `globalSetup: './tests/e2e/global-setup.ts'` (clears `test-results/.cleanup/` at run start so stale files from prior interrupted runs don't get re-processed) AND `globalTeardown: './tests/e2e/global-teardown.ts'`.
  - The `global-teardown.ts` script **MUST** read every `test-results/.cleanup/worker-*.jsonl` file, dedupe by `(resource, id)`, then drain in this exact FK-safe order: **proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters**.
  - For each row, the teardown **MUST** map the registry's snake_case resource name to the kebab-case URL path using this **explicit table** (the registry's resource string is NOT directly substitutable into the URL):

    | Registry `resource` | URL path |
    |---|---|
    | `proposal` | `DELETE /api/v1/_test/proposals/{id}` |
    | `digest` | `DELETE /api/v1/_test/digests/{id}` |
    | `study` | `DELETE /api/v1/_test/studies/{id}` |
    | `judgment_list` | `DELETE /api/v1/_test/judgment-lists/{id}` |
    | `query_set` | `DELETE /api/v1/_test/query-sets/{id}` |
    | `query_template` | `DELETE /api/v1/_test/query-templates/{id}` |
    | `cluster` | `DELETE /api/v1/clusters/{id}` (existing operator-facing soft-delete; NOT under `/_test/`) |
  - The teardown **MUST** write a summary JSON artifact at `test-results/cleanup-summary.json` with shape `{"registered": L, "registered_deduped": N, "attempted": N, "deleted": M, "failed": F, "skipped_404": K, "details": [{"resource": ..., "id": ..., "status": <http_code>}]}` — the artifact is the verification handshake for the E2E coverage gate (§14). The reporter's invariant: `registered == registered_deduped + duplicate_appends`, and `attempted == registered_deduped`, and `attempted == deleted + failed + skipped_404`.
  - The teardown **MUST** log a summary line to stdout: `cleanup: <N> rows deleted across <M> resources; <K> failures`.
  - The teardown **MUST** remove the `test-results/.cleanup/` directory at exit (success or failure). Per-run state does NOT persist to the next run.
  - Cleanup failures **MUST NOT** affect the Playwright exit code — the suite's pass/fail signal is determined by test results, not cleanup outcomes (developer-ergonomics gate; can be opt-in tightened via `PLAYWRIGHT_CLEANUP_STRICT=1` in a future v2, deferred per §19).
- Notes: The registry is **per-worker on disk**, merged in the orchestrator process by `globalTeardown`. There is no shared in-memory data structure. Each worker independently appends to its own file; orchestrator merges. Per-run lifecycle: `globalSetup` clears at start → workers append during specs → `globalTeardown` reads + drains + writes summary + removes directory at end.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `DELETE` | `/api/v1/_test/proposals/{proposal_id}` | Hard-delete proposal (test-only, FR-1) | `PROPOSAL_NOT_FOUND` (404), `RESOURCE_NOT_FOUND` (404 — env gate) |
| `DELETE` | `/api/v1/_test/digests/{digest_id}` | Hard-delete digest (test-only, FR-2) | `DIGEST_NOT_FOUND` (404), `RESOURCE_NOT_FOUND` (404 — env gate) |
| `DELETE` | `/api/v1/_test/studies/{study_id}` | Hard-delete study + cascade trials (test-only, FR-3) | `STUDY_NOT_FOUND` (404), `STUDY_HAS_DEPENDENT_PROPOSAL`/`STUDY_HAS_DEPENDENT_DIGEST` (409), `RESOURCE_NOT_FOUND` (404 — env gate) |
| `DELETE` | `/api/v1/_test/judgment-lists/{judgment_list_id}` | Hard-delete judgment_list + cascade judgments (test-only, FR-4) | `JUDGMENT_LIST_NOT_FOUND` (404), `JUDGMENT_LIST_HAS_DEPENDENT_STUDY` (409), `RESOURCE_NOT_FOUND` (404 — env gate) |
| `DELETE` | `/api/v1/_test/query-sets/{query_set_id}` | Hard-delete query_set + cascade queries (test-only, FR-5) | `QUERY_SET_NOT_FOUND` (404), `QUERY_SET_HAS_DEPENDENT_<resource>` (409), `RESOURCE_NOT_FOUND` (404 — env gate) |
| `DELETE` | `/api/v1/_test/query-templates/{template_id}` | Hard-delete query_template (test-only, FR-6) | `TEMPLATE_NOT_FOUND` (404), `QUERY_TEMPLATE_HAS_DEPENDENT_<resource>` (409), `RESOURCE_NOT_FOUND` (404 — env gate) |

### 7.2 Contract rules

- Error body **MUST** include machine-readable `error_code`.
- Status code 204 returned with no body on successful DELETE.
- Env-guard 404 returns `error_code = "RESOURCE_NOT_FOUND"` (intentional indistinguishability from "not registered" per the existing `_test.py:46-54` precedent).
- 409 envelopes returned with `retryable: false` — the cleanup script must fix ordering, not retry.

### 7.3 Response examples

**Success — DELETE /api/v1/_test/studies/{study_id}:** HTTP 204 No Content (no body).

**Failure — DELETE /api/v1/_test/studies/{unknown-id}:** HTTP 404
```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01990000-0000-0000-0000-000000000999 not found",
    "retryable": false
  }
}
```

**Failure — DELETE /api/v1/_test/studies/{id} with dependent proposal:** HTTP 409
```json
{
  "detail": {
    "error_code": "STUDY_HAS_DEPENDENT_PROPOSAL",
    "message": "study has 1 dependent proposal; delete proposal(s) first",
    "retryable": false
  }
}
```

**Failure — DELETE /api/v1/_test/studies/{id} called against staging/production:** HTTP 404
```json
{
  "detail": {
    "error_code": "RESOURCE_NOT_FOUND",
    "message": "Not found",
    "retryable": false
  }
}
```

### 7.4 Enumerated value contracts

No new option lists or dropdowns. The 6 new endpoints accept only a single path parameter (the resource id) — no query params, no body.

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `error_code` (new codes) | `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `STUDY_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `STUDY_HAS_DEPENDENT_PROPOSAL`, `STUDY_HAS_DEPENDENT_DIGEST`, `JUDGMENT_LIST_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_STUDY`, `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST`, `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY`, `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL`, `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST`, `RESOURCE_NOT_FOUND` | `backend/app/api/v1/_test.py` (`_err(...)` invocations) — codes are string literals raised via `HTTPException(detail=...)`. | `ui/tests/e2e/global-teardown.ts` only — none surface in the frontend production code. |

Note: `TEMPLATE_NOT_FOUND` already exists in the studies router (per `studies.py:209-211`) — reuse the same string literal across the codebase for consistency. `JUDGMENT_LIST_NOT_FOUND` and `QUERY_SET_NOT_FOUND` also reuse existing literals (per `studies.py:228-238`).

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `PROPOSAL_NOT_FOUND` | 404 | Proposal id does not exist. `retryable: false`. |
| `DIGEST_NOT_FOUND` | 404 | Digest id does not exist. `retryable: false`. |
| `STUDY_NOT_FOUND` | 404 | Study id does not exist (new — reuse the literal where existing code uses it implicitly). `retryable: false`. |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | Already exists in studies router; reused. |
| `QUERY_SET_NOT_FOUND` | 404 | Already exists in studies router; reused. |
| `TEMPLATE_NOT_FOUND` | 404 | Already exists in studies router; reused. |
| `STUDY_HAS_DEPENDENT_PROPOSAL` | 409 | Cannot delete study — a proposal still references it. Cleanup script must order proposals → studies. `retryable: false`. |
| `STUDY_HAS_DEPENDENT_DIGEST` | 409 | Cannot delete study — a digest still references it. `retryable: false`. |
| `JUDGMENT_LIST_HAS_DEPENDENT_STUDY` | 409 | Cannot delete judgment_list — a study still references it. `retryable: false`. |
| `QUERY_SET_HAS_DEPENDENT_STUDY` | 409 | Cannot delete query_set — a study still references it. `retryable: false`. |
| `QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST` | 409 | Cannot delete query_set — a judgment_list still references it. `retryable: false`. |
| `QUERY_TEMPLATE_HAS_DEPENDENT_STUDY` | 409 | Cannot delete template — a study still references it. `retryable: false`. |
| `QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL` | 409 | Cannot delete template — a proposal still references it. `retryable: false`. |
| `QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST` | 409 | Cannot delete template — a judgment_list still references it (`current_template_id`). `retryable: false`. |
| `RESOURCE_NOT_FOUND` | 404 | Env-guard 404 — returned when `Settings.environment != "development"`. Reused from existing `_test.py:50`. |

**Counts:** 14 NEW codes (6 NOT_FOUND + 8 HAS_DEPENDENT) + 1 REUSED (`RESOURCE_NOT_FOUND`) + 3 codes that already exist in studies router and are REUSED here without modification (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`). Of the 14 new codes, 6 are NOT_FOUND-shaped (one per resource — `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `STUDY_NOT_FOUND`, and the 3 reused; note `JUDGMENT_LIST_NOT_FOUND` / `QUERY_SET_NOT_FOUND` / `TEMPLATE_NOT_FOUND` are NOT new — they're reused). Strictly NEW codes: `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `STUDY_NOT_FOUND` (3) + 8 HAS_DEPENDENT = **11 strictly new** + 3 reused NOT_FOUND + `RESOURCE_NOT_FOUND` reused = 15 total declared.

Register the **11 strictly new codes** in [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) under a new "Test-only endpoints" subsection (or appended to the existing list with a `(test-only)` annotation). The 4 reused codes are already documented (or implicitly documented by the existing studies-router error catalog).

**Handler signature pattern** (FR-1 through FR-6 — all six new DELETE handlers MUST follow this exact shape to guarantee 204-no-body compliance):

```python
@router.delete(
    f"{_TEST_PREFIX}/<resource>/{{<resource>_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["test-only"],
    dependencies=[Depends(_require_development_env)],
)
async def delete_<resource>(
    <resource>_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    # Pre-flight EXISTS checks for each dependent table (per FR-3 pattern).
    # Raise 409 with the resource-specific HAS_DEPENDENT_<X> code if any
    # dependent row exists.
    ...
    deleted = await repo.hard_delete_<resource>(db, <resource>_id)
    if not deleted:
        raise _err(404, "<RESOURCE>_NOT_FOUND", f"<resource> {<resource>_id} not found", False)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

The explicit `response_class=Response` + `return Response(status_code=...)` is what prevents FastAPI from accidentally serializing `null` / `True` / `{}` into the body and breaking the 204 contract.

## 9) Data model and state transitions

### New/changed entities

**No schema changes.** No new tables, no new columns, no new constraints. The existing FK cascade structure handles trials/judgments/queries automatically; the new endpoints just translate FK-constraint violations into structured 409 envelopes.

### Required invariants

- **Cleanup order invariant:** The `global-teardown.ts` script MUST process resources in dependency order: proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters. Out-of-order deletion produces 409 responses; the script SHOULD treat 409 as "skip and continue, log warning" rather than retry.
- **404 consistency:** All 6 new endpoints return the same env-guard 404 (`RESOURCE_NOT_FOUND`) for outside-dev calls — never expose endpoint existence via differing status or envelope shapes.
- **No soft-delete:** Test-only DELETE is hard-delete. Soft-delete is operator-facing (clusters / conversations) and out of scope for test cleanup.

### State transitions

None — the new endpoints transition rows from "exists" to "deleted" (FK-cascade-resolved). No tracked state machine.

### Idempotency/replay behavior

- Calling DELETE on an already-deleted row returns 404 (not idempotent in the 204-vs-204 sense — idempotent in the "no side effect" sense). The cleanup script tolerates 404 as "already gone."

## 10) Security, privacy, and compliance

- **Threats:**
  1. Operator probes `GET /api/v1/_test/studies/{id}` invocation in production. **Mitigation:** the env-guard 404 returns the same envelope as "route not registered" (`RESOURCE_NOT_FOUND`) — calls return the same body shape regardless of whether the route exists. **Important clarification:** the endpoint path itself IS visible in the OpenAPI schema (matches the existing `POST /_test/studies/seed-completed` precedent); only the invocation result is indistinguishable. An attacker downloading `/openapi.json` learns the path. Pre-production deployments SHOULD NOT expose `/openapi.json` to untrusted networks. This is a pre-existing posture, not introduced by this feature.
  2. CI runner with `ENVIRONMENT=development` is exposed to the public internet. **Mitigation:** CI uses ephemeral container-internal networking; the API never reaches the public internet during a test run. Deployment-time enforcement: staging/production MUST set `ENVIRONMENT=staging`/`production`. Pre-launch validation: the existing `test_test_endpoint_guard.py` already asserts this; the new endpoints inherit the same gate.
  3. Test-only endpoints accidentally hit by an operator's `curl` script in their local dev environment. **Mitigation:** the `/_test/` prefix is visually distinct + the endpoints reject calls without a path-based id, so accidental `curl /api/v1/_test/studies` (no id) 405s rather than wiping everything. Operators with dev DB writes are expected to take responsibility — the chore explicitly does NOT add row-level "is this a test row?" guards.
  4. Cleanup script bug registers a real operator-named row's ID and deletes it. **Mitigation:** the registry only registers rows that a `seedXxx()` helper created (registration is in the helpers, not in arbitrary code). A bug in the helper that registers a wrong ID could cause data loss in dev DBs, but the impact is bounded to dev — staging/production return 404 and cannot be affected.
- **Controls:** `Depends(_require_development_env)` on every new endpoint (same pattern as existing `seed-completed`).
- **Secrets/key handling:** N/A.
- **Auditability:** N/A in MVP1 (`audit_log` lands at MVP2). Even at MVP2+, these endpoints would NOT emit audit events — they're test-only and the mutations are not tenant-visible.
- **Data retention/deletion/export impact:** Limited to the dev environment. The endpoints delete rows by ID; the spec relies on the cleanup helpers to only pass IDs of test-created rows. Real operator data in a polluted dev DB COULD be deleted if a registry-handling bug passed the wrong ID — `make seed-demo FORCE=1` restores known-good demo data; no real production data is at risk because the endpoints 404 in staging/production.

## 11) UX flows and edge cases

### Information architecture

No UI changes. No new pages, tabs, sections, or labels.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| (none) | — | — | — |

No tooltip changes. No UI-visible elements added.

### Primary flows

1. **Happy path — Playwright spec runs and cleans up.**
   - Spec calls `seedFullChain()` → 5 rows registered in `cleanupRegistry`.
   - Spec finishes successfully.
   - `globalTeardown.ts` runs after the last spec, drains the registry, logs `cleanup: 5 rows deleted across 5 resources; 0 failures`.
   - Dev DB is back to its pre-test state.

2. **Test failure — rows persist for debugging.**
   - Spec calls `seedFullChain()` + creates a study. 6 rows registered.
   - Spec fails on an assertion.
   - Playwright continues to other specs.
   - `globalTeardown` runs after the last spec — drains the registry as normal. Failed-spec rows are still cleaned up (cleanup is suite-scoped, not per-spec).
   - **Refinement:** if the operator wants failed rows to persist for inspection, they Ctrl-C the run before teardown OR run with `PLAYWRIGHT_NO_CLEANUP=1` (optional env-var escape hatch — out of scope for v1; document as a follow-up if needed).

3. **CI run.**
   - GitHub Actions spawns a per-job database via service containers.
   - `globalTeardown` runs at suite end. The cleanup endpoints fire against the ephemeral DB; the DB is destroyed seconds later regardless.
   - The cleanup is functionally a no-op in CI but exercises the new endpoints (good — keeps the endpoints tested in CI without needing a separate gate).

### Edge/error flows

- **409 dependent row**: cleanup script encounters a 409 → logs warning + skips → continues to next row. The failure is visible in stdout but doesn't crash the teardown.
- **Network failure on cleanup**: the cleanup HTTP call times out. Logged as failure; counter increments; teardown continues. Rows persist in the dev DB until the operator runs `make seed-demo FORCE=1` or `make reset` — there is no automatic next-run rescue (per the locked per-run registry lifecycle).
- **API server down during teardown**: all DELETE calls fail. Logged. Rows persist until manual reseed/reset. Equivalent to a "Ctrl-C before teardown" scenario from the operator's perspective.

## 12) Given/When/Then acceptance criteria

### AC-1: DELETE on existing row returns 204

- Given a study row exists with id `S1`
- When `DELETE /api/v1/_test/studies/S1` is called against `ENVIRONMENT=development`
- Then the response is HTTP 204 with no body
- And the `studies` row with id `S1` no longer exists in the DB
- And all `trials` rows with `study_id = S1` have been cascade-deleted

### AC-2: DELETE on non-existent row returns 404 with specific code

- Given no row exists with id `unknown`
- When `DELETE /api/v1/_test/studies/unknown` is called against `ENVIRONMENT=development`
- Then the response is HTTP 404 with body `{"detail": {"error_code": "STUDY_NOT_FOUND", "message": "study unknown not found", "retryable": false}}`

### AC-3: DELETE outside dev returns env-guard 404

- Given `ENVIRONMENT=staging`
- When `DELETE /api/v1/_test/studies/S1` is called (with or without an existing row)
- Then the response is HTTP 404 with body `{"detail": {"error_code": "RESOURCE_NOT_FOUND", "message": "Not found", "retryable": false}}`
- And no DB rows are affected
- And the response envelope does NOT contain `STUDY_NOT_FOUND` (the env gate fires first, masking row existence)

### AC-4: Dependent row blocks delete with 409

- Given a study `S1` exists with a `proposals` row `P1` referencing it
- When `DELETE /api/v1/_test/studies/S1` is called
- Then the response is HTTP 409 with `error_code = "STUDY_HAS_DEPENDENT_PROPOSAL"`
- And the study row still exists
- And no rows are deleted

### AC-5: Cascade delete on study removes trials

- Given a study `S1` exists with 3 `trials` rows referencing it
- And no `proposals` or `digests` reference the study
- When `DELETE /api/v1/_test/studies/S1` is called
- Then the response is HTTP 204
- And `SELECT COUNT(*) FROM trials WHERE study_id = 'S1'` returns 0

### AC-6: Cascade delete on judgment_list removes judgments

- Given a judgment_list `JL1` exists with 5 `judgments` rows
- And no `studies` reference `JL1`
- When `DELETE /api/v1/_test/judgment-lists/JL1` is called
- Then the response is HTTP 204
- And `SELECT COUNT(*) FROM judgments WHERE judgment_list_id = 'JL1'` returns 0

### AC-7: Cascade delete on query_set removes queries

- Given a query_set `QS1` exists with 4 `queries` rows
- And no `studies` or `judgment_lists` reference `QS1`
- When `DELETE /api/v1/_test/query-sets/QS1` is called
- Then the response is HTTP 204
- And `SELECT COUNT(*) FROM queries WHERE query_set_id = 'QS1'` returns 0

### AC-8: Playwright registry populated by every seed helper

- Given `test-results/.cleanup/worker-<idx>.jsonl` is empty (or absent) at the start of a worker process
- When `seedFullChain(2)` is called from a spec running in that worker
- Then the worker's `.cleanup/worker-<idx>.jsonl` file contains exactly these 4 JSON-line entries (one per row, in any order): `{"resource":"cluster","id":...}`, `{"resource":"query_set","id":...}`, `{"resource":"query_template","id":...}`, `{"resource":"judgment_list","id":...}`
- And every line is independently parseable as a complete JSON object (no concurrent-write tearing)

### AC-9: globalTeardown drains the registry in FK-safe order

- Given the registry contains 5 rows (1 cluster, 1 query_set, 1 template, 1 judgment_list, 1 study)
- When `globalTeardown` runs
- Then DELETE calls fire in this order: study → judgment_list → query_set → query_template → cluster
- And the final stdout line reads `cleanup: 5 rows deleted across 5 resources; 0 failures` (or similar — exact format documented)

### AC-10: Cleanup failure does not affect suite exit code

- Given the registry contains 1 row and the API server is unreachable for the teardown
- When `globalTeardown` runs
- Then the teardown logs a failure line
- And the Playwright exit code is `0` (assuming all tests passed)
- And NOT 1 / NOT propagated upstream

### AC-11: OpenAPI surface includes all 6 new endpoints

- Given the OpenAPI schema has been generated from the live FastAPI app
- When `test_openapi_surface.py` runs
- Then all 6 new `(delete, "/api/v1/_test/<resource>/{id}", "204")` tuples are present in the schema
- And the test passes against the updated `EXPECTED_ENDPOINTS` list

## 13) Non-functional requirements

- **Performance:** Each DELETE is O(1) for the parent row + O(N) for cascade children (FK cascade scans, typically <100 rows per test). Total teardown for a 5-row spec is <1 second.
- **Reliability:** Pure validation + DB write; no external dependencies. Failure modes are constrained to DB unavailability (teardown logs + continues).
- **Operability:** Teardown log line goes to Playwright stdout, visible in `pnpm e2e` output.
- **Accessibility/usability:** N/A — no UI changes.

## 14) Test strategy requirements (spec-level)

| Layer | Required tests |
|---|---|
| Unit (backend) | None — endpoint handlers are thin wrappers around repo functions. The repo functions themselves are covered by integration tests. |
| Integration (backend) | One happy-path test per endpoint (DELETE returns 204 + row is gone + cascade-children gone where applicable). One 404 test per endpoint (unknown id). Cover EVERY declared 409 dependent code: STUDY_HAS_DEPENDENT_PROPOSAL, STUDY_HAS_DEPENDENT_DIGEST, JUDGMENT_LIST_HAS_DEPENDENT_STUDY, QUERY_SET_HAS_DEPENDENT_STUDY, QUERY_SET_HAS_DEPENDENT_JUDGMENT_LIST, QUERY_TEMPLATE_HAS_DEPENDENT_STUDY, QUERY_TEMPLATE_HAS_DEPENDENT_PROPOSAL, QUERY_TEMPLATE_HAS_DEPENDENT_JUDGMENT_LIST = 8 cases. Total: 6 happy paths + 6 404s + 8 409 cases = **20 new integration cases**, in `backend/tests/integration/test_test_endpoints.py` (new file, sibling to `test_test_seeding.py`). |
| Contract (backend) | (1) Extend `test_test_endpoint_guard.py` with 6 new cases asserting each new DELETE returns env-guard 404 with `RESOURCE_NOT_FOUND` outside dev. (2) Add 6 tuples to `test_openapi_surface.py:EXPECTED_ENDPOINTS`. (3) Add a source-presence test asserting each new error code literal exists in `_test.py` (mirroring the studies-router pattern at [`test_studies_api_contract.py:test_studies_router_declares_judgment_mismatch_error_codes`](../../../../backend/tests/contract/test_studies_api_contract.py)). |
| E2E (frontend) | **Reporter-based verification**, not in-spec assertion (a Playwright spec cannot assert state AFTER `globalTeardown` runs). Implementation: (a) `globalTeardown` writes the `test-results/cleanup-summary.json` artifact per FR-7 with explicit `registered` / `registered_deduped` / `attempted` / `deleted` / `failed` / `skipped_404` counts. (b) A new Playwright Reporter at `ui/tests/e2e/cleanup-reporter.ts` reads the summary in its `onEnd` hook (fires AFTER `globalTeardown`) and asserts the file exists + the invariants `registered_deduped == attempted` AND `attempted == deleted + failed + skipped_404` hold + the `failed` count is 0. (c) On any assertion failure, the reporter logs to stdout and writes `test-results/cleanup-verification-failures.txt`. The reporter does NOT alter the Playwright exit code in v1 (developer-ergonomics gate per §16); the file is purely informational for local developers. The release-gate language in §16 reflects this — verification is "manual / local" in v1, not CI-strict. (d) For local verification, a developer can also run `node ui/tests/e2e/cleanup-reporter.ts --check` standalone after a suite run. AC-9 (drain order) is covered at the unit level by mocking `fetch` and asserting DELETE call sequence. |
| Unit (frontend / vitest) | (1) New `ui/tests/e2e/helpers/__tests__/cleanup-registry.test.ts` — test the registry's `appendForCleanup` + `drainAllWorkers` semantics: file write atomicity (each line is a complete JSON object), deduplication by `(resource, id)` after merge, FK-safe drain order. (2) New test of `global-teardown.ts` with `fetch` mocked + a tempdir fixture for worker JSONL files — asserts DELETE call order matches the FK-safe order from FR-7. |

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — append a new "Test-only endpoints" subsection (or extend the existing studies-endpoint code list with `(test-only)` annotations) covering the **11 strictly new error codes** (3 NOT_FOUND for proposal/digest/study + 8 HAS_DEPENDENT codes per §7.5) plus cross-references to the 3 reused NOT_FOUND codes (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`) and `RESOURCE_NOT_FOUND` (already documented).
- `docs/03_runbooks/` — no new runbook needed. The cleanup is automatic; failures are visible in stdout.
- `docs/00_overview/planned_features/chore_e2e_test_rows_isolation/` — this spec.
- `state.md` — updated post-merge in Step 8 finalization.
- `architecture.md` — no change (no new layer; `_test.py` already exists).
- `CLAUDE.md` — no change (no new convention; the `/_test/` prefix is already a precedent).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Backend endpoints ship under the existing `_require_development_env` gate; no operator-visible behavior in any environment.
- **Migration/backfill expectations:** None — no schema changes.
- **One-time legacy cleanup for developers**: developers with polluted dev DBs (existing `e2e-*` rows from prior runs) should run `make seed-demo FORCE=1` (TRUNCATE clusters CASCADE + reseed) OR `make reset` once after pulling this change. The new cleanup machinery only prevents *future* accumulation; it cannot retroactively know about pre-existing leftover rows. This step is documented in the PR description and in §18 DoD.
- **Operational readiness gates:** Existing CI gates (`make lint`, `make typecheck`, `make test-unit`, `make test-integration`, `make test-contract`, `pnpm test`, `pnpm typecheck`, `pnpm build`, Playwright smoke).
- **Release gate:**
  - All 11 ACs pass in CI.
  - `test_openapi_surface.py` updated with 6 new tuples.
  - `test_test_endpoint_guard.py` updated with 6 new env-guard cases.
  - `api-conventions.md` updated with new error codes.
  - The post-teardown verification by the new `cleanup-reporter.ts` Reporter logs "OK" (cleanup-summary.json invariants satisfied) — proves the file-based registry + globalTeardown is actually wired correctly across Playwright worker processes. The reporter does NOT fail the suite if invariants are violated in v1 (developer-ergonomics gate); verification is local/manual. Strict CI-gating is deferred to a follow-up (PLAYWRIGHT_CLEANUP_STRICT=1, see §19).
  - At least 1 cycle of GPT-5.5 cross-model review on the implementation plan and final PR diff.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (DELETE /_test/proposals/{id}) | AC-1, AC-2, AC-3 | Backend story — `_test.py` + `repo/proposal.py.hard_delete_proposal` | `test_test_endpoints.py`, `test_test_endpoint_guard.py`, `test_openapi_surface.py`, `api-conventions.md` |
| FR-2 (DELETE /_test/digests/{id}) | AC-1, AC-2, AC-3 | Backend story — `_test.py` + `repo/digest.py.hard_delete_digest` | same |
| FR-3 (DELETE /_test/studies/{id}) | AC-1, AC-2, AC-3, AC-4, AC-5 | Backend story — `_test.py` + `repo/study.py.hard_delete_study` | same |
| FR-4 (DELETE /_test/judgment-lists/{id}) | AC-1, AC-2, AC-3, AC-4, AC-6 | Backend story — `_test.py` + `repo/judgment_list.py.hard_delete_judgment_list` | same |
| FR-5 (DELETE /_test/query-sets/{id}) | AC-1, AC-2, AC-3, AC-4, AC-7 | Backend story — `_test.py` + `repo/query_set.py.hard_delete_query_set` | same |
| FR-6 (DELETE /_test/query-templates/{id}) | AC-1, AC-2, AC-3, AC-4 | Backend story — `_test.py` + `repo/query_template.py.hard_delete_query_template` | same |
| FR-7 (Playwright registry + teardown) | AC-8, AC-9, AC-10 | Frontend story — `seed.ts` registry + `global-teardown.ts` + `playwright.config.ts` wiring | `cleanup-registry.test.ts` (new), one assertion in existing spec |

## 18) Definition of feature done

- [ ] All 11 ACs pass in CI.
- [ ] Backend unit / integration / contract tests pass.
- [ ] Frontend vitest passes; `pnpm typecheck`, `pnpm lint`, `pnpm build` all green.
- [ ] Playwright E2E suite passes locally AND in CI smoke job.
- [ ] `globalTeardown` log line appears in the Playwright stdout with the expected `<N> rows deleted` count.
- [ ] After a successful local run, `psql -c "SELECT COUNT(*) FROM clusters WHERE name LIKE 'e2e-%' AND deleted_at IS NULL"` returns 0 (the cluster DELETE is soft-delete via the existing operator-facing endpoint, so rows remain in the table with `deleted_at` set; what matters is the operator-visible inventory which already filters `deleted_at IS NULL`). The other 5 entity types are hard-deleted: `psql -c "SELECT COUNT(*) FROM studies WHERE name LIKE 'e2e-%'"` returns 0, and similarly for `query_sets`, `judgment_lists`, `query_templates`, `proposals` (digests have no `name` column — verify via `SELECT COUNT(*) FROM digests WHERE study_id IN (SELECT id FROM studies WHERE name LIKE 'e2e-%')` which should be 0 after cleanup).
- [ ] `docs/01_architecture/api-conventions.md` updated with the **11 strictly new** error codes + cross-references to the 4 reused codes (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `RESOURCE_NOT_FOUND`).
- [ ] PR includes GPT-5.5 final review + Gemini Code Assist adjudication.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

(none — all decisions locked.)

### Decision log

- **2026-05-21** — Approach A (cleanup registry + new test-only DELETE endpoints) is the locked design. Rationale: smallest change; no migrations; reuses the existing `_test.py` precedent; cleanup is per-suite not per-table-column.
- **2026-05-21** — 6 new DELETE endpoints (not 5). Rationale: spec author's pre-spec inventory missed `query-sets` — there's no full-query-set DELETE today; only per-query DELETE via cascade FK.
- **2026-05-21** — All 6 endpoints are `/_test/`-gated, NOT operator-facing. Rationale: operators don't need them (soft-delete on clusters is the operator-facing path); exposing them as public API risks accidental data loss.
- **2026-05-21** — Hard-delete, not soft-delete, on test-only endpoints. Rationale: test rows don't need to survive; soft-delete defeats the cleanup purpose; adds a `deleted_at` column to 5 tables (Approach B's cost).
- **2026-05-21** — 409 envelope for FK violations, not 500. Rationale: dependent-row violation is a caller-side ordering issue (cleanup script ran out of order). The cleanup script needs to react gracefully.
- **2026-05-21** — Env-guard 404 (`RESOURCE_NOT_FOUND`) on outside-dev access, not 403. Rationale: matches the existing `seed-completed` precedent — operators can't distinguish "endpoint not registered" from "endpoint refused."
- **2026-05-21** — `globalTeardown` failure does NOT affect suite exit code. Rationale: test results are the signal; cleanup is hygiene. Coupling them would mask real test failures.
- **2026-05-21** — Registry is module-scoped in `seed.ts`, not Playwright-fixture-scoped. Rationale: rows registered in one spec file should be cleaned up regardless of which spec file last touched them.
- **2026-05-21** — No auto-purge by `e2e-*` prefix on the backend. Rationale: PR #184's drive-by changed `seedJudgmentList` target from `'e2e-target'` to `'products'`, breaking the convention. Names like `e2e-cluster-*` still apply but the bulk-prefix approach is fragile.
- **2026-05-21** — No `PLAYWRIGHT_NO_CLEANUP=1` escape hatch for v1. Rationale: scope creep. If operators need to inspect failed-test rows, they Ctrl-C before teardown OR roll back via `make seed-demo FORCE=1`. If demand emerges, add the env var as a follow-up.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — **File-based registry, not module-scoped Map.** Cycle-1 reviewer (B.1, High) correctly flagged that Playwright workers run in separate processes and a JS `Map` populated in worker A is invisible to `globalTeardown`. The registry MUST be per-worker JSONL files at `test-results/.cleanup/worker-<idx>.jsonl`, drained + merged by `globalTeardown` in the orchestrator process.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — **Failed-spec rows ARE cleaned up.** Playwright's `globalTeardown` runs after the suite regardless of pass/fail. The earlier idea framing "failed runs leave rows for debugging" was wrong — only **hard interruptions** (Ctrl-C, OS kill, crash before teardown) preserve rows. Updated §1 + §11.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — **Preflight `SELECT EXISTS` for FK violations, not `IntegrityError` catch.** Cycle-1 reviewer (A.5) flagged that `IntegrityError` doesn't carry the FK constraint name reliably across psycopg/asyncpg versions. Each handler does pre-flight checks for every dependent table BEFORE attempting the delete; the resource-specific 409 code is emitted directly.
- **2026-05-21 (post-GPT-5.5 cycle 1)** — **Cluster cleanup soft-deletes (existing endpoint) — `deleted_at` rows remain in the table.** Operator-visible inventory already filters by `deleted_at IS NULL` so the dropdown is clean; raw row count in `clusters` does NOT return to 0. Updated DoD SQL to `AND deleted_at IS NULL`.
- **2026-05-21 (post-GPT-5.5 cycle 1, deferred)** — `PLAYWRIGHT_CLEANUP_STRICT=1` for CI is OUT OF SCOPE for v1 (deferred). Cycle-1 reviewer (B.7) flagged that best-effort cleanup can silently regress; the v1 design accepts this for developer ergonomics. If CI starts seeing flake from stale rows, add the strict-mode env var as a follow-up.
