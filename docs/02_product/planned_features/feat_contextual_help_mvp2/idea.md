# feat — contextual help / tooltips (MVP2 Phases 2 + 3)

**Date:** 2026-05-15
**Status:** Idea — deferred from `feat_contextual_help` Phase 1 (MVP1, shipped via [PR #122](https://github.com/SoundMindsAI/relyloop/pull/122) on 2026-05-15).
**Origin:** Carved out of the original `feat_contextual_help/idea.md` during scope-lock; the locked decision was MVP1 Phase 1 only. Phases 2 + 3 stay tracked here so they're discoverable by future planning sessions and surface in the MVP2 dashboard.
**Depends on:** The Phase 1 primitives + glossary infrastructure already ship in `main` per PR #122 — `Tooltip` primitive, `InfoTooltip` + `HelpPopover` wrappers, and `ui/src/lib/glossary.ts` source-of-truth file are all in place. Phase 2 + 3 are purely additive: extend the glossary + apply wrappers to new surfaces.

## Problem

Phase 1 covered the create-study modal + study-detail surface — the steepest onboarding cliff. Two clusters of surfaces remain that a relevance engineer encounters after running their first study:

- **Phase 2** ([`phase2_idea.md`](phase2_idea.md)): judgments review + calibration modal + proposals lifecycle. Second-order onboarding impact — users reach these after running a study.
- **Phase 3** ([`phase3_idea.md`](phase3_idea.md)): chat composer example prompts + cluster registration auth-kind help + home-page first-run "start here" panel. First-run onboarding work; the home-page panel is the only product-design-shaped item.

The implemented Phase 1 spec + plan are archived at [`docs/00_overview/implemented_features/2026_05_15_feat_contextual_help/`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/).

## Proposed capabilities

See the two phase trackers in this folder:

- [`phase2_idea.md`](phase2_idea.md) — full FR-level breakdown for judgments + proposals.
- [`phase3_idea.md`](phase3_idea.md) — full FR-level breakdown for chat + cluster registration + home onboarding.

The next step is either (a) one combined `/pipeline` run on this folder generating a single MVP2 spec covering both phases, or (b) splitting into two separate planned-feature folders (`feat_contextual_help_phase2` / `feat_contextual_help_phase3`) for independent /pipeline runs. The design call is part of the MVP2 spec-gen flow, not this idea.

## Scope signals

- **Backend:** none. Frontend-only glossary additions + per-surface wrapper application.
- **Frontend:** ~10 page/component file edits across the two phases + ~25 new glossary keys (per-wire-value entries for `JudgmentSourceWire`, `JudgmentSourceFilterWire`, `RatingWire`, `ProposalStatusWire`, `ProposalPrStateWire`, `AuthKind`, `EnvironmentWire` from [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts)).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — view-only UI.
- **CLAUDE.md absolute-rules walked:** Enumerated Value Contract Discipline — every new glossary group cites its backend source-of-truth file per the FR-4 / FR-10 pattern established in Phase 1.

## Why deferred

- Design partners are expected to start with study creation (Phase 1 surface). Phase 1 absorbs the steepest cliff; Phase 2/3 have second-order impact.
- Splitting Phase 1 vs. Phase 2/3 lets design-partner feedback after Phase 1 ships inform Phase 2/3 priorities (e.g., whether calibration help is more urgent than chat example prompts).
- The Phase 3 "Start here" panel has an open product/UX design question (Stripe-style checklist vs. illustration vs. simple ordered list) that benefits from real feedback before locking.

## Relationship to other work

- [`implemented_features/2026_05_15_feat_contextual_help/`](../../../00_overview/implemented_features/2026_05_15_feat_contextual_help/) — Phase 1 (shipped, PR #122). All primitives + glossary infrastructure live here.
- [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/) — the underlying judgments + calibration data model Phase 2 overlays.
- [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/) — the proposals data model Phase 2 overlays.
- [`feat_github_pr_worker`](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/) — the proposals "Open PR" lifecycle Phase 2 explains via tooltip copy.
- [`feat_chat_agent`](../../../00_overview/implemented_features/2026_05_12_feat_chat_agent/) — the chat surface Phase 3 adds prompt seeding to.
- [`infra_adapter_elastic`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — the cluster registration data model Phase 3 overlays.
- [`feat_studies_ui`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) — the home page (`app/page.tsx`) Phase 3 adds the first-run panel to.
- [`infra_e2e_seed_completed_study`](../infra_e2e_seed_completed_study/) — cross-cutting E2E helper. Phase 2 (digest panel + proposals lifecycle E2E coverage) benefits from this helper too.
