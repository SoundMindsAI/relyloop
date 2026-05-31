# OpenSearch

!!! abstract "Summary"
    OpenSearch is a first-class, shipped engine (MVP1), served by the same
    `ElasticAdapter` as Elasticsearch. The study workflow is identical — pick
    the cluster, run the loop.

## Version support

| Versions | Status |
|---|---|
| 2.x | supported |
| 3.x | supported |

OpenSearch and Elasticsearch share one adapter implementation. Where the DSLs
diverge, the adapter probes capabilities and adapts; you don't choose a code
path.

## What RelyLoop tunes

The same query-time surface as Elasticsearch — field boosts, function scores,
fuzziness, `minimum_should_match`, tie-breakers, and hybrid weights — varied
together by Optuna's TPE sampler and scored with `ir_measures`.

## How RelyLoop relates to OpenSearch's own tooling

OpenSearch ships the most overlapping native tooling of any engine, so it's
worth being precise about the boundary:

- **Search Relevance Workbench (SRW)** has GA query sets, judgment lists, A/B
  comparison, LLM-as-judge, scheduled experiments, and UBI judgments — but its
  optimizer is a **66-cell grid** restricted to hybrid weights, and it has
  **no apply path** by explicit RFC decision.
- **The OpenSearch Relevance Agent** does conversational DSL recommendations
  for OpenSearch-only shops, but **does not run multi-thousand-trial sweeps**.

RelyLoop's slice is the autonomous, full-search-space Bayesian loop plus the
Git-PR apply path — and the fact that the *same* loop runs on ES and Solr too.
The citation-backed matrix is in the repo's [comparison
doc](https://github.com/SoundMindsAI/relyloop/blob/main/docs/07_research/comparison.md).

## Gotchas

!!! warning "Local dev runs without security"
    The bundled Compose OpenSearch has the security plugin **disabled** for
    local development. Operator clusters with auth are configured per
    `cluster` with credentials from mounted secret files.

- **UBI judgments arrive at MVP2.** OpenSearch's COEC click model is GA
  upstream; RelyLoop's own UBI-derived judgments (read from `ubi_queries` +
  `ubi_events`) land at MVP2, with a hybrid UBI + LLM mode.

## See also

- [Elasticsearch](elasticsearch.md) — same adapter
- [Git-as-Source-of-Truth](../concepts/git-source-of-truth.md) — the apply path SRW lacks
