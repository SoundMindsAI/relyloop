# `GET /api/v1/judgment-lists` silently ignores `?query_set_id=` and `?cluster_id=` filters

**Date:** 2026-05-20
**Status:** Bug — surfaced during local verification of PR #163 (`feat_create_study_search_space_builder`). Pre-existing since `feat_llm_judgments` (PR #35, 2026-05-11); not introduced by PR #163.
**Origin:** Manual testing of the create-study modal. Operator picked a query-set at Step 2, then a judgment-list from the (supposedly filtered) dropdown. Backend rejected the create at Step 5 with 422 `VALIDATION_ERROR: "judgment_list query_set_id does not match study query_set_id"`. Direct probe of `GET /api/v1/judgment-lists?query_set_id=<id>&limit=5` returned 5 rows where only 1 actually had a matching `query_set_id` — the backend was returning ALL judgment-lists, ignoring the filter.
**Depends on:** None.

## Problem

The frontend hook at [`ui/src/lib/api/judgments.ts:37-46`](../../../../ui/src/lib/api/judgments.ts#L37-L46) (`useJudgmentLists`) passes `query_set_id` and `cluster_id` query parameters when listing judgment-lists:

```ts
export function useJudgmentLists(
  filter: { query_set_id?: string; cluster_id?: string; cursor?: string; limit?: number },
): UseQueryResult<JudgmentListListResponse, ApiError> {
  const { query_set_id, cluster_id, cursor, limit } = filter;
  return useQuery<...>({
    queryKey: ['judgment-lists', { query_set_id, cluster_id, cursor, limit }],
    queryFn: () =>
      apiClient.get<JudgmentListListResponse>('/api/v1/judgment-lists', {
        params: { query_set_id, cluster_id, cursor, limit },
      }),
  });
}
```

The backend endpoint at [`backend/app/api/v1/judgments.py:334-385`](../../../../backend/app/api/v1/judgments.py#L334-L385) accepts ONLY: `cursor`, `limit`, `since`, `q`, `sort`. The `query_set_id` + `cluster_id` query params are not declared in the signature, FastAPI silently drops them, and the repo call at line 363 doesn't see them:

```python
async def list_judgment_lists_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[JudgmentListSortKey | None, Query()] = None,
) -> JudgmentListListResponse:
    ...
    rows = await repo.list_judgment_lists(
        db, cursor=decoded_cursor, limit=limit + 1, since=since, q=q, sort=sort,
    )
```

The repo function at [`backend/app/db/repo/judgment_list.py:58-100`](../../../../backend/app/db/repo/judgment_list.py#L58-L100) also has no `query_set_id` or `cluster_id` parameter.

**User-visible impact** (create-study modal at `/studies`):

1. Operator picks cluster at Step 1.
2. Operator picks query-set at Step 2. Judgment-list dropdown is supposed to filter by both `query_set_id` and `cluster_id` per the hook's contract — but the dropdown loads ALL judgment-lists regardless.
3. Operator picks any judgment-list from the (unfiltered) list.
4. Operator walks through Steps 3–5, fills required fields, clicks Submit.
5. Backend `POST /api/v1/studies` runs the cross-entity integrity check and returns 422 `VALIDATION_ERROR: "judgment_list query_set_id does not match study query_set_id"`.

This is a confusing failure mode — the UI suggests the picked judgment-list is valid (the dropdown showed it), but the server rejects only at create time with a cryptic message. In a fresh local environment with only seed data this is reproducible 100% of the time once enough cross-query-set judgment-lists exist.

## Proposed capabilities

### Required (fix the bug)

- **Backend endpoint** (`judgments.py`): add `query_set_id` and `cluster_id` `Query()` params; pass them through to the repo:
  ```python
  query_set_id: Annotated[str | None, Query()] = None,
  cluster_id: Annotated[str | None, Query()] = None,
  ...
  rows = await repo.list_judgment_lists(
      db, query_set_id=query_set_id, cluster_id=cluster_id, ...
  )
  total = await repo.count_judgment_lists(
      db, query_set_id=query_set_id, cluster_id=cluster_id, ...
  )
  ```
- **Repo function** (`repo/judgment_list.py`): accept `query_set_id: str | None` and `cluster_id: str | None`; apply `WHERE` clauses on the SQLAlchemy `select` statement before pagination.
- **Contract test** (`backend/tests/contract/test_judgments_*.py`): assert filtered + unfiltered cases return the right rows.
- **Integration test** (`backend/tests/integration/test_judgments_*.py`): create 3 judgment-lists across 2 query-sets; assert `?query_set_id=A` returns only the 2 in A, `?query_set_id=B` returns only the 1 in B.

### Optional (workaround surface improvement)

- Frontend: until the backend is fixed, show an inline amber warning below the judgment-list dropdown explaining that the filter isn't applied and offering a link to a future fix.

## Scope signals

- **Backend:** ~30 LOC (endpoint signature + 2 repo functions + Pydantic stays the same). Plus 2 new tests (~80 LOC).
- **Frontend:** zero LOC. The hook already sends the params correctly — once the backend honors them, the UI works without further change.
- **Migration:** none.
- **Config:** none.

## Why not implemented inline today

PR #163 (`feat_create_study_search_space_builder`) is frontend-only. Mixing this backend fix into PR #163 would expand the diff to two unrelated subsystems and obscure both reviews. Per the CLAUDE.md tangential-discoveries rubric:

> "Fix is ≤250 LOC + bounded tests AND the work-type fits this PR's intent (backend → backend, frontend → frontend, infra → infra)" → Inline OR same-branch adjacent commit.
>
> "Fix would break a CI gate this PR is specifically valued on… AND the fix is bounded" → **Adjacent PR off `main`** — not inline, not idea file.

This bug fits the second row: the fix is bounded but the work-type doesn't match PR #163's frontend scope. **Recommended path: a separate small backend PR off `main` that lands the endpoint + repo fix + two tests.** Estimated cycle time: under 30 minutes (the change is mechanical).

## Relationship to other work

- **Independent of** [`feat_create_study_search_space_builder`](../feat_create_study_search_space_builder/) — purely surfaces the bug; doesn't block it.
- **Related to** [`feat_create_study_target_autocomplete`](../feat_create_study_target_autocomplete/) (filed earlier this session) — both improve the create-study modal's "you can pick anything, server-side rejects later" failure mode.
- **Pre-existing since** [`feat_llm_judgments`](../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/) — the judgments router shipped without filter support; nothing has caught it because the e2e tests use `seedFullChain` which always creates exactly one matching judgment-list per query-set, and the `studies-create-validation.spec.ts` always picks that one option.
