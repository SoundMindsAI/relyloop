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
- Status: Not started
