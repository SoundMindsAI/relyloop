# API Conventions

**Status:** Adopted for MVP1. New conventions activate at the release noted on each row.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §28](../00_overview/product/relevance-copilot-spec.md) ("API conventions" subsection).

---

## URL structure

| Convention | Rule | MVP1 status |
|---|---|---|
| Versioning | URL-versioned at `/api/v1/<resource>` for business endpoints | Active |
| Operator endpoints | Unversioned; live at root (e.g., `/healthz`) | Active |
| Webhooks | Unversioned; live under `/webhooks/<provider>` (e.g., `/webhooks/github`) | Active for GitHub (added by `feat_github_webhook`) |
| Resource naming | Plural nouns: `/clusters`, `/studies`, `/proposals`, `/judgment-lists` | Active |
| ID-in-path | UUIDv7 in canonical hyphenated form: `/clusters/{cluster_id}` | Active |
| Sub-resources | Nest under parent: `/clusters/{cluster_id}/schema`, `/studies/{study_id}/trials` | Active |

Do not invent alternative prefixes (`/api/`, `/v1/`, `/relyloop/`). The single canonical prefix is `/api/v1/`.

## HTTP methods

| Method | Use for |
|---|---|
| `GET` | Read; idempotent; never mutates |
| `POST` | Create a resource; trigger a non-idempotent action (e.g., `POST /studies/{id}/cancel`) |
| `PUT` | Full replacement of an existing resource |
| `PATCH` | Partial update of an existing resource |
| `DELETE` | Soft-delete (sets `deleted_at`); hard-delete only on internal append-only tables |

## Error envelope

All non-auth error responses use a structured envelope. Auth errors (when auth lands at MVP4) often have a different shape — see "Auth errors" below.

**Shape (MVP1):**
```json
{
  "detail": {
    "error_code": "<MACHINE_READABLE_CODE>",
    "message": "<human-readable explanation>",
    "retryable": <bool>
  }
}
```

**Rules:**

- `error_code` is the contract — frontends and clients branch on it. Codes are stable (never renamed).
- `message` is for human display; can change freely.
- `retryable: true` means the same request *may* succeed if retried (transient infra failures, rate limits). `false` means client must change input.
- Status codes are deterministic per scenario — never `200 OK` with an error in the body.
- A single endpoint can return multiple `error_code` values; document them in the spec's §7.5 Error Code Catalog.

**RFC 7807 alignment:** the MVP1 envelope is a subset of RFC 7807 Problem Details; full RFC 7807 compliance (with `type`, `title`, `instance` fields) lands at GA v1.

**Why this shape:** machine-readable `error_code` + retryability flag covers the two questions every client needs to answer (what went wrong; should I retry). Adding RFC 7807 boilerplate now gives no value.

### Standard error codes

These are reserved across all features:

| Code | HTTP Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request body failed Pydantic validation. `details` field lists per-field errors. |
| `RESOURCE_NOT_FOUND` | 404 | Generic "not found." Most features define a specific code (e.g., `CLUSTER_NOT_FOUND`); `RESOURCE_NOT_FOUND` is for unknown sub-resources. |
| `RATE_LIMITED` | 429 | Caller exceeded rate budget. `retryable: true`. |
| `INTERNAL_ERROR` | 500 | Unexpected server error. Includes `trace_id` for log correlation. |
| `SERVICE_UNAVAILABLE` | 503 | A dependency is down or unreachable. `retryable: true`. |

Feature-specific codes (e.g., `CLUSTER_UNREACHABLE`, `INVALID_QUERY_DSL`) are documented in the feature's spec.

The studies endpoint surfaces two template-mismatch codes (added by `chore_create_study_wizard_polish`, 2026-05-19):

| Code | HTTP Status | Meaning |
|---|---|---|
| `SEARCH_SPACE_UNKNOWN_PARAM` | 400 | A key in `search_space.params` is not declared by the selected template. Message format: `"Param '{name}' is not declared by template '{template_name}'. Declared params: [...]."` `retryable: false`. |
| `SEARCH_SPACE_MISSING_DECLARED_PARAM` | 400 | A key in the template's `declared_params` is missing from the submitted `search_space.params`. Message format: `"Template '{template_name}' declares param '{name}' but it is missing from the search space. Add it or remove from the template."` `retryable: false`. |

The clusters endpoint surfaces an ACL-restriction code on the targets sub-resource (added by `feat_create_study_target_autocomplete`, 2026-05-20):

