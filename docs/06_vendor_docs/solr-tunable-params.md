<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Apache Solr tunable parameters

Per-knob reference for the Apache Solr tunable parameters exposed by
RelyLoop's runnable [template library](../../samples/templates/solr/).
Solr's request shape is structurally different from Elasticsearch /
OpenSearch — flat request parameters (passed as URL query params or a
JSON body) rather than a nested query DSL — so this doc cites the
checked-in [`solr-9/`](solr-9/) and [`solr-10/`](solr-10/) Solr ref-guide
asciidoc source as the primary reference.

**Engine versions covered:** Apache Solr **9.x** and **10.x** (the stock
`solr:9.x` and `solr:10.0` Docker images RelyLoop's compose stack uses).
The checked-in ref-guide pages under `solr-9/` and `solr-10/` are the
authoritative source — refresh from the upstream Apache Solr repo
(`raw.githubusercontent.com/apache/solr/releases/solr/<tag>/solr/solr-ref-guide/modules/...`)
when a new Solr release lands.

**Companion docs:**

- [`adapters.md`](../01_architecture/adapters.md) §"Cross-engine parameter naming"
- [`samples/templates/solr/README.md`](../../samples/templates/solr/README.md)
- [`solr-9/`](solr-9/) / [`solr-10/`](solr-10/) — checked-in Apache Solr ref-guide asciidoc

---

## Unified vocabulary (8 cross-engine params)

The [`adapters.md`](../01_architecture/adapters.md) "Cross-engine
parameter naming" table includes the canonical unified-name → Solr-
native pivots. The `SolrAdapter.render()` method translates these
automatically, so a template may use either the unified key
(`field_boosts`) or the native key (`qf`) — both work.

### `field_boosts` (per-field weights)

- **Native Solr name:** `qf` (Query Fields), e.g. `qf=title^2.0 description^1.0 bullet_points^0.5`.
- **Range:** float ≥ 0 per field. Practical range 0.1–10.
- **When to tune:** identical reasoning to ES/OS — when one field carries more discriminative signal than the others.
- **Caveats:** Solr expects a space-joined string; the adapter does this pivot automatically. Order is preserved (Solr's scoring is order-independent but the wire form should match the template's intent).
- **Templates that use this param:** `edismax_basic.j2`, `boost_decay.j2` (via `title_boost`, `description_boost`, `bullet_points_boost`).
- **Source:** [`solr-10/`](solr-10/) — `dismax-query-parser` / `edismax-query-parser` modules (`qf` parameter).

### `phrase_field_boosts`

- **Native Solr name:** `pf` (Phrase Fields), `pf2` (2-gram), `pf3` (3-gram). Same space-joined `field^boost` syntax as `qf`.
- **Range:** float ≥ 0 per field.
- **When to tune:** when multi-token phrases occurring verbatim in a field should boost the document above documents that only match individual tokens.
- **Caveats:** `pf` is the canonical knob `ps` (phrase slop) acts on — without any `pf`, `ps` becomes a silent no-op. That's why `edismax_basic.j2` bakes `pf="title description"` even though it's not a declared tunable.
- **Templates that use this param:** `edismax_basic.j2` (baked-in literal — see the template body).

### `tie_breaker`

- **Native Solr name:** `tie` (the edismax/dismax tie-breaker).
- **Range:** float in `[0.0, 1.0]`. `0.0` = best-match-only; `1.0` = sum of all field scores.
- **When to tune:** same as ES — multi-field discrimination with semi-redundant fields.
- **Caveats:** the adapter accepts both `tie_breaker` (unified) and `tie` (native); the renderer pivots `tie_breaker` → `tie`.
- **Templates that use this param:** `edismax_basic.j2` (via `tie`).
- **Source:** [`solr-10/`](solr-10/) — `edismax-query-parser` module (`tie` parameter).

### `min_should_match`

- **Native Solr name:** `mm` (Minimum Match) — richer arithmetic syntax than ES (e.g. `2<-25% 9<-3`).
- **Range:** integer (`1`, `2`, …), percentage (`50%`, `75%`), or arithmetic syntax (`<threshold><-<spec>`).
- **When to tune:** balance recall vs. precision on multi-clause queries.
- **Caveats:** the arithmetic syntax only activates above the threshold clause count; on shorter queries Solr falls back to `100%`-equivalent.
- **Templates that use this param:** `edismax_basic.j2` (via `mm`).
- **Source:** [`solr-10/`](solr-10/) — `dismax-query-parser` module (`mm` parameter).

### `fuzziness`

- **Native Solr name:** none — Solr expresses fuzziness via the `~` operator inside the query parser (`title:laptop~2`), NOT a request parameter.
- **Range:** N/A (per-term `~N` edit-distance suffix in the query text itself).
- **Caveats:** the SolrAdapter rejects a `fuzziness` request-param with a targeted error message pointing operators at the `~` operator. (Verified by `backend/tests/unit/adapters/test_solr_render.py::TestRenderRejectsUnknownKeys::test_fuzziness_has_custom_message`.)
- **Templates that use this param:** none in the runnable Solr library (`edismax_basic.j2` and `boost_decay.j2` do not expose fuzziness).
- **Source:** [`solr-10/`](solr-10/) — `standard-query-parser` module ("Fuzzy Searches").

### `slop`

- **Native Solr name:** `ps` (Phrase Slop) — applies to phrase queries generated from `pf` / `pf2` / `pf3`.
- **Range:** integer ≥ 0; practical 0–5.
- **When to tune:** when token-order should still matter on a phrase boost but exact order isn't strictly required.
- **Caveats:** `ps` is a no-op when no `pf` is set — that's why `edismax_basic.j2` bakes a `pf` literal.
- **Templates that use this param:** `edismax_basic.j2` (via `ps`).
- **Source:** [`solr-10/`](solr-10/) — `dismax-query-parser` module (`ps` parameter).

### `boost_fn` (boost function)

- **Native Solr name:** `bf` (Boost Function — additive) OR `boost` (multiplicative). The adapter picks one based on `boost_fn.combine="add"` or `"multiply"`.
- **Range:** any Solr function-query expression (`recip()`, `linear()`, `sum()`, `product()`, `scale()`, …).
- **When to tune:** any time a non-lexical signal (recency, popularity, price) should influence rank.
- **Caveats:** combining `bf` (additive) with `boost` (multiplicative) on the same query produces hard-to-reason-about scores; pick one combine semantics per template.
- **Templates that use this param:** `boost_decay.j2` (uses native `bf` with a `recip(ms(NOW, created_at), m, a, b)` expression interpolating `decay_scale` + `boost_weight`).
- **Source:** [`solr-10/`](solr-10/) — `dismax-query-parser` module (`bf` / `boost` parameters); function-query reference under `solr-ref-guide`.

### `rerank_model`

- **Native Solr name:** `rq={!ltr model=<ID> reRankDocs=<K>}` (the LTR query parser, exposed when the `ltr` Solr module is loaded — RelyLoop's Compose stack loads it via `SOLR_MODULES=ltr`).
- **Range:** depends on the deployed LTR model (`reRankDocs` is the rescore window).
- **Caveats:** LTR model deployment is out of scope for the RelyLoop tuning loop (RelyLoop tunes query-time params, not model weights). See [`learning-to-rank.adoc`](solr-10/learning-to-rank.adoc) for the LTR module behaviour.
- **Templates that use this param:** none in the runnable Solr library.

---

## Solr-specific knobs (template library coverage)

### `boost_weight`, `decay_scale`

- **Where used:** `boost_decay.j2` — interpolated into the rendered `bf` string `recip(ms(NOW, created_at), <decay_scale>, <boost_weight>, <boost_weight>)`.
- **Range:**
  - `boost_weight` — float ≥ 0. Both the `a` and `b` arguments of `recip(x, m, a, b) = a/(m*x + b)`; with `a == b` the function returns 1.0 at `x = 0` and asymptotically approaches 0 as `x` grows.
  - `decay_scale` — small positive number (string-typed in the search space so scientific notation like `"3e-11"` interpolates cleanly into the rendered `bf` string).
- **When to tune:** when recency / age should boost lexical edismax matches.
- **Caveats:** the `recip` form requires `created_at` to be a date- or numeric-typed Solr field; on string-typed timestamps the function silently returns identical scores for every doc.
- **Source:** [`solr-10/`](solr-10/) — function-query reference (`recip`, `ms` function descriptions).

### `tie`, `mm`, `ps`

See the unified-vocabulary sections above (`tie_breaker`,
`min_should_match`, `slop`) — Solr exposes these as native short names.

---

## Vector & hybrid — out of scope

Solr 9+ ships dense-vector support via the
[`DenseVectorField`](solr-10/) type + the `{!knn}` query parser
(`q={!knn f=embedding topK=50}<vector>`). Solr also supports hybrid
search by composing `{!knn}` with `bq` / `bf` boost terms or via the
result-set merge primitives, but the wire shape is materially different
from ES's `rrf` retriever and from OpenSearch's normalization processor.

**A Solr kNN / hybrid template is out of scope for this chore** — Solr's
dense-vector surface needs a separate field-type + (optionally) a
separate KNN configset, and is owned by a separate future effort, not
this content/docs chore. See `samples/templates/solr/README.md` "What's
NOT here (and why)" for the scoping decision.

---

## See also

- [`samples/templates/solr/README.md`](../../samples/templates/solr/README.md) — runnable Solr template library
- [`solr-9/`](solr-9/) / [`solr-10/`](solr-10/) — checked-in Apache Solr ref-guide asciidoc source
- [`elasticsearch-tunable-params.md`](elasticsearch-tunable-params.md) — Elasticsearch cheatsheet
- [`opensearch-tunable-params.md`](opensearch-tunable-params.md) — OpenSearch cheatsheet
- [`docs/01_architecture/adapters.md`](../01_architecture/adapters.md) — `SearchAdapter` Protocol + unified-vocabulary cross-engine parameter map
