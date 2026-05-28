# RelyLoop

> **Status: alpha (MVP1, v0.1.0).** The only open-source tool that runs automated Bayesian search-space optimization across thousands of trials, on every major open-source search engine (Elasticsearch, OpenSearch, Apache Solr at MVP2), and ships winning configs as Pull Requests for your existing approval workflow.

A conversational LLM agent describes the problem and proposes the search
space, but the engineering moat is the loop itself, the Git-PR posture, and
the three-engine reach. RelyLoop runs **thousands of Optuna/TPE trials**
across the full query-time search space (field boosts, function scores,
fuzziness, `mm`, tie-breakers, hybrid weights — not just one slice),
evaluates each trial against `ir_measures`-computed metrics, and opens a
**Pull Request** with the winning configuration against your central
search-config Git repo. Your existing approvers and CI handle deployment;
RelyLoop never sits on the live search-serving path.

See [`docs/07_research/comparison.md`](docs/07_research/comparison.md) for
the citation-backed comparison vs OpenSearch Search Relevance Workbench,
Quepid, RRE, Chorus, and Elastic's native tooling — and why the bundle is
genuinely unique in May 2026.

## 5-minute quickstart

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop

make up                # auto-generates secrets, builds the ui image, brings up the stack (~90s cold)
make migrate           # apply the alembic chain
make seed-clusters     # register local-es + local-opensearch
make seed-es           # seed local-es 'products' index from samples/products.json (1,000 docs)

open http://localhost:3000/chat
```

Tutorial — the full operator walkthrough from `git clone` through "PR opened
in GitHub" — is in
[`docs/08_guides/tutorial-first-study.md`](docs/08_guides/tutorial-first-study.md).

For a local-LLM walkthrough (Ollama / LM Studio / vLLM / TGI instead of OpenAI),
see Step 0 of the tutorial.

**Hardware:** 16 GB RAM is comfortable. Elasticsearch + OpenSearch each consume
~1 GB heap; bump `ES_HEAP_SIZE` in `.env` if you index large corpora.

## What's in MVP1 / What's coming

MVP1 ships the full Karpathy loop end-to-end on Elasticsearch + OpenSearch:
chat agent, Optuna/TPE optimizer, LLM-as-judge, digest, GitHub PR worker,
single-tenant install. **MVP2** adds Apache Solr + UBI judgments + hybrid
UBI+LLM (bundled). **MVP3** adds local-first observability (Langfuse +
SigNoz). **GA v1** is polish + governance + hardening — no new product
surface; all six differentiators are in by MVP3.

Canonical release matrix:
[`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md) —
do not duplicate here, the matrix is the source of truth.

## Key design choices

- **Engine-neutral across the three OSS engines** — Elasticsearch + OpenSearch in MVP1 via one adapter; Apache Solr in MVP2. Lucidworks Fusion explicitly dropped (see [`chore_drop_fusion_scope/idea.md`](docs/02_product/planned_features/chore_drop_fusion_scope/idea.md)).
- **Full-search-space Bayesian/TPE optimization** — Optuna across field boosts, function scores, fuzziness, `mm`, tie-breakers, hybrid weights, LTR rescoring. Not a 66-cell grid over hybrid weights alone (the only thing OpenSearch SRW's optimizer covers today).
- **Git-as-source-of-truth** — winning configs land as PRs against a central config repo; deployment is the operator's CI's job, not RelyLoop's. OpenSearch SRW has no apply path by explicit RFC choice; this is a stable differentiator.
- **Provider-neutral LLM** — OpenAI-compatible endpoint in MVP1 (works against api.openai.com, Ollama, LM Studio, vLLM, HuggingFace TGI via `OPENAI_BASE_URL`). Native non-OpenAI provider SDKs are in the backlog.
- **Local-first observability** — Langfuse + SigNoz both self-hosted (MVP3); no LLM trace data leaves the deployment VM.
- **Single-tenant through GA v1** — multi-tenancy is in the backlog; SSO via reverse proxy is the recommended path for now.
- **Deliberate, not real-time** — RelyLoop is for offline experimentation and change management; it does not sit on the live search-serving path. Online learning / bandits / production-quality monitoring are a v2 Path B direction.

See spec §4 (non-goals) for the full set.

## Links

- Tutorial: [`docs/08_guides/tutorial-first-study.md`](docs/08_guides/tutorial-first-study.md)
- Umbrella spec: [`docs/00_overview/relyloop-spec.md`](docs/00_overview/relyloop-spec.md)
- Architecture index: [`docs/01_architecture/`](docs/01_architecture/)
- Local-dev runbook: [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md)
- Release checklist (maintainers): [`docs/03_runbooks/release-checklist.md`](docs/03_runbooks/release-checklist.md)
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions use the Developer Certificate of Origin (DCO) — sign your commits with `git commit -s`.

## Maintainers

soundminds.ai is the initial maintainer. The project plans to transition toward community maintainership over 12–24 months. See spec §29 *OSS positioning & governance*.
