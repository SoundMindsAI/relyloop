# Teams thread — RelyLoop announcement (~200 words)

> Companion to the long-form blog at [`2026-05-20-haystack-to-relyloop.md`](2026-05-20-haystack-to-relyloop.md). Paste body below into the Teams channel; the long-form link can point at wherever the blog ends up published (internal wiki / Confluence / external blog).

---

**Quick share — open-source side project I just shipped: RelyLoop**

After three days at Haystack 2026 in Charlottesville earlier this month, I came home and started building. The trigger was Doug Turnbull's talk *AutoReSEARCH – Ranking coded by agents* — itself a deliberate play on Karpathy's [`autoresearch`](https://github.com/karpathy/autoresearch) repo (the "AI agent runs experiments overnight" loop, 82k stars). Doug's talk made the connection click: the same agent-in-a-loop technique can be pointed at search relevance tuning.

So I built **RelyLoop**: an open-source tool that runs offline parameter-search studies against Elasticsearch / OpenSearch / Fusion (Fusion adapter lands in MVP3), scores trials via `pytrec_eval`, and opens a PR against your central search-config repo with the winning config. A human approver merges it; your CI deploys. The tool never sits on the live serving path.

First commit was May 8 — the day after Haystack ended. `v0.1.0` alpha tag five days later. Eighteen features in `main` as of today. Apache 2.0.

📖 Long-form origin story (~10 min read): *[link to wherever the blog gets published]*
🔗 Repo: [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop)

If you've been frustrated with "guess and try" tuning sessions, take a look. Happy to chat about it on a coffee — DM me.
