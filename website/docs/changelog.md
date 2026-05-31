# Changelog

!!! abstract "Summary"
    Per-release notes live on GitHub Releases. This page keeps a
    human-readable summary of the major version themes; the
    [GitHub Releases](https://github.com/SoundMindsAI/relyloop/releases) page
    is authoritative for the exact change list of each tag.

## Release themes

RelyLoop ships in maturity-gated releases. Each release is themed; the
canonical release matrix lives in the repo's
[`tech-stack.md`](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/tech-stack.md).

For live, auto-generated per-release status, see the [Roadmap](roadmap.md).

| Release | Theme | Status & scope |
|---|---|---|
| **MVP1 / `v0.1`** | The Loop | ✅ Shipped — ES + OpenSearch adapter, OpenAI-compatible LLM, GitHub provider, single-tenant, Optuna/TPE Bayesian loop, Git-PR apply path, conversational agent |
| **MVP2 / `v0.2`** | Three-Engine + Real Signals | 🟡 In progress — Apache Solr adapter + UBI-derived judgments (incl. hybrid UBI + LLM) have landed; remaining MVP2 work in flight |
| **MVP3 / `v0.3`** | Observable | ⬜ Planned — self-hosted observability (Langfuse + SigNoz), audit log, lineage, PII redaction |
| **GA / `v1.0`** | Production-ready | ⬜ Planned — orchestrator hardening, full error model, 90% coverage, security gates — no new product surface |

## Versioning

RelyLoop follows [Semantic Versioning](https://semver.org/). The leading `0.`
signals pre-1.0 instability: expect breaking changes to APIs, schemas, and
adapter contracts between minor releases until `v1.0`.

## Latest release

See [GitHub Releases](https://github.com/SoundMindsAI/relyloop/releases) for
the current tag and its full notes. `v0.1.0` was the first public release;
the project has since tagged subsequent `v0.1.x` releases and is shipping MVP2
work — the [Roadmap](roadmap.md) tracks what's landed.
