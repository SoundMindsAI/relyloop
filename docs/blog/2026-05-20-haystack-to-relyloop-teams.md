# Teams thread — RelyLoop announcement (~250 words)

> Companion to the long-form blog at [`2026-05-20-haystack-to-relyloop.md`](2026-05-20-haystack-to-relyloop.md). Paste the body below into the Teams channel; the long-form link can point at wherever the blog ends up published (internal wiki / Confluence / external blog).

---

> I've been working on an open-source side project since Haystack 2026 in Charlottesville earlier this month, and I wanted to share where it's landed.
>
> The trigger was Doug Turnbull's talk *AutoReSEARCH – Ranking coded by agents*. He'd taken Karpathy's [`autoresearch`](https://github.com/karpathy/autoresearch) idea — an AI agent that runs experiments overnight against an automated evaluator and keeps the winners — and pointed it at search relevance tuning specifically. That was the architectural connection I'd been turning over for a while, and watching him present it was the moment it locked in.
>
> The tool I started building the day after Haystack ended is called **RelyLoop**. It is open-source under Apache 2.0. An operator describes a relevance problem in chat; an agent introspects the cluster, proposes a query-time search space (BM25 parameters, field boosts, minimum-should-match, tie-breakers — nothing structural), and an Optuna TPE sampler runs thousands of trials scored by `ir_measures` against a judgment list. The winner opens as a pull request against the operator's search-config repo. A human approver merges it; the operator's CI deploys it. The tool itself never sits on the live serving path.
>
> First commit was May 8 — the day after Haystack ended. `v0.1.0` alpha tag five days later. It is still in active development; not ready for production use. Elasticsearch and OpenSearch first; Lucidworks Fusion lands in MVP3.
>
> Long-form origin story (~10 min read): *[link to wherever the blog gets published]*
> Repo: [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop)
>
> If the problem space lines up with anything you're working on, I'd genuinely value a read on it. DM me, or grab a coffee.
