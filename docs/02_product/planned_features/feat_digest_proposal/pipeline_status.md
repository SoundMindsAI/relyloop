# Pipeline Status — feat_digest_proposal

Study-end digest narrative + proposal-population pipeline. Replaces the `digest_stub.py` shipped by `feat_study_lifecycle` Phase 2 with a real implementation. Single-phase per spec §3.

## Idea
- Skipped — spec authored directly (the digest design was nailed down in umbrella spec §15 + the data-model doc + `feat_study_lifecycle` Phase 2's durable-handoff design).

## Spec
- Status: **Approved** — 2026-05-11 (review-and-patched after `feat_study_lifecycle` Phase 2 + `feat_llm_judgments` shipped; original draft 2026-05-09).
- File: [feature_spec.md](feature_spec.md)
- Audit + patch pass (2026-05-11): inverted FR-2 worker contract from CREATE-proposal to POPULATE-existing-pending-proposal per Phase 2's C3-F1 atomicity fix at `backend/workers/orchestrator.py:346-356`. Acknowledged `digest_stub.py` replacement. Added FR-2b boot-time scan. Added FR-6 repo functions list. Pinned model via `Settings.openai_model`. Mirrored `feat_llm_judgments` preflight order (capability + pricing + budget peek). Fixed path drifts. Added §8.5 codes (`LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`, `OPENAI_BUDGET_EXCEEDED`, `OPENAI_NOT_CONFIGURED`) as worker-side terminal reasons. Added AC-9 / AC-10 / AC-11 covering boot scan + deferral + degraded-capability paths.
- Cross-model review: not yet run on the patched spec — Opus internal audit only. Recommended to run a GPT-5.5 cycle when `/pipeline` advances to plan generation.
- Phases: 1 (single-phase; no deferred work).

## Plan
- Status: Not started. Next: `/pipeline` → `impl-plan-gen` against this spec.

## Implementation
- Status: Not started.

## Dependencies (all satisfied)

| Dependency | Status |
|---|---|
| `infra_foundation` | Merged — PR #4 (2026-05-09) |
| `infra_adapter_elastic` | Merged — PR #16 (2026-05-10) |
| `infra_optuna_eval` | Merged — PR #23 (2026-05-10) |
| `feat_study_lifecycle` Phase 1 + Phase 2 | Merged — PR #18 + PR #25 (2026-05-10/11) — **this feature consumes Phase 2's `orchestrator._stop` durable-handoff design** |
| `feat_llm_judgments` | Merged — PR #35 (2026-05-11) — **this feature reuses its LLM hot-path infrastructure (capability_check, budget_gate, cost_model, prompt_loader)** |

## Open items requiring user input

None — all spec drifts resolved during the 2026-05-11 review-and-patch pass.

## Next action

```bash
/pipeline docs/02_product/planned_features/feat_digest_proposal/
```

Or, if the operator wants to skip the orchestration layer and call directly:

```bash
/impl-plan-gen docs/02_product/planned_features/feat_digest_proposal/feature_spec.md
```
