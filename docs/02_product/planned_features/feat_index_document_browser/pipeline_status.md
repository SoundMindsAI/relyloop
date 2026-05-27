# Pipeline Status — Index Document Browser

## Idea
- Status: Complete
- File: [idea.md](idea.md)
- Last patched: 2026-05-27 (Audit & Patch via `/idea-preflight`; 9 decisions locked D-1..D-9; IA section with route hierarchy table added)

## Spec
- Status: Approved
- Date: 2026-05-27
- File: [feature_spec.md](feature_spec.md) (925 lines)
- Cross-model review: GPT-5.5 passed (3 cycles — 13 + 11 + 9 = 33 findings, all 33 accepted; cycle 3 hit max-3 ceiling with no unresolved disagreements)
- Phases: 1 (single-phase per D-10; deferred surfaces tracked in sibling folders)
- FRs: 12 (5 backend + 5 frontend + 1 cursor encoding + 1 convention deviation)
- ACs: 20 (AC-1 through AC-20)
- Decisions logged: 28 (D-1..D-9 from idea + D-10..D-28 from spec)

## Plan
- Status: Approved
- Date: 2026-05-27
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 passed (3 cycles — 11 + 10 + 6 = 27 findings, 26 accepted + 1 rejected with cited counter-evidence; cycle 3 hit max-3 ceiling with 0 High findings remaining)
- Stories: 13 (across 3 epics — Adapter Protocol, Backend endpoints, Frontend UI)
  - Epic 1: 3 stories (Protocol additions + 2 ElasticAdapter impls)
  - Epic 2: 4 stories (helpers module + list endpoint + detail endpoint + studies `?target=` filter)
  - Epic 3: 6 stories (Indices card + summary page + list page + detail page + LinkedEntitiesRow/filter-chip + E2E)
- Branch: `feat/index-document-browser`
- Phases covered: 1 (all FRs in this plan)

## Implementation
- Status: Not started

## Done
- Status: —
