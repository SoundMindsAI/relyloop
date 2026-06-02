# Pipeline Status — Curated query-template library + per-engine tunable-params cheatsheets

**Release:** mvp2

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-02
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (7 cycles; 12 findings — 2 High, 9 Medium, 1 Low — all Accepted; final cycle 0 findings)
- Phases: 1 total, 1 covered by spec (single-phase)

## Plan
- Status: Approved
- Date: 2026-06-02
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (5 cycles; 8 findings — all Medium — all Accepted; final cycle 0 findings)
- Stories: 8 total across 3 epics
- Phases covered: 1 of 1 (single-phase)

## Implementation
- Status: **Complete** (PR #416, squash-merged `24568c8e` on 2026-06-02)
- Branch: `chore/template-library-expansion` (merged)
- Stories completed: 8 of 8 (Epic 1: 1.1 / 1.2 / 1.3 — runnable templates + render + invariant tests; Epic 2: 2.1 / 2.2 / 2.3 / 2.4 — three cheatsheets + index + tutorial + cheatsheet doc-consistency test; Epic 3: 3.1 — FR-7 **SHIPPED** client-side: `template-descriptions.ts` + optional `learnMoreHref` prop on `InfoTooltip` + modal wiring)
- CI status: 12/13 checks green; `smoke` cancelled at the 25-min cap (the known, deferred `infra_smoke_reseed_runtime_budget` issue — unrelated to this content/docs PR). Merged on the documented fast lane (D-6; `main` has no required status checks).
- Final gates green: `make lint && make typecheck` clean; `make test-unit` 2149 passed; `make test-contract` 327 passed; `pnpm test` 1005 passed; `pnpm lint && pnpm typecheck && pnpm build` clean; `ruff format --check backend/` clean.
- Cross-model review: Gemini Code Assist (4 findings — 3 accepted, 1 rejected with counter-evidence) + GPT-5.5 final review (converged after 5 cycles — 6 findings accepted-and-fixed across cycles 1–4, 0 in cycle 5). Adjudication summaries posted on PR #416.
- No migration (Alembic head stays at `0022_solr_engine_auth_check`).
- AC-3 byte-stability: the four existing demo templates untouched (asserted by `test_demo_template_unchanged`).
- Tangential idea filed: `bug_studies_detail_vitest_intermittent_timeout` (intermittent full-suite vitest timeout on the Study detail page, pre-existing).
