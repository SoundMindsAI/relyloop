# UBI on-ramp — keep no-signals operators first-class and nudge them toward real user signals

**Date:** 2026-05-29
**Status:** Idea — split out from [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) as a first-class feature (2026-05-29) so the no-signals-majority UX is dashboard-visible and not treated as optional UBI polish.
**Priority:** P1 — ships *with* the UBI anchor, not after. The majority of OSS-search deployments have no UBI plugin installed; this feature is what keeps MVP2 a strict upgrade for them rather than a release aimed only at the traffic-rich minority. See [`mvp2-overview.md` §4 "Design principle — no-UBI operators stay first-class"](../../../../01_architecture/mvp2-overview.md).
**Origin:** Operator review of the MVP2 plan (2026-05-29) — explicit requirement that UBI work "still has great support for apps that do not yet collect user signals" and "nudges the user to help them know how to improve." These were the B10–B13 story stubs inside `feat_ubi_judgments`; promoted to their own folder per an explicit granularity decision.
**Depends on:** [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) (the `UbiReader` / `SignalsConverter` / `generate-from-ubi` substrate this feature surfaces and degrades gracefully from). The engine-aware nudge (capability 2) covers all three engines only **after** [`infra_adapter_solr`](../infra_adapter_solr/idea.md) extends `engine_type` to accept `solr` — until then it is ES + OpenSearch, exactly like the rest of MVP1.

## Problem

`feat_ubi_judgments` adds click-derived judgments, but a UBI-centric release has a well-known failure mode: it makes the operators who *don't* have UBI feel like second-class citizens, when in reality they are the majority. Three concrete gaps if the on-ramp isn't built:

1. **The `UBI_NOT_ENABLED` (412) error is a dead-end, not an on-ramp.** A no-UBI operator who tries the UBI path gets a bare error code at the exact moment of maximum intent. There is no detection-and-guidance surface that says "here's how to turn on real user signals on *your* engine."

2. **Sparse UBI degrades into a hard failure (`UBI_INSUFFICIENT_DATA`, 422) rather than a recommendation.** An operator with *some* traffic should be steered into hybrid mode ("UBI rates the dense head, LLM fills the tail") and told concretely what they'd gain by collecting more — not bounced.

3. **The value of real signals is asserted, never shown.** The strongest nudge is the delta — "this UBI list covered 90% of last week's real traffic" beside "the previous LLM list rated 500 pairs on a snapshot." Without it, a no-UBI operator has no concrete reason to invest in enabling UBI.

A hard constraint frames all three: **RelyLoop never installs the plugin, never writes to the cluster, never modifies schema** (umbrella spec §4 non-goals). Every nudge is *guidance only* — detection plus engine-specific runbook links. Enabling UBI is always the operator's action on their own infrastructure.

## UBI readiness ladder

Each cluster sits on a rung (detected read-only via a `get_schema` probe for the `ubi_queries` index); the tool recommends the right judgment mode and nudges toward the next rung.

| Rung | State | Recommended mode | Nudge |
|---|---|---|---|
| 0 — No UBI | `ubi_queries` absent | **LLM-as-judge** (unchanged from MVP1) | "Enable real user signals" card → engine-specific runbook. Non-blocking, dismissible. |
| 1 — Installed, sparse | `ubi_queries` present, below `min_impressions_threshold` for most pairs | **Hybrid UBI+LLM** (UBI head + LLM tail) | "You have early signal — here's how much more traffic strengthens it." Show coverage %. |
| 2 — Dense head | enough impressions on the head; long tail thin | **Hybrid UBI+LLM** (default) | "Most adopters ship from here." Show head/tail split. |
| 3 — Full coverage | dense across the query set | **UBI threshold converter** (CTR or dwell) | "Counterfactual click models (CCM/DBN) become viable — post-MVP2." |

This ladder is *why* `HybridUbiLlmConverter` is the default recommended converter (the rung most real operators occupy), not the conservative CTR one.

## Proposed capabilities

### 1. Readiness probe + ladder surfacing (read-only) — was B10

- Reuse the `get_schema` probe for `ubi_queries` to classify each cluster on the rung 0–3 ladder; expose the rung on cluster detail and as a small badge on cluster cards.
- Turn the `UBI_NOT_ENABLED` (412) condition (defined in [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) §"API surface") from a bare error into a structured, renderable state the UI consumes.
- **No cluster writes** — detection only.

### 2. Engine-aware "enable real user signals" nudge — was B11

