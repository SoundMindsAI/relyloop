# Pipeline Status — UBI Judgments (engine-neutral User Behavior Insights)

## Idea
- Status: Complete
- File: [`idea.md`](idea.md)
- Origin: external review 2026-05-22; 2026-05-27 reframe (Solr bundle); 2026-05-29 `feat_ubi_onramp` merged back in; 2026-05-29 preflight refresh

## Spec
- Status: Approved
- Date: 2026-05-29
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 passed (3 cycles; cap hit; 10 findings — 1 H + 1 M cycle 1/2 + 2 H + 4 M + 2 L cycle 3 — all accepted and applied in place; see spec D-10)
- Phases: 1 default (single-phase delivery); contingency Phase 2 split decided at impl-plan-gen time if bundled diff exceeds ~1500 LOC
- Scope: ~700 LOC backend + ~350 LOC frontend + ~300 LOC tests + 1 additive Alembic migration (`0021_judgment_lists_generation_params.py`)

## Plan
- Status: Approved
- Date: 2026-05-29
- File: [`implementation_plan.md`](implementation_plan.md)
- Cross-model review: GPT-5.5 passed (3 cycles; cap hit; all 3 findings accepted — see plan footer)
- Stories: 14 across 5 epics
- Phases covered: Phase 1 (all 11 FRs, single-phase delivery per spec D-6)

## Implementation
- Status: **In progress — Epic 1 of 5 complete** (branch `feat/ubi-judgments`, parent `main` at `68fa357c`)
- Pacing: Epic by epic, pause between each (operator confirmation 2026-05-29; multi-session execution to respect single-conversation context limits)

### Done

| Epic | Story | Description | Commit |
|---|---|---|---|
| 1 | 1.1 | Migration `0021_judgment_lists_generation_params` (JSONB column for UBI worker resume) | `5acdee15` |
| 1 | 1.2 | `domain/ubi/` pure-domain library (features, async converter Protocol + 3 impls, position-bias prior, 58 unit tests) | `6036586a` |
| — | — | Planning bundle (idea refresh + spec + plan + dashboards) | `84c810aa` |

### Next session — resume at Epic 2

Run: `/impl-execute docs/00_overview/planned_features/02_mvp2/feat_ubi_judgments/implementation_plan.md 2.1`

Epic 2 stories (the next 3 to ship):

| Story | Description | Estimated scope |
|---|---|---|
| 2.1 | `UbiReader` service — engine-agnostic two-index scan + client-side join | ~200 LOC backend + 2 integration tests (the canned-features + the no-cluster-writes guard) |
| 2.2 | Readiness service + `start_ubi_judgment_generation` dispatcher refactor — shared helpers extracted from `start_judgment_generation` (parity-preserving) | ~250 LOC backend + 1 integration test for the dispatcher matrix |
| 2.3 | `_SourceBreakdown` evolution + `JudgmentSourceFilterWire` widening + 4 new wire Literals (`UbiConverterKind`, `JudgmentGenerationMethodWire`, `UbiReadinessRungWire`, `UbiMappingStrategyWire`) | ~100 LOC backend + 2 contract tests + 1 unit test |

Sequencing: 2.1 first (used by 2.2), then 2.2 + 2.3 in parallel (different files, no shared state). Branch tip remains `feat/ubi-judgments`; no rebase needed.

### Remaining work (Epics 3–5)

| Epic | Stories | Theme |
|---|---|---|
| 3 | 3.1, 3.2, 3.3, 3.4 | API endpoints + worker + agent tool |
| 4 | 4.1, 4.2, 4.3 | Frontend (enums + hook + badge, dialog method picker + nudge + sparse card, value-delta + recovery cards) |
| 5 | 5.1, 5.2 | Docs (runbook + glossary + FAQ + tutorial + umbrella spec patches) + E2E suite (4 specs + `seed_ubi.ts` helper) |

After Epic 5 completes: post-implementation ceremony (test coverage audit, deferred work extraction, tangential sweep, guide impact, push, CI watch, Gemini adjudication, final GPT-5.5 review, finalization to `implemented_features/2026_MM_DD_feat_ubi_judgments/`).

## Notes for `/impl-execute` resume
- **Epic 1 is durable** — the migration is round-trip-clean against the local Postgres, the domain library has 58 passing unit tests, and the branch is push-ready (will push at end of this session per the operator's "push after Epic 1" instruction).
- **No code in subsequent stories depends on un-pushed Epic 1 state** — Story 2.1 imports `backend.app.domain.ubi.features.UbiEvent` and `aggregate_features`; Story 2.2 imports `backend.app.services.ubi_reader` (Story 2.1's output) + the existing dispatcher helpers; etc.
- **The plan's §11 consistency review remains green** — none of the cycle-3 fixes contradicted Epic 1 stories (the `generation_kind: 'ubi'` discriminator goes in the JSONB at INSERT time in Story 2.2's dispatcher; the column itself was added in Story 1.1).
- **Resume command:** `/impl-execute docs/00_overview/planned_features/02_mvp2/feat_ubi_judgments/implementation_plan.md 2.1` (the second argument is the next story ID; `--all` would batch-run Epics 2-5, which is the right call if the next session has token budget for it).
