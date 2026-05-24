# Pipeline Status — `swap_template` LLM-Suggested Followups (Tier B)

## Idea
- Status: Complete
- File: idea.md
- Origin: split from sibling `feat_digest_executable_followups/phase2_idea.md` on 2026-05-24 (Phase 1 / Tier A shipped 2026-05-24 as PR #225 squash `83c526f2`)

## Spec
- Status: Approved
- Date: 2026-05-24
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (3 cycles — converged at max-cycle stop rule with all findings accepted)
  - Cycle 1: 12 findings (12 accepted, 0 rejected) — F1-F12 covered trusted-intersection narrowing, `build_starter_search_space` empty guard, 4-field `RemapResult` split, dropping the JSON-schema conditional in favor of empty-string sentinel, length-only `template_id` validator, removing the empty-LLM-search-space helper test, worker truncate-before-checks, audit-event allowed values including `text`, worker-side event emission for FR-8, FR-14 autofill-suppression guard, E2E asserting `template_id` only (lineage at integration layer), and exhaustive switch / Record mandate
  - Cycle 2: 5 findings (5 accepted, 0 rejected) — 3 re-raises (stale §2/§3 prose on optional schema + deterministic worker pre-clean rule; §13/§4 diagnostic field-name drift; §6 intro sentence still narrow) and 2 net-new (4th reason code `remap_invalid_search_space` for FR-7 step 3 emission; `validation_error` truncation matches the canonical `_truncate` helper)
  - Cycle 3: 1 finding (1 accepted, 0 rejected) — net-new internal-consistency catch: empty trusted intersection is unreachable on the worker path (Pydantic min_length=1 rejects empty `SearchSpace`), so helper rejects no-trusted-intersection inputs and prompt instructs LLM to skip in that case; disjoint-only swaps explicitly out of contract
  - Total: 18 accepted, 0 rejected across 18 findings (Decision Log D-17 through D-34 enumerate the resolutions)
- Phases: 1 total (single-phase delivery — no `phase2_idea.md`; Tier C `edit_template` tracked at sibling [`../backlog_feat_digest_template_edit_followups/`](../backlog_feat_digest_template_edit_followups/idea.md))

## Plan
- Status: Approved
- Date: 2026-05-24
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (2 cycles)
  - Cycle 1: 7 findings (7 accepted, 0 rejected) — F1 widen `hasActionableFollowup` gate to include swap_template; F2 extract per-card `SwapTemplateCard` child component (drops single-target shortcut); F3 move `sharedKeys` `useMemo` into the child component (Rules of Hooks); F4 prefill kind check via exhaustive `Record<FollowupKind, …>` lookup + `resolveTemplateIdForPrefill` switch with `_exhaustive: never`; F5 sequencing — glossary (3.4) MUST land before panel widening (3.1 + 3.2); F6 promote private `_truncate` to public `truncate_validation_error` so the worker can import it; F7 contract-test filename reconciliation (`test_digest_proposal_api_contract.py` exists; spec-named `test_proposal_detail_shape.py` doesn't).
  - Cycle 2: 4 findings (0 accepted, 4 rejected with cited counter-evidence) — F1 + F3 are spec-cycle prose drift (out of plan scope); F2 + F4 are re-raises of cycle-1 issues already resolved by the cycle-1 corrections.
  - Total: 7 accepted + 4 rejected across 11 findings; rejections-only stop rule reached convergence at cycle 2.
- Stories: 13 total across 5 epics (3 domain + 3 worker + 5 frontend + 2 API + 1 E2E)
- Phases covered: single-phase delivery (Tier B only)

## Implementation
- Status: Not started

## Implementation
- Status: Not started
