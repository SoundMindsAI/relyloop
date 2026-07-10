# GitHub webhook has no delivery-id replay cache

**Date:** 2026-07-10
**Status:** Idea — surfaced during the 2026-07-10 full-codebase security audit (backend API agent, finding #5)
**Priority:** Backlog
**Origin:** Security audit finding #5 — `backend/app/api/webhooks/github.py:87-235`
**Depends on:** None

## Problem

The GitHub webhook handler verifies the HMAC signature correctly and *before*
any mutation, but does not deduplicate on the `X-GitHub-Delivery` id. Replay
protection today relies entirely on DB state-machine idempotency
(`mark_proposal_pr_merged` returns `None` on a duplicate transition), so a
replayed valid delivery is a harmless no-op **for the current handlers**. The
gap is defense-in-depth: a future non-idempotent webhook handler would inherit
no replay protection, and there is no explicit audit trail of duplicate
deliveries.

## Proposed capabilities

### Delivery-id dedup

- Record each processed `X-GitHub-Delivery` id (short-TTL Redis key or a small
  `webhook_deliveries` table) after successful signature verification.
- On a repeat delivery id, short-circuit to a 200 no-op before dispatching to
  the handler, so replay safety no longer depends on each handler being
  idempotent.

## Scope signals

- **Backend:** `backend/app/api/webhooks/github.py`; either a Redis dedup key or
  a new `webhook_deliveries` table + repo function.
- **Frontend:** none.
- **Migration:** one, if the table approach is chosen (Redis approach: none).
- **Config:** possibly a TTL setting.
- **Audit events:** could emit a `webhook.duplicate_delivery` event at MVP3.

## Why deferred

Current handlers are idempotent via the DB state machine, so there is no live
correctness or security incident — the audit rated this acceptable/Low. The
table approach needs a migration and the change spans signature verification +
dispatch. It is a natural GA-hardening / defense-in-depth item to pick up when
a non-idempotent webhook handler is first added (defer-until-incident).

## Relationship to other work

Extends `feat_github_webhook` (`implemented_features/`). Related to the
existing `bug_webhook_concurrent_merge_race_timing_sensitive` MVP2 item (both
concern webhook delivery robustness), but distinct: that one is a concurrency
race, this one is replay dedup.
