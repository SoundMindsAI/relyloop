# feat — contextual help / tooltips (Phases 2 + 3 — shipped 2026-05-15)

**Date:** 2026-05-15
**Status:** **Shipped** as PR [#124](https://github.com/SoundMindsAI/relyloop/pull/124) (squash-merged 2026-05-15, commit `9d22f62`). Operator-driven scope expansion immediately after Phase 1 (#122) merged — the original MVP1-Phase-1-only scope lock was reversed when the operator decided to ship all three phases together rather than waiting for MVP2. This folder was created as planned-features tracking at finalization of Phase 1; PR #124 then implemented + merged it the same day.
**Origin:** Carved out of the original `feat_contextual_help/idea.md` during scope-lock. Initially deferred to MVP2; promoted to "ship now" once Phase 1 landed and the operator confirmed they wanted the full surface area.
**Depends on:** Phase 1 primitives + glossary infrastructure shipped in PR #122 — `Tooltip` primitive, `InfoTooltip` + `HelpPopover` wrappers, and `ui/src/lib/glossary.ts` source-of-truth file were all in place when this work began. Phases 2 + 3 were purely additive: extended the glossary + applied wrappers to new surfaces + added 2 new first-run components.

## Problem

Phase 1 covered the create-study modal + study-detail surface — the steepest onboarding cliff. Two clusters of surfaces remain that a relevance engineer encounters after running their first study:

- **Phase 2** ([`phase2_idea.md`](phase2_idea.md)): judgments review + calibration modal + proposals lifecycle. Second-order onboarding impact — users reach these after running a study.
- **Phase 3** ([`phase3_idea.md`](phase3_idea.md)): chat composer example prompts + cluster registration auth-kind help + home-page first-run "start here" panel. First-run onboarding work; the home-page panel is the only product-design-shaped item.

The implemented Phase 1 spec + plan are archived at [`docs/00_overview/implemented_features/2026_05_15_feat_contextual_help/`](../2026_05_15_feat_contextual_help/).

## Proposed capabilities

See the two phase trackers in this folder:

- [`phase2_idea.md`](phase2_idea.md) — full FR-level breakdown for judgments + proposals.
- [`phase3_idea.md`](phase3_idea.md) — full FR-level breakdown for chat + cluster registration + home onboarding.

**Outcome (2026-05-15):** option (a) was chosen — single combined PR #124. No separate spec was generated; the original phase trackers carried enough detail (FR-level surface lists + glossary keys + parity-test mappings) to drive implementation directly. Implementation followed the established Phase 1 pattern (extend `glossary.ts` + apply wrappers + wrap pre-existing tests in `TooltipProvider`).

## Scope signals

- **Backend:** none. Frontend-only glossary additions + per-surface wrapper application.
- **Frontend:** ~10 page/component file edits across the two phases + ~25 new glossary keys (per-wire-value entries for `JudgmentSourceWire`, `JudgmentSourceFilterWire`, `RatingWire`, `ProposalStatusWire`, `ProposalPrStateWire`, `AuthKind`, `EnvironmentWire` from [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts)).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — view-only UI.
- **CLAUDE.md absolute-rules walked:** Enumerated Value Contract Discipline — every new glossary group cites its backend source-of-truth file per the FR-4 / FR-10 pattern established in Phase 1.

## Why deferred → reversed and shipped same-day

The original rationale for deferring to MVP2:

- Design partners expected to start with study creation (Phase 1 surface), giving Phase 1 the steepest-cliff priority.
- Phase 3 "Start here" panel had an open product/UX design question (Stripe checklist vs. illustration vs. simple list).

What changed: the operator reviewed Phase 1's `feat_contextual_help_mvp2/idea.md` finalization output and asked to ship everything together rather than wait. The Start-here-panel design question was resolved inline ("Stripe-style checklist with progress detection") and Phases 2 + 3 went into PR #124 the same day Phase 1 finalized.

## Relationship to other work

- [`implemented_features/2026_05_15_feat_contextual_help/`](../2026_05_15_feat_contextual_help/) — Phase 1 (shipped, PR #122). All primitives + glossary infrastructure live here.
- [`feat_llm_judgments`](../2026_05_11_feat_llm_judgments/) — the underlying judgments + calibration data model Phase 2 overlays.
- [`feat_digest_proposal`](../2026_05_11_feat_digest_proposal/) — the proposals data model Phase 2 overlays.
- [`feat_github_pr_worker`](../2026_05_12_feat_github_pr_worker/) — the proposals "Open PR" lifecycle Phase 2 explains via tooltip copy.
- [`feat_chat_agent`](../2026_05_12_feat_chat_agent/) — the chat surface Phase 3 adds prompt seeding to.
- [`infra_adapter_elastic`](../2026_05_10_infra_adapter_elastic/) — the cluster registration data model Phase 3 overlays.
- [`feat_studies_ui`](../2026_05_12_feat_studies_ui/) — the home page (`app/page.tsx`) Phase 3 adds the first-run panel to.
- [`infra_e2e_seed_completed_study`](../infra_e2e_seed_completed_study/) — cross-cutting E2E helper. Phase 2 (digest panel + proposals lifecycle E2E coverage) benefits from this helper too.
