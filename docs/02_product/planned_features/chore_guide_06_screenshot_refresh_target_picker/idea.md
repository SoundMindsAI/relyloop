# Refresh guide 06 screenshot for the new target picker

**Date:** 2026-05-20
**Status:** Idea — surfaced during `feat_create_study_target_autocomplete` post-impl guide-impact assessment.
**Origin:** `feat_create_study_target_autocomplete` F2 changes the create-study modal Step 1 visually (target field is now a disabled `<Select>` "Pick a cluster first" placeholder by default, plus a new "Enter manually" toggle button below it, plus the unchanged "{N} fields discovered" hint). The single guide-06 screenshot at [`ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png`](../../../../ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png) — captured by [`ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts:53`](../../../../ui/tests/e2e/guides/06_create_and_monitor_study.spec.ts#L53) — still shows the prior free-text `<Input>` UI.
**Depends on:** `feat_create_study_target_autocomplete` PR must be merged (the screenshot regen runs against the post-merge UI).

## Problem

The walkthrough guide 06 ("Create and monitor a study") shows the operator opening the create-study modal as part of the wizard tour. The single Step-1 screenshot now disagrees with shipped UI — operators following the guide will see something different from what they're shown.

No functional impact (the spec itself only walks the modal opening + closes it immediately; no fill, no submit). The drift is cosmetic but reduces guide trust.

## Why not bundled into the parent PR

- Guide screenshot regen requires `make up` against the post-merge UI + a guide-capture run + PNG diff review. That's a separate operator-environment step.
- Following the established precedent: `chore_form_dropdown_guide_screenshot_refresh` (PR #154, 2026-05-19) regenerated 20 PNGs across 4 walkthroughs in response to `chore_form_dropdown_primitive` (PR #136). Same pattern — UI change ships first, screenshots refresh in a follow-up chore PR.
- The parent feature PR scope is already 6 commits + dashboards + bundled bug fix; adding a binary-diff PNG refresh would muddy the review.

## Proposed capabilities

### Capability 1 — Regenerate guide-06 screenshot

Run `pnpm capture-guides` (or the equivalent guide-specific capture) against the post-merge UI; replace the single PNG at `ui/public/guides/06_create_and_monitor_study/03-create-study-modal.png`; visual-diff against the prior version to confirm only the target field changed.

### Capability 2 (optional) — Audit guide 06's tutorial-first-study sibling

[`docs/08_guides/tutorial-first-study.md`](../../../03_runbooks/release-checklist.md) (and the broader walkthrough catalog) may also describe Step 1 in prose. If the prose references "type the target name" or similar, update to mention the dropdown + manual-mode fallback.

## Scope signals

- **Backend:** N/A.
- **Frontend:** N/A (no source code change — just a regenerated PNG).
- **Migration:** N/A.
- **Config:** N/A.
- **Audit events:** N/A.

## Relationship to other work

- **Builds on** [`feat_create_study_target_autocomplete`](../feat_create_study_target_autocomplete/) — must merge first.
- **Pattern from** [`chore_form_dropdown_guide_screenshot_refresh`](../../00_overview/implemented_features/2026_05_19_chore_form_dropdown_guide_screenshot_refresh/) — PR #154, same approach.
