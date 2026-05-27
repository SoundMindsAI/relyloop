# Quick tour — what RelyLoop does, in 10 minutes

A short, click-through tour for a search-relevance engineer who has never
seen the product. Skips the operator setup ceremony (registering a cluster,
importing samples, generating judgments) and goes straight to the value
prop: **the overnight optimization loop, the metric lift it produces, and
the PR-based ship discipline that wraps it.**

If you want the hands-on 30-minute end-to-end including setup, follow
[`tutorial-first-study.md`](tutorial-first-study.md) instead. Use this
guide when you want a quick narrative tour against pre-baked data.

<!-- presenter: this is the right artifact for a "show me what it does"
     conversation. The setup section pre-bakes one study with a believable
     +18% lift; the rest of the guide is pure value-prop. -->

---

## Before you start

You need:

- The stack up: `make up`, `make migrate`, `make seed-clusters`, `make seed-es`
  (these populate two clusters and 1,000 sample products — see
  [`tutorial-first-study.md`](tutorial-first-study.md) Steps 1–4 for details)
- One LLM provider configured (OpenAI key OR a local model per `tutorial-first-study.md` Step 0)

Then run the demo seed:

```bash
make seed-demo FORCE=1
```

This seeds four realistic demo scenarios (e-commerce, knowledge base,
news, jobs) and **runs a real 12-trial Optuna study against each one**
with a fixed seed (`config.seed=42`). Each study queries the local
Elasticsearch / OpenSearch backing store, scores against the real
judgment list, generates a real LLM-written digest, and creates a
pending proposal. Takes 3–4 minutes total. Idempotent: re-running
with the same seed produces the exact same metric values (verified —
0.7305 / 0.9060 reproduce to the digit run after run).

> **What's "real" here:** the metric values, the parameter importance,
> the digest narrative, and the suggested followups all emerge from
> the actual study data — no hardcoded fixtures. The trade-off is that
> the demo sample data is small (5 docs and 5–10 judgments per
> scenario), so some scenarios may show a saturated metric ceiling
> (`best_metric=1.0`) instead of a headline lift. The system honestly
> reports "no headroom on this knob" when the data is too sparse to
> support tuning — that's a feature, not a bug.

**Recommended demo target:** the **acme-products-prod** scenario. Its
template declares two tunable knobs (`title_boost` + `description_boost`),
so the digest produces a populated parameter-importance breakdown and
usually generates an actionable `narrow` followup card for Stops 4 / 5.
The acme cluster also has a second template seeded (`function-score-recency-decay-v1`)
so the LLM has a candidate it CAN suggest as a swap_template followup
when the data warrants.

When the script finishes, find the acme-products proposal URL with:

```bash
ACME_CLUSTER=$(docker compose exec -T postgres psql -U relyloop -d relyloop -At \
  -c "SELECT id FROM clusters WHERE name='acme-products-prod'")
ACME_PROPOSAL=$(docker compose exec -T postgres psql -U relyloop -d relyloop -At \
  -c "SELECT id FROM proposals WHERE cluster_id='$ACME_CLUSTER' AND status='pending' ORDER BY created_at DESC LIMIT 1")
echo "Open: http://localhost:3000/proposals/$ACME_PROPOSAL"
```

