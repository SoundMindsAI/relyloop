# Feature Specification — feat_query_inline_crud

**Date:** 2026-05-13
**Status:** Draft
**Owners:** soundminds.ai (initial maintainer per umbrella spec §29)
**Related docs:**
- [idea.md](idea.md) — origin + preflight notes
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — error envelope + cursor pagination
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) §"queries" — column-level reference
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — extends US-08 (query-set review surface)
- Depends on: [`infra_foundation`](../../../00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md), [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/feature_spec.md), [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/feature_spec.md), [`feat_studies_ui`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/feature_spec.md)

---

## 1) Purpose

- **Problem:** During `feat_studies_ui` Story 2.2, the team discovered the backend exposes only `POST /api/v1/query-sets/{id}/queries` (bulk add) for the `queries` resource — there is no listing, no per-query update, no per-query delete. The UI therefore ships a count + bulk-upload UX on `/query-sets/[id]`; per-query inspection, correction, and deletion are unavailable. Operators who notice a typo or want to drop a malformed query must today delete the entire query set and re-upload — a destructive workaround that loses any associated judgment lists.
- **Outcome:** A relevance engineer on the `/query-sets/[id]` page sees a paginated table of every query in the set with `query_text`, `reference_answer`, `query_metadata`, and a `judgment_count` derived field. They can inline-edit any of the three fields via a row-level `<Popover>` (text fields) or `<Dialog>` (JSONB metadata), and can delete a query via an `<AlertDialog>` confirm. Deletion of a query that already has judgments is blocked by an FK guard returning a 409 with the list of affected judgment lists; the UI surfaces this as a toast linking to the offending list so the operator can delete the parent judgment list first and retry.
- **Non-goal:** No soft-delete on `queries` (no `deleted_at` column added; FK guard is the integrity backstop). No CASCADE on `judgments.query_id` (intentional — we want explicit operator action, not silent rating loss). No bulk-edit / bulk-delete (single-row operations only; bulk uploads remain via the existing POST). No agent-tool exposure (the chat agent does not currently propose query mutations; if that changes, the agent surface calls these new endpoints directly).

## 2) Current state audit

### Existing implementations

