# Pipeline Status — `feat_data_table_primitive`

## Idea
- Status: Complete
- File: [idea.md](./idea.md)
- Preflighted: 2026-05-15

## Spec
- Status: Approved
- Date: 2026-05-15
- File: [feature_spec.md](./feature_spec.md)
- Cross-model review: GPT-5.5 — 3 cycles, 26 total findings (14 + 8 + 4), all accepted with cited counter-evidence and applied. Convergence reached at the max-3-cycle stop rule per `.claude/skills/spec-gen/SKILL.md` Step 7.
  - **Cycle 1 (14 findings):** ts_rank/cursor incompatibility, FR-2 to_tsvector double-wrap, §8.1 missing `?sort=` surface, §3 missing engine_type/environment params, judgments vs judgment_lists conflation, contract test envelope ambiguity, trials sort cycle direction, router.push vs replace for pagination, total-count display under cursor reload, AC-7 downgrade -1 insufficient, FR-9 sort-as-filter, E2E spec per-table tailoring, AC-9 conversations scope, §3 count.
  - **Cycle 2 (8 findings):** ts_rank patch missed sites (§8.2/§9/AC-5/§13), trials URL form contradiction, judgment_lists vs per-list judgments §8.4 wording, sort wire form expansion ambiguity, conversations sort row drift, AC-14 page-2 range wording, §14 alembic round-trip wording, AC-9 table list rewrite.
  - **Cycle 3 (4 findings):** Cursor incompatibility with non-default `?sort=` (sort-aware cursor encoding added to FR-3a/§8.2/§9), Back-button history semantics clarification, per-list judgments endpoint missing from Scope item 17, stale-cursor edge case rendering rule (new `kind="stale-cursor"` empty state in FR-9 + §11).
- Phases: single-phase delivery per Locked Decision #4 — no deferred phases, no `phase2_idea.md`.
- Scope: 17 functional requirements (FR-1 through FR-17), 16 acceptance criteria (AC-1 through AC-16), 6 Alembic migrations (0008–0013), 8 table component migrations, 1 new npm dep (`@tanstack/react-table@~8.21.3`), ~2400 LOC estimated.

## Plan
- Status: Approved
- Date: 2026-05-16
- File: [implementation_plan.md](./implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles, 24 total findings (13 + 7 + 4), all accepted with cited counter-evidence and applied. Convergence reached at the max-3-cycle stop rule.
  - **Cycle 1 (13 findings):** missing queries-table migration, Epic 3 phase-gate arithmetic, DataTable URL-state ownership refactor (controlled instead of owning), `getRowId`/`T extends {id}` constraint, `?template_id=` UUID typing, trials column-config affordances, missing `?since=` contract tests, Story 1.4 wrong test-file citation, sourceOfTruth backend citation convention, Story 2.13 enums.ts comment-check assertion, TypeScript `Omit<union>` → intersection, missing `bulkActions` prop, clusters E2E pagination assertion.
  - **Cycle 2 (7 findings):** missing controlled `pageSize` in DataTable props, sort-direction constraint for trials' `optuna_trial_number_asc`-only, missed cycle-1 patch sites (§3.5 follow-up wording, §3.4 spec count, §7 parallelization, execution tracker), Story 3.1 sourceOfTruth example, Stories 2.2–2.4 still imported `useRouter` directly (now consume props), null-aware keyset predicate guidance for nullable sort columns, hook signature `(tableId)` → `(tableId, columns, options)`.
  - **Cycle 3 (4 findings):** table/row testid props missing from `DataTableProps`, `clearAllFilters` semantics (now `clearAllMatchers` — clears filters + q), residual "follow-up" + "8 specs" wording, debounce edge case when transitioning from valid `q` to under-length input.
- Stories: 28 total (5 in Epic 1 backend, 13 in Epic 2 primitive, 9 in Epic 3 table migrations, 2 in Epic 4 docs).
- Phases covered: single-phase delivery per Locked Decision #4. No deferred phases.

## Implementation
- Status: Complete
- Date: 2026-05-16
- PR: [#126](https://github.com/SoundMindsAI/relyloop/pull/126) (squash commit `d6115b3`, merged 2026-05-16)
- CI: all 7 checks green on cycle 4 — backend lint + typecheck + tests + coverage, backend unit fast lane, docker buildx, frontend lint + typecheck + tests + build, gitleaks, secrets files guard, smoke (operator-path E2E)
- Stories completed: 28 / 28 (Epic 1: 5 backend stories, Epic 2: 13 primitive stories, Epic 3: 9 table-migration stories incl. Story 3.9 inheritor, Epic 4: 2 docs/idea-capture stories)
- Cross-model review:
  - 3 Epic-2 phase-gate GPT-5.5 cycles (15 + 7 + 3 findings) — converged with 13 fixes applied, 7 deferred to `chore_data_table_primitive_followups`, 4 rejected with cited counter-evidence
  - 1 Epic-3 phase-gate GPT-5.5 cycle (7 findings) — 5 accepted + fixed, 2 rejected with cited counter-evidence
  - Final cross-model GPT-5.5 review on full PR diff: 2 findings — 1 accepted + fixed (`test-llm-rater` fixture), 1 deferred to `bug_cursor_decode_value_validation`
- Gemini Code Assist: 7 line-level findings, all 7 accepted + fixed (commit `acfd304`). Adjudication summary posted as PR comment.
- Deferred follow-ups captured:
  - [`feat_fts_rank_ordering_mvp2`](../feat_fts_rank_ordering_mvp2/idea.md) — rank-ordered FTS results (per spec §16)
  - [`chore_data_table_primitive_followups`](../chore_data_table_primitive_followups/idea.md) — 6 review-cycle items
  - [`bug_cursor_decode_value_validation`](../bug_cursor_decode_value_validation/idea.md) — cursor payload validation
