# Capture the populated-stack screenshot for the morning result card

**Date:** 2026-06-04 (preflighted 2026-06-05)
**Status:** Idea — deferred FR-9 deliverable from PR #442
**Priority:** P2
**Origin:** `feat_overnight_final_solution_phase2` Story 6 / FR-9. The plan's hard-fallback escape hatch (see [`implementation_plan.md` §"Story 6 — Task 3 hard fallback"](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/implementation_plan.md)) explicitly allowed filing this chore when the demo seed cannot reliably produce a `follow_suggestions` terminated chain at `pnpm capture-guides` time. GPT-5.5 final-review finding flagged the missing screenshot as blocking, per the plan's "screenshot is required, not waived by D-17" rule.
**Depends on:** None — the morning card ships in [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/) (PR #442) and the chain-link transition cleanup landed in [`feat_overnight_final_solution_phase3`](../../implemented_features/2026_06_05_feat_overnight_final_solution_phase3/) (PR #457). The screenshot capture needs a populated stack with a deterministic terminated multi-link `follow_suggestions` chain (one anchor + ≥1 follow-up, winning proposal + winning-link digest both landed).

## Problem

The `docs/08_guides/tutorial-first-study.md` Step 12 sub-section *"In the morning — read the overnight result card"* (verified at [tutorial-first-study.md:510](../../../../docs/08_guides/tutorial-first-study.md#L510)) shipped on PR #442 with prose only — no `![Overnight result card](...)` screenshot reference. FR-9 required the screenshot. The reason it didn't land: the standard CI demo seed (`make seed-demo`) does not produce a chain that exercises the card's full rendered state (path + convergence chip + narrative excerpt) — chain children seeded via [`/api/v1/_test/auto-followup/seed-chain`](../../../../backend/app/services/test_seeding.py#L276) (`seed_auto_followup_chain` at `backend/app/services/test_seeding.py:276`) are deliberately scoped to chain-panel / cancel-modal E2E coverage: the seeder does NOT set `selected_followup_kind`, does NOT create a winning proposal, and does NOT create a winning-link digest. Verified via `grep "selected_followup_kind\|winning" backend/app/services/test_seeding.py` (zero matches).

Operators reading the tutorial Step 12 see the prose but no visual reference for what the card looks like. The screenshot is the "show, don't tell" component of the morning-review flow documentation.

**Preflight finding (2026-06-05) — asset path is unestablished, not "existing convention":** the implementation_plan.md hedged the screenshot path as `docs/08_guides/images/12-overnight-result-card.png (or similar; placement per existing convention)`. The "existing convention" does not exist — `docs/08_guides/images/` is not present in the repo, and `tutorial-first-study.md` contains zero `![](...)` references today (verified via `grep -n "!\[" docs/08_guides/tutorial-first-study.md`). This chore introduces the **first** tutorial-image precedent and therefore owns the path decision + the multi-consumer copy mechanics. See D-1 below.

## Proposed capabilities

### Capture the populated-stack screenshot

- Boot the local stack (`make up && make seed-demo`).
- Manually create a `follow_suggestions` chain via the UI wizard:
  - Pick the **Deep (1000)** preset.
  - Set `auto_followup_depth=2`.
  - Pick **Strategy: Try suggested follow-ups** (wire value: `follow_suggestions` per [`ui/src/lib/enums.ts:93`](../../../../ui/src/lib/enums.ts#L93) `OVERNIGHT_STRATEGY_VALUES`).
  - Launch the study.
- Wait for the chain to terminate (one anchor + at least one follow-up; the digest narrative + winning proposal both need to land — terminal `stop_reason ≠ in_flight`).
- Run `pnpm capture-guides` against the now-populated state OR navigate to `/studies/{anchor.id}` in a headless browser and capture a PNG of `data-testid="overnight-result-card"` ([`ui/src/components/studies/overnight-result-card.tsx:205`](../../../../ui/src/components/studies/overnight-result-card.tsx#L205)).
- Commit the PNG at the path locked by D-1 and add the matching `![Overnight result card](...)` reference to `docs/08_guides/tutorial-first-study.md` Step 12.
- **Run `bash scripts/regen-generated-artifacts.sh`** (the canonical CLAUDE.md regen path). This invokes BOTH `ui/scripts/copy-docs.mjs` (refreshes `ui/public/docs/tutorial-first-study.md`) AND `website/scripts/build_guides.py` (refreshes `website/docs/guides/in-depth/tutorial-first-study.md`). `pnpm prebuild` alone runs only copy-docs and leaves the website copy stale — the `build-guides-freshness` CI gate would fail. See D-2.

### Optional — extend the demo seed

Alternative path that fixes this AND the AC-12 E2E downgrade in one swing: extend `/api/v1/_test/auto-followup/seed-chain` (or add a sibling test-only endpoint) to take a `selected_followup_kind` argument so seeded chain links carry non-null kinds, and to optionally seed a winning proposal + digest. Then `pnpm capture-guides` against the demo seed produces a card-rendered guide page automatically, AND the E2E spec can promote AC-12's click-through from best-effort to required.

The optional extension is the cleaner long-term fix; the per-PR screenshot capture is the minimum to close the FR-9 gap.

## Scope signals

- **Backend:** None for the minimum scope. For the optional extension: ~30–60 LOC on the `/seed-chain` test endpoint + service + tests.
- **Frontend:** None — the morning card ships in PR #442 (Phase 2); the proposals-superseded transition that lets non-winning chain links resolve cleanly ships in PR #457 (Phase 3).
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A — read-only documentation.
- **Build pipeline:** Likely 2 small edits — `ui/scripts/copy-docs.mjs` to ferry the new `images/` subtree into `ui/public/docs/images/`, and `website/scripts/build_guides.py` to ferry it into `website/docs/guides/in-depth/images/`. Without both, at least one consumer 404s the PNG. **This is the load-bearing scope item the original idea missed** (see D-1 + D-2 below) and is what turns this from "drop a PNG" into a 3–5 file chore.

## Why deferred

The CI demo seed does not produce the precondition (a terminated `follow_suggestions` chain with a winning digest + proposal) so the auto-capture path didn't work. The plan's escape hatch authorized filing this chore instead of blocking PR #442 indefinitely while operator-side capture was arranged.

## Relationship to other work

- **Built on:** [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/) — the feature being documented.
- **Coordinates with:** [`infra_solr_smoke_stability`](../../implemented_features/2026_06_02_infra_solr_smoke_stability/) precedent for "things the demo seed should produce automatically" — adding chain seeding with non-null kinds + a winning proposal would mirror that pattern.

## Locked decisions (post-preflight 2026-06-05)

- **D-1 — PNG path: `docs/08_guides/images/12-overnight-result-card.png` (locked).** No existing tutorial-image precedent, so the source-of-truth file co-locates with its source. Rationale: (a) it mirrors the docs-tree-is-source-of-truth posture used everywhere else in the repo, (b) markdown reference `![Overnight result card](images/12-overnight-result-card.png)` is the most idiomatic relative-link spelling, (c) puts the asset on the docs-edit critical path so future tutorial images cluster naturally under one directory. Alternatives considered: `ui/public/guides/<NN>/...` (rejected — that path is the walkthrough deck's convention, not the long-form tutorial's; mixing them confuses future readers) and `ui/public/docs/images/...` (rejected — the `ui/public/docs/` tree is a generated mirror, never a source).
- **D-2 — Regen tool: `bash scripts/regen-generated-artifacts.sh`, not `pnpm prebuild` (locked).** The repo has three tutorial copies — source at `docs/08_guides/`, Next.js copy at `ui/public/docs/`, MkDocs copy at `website/docs/guides/in-depth/`. `pnpm prebuild` only refreshes the first copy and would let the website copy go stale (failing the `build-guides-freshness` CI gate, breaking the relyloop.com image). The regen-artifacts wrapper is the canonical CLAUDE.md path and is the only spelling that catches all three.
- **D-3 — Build-pipeline edits (locked, scope addition).** The capture-only minimum is impossible because of D-1 + D-2 — the image won't resolve under the website MkDocs copy without `website/scripts/build_guides.py` learning to ferry `docs/08_guides/images/` → `website/docs/guides/in-depth/images/`, and similarly `ui/scripts/copy-docs.mjs` must ferry to `ui/public/docs/images/`. Both edits are small (~10 LOC each) but they are real code, not docs. **This expands the chore from "drop a PNG" to "establish + exercise the tutorial-image plumbing."** Verify under all three consumers (`grep -n "12-overnight" docs/08_guides/ ui/public/docs/ website/docs/guides/in-depth/`) before declaring done.

## Open questions

- **Q1 — Optional `seed-chain` extension: defer, do not bundle.** A `selected_followup_kind` + winning-proposal + winning-digest extension to `seed_auto_followup_chain` would also unlock the AC-12 E2E click-through promotion that PR #442 deferred (and would let `pnpm capture-guides` auto-produce the card image without manual wizard clicks). But it is **its own ~80–150 LOC chore** with its own design decisions (which kinds to seed? deterministic vs randomized parent-rank inputs to the digest seeder?). Keep this chore minimum-scope: manual local capture + the build-pipeline edits above. File the seed extension as a sibling `chore_seed_chain_winning_proposal_kind` only if/when AC-12's E2E click-through actually needs to flip from best-effort to required.
- **Q2 — Block downstream? No.** Prose landed in PR #442; operators can read the card description today. Screenshot is polish — important polish (FR-9 contract owed) but not blocking. Recommend Backlog → P2 elevation only if a guide-deck refresh swing carries this for free.
