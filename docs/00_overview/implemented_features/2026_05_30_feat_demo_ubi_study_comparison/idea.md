# feat_demo_ubi_study_comparison — synthetic UBI in the demo + UBI-vs-LLM study comparison

**Date:** 2026-05-29 (preflight-audited 2026-05-29)
**Status:** Idea — operator-requested during `feat_ubi_judgments` PR #317 review
**Origin:** Operator asked whether the home-page demo reseed includes UBI data and whether you can run a UBI study + an LLM study on the same queries/data and compare. Today: no — the reseed writes zero UBI (RelyLoop never writes UBI by design; the demo clusters come up at rung_0).
**Depends on:** [`feat_ubi_judgments`](../../implemented_features/2026_05_29_feat_ubi_judgments/) (shipped, PR #317, 2026-05-29)
**Priority:** P1 (highest-leverage demo of the just-shipped UBI feature)

## Problem

The home-page "force refresh demo data" reseed
([`backend/app/services/demo_seeding.py:1065`](../../../../backend/app/services/demo_seeding.py#L1065) →
`reseed_demo_state`, dispatched by the Arq worker
[`backend/workers/demo_reseed.py:59`](../../../../backend/workers/demo_reseed.py#L59) →
`run_demo_reseed`) seeds product docs + clusters + query sets + LLM
judgment lists + studies across four small scenarios (3 Elasticsearch:
`acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod` + 1
OpenSearch: `news-search-staging`) plus a 5th rich ESCI scenario (ES,
1000 docs + LLM judgments + 15-trial study). But **zero UBI data is
written**. RelyLoop's runtime posture is read-only on UBI (Absolute Rule
#4 — adapter Protocol is the only engine surface at runtime), so nothing
in the product writes `ubi_queries`/`ubi_events`; those are
operator-application-emitted at real sites. The demo reseed writes to
the ES container directly via the existing
`engine_client: httpx.AsyncClient` pattern that
[`run_demo_reseed_cleanup`](../../../../backend/app/services/demo_seeding.py#L459)
already uses for index deletes — that's the precedent for any
seed-side engine write, including this feature's synthetic UBI data.

Result: a demo operator opening the generate-judgments dialog sees the
rung_0 on-ramp nudge on every cluster and can only run the LLM path.
There's no way to experience UBI judgments in the demo, let alone
compare a UBI-derived study against an LLM-derived one on the same
data.

## Proposed capabilities

### Phase 1 — synthetic UBI + dual judgment lists

1. **Synthetic UBI generator (demo/seed-only, write-side).** Given the
   demo query set + the seeded product docs + a known relevance signal,
   fabricate plausible `ubi_queries` + `ubi_events`:
   - impressions distributed across ranks with a built-in **position
     bias** (so the Wang-Bendersky position-bias correction in
     [`backend/app/domain/ubi/converter.py:203`](../../../../backend/app/domain/ubi/converter.py#L203)
     `CtrThresholdConverter` actually changes the ratings vs raw CTR —
     makes the prior calibration story demonstrable);
   - clicks/dwell correlated with the demo's ground-truth relevance so
     the derived UBI judgments are meaningful (not random);
   - enough volume to land target scenarios at **rung_3** (dense) and
     **rung_1** (sparse, triggers the hybrid nudge) so the rung badge,
     on-ramp nudge, sparse-data recovery card, and method-picker
     defaults are all browser-visible in the demo;
   - written directly to the demo Elasticsearch container (port 9200)
     and OpenSearch container (port 9201) via HTTP, using the existing
     `engine_client: httpx.AsyncClient` already threaded through
     `reseed_demo_state` — same posture as
     `run_demo_reseed_cleanup`'s index deletes. **Not** a runtime
     adapter call (the adapter stays read-only at runtime per Absolute
     Rule #4); this is seed-only install-side write code.
   - **Shape canonicalization.** The shipped Playwright helper
     [`ui/tests/e2e/helpers/seed_ubi.ts`](../../../../ui/tests/e2e/helpers/seed_ubi.ts)
     already writes the same `ubi_queries` + `ubi_events` index
     mappings (keyword/text/date/integer/float per field) the
     `UbiReader` reads. The Python synthetic generator MUST match those
     mappings byte-for-byte; extracting a single canonical mapping
     definition consumed by both (TS via `JSON.parse`, Python via
     module-level dict) is the recommended D-1 lock so the two sides
     can't drift.
2. **Reseed wiring.** Extend
   [`reseed_demo_state`](../../../../backend/app/services/demo_seeding.py#L1065)
   to (a) write the synthetic UBI indices into the appropriate engine
   container per scenario (see D-2 for which scenarios) and (b) for
   every scenario that gets UBI data, seed BOTH an LLM judgment list
   AND a UBI judgment list on the **same** query set — two judgment
   lists, one query set. Each gets its own real Optuna study against
   the same data + same template, so the digests / best configs /
   metric deltas compare apples-to-apples.
3. **Value-delta surfacing.** The existing value-delta card on the
   judgment-list detail page
   ([`ui/src/app/judgments/[id]/page.tsx`](../../../../ui/src/app/judgments/%5Bid%5D/page.tsx))
   already detects a prior LLM list on the same `query_set_id` and
   renders the comparison. With dual lists seeded, the card lights up
   for free — no frontend change required to demonstrate the
   per-judgment comparison.

### Phase 2 — dedicated UBI-vs-LLM study comparison view (deferred)

A side-by-side comparison view of the two **studies** (not just
judgments): digest narrative diff, best-trial param diff,
best-metric delta, convergence curve overlay. "What changed when we
grounded judgments in real behavior instead of an LLM's reading of the
rubric." Phase 1 ships everything needed to *manually* open both study
detail pages and read across; Phase 2 wraps that in a single page.
Phase 2 spawns its own `phase2_idea.md` at `/impl-execute` finalization
if Phase 1 ships clean and the operator still wants it.

## Honesty caveat (open question — UX/copy decision for /spec-gen)

This is **synthetic** clickstream, not real-world data. The generator
fabricates clicks/dwell that correlate with the demo's known relevance
+ adds position bias. It demonstrates the *mechanics + value shape* of
UBI honestly, but the UI/tutorial copy must not imply the demo UBI is
real user behavior. Surfaces that need the "simulated for
demonstration" framing:

- The generate-judgments dialog's method-picker UBI options
  ([`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx)),
  but **only on the demo clusters** (not on operator-registered
  clusters with real UBI traffic).
- The judgment-list detail page header for UBI lists seeded by the
  demo reseed.
- The home-page "force refresh demo data" banner (state-banner copy
  should mention that some lists are derived from synthetic clicks).
- The tutorial guide ([`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md)
  Step 11 UBI upgrade) if it grows a "compare two studies" section.

**Recommended default for /spec-gen:** gate the disclaimer on a
per-cluster `is_demo_synthetic_ubi` flag (or equivalent — could piggyback
on the existing `cluster.name`-pattern recognition already used by
demo-aware UI). Real operator clusters never see the disclaimer.
Keep open for spec-time UX call; do not invent a final string.

## Scope signals

- **Backend:** new synthetic-UBI generator module (seed-only) +
  `reseed_demo_state` wiring + a second judgment-list seed +
  second-study seed on the shared query set, per scenario. Net-new,
  ~300–500 LOC including the generator's correlation logic + position-bias
  injection.
- **Frontend:** **none** in Phase 1 — the existing dialog, on-ramp
  nudge, value-delta card, sparse-data card, and rung badge all render
  for free once the data is present. Phase 1 may add a small "synthetic
  data" disclaimer chip per the Honesty caveat (depends on the
  spec-time UX call).
- **Migration:** none.
- **Config:** none (uses the existing demo Elasticsearch and OpenSearch
  containers; both `engine_client` HTTP base URLs are already
  configured in `reseed_demo_state`'s startup).
- **Test infra:** shares the canonical `ubi_queries` + `ubi_events`
  index mappings already shipped in
  [`ui/tests/e2e/helpers/seed_ubi.ts`](../../../../ui/tests/e2e/helpers/seed_ubi.ts).
  D-1 below locks the mapping definitions to a single source of truth so
  the TS helper and the new Python generator can't drift.

## Decisions to lock for /spec-gen

### D-1 — Canonical UBI index mapping (locked)

Both the existing shipped `seed_ubi.ts` E2E helper and the new Python
synthetic generator write the same two indices (`ubi_queries`,
`ubi_events`). Phase 1 extracts a single canonical mapping definition
(YAML or JSON in `samples/ubi_index_mappings.json`) consumed by both —
TS via `JSON.parse(readFileSync(...))`, Python via `json.loads`. A
unit test pins the round-trip equality so future edits land in both
places.

### D-2 — Which demo scenarios get synthetic UBI (locked)

The reseed writes 5 scenarios across 2 engines. Phase 1 lights up
**three** so all UBI on-ramp UX surfaces are exercised:

- `acme-products-prod` (ES) → **rung_3** (dense). Demonstrates the
  "happy path": picker auto-defaults to `ctr_threshold`, value-delta
  card lights up vs the LLM list.
- `corp-docs-search` (ES) → **rung_1** (sparse). Demonstrates the
  on-ramp nudge + sparse-data card + hybrid-mode auto-default.
- `jobs-marketplace-prod` (ES) → **rung_2** (mid). Demonstrates the
  hybrid LLM-fill path and the value-delta on a mixed-source list.

The remaining two scenarios stay at **rung_0** (no UBI):

- `news-search-staging` (OS, port 9201) — kept rung_0 to demonstrate
  the **engine-neutral on-ramp nudge copy** on OpenSearch (the nudge
  text differs from ES per the shipped `ubi-onramp-nudge.tsx`).
- `acme-products-rich-prod` (rich ESCI scenario, ES) — kept LLM-only
  so the demo retains a "high-volume real Optuna study" comparison
  baseline; promoting the rich scenario to UBI is a Phase 2 extension
  if requested.

### D-3 — Per-scenario dual studies (locked)

For the three UBI-enabled scenarios (D-2), seed two studies per
scenario, each with `config.seed=42` for reproducibility: one grading
against the LLM list, one grading against the UBI list. Same query
set, same template, same Optuna config — only the judgment source
differs. This is what makes the per-study digest/best-config diff
meaningful.

### D-4 — Synthetic-data disclosure (open)

See "Honesty caveat" above. Recommended default exists; the exact
copy + surface placement is a /spec-gen UX call.

## Relationship to existing follow-ups

- [`chore_ubi_reader_search_after_pagination`](../chore_ubi_reader_search_after_pagination/idea.md)
  — independent today, but coordinate at spec-time: the synthetic
  generator's rung_3 scenario emits ~600+ events per scenario by
  design. If the spec lands generator volumes that approach the
  10000-row `ES_MAX_RESULT_WINDOW` clamp in `UbiReader`, that chore
  becomes blocking. Likely fine for Phase 1 (rung_3 cutoff is
  `5 × min_impressions_threshold`, well below 10k), but call out
  the bound explicitly in the spec's "scale signals" section.
- [`chore_ubi_hybrid_template_render`](../chore_ubi_hybrid_template_render/idea.md)
  — independent. The hybrid LLM-fill path in the rung_1 scenario uses
  the existing per-pair `get_document` callback (FR-2); no change.