| File | What it does | API | Notes |
|---|---|---|---|
| [`backend/app/api/v1/query_sets.py`](../../../../backend/app/api/v1/query_sets.py) | Query-set CRUD + bulk-add queries | `POST /query-sets`, `GET /query-sets`, `GET /query-sets/{id}`, `POST /query-sets/{id}/queries` | 4 endpoints exist today. **No per-query endpoints.** Confirmed by `grep -n "@router\." query_sets.py` returning exactly 4 matches. Cursor + `X-Total-Count` are wired on the LIST-of-query-sets endpoint via `(created_at, id)`-tuple `_encode_cursor` / `_decode_cursor`. **This feature uses a different, simpler cursor for the per-query list** — id-only — because `queries` has no `created_at` column and UUIDv7 already gives lexical time order. New helpers (`_encode_query_cursor` / `_decode_query_cursor`) live alongside the existing ones in the same router file. |
| [`backend/app/db/repo/query.py`](../../../../backend/app/db/repo/query.py) | Query repo functions | — | Today exports `create_query`, `list_queries_for_set` (ordered by `id`), `bulk_create_queries`. **No `get_query`, `update_query`, `delete_query`, `count_queries_for_set`, or `list_queries_for_set` with cursor support.** This feature adds them. |
| [`backend/app/db/repo/query_set.py`](../../../../backend/app/db/repo/query_set.py) | Query-set repo functions | — | `count_queries_in_set` already exists and is reused by `QuerySetDetail` (line 75 of router) — `feature_spec` does NOT add a new count helper; the per-query repo's `count_queries_for_set` is a new function on the query repo with cursor-filter awareness. |
| [`backend/app/db/repo/judgment.py`](../../../../backend/app/db/repo/judgment.py) | Judgment repo functions | — | Has `query_id` references but no `count_and_sample_judgment_refs` helper. This feature adds that single helper, returning the 4-field `JudgmentRefCounts` shape (`judgment_count`, `list_count`, `sample_lists`, `overflow_count`) used to construct the 409 envelope. See FR-5 + §8.5. |
| [`backend/app/db/models/judgment.py`](../../../../backend/app/db/models/judgment.py) lines 64–68 | `judgments.query_id` FK to `queries.id` | — | **No `ondelete="CASCADE"`** — verified by reading the model. This is the integrity hazard: a bare `DELETE FROM queries WHERE id=...` succeeds only if no judgment row references the query, otherwise Postgres raises `ForeignKeyViolation`. The 409 guard converts that into a contract-stable error response. The same FK is asserted in [`migrations/versions/0004_judgments.py:49`](../../../../migrations/versions/0004_judgments.py#L49). |
| [`backend/app/db/models/query.py`](../../../../backend/app/db/models/query.py) | `Query` ORM model | — | Columns: `id` (String(36) PK), `query_set_id` (FK→query_sets ON DELETE CASCADE), `query_text` (Text NOT NULL), `reference_answer` (Text nullable), `query_metadata` (JSONB nullable; DB column name `metadata`). No `created_at`, no `updated_at`, no `deleted_at`, no `version`. **Adding any of these is OUT OF SCOPE** — the FK guard is the integrity surface and ordering by `id` (UUIDv7, time-ordered) is the deterministic pagination order. |
| [`ui/src/app/query-sets/[id]/page.tsx`](../../../../ui/src/app/query-sets/[id]/page.tsx) lines 61–72 | Current detail page | — | Shows the count + an "Add queries" button + a placeholder card pointing at this feature ("Per-query inspection is deferred (see `chore_query_inline_edit_delete`) — use Add queries to bulk-upload JSON or CSV."). This feature replaces that placeholder card with a real `<QueriesTable>`. |
| [`ui/src/lib/api/query-sets.ts`](../../../../ui/src/lib/api/query-sets.ts) | Query-sets TanStack hooks | — | Exports `useQuerySets`, `useQuerySet`, `useCreateQuerySet`, `useAddQueries`. **No per-query hooks.** This feature adds `useQueries(querySetId, filter)`, `useUpdateQuery(querySetId)`, `useDeleteQuery(querySetId)`. Both mutation hooks invalidate the same `['query-sets', querySetId]` key the existing add hook uses, plus the new `['query-sets', querySetId, 'queries']` key. |
| [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) | Canonical wire-value allowlists | — | This feature adds NO new enums. PATCHable field names are validated server-side via `Field(...)` constraints (max-length); the frontend form schema mirrors those constraints. The `chore_query_inline_edit_delete` placeholder card in `page.tsx` line 68 is removed by Story 4.1 below — its bareword reference is the only outstanding cross-feature drift. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| [`ui/src/app/query-sets/[id]/page.tsx:68`](../../../../ui/src/app/query-sets/[id]/page.tsx#L68) | `<code>chore_query_inline_edit_delete</code>` placeholder text | Remove the placeholder card; the queries table replaces it. The `<code>` reference disappears with the surrounding `<Card>`. |
| [`docs/02_product/mvp1-user-stories.md`](../../mvp1-user-stories.md) US-08 (and related) | "view-only list of queries" wording (originally from `feat_studies_ui` spec FR-7) | Append "per-query inline edit + delete via `feat_query_inline_crud`" once this feature ships. No URL change. |

No other links, redirects, or page structure changes — this feature lives entirely within the existing `/query-sets/[id]` route and adds a new section inside it.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/src/components/query-sets/__tests__/add-queries-dialog.test.tsx`](../../../../ui/src/components/query-sets/__tests__/add-queries-dialog.test.tsx) (if present) | Bulk-add UX | n/a | None — bulk-add path is unchanged. |
| [`ui/src/app/query-sets/__tests__/detail.test.tsx`](../../../../ui/src/app/query-sets/__tests__/) (placeholder, if present today) | Placeholder card render | n/a | Update to render the new queries table; remove `chore_query_inline_edit_delete` bareword assertion. |
| [`backend/tests/integration/test_query_sets_router.py`](../../../../backend/tests/integration/test_query_sets_router.py) (if exists) | 4 existing endpoints | n/a | None — the existing tests stay; this feature adds new tests for the new endpoints. |

The test file inventory is verified at implementation time; the spec's claim is the contract — the implementation plan tightens it to exact files.

### Existing behaviors affected by scope change

- **Query-set detail page content:** Current: "Queries — N queries in this set. Per-query inspection is deferred …" placeholder Card. New: real `<QueriesTable>` with paginated rows + inline edit + delete. Decision needed: **no** (the placeholder was always a temporary stop-gap pointing at this feature).
- **Deletion semantics on the `queries` row:** Current: no API path exists; only CASCADE-from-parent-query-set deletes them. New: `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` hard-deletes IF no judgment row references the query; otherwise 409. Decision needed: **no** (locked in the idea — hard delete + FK guard, no `deleted_at` column).
- **Query-update semantics:** Current: no API path exists; queries are write-once via bulk upload. New: `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}` updates `query_text`, `reference_answer`, and/or `query_metadata` (whole-object replace, not deep-merge). Decision needed: **no** (locked in the idea).

---

## 3) Scope

### In scope

- Backend endpoint: `GET /api/v1/query-sets/{set_id}/queries` — cursor-paginated list of per-query rows with derived `judgment_count` per query. `X-Total-Count` header. `?cursor=`, `?limit=`, `?since=iso8601` (filters on synthetic ordering — see §9 "State transitions"). **This is a prerequisite for the UI table; without it the UI cannot render the table.**
- Backend endpoint: `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}` — partial update of `query_text` (Text), `reference_answer` (Text or null), `query_metadata` (JSONB or null). Whole-object replace semantics on `query_metadata` (not deep-merge).
- Backend endpoint: `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` — hard delete, FK-guarded. Returns 204 on success or 409 `QUERY_HAS_JUDGMENTS` with the affected `judgment_list_id`s (and names) listed in the error payload (up to 10, plus an overflow indicator).
- Repo functions: `get_query`, `count_queries_for_set`, `list_queries_for_set_cursor` (cursor + since-filterable), `update_query`, `delete_query` in `backend/app/db/repo/query.py`; `count_and_sample_judgment_refs` in `backend/app/db/repo/judgment.py` (returns the 4-field `JudgmentRefCounts` shape for the 409 envelope).
- Pydantic schemas: `QueryRow`, `QueryListResponse`, `UpdateQueryRequest`, `QueryHasJudgmentsErrorPayload` (the 409 detail shape — see §8.5).
- Frontend: new `<QueriesTable>` component on `/query-sets/[id]`, replacing the placeholder card. Inline edit via `<Popover>` for `query_text` + `reference_answer`; modal `<Dialog>` for `query_metadata` (needs room for JSON). Delete via `<AlertDialog>` confirm. 409 `QUERY_HAS_JUDGMENTS` surfaced as a destructive toast linking to the affected judgment list(s).
- Frontend TanStack hooks: `useQueries(querySetId, filter)`, `useUpdateQuery(querySetId)`, `useDeleteQuery(querySetId)`.
- Tests: contract + integration (FK guard happy/sad paths) + component tests for the inline UI.

### Out of scope

- Soft-delete on `queries` (no `deleted_at`). FK guard is the integrity backstop.
- CASCADE on `judgments.query_id`. Intentional — see §4.
- Bulk edit / bulk delete. Existing bulk-add (`POST /query-sets/{id}/queries`) covers the bulk path; this feature is single-row.
- Agent-tool exposure (chat agent does not propose query mutations).
- Audit-event instrumentation (MVP2 — `audit_log` doesn't exist yet; see §6 "Audit events").
- A separate `judgment_count_per_query` query in the list-judgment-lists endpoint. The per-query `judgment_count` derived field lives on `GET /query-sets/{id}/queries` only — not on the existing `GET /judgment-lists/{id}/judgments`.

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints (verified — `/api/v1/query-sets/...` matches the existing 4 endpoints).
- **Router namespace:** [`backend/app/api/v1/query_sets.py`](../../../../backend/app/api/v1/query_sets.py) — add the 3 new endpoints to this file.
- **HTTP methods:** `GET` for read, `PATCH` for partial update, `DELETE` for hard delete (queries are an append-only-shaped table from the API's perspective — no `deleted_at` column to soft-delete).
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<text>", "retryable": <bool> } }` — verified by reading `_err()` helper at [`query_sets.py:48-52`](../../../../backend/app/api/v1/query_sets.py#L48-L52). The 409 `QUERY_HAS_JUDGMENTS` envelope EXTENDS the detail object with a `judgment_lists` array — see §8.5 for the exact shape and §13 "Operability" for the rationale.
- **Auth error shape:** N/A in MVP1.

### Phase boundaries

Single-phase. The MVP1 deliverable is "operator opens `/query-sets/[id]`, sees the table, edits a query text, deletes a query that has no judgments → 204, attempts to delete a query that has judgments → 409 toast → clicks through to the offending judgment list page." Roughly 13 stories (3 backend epics + 1 frontend epic + 1 docs/CI epic; see the implementation plan).

## 4) Product principles and constraints

- **Hard delete + FK guard, not CASCADE.** Deleting a query that has judgments should be a deliberate, two-step operator action: first remove the judgment list, then remove the query. CASCADE would silently destroy ratings the operator paid OpenAI tokens to generate (or hand-curated). The 409 with a clickable list of affected judgment lists is the friction we want.
- **Whole-object replace on `query_metadata`.** Deep-merge introduces ambiguity (does `null` mean "remove key" or "key is absent"?). The bulk-add path already uses whole-object semantics — this feature matches.
- **Idempotent DELETE; non-idempotent PATCH.** DELETE on a missing query returns 404 (not 204) — operators should see the missing-resource signal. PATCH on a missing query returns 404. There's no concurrent-edit hazard worth optimistic-locking against in MVP1 (single-tenant; concurrent edits to the same query are pathological).
- **The 409 envelope is a contract, not just a message.** The frontend branches on `error_code === "QUERY_HAS_JUDGMENTS"` AND consumes the structured `judgment_lists` array to render clickable links. The shape is locked in §8.5 and must not drift.
- **No new column on `queries`.** Adding `updated_at`, `version`, `deleted_at`, etc. would force a migration of every existing query repo function. Out of scope.
- **The `judgment_count` per-query derived field is a single denormalized SUBQUERY.** Parallels the existing `QuerySetDetail.query_count` pattern (verified at [`query_sets.py:75`](../../../../backend/app/api/v1/query_sets.py#L75)). At MVP1 scale (≤10,000 queries per set typical), N+1 is fine for a single page — but the implementation MUST batch the count into a single GROUP BY over the paginated `queries.id IN (...)` set, not per-row. See §13 "Performance".

### Anti-patterns

- **Do not** add `ondelete="CASCADE"` to `judgments.query_id`. Silent rating loss is the threat we're guarding against. The FK guard is the integrity surface; CASCADE defeats it.
- **Do not** add `deleted_at` to `queries`. Out of scope; FK guard is sufficient. Adding it requires parallel changes to every query-listing repo function (`list_queries_for_set`, `bulk_create_queries`'s name-uniqueness joins) and the run_trial worker that consumes queries — a much bigger change than the feature warrants.
- **Do not** deep-merge `query_metadata` on PATCH. Whole-object replace per §4. Implementation must enumerate the keys via `model_dump(exclude_unset=True)` so the operator can explicitly opt INTO replacing the field (passing `query_metadata: null` removes it; omitting the key leaves it alone).
- **Do not** count judgments per-row with a N+1 SUBQUERY. Use a single GROUP BY (`judgments.query_id IN (...)`) over the paginated `queries.id` set; reshape into a `dict[query_id, count]` in Python, attach to each row.
- **Do not** invent a new error envelope. The 409 `QUERY_HAS_JUDGMENTS` shape extends the existing `_err()` detail object with one extra field (`judgment_lists: list[{id, name}]` + `overflow_count: int`); it does NOT replace the canonical envelope. See §8.5 and the existing `_err()` helper for the convention.
- **Do not** emit `audit_log` rows. MVP1 has no `audit_log` table; emission lands at MVP2 (see §6).
- **Do not** implement running-study protection in MVP1. The risk of an operator PATCHing or DELETEing a query mid-study is real but low-probability in single-tenant MVP1, and the cross-table state check on every PATCH/DELETE adds complexity that doesn't pay for itself yet. Deferred to a future `infra_running_study_protection` chore (idea-file capture in §19).

## 5) Assumptions and dependencies

- **Dependency: `feat_study_lifecycle` (Phase 1 + Phase 2)** — implemented. The `queries`, `judgment_lists`, `judgments` tables exist; the `queries` repo + `query_sets` router exist. This feature only ADDs endpoints + repo functions, does not modify the schema.
  - Status: implemented. PR #25 + PR #18 (Phase 1).
  - Risk if missing: blocker — this feature is not implementable without the parent tables.
- **Dependency: `feat_llm_judgments`** — implemented. The `judgments` child table exists with the `query_id` FK that this feature's DELETE guard reads. PR #35.
  - Risk if missing: the FK guard has nothing to guard against (returns 204 always); the spec degrades to "no guard needed yet, add when judgments ship." Since `feat_llm_judgments` IS shipped, the dependency is met.
- **Dependency: `feat_studies_ui`** — implemented. The `/query-sets/[id]` page exists with the placeholder card this feature replaces. PR #50.
  - Risk if missing: no UI surface to attach the table to.
- **Dependency: `infra_frontend_stack_refresh`** — implemented (Next 16 / React 19 / Tailwind 4 / Vitest 4 / shadcn primitives in `ui/src/components/ui/`). This feature uses `<Popover>`, `<Dialog>`, `<AlertDialog>`, `<Table>`, and `<Form>` from the existing shadcn surface — no new primitives.
  - Risk if missing: stack drift; not applicable since infra_frontend_stack_refresh shipped pre-MVP1.
- **No new external dependencies.** No new Python packages, no new npm packages.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (the same persona that creates query sets, generates judgments, and reviews study results). They review the queries table, correct typos, and remove queries that they don't want in the relevance evaluation.
- **Role model:** N/A — single-tenant, no auth (RelyLoop MVP1).
- **Permission boundaries:** N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. **When MVP2 ships**, this feature MUST emit:

| Endpoint | Event type | Metadata | Visibility |
|---|---|---|---|
| `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}` | `query.updated` | `{query_set_id, query_id, fields_changed: [...]}` (no field VALUES — `query_text` is user content; visibility per `audit_log` constraints) | tenant-visible |
| `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` | `query.deleted` | `{query_set_id, query_id, had_judgments: bool}` | tenant-visible |

Emission must be atomic — `audit_log` INSERT inside the same transaction as the primary mutation, before `db.commit()`. Metadata MUST NOT contain `query_text`, `reference_answer`, or `query_metadata` values themselves (they may contain commercial intent / customer data); only structural facts (which keys changed, whether judgments were present).

## 7) Functional requirements

### FR-1: List per-query rows under a query-set
- The system **MUST** expose `GET /api/v1/query-sets/{set_id}/queries?cursor=&limit=&since=` returning a cursor-paginated list of `QueryRow` items where each row contains `id`, `query_text`, `reference_answer`, `query_metadata`, `judgment_count` (int, derived).
- The system **MUST** order rows by `id ASC` (UUIDv7 → effectively time-ordered, ties broken deterministically by the lexical PK).
- The system **MUST** return 404 `QUERY_SET_NOT_FOUND` if the parent query-set does not exist.
- The system **MUST** set the `X-Total-Count` response header to the total query count in the set (independent of pagination, but respecting `?since=`).
- The system **MUST** compute `judgment_count` via a single GROUP BY (`judgments.query_id IN (<page>)` + count by `query_id`) — not per-row. See §13 "Performance".
- The system **MUST** support `?since=<iso8601>` filtering. Because `queries` has no `created_at` column, the filter applies via the UUIDv7 timestamp encoded in the row `id` (RFC 9562 — first 48 bits are a Unix-ms timestamp). Implementation: at the application layer, the router converts the `since` parameter to a UUIDv7 "lower-bound" id by constructing a UUIDv7-with-zero-randomness at that timestamp (`uuid_utils.UUID` has a `.timestamp` accessor; a UUIDv7 with `ts=since_ms` and zero clock_seq/random sorts lexically below any UUIDv7 minted at-or-after `since_ms`). The WHERE clause then reads `queries.id >= :since_lower_bound_id`. No new column, no application-layer post-filter scan.
- The system **MUST** use an **id-only cursor** (not the `(created_at, id)` cursor used by other endpoints). The cursor encodes only the last `id` from the prior page, base64-encoded for opacity. Decoded form: `{"id": "<uuidv7>"}`. The SQL pagination clause is `WHERE id > :decoded_id ORDER BY id ASC LIMIT :limit`. Rationale: UUIDv7 lexical ordering already supplies a deterministic, time-ordered key — adding a synthetic `created_at` tuple would be redundant and complicate the encode/decode helpers.
- Notes: covers the prerequisite that enabled the placeholder card in `feat_studies_ui` Story 2.2 to ship.

### FR-2: Update a single query
- The system **MUST** expose `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}` accepting a body of `UpdateQueryRequest` with optional fields `query_text`, `reference_answer`, `query_metadata`. Returns the updated `QueryRow` (including the recomputed `judgment_count`).
- The system **MUST** treat missing keys as "no change" and present keys (including null values) as "set this value." `query_metadata: null` removes the metadata; `query_metadata: {...}` REPLACES the whole object (not deep-merge).
- The system **MUST** return 404 `QUERY_SET_NOT_FOUND` if the parent set does not exist, 404 `QUERY_NOT_FOUND` if the query does not exist (or exists in a different set — anti-enumeration: prefer `QUERY_NOT_FOUND` over `QUERY_NOT_IN_SET` to avoid leaking existence of queries across sets).
- The system **MUST** reject `query_text` shorter than 1 character with 422 `VALIDATION_ERROR` (Pydantic `min_length=1`, matches the existing `BulkQueryItem.query_text` constraint at [`schemas.py:285`](../../../../backend/app/api/v1/schemas.py#L285)).
- The system **MUST** reject `query_text` longer than 4000 characters with 422 `VALIDATION_ERROR` (matches existing `max_length=4000`).
- The system **MAY** accept `reference_answer` of any length (the existing schema has no max-length on the column; spec leaves it unbounded for MVP1).
- The system **MUST NOT** require `If-Match` / optimistic concurrency headers (out of scope; single-tenant MVP1 has no concurrent-edit hazard worth designing for).
- The system **MUST** accept an empty PATCH body `{}` as a no-op: returns 200 with the current `QueryRow` (unchanged). Rationale: HTTP PATCH semantics say "apply the provided changes," and an empty change-set is a valid no-op. Forcing 422 on `{}` would surprise CLI / curl users who routinely round-trip resources. Test: AC-28 asserts no DB UPDATE is issued (verified via SQLAlchemy event hook or a no-op test that checks `created_at`/row-version remained unchanged).

### FR-3: Delete a single query (FK-guarded)
- The system **MUST** expose `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` returning 204 No Content on success.
- The system **MUST** return 404 `QUERY_SET_NOT_FOUND` if the parent set does not exist.
- The system **MUST** return 404 `QUERY_NOT_FOUND` if the query does not exist OR exists in a different `query_set_id` than the one named in the URL (anti-enumeration — identical envelope shape to "truly missing", per §10 Threat 2). The lookup is `get_query(query_id)` followed by an explicit `if query is None or query.query_set_id != set_id: → 404 QUERY_NOT_FOUND`.
- The system **MUST** issue the DELETE and, on `IntegrityError` from the FK constraint, rollback the transaction, then SELECT the sample of affected judgment-list refs (up to 10) + total judgment count + total distinct judgment-list count, and return 409 `QUERY_HAS_JUDGMENTS` with the envelope shape defined in §8.5. The `detail.judgment_lists` array enumerates up to N=10 affected lists by `id` + `name`; `detail.overflow_count` is `max(0, total_list_count - 10)`. The `detail.message` includes both the total judgment count and the total distinct list count for operator clarity. Rationale: lock-free, race-safe — a pre-DELETE count would race with concurrent INSERT to `judgments` between the count and the DELETE, so we let Postgres's FK check be the single source of truth.
- The system **MUST** not delete any `judgments` rows. The 409 forces the operator to delete the parent judgment list first (which CASCADEs the `judgments`).
- Notes: covers the FK-guard requirement; the integrity hazard is documented in `idea.md` and reverified at spec time.

### FR-4: Frontend table + inline edit/delete UI
- The system **MUST** render a `<QueriesTable>` component on `/query-sets/[id]` (replacing the existing placeholder card at lines 61-72 of `page.tsx`).
- The table **MUST** show columns: `query_text` (truncated to 100 chars with hover-tooltip for full text), `reference_answer` (truncated to 50 chars, "—" when null), `query_metadata` (a compact "Set" / "—" indicator badge — clicking the row's kebab → "Edit metadata" opens the metadata dialog), `judgment_count`, and a row-actions kebab menu with items **Edit**, **Edit metadata**, **Delete**.
- The system **MUST** use shadcn `<Popover>` for inline edit of `query_text` + `reference_answer` (text fields fit in a row anchor), and a separate `<Dialog>` modal for editing `query_metadata` (JSONB needs the space). Both use `react-hook-form` + zod, matching the existing modal patterns in `ui/src/components/`.
- The system **MUST** use shadcn `<AlertDialog>` for delete confirmation, with the destructive button labeled "Delete query" and a one-line preamble ("This permanently removes the query. Judgments must be removed first.").
- The system **MUST** surface `QUERY_HAS_JUDGMENTS` 409 as a destructive toast with a clickable link to the first affected list's detail page (`/judgments/{id}`). Because the global `MutationCache.onError` in [`ui/src/components/providers/query-provider.tsx`](../../../../ui/src/components/providers/query-provider.tsx) only emits string messages via `toToastMessage(err)`, the `useDeleteQuery` mutation MUST opt out of the global handler for THIS error code only by setting `meta: { suppressGlobalErrorToast: true }` on the mutation AND adding a local `onError` that (a) when `err.errorCode === "QUERY_HAS_JUDGMENTS"` calls `toast.error(...)` with the count + a Sonner `action` slot pointing at `/judgments/{first_id}`, OR (b) for any other error code, calls `toast.error(toToastMessage(err))` to preserve the canonical formatting. This is the documented "modal mutation caller" carve-out at [`query-provider.tsx:14-18`](../../../../ui/src/components/providers/query-provider.tsx#L14-L18). The toast text reads "N judgment lists reference this query. Open <first name> →". The full list is NOT enumerated in the toast (UI noise); operators discover the rest by navigating to the first list and following the judgment-list-detail UX.
- The system **MUST** paginate via the existing `<CursorPaginator>` primitive (50/page default, page-size selector with [10, 25, 50, 100]).

### FR-5: Repo + service layer additions
- The system **MUST** add `get_query(db, query_id) → Query | None` to [`backend/app/db/repo/query.py`](../../../../backend/app/db/repo/query.py).
- The system **MUST** add `count_queries_for_set(db, query_set_id, since=None) → int` to the same file.
- The system **MUST** add `list_queries_for_set_cursor(db, query_set_id, after_id=None, limit=50, since_lower_bound_id=None) → list[Query]` returning rows ordered by `id ASC` with `WHERE id > :after_id` (when set) AND `WHERE id >= :since_lower_bound_id` (when set). Both bounds are plain UUIDv7 strings — there is no tuple, no `ts` field, no JSON sub-structure.
- The system **MUST** add `update_query(db, query_id, *, fields_set: dict) → Query` applying ONLY the keys present in `fields_set` (mirroring the API's `model_dump(exclude_unset=True)` contract).
- The system **MUST** add `delete_query(db, query_id) → None` that issues the raw DELETE; the router catches `IntegrityError` and translates to 409.
- The system **MUST** add `count_and_sample_judgment_refs(db, query_id, sample_limit=10) → JudgmentRefCounts` returning a dataclass / pydantic shape with: `judgment_count` (int, total `judgments` rows referencing this query), `list_count` (int, count of distinct `judgment_list_id`s), `sample_lists` (list of up to `sample_limit` `{id, name}` entries — alphabetised by `name` for stable display), `overflow_count` (int, `max(0, list_count - sample_limit)`). The router uses ALL four fields to construct the 409 envelope: `judgment_count` + `list_count` feed `detail.message`, `sample_lists` feeds `detail.judgment_lists`, and `overflow_count` feeds `detail.overflow_count`. **Implementation: two SQL statements** in the same transaction (the helper is read-only and the rollback already happened when the FK `IntegrityError` fired) — (1) an aggregate `SELECT COUNT(*) AS judgment_count, COUNT(DISTINCT judgment_list_id) AS list_count FROM judgments WHERE query_id = :id` to get the two totals; (2) a sample `SELECT j.judgment_list_id, l.name FROM judgments j JOIN judgment_lists l ON l.id = j.judgment_list_id WHERE j.query_id = :id GROUP BY j.judgment_list_id, l.name ORDER BY l.name LIMIT :sample_limit` to fetch the alphabetically-first names. Two queries are simpler than a single window-function CTE and both are sub-100ms against the indexed `judgments_list_query_idx`. The helper is NOT called on the happy path (only after FK failure), so the two-query cost is paid only when the operator actually hit a 409.
- All repo functions follow the existing pattern: accept `db: AsyncSession` first, call `db.flush()` for staging, caller commits.
- Export all new functions via [`backend/app/db/repo/__init__.py`](../../../../backend/app/db/repo/__init__.py) `__all__`.

### FR-6: Frontend TanStack hooks
- The system **MUST** add `useQueries(querySetId: string, filter: QueriesFilter = {})` returning paginated `QueriesPage` (mirror the `useQuerySets` shape with `totalCount` from `X-Total-Count`).
- The system **MUST** add `useUpdateQuery(querySetId: string)` returning a mutation that invalidates `['query-sets', querySetId, 'queries']` and `['query-sets', querySetId]` on success.
- The system **MUST** add `useDeleteQuery(querySetId: string)` returning a mutation that invalidates the same keys.
- `useUpdateQuery` **MUST NOT** add its own `onError` toast handler — the global `MutationCache.onError` already toasts via `toToastMessage(err)`. The chore_cluster_delete_ui (PR #87) Gemini rejection is the precedent.
- `useDeleteQuery` is the **single carve-out** — see FR-4 above. It sets `meta: { suppressGlobalErrorToast: true }` AND adds a local `onError` because the 409 `QUERY_HAS_JUDGMENTS` toast must render an action link. Non-409 errors from this mutation still need to be toasted by the local handler (no falling back to the global, since suppression is mutation-wide). The local handler MUST call `toast.error(toToastMessage(err))` for any non-`QUERY_HAS_JUDGMENTS` error code so behavior matches the global handler.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/query-sets/{set_id}/queries` | List per-query rows with `judgment_count` derived | `QUERY_SET_NOT_FOUND` (404), `VALIDATION_ERROR` (422 — bad cursor / limit out of range) |
| `PATCH` | `/api/v1/query-sets/{set_id}/queries/{query_id}` | Partial update of `query_text`, `reference_answer`, `query_metadata` | `QUERY_SET_NOT_FOUND` (404), `QUERY_NOT_FOUND` (404), `VALIDATION_ERROR` (422) |
| `DELETE` | `/api/v1/query-sets/{set_id}/queries/{query_id}` | Hard-delete; FK-guarded | `QUERY_SET_NOT_FOUND` (404), `QUERY_NOT_FOUND` (404), `QUERY_HAS_JUDGMENTS` (409) |

All routes live in [`backend/app/api/v1/query_sets.py`](../../../../backend/app/api/v1/query_sets.py).

### 8.2 Contract rules
- Error body MUST include machine-readable `error_code` per [`api-conventions.md`](../../../01_architecture/api-conventions.md).
- Status codes MUST be deterministic per scenario (no `200 OK` with body-encoded error).
- The 409 envelope is documented in §8.5 and locked — frontend branches on the structure.

### 8.3 Response examples

**`GET /api/v1/query-sets/{set_id}/queries` success (200):**

```json
{
  "data": [
    {
      "id": "01935b9a-0000-7000-8000-000000000001",
      "query_text": "wireless noise-canceling headphones",
      "reference_answer": null,
      "query_metadata": {"intent": "commercial"},
      "judgment_count": 12
    },
    {
      "id": "01935b9a-0000-7000-8000-000000000002",
      "query_text": "running shoes for flat feet",
      "reference_answer": "Brooks Beast",
      "query_metadata": null,
      "judgment_count": 0
    }
  ],
  "next_cursor": "eyJpZCI6IjAxOTM1YjlhLTAwMDAtNzAwMC04MDAwLTAwMDAwMDAwMDAwMiJ9",
  "has_more": true
}
```

Response header: `X-Total-Count: 248`

**`PATCH /api/v1/query-sets/{set_id}/queries/{query_id}` success (200):**

```json
{
  "id": "01935b9a-0000-7000-8000-000000000001",
  "query_text": "wireless noise-canceling headphones, over-ear",
  "reference_answer": null,
  "query_metadata": {"intent": "commercial"},
  "judgment_count": 12
}
```

**`DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` success (204):** empty body.

**Non-auth failure example — 404 `QUERY_NOT_FOUND`:**

```json
{
  "detail": {
    "error_code": "QUERY_NOT_FOUND",
    "message": "query 01935b9a-0000-7000-8000-000000000001 not found",
    "retryable": false
  }
}
```

**Non-auth failure example — 409 `QUERY_HAS_JUDGMENTS` (the structured envelope locked in §8.5):**

The envelope is constructed from the four-field return of `count_and_sample_judgment_refs(query_id, sample_limit=10)` — `judgment_count` and `list_count` populate `detail.message`; `sample_lists` populates `detail.judgment_lists`; `overflow_count` populates `detail.overflow_count`.

```json
{
  "detail": {
    "error_code": "QUERY_HAS_JUDGMENTS",
    "message": "query 01935b9a-0000-7000-8000-000000000001 has 12 judgments across 2 judgment lists; remove the parent judgment list(s) first",
    "retryable": false,
    "judgment_lists": [
      {"id": "01935b9b-0000-7000-8000-000000000010", "name": "esci-tutorial-v1"},
      {"id": "01935b9c-0000-7000-8000-000000000020", "name": "esci-tutorial-v2"}
    ],
    "overflow_count": 0
  }
}
```

When more than 10 judgment lists reference the query (e.g., total `list_count = 15`):

```json
{
  "detail": {
    "error_code": "QUERY_HAS_JUDGMENTS",
    "message": "query <id> has 120 judgments across 15 judgment lists (showing first 10); remove the parent judgment list(s) first",
    "retryable": false,
    "judgment_lists": [/* exactly 10 {id, name} entries */],
    "overflow_count": 5
  }
}
```

**Auth failure example:** N/A in MVP1.

### 8.4 Enumerated value contracts

This feature does NOT add or modify any allowlists. The PATCH body uses Pydantic `Field(...)` constraints for length checks; there are no enums, no status badges, no filter dropdowns with discrete values flowing to the backend. The frontend's table page-size selector reuses the existing `[10, 25, 50, 100]` array from `<CursorPaginator>` (cosmetic only — the backend's `limit` validation is `ge=1, le=200`).

The only allowlist-relevant decision is the **PATCH-able field set**, which is hardcoded in the Pydantic model `UpdateQueryRequest` (`query_text`, `reference_answer`, `query_metadata`); attempts to PATCH other fields (`id`, `query_set_id`, etc.) are rejected by Pydantic as `VALIDATION_ERROR` because `model_config = ConfigDict(extra="forbid")` is enforced in `UpdateQueryRequest` (see §9 "New/changed entities").

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `QUERY_SET_NOT_FOUND` | 404 | Parent query-set `{set_id}` does not exist. **Reused from existing router** — verified at [`query_sets.py:174`](../../../../backend/app/api/v1/query_sets.py#L174) (already shipped). |
| `QUERY_NOT_FOUND` | 404 | The query `{query_id}` does not exist (anywhere). Anti-enumeration: a query that exists in a different set returns the same shape as a genuinely missing query. |
| `QUERY_HAS_JUDGMENTS` | 409 | Delete blocked because the query is referenced by 1+ `judgments` rows. The detail object extends the canonical envelope with `judgment_lists: list[{id, name}]` (up to 10) + `overflow_count: int`. Locked in §8.3 above. Frontend branches on `error_code === "QUERY_HAS_JUDGMENTS"` AND consumes `judgment_lists` directly — the shape is the contract. |
| `VALIDATION_ERROR` | 422 | Standard — request body failed Pydantic validation. Per `api-conventions.md`. |

No new global error codes; only 2 feature-specific ones (`QUERY_NOT_FOUND`, `QUERY_HAS_JUDGMENTS`).

## 9) Data model and state transitions

### New/changed entities

**No migrations.** This feature adds zero columns. The existing `queries` table and the existing `judgments.query_id` FK are sufficient.

For reference, the relevant existing column-level shape (verified from [`backend/app/db/models/query.py`](../../../../backend/app/db/models/query.py)):

```
queries
  id              VARCHAR(36) PRIMARY KEY              -- UUIDv7
  query_set_id    VARCHAR(36) NOT NULL                 -- FK → query_sets.id ON DELETE CASCADE
  query_text      TEXT NOT NULL
  reference_answer TEXT NULL
  metadata        JSONB NULL                           -- ORM attribute is `query_metadata`
```

And the FK that powers the guard:

```
judgments
  ...
  query_id        VARCHAR(36) NOT NULL                 -- FK → queries.id (NO CASCADE — intentional)
  ...
```

**Pydantic models (new):**

```python
class QueryRow(BaseModel):
    """GET /query-sets/{set_id}/queries item (and PATCH response)."""
    id: str
    query_text: str
    reference_answer: str | None
    query_metadata: dict[str, Any] | None
    judgment_count: int


class QueryListResponse(BaseModel):
    """GET /query-sets/{set_id}/queries response."""
    data: list[QueryRow]
    next_cursor: str | None
    has_more: bool


class UpdateQueryRequest(BaseModel):
    """PATCH /query-sets/{set_id}/queries/{query_id} body. Whole-object replace
    on query_metadata; explicit null removes a nullable field; omitted key = no
    change. `query_text` is NOT NULL on the underlying table so a body of
    `{"query_text": null}` MUST be rejected as 422 (a `@model_validator` runs
    the check because Pydantic's type-only `str` would also reject "field
    absent")."""
    model_config = ConfigDict(extra="forbid")
    query_text: str | None = Field(default=None, min_length=1, max_length=4000)
    reference_answer: str | None = None  # explicit None semantically "set to NULL"
    query_metadata: dict[str, Any] | None = None  # whole-object replace on PATCH

    @model_validator(mode="after")
    def _reject_explicit_null_query_text(self) -> "UpdateQueryRequest":
        # `queries.query_text` is NOT NULL — explicit null is a 422, not a SQL error.
        if "query_text" in self.model_fields_set and self.query_text is None:
            raise ValueError("query_text cannot be null (column is NOT NULL)")
        return self


class JudgmentListRef(BaseModel):
    """One entry in the QUERY_HAS_JUDGMENTS error payload."""
    id: str
    name: str


class QueryHasJudgmentsDetail(BaseModel):
    """The `detail` object of a 409 QUERY_HAS_JUDGMENTS response.

    Extends the canonical `{error_code, message, retryable}` envelope with two
    structured fields the frontend consumes directly (judgment_lists +
    overflow_count). Wired into the FastAPI route's `responses={409: {"model":
    QueryHasJudgmentsEnvelope}}` so the OpenAPI schema documents the contract.
    """
    error_code: Literal["QUERY_HAS_JUDGMENTS"]
    message: str
    retryable: Literal[False]
    judgment_lists: list[JudgmentListRef]  # up to 10 entries, alphabetical
    overflow_count: int  # max(0, total_list_count - 10)


class QueryHasJudgmentsEnvelope(BaseModel):
    """Top-level 409 wrapper (FastAPI nests under `detail` for HTTPException)."""
    detail: QueryHasJudgmentsDetail
```

The router MUST declare:

- `response_model=QueryListResponse` on `GET /api/v1/query-sets/{set_id}/queries`
- `response_model=QueryRow` on `PATCH /api/v1/query-sets/{set_id}/queries/{query_id}`
- `responses={409: {"model": QueryHasJudgmentsEnvelope}}` on `DELETE /api/v1/query-sets/{set_id}/queries/{query_id}` (the 204 success has no body, and `status_code=status.HTTP_204_NO_CONTENT` is set on the decorator)

The contract test `test_query_sets_api_contract.py` MUST assert the OpenAPI schema exposes all three of: (a) `QueryListResponse` as the GET 200 schema, (b) `QueryRow` as the PATCH 200 schema, (c) `QueryHasJudgmentsEnvelope` as the DELETE 409 schema with `judgment_lists` (array of `JudgmentListRef`) and `overflow_count` (integer) fields present.

Note: distinguishing "field absent (no change)" from "field present and null (remove)" requires `model_fields_set` or `model_dump(exclude_unset=True)`. The router MUST use `body.model_dump(exclude_unset=True)` and pass the resulting dict to `repo.update_query`. Setting `reference_answer: null` in the request body must propagate to a NULL UPDATE; omitting `reference_answer` must leave the existing value untouched.

### Required invariants

- **Invariant 1: No CASCADE on `judgments.query_id`.** Already true at the DB level (verified [`backend/app/db/models/judgment.py:64-68`](../../../../backend/app/db/models/judgment.py#L64-L68) — `ForeignKey("queries.id")` with NO `ondelete=` arg). This feature MUST NOT change it.
- **Invariant 2: Hard delete is atomic.** The 409 path must not partially-delete the query and leave orphan rows. Implementation: catch `IntegrityError` after the DELETE statement, rollback the transaction, then SELECT the sample of affected `judgment_lists` for the response. Test: integration assertion that on 409 the query row still exists post-rollback.
- **Invariant 3: PATCH preserves omitted keys.** A PATCH with body `{"query_text": "x"}` must NOT touch `reference_answer` or `query_metadata`. Test: integration assertion that pre/post non-PATCHed fields are bitwise equal.
- **Invariant 4: `judgment_count` is recomputed on PATCH response.** Even though PATCH does not change `judgments`, the response includes `judgment_count` for symmetry with the GET row shape — the frontend reuses the same `QueryRow` type. Implementation: after UPDATE, re-run the count subquery for the single query.
- **Invariant 5: List ordering is deterministic.** `ORDER BY id ASC` (UUIDv7 → time-ordered) means two pages of size 50 + a third query never accidentally shuffles rows. Test: integration assertion that two consecutive list calls return the same order.

### State transitions

The `queries` row itself has no status — it's a leaf record. The state transitions are at the FK-graph level:

- `query` exists with `judgment_count = 0` → DELETE allowed → 204.
- `query` exists with `judgment_count > 0` → DELETE blocked → 409 `QUERY_HAS_JUDGMENTS`.
- `query` exists, no PATCH → state unchanged.
- `query` exists, PATCH → fields updated; `judgment_count` unchanged (PATCH does not touch `judgments`).
- `query` does not exist → all per-query routes return 404.

No state machine; no idempotency complications beyond standard HTTP semantics.

### Idempotency/replay behavior

- **GET** is idempotent by definition.
- **PATCH** is non-idempotent (consecutive calls with `{"query_text": "x"}` then `{"query_text": "y"}` change state); MVP1 does not require `Idempotency-Key` header per [`api-conventions.md` §"Idempotency"](../../../01_architecture/api-conventions.md). Concurrent PATCHes are best-effort last-writer-wins; no optimistic-lock header.
- **DELETE** is idempotent in HTTP semantics ONLY if we returned 204 for a missing query. We chose 404 instead (see §4 "PATCH semantics"). Consecutive DELETE calls: first 204, second 404 (`QUERY_NOT_FOUND`). This is a deliberate trade-off — frontend treats the second 404 as "already deleted" and clears the row from the table.

## 10) Security, privacy, and compliance

- **Threat 1 — Silent rating loss via CASCADE.** Mitigation: no CASCADE; explicit FK guard with 409. Test: integration assertion that DELETE on a query with judgments fails AND the query row still exists post-rollback.
- **Threat 2 — Cross-set query enumeration.** A query exists in set A; an attacker calls `GET /query-sets/B/queries/<query_id_in_A>`. Mitigation: PATCH/DELETE both treat "query exists in different set" as `QUERY_NOT_FOUND` (same shape as genuinely missing). Test: contract assertion that PATCH/DELETE on a query whose `query_set_id` ≠ `{set_id}` in the URL returns 404 with `error_code=QUERY_NOT_FOUND`.
- **Threat 3 — Customer content in `query_text` / `reference_answer` leaking via audit-log metadata (MVP2).** Mitigation: §6 "Audit events" — metadata MUST NOT include the field VALUES, only structural facts (`fields_changed: [...]`, `had_judgments: bool`). This rule is enforced by the spec; MVP2's audit_log infra will reject violators.
- **Threat 4 — Concurrent DELETE during judgment-list creation race.** A delete check passes (judgment_count = 0), the operator confirms, the DELETE issues — but between check and delete, a concurrent judgment-generation worker inserts judgments. Mitigation: rely on the FK `IntegrityError` to catch the race (Postgres FK check happens during the DELETE statement, not at our application count). Test: integration with `asyncio.gather(delete_query, generate_judgments)` followed by an assertion that EITHER the delete succeeded and judgments were never inserted, OR the delete returned 409 and the judgments exist.
- **Threat 5 — Toast message includes user-content judgment-list names.** Risk: a malicious operator names a judgment list `<script>alert('xss')</script>`. Mitigation: the frontend toast renderer is React (text-content rendering by default); React escapes HTML. Test: component test confirming the toast renders the `name` string verbatim without HTML interpretation.
- **Secrets/key handling:** none introduced. No new secrets.
- **Auditability:** N/A at MVP1; see §6 for MVP2 audit-event matrix.
- **Data retention/deletion/export impact:** Hard-delete on `queries` is irreversible (no `deleted_at` column). The operator must back up the query-set before destructive operations if they need recovery. This is documented in the feature's docs/03_runbooks update (see §15).

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** `/query-sets/[id]` detail page. The queries table sits between the page header (name + cluster + count + "Add queries" button) and the "Associated judgment lists" section. The placeholder card at [`page.tsx:61-72`](../../../../ui/src/app/query-sets/[id]/page.tsx#L61-L72) is REPLACED by the new `<QueriesTable>` component. No new routes, no nav-tree changes.
- **Labeling taxonomy:**
  - Section heading: "Queries" (unchanged from the placeholder card title)
  - Column headers: "Query text", "Reference answer", "Metadata", "Judgments", "" (kebab menu column, no header)
  - Row-action menu items: "Edit", "Edit metadata", "Delete" (three items, in that order)
  - Edit popover title: "Edit query"
  - Edit metadata dialog title: "Edit query metadata"
  - Edit metadata dialog buttons: "Clear metadata" (left, destructive-secondary, sends `{"query_metadata": null}`), "Cancel", "Save"
  - Delete confirm title: "Delete query?"
  - Delete confirm body: "This permanently removes the query. Judgments must be removed first."
  - Destructive button label: "Delete query"
  - 409 toast text: "N judgment lists reference this query. Open <first name> →" (link to `/judgments/{first_id}`)
- **Content hierarchy:** Primary: queries table (always visible). Secondary: row-action menus (kebab → dropdown, click to open). Tertiary: Edit popover / Edit metadata dialog / Delete confirm (modal-style overlays).
- **Progressive disclosure:** Long `query_text` truncated to 100 chars in the table cell with a `<Tooltip>` on hover showing the full text. `query_metadata` shown as a compact "Set" / "—" indicator badge in the cell (no inline preview — keeps the row a manageable height); full editor only in the modal. Clicking the indicator badge opens the metadata dialog directly (a convenience shortcut equivalent to kebab → "Edit metadata").
- **Relationship to existing pages:** EXTENDS `/query-sets/[id]` — same page, replaces a placeholder card. Sits ALONGSIDE the existing "Associated judgment lists" section (which remains unchanged).

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| `query_text` cell (truncated) | Full `query_text` value | hover | top |
| `reference_answer` cell (truncated, may be "—") | "Reference answer not set" if null; full text if set | hover | top |
| `judgment_count` column header | "Number of (query, doc) ratings across all judgment lists for this query" | hover | top |
| Delete row-action with `judgment_count > 0` | "Delete blocked — query has N judgments. Remove the parent judgment list first." | hover | top |
| "Edit query metadata" dialog | Inline helper text: "JSON object. Whole-object replace — explicit null removes the field, omitted keys leave existing fields unchanged on PATCH (this dialog sends the whole edited object)." | always visible below the JSON editor | inline |

The tooltip on the deletion row-action is a soft UX guard — even with the tooltip warning, the destructive action is still clickable; the 409 fires only after confirm (the operator may want to attempt deletion to see which judgment lists are affected). The hard guard is server-side.

### Primary flows

1. **List queries.** Operator opens `/query-sets/{id}`. The page renders the existing header + the new `<QueriesTable>` populated by `useQueries`. Default pagination: 50 rows, sorted by `id ASC`. Page-size selector: [10, 25, 50, 100]. X-Total-Count drives a "248 queries total" indicator above the table.
2. **Inline edit a query text.** Operator clicks the kebab → "Edit" → `<Popover>` opens anchored on the row. Two text fields: `query_text` (required) and `reference_answer` (optional). Save → PATCH → success toast + cache invalidation → row updates in place.
3. **Edit query metadata.** Operator clicks the kebab → "Edit metadata" → `<Dialog>` opens with a textarea showing the current JSON. Operator edits, clicks Save → JSON parsed client-side (Zod) → PATCH with `{query_metadata: parsed_object}` → success toast + cache invalidation.
4. **Delete a query with no judgments.** Operator clicks the kebab → "Delete" → `<AlertDialog>` opens with the destructive confirm. Click "Delete query" → DELETE → 204 → success toast → row removed from the table.
5. **Delete a query with judgments (blocked).** Same path as flow 4, but the DELETE returns 409. Toast renders "2 judgment lists reference this query. Open esci-tutorial-v1 →" with the link pointing at `/judgments/{first_id}`. Operator clicks through, deletes the judgment list (the existing `/judgments/[id]` page supports list deletion via its DELETE endpoint shipped by `feat_llm_judgments`), returns to `/query-sets/{id}`, retries the delete.

### Edge/error flows

- **Cursor decode failure.** Frontend sends a stale cursor (e.g., after page reload). Backend returns 422 `VALIDATION_ERROR` with message including the decoded exception. Frontend treats it as a paging error: resets to first page, logs the cursor, toasts "Pagination state lost — back to page 1." This is the same behavior as the existing `useQuerySets` / `useStudies` paginators (consistent UX).
- **PATCH on a deleted query.** Operator opens the edit popover on a row, network blip occurs, operator submits. Backend returns 404 `QUERY_NOT_FOUND`. Frontend toasts the standard "Resource not found" message via `MutationCache.onError` and refetches the table.
- **PATCH with invalid JSON in `query_metadata`.** Modal validates client-side via Zod before submitting (JSON.parse in the resolver). Bad JSON shows an inline field error, never reaches the backend.
- **Empty `query_text` on PATCH.** Backend returns 422 `VALIDATION_ERROR`. Frontend's Zod resolver also catches `min(1)` before submit; the 422 is the defense-in-depth backstop.
- **Concurrent delete + judgment-list-create race.** See §10 Threat 4.
- **>10 judgment lists reference one query.** The 409 envelope's `overflow_count` is non-zero; the toast still surfaces only the first affected list (rationale: a query that appears in >10 judgment lists is a pathological scenario the operator should investigate via the API directly, not the UI).
- **`X-Total-Count` mismatch.** After a successful DELETE, the cache invalidation refetches the list — the next `X-Total-Count` reflects the new total. No race vs. external operators (single-tenant MVP1).
- **Page-size change mid-pagination.** Selecting a different page size resets to page 1 (same pattern as the existing `useStudies` paginator).
- **Network failure on PATCH.** Standard 4-attempt retry contract from `api-client.ts` (per `infra_foundation` FR-7 + `feat_studies_ui` Story 1.1) — 503-retryable errors retry, 4xx-non-retryable surface immediately.

## 12) Given/When/Then acceptance criteria

### AC-1: List queries with judgment_count
- Given a query-set with 3 queries: Q1 (5 judgments across 1 list), Q2 (0 judgments), Q3 (12 judgments across 2 lists)
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?limit=50`
- Then the response is 200 with `data` containing exactly 3 rows, `judgment_count` values `[5, 0, 12]` in some deterministic order (ORDER BY id ASC), `next_cursor: null`, `has_more: false`, and `X-Total-Count: 3`
- Example values:
  - `Q1.query_text = "wireless headphones"`, `Q1.judgment_count = 5`
  - `Q2.reference_answer = null`

### AC-2: List with cursor pagination
- Given a query-set with 75 queries
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?limit=50`
- Then the response contains 50 rows + a non-null `next_cursor` + `has_more: true`
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?limit=50&cursor=<next_cursor>`
- Then the response contains the remaining 25 rows + `next_cursor: null` + `has_more: false`
- And no row appears in both pages

### AC-3: List with invalid cursor
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?cursor=not-base64`
- Then the response is 422 with `error_code: VALIDATION_ERROR` and `retryable: false`

### AC-4: List 404 on missing parent set
- When the client calls `GET /api/v1/query-sets/non-existent/queries`
- Then the response is 404 with `error_code: QUERY_SET_NOT_FOUND`

### AC-5: PATCH replaces query_text
- Given a query with `query_text="old text"`, `reference_answer="ref"`, `query_metadata={"intent":"commercial"}`
- When the client PATCHes `{"query_text": "new text"}`
- Then the response is 200 with `query_text="new text"`, `reference_answer="ref"` (unchanged), `query_metadata={"intent":"commercial"}` (unchanged)
- And a subsequent GET returns the same shape

### AC-6: PATCH whole-object-replaces query_metadata
- Given a query with `query_metadata={"intent":"commercial","priority":"high"}`
- When the client PATCHes `{"query_metadata": {"intent": "informational"}}`
- Then the response has `query_metadata={"intent":"informational"}` — `priority` is gone (whole-object replace, NOT deep-merge)

### AC-7: PATCH with null reference_answer removes value
- Given a query with `reference_answer="Brooks Beast"`
- When the client PATCHes `{"reference_answer": null}`
- Then the response has `reference_answer: null`
- And a subsequent GET returns `reference_answer: null`

### AC-8: PATCH with omitted reference_answer preserves value
- Given a query with `reference_answer="Brooks Beast"`
- When the client PATCHes `{"query_text": "x"}` (reference_answer key absent from body)
- Then the response has `reference_answer="Brooks Beast"` (unchanged)

### AC-9: PATCH 422 on empty query_text
- When the client PATCHes `{"query_text": ""}`
- Then the response is 422 with `error_code: VALIDATION_ERROR`

### AC-10: PATCH 422 on extra field
- When the client PATCHes `{"id": "new-uuid"}` (attempting to change immutable field)
- Then the response is 422 with `error_code: VALIDATION_ERROR` (extra="forbid")

### AC-11: PATCH 404 on missing query
- When the client PATCHes a non-existent `query_id` under any set
- Then the response is 404 with `error_code: QUERY_NOT_FOUND`

### AC-12: PATCH 404 cross-set
- Given query Q1 exists in set S1
- When the client PATCHes Q1 via `/query-sets/S2/queries/Q1` (wrong parent)
- Then the response is 404 with `error_code: QUERY_NOT_FOUND` (anti-enumeration; SAME shape as truly missing)

### AC-13: DELETE 204 when no judgments
- Given a query with `judgment_count = 0`
- When the client DELETEs it
- Then the response is 204 with empty body
- And a subsequent `GET /api/v1/query-sets/{set_id}/queries` LIST call has `X-Total-Count` decremented by 1 AND the deleted row's `id` no longer appears in `data` (verified across however many pages the set requires)
- And a subsequent PATCH on the deleted `query_id` returns 404 `QUERY_NOT_FOUND` (using PATCH as the existence probe — there is intentionally no single-query GET endpoint; see Decision log 2026-05-13)

### AC-14: DELETE 409 when judgments exist
- Given a query with 5 judgments across 1 judgment list named "esci-tutorial-v1"
- When the client DELETEs it
- Then the response is 409 with `error_code: QUERY_HAS_JUDGMENTS`
- And `detail.judgment_lists` is exactly `[{"id": "<list-id>", "name": "esci-tutorial-v1"}]`
- And `detail.overflow_count = 0`
- And the query row STILL EXISTS (verified by a follow-up LIST call returning the row in `data`)

### AC-15: DELETE 409 with >10 affected lists
- Given a query referenced by 15 judgment lists
- When the client DELETEs it
- Then the response is 409 with `detail.judgment_lists` containing 10 entries and `detail.overflow_count = 5`

### AC-16: DELETE 404 on missing query
- When the client DELETEs a non-existent `query_id`
- Then the response is 404 with `error_code: QUERY_NOT_FOUND`

### AC-17: DELETE idempotency-on-second-call
- Given a query that was just successfully deleted
- When the client DELETEs the same query_id again
- Then the response is 404 with `error_code: QUERY_NOT_FOUND` (deliberate non-idempotent semantics per §4 / §9)

### AC-18: Frontend queries table renders + paginates
- Given the operator is on `/query-sets/{id}` and the set has 75 queries
- When the page loads
- Then the `<QueriesTable>` renders the first 50 rows + a `<CursorPaginator>` with Next active
- And clicking Next loads rows 51-75 + sets Next to disabled

### AC-19: Frontend inline edit popover happy path
- Given the operator is on `/query-sets/{id}`
- When they click the kebab on row Q1 → "Edit" → modify `query_text` → Save
- Then the `<Popover>` closes, a success toast appears, and the row updates in place (verified via msw handler-hit-count showing GET refetch after the PATCH)

### AC-20: Frontend 409 toast on delete-with-judgments
- Given the operator is on `/query-sets/{id}` and row Q3 has 12 judgments across 2 lists
- When they click kebab on Q3 → "Delete" → confirm in the AlertDialog
- Then a destructive toast appears containing "2 judgment lists reference this query" with a link to the first affected list's detail page (`/judgments/{first-id}`)
- And Q3 still appears in the table

### AC-21: Frontend cache invalidation on PATCH/DELETE
- Given the operator just PATCHed a query
- Then the `['query-sets', querySetId]` query is invalidated (verified by msw handler-hit-count on the GET endpoint)
- And the `['query-sets', querySetId, 'queries']` query is invalidated

### AC-22: Frontend metadata edit dialog happy path
- Given the operator is on `/query-sets/{id}` and row Q1 has `query_metadata = {"intent": "commercial", "priority": "high"}`
- When they click the kebab on Q1 → "Edit metadata" → modify the JSON to `{"intent": "informational"}` → Save
- Then the `<Dialog>` closes, a success toast appears, the PATCH body sent is `{"query_metadata": {"intent": "informational"}}` (whole-object replace), and the row's metadata indicator updates after the GET refetch

### AC-23: Frontend metadata edit dialog rejects invalid JSON
- Given the metadata `<Dialog>` is open
- When the operator types `{not valid json}` and clicks Save
- Then an inline field error renders ("Invalid JSON") and no PATCH request is sent (verified by zero handler-hits on the PATCH endpoint)

### AC-24: DELETE 404 cross-set (anti-enumeration)
- Given query Q1 exists in set S1
- When the client DELETEs `/api/v1/query-sets/S2/queries/Q1` (Q1 belongs to S1, not S2)
- Then the response is 404 with `error_code: QUERY_NOT_FOUND` (same shape as truly missing — leaks no information about whether the query exists elsewhere)
- And Q1 still exists in S1 (verified by a follow-up LIST on S1)

### AC-25: GET listing `?since` filter respects UUIDv7 lower-bound
- Given a query-set with 50 queries minted across an hour, where queries 1–20 have UUIDv7 ids minted at `T0` and queries 21–50 minted at `T0 + 30min`
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?since=<iso8601 of T0 + 15min>`
- Then the response includes queries 21–50 ONLY (queries 1–20 excluded by the UUIDv7 lower-bound filter)
- And `X-Total-Count` is `30` (respects `?since`, not the unfiltered set size)
- And the filter is inclusive of any UUIDv7 minted exactly at the `since` timestamp boundary

### AC-26: GET listing `?since` combined with cursor
- Given a query-set where `?since=<T>` matches 75 rows
- When the client calls `GET /api/v1/query-sets/{set_id}/queries?since=<T>&limit=50`
- Then 50 rows are returned + a non-null `next_cursor`
- When the client calls the same endpoint with the same `?since=<T>&cursor=<next_cursor>&limit=50`
- Then the remaining 25 rows are returned + `next_cursor: null`
- And `?since` is honoured on the second page (no rows from before `<T>` appear)

### AC-27: Frontend metadata dialog supports clearing metadata
- Given row Q1 has `query_metadata = {"intent": "commercial"}`
- When the operator opens the metadata `<Dialog>`, clicks the "Clear metadata" button, and confirms
- Then the PATCH body sent is exactly `{"query_metadata": null}` (NOT an empty object `{}` — explicit null is the SQL-NULL signal)
- And the row's metadata indicator updates to "—" after the GET refetch

### AC-28: PATCH with empty body is a no-op 200
- Given a query Q1 with `query_text="x"`, `reference_answer="y"`, `query_metadata={"k":"v"}`
- When the client PATCHes Q1 with body `{}`
- Then the response is 200 with the unchanged `QueryRow` (same `query_text`, `reference_answer`, `query_metadata`, `judgment_count`)
- And no UPDATE statement was issued against the `queries` table (verified by SQLAlchemy event hook or DB-side row hash)

## 13) Non-functional requirements

- **Performance:** List endpoint p95 < 200ms for query-sets up to 10k queries. `judgment_count` SUBQUERY uses a single GROUP BY over the paginated page (50 rows max), not per-row. Index `judgments_list_query_idx` (already exists at [`backend/app/db/models/judgment.py:55`](../../../../backend/app/db/models/judgment.py#L55)) supports the count efficiently. PATCH p95 < 100ms. DELETE happy-path p95 < 100ms; DELETE-409-path p95 < 200ms (FK error + sample SELECT).
- **Reliability:** No new failure modes beyond existing query-set router; FK integrity errors are translated to deterministic 409s (no 500s on FK violation).
- **Operability:** Standard structlog at `info` level on every PATCH/DELETE: `event=query_updated`/`query_deleted`, `query_set_id`, `query_id`, `request_id`, `latency_ms`. No new metrics or dashboards (MVP1 — observability stack arrives at MVP2).
- **Accessibility/usability:** Table is keyboard-navigable (tab through rows; Enter on kebab opens menu). `<Popover>` and `<Dialog>` use shadcn primitives which already support ARIA correctly. Destructive `<AlertDialog>` cannot be dismissed by clicking outside (per shadcn defaults); the destructive action requires explicit button click.

## 14) Test strategy requirements

Minimum required coverage by layer:

- **Unit tests** (`backend/tests/unit/`) — pure logic only; NOT DB-backed:
  - `backend/tests/unit/api/test_query_cursor_helpers.py` — `_encode_query_cursor` / `_decode_query_cursor` round-trip + invalid-cursor handling. Pure functions, no DB.
  - `backend/tests/unit/api/test_uuidv7_since_helper.py` — UUIDv7 lower-bound construction from an ISO-8601 timestamp (the helper used by `?since`). Pure function.
  - `backend/tests/unit/api/test_update_query_request.py` — Pydantic validation: `extra="forbid"`, `query_text=null` rejection via `@model_validator`, `min_length=1` / `max_length=4000` boundaries. No DB.
  - **Note:** repo functions touching the `queries` table, `judgments` FK behavior, JSONB updates, and any Postgres-specific UUIDv7 lexical ordering go in **integration**, not unit. SQLite-in-memory does not enforce FK by default and lacks JSONB, so unit-level FK or JSONB assertions would be falsely green.

- **Integration tests** (`backend/tests/integration/`) — DB-backed, using the existing service-container Postgres + the async session fixture:
  - `backend/tests/integration/test_query_sets_router_queries.py` — covers **AC-1 through AC-17 plus AC-24, AC-25, AC-26, and AC-28** at the router layer. AC-3 (invalid-cursor 422) is asserted here, not just at the helper unit level, because it's an API error-envelope contract. AC-24 asserts DELETE cross-set 404 anti-enumeration. AC-25/AC-26 assert `?since` filter semantics including UUIDv7 lower-bound inclusivity, `X-Total-Count` respecting `?since`, and `?since`+cursor combination. AC-28 asserts empty-PATCH `{}` returns 200 with the current `QueryRow` (no-op). Mocks NOTHING internal.
  - `backend/tests/integration/test_query_repo_extensions.py` — DB-backed exercises of `get_query`, `count_queries_for_set`, `list_queries_for_set_cursor` (including `?since` UUIDv7 lower-bound), `update_query` (whole-object replace on `query_metadata`; null vs missing key on `reference_answer`), `delete_query` (raises `IntegrityError` when a `judgments` row references the query).
  - `backend/tests/integration/test_judgment_repo_query_helpers.py` — DB-backed `count_and_sample_judgment_refs(query_id, sample_limit=10)`: returns `(judgment_count, list_count, sample_lists, overflow_count)` correctly across 0 / 1 / 10 / 11+ list scenarios. Asserts the helper's TWO-SQL design: one aggregate (`COUNT(*)` + `COUNT(DISTINCT judgment_list_id)`) plus one sample query (`GROUP BY` + `LIMIT 10`). Verify alphabetical ordering of `sample_lists` by `name`. SQL-statement count via SQLAlchemy event hook is optional — the contract-level assertion is that the returned data is correct.
  - The integration test MUST also cover the §10 Threat 4 race (concurrent `delete_query` + `bulk_create_judgments` via `asyncio.gather`), asserting EITHER the delete succeeded and no judgments exist OR the delete returned `IntegrityError` and judgments exist.

- **Contract tests** (`backend/tests/contract/`):
  - `backend/tests/contract/test_query_sets_api_contract.py` (new file) — assert the 3 new endpoints exist on the OpenAPI surface; assert `QueryRow`, `QueryListResponse`, `UpdateQueryRequest` schemas are exported; assert each endpoint emits the documented error codes via grep-based source-code static check (mirror the pattern in `test_webhook_api_contract.py`); assert `QUERY_HAS_JUDGMENTS` envelope has the documented `judgment_lists` + `overflow_count` fields (parse the OpenAPI schema for the 409 example).

- **E2E tests** (`ui/tests/e2e/`):
  - **None for MVP1.** E2E coverage for `/query-sets/[id]` does not exist today (per `feat_studies_ui` PR #50 stories). Adding the first E2E test against a real backend on this feature is out of scope — captured as `chore_query_inline_crud_e2e` idea file deferred from this implementation.

- **Frontend unit/component tests** (`ui/src/`):
  - `ui/src/components/query-sets/__tests__/queries-table.test.tsx` — renders rows, paginates, kebab opens, msw handler-hit-counts assert TanStack invalidation on PATCH and DELETE.
  - `ui/src/components/query-sets/__tests__/edit-query-popover.test.tsx` — form validation (Zod schema), success (200) and 422 paths; PATCH body shape (omitted keys absent from JSON).
  - `ui/src/components/query-sets/__tests__/edit-metadata-dialog.test.tsx` — (AC-22 / AC-23 / AC-27) whole-object replace happy path, invalid-JSON inline error + no PATCH submission, "Clear metadata" button sends exactly `{"query_metadata": null}`.
  - `ui/src/components/query-sets/__tests__/delete-query-dialog.test.tsx` — confirm-button disabled while pending; 409 `QUERY_HAS_JUDGMENTS` toast renders the affected-list link; non-409 errors fall through to `toToastMessage(err)` (bit-for-bit match with global handler).
  - `ui/src/lib/api/__tests__/queries.test.tsx` — `useQueries`, `useUpdateQuery`, `useDeleteQuery` hooks; msw handler-hit-count assertions for cache invalidation; assert `useDeleteQuery` opts out of the global error toast via `meta: { suppressGlobalErrorToast: true }`.

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md`: append `GET /api/v1/query-sets/{set_id}/queries` to the §"Pagination" MVP1-active endpoint list.
- `docs/02_product/mvp1-user-stories.md`: extend US-08 (query-set review) with a one-line note that per-query inline edit/delete shipped via `feat_query_inline_crud`. Add the feature to the MVP1 release table.
- `docs/03_runbooks/`: no new runbook needed (no new failure modes beyond standard 4xx/5xx). The existing `ui-debugging.md` (from `feat_studies_ui`) gets a new section: "Per-query editing — when delete returns 409, follow the toast link to the affected judgment list and remove it first."
- `docs/04_security/`: no new entries.
- `docs/05_quality/testing.md`: no new entries (test layers unchanged).
- `state.md`: move `feat_query_inline_crud` from `/pipeline candidates` to "Most recent meaningful changes" once shipped. Update the active backlog count accordingly.
- `architecture.md`: no changes (no new top-level layer; this is a feature spanning existing router/repo/UI layers).
- `CLAUDE.md`: no changes.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-tenant MVP1; no flag infrastructure exists. The feature ships behind the route that already exists — operators on `/query-sets/[id]` will see the new table immediately on first load post-merge.
- **Migration/backfill expectations:** No migrations. Zero schema change.
- **Operational readiness gates:**
  - `make test-unit && make test-integration && make test-contract` green.
  - `cd ui && pnpm test && pnpm typecheck && pnpm lint && pnpm build` green.
  - Coverage gate ≥ 80% (`pyproject.toml` `fail_under = 80`).
  - Enum source-of-truth gate green (this feature adds no new enums — gate is a no-op for it).
- **Release gate:** standard CI pass on the feature branch + Gemini Code Assist review adjudicated + GPT-5.5 final review clean per CLAUDE.md "Cross-model review policy."

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (list endpoint) | AC-1, AC-2, AC-3, AC-4, AC-25, AC-26 | Story 1.1 (router GET) + Story 1.2 (repo list) + Story 1.3 (judgment_count batch helper) + Story 1.4 (UUIDv7 lower-bound helper for `?since`) | `test_query_sets_router_queries.py`, `test_query_repo_extensions.py`, `test_query_sets_api_contract.py`, `test_uuidv7_since_helper.py` | `api-conventions.md` |
| FR-2 (PATCH endpoint) | AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-28 | Story 2.1 (router PATCH) + Story 2.2 (repo update + schema) | `test_query_sets_router_queries.py`, `test_query_repo_extensions.py`, `test_query_sets_api_contract.py`, `test_update_query_request.py` | `api-conventions.md` |
| FR-3 (DELETE endpoint + FK guard) | AC-13, AC-14, AC-15, AC-16, AC-17, AC-24 | Story 3.1 (router DELETE + 409 envelope + OpenAPI `responses` wiring) + Story 3.2 (repo delete + `count_and_sample_judgment_refs`) | `test_query_sets_router_queries.py`, `test_judgment_repo_query_helpers.py`, `test_query_sets_api_contract.py` | `api-conventions.md` |
| FR-4 (frontend table + edit/delete UI) | AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-27 | Story 4.1 (replace placeholder card with `<QueriesTable>`) + Story 4.2 (`<EditQueryPopover>` + `<EditMetadataDialog>` with Clear button) + Story 4.3 (`<DeleteQueryDialog>` + 409 toast wiring) | `queries-table.test.tsx`, `edit-query-popover.test.tsx`, `edit-metadata-dialog.test.tsx`, `delete-query-dialog.test.tsx` | `ui-debugging.md` |
| FR-5 (repo + service layer) | (covered transitively by AC-1..AC-17) | Stories 1.2, 1.3, 2.2, 3.2 above | `test_query_repo.py`, `test_judgment_repo_query_helpers.py` | (none — internal) |
| FR-6 (frontend hooks) | AC-21 | Story 4.0 (extend `ui/src/lib/api/query-sets.ts`) | `queries.test.tsx` | (none — internal) |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-28) pass in CI.
- [ ] All test layers green: unit, integration, contract, frontend unit/component.
- [ ] Coverage gate ≥ 80%.
- [ ] No new lint, typecheck, or enum source-of-truth violations.
- [ ] Documentation updates: `api-conventions.md`, `mvp1-user-stories.md`, `ui-debugging.md` merged in the same PR.
- [ ] `state.md` updated to reflect the feature shipping and the backlog row removed.
- [ ] The placeholder card at `ui/src/app/query-sets/[id]/page.tsx:61-72` (with the `chore_query_inline_edit_delete` bareword) is REMOVED — no orphan references in the codebase.
- [ ] Gemini Code Assist review adjudicated (all findings Accepted / Rejected with cited counter-evidence / Deferred to follow-up idea file).
- [ ] GPT-5.5 final review on the merged-branch diff is clean.

## 19) Open questions and decision log

### Open questions

None — all open questions in the idea file (`idea.md` §"Open questions for /spec-gen") have been resolved with the recommended defaults locked into this spec:

1. **`judgment_count` in listing endpoint.** Locked: YES, single GROUP BY batch helper. (§7 FR-1, §13 Performance)
2. **DELETE 409 envelope shape.** Locked: `{judgment_lists: list[{id, name}] (up to 10), overflow_count: int}`. (§8.5)
3. **Inline edit UX form factor.** Locked: `<Popover>` for `query_text` + `reference_answer`; `<Dialog>` for `query_metadata`. (§11)

One question is **deliberately deferred** to a future feature (not blocking this one):

- **Should PATCH or DELETE be blocked when the parent query-set is referenced by a running study?** Defer to a future `infra_running_study_protection` chore. The MVP1 risk is low (operators rarely PATCH a query mid-study); the protection adds cross-table state inspection on every PATCH/DELETE that doesn't pay for itself in MVP1. Captured as a tangential idea below.

### Decision log

- 2026-05-13 — **PATCH semantics: whole-object replace on `query_metadata`** (not deep-merge). Rationale: matches existing `BulkQueriesJsonRequest` convention and avoids null-vs-missing-key ambiguity. (Idea §"Locked decisions" #1)
- 2026-05-13 — **DELETE semantics: hard delete, FK-guarded.** No `deleted_at` column added. Rationale: data-model precedent + scope discipline. (Idea §"Locked decisions" #2)
- 2026-05-13 — **Audit-log emission deferred to MVP2.** Spec §6 matrix locks the event types and metadata constraints for when MVP2 lands. (Idea §"Locked decisions" #3)
- 2026-05-13 — **FK guard implementation: rely on `IntegrityError`, not pre-DELETE count.** Rationale: lock-free, race-safe, and the count-then-delete pattern is racy anyway. (§7 FR-3)
- 2026-05-13 — **`?since` filter uses UUIDv7 timestamp extraction**, not a `created_at` column. Rationale: avoids a schema migration on `queries`; UUIDv7 is already the PK and encodes ms-precision time. (§7 FR-1)
- 2026-05-13 — **`UpdateQueryRequest` has `model_config = ConfigDict(extra="forbid")`.** Rationale: rejects attempts to PATCH immutable fields (`id`, `query_set_id`) as 422 rather than silently ignoring. Mirrors existing Pydantic conventions in this codebase. (§9)
- 2026-05-13 — **`QUERY_NOT_FOUND` instead of `QUERY_NOT_IN_SET` on cross-set lookup.** Rationale: anti-enumeration — leaking that a query exists in a different set is a low-grade information disclosure. Same envelope as genuinely missing. (§10 Threat 2)
- 2026-05-13 — **No single-query GET endpoint.** Acceptance criteria verify existence/absence via either the LIST endpoint (X-Total-Count + data inspection) or via PATCH's 404 response as the existence probe. Adding `GET /api/v1/query-sets/{set_id}/queries/{query_id}` was considered for the inline-edit prefetch use case but rejected — the inline edit popover reads from the current table-row data (already in the TanStack cache), so a per-query GET is not load-bearing. Defer until a real consumer surfaces.
- 2026-05-13 — **Repo helper `count_and_sample_judgment_refs` returns all four fields** (`judgment_count`, `list_count`, `sample_lists`, `overflow_count`) so the 409 envelope can be constructed from a single helper call. Implementation: TWO SQL statements (aggregate for `judgment_count` + `list_count`, sample with `LIMIT 10` for `sample_lists`); helper is only called on the 409 cold path. (§7 FR-5)
- 2026-05-13 — **Cursor is id-only**, not `(created_at, id)`. UUIDv7 is already lexically time-ordered; the synthetic tuple would be redundant. New `_encode_query_cursor` / `_decode_query_cursor` helpers live alongside the existing query-set cursor helpers in the same router file. (§7 FR-1)
- 2026-05-13 — **Unit tests for FK / JSONB / UUIDv7-lexical behavior move to integration.** SQLite-in-memory does not enforce FK by default and lacks JSONB; unit-level FK/JSONB assertions would be falsely green. (§14)
- 2026-05-13 — **Frontend NO local `onError` handlers on mutations EXCEPT `useDeleteQuery`** (the 409 carve-out). Rationale: the global `MutationCache.onError` in `query-provider.tsx` already handles error toasting via `toToastMessage(err)` (precedent: chore_cluster_delete_ui PR #87 Gemini rejection). `useDeleteQuery` is the single exception because the 409 `QUERY_HAS_JUDGMENTS` toast must render an action link (Sonner `action` slot), which the generic global handler cannot emit. It opts out via `meta: { suppressGlobalErrorToast: true }` AND adds a local `onError` that delegates to `toToastMessage(err)` for any non-409 error code (so non-409 behavior matches the global handler bit-for-bit). (§7 FR-4 + FR-6)
