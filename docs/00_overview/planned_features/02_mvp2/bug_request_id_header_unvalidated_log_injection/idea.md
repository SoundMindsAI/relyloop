# bug_request_id_header_unvalidated_log_injection — client X-Request-ID adopted without validation

**Date:** 2026-06-09
**Status:** Idea — surfaced during a codebase-wide security review (branch `claude/codebase-security-review-6njwio`)
**Priority:** P2
**Origin:** Security review; finding in `backend/app/api/middleware.py`
**Depends on:** None

## Problem

`RequestIDMiddleware` adopts a client-supplied `X-Request-ID` header verbatim with no validation of length or character set:

`backend/app/api/middleware.py:50`
```python
request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid_utils.uuid7())
```

The adopted value is then (a) bound to the structlog context for every log line emitted during the request (`middleware.py:56`) and (b) echoed back in the `X-Request-ID` response header (`middleware.py:66`). Because it is treated as fully opaque, a client can supply:

- **Log-injection payloads** — CRLF / control characters that, once interpolated into a JSON or line-oriented log record consumed by a downstream aggregator, can forge or split log lines (anti-forensics, alert evasion). The structlog JSON renderer escapes within a string field, but any non-JSON sink or partial log scrape is exposed.
- **Unbounded length** — a multi-megabyte header value is copied into the contextvar and emitted on every log line for the request, inflating log volume/memory on a per-request basis (cheap, repeatable resource amplification).
- **Response-header reflection** — the value is written straight back into a response header; depending on the ASGI server's header validation this is a header-injection surface.

This is **Low** severity in the MVP1 posture (single-tenant, local, no auth), but it is a gratuitous trust of unvalidated client input on the request-correlation path that every request flows through, and it is a one-function fix.

## Proposed capabilities

### Validate or re-mint the request ID

- Accept a client `X-Request-ID` only if it matches a strict pattern (e.g. `^[A-Za-z0-9._-]{1,128}$`); otherwise mint a fresh UUIDv7 and ignore the client value. This preserves the documented idempotent-retry-correlation use case for well-behaved clients while removing the injection/amplification surface.
- Add unit tests: oversized value re-minted, CRLF value re-minted, valid value adopted, absent value minted.

## Scope signals

- **Backend:** `backend/app/api/middleware.py` (one function) + a unit test file.
- **Frontend:** none (the UI's `api-client.ts` already sends UUIDv7s, which match the pattern).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why filed as an idea rather than fixed inline

Genuinely borderline — this is close to the "≤50 LOC, no design fork" inline-fix threshold and could reasonably be fixed in a single small PR. It is captured here because it surfaced during a read-only review sweep alongside several sibling findings; bundle it into the same security-hardening batch rather than touching middleware out of band. If picked up first, it is a clean `/impl-execute --ad-hoc`.

## Relationship to other work

Part of the security-review idea sweep on branch `claude/codebase-security-review-6njwio` (siblings: cluster-URL SSRF, agent-confirmation matching, CORS-credentials, test-router mount). Independent of all of them.