Keep that URL open in a tab; you'll visit it at Stop 3. Also keep
[`http://localhost:3000/studies`](http://localhost:3000/studies) open
for Stop 1.

<!-- presenter: if `make seed-demo` fails with "api container is not
     running", you skipped `make up`. If it succeeds but you see no
     studies on /studies, check `make logs` — seed_meaningful_demos
     prints a per-scenario summary as it runs. -->
<!-- presenter: re-running `make seed-demo` against unhealthy ES
     scenarios (the FOUR seeded clusters all point at the same local
     ES — they share one healthy backend) will succeed only if local-es
     is reachable. Check `curl -s http://localhost:8000/healthz | jq
     .subsystems.elasticsearch_clusters` first — if all 4 say
     `unreachable`, fix that before running seed-demo (the studies
     will fail with CLUSTER_UNREACHABLE before producing any trials). -->
<!-- presenter: the digest worker's followup choice is LLM-driven and
     may produce text-kind only when the data doesn't show much
     variance. If Stop 4's panel shows only text (no Run buttons),
     skip Stop 5 and emphasize the digest narrative + parameter
     importance at Stop 3 instead. -->

---

## Stop 1 — `/studies` — "what the loop did overnight"

Open [`http://localhost:3000/studies`](http://localhost:3000/studies).

The studies table shows the four scenarios `make seed-demo` produced.
Each row is a real, completed 12-trial Optuna study with its own metric
value — not a hardcoded fixture. Values you'll typically see on the
local-sample data:

| Scenario | Best metric (ndcg@10) |
|---|---|
| acme-products-prod | 1.0 (saturated — sparse judgments hit the ceiling) |
| corp-docs-search | 0.7305 |
| news-search-staging | 0.9060 |
| jobs-marketplace-prod | 1.0 (saturated) |

**What this says:** four overnight studies ran against four different
production-shaped scenarios. The optimizer scored each one against its
own judgment list. Some hit a metric ceiling (sample data is intentionally
small — 5 docs, 5–10 judgments); the others produced real, non-trivial
metric values. In production with rich judgments (hundreds of docs,
hundreds of ratings), every scenario produces varied trial metrics
and a clear lift story.

<!-- presenter: the framing question to ask the audience here is "how
     many trials would your team typically run when tuning a query
     pipeline by hand?" Most Fusion engineers answer 5-10. The pitch
     lands: this isn't replacing a human; it's running 50× more
     experiments than a human ever could. -->

Click into the row to open the study detail.

---

## Stop 2 — Study detail — the lift, the trials, the parameter importance

The study detail page has four panels worth narrating:

### Metric delta

Baseline vs. best on the headline metric (ndcg@10). On rich production
judgments you'd see a clear lift; on the sample data the demo seed
uses, the baseline and best are often the same value (the optimizer
correctly reports "no headroom" rather than fabricating a lift). The
fact that the system tells the truth is itself a credibility signal.

### Trials table

13 rows (1 baseline + 12 Optuna trials), sorted by `primary_metric DESC`.
The top trial is highlighted. Each row shows the trial's parameter values
+ the metric it achieved.

**What this says:** the loop is auditable. You can see every trial it ran
and exactly which parameter values produced which metric. No black box.

### Parameter importance bars

A bar chart showing how much each parameter contributed to variance in
the metric. For the acme demo study (which tunes `title_boost` +
`description_boost`), you'll typically see a near-even split
(0.46 / 0.54) — meaning both knobs were exercised by the optimizer.

**What this says:** you don't just get a winning config. You get an
explanation of *which knobs the optimizer actually leaned on* and which
ones didn't matter.

### Confidence panel

Bootstrap CI on the winner's metric. When the data shows real variance,
this tells the operator whether the lift is statistically separable;
when the data is flat (sample-data territory), this honestly reports
equivalence.

<!-- presenter: this is the panel that lands for a relevance engineer who's
     been burned by single-sample tuning. Bootstrap CI + per-query metric
     breakdown is what separates "feels better" from "demonstrably better."
     Spend 30 extra seconds here if the audience is technical. -->

---

## Stop 3 — Proposal — the ship gate

Click "View proposal" from the study detail (or open the proposals page
and find the matching row).

The proposal page shows:

### Config diff

A small, scannable before/after diff for the winning parameter values.
This is what would land in the operator's search-config repo.

### Metric delta

The same baseline → best comparison shown on the study detail, presented
in the proposal context (with delta-pct breakdown).

### Digest narrative

Two to three LLM-generated paragraphs explaining what the loop learned:
which parameters moved the needle (or which didn't, when the data is
flat), what the winning configuration says about the optimizer's
exploration, and what the operator should investigate next. This
narrative becomes the PR body.

### "Open PR" button

Clicking this opens a real pull request against the operator's configured
search-config repo on GitHub. The operator's existing CI, reviewers, and
branch protection all stay in charge of what reaches production.

**What this says:** RelyLoop is not in the production-serving path. It
proposes; the operator's existing ship discipline disposes. No surprise
config changes.

<!-- presenter: this is the single biggest unlock for a Fusion customer
     who's used to having relevance engineers write Solr config XML by
     hand. The PR-based workflow is familiar (they already do this for
     everything else); the difference is that the PR body now includes
     statistical backing instead of just a one-line "tried this, looks
     better." Pause here. Let the audience react. -->

---

## Stop 4 — Suggested followups — the loop continues

Scroll the proposal page to the "Suggested followups" panel. The digest
worker (real LLM call against the actual study data) generates the
followups. **What kinds appear depends on what the data shows** — the
LLM looks at the trial distribution and picks the most-informative next
experiment(s):

- **`narrow`** — when the optimizer found a stable winning region:
  "Tighten boost bounds around the winning value to extract the last
  few percentage points." Same template, narrower search space.
- **`widen`** — when the winner sat near a search-space boundary:
  "Test boost values further from the winner to confirm the optimum
  isn't a local maximum." Same template, wider search space.
- **`swap_template`** — when the data suggests a different query
  shape might do better: "Test whether the alternative template beats
  this one." Cross-template exploration.
- **`text`** — when no actionable change is warranted: prose
  recommending the operator rethink the rubric, judgment density, or
  query selection. No Run button (text-kind suggestions aren't
  one-click runnable).

For the acme demo study, you'll typically see a **`narrow`** card
(the 2-D search space converges to a stable region inside the
[0.5, 5.0] bounds). Cards with actionable kinds have a **"Run this
followup"** button.

**What this says:** the loop didn't stop at one winner. It analyzed
where the optimizer's curiosity remained and proposed a concrete
next-experiment. The relevance engineer goes from "tune one thing and
ship" to "continuous, automated experimentation with a steady stream
of small wins for review."

<!-- presenter: this is the moment to drop the line "the loop runs
     itself overnight." Connect it back to Stop 1's "200 trials in
     4 hours" — the next followup will run tonight, you'll have a new
     PR in tomorrow's morning standup. -->

---

## Stop 5 (optional) — Kick off a followup live

If the demo has time, click **"Run this followup"** on the swap-template
card. A modal opens, pre-filled:

- Template: the swap target (a function_score template instead of multi_match)
- Search space: LLM-suggested narrower bounds carrying the parent's winning insight forward
- Cluster / query set / judgment list: inherited from the parent
- Name: `<parent name> — followup #1 (swap_template)`

Walk through the five wizard steps with `step-next`. Submit.

The new study appears in `/studies` as **queued**. Within a few seconds
it flips to **running** and trials start accumulating.

<!-- presenter: don't wait for it to complete — that takes minutes against
     real data. Just queue it, show the studies dashboard reflecting it,
     move on. The point is already made. -->

---

## Stop 6 (optional) — Drive via chat

Open [`http://localhost:3000/chat`](http://localhost:3000/chat).

Type something operator-shaped:

> *"I'm seeing poor recall on long-tail queries against the products
> index. What should I try?"*

The agent will:

- Use `get_cluster_status` to look at the configured cluster
- Suggest creating a new judgment list against a recent query slice
- Offer to start a study with a recall-oriented metric (e.g., `recall@100`)

**What this says:** a relevance engineer doesn't need to learn a new UI to
drive the loop. Describe the problem in plain language and the agent picks
the right tools.

---

## Closing pitch

Three points to land, in order:

1. **Engine-neutral by design.** What you saw runs against Elasticsearch
   and OpenSearch today. The Fusion adapter is on the MVP3 roadmap. The
   optimization engine doesn't care which backend implements the search;
   it tunes whatever knobs the adapter exposes. Your existing Fusion
   query pipelines map directly.
2. **Real signals next release.** MVP1.5 ("Real Signals") replaces
   LLM-as-judge with UBI click/dwell data as a first-class judgment
   source. Your existing Fusion Signals capture maps directly — you
   grade studies against your users' real behavior, not an LLM's guess.
3. **Open source, self-hosted.** Apache 2.0. Run it on a laptop, run it
   on your own infra. The PR-based ship workflow keeps your existing CI
   and existing reviewers in charge of production.

---

## Where to go next

- [`tutorial-first-study.md`](tutorial-first-study.md) — full 30-min
  hands-on from `git clone` through "PR opened in GitHub"
- [`workflows-overview.md`](workflows-overview.md) — inventory of all
  30 distinct workflows the product supports
- In-app guides 01–10 (open the `/guide` page in the UI) — per-workflow
  60-second screenshot decks
- [`docs/01_architecture/`](../01_architecture/) — architecture docs:
  adapters, optimization, agent tools, apply path

<!-- presenter: if the conversation is going long, end after Stop 4 +
     Closing pitch. Stops 5 and 6 are nice-to-have, not required. The
     value prop is fully delivered by the time you reach Stop 4. -->
