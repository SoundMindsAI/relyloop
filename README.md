# RelyLoop

> **Status: pre-MVP1 (private alpha).** Spec is complete; engineering has not started. This repo is currently soundminds.ai-internal; it will become public when MVP1 ships.

**Open-source automated relevance tuning for enterprise search platforms.** RelyLoop combines an LLM-driven agent with an Optuna-driven optimization loop ("Karpathy loop") to systematically tune query-time search relevance on Elasticsearch, OpenSearch, and Lucidworks Fusion. Engineers describe relevance problems in chat; the agent introspects the cluster, proposes a search-space, and queues thousands of trials against pytrec_eval-computed metrics. Winning configurations are surfaced as Pull Requests against a central search-config Git repo, where named approvers review and merge.

## What's in this repo today

This repo currently holds the design artifacts:

- [`relevance-copilot-spec.md`](relevance-copilot-spec.md) — the full 30-section product and architectural specification (~2,800 lines)
- [`mvp1-execution-plan.md`](mvp1-execution-plan.md) — week-by-week plan for the 5-week MVP1 release
- [`LICENSE`](LICENSE) — Apache License 2.0
- [`NOTICE`](NOTICE) — Apache 2.0 NOTICE file with dependency attribution
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — DCO-based contribution guide (forward-looking)
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1

Engineering for MVP1 is described in the execution plan and starts when the pre-flight checklist (TESS, domains, namespaces, design partners) is complete.

## Roadmap at a glance

Five releases, each meaningful as a discrete capability bundle:

| Release | Theme | Time | Audience |
|---|---|---|---|
| MVP1 / v0.1 | The Loop | 5 weeks | Technical evaluators willing to test on a laptop |
| MVP2 / v0.2 | Observable | +3 weeks | Platform teams considering serious evaluation |
| MVP3 / v0.3 | Production Stacks | +3 weeks | Lucidworks shops, GitLab/Bitbucket enterprises |
| MVP4 / v0.4 | Multi-tenant, Multi-LLM | +3 weeks | Platform teams operating for many customers |
| GA v1 / v1.0 | Production-ready | +3 weeks | Production deployments, contributors, the community |

See spec §27 for the full phasing detail.

## Key design choices

- **Engine-agnostic** — Elasticsearch + OpenSearch in MVP1 via one adapter; Lucidworks Fusion in MVP3; pure Solr in v2; adapter pattern enables community-contributed engines
- **Provider-agnostic** — OpenAI in MVP1; Anthropic, AWS Bedrock, Azure OpenAI, Google Vertex, Ollama/vLLM in MVP4
- **Git-as-source-of-truth** — winning configs land as PRs against a central config repo; deployment is the operator's CI's job, not RelyLoop's
- **Local-first observability** — Langfuse + SigNoz both self-hosted; no LLM trace data leaves the deployment VM
- **Multi-tenant from MVP4** — single deployment serves many downstream customers in isolation
- **Agent-first API** — every operation the in-tool orchestrator can perform is also callable by external agents; OpenAPI 3.1, idempotency keys, RFC 7807 errors, outgoing webhooks (no MCP server; idiomatic REST instead)
- **Deliberate, not real-time** — RelyLoop is for offline experimentation and change management; it does not sit on the live search-serving path

See spec §4 (non-goals) and §28 (tech stack) for the full set.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions use the Developer Certificate of Origin (DCO) — sign your commits with `git commit -s`.

## Maintainers

soundminds.ai is the initial maintainer. The project plans to transition toward community maintainership over 12–24 months. See spec §29 *OSS positioning & governance*.
