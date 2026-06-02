# Where RelyLoop fits: the complementary-architecture view

**Status:** Positioning reference. Not normative — it informs how we talk about RelyLoop, not what it does.
**Audience:** Search-engineering teams evaluating whether RelyLoop is worth adopting *regardless of what they run at serving time*.

## The one-line version

No matter what you do at runtime, you still need a well-tuned **query-time baseline**. RelyLoop finds that baseline automatically — thousands of Bayesian trials across the full parameter space — and hands it to you as a reviewable Pull Request. It never touches your serving path, so it can't compete with or constrain whatever you build there.

## The three layers of a search pipeline

Every relevance stack, however modern, separates into three layers. RelyLoop deliberately occupies exactly one of them.

| Layer | What lives here | Who owns it |
|---|---|---|
| **1. Ingest / index-time** | Document enrichment, ETL, analyzers, embeddings, field mapping | **You.** RelyLoop never modifies schema, mappings, or analyzers. |
| **2. Query-time configuration** | Field boosts, function scores, fuzziness, `mm`, tie-breakers, hybrid weights | **RelyLoop** — offline, via Bayesian (Optuna/TPE) optimization, shipped as a Git PR. |
| **3. Runtime / serving** | Reranking, LLM-judge gates, adaptive retries, online learning, RAG, agentic orchestration | **You.** RelyLoop never sits on the live request path. |

Layers 1 and 3 are where teams invest in differentiation — and they vary enormously from team to team. Layer 2 is the connective tissue between them: the query-time config that turns your retrieval into the candidate set everything downstream depends on. It's also the layer that's almost always hand-tuned, one parameter at a time, and rarely re-tuned once "good enough."

## Why this is runtime-agnostic

RelyLoop is **strictly offline and strictly query-time**. That single constraint is what makes it valuable no matter what your serving stack looks like:

- **It's orthogonal to every runtime choice.** Whether your runtime is a reranker, an LLM-as-judge quality gate, an adaptive retry loop, a RAG retriever, an agentic tool call, or nothing at all — none of that changes. RelyLoop tunes the config that *feeds* your runtime; it never participates in serving a request.
- **A better baseline is a better input to whatever runs on top.** Cleaner candidate sets mean fewer runtime retries, less lift your reranker has to manufacture, and a stronger starting point for any adaptive layer. You can only adapt as well as your baseline lets you.
- **It can't become a production dependency.** The output is a config change proposed as a Pull Request — reviewed and merged by your existing approvers, deployed by your existing CI. RelyLoop is never in the request path, never an inline dependency, never a thing that can fall over at 3 a.m.

## What you actually get

- **Full-search-space optimization, not single-parameter grids.** Thousands of trials explore field weights, function scores, fuzziness, `mm`, tie-breakers, and hybrid weights *together*, surfacing interactions a one-knob-at-a-time sweep can't see.
- **One workflow across three engines.** Elasticsearch, OpenSearch, and Apache Solr, behind a single adapter — the same loop, the same UI, the same PR posture on all three.
- **A reviewable apply path.** Winning configs land as Pull Requests against your search-config repo. Your approvers review the diff; your branch protection and CI decide what ships.
- **Apache-2.0, self-hosted.** Runs in your lower environments. Nothing leaves your deployment that you don't choose to send.

## The pitch in one sentence

> Bring your own ingest pipeline and your own runtime — RelyLoop fills the gap in the middle, finding the optimized query-time baseline both of them are built on, and proposing it as a Pull Request you control.
