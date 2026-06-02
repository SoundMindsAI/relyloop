<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Sample query templates

This directory holds canonical Jinja2 query templates used by the
RelyLoop tutorial + demo seeding, plus the **runnable library** that
ships with the curated-template-library expansion (MVP2). Layout:

```
samples/templates/
  product_search.j2                       # ES / OpenSearch — the MVP1 demo
  multi_match_basic.j2                    # ES / OpenSearch — library: basic best_fields
  multi_match_basic.search_space.json     # starter SearchSpace for multi_match_basic
  function_score_decay.j2                 # ES / OpenSearch — library: function_score gauss decay
  function_score_decay.search_space.json
  bool_boosted.j2                         # ES / OpenSearch — library: bool must/should/filter
  bool_boosted.search_space.json
  rescore_phrase.j2                       # ES / OpenSearch — library: first-pass + phrase rescore
  rescore_phrase.search_space.json
  solr/                                   # Apache Solr templates (MVP2 — infra_adapter_solr)
    products_edismax.j2                   # demo
    products_dismax.j2                    # demo
    products_lucene.j2                    # demo
    edismax_basic.j2                      # library: edismax lexical
    edismax_basic.search_space.json
    boost_decay.j2                        # library: edismax + recency boost
    boost_decay.search_space.json
    README.md                             # per-template Solr docs + registration blocks
```

## Engine subdirectories

ES and OpenSearch share the same Query DSL surface — top-level templates
(`product_search.j2` plus the four library templates) render directly to
an ES / OpenSearch query body and work against both engines. Apache
Solr's request shape is structurally different (request parameters, not
a query body), so Solr templates live under `samples/templates/solr/`
and render to a flat Solr-param dict.

Future engines follow the same `<engine>/` subdir convention.

## Template authoring rules

1. **One Jinja2 file per template** — the template body is the file
   content; the declared params + engine type are configured on the
   `query_templates` row that references it.
2. **Strict-undefined** — referencing an undeclared parameter raises
   `UndefinedError` at render time; declare every parameter the template
   reads (`title_boost`, `min_should_match`, …) in the row's
   `declared_params` map.
3. **JSON output** — the rendered output MUST parse as a JSON object.
   For ES / OpenSearch the object is the engine-native query body; for
   Solr the object is a request-parameter dict whose keys are either
   Solr-native (`defType`, `q`, `qf`, …) or unified (`field_boosts`,
   `boost_fn`, …) per the
   [cross-engine parameter map](../../docs/01_architecture/adapters.md).
4. **No attribute access** — the Jinja sandbox forbids `.attr` access
   on built-ins; flatten any nested param structures (`field_boosts`
   is a flat dict, not `boost_config.fields`).
5. **`declared_params` keys MUST equal `<name>.search_space.json` keys
   exactly.** The platform validator `validate_against_template`
   ([`backend/app/domain/study/search_space.py`](../../backend/app/domain/study/search_space.py))
   rejects both extra search-space keys and missing declared params.
   Any structural value that should stay constant (field names, decay
   function kind, `boost_mode`, `defType`) MUST be a Jinja **literal
   baked into the template body**, NOT a declared param.
6. **Co-located `.search_space.json`.** Every runnable library template
   ships a checked-in `<name>.search_space.json` next to its `.j2`.
   Cardinality (product of per-param bucket counts / categorical /
   integer ranges) MUST stay under 10⁶; floats count as 100 buckets
   each. With three floats already at the cap, additional tunable
   knobs must be `categorical` or `int` with small ranges (see the
   library spaces for the canonical pattern).
7. **Recommended registration name** — each runnable template carries a
   recommended `--name` (e.g. `multi-match-basic-v1`) documented below.
   The FR-7 client-side description map (if it ships) keys off this
   name, so following the convention lets the Step-3 picker show a
   "when to use" summary.

See each engine subdir's `*.j2` files for canonical examples.

---

## Runnable library templates

The four ES/OpenSearch templates below are **engine-agnostic** — the
lexical / function-score / rescore DSL they emit is identical and valid
on both ES 8.11+ and OpenSearch 2.x. Because `query_templates.engine_type`
is a single value per row, an operator who runs both engines registers
the same body **once per engine** with a different `engine_type` value.
The `ENGINE_TYPE="elasticsearch"  # or opensearch` variable in each
registration block below makes that explicit.

### `multi_match_basic.j2`

**When to use:** a fast lexical baseline you can drop into any catalog
that has `title` / `description` / `bullet_points` text fields. Best as
the "what do we beat?" starting point before reaching for decay,
boosting, or rescoring.

**Declared params** (tunable):

