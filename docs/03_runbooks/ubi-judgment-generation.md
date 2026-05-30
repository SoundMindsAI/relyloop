# UBI judgment generation — operator runbook

Status: shipped with `feat_ubi_judgments` (MVP2, 2026-05-29)

## What is UBI judgment generation?

UBI ("User Behavior Insights") derives judgment ratings from real user
signal — clicks, dwell-time — captured at query-time by a search-engine
plugin. RelyLoop **reads** the standardized UBI indices (`ubi_queries`
+ `ubi_events`) via its existing engine adapter and converts the events
into per-(query, doc) ratings. **RelyLoop never writes to the cluster.**

Three converter modes:

- **`ctr_threshold`** — position-bias-corrected click-through rate.
  Default thresholds: `{1: 0.05, 2: 0.15, 3: 0.30}` (CTR > 0.30 → rating 3).
- **`dwell_time`** — post-click dwell-time mean (seconds). Default
  thresholds: `{1: 10.0, 2: 30.0, 3: 90.0}`.
- **`hybrid_ubi_llm`** — UBI for pairs above an impression threshold,
  LLM-fill for sparse pairs.

## Per-engine installation

### Elasticsearch — o19s ES UBI fork {#elasticsearch}

Install the [o19s/ubi fork plugin](https://github.com/o19s/ubi) on every
ES node (8.11+ / 9.x). Restart the cluster. Verify by hitting
`GET /ubi_queries` from your cluster's REST endpoint — a successful
response (even empty) means the index template installed correctly.

In your application, emit UBI events as documents to the
`ubi_queries` and `ubi_events` indices with:

- `application` set to the **target index name** RelyLoop is tuning
  against (e.g. `"products"`). This is how RelyLoop scopes events to a
  single tuning target when one cluster serves multiple frontends.
- `query_id` as a stable UUID per user-issued search; carries the join
  key from `ubi_queries` → `ubi_events`.
- Standard event-attributes per the
  [UBI spec](https://github.com/o19s/ubi) for `position`, `object_id`,
  and `dwell_time_seconds`.

### OpenSearch — OpenSearch UBI plugin {#opensearch}

Install the [OpenSearch UBI plugin](https://opensearch.org/docs/latest/search-plugins/ubi/)
on every OS node (2.x+). The plugin auto-creates `ubi_queries` and
`ubi_events` indices on first event ingest. Same `application` scoping
convention as the ES fork.

### Apache Solr — `solr.UBIComponent` (MVP3)

Solr support requires `infra_adapter_solr` (shipping alongside UBI in
MVP2). The `solr.UBIComponent` writes the same standardized index
shapes, so RelyLoop's UbiReader is engine-agnostic once the Solr
adapter lands.

## Choosing a converter

| Converter | Use when |
|---|---|
| `ctr_threshold` | High-traffic searches with stable user behavior; you trust clicks as a relevance signal. |
| `dwell_time` | Click-through is noisy (e.g. result snippets that mislead) but post-click engagement is meaningful. Needs `dwell_time_seconds` in events. |
| `hybrid_ubi_llm` | Long-tail query set; UBI covers the head, LLM fills sparse pairs. Requires an LLM-fill template + rubric. |

When the readiness probe reports `rung_3` the create-judgments dialog
defaults to `ctr_threshold`; at `rung_2` or `rung_1` it defaults to
`hybrid_ubi_llm`. Override by changing the picker before submit.

## Calibrating the position-bias prior

The position-bias prior assigns a weight per result rank so the
Wang-Bendersky CTR correction can adjust for the natural click bias
toward top positions. RelyLoop ships an **uninformed prior** by default
(every position weighted 1.0) — equivalent to raw CTR.

To install an informed prior, drop a JSON file with the following shape:

```json
{
  "positions": {
    "1": 1.0,
    "2": 0.65,
    "3": 0.45,
    "4": 0.30,
    "5": 0.22
  }
}
```

Set `UBI_POSITION_BIAS_PRIOR_FILE=/path/to/prior.json` in the API +
worker environments. Restart both. Subsequent generations consume the
new prior on the next run.

## Debugging

### `UBI_NOT_ENABLED` (412)

The `ubi_queries` index doesn't exist on the cluster. The plugin isn't
installed, or it's installed but no events have been emitted yet
(some installs only create indices on first event). Verify with:

```bash
curl -u <auth> https://your-cluster/ubi_queries/_count
```

### `UBI_INSUFFICIENT_DATA` (422)

The (target, window) tuple captured fewer events than the configured
`min_impressions_threshold` (default 100). The message will include
the actual observed count and the threshold. Options:

- Widen the window (`since` further back).
- Switch to `hybrid_ubi_llm` to let the LLM fill sparse pairs.
- Lower `min_impressions_threshold` (advanced — risks noisy ratings).

### `ambiguous_query_skip_count > 0` in calibration

The worker skipped queries where the same `user_query` string matched
more than one row in your query set, and `mapping_strategy='reject'`
(default) was active. The judgment-list detail page surfaces an
"Re-run with `most_recent` tiebreaker" affordance.

Alternative resolutions:

- De-dup the query set so each `user_query` is unique.
- Re-run with `mapping_strategy='first_match'` for deterministic
  lexicographic resolution.
- Re-run with `mapping_strategy='most_recent'` to prefer the
  freshest matching query row.

## Diagnosing synthetic-data issues (demo)

The demo reseed seeds **synthetic UBI clickstream** on three of four
demo clusters (`acme-products-prod`, `corp-docs-search`,
`jobs-marketplace-prod`) so the rung classifier, method picker, and
value-delta card are browser-visible without operator setup. The
fourth demo cluster (`news-search-staging`) intentionally stays at
rung_0. See [`feat_demo_ubi_study_comparison`](../00_overview/implemented_features/2026_05_29_feat_demo_ubi_study_comparison/).

### Confirm the indices exist

```bash
# From the host:
curl http://127.0.0.1:9200/ubi_queries?pretty | head
curl http://127.0.0.1:9200/ubi_events?pretty | head

# Or check counts per demo application:
curl 'http://127.0.0.1:9200/ubi_events/_count?q=application:products'
curl 'http://127.0.0.1:9200/ubi_events/_count?q=application:docs-articles'
curl 'http://127.0.0.1:9200/ubi_events/_count?q=application:job-listings'
```

A clean reseed produces ~640 events for the rung_3 acme scenario,
~240 for jobs (rung_2), and ~50 for corp (rung_1). Drift here means
the synthetic generator's volume math regressed — see
[`backend/app/domain/demo/synthetic_ubi.py`](../../backend/app/domain/demo/synthetic_ubi.py).

### Read the rung classifier for a demo cluster

```bash
# Discover the cluster id + query_set id:
curl 'http://127.0.0.1:8000/api/v1/clusters?limit=10' | jq '.data[] | {id, name}'
curl 'http://127.0.0.1:8000/api/v1/query-sets?limit=10' | jq '.data[] | {id, name, cluster_id}'

# Hit the readiness endpoint:
curl 'http://127.0.0.1:8000/api/v1/clusters/<id>/ubi-readiness?query_set_id=<qs_id>&target=products' | jq
```

Expected: `rung_3` for acme-products-prod, `rung_2` for jobs,
`rung_1` for corp, `rung_0` for news.

### Manually rerun the synthetic generator outside the reseed

The home-button reseed cleanup pass DELETEs both UBI indices at start
of every reseed (`DEMO_ES_INDICES` includes `ubi_queries` +
`ubi_events`). To regenerate synthetic UBI without clobbering the
rest of the demo state, use the fast-lane integration test:

```bash
.venv/bin/pytest backend/tests/integration/test_demo_seeding_ubi_fast.py -v
```

It writes a self-contained synthetic dataset against an
`application=products-fasttest` filter so it does not collide with
the demo cluster's `application=products` rows.

## Related docs

- [`docs/01_architecture/llm-orchestration.md`](../01_architecture/llm-orchestration.md) — hybrid LLM-fill cost model
- [`docs/04_security/llm-data-flow.md`](../04_security/llm-data-flow.md) — what data leaves the cluster
- Implementation: [`backend/app/services/ubi_reader.py`](../../backend/app/services/ubi_reader.py) (reader), [`backend/workers/judgments_ubi.py`](../../backend/workers/judgments_ubi.py) (worker)
- Synthetic UBI: [`backend/app/domain/demo/synthetic_ubi.py`](../../backend/app/domain/demo/synthetic_ubi.py) (generator), [`backend/app/services/demo_ubi_seed.py`](../../backend/app/services/demo_ubi_seed.py) (writer + allowlist)
