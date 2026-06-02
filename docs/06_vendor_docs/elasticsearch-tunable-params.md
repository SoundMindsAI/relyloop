<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Elasticsearch tunable parameters

Per-knob reference for the Elasticsearch tunable parameters exposed by
RelyLoop's runnable [template library](../../samples/templates/). Every
section covers: the native ES name, RelyLoop's unified name (when they
differ), valid range / choices, when to tune, common caveats, and the
templates in the library that declare the knob.

**Engine versions covered:** Elasticsearch **8.11+** and **9.x**. Older
ES versions are out of scope (see `docs/01_architecture/adapters.md`
§"Engine version support"). For the OpenSearch-specific divergences,
see [`opensearch-tunable-params.md`](opensearch-tunable-params.md).

**Companion docs:**

- [`adapters.md`](../01_architecture/adapters.md) §"Cross-engine parameter naming" — the canonical unified-name → native-name table this cheatsheet expands.
- [`samples/templates/README.md`](../../samples/templates/README.md) — the runnable template library + per-template registration blocks.

---

## Unified vocabulary (8 cross-engine params)

The cross-engine vocabulary in
[`adapters.md`](../01_architecture/adapters.md) §"Cross-engine parameter
naming" defines 8 unified names that work the same way on every adapter.
Each section below pairs the unified name with the ES native key.

### `field_boosts` (per-field weights)

- **Native ES name:** the `fields` array on a `multi_match` query, e.g. `"fields": ["title^2.0", "description^1.0"]`.
- **Range:** float ≥ 0 per field. Effective signal range: 0.1–10.0; beyond that the boost dominates the tf-idf signal.
- **When to tune:** when one of your fields holds more discriminative tokens than the others (typically `title` > `description` > `bullet_points`).
- **Caveats:** the boost is multiplicative on the per-field score, NOT a global weight — extreme values (e.g. 100×) effectively short-circuit ranking to a single field.
- **Templates that use this param:** `multi_match_basic.j2` (via `title_boost`, `description_boost`, `bullet_points_boost`), `function_score_decay.j2` (same), `bool_boosted.j2` (same), `rescore_phrase.j2` (same).
- **Source:** [ES `multi_match` query reference](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-multi-match-query.html) (accessed 2026-06-02).

### `phrase_field_boosts`

- **Native ES name:** there is no single ES param — phrase emphasis is built either via a `match_phrase` clause inside a `bool` query OR via a `rescore` block over a `match_phrase` (see `rescore_phrase.j2`).
- **Range:** N/A — it's a clause shape, not a numeric knob.
- **When to tune:** when exact phrase matches are an important relevance signal (long product titles, named entities).
- **Caveats:** ES doesn't expose a single `phrase_field_boosts` parameter — the unified concept maps to a `rescore` over a `match_phrase` clause. See `rescore_phrase.j2` for the canonical shape.
- **Templates that use this param:** `rescore_phrase.j2` (implicitly via the phrase-rescore clause).

### `tie_breaker`

