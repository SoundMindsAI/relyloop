# Studies-list convergence visibility + demo data that shows real optimization

**Date:** 2026-06-02
**Status:** Idea — user request during a demo-quality review session (2026-06-02). Scoping forks already resolved by the user (see Decisions).
**Priority:** P1
**Origin:** User feedback on `http://127.0.0.1:3000/studies` — "it would be great if I could see the number of trials for each study plus an indicator about convergence if the number of trials was too low to tell," plus a demo-quality concern about studies that hit the metric ceiling (≥0.99) showing the `Pinned at metric ceiling … not a real optimizer win` badge. "I want to make sure that our demo provides real value."
**Depends on:** None new. Builds on the shipped `feat_study_convergence_indicator` (PR #352) classifier and the demo-seeding scenarios.

## Problem

Two coupled gaps, sharing one root cause.

**A — The `/studies` list hides the two signals an operator most needs to judge a study at a glance.** The list ([`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx) + [`studies-table.column-config.tsx`](../../../../ui/src/components/studies/studies-table.column-config.tsx)) shows name, cluster, status, best_metric (with a ceiling badge), created, completed — but **not** the completed-trial count and **not** the convergence verdict. Both already exist on the study DETAIL response (`StudyDetail.trials_summary`, `StudyDetail.convergence` at [`backend/app/api/v1/schemas.py:829`](../../../../backend/app/api/v1/schemas.py)) and the `<ConvergencePanel>`, but the LIST response (`StudySummary`, [`schemas.py:881`](../../../../backend/app/api/v1/schemas.py)) omits them. So an operator scanning the list can't tell "is this 0.99 a real win or just too few trials to trust?" without opening each study.

**B — The demo studies hit `best_metric = 1.0` because the seed data is too sparse for real optimization.** The five small scenarios in [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) (mirrored in [`backend/app/services/demo_seeding.py`](../../../../backend/app/services/demo_seeding.py)) each index ~5 docs with **1–2 judgments per query**, mostly single "perfect 3" ratings, at **`max_trials = 12`**. With that little signal, any config that ranks the one graded doc first scores ~1.0 — the optimizer trivially maxes the metric, the UI correctly shows the honest `study.best_metric.saturated` ceiling badge ([`studies-table.column-config.tsx:32`](../../../../ui/src/components/studies/studies-table.column-config.tsx), threshold 0.99), and the convergence classifier returns `too_few_trials` for everything under its 50-trial warmup floor ([`backend/app/domain/study/convergence.py:222`](../../../../backend/app/domain/study/convergence.py)). The demo therefore showcases the *degenerate* case the tool warns about, not a real optimizer win.

The two are coupled: adding the convergence indicator (A) is only compelling in the demo if the demo studies (B) actually produce non-trivial, improving metrics and enough trials for the verdict to read `converged` / `still_improving` rather than a uniform `too_few_trials`.

## Decisions (locked by the user, 2026-06-02)

- **D-1 (demo data):** **Enrich judgments + bump trials.** Rework the small scenarios with more candidate docs + denser GRADED judgments (ratings spanning 3/2/1/0 across several docs per query) so the baseline metric lands believably mid-range with headroom, and raise `max_trials` toward the convergence warmup floor so the indicator can read `converged`. (Chosen over judgments-only, rich-scenario-as-flagship, and leave-as-is.)
- **D-2 (list UI):** **Trial count + full verdict badge.** Show the completed-trial count plus a convergence badge (`converged` / `still improving` / `too few to tell`), reusing the shipped detail-page classifier per study. (Chosen over count + 'too few' flag only, and count only.)
- **D-3 (badges stay):** Keep the honest `metric ceiling` and `too_few_trials` indicators — they are truthful, educational signals for genuinely sparse cases. This work makes the *demo* avoid the degenerate case; it does NOT hide the signal when data really is sparse.

## Proposed capabilities

### A. Studies-list trial count + convergence badge

- Extend the list response item (`StudySummary`) with the completed-trial count and the convergence verdict (reuse `classify_convergence`; do NOT fork the logic).
- The list builder computes per-study trial count + verdict. At single-tenant demo scale the per-row trial fetch + classify is acceptable; the spec should still note the N+1 shape and pick an efficient query (e.g. a grouped `COUNT` + a bounded trial fetch only for studies with ≥ `CONVERGENCE_FLAT_MIN_COMPLETE` complete trials). The `too_few_trials` state is derivable from the count alone (`< STUDIES_TPE_WARMUP_FLOOR`, 50) without building the curve — use that to skip the expensive path for low-trial studies.
- Frontend: add a "Trials" column (count) and a convergence badge column to [`studies-table.column-config.tsx`](../../../../ui/src/components/studies/studies-table.column-config.tsx). Badge variants map to the three verdicts; tooltip/glossary copy reused from the existing convergence glossary entries. Wire-value discipline: the verdict literals must match the backend `ConvergenceVerdict` Literal (`converged` / `still_improving` / `too_few_trials`).
- Cross-reference the existing ceiling badge so a study that is BOTH ceiling-pinned AND too-few-trials reads coherently (the convergence badge explains *why* the ceiling isn't trustworthy).

### B. Demo seeding enrichment for real optimization value

- Per small scenario: expand the candidate doc set per index and author **graded** judgment distributions (multiple docs per query across ratings 3/2/1/0) sized so the BASELINE template config scores a believable mid-range (target roughly ~0.5–0.7, spec to pin exact targets) with clear headroom for the optimizer to find lift.
- Raise `max_trials` for the small scenarios (currently 12) toward/above the convergence warmup floor (50) so the verdict can read `converged` / `still_improving` — balanced against demo seed wall-clock (each extra trial × LLM-study + UBI-study × 5 scenarios adds time; the spec must weigh the seed-runtime budget, cf. the smoke reseed-runtime debt).
- **Parity is mandatory:** the CLI path ([`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)) and the service/home-button reseed path ([`backend/app/services/demo_seeding.py`](../../../../backend/app/services/demo_seeding.py)) must seed identical data; there's an existing parity CI guard (`scripts/ci/verify_demo_slug_parity.sh`) — extend its coverage if judgment/doc counts become part of the contract.
- Keep the rich ESCI scenario as-is (it already demonstrates real lift at 1000 docs / 40 trials).
- Acceptance: after reseed, the enriched scenarios' studies show `best_metric` below the 0.99 ceiling with a visible baseline→best improvement, and the convergence verdict reads meaningfully (not a uniform `too_few_trials`).

## Scope signals

- **Backend:** `StudySummary` schema (+2 fields); the `GET /api/v1/studies` list builder ([`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py)) — add trial-count + convergence per item, efficiently; reuse `classify_convergence`. No new domain logic (reuse). Contract test for the new list fields.
- **Frontend:** new columns in `studies-table.column-config.tsx`; glossary/tooltip reuse; column-discipline source-of-truth comment + the data-table lint guard (`sourceOfTruth`) for the verdict enum. Vitest + a studies-list E2E assertion.
- **Demo seeding:** new graded judgment maps + doc sets in BOTH seed paths; raised `max_trials`; parity guard update. Integration test that an enriched scenario's seeded study lands below ceiling with lift (or a domain-level test on the judgment density).
- **Migration:** none expected (no schema change — trial count + convergence are computed, not stored).
- **Config:** possibly a demo `max_trials` constant bump; no new env var.
- **Audit events:** N/A (pre-MVP3).

## Why now / priority

Direct user request tied to demo credibility ("provide real value"). P1 — the demo is the primary evaluation surface and currently leads with studies the tool itself flags as non-wins. Independent of any in-flight work.

## Relationship to other work

- Reuses `feat_study_convergence_indicator` (PR #352) — the classifier, constants, runbook ([`docs/03_runbooks/convergence-verdict.md`](../../../../docs/03_runbooks/convergence-verdict.md)).
- Touches the same demo-seed paths as the recently-shipped `bug/cli-seed-ubi-missing-engine-type` (PR #419) and the engine-tolerance work (`infra_solr_ci_readiness`).
- Seed-runtime increase interacts with the deferred [`infra_smoke_reseed_runtime_budget`](../infra_smoke_reseed_runtime_budget/idea.md) (bumping trials makes the smoke reseed slower — the spec should account for it).
- Could be split into two phases at spec time (A = list UI/API, B = demo enrichment) if reviewability calls for it; they're coupled by the demo narrative but independently shippable.
