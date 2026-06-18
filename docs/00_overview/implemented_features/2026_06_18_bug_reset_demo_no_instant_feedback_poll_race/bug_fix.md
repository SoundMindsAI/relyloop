# Bug fix — bug_reset_demo_no_instant_feedback_poll_race

**Release:** mvp2
**Status:** Complete (PR #562, merged 2026-06-18 `bb247a5c`)
**Type:** bug fix — medium (frontend UX)
**Date:** 2026-06-18

## Problem

Clicking **Confirm** on the home "Reset to demo state" dialog appeared to do nothing — operators clicked again, eventually saw a `409`-driven toast, and never saw the streaming step log. One root cause produced all of it.

## Reproduction

Operator-reported (2026-06-18, home dashboard `http://localhost:3000`): click Reset → Confirm → no visible change → click again → "A reseed is already running" toast → no streaming status during the run.

Regression tests (fail on `main`):

```bash
cd ui && pnpm test --run reset-demo-state-button
```

## Root cause

`startReseed` ([reset-demo-state-button.tsx](../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)) enabled the status poller **before** sending the reseed, and discarded the POST's returned initial status:

```js
setPollingEnabled(true);     // poller's first fetch fires now…
await postDemoReseed(...);    // …racing the POST that writes `running` to Redis
```

Two failures:

1. **Start-up race → frozen UI + no streaming.** The poller's first `GET /reseed/status` could win the race and read `idle` (before the worker wrote `running`). The poller's `refetchInterval` **stops on any non-`running` status** ([demo-reseed.ts:155](../../../../ui/src/lib/api/demo-reseed.ts#L155)), so it stopped permanently. The reseed ran in the background but the dialog stayed frozen on the "are you sure?" screen and the step log never streamed.
2. **No instant feedback → double-click.** The POST returns the initial `running` status but the code threw it away, so the dialog only switched to the progress view after a *separate* status round-trip. Until then the Confirm button stayed active → second click → `409 SEED_IN_PROGRESS` → the toast the operator "finally" saw.

- Owning layer: frontend (React component + the polling hook's start sequencing)
- Origin: [reset-demo-state-button.tsx `startReseed`](../../../../ui/src/components/dashboard/reset-demo-state-button.tsx)

## Fix design (locked decisions)

1. **Reorder + seed the cache.** Send the reseed FIRST, write its returned `running` status straight into the `['demo-reseed','status']` cache via `queryClient.setQueryData`, THEN enable polling. The progress view + step log render instantly off the seeded cache; the race is gone because Redis already holds `running` before the first poll. Cites: TanStack Query optimistic-seed pattern.
2. **Optimistic in-flight state.** A synchronous `submitting` flag disables Confirm and shows "Starting…" the instant it's clicked — immediate acknowledgment, no double-submit. The `if (submitting) return` guard is belt-and-suspenders.
3. **Scope: frontend only.** No backend change. The 2s poll cadence is unchanged — it WAS the streaming; it was just dying at start. (True SSE remains the separate deferred `feat_reseed_status_sse_streaming` idea.)

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| vitest | `ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx` | Confirm seeds the poller cache with the POST's `running` status; Confirm is disabled + "Starting…" while the POST is in flight (second click is a no-op); the cache seed does NOT happen before the POST resolves (no start-up race) |

## Rollout

Frontend-only; no migration, no backend change, no API change. Operators get the responsive behavior on the next `make up` (ui rebuild). Default flow otherwise unchanged.

## Tangential observations

None.
