# Capture the populated-stack screenshot for the morning result card

**Date:** 2026-06-04
**Status:** Idea — deferred FR-9 deliverable from PR #442
**Priority:** P2
**Origin:** `feat_overnight_final_solution_phase2` Story 6 / FR-9. The plan's hard-fallback escape hatch (see [`implementation_plan.md` §"Story 6 — Tasks #3 hard fallback"](../feat_overnight_final_solution_phase2/implementation_plan.md)) explicitly allowed filing this chore when the demo seed cannot reliably produce a `follow_suggestions` terminated chain at `pnpm capture-guides` time. GPT-5.5 final-review finding flagged the missing screenshot as blocking, per the plan's "screenshot is required, not waived by D-17" rule.
**Depends on:** None — the morning card ships in [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/) (PR #442). The screenshot capture needs a populated stack with a deterministic terminated multi-link `follow_suggestions` chain.

## Problem

The `docs/08_guides/tutorial-first-study.md` Step 12 sub-section *"In the morning — read the overnight result card"* shipped on PR #442 with prose only — no `![Overnight result card](images/12-overnight-result-card.png)` screenshot reference. FR-9 required the screenshot. The reason it didn't land: the standard CI demo seed (`make seed-demo`) does not produce a chain that exercises the card's full rendered state (path + convergence chip + narrative excerpt) — chain children seeded via `/api/v1/_test/auto-followup/seed-chain` have NULL `selected_followup_kind` (legacy narrow pattern), no winning proposal, no winning-link digest.

Operators reading the tutorial Step 12 see the prose but no visual reference for what the card looks like. The screenshot is the "show, don't tell" component of the morning-review flow documentation.

## Proposed capabilities

### Capture the populated-stack screenshot

- Boot the local stack (`make up && make seed-demo`).
- Manually create a `follow_suggestions` chain via the UI wizard:
  - Pick the **Deep (1000)** preset.
  - Set `auto_followup_depth=2`.
  - Pick **Strategy: Try suggested follow-ups**.
  - Launch the study.
- Wait for the chain to terminate (one anchor + at least one follow-up; the digest narrative + winning proposal both need to land).
- Run `pnpm capture-guides` against the now-populated state OR navigate to `/studies/{anchor.id}` in a headless browser and capture a PNG of `data-testid="overnight-result-card"`.
- Commit the resulting `docs/08_guides/images/12-overnight-result-card.png` and add the `![Overnight result card](images/12-overnight-result-card.png)` reference to `docs/08_guides/tutorial-first-study.md` Step 12.
- Regenerate `ui/public/docs/tutorial-first-study.md` via `pnpm prebuild` (the copy-docs gate).

### Optional — extend the demo seed

Alternative path that fixes this AND the AC-12 E2E downgrade in one swing: extend `/api/v1/_test/auto-followup/seed-chain` (or add a sibling test-only endpoint) to take a `selected_followup_kind` argument so seeded chain links carry non-null kinds, and to optionally seed a winning proposal + digest. Then `pnpm capture-guides` against the demo seed produces a card-rendered guide page automatically, AND the E2E spec can promote AC-12's click-through from best-effort to required.

The optional extension is the cleaner long-term fix; the per-PR screenshot capture is the minimum to close the FR-9 gap.

## Scope signals

- **Backend:** None for the minimum scope (just capture the screenshot). For the optional extension: ~30–60 LOC on the `/seed-chain` test endpoint + tests.
- **Frontend:** None — the morning card ships in PR #442.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A — read-only.

## Why deferred

The CI demo seed does not produce the precondition (a terminated `follow_suggestions` chain with a winning digest + proposal) so the auto-capture path didn't work. The plan's escape hatch authorized filing this chore instead of blocking PR #442 indefinitely while operator-side capture was arranged.

## Relationship to other work

- **Built on:** [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/) — the feature being documented.
- **Coordinates with:** [`infra_solr_smoke_stability`](../../implemented_features/2026_06_02_infra_solr_smoke_stability/) precedent for "things the demo seed should produce automatically" — adding chain seeding with non-null kinds + a winning proposal would mirror that pattern.

## Open questions

- **Q1** Capture path: manual local capture vs extend `seed-chain` endpoint? Recommend manual local capture for the minimum (lowest cost to clear FR-9); the demo-seed extension is its own follow-up if AC-12's E2E click-through ever needs to be promoted from best-effort.
- **Q2** Should this block any downstream work? Recommend no — the prose lands in PR #442, operators can read the card description. The screenshot is a polish item.
