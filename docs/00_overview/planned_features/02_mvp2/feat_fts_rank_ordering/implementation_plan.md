# Implementation Plan — Rank-ordered FTS results

**Date:** 2026-06-05
**Status:** Ready for Execution (self-reviewed — see §8)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) (repo/router conventions, cursor pagination, test layers); [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)

> **Cross-model review:** GPT models unreachable in this env (no key, egress 403). Opus self-review substituted per operator decision (2026-06-05). Ledger in §8.

---

## 0) Design recap (from spec §2)

- Rank ordering is the implicit default when `?q=` is present AND `parse_sort(sort, allowed) is None`. Explicit `?sort=` overrides (D-1).
- Rank path: `ORDER BY floor(ts_rank(search_vector, plainto_tsquery('english', :q)) * 1_000_000) DESC, id DESC`. Cursor is the **existing 2-tuple** `(rank_bucket:int, id)` — reuses `order_by_clauses(None, default_col=rank_expr, id_col)` + `keyset_predicate(None, value, id, default_col=rank_expr, id_col)` (the `parsed=None` branch IS a 2-col DESC keyset). No new `_sort.py` functions; no migration (D-2).
- The computed `rank_bucket` isn't a model attribute → the repo selects it `.label(...)`, stashes it on each returned ORM object as a transient `_fts_rank_bucket`, and the router reads `last._fts_rank_bucket` for the next cursor.

## 1) Scope traceability

| FR | Story | Notes |
|---|---|---|
| FR-1 (rank ORDER BY) | 1.1 (helpers) + 1.2 (6 repos) | Additive branch; non-`q` path untouched. |
| FR-2 (exact keyset) | 1.2 (repos) + 1.3 (6 routers) | Reuse `parsed=None` keyset with `rank_expr` as default_col. |
| FR-3 (cursor round-trip) | 1.1 + 1.4 (unit) | Existing `encode_cursor`/`decode_cursor` (int value, `value_is_datetime=False`). |
| FR-4 (frontend indicator) | 2.1 | Toolbar pill + glossary. |
| FR-5 (no non-`q` change) | 1.4 regression + 1.5 integration | AC-4. |

## 2) Delivery structure — 2 epics

### Epic 1 — Backend rank ordering

