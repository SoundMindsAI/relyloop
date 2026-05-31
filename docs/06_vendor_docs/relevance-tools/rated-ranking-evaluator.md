# Rated Ranking Evaluator (RRE)

**Vendor:** Sease Ltd (Apache 2.0).
**Access date:** 2026-05-31.

An **offline search-quality evaluation** library/toolkit for Apache Solr and
Elasticsearch. Aimed at the search engineer's CI workflow.

**Capabilities (verified 2026-05-31):**

- **Engine support** — Apache Solr + Elasticsearch.
- **How you run it** — primarily a **Java library invoked via a Maven plugin**
  (set up a Maven project, import RRE, run the evaluation); there is also an
  RRE Server (web console). A standalone **CLI is in development / not part of
  the current release** — so "CLI-driven" overstates it; "Maven-plugin / CI-driven"
  is accurate.
- **A/B comparison / evaluation** — yes, offline; compares rankings across
  configurations/versions and computes IR metrics.
- **Scheduled / unattended** — via CI/cron driving the Maven build (not a
  built-in scheduler).
- **Optimization** — none. RRE evaluates and reports; it does not run automated
  parameter sweeps, is not LLM-driven, and has no apply path.

**Why it matters vs RelyLoop:** RRE is a mature offline evaluation harness for
the Solr/ES world, but it's a measurement tool, not an optimizer — no Bayesian
search, no LLM, no Git-PR apply.

**Upstream URLs:**

- Repo — https://github.com/SeaseLtd/rated-ranking-evaluator
- Wiki — https://github.com/SeaseLtd/rated-ranking-evaluator/wiki
- Overview — https://sease.io/2021/01/offline-search-quality-evaluation-rated-ranking-evaluator-rre.html
