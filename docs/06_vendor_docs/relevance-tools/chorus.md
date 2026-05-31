# Chorus

**Vendor:** Querqy / OpenSource Connections community (Apache 2.0).
**Access date:** 2026-05-31.

A **reference integration stack** for e-commerce search — a way to stand up a
realistic relevance stack (search engine + Querqy rules + SMUI + UBI +
Quepid/RRE) rather than a single tuning tool.

**Capabilities (verified 2026-05-31):**

- **Engine support — three editions:** Solr (the original/primary,
  [`querqy/chorus`](https://github.com/querqy/chorus)), **Elasticsearch**
  ([`querqy/chorus-elasticsearch-edition`](https://github.com/querqy/chorus-elasticsearch-edition)),
  and **OpenSearch**
  ([`o19s/chorus-opensearch-edition`](https://github.com/o19s/chorus-opensearch-edition)).
  The ES/OpenSearch editions trail the Solr original in completeness (e.g. SMUI
  was built for Solr; **Querqy was removed from the OpenSearch edition** until
  updated for recent OpenSearch versions). → **This corrects the earlier
  comparison claim of "Solr (primary) + OpenSearch (partial)," which omitted
  the Elasticsearch edition.**
- **UBI** — Chorus (esp. the OpenSearch edition) is a reference **UBI showcase**;
  UBI itself has plugins for OpenSearch, Elasticsearch, and Solr.
- **Evaluation / A/B** — via the bundled tools (Quepid/RRE), not a native Chorus
  feature.
- **Optimization** — none of its own. No automated sweep, no Bayesian search,
  no LLM-driven loop, no apply path. It's an assembly of components.

**Why it matters vs RelyLoop:** Chorus shows how the OSS relevance pieces fit
together across engines, but the *optimization* is left to the human using the
bundled tools — there is no autonomous loop or Git-PR apply path.

**Upstream URLs:**

- Solr (primary) — https://github.com/querqy/chorus
- Elasticsearch edition — https://github.com/querqy/chorus-elasticsearch-edition
- OpenSearch edition — https://github.com/o19s/chorus-opensearch-edition
- Querqy umbrella — https://querqy.org/
- UBI — https://www.ubisearch.dev/
