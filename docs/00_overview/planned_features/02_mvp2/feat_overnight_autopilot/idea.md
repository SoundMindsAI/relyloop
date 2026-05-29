# Overnight autopilot — surface autonomous study chaining as a first-class "set it and wake up to results" path

**Date:** 2026-05-29
**Status:** Idea — surfaced from an operator dogfooding review (2026-05-29). The autonomous-chaining *engine* already shipped; this is the ergonomics layer that makes it discoverable.
**Priority:** P2 — high operator value, but the underlying capability already works; this is surfacing + a morning summary, not new core machinery. Pairs with [`feat_study_budget_presets`](../feat_study_budget_presets/idea.md) (the P1 of the theme).
**Origin:** Operator's stated goal: "set a study in motion, come back in a few hours (overnight), and wake up to a few results I could review and potentially turn into a PR." Tracing the live DB (2026-05-29) showed **zero** studies have ever used `auto_followup_depth` and zero are chain children — the feature that delivers exactly this goal is shipped but invisible.
**Depends on:** [`feat_auto_followup_studies`](../../../implemented_features/2026_05_24_feat_auto_followup_studies/) (shipped 2026-05-24, PR #223) — the autonomous chaining engine. This idea is purely the surfacing + summary layer on top of it.

## Problem

The "Karpathy overnight loop" is already implemented and already autonomous, but an operator has no way to discover or trust it:

1. **`auto_followup_depth` is a hidden config key.** When set (the validator accepts `0–5`, where `0` = no chaining, so `1–5` enables it — [`schemas.py:645`](../../../../../backend/app/api/v1/schemas.py#L645)), a completed study automatically narrows the search space around its winner, decrements the depth, and spawns a child study — **zero human intervention between iterations** ([`backend/workers/auto_followup.py`](../../../../../backend/workers/auto_followup.py)). The chain self-terminates on depth exhaustion, sub-epsilon lift (<0.5%), budget at 80%, or parent failure. This is exactly the operator's "wake up to a few results" ask. But it is not exposed as a first-class control in the create-study wizard — the operator never knew it existed, so all 7 studies ran one-shot.

2. **No "what happened overnight" surface.** Even with chaining on, there is no single place that says "here are the 3 studies that ran while you slept, here's the best config each found, here's the cumulative lift, here's the one that's ready to become a PR." The operator would have to piece it together from the studies list + individual proposals.

3. **The human-approval boundary is correct but undescribed.** PR-opening is deliberately a manual click (production config changes require human approval — umbrella spec §6 hard constraint). That's right, but the operator doesn't have a framing that says "the loop runs autonomously up to the PR; the PR is your one decision." Without that framing, "overnight autopilot" feels either impossible (it's not) or unsafe (it isn't — nothing reaches production without a human merge).

## Proposed capabilities

### First-class "Run overnight (compound automatically)" toggle in the create-study wizard

Promote `auto_followup_depth` from a hidden config key to a labeled wizard control with plain-language copy:

> **🌙 Run overnight (compound automatically)** — When this study finishes, automatically start a follow-up that narrows in on the best result, and repeat. Stops on its own when it stops improving, runs out of depth, or hits the daily budget. No production changes happen without your review — you still open every PR by hand.
>
> Compound up to **[3]** times. (1–5)

Pairs naturally with the "Thorough (overnight)" budget preset from [`feat_study_budget_presets`](../feat_study_budget_presets/idea.md): selecting the overnight preset could default the chain depth on. Sets the existing `config.auto_followup_depth` field — no schema change.

### Morning results summary ("the overnight digest")

A surface — a chain-view panel on the study detail page and/or a top-of-`/studies` "ran while you were away" card — that, for a completed chain, shows:

- The chain as an ordered list (parent → child → grandchild), each with its best metric and the delta from the prior link.
- Cumulative lift from the chain's start to its best link.
- A clear "best config across the whole chain" and a one-click path to the proposal that carries it (which is then one more click from a PR).
- Why the chain stopped (depth exhausted / no further lift / budget) — reusing the telemetry events the worker already emits (`auto_followup_depth_exhausted`, `auto_followup_skipped_no_lift`, `auto_followup_skipped_budget`).

This is the "wake up to a few results you could review and potentially turn into a PR" deliverable, made concrete.

### Tutorial + docs: name the autopilot path

A short tutorial section ("Run the loop overnight") that walks: pick the overnight budget preset → enable compounding depth 3 → start before you log off → review the chain summary in the morning → open the winning PR. Make the human-approval boundary explicit and reassuring.

## Scope signals

- **Backend:** small-to-moderate. Mostly read-side: a chain-summary aggregation (walk `parent_study_id` links, roll up best metrics + deltas + stop reason). The write path (`auto_followup_depth`) already exists and is validated. No migration.
- **Frontend:** moderate. Wizard toggle + the chain-summary panel/card. The chain-summary panel is the bulk of the work.
- **Migration:** none.
- **Config:** none (uses existing `config.auto_followup_depth` and existing budget settings).
- **Audit events:** N/A (pre-`audit_log`).

## Why this isn't just "add a tooltip"

The capability is real but the *trust and discoverability* gap is the whole barrier. An operator will not hand a tool an unattended overnight run unless (a) they can find the switch, (b) they understand it can't touch production without them, and (c) there's a clean morning surface that makes the results reviewable in minutes. All three are missing today, which is why a shipped feature has zero usage.

## Relationship to other work

- **Surfaces** [`feat_auto_followup_studies`](../../../implemented_features/2026_05_24_feat_auto_followup_studies/) (the engine).
- **Sibling theme:** [`feat_study_budget_presets`](../feat_study_budget_presets/idea.md) (the overnight preset feeds this) + [`feat_study_convergence_indicator`](../feat_study_convergence_indicator/idea.md) (each chain link's convergence display).
- **Composes with the MVP2 UBI anchor** ([`feat_ubi_judgments`](../feat_ubi_judgments/idea.md)): overnight compounding is dramatically more valuable against a continuously-fresh UBI judgment list than a static LLM snapshot — the `feat_ubi_judgments` idea already notes this composition. This is the operator-facing payoff of that pairing.
- **Respects** the human-merge invariant (umbrella spec §6) — autopilot runs the *exploration* side unattended; the *deployment* side stays a deliberate human click.

## Open questions for /spec-gen

1. Where the morning summary lives: study-detail chain panel, a `/studies` "ran while away" card, or both.
2. Whether selecting the "Thorough (overnight)" budget preset auto-enables compounding (and at what default depth), or whether they stay independent toggles.
3. Whether to add an optional notification hook (the spec backlog already lists "outgoing webhooks for resource lifecycle events" — a chain-complete webhook would be the real "wake up to results" trigger, but that's likely a separate backlog item, not MVP2).
