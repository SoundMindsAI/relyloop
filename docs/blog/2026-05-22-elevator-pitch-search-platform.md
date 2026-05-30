# LinkedIn DM — Haystack friend, expert search engineer

*Use when: DMing someone you met at Haystack 2026 who's an expert search engineer — fluent in BM25 / NDCG and likely to recognize Karpathy's `autoresearch` (though they may need a gentle reminder of the pattern). This is a message about a side project that isn't released yet. The ask is for honest feedback and for their read on whether this would be useful to their organization. No pitch; just looking for signal from a peer.*

---

> Hi — I've been working on an open-source side project since we got back from Haystack, and I wanted to run it by you before it goes anywhere public.
>
> You probably remember Karpathy's `autoresearch` — the idea of an agent that runs experiments overnight against an automated evaluator, keeps the winners, and iterates. I sat in on Doug Turnbull's autoresearch talk on the Wednesday at Haystack, and watching him point that pattern at search ranking specifically was the moment it clicked for me. I'd been turning the idea over for a while, and that talk was what made it concrete. The day after the conference ended, I started building it.
>
> The rough shape is this: an operator describes a relevance problem in chat, the agent introspects the cluster and proposes a query-time search space (BM25 parameters, field boosts, minimum-should-match, tie-breakers — nothing structural like schema or analyzers), and an Optuna TPE sampler runs thousands of trials scored by `ir_measures` against a judgment list. The winning configuration opens as a pull request against the operator's search-config repository. The tool itself never sits on the live serving path. The deploy decision stays with the operator's approvers and their existing CI.
>
> It is not actually released yet. I'm still finishing MVP1, which supports Elasticsearch and OpenSearch first, with Apache Solr coming in MVP2. The license is Apache 2.0 and the repository is already public on GitHub, just not yet announced anywhere.
>
> The real reason I'm reaching out is that I'd genuinely value your feedback on it. And the bigger question I'd like your honest read on is whether this is something that would actually be useful to your organization. If the framing is off, or the scope is wrong, or the whole premise does not match a problem your team actually has, I would much rather hear that from you now than discover it after release.
>
> The repository is at [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop) if you'd like to look around. If a call would be easier than reading through it on your own, I'd be happy to walk you through it instead.

---

**Notes on the choices:**

- Opens on what I've been doing, not on them and not on a hook. A message to a friend does not need a hook; the friendship is the hook.
- The Karpathy reference is a gentle reminder rather than an explanation. A single sentence summarizing the pattern is enough for someone who's heard of `autoresearch` to reload the context, without being condescending if they already have it in mind.
- Doug Turnbull's talk is named because it happened and it mattered, not as a credibility play. The phrasing "I sat in on" works whether they were in the room or not.
- "It is not actually released yet" is the honest state, and it frames everything else correctly. The ask is for a read on a work-in-progress, not for adoption of a finished product.
- Engine support is stated neutrally, without assuming which engine they care about. If a particular engine matters to them, they will ask; if not, the sentence is just neutral information about the state of the project.
- "The real reason I'm reaching out" signals that I'm being direct about the ask. There are two asks, ordered smallest first: feedback (low commitment, anyone can give it) and the organization-fit question (the one I most want answered).
- The organization-fit question is phrased as "would this actually be useful to your organization," not "would your organization buy this" or "would you adopt this." I'm asking for a read on whether the problem RelyLoop solves matches a problem they have. That is a peer question, not a sales question.
- The message deliberately does not speculate about their angle, their role, or how their team tunes in practice. They know their context; I do not. Asking the question cleanly lets them answer from wherever they actually sit.
- "I would much rather hear that from you now than discover it after release" makes negative signal welcome. If they think the scope or framing is wrong, that is the most valuable thing they could tell me.
- The closing offer of a call lowers the activation energy for engagement without asking for a commitment.

**If they reply with a real question, things worth being ready to talk about:**

- Judgments: operator-provided lists, or LLM-as-judge synthesis with calibration overrides. The synthesis path is the interesting one — happy to share how I'm handling drift.
- Search space: the agent proposes it from cluster introspection plus a template library; the operator can edit before trials kick off. Optuna TPE narrows from there.
- Deploy story: there isn't one. Tool ends at the PR. The operator's protected branches + CI own the rest by design.
- Why `ir_measures`: clean typed-metric DSL (nDCG@10, AP@5, RR, P@k, R@k), broad metric coverage, actively maintained by the PyTerrier team.
- Solr: adapter Protocol is already in the spec; ES/OpenSearch shipped first because they were the fastest path to closing the loop end-to-end. Solr is the third adapter, not an afterthought.
- If they ask "how would my org actually use this": the workflow is offline tuning sessions, not continuous. Someone on the team points it at a query set + judgments, lets it grind, reviews the resulting PR, merges if the diff is sane. Sits alongside whatever they already do, not instead of it.
- If they push back on the premise — "we don't actually have a tuning problem worth this" or "our judgments aren't good enough for this to mean anything" — that's the most useful answer they could give. Ask follow-ups, don't defend.

**Companion pieces:**

- Long-form origin story (the full Karpathy → Doug → RelyLoop arc): [`2026-05-20-haystack-to-relyloop.md`](2026-05-20-haystack-to-relyloop.md)
- Teams-channel announcement: [`2026-05-20-haystack-to-relyloop-teams.md`](2026-05-20-haystack-to-relyloop-teams.md)
