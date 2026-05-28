# Pipeline Status — Executable Digest Follow-ups

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved (Auto-mode — pending user redirect via pipeline gates)
- Date: 2026-05-23
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (3 cycles — convergence reached at max-cycle stop rule with all findings accepted)
  - Cycle 1: 9 findings (8 accepted, 1 rejected with cited counter-evidence)
  - Cycle 2: 6 findings (6 accepted — included regression patches and one re-raise of the migration surface with new information)
  - Cycle 3: 3 findings (3 accepted — internal-consistency clarifications)
  - Total: 17 accepted, 1 rejected
- Phases: 3 total (Phase 1 covered by spec; Phase 2 split out 2026-05-24 to standalone folder [`../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/`](../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/idea.md) so it ships cleanly through `/pipeline --auto` with standard artifact names; Phase 3 split out 2026-05-24 to standalone backlog folder [`../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/`](../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/idea.md) because the template-editor UI prerequisite is beyond MVP1 scope)

## Plan
- Status: Approved
- Date: 2026-05-23
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (1 cycle — convergence reached at "no major accepted changes" stop rule)
  - Cycle 1: 5 findings (3 accepted: F1 explicit downgrade-task ordering for migration 0018, F2 enable parent-study fetch when actionable followups exist, F3 contract tests for malformed `parent` payloads; 2 rejected with cited counter-evidence: F4 spec-level tenant-column note authorized by CLAUDE.md MVP4 forward-looking convention, F5 re-raise of spec D-17 with persisted-lineage counter-evidence per CLAUDE.md Absolute Rule #8)
- Stories: 16 total across 6 epics (Epic 1 Domain: 1 story; Epic 2 Worker + prompts: 3 stories; Epic 3 Migrations + ORM: 6 stories; Epic 4 API: 2 stories; Epic 5 Frontend: 3 stories; Epic 6 E2E: 1 story)
- Phases covered: Phase 1 (Tier A — `narrow` / `widen` / `text` followup kinds). Phase 2 (Tier B `swap_template`) split out 2026-05-24 to [`../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/`](../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/idea.md). Phase 3 (Tier C `edit_template`) split out 2026-05-24 to [`../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/`](../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/idea.md) — see promotion-criteria section there.

## Implementation
- Status: Complete — Phase 1 merged into main as PR #225 squash `83c526f2` on 2026-05-24; folder moved to `implemented_features/2026_05_24_feat_digest_executable_followups/` after both deferred phases were split to standalone sibling folders (PRs #227 + #229).
- Branch: `feature/digest-executable-followups` (deleted post-merge).
- PR: [#225](https://github.com/SoundMindsAI/relyloop/pull/225) — CI all 7 jobs green, Gemini Code Assist 2 Medium accepted + applied (head-and-tail truncate + parent-name 200-char cap), final GPT-5.5 cross-model review 3 findings (1 accepted as documented drift — `search_space_json` string workaround captured in plan §9; 2 rejected with cited counter-evidence — repo `**fields` passthrough + types.ts already regenerated).
- All 16 stories shipped across 6 epics. Test deltas: backend unit 1282 → 1316 (+34); +5 integration, +6 contract, +19 vitest, +1 Playwright E2E. Alembic head moves from `0017_proposals_last_polled_at` to `0019_digests_suggested_followups_jsonb` (two migrations: 0018 studies parent_proposal columns + BEFORE DELETE trigger + partial index, 0019 ARRAY(Text) → JSONB column-type change via PL/pgSQL helpers).
- **Phase 1 audit trail complete.** Both deferred phases were split to standalone sibling folders on 2026-05-24: Phase 2 → [`../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/`](../../../00_overview/planned_features/feat_digest_executable_followups_swap_template/idea.md) (PR #229); Phase 3 → [`../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/`](../../../00_overview/planned_features/backlog_feat_digest_template_edit_followups/idea.md) (PR #227). With no `phase*_idea.md` files remaining, the parent folder moved here per `impl-execute` Step 8.
- Tangential capture: `bug_markdown_doc_localstorage_undefined_jsdom/idea.md` — pre-existing vitest failure in unrelated guide-viewer tests, captured per CLAUDE.md tangential-discoveries rule.
