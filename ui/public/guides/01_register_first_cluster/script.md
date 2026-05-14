# Register your first cluster

> 2-minute walkthrough — first step of the Karpathy loop.

RelyLoop optimizes search relevance off-line, but it needs to know *which*
cluster to tune against. A "cluster" record carries the URL, engine type,
auth mode, and an adapter-validated handle to your live Elasticsearch or
OpenSearch instance. Every study, query set, and judgment list references
a cluster by ID.

## Steps

1. **Open the Clusters page.** Click "Clusters" in the top nav. On a fresh
   install the list is empty; subsequent registrations append rows.

2. **Click "Register cluster" in the top right.** A modal opens with the
   defaults pre-filled.

3. **Fill the form:**
   - **Name** — lowercase + dashes only (e.g., `local-es`, `prod-search-1`).
   - **Engine** — elasticsearch or opensearch.
   - **Environment** — dev / staging / prod.
   - **Base URL** — `http://elasticsearch:9200` for the local Compose stack
     (use the internal Docker hostname, not `localhost`, because the API
     container probes the cluster from inside the network).
   - **Auth kind** — es_apikey + an API key, OR es_basic + username/password.
     The local-es fixture uses es_basic.
   - **Credentials ref** — the filename under `./secrets/` holding the
     credential. `local-es` is pre-mounted by `make up`.

4. **Submit.** RelyLoop calls the adapter's `verify_credentials()` probe
   against the cluster. Reachable + authenticated clusters land in the list
   with a green health badge; unreachable ones return
   `CLUSTER_UNREACHABLE` with the underlying error in the response body.

5. **Click the row** to see the cluster's detail page — health probe,
   credentials reference, and the studies that have run against it.

## Next

Now that you have a cluster registered, create a query set to tune for:
see [Guide 02: Create a query set + judgments](#).

## Reference

- API: `POST /api/v1/clusters` with `{name, engine_type, environment, base_url, auth_kind, credentials_ref}`
- Bulk-register the tutorial clusters: `make seed-clusters` registers `local-es` + `local-opensearch`
