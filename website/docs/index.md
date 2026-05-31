---
title: RelyLoop
hide:
  - navigation
  - toc
---

# Autonomous relevance optimization for enterprise search

RelyLoop runs thousands of Bayesian optimization trials across the **full
query-time search space** of your Elasticsearch, OpenSearch, or Apache Solr
cluster, evaluates each trial against your judgments, and ships the winning
configuration as a **Pull Request** to your config repo — where your existing
approvers and CI decide what reaches production. It never sits on the live
search-serving path.

[Get started :material-arrow-right:](getting-started/install.md){ .md-button .md-button--primary }
[View on GitHub :fontawesome-brands-github:](https://github.com/SoundMindsAI/relyloop){ .md-button }

!!! info "Status: alpha · MVP2 in progress · Apache-2.0"
    MVP1 (the full loop) shipped, and MVP2 is underway — the **Apache Solr
    adapter** and **UBI judgments** have already landed. See the
    [Roadmap](roadmap.md) for live status and
    [GitHub Releases](https://github.com/SoundMindsAI/relyloop/releases) for the
    current version. APIs and schemas are still evolving — expect breaking
    changes between minor releases until v1.0.

---

## Why RelyLoop

<div class="grid cards" markdown>

-   :material-sync:{ .lg .middle } __An autonomous loop, not a grid__

    ---

    A Karpathy-style loop — propose, evaluate, select, repeat — driven by
    Optuna's TPE sampler over **thousands** of trials. It tunes field boosts,
    function scores, fuzziness, `mm`, tie-breakers, and hybrid weights
    together, not a single slice in isolation.

-   :material-database-search:{ .lg .middle } __One workflow, three engines__

    ---

    Elasticsearch, OpenSearch, and Apache Solr behind a single
    `SearchAdapter` Protocol. One UI, one schema, one optimization loop —
    the engine is a configuration detail, not a fork in your tooling.

-   :material-source-pull:{ .lg .middle } __Git is the source of truth__

    ---

    Winning configs land as Pull Requests against your central config repo.
    Your named approvers merge; your CI deploys. RelyLoop's job ends at the
    PR — no agent on the serving path, no surprise production changes.

</div>

## Who it's for

- **Relevance engineers** who tune query-time parameters by hand today and
  want a loop that searches the space far wider than a person can.
- **Search platform teams** running multiple clusters or environments who
  want config changes to flow through a reviewed, auditable Pull Request.
- **Relevance consultants** who work across engines and want one tool that
  spans Elasticsearch, OpenSearch, and Solr instead of three.

## How it compares

RelyLoop is not the first tool in this space and doesn't try to replace the
ones already there. The difference is **the loop itself**. Quepid is a superb
interactive workbench — but a human drives every iteration. The OpenSearch
Relevance Agent recommends configurations conversationally — but doesn't run
multi-thousand-trial sweeps. OpenSearch's Hybrid Search Optimizer is a fixed
66-cell grid over hybrid weights, with no apply path by explicit RFC decision.

RelyLoop instead runs a **[Karpathy-style optimization loop](concepts/optimization-loop.md)** —
propose, evaluate, select, repeat — *autonomously*, across thousands of
Bayesian trials over the full query-time search space, on all three major OSS
engines, ending each run as a reviewable Pull Request. None of the others
close that loop and hand off through Git; that combination is what RelyLoop
owns. The full, citation-backed matrix lives in the repo's [comparison
doc](https://github.com/SoundMindsAI/relyloop/blob/main/docs/07_research/comparison.md).
