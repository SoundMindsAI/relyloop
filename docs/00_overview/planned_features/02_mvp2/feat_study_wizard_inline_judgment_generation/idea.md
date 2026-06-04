# Study wizard — inline judgment generation when a query set has none

**Date:** 2026-06-04
**Status:** Idea — user-reported workflow blocker during demo/dev usage
**Priority:** P1
**Origin:** User report (2026-06-04): "I see a lot of Query Sets that do not have an associated Judgment List… Because they don't have a Judgment List, I am being blocked from creating a Study using the wizard." Root-cause investigation confirmed the real demo query sets all have judgment lists; the blocked ones were test-run leftovers — but the wizard's dead-end behavior is the durable gap regardless of where the orphan query set came from.
**Depends on:** None (reuses the existing `<GenerateJudgmentsDialog>` and `useJudgmentLists`).

## Problem

In the Create-Study wizard, Step 1 requires both a query set AND a judgment list (`ui/src/components/studies/create-study-modal.tsx:672` — `Boolean(values.query_set_id && values.judgment_list_id)`), and the backend likewise requires `judgment_list_id` (`backend/app/api/v1/schemas.py:875`). The judgment-list dropdown is filtered by `query_set_id` + `cluster_id` + `target` (`create-study-modal.tsx:386-391` via `useJudgmentLists`). When the selected query set has **no** matching judgment list, the dropdown is empty and the wizard's "Next" is disabled — the only escape today is an empty-state link to `/judgments` (`create-study-modal.tsx:971-989`), which forces the operator to abandon the half-filled wizard, generate judgments elsewhere, and start over. This is a hard dead-end for any query set without judgments (test leftovers, freshly-imported query sets, or a query set whose judgments were generated against a different cluster/target).

## Proposed capabilities

### Inline "Generate judgments" affordance in the wizard

- When the judgment-list dropdown is empty for the chosen (query set, cluster, target), replace the bare "go to /judgments" link with a prominent inline **"Generate judgments for this query set"** button.
- Clicking it opens the existing `<GenerateJudgmentsDialog>` (`ui/src/components/query-sets/generate-judgments-dialog.tsx`, props `clusterId` / `querySetId` / `open` / `onOpenChange`) **without leaving the wizard** — pre-targeted at the already-selected cluster + query set.
- On successful generation dispatch, the dialog closes and the wizard's `useJudgmentLists` query invalidates/refetches so the new (or generating) judgment list appears in the dropdown; the operator selects it and continues. Keep the `/judgments` deep-link as a secondary "advanced" escape.

### Honest in-progress state

- Judgment generation is async (LLM / UBI worker). The wizard should reflect a freshly-dispatched list that is still `generating` (not yet `complete`) — either show it in the dropdown with a status hint, or surface a "judgments are generating…" affordance — rather than appearing to still be empty. Decide during spec whether a study may be created against a not-yet-complete judgment list or must wait for `complete` (the backend's current required-FK + status semantics govern this).

## Scope signals

- **Backend:** none expected — reuses `POST /api/v1/judgments/generate` (+ `/generate-from-ubi`) and `GET /api/v1/judgment-lists`. Confirm during spec whether study creation tolerates a `generating` judgment list or requires `complete`.
- **Frontend:** the change is localized to `create-study-modal.tsx` (empty-state block ~971-989) + mounting `<GenerateJudgmentsDialog>` inside the wizard with refetch-on-success wiring. Reuses existing components/hooks — no new primitives.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — no new state-mutating server surface (generation already emits its own events).

## Why not yet prioritized

It is being prioritized now (P1) — filed as a feature so it ships through the normal spec → plan → impl ceremony rather than as an ad-hoc patch, since it touches a core operator flow (study creation) and has a real product decision embedded (whether to allow study creation against an in-flight judgment list).

## Relationship to other work

Reuses `<GenerateJudgmentsDialog>` (`feat_llm_judgments` + `feat_ubi_judgments`). Complementary to `feat_studies_ui` (the wizard's owner). Does not change the backend study-creation contract.