| Code | HTTP Status | Meaning |
|---|---|---|
| `TARGETS_FORBIDDEN` | 403 | Cluster denied the listing call (typically the Elasticsearch security plugin returning 401/403 on `GET /_cat/indices`). `retryable: false` — the UI auto-engages manual-mode target entry on this code rather than retrying. Distinguishes from `CLUSTER_UNREACHABLE` because retry won't help when the cluster's ACL is the cause. |

### Auth errors (MVP4+)

When auth arrives, auth failures use a separate envelope:
```json
{ "detail": "Authentication required" }
```
Plain string, not structured. This matches FastAPI's default for `HTTPBearer` / `HTTPBasic` deps.

Why different: auth failures fire before request validation; the structured envelope is overkill.

## Pagination

All list endpoints use **cursor pagination**. No offset/limit.

**Request:**
- `?cursor=<opaque>` — opaque server-issued token; absent for first page.
- `?limit=<n>` — page size; default 50, max 200.

**Response:**
```json
{
  "data": [ ... ],
  "next_cursor": "<opaque>" | null,
  "has_more": <bool>
}
```

`next_cursor` is `null` when there are no more pages. Cursors are opaque to clients — never construct them. They're typically `(created_at, id)` base64-encoded.

**Total counts.** Every list endpoint **MUST** return an `X-Total-Count` response header with the total row count matching the current filter (independent of pagination). Required for dashboard count widgets in `feat_studies_ui` + `feat_proposals_ui` (e.g., "studies completed in last 7 days") without forcing the UI to paginate the entire list. Backend implementation is a separate `COUNT(*)` query alongside the paginated SELECT; perf is acceptable for MVP1 list sizes (<10K rows typical) and can be optimized via cached estimates at MVP2.

**Filtering by recency.** Every list endpoint **MUST** accept a `?since=<iso8601>` query param that filters by `created_at >= since`. Combines with other filter params. `feat_data_table_primitive` extended this convention to `GET /api/v1/judgment-lists` and `GET /api/v1/conversations`, which previously lacked the param.

**Full-text search.** Six list endpoints accept `?q=<text>` for full-text search powered by a Postgres `tsvector GENERATED ALWAYS AS … STORED` column + GIN index per row (added by `feat_data_table_primitive` migrations `0008`–`0013`). The predicate is `search_vector @@ plainto_tsquery('english', q)`. Results are filtered (not rank-ordered — rank ordering deferred to MVP2; see [`docs/02_product/planned_features/feat_fts_rank_ordering_mvp2/idea.md`](../02_product/planned_features/feat_fts_rank_ordering_mvp2/idea.md)) so the existing `(created_at, id)` cursor stays correct. The Zod schema in the UI rejects under-length input (min 2 chars) before the backend ever sees the call.

| Endpoint | Searchable fields |
|---|---|
| `GET /api/v1/clusters` | `name + base_url` |
| `GET /api/v1/studies` | `name` |
| `GET /api/v1/query-sets` | `name` |
| `GET /api/v1/query-templates` | `name` |
| `GET /api/v1/judgment-lists` | `name` |
| `GET /api/v1/conversations` | `title` |

The `search_vector` column is **not declared in the ORM models** — it is database-generated. Never INSERT or UPDATE it directly; the column is read-only from the application's perspective.

**Sort.** Most list endpoints accept `?sort=<col>:<asc|desc>` (e.g. `?sort=name:asc`, `?sort=created_at:desc`). The cursor encoding is sort-aware: when `?sort=name:asc` is active, the cursor encodes `(name, id)` rather than `(created_at, id)`, so changing sort drops the cursor and starts a new page-1. `trials` is the one exception — its backend Literal predates this convention and uses fused tokens (`primary_metric_desc`, `ended_at_asc`, `optuna_trial_number_asc`). The frontend `<DataTable>` accepts an optional `sortCodec` prop that translates between internal `(col, dir)` and the wire form so the legacy contract survives unchanged.

**MVP1 status:** `?cursor=`, `?limit=`, `?since=` active for `GET /api/v1/clusters`, `GET /api/v1/studies`, `GET /api/v1/proposals`, `GET /api/v1/conversations`, `GET /api/v1/query-sets`, `GET /api/v1/query-sets/{id}/queries` (per-query list, added by `feat_query_inline_crud` with id-only UUIDv7 cursor + UUIDv7-lower-bound `?since`), `GET /api/v1/query-templates`, `GET /api/v1/judgment-lists`, `GET /api/v1/config-repos`. `?q=` + `?sort=` added by `feat_data_table_primitive` to the 6/7 endpoints in the tables above. Not used on resource-detail endpoints.

