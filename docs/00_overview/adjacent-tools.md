# Adjacent tools — how RelyLoop fits alongside the rest of the relevance landscape

RelyLoop is not the first tool in the search-relevance space, and it does not
try to replace the tools that already exist there. It is deliberately scoped to
a specific gap — **autonomous, engine-agnostic, Git-PR-mediated query-time
parameter tuning** — and is designed to coexist with the tools listed below.

This document explains, honestly, where each adjacent tool fits, where RelyLoop
fits, and how they can be used together. We would rather you pick the right
tool for your job than pick ours by default.

## At a glance

| Tool | Primary role | Engines | Automated multi-trial optimization | Output channel | Pairs with RelyLoop how |
|---|---|---|---|---|---|
| [**OpenSearch Relevance Agent**](https://opensearch.org/blog/introducing-opensearch-relevance-agent-ai-powered-search-tuning/) (OpenSearch 3.6+, experimental) | Conversational tuning agent w/ hypothesis-driven experiments inside OpenSearch | OpenSearch only | Yes (query-DSL adjustments) | Proposals reviewed in OpenSearch Dashboards | **Direct overlap.** Choose this for single-cluster OpenSearch shops that don't need Git-PR workflow; choose RelyLoop if you need engine-agnosticism, PR-based change management, or multi-cluster/multi-tenant scope |
| [**Quepid**](https://quepid-docs.dev.o19s.com/2/quepid) (OpenSource Connections) | Interactive workbench for per-query exploration; human + AI judging | ES, OpenSearch, Solr, any HTTP-accessible engine | No (manual iteration) | Manual config edits, "Cases" + snapshots | **Strongly complementary.** Quepid is the microscope for individual queries; RelyLoop is the optimization sweep for the whole query set |
| [**OpenSearch Search Relevance Workbench**](https://docs.opensearch.org/latest/search-plugins/search-relevance/) | Built-in query-sets / judgments / experiments framework on OpenSearch | OpenSearch only | Partial — 66-cell grid search over hybrid weights only (Bayesian in [RFC #934](https://github.com/opensearch-project/neural-search/issues/934), no shipped code) | Cluster-side artifacts (no Git-PR apply path — explicitly out of scope per [RFC #17735](https://github.com/opensearch-project/OpenSearch/issues/17735)) | RelyLoop's MVP2 can read OpenSearch judgments and query sets directly; OpenSearch SRW is the source-side building block, RelyLoop is the optimization layer (full-search-space Bayesian + Git PR) above it |
| [**Chorus**](https://github.com/querqy/chorus) (querqy / o19s) | Reference integration stack bundling Solr/ES + Quepid + SMUI + Querqy + monitoring | Solr + ES | No | n/a (it's a stack composition) | RelyLoop can be a member of a Chorus-like stack — Chorus provides the integrated workbench, RelyLoop provides the optimization loop |
| [**SMUI + Querqy**](https://querqy.org/docs/smui/) | Query-rewriting rules management (synonyms, boosts, filters) | Solr (native), ES (via Querqy port) | No | Rule files deployed to engine | **Different layer of the stack.** SMUI/Querqy rewrites queries *before* the engine sees them; RelyLoop tunes the parameters the engine itself uses. Both can run simultaneously |
| [**RRE (Rated Ranking Evaluator)**](https://github.com/SeaseLtd/rated-ranking-evaluator) (Sease) | Java/Maven offline evaluation library + Maven plugins | Solr, Elasticsearch | No | CI metrics, multi-version comparisons | RRE plays the role of the evaluation primitive in CI; RelyLoop uses `ir_measures` (Python) to play the same role inside its own loop. If your team already runs RRE for regression guards, keep it — RelyLoop owns the upstream "find good parameters" step |
| [**Elasticsearch Ranking Evaluation API**](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval) | ES-native endpoint that computes IR metrics from judgments | Elasticsearch only | No (single-metric request) | API response | A low-level primitive. RelyLoop's adapter could call it for in-engine metric computation; today RelyLoop computes metrics off-engine via `ir_measures` for engine-agnosticism |
| [**Elasticsearch LTR plugin / Solr LTR**](https://github.com/o19s/elasticsearch-learning-to-rank) | Learning-to-Rank reranker model training + serving | ES, Solr | n/a (LTR-specific) | Trained reranker model on cluster | **Downstream of RelyLoop.** RelyLoop tunes query-time params (BM25 stage); LTR layers a reranker on top. Tune the base first, train the reranker second. LTR is explicitly out of RelyLoop's v1 scope (spec §4 non-goal) |
| [**Splainer**](https://splainer.io/) (o19s) | Single-query `_explain` visualizer | Solr + ES | No | Diagnostic UI | RelyLoop is the telescope; Splainer is the microscope. Use Splainer when one query is broken; use RelyLoop when the whole template needs systematic improvement |
| [**OpenSearch UBI plugin**](https://github.com/opensearch-project/user-behavior-insights) | Server-side click / event capture | OpenSearch (via plugin); the o19s ES fork + Solr's first-party `solr.UBIComponent` use the same schema | n/a (signals only, no tuning) | UBI tables (`ubi_queries`, `ubi_events`) | **Strongest pairing.** RelyLoop MVP2 ships a `UbiReader` + `SignalsConverter` that turn UBI events into judgments via position-bias-corrected CTR, dwell-time, or **hybrid UBI+LLM** mode (UBI rates the dense head; LLM fills the long tail). Works across all three OSS engines via the standardized schema. SRW also has UBI judgments GA via COEC, but no hybrid mode and no full-search-space optimizer to feed |
| [**Algolia, Coveo, Vespa Cloud, Elastic Cloud, etc.**](https://www.algolia.com/) (proprietary SaaS) | Hosted search engines with built-in relevance tooling | Their own engine | Varies; some include automated tuning | Vendor dashboard | **Different market.** These replace the engine itself. If you're on Algolia or Coveo, your relevance tuning is in their console — RelyLoop is not for you. RelyLoop is for shops that operate their own Elasticsearch / OpenSearch / Apache Solr |

## Where the overlap is, and why RelyLoop exists

The closest tool to RelyLoop in 2026 is the **OpenSearch Relevance Agent**,
introduced in OpenSearch 3.6 as an experimental release inside OpenSearch Agent
Server. It overlaps with RelyLoop on every dimension that matters to the
elevator pitch:

- Conversational, LLM-driven tuning interface
- Hypothesis generation by an LLM ("Hypothesis Generator Agent" on Bedrock)
- Query Sets + Judgment Lists as primitives
- End-to-end automated experimentation pipeline
- Output is a human-reviewed proposal, not an auto-applied change
- Metrics offloaded to deterministic tools (not LLM-computed)

**Honest assessment:** if you operate OpenSearch only, want the simplest
possible deployment, and don't need a Git-PR change-management workflow for
production config, the OpenSearch Relevance Agent is likely the better choice
for your shop. It's bundled with your OpenSearch stack, runs inside the
cluster, integrates with OpenSearch Dashboards, and avoids the operational
overhead of a second tool. The OpenSearch team are search experts shipping a
search-experts' product; we're not going to claim our hosted-LLM-tuning loop
is fundamentally better than theirs on OpenSearch's own turf.

**RelyLoop is the better choice for your shop when one or more of these is
true:**

1. **You operate Elasticsearch** (or Apache Solr, or any mix of ES + OpenSearch + Solr). The Relevance Agent only helps on OpenSearch. RelyLoop's single adapter spans ES 8.11+/9.x and OpenSearch 2.x/3.x today, with Apache Solr 9.x/10.x arriving at MVP2 (bundled with UBI judgments via Solr's first-party `solr.UBIComponent`). Lucidworks Fusion is explicitly dropped — see [`chore_drop_fusion_scope/idea.md`](../00_overview/planned_features/chore_drop_fusion_scope/idea.md).

2. **You require Git-as-source-of-truth for production search-config changes.**
   RelyLoop opens Pull Requests against a central config repo where named
   approvers review and merge them. The Relevance Agent applies changes
   inside OpenSearch directly. RelyLoop's posture is appropriate when the
   operating model says "production behavior is determined by what an approver
   merges, not by what the tool decides."

3. **You have multiple clusters and environments** (prod / staging / dev across
   one or more product lines). RelyLoop's data model is built around running
   studies against any registered cluster from one deployment, and its
   `proposals` workflow is tied to a `config_repo` that can map onto your
   real branch / environment topology.

4. **You want maximum LLM flexibility with zero per-provider engineering.** RelyLoop talks to any OpenAI-compatible endpoint via `OPENAI_BASE_URL` — that one env var is the entire integration surface. Anything that speaks the OpenAI Chat Completions wire protocol works unchanged: OpenAI cloud, Ollama (local), LM Studio (local), vLLM (local or remote), HuggingFace TGI (local or remote), Azure OpenAI's OpenAI-compatible mode, OpenRouter, LiteLLM proxy in front of Bedrock / Vertex / Anthropic. Truly air-gapped deployments run RelyLoop against Ollama on the same VM with zero data leaving the network. See [`docs/08_guides/llm-endpoint-setup.md`](../08_guides/llm-endpoint-setup.md) for the side-by-side configuration walk-through. The OpenSearch Relevance Agent runs on OpenSearch ML Commons connectors with its own provider list.

5. **You want a longer-term path that spans the open-source engine landscape** — running studies across Elasticsearch + OpenSearch + Apache Solr from one tool, one workflow, one config repo.

These differences are deliberate. RelyLoop is not trying to be a better
OpenSearch Relevance Agent on OpenSearch's home turf. It targets a different
operating posture — one that prioritizes engine-agnosticism, Git-mediated
change management, multi-cluster / multi-tenant scope, and provider-agnostic
LLM use.

## Pairing patterns

The honest pitch is rarely "pick one." Most mature relevance stacks layer
multiple tools.

### RelyLoop + Quepid — automated sweep meets interactive workbench

- **Quepid** for: investigating why a specific query is broken, gathering
  subject-matter-expert ratings, hand-crafting judgments interactively, and
  exploring "what if" hypotheses on individual cases.
- **RelyLoop** for: running the overnight optimization sweep that finds
  parameters that improve the whole query set, then opening the PR.
- **Workflow:** start in Quepid to identify a relevance failure mode; export
  the judgment list (or have RelyLoop generate one with LLM-as-judge); run
  a RelyLoop study; review the proposal PR; if the digest surfaces a
  genuinely puzzling sub-population, drop back into Quepid to investigate.

### RelyLoop + OpenSearch UBI — the strongest single pairing

- **UBI** captures real user search behavior (queries, clicks, dwell,
  refinements) server-side. The schema is standardized across all three OSS
  engines: OpenSearch UBI plugin, o19s Elasticsearch UBI fork, Solr's
  first-party `solr.UBIComponent`.
- **RelyLoop MVP2** ships a `UbiReader` (engine-agnostic; reads `ubi_queries`
  + `ubi_events`) and a pluggable `SignalsConverter` Protocol with built-in
  position-bias-corrected CTR, dwell-time, and hybrid UBI+LLM converters.
- **Why it matters:** LLM-as-judge is fast and cheap but operators with real
  traffic distrust it as the sole trust anchor. UBI gives you ground truth
  derived from your actual users. RelyLoop is built to consume it as a
  first-class judgment source.

### RelyLoop + SMUI/Querqy — different layers of the same stack

- **SMUI/Querqy** rewrites the user's query *before* the engine evaluates it
  (synonyms, boosts, filters, spelling).
- **RelyLoop** tunes the parameters the engine uses to evaluate the
  (possibly rewritten) query (field weights, function-score, tie-breakers,
  minimum-should-match).
- **They are orthogonal.** A mature stack uses both — rewriting rules in
  SMUI/Querqy, parameter tuning via RelyLoop. RelyLoop's adapter renders
  query templates against whatever the engine actually sees, including
  Querqy-rewritten queries.

### RelyLoop + Elasticsearch/Solr LTR — base-tier first, reranker second

- **RelyLoop** tunes BM25-stage parameters (the base retrieval).
- **LTR plugins** train a reranker model that re-scores the top-K retrieved.
- **Order matters.** Tune the base first; the reranker compounds on what the
  base hands it. LTR is explicitly out of RelyLoop's v1 scope (spec §4
  non-goal) — these are different problems.

### RelyLoop + RRE — orchestration upstream, regression guard downstream

- **RRE** is a Java/Maven library invoked from CI to catch ranking
  regressions in committed code. It computes metrics against committed
  judgment lists during build.
- **RelyLoop** is the upstream optimization layer that *finds* the
  parameters in the first place, then opens the PR that RRE's CI gate
  will evaluate.
- Both can read the same judgment-list format with light adaptation.

### RelyLoop + Chorus — optimization loop joins the reference stack

- **Chorus** is a reference stack for e-commerce search composition: Solr or
  ES + SMUI + Querqy + Quepid + Keycloak + Prometheus + Grafana + Jaeger,
  pre-wired.
- **RelyLoop** can sit alongside as the automated tuning service that opens
  PRs against the search-config repo Chorus's deployment uses.

## Where RelyLoop deliberately does not compete

RelyLoop explicitly is not, and will not become, a competitor to:

- **Live search-serving runtimes.** RelyLoop never sits on the query-serving
  path (spec §4 non-goal). The engine handles serving; RelyLoop handles
  off-cluster experimentation.
- **Online A/B-testing platforms.** RelyLoop evaluates offline against
  judgment lists. Online A/B is a different operating model with different
  guardrails.
- **Production search-quality monitoring.** Streaming rolling-window metrics
  and alerting on degradation belong to APM (DataDog, Grafana, SRW's own
  metrics surface) — not RelyLoop (spec §4 non-goal). Path B in §27 captures
  this as a v2 candidate direction.
- **Learning-to-Rank model training.** Out of scope for v1. LTR plugins
  (Elastic LTR, Solr LTR) remain the right tool. RelyLoop tunes the
  retrieval layer that LTR reranks.
- **Query-rewriting rule management.** SMUI / Querqy own this layer.
- **Hosted SaaS relevance platforms.** Algolia, Coveo, Vespa Cloud,
  Elastic Cloud Enterprise are different products in a different market.
  RelyLoop is for organizations that operate their own engine.

The scope is deliberately small so that the slice RelyLoop owns — autonomous
query-time parameter tuning, engine-agnostic, Git-PR-mediated — can be done
well, and so that the rest of the relevance ecosystem stays useful around it.

## A note on the OpenSearch Relevance Agent's roadmap

The OpenSearch Relevance Agent's announced roadmap mentions interleaving
tests, schema-evolution recommendations, and LTR automation. If those land
inside OpenSearch, the OpenSearch Relevance Agent will expand into territory
RelyLoop's v1 deliberately doesn't address (e.g., LTR; see spec §4 non-goal).
That is good for OpenSearch operators and not a threat to RelyLoop's
positioning — RelyLoop's pitch (engine-agnostic, Git-mediated, multi-cluster,
multi-tenant) remains differentiated regardless of what the in-engine agent
does on OpenSearch alone. We will keep this document updated as the
landscape changes.
