# Idea — Starlette `Request(scope=...)` instantiation poisons subsequent FastAPI `Depends` tests in the same file

**Date:** 2026-05-27
**Status:** Idea — bug captured during feat_index_document_browser Story 2.1
**Type:** `bug_`
**Priority:** P3 (low — workaround documented; affects only an obscure test pattern)

## Origin

Surfaced while writing `backend/tests/unit/api/test_strict_query_params.py` for
Story 2.1 of `feat_index_document_browser`. The test file mixed two patterns:

1. Direct dep-callable invocation: `dep(req)` where `req = Request(scope=...)`
   (3 tests).
2. End-to-end FastAPI app + `TestClient` + `Depends(strict_unknown_query_params(...))`
   (1 test).

When run together in pytest, the second test (TestClient invocation with an
unknown query param) returns **200 instead of the expected 422** — the
`Depends` callable is never invoked, even though it's identical code that
returns 422 when called directly.

A minimal repro that touches `Request(scope=...)` in test A and then runs a
fresh `FastAPI() + TestClient + Depends(...)` test B in the same file
reproduces the failure 100%. Moving each pattern to its own file (or removing
the Request instantiation entirely) eliminates the failure.

## Problem

There is shared state somewhere in starlette / FastAPI that is mutated by
`Request(scope={"type": "http", ...})` and breaks subsequent `Depends`
resolution. Possible suspects:

- Pydantic v2 caching of validator chains keyed by something Request mutates.
- Starlette's `_scope_inheritance_cache` or similar module-level lookup.
- FastAPI's `Dependant` cache (the `dependencies_cache` dict on `Dependant`
  instances) — but this is per-router, not global.

The failure is consistent within the relyloop test suite (asyncio_mode=auto,
configfile=pyproject.toml) but does NOT reproduce when the same file is
moved under `/tmp` (rootdir change → different cache state).

## Why deferred

The workaround is simple: keep `Request(scope=...)` patterns and
`FastAPI + TestClient + Depends` patterns in separate test files. The Story 2.1
implementation lives entirely in pure-function dep-callable tests; router-level
behavior is covered by `backend/tests/integration/test_documents_endpoints.py`
where the dep runs through the real app stack and works correctly. So this
isn't a product bug — it's a test-infra footgun.

Capture-as-idea-file (not inline-fix) because:
- Reproducing in isolation requires bisecting starlette / FastAPI internals.
- The fix likely belongs in framework code, not our test setup.
- Workaround is one-line (split the test file) and documented above.

## Proposed capabilities (when this is picked up)

1. Build a minimal failing repro outside relyloop (vanilla pytest + FastAPI
   + httpx project) so the issue can be filed upstream.
2. Bisect starlette versions to find which release introduced the cache.
3. If reproducible upstream, file an issue with FastAPI / starlette.
4. If only reproducible in relyloop, identify the conftest interaction
   (likely the `_clear_settings_caches` autouse fixture).

## Scope signals

- Test-only — no production code change.
- Likely a 1-line conftest tweak or a 1-section README addition to
  `docs/05_quality/testing.md` documenting the pattern to avoid.

## Related ideas

None known; this is the first time the pattern has been hit.
