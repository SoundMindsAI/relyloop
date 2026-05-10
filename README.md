# RelyLoop

> **Status: MVP1 in progress (private alpha).** Spec is complete; the foundation feature (`infra_foundation`) is in review (PR #4) — Docker stack, FastAPI + `/healthz`, OpenAI capability check, Alembic baseline, CI workflow, 90% measured backend coverage against an 80% gate. The next 11 MVP1 features are spec-approved and queued. This repo is currently soundminds.ai-internal; it will become public when MVP1 ships.

**Open-source automated relevance tuning for enterprise search platforms.** RelyLoop combines an LLM-driven agent with an Optuna-driven optimization loop ("Karpathy loop") to systematically tune query-time search relevance on Elasticsearch, OpenSearch, and Lucidworks Fusion. Engineers describe relevance problems in chat; the agent introspects the cluster, proposes a search-space, and queues thousands of trials against pytrec_eval-computed metrics. Winning configurations are surfaced as Pull Requests against a central search-config Git repo, where named approvers review and merge.

## Quickstart

```bash
git clone https://github.com/SoundMindsAI/relyloop.git
cd relyloop

# 1. Install dev toolchain
uv sync                          # Python deps + .venv (requires Python 3.12+)
pnpm --dir ui install            # frontend deps (requires Node 20+ + pnpm 9+)
make pre-commit-install          # install Git hooks

# 2. Bring up the stack
make up                          # auto-generates secrets, then docker compose up -d
                                 # ~90s cold (image pulls), ~60s warm

# 3. Apply migrations + seed local clusters
make migrate                     # applies the alembic chain (incl. 0002_clusters_config_repos)
make seed-clusters               # registers local-es + local-opensearch (idempotent)

# 4. Verify
curl -s http://localhost:8000/healthz | jq    # status: ok, all subsystems reachable
                                              # subsystems.elasticsearch_clusters.registered: 2

# 5. (Optional) populate OpenAI key for the capability check
echo "sk-..." > ./secrets/openai_key
make down && make up             # re-runs the 4-step capability check at startup
```

`make` (no target) prints every Make target with descriptions. Full operator
walkthrough — debugging, port collisions, ES OOMs, the `make reset` flow, the
operator setup checklist — lives in
[`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md).

**Hardware:** 16 GB RAM is comfortable. Elasticsearch + OpenSearch each
consume ~1 GB; bump `ES_HEAP_SIZE` in `.env` if you index large corpora.

## What's in this repo today

The bootstrap (`infra_foundation`) has shipped. The repo now holds:

**Code (MVP1 Stories 1.1 → 5.2):**

- [`backend/app/`](backend/app/) — FastAPI skeleton + `/healthz` + structlog +
  request-ID middleware + error envelope + Settings (mounted-secret pattern) +
  async SQLAlchemy engine + OpenAI capability check
- [`backend/workers/`](backend/workers/) — Arq worker stub
  (`functions=[]` until later features add jobs)
- [`backend/tests/`](backend/tests/) — unit / integration / contract layers (90% backend coverage)
- [`migrations/`](migrations/) — Alembic baseline (`0001_baseline`)
- [`ui/`](ui/) — Next.js 14 placeholder page (real shell lands with `feat_studies_ui`)
- [`Dockerfile`](Dockerfile) + [`docker-compose.yml`](docker-compose.yml) +
  [`.env.example`](.env.example) + [`scripts/install.sh`](scripts/install.sh) — the 6-service stack
- [`.github/workflows/pr.yml`](.github/workflows/pr.yml) + [`.github/dependabot.yml`](.github/dependabot.yml) — CI gates

**Design artifacts:**

- [`docs/README.md`](docs/README.md) — documentation index and section map
- [`docs/00_overview/product/relevance-copilot-spec.md`](docs/00_overview/product/relevance-copilot-spec.md) — the full 30-section product and architectural specification (~2,800 lines)
- [`docs/02_product/mvp1-user-stories.md`](docs/02_product/mvp1-user-stories.md) — MVP1 broken into 31 user stories mapped to 12 feature folders
- [`docs/02_product/planned_features/`](docs/02_product/planned_features/) — per-feature spec folders (`infra_foundation` will move to `docs/00_overview/implemented_features/` on merge; the next 11 are spec-approved and queued)
- [`state.md`](state.md) · [`architecture.md`](architecture.md) · [`CLAUDE.md`](CLAUDE.md) — project context root files
- [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md) — local boot, debug, reset
- [`docs/05_quality/testing.md`](docs/05_quality/testing.md) — test layers + 80% coverage gate

**Open-source housekeeping:**

- [`LICENSE`](LICENSE) — Apache License 2.0
- [`NOTICE`](NOTICE) — Apache 2.0 NOTICE file with dependency attribution
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — DCO-based contribution guide
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1

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
