# UBI Judgments — engine-neutral User Behavior Insights as a first-class judgment source

**Date:** 2026-05-22 (refreshed 2026-05-27 for the positioning reframe)
**Status:** Idea — bundled with [`infra_adapter_solr`](../infra_adapter_solr/idea.md) into MVP2 / v0.2 "Three-Engine + Real Signals"
**Priority:** P1 — MVP2 ships UBI + Solr together; the hybrid UBI+LLM converter is the differentiated capability vs OpenSearch SRW (which has UBI-via-COEC GA but no hybrid mode, no full-search-space Bayesian optimizer to feed). See [`docs/07_research/comparison.md`](../../../07_research/comparison.md) for the citation-backed competitive position.
**Origin:** Originally prompted by an external review on 2026-05-22 (LinkedIn outreach to a senior search engineer at a relevance-tooling company who pushed back on LLM-as-judge as the only authoritative judgment source). The 2026-05-27 reframe bundled this work with the Solr adapter into one MVP2 release because Solr's first-party `solr.UBIComponent` writes the same UBI schema as the OpenSearch UBI plugin — UBI on Solr is free once the adapter ships, and the combined release tells the engine-neutral story coherently.
**Depends on:** MVP1 shipped (`judgments` + `judgment_lists` tables, `ElasticAdapter` with `SearchAdapter.search_batch`, `generate_judgments_llm` agent tool pattern). Co-ships with [`infra_adapter_solr`](../infra_adapter_solr/idea.md) in MVP2.

## Problem

