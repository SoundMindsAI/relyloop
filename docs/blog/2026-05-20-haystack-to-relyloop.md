# From Karpathy's Autoresearch to RelyLoop: My Haystack 2026 Story

*Published: 2026-05-20*

I spent three days at [Haystack 2026](https://haystackconf.com/) in Charlottesville this May. I came home and started building. On May 8 — the day after the conference ended — I pushed the first commit of a new open-source tool called RelyLoop. Twelve days later there are eighteen features in the main branch and a `v0.1.0` alpha tag. This is the story of why it happened the way it did.

## The pre-existing itch

I work as an engineer on an Enterprise Search Platform team. Most days my job involves the same kind of conversation that, judging by every Haystack hallway I've ever stood in, a thousand other relevance engineers have: someone reports that a specific search app is returning sub-optimal results for a specific query, and we go in and tune.

The honest description of how that tuning works, across our industry, is this: you take a guess at a config change and try it out. You eyeball a few queries. You ask a stakeholder if the new results "look better." If they do, you commit. If they don't, you guess again.

It's not because the people doing the work are sloppy. It's because the alternative — running structured offline experiments against scored judgment lists, with thousands of parameter combinations, evaluated by rigorous IR metrics — requires infrastructure that nobody on a typical relevance team has time to build. You can do it manually for one tuning task. You can't do it as a sustainable practice.

So you guess. And every relevance engineer I've talked to suspects, quietly, that the configs we ship are working but not optimized. There's a better one in the parameter space. We just don't have a tool that can find it.

## The Karpathy Loop, in the abstract

A few months before Haystack, I'd been reading about a thing I'd started thinking of as the "Karpathy Loop." The clearest version is in Andrej Karpathy's [`autoresearch`](https://github.com/karpathy/autoresearch) repo — a now-82k-star project where an AI agent runs experiments overnight on a single GPU, modifies training code, evaluates the result against a metric, keeps or discards, and repeats. The README opens with a striking framing: *"One day, frontier AI research used to be done by meat computers... that era is long gone."*

What stuck with me wasn't the LLM-training application. What stuck was the *technique*: an agent, in a feedback loop, with an automated evaluator, iterating overnight. The loop closes because the evaluator is fast and the search space is big. The agent doesn't have to be smarter than a human researcher — it just has to be tireless and structured.

I remember reading that and thinking: this is the missing piece for relevance tuning. We have the evaluator — decades of IR literature on how to score a run, plus libraries like `ir_measures` that compute NDCG, MAP, MRR off the shelf. We have the search space — every BM25 parameter, every field boost, every minimum-should-match, every tie-breaker on every analyzer. What we don't have is an agent, in a loop, willing to grind.

But I didn't know how to build it. I had the seed without the architecture. How would the agent actually plug into a real search engine? Where would the judgments come from? What does "winning" mean for a config that wins by 0.04 NDCG on one query set? How does a config that won offline actually get shipped to production without taking down a search app?

## Doug's talk, and the click

That's the context in which, on the afternoon of May 6, I sat down in the Main Stage room at Haystack and watched Doug Turnbull (SoftwareDoug LLC) present [*AutoReSEARCH – Ranking coded by agents*](https://haystackconf.com/session/search-rankers-coded-by-agents/).

The title was a deliberate play on Karpathy's repo. The technical case was clean: give an AI coding agent the basic retrieval primitives — BM25, vector similarity, query-category features — and let it iteratively generate ranking functions, testing each one against a held-out evaluation set. Doug walked through what worked, what didn't, where traditional search experience still mattered, and where it fell apart. The honest framing of it as an experiment, not a sales pitch, was what made it land.

But the bigger thing that happened in that talk wasn't the specific technique. It was the realization that the Karpathy Loop and the relevance-tuning problem could actually fit together. Doug had taken Karpathy's "agent runs experiments overnight" framing and pointed it at search ranking. That was the missing architectural connection I'd been turning over.

The talk wasn't the only thing. Haystack week is dense — hallway conversations about LLM-as-judge calibration, talks on evaluation methodology I won't try to summarize fairly here, the cumulative effect of three days surrounded by people who think about relevance for a living. By Thursday evening I was scribbling architecture diagrams on hotel paper. The Karpathy seed plus Doug's pointer plus the daily relevance-tuning frustration plus everything else I absorbed that week — they all locked in.

## What I started building

On May 8, two days after Doug's talk, I pushed the first commit of RelyLoop. Thirteen minutes later I pushed the second commit: a design spec, an MVP1 plan, and the open-source scaffolding. The architecture was on paper before midnight.

The product, in one paragraph: a relevance engineer describes a problem in chat. An LLM agent introspects the cluster and proposes a parameter search space. An Optuna TPE sampler runs thousands of trials against a judgment list — judgments either provided by the operator or synthesized by an LLM-as-judge worker — and scores each trial through `ir_measures`. The winning configuration becomes a Pull Request against the operator's central search-config repository. A human approver merges it. The operator's existing CI deploys it. RelyLoop never sits on the live search-serving path, never runs online A/B tests, never modifies cluster schema or analyzers. It tunes query-time parameters offline and gets out of the way.

That last constraint is load-bearing. The reason it's an offline tool that produces PRs instead of an online tuner that auto-deploys is that the deploy decision belongs to the operator, on their own protected branches, in their own CI. RelyLoop's job ends at the PR.

The architecture is engine-agnostic by design. The initial release supports Elasticsearch and OpenSearch via a shared adapter; **Apache Solr lands in MVP2**, completing the three supported OSS engines. The same adapter pattern abstracts LLM providers (OpenAI today, Anthropic / Bedrock / Vertex / self-hosted Ollama later) and Git providers (GitHub now; GitLab and Bitbucket later). No part of the system is structurally coupled to a vendor — RelyLoop is intentionally a tool that complements whatever search stack a team already runs.

## Where it is, twelve days in

As of today, May 20, 2026, there are eighteen features merged into `main`. A `v0.1.0` alpha tag was cut on May 13 — five days after the first commit. The project is Apache 2.0. The repo lives at [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop) — `SoundMindsAI` is my open-source identity.

The cadence isn't a stunt. It works because the architecture is small (four cooperating layers — adapter, domain, service, API+UI), because the test layers are disciplined (every endpoint has a contract test, every service an integration test, every domain function a unit test, with an 80% coverage gate on backend Python), and because the project is meant to do one thing well. RelyLoop is not a competitor to any vendor stack or a replacement for one; it's a tool that a relevance team can run alongside their existing platform to make tuning sessions less of a guess.

If you're a relevance engineer who's tired of guessing at configs, the easiest ways to engage:

- **Try it.** `make up` boots the entire stack via Docker Compose. The [tutorial](https://github.com/SoundMindsAI/relyloop/blob/main/docs/08_guides/tutorial-first-study.md) walks from clone → first PR in about thirty minutes.
- **Star the repo** if the idea resonates — it helps other relevance engineers find it.
- **Contribute.** The project is genuinely open. The roadmap is public on the [MVP1 dashboard](https://github.com/SoundMindsAI/relyloop/blob/main/docs/00_overview/MVP1_DASHBOARD.md) and [MVP2 dashboard](https://github.com/SoundMindsAI/relyloop/blob/main/docs/00_overview/MVP2_DASHBOARD.md), and the contribution flow is the standard PR-with-CI dance. Issues, bug reports, and adapter requests are all welcome.

Mostly, though, I want to give credit where it's due. The lineage that produced RelyLoop is direct: Andrej Karpathy framed the loop in `autoresearch`, Doug Turnbull pointed it at search ranking in `AutoReSEARCH – Ranking coded by agents`, and the Haystack 2026 community gave me three days of dense context in which all the pieces locked together. RelyLoop is what I built when I stopped waiting for someone else to build it.

If you've been waiting too, the code is there.

---

**Links**

- Repo: [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop)
- Doug Turnbull's Haystack 2026 talk: [*AutoReSEARCH – Ranking coded by agents*](https://haystackconf.com/session/search-rankers-coded-by-agents/)
- Karpathy's `autoresearch`: [github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)
- Haystack Conference: [haystackconf.com](https://haystackconf.com/)
