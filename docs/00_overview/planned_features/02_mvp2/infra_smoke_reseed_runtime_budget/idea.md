# infra_smoke_reseed_runtime_budget — Playwright demo-ubi reseed exceeds the smoke-job budget once Solr actually boots

**Date:** 2026-06-01
**Status:** Idea — captured at `infra_solr_smoke_stability` PR #383 merge time
**Priority:** P1 — smoke job stays red on every branch until this ships. With Solr now unblocked (PR #383's Lever-0 perms fix), the demo-ubi.spec.ts `beforeAll` reseed runs the full 6-scenario set and the smoke job hits its 25-min cap. This is the last barrier to a green smoke job on every PR.
**Origin:** PR #383 run 26790636716. The smoke job progressed through three failure modes during PR #383's CI iterations: (1) Solr container crashed in 542ms (filesystem permissions — fixed inline as Lever 0); (2) Playwright `beforeAll` hook hit 30s timeout (fixed inline); (3) job-level `timeout-minutes: 15` cap fired (bumped to 25 inline). The fourth iteration timed out the new 25-min cap too — the Playwright reseed is simply too long for any reasonable per-PR smoke budget. Per the spec's D-6 forcing function, this follow-up MUST be filed AND linked from PR #383's body before merge.

## The captured evidence

Smoke run 26790636716 timeline:
- 0:00 — make up succeeds (containers all `exit=0 health=healthy` including Solr)
- 0:01 — pytest smoke (LLM judgment generation + study + alignment guard + digest) passes
- 0:02 — pnpm install + Playwright install
- 0:03 — Playwright E2E starts; `demo-ubi.spec.ts` `beforeAll` calls `/api/v1/_test/demo/reseed`
- 25:18 — job-level timeout-minutes: 25 cap fires; "The operation was canceled"

The reseed never reached terminal status within 25 min on the smoke runner. AC-8 of the spec for `feat_demo_ubi_study_comparison` bounds the reseed at 24 min, but that's the in-flight orchestrator budget — adding the Playwright + smoke-job setup overhead pushes total wall-clock past 25 min.

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

## Three candidate fixes (pick at spec time)

### Option A — Skip `demo-ubi.spec.ts` on the smoke job

**Edit shape:** add `--grep-invert "demo-ubi"` (or equivalent Playwright config exclude) to the smoke job's `pnpm --dir ui test:e2e` step. Single-line YAML edit.

**Trade-off:** demo-ubi keeps running locally + can move to a separate nightly CI job. Loses per-PR signal for the demo-ubi UBI-comparison surface but that surface isn't part of the smoke job's stated role ("operator-path tutorial flow"). **Recommended default** — cleanest scope, single-file fix, ships in one PR.

### Option B — Bump job timeout to 35-40 min

**Edit shape:** `timeout-minutes: 25 → 35` in pr.yml's smoke-test job. Single-line YAML edit.

**Trade-off:** burns ~$0.10/PR more in GHA minutes (free on public repos, but slow operator iteration). Other smoke E2Es sit under the same cap, so any future test that genuinely needs a quick fail waits 35 min instead of 25. Doesn't fix the underlying "reseed is the bottleneck" issue — just pushes the cap.

### Option C — Trim reseed to a subset on the smoke path

**Edit shape:** add `RELYLOOP_RESEED_SCENARIOS_ONLY=acme-products-prod,news-search-staging,acme-kb-docs-solr` env var that the reseed orchestrator honors (one scenario per engine). The smoke job sets it; local dev doesn't (full 6-scenario reseed preserved). Multi-file scope: env-var plumbing + orchestrator change + demo-ubi.spec test-fixture change.

**Trade-off:** ~2-3 hours of work for the full path. Best long-term fit — preserves demo-ubi smoke coverage AND keeps reseed runtime bounded. But too big to ship inline on PR #383.

## Why deferred (not fixed on PR #383)

Per CLAUDE.md "fix inline by default" rule, options A and B are both inline-cheap (single-line YAML edits). The reason this didn't ship inline on PR #383 anyway: the user explicitly chose "merge what's shipped now, file follow-up" when asked. The PR's stated outcomes already shipped — diagnostics fold-in + Lever 0 + Lever 1 + runbook + CLAUDE.md row + two inline tangential fixes. Smoke staying red is the documented D-6 fast-lane posture. Keeping the option-A/B/C decision as its own follow-up keeps PR #383 reviewable as a Solr-stability story instead of widening it into a smoke-job-architecture story.

## Relationship to other work

- **Sibling of** `infra_solr_smoke_stability` ([PR #383](https://github.com/SoundMindsAI/relyloop/pull/383), merged with smoke red per D-6). The smoke-solr-stability runbook (`docs/03_runbooks/smoke-solr-stability.md`) needs a new lever-cascade entry after this work ships, OR a section noting that reseed-runtime is a separate concern from Solr stability.
- **Independent of** `infra_solr_ci_readiness` Phase 1 (backend half — shipped, unaffected).

## Scope signals

- **Backend:** Option C only — env-var plumbing for reseed scenario filter.
- **Frontend:** Option C only — demo-ubi.spec test-fixture change.
- **Migration:** none.
- **Config:** smoke job environment (one new env or one filter flag, depending on option).
- **Audit events:** N/A.
- **Operator impact:** Option A = none (per-PR signal change only); Option B = none; Option C = none (env-var defaults preserve local behavior).
