# Feature Specification — Rank-ordered FTS results (`ORDER BY ts_rank DESC` when `?q=` is active)

**Date:** 2026-06-05
**Status:** Approved (self-reviewed — see §13)
**Owners:** Product — soundminds.ai · Engineering — RelyLoop core
**Depends on:** `feat_data_table_primitive` (shipped — the 6 `search_vector` columns + GIN indexes (migrations `0008`–`0013`), the `fts_predicate` helper, the keyset-cursor `_sort.py` helpers, and the `<DataTable>` search input all exist).
**Related docs:**
- [`idea.md`](idea.md) — origin brief
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) — cursor pagination contract; offset/limit banned
- `backend/app/db/repo/_sort.py`, `backend/app/db/repo/_fts.py` — the helpers this feature extends

> ### Cross-model review note
> CLAUDE.md requires GPT-5.5 cross-model review of specs/plans. The GPT models are **unreachable in this execution environment** (`OPENAI_API_KEY` absent; `api.openai.com` egress blocked, HTTP 403). Per the operator decision (2026-06-05), **Opus self-review is substituted** for the GPT-5.5 cross-model review on this spec and its plan. See §13 for the self-review ledger.

---

## 1) Purpose

- **Problem:** `feat_data_table_primitive` shipped **filter-only** FTS — `?q=foo` matches rows where `search_vector @@ plainto_tsquery('english', 'foo')` but orders by the default `created_at DESC, id DESC`. For ambiguous queries the user gets the *newest* matches, not the *most relevant*.
- **Outcome:** When `?q=` is present **and no explicit `?sort=` is supplied**, the 6 search-enabled list endpoints order results by relevance: `ORDER BY rank_bucket DESC, created_at DESC, id DESC`, where `rank_bucket = floor(ts_rank(search_vector, plainto_tsquery('english', :q)) * 1e6)`. Keyset cursor pagination stays exact (no offset/limit) because the cursor encodes the *same* integer `rank_bucket` that the ORDER BY uses. The `<DataTable>` toolbar shows a "Sorted by relevance" indicator when this ordering is active.
- **Non-goal:** No new persisted column, no migration (approach 1). No change to the `?q=` filter semantics (which rows match). No exposure of `ts_rank` as a column-header sort. No change to non-`q` list behavior.

## 2) Design decisions

- **D-1 — Rank is the implicit default when `?q=` is active, not an opt-in sort key.** Searching implies "show me the best matches." When both `?q=` and `?sort=` are present, **the explicit `?sort=` wins** (the user deliberately re-sorted). This matches the idea's model and avoids polluting each resource's `_SORT_COLUMNS` allowlist with a non-column `ts_rank` key.
- **D-2 — Rank-bucketed cursor (idea approach 1), no migration.** The cursor encodes `(rank_bucket: int, created_at: iso, id: str)`. Critically, the **ORDER BY uses the identical `floor(ts_rank·1e6)` integer expression**, so the 3-tuple keyset predicate is *exact* — rows sharing a bucket are deterministically tiebroken by `(created_at, id)`. This sidesteps float-cursor brittleness without a `last_search_score` column (approach 2, rejected: needs a 6-table migration for a transient value).
- **D-3 — `BUCKET_SCALE = 1_000_000`.** `ts_rank` for `plainto_tsquery` results is in `[0, ~1]` for these short documents; ×1e6 gives ~6 significant digits of rank resolution before the `(created_at, id)` tiebreaker takes over — far finer than any user-perceptible relevance difference. The scale is a single backend constant; clients never see it (opaque cursor).
- **D-4 — `conversations` participates too.** It has no `?sort=` param, so when `?q=` is present it always rank-orders (no override path). Its repo gains the same rank branch. (`list_conversations_with_preview_data` is the preview variant; both list paths get the branch where they apply the FTS predicate.)
- **D-5 — Cursor invalidation is already handled.** The frontend `use-data-table-url-state.ts` already sets `cursor: null` when `q`, `sort`, or any filter changes (verified). No frontend cursor-reset work is needed; the indicator is display-only.
- **D-6 — The indicator is an indicator, not a toggle.** It communicates "results are ranked by relevance"; the user changes ordering via the existing column-header sort (which sets `?sort=` and thereby overrides rank). No new control wiring beyond the conditional pill.

## 3) Phase boundaries

Single phase. No deferred work. No `phase<N>_idea.md`.

