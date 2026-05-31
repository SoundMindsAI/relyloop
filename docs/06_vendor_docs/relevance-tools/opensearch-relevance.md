# OpenSearch relevance tooling (SRW + Relevance Agent)

**Vendor:** OpenSearch project (Apache 2.0).
**Access date:** 2026-05-31. **Latest version reviewed:** OpenSearch 3.6.

Two distinct, related products ship under the OpenSearch umbrella. RelyLoop is
compared against both.

---

## OpenSearch Search Relevance Workbench (SRW)

A Dashboards-based workbench for evaluating and comparing search
configurations. The closest competitor to RelyLoop.

**Capabilities (verified 2026-05-31):**

- **Query sets, judgments, experiments** — sampling test queries, managing
  relevance ratings, and comparing configurations with metrics. New metrics
  added through 3.5/3.6: Recall@K, MRR, DCG@K.
- **LLM-as-judge** — GA in 3.5; customizable prompts; requires a configured
  LLM connector.
- **UBI-derived judgments** — COEC click model, GA.
- **Scheduled experiments** — nightly/weekly cadence, GA in 3.5.
- **Multi-datasource** — run experiments across multiple sources, added 3.6.
- **Hybrid Search Optimizer** — a **grid search**, not Bayesian. The "Global"
  optimizer tests **66 combinations** = `{2 normalization × 3 combination ×
  11 weight steps}`, over **hybrid lexical/neural weights only** — not field
  boosts or broader query-time parameters. A separate "Dynamic" optimizer
  (ML regression / random forest to predict per-query "neuralness") and the
  grid optimizer both live in an **external o19s notebook repository**, not as
  built-in OpenSearch features. Bayesian optimization is listed as
  **"not yet implemented"** in that repo and is tracked in
  [RFC #934](https://github.com/opensearch-project/neural-search/issues/934).
- **Apply path** — none. The SRW RFC scopes the product to evaluation and
  analysis (query sets / judgments / experimentation); it does not describe
  applying winning configs to production, promoting settings, or managing
  rollouts. No PR/Git apply mechanism.

**Why it matters vs RelyLoop:** SRW is the most feature-complete competitor,
but (1) its optimizer is a 66-cell grid over hybrid weights, versus RelyLoop's
Optuna/TPE Bayesian search over the full query-time space; (2) it has no
apply path; (3) it is OpenSearch-only.

**Upstream URLs:**

- Workbench docs — https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/
- Hybrid search optimizer docs — https://docs.opensearch.org/latest/search-plugins/search-relevance/optimize-hybrid-search/
- Optimization blog — https://opensearch.org/blog/hybrid-search-optimization/
- External optimizer notebooks (o19s) — https://github.com/o19s/opensearch-hybrid-search-optimization
- Judgments (COEC) — https://docs.opensearch.org/latest/search-plugins/search-relevance/judgments/
- SRW scope RFC #17735 — https://github.com/opensearch-project/OpenSearch/issues/17735
- Hybrid optimizer RFC #934 — https://github.com/opensearch-project/neural-search/issues/934
- Repo — https://github.com/opensearch-project/search-relevance
- 3.5 / 3.6 release notes — https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.5.0.md · https://github.com/opensearch-project/opensearch-build/blob/main/release-notes/opensearch-release-notes-3.6.0.md

---

## OpenSearch Relevance Agent

An **experimental** (3.6) conversational, agent-driven tuning system in
OpenSearch Dashboards. A separate product from SRW.

**Capabilities (verified 2026-05-31):**

- A **multi-agent, hypothesis-driven** workflow: a User-Behavior-Analysis agent
  identifies relevance gaps (from UBI data or query patterns), a
  Hypothesis-Generator agent proposes tuning strategies, and an Evaluator agent
  validates them via **offline evaluation on historical data**.
- Produces **query-DSL-level optimizations** — refining search fields,
  adjusting weights, tuning boost functions. Human-in-the-loop ("you remain the
  ultimate decision-maker").
- **Does not** run large automated parameter sweeps or Bayesian optimization,
  and **does not** apply changes to production (online/interleaving tests are
  listed as future work).

**Why it matters vs RelyLoop:** it's conversational like RelyLoop's chat agent,
but it recommends/validates DSL changes one hypothesis at a time rather than
running thousands of Bayesian trials, and it is OpenSearch-only with no
Git-PR apply path.

**Upstream URL:** https://opensearch.org/blog/introducing-opensearch-relevance-agent-ai-powered-search-tuning/
