# Pipeline Status — Replace deprecated `arq_pool.close()` with `aclose()`

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-01
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (1 cycle, 0 findings)
- Phases: 1 total, 1 covered by spec (single-phase)

## Plan
- Status: Approved
- Date: 2026-06-01
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (1 cycle, 0 findings)
- Stories: 2 total across 1 epic
- Phases covered: 1 of 1 (single-phase)

## Implementation
- Status: Complete (shipped earlier in PR #387, 2026-06-01 — folder finalized 2026-06-05)
- Release: mvp2
- Note: both call sites (`backend/app/main.py`, `backend/workers/all.py`) already use `await arq_pool.aclose()` and the two regression guards (`test_main_lifespan.py::test_lifespan_closes_arq_pool_with_aclose`, `test_workers.py::test_on_shutdown_closes_arq_pool_with_aclose`) are green. This planned-feature folder was left un-moved when the fix shipped; this is the bookkeeping finalization.