## 4) Functional requirements

### FR-1 — Rank ORDER BY when `?q=` active and no explicit sort
- When a list request has a non-empty `q` AND `parse_sort(sort, ...)` returns `None` (no/blank/unknown `?sort=`), the repo MUST order by `rank_bucket DESC, <default_col> DESC, id DESC`, where `rank_bucket = floor(ts_rank(search_vector, plainto_tsquery('english', :q)) * 1_000_000)` evaluated against the same `:q`.
- When `q` is empty/None, ordering is unchanged (legacy `order_by_clauses`).
- When `q` is present AND an explicit valid `?sort=` is supplied, the explicit sort wins (legacy `order_by_clauses(parsed, ...)`) — rank is NOT applied (D-1).

### FR-2 — Exact keyset pagination on the rank triple
- The cursor for the rank path MUST encode `(rank_bucket: int, created_at, id)`.
- The keyset predicate MUST be the exact 3-column all-DESC lexicographic predicate matching the FR-1 ORDER BY, evaluated against the same `:q` bind (so `rank_bucket` is recomputed identically on the next page). No row may be skipped or duplicated across page boundaries.
- `X-Total-Count` is unchanged (it counts matching rows, order-independent).

### FR-3 — Cursor encode/decode for the rank triple
- A rank cursor round-trips `(int, datetime, str)` → opaque token → `(int, datetime, str)`. Tampered/malformed rank cursors raise the existing `VALIDATION_ERROR` (422), never 500 — same guarantee as the 2-tuple cursor.

### FR-4 — Frontend "Sorted by relevance" indicator
- The `<DataTable>` toolbar renders a non-interactive "Sorted by relevance" pill when `q` is non-empty AND there is no active explicit `sort` (i.e. the rank ordering is in effect). It disappears when `q` is cleared or an explicit column sort is applied.
- A glossary-backed tooltip explains the behavior (reuse/add a `fts.relevance_sort` short glossary entry).

### FR-5 — No behavior change when not searching
- With no `?q=`, every endpoint's ordering, cursor, and counts are byte-identical to today. Regression tests assert this for the shared helpers.

## 5) Affected surfaces

| Layer | File | Change |
|---|---|---|
| Repo helper | `backend/app/db/repo/_fts.py` | Add `rank_bucket_expr(q)` (labeled int SQL expr) + `RANK_BUCKET_SCALE`. |
| Repo helper | `backend/app/db/repo/_sort.py` | Add `rank_order_by(rank_col, default_col, id_col)`, `rank_keyset_predicate(...)`, and rank-triple `encode_rank_cursor`/`decode_rank_cursor` (or extend the existing encoder to accept the triple). |
| Repos ×6 | `cluster.py`, `study.py`, `query_set.py`, `query_template.py`, `judgment_list.py`, `conversation.py` | In each `list_*`: when `q` present and `parsed_sort is None`, take the rank branch (rank ORDER BY + rank cursor decode + rank keyset predicate + emit the rank cursor for the next page). |
| Routers ×6 | `backend/app/api/v1/<resource>.py` | Decode the incoming cursor as a rank cursor when the rank branch is active; pass through. (Most routers already delegate cursor decode to the repo via `cursor_value_is_datetime`; the rank branch needs the triple-aware decode.) |
| Frontend | `ui/src/components/common/data-table-toolbar.tsx` (+ a small `relevance-indicator.tsx` or inline) | Conditional "Sorted by relevance" pill. |
| Frontend | `ui/src/lib/glossary.ts` | Add `fts.relevance_sort` short entry. |

No new endpoints, no schema/migration, no new error codes (reuse `VALIDATION_ERROR`), no audit events.

## 6) Audit-event coverage
N/A — FTS reads, no state mutation.

## 7) API contract
No new endpoints or params. `?q=`, `?sort=`, `?cursor=`, `?limit=` are unchanged in name and shape. The only observable change: response *ordering* when `?q=` is set without `?sort=`, and the opaque cursor's internal encoding on that path. Error envelope unchanged.

## 8) Acceptance criteria

