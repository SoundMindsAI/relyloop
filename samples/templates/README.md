<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Sample query templates

This directory holds canonical Jinja2 query templates used by the
RelyLoop tutorial + demo seeding. Layout:

```
samples/templates/
  product_search.j2         # Elasticsearch / OpenSearch — the MVP1 demo
  solr/                     # Apache Solr templates (MVP2 — infra_adapter_solr)
    products_edismax.j2
    products_dismax.j2
    products_lucene.j2
```

## Engine subdirectories

ES and OpenSearch share the same Query DSL surface — the MVP1 template at
the top level (`product_search.j2`) renders directly to an ES `multi_match`
body and works against both. Apache Solr's request shape is structurally
different (request parameters, not a query body), so Solr templates live
under `samples/templates/solr/` and render to a flat Solr-param dict.

Future engines (when/if they land) follow the same `<engine>/` subdir
convention.

## Template authoring rules

1. **One Jinja2 file per template** — the template body is the file
   content; the declared params + engine type are configured on the
   `query_templates` row that references it.
2. **Strict-undefined** — referencing an undeclared parameter raises
   `UndefinedError` at render time; declare every parameter the template
   reads (`title_boost`, `field_boosts`, etc.) in the row's
   `declared_params` map.
3. **JSON output** — the rendered output MUST parse as a JSON object. For
   ES the object is the engine-native query body; for Solr the object
   is a request-parameter dict whose keys are either Solr-native
   (`defType`, `q`, `qf`, ...) or unified (`field_boosts`, `boost_fn`, ...)
   per the [cross-engine parameter map](../../docs/01_architecture/adapters.md).
4. **No attribute access** — the Jinja sandbox forbids `.attr` access on
   built-ins; flatten any nested param structures (`field_boosts` is a
   flat dict, not `boost_config.fields`).

See each engine subdir's `*.j2` files for canonical examples.
