# Pipeline Status — feat_study_target_judgment_mismatch_guard

## Idea
- Status: Complete
- File: idea.md
- Preflight: applied 2026-05-21 (5 patches across idea.md — Locked decisions section added, capability gaps closed, line-ref drift fixed)

## Spec
- Status: Approved
- Date: 2026-05-21
- File: feature_spec.md
- Cross-model review: GPT-5.5 — 3 cycles (10 + 4 + 4 findings raised; 17 accepted + 1 rejected with cited counter-evidence at `create-study-modal.tsx:508`)
- Phases: 1 (single-phase ship; no deferred phases)
- Major changes vs idea: added FR-1b `JUDGMENT_CLUSTER_MISMATCH` cross-check (cycle-1 High finding closed the cross-cluster judgment-list reuse gap); +2 ACs (AC-11 + AC-12); +1 follow-up boundary documented (`bug_studies_query_set_cluster_consistency`).

## Plan
- Status: Approved
- Date: 2026-05-21
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles (12 + 3 + 1 findings raised; **all 16 accepted, 0 rejected**)
- Stories: 3 across 1 epic (1.1 backend listing surface, 1.2 backend validators, 2.1 frontend filter + cascade + empty-state)
- Phases covered: single phase

## Implementation
- Status: Complete
- Date: 2026-05-21
- PR: #184 (merged squash `ce3fcf4`)
- CI: green on final commit `a358a71` (5/5 jobs incl. 70-test smoke)
- Stories completed: 3 / 3 (1.1 backend listing + 1.2 backend validators + 2.1 frontend filter)
- Cross-model reviews: spec 3 cycles (17 findings, all accepted, 1 rejected); plan 3 cycles (16 findings, all accepted, 1 rejected); Gemini Code Assist (2 findings — 1 accepted in `035af0a`, 1 rejected with precedent counter-evidence); final GPT-5.5 (10 findings — 2 accepted in `a358a71`, 8 rejected with cited counter-evidence including 5 truncation false positives)
- Drive-by fix bundled in PR: E2E seed helpers (`seedJudgmentList`, `seedFullChain`, `seedStudy`) gain optional `target` overrides; 3 specs updated to align target values so the new FR-1 validator doesn't reject chained POSTs
- Tests at merge: backend unit 1040, integration +7 cases, contract +2 cases; UI vitest 567 → 572 (+5)