- **AC-1:** `GET /clusters?q=prod` (no sort) returns rows ordered by descending `ts_rank` for "prod", with `(created_at, id)` tiebreak. (integration)
- **AC-2:** Paging the AC-1 result with the returned cursor yields the next page with **no duplicate and no skipped row** vs. a single large-limit fetch of the same query. (integration — the keyset-exactness guarantee)
- **AC-3:** `GET /clusters?q=prod&sort=name:asc` orders by `name` ascending (explicit sort overrides rank). (integration)
- **AC-4:** `GET /clusters` (no `q`) is byte-identical in order + cursor to pre-feature behavior. (integration/regression)
- **AC-5:** A tampered rank cursor → 422 `VALIDATION_ERROR`, not 500. (contract)
- **AC-6:** `encode_rank_cursor`/`decode_rank_cursor` round-trip `(int, datetime, str)` exactly; bool/shape violations raise `ValueError`. (unit)
- **AC-7:** `rank_keyset_predicate` produces the exact 3-tuple all-DESC predicate (asserted structurally + via an in-memory ordering oracle). (unit)
- **AC-8:** Frontend: the "Sorted by relevance" pill renders iff `q` non-empty AND no active sort; hidden otherwise. (vitest)
- **AC-9:** All 6 resources covered by the FTS-rank integration matrix (parametrized like `test_fts_endpoints.py`). (integration)

## 9) Test plan

- **Unit** (`backend/tests/unit/`): cursor triple round-trip + tamper (AC-6); `rank_bucket_expr` SQL shape; `rank_order_by` + `rank_keyset_predicate` structural + an in-memory oracle that sorts sample `(rank, created_at, id)` tuples and confirms the predicate selects exactly the "after cursor" suffix (AC-7). **These are the load-bearing local tests** — they verify keyset exactness without a DB.
- **Integration** (`backend/tests/integration/test_fts_endpoints.py` extend, or a new `test_fts_rank_endpoints.py`): AC-1/2/3/4/9 across the 6 resources (DB-backed; runs in CI).
- **Contract** (`backend/tests/contract/`): AC-5 tampered-rank-cursor 422.
- **vitest**: AC-8 toolbar pill.
- No E2E required (covered by integration + vitest); optional follow-up.

## 10) Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Keyset off-by-one at bucket boundaries skips/dupes rows | M | H | ORDER BY the *same* `floor(·1e6)` int the cursor encodes (D-2) so the predicate is exact; AC-2 integration + AC-7 unit oracle both assert no skip/dupe. |
| Shared `_sort.py` change regresses non-`q` paths | L | H | FR-5 + AC-4 regression; the rank branch is strictly additive (only taken when `q` present and no sort). |
| `ts_rank` perf on large tables | L | L | GIN index already exists; single-tenant alpha scale; `ts_rank` computed only on the matched subset. |
| Float locale / `floor` semantics differ Postgres vs Python oracle | L | M | Oracle replicates `floor(x*1e6)` in Python int math; integration test is the ground truth on real Postgres. |

## 11) Rollout
Pure read-ordering change; no flag, no migration, no cutover. Ships with the merge.

## 12) Open questions
None. The cursor approach (D-2) and the rank-default model (D-1) are locked.

## 13) Self-review ledger (Opus, substituting for GPT-5.5 per operator decision)

**Pass 1 — codebase accuracy.** Verified against the Explore reconnaissance: `_sort.py` holds `encode_cursor`/`decode_cursor`/`parse_sort`/`order_by_clauses`/`keyset_predicate`; `_fts.py` holds `fts_predicate`; 6 repos reuse them; `conversations` has no `?sort=` (D-4 accounts for it); the frontend hook already nulls the cursor on `q`/`sort`/filter change (D-5). Migrations 0008–0013 provide the `search_vector` columns.

**Pass 2 — contract/keyset correctness.** The load-bearing risk is keyset exactness. Resolved by D-2: ORDER BY and cursor use the **same** integer `floor(ts_rank·1e6)`, so the 3-tuple all-DESC predicate `(rank,created,id) < (c_rank,c_created,c_id)` is exact (standard lexicographic keyset). AC-2 (integration no-skip/no-dupe) + AC-7 (unit ordering oracle) double-cover it. The "explicit sort overrides rank" rule (D-1) keeps the change additive and the non-`q` path untouched (FR-5/AC-4).

**Pass 3 — scope/verifiability.** No migration, no new endpoints/errors. Largest risk to autonomous execution is that the integration tests are DB-only (CI-verified here), so Pass-2 keyset correctness is mirrored into pure unit tests (AC-6/AC-7) that run locally. Findings: 0 unresolved. Converged.
