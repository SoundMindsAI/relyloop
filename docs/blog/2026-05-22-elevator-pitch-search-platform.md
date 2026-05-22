# 30-second elevator pitch — Search Platform Engineering audience

*Use when: you have ~30 seconds with a relevance engineer, search platform engineer, or anyone who already speaks BM25 / NDCG / config-repo. Assumes the listener knows the relevance-tuning problem space and won't need it explained.*

---

> RelyLoop is an open-source offline relevance tuner for Elasticsearch, OpenSearch, and Fusion. You describe the relevance problem in chat; an agent introspects the cluster, defines a parameter search space, and runs thousands of Optuna trials scored by `pytrec_eval` against your judgments. The winner opens as a PR against your search-config repo — your existing approver flow and CI deploy it. It never sits on the serving path. Think "overnight tuning loop that produces a reviewable diff" instead of guess-and-eyeball.

---

**Why this version works for platform engineers:**

- Trades on terms they already own — Optuna, `pytrec_eval`, NDCG-shaped scoring, config-repo, CI deploy — so no glossary tax.
- Lands the safety property up front: *"never sits on the serving path."* This is the first question a platform engineer asks about any tuning tool, and answering it unprompted earns the next 30 seconds of attention.
- Frames the output as a PR, not a config push. Platform engineers care about deploy discipline; "we open a PR against your repo, you merge it" maps onto an existing mental model.
- Contrasts explicitly with the status quo (*"instead of guess-and-eyeball"*). The listener has lived this; naming it is the hook.

**If they want more, the natural follow-ons:**

- *"Where do the judgments come from?"* → Operator-provided judgment lists, or LLM-as-judge synthesis with calibration overrides.
- *"What does it tune?"* → Query-time parameters only — BM25 knobs, field boosts, minimum-should-match, tie-breakers. Never schema, mapping, or analyzers.
- *"How does the agent know what to try?"* → Cluster introspection + a TPE sampler that narrows the search space over thousands of trials.
- *"What's the license / repo?"* → Apache 2.0, [github.com/SoundMindsAI/relyloop](https://github.com/SoundMindsAI/relyloop), `make up` boots the whole stack.

**Companion pieces:**

- Long-form origin story: [`2026-05-20-haystack-to-relyloop.md`](2026-05-20-haystack-to-relyloop.md)
- Teams-channel announcement: [`2026-05-20-haystack-to-relyloop-teams.md`](2026-05-20-haystack-to-relyloop-teams.md)
