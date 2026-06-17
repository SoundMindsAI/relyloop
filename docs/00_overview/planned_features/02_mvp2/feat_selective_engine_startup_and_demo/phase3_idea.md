# Phase 3 — SSE migration for reseed status streaming

**Date:** 2026-06-17
**Status:** Idea — defer-until-incident; deferred phase of [`feat_selective_engine_startup_and_demo`](feature_spec.md)
**Priority:** Backlog — pick up only if operators report the existing 2-second poll cadence is insufficient
**Origin:** Deferred from [`feature_spec.md`](feature_spec.md) §3 "Phase boundaries" (Phase 3 row) and Decision D-2. The user's original ask in [`idea.md`](idea.md) included "streaming status updates" for the reset-to-demo flow; Phase 1 satisfies this via the existing 2-second Redis poll loop, which already renders incremental `current_step` updates and a deduped step log.
**Depends on:** Phase 1 shipped. No hard dependency on Phase 2.

## Problem

The Phase 1 spec locked the reseed-status streaming mechanism to the existing 2-second `GET /api/v1/_test/demo/reseed/status` Redis poll (Decision D-2 in [`feature_spec.md`](feature_spec.md)). If operators eventually report that the 2-second granularity is insufficient (e.g., during a long reseed they want sub-second progress updates, or a use-case emerges where the polling lag is operator-visible), the migration path is to replace the poll with a Server-Sent Events stream using the existing chat-agent SSE infrastructure.

This is filed in `99_backlog`-spirit posture: not "deferred until time," but "defer until incident."

## Proposed capabilities

### A. New SSE endpoint alongside the existing poll endpoint

- Add `GET /api/v1/_test/demo/reseed/status/stream` returning `text/event-stream`, gated by `_require_development_env`.
- Use the existing `to_sse_frame()` infrastructure at [`backend/app/agent/events.py`](../../../../../backend/app/agent/events.py) — the same pattern the conversation orchestrator already uses ([backend/app/api/v1/conversations.py:301](../../../../../backend/app/api/v1/conversations.py#L301)).
- Each event emitted whenever the worker updates the Redis status, with the full `ReseedStatusResponse` payload.
- The existing `GET /status` poll endpoint stays in place for backward compatibility — older frontend versions continue to work.

### B. Frontend migration to `EventSource` (or native fetch + ReadableStream)

- Update [`useDemoReseedStatus`](../../../../../ui/src/lib/api/demo-reseed.ts) to use `EventSource` (GET-only) or native `fetch()` + `ReadableStream` for SSE-framed-body-over-POST (the chat-agent pattern documented in [`docs/01_architecture/ui-architecture.md` §"Streaming chat"](../../../../01_architecture/ui-architecture.md)).
- Replace the `refetchInterval` polling loop with stream consumption.
- Same `ReseedStatusResponse` shape consumed identically by the existing dialog.

### C. Operational considerations

- SSE connections hold an HTTP connection open for the duration of the reseed (~5–9 min). Verify the deployment proxy (none in MVP1/2 dev — direct connection; would matter at MVP3+ when a reverse proxy lands).
- Reconnect semantics: on connection drop mid-reseed, the client SHOULD reconnect via `EventSource`'s built-in retry and resume from the latest Redis status.

## Scope signals

- **Backend:** ~50–100 LOC. New SSE route in [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py). Reuses existing `ReseedStatusResponse` model.
- **Frontend:** ~80–150 LOC. Refactor `useDemoReseedStatus` to consume SSE; keep the same hook signature so the dialog component is unchanged.
- **Infra / Compose:** None.
- **CI:** Verify SSE works in the smoke-job environment (long-running HTTP connections through whatever proxy CI uses).
- **Migration:** None.
- **Audit events:** N/A.

## Why defer-until-incident

- The existing 2-second poll already streams incremental progress with step-by-step updates and a deduped step log. No measured latency complaint exists today.
- SSE migration is mostly upside (lower polling load on the API), but the marginal UX improvement is small for a reseed that takes ~5–9 minutes — the operator isn't watching every sub-second update; they're glancing periodically.
- Implementing SSE for a flow nobody has complained about would spend review-cycle + maintenance budget on a non-felt problem.

If operators eventually report the 2-second cadence as choppy or insufficient (e.g., "I clicked Reset and the dialog sat at 'enqueued' for 4 seconds before the first step appeared"), pick this up.

## Relationship to other work

- Builds on Phase 1's reseed-status contract (the existing `ReseedStatusResponse` shape stays the wire payload, only the transport changes).
- Mirrors the chat-agent SSE pattern from `feat_chat_agent` (already shipped — [`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/`](../../../implemented_features/2026_05_12_feat_chat_agent/)) — the patterns are well-trodden.
