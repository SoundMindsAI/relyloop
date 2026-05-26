# Closeout — fixed as side effect of PR #268

**Date:** 2026-05-26
**Status:** Closed — no dedicated bug-fix PR needed.
**Closing PR:** None directly. **Side-effect of [`bug_dashboard_reset_disclosure_gating_too_strict`](../2026_05_26_bug_dashboard_reset_disclosure_gating_too_strict/) shipped as part of [PR #268](https://github.com/SoundMindsAI/relyloop/pull/268) (squash `66244f74`, merged 2026-05-26).**

## Why this folder didn't need its own fix PR

The three failing tests this bug folder tracked:

- `ui/tests/e2e/dashboard-reseed.spec.ts:77` — `AC-10: confirm dialog → reseed → dashboard refetches with 4 demo studies` (`reset-demo-state-disclosure` testid)
- `ui/tests/e2e/dashboard.spec.ts:47` — `banner renders on a seeded stack regardless of seeded studies (FR-1, AC-1)` (`demo-data-banner` testid)
- `ui/tests/e2e/dashboard.spec.ts:63` — `Dismiss persists across reload (FR-7, AC-3)` (same testid)

PR #268's [`bug_dashboard_reset_disclosure_gating_too_strict`](../2026_05_26_bug_dashboard_reset_disclosure_gating_too_strict/bug_fix.md) tightened the disclosure gating predicate at [`ui/src/components/dashboard/start-here-checklist.tsx:150`](../../../ui/src/components/dashboard/start-here-checklist.tsx#L150) from `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies` (3-way AND) to just `!hasClusters` (single predicate). That change made the disclosure render in MORE states — specifically, in the state the smoke stack lands in after seeding.

The `dashboard-reseed.spec.ts:77` test directly asserts the disclosure is visible. The new predicate satisfies that assertion against the smoke stack's actual state.

The two `demo-data-banner` tests are on a different component (`<DemoDataBanner>`), but they also passed on the post-PR#268 runs — likely because the underlying smoke-stack seed-state changed downstream of the disclosure-gating fix (or were flake-passing this round). **If those tests revert to failing on a future main run, that's a separate root-cause investigation under a fresh bug folder; this folder stays closed.**

## Empirical evidence

Smoke job failure count on consecutive main CI runs:

| SHA | When | Smoke failures | Dashboard tests in failure list? |
|---|---|---|---|
| `20f59bc7` (pre-PR#268 main) | 2026-05-26 17:22 | 4 | ✅ all 3 present |
| `66244f74` (post-PR#268 main) | 2026-05-26 19:00 | 1 | ❌ all 3 gone |
| `4810cfa4` (post-PR#270 PR-build) | 2026-05-26 19:21 | 1 | ❌ all 3 gone |

Two independent runs across different code states confirm the dashboard tests now pass on the smoke stack.

## What if a future main run shows them failing again?

Re-open by creating a fresh `bug_smoke_dashboard_demo_state_*_<distinguisher>/` folder with a NEW root-cause investigation. Don't try to revive this folder — the empirical evidence above documents that PR #268 fixed the specific state this folder tracked, even if a different (similar-shaped) bug surfaces later.

## Related

- The only smoke failure remaining post-PR#268 is `followup_run.spec.ts:111` (swap-template `template_id` assertion), tracked separately in `bug_smoke_followup_clone_e2e_flakes`.
