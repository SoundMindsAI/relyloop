# Implementation Plan — Shared `<DataTable>` primitive (FTS + sort + filter + URL state)

**Date:** 2026-05-15
**Status:** Draft
**Primary spec:** [feature_spec.md](./feature_spec.md)
**Policy source(s):**
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — cursor pagination + `X-Total-Count` + error envelope
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — frontend stack, URL-state convention, contextual-help primitives
- [CLAUDE.md](../../../../CLAUDE.md) — Absolute Rules, conventions, testing layers

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs.
- Single PR per Locked Decision #4 — commit boundaries inside the PR map to stories, so reviewers can navigate.
- Sequential execution: Epic 1 (backend) → Epic 2 (primitive scaffold) → Epic 3 (table migrations) → Epic 4 (docs).
- Phase gates are hard stops — cross-model review after Epic 1, Epic 2, and Epic 3.
- Keep increments narrow enough to verify independently — each story is independently testable.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (`?q=` on 6 endpoints) | Epic 1 / Story 1.2 | Filter-only FTS; preserves `(created_at, id)` cursor |
| FR-2 (6 Alembic migrations) | Epic 1 / Story 1.1 | One commit per migration (`0008` → `0013`) |
| FR-3 (`?template_id=` on proposals) | Epic 1 / Story 1.5 | + `?since=` on judgment-lists & conversations (closes pre-existing drift) |
| FR-3a (`?sort=`, `?engine_type=`, `?environment=`) | Epic 1 / Stories 1.3 + 1.4 | 1.3: `?sort=` + sort-aware cursor on 7 endpoints; 1.4: enum filters on clusters + templates |
| FR-4 (sortable column headers) | Epic 2 / Story 2.2 | TanStack Table sort state + `firstClickDirection` override |
| FR-5 (filter chips: enum + fk-select) | Epic 2 / Story 2.3 | Generalizes existing chip + select patterns |
| FR-6 (debounced text search) | Epic 2 / Story 2.4 | 300ms debounce + Zod min(2) |
| FR-7 (total-count display) | Epic 2 / Story 2.5 | Range form on page 1; "N rows of M matching" on subsequent pages |
| FR-8 (URL-backed state with push/replace) | Epic 2 / Story 2.6 | `push()` on cursor, `replace()` on filter/sort/q |
| FR-9 (three empty-state shapes) | Epic 2 / Story 2.7 | `no-rows-match` / `no-rows-exist` / `stale-cursor` |
| FR-10 (cursor pagination controls) | Epic 2 / Story 2.7 | Internal `CursorPaginator` wrapper |
| FR-11 (sticky header) | Epic 2 / Story 2.8 | `position: sticky` Tailwind utility |
| FR-12 (tooltip-enabled headers) | Epic 2 / Story 2.8 | Reuses `InfoTooltip` + glossary |
| FR-13 (selection + bulk-action toolbar) | Epic 2 / Story 2.9 | React-only selection; clears on cursor move |
| FR-14 (column visibility menu) | Epic 2 / Story 2.10 | localStorage-persisted |
| FR-15 (density toggle) | Epic 2 / Story 2.11 | localStorage-persisted |
| FR-16 (keyboard navigation) | Epic 2 / Story 2.12 | Arrow / Enter / Space |
| FR-17 (source-of-truth lint guard) | Epic 2 / Story 2.13 | Vitest scan of column configs |
| (8 table migrations) | Epic 3 / Stories 3.1 – 3.8 | One story per migrated table |
| (docs + follow-ups) | Epic 4 / Stories 4.1 – 4.2 | Architecture docs + deferred-feature capture |

**Deferred FRs**: none. Spec is single-phase per Locked Decision #4.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Frontend stories use the UI element inventory + state dependency analysis pattern. Migration stories use the Phase → Tasks → Checkpoint gate inline.

### Conventions for this plan

- Backend repo functions take `db: AsyncSession` as first arg and use `await db.flush()`; the caller (service or router) commits.
- Pydantic v2; field aliases (`Query(alias="status")`) where wire name differs from kwarg.
- Cursor encoding stays opaque base64-JSON; payload shape is sort-aware per FR-3a.
- Frontend column configs export from `ui/src/components/<resource>/<table>-table.column-config.ts` (a new co-located convention; the table component itself just wires the config to `<DataTable>`).
- Every column config that uses `filter.kind === 'enum'` MUST cite the **backend allowlist** via `sourceOfTruth: "backend/app/api/v1/schemas.py <Symbol>"` (e.g., `"backend/app/api/v1/schemas.py StudyStatusWire"`). The frontend `wireValues` value is imported from `ui/src/lib/enums.ts` (which itself carries the reverse `// Values must match backend/...py <Symbol>` source-of-truth comment per the existing Story 4.2 grep gate). The lint guard (Story 2.13) asserts both: backend citation in `sourceOfTruth` AND `wireValues` imported from `enums.ts`.
- Every new `<col>:<dir>` Literal in `backend/app/api/v1/schemas.py` carries a `# Values must match ui/src/lib/enums.ts <SYMBOL>` comment; the matching `enums.ts` export carries the reverse `// Values must match backend/...py <Symbol>` comment. The existing Story 4.2 CI grep gate (`scripts/ci/verify_enum_source_of_truth.sh`) enforces parity.
- All Alembic migrations include `downgrade()` per CLAUDE.md Absolute Rule #5. Round-trip clean is asserted in integration tests.
- Tests run against the real Postgres + Redis (no in-memory mocks for DB/Redis).
- E2E tests use Playwright `page` for browser interactions; `request` only for setup helpers in `ui/tests/e2e/helpers/seed.ts`.

### AI Agent Execution Protocol

Per template; no project-specific overrides. Execute Epic 1 fully before starting Epic 2; Epic 2 fully before Epic 3; Epic 3 fully before Epic 4.

---

## Epic 1 — Backend FTS + filter/sort surface

**Goal:** Land the 6 Alembic migrations and the new query-parameter surface on the affected list endpoints. By the end of Epic 1 the backend is ready for the frontend primitive — no frontend code changes yet.

### Story 1.1 — Add 6 `search_vector` migrations (0008 – 0013)

**Outcome:** Each of clusters, studies, query_sets, query_templates, judgment_lists, conversations has a `tsvector GENERATED ALWAYS AS … STORED` column and a `GIN(search_vector)` index. Round-trip clean per CLAUDE.md Rule #5.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0008_search_vector_clusters.py` | Add `search_vector` column + `clusters_search_vector_idx` GIN index on `clusters` |
| `migrations/versions/0009_search_vector_studies.py` | Same shape on `studies` (source columns: `name + target`) |
| `migrations/versions/0010_search_vector_query_sets.py` | Same shape on `query_sets` (source column: `name`) |
| `migrations/versions/0011_search_vector_query_templates.py` | Same shape on `query_templates` (source column: `name`) |
| `migrations/versions/0012_search_vector_judgment_lists.py` | Same shape on `judgment_lists` (source columns: `name + target`) |
| `migrations/versions/0013_search_vector_conversations.py` | Same shape on `conversations` (source column: `coalesce(title, '')`) |

**Modified files**

None — migrations only.

**Key interfaces**

Each migration follows the pattern:

```python
revision = "0008"
down_revision = "0007"

def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE clusters ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(base_url, ''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX clusters_search_vector_idx ON clusters USING GIN (search_vector)")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS clusters_search_vector_idx")
    op.execute("ALTER TABLE clusters DROP COLUMN IF EXISTS search_vector")
```

Per-migration generated expression per [spec FR-2](./feature_spec.md#fr-2-six-alembic-migrations-adding-generated-search_vector-columns--gin-indexes):

| Migration | Generated expression |
|---|---|
| `0008` clusters | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(base_url, ''))` |
| `0009` studies | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(target, ''))` |
| `0010` query_sets | `to_tsvector('english', coalesce(name, ''))` |
| `0011` query_templates | `to_tsvector('english', coalesce(name, ''))` |
| `0012` judgment_lists | `to_tsvector('english', coalesce(name, '') \|\| ' ' \|\| coalesce(target, ''))` |
| `0013` conversations | `to_tsvector('english', coalesce(title, ''))` |

**Tasks**

1. Verify current Alembic head with `ls migrations/versions/ | sort | tail -1` — must be `0007_conversations_messages` before starting.
2. Write `0008_search_vector_clusters.py` per the pattern above. Pin `revision = "0008"`, `down_revision = "0007"`.
3. Run `.venv/bin/alembic upgrade head` from repo root; confirm no error.
4. Run `.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`; confirm round-trip clean.
5. Repeat steps 2–4 for `0009` (down_rev `0008`), `0010` (down_rev `0009`), `0011` (down_rev `0010`), `0012` (down_rev `0011`), `0013` (down_rev `0012`).
6. After all 6 land: run `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade 0007 && .venv/bin/alembic upgrade head` to verify the full-stack round-trip.
7. **Commit boundaries**: one commit per migration. Six commits.

**Definition of Done**
- All six migration files exist with `upgrade()` and `downgrade()`.
- Full-stack round-trip `upgrade head → downgrade 0007 → upgrade head` passes locally.
- Per-migration round-trip (`upgrade <rev> → downgrade -1 → upgrade <rev>`) passes for each of the 6.
- ORM models in `backend/app/db/models/` are NOT updated to declare `search_vector` (per spec FR-2 invariant). Verified by `grep -r 'search_vector' backend/app/db/models/` returning no matches.
- **Test file ownership:** `backend/tests/integration/test_search_vector_migrations.py` is created in this story (asserts AC-7 + AC-8); the file covers both the full-stack and per-migration round-trip shapes.

---

### Story 1.2 — `?q=` query parameter on 6 searchable list endpoints

