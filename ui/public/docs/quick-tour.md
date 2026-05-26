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
make seed-demo
```

This seeds four realistic demo scenarios (e-commerce, knowledge base,
news, jobs) — each with its own cluster, query template, query set,
judgment list, and one completed study with a believable metric lift
(0.412 → 0.487, +18%) plus a pending proposal. Idempotent — safe to
re-run if you want to reset the demo state. Add `FORCE=1` to skip the
destructive-reseed prompt.

The **acme-products-prod** scenario is the canonical demo target —
this one's digest carries three actionable suggested followups (narrow,
widen, swap_template) so Stops 4 and 5 of this tour have "Run this
followup" buttons to click. The other three scenarios fall back to
text-kind followups (informational only).

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
<!-- presenter: if the cluster appears as 0 healthy in /healthz, the seed
     still works (it doesn't talk to ES) but the "Run this followup"
     submit at Stop 5 will fail when the new study tries to start its
     first trial. Skip Stop 5 in that case — Stops 1–4 don't depend on
     a healthy ES connection. -->

---

## Stop 1 — `/studies` — "what the loop did overnight"

Open [`http://localhost:3000/studies`](http://localhost:3000/studies).

The studies table shows the work the loop has completed. For the demo
study, the row reads:

- **Status:** completed
- **Best metric:** 0.487 (ndcg@10)
- **Created:** yesterday at 8pm
- **Completed:** this morning at 12:14am

**What this says:** an engineer kicked off the study before they went home.
Optuna ran 200 trials over four hours against the operator's real
judgment list. The winner held with a measurable lift over baseline.

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

Baseline 0.412 → best 0.487 (+18.2% on ndcg@10). Not a sliver — a real,
ship-worthy lift on a real metric.

### Trials table

200 rows, sorted by `primary_metric DESC`. The top trial is highlighted.
Each row shows the trial's parameter values + the metric it achieved.

**What this says:** the loop is auditable. You can see every trial it ran
and exactly which parameter values produced which metric. No black box.

### Parameter importance bars

A bar chart showing how much each parameter contributed to variance in
the metric. For the demo study, `title.boost` accounted for ~64%; the
rest split among `tie_breaker`, `fuzziness`, and `slop`.

**What this says:** you don't just get a winning config. You get an
explanation of *why* it won — which knobs matter and which don't.

### Confidence panel

Bootstrap CI on the winner's metric. The lift is statistically separable
from the runner-up, so the operator can trust it'll hold in production.

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

Same +18.2% lift, presented in the proposal context.

### Digest narrative

Two to three LLM-generated paragraphs explaining what the loop learned:
which parameters moved the needle, what the winning configuration says
about user intent, what the operator should watch in production after
rollout. This narrative becomes the PR body.

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

Scroll the proposal page to the "Suggested followups" panel. The seed
script populated three follow-up cards:

1. **Narrow bounds:** *"Tighten boost bounds around the winning value
   to extract the last few percentage points."* Exploitation — same
   template, narrower search space.
2. **Widen bounds:** *"Test boost values further from the winner to
   confirm the optimum isn't a local maximum."* Exploration — same
   template, wider search space.
3. **Swap template:** *"Test whether a function_score template with
   recency decay beats the multi_match winner."* Cross-template
   exploration — different query shape entirely.

Each card has a **"Run this followup"** button. One click queues a new
study with the right template + LLM-suggested bounds inherited from this
study's winner.

**What this says:** the loop didn't stop at one winner. It looked at
where the optimizer was still curious and proposed three concrete
next-experiments, each one-click. The relevance engineer goes from
"tune one thing and ship" to "continuous, automated experimentation
with a steady stream of small wins for review."

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
