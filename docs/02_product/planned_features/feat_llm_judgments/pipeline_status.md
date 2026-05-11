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
- Status: **Approved** — 2026-05-11
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 (`gpt-5.5`) — 2 cycles, **20 findings total**, 19 accepted + applied, 1 rejected with cited counter-evidence (cycle-1 F11 — `SearchAdapter.render(...)` does exist at `backend/app/adapters/protocol.py:143` + `backend/workers/trials.py:385` already calls it).
- Stories: 16 stories across 4 epics (Foundations 7 / Worker 1 / API 5 / Docs 3).
- Endpoints: 7 (spec §8.1 lists 6; the 7th is the import endpoint described in FR-3b — spec drift captured for follow-up).
- Error codes: 13 covered (11 from spec §8.5 + 2 from spec body text — `QUERY_NOT_IN_SET` from FR-3b and `LIST_NOT_READY` from §11 — plus `UNKNOWN_MODEL_PRICING` introduced by GPT-5.5 cycle 2 F4 for budget-gate integrity, captured as spec drift).
- Test files: 4 unit + 10 integration + 1 contract = **15 test files**.
- Spec drifts captured (4 follow-up idea files to file during execution):
  - `chore_spec_llm_judgments_endpoint_drift` — §8.1 missing import endpoint
  - `chore_spec_llm_judgments_error_drift` — §8.5 missing `QUERY_NOT_IN_SET` + `LIST_NOT_READY`
  - `chore_spec_llm_judgments_pricing_drift` — §8.5 missing `UNKNOWN_MODEL_PRICING` + FR-5 missing "run calibration before overrides" guidance
  - `chore_judgments_periodic_resume_sweep` — in-worker periodic resume sweeper (boot-time sweep + CLI handle MVP1)
- Phases covered: 1 (single-phase per spec §3).

## Implementation
- Status: **PR created — awaiting merge** — 2026-05-11
- PR: [#35](https://github.com/SoundMindsAI/relyloop/pull/35) — `feat(judgments): LLM-as-judge worker + 7 API endpoints (feat_llm_judgments)`
- CI: green (final run after cycle-9 fixes, then cycle-10 convergence pass)
- Stories: 16 / 16 complete (all 4 epics shipped; Story 1.1 + 1.2 committed pre-PR-open, remaining 14 in this PR)
- Cross-model review: **10 cycles of GPT-5.5** on the cumulative diff. 19 findings raised total; 18 accepted + applied, 1 rejected with cited counter-evidence (C7-F1 — uuid_utils dep declared at `pyproject.toml:37`). Cycle 10 returned `{"findings":[]}` — convergence.
- Gemini Code Assist: not installed on the repo (PRs #25 / #23 / #18 / #16 / #4 all had 0 line comments).
- Follow-up idea files captured during execution: 4 spec-drift / strategic-followup chores (see Plan section above).
- After merge: separate finalize PR moves the folder to `docs/00_overview/implemented_features/` + updates `state.md` with the merged-SHA-bearing summary.

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

Run `/impl-execute` against the approved plan to ship the feature:

```bash
/impl-execute docs/02_product/planned_features/feat_llm_judgments/implementation_plan.md --all
```

16 stories across 4 epics. Execution surfaces 4 spec-drift idea files (listed above) that the operator captures during the standard `/impl-execute` post-implementation workflow.
