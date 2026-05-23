# Pipeline Status — Study Default Stop Conditions

## Idea
- Status: Complete
- File: idea.md (preflighted 2026-05-23 — 5 locked decisions + 5 open Qs surfaced, 4 with recommended defaults; all 5 resolved in spec)

## Spec
- Status: Approved
- Date: 2026-05-23
- File: feature_spec.md
- Cross-model review: GPT-5.5 converged at cycle 3 — 1 rejected with cited counter-evidence (Pass A AC-9 envelope claim; counter-evidence at `backend/app/api/errors.py:62, 118`), 11 accepted + applied across cycles 1-3 (FR-3 time_budget clearing, AC-7 prompt-content reshape, accessibility group labeling, Focused pruner semantics, `type="button"` requirement, FR-9 transition tests, Flow 5 reword, §13 RadioGroup→button-group consistency, AC-7 grep regex word/EOL boundary, §14 ≥10 case count + transition test bullets, status line stamp).
- Phases: 1 total, 1 covered by spec (single phase — Tier A + Tier B ship together).

## Plan
- Status: Approved
- Date: 2026-05-23
- File: implementation_plan.md
- Cross-model review: GPT-5.5 converged at cycle 2 — 5 findings cycle 1 (all accepted + applied: aria-label on buttons, watcher undefined-normalization to prevent open-flip race, Story 1.2 DoD grep simplification, Story 1.5 outcome reworded to "spec §14 vitest set", UI Guidance per-option helper text explicit-omit); 0 findings cycle 2 (clean pass).
- Stories: 5 across 1 epic — 1.1 glossary refresh + new `study.preset` entry, 1.2 system prompt update, 1.3 form default `max_trials=200`, 1.4 button-group preset selector + state transitions, 1.5 vitest test suite (≥10 cases).
- Phases covered: single-phase, full coverage of FR-1..FR-9.

## Implementation
- Status: Complete (merged 2026-05-23)
- Date: 2026-05-23
- Branch: `feature/chore-study-default-stop-conditions`
- PR: [#215](https://github.com/SoundMindsAI/relyloop/pull/215) (squash-merged as `370c87d9`)
- Stories: 5/5 complete — 1.1 glossary refresh, 1.2 system prompt update, 1.3 form default `max_trials=200`, 1.4 button-group preset selector + state transitions, 1.5 vitest test suite (12 cases after AC-6 follow-up).
- Test layers: vitest + E2E (per spec §14). Full UI suite 98/98 studies + 730+ overall green. tsc clean. ESLint at baseline (no new warnings). All 5 CI jobs green (frontend, backend coverage, backend fast, smoke, docker buildx).
- Cross-model implementation review: GPT-5.5 cycle 1 raised 1 Medium finding (modal-open form-field reset gap, Radix Dialog mount-persistence bug). Cycle 2 clean.
- Late-stage E2E fix (during review): `studies-create-builder.spec.ts:130` + `studies-create-target-dropdown.spec.ts:48` regressed against the production UI image because Playwright's `.fill('10')` on a non-empty Max trials input triggered a stray form-submit event before the test's explicit submit-button click. Resolved by decoupling the submit from the form's `onSubmit` event: `<form onSubmit={e => e.preventDefault()}>` + submit-button changed to `type="button"` with `onClick={form.handleSubmit(onSubmit)}`. Both tests green post-fix.
- Gemini Code Assist adjudication: 1 Medium finding (Defer — pre-existing form-state persistence across modal toggles, out of scope for this chore).
