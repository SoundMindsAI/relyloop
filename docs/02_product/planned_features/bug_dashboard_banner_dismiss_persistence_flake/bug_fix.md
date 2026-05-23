# Bug fix — dashboard_banner_dismiss_persistence_flake

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/dashboard-banner-dismiss-persistence-flake`
**Type:** bug fix — medium (test-only change, ~15 LOC; latent race verified by design analysis + two CI failures cited in idea)
**Date:** 2026-05-23

## Problem

A Playwright E2E test (`Dismiss persists across reload (FR-7, AC-3)`) flakes intermittently on CI smoke runs because it uses `context.addInitScript` to clear the dismissed flag from localStorage — but init scripts run on EVERY page initialization including `page.reload()`. After the reload step, the script re-clears the flag, racing with React hydration to decide whether the banner stays hidden. The `toBeHidden()` assertion can pass during the brief SSR-snapshot window (banner starts hidden because `getDismissedServerSnapshot()` returns `true`) and then fail once hydration reads the cleared flag and flips the banner visible.

Two consecutive smoke CI runs on PR #193 (`feat_study_preflight_overlap_probe`) failed at this assertion — unrelated to that PR's substance — making the bug "intermittent in CI, latent in the codebase."

## Reproduction

The race is environment-timing-sensitive and doesn't reliably reproduce locally. Verified via:

```bash
# Pre-fix (race-prone — passed 3/3 locally but failed 2/2 on CI runners 26301403853 + 26302635889):
cd ui && npx playwright test tests/e2e/dashboard.spec.ts -g "Dismiss persists across reload"

# Post-fix (deterministic — 5/5 local runs pass):
for i in 1 2 3 4 5; do
  npx playwright test tests/e2e/dashboard.spec.ts -g "Dismiss persists across reload" --reporter=list
done
```

The "stays hidden after reload" assertion is the canonical race site. After the fix it has no init script clearing localStorage during the reload, so the assertion fires against the actual user-facing behavior under test.

## Root cause

- **Owning layer:** UI / test harness (Playwright E2E spec)
- **Origin:** [`ui/tests/e2e/dashboard.spec.ts:64-66`](../../../../ui/tests/e2e/dashboard.spec.ts#L64-L66) (pre-fix) — `context.addInitScript` clearing the dismissed flag runs on every page init including reload.
- **Component logic referenced** (correct; not the bug site): [`ui/src/components/dashboard/demo-data-banner.tsx:55-63`](../../../../ui/src/components/dashboard/demo-data-banner.tsx#L55-L63) — `getDismissedServerSnapshot()` returns `true` (conservative SSR default) so the banner starts hidden until hydration reads the client snapshot. This is the right design — the test pattern was the bug.

## Fix design (locked decisions)

1. **Option A — replace `context.addInitScript` with `page.evaluate` + `page.reload`.** Move the localStorage cleanup to a single `page.evaluate` call that runs once, then reload to ensure a clean React mount with no init-script interference. Cites: idea.md preflight-locked decision; preserves the test's user-facing intent ("banner stays hidden after reload because dismissal persisted") and uses real browser interactions throughout per [CLAUDE.md](../../../../CLAUDE.md) "E2E Testing Rules".
2. **Option B rejected — query localStorage directly.** The preflight rejected this alternative because it would change the test's intent (from "banner stays hidden" to "localStorage was written") and silently miss a future regression where storage writes succeed but the banner re-renders anyway.
3. **Add an inline code comment** referencing this bug folder so the next test author understands why the init-script approach was abandoned. Cites: CLAUDE.md comments policy — the WHY is non-obvious (init scripts re-fire on reload is a Playwright quirk, not standard intuition), so a comment is justified.

### Open questions

None — every fork was an engineering judgment call already locked in idea.md's "Proposed fix (Option A — locked)" section.

## Regression test plan

The fix IS a test edit; the test under repair IS the regression guard. After the fix:

| Layer | Path | What it asserts |
|---|---|---|
| e2e | `ui/tests/e2e/dashboard.spec.ts:63` (`Dismiss persists across reload (FR-7, AC-3)`) | The banner stays hidden after a reload because dismissal persisted to localStorage. The race-prone init-script pattern is removed; reload is the only page-init that fires after the dismiss click, and no init script clears the flag during that reload. |

5/5 local Playwright runs pass post-fix. The remaining 4 dashboard.spec.ts tests are unchanged and pass; the wider E2E suite is unchanged in shape.

## Rollout

None — test-only change, no production code touched.

- No schema, no API, no migration.
- No backend code change. Banner component at `demo-data-banner.tsx` is unchanged — its `useSyncExternalStore` + `getDismissedServerSnapshot` wiring was always correct; the test was fighting it.
- No operator action required.

## Tangential observations

None. The fix is bounded to one test function; no adjacent code was inspected beyond verifying the banner's hydration logic at `demo-data-banner.tsx:55-63` (read-only confirmation that the design is correct, not the source of the bug).
