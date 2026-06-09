# chore_cors_credentials_origin_hardening — guard allow_credentials against over-broad origins

**Date:** 2026-06-09
**Status:** Idea — surfaced during a codebase-wide security review (branch `claude/codebase-security-review-6njwio`)
**Priority:** Backlog
**Origin:** Security review of the FastAPI app surface; finding in `backend/app/main.py`
**Depends on:** Auth / browser-session surface (multi-tenant, backlog) — the exploit is latent until then

## Problem

CORS is configured with `allow_credentials=True` and an operator-configurable origin list:

`backend/app/main.py:195-207`
```python
_cors_origins = [o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        ...
    )
```

The MVP1 default (`http://localhost:3000,http://127.0.0.1:3000`) is safe, and `allow_origins=["*"]` combined with `allow_credentials=True` is actually neutralized by Starlette/the CORS spec (a literal `*` is not reflected when credentials are allowed). The real footgun is a future operator setting a **broad but non-`*` origin** (e.g. a wildcard-ish entry, or pasting in a list that includes an attacker-influencable origin) while `allow_credentials=True` stays hardcoded. Once RelyLoop has any browser-bound credential (cookie/session — arrives with the multi-tenant auth surface, currently backlog), that combination lets a malicious origin in the list make credentialed cross-origin requests and read the responses.

Today there is **no auth and no browser credential**, so there is nothing for `allow_credentials=True` to leak — this is a **latent** hardening item, not a live vulnerability. It is filed so the footgun is closed *before* the auth surface that arms it lands, not after.

## Proposed capabilities

### Make the credentials/origins combination safe by construction

- When the auth surface lands, validate the CORS config at startup: reject (fail-fast) any wildcard/over-broad origin entry while `allow_credentials=True`, or decouple credentialed CORS from the public-origin list entirely.
- Consider gating `allow_credentials` on whether a browser-session credential actually exists (it does not in MVP1), so the flag is not "on" ahead of need.
- Document the safe configuration in `docs/04_security/` and `docs/01_architecture/deployment.md`.

## Scope signals

- **Backend:** `backend/app/main.py` CORS setup + a startup validation helper; a unit/contract test asserting the rejected combinations.
- **Frontend:** none.
- **Migration:** none.
- **Config:** `CORS_ALLOW_ORIGINS` semantics documented; possibly a new `CORS_ALLOW_CREDENTIALS` toggle.
- **Audit events:** N/A.

## Why filed as an idea (and in 04_ga) rather than fixed inline

The exploit is only reachable once browser-bound credentials/auth exist, which is the multi-tenant/SSO surface deferred to the backlog/GA — so this is a **different-release** hardening concern, not current-MVP work, and it depends on a design (how auth + CORS interact) that does not exist yet. Filing in `04_ga/` (production-readiness hardening) matches where the dependency lands.

## Relationship to other work

Part of the security-review idea sweep on branch `claude/codebase-security-review-6njwio`. Couples to the future auth/multi-tenant surface (backlog). Independent of the SSRF, request-ID, agent-confirmation, and test-router siblings.
