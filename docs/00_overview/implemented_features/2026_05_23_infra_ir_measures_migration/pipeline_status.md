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
- Status: Complete
- Date merged: 2026-05-23
- PR: [#198](https://github.com/SoundMindsAI/relyloop/pull/198) (squash commit `350b2fc`)
- CI: 5/5 jobs green on the final SHA (frontend lint/typecheck/tests/build, backend unit fast-lane, backend full lint/typecheck/tests/coverage, smoke operator-path tutorial, docker buildx)
- Stories completed: 8/8
- Gemini Code Assist: 3 findings — 1 already-resolved (#1 pyproject conflict, fixed pre-Gemini in 352d60f), 2 accepted + applied (#2 + #3 Measure-object reverse map in 90884ed)
- Final GPT-5.5 review: 4 findings — 2 accepted + applied (F1 CLAUDE.md/optimization.md package-name removal + F3 parity-test docstring reword, both in a6b954d), 1 rejected with cited counter-evidence (F2 — `ir_measures` is Apache 2.0 per METADATA classifier), 1 deferred to finalization (F4 — dashboard PR# auto-fixes when folder moves)
- Branch: `feature/infra-ir-measures-migration` (15 commits) — deleted post-merge

### Implementation timeline
- 4ec8357 — planning artifacts baseline (spec + plan + pipeline_status + dashboard regen)
- b265463 — Story 1.1 (pyproject: ir-measures runtime + pytrec-eval dev + mypy override drop)
- 5ae53de — Story 1.2 (parity-test fixture + skipped skeleton)
- 5f205e6 — Story 1.3 (scoring.py rewrite with metric-object mapping + universe filter)
- 8c67447 — Story 1.4 (parity test activation; 30/30 cases PASS at 1e-6)
- 4f14c28 — Story 1.5 (leakage assertions extended; existing-row regression added; p@10 inline fix)
- 2799040 — Story 1.6 (operator-visible studies.py:313 message + contract docstring reword)
- c2594c1 — Story 1.7 (Dockerfile comment reworded; docker build verified)
- fdd22ea — Story 1.8 (full doc-rewrite sweep + dashboard regen + grep gates clean)
- b5dbaa3 — phase-gate fixes (5 accepted findings: silent-skip → raise; scoring.py docstring reword; AC-12 fetch_study_confidence direct call; dashboard override sidecar moved out of implemented_features/; AC-3 positive cases made dynamic)
- 86d91bb — post-impl docs (state.md entry + pipeline_status.md Implementation section + tangential sweep summary + guide impact assessment)
- 352d60f — CI fix (removed conflicting pytrec-eval dev pin; rely on transitive pytrec-eval-terrier)
- 3b76fe1 — CI fix (trial-list response shape: 'data' not 'items')
- 90884ed — Gemini fix (Measure-object reverse map instead of repr(obj))
- a6b954d — final GPT-5.5 fixes (CLAUDE.md/optimization.md package-name removal + parity-test docstring)

### Q1–Q5 resolutions
- Q1: migration docstring at 0015_trials_per_query_metrics.py reworded (Story 1.8) — outcome (b) per spec §19
- Q2: both `ir_measures` AND `pytrec-eval-terrier` ship `py.typed` → `pytrec_eval` mypy override dropped (Story 1.1)
- Q3: `ir-measures` resolves `pytrec-eval-terrier` transitively → Dockerfile gcc/g++/python3-dev install stays; comment reworded (Story 1.7) — outcome (a) per spec §19
- Q4: default `ir_measures` provider routing produces 1e-6 parity → no forcing needed (Story 1.4) — outcome (a) per spec §19
- Q5: all transitive deps compatible with Apache 2.0 (ir_measures Apache 2.0; pytrec-eval-terrier MIT); benchmark passes under 100ms/query threshold (Story 1.4)

### Decision log addition (post-CI)
- 2026-05-23: dev-group `pytrec-eval>=0.5` pin REMOVED after CI revealed an install-time conflict with the transitively-resolved `pytrec-eval-terrier` (both ship the same `pytrec_eval` module name; install order determines winner). AC-4b superseded — the gate now asserts the pin is ABSENT. The parity gate stays alive via the transitive backend.
- Stories executed: 8/8 sequentially per the plan's strict-sequential order. Commits:
  - 4ec8357 — planning artifacts baseline (spec + plan + pipeline_status + dashboard regen)
  - b265463 — Story 1.1 (pyproject: ir-measures runtime + pytrec-eval dev + mypy override drop)
  - 5ae53de — Story 1.2 (parity-test fixture + skipped skeleton)
  - 5f205e6 — Story 1.3 (scoring.py rewrite with metric-object mapping + universe filter)
  - 8c67447 — Story 1.4 (parity test activation; 30/30 cases PASS at 1e-6)
  - 4f14c28 — Story 1.5 (leakage assertions extended; existing-row regression added; p@10 inline fix)
  - 2799040 — Story 1.6 (operator-visible studies.py:313 message + contract docstring reword)
  - c2594c1 — Story 1.7 (Dockerfile comment reworded; docker build verified)
  - fdd22ea — Story 1.8 (full doc-rewrite sweep + dashboard regen + grep gates clean)
- Phase-gate fixes: b5dbaa3 — 5 accepted findings from GPT-5.5 cumulative-diff review (silent-skip → raise; scoring.py docstring reword; AC-12 fetch_study_confidence direct call; dashboard override sidecar moved out of implemented_features/; AC-3 positive cases made dynamic)
- Tests: 1128 unit + 235 contract pass locally; integration tests will run in CI (Postgres host-binding skip per CLAUDE.md)
- Open questions Q1–Q5 all resolved during implementation (recorded in commit messages):
  - Q1: migration docstring reworded (Story 1.8)
  - Q2: ir_measures + pytrec-eval-terrier both ship py.typed → mypy override dropped (Story 1.1)
  - Q3: pytrec-eval-terrier resolved transitively → Dockerfile gcc/g++/python3-dev install stays (Story 1.7)
  - Q4: default ir_measures routing produces parity at 1e-6 → no forcing needed (Story 1.4)
  - Q5: license + perf check clean (Apache 2.0 + MIT + MPL-2.0/MIT; perf within ±10%) (Story 1.4)
