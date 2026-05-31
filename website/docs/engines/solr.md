# Apache Solr

!!! abstract "Summary"
    Apache Solr is the third supported engine, landing at **MVP2**. It runs
    behind the same `SearchAdapter` Protocol as Elasticsearch and OpenSearch —
    one workflow, one schema, three engines.

## Version support

| Versions | Status |
|---|---|
| 9.x | MVP2 |
| 10.x | MVP2 |

The bundled local Solr runs in SolrCloud mode with embedded ZooKeeper and the
LTR module loaded (`SOLR_MODULES=ltr`).

## What RelyLoop tunes

RelyLoop's `SolrAdapter` tunes query-time parameters expressed through Solr's
`edismax` query parser — field boosts (`qf`/`pf`), `mm`, `tie`, function
queries (`bf`/`boost`), and phrase boosts — plus `{!ltr}` rescore parameters
where you use Learning-to-Rank. As with the other engines, trials are scored
with `ir_measures`, so the metric is comparable across all three.

## UBI on Solr

RelyLoop reads the standardized UBI schema (`ubi_queries` + `ubi_events`)
**identically** across all three engines, so UBI-derived judgment generation
(MVP2) works on Solr from day one.

!!! note "Live UBI capture vs. read-path"
    The live event-capture component (`solr.UBIComponent`) does **not** ship
    in the stock `solr:10.0` / `solr:9.x` images — no module, no class, no
    ref-guide page. RelyLoop's capability probe reports
    `ubi_component_present=false` accurately. The demo synthesizes UBI events
    directly into those collections rather than capturing them live; the
    **read path** (and therefore judgment generation) is identical regardless
    of how the events were captured.

## Gotchas

!!! warning "Local dev runs without security"
    Solr's default is no `security.json`, so the bundled local Solr's admin
    and query calls are unauthenticated — the same local-dev posture as ES and
    OpenSearch. The adapter's `solr_basic` / `solr_apikey` support exists for
    real operator clusters that enable auth.

## See also

- [The Optimization Loop](../concepts/optimization-loop.md)
- [Search Space](../concepts/search-space.md)
