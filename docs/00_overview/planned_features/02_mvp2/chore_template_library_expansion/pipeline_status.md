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
- Status: PR created (chore/template-library-expansion branch)
- Branch: `chore/template-library-expansion`
- Date: 2026-06-02
- Stories completed: 8 of 8 (Epic 1: 1.1 / 1.2 / 1.3 — runnable templates + render + invariant tests; Epic 2: 2.1 / 2.2 / 2.3 / 2.4 — three cheatsheets + index + tutorial + cheatsheet doc-consistency test; Epic 3: 3.1 — FR-7 **SHIPPED** client-side: `template-descriptions.ts` + optional `learnMoreHref` prop on `InfoTooltip` + modal wiring)
- Gates green locally:
  - `make lint && make typecheck` clean
  - `make test-unit` — 2145 passed (incl. 30 new template-library tests + 14 new cheatsheet tests + 2 new Solr library render tests + 9 new ES library render tests)
  - `make test-contract` — 327 passed (66 unrelated Postgres-unreachable skips)
  - `pnpm test` — 1003 passed (incl. 5 new template-descriptions vitest cases)
  - `pnpm lint && pnpm typecheck && pnpm build` clean
  - `ruff format --check backend/` clean (CI parity)
- No migration (Alembic head stays at `0022_solr_engine_auth_check`).
- AC-3 byte-stability: the four existing demo templates untouched (asserted by `test_demo_template_unchanged`).
