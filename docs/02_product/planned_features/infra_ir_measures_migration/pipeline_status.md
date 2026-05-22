# Pipeline Status — infra_ir_measures_migration

## Idea
- Status: Complete
- File: [`idea.md`](./idea.md)
- Refreshed via `/idea-preflight` on 2026-05-22 (PR #197 — preflight ledger captured in the file's "Sequencing-pressure update" + "Still-needed verification" sections).

## Spec
- Status: Approved
- Date: 2026-05-22
- File: [`feature_spec.md`](./feature_spec.md)
- Cross-model review: GPT-5.5 — 3 cycles (11 findings → 6 → 1). All findings accepted; zero rejections. Convergence trajectory monotonically decreasing.
- Phases: 1 of 1 (single-phase migration; §3 "Phase boundaries" rationale locks the single-PR scope).
- Locked decisions (§19 Decision log): single-PR scope; `ir_measures` over `ranx` / `pytrec-eval-terrier`; public API of `scoring.py` frozen; persisted JSONB key shape frozen; 6dp parity tolerance; sibling planned-features updated in same PR; `confidence.py` out of scope; `pytrec-eval` retained permanently in `[dependency-groups.dev]` for parity-gate infrastructure.
- 5 open questions (Q1–Q5, all empirical, resolved at impl-plan time): historical migration docstring rewording; `ir_measures` type hints; `pytrec_eval` transitive backend status; provider-routing observability; transitive deps / license / performance verification.

## Plan
- Status: Approved
- Date: 2026-05-22
- File: [`implementation_plan.md`](./implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles (10 → 4 → 1 findings). 14 accepted + applied, 1 rejected with cited counter-evidence. Convergence trajectory monotonically decreasing.
- Stories: 8 stories in 1 epic (single-PR migration per spec §3 Phase boundaries).
- Phases covered: 1 of 1 (single-phase migration; no deferred phases).
- Sequencing: strict-sequential 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8. No parallelization opportunities across stories.
- Locked decisions reflected in plan: public API of `scoring.py` frozen; persisted JSONB keys frozen; aggregate-via-iter (no `calc_aggregate`); per-query universe filtered to `pytrec_eval` historical contract; `pytrec-eval` permanent in `[dependency-groups.dev]` for parity gate.

## Implementation
- Status: Not started