**Story 1.1 — Helpers (`rank_bucket_expr`, `rank_active`).**
- `backend/app/db/repo/_fts.py`: add
  - `RANK_BUCKET_SCALE = 1_000_000`
  - `def rank_bucket_expr(q: str) -> ColumnElement[int]:` → `func.floor(func.ts_rank(text("search_vector"), func.plainto_tsquery("english", q_bind)) * RANK_BUCKET_SCALE).cast(Integer)`. Build with a bound param for `q` (mirror `fts_predicate`'s `text(...).bindparams(q=q)` injection-safety). Return labeled-able expression (caller adds `.label`).
  - `def rank_active(q: str | None, parsed: ParsedSort | None) -> bool:` → `bool(q) and parsed is None`. Single source of truth shared by repo + router (prevents drift).
- DoD: unit-tested (1.4); mypy/ruff green.

**Story 1.2 — Rank branch in the 6 repos.** Files: `cluster.py`, `study.py`, `query_set.py`, `query_template.py`, `judgment_list.py`, `conversation.py` (both `list_conversations` and `list_conversations_with_preview_data`).
- In each `list_*`: after computing `parsed_sort` + `fts`, compute `is_rank = rank_active(q, parsed_sort)`.
- When `is_rank`: build `rank_col = rank_bucket_expr(q)`; `stmt = select(Model, rank_col.label("rb"))`; ORDER BY `order_by_clauses(None, default_col=rank_col, id_col=Model.id)`; keyset (if cursor) `keyset_predicate(None, cursor_value, cursor_id, default_col=rank_col, id_col=Model.id)`; execute and return rows with `obj._fts_rank_bucket = rb` stashed.
- When not `is_rank`: unchanged (existing scalar path).
- **Helper to avoid 6× duplication of the row-stash:** add `def _attach_rank(result) -> list:` local pattern OR a tiny shared `backend/app/db/repo/_fts.py:rows_with_rank(result)` that iterates `result.all()`, sets `_fts_rank_bucket`, returns the ORM list. Use it in all 6.
- DoD: each repo returns `Sequence[Model]` unchanged in type; rank path stashes the transient attr.

**Story 1.3 — Rank branch in the 6 routers.** Files: `clusters.py`, `studies.py`, `query_sets.py`, `query_templates.py`, `judgment_lists.py`, `conversations.py`.
- Compute `is_rank = rank_active(q, parsed_sort)`.
- Cursor decode: `value_is_datetime = False if is_rank else cursor_value_is_datetime(parsed_sort)`.
- Next cursor value-half: `last._fts_rank_bucket if is_rank else (last.created_at if parsed_sort is None else getattr(last, parsed_sort.col_name))`.
- `conversations.py` has no `sort` param → `parsed_sort` is always `None` there, so `is_rank = bool(q)`.
- DoD: contract tests green; tampered-rank-cursor → 422.

### Epic 2 — Frontend indicator

**Story 2.1 — "Sorted by relevance" pill.**
- `ui/src/components/common/data-table-toolbar.tsx` (or a small `relevance-indicator.tsx`): render a non-interactive pill in `leftSlot` when `urlState.q` is non-empty AND `urlState.sort` is falsy (rank active). Use `InfoTooltip glossaryKey="fts.relevance_sort"`.
- `ui/src/lib/glossary.ts`: add `fts.relevance_sort` short entry (e.g. "Results are ordered by how well they match your search. Click a column header to sort by that column instead.").
- DoD: vitest AC-8 (pill shows iff q && !sort); typecheck/lint/prettier/build green.

## 3) Testing workstream

- **Unit** `backend/tests/unit/`:
  - `test_query_cursor_helpers.py` (extend): int value-half round-trip (`encode_cursor(12345, "id")` → decode `value_is_datetime=False` → `(12345, "id")`); bool/shape rejection still holds (AC-6).
  - **`test_fts_rank_ordering.py` (new) — the load-bearing local test (AC-7):** an in-memory oracle. Generate sample `(rank_bucket:int, id:str)` tuples; sort by `(rank desc, id desc)`; pick a cursor row; assert that a Python re-implementation of the `keyset_predicate(None, ...)` boolean (`rank < cv or (rank==cv and id<cid)`) selects EXACTLY the suffix after the cursor — no skip, no dupe — across several cursor positions incl. rank ties and bucket boundaries. Also assert `rank_active(q, parsed)` truth table and `rank_bucket_expr` compiles to SQL containing `ts_rank` + `floor` + `plainto_tsquery` (str(expr)).
- **Integration** `backend/tests/integration/test_fts_rank_endpoints.py` (new; mirror `test_fts_endpoints.py` parametrization over the 6 resources): AC-1 (rank order), AC-2 (paginate with cursor == single big-limit fetch, no skip/dupe), AC-3 (explicit sort overrides), AC-4 (no-`q` unchanged), AC-9 (all 6). DB-backed → CI.
- **Contract** `backend/tests/contract/`: AC-5 tampered-rank-cursor 422 (one resource suffices; the decode path is shared).
- **vitest**: AC-8 toolbar pill.

## 4) Documentation
- `docs/01_architecture/api-conventions.md`: one paragraph — "When `?q=` is set without `?sort=`, results are ordered by `ts_rank` (relevance) via a rank-bucketed keyset cursor; `?sort=` overrides."
- `state.md` "Last 5 merges" at finalization.

## 5) Migration
None (D-2). Alembic head unchanged.

## 6) Audit-event coverage
N/A — reads only.

## 7) Risks (from spec §10) — execution notes
- Keyset exactness is the top risk and is DB-integration-verified (CI). The unit oracle (1.4) mirrors the predicate boolean so the math is verified locally before CI. The rank branch is additive (only when `q` && no sort) → non-search listing is byte-identical (AC-4).
- Transient `_fts_rank_bucket` attr: ORM models are declarative without `__slots__`, so instance attribute assignment is fine; it is never flushed (not a mapped column).

## 8) Self-review ledger (Opus, substituting GPT-5.5)

- **Pass 1 (codebase accuracy):** signatures verified by Read — `_sort.py` (`parse_sort`/`order_by_clauses`/`keyset_predicate`/`encode_cursor`/`decode_cursor`/`cursor_value_is_datetime`), `_fts.py` (`fts_predicate`), `cluster.py:list_clusters` + `clusters.py` router decode/next-cursor pattern. The `parsed=None` branch of `keyset_predicate`/`order_by_clauses` is exactly the 2-col DESC keyset the rank path needs → no new sort helpers. Confirmed routers own decode + next-cursor and pass a pre-decoded 2-tuple to repos.
- **Pass 2 (correctness):** the cursor and ORDER BY use the SAME `floor(ts_rank·1e6)` int (passed as `default_col`), so the keyset is exact. Dropping `created_at` from the rank tiebreak is safe — `id` is UUIDv7 (time-ordered), and uniqueness guarantees determinism. `rank_active` shared by repo+router prevents the decode/encode paths from disagreeing on triple-vs-default.
- **Pass 3 (scope/verifiability):** larger than the idea's estimate because the computed rank column must be surfaced for the next cursor (transient-attr stash) and the branch repeats across 6 repos+routers, but each change is small/mechanical and additive. Local verification: cursor unit + the in-memory keyset oracle (1.4) cover the bug-prone math without a DB; CI covers the SQL. 0 unresolved findings. Converged.
