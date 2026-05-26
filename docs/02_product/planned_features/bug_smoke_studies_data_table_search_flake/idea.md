---
name: bug-smoke-studies-data-table-search-flake
description: studies-data-table.spec.ts:20 (search ?q= URL state) newly failed on PR #273's smoke CI but passed on the pre-PR main commit. My PR's diff doesn't touch the test or its code paths — most likely a genuine flake, but the cross-test interference hypothesis is open.
metadata:
  type: bug
---

# Bug — smoke flake: `studies-data-table.spec.ts:20 search input drives ?q= URL state (debounced)`

**Date:** 2026-05-26
**Status:** Idea — surfaced during PR #273 CI watch.
**Priority:** P2 — every-PR smoke red is the same operator-friction class as `bug_smoke_followup_clone_e2e_flakes`. Captures so the next infra-sweep agent can trace.
**Depends on:** None.

## Origin

PR #273 ([`chore_clone_narrow_bounds_full_roundtrip_e2e`](../chore_clone_narrow_bounds_full_roundtrip_e2e/idea.md)) added a new submit-round-trip step to `ui/tests/e2e/study-clone-narrow-bounds.spec.ts`. CI's smoke job on the post-Gemini-fix SHA `5bc44e41` failed with TWO smoke failures:

1. `followup_run.spec.ts:111` — pre-existing flake under `bug_smoke_followup_clone_e2e_flakes` (swap-template `template_id` assertion).
2. **NEW:** `studies-data-table.spec.ts:20 — / studies DataTable › search input drives ?q= URL state (debounced)` — failed at line 39 (`await expect(page.getByText(studyA.name).first()).toBeVisible()`).

Latest main commit before this PR (`4810cfa4`, post-PR #270): only the swap-template failure. The studies-data-table test was passing on main.

## Problem

[`ui/tests/e2e/studies-data-table.spec.ts:20-40`](../../../../ui/tests/e2e/studies-data-table.spec.ts#L20-L40):

1. `seedFullChain(2) + seedStudy(...)` → creates a fresh studyA with a unique UUID-suffixed name.
2. `await page.goto('/studies')`.
3. Wait for `studies-table` testid (5s timeout).
4. Extract `suffix = studyA.name.replace(/^e2e-study-/, '')`.
5. Fill the `data-table-search` input with the suffix.
6. Assert `?q=<suffix>` lands in URL (2s timeout) — PASSES on the failed run.
7. **FAILS HERE:** Assert `studyA.name` is visible on the page.

So the URL update lands but the search-filtered studies-list re-render doesn't reflect studyA in time.

## Hypotheses

1. **Genuine flake** — debounce (300ms) + studies-list refetch + render race; a slow CI runner can miss the timing.
2. **Cross-test interference from PR #273** — `study-clone-narrow-bounds.spec.ts` runs BEFORE `studies-data-table.spec.ts` (alphabetical: `study-c...` < `studies-d...`). The new submit-round-trip step creates an additional study in the DB. If the studies-list query refetches and the new study somehow affects the search/visibility timing... weak hypothesis since the search is by UUID suffix unique to studyA.
3. **Pre-existing fragility surfaced by additional DB state** — `studies-data-table.spec.ts` might be borderline-flaky and the additional study from PR #273's clone pushes it over the edge in CI's resource envelope.

## Reopen criteria / next-action signals

- If a future main CI run (post-PR-#273 merge) shows the test passing → it was a flake; this folder can close-out via the same docs-only pattern used for `bug_smoke_dashboard_demo_state_locator_missing`.
- If subsequent main runs show the test STILL failing → hypothesis 2 or 3 is real; investigate via Playwright trace download (the `playwright-report` artifact) on a failing CI run.

## Scope signals

- **Backend:** None.
- **Frontend:** Possibly (if hypothesis 2/3 → may need stale-list-invalidation fix in studies-list query).
- **Migration:** None.
- **Config:** None.
- **Tests:** the failing test itself; possibly tighten its wait pattern (e.g. `expect.poll` instead of single-shot `.toBeVisible()`).

## Why captured now

PR #273's diff doesn't touch this test or its code paths, so the failure is NOT a regression introduced by #273. Per the tangential-discoveries-rule in CLAUDE.md, smoke flakes that newly appear during CI watch must be captured (operators otherwise have to mentally subtract them from every red verdict). Same pattern as `bug_smoke_dashboard_demo_state_locator_missing` + `bug_smoke_followup_clone_e2e_flakes`.

## Relationship to other work

- **Sibling smoke-flake folders:** [`bug_smoke_followup_clone_e2e_flakes`](../bug_smoke_followup_clone_e2e_flakes/idea.md) — same operator-friction class, different test files.
- **Originating PR:** #273 (`chore_clone_narrow_bounds_full_roundtrip_e2e`) — the PR whose CI surfaced this.
