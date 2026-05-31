# Splainer

**Vendor:** OpenSource Connections / o19s (Apache 2.0).
**Access date:** 2026-05-31.

A **relevance diagnostics sandbox** — paste a search URL with all its query
params and Splainer shows the results alongside parsed, summarized `explain`
information so you can understand *why* documents rank where they do. A
debugging tool, not an optimizer.

**Capabilities (verified 2026-05-31):**

- **Engine support** — Solr, Elasticsearch, and **OpenSearch** (with
  experimental support for others, e.g. Vectara). → **This corrects the earlier
  comparison claim of "Solr + ES," which omitted OpenSearch.** The underlying
  `splainer-search` library also powers Quepid's diagnostics.
- **What it does** — interactive explain/score breakdown and query tweaking in a
  sandbox.
- **What it doesn't** — no judgments/metrics workflow, no automated A/B at
  scale, no parameter sweep, no LLM, no scheduling, no apply path.

**Why it matters vs RelyLoop:** Splainer is the "why did this rank?" microscope;
it's complementary to RelyLoop, not a competitor on optimization or apply.

**Upstream URLs:**

- Sandbox app — https://splainer.io/
- `splainer-search` library — https://github.com/o19s/splainer-search
- Splainer app repo — https://github.com/o19s/splainer
