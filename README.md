# RelyLoop

> **Status: alpha (MVP1, v0.1.0).** Open-source automated relevance tuning for enterprise search platforms.

RelyLoop combines an LLM-driven chat agent with an Optuna-driven optimization
loop ("Karpathy loop") to systematically tune query-time relevance on
Elasticsearch and OpenSearch. Engineers describe the problem in chat; the
agent introspects the cluster, proposes a search-space, and runs thousands
of trials against `ir_measures`-computed metrics. Winning configurations
land as Pull Requests against a central search-config Git repo, where named
approvers review and merge.

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
chat agent, Optuna optimizer, LLM-as-judge, digest, GitHub PR worker, single-
tenant install. Observable / Production Stacks / Multi-tenant land in MVP2 →
MVP3 → MVP4.

Canonical release matrix:
[`docs/01_architecture/tech-stack.md`](docs/01_architecture/tech-stack.md) —
do not duplicate here, the matrix is the source of truth.

## Key design choices

- **Engine-agnostic** — Elasticsearch + OpenSearch in MVP1 via one adapter; Lucidworks Fusion in MVP3; pure Solr in v2.
- **Provider-agnostic** — OpenAI in MVP1; Anthropic, AWS Bedrock, Azure OpenAI, Vertex, Ollama / vLLM in MVP4.
- **Git-as-source-of-truth** — winning configs land as PRs against a central config repo; deployment is the operator's CI's job, not RelyLoop's.
- **Local-first observability** — Langfuse + SigNoz both self-hosted (MVP2+); no LLM trace data leaves the deployment VM.
- **Multi-tenant from MVP4** — single deployment serves many downstream customers in isolation.
- **Agent-first API** — every operation the in-tool orchestrator can perform is also callable by external agents; OpenAPI 3.1, idempotency keys, RFC 7807 errors, outgoing webhooks.
- **Deliberate, not real-time** — RelyLoop is for offline experimentation and change management; it does not sit on the live search-serving path.

See spec §4 (non-goals) for the full set.

## How RelyLoop fits with other relevance tools

RelyLoop is not the first tool in the search-relevance space and does not try
to replace the tools already there. It sits alongside Quepid (interactive
workbench), the OpenSearch Relevance Agent (in-cluster automated tuning for
OpenSearch-only shops), Chorus (reference integration stack), SMUI + Querqy
(query-rewriting rules), Elasticsearch / Solr LTR (reranker model training),
OpenSearch UBI (real user signals), and the rest of the open-source relevance
ecosystem.

The slice RelyLoop owns is **autonomous, engine-agnostic, Git-PR-mediated
query-time parameter tuning** — useful when you operate Elasticsearch or both
ES + OpenSearch, want production config changes to flow through a Pull
Request reviewed by named approvers, run multiple clusters / environments,
or eventually want one tool that spans engines.

The full breakdown — honest assessment of where each adjacent tool fits,
where RelyLoop fits, and the pairing patterns we recommend — is in
[`docs/00_overview/adjacent-tools.md`](docs/00_overview/adjacent-tools.md).

## Links

- Tutorial: [`docs/08_guides/tutorial-first-study.md`](docs/08_guides/tutorial-first-study.md)
- Umbrella spec: [`docs/00_overview/relyloop-spec.md`](docs/00_overview/relyloop-spec.md)
- Architecture index: [`docs/01_architecture/`](docs/01_architecture/)
- Local-dev runbook: [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md)
- Release checklist (maintainers): [`docs/03_runbooks/release-checklist.md`](docs/03_runbooks/release-checklist.md)
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, branching, and PR conventions. Contributions use the Developer Certificate of Origin (DCO) — sign your commits with `git commit -s`. Be kind ([CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)).

## Security

Vulnerabilities go through [SECURITY.md](SECURITY.md), not public issues.

## Governance and maintainers

- Current maintainers: [MAINTAINERS.md](MAINTAINERS.md). At v0.1, all maintainers are soundminds.ai employees — stated openly so the bus factor is visible.
- How decisions are made + the plan to grow the maintainer set across organizations: [GOVERNANCE.md](GOVERNANCE.md). The transition target is 12–24 months from MVP1's first stable release.