| Param | Type | Notes |
|---|---|---|
| `title_boost` | float | per-field boost on `title` |
| `description_boost` | float | per-field boost on `description` |
| `bullet_points_boost` | categorical | discrete float choices |
| `tie_breaker` | categorical | `best_fields` tie-breaker, range 0–1 |
| `fuzziness` | categorical | `"0"`, `"1"`, `"2"`, `"AUTO"` |

`slop` is intentionally NOT exposed — it only affects `phrase` /
`phrase_prefix` multi_match, not `best_fields`. Phrase-slop tuning
lives on `rescore_phrase.j2`.

**Expected metric behavior:** tuning `fuzziness` and `tie_breaker`
typically moves nDCG@10 by 1–3 points on noisy catalogs; on clean
catalogs the boosts dominate. Cardinality: 100 × 100 × 5 × 5 × 4 = 1,000,000.

**Caveats:** `fuzziness="AUTO"` triggers per-term length-based fuzzy
expansion and is markedly slower on long queries than fixed edit-
distance choices.

**Recommended registration name:** `multi-match-basic-v1`.

**Register (copy-paste):**

```bash
ENGINE_TYPE="elasticsearch"  # or opensearch
jq -n \
  --arg body "$(cat samples/templates/multi_match_basic.j2)" \
  --arg engine "$ENGINE_TYPE" \
  '{
    name: "multi-match-basic-v1",
    engine_type: $engine,
    body: $body,
    declared_params: {
      title_boost: "float",
      description_boost: "float",
      bullet_points_boost: "categorical",
      tie_breaker: "categorical",
      fuzziness: "categorical"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

### `function_score_decay.j2`

**When to use:** when recency (or another numeric/date signal) should
boost lexical relevance. Pairs a `multi_match best_fields` first pass
with a Gaussian decay on `created_at`.

**Declared params** (tunable):

| Param | Type | Notes |
|---|---|---|
| `title_boost` | float | per-field boost on `title` |
| `description_boost` | float | per-field boost on `description` |
| `bullet_points_boost` | categorical | discrete float choices |
| `decay_scale` | categorical | gauss decay half-life: `30d`, `180d`, `365d` |
| `decay_offset` | categorical | plateau before decay: `0d`, `30d` |
| `decay_decay` | categorical | value at `decay_scale` distance: `0.3`, `0.5`, `0.7` |

The decay field name (`created_at`), the decay function kind (`gauss`),
and `boost_mode` (`multiply`) are baked into the template as Jinja
literals — they're structural decisions, not tunable knobs.

**Expected metric behavior:** large nDCG@10 deltas on news / catalog
data with strong recency bias; little to no signal on time-invariant
catalogs. Cardinality: 100 × 100 × 3 × 3 × 2 × 3 = 540,000.

**Caveats:** the `gauss` decay requires `created_at` to be a date- or
numeric-mapped field; on string-typed timestamps it silently scores
all docs equally. Verify the mapping before registering.

**Recommended registration name:** `function-score-decay-v1`.

**Register (copy-paste):**

```bash
ENGINE_TYPE="elasticsearch"  # or opensearch
jq -n \
  --arg body "$(cat samples/templates/function_score_decay.j2)" \
  --arg engine "$ENGINE_TYPE" \
  '{
    name: "function-score-decay-v1",
    engine_type: $engine,
    body: $body,
    declared_params: {
      title_boost: "float",
      description_boost: "float",
      bullet_points_boost: "categorical",
      decay_scale: "categorical",
      decay_offset: "categorical",
      decay_decay: "categorical"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

### `bool_boosted.j2`

**When to use:** when you need explicit clause-level control
(`must` for recall, `should` for ranking signal, `minimum_should_match`
for precision tuning) and want to optimize `min_should_match` directly.

**Declared params** (tunable):

| Param | Type | Notes |
|---|---|---|
| `title_boost` | float | should-clause boost on `title` |
| `description_boost` | float | should-clause boost on `description` |
| `bullet_points_boost` | categorical | should-clause boost on `bullet_points` |
| `min_should_match` | categorical | Elasticsearch `minimum_should_match` syntax: `1`, `2`, `50%`, `75%`, `2<-25% 9<-3` |

The `must`-clause field (`title`) and the should-clause field names
(`title`, `description`, `bullet_points`) are baked-in literals.

**Expected metric behavior:** tightening `min_should_match` (e.g. from
`50%` → `75%`) typically lifts precision @ low N at the cost of recall;
the optimizer trades these off against the boost weights.
Cardinality: 100 × 100 × 5 × 5 = 250,000.

**Caveats:** the arithmetic-syntax choice `2<-25% 9<-3` only kicks in on
queries with ≥ 3 should-clauses; on shorter queries it falls back to
`100%`-must behaviour. Combine with longer query sets to see the
trade-off in metrics.

**Recommended registration name:** `bool-boosted-v1`.

**Register (copy-paste):**

```bash
ENGINE_TYPE="elasticsearch"  # or opensearch
jq -n \
  --arg body "$(cat samples/templates/bool_boosted.j2)" \
  --arg engine "$ENGINE_TYPE" \
  '{
    name: "bool-boosted-v1",
    engine_type: $engine,
    body: $body,
    declared_params: {
      title_boost: "float",
      description_boost: "float",
      bullet_points_boost: "categorical",
      min_should_match: "categorical"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

### `rescore_phrase.j2`

**When to use:** when a fast lexical first pass gets recall right but
exact-phrase matches should be promoted within the top-N. Combines
`multi_match best_fields` with a `match_phrase` rescore over a tunable
window.

**Declared params** (tunable):

| Param | Type | Notes |
|---|---|---|
| `title_boost` | categorical | first-pass boost on `title` |
| `description_boost` | categorical | first-pass boost on `description` |
| `bullet_points_boost` | categorical | first-pass boost on `bullet_points` |
| `rescore_window_size` | categorical | hits to rescore: `10`, `25`, `50`, `100`, `200` |
| `rescore_query_weight` | categorical | first-pass weight: `0.5`, `1.0`, `1.5`, `2.0` |
| `rescore_phrase_slop` | int | phrase-slop tolerance (0–5) on the rescore pass |

First-pass `type: best_fields` and the rescore phrase field (`title`)
are baked-in literals.

**Expected metric behavior:** large MRR / nDCG@10 lifts on catalogs
where multi-word product names appear verbatim in `title`; minimal
signal on free-text fields. Cardinality: 5 × 5 × 5 × 5 × 4 × 6 = 75,000.

**Caveats:** rescore is a per-shard operation, so `window_size` larger
than the first-pass `from + size` is wasted work. Keep `window_size`
≤ 200 for catalog-search workloads.

**Recommended registration name:** `rescore-phrase-v1`.

**Register (copy-paste):**

```bash
ENGINE_TYPE="elasticsearch"  # or opensearch
jq -n \
  --arg body "$(cat samples/templates/rescore_phrase.j2)" \
  --arg engine "$ENGINE_TYPE" \
  '{
    name: "rescore-phrase-v1",
    engine_type: $engine,
    body: $body,
    declared_params: {
      title_boost: "categorical",
      description_boost: "categorical",
      bullet_points_boost: "categorical",
      rescore_window_size: "categorical",
      rescore_query_weight: "categorical",
      rescore_phrase_slop: "int"
    }
  }' \
| curl -X POST http://localhost:8000/api/v1/query-templates \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

