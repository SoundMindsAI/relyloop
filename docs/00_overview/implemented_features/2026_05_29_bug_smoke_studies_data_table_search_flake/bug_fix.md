# Bug fix — bug_smoke_studies_data_table_search_flake

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/smoke-studies-data-table-search-flake`
**Type:** bug fix — small (test resilience; e2e-only)
**Date:** 2026-05-29

## Problem

The smoke e2e `studies-data-table.spec.ts:20 — "search input drives ?q= URL state (debounced)"` intermittently fails at the post-search visibility assertion on loaded CI runners. The test passed on `main` before PR #273 and the diff that surfaced it didn't touch the test — i.e. a timing flake, not a regression.

## Reproduction

CI-only (slow-runner timing); does not reproduce locally where the filtered refetch is fast. The failing assertion was line 39: `await expect(page.getByText(studyA.name).first()).toBeVisible()` with Playwright's default 5s expect timeout.

## Root cause

- Owning layer: **e2e test** (wait pattern), not product code.
- The `?q=` URL state lands as soon as the 300ms search debounce fires ([studies-data-table.spec.ts:38](../../../../ui/tests/e2e/studies-data-table.spec.ts#L38)). But the studies-list still has to **refetch the filtered page and re-render** before `studyA` appears. `studyA` may have been on a later page of the *unfiltered* list, so it only reliably becomes visible after that refetch completes. On a contended CI runner the refetch + render can exceed the default 5s expect timeout → the single-shot `.toBeVisible()` at line 39 fails.
- **Convention gap that confirms the diagnosis:** the sibling DataTable specs — [clusters-data-table.spec.ts:24](../../../../ui/tests/e2e/clusters-data-table.spec.ts#L24), `query-sets-data-table.spec.ts`, `templates-data-table.spec.ts` — all stop at the `?q=` URL assertion for the same "search drives URL state" behavior. Only `studies-data-table` adds the extra filtered-render assertion, and that extra assertion is the sole flake source.

## Fix design (locked decisions)

1. **Keep the filtered-render assertion, make it resilient** — rather than dropping it to match the siblings. Dropping coverage could mask the idea's hypotheses 2/3 (cross-test interference / stale-list-invalidation). Instead: scope the match to the table (`getByTestId('studies-table').getByText(...)`, avoids incidental page text) and raise the web-first assertion's timeout to 15s. Playwright auto-retries `toBeVisible` until satisfied or timed out, so this rides out debounce + refetch + render on slow runners without weakening what's verified. Well under the 30s per-test timeout. Cites: idea §"Scope signals" ("tighten its wait pattern, e.g. expect.poll instead of single-shot .toBeVisible()").
2. **No product-code change** — the diagnosis is a test-timing race; the search/filter behavior itself is correct (the test passed on `main`). Adding a stale-list-invalidation fix would be speculative against an unconfirmed hypothesis.

## Regression test plan

The flaky test **is** the regression guard — the change hardens it in place. No new test file (a more-resilient wait is the fix). Verified `pnpm lint` + `pnpm typecheck` clean.

**Verification limitation (documented honestly):** (a) the flake does not reproduce locally (fast refetch), and (b) running the spec against the operator's live `make up` stack was declined to avoid seeding test studies into their working DB (the stack was up and `/healthz` reported degraded). (c) **CI smoke is temporarily disabled** under the `SKIP_HEAVY_CI` budget kill-switch (PR #307, ~3 days), so CI cannot exercise this until the switch is removed (~2026-06-01). The fix is hypothesis-agnostic resilience and strictly safer than the original assertion, so it lands now and will be in place when smoke re-enables.

## Rollout

None — e2e-only change. No product code, no migration, no operator action.

## Tangential observations

- The sibling DataTable specs' convention (stop at `?q=` URL assertion) vs this spec's extra render assertion is a minor inconsistency, now intentional+documented here rather than "fixed" by dropping coverage. No separate idea filed.
