# E2E `studies-create-target-dropdown.spec.ts` times out reliably

**Date:** 2026-05-20
**Status:** Idea — surfaced during `feat_create_study_target_autocomplete` Story F2 implementation; the new E2E happy-path spec is currently `test.skip`'d.
**Origin:** Story F2's plan §3.4 calls for a real-backend E2E that picks a target from the dropdown (not manual mode). I authored [`ui/tests/e2e/studies-create-target-dropdown.spec.ts`](../../../../ui/tests/e2e/studies-create-target-dropdown.spec.ts) but it times out at 120s consistently. The other coverage layers pass (8 hook unit tests + 6 modal vitest cases + 4 existing builder E2E with the manual-mode click), so the feature ships without this single spec — but the dropdown-mode browser path lacks end-to-end verification.
**Depends on:** None — `feat_create_study_target_autocomplete` is shipping.

## Problem

The skipped test seeds two ES indices via Playwright's `request.put` (Node), opens the create-study modal, picks the seeded cluster via the cluster `<EntitySelect>` (which works — that's `cs-cluster`, exercised by the existing builder spec), then tries to `dispatchEvent('click')` on the target `<EntitySelect>` (`cs-target`). The target trigger either never becomes enabled or the popover never reveals option entries — the test hangs until timeout, then the cleanup `request.delete` errors because the browser context closed.

Observed symptoms:
- API endpoint `GET /api/v1/clusters/{id}/targets` returns the seeded indices correctly when called directly from `request.get` (pre-flight verification step passes).
- The 4 existing `studies-create-builder.spec.ts` cases pass against the same rebuilt stack (with my F2's manual-mode-flip prepended).
- Page snapshot at timeout shows the operator already navigated back to `/studies` — modal is closed. Not clear whether the modal closed on a stray click during dispatch, or whether the snapshot is post-timeout cleanup state.

## Why deferred

- Story F2's spec was bounded; the failure mode is in the test infrastructure, not the product code. The dropdown-mode hook + modal logic is independently covered by 14 vitest cases.
- Live-debugging Radix's Select portal under Playwright's `dispatchEvent('click')` + scrolled-popover-into-view interactions needs a focused session — the existing builder/validation E2E specs use `pickEntity()` helper with the same pattern and DO work for `cs-cluster` / `cs-qs` / `cs-jl` / `cs-tpl`, so something about `cs-target` (or its render branch transition timing) is different.
- The bundled-into-this-PR alternative (`test.skip` + capture this idea) keeps PR scope tight; tackling the flake separately keeps debugging surface narrow.

## Proposed capabilities

### Capability 1 — Get the spec passing

- Debug the actual hang point with `--headed` + `--debug` or with Playwright's trace viewer.
- Likely root causes to investigate (ordered by suspected probability):
  1. The `cs-target` trigger's `data-testid` is preserved across the disabled-`<Select>` → real-`<EntitySelect>` render branch transition; perhaps Playwright's locator caches the disabled element and never re-resolves. Try `await page.locator('[data-testid="cs-target"]').waitFor({ state: 'enabled' })` instead of the `toBeEnabled` matcher.
  2. The targets query's `staleTime: 30_000` may serve cached empty data from a prior test in the same session; force a fresh fetch by adding the cluster pick to invalidate the cache, or set `staleTime: 0` for this test's QueryClient (not possible in E2E — the real app is running).
  3. After the cluster pick, the modal re-renders with the new EntitySelect; the focus-trap inside `<Dialog>` may grab focus away from the new trigger between the pick and the next interaction. Try waiting for the loading placeholder text to clear before clicking.
- Acceptance: the existing test body in `studies-create-target-dropdown.spec.ts` runs to completion under ≤90s without flakes for 5 consecutive CI runs.

### Capability 2 — (Optional) Add a `pickTarget()` helper to `tests/e2e/helpers/seed.ts`

If the root cause is general (re: `cs-target` render branch timing), factor a helper so future create-study specs can pick a target from the dropdown without re-implementing the dispatch pattern.

## Scope signals

- **Backend:** N/A — the endpoint is correct (proven by the unit + integration + contract tests + the manual `curl` against the rebuilt stack).
- **Frontend:** N/A — modal renders correctly (proven by the 6 vitest modal cases against jsdom).
- **E2E only:** 1 spec file. ~140 LOC including the cleanup helpers; the spec body is ~100 LOC.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A (MVP1, pre-audit_log).

## Relationship to other work

- **Independent of** [`feat_create_study_target_autocomplete`](../../00_overview/implemented_features/<YYYY_MM_DD>_feat_create_study_target_autocomplete/) (this idea's parent — will move post-merge).
- **Sibling pattern to** the prior `chore_create_study_modal_e2e_stability` (PR #161) which un-skipped a different create-study modal Playwright flake via the `dispatchEvent('click')` swap. Same family of issues; likely the same fix family.
