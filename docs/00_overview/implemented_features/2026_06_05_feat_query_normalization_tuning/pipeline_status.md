# Pipeline Status — feat_query_normalization_tuning

**Release:** mvp2

## Idea
- Status: Complete
- File: [`idea.md`](idea.md)
- Preflighted: 2026-05-31 (line citation refreshed at `template_validator.py:58`; sibling-link repointed to `implemented_features/feat_ubi_judgments`; four open questions resolved with `Recommended default for /spec-gen` lines; D-1 gating fork locked at option (b))

## Spec
- Status: Approved
- Date: 2026-05-31
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 passed (3 cycles — cycle 1: 14 findings (4 High, 7 Medium, 3 Low) → 13 accepted + 1 rejected with counter-evidence; cycle 2: 7 findings (2 High, 4 Medium, 1 Low) → all accepted; cycle 3: 4 findings (all Low) → all accepted; stop rule satisfied — no remaining High)
- Phases: 3 total, 1 covered by spec (Phase 1). Phase 2 + Phase 3 carved out into their own planned-features folders 2026-05-31:
  - [`feat_query_normalizer_typed_pipeline`](../feat_query_normalizer_typed_pipeline/idea.md) — typed `NormalizerPipelineParam` + JS snippet + smart-quote contractions (was `phase2_idea.md`)
  - [`feat_apply_path_normalizer_declaration`](../feat_apply_path_normalizer_declaration/idea.md) — apply-path-side structured normalizer declaration (option (a) of the gating fork) (was `phase3_idea.md`)

## Plan
- Status: Approved
- Date: 2026-05-31
- File: [`implementation_plan.md`](implementation_plan.md)
- Cross-model review: Skipped (operator decision — Opus-only internal passes; spec already ran 3 GPT-5.5 convergence cycles)
- Internal review passes: 2 (plan-internal consistency + codebase accuracy); both clean — no hard blockers
- Stories: 11 total across 6 epics
- Test files: 8 unit + 1 integration + 1 contract + 1 E2E + 2 vitest = 13 new
- Phases covered: Phase 1 only (Phases 2 + 3 deferred — tracked in sibling folders `feat_query_normalizer_typed_pipeline` + `feat_apply_path_normalizer_declaration`)
- Special-attention story: 1.2 (`compute_default_params` extension) has its own hard-stop verification gate per spec cycle-2 finding
- Cross-engine portability: explicit parametrized test in Story 2.3 + integration test asserts ES + OpenSearch + Solr behave identically

## Implementation
- Status: Complete
- Date: 2026-06-05
- PR: [#459](https://github.com/SoundMindsAI/relyloop/pull/459) (squash-merged `7436bf92`)
- CI: all 18 `pr.yml` checks green (smoke skipped — opt-in/off)
- Stories: 11/11 complete across 6 epics
- Gemini review: 2 medium findings, both accepted + fixed (case-insensitive analyzer match; single `model_validate` in `create_study`)
- Tangential inline fixes: wizard auto-fill seeds the reserved key to the full `NORMALIZER_CHOICES` (parity-locked Python + TS) instead of the `__placeholder__` sentinel; spec FR-6 schema-endpoint path corrected
- Final cross-model (GPT-5.5) review: skipped, consistent with the plan's recorded operator decision (Opus-only internal passes); Gemini reviewed the diff + CI green

