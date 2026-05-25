# Pipeline status — `feat_study_baseline_trial`

| Stage | Status | Date | Artifact |
|---|---|---|---|
| IDEA | ✅ Complete | 2026-05-22 (preflight-patched 2026-05-25) | [`idea.md`](idea.md) |
| SPEC | ✅ Complete | 2026-05-25 | [`feature_spec.md`](feature_spec.md) |
| PLAN | ✅ Complete | 2026-05-25 | [`implementation_plan.md`](implementation_plan.md) |
| IMPLEMENT | — | — | — |
| DONE | — | — | — |

## SPEC stage details

- **Cross-model review cycles**: 3 (max). Convergence reached.
  - **Cycle 1 (Opus → GPT-5.5)**: 15 findings raised; 14 accepted + patched, 1 rejected with cited counter-evidence (CHECK constraint really does not include `'running'`; the worker only INSERTs at terminal state — verified at `backend/app/db/models/trial.py:48-51`).
  - **Cycle 2 (with rejection log)**: 9 new findings (all genuinely new — no repeats); all accepted + patched. Included a forward-looking direction-aware fix for `evaluate_chain_gate` that closes a latent minimize-direction bug in `feat_auto_followup_studies`.
  - **Cycle 3 (convergence check)**: 1 High-severity new finding — resume-race that could allow double-baseline-trial-INSERT. Accepted; patched with defense-in-depth (Arq `_job_id` dedupe + partial unique index + FR-12 stamping idempotency predicate).
- **Functional requirements**: 12 FRs (FR-1 through FR-12).
- **Acceptance criteria**: 18 ACs (AC-1 through AC-18).
- **Phases**: 1 (no further sub-phases).
- **Open questions remaining**: 0 (OQ-1 / OQ-2 / OQ-3 resolved inside the spec).
- **Touched surfaces**: 1 migration (0020), 1 new worker module (`backend/workers/baseline.py`), 1 new domain module (`backend/app/domain/study/baseline_resolver.py`), 1 new service helper (`services.study_state.stamp_baseline_trial`), orchestrator change (`backend/workers/orchestrator.py:start_study`), confidence one-line change (`confidence.py:624`), auto-followup gate (`auto_followup.py:91-169` direction-aware), digest system prompt (`prompts/digest_narrative.system.md`), API schema (`StudyDetail.baseline_trial_id`, `TrialDetail.is_baseline`), trials repo filter updates (`aggregate_trials_summary` + siblings), trials-table UI filter toggle.
- **Code estimate**: ~600-900 LOC backend; ~50 LOC frontend; ~400 LOC tests.

## PLAN stage details

- **Cross-model review cycles**: 3 (max). Convergence reached.
  - **Cycle 1**: 10 findings (all accepted + patched) — story ordering issues, missing commits, AC-12 PR body coverage, FR-11 auto-followup filter, migration idempotency, SQLAlchemy placeholder convention, late-completion fault seam, resolver DoD scoping.
  - **Cycle 2**: 2 new High findings (both accepted + patched) — overzealous repo filter would have hidden baseline from the trials-listing API; `_resolve_and_enqueue_baseline` return type couldn't distinguish skipped from deduped.
  - **Cycle 3**: clean (`{"findings": []}`). Convergence.
- **Epics**: 4 (Foundation / Activation / Frontend / Close-out).
- **Stories**: 14 (1.1–1.7, 2.1–2.3, 3.1–3.2, 4.1–4.2) with explicit phase gates between epics.
- **Test estimate**: 30+ unit, 8+ integration, 4+ contract, 1 E2E.

## Next action

User invoked `--auto` — pipeline advances autonomously to IMPLEMENT stage (Epic 1 execution).
