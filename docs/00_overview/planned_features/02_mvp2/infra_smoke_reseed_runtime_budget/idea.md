# infra_smoke_reseed_runtime_budget — Playwright demo-ubi reseed exceeds the smoke-job budget once Solr actually boots

**Date:** 2026-06-01 (refreshed 2026-06-02 during idea-preflight)
**Status:** Idea — captured at `infra_solr_smoke_stability` PR #383 merge time; refreshed after the smoke-off-by-default flip
**Priority:** P1 — precondition for re-enabling per-PR smoke signal. As of 2026-06-02 the smoke job is OFF by default (gated behind a new `SMOKE_TEST` repo variable in [`pr.yml:42-57`](../../.github/workflows/pr.yml#L42-L57), set OFF specifically because of this issue per [`pr.yml:44-47`](../../.github/workflows/pr.yml#L44-L47)) — so today's *daily* cost is zero. The P1 framing holds because re-enabling smoke (= restoring per-PR signal for the operator-path tutorial flow) requires this fix to land first. Until then, every PR loses the full-stack Playwright signal that smoke is meant to provide.
**Origin:** PR #383 run 26790636716. The smoke job progressed through three failure modes during PR #383's CI iterations: (1) Solr container crashed in 542ms (filesystem permissions — fixed inline as Lever 0); (2) Playwright `beforeAll` hook hit 30s timeout (fixed inline); (3) job-level `timeout-minutes: 15` cap fired (bumped to 25 inline). The fourth iteration timed out the new 25-min cap too — the Playwright reseed is simply too long for any reasonable per-PR smoke budget. Per the spec's D-6 forcing function, the follow-up was filed AND linked from PR #383's body before merge.

## Current CI state (added 2026-06-02)

After this idea was filed, the smoke job was disabled by default 2026-06-02 ([`pr.yml:42-57`](../../.github/workflows/pr.yml#L42-L57) + [`pr.yml:505-523`](../../.github/workflows/pr.yml#L505-L523), referenced from `state.md`). The gate is `if: ${{ vars.SMOKE_TEST == 'true' && vars.SKIP_HEAVY_CI != 'true' }}` — unset → false → skipped. Opt in with `gh variable set SMOKE_TEST --body true`; default state is OFF. This flipped the framing from "smoke is red every PR — fix the budget now" to "smoke is silent every PR — fix the budget so we can turn smoke back on". The fix shape (Options A/B/C below) is unchanged; the urgency framing shifts from "stop the daily bleed" to "restore lost signal".

## The captured evidence

Smoke run 26790636716 timeline:
- 0:00 — make up succeeds (containers all `exit=0 health=healthy` including Solr)
- 0:01 — pytest smoke (LLM judgment generation + study + alignment guard + digest) passes
- 0:02 — pnpm install + Playwright install
- 0:03 — Playwright E2E starts; `demo-ubi.spec.ts` `beforeAll` calls `/api/v1/_test/demo/reseed`
- 25:18 — job-level timeout-minutes: 25 cap fires; "The operation was canceled"

The reseed never reached terminal status within 25 min on the smoke runner. AC-8 of the spec for `feat_demo_ubi_study_comparison` actually bounds the reseed at **1140s (~19 min) hard ceiling** ([feature_spec.md §AC-8](../../implemented_features/2026_05_30_feat_demo_ubi_study_comparison/feature_spec.md) line 324, line 559–563), with §14 estimating a **~28 min worst case** once the Solr scenario lights up. Downstream references in [`pr.yml:518-523`](../../.github/workflows/pr.yml#L518-L523) and [`ui/tests/e2e/demo-ubi.spec.ts:11`](../../../../ui/tests/e2e/demo-ubi.spec.ts#L11) cite 24/25 min — that's drift from the spec, captured but out of scope for this idea. Either reading of AC-8 supports the conclusion: in-flight reseed alone consumes 19–28 min; adding Playwright + smoke-job setup overhead pushes total wall-clock past the 25-min smoke job cap.

## Why this didn't surface before

Before `infra_solr_smoke_stability` PR #383:
- Solr crashed in 542ms (filesystem permissions).
- The demo reseed's Solr scenario (`acme-kb-docs-solr`) was skipped via `infra_solr_ci_readiness` Phase 1's engine-tolerant `is_engine_reachable` check.
- Reseed only did 5 scenarios (4 small + 1 rich ESCI on ES + 1 OpenSearch news) and finished fast.
- Playwright `beforeAll` default 30s timeout was fine.
- Job timeout-minutes: 15 was fine.

After PR #383's Lever-0 perms fix:
- Solr actually boots → engine-tolerant skip no longer triggers → reseed seeds all 6 scenarios including the heaviest (Solr's `acme-kb-docs-solr`).
- Wall-clock blows through 30s hook timeout → fixed inline.
- Wall-clock blows through 15-min job timeout → bumped to 25 inline.
- Wall-clock still blows through 25-min cap.

This is a real architectural reality, not a one-line tweak — the smoke job's budget assumption was wrong from the start, and Solr actually working exposes the wrongness.

## Decisions (locked at preflight 2026-06-02)

- **D-1. Option A is locked as the picked default.** Single-line Playwright `--grep-invert "demo-ubi"` (or equivalent config exclude) on the smoke job's E2E step. Rationale: simplest scope, single-file YAML edit, ships in one PR. The "operator-path tutorial flow" smoke job's stated role does not include demo-ubi (the comparison surface is a separate UBI-vs-LLM exploration target, not part of the first-study path). Option B (timeout bump) papers over the underlying reseed budget without fixing it. Option C (env-var scenario filter) is correct long-term but ~2–3 hours of work spanning backend + frontend + reseed-orchestrator changes — too wide for an unblock-smoke PR.
- **D-2. Option A is locked (operator decision, 2026-06-02).** Option A is the spec; Option C is NOT pursued. Per-PR smoke coverage of the demo-ubi UBI-comparison surface is intentionally accepted as lost on the per-PR lane — demo-ubi still runs on every local `make up` smoke (and a future nightly job if one is scheduled). The smoke job's "operator-path tutorial flow" role does not include the UBI comparison surface, so the loss is acceptable. This was the only genuinely product-shaped question and it is now resolved; spec-gen has no open forks.
- **D-3. Option B is rejected.** Burning the headroom only delays the next failure. The spec's own §14 estimates ~28 min worst case; even 35-min cap leaves <7 min margin and grows linearly with each future demo scenario. Rejected even as a fallback.
- **D-4. Coordinate the YAML edit with `infra_smoke_fork_pr_secret_skip`.** Both ideas target the same `pr.yml` smoke-test job. Whichever ships first should anticipate the other's edit shape to avoid a merge-conflict re-roll.

## Three candidate fixes (pick at spec time)

### Option A — Skip `demo-ubi.spec.ts` on the smoke job

**Edit shape:** add `--grep-invert "demo-ubi"` (or equivalent Playwright config exclude) to the smoke job's `pnpm --dir ui test:e2e` step. Single-line YAML edit.

**Trade-off:** demo-ubi keeps running locally + can move to a separate nightly CI job. Loses per-PR signal for the demo-ubi UBI-comparison surface but that surface isn't part of the smoke job's stated role ("operator-path tutorial flow"). **Locked as default (D-1)** — cleanest scope, single-file fix, ships in one PR.

### Option B — Bump job timeout to 35-40 min

**Edit shape:** `timeout-minutes: 25 → 35` in pr.yml's smoke-test job. Single-line YAML edit.

**Trade-off:** burns ~$0.10/PR more in GHA minutes (free on public repos, but slow operator iteration). Other smoke E2Es sit under the same cap, so any future test that genuinely needs a quick fail waits 35 min instead of 25. Doesn't fix the underlying "reseed is the bottleneck" issue — just pushes the cap. Worst case: spec §14 estimates ~28 min, so even 35 min leaves <7 min margin that erodes with each future demo scenario. **Rejected (D-3)**.

### Option C — Trim reseed to a subset on the smoke path

**Edit shape:** add `RELYLOOP_RESEED_SCENARIOS_ONLY=acme-products-prod,news-search-staging,acme-kb-docs-solr` env var that the reseed orchestrator honors (one scenario per engine). The smoke job sets it; local dev doesn't (full 6-scenario reseed preserved). Multi-file scope: env-var plumbing + orchestrator change + demo-ubi.spec test-fixture change.

**Trade-off:** ~2-3 hours of work for the full path. Best long-term fit — preserves demo-ubi smoke coverage AND keeps reseed runtime bounded. Per D-2, this is the answer if the operator wants per-PR smoke coverage of demo-ubi preserved; otherwise Option A alone is the spec.

## Why deferred (not fixed on PR #383)

Per CLAUDE.md "fix inline by default" rule, options A and B are both inline-cheap (single-line YAML edits). The reason this didn't ship inline on PR #383 anyway: the user explicitly chose "merge what's shipped now, file follow-up" when asked. The PR's stated outcomes already shipped — diagnostics fold-in + Lever 0 + Lever 1 + runbook + CLAUDE.md row + two inline tangential fixes. Smoke staying red is the documented D-6 fast-lane posture. Keeping the option-A/B/C decision as its own follow-up keeps PR #383 reviewable as a Solr-stability story instead of widening it into a smoke-job-architecture story.

## Relationship to other work

- **Sibling of** `infra_solr_smoke_stability` ([PR #383](https://github.com/SoundMindsAI/relyloop/pull/383), merged with smoke red per D-6). The smoke-solr-stability runbook (`docs/03_runbooks/smoke-solr-stability.md`) needs a new lever-cascade entry after this work ships, OR a section noting that reseed-runtime is a separate concern from Solr stability.
- **Independent of** `infra_solr_ci_readiness` Phase 1 (backend half — shipped, unaffected).
- **Sibling "smoke job stays red" issue:** [`infra_smoke_fork_pr_secret_skip`](../infra_smoke_fork_pr_secret_skip/idea.md) — a **separate, independent** smoke-red failure mode (external-fork PRs can't read `OPENAI_API_KEY_TEST`, so smoke hard-fails at the secret sanity-check). Neither fix resolves the other: this idea fixes the reseed wall-clock; that one fixes the fork-secret gate. Both must ship for `smoke` to be green on every PR — and both edit the same `pr.yml` smoke-test job, so coordinate the YAML changes to avoid collisions.

## Open questions for /spec-gen

_None. The single product-shaped question (preserve per-PR demo-ubi smoke coverage?) was resolved 2026-06-02: operator picked Option A (see D-2). All forks locked in D-1..D-4 — spec-gen has no open decisions._

## Scope signals

(Option A is locked per D-2 — signals below reflect that.)

- **Backend:** none.
- **Frontend:** none (no test-file logic change; demo-ubi.spec.ts keeps running locally + unchanged).
- **Migration:** none.
- **Config:** one-line edit to the `pr.yml` smoke-test job's Playwright E2E step (`--grep-invert "demo-ubi"` or equivalent config exclude). Coordinate with `infra_smoke_fork_pr_secret_skip` per D-4 (same job).
- **Audit events:** N/A.
- **Operator impact:** none — per-PR smoke loses demo-ubi coverage only; local `make up` smoke unaffected.
