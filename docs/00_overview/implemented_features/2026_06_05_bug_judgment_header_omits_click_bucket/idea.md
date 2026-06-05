# Idea — judgment-list header omits the `click` (UBI) source bucket

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Story 2.1, PR forthcoming)
**Type:** `bug_`
**Priority:** P2 — UBI-derived judgment lists under-report their composition in the header; no data loss, but the source-breakdown card is misleading on UBI/hybrid lists.

## Origin

While regenerating `ui/src/lib/types.ts` for `feat_overnight_autopilot` Story 2.1, the refreshed `_SourceBreakdown` schema surfaced a required `click` bucket (added by `feat_ubi_judgments`, MVP2). The generated type's doc comment states:

> "the UI's source-breakdown card now renders all three buckets separately"

But [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) renders only `source_breakdown.llm` and `source_breakdown.human` (the `<dd data-testid="header-breakdown">` block, lines 61–67 at audit time) — the `click` bucket (UBI-derived judgments) is not displayed.

**Preflight verification (2026-06-02):**

- The wire field exists and carries three terms. Backend Pydantic shape `_SourceBreakdown` ([`backend/app/api/v1/schemas.py:1017-1029`](../../../../backend/app/api/v1/schemas.py)) declares `llm: int`, `human: int`, `click: int`. The detail serializer ([`backend/app/api/v1/judgments.py:148-152`](../../../../backend/app/api/v1/judgments.py)) populates all three from `repo.source_breakdown_for_list`, which returns `{"llm": …, "human": …, "click": …}` ([`backend/app/db/repo/judgment.py:282-307`](../../../../backend/app/db/repo/judgment.py)) with the invariant `llm + human + click == judgment_count`. So the data is on the wire today — this is a pure render gap.
- The generated TS mirror `components['schemas']['_SourceBreakdown']` ([`ui/src/lib/types.ts:3785-3792`](../../../../ui/src/lib/types.ts)) already has `click: number`, so `list.source_breakdown.click` is type-safe in the component with no `types:gen` regen needed.
- The component is presentational and consumed via `JudgmentListHeaderWithSyntheticChip` ([`ui/src/app/judgments/[id]/page.tsx:203-217`](../../../../ui/src/app/judgments/[id]/page.tsx)); no page-level plumbing change is required since `list.source_breakdown.click` is already passed in via the `list` prop.
- A glossary key for the click source already exists: `judgment.source.click` ([`ui/src/lib/glossary.ts:454`](../../../../ui/src/lib/glossary.ts), short: "Inferred from production click logs. Lower confidence than human or LLM ratings."). The fix can reuse it for any tooltip rather than minting a new key.
- Existing component vitest: [`ui/src/__tests__/components/judgments/judgment-list-header.test.tsx`](../../../../ui/src/__tests__/components/judgments/judgment-list-header.test.tsx) — currently only covers the FR-7 synthetic-data chip (3 cases), with `source_breakdown: { llm: 10, human: 2, click: 0 }` on the base fixture. It does NOT assert the breakdown render, which is why the gap shipped silently.

## Problem

A judgment list generated from UBI (or hybrid UBI+LLM) carries non-zero `source_breakdown.click`, but the header's source-breakdown card silently drops it. Operators reviewing a UBI list see only the LLM/human split and can't tell how many judgments came from real click behavior — which is the entire value proposition of the UBI path.

## Proposed capability

Render the `click` bucket in the source-breakdown card alongside `llm` and `human`, with an appropriate label and the existing per-bucket styling. Verify the doc-comment claim ("renders all three buckets separately") becomes true.

### Locked decisions (preflight 2026-06-02)

The idea left the label and layout shape implicit. Locking both so the spec can act without re-litigating:

- **D-1 (locked): Three-term inline render in the existing `header-breakdown` cell.** Keep the single `<dd data-testid="header-breakdown">` cell and render `llm / human / click` as a three-term slash-joined string (e.g. `10 / 2 / 5`), updating the `<dt>` label to `LLM / Human / Clicks`. Rationale: minimal diff, preserves the existing `data-testid` so the `judgments.spec.ts` `header-count` neighbor and any snapshot stays stable; matches the existing two-term pattern. Alternative considered — a separate fourth grid `<div>` for clicks — rejected as more layout churn for no operator benefit (the grid is already `md:grid-cols-4` and full with count/breakdown/κ/weighted-κ).
- **D-2 (locked): Reuse the existing `judgment.source.click` glossary key for the tooltip; do NOT mint a new key.** The label term "Clicks" carries the existing glossary short text via the established info-tooltip pattern if a tooltip is added; spec may choose to add the tooltip or keep the label bare (low-risk either way since the label is self-describing). Default: add a single info tooltip on the breakdown label keyed to `judgment.source.click`.
- **D-3 (locked): Label wire-neutrality.** The `click` term is a **display-only integer count**, not a `<select>`/filter wire value sent to the backend, so the §7.4 enumerated-value-contract discipline does not gate this change. The source-of-truth for the three terms is the backend `_SourceBreakdown` shape, not an allowlist. A source-of-truth comment pointing at `backend/app/api/v1/schemas.py _SourceBreakdown` SHOULD be added above the breakdown render so future edits track the wire shape.

## Scope signals

- **Backend:** none (the field already exists on the wire — verified at `judgments.py:148-152` + `judgment.py:282-307`).
- **Frontend:** small — one component (`judgment-list-header.tsx`) + its vitest, plus a focused real-backend E2E assertion (extend the `ubi-source-filter.spec.ts` pattern, which already produces a list with non-zero `click`, OR add a header-breakdown assertion to `judgments.spec.ts`).
- **Migration / config:** none.
- **Audit events:** N/A — read-only render change, no state mutation.

### Test layers required (per CLAUDE.md frontend convention)

A frontend feature is not complete until every layer it touches is covered:

- **vitest (component):** extend `judgment-list-header.test.tsx` to assert the `header-breakdown` cell renders all three terms for a fixture with non-zero `click` (e.g. `{ llm: 10, human: 2, click: 5 }`), and that the label reads `LLM / Human / Clicks`.
- **E2E (Playwright, real backend, no `page.route()` mocking):** assert the header surfaces the click count on a real UBI-generated list. The `ubi-source-filter.spec.ts` flow already seeds UBI via `seedUbiForQuerySet` → generates a pure-CTR list → navigates to `/judgments/[id]`; add a `header-breakdown` assertion there (or a sibling spec) so the browser-visible render is exercised end-to-end.

## Why deferred (not fixed inline)

Different feature surface (judgments UI) than the overnight-autopilot chain panel; out of scope for that PR. Bounded and cheap, but belongs with the judgments-header component, not the chain feature.

## Relationship to other work

- Originating feature: `feat_ubi_judgments` (shipped 2026-05-29) — added the `click` bucket to `_SourceBreakdown` and the doc comment that this component doesn't yet honor.
- Sibling deferred UBI cleanup (all under `02_mvp2/`, confirmed present): `chore_ubi_hybrid_template_render`, `chore_ubi_reader_search_after_pagination`, `bug_relyloop_spec_ubi_section_drift`, `feat_ubi_llm_study_comparison`. None overlap the judgments-header surface — coordinate-only, no ordering dependency.
- **Tangential doc-rot noticed during preflight (NOT in scope here, different file):** the module-level docstring at [`backend/app/db/repo/judgment.py:24-27`](../../../../backend/app/db/repo/judgment.py) still says "Source breakdown folds `click` into `human` … no `click` rows exist in MVP1" — stale since `feat_ubi_judgments` FR-10 (the function body at line 286+ and its own docstring at 286-294 already describe the correct three-term behavior). This is a one-line backend docstring fix in a separate subsystem from this frontend bug; flagged so a future backend-touching PR can sweep it. It does not affect this feature's render fix.
