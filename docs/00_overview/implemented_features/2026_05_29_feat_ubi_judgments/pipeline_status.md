# Pipeline Status — UBI Judgments (engine-neutral User Behavior Insights)

**Release:** mvp2

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
- Status: **Complete (PR #317, squash-merged 2026-05-29)**
- CI: `pr.yml` green on the merge SHA; DCO + secrets-defense green.
- Stories: 13 of 13 shipped (all 5 epics). Story 5.2's E2E half + the
  hybrid-template-render contract cleanup were the only deferrals — both
  resolved below.
- Reviews: Gemini Code Assist (6 findings, all accepted + fixed) + GPT-5.5
  final cross-model review (6 findings: 4 fixed, 1 documented, 1
  analyzed as working-as-designed) — adjudication tables posted on the PR.
- Tests at merge: 1,719 backend unit + 931 UI vitest + 4 UBI E2E (live
  ES + worker, no mocking) all green; mypy --strict clean (507 files).

### Notable: E2E surfaced a real backend bug
The rung-3 E2E (real engine) caught what stubbed unit tests structurally
could not: `UbiReader` requested `size=50000` > the engine's default
`index.max_result_window` (10000) → "all shards failed" → swallowed →
spurious `UBI_INSUFFICIENT_DATA` on dense clusters. Fixed (cap at 10k +
clamp + regression guard); full-traffic aggregation deferred to
`chore_ubi_reader_search_after_pagination`.

### Deferred follow-ups (all captured as idea files)
- `chore_ubi_reader_search_after_pagination` (P2) — exact full-traffic
  UBI aggregation via `search_after` (current: 10k-event sample).
- `chore_ubi_hybrid_template_render` (P3) — drop the now-vestigial
  `current_template_id` requirement for hybrid (a product/contract
  decision; the worker's per-pair `get_document` scoring is correct per
  FR-2).
- `feat_demo_ubi_study_comparison` (P1) — synthetic UBI in the demo
  reseed + UBI-vs-LLM study comparison (operator-requested).
- **Resume command:** `/impl-execute docs/00_overview/planned_features/02_mvp2/feat_ubi_judgments/implementation_plan.md 2.1` (the second argument is the next story ID; `--all` would batch-run Epics 2-5, which is the right call if the next session has token budget for it).
