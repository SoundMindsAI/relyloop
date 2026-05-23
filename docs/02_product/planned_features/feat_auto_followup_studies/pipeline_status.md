# Pipeline Status — Auto-Followup Studies

## Idea
- Status: Complete
- File: [`idea.md`](idea.md)
- Preflight audit: 2026-05-23 (49 insertions / 18 deletions; 6 Open questions locked at spec time)

## Spec
- Status: Approved (auto-mode pipeline; no operator review pause per `/pipeline --auto`)
- Date: 2026-05-23
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 passed (3 cycles — max-cycle convergence)
  - Cycle 1: 1 High finding (depth=0 inconsistency across FR-1 / FR-3 / AC-5) — accepted, patched across FR-1, §8.4, §8.5, AC-2, §14.
  - Cycle 2: 10 findings (2 High, 8 Medium) — all accepted, patched across digest trigger, idempotency design, event catalog, AC-6 lock, repo signature, cost-model citation, cancel-callers inventory, Pydantic coercion. D-10 through D-13 added.
  - Cycle 3: 6 findings (3 High, 3 Medium) — all accepted, patched (dangling references from cycle-2 patches: API convention check still said "no new endpoints"; §2/§4/§8.3/§9 still encoded `1..5` validator; §6 still said "6 events"; FR-3 missing the layer-2 backstop step; §11 edge flow still said failed-parent emits telemetry; §11 primary flow miscounted chain depth).
- Phases: 1 of 1 (single-phase delivery — Tier A + Tier B ship together per §3 Phase boundaries)
- FRs: 12 (FR-1 through FR-12)
- ACs: 13 (AC-1 through AC-13)
- Telemetry events: 8 (FR-9 authoritative catalog)

## Plan
- Status: Approved (auto-mode pipeline; no operator review pause per `/pipeline --auto`)
- Date: 2026-05-23
- File: [`implementation_plan.md`](implementation_plan.md)
- Cross-model review: GPT-5.5 passed (3 cycles — max-cycle convergence)
  - Cycle 1: 15 findings (3 High, 8 Medium, 4 Low) — all accepted, patched across first-decile algorithm, Pydantic validator strategy (custom `error_code` prefix-parser added to global handler), test file ownership, telemetry event renames (`digest_followup_*` to keep FR-9 catalog stable), trigger placement, cancel modal logic, hook path, repo imports, Redis client inline-creation, E2E scenario, enqueue try/except, pnpm script reference.
  - Cycle 2: 5 findings (2 High, 1 Medium, 2 Low) — all accepted, patched across prefix-parser allowlist constraint, contract-test ownership reconciliation, event-name reconciliation, `<StudyActionBar>` prop refactor (renamed `chainChildren` to avoid React-`children` collision), cascade-service redesign for terminal parents. SPEC AC-8 + AC-9 rewritten to match the realistic chain lifecycle.
  - Cycle 3: 4 findings (3 High, 1 Medium) — all accepted, patched (cascade algorithm now recurses through terminal intermediates to reach in-flight descendants; auxiliary event added to gate condition; contract tests rewritten for realistic lifecycle; "Stop chain" modal label implemented per C2-5's promise). One partial-reject: cycle-3 C3-4 asked for backend transitive-descendant detection — rejected because the spec D-13 deliberately scopes cascade UX to direct children; instead, captured the UX limitation in the runbook + named `feat_auto_followup_root_chain_stop` as the future feature if operators ask.
- Stories: 10 across 4 epics (1 Backend foundation / 2 Worker + API / 3 Frontend / 4 Documentation)
- Test files: 12 (4 backend unit, 3 backend integration, 1 backend contract, 3 frontend unit, 1 E2E)
- Auxiliary events outside FR-9 catalog: 4 (`digest_followup_enqueue_pool_missing`, `digest_followup_enqueue_failed`, `digest_followup_start_study_enqueue_failed`, `auto_followup_cancel_terminal_parent`)
- Known UX limitation (deliberate): Cancel-from-completed-root requires operator to navigate to the in-flight descendant. Per D-13 direct-children scoping. Documented in `docs/03_runbooks/auto-followup-debugging.md` (Story 4.1).

## Implementation
- Status: In Progress — PR #223 open and CI green; awaiting merge. All 10 stories complete + all 3 phase gates passed.
- Branch: `feature/auto-followup-studies`
- PR: [#223](https://github.com/SoundMindsAI/relyloop/pull/223) (opened 2026-05-23, CI all 5 jobs green, Gemini Code Assist 1 Medium accepted + applied, final GPT-5.5 review 2 Medium accepted + shipped).
- Stories complete (10/10):
  - **Story 1.1** — Chain-gate domain + StudyConfigSpec field + error-handler prefix parser. Commit `b32645c1`.
  - **Story 1.2** — NO-OP discovery: `narrow_around_winner` was already extracted. Commit `33e9ccc7`.
  - **Story 1.3** — `list_children_of_study` repo + `cancel_study_with_chain_cascade` service (cycle-3 C3-1 redesign). Commit `8bd0a685`.
  - **Story 2.1** — `enqueue_followup_study` Arq job (FR-3, FR-5, FR-6, FR-7 worker side, FR-9 events 1-7). Commit `9718812a`.
  - **Story 2.2** — Digest worker trigger with deterministic `_job_id`. Commit `70f61d8c`.
  - **Story 2.3** — Cancel cascade endpoint extension + new children endpoint + `_parse_cascade` dependency. Commit `daaa9e35`.
  - **Story 3.1 + 3.2 + 3.3** — Chain panel + wizard depth selector + cancel-modal cascade radio + Node 22 pin. Commit `d640b593` (interlocked at same files; landed together).
  - **Story 4.1** — Runbook at `docs/03_runbooks/auto-followup-debugging.md` + `state.md` entry. Commit TBD (this turn).
- **Epic 1 phase gate:** ✓ (cumulative review deferred to Epic 2)
- **Epic 1+2 phase gate:** ✓ — GPT-5.5 cycle 1: 8 findings (1 High, 7 Medium). 2 substantive fixes (F3 + F5), 2 doc fixes (F1 + F4), 1 future-work idea captured (`chore_auto_followup_completed_parent_stop_chain_race`).
- **Epic 3 phase gate:** ✓ — `pnpm typecheck` + `pnpm lint` (0 errors, 105 pre-existing warnings) + `pnpm test` (744 pass, +13 new) + `pnpm build` all green on Node 22.
- **Test totals:** backend `make test-unit` 1220 pass (+23 new); UI vitest 744 pass (+13 new); 8 integration tests CI-gated.
- See [`implementation_plan.md` §9 Execution tracker](implementation_plan.md) for the full per-story checkbox list

## Notes
- This feature uses an existing column (`studies.parent_study_id` self-FK from `feat_study_lifecycle` Phase 1 migration 0003) for the first time. **No schema migration is needed.**
- Soft dependency: `feat_study_baseline_trial` (idea-stage). The spec ships with FR-2a (lift-over-first-decile gate) and switches to FR-2b (lift-over-baseline) via a one-line change in `evaluate_chain_gate` when the dependency lands. Tracked in D-3.
- Single-tenant MVP1 — no auth, no audit_log (MVP2 catalog entries pre-shaped per §6).
