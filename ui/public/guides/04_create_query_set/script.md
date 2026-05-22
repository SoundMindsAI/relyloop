# Create a query set

> 2-minute walkthrough — define the benchmark you'll tune for.

A "query set" is a named collection of queries scoped to a single cluster.
It's your stable evaluation benchmark — every study scores against it, so
metric improvements across studies are comparable.

## Steps

1. **Open the Query Sets page.** Click "Query Sets" in the top nav.
2. **Click "Create query set."** Modal opens.
3. **Fill the form:**
   - **Name** — short identifier (e.g., `tutorial_queries`, `prod_top_500`)
   - **Cluster ID** — paste the UUIDv7 from the Clusters list
4. **Submit.** The new set lands in the list, empty.
5. **Open the detail page** and click **"Add queries"**.
6. **Upload queries** — accepts JSON (`[{query_text, ...}, ...]`) or CSV
   (`query_id,query_text` header). The dialog validates and bulk-inserts.

## Why query sets are scoped to one cluster

A query set's queries are evaluated against a specific cluster's index.
Sharing a query set across clusters would lose meaning — the same query
returns different results against different indexes, so the benchmark
itself is per-cluster.

If you want to tune against multiple clusters (e.g., dev vs. prod), create
separate query sets for each.

## Reference

- API list: `GET /api/v1/query-sets`
- API create: `POST /api/v1/query-sets` with `{name, cluster_id, description?}`
- API bulk-add queries: `POST /api/v1/query-sets/{id}/queries` (JSON or CSV via Content-Type)
- Per-query CRUD: see Guide 03 (Create a query template) and the in-app
  inline edit/delete buttons on the query-set detail page

> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
