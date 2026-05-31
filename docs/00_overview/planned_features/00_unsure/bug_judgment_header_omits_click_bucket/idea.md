# Idea — judgment-list header omits the `click` (UBI) source bucket

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Story 2.1, PR forthcoming)
**Type:** `bug_`
**Priority:** P2 — UBI-derived judgment lists under-report their composition in the header; no data loss, but the source-breakdown card is misleading on UBI/hybrid lists.

## Origin

While regenerating `ui/src/lib/types.ts` for `feat_overnight_autopilot` Story 2.1, the refreshed `_SourceBreakdown` schema surfaced a required `click` bucket (added by `feat_ubi_judgments`, MVP2). The generated type's doc comment states:

> "the UI's source-breakdown card now renders all three buckets separately"

But [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) renders only `source_breakdown.llm` and `source_breakdown.human` — the `click` bucket (UBI-derived judgments) is not displayed.

## Problem

A judgment list generated from UBI (or hybrid UBI+LLM) carries non-zero `source_breakdown.click`, but the header's source-breakdown card silently drops it. Operators reviewing a UBI list see only the LLM/human split and can't tell how many judgments came from real click behavior — which is the entire value proposition of the UBI path.

## Proposed capability

Render the `click` bucket in the source-breakdown card alongside `llm` and `human`, with an appropriate label (e.g. "UBI clicks") and the existing per-bucket styling. Verify the doc-comment claim ("renders all three buckets separately") becomes true.

## Scope signals

- **Backend:** none (the field already exists on the wire).
- **Frontend:** small — one component (`judgment-list-header.tsx`) + its vitest.
- **Migration / config:** none.
- **Audit events:** N/A.

## Why deferred (not fixed inline)

Different feature surface (judgments UI) than the overnight-autopilot chain panel; out of scope for that PR. Bounded and cheap, but belongs with the judgments-header component, not the chain feature.

## Relationship to other work

- Originating feature: `feat_ubi_judgments` (shipped 2026-05-29) — added the `click` bucket to `_SourceBreakdown` and the doc comment that this component doesn't yet honor.
- Sibling deferred UBI cleanup: `chore_ubi_hybrid_template_render`, `chore_ubi_reader_search_after_pagination`.
