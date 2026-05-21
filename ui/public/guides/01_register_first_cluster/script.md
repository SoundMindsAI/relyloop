# Register your first cluster

> 3-minute walkthrough — first step of the Karpathy loop.

RelyLoop optimizes search relevance off-line, but it needs to know *which*
cluster to tune against. A "cluster" record carries the URL, engine type,
auth mode, and an adapter-validated handle to your live Elasticsearch or
OpenSearch instance. Every study, query set, and judgment list references
a cluster by ID.

## Steps

1. **Open the Clusters page.** Click "Clusters" in the top nav. On a fresh
   install the list is empty; if you ran `make seed-demo` you'll see four
   meaningful demo scenarios (acme-products-prod, corp-docs-search,
   news-search-staging, jobs-marketplace-prod) — register your own to add
   another row.

2. **Click "Register cluster" in the top right.** A modal opens with the
   defaults pre-filled. The form extends below the visible viewport —
   scroll within the modal to see every field including the optional
   Notes and Target filter inputs.

3. **Fill the form** with realistic values for a production e-commerce
   cluster:
   - **Name** — lowercase + dashes only (e.g., `acme-products-prod`).
   - **Engine** — elasticsearch or opensearch.
   - **Environment** — `prod` for production clusters, `staging`/`dev`
     otherwise.
   - **Base URL** — `http://elasticsearch:9200` for the local Compose stack
     (use the internal Docker hostname, not `localhost`, because the API
     container probes the cluster from inside the network).
   - **Auth kind** — `es_apikey` + an API key, OR `es_basic` + username/
     password. The local-es fixture uses `es_basic`.
   - **Credentials ref** — the filename under `./secrets/` holding the
     credential. `local-es` is pre-mounted by `make up`.
   - **Notes** — a free-form description of the cluster's purpose
     (e.g., "Production Elasticsearch cluster — e-commerce product search").
   - **Target filter (optional)** — a glob that scopes this cluster's
     index picker. Set it to `products*` and the create-study modal's
     index dropdown will only show matching indices for this cluster
     instead of every index on the box. Brace expansion
     (`docs-{en,fr}*`) isn't supported — use a wider glob like `docs-*`
     or register multiple clusters.

4. **Submit.** RelyLoop calls the adapter's `verify_credentials()` probe
   against the cluster. Reachable + authenticated clusters land in the
   list with a health badge (green when healthy, yellow when partially
   reachable, red on `CLUSTER_UNREACHABLE`). The toast in the bottom
   right confirms the registration and the probe result.

5. **Click the row** to see the cluster's detail page — health probe,
   version, base URL, auth kind, your notes, and the studies that have
   run against it.

## Next

Now that you have a cluster registered, create a query set to tune for:
see [Guide 04: Create a query set](#).

## Reference

- API: `POST /api/v1/clusters` with `{name, engine_type, environment, base_url, auth_kind, credentials_ref, notes?, target_filter?}`
- Bulk-register the tutorial clusters: `make seed-clusters` registers `local-es` + `local-opensearch`
- Seed 4 realistic demo scenarios with target filters baked in: `make seed-demo`
