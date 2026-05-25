# Bug: smoke CI fails on dashboard demo-state locators (`reset-demo-state-disclosure`, `demo-data-banner`)

**Date:** 2026-05-25
**Status:** Idea — captured during feat_study_clone_from_previous PR #243 CI watch

## Origin

Surfaced during the CI watch for [PR #243](https://github.com/SoundMindsAI/relyloop/pull/243) (feat_study_clone_from_previous). The `smoke (operator-path tutorial flow)` Playwright check fails consistently with the same locator-not-found pattern:

- `tests/e2e/dashboard-reseed.spec.ts:77` — `AC-10: confirm dialog → reseed → dashboard refetches with 4 demo studies`
  - `expect(locator).toBeVisible() failed` on `getByTestId('reset-demo-state-disclosure')`
- `tests/e2e/dashboard.spec.ts:47` — `banner renders on a seeded stack regardless of seeded studies (FR-1, AC-1)`
  - `expect(locator).toBeVisible() failed` on `getByTestId('demo-data-banner')`
- `tests/e2e/dashboard.spec.ts:63` — `Dismiss persists across reload (FR-7, AC-3)`
  - Same `demo-data-banner` not found.

**Verified pre-existing on `origin/main`** — the exact same failures are reproduced on run [`26397500888`](https://github.com/SoundMindsAI/relyloop/actions/runs/26397500888) (the most-recent `pr` workflow run on `main` — push event, headSha `70b2ae46`, the `fix(healthz)` PR #236 merge). Same locator strings, same line numbers, same test names.

PR #243 does NOT touch the dashboard surface (`/` route, `demo-data-banner` component, `reset-demo-state-*` testids) or the dashboard's Playwright specs. The clone feature only touches `/studies` + `study-detail` action bar + `create-study-modal`.

## Problem

Both `getByTestId('reset-demo-state-disclosure')` and `getByTestId('demo-data-banner')` are NOT being rendered on the smoke-stack's `/` route. Either:

1. The dashboard component that mounts these testids was renamed/removed/conditionally-hidden on a recent main commit but the Playwright specs weren't updated — strict spec-vs-code drift, OR
2. The demo-data seeding (which the dashboard depends on for the banner to render) doesn't complete before the test asserts — race / setup ordering bug, OR
3. The `feat_home_demo_reseed_endpoint` shipped in PR #228 / `chore_tutorial_polish` removed the `<DemoDataBanner>` or `<ResetDemoStateDisclosure>` component without a matching spec update.

`grep` for the testids in the repo (run from main) will tell which option applies: if the testid is GONE from the component tree, it's option (1); if it's still there but only behind a condition, it's likely option (2) or (3).

## Why deferred

Out of scope for PR #243 — the feat_study_clone_from_previous feature touches `/studies` + `study-detail` + `create-study-modal`, none of which the failing tests cover. Fixing the smoke regression requires investigation of the dashboard / demo-data path, which is unrelated to clone-from-previous.

The PR can't be merged with a red smoke check, BUT the same smoke is red on main → the gate is broken on main too. Two options for unblocking #243:

- **(a) Bypass route:** if branch protection allows admin merge with a failing smoke check (likely yes given that main itself currently has a failing smoke), merge #243 anyway with an explicit "smoke is pre-existing red on main, see [this bug folder]" PR comment.
- **(b) Fix route:** triage and fix this bug first as a separate small PR (off main), get main's smoke green, then re-trigger CI on #243.

Route (b) is the cleaner workflow but adds a serial dependency. Route (a) is acceptable given the main-branch baseline state.

## Scope signals

- E2E test / Playwright concern (not unit or integration)
- Dashboard demo-data surface (`/` route, `demo-data-banner`, `reset-demo-state-disclosure`, `reset-demo-state-trigger`)
- Possibly seeded by `feat_home_demo_reseed_endpoint` (PR #228) or `chore_tutorial_polish` (PR #64)
- Smoke job uses `OPENAI_API_KEY_TEST` secret and operator-tutorial flow — the broken state may have been introduced when a sibling PR changed the dashboard component without updating the specs.

## Proposed investigation steps

1. `grep -rn "reset-demo-state-disclosure\|demo-data-banner" ui/src/` on main → confirm the testids exist in component code.
2. If they exist: render `/` locally with the smoke seed via `pnpm run dev` + `make seed-demo` and inspect what's actually in the DOM. Compare to the spec's expected state.
3. If they don't exist: bisect the last 10 main commits via `git log --oneline -20 -- ui/src/app/page.tsx ui/src/components/dashboard/` to find which PR removed/renamed them.
4. Confirm fix locally + small dedicated PR off main → green → re-trigger #243.