- A dismissible card on the judgment-generation modal and cluster-detail page when UBI is absent (rung 0), with steps specific to the cluster's `engine_type`:
  - **OpenSearch** → OpenSearch UBI plugin
  - **Elasticsearch** → o19s ES UBI fork
  - **Solr** → first-party `solr.UBIComponent` (available once [`infra_adapter_solr`](../infra_adapter_solr/idea.md) lands; `engine_type` accepts only `elasticsearch | opensearch` today per [`backend/app/db/models/cluster.py:30`](../../../../../backend/app/db/models/cluster.py#L30))
- Deep-links to the new `docs/03_runbooks/ubi-judgment-generation.md` (authored in `feat_ubi_judgments` B9).
- Reuses the shipped contextual-help idiom — [`feat_contextual_help`](../../../implemented_features/2026_05_15_feat_contextual_help/) ([`ui/src/components/common/help-popover.tsx`](../../../../../ui/src/components/common/help-popover.tsx)) — and the existing client-side dismissal pattern ([`ui/src/hooks/use-local-storage-set.ts`](../../../../../ui/src/hooks/use-local-storage-set.ts), as used by [`demo-data-banner.tsx`](../../../../../ui/src/components/dashboard/demo-data-banner.tsx)).
- **Never blocks the LLM path.** Re-surfaces on next visit if dismissed but the underlying rung is still 0.

### 3. Sparse-data guidance, not a wall — was B12

- When UBI is present but below `min_impressions_threshold` (rung 1), the would-be `UBI_INSUFFICIENT_DATA` (422) path instead **recommends hybrid mode** and shows current coverage ("~12% of your query set has enough signal — hybrid rates that head, LLM fills the rest").
- The empty/partial state on the judgment-list detail page explains *why* pairs were dropped and what closes the gap.

### 4. Value-delta framing — was B13

- On UBI/hybrid list completion, surface coverage stats ("covered N queries / X% of traffic in the window").
- Where a prior LLM list exists on the same query set, show the metric/coverage delta — the concrete "here's what real signals bought you" moment.
- Feeds the PR-body confidence framing (composes with shipped [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/)): "scored against 50,000 UBI-derived ratings covering 90% of last week's traffic" is a far stronger claim than "500 LLM ratings on a snapshot."

## Scope signals

- **Backend:** small. The readiness classifier is a read-side wrapper over the same `get_schema` probe `feat_ubi_judgments` already uses; turning `UBI_NOT_ENABLED` / `UBI_INSUFFICIENT_DATA` into structured states (vs. bare errors) is a response-shape change, not new core logic. No new cluster-write path.
- **Frontend:** moderate — the bulk of this feature. Rung badge + readiness surfacing; the engine-aware nudge card; sparse-data recommendation copy; the value-delta surface on list completion.
- **Migration:** **none.** Pure read-side detection + UX over the existing `judgments` substrate (rides `feat_ubi_judgments`, which is itself zero-migration).
- **Config:** the `min_impressions_threshold` / rung boundaries are constants (possibly an optional setting); no required new config.
- **Audit events:** N/A (MVP2 is pre-`audit_log`).

## Why split from `feat_ubi_judgments` (not left as story stubs)

- **Dashboard visibility.** As stubs inside the anchor's idea, the no-signals-majority UX is invisible to `/pipeline status` and the MVP2 dashboard, and risks being treated as optional polish at implementation time. As a P1 folder it is tracked and sequenced explicitly.
- **Clean ownership boundary.** `feat_ubi_judgments` owns the *machinery* (reader, converters, endpoint, agent tool); this feature owns the *no-UBI / partial-UBI operator experience* on top of it. Two reviewable units, one coherent each.
- **Single coherent system, one file.** Capabilities 1–4 share one detection mechanism (the `ubi_queries` probe), one dismissal-state question, and one engine-aware-copy concern — so they belong in one idea, not four.

## Relationship to other work

- **Depends on / surfaces** [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) (the anchor) — ships in the same release, sequenced together.
- **Engine-aware nudge spans all three engines only after** [`infra_adapter_solr`](../infra_adapter_solr/idea.md).
- **Reuses** [`feat_contextual_help`](../../../implemented_features/2026_05_15_feat_contextual_help/) (the nudge idiom + dismissal pattern).
- **Feeds** [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/) (value-delta → PR confidence framing).
- **Tracked in** [`mvp2-overview.md` Workstream B](../../../../01_architecture/mvp2-overview.md) (capabilities 1–4 = the former B10–B13).

## Open questions for /spec-gen

1. **Nudge persistence + cadence** — store "dismissed" client-side (localStorage, like `demo-data-banner`) or per-cluster server-side? Re-surface on a schedule or only while the readiness rung is unchanged?
2. **Readiness thresholds** — what impression counts define the rung 1→2→3 boundaries; operator-configurable or fixed defaults for MVP2?
3. **Value-delta baseline** — when no prior LLM list exists on the query set, what does capability 4 show (coverage-only? a one-off LLM spot-rating for comparison? nothing)?
