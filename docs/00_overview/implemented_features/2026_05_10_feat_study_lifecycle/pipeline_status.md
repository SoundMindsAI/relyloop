# Pipeline Status — feat_study_lifecycle

Multi-phase feature. Phase 1 = Schema (this PR scope); Phase 2 = Orchestrator + API (deferred via [phase2_idea.md](phase2_idea.md)).

## Idea
- Skipped — spec authored directly. (See spec line 16 for the Phase 1/Phase 2 split intent that pre-dates this orchestrator.)

## Spec
- Status: **Approved** — 2026-05-10 (Phase 1 ready for impl-plan-gen)
- File: [feature_spec.md](feature_spec.md)
- Patches landed pre-pipeline (commit `f375da5`):
  - Status: Draft → Approved
  - §3 Phase boundaries: "Single-phase" → multi-phase Phase 1 (Schema) + Phase 2 (Orchestrator + API)
- Open question O4-equivalent: none (spec §19 has zero open questions)

## Plan (Phase 1 — Schema)
- Status: **Approved** — 2026-05-10
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles, **15 findings, all accepted + applied**
  - Cycle 1: 9 findings (1 High / 4 Medium / 4 Low) — applied
  - Cycle 2: 5 findings (0 High / 2 Medium / 3 Low) — applied
  - Cycle 3: 1 minor finding (count straggler) — applied
- Stories: **3 across 1 epic** (single-epic plan: ORM → Migration → Repos)
- Phases covered: Phase 1 only; Phase 2 deferred via [phase2_idea.md](phase2_idea.md)

## Implement (Phase 1 — Schema)
- Status: **Complete** — 2026-05-10
- PR: [#18](https://github.com/SoundMindsAI/relyloop/pull/18) (squash-merged as `d74e1be`)
- CI: green (backend + frontend + docker buildx all passed on `f5d3302`)
- Stories: 3/3 (`7bb9613` ORM models, `b3be589` migration, `7b4dd0a` repos)
- Cross-model review: GPT-5.5 phase-diff (5 findings — 4 accepted, 1 rejected with cited counter-evidence) + final review (1 finding — accepted, doc straggler `11 → 12 endpoints`). Both cycles converged; review-fix commits `08b8b30` + `f5d3302`.
- Gemini Code Assist: N/A (not configured on `SoundMindsAI/relyloop`; same as PR #16)
- Test coverage added: 14 integration test methods across 8 classes in `test_study_lifecycle_migration.py`; 11 round-trip tests in `test_study_repos.py`.

## Plan (Phase 2 — Orchestrator + API)
- Status: **Approved** — 2026-05-10
- File: [phase2_implementation_plan.md](phase2_implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles, **21 findings**, 19 accepted + applied, 1 rejected with cited counter-evidence (cycle-1 F2 → spec drift, captured as [`chore_spec_query_set_cluster_id_drift`](../chore_spec_query_set_cluster_id_drift/idea.md)), 1 second-pass discovery (C3-F3) applied in-cycle.
  - Cycle 1: 12 findings (5 High / 6 Medium / 1 Low) — 11 accepted + applied, 1 rejected with cited counter-evidence
  - Cycle 2: 6 findings (1 High / 3 Medium / 2 Low) — all accepted + applied (closing residual gaps in cycle-1 F6/F10/F11 fixes + 1 new architectural concern C2-F4)
  - Cycle 3: 3 findings (0 High / 3 Medium) — all accepted + applied (C3-F1 config key-omission, C3-F2 long-lived DB session, C3-F3 digest handoff atomicity)
- Stories: **14 across 4 epics** (Epic 1 foundations × 5 stories → Epic 2 orchestrator × 3 stories → Epic 3 API × 5 stories → Epic 4 docs × 1 story)
- Phase 2 endpoints: 12 (all in spec §7.1)
- Phase 2 error codes: 12 (all in spec §7.5) + 1 add-on (judgment/query-set mismatch → VALIDATION_ERROR)
- Test files: 4 new unit + 6 new integration + 2 new contract = 12 new test files; estimated +75 new test methods across all files

## Implement (Phase 2 — Orchestrator + API)
- Status: **PR open** — 2026-05-10
- PR: [#25](https://github.com/SoundMindsAI/relyloop/pull/25) (open, awaiting human merge)
- CI: green on latest commit (`923096a`)
- Stories: 14/14 across 4 epics
- Cross-model review: GPT-5.5 final-review — **4 cycles to convergence** (cycle 1: 10 findings → 5 applied + 5 deferred to idea files; cycle 2: 3 findings, all applied; cycle 3: 2 findings, all applied; cycle 4: `{"findings": []}` clean pass). See PR #25 adjudication summary comment for the full verdict table.
- Gemini Code Assist: N/A (not configured on `SoundMindsAI/relyloop`)
- Tangential idea files captured: `infra_per_trial_timeout`, `chore_openapi_contract_validation`, `infra_arq_subprocess_test` (Phase 2 cycle); `chore_trial_summary_single_query`, `chore_spec_trial_created_at_drift`, `chore_spec_query_set_cluster_id_drift` (Phase 1/Phase 2 plan-review cycle).

## Done
- Phase 1: **Complete (PR #18, merged 2026-05-10)**
- Phase 2: **PR #25 open** — awaiting human merge. After merge, the feature folder moves to `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_study_lifecycle/` (impl-execute Step 8 finalization).

## Open items requiring user input

- Human review + merge of PR #25.

## Next action

After PR #25 merges, run the finalization commit on a fresh branch from
main (sibling worktree at `/private/tmp/relyloop-release-main` may own
main locally; create `docs/finalize-feat-study-lifecycle` from
`origin/main` per impl-execute Step 8.0):

```bash
git fetch origin main
git checkout -b docs/finalize-feat-study-lifecycle origin/main
mv docs/00_overview/planned_features/feat_study_lifecycle \
   docs/00_overview/implemented_features/2026_05_10_feat_study_lifecycle
git add -A && git commit -m "docs: archive feat_study_lifecycle Phase 2 (PR #25)"
git push -u origin docs/finalize-feat-study-lifecycle
```
