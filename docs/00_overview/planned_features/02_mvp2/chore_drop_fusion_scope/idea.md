# Drop Lucidworks Fusion from the engine roadmap

**Date:** 2026-05-27
**Status:** Idea — scope decision, paired with [`infra_adapter_solr`](../infra_adapter_solr/idea.md)
**Priority:** P1 — gates the umbrella spec rewrite and the MVP2 release-theme rename
**Origin:** Positioning reframe on 2026-05-27. Triggered by the competitive analysis vs OpenSearch Search Relevance Workbench (see [`docs/07_research/comparison.md`](../../../07_research/comparison.md)) which surfaced that the "engine-neutral" pitch is the strongest moat — but only if the engines RelyLoop supports are the three open-source engines (ES, OpenSearch, Solr) that the OSC/Haystack community treats as canonical. Fusion as a fourth engine adds vendor entanglement without strengthening the moat.
**Depends on:** None — this is a documentation decision. The Fusion adapter was never implemented (Fusion was MVP3 scope per the prior release matrix; only design references existed).

## Problem

The prior umbrella spec ([`docs/00_overview/relyloop-spec.md`](../../../relyloop-spec.md)) planned Lucidworks Fusion as the MVP3 engine target and Apache Solr as a v2+ "architectural reference, not v1 scope" addition. After the 2026-05-27 reframe, this ordering is reversed and compressed:

- **Solr is promoted to MVP2**, bundled with UBI judgments (see [`infra_adapter_solr`](../infra_adapter_solr/idea.md) + [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md)).
- **Fusion is dropped entirely** — this idea documents why.
- **Multi-Git provider abstraction (GitLab, Bitbucket) is moved to the backlog** — was previously bundled with Fusion in the prior MVP3 release.

The reasons are stack-ranked below from most to least decisive.

### 1. Fusion doesn't strengthen the engine-neutral moat

The competitive analysis vs OpenSearch SRW ([`docs/07_research/comparison.md`](../../../07_research/comparison.md)) identifies the defensible moat as "Bayesian/TPE optimization across the full query-time search space, on every major open-source engine, with a Git-PR apply path." SRW is OpenSearch-only by architecture; Elasticsearch has no SRW equivalent (deprecated Behavioral Analytics + Search Applications in 9.0); Solr's ecosystem (Quepid + Chorus + RRE) is mature for manual evaluation but has no auto-optimizer.

The three engines that complete the OSS sweep are ES + OpenSearch + Solr. Fusion is a commercial layer on top of Solr — supporting it doesn't extend the engine-neutral claim, it just adds a vendor-specific surface.

### 2. Fusion creates vendor entanglement

The original spec called out at §29 #12 ("Lucidworks eval license policy for engineers") that hands-on Fusion access requires a Lucidworks evaluation license, with three options ranging from a shared team license to per-engineer 30-day evals. Every contributor touching the adapter needs license logistics. The replay-cassette infrastructure for offline tests was a separate maintenance burden (recording cassettes, refreshing them on Fusion version upgrades, owning the `fusion-mock` service).

None of this overhead applies to Solr — Apache 2.0 image runs locally in Compose with no licensing.

### 3. Fusion's audience overlap with the Quepid/Chorus community is smaller than Solr's

The natural early-adopter community for RelyLoop is the OSC + Sease + Querqy + Haystack ecosystem — the people who already run query sets and judgment lists for a living. Their primary engine, by a wide margin, is Apache Solr (Quepid was Solr-first; Chorus is Solr-centric; RRE was originally Solr-only). Fusion's audience is enterprise platform teams who chose Lucidworks as a vendor — overlapping but smaller, and disproportionately concentrated in industries (large e-commerce, government) where the design-partner conversation is longer.

### 4. Fusion adapter cost was material

The prior §27 estimated MVP3 at +3 weeks for "Lucidworks Fusion adapter + multi-Git-provider abstraction." The Fusion adapter alone was estimated at substantially more than the Solr adapter (which is ~2–3 engineer-weeks per the [Solr ecosystem research](../../../07_research/comparison.md) — see also [`infra_adapter_solr/idea.md`](../infra_adapter_solr/idea.md) scope signals):

- Fusion's query API is fundamentally different from ES/Solr Query DSL — pipeline-based, with per-stage parameter overrides. The adapter's `render` path is ~2× the complexity of the Solr adapter's edismax rendering.
- Fusion's auth model (session cookies, JWT, the session pool) is its own thing.
- The two-step apply path (PR edits pipeline params + CI runs `objects-import`) is more complex than the Solr-side single-step (PR edits `*.params.json`, CI runs `bin/post` or `solrconfig.xml` swap).
- Fusion's `*_signals` collection has a different schema from UBI, requiring a Fusion-specific reader feeding the `SignalsConverter` Protocol. Solr uses `solr.UBIComponent` with the standard UBI schema — no Solr-specific reader needed.

Dropping Fusion + deferring multi-Git makes room in MVP2 for the Solr + UBI bundle (~4–5 engineer-weeks combined; see [`infra_adapter_solr/idea.md`](../infra_adapter_solr/idea.md) §"Why bundled with UBI into MVP2"). The four big-ticket Fusion items (adapter, signals reader, replay cassettes, mock service) are gone outright; the multi-Git work is captured separately in the backlog so it's not lost.

### 5. Path B (future production-monitoring + bandits) doesn't need Fusion either

