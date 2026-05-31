---
date: 2026-05-31
authors:
  - relyloop
---

# RelyLoop is public

RelyLoop is now open source under Apache 2.0. It's the only tool that runs
**autonomous, full-search-space Bayesian optimization** across all three major
open-source search engines — Elasticsearch, OpenSearch, and Apache Solr — and
ships the winning configuration as a **Pull Request** to your config repo,
where your existing approvers and CI decide what reaches production.

<!-- more -->

The shape is a Karpathy-style loop — propose, evaluate, select, repeat — with
Optuna's TPE sampler tuning field boosts, function scores, fuzziness, `mm`,
tie-breakers, and hybrid weights together, scored against your judgments with
`ir_measures`. The loop ends at the PR: RelyLoop never sits on the live
search-serving path.

RelyLoop is alpha. MVP1 — the full loop — shipped, and MVP2 is already
underway: the **Apache Solr adapter** and **UBI-derived judgments** (including
the hybrid UBI + LLM mode) have landed. The [Roadmap](../../roadmap.md) tracks
live status. We're single-vendor-stewarded for now and [actively looking to
broaden the maintainer team](../../community/governance.md).

Try the [Quickstart](../../getting-started/quickstart.md), and tell us what
breaks on [GitHub](https://github.com/SoundMindsAI/relyloop).
