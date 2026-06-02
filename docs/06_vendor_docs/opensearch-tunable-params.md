<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# OpenSearch tunable parameters

Per-knob reference for the OpenSearch tunable parameters exposed by
RelyLoop's runnable [template library](../../samples/templates/). Most
of the lexical surface mirrors Elasticsearch (`multi_match`,
`function_score`, `bool`, `rescore`) — the divergences live in **hybrid
search** (no `rrf` retriever) and in version-specific defaults.

**Engine versions covered:** OpenSearch **2.x** (baseline equivalent to
ES 7.10) and **3.x**. For the lexical knobs that ARE shared with ES,
this doc cross-references
[`elasticsearch-tunable-params.md`](elasticsearch-tunable-params.md)
rather than duplicating the prose; the engine-divergence sections are
called out explicitly.

**Companion docs:**

- [`adapters.md`](../01_architecture/adapters.md) §"Cross-engine parameter naming"
- [`samples/templates/README.md`](../../samples/templates/README.md)
- [`elasticsearch-tunable-params.md`](elasticsearch-tunable-params.md) (~90% of the lexical surface is shared)

---

## Unified vocabulary (8 cross-engine params)

### `field_boosts` (per-field weights)

- **Native OpenSearch name:** the `fields` array on `multi_match` — same shape as ES (`["title^2.0", "description^1.0"]`).
- **Range:** float ≥ 0 per field; practical range 0.1–10.
- **When to tune:** identical to ES — when one field carries more discriminative signal than the others.
- **Caveats:** none beyond the ES advice. Lexical DSL is byte-identical between OpenSearch 2.x and ES 8.11+ for `multi_match`.
- **Templates that use this param:** `multi_match_basic.j2`, `function_score_decay.j2`, `bool_boosted.j2`, `rescore_phrase.j2` (via `title_boost`, `description_boost`, `bullet_points_boost`).
- **Source:** [OpenSearch `multi_match`](https://opensearch.org/docs/2.13/query-dsl/full-text/multi-match/) (accessed 2026-06-02).

### `phrase_field_boosts`

- **Native OpenSearch name:** no single key — same as ES, the canonical implementation is a `rescore` clause over `match_phrase`.
- **Templates that use this param:** `rescore_phrase.j2`.

### `tie_breaker`

- **Native OpenSearch name:** `tie_breaker` (same key as ES).
- **Range:** float in `[0.0, 1.0]`.
- **When to tune:** same as ES — multi-field discrimination with semi-redundant fields.
- **Caveats:** only meaningful with `best_fields` / `most_fields` multi_match; ignored on `cross_fields`. No OpenSearch-specific divergence.
- **Templates that use this param:** `multi_match_basic.j2` (via `tie_breaker`).
- **Source:** [OpenSearch `multi_match` `tie_breaker`](https://opensearch.org/docs/2.13/query-dsl/full-text/multi-match/#best-fields) (accessed 2026-06-02).

### `min_should_match`

- **Native OpenSearch name:** `minimum_should_match` on a `bool` query.
- **Range:** integer, percentage, or arithmetic syntax — identical to ES.
- **Caveats:** identical to ES — arithmetic syntax requires ≥ 3 should-clauses to activate.
- **Templates that use this param:** `bool_boosted.j2` (via `min_should_match`).
- **Source:** [OpenSearch `minimum_should_match`](https://opensearch.org/docs/2.13/query-dsl/minimum-should-match/) (accessed 2026-06-02).

### `fuzziness`

- **Native OpenSearch name:** `fuzziness`.
- **Range:** `"0"`, `"1"`, `"2"`, `"AUTO"`. Same accepted shapes as ES.
- **Caveats:** identical to ES — `AUTO` adapts edit distance to term length and is slower on long queries.
- **Templates that use this param:** `multi_match_basic.j2` (via `fuzziness`).
- **Source:** [OpenSearch common options](https://opensearch.org/docs/2.13/query-dsl/full-text/index/#common-options) (accessed 2026-06-02).

### `slop`

- **Native OpenSearch name:** `slop` on `match_phrase` / `match_phrase_prefix`.
- **Range:** integer ≥ 0; practical 0–5.
- **Caveats:** identical to ES — `slop` is a no-op on `best_fields` multi_match. The runnable `rescore_phrase.j2` is the only template that declares it.
- **Templates that use this param:** `rescore_phrase.j2` (via `rescore_phrase_slop`).
- **Source:** [OpenSearch `match_phrase`](https://opensearch.org/docs/2.13/query-dsl/full-text/match-phrase/) (accessed 2026-06-02).

### `boost_fn` (boost function)

- **Native OpenSearch name:** `function_score` query with a `functions` array — same shape as ES.
- **Range:** decay families (`gauss`, `linear`, `exp`), `field_value_factor`, `script_score`.
- **Caveats:** OpenSearch's `script_score` uses **Painless** (same as ES); `function_score` script changes between OpenSearch 2.x and 3.x are minimal but check the version page.
- **Templates that use this param:** `function_score_decay.j2` (a `gauss` decay).
- **Source:** [OpenSearch `function_score`](https://opensearch.org/docs/2.13/query-dsl/compound/function-score/) (accessed 2026-06-02).

### `rerank_model`

- **Native OpenSearch name:** `learning_to_rank` query (OpenSearch LTR plugin) OR a `rescore` clause.
- **Caveats:** LTR model deployment is out of scope for the RelyLoop tuning loop (RelyLoop tunes query-time params).
- **Templates that use this param:** none in the runnable library.

---

## OpenSearch-specific knobs (template library coverage)

### `decay_scale`, `decay_offset`, `decay_decay`

- **Native OpenSearch name:** `scale`, `offset`, `decay` under a `gauss` / `linear` / `exp` decay inside `function_score`. Identical shape to ES.
- **Range:** see `elasticsearch-tunable-params.md` §"`decay_scale`, `decay_offset`, `decay_decay`" — same defaults and same accepted unit families.
- **Caveats:** OpenSearch's date-math parser is the same lib as ES; cross-version differences appear only on `date_nanos` precision (rare in catalog search).
- **Templates that use this param:** `function_score_decay.j2`.
- **Source:** [OpenSearch decay functions](https://opensearch.org/docs/2.13/query-dsl/compound/function-score/#decay-functions) (accessed 2026-06-02).

### `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop`

- **Native OpenSearch name:** `window_size`, `query_weight`, and rescore-clause `slop` — identical to ES.
- **Range:** same practical ranges (`window_size` 10–500; `query_weight` 0–5; `slop` 0–5).
- **Caveats:** identical to ES. Per-shard window math is the same.
- **Templates that use this param:** `rescore_phrase.j2`.
- **Source:** [OpenSearch rescore](https://opensearch.org/docs/2.13/search-plugins/rescore/) (accessed 2026-06-02).

---

## Vector & hybrid (reference shapes)

> The following templates are **reference snippets**, not runnable
> templates — they require a query-vector mechanism the RelyLoop trial
> runner does not currently inject (the render context is exactly
> `{**params, "query_text": query_text}`; no embedding pipeline runs).
> They graduate to runnable templates if a future feature wires
> query-vector injection.

### kNN (OpenSearch native)

OpenSearch 2.x ships dense-vector kNN via the `knn` query and the
`knn_vector` field type.

```json
{
  "query": {
    "knn": {
      "embedding": {
        "vector": "<EMBEDDING_VECTOR_PLACEHOLDER>",
        "k": 50
      }
    }
  }
}
```

Key knobs (cite [OpenSearch kNN](https://opensearch.org/docs/2.13/search-plugins/knn/knn-index/), accessed 2026-06-02):

| Knob | Range | When to tune |
|---|---|---|
| `k` | int ≥ 1 | how many neighbours to return |
| `ef_search` (index-level) | int ≥ `k` | per-shard exploration depth — recall/latency knob (analog to ES `num_candidates`) |
| `space_type` (index-level) | `l2`, `cosinesimil`, `innerproduct`, `l1` | distance metric — fix at index time |

### Hybrid (OpenSearch search-pipeline normalization processor)

**OpenSearch does NOT ship the Elasticsearch `rrf` retriever.** Its
hybrid surface combines a lexical clause with a kNN clause via a
[search-pipeline normalization processor](https://opensearch.org/docs/2.13/search-plugins/search-pipelines/normalization-processor/)
that runs at search time:

```json
{
  "query": {
    "hybrid": {
      "queries": [
        {"multi_match": {"query": "<QUERY_TEXT>", "fields": ["title", "description"]}},
        {"knn": {"embedding": {"vector": "<EMBEDDING_VECTOR_PLACEHOLDER>", "k": 50}}}
      ]
    }
  }
}
```

Combined with a search pipeline whose normalization processor merges
the two result lists, e.g.:

```json
{
  "phase_results_processors": [
    {
      "normalization-processor": {
        "normalization": {"technique": "min_max"},
        "combination": {"technique": "arithmetic_mean", "parameters": {"weights": [0.6, 0.4]}}
      }
    }
  ]
}
```

**This is the OpenSearch-specific construct.** Elasticsearch's `rrf`
retriever (see
[`elasticsearch-tunable-params.md`](elasticsearch-tunable-params.md)
§"Hybrid") is NOT valid on OpenSearch — copying it produces a 400. The
two engines diverge here intentionally.

Key knobs (cite [OpenSearch normalization processor](https://opensearch.org/docs/2.13/search-plugins/search-pipelines/normalization-processor/), accessed 2026-06-02):

| Knob | Range | When to tune |
|---|---|---|
| `normalization.technique` | `min_max`, `l2` | how raw scores are scaled before combining |
| `combination.technique` | `arithmetic_mean`, `geometric_mean`, `harmonic_mean` | how normalized scores are combined |
| `combination.parameters.weights` | array of floats summing to 1.0 | per-clause weighting in the combined score |

---

## See also

- [`samples/templates/README.md`](../../samples/templates/README.md) — runnable ES/OS template library (engine-agnostic for the four lexical shapes)
- [`elasticsearch-tunable-params.md`](elasticsearch-tunable-params.md) — ES-specific reference (most lexical knobs are shared)
- [`solr-tunable-params.md`](solr-tunable-params.md) — Apache Solr cheatsheet
- [`docs/01_architecture/adapters.md`](../01_architecture/adapters.md) — `SearchAdapter` Protocol + unified-vocabulary cross-engine parameter map