**Outcome:** `GET /api/v1/{clusters,studies,query-sets,query-templates,judgment-lists,conversations}` accept `?q=<text>` (≥2 chars, ≤200 chars). Filter-only FTS — no `ts_rank` re-ordering; existing `created_at DESC, id DESC` ordering preserved. `?q=` combines with all existing filters via AND. `X-Total-Count` matches the filtered set.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/_fts.py` | Shared helper: `def fts_predicate(q: str | None) -> ColumnElement \| None` returning `sa.text("search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q)` or `None`. Imported by each `list_*` / `count_*` repo function. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py:173-198` | Add `q: Annotated[str \| None, Query(min_length=2, max_length=200)] = None` to `list_clusters`; thread to `repo.list_clusters(q=q)` + `repo.count_clusters(q=q)`. |
| `backend/app/api/v1/studies.py:262-298` | Same on `list_studies`. |
| `backend/app/api/v1/query_sets.py:148-171` | Same on `list_query_sets`. |
| `backend/app/api/v1/query_templates.py:155-178` | Same on `list_query_templates`. |
| `backend/app/api/v1/judgments.py:326-345` | Same on `list_judgment_lists_endpoint` (also add `?since=` per Story 1.5). |
| `backend/app/api/v1/conversations.py:106-144` | Same on `list_conversations_endpoint` (also add `?since=` per Story 1.5). |
| `backend/app/db/repo/cluster.py:33-69` | Add `q: str | None = None` kwarg to `list_clusters` and `count_clusters`. Apply `fts_predicate(q)` via SQL AND. |
| `backend/app/db/repo/study.py` | Same on `list_studies` + `count_studies`. |
| `backend/app/db/repo/query_set.py` | Same. |
| `backend/app/db/repo/query_template.py` | Same. |
| `backend/app/db/repo/judgment_list.py` | Same. |
| `backend/app/db/repo/conversation.py` | Same. |

**Endpoints** (no shape change; `?q=` added as optional query param to existing endpoints)

| Method | Path | New param | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/clusters` | `?q` (str, 2–200) | unchanged `ClusterListResponse` + `X-Total-Count` | `VALIDATION_ERROR` (422) |
| `GET` | `/api/v1/studies` | `?q` (str, 2–200) | unchanged `StudyListResponse` | `VALIDATION_ERROR` |
| `GET` | `/api/v1/query-sets` | `?q` (str, 2–200) | unchanged `QuerySetListResponse` | `VALIDATION_ERROR` |
| `GET` | `/api/v1/query-templates` | `?q` (str, 2–200) | unchanged `QueryTemplateListResponse` | `VALIDATION_ERROR` |
| `GET` | `/api/v1/judgment-lists` | `?q` (str, 2–200) | unchanged `JudgmentListListResponse` | `VALIDATION_ERROR` |
| `GET` | `/api/v1/conversations` | `?q` (str, 2–200) | unchanged `ConversationsListResponse` | `VALIDATION_ERROR` |

**Key interfaces**

```python
# backend/app/db/repo/_fts.py
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

def fts_predicate(q: str | None) -> TextClause | None:
    """Build the FTS WHERE clause for ?q= or return None when not active.

    Uses `plainto_tsquery('english', :q)` which is injection-safe (no operator
    parsing). Returns None when q is None or empty.
    """
    if not q:
        return None
    return text("search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q)

# Each list_*/count_* repo function adds:
async def list_clusters(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
) -> Sequence[Cluster]: ...
```

**Pydantic schemas**

No new schemas; `?q=` is a query parameter, not a body field.

**Tasks**

1. Create `backend/app/db/repo/_fts.py` with `fts_predicate(q)`.
2. For each of the 6 repos, add `q: str | None = None` kwarg to `list_*` + `count_*`. Apply `fts_predicate(q)` via SQL AND alongside existing filters.
3. For each of the 6 routers, add `q: Annotated[str | None, Query(min_length=2, max_length=200)] = None` and thread to the repo. The Pydantic min/max constraint produces `VALIDATION_ERROR` on under/over-length input.
4. Verify `X-Total-Count` matches the filtered set on each endpoint (the existing `count_*` shape already takes the same kwargs).
5. **Commit boundary**: one commit covering all 6 routers + repos + the shared helper.

**Definition of Done**
- All 6 endpoints accept `?q=` and return filtered results.
- Under-length / over-length `?q=` produces `VALIDATION_ERROR` (422) with the canonical envelope.
- `X-Total-Count` matches the filtered set on each endpoint.
- No `ts_rank` in the repo layer (`grep -r 'ts_rank' backend/app/db/repo/` returns no matches).
- **Test file ownership:** integration files `test_{clusters,studies,query_sets,query_templates,judgment_lists,conversations}_fts.py` are created in this story; contract assertions for the under/over-length 422 envelope are added to existing `test_<resource>_api_contract.py` files (under §3.3).

---

### Story 1.3 — `?sort=<col>:<dir>` with sort-aware cursor on 7 sortable endpoints

**Outcome:** `GET /api/v1/{clusters,studies,query-sets,query-templates,judgment-lists,proposals}` and `GET /api/v1/judgment-lists/{id}/judgments` accept `?sort=<col>:<asc|desc>` Literal values per spec §8.4. The cursor encoding becomes sort-aware: `(<sort_col_value>, id)` when `?sort=` is non-default, `(created_at, id)` when absent or `?sort=created_at:desc`. Repo applies a keyset predicate matching the active ORDER BY. Trials endpoint is unchanged (preserves existing combined-wire `TrialSortKey`).

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/_sort.py` | Shared helpers: `def parse_sort(s: str \| None, allowed: dict[str, ColumnElement]) -> tuple[ColumnElement, bool] \| None` (returns `(column, is_desc)`); `def sort_aware_keyset(...)` that builds the `(value, id)` keyset predicate matching the active ORDER BY. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add new `Literal[...]` symbols: `StudySortKey`, `ClusterSortKey`, `QuerySetSortKey`, `QueryTemplateSortKey`, `JudgmentListSortKey`, `ProposalSortKey`, `JudgmentRowSortKey`. Each Literal lists the full `<col>:asc / <col>:desc` cross-product. Add `# Values must match ui/src/lib/enums.ts <SYMBOL>` comment above each. |
| `backend/app/api/v1/clusters.py:173-198` | Add `sort: Annotated[ClusterSortKey \| None, Query()] = None` to `list_clusters`. Thread to repo. Update `_decode_cursor` to be sort-aware: when `sort` is non-default, cursor value is the sort column's value (string for `name` / `environment`; datetime for `created_at`). |
| `backend/app/api/v1/studies.py:262-298` | Same on `list_studies` with `StudySortKey`. |
| `backend/app/api/v1/query_sets.py:148-171` | Same with `QuerySetSortKey`. |
| `backend/app/api/v1/query_templates.py:155-178` | Same with `QueryTemplateSortKey`. |
| `backend/app/api/v1/judgments.py:326-345` | Same on `list_judgment_lists_endpoint` with `JudgmentListSortKey`. |
| `backend/app/api/v1/judgments.py:383-` | Add `sort: Annotated[JudgmentRowSortKey \| None, Query()] = None` to `list_judgments_endpoint`. Thread to repo. |
| `backend/app/api/v1/proposals.py:329-359` | Add `sort: Annotated[ProposalSortKey \| None, Query()] = None` to `list_proposals_endpoint`. Thread to repo. |
| `backend/app/db/repo/cluster.py:33-69` | Add `sort: str \| None = None`. When set, ORDER BY the sort column (DESC/ASC + `NULLS LAST/FIRST`) and apply matching keyset predicate. When absent, preserve `created_at DESC, id DESC`. |
| `backend/app/db/repo/study.py` | Same. |
| `backend/app/db/repo/query_set.py` | Same. |
| `backend/app/db/repo/query_template.py` | Same. |
| `backend/app/db/repo/judgment_list.py` | Same. |
| `backend/app/db/repo/judgment.py` (per-row list) | Add `sort: str \| None = None` to `list_judgments`. Keyset predicate on `created_at` / `rating` / `source`. |
| `backend/app/db/repo/proposal.py` | Same. |
| `ui/src/lib/enums.ts` | Add 7 new `as const` arrays: `STUDY_SORT_VALUES`, `CLUSTER_SORT_VALUES`, `QUERY_SET_SORT_VALUES`, `QUERY_TEMPLATE_SORT_VALUES`, `JUDGMENT_LIST_SORT_VALUES`, `JUDGMENT_ROW_SORT_VALUES`, `PROPOSAL_SORT_VALUES`. Each carries the `// Values must match backend/app/api/v1/schemas.py <Symbol>` source-of-truth comment. |

**Per-endpoint sort Literal allowlists**

| Endpoint | `Literal[...]` values |
|---|---|
| `/api/v1/clusters?sort=` | `name:asc \| name:desc \| created_at:asc \| created_at:desc \| environment:asc \| environment:desc` |
| `/api/v1/studies?sort=` | `name:asc \| name:desc \| created_at:asc \| created_at:desc \| completed_at:asc \| completed_at:desc \| best_metric:asc \| best_metric:desc \| status:asc \| status:desc` |
| `/api/v1/query-sets?sort=` | `name:asc \| name:desc \| created_at:asc \| created_at:desc` |
| `/api/v1/query-templates?sort=` | `name:asc \| name:desc \| created_at:asc \| created_at:desc \| engine_type:asc \| engine_type:desc \| version:asc \| version:desc` |
| `/api/v1/judgment-lists?sort=` | `name:asc \| name:desc \| created_at:asc \| created_at:desc \| status:asc \| status:desc` |
| `/api/v1/proposals?sort=` | `created_at:asc \| created_at:desc \| status:asc \| status:desc \| pr_state:asc \| pr_state:desc` |
| `/api/v1/judgment-lists/{id}/judgments?sort=` | `created_at:asc \| created_at:desc \| rating:asc \| rating:desc \| source:asc \| source:desc` |

**Key interfaces**

```python
# backend/app/db/repo/_sort.py
from dataclasses import dataclass
from sqlalchemy.sql.elements import ColumnElement

@dataclass(frozen=True)
class ParsedSort:
    column: ColumnElement
    desc: bool
    col_name: str  # e.g. "name", "created_at"

def parse_sort(s: str | None, allowed: dict[str, ColumnElement]) -> ParsedSort | None:
    """Parse '<col>:<asc|desc>'; return None when s is None or empty.

    `allowed` maps col_name → SQLAlchemy column. Unknown col returns None
    (Pydantic Literal already rejected unknown values upstream).
    """
    if not s:
        return None
    col_name, _, dir_str = s.partition(":")
    col = allowed.get(col_name)
    if col is None:
        return None
    return ParsedSort(column=col, desc=(dir_str == "desc"), col_name=col_name)

# In each list_* repo function:
async def list_clusters(
    db: AsyncSession,
    *,
    cursor: tuple[Any, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> Sequence[Cluster]: ...
```

**Cursor encoding under `?sort=`:**
- Absent or `created_at:desc`: cursor is `(created_at, id)` — existing shape.
- Non-default (e.g., `name:asc`): cursor is `(name_value, id)` — the value half is the sort column's value at the last row of the previous page.
- The opaque base64-JSON wire shape stays `[<value>, <id>]`; only the value's type varies.
- The encode helper uses `isoformat()` for datetime values, raw value for str/int/float, `null` for nullable columns.

**Null-aware keyset predicates** (required when the sort column is nullable, e.g., `studies.completed_at`, `studies.best_metric`, `proposals.pr_state`):
- The `ORDER BY` clause uses explicit `NULLS FIRST` (on `:asc`) or `NULLS LAST` (on `:desc`) so null rows have a stable sort position.
- The keyset predicate must mirror the null position. The `_sort.py` helper's `sort_aware_keyset(parsed_sort, cursor_value, cursor_id)` produces SQL like:
  - `:desc` with NULLS LAST + cursor_value is non-null:
    `WHERE (<col> < :cursor_value OR (<col> = :cursor_value AND id < :cursor_id) OR <col> IS NULL)`
  - `:desc` with NULLS LAST + cursor_value IS NULL:
    `WHERE (<col> IS NULL AND id < :cursor_id)` (we've already iterated past all non-null rows)
  - `:asc` with NULLS FIRST + cursor_value IS NULL:
    `WHERE (<col> IS NOT NULL OR (<col> IS NULL AND id < :cursor_id))`
  - `:asc` with NULLS FIRST + cursor_value non-null:
    `WHERE (<col> > :cursor_value OR (<col> = :cursor_value AND id < :cursor_id))` (NULLS already iterated)
- Integration test cases (per resource with nullable sort columns):
  - Page 1's last row has a null `completed_at`; fetch page 2 via cursor; assert no duplicate rows + no missed rows.
  - Same shape for `:asc` direction.

**Tasks**

1. Create `backend/app/db/repo/_sort.py` with `parse_sort` + helpers.
2. Add the 7 sort Literals to `schemas.py` with source-of-truth comments.
3. Add the matching 7 `as const` arrays to `ui/src/lib/enums.ts` with reverse comments.
4. For each of the 7 sortable endpoints, modify the router to accept `sort: Annotated[...SortKey | None, Query()] = None`.
5. For each of the 7 list endpoints' repos, accept `sort: str | None` and:
   - Build the `allowed` dict mapping `col_name → Model.<column>`.
   - Call `parse_sort(sort, allowed)` to get `ParsedSort` or `None`.
   - If `None`, preserve existing `ORDER BY created_at DESC, id DESC` and existing cursor.
   - If `ParsedSort`, apply `ORDER BY <col> <DIR> NULLS <FIRST|LAST>, id DESC` and the sort-aware keyset predicate.
6. Update the router's `_encode_cursor` / `_decode_cursor` helpers to accept the active sort column and encode the appropriate value type. Trials endpoint already does this — use it as the precedent ([`backend/app/api/v1/studies.py:88-109`](../../../../backend/app/api/v1/studies.py)).
7. **Commit boundaries**: one commit for the shared helpers (`_sort.py` + schemas Literals + enums.ts arrays); one commit per endpoint family (e.g., clusters + studies + query-sets together; templates + judgment-lists + proposals together; judgments-per-list separately). Three to four commits.

**Definition of Done**
- All 7 endpoints accept `?sort=<col>:<dir>` and respond with `VALIDATION_ERROR` 422 on unknown values.
- Each Literal is paired with an `enums.ts` `as const` array carrying the `// Values must match …` comment; `scripts/ci/verify_enum_source_of_truth.sh` passes.
- Trials endpoint is unchanged (regression-asserted in `test_studies_api_contract.py`).
- **Test file ownership:** integration files `test_{clusters,studies,query_sets,query_templates,judgment_lists,proposals}_sort_pagination.py` (6 files) + `test_judgments_row_sort.py` (1 file) are created in this story; each asserts no duplicates + no skips across multi-page cursor traversal under a non-default `?sort=`. Contract assertions for the unknown-`?sort=` 422 envelope added to existing `test_<resource>_api_contract.py` files (under §3.3).

---

### Story 1.4 — `?engine_type=` and `?environment=` filter params on clusters + templates

**Outcome:** `GET /api/v1/clusters` accepts `?engine_type=elasticsearch|opensearch` and `?environment=prod|staging|dev`. `GET /api/v1/query-templates` accepts `?engine_type=`. All threaded to the repo + count for `X-Total-Count` accuracy.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py:173-198` | Add `engine_type: Annotated[EngineTypeWire \| None, Query()] = None` and `environment: Annotated[Environment \| None, Query()] = None`. Thread to repo. |
| `backend/app/api/v1/query_templates.py:155-178` | Add `engine_type: Annotated[EngineTypeWire \| None, Query()] = None`. Thread to repo. |
| `backend/app/db/repo/cluster.py:33-69` | Add `engine_type: str \| None = None`, `environment: str \| None = None` to `list_clusters` + `count_clusters`. Apply via SQL AND on existing columns. |
| `backend/app/db/repo/query_template.py` | Same for `engine_type`. |

**Endpoints**

| Method | Path | New params | Notes |
|---|---|---|---|
| `GET` | `/api/v1/clusters` | `?engine_type`, `?environment` | Reuses existing `EngineTypeWire` + `Environment` Literals |
| `GET` | `/api/v1/query-templates` | `?engine_type` | Reuses existing `EngineTypeWire` Literal |

**Tasks**

1. Add the new query params to the two routers.
2. Thread to the repos + count functions.
3. **Commit boundary**: one commit covering both routers + repos.

**Definition of Done**
- Both endpoints filter correctly via SQL AND alongside other active filters.
- `X-Total-Count` matches the filtered set.
- Unknown values produce `VALIDATION_ERROR` (Literal type rejection — already handled by FastAPI).
- **Test file ownership:** assertions added to `test_clusters_fts.py` + `test_query_templates_fts.py` (created in Story 1.2) for engine/environment filter combinations; contract assertions for unknown-value 422 added to existing `test_clusters_api_contract.py` + `test_query_templates_api_contract.py` files (NOT query-sets — that resource gets no `?engine_type=` filter). No new test files.

---

### Story 1.5 — `?template_id=` on proposals + `?since=` on judgment-lists & conversations

**Outcome:** `GET /api/v1/proposals` accepts `?template_id=<uuid>` (filters by `proposals.template_id` FK). `GET /api/v1/judgment-lists` and `GET /api/v1/conversations` accept `?since=<iso8601>` (closes pre-existing api-conventions.md drift — every list endpoint MUST accept `?since=`).

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py:329-359` | Add `template_id: Annotated[UUID \| None, Query()] = None` (import `uuid.UUID`) to `list_proposals_endpoint`. FastAPI auto-validates the UUID at the boundary — invalid strings produce `RequestValidationError` → canonical `VALIDATION_ERROR` envelope. Thread the stringified UUID to the repo. No FK-empty fallback. |
| `backend/app/db/repo/proposal.py` | Add `template_id: str \| None = None` to `list_proposals_paginated` + `count_proposals`. Apply via SQL AND on `Proposal.template_id`. |
| `backend/app/api/v1/judgments.py:326-345` | Add `since: Annotated[datetime \| None, Query()] = None` to `list_judgment_lists_endpoint`. Thread to repo. |
| `backend/app/db/repo/judgment_list.py` | Add `since: datetime \| None = None` to `list_judgment_lists` + `count_judgment_lists`. Apply via SQL AND. |
| `backend/app/api/v1/conversations.py:106-144` | Add `since: Annotated[datetime \| None, Query()] = None`. Thread to repo. |
| `backend/app/db/repo/conversation.py` | Add `since: datetime \| None = None` to `list_conversations_with_preview_data` + `count_conversations`. Apply via SQL AND. |

**Tasks**

1. Add `?template_id=` to proposals router + repo.
2. Add `?since=` to judgment-lists router + repo.
3. Add `?since=` to conversations router + repo.
4. **Commit boundary**: one commit covering all three.

**Definition of Done**
- `?template_id=` filter returns the expected subset.
- `?since=` on judgment-lists and conversations filters by `created_at >= since`.
- Invalid UUID on `?template_id=` produces `VALIDATION_ERROR`.
- `X-Total-Count` matches the filtered set on all three.
- **Test file ownership:** new file `backend/tests/integration/test_proposals_template_filter.py` is created in this story for `?template_id=`; `?since=` assertions added to `test_judgment_lists_fts.py` + `test_conversations_fts.py` (created in Story 1.2); contract assertions for invalid UUID added to existing `test_digest_proposal_api_contract.py`.

### Epic 1 — Phase gate (hard stop before Epic 2)

- [ ] All 6 migrations are committed and round-trip clean.
- [ ] All 6 `?q=` endpoints respond correctly to integration tests.
- [ ] All 7 `?sort=` endpoints respond correctly with sort-aware cursor pagination.
- [ ] All 4 new filter params (`?engine_type=`, `?environment=`, `?template_id=`, the `?since=` additions) work.
- [ ] Contract tests for `VALIDATION_ERROR` on bad input pass.
- [ ] GPT-5.5 phase-gate review on cumulative Epic 1 diff (per `.claude/skills/impl-execute/SKILL.md` Step 5b).
- [ ] `make backend-fmt && make backend-lint && make backend-typecheck && make test-unit` pass.

---

## Epic 2 — DataTable primitive + co-located helpers

**Goal:** Build the headless DataTable primitive in 13 small stories. By the end of Epic 2 the primitive exists, is fully tested at the component layer, and has zero consumers (no migrated tables yet — that's Epic 3).

### Story 2.1 — Add `@tanstack/react-table` dep + scaffold primitive shell

**Outcome:** New npm dep `@tanstack/react-table@~8.21.3` installed. `ui/src/components/common/data-table.tsx` exists as a minimal shell that renders a `<Table>` with `<TableHeader>` / `<TableBody>` from `@/components/ui/table`, accepts a `columns` array (TanStack `ColumnDef[]`), accepts `data` + `isLoading` + `totalCount` + `next_cursor` + `has_more` props, and renders rows. No sort, no filter, no search yet — those land in 2.2–2.12.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table.tsx` | The primitive — currently just renders rows + paginator shell |
| `ui/src/components/common/data-table-toolbar.tsx` | Toolbar slot (empty for now) |
| `ui/src/components/common/data-table-empty.tsx` | Empty-state shapes (3 variants land in 2.7) |
| `ui/src/components/common/types.ts` | Shared types: `DataTableProps<T>`, `DataTableColumnDef<T>`, `DataTableFilter`, `DataTableSort`, etc. |

**Modified files**

| File | Change |
|---|---|
| `ui/package.json` | Add `"@tanstack/react-table": "~8.21.3"` to `dependencies`. Run `pnpm install` to update lockfile. |
| `ui/pnpm-lock.yaml` | Updated automatically by `pnpm install`. |

**Key interfaces**

```typescript
// ui/src/components/common/types.ts
import type { ColumnDef as TanstackColumnDef } from '@tanstack/react-table';
import type { GlossaryKey } from '@/lib/glossary';

export interface DataTableEnumFilter {
  kind: 'enum';
  wireValues: readonly string[];
  sourceOfTruth: string; // backend allowlist citation, e.g., "backend/app/api/v1/schemas.py StudyStatusWire"
  label?: (value: string) => string;
}

export interface DataTableFkSelectFilter {
  kind: 'fk-select';
  useOptions: () => { data: { id: string; label: string }[]; isLoading: boolean };
  sourceOfTruth: string; // backend FK column citation, e.g., "DB FK on proposals.template_id"
  placeholder: string;
}

export type DataTableFilter = DataTableEnumFilter | DataTableFkSelectFilter;

// Intersection rather than `interface extends Omit<union>` — TanStack Table's
// ColumnDef is a discriminated union and `interface extends Omit<…>` erases the
// narrowing and breaks `pnpm typecheck`. Intersection preserves the union.
export type DataTableColumnDef<T extends { id: string }, TValue = unknown> = TanstackColumnDef<T, TValue> & {
  id: string;
  sortable?: boolean;
  sortKey?: string;
  firstClickDirection?: 'asc' | 'desc';
  // Constrains the set of allowed sort directions for the column. Default is
  // `['asc', 'desc']` (full three-state cycle). Set to `['asc']` or `['desc']`
  // for columns where the backend Literal only accepts one direction (e.g.,
  // trials.optuna_trial_number has `optuna_trial_number_asc` in TrialSortKey
  // but no `_desc` value). When the cycle would advance to an unsupported
  // direction, the primitive skips it (asc-only: click cycles unsorted → asc → unsorted).
  sortDirections?: readonly ('asc' | 'desc')[];
  filter?: DataTableFilter;
  tooltipKey?: GlossaryKey;
  hideable?: boolean;
  sticky?: boolean;
};

export interface BulkAction {
  label: string;
  onClick: (selectedIds: string[], clearSelection: () => void) => void;
  variant?: 'default' | 'destructive';
  testid?: string;
}

// Note: T is constrained to { id: string } so every consumer's summary row has
// a stable id field. Internally DataTable passes getRowId: (row) => row.id to
// useReactTable so selection, keyboard activation, and row testids align with
// backend UUIDs rather than zero-based array indices.
export interface DataTableProps<T extends { id: string }> {
  tableId: string;
  columns: readonly DataTableColumnDef<T>[];
  data: readonly T[];
  isLoading: boolean;
  isError: boolean;
  totalCount?: number;
  has_more: boolean;
  next_cursor: string | null;
  searchable?: boolean;
  selectable?: boolean;
  keyboardNav?: boolean;
  defaultPageSize?: number;
  onRowActivate?: (rowId: string) => void;
  onSelectionChange?: (selectedIds: string[]) => void;
  bulkActions?: readonly BulkAction[];
  emptyStateNoRows: { title: string; message: string; primaryCta?: React.ReactNode };
  emptyStateNoMatch?: { title?: string; message?: string };
  // Testid preservation — required so existing E2E specs against `studies-table`,
  // `proposals-table`, etc. keep passing without rewrites. Row testids vary by
  // resource (`study-row-<id>` for studies, `row-<id>` for queries-table — no
  // global pattern fits), so the consumer supplies them explicitly.
  tableTestId: string;            // e.g., "studies-table"
  rowTestId: (row: T) => string;  // e.g., (r) => `study-row-${r.id}`
  // Controlled URL state (per Story 2.6) — supplied by the consumer's
  // useDataTableUrlState() hook so the consumer's query hook can refetch
  // when URL state changes.
  urlState: import('@/hooks/use-data-table-url-state').DataTableUrlState;
  setSort: (sort: string | null) => void;
  setFilter: (column: string, value: string | null) => void;
  setQ: (q: string | null) => void;
  setCursor: (cursor: string | null) => void;
  setPageSize: (pageSize: number) => void;
  pageSizeOptions?: readonly number[]; // default [50, 100, 200]
}
```

**Tasks**

1. Run `cd ui && pnpm add @tanstack/react-table@~8.21.3` and commit `package.json` + `pnpm-lock.yaml`.
2. Create `ui/src/components/common/types.ts` with the interfaces above.
3. Create `ui/src/components/common/data-table.tsx` minimal shell: takes the props, uses `useReactTable({ data, columns, getCoreRowModel })`, renders `<Table>` with header + rows. No sort/filter/search wiring yet.
4. Create `data-table-toolbar.tsx` and `data-table-empty.tsx` as empty shells (just default-exported components that render `null`).
5. Write `ui/src/__tests__/components/common/data-table.test.tsx` minimal test: renders rows when `data` has rows, renders nothing when empty (full empty-state shapes land in 2.7).
6. **Commit boundary**: one commit.

**Definition of Done**
- `pnpm install` succeeds; `pnpm test` passes; `pnpm typecheck` clean.
- Vitest test renders 3 mock rows and asserts they appear.
- The shell does not consume `useRouter` yet (URL state lands in 2.6).

---

### Story 2.2 — Sortable column headers + URL sort serialization (FR-4)

**Outcome:** Clicking a sortable column header cycles `unsorted → <firstClickDirection> → <opposite> → unsorted`. The chevron icon (lucide-react `<ChevronUp />` / `<ChevronDown />`) reflects state. URL serializes as `?sort=<col>:<dir>` (omitted when unsorted). On initial mount, the primitive reads `?sort=` from the URL and applies it.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-sort-header.tsx` | Sub-component rendered inside `<TableHead>` for sortable columns. Owns the click handler + chevron rendering. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table.tsx` | Use TanStack `state.sorting` driven by URL `?sort=`. Wire `column.sortable` + `column.firstClickDirection` + `column.sortKey`. |
| `ui/src/components/common/types.ts` | Already includes `sortable`, `sortKey`, `firstClickDirection`. No change. |

**Tasks**

1. DataTable receives `urlState.sort` + `setSort` as props (controlled — established in Story 2.6 but the type already accepts them per the Story 2.1 props extension). For Stories 2.2–2.5, tests can supply mocked `urlState` / setter props directly; the `useDataTableUrlState` hook itself lands in Story 2.6.
2. Map TanStack `state.sorting` from incoming `urlState.sort` prop on every render.
3. Render sortable column headers via `<DataTableSortHeader>` with the cycle logic. Cycle respects `column.firstClickDirection` AND `column.sortDirections`:
   - `sortDirections = ['asc', 'desc']` (default): unsorted → first → opposite → unsorted.
   - `sortDirections = ['asc']`: unsorted → asc → unsorted (skip desc).
   - `sortDirections = ['desc']`: unsorted → desc → unsorted (skip asc).
4. On click, call `props.setSort(newSortValue | null)` — DataTable itself does NOT call `router.replace`; the prop setter (originating in `useDataTableUrlState`) does.
5. Write tests asserting:
   - `firstClickDirection='asc'`, default sortDirections → click cycles to `asc`, then `desc`, then unsorted.
   - `firstClickDirection='desc'`, default → click cycles to `desc`, then `asc`, then unsorted.
   - `sortDirections=['asc']` → click cycles only between unsorted and asc.
   - `setSort` mock is called with the expected string.
6. **Commit boundary**: one commit.

**Definition of Done**
- Vitest cases pass (sortable=true, sortable=false, firstClickDirection override).
- URL `?sort=` round-trips correctly on mount.
- AC-1 acceptance criterion implementable.

---

### Story 2.3 — Filter chips (enum + fk-select) (FR-5)

**Outcome:** Column configs with `filter: { kind: 'enum', wireValues, sourceOfTruth }` render a chip row in the toolbar; `{ kind: 'fk-select', useOptions, sourceOfTruth, placeholder }` renders a native `<select>` dropdown. Clicking a chip sets URL `?<column.id>=<wireValue>`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-filter-chips.tsx` | Renders an enum-filter chip row for one column |
| `ui/src/components/common/data-table-fk-select.tsx` | Renders an fk-select `<select>` for one column |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-toolbar.tsx` | Renders one filter-chips row / fk-select per filterable column |

**Tasks**

1. Implement `<DataTableFilterChips>` for `kind: 'enum'`: maps `wireValues` to chips with an "all" chip; clicking calls `props.setFilter(column, value | null)`.
2. Implement `<DataTableFkSelect>` for `kind: 'fk-select'`: calls `useOptions()` hook, renders `<select>` with `{id, label}` options; "all" option uses empty value; calls `props.setFilter(column, id | null)`.
3. **No direct router call** — the primitive only calls the controlled `setFilter` prop. URL writes happen inside `useDataTableUrlState` (Story 2.6).
4. Add disabled state when `props.isLoading` (the consumer's `query.isPending`).
5. Tests:
   - Enum chip: click → mocked `setFilter` called with `(column, value)`.
   - Fk-select: loading state shows "(loading…)"; data state renders options; selection calls `setFilter`.
6. **Commit boundary**: one commit.

**Definition of Done**
- Tests pass.
- Both filter kinds render correctly via the existing testid pattern (`data-testid="filter-chip-<column>-<value>"` for chips, `data-testid="fk-select-<column>"` for selects).

---

### Story 2.4 — Debounced text-search input (FR-6)

**Outcome:** When `props.searchable === true`, a text input renders in the toolbar with placeholder "Search…". 300ms debounce. Frontend Zod schema rejects `<2 chars`. URL serializes `?q=<text>`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-search.tsx` | Search input sub-component |
| `ui/src/hooks/use-debounced-value.ts` | Generic debounce hook (`useDebouncedValue(value, delayMs)`) |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-toolbar.tsx` | Conditionally renders `<DataTableSearch>` when `searchable` |

**Tasks**

1. Implement `useDebouncedValue(value: string, delayMs: number): string` with `useEffect` + cleanup.
2. Implement `<DataTableSearch>` with Zod schema `z.string().min(2).max(200)`. On debounced value change, call `props.setQ(value | null)`.
3. Show "(N results)" indicator next to input when `props.totalCount` is known and search is active.
4. **No direct router call** — calls the controlled `setQ` prop. URL writes happen inside `useDataTableUrlState` (Story 2.6).
5. Tests:
   - Type "p" (1 char) from empty initial state → no `setQ` call after debounce.
   - Type "pr" (2 chars) → mocked `setQ('pr')` called after 300ms.
   - **Edit `product` down to `p` (transitions from valid → under-length while `?q=product` is active)** → mocked `setQ(null)` called after debounce; URL drops `?q=`. The implementation calls `setQ(null)` whenever the debounced value drops below 2 chars AND there was a prior non-null `q`; this prevents stale `?q=product` from sticking when the user partially clears the input.
   - Clear input entirely → mocked `setQ(null)` called.
6. **Commit boundary**: one commit.

**Definition of Done**
- Vitest debounce timer tests pass (using `vi.useFakeTimers()`).
- AC-3 acceptance criterion implementable.

---

### Story 2.5 — Total-count display (FR-7)

**Outcome:** Toolbar's top-right slot reads "Showing 1–N of M" on first page (cursor stack length 1) or "Showing N rows (of M matching)" on subsequent pages, per FR-7's cursor-paginator-honest wording.

**New files**

None — inline in `data-table-toolbar.tsx`.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-toolbar.tsx` | Render the total-count indicator computed from `totalCount` + `rowsRendered` + cursor stack length |
| `ui/src/components/common/data-table.tsx` | Pass `totalCount` + `rowsRendered` + cursor stack info to toolbar |

**Tasks**

1. Add `rowsRendered = data.length` derivation + cursor stack length state (lives in DataTable, lifted from internal `useState<string | undefined[]>([undefined])`).
2. Render the two display forms per FR-7.
3. Tests:
   - First page: "Showing 1–N of M".
   - After clicking Next: "Showing N rows (of M matching)".
   - `totalCount === 0`: "No matching rows".
4. **Commit boundary**: one commit.

**Definition of Done**
- AC-14 implementable.

---

### Story 2.6 — `useDataTableUrlState` hook with push/replace history (FR-8) — **lifted to the consumer**

**Outcome:** A reusable hook that owns the URL-state contract: cursor uses `router.push()`, filter/sort/q use `router.replace()`. Cursor resets on filter/sort/q change. Hydrates from URL on mount. **The hook lives at the page-level consumer**, not inside DataTable, so the consumer's TanStack Query hook receives the URL state and refetches accordingly. DataTable becomes a **controlled component** receiving `urlState` + setters as props (per spec §4 "Consumer-supplied data" principle).

**New files**

| File | Purpose |
|---|---|
| `ui/src/hooks/use-data-table-url-state.ts` | The hook |
| `ui/src/__tests__/hooks/use-data-table-url-state.test.ts` | Vitest covering hydration + history strategy |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table.tsx` | Refactor: remove the ad-hoc URL handling added in 2.2 / 2.3 / 2.4 (which was a stepping-stone). Receive `urlState` and `onUrlStateChange` (or specific setters) as props. Internal renderers (sort headers, filter chips, search input, paginator) call the prop setters; they no longer read/write the URL directly. |
| `ui/src/components/common/types.ts` | Add `urlState` + setter props to `DataTableProps<T>` (see Key interfaces below). |

**Key interfaces**

```typescript
// ui/src/hooks/use-data-table-url-state.ts
import type { DataTableColumnDef } from '@/components/common/types';

export interface DataTableUrlState {
  sort: string | null;
  filters: Record<string, string>;
  q: string | null;
  cursor: string | null;
  pageSize: number;
}

export interface DataTableUrlStateApi extends DataTableUrlState {
  setSort: (sort: string | null) => void;
  setFilter: (column: string, value: string | null) => void;
  setQ: (q: string | null) => void;
  setCursor: (cursor: string | null) => void;
  setPageSize: (pageSize: number) => void;
  clearCursor: () => void;
  // Clears every column-filter param AND `?q=`; preserves sort + pageSize.
  // This is the action wired to the FR-9 "no-rows-match" empty state's
  // "Clear filters" button — search-only empty states must clear `q` too,
  // otherwise the button is a no-op when the only active matcher is search.
  clearAllMatchers: () => void;
  // Active when at least one column-filter param OR `?q=` is non-empty.
  // Drives FR-9's `no-rows-match` vs `no-rows-exist` branching.
  anyMatcherActive: boolean;
}

// Takes `columns` so the hook knows which URL query params are filter keys
// (vs. unrelated route params). Only columns with `filter` config are parsed;
// other params pass through unchanged.
export function useDataTableUrlState<T extends { id: string }>(
  tableId: string,
  columns: readonly DataTableColumnDef<T>[],
  options?: { defaultPageSize?: number; pageSizeOptions?: readonly number[] },
): DataTableUrlStateApi;

// In ui/src/components/common/types.ts — DataTableProps<T> gains:
export interface DataTableProps<T extends { id: string }> {
  // ... existing props ...
  urlState: DataTableUrlState;
  setSort: (sort: string | null) => void;
  setFilter: (column: string, value: string | null) => void;
  setQ: (q: string | null) => void;
  setCursor: (cursor: string | null) => void;
  // ... etc
}
```

**Consumer wiring pattern** (used by every Epic 3 page migration):

```typescript
// ui/src/app/studies/page.tsx (illustrative)
function StudiesPageInner() {
  const urlState = useDataTableUrlState('studies', studiesColumns, { defaultPageSize: 50 });
  // The query hook reads URL state and refetches on any change.
  const query = useStudies({
    status: urlState.filters['status'],
    sort: urlState.sort,
    q: urlState.q,
    cursor: urlState.cursor,
    limit: urlState.pageSize, // controlled — DataTable's page-size selector mutates urlState.pageSize
  });
  return (
    <DataTable<StudySummary>
      tableId="studies"
      columns={studiesColumns}
      data={query.data?.data ?? []}
      totalCount={query.data?.totalCount}
      has_more={query.data?.has_more ?? false}
      next_cursor={query.data?.next_cursor ?? null}
      isLoading={query.isPending}
      isError={query.isError}
      searchable
      urlState={urlState}
      setSort={urlState.setSort}
      setFilter={urlState.setFilter}
      setQ={urlState.setQ}
      setCursor={urlState.setCursor}
      setPageSize={urlState.setPageSize}
      emptyStateNoRows={{ title: "No studies yet", message: "Create a study to begin.", primaryCta: <Button>Create study</Button> }}
    />
  );
}
```

**Tasks**

1. Implement the hook. Use `useSearchParams()` for read; `useRouter()` for write.
2. `setSort`, `setFilter`, `setQ` use `router.replace()` AND reset cursor (`?cursor=` dropped from URL).
3. `setCursor` uses `router.push()` for browser-history-stepping support.
4. Refactor `data-table.tsx`: remove internal `useRouter`/`useSearchParams` calls; consume the props. Each event handler in sub-components (sort header click, filter chip click, search debounce, paginator next/prev) now calls the prop setter rather than the router directly.
5. Tests using mocked `useRouter`:
   - Mount with URL `?status=completed&sort=name:asc&q=test&cursor=opaque` → hook state matches.
   - Call `setFilter('status', 'queued')` → mocked `replace` called with new URL minus `cursor=`.
   - Call `setCursor('newopaque')` → mocked `push` called with `cursor=newopaque`.
6. **Commit boundary**: one commit.

**Definition of Done**
- Hook tests pass.
- DataTable refactored to consume the hook.

---

### Story 2.7 — Three empty-state shapes + cursor-pagination wrapping (FR-9 + FR-10)

**Outcome:** Three `<DataTableEmpty>` variants — `no-rows-match`, `no-rows-exist`, `stale-cursor`. DataTable wraps the existing `<CursorPaginator>`. Consumer never imports paginator directly.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-empty.tsx` | Implement 3 variants with primitive-supplied actions for `no-rows-match` (clear filters) and `stale-cursor` (return to first page) |
| `ui/src/components/common/data-table.tsx` | Conditional render of the right empty state based on `data.length === 0` + URL state. Wrap `<CursorPaginator>` at the bottom. |

**Tasks**

1. Implement `<DataTableEmpty kind>` with the three branches per FR-9.
2. Wire conditional rendering in DataTable: check `data.length`, `totalCount`, filter/q/cursor state.
3. Render `<CursorPaginator>` at the bottom with `hasMore`, `onNext`, `onPrev`, `pageSize`, `onPageSizeChange`, `totalCount`.
4. Tests:
   - Empty resource, no filter/q: renders `no-rows-exist` with consumer CTA.
   - Empty result, filter active: renders `no-rows-match` with "Clear filters" button.
   - `data.length === 0` but `totalCount > 0` and cursor in URL: renders `stale-cursor` with "Return to first page" button.
5. **Commit boundary**: one commit.

**Definition of Done**
- AC-15 + AC-2 implementable.

---

### Story 2.8 — Sticky header + tooltip-enabled column headers (FR-11 + FR-12)

**Outcome:** `<TableHeader>` is `position: sticky; top: 0; z-10`. Columns with `column.tooltipKey` render `<InfoTooltip glossaryKey={...} />` next to the header text.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table.tsx` | Add Tailwind sticky classes to `<TableHeader>`; wrap header text in `<span className="inline-flex items-center gap-1">` with `<InfoTooltip>` when `tooltipKey` is set |
| `ui/src/lib/glossary.ts` | Add 6 new keys: `datatable.sort.toggle`, `datatable.search.min_length`, `datatable.total_count`, `datatable.density.toggle`, `datatable.column_visibility`, `datatable.selection.all_on_page` (per spec §11) |

**Tasks**

1. Apply `sticky top-0 bg-background z-10` Tailwind classes to header row.
2. Wire tooltip rendering when `column.tooltipKey` is set.
3. Add 6 glossary entries per spec §11.
4. Tests:
   - Column with `tooltipKey` renders the InfoTooltip; without it doesn't.
   - Glossary parity test extended (existing pattern in `ui/src/__tests__/lib/glossary.test.ts`).
5. **Commit boundary**: one commit.

**Definition of Done**
- AC-12 tooltip cases pass.
- Sticky header visible in browser (verified manually + E2E spec assertion that header element has `position: sticky` computed style).

---

### Story 2.9 — Multi-row selection + bulk-action toolbar (FR-13)

**Outcome:** When `props.selectable === true`, a checkbox column renders at the left. "Select all on page" header checkbox. Bulk-action toolbar lights up when `selectedIds.length >= 1`; renders consumer-supplied actions plus a counter "N selected on this page". Selection clears on cursor move / filter / sort / q change.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-bulk-actions.tsx` | The bulk-action toolbar |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table.tsx` | Add `useState<Set<string>>` for selection; wire native `<input type="checkbox">` cells; clear on URL state change |
| `ui/src/components/common/types.ts` | Add `BulkAction` type: `{ label: string; onClick: (selectedIds: string[]) => void; variant?: 'default' \| 'destructive' }` |

**Tasks**

1. Use **native `<input type="checkbox">`** (Tailwind-styled) rather than introducing a new Radix Checkbox dep. The shadcn Checkbox primitive is NOT in this repo (verified by `ls ui/src/components/ui/`) and adding `@radix-ui/react-checkbox` for one feature would be unjustified scope. Style the input with `accent-primary h-4 w-4 rounded border-border` Tailwind utilities to match the rest of the form surfaces.
2. Add `selectedIds: Set<string>` state inside DataTable.
3. Render checkbox column at index 0 when `props.selectable`.
4. Render header checkbox controlling "select all on page" — checked state derived from `selectedIds.size === data.length && data.length > 0`; indeterminate state via `ref.indeterminate = selectedIds.size > 0 && selectedIds.size < data.length` (manual imperative set inside `useEffect`).
5. Render `<DataTableBulkActions selectedCount actions onClear />` when `selectedIds.size >= 1`.
6. Clear selection on cursor / filter / sort / q change (via `useEffect` watching the URL state).
7. Tests:
   - Click 2 row checkboxes → toolbar shows "2 selected on this page".
   - Click Next page → toolbar disappears, `selectedIds` is empty.
   - Header checkbox toggles all rows on page (uses `indeterminate` for partial selection).
8. **Commit boundary**: one commit.

**Definition of Done**
- AC-10 implementable.

---

### Story 2.10 — Column visibility menu (FR-14)

**Outcome:** Eye-icon dropdown in toolbar lists every `column.hideable !== false`. Toggle persists hidden set to `localStorage` under key `relyloop:datatable:<tableId>:hidden-columns`. Sticky columns are not hideable.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-column-visibility.tsx` | Eye-icon trigger using existing shadcn `<Popover>` + a checkbox list inside |
| `ui/src/hooks/use-local-storage-set.ts` | Generic hook: `useLocalStorageSet(key, defaultValue: string[])` |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-toolbar.tsx` | Render `<DataTableColumnVisibility>` in the toolbar |
| `ui/src/components/common/data-table.tsx` | Apply hidden set via TanStack Table's column visibility state |

**Tasks**

1. Build `<DataTableColumnVisibility>` using the **existing** [`<Popover>`](../../../../ui/src/components/ui/popover.tsx) primitive (already in the repo) + a `<Button variant="outline" size="sm">` trigger with lucide-react `<Eye />` icon. Inside the popover, render a `<div>` with one labeled native `<input type="checkbox">` per hideable column. **Do NOT add `@radix-ui/react-dropdown-menu`** — `<Popover>` covers the use case (verified `ls ui/src/components/ui/` shows `popover.tsx` exists).
2. Implement `useLocalStorageSet(key, defaultValue)` with `useEffect` + try/catch on quota exceeded; returns `{ value: string[], add(id), remove(id), toggle(id) }`.
3. Implement `<DataTableColumnVisibility>` rendering a checkbox per column.
4. Wire hidden state to TanStack Table's `state.columnVisibility`.
5. Tests:
   - Hide a column → localStorage write fires + column disappears.
   - Mount with a localStorage entry → column starts hidden.
   - Sticky column is not in the dropdown.
   - Popover opens on click and closes on outside click (uses existing `<Popover>` shadcn behavior).
6. **Commit boundary**: one commit.

**Definition of Done**
- AC-11 implementable.

---

### Story 2.11 — Density toggle (FR-15)

**Outcome:** Two-position toggle in toolbar (`comfortable` / `compact`). Persists to `localStorage` under `relyloop:datatable:<tableId>:density`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/common/data-table-density-toggle.tsx` | The toggle |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table-toolbar.tsx` | Render `<DataTableDensityToggle>` |
| `ui/src/components/common/data-table.tsx` | Apply `py-3 px-4` / `py-1.5 px-3` Tailwind classes to cells based on density |

**Tasks**

1. Implement the toggle.
2. Apply Tailwind classes conditionally.
3. Persist to localStorage.
4. Tests:
   - Toggle changes class.
   - localStorage round-trip.
5. **Commit boundary**: one commit.

**Definition of Done**
- Manual visual verification + component tests pass.

---

### Story 2.12 — Keyboard navigation (FR-16)

**Outcome:** When `props.keyboardNav !== false`, Arrow Up/Down moves row focus; Enter calls `onRowActivate(rowId)`; Space toggles selection when `selectable`. Wraps from last to first row.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/common/data-table.tsx` | Add `tabIndex={0}` on `<TableRow>`; add `onKeyDown` handler to detect Arrow/Enter/Space; manage focused-row index via `useState` |

**Tasks**

1. Add `focusedRowIndex` state.
2. Render `tabIndex={focusedRowIndex === idx ? 0 : -1}` on each row (roving tabindex).
3. Handle Arrow Up / Arrow Down (wrap) + Enter (call `onRowActivate`) + Space (toggle selection if enabled).
4. Tests using `@testing-library/user-event`:
   - Tab into row 0; Arrow Down → row 1 focused.
   - Enter → `onRowActivate` called with row id.
   - Space → row selected.
5. **Commit boundary**: one commit.

**Definition of Done**
- AC-12 implementable.

---

### Story 2.13 — Source-of-truth lint guard test (FR-17)

**Outcome:** A vitest test scans every `*.column-config.ts` (or `*.tsx` with an exported column config) under `ui/src/components/**` and asserts every column with `filter.kind === 'enum'` has a non-empty `sourceOfTruth` field AND `wireValues` is imported from `enums.ts` (not an inline literal). For `fk-select`, asserts `sourceOfTruth` is non-empty.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/common/data-table-column-discipline.test.tsx` | The lint-guard test |

**Tasks**

1. Use Node's `fs.readdirSync` + `path.join` to find all column configs under `ui/src/components/**/*.column-config.ts` (no new deps required; vitest runs in Node).
2. For each file, parse via regex against the source text:
   - `filter:\s*\{\s*kind:\s*['"]enum['"]\s*,\s*wireValues:\s*([A-Z_]+)` — capture the imported identifier name
   - `sourceOfTruth:\s*['"]([^'"]+)['"]` — capture the backend citation
3. For each captured `wireValues` identifier:
   - Confirm the column-config file imports it from `'@/lib/enums'` (verify via `import\s+{[^}]*<name>[^}]*}\s+from\s+['"]@/lib/enums['"]`).
   - **Open `ui/src/lib/enums.ts` and verify the identifier's declaration is immediately preceded (line N-1 or N-2) by the canonical `// Values must match backend/...py <Symbol>` comment.** Missing comments fail the test.
4. For each captured `sourceOfTruth`:
   - Assert it is non-empty.
   - Assert it starts with `backend/` (path prefix indicating a backend citation, not a frontend path).
5. For `kind: 'fk-select'` columns, assert `sourceOfTruth` is non-empty (no `enums.ts` import expected since FK options are dynamically loaded).
6. **Commit boundary**: one commit (the test passes vacuously in Epic 2; assertions fire when Epic 3 column configs are written).

**Definition of Done**
- AC-16 implementable. Test passes vacuously in Epic 2; with full assertions in Epic 3 after all 8 column configs exist.
- A regression test (intentionally introduce a column-config without `sourceOfTruth`) confirms the test fails with a clear error message.

### Epic 2 — Phase gate

- [ ] All 13 stories committed.
- [ ] All component tests pass (vitest).
- [ ] Primitive has no consumers yet (no migrated tables) — by design.
- [ ] GPT-5.5 phase-gate review on cumulative Epic 2 diff.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test` pass.

---

## Epic 3 — Migrate 8 standalone tables to the DataTable primitive

**Goal:** Each existing table component is migrated to use `<DataTable>` driven by a co-located column config. The 9th table (`studies-by-cluster-table.tsx`) inherits via its existing thin-wrap pattern.

### Story 3.1 — Migrate `studies-table.tsx`

**Outcome:** [`ui/src/components/studies/studies-table.tsx`](../../../../ui/src/components/studies/studies-table.tsx) (76 LOC) renders via `<DataTable>` with a co-located `studies-table.column-config.ts`. URL state expands to `?status=&sort=&q=&cursor=`. The parent `/studies` page reads/writes filter via the DataTable; the existing `StudyStatusFilterChips` (40 LOC) is deleted.

**UI element inventory (current studies-table)**

Read [`studies-table.tsx`](../../../../ui/src/components/studies/studies-table.tsx) (76 LOC):
- 6 columns: Name (link to `/studies/<id>`), Cluster, Status (`<StatusBadge>`), Best metric, Created, Completed
- Empty state: `<p data-testid="studies-empty">No studies match the current filters.</p>`
- Sort: none
- Filter: none (filter chips are in `study-status-filter-chips.tsx` rendered by the parent page)

**Legacy Behavior Parity table** (per template requirement for migrated user-facing components — studies-table is <100 LOC but the migrated parent page logic is the heart of the user-facing surface)

| # | Legacy behavior | Location in old code | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | "completed" filter chip URL-backed via `?status=` | `ui/src/app/studies/page.tsx:30-40` | Preserved | DataTable filter column for `status`, URL pattern unchanged |
| 2 | Empty-state copy "No studies match the current filters" | `studies-table.tsx:22-24` | Preserved | `<DataTableEmpty kind="no-rows-match">` consumer copy |
| 3 | "Create study" button on header | `ui/src/app/studies/page.tsx:48-50` | Preserved | Unchanged — lives in page, outside DataTable |
| 4 | Name → `/studies/<id>` link | `studies-table.tsx:42-49` | Preserved | DataTable column `cell:` render fn |
| 5 | Status badge via `<StatusBadge kind="study">` | `studies-table.tsx:51-53` | Preserved | DataTable column `cell:` render fn |
| 6 | Best metric numeric formatting `.toFixed(3)` | `studies-table.tsx:55-59` | Preserved | DataTable column `cell:` render fn |

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/studies-table.column-config.ts` | Exports `studiesColumns: DataTableColumnDef<StudySummary>[]` |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/studies-table.tsx` | Rewritten to consume `<DataTable>` with `studiesColumns`. Becomes ~30 LOC. |
| `ui/src/app/studies/page.tsx` | Remove `<StudyStatusFilterChips>` (DataTable owns filtering now), remove ad-hoc cursor stack state, pass `useStudies({...})` query result as `data` + `totalCount` + `next_cursor` + `has_more` to `<DataTable>`. |
| `ui/src/components/studies/study-status-filter-chips.tsx` | **Deleted** — DataTable filter column replaces it. |
| `ui/src/__tests__/app/studies/page.test.tsx` | Update mock setup; assert new DataTable toolbar testids. |

**Endpoints** — uses Story 1.2/1.3 surface (`/api/v1/studies?q=&sort=&status=&cursor=`). No new endpoints.

**Tasks**

1. Write `studies-table.column-config.ts` with 6 columns + sort + filter:
   - `name` (sortable, sortKey: `name`)
   - `cluster_id` (not sortable, not hideable — sticky identifier)
   - `status` (sortable, filter `{ kind: 'enum', wireValues: STUDY_STATUS_VALUES, sourceOfTruth: 'backend/app/api/v1/schemas.py StudyStatusWire' }` — `STUDY_STATUS_VALUES` is imported from `@/lib/enums` which itself carries the `// Values must match backend/app/api/v1/schemas.py StudyStatusWire.` comment per the existing Story 4.2 grep gate; the `sourceOfTruth` field is the backend citation for the lint guard from Story 2.13)
   - `best_metric` (sortable, `firstClickDirection: 'desc'`)
   - `created_at` (sortable, `firstClickDirection: 'desc'`)
   - `completed_at` (sortable, hideable)
2. Update `useStudies` hook in `ui/src/lib/api/studies.ts` to accept the new `sort` param.
3. Rewrite `studies-table.tsx` to render `<DataTable tableId="studies" columns={studiesColumns} {...query.data} searchable />`.
4. Update `/studies/page.tsx` to remove the chips + cursor-stack and pass the query result through.
5. Delete `study-status-filter-chips.tsx`.
6. Update `page.test.tsx` mocks — assert on `data-testid="data-table-toolbar"`, `filter-chip-status-completed`, `data-table-search`, etc.
7. Add `ui/tests/e2e/studies-data-table.spec.ts` per spec §14 matrix (search + sort + filter + pagination + URL state survives refresh).
8. **Commit boundary**: one commit per migrated table.

**Definition of Done**
- Studies page renders via DataTable.
- All 6 Legacy Parity rows asserted by tests.
- New E2E spec passes against `make up` stack.
- `study-status-filter-chips.tsx` file deleted.

---

### Story 3.2 — Migrate `proposals-table.tsx`

**Outcome:** [`proposals-table.tsx`](../../../../ui/src/components/proposals/proposals-table.tsx) (117 LOC) renders via `<DataTable>` with `proposals-table.column-config.ts`. Filters: `status` (enum chips), `source` (enum chips), `cluster_id` (fk-select), `template_id` (fk-select — NEW). `searchable={false}` (no FTS on proposals per spec §3). Sort: `created_at`, `status`, `pr_state`.

**UI element inventory (current proposals-table)**: 7 columns — Source link, Cluster, Template+version, Status badge, PR state badge, Metric delta, Created. Read the file — already studied during spec-gen.

**Legacy Behavior Parity** (proposals-table is 117 LOC + parent page is larger — parity table required)

| # | Legacy behavior | Location | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | Source filter `study | manual | all` via URL `?source=` | `app/proposals/page.tsx:20-71` + `proposal-source-filter-chips.tsx` | Preserved (PROPOSAL_SOURCE_VALUES added to enums.ts, DataTable enum filter) |
| 2 | Status filter via URL `?status=` | `app/proposals/page.tsx` + `proposal-status-filter-chips.tsx` | Preserved (DataTable enum filter) |
| 3 | Cluster filter via URL `?cluster_id=` | `app/proposals/page.tsx` + `cluster-filter-select.tsx` | Preserved (DataTable fk-select filter) |
| 4 | New: template filter via URL `?template_id=` | n/a (new) | Added (DataTable fk-select filter; backend FR-3) |
| 5 | Metric delta panel rendering | `proposals-table.tsx:91-107` | Preserved (column `cell:` render fn) |
| 6 | PR state badge conditional | `proposals-table.tsx:91-97` | Preserved (column `cell:` render fn) |
| 7 | Per-row "study" / "manual" link with detail-link | `proposals-table.tsx:57-82` | Preserved (column `cell:` render fn with the same link shape) |
| 8 | 30s pulse-refetch | `app/proposals/page.tsx` (existing `refetchInterval`) | Preserved — DataTable doesn't own server state; consumer hook keeps `refetchInterval` |
| 9 | `?action=open_pr` auto-trigger on proposals detail | `app/proposals/[id]/page.tsx` | Preserved — only the list page is migrated in this story; detail page not touched |

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/proposals-table.column-config.ts` | Exports `proposalsColumns: DataTableColumnDef<ProposalSummary>[]` + `useTemplatesForFilter()` helper |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/proposals/proposals-table.tsx` | Rewritten to consume `<DataTable>` |
| `ui/src/app/proposals/page.tsx` | Remove `<ProposalStatusFilterChips>`, `<ProposalSourceFilterChips>`, `<ClusterFilterSelect>` (DataTable owns all filters now). Keep `refetchInterval` on the query hook. |
| `ui/src/components/proposals/proposal-status-filter-chips.tsx` | **Deleted** |
| `ui/src/components/proposals/proposal-source-filter-chips.tsx` | **Deleted** |
| `ui/src/components/proposals/cluster-filter-select.tsx` | **Deleted** |
| `ui/src/lib/api/proposals.ts` | Add `template_id` + `sort` to `useProposals` filter type |
| `ui/src/lib/enums.ts` | Add `PROPOSAL_SOURCE_VALUES = ['study', 'manual'] as const` with `// Values must match backend/app/api/v1/schemas.py ProposalSourceWire` comment |
| `ui/src/__tests__/app/proposals/page.test.tsx` | Update tests |

**Tasks**

1. Add `PROPOSAL_SOURCE_VALUES` to `enums.ts`.
2. Write column config with the 4 filters (enum × 2, fk-select × 2).
3. The `template_id` fk-select uses a new `useTemplatesForFilter()` hook that wraps `useTemplates({ limit: 200 })`.
4. Rewrite proposals-table.tsx; update parent page; delete the 3 old filter components.
5. Update tests.
6. Add `ui/tests/e2e/proposals-data-table.spec.ts` per spec §14 matrix (no search, sort + 4 filters + pagination + URL state).
7. **Commit boundary**: one commit.

**Definition of Done**
- All 9 Legacy Parity rows asserted.
- New E2E spec passes.
- Three filter-chip files deleted.

---

### Story 3.3 — Migrate `clusters-table.tsx`

**Outcome:** [`clusters-table.tsx`](../../../../ui/src/components/clusters/clusters-table.tsx) (60 LOC) renders via `<DataTable>`. New filters: `engine_type`, `environment`. Sort: `name`, `created_at`, `environment`. `searchable={true}` (FTS on `name + base_url`).

**Legacy Behavior Parity:** clusters-table is <100 LOC — section omitted per template rule. Empty-state copy preserved via `<DataTableEmpty kind="no-rows-exist" primaryCta={<Register cluster button>}>`.

**New files**: `ui/src/components/clusters/clusters-table.column-config.ts`.

**Modified files**: `clusters-table.tsx`, `ui/src/app/clusters/page.tsx`, `ui/src/lib/api/clusters.ts` (add `q`, `sort`, `engine_type`, `environment` to filter type).

**Tasks**

1. Write column config: Name (sortable, sticky), Engine (filter enum on `engine_type`), Environment (sortable, filter enum), Health (not filterable — it's a synthetic field), Base URL (not sortable).
2. Rewrite `clusters-table.tsx`; update page to pass query through.
3. Update `useClusters` to accept new params.
4. Update existing tests.
5. Add `ui/tests/e2e/clusters-data-table.spec.ts`.
6. **Commit boundary**: one commit.

**Definition of Done**: Studies-style. E2E passes.

---

### Story 3.4 — Migrate `templates-table.tsx`

**Outcome:** [`templates-table.tsx`](../../../../ui/src/components/templates/templates-table.tsx) (57 LOC) renders via `<DataTable>`. Filter: `engine_type`. Sort: `name`, `created_at`, `engine_type`, `version`. `searchable={true}` (FTS on `name`).

**New files**: `templates-table.column-config.ts`.
**Modified files**: `templates-table.tsx`, `ui/src/app/templates/page.tsx`, `ui/src/lib/api/query-templates.ts`.

**Tasks**: same shape as 3.3. Add E2E spec `templates-data-table.spec.ts`.

**Definition of Done**: E2E passes.

---

### Story 3.5 — Migrate `query-sets-table.tsx`

**Outcome:** [`query-sets-table.tsx`](../../../../ui/src/components/query-sets/query-sets-table.tsx) (55 LOC) renders via `<DataTable>`. Filters: none. Sort: `name`, `created_at`. `searchable={true}` (FTS on `name`).

**New files**: `query-sets-table.column-config.ts`.
**Modified files**: `query-sets-table.tsx`, `ui/src/app/query-sets/page.tsx`, `ui/src/lib/api/query-sets.ts`.

**Tasks**: same shape. Add E2E spec `query-sets-data-table.spec.ts`.

**Definition of Done**: E2E passes.

---

### Story 3.6 — Migrate `judgments-table.tsx` (per-list rows, `searchable={false}`)

**Outcome:** [`judgments-table.tsx`](../../../../ui/src/components/judgments/judgments-table.tsx) (107 LOC) renders via `<DataTable>`. URL-backs the `?source=` filter (previously React state). Adds `?sort=<col>:<dir>` on `created_at`, `rating`, `source`. `searchable={false}` (per spec §3 — judgments FTS is out of scope; the per-list endpoint adds `?sort=` only).

**Legacy Behavior Parity** (107 LOC component):

| # | Legacy behavior | Location | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | Source filter chip row (`all` / `llm` / `human`) | `judgments-table.tsx:35-50` | Preserved (DataTable enum filter with `JUDGMENT_SOURCE_FILTER_VALUES` from enums.ts) |
| 2 | InfoTooltip on Rating column header | `judgments-table.tsx:65-69` | Preserved (DataTable column `tooltipKey: 'judgment.relevance'`) |
| 3 | InfoTooltip on Source column header | `judgments-table.tsx:71-74` | Preserved (DataTable column `tooltipKey: 'judgment.source'`) |
| 4 | `<OverridePopover>` in last column | `judgments-table.tsx:94-96` | Preserved (column `cell:` render fn keeps the popover) |
| 5 | `<StatusBadge kind="judgment_list">` for source value | `judgments-table.tsx:87-89` | Preserved |
| 6 | Empty-state copy "No judgments match the current filters" | `judgments-table.tsx:51-57` | Preserved via `<DataTableEmpty kind="no-rows-match">` |
| 7 | Notes column with `—` fallback | `judgments-table.tsx:91-93` | Preserved (column `cell:` render fn) |

**New files**: `judgments-table.column-config.ts`.
**Modified files**: `judgments-table.tsx`, `ui/src/app/judgments/[id]/page.tsx` (URL-back the source filter), `ui/src/lib/api/judgments.ts` (add `sort` param to `useJudgments`).

**Tasks**

1. Write column config: Query (not sortable, sticky), Doc (not sortable), Rating (sortable, tooltipKey, `firstClickDirection: 'desc'`), Source (sortable, filter enum, tooltipKey), Notes (not sortable), Actions (not sortable, not hideable, no header).
2. Rewrite `judgments-table.tsx` to consume DataTable. The parent page now passes URL-backed `?source=` through (instead of React-state-only).
3. Update `useJudgments` hook to accept `sort`.
4. Update existing tests.
5. Add `ui/tests/e2e/judgments-data-table.spec.ts` per matrix (no search, sort + filter + pagination + URL state).
6. **Commit boundary**: one commit.

**Definition of Done**: 7 Legacy Parity rows asserted. E2E passes.

---

### Story 3.7 — Migrate `trials-table.tsx` (combined-wire sort encoder)

**Outcome:** [`trials-table.tsx`](../../../../ui/src/components/studies/trials-table.tsx) (105 LOC) renders via `<DataTable>` with a custom `encodeSort` / `decodeSort` that maps internal `(col, dir)` to the existing combined wire shape (`primary_metric_desc`, `ended_at_asc`, etc.). The `<Select>` is deleted; column-header clicks drive sort. `searchable={false}`.

**Legacy Behavior Parity** (105 LOC component):

| # | Legacy behavior | Location | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | `<Select>` with 5 sort options | `trials-table.tsx:31-50` | Intentionally dropped — replaced by column-header click sort per spec FR-4 + AC-13. Backend wire values preserved. |
| 2 | InfoTooltip on "Sort by" label | `trials-table.tsx:36` | Preserved (or moved to the new column-header tooltip pattern; primary_metric column header gets `tooltipKey: 'trial.primary_metric'`) |
| 3 | 5 column headers with `<InfoTooltip>` | `trials-table.tsx:58-83` | Preserved (column `tooltipKey` per FR-12) |
| 4 | `<StatusBadge kind="trial">` for status column | `trials-table.tsx:89-92` | Preserved |
| 5 | `.toFixed(4)` on primary_metric | `trials-table.tsx:93-95` | Preserved |
| 6 | Empty state "No trials yet" | `trials-table.tsx:51-55` | Preserved via `<DataTableEmpty kind="no-rows-exist">` |
| 7 | `JSON.stringify(t.params)` in Params column | `trials-table.tsx:96-97` | Preserved (column `cell:` render fn) |

**New files**: `trials-table.column-config.ts` with the custom encoder.

**Modified files**: `trials-table.tsx`, `ui/src/app/studies/[id]/page.tsx` (URL-back the sort), `ui/src/lib/api/studies.ts` (no signature change — `sort` already accepted).

**Custom encoder for trials**: the column config exports `encodeSort: (col, dir) => 'primary_metric_desc' | ...` and `decodeSort: (wire) => ({col, dir})`. DataTable picks these up via a new optional `tableOpts.encodeSort` / `decodeSort` prop.

**Tasks**

1. Add `encodeSort` / `decodeSort` props to `DataTableProps` (and to `useDataTableUrlState`).
2. Implement the trials encoder. Mapping table:

   | Internal `(col, dir)` | Wire value |
   |---|---|
   | `('primary_metric', 'desc')` | `primary_metric_desc` |
   | `('primary_metric', 'asc')` | `primary_metric_asc` |
   | `('ended_at', 'desc')` | `ended_at_desc` |
   | `('ended_at', 'asc')` | `ended_at_asc` |
   | `('optuna_trial_number', 'asc')` | `optuna_trial_number_asc` |

   Note: `optuna_trial_number_desc` is **not** in the existing `TrialSortKey` Literal. The column config must set `firstClickDirection: 'asc'` on the trial-number column and disable the second click (no toggle to desc) — or simply only declare `optuna_trial_number` as sortable in the asc direction.
3. Write column config:
   - **Trial number** (sortable, `firstClickDirection: 'asc'`, `sortDirections: ['asc']` — only `optuna_trial_number_asc` exists in `TrialSortKey`; the primitive's sort cycle is constrained to unsorted ↔ asc per the column-config `sortDirections` field added in Story 2.2's type)
   - **Status** (not sortable — no `status` value in `TrialSortKey`; no filter — `/api/v1/studies/{id}/trials` has no `?status=` query param. Tooltip preserved via `tooltipKey: 'trial.status'`.)
   - **Primary metric** (sortable, `firstClickDirection: 'desc'`, `sortDirections: ['asc', 'desc']`, tooltip)
   - **Ended at** (NEW column header — replaces the `Duration` reference because the wire keys are `ended_at_*`; render `ended_at` time alongside the existing duration display. Sortable, `firstClickDirection: 'desc'`, `sortDirections: ['asc', 'desc']`, tooltip.)
   - **Duration** (rendered alongside the Ended-at column or as a separate not-sortable column — duration is NOT in `TrialSortKey`, so it cannot be sortable. Tooltip preserved.)
   - **Params** (not sortable, not hideable, tooltip)
4. Rewrite `trials-table.tsx` — delete the `<Select>`.
5. Update existing trials-table tests + parent page.
6. Add `ui/tests/e2e/trials-data-table.spec.ts` per matrix.
7. **Commit boundary**: one commit.

**Definition of Done**: AC-13 implementable. 7 Legacy Parity rows asserted (1 dropped with rationale). No invalid `?sort=` wire values generated (verified by contract test in `test_studies_api_contract.py`).

---

### Story 3.8 — Migrate `queries-table.tsx`

**Outcome:** [`queries-table.tsx`](../../../../ui/src/components/query-sets/queries-table.tsx) (205 LOC) renders via `<DataTable>` with a co-located `queries-table.column-config.ts`. The inline edit / metadata / delete actions are preserved as a column `cell:` render function that wraps `<EditQueryPopover>` / `<EditMetadataDialog>` / `<DeleteQueryDialog>` per row. `searchable={false}` (the per-query endpoint has no FTS — search would belong on the parent `/query-sets` index, not the per-query sub-resource). URL-back the existing cursor stack via `useDataTableUrlState`.

**UI element inventory (current queries-table)** — read [`queries-table.tsx`](../../../../ui/src/components/query-sets/queries-table.tsx) (205 LOC):
- 5 columns: Query text (truncated 100ch), Reference answer (truncated 50ch), Metadata (Badge with set/—), Judgments count, Actions (3 icon buttons: Edit / Metadata / Delete)
- Page-size selector (10/25/50/100); internal cursor stack via `useState`
- Header line "X queries total" via `<p data-testid="queries-total">`
- EmptyState for none / error / no data variants
- 3 child popovers/dialogs: `<EditQueryPopover>`, `<EditMetadataDialog>`, `<DeleteQueryDialog>`

**Legacy Behavior Parity** (205 LOC component — parity table required):

| # | Legacy behavior | Location | Verdict | Preservation site |
|---|---|---|---|---|
| 1 | Page-size selector with options `[10, 25, 50, 100]` | `queries-table.tsx:22, 188-191` | Preserved (DataTable `pageSizeOptions` prop = `[10, 25, 50, 100]` via existing `CursorPaginator`) |
| 2 | Truncate query_text to 100 chars with `…` | `queries-table.tsx:96-98` | Preserved (column `cell:` render fn) |
| 3 | Truncate reference_answer to 50 chars; `—` when null | `queries-table.tsx:99-104` | Preserved |
| 4 | Metadata `<Badge>` with `Set` / `—` + keyboard activation (`Enter` / `Space`) | `queries-table.tsx:105-126` | Preserved |
| 5 | `<EditQueryPopover>` triggered from Edit icon | `queries-table.tsx:131-145` | Preserved (column `cell:` render fn) |
| 6 | `<EditMetadataDialog>` triggered from `{ }` icon | `queries-table.tsx:147-155` + `193-202` | Preserved |
| 7 | `<DeleteQueryDialog>` triggered from Delete icon with conditional `title` based on `judgment_count > 0` | `queries-table.tsx:156-175` | Preserved |
| 8 | Loading / error / empty states distinct | `queries-table.tsx:56-69` | Preserved via DataTable empty states + `isPending` / `isError` props |
| 9 | "X queries total" header line via `queries-total` testid | `queries-table.tsx:75-77` | Preserved — DataTable's total-count toolbar slot covers this (FR-7); the testid moves to `data-table-toolbar-total-count` |
| 10 | DELETE-409 envelope handling (in `useDeleteQuery`) | `queries-table.tsx:156-175` + `useDeleteQuery` hook | Preserved (no change — the hook stays in `lib/api/query-sets.ts`) |

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/query-sets/queries-table.column-config.ts` | Exports `useQueriesColumns(querySetId)`: a hook because the action-column cell handlers close over `querySetId` |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/query-sets/queries-table.tsx` | Rewritten to consume `<DataTable>`. The two-prop shape stays: `<QueriesTable querySetId={...} />`. Internal cursor stack removed (moves to URL via `useDataTableUrlState` lifted at this component). |
| `ui/src/lib/api/query-sets.ts` | `useQueries` accepts URL-backed cursor in addition to the current React-state cursor (additive — supports both for the migration window, then drop the React-state-only path in the same commit). |
| `ui/src/__tests__/components/query-sets/queries-table.test.tsx` | Update mocks; assert on `data-table-toolbar` etc. |
| `ui/src/__tests__/components/query-sets/queries-table-delete-flow.test.tsx` | Preserved; update wrapper to provide URL state context. |

**Tasks**

1. Write `queries-table.column-config.ts` as `useQueriesColumns(querySetId)`:
   - Query text (not sortable, sticky)
   - Reference answer (not sortable, hideable)
   - Metadata (Badge cell)
   - Judgments count (sortable would require backend `?sort=` support which is out of scope for the per-query sub-resource — keep `sortable: false`)
   - Actions (cell renders the 3 popovers/dialogs; `hideable: false`, `sortable: false`)
2. Rewrite `queries-table.tsx` to consume DataTable with `searchable={false}`, `selectable={false}` (the per-query bulk actions are also out of scope).
3. Update `useQueries` hook to accept the URL-backed cursor.
4. Update the 2 existing test files for the new DOM structure (preserve `meta-badge-<id>`, `edit-<id>`, `meta-<id>`, `delete-<id>` testids).
5. Add `ui/tests/e2e/queries-data-table.spec.ts` per spec §14 matrix (no search, no sort, no filter; cursor pagination + URL state survives refresh).
6. **Commit boundary**: one commit.

**Definition of Done**: All 10 Legacy Parity rows asserted by tests (delete-409 flow already covered by `queries-table-delete-flow.test.tsx`). New E2E spec passes.

### Story 3.9 — `studies-by-cluster-table.tsx` inherits via wrapper (no changes needed)

**Outcome:** [`studies-by-cluster-table.tsx`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx) (41 LOC) automatically inherits the new DataTable behavior because it composes `<StudiesTable>` internally. Verify by asserting the table renders with the new toolbar on a `/clusters/[id]` page that has studies.

**Modified files**: None expected.

**Tasks**

1. Read the file and confirm it imports `StudiesTable` directly.
2. Verify with an E2E spec `studies-by-cluster-data-table.spec.ts` that navigates to `/clusters/<id>` and asserts the new DataTable toolbar appears (search input, etc.).
3. If anything is broken (e.g., the new DataTable requires props the wrapper doesn't pass), update the wrapper minimally.
4. **Commit boundary**: one commit (test + any minor wrapper fix).

**Definition of Done**: E2E spec passes. Verification confirms no functional regression.

### Epic 3 — Phase gate

- [ ] All 8 standalone tables migrated (Stories 3.1–3.8: studies, proposals, clusters, templates, query-sets, judgments, trials, queries) + 1 inherited wrapper verified (Story 3.9: studies-by-cluster).
- [ ] All 9 new E2E specs pass against `make up` stack.
- [ ] All Legacy Parity rows assertion-verified in component tests.
- [ ] No old filter-chip files remain (`study-status-filter-chips.tsx`, `proposal-status-filter-chips.tsx`, `proposal-source-filter-chips.tsx`, `cluster-filter-select.tsx` all deleted).
- [ ] GPT-5.5 phase-gate review on cumulative Epic 3 diff.
- [ ] `make test-unit && cd ui && pnpm test && pnpm test:e2e` pass.

---

## Epic 4 — Documentation + deferred-feature capture

### Story 4.1 — Update architecture & convention docs

**Outcome:** `api-conventions.md`, `ui-architecture.md`, `data-model.md`, `CLAUDE.md` updated to reflect the DataTable + FTS surface.

**Modified files**

| File | Change |
|---|---|
| [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) §"Pagination" | Add `?q=` paragraph documenting the FTS contract + 6 searchable resources. Add `?since=` to the MVP1-status row for judgment-lists + conversations (the pre-existing drift this PR closes). Add `?sort=` documentation. |
| [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) | New §"DataTable primitive" section documenting the primitive's shape, column-config interface, and source-of-truth discipline. |
| [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) | Add `search_vector` (generated) + GIN index row to each of the 6 affected tables' column lists. |
| [CLAUDE.md](../../../../CLAUDE.md) "Common Pitfalls" | Add: "Do not write to `search_vector` columns — they are generated; the ORM models do not declare them." |
| CLAUDE.md "Frontend Conventions" §"Enumerated Value Contract Discipline" | Cross-reference the new `data-table.tsx` `column.filter.sourceOfTruth` field as another enforcement point. |
| `state.md` | Add this feature to the recent-changes log, update Alembic head to `0013`. |
| `architecture.md` | Add `ui/src/components/common/data-table.tsx` to the navigation hub if material; otherwise leave (it's an internal primitive, not a top-level concern). |

**Tasks**

1. Patch each doc per the above.
2. **Commit boundary**: one commit (all docs together).

**Definition of Done**: All docs render correctly; cross-references resolve.

---

### Story 4.2 — Capture deferred-feature idea files

**Outcome:** Per spec §16, create `feat_fts_rank_ordering_mvp2/idea.md` to capture rank-ordered FTS as a deferred feature.

**New files**

| File | Purpose |
|---|---|
| `docs/02_product/planned_features/feat_fts_rank_ordering_mvp2/idea.md` | Origin pointer to spec §16, deferred FRs (only rank ordering on `?q=`), why deferred (cursor encoding constraint), dependencies on this feature (the 6 search_vector columns exist + the `plainto_tsquery` predicate is in place; only the ORDER BY needs to change + cursor encoding update) |

**Tasks**

1. Write `feat_fts_rank_ordering_mvp2/idea.md` per the [idea template](../feature_templates/idea-template.md).
2. **Commit boundary**: one commit.

**Definition of Done**: Idea file exists with origin pointer to spec §16.

### Epic 4 — Phase gate (final)

- [ ] All docs updated.
- [ ] Deferred idea file captured.
- [ ] Final cross-model review (GPT-5.5) on the complete cumulative diff per `.claude/skills/impl-execute/SKILL.md` Step 6.
- [ ] Gemini Code Assist findings adjudicated per CLAUDE.md.
- [ ] All AC-1 through AC-16 verified in CI.

---

## UI Guidance

This section provides the unambiguous patterns the Epic-2 and Epic-3 stories rely on.

### Reference: current component structure

| Component | Path | LOC | Section structure |
|---|---|---|---|
| `studies-table.tsx` | `ui/src/components/studies/studies-table.tsx` | 76 | Single `<Table>` with 6 columns. Empty-state `<p data-testid="studies-empty">`. |
| `proposals-table.tsx` | `ui/src/components/proposals/proposals-table.tsx` | 117 | Single `<Table>` with 7 columns. Metric-delta sub-component inline in cell. |
| `judgments-table.tsx` | `ui/src/components/judgments/judgments-table.tsx` | 107 | Source-filter chip row above `<Table>` (parent-driven state). Two InfoTooltip-decorated headers. |
| `trials-table.tsx` | `ui/src/components/studies/trials-table.tsx` | 105 | `<Select>` sort control above `<Table>`. Five InfoTooltip-decorated headers. |
| `clusters-table.tsx` | `ui/src/components/clusters/clusters-table.tsx` | 60 | 5 columns. No filter/sort. |
| `templates-table.tsx` | `ui/src/components/templates/templates-table.tsx` | 57 | 4 columns. No filter/sort. |
| `query-sets-table.tsx` | `ui/src/components/query-sets/query-sets-table.tsx` | 55 | 3 columns. No filter/sort. |
| `cursor-paginator.tsx` | `ui/src/components/common/cursor-paginator.tsx` | 73 | Page-size `<select>` + total-count + Prev/Next buttons. |

### Insertion point

The DataTable lives at `ui/src/components/common/data-table.tsx` — a new file. The 8 existing table-component files are **rewritten** to consume it; they keep their existing import path and `<Component rows={...}>` testid shape so consumer pages don't need broad refactors.

### Analogous markup patterns

**Pattern: shadcn Table structure** — already in use by every migrated table. Copy from [`studies-table.tsx:28-75`](../../../../ui/src/components/studies/studies-table.tsx):

```tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

<Table data-testid="studies-table">
  <TableHeader>
    <TableRow>
      <TableHead>Name</TableHead>
      {/* ... */}
    </TableRow>
  </TableHeader>
  <TableBody>
    {rows.map((s) => (
      <TableRow key={s.id} data-testid={`study-row-${s.id}`}>
        <TableCell>{/* ... */}</TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

DataTable preserves the outer `<Table data-testid="<tableId>">` and `<TableRow data-testid="<rowKey>-${row.id}">` testid shape so existing E2E specs keep passing.

**Pattern: existing filter-chip row** — from [`study-status-filter-chips.tsx`](../../../../ui/src/components/studies/study-status-filter-chips.tsx):

```tsx
<div className="flex flex-wrap items-center gap-2" role="group" aria-label="Status filter">
  {CHIP_VALUES.map((chip) => (
    <Button
      key={chip}
      type="button"
      variant={isActive ? 'default' : 'outline'}
      size="sm"
      data-testid={`status-chip-${chip}`}
      onClick={() => onChange(chip === ALL ? null : chip)}
    >
      {chip}
    </Button>
  ))}
</div>
```

DataTable's `<DataTableFilterChips>` reuses this exact `<Button>` + role + data-testid shape; the testid pattern becomes `filter-chip-<column>-<value>`.

**Pattern: existing native `<select>` for fk-filtering** — from [`cluster-filter-select.tsx`](../../../../ui/src/components/proposals/cluster-filter-select.tsx):

```tsx
<select
  id="cluster-filter"
  className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm"
  value={value ?? ''}
  onChange={(e) => onChange(e.target.value || null)}
  disabled={isLoading}
  data-testid="cluster-filter-select"
>
  <option value="">{isLoading ? '(loading…)' : 'All clusters'}</option>
  {clusters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
</select>
```

DataTable's `<DataTableFkSelect>` reuses this — same native `<select>`, same classNames.

**Pattern: existing tooltip wrapping** — from [`trials-table.tsx:60-69`](../../../../ui/src/components/studies/trials-table.tsx):

```tsx
<TableHead>
  <span className="inline-flex items-center gap-1">
    Status
    <InfoTooltip glossaryKey="trial.status" />
  </span>
</TableHead>
```

DataTable's sortable header wraps the column's `header` text in this exact pattern when `column.tooltipKey` is set.

**Pattern: cursor paginator integration** — from [`queries-table.tsx:183-191`](../../../../ui/src/components/query-sets/queries-table.tsx):

```tsx
<CursorPaginator
  hasMore={queries.data.has_more}
  onNext={queries.data.has_more ? onNext : undefined}
  onPrev={cursorStack.length > 1 ? onPrev : undefined}
  pageSize={pageSize}
  onPageSizeChange={onPageSizeChange}
  totalCount={queries.data.totalCount}
  pageSizeOptions={PAGE_SIZE_OPTIONS}
/>
```

DataTable wraps this internally; consumers stop importing `CursorPaginator` directly.

### Layout and structure

- DataTable layout: toolbar (top, single row, wraps on narrow screens) → table body with sticky header → cursor paginator (bottom, fixed two-column flex per existing CursorPaginator).
- Toolbar columns left-to-right: search input (if `searchable`) | filter chip rows / fk-selects (one per filterable column) | spacer (`flex-1`) | total-count indicator | density toggle | column-visibility menu.
- Bulk-action toolbar appears between toolbar and table body when `selectedIds.length >= 1`.

### Component composition

- DataTable is composed of: `<DataTableToolbar>` (renders search + filters + total-count + density + col-vis + bulk-actions) → `<Table>` (renders sortable headers + body rows) → `<CursorPaginator>`.
- Empty state replaces the `<Table>` body when `data.length === 0`.
- All sub-components live in `ui/src/components/common/data-table-*.tsx` and are NOT exported individually — they're internal to DataTable. Only `<DataTable>` and the `DataTableColumnDef<T>` type are exported.

### Information architecture placement

- DataTable is a primitive — no IA placement of its own.
- The migrated table consumers preserve their existing IA placement: `/studies`, `/proposals`, `/clusters`, `/templates`, `/query-sets`, `/query-sets/[id]` (queries sub-table), `/judgments/[id]` (per-list judgments), `/studies/[id]` (trials), `/clusters/[id]` (studies-by-cluster inheritance).

### Tooltips and contextual help

Per spec §11, six new glossary keys ship with the primitive (`datatable.sort.toggle`, `datatable.search.min_length`, `datatable.total_count`, `datatable.density.toggle`, `datatable.column_visibility`, `datatable.selection.all_on_page`). All consume the existing [`InfoTooltip`](../../../../ui/src/components/common/info-tooltip.tsx) wrapper. Pattern from [`info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx):

```tsx
<InfoTooltip glossaryKey="datatable.sort.toggle" />
```

Column-config-supplied `tooltipKey` renders an `<InfoTooltip>` next to the header text via the existing `<span className="inline-flex items-center gap-1">` pattern.

### Visual consistency

- Use shadcn `<Button variant="default" | "outline">` for chips, density toggle, column-visibility trigger.
- Use lucide-react `<ChevronUp />` / `<ChevronDown />` / `<ChevronsUpDown />` for sort chevrons (already in repo).
- Use lucide-react `<Eye />` for column-visibility trigger.
- Sticky header: Tailwind `sticky top-0 bg-background z-10` (the `bg-background` is required so rows don't bleed through).

### Legacy behavior parity

Per-story parity tables are inside each Story 3.x. The Epic-3 phase gate asserts every "Preserved" row has a test reference; every "Intentionally dropped" row has a cited rationale.

### Client-side persistence

Two `localStorage` keys per migrated table:
- `relyloop:datatable:<tableId>:hidden-columns` — `string[]` of hidden column ids (FR-14)
- `relyloop:datatable:<tableId>:density` — `'comfortable' | 'compact'` (FR-15)

DoD wording must say "persists across sessions" (matches `localStorage`).

---

## 3) Testing workstream

### 3.1 Unit tests (backend)

- Location: `backend/tests/unit/`
- Scope: pure validation logic + SQL clause builders
- Tasks:
  - [ ] `test_fts_predicate.py` — `fts_predicate(None)` returns `None`; `fts_predicate("term")` returns the expected `text(...)` clause shape.
  - [ ] `test_parse_sort.py` — `parse_sort` returns `None` on unknown; returns `ParsedSort` on valid; respects `:desc` direction.
  - [ ] Each repo's `count_*` function under unit-style mocked DB (skipped — repos go through integration tests since they hit real SQL).
- DoD:
  - [ ] All branches covered; no DB required.

### 3.2 Integration tests (backend)

- Location: `backend/tests/integration/`
- Scope: DB-backed FTS + cursor pagination + filter combinations
- Tasks:
  - [ ] **`test_search_vector_migrations.py`** — Round-trip test for all 6 migrations: `upgrade head → downgrade 0007 → upgrade head` asserts GIN indexes + columns exist/don't-exist via `pg_indexes` and `information_schema.columns`. Per-migration test: `upgrade <rev> → downgrade -1 → upgrade <rev>` asserts only that revision's column/index.
  - [ ] **`test_clusters_fts.py`** — Seed 5 clusters with known names + base_urls; assert `?q=<term>` filters correctly; assert `X-Total-Count`; assert combinations with `?engine_type=`, `?environment=`, `?since=`, `?cursor=`.
  - [ ] **`test_studies_fts.py`** — Same shape for studies (with `?q=` + `?status=` + `?sort=`).
  - [ ] **`test_query_sets_fts.py`** — Same shape.
  - [ ] **`test_query_templates_fts.py`** — Same shape (with `?engine_type=`).
  - [ ] **`test_judgment_lists_fts.py`** — Same shape, including new `?since=`.
  - [ ] **`test_conversations_fts.py`** — Same shape, including new `?since=`.
  - [ ] **`test_proposals_template_filter.py`** — `?template_id=` filters correctly.
  - [ ] **`test_<resource>_sort_pagination.py`** (7 files, one per sortable resource) — Seed N rows, hit `?sort=<col>:<dir>&limit=2`, fetch all pages via cursor, assert no duplicates + no skips.
  - [ ] **`test_judgments_row_sort.py`** — Per-list judgment rows: `?sort=rating:desc`, `?sort=created_at:asc`, etc.
- DoD:
  - [ ] All FTS endpoints + sort endpoints have multi-page assertion coverage.

### 3.3 Contract tests (backend)

- Location: `backend/tests/contract/`
- Scope: Pydantic validation + error envelope shape
- Tasks:
  - [ ] **`test_clusters_api_contract.py`** — Existing file gains: `?q=p` → 422 `VALIDATION_ERROR`; `?q=<201 chars>` → 422; `?sort=foo` → 422; `?engine_type=spaceship` → 422; `?environment=neptune` → 422. All assert `detail.error_code == "VALIDATION_ERROR"` and `detail.retryable === false`.
  - [ ] **`test_studies_api_contract.py`** — Same shape for `?q=`, `?sort=`. Plus regression: existing trials `?sort=primary_metric_desc` still works (no change).
  - [ ] **`test_query_sets_api_contract.py`** — `?q=`, `?sort=`.
  - [ ] (Same for `query_templates`, `judgments`, `conversations`, `proposals` contract files.)
  - [ ] **`test_proposals_api_contract.py`** — `?template_id=not-a-uuid` → 422.
  - [ ] **`test_judgments_api_contract.py`** — `?since=not-a-date` → 422 (added in Story 1.5 — closes pre-existing api-conventions.md drift; covered by FR-3 acceptance).
  - [ ] **`test_conversations_api_contract.py`** — `?since=not-a-date` → 422 (added in Story 1.5).
  - [ ] **`test_openapi_surface.py`** — Re-run; verify all new query params appear in the OpenAPI schema.
- DoD:
  - [ ] Every new query param has an unknown-value contract test asserting 422 + envelope shape.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- **Rule:** Real backend only (no `page.route()` mocks). Setup via `helpers/seed.ts`; assertions via `page`.
- Tasks (per spec §14 matrix — 9 specs total: 8 standalone + 1 wrapper):
  - [ ] **`studies-data-table.spec.ts`** — search "product" → sort by Created → filter `?status=completed` → click Next → refresh page → assert URL state survives.
  - [ ] **`proposals-data-table.spec.ts`** — no search (assert input absent); filter by status → filter by source → fk-select cluster → fk-select template → click Next → refresh → URL state survives.
  - [ ] **`queries-data-table.spec.ts`** — `/query-sets/<id>` route — no search, no sort, no filter; seed N queries; click Next → URL gains `?cursor=<opaque>`; refresh → cursor + page-size survive. Inline edit/delete/metadata popovers continue to work.
  - [ ] **`clusters-data-table.spec.ts`** — seed >`pageSize` clusters via API helper; search "elastic" → sort by Name → filter `?engine_type=elasticsearch` → filter `?environment=dev` → click Next page → assert URL gains `?cursor=<opaque>` → refresh → URL state + cursor survive (this is the **new** paginator path — clusters had no paginator pre-DataTable).
  - [ ] **`templates-data-table.spec.ts`** — search "boost" → sort by Version → filter `?engine_type=opensearch` → URL state survives.
  - [ ] **`query-sets-data-table.spec.ts`** — search "smoke" → sort by Name → URL state survives.
  - [ ] **`judgments-data-table.spec.ts`** — `/judgments/<id>` route — no search (assert input absent); sort by Rating desc → filter by source `?source=llm` → URL state survives.
  - [ ] **`trials-data-table.spec.ts`** — no search; column-header click on "Primary metric" → URL becomes `?sort=primary_metric_desc` (combined wire form); click again → `?sort=primary_metric_asc`. Existing trials wire shape preserved.
  - [ ] **`studies-by-cluster-data-table.spec.ts`** — navigate to `/clusters/<id>`; assert the studies-by-cluster table renders with the new DataTable toolbar (search input visible per inherited config).
- DoD:
  - [ ] All 9 new E2E specs pass against `make up` stack.
  - [ ] Each spec uses `page.goto()`, `page.fill()`, `page.click()`, `page.keyboard.press()` — no `page.route()` calls.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/src/__tests__/app/studies/page.test.tsx` | Asserts on `<StudyStatusFilterChips>` | ~5 | Update to assert on new DataTable filter-chip testids (`filter-chip-status-completed` etc.) |
| `ui/src/__tests__/app/proposals/page.test.tsx` | Asserts on `<ProposalStatusFilterChips>`, `<ProposalSourceFilterChips>`, `<ClusterFilterSelect>` | ~10 | Update to assert on DataTable filter-chip testids; add assertions for new `template_id` fk-select |
| `ui/src/__tests__/app/clusters/page.test.tsx` | Asserts on `clusters-table` testid | ~3 | Preserved (the testid stays); add new toolbar assertions |
| `ui/src/__tests__/app/judgments/[id]/page.test.tsx` | Asserts on source filter chips via React state | ~4 | Update to URL-back the source filter |
| `ui/src/__tests__/app/studies/[id]/page.test.tsx` | Asserts on trials sort `<Select>` | ~3 | Update to column-header sort |
| `ui/src/__tests__/components/proposals/proposals-table.test.tsx` | Tests the table component directly | ~3 | Preserve test IDs; update prop shape (now consumes DataTable) |
| `ui/src/__tests__/components/query-sets/queries-table.test.tsx` | Tests queries-table | ~3 | Update for the Story 3.8 migration: the queries-table is now a DataTable consumer. Existing row/action testids (`meta-badge-<id>`, `edit-<id>`, `meta-<id>`, `delete-<id>`) are preserved; add assertions for the new `data-table-toolbar` + URL-backed cursor. |
| `ui/tests/e2e/studies.spec.ts` | Asserts on `studies-table` testid + chips | ~5 | Preserve table testid; chip testids update |
| `ui/tests/e2e/proposals.spec.ts` | Asserts on proposal-status-chip-* and proposal-source-chip-* | ~6 | Update to `filter-chip-status-*` / `filter-chip-source-*` testid pattern |

### 3.6 Migration verification

- [ ] All 6 migrations include `downgrade()` (per spec FR-2)
- [ ] `alembic upgrade head` succeeds with all 6
- [ ] Round-trip: `alembic downgrade 0007 && alembic upgrade head` clean
- [ ] Per-migration round-trip clean
- [ ] No `search_vector` declared in ORM models (grep assertion)

### 3.7 CI gates

- [ ] `make backend-fmt && make backend-lint && make backend-typecheck`
- [ ] `make test-unit && make test-integration && make test-contract`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test`
- [ ] `cd ui && pnpm test:e2e` (9 new specs all pass against `make up`: 8 standalone-table specs + 1 inherited-wrapper spec)
- [ ] `scripts/ci/verify_enum_source_of_truth.sh` passes (7 new enum entries)
- [ ] 80% backend coverage gate not regressed

---

## 4) Documentation update workstream

Per Epic 4 / Story 4.1:

### 4.0 Core context files
- [ ] **`state.md`** — add this feature to recent changes; update Alembic head to `0013`.
- [ ] **`architecture.md`** — minimal update (new primitive in `ui/src/components/common/`); no new top-level layer.
- [ ] **`CLAUDE.md`** — add `search_vector`-not-writable to "Common Pitfalls"; cross-ref `data-table.tsx` filter `sourceOfTruth` from "Enumerated Value Contract Discipline".

### 4.1 Architecture docs
- [ ] `docs/01_architecture/api-conventions.md` — `?q=`, `?sort=`, closing `?since=` drift
- [ ] `docs/01_architecture/ui-architecture.md` — new §"DataTable primitive"
- [ ] `docs/01_architecture/data-model.md` — `search_vector` columns + indexes on 6 tables

### 4.2 Product docs
- [ ] None — spec + plan already exist

### 4.3 Runbooks
- [ ] None — no new ops procedures

### 4.4 Security docs
- [ ] None — no new threat surfaces (FTS uses `plainto_tsquery` which is safe per spec §10)

### 4.5 Quality docs
- [ ] `docs/05_quality/testing.md` — optional: note the new `data-table-column-discipline.test.tsx` shape

**Documentation DoD**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with shipped behavior
- [ ] All architecture doc edits in same PR

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- **Eliminate duplication** across 4 filter-chip components (`study-status-filter-chips.tsx`, `proposal-status-filter-chips.tsx`, `proposal-source-filter-chips.tsx`, `cluster-filter-select.tsx`) — consolidate into `<DataTableFilterChips>` / `<DataTableFkSelect>` (Story 3.2 + Story 3.3 delete the old files).
- **Centralize cursor pagination** by wrapping `<CursorPaginator>` inside `<DataTable>` so consumers stop importing it directly (8 fewer import lines).
- **Centralize source-of-truth discipline** for filter values via `column.filter.sourceOfTruth` (FR-17 / Story 2.13).

### 5.2 Planned refactor tasks

- [ ] Delete `study-status-filter-chips.tsx` (Story 3.1)
- [ ] Delete `proposal-status-filter-chips.tsx`, `proposal-source-filter-chips.tsx`, `cluster-filter-select.tsx` (Story 3.2)
- [ ] No backend refactor in scope — FTS + sort additions are net-new code.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by per-story Legacy Parity tables + tests (Epic 3).
- [ ] Lint/typecheck remain green at every commit.
- [ ] No expansion of product scope beyond the spec.
- [ ] No unrelated refactors — every change in this PR is in spec scope (including the `queries-table.tsx` migration per Story 3.8).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_contextual_help` Phase 1 (`InfoTooltip`, `HelpPopover`, `glossary.ts`) | Epic 2 Story 2.8 (tooltip headers) | Implemented (PR #122, on main) | Would require rebuilding tooltip primitives; not blocking — dep is met. |
| `@tanstack/react-table@~8.21.3` npm package | Epic 2 Story 2.1 | Planned (this PR) | Reimplementing TanStack Table's sort/filter/row-model is infeasible. The version is the latest stable 8.x verified during preflight. |
| Postgres 16 `english` FTS dictionary | Epic 1 Stories 1.1–1.2 | Built into Postgres; no extension required | None — `english` dict ships with Postgres. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TanStack Table 8.x major-version churn during implementation | L | M | Tilde-pin (`~8.21.3`) so patch updates apply but minors don't. |
| Sort-aware cursor encoding has edge cases (e.g., null `completed_at`) | M | M | Each integration test seeds rows with NULL values + paginates through; `NULLS LAST/FIRST` clause is explicit in repo. |
| Component tests for DataTable's 13 features become unwieldy | M | L | Split into 5+ test files (one per major feature); use `vi.useFakeTimers()` for debounce. |
| Legacy Behavior Parity rows missed during 8-table migration | M | M | Per-story parity tables (template enforced); Epic-3 phase gate asserts every "Preserved" row has a test reference. |
| 8 new E2E specs slow down CI | L | L | Existing CI already runs `pnpm test:e2e` in ~3s for 8 specs; +8 specs adds ~3-5s. Acceptable. |
| `localStorage` quota exceeded on column-visibility writes | L | L | Story 2.10's `useLocalStorageSet` wraps in try/catch; falls back to React-state-only. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| `?q=` over 200 chars | User pastes long text into search input | Frontend Zod truncates; backend returns 422 `VALIDATION_ERROR` | Auto — user sees error toast |
| Stale cursor in shared URL | Row deleted between page-1 and page-2 navigation | DataTable detects `data.length === 0 AND totalCount > 0 AND ?cursor=` → renders `stale-cursor` empty state with "Return to first page" button | User-driven click |
| Backend 5xx during search | API container crash | Existing global error toast renders; DataTable shows `<EmptyState>` "Backend unreachable" | Auto-retry on next refetch |
| `localStorage` SecurityError (private browsing) | Safari Private Browsing | `useLocalStorageSet` try/catch swallows; defaults apply | Silent — user-invisible |
| Concurrent insert during sort + cursor pagination | New row appears with `created_at` between two cursor pages | Keyset predicate may show or skip the new row depending on its values; this is inherent to keyset pagination | Documented behavior; no special handling |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 — Backend foundation** (Stories 1.1 – 1.5)
   - 1.1 (migrations) → 1.2 (FTS) → 1.3 (sort) → 1.4 (enum filters) → 1.5 (FK + since)
   - Sequential within Epic 1 because each story builds on the previous repo signatures.
2. **Epic 2 — DataTable primitive** (Stories 2.1 – 2.13)
   - 2.1 (scaffold) → 2.2 (sort) + 2.3 (filters) + 2.4 (search) can run sequentially or in parallel branches if multi-agent.
   - 2.5 (total-count) → 2.6 (url-state hook) — 2.6 consolidates the URL handling from 2.2/2.3/2.4 so should land after them.
   - 2.7 (empty states + paginator) → 2.8 (sticky + tooltip) → 2.9 (selection) → 2.10 (col-vis) → 2.11 (density) → 2.12 (keyboard) → 2.13 (lint guard).
3. **Epic 3 — Table migrations** (Stories 3.1 – 3.8) — can be parallelized per-table after Epic 2 lands.
4. **Epic 4 — Docs** (Stories 4.1 – 4.2) — last, after all code lands.

### Parallelization opportunities

- Epic-3 stories 3.1 – 3.8 are independent (each table migrates separately) and could be parallelized if multi-agent execution is supported. Story 3.9 must wait for 3.1 (it inherits from `studies-table`).
- Within Epic 1, stories 1.4 and 1.5 are independent of each other and could be parallelized after 1.3 lands.

---

## 8) Rollout and cutover plan

- **Rollout stages:** none — MVP1 is local-only.
- **Feature flag strategy:** none — single-PR atomic delivery per Locked Decision #4.
- **Migration steps:** operator runs `make migrate` after pulling main; `make up` rebuilds the api + worker images with the new code.
- **Cutover:** zero downtime expected; all existing API consumers (the migrated tables) work without modification because the new `?q=`, `?sort=`, etc. params are optional.
- **Reconciliation:** N/A — no external systems involved.

---

## 9) Execution tracker

### Current sprint
- [x] Story 1.1 — 6 search_vector migrations
- [x] Story 1.2 — `?q=` on 6 endpoints
- [x] Story 1.3 — `?sort=` with sort-aware cursor
- [x] Story 1.4 — `?engine_type=` + `?environment=` filters
- [x] Story 1.5 — `?template_id=` + `?since=` additions
- [x] Story 2.1 — `@tanstack/react-table` dep + primitive scaffold
- [x] Story 2.2 — Sortable column headers
- [x] Story 2.3 — Filter chips (enum + fk-select)
- [x] Story 2.4 — Debounced text search
- [x] Story 2.5 — Total-count display
- [x] Story 2.6 — `useDataTableUrlState` hook
- [x] Story 2.7 — Three empty states + cursor wrapping
- [x] Story 2.8 — Sticky header + tooltip headers
- [x] Story 2.9 — Multi-row selection + bulk actions
- [x] Story 2.10 — Column visibility menu
- [x] Story 2.11 — Density toggle
- [x] Story 2.12 — Keyboard navigation
- [x] Story 2.13 — Source-of-truth lint guard test
- [x] Story 3.1 — Migrate studies-table
- [x] Story 3.2 — Migrate proposals-table
- [x] Story 3.3 — Migrate clusters-table
- [x] Story 3.4 — Migrate templates-table
- [x] Story 3.5 — Migrate query-sets-table
- [ ] Story 3.6 — Migrate judgments-table
- [ ] Story 3.7 — Migrate trials-table
- [ ] Story 3.8 — Migrate queries-table
- [ ] Story 3.9 — Verify studies-by-cluster inheritance
- [ ] Story 4.1 — Update architecture & convention docs
- [ ] Story 4.2 — Capture deferred-feature idea files

### Blocked items
(none)

### Done this sprint
(none yet)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match the story's New/Modified files tables.
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error_code).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added for all relevant layers (unit/integration/contract/component/E2E).
- [ ] Commands executed and passed:
  - [ ] `make backend-fmt`
  - [ ] `make backend-lint`
  - [ ] `make backend-typecheck`
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm test:e2e` (if UI touched in story)
- [ ] Migration round-trip evidence (per-migration + full-stack) if schema changed.
- [ ] Per-story commit follows Conventional Commits format (Rule #7).

---

## 11) Plan consistency review

Performed during plan-gen Pass 1 + Pass 2 + GPT-5.5 cycles. Findings ledger in the spec-gen + plan-gen output. All findings adjudicated and applied before this plan was marked Draft.

Key checks executed:

1. **Spec → plan endpoint count parity:** Spec §8.1 lists 8 affected endpoints (+ the per-list judgments sort endpoint = 9). Plan Stories 1.2 + 1.3 + 1.4 + 1.5 cover all 9. ✓
2. **Spec → plan FR coverage:** Every FR (FR-1 through FR-17) has a row in §1 traceability and is assigned to a story. ✓
3. **Story endpoint table parity:** Each story's endpoint table mentions only the endpoints owned by that story; no overlap. ✓
4. **Test file count:** §3.2 lists 7 FTS integration test files + 7 sort-pagination test files + per-resource contract tests in §3.3 + 9 E2E specs in §3.4 (8 standalone + 1 inherited wrapper). Total ~31 new test files. ✓
5. **Alembic head + revision sequencing:** `0008` builds on `0007_conversations_messages` (verified via `ls migrations/versions/`). Sequential `0008 → 0009 → 0010 → 0011 → 0012 → 0013`. ✓
6. **Frontend filter wire-value parity (FR-17 + AC-9):** Every column config with `kind: 'enum'` references an existing `enums.ts` symbol with the canonical source-of-truth comment. `PROPOSAL_SOURCE_VALUES` is **new** in this PR (added in Story 3.2) and matches `backend/app/api/v1/schemas.py:752 ProposalSourceWire = Literal["study", "manual"]`. ✓
7. **Trials backward compatibility:** Existing `TRIAL_SORT_VALUES` Literal is preserved unchanged (verified by reading `schemas.py:181`); only the consumer-side encoder is custom. ✓
8. **MVP-rule activation gates:**
   - MVP1 single-tenant: no `tenant_id` columns added. ✓
   - MVP2 audit_log: not yet active; FR set is read-only. ✓
   - CLAUDE.md Rule #5 (downgrade): all 6 migrations include `downgrade()`. ✓
   - Rule #8 (no hardcoded model names): N/A — feature is not LLM-touching.

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers (unit/integration/contract/component/E2E) explicitly scoped.
- [x] Documentation updates across docs/01-05 planned and owned (Epic 4 Story 4.1).
- [x] Lean refactor scope + guardrails explicit (§5).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed; findings adjudicated.