- **Native ES name:** `tie_breaker`.
- **Range:** float in `[0.0, 1.0]`. `0.0` = pure best-match-only; `1.0` = sum of all field scores.
- **When to tune:** when documents matching multiple fields should rank above documents that only match one — typical for product search with semi-redundant fields.
- **Caveats:** only meaningful with `type: best_fields` or `most_fields` multi_match; ignored on `cross_fields`.
- **Templates that use this param:** `multi_match_basic.j2` (via `tie_breaker`).
- **Source:** [ES `multi_match` `tie_breaker`](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-multi-match-query.html#type-best-fields) (accessed 2026-06-02).

### `min_should_match`

- **Native ES name:** `minimum_should_match` on a `bool` query.
- **Range:** integer (`1`, `2`, …), percentage (`50%`, `75%`), or arithmetic syntax (`2<-25% 9<-3`).
- **When to tune:** to balance recall vs. precision on multi-clause `bool` queries.
- **Caveats:** the arithmetic syntax only kicks in once the should-clause count exceeds the threshold — on short queries ES silently falls back to a `100%`-equivalent.
- **Templates that use this param:** `bool_boosted.j2` (via `min_should_match`).
- **Source:** [ES `minimum_should_match` reference](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-minimum-should-match.html) (accessed 2026-06-02).

### `fuzziness`

- **Native ES name:** `fuzziness`.
- **Range:** `"0"`, `"1"`, `"2"`, or `"AUTO"`. (Numeric integers are also accepted on `match` clauses.)
- **When to tune:** on noisy user input (typos, OCR text, free-text queries). `AUTO` adapts edit distance to term length.
- **Caveats:** `AUTO` is markedly slower on long queries than a fixed edit distance because every term gets a per-length expansion.
- **Templates that use this param:** `multi_match_basic.j2` (via `fuzziness`).
- **Source:** [ES `fuzziness` reference](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/common-options.html#fuzziness) (accessed 2026-06-02).

### `slop`

- **Native ES name:** `slop` on `match_phrase` / `match_phrase_prefix` queries.
- **Range:** integer ≥ 0. Practical range: 0–5.
- **When to tune:** when an exact phrase is too strict but token-order should still matter (e.g. "blue sofa" → "sofa, blue").
- **Caveats:** `slop` is a **no-op** on `multi_match best_fields` — that's why `multi_match_basic.j2` deliberately omits it. The phrase-slop knob lives on `rescore_phrase.j2` where the rescore-pass query IS a `match_phrase`.
- **Templates that use this param:** `rescore_phrase.j2` (via `rescore_phrase_slop`).
- **Source:** [ES `match_phrase` `slop`](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-match-query-phrase.html) (accessed 2026-06-02).

### `boost_fn` (boost function)

- **Native ES name:** `function_score` query with a `functions` array (multiplicative by default; additive when the combine semantics are explicit).
- **Range:** the function family is open-ended (`gauss`, `linear`, `exp` decays; `field_value_factor`; arbitrary `script_score`).
- **When to tune:** any time a non-lexical signal (recency, popularity, price) should influence rank order.
- **Caveats:** combining `function_score` with `rescore` produces hard-to-reason-about score multipliers; pick one boosting layer.
- **Templates that use this param:** `function_score_decay.j2` (a `gauss` decay over `created_at`).
- **Source:** [ES `function_score`](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-function-score-query.html) (accessed 2026-06-02).

### `rerank_model`

- **Native ES name:** `rescore` with an LTR model OR (8.13+) the native `learning_to_rank` retriever.
- **Range:** depends on the LTR model deployed.
- **When to tune:** when an offline-trained ranking model exists.
- **Caveats:** LTR model deployment is out of scope for the RelyLoop tuning loop (RelyLoop tunes query-time params, not model weights).
- **Templates that use this param:** none in the runnable library (no LTR-bearing template ships in MVP2).

---

## ES-specific knobs (template library coverage)

### `decay_scale`, `decay_offset`, `decay_decay`

- **Native ES name:** `scale`, `offset`, `decay` parameters under a `gauss` / `linear` / `exp` decay function inside `function_score`.
- **Range:**
  - `scale` — a duration string (`"30d"`, `"180d"`) or numeric distance. Controls the half-life-style falloff distance.
  - `offset` — same unit as `scale`. The plateau distance before decay starts. Default `0`.
  - `decay` — float in `(0, 1)`. The value the function returns at `scale` distance from `origin`. Default `0.5`.
- **When to tune:** when freshness / proximity should influence rank. `scale` controls *how fast* the boost fades; `decay` controls *how steep* the curve is at `scale` distance.
- **Caveats:** `scale` must use the same unit family as the source field (date-typed → date-math; numeric → bare numeric). Crossing the boundary silently produces a no-op decay.
- **Templates that use this param:** `function_score_decay.j2`.
- **Source:** [ES decay functions](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/query-dsl-function-score-query.html#function-decay) (accessed 2026-06-02).

### `rescore_window_size`, `rescore_query_weight`, `rescore_phrase_slop`

- **Native ES name:** `window_size`, `query_weight` (and the implicit `rescore_query_weight`), and `slop` inside a `rescore` block.
- **Range:**
  - `window_size` — integer ≥ 1. Practical range: 10–500.
  - `query_weight` — float ≥ 0. The relative weight of the first-pass score in the combined output.
  - `phrase_slop` (which maps onto the rescore-clause's `slop`) — integer ≥ 0. Practical range: 0–5.
- **When to tune:** when a fast first-pass query gets recall right but exact-phrase matches should be promoted within the top-N.
- **Caveats:** `window_size` is per-shard; setting it larger than `from + size` wastes computation. Combined `query_weight` + the implicit rescore weight controls how aggressively the rescore overrides the first pass.
- **Templates that use this param:** `rescore_phrase.j2`.
- **Source:** [ES query rescorer](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/filter-search-results.html#rescore) (accessed 2026-06-02).

---

## Vector & hybrid (reference shapes)

> The following templates are **reference snippets**, not runnable
> templates — they require a query-vector mechanism the RelyLoop trial
> runner does not currently inject (the render context is exactly
> `{**params, "query_text": query_text}`; no embedding pipeline runs).
> They graduate to runnable templates if a future feature wires
> query-vector injection. See `samples/templates/README.md` "What's NOT
> here (and why)" for the scoping decision.

### kNN (Elasticsearch native)

ES 8.11+ exposes `knn` as both a top-level search clause and as the
dense-vector retriever building block for the `rrf` retriever (below).

```json
{
  "knn": {
    "field": "embedding",
    "query_vector": "<EMBEDDING_VECTOR_PLACEHOLDER>",
    "k": 50,
    "num_candidates": 200,
    "boost": 1.0
  }
}
```

Key knobs (cite [ES kNN search ref](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/knn-search.html), accessed 2026-06-02):

| Knob | Range | When to tune |
|---|---|---|
| `k` | int ≥ 1 | how many neighbours to return |
| `num_candidates` | int ≥ `k` | how wide the per-shard scan is — recall/latency knob |
| `boost` | float | multiplier on the kNN score relative to other clauses |

### Hybrid (Elasticsearch native `rrf` retriever — 8.11+)

```json
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {"standard": {"query": {"multi_match": {"query": "<QUERY_TEXT>", "fields": ["title", "description"]}}}},
        {"knn": {"field": "embedding", "query_vector": "<EMBEDDING_VECTOR_PLACEHOLDER>", "k": 50, "num_candidates": 200}}
      ],
      "rank_window_size": 100,
      "rank_constant": 60
    }
  }
}
```

**This is the Elasticsearch-only construct.** OpenSearch 2.x does NOT
ship the `rrf` retriever — its hybrid surface is a search-pipeline
normalization processor (see
[`opensearch-tunable-params.md`](opensearch-tunable-params.md) §"Hybrid").
The two are **not interchangeable** — copying the snippet above into
OpenSearch produces a 400.

**Source:** [ES `rrf` retriever ref](https://www.elastic.co/guide/en/elasticsearch/reference/8.11/rrf.html) (accessed 2026-06-02).

---

## See also

- [`samples/templates/README.md`](../../samples/templates/README.md) — runnable ES/OS template library
- [`opensearch-tunable-params.md`](opensearch-tunable-params.md) — OpenSearch-specific divergences (hybrid construct in particular)
- [`solr-tunable-params.md`](solr-tunable-params.md) — Apache Solr cheatsheet
- [`docs/01_architecture/adapters.md`](../01_architecture/adapters.md) — `SearchAdapter` Protocol + cross-engine vocabulary
