# Pipeline Status — Create-Study Wizard Polish

## Idea
- Status: Complete
- File: idea.md
- Audited via /idea-preflight on 2026-05-19; 7 patches applied (line-number drifts, error-code module path correction, InfoTooltip vs Glossary component naming, K_REQUIRED citation).

## Spec
- Status: Approved (autonomous mode, /pipeline --auto)
- Date: 2026-05-19
- File: feature_spec.md
- Cross-model review: GPT-5.5 — 3 cycles
  - Cycle 1: 11 findings (5 Pass A, 6 Pass B). All accepted; 3 Major (`study.search_space` long-only vs InfoTooltip type contract; `'string'` simple-form omit vs FR-3 rejection; §4 "no silent ignores" contradicting FR-4 tri-state).
  - Cycle 2: 5 findings (3 Pass A, 2 Pass B). All Medium; all accepted (HelpPopover wiring, zero-declared-params edge, network-failure flow, AC-13 frontend test, decision-log consistency).
  - Cycle 3: 3 findings (3 Pass A, 0 Pass B). All Medium; all accepted (spec-internal cleanups from prior patching — §11 stale references, loading state contradiction, toast/undo timing model).
  - 0 High-severity findings in cycle 3; convergence reached at max-cycle limit.
- Internal Opus review: 1 Major correction during Pass 1 (binary→tri-state metric+k after reading `backend/app/eval/scoring.py:32`).
- Phases: 1 of 1 (single-phase chore; no `phase*_idea.md` artifacts required).

## Plan
- Status: Approved (autonomous mode, /pipeline --auto)
- Date: 2026-05-19
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles
  - Cycle 1: 17 findings (9 Pass A, 8 Pass B). 15 accepted + applied; 2 rejected with cited counter-evidence (A4: plan-template rule applies to new files only; B5: TanStack Query's reference equality handles same-template re-select).
  - Cycle 2: 4 findings (0 Pass A, 4 Pass B). 1 High (B1: cycle-1 acceptance reversed the spec's exact-message-format contract — restored 3-arg signature) + 3 Medium. All accepted.
  - Cycle 3: 4 findings (1 Pass A re-raise with new info, 3 Pass B new). All Medium; all accepted (cap-aware fallback ordering, locked 3-arg signature in spec, autoFillSignatures Set semantics, Epic 4 gate update).
- Stories: 7 across 4 epics
- Phases covered: single phase (all 7 FRs)

## Implementation
- Status: Complete
- Date merged: 2026-05-20
- PR: [#157](https://github.com/SoundMindsAI/relyloop/pull/157) — squash-merged as commit `075c46b`
- CI: green (backend lint/typecheck/tests/coverage + frontend lint/typecheck/tests/build + Playwright smoke + docker buildx + gitleaks + secrets-files guard, all SUCCESS)
- Stories completed: 7/7 (Story 1.1 + 1.2 from earlier on the branch; 2.1 + 2.2 + 3.1 + 3.2 + 4.1 in this run)
- Tests added: 16 new test files (3 backend unit, 1 integration, 2 contract, 4 frontend unit, 6 frontend component, 1 E2E — 1 skipped pending stability follow-up) + 2 modified + 1 shared JSON fixture
- Cross-model review:
  - Gemini Code Assist: 2 medium findings, both rejected with cited counter-evidence (eslint-disable callsites guard documented state-thrash failure modes per CLAUDE.md).
  - GPT-5.5 final pass (`gpt-5.5-2026-04-23`, 113.8K tokens): 7 findings — 2 rejected with counter-evidence, 5 deferred (4 as pre-existing Story 1.1/1.2 drift covered behaviorally by integration tests; 1 captured as `bug_err_metric_frontend_backend_drift`).
- Follow-up ideas filed during implementation:
  - `bug_tutorial_template_param_boost_naming` — tutorial template `<field>_boost` names don't match the heuristic's `boost_<field>` prefix.
  - `chore_create_study_modal_e2e_stability` — re-enable the skipped Playwright validation spec once EntitySelect disabled gating stabilizes under chained TanStack refetches.
  - `bug_err_metric_frontend_backend_drift` — `err` metric is selectable but unsupported by scoring.py; drop from OBJECTIVE_METRIC_VALUES until ERR@k lands.
