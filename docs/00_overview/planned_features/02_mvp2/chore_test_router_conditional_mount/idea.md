# chore_test_router_conditional_mount — defense-in-depth for the dev-only `_test` router

**Date:** 2026-06-09
**Status:** Idea — surfaced during a codebase-wide security review (branch `claude/codebase-security-review-6njwio`)
**Priority:** P2
**Origin:** Security review of the FastAPI app surface; finding in `backend/app/main.py` + `backend/app/api/v1/_test.py`
**Depends on:** None

## Problem

The `_test` router exposes data-mutating endpoints used only for deterministic E2E (seed a completed study, demo reseed, hard-delete studies/judgment-lists/proposals). Today it is registered **unconditionally** at app boot:

`backend/app/main.py:219-221`
```python
app.include_router(
    test_router.router, prefix="/api/v1"
)  # infra_e2e_seed_completed_study — dev-only; 404 outside
```

Containment currently rests entirely on a **per-endpoint** dependency: every route carries `dependencies=[Depends(_require_development_env)]`, which returns 404 whenever `Settings.environment != "development"` (verified — the guard is default-deny, so an accidental `ENVIRONMENT=production` or any unset/misconfigured value correctly disappears the surface). So this is **not** a live vulnerability — the existing gate is sound.

The weakness is structural, not behavioral: the safety is one decorator argument per route, repeated by hand 9 times. The day someone adds a 10th endpoint to this router and forgets the `dependencies=[...]` line, it ships wide open in every environment, and nothing fails — there is no test asserting the invariant. For a router whose endpoints hard-delete rows and wipe/reseed demo data, that is a fragile place to rely on copy-paste discipline.

## Proposed capabilities

### Make "dev-only" structural, not per-route

- **Primary:** attach `_require_development_env` as a **router-level** dependency (`APIRouter(dependencies=[Depends(_require_development_env)])`) so individual routes physically cannot opt out — this is the structural fix and needs no settings access at import time.
- **Optionally also** register the router conditionally at boot. If a module-load environment check is used, read the env directly (`os.environ.get("ENVIRONMENT") == "development"`) rather than building the full `get_settings()` object at import time, to avoid the import-time-settings caveat that bites unit tests imported without the runtime stack. (Note: `main.py`'s CORS block already reads `get_settings()` at module load, so this is a soft preference, not a hard rule — but the router-level dependency above makes the conditional mount unnecessary anyway.) Keep the per-endpoint guards too — belt-and-suspenders.
- Add a guard test that introspects `test_router.router.routes` and asserts every route carries the development-env dependency — so a future un-gated endpoint fails CI instead of shipping.

## Scope signals

- **Backend:** `backend/app/main.py` (conditional include) + `backend/app/api/v1/_test.py` (router-level dep) + a contract/unit guard test.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none (reuses `ENVIRONMENT`).
- **Audit events:** N/A.

## Why filed as an idea rather than fixed inline

Small enough to be inline, but captured during a read-only review sweep with no behavior change today (the surface is already correctly 404'd outside dev). It is a defense-in-depth + regression-guard task whose value is the test asserting the invariant; bundle it into the security-hardening batch. Clean `/impl-execute --ad-hoc` if picked up alone.

## Relationship to other work

Part of the security-review idea sweep on branch `claude/codebase-security-review-6njwio`. Independent of the SSRF, request-ID, agent-confirmation, and CORS siblings.
