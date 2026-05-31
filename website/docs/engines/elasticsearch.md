# Elasticsearch

!!! abstract "Summary"
    Elasticsearch is a first-class, shipped engine (MVP1). RelyLoop tunes
    query-time parameters against ES through the same `SearchAdapter` Protocol
    it uses for every engine — no ES-specific workflow.

## Version support

| Versions | Status |
|---|---|
| 8.11+ | supported |
| 9.x | supported |

A single adapter (`ElasticAdapter`) serves both Elasticsearch 8.11+/9.x and
OpenSearch 2.x/3.x — their query DSLs overlap enough that one implementation
covers both, with capability probing for the differences.

## What RelyLoop tunes

Query-time parameters only:

- `function_score` modifiers (recency, popularity, decay)
- per-field boosts in `multi_match` / `dis_max`
- `fuzziness` and `minimum_should_match`
- `tie_breaker` across fields
- hybrid lexical/semantic weights where you run hybrid search

It evaluates trials by running your query set against the cluster and scoring
with `ir_measures`. It does **not** touch mappings, analyzers, or index
settings.

## Gotchas

!!! warning "Local dev runs without security"
    The bundled Compose Elasticsearch has security **disabled** for local
    development — same posture as the bundled OpenSearch. Real operator
    clusters that enable auth are configured per `cluster` in the registry;
    credentials are resolved from mounted secret files, never bare env vars.

- **`_rank_eval` is not what RelyLoop uses.** ES ships `_rank_eval` as an API
  primitive, but RelyLoop runs its own trial loop and scores with
  `ir_measures` so the metric is identical across engines.
- **License tiers don't gate RelyLoop.** RelyLoop tunes query-time parameters
  that work on any ES tier; it does not depend on Platinum-tier LTR or ML
  inference.

## See also

- [Search Space](../concepts/search-space.md) — the parameters tuned
- [OpenSearch](opensearch.md) — served by the same adapter
