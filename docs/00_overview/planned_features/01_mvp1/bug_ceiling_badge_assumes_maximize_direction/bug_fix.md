# Bug fix — bug_ceiling_badge_assumes_maximize_direction

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/ceiling-badge-assumes-maximize-direction`
**Type:** bug fix — medium (cross-layer: backend schema + frontend gate)
**Date:** 2026-05-29

## Problem

The "Ceiling" badge on the studies list ([`studies-table.column-config.tsx`](../../../../ui/src/components/studies/studies-table.column-config.tsx)) flags any study with `best_metric >= 0.99`. That's correct for **maximize** objectives (NDCG/MAP/MRR/Precision/Recall pinned at their upper bound) but **wrong for minimize** objectives — there a 0.99 is a *bad* score, not a ceiling. The badge would tell the operator "pinned at metric ceiling, optimizer found nothing special" when the truth is the exact opposite.

## Preflight finding — the bug went from latent to live

The idea (2026-05-27) deferred on the premise that **no minimize study could be created** ("the objective metric allowlist is all higher-is-better; no minimize study can be created today via API or UI"). That premise is now **stale**: `feat_study_baseline_trial` added `direction` to the objective spec — [`ObjectiveSpec.direction: ObjectiveDirection = "maximize"`](../../../../backend/app/api/v1/schemas.py#L579) where `ObjectiveDirection = Literal["maximize", "minimize"]`. A `direction=minimize` study **is creatable via the API today**, so the badge can actively mislabel one. The bug is no longer prophylactic.

## Reproduction

```bash
# Frontend (the user-visible mislabel):
cd ui && pnpm test -- --run src/__tests__/components/studies/studies-table-ceiling-badge.test.tsx
# Backend (direction must flow onto StudySummary):
pytest backend/tests/unit/api/test_study_summary_direction.py -v
```

On `main`, the FE test "does NOT show the Ceiling badge for a minimize study at 0.99" fails — the badge renders because the gate is `best_metric >= 0.99` with no direction check. On this branch it passes.

## Root cause

- Owning layer: **frontend** (the false label) + **backend** (the list shape didn't expose the data needed to gate it).
- Origin: [studies-table.column-config.tsx:76](../../../../ui/src/components/studies/studies-table.column-config.tsx#L76) — `const saturated = m >= METRIC_CEILING_THRESHOLD` with no direction awareness.
- Data gap: [`StudySummary`](../../../../backend/app/api/v1/schemas.py#L755) (list-view shape) omitted `direction`, so the gate couldn't be written client-side without a TypeScript error (the idea's reason #2).

## Fix design (locked decisions)

1. **Add `direction` to `StudySummary`** (the idea's smallest-fix option). `direction: ObjectiveDirection = "maximize"` on the Pydantic model; `_summary()` reads `row.objective.get("direction", "maximize")`. Cites: idea §"Proposed capabilities" option 1.
2. **Default to `maximize`** for objective JSON that predates the `direction` key (pre-`feat_study_baseline_trial` rows). Backward-compat; preserves the historical implicit behavior. Cites: CLAUDE.md data-model conventions (additive, nullable-safe).
3. **Gate the badge, don't invert it.** The badge shows only when `direction === 'maximize' && best_metric >= 0.99`. A minimize study shows *no* badge (correct — we make no false claim) rather than a new "Floor" badge. Inverting/adding a floor badge needs floor-threshold + glossary-copy decisions that are a UX enhancement, not part of fixing the mislabel. Cites: CLAUDE.md Bug Fix Protocol step 3 ("minimal change that addresses the root cause; don't add features").
4. **Hand-edit `types.ts`** rather than regen. `ui/scripts/gen-types.mjs` needs the backend serving the new schema at `localhost:8000`; CI treats committed `types.ts` as source of truth. The single added field is written to match openapi-typescript's style for a defaulted enum field (matches the existing `ObjectiveSpec.direction` rendering).

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit (FE) | `ui/src/__tests__/components/studies/studies-table-ceiling-badge.test.tsx` | maximize@0.99 → badge; **minimize@0.99 → NO badge**; maximize@0.5 → no badge; null → em dash |
| unit (BE) | `backend/tests/unit/api/test_study_summary_direction.py` | `_summary` surfaces minimize/maximize from objective; defaults maximize when key absent |

## Rollout

None — code-only. Additive backend field (defaulted, backward-compatible); additive frontend gate. No migration (objective is existing JSONB; `direction` already written there by study creation). No env var, no operator action.

## Tangential observations

None — the trace was contained to the studies-list shape + the one badge cell. The minimize "Floor" badge is a possible future enhancement, not filed as a separate idea (it's a UX-copy decision, capturable later if a minimize-heavy workflow emerges).