## Idempotency

**MVP1:** Not enforced. Clients are responsible for retry-safe code paths.

**GA v1:** `Idempotency-Key` header on POST/PATCH/DELETE. Server stores `(idempotency_key, response_hash)` for 24h; replays return the cached response.

## Trace / request correlation

**MVP1:** every request gets a `request_id` (UUIDv7) generated by FastAPI middleware on entry, attached to every structured-log record for that request via structlog context, and echoed back in the `X-Request-ID` response header. If the client supplies `X-Request-ID` on the request, the server adopts it (idempotent retry support); otherwise the server mints one. **MVP1 does NOT propagate `traceparent` through DB / Redis / OpenAI / ES / GitHub** — that's MVP2 work and requires custom Arq enqueue→pickup serialization which is out of scope here.

**MVP2+:** W3C `traceparent` flows through every boundary (API → Redis → worker → adapter → engine), including the Arq queue boundary (custom serialization). OpenTelemetry exporter wired to SigNoz collector; full distributed tracing.

## Rate limiting

**MVP1: not implemented.** No middleware, no headers, no `RATE_LIMITED` errors. The MVP1 install is single-tenant on a laptop with no production load — rate limiting is unwarranted infrastructure.

**MVP4+:** activates with bearer API keys per umbrella §18. Per-key rate limits with the standard headers:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | Window limit |
| `X-RateLimit-Remaining` | Remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

The `RATE_LIMITED` error code (HTTP 429, `retryable: true`) is reserved in §"Standard error codes" for when this activates.

## Request/response shapes

**Pydantic-first.** Every request body and response body is a Pydantic v2 model. FastAPI auto-generates OpenAPI from these models; the OpenAPI schema is the source of truth for the contract.

**Naming:**
- Request models: `Create<Resource>Request`, `Update<Resource>Request`, etc.
- Response models: `<Resource>` for the canonical full shape; `<Resource>Summary` for list views with fewer fields.
- All Pydantic field names are `snake_case` matching DB column names.

**JSON-only.** No multipart, no XML, no form-encoded — except CSV upload endpoints (e.g., import queries from CSV) which use `Content-Type: text/csv` directly with the body.

## Reserved for later releases

API conventions that activate later (consolidated from the per-row "MVP1 status" annotations above):

| Convention | Activates at |
|---|---|
| W3C `traceparent` propagation through DB / Redis / OpenAI / ES / GitHub (incl. Arq boundary) | MVP2 |
| OpenTelemetry exporter wired to a real collector (traces leave the process) | MVP2 |
| Webhook signature verification beyond GitHub (GitLab, Bitbucket signers) | MVP3 |
| Auth surface (`Authorization` headers, auth error envelope, 401/403 responses, SSO header trust) | MVP4 |
| Bearer API keys (Argon2id-hashed at rest) for service accounts | MVP4 |
| Rate-limit middleware + `X-RateLimit-*` headers + `RATE_LIMITED` error active | MVP4 (with API keys) |
| Tenant-scoped routing (`/api/v1/tenants/{tenant_id}/...` or per-tenant subdomain) | MVP4 |
| `Idempotency-Key` header on POST/PATCH/DELETE | GA v1 |
| Full RFC 7807 Problem Details (`type`, `title`, `instance` fields) on errors | GA v1 |

## Anti-patterns

These are explicitly wrong:

- **Do not** return `200 OK` with an error in the body. HTTP status is the contract.
- **Do not** invent error envelope shapes per endpoint. The shape in §"Error envelope" is the only shape.
- **Do not** use offset/limit pagination. Cursor only.
- **Do not** put credentials, tokens, or PII in URLs or query strings. Bodies only, over TLS (when TLS arrives at MVP4).
- **Do not** rename `error_code` values once shipped. Add new codes; deprecate old ones via the changelog.
- **Do not** version individual endpoints (`/api/v1/foo` and `/api/v2/foo` simultaneously). Version the whole API or use additive evolution.

## Cross-references

- Backend stack (FastAPI, Pydantic v2): [`tech-stack.md`](tech-stack.md)
- Service topology and where these endpoints live: [`system-overview.md`](system-overview.md)
- Tables backing the resources: [`data-model.md`](data-model.md)
- Engine adapter Protocol (consumed by `/clusters/{id}/...` endpoints): [`adapters.md`](adapters.md)
