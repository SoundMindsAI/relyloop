# Quepid

**Vendor:** OpenSource Connections / o19s (Apache 2.0).
**Access date:** 2026-05-31.

The de-facto open-source **interactive relevance workbench**: create test
cases ("cases"/"books"), gather human judgments, compute metrics (nDCG, etc.),
and watch them move as you tweak the query configuration by hand.

**Capabilities (verified 2026-05-31):**

- **Engine support** — OpenSearch, Elasticsearch, Solr, plus Vectara, Algolia,
  and custom Search APIs. (Diagnostics are powered by the shared `splainer-search`
  library.)
- **LLM-as-judge — built into the OSS core.** Quepid ships an **"AI Judge"**
  ("LLM as a Judge") feature, added in **v8.0.0 (2025-02-14)** in the
  open-source repo (not a paid/hosted-only feature). You set an LLM key, supply
  a customizable judgement prompt, and the AI Judge rates query/document pairs.
  Later releases added Ollama support and encrypted key storage (8.2.0). →
  **This corrects the earlier comparison claim that Quepid's LLM-judge was a
  "community plugin, not in the OSS core."**
- **A/B comparison** — yes, but **manual/human-driven**: a person changes the
  query config and compares cases. No automated parameter sweep.
- **Multi-cluster** — yes (multiple cases/configs).
- **Optimization** — none. Quepid does not run automated parameter sweeps or
  Bayesian optimization, and does not write/apply search configs (it manages
  judgments and measurement, not config deployment).

**Why it matters vs RelyLoop:** Quepid is the strongest tool for human-rated
judgment management and manual A/B, and it now applies LLMs to *judging*. But
its LLM use is for judging, not for *driving an optimization loop* — there is
no autonomous sweep and no apply path.

**Upstream URLs:**

- Repo — https://github.com/o19s/quepid
- Changelog (AI Judge debuts v8.0.0) — https://github.com/o19s/quepid/blob/main/CHANGELOG.md
- Product site — https://www.quepidapp.com/
- User manual — https://quepid-docs.dev.o19s.com/
