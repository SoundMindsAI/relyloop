<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Apache Solr — register, probe, and tune

Operator runbook for Apache Solr (`infra_adapter_solr` Story A12).
Covers cluster registration, capability probe + `/reprobe`, edismax
defaults, enabling `solr.UBIComponent`, and uploading LTR models.

> **Solr support landed in MVP2.** Supported versions: Solr 9.x and
> 10.x in standalone and SolrCloud modes. Earlier versions are rejected
> by the capability probe with a clear "below minimum (9.0)" error.

## Prerequisites

- Solr running and reachable from the RelyLoop API container. The
  local Compose stack brings up `solr:10.0` on `127.0.0.1:8983` (see
  [`docker-compose.yml`](../../docker-compose.yml)).
- BasicAuth credentials stored in `./secrets/cluster_credentials.yaml`
  under a `credentials_ref` you'll reference in registration. For local
  Solr the install script seeds `local-solr`.

  > **Credential edits require an API restart.**
  > `cluster_credentials.yaml` is read through a cached `Settings`
  > accessor that memoizes its value at process start. If you edit the
  > file on a running stack (or run step 5a of `scripts/install.sh` after
  > `docker compose up -d`), the api keeps serving the *old* credentials
  > until you restart: `docker compose restart api worker`.
  > The same caching applies to Elasticsearch and OpenSearch credentials.

- For SolrCloud: the operator-supplied URL must point at a Solr node
  that exposes `/admin/zookeeper/status` — the probe uses that
  endpoint to auto-detect cloud vs. standalone.

## 1. Register a Solr cluster

UI: open `/clusters` → click **Register cluster** → pick **Apache
Solr** in the Engine dropdown. The Auth dropdown filters to only
`solr_basic` / `solr_apikey` — the other auth kinds can no longer be
picked for Solr (`AUTH_KIND_NOT_SUPPORTED` 400 has been replaced by
client-side filtering).

Click **Test connection** before submitting. Reachable clusters
report status + version + a capability summary
(UBI / LTR / uniqueKey per target). The button always returns 200 —
unreachable clusters surface as a red ✗ with the diagnostic message,
not a 503.

API: `POST /api/v1/clusters` with
`engine_type: "solr"`,
`auth_kind: "solr_basic" | "solr_apikey"`,
`base_url: "http://<host>:<port>"` (the cluster ROOT — do NOT include
`/solr/<collection>`; the adapter appends `/<target>/...` itself),
`credentials_ref: "<your-ref>"`.

## 2. Capability probe + `/reprobe`

Registration runs `probe_capabilities()`, which writes to
`clusters.engine_config`:

```json
{
  "version": "10.0.0",
  "mode": "cloud" | "standalone",
  "ubi_component_present": true | false,
  "ltr_module_present": true | false,
  "ltr_models": ["xgboost_v1", ...],
  "unique_key_per_target": { "products": "id", "orders": "sku" }
}
```

