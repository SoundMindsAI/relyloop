# Bug fix — `bug_dashboard_reset_disclosure_gating_too_strict`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/stuck-stack-self-rescue-bundle`
**Type:** bug fix — medium (bundled with sibling [`bug_seed_demo_if_empty_counts_soft_deleted`](../bug_seed_demo_if_empty_counts_soft_deleted/idea.md) per the "Relationship to other work" section of both ideas; together they fully restore the in-product recovery path)
**Date:** 2026-05-26

## Problem

[`ui/src/components/dashboard/start-here-checklist.tsx:150`](../../../../ui/src/components/dashboard/start-here-checklist.tsx#L150) gated the "Reset to demo state" disclosure on `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies` — a 3-way AND modeling "truly pristine first-run." But the realistic stuck state — **data orphaned without any live clusters** — is exactly when the operator needs the rescue affordance most, and the strict predicate hid it. Reproduced earlier this session: operator's `/` showed Step 1 (Register cluster) as NOT done, Steps 2 + 3 as Done, and no disclosure anywhere.

Without live clusters, every cluster-scoped operation (run study, generate judgments, view studies tied to clusters) fails. The orphan studies + query_sets are unusable until the operator either registers a cluster manually OR resets to demo state. The disclosure was the documented self-rescue path; hiding it forced CLI knowledge of `make seed-demo FORCE=1`.

## Reproduction

Pre-fix vitest test at [`ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx`](../../../../ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx) asserted the wrong behavior (AC-8 — "hides the disclosure when hasQuerySetsWithJudgments is true" + "hides when hasStudies is true"). The fix flips both to "renders the disclosure when hasClusters=false regardless of orphan data."

Run the updated tests:

```bash
cd ui && pnpm vitest run src/__tests__/components/dashboard/start-here-checklist.test.tsx
# Pre-fix: 4 PASS + 2 (now-flipped) FAIL.
# Post-fix: 6 PASS.
```

## Root cause

- **Owning layer:** UI component (`StartHereChecklist`).
- **Origin:** [`ui/src/components/dashboard/start-here-checklist.tsx:150`](../../../../ui/src/components/dashboard/start-here-checklist.tsx#L150) — predicate `!hasClusters && !hasQuerySetsWithJudgments && !hasStudies` only fires for truly-pristine stacks.
- **Why the predicate was too strict:** the original spec (`feat_home_demo_reseed_endpoint` PR #228 §11) modeled "first-run experience" as the disclosure's only audience. The "stuck-after-data" state wasn't in scope when the spec was written. This is a spec drift — the implementation matches the spec literally, but the spec's intent (per its FR-1 / AC-7 language about "operator who needs to reset") is broader.

## Fix design (locked decisions)

1. **Tighten predicate to `!hasClusters` only.** Cites: idea.md "Proposed fix" (locked rationale). `hasClusters` is the load-bearing signal — without live clusters, every other piece of data is unusable, so the disclosure should always be available. The other two signals (`hasQuerySetsWithJudgments`, `hasStudies`) are downstream of having a cluster; gating on them is incidental complexity.
2. **Keep `hasClusters=true` as the disclosure's "hide" trigger.** Cites: an operator with a live cluster has a working stack and might lose work by accidentally clicking "Reset" — preserving that single guardrail prevents click-by-accident data loss. The remaining guard via `<ResetDemoStateButton>`'s confirm dialog is sufficient defense once the operator deliberately expands the disclosure.
3. **Inline-comment the predicate change** with a pointer to this bug folder. Cites: CLAUDE.md "Only add [a comment] when the WHY is non-obvious" — the predicate's history would otherwise be invisible to a future reader who'd just see the trivial `!hasClusters` and wonder why the redundant `&& !hasQuerySetsWithJudgments && !hasStudies` was removed.
4. **Test coverage**: flip the 2 AC-8 tests that asserted the old behavior; add a 3rd positive test for the exact stuck state (no live clusters + orphan data on BOTH other signals) that surfaced the bug. Cites: regression rigor — pin the new contract at both single-orphan and double-orphan states.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit (vitest) | [`ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx`](../../../../ui/src/__tests__/components/dashboard/start-here-checklist.test.tsx) | Existing AC-7 (all-three-false → disclosure renders) AND existing AC-8 hasClusters=true case kept. Two old AC-8 cases (hides when only hasQuerySetsWithJudgments / hasStudies is true) replaced with their inverses. New test: disclosure renders when hasClusters=false AND both other signals true (the exact 2026-05-26 stuck-state repro). |

## Rollout

Frontend-only change. Forward-only. Operators who reload `/` after this ships will see the disclosure whenever they're missing live clusters — no restart, no migration, no operator action. Sibling fix at [`bug_seed_demo_if_empty_counts_soft_deleted`](../bug_seed_demo_if_empty_counts_soft_deleted/idea.md) (shipping in the same PR) tightens the auto-seed gate so fresh `make up` correctly re-seeds when only soft-deleted clusters exist.

## Tangential observations

- [`bug_seed_demo_if_empty_counts_soft_deleted`](../bug_seed_demo_if_empty_counts_soft_deleted/idea.md) — sibling fix shipping in the same PR as the first commit. Fixing both restores recovery at both layers (auto-seed path + in-product rescue path).
