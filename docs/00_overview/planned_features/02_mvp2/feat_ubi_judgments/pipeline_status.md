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
  - Cycle 1: spec fix (`TEMPLATE_NOT_FOUND` added to §8.5 + §8.1)
  - Cycle 2: plan fix (`_build_ubi_generation_params(req)` helper injects `generation_kind: 'ubi'` server-side)
  - Cycle 3: plan fix (dropped snapshot `<UbiRungBadge>` variant — render only inside dialog where `query_set_id`+`target` exist per spec FR-7)
- Stories: 14 across 5 epics (Epic 1 Foundations 2 stories · Epic 2 Reader+Dispatcher+Breakdown 3 · Epic 3 API+Worker+Agent 4 · Epic 4 Frontend 3 · Epic 5 Docs+E2E 2)
- Phases covered: Phase 1 (all 11 FRs, single-phase delivery per spec D-6)

## Implementation
- Status: Not started
- Next: `/impl-execute docs/00_overview/planned_features/02_mvp2/feat_ubi_judgments/implementation_plan.md --all`

## Notes for `/impl-execute`
- **Suggested sequence** (per plan §7): 1.1 (migration) → 1.2 (domain) → [2.1 + 2.3 parallel] → 2.2 (dispatcher refactor) → [3.1 + 3.2 parallel] → [3.3 + 3.4 parallel] → 4.1 → 4.2 → 4.3 → 5.1 → 5.2.
- **Story 1.1 is the gating step** — Alembic migration round-trip must verify before any later story reads `generation_params`.
- **Story 2.2 includes a refactor** of `start_judgment_generation` to share helpers with the new UBI dispatcher. Existing LLM contract tests must pass without modification (parity DoD).
- **Story 3.3 worker registration** extends the boot-time resume sweep at `backend/workers/all.py:148-161` — verify the sweep correctly routes UBI vs LLM lists via `generation_params IS NOT NULL`.
- **Story 4.2 form-select discipline** — the method picker MUST use `JUDGMENT_GENERATION_METHOD_VALUES.map(...)` per the existing lint guard. If the guard rejects the new `<Select>`, the build will fail.
- **Story 5.2 E2E seeds UBI** via `tests/e2e/helpers/seed_ubi.ts` against the existing OpenSearch service container — no new service container required.
- **Bundle size estimate** ~1350 LOC. If pre-push gate or Gemini review surfaces reviewability concerns, the spec §3 Phase 2 contingency split is available (Phase 1 = Capabilities 1–5 + E; Phase 2 = Capabilities A–D). Default delivery is single-phase.