The probe is per-collection for the **first enumerated target only**
(Solr's `model-store` is per-collection, not cluster-wide). Operators
with multi-collection LTR deployments should:

1. Register the cluster.
2. Run `POST /api/v1/clusters/{id}/reprobe` after selecting the
   intended collection in `engine_config.target_filter` (planned —
   the current probe always picks the first enumerated collection).

The Reprobe endpoint serializes concurrent calls on `SELECT … FOR
UPDATE` so two operators clicking the button at once produce one
consistent result.

## 3. Configure `edismax` defaults

The `relyloop_products` configset ships with:

```xml
<requestHandler name="/select" class="solr.SearchHandler">
  <lst name="defaults">
    <str name="defType">edismax</str>
    <str name="qf">title^2.0 description^1.0 bullet_points^0.5</str>
  </lst>
</requestHandler>
```

RelyLoop's `qf` / `pf` / `tie` / `mm` / `ps` / `bf` / `boost` values
override these defaults at trial time via the `samples/templates/solr/`
templates. The defaults exist so a freshly-created collection responds
to a bare `/select?q=*` query without 400-ing on missing `qf`.

## 4. UBI on Solr

**Important:** the live event-capture component `solr.UBIComponent` does **not**
ship in the stock `solr:10.0` / `solr:9.x` Docker images (verified: no module,
no class, no ref-guide page as of 2026-05). RelyLoop's local demo therefore
**synthesizes** UBI events directly into the `ubi_queries` / `ubi_events`
collections — `UbiReader` reads them back identically to how it reads UBI on
ES/OpenSearch, so UBI **judgment generation** works on Solr out of the box. The
capability probe reports `ubi_component_present=false`, which is accurate.

If you run a Solr build that *does* provide a UBI search component, register it
in your `solrconfig.xml` and the probe will flip to `true` after a `/reprobe`.
The historical example below (a `<searchComponent class="solr.UBIComponent">`
wired into `/select`) is what such a configuration would look like — it is **not**
active in the shipped `relyloop_products` configset:

```xml
<searchComponent name="ubi" class="solr.UBIComponent" />

<requestHandler name="/select" class="solr.SearchHandler">
  <arr name="last-components">
    <str>ubi</str>
  </arr>
</requestHandler>
```

Then `POST /api/v1/clusters/{id}/reprobe` so the next probe records
`ubi_component_present: true`. The frontend UBI on-ramp nudge will
flip from the "enable UBI" copy to the green "UBI is active" copy.

The UBI component writes to the `ubi_queries` + `ubi_events`
collections (you create those at the same time as your main
collection — the install seed script creates all three from the
`relyloop_products` + `relyloop_ubi` configsets).

## 5. Upload an LTR model

Solr's LTR module ships in Solr 10+. Solr 9 requires loading the
module via `solrconfig.xml`. Once loaded, models are uploaded
per-collection via the `model-store`:

```bash
curl -X POST -H "Content-Type: application/json" \
  --data-binary @model.json \
  -u "$SOLR_USER:$SOLR_PASS" \
  "http://solr:8983/solr/products/schema/model-store"
```

`model.json` is a `MultipleAdditiveTreesModel` (or another LTR model
class) per Solr's reference docs. After upload, `POST /reprobe` so the
new model name shows up in `engine_config.ltr_models`. Then a study
search-space whose `rerank_model.id` references the uploaded name
passes the pre-flight check.

If the search-space references an LTR model that's not in
`engine_config.ltr_models`, the study create / run_query request
fails with 400 `LTR_MODEL_NOT_FOUND` listing the available models so
the operator can correct.

## 6. Re-record SolrCloud cassettes

The cassette tests for SolrCloud paths (`backend/tests/integration/
test_solr_cloud_*.py`) are recorded against a maintainer's local
SolrCloud cluster — the CI doesn't run a multi-node SolrCloud.
Re-record when the cluster topology / version changes:

```bash
# Stand up a 3-node SolrCloud locally:
docker compose -f docker-compose.solrcloud.yml up -d

# Re-record (overwrites cassettes/ files):
RELYLOOP_RECORD_CASSETTES=1 .venv/bin/pytest \
  backend/tests/integration/test_solr_cloud_*.py

# Commit the updated cassettes alongside the change that made them
# stale (e.g. a new probe endpoint).
```

## 7. Common errors

| Error code | When | Fix |
|---|---|---|
| `AUTH_KIND_NOT_SUPPORTED` (400) | `auth_kind` not in `solr_basic` / `solr_apikey` | Frontend filters this in the dropdown; if you POST directly, fix the `auth_kind` field. |
| `CLUSTER_UNREACHABLE` (503) | Solr returned 5xx, connection refused, or version below 9.0 | Check `docker logs solr`; verify Solr 9+ is running. |
| `CREDENTIALS_INVALID` (400) on /test-connection | YAML resolution failed before the network call | Add the `credentials_ref` entry to `cluster_credentials.yaml`. |
| `LTR_MODEL_NOT_FOUND` (400) | Study or run_query references an LTR model not in `engine_config.ltr_models` | Upload the model OR rerun `/reprobe` after upload. |
| Authentication failed (HTTP 401/403) | A real operator Solr with auth enabled denied the request | Check the `credentials_ref` username + password match the cluster's `security.json`. (The local Compose Solr runs security-disabled, so this never fires locally.) |

## 8. Where things live

- Compose service: [`docker-compose.yml`](../../docker-compose.yml) → `solr` (SolrCloud, `SOLR_MODULES=ltr`, security disabled for local dev).
- Configsets:
  - [`docker/solr/configsets/relyloop_products/`](../../docker/solr/configsets/relyloop_products/) — LTR queryParser + `[features]` transformer + feature-vector cache.
  - [`docker/solr/configsets/relyloop_ubi/`](../../docker/solr/configsets/relyloop_ubi/) — ubi_queries/ubi_events.
- Adapter: [`backend/app/adapters/solr.py`](../../backend/app/adapters/solr.py).
- Templates: [`samples/templates/solr/`](../../samples/templates/solr/).
- Seed script: [`backend/app/scripts/seed_solr_products.py`](../../backend/app/scripts/seed_solr_products.py).
