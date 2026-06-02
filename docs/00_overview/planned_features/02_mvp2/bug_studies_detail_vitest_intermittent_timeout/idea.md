# Idea — `studies/[id]/page.test.tsx` intermittently times out under full-suite vitest run

**Date:** 2026-06-02
**Status:** Idea — captured during `chore_template_library_expansion` post-impl tangential sweep
**Origin:** Noticed while running `pnpm test` as the Story 3.1 (FR-7) pre-push gate during PR `chore/template-library-expansion`. First full-suite run: `src/__tests__/app/studies/[id]/page.test.tsx > Study detail page > renders header, trials table, and digest panel for a completed study` failed with `Test timed out in 5000ms` after 5042ms wall-clock + a JSDOM `Not implemented: navigation to another Document` log line. Second full-suite run (no code change): 1003 / 1003 passed. The same test, run in isolation, passes in <1 s (`pnpm test -- run src/__tests__/app/studies/[id]/page.test.tsx`).

**Priority:** P2 — intermittent. CI is unlikely to flag it consistently (vitest's worker pool dispatches files in different orders run-to-run), but the noise will burn future operator time on false-alarm investigations until the underlying race is fixed.

## Problem

Under the full `pnpm test` run (`vitest run`, default worker pool), the Study-detail-page render test sometimes blocks past the 5 s `testTimeout` default — but the test itself is data-driven from mocked fixtures and shouldn't be doing real I/O. The JSDOM `Not implemented: navigation to another Document` log line strongly suggests something in the test environment (or a sibling test that ran in the same worker before it) is triggering a `window.location` assignment / form submission that JSDOM can't honour.

The failing assertion site:

- File: [`ui/src/__tests__/app/studies/[id]/page.test.tsx:88`](ui/src/__tests__/app/studies/[id]/page.test.tsx)
- Test: `'renders header, trials table, and digest panel for a completed study'`
- Default vitest `testTimeout`: 5000 ms (see `ui/vitest.config.ts` if a project-level override exists).

## Why it wasn't fixed inline on PR `chore/template-library-expansion`

Per CLAUDE.md's tangential-discoveries rubric:

- **Fix path uncertain.** Resolving an intermittent test-isolation flake usually means identifying which OTHER test (running in the same worker before this one) is leaving a stray timer / pending fetch / window listener that this test then trips over. That investigation is open-ended and not a 60-min path — the offending sibling could be anywhere in 135 test files.
- **Cross-subsystem.** The PR's scope is content + docs + tests for the template library. Investigating a Study-detail-page test (an entirely separate UI surface, not touched by the PR) would conflate scope.
- **Pre-existing.** The flake reproduces on `main` — verified by running the full UI suite twice; the second run was green. My PR's only UI change is an additive optional `learnMoreHref` prop on `InfoTooltip` + a new `template-descriptions.ts` map + a Step-3 modal summary block. None of those touch the Study detail page's rendering paths.

The PR proceeded on the green second-run.

## Investigation paths (for whoever picks this up)

1. **Pin the offender via worker-isolation.** Run `pnpm test --pool=forks --poolOptions.forks.singleFork=true` — if the test passes deterministically, the cause is cross-test state in the default worker pool. `git bisect`-style binary-search over the test-file list will identify the polluter.
2. **Hunt for in-test navigation.** Grep the suite for `window.location`, `form.submit()`, anchor clicks with `target="_self"`, and `Link` navigations not wrapped in a mock router. The JSDOM `Not implemented: navigation to another Document` log is emitted from JSDOM's URL-changing code paths.
3. **Raise `testTimeout` defensively.** Last-resort patch if the root cause stays elusive: bump the suite's `testTimeout` to 10000 ms (or set it per-file in the affected test). This is the "deferral" fix — it covers the symptom but not the cause.

## Acceptance signal

- `pnpm test` (default worker pool, all 136 files) runs 10 consecutive times with zero timeouts on the `studies/[id]/page.test.tsx` cases.
- OR: the polluting sibling test is fixed and a one-line regression assertion is added to prevent recurrence.

## Cross-links

- Tangential to: `chore_template_library_expansion` PR `chore/template-library-expansion` (2026-06-02).
- Reminder of the CLAUDE.md "test-isolation bug" failure-mode entry under `## Tangential discoveries`: re-running a flake without investigating is the trap; this idea file IS the investigation paper trail.
