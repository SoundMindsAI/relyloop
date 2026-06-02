<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Solr query templates

Apache Solr templates (Solr 9.x + 10.x). Renders to a flat Solr request-
parameter dict per the `SolrAdapter.render()` contract — mixing Solr-native
keys (`defType`, `q`, `qf`, `pf`, `tie`, `mm`, `ps`, `bf`, `boost`, `fl`,
…) with unified-pivot keys (`field_boosts` → `qf`, `tie_breaker` → `tie`,
`min_should_match` → `mm`, `slop` → `ps`, `boost_fn` → `bf` / `boost`)
documented in
[`docs/01_architecture/adapters.md`](../../../docs/01_architecture/adapters.md).

Layout:

```
samples/templates/solr/
  products_edismax.j2                  # demo (infra_adapter_solr)
  products_dismax.j2                   # demo
  products_lucene.j2                   # demo
  edismax_basic.j2                     # library: edismax lexical
  edismax_basic.search_space.json
  boost_decay.j2                       # library: edismax + recency boost
  boost_decay.search_space.json
```

The demo templates (`products_*.j2`) are byte-stable — they're read by
`backend/app/services/demo_seeding.py` and the smoke path. The library
templates below are NEW additions an operator registers on demand.

## Runnable library templates

### `edismax_basic.j2`

**When to use:** the canonical Solr lexical baseline — wider tunable
surface than the demo `products_edismax.j2`. Drop in when you want to
optimize `tie` / `mm` / `ps` along with per-field boosts.

**Declared params** (tunable):

| Param | Type | Notes |
|---|---|---|
| `title_boost` | float | per-field boost on `title` |
| `description_boost` | categorical | discrete float choices |
| `bullet_points_boost` | categorical | discrete float choices |
| `tie` | categorical | edismax tie-breaker, `0.0`–`1.0` |
| `mm` | categorical | Solr `mm` arithmetic syntax: `1`, `2`, `75%`, `2<-25% 9<-3` |
| `ps` | int | phrase-slop tolerance (0–3) |

Baked into the body: `defType=edismax`, the qf field names, the
`pf="title description"` phrase-fields source (without `pf`, `ps` is a
silent no-op — Gemini finding on the spec, accepted), and `fl=*,score`.

**Expected metric behavior:** larger `tie` boosts long-tail matches at
the cost of headline relevance; `ps` lift is workload-dependent.
Cardinality: 100 × 5 × 5 × 5 × 4 × 4 = 200,000.

**Caveats:** `mm`'s arithmetic syntax (`2<-25% 9<-3`) only kicks in on
queries with ≥ 3 clauses; on short queries Solr falls back to `100%`.

**Recommended registration name:** `edismax-basic-v1`.

**Register (copy-paste):**

```bash
jq -n \
  --arg body "$(cat samples/templates/solr/edismax_basic.j2)" \
  '{
    name: "edismax-basic-v1",
    engine_type: "solr",
    body: $body,
    declared_params: {
      title_boost: "float",
      description_boost: "categorical",
      bullet_points_boost: "categorical",
      tie: "categorical",
      mm: "categorical",
      ps: "int"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

### `boost_decay.j2`

**When to use:** when recency (or another date-typed signal) should
boost lexical edismax matches. Uses Solr's `recip(ms(NOW, field), m, a, b)`
function-query expression as an additive boost via `bf`.

**Declared params** (tunable), exact set:

| Param | Type | Notes |
|---|---|---|
| `title_boost` | float | per-field boost on `title` |
| `description_boost` | float | per-field boost on `description` |
| `bullet_points_boost` | categorical | discrete float choices |
| `boost_weight` | categorical | additive boost magnitude — interpolated as both `a` and `b` in `recip(...)` |
| `decay_scale` | categorical | recip slope (`m`), smaller = slower decay |

The `bf` function-expression skeleton, the decay field name
(`created_at`), and `defType=edismax` are baked-in literals. `boost_weight`
and `decay_scale` are interpolated into the rendered `bf` string at
render time.

**Expected metric behavior:** large nDCG@10 deltas on catalogs with
strong recency bias; little signal on time-invariant content.
Cardinality: 100 × 100 × 5 × 4 × 3 = 600,000.

**Caveats:** the `recip(ms(NOW,…), …)` form requires `created_at` to
be a date- or numeric-typed Solr field; on string-typed timestamps the
function silently returns identical scores. Verify the schema before
registering.

**Recommended registration name:** `boost-decay-v1`.

**Register (copy-paste):**

```bash
jq -n \
  --arg body "$(cat samples/templates/solr/boost_decay.j2)" \
  '{
    name: "boost-decay-v1",
    engine_type: "solr",
    body: $body,
    declared_params: {
      title_boost: "float",
      description_boost: "float",
      bullet_points_boost: "categorical",
      boost_weight: "categorical",
      decay_scale: "categorical"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

## What's NOT here (and why)

- **A Solr kNN template** (e.g. `{!knn}`) — Solr's dense-vector surface
  has materially different infra requirements (a `vector` field type,
  potentially a separate KNN configset) and is owned by a separate
  future effort, not this content/docs chore.
- **A Solr hybrid template** — same reason. The
  [`solr-tunable-params.md`](../../../docs/06_vendor_docs/solr-tunable-params.md)
  cheatsheet documents the out-of-scope rationale.

## See also

- [`docs/06_vendor_docs/solr-tunable-params.md`](../../../docs/06_vendor_docs/solr-tunable-params.md) — per-knob native names, ranges, citations, and template back-links
- [`docs/06_vendor_docs/solr-9/`](../../../docs/06_vendor_docs/solr-9/) / [`solr-10/`](../../../docs/06_vendor_docs/solr-10/) — Solr ref-guide asciidoc source
- [`docs/01_architecture/adapters.md`](../../../docs/01_architecture/adapters.md) — `SearchAdapter` Protocol + cross-engine parameter map