---

## What's NOT here (and why)

- **`knn_only.j2` / `hybrid_rrf.j2`** — neither ships as a runnable
  template. The trial-runner render context is exactly
  `{**params, "query_text": query_text}` — there is no query-vector
  injection mechanism, so a pure-kNN or hybrid template cannot render
  a complete request today. Instead, engine-correct reference snippets
  live in the ES and OpenSearch tunable-params cheatsheets — see
  [`docs/06_vendor_docs/elasticsearch-tunable-params.md`](../../docs/06_vendor_docs/elasticsearch-tunable-params.md)
  and
  [`docs/06_vendor_docs/opensearch-tunable-params.md`](../../docs/06_vendor_docs/opensearch-tunable-params.md).
- **A Solr kNN / hybrid template** — Solr's dense-vector and hybrid
  surface is materially different from ES / OpenSearch and is owned
  by a separate future effort. The Solr cheatsheet documents the
  out-of-scope rationale.

## See also

- [`docs/06_vendor_docs/elasticsearch-tunable-params.md`](../../docs/06_vendor_docs/elasticsearch-tunable-params.md) — per-knob native names, ranges, citations, and template back-links
- [`docs/06_vendor_docs/opensearch-tunable-params.md`](../../docs/06_vendor_docs/opensearch-tunable-params.md)
- [`docs/06_vendor_docs/solr-tunable-params.md`](../../docs/06_vendor_docs/solr-tunable-params.md)
- [`docs/01_architecture/adapters.md`](../../docs/01_architecture/adapters.md) — `SearchAdapter` Protocol + unified-vocabulary cross-engine parameter map
- [`docs/08_guides/tutorial-first-study.md`](../../docs/08_guides/tutorial-first-study.md) — end-to-end first study walkthrough