MVP1 ships with **LLM-as-judge** as the only authoritative judgment source. The architecture anticipated this would change — the `judgments.source` CHECK already accepts `click` ([`backend/app/db/models/judgment.py:42-48`](../../../../backend/app/db/models/judgment.py#L42-L48)), and judgment lists can mix sources by design ([umbrella spec §14 line 719](../../relyloop-spec.md)). But the actual reader, converter, and ingestion endpoint have never been built.

This leaves three unsolved gaps for operators with production search traffic:

1. **LLM-as-judge is a weaker trust anchor than real user behavior.** For e-commerce, content discovery, and any surface where user intent is the source of truth, ratings derived from clicks + dwell + conversions reflect what users *find* relevant, not what an LLM *guesses* should be relevant. The optimization loop's quality ceiling is the judgment list's quality; replacing the ceiling is the single biggest believability upgrade RelyLoop can ship.
2. **Judgment-list scale and freshness are bounded.** LLM-as-judge produces hundreds to low thousands of (query, doc) ratings per call (rate-limited, cost-bounded). The 80/20 long tail of queries users actually issue never gets rated. Each new study reuses a snapshot judgment list that goes stale; there's no continuous-refresh path.
3. **UBI is the standardized schema across all three OSS engines.** The UBI plugin (championed by Eric Pugh / OpenSource Connections — the same team behind Quepid and the Haystack conference) writes two standardized indices: `ubi_queries` and `ubi_events`. The OpenSearch UBI plugin shipped in 2024 ([opensearch-project/user-behavior-insights](https://github.com/opensearch-project/user-behavior-insights), Apache 2.0). The o19s ES fork ([repo](https://github.com/o19s/user-behavior-insights-elasticsearch)) extends UBI to ES. Apache Solr ships UBI **first-party** as `<searchComponent class="solr.UBIComponent">` in core ([Solr reference guide](https://solr.apache.org/guide/solr/latest/query-guide/learning-to-rank.html); [UBI tools index](https://www.ubisearch.dev/tools/)). The integration friction is unusually low — RelyLoop reads two indices in a cluster it already talks to, on any of the three engines, with no engine-specific UBI code.

## Proposed capabilities

Single-tier — small, additive, no schema migration. Five capability blocks below.

### `UbiReader` — engine-agnostic read layer

- **Location:** new module `backend/app/services/ubi_reader.py` + supporting feature aggregation in `backend/app/domain/ubi/features.py`.
- **Inputs:** `cluster_id`, `target` (the live index being tuned, used to disambiguate UBI events emitted from multiple applications against the same UBI indices), `since` / `until` window, optional `query_filter` (substring or exact-match), optional `max_queries` (default 5000).
- **Reads:** the standardized `ubi_queries` and `ubi_events` indices via `SearchAdapter.search_batch` — the engine adapter is unchanged, the reader uses two scrolling searches and a client-side join on `query_id`. No new adapter method, no engine-specific UBI code.
- **Output:** a per-(query, doc) feature dict with click count, impression count, position-bias-corrected CTR (Wang-Bendersky correction with a configurable position-bias prior; CCM/DBN deferred to v1.5+), post-click dwell-time mean, conversion rate (where the operator emits conversion events; NULL otherwise), refinement rate.
- **Engine-agnostic by construction.** Any `SearchAdapter` that can run a `search_batch` over `ubi_queries` + `ubi_events` is supported. ES + OpenSearch both work in MVP2; engines added later (Solr ships in the same MVP2 release; future adapters land) work the moment their adapter ships, no UBI-specific code required.
- **Operator-facing constraint:** the OpenSearch UBI plugin must be installed and event capture enabled in the operator's application. A capability check at endpoint entry returns 412 `UBI_NOT_ENABLED` if `ubi_queries` is absent.

### `SignalsConverter` Protocol + initial implementations

- **Location:** new module `backend/app/domain/ubi/converter.py` with the Protocol + three concrete impls.
- **Protocol:** `convert(features: dict[QueryDocPair, FeatureVec]) -> dict[QueryDocPair, Rating]` where `Rating` is 0–3 graded. Pure-domain, no I/O.
- **Initial implementations (MVP2):**
  - `CtrThresholdConverter` — position-bias-corrected CTR mapped to 0/1/2/3 via configurable thresholds (defaults: 0.05 / 0.15 / 0.30). Conservative, works on small-traffic clusters.
  - `DwellTimeThresholdConverter` — post-click dwell-time mapped to ratings. Good for content discovery / long-read surfaces where clicks alone don't separate scan-and-bounce from genuine engagement.
  - `HybridUbiLlmConverter` — UBI converter applies where `impressions >= llm_fill_threshold` (default 20); below the threshold the LLM-as-judge path runs over the (query, doc) pair and the resulting `source='llm'` row is interleaved with `source='click'` rows in the same judgment list. This is the operating mode most adopters will ship to production.
- **Deferred to v1.5+ post-GA:** `CcmConverter` and `DbnConverter` (counterfactual click models). Require enough impressions per (query, doc) to be statistically valid, which most early-MVP2 adopters won't have. Same Protocol — additive.

### API surface

- **New endpoint:** `POST /api/v1/judgment-lists/generate-from-ubi` taking `{cluster_id, target, query_set_id, since, until?, converter: "ctr_threshold" | "dwell_time" | "hybrid_ubi_llm", converter_config?: dict, llm_fill_threshold?: int, name: str}` → 202 `{judgment_list_id, status: "generating"}`. Idempotency via `Idempotency-Key` header (consistent with the rest of the API).
- **Background worker:** new `backend/workers/judgments.py:generate_judgments_from_ubi` Arq job that pulls UBI features, runs the converter, optionally invokes the LLM fill, and INSERTs `judgments` rows with the appropriate `source` value per row. Calibration row written to `judgment_lists.calibration` on completion.
- **Error envelopes:** `UBI_NOT_ENABLED` (412) when `ubi_queries` is missing; `UBI_INSUFFICIENT_DATA` (422) when fewer than `min_impressions_threshold` events match the window/query set; `UBI_QUERY_MAPPING_AMBIGUOUS` (422) when a UBI `user_query` string maps to more than one `query_set.queries.query_text` and the operator hasn't specified a tiebreaker.

### Agent tool

- **New tool:** `generate_judgments_from_ubi(query_set_id, cluster_id, target, since, until?, converter, llm_fill_threshold?)` → `JudgmentList`. Mirrors `generate_judgments_llm` shape so the chat agent can switch between the two transparently. Listed in spec §19 Query sets & judgments alongside `generate_judgments_llm`.
- **System prompt update:** the orchestrator's tool description for "generate a judgment list" now prefers UBI when the operator's cluster has UBI enabled (detected via a one-shot `get_schema` probe for the `ubi_queries` index), and falls back to LLM-as-judge otherwise. This is the chat ergonomic that earns the MVP2 release name.

### Operator-facing documentation

- **New runbook:** `docs/03_runbooks/ubi-judgment-generation.md` — installing the OpenSearch UBI plugin, configuring event capture in the operator's application, choosing the right converter for the use case, calibrating thresholds against a 30–50 row hand-labeled sample.
- **Tutorial extension:** `docs/08_guides/tutorial-first-study.md` gains a Step 7 — "Swap the LLM judgment list for a UBI-derived one." Demonstrates the value upgrade by re-running the tutorial study against the new list and surfacing the metric delta.

## Scope signals

- **Backend:** ~600 LOC — `ubi_reader.py` (~200), `domain/ubi/features.py` (~100), `domain/ubi/converter.py` (~150), worker (~80), router additions (~70). Plus ~250 LOC test coverage across unit/integration/contract layers.
- **Frontend:** ~150 LOC — extend the judgment-generation modal (`ui/src/components/judgments/create-judgment-modal.tsx` or whatever sibling shape lands by then) with a "source: LLM | UBI | Hybrid" picker + UBI window controls; new empty-state on the judgment-list detail page when the converter dropped some pairs as insufficient-data.
- **Migration:** **none.** UBI rides the existing `judgments` table; the `source IN ('llm', 'human', 'click')` CHECK already accepts the new value. Alembic head unchanged at whatever MVP1 ships.
- **Config:** one new optional env var `UBI_POSITION_BIAS_PRIOR_FILE` for operators who want to override the default Wang-Bendersky prior with a learned table. Default behaves like an uninformed prior.
- **Audit events:** N/A (MVP2 still pre-`audit_log`; that surface activates at MVP3).
- **Tests:**
  - Unit: converter math (CTR thresholds, dwell-time thresholds, hybrid routing), feature aggregation, position-bias correction edge cases (zero impressions, single-impression queries, NULL dwell)
  - Integration: end-to-end `POST /api/v1/judgment-lists/generate-from-ubi` against a stubbed `UbiReader` that returns canned feature vectors; mixed-source judgment list round-trip (INSERT + SELECT + calibration roll-up)
  - Contract: error-code envelopes (`UBI_NOT_ENABLED`, `UBI_INSUFFICIENT_DATA`, `UBI_QUERY_MAPPING_AMBIGUOUS`), OpenAPI shape lock for the new endpoint, agent-tool registry inventory test
  - Real-engine integration (optional, gated): UBI plugin smoke test against a CI OpenSearch service container with seeded `ubi_queries` + `ubi_events` indices

## Why not implemented inline in MVP1

1. **MVP1 is sized to demonstrate the loop, not to maximize judgment quality.** Adding UBI inline doubles the judgment-source code path before the LLM-as-judge path has been proven against real adopter feedback. Shipping LLM-only first lets MVP1 stay focused on the optimization-loop value prop; MVP2 then earns the trust upgrade for operators with traffic.
2. **Converter strategy benefits from MVP1 adopter feedback.** Position-bias priors, dwell-time thresholds, and the LLM-fill cutoff are all judgment calls that get sharper after watching adopters run MVP1's LLM-as-judge against their real data. Building MVP2 against MVP1 adopter signal is meaningfully cheaper than building it speculatively.
3. **No schema migration is required to wait.** The `judgments.source` enum, the mixed-source judgment list contract, and the `SignalsConverter` Protocol shape were designed for this upgrade from day one. Delaying ships nothing important earlier; rushing ships a less-tuned converter.
4. **Strategic positioning.** Naming a dedicated MVP2 "Real Signals" release for UBI signals that UBI is a first-class direction — relevant for adoption in the OSC community where UBI was incubated, and for design partners who'd otherwise discount RelyLoop as an LLM-only tuning toy. Burying UBI in a later observability or hardening release misses that positioning.

## Relationship to other work

- **Cleans up [`docs/00_overview/relyloop-spec.md`](../../relyloop-spec.md) §14 + §19 + §27** — the spec previously framed click data as a per-engine adapter concern with engine-specific timelines. The §14 patch (landing with this idea) re-anchors the architecture around the engine-neutral UBI schema (which works across all three OSS engines via their respective UBI implementations), with engine-native readers (Elastic Behavioral Analytics, etc.) as thin extensions feeding the same `SignalsConverter` Protocol when an adopter needs them.
- **Composes with [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)** — auto-chained follow-up studies become dramatically more useful with a continuously-refreshed UBI judgment list than with a snapshot LLM-as-judge list. The two features are complementary; UBI ships first.
- **Composes with [`feat_pr_metric_confidence`](../../implemented_features/2026_05_21_feat_pr_metric_confidence/)** (shipped 2026-05-21) — the confidence framing in the PR body becomes meaningfully stronger when "the metric was scored against 50,000 UBI-derived ratings covering 90% of last week's traffic" replaces "the metric was scored against 500 LLM ratings against a snapshot query set."
- **Composes with [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) + [`feat_config_repo_baseline_tracking`](../feat_config_repo_baseline_tracking/idea.md)** — once UBI is the judgment source, "the baseline metric on the live config" becomes a meaningful absolute number rather than a synthetic LLM-rated approximation. Materially raises the credibility of every winning trial.
- **Does NOT block MVP2 "Observable"** — Langfuse and SigNoz instrumentation can layer on top of `generate_judgments_from_ubi` exactly as it would on top of `generate_judgments_llm`. The `langfuse_trace_id` lineage column landing at MVP2 will be NULL for `source='click'` rows (which never invoke an LLM) and populated for `source='llm'` rows in the hybrid case — same column, source-dependent fill.
- **Does NOT block later engine work** — the MVP2 `SignalsConverter` Protocol is engine-agnostic. New adapters added in later releases contribute their own engine-native reader (where they have one) feeding the same Protocol; the converter library and the API surface are unchanged regardless of which engines ship.
