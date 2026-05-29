# feat_demo_ubi_study_comparison — synthetic UBI in the demo + UBI-vs-LLM study comparison

**Date:** 2026-05-29
**Status:** Idea — operator-requested during `feat_ubi_judgments` PR #317 review
**Origin:** Operator asked whether the home-page demo reseed includes UBI data and whether you can run a UBI study + an LLM study on the same queries/data and compare. Today: no — the reseed writes zero UBI (RelyLoop never writes UBI by design; the demo cluster comes up at rung_0).
**Depends on:** `feat_ubi_judgments` (shipped, PR #317)
**Priority:** P1 (highest-leverage demo of the just-shipped UBI feature)

## Problem

The home-page "force refresh demo data" reseed
(`backend/app/services/demo_seeding.py` → `run_demo_reseed`) seeds
product docs + clusters + query sets + LLM judgment lists + studies, but
**no UBI data**. RelyLoop's read-only posture (Absolute Rule #4, spec
"no cluster writes ever") means nothing in the product writes
`ubi_queries`/`ubi_events` — those are operator-application-emitted. So a
demo operator opening the generate-judgments dialog sees the rung_0
on-ramp nudge and can only run the LLM path. There's no way to
experience UBI judgments, let alone compare a UBI-derived study against
an LLM-derived one.

## Proposed capabilities

1. **Synthetic UBI generator (demo/seed-only, write-side).** Given the
   demo query set + the seeded product docs + a known relevance signal,
   fabricate plausible `ubi_queries` + `ubi_events`:
   - impressions distributed across ranks with a built-in **position
     bias** (so the Wang-Bendersky correction in the CTR converter
     actually changes the ratings vs raw CTR — makes the prior
     calibration story demonstrable),
   - clicks/dwell correlated with the demo's ground-truth relevance so
     the derived UBI judgments are meaningful (not random),
   - enough volume to land the demo cluster at **rung_3** (dense) for
     some query sets and **rung_1** (sparse, triggers the hybrid nudge)
     for others — so all the on-ramp UX surfaces are reachable in the demo.
   - written directly to the demo OpenSearch container via the HTTP API
     (bypassing the read-only `SearchAdapter` — same install-side write
     posture as the deferred `seed_ubi.ts` E2E helper in
     `chore_ubi_e2e_suite`; the generator is NOT part of the product's
     runtime path).
2. **Reseed wiring.** Extend `run_demo_reseed` to (a) write the synthetic
   UBI indices and (b) seed BOTH an LLM judgment list AND a UBI judgment
   list on the **same** query set, so two studies can run head-to-head.
3. **Comparison UX (optional, second phase).** A side-by-side of the two
   studies' digests / best configs / metric deltas — "what changed when
   we grounded judgments in real behavior instead of an LLM's reading of
   the rubric." Could start as a manual "open both study detail pages"
   flow and graduate to a dedicated comparison view.

## Honesty caveat (product decision needed)

This is **synthetic** clickstream, not real-world data. The generator
fabricates clicks/dwell that correlate with the demo's known relevance +
adds position bias. It demonstrates the *mechanics + value shape* of UBI
honestly, but the UI/tutorial copy must not imply the demo UBI is real
user behavior. Decide the framing ("simulated user signal for
demonstration") at spec time.

## Scope signals

- Backend: new synthetic-UBI generator module (seed-only) + `run_demo_reseed`
  wiring + a second judgment-list seed on the shared query set. Net-new,
  likely 250–400 LOC.
- Frontend: minimal for phase 1 (the existing dialog + value-delta card
  already render UBI); a comparison view is phase 2.
- Migration: none.
- Config: none (uses the existing demo OpenSearch container).
- Test infra: shares the synthetic-UBI shape with `chore_ubi_e2e_suite`'s
  `seed_ubi.ts` — consider extracting one canonical generator both consume.

## Relationship to existing follow-ups

- `chore_ubi_e2e_suite` — the E2E `seed_ubi.ts` helper writes the same
  index shapes; the generator here could be the canonical source both use.
- `chore_ubi_hybrid_template_render` — independent (hybrid LLM-fill
  retrieval path); not blocking.
