# Elasticsearch (native relevance tooling)

**Vendor:** Elastic. **License:** Elastic License 2.0 + SSPL (not OSI open
source); feature gating by subscription tier.
**Access date:** 2026-05-31. **Latest major reviewed:** Elasticsearch 9.x.

What Elasticsearch ships *natively* for relevance evaluation/tuning — distinct
from third-party tools that run against it.

**Capabilities (verified 2026-05-31):**

- **`_rank_eval` API** — an evaluation **primitive** (computes MRR, precision,
  DCG/nDCG over a query set + rated docs). Available in the **Basic** tier. It
  is an API, not a UI/workbench, and it is **not deprecated** in 9.x.
- **No native SRW/RelyLoop equivalent.** Elastic **deprecated** its
  higher-level **Behavioral Analytics** and **Search Applications** in
  **9.0.0** (Behavioral Analytics emits deprecation warnings; **App Search is
  discontinued** with Stack 9.0 and Enterprise Search ships no new majors past
  8.x). Search Applications + Behavioral Analytics required a paid tier
  (trial/Platinum/Enterprise) even before deprecation.
- **Learning to Rank (LTR)** — Elasticsearch supports **model inference** for
  LTR (GBDT/LambdaMART; training happens outside ES). LTR + ML inference are
  **paid-tier** features (Platinum or higher), not Basic.
- **Subscription tiers (2026):** Free/Basic, Gold (Elastic Cloud Hosted only),
  Platinum, Enterprise.
- **Optimization / apply path** — none native. No automated sweep, no Bayesian
  search, no Git-PR apply.

**Why it matters vs RelyLoop:** ES gives you the evaluation primitive
(`_rank_eval`) but no optimizer, no workbench (the higher-level products are
deprecated), and its advanced ranking (LTR) is paywalled. RelyLoop runs
against ES (Apache-2.0) and adds the loop + apply path on top.

**Upstream URLs:**

- 9.0 release notes (deprecations) — https://www.elastic.co/guide/en/elastic-stack/9.0/release-notes-elasticsearch-9.0.0.html
- `_rank_eval` — https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval
- LTR — https://www.elastic.co/docs/solutions/search/ranking/learning-to-rank-ltr
- Subscriptions / tiers — https://www.elastic.co/subscriptions
