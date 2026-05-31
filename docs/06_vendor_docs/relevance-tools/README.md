# Adjacent relevance tools — distilled snapshots

Distilled capability snapshots of the OSS/commercial relevance-tuning tools
that overlap RelyLoop's surface. These are the **evidence base** for the
competitive matrix in
[`docs/07_research/comparison.md`](../../07_research/comparison.md): each note
records what the tool does, the version/status, the license/tier, the upstream
URLs, and the **access date** the claims were verified against.

These are *competitive-landscape* references, distinct from the
engine-integration references at the top level (`solr-9/`, `solr-10/`) — RelyLoop
does not integrate with these tools; it is compared against them.

## Index

| Note | Tool(s) | Backs comparison columns |
|---|---|---|
| [`opensearch-relevance.md`](opensearch-relevance.md) | OpenSearch Search Relevance Workbench (SRW) + OpenSearch Relevance Agent | "OpenSearch SRW", "OpenSearch Relevance Agent" |
| [`quepid.md`](quepid.md) | Quepid (OpenSource Connections / o19s) | "Quepid" |
| [`rated-ranking-evaluator.md`](rated-ranking-evaluator.md) | Rated Ranking Evaluator (Sease) | "RRE" |
| [`chorus.md`](chorus.md) | Chorus (Querqy / o19s) | "Chorus" |
| [`elasticsearch-native.md`](elasticsearch-native.md) | Elasticsearch native (`_rank_eval`, LTR, deprecated Behavioral Analytics / Search Applications) | "Elasticsearch (native)" |
| [`splainer.md`](splainer.md) | Splainer (o19s) | "Splainer" |

## Maintenance

Refresh a note when the tool ships a release that changes a comparison cell.
Always update the **Access date** line and re-verify the upstream URLs when you
touch a note, then propagate any cell change into `comparison.md` (and bump its
"Last updated" line). Corrections preferred over new claims.

**Last audited:** 2026-05-31.
