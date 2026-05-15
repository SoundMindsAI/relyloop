# feat_contextual_help — Phase 2 deferred tracking (judgments + proposals)

**Date:** 2026-05-14
**Status:** Deferred — Phase 1 ([`feature_spec.md`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md), shipped via PR #122 on 2026-05-15) covered create-study modal + study-detail surface only. Phase 2 picks up the judgments-review + proposals surfaces.
**Origin:** Carved out of [`feat_contextual_help/idea.md`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/idea.md) §"Proposed capabilities → Phase 2 — judgments + proposals" during cycle 1 of spec-gen scope-lock (2026-05-14, idea Locked Decisions §1).
**Depends on:** Phase 1 ships (the primitives `Tooltip`, `InfoTooltip`, `HelpPopover` and the `ui/src/lib/glossary.ts` source-of-truth file). Once those are in place, Phase 2 is purely a per-surface application pass plus glossary-content additions.

## Problem (still applicable after Phase 1)

Phase 1 absorbs the steepest onboarding cliff (create-study modal Step 5 + digest panel). Two surfaces remain that a relevance engineer hits after running their first study:

1. **Judgments review** (`/judgments/[id]`) — the relevance rating page. The 0–3 rating scale appears on every row with no inline legend; the `source` column shows `llm` / `human` / `click` with no explanation of when each is produced; the override button has no tooltip explaining what manual overrides do or how they're stored.
2. **Calibration modal** ([`calibration-modal.tsx`](../../../../ui/src/components/judgments/calibration-modal.tsx)) — the Cohen's κ panel shows a number with no interpretation guidance (κ > 0.7 strong / 0.4–0.7 moderate / < 0.4 needs calibration).
3. **Proposals lifecycle** (`/proposals` list + `/proposals/[id]`) — status badges (`pending` → `pr_opened` → `pr_merged` | `rejected`) have no lifecycle explanation; the `pr-panel.tsx` Open PR button (a distinct component from the digest-panel's Open PR button — see [Phase 1 spec FR-9 clarifying note](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md)) has no tooltip; config-diff column headers don't explain what `From` / `To` mean in context.

## Proposed Phase 2 capabilities (full list — pick up in MVP2 spec)

### Judgments review page

- `Relevance` column header — `InfoTooltip` (key: `judgment.relevance`) with the 0–3 scale legend.
- Per-rating-value tooltips on each row's rating display — `InfoTooltip` (keys: `judgment.rating.0`, `judgment.rating.1`, `judgment.rating.2`, `judgment.rating.3`) per the FR-4 parity-prefix table; values must match [`backend/app/api/v1/schemas.py:RatingWire`](../../../../backend/app/api/v1/schemas.py).
- `Source` column header — `InfoTooltip` (key: `judgment.source`). Per-value tooltips `judgment.source.{llm,human,click}` must match `JudgmentSourceWire` in the same schemas file.
- `Override` button — `InfoTooltip` (key: `judgment.override_button`) explaining that overrides are persisted as `judgment_overrides` rows and affect the next study trial against this judgment list.
- Source filter chips at the top of the page — `InfoTooltip` per chip explaining `all` / `llm` / `human` filtering.

### Calibration modal

- "Run calibration" section — `HelpPopover` (key: `judgment.calibration`) with multi-line guidance: paste CSV format, Cohen's κ interpretation (κ > 0.7 strong / 0.4–0.7 moderate / < 0.4 needs calibration), expected sample-size minimum.
- Existing `DialogDescription` at [`calibration-modal.tsx:109`](../../../../ui/src/components/judgments/calibration-modal.tsx) is preserved; the help-popover is additive.

### Proposals list page

- Status filter chips (`pending` / `pr_opened` / `pr_merged` / `rejected`) — `InfoTooltip` per chip with the status meaning, sourced from `study.proposal.status.*` parity-prefix glossary keys. Values must match [`backend/app/api/v1/schemas.py:ProposalStatusWire`](../../../../backend/app/api/v1/schemas.py).
- Source filter chips (`digest` / `manual`) — `InfoTooltip` per chip.

### Proposals detail page

- Status badge — `InfoTooltip` (adjacent icon, Pattern A per [Phase 1 spec FR-7 precedent](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md)) showing the lifecycle and current-state meaning.
- PR state badge (when a PR exists) — `InfoTooltip` per `proposal.pr_state.{open,closed,merged}` value. Values must match `ProposalPrStateWire` in the same schemas file.
- `pr-panel.tsx` `Open PR…` button — `InfoTooltip asChild` (Pattern B per [Phase 1 spec FR-9 precedent](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md)). Glossary key: `proposal.open_pr_button`. **This is a structurally different button** from the Phase 1 digest-panel Open PR — same label, different component, different route.
- Config-diff column headers (`Key`, `From`, `To`) — `InfoTooltip` explaining each.
- Metric-delta interpretation — `InfoTooltip` explaining the baseline → best convention and direction-aware sign.
- "Suggested follow-ups" section header — `InfoTooltip` explaining LLM-generated next-study suggestions.

## Scope signals

- **Backend:** none. Phase 2 is purely frontend glossary additions + per-surface application of the existing Phase 1 wrappers.
- **Frontend:** glossary entries (~25 new keys across the parity-prefix groups for judgment ratings, judgment sources, proposal statuses, proposal PR states); edits to ~6 page/component files (`judgments-table.tsx`, `judgment-list-header.tsx`, `calibration-modal.tsx`, `proposals-table.tsx`, `proposal-header.tsx`, `pr-panel.tsx`, `config-diff-panel.tsx`).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — view-only UI, no state mutations.
- **CLAUDE.md absolute-rules walked:** Enumerated Value Contract Discipline — every new glossary group cites its backend source-of-truth file per the FR-4 / FR-10 pattern established in Phase 1.

## Why this is deferred

- Design partners are expected to start with study creation (Phase 1 surface) and only reach judgments / proposals after running their first end-to-end study. Phase 1 tooltips absorb the steepest cliff; Phase 2 surfaces have second-order onboarding impact.
- Splitting Phase 1 vs. Phase 2 lets design-partner feedback after Phase 1 ships inform whether Phase 2 priorities change (e.g., calibration help may be more or less urgent than expected).

## Relationship to other work

- [`feat_contextual_help/feature_spec.md`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/feature_spec.md) — Phase 1 (shipped) provides the primitives, wrappers, and glossary file; Phase 2 is a per-surface application pass on top.
- [`feat_llm_judgments` (PR #35)](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/) — the underlying judgments + calibration data model and UI this phase overlays.
- [`feat_digest_proposal` (PR #41)](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/) — the proposals data model + UI this phase overlays.
- [`feat_github_pr_worker` (PR #45)](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/) — the proposals "Open PR" lifecycle this phase explains via tooltip copy.
