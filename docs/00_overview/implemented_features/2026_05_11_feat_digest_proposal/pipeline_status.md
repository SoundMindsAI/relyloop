# Pipeline Status — feat_digest_proposal

Study-end digest narrative + proposal-population pipeline. Replaces the `digest_stub.py` shipped by `feat_study_lifecycle` Phase 2 with a real implementation. Single-phase per spec §3.

## Idea
- Skipped — spec authored directly (the digest design was nailed down in umbrella spec §15 + the data-model doc + `feat_study_lifecycle` Phase 2's durable-handoff design).

## Spec
- Status: **Approved** — 2026-05-11 (review-and-patched after `feat_study_lifecycle` Phase 2 + `feat_llm_judgments` shipped; original draft 2026-05-09; further patched 2026-05-11 during plan-gen cycle-2 review per F1).
- File: [feature_spec.md](feature_spec.md)
- Cross-model review history: spec went through plan-gen cycle 2 to patch FR-5 + AC-1 + Decision Log entries — `recommended_config` is now formally documented as worker-computed (deterministic), not LLM-generated. The LLM's contract is `{narrative, suggested_followups}` only.
- Phases: 1 (single-phase; no deferred work).

## Plan
- Status: **Approved** — 2026-05-11.
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 ran 3 cycles to the configured cap.
  - Cycle 1 (9 findings, all accepted): suggested_followups NOT NULL with default; worker-side error code grep; SQL example fix; `DIGEST_RESPONSE_FORMAT` constant + maxItems=5 wired; **recommended_config is deterministic from best-trial params, not LLM-generated** (structural); pre-LLM idempotency guard; AC-7 sum-to-1.0 test; benchmark reads `Settings.openai_model`; deterministic template-drift handling.
  - Cycle 2 (7 findings, all accepted): spec FR-5 + AC-1 + Decision Log patched for cycle-1 F5; prompt loader receives `recommended_config` + `dropped_template_params` as inputs; risk row rewritten; contract-test grep split (router vs worker); zero-trials path moved BEFORE OpenAI preflights; `pg_try_advisory_xact_lock` added; all-dropped template-drift sub-case defined.
  - Cycle 3 (4 findings, all accepted): stale gate/DoD text aligned with the split-grep design; capability fallback no longer bypasses pricing + budget (made into a mode flag); `render_digest_user_prompt(include_recommendation: bool)` added with degraded-mode jinja branch; `update_proposal_for_digest` made conditional on `status='pending'` to handle the operator-reject mid-LLM race.
- Stories: 12 stories across 4 epics (Foundations / Worker / API / Docs+tests+cleanup).
- Phases covered: all (single-phase feature).
- Tests planned: 3 unit + 26 integration + 1 contract + 1 benchmark = 31 test files.

## Implementation
- Status: **Complete** — merged 2026-05-11.
- PR: [#41](https://github.com/SoundMindsAI/relyloop/pull/41) (squash commit `3753894`).
- CI: green (4 cycles — initial fail on test seed/setting/migration order, AC-11 fix, final-review fix, all green).
- Stories completed: 12 of 12 across 4 epics.
- Test counts: 350 unit + 26 integration + 1 contract + 1 benchmark.
- Final cross-model review: GPT-5.5 raised 6 findings; 5 accepted + applied, 1 rejected with cited counter-evidence (full adjudication on PR #41).
- Gemini Code Assist: N/A on this repo.

## Done
- Status: **Deployed** (no remote staging in MVP1; merge to main IS the deploy event).
- Date: 2026-05-11
- Follow-up tracked: [`bug_digest_param_importance_seam`](../bug_digest_param_importance_seam/idea.md) — AC-7 test fixture seam (xfail in this PR).

## Dependencies (all satisfied)

| Dependency | Status |
|---|---|
| `infra_foundation` | Merged — PR #4 (2026-05-09) |
| `infra_adapter_elastic` | Merged — PR #16 (2026-05-10) |
| `infra_optuna_eval` | Merged — PR #23 (2026-05-10) |
| `feat_study_lifecycle` Phase 1 + Phase 2 | Merged — PR #18 + PR #25 (2026-05-10/11) — **this feature consumes Phase 2's `orchestrator._stop` durable-handoff design** |
| `feat_llm_judgments` | Merged — PR #35 (2026-05-11) — **this feature reuses its LLM hot-path infrastructure (capability_check, budget_gate, cost_model, prompt_loader)** |

## Open items requiring user input

None — all spec drifts and plan-review findings resolved across 3 GPT-5.5 cycles.

## Next action

```bash
/impl-execute docs/00_overview/planned_features/feat_digest_proposal/implementation_plan.md --all
```
