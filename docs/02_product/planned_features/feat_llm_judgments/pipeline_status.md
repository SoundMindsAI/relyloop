# Pipeline Status — feat_llm_judgments

Single-phase feature (per spec §3 "Phase boundaries"). LLM-as-judge pipeline + import endpoint + calibration. Creates the `judgments` child table that unblocks the `qrels_loader.py` stub left behind by `feat_study_lifecycle` Phase 2.

## Idea
- Skipped — spec authored directly (this feature's design was nailed down in the umbrella spec §14 + the data-model doc).

## Spec
- Status: **Approved** — 2026-05-11 (originally drafted 2026-05-09; path drifts patched + Status flipped after `feat_study_lifecycle` Phase 2 merged via PR #25)
- File: [feature_spec.md](feature_spec.md)
- Audit + patch pass (2026-05-11): 4 path-prefix drifts corrected (`backend/worker/` → `backend/workers/`, `backend/eval/` → `backend/app/eval/`, `backend/api/` → `backend/app/api/v1/`, `backend/db/models/` → `backend/app/db/models/`); 3 section-numbering bugs fixed (`### 7.1/7.4/7.5` → `### 8.1/8.4/8.5` under §8); §2 "Current state audit" refreshed from future-tense ("After dependencies ship") to past-tense citing `backend/app/db/models/judgment_list.py` + `qrels_loader.py` MVP1 stub.
- Cross-model review: not yet run on the spec — Opus internal audit only. Recommended to run a GPT-5.5 cycle when `/pipeline` advances to plan generation.
- Phases: 1 (single-phase; no deferred work).

## Plan
- Status: Not started.

## Implementation
- Status: Not started.

## Dependencies (all satisfied)

| Dependency | Status |
|---|---|
| `infra_foundation` | Merged — PR #4 (2026-05-09) |
| `infra_adapter_elastic` | Merged — PR #16 (2026-05-10) |
| `infra_optuna_eval` | Merged — PR #23 (2026-05-10) |
| `feat_study_lifecycle` Phase 1 + Phase 2 | Merged — PR #18 + PR #25 (2026-05-10/11) |

## Open items requiring user input

- **Final rubric content** (spec §19 open question 1) — the spec ships with a starter rubric in FR-3c. Product to replace with the final tailored content **before this feature merges to main** (NOT before plan generation). Non-blocking for `/pipeline`.

## Next action

Run `/pipeline` against the approved spec to advance to plan generation:

```bash
/pipeline docs/02_product/planned_features/feat_llm_judgments/
```

The plan generator will produce `implementation_plan.md` covering FR-1 through FR-6 + AC-1 through AC-7. Single-phase feature — no phase split expected.
