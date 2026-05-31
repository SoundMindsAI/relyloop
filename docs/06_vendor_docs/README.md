# Vendor Docs

Engine-, provider-, or vendor-specific references, adapter notes, version quirks, and integration guidance. Distilled snapshots of upstream vendor docs (with the upstream URLs noted), pinned to whatever the project uses today, plus the workflow we'd run when interacting with that vendor.

## Index

| Doc | What it covers | Used by |
|---|---|---|
| [`github-branch-protection.md`](github-branch-protection.md) | Two procedures (modern Rulesets + classic Branch Protection) for requiring CI status checks before merge to `main`; the three exact check names for the `relyloop` repo; verification + gotchas | `infra_foundation` plan §7.5 manual handoff #3; every operator who needs to update branch rules |
| [`solr-10/`](solr-10/) | Apache Solr 10.0 ref-guide pages (asciidoc source, tag `releases/solr/10.0.0`) — matches the `solr:10.0` image. Module loading (`SOLR_MODULES`, no `<lib>`), configsets + UPLOAD API, LTR, auth | `infra_adapter_solr` (MVP2 Solr adapter + Compose infra) |
| [`solr-9/`](solr-9/) | Apache Solr 9.9 ref-guide pages (asciidoc source, tag `releases/solr/9.9.0`) for cross-version comparison | `infra_adapter_solr` — confirm which behaviours differ between 9.x and 10 |
| [`relevance-tools/`](relevance-tools/) | Distilled capability snapshots (with upstream URLs + access dates) of the adjacent/competing relevance tools — OpenSearch SRW + Relevance Agent, Quepid, RRE, Chorus, Elasticsearch native, Splainer. Competitive-landscape references, not integration targets | Evidence base for [`docs/07_research/comparison.md`](../07_research/comparison.md); refresh when a tool ships a release that flips a comparison cell |

### Solr docs detail

Both dirs hold the same 9 ref-guide pages as **asciidoc source** from
`raw.githubusercontent.com/apache/solr/<tag>/solr/solr-ref-guide/modules/...`
(the rendered HTML site is WAF/JS-gated and not cleanly scrapable; the
`.adoc` source is the authoritative text). Pages: `solr-modules`,
`config-sets`, `configsets-api`, `learning-to-rank`,
`basic-authentication-plugin`, `rule-based-authorization-plugin`,
`securing-solr`, `solr-in-docker`, `solr-tutorial`.

**Key finding for `infra_adapter_solr`:** there is NO `user-behavior-insights`
page in either the 9.9 or 10.0 ref guide, and the stock `solr:10.0` Docker
image ships no `ubi` module binary (only `ltr`). The original Story A10/A13
assumption that `solr.UBIComponent` is available in-core does not hold for
the pinned image. Refresh by re-downloading from the raw GitHub path above
with the desired version tag.

## Coming with later features

- `elasticsearch-9x.md` / `opensearch-2x.md` — version quirks the ElasticAdapter must work around (lands with `infra_adapter_elastic`)
- `solr.md` — Apache Solr adapter notes (lands at MVP2 with the Solr adapter)
- `openai-compatible-endpoints.md` — Ollama / LM Studio / vLLM / TGI behavioral differences from canonical OpenAI (lands with `chore_tutorial_polish` operator-runbook polish)
- `gitlab.md` / `bitbucket.md` — Git provider quirks (lands at MVP3 with multi-provider support)
- `anthropic.md` / `bedrock.md` / `vertex.md` — non-OpenAI provider notes (lands at MVP4 with the BaseChatModel abstraction)
