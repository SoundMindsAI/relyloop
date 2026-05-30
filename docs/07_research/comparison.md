# Comparison with adjacent tools

**Status:** Factual reference. Updated when a referenced tool ships a release that changes a row.
**Last updated:** 2026-05-27.
**Scope:** OSS and commercial relevance-tuning tools that overlap RelyLoop's surface. Excludes general-purpose ML observability (Phoenix, LangSmith, Helicone) — those are complementary, not competitive.

This page is a factual matrix, not a sales sheet. Each row links to the tool's own docs so readers can verify claims independently. Where a capability is partial, the cell describes the partial state rather than claiming "no."

## Snapshot matrix

| Capability | RelyLoop (v0.1.0) | OpenSearch SRW (3.6) | OpenSearch Relevance Agent (3.6) | Quepid | RRE | Chorus | Elasticsearch (native) | Splainer |
|---|---|---|---|---|---|---|---|---|
| **Bayesian / TPE optimization over full query-time search space** | yes (Optuna TPE, thousands of trials) | no — Hybrid Search Optimizer is a 66-cell grid search over `{2 norms × 3 combiners × 11 weight steps}` for hybrid weights only ([docs](https://docs.opensearch.org/latest/search-plugins/search-relevance/optimize-hybrid-search/)); Bayesian is in [RFC #934](https://github.com/opensearch-project/neural-search/issues/934) with no shipped code | no | no | no | no | no | no |
| **LLM-as-judge with customizable prompts** | yes | yes — GA in 3.5 ([release notes](https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.5.0.md)) | suggests judgments conversationally | community plugin, not in the OSS core | no | no | no — operators DIY against `_rank_eval` | no |
| **UBI-derived judgments (click streams → ratings)** | planned MVP2 (`feat_ubi_judgments`); hybrid UBI+LLM is the differentiated mode | yes — COEC click model GA ([docs](https://docs.opensearch.org/latest/search-plugins/search-relevance/judgments/)) | no | no | no | yes — reference UBI showcase ([repo](https://github.com/o19s/chorus-opensearch-edition)) | no native UI; UBI plugin available as community fork ([repo](https://github.com/o19s/user-behavior-insights-elasticsearch)) | no |
| **Engine support** | Elasticsearch 8.11+/9.x + OpenSearch 2.x/3.x + **Apache Solr 9.x/10.x (MVP2 shipped)**; one adapter, one workflow | OpenSearch only | OpenSearch only | Solr (since day one) + ES + OpenSearch | Solr + ES | Solr (primary) + OpenSearch (partial) | ES only | Solr + ES |
| **Git-PR apply path (winning configs land as PRs, named approvers merge)** | yes (GitHub today; GitLab + Bitbucket in backlog) | **no — explicitly out of scope by RFC** ([RFC #17735](https://github.com/opensearch-project/OpenSearch/issues/17735): "focuses on evaluation and analysis, not production deployment mechanisms") | no | no — Quepid writes judgments, not configs | no | no | no | no |
| **Search-configuration A/B comparison runner** | indirect (compare studies) | yes — GA in 3.1 ([docs](https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/)) | suggests configs, doesn't compare them at scale | yes (manual) | yes (CLI) | yes (via Quepid) | no — `_rank_eval` is an API primitive, no UI | yes (drill-down) |
| **Scheduled / unattended experiment runs** | yes (Optuna study runs overnight; `feat_auto_followup_studies` chains them) | yes — GA in 3.5 (nightly/weekly/monthly cadence) | no | no | yes (cron-driven CLI) | no | no | no |
| **Multi-cluster support** | yes (one tool, many `clusters` rows) | yes — added in 3.6 ([release notes](https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.6.0.md)) | yes (3.6) | yes | yes | yes | no | no |
| **Conversational agent that runs the loop** | yes (chat orchestrator dispatches `start_study`, `generate_judgments_*`, `open_proposal` tools) | no (SRW UI is form-driven; the Relevance Agent is a separate experimental product) | yes — DSL recommender, **but does not run multi-thousand-trial sweeps** ([blog](https://opensearch.org/blog/introducing-opensearch-relevance-agent-ai-powered-search-tuning/)) | no | no | no | no | no |
| **Local-first LLM observability (self-hosted Langfuse/SigNoz)** | planned MVP2 | n/a (no LLM-as-judge observability surface) | n/a | n/a | n/a | n/a | n/a | n/a |
| **Apache 2.0 license** | yes | yes ([repo](https://github.com/opensearch-project/search-relevance)) | yes (OpenSearch project) | yes ([repo](https://github.com/o19s/quepid)) | yes ([repo](https://github.com/SeaseLtd/rated-ranking-evaluator)) | yes ([repo](https://github.com/querqy/chorus)) | Elastic License 2.0 + SSPL (not OSI-OSS); `_rank_eval` API is Basic-tier | yes ([repo](https://github.com/o19s/splainer-search)) |
| **License tier for relevance-tuning features** | Apache 2.0, all tiers | Apache 2.0, all tiers | Apache 2.0, all tiers | Apache 2.0, all tiers | Apache 2.0, all tiers | Apache 2.0, all tiers | `_rank_eval` Basic; native LTR + ML inference Platinum or higher ([subscriptions](https://www.elastic.co/subscriptions)) | Apache 2.0, all tiers |

## Why the bundle matters

Each individual capability above has at least one OSS comparable. The combination — *Bayesian/TPE optimization across the full search space, on every major open-source engine, with a Git-PR apply path* — does not. Concretely:

- OpenSearch SRW is the closest competitor and ships GA query sets, judgment lists, A/B comparison, LLM-as-judge, scheduled experiments, and UBI judgments — but its optimizer is a 66-cell grid restricted to hybrid weights, and it has no apply path by explicit RFC decision.
- Quepid is the closest *workbench* (manual A/B with judgments) and is the strongest tool for human-rated judgment management; it does not run automated sweeps and is not LLM-driven.
- Elasticsearch ships `_rank_eval` (an API primitive) and deprecated its higher-level Behavioral Analytics and Search Applications products in 9.0 ([release notes](https://www.elastic.co/guide/en/elastic-stack/9.0/release-notes-elasticsearch-9.0.0.html)). There is no native ES equivalent to SRW or RelyLoop.
- Solr's ecosystem (Quepid + Chorus + RRE) is mature for manual evaluation but has no auto-optimizer. UBI ships first-party on Solr as `solr.UBIComponent` ([reference guide](https://solr.apache.org/guide/solr/latest/query-guide/learning-to-rank.html); [UBI tools](https://www.ubisearch.dev/tools/)).

## What RelyLoop deliberately does NOT do

To stay honest about scope:

- **Online A/B testing on production traffic.** Offline evaluation only. See [umbrella spec §4](../00_overview/relyloop-spec.md).
- **Online learning / bandits.** Documented as a v2 Path B direction; deliberately deferred from v1.
- **Production search-quality monitoring.** APM, Grafana, and SRW's own metrics surface own this space.
- **Schema / mapping / analyzer changes.** Tuning is restricted to query-time parameters.
- **Sitting on the live search-serving path.** RelyLoop opens PRs; operator CI deploys them.
- **Training Learning-to-Rank models** in v1. Output is query-time parameter changes, not learned reranker weights. LTR support is a v2 Path A candidate.

## Update cadence

This page is updated when:

- A row changes (a referenced tool ships a release that flips a capability from "no" to "yes" or vice versa).
- A new comparable tool ships its first GA release.
- RelyLoop ships a release that changes its own row.

Pull requests welcomed from operators using any of the listed tools — corrections preferred over new claims.

## Sources

- [OpenSearch Search Relevance Workbench documentation](https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/)
- [OpenSearch SRW repository](https://github.com/opensearch-project/search-relevance)
- [OpenSearch 3.5 release notes (LLM-as-judge GA, scheduled experiments)](https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.5.0.md)
- [OpenSearch 3.6 release notes (multi-datasource SRW, Relevance Agent)](https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.6.0.md)
- [OpenSearch Hybrid Search Optimizer docs (grid search, 66 trials)](https://docs.opensearch.org/latest/search-plugins/search-relevance/optimize-hybrid-search/)
- [Hybrid Search Optimization blog post](https://opensearch.org/blog/hybrid-search-optimization/)
- [RFC #17735 — Search Relevance Workbench scope (apply-path out of scope)](https://github.com/opensearch-project/OpenSearch/issues/17735)
- [RFC #934 — Hybrid Search Optimizer Bayesian future work](https://github.com/opensearch-project/neural-search/issues/934)
- [OpenSearch Relevance Agent blog (experimental, 3.6)](https://opensearch.org/blog/introducing-opensearch-relevance-agent-ai-powered-search-tuning/)
- [OpenSearch UBI plugin documentation](https://docs.opensearch.org/latest/search-plugins/ubi/index/)
- [OpenSearch SRW judgments documentation (COEC)](https://docs.opensearch.org/latest/search-plugins/search-relevance/judgments/)
- [UBI specification (o19s/ubi)](https://github.com/o19s/ubi) · [rendered spec](https://o19s.github.io/ubi/)
- [UBI tools and plugins index](https://www.ubisearch.dev/tools/)
- [Apache Solr LTR reference guide](https://solr.apache.org/guide/solr/latest/query-guide/learning-to-rank.html)
- [Sease: Solr 10 — Vector Search and LTR (March 2026)](https://sease.io/2026/03/apache-solr-10-what-is-new-for-vector-search-and-ltr.html)
- [Quepid repository](https://github.com/o19s/quepid)
- [Chorus repository (Solr-centric reference stack)](https://github.com/querqy/chorus)
- [Chorus OpenSearch edition](https://github.com/o19s/chorus-opensearch-edition)
- [Rated Ranking Evaluator (Sease)](https://github.com/SeaseLtd/rated-ranking-evaluator)
- [Splainer](https://github.com/o19s/splainer-search)
- [Elasticsearch 9.0 release notes (Behavioral Analytics + Search Applications deprecation)](https://www.elastic.co/guide/en/elastic-stack/9.0/release-notes-elasticsearch-9.0.0.html)
- [Elasticsearch `_rank_eval` API reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval)
- [Elasticsearch native LTR docs](https://www.elastic.co/docs/solutions/search/ranking/learning-to-rank-ltr)
- [Elastic subscriptions / license tier matrix](https://www.elastic.co/subscriptions)
