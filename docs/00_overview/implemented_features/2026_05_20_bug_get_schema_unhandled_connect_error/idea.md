# `ElasticAdapter.get_schema()` surfaces `httpx.HTTPError` as 500 INTERNAL_ERROR

**Date:** 2026-05-20
**Status:** **Bundled-and-fixed** in the same PR as `feat_create_study_target_autocomplete` (per user direction during post-implementation sweep — the inline-over-defer rubric tipped the right way once both buggy methods were inventoried: `get_schema` + `explain` = 2 methods, ~10 LOC + 2 regression tests, same `ElasticAdapter` subsystem as B1, no product decision). Originally captured as a separate idea per CLAUDE.md tangential-discoveries rule before the user asked "should we fix now?".
**Origin:** [`feat_create_study_target_autocomplete/implementation_plan.md` §6 Risks](../feat_create_study_target_autocomplete/implementation_plan.md) flagged this during planning. The B1 implementation snippet in that plan explicitly adds a `try/except httpx.HTTPError` around `_request(..., translate_errors=False)` because `_request` re-raises raw httpx connection-class exceptions (`ConnectError`, `RemoteProtocolError`, `ConnectTimeout`, `ReadTimeout`) when `translate_errors=False` is used — verified at [`backend/app/adapters/elastic.py:200-210`](../../../../backend/app/adapters/elastic.py#L200-L210).
**Depends on:** None.

## Problem

`ElasticAdapter.get_schema()` at [`backend/app/adapters/elastic.py:399-416`](../../../../backend/app/adapters/elastic.py#L399-L416) calls `_request(..., translate_errors=False)` and maps HTTP status codes explicitly: 404 → `TargetNotFoundError`, 401/403/5xx → `ClusterUnreachableError`, other 4xx → `ClusterUnreachableError`.

But it does NOT catch the raw `httpx.HTTPError` (or its subclasses) that `_request` re-raises on connection failures when `translate_errors=False`. From [`elastic.py:200-210`](../../../../backend/app/adapters/elastic.py#L200-L210):

```python
for attempt in (1, 2):
    try:
        resp = await self._client.request(**kwargs)
        break
    except connection_excs as exc:
        if attempt == 2:
            if translate_errors:
                raise ClusterUnreachableError(str(exc)) from exc
            raise   # <-- propagates raw httpx.ConnectError (or sibling) to caller
```

**Failure mode:** when a cluster's `base_url` becomes unreachable between registration and a schema lookup (network partition, ES restart, DNS flap), the schema endpoint's caller path is:

1. `GET /api/v1/clusters/{id}/schema?target=products`
2. Router calls `acquire_adapter(cluster).get_schema(target)`.
3. `get_schema()` → `_request("GET", "/{target}/_mapping", translate_errors=False)`.
4. `_request` retries once, then re-raises `httpx.ConnectError`.
5. `get_schema()` has no `try/except httpx.HTTPError` — the raw exception propagates up.
6. Router's `except (ClusterUnreachable, ClusterUnreachableError)` clause does NOT match `httpx.HTTPError`.
7. FastAPI's default 500 handler kicks in → operator sees `INTERNAL_ERROR` instead of `503 CLUSTER_UNREACHABLE retryable=true`.

This is silent — no integration test covers the "connection drops during schema fetch" path because the existing tests either: (a) hit a real ES instance that's always up, or (b) mock at higher layers. So the bug ships under test-green.

**Same shape applies to** any other method that calls `_request(..., translate_errors=False)` without the defensive `try/except`. Currently:
- `list_targets()` — **fixed** by `feat_create_study_target_autocomplete` Story B1 (the going-forward pattern).
- `get_schema()` — **unfixed** (this bug).
- `health_check()` at [`elastic.py:232-298`](../../../../backend/app/adapters/elastic.py#L232-L298) — let me verify; if it uses `translate_errors=False` without the catch, it has the same bug.

## Proposed capabilities

### Option A — Defensive catch in each method (matches Story B1 pattern)

Add `try/except httpx.HTTPError as exc: raise ClusterUnreachableError(str(exc)) from exc` around `_request(..., translate_errors=False)` calls in:

- `get_schema()` — the canonical case this bug names.
- `health_check()` — if it has the same shape (verify at implementation time).
- Any future method that opts out of `translate_errors`.

Pros: localized; the existing per-method status-mapping logic stays intact.
Cons: 4 lines of duplication per call site (3 if we extract a helper).

### Option B — Fix at the `_request` layer

Always translate connection-class exceptions to `ClusterUnreachableError`, regardless of `translate_errors`. Keep `translate_errors=False` semantics for HTTP status codes only (so callers can map 401/403/404/5xx themselves).

Pros: single source of truth; "translate connection failures" becomes the inviolable contract.
Cons: Subtle behavior change — `health_check()` currently uses `translate_errors=False` precisely so it can return `HealthStatus(status='unreachable', ...)` rather than raise. If Option B forces a raise for connection failures, `health_check` must add a `try/except ClusterUnreachableError` clause. Behavior identical at the operator surface but the migration touches every caller.

### Recommended default

**Option A** for parity with the just-shipped B1 fix. Locked decision in the parent plan's Risks table cites Option A explicitly.

If the same bug surfaces in `health_check` or future methods, escalate to Option B in a separate refactor (`infra_adapter_request_unify_connect_translation` or similar).

## Scope signals

- **Backend:** ~5 LOC in `get_schema()` (and possibly the same in `health_check()` if confirmed). One unit test in `backend/tests/unit/adapters/test_elastic_schema.py::TestGetSchemaErrors` mirroring the new `test_connection_error_raises_unreachable` case in `TestListTargets`.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (MVP1, pre-audit_log).

## Why not implemented inline today

Different endpoint surface (`/schema` vs the new `/targets`) with its own test fixtures. Bundling would have:
- Added ~30 LOC of unrelated test coverage to the parent feature's commit history.
- Required a separate audit of `health_check()`'s connect-error behavior (additional rabbit hole).
- Risked muddying the parent feature's review surface.

Inline-fix-vs-defer rubric (CLAUDE.md): the change is ~5 LOC + a unit test. That puts it at the boundary. Tipping factor: the bug pre-existed since `infra_adapter_elastic` (PR #16, 2026-05-10) and has never produced operator pain in MVP1 (single-tenant local deploy = stable network). Low urgency, isolated fix, ship as a `/bug-fix` slice when the operational pain ever surfaces.

## Relationship to other work

- **Pattern-source:** [`feat_create_study_target_autocomplete`](../feat_create_study_target_autocomplete/) Story B1 — adopts the defensive `try/except httpx.HTTPError` as the going-forward standard. This bug applies the same pattern to `get_schema()`.
- **Coordinate-only with:** [`infra_adapter_elastic`](../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — origin of `_request`'s dual-mode (translate vs not) signature.