The v2 Path B roadmap in the original spec called out "Fusion Experiments integration" as one Path B candidate. After this drop, that candidate is gone. The remaining Path B candidates (production quality monitoring via signal streams, bandit-style online learning, shadow validation, manual one-click rollback) are all engine-agnostic and work on ES/OpenSearch/Solr equally.

## Proposed action

This is a documentation-only change. No code is touched (the Fusion adapter was never implemented).

### Files to update

1. **`docs/00_overview/relyloop-spec.md`** (~110 Fusion mentions):
   - §1 Summary — remove Fusion from the engine list; add Solr alongside ES + OpenSearch
   - §6 Personas — drop Fusion-specific references
   - §8 Engine adapter specification — delete the `LucidworksFusionAdapter notes` subsection; promote the `SolrAdapter notes` subsection from "architectural reference" to a concrete MVP2 plan; drop the Fusion column from the cross-engine parameter table
   - §14 Evaluation — remove "Fusion Signals" subsection; the engine-native signals reader for Fusion is gone
   - §16 Apply path — remove the Fusion-specific two-step apply path; the Solr apply path matches ES (single-step PR edit)
   - §17 Multi-cluster — remove Fusion-specific cluster examples
   - §22 UI screens — drop Fusion-specific config-repo conventions
   - §25 Deployment — drop the Fusion eval-license appendix; remove `fusion-mock` from the Compose plan
   - §27 Phased delivery — full release-matrix rewrite: MVP2 becomes "Three-Engine + Real Signals" (Solr adapter + UBI judgments, bundled); MVP3 becomes "Observable" (was MVP2 in the prior plan); GA v1 becomes mostly polish + governance + hardening over MVP3; multi-Git + multi-tenant + multi-LLM (prior MVP3 + MVP4 scope) moved to backlog; remove "Fusion Experiments integration" from v2 Path B
   - §28 Tech stack — drop Fusion-related entries
   - §29 Comparison + Open questions — drop Lucidworks-eval-license question, Fusion-cassette-refresh question, Fusion-pipeline-forking-strategy question, Fusion-app/collection-scoping question, mock-Fusion-fidelity-scope question

2. **`docs/01_architecture/adapters.md`** (~18 mentions):
   - Remove `lucidworks_fusion` from the `engine_type` Protocol literal
   - Remove Fusion column from the cross-engine parameter table; promote Solr column to first-class MVP2 status
   - Drop the `stage_enabled` unified-vocabulary parameter (Fusion-only)
   - Remove the line about future `backend/app/adapters/fusion.py`

3. **`docs/01_architecture/tech-stack.md`** (4 mentions):
   - Update release matrix: MVP2 = "Three-Engine + Real Signals" (Solr adapter + UBI judgments); MVP3 = "Observable" (was MVP2 in the prior plan); GA = polish + governance + hardening; multi-Git + multi-tenant + multi-LLM moved to backlog; v2+ no longer lists Apache Solr

4. **`CLAUDE.md`** (3 mentions):
   - Update project overview blurb to list ES + OpenSearch + Solr (not Fusion)
   - Update release matrix

5. **`README.md`** (1 mention):
   - Update headline pitch and "key design choices"

6. **`architecture.md`** (1 mention):
   - Layer 1 adapter description: drop Fusion, add Solr

7. **`state.md`** — capture the release-matrix reshuffle (MVP2 scope, MVP3 renumber, MVP4 → backlog)

8. **Smaller docs** — `optimization.md`, `system-overview.md`, `agent-tools.md`, `mvp1-overview.md`, `deployment.md`, `apply-path.md`, `mvp1-user-stories.md` — 1–3 prune each

### Forward-only

Per the project's forward-only documentation stance, the Fusion sections are deleted outright, not commented out or kept as "deprecated." The git history is the audit trail; future readers find this idea file for the rationale.

## Scope signals

- **Backend:** zero LOC. No Fusion adapter ever existed; no code to remove.
- **Frontend:** zero LOC. No Fusion-specific UI ever shipped.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** none — no Fusion test coverage to remove.
- **Documentation:** ~120 Fusion mentions across ~14 files. All deletions or rewrites, no additions beyond what `infra_adapter_solr/idea.md` adds.

## Why drop, not defer

Deferring Fusion to v2+ would carry the architectural surface (the `lucidworks_fusion` engine_type literal, the Fusion column in the parameter table, the Fusion-specific apply path documentation) forward indefinitely. Future contributors would read the spec, see Fusion, and assume it's the plan. Documentation-as-aspiration rots fastest.

Dropping outright makes the spec truthful: RelyLoop supports the three open-source engines and does not have a roadmap commitment to commercial engines. If a Fusion adopter materializes later with a real workload, the adapter Protocol shape makes contributing a community adapter straightforward — but the project isn't owning that direction.

## Relationship to other work

- **Paired with [`infra_adapter_solr`](../infra_adapter_solr/idea.md)** — Solr fills the MVP2 engine slot Fusion is vacating.
- **Triggered by the reframe in [`docs/07_research/comparison.md`](../../../07_research/comparison.md)** — that doc names the moat (Bayesian + Git-PR + all three OSS engines); this doc executes the engine-list cleanup.
- **Coordinates with the spec §27 revision** that compresses the release matrix to three pre-GA stops (MVP1 shipped → MVP2 Three-Engine + Real Signals → MVP3 Observable → GA v1 polish).
- **Does NOT block UBI on Solr** — the `solr.UBIComponent` writes the standard UBI schema; the MVP2 UBI reader works against Solr unchanged because both ship in the same release.
