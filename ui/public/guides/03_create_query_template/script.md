# Create a query template

> 3-minute walkthrough — define the search-time parameters Optuna will tune.

A "query template" is RelyLoop's abstraction over a parameterized
Elasticsearch / OpenSearch query DSL. Without templates, every study would
need its own ad-hoc query construction. With templates, you write the
query once and declare which parts of it vary per trial.

## Steps

1. **Open the Templates page.** Click "Templates" in the top nav.
2. **Click "Create template."** A modal opens.
3. **Fill the form:**
   - **Name** — short identifier (e.g., `product_search`, `multi_match_with_boosts`)
   - **Engine** — elasticsearch or opensearch
   - **Body** — the JSON query DSL with `{{ param_name }}` Jinja2 placeholders
   - **Declared params** — one `name:type` per line; types are `string`, `int`, `float`, `bool`
4. **Submit.** RelyLoop validates the Jinja2 syntax + the declared-vs-used
   param consistency.

## Versioning via fork

Templates are immutable for traceability. To evolve a template, click
**"Fork to v2"** on its detail page. The fork inherits the same name with
an incremented version. `parent_id` on the new template preserves the
lineage so studies can reference a specific historical version.

## Reference

- API: `POST /api/v1/query-templates` with `{name, engine_type, body, declared_params, parent_id?}`
- Validation: `INVALID_TEMPLATE_SYNTAX` on bad Jinja2; `DECLARED_PARAM_UNUSED` /
  `UNDECLARED_PARAM_USED` on declared-vs-used mismatch
- Docs: [`docs/01_architecture/adapters.md`](../01_architecture/adapters.md)
  documents how templates are rendered through the engine adapter at trial time
