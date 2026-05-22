# Pipeline Status — chore_e2e_test_rows_isolation

## Idea
- Status: Complete
- File: idea.md
- Preflight: applied 2026-05-21 (7 edits across idea.md — refreshed deferral rationale post-PR-184; corrected DELETE endpoint inventory; updated Approach C framing for PR #182 auto-seed; rewired upstream link to implemented_features path)

## Spec
- Status: Approved
- Date: 2026-05-21
- File: feature_spec.md
- Cross-model review: GPT-5.5 — 3 cycles (14 + 5 + 7 = 26 findings raised; **25 accepted + 1 deferred** to a v2 follow-up — PLAYWRIGHT_CLEANUP_STRICT=1)
- Phases: 1 (single-phase ship; no deferred phases)
- Major design fix from cycle 1: file-based per-worker JSONL registry instead of in-memory Map (Playwright workers are separate processes — module-scoped state invisible to globalTeardown). 6 new test-only DELETE endpoints under `/api/v1/_test/*` gated by `_require_development_env`.

## Plan
- Status: Approved
- Date: 2026-05-21
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles (9 + 7 + 4 = **20 findings raised, all 20 accepted**, 0 rejected)
- Stories: 2 across 1 epic (1.1 backend 6 DELETE endpoints + tests + docs; 1.2 frontend registry + globalSetup/Teardown + reporter)
- Phases covered: single phase (no deferred phases)
- Critical cycle-1 findings: wrong env var (`PLAYWRIGHT_WORKER_INDEX` → `TEST_WORKER_INDEX`); missing API base URL resolution (now `resolveApiBaseUrl(config)`); pure shared module extraction (`cleanup-core.ts`).
- Critical cycle-2 findings: top-level fs ops could reject globalTeardown (now try/catch/finally); fetch lacks timeout (now AbortController 5s).
- Critical cycle-3 findings: parse failures didn't count toward `failed` invariant (now do); stdout log misstated `entries.length` vs distinct-resource count.

## Implementation
- Status: Complete
- Date: 2026-05-21
- PR: #186 (squash `a444b94`, merged into `main` 2026-05-21)
- Branch: `chore/e2e-test-rows-isolation` (deleted post-merge)
- Stories shipped: 2 of 2 (1.1 backend 6 DELETE endpoints + 20 integration cases + 6 env-guard contract + 11 strictly-new error-code source-presence + 7 OpenAPI tuples; 1.2 frontend per-worker JSONL registry + globalSetup/Teardown + cleanup-reporter + 29 vitest cases)
- CI: green on final HEAD (5/5 jobs incl. smoke 70/70 Playwright)
- Reviews: Gemini Code Assist 3 Medium findings (all rejected with SQLAlchemy AsyncSession-concurrency counter-evidence at `backend/app/api/v1/_test.py:269/353/415`); GPT-5.5 final review 1 High finding (rejected — truncated-diff false positive at `backend/app/db/repo/__init__.py:38–42`).
- Post-merge fix: one follow-up commit on the same branch added `testMatch: ['**/*.spec.ts']` to `ui/playwright.config.ts` after the smoke job tried to load vitest `.test.ts` files as Playwright specs.
- Tangential capture: `chore_e2e_seed_acme_helper_dead/idea.md` — `seedAcmeProductsChain` is dead code (Backlog).

## Done
- Status: Merged
- Date: 2026-05-21
