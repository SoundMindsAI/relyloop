# RelyLoop — Workflows Overview

> **Audience:** Search engineers new to RelyLoop. You're comfortable with Elasticsearch / OpenSearch query DSL and the day-to-day pain of "tune a boost, redeploy, hope it's better." This guide is the map of *what RelyLoop lets you do* — every distinct workflow, what real-world problem it solves, and where to execute it (UI route, API endpoint, or worker job).
>
> **Companion docs:** [`tutorial-first-study.md`](tutorial-first-study.md) is the 10-step happy-path walkthrough. This file is the inventory — broader and more reference-shaped.

---

## The Problem RelyLoop Was Built For

A typical search-relevance team operates on a guess-and-deploy loop:

1. An exec, sales engineer, or customer complains that searches for *"laptop screen protector"* return irrelevant results.
2. A relevance engineer tweaks an analyzer, bumps a boost, restructures a `function_score`, or adds a synonym.
3. They run a handful of eyeball queries against staging, decide "that looks better," and deploy.
4. Two weeks later, a different complaint surfaces — possibly because the previous fix regressed a class of queries no one was watching.

The industry literature is blunt about this: *"Teams can't measure what they can't improve — most teams guess at solutions"* ([OSC](https://opensourceconnections.com/about-us/tools/)). Generic out-of-box relevance "is fine for demos but real-world data with domain-specific jargon, complex queries, and synonyms doesn't handle well" ([Pureinsights](https://pureinsights.com/blog/2025/top-7-elasticsearch-pitfalls-and-how-to-avoid-them/)). The default workflow is *"tweak analyzers, adjust boost factors, shuffle query logic, deploy, and hope"* ([dev.to](https://dev.to/iprithv/stop-guessing-on-search-tuning-using-opensearch-search-relevance-to-improve-results-2f0j)).

RelyLoop replaces that loop with a **measured, off-line, Git-deployed loop**: you describe what's broken in chat, the system runs thousands of trials overnight, and the winning config arrives in your inbox as a Pull Request. The tool never sits on the live search-serving path; the only thing that changes production is the operator merging the PR.

This document is the catalog of distinct things a search engineer can do with the tool **today** (MVP1, v0.1.0 — 15 features shipped as of 2026-05-14).

---

## Who Uses RelyLoop

Three personas, each with a sharply different relationship to the tool:

- **Relevance Engineer (primary user).** Runs studies, reviews digests, opens proposals. Most workflows below are written from this persona's perspective.
- **Approver.** A subset of relevance engineers (or platform engineers) with merge rights on the config repo's protected branches. **The approver never logs into RelyLoop** — they review the PR on GitHub and merge. RelyLoop has no in-tool approval surface; it delegates approval to the config repo's branch protection.
- **Viewer.** Read-only stakeholder (PMs, exec, peer engineers). In MVP1, role enforcement is conventional (no auth exists yet); explicit role gates land at MVP4.

---

## The Workflow Inventory

Workflows are grouped into six phases — roughly the order a new engineer will encounter them. Each entry lists the *problem solved*, the *primary surface* (UI route or API endpoint), and any *side effects* worth knowing.

### Phase A — First-time setup

These run once per RelyLoop deployment (or once per relevance engineer joining the team).

#### A1. Bootstrap the stack locally
- **Solves:** Getting RelyLoop running in under 5 minutes from a `git clone` with no Docker / Postgres / Redis / Elasticsearch knowledge required.
- **How:** `make up` — invokes [`scripts/install.sh`](../../scripts/install.sh), auto-generates required secrets (Postgres password, database URL), starts seven containers (Postgres, Redis, API, worker, migration init container, Elasticsearch, OpenSearch, UI dev server), and prints follow-up instructions. UI lands at `http://localhost:3000`, API at `http://localhost:8000`.
- **Verifies via:** `GET /healthz` — unauthenticated operator probe; reports per-subsystem status (`db`, `redis`, `openai`, `elasticsearch_clusters`).
- **Reference:** [`docs/03_runbooks/local-dev.md`](../03_runbooks/local-dev.md).

#### A2. Mount the LLM credential (optional but recommended)
- **Solves:** Enabling LLM-dependent features (judgment generation, digest narrative, chat agent tool dispatch). Without it, the stack still runs but those features degrade or refuse.
- **How:** Drop the key into `./secrets/openai_key` (mounted as a Docker secret). For non-OpenAI endpoints (Ollama, LM Studio, vLLM, HF TGI), set `OPENAI_BASE_URL` + `OPENAI_MODEL` in `.env`. Bare env-var `OPENAI_API_KEY=sk-...` is **not** supported — it appears in `docker inspect` and `ps`.
- **Verifies via:** API boot fires a capability probe (`/healthz` reports `openai: ok | missing_key | incapable`).
- **Reference:** [`docs/01_architecture/llm-orchestration.md`](../01_architecture/llm-orchestration.md).

#### A3. Register an Elasticsearch / OpenSearch cluster
- **Solves:** Telling RelyLoop *which engine to tune against*. A "cluster" record carries the URL, engine type, auth mode, and an adapter-validated handle to the live cluster.
- **How (UI):** [`/clusters`](../../ui/src/app/clusters/page.tsx) → "Register cluster" modal. Provide name, engine type (`elasticsearch` or `opensearch`), URL, auth kind, credentials reference.
- **How (API):** `POST /api/v1/clusters` — registration runs an immediate health probe via the adapter Protocol; rejects unreachable clusters.
- **How (bulk):** `make seed-clusters` runs [`scripts/seed_clusters.py`](../../backend/app/scripts/seed_clusters.py) to register `local-es` + `local-opensearch` for the tutorial.
- **Side effect:** Writes a `clusters` row; subsequent operations reference it by `cluster_id`.

#### A4. Register a config repo (where winning configs will be PR'd)
- **Solves:** Wiring RelyLoop to the central Git repo your CI/CD pipeline reads from. RelyLoop opens PRs here; it never deploys configs directly.
- **How (API):** `POST /api/v1/config-repos` — provide repo URL (GitHub only in MVP1), the directory path within the repo where `*.params.json` files live, and an `auth_ref` (filename under `./secrets/` holding a per-repo GitHub PAT). Optionally provides a `webhook_secret_ref` to auto-register a GitHub webhook pointing at `/webhooks/github`.
- **Side effect:** Best-effort `register_webhook` worker job; durable `webhook_registration_error` column captures failures for operator triage.
- **Reference:** [`docs/04_security/github-token-handling.md`](../04_security/github-token-handling.md) for PAT scoping + rotation.
- **Note:** This workflow has **no UI form in MVP1** — operators use `curl` or the chat agent.

#### A5. Seed sample data into Elasticsearch (tutorial only)
- **Solves:** Letting a new engineer evaluate RelyLoop end-to-end without first having to populate their own index.
- **How:** `make seed-es` loads 1,000 sample products from [`samples/products.json`](../../samples/products.json) into the `products` index.
- **Reference:** [`tutorial-first-study.md`](tutorial-first-study.md) Step 2.

---

### Phase B — Build relevance assets

These define *what you're tuning* (the query template knobs) and *what good looks like* (the judgments). They're reused across many studies.

#### B1. Define a query template
- **Solves:** Capturing the search-time query DSL as a parameterized Jinja2 template so RelyLoop can vary boosts, type weights, function scores, etc. across trials. Without this abstraction, every study would need its own ad-hoc query construction.
- **How (UI):** [`/templates`](../../ui/src/app/templates/page.tsx) → "Create template". Provide name, engine type, Jinja2 template body, and a `declared_params` map (parameter name → type).
- **How (API):** `POST /api/v1/query-templates`. The backend validates Jinja2 syntax and rejects templates whose declared params don't match the params actually referenced in the body.
- **Versioning:** Templates are immutable. To evolve a template, **fork it to v2** ([`/templates/[id]`](../../ui/src/app/templates/[id]/page.tsx) → "Fork to v{N+1}" button) — this preserves study lineage (`study.query_template_id` always points at a specific version).

#### B2. Create a query set and load queries
- **Solves:** Defining *the queries you care about being good for*. Studies score against this fixed list, so the relevance metric improvement is measured against a stable benchmark.
- **How (UI):** [`/query-sets`](../../ui/src/app/query-sets/page.tsx) → "Create query set" modal. Bind to a cluster (the queries are evaluated against that cluster's index). Optionally upload a CSV in the same modal.
- **How (API):** `POST /api/v1/query-sets` + `POST /api/v1/query-sets/{id}/queries` (accepts JSON or CSV via `Content-Type`).

#### B3. Inspect / edit / delete individual queries
- **Solves:** Maintenance of the benchmark set: removing queries that are no longer representative, fixing typos, attaching metadata for filtering.
- **How (UI):** [`/query-sets/[id]`](../../ui/src/app/query-sets/[id]/page.tsx) → `<QueriesTable>` with inline Edit / Metadata / Delete icon-buttons per row.
- **How (API):** `GET /api/v1/query-sets/{id}/queries` (cursor pagination, `?since=` filter), `PATCH .../queries/{query_id}`, `DELETE .../queries/{query_id}`. DELETE returns 409 `QUERY_HAS_JUDGMENTS` with a structured envelope listing affected judgment lists — the UI surfaces this as a Sonner toast with a "View affected judgments" action link.

#### B4. Generate judgments via LLM
- **Solves:** *"What does good look like?"* For every (query, doc) pair the queries surface, the LLM scores relevance on a 0–3 scale per the rubric. Without judgments, there's no ground truth to score trials against.
- **How (UI):** [`/query-sets/[id]`](../../ui/src/app/query-sets/[id]/page.tsx) → "Generate judgments" modal. Pick the cluster, template, and rubric.
- **How (API):** `POST /api/v1/judgments/generate` returns `202 ACCEPTED` with a `judgment_list_id`. The `generate_judgments_llm` worker job runs the actual LLM calls.
- **Side effects:** Creates a `judgment_lists` row (status=`generating`), enqueues the worker. Cost-gated by daily OpenAI budget. ~$0.01–$0.05 with `gpt-4o-mini` on the 48-query tutorial set.
- **Auto-recovery:** If the worker crashes mid-list, the boot-time sweep + the every-15-minute `resume_stuck_judgment_lists` cron re-enqueue stuck lists (capped at 24 attempts/day to prevent infinite loops). See [`feat_judgments_periodic_resume_sweep`](../00_overview/implemented_features/2026_05_14_feat_judgments_periodic_resume_sweep/).

#### B5. Import pre-curated judgments (tutorial / sideload path)
- **Solves:** Bypassing LLM generation when you already have human-labeled judgments (e.g., from Amazon ESCI, a previous tool, or hand-curation).
- **How (API):** `POST /api/v1/judgment-lists/import` — bulk-insert with strict validation (every `query_id` must exist in the query set, duplicate `(query_id, doc_id)` rejected). Sets status=`complete` immediately, no LLM call.
- **No UI surface in MVP1.**

#### B6. Review and override individual judgments
- **Solves:** The LLM gets things wrong — sometimes spectacularly. Engineers need to inspect the (query, doc, rating, LLM-reasoning) tuples and override the bad ones, *without* re-running generation.
- **How (UI):** [`/judgments/[id]`](../../ui/src/app/judgments/[id]/page.tsx) — table with a source filter (`llm` / `human`), inline override.
- **How (API):** `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` — UPSERT semantics; the human override coexists with the LLM judgment and supersedes it for scoring.

#### B7. Calibrate LLM judgments against human ground truth
- **Solves:** Quantifying *how much you can trust the LLM*. Cohen's kappa + linear-weighted kappa scores the LLM's agreement with a held-out set of human judgments.
- **How (UI):** [`/judgments/[id]`](../../ui/src/app/judgments/[id]/page.tsx) → "Calibrate" button.
- **How (API):** `POST /api/v1/judgment-lists/{id}/calibration` — requires ≥10 human-labeled pairs in the list; computes the kappa scores and persists them on the parent row.

---

### Phase C — Run the loop (the core value)

This is what RelyLoop *is*: an off-line optimization loop driven by Optuna against `ir_measures`-computed metrics.

#### C1. Create a study via the UI
- **Solves:** Codifying *"tune these parameters for this query set against this cluster"* as a structured optimization run.
- **How (UI):** [`/studies`](../../ui/src/app/studies/page.tsx) → "Create study". Pick cluster + query set + template + judgment list, define the search space (per-parameter type + bounds), set `max_trials`.
- **How (API):** `POST /api/v1/studies` — synchronously validates the search space and FKs, returns `202 ACCEPTED`, enqueues `start_study(study_id)`.
- **Side effect:** Creates `studies` row (status=`queued`), the orchestrator worker transitions it to `running` and begins sampling.

#### C2. Create a study via the chat agent
- **Solves:** Lowering the friction for "I have a relevance problem but I haven't filled out the form yet." Engineers describe the problem in natural language; the agent introspects the cluster, proposes a search space, asks for confirmation, then enqueues.
- **How (UI):** [`/chat`](../../ui/src/app/chat/page.tsx) → "New conversation". Type: *"Tune `product_search v1` against `tutorial_queries` on `local-es:products`, max 10 trials."* Watch the agent's tool calls (`get_schema`, `run_query`, `create_study`) render inline.
- **How (API):** `POST /api/v1/conversations` + `POST /api/v1/conversations/{id}/messages` (returns `text/event-stream`).
- **Side effect:** Same downstream as C1 once the agent fires `create_study`.

#### C3. Monitor a running study
- **Solves:** "Is it actually doing anything? Is it converging? Has it hit a stuck trial?"
- **How (UI):** [`/studies/[id]`](../../ui/src/app/studies/[id]/page.tsx) — header summary (status, baseline, best metric) + trials table (auto-polls every 3 seconds while running). Sort by primary metric, trial number, or `ended_at`.
- **How (API):** `GET /api/v1/studies/{id}` returns a `trials_summary` aggregation (total / complete / failed / pruned / best). `GET /api/v1/studies/{id}/trials` paginates the per-trial detail.
- **Orientation surfaces on the page:** named clickable links to the **cluster**, **query set**, **judgment list**, and **template** (`LinkedEntitiesRow`), a `Proposal: view proposal (<status>)` link once a proposal has been promoted, and `(i)` glossary tooltips on every column heading. The Guide button (bottom-right) opens the full glossary.

#### C3b. Read the Confidence panel
- **Solves:** "Is this winner statistically reliable, or did Optuna get lucky on one trial?" — and *"which queries gained, which queries lost?"*.
- **How (UI):** [`ConfidencePanel`](../../ui/src/components/studies/confidence-panel.tsx) renders on the study detail page once the study completes. Four sections:
  1. **Headline metric + 95% CI band** (bootstrap, N≥10 queries; omitted on small studies).
  2. **Per-query outcome chips** — `X Improved · Y Unchanged · Z Regressed` vs. runner-up (or baseline when present).
  3. **Queries that improved** / **Queries that regressed** — named tables with query text + winner score + comparison score + signed delta. Each capped at 5 rows.
  4. **Secondary callouts** — *runner-up gap* (robust plateau vs. sharp peak), *late-trial 1σ*, and *convergence regime* (early-and-held vs. late-rising vs. noisy).
- **How (API):** `GET /api/v1/studies/{id}` returns the full `confidence` shape inline; see [`backend/app/domain/study/confidence.py`](../../backend/app/domain/study/confidence.py).
- **Glossary:** every `(i)` icon resolves to a definition under the `confidence.*` namespace in [`ui/src/lib/glossary.ts`](../../ui/src/lib/glossary.ts).

#### C4. Cancel a study mid-flight
- **Solves:** "This isn't going anywhere — kill it and free the worker for something else."
- **How (UI):** Study detail action bar → "Cancel".
- **How (API):** `POST /api/v1/studies/{id}/cancel` (409 if not in `queued` or `running`). Within ~30s the orchestrator stops enqueuing new trials; in-flight trials complete cleanly.

#### C5. Resume a study after worker restart
- **Solves:** Worker crashes / Docker restarts shouldn't lose hours of trial state.
- **How:** Automatic. Optuna's `RDBStorage` holds trial history in Postgres; the `on_startup` hook in [`backend/workers/all.py`](../../backend/workers/all.py) sweeps running studies and enqueues `resume_study(study_id)` for each, picking up from the last completed trial.
- **No user action required** — but if you're debugging "why did my study resume?", this is the mechanism.

---

### Phase D — Review and ship the winner

The loop produces a `proposal` — a row that says *"these parameter values beat the baseline by X%"*. This phase is the human-judgment gate before anything reaches production.

#### D1. Read the digest narrative
- **Solves:** Skimmable, LLM-written summary of what the study found, what mattered, and what to investigate next — so an engineer doesn't have to manually correlate 100+ trial rows.
- **How (UI):** Study detail page renders the digest panel once the study completes.
- **How (API):** `GET /api/v1/studies/{id}/digest` (404 `DIGEST_NOT_READY` if still generating).
- **What's in it:** Top trial config, primary metric delta vs. baseline, parameter importance scores (Optuna's FanovaImportanceEvaluator), parameter importance bar chart, narrative summary, up to 5 suggested follow-up studies. See [`feat_digest_proposal`](../00_overview/implemented_features/2026_05_11_feat_digest_proposal/).

#### D2. Browse and filter the proposals queue
- **Solves:** A team running many studies needs a workflow surface where every winning config is queued for review.
- **How (UI):** [`/proposals`](../../ui/src/app/proposals/page.tsx) — filter by status (`pending` / `pr_opened` / `merged` / `rejected`), source (`chat_triggered` / `digest_triggered`), and cluster. Auto-refetches every 30s when any visible row has an open PR (so webhook-driven status updates are seen without manual reload).
- **How (API):** `GET /api/v1/proposals?status=&source=&cluster_id=&cursor=&limit=`.

#### D3. Review a proposal in detail
- **Solves:** "What exactly is this proposal changing, and is the metric improvement believable?"
- **How (UI):** [`/proposals/[id]`](../../ui/src/app/proposals/[id]/page.tsx) — side-by-side YAML diff of baseline vs. proposed params (`ConfigDiffPanel`), baseline-vs-achieved metric delta, suggested-followups panel, PR panel (4-state: pending / opening / opened / errored).
- **How (API):** `GET /api/v1/proposals/{id}` returns the proposal with inline `study_summary` + `digest` so the page renders without a waterfall.

#### D4. Open a Pull Request from a proposal
- **Solves:** The handoff from RelyLoop to production. The PR is the *only* mechanism by which a study result becomes a real config change — no auto-deploy, no in-tool approve-and-apply.
- **How (UI):** Proposal detail page → "Open PR" button.
- **How (API):** `POST /api/v1/proposals/{id}/open_pr` — returns `202 ACCEPTED`, enqueues `open_pr` worker job with a deterministic `_job_id` (Arq dedup; AC-12 from [`feat_github_pr_worker`](../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/)).
- **Side effects (worker):** Token-safe `git` via `GIT_CONFIG_*` env vars (PAT never in argv), acquires per-config-repo advisory lock, creates branch + commits `*.params.json` + opens GitHub PR + posts the parameter-importance chart as a PR comment. Persist-then-side-effect: PR is opened on GitHub first, then the proposal is marked `pr_opened` in the DB.
- **Reference:** [`docs/03_runbooks/pr-open-debugging.md`](../03_runbooks/pr-open-debugging.md).

#### D5. Track PR state (webhook + reconciliation)
- **Solves:** When the approver merges / closes the PR on GitHub, RelyLoop needs to know so dashboards reflect reality.
- **How (primary):** `POST /webhooks/github` — receives `pull_request.{closed,merged}` events, validates HMAC signature, atomically marks the proposal `merged` / `closed`.
- **How (fallback):** `reconcile_pr_state` cron (every ~5 min) selects open proposals <90 days old, polls GitHub `/pulls/{n}`, reconciles state. Catches missed webhooks.
- **Reference:** [`docs/03_runbooks/webhook-debugging.md`](../03_runbooks/webhook-debugging.md).

#### D6. Reject a proposal
- **Solves:** "The metric went up but the config change is wrong / risky / regresses queries the metric doesn't capture." Closes the proposal without opening a PR.
- **How (UI):** Proposal detail page → "Reject" dialog (shown only when status=`pending`).
- **How (API):** `POST /api/v1/proposals/{id}/reject` (409 if not pending).

#### D7. Triage suggested follow-up studies
- **Solves:** The digest often surfaces *"this study converged but only sampled the low end of `title_boost` — try expanding the range"* or *"the metric improvement is concentrated in 5 queries — split them out into a sub-study."* These belong in your backlog.
- **How:** Read the suggested-followups panel on the proposal detail page. There is no in-tool "convert to new study" button — copy the suggested search space into a new study creation form. (Could become its own workflow in a future release.)

#### D8. Manually author a proposal without a study
- **Solves:** Edge case: an engineer wants to push a hand-crafted config change through the same review-and-PR pipeline (e.g., codifying a hot-fix the loop didn't propose).
- **How (API only):** `POST /api/v1/proposals` with `study_id=NULL`, providing cluster + template + config_diff JSON. The proposal enters the same `pending → pr_opened → merged` lifecycle.
- **No UI form in MVP1** — chat agent uses this endpoint internally.

---

### Phase E — Conversational introspection and debugging

The chat agent isn't just for creating studies — it's a general-purpose introspection layer.

#### E1. Ask the agent about cluster state
- **Solves:** *"What's the schema of the products index? How many docs? Which analyzers?"* — answered without leaving RelyLoop.
- **How:** Chat → ask. Agent dispatches `get_schema` tool against the registered cluster adapter.
- **Backend:** Same `GET /api/v1/clusters/{id}/schema` endpoint the agent uses is callable directly (no UI surface).

#### E2. Ask the agent to run an ad-hoc query
- **Solves:** *"Show me the top 10 results for 'laptop screen protector' on the products index with my proposed boosts."* — sanity-check before committing to a full study.
- **How:** Chat → describe the query. Agent dispatches `run_query` against the adapter.
- **Backend:** `POST /api/v1/clusters/{id}/run_query` (30s timeout cap; no UI surface).

#### E3. Ask the agent for study status
- **Solves:** *"How's that study doing? What's the best trial so far? How long until it's done?"* — quicker than navigating to the study detail page.
- **How:** Chat → ask. Agent dispatches `get_study` and summarizes.

#### E4. Resume a past conversation
- **Solves:** Continuity. An engineer working on a relevance problem over multiple days doesn't have to re-explain context.
- **How (UI):** [`/chat`](../../ui/src/app/chat/page.tsx) → conversation list shows each past chat with a preview of the last user/assistant message + the timestamp of the last activity (added in [`chore_chat_last_message_preview`](../00_overview/implemented_features/2026_05_14_chore_chat_last_message_preview/)). Click to resume.

---

### Phase F — Operating the stack

These are operator-flavored workflows — most run automatically, but you'll need to understand them when something breaks.

#### F1. Health probe
- **Solves:** *"Is RelyLoop healthy enough that I can trust its answers?"*
- **How:** `GET /healthz` — unauthenticated, unprefixed (NOT `/api/v1/`). Runs 5 parallel subsystem probes (Postgres, Redis, OpenAI capability cache, ES connectivity, OpenSearch connectivity) with a 200ms timeout each; returns 200 or 503.

#### F2. Boot-time + cron-driven auto-recovery sweeps
- **Solves:** Worker crashes, OOM kills, or laptop restarts shouldn't permanently strand in-flight work.
- **What runs:**
  - **`on_startup`** sweeps `running` studies → enqueues `resume_study` for each.
  - **`on_startup`** sweeps `generating` judgment lists → enqueues `generate_judgments_llm` for each (with budget cap).
  - **`on_startup`** sweeps `pending` proposals lacking a digest → enqueues `generate_digest`.
  - **`reconcile_pr_state`** cron (~5 min) catches missed GitHub webhooks.
  - **`resume_stuck_judgment_lists`** cron (~15 min) re-enqueues stuck judgment generation, capped at 24/day per list.

#### F3. Rotate a per-repo GitHub PAT
- **Solves:** Token compromise, scheduled rotation, or PAT expiry without redeploying RelyLoop.
- **How:** Update the secret file at `./secrets/<config_repos.auth_ref>` and `docker compose restart api worker`. The next worker job reads the new value.
- **Reference:** [`docs/04_security/github-token-handling.md`](../04_security/github-token-handling.md) + [`pr-open-debugging.md`](../03_runbooks/pr-open-debugging.md).

#### F4. Soft-delete a cluster
- **Solves:** Decommissioning a cluster registration without losing the audit trail of studies that ran against it.
- **How (UI):** [`/clusters/[id]`](../../ui/src/app/clusters/[id]/page.tsx) action bar → "Delete" (type-the-name confirmation gate).
- **How (API):** `DELETE /api/v1/clusters/{id}` (soft delete; `deleted_at` column).

---

## Workflows available via API but not via UI in MVP1

Captured here so an external agent or `curl` user can find them:

| Capability | Endpoint |
|---|---|
| Register a config repo | `POST /api/v1/config-repos` |
| Manually author a proposal | `POST /api/v1/proposals` |
| Import pre-curated judgments | `POST /api/v1/judgment-lists/import` |
| Schema introspection | `GET /api/v1/clusters/{id}/schema` |
| Ad-hoc query against a cluster | `POST /api/v1/clusters/{id}/run_query` |
| Delete a conversation | `DELETE /api/v1/conversations/{id}` |

These are deliberate MVP1 trims — the API surface is the contract, and the UI catches up as the surfaces prove themselves through use.

---

## What RelyLoop deliberately does NOT do

Important framing for new engineers, because the negative space defines the tool as much as the positive:

- **Never sits on the live search-serving path.** All optimization is off-line against `ir_measures`. The only thing that changes production is a merged PR.
- **Never runs online A/B tests.**
- **Never trains LTR models.**
- **Never modifies cluster schema / mapping / analyzer settings.** Tuning is restricted to query-time parameters surfaced through the engine adapter.
- **Has no in-tool approval surface.** Approval is delegated to the config repo's branch protection (CODEOWNERS, required reviewers).
- **Single-tenant in MVP1.** Multi-tenancy, SSO, and role enforcement land at MVP4.

If your team needs any of the above, RelyLoop is complementary, not a replacement — the umbrella spec (`docs/00_overview/relyloop-spec.md` §4) is the canonical non-goals list.

---

## Where to go next

- **Run the tutorial:** [`tutorial-first-study.md`](tutorial-first-study.md) walks the happy path end-to-end in ~30 minutes.
- **Pick a workflow above** and try executing it against the live stack at `http://localhost:3000`.
- **Read the user stories:** [`docs/02_product/mvp1-user-stories.md`](../02_product/mvp1-user-stories.md) is the canonical narrative source — every workflow above traces back to a numbered US-N.

---

## Sources for industry framing

The "guess-and-deploy loop" framing in the opening section synthesizes commentary from:

- [Stop Guessing on Search Tuning: Using OpenSearch Search Relevance to Improve Results](https://dev.to/iprithv/stop-guessing-on-search-tuning-using-opensearch-search-relevance-to-improve-results-2f0j) — dev.to
- [Top 7 Elasticsearch Pitfalls (and How to Avoid Them)](https://pureinsights.com/blog/2025/top-7-elasticsearch-pitfalls-and-how-to-avoid-them/) — Pureinsights
- [Search Relevance Tuning Tools](https://opensourceconnections.com/about-us/tools/) — OpenSource Connections
- [From Oracle Endeca to Elasticsearch: Modernizing Enterprise Search Engineering](https://earezki.com/ai-news/2026-02-28-from-oracle-endeca-to-elasticsearch-what-10-years-in-enterprise-search-taught-me-about-modern-search-engineering/) — Dev|Journal
